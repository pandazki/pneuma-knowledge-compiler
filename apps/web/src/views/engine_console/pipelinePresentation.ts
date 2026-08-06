import type {
  EngineAccessRoute,
  EngineEdge,
  EngineSchema,
  EngineValue,
} from "@/engine/types";
import { isEdgeActive } from "@/lib/engineConsole";

export type StageLane = "spine" | "branch" | "support";
export type EdgeVisualRole = "spine" | "branch" | "return";

export interface StagePlacement {
  id: string;
  x: number;
  y: number;
  lane: StageLane;
}

export interface AccessRoutePlacement {
  id: string;
  x: number;
  y: number;
  width: number;
}

export interface AccessRouteMergePlacement {
  targetId: string;
  x: number;
  y: number;
}

export type AccessRouteState = "active" | "inactive" | "conditional";

const STAGE_WIDTH = 216;
const ACCESS_ROUTE_HEIGHT = 32;
const ACCESS_ROUTE_GAP = 46;
const ACCESS_ROUTE_BRANCH_CLEARANCE = 122;
const ACCESS_ROUTE_MERGE_RISE = 58;
const ACCESS_ROUTE_MERGE_RUN = 164;

/**
 * Lay out the schema rather than a hand-drawn stage-id diagram. Unconditional edges form the
 * horizontal lifecycle spine, conditional neighbours alternate above/below it, and stages with
 * no edges form a clearly separated strategy shelf. Generous graph-space gaps are intentional:
 * the topology and its edge labels get visual priority over node density.
 */
export function placeEngineStages(schema: EngineSchema): StagePlacement[] {
  const ids = new Set(schema.stages.map((stage) => stage.id));
  const plainEdges = schema.edges.filter(
    (edge) => !edge.condition && ids.has(edge.from) && ids.has(edge.to),
  );
  const plainIncoming = new Set(plainEdges.map((edge) => edge.to));
  const outgoing = new Map<string, EngineEdge[]>();
  for (const edge of plainEdges) {
    outgoing.set(edge.from, [...(outgoing.get(edge.from) ?? []), edge]);
  }

  const spine: string[] = [];
  const seen = new Set<string>();
  const starts = schema.stages
    .map((stage) => stage.id)
    .filter((id) => outgoing.has(id) && !plainIncoming.has(id));

  const walk = (start: string) => {
    let current: string | undefined = start;
    while (current && !seen.has(current)) {
      spine.push(current);
      seen.add(current);
      current = (outgoing.get(current) ?? []).find((edge) => !seen.has(edge.to))?.to;
    }
  };
  for (const start of starts) walk(start);
  for (const edge of plainEdges) {
    if (!seen.has(edge.from)) walk(edge.from);
    if (!seen.has(edge.to)) walk(edge.to);
  }

  const connected = new Set(schema.edges.flatMap((edge) => [edge.from, edge.to]));
  const branches = schema.stages
    .map((stage) => stage.id)
    .filter((id) => connected.has(id) && !seen.has(id));
  const support = schema.stages
    .map((stage) => stage.id)
    .filter((id) => !connected.has(id));

  // A schema with only conditional edges still needs a readable anchor row.
  if (spine.length === 0 && branches.length > 0) {
    spine.push(branches.shift()!);
    seen.add(spine[0]);
  }

  // The access routes occupy their own band, so every lifecycle step keeps one regular rhythm.
  const placements: StagePlacement[] = [];
  let spineX = 70;
  spine.forEach((id) => {
    placements.push({ id, x: spineX, y: 320, lane: "spine" });
    spineX += 420;
  });
  const spineIndex = new Map(spine.map((id, index) => [id, index]));
  const branchCount = new Map<string, number>();

  for (const id of branches) {
    const touching = schema.edges.find(
      (edge) =>
        (edge.to === id && spineIndex.has(edge.from)) ||
        (edge.from === id && spineIndex.has(edge.to)),
    );
    const anchor = touching
      ? spineIndex.get(touching.to === id ? touching.from : touching.to) ?? 0
      : 0;
    const key = spine[anchor] ?? "root";
    const atAnchor = branchCount.get(key) ?? 0;
    branchCount.set(key, atAnchor + 1);
    const above = atAnchor % 2 === 0;
    const tier = Math.floor(atAnchor / 2);
    const anchorX = placements.find((placement) => placement.id === key)?.x ?? 70;
    placements.push({
      id,
      x: anchorX + tier * 250,
      y: above ? 72 - tier * 18 : 536 + tier * 18,
      lane: "branch",
    });
  }

  const finalSpineX = Math.max(
    ...placements.filter((placement) => placement.lane === "spine").map((placement) => placement.x),
    70,
  );
  const accessRouteCount = schema.access_routes?.length ?? 0;
  const accessRouteTop = accessRouteBandTop(placements);
  const accessRouteBottom = accessRouteCount > 0
    ? accessRouteTop + (accessRouteCount - 1) * ACCESS_ROUTE_GAP + ACCESS_ROUTE_HEIGHT
    : 0;
  const supportY = Math.max(758, accessRouteBottom + 102);
  const shelfWidth = Math.max(finalSpineX - 70 + 216, 816);
  const supportGap = support.length > 1 ? (shelfWidth - 216) / (support.length - 1) : 0;
  support.forEach((id, index) => {
    placements.push({
      id,
      x: 70 + (support.length === 1 ? (shelfWidth - 216) / 2 : supportGap * index),
      y: supportY,
      lane: "support",
    });
  });

  // Truly isolated single-stage schemas have neither an edge nor a shelf to compare against.
  if (placements.length === 0 && schema.stages[0]) {
    placements.push({ id: schema.stages[0].id, x: 70, y: 320, lane: "spine" });
  }
  return placements;
}

