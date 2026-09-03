import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Search } from "lucide-react";
import { deriveVisitorClass } from "@/lib/lenses";
import { useApp, type RecallMode, type SessionAsk } from "@/lib/store";
import {
  ragStream,
  recallStream,
  type ComponentEvidence,
  type EpisodeSummary,
  type RagResult,
  type RecallAnswer,
  type RecallHit,
  type TrailStep,
  type UsedClaim,
} from "@/lib/api";
import { claimOneLine } from "@/lib/claim";
import { fmtDay, fmtTime } from "@/lib/format";
import { recallSourceIds } from "@/lib/sourceTitles";
import { FAST_LANE_ORDER, RAG_LANE_ORDER, formatStageMs } from "@/lib/stages";
import { useT, useTOr } from "@/lib/useT";
import { PageHeader } from "@/components/PageHeader";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Footnote } from "@/ui/Footnote";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SearchField } from "@/ui/SearchField";
import { SectionRule } from "@/ui/SectionRule";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";
import { CitedAnswer } from "../_shared/CitedAnswer";
import { UsageLine } from "../_shared/UsageLine";
import { StageStrip } from "../_shared/StageStrip";
import { useLiveLane } from "../_shared/useLiveLane";
import { useSourceTitles } from "../_shared/useSourceTitles";
import { openSitting } from "./sitting";

/**
 * All three lanes keep their input and their results in `store.recallCache`, so jumping to
 * Sources to read an original and coming Back loses nothing.
 */
