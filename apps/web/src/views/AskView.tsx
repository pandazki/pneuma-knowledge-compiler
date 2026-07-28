import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, Camera, Layers, Loader2, MessagesSquare, Send } from "lucide-react";
import { useApp, type AskMode, type AskTurn } from "@/lib/store";
import { Button, Chip, EmptyState, Eyebrow } from "@/components/ui";
import { CitedAnswer } from "@/lib/citeInline";
import * as api from "@/lib/api";
import { UsageBar } from "./RecallView";

/**
 * Ask panel (M4): build a source-anchored / query briefing over the active snapshot,
 * then ask it — three ways. briefing-ask replays the stable pack (/briefings/{id}/ask);
 * fast/deep answer over the live canonical claim projection (/recall).
 */
export function AskView() {
  const { currentUser, currentSnapshot, focusSource } = useApp();
  // build inputs + conversation live in the store so a Sources jump + Back keeps them.
  const { askCache, setAskCache } = useApp();
  const { scopeQuery, selected: selectedIds, briefing, askMode, question, turns } = askCache;
  const selected = useMemo(() => new Set(selectedIds), [selectedIds]);
  const [sources, setSources] = useState<api.SourceSummary[]>([]);
  const [building, setBuilding] = useState(false);
  const [buildError, setBuildError] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState<string | null>(null);

  // The cache (briefing / turns / selection) is reset per user in the store on `setUser`;
  // here we only (re)load the source list for the active user.
  useEffect(() => {
    if (!currentUser) return;
    api
      .listSources(currentUser)
      .then(setSources)
      .catch(() => setSources([]));
  }, [currentUser]);

  if (!currentUser) {
    return (
      <EmptyState
        icon={<MessagesSquare size={28} />}
        title="未选择用户"
        hint="在右上角选择一个 user_id 后即可构建 Briefing 并连续提问。"
      />
    );
  }

  function toggleSource(id: string) {
    const next = selected.has(id)
      ? selectedIds.filter((x) => x !== id)
      : [...selectedIds, id];
    setAskCache({ selected: next });
  }

  async function onBuild() {
    if (!currentUser) return;
    if (!scopeQuery.trim() && selected.size === 0) {
      setBuildError("请至少填写一个 query 或选中一个来源。");
      return;
    }
    setBuilding(true);
    setBuildError(null);
    try {
      const built = await api.buildBriefing(currentUser, {
        query: scopeQuery.trim() || null,
        source_ids: [...selected],
        snapshot: currentSnapshot,
      });
      setAskCache({ briefing: built });
    } catch (e) {
      setBuildError((e as Error).message);
      setAskCache({ briefing: null });
    } finally {
      setBuilding(false);
    }
  }

  async function onAsk() {
    if (!currentUser || !question.trim()) return;
    if (askMode === "briefing" && !briefing) {
      setAskError("briefing 问法需先构建 Briefing。");
      return;
    }
    const q = question.trim();
    setAsking(true);
    setAskError(null);
    try {
      let turn: AskTurn;
      if (askMode === "briefing" && briefing) {
        const res = await api.askBriefing(currentUser, briefing.briefing_id, q);
        turn = {
          question: q,
          mode: askMode,
          answer: res.answer,
          citations: res.citations,
          handles: res.citation_handles ?? {},
          usage: res.token_usage,
        };
      } else {
        const res = await api.recallAnswer(currentUser, { query: q, mode: askMode as "fast" | "deep" });
        const citations = res.used_claims.flatMap((c) => c.citations);
        turn = {
          question: q,
          mode: askMode,
          answer: res.answer,
          citations,
          handles: res.citation_handles ?? {},
          usage: res.token_usage,
        };
      }
      setAskCache({ turns: [...turns, turn], question: "" });
    } catch (e) {
      setAskError((e as Error).message);
    } finally {
      setAsking(false);
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col lg:flex-row">
      {/* ── build region ─────────────────────────────────────────── */}
      <aside className="flex min-h-0 flex-col border-b border-border bg-card lg:w-80 lg:flex-none lg:border-b-0 lg:border-r">
        <div className="border-b border-border px-4 py-3">
          <Eyebrow>构建 Briefing</Eyebrow>
          <div className="mt-1 flex items-center gap-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
            <Camera size={11} />
            快照：{currentSnapshot ? `${currentSnapshot.slice(0, 8)}（历史只读）` : "当前 HEAD"}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <label className="text-[length:var(--text-2xs)] font-medium text-muted-foreground">scope.query（检索取料）</label>
          <textarea
            className="mt-1 h-16 w-full resize-none rounded-sm border border-border bg-card px-2.5 py-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={scopeQuery}
            onChange={(e) => setAskCache({ scopeQuery: e.target.value })}
            placeholder="可选：一句检索意图"
          />
          <div className="mt-3 text-[length:var(--text-2xs)] font-medium text-muted-foreground">
            scope.source_ids（锚定原始来源）
          </div>
          <div className="mt-1 space-y-1">
            {sources.length === 0 ? (
              <div className="text-[length:var(--text-2xs)] text-muted-foreground">（无来源）</div>
            ) : (
              sources.map((s) => (
                <label
                  key={s.source_id}
                  className="flex cursor-pointer items-start gap-2 rounded-sm px-1.5 py-1 text-xs hover:bg-accent"
                >
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={selected.has(s.source_id)}
                    onChange={() => toggleSource(s.source_id)}
                  />
                  <span className="min-w-0">
                    <span className="block truncate">{s.title}</span>
                    <span className="block truncate font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                      {s.source_id.slice(0, 8)}… · {s.kind}
                    </span>
                  </span>
                </label>
              ))
            )}
          </div>
          {buildError && (
            <div className="mt-2 text-[length:var(--text-2xs)] text-[var(--color-danger,#c00)]">{buildError}</div>
          )}
        </div>
        <div className="border-t border-border px-4 py-3">
          <Button variant="primary" size="md" className="w-full" disabled={building} onClick={onBuild}>
            {building ? <Loader2 size={14} className="animate-spin" /> : <Layers size={14} />}
            构建 Briefing
          </Button>
          {briefing && (
            <div className="mt-2 rounded-sm border border-border px-2.5 py-2 text-[length:var(--text-2xs)] text-muted-foreground">
              <div className="font-medium text-foreground">已构建（pack 摘要）</div>
              <div className="mt-1 flex flex-wrap gap-1.5">
                <Chip>claims {briefing.claims_count}</Chip>
                <Chip>来源 {briefing.source_count}</Chip>
                <Chip>{briefing.char_count} 字符</Chip>
              </div>
              <div className="mt-1 font-mono">
                snapshot {briefing.snapshot_ref ? briefing.snapshot_ref.slice(0, 8) : "（空）"}
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* ── conversation region ──────────────────────────────────── */}
      <section className="flex min-h-0 flex-1 flex-col">
        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {turns.length === 0 ? (
            <EmptyState
              icon={<MessagesSquare size={28} />}
              title="连续提问"
              hint="briefing 问法复用稳定知识包（/briefings/{id}/ask）；fast/deep 走 /recall 直接消费 canonical claim。"
            />
          ) : (
            <div className="mx-auto max-w-3xl space-y-4">
              {turns.map((t, i) => (
                <div key={i} className="space-y-2">
                  <div className="flex items-center gap-2 text-sm">
                    <Chip dotColor="var(--color-border-strong)">{t.mode}</Chip>
                    <span className="font-medium">{t.question}</span>
                  </div>
                  <div className="rounded-sm border border-border bg-card px-4 py-3">
                    <div className="break-words text-[length:var(--text-base)] leading-7">
                      {t.answer ? (
                        <CitedAnswer text={t.answer} handles={t.handles} />
                      ) : (
                        "（空）"
                      )}
                    </div>
                    {t.citations.length > 0 ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {t.citations.map((c, j) => (
                          <Chip
                            key={j}
                            onClick={() =>
                              focusSource(c.source_id, { start: c.block_start, end: c.block_end })
                            }
                            title="定位到 Sources"
                          >
                            {c.source_id.slice(0, 8)}…¶{c.block_start}–{c.block_end}
                          </Chip>
                        ))}
                      </div>
                    ) : (
                      <div className="mt-2 flex items-start gap-1.5 border-l-2 border-[var(--color-warning)] bg-[var(--color-surface-muted)] px-2.5 py-2 text-[length:var(--text-2xs)] text-muted-foreground">
                        <AlertTriangle size={12} className="mt-0.5 flex-none text-[var(--color-warning)]" />
                        本轮没有返回 source citation；答案可阅读，但尚未完成证据绑定。
                      </div>
                    )}
                    <div className="mt-2">
                      <UsageBar usage={t.usage} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* ask bar */}
        <div className="border-t border-border bg-card px-5 py-3">
          {askError && (
            <div className="mb-2 text-[length:var(--text-2xs)] text-[var(--color-danger,#c00)]">{askError}</div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <select
                aria-label="问法"
                value={askMode}
                onChange={(e) => setAskCache({ askMode: e.target.value as AskMode })}
                className="h-9 appearance-none rounded-sm border border-border bg-card px-3 pr-7 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                <option value="briefing">briefing</option>
                <option value="fast">fast</option>
                <option value="deep">deep</option>
              </select>
            </div>
            <input
              className="h-9 min-w-[14rem] flex-1 rounded-sm border border-border bg-card px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              value={question}
              onChange={(e) => setAskCache({ question: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") void onAsk();
              }}
              placeholder={askMode === "briefing" ? "对已构建的 Briefing 提问" : "自然语言提问"}
            />
            <Button
              variant="primary"
              size="md"
              disabled={asking || !question.trim() || (askMode === "briefing" && !briefing)}
              onClick={onAsk}
            >
              {asking ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              提问
            </Button>
          </div>
          {askMode === "briefing" && !briefing && (
            <div className="mt-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
              briefing 问法需先在左侧构建 Briefing。
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
