import { useApp } from "@/lib/store";
import { isViewVisible, type Lens } from "@/lib/lenses";
import { modelLaneLocked } from "@/lib/modelLanes";
import { useT } from "@/lib/useT";
import type { MessageKey } from "@/lib/i18n";
import type { ViewName } from "@/lib/types";
import { cn } from "@/ui/cn";
import { LensBadge } from "./LensBadge";

interface TocItem {
  view: ViewName;
  /** The § number, STAMPED from position by `numbered` below — never written by hand. */
  no: string;
  label: MessageKey;
}

interface TocGroup {
  group: MessageKey;
  items: TocItem[];
}

/** A chapter as it is declared: order and grouping, with no number in it. */
interface Chapter {
  group: MessageKey;
  items: { view: ViewName; label: MessageKey }[];
}

/**
 * The machine's own entry, above the book. It is not a chapter — it is not about this
 * library at all — so it carries no § number and sits outside the numbering, and it is
 * PREPENDED only when a home answered (`HOME_GROUP` below). On every project deployment the
 * rail is the table it always was.
 */
const HOME_GROUP: TocGroup = {
  group: "nav.group.machine",
  items: [{ view: "home", no: "", label: "nav.view.home" }],
};

/**
 * The chapter table from DESIGN.md §3 (the hidden "components" route stays out of it).
 * Structure — order and grouping — lives here; the words live in i18n/nav.ts.
 *
 * The Steward is not in it. It is not a chapter of this library at all: it is the person you
 * talk to about it, from wherever you happen to be standing, so it sits in the top bar
 * (`components/StewardEntry.tsx`) beside the other global controls.
 */
const CHAPTERS: Chapter[] = [
  {
    group: "nav.group.front",
    items: [{ view: "overview", label: "nav.view.overview" }],
  },
  {
    group: "nav.group.materials",
    items: [
      { view: "sources", label: "nav.view.sources" },
      { view: "ingest", label: "nav.view.ingest" },
    ],
  },
  {
    group: "nav.group.process",
    items: [{ view: "process", label: "nav.view.process" }],
  },
  {
    group: "nav.group.retrieval",
    items: [
      { view: "recall", label: "nav.view.recall" },
      { view: "ask", label: "nav.view.ask" },
      { view: "live_context", label: "nav.view.live_context" },
      // The record of everything the three lanes above it answered — the retrieval chapter
      // read backwards, which is why it closes that chapter rather than opening another.
      { view: "consultations", label: "nav.view.consultations" },
    ],
  },
  {
    group: "nav.group.canon",
    items: [
      { view: "library", label: "nav.view.library" },
      { view: "lens", label: "nav.view.lens" },
      // The check sits beside the lens because they read the same library from two heights:
      // the lens says what the whole is becoming, the check lists what one page has to fix.
      { view: "review", label: "nav.view.review" },
      { view: "history", label: "nav.view.history" },
    ],
  },
  {
    group: "nav.group.evolution",
    items: [
      { view: "evolve", label: "nav.view.evolve" },
      { view: "engine_console", label: "nav.view.engine_console" },
    ],
  },
  {
    group: "nav.group.back",
    items: [{ view: "profile", label: "nav.view.profile" }],
  },
];

/**
 * Stamp the § numbers from POSITION, running across the groups in order.
 *
 * A sequence number is bookkeeping, not meaning: there is nothing to save by squeezing a new
 * chapter in as 「04b」, and a book that numbers itself cannot disagree with its own order.
 * Insert or remove a chapter above and everything below it renumbers, which is what a
 * renumbered book does.
 */
function numbered(chapters: Chapter[]): TocGroup[] {
  let n = 0;
  return chapters.map((chapter) => ({
    group: chapter.group,
    items: chapter.items.map((item) => ({ ...item, no: String(++n).padStart(2, "0") })),
  }));
}

export const TOC: TocGroup[] = numbered(CHAPTERS);

/**
 * The rail this lens actually gets. Nothing here keeps a second list of who sees what: it
 * filters the one chapter table through `VIEW_LENSES`, so a view added to the table without
 * a lens declaration is a build error rather than a page a visitor finds by scrolling.
 */
export function tocForLens(lens: Lens, hasHome = false): TocGroup[] {
  const table = hasHome ? [HOME_GROUP, ...TOC] : TOC;
  if (lens === "owner") return table;
  return table
    .map((group) => ({
      ...group,
      items: group.items.filter((item) => isViewVisible(item.view, lens)),
    }))
    .filter((group) => group.items.length > 0);
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
 * apparatus goes with the chapters: § numbers and group headings name a book of fifteen
 * sections, and printing 「§05」 above two lines would keep pointing at thirteen pages that
 * are not there. Same component, same rows, fewer of them — the foot is unchanged by the
 * lens, because the way back out of the reading room must never be one of the things the
 * reading room subtracts.
 */
export function TocNav({ onNavigate }: TocNavProps) {
  const view = useApp((s) => s.view);
  const lens = useApp((s) => s.lens);
  const setView = useApp((s) => s.setView);
  const hasHome = useApp((s) => s.home != null);
  // A key this library does not have closes the three model lanes, but it must not edit the
  // table of contents: the map of the console is the same map, and an entry that vanished
  // with a credential would teach that the page was never there.
  const home = useApp((s) => s.home);
  const t = useT();
  const groups = tocForLens(lens, hasHome);
  const chapters = lens === "owner";

  return (
    <div className="flex h-full flex-col">
      {/* The chapters scroll, the foot does not: fifteen sections are taller than a short
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
              const locked = modelLaneLocked(item.view, home);
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
                      {/* The machine's entry is outside the numbering, so its cell is empty
                          rather than reading 「§」 — the column still aligns. */}
                      {item.no === "" ? "" : `§${item.no}`}
                    </span>
                  )}
                  <span className="min-w-0 truncate">{t(item.label)}</span>
                  {/* The entry stays; it is marked. One quiet word, and the reason on hover. */}
                  {locked && (
                    <span
                      title={t("nav.modelLane.title")}
                      className="shrink-0 rounded-1 border border-line-2 px-1 font-mono text-12 text-ink-3"
                    >
                      {t("nav.modelLane.badge")}
                    </span>
                  )}
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
