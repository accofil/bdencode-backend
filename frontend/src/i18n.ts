import { useSyncExternalStore } from "react";

/**
 * The interface language.  Every visible text is written as a Hungarian and
 * English pair at the place where it is used: `t("Mentés", "Save")`.
 *
 * `t` reads the current language at call time, so it works in components and
 * in plain helpers alike.  The App component subscribes with `useLanguage()`,
 * which re-renders the whole tree on a switch; a `useMemo` that builds text
 * must list `useLanguage()` among its dependencies.
 */
export type Language = "hu" | "en";

export const LANGUAGES: readonly Language[] = ["hu", "en"];
export const LANGUAGE_STORAGE_KEY = "bdencode.language";

function storedLanguage(): Language | null {
  try {
    const value = window.localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return value === "hu" || value === "en" ? value : null;
  } catch {
    return null;
  }
}

/** The saved choice, else the browser's language: Hungarian browsers get Hungarian, everyone else English. */
export function detectLanguage(): Language {
  const stored = storedLanguage();
  if (stored) return stored;
  const preferred = typeof navigator === "undefined"
    ? []
    : [...(navigator.languages ?? []), navigator.language].filter(Boolean);
  return preferred.some((tag) => tag.toLowerCase().startsWith("hu")) ? "hu" : "en";
}

let current: Language = detectLanguage();
const listeners = new Set<() => void>();

function applyDocumentLanguage(language: Language): void {
  if (typeof document !== "undefined") document.documentElement.lang = language;
}
applyDocumentLanguage(current);

export function getLanguage(): Language {
  return current;
}

export function setLanguage(language: Language, { persist = true }: { persist?: boolean } = {}): void {
  if (persist) {
    try {
      window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
    } catch {
      // Private mode or blocked storage: the choice lasts for this page only.
    }
  }
  if (language === current) return;
  current = language;
  applyDocumentLanguage(language);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** The current language; the calling component re-renders when it changes. */
export function useLanguage(): Language {
  return useSyncExternalStore(subscribe, getLanguage, getLanguage);
}

/** The text in the current language. */
export function t(hu: string, en: string): string {
  return current === "hu" ? hu : en;
}

/** A Hungarian/English pair kept as data, resolved when shown. */
export interface LocalText {
  hu: string;
  en: string;
}

export function tx(text: LocalText): string {
  return text[current];
}

/** The locale for Intl date and number formatting. */
export function locale(): string {
  return current === "hu" ? "hu-HU" : "en-GB";
}
