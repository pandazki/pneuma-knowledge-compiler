import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Database, Layers, PackageOpen } from "lucide-react";
import {
  crawlSources,
  fetchLocator,
  getSource,
  type SourceDetail,
  type SourceSummary,
} from "@/lib/api";
import { fmtCount, fmtDay, fmtTime } from "@/lib/format";
import {
  EMPTY_SOURCE_FILTER,
  filterSources,
  selectedDay,
  sortByTimeline,
  sourceDensity,
  sourceFacets,
  sourceTimeline,
  timelineBounds,
  toggleDay,
  type SourceFilter,
} from "@/lib/sourceFilter";
import { useApp } from "@/lib/store";
import { useT, useTOr, type TOrFunction } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Drawer } from "@/ui/Drawer";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { ScrollRegion } from "@/ui/ScrollRegion";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { Tabs } from "@/ui/Tabs";
import { ActivityHeatmap } from "@/components/ActivityHeatmap";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/ui/cn";
import { SourceFilterBar } from "./SourceFilterBar";
import { SourceKindName, SourceKindSummary, SourceReader } from "./SourceReaders";

/** The block range to highlight on the galley page (inclusive). */
interface BlockRange {
  start: number;
  end: number;
}

/** How many rows enter the DOM at once, and how many more each reveal adds. */
const REVEAL_STEP = 120;

/**
 * A calendar wide enough for a corpus's own time. The shared default covers a few months,
 * which suits a recency read; material replayed out of an archive reaches back further, and
 * cropping it would hide the very distribution the calendar is there to show.
 */
const CALENDAR_WEEKS = 54;

