import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Plug, Plus, RadioTower, RotateCcw, Trash2 } from "lucide-react";
import { useApp } from "@/lib/store";
import {
  LiveContextSocket,
  liveContextStream,
  getContextFocuses,
  getSuggestionKinds,
  listAllSources,
  type ContextFocusOption,
  type ContextSuggestion,
  type LiveContextDone,
  type LiveContextReadyFrame,
  type LiveContextServerFrame,
  type LiveContextSocketStatus,
  type LiveContextStatsFrame,
  type ContextTurnInput,
  type SuggestionDetailFrame,
} from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import { useT, useTOr, type TFunction, type TOrFunction } from "@/lib/useT";
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
import { ContextSuggestionCard } from "./ContextSuggestionCard";

type Role = "owner" | "other" | "unknown";

/**
 * The role vocabulary is the client's own (the wire takes the bare `owner` / `other` /
 * `unknown`), so it holds message keys and is resolved per render — a module-level constant
 * built from `tx()` would freeze the locale at import time.
 */
const ROLE_OPTIONS: { value: Role; labelKey: MessageKey }[] = [
  { value: "owner", labelKey: "liveContext.role.owner" },
  { value: "other", labelKey: "liveContext.role.other" },
  { value: "unknown", labelKey: "liveContext.role.unknown" },
];

const roleOptions = (t: TFunction) =>
  ROLE_OPTIONS.map(({ value, labelKey }) => ({ value, label: t(labelKey) }));

/** The focus select's options and hint, from the server vocabulary + the enum dictionary. */
function focusOptions(focuses: ContextFocusOption[], t: TFunction, tOr: TOrFunction) {
  return focuses.map((f) => ({
    value: f.key,
    label: t("liveContext.focus.option", {
      label: tOr(`enum.contextFocus.${f.key}.label`, f.label),
      key: f.key,
    }),
  }));
}

function focusHint(
  focuses: ContextFocusOption[],
  selected: string | null,
  tOr: TOrFunction,
): string | undefined {
  const found = focuses.find((f) => f.key === selected);
  if (!found) return undefined;
  return tOr(`enum.contextFocus.${found.key}.summary`, found.summary);
}

let seed = 0;
const nextId = () => `${Date.now().toString(36)}-${(seed++).toString(36)}`;

