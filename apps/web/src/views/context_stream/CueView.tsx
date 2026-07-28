import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Ear, Plug, Plus, RotateCcw, Trash2 } from "lucide-react";
import { useApp } from "@/lib/store";
import {
  CueSocket,
  cueStream,
  getCueFocuses,
  getCueKinds,
  listSources,
  type Cue,
  type CueDone,
  type CueReadyFrame,
  type CueServerFrame,
  type CueSocketStatus,
  type CueStatsFrame,
  type CueTurnInput,
  type CueDetailFrame,
} from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { GateLedger } from "@/components/GateLedger";
import { type CitationEntry } from "@/components/CitationList";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { IconButton } from "@/ui/IconButton";
import { Mono } from "@/ui/Mono";
import { NumberField } from "@/ui/NumberField";
import { SectionRule } from "@/ui/SectionRule";
import { Select } from "@/ui/Select";
import { SkeletonText } from "@/ui/Skeleton";
import { Slider } from "@/ui/Slider";
import { Switch } from "@/ui/Switch";
import { Tabs } from "@/ui/Tabs";
import { TextField } from "@/ui/TextField";
import { cn } from "@/ui/cn";
import { UsageLine } from "../_shared/UsageLine";
import { CueCard } from "./CueCard";

type Role = "owner" | "other" | "unknown";

const ROLE_OPTIONS = [
  { value: "owner", label: "本人" },
  { value: "other", label: "参与者" },
  { value: "unknown", label: "未知" },
];

let seed = 0;
const nextId = () => `${Date.now().toString(36)}-${(seed++).toString(36)}`;

/* ============================================================== 一次性 SSE panel */

interface SseTurn {
  id: string;
  speaker: string;
  text: string;
  role: Role;
}

function useSsePanel(currentUser: string | null) {
  const [turns, setTurns] = useState<SseTurn[]>([]);
  const [focus, setFocus] = useState<string | null>(null);
  const [minConf, setMinConf] = useState(1);
  const [maxCues, setMaxCues] = useState<number | null>(3);
  const [turnWindow, setTurnWindow] = useState<number | null>(3);
  /** 本地再过滤阈值：纯前端 software filter，不发任何请求。 */
  const [threshold, setThreshold] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cards, setCards] = useState<Cue[]>([]);
  const [done, setDone] = useState<CueDone | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // 卸载中断 SSE。
  useEffect(() => () => abortRef.current?.abort(), []);

  const addTurn = useCallback(() => {
    setTurns((ts) => [...ts, { id: nextId(), speaker: "", text: "", role: "unknown" }]);
  }, []);
  const removeTurn = useCallback((id: string) => {
    setTurns((ts) => ts.filter((t) => t.id !== id));
  }, []);
  const updateTurn = useCallback((id: string, patch: Partial<SseTurn>) => {
    setTurns((ts) => ts.map((t) => (t.id === id ? { ...t, ...patch } : t)));
  }, []);

  const visible = useMemo(
    () => cards.filter((c) => c.confidence >= threshold),
    [cards, threshold],
  );

  async function evaluate() {
    if (!currentUser || !focus || turns.length === 0) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(true);
    setError(null);
    setDone(null);
    await cueStream(
      currentUser,
      {
        turns: turns
          .filter((t) => t.text.trim() !== "")
          .map(({ speaker, text, role }) => ({
            speaker: speaker.trim() || role,
            text: text.trim(),
            role,
          })),
        focus,
        min_confidence: minConf,
        max_cues: maxCues ?? 3,
        turn_window: turnWindow ?? 3,
        // 去重回填：已下发的卡片以 {kind, title} 回传，避免重复提示。
        already_shown: cards.map((c) => ({ kind: c.kind, title: c.title })),
      },
      {
        onCue: (cue) => setCards((cs) => [...cs, cue]),
        onDone: (d) => setDone(d),
        onError: (m) => {
          if (!ac.signal.aborted) setError(m);
        },
      },
      ac.signal,
    );
    if (abortRef.current === ac) setBusy(false);
  }

  return {
    turns,
    addTurn,
    removeTurn,
    updateTurn,
    focus,
    setFocus,
    minConf,
    setMinConf,
    maxCues,
    setMaxCues,
    turnWindow,
    setTurnWindow,
    threshold,
    setThreshold,
    busy,
    error,
    cards,
    setCards,
    done,
    visible,
    evaluate,
  };
}

