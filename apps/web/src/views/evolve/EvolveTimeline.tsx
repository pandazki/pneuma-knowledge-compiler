import { fmtTime } from "@/lib/format";
import {
  evolveStatusLabelKey,
  evolveStatusTone,
  ttlRemainingMessage,
  ttlRemainingMs,
  type EvolveTimelineEntry,
} from "@/lib/evolve";
import { EVOLVE_DRAFT_TTL_HOURS } from "@/lib/api";
import { useT, useTOr, type TFunction } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * The evolution timeline: one row per evolution, newest at the top.
 *
 * The visual keeps DESIGN.md's "ruler line" vocabulary — a hairline vertical rule threading
 * numbered stations, not a circuit diagram. The station's SHAPE carries the status redundantly
 * (filled = adopted, diamond = at the gate, hollow = declined), and semantic colour is
 * reserved for real states.
 */

/** A station: shape plus ink/semantic colour, so it still reads by shape alone. */
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

function scaleLine(entry: EvolveTimelineEntry, t: TFunction): string {
  const { scale } = entry;
  const parts: string[] = [];
  if (scale.newDocuments > 0)
    parts.push(t("evolve.scale.newDocuments", { count: scale.newDocuments }));
  if (scale.movedClaims > 0)
    parts.push(t("evolve.scale.moved", { count: scale.movedClaims }));
  if (scale.mergedClaims > 0)
    parts.push(t("evolve.scale.merged", { count: scale.mergedClaims }));
  if (parts.length === 0) return t("evolve.scale.none");
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
  const t = useT();
  const tOr = useTOr();
  const ttl = entry.awaitingReview
    ? ttlRemainingMs(entry.createdAt, EVOLVE_DRAFT_TTL_HOURS)
    : null;
  const ttlMessage = ttl != null ? ttlRemainingMessage(ttl) : null;
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
        {/* The ruler line + the station (station centre 11px below the row top: mt-1.5 + half a station) */}
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
              {t("evolve.evolutionOrdinal", { n: entry.ordinal })}
            </span>
            <Badge tone={evolveStatusTone(entry.status)}>
              {tOr(evolveStatusLabelKey(entry.status), entry.status)}
            </Badge>
            {ttlMessage && (
              <span className="text-12 text-ink-3">
                {t(ttlMessage.key, ttlMessage.params)}
              </span>
            )}
          </span>

          <span className="text-12 text-ink-3">
            {fmtTime(entry.createdAt)}
            {entry.decidedAt != null &&
              ` · ${t("evolve.decided", { at: fmtTime(entry.decidedAt) })}`}
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
            <span className="text-12 text-ink-3">{t("evolve.timeline.noNewFamily")}</span>
          )}

          <span className="text-12 text-ink-2">{scaleLine(entry, t)}</span>
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
