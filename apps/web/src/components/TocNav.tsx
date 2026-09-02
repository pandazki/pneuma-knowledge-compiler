import { useApp } from "@/lib/store";
import { isViewVisible, type Lens } from "@/lib/lenses";
import { useT } from "@/lib/useT";
import type { MessageKey } from "@/lib/i18n";
import type { ViewName } from "@/lib/types";
import { cn } from "@/ui/cn";
import { LensBadge } from "./LensBadge";

interface TocItem {
  view: ViewName;
  no: string;
  label: MessageKey;
}

interface TocGroup {
  group: MessageKey;
  items: TocItem[];
}

/**
 * The chapter table from DESIGN.md §3 (the hidden "components" route stays out of it).
 * Structure — § numbers, order, grouping — lives here; the words live in i18n/nav.ts.
 */
export const TOC: TocGroup[] = [
  {
    group: "nav.group.front",
    items: [{ view: "overview", no: "01", label: "nav.view.overview" }],
  },
  {
    group: "nav.group.materials",
    items: [
      { view: "sources", no: "02", label: "nav.view.sources" },
      { view: "ingest", no: "03", label: "nav.view.ingest" },
    ],
  },
  {
    group: "nav.group.process",
    items: [{ view: "process", no: "04", label: "nav.view.process" }],
  },
  {
    group: "nav.group.retrieval",
    items: [
      { view: "recall", no: "05", label: "nav.view.recall" },
      { view: "ask", no: "06", label: "nav.view.ask" },
      { view: "live_context", no: "07", label: "nav.view.live_context" },
      // The record of everything the three lanes above it answered — the retrieval chapter
      // read backwards, which is why it closes that chapter rather than opening another.
      { view: "consultations", no: "08", label: "nav.view.consultations" },
    ],
  },
  {
    group: "nav.group.canon",
    items: [
      { view: "library", no: "09", label: "nav.view.library" },
      { view: "graph", no: "10", label: "nav.view.graph" },
      { view: "history", no: "11", label: "nav.view.history" },
    ],
  },
  {
    group: "nav.group.evolution",
    items: [
      { view: "evolve", no: "12", label: "nav.view.evolve" },
      { view: "engine_console", no: "13", label: "nav.view.engine_console" },
    ],
  },
  {
    group: "nav.group.back",
    items: [{ view: "profile", no: "14", label: "nav.view.profile" }],
  },
];

/**
 * The rail this lens actually gets. Nothing here keeps a second list of who sees what: it
 * filters the one chapter table through `VIEW_LENSES`, so a view added to the table without
 * a lens declaration is a build error rather than a page a visitor finds by scrolling.
 */
export function tocForLens(lens: Lens): TocGroup[] {
  if (lens === "owner") return TOC;
  return TOC.map((group) => ({
    ...group,
    items: group.items.filter((item) => isViewVisible(item.view, lens)),
  })).filter((group) => group.items.length > 0);
}

export interface TocNavProps {
  /** Called after a pick (the mobile Drawer uses it to close itself). */
  onNavigate?: () => void;
}

/**
 * The contents rail: chapter groups + § numbers + an accent rule on the current page, and —
 * pinned at its foot, under a rule — who is reading it.
 *
 * The lens belongs here rather than in the top bar because it is not an administrative
 * control over the library; it decides what this rail even lists. Reading down the contents
 * and arriving at the identity that produced them is the honest order, and it keeps the top
 * bar to the global functions it already had.
 *
 * Under a visitor lens the rail collapses to the reading room's two entries, and the chapter
 * apparatus goes with the chapters: § numbers and group headings name a book of fourteen
 * sections, and printing 「§05」 above two lines would keep pointing at twelve pages that
 * are not there. Same component, same rows, fewer of them — the foot is unchanged by the
 * lens, because the way back out of the reading room must never be one of the things the
 * reading room subtracts.
 */
export function TocNav({ onNavigate }: TocNavProps) {
  const view = useApp((s) => s.view);
  const lens = useApp((s) => s.lens);
  const setView = useApp((s) => s.setView);
  const t = useT();
  const groups = tocForLens(lens);
  const chapters = lens === "owner";

  return (
    <div className="flex h-full flex-col">
      {/* The chapters scroll, the foot does not: fourteen sections are taller than a short
          window, and an identity you have to scroll to find is not one you can see you are
          wearing. */}
      <nav
        aria-label={t("nav.toc.aria")}
        className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-3 py-4"
      >
        {groups.map((group) => (
          <div key={group.group} className="flex flex-col gap-0.5">
            {chapters && <p className="px-2 pb-1 text-12 text-ink-3">{t(group.group)}</p>}
            {group.items.map((item) => {
              const active = item.view === view;
              return (
                <button
                  key={item.view}
                  type="button"
                  aria-current={active ? "page" : undefined}
                  onClick={() => {
                    setView(item.view);
                    onNavigate?.();
                  }}
                  className={cn(
                    "flex items-baseline gap-2 border-l-2 px-2 py-1.5 text-left text-13",
                    "transition-colors duration-120 ease-out",
                    active
                      ? "border-accent font-medium text-ink"
                      : "border-transparent text-ink-2 hover:bg-hover hover:text-ink",
                  )}
                >
                  {chapters && (
                    <span
                      className={cn(
                        "w-6 shrink-0 font-mono text-12",
                        active ? "text-accent" : "text-ink-3",
                      )}
                    >
                      §{item.no}
                    </span>
                  )}
                  <span className="min-w-0 truncate">{t(item.label)}</span>
                </button>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="shrink-0 border-t border-line px-3 py-3">
        <p className="px-2 pb-1.5 text-12 text-ink-3">{t("nav.lens.label")}</p>
        <LensBadge />
        {/* The silent stance is stated WHERE the identity is, not as a banner reflowing the
            page: switching who you are must not move what you were reading. */}
        {lens === "silent" && (
          <p className="px-2 pt-1.5 text-12 text-ink-3">{t("nav.lens.silentBanner")}</p>
        )}
      </div>
    </div>
  );
}
