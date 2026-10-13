"use client";

import { useEffect, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Citation, Doc, Message, Mode, Preferences } from "@/lib/types";
import { Markdown } from "./Markdown";

const MODES: Mode[] = ["general", "programming", "career", "education"];

interface Props {
  chatId: string | null;
  preferences: Preferences;
  onChatCreated: (id: string) => void;
  onChanged: () => void;
}

export function ChatView({ chatId, onChatCreated, onChanged }: Props) {
  const { t } = useI18n();
  const [id, setId] = useState(chatId);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<Mode>("general");
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState("");
  const [uploads, setUploads] = useState<Doc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [docs, setDocs] = useState<Doc[]>([]);
  const [scope, setScope] = useState("");
  const [showExport, setShowExport] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (chatId) api.chat(chatId).then((c) => setMessages(c.messages)).catch((e) => setError(e.message));
  }, [chatId]);

  useEffect(() => {
    api.documents().then((d) => setDocs(d.filter((x) => x.status === "ready"))).catch(() => {});
  }, [uploads]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  // Poll attached files until they finish background processing
  useEffect(() => {
    if (!uploads.some((u) => u.status === "pending" || u.status === "processing")) return;
    const h = setInterval(async () => {
      const fresh = await Promise.all(uploads.map((u) => (u.status === "ready" || u.status === "failed" ? u : api.documents().then((all) => all.find((d) => d.id === u.id) ?? u))));
      setUploads(fresh);
    }, 2000);
    return () => clearInterval(h);
  }, [uploads]);

  async function attach(files: FileList | null) {
    if (!files?.length) return;
    setUploading(true);
    setError("");
    try {
      for (const f of Array.from(files)) {
        const d = await api.uploadDocument(f);
        setUploads((u) => [...u, d]);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : t("error"));
    } finally {
      setUploading(false);
      if (fileInput.current) fileInput.current.value = "";
    }
  }

  async function send(e?: FormEvent) {
    e?.preventDefault();
    const text = input.trim();
    if (!text || streaming) return;
    setError("");
    setInput("");
    let cid = id;
    try {
      if (!cid) {
        cid = (await api.createChat()).id;
        setId(cid);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : t("error"));
      return;
    }
    setMessages((m) => [...m, { id: `u${Date.now()}`, role: "user", content: text }, { id: "streaming", role: "assistant", content: "" }]);
    setStreaming(true);
    abort.current = new AbortController();
    const patchLast = (fn: (m: Message) => Message) =>
      setMessages((all) => all.map((m, i) => (i === all.length - 1 ? fn(m) : m)));
    try {
      await api.streamMessage(
        cid,
        text,
        { mode, documentIds: scope ? [scope] : undefined, signal: abort.current.signal },
        {
          onToken: (tok) => patchLast((m) => ({ ...m, content: m.content + tok })),
          onCitations: (c) => patchLast((m) => ({ ...m, citations: c })),
          onMeta: () => {},
          onError: (msg) => setError(msg),
        },
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError(err instanceof Error ? err.message : t("error"));
    } finally {
      setStreaming(false);
      abort.current = null;
      if (!chatId) onChatCreated(cid);
      else onChanged();
    }
  }

  function onKey(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      send();
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center justify-end gap-2 px-3 py-2">
        {id && (
          <div className="relative">
            <button className="btn btn-ghost" onClick={() => setShowExport(!showExport)} aria-haspopup="menu" aria-expanded={showExport}>
              ⤓ {t("export")}
            </button>
            {showExport && (
              <div role="menu" className="absolute end-0 z-10 mt-1 w-32 rounded-lg border border-slate-200 bg-white p-1 shadow-lg dark:border-slate-700 dark:bg-slate-900">
                {(["md", "txt", "json"] as const).map((f) => (
                  <button key={f} role="menuitem" className="btn btn-ghost w-full justify-start" onClick={() => { api.exportChat(id, f); setShowExport(false); }}>
                    .{f}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-3" aria-live="polite">
        <div className="mx-auto max-w-3xl space-y-6 pb-4">
          {messages.length === 0 && (
            <div className="py-16 text-center">
              <h2 className="text-2xl font-semibold">{t("welcome")}</h2>
              <p className="mx-auto mt-2 max-w-md text-sm text-slate-500 dark:text-slate-400">{t("welcomeSub")}</p>
            </div>
          )}
          {messages.map((m) => (
            <MessageBubble key={m.id} m={m} streaming={streaming && m.id === "streaming"} />
          ))}
          <div ref={bottom} />
        </div>
      </div>

      <form onSubmit={send} className="border-t border-slate-200 p-3 dark:border-slate-800">
        <div className="mx-auto max-w-3xl space-y-2">
          {error && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          {uploads.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {uploads.map((u) => (
                <span key={u.id} className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-3 py-1 text-xs dark:bg-slate-800">
                  📎 {u.filename} · {t(u.status)}
                </span>
              ))}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select className="input !w-auto !py-1" value={mode} onChange={(e) => setMode(e.target.value as Mode)} aria-label={t("mode")}>
              {MODES.map((m) => (
                <option key={m} value={m}>
                  {t(m)}
                </option>
              ))}
            </select>
            {docs.length > 0 && (
              <select className="input !w-auto max-w-[12rem] !py-1" value={scope} onChange={(e) => setScope(e.target.value)} aria-label={t("useDocs")}>
                <option value="">{t("allDocs")}</option>
                {docs.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="flex items-end gap-2">
            <input ref={fileInput} type="file" multiple hidden onChange={(e) => attach(e.target.files)} accept=".pdf,.docx,.txt,.md,.markdown,.csv,.xlsx,.pptx,image/*,audio/*,video/*" />
            <button type="button" className="btn btn-ghost" onClick={() => fileInput.current?.click()} disabled={uploading} aria-label={t("attach")} title={t("attach")}>
              {uploading ? "…" : "📎"}
            </button>
            <textarea
              className="input max-h-40 min-h-[2.5rem] flex-1 resize-none"
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder={t("placeholder")}
              aria-label={t("placeholder")}
            />
            {streaming ? (
              <button type="button" className="btn btn-primary" onClick={() => abort.current?.abort()}>
                ■ {t("stop")}
              </button>
            ) : (
              <button className="btn btn-primary" disabled={!input.trim()}>
                {t("send")}
              </button>
            )}
          </div>
        </div>
      </form>
    </div>
  );
}

function MessageBubble({ m, streaming }: { m: Message; streaming: boolean }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const mine = m.role === "user";
  return (
    <div className={`flex ${mine ? "justify-end" : ""}`}>
      <div className={`max-w-full ${mine ? "rounded-2xl bg-indigo-600 px-4 py-2 text-white md:max-w-[80%]" : "w-full"}`}>
        {mine ? (
          <p className="whitespace-pre-wrap break-words">{m.content}</p>
        ) : m.content ? (
          <>
            <Markdown text={m.content} />
            {!streaming && (
              <button
                className="mt-1 text-xs text-slate-500 hover:underline"
                onClick={() => {
                  navigator.clipboard?.writeText(m.content);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 1500);
                }}
              >
                {copied ? t("copied") : t("copy")}
              </button>
            )}
          </>
        ) : (
          <span className="animate-pulse text-slate-500">{t("thinking")}</span>
        )}
        {!!m.citations?.length && <Sources citations={m.citations} />}
      </div>
    </div>
  );
}

function Sources({ citations }: { citations: Citation[] }) {
  const { t } = useI18n();
  const [openN, setOpenN] = useState<number | null>(null);
  const active = citations.find((c) => c.n === openN);
  return (
    <div className="mt-2 space-y-2">
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-slate-500">{t("sources")}:</span>
        {citations.map((c) => (
          <button
            key={c.n}
            onClick={() => setOpenN(openN === c.n ? null : c.n)}
            aria-expanded={openN === c.n}
            className="rounded-full border border-slate-300 px-2 py-0.5 hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800"
          >
            [{c.n}] {c.filename}
            {c.page ? ` ${t("page")}${c.page}` : ""}
          </button>
        ))}
      </div>
      {active && <blockquote className="rounded-lg bg-slate-100 p-3 text-xs text-slate-700 dark:bg-slate-800 dark:text-slate-300">{active.snippet}…</blockquote>}
    </div>
  );
}
