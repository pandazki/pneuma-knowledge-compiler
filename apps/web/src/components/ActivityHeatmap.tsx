import { CalendarDays } from "lucide-react";
import type { ActivityDay } from "@/lib/api";
import { buildActivityGrid } from "@/lib/activity";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";

const LEVEL_CLASSES = [
  "border-line bg-surface",
  "border-accent-line bg-accent-soft",
  "border-accent-line bg-accent-line",
  "border-accent bg-accent opacity-70",
  "border-accent bg-accent",
] as const;

function levelFor(count: number, maxCount: number): number {
  if (count <= 0 || maxCount <= 0) return 0;
  return Math.max(
    1,
    Math.min(4, Math.ceil((Math.log1p(count) / Math.log1p(maxCount)) * 4)),
  );
}

function activityDescription(
  day: ActivityDay,
  labels: Record<string, string>,
): string {
  const breakdown = Object.entries(day.kinds)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([kind, count]) => `${labels[kind] ?? kind} ${count}`)
    .join(" · ");
  return `${day.date} · ${day.count} 条${breakdown ? ` · ${breakdown}` : ""}`;
}

export function ActivityHeatmap({
  days,
  title,
  kindLabels,
  className,
  compact = false,
}: {
  days: ActivityDay[];
  title: string;
  kindLabels: Record<string, string>;
  className?: string;
  /** Removes the full-width section chrome so the calendar can sit beside a page heading. */
  compact?: boolean;
}) {
  const grid = buildActivityGrid(days);

  return (
    <section
      aria-label={title}
      className={cn(
        compact ? "min-w-0" : "border-y border-line py-3",
        className,
      )}
    >
      <div
        className={cn(
          "flex flex-wrap items-center justify-between gap-3",
          compact ? "mb-2" : "mb-3",
        )}
      >
        <p className="flex items-center gap-2 text-13 text-ink-2">
          <CalendarDays size={14} aria-hidden className="text-accent" />
          <span>{title}</span>
          {grid.firstDate && grid.lastDate && (
            <span className="text-12 text-ink-3">
              {grid.firstDate} — {grid.lastDate}
            </span>
          )}
        </p>
        <div className="flex items-center gap-1.5 text-12 text-ink-3" aria-label="密度图例">
          <span>少</span>
          {LEVEL_CLASSES.map((classes, level) => (
            <span
              key={level}
              aria-hidden
              className={cn("h-3 w-3 rounded-1 border", classes)}
            />
          ))}
          <span>多</span>
        </div>
      </div>

      {grid.cells.length === 0 ? (
        <p className="text-13 text-ink-3">还没有可绘制的活动。</p>
      ) : (
        <div className="overflow-x-auto pb-1">
          <div className="inline-flex min-w-max items-start gap-2">
            <div
              aria-hidden
              className="grid h-[108px] grid-rows-7 gap-1 pt-0.5 text-12 leading-3 text-ink-3"
            >
              <span>一</span>
              <span />
              <span>三</span>
              <span />
              <span>五</span>
              <span />
              <span>日</span>
            </div>
            <div className="grid grid-flow-col grid-rows-7 gap-1">
              {grid.cells.map((cell) => {
                const level = levelFor(cell.count, grid.maxCount);
                if (!cell.active) {
                  return (
                    <span
                      key={cell.date}
                      aria-hidden
                      className={cn("h-3 w-3 rounded-1 border", LEVEL_CLASSES[0])}
                    />
                  );
                }
                const label = activityDescription(cell, kindLabels);
                return (
                  <Tooltip key={cell.date} content={label}>
                    <span
                      tabIndex={0}
                      role="img"
                      aria-label={label}
                      className={cn(
                        "h-3 w-3 rounded-1 border outline-none transition-transform duration-120",
                        "focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-1",
                        "hover:scale-125",
                        LEVEL_CLASSES[level],
                      )}
                    />
                  </Tooltip>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
