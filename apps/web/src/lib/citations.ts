/**
 * Citation identity + human-first naming.
 *
 * The wording is INJECTED (`CitationI18n`) rather than imported: tests transpile this file
 * on its own into a data: URL module, so a runtime import here would not resolve. Passing
 * the lookup in also keeps the module honest — it decides what to say, not in which language.
 */

export interface CitationLocatorLike {
  sourceId: string;
  blockStart?: number | null;
  blockEnd?: number | null;
}

export interface CitationSourceLike {
  sourceId: string;
  title?: string | null;
  kind?: string | null;
  capturedAt?: string | null;
}

/** The wording + formatting a caller supplies (see lib/i18n: `translateOr`, `intlTag`). */
export interface CitationI18n {
  tOr: (key: string, fallback: string, params?: Record<string, string | number>) => string;
  intlTag: string;
}

/** A document citation is identified by its source and exact block span. */
export function citationKey(citation: CitationLocatorLike): string {
  return `${citation.sourceId}:${citation.blockStart ?? ""}-${citation.blockEnd ?? ""}`;
}

/** Stable 1-based numbers for a document-level citation ledger. */
export function buildCitationNumbers(
  citations: CitationLocatorLike[],
): Map<string, number> {
  return new Map(
    citations.map((citation, index) => [citationKey(citation), index + 1]),
  );
}

function sourceKindLabel(
  kind: string | null | undefined,
  i18n: CitationI18n,
): string | null {
  if (!kind) return null;
  return i18n.tOr(`enum.citationKind.${kind}`, kind);
}

function fullTimestamp(
  value: string | null | undefined,
  i18n: CitationI18n,
): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(i18n.intlTag, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

function hasReadableTitle(title: string | null | undefined, sourceId: string): boolean {
  const value = title?.trim();
  return !!value && value !== sourceId && value !== `src:${sourceId}`;
}

/**
 * Human-first citation naming. The source id remains available as technical metadata,
 * but never has to be the primary label when the public projection has source metadata.
 */
export function presentCitationSource(
  source: CitationSourceLike,
  i18n: CitationI18n,
): {
  title: string;
  description: string | null;
} {
  const kind = sourceKindLabel(source.kind, i18n);
  const capturedAt = fullTimestamp(source.capturedAt, i18n);

  if (hasReadableTitle(source.title, source.sourceId)) {
    return {
      title: source.title!.trim(),
      description: [kind, capturedAt].filter(Boolean).join(" · ") || null,
    };
  }

  const noun = kind ?? i18n.tOr("common.citation.sourceNoun", "source");
  return {
    title: capturedAt
      ? i18n.tOr("common.citation.capturedTitle", `${noun} ${capturedAt}`, {
          kind: noun,
          capturedAt,
        })
      : i18n.tOr("common.citation.untitled", `Untitled ${noun}`, { kind: noun }),
    description: i18n.tOr("common.citation.missingTitle", "Original title missing"),
  };
}
