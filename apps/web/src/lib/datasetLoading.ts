import type { ViewName } from "./types";

/**
 * Which views need the whole canonical projection.
 *
 * Exactly one does: the Canonical view reads every document's body, claims and links at once
 * (the tree, the proof, the neighbourhood card). The structure lens used to be the second —
 * it derived its readings from the same payload — and no longer is: its report comes from
 * `GET /v1/users/{uid}/lens`, which is the point of computing it in core.
 */
const CANONICAL_DATASET_VIEWS = new Set<ViewName>([
  "library",
]);

export function needsCanonicalDataset(view: ViewName): boolean {
  return CANONICAL_DATASET_VIEWS.has(view);
}
