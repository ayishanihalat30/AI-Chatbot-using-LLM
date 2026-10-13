"""LLM access layer built on open-source models.

* Chat / vision: any OpenAI-compatible server (Ollama locally, or Groq / Together / OpenRouter / vLLM hosted).
* Embeddings: local multilingual model via fastembed (ONNX), or the server's /embeddings endpoint.
* Audio / video: faster-whisper (local) or the server's /audio/transcriptions endpoint.
* OCR: a vision model when configured (best for Indic scripts), else RapidOCR (local, Latin scripts).

Everything goes through the LLMClient protocol so tests can use a fake.
"""
import asyncio
import base64
import io
import json
import logging
import os
import tempfile
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

RETRIES = 2  # per model; then fail over to the next model
BACKOFF = 1.0  # seconds; doubles each attempt
FIRST_TOKEN_TIMEOUT = 60  # local models can be slow to load; hosted ones answer in ~1s
EMBED_BATCH = 32
MAX_OCR_PAGES = 30


class LLMClient(Protocol):
    def stream(self, system: str, messages: list[dict]) -> AsyncIterator[str]: ...
    async def generate(self, prompt: str) -> str: ...
    async def embed(self, texts: list[str], query: bool = False) -> list[list[float]]: ...
    async def describe_media(self, data: bytes, mime: str, instruction: str) -> str: ...


def _transient(e: Exception) -> bool:
    if isinstance(e, (asyncio.TimeoutError, httpx.TransportError)):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code in (408, 429, 500, 502, 503, 504)
    return False


def _reading_order(boxes: list) -> str:
    """OCR returns unordered boxes [[4 corner points], text, score]; rebuild lines top-to-bottom, left-to-right."""
    items = []
    for pts, text, *_ in boxes:
        ys = [p[1] for p in pts]
        xs = [p[0] for p in pts]
        items.append((sum(ys) / 4, max(ys) - min(ys), min(xs), text))
    items.sort()
    lines: list[list[tuple[float, str]]] = []
    last_cy = last_h = None
    for cy, h, x, text in items:
        if last_cy is not None and abs(cy - last_cy) <= 0.6 * max(h, last_h or h):
            lines[-1].append((x, text))
        else:
            lines.append([(x, text)])
        last_cy, last_h = cy, h
    return "\n".join(" ".join(t for _, t in sorted(line)) for line in lines)


def _normalize(v: list[float]) -> list[float]:
    n = sum(x * x for x in v) ** 0.5 or 1.0
    return [x / n for x in v]


