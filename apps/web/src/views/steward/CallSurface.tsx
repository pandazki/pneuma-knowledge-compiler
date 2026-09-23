/**
 * The call surface: a voice conversation with the library, in the Steward's own column.
 *
 * It takes the chat's place rather than floating over it, because a call is not a panel
 * beside a session — it IS the session for as long as it lasts, and the way back out is one
 * control that also ends it. Nothing here starts on its own: a session is billed by the
 * minute, so the only road to `CallSession.start()` is the Owner's click, and leaving this
 * surface (Back, a view change, the tab closing) hangs up properly rather than leaving a
 * microphone open on a page nobody is looking at.
 *
 * The page is read left to right and that order is the argument: the captions are what was
 * SAID, and the cards to their right are what the LIBRARY answered. A stretch of speech the
 * library did not supply is marked as the voice model's own, and one it did carries the
 * card's ordinal and jumps to it — so the reader is never left guessing which of the two they
 * just heard. The arithmetic behind both marks is `lib/call.ts`; this file only draws it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ArrowLeft, AudioLines, BookOpen, ChevronDown, Info, LoaderCircle, Mic, MicOff, Phone, PhoneOff, Volume2 } from "lucide-react";
import {
  captionMarks,
  emptyCall,
  formatCost,
  formatElapsed,
  isCallLive,
  ordinalBadge,
  reduce,
  type CallEvent,
  type CallState,
} from "@/lib/call";
import { CallSession } from "@/lib/callSession";
import type { CallStatus } from "@/lib/api";
import { recallSourceIds } from "@/lib/sourceTitles";
import { useApp } from "@/lib/store";
import { useLocale, useT } from "@/lib/useT";
import type { MessageKey } from "@/lib/i18n";
import type { CitationEntry } from "@/components/CitationList";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { IconButton } from "@/ui/IconButton";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";
import { useSourceTitles } from "../_shared/useSourceTitles";
import { CallAnswerCard, asRecallAnswer } from "./CallAnswerCard";
import { StewardDetails } from "./StewardDetails";

const PHASE_KEYS: Record<CallState["status"], MessageKey> = {
  idle: "call.phase.idle",
  "asking-mic": "call.phase.askingMic",
  connecting: "call.phase.connecting",
  live: "call.phase.live",
  ending: "call.phase.ending",
  ended: "call.phase.ended",
  failed: "call.phase.failed",
};

/** Above this share of the voice session's context window, the gauge is worth showing. */
const CONTEXT_VISIBLE_AT = 0.5;

/** Close enough to the foot of a scroll region to count as reading the latest. */
const AT_BOTTOM_PX = 48;

