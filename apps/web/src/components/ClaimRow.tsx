import type { Claim, Citation } from "@/lib/types";
import { useTOr } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Footnote } from "@/ui/Footnote";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";

export interface ClaimRowProps {
  claim: Claim;
  /** Footnote click → the source-span landing (usually store.focusSource). */
  onJumpCitation?: (citation: Citation) => void;
  className?: string;
}

/**
 * One canonical claim: serif prose + a superscript footnote sequence + a mono anchor. Flags
 * render as marginalia (a right rail at ≥md, dropping under the prose on a narrow screen).
 */
export function ClaimRow({ claim, onJumpCitation, className }: ClaimRowProps) {
  const tOr = useTOr();
  const flags = claim.flags ?? [];
  const notes = claim.notes ?? {};

  const marginalia = flags.length > 0 && (
    <div className="flex flex-row flex-wrap gap-2 md:flex-col md:flex-nowrap">
      {flags.map((flag) => (
        <div key={flag} className="flex flex-col gap-1">
          <Badge tone="warn">{tOr(`common.flag.${flag}`, flag)}</Badge>
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
