/**
 * Display formatters. The locale comes from the module-level active locale rather than a
 * parameter: these are called from deep inside render trees, and a language switch
 * re-renders everything, so reading it at call time is both simpler and correct. The
 * parameter is still there for tests and for any caller that needs a fixed locale.
 */
import { activeLocale, groupNumber, intlTag, type Locale } from "./i18n";

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
  // One policy, one implementation: `t("…", { count })` groups through the same function
  // (lib/i18n `groupNumber`), so a number written into a message and a number rendered
  // beside it can never disagree about where the commas go.
  return groupNumber(n, locale);
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

/**
 * A full moment — day AND clock, with the year. `fmtTime` drops the year because it stamps
 * things that just happened; a stamp sitting next to a corpus date (a galley header) needs
 * the year, or the reader cannot tell which of the two dates is which.
 */
export function fmtDateTime(
  ts: string | null | undefined,
  locale: Locale = activeLocale(),
): string {
  if (!ts) return "—";
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(intlTag(locale), {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

/**
 * A moment of unknown shape, as it should read: a bare `YYYY-MM-DD` as a day, anything the
 * Date constructor understands as a full stamp, and everything else untouched. Source
 * metadata carries whatever the provider wrote, so the alternative to this is a page mixing
 * ISO strings with localized ones — which is exactly what it did.
 */
export function fmtMoment(
  value: string | null | undefined,
  locale: Locale = activeLocale(),
): string {
  if (!value) return "—";
  const text = value.trim();
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) return fmtDay(text, locale);
  // A date-like string only: anything without digits and separators is prose, not a stamp.
  if (!/^\d{4}-\d{2}-\d{2}[T ]/.test(text)) return value;
  const d = new Date(text);
  if (isNaN(d.getTime())) return value;
  return fmtDateTime(text, locale);
}

/**
 * Runs of whitespace collapsed to one space. Commit subjects and labels arrive with the
 * spacing they were written with; a display line is not the place to reproduce it.
 */
export function squish(text: string | null | undefined): string {
  return (text ?? "").replace(/\s+/g, " ").trim();
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

/**
 * Money, as the API handed it over: the amount and the currency LABEL the deployment
 * declared, never a symbol this app chose for it. `—` when there is no cost — which is what
 * an undeclared price reads as, and is deliberately not `0.00`.
 *
 * The decimals scale with the amount because both ends are real: a compile run costs
 * dollars, and one fast answer costs fractions of a cent. Two decimals everywhere would
 * print `0.00` for money that was actually spent.
 */
export function fmtMoney(
  cost: { amount: number; currency: string } | null | undefined,
): string {
  if (!cost || !Number.isFinite(cost.amount)) return "—";
  const size = Math.abs(cost.amount);
  const decimals = size >= 1 ? 2 : size >= 0.01 ? 4 : 6;
  return `${cost.amount.toFixed(decimals)} ${cost.currency}`;
}

/**
 * The one token ledger's line, as text: what a call spent, and — only where the deployment
 * declared a price for the model behind it — what that cost.
 *
 * A string builder rather than markup because the decision in it is worth testing: an
 * undeclared price prints NOTHING, not `0.00`, and "the deployment says nothing about this
 * model" must never read as "this call was free". `UsageLine` renders exactly this.
 */
export function usageLine(
  usage: {
    input_tokens?: number;
    output_tokens?: number;
    total_tokens?: number;
    cache_read?: number;
    cache_creation?: number;
  },
  cost?: { amount: number; currency: string } | null,
  locale: Locale = activeLocale(),
): string {
  const line =
    `in ${fmtCount(usage.input_tokens ?? 0, locale)} · ` +
    `out ${fmtCount(usage.output_tokens ?? 0, locale)} · ` +
    `total ${fmtCount(usage.total_tokens ?? 0, locale)} · ` +
    `cache_read ${fmtCount(usage.cache_read ?? 0, locale)} · ` +
    `cache_creation ${fmtCount(usage.cache_creation ?? 0, locale)}`;
  return cost ? `${line} · cost ${fmtMoney(cost)}` : line;
}
