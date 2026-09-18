/**
 * One card: a question the voice handed to the library, and what the library answered.
 *
 * The card is the honest half of a call. A voice model paraphrases, hesitates and fills; this
 * column is where the library's OWN answer stands, with its citations, so a reader can hold
 * the two against each other. Which is why the answer is rendered by the same components the
 * Recall view uses for a fast answer — `CitedAnswer` and `UsedClaimRow` — rather than by a
 * second renderer that might one day disagree with the first about what a citation is.
 *
 * While the answer is still being written there is only `said`, the plain text handed over so
 * far. It is shown as plain text and never as an answer: it carries no citations yet, and
 * dressing it as one would be the exact confusion this column exists to prevent.
 */

import { ordinalBadge, type Delegation } from "@/lib/call";
import { formatDelegationSeconds } from "@/lib/call";
import type { RecallAnswer } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import { useT } from "@/lib/useT";
import type { CitationEntry } from "@/components/CitationList";
import { Mono } from "@/ui/Mono";
import { cn } from "@/ui/cn";
import { CitedAnswer } from "../_shared/CitedAnswer";
import { UsedClaimRow } from "../_shared/UsedClaimRow";

/** The three states that are a stage of the work; the other three are said differently. */
const WORKING: Partial<Record<Delegation["state"], MessageKey>> = {
  hearing: "call.cards.hearing",
  searching: "call.cards.searching",
  answering: "call.cards.answering",
};

/**
 * The engine hands the recall payload through untouched (`answer: unknown`), so it is checked
 * here before it is rendered rather than asserted: a shape this console does not recognise
 * leaves the card showing what it does know — the ask, the state, the text already spoken.
 */
export function asRecallAnswer(answer: unknown): RecallAnswer | null {
  if (answer == null || typeof answer !== "object") return null;
  const candidate = answer as { answer?: unknown };
  return typeof candidate.answer === "string" ? (answer as RecallAnswer) : null;
}

export function CallAnswerCard({
  delegation,
  ordinal,
  titles,
  onJump,
  highlighted,
}: {
  delegation: Delegation;
  ordinal: number;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
  /** The caption row that speaks this card was clicked: the card says which one it is. */
  highlighted: boolean;
}) {
  const t = useT();
  const answer = asRecallAnswer(delegation.answer);
  const working = WORKING[delegation.state];
  const state =
    working != null
      ? t(working)
      : delegation.state === "done"
        ? t("call.cards.done", { seconds: formatDelegationSeconds(delegation.elapsed_ms) || "—" })
        : delegation.detail || delegation.state;
  const claims = answer?.used_claims ?? [];
  // Where the wait went, hung off the duration rather than laid out beside it: a finished card
  // owes the reader one number, and the breakdown is for the call that felt slow.
  const breakdown = Object.entries(delegation.timings)
    .sort((a, b) => a[1] - b[1])
    .map(([stage, ms]) => `${stage} ${(ms / 1000).toFixed(1)}s`)
    .join(" · ");

  return (
    <article
      id={`call-card-${delegation.id}`}
      className={cn(
        "border-b border-line px-2 py-3 transition-colors duration-200 ease-out",
        highlighted && "bg-accent-soft",
      )}
    >
      <div className="flex items-baseline gap-2">
        <span className="shrink-0 text-13 text-accent" aria-hidden>
          {ordinalBadge(ordinal)}
        </span>
        <h3 className="prose min-w-0 flex-1 text-14 text-ink">
          {delegation.ask || state}
        </h3>
      </div>
      <p
        title={breakdown || undefined}
        className={cn(
          "mt-1 pl-6 text-12",
          delegation.state === "failed" ? "text-danger" : "text-ink-3",
        )}
      >
        {/* The title already says it while the ask is still being heard — not twice. */}
        {delegation.ask ? state : ""}
      </p>
      {!delegation.spoken && (
        <p className="mt-1 pl-6 text-12 text-warn">{t("call.cards.unspoken")}</p>
      )}

      {answer != null ? (
        <>
          <div className="prose mt-2 max-w-measure pl-6 text-14">
            <CitedAnswer text={answer.answer} handles={answer.citation_handles} />
          </div>
          {claims.length > 0 && (
            <div className="mt-2 pl-6">
              <p className="text-12 text-ink-3">
                {t("call.cards.claims", { count: claims.length })}
              </p>
              <div className="border-t border-line">
                {claims.map((claim) => (
                  <UsedClaimRow
                    key={claim.anchor}
                    claim={claim}
                    titles={titles}
                    onJump={onJump}
                    showScore={false}
                  />
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        delegation.said !== "" && (
          <div className="mt-2 pl-6">
            <p className="text-12 text-ink-3">{t("call.cards.said")}</p>
            <p className="prose max-w-measure text-14 text-ink-2">{delegation.said}</p>
          </div>
        )
      )}

      {delegation.state === "done" && answer == null && delegation.said === "" && (
        <Mono className="mt-2 block pl-6 text-12 text-ink-3">{delegation.detail}</Mono>
      )}
    </article>
  );
}
