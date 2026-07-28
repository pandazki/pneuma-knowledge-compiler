/**
 * 图谱画布真实现（DESIGN.md §5 graph）：@xyflow/react + dagre 布局。
 * 墨色纪律（§6）：节点用 typeGlyph 的形状 + 墨阶冗余编码，边用发丝线
 * var(--line-2)，选中节点 accent 描边，邻域（expandNeighborhood ids）高亮、
 * 其余压淡。全部颜色经 CSS 变量 / color-mix 推导，零 hex、零彩色。
 *
 * 本文件只经 ./index.ts 的 React.lazy 引用（硬性规则 11）；xyflow 的
 * css import 只允许出现在本文件内。
 */
import { useEffect, useMemo } from "react";
import dagre from "dagre";
import {
  Background,
  BackgroundVariant,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Model, NodeShape } from "@/lib/model";
import { typeGlyph } from "@/lib/model";
import { ShapeIcon, inkShade } from "./glyph";

const NODE_W = 176;
const NODE_H = 44;

export interface GraphCanvasProps {
  model: Model;
  /** 当前选中节点（null = 无选中，整图正常墨色）。 */
  selectedId: string | null;
  /** 邻域高亮集合（expandNeighborhood 的 ids，含中心）；selection 为空时为 null。 */
  neighborhood: Set<string> | null;
  onSelectNode: (id: string) => void;
}

/* ------------------------------------------------------------------ 节点 */

interface InkNodeData extends Record<string, unknown> {
  title: string;
  type: string | null;
  shape: NodeShape;
  shade: string;
  selected: boolean;
  dim: boolean;
}

type InkNode = Node<InkNodeData, "ink">;

function InkNodeView({ data }: NodeProps<InkNode>) {
  const invisible = { opacity: 0 } as const;
  return (
    <div
      title={data.title}
      className="flex items-center gap-2 rounded-1 border bg-surface px-2.5 transition-opacity duration-120"
      style={{
        width: NODE_W,
        height: NODE_H,
        opacity: data.dim ? 0.25 : 1,
        borderColor: data.selected ? "var(--accent)" : "var(--line-2)",
        borderWidth: data.selected ? 2 : 1,
        boxShadow: data.selected
          ? "0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent)"
          : "none",
      }}
    >
      <Handle type="target" position={Position.Left} style={invisible} />
      <Handle type="source" position={Position.Right} style={invisible} />
      <ShapeIcon shape={data.shape} shade={data.shade} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-13 leading-tight text-ink">{data.title}</div>
        <div
          className="truncate text-12 leading-tight"
          style={{ color: data.shade }}
        >
          {data.type ?? "—"}
        </div>
      </div>
    </div>
  );
}

const nodeTypes = { ink: InkNodeView };

/* ------------------------------------------------------------------ 布局 */

function useLayout(model: Model) {
  return useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 20, ranksep: 80, marginx: 16, marginy: 16 });
    g.setDefaultEdgeLabel(() => ({}));
    for (const n of model.dataset.graph.nodes)
      g.setNode(n.id, { width: NODE_W, height: NODE_H });
    for (const e of model.dataset.graph.edges)
      if (model.nodeById.has(e.source) && model.nodeById.has(e.target))
        g.setEdge(e.source, e.target);
    dagre.layout(g);
    const pos = new Map<string, { x: number; y: number }>();
    for (const n of model.dataset.graph.nodes) {
      const p = g.node(n.id);
      if (p) pos.set(n.id, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 });
    }
    return pos;
  }, [model]);
}

/* ------------------------------------------------------------------ 画布 */

function Flow({ model, selectedId, neighborhood, onSelectNode }: GraphCanvasProps) {
  const { fitView } = useReactFlow();
  const positions = useLayout(model);

  const nodes = useMemo<InkNode[]>(
    () =>
      model.dataset.graph.nodes.map((n) => {
        const selected = n.id === selectedId;
        const dim = !!neighborhood && !neighborhood.has(n.id);
        return {
          id: n.id,
          type: "ink" as const,
          position: positions.get(n.id) ?? { x: 0, y: 0 },
          measured: { width: NODE_W, height: NODE_H },
          data: {
            title: n.title,
            type: n.type,
            shape: typeGlyph(model, n.type).shape,
            shade: inkShade(model, n.type),
            selected,
            dim,
          },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
        };
      }),
    [model, positions, selectedId, neighborhood],
  );

  const edges = useMemo<Edge[]>(
    () =>
      model.dataset.graph.edges
        .filter((e) => model.nodeById.has(e.source) && model.nodeById.has(e.target))
        .map((e, i) => {
          const incident = !!selectedId && (e.source === selectedId || e.target === selectedId);
          const inside =
            !!neighborhood && neighborhood.has(e.source) && neighborhood.has(e.target);
          const dim = !!neighborhood && !inside;
          return {
            id: `e${i}`,
            source: e.source,
            target: e.target,
            zIndex: incident ? 10 : 0,
            style: {
              stroke: incident ? "var(--ink-2)" : "var(--line-2)",
              strokeWidth: incident ? 1.5 : 1,
              strokeDasharray:
                e.type === "relationship" ? "6 4" : e.type === "merge" ? "2 4" : undefined,
              opacity: dim ? 0.12 : 1,
            },
          };
        }),
    [model, selectedId, neighborhood],
  );

  // 布局 / 数据变化时重取景；选中变化不重取（避免打断用户缩放）。
  useEffect(() => {
    const id = requestAnimationFrame(() => {
      void fitView({ padding: 0.12, duration: 200, maxZoom: 1.2 });
    });
    return () => cancelAnimationFrame(id);
  }, [fitView, positions]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onSelectNode(node.id)}
      fitView
      minZoom={0.15}
      maxZoom={2}
      nodesConnectable={false}
      nodesDraggable={false}
      elementsSelectable={false}
      proOptions={{ hideAttribution: true }}
      aria-label="知识图谱画布"
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="var(--line-2)" />
    </ReactFlow>
  );
}

export default function GraphCanvas(props: GraphCanvasProps) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
