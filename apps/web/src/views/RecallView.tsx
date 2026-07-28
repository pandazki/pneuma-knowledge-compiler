import { useState } from "react";
import { Search, Loader2, Radar, ArrowRight, Quote, FileText } from "lucide-react";
import { useApp, type RecallMode } from "@/lib/store";
import { Button, Chip, EmptyState, Eyebrow } from "@/components/ui";
import { cn } from "@/lib/cn";
import { CitedAnswer } from "@/lib/citeInline";
import { extractClaimLabel } from "@/lib/claim";
import { ClaimLabelBadge } from "@/components/ClaimView";
import * as api from "@/lib/api";

const PATH_COLOR: Record<string, string> = {
  lexical: "var(--color-info, var(--color-accent))",
  vector: "var(--color-accent)",
};

export function RecallView() {
  // inputs + last result live in the store so a Sources jump + Back keeps them (per user).
  const { currentUser, focusSource, recallCache, setRecallCache } = useApp();
  const { query, mode, hits, answer, error } = recallCache;
  // liveTrail + searching are transient to the in-flight query — no need to survive a jump.
  const [liveTrail, setLiveTrail] = useState<api.TrailStep[]>([]);
  const [searching, setSearching] = useState(false);

  async function onSearch() {
    if (!currentUser || !query.trim()) return;
    setSearching(true);
    setRecallCache({ error: null });
    setLiveTrail([]);
    try {
      if (mode === "rag") {
        const rows = await api.recall(currentUser, { query: query.trim(), mode, limit: 20 });
        setRecallCache({ answer: null, hits: rows });
      } else if (mode === "deep") {
        // deep streams its agentic steps: each tool call appends to liveTrail as it lands,
        // then the final answer arrives. Step-level increments, not token streaming.
        setRecallCache({ hits: null, answer: null });
        await api.recallDeepStream(currentUser, query.trim(), {
          onStep: (s) => setLiveTrail((t) => [...t, s]),
          onDone: (a) => setRecallCache({ answer: a }),
          onError: (m) => setRecallCache({ error: m }),
        });
      } else {
        const a = await api.recallAnswer(currentUser, { query: query.trim(), mode });
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
      <EmptyState
        icon={<Radar size={28} />}
        title="未选择用户"
        hint="在右上角选择一个 user_id 后即可对其知识库做召回。"
      />
    );
  }

  const eyebrow =
    mode === "rag"
      ? "Recall · L2+L1 双路 + RRF"
      : mode === "fast"
        ? "Recall · fast · canonical claim 密集消费"
        : "Recall · deep · claim 消费 + 有界核验";

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* query bar */}
      <div className="border-b border-border bg-card px-5 py-4">
        <Eyebrow>{eyebrow}</Eyebrow>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <div className="relative min-w-[16rem] flex-1">
            <Search
              size={14}
              className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground"
            />
            <input
              className="h-9 w-full rounded-sm border border-border bg-card pl-8 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={query}
              onChange={(e) => setRecallCache({ query: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") void onSearch();
              }}
              placeholder={
                mode === "rag"
                  ? "查询词，如「Atlas 发布 门禁」"
                  : "自然语言提问，如「公开发布前还缺什么」"
              }
            />
          </div>
          <div className="relative">
            <select
              aria-label="召回 mode"
              value={mode}
              onChange={(e) => setRecallCache({ mode: e.target.value as RecallMode })}
              className="h-9 appearance-none rounded-sm border border-border bg-card px-3 pr-7 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="rag">rag</option>
              <option value="fast">fast</option>
              <option value="deep">deep</option>
            </select>
          </div>
          <Button variant="primary" size="md" disabled={searching || !query.trim()} onClick={onSearch}>
            {searching ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}
            {mode === "rag" ? "召回" : "提问"}
          </Button>
        </div>
      </div>

      {/* results */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {error ? (
          <EmptyState icon={<Radar size={28} />} title="召回失败" hint={error} />
        ) : answer ? (
          <AnswerPanel answer={answer} onJump={focusSource} />
        ) : mode === "deep" && searching ? (
          <div className="mx-auto max-w-3xl px-5 py-4">
            <DeepTrail steps={liveTrail} live />
          </div>
        ) : hits == null ? (
          <EmptyState
            icon={<Radar size={28} />}
            title={mode === "rag" ? "输入查询开始召回" : "提问开始 claim 问答"}
            hint={
              mode === "rag"
                ? "rag 模式跑 L2 语义 + L1 词法双路，命中经 RRF 融合排序。"
                : "fast 基于 canonical claim 注记直接作答；deep 再对引用逐条 L0 核验。"
            }
          />
        ) : hits.length === 0 ? (
          <EmptyState icon={<Radar size={28} />} title="无命中" hint="换个查询词，或先入库更多数据。" />
        ) : (
          <div className="mx-auto max-w-3xl px-5 py-4">
            <div className="mb-2 text-[length:var(--text-2xs)] font-medium text-muted-foreground">
              {hits.length} 命中 · 点击定位到 Sources
            </div>
            <div className="space-y-2">
              {hits.map((h, i) => (
                <button
                  key={i}
                  onClick={() =>
                    focusSource(h.source_id, { start: h.block_start, end: h.block_end })
                  }
                  className={cn(
                    "group block w-full border border-border rounded-sm px-4 py-3 text-left",
                    "outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                  )}
                >
                  <div className="flex flex-wrap items-center gap-1.5 text-[length:var(--text-2xs)]">
                    {h.paths.map((p) => (
                      <Chip key={p} dotColor={PATH_COLOR[p] ?? "var(--color-border-strong)"}>
                        {p}
                      </Chip>
                    ))}
                    <span className="font-mono text-muted-foreground">
                      {h.source_id.slice(0, 8)}…#{h.block_start}–{h.block_end}
                    </span>
                    <span className="ml-auto font-mono text-muted-foreground">
                      score {h.score.toFixed(4)}
                    </span>
                    <ArrowRight
                      size={13}
                      className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                    />
                  </div>
                  <div className="mt-1.5 break-words text-sm leading-6">{h.text}</div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** The deep agentic search process, one row per tool call. `live` = still streaming (steps
 * arrive incrementally via SSE), so show a spinner and keep it visible even at 0 steps. */
function DeepTrail({
  steps,
  live,
  collapsed,
}: {
  steps: api.TrailStep[];
  live?: boolean;
  collapsed?: boolean;
}) {
  if (steps.length === 0 && !live) return null;
  const title = (
    <span className="inline-flex items-center gap-1.5">
      <Search size={12} /> 深查过程（{steps.length} 步）
      {live && <Loader2 size={12} className="animate-spin text-[var(--color-accent)]" />}
    </span>
  );
  const body = (
    <ol className="space-y-1.5">
      {steps.map((step, i) => {
          const label =
            step.tool === "search_claims"
              ? "搜 claim"
              : step.tool === "search_content"
                ? "搜原文"
                : step.tool === "fetch_verbatim"
                  ? "取原文"
                  : step.tool;
          const arg =
            step.query ??
            (step.source_id
              ? `${step.source_id.slice(0, 8)}… ${JSON.stringify(step.locator ?? {})}`
              : "");
          const meta = step.error
            ? "失败"
            : step.hits != null
              ? `命中 ${step.hits}`
              : step.chars != null
                ? `${step.chars} 字`
                : "";
          return (
            <li key={i} className="rounded-sm border border-border bg-card">
              <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-[length:var(--text-2xs)]">
                <span className="font-mono text-muted-foreground">{i + 1}</span>
                <Chip dotColor="var(--color-accent)">{label}</Chip>
                {arg && <span className="min-w-0 truncate text-foreground">{arg}</span>}
                {meta && (
                  <span
                    className={cn(
                      "ml-auto whitespace-nowrap",
                      step.error ? "text-[var(--color-danger)]" : "text-muted-foreground",
                    )}
                  >
                    {meta}
                  </span>
                )}
              </div>
              {(step.result || step.error) && (
                <details className="border-t border-border-subtle px-3 py-2">
                  <summary className="cursor-pointer text-[length:var(--text-2xs)] text-muted-foreground">
                    结果
                  </summary>
                  <pre className="mt-1.5 max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-[length:var(--text-2xs)] leading-5 text-foreground">
                    {step.result || step.error}
                  </pre>
                </details>
              )}
            </li>
          );
        })}
      </ol>
  );
  if (collapsed) {
    return (
      <details className="rounded-sm border border-border bg-card px-3 py-2">
        <summary className="cursor-pointer list-none text-[length:var(--text-2xs)] font-medium text-muted-foreground">
          {title}
        </summary>
        <div className="mt-2">{body}</div>
      </details>
    );
  }
  return (
    <div>
      <div className="mb-2 text-[length:var(--text-2xs)] font-medium text-muted-foreground">{title}</div>
      {body}
    </div>
  );
}

/** fast/deep answer + the capped claims that informed it. */
function AnswerPanel({
  answer,
  onJump,
}: {
  answer: api.RecallAnswer;
  onJump: (sourceId: string, range?: { start: number; end: number } | null) => void;
}) {
  const windows = answer.used_windows ?? [];
  const trail = answer.trail ?? [];
  // claim-prefix vocabulary rides the store's dataset meta (single data flow, no 2nd request).
  const claimLabels = useApp((s) => s.model?.dataset.claimLabels);
  return (
    <div className="mx-auto max-w-3xl space-y-4 px-5 py-4">
      {/* deep: the search process, auto-collapsed once the answer is in — the answer is
          the headline, the process is available on demand above it. */}
      {answer.mode === "deep" && <DeepTrail steps={trail} collapsed />}

      <div className="rounded-sm border border-border bg-card p-4">
        <div className="flex items-center gap-2">
          <Chip dotColor="var(--color-accent)">{answer.mode}</Chip>
          <span className="text-[length:var(--text-2xs)] text-muted-foreground">as_of {answer.as_of}</span>
        </div>
        <div className="mt-2 break-words text-[length:var(--text-base)] font-medium leading-7">
          {answer.answer ? (
            <CitedAnswer text={answer.answer} handles={answer.citation_handles} />
          ) : (
            "（空）"
          )}
        </div>
      </div>

      <UsageBar usage={answer.token_usage} />

      <div>
        <div className="mb-2 flex items-center gap-1.5 text-[length:var(--text-2xs)] font-medium text-muted-foreground">
          <Quote size={12} /> 依据 claim（{answer.used_claims.length}）· 点击引用定位到 Sources
        </div>
        <div className="space-y-2">
          {answer.used_claims.map((c) => {
            const labeled = extractClaimLabel(c.text, claimLabels);
            return (
            <div
              key={c.anchor}
              className="border border-border rounded-sm px-4 py-3"
            >
              <div className="flex flex-wrap items-center gap-1.5 text-[length:var(--text-2xs)]">
                {c.paths.map((p) => (
                  <Chip key={p} dotColor={PATH_COLOR[p] ?? "var(--color-border-strong)"}>
                    {p}
                  </Chip>
                ))}
                <span className="font-mono text-muted-foreground">
                  c:{c.anchor.slice(0, 8)} · {c.document_path}
                </span>
              </div>
              <div className="mt-1.5 break-words text-sm leading-6">
                {labeled && (
                  <>
                    <ClaimLabelBadge label={labeled.label} />{" "}
                  </>
                )}
                {labeled ? labeled.rest : c.text}
              </div>
              {c.citations.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {c.citations.map((cit, i) => (
                    <Chip
                      key={i}
                      onClick={() =>
                        onJump(cit.source_id, { start: cit.block_start, end: cit.block_end })
                      }
                      title="定位到 Sources"
                    >
                      {cit.source_id.slice(0, 8)}…¶{cit.block_start}–{cit.block_end}
                    </Chip>
                  ))}
                </div>
              )}
            </div>
            );
          })}
        </div>
      </div>

      {windows.length > 0 && (
        <div>
          <div className="mb-2 flex items-center gap-1.5 text-[length:var(--text-2xs)] font-medium text-muted-foreground">
            <FileText size={12} /> 原文摘录（{windows.length}）· 未编译为 claim 的原始内容 · 点击定位到 Sources
          </div>
          <div className="space-y-2">
            {windows.map((w, i) => (
              <button
                key={i}
                onClick={() =>
                  onJump(w.source_id, { start: w.block_start, end: w.block_end })
                }
                className={cn(
                  "group block w-full border border-border rounded-sm px-4 py-3 text-left",
                  "outline-none transition-colors hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring",
                )}
              >
                <div className="flex flex-wrap items-center gap-1.5 text-[length:var(--text-2xs)]">
                  {w.paths.map((p) => (
                    <Chip key={p} dotColor={PATH_COLOR[p] ?? "var(--color-border-strong)"}>
                      {p}
                    </Chip>
                  ))}
                  <span className="font-mono text-muted-foreground">
                    {w.source_id.slice(0, 8)}…¶{w.block_start}–{w.block_end}
                  </span>
                  <span className="ml-auto font-mono text-muted-foreground">
                    score {w.score.toFixed(4)}
                  </span>
                  <ArrowRight
                    size={13}
                    className="text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
                  />
                </div>
                <div className="mt-1.5 break-words text-sm leading-6">{w.text}</div>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

/** Per-answer token usage — cache_read is non-zero only against a real provider. */
export function UsageBar({ usage }: { usage: api.TokenUsage }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--text-2xs)] font-mono text-muted-foreground">
      <span>in {usage.input_tokens}</span>
      <span>out {usage.output_tokens}</span>
      <span>total {usage.total_tokens}</span>
      <span title="provider cache 命中 token（scripted 模型恒为 0）">
        cache_read {usage.cache_read}
      </span>
      <span>cache_creation {usage.cache_creation}</span>
    </div>
  );
}
