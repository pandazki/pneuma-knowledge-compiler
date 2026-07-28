/**
 * Tree-first knowledge-graph canvas (xyflow). The earlier layered layout kept its
 * columns aligned but still DREW every ego edge, so a dense neighbourhood (e.g. a
 * legal Consultation node wired to almost every concept/person/matter) collapsed
 * into a spider web of long cross-column béziers that drowned the center's actual
 * relationships. The user's screenshots proved ink-fade + hover alone could not
 * rescue that density.
 *
 * The fix is to render STRUCTURE by default and offer the rest on demand:
 *
 *  1. DEFAULT = ego spanning tree only. A deterministic BFS from the center assigns
 *     every reachable node exactly one tree parent (in-edge subtree on the LEFT,
 *     out-edge subtree on the RIGHT — the old column semantics). Only tree edges are
 *     drawn, so the default view is a tidy tree with zero cross-column béziers.
 *  2. Non-tree edges become an affordance: a node with hidden associations shows a
 *     "+N" badge; hovering the node reveals its non-tree edges (dashed, faint),
 *     clicking the badge pins them. A top-bar "显示全部关联" switch restores the full
 *     edge set (with the old hover isolation).
 *  3. Fan-out guard: a non-center parent with more tree children than FANOUT_MAX
 *     collapses its tail into a "…更多 N 项" aggregate node, so one hub concept can't
 *     blow a column out. Clicking the aggregate expands (and re-collapses) it.
 *  4. Stable tree: BFS parent ties break by (edge-type weight relationship>merge>link,
 *     then parent id), so the same center always renders the same tree.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  ReactFlow,
  ReactFlowProvider,
  MarkerType,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { Model, NodeShape } from "@/lib/model";
import { expandNeighborhood, typeGlyph } from "@/lib/model";
import type { GraphEdge } from "@/lib/types";
import { GlyphSwatch } from "./Glyph";

const NODE_W = 184;
const NODE_H = 46;
const COL_GAP = 268; // horizontal distance between hop columns
const ROW_GAP = 68; // vertical distance between leaf slots
const FANOUT_MAX = 8; // a non-center parent past this collapses its tail into an aggregate

// Monochrome ink hierarchy (STYLE.md: no colour, express rank via ink + weight).
const EDGE_INK = {
  hot: "var(--color-text-secondary)", // hovered / pinned node's incident edges — strongest
  near: "var(--color-text-tertiary)", // 1-hop tree edges — mid ink
  far: "var(--color-border-strong)", // deeper tree edges & revealed non-tree edges — faint
} as const;

/** relationship (0) preferred over merge (1) over link (2) when picking a tree parent. */
function edgeWeight(type: string | undefined): number {
  if (type === "relationship") return 0;
  if (type === "merge") return 1;
  return 2;
}

/** Dash pattern per edge relation type (link solid / relationship dashed / merge dotted). */
function edgeDash(type: string | undefined): string | undefined {
  if (type === "relationship") return "6 4";
  if (type === "merge") return "2 4";
  return undefined;
}

/* ------------------------------------------------------------------- tree build */

interface TreeData {
  gnodes: Model["dataset"]["graph"]["nodes"];
  depth: Map<string, number>;
  side: Map<string, number>; // -1 left (in), +1 right (out), 0 center
  parent: Map<string, string>;
  children: Map<string, string[]>; // parent -> ordered tree children
  treeType: Map<string, string | undefined>; // child -> tree-edge relation type
  nonTree: GraphEdge[];
  adj: Map<string, Set<string>>; // undirected, for hover neighbour dimming
}

/**
 * Deterministic ego spanning tree. Signed BFS: the first hop off the center fixes a
 * node's side (out-edge → right, in-edge → left, reciprocal → balanced), descendants
 * inherit their parent's side. Parent ties within a BFS level break by edge weight
 * then id, so the tree is stable for a given center.
 */
