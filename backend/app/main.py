import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import text

from app.api import auth, chats, documents, users
from app.config import LANGUAGES, get_settings
from app.db import engine, is_postgres
from app.deps import limiter
from app.logging_conf import request_id_var, setup_logging
from app.models import Base

setup_logging()
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not is_postgres():  # dev/test convenience; Postgres uses Alembic migrations
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


s = get_settings()
app = FastAPI(title="Multilingual RAG Chatbot API", version="1.0.0", lifespan=lifespan,
              docs_url=None if s.is_prod else "/docs", redoc_url=None, openapi_url=None if s.is_prod else "/openapi.json")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=s.cors_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Content-Disposition"],
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
    request_id_var.set(rid)
    start = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    response.headers["X-Content-Type-Options"] = "nosniff"
    log.info("%s %s -> %s (%.0f ms)", request.method, request.url.path, response.status_code, (time.perf_counter() - start) * 1000)
    return response


@app.exception_handler(RequestValidationError)
async def validation_handler(_: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": "Validation failed", "errors": errors}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse({"detail": "Internal server error", "request_id": request_id_var.get()}, status_code=500)


@app.get("/healthz", tags=["health"])
@limiter.exempt
async def healthz():
    try:
        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse({"status": "degraded"}, status_code=503)
    return {"status": "ok"}


@app.get("/api/v1/languages", tags=["meta"])
async def languages():
    return LANGUAGES


for r in (auth.router, users.router, chats.router, documents.router):
    app.include_router(r, prefix="/api/v1")
