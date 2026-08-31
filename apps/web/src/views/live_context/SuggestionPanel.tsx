/**
 * The right-hand column: what the system has to say, and the record of how it said it.
 *
 * TOP is the product — one live bubble with its countdown (`SuggestionBubble`). BOTTOM is the
 * bench, in two tabs, and the split matters: a page that mixed them would either bury the
 * suggestion in instrumentation or hide the instrumentation a bench exists for.
 *
 *   历史提示 — every suggestion that has left the bubble, with its FATE. "Why did I not see
 *     that one" (expired) and "why did that one stay" (pinned) are different questions, and a
 *     history that only listed titles could answer neither.
 *   处理状态 — the debug surface: transport frames, the citation gate's ledger per evaluation,
 *     what deduplication suppressed, the running counts, and the policy the server echoed
 *     back. Silence is this feature's steady state, so "why did nothing fire" is the question
 *     this page gets asked most — and it is answered here, from the server's own counters,
 *     rather than guessed at.
 */

import { RadioTower } from "lucide-react";
import type { ContextSuggestion, LiveContextReadyFrame, LiveContextStatsFrame, SuggestionDetailFrame } from "@/lib/api";
import type { HistoryEntry, QueueState } from "@/lib/suggestionQueue";
import { pendingCount, remainingFraction, remainingSeconds } from "@/lib/suggestionQueue";
import { useT, useTOr } from "@/lib/useT";
import { fmtTime } from "@/lib/format";
import { GateLedger } from "@/components/GateLedger";
import { type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { Tabs } from "@/ui/Tabs";
import { cn } from "@/ui/cn";
import { UsageLine } from "../_shared/UsageLine";
import { SuggestionBubble } from "./SuggestionBubble";

/** One line in the transport log — what went over the wire, and which way. */
export interface WireEvent {
  id: string;
  at: number;
  direction: "in" | "out";
  label: string;
  detail?: string;
}

export interface PanelCounts {
  turnsSent: number;
  suggestions: number;
  /** Suppressed by the client's own {kind,title} deduplication, which is the authority. */
  deduped: number;
  evaluations: number;
}

export interface SuggestionPanelProps {
  queue: QueueState;
  /** Ticked by the view; passed in so this component reads no clock of its own. */
  now: number;
  kindLabel: (kind: string) => string;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
  onWantMore: () => void;
  onDismiss: () => void;
  canExpand: boolean;
  pending: boolean;
  detail?: SuggestionDetailFrame;
  failure?: string;
  /** Per-card expansion books, keyed by the card id the ref resolved back to. */
  details: Record<string, SuggestionDetailFrame>;
  statsLog: LiveContextStatsFrame[];
  wireLog: WireEvent[];
  counts: PanelCounts;
  ready: LiveContextReadyFrame | null;
  tab: string;
  onTabChange: (tab: string) => void;
}

const FATE_TONE = {
  expired: "neutral",
  dismissed: "neutral",
  pinned: "accent",
} as const;

/**
 * One tick, as the bench reads it.
 *
 * Silence is this feature's steady state, so "why did nothing fire" is the question this
 * page gets asked most — and the answer now has three depths, all of them here: the tick
 * never retrieved (`skipped` names which door closed), it retrieved and built nothing, or it
 * built candidates and the pick declined. The per-stage milliseconds sit alongside, because
 * "it was slow" is not an answer to WHICH PART.
 */
function TickRow({ stats, tOr }: { stats: LiveContextStatsFrame; tOr: ReturnType<typeof useTOr> }) {
  const t = useT();
  const stages = (stats.stages ?? []).filter((s) => s.status !== "skipped");
  const dropped = stats.dropped ?? {};
  const hasGates = Object.values(dropped).some((n) => (n ?? 0) > 0);
  return (
    <div>
      <p className="mb-1 flex flex-wrap items-baseline gap-x-2 text-11 text-ink-3">
        <Mono>seq {stats.seq}</Mono>
        <span>{t("liveContext.deliveredCount", { count: stats.delivered })}</span>
        <span>
          focus <Mono>{tOr(`enum.contextFocus.${stats.focus}.label`, stats.focus)}</Mono>
        </span>
        {stats.skipped ? (
          <Badge tone="neutral">
            {tOr(`liveContext.skip.${stats.skipped}`, stats.skipped)}
          </Badge>
        ) : (
          <Badge tone="accent">{t("liveContext.skip.delivered")}</Badge>
        )}
        {stats.worth > 0 && <Mono>worth {stats.worth}</Mono>}
      </p>
      {stats.intent && (
        <p className="mb-1 text-11 text-ink-2">
          {t("liveContext.debug.intent", { intent: stats.intent })}
        </p>
      )}
      {stats.plan?.length > 0 && (
        <p className="mb-1 text-11 text-ink-3">
          <Mono>{stats.plan.join(" · ")}</Mono>
        </p>
      )}
      {stats.candidates?.length > 0 && (
        <ol className="mb-1 flex flex-col gap-0.5">
          {stats.candidates.map((c) => (
            <li
              key={c.index}
              className={cn(
                "flex items-baseline gap-1.5 text-11",
                c.index === stats.chosen ? "text-accent" : "text-ink-3",
              )}
            >
              <Mono>{c.index}</Mono>
              <span className="truncate">{c.title}</span>
              <Mono className="shrink-0">
                {c.kind} · {c.provenance ?? "library"} · {c.origin} · {c.citations}
              </Mono>
            </li>
          ))}
        </ol>
      )}
      {/* What the supplementary internet face did, and what it cost. Shown only when it
          ran: a tick that never reached outside the library has nothing to report here, and
          a row saying "off" on every tick would bury the two that are not. */}
      {stats.web && stats.web.tier !== "off" && (
        <p className="mb-1 text-11 text-ink-3">
          <Mono>
            {t("liveContext.web.line", {
              tier: t(`liveContext.web.tier.${stats.web.tier}` as const),
              searches: stats.web.searches,
              cost: stats.web.cost.toFixed(4),
              pages: stats.web.pages ?? 0,
            })}
          </Mono>
          {/* Billed and cited nothing. Said out loud, because the alternative is a tick
              showing a cost next to an absent card with no stated reason. */}
          {stats.web.searches > 0 && (stats.web.pages ?? 0) === 0 && (
            <span className="ml-2 text-warn">{t("liveContext.web.nopages")}</span>
          )}
        </p>
      )}
      {stages.length > 0 && (
        <p className="mb-1 flex flex-wrap gap-x-3 text-11 text-ink-3">
          {stages.map((stage) => (
            <span key={stage.name}>
              <Mono>{stage.name}</Mono> {stage.ms}ms
              {stage.detail ? ` (${stage.detail})` : ""}
            </span>
          ))}
        </p>
      )}
      {hasGates && <GateLedger dropped={dropped} />}
      <UsageLine usage={stats.token_usage} className="mt-1" />
    </div>
  );
}

function HistoryRow({
  entry,
  kindLabel,
  detail,
}: {
  entry: HistoryEntry;
  kindLabel: (kind: string) => string;
  detail?: SuggestionDetailFrame;
}) {
  const t = useT();
  const suggestion: ContextSuggestion = entry.suggestion;
  return (
    <li className="border-b border-line py-3">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span className="text-13 font-medium text-ink">{suggestion.title}</span>
        <Badge>{kindLabel(suggestion.kind)}</Badge>
        <Badge tone={FATE_TONE[entry.fate]}>{t(`liveContext.fate.${entry.fate}` as const)}</Badge>
        <Mono className="text-11 text-ink-3" title={new Date(entry.retiredAt).toISOString()}>
          {fmtTime(new Date(entry.retiredAt).toISOString())}
        </Mono>
      </div>
      <p className="prose mt-1 text-13 text-ink-2">{suggestion.body}</p>
      {detail && (
        <p className="mt-1 border-l-2 border-line pl-2 text-12 text-ink-2">{detail.detail}</p>
      )}
    </li>
  );
}

export function SuggestionPanel({
  queue,
  now,
  kindLabel,
  titles,
  onJump,
  onWantMore,
  onDismiss,
  canExpand,
  pending,
  detail,
  failure,
  details,
  statsLog,
  wireLog,
  counts,
  ready,
  tab,
  onTabChange,
}: SuggestionPanelProps) {
  const t = useT();
  const tOr = useTOr();

  const history = (
    <ScrollRegion className="min-h-0 flex-1 px-3">
      {queue.history.length === 0 ? (
        <p className="py-6 text-center text-13 text-ink-3">{t("liveContext.history.empty")}</p>
      ) : (
        <ol>
          {queue.history.map((entry) => (
            <HistoryRow
              key={entry.id}
              entry={entry}
              kindLabel={kindLabel}
              detail={details[entry.id]}
            />
          ))}
        </ol>
      )}
    </ScrollRegion>
  );

  const debug = (
    <ScrollRegion className="min-h-0 flex-1 px-3 py-3">
      <div className="flex flex-col gap-5">
        <section>
          <h4 className="mb-2 text-12 font-medium text-ink-2">{t("liveContext.debug.counts")}</h4>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-12 text-ink-3">
            <span>{t("liveContext.debug.turnsSent", { count: counts.turnsSent })}</span>
            <span>{t("liveContext.debug.evaluations", { count: counts.evaluations })}</span>
            <span>{t("liveContext.debug.suggestions", { count: counts.suggestions })}</span>
            {/* The client is the deduplication authority: the server sends what it found and
                this page decides a {kind,title} already shown is not shown again. */}
            <span>{t("liveContext.debug.deduped", { count: counts.deduped })}</span>
            <span>{t("liveContext.debug.queued", { count: pendingCount(queue) })}</span>
          </div>
        </section>

        {ready && (
          <section>
            <h4 className="mb-2 text-12 font-medium text-ink-2">
              {t("liveContext.debug.readyEcho")}
            </h4>
            <DefinitionList
              items={[
                { term: "focus", definition: <Mono>{ready.focus}</Mono> },
                { term: "min_confidence", definition: <Mono>{ready.min_confidence}</Mono> },
                { term: "max_pending_turns", definition: <Mono>{ready.max_pending_turns}</Mono> },
                { term: "quiet_period", definition: <Mono>{ready.quiet_period}s</Mono> },
                {
                  term: "web_search",
                  definition: <Mono>{ready.web_search ? "on" : "off"}</Mono>,
                },
                { term: "briefing_id", definition: <Mono>{ready.briefing_id ?? "—"}</Mono> },
                { term: "stats", definition: <Mono>{ready.stats ? "on" : "off"}</Mono> },
              ]}
            />
          </section>
        )}

        <section>
          <h4 className="mb-2 text-12 font-medium text-ink-2">{t("liveContext.debug.gate")}</h4>
          {statsLog.length === 0 ? (
            <p className="text-12 text-ink-3">{t("liveContext.debug.gateEmpty")}</p>
          ) : (
            <div className="flex flex-col gap-4">
              {statsLog.map((s, i) => (
                <TickRow key={`${s.seq}-${i}`} stats={s} tOr={tOr} />
              ))}
            </div>
          )}
        </section>

        <section>
          <h4 className="mb-2 text-12 font-medium text-ink-2">{t("liveContext.debug.frames")}</h4>
          {wireLog.length === 0 ? (
            <p className="text-12 text-ink-3">{t("liveContext.debug.framesEmpty")}</p>
          ) : (
            <ol className="flex flex-col gap-0.5">
              {wireLog.map((event) => (
                <li key={event.id} className="flex items-baseline gap-2 text-11">
                  <Mono className="shrink-0 text-ink-3">
                    {fmtTime(new Date(event.at).toISOString())}
                  </Mono>
                  <span
                    className={cn(
                      "shrink-0",
                      event.direction === "out" ? "text-accent" : "text-ink-3",
                    )}
                  >
                    {event.direction === "out" ? "→" : "←"}
                  </span>
                  <Mono className="shrink-0 text-ink-2">{event.label}</Mono>
                  {event.detail && (
                    <span className="min-w-0 truncate text-ink-3">{event.detail}</span>
                  )}
                </li>
              ))}
            </ol>
          )}
        </section>
      </div>
    </ScrollRegion>
  );

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-2 border border-line bg-surface">
      <div className="shrink-0 border-b border-line p-3">
        {queue.current ? (
          <SuggestionBubble
            card={queue.current}
            fraction={remainingFraction(queue, now)}
            seconds={remainingSeconds(queue, now)}
            queued={pendingCount(queue)}
            kindLabel={kindLabel(queue.current.suggestion.kind)}
            titles={titles}
            onJump={onJump}
            onWantMore={onWantMore}
            onDismiss={onDismiss}
            canExpand={canExpand}
            pending={pending}
            detail={detail}
            failure={failure}
          />
        ) : (
          <div className="rounded-2 border border-dashed border-line px-4 py-8">
            <EmptyState
              icon={RadioTower}
              title={t("liveContext.bubble.emptyTitle")}
              description={t("liveContext.bubble.emptyDescription")}
            />
          </div>
        )}
      </div>

      <Tabs
        className="flex min-h-0 flex-1 flex-col"
        contentClassName="flex min-h-0 flex-1 flex-col pt-3"
        aria-label={t("liveContext.tabs.aria")}
        value={tab}
        onChange={onTabChange}
        tabs={[
          {
            value: "history",
            label: t("liveContext.tabs.history", { count: queue.history.length }),
            panel: history,
          },
          { value: "debug", label: t("liveContext.tabs.debug"), panel: debug },
        ]}
      />
    </section>
  );
}