/** Place access routes as an evenly spaced horizontal channel band below the process graph. */
export function placeAccessRoutes(
  routes: readonly EngineAccessRoute[],
  stages: readonly StagePlacement[],
): AccessRoutePlacement[] {
  if (routes.length === 0) return [];
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  const targetXs = routes
    .map((route) => byId.get(route.to))
    .filter((placement): placement is StagePlacement => placement != null)
    .map((placement) => placement.x + STAGE_WIDTH / 2);
  if (targetXs.length === 0) return [];
  const laneEndX = Math.min(...targetXs) - ACCESS_ROUTE_MERGE_RUN;
  const firstY = accessRouteBandTop(stages);
  return routes.flatMap((route, index) => {
    const source = byId.get(route.from);
    const target = byId.get(route.to);
    if (!source || !target) return [];
    const x = source.x + STAGE_WIDTH / 2;
    return [{
      id: route.id,
      x,
      y: firstY + index * ACCESS_ROUTE_GAP,
      width: Math.max(180, laneEndX - x),
    }];
  });
}

/** The four channels meet at one marker before a single trunk enters recall. */
export function placeAccessRouteMerge(
  routes: readonly EngineAccessRoute[],
  stages: readonly StagePlacement[],
  placements: readonly AccessRoutePlacement[],
): AccessRouteMergePlacement | null {
  if (routes.length === 0 || placements.length === 0) return null;
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  const targetId = routes[0]?.to;
  if (!targetId || routes.some((route) => route.to !== targetId)) return null;
  const target = byId.get(targetId);
  if (!target) return null;
  return {
    targetId,
    x: target.x + STAGE_WIDTH / 2,
    y: Math.min(...placements.map((placement) => placement.y)) - ACCESS_ROUTE_MERGE_RISE,
  };
}

function accessRouteBandTop(stages: readonly StagePlacement[]): number {
  const lowestBranchY = Math.max(
    ...stages
      .filter((stage) => stage.lane === "branch")
      .map((stage) => stage.y),
    536,
  );
  return lowestBranchY + ACCESS_ROUTE_BRANCH_CLEARANCE;
}

/**
 * Intake-plan conditions are per-source rather than deployment knobs. When no concrete plan
 * is in the values map, keep the lane visibly conditional instead of claiming it is off.
 */
export function accessRouteState(
  route: EngineAccessRoute,
  values: Record<string, EngineValue>,
): AccessRouteState {
  if (!route.condition) return "active";
  if (!(route.condition in values)) return "conditional";
  const value = values[route.condition];
  return value === false || value == null || value === "" || value === "none"
    ? "inactive"
    : "active";
}

/** A stage is available when at least one incoming route is currently wired. */
export function stageRouteAvailable(
  stageId: string,
  edges: EngineEdge[],
  values: Record<string, EngineValue>,
): boolean {
  const incoming = edges.filter((edge) => edge.to === stageId);
  return incoming.length === 0 || incoming.some((edge) => isEdgeActive(edge, values));
}

export function isReversePair(edge: EngineEdge, edges: EngineEdge[]): boolean {
  const index = edges.indexOf(edge);
  return edges.some(
    (candidate, candidateIndex) =>
      candidateIndex < index && candidate.from === edge.to && candidate.to === edge.from,
  );
}

/** The visual grammar is derived from topology, never stage names. */
export function edgeVisualRole(
  edge: EngineEdge,
  edges: EngineEdge[],
  placements: StagePlacement[],
): EdgeVisualRole {
  if (isReversePair(edge, edges)) return "return";
  const laneById = new Map(placements.map((placement) => [placement.id, placement.lane]));
  return !edge.condition && laneById.get(edge.from) === "spine" && laneById.get(edge.to) === "spine"
    ? "spine"
    : "branch";
}
