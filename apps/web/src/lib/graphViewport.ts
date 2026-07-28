export interface GraphViewportNode {
  id: string;
}

export interface GraphViewportEdge {
  source: string;
  target: string;
}

/**
 * Pick a deterministic entry point near a readable degree. The absolute
 * highest-degree node is usually a profile/root node whose star collapses when
 * fit into the initial canvas.
 */
export function pickGraphHub<
  Node extends GraphViewportNode,
  Edge extends GraphViewportEdge,
>(nodes: readonly Node[], edges: readonly Edge[]): string | null {
  if (nodes.length === 0) return null;
  const ids = new Set(nodes.map((node) => node.id));
  const degree = new Map(nodes.map((node) => [node.id, 0]));
  for (const edge of edges) {
    if (!ids.has(edge.source) || !ids.has(edge.target)) continue;
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  }
  const targetDegree = 8;
  return nodes.reduce((best, node) => {
    const nodeDegree = degree.get(node.id) ?? 0;
    const bestDegree = degree.get(best.id) ?? 0;
    if (bestDegree === 0 && nodeDegree > 0) return node;
    if (nodeDegree === 0) return best;
    const distance = Math.abs(nodeDegree - targetDegree);
    const bestDistance = Math.abs(bestDegree - targetDegree);
    if (distance !== bestDistance) return distance < bestDistance ? node : best;
    return nodeDegree > bestDegree ? node : best;
  }).id;
}

/** Keep only nodes in the active neighborhood and edges whose two endpoints remain. */
export function sliceGraph<
  Node extends GraphViewportNode,
  Edge extends GraphViewportEdge,
>(
  nodes: readonly Node[],
  edges: readonly Edge[],
  visibleIds: ReadonlySet<string> | null,
): { nodes: Node[]; edges: Edge[] } {
  if (visibleIds == null) return { nodes: [...nodes], edges: [...edges] };
  const visibleNodes = nodes.filter((node) => visibleIds.has(node.id));
  const existingIds = new Set(visibleNodes.map((node) => node.id));
  return {
    nodes: visibleNodes,
    edges: edges.filter(
      (edge) => existingIds.has(edge.source) && existingIds.has(edge.target),
    ),
  };
}

/**
 * Bound a dense neighborhood without losing the graph data itself.
 * The center always survives; direct and structurally connected neighbors win,
 * then titles make the result deterministic for screenshots and keyboard order.
 */
export function limitGraphNeighborhood<
  Node extends GraphViewportNode & { title: string },
  Edge extends GraphViewportEdge,
>(
  nodes: readonly Node[],
  edges: readonly Edge[],
  centerId: string,
  neighborhood: ReadonlySet<string>,
  limit: number,
): Set<string> {
  const valid = new Set(nodes.map((node) => node.id));
  const candidates = [...neighborhood].filter((id) => valid.has(id));
  if (candidates.length <= limit) return new Set(candidates);

  const direct = new Set<string>();
  const degrees = new Map<string, number>();
  for (const edge of edges) {
    if (!neighborhood.has(edge.source) || !neighborhood.has(edge.target)) continue;
    degrees.set(edge.source, (degrees.get(edge.source) ?? 0) + 1);
    degrees.set(edge.target, (degrees.get(edge.target) ?? 0) + 1);
    if (edge.source === centerId) direct.add(edge.target);
    if (edge.target === centerId) direct.add(edge.source);
  }
  const titles = new Map(nodes.map((node) => [node.id, node.title]));
  candidates.sort((left, right) => {
    if (left === centerId) return -1;
    if (right === centerId) return 1;
    const directDelta = Number(direct.has(right)) - Number(direct.has(left));
    if (directDelta !== 0) return directDelta;
    const degreeDelta = (degrees.get(right) ?? 0) - (degrees.get(left) ?? 0);
    if (degreeDelta !== 0) return degreeDelta;
    return (titles.get(left) ?? left).localeCompare(titles.get(right) ?? right, "zh-CN");
  });
  return new Set(candidates.slice(0, Math.max(1, limit)));
}
