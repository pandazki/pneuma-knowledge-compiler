import { Bot } from "lucide-react";
import { isViewVisible } from "@/lib/lenses";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Tooltip } from "@/ui/Tooltip";
import { cn } from "@/ui/cn";

/**
 * The way to the Steward, in the top bar rather than in the contents.
 *
 * The rail is a book and its entries are chapters OF this library. The Steward is not one: it
 * is who you talk to about the library, and you talk to it from wherever you are standing —
 * reading a page, watching the queue, halfway through a version. So it sits with the other
 * global controls, left of which library is on the bench.
 *
 * Visibility is the VIEW's own lens declaration (`VIEW_LENSES.steward` = owner) read through
 * `isViewVisible`, exactly as the rail read it. Nothing here keeps a second list, and nothing
 * here consults a credential: the entry is the map, and a map that changed with the state of a
 * key would teach that the page was never there. Voice controls live inside the Steward.
 */
export function StewardEntry() {
  const view = useApp((s) => s.view);
  const lens = useApp((s) => s.lens);
  const setView = useApp((s) => s.setView);
  const t = useT();
  const visible = isViewVisible("steward", lens);
  if (!visible) return null;
  const active = view === "steward";

  return (
    <Tooltip content={t("nav.steward.title")}>
        <button
          type="button"
          aria-label={t("nav.steward.label")}
          aria-current={active ? "page" : undefined}
          onClick={() => setView("steward")}
          className={cn(
            "inline-flex h-8 shrink-0 items-center gap-1.5 rounded-2 border px-2.5 text-13",
            "transition-colors duration-120 ease-out",
            active
              ? "border-accent bg-accent-soft text-ink"
              : "border-line-2 bg-surface text-ink hover:bg-hover",
          )}
        >
          <Bot size={14} aria-hidden className={active ? "text-accent" : "text-ink-3"} />
          {/* The label goes at 390px the way the wordmark's second half does; the button keeps
              its accessible name either way. */}
          <span className="hidden sm:inline">{t("nav.steward.label")}</span>
        </button>
    </Tooltip>
  );
}
