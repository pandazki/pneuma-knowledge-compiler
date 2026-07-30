/**
 * The React face of lib/i18n. `locale` lives in the app store next to `theme`, so switching
 * language re-renders every subscribed component immediately — no reload, no provider tree.
 */
import { useCallback } from "react";
import { useApp } from "./store";
import {
  translate,
  translateOr,
  type Locale,
  type MessageKey,
  type MessageParams,
} from "./i18n";

export type TFunction = (key: MessageKey, params?: MessageParams) => string;
export type TOrFunction = (key: string, fallback: string, params?: MessageParams) => string;

export function useLocale(): Locale {
  return useApp((s) => s.locale);
}

/** Declared keys, checked at build time. The everyday hook. */
export function useT(): TFunction {
  const locale = useLocale();
  return useCallback(
    (key: MessageKey, params?: MessageParams) => translate(locale, key, params),
    [locale],
  );
}

/**
 * Server-derived keys with a server-supplied fallback — closed vocabularies whose values the
 * client may not know yet (intake archetypes, suggestion focuses / kinds).
 */
export function useTOr(): TOrFunction {
  const locale = useLocale();
  return useCallback(
    (key: string, fallback: string, params?: MessageParams) =>
      translateOr(locale, key, fallback, params),
    [locale],
  );
}
