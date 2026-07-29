import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { FileDiff, Inbox, UserRound } from "lucide-react";
import {
  getHistoryActivity,
  listHistory,
  type ActivityDay,
  type HistoryPage,
} from "@/lib/api";
import {
  normalizeHistoryItem,
  type HistoryTimelineItem,
} from "@/lib/history";
import { useApp } from "@/lib/store";
import type { PatchRecord, SidecarClaimRef } from "@/lib/types";
import { patchChanges, type Model } from "@/lib/model";
import { escalationText } from "@/lib/claim";
import { fmtTime, fmtTokens, shortSha } from "@/lib/format";
import {
  firstPage,
  nextPage,
  previousPage,
  type CursorPageState,
} from "@/lib/pagination";
import { PageHeader } from "@/components/PageHeader";
import { PaginationBar } from "@/components/PaginationBar";
import { ActivityHeatmap } from "@/components/ActivityHeatmap";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { Callout } from "@/ui/Callout";
import { DefinitionList } from "@/ui/DefinitionList";
import { EmptyState } from "@/ui/EmptyState";
import { ErrorState } from "@/ui/ErrorState";
import { Mono } from "@/ui/Mono";
import { SectionRule } from "@/ui/SectionRule";
import { SkeletonText } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";

const PAGE_SIZE = 25;

type PatchTimelineItem = Extract<HistoryTimelineItem, { kind: "patch" }>;

function isPatchItem(item: HistoryTimelineItem): item is PatchTimelineItem {
  return item.kind === "patch";
}

