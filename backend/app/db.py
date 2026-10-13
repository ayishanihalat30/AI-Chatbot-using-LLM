from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings


def normalize_url(url: str) -> tuple[str, dict]:
    """Turn a provider URL (Neon/Supabase style) into an asyncpg-compatible one."""
    args: dict = {}
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgresql+asyncpg://") and "?" in url:
        base, query = url.split("?", 1)
        kept = []
        for part in query.split("&"):
            if part.startswith("sslmode="):
                if part.split("=", 1)[1] != "disable":
                    args["ssl"] = True
            elif part.startswith("channel_binding="):
                continue
            else:
                kept.append(part)
        url = base + ("?" + "&".join(kept) if kept else "")
    return url, args


_url, _args = normalize_url(get_settings().database_url)
engine = create_async_engine(_url, connect_args=_args, pool_pre_ping=True)

if engine.dialect.name == "postgresql":
    from pgvector.asyncpg import register_vector

    @event.listens_for(engine.sync_engine, "connect")
    def _register(dbapi_conn, _):  # pragma: no cover - needs postgres
        dbapi_conn.run_async(register_vector)

SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


def is_postgres() -> bool:
    return engine.dialect.name == "postgresql"


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
