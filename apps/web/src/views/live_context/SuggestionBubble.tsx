/**
 * The live suggestion: one card, one countdown, one queue behind it.
 *
 * This is the product surface of the whole feature. Everything else on the page is a bench —
 * knobs, ledgers, frames — but this is what a real context client would show a person mid
 * conversation, so it is shaped like an interruption that respects them: it arrives, it states
 * its business, and it leaves on its own after thirty seconds unless it is wanted.
 *
 * The **ring** is the honest part. A suggestion that vanished without warning would feel like a
 * glitch; a ring draining tells the reader exactly how long they have and makes the
 * disappearance their expectation rather than a surprise. `want more` stops it — the expansion
 * arrives over the socket seconds later, and a card that expired while its own answer was in
 * flight would deliver the answer to nobody.
 *
 * The **"+N" badge** is the promise that nothing was thrown away. Evaluations can land two
 * cards a second apart; the queue means the second one waits its turn instead of replacing the
 * first, and the badge is how the reader knows it exists.
 */

import { Pin, X } from "lucide-react";
import type { ContextSuggestion, SuggestionDetailFrame } from "@/lib/api";
import type { ActiveSuggestion } from "@/lib/suggestionQueue";
import { SUGGESTION_TTL_MS } from "@/lib/suggestionQueue";
import { useT } from "@/lib/useT";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { WebCitationList } from "@/components/WebCitationList";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { IconButton } from "@/ui/IconButton";
import { Mono } from "@/ui/Mono";
import { Spinner } from "@/ui/Spinner";
import { cn } from "@/ui/cn";
import { UsageLine } from "../_shared/UsageLine";

const RING = 15; // radius, in the 36×36 viewBox below
const CIRCUMFERENCE = 2 * Math.PI * RING;

/**
 * The countdown ring. An SVG arc rather than a CSS transition, because the fraction is
 * computed from timestamps (`remainingFraction(state, now)`) — so a tab that was backgrounded
 * for a minute draws the truth on its first frame back, instead of resuming an animation from
 * wherever it was paused.
 */
function CountdownRing({
  fraction,
  seconds,
  pinned,
}: {
  fraction: number;
  seconds: number;
  pinned: boolean;
}) {
  const t = useT();
  return (
    <span
      className="relative inline-flex size-9 shrink-0 items-center justify-center"
      title={pinned ? t("liveContext.bubble.pinnedTitle") : t("liveContext.bubble.countdownTitle", { seconds })}
    >
      <svg viewBox="0 0 36 36" className="size-9 -rotate-90" aria-hidden>
        <circle cx="18" cy="18" r={RING} fill="none" stroke="var(--line)" strokeWidth="2" />
        <circle
          cx="18"
          cy="18"
          r={RING}
          fill="none"
          stroke={pinned ? "var(--accent)" : "var(--ink-3)"}
          strokeWidth="2"
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={CIRCUMFERENCE * (1 - fraction)}
        />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center">
        {pinned ? (
          <Pin size={12} className="text-accent" aria-hidden />
        ) : (
          <Mono className="text-11 text-ink-3">{seconds}</Mono>
        )}
      </span>
      <span className="sr-only">
        {pinned ? t("liveContext.bubble.pinnedTitle") : t("liveContext.bubble.countdownTitle", { seconds })}
      </span>
    </span>
  );
}

export interface SuggestionBubbleProps {
  card: ActiveSuggestion;
  /** 1 → full ring, 0 → gone. Recomputed from the clock by the view, never animated. */
  fraction: number;
  seconds: number;
  /** How many are waiting behind this one — the "+N" badge. */
  queued: number;
  kindLabel: string;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
  onWantMore: () => void;
  onDismiss: () => void;
  /** want_more travels on the long-lived socket; without one, pinning still works. */
  canExpand: boolean;
  pending: boolean;
  detail?: SuggestionDetailFrame;
  failure?: string;
}

