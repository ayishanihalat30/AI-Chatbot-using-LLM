"""Structure-aware chunking: splits on paragraphs, packs to a size budget, keeps overlap and headings."""
import re
from dataclasses import dataclass

MAX_CHARS = 3000
OVERLAP_CHARS = 400


@dataclass
class Segment:
    text: str
    page: int | None = None


@dataclass
class ChunkOut:
    text: str
    page: int | None


_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+)$")


def _split_long(paragraph: str, limit: int) -> list[str]:
    if len(paragraph) <= limit:
        return [paragraph]
    # Sentence-ish split (covers Latin, Devanagari danda, Arabic question mark etc.)
    parts = re.split(r"(?<=[.!?।؟])\s+", paragraph)
    out, cur = [], ""
    for p in parts:
        while len(p) > limit:  # no sentence breaks: hard split
            if cur:
                out.append(cur)
                cur = ""
            out.append(p[:limit])
            p = p[limit:]
        if len(cur) + len(p) + 1 > limit and cur:
            out.append(cur)
            cur = p
        else:
            cur = f"{cur} {p}".strip()
    if cur:
        out.append(cur)
    return out


def chunk_segments(
    segments: list[Segment], max_chars: int = MAX_CHARS, overlap: int = OVERLAP_CHARS
) -> list[ChunkOut]:
    chunks: list[ChunkOut] = []
    for seg in segments:
        heading = ""
        cur = ""
        for para in re.split(r"\n\s*\n", seg.text.strip()):
            para = para.strip()
            if not para:
                continue
            m = _HEADING.match(para.splitlines()[0])
            if m:
                heading = m.group(1).strip()
            for piece in _split_long(para, max_chars):
                if cur and len(cur) + len(piece) + 2 > max_chars:
                    chunks.append(ChunkOut(cur, seg.page))
                    tail = cur[-overlap:] if overlap else ""
                    # start the next chunk with context: heading + overlap tail
                    prefix = f"[{heading}] " if heading and not piece.lstrip().startswith("#") else ""
                    cur = f"{prefix}{tail}\n\n{piece}".strip() if tail else f"{prefix}{piece}"
                else:
                    cur = f"{cur}\n\n{piece}" if cur else piece
        if cur.strip():
            chunks.append(ChunkOut(cur.strip(), seg.page))
    return chunks
