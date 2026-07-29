import type { ReactNode } from "react";
import { cn } from "@/ui/cn";
import { Mono } from "@/ui/Mono";

export interface CitationEntry {
  sourceId: string;
  blockStart?: number | null;
  blockEnd?: number | null;
  /** source 标题（缺省显示 sourceId）。 */
  title?: ReactNode;
  /** 标题下方的来源类型、时间等辅助信息。 */
  description?: ReactNode;
}

export interface CitationListProps {
  citations: CitationEntry[];
  /** 点击某条跳 source span（sources 视图落点）。 */
  onJump?: (citation: CitationEntry) => void;
  className?: string;
}

function rangeText(c: CitationEntry): string | null {
  if (c.blockStart == null) return null;
  const end = c.blockEnd ?? c.blockStart;
  return end === c.blockStart ? `b${c.blockStart}` : `b${c.blockStart}–b${end}`;
}

/** 引用列表：编号 + source 标题/id + block 区间 + 跳转。 */
export function CitationList({ citations, onJump, className }: CitationListProps) {
  if (citations.length === 0) return null;
  return (
    <ol className={cn("flex flex-col border-t border-line", className)}>
      {citations.map((c, i) => {
        const range = rangeText(c);
        const hasReadableTitle = c.title != null;
        const shortId = c.sourceId.length > 12 ? c.sourceId.slice(0, 8) : c.sourceId;
        const body = (
          <>
            <Mono className="w-7 shrink-0 text-12 text-accent">[{i + 1}]</Mono>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-13 text-ink">
                {c.title ?? c.sourceId}
              </span>
              {c.description != null && (
                <span className="mt-0.5 block truncate text-12 text-ink-3">
                  {c.description}
                </span>
              )}
            </span>
            {range && <Mono className="shrink-0 text-12 text-ink-3">{range}</Mono>}
            {hasReadableTitle && (
              <Mono
                className="hidden max-w-24 shrink-0 truncate text-12 text-ink-3 sm:block"
                title={c.sourceId}
              >
                {shortId}
              </Mono>
            )}
          </>
        );
        return (
          <li key={`${c.sourceId}-${range ?? i}`} className="border-b border-line">
            {onJump ? (
              <button
                type="button"
                onClick={() => onJump(c)}
                className="flex w-full items-start gap-2 px-1 py-2 text-left transition-colors duration-120 hover:bg-hover"
              >
                {body}
              </button>
            ) : (
              <div className="flex items-start gap-2 px-1 py-2">{body}</div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
