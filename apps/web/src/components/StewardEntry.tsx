import { useEffect, useState } from "react";
import { Bot, Phone } from "lucide-react";
import { getCallStatus, type CallStatus } from "@/lib/api";
import { isViewVisible } from "@/lib/lenses";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { IconButton } from "@/ui/IconButton";
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
 * key would teach that the page was never there. The only thing a probe may decide is the
 * phone BESIDE it — a call is a feature an older engine does not have at all (404 → `null`),
 * and one that costs money by the minute, so the affordance appears only where there is
 * something to call and the gesture stays the Owner's on the surface itself.
 */
export function StewardEntry() {
  const view = useApp((s) => s.view);
  const lens = useApp((s) => s.lens);
  const currentUser = useApp((s) => s.currentUser);
  const setView = useApp((s) => s.setView);
  const t = useT();
  const visible = isViewVisible("steward", lens);
  const [call, setCall] = useState<CallStatus | null>(null);

  // One cheap GET per library, and only where the entry itself shows: every absence — no
  // route, no engine, no JSON — comes back as null, which is the whole of "no phone here".
  useEffect(() => {
    if (!visible || !currentUser) {
      setCall(null);
      return;
    }
    let live = true;
    getCallStatus(currentUser)
      .then((s) => live && setCall(s))
      .catch(() => live && setCall(null));
    return () => {
      live = false;
    };
  }, [visible, currentUser]);

  if (!visible) return null;
  const active = view === "steward";

  return (
    <>
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
      {call?.configured === true && (
        <Tooltip content={t("call.open")}>
          <IconButton
            size="sm"
            aria-label={t("call.open")}
            onClick={() => setView("steward", { call: "1" })}
          >
            <Phone size={14} aria-hidden />
          </IconButton>
        </Tooltip>
      )}
    </>
  );
}
