import type { SuggestionDropped } from "@/lib/api";
import { cn } from "@/ui/cn";

export interface GateLedgerProps {
  dropped: SuggestionDropped;
  className?: string;
}

/**
 * 五栏：label / 中文名 / 严重度（>0 时的文字色）。
 * uncited 是引用门禁的正门，记 danger；其余记 warn。0 栏一律 ink-3。
 */
const GATES: { key: keyof SuggestionDropped; label: string; tone: "danger" | "warn" }[] = [
  { key: "unparsed", label: "无法解析", tone: "warn" },
  { key: "repeat", label: "重复", tone: "warn" },
  { key: "uncited", label: "无引用", tone: "danger" },
  { key: "low_confidence", label: "低置信", tone: "warn" },
  { key: "capped", label: "超限", tone: "warn" },
];

/**
 * suggestion 门禁账：被门禁吃掉的内容不展示原文，只在这本账里留下计数。
 */
export function GateLedger({ dropped, className }: GateLedgerProps) {
  return (
    <dl
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-2 border border-line bg-line sm:grid-cols-5",
        className,
      )}
      aria-label="门禁计数"
    >
      {GATES.map(({ key, label, tone }) => {
        const n = dropped[key] ?? 0;
        return (
          <div key={key} className="flex flex-col gap-1 bg-surface px-3 py-2.5">
            <dt className="text-12 text-ink-3">{label}</dt>
            <dd
              className={cn(
                "font-mono text-20 tabular-nums",
                n > 0 ? (tone === "danger" ? "text-danger" : "text-warn") : "text-ink-3",
              )}
            >
              {n}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}