export default function SourcesView() {
  const t = useT();
  const tOr = useTOr();
  const currentUser = useApp((s) => s.currentUser);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const setView = useApp((s) => s.setView);

  const sourceSel = selection?.kind === "source" ? selection : null;

  const [catalogue, setCatalogue] = useState<SourceSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [listError, setListError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [filter, setFilter] = useState<SourceFilter>(EMPTY_SOURCE_FILTER);
  const [revealed, setRevealed] = useState(REVEAL_STEP);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(() => setReloadKey((k) => k + 1), []);
  const reveal = useCallback(() => setRevealed((n) => n + REVEAL_STEP), []);

  /**
   * The whole catalogue, in corpus-time order.
   *
   * Held client-side on purpose: the reader's question is a directory lookup over metadata
   * that is already small, and answering it locally is what makes the search answer as they
   * type. It arrives page by page and the list paints as it fills, so a five-figure inventory
   * is readable long before the tail lands.
   */
  useEffect(() => {
    if (!currentUser) {
      setCatalogue(null);
      setTotal(0);
      setSelectedId(null);
      setListError(null);
      return;
    }
    const controller = new AbortController();
    setListError(null);
    setCatalogue(null);
    setTotal(0);
    setLoading(true);
    crawlSources(currentUser, {
      signal: controller.signal,
      onProgress: (items, pageTotal) => {
        if (controller.signal.aborted) return;
        setCatalogue(sortByTimeline(items));
        setTotal(pageTotal);
      },
    })
      .then(() => {
        if (!controller.signal.aborted) setLoading(false);
      })
      .catch((e: Error) => {
        if (controller.signal.aborted) return;
        setLoading(false);
        setListError(e.message);
      });
    return () => controller.abort();
  }, [currentUser, reloadKey]);

  // A user switch is a different catalogue, so it is also a different question.
  useEffect(() => {
    setFilter(EMPTY_SOURCE_FILTER);
  }, [currentUser]);

  // Narrowing hands the reader a new list; it must start at its own top.
  useEffect(() => {
    setRevealed(REVEAL_STEP);
  }, [filter]);

  // deep link `#/sources/source/<id>/<block?>`: arriving by hash opens that galley.
  // (Citation jumps no longer land here — they open the global source sheet in place.)
  useEffect(() => {
    if (sourceSel) setSelectedId(sourceSel.id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceSel?.id, sourceSel?.block]);

  /** Closing gives the address bar back too, so the deep link does not outlive the sheet. */
  const closeGalley = useCallback(() => {
    setSelectedId(null);
    if (useApp.getState().selection?.kind === "source") select(null);
  }, [select]);

  const openGalley = useCallback(
    (sourceId: string) => {
      setSelectedId(sourceId);
      select({ kind: "source", id: sourceId });
    },
    [select],
  );

  const sources = catalogue ?? [];
  const hits = useMemo(() => filterSources(sources, filter), [sources, filter]);
  const facets = useMemo(() => sourceFacets(sources, filter), [sources, filter]);
  const bounds = useMemo(() => timelineBounds(sources), [sources]);
  /**
   * The calendar answers "where in time is what I am looking at" — so it shows the density
   * of everything the OTHER controls let through, with the pinned day marked. Redrawing it
   * from the range as well would leave one lit cell and nowhere to click next.
   */
  const density = useMemo(
    () => sourceDensity(filterSources(sources, { ...filter, from: null, to: null })),
    [sources, filter],
  );
  const kindLabels = useMemo(() => {
    const labels: Record<string, string> = {};
    for (const source of sources) {
      labels[source.kind] ??= tOr(`enum.sourceKind.${source.kind}`, source.kind);
    }
    return labels;
  }, [sources, tOr]);

  // Highlight range: a block carried by the selection (deep link) drives the galley;
  // citation jumps open the global source sheet and never pass through this view.
  const highlight: BlockRange | null =
    sourceSel && sourceSel.id === selectedId && sourceSel.block != null
      ? { start: sourceSel.block, end: sourceSel.block }
      : null;

  if (!currentUser) {
    return (
      <EmptyState
        icon={Database}
        title={t("sources.empty.noUser.title")}
        description={t("sources.empty.noUser.description")}
      />
    );
  }
  if (listError) {
    return <ErrorState title={t("sources.error.list")} error={listError} onRetry={load} />;
  }
  if (catalogue == null) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader
          title={t("nav.view.sources")}
          description={t("sources.descriptionShort")}
        />
        <SkeletonText lines={6} />
      </div>
    );
  }
  if (catalogue.length === 0) {
    return (
      <EmptyState
        icon={PackageOpen}
        title={t("sources.empty.none.title")}
        description={t("sources.empty.none.description")}
        action={
          <Button size="sm" onClick={() => setView("ingest")}>
            {t("sources.empty.none.action")}
          </Button>
        }
      />
    );
  }

  return (
    <>
      <PageHeader
        className="shrink-0"
        title={t("nav.view.sources")}
        description={t("sources.description")}
      />
      <ActivityHeatmap
        className="mb-4 shrink-0"
        days={density}
        maxWeeks={CALENDAR_WEEKS}
        title={`${t("sources.heatmap.title")} · ${t("sources.heatmap.hint")}`}
        kindLabels={kindLabels}
        selectedDate={selectedDay(filter)}
        onSelectDay={(date) => setFilter((current) => toggleDay(current, date))}
      />
      <SourceFilterBar
        filter={filter}
        onChange={setFilter}
        facets={facets}
        total={total || sources.length}
        hits={hits.length}
        bounds={bounds}
        loading={loading}
        loaded={sources.length}
      />

      {hits.length === 0 ? (
        <EmptyState
          icon={PackageOpen}
          title={t("sources.filter.noHits.title")}
          description={t("sources.filter.noHits.description")}
          action={
            <Button size="sm" variant="ghost" onClick={() => setFilter(EMPTY_SOURCE_FILTER)}>
              {t("sources.filter.clear")}
            </Button>
          }
        />
      ) : (
        <SourceCatalogue
          hits={hits}
          revealed={revealed}
          onReveal={reveal}
          selectedId={selectedId}
          onSelect={openGalley}
          tOr={tOr}
        />
      )}

      <Drawer
        open={selectedId != null}
        onOpenChange={(open) => {
          if (!open) closeGalley();
        }}
        side="right"
        title={t("sources.detail.title")}
        contentClassName="w-[min(48rem,100vw)]"
      >
        {selectedId && (
          <div className="p-5">
            <SourceGalley
              key={selectedId}
              userId={currentUser}
              sourceId={selectedId}
              highlight={highlight}
            />
          </div>
        )}
      </Drawer>
    </>
  );
}

