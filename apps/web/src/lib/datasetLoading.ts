import type { ViewName } from "./types";

const CANONICAL_DATASET_VIEWS = new Set<ViewName>([
  "library",
  "graph",
]);

export function needsCanonicalDataset(view: ViewName): boolean {
  return CANONICAL_DATASET_VIEWS.has(view);
}
