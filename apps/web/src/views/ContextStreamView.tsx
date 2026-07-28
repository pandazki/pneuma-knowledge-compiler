/**
 * AI Cue bench — context_stream 主动提词的手动试验台.
 *
 * This page exists so the project owner can CLICK the feature and judge it, not to be a
 * lens UI. Three things it is built around, in priority order:
 *
 * 1. **Both transports, switchable.** Shape A (one-shot SSE over a posted window) and
 *    shape B (the long-lived socket with the server-side sliding window / quiet period /
 *    single-in-flight coalescing) behave very differently, and comparing them is the
 *    point of the page.
 * 2. **The sensitivity dial filters IN SOFTWARE.** Each cue carries its own `confidence`,
 *    so moving the slider re-filters cards already on screen with zero requests. The page
 *    makes that visible (it counts what the local threshold is hiding) instead of leaving
 *    it as an implementation note nobody can see.
 * 3. **Why did this card fire.** Every card shows its `trigger`, and selecting a card
 *    highlights that fragment inside the transcript.
 *
 * The focus vocabulary is fetched from `GET /v1/cue/focuses`; a private copy in the
 * frontend would be a third place for a closed vocabulary to drift (architecture.md).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ChevronDown,
  Ear,
  Link2,
  Loader2,
  Plug,
  PlugZap,
  Plus,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
  Zap,
} from "lucide-react";
import { useApp } from "@/lib/store";
import { Button, Chip, EmptyState, Eyebrow, SegmentedControl, type Segment } from "@/components/ui";
import { CitationChip } from "@/components/ClaimView";
import { UsageBar } from "./RecallView";
import { CUE_PRESETS, type CuePreset } from "@/lib/cuePresets";
import type { Citation } from "@/lib/types";
import { cn } from "@/lib/cn";
import * as api from "@/lib/api";

/* ------------------------------------------------------------------------ helpers */

type Transport = "sse" | "ws";
type Scope = "full" | "briefing";
type Role = "owner" | "other";

interface Turn {
  id: string;
  speaker: string;
  text: string;
  role: Role;
  /** WS only: has this turn been pushed to the open socket yet. */
  sent?: boolean;
}

/** One card as received, plus where/when it arrived. Kept even when the local threshold
 * hides it — re-filtering must not need a re-request, which means never discarding. */
interface Received {
  id: string;
  cue: api.Cue;
  via: Transport;
  seq: number | null;
  at: number;
}

interface LogLine {
  id: string;
  at: number;
  text: string;
  tone: "info" | "warn" | "good";
}

let seed = 0;
const nextId = () => `${Date.now().toString(36)}-${(seed++).toString(36)}`;

const ROLE_LABEL: Record<Role, string> = { owner: "本人", other: "参与者" };

const DROP_LABEL: Record<string, string> = {
  unparsed: "解析失败",
  repeat: "本轮重复",
  uncited: "无有效引用",
  low_confidence: "信心不足",
  capped: "超出 max_cues",
};

/**
 * Locate `needle` inside `text`. Exact first; then whitespace-insensitively, because a
 * `trigger` is the model quoting the transcript back and quotes drift on whitespace far
 * more often than on characters. Returns null rather than guessing at a fuzzy match — a
 * wrong highlight is worse than none on a page whose job is explaining why a card fired.
 */
function findSpan(text: string, needle: string): [number, number] | null {
  const t = needle.trim();
  if (!t) return null;
  const exact = text.indexOf(t);
  if (exact !== -1) return [exact, exact + t.length];

  const map: number[] = [];
  let norm = "";
  for (let i = 0; i < text.length; i++) {
    if (/\s/.test(text[i])) continue;
    map.push(i);
    norm += text[i];
  }
  const flat = t.replace(/\s+/g, "");
  if (!flat) return null;
  const j = norm.indexOf(flat);
  if (j === -1) return null;
  return [map[j], map[j + flat.length - 1] + 1];
}

/** Render `text` with `trigger` marked, or plain when it is not in this turn. */
function Highlighted({ text, trigger }: { text: string; trigger: string | null }) {
  const span = trigger ? findSpan(text, trigger) : null;
  if (!span) return <>{text}</>;
  return (
    <>
      {text.slice(0, span[0])}
      <mark
        className="rounded-[2px] px-0.5"
        style={{ background: "var(--color-accent)", color: "var(--color-accent-foreground, #fff)" }}
      >
        {text.slice(span[0], span[1])}
      </mark>
      {text.slice(span[1])}
    </>
  );
}

const citeKey = (c: api.CueCitation) => `${c.source_id}:${c.block_start}:${c.block_end}`;

/* -------------------------------------------------------------------------- view */