function buildTree(
  model: Model,
  center: string,
  degree: number,
): TreeData {
  const { ids } = expandNeighborhood(model, center, degree);
  const gnodes = [...ids]
    .map((id) => model.nodeById.get(id))
    .filter((n): n is NonNullable<typeof n> => !!n);
  const gedges = model.dataset.graph.edges.filter(
    (e) => ids.has(e.source) && ids.has(e.target),
  );

  // incident edges per node (undirected) + directed sets for the center's side rule.
  const inc = new Map<string, { other: string; edge: GraphEdge }[]>();
  const push = (a: string, other: string, edge: GraphEdge) => {
    (inc.get(a) ?? inc.set(a, []).get(a)!).push({ other, edge });
  };
  const centerOut = new Set<string>();
  const centerIn = new Set<string>();
  const adj = new Map<string, Set<string>>();
  const linkAdj = (a: string, b: string) => {
    (adj.get(a) ?? adj.set(a, new Set()).get(a)!).add(b);
  };
  for (const e of gedges) {
    push(e.source, e.target, e);
    push(e.target, e.source, e);
    linkAdj(e.source, e.target);
    linkAdj(e.target, e.source);
    if (e.source === center) centerOut.add(e.target);
    if (e.target === center) centerIn.add(e.source);
  }

  const depth = new Map<string, number>([[center, 0]]);
  const side = new Map<string, number>([[center, 0]]);
  const parent = new Map<string, string>();
  const treeEdgeOf = new Map<string, GraphEdge>();
  let frontier = [center];
  let leftCount = 0;
  let rightCount = 0;
  for (let lvl = 1; lvl <= degree && frontier.length; lvl++) {
    const cands: { u: string; v: string; edge: GraphEdge }[] = [];
    for (const u of frontier)
      for (const { other: v, edge } of inc.get(u) ?? [])
        if (!depth.has(v)) cands.push({ u, v, edge });
    cands.sort(
      (a, b) =>
        edgeWeight(a.edge.type) - edgeWeight(b.edge.type) ||
        a.u.localeCompare(b.u) ||
        a.v.localeCompare(b.v),
    );
    const next: string[] = [];
    for (const c of cands) {
      if (depth.has(c.v)) continue;
      depth.set(c.v, lvl);
      parent.set(c.v, c.u);
      treeEdgeOf.set(c.v, c.edge);
      if (c.u === center) {
        const hasOut = centerOut.has(c.v);
        const hasIn = centerIn.has(c.v);
        const s = hasOut && hasIn ? (rightCount <= leftCount ? 1 : -1) : hasOut ? 1 : -1;
        if (s > 0) rightCount++;
        else leftCount++;
        side.set(c.v, s);
      } else {
        side.set(c.v, side.get(c.u) ?? 0);
      }
      next.push(c.v);
    }
    frontier = next;
  }

  // children lists, ordered stably (edge weight then id).
  const children = new Map<string, string[]>();
  for (const [child, p] of parent) {
    (children.get(p) ?? children.set(p, []).get(p)!).push(child);
  }
  for (const list of children.values())
    list.sort(
      (a, b) =>
        edgeWeight(treeEdgeOf.get(a)?.type) - edgeWeight(treeEdgeOf.get(b)?.type) ||
        a.localeCompare(b),
    );

  const treeType = new Map<string, string | undefined>();
  for (const [child, edge] of treeEdgeOf) treeType.set(child, edge.type);

  // Non-tree edges become the "+N" affordance. Collapse each unordered endpoint pair
  // to a single edge: a reciprocal link (A→B and B→A) or a reverse of a tree edge must
  // not be double-counted, or a bidirectional dataset shows a "+N" badge that reveals
  // nothing new on hover (the pair is already drawn, once as tree, once underneath).
  const treeEdgeSet = new Set(treeEdgeOf.values());
  const pairKey = (a: string, b: string) => (a < b ? `${a} ${b}` : `${b} ${a}`);
  const coveredPairs = new Set<string>();
  for (const e of treeEdgeOf.values()) coveredPairs.add(pairKey(e.source, e.target));
  const nonTree: GraphEdge[] = [];
  for (const e of gedges) {
    if (treeEdgeSet.has(e) || e.source === e.target) continue;
    const key = pairKey(e.source, e.target);
    if (coveredPairs.has(key)) continue; // reverse of a tree edge, or an earlier dup
    coveredPairs.add(key);
    nonTree.push(e);
  }

  return { gnodes, depth, side, parent, children, treeType, nonTree, adj };
}

/* ------------------------------------------------------------------ tidy layout */