/* ============================================================== 长连接 WS panel */

interface WsCard {
  id: string;
  cue: Cue;
  seq: number;
}

function useWsPanel(currentUser: string | null) {
  const sockRef = useRef<CueSocket | null>(null);
  const [status, setStatus] = useState<CueSocketStatus>("closed");
  const [ready, setReady] = useState<CueReadyFrame | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [minConf, setMinConf] = useState(6);
  const [turnWindow, setTurnWindow] = useState<number | null>(3);
  const [quietPeriod, setQuietPeriod] = useState<number | null>(6);
  const [statsOn, setStatsOn] = useState(true);
  const [cards, setCards] = useState<WsCard[]>([]);
  const [sentTurns, setSentTurns] = useState<CueTurnInput[]>([]);
  const [statsLog, setStatsLog] = useState<CueStatsFrame[]>([]);
  const [error, setError] = useState<string | null>(null);
  // want_more 三件套都按「收到卡片的 id」归账，由送出的 ref 解析回来——
  // 绝不按 title 对（title 是去重键，说不出失败属于哪个请求）。
  const [details, setDetails] = useState<Record<string, CueDetailFrame>>({});
  const [pending, setPending] = useState<string[]>([]);
  const [failures, setFailures] = useState<Record<string, string>>({});
  // 在途 want_more 关联：ref → 卡片 id。用 ref 不用 state——帧处理器要同步读。
  const refToCard = useRef(new Map<string, string>());

  const [draftSpeaker, setDraftSpeaker] = useState("对方");
  const [draftText, setDraftText] = useState("");
  const [draftRole, setDraftRole] = useState<Role>("other");

  /** 把帧的 ref 解析回发起请求的卡片并退休该关联；ref 为空或已失效 → null。 */
  const takeRef = useCallback((ref: string | null | undefined): string | null => {
    if (!ref) return null;
    const card = refToCard.current.get(ref) ?? null;
    refToCard.current.delete(ref);
    return card;
  }, []);

  const onFrame = useCallback(
    (frame: CueServerFrame) => {
      switch (frame.type) {
        case "ready":
          setReady(frame);
          break;
        case "stats":
          // 每次评估都回一帧，包括零下发的——那正是需要门禁账解释的一帧。
          setStatsLog((l) => [frame, ...l].slice(0, 8));
          break;
        case "cue":
          setCards((cs) => {
            // 客户端是去重权威：已下发的 {kind,title} 不再收第二次。
            if (cs.some((c) => c.cue.kind === frame.cue.kind && c.cue.title === frame.cue.title))
              return cs;
            return [...cs, { id: nextId(), cue: frame.cue, seq: frame.seq }];
          });
          break;
        case "cue_detail": {
          const card = takeRef(frame.ref);
          if (card) {
            setDetails((d) => ({ ...d, [card]: frame }));
            setFailures((f) => {
              if (!(card in f)) return f;
              const { [card]: _gone, ...rest } = f;
              return rest;
            });
            setPending((p) => p.filter((x) => x !== card));
          }
          break;
        }
        case "error": {
          // 带 ref 的失败归属对应的 want_more；无 ref（坏帧/评估失败）不归属任何请求。
          const card = takeRef(frame.ref);
          if (card) {
            setFailures((f) => ({ ...f, [card]: frame.detail }));
            setPending((p) => p.filter((x) => x !== card));
          } else {
            setError(frame.detail);
          }
          break;
        }
        case "ping":
          break;
      }
    },
    [takeRef],
  );

  const policyMessage = useCallback(
    () => ({
      focus: focus ?? undefined,
      min_confidence: minConf,
      turn_window: turnWindow ?? undefined,
      quiet_period: quietPeriod ?? undefined,
      // 试验台显式开启 stats；context 客户端永远不会——静默连接必须真的静默。
      stats: statsOn,
    }),
    [focus, minConf, turnWindow, quietPeriod, statsOn],
  );

  /**
   * 打开连接。restore=true 时在首个 config 里回放窗口 + 已展示卡片——
   * 这是文档规定的重连路径：客户端是去重权威，服务端跨断线不记任何事。
   */
  const connect = useCallback(
    (restore: boolean) => {
      if (!currentUser) return;
      sockRef.current?.close();
      setReady(null);
      setError(null);
      // 关联不跨连接存活：旧 socket 上送出的 ref 永远不会再有应答。
      refToCard.current.clear();
      setPending([]);
      setStatsLog([]);
      const sock = new CueSocket(currentUser, onFrame, (s) => setStatus(s));
      sockRef.current = sock;
      const open = () => {
        if (!sock.ready) {
          window.setTimeout(open, 60);
          return;
        }
        sock.config({
          ...policyMessage(),
          ...(restore
            ? {
                turns: sentTurns,
                already_shown: cards.map((c) => ({ kind: c.cue.kind, title: c.cue.title })),
              }
            : {}),
        });
      };
      open();
    },
    [currentUser, onFrame, policyMessage, sentTurns, cards],
  );

  const disconnect = useCallback(() => {
    sockRef.current?.close();
    sockRef.current = null;
    setReady(null);
    refToCard.current.clear();
    setPending([]);
  }, []);

  // 卸载（或用户切换）时拆掉连接——绑着旧用户的监听器会继续对旧知识库评估。
  useEffect(() => {
    return () => {
      sockRef.current?.close();
      sockRef.current = null;
    };
  }, [currentUser]);

  // 旋钮在连接中可调：每次变更实时推 config，服务端回一帧新的 ready。
  const policyKey = JSON.stringify(policyMessage());
  useEffect(() => {
    if (status === "open") sockRef.current?.config(JSON.parse(policyKey));
  }, [policyKey, status]);

  function sendDraft() {
    const text = draftText.trim();
    const sock = sockRef.current;
    if (!sock?.ready || !text) return;
    const turn: CueTurnInput = {
      speaker: draftSpeaker.trim() || draftRole,
      text,
      role: draftRole,
    };
    sock.turn(turn);
    setSentTurns((ts) => [...ts, turn]);
    setDraftText("");
  }

  function flush() {
    sockRef.current?.flush();
  }

  function wantMore(item: WsCard) {
    const sock = sockRef.current;
    if (!sock?.ready) return;
    // 每个请求一个全新的 ref：失败重试是新的关联，迟到应答不会错挂。
    const ref = nextId();
    refToCard.current.set(ref, item.id);
    sock.wantMore(item.cue, ref);
    setFailures((f) => {
      if (!(item.id in f)) return f;
      const { [item.id]: _gone, ...rest } = f;
      return rest;
    });
    setPending((p) => (p.includes(item.id) ? p : [...p, item.id]));
  }

  return {
    status,
    ready,
    focus,
    setFocus,
    minConf,
    setMinConf,
    turnWindow,
    setTurnWindow,
    quietPeriod,
    setQuietPeriod,
    statsOn,
    setStatsOn,
    cards,
    sentTurns,
    statsLog,
    error,
    setError,
    details,
    pending,
    failures,
    draftSpeaker,
    setDraftSpeaker,
    draftText,
    setDraftText,
    draftRole,
    setDraftRole,
    connect,
    disconnect,
    sendDraft,
    flush,
    wantMore,
  };
}

