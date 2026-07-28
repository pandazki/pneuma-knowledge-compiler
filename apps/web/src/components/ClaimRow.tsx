import type { Claim, Citation } from "@/lib/types";
import { Badge } from "@/ui/Badge";
import { Footnote } from "@/ui/Footnote";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

export interface ClaimRowProps {
  claim: Claim;
  /** 脚注点击 → source span 落点（通常接 store.focusSource）。 */
  onJumpCitation?: (citation: Citation) => void;
  className?: string;
}

const FLAG_LABEL: Record<string, string> = {
  disputed: "有争议",
  open_question: "待决问题",
  inferred: "推断",
};

/**
 * canonical claim 一行：serif 正文 + 上标脚注序列 + mono 锚点；
 * flag 以页边注呈现（≥md 显示在右侧边栏，窄屏落到正文下方）。
 */
export function ClaimRow({ claim, onJumpCitation, className }: ClaimRowProps) {
  const flags = claim.flags ?? [];
  const notes = claim.notes ?? {};

  const marginalia = flags.length > 0 && (
    <div className="flex flex-row flex-wrap gap-2 md:flex-col md:flex-nowrap">
      {flags.map((flag) => (
        <div key={flag} className="flex flex-col gap-1">
          <Badge tone="warn">{FLAG_LABEL[flag] ?? flag}</Badge>
          {notes[flag as keyof typeof notes] && (
            <p className="max-w-44 text-12 leading-relaxed text-ink-3">
              {notes[flag as keyof typeof notes]}
            </p>
          )}
        </div>
      ))}
    </div>
  );

  return (
    <div className={cn("flex flex-col gap-2 py-3 md:flex-row md:gap-6", className)}>
      <div className="min-w-0 flex-1">
        <p className="prose">
          {claim.text}
          {claim.citations.map((c, i) => (
            <Footnote
              key={`${c.source_id}-${c.from}-${i}`}
              index={i + 1}
              citation={{
                sourceId: c.source_id,
                blockStart: c.from,
                blockEnd: c.to,
                snippet: c.redaction_state === "withheld" ? undefined : c.snippet,
              }}
              onJump={
                onJumpCitation ? () => onJumpCitation(c) : undefined
              }
            />
          ))}
        </p>
        {claim.anchor && (
          <Mono className="mt-1 block text-12 text-ink-3">⚓ {claim.anchor}</Mono>
        )}
      </div>
      {marginalia && <aside className="shrink-0 md:w-44 md:border-l md:border-line md:pl-4">{marginalia}</aside>}
    </div>
  );
}
