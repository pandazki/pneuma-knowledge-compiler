import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MessagesSquare } from "lucide-react";
import { useApp, type AskTurn } from "@/lib/store";
import {
  askBriefingStream,
  buildBriefingStream,
  getBriefing,
  listBriefings,
  listSources,
  type BriefingBuilt,
  type BriefingDetail,
  type BriefingSummary,
  type SourceSummary,
} from "@/lib/api";
import { briefingTextLines } from "@/lib/ask";
import { fmtCount, fmtTime } from "@/lib/format";
import {
  firstPage,
  nextPage,
  previousPage,
  type CursorPageState,
  type Page,
} from "@/lib/pagination";
import { useT, useTOr } from "@/lib/useT";
import { PageHeader } from "@/components/PageHeader";
import { PaginationBar } from "@/components/PaginationBar";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Checkbox } from "@/ui/Checkbox";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { NumberField } from "@/ui/NumberField";
import { SearchField } from "@/ui/SearchField";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";
import { TextField } from "@/ui/TextField";
import { CitedAnswer } from "../_shared/CitedAnswer";
import { StageStrip } from "../_shared/StageStrip";
import { UsageLine } from "../_shared/UsageLine";
import { useLiveLane } from "../_shared/useLiveLane";
import { useSourceTitles } from "../_shared/useSourceTitles";

const SOURCE_PAGE_SIZE = 12;

/**
 * Ask: first build a briefing — a frozen knowledge pack, anchored to sources or gathered by a
 * query — then keep questioning it. Both the build inputs and the question thread live in
 * `store.askCache`, so jumping to Sources to read a citation and coming Back loses nothing.
 */