/**
 * The catalogue list: one scroll region of its own (the scroll charter), revealing a window
 * of rows at a time. Five thousand buttons in the DOM would make every keystroke pay for
 * rows nobody has scrolled to; the window grows as the reader reaches the end of it, and a
 * button does the same job where an observer cannot run.
 */
function SourceCatalogue({
  hits,
  revealed,
  onReveal,
  selectedId,
  onSelect,
  tOr,
}: {
  hits: SourceSummary[];
  revealed: number;
  onReveal: () => void;
  selectedId: string | null;
  onSelect: (sourceId: string) => void;
  tOr: TOrFunction;
}) {
  const t = useT();
  const sentinel = useRef<HTMLLIElement>(null);
  const shown = Math.min(revealed, hits.length);
  const more = hits.length - shown;

  useEffect(() => {
    const node = sentinel.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) onReveal();
      },
      { rootMargin: "400px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [onReveal, shown]);

  return (
    <>
      <ScrollRegion
        as="ul"
        aria-label={t("sources.list.aria")}
        className="min-h-0 flex-1 border-b border-line"
      >
        {hits.slice(0, shown).map((source) => (
          <CatalogueRow
            key={source.source_id}
            source={source}
            selected={source.source_id === selectedId}
            onSelect={onSelect}
            tOr={tOr}
          />
        ))}
        {more > 0 && (
          <li ref={sentinel} className="flex justify-center py-3">
            <Button size="sm" variant="ghost" onClick={onReveal}>
              {t("sources.list.more", { count: Math.min(more, REVEAL_STEP) })}
            </Button>
          </li>
        )}
      </ScrollRegion>
      <p className="shrink-0 pt-2 text-12 text-ink-3">
        {t("sources.list.shown", {
          shown: fmtCount(shown),
          hits: fmtCount(hits.length),
        })}
      </p>
    </>
  );
}

function CatalogueRow({
  source,
  selected,
  onSelect,
  tOr,
}: {
  source: SourceSummary;
  selected: boolean;
  onSelect: (sourceId: string) => void;
  tOr: TOrFunction;
}) {
  const t = useT();
  const timeline = sourceTimeline(source);
  const digested = source.digested_at != null;
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        aria-current={selected ? "true" : undefined}
        aria-label={t("sources.list.openAria", { title: source.title })}
        onClick={() => onSelect(source.source_id)}
        className={cn(
          // The right padding keeps the digest dot clear of the region's hairline rail.
          "relative flex w-full items-baseline gap-3 py-2 pl-2 pr-3 text-left",
          "transition-colors duration-120 ease-out",
          selected ? "bg-accent-soft" : "hover:bg-hover",
        )}
      >
        {selected && (
          <span aria-hidden className="absolute inset-y-0 left-0 w-px bg-accent" />
        )}
        {/* The day the material happened — and, when that is unknown, a visible admission
            that the row is placed by its import instead. */}
        <span
          className="flex w-[7.5rem] shrink-0 items-baseline gap-1"
          title={
            timeline.basis === "occurred"
              ? t("sources.timeline.occurred")
              : t("sources.timeline.ingestedHint")
          }
        >
          <Mono
            className={cn("text-12", timeline.basis === "occurred" ? "text-ink-2" : "text-ink-3")}
          >
            {fmtDay(timeline.date)}
          </Mono>
          {timeline.basis === "ingested" && (
            <span className="text-11 text-ink-3" aria-label={t("sources.timeline.ingested")}>
              ≈
            </span>
          )}
        </span>

        <span className="min-w-0 flex-1 truncate text-14 text-ink">{source.title}</span>

        <span className="hidden shrink-0 items-baseline gap-1.5 sm:flex">
          <Badge>
            <SourceKindName kind={source.kind} />
          </Badge>
          <Badge>{tOr(`enum.sourceClass.${source.source_class}`, source.source_class)}</Badge>
        </span>
        <Mono className="w-[4.5rem] shrink-0 text-right text-12 whitespace-nowrap text-ink-3">
          {fmtCount(source.block_count)} blk
        </Mono>
        <span
          aria-label={t(digested ? "sources.directory.digested" : "sources.directory.undigested")}
          title={t(digested ? "sources.directory.digested" : "sources.directory.undigested")}
          className={cn(
            "size-1.5 shrink-0 self-center rounded-full border",
            digested ? "border-accent bg-accent" : "border-line-2",
          )}
        />
      </button>
    </li>
  );
}

