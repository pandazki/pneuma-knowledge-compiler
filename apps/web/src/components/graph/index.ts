import { lazy } from "react";

/** 图谱画布：lazy 加载（@xyflow/react + dagre 不进主包，DESIGN.md 硬性规则 11）。 */
export const GraphCanvas = lazy(() => import("./GraphCanvas"));
