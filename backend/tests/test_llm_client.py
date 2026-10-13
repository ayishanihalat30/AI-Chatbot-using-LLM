import json

import httpx
import pytest

from app.services import llm as llm_mod


def sse(*tokens: str) -> str:
    lines = [f"data: {json.dumps({'choices': [{'delta': {'content': t}}]})}\n\n" for t in tokens]
    return "".join(lines) + "data: [DONE]\n\n"


def make_client(handler, **overrides):
    c = llm_mod.OpenSourceClient()
    for k, v in overrides.items():
        setattr(c._s, k, v)
    c._http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://llm.test/v1")
    return c


async def collect(c, system="s", msgs=None):
    return "".join([t async for t in c.stream(system, msgs or [{"role": "user", "content": "hi"}])])


async def test_stream_parses_openai_sse_and_sends_system_prompt():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, text=sse("Hel", "lo ", "നമസ്കാരം"))

    out = await collect(make_client(handler), system="be nice")
    assert out == "Hello നമസ്കാരം"
    assert seen["body"]["stream"] is True
    assert seen["body"]["messages"][0] == {"role": "system", "content": "be nice"}


async def test_retries_then_fails_over_to_next_model(monkeypatch):
    monkeypatch.setattr(llm_mod, "BACKOFF", 0)
    tried = []

    def handler(req):
        model = json.loads(req.content)["model"]
        tried.append(model)
        if model == "primary":
            return httpx.Response(503, text="busy")
        return httpx.Response(200, text=sse("ok"))

    c = make_client(handler, chat_model="primary", fallback_chat_models="backup")
    assert await collect(c) == "ok"
    assert tried == ["primary", "primary", "backup"]


async def test_non_transient_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(llm_mod, "BACKOFF", 0)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404, text="model not found")

    with pytest.raises(httpx.HTTPStatusError):
        await collect(make_client(handler))
    assert len(calls) == 1


async def test_everything_down_raises_friendly_error(monkeypatch):
    monkeypatch.setattr(llm_mod, "BACKOFF", 0)
    with pytest.raises(RuntimeError, match="busy or unreachable"):
        await collect(make_client(lambda r: httpx.Response(503)))


async def test_generate_returns_message_content():
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "[1, 2]"}}]})

    assert await make_client(handler).generate("rate") == "[1, 2]"


async def test_api_embeddings_are_normalised_and_dim_checked():
    def handler(req):
        body = json.loads(req.content)
        data = [{"index": i, "embedding": [3.0, 4.0] + [0.0] * 766} for i in range(len(body["input"]))]
        return httpx.Response(200, json={"data": data[::-1]})

    c = make_client(handler, embed_backend="api")
    (v,) = await c.embed(["x"])
    assert len(v) == 768 and abs(v[0] - 0.6) < 1e-9 and abs(v[1] - 0.8) < 1e-9

    bad = make_client(lambda r: httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0]}]}), embed_backend="api")
    with pytest.raises(RuntimeError, match="dims"):
        await bad.embed(["x"])


async def test_audio_is_transcribed_then_summarised():
    def handler(req):
        if req.url.path.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": "[00:01] revenue grew"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "Revenue grew."}}]})

    c = make_client(handler, transcribe_backend="api")
    out = await c.describe_media(b"RIFFxxxx", "audio/wav", "")
    assert "Transcript:" in out and "revenue grew" in out and "Summary:\nRevenue grew." in out


async def test_image_uses_vision_model_when_configured():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "Text: STOP\n\nDescription: a sign"}}]})

    c = make_client(handler, vision_model="vision-x")
    out = await c.describe_media(b"\x89PNGdata", "image/png", "")
    assert "STOP" in out
    assert seen["body"]["model"] == "vision-x"
    content = seen["body"]["messages"][0]["content"]
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_unsupported_media_rejected():
    with pytest.raises(ValueError):
        await make_client(lambda r: httpx.Response(200)).describe_media(b"x", "application/zip", "")


def test_reading_order_rebuilds_lines_from_unordered_boxes():
    def box(x, y, text):
        return [[[x, y], [x + 80, y], [x + 80, y + 20], [x, y + 20]], text, 0.9]

    boxes = [box(200, 100, "world"), box(10, 10, "Hello"), box(10, 100, "Second"), box(110, 12, "there")]
    assert llm_mod._reading_order(boxes) == "Hello there\nSecond world"
