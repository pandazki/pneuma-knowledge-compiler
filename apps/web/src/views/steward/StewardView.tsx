/**
 * The Steward view — one conversation with the coding agent that compiles this library.
 *
 * The page is a transcript and a composer, and the transcript is deliberately literal: the
 * Steward's prose as it is written, and every command it ran as a row with the command on the
 * line and its result folded underneath. The console adds nothing the agent did not do and
 * hides nothing it did (docs/design/coding-agent-mode.md §5.6) — so a step keeps the reported command
 * and output verbatim. Status icons disclose exit codes and timing on hover/focus/tap.
 *
 * Three states the page has to be honest about, because each of them is a different truth:
 *
 *   NOT CONFIGURED  this deployment compiles with a model, so there is no Steward to talk to.
 *                   An empty state naming the one line to change, not an error.
 *   EXITED          the harness process is gone. It is NOT restarted behind the Owner's back;
 *                   the page says so and offers to start a new session.
 *   QUEUED          a message typed while a turn is running is held and sent when that turn
 *                   ends. Marked on the message itself, because a message that looks sent and
 *                   is not is the thing this marker exists to prevent.
 *
 * And one thing the page does that is not about the page: when a step that changed the
 * library finishes, it tells the store the library moved, and the history, process and
 * sources views refetch. That is story 2.5f's "the history view moved while the Steward was
 * still typing" — mechanically, `lib/steward.ts` INVALIDATING and `store.libraryChanged`.
 */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Bot, Check, ChevronRight, CircleAlert, CircleMinus, CircleX, Gauge, LoaderCircle, Phone, RotateCcw } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import {
  StewardSocket,
  getCallStatus,
  getStewardStatus,
  type CallStatus,
  type LiveContextSocketStatus,
  type StewardStatus,
} from "@/lib/api";
import {
  clearInvalidations,
  emptyConversation,
  formatDuration,
  ownerSaid,
  reduce,
  usageEntries,
  willQueue,
  type StepItem,
  type StewardFrame,
  type StewardImage,
  type StewardItem,
  type StewardState,
} from "@/lib/steward";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { EmptyState } from "@/ui/EmptyState";
import { Dialog } from "@/ui/Dialog";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { Tooltip } from "@/ui/Tooltip";
import { CallSurface } from "./CallSurface";
import { StewardComposer } from "./StewardComposer";
import { StewardMarkdown } from "./StewardMarkdown";
import { StewardDetails } from "./StewardDetails";

