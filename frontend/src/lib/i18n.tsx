"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import ar from "@/locales/ar.json";
import en from "@/locales/en.json";
import fr from "@/locales/fr.json";
import hi from "@/locales/hi.json";
import kn from "@/locales/kn.json";
import ml from "@/locales/ml.json";
import ta from "@/locales/ta.json";
import te from "@/locales/te.json";
import type { Lang } from "./types";

export type Dict = Record<string, string>;
export const DICTS: Record<Lang, Dict> = { en, ml, hi, ta, kn, te, ar, fr };

export const LANGUAGE_NAMES: Record<Lang, string> = {
  en: "English",
  ml: "മലയാളം",
  hi: "हिन्दी",
  ta: "தமிழ்",
  kn: "ಕನ್ನಡ",
  te: "తెలుగు",
  ar: "العربية",
  fr: "Français",
};
export const RTL: Lang[] = ["ar"];
const KEY = "rag.lang";

/** Look up a key, falling back to English and finally the key itself. */
export function translate(lang: Lang, key: string): string {
  return DICTS[lang]?.[key] ?? DICTS.en[key] ?? key;
}

interface Ctx {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string) => string;
}
const I18nContext = createContext<Ctx>({ lang: "en", setLang: () => {}, t: (k) => translate("en", k) });

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>("en");

  useEffect(() => {
    try {
      const saved = localStorage.getItem(KEY) as Lang | null;
      if (saved && saved in DICTS) setLangState(saved);
    } catch {}
  }, []);

  useEffect(() => {
    document.documentElement.lang = lang;
    document.documentElement.dir = RTL.includes(lang) ? "rtl" : "ltr";
  }, [lang]);

  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    try {
      localStorage.setItem(KEY, l);
    } catch {}
  }, []);

  const value = useMemo(() => ({ lang, setLang, t: (k: string) => translate(lang, k) }), [lang, setLang]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export const useI18n = () => useContext(I18nContext);