export default function HistoryView() {
  const currentUser = useApp((s) => s.currentUser);
  const model = useApp((s) => s.model);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const setView = useApp((s) => s.setView);

  const [historyPage, setHistoryPage] = useState<HistoryPage | null>(null);
  const [pageState, setPageState] = useState<CursorPageState>(firstPage);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const [activityDays, setActivityDays] = useState<ActivityDay[]>([]);
  const detailRef = useRef<HTMLDivElement>(null);

  const reload = useCallback(() => {
    setPageState(firstPage());
    setReloadKey((key) => key + 1);
  }, []);

  const selectPatch = useCallback(
    (patchId: string) => {
      select({ kind: "patch", id: patchId });
      if (window.matchMedia("(max-width: 1023px)").matches) {
        window.requestAnimationFrame(() => {
          detailRef.current?.scrollIntoView({
            behavior: "smooth",
            block: "start",
          });
        });
      }
    },
    [select],
  );

  useEffect(() => {
    setPageState(firstPage());
    setHistoryPage(null);
    setLoadError(null);
  }, [currentUser]);

  useEffect(() => {
    if (!currentUser) {
      setActivityDays([]);
      return;
    }
    let live = true;
    void getHistoryActivity(currentUser, "patch")
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

  useEffect(() => {
    if (!currentUser) {
      setHistoryPage(null);
      setLoading(false);
      return;
    }
    let live = true;
    setLoading(true);
    void listHistory(currentUser, {
      limit: PAGE_SIZE,
      cursor: pageState.cursor,
      kind: "patch",
    })
      .then((page) => {
        if (!live) return;
        setHistoryPage(page);
        setLoadError(null);
      })
      .catch((error: unknown) => {
        if (!live) return;
        setLoadError((error as Error).message);
      })
      .finally(() => {
        if (live) setLoading(false);
      });
    return () => {
      live = false;
    };
  }, [currentUser, pageState.cursor, reloadKey]);

  const items = useMemo(
    () =>
      (historyPage?.items.map(normalizeHistoryItem) ?? []).filter(isPatchItem),
    [historyPage],
  );
  const selected =
    (selection?.kind === "patch"
      ? items.find((item) => item.ref === selection.id)
      : null) ??
    items[0] ??
    null;

  if (!currentUser) {
    return (
      <>
        <PageHeader
          title="版本 History"
          description="查看知识库每一次可追溯的内容变化。"
        />
        <EmptyState
          icon={UserRound}
          title="未选择用户"
          description="先在顶栏选择一个 user_id，再查看它的知识版本。"
        />
      </>
    );
  }

  const patchCount = historyPage?.counts.patches;
  const headerDescription =
    patchCount == null
      ? "查看知识库每一次可追溯的内容变化。"
      : `${patchCount} 个知识版本，按编译时间倒序。运行任务请前往「工序 Process」查看。`;

  return (
    <>
      <div className="mb-6 grid gap-5 border-b border-line pb-5 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
        <PageHeader
          className="mb-0 lg:pt-1"
          title="版本 History"
          description={headerDescription}
        />
        <ActivityHeatmap
          compact
          className="max-w-full lg:w-96"
          days={activityDays}
          title="版本编译密度"
          kindLabels={{ patch: "知识版本" }}
        />
      </div>
      {loadError ? (
        <ErrorState
          title="加载知识变更失败"
          error={loadError}
          onRetry={reload}
        />
      ) : historyPage == null ? (
        <SkeletonText lines={9} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="还没有知识版本"
          description="这个知识库尚未产生内容变化。导入原料并完成编译后，每次知识更新都会在这里留下可读的差异。"
          action={
            <Button size="sm" onClick={() => setView("ingest")}>
              去导入
            </Button>
          }
        />
      ) : (
        <div
          className="flex flex-col gap-6 lg:flex-row lg:items-start"
          aria-busy={loading}
        >
          <div className="flex w-full shrink-0 flex-col gap-3 lg:w-80">
            <ol className="border-y border-line">
              {items.map((item) => (
                <TimelineRow
                  key={item.ref}
                  item={item}
                  model={model}
                  selected={selected?.ref === item.ref}
                  onSelect={() => selectPatch(item.ref)}
                />
              ))}
            </ol>
            <PaginationBar
              pageIndex={pageState.previous.length}
              limit={PAGE_SIZE}
              itemCount={items.length}
              total={historyPage.page.total}
              hasNext={historyPage.page.next_cursor != null}
              loading={loading}
              noun="次更新"
              onPrevious={() => {
                select(null);
                setPageState((state) => previousPage(state));
              }}
              onNext={() => {
                const cursor = historyPage.page.next_cursor;
                if (!cursor) return;
                select(null);
                setPageState((state) => nextPage(state, cursor));
              }}
            />
          </div>

          <div
            ref={detailRef}
            className="min-w-0 flex-1 scroll-mt-16 lg:border-l lg:border-line lg:pl-6"
          >
            {selected ? (
              <PatchDetail patch={selected.patch} model={model} />
            ) : (
              <p className="text-13 text-ink-3">
                在左侧选择一次知识更新查看内容差异。
              </p>
            )}
          </div>
        </div>
      )}
    </>
  );
}

function readableDocumentName(path: string, model: Model | null): string {
  const document = model?.docByPath.get(path);
  if (document?.title) return document.title;
  const parts = path.split("/");
  const filename = parts[parts.length - 1] ?? path;
  return filename.replace(/\.md$/i, "").replaceAll("-", " ");
}

function cleanClaimText(value: string | null | undefined): string {
  return (value ?? "")
    .replace(/\s*\[cite:[^\]]+\]/g, "")
    .replace(/\s*<!--\s*c:[^>]+-->/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

function truncateText(value: string, maxLength: number): string {
  return value.length > maxLength
    ? `${value.slice(0, maxLength).trimEnd()}…`
    : value;
}

function patchSummary(patch: PatchRecord): string {
  const firstChange = patch.claims.find(
    (claim) => cleanClaimText(claim.after ?? claim.before).length > 0,
  );
  const text = cleanClaimText(firstChange?.after ?? firstChange?.before);
  if (!text) return "本次更新没有留下可读的内容摘要";
  return truncateText(text, 52);
}

function patchTitle(patch: PatchRecord): string {
  const added = patch.claims.filter(
    (claim) => claimKind(claim) === "added",
  ).length;
  const revised = patch.claims.filter(
    (claim) => claimKind(claim) === "revised",
  ).length;
  if (added > 0 && revised > 0) {
    return `新增 ${added} 条、修订 ${revised} 条知识`;
  }
  if (revised > 0) return `修订 ${revised} 条知识`;
  if (added > 0) return `新增 ${added} 条知识`;
  return "知识库更新";
}

function TimelineRow({
  item,
  model,
  selected,
  onSelect,
}: {
  item: PatchTimelineItem;
  model: Model | null;
  selected: boolean;
  onSelect: () => void;
}) {
  const documentCount = patchChanges(model, item.patch).length;
  const claimCount = item.patch.claims.length;
  return (
    <li className="border-b border-line last:border-b-0">
      <button
        type="button"
        onClick={onSelect}
        aria-current={selected || undefined}
        className={cn(
          "flex w-full flex-col gap-1 px-3 py-2.5 text-left transition-colors duration-120",
          selected ? "bg-accent-soft" : "hover:bg-hover",
        )}
      >
        <span className="line-clamp-2 font-medium text-13 text-ink">
          {patchSummary(item.patch)}
        </span>
        <span className="flex items-baseline justify-between gap-3 text-12 text-ink-3">
          <span>{fmtTime(item.ts)}</span>
          <span className="shrink-0">
            {documentCount} 篇 · {claimCount} 条
          </span>
        </span>
      </button>
    </li>
  );
}

function claimKind(claim: SidecarClaimRef): "added" | "revised" | "unknown" {
  if (claim.type === "claim_added") return "added";
  if (claim.type === "claim_revised") return "revised";
  if (claim.before != null && claim.after != null) return "revised";
  if (claim.after != null) return "added";
  return "unknown";
}

interface DocumentClaimGroup {
  path: string;
  claims: SidecarClaimRef[];
}

function groupClaimsByDocument(
  patch: PatchRecord,
  model: Model | null,
): DocumentClaimGroup[] {
  const fallbackPath = patchChanges(model, patch)[0]?.path ?? "未定位文档";
  const groups = new Map<string, SidecarClaimRef[]>();
  for (const claim of patch.claims) {
    const path = claim.path ?? fallbackPath;
    const claims = groups.get(path) ?? [];
    claims.push(claim);
    groups.set(path, claims);
  }
  return [...groups].map(([path, claims]) => ({ path, claims }));
}

function PatchDetail({
  patch,
  model,
}: {
  patch: PatchRecord;
  model: Model | null;
}) {
  const jump = useApp((s) => s.jump);
  const focusSource = useApp((s) => s.focusSource);

  const changes = patchChanges(model, patch);
  const groups = groupClaimsByDocument(patch, model);
  const addedCount = patch.claims.filter(
    (claim) => claimKind(claim) === "added",
  ).length;
  const revisedCount = patch.claims.filter(
    (claim) => claimKind(claim) === "revised",
  ).length;
  const flagEntries = Object.entries(patch.flag_counts ?? {});
  const lineage = patch.lineage ?? {};
  const technicalItems = [
    { term: "版本", definition: <Mono className="break-all">{patch.patch_id}</Mono> },
    ...(patch.job_id
      ? [{ term: "编译任务", definition: <Mono className="break-all">{patch.job_id}</Mono> }]
      : []),
    ...(patch.base_commit
      ? [{ term: "基于版本", definition: <Mono>{shortSha(patch.base_commit)}</Mono> }]
      : []),
    ...(lineage.model
      ? [{ term: "model", definition: <Mono>{lineage.model}</Mono> }]
      : []),
    ...(lineage.provider
      ? [{ term: "provider", definition: <Mono>{lineage.provider}</Mono> }]
      : []),
    ...(lineage.tokens != null
      ? [{ term: "tokens", definition: <Mono>{fmtTokens(lineage.tokens)}</Mono> }]
      : []),
    ...(lineage.driver
      ? [{ term: "driver", definition: <Mono>{lineage.driver}</Mono> }]
      : []),
    ...(lineage.producer
      ? [{ term: "producer", definition: <Mono>{lineage.producer}</Mono> }]
      : []),
  ];

  return (
    <div className="flex flex-col gap-8">
      <header>
        <div className="flex items-start gap-3">
          <FileDiff className="mt-1 shrink-0 text-accent" size={18} aria-hidden />
          <div className="min-w-0">
            <h2 className="font-serif text-24 text-ink text-balance">
              {patchTitle(patch)}
            </h2>
            <p className="mt-1 text-13 text-ink-3">
              {fmtTime(patch.ts)} · 版本{" "}
              <Mono title={patch.patch_id}>{shortSha(patch.patch_id)}</Mono>
            </p>
            <p className="mt-3 max-w-measure font-serif text-14 leading-relaxed text-ink-2">
              {patchSummary(patch)}
            </p>
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-1 border-y border-line py-2 text-13 text-ink-2">
          <span>{changes.length} 篇文档</span>
          <span className="text-ok">新增 {addedCount}</span>
          <span className="text-accent">修订 {revisedCount}</span>
          <span>{patch.sources_consumed.length} 个来源</span>
        </div>
      </header>

      <section>
        <SectionRule no={1} title="内容差异" />
        {groups.length > 0 ? (
          <div className="mt-4 flex flex-col gap-6">
            {groups.map((group) => {
              const document = model?.docByPath.get(group.path);
              const docId = document?.document_id ?? null;
              return (
                <article key={group.path}>
                  <header className="flex min-w-0 items-baseline justify-between gap-3 border-b border-line pb-2">
                    <div className="min-w-0">
                      <h3 className="truncate font-medium text-14 text-ink">
                        {readableDocumentName(group.path, model)}
                      </h3>
                      <Mono className="block truncate text-12 text-ink-3">
                        {group.path}
                      </Mono>
                    </div>
                    <Badge tone="neutral">{group.claims.length} 条变化</Badge>
                  </header>
                  <ol>
                    {group.claims.map((claim, index) => {
                      const anchor = claim.anchor?.anchor;
                      const kind = claimKind(claim);
                      const jumpable = !!docId && !!anchor;
                      return (
                        <li
                          key={`${anchor ?? "claim"}-${index}`}
                          className="border-b border-line py-4 last:border-b-0"
                        >
                          <div className="mb-2 flex flex-wrap items-center gap-2">
                            <Badge tone={kind === "added" ? "ok" : "accent"}>
                              {kind === "added"
                                ? "新增"
                                : kind === "revised"
                                  ? "修订"
                                  : "变更"}
                            </Badge>
                            {anchor && (
                              <Mono className="text-12 text-ink-3">
                                ⚓ {anchor}
                              </Mono>
                            )}
                            {jumpable && (
                              <button
                                type="button"
                                className="ml-auto text-12 text-accent underline-offset-2 hover:underline"
                                onClick={() =>
                                  jump(
                                    {
                                      kind: "claim",
                                      documentId: docId,
                                      anchor,
                                    },
                                    "library",
                                  )
                                }
                              >
                                查看当前原文
                              </button>
                            )}
                          </div>

                          {kind === "revised" && claim.before != null ? (
                            <div className="grid gap-2 md:grid-cols-2">
                              <div className="min-w-0 rounded-2 bg-danger-soft px-3 py-2.5">
                                <span className="text-12 font-medium text-danger">
                                  原
                                </span>
                                <p className="mt-1 whitespace-pre-wrap break-words font-serif text-14 leading-relaxed text-ink-2">
                                  {cleanClaimText(claim.before)}
                                </p>
                              </div>
                              <div className="min-w-0 rounded-2 bg-ok-soft px-3 py-2.5">
                                <span className="text-12 font-medium text-ok">
                                  现
                                </span>
                                <p className="mt-1 whitespace-pre-wrap break-words font-serif text-14 leading-relaxed text-ink">
                                  {cleanClaimText(claim.after) || "—"}
                                </p>
                              </div>
                            </div>
                          ) : (
                            <div className="min-w-0 rounded-2 bg-ok-soft px-3 py-2.5">
                              <span className="text-12 font-medium text-ok">
                                +
                              </span>
                              <p className="mt-1 whitespace-pre-wrap break-words font-serif text-14 leading-relaxed text-ink">
                                {cleanClaimText(claim.after ?? claim.note) ||
                                  "未记录正文差异"}
                              </p>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ol>
                </article>
              );
            })}
          </div>
        ) : (
          <Callout className="mt-4" tone="info" title="暂无逐条差异">
            这个旧版本只记录了受影响的文档，没有保存知识条目的前后文本。
          </Callout>
        )}
      </section>

      <section>
        <SectionRule no={2} title="依据来源" />
        <div className="mt-3 flex flex-col border-y border-line">
          {patch.sources_consumed.map((sourceId, index) => (
            <button
              key={sourceId}
              type="button"
              onClick={() => focusSource(sourceId)}
              className="flex min-w-0 items-baseline gap-3 border-b border-line px-1 py-2 text-left transition-colors duration-120 last:border-b-0 hover:bg-hover"
            >
              <span className="shrink-0 text-13 text-ink-2">
                来源 {index + 1}
              </span>
              <Mono
                className="min-w-0 flex-1 truncate text-12 text-ink-3"
                title={sourceId}
              >
                {sourceId}
              </Mono>
              <span className="shrink-0 text-12 text-accent">查看原料</span>
            </button>
          ))}
          {patch.sources_consumed.length === 0 && (
            <p className="py-2 text-13 text-ink-3">未记录来源。</p>
          )}
        </div>
      </section>

      {(patch.escalations.length > 0 || flagEntries.length > 0) && (
        <section>
          <SectionRule no={3} title="需复核" />
          <div className="mt-3 flex flex-col gap-2">
            {patch.escalations.map((escalation, index) => {
              const { label, body } = escalationText(escalation);
              return (
                <Callout key={index} tone="notice" title={label}>
                  {body || "这条变化需要人工复核。"}
                </Callout>
              );
            })}
            {flagEntries.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {flagEntries.map(([flag, count]) => (
                  <Badge key={flag} tone="warn">
                    {flag} · {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </section>
      )}

      <details className="border-t border-line pt-3">
        <summary className="cursor-pointer text-13 text-ink-2 marker:text-ink-3">
          技术记录
        </summary>
        <DefinitionList className="mt-2" items={technicalItems} />
      </details>
    </div>
  );
}
