import hashlib
import json
import os
import random
import re
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/test.db"
os.environ["UPLOAD_DIR"] = f"{_tmp}/uploads"
os.environ["JWT_SECRET"] = "test-secret-test-secret"
os.environ.pop("REDIS_URL", None)

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Base  # noqa: E402
from app.services.llm import set_llm  # noqa: E402

DIM = 64


class FakeLLM:
    """Deterministic stand-in for the model: hashed bag-of-words embeddings, canned generation."""

    def __init__(self):
        self.systems: list[str] = []
        self.fail_stream = False

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for t in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(t.encode()).hexdigest(), 16) % DIM] += 1.0
        return v

    async def embed(self, texts, query=False):
        return [self._vec(t) for t in texts]

    async def generate(self, prompt):
        if "durable personal facts" in prompt:
            return '["Works as a nurse"]'
        return "[]"

    async def describe_media(self, data, mime, instruction):
        return f"Transcript: the quarterly zebra report ({mime})"

    async def stream(self, system, messages):
        self.systems.append(system)
        if self.fail_stream:
            raise RuntimeError("boom")
        reply = "According to the docs [1], yes." if "<context>" in system else "Hello there."
        for w in reply.split(" "):
            yield w + " "


@pytest.fixture
def fake_llm():
    llm = FakeLLM()
    set_llm(llm)
    yield llm
    set_llm(None)


@pytest_asyncio.fixture(autouse=True)
async def _db():
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.drop_all)
        await c.run_sync(Base.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client(fake_llm):
    ip = ".".join(str(random.randint(1, 250)) for _ in range(4))  # isolate rate-limit buckets per test
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test", headers={"x-forwarded-for": ip}
    ) as c:
        yield c


async def register(client, email="a@example.com", password="password123") -> dict:
    r = await client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()


@pytest_asyncio.fixture
async def auth(client):
    tokens = await register(client)
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def parse_sse(text: str) -> list[tuple[str, object]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        ev = lines[0].removeprefix("event: ")
        events.append((ev, json.loads(lines[1].removeprefix("data: "))))
    return events
