from tests.conftest import register


async def test_register_login_me(client):
    await register(client)
    r = await client.post("/api/v1/auth/login", json={"email": "A@Example.com", "password": "password123"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    me = (await client.get("/api/v1/auth/me", headers=h)).json()
    assert me["email"] == "a@example.com"
    assert me["preferences"]["language"] == "en"


async def test_duplicate_email_and_bad_input(client):
    await register(client)
    r = await client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": "password123"})
    assert r.status_code == 409
    r = await client.post("/api/v1/auth/register", json={"email": "nope", "password": "short"})
    assert r.status_code == 422
    assert r.json()["errors"]


async def test_wrong_password(client):
    await register(client)
    r = await client.post("/api/v1/auth/login", json={"email": "a@example.com", "password": "wrongwrong"})
    assert r.status_code == 401


async def test_requires_auth(client):
    assert (await client.get("/api/v1/chats")).status_code == 401
    assert (await client.get("/api/v1/chats", headers={"Authorization": "Bearer junk"})).status_code == 401


async def test_refresh_rotation(client):
    tokens = await register(client)
    r1 = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r1.status_code == 200
    # old token is single-use
    r2 = await client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r2.status_code == 401
    await client.post("/api/v1/auth/logout", json={"refresh_token": r1.json()["refresh_token"]})
    r3 = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1.json()["refresh_token"]})
    assert r3.status_code == 401


async def test_rate_limit_on_login(client):
    codes = []
    for _ in range(12):
        r = await client.post("/api/v1/auth/login", json={"email": "x@example.com", "password": "whatever1"})
        codes.append(r.status_code)
    assert 429 in codes


async def test_preferences_and_memory_consent(client, auth):
    r = await client.patch(
        "/api/v1/users/me/preferences", headers=auth, json={"language": "ml", "answer_length": "short"}
    )
    assert r.json()["language"] == "ml" and r.json()["answer_length"] == "short"
    assert (await client.patch("/api/v1/users/me/preferences", headers=auth, json={"language": "xx"})).status_code == 422
    # memory is off by default -> cannot add
    assert (await client.post("/api/v1/users/me/memories", headers=auth, json={"content": "likes tea"})).status_code == 403
    await client.patch("/api/v1/users/me/preferences", headers=auth, json={"memory_enabled": True})
    m = await client.post("/api/v1/users/me/memories", headers=auth, json={"content": "likes tea"})
    assert m.status_code == 201
    assert len((await client.get("/api/v1/users/me/memories", headers=auth)).json()) == 1
    assert (await client.delete(f"/api/v1/users/me/memories/{m.json()['id']}", headers=auth)).status_code == 204


async def test_delete_account(client, auth):
    assert (await client.delete("/api/v1/users/me", headers=auth)).status_code == 204
    assert (await client.get("/api/v1/auth/me", headers=auth)).status_code == 401


async def test_healthz(client):
    assert (await client.get("/healthz")).json() == {"status": "ok"}
