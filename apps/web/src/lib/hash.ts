/**
 * URL-hash routing (P1-1). Encodes the active view + selection into the location
 * hash so views are deep-linkable and the browser Back button navigates WITHIN the
 * app instead of leaving it.
 *
 * Shapes:
 *   #/library
 *   #/library/document/doc-a11c
 *   #/library/claim/doc-a901/c-a912
 *   #/process/patch/kp-3
 *   #/process/job/job-2026...
 *   #/history/snapshot/src-c7a3...
 *   #/lens/node/doc-a11c
 *
 * The set of routable views is NOT declared here: it is the key set of `VIEW_LENSES` in
 * ./lenses, which is also what decides who may see each of them. One table, so a view can
 * never be deep-linkable and unknown to the lens guard at the same time.
 *
 * One view has been renamed since links to it were shared, so `LEGACY_VIEWS` below maps the
 * old first segment onto the new one on the way IN only. Nothing writes an old address: the
 * store re-writes the hash from the parsed state, so following an old link normalizes the
 * address bar in place and Back still walks in-app history.
 */
import { ROUTED_VIEWS } from "./lenses";
import type { Selection, ViewName } from "./types";

export function isViewName(v: string): v is ViewName {
  return (ROUTED_VIEWS as string[]).includes(v);
}

/**
 * Retired route names, and where they resolve now. `#/graph` was the structure surface
 * before it became the structure lens; `#/graph/node/<id>` keeps its selection, which the
 * lens view resolves to the document (or source) that node stood for.
 */
const LEGACY_VIEWS: Record<string, ViewName> = {
  graph: "lens",
};

/** The view a hash's first segment names, following a retired name to its successor. */
function routeView(segment: string): ViewName | null {
  if (isViewName(segment)) return segment;
  return LEGACY_VIEWS[segment] ?? null;
}

export function selectionToHash(view: ViewName, selection: Selection): string {
  const parts: string[] = [view];
  if (selection) {
    parts.push(selection.kind);
    if (selection.kind === "claim") {
      parts.push(selection.documentId, selection.anchor);
    } else if (selection.kind === "source") {
      parts.push(selection.id);
      if (selection.block != null) parts.push(String(selection.block));
    } else {
      parts.push(selection.id);
    }
  }
  return "#/" + parts.map(encodeURIComponent).join("/");
}

export interface RouteState {
  view: ViewName;
  selection: Selection;
}

export function hashToState(hash: string): RouteState | null {
  const segs = hash
    .replace(/^#\/?/, "")
    .split("/")
    .filter(Boolean)
    .map((s) => {
      try {
        return decodeURIComponent(s);
      } catch {
        return s;
      }
    });
  if (segs.length === 0) return null;
  const view = routeView(segs[0]);
  if (view === null) return null;

  let selection: Selection = null;
  const kind = segs[1];
  switch (kind) {
    case "document":
    case "node":
    case "patch":
    case "job":
    case "snapshot":
    case "evolve-task":
      if (segs[2]) selection = { kind, id: segs[2] };
      break;
    case "claim":
      if (segs[2] && segs[3])
        selection = { kind: "claim", documentId: segs[2], anchor: segs[3] };
      break;
    case "source":
      if (segs[2]) {
        const block = segs[3] != null ? Number(segs[3]) : NaN;
        selection = Number.isFinite(block)
          ? { kind: "source", id: segs[2], block }
          : { kind: "source", id: segs[2] };
      }
      break;
    default:
      selection = null;
  }
  return { view, selection };
}

export function sameSelection(a: Selection, b: Selection): boolean {
  if (a === b) return true;
  if (!a || !b) return false;
  if (a.kind !== b.kind) return false;
  if (a.kind === "claim" && b.kind === "claim")
    return a.documentId === b.documentId && a.anchor === b.anchor;
  if (a.kind === "source" && b.kind === "source")
    return a.id === b.id && a.block === b.block;
  if (a.kind !== "claim" && b.kind !== "claim") return a.id === b.id;
  return false;
}
