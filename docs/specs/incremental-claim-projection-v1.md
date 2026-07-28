# Incremental claim projection v1

Status: accepted for the OPC 84-day scale experiment

## 1. Problem

Canonical is the authority and every retrieval index is derived. The current worker
honors that invariant by deleting and rebuilding every PostgreSQL, Meilisearch and
Qdrant claim after each successful commit. In a chronological workload this makes the
cost of batch N proportional to all claims accumulated through N, even when the commit
changed only a handful of anchors. Real embeddings amplify the waste.

## 2. Two projection paths

1. `rebuild_projection` remains the explicit repair/strategy-migration path. It reads
   the complete canonical snapshot and fully rebuilds every derived store.
2. `sync_projection` is the normal commit path. It still projects the complete frozen
   canonical snapshot, compares it with PostgreSQL's last successful projection
   manifest, and writes only the delta to retrieval indexes.

Both paths are reconstructable from canonical. Incremental sync is an optimization of
derived writes, never a new source of truth.

## 3. Claim identity and equality

- Identity is `(document_path, anchor)`, matching the PostgreSQL primary key and the
  deterministic Meilisearch/Qdrant IDs.
- A claim is unchanged only when `section_path`, rendered `text` and the ordered
  citation triples are equal.
- `snapshot_ref` is projection metadata and does not make unchanged content dirty.
- A strategy change that alters rendered text naturally marks affected claims changed.

## 4. Commit protocol

For one user, under the existing single-writer queue:

1. read canonical at the just-committed ref;
2. project all current claims in deterministic order;
3. read the last PostgreSQL claim manifest and compute added/changed/deleted/unchanged;
4. embed only added or changed claim text;
5. idempotently upsert/delete the Meilisearch and Qdrant delta;
6. transactionally apply the same PostgreSQL delta and advance every surviving row's
   `snapshot_ref`;
7. only then mark the compile job complete.

PostgreSQL lands last. If a remote index or embedding call fails, its manifest remains
old and a retry recomputes the same delta. Deterministic remote IDs make partial
upserts/deletes safe to repeat.

## 5. Acceptance

- An unchanged claim is neither embedded nor upserted remotely.
- Added/changed claims are embedded exactly once per sync attempt.
- Removed identities are deleted from all three derived stores.
- PostgreSQL rows all carry the current snapshot ref after success.
- A zero-delta commit performs no embedding call.
- The explicit full rebuild remains idempotent and passes the existing three-store
  integration test.
- The 12-batch real experiment reports per-batch elapsed time without the prior
  cumulative re-embedding curve.
