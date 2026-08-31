/**
 * The conversation, and the composer under it.
 *
 * ONE chat surface for both transports. The old page had two, one per socket, each with its
 * own turn editor — which taught that a one-shot evaluation and a long-lived listener are
 * different features. They are not: they are two deliveries of the same conversation, and the
 * only thing the operator should have to think about is which one is on.
 *
 * That leaves exactly one honest difference on this surface, and it is visible rather than
 * hidden: **a turn already pushed on the long-lived socket is frozen.** The stream is
 * append-only, the server holds that turn inside the window it evaluates against, and no wire
 * verb takes it back. So it renders with a 已发送 mark and no edit affordance, while an unsent
 * draft — and every turn in one-shot mode, where the whole window is re-sent anyway — stays
 * editable. The rule is enforced in `liveContextChat.ts`, not here; this only shows it.
 */

import { useEffect, useRef, useState } from "react";
import { Check, Pencil, Send, Trash2, X, Zap } from "lucide-react";
import type { ChatMode, LiveRole, LiveTurn, RoleColour } from "@/lib/liveContextChat";
import { canEditTurn } from "@/lib/liveContextChat";
import { useT } from "@/lib/useT";
import { fmtTime } from "@/lib/format";
import { Button } from "@/ui/Button";
import { IconButton } from "@/ui/IconButton";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { TextArea } from "@/ui/TextArea";
import { cn } from "@/ui/cn";
import { RolePills, roleInk } from "./RolePills";

export interface ChatPanelProps {
  mode: ChatMode;
  roles: LiveRole[];
  activeRoleId: string;
  turns: LiveTurn[];
  draft: string;
  /** True while a one-shot evaluation is in flight. */
  busy: boolean;
  /** Whether the long-lived socket can take a turn right now. */
  canSend: boolean;
  onDraftChange: (text: string) => void;
  onSend: () => void;
  onEvaluate: () => void;
  onEditTurn: (id: string, text: string) => void;
  onDeleteTurn: (id: string) => void;
  onActivateRole: (id: string) => void;
  onAddRole: (name: string) => void;
  onRenameRole: (id: string, name: string) => void;
  onRecolourRole: (id: string, colour: RoleColour) => void;
  onRemoveRole: (id: string) => void;
}

