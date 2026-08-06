import { useMemo, useState } from "react";
import {
  Background,
  BackgroundVariant,
  BaseEdge,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Panel,
  Position,
  ReactFlow,
  getBezierPath,
  getStraightPath,
  type Edge,
  type EdgeProps,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  Cpu,
  FileText,
  GitBranch,
  Inbox,
  MessagesSquare,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  UserRound,
  X,
  type LucideIcon,
} from "lucide-react";
import type {
  EngineAccessRoute,
  EngineSchema,
  EngineStage,
  EngineState,
  EngineValue,
} from "@/engine/types";
import { isEdgeActive, pickLocalized } from "@/lib/engineConsole";
import type { MessageKey } from "@/lib/i18n";
import { useLocale, useT } from "@/lib/useT";
import { IconButton } from "@/ui/IconButton";
import {
  accessRouteState,
  edgeVisualRole,
  placeAccessRouteMerge,
  placeAccessRoutes,
  placeEngineStages,
  stageRouteAvailable,
  type AccessRouteState,
  type EdgeVisualRole,
  type StageLane,
} from "./pipelinePresentation";

const STAGE_ICON: Record<string, LucideIcon> = {
  intake: Inbox,
  compile: FileText,
  challenge: ShieldCheck,
  evolve: GitBranch,
  recall: Search,
  models: Cpu,
  persona: UserRound,
  prompts: MessagesSquare,
};

type StageNodeData = {
  stage: EngineStage;
  edited: boolean;
  available: boolean;
  stateAvailable: boolean;
  lane: StageLane;
};

type StageFlowNode = Node<StageNodeData, "engineStage">;
type SupportAreaNode = Node<{ title: string }, "supportArea">;
type AccessRouteNodeData = {
  route: EngineAccessRoute;
  state: AccessRouteState;
};
type AccessRouteFlowNode = Node<AccessRouteNodeData, "accessRoute">;
type AccessMergeFlowNode = Node<Record<string, never>, "accessMerge">;
type EngineMapNode = StageFlowNode | SupportAreaNode | AccessRouteFlowNode | AccessMergeFlowNode;

type AccessEdgeRole = "access-source" | "access-merge" | "access-trunk";

type FlowEdgeData = {
  label: string;
  active: boolean;
  conditional: boolean;
  role: EdgeVisualRole | AccessEdgeRole;
  routeState?: AccessRouteState;
  accessGaps?: number[];
};

type EngineFlowEdge = Edge<FlowEdgeData, "engineEdge">;

const nodeTypes = {
  engineStage: EngineStageNode,
  supportArea: SupportAreaNode,
  accessRoute: AccessRouteNode,
  accessMerge: AccessMergeNode,
};
const edgeTypes = { engineEdge: EngineFlowEdge };

export interface PipelineMapProps {
  schema: EngineSchema;
  values: Record<string, EngineValue>;
  state: EngineState | null;
  editedRefs: ReadonlySet<string>;
  selectedStageId: string | null;
  onSelect: (stageId: string | null) => void;
}

