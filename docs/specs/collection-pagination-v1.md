# Collection pagination v1

Status: accepted for the OPC 84-day scale experiment

## 1. Problem

The 84-day experiment produces 98 sources, 196 jobs, 62 canonical snapshots and a
302-entry audit timeline. The current API returns unbounded arrays and the web UI maps
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
snapshot ref and is valid only if that ref still exists for this user.

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

## 5. Dataset and history follow-up

Pagination of Sources and Jobs does not make `GET /dataset` acceptable. The next slice
must:

1. stop loading the full dataset during application boot;
2. load canonical documents/graph only for views that consume them;
3. move History to its own paged audit contract instead of rendering the entire
   `timeline`;
4. preserve snapshot reads by passing the selected ref to the lazy canonical request.

## 6. Acceptance evidence

- Integration tests against PostgreSQL prove stable ordering, limits, totals, filters,
  cursor continuation, malformed-cursor failure and cross-user isolation.
- Web tests prove API query construction and page-state transitions.
- The OPC 84-day browser rerun proves Sources and Process render at most one page.
- The post-fix report compares API bytes, route time, DOM size and scroll height with
  `docs/experiments/results/opc-84d-frontend-baseline.json`.
