/**
 * Live Context — one conversation, two deliveries, one place the system answers.
 *
 * The page is three regions and the arrangement is the argument:
 *
 *   TOP     a collapsible config strip. Open, it is the bench's knob panel. Collapsed — which
 *           is how it starts — it is one line stating what is in force: the mode, whether the
 *           server has acknowledged the policy, the confidence floor, the transport's state.
 *           The knobs matter while you are setting up and never again, so they do not deserve
 *           permanent tenancy of the top third of the screen.
 *   LEFT    the conversation, and the composer that grows it.
 *   RIGHT   what the system had to say about it, and the record of how it said it.
 *
 * Both panes fill the viewport and scroll inside themselves, so the page itself never scrolls:
 * a live conversation and a live suggestion are two things you watch at once, and either one
 * disappearing off the bottom while you read the other is the failure this layout exists to
 * prevent. (The height bound comes from the app shell's viewport-pane list.)
 *
 * **The mode changes delivery, not the conversation.** One-shot re-sends the whole window on
 * an explicit 「评估一次」; the long connection pushes each turn as it is sent and the server
 * decides when to evaluate. The turn list, the roles and the suggestion surface are the same
 * either way — the previous page had two of everything, which taught that these were two
 * features rather than two transports.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, Plug, RadioTower, Trash2 } from "lucide-react";
import { useApp } from "@/lib/store";
import {
  LiveContextSocket,
  getContextFocuses,
  getSuggestionKinds,
  liveContextStream,
  type ContextFocusOption,
  type ContextSuggestion,
  type LiveContextReadyFrame,
  type LiveContextServerFrame,
  type LiveContextSocketStatus,
  type LiveContextStatsFrame,
  type SuggestionDetailFrame,
  type SuggestionShown,
} from "@/lib/api";
import {
  roleReducer,
  turnReducer,
  wireRole,
  type ChatMode,
  type LiveRole,
  type RoleColour,
  type RoleState,
} from "@/lib/liveContextChat";
import {
  arrive,
  dismiss as dismissCard,
  emptyQueue,
  emptySurface,
  pin as pinCard,
  settleStale,
  staleProvisional,
  surfaceIsEmpty,
  tick,
  upgrade as upgradeCard,
  type QueueState,
  type SuggestionSurface,
} from "@/lib/suggestionQueue";
import {
  DEFAULT_DENSITY,
  DENSITY_PRESETS,
  densityValues,
  detectDensity,
  type DensityValues,
} from "@/lib/liveContextDensity";
import { useT, useTOr, type TFunction, type TOrFunction } from "@/lib/useT";
import { PageHeader } from "@/components/PageHeader";
import { type CitationEntry } from "@/components/CitationList";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Select } from "@/ui/Select";
import { Switch } from "@/ui/Switch";
import { cn } from "@/ui/cn";
import { useSourceTitles } from "../_shared/useSourceTitles";
import { ChatPanel } from "./ChatPanel";
import { SuggestionPanel, type PanelCounts, type WireEvent } from "./SuggestionPanel";

let seed = 0;
const nextId = () => `${Date.now().toString(36)}-${(seed++).toString(36)}`;

/** How often the countdown ring is recomputed. Fine enough to look continuous, coarse enough
 * to be free — the fraction is derived from timestamps, so this only decides the frame rate. */
const TICK_MS = 250;

/** Wire log depth. Enough to read the last exchange, bounded so a long session cannot grow. */
const WIRE_LOG_LIMIT = 40;

/** The client is the deduplication authority: a {kind,title} already delivered is never taken
 * a second time, on either transport. The separator is written as an ESCAPE and not as a
 * literal NUL: a raw one in the source makes this file binary to git and to grep, which
 * costs every future reader of this page a readable diff. */
const shownKey = (s: { kind: string; title: string }) => `${s.kind}\u0000${s.title}`;

function focusOptions(focuses: ContextFocusOption[], t: TFunction, tOr: TOrFunction) {
  return focuses.map((f) => ({
    value: f.key,
    label: t("liveContext.focus.option", {
      label: tOr(`enum.contextFocus.${f.key}.label`, f.label),
      key: f.key,
    }),
  }));
}

