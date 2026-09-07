/**
 * The Steward view — one conversation with the coding agent that compiles this library.
 *
 * The page is a transcript and a composer, and the transcript is deliberately literal: the
 * Steward's prose as it is written, and every command it ran as a row with the command on the
 * line and its result folded underneath. The console adds nothing the agent did not do and
 * hides nothing it did (docs/design/coding-agent-mode.md §5.6) — so a step shows the command
 * text the harness reported, its exit code and how long it took, and nothing is re-worded.
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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bot, ChevronRight, Plug, RotateCcw, Send, Terminal } from "lucide-react";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import {
  StewardSocket,
  getStewardStatus,
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
  type StepItem,
  type StewardFrame,
  type StewardItem,
  type StewardState,
} from "@/lib/steward";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { TextArea } from "@/ui/TextArea";

export default function StewardView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const setView = useApp((s) => s.setView);
  const libraryChanged = useApp((s) => s.libraryChanged);

  const [status, setStatus] = useState<StewardStatus | null>(null);
  const [socketState, setSocketState] = useState<LiveContextSocketStatus>("connecting");
  const [conversation, setConversation] = useState<StewardState>(emptyConversation);
  const [draft, setDraft] = useState("");
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
    if (!text || !socketRef.current) return;
    socketRef.current.say(text);
    setConversation((c) => ownerSaid(c, text));
    setDraft("");
  }, [draft]);

  const restart = useCallback(() => {
    socketRef.current?.startAgain();
    setConversation(emptyConversation());
  }, []);

  const endSession = useCallback(() => {
    socketRef.current?.end();
  }, []);

  const header = (
    <PageHeader
      title={t("steward.title")}
      description={t("steward.description")}
      actions={
        status?.configured ? (
          <div className="flex items-center gap-2">
            <Badge tone={conversation.exited ? "warn" : socketState === "open" ? "ok" : "neutral"}>
              {conversation.exited
                ? t("steward.status.exited")
                : socketState === "open"
                  ? t("steward.status.live")
                  : socketState === "connecting"
                    ? t("steward.status.connecting")
                    : t("steward.status.closed")}
            </Badge>
            <Badge>
              {t("steward.status.backend", {
                label: status.label || status.backend,
                protocol: status.protocol,
              })}
            </Badge>
            {!conversation.exited && (
              <Button size="sm" variant="ghost" onClick={endSession}>
                {t("steward.end")}
              </Button>
            )}
          </div>
        ) : null
      }
    />
  );

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
              <ConversationItem item={item} />
            </li>
          ))}
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
        {conversation.busy && (
          <p className="mb-1 text-12 text-ink-3">{t("steward.compose.busy")}</p>
        )}
        <div className="flex items-end gap-2">
          <TextArea
            autoRows
            maxRows={6}
            rows={2}
            value={draft}
            disabled={conversation.exited}
            placeholder={t("steward.compose.placeholder")}
            hint={t("steward.compose.hint")}
            wrapperClassName="flex-1"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
          />
          <Button
            variant="primary"
            disabled={conversation.exited || draft.trim() === ""}
            onClick={send}
          >
            <Send size={14} aria-hidden />
            {t("steward.compose.send")}
          </Button>
        </div>
      </div>
    </div>
  );
}

function ConversationItem({ item }: { item: StewardItem }) {
  const t = useT();
  if (item.kind === "owner") {
    return (
      <div className="rounded-2 border border-accent-line bg-accent-soft px-3 py-2">
        <p className="text-12 font-medium text-accent">{t("steward.item.owner")}</p>
        <p className="whitespace-pre-wrap text-14 text-ink">{item.text}</p>
        {item.queued && <p className="mt-1 text-12 text-ink-3">{t("steward.item.queued")}</p>}
      </div>
    );
  }
  if (item.kind === "text") {
    return <p className="whitespace-pre-wrap text-14 text-ink">{item.text}</p>;
  }
  if (item.kind === "usage") {
    const entries = usageEntries(item.usage);
    return (
      <p className="text-12 text-ink-3">
        {item.error !== "" && (
          <span className="text-danger">{t("steward.item.turnError", { error: item.error })} </span>
        )}
        {entries.length > 0 &&
          t("steward.item.usage", {
            usage: entries.map(([k, v]) => `${k} ${v}`).join(" · "),
          })}
        {item.costUsd != null && ` · ${t("steward.item.cost", { cost: item.costUsd.toFixed(4) })}`}
        {item.durationMs > 0 && ` · ${formatDuration(item.durationMs)}`}
      </p>
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

/** One command the Steward ran, with its result folded under it. */
function StepRow({ step }: { step: StepItem }) {
  const t = useT();
  const [open, setOpen] = useState(false);
  const tone = step.stopped ? "danger" : step.failed ? "warn" : step.running ? "neutral" : "ok";
  const detail = useMemo(() => step.output.trimEnd(), [step.output]);
  return (
    <div className="rounded-2 border border-line-2 bg-surface">
      <button
        type="button"
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((o) => !o)}
      >
        <ChevronRight
          size={14}
          aria-hidden
          className={`shrink-0 text-ink-3 transition-transform ${open ? "rotate-90" : ""}`}
        />
        {step.tool === "permission" ? (
          <Plug size={14} aria-hidden className="shrink-0 text-danger" />
        ) : (
          <Terminal size={14} aria-hidden className="shrink-0 text-ink-3" />
        )}
        <Mono className="min-w-0 flex-1 truncate text-13 text-ink">{step.command}</Mono>
        {step.running ? (
          <Badge tone="neutral">{t("steward.item.running")}</Badge>
        ) : (
          <>
            {step.exitCode != null && (
              <Badge tone={tone}>{t("steward.item.exit", { code: String(step.exitCode) })}</Badge>
            )}
            {step.durationMs > 0 && (
              <span className="text-12 text-ink-3">{formatDuration(step.durationMs)}</span>
            )}
          </>
        )}
      </button>
      {open && (
        <div className="border-t border-line-2 px-3 py-2">
          {step.stopped && <p className="mb-1 text-12 text-danger">{t("steward.item.stopped")}</p>}
          <p className="mb-1 text-12 text-ink-3">{t("steward.item.output")}</p>
          <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-mono text-12 text-ink-2">
            {detail || t("steward.item.noOutput")}
          </pre>
        </div>
      )}
    </div>
  );
}
