import type { ReactNode } from "react";
import { cn } from "@/ui/cn";
import { Mono } from "@/ui/Mono";

export interface CitationEntry {
  sourceId: string;
  blockStart?: number | null;
  blockEnd?: number | null;
  /** Source title (falls back to the sourceId). */
  title?: ReactNode;
  /** Supporting line under the title: source kind, capture time, … */
  description?: ReactNode;
}

export interface CitationListProps {
  citations: CitationEntry[];
  /** Click a row to jump to its source span (landing in the Sources view). */
  onJump?: (citation: CitationEntry) => void;
  className?: string;
}

function rangeText(c: CitationEntry): string | null {
  if (c.blockStart == null) return null;
  const end = c.blockEnd ?? c.blockStart;
  return end === c.blockStart ? `b${c.blockStart}` : `b${c.blockStart}–b${end}`;
}

/**
 * Citation list: number + source title/id + block range + jump.
 *
 * Set as a footnote apparatus, not as a second body: one hairline closes the prose above,
 * then quiet 12px lines at ink-2 / ink-3 with the rules between them dropped and the leading
 * pulled in. The `[n]` matches the footnote markers in the prose but drops the accent — the
 * blue pencil belongs to the marker in the text, not to the ledger under it. Everything stays
 * clickable and hoverable: a row is the way back to the source span, so hover lifts the ink
 * back up rather than hiding the affordance.
 */
export function CitationList({ citations, onJump, className }: CitationListProps) {
  if (citations.length === 0) return null;
  return (
    <ol className={cn("flex flex-col border-t border-line pt-1", className)}>
      {citations.map((c, i) => {
        const range = rangeText(c);
        const hasReadableTitle = c.title != null;
        const shortId = c.sourceId.length > 12 ? c.sourceId.slice(0, 8) : c.sourceId;
        const body = (
          <>
            <Mono className="w-6 shrink-0 text-12 leading-[1.45] text-ink-3">[{i + 1}]</Mono>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-12 leading-[1.45] text-ink-2 transition-colors duration-120 group-hover/citation:text-ink">
                {c.title ?? c.sourceId}
              </span>
              {c.description != null && (
                <span className="block truncate text-12 leading-[1.45] text-ink-3">
                  {c.description}
                </span>
              )}
            </span>
            {range && (
              <Mono className="shrink-0 text-12 leading-[1.45] text-ink-3">{range}</Mono>
            )}
            {hasReadableTitle && (
              <Mono
                className="hidden max-w-20 shrink-0 truncate text-12 leading-[1.45] text-ink-3 sm:block"
                title={c.sourceId}
              >
                {shortId}
              </Mono>
            )}
          </>
        );
        return (
          <li key={`${c.sourceId}-${range ?? i}`}>
            {onJump ? (
              <button
                type="button"
                onClick={() => onJump(c)}
                className="group/citation flex w-full items-baseline gap-2 rounded-1 px-1 py-0.5 text-left transition-colors duration-120 hover:bg-hover"
              >
                {body}
              </button>
            ) : (
              <div className="flex items-baseline gap-2 px-1 py-0.5">{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