export default function AskView() {
  const t = useT();
  const tOr = useTOr();
  const currentUser = useApp((s) => s.currentUser);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const focusSource = useApp((s) => s.focusSource);
  const askCache = useApp((s) => s.askCache);
  const setAskCache = useApp((s) => s.setAskCache);
  const selectBriefing = useApp((s) => s.selectBriefing);
  const { scopeQuery, selected: selectedIds, briefing, question, turns } = askCache;
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);

  const [sourcePage, setSourcePage] = useState<Page<SourceSummary> | null>(null);
  const [sourcePageState, setSourcePageState] =
    useState<CursorPageState>(firstPage);
  const [sourceQuery, setSourceQuery] = useState("");
  const [sourceKind, setSourceKind] = useState("all");
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const sourceRequestVersion = useRef(0);
  const [history, setHistory] = useState<BriefingSummary[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  // budget_chars is a build input the store does not keep; session-only, default 4000.
  const [budget, setBudget] = useState<number | null>(4000);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  // Both halves of this page cost real seconds, and both are now watched the same way as
  // Recall's lanes: the build's retrieval/expansion/assembly, and each question's loop.
  const liveBuild = useLiveLane(building);
  const liveAsk = useLiveLane(asking);

  const sources = sourcePage?.items ?? null;

  // A footnote names its source by title. The picker page only knows the titles of the rows
  // it has shown, and an answer cites whatever the briefing holds — so every cited source the
  // page has not met is looked up once, through the same cache Recall and Process use.
  const cited = useMemo(
    () => [...new Set(turns.flatMap((turn) => turn.citations.map((c) => c.source_id)))],
    [turns],
  );
  const { titles, remember } = useSourceTitles(currentUser, cited);

  const loadSources = useCallback(() => {
    if (!currentUser) return;
    const requestVersion = ++sourceRequestVersion.current;
    setSourcesError(null);
    setSourcesLoading(true);
    listSources(currentUser, {
      limit: SOURCE_PAGE_SIZE,
      cursor: sourcePageState.cursor,
      query: sourceQuery.trim() || null,
      kind: sourceKind === "all" ? null : sourceKind,
    })
      .then((page) => {
        if (requestVersion !== sourceRequestVersion.current) return;
        setSourcePage(page);
        // The rows this page listed are titles the cache now knows for free.
        remember(page.items);
      })
      .catch((e) => {
        if (requestVersion !== sourceRequestVersion.current) return;
        setSourcePage(null);
        setSourcesError((e as Error).message);
      })
      .finally(() => {
        if (requestVersion === sourceRequestVersion.current) {
          setSourcesLoading(false);
        }
      });
  }, [currentUser, remember, sourceKind, sourcePageState.cursor, sourceQuery]);

  const loadHistory = useCallback(() => {
    if (!currentUser) return;
    setHistoryError(null);
    listBriefings(currentUser)
      .then(setHistory)
      .catch((e) => {
        setHistory([]);
        setHistoryError((e as Error).message);
      });
  }, [currentUser]);

  useEffect(loadSources, [loadSources]);
  useEffect(loadHistory, [loadHistory]);

  useEffect(() => {
    setSourcePageState(firstPage());
  }, [currentUser]);

  const jumpToCitation = useCallback(
    (c: CitationEntry) =>
      focusSource(
        c.sourceId,
        c.blockStart != null ? { start: c.blockStart, end: c.blockEnd ?? c.blockStart } : null,
      ),
    [focusSource],
  );

  if (!currentUser) {
    return (
      <>
        <PageHeader title={t("ask.title")} description={t("ask.descriptionShort")} />
        <EmptyState
          icon={MessagesSquare}
          title={t("ask.noUser.title")}
          description={t("ask.noUser.description")}
        />
      </>
    );
  }

  /** Every briefing change goes through here: the store resets the thread and the draft
   * question, and the one piece of thread state that is local — the last ask error — is
   * cleared beside it. Nothing about the previous pack survives the switch. */
  function pickBriefing(next: BriefingBuilt | null) {
    selectBriefing(next);
    setAskError(null);
  }

  function toggleSource(id: string) {
    const next = selected.has(id) ? selectedIds.filter((x) => x !== id) : [...selectedIds, id];
    setAskCache({ selected: next });
  }

  const canBuild = scopeQuery.trim() !== "" || selected.size > 0;

  async function onBuild() {
    if (!currentUser || !canBuild) return;
    setBuilding(true);
    setBuildError(null);
    liveBuild.reset();
    try {
      await buildBriefingStream(
        currentUser,
        {
          query: scopeQuery.trim() || null,
          source_ids: [...selected],
          budget_chars: budget ?? undefined,
          snapshot: currentSnapshot,
        },
        {
          onStage: liveBuild.onStage,
          onDone: (built) => {
            pickBriefing(built);
            void loadHistory();
          },
          onError: setBuildError,
        },
      );
    } catch (e) {
      setBuildError((e as Error).message);
    } finally {
      setBuilding(false);
    }
  }

  async function onAsk() {
    // Enter in the question field arrives here too; while an answer streams, a second
    // question must wait — two in flight would both append to the same stale thread.
    if (asking) return;
    if (!currentUser || !briefing || !question.trim()) return;
    const q = question.trim();
    setAsking(true);
    setAskError(null);
    liveAsk.reset();
    try {
      await askBriefingStream(
        currentUser,
        briefing.briefing_id,
        q,
        {
          onStage: liveAsk.onStage,
          onToken: liveAsk.onToken,
          onDone: (res) => {
            const turn: AskTurn = {
              question: q,
              mode: "briefing",
              answer: res.answer,
              citations: res.citations,
              handles: res.citation_handles ?? {},
              usage: res.token_usage,
              verbatim:
                res.verbatim_fetches.length > 0 ? res.verbatim_fetches : undefined,
              stages: res.stages,
            };
            setAskCache({ turns: [...turns, turn], question: "" });
          },
          onError: setAskError,
        },
      );
    } catch (e) {
      setAskError((e as Error).message);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader title={t("ask.title")} description={t("ask.description")} />

      {briefing == null ? (
        <>
          {/* ------------------------------------------------ build a briefing */}
          <section>
            <SectionRule no={1} title={t("ask.build.title")} />
            <div className="mt-4 flex max-w-measure flex-col gap-4">
              <TextField
                label={t("ask.build.queryLabel")}
                value={scopeQuery}
                onChange={(e) => setAskCache({ scopeQuery: e.target.value })}
                placeholder={t("ask.build.queryPlaceholder")}
                hint={t("ask.build.queryHint")}
              />
              <div>
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <p className="text-13 font-medium text-ink-2">
                    {t("ask.build.sourcesLabel")}
                  </p>
                  <p className="text-12 text-ink-3" aria-live="polite">
                    {t("ask.build.selectedLabel")} <Mono>{selected.size}</Mono>
                    <span> · {t("ask.build.matchLabel")} </span>
                    <Mono>{fmtCount(sourcePage?.page.total ?? 0)}</Mono>
                  </p>
                </div>
                <div className="mt-2 grid gap-2 sm:grid-cols-[minmax(0,1fr)_12rem]">
                  <SearchField
                    id="ask-source-search"
                    name="source-query"
                    aria-label={t("ask.build.searchAria")}
                    placeholder={t("ask.build.searchPlaceholder")}
                    value={sourceQuery}
                    onChange={(value) => {
                      setSourceQuery(value);
                      setSourcePageState(firstPage());
                    }}
                  />
                  <Select
                    aria-label={t("ask.build.kindAria")}
                    value={sourceKind}
                    onChange={(value) => {
                      setSourceKind(value);
                      setSourcePageState(firstPage());
                    }}
                    options={[
                      { value: "all", label: t("ask.build.kind.all") },
                      { value: "meeting", label: t("ask.build.kind.meeting") },
                      {
                        value: "document_library",
                        label: t("ask.build.kind.documentLibrary"),
                      },
                      { value: "im", label: t("ask.build.kind.im") },
                      { value: "email", label: t("ask.build.kind.email") },
                    ]}
                  />
                </div>
                {selectedIds.length > 0 && (
                  <details className="mt-2 rounded-2 border border-line bg-surface px-3 py-2">
                    <summary className="cursor-pointer text-13 text-ink-2">
                      {t("ask.build.selectedSummary")} <Mono>{selectedIds.length}</Mono>
                    </summary>
                    <ol className="mt-2 border-t border-line pt-1">
                      {selectedIds.map((sourceId) => (
                        <li
                          key={sourceId}
                          className="flex items-baseline justify-between gap-3 py-1 text-12"
                        >
                          <span className="min-w-0 truncate text-ink-2">
                            {titles[sourceId] ?? sourceId}
                          </span>
                          <button
                            type="button"
                            className="shrink-0 rounded-1 px-1.5 py-0.5 text-ink-3 hover:bg-hover hover:text-ink"
                            onClick={() => toggleSource(sourceId)}
                          >
                            {t("ask.build.remove")}
                          </button>
                        </li>
                      ))}
                    </ol>
                  </details>
                )}
                {sourcesError ? (
                  <div className="mt-2">
                    <ErrorState
                      title={t("ask.build.sourcesError")}
                      error={sourcesError}
                      onRetry={loadSources}
                    />
                  </div>
                ) : sources == null ? (
                  <SkeletonText lines={3} className="mt-2" />
                ) : sources.length === 0 ? (
                  <p className="mt-2 text-13 text-ink-3">
                    {sourceQuery.trim() || sourceKind !== "all"
                      ? t("ask.build.noMatch")
                      : t("ask.build.noSources")}
                  </p>
                ) : (
                  <>
                    <ol className="mt-2 border-t border-line">
                      {sources.map((s) => (
                        <li key={s.source_id} className="border-b border-line py-2">
                          <Checkbox
                            checked={selected.has(s.source_id)}
                            onCheckedChange={() => toggleSource(s.source_id)}
                            label={s.title}
                            hint={
                              <Mono>
                                {s.source_id} · {tOr(`enum.sourceKind.${s.kind}`, s.kind)} ·{" "}
                                {t("sources.blockCount", { count: s.block_count })}
                              </Mono>
                            }
                          />
                        </li>
                      ))}
                    </ol>
                    <PaginationBar
                      pageIndex={sourcePageState.previous.length}
                      limit={SOURCE_PAGE_SIZE}
                      itemCount={sources.length}
                      total={sourcePage?.page.total ?? sources.length}
                      hasNext={sourcePage?.page.next_cursor != null}
                      loading={sourcesLoading}
                      noun={t("ask.build.sourceNoun")}
                      onPrevious={() => setSourcePageState((state) => previousPage(state))}
                      onNext={() => {
                        const cursor = sourcePage?.page.next_cursor;
                        if (cursor) {
                          setSourcePageState((state) => nextPage(state, cursor));
                        }
                      }}
                    />
                  </>
                )}
              </div>
              <NumberField
                label={t("ask.build.budgetLabel")}
                value={budget}
                onChange={setBudget}
                min={500}
                max={20000}
                step={500}
              />
              <p className="text-12 text-ink-3">
                {t("ask.build.snapshotLabel")}
                {currentSnapshot ? (
                  <>
                    <Mono>{currentSnapshot}</Mono>
                    {t("ask.build.snapshotReadOnly")}
                  </>
                ) : (
                  t("ask.build.snapshotHead")
                )}
              </p>
              {buildError && (
                <ErrorState
                  title={t("ask.build.error")}
                  error={buildError}
                  onRetry={() => void onBuild()}
                />
              )}
              {/* A build runs no model at all — retrieval, expansion, assembly — which is
                  exactly why watching it is worth something: when it takes nine seconds the
                  whole question is which of the three it spent them in. */}
              {building && (
                <StageStrip
                  live={liveBuild.stages}
                  description={t("ask.stages.buildDescription")}
                />
              )}
              <div className="flex flex-col gap-1.5">
                <Button
                  variant="primary"
                  loading={building}
                  disabled={!canBuild}
                  onClick={() => void onBuild()}
                >
                  {t("ask.build.action")}
                </Button>
                {/* A disabled control with no reason beside it reads as a broken one: the
                    hint states the one condition a pack needs, and disappears once it holds. */}
                {!canBuild && (
                  <p className="text-12 text-ink-3">{t("ask.build.disabledHint")}</p>
                )}
              </div>
            </div>
          </section>

          {/* ------------------------------------------------ past briefings */}
          <section>
            <SectionRule no={2} title={t("ask.history.title")} />
            {history == null ? (
              <SkeletonText lines={3} className="mt-4 max-w-measure" />
            ) : historyError ? (
              <div className="mt-4">
                <ErrorState
                  title={t("ask.history.error")}
                  error={historyError}
                  onRetry={loadHistory}
                />
              </div>
            ) : history.length === 0 ? (
              <p className="mt-4 text-13 text-ink-3">{t("ask.history.empty")}</p>
            ) : (
              <ol className="mt-2 border-t border-line">
                {history.map((b) => (
                  <li key={b.briefing_id} className="border-b border-line px-1 py-2">
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                      <button
                        type="button"
                        onClick={() =>
                          pickBriefing({
                            briefing_id: b.briefing_id,
                            snapshot_ref: b.snapshot_ref,
                            // A history row carries no claims / source counts; show what it has.
                            claims_count: 0,
                            source_count: 0,
                            char_count: b.char_count,
                          })
                        }
                        className="flex min-w-0 flex-1 flex-wrap items-baseline gap-x-3 gap-y-1 rounded-1 px-1 py-0.5 text-left transition-colors duration-120 hover:bg-hover"
                      >
                        <Mono className="text-13 text-accent">{b.briefing_id}</Mono>
                        <Mono className="text-12 text-ink-3" title={b.created_at ?? undefined}>
                          {b.created_at ? fmtTime(b.created_at) : t("ask.history.noTime")}
                        </Mono>
                        <Mono className="ml-auto text-12 text-ink-3">
                          {t("ask.history.chars", { count: b.char_count })}
                        </Mono>
                      </button>
                      <BriefingText userId={currentUser} briefingId={b.briefing_id} />
                    </div>
                  </li>
                ))}
              </ol>
            )}
            <p className="mt-2 text-12 text-ink-3">{t("ask.history.hint")}</p>
          </section>
        </>
      ) : (
        <>
          {/* --------------------------------- built, and the ongoing question thread */}
          <section>
            <SectionRule
              no={1}
              title={t("ask.current.title")}
              actions={
                <Button size="sm" onClick={() => pickBriefing(null)}>
                  {t("ask.current.rebuild")}
                </Button>
              }
            />
            <DefinitionList
              className="mt-2 max-w-measure"
              items={[
                { term: "briefing_id", definition: <Mono>{briefing.briefing_id}</Mono> },
                {
                  term: "snapshot_ref",
                  definition: <Mono>{briefing.snapshot_ref || t("ask.blank")}</Mono>,
                },
                ...(briefing.claims_count > 0 || briefing.source_count > 0
                  ? [
                      {
                        term: "claims",
                        definition: <Mono>{fmtCount(briefing.claims_count)}</Mono>,
                      },
                      {
                        // `source_count` is the size of the pack's SCOPE — the sources it was
                        // anchored to — and not the number of sources its answers end up
                        // citing. A pack gathered by query is anchored to none, which is why
                        // this line read "sources 0" beside two dozen cited claims.
                        term: t("ask.current.anchoredSources"),
                        definition: <Mono>{fmtCount(briefing.source_count)}</Mono>,
                      },
                    ]
                  : []),
                {
                  term: t("ask.current.chars"),
                  definition: <Mono>{fmtCount(briefing.char_count)}</Mono>,
                },
              ]}
            />
            {/* What the build itself cost, beside what it produced. Renders nothing for a
                briefing picked out of history — that one was built in another session, and
                its breakdown comes back with the pack instead (BriefingText below). */}
            <StageStrip
              stages={briefing.stages}
              description={t("ask.stages.buildDescription")}
            />
            <div className="mt-3 flex max-w-measure flex-wrap items-baseline gap-2">
              <BriefingText
                userId={currentUser}
                briefingId={briefing.briefing_id}
                showStages={false}
              />
            </div>
          </section>

          <section>
            <SectionRule no={2} title={t("ask.thread.title")} />
            {turns.length === 0 ? (
              <div className="mt-4">
                <EmptyState
                  icon={MessagesSquare}
                  title={t("ask.thread.emptyTitle")}
                  description={t("ask.thread.emptyDescription")}
                />
              </div>
            ) : (
              <div className="mt-4 flex flex-col gap-8">
                {turns.map((turn, i) => (
                  <article key={i}>
                    <p className="text-14 font-medium text-ink">{turn.question}</p>
                    <div className="prose mt-2 max-w-measure">
                      {turn.answer ? (
                        <CitedAnswer text={turn.answer} handles={turn.handles} />
                      ) : (
                        t("ask.blank")
                      )}
                    </div>
                    {turn.citations.length > 0 ? (
                      <CitationList
                        className="mt-3 max-w-measure"
                        citations={turn.citations.map((c) => ({
                          sourceId: c.source_id,
                          blockStart: c.block_start,
                          blockEnd: c.block_end,
                          title: titles[c.source_id],
                        }))}
                        onJump={jumpToCitation}
                      />
                    ) : (
                      <Callout tone="warn" className="mt-3 max-w-measure">
                        {t("ask.thread.noCitations")}
                      </Callout>
                    )}
                    <UsageLine usage={turn.usage} className="mt-2" />
                    {/* This turn's own loop: the turns it took, the tools it reached for, and
                        the total around them. The pack is not in it — it was built once. */}
                    <StageStrip
                      stages={turn.stages}
                      description={t("ask.stages.askDescription")}
                    />
                    {turn.verbatim && turn.verbatim.length > 0 && (
                      <details className="mt-2 max-w-measure">
                        <summary className="cursor-pointer text-13 text-ink-2">
                          {t("ask.thread.verbatim", { count: turn.verbatim.length })}
                        </summary>
                        <pre className="mt-2 max-h-64 overflow-auto rounded-2 border border-line bg-surface p-3 font-mono text-12 whitespace-pre-wrap text-ink-2">
                          {JSON.stringify(turn.verbatim, null, 2)}
                        </pre>
                      </details>
                    )}
                  </article>
                ))}
              </div>
            )}

            {/* Question row */}
            <div className="mt-6 flex max-w-measure flex-col gap-2">
              {asking ? (
                <div className="flex flex-col gap-3">
                  <StageStrip
                    live={liveAsk.stages}
                    description={t("ask.stages.askDescription")}
                  />
                  {liveAsk.text ? (
                    <p className="prose max-w-measure text-14 whitespace-pre-wrap">
                      {liveAsk.text}
                    </p>
                  ) : (
                    liveAsk.stages.length === 0 && <SkeletonText lines={4} />
                  )}
                </div>
              ) : (
                askError && (
                  <ErrorState
                    title={t("ask.thread.error")}
                    error={askError}
                    onRetry={() => void onAsk()}
                  />
                )
              )}
              <div className="flex items-center gap-2">
                <TextField
                  id="ask-question"
                  name="question"
                  wrapperClassName="flex-1"
                  value={question}
                  onChange={(e) => setAskCache({ question: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void onAsk();
                  }}
                  placeholder={t("ask.thread.placeholder")}
                  aria-label={t("ask.thread.aria")}
                />
                <Button
                  variant="primary"
                  loading={asking}
                  disabled={!question.trim()}
                  onClick={() => void onAsk()}
                >
                  {t("ask.thread.action")}
                </Button>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

/**
 * The briefing pack, read back on demand.
 *
 * A briefing is plain text and the answers above are grounded in exactly it, so being able to
 * open it is the difference between trusting the pack and inspecting it. Fetched on first
 * open only (a pack runs to tens of thousands of characters), kept for the session, and
 * rendered verbatim — no markdown, because what the model was handed is the literal string.
 */
function BriefingText({
  userId,
  briefingId,
  showStages = true,
}: {
  userId: string;
  briefingId: string;
  /** false when the caller already draws the build strip beside this toggle (the
      current-briefing card), so the breakdown is not shown twice on one card. */
  showStages?: boolean;
}) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<BriefingDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getBriefing(userId, briefingId)
      .then(setDetail)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [userId, briefingId]);

  function toggle() {
    const next = !open;
    setOpen(next);
    if (next && detail == null && !loading) load();
  }

  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        onClick={toggle}
        className="shrink-0 rounded-1 px-1.5 py-0.5 text-12 text-ink-3 transition-colors duration-120 hover:bg-hover hover:text-ink"
      >
        {open ? t("ask.text.hide") : t("ask.text.show")}
      </button>
      {open && (
        <div className="w-full">
          {loading ? (
            <SkeletonText lines={4} className="mt-2" />
          ) : error ? (
            <div className="mt-2">
              <ErrorState title={t("ask.text.error")} error={error} onRetry={load} />
            </div>
          ) : detail == null ? null : detail.text === "" ? (
            <p className="mt-2 text-12 text-ink-3">{t("ask.text.empty")}</p>
          ) : (
            <>
              <p className="mt-2 text-12 text-ink-3">
                {t("ask.text.metrics", {
                  chars: detail.char_count,
                  lines: briefingTextLines(detail.text),
                })}
              </p>
              {/* A pack stored before builds were measured carries no stages and shows none:
                  "not recorded" is not "took no time", so nothing is drawn as zeros. */}
              {showStages && (
                <StageStrip
                  stages={detail.stages}
                  description={t("ask.stages.buildDescription")}
                />
              )}
              <pre className="mt-1 max-h-96 overflow-auto rounded-2 border border-line bg-surface p-3 font-mono text-12 whitespace-pre-wrap text-ink-2">
                {detail.text}
              </pre>
            </>
          )}
        </div>
      )}
    </>
  );
}