interface Placed {
  pos: Map<string, { x: number; y: number }>;
  aggregates: { id: string; parentId: string; count: number }[];
  visible: Set<string>; // visible REAL node ids (excludes aggregates)
  hidden: Map<string, number>; // node id -> incident non-tree edge count among visible nodes
}

/**
 * Lay the (possibly collapsed) visible tree out as two back-to-back tidy trees, each
 * vertically centred on the center node. Aggregate placeholders are leaves in the
 * layout so a collapsed fan-out still occupies exactly one slot.
 */
function placeTree(
  tree: TreeData,
  center: string,
  expanded: Set<string>,
  showAll: boolean,
): Placed {
  const { depth, side, children, nonTree } = tree;

  // per-parent split into shown children + optional aggregate (center never collapses).
  const shownOf = new Map<string, string[]>();
  const aggregates: { id: string; parentId: string; count: number }[] = [];
  const layoutKids = new Map<string, string[]>(); // node -> [shown..., aggId?] for tidy
  const visible = new Set<string>([center]);

  const resolve = (node: string) => {
    const all = children.get(node) ?? [];
    // A non-center parent past the fan-out cap keeps an aggregate node in BOTH states:
    // collapsed it hides the tail ("…更多 N 项"); expanded it shows every child plus a
    // count-0 aggregate that renders "收起" — the reverse toggle. Without it the expand
    // is one-way (there is no other collapse affordance on the canvas).
    const overflow = !showAll && node !== center && all.length > FANOUT_MAX;
    if (!overflow) {
      shownOf.set(node, all);
      layoutKids.set(node, all);
      return;
    }
    const shown = expanded.has(node) ? all : all.slice(0, FANOUT_MAX - 1);
    const hiddenCount = all.length - shown.length; // 0 when expanded
    const aggId = `__agg__${node}`;
    aggregates.push({ id: aggId, parentId: node, count: hiddenCount });
    shownOf.set(node, shown);
    layoutKids.set(node, [...shown, aggId]);
    layoutKids.set(aggId, []); // aggregate is a leaf
  };

  // DFS to mark visibility + resolve collapse.
  const walk = (node: string) => {
    resolve(node);
    for (const c of shownOf.get(node) ?? []) {
      visible.add(c);
      walk(c);
    }
  };
  walk(center);

  // center's shown children split by side, preserving order.
  const centerKids = shownOf.get(center) ?? [];
  const rightRoots = centerKids.filter((c) => (side.get(c) ?? 0) > 0);
  const leftRoots = centerKids.filter((c) => (side.get(c) ?? 0) < 0);

  const pos = new Map<string, { x: number; y: number }>();
  const aggDepth = (aggId: string) =>
    (depth.get(aggId.replace("__agg__", "")) ?? 0) + 1;
  const aggSide = (aggId: string) => side.get(aggId.replace("__agg__", "")) ?? 0;

  const tidy = (roots: string[], sign: number) => {
    if (!roots.length) return;
    let slot = 0;
    const y = new Map<string, number>();
    const place = (n: string) => {
      const ks = layoutKids.get(n) ?? [];
      if (!ks.length) {
        y.set(n, slot++);
        return;
      }
      ks.forEach(place);
      y.set(n, (y.get(ks[0])! + y.get(ks[ks.length - 1])!) / 2);
    };
    roots.forEach(place);
    const centerY = (y.get(roots[0])! + y.get(roots[roots.length - 1])!) / 2;
    for (const [id, slotY] of y) {
      const d = id.startsWith("__agg__") ? aggDepth(id) : depth.get(id) ?? 1;
      pos.set(id, {
        x: sign * d * COL_GAP - NODE_W / 2,
        y: (slotY - centerY) * ROW_GAP - NODE_H / 2,
      });
    }
  };
  tidy(rightRoots, 1);
  tidy(leftRoots, -1);
  pos.set(center, { x: -NODE_W / 2, y: -NODE_H / 2 });

  // aggregates whose parent sits with no side children still need a home; the tidy
  // pass already placed every aggregate reachable from a side root, but a center-side
  // aggregate can't exist (center never collapses), so nothing more to do. Guard any
  // stray aggregate (shouldn't happen) at its parent's column.
  for (const a of aggregates)
    if (!pos.has(a.id)) {
      const p = pos.get(a.parentId) ?? { x: 0, y: 0 };
      pos.set(a.id, { x: p.x + aggSide(a.id) * COL_GAP, y: p.y });
    }

  // non-tree edge count per visible node (only edges with both endpoints visible).
  const hidden = new Map<string, number>();
  for (const e of nonTree) {
    if (!visible.has(e.source) || !visible.has(e.target)) continue;
    hidden.set(e.source, (hidden.get(e.source) ?? 0) + 1);
    hidden.set(e.target, (hidden.get(e.target) ?? 0) + 1);
  }

  return { pos, aggregates, visible, hidden };
}