export function ContextStreamView() {
  const { currentUser } = useApp();

  // --- server vocabularies (never inlined) ---
  const [focuses, setFocuses] = useState<api.CueFocusOption[]>([]);
  const [kinds, setKinds] = useState<api.CueKindOption[]>([]);
  const [vocabError, setVocabError] = useState<string | null>(null);

  // --- transcript ---
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [draftRole, setDraftRole] = useState<Role>("other");
  const [draftSpeaker, setDraftSpeaker] = useState("对方");

  // --- policy ---
  const [transport, setTransport] = useState<Transport>("sse");
  const [focus, setFocus] = useState("general");
  const [sensitivity, setSensitivity] = useState(6);
  // When false the server gate is pinned open (min_confidence 1) and ALL scored cards come
  // down, so the slider's client-side re-filter is the only thing acting — which is the
  // behaviour this page exists to show. When true the slider is also sent as the server
  // gate, and `dropped.low_confidence` starts counting instead.
  const [gateOnServer, setGateOnServer] = useState(false);
  const [maxCues, setMaxCues] = useState(3);
  const [turnWindow, setTurnWindow] = useState(3);
  const [quietPeriod, setQuietPeriod] = useState(6);
  const [scope, setScope] = useState<Scope>("full");
  const [briefings, setBriefings] = useState<api.BriefingSummary[]>([]);
  const [briefingId, setBriefingId] = useState("");
  const [sendShown, setSendShown] = useState(true);

  // --- results ---
  const [received, setReceived] = useState<Received[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [snippets, setSnippets] = useState<Record<string, string>>({});
  const [lastDone, setLastDone] = useState<api.CueDone | null>(null);
  // All three keyed by the RECEIVED CARD's id, resolved from the `ref` we minted for that
  // expansion request — never by title, which only works by coincidence (title is also
  // the dedup key) and says nothing about which request an error belongs to.
  const [details, setDetails] = useState<Record<string, api.CueDetailFrame>>({});
  const [detailPending, setDetailPending] = useState<string[]>([]);
  const [detailErrors, setDetailErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // In-flight `want_more` correlation: ref → card id. A plain ref, not state, because
  // nothing renders from it and the frame handler has to read it synchronously.
  const refToCard = useRef<Map<string, string>>(new Map());

  // --- socket ---
  const sockRef = useRef<api.CueSocket | null>(null);
  const [wsStatus, setWsStatus] = useState<api.CueSocketStatus>("closed");
  const [ready, setReady] = useState<api.CueReadyFrame | null>(null);
  const [lastStats, setLastStats] = useState<api.CueStatsFrame | null>(null);
  const [log, setLog] = useState<LogLine[]>([]);

  const pushLog = useCallback((text: string, tone: LogLine["tone"] = "info") => {
    setLog((l) => [{ id: nextId(), at: Date.now(), text, tone }, ...l].slice(0, 60));
  }, []);

  /* ------------------------------------------------------------------ load vocab */

  useEffect(() => {
    let alive = true;
    Promise.all([api.getCueFocuses(), api.getCueKinds()])
      .then(([f, k]) => {
        if (!alive) return;
        setFocuses(f);
        setKinds(k);
        // Never default to a value the server did not offer.
        if (f.length && !f.some((o) => o.key === focus)) setFocus(f[0].key);
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
    api
      .listBriefings(currentUser)
      .then((b) => alive && setBriefings(b))
      .catch(() => alive && setBriefings([]));
    return () => {
      alive = false;
    };
  }, [currentUser]);

  /* ----------------------------------------------------------- citation snippets */

  // The wire citation is `{source_id, block_start, block_end}` with no text, so the
  // snippet the shared CitationChip shows has to be fetched. One request per distinct
  // span, cached for the life of the view.
  const hydrate = useCallback(
    (cue: api.Cue) => {
      if (!currentUser) return;
      for (const c of cue.citations) {
        const key = citeKey(c);
        setSnippets((prev) => {
          if (key in prev) return prev;
          void api
            .fetchLocator(currentUser, c.source_id, { blocks: [c.block_start, c.block_end] })
            .then((r) => setSnippets((p) => ({ ...p, [key]: r.text })))
            .catch(() => setSnippets((p) => ({ ...p, [key]: "（原文取用失败）" })));
          return { ...prev, [key]: "" };
        });
      }
    },
    [currentUser],
  );

  const toCitation = useCallback(
    (c: api.CueCitation): Citation => {
      const text = snippets[citeKey(c)];
      return {
        source_id: c.source_id,
        from: c.block_start,
        to: c.block_end,
        snippet: text || "（原文载入中…）",
        redaction_state: "included",
      };
    },
    [snippets],
  );

  /* --------------------------------------------------------------- derived state */

  // THE point of the sensitivity dial: cards already in hand are re-filtered locally.
  const visible = useMemo(
    () => received.filter((r) => r.cue.confidence >= sensitivity),
    [received, sensitivity],
  );
  const hiddenLocally = received.length - visible.length;

  const activeCue = useMemo(
    () => received.find((r) => r.id === activeId) ?? null,
    [received, activeId],
  );
  const activeTrigger = activeCue?.cue.trigger ?? null;
  const triggerLocated = useMemo(() => {
    if (!activeTrigger) return true;
    return turns.some((t) => findSpan(t.text, activeTrigger) !== null);
  }, [turns, activeTrigger]);

  const alreadyShown = useMemo<api.CueShown[]>(
    () => received.map((r) => ({ kind: r.cue.kind, title: r.cue.title })),
    [received],
  );

  const wireTurns = useCallback(
    (): api.CueTurnInput[] =>
      turns.map((t) => ({ speaker: t.speaker, text: t.text, role: t.role })),
    [turns],
  );

  // What the server gate is actually set to, given the pinned-open switch.
  const serverMinConfidence = gateOnServer ? sensitivity : 1;
  const effectiveBriefing = scope === "briefing" ? briefingId : "";

  /* --------------------------------------------------------------- transcript ops */

  function loadPreset(p: CuePreset) {
    setTurns(p.turns.map((t) => ({ ...t, id: nextId() })));
    setActiveId(null);
  }

  function addTurn() {
    const text = draft.trim();
    if (!text) return;
    setTurns((ts) => [
      ...ts,
      { id: nextId(), speaker: draftSpeaker.trim() || ROLE_LABEL[draftRole], text, role: draftRole },
    ]);
    setDraft("");
  }

  function clearAll() {
    setTurns([]);
    setReceived([]);
    setActiveId(null);
    setLastDone(null);
    setDetails({});
    setDetailErrors({});
    setError(null);
  }

  /* ---------------------------------------------------------------- shape A: SSE */

  async function runOnce() {
    if (!currentUser || turns.length === 0) return;
    setBusy(true);
    setError(null);
    setLastDone(null);
    await api.cueStream(
      currentUser,
      {
        turns: wireTurns(),
        focus,
        min_confidence: serverMinConfidence,
        max_cues: maxCues,
        turn_window: turnWindow,
        briefing_id: effectiveBriefing || null,
        already_shown: sendShown ? alreadyShown : [],
      },
      {
        onCue: (cue) => {
          hydrate(cue);
          setReceived((r) => [...r, { id: nextId(), cue, via: "sse", seq: null, at: Date.now() }]);
        },
        onDone: (done) => setLastDone(done),
        onError: (m) => setError(m),
      },
    );
    setBusy(false);
  }

  /* ----------------------------------------------------------------- shape B: WS */

  const policyMessage = useCallback(
    (): api.CueConfigMessage => ({
      focus,
      min_confidence: serverMinConfidence,
      max_cues: maxCues,
      turn_window: turnWindow,
      quiet_period: quietPeriod,
      // "" is how briefing scope is turned back OFF; null would mean "unchanged".
      briefing_id: effectiveBriefing,
      // A bench page opts in; the context clients never would. Off by default on the server so a
      // quiet connection stays actually quiet — here the whole point is watching the
      // evaluations that delivered nothing.
      stats: true,
    }),
    [focus, serverMinConfidence, maxCues, turnWindow, quietPeriod, effectiveBriefing],
  );

  /** Resolve a frame's `ref` to the card that asked, retiring the correlation. Null for a
   * ref-less frame, and for a ref we no longer know about (a reply that outlived its
   * card) — neither may be pinned on some other card. */
  const takeRef = useCallback((ref: string | null | undefined): string | null => {
    if (!ref) return null;
    const card = refToCard.current.get(ref) ?? null;
    refToCard.current.delete(ref);
    return card;
  }, []);

  const onFrame = useCallback(
    (frame: api.CueServerFrame) => {
      switch (frame.type) {
        case "ready":
          setReady(frame);
          pushLog(
            `ready · focus=${frame.focus} min_conf=${frame.min_confidence} window=${frame.turn_window} quiet=${frame.quiet_period}s briefing=${frame.briefing_id ?? "—"} stats=${frame.stats ? "on" : "off"}`,
            "good",
          );
          break;
        case "stats":
          // Fires on EVERY evaluation, including the ones that delivered nothing — which
          // is the case worth watching, since silence is this feature's steady state.
          setLastStats(frame);
          pushLog(
            `stats · seq=${frame.seq} 下发 ${frame.delivered} · ${
              Object.entries(frame.dropped)
                .filter(([, n]) => n)
                .map(([k, n]) => `${DROP_LABEL[k] ?? k} ${n}`)
                .join(" ") || "无丢弃"
            }`,
          );
          break;
        case "cue":
          hydrate(frame.cue);
          setReceived((r) => [
            ...r,
            { id: nextId(), cue: frame.cue, via: "ws", seq: frame.seq, at: Date.now() },
          ]);
          pushLog(`cue · seq=${frame.seq} · ${frame.cue.title}（信心 ${frame.cue.confidence}）`);
          break;
        case "cue_detail": {
          const card = takeRef(frame.ref);
          if (card) {
            setDetails((d) => ({ ...d, [card]: frame }));
            setDetailErrors((e) => {
              if (!(card in e)) return e;
              const { [card]: _gone, ...rest } = e;
              return rest;
            });
            setDetailPending((p) => p.filter((x) => x !== card));
          }
          pushLog(`cue_detail · ref=${frame.ref ?? "—"} · ${frame.title}`, "good");
          break;
        }
        case "error": {
          // `ref` says which `want_more` failed, so a failure retires exactly its own
          // pending expansion. A ref-less error (bad frame, failed evaluation) belongs to
          // no request: surface it at the top, and leave every in-flight expansion alone.
          const card = takeRef(frame.ref);
          if (card) {
            setDetailErrors((e) => ({ ...e, [card]: frame.detail }));
            setDetailPending((p) => p.filter((x) => x !== card));
          } else {
            setError(frame.detail);
          }
          pushLog(`error${frame.ref ? ` · ref=${frame.ref}` : ""} · ${frame.detail}`, "warn");
          break;
        }
        case "ping":
          pushLog("ping（服务端保活）");
          break;
      }
    },
    [hydrate, pushLog, takeRef],
  );

  /** Open the socket. `restore` replays the window + already-shown list in the first
   * `config`, which is the documented reconnect path: the CLIENT is the dedup authority
   * and the server keeps no memory across a dropped connection. */
  const connect = useCallback(
    (restore: boolean) => {
      if (!currentUser) return;
      sockRef.current?.close();
      setReady(null);
      // Correlations do not survive the connection: nothing will ever answer a `ref` sent
      // on a socket that is gone, and a pending card would keep its button disabled.
      refToCard.current.clear();
      setDetailPending([]);
      setLastStats(null);
      const sock = new api.CueSocket(currentUser, onFrame, (status, detail) => {
        setWsStatus(status);
        if (detail) pushLog(`socket ${status} · ${detail}`, status === "closed" ? "warn" : "info");
      });
      sockRef.current = sock;
      const open = () => {
        if (!sock.ready) {
          window.setTimeout(open, 60);
          return;
        }
        sock.config({
          ...policyMessage(),
          ...(restore
            ? { turns: wireTurns(), already_shown: sendShown ? alreadyShown : [] }
            : {}),
        });
        if (restore) {
          setTurns((ts) => ts.map((t) => ({ ...t, sent: true })));
          pushLog(`重连恢复 · 回放 ${turns.length} 轮 + ${alreadyShown.length} 张已展示卡片`);
        } else {
          setTurns((ts) => ts.map((t) => ({ ...t, sent: false })));
        }
      };
      open();
    },
    [currentUser, onFrame, policyMessage, pushLog, wireTurns, sendShown, alreadyShown, turns.length],
  );

  function disconnect() {
    sockRef.current?.close();
    sockRef.current = null;
    setReady(null);
    refToCard.current.clear();
    setDetailPending([]);
  }

  // Tear the socket down when the view unmounts or the user changes — a live listener
  // bound to a user that is no longer selected would keep evaluating against their KB.
  useEffect(() => {
    return () => {
      sockRef.current?.close();
      sockRef.current = null;
    };
  }, [currentUser]);

  // Live policy push: every knob on this page is adjustable mid-connection, and the
  // server echoes the effective policy back as a fresh `ready`.
  const policyKey = JSON.stringify(policyMessage());
  useEffect(() => {
    if (wsStatus === "open") sockRef.current?.config(JSON.parse(policyKey));
  }, [policyKey, wsStatus]);

  function pushTurn(t: Turn) {
    const sock = sockRef.current;
    if (!sock?.ready) {
      pushLog("socket 未连接，无法推送轮次", "warn");
      return;
    }
    sock.turn({ speaker: t.speaker, text: t.text, role: t.role });
    setTurns((ts) => ts.map((x) => (x.id === t.id ? { ...x, sent: true } : x)));
    pushLog(`turn → ${t.speaker}：${t.text.slice(0, 24)}…`);
  }

  function pushRemaining() {
    for (const t of turns) if (!t.sent) pushTurn(t);
  }

  function wantMore(r: Received) {
    const sock = sockRef.current;
    if (!sock?.ready) {
      pushLog("want_more 只能走 WebSocket —— 请先连接", "warn");
      return;
    }
    // One fresh ref per request, so a retry after a failure is its own correlation and a
    // late reply to the abandoned attempt lands on nothing rather than on this one.
    const ref = nextId();
    refToCard.current.set(ref, r.id);
    sock.wantMore(r.cue, ref);
    setDetailErrors((e) => {
      if (!(r.id in e)) return e;
      const { [r.id]: _gone, ...rest } = e;
      return rest;
    });
    setDetailPending((p) => (p.includes(r.id) ? p : [...p, r.id]));
    pushLog(`want_more → ${r.cue.title}（ref=${ref}）`);
  }

  /* --------------------------------------------------------------------- render */

  if (!currentUser) {
    return (
      <EmptyState
        icon={<Ear size={28} />}
        title="未选择用户"
        hint="在右上角选择一个 user_id。提词卡只能引用该用户知识库里的真实来源——没有来源的卡片会被引用闸门丢掉。"
      />
    );
  }

  const transportSegments: Segment<Transport>[] = [
    { value: "sse", label: <><Zap size={13} /> HTTP 一次性 SSE</> },
    { value: "ws", label: <><Plug size={13} /> WebSocket 长连接</> },
  ];

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* ------------------------------------------------------------ control strip */}
      <div className="border-b border-border bg-card px-5 py-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Eyebrow>ContextStream · AI Cue 提词台</Eyebrow>
          <SegmentedControl
            segments={transportSegments}
            value={transport}
            onChange={(v) => setTransport(v)}
            className="w-max min-w-max [&>button]:flex-none [&>button]:px-3"
          />
          {transport === "ws" && (
            <div className="flex items-center gap-1.5">
              <Chip
                dotColor={
                  wsStatus === "open"
                    ? "var(--color-verified)"
                    : wsStatus === "connecting"
                      ? "var(--color-accent)"
                      : "var(--color-border-strong)"
                }
              >
                {wsStatus === "open" ? "已连接" : wsStatus === "connecting" ? "连接中" : "未连接"}
              </Chip>
              {wsStatus === "open" ? (
                <>
                  <Button size="sm" variant="outline" onClick={disconnect}>
                    断开
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    title="断开后重连，并在 config 里回放窗口与已展示卡片（客户端才是去重权威）"
                    onClick={() => connect(true)}
                  >
                    <RotateCcw size={13} /> 重连恢复
                  </Button>
                </>
              ) : (
                <Button size="sm" variant="primary" onClick={() => connect(false)}>
                  <PlugZap size={13} /> 连接
                </Button>
              )}
            </div>
          )}
        </div>

        <div className="mt-3 flex flex-wrap items-end gap-x-5 gap-y-3">
          {/* focus — rendered from GET /v1/cue/focuses */}
          <Field label="focus（注意力指向）">
            <div className="relative">
              <select
                aria-label="cue focus"
                value={focus}
                onChange={(e) => setFocus(e.target.value)}
                disabled={focuses.length === 0}
                title={focuses.find((f) => f.key === focus)?.summary}
                className="h-8 appearance-none rounded-sm border border-border bg-card pl-2.5 pr-7 text-[length:var(--text-sm)] outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
              >
                {focuses.map((f) => (
                  <option key={f.key} value={f.key}>
                    {f.label}（{f.key}）
                  </option>
                ))}
                {focuses.length === 0 && <option value="general">载入词表…</option>}
              </select>
              <ChevronDown
                size={13}
                className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
              />
            </div>
          </Field>

          {/* sensitivity — the software gate */}
          <Field label={`灵敏度 min_confidence = ${sensitivity}`}>
            <div className="flex items-center gap-2">
              <input
                type="range"
                min={1}
                max={10}
                step={1}
                value={sensitivity}
                onChange={(e) => setSensitivity(Number(e.target.value))}
                aria-label="灵敏度阈值"
                className="h-8 w-40 accent-[var(--color-accent)]"
              />
              <label className="flex items-center gap-1.5 text-[length:var(--text-2xs)] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={gateOnServer}
                  onChange={(e) => setGateOnServer(e.target.checked)}
                  className="accent-[var(--color-accent)]"
                />
                同时作为服务端闸门
              </label>
            </div>
          </Field>

          <Field label="max_cues">
            <NumberInput value={maxCues} min={1} max={5} onChange={setMaxCues} />
          </Field>
          <Field label="turn_window">
            <NumberInput value={turnWindow} min={1} max={12} onChange={setTurnWindow} />
          </Field>
          {transport === "ws" && (
            <Field label="quiet_period（秒）">
              <NumberInput value={quietPeriod} min={0} max={60} onChange={setQuietPeriod} />
            </Field>
          )}

          <Field label="scope">
            <div className="flex items-center gap-1.5">
              <SegmentedControl
                segments={[
                  { value: "full", label: "full · 先检索" },
                  { value: "briefing", label: "briefing · 冻结包" },
                ]}
                value={scope}
                onChange={(v) => setScope(v as Scope)}
                className="w-max min-w-max [&>button]:flex-none [&>button]:px-2.5"
              />
              {scope === "briefing" && (
                <div className="relative">
                  <select
                    aria-label="briefing"
                    value={briefingId}
                    onChange={(e) => setBriefingId(e.target.value)}
                    className="h-8 max-w-[13rem] appearance-none rounded-sm border border-border bg-card pl-2.5 pr-7 text-[length:var(--text-sm)] outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <option value="">选择 briefing…</option>
                    {briefings.map((b) => (
                      <option key={b.briefing_id} value={b.briefing_id}>
                        {b.briefing_id.slice(0, 8)}… · {b.char_count} 字
                      </option>
                    ))}
                  </select>
                  <ChevronDown
                    size={13}
                    className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground"
                  />
                </div>
              )}
            </div>
          </Field>

          <label className="flex items-center gap-1.5 pb-1 text-[length:var(--text-2xs)] text-muted-foreground">
            <input
              type="checkbox"
              checked={sendShown}
              onChange={(e) => setSendShown(e.target.checked)}
              className="accent-[var(--color-accent)]"
            />
            带上 already_shown（{alreadyShown.length}）
          </label>
        </div>

        {vocabError && (
          <div className="mt-2 flex items-center gap-1.5 text-[length:var(--text-2xs)] text-[var(--color-danger)]">
            <AlertTriangle size={12} /> 词表拉取失败：{vocabError}
          </div>
        )}
      </div>

      {/* --------------------------------------------------------------- two panes */}
      <div className="flex min-h-0 flex-1 flex-col lg:flex-row">
        {/* LEFT — transcript */}
        <div className="flex min-h-0 flex-col border-b border-border lg:w-[42%] lg:border-b-0 lg:border-r">
          <div className="border-b border-border px-4 py-2.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[length:var(--text-2xs)] font-medium text-muted-foreground">预置场景</span>
              {CUE_PRESETS.map((p) => (
                <Chip key={p.key} onClick={() => loadPreset(p)} title={`${p.summary} · ${p.expect}`}>
                  {p.label}
                </Chip>
              ))}
              <Button size="sm" variant="ghost" onClick={clearAll} title="清空转录与卡片">
                <Trash2 size={13} /> 清空
              </Button>
            </div>
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
            {turns.length === 0 ? (
              <EmptyState
                icon={<Ear size={26} />}
                title="转录为空"
                hint="点上面的预置场景，或在下方逐轮追加。整段转录永远全量送入——focus 只改变模型的注意力指向，不做说话人过滤。"
              />
            ) : (
              <ol className="space-y-2">
                {turns.map((t) => (
                  <li
                    key={t.id}
                    className={cn(
                      "rounded-sm border border-border bg-card px-3 py-2",
                      transport === "ws" && t.sent && "opacity-60",
                    )}
                  >
                    <div className="flex items-center gap-1.5 text-[length:var(--text-2xs)]">
                      <Chip
                        dotColor={
                          t.role === "owner" ? "var(--color-accent)" : "var(--color-border-strong)"
                        }
                      >
                        {ROLE_LABEL[t.role]}
                      </Chip>
                      <span className="text-muted-foreground">{t.speaker}</span>
                      {transport === "ws" && (
                        <span className="ml-auto flex items-center gap-1.5">
                          {t.sent ? (
                            <span className="text-muted-foreground">已推送</span>
                          ) : (
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={wsStatus !== "open"}
                              onClick={() => pushTurn(t)}
                            >
                              <Send size={12} /> 推送
                            </Button>
                          )}
                        </span>
                      )}
                      <button
                        type="button"
                        aria-label="删除该轮"
                        onClick={() => setTurns((ts) => ts.filter((x) => x.id !== t.id))}
                        className={cn(
                          "rounded-sm p-0.5 text-muted-foreground hover:bg-accent",
                          transport === "ws" ? "" : "ml-auto",
                        )}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                    <div className="mt-1 break-words text-sm leading-6 text-foreground">
                      <Highlighted text={t.text} trigger={activeTrigger} />
                    </div>
                  </li>
                ))}
              </ol>
            )}

            {activeCue && !triggerLocated && (
              <div className="mt-3 rounded-sm border border-border px-3 py-2 text-[length:var(--text-2xs)] text-muted-foreground">
                选中卡片的 trigger 未能在当前转录中定位（模型引述与原文有出入，或该轮已滚出窗口）：
                <span className="text-foreground">「{activeTrigger}」</span>
              </div>
            )}
          </div>

          {/* composer */}
          <div className="border-t border-border px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <SegmentedControl
                segments={[
                  { value: "other", label: "参与者" },
                  { value: "owner", label: "本人" },
                ]}
                value={draftRole}
                onChange={(v) => {
                  const role = v as Role;
                  setDraftRole(role);
                  setDraftSpeaker((s) =>
                    s === ROLE_LABEL.owner || s === ROLE_LABEL.other || !s ? ROLE_LABEL[role] : s,
                  );
                }}
                className="w-max min-w-max [&>button]:flex-none [&>button]:px-2.5"
              />
              <input
                value={draftSpeaker}
                onChange={(e) => setDraftSpeaker(e.target.value)}
                aria-label="说话人"
                placeholder="说话人"
                className="h-8 w-24 rounded-sm border border-border bg-card px-2 text-[length:var(--text-sm)] outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") addTurn();
                }}
                aria-label="这一轮说了什么"
                placeholder="这一轮说了什么…"
                className="h-8 min-w-[10rem] flex-1 rounded-sm border border-border bg-card px-2 text-[length:var(--text-sm)] outline-none focus-visible:ring-2 focus-visible:ring-ring"
              />
              <Button size="sm" variant="outline" onClick={addTurn} disabled={!draft.trim()}>
                <Plus size={13} /> 追加
              </Button>
            </div>

            <div className="mt-2.5 flex flex-wrap items-center gap-2">
              {transport === "sse" ? (
                <Button
                  variant="primary"
                  size="md"
                  disabled={busy || turns.length === 0}
                  onClick={runOnce}
                >
                  {busy ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />}
                  送整段评估一次
                </Button>
              ) : (
                <>
                  <Button
                    variant="primary"
                    size="md"
                    disabled={wsStatus !== "open" || turns.every((t) => t.sent)}
                    onClick={pushRemaining}
                  >
                    <Send size={14} /> 推送未发送的轮次
                  </Button>
                  <Button
                    variant="outline"
                    size="md"
                    disabled={wsStatus !== "open"}
                    title="立即评估，跳过静默期（不跳过单在途规则）"
                    onClick={() => {
                      sockRef.current?.flush();
                      pushLog("flush · 请求立即评估");
                    }}
                  >
                    flush
                  </Button>
                </>
              )}
              <span className="text-[length:var(--text-2xs)] text-muted-foreground">
                {transport === "sse"
                  ? "一次性：无会话、无节流、无服务端去重"
                  : "长连接：服务端持窗口 + 静默期 + 单在途合并"}
              </span>
            </div>
          </div>
        </div>

        {/* RIGHT — cards + debug */}
        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
          <div className="mb-2.5 flex flex-wrap items-center gap-2">
            <span className="text-[length:var(--text-2xs)] font-medium text-muted-foreground">
              提词卡 {visible.length} / 收到 {received.length}
            </span>
            {hiddenLocally > 0 && (
              <Chip dotColor="var(--color-accent)" title="纯客户端过滤，未重新请求任何东西">
                本地阈值挡下 {hiddenLocally} 张（未重新请求）
              </Chip>
            )}
            {received.length > 0 && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setReceived([]);
                  setActiveId(null);
                  setDetails({});
                  setDetailErrors({});
                }}
              >
                <Trash2 size={13} /> 清空卡片
              </Button>
            )}
          </div>

          {error && (
            <div className="mb-2.5 flex items-start gap-1.5 rounded-sm border border-border px-3 py-2 text-[length:var(--text-sm)] text-[var(--color-danger)]">
              <AlertTriangle size={13} className="mt-0.5 flex-none" /> {error}
            </div>
          )}

          {visible.length === 0 ? (
            <div className="rounded-sm border border-border px-4 py-6 text-center">
              <div className="text-sm text-foreground">
                {received.length === 0 ? "还没有提词卡" : "全部卡片被当前灵敏度挡下"}
              </div>
              <div className="mx-auto mt-1.5 max-w-md text-[length:var(--text-2xs)] leading-5 text-muted-foreground">
                {received.length === 0
                  ? "沉默是这个功能的稳态：解析失败 / 无有效引用 / 信心不足 / 超出上限，四道闸门任一都会让这次评估一张卡都不出。下方调试面板显示卡在哪一道。"
                  : "把灵敏度调低即可让它们重新出现——阈值是程序侧过滤，卡片自带 confidence，不需要重新评估。"}
              </div>
            </div>
          ) : (
            <div className="space-y-2.5">
              {visible.map((r) => (
                <CueCard
                  key={r.id}
                  item={r}
                  active={r.id === activeId}
                  kindLabel={kinds.find((k) => k.key === r.cue.kind)?.label ?? r.cue.kind}
                  detail={details[r.id]}
                  pending={detailPending.includes(r.id)}
                  failure={detailErrors[r.id]}
                  canExpand={transport === "ws" && wsStatus === "open"}
                  onSelect={() => setActiveId(r.id === activeId ? null : r.id)}
                  onWantMore={() => wantMore(r)}
                  toCitation={toCitation}
                />
              ))}
            </div>
          )}

          <DebugPanel
            transport={transport}
            done={lastDone}
            stats={lastStats}
            ready={ready}
            log={log}
            sensitivity={sensitivity}
            gateOnServer={gateOnServer}
            hiddenLocally={hiddenLocally}
          />
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------- sub-components */

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </span>
      {children}
    </label>
  );
}

