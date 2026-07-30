import type { SuggestionDropped } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/useT";
import { cn } from "@/ui/cn";

export interface GateLedgerProps {
  dropped: SuggestionDropped;
  className?: string;
}

/**
 * Five columns: gate name + severity (the text colour once the count is > 0). `uncited` is
 * the citation gate's front door, so it reads danger; the rest read warn. A zero is ink-3.
 */
const GATES: {
  key: keyof SuggestionDropped;
  label: MessageKey;
  tone: "danger" | "warn";
}[] = [
  { key: "unparsed", label: "common.gate.unparsed", tone: "warn" },
  { key: "repeat", label: "common.gate.repeat", tone: "warn" },
  { key: "uncited", label: "common.gate.uncited", tone: "danger" },
  { key: "low_confidence", label: "common.gate.low_confidence", tone: "warn" },
  { key: "capped", label: "common.gate.capped", tone: "warn" },
];

/**
 * The suggestion gate ledger: what a gate ate is never shown, only counted here.
 */
export function GateLedger({ dropped, className }: GateLedgerProps) {
  const t = useT();
  return (
    <dl
      className={cn(
        "grid grid-cols-2 gap-px overflow-hidden rounded-2 border border-line bg-line sm:grid-cols-5",
        className,
      )}
      aria-label={t("common.gate.aria")}
    >
      {GATES.map(({ key, label, tone }) => {
        const n = dropped[key] ?? 0;
        return (
          <div key={key} className="flex flex-col gap-1 bg-surface px-3 py-2.5">
            <dt className="text-12 text-ink-3">{t(label)}</dt>
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