export function PipelineMap({
  schema,
  values,
  state,
  editedRefs,
  selectedStageId,
  onSelect,
}: PipelineMapProps) {
  const locale = useLocale();
  const t = useT();
  const [selectedRouteId, setSelectedRouteId] = useState<string | null>(null);
  const placements = useMemo(() => placeEngineStages(schema), [schema]);
  const positionById = useMemo(
    () => new Map(placements.map((placement) => [placement.id, placement])),
    [placements],
  );
  const routePlacements = useMemo(
    () => placeAccessRoutes(schema.access_routes ?? [], placements),
    [placements, schema.access_routes],
  );
  const routePositionById = useMemo(
    () => new Map(routePlacements.map((placement) => [placement.id, placement])),
    [routePlacements],
  );
  const routeMerge = useMemo(
    () => placeAccessRouteMerge(schema.access_routes ?? [], placements, routePlacements),
    [placements, routePlacements, schema.access_routes],
  );
  const selectedRoute =
    schema.access_routes?.find((route) => route.id === selectedRouteId) ?? null;

  const computedNodes = useMemo<EngineMapNode[]>(() => {
    const stageNodes: StageFlowNode[] = schema.stages.map((stage) => {
      const placement = positionById.get(stage.id) ?? {
        id: stage.id,
        x: 70,
        y: 758,
        lane: "support" as const,
      };
      return {
        id: stage.id,
        type: "engineStage",
        position: { x: placement.x, y: placement.y },
        selected: stage.id === selectedStageId,
        data: {
          stage,
          edited: [...editedRefs].some((ref) => ref.startsWith(`${stage.id}.`)),
          available: stageRouteAvailable(stage.id, schema.edges, values),
          stateAvailable: state != null,
          lane: placement.lane,
        },
        ariaLabel: t("engineConsole.stage.open", {
          stage: pickLocalized(stage.title, locale),
        }),
        draggable: false,
      };
    });
    const support = placements.filter((placement) => placement.lane === "support");
    const routeNodes: AccessRouteFlowNode[] = (schema.access_routes ?? []).flatMap((route) => {
      const placement = routePositionById.get(route.id);
      if (!placement) return [];
      return [{
        id: `__access-${route.id}`,
        type: "accessRoute",
        position: { x: placement.x, y: placement.y },
        selected: route.id === selectedRouteId,
        data: { route, state: accessRouteState(route, values) },
        ariaLabel: t("engineConsole.route.open", {
          route: pickLocalized(route.title, locale),
        }),
        draggable: false,
        style: { width: placement.width },
      }];
    });
    const mergeNode: AccessMergeFlowNode[] = routeMerge
      ? [{
          id: "__access-merge",
          type: "accessMerge",
          position: { x: routeMerge.x - 9, y: routeMerge.y - 9 },
          data: {},
          draggable: false,
          selectable: false,
          focusable: false,
        }]
      : [];
    if (support.length === 0) return [...mergeNode, ...stageNodes, ...routeNodes];
    const minX = Math.min(...support.map((placement) => placement.x));
    const maxX = Math.max(...support.map((placement) => placement.x));
    const supportArea: SupportAreaNode = {
      id: "__support-area",
      type: "supportArea",
      position: { x: minX - 38, y: support[0].y - 58 },
      data: { title: t("engineConsole.map.supporting") },
      draggable: false,
      selectable: false,
      focusable: false,
      zIndex: -1,
      style: { width: maxX - minX + 292, height: 190 },
    };
    return [supportArea, ...mergeNode, ...stageNodes, ...routeNodes];
  }, [
    editedRefs,
    locale,
    placements,
    positionById,
    routePositionById,
    routeMerge,
    schema.edges,
    schema.access_routes,
    schema.stages,
    selectedRouteId,
    selectedStageId,
    state,
    t,
    values,
  ]);

  const computedEdges = useMemo<EngineFlowEdge[]>(() => {
    const processEdges: EngineFlowEdge[] = schema.edges.map((edge, index) => {
        const source = positionById.get(edge.from);
        const target = positionById.get(edge.to);
        const role = edgeVisualRole(edge, schema.edges, placements);
        const active = isEdgeActive(edge, values);
        const conditional = edge.condition != null;
        const handles = edgeHandles(source, target, role);
        return {
          id: `${edge.from}-${edge.to}-${index}`,
          source: edge.from,
          target: edge.to,
          sourceHandle: handles.source,
          targetHandle: handles.target,
          type: "engineEdge",
          selectable: false,
          focusable: false,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 14,
            height: 14,
            color:
              role === "spine"
                ? "var(--engine-accent)"
                : conditional
                  ? active
                    ? "var(--engine-accent)"
                    : "var(--engine-ink-3)"
                  : "var(--engine-line-2)",
          },
          data: {
            label: pickLocalized(edge.label, locale),
            active,
            conditional,
            role,
          },
        };
      });
    const placedRoutes = (schema.access_routes ?? []).flatMap((route) => {
      const placement = routePositionById.get(route.id);
      return placement ? [{ route, placement }] : [];
    });
    const routesBySource = new Map<string, typeof placedRoutes>();
    for (const placedRoute of placedRoutes) {
      routesBySource.set(placedRoute.route.from, [
        ...(routesBySource.get(placedRoute.route.from) ?? []),
        placedRoute,
      ]);
    }
    const accessSourceEdges: EngineFlowEdge[] = [...routesBySource].flatMap(
      ([sourceId, sourceRoutes]) => {
        const source = positionById.get(sourceId);
        if (!source) return [];
        const lastRoute = [...sourceRoutes].sort((a, b) => b.placement.y - a.placement.y)[0];
        if (!lastRoute) return [];
        const states = sourceRoutes.map(({ route }) => accessRouteState(route, values));
        const routeState: AccessRouteState = states.includes("active")
          ? "active"
          : states.includes("conditional")
            ? "conditional"
            : "inactive";
        const sourceCenterX = source.x + 108;
        const accessGaps = placedRoutes
          .filter(
            ({ route, placement }) =>
              route.from !== sourceId &&
              placement.x < sourceCenterX &&
              placement.x + placement.width > sourceCenterX,
          )
          .map(({ placement }) => placement.y + 16);
        return [{
          id: `access-source-${sourceId}`,
          source: sourceId,
          target: `__access-${lastRoute.route.id}`,
          sourceHandle: "bottom-source",
          targetHandle: "left-target",
          type: "engineEdge",
          selectable: false,
          focusable: false,
          data: {
            label: "",
            active: routeState === "active",
            conditional: routeState !== "active",
            role: "access-source",
            routeState,
            accessGaps,
          },
        }];
      },
    );
    const accessMergeEdges: EngineFlowEdge[] = routeMerge
      ? placedRoutes.map(({ route }) => {
          const routeState = accessRouteState(route, values);
          return {
            id: `access-merge-${route.id}`,
            source: `__access-${route.id}`,
            target: "__access-merge",
            sourceHandle: "right-source",
            targetHandle: "bottom-target",
            type: "engineEdge" as const,
            selectable: false,
            focusable: false,
            data: {
              label: "",
              active: routeState === "active",
              conditional: Boolean(route.condition),
              role: "access-merge" as const,
              routeState,
            },
          };
        })
      : [];
    const accessTrunkEdge: EngineFlowEdge[] = routeMerge
      ? [{
          id: "access-merge-recall",
          source: "__access-merge",
          target: routeMerge.targetId,
          sourceHandle: "top-source",
          targetHandle: "bottom-target",
          type: "engineEdge",
          selectable: false,
          focusable: false,
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 13,
            height: 13,
            color: "var(--engine-accent)",
          },
          data: {
            label: "",
            active: true,
            conditional: false,
            role: "access-trunk",
            routeState: "active",
          },
        }]
      : [];
    return [...processEdges, ...accessSourceEdges, ...accessMergeEdges, ...accessTrunkEdge];
  }, [
    locale,
    placements,
    positionById,
    routeMerge,
    routePositionById,
    schema.access_routes,
    schema.edges,
    values,
  ]);

  return (
    <ReactFlow<EngineMapNode, EngineFlowEdge>
      nodes={computedNodes}
      edges={computedEdges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodeClick={(_, node) => {
        if (node.type === "engineStage") {
          setSelectedRouteId(null);
          onSelect(node.id);
        } else if (node.type === "accessRoute") {
          onSelect(null);
          setSelectedRouteId((current) => current === node.data.route.id ? null : node.data.route.id);
        }
      }}
      onPaneClick={() => {
        setSelectedRouteId(null);
        onSelect(null);
      }}
      fitView
      fitViewOptions={{ padding: 0.08, minZoom: 0.4, maxZoom: 0.95 }}
      minZoom={0.28}
      maxZoom={1.45}
      nodesDraggable={false}
      nodesConnectable={false}
      edgesReconnectable={false}
      deleteKeyCode={null}
      selectionKeyCode={null}
      multiSelectionKeyCode={null}
      panOnScroll
      zoomOnScroll={false}
      zoomOnPinch
      proOptions={{ hideAttribution: true }}
      aria-label={t("engineConsole.map.aria")}
    >
      <Background
        variant={BackgroundVariant.Dots}
        gap={24}
        size={1.2}
        color="var(--engine-grid)"
      />
      <Controls
        showInteractive={false}
        fitViewOptions={{ padding: 0.08, minZoom: 0.4, maxZoom: 0.95 }}
        aria-label={t("engineConsole.map.controls")}
      />
      {selectedRoute && (
        <Panel position="top-right" className="engine-access-detail">
          <div>
            <strong>{pickLocalized(selectedRoute.title, locale)}</strong>
            <span>
              {t(accessRouteStatusKey(accessRouteState(selectedRoute, values), Boolean(selectedRoute.condition)))}
            </span>
          </div>
          <IconButton
            size="sm"
            aria-label={t("common.close")}
            onClick={() => setSelectedRouteId(null)}
          >
            <X size={14} aria-hidden />
          </IconButton>
          <p>{pickLocalized(selectedRoute.summary, locale)}</p>
        </Panel>
      )}
    </ReactFlow>
  );
}