function focusHint(focuses: ContextFocusOption[], selected: string | null, tOr: TOrFunction) {
  const found = focuses.find((f) => f.key === selected);
  return found ? tOr(`enum.contextFocus.${found.key}.summary`, found.summary) : undefined;
}

export default function LiveContextView() {
  const t = useT();
  const tOr = useTOr();
  const currentUser = useApp((s) => s.currentUser);
  const focusSource = useApp((s) => s.focusSource);
  const conversation = useApp((s) => s.liveContext);
  const setLiveContext = useApp((s) => s.setLiveContext);
  const clearTurns = useApp((s) => s.clearLiveContextTurns);

  const { roles, activeRoleId, turns, mode } = conversation;

  /* ------------------------------------------------------------------ vocabularies */

  const [focuses, setFocuses] = useState<ContextFocusOption[]>([]);
  const [kindLabels, setKindLabels] = useState<Record<string, string>>({});
  const [vocabError, setVocabError] = useState<string | null>(null);

  const [focus, setFocus] = useState<string | null>(null);
  // The three hyperparameters move together, chosen by posture rather than by number — see
  // `lib/liveContextDensity.ts`. The RAW values are what is held and what goes on the wire;
  // the preset is derived, so a combination matching none of them reads as "custom" instead
  // of being quietly snapped to the nearest one.
  const [knobs, setKnobs] = useState<DensityValues>(() => densityValues(DEFAULT_DENSITY));
  const density = detectDensity(knobs);
  const [statsOn, setStatsOn] = useState(true);
  // The client half of the internet toggle. OFF by default and asked for explicitly: the
  // library is the authority, this reaches outside it, and it bills per search. What the
  // server GRANTS is a different value — `ready.web_search` below — because the deployment
  // has its own answer and a client that was told no must be able to see that it was.
  const [webSearchOn, setWebSearchOn] = useState(false);
  const [webSearchGranted, setWebSearchGranted] = useState<boolean | null>(null);
  const [configOpen, setConfigOpen] = useState(false);
  const [tab, setTab] = useState("history");

  useEffect(() => {
    let alive = true;
    Promise.all([getContextFocuses(), getSuggestionKinds()])
      .then(([f, k]) => {
        if (!alive) return;
        setFocuses(f);
        setKindLabels(Object.fromEntries(k.map((x) => [x.key, x.label])));
        // The default is always the vocabulary's first entry, never a hard-coded key.
        if (f.length > 0) setFocus((cur) => cur ?? f[0].key);
      })
      .catch((e) => alive && setVocabError((e as Error).message));
    return () => {
      alive = false;
    };
  }, []);

  /* ------------------------------------------------------------------------- roles */

  // The default pills are seeded ONCE, from the interface language in force at the time, and
  // are the operator's data from then on: a later language switch must not rewrite a role they
  // renamed. Same rule the old panel's draft speaker followed.
  useEffect(() => {
    if (roles.length > 0) return;
    const owner: LiveRole = {
      id: "role-owner",
      name: t("liveContext.role.owner"),
      colour: "slate",
      kind: "owner",
    };
    const other: LiveRole = {
      id: "role-other",
      name: t("liveContext.role.other"),
      colour: "amber",
      kind: "other",
    };
    setLiveContext({ roles: [owner, other], activeRoleId: other.id });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roles.length]);

  const applyRoles = useCallback(
    (action: Parameters<typeof roleReducer>[1]) => {
      const state: RoleState = { roles, activeId: activeRoleId };
      const next = roleReducer(state, action);
      if (next === state) return;
      setLiveContext({ roles: next.roles, activeRoleId: next.activeId });
    },
    [roles, activeRoleId, setLiveContext],
  );

  const applyTurns = useCallback(
    (action: Parameters<typeof turnReducer>[1]) => {
      const next = turnReducer(turns, action);
      if (next !== turns) setLiveContext({ turns: next });
      return next;
    },
    [turns, setLiveContext],
  );

  /* ------------------------------------------------------------------- the wire log */

  const [wireLog, setWireLog] = useState<WireEvent[]>([]);
  const [statsLog, setStatsLog] = useState<LiveContextStatsFrame[]>([]);
  const log = useCallback((direction: "in" | "out", label: string, detail?: string) => {
    setWireLog((l) => [{ id: nextId(), at: Date.now(), direction, label, detail }, ...l].slice(0, WIRE_LOG_LIMIT));
  }, []);

  /* -------------------------------------------------------------- suggestion queue */

  const [queue, setQueue] = useState<QueueState>(emptyQueue);
  const [now, setNow] = useState(() => Date.now());
  // The cards this page has shown, in arrival order, keyed by `${kind} ${title}`. A MAP,
  // not a set of keys: the server needs the body back (the discover stage answers "already
  // mined" against it) and the subject back (it restores the session's ledger, so a
  // reconnect does not re-introduce a subject this reader has met) — and splitting a key
  // string back apart would have lost every title containing a space anyway.
  const seenRef = useRef<Map<string, SuggestionShown>>(new Map());
  const [counts, setCounts] = useState<PanelCounts>({
    turnsSent: 0,
    suggestions: 0,
    deduped: 0,
    evaluations: 0,
  });

  // One ticker for the ring and the expiry, and it runs only while there is something to
  // expire — an idle page costs no wakeups, which is the same discipline the server's own
  // listener follows.
  const hasCards = queue.current !== null || queue.queue.length > 0;
  // The queue as the ticker sees it. A ref because the ticker also has to REPORT what it
  // did (a self-settled card is a lost frame, and the wire log is where that is said), and
  // a `setQueue` updater is not a place to write a log line from.
  const queueRef = useRef(queue);
  useEffect(() => {
    queueRef.current = queue;
  }, [queue]);
  const selfSettledRef = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!hasCards) return;
    const id = window.setInterval(() => {
      const at = Date.now();
      setNow(at);
      // The client-side belt under the server's `upgrade` frame: a provisional card that
      // waited past the timeout settles itself, as final, with what it already has. Said
      // out loud in the wire log — a badge that stopped shimmering because nothing arrived
      // is a different fact from one the server settled, and only one of them is a bug.
      for (const card of staleProvisional(queueRef.current, at)) {
        if (selfSettledRef.current.has(card.id)) continue;
        selfSettledRef.current.add(card.id);
        log("in", "settle (no upgrade)", `seq ${card.seq ?? "—"} · ${card.suggestion.title}`);
      }
      setQueue((q) => settleStale(tick(q, at), at));
    }, TICK_MS);
    return () => window.clearInterval(id);
  }, [hasCards, log]);

  const offer = useCallback((suggestion: ContextSuggestion, seq: number | null) => {
    const key = shownKey(suggestion);
    if (seenRef.current.has(key)) {
      setCounts((c) => ({ ...c, deduped: c.deduped + 1 }));
      return;
    }
    seenRef.current.set(key, {
      kind: suggestion.kind,
      title: suggestion.title,
      body: suggestion.body,
      subject: suggestion.subject ?? "",
      subject_label: suggestion.subject_label ?? suggestion.subject ?? "",
    });
    const at = Date.now();
    setCounts((c) => ({ ...c, suggestions: c.suggestions + 1 }));
    setQueue((q) => arrive(q, { id: nextId(), suggestion, seq, arrivedAt: at }, at));
  }, []);

  const alreadyShown = useCallback((): SuggestionShown[] => [...seenRef.current.values()], []);

  /* --------------------------------------------------------------- want_more books */

  const [details, setDetails] = useState<Record<string, SuggestionDetailFrame>>({});
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const [failures, setFailures] = useState<Record<string, string>>({});
  const refToCard = useRef(new Map<string, string>());

  /* ----------------------------------------------------------------- the transports */

  const [status, setStatus] = useState<LiveContextSocketStatus>("closed");
  const [ready, setReady] = useState<LiveContextReadyFrame | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const sockRef = useRef<LiveContextSocket | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const onFrame = useCallback(
    (frame: LiveContextServerFrame) => {
      switch (frame.type) {
        case "ready":
          setReady(frame);
          // The EFFECTIVE grant, which is not the request: the deployment may have said no.
          setWebSearchGranted(frame.web_search);
          log(
            "in",
            "ready",
            `focus ${frame.focus} · min_confidence ${frame.min_confidence}` +
              (frame.web_search ? " · web" : ""),
          );
          break;
        case "stats":
          setStatsLog((l) => [frame, ...l].slice(0, 8));
          setCounts((c) => ({ ...c, evaluations: c.evaluations + 1 }));
          log("in", "stats", `seq ${frame.seq} · delivered ${frame.delivered}`);
          break;
        case "suggestion":
          log("in", "suggestion", frame.suggestion.title);
          offer(frame.suggestion, frame.seq);
          break;
        // The provisional card's ending. It is a REPLACEMENT IN PLACE and never an arrival:
        // the card is already on screen, in this seq's slot, and `offer` would both queue a
        // second bubble about one subject and count it twice. This case going missing is
        // exactly the live defect — the server sent the frame, nothing read it, and the
        // badge said 「细节补充中…」 about a tick that had finished eight seconds earlier.
        // The `default` below is what makes a repeat of that a build failure.
        case "upgrade":
          log(
            "in",
            "upgrade",
            `seq ${frame.seq} · ${frame.suggestion ? frame.suggestion.title : t("liveContext.wire.settledInPlace")}`,
          );
          // The card that took the provisional one's place is a card this page has shown,
          // so it belongs in the dedup ledger like any other — the server replays it to the
          // discover stage on reconnect, and a subject introduced once is not introduced
          // again. The counter is NOT touched: one slot, one card, one count.
          if (frame.suggestion) {
            seenRef.current.set(shownKey(frame.suggestion), {
              kind: frame.suggestion.kind,
              title: frame.suggestion.title,
              body: frame.suggestion.body,
              subject: frame.suggestion.subject ?? "",
              subject_label: frame.suggestion.subject_label ?? frame.suggestion.subject ?? "",
            });
          }
          setQueue((q) => upgradeCard(q, frame.seq, frame.suggestion));
          break;
        case "suggestion_detail": {
          const card = frame.ref ? refToCard.current.get(frame.ref) : undefined;
          if (frame.ref) refToCard.current.delete(frame.ref);
          log("in", "suggestion_detail", frame.title);
          if (card) {
            setDetails((d) => ({ ...d, [card]: frame }));
            setFailures((f) => {
              if (!(card in f)) return f;
              const { [card]: _gone, ...rest } = f;
              return rest;
            });
            setPendingIds((p) => p.filter((x) => x !== card));
          }
          break;
        }
        case "error": {
          // A failure carrying a ref belongs to that want_more; without one it belongs to no
          // request and surfaces as the page error.
          const card = frame.ref ? refToCard.current.get(frame.ref) : undefined;
          if (frame.ref) refToCard.current.delete(frame.ref);
          log("in", "error", frame.detail);
          if (card) {
            setFailures((f) => ({ ...f, [card]: frame.detail }));
            setPendingIds((p) => p.filter((x) => x !== card));
          } else {
            setError(frame.detail);
          }
          break;
        }
        case "ping":
          break;
        default: {
          // MECHANISM, not diligence. A frame the server sends and this switch does not
          // name used to fall through in silence — which is how `upgrade` was added to the
          // protocol, sent every tick, and read by nobody. `never` makes the omission a
          // `tsc -b` failure instead of a badge that shimmers forever.
          const unhandled: never = frame;
          log("in", "unknown", JSON.stringify(unhandled).slice(0, 80));
          break;
        }
      }
    },
    [log, offer, t],
  );

  const policy = useMemo(
    () => ({
      focus: focus ?? undefined,
      min_confidence: knobs.min_confidence,
      max_pending_turns: knobs.max_pending_turns,
      quiet_period: knobs.quiet_period,
      web_search: webSearchOn,
      stats: statsOn,
    }),
    [focus, knobs, statsOn, webSearchOn],
  );

  // The long connection exists exactly while the page is in stream mode. Switching away closes
  // it rather than leaving a listener evaluating against a conversation nobody is watching.
  useEffect(() => {
    if (mode !== "stream" || !currentUser || !focus) return;
    const sock = new LiveContextSocket(currentUser, onFrame, (s) => setStatus(s));
    sockRef.current = sock;
    refToCard.current.clear();
    setPendingIds([]);
    const open = () => {
      if (sockRef.current !== sock) return;
      if (!sock.ready) {
        window.setTimeout(open, 60);
        return;
      }
      // The documented restore path, used here for the ordinary first connect too: the client
      // is the deduplication authority, so it hands over the window it holds and the cards it
      // has already shown. That also means turns written while in one-shot mode simply catch
      // up when the connection opens, instead of being a second kind of turn.
      const restore = useApp.getState().liveContext.turns;
      sock.config({
        ...policy,
        turns: restore.map((turn) => ({
          speaker: useApp.getState().liveContext.roles.find((r) => r.id === turn.roleId)?.name ?? "",
          text: turn.text,
          role: wireRole(useApp.getState().liveContext.roles, turn.roleId),
        })),
        already_shown: alreadyShown(),
      });
      log("out", "config", `restore ${restore.length} turns`);
      if (restore.some((turn) => !turn.sent)) {
        setLiveContext({ turns: restore.map((turn) => ({ ...turn, sent: true })) });
      }
    };
    open();
    return () => {
      sock.close();
      if (sockRef.current === sock) sockRef.current = null;
      setReady(null);
      setStatus("closed");
    };
    // `policy` is applied live below; re-running this effect on every knob would reconnect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, currentUser, focus !== null]);

  // The knobs stay live while connected: each change pushes config and the server answers with
  // a fresh ready frame.
  const policyKey = JSON.stringify(policy);
  useEffect(() => {
    if (mode === "stream" && status === "open") {
      sockRef.current?.config(JSON.parse(policyKey));
      log("out", "config", "policy changed");
    }
  }, [policyKey, status, mode, log]);

  useEffect(() => () => abortRef.current?.abort(), []);

  /* ------------------------------------------------------------------ the composer */

  const [draft, setDraft] = useState("");

  const sendTurn = useCallback(() => {
    const text = draft.trim();
    if (!text) return;
    const roleId = activeRoleId;
    const sock = sockRef.current;
    const pushed = mode === "stream" && !!sock?.ready;
    const id = nextId();
    applyTurns({ type: "append", id, roleId, text, at: Date.now(), sent: pushed });
    if (pushed) {
      const role = roles.find((r) => r.id === roleId);
      sock!.turn({
        speaker: role?.name ?? "",
        text,
        role: wireRole(roles, roleId),
      });
      setCounts((c) => ({ ...c, turnsSent: c.turnsSent + 1 }));
      log("out", "turn", text.slice(0, 40));
    }
    setDraft("");
  }, [draft, activeRoleId, mode, roles, applyTurns, log]);

  const evaluate = useCallback(async () => {
    if (!currentUser || !focus || turns.length === 0) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setBusy(true);
    setError(null);
    log("out", "stream", `${turns.length} turns`);
    await liveContextStream(
      currentUser,
      {
        turns: turns.map((turn) => ({
          speaker: roles.find((r) => r.id === turn.roleId)?.name ?? "",
          text: turn.text,
          role: wireRole(roles, turn.roleId),
        })),
        focus,
        min_confidence: knobs.min_confidence,
        max_pending_turns: knobs.max_pending_turns,
        // The one-shot transport clamps this exactly as the socket does, so the toggle in
        // the config strip means the same thing in both modes rather than silently doing
        // nothing in one of them.
        web_search: webSearchOn,
        already_shown: alreadyShown(),
      },
      {
        onSuggestion: (suggestion) => {
          log("in", "suggestion", suggestion.title);
          // One-shot has no evaluation sequence — `null` says so rather than inventing a 0.
          offer(suggestion, null);
        },
        onDone: (done) => {
          setCounts((c) => ({ ...c, evaluations: c.evaluations + 1 }));
          log("in", "done", `${done.count} delivered`);
          // One-shot has no seq to upgrade into, so its provisional card settles on the
          // event the stream ALWAYS ends with. Same rule as the socket's `upgrade`: the
          // tick that promised to fill this card in has finished, one way or another, and
          // the badge stops saying otherwise.
          setQueue((q) => upgradeCard(q, null, null));
          // The SSE `done` frame carries the same gate counters the socket's `stats` does, so
          // it lands in the same ledger — one place to read "why did nothing fire", whichever
          // transport asked.
          setStatsLog((l) =>
            [
              {
                ...done,
                type: "stats" as const,
                seq: l.length,
                focus: done.focus,
                delivered: done.count,
                token_usage: done.token_usage,
              },
              ...l,
            ].slice(0, 8),
          );
        },
        onError: (m) => {
          // The stream's OTHER ending. A failed one-shot settles its provisional card too:
          // the card stands as what it is, and the failure is reported beside it rather
          // than inside it.
          setQueue((q) => upgradeCard(q, null, null));
          if (!ac.signal.aborted) setError(m);
        },
      },
      ac.signal,
    );
    if (abortRef.current === ac) setBusy(false);
  }, [currentUser, focus, turns, roles, knobs, webSearchOn, alreadyShown, offer, log]);

  /* ---------------------------------------------------------------------- citations */

  const cited = useMemo(() => {
    const ids = new Set<string>();
    const each = (s: ContextSuggestion) => s.citations.forEach((c) => ids.add(c.source_id));
    if (queue.current) each(queue.current.suggestion);
    queue.queue.forEach((c) => each(c.suggestion));
    queue.history.forEach((h) => each(h.suggestion));
    Object.values(details).forEach((d) => d.citations.forEach((c) => ids.add(c.source_id)));
    return [...ids];
  }, [queue, details]);
  const { titles } = useSourceTitles(currentUser, cited);

  const jumpToCitation = useCallback(
    (c: CitationEntry) =>
      focusSource(
        c.sourceId,
        c.blockStart != null ? { start: c.blockStart, end: c.blockEnd ?? c.blockStart } : null,
      ),
    [focusSource],
  );

  /* ------------------------------------------------------------------- bubble verbs */

  const currentId = queue.current?.id ?? null;

  const wantMore = useCallback(() => {
    const card = queue.current;
    if (!card) return;
    // Pinning first, and unconditionally: it is what stops the countdown, and a card that
    // expired while its own expansion was in flight would deliver the answer to nobody.
    setQueue((q) => pinCard(q));
    const sock = sockRef.current;
    if (mode !== "stream" || !sock?.ready) return;
    const ref = nextId();
    refToCard.current.set(ref, card.id);
    sock.wantMore(card.suggestion, ref);
    log("out", "want_more", card.suggestion.title);
    setFailures((f) => {
      if (!(card.id in f)) return f;
      const { [card.id]: _gone, ...rest } = f;
      return rest;
    });
    setPendingIds((p) => (p.includes(card.id) ? p : [...p, card.id]));
  }, [queue.current, mode, log]);

  const dismiss = useCallback(() => setQueue((q) => dismissCard(q, Date.now())), []);

  /* ---------------------------------------------------------------- clearing it all */

  /** Everything the page holds about this conversation, as one value. Read during render so
   * the clear button can ask ONE question — is anything still there — instead of carrying a
   * list of conditions that a new store would silently fall out of. */
  const surface: SuggestionSurface<WireEvent, LiveContextStatsFrame, SuggestionDetailFrame> = {
    queue,
    seen: seenRef.current,
    counts,
    wire: wireLog,
    stats: statsLog,
    details,
    pending: pendingIds,
    failures,
  };

  /**
   * 「清空对话」 — end to end, or it is a lie.
   *
   * The turns go, every store the conversation filled goes, and the SERVER session that has
   * been reading it is reset too. The last of those is the one that was missing: the client
   * is the dedup authority, so a clear that emptied only this side left the server holding
   * the subject ledger, the context tail and the mined list of a conversation nobody could
   * see any more — and the next mention of a subject from before the clear came back skipped
   * as `already_mined`, against a card that no longer existed on this screen.
   *
   * One-shot has no session to reset: it carries the whole window on every call, so a
   * cleared client already IS a cleared conversation there.
   */
  const clearConversation = useCallback(() => {
    const cleared = emptySurface<WireEvent, LiveContextStatsFrame, SuggestionDetailFrame>();
    clearTurns();
    setQueue(cleared.queue);
    seenRef.current = cleared.seen;
    setCounts(cleared.counts);
    setWireLog(cleared.wire);
    setStatsLog(cleared.stats);
    setDetails(cleared.details);
    setPendingIds(cleared.pending);
    setFailures(cleared.failures);
    refToCard.current.clear();
    setError(null);
    if (mode === "stream" && sockRef.current?.ready) {
      sockRef.current.reset();
      log("out", "reset", "session cleared");
    }
  }, [clearTurns, mode, log]);

  /* ---------------------------------------------------------------------- rendering */

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

  const transportLabel =
    mode === "stream"
      ? status === "open"
        ? t("liveContext.transport.open")
        : status === "connecting"
          ? t("liveContext.transport.connecting")
          : t("liveContext.transport.closed")
      : t("liveContext.summary.oneshot");

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3">
      {/* ---------------------------------------------------------------- config */}
      <section className="shrink-0 rounded-2 border border-line bg-surface">
        <button
          type="button"
          onClick={() => setConfigOpen((o) => !o)}
          aria-expanded={configOpen}
          data-testid="live-context-config-toggle"
          className="flex w-full items-center gap-3 px-3 py-2 text-left transition-colors hover:bg-hover"
        >
          <ChevronDown
            size={14}
            aria-hidden
            className={cn("shrink-0 text-ink-3 transition-transform", configOpen && "rotate-180")}
          />
          <span className="text-13 font-medium text-ink">{t("liveContext.config.title")}</span>
          {/* The collapsed summary: everything that changes what the server will do, in one
              line, so the panel does not have to be open to be trusted. */}
          <span className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-3 gap-y-1 text-12 text-ink-3">
            <span className="inline-flex items-center gap-1.5">
              <span
                aria-hidden
                className={cn(
                  "inline-block size-1.5 rounded-full",
                  mode === "stream"
                    ? status === "open"
                      ? "bg-ok"
                      : status === "connecting"
                        ? "bg-accent"
                        : "bg-ink-3"
                    : "bg-ink-3",
                )}
              />
              {transportLabel}
            </span>
            <Mono>focus {focus ?? "…"}</Mono>
            <span>
              {density
                ? t(`liveContext.density.${density}.label` as const)
                : t("liveContext.density.custom.label")}
            </span>
            <Mono>
              {t("liveContext.density.summary", {
                confidence: knobs.min_confidence,
                quiet: knobs.quiet_period,
                turns: knobs.max_pending_turns,
              })}
            </Mono>
            <span>{ready ? t("liveContext.summary.acked") : t("liveContext.summary.notAcked")}</span>
          </span>
        </button>

        {configOpen && (
          <div className="grid gap-4 border-t border-line px-3 py-3 sm:grid-cols-2">
            <div className="flex flex-col gap-3">
              <div>
                <p className="mb-1.5 text-12 text-ink-2">{t("liveContext.config.mode")}</p>
                <SegmentedControl
                  size="sm"
                  aria-label={t("liveContext.config.mode")}
                  value={mode}
                  onChange={(v) => setLiveContext({ mode: v as ChatMode })}
                  options={[
                    { value: "oneshot", label: t("liveContext.mode.oneshot") },
                    { value: "stream", label: t("liveContext.mode.stream") },
                  ]}
                />
                <p className="mt-1.5 text-11 text-ink-3">
                  {mode === "oneshot"
                    ? t("liveContext.mode.oneshotHint")
                    : t("liveContext.mode.streamHint")}
                </p>
              </div>
              <Select
                label={t("liveContext.focus.label")}
                value={focus}
                onChange={setFocus}
                options={focusOptions(focuses, t, tOr)}
                placeholder={t("liveContext.focus.loading")}
                disabled={focuses.length === 0}
                hint={focusHint(focuses, focus, tOr)}
              />
            </div>
            <div className="flex flex-col gap-3">
              <div>
                <p className="mb-1.5 text-12 text-ink-2">{t("liveContext.density.label")}</p>
                {/* Three postures, not four number fields. "What IS a good max_pending_turns"
                    is a question nobody can answer in the abstract; "do you want more
                    suggestions or fewer interruptions" is one everybody can. */}
                <div className="flex flex-wrap gap-1.5" role="group" aria-label={t("liveContext.density.label")}>
                  {DENSITY_PRESETS.map((preset) => (
                    <button
                      key={preset.key}
                      type="button"
                      aria-pressed={density === preset.key}
                      onClick={() => setKnobs({ ...preset.values })}
                      className={cn(
                        "rounded-full border px-3 py-1 text-12 transition-colors",
                        density === preset.key
                          ? "border-accent-line bg-accent-soft text-accent"
                          : "border-line text-ink-2 hover:border-line-2",
                      )}
                    >
                      {t(`liveContext.density.${preset.key}.label` as const)}
                    </button>
                  ))}
                  {density === null && (
                    // Not a choice — a report. Somebody's own numbers arrived, and snapping
                    // them to the nearest preset would change their policy under them.
                    <span className="rounded-full border border-dashed border-line px-3 py-1 text-12 text-ink-3">
                      {t("liveContext.density.custom.label")}
                    </span>
                  )}
                </div>
                <p className="mt-1.5 text-11 text-ink-3">
                  {density
                    ? t(`liveContext.density.${density}.hint` as const)
                    : t("liveContext.density.custom.hint")}
                </p>
                <p className="mt-1 text-11 text-ink-3">
                  <Mono>
                    {t("liveContext.density.summary", {
                      confidence: knobs.min_confidence,
                      quiet: knobs.quiet_period,
                      turns: knobs.max_pending_turns,
                    })}
                  </Mono>
                </p>
              </div>
              <div>
                <Switch
                  checked={webSearchOn}
                  onCheckedChange={setWebSearchOn}
                  label={t("liveContext.config.webSearch.label")}
                  hint={t("liveContext.config.webSearch.hint")}
                />
                {/* The deployment's answer, shown only when it contradicts the request.
                    Silence otherwise: a toggle that explained itself on every render would
                    be noise, and a request that was refused with no sign of it would be a
                    lie by omission. */}
                {webSearchOn && webSearchGranted === false && (
                  <p className="mt-1 text-12 text-warn">
                    {t("liveContext.config.webSearch.refused")}
                  </p>
                )}
              </div>
              {mode === "stream" && (
                <Switch
                  checked={statsOn}
                  onCheckedChange={setStatsOn}
                  label={t("liveContext.config.stats.label")}
                  hint={t("liveContext.config.stats.hint")}
                />
              )}
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={clearConversation}
                  disabled={turns.length === 0 && surfaceIsEmpty(surface)}
                >
                  <Trash2 size={13} aria-hidden /> {t("liveContext.config.clearTurns")}
                </Button>
                {mode === "stream" && (
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={status !== "open"}
                    title={t("liveContext.config.flushTitle")}
                    onClick={() => {
                      sockRef.current?.flush();
                      log("out", "flush");
                    }}
                  >
                    <Plug size={13} aria-hidden /> {t("liveContext.config.flush")}
                  </Button>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {vocabError && (
        <Callout tone="warn" className="shrink-0">
          {t("liveContext.vocabError", { detail: vocabError })}
        </Callout>
      )}
      {error && (
        <Callout tone="danger" className="shrink-0" onDismiss={() => setError(null)}>
          {error}
        </Callout>
      )}

      {/* ------------------------------------------------------- the two live panes */}
      <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <ChatPanel
          mode={mode}
          roles={roles}
          activeRoleId={activeRoleId}
          turns={turns}
          draft={draft}
          busy={busy}
          canSend={status === "open"}
          onDraftChange={setDraft}
          onSend={sendTurn}
          onEvaluate={() => void evaluate()}
          onEditTurn={(id, text) => applyTurns({ type: "edit", id, text, mode })}
          onDeleteTurn={(id) => applyTurns({ type: "delete", id, mode })}
          onActivateRole={(id) => applyRoles({ type: "activate", id })}
          onAddRole={(name) => applyRoles({ type: "add", id: nextId(), name })}
          onRenameRole={(id, name) => applyRoles({ type: "rename", id, name })}
          onRecolourRole={(id, colour: RoleColour) => applyRoles({ type: "recolour", id, colour })}
          onRemoveRole={(id) => applyRoles({ type: "remove", id })}
        />

        <SuggestionPanel
          queue={queue}
          now={now}
          kindLabel={(kind) => tOr(`enum.suggestionKind.${kind}.label`, kindLabels[kind] ?? kind)}
          titles={titles}
          onJump={jumpToCitation}
          onWantMore={wantMore}
          onDismiss={dismiss}
          canExpand={mode === "stream" && status === "open"}
          pending={currentId !== null && pendingIds.includes(currentId)}
          detail={currentId ? details[currentId] : undefined}
          failure={currentId ? failures[currentId] : undefined}
          details={details}
          statsLog={statsLog}
          wireLog={wireLog}
          counts={counts}
          ready={ready}
          tab={tab}
          onTabChange={setTab}
        />
      </div>
    </div>
  );
}
