"""Exercises the PostgreSQL-only retrieval path (pgvector cosine + FTS) against a migrated database.

Run in CI after `alembic upgrade head`. Uses deterministic fake embeddings, no network.
"""
import asyncio
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal, engine, is_postgres  # noqa: E402
from app.models import DIM, Chunk, Document, Preference, User  # noqa: E402
from app.services.retrieval import retrieve  # noqa: E402


class Fake:
    def vec(self, text):
        v = [0.0] * DIM
        for t in re.findall(r"\w+", text.lower()):
            v[int(hashlib.md5(t.encode()).hexdigest(), 16) % DIM] += 1.0
        return v

    async def embed(self, texts, query=False):
        return [self.vec(t) for t in texts]

    async def generate(self, prompt):
        return "[]"


async def main() -> None:
    assert is_postgres(), "DATABASE_URL must point to PostgreSQL"
    async with SessionLocal() as s:
        u = User(email="smoke@example.com", password_hash="x")
        u.preference = Preference()
        s.add(u)
        await s.flush()
        d = Document(user_id=u.id, filename="smoke.txt", mime="text/plain", size=1, storage_url="x", status="ready")
        s.add(d)
        await s.flush()
        llm = Fake()
        texts = ["zebras live in africa", "bananas are yellow fruit", "the quarterly revenue grew in Kochi"]
        for i, (t, v) in enumerate(zip(texts, await llm.embed(texts))):
            s.add(Chunk(document_id=d.id, user_id=u.id, idx=i, content=t, embedding=v))
        await s.commit()
        hits = await retrieve(s, llm, u.id, "quarterly revenue Kochi", final_k=2)
        assert hits and "Kochi" in hits[0].content, hits
        print("pgvector hybrid retrieval OK:", hits[0].content)
    await engine.dispose()


asyncio.run(main())