/* --------------------------------------------------------------------- rf nodes */

interface KbNodeData {
  title: string;
  type: string | null;
  shape: NodeShape;
  shade: string;
  isCenter: boolean;
  dim: boolean;
  hiddenCount: number;
  badgeActive: boolean;
  badgeStatic: boolean; // showAll: badge is a pure count, not a pin toggle
  onBadge: (id: string) => void;
  [key: string]: unknown;
}

interface AggNodeData {
  count: number;
  expanded: boolean;
  dim: boolean;
  [key: string]: unknown;
}

/** Four invisible handles (source+target on each side) so any edge can flow left→right. */
function EdgeHandles() {
  const s = { opacity: 0 } as const;
  return (
    <>
      <Handle id="l-t" type="target" position={Position.Left} style={s} />
      <Handle id="l-s" type="source" position={Position.Left} style={s} />
      <Handle id="r-t" type="target" position={Position.Right} style={s} />
      <Handle id="r-s" type="source" position={Position.Right} style={s} />
    </>
  );
}

/** A knowledge-point card: type glyph + truncated title, with an optional +N badge. */
function KbNode({ id, data }: NodeProps<Node<KbNodeData>>) {
  return (
    <div
      title={data.title}
      className="relative flex items-center gap-2 rounded-sm border bg-card px-2.5 text-[length:var(--text-sm)] transition-[opacity,box-shadow]"
      style={{
        width: NODE_W,
        height: NODE_H,
        opacity: data.dim ? 0.28 : 1,
        borderColor: data.isCenter ? "var(--color-accent)" : "var(--color-border-strong)",
        borderWidth: data.isCenter ? 2 : 1,
        boxShadow: data.isCenter
          ? "0 0 0 3px color-mix(in srgb, var(--color-accent) 30%, transparent), var(--shadow-overlay)"
          : "var(--shadow-subtle, none)",
      }}
    >
      <EdgeHandles />
      <GlyphSwatch shape={data.shape} shade={data.shade} size={14} />
      <div className="min-w-0 flex-1">
        <div className="truncate leading-tight text-foreground">{data.title}</div>
        <div className="truncate text-[length:var(--text-2xs)] leading-tight text-muted-foreground">
          {data.type ?? "—"}
        </div>
      </div>
      {data.hiddenCount > 0 &&
        (data.badgeStatic ? (
          // showAll draws every edge already, so the badge is a plain count, not a toggle.
          <span
            className="pointer-events-none absolute -right-2 -top-2 z-10 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full border px-1 text-[length:var(--text-2xs)] font-medium leading-none"
            style={{
              borderColor: "var(--color-border-strong)",
              background: "var(--color-surface)",
              color: "var(--color-text-secondary)",
            }}
            title={`${data.hiddenCount} 条非树关联`}
          >
            +{data.hiddenCount}
          </span>
        ) : (
          <button
            className="nodrag absolute -right-2 -top-2 z-10 inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-full border px-1 text-[length:var(--text-2xs)] font-medium leading-none transition-colors"
            style={{
              borderColor: data.badgeActive
                ? "var(--color-accent)"
                : "var(--color-border-strong)",
              background: data.badgeActive
                ? "color-mix(in srgb, var(--color-accent) 20%, var(--color-surface))"
                : "var(--color-surface)",
              color: data.badgeActive ? "var(--color-accent)" : "var(--color-text-secondary)",
            }}
            title={
              data.badgeActive
                ? "隐藏其余关联"
                : `还有 ${data.hiddenCount} 条关联未显示 — 点击固定显示`
            }
            onClick={(e) => {
              e.stopPropagation();
              data.onBadge(id);
            }}
          >
            +{data.hiddenCount}
          </button>
        ))}
    </div>
  );
}

