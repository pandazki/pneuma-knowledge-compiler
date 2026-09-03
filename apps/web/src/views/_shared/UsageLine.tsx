import type { Cost, TokenUsage } from "@/lib/api";
import { usageLine } from "@/lib/format";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * One call's token usage, as a single mono line — the ONE token ledger in the app: per turn in
 * Ask, per answer in Recall (which used to draw the same five numbers as a four-row definition
 * list), and in the suggestion evaluation ledger.
 *
 * Every word in it is a field name, so there is nothing to translate. The numbers are grouped,
 * like every other count on every other page: `36533` reads as an identifier.
 *
 * `cost` is the same line's money half, and it appears only when the API supplied one. A
 * deployment that has declared no rates for the model behind this call shows tokens and
 * nothing else — the framework quotes no price of its own, and a `0.00` would claim the
 * call was free rather than unpriced.
 */
export function UsageLine({
  usage,
  cost,
  className,
}: {
  usage: Partial<TokenUsage>;
  cost?: Cost | null;
  className?: string;
}) {
  return (
    <p className={cn("text-12 text-ink-3", className)}>
      <Mono>{usageLine(usage, cost)}</Mono>
    </p>
  );
}
