-- pneuma-knowledge-compiler PG content layer (architecture.md §5).
-- Applied idempotently by the service at startup (CREATE TABLE IF NOT EXISTS);
-- v1 migration strategy = this file, no ORM/alembic. Every table's first
-- dimension is user_id (invariant I1: per-user isolation, no cross-user read).

CREATE TABLE IF NOT EXISTS sources (
    user_id  text        NOT NULL,
    source_id     text        NOT NULL,
    kind          text        NOT NULL,
    source_class  text        NOT NULL,
    title         text        NOT NULL,
    mime          text        NOT NULL,
    checksum      text        NOT NULL,
    created_at    timestamptz NOT NULL,
    meta          jsonb       NOT NULL DEFAULT '{}'::jsonb,
    intake_plan   jsonb,
    structure_map jsonb       NOT NULL DEFAULT '{"sections": []}'::jsonb,
    -- M3b: set by the compile worker after a source is digested into canonical.
    -- NULL = not yet compiled; drives the Sources digestion status + POST /compile.
    digested_at   timestamptz,
    PRIMARY KEY (user_id, source_id)
);

-- Idempotent additive migration for stores created before M3b (v1 strategy = this
-- file; no ORM/alembic). ADD COLUMN IF NOT EXISTS is a no-op when already present.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS digested_at timestamptz;
-- First-party provenance (RawSource.origin): 'upload' | 'context_stream'. Drives the
-- owner-aware context_stream adapter/skill path for first-party Pneuma meeting transcripts.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS origin text NOT NULL DEFAULT 'upload';

-- Content dedup key (invariant: append-only, same user + same checksum = same source).
CREATE UNIQUE INDEX IF NOT EXISTS sources_user_checksum
    ON sources (user_id, checksum);

CREATE TABLE IF NOT EXISTS blocks (
    user_id text    NOT NULL,
    source_id    text    NOT NULL,
    block_index  integer NOT NULL,
    text         text    NOT NULL,
    section_path jsonb   NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (user_id, source_id, block_index),
    FOREIGN KEY (user_id, source_id)
        REFERENCES sources (user_id, source_id) ON DELETE CASCADE
);

-- chunk_manifests: byte-deterministic rebuild anchor for semantic L2 chunking (M5).
-- Semantic chunking asks an LLM for topic/entity boundaries, which are NOT reproducible
-- across calls (the same source re-indexed gave 17 vs 19 chunks). This records the
-- boundaries the LLM chose for a given (content_digest, strategy, model), so a later
-- re-index REPLAYS them instead of re-detecting — turning "rebuildable" into
-- "byte-deterministic rebuild" (invariant I2: still derived, still rebuilt from L0; the
-- manifest only pins the one non-deterministic step + carries model lineage). A source
-- edit (new content_digest), a strategy switch, or a model change misses the cache and
-- re-detects, writing a fresh manifest. Chunk text stays a verbatim L0 slice regardless.
-- segments = the LLM segment intervals [[start,end],…]; result_digest = fingerprint of the
-- produced chunk char spans (audit: a drift shows up as a changed fingerprint).
CREATE TABLE IF NOT EXISTS chunk_manifests (
    user_id   text        NOT NULL,
    source_id      text        NOT NULL,
    strategy       text        NOT NULL,
    model          text        NOT NULL,
    content_digest text        NOT NULL,
    segments       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    result_digest  text        NOT NULL,
    updated_at     timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, source_id),
    FOREIGN KEY (user_id, source_id)
        REFERENCES sources (user_id, source_id) ON DELETE CASCADE
);

-- compile job queue: per-user_id serial claim via FOR UPDATE SKIP LOCKED (§5).
-- Generic kind + payload jsonb to match the JobQueue port (enqueue(user, kind,
-- payload)); a compile job's payload carries {"source_ids": [...]}.
CREATE TABLE IF NOT EXISTS compile_jobs (
    id           text        NOT NULL PRIMARY KEY,
    user_id text        NOT NULL,
    kind         text        NOT NULL,
    payload      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    status       text        NOT NULL DEFAULT 'queued',
    claimed_by   text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    claimed_at   timestamptz,
    completed_at timestamptz,
    -- M3b: worker outcome. ok=NULL while running; true=committed/noop, false=aborted.
    ok           boolean,
    detail       text,
    snapshot_ref text
);

ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS ok boolean;
ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS detail text;
ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS snapshot_ref text;