export default function RecallView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const focusSource = useApp((s) => s.focusSource);
  const recallCache = useApp((s) => s.recallCache);
  const setRecallCache = useApp((s) => s.setRecallCache);
  const currentKbSnapshot = useApp((s) => s.currentKbSnapshot);
  // The stance travels with every answering call, derived from who is at the console rather
  // than chosen beside the question; `rag` reaches no model, so it records nothing and sends
  // none. The lens also decides whether this page is the whole cockpit's retrieval panel or
  // the reading room a visitor was handed.
  const lens = useApp((s) => s.lens);
  const visitorClass = deriveVisitorClass(lens);
  const sessionAsks = useApp((s) => s.sessionAsks);
  const pushSessionAsk = useApp((s) => s.pushSessionAsk);
  // Which sitting this is. A lens or library change clears the cache and bumps this, and a
  // request that opened under an older epoch writes nothing when it lands.
  const identityEpoch = useApp((s) => s.identityEpoch);
  const { query, mode, rag, answer, error } = recallCache;

  // liveTrail / live / searching are transients of the in-flight query; Back need not
  // preserve them — the finished answer carries its own breakdown.
  const [searching, setSearching] = useState(false);
  const [liveTrail, setLiveTrail] = useState<TrailStep[]>([]);
  // Both answering lanes are watched the same way: the stages as they open and settle, and
  // the answer as it is written. deep keeps its trail beside this; fast has none to keep.
  const live = useLiveLane(searching);
  const abortRef = useRef<AbortController | null>(null);

  // source id → title, for the hit ledger and the citation list; on failure the id shows.
  // ONLY the ids this answer prints are asked for — the page used to download the whole
  // catalogue (six round trips of 500 rows) to read a dozen titles.
  const cited = useMemo(() => recallSourceIds(rag, answer), [rag, answer]);
  const { titles } = useSourceTitles(currentUser, cited);

  // Abort the deep SSE stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

  // deep's trail, appended one row per tool call. Named rather than inlined because it is a
  // write into the sitting like any other and travels through the same handle.
  const appendTrail = useCallback((s: TrailStep) => setLiveTrail((t) => [...t, s]), []);

  // A change of person or of library ends this sitting, so the question it was answering is
  // no longer anybody's: stop the stream rather than let it finish into an empty room, and
  // clear the half-drawn picture it left — stages, streamed text, trail — the way the store
  // clears the settled one. The abort and the clear are the courtesy; `openSitting` below is
  // what makes the drop mechanical, because a response can be in flight past any abort we
  // manage to call, and its next frame would redraw exactly what we just cleared.
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setSearching(false);
    setLiveTrail([]);
    live.reset();
  }, [identityEpoch, live.reset]);

  const jumpToCitation = useCallback(
    (c: CitationEntry) =>
      focusSource(
        c.sourceId,
        c.blockStart != null ? { start: c.blockStart, end: c.blockEnd ?? c.blockStart } : null,
      ),
    [focusSource],
  );

  async function onSearch() {
    if (!currentUser || !query.trim()) return;
    // The header's read-plane pin travels with every question: a frozen snapshot answers from
    // its own copies of the retrieval layers, so this is the only thing the view has to say.
    const snapshot = currentKbSnapshot?.snapshot_id ?? null;
    abortRef.current?.abort();
    // Everything this run writes goes through the sitting it opened in — the live picture as
    // much as the settled answer. If the lens changes mid-answer the store is reset and this
    // handle stops writing, so neither the completion nor the next streamed frame can
    // repopulate a cleared sitting with the previous person's question, stages or answer.
    const sitting = openSitting(() => useApp.getState().identityEpoch, {
      setRecallCache,
      pushSessionAsk,
      onStage: live.onStage,
      onToken: live.onToken,
      onStep: appendTrail,
    });
    setSearching(true);
    setRecallCache({ error: null });
    setLiveTrail([]);
    live.reset();
    try {
      if (mode === "rag") {
        // The retrieval lane streams too: it reaches no model, so there is no answer being
        // written, but a slow Meili or Qdrant round trip is exactly the wait the diagram
        // exists to explain. The `done` frame carries the hit list AND its breakdown.
        setRecallCache({ answer: null, rag: null });
        const ac = new AbortController();
        abortRef.current = ac;
        await ragStream(
          currentUser,
          query.trim(),
          {
            onStage: sitting.onStage,
            onDone: (r) => sitting.setRecallCache({ rag: r }),
            onError: (m) => {
              if (!ac.signal.aborted) sitting.setRecallCache({ error: m });
            },
          },
          ac.signal,
          snapshot,
          20,
        );
      } else {
        // Both answering lanes run over SSE now: the stage diagram grows in place while the
        // lane works, the answer text arrives as it is written, and deep additionally appends
        // each tool call to the trail. The finished answer lands with the `done` frame.
        setRecallCache({ rag: null, answer: null });
        const ac = new AbortController();
        abortRef.current = ac;
        await recallStream(
          currentUser,
          query.trim(),
          mode,
          {
            onStage: sitting.onStage,
            onToken: sitting.onToken,
            onStep: sitting.onStep,
            onDone: (a) => {
              sitting.setRecallCache({ answer: a });
              // The reading room's own memory of this sitting. Client-side and nowhere
              // else: the ledger of what a library answered is the owner's, and a silent
              // visitor asked for exactly none of it to be written down.
              sitting.pushSessionAsk({ question: query.trim(), mode, answer: a });
            },
            onError: (m) => {
              if (!ac.signal.aborted) sitting.setRecallCache({ error: m });
            },
          },
          ac.signal,
          snapshot,
          [],
          visitorClass,
        );
      }
    } catch (e) {
      sitting.setRecallCache({ error: (e as Error).message, rag: null, answer: null });
    } finally {
      if (sitting.current()) setSearching(false);
    }
  }

  if (!currentUser) {
    return (
      <>
        <PageHeader title={t("recall.title")} description={t("recall.descriptionShort")} />
        <EmptyState
          icon={Search}
          title={t("recall.noUser.title")}
          description={t("recall.noUser.description")}
        />
      </>
    );
  }

  return (
    // Query row and lane switch pinned, results scrolling on their own (scroll charter).
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        className="shrink-0"
        title={lens === "owner" ? t("recall.title") : t("recall.readingTitle")}
        description={
          lens === "owner" ? t("recall.description") : t("recall.readingDescription")
        }
      />

      {/* Query row */}
      <div className="flex shrink-0 flex-wrap items-center gap-2">
        <SearchField
          id="recall-query"
          name="query"
          wrapperClassName="min-w-56 flex-1"
          value={query}
          onChange={(v) => setRecallCache({ query: v })}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSearch();
          }}
          placeholder={
            mode === "rag"
              ? t("recall.query.placeholderRag")
              : t("recall.query.placeholderAsk")
          }
          aria-label={t("recall.query.aria")}
        />
        <SegmentedControl
          aria-label={t("recall.mode.aria")}
          value={mode}
          onChange={(m) => setRecallCache({ mode: m as RecallMode })}
          options={[
            { value: "rag", label: t("recall.mode.rag") },
            { value: "fast", label: t("recall.mode.fast") },
            { value: "deep", label: t("recall.mode.deep") },
          ]}
        />
        <Button
          variant="primary"
          loading={searching}
          disabled={!query.trim()}
          onClick={() => void onSearch()}
        >
          {mode === "rag" ? t("recall.action.search") : t("recall.action.ask")}
        </Button>
      </div>

      {/* Results */}
      <ScrollRegion className="min-h-0 lg:flex-1">
      {error ? (
        <ErrorState
          title={t("recall.error.title")}
          error={error}
          onRetry={() => void onSearch()}
        />
      ) : searching ? (
        <LiveLanePanel
          live={live}
          mode={mode}
          trail={liveTrail}
        />
      ) : answer ? (
        <AnswerPanel answer={answer} titles={titles} onJump={jumpToCitation} />
      ) : rag == null ? (
        <EmptyState
          icon={Search}
          title={mode === "rag" ? t("recall.empty.ragTitle") : t("recall.empty.askTitle")}
          description={
            mode === "rag"
              ? t("recall.empty.ragDescription")
              : t("recall.empty.askDescription")
          }
        />
      ) : (
        <RagPanel rag={rag} titles={titles} onJump={jumpToCitation} />
      )}
      {/* Only in the reading room: the owner reads the same history in Consultations, as a
          server-side ledger with its evidence chains, and two lists of one thing would be
          two answers to "what did I ask". */}
      {lens !== "owner" && sessionAsks.length > 0 && (
        <SessionAsks
          asks={sessionAsks}
          onReopen={(ask) =>
            setRecallCache({
              query: ask.question,
              mode: ask.mode,
              rag: null,
              answer: ask.answer,
              error: null,
            })
          }
        />
      )}
      </ScrollRegion>
    </div>
  );
}

