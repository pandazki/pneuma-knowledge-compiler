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
 *   #/graph/node/doc-a11c
 */
import type { Selection, ViewName } from "./types";

const VIEWS: ViewName[] = [
  "overview",
  "profile",
  "sources",
  "ingest",
  "recall",
  // "ask" and "context_stream" are nav-visible views; both must be here or a deep link to
  // them parses as null and silently falls back to the default view.
  "ask",
  "context_stream",
  "library",
  "process",
  "history",
  "graph",
  "evolve",
  // hidden route: primitives 状态矩阵（验收用，不进目录）
  "components",
];

export function isViewName(v: string): v is ViewName {
  return (VIEWS as string[]).includes(v);
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
  const view = segs[0];
  if (!isViewName(view)) return null;

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
