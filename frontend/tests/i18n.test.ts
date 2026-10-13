import { describe, expect, it } from "vitest";
import { DICTS, LANGUAGE_NAMES, RTL, translate } from "@/lib/i18n";
import type { Lang } from "@/lib/types";

describe("i18n", () => {
  const langs = Object.keys(DICTS) as Lang[];
  const enKeys = Object.keys(DICTS.en).sort();

  it("supports the 8 required languages", () => {
    expect(langs.sort()).toEqual(["ar", "en", "fr", "hi", "kn", "ml", "ta", "te"]);
    expect(Object.keys(LANGUAGE_NAMES).sort()).toEqual(langs.sort());
  });

  it.each(langs)("%s has exactly the same keys as English and no empty values", (l) => {
    expect(Object.keys(DICTS[l]).sort()).toEqual(enKeys);
    for (const v of Object.values(DICTS[l])) expect(v.trim()).not.toBe("");
  });

  it("actually translates (non-English differs from English for core strings)", () => {
    for (const l of langs.filter((x) => x !== "en")) expect(DICTS[l].signIn).not.toBe(DICTS.en.signIn);
  });

  it("falls back to English then key", () => {
    expect(translate("fr", "nope-key")).toBe("nope-key");
  });

  it("marks Arabic as RTL only", () => {
    expect(RTL).toEqual(["ar"]);
  });
});
