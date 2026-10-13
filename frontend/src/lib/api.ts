import { createSSEParser } from "./sse";
import type { Chat, ChatDetail, Citation, Doc, Memory, Mode, Preferences, User } from "./types";

export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");
const BASE = `${API_URL}/api/v1`;
const REFRESH_KEY = "rag.refresh";

let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
let onAuthLost: () => void = () => {};

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export function setAuthLostHandler(fn: () => void) {
  onAuthLost = fn;
}
export const hasStoredSession = () => typeof window !== "undefined" && !!localStorage.getItem(REFRESH_KEY);

function storeTokens(t: { access_token: string; refresh_token: string }) {
  accessToken = t.access_token;
  try {
    localStorage.setItem(REFRESH_KEY, t.refresh_token);
  } catch {}
}
export function clearTokens() {
  accessToken = null;
  try {
    localStorage.removeItem(REFRESH_KEY);
  } catch {}
}

async function parseError(res: Response): Promise<ApiError> {
  let msg = res.statusText;
  try {
    const j = await res.json();
    msg = j.errors?.[0] ? `${j.errors[0].field}: ${j.errors[0].message}` : j.detail || msg;
  } catch {}
  return new ApiError(res.status, String(msg));
}

export async function refreshSession(): Promise<boolean> {
  if (refreshing) return refreshing;
  refreshing = (async () => {
    const rt = typeof window !== "undefined" ? localStorage.getItem(REFRESH_KEY) : null;
    if (!rt) return false;
    const res = await fetch(`${BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    }).catch(() => null);
    if (!res || !res.ok) {
      if (res) clearTokens();
      return false;
    }
    storeTokens(await res.json());
    return true;
  })().finally(() => {
    refreshing = null;
  });
  return refreshing;
}

async function raw(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type"))
    headers.set("Content-Type", "application/json");
  const res = await fetch(`${BASE}${path}`, { ...init, headers });
  if (res.status === 401 && retry && (await refreshSession())) return raw(path, init, false);
  if (res.status === 401 && retry) onAuthLost();
  if (!res.ok) throw await parseError(res);
  return res;
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await raw(path, init);
  return res.status === 204 ? (undefined as T) : res.json();
}

const body = (o: unknown) => JSON.stringify(o);

async function authCall(path: string, email: string, password: string) {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body({ email, password }),
  });
  if (!res.ok) throw await parseError(res);
  storeTokens(await res.json());
}

export interface StreamCallbacks {
  onToken: (t: string) => void;
  onCitations: (c: Citation[]) => void;
  onMeta: (title: string) => void;
  onError: (m: string) => void;
}

export const api = {
  register: (email: string, password: string) => authCall("/auth/register", email, password),
  login: (email: string, password: string) => authCall("/auth/login", email, password),
  async logout() {
    const rt = localStorage.getItem(REFRESH_KEY);
    if (rt)
      await fetch(`${BASE}/auth/logout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: body({ refresh_token: rt }),
      }).catch(() => {});
    clearTokens();
  },
  me: () => json<User>("/auth/me"),
  updatePrefs: (p: Partial<Preferences>) =>
    json<Preferences>("/users/me/preferences", { method: "PATCH", body: body(p) }),
  memories: () => json<Memory[]>("/users/me/memories"),
  addMemory: (content: string) => json<Memory>("/users/me/memories", { method: "POST", body: body({ content }) }),
  deleteMemory: (id: string) => json<void>(`/users/me/memories/${id}`, { method: "DELETE" }),
  clearMemories: () => json<void>("/users/me/memories", { method: "DELETE" }),
  chats: (q?: string) => json<Chat[]>(`/chats${q ? `?q=${encodeURIComponent(q)}` : ""}`),
  createChat: () => json<Chat>("/chats", { method: "POST", body: body({}) }),
  chat: (id: string) => json<ChatDetail>(`/chats/${id}`),
  renameChat: (id: string, title: string) => json<Chat>(`/chats/${id}`, { method: "PATCH", body: body({ title }) }),
  deleteChat: (id: string) => json<void>(`/chats/${id}`, { method: "DELETE" }),
  async exportChat(id: string, format: "md" | "txt" | "json") {
    const res = await raw(`/chats/${id}/export?format=${format}`);
    const blob = await res.blob();
    const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") || "")?.[1] || `chat.${format}`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  },
  documents: () => json<Doc[]>("/documents"),
  uploadDocument(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return json<Doc>("/documents", { method: "POST", body: fd });
  },
  deleteDocument: (id: string) => json<void>(`/documents/${id}`, { method: "DELETE" }),
  reprocessDocument: (id: string) => json<Doc>(`/documents/${id}/reprocess`, { method: "POST" }),

  /** Streams an assistant reply; callbacks fire as SSE events arrive. */
  async streamMessage(
    chatId: string,
    content: string,
    opts: { mode: Mode; documentIds?: string[]; signal?: AbortSignal },
    cb: StreamCallbacks,
  ) {
    const res = await raw(`/chats/${chatId}/messages`, {
      method: "POST",
      body: body({ content, mode: opts.mode, document_ids: opts.documentIds?.length ? opts.documentIds : null }),
      signal: opts.signal,
    });
    if (!res.body) throw new ApiError(500, "No response stream");
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    const parse = createSSEParser();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const ev of parse(decoder.decode(value, { stream: true }))) {
        if (ev.event === "token") cb.onToken(ev.data as string);
        else if (ev.event === "citations") cb.onCitations(ev.data as Citation[]);
        else if (ev.event === "meta") cb.onMeta((ev.data as { title: string }).title);
        else if (ev.event === "error") cb.onError((ev.data as { message: string }).message);
        else if (ev.event === "done") cb.onCitations((ev.data as { citations: Citation[] }).citations);
      }
    }
  },
};