/** A "…更多 N 项" aggregate for a collapsed fan-out tail; click toggles expansion. */
function AggNode({ data }: NodeProps<Node<AggNodeData>>) {
  return (
    <div
      className="flex items-center justify-center rounded-sm border border-dashed bg-card px-2 text-[length:var(--text-xs)] text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      style={{
        width: NODE_W,
        height: NODE_H - 12,
        borderColor: "var(--color-border-strong)",
        opacity: data.dim ? 0.28 : 1,
      }}
      title={data.expanded ? "收起这些节点" : `展开其余 ${data.count} 项`}
    >
      <EdgeHandles />
      {data.expanded ? "收起" : `…更多 ${data.count} 项`}
    </div>
  );
}

const nodeTypes = { kb: KbNode, agg: AggNode };

/* ---------------------------------------------------------------------- flow */

function Flow({
  model,
  center,
  degree,
  activeTypes,
  showAll,
  onRecenter,
}: {
  model: Model;
  center: string;
  degree: number;
  activeTypes: Set<string> | null;
  showAll: boolean;
  onRecenter: (id: string) => void;
}) {
  const { fitView } = useReactFlow();
  const [compactViewport, setCompactViewport] = useState(
    () => typeof window !== "undefined" && window.matchMedia("(max-width: 720px)").matches,
  );
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [pinned, setPinned] = useState<Set<string>>(new Set());

  // Per-node identity cache. Hover rebuilds the node array; xyflow re-measures (and hides
  // for a frame) only nodes whose object REFERENCE changed. Keeping a stable ref for every
  // node whose visuals are unchanged means the hovered node never gets hidden out from
  // under the cursor — which is what otherwise made hover clear itself and flicker.
  const nodeCache = useRef(
    new Map<string, { sig: string; node: Node<KbNodeData | AggNodeData> }>(),
  );

  useEffect(() => {
    const query = window.matchMedia("(max-width: 720px)");
    const sync = () => setCompactViewport(query.matches);
    sync();
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, []);

  // Reset per-view interaction state whenever the tree itself changes.
  useEffect(() => {
    setExpanded(new Set());
    setPinned(new Set());
    setHoverId(null);
  }, [center, degree, model]);

  // Heavy layer: ego spanning tree. Only recomputed when the graph changes.
  const tree = useMemo(() => buildTree(model, center, degree), [model, center, degree]);

  // Mid layer: collapse + tidy layout. Recomputed on expand / showAll (not on hover).
  const laid = useMemo(
    () => placeTree(tree, center, expanded, showAll),
    [tree, center, expanded, showAll],
  );

  const toggleExpand = useCallback((parentId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(parentId)) next.delete(parentId);
      else next.add(parentId);
      return next;
    });
  }, []);
  const togglePin = useCallback((id: string) => {
    setPinned((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  // Light layer: node + edge styling from hover / pin / filter. Cheap; no layout.
  const { nodes, edges } = useMemo(() => {
    const { pos, aggregates, visible, hidden } = laid;
    const { depth, parent, treeType, nonTree, adj } = tree;
    const hoverNeighbors = hoverId ? adj.get(hoverId) ?? new Set<string>() : null;
    const passesFilter = (id: string, type: string | null) =>
      !activeTypes || id === center || (!!type && activeTypes.has(type));

    const posOf = (id: string) => pos.get(id) ?? { x: 0, y: 0 };
    const badgeActive = (id: string) => pinned.has(id);

    // which non-tree edges are drawn: all (showAll) | hovered-incident | pinned-incident.
    const revealed = (e: GraphEdge) => {
      if (!visible.has(e.source) || !visible.has(e.target)) return false;
      if (showAll) return true;
      if (hoverId && (e.source === hoverId || e.target === hoverId)) return true;
      return pinned.has(e.source) || pinned.has(e.target);
    };

    // Reconcile against last render: reuse the prior object reference when the signature
    // (everything that affects the node's look/position) is identical, so unchanged nodes
    // keep identity and xyflow leaves them measured & visible.
    const prevCache = nodeCache.current;
    const nextCache = new Map<string, { sig: string; node: Node<KbNodeData | AggNodeData> }>();
    const reconcile = (
      id: string,
      sig: string,
      build: () => Node<KbNodeData | AggNodeData>,
    ) => {
      const prev = prevCache.get(id);
      const node = prev && prev.sig === sig ? prev.node : build();
      nextCache.set(id, { sig, node });
      return node;
    };

    const rfNodes: Node<KbNodeData | AggNodeData>[] = [];
    for (const n of tree.gnodes) {
      if (!visible.has(n.id)) continue;
      const glyph = typeGlyph(model, n.type);
      const filteredOut = !passesFilter(n.id, n.type);
      const hoverDim =
        !!hoverId && n.id !== hoverId && !hoverNeighbors?.has(n.id) && n.id !== center;
      const p = posOf(n.id);
      const isCenter = n.id === center;
      const dim = filteredOut || hoverDim;
      const hiddenCount = hidden.get(n.id) ?? 0;
      const active = badgeActive(n.id);
      const sig = `kb|${p.x}|${p.y}|${n.title}|${n.type}|${glyph.shape}|${glyph.shade}|${isCenter}|${dim}|${hiddenCount}|${active}|${showAll}`;
      rfNodes.push(
        reconcile(n.id, sig, () => ({
          id: n.id,
          type: "kb",
          position: p,
          // Fixed CSS size, declared so xyflow can lay out edges before first measure.
          measured: { width: NODE_W, height: NODE_H },
          data: {
            title: n.title,
            type: n.type,
            shape: glyph.shape,
            shade: glyph.shade,
            isCenter,
            dim,
            hiddenCount,
            badgeActive: active,
            badgeStatic: showAll,
            onBadge: togglePin,
          },
          sourcePosition: Position.Right,
          targetPosition: Position.Left,
        })),
      );
    }
    for (const a of aggregates) {
      const p = posOf(a.id);
      const isExpanded = expanded.has(a.parentId);
      const dim = !!hoverId;
      const sig = `agg|${p.x}|${p.y}|${a.count}|${isExpanded}|${dim}`;
      rfNodes.push(
        reconcile(a.id, sig, () => ({
          id: a.id,
          type: "agg",
          position: p,
          measured: { width: NODE_W, height: NODE_H - 12 },
          data: { count: a.count, expanded: isExpanded, dim },
        })),
      );
    }
    nodeCache.current = nextCache;

    // an edge, always drawn left→right so no bézier ever loops back on itself.
    const conn = (aId: string, bId: string) => {
      const pa = posOf(aId);
      const pb = posOf(bId);
      const [srcId, tgtId] = pa.x <= pb.x ? [aId, bId] : [bId, aId];
      return { source: srcId, sourceHandle: "r-s", target: tgtId, targetHandle: "l-t" };
    };

    const rfEdges: Edge[] = [];

    // 1) tree edges (always) — ink by depth; hover lifts the hovered node's own.
    const emitTree = (childId: string, dashType: string | undefined) => {
      const p = parent.get(childId);
      if (p === undefined || !visible.has(p) || !visible.has(childId)) return;
      const d = depth.get(childId) ?? 1;
      const incidentHover = !!hoverId && (childId === hoverId || p === hoverId);
      let ink: string = d <= 1 ? EDGE_INK.near : EDGE_INK.far;
      let width = d <= 1 ? 2 : 1.4;
      let opacity = d <= 1 ? 1 : d === 2 ? 0.72 : 0.55;
      if (hoverId) {
        if (incidentHover) {
          ink = EDGE_INK.hot;
          width = 2.5;
          opacity = 1;
        } else opacity = Math.min(opacity, 0.16);
      }
      const filteredOut =
        !passesFilter(p, model.nodeById.get(p)?.type ?? null) ||
        !passesFilter(childId, model.nodeById.get(childId)?.type ?? null);
      if (filteredOut) opacity = Math.min(opacity, 0.12);
      rfEdges.push({
        id: `t:${childId}`,
        ...conn(p, childId),
        zIndex: incidentHover ? 10 : d <= 1 ? 5 : 1,
        style: { stroke: ink, strokeWidth: width, strokeDasharray: dashType, opacity },
        markerEnd: { type: MarkerType.ArrowClosed, color: ink, width: 12, height: 12 },
      });
    };
    for (const childId of parent.keys()) {
      if (!visible.has(childId)) continue;
      // dash reflects the actual tree edge's relation type.
      emitTree(childId, edgeDash(treeType.get(childId)));
    }

    // 1b) aggregate connector edges (parent → aggregate placeholder).
    for (const a of aggregates) {
      if (!visible.has(a.parentId)) continue;
      const incidentHover = !!hoverId && a.parentId === hoverId;
      rfEdges.push({
        id: `t:${a.id}`,
        ...conn(a.parentId, a.id),
        zIndex: 1,
        style: {
          stroke: EDGE_INK.far,
          strokeWidth: 1.25,
          strokeDasharray: "2 3",
          opacity: hoverId && !incidentHover ? 0.16 : 0.55,
        },
      });
    }

    // 2) non-tree edges — only the revealed subset, dashed & faint (unless showAll).
    nonTree.forEach((e, i) => {
      if (!revealed(e)) return;
      const incidentHover =
        !!hoverId && (e.source === hoverId || e.target === hoverId);
      const filteredOut =
        !passesFilter(e.source, model.nodeById.get(e.source)?.type ?? null) ||
        !passesFilter(e.target, model.nodeById.get(e.target)?.type ?? null);
      let ink: string = EDGE_INK.far;
      let width = 1.25;
      let opacity = showAll ? 0.5 : 0.66;
      if (incidentHover || pinned.has(e.source) || pinned.has(e.target)) {
        ink = EDGE_INK.hot;
        width = 2;
        opacity = 0.95;
      } else if (hoverId) {
        opacity = 0.1;
      }
      if (filteredOut) opacity = Math.min(opacity, 0.1);
      rfEdges.push({
        id: `n:${i}`,
        ...conn(e.source, e.target),
        zIndex: incidentHover ? 9 : 0,
        style: {
          stroke: ink,
          strokeWidth: width,
          strokeDasharray: edgeDash(e.type) ?? "4 3",
          opacity,
        },
      });
    });

    return { nodes: rfNodes, edges: rfEdges };
  }, [
    laid,
    tree,
    activeTypes,
    hoverId,
    pinned,
    expanded,
    showAll,
    center,
    model,
    togglePin,
  ]);

  // Anchor the selection: refit only when the layout changes — never on hover / pin.
  const fitRef = useRef(fitView);
  fitRef.current = fitView;
  useEffect(() => {
    const id = requestAnimationFrame(() =>
      fitRef.current({
        padding: compactViewport ? 0.04 : 0.18,
        duration: 400,
        minZoom: compactViewport ? 0.58 : 0.2,
        maxZoom: compactViewport ? 0.9 : 1.4,
      }),
    );
    return () => cancelAnimationFrame(id);
  }, [compactViewport, laid]);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.type === "agg") {
        toggleExpand(node.id.replace("__agg__", ""));
        return;
      }
      if (node.id !== center) onRecenter(node.id);
    },
    [center, onRecenter, toggleExpand],
  );
  const onNodeMouseEnter = useCallback((_: React.MouseEvent, node: Node) => {
    if (node.type !== "agg") setHoverId(node.id);
  }, []);
  const onNodeMouseLeave = useCallback(() => setHoverId(null), []);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      onNodeClick={onNodeClick}
      onNodeMouseEnter={onNodeMouseEnter}
      onNodeMouseLeave={onNodeMouseLeave}
      fitView
      minZoom={compactViewport ? 0.58 : 0.2}
      maxZoom={2}
      proOptions={{ hideAttribution: true }}
      nodesConnectable={false}
      nodesDraggable={false}
      selectNodesOnDrag={false}
      elementsSelectable
      className="pneuma-flow"
    >
      <Background variant={BackgroundVariant.Dots} gap={22} size={1} />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

export function GraphCanvas(props: {
  model: Model;
  center: string;
  degree: number;
  activeTypes: Set<string> | null;
  showAll: boolean;
  onRecenter: (id: string) => void;
}) {
  return (
    <ReactFlowProvider>
      <Flow {...props} />
    </ReactFlowProvider>
  );
}
