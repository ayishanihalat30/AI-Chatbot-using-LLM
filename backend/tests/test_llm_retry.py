import pytest
from app.services import llm as llm_mod


class _Models:
    def __init__(self, fail_times):
        self.fail_times = fail_times
        self.calls = 0

    async def generate_content(self, model, contents):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("503 UNAVAILABLE. high demand")

        class R:
            text = "ok"

        return R()


def _client(models):
    c = llm_mod.GeminiClient.__new__(llm_mod.GeminiClient)
    from app.config import get_settings

    c._s = get_settings()
    c._client = type("C", (), {"aio": type("A", (), {"models": models})()})()
    return c


async def test_generate_retries_transient_errors(monkeypatch):
    monkeypatch.setattr(llm_mod, "BACKOFF", 0)
    m = _Models(fail_times=2)
    assert await _client(m).generate("hi") == "ok"
    assert m.calls == 3


async def test_generate_gives_up_and_non_transient_raises(monkeypatch):
    monkeypatch.setattr(llm_mod, "BACKOFF", 0)
    with pytest.raises(RuntimeError):
        await _client(_Models(fail_times=99)).generate("hi")

    class Bad(_Models):
        async def generate_content(self, model, contents):
            self.calls += 1
            raise RuntimeError("404 NOT_FOUND")

    b = Bad(0)
    with pytest.raises(RuntimeError):
        await _client(b).generate("hi")
    assert b.calls == 1