export default function StewardView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const setView = useApp((s) => s.setView);
  const libraryChanged = useApp((s) => s.libraryChanged);
  const viewParams = useApp((s) => s.viewParams);
  const clearViewParams = useApp((s) => s.clearViewParams);

  const [status, setStatus] = useState<StewardStatus | null>(null);
  // The call is its own feature on its own endpoint: an engine that predates it answers 404
  // and this stays null, which is the whole of "the button is not there".
  const [callStatus, setCallStatus] = useState<CallStatus | null>(null);
  const [callOpen, setCallOpen] = useState(false);
  const [callArmed, setCallArmed] = useState(false);
  const [socketState, setSocketState] = useState<LiveContextSocketStatus>("connecting");
  const [conversation, setConversation] = useState<StewardState>(emptyConversation);
  const [draft, setDraft] = useState("");
  const [images, setImages] = useState<StewardImage[]>([]);
  const [zoomed, setZoomed] = useState<StewardImage | null>(null);
  const socketRef = useRef<StewardSocket | null>(null);
  const tailRef = useRef<HTMLDivElement | null>(null);

  // The status read is what draws the page before a socket exists: a deployment with no
  // coding agent must show its empty state without opening one.
  useEffect(() => {
    if (!currentUser) return;
    let live = true;
    getStewardStatus(currentUser)
      .then((s) => live && setStatus(s))
      .catch(() => live && setStatus(null));
    return () => {
      live = false;
    };
  }, [currentUser]);

  // The call does not need the harness — it answers from the library, not from a coding
  // agent — so it is probed on its own and shown whatever the Steward's own state is.
  useEffect(() => {
    if (!currentUser) return;
    let live = true;
    getCallStatus(currentUser)
      .then((s) => live && setCallStatus(s))
      .catch(() => live && setCallStatus(null));
    return () => {
      live = false;
    };
  }, [currentUser]);

  /**
   * `#/steward?call=1` opens the call surface with the Start button focused — and stops
   * there. A call costs money by the minute, so an address may set one up and may never
   * start one: the gesture stays the Owner's. The parameter is read once and dropped.
   */
  useEffect(() => {
    if (viewParams.call !== "1") return;
    setCallOpen(true);
    setCallArmed(true);
    clearViewParams();
  }, [viewParams.call, clearViewParams]);

  useEffect(() => {
    if (!currentUser || status == null || !status.configured) return;
    setConversation(emptyConversation());
    const socket = new StewardSocket(
      currentUser,
      (frame) => setConversation((c) => reduce(c, frame as StewardFrame)),
      (s) => setSocketState(s),
    );
    socketRef.current = socket;
    return () => {
      socketRef.current = null;
      socket.close();
    };
  }, [currentUser, status?.configured]);

  // The library moved: the ledger, the catalogue and the canonical views refetch, and the
  // Owner is not asked to reload anything.
  useEffect(() => {
    if (conversation.invalidations.length === 0) return;
    libraryChanged();
    setConversation((c) => clearInvalidations(c));
  }, [conversation.invalidations, libraryChanged]);

  useEffect(() => {
    tailRef.current?.scrollIntoView({ block: "end" });
  }, [conversation.seq]);

  const send = useCallback(() => {
    const text = draft.trim();
    if ((!text && images.length === 0) || !socketRef.current) return;
    socketRef.current.say(text, images);
    setConversation((c) => ownerSaid(c, text, images));
    setDraft("");
    setImages([]);
  }, [draft, images]);

  const restart = useCallback(() => {
    socketRef.current?.startAgain();
    setConversation(emptyConversation());
    setImages([]);
  }, []);

  const endSession = useCallback(() => {
    socketRef.current?.end();
  }, []);

  // The call surface is open only where there is something to call: a null status is an
  // engine that never promised the feature, and an unconfigured one says why on the button.
  const showCall = callOpen && callStatus?.configured === true && currentUser != null;

  const header = (
    <PageHeader
      title={t("steward.title")}
      description={t("steward.description")}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {status?.configured && (
            <>
              <Badge
                tone={conversation.exited ? "warn" : socketState === "open" ? "ok" : "neutral"}
              >
                {conversation.exited
                  ? t("steward.status.exited")
                  : socketState === "open"
                    ? t("steward.status.live")
                    : socketState === "connecting"
                      ? t("steward.status.connecting")
                      : t("steward.status.closed")}
              </Badge>
              <Tooltip content={t("steward.status.backend", {
                label: status.label || status.backend, protocol: status.protocol,
              })}>
                <span tabIndex={0} className="rounded-1 text-12 text-ink-2">
                  {status.label || status.backend}
                </span>
              </Tooltip>
            </>
          )}
          {/* The call stands beside the text session whatever the Steward's own state is:
              it answers from the library and needs no harness at all. */}
          {callStatus != null && !showCall && (
            <CallButton
              status={callStatus}
              onOpen={() => {
                setCallOpen(true);
                setCallArmed(false);
              }}
            />
          )}
          {status?.configured && !conversation.exited && (
            <Button size="sm" variant="ghost" onClick={endSession}>
              {t("steward.end")}
            </Button>
          )}
        </div>
      }
    />
  );

  if (showCall) {
    return (
      <div className="flex h-full min-h-0 flex-col">
        {header}
        <CallSurface
          userId={currentUser}
          status={callStatus}
          armed={callArmed}
          onBack={() => {
            setCallOpen(false);
            setCallArmed(false);
          }}
        />
      </div>
    );
  }

  if (status != null && !status.configured) {
    return (
      <div className="flex min-h-0 flex-col">
        {header}
        <EmptyState
          icon={Bot}
          title={t("steward.empty.title")}
          description={
            <>
              {t("steward.empty.body")}
              <br />
              <span className="text-ink-3">
                {t("steward.empty.detail", { detail: status.spec || status.backend || "—" })}
              </span>
            </>
          }
          action={
            <Button size="sm" onClick={() => setView("engine_console")}>
              {t("steward.empty.engine")}
            </Button>
          }
        />
      </div>
    );
  }

  const notConfigured = conversation.notConfigured;

  return (
    <div className="flex h-full min-h-0 flex-col">
      {header}
      {notConfigured !== "" && (
        <Callout tone="warn" title={t("steward.empty.title")} className="mb-4">
          {t("steward.empty.detail", { detail: notConfigured })}
        </Callout>
      )}
      <ScrollRegion className="min-h-0 flex-1">
        <ol className="flex flex-col gap-3 pr-2">
          {conversation.items.map((item) => (
            <li key={item.id}>
              <ConversationItem item={item} onZoomImage={setZoomed} />
            </li>
          ))}
          {conversation.busy && !conversation.exited && (
            <li>
              <WorkingNote />
            </li>
          )}
        </ol>
        {conversation.exited && (
          <Callout tone="warn" title={t("steward.exited.title")} className="mt-4">
            <p>{t("steward.exited.body", { code: String(conversation.exitCode ?? 0) })}</p>
            <div className="mt-2">
              <Button size="sm" onClick={restart}>
                <RotateCcw size={14} aria-hidden />
                {t("steward.exited.restart")}
              </Button>
            </div>
          </Callout>
        )}
        <div ref={tailRef} />
      </ScrollRegion>
      <div className="mt-3 border-t border-line pt-3">
        <StewardComposer
          draft={draft}
          onDraftChange={setDraft}
          images={images}
          onImagesChange={setImages}
          onSend={send}
          disabled={conversation.exited}
          queueing={willQueue(conversation, draft, images.length)}
          working={conversation.busy}
        />
      </div>
      <Dialog
        open={zoomed != null}
        onOpenChange={(open) => !open && setZoomed(null)}
        title={zoomed?.name ?? ""}
        contentClassName="max-w-3xl"
      >
        {zoomed != null && (
          <img
            src={zoomed.dataUrl}
            alt={zoomed.name}
            className="max-h-[70vh] w-full rounded-2 border border-line object-contain"
          />
        )}
      </Dialog>
    </div>
  );
}