/* ============================================================= one-shot SSE panel */

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
  const [maxContextSuggestions, setMaxContextSuggestions] = useState<number | null>(3);
  const [turnWindow, setTurnWindow] = useState<number | null>(3);
  /** The local re-filter threshold: a client-side software filter, sending no request. */
  const [threshold, setThreshold] = useState(1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [cards, setCards] = useState<ContextSuggestion[]>([]);
  const [done, setDone] = useState<LiveContextDone | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Abort the SSE stream on unmount.
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
    await liveContextStream(
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
        max_suggestions: maxContextSuggestions ?? 3,
        turn_window: turnWindow ?? 3,
        // Deduplication feedback: cards already delivered go back as {kind, title}, so the
        // same suggestion is not raised twice.
        already_shown: cards.map((c) => ({ kind: c.kind, title: c.title })),
      },
      {
        onSuggestion: (suggestion) => setCards((cs) => [...cs, suggestion]),
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
    maxContextSuggestions,
    setMaxContextSuggestions,
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

/* ========================================================== long-lived WS panel */

interface WsCard {
  id: string;
  suggestion: ContextSuggestion;
  seq: number;
}

function useWsPanel(currentUser: string | null, t: TFunction) {
  const sockRef = useRef<LiveContextSocket | null>(null);
  const [status, setStatus] = useState<LiveContextSocketStatus>("closed");
  const [ready, setReady] = useState<LiveContextReadyFrame | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [minConf, setMinConf] = useState(6);
  const [turnWindow, setTurnWindow] = useState<number | null>(3);
  const [quietPeriod, setQuietPeriod] = useState<number | null>(6);
  const [statsOn, setStatsOn] = useState(true);
  const [cards, setCards] = useState<WsCard[]>([]);
  const [sentTurns, setSentTurns] = useState<ContextTurnInput[]>([]);
  const [statsLog, setStatsLog] = useState<LiveContextStatsFrame[]>([]);
  const [error, setError] = useState<string | null>(null);
  // All three want_more books are kept against the RECEIVED CARD's id, resolved back from
  // the ref that was sent — never against the title (the title is the deduplication key and
  // cannot say which request a failure belongs to).
  const [details, setDetails] = useState<Record<string, SuggestionDetailFrame>>({});
  const [pending, setPending] = useState<string[]>([]);
  const [failures, setFailures] = useState<Record<string, string>>({});
  // In-flight want_more links: ref → card id. A ref, not state — the frame handler reads it
  // synchronously.
  const refToCard = useRef(new Map<string, string>());

  // The draft speaker is a starting value for an editable field, so it is read once: a later
  // locale switch must not overwrite what the operator typed.
  const [draftSpeaker, setDraftSpeaker] = useState(() => t("liveContext.ws.defaultSpeaker"));
  const [draftText, setDraftText] = useState("");
  const [draftRole, setDraftRole] = useState<Role>("other");

  /** Resolve a frame's ref back to the card that asked, retiring the link; unknown → null. */
  const takeRef = useCallback((ref: string | null | undefined): string | null => {
    if (!ref) return null;
    const card = refToCard.current.get(ref) ?? null;
    refToCard.current.delete(ref);
    return card;
  }, []);

  const onFrame = useCallback(
    (frame: LiveContextServerFrame) => {
      switch (frame.type) {
        case "ready":
          setReady(frame);
          break;
        case "stats":
          // Every evaluation returns one, including those that delivered nothing — precisely
          // the frame whose gate ledger needs reading.
          setStatsLog((l) => [frame, ...l].slice(0, 8));
          break;
        case "suggestion":
          setCards((cs) => {
            // The client is the deduplication authority: a {kind,title} already delivered is
            // never taken a second time.
            if (cs.some((c) => c.suggestion.kind === frame.suggestion.kind && c.suggestion.title === frame.suggestion.title))
              return cs;
            return [...cs, { id: nextId(), suggestion: frame.suggestion, seq: frame.seq }];
          });
          break;
        case "suggestion_detail": {
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
          // A failure carrying a ref belongs to that want_more; without one (a bad frame, a
          // failed evaluation) it belongs to no request and surfaces as the panel error.
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
      // The bench turns stats on explicitly; a real context client never would — a silent
      // connection has to be genuinely silent.
      stats: statsOn,
    }),
    [focus, minConf, turnWindow, quietPeriod, statsOn],
  );

  /**
   * Open the connection. With restore=true the first config replays the window plus the
   * cards already shown — the documented reconnect path: the client is the deduplication
   * authority and the server remembers nothing across a disconnect.
   */
  const connect = useCallback(
    (restore: boolean) => {
      if (!currentUser) return;
      sockRef.current?.close();
      setReady(null);
      setError(null);
      // Links do not outlive a connection: a ref sent on the old socket will never be answered.
      refToCard.current.clear();
      setPending([]);
      setStatsLog([]);
      const sock = new LiveContextSocket(currentUser, onFrame, (s) => setStatus(s));
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
                already_shown: cards.map((c) => ({ kind: c.suggestion.kind, title: c.suggestion.title })),
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

  // Tear the connection down on unmount (or a user switch) — a listener bound to the previous
  // user would go on evaluating against the previous knowledge base.
  useEffect(() => {
    return () => {
      sockRef.current?.close();
      sockRef.current = null;
    };
  }, [currentUser]);

  // The knobs stay live while connected: each change pushes config and the server answers
  // with a fresh ready frame.
  const policyKey = JSON.stringify(policyMessage());
  useEffect(() => {
    if (status === "open") sockRef.current?.config(JSON.parse(policyKey));
  }, [policyKey, status]);

  function sendDraft() {
    const text = draftText.trim();
    const sock = sockRef.current;
    if (!sock?.ready || !text) return;
    const turn: ContextTurnInput = {
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
    // A brand-new ref per request: a retry after a failure is a new link, so a late answer
    // cannot attach itself to the wrong card.
    const ref = nextId();
    refToCard.current.set(ref, item.id);
    sock.wantMore(item.suggestion, ref);
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

/* ================================================================ Live Context view */

/**
 * The Live Context bench, one panel per transport.
 * One-shot SSE evaluates a whole workstream window in a single call; the long-lived WS keeps
 * the window, the quiet period and single-in-flight coalescing on the server, with want_more
 * expanding a card into a suggestion_detail. Both transports' state hangs off hooks at the
 * LiveContextView level — switching tabs unmounts the inactive panel, so the state has to
 * outlive it.
 */
export default function LiveContextView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const focusSource = useApp((s) => s.focusSource);
  const [tab, setTab] = useState("sse");
  const [focuses, setFocuses] = useState<ContextFocusOption[]>([]);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [vocabError, setVocabError] = useState<string | null>(null);
  const [titles, setTitles] = useState<Record<string, string>>({});

  const sse = useSsePanel(currentUser);
  const ws = useWsPanel(currentUser, t);

  // The focus / kind vocabularies come from the server (closed vocabularies; the front end
  // keeps no private copy — only translations of the served keys).
  useEffect(() => {
    let alive = true;
    Promise.all([getContextFocuses(), getSuggestionKinds()])
      .then(([f, k]) => {
        if (!alive) return;
        setFocuses(f);
        setKindLabels(Object.fromEntries(k.map((x) => [x.key, x.label])));
        // The default is always the vocabulary's first entry, never a hard-coded key.
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
    listAllSources(currentUser)
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
        <PageHeader
          title={t("nav.view.live_context")}
          description={t("liveContext.descriptionShort")}
        />
        <EmptyState
          icon={RadioTower}
          title={t("liveContext.noUser.title")}
          description={t("liveContext.noUser.description")}
        />
      </>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title={t("nav.view.live_context")}
        description={t("liveContext.description")}
      />
      {vocabError && (
        <Callout tone="warn">{t("liveContext.vocabError", { detail: vocabError })}</Callout>
      )}
      <Tabs
        aria-label={t("liveContext.transportAria")}
        value={tab}
        onChange={setTab}
        tabs={[
          {
            value: "sse",
            label: t("liveContext.tab.sse"),
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
            label: t("liveContext.tab.ws"),
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

/* ---------------------------------------------------------------- SSE panel */

function SsePanel({
  panel,
  focuses,
  kindLabels,
  titles,
  onJump,
}: {
  panel: ReturnType<typeof useSsePanel>;
  focuses: ContextFocusOption[];
  kindLabels: Record<string, string>;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const t = useT();
  const tOr = useTOr();
  const hidden = panel.cards.length - panel.visible.length;
  return (
    <div className="flex flex-col gap-8">
      {/* the workstream window */}
      <section>
        <SectionRule
          no={1}
          title={t("liveContext.sse.window.title")}
          actions={
            <Button size="sm" onClick={panel.addTurn}>
              <Plus size={13} aria-hidden /> {t("liveContext.sse.window.add")}
            </Button>
          }
        />
        {panel.turns.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">{t("liveContext.sse.window.hint")}</p>
        ) : (
          <ol className="mt-3 flex flex-col gap-2">
            {panel.turns.map((turn) => (
              <li key={turn.id} className="flex flex-wrap items-start gap-2">
                <TextField
                  wrapperClassName="w-28"
                  value={turn.speaker}
                  onChange={(e) => panel.updateTurn(turn.id, { speaker: e.target.value })}
                  placeholder={t("liveContext.turn.speaker")}
                  aria-label={t("liveContext.turn.speaker")}
                />
                <Select
                  wrapperClassName="w-28"
                  value={turn.role}
                  onChange={(v) => panel.updateTurn(turn.id, { role: v as Role })}
                  options={roleOptions(t)}
                  aria-label={t("liveContext.turn.role")}
                />
                <TextField
                  wrapperClassName="min-w-40 flex-1"
                  value={turn.text}
                  onChange={(e) => panel.updateTurn(turn.id, { text: e.target.value })}
                  placeholder={t("liveContext.turn.textPlaceholder")}
                  aria-label={t("liveContext.turn.text")}
                />
                <IconButton
                  aria-label={t("liveContext.turn.remove")}
                  size="md"
                  onClick={() => panel.removeTurn(turn.id)}
                >
                  <Trash2 size={14} aria-hidden />
                </IconButton>
              </li>
            ))}
          </ol>
        )}
      </section>

      {/* evaluation parameters */}
      <section>
        <SectionRule no={2} title={t("liveContext.sse.params.title")} />
        <div className="mt-4 flex max-w-measure flex-col gap-4">
          <Select
            label={t("liveContext.focus.label")}
            value={panel.focus}
            onChange={panel.setFocus}
            options={focusOptions(focuses, t, tOr)}
            placeholder={t("liveContext.focus.loading")}
            disabled={focuses.length === 0}
            hint={focusHint(focuses, panel.focus, tOr)}
          />
          <Slider
            label={t("liveContext.sse.minConfidence.label")}
            value={panel.minConf}
            onChange={panel.setMinConf}
            min={1}
            max={10}
            hint={t("liveContext.sse.minConfidence.hint")}
          />
          <div className="flex flex-wrap gap-4">
            <NumberField
              label="max_suggestions"
              value={panel.maxContextSuggestions}
              onChange={panel.setMaxContextSuggestions}
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
              {t("liveContext.sse.run")}
            </Button>
          </div>
        </div>
      </section>

      {/* results */}
      {panel.error ? (
        <ErrorState
          title={t("liveContext.sse.errorTitle")}
          error={panel.error}
          onRetry={() => void panel.evaluate()}
        />
      ) : (
        <section>
          <SectionRule
            no={3}
            title={t("liveContext.sse.cards.title", {
              visible: panel.visible.length,
              total: panel.cards.length,
            })}
            actions={
              panel.cards.length > 0 ? (
                <Button size="sm" variant="ghost" onClick={() => panel.setCards([])}>
                  {t("liveContext.cards.clear")}
                </Button>
              ) : undefined
            }
          />
          {panel.cards.length === 0 && !panel.busy && !panel.done ? (
            <div className="mt-4">
              <EmptyState
                icon={RadioTower}
                title={t("liveContext.cards.emptyTitle")}
                description={t("liveContext.sse.cards.emptyDescription")}
              />
            </div>
          ) : (
            <>
              <div className="mt-4 max-w-measure">
                <Slider
                  label={t("liveContext.sse.threshold.label")}
                  value={panel.threshold}
                  onChange={panel.setThreshold}
                  min={1}
                  max={10}
                  hint={t("liveContext.sse.threshold.hint")}
                />
                {hidden > 0 && (
                  <p className="mt-1 text-12 text-ink-3">
                    {t("liveContext.sse.threshold.hidden", { count: hidden })}
                  </p>
                )}
              </div>
              {panel.busy && (
                <p className="mt-3 text-12 text-ink-3">{t("liveContext.sse.streaming")}</p>
              )}
              {panel.busy && panel.cards.length === 0 && (
                <SkeletonText lines={3} className="mt-3 max-w-measure" />
              )}
              <div className="border-t border-line">
                {panel.visible.map((suggestion, i) => (
                  <ContextSuggestionCard
                    key={`${suggestion.kind}:${suggestion.title}:${i}`}
                    suggestion={suggestion}
                    kindLabel={tOr(
                      `enum.suggestionKind.${suggestion.kind}.label`,
                      kindLabels[suggestion.kind] ?? suggestion.kind,
                    )}
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

      {/* the gate ledger */}
      {panel.done && (
        <section>
          <SectionRule no={4} title={t("liveContext.gate.title")} />
          <GateLedger className="mt-4 max-w-measure" dropped={panel.done.dropped} />
          <p className="mt-2 text-12 text-ink-3">
            {t("liveContext.deliveredCount", { count: panel.done.count })} · focus{" "}
            <Mono>{panel.done.focus}</Mono> · as_of <Mono>{panel.done.as_of}</Mono>
          </p>
          <UsageLine usage={panel.done.token_usage} className="mt-1" />
        </section>
      )}
    </div>
  );
}

/* ----------------------------------------------------------------- WS panel */

function WsPanel({
  panel,
  focuses,
  kindLabels,
  titles,
  onJump,
}: {
  panel: ReturnType<typeof useWsPanel>;
  focuses: ContextFocusOption[];
  kindLabels: Record<string, string>;
  titles: Record<string, string>;
  onJump: (c: CitationEntry) => void;
}) {
  const t = useT();
  const tOr = useTOr();
  const open = panel.status === "open";
  return (
    <div className="flex flex-col gap-8">
      {/* the connection */}
      <section>
        <SectionRule
          no={1}
          title={t("liveContext.ws.connection.title")}
          actions={
            open ? (
              <>
                <Button size="sm" onClick={panel.disconnect}>
                  {t("liveContext.ws.disconnect")}
                </Button>
                <Button
                  size="sm"
                  title={t("liveContext.ws.reconnectTitle")}
                  onClick={() => panel.connect(true)}
                >
                  <RotateCcw size={13} aria-hidden /> {t("liveContext.ws.reconnect")}
                </Button>
              </>
            ) : (
              <Button size="sm" variant="primary" onClick={() => panel.connect(false)}>
                <Plug size={13} aria-hidden /> {t("liveContext.ws.connect")}
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
          {open
            ? t("liveContext.ws.status.open")
            : panel.status === "connecting"
              ? t("liveContext.ws.status.connecting")
              : t("liveContext.ws.status.closed")}
        </p>
        {panel.status === "closed" && (
          <Callout tone="notice" className="mt-3 max-w-measure">
            {t("liveContext.ws.closedNotice")}
          </Callout>
        )}
        {panel.ready && (
          <DefinitionList
            className="mt-3 max-w-measure"
            items={[
              { term: "focus", definition: <Mono>{panel.ready.focus}</Mono> },
              { term: "min_confidence", definition: <Mono>{panel.ready.min_confidence}</Mono> },
              { term: "max_suggestions", definition: <Mono>{panel.ready.max_suggestions}</Mono> },
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
        <SectionRule no={2} title={t("liveContext.ws.config.title")} />
        <div className="mt-4 flex max-w-measure flex-col gap-4">
          <Select
            label={t("liveContext.focus.label")}
            value={panel.focus}
            onChange={panel.setFocus}
            options={focusOptions(focuses, t, tOr)}
            placeholder={t("liveContext.focus.loading")}
            disabled={focuses.length === 0}
            hint={focusHint(focuses, panel.focus, tOr)}
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
              label={t("liveContext.ws.quietPeriod.label")}
              value={panel.quietPeriod}
              onChange={panel.setQuietPeriod}
              min={0}
              max={60}
            />
          </div>
          <Switch
            checked={panel.statsOn}
            onCheckedChange={panel.setStatsOn}
            label={t("liveContext.ws.stats.label")}
            hint={t("liveContext.ws.stats.hint")}
          />
          <p className="text-12 text-ink-3">{t("liveContext.ws.config.liveNote")}</p>
        </div>
      </section>

      {/* appending workstream fragments + flush */}
      <section>
        <SectionRule
          no={3}
          title={t("liveContext.ws.turns.title")}
          actions={
            <Button
              size="sm"
              disabled={!open}
              title={t("liveContext.ws.flushTitle")}
              onClick={panel.flush}
            >
              {t("liveContext.ws.flush")}
            </Button>
          }
        />
        <div className="mt-3 flex flex-wrap items-start gap-2">
          <TextField
            wrapperClassName="w-28"
            value={panel.draftSpeaker}
            onChange={(e) => panel.setDraftSpeaker(e.target.value)}
            placeholder={t("liveContext.turn.speaker")}
            aria-label={t("liveContext.turn.speaker")}
          />
          <Select
            wrapperClassName="w-28"
            value={panel.draftRole}
            onChange={(v) => panel.setDraftRole(v as Role)}
            options={roleOptions(t)}
            aria-label={t("liveContext.turn.role")}
          />
          <TextField
            wrapperClassName="min-w-40 flex-1"
            value={panel.draftText}
            onChange={(e) => panel.setDraftText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") panel.sendDraft();
            }}
            placeholder={t("liveContext.turn.textPlaceholder")}
            aria-label={t("liveContext.turn.text")}
          />
          <Button disabled={!open || !panel.draftText.trim()} onClick={panel.sendDraft}>
            {t("liveContext.ws.send")}
          </Button>
        </div>
        <p className="mt-2 text-12 text-ink-3">
          {t("liveContext.ws.sentCount", { count: panel.sentTurns.length })}
        </p>
      </section>

      {panel.error && (
        <Callout tone="danger" onDismiss={() => panel.setError(null)}>
          {panel.error}
        </Callout>
      )}

      {/* context suggestions */}
      <section>
        <SectionRule
          no={4}
          title={t("liveContext.ws.cards.title", { count: panel.cards.length })}
        />
        {panel.cards.length === 0 ? (
          <div className="mt-4">
            <EmptyState
              icon={RadioTower}
              title={t("liveContext.cards.emptyTitle")}
              description={t("liveContext.ws.cards.emptyDescription")}
            />
          </div>
        ) : (
          <div className="border-t border-line">
            {panel.cards.map((item) => (
              <ContextSuggestionCard
                key={item.id}
                suggestion={item.suggestion}
                kindLabel={tOr(
                  `enum.suggestionKind.${item.suggestion.kind}.label`,
                  kindLabels[item.suggestion.kind] ?? item.suggestion.kind,
                )}
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

      {/* the stats history */}
      <section>
        <SectionRule no={5} title={t("liveContext.ws.statsLog.title")} />
        {panel.statsLog.length === 0 ? (
          <p className="mt-3 text-13 text-ink-3">{t("liveContext.ws.statsLog.empty")}</p>
        ) : (
          <div className="mt-4 flex flex-col gap-6">
            {panel.statsLog.map((s) => (
              <div key={s.seq}>
                <p className="mb-2 text-12 text-ink-3">
                  <Mono>seq {s.seq}</Mono> ·{" "}
                  {t("liveContext.deliveredCount", { count: s.delivered })} · focus{" "}
                  <Mono>{s.focus}</Mono>
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
