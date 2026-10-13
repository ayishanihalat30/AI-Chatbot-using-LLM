"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { LANGUAGE_NAMES, useI18n } from "@/lib/i18n";
import type { Lang, Length, Memory, Preferences, Style, User } from "@/lib/types";

const LENGTHS: Length[] = ["short", "medium", "detailed"];
const STYLES: Style[] = ["balanced", "friendly", "professional", "technical", "simple"];

export function SettingsView({ user, onUserChange }: { user: User; onUserChange: (u: User) => void }) {
  const { t, setLang } = useI18n();
  const prefs = user.preferences;
  const [memories, setMemories] = useState<Memory[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState("");

  const loadMem = useCallback(() => api.memories().then(setMemories).catch(() => {}), []);
  useEffect(() => {
    loadMem();
  }, [loadMem, prefs.memory_enabled]);

  async function update(p: Partial<Preferences>) {
    setError("");
    try {
      const next = await api.updatePrefs(p);
      onUserChange({ ...user, preferences: next });
      if (p.language) setLang(p.language);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("error"));
    }
  }

  const Seg = <T extends string>({ value, options, onPick, label }: { value: T; options: T[]; onPick: (v: T) => void; label: string }) => (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={o}
          role="radio"
          aria-checked={value === o}
          onClick={() => onPick(o)}
          className={`btn border ${value === o ? "border-indigo-600 bg-indigo-600 text-white" : "border-slate-300 dark:border-slate-700"}`}
        >
          {t(o)}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex-1 overflow-y-auto p-4">
      <div className="mx-auto max-w-2xl space-y-8">
        <h2 className="text-xl font-semibold">{t("settings")}</h2>
        {error && <p role="alert" className="text-sm text-red-600">{error}</p>}

        <section className="space-y-2">
          <label className="font-medium" htmlFor="lang">{t("language")}</label>
          <select id="lang" className="input" value={prefs.language} onChange={(e) => update({ language: e.target.value as Lang })}>
            {(Object.keys(LANGUAGE_NAMES) as Lang[]).map((l) => (
              <option key={l} value={l}>
                {LANGUAGE_NAMES[l]}
              </option>
            ))}
          </select>
        </section>

        <section className="space-y-2">
          <h3 className="font-medium">{t("answerLength")}</h3>
          <Seg value={prefs.answer_length} options={LENGTHS} onPick={(v) => update({ answer_length: v })} label={t("answerLength")} />
        </section>

        <section className="space-y-2">
          <h3 className="font-medium">{t("answerStyle")}</h3>
          <Seg value={prefs.answer_style} options={STYLES} onPick={(v) => update({ answer_style: v })} label={t("answerStyle")} />
        </section>

        <section className="space-y-3">
          <h3 className="font-medium">{t("memory")}</h3>
          <label className="flex items-start gap-3">
            <input type="checkbox" className="mt-1 h-4 w-4" checked={prefs.memory_enabled} onChange={(e) => update({ memory_enabled: e.target.checked })} />
            <span className="text-sm text-slate-600 dark:text-slate-400">{t("memoryDesc")}</span>
          </label>
          {prefs.memory_enabled && (
            <div className="space-y-2">
              <form
                className="flex gap-2"
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!draft.trim()) return;
                  await api.addMemory(draft.trim()).catch((err) => setError(err.message));
                  setDraft("");
                  loadMem();
                }}
              >
                <input className="input" value={draft} maxLength={500} onChange={(e) => setDraft(e.target.value)} placeholder={t("memoryAdd")} aria-label={t("memoryAdd")} />
                <button className="btn btn-primary">{t("add")}</button>
              </form>
              {memories.length === 0 && <p className="text-sm text-slate-500">{t("memoryEmpty")}</p>}
              <ul className="space-y-1">
                {memories.map((m) => (
                  <li key={m.id} className="flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
                    <span className="flex-1">{m.content}</span>
                    <button aria-label={t("delete")} onClick={() => api.deleteMemory(m.id).then(loadMem)}>
                      ✕
                    </button>
                  </li>
                ))}
              </ul>
              {memories.length > 0 && (
                <button className="text-sm text-red-600 hover:underline" onClick={() => confirm(t("confirmDelete")) && api.clearMemories().then(loadMem)}>
                  {t("clearAll")}
                </button>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
