/**
 * Display formatters. The locale comes from the module-level active locale rather than a
 * parameter: these are called from deep inside render trees, and a language switch
 * re-renders everything, so reading it at call time is both simpler and correct. The
 * parameter is still there for tests and for any caller that needs a fixed locale.
 */
import { activeLocale, intlTag, type Locale } from "./i18n";

export function fmtTime(
  ts: string | null | undefined,
  locale: Locale = activeLocale(),
): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(intlTag(locale), {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function fmtDate(
  ts: string | null | undefined,
  locale: Locale = activeLocale(),
): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleDateString(intlTag(locale), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function shortSha(sha: string | null | undefined, n = 8): string {
  if (!sha) return "—";
  return sha.slice(0, n);
}

export function fmtTokens(n: number | undefined): string {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