/* ====================================================================== view */

/**
 * context_stream 提示：双链路面板。
 * SSE 一次性：整段转录窗口一次性评估；WS 长连接：服务端持窗口 + 静默期 +
 * 单在途合并，want_more 展开 cue_detail。两链路的状态都挂在 CueView 顶层的
 * hook 上——Tabs 切换会卸载未激活面板，状态必须比面板活得久。
 */
export default function CueView() {
  const currentUser = useApp((s) => s.currentUser);
  const focusSource = useApp((s) => s.focusSource);
  const [tab, setTab] = useState("sse");
  const [focuses, setFocuses] = useState<{ key: string; label: string; summary: string }[]>([]);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [vocabError, setVocabError] = useState<string | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});

  const sse = useSsePanel(currentUser);
  const ws = useWsPanel(currentUser);

  // focus / kind 词表由服务端供给（封闭词汇，不在前端私抄一份）。
  useEffect(() => {
    let alive = true;
    Promise.all([getCueFocuses(), getCueKinds()])
      .then(([f, k]) => {
        if (!alive) return;
        setFocuses(f);
        setKindLabels(Object.fromEntries(k.map((x) => [x.key, x.label])));
        // 默认值永远取服务端词表的第一项，不硬编码。
        if (f.length > 0) {
          sse.setFocus((cur) => cur ?? f[0].key);
          ws.setFocus((cur) => cur ?? f[0].key);
        }
      })
      .catch((e) => alive && setVocabError((e as Error).message));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!currentUser) return;
    let alive = true;
    listSources(currentUser)
      .then((rows) => {
        if (alive) setTitles(Object.fromEntries(rows.map((r) => [r.source_id, r.title])));
      })
      .catch(() => alive && setTitles({}));
    return () => {
      alive = false;
    };
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
        <PageHeader title="提示 Cue" description="context_stream 主动提示，双链路。" />
        <EmptyState
          icon={Ear}
          title="未选择用户"
          description="在右上角选择一个 user_id。提词卡只能引用该用户知识库里的真实来源——没有来源的卡片会被引用闸门丢掉。"
        />
      </>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="提示 Cue"
        description="context_stream 主动提示：同一段转录，可对比一次性 SSE 与长连接 WS 两条链路。被门禁吃掉的内容只在门禁账里留下计数。"
      />
      {vocabError && <Callout tone="warn">focus 词表拉取失败：{vocabError}</Callout>}
      <Tabs
        aria-label="cue 链路"
        value={tab}
        onChange={setTab}
        tabs={[
          {
            value: "sse",
            label: "一次性 SSE",
            panel: (
              <SsePanel
                panel={sse}
                focuses={focuses}
                kindLabels={kindLabels}
                titles={titles}
                onJump={jumpToCitation}
              />
            ),
          },
          {
            value: "ws",
            label: "长连接 WS",
            panel: (
              <WsPanel
                panel={ws}
                focuses={focuses}
                kindLabels={kindLabels}
                titles={titles}
                onJump={jumpToCitation}
              />
            ),
          },
        ]}
      />
    </div>
  );
}