/* --------------------------------------------------------- the reading room's session */

/**
 * What this visitor has asked since the page opened, newest last, held in client memory and
 * written nowhere. Picking a row puts its answer back in the panel above — the same panel,
 * with the same citations still opening the same sources.
 */
function SessionAsks({
  asks,
  onReopen,
}: {
  asks: SessionAsk[];
  onReopen: (ask: SessionAsk) => void;
}) {
  const t = useT();
  return (
    <section className="mt-8 border-t border-line pt-4">
      {/* The rail's chapter apparatus is gone in the reading room, so this heading is the
          quiet label the hit ledger already uses rather than a numbered § of a book with
          twelve missing chapters. */}
      <p className="mb-2 text-13 text-ink-2">{t("recall.session.title")}</p>
      <ol className="border-t border-line">
        {asks.map((ask, i) => (
          <li key={i} className="border-b border-line">
            <button
              type="button"
              title={t("recall.session.reopen")}
              onClick={() => onReopen(ask)}
              className="flex w-full items-baseline gap-3 rounded-1 px-1 py-2 text-left transition-colors duration-120 hover:bg-hover"
            >
              <Mono className="w-10 shrink-0 text-12 text-ink-3">{ask.mode}</Mono>
              <span className="min-w-0 flex-1 truncate text-13 text-ink">{ask.question}</span>
            </button>
          </li>
        ))}
      </ol>
      <p className="mt-2 text-12 text-ink-3">{t("recall.session.note")}</p>
    </section>
  );
}

/* ---------------------------------------------------------------- rag hit ledger */

/**
 * The finished rag lane: the same diagram the live run drew, above the ledger it produced.
 *
 * Nothing is re-rendered here — `rag.stages` is the measurement `StageStrip` was already
 * showing, so the picture does not change shape the moment the lane lands. A search that
 * found nothing keeps its diagram: "where did those seconds go" is a better question when
 * the answer is empty, not a worse one.
 */
