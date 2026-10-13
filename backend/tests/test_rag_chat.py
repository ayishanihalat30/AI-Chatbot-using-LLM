from tests.conftest import parse_sse, register

DOC = b"# Zebra Facts\n\nThe quarterly zebra report shows revenue grew twelve percent in Kochi.\n\nUnrelated: bananas are yellow."


async def upload(client, auth, name="facts.md", data=DOC):
    r = await client.post("/api/v1/documents", headers=auth, files={"file": (name, data)})
    assert r.status_code == 202, r.text
    return r.json()


async def new_chat(client, auth):
    return (await client.post("/api/v1/chats", headers=auth, json={})).json()["id"]


async def test_upload_is_processed_in_background(client, auth):
    doc = await upload(client, auth)
    got = (await client.get(f"/api/v1/documents/{doc['id']}", headers=auth)).json()
    assert got["status"] == "ready" and got["chunk_count"] >= 1


async def test_upload_validation(client, auth):
    r = await client.post("/api/v1/documents", headers=auth, files={"file": ("evil.exe", b"MZ....")})
    assert r.status_code == 415
    r = await client.post("/api/v1/documents", headers=auth, files={"file": ("fake.pdf", b"hello")})
    assert r.status_code == 415
    r = await client.post("/api/v1/documents", headers=auth, files={"file": ("e.txt", b"")})
    assert r.status_code == 400
    r = await client.post("/api/v1/documents", files={"file": ("a.txt", b"x")})
    assert r.status_code == 401


async def test_failed_processing_is_reported(client, auth):
    doc = await upload(client, auth, "blank.txt", b"   \n  ")
    got = (await client.get(f"/api/v1/documents/{doc['id']}", headers=auth)).json()
    assert got["status"] == "failed" and "No extractable text" in got["error"]


async def test_chat_streams_grounded_answer_with_citations(client, auth, fake_llm):
    await upload(client, auth)
    await client.patch("/api/v1/users/me/preferences", headers=auth, json={"language": "fr", "answer_length": "short"})
    cid = await new_chat(client, auth)
    r = await client.post(
        f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "What did the zebra report say about Kochi?", "mode": "education"}
    )
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    names = [e for e, _ in events]
    assert names[0] == "meta" and "citations" in names and "token" in names and names[-1] == "done"
    cites = dict(events)["citations"]
    assert cites[0]["filename"] == "facts.md" and "zebra" in cites[0]["snippet"]
    # prompt reflects preferences + retrieved context
    sys = fake_llm.systems[-1]
    assert "French" in sys and "<context>" in sys and "tutor" in sys
    chat = (await client.get(f"/api/v1/chats/{cid}", headers=auth)).json()
    assert [m["role"] for m in chat["messages"]] == ["user", "assistant"]
    assert chat["messages"][1]["citations"][0]["n"] == 1
    assert chat["title"].startswith("What did the zebra")


async def test_chat_without_documents_has_no_context(client, auth, fake_llm):
    cid = await new_chat(client, auth)
    r = await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "hi"})
    assert "citations" not in [e for e, _ in parse_sse(r.text)]
    assert "<context>" not in fake_llm.systems[-1]


async def test_llm_failure_emits_error_event(client, auth, fake_llm):
    fake_llm.fail_stream = True
    cid = await new_chat(client, auth)
    r = await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "hi"})
    assert parse_sse(r.text)[-1][0] == "error"


async def test_memory_only_used_with_consent(client, auth, fake_llm):
    cid = await new_chat(client, auth)
    await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "I am a nurse"})
    assert (await client.get("/api/v1/users/me/memories", headers=auth)).json() == []  # consent off
    await client.patch("/api/v1/users/me/preferences", headers=auth, json={"memory_enabled": True})
    await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "I am a nurse"})
    assert [m["content"] for m in (await client.get("/api/v1/users/me/memories", headers=auth)).json()] == ["Works as a nurse"]
    await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "next"})
    assert "Works as a nurse" in fake_llm.systems[-1]


async def test_data_isolation_between_users(client, auth, fake_llm):
    doc = await upload(client, auth)
    cid = await new_chat(client, auth)
    other = await register(client, "b@example.com")
    h2 = {"Authorization": f"Bearer {other['access_token']}"}
    assert (await client.get(f"/api/v1/chats/{cid}", headers=h2)).status_code == 404
    assert (await client.delete(f"/api/v1/chats/{cid}", headers=h2)).status_code == 404
    assert (await client.get(f"/api/v1/documents/{doc['id']}", headers=h2)).status_code == 404
    assert (await client.get("/api/v1/documents", headers=h2)).json() == []
    # user B cannot retrieve user A's chunks, even by passing the document id
    cid2 = await new_chat(client, h2)
    r = await client.post(
        f"/api/v1/chats/{cid2}/messages", headers=h2, json={"content": "zebra Kochi", "document_ids": [doc["id"]]}
    )
    assert "citations" not in [e for e, _ in parse_sse(r.text)]


async def test_search_rename_export_delete(client, auth):
    cid = await new_chat(client, auth)
    await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "Tell me about pineapples"})
    other = await new_chat(client, auth)
    assert [c["id"] for c in (await client.get("/api/v1/chats?q=pineapple", headers=auth)).json()] == [cid]
    assert (await client.get("/api/v1/chats?q=100%25", headers=auth)).json() == []  # % is escaped, not a wildcard
    assert len((await client.get("/api/v1/chats", headers=auth)).json()) == 2
    r = await client.patch(f"/api/v1/chats/{other}", headers=auth, json={"title": "Renamed"})
    assert r.json()["title"] == "Renamed"
    for fmt, needle in (("md", "pineapples"), ("txt", "pineapples"), ("json", '"role": "assistant"')):
        e = await client.get(f"/api/v1/chats/{cid}/export?format={fmt}", headers=auth)
        assert e.status_code == 200 and needle in e.text and "attachment" in e.headers["content-disposition"]
    assert (await client.get(f"/api/v1/chats/{cid}/export?format=exe", headers=auth)).status_code == 422
    assert (await client.delete(f"/api/v1/chats/{cid}", headers=auth)).status_code == 204
    assert (await client.get(f"/api/v1/chats/{cid}", headers=auth)).status_code == 404


async def test_delete_document_removes_chunks_and_validation(client, auth):
    doc = await upload(client, auth)
    assert (await client.delete(f"/api/v1/documents/{doc['id']}", headers=auth)).status_code == 204
    assert (await client.get("/api/v1/documents", headers=auth)).json() == []
    cid = await new_chat(client, auth)
    assert (await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": ""})).status_code == 422
    assert (await client.post(f"/api/v1/chats/{cid}/messages", headers=auth, json={"content": "x", "mode": "bad"})).status_code == 422
