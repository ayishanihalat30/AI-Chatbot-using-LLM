"""Document ingestion pipeline: load -> extract -> chunk -> embed -> store."""
import logging

from sqlalchemy import delete

from app.db import SessionLocal
from app.models import Chunk, Document
from app.services.chunking import chunk_segments
from app.services.extract import extract
from app.services.llm import LLMClient, get_llm
from app.services.storage import load_file

log = logging.getLogger(__name__)


async def process_document(doc_id: str, llm: LLMClient | None = None) -> None:
    llm = llm or get_llm()
    async with SessionLocal() as s:
        doc = await s.get(Document, doc_id)
        if not doc:
            return
        doc.status, doc.error = "processing", None
        await s.commit()
        try:
            data = await load_file(doc.storage_url)
            segments = await extract(doc.filename, data, llm)
            chunks = chunk_segments(segments)
            if not chunks:
                raise ValueError("No extractable text found in this file")
            vectors = await llm.embed([c.text for c in chunks])
            await s.execute(delete(Chunk).where(Chunk.document_id == doc.id))
            s.add_all(
                Chunk(document_id=doc.id, user_id=doc.user_id, idx=i, page=c.page, content=c.text, embedding=v)
                for i, (c, v) in enumerate(zip(chunks, vectors))
            )
            doc.chunk_count = len(chunks)
            doc.summary = chunks[0].text[:300]
            doc.status = "ready"
        except Exception as e:
            log.exception("document %s failed", doc_id)
            await s.rollback()
            doc = await s.get(Document, doc_id)
            doc.status, doc.error = "failed", str(e)[:500]
        await s.commit()
