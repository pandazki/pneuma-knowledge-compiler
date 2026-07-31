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

/**
 * A cardinal count, grouped. Five figures of catalogue read as "5,832"; "5832" reads as an
 * identifier. Returned as a STRING because it goes into a message placeholder, and a plural
 * token would have nothing numeric left to agree with — the templates that use it therefore
 * never carry one.
 */
export function fmtCount(n: number, locale: Locale = activeLocale()): string {
  if (!Number.isFinite(n)) return "—";
  return n.toLocaleString(intlTag(locale));
}

/**
 * A `YYYY-MM-DD` day, as a day — no clock. Passed through untouched if it is not one, so a
 * malformed stamp stays visible instead of turning into "Invalid Date".
 */
export function fmtDay(day: string | null | undefined, locale: Locale = activeLocale()): string {
  if (!day) return "—";
  if (!/^\d{4}-\d{2}-\d{2}$/.test(day)) return day;
  const [year, month, date] = day.split("-").map(Number);
  return new Date(Date.UTC(year!, month! - 1, date!)).toLocaleDateString(intlTag(locale), {
    timeZone: "UTC",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export function shortSha(sha: string | null | undefined, n = 8): string {
  if (!sha) return "—";
  return sha.slice(0, n);
}

/**
 * A 0–1 share as a percentage, always one decimal: a structure reading of "0%" for a subject
 * that really holds a few claims reads as absent rather than small, which is the wrong lie.
 */
export function fmtPercent(share: number): string {
  if (!Number.isFinite(share)) return "—";
  return `${(share * 100).toFixed(1)}%`;
}

/** A signed count for a difference column; zero prints as an en dash, not as "+0". */
export function fmtDelta(n: number, decimals = 0): string {
  if (!Number.isFinite(n)) return "—";
  if (n === 0) return "–";
  return `${n > 0 ? "+" : "−"}${Math.abs(n).toFixed(decimals)}`;
}

export function fmtTokens(n: number | undefined): string {
  if (n == null) return "—";
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}
