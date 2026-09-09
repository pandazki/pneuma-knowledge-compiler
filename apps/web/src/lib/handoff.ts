/**
 * The face a visitor arrives WITH: `?locale=zh&theme=dark` on the console's URL.
 *
 * A launcher such as a menu-bar tray may already hold the Owner's language
 * choice and paints itself in the OS appearance; the console, opened in a browser, used to
 * re-guess both from `navigator.language` and `prefers-color-scheme` and could land in
 * English on an Owner who had set Chinese. The tray now states its face when it opens the
 * console, and this module is the console's side of that one sentence.
 *
 * Two rules make it safe to accept a preference from a URL. It carries NO authority beyond
 * the two enumerated values — anything else is ignored, never echoed, never stored. And it
 * is written into the console's OWN keys and then removed from the address with
 * `history.replaceState`, so a later visit keeps the preference without the parameter, and
 * a shared link carries no one's settings.
 *
 * Deliberately import-free: `store.ts` adopts it before the locale/theme ladders run, and a
 * unit test loads this file on its own.
 */

/** The console's stored-preference keys. Written by `store.ts` (`applyTheme` / `applyLocale`);
 *  named here because the handoff writes the same two, and `handoff.test.mjs` asserts the
 *  literals still match the ones those two functions use. */
export const HANDOFF_LOCALE_KEY = "pneuma-knowledge-locale";
export const HANDOFF_THEME_KEY = "pneuma-knowledge-theme";

/** The query parameters the tray appends. */
export const HANDOFF_LOCALE_PARAM = "locale";
export const HANDOFF_THEME_PARAM = "theme";

export type HandoffLocale = "zh" | "en";
export type HandoffTheme = "light" | "dark";

export interface HandoffPreferences {
  locale?: HandoffLocale;
  theme?: HandoffTheme;
}

/** The slice of `localStorage` this needs — so a test can hand it a plain object. */
export interface PreferenceStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

function asLocale(value: string | null): HandoffLocale | undefined {
  return value === "zh" || value === "en" ? value : undefined;
}

function asTheme(value: string | null): HandoffTheme | undefined {
  return value === "light" || value === "dark" ? value : undefined;
}

/** Whether the address carries either parameter — valid or not, it should not stay in it. */
export function hasHandoffPreferences(search: string): boolean {
  const params = new URLSearchParams(search);
  return params.has(HANDOFF_LOCALE_PARAM) || params.has(HANDOFF_THEME_PARAM);
}

/**
 * Read `search`, persist what is valid into `storage`, and return exactly what was applied.
 *
 * Pure but for the two writes: no DOM, no store, no location. An unrecognised value leaves
 * the stored preference as it was — the fallback is what the console would have done on its
 * own, which is never worse than obeying a string nobody wrote.
 */
export function adoptPreferencesFrom(
  search: string,
  storage: PreferenceStorage | null | undefined,
): HandoffPreferences {
  const params = new URLSearchParams(search);
  const applied: HandoffPreferences = {};
  const locale = asLocale(params.get(HANDOFF_LOCALE_PARAM));
  const theme = asTheme(params.get(HANDOFF_THEME_PARAM));
  if (locale) applied.locale = locale;
  if (theme) applied.theme = theme;
  if (!storage) return applied;
  try {
    if (locale) storage.setItem(HANDOFF_LOCALE_KEY, locale);
    if (theme) storage.setItem(HANDOFF_THEME_KEY, theme);
  } catch {
    /* a browser with site data blocked still gets the preference for this visit */
  }
  return applied;
}

/**
 * The whole handoff, once, at boot: adopt what the address states, then take the parameters
 * out of it. Called from `store.ts` BEFORE the locale/theme ladders read localStorage, so
 * the ordinary resolution does the applying and nothing downstream learns a second source.
 */
export function adoptHandoffPreferences(): HandoffPreferences {
  if (typeof window === "undefined") return {};
  const search = window.location.search;
  if (!hasHandoffPreferences(search)) return {};
  const storage = typeof localStorage !== "undefined" ? localStorage : null;
  const applied = adoptPreferencesFrom(search, storage);
  try {
    const url = new URL(window.location.href);
    url.searchParams.delete(HANDOFF_LOCALE_PARAM);
    url.searchParams.delete(HANDOFF_THEME_PARAM);
    window.history.replaceState(null, "", `${url.pathname}${url.search}${url.hash}`);
  } catch {
    /* an address we cannot rewrite is still an address the preference was read from */
  }
  return applied;
}
