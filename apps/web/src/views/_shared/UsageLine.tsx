import type { TokenUsage } from "@/lib/api";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/**
 * One call's token usage, as a single mono line — used per turn in Ask and for the suggestion
 * evaluation ledger. Every word in it is a field name, so there is nothing to translate.
 */
export function UsageLine({ usage, className }: { usage: TokenUsage; className?: string }) {
  return (
    <p className={cn("text-12 text-ink-3", className)}>
      <Mono>
        in {usage.input_tokens} · out {usage.output_tokens} · total {usage.total_tokens} ·
        cache_read {usage.cache_read} · cache_creation {usage.cache_creation}
      </Mono>
    </p>
  );
}
