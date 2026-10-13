import logging

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.deps import current_user, limiter
from app.models import Chunk, Document, User
from app.schemas import DocumentOut
from app.services.extract import guess_mime, validate_upload
from app.services.ingest import process_document
from app.services.storage import delete_file, save_file

log = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])
_s = get_settings()


def _enqueue_redis(doc_id: str) -> None:
    from redis import Redis
    from rq import Queue

    Queue("documents", connection=Redis.from_url(get_settings().redis_url)).enqueue(
        "app.workers.tasks.run_process_document", doc_id, job_timeout=1800
    )


async def enqueue(background: BackgroundTasks, doc_id: str) -> None:
    """Redis/RQ worker when REDIS_URL is set, otherwise in-process background task."""
    if get_settings().redis_url:
        try:
            await run_in_threadpool(_enqueue_redis, doc_id)
            return
        except Exception:
            log.exception("redis enqueue failed; processing in-process")
    background.add_task(process_document, doc_id)


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    buf = bytearray()
    while chunk := await file.read(1024 * 1024):
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(413, f"File exceeds {limit // (1024 * 1024)} MB limit")
    return bytes(buf)


@router.post("", response_model=DocumentOut, status_code=202)
@limiter.limit("20/minute")
async def upload(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    name = (file.filename or "upload").strip()[:200]
    data = await _read_limited(file, _s.max_upload_mb * 1024 * 1024)
    if not data:
        raise HTTPException(400, "Empty file")
    if err := validate_upload(name, data[:16]):
        raise HTTPException(415, err)
    mime = guess_mime(name)
    if mime == "application/octet-stream":
        mime = file.content_type or mime
    url = await save_file(name, data, mime)
    doc = Document(user_id=user.id, filename=name, mime=mime, size=len(data), storage_url=url)
    session.add(doc)
    await session.commit()
    await enqueue(background, doc.id)
    return doc


async def _get_owned(session: AsyncSession, user: User, doc_id: str) -> Document:
    doc = (
        await session.execute(select(Document).where(Document.id == doc_id, Document.user_id == user.id))
    ).scalar_one_or_none()
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


@router.get("", response_model=list[DocumentOut])
async def list_documents(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(Document).where(Document.user_id == user.id).order_by(Document.created_at.desc())
    )
    return rows.scalars().all()


@router.get("/{doc_id}", response_model=DocumentOut)
async def get_document(doc_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _get_owned(session, user, doc_id)


@router.post("/{doc_id}/reprocess", response_model=DocumentOut, status_code=202)
async def reprocess(
    doc_id: str,
    background: BackgroundTasks,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    doc = await _get_owned(session, user, doc_id)
    doc.status, doc.error = "pending", None
    await session.commit()
    await enqueue(background, doc.id)
    return doc


@router.delete("/{doc_id}", status_code=204)
async def delete_document(doc_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    doc = await _get_owned(session, user, doc_id)
    await session.execute(delete(Chunk).where(Chunk.document_id == doc.id))
    await session.delete(doc)
    await session.commit()
    await delete_file(doc.storage_url)
