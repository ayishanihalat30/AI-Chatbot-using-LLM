"use client";

import { useCallback, useEffect, useState } from "react";
import { api, clearTokens, hasStoredSession, refreshSession, setAuthLostHandler } from "@/lib/api";
import { I18nProvider, useI18n } from "@/lib/i18n";
import type { User } from "@/lib/types";
import { AuthForm } from "./AuthForm";
import { Shell } from "./Shell";

function Gate() {
  const { setLang, t } = useI18n();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const u = await api.me();
      setUser(u);
      setLang(u.preferences.language);
    } catch {
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, [setLang]);

  useEffect(() => {
    setAuthLostHandler(() => setUser(null));
    (async () => {
      if (hasStoredSession() && (await refreshSession())) await load();
      else setLoading(false);
    })();
  }, [load]);

  async function signOut() {
    await api.logout().catch(() => clearTokens());
    setUser(null);
  }

  if (loading) return <div className="p-8 text-center text-slate-500">{t("loading")}</div>;
  if (!user) return <AuthForm onDone={load} />;
  return <Shell user={user} onUserChange={setUser} onSignOut={signOut} />;
}

export function Root() {
  return (
    <I18nProvider>
      <Gate />
    </I18nProvider>
  );
}