/* ---------------------------------------------------------------- SSE 面板 */

function SsePanel({
  panel,
  focuses,
  kindLabels,
  titles,
  onJump,
}: {
  panel: ReturnType<typeof useSsePanel>;
  focuses: { key: string; label: string; summary: string }[];
  kindLabels: Record<string, string>;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const hidden = panel.cards.length - panel.visible.length;
  return (
    <div className="flex flex-col gap-8">
      {/* 转录窗口 */}
      <section>
        <SectionRule
          no={1}
          title="转录窗口"
          actions={
            <Button size="sm" onClick={panel.addTurn}>
              <Plus size={13} aria-hidden /> 追加一轮
            </Button>
          }
        />
        {panel.turns.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">
            逐轮录入对话，整段窗口一次性送入评估——focus 只改变注意力指向，不做说话人过滤。
          </p>
        ) : (
          <ol className="mt-3 flex flex-col gap-2">
            {panel.turns.map((t) => (
              <li key={t.id} className="flex flex-wrap items-start gap-2">
                <TextField
                  wrapperClassName="w-28"
                  value={t.speaker}
                  onChange={(e) => panel.updateTurn(t.id, { speaker: e.target.value })}
                  placeholder="说话人"
                  aria-label="说话人"
                />
                <Select
                  wrapperClassName="w-28"
                  value={t.role}
                  onChange={(v) => panel.updateTurn(t.id, { role: v as Role })}
                  options={ROLE_OPTIONS}
                  aria-label="角色"
                />
                <TextField
                  wrapperClassName="min-w-40 flex-1"
                  value={t.text}
                  onChange={(e) => panel.updateTurn(t.id, { text: e.target.value })}
                  placeholder="这一轮说了什么…"
                  aria-label="转录文本"
                />
                <IconButton
                  aria-label="删除该轮"
                  size="md"
                  onClick={() => panel.removeTurn(t.id)}
                >
                  <Trash2 size={14} aria-hidden />
                </IconButton>
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* 评估参数 */}
      <section>
        <SectionRule no={2} title="评估参数" />
        <div className="mt-4 flex max-w-measure flex-col gap-4">
          <Select
            label="focus（注意力指向）"
            value={panel.focus}
            onChange={panel.setFocus}
            options={focuses.map((f) => ({ value: f.key, label: `${f.label}（${f.key}）` }))}
            placeholder="载入词表…"
            disabled={focuses.length === 0}
            hint={focuses.find((f) => f.key === panel.focus)?.summary}
          />
          <Slider
            label="min_confidence（服务端闸门）"
            value={panel.minConf}
            onChange={panel.setMinConf}
            min={1}
            max={10}
            hint="低于该置信度的卡片不会下发，计入 dropped.low_confidence。"
          />
          <div className="flex flex-wrap gap-4">
            <NumberField
              label="max_cues"
              value={panel.maxCues}
              onChange={panel.setMaxCues}
              min={1}
              max={5}
            />
            <NumberField
              label="turn_window"
              value={panel.turnWindow}
              onChange={panel.setTurnWindow}
              min={1}
              max={12}
            />
          </div>
          <div>
            <Button
              variant="primary"
              loading={panel.busy}
              disabled={panel.turns.length === 0 || !panel.focus}
              onClick={() => void panel.evaluate()}
            >
              送整段评估一次
            </Button>
          </div>
        </div>
      </section>

      {/* 结果 */}
      {panel.error ? (
        <ErrorState title="评估失败" error={panel.error} onRetry={() => void panel.evaluate()} />
      ) : (
        <section>
          <SectionRule
            no={3}
            title={`存活卡片（${panel.visible.length} / 已下发 ${panel.cards.length}）`}
            actions={
              panel.cards.length > 0 ? (
                <Button size="sm" variant="ghost" onClick={() => panel.setCards([])}>
                  清空卡片
                </Button>
              ) : undefined
            }
          />
          {panel.cards.length === 0 && !panel.busy && !panel.done ? (
            <div className="mt-4">
              <EmptyState
                icon={Ear}
                title="还没有提词卡"
                description="沉默是这个功能的稳态：解析失败 / 无引用 / 低置信 / 超限，任一道闸门都会让一次评估一张卡都不出——门禁账会说明卡在哪一道。"
              />
            </div>
          ) : (
            <>
              <div className="mt-4 max-w-measure">
                <Slider
                  label="本地再过滤阈值（software filter）"
                  value={panel.threshold}
                  onChange={panel.setThreshold}
                  min={1}
                  max={10}
                  hint="纯前端过滤：confidence ≥ 阈值的已下发卡片保留，不发任何请求。"
                />
                {hidden > 0 && (
                  <p className="mt-1 text-12 text-ink-3">
                    本地阈值挡下 {hidden} 张（未重新请求）。
                  </p>
                )}
              </div>
              {panel.busy && <p className="mt-3 text-12 text-ink-3">评估中，卡片逐一到达…</p>}
              {panel.busy && panel.cards.length === 0 && (
                <SkeletonText lines={3} className="mt-3 max-w-measure" />
              )}
              <div className="border-t border-line">
                {panel.visible.map((cue, i) => (
                  <CueCard
                    key={`${cue.kind}:${cue.title}:${i}`}
                    cue={cue}
                    kindLabel={kindLabels[cue.kind]}
                    via="sse"
                    titles={titles}
                    onJump={onJump}
                  />
                ))}
              </div>
            </>
          )}
        </section>
      )}

      {/* 门禁账 */}
      {panel.done && (
        <section>
          <SectionRule no={4} title="门禁账" />
          <GateLedger className="mt-4 max-w-measure" dropped={panel.done.dropped} />
          <p className="mt-2 text-12 text-ink-3">
            下发 {panel.done.count} 张 · focus <Mono>{panel.done.focus}</Mono> · as_of{" "}
            <Mono>{panel.done.as_of}</Mono>
          </p>
          <UsageLine usage={panel.done.token_usage} className="mt-1" />
        </section>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- WS 面板 */

function WsPanel({
  panel,
  focuses,
  kindLabels,
  titles,
  onJump,
}: {
  panel: ReturnType<typeof useWsPanel>;
  focuses: { key: string; label: string; summary: string }[];
  kindLabels: Record<string, string>;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const open = panel.status === "open";
  return (
    <div className="flex flex-col gap-8">
      {/* 连接 */}
      <section>
        <SectionRule
          no={1}
          title="连接"
          actions={
            open ? (
              <>
                <Button size="sm" onClick={panel.disconnect}>
                  断开
                </Button>
                <Button
                  size="sm"
                  title="断开后重连，并在 config 里回放窗口与已展示卡片（客户端是去重权威）"
                  onClick={() => panel.connect(true)}
                >
                  <RotateCcw size={13} aria-hidden /> 重连（回放）
                </Button>
              </>
            ) : (
              <Button size="sm" variant="primary" onClick={() => panel.connect(false)}>
                <Plug size={13} aria-hidden /> 连接
              </Button>
            )
          }
        />
        <p className="mt-3 flex items-center gap-2 text-13 text-ink-2">
          <span
            aria-hidden
            className={cn(
              "inline-block size-2 rounded-full",
              open ? "bg-ok" : panel.status === "connecting" ? "bg-accent" : "bg-ink-3",
            )}
          />
          {open ? "已连接" : panel.status === "connecting" ? "连接中…" : "已断开"}
        </p>
        {panel.status === "closed" && (
          <Callout tone="notice" className="mt-3 max-w-measure">
            连接已断开。客户端是去重权威：重连时在 config 里回放已推送的 turns 与已下发卡片
            already_shown，服务端跨断线不记任何事。
          </Callout>
        )}
        {panel.ready && (
          <DefinitionList
            className="mt-3 max-w-measure"
            items={[
              { term: "focus", definition: <Mono>{panel.ready.focus}</Mono> },
              { term: "min_confidence", definition: <Mono>{panel.ready.min_confidence}</Mono> },
              { term: "max_cues", definition: <Mono>{panel.ready.max_cues}</Mono> },
              { term: "turn_window", definition: <Mono>{panel.ready.turn_window}</Mono> },
              { term: "quiet_period", definition: <Mono>{panel.ready.quiet_period}s</Mono> },
              {
                term: "briefing_id",
                definition: <Mono>{panel.ready.briefing_id ?? "—"}</Mono>,
              },
              { term: "stats", definition: <Mono>{panel.ready.stats ? "on" : "off"}</Mono> },
            ]}
          />
        )}
      </section>

      {/* config */}
      <section>
        <SectionRule no={2} title="生效策略（config）" />
        <div className="mt-4 flex max-w-measure flex-col gap-4">
          <Select
            label="focus（注意力指向）"
            value={panel.focus}
            onChange={panel.setFocus}
            options={focuses.map((f) => ({ value: f.key, label: `${f.label}（${f.key}）` }))}
            placeholder="载入词表…"
            disabled={focuses.length === 0}
            hint={focuses.find((f) => f.key === panel.focus)?.summary}
          />
          <Slider
            label="min_confidence"
            value={panel.minConf}
            onChange={panel.setMinConf}
            min={1}
            max={10}
          />
          <div className="flex flex-wrap gap-4">
            <NumberField
              label="turn_window"
              value={panel.turnWindow}
              onChange={panel.setTurnWindow}
              min={1}
              max={12}
            />
            <NumberField
              label="quiet_period（秒）"
              value={panel.quietPeriod}
              onChange={panel.setQuietPeriod}
              min={0}
              max={60}
            />
          </div>
          <Switch
            checked={panel.statsOn}
            onCheckedChange={panel.setStatsOn}
            label="stats 帧"
            hint="开启后每次评估都回一帧门禁账，包括一张卡都没下发的评估。"
          />
          <p className="text-12 text-ink-3">连接打开时，改动实时推送 config。</p>
        </div>
      </section>

      {/* turn 追加 + flush */}
      <section>
        <SectionRule
          no={3}
          title="转录追加"
          actions={
            <Button size="sm" disabled={!open} title="立即评估，跳过静默期" onClick={panel.flush}>
              立即评估（flush）
            </Button>
          }
        />
        <div className="mt-3 flex flex-wrap items-start gap-2">
          <TextField
            wrapperClassName="w-28"
            value={panel.draftSpeaker}
            onChange={(e) => panel.setDraftSpeaker(e.target.value)}
            placeholder="说话人"
            aria-label="说话人"
          />
          <Select
            wrapperClassName="w-28"
            value={panel.draftRole}
            onChange={(v) => panel.setDraftRole(v as Role)}
            options={ROLE_OPTIONS}
            aria-label="角色"
          />
          <TextField
            wrapperClassName="min-w-40 flex-1"
            value={panel.draftText}
            onChange={(e) => panel.setDraftText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") panel.sendDraft();
            }}
            placeholder="这一轮说了什么…"
            aria-label="转录文本"
          />
          <Button disabled={!open || !panel.draftText.trim()} onClick={panel.sendDraft}>
            发送
          </Button>
        </div>
        <p className="mt-2 text-12 text-ink-3">已推送 {panel.sentTurns.length} 轮。</p>
      </section>

      {panel.error && (
        <Callout tone="danger" onDismiss={() => panel.setError(null)}>
          {panel.error}
        </Callout>
      )}

      {/* 提词卡 */}
      <section>
        <SectionRule no={4} title={`提词卡（${panel.cards.length}）`} />
        {panel.cards.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              icon={Ear}
              title="还没有提词卡"
              description="长连接的稳态是静默：服务端持窗口 + 静默期 + 单在途合并，评估没东西可提示时一帧都不发。开启 stats 后可在下方看到每次评估的门禁账。"
            />
          </div>
        ) : (
          <div className="border-t border-line">
            {panel.cards.map((item) => (
              <CueCard
                key={item.id}
                cue={item.cue}
                kindLabel={kindLabels[item.cue.kind]}
                via={`ws · seq ${item.seq}`}
                titles={titles}
                onJump={onJump}
                canExpand={open}
                pending={panel.pending.includes(item.id)}
                failure={panel.failures[item.id]}
                detail={panel.details[item.id]}
                onWantMore={() => panel.wantMore(item)}
              />
            ))}
          </div>
        )}
      </section>

      {/* stats 历史 */}
      <section>
        <SectionRule no={5} title="评估账（stats 历史）" />
        {panel.statsLog.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">
            还没有评估帧。stats 开启后每次评估都会回一帧——包括零下发的那些。
          </p>
        ) : (
          <div className="mt-4 flex flex-col gap-6">
            {panel.statsLog.map((s) => (
              <div key={s.seq}>
                <p className="mb-2 text-12 text-ink-3">
                  <Mono>seq {s.seq}</Mono> · 下发 {s.delivered} 张 · focus <Mono>{s.focus}</Mono>
                </p>
                <GateLedger className="max-w-measure" dropped={s.dropped} />
                <UsageLine usage={s.token_usage} className="mt-1" />
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