export function ChatPanel(props: ChatPanelProps) {
  const t = useT();
  const {
    mode,
    roles,
    activeRoleId,
    turns,
    draft,
    busy,
    canSend,
    onDraftChange,
    onSend,
    onEvaluate,
    onEditTurn,
    onDeleteTurn,
  } = props;

  const [editing, setEditing] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const endRef = useRef<HTMLDivElement | null>(null);
  const roleOf = (id: string) => roles.find((r) => r.id === id);

  // Follow the conversation as it grows — a chat that does not scroll to the newest turn is a
  // log, not a conversation.
  useEffect(() => {
    endRef.current?.scrollIntoView({ block: "end" });
  }, [turns.length]);

  const activeRole = roleOf(activeRoleId);

  return (
    <section className="flex min-h-0 flex-1 flex-col rounded-2 border border-line bg-surface">
      <header className="flex shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-2">
        <h2 className="text-13 font-medium text-ink-2">{t("liveContext.chat.title")}</h2>
        <span className="text-12 text-ink-3">
          {t("liveContext.chat.count", { count: turns.length })}
        </span>
      </header>

      <ScrollRegion className="min-h-0 flex-1 px-3 py-3">
        {turns.length === 0 ? (
          <p className="mt-6 text-center text-13 text-ink-3">{t("liveContext.chat.empty")}</p>
        ) : (
          <ol className="flex flex-col gap-3">
            {turns.map((turn) => {
              const role = roleOf(turn.roleId);
              const editable = canEditTurn(turn, mode);
              const owner = role?.kind === "owner";
              return (
                <li
                  key={turn.id}
                  className={cn("group/turn flex flex-col gap-1", owner && "items-end")}
                >
                  <div className={cn("flex items-baseline gap-2", owner && "flex-row-reverse")}>
                    <span
                      className="text-12 font-medium"
                      style={{ color: role ? roleInk(role.colour) : undefined }}
                    >
                      {role?.name ?? t("liveContext.chat.unknownRole")}
                    </span>
                    <span className="text-11 text-ink-3">{fmtTime(new Date(turn.at).toISOString())}</span>
                    {/* The honest mark. In stream mode this turn is inside a window the
                        server has already read, and nothing can take it back. */}
                    {turn.sent && mode === "stream" && (
                      <span className="text-11 text-ink-3">{t("liveContext.chat.sent")}</span>
                    )}
                  </div>

                  {editing === turn.id ? (
                    <div className="flex w-full max-w-[85%] items-start gap-1">
                      <TextArea
                        value={editDraft}
                        onChange={(e) => setEditDraft(e.target.value)}
                        rows={2}
                        aria-label={t("liveContext.turn.text")}
                        wrapperClassName="flex-1"
                      />
                      <IconButton
                        size="sm"
                        aria-label={t("liveContext.chat.saveEdit")}
                        onClick={() => {
                          onEditTurn(turn.id, editDraft);
                          setEditing(null);
                        }}
                      >
                        <Check size={13} aria-hidden />
                      </IconButton>
                      <IconButton
                        size="sm"
                        aria-label={t("liveContext.chat.cancelEdit")}
                        onClick={() => setEditing(null)}
                      >
                        <X size={13} aria-hidden />
                      </IconButton>
                    </div>
                  ) : (
                    <div className={cn("flex max-w-[85%] items-start gap-1", owner && "flex-row-reverse")}>
                      <p
                        className={cn(
                          "whitespace-pre-wrap rounded-2 border px-3 py-2 text-14",
                          turn.sent && mode === "stream"
                            ? "border-line bg-bg text-ink-2"
                            : "border-line-2 bg-raised text-ink",
                        )}
                        style={
                          role
                            ? { borderColor: `color-mix(in srgb, ${roleInk(role.colour)} 30%, var(--bg))` }
                            : undefined
                        }
                      >
                        {turn.text}
                      </p>
                      {editable && (
                        <span className="flex shrink-0 gap-0.5 opacity-0 transition-opacity group-hover/turn:opacity-100 focus-within:opacity-100">
                          <IconButton
                            size="sm"
                            aria-label={t("liveContext.chat.edit")}
                            onClick={() => {
                              setEditDraft(turn.text);
                              setEditing(turn.id);
                            }}
                          >
                            <Pencil size={12} aria-hidden />
                          </IconButton>
                          <IconButton
                            size="sm"
                            aria-label={t("liveContext.turn.remove")}
                            onClick={() => onDeleteTurn(turn.id)}
                          >
                            <Trash2 size={12} aria-hidden />
                          </IconButton>
                        </span>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        )}
        <div ref={endRef} />
      </ScrollRegion>

      {/* the composer */}
      <div className="shrink-0 border-t border-line px-3 py-2">
        <RolePills
          className="mb-2"
          roles={roles}
          activeId={activeRoleId}
          onActivate={props.onActivateRole}
          onAdd={props.onAddRole}
          onRename={props.onRenameRole}
          onRecolour={props.onRecolourRole}
          onRemove={props.onRemoveRole}
        />
        <div className="flex items-end gap-2">
          <TextArea
            wrapperClassName="min-w-0 flex-1"
            value={draft}
            rows={2}
            onChange={(e) => onDraftChange(e.target.value)}
            onKeyDown={(e) => {
              // Enter sends, Shift+Enter breaks the line: this is a chat composer, and the
              // turns it produces are one or two sentences.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                onSend();
              }
            }}
            placeholder={t("liveContext.compose.placeholder", { role: activeRole?.name ?? "" })}
            aria-label={t("liveContext.turn.text")}
            data-testid="live-context-composer"
          />

          {mode === "stream" ? (
            <Button
              variant="primary"
              disabled={!canSend || !draft.trim()}
              onClick={onSend}
              title={t("liveContext.compose.sendTitle")}
            >
              <Send size={13} aria-hidden /> {t("liveContext.compose.send")}
            </Button>
          ) : (
            <Button disabled={!draft.trim()} onClick={onSend} title={t("liveContext.compose.addTitle")}>
              <Send size={13} aria-hidden /> {t("liveContext.compose.add")}
            </Button>
          )}
        </div>

        {/* One-shot has an explicit act; the long connection pushes each turn as it is sent. */}
        {mode === "oneshot" ? (
          <div className="mt-2 flex items-center gap-2">
            <Button
              variant="primary"
              size="sm"
              loading={busy}
              disabled={turns.length === 0}
              onClick={onEvaluate}
              data-testid="live-context-evaluate"
            >
              <Zap size={13} aria-hidden /> {t("liveContext.compose.evaluate")}
            </Button>
            <span className="text-11 text-ink-3">{t("liveContext.compose.evaluateHint")}</span>
          </div>
        ) : (
          <p className="mt-2 text-11 text-ink-3">{t("liveContext.compose.streamHint")}</p>
        )}
      </div>
    </section>
  );
}