/**
 * The turn in flight, said on the Steward's own side of the page.
 *
 * It sits where the next sentence will appear, because that is the thing being waited for.
 * The dot's pulse collapses to nothing under prefers-reduced-motion (index.css, hard rule 9).
 */
function WorkingNote() {
  const t = useT();
  return (
    <p className="flex items-center gap-2 text-12 text-ink-3" aria-live="polite">
      <span
        aria-hidden
        className="size-1.5 shrink-0 animate-pulse rounded-full bg-accent"
      />
      {t("steward.compose.working")}
    </p>
  );
}

/**
 * The way into a call, beside the text session.
 *
 * Disabled rather than hidden when the engine cannot place one: the Owner is told what is
 * missing in the engine's own sentence, which is more use than a control that quietly is not
 * there. The tooltip hangs on a focusable wrapper, because a disabled button receives neither
 * pointer nor keyboard events and would carry its explanation where nobody can reach it.
 */
function CallButton({ status, onOpen }: { status: CallStatus; onOpen: () => void }) {
  const t = useT();
  if (status.configured) {
    return (
      <Button size="sm" variant="ghost" onClick={onOpen}>
        <Phone size={14} aria-hidden />
        {t("call.open")}
      </Button>
    );
  }
  const why = status.detail || t("call.open.unavailable");
  return (
    <Tooltip content={why}>
      <span tabIndex={0} className="inline-flex rounded-2" aria-label={why}>
        <Button size="sm" variant="ghost" disabled>
          <Phone size={14} aria-hidden />
          {t("call.open")}
        </Button>
      </span>
    </Tooltip>
  );
}

