"""LLM access layer. Everything goes through the LLMClient protocol so tests can use a fake."""
import asyncio
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from typing import Protocol

from app.config import get_settings


class LLMClient(Protocol):
    def stream(self, system: str, messages: list[dict]) -> AsyncIterator[str]: ...
    async def generate(self, prompt: str) -> str: ...
    async def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...
    async def describe_media(self, data: bytes, mime: str, instruction: str) -> str: ...


INLINE_LIMIT = 15 * 1024 * 1024
EMBED_BATCH = 50
RETRIES = 2  # per model; then fail over to the next model
BACKOFF = 1.0  # seconds; doubles each attempt
FIRST_TOKEN_TIMEOUT = 12  # seconds to wait for a model to start answering
log = logging.getLogger(__name__)


def _transient(e: Exception) -> bool:
    s = str(e)
    return isinstance(e, asyncio.TimeoutError) or any(k in s for k in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500 INTERNAL", "504", "overloaded"))


class GeminiClient:
    def __init__(self) -> None:
        from google import genai

        s = get_settings()
        if not s.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self._s = s
        self._embed_model = s.embed_model
        self._client = genai.Client(api_key=s.gemini_api_key)

    async def stream(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        from google.genai import types

        contents = [
            types.Content(role="model" if m["role"] == "assistant" else "user", parts=[types.Part(text=m["content"])])
            for m in messages
        ]
        started = False
        attempt = 0
        for model in self._chat_models():
            for attempt in range(RETRIES):
                try:
                    resp = await self._client.aio.models.generate_content_stream(
                        model=model,
                        contents=contents,
                        config=types.GenerateContentConfig(system_instruction=system),
                    )
                    it = resp.__aiter__()
                    while True:
                        try:
                            chunk = await asyncio.wait_for(
                                it.__anext__(), None if started else FIRST_TOKEN_TIMEOUT
                            )
                        except StopAsyncIteration:
                            break
                        if chunk.text:
                            started = True
                            yield chunk.text
                    return
                except Exception as e:
                    # Only retry if nothing has been sent to the user yet.
                    if started or not _transient(e):
                        raise
                    log.warning("Gemini %s transient error (attempt %d): %s", model, attempt + 1, str(e)[:120])
                    if attempt < RETRIES - 1:
                        await asyncio.sleep(BACKOFF * 2**attempt)
        raise RuntimeError("Gemini is busy right now. Please try again in a moment.")

    async def generate(self, prompt: str) -> str:
        last: Exception | None = None
        for model in self._chat_models():
            for attempt in range(RETRIES):
                try:
                    resp = await self._client.aio.models.generate_content(model=model, contents=prompt)
                    return resp.text or ""
                except Exception as e:
                    if not _transient(e):
                        raise
                    last = e
                    if attempt < RETRIES - 1:
                        await asyncio.sleep(BACKOFF * 2**attempt)
        raise last  # type: ignore[misc]

    def _chat_models(self) -> list[str]:
        extra = [m.strip() for m in self._s.fallback_chat_models.split(",") if m.strip()]
        return list(dict.fromkeys([self._s.chat_model, *extra]))

    async def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        from google.genai import types

        out: list[list[float]] = []
        task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"
        for i in range(0, len(texts), EMBED_BATCH):
            res = await self._embed_batch(texts[i : i + EMBED_BATCH], types, task)
            out.extend(_normalize(e.values) for e in res.embeddings)
        return out

    async def _embed_batch(self, batch, types, task):
        # Google retires model names over time; fall back through known ones and remember what works.
        candidates = [self._embed_model, "gemini-embedding-2", "gemini-embedding-001"]
        last: Exception | None = None
        for model in dict.fromkeys(candidates):
            try:
                res = await self._client.aio.models.embed_content(
                    model=model,
                    contents=batch,
                    config=types.EmbedContentConfig(task_type=task, output_dimensionality=self._s.embed_dim),
                )
                self._embed_model = model
                return res
            except Exception as e:
                if "404" not in str(e) and "NOT_FOUND" not in str(e):
                    raise
                last = e
        raise last  # type: ignore[misc]

    async def describe_media(self, data: bytes, mime: str, instruction: str) -> str:
        from google.genai import types

        if len(data) <= INLINE_LIMIT:
            part = types.Part.from_bytes(data=data, mime_type=mime)
            resp = await self._client.aio.models.generate_content(
                model=self._s.chat_model, contents=[part, instruction]
            )
            return resp.text or ""
        # Large media goes through the Files API.
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(data)
            path = tmp.name
        try:
            f = await self._client.aio.files.upload(file=path, config={"mime_type": mime})
            for _ in range(120):
                f = await self._client.aio.files.get(name=f.name)
                if f.state and f.state.name == "ACTIVE":
                    break
                if f.state and f.state.name == "FAILED":
                    raise RuntimeError("Gemini file processing failed")
                await asyncio.sleep(3)
            resp = await self._client.aio.models.generate_content(
                model=self._s.chat_model, contents=[f, instruction]
            )
            return resp.text or ""
        finally:
            os.unlink(path)


def _normalize(v: list[float]) -> list[float]:
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = GeminiClient()
    return _llm


def set_llm(client: LLMClient | None) -> None:
    """Override the process-wide client (used by tests)."""
    global _llm
    _llm = client