function accessRouteStatusKey(state: AccessRouteState, conditional: boolean): MessageKey {
  if (!conditional) return "engineConsole.route.unconditional";
  if (state === "active") return "engineConsole.route.planActive";
  if (state === "inactive") return "engineConsole.route.planInactive";
  return "engineConsole.route.planDependent";
}

function edgeHandles(
  source: { x: number; y: number } | undefined,
  target: { x: number; y: number } | undefined,
  role: EdgeVisualRole,
): { source: string; target: string } {
  if (role === "return") return { source: "right-source", target: "right-target" };
  const dx = (target?.x ?? 0) - (source?.x ?? 0);
  const dy = (target?.y ?? 0) - (source?.y ?? 0);
  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0
      ? { source: "right-source", target: "left-target" }
      : { source: "left-source", target: "right-target" };
  }
  return dy >= 0
    ? { source: "bottom-source", target: "top-target" }
    : { source: "top-source", target: "bottom-target" };
}

function EngineStageNode({ data, selected }: NodeProps<StageFlowNode>) {
  const t = useT();
  const locale = useLocale();
  const Icon = STAGE_ICON[data.stage.id] ?? SlidersHorizontal;
  const document = data.stage.knobs.some((knob) => knob.type === "document");
  const overlays = data.stage.knobs.some((knob) => knob.type === "overlay_map");
  const statusKey = !data.stateAvailable
    ? "engineConsole.node.unavailable"
    : !data.available
      ? "engineConsole.node.standby"
      : document
        ? "engineConsole.node.document"
        : overlays
          ? "engineConsole.node.overlays"
          : data.lane === "support"
            ? "engineConsole.node.configured"
            : "engineConsole.node.live";

  return (
    <article
      className="engine-stage-node"
      data-selected={selected || undefined}
      data-available={data.available || undefined}
      data-edited={data.edited || undefined}
      data-lane={data.lane}
    >
      {(["top", "right", "bottom", "left"] as const).flatMap((side) => {
        const position = {
          top: Position.Top,
          right: Position.Right,
          bottom: Position.Bottom,
          left: Position.Left,
        }[side];
        return [
          <Handle
            key={`${side}-target`}
            id={`${side}-target`}
            type="target"
            position={position}
            className="engine-handle"
          />,
          <Handle
            key={`${side}-source`}
            id={`${side}-source`}
            type="source"
            position={position}
            className="engine-handle"
          />,
        ];
      })}

      <header className="engine-stage-node__header">
        <span className="engine-stage-node__icon">
          <Icon size={17} aria-hidden />
        </span>
        <span className="engine-stage-node__heading">
          <strong>{pickLocalized(data.stage.title, locale)}</strong>
          <span title={data.stage.file}>{data.stage.file}</span>
        </span>
        {data.edited && (
          <span className="engine-stage-node__edited" title={t("engineConsole.map.edited")} />
        )}
      </header>

      <div className="engine-stage-node__status">
        <span className="engine-status-dot" />
        <span>{t(statusKey)}</span>
      </div>
    </article>
  );
}