function ConversationItem({
  item,
  onZoomImage,
}: {
  item: StewardItem;
  onZoomImage: (image: StewardImage) => void;
}) {
  const t = useT();
  if (item.kind === "owner") {
    return (
      <div className="rounded-2 border border-accent-line bg-accent-soft px-3 py-2">
        <p className="text-12 font-medium text-accent">{t("steward.item.owner")}</p>
        {/* The Owner's words, verbatim: plain text with the line breaks kept. */}
        {item.text !== "" && <p className="whitespace-pre-wrap text-14 text-ink">{item.text}</p>}
        {item.images.length > 0 && (
          <ul className="mt-2 flex flex-wrap gap-2">
            {item.images.map((image, index) => (
              <li key={`${image.name}:${index}`}>
                <button
                  type="button"
                  title={image.name}
                  aria-label={t("steward.item.openImage", { name: image.name })}
                  onClick={() => onZoomImage(image)}
                  className="block rounded-2"
                >
                  <img
                    src={image.dataUrl}
                    alt={image.name}
                    className="size-16 rounded-2 border border-accent-line object-cover"
                  />
                </button>
              </li>
            ))}
          </ul>
        )}
        {item.queued && <p className="mt-1 text-12 text-ink-3">{t("steward.item.queued")}</p>}
      </div>
    );
  }
  if (item.kind === "text") {
    return <StewardMarkdown text={item.text} />;
  }
  if (item.kind === "usage") {
    const entries = usageEntries(item.usage);
    const hasDetails = entries.length > 0 || item.costUsd != null || item.durationMs > 0;
    if (!hasDetails && !item.error) return null;
    return (
      <div className="flex items-start gap-2">
        {item.error !== "" && (
          <p role="alert" className="flex-1 text-12 text-danger">
            {t("steward.item.turnError", { error: item.error })}
          </p>
        )}
        {hasDetails && (
          <StewardDetails align="start" label={t("steward.item.usageDetails")} icon={<Gauge size={14} aria-hidden />}>
            <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-6 gap-y-1 tabular-nums">
              {entries.map(([key, value]) => (
                <div key={key} className="contents">
                  <dt className="text-ink-2">{usageLabel(key, t)}</dt>
                  <dd className="text-right">{value.toLocaleString()}</dd>
                </div>
              ))}
              {item.costUsd != null && <><dt>{t("steward.item.costLabel")}</dt><dd className="text-right">${item.costUsd.toFixed(4)}</dd></>}
              {item.durationMs > 0 && <><dt>{t("steward.item.duration")}</dt><dd className="text-right">{formatDuration(item.durationMs)}</dd></>}
            </dl>
          </StewardDetails>
        )}
      </div>
    );
  }

  if (item.kind === "notice") {
    return (
      <p className="text-12 text-ink-3">
        <Mono>{item.code}</Mono> {item.detail}
      </p>
    );
  }
  return <StepRow step={item} />;
}

/** Harness field names are transport details; unknown metrics stay inspectable. */
function usageLabel(key: string, t: ReturnType<typeof useT>): string {
  const labels: Record<string, "input" | "output" | "cached" | "cacheWrite" | "reasoning" | "total"> = {
    inputtokens: "input", outputtokens: "output", cachedinputtokens: "cached",
    cachereadtokens: "cached", cachewritetokens: "cacheWrite", cachecreationinputtokens: "cacheWrite",
    reasoningoutputtokens: "reasoning", reasoningtokens: "reasoning", totaltokens: "total",
  };
  const label = labels[key.replaceAll("_", "").toLowerCase()];
  return label ? t(`steward.usage.${label}`) : key;
}

/** One command the Steward ran, with output and diagnostic details disclosed separately. */
function StepRow({ step }: { step: StepItem }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const outputId = useId();
  const detail = useMemo(() => step.output.trimEnd(), [step.output]);
  const state = step.stopped ? "stoppedShort" : step.failed ? "failed" : step.running ? "running" : step.exitCode === 0 ? "succeeded" : "finished";
  const label = t(`steward.item.${state}`);
  const Icon = step.stopped ? CircleMinus : step.failed ? CircleX : step.running ? LoaderCircle : step.exitCode === 0 ? Check : CircleAlert;
  return (
    <div className="border-b border-line">
      <div className="flex items-center gap-1">
        <button type="button" aria-expanded={open} aria-controls={outputId}
          className="flex min-w-0 flex-1 items-center gap-2 rounded-1 px-1 py-1.5 text-left hover:bg-hover"
          onClick={() => setOpen((value) => !value)}>
          <ChevronRight size={14} aria-hidden className={`shrink-0 text-ink-2 transition-transform ${open ? "rotate-90" : ""}`} />
          <Mono className="min-w-0 flex-1 truncate text-13 text-ink-2">{step.command}</Mono>
        </button>
        <StewardDetails label={label}
          className={step.failed || step.stopped ? "text-danger" : "text-ink-2"}
          icon={<Icon size={14} aria-hidden className={step.running ? "animate-spin" : undefined} />}>
          <div className="flex flex-col gap-1">
            {step.exitCode != null && <p>{t("steward.item.exit", { code: String(step.exitCode) })}</p>}
            {step.durationMs > 0 && <p>{t("steward.item.duration")}: {formatDuration(step.durationMs)}</p>}
          </div>
        </StewardDetails>
      </div>
      {open && (
        <div id={outputId} className="px-6 pb-3 pt-1">
          {step.stopped && <p className="mb-2 text-12 text-danger">{t("steward.item.stopped")}</p>}
          <pre className="mb-2 overflow-auto whitespace-pre-wrap break-words font-mono text-12 text-ink">{step.command}</pre>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words font-mono text-12 text-ink-2">
            {detail || t("steward.item.noOutput")}
          </pre>
        </div>
      )}
    </div>
  );
}
