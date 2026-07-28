import type { TokenUsage } from "@/lib/api";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

/** 一次调用的 token 用量，mono 单行（ask 逐轮 / cue 评估账用）。 */
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