/** One source's galley page: the intake_plan table, the structure map, the raw blocks. */
function SourceGalley({
  userId,
  sourceId,
  highlight,
}: {
  userId: string;
  sourceId: string;
  highlight: BlockRange | null;
}) {
  const t = useT();
  const tOr = useTOr();
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [exact, setExact] = useState<{ block: number; text: string } | null>(null);
  const [fetching, setFetching] = useState(false);
  const [activeTab, setActiveTab] = useState("source");
  const blockRefs = useRef<Map<number, HTMLElement>>(new Map());

  const load = useCallback(async () => {
    setError(null);
    setDetail(null);
    setExact(null);
    try {
      setDetail(await getSource(userId, sourceId));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [userId, sourceId]);

  useEffect(() => {
    void load();
  }, [load]);

  // Span landing: once the detail is in, scroll the target block range into view.
  useEffect(() => {
    if (!detail || !highlight) return;
    blockRefs.current.get(highlight.start)?.scrollIntoView({
      block: "center",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [activeTab, detail, highlight]);

  const inRange = (index: number) =>
    highlight != null && index >= highlight.start && index <= highlight.end;

  const blockRef = (index: number) => (element: HTMLElement | null) => {
    if (element) blockRefs.current.set(index, element);
    else blockRefs.current.delete(index);
  };

  // Clicking a block: fetchLocator returns that block's exact span (shown in a Callout).
  async function onFetchBlock(index: number) {
    setFetching(true);
    try {
      const res = await fetchLocator(userId, sourceId, { blocks: [index, index] });
      setExact({ block: index, text: res.text });
    } catch (e) {
      setExact({
        block: index,
        text: t("common.sourceSpan.fetchFailed", { detail: (e as Error).message }),
      });
    } finally {
      setFetching(false);
    }
  }

  if (error) {
    return (
      <ErrorState title={t("sources.error.detail")} error={error} onRetry={() => void load()} />
    );
  }
  if (!detail) {
    return <SkeletonText lines={10} />;
  }

  return (
    <article className="flex flex-col gap-6">
      {/* header: title + metadata */}
      <header className="flex flex-col gap-3 border-b border-line pb-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
          <div className="min-w-0">
            <p className="mb-1 flex flex-wrap items-center gap-1.5">
              <Badge tone="accent">
                <SourceKindName kind={detail.kind} />
              </Badge>
              <Badge>{tOr(`enum.sourceOrigin.${detail.origin}`, detail.origin)}</Badge>
              <Badge>{tOr(`enum.sourceClass.${detail.source_class}`, detail.source_class)}</Badge>
            </p>
            <h2 className="font-serif text-24 text-balance text-ink">{detail.title}</h2>
            <p className="mt-1 text-13 text-ink-2">
              <SourceKindSummary detail={detail} />
            </p>
          </div>
          <p className="flex shrink-0 flex-col items-start gap-0.5 text-12 text-ink-3 sm:items-end">
            <Mono>{fmtTime(detail.created_at)}</Mono>
            <span>{detail.mime}</span>
          </p>
        </div>
        <Mono className="break-all text-12 text-ink-3">{detail.source_id}</Mono>
      </header>

      {exact && (
        <Callout
          tone="notice"
          title={<Mono>{t("sources.exactSpan.title", { block: exact.block })}</Mono>}
          onDismiss={() => setExact(null)}
        >
          <p className="prose whitespace-pre-wrap">{exact.text}</p>
        </Callout>
      )}

      <Tabs
        value={activeTab}
        onChange={setActiveTab}
        aria-label={t("sources.tabs.aria")}
        tabs={[
          {
            value: "source",
            label: t("sources.tabs.source"),
            panel: (
              <SourceReader
                detail={detail}
                inRange={inRange}
                onFetchBlock={(index) => void onFetchBlock(index)}
                blockRef={blockRef}
                fetching={fetching}
              />
            ),
          },
          {
            value: "compiler",
            label: t("sources.tabs.compiler"),
            panel: (
              <CompilerGalley
                detail={detail}
                inRange={inRange}
                onFetchBlock={(index) => void onFetchBlock(index)}
                blockRef={blockRef}
                fetching={fetching}
              />
            ),
          },
        ]}
      />
    </article>
  );
}

function CompilerGalley({
  detail,
  inRange,
  onFetchBlock,
  blockRef,
  fetching,
}: {
  detail: SourceDetail;
  inRange: (index: number) => boolean;
  onFetchBlock: (index: number) => void;
  blockRef: (index: number) => (element: HTMLElement | null) => void;
  fetching: boolean;
}) {
  const t = useT();
  return (
    <div className="flex flex-col gap-8">
      {detail.intake_plan && (
        <section className="flex flex-col gap-3">
          <SectionRule no={1} title={t("sources.compiler.plan")} />
          <DefinitionList
            termClassName="sm:w-48"
            items={[
              {
                term: "canonical_treatment",
                definition: <Mono>{detail.intake_plan.canonical_treatment}</Mono>,
              },
              {
                term: "semantic_indexing",
                definition: <Mono>{detail.intake_plan.semantic_indexing}</Mono>,
              },
              {
                term: t("sources.compiler.confirmTerm"),
                definition: detail.intake_plan.user_confirmed
                  ? t("sources.compiler.confirmed")
                  : t("sources.compiler.proposed"),
              },
              { term: "rationale", definition: detail.intake_plan.rationale },
            ]}
          />
        </section>
      )}

      {detail.structure.sections.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionRule no={2} title={t("sources.compiler.structure")} />
          <ul className="flex flex-col border-y border-line">
            {detail.structure.sections.map((sec, i) => {
              const depth = Math.max(0, sec.path.length - 1);
              const label = sec.path[sec.path.length - 1] ?? "(root)";
              return (
                <li
                  key={i}
                  className="flex items-baseline gap-3 border-b border-line py-1.5 last:border-b-0"
                  style={{ paddingLeft: `${depth * 16}px` }}
                >
                  <span className="min-w-0 flex-1 truncate text-14 text-ink">{label}</span>
                  <Mono className="shrink-0 text-12 text-ink-3">
                    b{sec.start_block}–b{sec.end_block}
                  </Mono>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <section className="flex flex-col gap-3">
        <SectionRule
          no={3}
          title={t("sources.compiler.blocks", { count: detail.blocks.length })}
          actions={
            <span className="text-12 text-ink-3">
              <Layers size={12} aria-hidden className="mr-1 inline-block align-[-2px]" />
              {t("sources.compiler.blocksHint")}
            </span>
          }
        />
        <ol className="flex flex-col border-y border-line">
          {detail.blocks.map((block) => (
            <li
              key={block.index}
              ref={blockRef(block.index)}
              className={cn(
                "flex gap-3 border-b border-line px-2 py-2 last:border-b-0",
                inRange(block.index) && "bg-accent-soft",
              )}
            >
              <button
                type="button"
                disabled={fetching}
                onClick={() => onFetchBlock(block.index)}
                aria-label={t("sources.block.fetchAria", { index: block.index })}
                title={t("sources.block.fetchTitle")}
                className="shrink-0 rounded-1 px-1 pt-0.5 text-right text-ink-3 hover:bg-hover hover:text-accent disabled:opacity-45"
              >
                <Mono className="text-12">b{block.index}</Mono>
              </button>
              <p className="prose min-w-0 whitespace-pre-wrap text-14">{block.text}</p>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
