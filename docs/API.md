# REST API (`/api/v1`)

Auth: `Authorization: Bearer <access_token>` on everything except `/auth/*` (register/login/refresh/logout). Interactive docs at `/docs` outside production.
Errors: `{"detail": "..."}`; validation errors → `422 {"detail":"Validation failed","errors":[{"field","message"}]}`; rate limit → `429`.

| Method & path | Description |
|---|---|
| `POST /auth/register` `{email,password≥8}` | → `{access_token, refresh_token}` (10/min/IP) |
| `POST /auth/login` | same |
| `POST /auth/refresh` `{refresh_token}` | rotates; old token becomes invalid |
| `POST /auth/logout` `{refresh_token}` | revokes |
| `GET /auth/me` | user + preferences |
| `GET/PATCH /users/me/preferences` | `language` (en/ml/hi/ta/kn/te/ar/fr), `answer_length` (short/medium/detailed), `answer_style`, `memory_enabled` |
| `GET/POST/DELETE /users/me/memories`, `DELETE /users/me/memories/{id}` | POST needs `memory_enabled=true` |
| `DELETE /users/me` | deletes account, chats, documents, files |
| `GET /chats?q=` | list / full-text search |
| `POST /chats`, `GET/PATCH/DELETE /chats/{id}` | CRUD |
| `GET /chats/{id}/export?format=md\|txt\|json` | download |
| `POST /chats/{id}/messages` `{content, mode, document_ids?}` | **SSE** stream (30/min) |
| `POST /documents` (multipart `file`) | 202; processed in background |
| `GET /documents`, `GET /documents/{id}` | status: pending → processing → ready / failed |
| `POST /documents/{id}/reprocess`, `DELETE /documents/{id}` | |
| `GET /healthz` | DB connectivity |

## SSE events (`POST /chats/{id}/messages`)
`meta {chat_id,title}` → `citations [{n,document_id,filename,page,snippet}]` (if documents matched) → many `token "<text>"` → `done {message_id, citations}`. On failure: `error {message}`.