export function CallSurface({
  userId,
  status,
  armed,
  onBack,
}: {
  userId: string;
  status: CallStatus;
  /** Arrived at through `#/steward?call=1`: the Start button takes focus, and nothing else. */
  armed: boolean;
  onBack: () => void;
}) {
  const t = useT();
  const locale = useLocale();
  const focusSource = useApp((s) => s.focusSource);

  const [call, setCall] = useState<CallState>(emptyCall);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [localSeconds, setLocalSeconds] = useState(0);
  const [openCard, setOpenCard] = useState("");
  const sessionRef = useRef<CallSession | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const startRef = useRef<HTMLButtonElement | null>(null);

  const onEvent = useCallback((event: CallEvent) => setCall((s) => reduce(s, event)), []);

  const play = useCallback((stream: MediaStream) => {
    const el = audioRef.current;
    if (!el) return;
    el.srcObject = stream;
    // Autoplay with sound is refused on a page the browser has not seen interacted with;
    // that refusal is a state with an affordance, not an error to swallow.
    el.play().then(
      () => setAudioBlocked(false),
      () => setAudioBlocked(true),
    );
  }, []);

  const begin = useCallback(() => {
    if (sessionRef.current) return;
    setLocalSeconds(0);
    setAudioBlocked(false);
    const session = new CallSession(userId, locale, { onEvent, onRemoteStream: play });
    sessionRef.current = session;
    void session.start();
  }, [locale, onEvent, play, userId]);

  const hangUp = useCallback(() => sessionRef.current?.end(), []);

  // A finished session is not reusable: releasing it here is what makes "call again" a NEW
  // call rather than a second start on a peer connection that is already closed.
  useEffect(() => {
    if (call.status === "ended" || call.status === "failed") sessionRef.current = null;
  }, [call.status]);

  // Leaving the surface ends the call. The cleanup runs on Back, on a view change and on an
  // unmount alike, which is the whole of "an in-progress call keeps running only while the
  // surface is open".
  useEffect(
    () => () => {
      sessionRef.current?.hangUpNow();
      sessionRef.current = null;
    },
    [],
  );

  // The tab is going away: both goodbyes go out best-effort, because there is no later.
  useEffect(() => {
    const onHide = () => sessionRef.current?.hangUpNow();
    window.addEventListener("pagehide", onHide);
    return () => window.removeEventListener("pagehide", onHide);
  }, []);

  useEffect(() => {
    if (armed) startRef.current?.focus();
  }, [armed]);

  // The engine's seconds are the billed truth; the local tick only fills the gap before the
  // first `usage` frame, so the strip never shows a call that has been running for 00:00.
  useEffect(() => {
    if (call.status !== "live" && call.status !== "ending") return;
    const timer = setInterval(() => setLocalSeconds((n) => n + 1), 1000);
    return () => clearInterval(timer);
  }, [call.status]);

  const elapsed = call.seconds > 0 ? call.seconds : localSeconds;
  const marks = useMemo(() => captionMarks(call), [call]);
  const live = isCallLive(call);

  const cited = useMemo(() => {
    const ids = new Set<string>();
    for (const delegation of call.delegations) {
      for (const id of recallSourceIds(null, asRecallAnswer(delegation.answer))) ids.add(id);
    }
    return [...ids];
  }, [call.delegations]);
  // The same hook Recall and Ask use: a title is fetched once and looked up the same way on
  // every surface that prints an id it did not itself list.
  const { titles } = useSourceTitles(userId, cited);

  const jumpToCitation = useCallback(
    (c: CitationEntry) =>
      focusSource(
        c.sourceId,
        c.blockStart != null ? { start: c.blockStart, end: c.blockEnd ?? c.blockStart } : null,
      ),
    [focusSource],
  );

  const openTheCard = useCallback((id: string) => {
    setOpenCard(id);
    document.getElementById(`call-card-${id}`)?.scrollIntoView({ block: "nearest" });
  }, []);

  const negotiating = call.status === "asking-mic" || call.status === "connecting";
  const hasTranscript = call.rows.length > 0 || call.delegations.length > 0;
  const retry = call.status === "ended" || call.status === "failed";
  const cancel = () => sessionRef.current?.hangUpNow();
  const phase = call.muted && live ? t("call.muted") : t(PHASE_KEYS[call.status]);
  const errorHint = call.errorCode === "mic_denied" ? t("call.error.micDenied")
    : call.errorCode === "no_microphone" ? t("call.error.noMicrophone") : call.error;

  const controls = (
    <div className={cn("flex shrink-0 flex-col items-center gap-3 py-6", hasTranscript && "border-t border-line")}>
        {audioBlocked && (
          <Button onClick={() => void audioRef.current?.play().then(() => setAudioBlocked(false))}>
            <Volume2 size={16} aria-hidden />{t("call.audioBlocked")}
          </Button>
        )}
        <div className="flex items-center justify-center gap-4">
          {live ? (
            <>
              <Tooltip content={call.muted ? t("call.unmute") : t("call.mute")}>
                <IconButton aria-label={call.muted ? t("call.unmute") : t("call.mute")}
                  aria-pressed={call.muted} disabled={call.status === "ending"}
                  onClick={() => sessionRef.current?.setMuted(!call.muted)}
                  className={cn("size-12 rounded-full border border-line-2", call.muted && "bg-warn-soft text-warn")}>
                  {call.muted ? <MicOff size={20} aria-hidden /> : <Mic size={20} aria-hidden />}
                </IconButton>
              </Tooltip>
              <Button variant="danger" className="h-12 rounded-full px-6" onClick={hangUp} loading={call.status === "ending"}>
                <PhoneOff size={18} aria-hidden />{t("call.end")}
              </Button>
            </>
          ) : negotiating ? (
            <Button className="h-12 px-6" onClick={cancel}>{t("call.cancel")}</Button>
          ) : (
            <Button ref={startRef} variant="primary" className="h-12 gap-3 px-6" onClick={begin}>
              <Phone size={18} aria-hidden />{retry ? t("call.again") : t("call.start")}
            </Button>
          )}
        </div>
        {!live && !negotiating && <p className="max-w-sm text-center text-12 text-ink-2">{t("call.start.note")}</p>}
        {live && <p className="text-12 text-ink-2" aria-live="polite">{call.muted ? t("call.muted") : t("call.micOn")}</p>}
      </div>
  );

  return (
    <div className="flex h-[calc(100dvh-6rem)] min-h-0 flex-col lg:h-full">
      <div className="flex shrink-0 items-center justify-between gap-3 pb-4">
        <Button size="sm" variant="ghost" onClick={onBack}>
          <ArrowLeft size={14} aria-hidden />{t(live || negotiating ? "call.leave" : "call.back")}
        </Button>
        <StewardDetails label={t("call.details")} icon={<Info size={16} aria-hidden />}>
          <div className="flex max-w-64 flex-col gap-2">
            <p>{t("call.model", { model: status.model, voice: status.voice })}</p>
            {elapsed > 0 && <p>{t("call.cost", { cost: formatCost(elapsed) })}</p>}
            {call.contextRatio != null && <p>{t("call.context", { percent: Math.round(call.contextRatio * 100) })}</p>}
            {call.errorCode && <Mono>{call.errorCode}</Mono>}
            {call.closedReason && <p>{t("call.closed", { reason: call.closedReason })}</p>}
          </div>
        </StewardDetails>
      </div>

      {hasTranscript ? (
        <div className="flex shrink-0 flex-wrap items-baseline justify-between gap-2 border-b border-line pb-4">
          <h1 className="font-serif text-24 text-ink">{t("call.title")}</h1>
          <div className="flex items-center gap-3 text-13 text-ink-2">
            <span aria-live="polite">{phase}</span>
            <span className="tabular-nums" aria-label={t("call.elapsed", { time: formatElapsed(elapsed) })}>{formatElapsed(elapsed)}</span>
          </div>
        </div>
      ) : (
        <div className="flex min-h-64 flex-1 flex-col items-center justify-center px-4 py-8 text-center">
          <div className={cn("mb-6 flex size-20 items-center justify-center rounded-full border border-line-2", live && "border-accent-line text-accent", !live && "text-ink-2")}>
            {negotiating ? <LoaderCircle size={30} aria-hidden className="animate-spin" />
              : live ? <AudioLines size={32} aria-hidden /> : <BookOpen size={32} strokeWidth={1.5} aria-hidden />}
          </div>
          <h1 className="font-serif text-30 text-ink">{t("call.title")}</h1>
          <p className="mt-3 max-w-sm text-14 text-ink-2" aria-live="polite">
            {call.status === "idle" ? t("call.description") : live && !call.muted ? t("call.readyToTalk") : phase}
          </p>
          {(live || elapsed > 0) && <p className="mt-4 text-20 tabular-nums text-ink-2">{formatElapsed(elapsed)}</p>}
          {call.error !== "" && <Callout tone="danger" className="mt-5 w-full max-w-sm text-left"><p>{errorHint}</p></Callout>}
          {!live && !negotiating && <div className="mt-3">{controls}</div>}
        </div>
      )}

      {hasTranscript && call.error !== "" && (
        <Callout tone="danger" className="mx-auto my-4 w-full max-w-lg">
          <p>{errorHint}</p>
        </Callout>
      )}
      {call.contextRatio != null && call.contextRatio > CONTEXT_VISIBLE_AT && (
        <p className="my-2 text-center text-12 text-warn">{t("call.context", { percent: Math.round(call.contextRatio * 100) })}</p>
      )}

      {hasTranscript && (
        <div className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_minmax(0,1fr)] gap-6 py-5 lg:grid-rows-1 lg:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
          <CaptionColumn call={call} marks={marks} onOpenCard={openTheCard} />
          <section className="flex min-h-0 flex-col border-t border-line pt-4 lg:border-t-0 lg:border-l lg:pt-0 lg:pl-6">
            <h2 className="text-13 font-medium text-ink-2">{t("call.cards.title")}</h2>
            <ScrollRegion className="mt-3 min-h-0 flex-1">
              {call.delegations.length === 0 ? (
                <p className="max-w-measure text-13 text-ink-2">{t("call.cards.empty")}</p>
              ) : call.delegations.map((delegation, index) => (
                <CallAnswerCard key={delegation.id} delegation={delegation} ordinal={index + 1}
                  titles={titles} onJump={jumpToCitation} highlighted={openCard === delegation.id} />
              ))}
            </ScrollRegion>
          </section>
        </div>
      )}

      {(hasTranscript || live || negotiating) && controls}

      <audio ref={audioRef} autoPlay className="sr-only" />
    </div>
  );
}

