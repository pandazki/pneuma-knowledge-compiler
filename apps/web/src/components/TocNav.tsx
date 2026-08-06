import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import type { MessageKey } from "@/lib/i18n";
import type { ViewName } from "@/lib/types";
import { cn } from "@/ui/cn";

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
    ],
  },
  {
    group: "nav.group.canon",
    items: [
      { view: "library", no: "08", label: "nav.view.library" },
      { view: "graph", no: "09", label: "nav.view.graph" },
      { view: "history", no: "10", label: "nav.view.history" },
    ],
  },
  {
    group: "nav.group.evolution",
    items: [
      { view: "evolve", no: "11", label: "nav.view.evolve" },
      { view: "engine_console", no: "12", label: "nav.view.engine_console" },
    ],
  },
  {
    group: "nav.group.back",
    items: [{ view: "profile", no: "13", label: "nav.view.profile" }],
  },
];

export interface TocNavProps {
  /** Called after a pick (the mobile Drawer uses it to close itself). */
  onNavigate?: () => void;
}

/** The contents rail: chapter groups + § numbers + an accent rule on the current page. */
export function TocNav({ onNavigate }: TocNavProps) {
  const view = useApp((s) => s.view);
  const setView = useApp((s) => s.setView);
  const t = useT();

  return (
    <nav aria-label={t("nav.toc.aria")} className="flex flex-col gap-5 px-3 py-4">
      {TOC.map((group) => (
        <div key={group.group} className="flex flex-col gap-0.5">
          <p className="px-2 pb-1 text-12 text-ink-3">{t(group.group)}</p>
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
                <span
                  className={cn(
                    "w-6 shrink-0 font-mono text-12",
                    active ? "text-accent" : "text-ink-3",
                  )}
                >
                  §{item.no}
                </span>
                <span className="min-w-0 truncate">{t(item.label)}</span>
              </button>
            );
          })}
        </div>
      ))}
    </nav>
  );
}
