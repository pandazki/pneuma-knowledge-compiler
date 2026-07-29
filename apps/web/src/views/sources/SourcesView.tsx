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

/** 校样页上待高亮的 block 区间（闭区间）。 */
interface BlockRange {
  start: number;
  end: number;
}

const PAGE_SIZE = 25;

export default function SourcesView() {
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

  // source 目录：随用户切换 / 手动重试重载。
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
        // 落点优先级：deep-link selection > store.sourceFocus > 上次选中 > 第一条。
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

  // 跨视图落点（recall/ask/suggestion 的 focusSource）：选中目标 source，只读消费、不动 hash。
  useEffect(() => {
    if (sourceFocus) {
      setSelectedId(sourceFocus.sourceId);
    }
  }, [sourceFocus]);

  // deep-link `#/sources/source/<id>/<block?>`：hash 进入时选中对应 source。
  useEffect(() => {
    if (sourceSel) {
      setSelectedId(sourceSel.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceSel?.id, sourceSel?.block]);

  // 高亮区间：selection 带的 block 优先，其次 sourceFocus 的 span。
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
        title="未选择用户"
        description="先在顶栏选择一个 user_id，再查看它的原料目录。"
      />
    );
  }
  if (listError) {
    return <ErrorState title="加载原料目录失败" error={listError} onRetry={load} />;
  }
  if (sources == null) {
    return (
      <div className="flex flex-col gap-4">
        <PageHeader title="原料 Sources" description="编译的输入：每条 source 的校样与消化态。" />
        <SkeletonText lines={6} />
      </div>
    );
  }
  if (sources.length === 0) {
    return (
      <EmptyState
        icon={PackageOpen}
        title="还没有原料"
        description="去「导入 Ingest」添加第一条 source，再回来查看它的校样页。"
        action={
          <Button size="sm" onClick={() => setView("ingest")}>
            去导入
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
        title="原料 Sources"
        description="浏览会议、文档库、即时消息与邮件的来源原貌；切换到编译校样可审计 intake plan、结构与 block 落点。"
        actions={
          <Button
            size="sm"
            variant="ghost"
            className="xl:hidden"
            onClick={() => setDirectoryOpen(true)}
          >
            <FileText size={14} aria-hidden />
            切换来源
          </Button>
        }
      />
      <ActivityHeatmap
        className="mb-6"
        days={activityDays}
        title="来源密度"
        kindLabels={{
          meeting: "会议",
          document_library: "文档",
          im: "IM",
          email: "邮件",
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
            <EmptyState icon={FileText} title="在左侧目录选择一条 source" />
          )}
        </div>
      </div>
      <Drawer
        open={directoryOpen}
        onOpenChange={setDirectoryOpen}
        side="bottom"
        title="选择来源"
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
  return (
    <div className="flex h-full min-h-0 flex-col">
      <p className="shrink-0 pb-2 text-12 text-ink-3">目录 · {total} 条</p>
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
                      已消化 · <Mono>{fmtTime(source.digested_at)}</Mono>
                    </>
                  ) : (
                    "未消化"
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
          noun="条 source"
          onPrevious={onPrevious}
          onNext={onNext}
        />
      </div>
    </div>
  );
}

/** 单条 source 的校样页：intake_plan 定义表 + 结构地图 + 原文 blocks。 */
function SourceGalley({
  userId,
  sourceId,
  highlight,
}: {
  userId: string;
  sourceId: string;
  highlight: BlockRange | null;
}) {
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

  // span 落点：详情就绪后把目标 block 区间滚动进视野。
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

  // 点击 block：fetchLocator 取该块的精确段（Callout 呈现）。
  async function onFetchBlock(index: number) {
    setFetching(true);
    try {
      const res = await fetchLocator(userId, sourceId, { blocks: [index, index] });
      setExact({ block: index, text: res.text });
    } catch (e) {
      setExact({ block: index, text: `fetch 失败：${(e as Error).message}` });
    } finally {
      setFetching(false);
    }
  }

  if (error) {
    return <ErrorState title="加载 source 详情失败" error={error} onRetry={() => void load()} />;
  }
  if (!detail) {
    return <SkeletonText lines={10} />;
  }

  return (
    <article className="flex flex-col gap-6">
      {/* 页头：标题 + 元信息 */}
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
          title={<Mono>{`b${exact.block} · 精确段`}</Mono>}
          onDismiss={() => setExact(null)}
        >
          <p className="prose whitespace-pre-wrap">{exact.text}</p>
        </Callout>
      )}

      <Tabs
        value={activeTab}
        onChange={setActiveTab}
        aria-label="来源详情视图"
        tabs={[
          {
            value: "source",
            label: "来源视图",
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
            label: "编译校样",
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
  return (
    <div className="flex flex-col gap-8">
      {detail.intake_plan && (
        <section className="flex flex-col gap-3">
          <SectionRule no={1} title="编译计划" />
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
                term: "确认状态",
                definition: detail.intake_plan.user_confirmed
                  ? "用户已确认"
                  : "系统提案（未人工确认）",
              },
              { term: "rationale", definition: detail.intake_plan.rationale },
            ]}
          />
        </section>
      )}

      {detail.structure.sections.length > 0 && (
        <section className="flex flex-col gap-3">
          <SectionRule no={2} title="结构地图" />
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
          title={`归一化原文 · ${detail.blocks.length} blocks`}
          actions={
            <span className="text-12 text-ink-3">
              <Layers size={12} aria-hidden className="mr-1 inline-block align-[-2px]" />
              点击块号取精确段
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
                aria-label={`取 block ${block.index} 精确段`}
                title="取精确原文段"
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
