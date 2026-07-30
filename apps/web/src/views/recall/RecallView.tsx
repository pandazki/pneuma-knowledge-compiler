import { useCallback, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useApp, type RecallMode } from "@/lib/store";
import {
  listAllSources,
  recall,
  recallAnswer,
  recallDeepStream,
  type RecallAnswer,
  type RecallHit,
  type TokenUsage,
  type TrailStep,
  type UsedClaim,
} from "@/lib/api";
import { useT } from "@/lib/useT";
import { PageHeader } from "@/components/PageHeader";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Footnote } from "@/ui/Footnote";
import { Mono } from "@/ui/Mono";
import { SearchField } from "@/ui/SearchField";
import { SectionRule } from "@/ui/SectionRule";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";
import { CitedAnswer } from "../_shared/CitedAnswer";

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
  const { query, mode, hits, answer, error } = recallCache;

  // liveTrail / searching are transients of the in-flight query; Back need not preserve them.
  const [searching, setSearching] = useState(false);
  const [liveTrail, setLiveTrail] = useState<TrailStep[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});

  // source id → title, for the hit ledger and the citation list; on failure the id shows.
  useEffect(() => {
    if (!currentUser) return;
    let alive = true;
    listAllSources(currentUser)
      .then((rows) => {
        if (!alive) return;
        setTitles(Object.fromEntries(rows.map((r) => [r.source_id, r.title])));
      })
      .catch(() => alive && setTitles({}));
    return () => {
      alive = false;
    };
  }, [currentUser]);

  // Abort the deep SSE stream on unmount.
  useEffect(() => () => abortRef.current?.abort(), []);

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
    abortRef.current?.abort();
    setSearching(true);
    setRecallCache({ error: null });
    setLiveTrail([]);
    try {
      if (mode === "rag") {
        const rows = await recall(currentUser, { query: query.trim(), mode, limit: 20 });
        setRecallCache({ answer: null, hits: rows });
      } else if (mode === "deep") {
        // deep runs over SSE: each tool call appends to liveTrail live, and the final answer
        // arrives with the done frame.
        setRecallCache({ hits: null, answer: null });
        const ac = new AbortController();
        abortRef.current = ac;
        await recallDeepStream(
          currentUser,
          query.trim(),
          {
            onStep: (s) => setLiveTrail((t) => [...t, s]),
            onDone: (a) => setRecallCache({ answer: a }),
            onError: (m) => {
              if (!ac.signal.aborted) setRecallCache({ error: m });
            },
          },
          ac.signal,
        );
      } else {
        const a = await recallAnswer(currentUser, { query: query.trim(), mode });
        setRecallCache({ hits: null, answer: a });
      }
    } catch (e) {
      setRecallCache({ error: (e as Error).message, hits: null, answer: null });
    } finally {
      setSearching(false);
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
    <div className="flex flex-col gap-6">
      <PageHeader title={t("recall.title")} description={t("recall.description")} />

      {/* Query row */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
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
      {error ? (
        <ErrorState
          title={t("recall.error.title")}
          error={error}
          onRetry={() => void onSearch()}
        />
      ) : searching && mode === "deep" ? (
        <TrailTimeline steps={liveTrail} live />
      ) : searching ? (
        <SkeletonText lines={6} className="max-w-measure" />
      ) : answer ? (
        <AnswerPanel answer={answer} titles={titles} onJump={jumpToCitation} />
      ) : hits == null ? (
        <EmptyState
          icon={Search}
          title={mode === "rag" ? t("recall.empty.ragTitle") : t("recall.empty.askTitle")}
          description={
            mode === "rag"
              ? t("recall.empty.ragDescription")
              : t("recall.empty.askDescription")
          }
        />
      ) : hits.length === 0 ? (
        <EmptyState
          icon={Search}
          title={t("recall.empty.noHitsTitle")}
          description={t("recall.empty.noHitsDescription")}
        />
      ) : (
        <HitList hits={hits} titles={titles} onJump={jumpToCitation} />
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- rag hit ledger */

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

/* ------------------------------------------------------------------ deep timeline */

/** The deep lane's tool-call timeline: mono tool + query + hits/chars, errors in danger. */
function TrailTimeline({ steps, live }: { steps: TrailStep[]; live?: boolean }) {
  const t = useT();
  return (
    <section>
      <p className="mb-2 flex items-center gap-2 text-13 text-ink-2">
        {t("recall.trail.title", { count: steps.length })}
        {live && <span className="text-12 text-ink-3">{t("recall.trail.live")}</span>}
      </p>
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
            return (
              <li key={i} className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-b border-line py-2">
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
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}

/* --------------------------------------------------------- the fast/deep answer */

function UsageDefinitionList({ usage }: { usage: TokenUsage }) {
  return (
    <DefinitionList
      className="max-w-measure"
      items={[
        { term: <Mono>input</Mono>, definition: <Mono>{usage.input_tokens}</Mono> },
        { term: <Mono>output</Mono>, definition: <Mono>{usage.output_tokens}</Mono> },
        { term: <Mono>cache_read</Mono>, definition: <Mono>{usage.cache_read}</Mono> },
        { term: <Mono>cache_creation</Mono>, definition: <Mono>{usage.cache_creation}</Mono> },
      ]}
    />
  );
}

function UsedClaimRow({
  claim,
  titles,
  onJump,
}: {
  claim: UsedClaim;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  return (
    <div className="border-b border-line py-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <Mono className="text-12 text-ink-3">{claim.anchor}</Mono>
        <Mono className="text-12 text-ink-3">{claim.document_path}</Mono>
        {claim.paths.map((p) => (
          <Badge key={p}>{p}</Badge>
        ))}
        <Mono className="ml-auto text-12 text-ink-3">score {claim.score.toFixed(4)}</Mono>
      </div>
      <p className="prose mt-1 max-w-measure text-14">{claim.text}</p>
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
  const windows = answer.used_windows ?? [];
  return (
    <div className="flex flex-col gap-6">
      {/* deep: the answer leads; the process folds away for checking */}
      {answer.mode === "deep" && trail.length > 0 && (
        <details className="max-w-measure">
          <summary className="cursor-pointer text-13 text-ink-2">
            {t("recall.trail.title", { count: trail.length })}
          </summary>
          <div className="mt-3">
            <TrailTimeline steps={trail} />
          </div>
        </details>
      )}

      <section>
        <SectionRule no={1} title={t("recall.answer.title")} />
        <p className="mt-3 text-12 text-ink-3">
          as_of <Mono>{answer.as_of}</Mono>
        </p>
        <div className="prose mt-2 max-w-measure">
          {answer.answer ? (
            <CitedAnswer text={answer.answer} handles={answer.citation_handles} />
          ) : (
            t("recall.answer.blank")
          )}
        </div>
        <div className="mt-4">
          <UsageDefinitionList usage={answer.token_usage} />
        </div>
      </section>

      {answer.used_claims.length > 0 && (
        <section>
          <SectionRule
            no={2}
            title={t("recall.usedClaims.title", { count: answer.used_claims.length })}
          />
          <div className="mt-2 border-t border-line">
            {answer.used_claims.map((c) => (
              <UsedClaimRow key={c.anchor} claim={c} titles={titles} onJump={onJump} />
            ))}
          </div>
        </section>
      )}

      {windows.length > 0 && (
        <section>
          <SectionRule no={3} title={t("recall.windows.title", { count: windows.length })} />
          <p className="mt-2 text-12 text-ink-3">{t("recall.windows.description")}</p>
          <div className="mt-2">
            <HitList hits={windows} titles={titles} onJump={onJump} />
          </div>
        </section>
      )}
    </div>
  );
}
