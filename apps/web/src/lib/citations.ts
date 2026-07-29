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

const SOURCE_KIND_LABELS: Record<string, string> = {
  meeting: "会议",
  document_library: "文档",
  im: "即时消息",
  email: "邮件",
  conversation: "对话",
  document: "文档",
  structured: "结构化数据",
};

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

function sourceKindLabel(kind: string | null | undefined): string | null {
  if (!kind) return null;
  return SOURCE_KIND_LABELS[kind] ?? kind;
}

function fullTimestamp(value: string | null | undefined): string | null {
  if (!value) return null;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", {
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
export function presentCitationSource(source: CitationSourceLike): {
  title: string;
  description: string | null;
} {
  const kind = sourceKindLabel(source.kind);
  const capturedAt = fullTimestamp(source.capturedAt);

  if (hasReadableTitle(source.title, source.sourceId)) {
    return {
      title: source.title!.trim(),
      description: [kind, capturedAt].filter(Boolean).join(" · ") || null,
    };
  }

  return {
    title: capturedAt
      ? `${capturedAt} 的${kind ?? "来源"}`
      : `未命名${kind ?? "来源"}`,
    description: "原始标题缺失",
  };
}
