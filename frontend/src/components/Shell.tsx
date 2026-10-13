"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import type { Chat, User } from "@/lib/types";
import { ChatView } from "./ChatView";
import { DocumentsView } from "./DocumentsView";
import { SettingsView } from "./SettingsView";

type View = "chat" | "documents" | "settings";

interface Props {
  user: User;
  onUserChange: (u: User) => void;
  onSignOut: () => void;
}

export function Shell({ user, onUserChange, onSignOut }: Props) {
  const { t } = useI18n();
  const [view, setView] = useState<View>("chat");
  const [chats, setChats] = useState<Chat[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setChats(await api.chats(query.trim() || undefined));
    } catch {}
  }, [query]);

  useEffect(() => {
    const h = setTimeout(refresh, query ? 250 : 0); // debounce search
    return () => clearTimeout(h);
  }, [refresh, query]);

  function go(v: View, chatId: string | null = null) {
    setView(v);
    if (v === "chat") setActiveId(chatId);
    setOpen(false);
  }

  async function removeChat(id: string) {
    if (!confirm(t("confirmDelete"))) return;
    await api.deleteChat(id);
    if (activeId === id) setActiveId(null);
    refresh();
  }

  async function renameChat(c: Chat) {
    const title = prompt(t("rename"), c.title)?.trim();
    if (title) {
      await api.renameChat(c.id, title);
      refresh();
    }
  }

  const nav = (v: View, label: string) => (
    <button
      className={`btn btn-ghost flex-1 ${view === v ? "bg-slate-100 dark:bg-slate-800" : ""}`}
      onClick={() => go(v, v === "chat" ? activeId : null)}
    >
      {label}
    </button>
  );

  return (
    <div className="flex h-full">
      {open && <div className="fixed inset-0 z-20 bg-black/40 md:hidden" onClick={() => setOpen(false)} aria-hidden />}
      <aside
        className={`fixed inset-y-0 start-0 z-30 flex w-72 flex-col border-e border-slate-200 bg-slate-50 transition-transform dark:border-slate-800 dark:bg-slate-900 md:static md:translate-x-0 rtl:md:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full rtl:translate-x-full"
        }`}
        aria-label={t("chats")}
      >
        <div className="space-y-2 p-3">
          <div className="flex items-center justify-between">
            <span className="text-lg font-bold">✦ {t("appName")}</span>
            <button className="btn btn-ghost md:hidden" onClick={() => setOpen(false)} aria-label={t("close")}>
              ✕
            </button>
          </div>
          <button className="btn btn-primary w-full" onClick={() => go("chat", null)}>
            + {t("newChat")}
          </button>
          <input
            className="input"
            type="search"
            placeholder={t("searchChats")}
            aria-label={t("searchChats")}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-2" aria-label={t("chats")}>
          {chats.length === 0 && <p className="p-3 text-sm text-slate-500">{t("noChats")}</p>}
          {chats.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center rounded-lg ${activeId === c.id && view === "chat" ? "bg-slate-200 dark:bg-slate-800" : "hover:bg-slate-100 dark:hover:bg-slate-800/60"}`}
            >
              <button className="min-w-0 flex-1 truncate px-3 py-2 text-start text-sm" onClick={() => go("chat", c.id)}>
                {c.title}
              </button>
              <button className="px-1 text-xs opacity-60 hover:opacity-100 md:opacity-0 md:group-hover:opacity-60" onClick={() => renameChat(c)} aria-label={t("rename")} title={t("rename")}>
                ✎
              </button>
              <button className="px-2 text-xs opacity-60 hover:opacity-100 md:opacity-0 md:group-hover:opacity-60" onClick={() => removeChat(c.id)} aria-label={t("delete")} title={t("delete")}>
                🗑
              </button>
            </div>
          ))}
        </nav>
        <div className="space-y-2 border-t border-slate-200 p-3 dark:border-slate-800">
          <div className="flex gap-1">
            {nav("chat", t("chats"))}
            {nav("documents", t("documents"))}
            {nav("settings", t("settings"))}
          </div>
          <div className="flex items-center justify-between gap-2 text-xs text-slate-500">
            <span className="truncate">{user.email}</span>
            <button className="shrink-0 hover:underline" onClick={onSignOut}>
              {t("signOut")}
            </button>
          </div>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-slate-200 p-2 dark:border-slate-800 md:hidden">
          <button className="btn btn-ghost" onClick={() => setOpen(true)} aria-label={t("menu")}>
            ☰
          </button>
          <span className="font-semibold">✦ {t("appName")}</span>
        </header>
        {view === "chat" && (
          <ChatView
            key={activeId ?? "new"}
            chatId={activeId}
            preferences={user.preferences}
            onChatCreated={(id) => {
              setActiveId(id);
              refresh();
            }}
            onChanged={refresh}
          />
        )}
        {view === "documents" && <DocumentsView />}
        {view === "settings" && <SettingsView user={user} onUserChange={onUserChange} />}
      </main>
    </div>
  );
}
