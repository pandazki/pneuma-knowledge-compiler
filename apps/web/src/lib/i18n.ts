/**
 * UI i18n, hand-rolled (no i18next): a typed dictionary + `t()` + one module-level "active
 * locale" so that non-React code (lib/api.ts, the pure presentation helpers) can render
 * text too.
 *
 * Layering, and why it is three files rather than one:
 *   lib/i18n.ts (this file) — pure, no store, no React. Testable on its own.
 *   lib/store.ts            — owns the `locale` piece of app state, exactly like `theme`.
 *   lib/useT.ts             — the React hooks, which need both of the above.
 * Collapsing the hooks in here would make lib/i18n ↔ lib/store a cycle.
 *
 * Locale resolution: an explicit choice in localStorage wins; otherwise `navigator.language`
 * starting with `zh` picks Chinese; otherwise English. English is the default because this
 * is an open-source tool whose prompt catalogue and API vocabulary are English.
 */
import { MESSAGES, type MessageKey } from "@/i18n";
import { LOCALES, type Locale } from "@/i18n/define";

export type { Locale, MessageKey };
export { LOCALES };

export const LOCALE_STORAGE_KEY = "pneuma-knowledge-locale";

export type MessageParams = Record<string, string | number>;

export function isLocale(value: unknown): value is Locale {
  return value === "zh" || value === "en";
}

/**
 * The locale for a stored choice + a browser language, in that precedence. Pure so the
 * fallback ladder can be tested without a DOM.
 */
export function resolveLocale(
  stored: string | null | undefined,
  navigatorLanguage?: string | null,
): Locale {
  if (isLocale(stored)) return stored;
  const language = (navigatorLanguage ?? "").toLowerCase();
  // zh, zh-CN, zh-Hant-TW … all land on Chinese; everything else on English.
  if (language === "zh" || language.startsWith("zh-") || language.startsWith("zh_")) {
    return "zh";
  }
  return "en";
}

/** Read the environment (localStorage, then navigator) for the locale to start in. */
export function detectLocale(): Locale {
  const stored =
    typeof localStorage !== "undefined" ? localStorage.getItem(LOCALE_STORAGE_KEY) : null;
  const language = typeof navigator !== "undefined" ? navigator.language : null;
  return resolveLocale(stored, language);
}

/**
 * The active locale, mirrored out of the store so pure helpers and lib/api.ts can format
 * text without threading a locale through every signature. The store is still the single
 * writer (`setLocale`); this is a read cache, and a locale change re-renders every view, so
 * anything computed from it is recomputed with it.
 */
let active: Locale | null = null;

export function activeLocale(): Locale {
  if (active === null) active = detectLocale();
  return active;
}

export function setActiveLocale(locale: Locale): void {
  active = locale;
}

/**
 * `{name|singular|plural}` — pick a word by the numeric param `name`.
 *
 * English needs this ("1 documents" is wrong); Chinese does not, and because the choice lives
 * INSIDE the value rather than in a second key, the zh column simply never writes the token
 * and zh/en key parity stays trivially intact. Two forms is exactly what zh + en require; a
 * language with more plural categories would need a real CLDR rule set, and that is the point
 * at which this should grow rather than be worked around.
 */
function pluralize(template: string, params?: MessageParams): string {
  if (!params) return template;
  return template.replace(
    /\{(\w+)\|([^{}|]*)\|([^{}|]*)\}/g,
    (whole, name: string, one: string, many: string) => {
      const value = params[name];
      if (typeof value !== "number") return whole;
      return value === 1 ? one : many;
    },
  );
}

/** `{name}` placeholders, same shape as the backend prompt catalogue's. */
function interpolate(template: string, params?: MessageParams): string {
  if (!params) return template;
  // Plural tokens first — they are disjoint from bare `{name}` placeholders, and resolving
  // them first means the chosen word can itself never be mistaken for a placeholder.
  return pluralize(template, params).replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in params ? String(params[name]) : whole,
  );
}

/**
 * Look a declared key up. `MessageKey` makes an unknown key a build error, so the runtime
 * fallbacks here only matter for a dictionary that drifted past the type checker: English
 * first, then the key itself (visible, never blank).
 */
export function translate(locale: Locale, key: MessageKey, params?: MessageParams): string {
  const template = MESSAGES[locale][key] ?? MESSAGES.en[key] ?? key;
  return interpolate(template, params);
}

/**
 * Look an UNDECLARED-at-compile-time key up — a key computed from server data, e.g.
 * `enum.contextFocus.${key}.label` — and fall back to what the server sent. This is the
 * mechanism that lets the backend add a value to a closed vocabulary without the client
 * rendering a blank: it degrades to the server's English label.
 */
export function translateOr(
  locale: Locale,
  key: string,
  fallback: string,
  params?: MessageParams,
): string {
  const table = MESSAGES[locale] as Record<string, string | undefined>;
  const english = MESSAGES.en as Record<string, string | undefined>;
  const template = table[key] ?? english[key];
  return template === undefined ? fallback : interpolate(template, params);
}

/** `translate` against the module-level active locale, for non-React call sites. */
export function tx(key: MessageKey, params?: MessageParams): string {
  return translate(activeLocale(), key, params);
}

/** `translateOr` against the module-level active locale, for non-React call sites. */
export function txOr(key: string, fallback: string, params?: MessageParams): string {
  return translateOr(activeLocale(), key, fallback, params);
}

/**
 * The BCP-47 tag handed to `Intl` / `toLocaleString`.
 *
 * `en-CA` rather than `en-US` / `en-GB` on purpose: it yields ISO-8601 numeric dates
 * (2026-07-30), which are unambiguous for every reader and match the register of the rest of
 * the interface — mono refs, short shas, block numbers. `zh-CN` keeps the existing output.
 */
const INTL_TAGS: Record<Locale, string> = {
  zh: "zh-CN",
  en: "en-CA",
};

export function intlTag(locale: Locale = activeLocale()): string {
  return INTL_TAGS[locale];
}
