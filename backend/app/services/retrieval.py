"""Hybrid retrieval: vector search + keyword/FTS, fused with RRF, then LLM reranking."""
import json
import math
import re
from dataclasses import dataclass

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import is_postgres
from app.models import DIM, Chunk, Document
from app.services.llm import LLMClient

CANDIDATES = 20
FINAL_K = 6
RRF_K = 60


@dataclass
class Hit:
    chunk_id: str
    document_id: str
    filename: str
    page: int | None
    content: str


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> list[str]:
    """Reciprocal Rank Fusion over ranked id lists. Returns ids best-first."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, cid in enumerate(ranking):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores, key=lambda c: scores[c], reverse=True)


def tokens(text: str) -> list[str]:
    return [t.lower() for t in re.findall(r"\w+", text) if len(t) > 1][:32]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


async def _candidates(
    s: AsyncSession, user_id: str, doc_ids: list[str] | None, query: str, qvec: list[float]
) -> tuple[list[str], list[str]]:
    base = sa.select(Chunk.id).where(Chunk.user_id == user_id)
    if doc_ids:
        base = base.where(Chunk.document_id.in_(doc_ids))
    toks = tokens(query)

    if is_postgres():
        dist = Chunk.embedding.op("<=>")(sa.cast(str(qvec), Vector(DIM)))
        vec_ids = (await s.execute(base.order_by(dist).limit(CANDIDATES))).scalars().all()
        kw_ids: list[str] = []
        if toks:
            tsq = sa.func.to_tsquery("simple", " | ".join(toks))
            tsv = sa.func.to_tsvector("simple", Chunk.content)
            rank = sa.func.ts_rank(tsv, tsq)
            kw_ids = (
                await s.execute(base.where(tsv.op("@@")(tsq)).order_by(rank.desc()).limit(CANDIDATES))
            ).scalars().all()
        return list(vec_ids), list(kw_ids)

    # Portable fallback (SQLite in tests / local dev)
    stmt = sa.select(Chunk.id, Chunk.content, Chunk.embedding).where(Chunk.user_id == user_id)
    if doc_ids:
        stmt = stmt.where(Chunk.document_id.in_(doc_ids))
    rows = (await s.execute(stmt)).all()
    vec_rank = sorted(rows, key=lambda r: _cosine(qvec, r.embedding or [0.0] * len(qvec)), reverse=True)
    kw_scored = []
    for r in rows:
        low = r.content.lower()
        score = sum(low.count(t) for t in toks)
        if score:
            kw_scored.append((score, r.id))
    kw_scored.sort(reverse=True)
    return [r.id for r in vec_rank[:CANDIDATES]], [i for _, i in kw_scored[:CANDIDATES]]


async def rerank(llm: LLMClient, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
    if len(hits) <= max(1, top_k):
        return hits  # nothing to cut, so skip the extra LLM call
    listing = "\n".join(f"[{i}] {h.content[:500]!r}" for i, h in enumerate(hits))
    prompt = (
        "Rate how useful each passage is for answering the question, from 0 (irrelevant) to 10 (directly answers).\n"
        f"Question: {query}\n\nPassages:\n{listing}\n\n"
        'Reply with ONLY a JSON array of numbers, one per passage, e.g. [3, 9, 0].'
    )
    try:
        raw = await llm.generate(prompt)
        scores = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
        if len(scores) != len(hits):
            raise ValueError("score count mismatch")
        order = sorted(range(len(hits)), key=lambda i: (-float(scores[i]), i))
        return [hits[i] for i in order][:top_k]
    except Exception:
        return hits[:top_k]  # keep RRF order if the reranker misbehaves


async def retrieve(
    s: AsyncSession,
    llm: LLMClient,
    user_id: str,
    query: str,
    doc_ids: list[str] | None = None,
    final_k: int = FINAL_K,
) -> list[Hit]:
    has_chunks = (await s.execute(sa.select(Chunk.id).where(Chunk.user_id == user_id).limit(1))).first()
    if not has_chunks:
        return []
    (qvec,) = await llm.embed([query], query=True)
    vec_ids, kw_ids = await _candidates(s, user_id, doc_ids, query, qvec)
    fused = rrf_fuse([vec_ids, kw_ids])[:CANDIDATES]
    if not fused:
        return []
    rows = (
        await s.execute(
            sa.select(Chunk, Document.filename).join(Document, Document.id == Chunk.document_id).where(Chunk.id.in_(fused))
        )
    ).all()
    by_id = {c.id: Hit(c.id, c.document_id, fn, c.page, c.content) for c, fn in rows}
    ordered = [by_id[i] for i in fused if i in by_id]
    return await rerank(llm, query, ordered, final_k)
