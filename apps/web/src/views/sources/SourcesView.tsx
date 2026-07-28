import { useCallback, useEffect, useRef, useState } from "react";
import { Database, FileText, Layers, PackageOpen } from "lucide-react";
import {
  fetchLocator,
  getSource,
  listSources,
  type SourceDetail,
  type SourceSummary,
} from "@/lib/api";
import { fmtTime } from "@/lib/format";
import { useApp } from "@/lib/store";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/ui/cn";

/** 校样页上待高亮的 block 区间（闭区间）。 */
interface BlockRange {
  start: number;
  end: number;
}

export default function SourcesView() {
  const currentUser = useApp((s) => s.currentUser);
  const sourceFocus = useApp((s) => s.sourceFocus);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const setView = useApp((s) => s.setView);

  const sourceSel = selection?.kind === "source" ? selection : null;

  const [sources, setSources] = useState<SourceSummary[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(() => setReloadKey((k) => k + 1), []);

  // source 目录：随用户切换 / 手动重试重载。
  useEffect(() => {
    if (!currentUser) {
      setSources(null);
      setListError(null);
      setSelectedId(null);
      return;
    }
    let live = true;
    setListError(null);
    listSources(currentUser)
      .then((rows) => {
        if (!live) return;
        setSources(rows);
        // 落点优先级：deep-link selection > store.sourceFocus > 上次选中 > 第一条。
        setSelectedId((prev) => {
          if (sourceSel && rows.some((r) => r.source_id === sourceSel.id)) return sourceSel.id;
          const focus = sourceFocus?.sourceId;
          if (focus && rows.some((r) => r.source_id === focus)) return focus;
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
  }, [currentUser, reloadKey]);

  // 跨视图落点（recall/ask/cue 的 focusSource）：选中目标 source，只读消费、不动 hash。
  useEffect(() => {
    if (sourceFocus && sources?.some((r) => r.source_id === sourceFocus.sourceId)) {
      setSelectedId(sourceFocus.sourceId);
    }
  }, [sourceFocus, sources]);

  // deep-link `#/sources/source/<id>/<block?>`：hash 进入时选中对应 source。
  useEffect(() => {
    if (sourceSel && sources?.some((r) => r.source_id === sourceSel.id)) {
      setSelectedId(sourceSel.id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceSel?.id, sourceSel?.block, sources]);

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

  const selectedMissing =
    !!sourceSel && sources != null && !sources.some((r) => r.source_id === sourceSel.id);

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

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="原料 Sources"
        description="编译的输入：左为 source 目录，右为选中条的校样页——结构地图与原文 blocks。"
      />
      <div className="flex flex-col gap-6 md:flex-row md:items-start">
        {/* 左栏：source 目录 */}
        <aside className="w-full shrink-0 md:w-72">
          <p className="mb-2 text-12 text-ink-3">目录 · {sources.length} 条</p>
          <ul className="flex flex-col border-y border-line">
            {sources.map((s) => {
              const selected = s.source_id === selectedId;
              return (
                <li key={s.source_id} className="border-b border-line last:border-b-0">
                  <button
                    type="button"
                    onClick={() => {
                      setSelectedId(s.source_id);
                      select({ kind: "source", id: s.source_id });
                    }}
                    className={cn(
                      "relative flex w-full flex-col gap-1.5 px-3 py-2.5 text-left",
                      "transition-colors duration-120 ease-out",
                      selected ? "bg-accent-soft" : "hover:bg-hover",
                    )}
                  >
                    {selected && (
                      <span aria-hidden className="absolute inset-y-0 left-0 w-0.5 bg-accent" />
                    )}
                    <span className="flex min-w-0 items-baseline gap-2">
                      <span className="min-w-0 flex-1 truncate text-14 font-medium text-ink">
                        {s.title}
                      </span>
                      <Mono className="shrink-0 text-12 text-ink-3">{s.block_count} blk</Mono>
                    </span>
                    <span className="flex flex-wrap items-center gap-1.5">
                      <Badge>{s.kind}</Badge>
                      <Badge>{s.source_class}</Badge>
                    </span>
                    <span className="text-12 text-ink-3">
                      {s.digested_at ? (
                        <>
                          已消化 · <Mono>{fmtTime(s.digested_at)}</Mono>
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
        </aside>

        {/* 右栏：校样页 */}
        <div className="min-w-0 flex-1">
          {selectedMissing ? (
            <EmptyState
              icon={FileText}
              title="原文已不可用"
              description="溯源链接指向的 source 不在当前用户的原料目录中——可能已被删除或属于其他用户。"
            />
          ) : selectedId ? (
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
  const blockRefs = useRef<Map<number, HTMLLIElement>>(new Map());

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
      behavior: "smooth",
    });
  }, [detail, highlight]);

  const inRange = (index: number) =>
    highlight != null && index >= highlight.start && index <= highlight.end;

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
      <header className="flex flex-col gap-2">
        <h2 className="font-serif text-20 text-balance text-ink">{detail.title}</h2>
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-12 text-ink-3">
          <Mono className="break-all">{detail.source_id}</Mono>
          <span>{detail.mime}</span>
          <Mono>{fmtTime(detail.created_at)}</Mono>
        </p>
        <p className="flex flex-wrap items-center gap-1.5">
          <Badge>{detail.kind}</Badge>
          <Badge>{detail.source_class}</Badge>
        </p>
      </header>

      {/* 编译计划 */}
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

      {/* 结构地图 */}
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

      {/* 原文 blocks */}
      <section className="flex flex-col gap-3">
        <SectionRule
          no={3}
          title={`原文 · ${detail.blocks.length} blocks`}
          actions={
            <span className="text-12 text-ink-3">
              <Layers size={12} aria-hidden className="mr-1 inline-block align-[-2px]" />
              点击块号取精确段
            </span>
          }
        />
        {exact && (
          <Callout
            tone="notice"
            title={<Mono>{`b${exact.block} · 精确段`}</Mono>}
            onDismiss={() => setExact(null)}
          >
            <p className="prose whitespace-pre-wrap">{exact.text}</p>
          </Callout>
        )}
        <ol className="flex flex-col border-y border-line">
          {detail.blocks.map((b) => (
            <li
              key={b.index}
              ref={(el) => {
                if (el) blockRefs.current.set(b.index, el);
                else blockRefs.current.delete(b.index);
              }}
              className={cn(
                "flex gap-3 border-b border-line px-2 py-2 last:border-b-0",
                inRange(b.index) && "bg-accent-soft",
              )}
            >
              <button
                type="button"
                disabled={fetching}
                onClick={() => void onFetchBlock(b.index)}
                aria-label={`取 block ${b.index} 精确段`}
                title="fetch 精确段"
                className="shrink-0 pt-0.5 text-right disabled:opacity-45"
              >
                <Mono className="text-12 text-ink-3 hover:text-accent">b{b.index}</Mono>
              </button>
              <p className="prose min-w-0 text-14 whitespace-pre-wrap">
                {b.text}
              </p>
            </li>
          ))}
        </ol>
      </section>
    </article>
  );
}
