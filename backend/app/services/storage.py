"""Object storage: Vercel Blob when a token is configured, otherwise local disk (dev)."""
import uuid
from pathlib import Path

import httpx

from app.config import get_settings

BLOB_API = "https://blob.vercel-storage.com"


async def save_file(filename: str, data: bytes, content_type: str) -> str:
    s = get_settings()
    safe = Path(filename).name.replace(" ", "_")
    if s.blob_read_write_token:
        async with httpx.AsyncClient(timeout=120) as c:
            r = await c.put(
                f"{BLOB_API}/uploads/{safe}",
                content=data,
                headers={
                    "authorization": f"Bearer {s.blob_read_write_token}",
                    "x-api-version": "7",
                    "x-add-random-suffix": "1",
                    "x-content-type": content_type,
                },
            )
            r.raise_for_status()
            return r.json()["url"]
    d = Path(s.upload_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{uuid.uuid4().hex}_{safe}"
    path.write_bytes(data)
    return f"file://{path.resolve().as_posix()}"


async def load_file(url: str) -> bytes:
    if url.startswith("file://"):
        return Path(url[len("file://"):]).read_bytes()
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as c:
        r = await c.get(url)
        r.raise_for_status()
        return r.content


async def delete_file(url: str) -> None:
    s = get_settings()
    try:
        if url.startswith("file://"):
            Path(url[len("file://"):]).unlink(missing_ok=True)
        elif s.blob_read_write_token:
            async with httpx.AsyncClient(timeout=30) as c:
                await c.post(
                    f"{BLOB_API}/delete",
                    json={"urls": [url]},
                    headers={"authorization": f"Bearer {s.blob_read_write_token}", "x-api-version": "7"},
                )
    except Exception:  # best effort cleanup
        pass
