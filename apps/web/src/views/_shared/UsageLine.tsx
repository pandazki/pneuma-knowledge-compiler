import type { TokenUsage } from "@/lib/api";
import { fmtCount } from "@/lib/format";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * One call's token usage, as a single mono line — the ONE token ledger in the app: per turn in
 * Ask, per answer in Recall (which used to draw the same five numbers as a four-row definition
 * list), and in the suggestion evaluation ledger.
 *
 * Every word in it is a field name, so there is nothing to translate. The numbers are grouped,
 * like every other count on every other page: `36533` reads as an identifier.
 */
export function UsageLine({ usage, className }: { usage: TokenUsage; className?: string }) {
  return (
    <p className={cn("text-12 text-ink-3", className)}>
      <Mono>
        in {fmtCount(usage.input_tokens)} · out {fmtCount(usage.output_tokens)} · total{" "}
        {fmtCount(usage.total_tokens)} · cache_read {fmtCount(usage.cache_read)} ·
        cache_creation {fmtCount(usage.cache_creation)}
      </Mono>
    </p>
  );
}
