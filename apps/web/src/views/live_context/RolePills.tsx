/**
 * The speaker pills, sitting to the left of the composer.
 *
 * A row of flat activators rather than a dropdown, because of what the control is FOR. In a
 * live conversation the speaker changes every turn or two, and a dropdown makes that two
 * interactions and a moment of reading; a pill makes it one click on a target that is already
 * on screen, in a colour the operator has learned. The list is short by nature — a
 * conversation with fifteen participants is not what this page is for — so the row costs
 * nothing that a menu would save.
 *
 * The owner pill (知识主体) is visually distinct and cannot be removed. That is not decoration:
 * the citation gate treats the knowledge subject's own words differently from a participant's,
 * so which pill is which is a fact about the evaluation, and a conversation with no owner
 * could not say whose knowledge base it is about.
 */

import { useEffect, useRef, useState } from "react";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import type { LiveRole, RoleColour } from "@/lib/liveContextChat";
import { ROLE_COLOURS } from "@/lib/liveContextChat";
import { useT } from "@/lib/useT";
import { IconButton } from "@/ui/IconButton";
import { Popover } from "@/ui/Popover";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";

/** A role's ink, as the CSS variable the tokens file defines for it. */
export function roleInk(colour: RoleColour): string {
  return `var(--role-${colour})`;
}

/**
 * Ground / border / text for a pill, derived from its one ink by `color-mix` — the same way
 * `--accent-soft` and `--accent-line` are derived from `--accent`. A role is one value in the
 * tokens file, not three, and both themes stay consistent for free.
 */
export function roleStyle(colour: RoleColour, active: boolean) {
  const ink = roleInk(colour);
  return {
    color: active ? ink : undefined,
    borderColor: active ? `color-mix(in srgb, ${ink} 45%, var(--bg))` : undefined,
    backgroundColor: active ? `color-mix(in srgb, ${ink} 12%, var(--bg))` : undefined,
  };
}

export interface RolePillsProps {
  roles: LiveRole[];
  activeId: string;
  onActivate: (id: string) => void;
  onAdd: (name: string) => void;
  onRename: (id: string, name: string) => void;
  onRecolour: (id: string, colour: RoleColour) => void;
  onRemove: (id: string) => void;
  className?: string;
}

