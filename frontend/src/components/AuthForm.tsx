"use client";

import { useState, type FormEvent } from "react";
import { api } from "@/lib/api";
import { LANGUAGE_NAMES, useI18n } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

export function AuthForm({ onDone }: { onDone: () => void }) {
  const { t, lang, setLang } = useI18n();
  const [register, setRegister] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await (register ? api.register : api.login)(email.trim(), password);
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : t("error"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-6">
        <div className="text-center">
          <h1 className="text-3xl font-bold tracking-tight">✦ {t("appName")}</h1>
          <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">{t("tagline")}</p>
        </div>
        <form onSubmit={submit} className="space-y-3" aria-label={register ? t("signUp") : t("signIn")}>
          <input
            className="input"
            type="email"
            required
            autoComplete="email"
            placeholder={t("email")}
            aria-label={t("email")}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
          <input
            className="input"
            type="password"
            required
            minLength={register ? 8 : 1}
            autoComplete={register ? "new-password" : "current-password"}
            placeholder={t("password")}
            aria-label={t("password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          {error && (
            <p role="alert" className="text-sm text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          <button className="btn btn-primary w-full" disabled={busy}>
            {busy ? t("loading") : register ? t("signUp") : t("signIn")}
          </button>
        </form>
        <button className="w-full text-center text-sm text-indigo-600 hover:underline dark:text-indigo-400" onClick={() => setRegister(!register)}>
          {register ? t("haveAccount") : t("noAccount")}
        </button>
        <select className="input" value={lang} onChange={(e) => setLang(e.target.value as Lang)} aria-label={t("language")}>
          {(Object.keys(LANGUAGE_NAMES) as Lang[]).map((l) => (
            <option key={l} value={l}>
              {LANGUAGE_NAMES[l]}
            </option>
          ))}
        </select>
      </div>
    </main>
  );
}
