import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { useApp } from "@/lib/store";
import { getWorkspaceSummary, type WorkspaceSummary } from "@/lib/api";
import type { MessageKey } from "@/lib/i18n";
import type { ViewName } from "@/lib/types";
import { useT } from "@/lib/useT";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { Skeleton } from "@/ui/Skeleton";
import { Stamp } from "@/ui/Stamp";
import { cn } from "@/ui/cn";

/* ------------------------------------------- The ruled production-line diagram */

interface FlowNode {
  no: string;
  name: string;
  caption: string;
  view: ViewName;
  /** null = loading (Skeleton); undefined = no data / no user (—). */
  count: number | null | undefined;
  unit: string;
}

function FlowChart({ nodes }: { nodes: FlowNode[] }) {
  const setView = useApp((s) => s.setView);
  const t = useT();
  return (
    <ol
      aria-label={t("overview.flow.aria")}
      className="flex flex-col border-l border-line sm:grid sm:grid-cols-4 sm:gap-x-6 sm:border-t sm:border-l-0"
    >
      {nodes.map((node) => (
        <li key={node.no} className="min-w-0">
          <button
            type="button"
            onClick={() => setView(node.view)}
            className={cn(
              "group flex w-full flex-col items-start gap-1 py-4 pl-4 text-left sm:py-0 sm:pt-4 sm:pl-0",
              "transition-colors duration-120 ease-out",
            )}
          >
            {/* Ruler tick: vertical off the top rule on wide screens, horizontal off the left rule when narrow */}
            <span
              aria-hidden
              className="hidden h-3 w-px bg-line-2 sm:-mt-4 sm:block"
            />
            <span className="flex items-baseline gap-2">
              <span className="font-mono text-12 text-accent">{node.no}</span>
              <span className="font-serif text-20 text-ink group-hover:text-accent">
                {node.name}
              </span>
            </span>
            <span className="text-13 text-ink-3">{node.caption}</span>
            <span className="mt-2 flex items-baseline gap-2" aria-live="polite">
              {node.count === null ? (
                <Skeleton className="h-7 w-12" />
              ) : node.count === undefined ? (
                <span className="font-serif text-24 text-ink-3">—</span>
              ) : (
                <span className="font-serif text-24 text-accent tabular-nums">
                  {node.count}
                </span>
              )}
              <span className="text-12 text-ink-3">{node.unit}</span>
            </span>
            <span className="mt-1 inline-flex items-center gap-1 text-12 text-accent opacity-0 transition-opacity duration-120 group-hover:opacity-100 group-focus-visible:opacity-100">
              {t("overview.flow.enter")} <ArrowRight size={12} aria-hidden />
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

/* --------------------------------------------------------------- Reading guide */

interface GuideItem {
  no: string;
  titleKey: MessageKey;
  bodyKey: MessageKey;
  view: ViewName;
}

const GUIDE: GuideItem[] = [
  {
    no: "01",
    titleKey: "overview.guide.ingest.title",
    bodyKey: "overview.guide.ingest.body",
    view: "ingest",
  },
  {
    no: "02",
    titleKey: "overview.guide.process.title",
    bodyKey: "overview.guide.process.body",
    view: "process",
  },
  {
    no: "03",
    titleKey: "overview.guide.library.title",
    bodyKey: "overview.guide.library.body",
    view: "library",
  },
  {
    no: "04",
    titleKey: "overview.guide.recall.title",
    bodyKey: "overview.guide.recall.body",
    view: "recall",
  },
  {
    no: "05",
    titleKey: "overview.guide.history.title",
    bodyKey: "overview.guide.history.body",
    view: "history",
  },
  {
    no: "06",
    titleKey: "overview.guide.evolve.title",
    bodyKey: "overview.guide.evolve.body",
    view: "evolve",
  },
];

/* --------------------------------------------------------------------- The view */

/** The L0–L3 definition table: term glyph in code, prose in the dictionary. */
const LAYERS: { term: string; key: MessageKey }[] = [
  { term: "L0", key: "overview.layer.l0" },
  { term: "L1", key: "overview.layer.l1" },
  { term: "L2", key: "overview.layer.l2" },
  { term: "L3", key: "overview.layer.l3" },
];

export default function OverviewView() {
  const currentUser = useApp((s) => s.currentUser);
  const usersError = useApp((s) => s.usersError);
  const setView = useApp((s) => s.setView);
  const t = useT();

  // The live counts come from one bounded summary; the front matter never downloads the
  // whole of sources / jobs / dataset.
  const [summary, setSummary] = useState<WorkspaceSummary | null>(null);
  const [countsLoaded, setCountsLoaded] = useState(false);

  useEffect(() => {
    if (!currentUser) {
      setSummary(null);
      setCountsLoaded(false);
      return;
    }
    let live = true;
    setCountsLoaded(false);
    getWorkspaceSummary(currentUser)
      .then((result) => {
        if (!live) return;
        setSummary(result);
        setCountsLoaded(true);
      })
      .catch(() => {
        if (!live) return;
        setSummary(null);
        setCountsLoaded(true);
      });
    return () => {
      live = false;
    };
  }, [currentUser]);

  /** Three count states: loading null→Skeleton; no user / failed undefined→—; else the number. */
  const asCount = (loaded: boolean, value: number | null): number | null | undefined => {
    if (!currentUser) return undefined;
    if (!loaded) return null;
    return value ?? undefined;
  };

  const nodes: FlowNode[] = [
    {
      no: "§1",
      name: t("overview.flow.sources.name"),
      caption: t("overview.flow.sources.caption"),
      view: "sources",
      count: asCount(countsLoaded, summary?.sources ?? null),
      unit: t("overview.flow.sources.unit"),
    },
    {
      no: "§2",
      name: t("overview.flow.process.name"),
      caption: t("overview.flow.process.caption"),
      view: "process",
      count: asCount(countsLoaded, summary?.jobs ?? null),
      unit: t("overview.flow.process.unit"),
    },
    {
      no: "§3",
      name: t("overview.flow.library.name"),
      caption: t("overview.flow.library.caption"),
      view: "library",
      count: asCount(
        countsLoaded,
        summary ? summary.documents + summary.claims : null,
      ),
      unit: t("overview.flow.library.unit"),
    },
    {
      no: "§4",
      name: t("overview.flow.recall.name"),
      caption: t("overview.flow.recall.caption"),
      view: "recall",
      count: asCount(countsLoaded, summary?.snapshots ?? null),
      unit: t("overview.flow.recall.unit"),
    },
  ];

  return (
    <div className="flex flex-col gap-10">
      {usersError && (
        <Callout tone="warn" title={t("overview.offline.title")}>
          {t("overview.offline.body", { detail: usersError })}
        </Callout>
      )}

      {/* Title page + editor's note */}
      <header className="max-w-measure">
        <h1 className="font-serif text-30 text-balance text-ink sm:text-38">
          {t("overview.hero.title")}
        </h1>
        <p className="prose-lede mt-4">{t("overview.hero.lede")}</p>
      </header>

      {/* The ruled production-line diagram */}
      <section>
        <SectionRule no={1} title={t("overview.section.flow")} className="mb-6" />
        <FlowChart nodes={nodes} />
        <p className="mt-3 text-12 text-ink-3">{t("overview.flow.countNote")}</p>
      </section>

      {/* The L0–L3 definition table */}
      <section>
        <SectionRule no={2} title={t("overview.section.layers")} className="mb-2" />
        <DefinitionList
          termClassName="sm:w-28"
          items={LAYERS.map((layer) => ({
            term: <Mono>{layer.term}</Mono>,
            definition: t(layer.key),
          }))}
        />
      </section>

      {/* Reading guide */}
      <section>
        <SectionRule no={3} title={t("overview.section.guide")} className="mb-2" />
        <ol className="flex flex-col">
          {GUIDE.map((item) => (
            <li key={item.no} className="border-t border-line first:border-t-0">
              <button
                type="button"
                onClick={() => setView(item.view)}
                className={cn(
                  "group flex w-full items-baseline gap-3 py-3 text-left",
                  "transition-colors duration-120 ease-out hover:bg-hover",
                )}
              >
                <span className="w-7 shrink-0 font-mono text-12 text-accent">{item.no}</span>
                <span className="flex min-w-0 flex-1 flex-col gap-0.5 sm:flex-row sm:items-baseline sm:gap-3">
                  <span className="shrink-0 font-serif text-16 text-ink group-hover:text-accent sm:w-40">
                    {t(item.titleKey)}
                  </span>
                  <span className="min-w-0 flex-1 text-13 text-ink-2">{t(item.bodyKey)}</span>
                </span>
                <ArrowRight
                  size={14}
                  aria-hidden
                  className="shrink-0 self-center text-ink-3 group-hover:text-accent"
                />
              </button>
            </li>
          ))}
        </ol>
      </section>

      {/* Synthetic-data disclosure */}
      <section className="border-t border-line pt-6">
        <div className="flex flex-wrap items-center gap-3">
          <Stamp tone="neutral">SYNTHETIC DEMO DATA</Stamp>
          <p className="max-w-measure text-13 text-ink-2">{t("overview.synthetic.body")}</p>
        </div>
      </section>
    </div>
  );
}