class OpenSourceClient:
    def __init__(self) -> None:
        self._s = get_settings()
        headers = {"Content-Type": "application/json"}
        if self._s.llm_api_key:
            headers["Authorization"] = f"Bearer {self._s.llm_api_key}"
        self._http = httpx.AsyncClient(
            base_url=self._s.llm_base_url.rstrip("/"), headers=headers, timeout=httpx.Timeout(300, connect=10)
        )
        self._embedder = None
        self._whisper = None
        self._ocr = None

    # ---- chat ---------------------------------------------------------------------------------

    def _chat_models(self) -> list[str]:
        extra = [m.strip() for m in self._s.fallback_chat_models.split(",") if m.strip()]
        return list(dict.fromkeys([self._s.chat_model, *extra]))

    async def stream(self, system: str, messages: list[dict]) -> AsyncIterator[str]:
        payload_msgs = [{"role": "system", "content": system}, *messages]
        started = False
        for model in self._chat_models():
            for attempt in range(RETRIES):
                try:
                    async with self._http.stream(
                        "POST", "/chat/completions", json={"model": model, "messages": payload_msgs, "stream": True}
                    ) as r:
                        if r.status_code >= 400:
                            await r.aread()
                            r.raise_for_status()
                        lines = r.aiter_lines().__aiter__()
                        while True:
                            try:
                                line = await asyncio.wait_for(
                                    lines.__anext__(), None if started else FIRST_TOKEN_TIMEOUT
                                )
                            except StopAsyncIteration:
                                break
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                delta = json.loads(data)["choices"][0]["delta"].get("content")
                            except (KeyError, IndexError, json.JSONDecodeError):
                                continue
                            if delta:
                                started = True
                                yield delta
                    return
                except Exception as e:
                    if started or not _transient(e):
                        raise
                    log.warning("LLM %s transient error (attempt %d): %s", model, attempt + 1, str(e)[:120])
                    if attempt < RETRIES - 1:
                        await asyncio.sleep(BACKOFF * 2**attempt)
        raise RuntimeError("The model server is busy or unreachable right now. Please try again in a moment.")

    async def generate(self, prompt: str) -> str:
        return await self._complete([{"role": "user", "content": prompt}])

    async def _complete(self, messages: list[dict], model: str | None = None) -> str:
        last: Exception | None = None
        for m in [model] if model else self._chat_models():
            for attempt in range(RETRIES):
                try:
                    r = await self._http.post("/chat/completions", json={"model": m, "messages": messages})
                    r.raise_for_status()
                    return r.json()["choices"][0]["message"]["content"] or ""
                except Exception as e:
                    if not _transient(e):
                        raise
                    last = e
                    if attempt < RETRIES - 1:
                        await asyncio.sleep(BACKOFF * 2**attempt)
        raise last  # type: ignore[misc]

    # ---- embeddings -----------------------------------------------------------------------------

    async def embed(self, texts: list[str], query: bool = False) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH):
            batch = texts[i : i + EMBED_BATCH]
            vecs = await (self._embed_api(batch) if self._s.embed_backend == "api" else self._embed_local(batch))
            out.extend(_normalize(v) for v in vecs)
        if out and len(out[0]) != self._s.embed_dim:
            raise RuntimeError(
                f"Embedding model returns {len(out[0])} dims but EMBED_DIM={self._s.embed_dim}. "
                "The database vector size must match the model."
            )
        return out

    async def _embed_local(self, batch: list[str]) -> list[list[float]]:
        def run() -> list[list[float]]:
            if self._embedder is None:
                from fastembed import TextEmbedding

                self._embedder = TextEmbedding(model_name=self._s.embed_model, cache_dir=self._s.model_cache_dir)
            return [list(map(float, v)) for v in self._embedder.embed(batch)]

        return await asyncio.to_thread(run)

    async def _embed_api(self, batch: list[str]) -> list[list[float]]:
        r = await self._http.post("/embeddings", json={"model": self._s.embed_model, "input": batch})
        r.raise_for_status()
        return [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]

    # ---- media ----------------------------------------------------------------------------------

    async def describe_media(self, data: bytes, mime: str, instruction: str) -> str:
        if mime.startswith(("audio/", "video/")):
            return await self._transcribe_and_summarise(data, mime)
        if mime == "application/pdf":
            return await self._ocr_pdf(data)
        if mime.startswith("image/"):
            return await self._read_image(data, mime)
        raise ValueError(f"Unsupported media type: {mime}")

    async def _transcribe_and_summarise(self, data: bytes, mime: str) -> str:
        text = await (self._transcribe_api(data, mime) if self._s.transcribe_backend == "api" else self._transcribe_local(data))
        if not text.strip():
            return ""
        summary = ""
        try:
            summary = await self._complete(
                [
                    {
                        "role": "user",
                        "content": "Summarise this transcript in the language it is spoken in: a short summary then "
                        f"3-6 key points.\n\nTranscript:\n{text[:12000]}",
                    }
                ]
            )
        except Exception:
            log.exception("summary failed; storing transcript only")
        return f"Transcript:\n{text}" + (f"\n\nSummary:\n{summary}" if summary else "")

    async def _transcribe_local(self, data: bytes) -> str:
        def run() -> str:
            if self._whisper is None:
                from faster_whisper import WhisperModel

                self._whisper = WhisperModel(
                    self._s.transcribe_model, device="auto", compute_type="int8", download_root=self._s.model_cache_dir
                )
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(data)
                path = tmp.name
            try:
                segments, _info = self._whisper.transcribe(path, vad_filter=True)
                lines = []
                for s in segments:  # lazily decoded; iterate fully
                    t = s.text.strip()
                    if t:
                        lines.append(f"[{int(s.start) // 60:02d}:{int(s.start) % 60:02d}] {t}")
                return "\n".join(lines)
            finally:
                os.unlink(path)

        return await asyncio.to_thread(run)

    async def _transcribe_api(self, data: bytes, mime: str) -> str:
        ext = mime.split("/")[-1].replace("mpeg", "mp3").replace("quicktime", "mov")
        headers = {k: v for k, v in self._http.headers.items() if k.lower() != "content-type"}
        r = await self._http.post(
            "/audio/transcriptions",
            data={"model": self._s.transcribe_model},
            files={"file": (f"audio.{ext}", data, mime)},
            headers=headers,
        )
        r.raise_for_status()
        return r.json().get("text", "")

    async def _read_image(self, data: bytes, mime: str) -> str:
        parts = []
        if self._s.vision_model:
            b64 = base64.b64encode(data).decode()
            try:
                parts.append(
                    await self._complete(
                        [
                            {
                                "role": "user",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": "Extract any visible text verbatim (OCR), then describe the image in "
                                        "detail. Format: 'Text:' section followed by 'Description:' section.",
                                    },
                                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                                ],
                            }
                        ],
                        model=self._s.vision_model,
                    )
                )
            except Exception:
                log.exception("vision model failed; falling back to local OCR")
        if not parts:
            text = await asyncio.to_thread(self._rapid_ocr, data)
            if text.strip():
                parts.append(f"Text:\n{text}")
        return "\n\n".join(parts)

    def _rapid_ocr(self, png_or_jpeg: bytes) -> str:
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        result, _ = self._ocr(png_or_jpeg)
        return _reading_order(result or [])

    async def _ocr_pdf(self, data: bytes) -> str:
        def render() -> list[bytes]:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(data)
            pages = []
            for i in range(min(len(pdf), MAX_OCR_PAGES)):
                buf = io.BytesIO()
                pdf[i].render(scale=2).to_pil().save(buf, format="PNG")
                pages.append(buf.getvalue())
            return pages

        out = []
        for n, png in enumerate(await asyncio.to_thread(render), 1):
            text = await self._read_image(png, "image/png")
            if text.strip():
                out.append(f"## Page {n}\n\n{text}")
        return "\n\n".join(out)


_llm: LLMClient | None = None


def get_llm() -> LLMClient:
    global _llm
    if _llm is None:
        _llm = OpenSourceClient()
    return _llm


def set_llm(client: LLMClient | None) -> None:
    """Override the process-wide client (used by tests)."""
    global _llm
    _llm = client
