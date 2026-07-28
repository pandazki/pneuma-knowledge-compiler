import { useCallback, useEffect, useRef, useState } from "react";
import { Search } from "lucide-react";
import { useApp, type RecallMode } from "@/lib/store";
import {
  listSources,
  recall,
  recallAnswer,
  recallDeepStream,
  type RecallAnswer,
  type RecallHit,
  type TokenUsage,
  type TrailStep,
  type UsedClaim,
} from "@/lib/api";
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

/** 三 lane 的输入与结果都在 store.recallCache：跳 sources 看原文 + Back 不丢。 */
export default function RecallView() {
  const currentUser = useApp((s) => s.currentUser);
  const focusSource = useApp((s) => s.focusSource);
  const recallCache = useApp((s) => s.recallCache);
  const setRecallCache = useApp((s) => s.setRecallCache);
  const { query, mode, hits, answer, error } = recallCache;

  // liveTrail / searching 是在途查询的瞬态，不需要随 Back 保留。
  const [searching, setSearching] = useState(false);
  const [liveTrail, setLiveTrail] = useState<TrailStep[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});

  // source id → 标题（命中账与引用列表展示用；失败则退回显示 id）。
  useEffect(() => {
    if (!currentUser) return;
    let alive = true;
    listSources(currentUser)
      .then((rows) => {
        if (!alive) return;
        setTitles(Object.fromEntries(rows.map((r) => [r.source_id, r.title])));
      })
      .catch(() => alive && setTitles({}));
    return () => {
      alive = false;
    };
  }, [currentUser]);

  // 卸载时中断 deep SSE。
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
        // deep 走 SSE：每个工具调用实时追加到 liveTrail，最终答案随 done 帧到达。
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
        <PageHeader title="检索 Recall" description="rag / fast / deep 三条检索 lane。" />
        <EmptyState
          icon={Search}
          title="未选择用户"
          description="在右上角选择一个 user_id 后，即可对其知识库做检索。"
        />
      </>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="检索 Recall"
        description="同一个查询可在 rag / fast / deep 三条 lane 上重跑对比：命中账、直接作答、带核验的深查。"
      />

      {/* 查询行 */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchField
          wrapperClassName="min-w-56 flex-1"
          value={query}
          onChange={(v) => setRecallCache({ query: v })}
          onKeyDown={(e) => {
            if (e.key === "Enter") void onSearch();
          }}
          placeholder={
            mode === "rag" ? "查询词，如「发布 门禁」" : "自然语言提问，如「发布前还缺什么」"
          }
          aria-label="检索查询"
        />
        <SegmentedControl
          aria-label="检索模式"
          value={mode}
          onChange={(m) => setRecallCache({ mode: m as RecallMode })}
          options={[
            { value: "rag", label: "rag" },
            { value: "fast", label: "fast" },
            { value: "deep", label: "deep" },
          ]}
        />
        <Button
          variant="primary"
          loading={searching}
          disabled={!query.trim()}
          onClick={() => void onSearch()}
        >
          {mode === "rag" ? "检索" : "提问"}
        </Button>
      </div>

      {/* 结果 */}
      {error ? (
        <ErrorState title="检索失败" error={error} onRetry={() => void onSearch()} />
      ) : searching && mode === "deep" ? (
        <TrailTimeline steps={liveTrail} live />
      ) : searching ? (
        <SkeletonText lines={6} className="max-w-measure" />
      ) : answer ? (
        <AnswerPanel answer={answer} titles={titles} onJump={jumpToCitation} />
      ) : hits == null ? (
        <EmptyState
          icon={Search}
          title={mode === "rag" ? "输入查询开始检索" : "提问开始作答"}
          description={
            mode === "rag"
              ? "rag 跑 L2 语义 + L1 词法双路，命中经 RRF 融合排序。"
              : "fast 基于 canonical claim 直接作答；deep 再对引用逐条核验。"
          }
        />
      ) : hits.length === 0 ? (
        <EmptyState
          icon={Search}
          title="无命中"
          description="换个查询词，或先去「导入 Ingest」入库更多材料。"
        />
      ) : (
        <HitList hits={hits} titles={titles} onJump={jumpToCitation} />
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- rag 命中账 */

function HitList({
  hits,
  titles,
  onJump,
}: {
  hits: RecallHit[];
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  return (
    <section>
      <p className="mb-2 text-13 text-ink-2">{hits.length} 条命中 · 点击脚注定位到原文</p>
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

/* --------------------------------------------------------------- deep 时间线 */

/** deep 的工具调用时间线：tool mono + query + hits/chars，错误用 danger。 */
function TrailTimeline({ steps, live }: { steps: TrailStep[]; live?: boolean }) {
  return (
    <section>
      <p className="mb-2 flex items-center gap-2 text-13 text-ink-2">
        深查过程（{steps.length} 步）
        {live && <span className="text-12 text-ink-3">进行中…</span>}
      </p>
      {steps.length === 0 && live ? (
        <SkeletonText lines={3} className="max-w-measure" />
      ) : (
        <ol className="border-t border-line">
          {steps.map((s, i) => {
            const arg =
              s.query ?? (s.source_id ? `${s.source_id} ${JSON.stringify(s.locator ?? {})}` : "");
            const meta = s.error
              ? `失败：${s.error}`
              : s.hits != null
                ? `${s.hits} 命中`
                : s.chars != null
                  ? `${s.chars} 字`
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

/* ------------------------------------------------------------- fast/deep 答案 */

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
  const trail = answer.trail ?? [];
  const windows = answer.used_windows ?? [];
  return (
    <div className="flex flex-col gap-6">
      {/* deep：答案是头条，过程折叠备查 */}
      {answer.mode === "deep" && trail.length > 0 && (
        <details className="max-w-measure">
          <summary className="cursor-pointer text-13 text-ink-2">
            深查过程（{trail.length} 步）
          </summary>
          <div className="mt-3">
            <TrailTimeline steps={trail} />
          </div>
        </details>
      )}

      <section>
        <SectionRule no={1} title="答案" />
        <p className="mt-3 text-12 text-ink-3">
          as_of <Mono>{answer.as_of}</Mono>
        </p>
        <div className="prose mt-2 max-w-measure">
          {answer.answer ? (
            <CitedAnswer text={answer.answer} handles={answer.citation_handles} />
          ) : (
            "（空）"
          )}
        </div>
        <div className="mt-4">
          <UsageDefinitionList usage={answer.token_usage} />
        </div>
      </section>

      {answer.used_claims.length > 0 && (
        <section>
          <SectionRule no={2} title={`依据 claim（${answer.used_claims.length}）`} />
          <div className="mt-2 border-t border-line">
            {answer.used_claims.map((c) => (
              <UsedClaimRow key={c.anchor} claim={c} titles={titles} onJump={onJump} />
            ))}
          </div>
        </section>
      )}

      {windows.length > 0 && (
        <section>
          <SectionRule no={3} title={`原文摘录（${windows.length}）`} />
          <p className="mt-2 text-12 text-ink-3">未编译为 claim 的原始内容，同样可定位回原文。</p>
          <div className="mt-2">
            <HitList hits={windows} titles={titles} onJump={onJump} />
          </div>
        </section>
      )}
    </div>
  );
}