function RagPanel({
  rag,
  titles,
  onJump,
}: {
  rag: RagResult;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const t = useT();
  return (
    <div className="flex flex-col gap-4">
      <StageStrip stages={rag.stages} description={t("recall.stages.descriptionRag")} />
      {rag.hits.length === 0 ? (
        <EmptyState
          icon={Search}
          title={t("recall.empty.noHitsTitle")}
          description={t("recall.empty.noHitsDescription")}
        />
      ) : (
        <HitList hits={rag.hits} titles={titles} onJump={onJump} />
      )}
    </div>
  );
}

function HitList({
  hits,
  titles,
  onJump,
}: {
  hits: RecallHit[];
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const t = useT();
  return (
    <section>
      <p className="mb-2 text-13 text-ink-2">
        {t("recall.hits.count", { count: hits.length })}
      </p>
      <ol className="border-t border-line">
        {hits.map((h, i) => {
          const citation: CitationEntry = {
            sourceId: h.source_id,
            blockStart: h.block_start,
            blockEnd: h.block_end,
            title: titles[h.source_id],
          };
          return (
            <li key={i} className="flex gap-3 border-b border-line py-3">
              <Footnote
                index={i + 1}
                citation={{
                  sourceId: h.source_id,
                  blockStart: h.block_start,
                  blockEnd: h.block_end,
                  title: titles[h.source_id],
                  snippet: h.text.slice(0, 160),
                }}
                onJump={onJump}
                className="mt-1"
              />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <span className="text-13 font-medium text-ink">
                    {titles[h.source_id] ?? h.source_id}
                  </span>
                  <Mono className="text-12 text-ink-3">{h.source_id}</Mono>
                  <Mono className="text-12 text-ink-3">
                    b{h.block_start}–b{h.block_end}
                  </Mono>
                  {h.paths.map((p) => (
                    <Badge key={p}>{p}</Badge>
                  ))}
                  <Mono className="ml-auto text-12 text-ink-3">
                    score {h.score.toFixed(4)}
                  </Mono>
                </div>
                <button
                  type="button"
                  onClick={() => onJump(citation)}
                  className="prose mt-1 block w-full text-left text-14 text-ink-2 transition-colors duration-120 hover:text-ink"
                >
                  {h.text}
                </button>
              </div>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

/* ---------------------------------------------------------------- the lane, live */

/**
 * What the reader looks at WHILE the answer is being made.
 *
 * It replaces the skeleton that used to sit here, and the difference is the point: a skeleton
 * says "something is happening", while this says which stage is happening, how long it has
 * been happening, and — as soon as the model starts writing — what the answer is going to be.
 * Nothing here is re-rendered when the answer lands; the finished panel draws the same
 * diagram from the same measurements, which is what makes the live picture trustworthy.
 */
function LiveLanePanel({
  live,
  mode,
  trail,
}: {
  live: ReturnType<typeof useLiveLane>;
  mode: RecallMode;
  trail: TrailStep[];
}) {
  const t = useT();
  return (
    <div className="flex flex-col gap-4">
      <StageStrip
        live={live.stages}
        // Both deterministic lanes have a fixed vocabulary, so the diagram is drawn in the
        // lane's order from the first event. deep has none — its order is the finding.
        order={mode === "fast" ? FAST_LANE_ORDER : mode === "rag" ? RAG_LANE_ORDER : undefined}
        description={t(
          mode === "deep"
            ? "recall.stages.descriptionDeep"
            : mode === "rag"
              ? "recall.stages.descriptionRag"
              : "recall.stages.description",
        )}
      />
      {/* deep only: the tool calls as they land. Each record already carries its own `ms`. */}
      {mode === "deep" && <TrailTimeline steps={trail} live />}
      {live.text ? (
        <section>
          <p className="text-12 text-ink-3">{t("recall.stages.answering")}</p>
          {/* Deliberately unlinked: citations are bound once the answer settles, and a
              half-written `[cite: s0` is not yet a citation to bind. */}
          <p className="prose mt-1 max-w-measure text-14 whitespace-pre-wrap">{live.text}</p>
        </section>
      ) : (
        live.stages.length === 0 && <SkeletonText lines={6} className="max-w-measure" />
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ deep timeline */

/**
 * The deep lane's tool-call timeline: mono tool + query + hits/chars, errors in danger.
 *
 * `heading` is false where a `<summary>` already names it — the finished answer folds the
 * trail away behind exactly this sentence, and printing it again inside the fold said the
 * same thing twice.
 */
function TrailTimeline({
  steps,
  live,
  heading = true,
}: {
  steps: TrailStep[];
  live?: boolean;
  heading?: boolean;
}) {
  const t = useT();
  return (
    <section>
      {heading && (
        <p className="mb-2 flex items-center gap-2 text-13 text-ink-2">
          {t("recall.trail.title", { count: steps.length })}
          {live && <span className="text-12 text-ink-3">{t("recall.trail.live")}</span>}
        </p>
      )}
      {steps.length === 0 && live ? (
        <SkeletonText lines={3} className="max-w-measure" />
      ) : (
        <ol className="border-t border-line">
          {steps.map((s, i) => {
            const arg =
              s.query ?? (s.source_id ? `${s.source_id} ${JSON.stringify(s.locator ?? {})}` : "");
            const meta = s.error
              ? t("recall.trail.failed", { detail: s.error })
              : s.hits != null
                ? t("recall.trail.hits", { count: s.hits })
                : s.chars != null
                  ? t("recall.trail.chars", { count: s.chars })
                  : "";
            const head = (
              <>
                <Mono className="w-6 shrink-0 text-12 text-ink-3">{i + 1}</Mono>
                <Mono className="shrink-0 text-13 text-accent">{s.tool}</Mono>
                {arg && (
                  <span className="min-w-0 flex-1 truncate text-13 text-ink-2">{arg}</span>
                )}
                {meta && (
                  <span className={cn("ml-auto text-12", s.error ? "text-danger" : "text-ink-3")}>
                    {meta}
                  </span>
                )}
                {/* What this step cost, measured around the tool itself and already on the
                    record when it arrived — so a trail growing live reads as a real clock,
                    not as the gap between two renders. `ml-auto` only when nothing else
                    claimed the right edge. */}
                {s.ms != null && (
                  <Mono className={cn("shrink-0 text-12 text-ink-3", !meta && "ml-auto")}>
                    · {formatStageMs(s.ms)}
                  </Mono>
                )}
              </>
            );
            // Component tools (person_profile, enumerate_identities, timeline …) answer with
            // several lines of structured text, not a number. The row stays one line; the
            // result opens under it, verbatim — line breaks are the reading order.
            return (
              <li key={i} className="border-b border-line">
                {s.result ? (
                  <details className="group">
                    <summary className="flex cursor-pointer flex-wrap items-baseline gap-x-3 gap-y-1 py-2">
                      {head}
                      <span className="shrink-0 text-12 text-ink-3">
                        {t("recall.trail.result")}
                      </span>
                    </summary>
                    <pre className="mb-2 max-h-96 overflow-auto rounded-1 bg-surface p-3 font-mono text-12 leading-relaxed whitespace-pre-wrap break-words text-ink-2">
                      {s.result}
                    </pre>
                  </details>
                ) : (
                  <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 py-2">{head}</div>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/* --------------------------------------------------------- the fast/deep answer */

function UsedClaimRow({
  claim,
  titles,
  onJump,
  showScore = true,
}: {
  claim: UsedClaim;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
  showScore?: boolean;
}) {
  const tOr = useTOr();
  // Labels are a component's mechanical marks on a claim (`current`, `superseded`), an open
  // vocabulary: a label this build does not know renders as the word the server sent.
  const labels = claim.labels ?? [];
  const superseded = labels.includes("superseded");
  return (
    <div className="border-b border-line py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Mono className="text-12 text-ink-3">{claim.anchor}</Mono>
        <Mono className="text-12 text-ink-3">{claim.document_path}</Mono>
        {claim.paths.map((p) => (
          <Badge key={p}>{p}</Badge>
        ))}
        {labels.map((label) =>
          // `via:person,timespan` — a component lookup returned this same claim. The paths
          // are dynamic, so the badge is built from the label itself rather than translated.
          label.startsWith("via:") ? (
            <Badge key={label} tone="neutral">
              {tOr("recall.components.via", "via {paths}").replace(
                "{paths}",
                label.slice(4).split(",").join(", "),
              )}
            </Badge>
          ) : (
            <Badge key={label} tone={label === "superseded" ? "warn" : "neutral"}>
              {tOr(`enum.claimLabel.${label}`, label)}
            </Badge>
          ),
        )}
        {showScore && (
          <Mono className="ml-auto text-12 text-ink-3">score {claim.score.toFixed(4)}</Mono>
        )}
      </div>
      <p className={cn("prose mt-1 max-w-measure text-14", superseded && "text-ink-3")}>
        {/* The service ships the ledger line as written — anchor comments and cross-link
            markup included; the reader gets the sentence, never the machinery. */}
        {claimOneLine(claim.text)}
      </p>
      <CitationList
        className="mt-2 max-w-measure"
        citations={claim.citations.map((c) => ({
          sourceId: c.source_id,
          blockStart: c.block_start,
          blockEnd: c.block_end,
          title: titles[c.source_id],
        }))}
        onJump={onJump}
      />
    </div>
  );
}

/**
 * One routed component lookup: the path it ran, the arguments routing chose, and what it
 * returned — its own evidence face, so it is shown as one card rather than merged into the
 * ranked ledger. A path that contributed nothing still gets a card: what the model asked for
 * and why the answer has nothing from it is exactly the part worth reading.
 */
function ComponentEvidenceCard({
  evidence,
  titles,
  onJump,
}: {
  evidence: ComponentEvidence;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const t = useT();
  const claims = evidence.claims ?? [];
  const windows = evidence.windows ?? [];
  const args = JSON.stringify(evidence.args ?? {});
  const dropped = evidence.dropped ?? 0;
  const droppedSummary = evidence.dropped_summary ?? [];
  const alreadyShown = evidence.already_shown ?? 0;
  return (
    <section className="border-b border-line py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Mono className="text-13 text-accent">{evidence.path}</Mono>
        <Mono className="min-w-0 flex-1 truncate text-12 text-ink-3" title={args}>
          {args}
        </Mono>
        {claims.length > 0 && (
          <Badge>{t("recall.components.claims", { count: claims.length })}</Badge>
        )}
        {windows.length > 0 && (
          <Badge>{t("recall.components.windows", { count: windows.length })}</Badge>
        )}
        {evidence.degraded && (
          <Badge tone="warn">
            {t("recall.components.degraded", { reason: evidence.degraded })}
          </Badge>
        )}
      </div>

      {claims.length > 0 && (
        <div className="mt-1 border-t border-line">
          {claims.map((claim, index) => (
            <UsedClaimRow
              key={`${claim.anchor}:${index}`}
              claim={claim}
              titles={titles}
              onJump={onJump}
              showScore={false}
            />
          ))}
        </div>
      )}

      {windows.length > 0 && (
        <div className="mt-1">
          <HitList hits={windows} titles={titles} onJump={onJump} />
        </div>
      )}

      {claims.length === 0 && windows.length === 0 && !evidence.degraded && alreadyShown === 0 && (
        <p className="mt-1 text-13 text-ink-3">{t("recall.components.empty")}</p>
      )}

      {/* The lookup found these too — they are in the ranked ledger above, so this face
          hides them rather than showing the same evidence twice. */}
      {alreadyShown > 0 && (
        <p className="mt-1 text-12 text-ink-3">
          {t("recall.components.alreadyShown", { count: alreadyShown })}
        </p>
      )}

      {/* What was NOT shown, described rather than counted: a truncation the reader can act on. */}
      {droppedSummary.length > 0 ? (
        <p className="mt-1 text-12 text-ink-3">
          {t("recall.components.notShown", {
            detail: droppedSummary.map(([group, count]) => `${group} ×${count}`).join(" · "),
          })}
        </p>
      ) : (
        dropped > 0 && (
          <p className="mt-1 text-12 text-ink-3">
            {t("recall.components.dropped", { count: dropped })}
          </p>
        )
      )}
    </section>
  );
}

/** The routing turn, as one technical line: what was on offer, what was chosen, what broke. */
function RoutingLine({ answer }: { answer: RecallAnswer }) {
  const t = useT();
  const offered = answer.route_offered ?? [];
  const chosen = answer.route_chosen ?? [];
  const degraded = answer.route_degraded ?? null;
  if (offered.length === 0 && chosen.length === 0 && !degraded) return null;
  return (
    <p className="mt-2 flex flex-wrap items-baseline gap-x-2 text-12 text-ink-3">
      <span>{t("recall.route.title")}</span>
      {offered.length > 0 && (
        <Mono className="text-12">
          {t("recall.route.offered", { paths: offered.join(", ") })}
        </Mono>
      )}
      <span aria-hidden>→</span>
      <Mono className="text-12">
        {chosen.length > 0
          ? t("recall.route.chosen", { paths: chosen.join(", ") })
          : t("recall.route.none")}
      </Mono>
      {degraded && (
        <span className="text-danger">
          {t("recall.route.degraded", { reason: degraded })}
        </span>
      )}
    </p>
  );
}

function EpisodeSummaryRow({
  summary,
  onJump,
}: {
  summary: EpisodeSummary;
  onJump: (c: CitationEntry) => void;
}) {
  const t = useT();
  const citation = {
    sourceId: summary.source_id,
    blockStart: summary.block_start,
    blockEnd: summary.block_end,
    title: summary.source_title,
    snippet: summary.text.slice(0, 160),
  };
  return (
    <div className="border-b border-line py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Badge>{t("recall.episodeSummaries.derived")}</Badge>
        <span className="text-13 font-medium text-ink">
          {summary.source_title || summary.source_id}
        </span>
        <Mono className="text-12 text-ink-3">{summary.source_id}</Mono>
        <Mono className="text-12 text-ink-3">
          b{summary.block_start}–b{summary.block_end}
        </Mono>
        {summary.source_occurred_on && (
          <Mono className="text-12 text-ink-3">{fmtDay(summary.source_occurred_on)}</Mono>
        )}
        {summary.section_path.length > 0 && (
          <span className="text-12 text-ink-3">{summary.section_path.join(" / ")}</span>
        )}
        <Mono className="ml-auto text-12 text-ink-3">score {summary.score.toFixed(4)}</Mono>
      </div>
      <button
        type="button"
        onClick={() => onJump(citation)}
        className="prose mt-1 block max-w-measure text-left text-14 text-ink-2 transition-colors duration-120 hover:text-ink"
      >
        {summary.text}
      </button>
    </div>
  );
}

function AnswerPanel({
  answer,
  titles,
  onJump,
}: {
  answer: RecallAnswer;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const t = useT();
  const trail = answer.trail ?? [];
  const episodeSummaries = answer.used_episode_summaries ?? [];
  const windows = answer.used_windows ?? [];
  const componentEvidence = answer.used_component_evidence ?? [];
  // Sections are numbered as they are rendered: an answer with no component lookups reads
  // exactly as it did before the seam existed.
  let section = 1;
  return (
    <div className="flex flex-col gap-6">
      {/* deep: the answer leads; the process folds away for checking */}
      {answer.mode === "deep" && trail.length > 0 && (
        <details className="max-w-measure">
          <summary className="cursor-pointer text-13 text-ink-2">
            {t("recall.trail.title", { count: trail.length })}
          </summary>
          <div className="mt-3">
            <TrailTimeline steps={trail} heading={false} />
          </div>
        </details>
      )}

      <section>
        <SectionRule no={section++} title={t("recall.answer.title")} />
        <p className="mt-3 text-12 text-ink-3">
          as_of <Mono title={answer.as_of}>{fmtTime(answer.as_of)}</Mono>
        </p>
        {answer.mode === "fast" && (
          <div className="mt-2 flex flex-wrap gap-2">
            <Badge>
              {t("recall.answer.evidenceStrategy")}: {answer.evidence_strategy ?? "ranked"}
            </Badge>
            <Badge>
              {t("recall.answer.answerFormat")}: {answer.answer_format ?? "text"}
            </Badge>
            {answer.evidence_strategy === "select" && (
              <Badge>
                {t("recall.answer.selectorContribution", {
                  claims: answer.model_selected_claims ?? 0,
                  claimCandidates: answer.claim_candidates ?? 0,
                  episodes: answer.model_selected_episode_summaries ?? 0,
                  episodeCandidates: answer.episode_summary_candidates ?? 0,
                  windows: answer.model_selected_windows ?? 0,
                  windowCandidates: answer.window_candidates ?? 0,
                })}
              </Badge>
            )}
            {answer.answer_kind && <Badge>{answer.answer_kind}</Badge>}
            {(answer.evidence_selection_degraded || answer.answer_format_degraded) && (
              <Badge>
                {t("recall.answer.degraded")}: {answer.evidence_selection_degraded ?? answer.answer_format_degraded}
              </Badge>
            )}
          </div>
        )}
        {answer.mode === "fast" && <RoutingLine answer={answer} />}
        {/* Both lanes: the strip renders nothing when the answer carries no stages (an
            answer restored from the session cache), so the lane check would be noise. */}
        <StageStrip
          stages={answer.stages}
          description={t(
            answer.mode === "deep" ? "recall.stages.descriptionDeep" : "recall.stages.description",
          )}
        />
        {/* The answering call's own evidence review, when its schema carried one. Collapsed
            by default and above the answer: it explains the answer, it is not the answer, and
            it is model output rather than evidence — so it never renders as a citation. */}
        {answer.deliberation && (
          <details className="mt-3 max-w-measure">
            <summary className="cursor-pointer text-13 text-ink-2">
              {t("recall.answer.deliberation")}
            </summary>
            <p className="mt-2 text-13 leading-relaxed whitespace-pre-wrap text-ink-2">
              {answer.deliberation}
            </p>
          </details>
        )}
        <div className="prose mt-2 max-w-measure">
          {answer.answer ? (
            <CitedAnswer text={answer.answer} handles={answer.citation_handles} />
          ) : (
            t("recall.answer.blank")
          )}
        </div>
        {/* One token ledger for the whole app: Ask prints the same line for its turns. */}
        <UsageLine usage={answer.token_usage} cost={answer.cost} className="mt-4" />
      </section>

      {componentEvidence.length > 0 && (
        <section>
          <SectionRule
            no={section++}
            title={t("recall.components.title", { count: componentEvidence.length })}
          />
          <p className="mt-2 text-12 text-ink-3">{t("recall.components.description")}</p>
          <div className="mt-2 border-t border-line">
            {componentEvidence.map((evidence, index) => (
              <ComponentEvidenceCard
                key={`${evidence.path}:${index}`}
                evidence={evidence}
                titles={titles}
                onJump={onJump}
              />
            ))}
          </div>
        </section>
      )}

      {answer.used_claims.length > 0 && (
        <section>
          <SectionRule
            no={section++}
            title={t("recall.usedClaims.title", { count: answer.used_claims.length })}
          />
          <div className="mt-2 border-t border-line">
            {answer.used_claims.map((c) => (
              <UsedClaimRow key={c.anchor} claim={c} titles={titles} onJump={onJump} />
            ))}
          </div>
        </section>
      )}

      {episodeSummaries.length > 0 && (
        <section>
          <SectionRule
            no={section++}
            title={t("recall.episodeSummaries.title", { count: episodeSummaries.length })}
          />
          <p className="mt-2 text-12 text-ink-3">
            {t("recall.episodeSummaries.description")}
          </p>
          <div className="mt-2 border-t border-line">
            {episodeSummaries.map((summary, index) => (
              <EpisodeSummaryRow
                key={`${summary.source_id}:${summary.block_start}:${summary.block_end}:${index}`}
                summary={summary}
                onJump={onJump}
              />
            ))}
          </div>
        </section>
      )}

      {windows.length > 0 && (
        <section>
          <SectionRule
            no={section++}
            title={t("recall.windows.title", { count: windows.length })}
          />
          <p className="mt-2 text-12 text-ink-3">{t("recall.windows.description")}</p>
          <div className="mt-2">
            <HitList hits={windows} titles={titles} onJump={onJump} />
          </div>
        </section>
      )}
    </div>
  );
}
