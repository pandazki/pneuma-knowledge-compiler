import { fmtTime } from "@/lib/format";
import {
  evolveStatusLabel,
  evolveStatusTone,
  fmtTtlRemaining,
  ttlRemainingMs,
  type EvolveTimelineEntry,
} from "@/lib/evolve";
import { EVOLVE_DRAFT_TTL_HOURS } from "@/lib/api";
import { Badge } from "@/ui/Badge";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * 演化时间线：一次演化一条账，按时间倒序（最新在上）。
 *
 * 视觉沿用 DESIGN.md 的「标尺线」语汇——一条发丝竖线串起编号刻度，不是线路图：
 * 刻度形状承担状态冗余编码（实心=已采用、菱形=闸门待审、空心=已否决），
 * 语义色只给真实状态。
 */

/** 刻度：形状 + 墨阶/语义色双重编码，色盲下靠形状仍可读。 */
function StationMark({ entry }: { entry: EvolveTimelineEntry }) {
  const { status } = entry;
  if (entry.awaitingReview) {
    return (
      <span
        aria-hidden
        className="relative z-1 mt-1.5 size-2.5 rotate-45 border-2 border-warn bg-bg"
      />
    );
  }
  if (status === "adopted") {
    return <span aria-hidden className="relative z-1 mt-1.5 size-2.5 bg-ok" />;
  }
  if (status === "aborted") {
    return (
      <span
        aria-hidden
        className="relative z-1 mt-1.5 size-2.5 border-2 border-danger bg-bg"
      />
    );
  }
  if (entry.pending) {
    return (
      <span
        aria-hidden
        className="relative z-1 mt-1.5 size-2.5 rounded-full border-2 border-accent bg-bg"
      />
    );
  }
  return (
    <span aria-hidden className="relative z-1 mt-1.5 size-2.5 border border-line-2 bg-bg" />
  );
}

function scaleLine(entry: EvolveTimelineEntry): string {
  const { scale } = entry;
  const parts: string[] = [];
  if (scale.newDocuments > 0) parts.push(`新建 ${scale.newDocuments} 篇`);
  if (scale.movedClaims > 0) parts.push(`搬移 ${scale.movedClaims} 条`);
  if (scale.mergedClaims > 0) parts.push(`合并 ${scale.mergedClaims} 条`);
  if (parts.length === 0) return "无机械规模摘要";
  return parts.join(" · ");
}

export function EvolveTimelineRow({
  entry,
  selected,
  first,
  last,
  onSelect,
}: {
  entry: EvolveTimelineEntry;
  selected: boolean;
  first: boolean;
  last: boolean;
  onSelect: () => void;
}) {
  const ttl = entry.awaitingReview
    ? ttlRemainingMs(entry.createdAt, EVOLVE_DRAFT_TTL_HOURS)
    : null;
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected || undefined}
        className={cn(
          "grid w-full grid-cols-[auto_minmax(0,1fr)] gap-3 px-3 py-3 text-left",
          "transition-colors duration-120 ease-out",
          selected ? "bg-accent-soft" : "hover:bg-hover",
        )}
      >
        {/* 标尺线 + 刻度（刻度中心距行顶 11px：mt-1.5 + 半个刻度） */}
        <span className="relative flex w-2.5 justify-center">
          {!(first && last) && (
            <span
              aria-hidden
              className={cn(
                "absolute left-1/2 w-px -translate-x-1/2 bg-line",
                first ? "top-[11px] bottom-0" : last ? "top-0 h-[11px]" : "top-0 bottom-0",
              )}
            />
          )}
          <StationMark entry={entry} />
        </span>

        <span className="flex min-w-0 flex-col gap-1">
          <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span className="font-serif text-14 font-medium text-ink">
              第 {entry.ordinal} 次演化
            </span>
            <Badge tone={evolveStatusTone(entry.status)}>
              {evolveStatusLabel(entry.status)}
            </Badge>
            {ttl != null && (
              <span className="text-12 text-ink-3">{fmtTtlRemaining(ttl)}</span>
            )}
          </span>

          <span className="text-12 text-ink-3">
            {fmtTime(entry.createdAt)}
            {entry.decidedAt != null && ` · 决定 ${fmtTime(entry.decidedAt)}`}
          </span>

          {entry.families.length > 0 ? (
            <span className="flex flex-wrap gap-1">
              {entry.families.map((family) => (
                <Mono
                  key={family}
                  className="rounded-1 border border-line-2 bg-surface px-1.5 py-px text-12 text-ink-2"
                >
                  +{family}
                </Mono>
              ))}
            </span>
          ) : (
            <span className="text-12 text-ink-3">未提出新 family</span>
          )}

          <span className="text-12 text-ink-2">{scaleLine(entry)}</span>
        </span>
      </button>
    </li>
  );
}

export function EvolveTimeline({
  entries,
  selectedTaskId,
  onSelect,
  className,
}: {
  entries: EvolveTimelineEntry[];
  selectedTaskId: string | null;
  onSelect: (taskId: string) => void;
  className?: string;
}) {
  return (
    <ol className={cn("border-y border-line", className)}>
      {entries.map((entry, index) => (
        <EvolveTimelineRow
          key={entry.taskId}
          entry={entry}
          selected={entry.taskId === selectedTaskId}
          first={index === 0}
          last={index === entries.length - 1}
          onSelect={() => onSelect(entry.taskId)}
        />
      ))}
    </ol>
  );
}