/**
 * The captions.
 *
 * Two things here are rules rather than taste. The scroll follows the bottom only while the
 * reader is AT the bottom — scrolling back to re-read a sentence must not be yanked forward
 * by the next fragment — and the provenance mark sits on the row rather than beside the
 * column, because it is a property of those words and not of the conversation.
 */
function CaptionColumn({
  call,
  marks,
  onOpenCard,
}: {
  call: CallState;
  marks: ReturnType<typeof captionMarks>;
  onOpenCard: (id: string) => void;
}) {
  const t = useT();
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [atBottom, setAtBottom] = useState(true);

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight <= AT_BOTTOM_PX);
  }, []);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el || !atBottom) return;
    el.scrollTop = el.scrollHeight;
  }, [call.rows, atBottom]);

  return (
    <section className="relative flex min-h-0 flex-col">
      <h2 className="text-13 font-medium text-ink-2">{t("call.captions.title")}</h2>
      <ScrollRegion ref={scrollerRef} onScroll={onScroll} className="mt-2 min-h-0 flex-1">
        {call.rows.length === 0 ? (
          <p className="max-w-measure text-13 text-ink-3">{t("call.captions.empty")}</p>
        ) : (
          <ol className="flex flex-col gap-3 pr-2">
            {call.rows.map((row) => {
              const mark = marks[row.id];
              return (
                <li key={row.id}>
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-12 text-ink-3">
                      {t(row.speaker === "owner" ? "call.captions.owner" : "call.captions.voice")}
                    </span>
                    {mark != null && mark.ordinal > 0 && (
                      <button
                        type="button"
                        onClick={() => onOpenCard(mark.delegationId)}
                        aria-label={t("call.captions.linked", { index: mark.ordinal })}
                        className="rounded-1 text-12 text-accent"
                      >
                        {ordinalBadge(mark.ordinal)}
                      </button>
                    )}
                    {mark != null && mark.unlinked && (
                      <Tooltip content={t("call.captions.unlinkedHint")}>
                        <span
                          tabIndex={0}
                          className="rounded-1 text-12 text-ink-3 underline decoration-dotted underline-offset-2"
                        >
                          {t("call.captions.unlinked")}
                        </span>
                      </Tooltip>
                    )}
                  </div>
                  <p
                    className={cn(
                      "prose max-w-measure text-14",
                      row.speaker === "owner" ? "text-ink" : "text-ink-2",
                    )}
                  >
                    {row.text}
                  </p>
                </li>
              );
            })}
          </ol>
        )}
      </ScrollRegion>
      {!atBottom && call.rows.length > 0 && (
        <Button
          size="sm"
          className="absolute right-3 bottom-2"
          onClick={() => {
            const el = scrollerRef.current;
            if (!el) return;
            el.scrollTop = el.scrollHeight;
            setAtBottom(true);
          }}
        >
          <ChevronDown size={13} aria-hidden />
          {t("call.captions.latest")}
        </Button>
      )}
    </section>
  );
}