export function SuggestionBubble({
  card,
  fraction,
  seconds,
  queued,
  kindLabel,
  titles,
  onJump,
  onWantMore,
  onDismiss,
  canExpand,
  pending,
  detail,
  failure,
}: SuggestionBubbleProps) {
  const t = useT();
  const suggestion: ContextSuggestion = card.suggestion;
  const isWeb = suggestion.kind === "web";
  const webCitations = suggestion.web_citations ?? [];
  // `want_more` fetches a card's own citations VERBATIM out of the owner's store and asks a
  // model to expand within them. A web card has no source block to fetch, so there is
  // nothing to expand within — the honest surface is the pages themselves, which are one
  // click away above. Hiding the affordance is better than offering one that would fail.
  const expandable = !isWeb;
  return (
    <article
      className={cn(
        "relative rounded-2 border bg-raised p-4 shadow-overlay transition-colors",
        card.pinned ? "border-accent-line" : "border-line-2",
      )}
      aria-live="polite"
    >
      {queued > 0 && (
        <span
          className="absolute -right-2 -top-2 inline-flex min-w-6 items-center justify-center rounded-full border border-accent-line bg-accent-soft px-1.5 py-0.5 text-11 font-medium text-accent"
          title={t("liveContext.bubble.queuedTitle", { count: queued })}
        >
          +{queued}
        </span>
      )}

      <div className="flex items-start gap-3">
        <CountdownRing fraction={fraction} seconds={seconds} pinned={card.pinned} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <h3 className="text-14 font-medium text-ink">{suggestion.title}</h3>
            {/* A web card says so on its face. Not decoration: this card's words came from
                outside the library, its citations point at pages rather than at anything
                the owner said, and a reader deciding how much to trust it is entitled to
                know that before they read the lede rather than after. */}
            <Badge tone={isWeb ? "accent" : "neutral"}>
              {isWeb ? t("liveContext.card.webBadge") : kindLabel}
            </Badge>
            <Mono className="text-11 text-ink-3">confidence {suggestion.confidence}</Mono>
            {card.seq !== null && <Mono className="text-11 text-ink-3">seq {card.seq}</Mono>}
          </div>
          {/* The LEDE — the guess at what this reader needs right now. One or two sentences,
              capped server-side, and the only text on this card a model wrote. */}
          <p className="prose mt-2 text-14">{suggestion.body}</p>
          {suggestion.evidence && (
            // Collapsed, and that is the argument: the evidence is what the library actually
            // says, verbatim and unrewritten, and it earns its place UNDER the guess rather
            // than in front of it. Someone who wants to check reads it; someone mid
            // conversation does not have to.
            <details className="mt-2 rounded-2 border border-line bg-surface px-2 py-1.5">
              <summary className="cursor-pointer select-none text-12 text-ink-3">
                {/* A web card's evidence is not what the LIBRARY says, and labelling it so
                    would be the one dishonest sentence on an otherwise honest card. */}
                {t(isWeb ? "liveContext.card.evidenceWeb" : "liveContext.card.evidence")}
              </summary>
              <pre className="mt-1.5 whitespace-pre-wrap break-words font-sans text-12 text-ink-2">
                {suggestion.evidence}
              </pre>
            </details>
          )}
          <p className="mt-2 text-12 text-ink-3">
            {t("liveContext.card.trigger", { trigger: suggestion.trigger })}
          </p>
          {/* One apparatus, two destinations. A card carries one list or the other — never
              both — and which it is, is stated by `kind` rather than sniffed for. */}
          {suggestion.citations.length > 0 && (
            <CitationList
              className="mt-2"
              citations={suggestion.citations.map((c) => ({
                sourceId: c.source_id,
                blockStart: c.block_start,
                blockEnd: c.block_end,
                title: titles[c.source_id],
              }))}
              onJump={onJump}
            />
          )}
          {webCitations.length > 0 && (
            <WebCitationList className="mt-2" citations={webCitations} />
          )}
        </div>
        <IconButton
          size="md"
          aria-label={t("liveContext.bubble.dismiss")}
          title={t("liveContext.bubble.dismissTitle")}
          onClick={onDismiss}
        >
          <X size={14} aria-hidden />
        </IconButton>
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        {expandable ? (
          <Button
            size="sm"
            variant={card.pinned ? "ghost" : "primary"}
            onClick={onWantMore}
            disabled={card.pinned && !canExpand}
            title={canExpand ? t("liveContext.bubble.wantMoreTitle") : t("liveContext.card.wantMoreDisabled")}
          >
            {t("liveContext.bubble.wantMore")}
          </Button>
        ) : (
          <span className="text-12 text-ink-3">{t("liveContext.card.webNoExpand")}</span>
        )}
        {pending && (
          <span className="inline-flex items-center gap-1.5 text-12 text-ink-3">
            <Spinner size={12} /> {t("liveContext.bubble.expanding")}
          </span>
        )}
        {card.pinned && !pending && !detail && !failure && (
          <span className="text-12 text-ink-3">
            {canExpand ? t("liveContext.bubble.pinnedNote") : t("liveContext.bubble.pinnedNoSocket")}
          </span>
        )}
      </div>

      {failure && (
        <Callout tone="danger" className="mt-3">
          {t("liveContext.card.expandFailed", { detail: failure })}
        </Callout>
      )}
      {detail && (
        <div className="mt-3 border-t border-line pt-3">
          <p className="prose text-14">{detail.detail || t("liveContext.card.detailEmpty")}</p>
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
          <UsageLine usage={detail.token_usage} className="mt-1" />
        </div>
      )}
    </article>
  );
}

/** The TTL, re-exported so the view's ticker and this component cannot disagree about it. */
export { SUGGESTION_TTL_MS };
