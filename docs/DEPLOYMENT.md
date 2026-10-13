# Deployment guide

Order: **Database → Redis/Backend (Render) → Frontend (Vercel) → CORS → GitHub secrets**.

## 1. PostgreSQL + pgvector (Neon)
1. Create a Neon project (any region near your backend). pgvector is available out of the box.
2. Copy the connection string (`postgresql://user:pass@host/db?sslmode=require`) — this is `DATABASE_URL`.
3. Migrations run automatically on backend start (`alembic upgrade head` creates the `vector` extension, tables, HNSW and GIN indexes).

(Supabase works the same: use the *session pooler* connection string.)

## 2. Chat model server (open-source models)
Pick one:
- **Hosted (simplest for a public app):** [Groq](https://console.groq.com) free tier. Set `LLM_BASE_URL=https://api.groq.com/openai/v1`, `LLM_API_KEY=<key>`, `CHAT_MODEL=llama-3.3-70b-versatile`, `FALLBACK_CHAT_MODELS=llama-3.1-8b-instant`, `VISION_MODEL=meta-llama/llama-4-scout-17b-16e-instruct`, and for audio `TRANSCRIBE_BACKEND=api`, `TRANSCRIBE_MODEL=whisper-large-v3-turbo`. (Together AI and OpenRouter work the same way; model names differ.)
- **Self-hosted:** run Ollama or vLLM on a GPU/VPS and set `LLM_BASE_URL` to it (put it behind HTTPS and an API key).

Embeddings stay local by default (no key). Groq does not serve embeddings; if your backend host has under ~2 GB RAM, use a provider that does and set `EMBED_BACKEND=api` + `EMBED_MODEL` (output must be 768 dims).

## 3. Vercel Blob (file storage)
In the Vercel dashboard: **Storage → Create → Blob**, connect it to any project, and copy `BLOB_READ_WRITE_TOKEN`. (Without it the backend stores files on local disk, which is ephemeral on Render and not shared with the worker — always set it in production.)

## 4. Backend + worker on Render
1. Push this repo to GitHub.
2. Render → **New → Blueprint** → pick the repo. `render.yaml` creates the API (web), worker, and a Redis (Key Value) instance.
3. Fill the prompted secrets: `DATABASE_URL`, `LLM_BASE_URL`, `LLM_API_KEY`, `CHAT_MODEL`, `BLOB_READ_WRITE_TOKEN`, `CORS_ORIGINS` (set after step 5; e.g. `https://your-app.vercel.app`), and `JWT_SECRET` for the **worker** (use the same value as the API's generated one; the API/worker must match).
4. Verify: `https://<api>.onrender.com/healthz` → `{"status":"ok"}`.

Railway: create one service from `backend/` (Dockerfile), one with start command `python worker.py`, add a Redis plugin, set the same env vars.

## 5. Frontend on Vercel
1. Vercel → **Add New → Project** → import the repo, set **Root Directory** to `frontend`.
2. Environment variable: `NEXT_PUBLIC_API_URL=https://<api>.onrender.com`.
3. Deploy. Then update the backend `CORS_ORIGINS` to the Vercel URL (and any custom domain) and redeploy the API.

CLI alternative:
```bash
cd frontend && vercel --prod
```

## 6. CI/CD (GitHub Actions)
`ci.yml` runs on every push/PR: lint + tests + migrations/pgvector smoke test on a Postgres service, frontend lint/typecheck/tests/build, Docker image build.

`deploy.yml` is opt-in. Set repository **variables** `VERCEL_DEPLOY=true` and/or `RENDER_DEPLOY=true`, plus **secrets** `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID`, `RENDER_DEPLOY_HOOK_URL`. If you use Vercel's / Render's Git integrations (auto-deploy on push) you can leave it disabled.

## 7. Production checklist
- `ENVIRONMENT=production` (hides API docs, enforces a real `JWT_SECRET`).
- Use the same `JWT_SECRET` across API instances.
- Rate limits are shared across instances only when `REDIS_URL` is set.
- The blueprint uses Render's `standard` plan because the local embedding model (~1.5 GB RAM) does not fit free/starter. With `EMBED_BACKEND=api` and `TRANSCRIBE_BACKEND=api` a smaller plan works.
- Render's free tier sleeps; the first request after idle is slow.
- Rotate keys by changing env vars; no code changes needed.
