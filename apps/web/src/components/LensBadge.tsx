import { Check, ChevronsUpDown, UserRound } from "lucide-react";
import { useApp } from "@/lib/store";
import { LENSES, type Lens } from "@/lib/lenses";
import { useT } from "@/lib/useT";
import { cn } from "@/ui/cn";
import { Menu } from "@/ui/Menu";

const NAME = {
  owner: "nav.lens.owner",
  visitor: "nav.lens.visitor",
  silent: "nav.lens.silent",
} as const;

const CONSEQUENCE = {
  owner: "nav.lens.owner.consequence",
  visitor: "nav.lens.visitor.consequence",
  silent: "nav.lens.silent.consequence",
} as const;

/**
 * Who is at this console, said out loud at the foot of the contents rail and switchable
 * from there.
 *
 * It is a badge and not a setting buried in a panel because the lens decides what the whole
 * app is — cockpit or reading room — and what every question it asks leaves behind. It sits
 * under the chapters rather than in the top bar for the same reason: the top bar holds the
 * console's global administration, and identity is not one more administrative control, it
 * is the thing that decided how long that list of chapters is. Each option carries the
 * consequence beside the name, the same way the visitor classes did: the name says who you
 * are, the line says what that costs the library.
 *
 * The silent lens wears a muted accent so the difference is visible at a glance, without a
 * second theme: honesty here is one changed word and one changed tint, not a redesign.
 */
export function LensBadge() {
  const lens = useApp((s) => s.lens);
  const setLens = useApp((s) => s.setLens);
  const t = useT();

  return (
    <Menu
      align="start"
      // The rail's foot is the bottom of the viewport; a menu opening downward from there
      // would open off the screen.
      side="top"
      contentClassName="min-w-64"
      trigger={
        <button
          type="button"
          aria-label={t("nav.lens.aria")}
          className={cn(
            "flex h-7 w-full items-center gap-1.5 rounded-1 border border-line px-2 text-13",
            "transition-colors duration-120 ease-out hover:bg-hover",
            lens === "silent" ? "bg-accent-soft text-accent" : "text-ink-2",
          )}
        >
          <UserRound size={14} aria-hidden className="shrink-0" />
          <span className="min-w-0 flex-1 truncate text-left">{t(NAME[lens])}</span>
          <ChevronsUpDown size={13} aria-hidden className="shrink-0 text-ink-3" />
        </button>
      }
      items={LENSES.map((option: Lens) => ({
        key: option,
        icon: (
          <Check
            size={14}
            aria-hidden
            className={cn("shrink-0", option === lens ? "text-accent" : "invisible")}
          />
        ),
        label: (
          <span className="flex min-w-0 flex-col">
            <span className="truncate">{t(NAME[option])}</span>
            <span className="truncate text-12 text-ink-3">{t(CONSEQUENCE[option])}</span>
          </span>
        ),
        onSelect: () => setLens(option),
      }))}
    />
  );
}
