import { useCallback, useEffect, useRef, useState } from "react";
import { Database, FileText, Layers, PackageOpen } from "lucide-react";
import {
  fetchLocator,
  getSourceActivity,
  getSource,
  listSources,
  type ActivityDay,
  type SourceDetail,
  type SourceSummary,
} from "@/lib/api";
import { fmtTime } from "@/lib/format";
import {
  firstPage,
  nextPage,
  previousPage,
  type CursorPageState,
  type Page,
} from "@/lib/pagination";
import { useApp } from "@/lib/store";
import { useT } from "@/lib/useT";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { Drawer } from "@/ui/Drawer";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { Tabs } from "@/ui/Tabs";
import { ActivityHeatmap } from "@/components/ActivityHeatmap";
import { PageHeader } from "@/components/PageHeader";
import { PaginationBar } from "@/components/PaginationBar";
import { cn } from "@/ui/cn";
import { SourceKindName, SourceKindSummary, SourceReader } from "./SourceReaders";

/** The block range to highlight on the galley page (inclusive). */
interface BlockRange {
  start: number;
  end: number;
}

const PAGE_SIZE = 25;

export default function SourcesView() {
  const t = useT();
  const currentUser = useApp((s) => s.currentUser);
  const sourceFocus = useApp((s) => s.sourceFocus);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const setView = useApp((s) => s.setView);

  const sourceSel = selection?.kind === "source" ? selection : null;

  const [sourcePage, setSourcePage] = useState<Page<SourceSummary> | null>(null);
  const [pageState, setPageState] = useState<CursorPageState>(firstPage);
  const [listError, setListError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [directoryOpen, setDirectoryOpen] = useState(false);
  const [activityDays, setActivityDays] = useState<ActivityDay[]>([]);
  const detailTopRef = useRef<HTMLDivElement>(null);

  const sources = sourcePage?.items ?? null;

  const load = useCallback(() => {
    setPageState(firstPage());
    setReloadKey((k) => k + 1);
  }, []);

  const chooseSource = useCallback(
    (sourceId: string) => {
      setSelectedId(sourceId);
      select({ kind: "source", id: sourceId });
      setDirectoryOpen(false);
      requestAnimationFrame(() => {
        detailTopRef.current?.scrollIntoView({
          block: "start",
          behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "auto"
            : "smooth",
        });
      });
    },
    [select],
  );

  useEffect(() => {
    setPageState(firstPage());
  }, [currentUser]);

  useEffect(() => {
    if (!currentUser) {
      setActivityDays([]);
      return;
    }
    let live = true;
    void getSourceActivity(currentUser)
      .then((calendar) => {
        if (live) setActivityDays(calendar.days);
      })
      .catch(() => {
        if (live) setActivityDays([]);
      });
    return () => {
      live = false;
    };
  }, [currentUser, reloadKey]);

  // The source catalogue: reloads on a user switch or a manual retry.
  useEffect(() => {
    if (!currentUser) {
      setSourcePage(null);
      setListError(null);
      setSelectedId(null);
      return;
    }
    let live = true;
    setListError(null);
    setSourcePage(null);
    listSources(currentUser, { limit: PAGE_SIZE, cursor: pageState.cursor })
      .then((page) => {
        if (!live) return;
        const rows = page.items;
        setSourcePage(page);
        // Landing priority: deep-link selection > store.sourceFocus > last pick > first row.
        setSelectedId((prev) => {
          if (sourceSel) return sourceSel.id;
          const focus = sourceFocus?.sourceId;
          if (focus) return focus;
          if (prev && rows.some((r) => r.source_id === prev)) return prev;
          return rows[0]?.source_id ?? null;
        });
      })
      .catch((e: Error) => {
        if (!live) return;
        setListError(e.message);
      });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentUser, pageState.cursor, reloadKey]);

  // Cross-view landing (focusSource from recall/ask/suggestion): select the target source.
  // Read-only consumption — the hash is left alone.
  useEffect(() => {
    if (sourceFocus) {
      setSelectedId(sourceFocus.sourceId);
    }
  }, [sourceFocus]);

  // deep link `#/sources/source/<id>/<block?>`: arriving by hash selects that source.
  useEffect(() => {
    if (sourceSel) {
      setSelectedId(sourceSel.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceSel?.id, sourceSel?.block]);

  // Highlight range: a block carried by the selection wins, then sourceFocus's span.
  const highlight: BlockRange | null =
    sourceSel && sourceSel.id === selectedId && sourceSel.block != null
      ? { start: sourceSel.block, end: sourceSel.block }
      : sourceFocus &&
          sourceFocus.sourceId === selectedId &&
          sourceFocus.blockStart != null
        ? {
            start: sourceFocus.blockStart,
            end: sourceFocus.blockEnd ?? sourceFocus.blockStart,
          }
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
  if (sources == null) {
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
  if (sources.length === 0) {
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

  const directory = (
    <SourceDirectory
      sources={sources}
      total={sourcePage?.page.total ?? sources.length}
      selectedId={selectedId}
      pageIndex={pageState.previous.length}
      hasNext={sourcePage?.page.next_cursor != null}
      onSelect={chooseSource}
      onPrevious={() => setPageState((state) => previousPage(state))}
      onNext={() => {
        const cursor = sourcePage?.page.next_cursor;
        if (cursor) setPageState((state) => nextPage(state, cursor));
      }}
    />
  );

  return (
    <>
      <PageHeader
        title={t("nav.view.sources")}
        description={t("sources.description")}
        actions={
          <Button
            size="sm"
            variant="ghost"
            className="xl:hidden"
            onClick={() => setDirectoryOpen(true)}
          >
            <FileText size={14} aria-hidden />
            {t("sources.switchSource")}
          </Button>
        }
      />
      <ActivityHeatmap
        className="mb-6"
        days={activityDays}
        title={t("sources.heatmap.title")}
        kindLabels={{
          meeting: t("sources.heatmap.kind.meeting"),
          document_library: t("sources.heatmap.kind.document_library"),
          im: t("sources.heatmap.kind.im"),
          email: t("sources.heatmap.kind.email"),
        }}
      />
      <div className="xl:grid xl:grid-cols-[18rem_minmax(0,1fr)] xl:items-start xl:gap-8">
        <aside className="sticky top-16 hidden h-[calc(100dvh-5rem)] min-h-0 overflow-hidden xl:block">
          {directory}
        </aside>

        <div ref={detailTopRef} className="min-w-0 scroll-mt-16">
          {selectedId ? (
            <SourceGalley
              key={selectedId}
              userId={currentUser}
              sourceId={selectedId}
              highlight={highlight}
            />
          ) : (
            <EmptyState icon={FileText} title={t("sources.empty.pick")} />
          )}
        </div>
      </div>
      <Drawer
        open={directoryOpen}
        onOpenChange={setDirectoryOpen}
        side="bottom"
        title={t("sources.chooseSource")}
        contentClassName="h-[min(44rem,85dvh)] max-h-[85dvh]"
      >
        <div className="h-full min-h-0 p-4">{directory}</div>
      </Drawer>
    </>
  );
}

function SourceDirectory({
  sources,
  total,
  selectedId,
  pageIndex,
  hasNext,
  onSelect,
  onPrevious,
  onNext,
}: {
  sources: SourceSummary[];
  total: number;
  selectedId: string | null;
  pageIndex: number;
  hasNext: boolean;
  onSelect: (sourceId: string) => void;
  onPrevious: () => void;
  onNext: () => void;
}) {
  const t = useT();
  return (
    <div className="flex h-full min-h-0 flex-col">
      <p className="shrink-0 pb-2 text-12 text-ink-3">
        {t("sources.directory.count", { total })}
      </p>
      <ul className="min-h-0 flex-1 overflow-y-auto overscroll-y-contain border-y border-line">
        {sources.map((source) => {
          const selected = source.source_id === selectedId;
          return (
            <li key={source.source_id} className="border-b border-line last:border-b-0">
              <button
                type="button"
                aria-current={selected ? "true" : undefined}
                onClick={() => onSelect(source.source_id)}
                className={cn(
                  "relative flex w-full flex-col gap-1.5 px-3 py-2.5 text-left",
                  "transition-colors duration-120 ease-out",
                  selected ? "bg-accent-soft" : "hover:bg-hover",
                )}
              >
                {selected && (
                  <span aria-hidden className="absolute inset-y-0 left-0 w-px bg-accent" />
                )}
                <span className="flex min-w-0 items-baseline gap-2">
                  <span className="min-w-0 flex-1 truncate text-14 font-medium text-ink">
                    {source.title}
                  </span>
                  <Mono className="shrink-0 text-12 text-ink-3">
                    {source.block_count} blk
                  </Mono>
                </span>
                <span className="flex flex-wrap items-center gap-1.5">
                  <Badge>
                    <SourceKindName kind={source.kind} />
                  </Badge>
                  <Badge>{source.origin}</Badge>
                </span>
                <span className="text-12 text-ink-3">
                  {source.digested_at ? (
                    <>
                      {t("sources.directory.digested")} ·{" "}
                      <Mono>{fmtTime(source.digested_at)}</Mono>
                    </>
                  ) : (
                    t("sources.directory.undigested")
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
      <div className="shrink-0 pt-3">
        <PaginationBar
          pageIndex={pageIndex}
          limit={PAGE_SIZE}
          itemCount={sources.length}
          total={total}
          hasNext={hasNext}
          noun={t("sources.directory.noun")}
          onPrevious={onPrevious}
          onNext={onNext}
        />
      </div>
    </div>
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
              <Badge>{detail.origin}</Badge>
              <Badge>{detail.source_class}</Badge>
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
