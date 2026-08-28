/**
 * Locating a deep-linked job in a cursor-paged ledger.
 *
 * `#/process/job/<id>` names a job; the ledger route only pages. So the page walks forward
 * from the top until the row is on screen, and gives up after a bound. The walk is a small
 * state machine, kept pure here so the one case that bit in production is pinned by a test:
 * the link opened ON the first page. Resetting to the first page then changed nothing — the
 * same cursor, the same rows — so the effect that drives the walk never ran again, and the
 * "paging forward…" notice sat there forever. The step must advance from the page it is
 * already reading, not re-request it.
 */

export interface LocateWalk {
  id: string;
  /** Pages stepped so far; `-1` marks a search finished (found, or given up) for this id. */
  pagesWalked: number;
}

export interface LocatePage {
  ids: readonly string[];
  /** The cursor this page was loaded with — `null` is the first page. */
  loadedCursor: string | null;
  nextCursor: string | null;
}

export type LocateStep =
  | { kind: "found"; walk: LocateWalk }
  | { kind: "settled" }
  | { kind: "restart"; walk: LocateWalk }
  | { kind: "advance"; walk: LocateWalk; cursor: string }
  | { kind: "give-up"; walk: LocateWalk };

export function locateStep(
  walk: LocateWalk | null,
  jobId: string,
  page: LocatePage,
  pageLimit: number,
): LocateStep {
  if (page.ids.includes(jobId)) return { kind: "found", walk: { id: jobId, pagesWalked: -1 } };
  // A search already finished for this id: a poll landing a new page must not restart it.
  if (walk?.id === jobId && walk.pagesWalked < 0) return { kind: "settled" };
  let current = walk;
  if (!current || current.id !== jobId) {
    current = { id: jobId, pagesWalked: 0 };
    // The job may be on a page BEHIND the one being read: start from the top — unless the
    // top is what is being read, in which case stepping forward from it IS the start.
    if (page.loadedCursor !== null) return { kind: "restart", walk: current };
  }
  if (!page.nextCursor || current.pagesWalked >= pageLimit) {
    return { kind: "give-up", walk: { id: jobId, pagesWalked: -1 } };
  }
  return {
    kind: "advance",
    walk: { id: jobId, pagesWalked: current.pagesWalked + 1 },
    cursor: page.nextCursor,
  };
}
