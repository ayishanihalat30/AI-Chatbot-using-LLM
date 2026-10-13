from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.deps import current_user
from app.models import Memory, User
from app.schemas import MemoryIn, MemoryOut, PreferenceIn, PreferenceOut

router = APIRouter(prefix="/users/me", tags=["users"])
MAX_MEMORIES = 50


@router.get("/preferences", response_model=PreferenceOut)
async def get_prefs(user: User = Depends(current_user)):
    return user.preference


@router.patch("/preferences", response_model=PreferenceOut)
async def update_prefs(body: PreferenceIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    pref = await session.merge(user.preference)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(pref, k, v)
    await session.commit()
    return pref


@router.get("/memories", response_model=list[MemoryOut])
async def list_memories(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    rows = await session.execute(select(Memory).where(Memory.user_id == user.id).order_by(Memory.created_at))
    return rows.scalars().all()


@router.post("/memories", response_model=MemoryOut, status_code=201)
async def add_memory(body: MemoryIn, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    if not user.preference.memory_enabled:
        raise HTTPException(403, "Enable memory in settings first")
    count = (await session.execute(select(func.count()).select_from(Memory).where(Memory.user_id == user.id))).scalar_one()
    if count >= MAX_MEMORIES:
        raise HTTPException(409, "Memory limit reached")
    m = Memory(user_id=user.id, content=body.content.strip())
    session.add(m)
    await session.commit()
    return m


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    res = await session.execute(delete(Memory).where(Memory.id == memory_id, Memory.user_id == user.id))
    if not res.rowcount:
        raise HTTPException(404, "Memory not found")
    await session.commit()


@router.delete("/memories", status_code=204)
async def clear_memories(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    await session.execute(delete(Memory).where(Memory.user_id == user.id))
    await session.commit()


@router.delete("", status_code=204)
async def delete_account(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    from app.models import Chat, Chunk, Document, Message, Preference, RefreshToken
    from app.services.storage import delete_file

    urls = (await session.execute(select(Document.storage_url).where(Document.user_id == user.id))).scalars().all()
    for u in urls:
        await delete_file(u)
    chat_ids = select(Chat.id).where(Chat.user_id == user.id)
    await session.execute(delete(Message).where(Message.chat_id.in_(chat_ids)))
    await session.execute(delete(Chunk).where(Chunk.user_id == user.id))
    for model in (Document, Chat, Memory, RefreshToken):
        await session.execute(delete(model).where(model.user_id == user.id))
    await session.execute(delete(Preference).where(Preference.user_id == user.id))
    await session.execute(delete(User).where(User.id == user.id))
    await session.commit()