function NumberInput({
  value,
  min,
  max,
  onChange,
}: {
  value: number;
  min: number;
  max: number;
  onChange: (n: number) => void;
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      max={max}
      onChange={(e) => {
        const n = Number(e.target.value);
        if (Number.isFinite(n)) onChange(Math.min(max, Math.max(min, Math.round(n))));
      }}
      className="h-8 w-20 rounded-sm border border-border bg-card px-2 text-[length:var(--text-sm)] outline-none focus-visible:ring-2 focus-visible:ring-ring"
    />
  );
}

/** One cue card: kind + confidence + title + body + citations + the trigger that fired it. */
function CueCard({
  item,
  active,
  kindLabel,
  detail,
  pending,
  failure,
  canExpand,
  onSelect,
  onWantMore,
  toCitation,
}: {
  item: Received;
  active: boolean;
  kindLabel: string;
  detail?: api.CueDetailFrame;
  pending: boolean;
  /** This card's own failed expansion, matched by `ref` — never another card's. */
  failure?: string;
  canExpand: boolean;
  onSelect: () => void;
  onWantMore: () => void;
  toCitation: (c: api.CueCitation) => Citation;
}) {
  const { cue } = item;
  return (
    <div
      className={cn(
        "rounded-sm border bg-card px-4 py-3 transition-colors",
        active ? "border-[var(--color-accent)]" : "border-border",
      )}
      style={active ? { boxShadow: "inset 3px 0 0 var(--color-accent)" } : undefined}
    >
      <div className="flex flex-wrap items-center gap-1.5 text-[length:var(--text-2xs)]">
        <Chip
          dotColor={
            cue.kind === "concept" ? "var(--color-accent)" : "var(--color-verified)"
          }
        >
          {kindLabel}
        </Chip>
        <Chip title="模型给这张卡打的信心分（1-10）——阈值过滤就作用在它身上">
          信心 {cue.confidence}
        </Chip>
        <Chip>{item.via === "ws" ? `ws · seq ${item.seq}` : "sse"}</Chip>
        <button
          type="button"
          onClick={onSelect}
          className="ml-auto text-[length:var(--text-2xs)] text-muted-foreground underline underline-offset-2 hover:text-foreground"
        >
          {active ? "取消高亮" : "在转录中高亮 trigger"}
        </button>
      </div>

      <div className="mt-2 text-[length:var(--text-base)] font-medium leading-6 text-foreground">{cue.title}</div>
      <div className="mt-1 break-words text-sm leading-6 text-foreground">{cue.body}</div>

      {cue.citations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {cue.citations.map((c, i) => (
            <CitationChip key={i} cite={toCitation(c)} />
          ))}
        </div>
      )}

      <div className="mt-2 flex items-start gap-1.5 border-t border-border-subtle pt-2 text-[length:var(--text-2xs)] text-muted-foreground">
        <Link2 size={12} className="mt-0.5 flex-none" />
        <span>
          trigger：<span className="text-foreground">「{cue.trigger}」</span>
        </span>
      </div>

      <div className="mt-2">
        <Button
          size="sm"
          variant="outline"
          disabled={!canExpand || pending}
          title={canExpand ? "走 WS 的 want_more，基于本卡引用取原文再展开" : "want_more 只在 WebSocket 链路可用"}
          onClick={onWantMore}
        >
          {pending ? <Loader2 size={12} className="animate-spin" /> : <Sparkles size={12} />}
          {failure ? "重试展开（want_more）" : "展开（want_more）"}
        </Button>
      </div>

      {failure && (
        <div className="mt-2 flex items-start gap-1.5 rounded-sm border border-border-subtle px-3 py-2 text-[length:var(--text-2xs)] leading-5 text-[var(--color-danger)]">
          <AlertTriangle size={12} className="mt-0.5 flex-none" />
          <span>展开失败：{failure}</span>
        </div>
      )}

      {detail && (
        <div className="mt-2 rounded-sm border border-border-subtle bg-[var(--color-surface-muted)] px-3 py-2">
          <div className="text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
            cue_detail
          </div>
          <div className="mt-1 whitespace-pre-wrap break-words text-[length:var(--text-sm)] leading-6 text-foreground">
            {detail.detail || "（空）"}
          </div>
          {detail.citations.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {detail.citations.map((c, i) => (
                <CitationChip key={i} cite={toCitation(c)} />
              ))}
            </div>
          )}
          <div className="mt-1.5">
            <UsageBar usage={detail.token_usage} />
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * The gate counters + the effective policy + the socket frame log.
 *
 * `dropped` is the reason this panel earns its space: when a transcript produces nothing,
 * it says WHICH of the four mechanical gates ate the card, which is exactly what you need
 * while tuning sensitivity. Both transports report it — SSE on its terminal `done` frame,
 * the socket on the `stats` frame this page opts into. The socket's arrives on EVERY
 * evaluation including the ones that delivered nothing, so the zero-card case, the one
 * you most want explained, is covered rather than silent.
 */
function DebugPanel({
  transport,
  done,
  stats,
  ready,
  log,
  sensitivity,
  gateOnServer,
  hiddenLocally,
}: {
  transport: Transport;
  done: api.CueDone | null;
  stats: api.CueStatsFrame | null;
  ready: api.CueReadyFrame | null;
  log: LogLine[];
  sensitivity: number;
  gateOnServer: boolean;
  hiddenLocally: number;
}) {
  // One shape for both transports, so the panel reads identically either way.
  const gates =
    transport === "ws"
      ? stats && {
          dropped: stats.dropped,
          focus: stats.focus,
          count: stats.delivered,
          usage: stats.token_usage,
          stamp: `seq ${stats.seq}`,
        }
      : done && {
          dropped: done.dropped,
          focus: done.focus,
          count: done.count,
          usage: done.token_usage,
          stamp: `as_of ${done.as_of}`,
        };
  const dropped = (gates ? gates.dropped : {}) as Record<string, number>;
  const order = ["unparsed", "repeat", "uncited", "low_confidence", "capped"];
  return (
    <div className="mt-4 space-y-2.5">
      <Eyebrow>调试面板</Eyebrow>

      <div className="rounded-sm border border-border bg-card px-3 py-2.5">
        <div className="text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
          闸门丢弃计数 · dropped
        </div>
        {gates == null ? (
          <div className="mt-1.5 text-[length:var(--text-2xs)] leading-5 text-muted-foreground">
            {transport === "ws"
              ? "还没有评估结果。本页已在 config 里开启 stats，每次评估都会回一帧——包括一张卡都没下发的那些。"
              : "还没有评估结果。"}
          </div>
        ) : (
          <>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {order.map((k) => {
                const n = dropped[k] ?? 0;
                return (
                  <Chip
                    key={k}
                    dotColor={n > 0 ? "var(--color-accent)" : "var(--color-border-strong)"}
                    title={k}
                  >
                    {DROP_LABEL[k]} {n}
                  </Chip>
                );
              })}
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[length:var(--text-2xs)] text-muted-foreground">
              <span>focus {gates.focus}</span>
              <span>下发 {gates.count} 张</span>
              <span className="font-mono">{gates.stamp}</span>
            </div>
            <div className="mt-1.5">
              <UsageBar usage={gates.usage} />
            </div>
          </>
        )}
      </div>

      <div className="rounded-sm border border-border bg-card px-3 py-2.5">
        <div className="text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
          灵敏度落在哪一侧
        </div>
        <div className="mt-1.5 text-[length:var(--text-2xs)] leading-5 text-muted-foreground">
          客户端阈值 <span className="font-mono text-foreground">{sensitivity}</span>，正挡下{" "}
          <span className="font-mono text-foreground">{hiddenLocally}</span> 张已收到的卡片（纯本地
          过滤，不发任何请求）。服务端闸门{" "}
          <span className="font-mono text-foreground">
            min_confidence = {gateOnServer ? sensitivity : 1}
          </span>
          {gateOnServer
            ? " —— 低于它的卡片根本不会下发，计入 dropped.low_confidence。"
            : " —— 闸门放开，模型打了分的卡片全部下发，过滤完全在本页做。"}
        </div>
      </div>

      {transport === "ws" && (
        <>
          <div className="rounded-sm border border-border bg-card px-3 py-2.5">
            <div className="text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
              服务端回执的生效策略 · ready
            </div>
            {ready ? (
              <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1 font-mono text-[length:var(--text-2xs)] text-muted-foreground">
                <span>focus {ready.focus}</span>
                <span>min_conf {ready.min_confidence}</span>
                <span>max_cues {ready.max_cues}</span>
                <span>window {ready.turn_window}</span>
                <span>quiet {ready.quiet_period}s</span>
                <span>briefing {ready.briefing_id ?? "—"}</span>
                <span>stats {ready.stats ? "on" : "off"}</span>
              </div>
            ) : (
              <div className="mt-1.5 text-[length:var(--text-2xs)] text-muted-foreground">未连接。</div>
            )}
          </div>

          <div className="rounded-sm border border-border bg-card px-3 py-2.5">
            <div className="text-[length:var(--text-2xs)] font-medium uppercase tracking-wide text-muted-foreground">
              帧日志（最近 {log.length}）
            </div>
            <ol className="mt-1.5 max-h-64 space-y-1 overflow-y-auto">
              {log.length === 0 && (
                <li className="text-[length:var(--text-2xs)] text-muted-foreground">暂无。</li>
              )}
              {log.map((l) => (
                <li key={l.id} className="flex gap-2 font-mono text-[length:var(--text-2xs)] leading-5">
                  <span className="flex-none text-muted-foreground">
                    {new Date(l.at).toLocaleTimeString()}
                  </span>
                  <span
                    className={cn(
                      "min-w-0 break-words",
                      l.tone === "warn"
                        ? "text-[var(--color-danger)]"
                        : l.tone === "good"
                          ? "text-foreground"
                          : "text-muted-foreground",
                    )}
                  >
                    {l.text}
                  </span>
                </li>
              ))}
            </ol>
          </div>
        </>
      )}
    </div>
  );
}
