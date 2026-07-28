import { useCallback, useEffect, useMemo, useState } from "react";
import { MessagesSquare } from "lucide-react";
import { useApp, type AskTurn } from "@/lib/store";
import {
  askBriefing,
  buildBriefing,
  listBriefings,
  listAllSources,
  type BriefingSummary,
  type SourceSummary,
} from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { CitationList, type CitationEntry } from "@/components/CitationList";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { Checkbox } from "@/ui/Checkbox";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { NumberField } from "@/ui/NumberField";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { TextField } from "@/ui/TextField";
import { CitedAnswer } from "../_shared/CitedAnswer";
import { UsageLine } from "../_shared/UsageLine";

/**
 * ask 问答：先构建一个 source 锚定 / query 检索的 briefing（冻结知识包），
 * 再对它连续提问。构建输入与问答线程都在 store.askCache —— 跳 sources 看
 * 引用原文 + Back 不丢。
 */
export default function AskView() {
  const currentUser = useApp((s) => s.currentUser);
  const currentSnapshot = useApp((s) => s.currentSnapshot);
  const focusSource = useApp((s) => s.focusSource);
  const askCache = useApp((s) => s.askCache);
  const setAskCache = useApp((s) => s.setAskCache);
  const { scopeQuery, selected: selectedIds, briefing, question, turns } = askCache;
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);

  const [sources, setSources] = useState<SourceSummary[] | null>(null);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [history, setHistory] = useState<BriefingSummary[] | null>(null);
  const [historyError, setHistoryError] = useState<string | null>(null);
  // budget_chars 未进 store（lib 冻结），仅会话内保留；默认 4000。
  const [budget, setBudget] = useState<number | null>(4000);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);
  // AskTurn 无 verbatim_fetches 字段（lib 冻结），按轮次下标会话内暂存。
  const [verbatim, setVerbatim] = useState<Record<number, Record<string, unknown>[]>>({});

  const titles = useMemo(
    () => Object.fromEntries((sources ?? []).map((s) => [s.source_id, s.title])),
    [sources],
  );

  const loadSources = useCallback(() => {
    if (!currentUser) return;
    setSourcesError(null);
    listAllSources(currentUser)
      .then(setSources)
      .catch((e) => {
        setSources([]);
        setSourcesError((e as Error).message);
      });
  }, [currentUser]);

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
        <PageHeader title="问答 Ask" description="构建 briefing，然后连续提问。" />
        <EmptyState
          icon={MessagesSquare}
          title="未选择用户"
          description="在右上角选择一个 user_id 后，即可构建 Briefing 并连续提问。"
        />
      </>
    );
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
    try {
      const built = await buildBriefing(currentUser, {
        query: scopeQuery.trim() || null,
        source_ids: [...selected],
        budget_chars: budget ?? undefined,
        snapshot: currentSnapshot,
      });
      setAskCache({ briefing: built });
      void loadHistory();
    } catch (e) {
      setBuildError((e as Error).message);
    } finally {
      setBuilding(false);
    }
  }

  async function onAsk() {
    if (!currentUser || !briefing || !question.trim()) return;
    const q = question.trim();
    setAsking(true);
    setAskError(null);
    try {
      const res = await askBriefing(currentUser, briefing.briefing_id, q);
      const turn: AskTurn = {
        question: q,
        mode: "briefing",
        answer: res.answer,
        citations: res.citations,
        handles: res.citation_handles ?? {},
        usage: res.token_usage,
      };
      if (res.verbatim_fetches.length > 0) {
        setVerbatim((v) => ({ ...v, [turns.length]: res.verbatim_fetches }));
      }
      setAskCache({ turns: [...turns, turn], question: "" });
    } catch (e) {
      setAskError((e as Error).message);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        title="问答 Ask"
        description="把一批 claim 冻结成 briefing 知识包，再对它连续提问——每轮答案都带引用脚注与 token 账。"
      />

      {briefing == null ? (
        <>
          {/* ------------------------------------------------ 构建 briefing */}
          <section>
            <SectionRule no={1} title="构建 Briefing" />
            <div className="mt-4 flex max-w-measure flex-col gap-4">
              <TextField
                label="scope.query（检索取料）"
                value={scopeQuery}
                onChange={(e) => setAskCache({ scopeQuery: e.target.value })}
                placeholder="可选：一句检索意图"
                hint="query 与来源多选至少填一项。"
              />
              <div>
                <p className="text-13 font-medium text-ink-2">scope.source_ids（锚定原始来源）</p>
                {sources == null ? (
                  <SkeletonText lines={3} className="mt-2" />
                ) : sourcesError ? (
                  <div className="mt-2">
                    <ErrorState title="来源列表拉取失败" error={sourcesError} onRetry={loadSources} />
                  </div>
                ) : sources.length === 0 ? (
                  <p className="mt-2 text-13 text-ink-3">
                    （无来源——可只靠 query 构建；或先去「导入 Ingest」入库材料）
                  </p>
                ) : (
                  <ol className="mt-2 border-t border-line">
                    {sources.map((s) => (
                      <li key={s.source_id} className="border-b border-line py-2">
                        <Checkbox
                          checked={selected.has(s.source_id)}
                          onCheckedChange={() => toggleSource(s.source_id)}
                          label={s.title}
                          hint={
                            <Mono>
                              {s.source_id} · {s.kind} · {s.block_count} blocks
                            </Mono>
                          }
                        />
                      </li>
                    ))}
                  </ol>
                )}
              </div>
              <NumberField
                label="budget_chars（字符预算）"
                value={budget}
                onChange={setBudget}
                min={500}
                max={20000}
                step={500}
              />
              <p className="text-12 text-ink-3">
                快照：
                {currentSnapshot ? (
                  <>
                    <Mono>{currentSnapshot}</Mono>（历史只读）
                  </>
                ) : (
                  "当前 HEAD"
                )}
              </p>
              {buildError && (
                <ErrorState title="构建失败" error={buildError} onRetry={() => void onBuild()} />
              )}
              <div>
                <Button
                  variant="primary"
                  loading={building}
                  disabled={!canBuild}
                  onClick={() => void onBuild()}
                >
                  构建 Briefing
                </Button>
              </div>
            </div>
          </section>

          {/* ------------------------------------------------ 历史 briefing */}
          <section>
            <SectionRule no={2} title="历史 Briefing" />
            {history == null ? (
              <SkeletonText lines={3} className="mt-4 max-w-measure" />
            ) : historyError ? (
              <div className="mt-4">
                <ErrorState title="历史拉取失败" error={historyError} onRetry={loadHistory} />
              </div>
            ) : history.length === 0 ? (
              <p className="mt-4 text-13 text-ink-3">还没有构建过 briefing。</p>
            ) : (
              <ol className="mt-2 border-t border-line">
                {history.map((b) => (
                  <li key={b.briefing_id} className="border-b border-line">
                    <button
                      type="button"
                      onClick={() =>
                        setAskCache({
                          briefing: {
                            briefing_id: b.briefing_id,
                            snapshot_ref: b.snapshot_ref,
                            // 历史条目不带 claims/source 计数，只展示有的字段。
                            claims_count: 0,
                            source_count: 0,
                            char_count: b.char_count,
                          },
                        })
                      }
                      className="flex w-full flex-wrap items-baseline gap-x-3 gap-y-1 px-1 py-2 text-left transition-colors duration-120 hover:bg-hover"
                    >
                      <Mono className="text-13 text-accent">{b.briefing_id}</Mono>
                      <Mono className="text-12 text-ink-3">{b.created_at ?? "（无时间）"}</Mono>
                      <Mono className="ml-auto text-12 text-ink-3">{b.char_count} 字</Mono>
                    </button>
                  </li>
                ))}
              </ol>
            )}
            <p className="mt-2 text-12 text-ink-3">选中一条即可在它的知识包上继续提问。</p>
          </section>
        </>
      ) : (
        <>
          {/* ------------------------------------------------ 已构建 + 连续问答 */}
          <section>
            <SectionRule
              no={1}
              title="当前 Briefing"
              actions={
                <Button size="sm" onClick={() => setAskCache({ briefing: null })}>
                  重新构建 briefing
                </Button>
              }
            />
            <DefinitionList
              className="mt-2 max-w-measure"
              items={[
                { term: "briefing_id", definition: <Mono>{briefing.briefing_id}</Mono> },
                {
                  term: "snapshot_ref",
                  definition: <Mono>{briefing.snapshot_ref || "（空）"}</Mono>,
                },
                ...(briefing.claims_count > 0 || briefing.source_count > 0
                  ? [
                      { term: "claims", definition: <Mono>{briefing.claims_count}</Mono> },
                      { term: "来源", definition: <Mono>{briefing.source_count}</Mono> },
                    ]
                  : []),
                { term: "字符", definition: <Mono>{briefing.char_count}</Mono> },
              ]}
            />
          </section>

          <section>
            <SectionRule no={2} title="连续问答" />
            {turns.length === 0 ? (
              <div className="mt-4">
                <EmptyState
                  icon={MessagesSquare}
                  title="还没有提问"
                  description="在下方输入问题——briefing 问法复用冻结的知识包，每轮答案都带引用脚注。"
                />
              </div>
            ) : (
              <div className="mt-4 flex flex-col gap-8">
                {turns.map((t, i) => (
                  <article key={i}>
                    <p className="text-14 font-medium text-ink">{t.question}</p>
                    <div className="prose mt-2 max-w-measure">
                      {t.answer ? <CitedAnswer text={t.answer} handles={t.handles} /> : "（空）"}
                    </div>
                    {t.citations.length > 0 ? (
                      <CitationList
                        className="mt-3 max-w-measure"
                        citations={t.citations.map((c) => ({
                          sourceId: c.source_id,
                          blockStart: c.block_start,
                          blockEnd: c.block_end,
                          title: titles[c.source_id],
                        }))}
                        onJump={jumpToCitation}
                      />
                    ) : (
                      <Callout tone="warn" className="mt-3 max-w-measure">
                        本轮没有返回 source 引用；答案可阅读，但尚未完成证据绑定。
                      </Callout>
                    )}
                    <UsageLine usage={t.usage} className="mt-2" />
                    {(verbatim[i]?.length ?? 0) > 0 && (
                      <details className="mt-2 max-w-measure">
                        <summary className="cursor-pointer text-13 text-ink-2">
                          verbatim_fetches（{verbatim[i].length}）
                        </summary>
                        <pre className="mt-2 max-h-64 overflow-auto rounded-2 border border-line bg-surface p-3 font-mono text-12 whitespace-pre-wrap text-ink-2">
                          {JSON.stringify(verbatim[i], null, 2)}
                        </pre>
                      </details>
                    )}
                  </article>
                ))}
              </div>
            )}

            {/* 提问行 */}
            <div className="mt-6 flex max-w-measure flex-col gap-2">
              {asking ? (
                <SkeletonText lines={4} />
              ) : (
                askError && (
                  <ErrorState title="提问失败" error={askError} onRetry={() => void onAsk()} />
                )
              )}
              <div className="flex items-center gap-2">
                <TextField
                  wrapperClassName="flex-1"
                  value={question}
                  onChange={(e) => setAskCache({ question: e.target.value })}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void onAsk();
                  }}
                  placeholder="对当前 Briefing 提问"
                  aria-label="提问"
                />
                <Button
                  variant="primary"
                  loading={asking}
                  disabled={!question.trim()}
                  onClick={() => void onAsk()}
                >
                  提问
                </Button>
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  );
}
