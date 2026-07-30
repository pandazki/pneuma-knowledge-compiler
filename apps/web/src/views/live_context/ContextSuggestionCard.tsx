import type { ContextSuggestion, SuggestionDetailFrame } from "@/lib/api";
import { useT } from "@/lib/useT";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Mono } from "@/ui/Mono";
import { UsageLine } from "../_shared/UsageLine";

export interface ContextSuggestionCardProps {
  suggestion: ContextSuggestion;
  /** Display name for the kind, localised by the caller (absent → the kind key shows). */
  kindLabel?: string;
  /** Arrival-channel note, e.g. "ws · seq 3" / "sse". */
  via?: string;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
  /** want_more expansion (WS only): omit and the card has no expansion area. */
  canExpand?: boolean;
  pending?: boolean;
  /** This card's own expansion failure (attributed by ref, never crossed with another). */
  failure?: string;
  detail?: SuggestionDetailFrame;
  onWantMore?: () => void;
}

/**
 * One context suggestion: title + serif body + the trigger line + confidence in mono +
 * citations. What a gate ate never appears here — only in the GateLedger's counts.
 *
 * `title` / `body` / `trigger` and the citations are server payload, rendered verbatim.
 */
export function ContextSuggestionCard({
  suggestion,
  kindLabel,
  via,
  titles,
  onJump,
  canExpand,
  pending,
  failure,
  detail,
  onWantMore,
}: ContextSuggestionCardProps) {
  const t = useT();
  return (
    <article className="border-b border-line py-4">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="text-14 font-medium text-ink">{suggestion.title}</span>
        <Badge>{kindLabel ?? suggestion.kind}</Badge>
        <Mono className="text-12 text-ink-3">confidence {suggestion.confidence}</Mono>
        {via && <Mono className="text-12 text-ink-3">{via}</Mono>}
      </div>
      <p className="prose mt-2 max-w-measure text-14">{suggestion.body}</p>
      <p className="mt-2 text-12 text-ink-3">
        {t("liveContext.card.trigger", { trigger: suggestion.trigger })}
      </p>
      {suggestion.citations.length > 0 && (
        <CitationList
          className="mt-2 max-w-measure"
          citations={suggestion.citations.map((c) => ({
            sourceId: c.source_id,
            blockStart: c.block_start,
            blockEnd: c.block_end,
            title: titles[c.source_id],
          }))}
          onJump={onJump}
        />
      )}

      {onWantMore && (
        <div className="mt-3">
          <Button
            size="sm"
            loading={pending}
            disabled={!canExpand}
            title={
              canExpand
                ? t("liveContext.card.wantMoreTitle")
                : t("liveContext.card.wantMoreDisabled")
            }
            onClick={onWantMore}
          >
            {failure ? t("liveContext.card.wantMoreRetry") : t("liveContext.card.wantMore")}
          </Button>
        </div>
      )}
      {failure && (
        <Callout tone="danger" className="mt-2 max-w-measure">
          {t("liveContext.card.expandFailed", { detail: failure })}
        </Callout>
      )}
      {detail && (
        <div className="mt-3 max-w-measure border-l-2 border-line-2 pl-3">
          <p className="text-12 text-ink-3">suggestion_detail</p>
          <p className="prose mt-1 text-14 whitespace-pre-wrap">
            {detail.detail || t("liveContext.card.detailEmpty")}
          </p>
          {detail.citations.length > 0 && (
            <CitationList
              className="mt-2"
              citations={detail.citations.map((c) => ({
                sourceId: c.source_id,
                blockStart: c.block_start,
                blockEnd: c.block_end,
                title: titles[c.source_id],
              }))}
              onJump={onJump}
            />
          )}
          <UsageLine usage={detail.token_usage} className="mt-2" />
        </div>
      )}
    </article>
  );
}
