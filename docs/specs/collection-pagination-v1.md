# Collection pagination v1

Status: accepted after a 12-week longitudinal scale exercise

## 1. Problem

The 84-day experiment produces 98 sources, 196 jobs, 62 canonical snapshots and a
356-entry audit ledger (98 source captures + 196 jobs + 62 committed patches). The
current API returns unbounded arrays and the web UI maps
each array directly into the DOM. At this modest scale the Process and History pages
already create more than 2,000 DOM nodes, while `GET /dataset` transfers 437 KB and
takes about 0.58 seconds on localhost.

Pagination must reduce work at the storage, API and rendering boundaries. Slicing an
already-loaded array in React does not satisfy this contract.

## 2. Shared page contract

Collection endpoints return an envelope:

```json
{
  "items": [],
  "page": {
    "limit": 25,
    "total": 196,
    "next_cursor": "opaque-or-null"
  }
}
```

Invariants:

1. `limit` defaults to 25, has a minimum of 1 and a maximum of 100.
2. `total` counts the filtered collection, not only the current page.
3. `next_cursor` is opaque to clients. It is `null` only on the last page.
4. A malformed or context-incompatible cursor returns HTTP 422; it never silently
   restarts at page one.
5. A page contains at most `limit` items and never repeats an item from its immediately
   preceding page.
6. User isolation is applied before filtering, counting and cursor comparison.
7. The database query fetches at most `limit + 1` rows. It must not load the complete
   collection and slice it in application memory.

## 3. Endpoint contracts

### `GET /v1/users/{user_id}/sources`

Parameters:

- `limit`: shared limit.
- `cursor`: opaque continuation.
- `query`: optional case-insensitive title search.
- `kind`: optional exact source kind.

Ordering is `(created_at DESC, source_id DESC)`. The cursor binds to the user, query and
kind filter.

Every source item keeps the existing `SourceOut` fields. `block_count` and
`digested_at` are computed only for sources in the page.

### `GET /v1/users/{user_id}/jobs`

Parameters:

- `limit`: shared limit.
- `cursor`: opaque continuation.
- `status`: optional exact queue status.
- `kind`: optional exact job kind.

Ordering is `(created_at DESC, job_id DESC)`. The cursor binds to the user and filters.
Active-job polling refreshes page one only; it does not append duplicate historical
pages.

### `GET /v1/users/{user_id}/snapshots`

Parameters:

- `limit`: shared limit.
- `cursor`: opaque continuation.

Ordering follows canonical git history, newest first. The cursor is the last returned
snapshot ref and is valid only if that ref remains an ancestor of this user's HEAD.
Continuation walks that ref's ancestors rather than a numeric offset, so new commits
inserted at HEAD after page one do not shift or invalidate page two.

### `GET /v1/users/{user_id}/history`

Parameters:

- `limit`: shared limit.
- `cursor`: opaque continuation.

The endpoint merges source captures (`snapshot`), compile jobs (`job`) and committed
compile-event groups (`patch`) into one audit ledger ordered by
`(ts DESC, kind DESC, ref DESC)`. In addition to the shared page envelope it returns
stable collection counts:

```json
{
  "items": [
    {
      "kind": "patch",
      "ref": "commit-or-snapshot-ref",
      "ts": "2026-07-28T12:00:00+00:00",
      "payload": {}
    }
  ],
  "page": {
    "limit": 25,
    "total": 356,
    "next_cursor": "opaque-or-null"
  },
  "counts": {
    "patches": 62,
    "jobs": 196,
    "snapshots": 98,
    "total": 356
  }
}
```

`counts.total` equals `page.total`. A patch count is one per compile job with compile
events, never one per individual claim event. The cursor binds to the user and the
three-part ordering position.

## 4. Web behavior

1. Sources and Process load only page one on entry.
2. Both views expose explicit previous/next controls and show
   `visible range / total` without rendering hidden pages.
3. A selected source reached by deep link or cross-view citation is fetched directly;
   it does not require downloading pages until the source happens to appear.
4. Overview counts use `page.total` from `limit=1` requests.
5. Source-selection tools may progressively request more pages, but they must not block
   the route shell or application boot on a complete source inventory.
6. Snapshot selection initially loads the newest page. Older snapshots are loaded on
   demand.
7. History loads only its own first audit page on entry. It must not request
   `GET /dataset`, and it renders at most one page of ledger rows.
8. History preserves the selected row and detail pane within the current page. Links
   whose target is not present in that bounded page remain readable but are not
   presented as actionable controls.

## 5. Dataset and history follow-up

Pagination of Sources and Jobs does not make `GET /dataset` acceptable. The next slice
must:

1. stop loading the full dataset during application boot;
2. load canonical documents/graph only for views that consume them;
3. move History to its own paged audit contract instead of rendering the entire
   `timeline` (contract defined above);
4. preserve snapshot reads by passing the selected ref to the lazy canonical request.

### 5.1 Canonical tree read

Library and Graph legitimately need every canonical document at the selected snapshot;
pagination would make their indexes and graph incomplete. The canonical adapter must
therefore keep the result complete while bounding process overhead:

1. one list operation reads the selected Git tree through one `git archive` subprocess;
2. it must not run `git show` once per document or extract the archive to disk;
3. non-Markdown metadata in the same commit is ignored;
4. document ordering and parsing are byte-for-byte compatible with the existing list
   contract;
5. HEAD still performs one existence probe so a newly-created empty user returns an
   empty collection rather than a Git error.

### 5.2 Canonical-only dataset projection

`GET /v1/users/{user_id}/dataset` keeps its existing full response by default for
export/backward compatibility. Canonical readers request `audit=false`:

1. `workspace`, `documents`, `graph` and `claim_labels` remain complete;
2. `timeline` keeps the stable schema but its collection fields are empty, and
   `journal` is empty;
3. the service must not call the unbounded job or compile-event list methods;
4. no audit record is deleted or made unreachable: History owns that concern through
   its paged endpoint;
5. the web Library and Graph requests use `audit=false`; historical snapshot reads
   combine it with `at=<ref>`.

## 6. Acceptance evidence

- Integration tests against PostgreSQL prove stable ordering, limits, totals, filters,
  cursor continuation, malformed-cursor failure and cross-user isolation.
- Web tests prove API query construction and page-state transitions.
- The longitudinal browser rerun proves Sources and Process render at most one page.
- The retained regression tests cover API bounds, page-state transitions, DOM size and
  scroll behavior. One-off baseline captures are intentionally not kept as project
  documentation.
