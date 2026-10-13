"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Doc } from "@/lib/types";

const fmt = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);
const BADGE: Record<Doc["status"], string> = {
  pending: "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-200",
  processing: "bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-200",
  ready: "bg-green-100 text-green-800 dark:bg-green-900/50 dark:text-green-200",
  failed: "bg-red-100 text-red-800 dark:bg-red-900/50 dark:text-red-200",
};

export function DocumentsView() {
  const { t } = useI18n();
  const [docs, setDocs] = useState<Doc[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  const load = useCallback(() => api.documents().then(setDocs).catch((e) => setError(e.message)), []);
  useEffect(() => {
    load();
  }, [load]);

  const working = docs.some((d) => d.status === "pending" || d.status === "processing");
  useEffect(() => {
    if (!working) return;
    const h = setInterval(load, 2500);
    return () => clearInterval(h);
  }, [working, load]);

  async function upload(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      for (const f of Array.from(files)) await api.uploadDocument(f);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("error"));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
      load();
    }
  }

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="mx-auto max-w-3xl space-y-4">
        <h2 className="text-xl font-semibold">{t("documents")}</h2>
        <div
          className="rounded-xl border-2 border-dashed border-slate-300 p-8 text-center dark:border-slate-700"
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            upload(e.dataTransfer.files);
          }}
        >
          <input ref={input} type="file" multiple hidden onChange={(e) => upload(e.target.files)} accept=".pdf,.docx,.txt,.md,.markdown,.csv,.xlsx,.pptx,image/*,audio/*,video/*" />
          <button className="btn btn-primary" onClick={() => input.current?.click()} disabled={busy}>
            {busy ? t("uploading") : t("uploadFiles")}
          </button>
          <p className="mt-2 text-xs text-slate-500">{t("dropHint")}</p>
        </div>
        {error && <p role="alert" className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        <ul className="divide-y divide-slate-200 dark:divide-slate-800">
          {docs.map((d) => (
            <li key={d.id} className="flex flex-wrap items-center gap-3 py-3">
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{d.filename}</p>
                <p className="text-xs text-slate-500">
                  {fmt(d.size)} · {new Date(d.created_at).toLocaleDateString()}
                  {d.status === "ready" && ` · ${d.chunk_count} chunks`}
                </p>
                {d.error && <p className="text-xs text-red-600 dark:text-red-400">{d.error}</p>}
              </div>
              <span className={`rounded-full px-2 py-0.5 text-xs ${BADGE[d.status]}`}>{t(d.status)}</span>
              {d.status === "failed" && (
                <button className="btn btn-ghost" onClick={() => api.reprocessDocument(d.id).then(load)}>
                  {t("retry")}
                </button>
              )}
              <button
                className="btn btn-ghost"
                aria-label={`${t("delete")} ${d.filename}`}
                onClick={async () => {
                  if (confirm(t("confirmDelete"))) {
                    await api.deleteDocument(d.id);
                    load();
                  }
                }}
              >
                🗑
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