CREATE INDEX IF NOT EXISTS compile_jobs_claim
    ON compile_jobs (user_id, status, created_at);

-- compile_events: mechanically derived claim-level events per committed compile
-- (architecture.md §8; runner.derive_events). Append-only audit of what each compile
-- changed; the dataset endpoint reads these into the History / Process projections.
CREATE TABLE IF NOT EXISTS compile_events (
    user_id text        NOT NULL,
    job_id       text        NOT NULL,
    seq          integer     NOT NULL,
    snapshot_ref text        NOT NULL,
    type         text        NOT NULL,   -- claim_added | claim_revised
    path         text        NOT NULL,
    anchor       text        NOT NULL,
    before       text,
    after        text        NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, job_id, seq)
);

CREATE INDEX IF NOT EXISTS compile_events_user
    ON compile_events (user_id, created_at);

-- canonical_claims: the L3 retrieval projection (architecture.md §7; M4). Derived
-- (invariant I2): one row per anchored claim in the latest snapshot, rebuilt in whole
-- after every compile commit. citations is the [{source_id, block_start, block_end}]
-- provenance list; the GIN index backs citation reverse lookup (claims citing a source).
CREATE TABLE IF NOT EXISTS canonical_claims (
    user_id  text        NOT NULL,
    document_path text        NOT NULL,
    anchor        text        NOT NULL,
    section_path  jsonb       NOT NULL DEFAULT '[]'::jsonb,
    text          text        NOT NULL,
    citations     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    snapshot_ref  text        NOT NULL,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, document_path, anchor)
);

-- citation reverse lookup: canonical_claims WHERE citations @> '[{"source_id": "..."}]'.
CREATE INDEX IF NOT EXISTS canonical_claims_citations_gin
    ON canonical_claims USING gin (citations jsonb_path_ops);

CREATE INDEX IF NOT EXISTS canonical_claims_user
    ON canonical_claims (user_id, document_path);

-- briefings: derived preloaded-Q&A context packs (architecture.md §7; M4). scope is the
-- BriefingScope proposal, system_prefix the byte-stable knowledge pack built over
-- snapshot_ref. Rebuildable from canonical + the same scope (I2).
CREATE TABLE IF NOT EXISTS briefings (
    briefing_id   text        NOT NULL PRIMARY KEY,
    user_id  text        NOT NULL,
    scope         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    snapshot_ref  text        NOT NULL,
    system_prefix text        NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS briefings_user
    ON briefings (user_id, created_at);

-- evolve_tasks: schema-evolve proposals + their review lifecycle (schema-evolve §2.5).
-- One row per evolve run: a proposal that landed a branch (status='draft') awaiting
-- adopt/drop, or a terminal outcome ('no_change'/'aborted' — nothing to review; 'adopted'/
-- 'dropped'/'expired' — decided). base_ref is the git HEAD the reorganization branched
-- from; branch is refs/heads/evolve/<task_id> while a draft is live (deleted on decide).
-- proposal/summary/dropped are the review payload; detail carries the terminal reason or the
-- adopt provenance JSON (adopted_ref + pre_adopt_ref for the manual git-history rollback).
CREATE TABLE IF NOT EXISTS evolve_tasks (
    task_id       text        NOT NULL PRIMARY KEY,
    user_id  text        NOT NULL,
    status        text        NOT NULL,   -- draft|adopted|dropped|expired|aborted|no_change
    base_ref      text,
    branch        text,
    proposal      jsonb,
    summary       jsonb,
    dropped       jsonb,
    detail        text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    decided_at    timestamptz
);

CREATE INDEX IF NOT EXISTS evolve_tasks_user
    ON evolve_tasks (user_id, created_at);

-- user_profiles: onboarding-editable user picture (external-sync + local
-- override). When a user fills in / edits their profile in the UI it is persisted here
-- and takes precedence over the mock synthesis; users who never filled it in still fall
-- through to the deterministic mock (source="mock"). profile is the full UserProfile
-- JSON (source="user"); user_id is the sole key (invariant I1).
CREATE TABLE IF NOT EXISTS user_profiles (
    user_id text        NOT NULL PRIMARY KEY,
    profile      jsonb       NOT NULL,
    updated_at   timestamptz NOT NULL DEFAULT now()
);
