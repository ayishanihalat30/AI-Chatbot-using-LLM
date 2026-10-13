import json
import logging
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_settings
from app.db import SessionLocal, get_session
from app.deps import current_user, limiter
from app.models import Chat, Memory, Message, User
from app.schemas import ChatCreate, ChatDetail, ChatOut, ChatPatch, MessageIn
from app.services.llm import get_llm
from app.services.prompting import build_system_prompt
from app.services.retrieval import retrieve

log = logging.getLogger(__name__)
router = APIRouter(prefix="/chats", tags=["chats"])
_s = get_settings()
HISTORY_LIMIT = 20


async def _owned(session: AsyncSession, user: User, chat_id: str, with_messages: bool = False) -> Chat:
    stmt = select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id)
    if with_messages:
        stmt = stmt.options(selectinload(Chat.messages))
    chat = (await session.execute(stmt)).scalar_one_or_none()
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


@router.post("", response_model=ChatOut, status_code=201)
async def create_chat(body: ChatCreate, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    chat = Chat(user_id=user.id, title=(body.title or "New chat").strip() or "New chat")
    session.add(chat)
    await session.commit()
    return chat


@router.get("", response_model=list[ChatOut])
async def list_chats(
    q: str | None = Query(default=None, max_length=200),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    stmt = select(Chat).where(Chat.user_id == user.id)
    if q and q.strip():
        like = "%" + q.strip().replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_") + "%"
        in_messages = select(Message.chat_id).where(Message.content.ilike(like, escape="\\"))
        stmt = stmt.where(or_(Chat.title.ilike(like, escape="\\"), Chat.id.in_(in_messages)))
    rows = await session.execute(stmt.order_by(Chat.updated_at.desc()).limit(200))
    return rows.scalars().all()


@router.get("/{chat_id}", response_model=ChatDetail)
async def get_chat(chat_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    return await _owned(session, user, chat_id, with_messages=True)


@router.patch("/{chat_id}", response_model=ChatOut)
async def rename_chat(chat_id: str, body: ChatPatch, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    chat = await _owned(session, user, chat_id)
    chat.title = body.title.strip()
    await session.commit()
    return chat


@router.delete("/{chat_id}", status_code=204)
async def delete_chat(chat_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    chat = await _owned(session, user, chat_id, with_messages=True)
    await session.delete(chat)
    await session.commit()


@router.get("/{chat_id}/export")
async def export_chat(
    chat_id: str,
    format: str = Query(default="md", pattern="^(md|json|txt)$"),
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    chat = await _owned(session, user, chat_id, with_messages=True)
    slug = re.sub(r"[^\w-]+", "-", chat.title, flags=re.UNICODE).strip("-")[:50] or "chat"
    if format == "json":
        body = json.dumps(
            {
                "title": chat.title,
                "created_at": chat.created_at.isoformat(),
                "messages": [
                    {"role": m.role, "content": m.content, "citations": m.citations, "created_at": m.created_at.isoformat()}
                    for m in chat.messages
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        media = "application/json"
    else:
        lines = [f"# {chat.title}\n"] if format == "md" else [chat.title, ""]
        for m in chat.messages:
            who = "You" if m.role == "user" else "Assistant"
            lines.append(f"**{who}:**\n\n{m.content}\n" if format == "md" else f"{who}: {m.content}\n")
            for c in m.citations or []:
                lines.append(f"- [{c['n']}] {c['filename']}" + (f", p.{c['page']}" if c.get("page") else ""))
        body = "\n".join(lines)
        media = "text/markdown" if format == "md" else "text/plain"
    return Response(
        body.encode("utf-8"),
        media_type=f"{media}; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.{format}"'},
    )


def sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _remember(user_id: str, user_text: str, llm) -> None:
    """Consent-gated: only called when the user has enabled memory. Stores durable facts only."""
    prompt = (
        "From the user message below, extract up to 2 durable personal facts or preferences worth remembering "
        "for future chats (e.g. their profession, goals, tools they use). Ignore anything sensitive (health, "
        "finances, passwords, IDs) and one-off requests. Reply ONLY with a JSON array of short strings, "
        f"or [] if none.\n\nMessage: {user_text[:2000]}"
    )
    try:
        raw = await llm.generate(prompt)
        facts = json.loads(re.search(r"\[.*\]", raw, re.S).group(0))
    except Exception:
        return
    async with SessionLocal() as s:
        existing = {m.lower() for m in (await s.execute(select(Memory.content).where(Memory.user_id == user_id))).scalars()}
        for f in facts[:2]:
            if isinstance(f, str) and 3 < len(f) <= 300 and f.lower() not in existing and len(existing) < 50:
                s.add(Memory(user_id=user_id, content=f.strip()))
                existing.add(f.lower())
        await s.commit()


@router.post("/{chat_id}/messages")
@limiter.limit(_s.rate_limit_chat)
async def send_message(
    request: Request,
    chat_id: str,
    body: MessageIn,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    await _owned(session, user, chat_id)
    pref = user.preference
    user_id = user.id

    async def gen() -> AsyncIterator[str]:
        try:
            llm = get_llm()
        except Exception as e:
            log.error("LLM unavailable: %s", e)
            yield sse("error", {"message": "AI service is not configured (missing or invalid GEMINI_API_KEY)."})
            return
        async with SessionLocal() as s:
            chat = await s.get(Chat, chat_id)
            s.add(Message(chat_id=chat_id, role="user", content=body.content))
            if chat.title == "New chat":
                chat.title = body.content.strip().replace("\n", " ")[:60]
            await s.commit()
            history_rows = (
                await s.execute(
                    select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at.desc()).limit(HISTORY_LIMIT)
                )
            ).scalars().all()
            history = [{"role": m.role, "content": m.content} for m in reversed(history_rows)]
            memories = []
            if pref.memory_enabled:
                memories = list(
                    (await s.execute(select(Memory.content).where(Memory.user_id == user_id).order_by(Memory.created_at))).scalars()
                )
            try:
                hits = await retrieve(s, llm, user_id, body.content, body.document_ids)
            except Exception:
                log.exception("retrieval failed; continuing without context")
                hits = []
            citations = [
                {"n": i, "document_id": h.document_id, "filename": h.filename, "page": h.page, "snippet": h.content[:300]}
                for i, h in enumerate(hits, 1)
            ]
            yield sse("meta", {"chat_id": chat_id, "title": chat.title})
            if citations:
                yield sse("citations", citations)
            system = build_system_prompt(pref.language, pref.answer_length, pref.answer_style, body.mode, memories, hits)
            answer = ""
            try:
                async for tok in llm.stream(system, history):
                    answer += tok
                    yield sse("token", tok)
            except Exception as e:
                log.exception("generation failed")
                yield sse("error", {"message": f"The AI service failed to respond: {str(e)[:200]}"})
                if not answer:
                    return
            used = [c for c in citations if f"[{c['n']}]" in answer] or (citations if answer else [])
            msg = Message(chat_id=chat_id, role="assistant", content=answer, citations=used or None)
            s.add(msg)
            await s.commit()
            yield sse("done", {"message_id": msg.id, "citations": used})
        if pref.memory_enabled:
            await _remember(user_id, body.content, llm)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
