import { Suspense, useMemo, useState } from "react";
import { Waypoints, Inbox, BookOpen } from "lucide-react";
import { useApp } from "@/lib/store";
import { expandNeighborhood } from "@/lib/model";
import {
  limitGraphNeighborhood,
  pickGraphHub,
  sliceGraph,
} from "@/lib/graphViewport";
import { GraphCanvas } from "@/components/graph";
import { GlyphSwatch } from "@/components/graph/glyph";
import { PageHeader } from "@/components/PageHeader";
import { Badge } from "@/ui/Badge";
import { Button } from "@/ui/Button";
import { EmptyState } from "@/ui/EmptyState";
import { Mono } from "@/ui/Mono";
import { SegmentedControl } from "@/ui/SegmentedControl";
import { Skeleton } from "@/ui/Skeleton";
import { cn } from "@/ui/cn";

export default function GraphView() {
  const model = useApp((s) => s.model);
  const dataset = useApp((s) => s.dataset);
  const selection = useApp((s) => s.selection);
  const select = useApp((s) => s.select);
  const jump = useApp((s) => s.jump);
  const setView = useApp((s) => s.setView);
  const [degree, setDegree] = useState(1);

  const nodes = model?.dataset.graph.nodes ?? [];

  // 选中节点：node selection 直接命中；document selection 映射到同名 graph 节点。
  const selectedId = useMemo(() => {
    if (!model || !selection) return null;
    if (selection.kind === "node" && model.nodeById.has(selection.id)) return selection.id;
    if (selection.kind === "document" && model.nodeById.has(selection.id)) return selection.id;
    if (selection.kind === "claim" && model.nodeById.has(selection.documentId))
      return selection.documentId;
    return null;
  }, [model, selection]);

  const defaultId = useMemo(
    () =>
      model
        ? pickGraphHub(model.dataset.graph.nodes, model.dataset.graph.edges)
        : null,
    [model],
  );
  const activeId = selectedId ?? defaultId;

  const expandedNeighborhood = useMemo(() => {
    if (!model || !activeId) return null;
    return expandNeighborhood(model, activeId, degree).ids;
  }, [model, activeId, degree]);

  const neighborhood = useMemo(() => {
    if (!model || !activeId || !expandedNeighborhood) return null;
    return limitGraphNeighborhood(
      model.dataset.graph.nodes,
      model.dataset.graph.edges,
      activeId,
      expandedNeighborhood,
      24,
    );
  }, [model, activeId, expandedNeighborhood]);

  const visibleGraph = useMemo(
    () =>
      model
        ? sliceGraph(
            model.dataset.graph.nodes,
            model.dataset.graph.edges,
            neighborhood,
          )
        : { nodes: [], edges: [] },
    [model, neighborhood],
  );

  const selNode = activeId && model ? model.nodeById.get(activeId) : undefined;
  const selDoc = selNode && model ? model.docById.get(selNode.id) : undefined;

  const incidentEdges = useMemo(() => {
    if (!model || !activeId || !neighborhood) return [];
    return model.dataset.graph.edges.filter(
      (e) =>
        (e.source === activeId && neighborhood.has(e.target)) ||
        (e.target === activeId && neighborhood.has(e.source)),
    );
  }, [model, activeId, neighborhood]);

  const totalIncidentEdges = useMemo(() => {
    if (!model || !activeId) return 0;
    return model.dataset.graph.edges.filter(
      (e) => e.source === activeId || e.target === activeId,
    ).length;
  }, [model, activeId]);

  const usedTypes = useMemo(() => {
    if (!model) return [];
    const present = new Set(nodes.map((n) => n.type).filter((t): t is string => !!t));
    return model.types.filter((t) => present.has(t));
  }, [model, nodes]);

  if (!dataset || !model) {
    return (
      <>
        <PageHeader title="图谱 Graph" description="canonical 文档之间的关系图：墨色节点 + 发丝线边。" />
        <EmptyState
          icon={Inbox}
          title="还没有图谱"
          description="这个知识库尚未编译——先去「导入 Ingest」添加原料并编译，图谱随正典一起产出。"
          action={<Button size="sm" onClick={() => setView("ingest")}>去导入</Button>}
        />
      </>
    );
  }

  if (nodes.length === 0) {
    return (
      <>
        <PageHeader title="图谱 Graph" description="canonical 文档之间的关系图：墨色节点 + 发丝线边。" />
        <EmptyState
          icon={Waypoints}
          title="图为空"
          description="graph 没有节点——文档间尚未建立链接。"
        />
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="图谱 Graph"
        description={`全库 ${nodes.length} 节点 / ${model.dataset.graph.edges.length} 条边 · 当前聚焦 ${visibleGraph.nodes.length} 节点 / ${visibleGraph.edges.length} 条边${expandedNeighborhood && expandedNeighborhood.size > visibleGraph.nodes.length ? `（从 ${expandedNeighborhood.size} 个邻域节点中择取）` : ""}；单击节点切换中心。`}
        actions={
          <SegmentedControl
            aria-label="邻域度数"
            size="sm"
            value={String(degree)}
            onChange={(v) => setDegree(Number(v))}
            options={[
              { value: "1", label: "1 度" },
              { value: "2", label: "2 度" },
            ]}
          />
        }
      />
      <div className="flex flex-col gap-4 lg:flex-row lg:items-stretch">
        {/* 画布（lazy；移动端在上）。flex-1 只给 lg（行向主轴=宽度）：列向下
            flex-basis:0% 会压掉 h-[420px]，画布塌成 0 高（React Flow 错误 004）。 */}
        <div className="h-[420px] min-w-0 overflow-hidden rounded-2 border border-line bg-surface lg:h-[560px] lg:flex-1">
          <Suspense fallback={<Skeleton className="m-4 h-[calc(100%-32px)]" />}>
            <GraphCanvas
              model={model}
              selectedId={activeId}
              neighborhood={neighborhood}
              onSelectNode={(id) => select({ kind: "node", id })}
            />
          </Suspense>
        </div>

        {/* 右：详情 + 图例（移动端在下） */}
        <aside className="w-full shrink-0 lg:w-72 lg:overflow-y-auto">
          {selNode ? (
            <section aria-label="节点详情">
              <div className="flex items-center gap-2">
                <GlyphSwatch model={model} type={selNode.type} />
                <Badge tone="neutral">{selNode.type ?? "—"}</Badge>
              </div>
              <h2 className="mt-2 font-serif text-20 text-balance text-ink">{selNode.title}</h2>
              <Mono className="mt-1 block break-all text-12 text-ink-3">{selNode.id}</Mono>
              <Mono className="mt-0.5 block break-all text-12 text-ink-3">{selNode.path}</Mono>
              {selDoc && (
                <div className="mt-3">
                  <Button
                    size="sm"
                    onClick={() => jump({ kind: "document", id: selNode.id }, "library")}
                  >
                    <BookOpen size={13} aria-hidden /> 打开文档
                  </Button>
                </div>
              )}

              <p className="mt-5 border-t border-line pt-3 text-12 text-ink-3">
                当前可见相邻边 · {incidentEdges.length}
                {totalIncidentEdges > incidentEdges.length && ` / 全部 ${totalIncidentEdges}`}
              </p>
              <ul className="mt-1 flex flex-col">
                {incidentEdges.map((e, i) => {
                  const otherId = e.source === activeId ? e.target : e.source;
                  const other = model.nodeById.get(otherId);
                  if (!other) return null;
                  return (
                    <li key={`${e.source}-${e.target}-${i}`}>
                      <button
                        type="button"
                        onClick={() => select({ kind: "node", id: otherId })}
                        className="flex w-full items-center gap-2 rounded-1 py-1.5 text-left transition-colors duration-120 hover:bg-hover"
                      >
                        <GlyphSwatch model={model} type={other.type} size={12} />
                        <span className="min-w-0 flex-1 truncate text-13 text-ink">
                          {other.title}
                        </span>
                        <Mono className="shrink-0 text-12 text-ink-3">
                          {e.source === activeId ? "→" : "←"} {e.type}
                        </Mono>
                      </button>
                    </li>
                  );
                })}
                {incidentEdges.length === 0 && (
                  <li className="py-1.5 text-12 text-ink-3">无出入链接。</li>
                )}
              </ul>
            </section>
          ) : (
            <p className="text-13 text-ink-3">
              在图中单击一个节点，这里显示它的类型、路径与相邻边。
            </p>
          )}

          {/* 图例：typeGlyph 形状 + 墨阶 + 类型名 */}
          <p className="mt-5 border-t border-line pt-3 text-12 text-ink-3">图例 · 类型</p>
          <ul className="mt-1 flex flex-col">
            {usedTypes.map((t) => (
              <li key={t} className={cn("flex items-center gap-2 py-1")}>
                <GlyphSwatch model={model} type={t} size={13} />
                <span className="text-12 text-ink-2">{t}</span>
              </li>
            ))}
          </ul>
        </aside>
      </div>
    </>
  );
}