function SupportAreaNode({ data }: NodeProps<SupportAreaNode>) {
  return (
    <section className="engine-support-area" aria-hidden>
      <span>{data.title}</span>
    </section>
  );
}

function AccessRouteNode({ data, selected }: NodeProps<AccessRouteFlowNode>) {
  const locale = useLocale();
  return (
    <article
      className="engine-access-node"
      data-state={data.state}
      data-selected={selected || undefined}
    >
      <Handle
        id="left-target"
        type="target"
        position={Position.Left}
        className="engine-handle"
      />
      <Handle
        id="right-source"
        type="source"
        position={Position.Right}
        className="engine-handle"
      />
      <strong className="engine-access-node__label">
        {pickLocalized(data.route.title, locale)}
      </strong>
    </article>
  );
}

function AccessMergeNode() {
  return (
    <span className="engine-access-merge" aria-hidden>
      <Handle
        id="bottom-target"
        type="target"
        position={Position.Bottom}
        className="engine-handle"
      />
      <Handle
        id="top-source"
        type="source"
        position={Position.Top}
        className="engine-handle"
      />
      <i />
    </span>
  );
}

function EngineFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  markerEnd,
  data,
}: EdgeProps<EngineFlowEdge>) {
  const role = data?.role ?? "branch";
  const accessRole = role.startsWith("access-");
  const [path, labelX, labelY] =
    role === "spine"
      ? getStraightPath({ sourceX, sourceY, targetX, targetY })
      : role === "return"
        ? getReturnPath(sourceX, sourceY, targetX, targetY)
        : role === "access-source"
          ? getAccessSourcePath(sourceX, sourceY, targetX, targetY, data?.accessGaps ?? [])
          : role === "access-trunk"
            ? getStraightPath({ sourceX, sourceY, targetX, targetY })
            : getBezierPath({
                sourceX,
                sourceY,
                targetX,
                targetY,
                sourcePosition,
                targetPosition,
                curvature: 0.24,
              });
  const state =
    accessRole
      ? data?.routeState ?? "conditional"
      : data?.conditional
        ? data.active
          ? "active"
          : "inactive"
        : "plain";
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        className="engine-flow-edge"
        data-state={state}
        data-role={role}
      />
      {data?.label && (
        <EdgeLabelRenderer>
          <span
            className="engine-flow-edge__label"
            data-state={state}
            data-role={role}
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
          >
            {data.label}
          </span>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

function getAccessSourcePath(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
  gaps: readonly number[],
): [string, number, number] {
  const direction = targetY >= sourceY ? 1 : -1;
  const minY = Math.min(sourceY, targetY);
  const maxY = Math.max(sourceY, targetY);
  const orderedGaps = gaps
    .filter((gap) => gap > minY + 8 && gap < maxY - 8)
    .sort((a, b) => direction * (a - b));
  let cursorY = sourceY;
  const segments = [`M ${sourceX},${sourceY} L ${targetX},${sourceY}`];
  for (const gap of orderedGaps) {
    const before = gap - direction * 6;
    const after = gap + direction * 6;
    segments.push(`M ${targetX},${cursorY} L ${targetX},${before}`);
    cursorY = after;
  }
  segments.push(`M ${targetX},${cursorY} L ${targetX},${targetY}`);
  return [segments.join(" "), targetX, (sourceY + targetY) / 2];
}

function getReturnPath(
  sourceX: number,
  sourceY: number,
  targetX: number,
  targetY: number,
): [string, number, number] {
  const loopX = Math.max(sourceX, targetX) + 112;
  return [
    `M ${sourceX},${sourceY} C ${loopX},${sourceY} ${loopX},${targetY} ${targetX},${targetY}`,
    loopX - 8,
    (sourceY + targetY) / 2,
  ];
}
