/**
 * The real graph canvas (DESIGN.md §5 graph): @xyflow/react with a dagre layout.
 * Ink discipline (§6): nodes carry the redundant typeGlyph encoding (shape + ink step), edges
 * are hairlines in var(--line-2), the selected node takes an accent outline, and the
 * neighbourhood (expandNeighborhood ids) is highlighted while the rest is dimmed. Every colour
 * derives from a CSS variable / color-mix — no hex, no hue.
 *
 * This file is only ever reached through ./index.ts's React.lazy (hard rule 11); the xyflow
 * css import is allowed nowhere else.
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
import { sliceGraph } from "@/lib/graphViewport";
import { useT } from "@/lib/useT";
import { ShapeIcon, inkShade } from "./glyph";

const NODE_W = 176;
const NODE_H = 44;

export interface GraphCanvasProps {
  model: Model;
  /** The selected node (null = nothing selected, the whole graph at normal ink). */
  selectedId: string | null;
  /**
   * The highlighted neighbourhood (expandNeighborhood's ids, centre included); null when
   * nothing is selected.
   */
  neighborhood: Set<string> | null;
  onSelectNode: (id: string) => void;
}

/* ------------------------------------------------------------------- Nodes */

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

/* ------------------------------------------------------------------ Layout */

function useLayout(
  nodes: Model["dataset"]["graph"]["nodes"],
  edges: Model["dataset"]["graph"]["edges"],
) {
  return useMemo(() => {
    const g = new dagre.graphlib.Graph();
    g.setGraph({ rankdir: "LR", nodesep: 20, ranksep: 80, marginx: 16, marginy: 16 });
    g.setDefaultEdgeLabel(() => ({}));
    for (const n of nodes)
      g.setNode(n.id, { width: NODE_W, height: NODE_H });
    const visibleIds = new Set(nodes.map((node) => node.id));
    for (const e of edges)
      if (visibleIds.has(e.source) && visibleIds.has(e.target)) g.setEdge(e.source, e.target);
    dagre.layout(g);
    const pos = new Map<string, { x: number; y: number }>();
    for (const n of nodes) {
      const p = g.node(n.id);
      if (p) pos.set(n.id, { x: p.x - NODE_W / 2, y: p.y - NODE_H / 2 });
    }
    return pos;
  }, [nodes, edges]);
}

/* ------------------------------------------------------------------ Canvas */

function Flow({ model, selectedId, neighborhood, onSelectNode }: GraphCanvasProps) {
  const { fitView } = useReactFlow();
  const t = useT();
  const visibleGraph = useMemo(
    () =>
      sliceGraph(
        model.dataset.graph.nodes,
        model.dataset.graph.edges,
        neighborhood,
      ),
    [model, neighborhood],
  );
  const positions = useLayout(visibleGraph.nodes, visibleGraph.edges);

  const nodes = useMemo<InkNode[]>(
    () =>
      visibleGraph.nodes.map((n) => {
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
    [model, visibleGraph.nodes, positions, selectedId, neighborhood],
  );

  const edges = useMemo<Edge[]>(
    () =>
      visibleGraph.edges
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
    [model, visibleGraph.edges, selectedId, neighborhood],
  );

  // Re-fit the view when the layout / data changes, but not on a selection change — that
  // would interrupt the reader's own zoom.
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
      aria-label={t("graph.canvas.aria")}
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
