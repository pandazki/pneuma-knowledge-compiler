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

import { Activity } from "lucide-react";
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

      {answer != null && delegation.preliminary && (
        <details className="mt-2 pl-6 text-13">
          <summary className="cursor-pointer text-ink-3">{t("call.trace.first")}</summary>
          <p className="prose mt-2 text-ink-2">{delegation.preliminary}</p>
        </details>
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

      <details className="mt-2 pl-6 text-13">
        <summary aria-label={t("call.trace.title")} title={t("call.trace.title")} className="inline-flex size-7 cursor-pointer list-none items-center justify-center rounded-1 text-ink-2 hover:bg-hover [&::-webkit-details-marker]:hidden"><Activity size={14} aria-hidden /><span className="sr-only">{t("call.trace.title")}</span></summary>
        <p className="mt-2 text-12 text-ink-3">{t("call.trace.note")}</p>
        <Mono className="mt-2 block break-all text-12">{delegation.provider_id || delegation.id}</Mono>
        <ol className="mt-2 space-y-1 text-12 text-ink-3">
          {Object.entries(delegation.timings).sort((a, b) => a[1] - b[1]).map(([stage, ms]) => (
            <li key={stage}>+{(ms / 1000).toFixed(3)}s · {stage}</li>
          ))}
        </ol>
        <ol className="mt-3 space-y-3">
          {(delegation.updates ?? []).map((update) => (
            <li key={update.event_id} className="border-t border-line pt-2">
              <p className="text-12 text-ink-3">+{(update.sent_ms / 1000).toFixed(3)}s · {update.phase} · {update.state}</p>
              <Mono className="block break-all text-12 text-ink-3">{update.type} · {update.event_id}</Mono>
              <p className="prose mt-1 whitespace-pre-wrap text-ink-2">{update.content}</p>
              {update.ack_ms != null && update.start_ms != null && update.end_ms != null && (
                <p className="mt-1 text-12 text-ink-3">{t("call.trace.ack", {
                  time: (update.ack_ms / 1000).toFixed(3), start: (update.start_ms / 1000).toFixed(3), end: (update.end_ms / 1000).toFixed(3),
                })}</p>
              )}
              {update.error && <p className="text-12 text-danger">{update.error}</p>}
            </li>
          ))}
        </ol>
        {!!delegation.owner_changes?.length && <div className="mt-3">
          <p className="text-12 text-ink-3">{t("call.trace.change")}</p>
          {delegation.owner_changes.map((change, i) => <p key={i} className="prose text-13">+{(change.ms / 1000).toFixed(3)}s · {change.action} · {change.text}</p>)}
        </div>}
        {!!delegation.observed_speech?.length && <div className="mt-3">
          <p className="text-12 text-ink-3">{t("call.trace.speech")}</p>
          <p className="prose mt-1 text-ink-2">{delegation.observed_speech.map(fragment => fragment.delta).join("")}</p>
        </div>}
        <button type="button" className="mt-3 text-12 text-accent" onClick={() => {
          const url = URL.createObjectURL(new Blob([JSON.stringify(delegation, null, 2)], { type: "application/json" }));
          const link = document.createElement("a"); link.href = url; link.download = `delegation-${delegation.id}.json`; link.click();
          setTimeout(() => URL.revokeObjectURL(url), 1000);
        }}>{t("call.trace.export")}</button>
      </details>

      {delegation.state === "done" && answer == null && delegation.said === "" && (
        <Mono className="mt-2 block pl-6 text-12 text-ink-3">{delegation.detail}</Mono>
      )}
    </article>
  );
}
