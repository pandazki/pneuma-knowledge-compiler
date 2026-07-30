import { lazy } from "react";

/** Graph canvas, lazily loaded (@xyflow/react + dagre stay out of the main bundle —
 *  DESIGN.md hard rule 11). */
export const GraphCanvas = lazy(() => import("./GraphCanvas"));