export function RolePills({
  roles,
  activeId,
  onActivate,
  onAdd,
  onRename,
  onRecolour,
  onRemove,
  className,
}: RolePillsProps) {
  const t = useT();
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    if (editing || adding) inputRef.current?.focus();
  }, [editing, adding]);

  function commit() {
    const name = draft.trim();
    if (name) {
      if (editing) onRename(editing, name);
      else onAdd(name);
    }
    setEditing(null);
    setAdding(false);
    setDraft("");
  }

  function cancel() {
    setEditing(null);
    setAdding(false);
    setDraft("");
  }

  const nameField = (
    <span className="inline-flex items-center gap-1">
      <input
        ref={inputRef}
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
          if (e.key === "Escape") cancel();
        }}
        // Blur commits: the operator's next click is almost always the input field or a
        // suggestion, and losing a typed name to a stray click would be the rudest possible
        // outcome for a control this small.
        onBlur={commit}
        maxLength={16}
        placeholder={t("liveContext.roles.namePlaceholder")}
        aria-label={t("liveContext.roles.nameLabel")}
        className="w-24 rounded-1 border border-accent-line bg-raised px-2 py-1 text-13 text-ink outline-none"
      />
      <IconButton size="sm" aria-label={t("liveContext.roles.confirm")} onMouseDown={(e) => e.preventDefault()} onClick={commit}>
        <Check size={13} aria-hidden />
      </IconButton>
    </span>
  );

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      {roles.map((role) =>
        editing === role.id ? (
          <span key={role.id}>{nameField}</span>
        ) : (
          <Popover
            key={role.id}
            side="top"
            align="start"
            contentClassName="w-48 p-2"
            trigger={
              <button
                type="button"
                onClick={() => onActivate(role.id)}
                // The pill is the activator; its own menu is a secondary gesture, so it hangs
                // off a right-click / long-press rather than stealing the primary one.
                onContextMenu={(e) => e.preventDefault()}
                aria-pressed={role.id === activeId}
                style={roleStyle(role.colour, role.id === activeId)}
                className={cn(
                  "inline-flex max-w-32 items-center gap-1.5 truncate rounded-full border px-2.5 py-1 text-12 transition-colors",
                  role.id === activeId
                    ? "font-medium"
                    : "border-line text-ink-2 hover:bg-hover",
                )}
                title={
                  role.kind === "owner"
                    ? t("liveContext.roles.ownerTitle")
                    : t("liveContext.roles.pillTitle", { name: role.name })
                }
              >
                <span
                  aria-hidden
                  className={cn(
                    "size-1.5 shrink-0 rounded-full",
                    // The owner's marker is a ring rather than a dot — a different SHAPE, so
                    // the distinction survives both a colour change and a colour-blind reader.
                    role.kind === "owner" && "ring-1 ring-offset-1 ring-offset-transparent",
                  )}
                  style={{
                    backgroundColor: role.kind === "owner" ? "transparent" : roleInk(role.colour),
                    ...(role.kind === "owner" ? { boxShadow: `inset 0 0 0 1px ${roleInk(role.colour)}` } : {}),
                  }}
                />
                <span className="truncate">{role.name}</span>
              </button>
            }
          >
            <p className="mb-2 px-1 text-12 text-ink-3">
              {role.kind === "owner" ? t("liveContext.roles.ownerNote") : role.name}
            </p>
            <div className="mb-2 flex flex-wrap gap-1 px-1">
              {ROLE_COLOURS.map((colour) => (
                <button
                  key={colour}
                  type="button"
                  aria-label={t("liveContext.roles.colour", { colour: t(`liveContext.colour.${colour}`) })}
                  onClick={() => onRecolour(role.id, colour)}
                  className={cn(
                    "size-4 rounded-full border transition-transform hover:scale-110",
                    role.colour === colour ? "border-ink" : "border-transparent",
                  )}
                  style={{ backgroundColor: roleInk(colour) }}
                />
              ))}
            </div>
            <div className="flex items-center gap-1">
              <IconButton
                size="sm"
                aria-label={t("liveContext.roles.rename")}
                onClick={() => {
                  setDraft(role.name);
                  setEditing(role.id);
                }}
              >
                <Pencil size={13} aria-hidden />
              </IconButton>
              {/* The knowledge subject has no remove button at all, rather than a disabled
                  one: it is not a permission the operator is missing, it is not a thing. */}
              {role.kind !== "owner" && roles.length > 1 && (
                <IconButton
                  size="sm"
                  aria-label={t("liveContext.roles.remove")}
                  onClick={() => onRemove(role.id)}
                >
                  <Trash2 size={13} aria-hidden />
                </IconButton>
              )}
            </div>
          </Popover>
        ),
      )}

      {adding ? (
        nameField
      ) : (
        <Tooltip content={t("liveContext.roles.addTitle")}>
          <button
            type="button"
            aria-label={t("liveContext.roles.add")}
            onClick={() => {
              setDraft("");
              setAdding(true);
            }}
            className="inline-flex items-center rounded-full border border-dashed border-line-2 px-2 py-1 text-12 text-ink-3 transition-colors hover:border-line-2 hover:bg-hover hover:text-ink-2"
          >
            <Plus size={12} aria-hidden />
          </button>
        </Tooltip>
      )}
      {(editing || adding) && (
        <IconButton size="sm" aria-label={t("liveContext.roles.cancel")} onMouseDown={(e) => e.preventDefault()} onClick={cancel}>
          <X size={13} aria-hidden />
        </IconButton>
      )}
    </div>
  );
}
