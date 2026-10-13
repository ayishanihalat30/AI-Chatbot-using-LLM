# Lumen AI — multilingual, multimodal RAG chatbot

Chat in **English, Malayalam, Hindi, Tamil, Kannada, Telugu, Arabic (RTL) and French**. Ask general questions, get coding / career / learning help, and ground answers in your own **PDF, DOCX, TXT, Markdown, CSV, XLSX, PPTX, image, audio and video** files with cited sources.

| Layer | Tech |
|---|---|
| Frontend | Next.js 15 (App Router), React 19, TypeScript, Tailwind — deploy on **Vercel** |
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic — deploy on **Render** (Docker) |
| Database | PostgreSQL + **pgvector** (Neon / Supabase) |
| Queue | Redis + RQ worker (falls back to in-process tasks when `REDIS_URL` is unset) |
| Files | Vercel Blob (falls back to local disk in dev) |
| LLM | Google **Gemini** — chat, embeddings, vision/OCR, audio & video understanding |

```
Browser ──REST/SSE──▶ FastAPI ──▶ Postgres+pgvector
   (Vercel)             │  ├────▶ Redis ──▶ RQ worker ─▶ extract → chunk → embed → store
                        │  ├────▶ Vercel Blob (uploads)
                        └──┴────▶ Gemini API
```

## RAG pipeline

1. **Upload** → validated (extension allowlist, magic-byte check, size limit) → stored in Blob → document row `pending`, job queued.
2. **Extract** (worker): pypdf / python-docx / python-pptx / openpyxl / csv; **OCR** for scanned PDFs and images (vision model if `VISION_MODEL` is set � recommended for Indic scripts � otherwise local RapidOCR, which handles Latin scripts), **Whisper transcription + LLM summary** for audio and video (language auto-detected).
3. **Chunk**: paragraph-aware packing (~3000 chars, 400 overlap, heading context, page/slide metadata; sheets are chunked by row groups with headers repeated).
4. **Embed**: `paraphrase-multilingual-mpnet-base-v2` @ 768 dims (50+ languages, cross-lingual: a Malayalam question finds English text), normalised, stored in `pgvector` (HNSW index).
5. **Retrieve** (hybrid): pgvector cosine top-20 + Postgres full-text (`simple` config, language-agnostic) top-20 → **Reciprocal Rank Fusion** → LLM **reranker** → top 6.
6. **Answer**: system prompt carries language, length, style, mode (and consented memories); context is marked as data to resist prompt injection; reply streams over **SSE**; used sources are returned as **citations** (`[1]`, `[2]` → file + page + snippet).

## Features

- Secure auth: argon2 hashing, short-lived JWT access tokens, single-use rotating refresh tokens, uniform-time login.
- Per-user preferences: language, answer length (short/medium/detailed), style (balanced/friendly/professional/technical/simple); modes: general, coding, career, learning.
- **Memory is opt-in** (off by default); view, add, delete and clear everything. Nothing is extracted or injected unless enabled.
- Chat history, rename/delete, full-text **chat search** (titles and message bodies), **export** to Markdown / text / JSON.
- Background processing with status polling and retry for failed files.
- Rate limiting (Redis-backed when available), validation errors, structured JSON logs with request IDs, security headers.

## Local development

Requirements: Python 3.12, Node 22, and a chat model server � either [Ollama](https://ollama.com) (free, local: `ollama pull llama3.2`) or a hosted open-model API key (e.g. [Groq](https://console.groq.com), free tier). Docker is optional. The first document upload downloads ~1 GB of embedding weights (and Whisper weights for audio) into `MODEL_CACHE_DIR`.

### Option A — Docker (Postgres + Redis + API + worker)
```bash
cp backend/.env.example backend/.env      # set JWT_SECRET; LLM_* for your model server
docker compose up --build                  # API on http://localhost:8000
# fully local models too:  docker compose --profile local-llm up  (then: docker compose exec ollama ollama pull llama3.2,
# and set LLM_BASE_URL=http://ollama:11434/v1 in backend/.env)
cd frontend && cp .env.example .env.local && npm install && npm run dev   # http://localhost:3000
```

### Option B — no Docker (SQLite, in-process background tasks)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
uvicorn app.main:app --reload                           # tables auto-created on SQLite; uses Ollama at localhost:11434
cd ../frontend && cp .env.example .env.local && npm install && npm run dev
```
SQLite mode uses a pure-Python vector scan — fine for development; use Postgres for anything real.

### Tests
```bash
cd backend && pytest            # 31 tests: auth, isolation, RAG, extractors, streaming, limits
cd frontend && npm test && npm run lint && npm run typecheck && npm run build
```
Backend tests use a deterministic fake LLM and a mock model server, so they need no models, keys or network. `scripts/pg_smoke.py` exercises the Postgres-only retrieval SQL; CI runs it against a `pgvector` service container.

## Configuration

| Variable | Where | Purpose |
|---|---|---|
| `DATABASE_URL` | backend | Postgres URL (`postgresql://…?sslmode=require` works as given by Neon) |
| `JWT_SECRET` | backend | long random string; required in production |
| `LLM_BASE_URL`, `LLM_API_KEY`, `CHAT_MODEL` | backend + worker | OpenAI-compatible chat server (default Ollama `http://localhost:11434/v1`, `llama3.2`) |
| `FALLBACK_CHAT_MODELS`, `VISION_MODEL` | backend + worker | backup chat models; vision model for image/scan OCR |
| `EMBED_BACKEND` (`local`/`api`), `EMBED_MODEL`, `EMBED_DIM` | backend + worker | embeddings; dimension must match the DB (768) |
| `TRANSCRIBE_BACKEND` (`local`/`api`), `TRANSCRIBE_MODEL` | worker | Whisper size (`small`) or hosted model |
| `CORS_ORIGINS` | backend | comma-separated frontend origins |
| `REDIS_URL` | backend + worker | enables queue + shared rate limits |
| `BLOB_READ_WRITE_TOKEN` | backend + worker | Vercel Blob storage |
| `MAX_UPLOAD_MB`, `CHAT_MODEL`, `EMBED_MODEL` | backend | optional tuning |
| `NEXT_PUBLIC_API_URL` | frontend | backend base URL |

Secrets live only in environment variables; `.env` files are git-ignored.

## Deployment

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). API reference: [docs/API.md](docs/API.md).

## Design notes & limitations

- Refresh tokens are kept in `localStorage` and rotated on each use. This is simple for a cross-origin Vercel→Render setup; moving them to `httpOnly` cookies behind a same-origin proxy would harden against XSS.
- Uploads go browser → API → Blob (not direct-to-Blob), so each file is limited by your backend's request limits (default 100 MB).
- Reranking is done by the LLM (one extra call per question); swap `services/retrieval.py::rerank` for a cross-encoder if latency matters.
- Local OCR (RapidOCR) does not read Malayalam/Hindi/Tamil/etc.; set `VISION_MODEL` to a vision-capable open model for those. Whisper on CPU is slow for long videos (hence the worker); use `TRANSCRIBE_BACKEND=api` with a hosted Whisper for speed.
- The local embedding + Whisper models need roughly 1.5�2 GB RAM on the backend/worker host. On small hosts use `EMBED_BACKEND=api` (a provider that serves embeddings, e.g. Together/OpenRouter/Ollama) and `TRANSCRIBE_BACKEND=api`. Changing embedding models with a different dimension requires a new migration and re-embedding.
- Open models are weaker than frontier APIs, especially for Malayalam/Kannada/Telugu generation; pick the largest model your budget allows (e.g. `llama-3.3-70b-versatile`, `qwen2.5:72b`).
