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
-- The archive (docs/design/archive.md §2.2): one of the two authoritative marks, the one
-- that lives on L0. NULL = live; a timestamp = the Owner has retired this material. Nothing
-- is removed — every block, the structure map, the media and the chunk manifest stay exactly
-- as they were, and L0 fetch by locator stays unconditional (invariant I3), so a claim
-- citing an archived source still resolves to its exact passage. What the mark changes is
-- the SEARCH face (the L1/L2 flags derived from it) and the listing default.
ALTER TABLE sources ADD COLUMN IF NOT EXISTS archived_at timestamptz;

-- Content dedup key (invariant: append-only, same user + same checksum = same source).
CREATE UNIQUE INDEX IF NOT EXISTS sources_user_checksum
    ON sources (user_id, checksum);

CREATE TABLE IF NOT EXISTS blocks (
    user_id text    NOT NULL,
    source_id    text    NOT NULL,
    block_index  integer NOT NULL,
    text         text    NOT NULL,
    section_path jsonb   NOT NULL DEFAULT '[]'::jsonb,
    images       jsonb   NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (user_id, source_id, block_index),
    FOREIGN KEY (user_id, source_id)
        REFERENCES sources (user_id, source_id) ON DELETE CASCADE
);

-- Additive v1 migration for databases created before block-aligned image support.
ALTER TABLE blocks ADD COLUMN IF NOT EXISTS images jsonb NOT NULL DEFAULT '[]'::jsonb;

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
-- payload)); a compile job's payload carries {"source_ids": [...]}, an index job
-- {"source_id": ...}, an evolve_adopt job {"task_id": ...}, and a groom (document
-- rollover) job {"path": ...}. Deliberately not an enum: a new pipeline stage rides the
-- one per-user serial queue without a migration, which is what keeps the git
-- single-writer guarantee covering every canonical write channel.
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
    snapshot_ref text,
    -- Post-compile derived narration (brief_enabled): generated from this job's
    -- compile_events only, shown on the History timeline. NULL = none generated.
    brief        text
);

ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS ok boolean;
ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS detail text;
ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS snapshot_ref text;
ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS brief text;
-- What the JOB spent, as the compile loop's own usage mapping (input/output/total tokens,
-- summed across the first round and its repair round). Tokens and never money — the same
-- rule the consultations record follows: the count is what happened, the price is declared
-- elsewhere and derived when somebody reads. NULL = the job predates the column, or nothing
-- was reported; neither is a claim that the job was free.
ALTER TABLE compile_jobs ADD COLUMN IF NOT EXISTS token_usage jsonb;

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
    type         text        NOT NULL,   -- claim_added | claim_revised | claim_superseded
                                         -- | overview_rewritten (document-level: anchor is '')
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
-- (invariant I2): one row per anchored claim in the latest snapshot. Normal commits
-- synchronize a content delta; repair/strategy migration can rebuild it in whole.
-- citations is the [{source_id, block_start, block_end}]
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
    -- Derived from the document's path, not stored judgement: a claim is archived iff its
    -- page sits under `archive/` (core domain/archive.py). It rides the projection row so a
    -- rebuild that only flips the flag still reaches the two claim indexes.
    archived      boolean     NOT NULL DEFAULT false,
    PRIMARY KEY (user_id, document_path, anchor)
);

-- Additive v1 migration for stores created before the archive existed.
ALTER TABLE canonical_claims
    ADD COLUMN IF NOT EXISTS archived boolean NOT NULL DEFAULT false;

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

-- The build's measured per-stage wall-clock (recall/briefing.py BUILD_STAGE_ORDER), stored
-- as the wire shape [{name, ms, status, detail}] so the detail endpoint can hand a past
-- briefing's breakdown back unchanged. Additive: rows written before it read as '[]'.
ALTER TABLE briefings ADD COLUMN IF NOT EXISTS stages jsonb NOT NULL DEFAULT '[]'::jsonb;

-- What the PACK put in front of the model, recorded when the pack was built: the addresses
-- of exactly the rendered blocks the character budget left whole ([{kind, ref, path}], the
-- same shape `consultations.evidence_handed` uses). An ask over this briefing admits its
-- citations against this list, so it cannot be re-derived from `system_prefix` later — the
-- pack is text by then, and text cannot say whether a `[cite: …]` in it is a marker the
-- renderer wrote or a line the source quotes. Additive: a row written before this column
-- existed reads as '[]', and an ask over it admits nothing, which is the honest reading of
-- "nobody recorded what this pack showed".
ALTER TABLE briefings ADD COLUMN IF NOT EXISTS pack_manifest jsonb NOT NULL DEFAULT '[]'::jsonb;

-- consultations: USE-SIDE L0 (docs/design/steward-owner-visitor.md §2). One row per
-- answering-lane call that a non-silent visitor made — the question, the addresses of what
-- was put in front of the model, the answer and what it cited. Kept verbatim and never
-- re-derived: unlike every other derived table in this file, `rebuild_derived` does not
-- touch it, because nothing can regenerate the fact that somebody asked something.
--
-- It is NOT an authority over knowledge. Canonical derives from knowledge L0 and from
-- nothing else; no gate, contract or projection reads a row here to decide what is true.
-- What a row may feed is a component's own derived ledger, which is rebuilt BY replaying
-- these rows in `created_at` order — hence the index below carrying the id as a tie-break,
-- so a replay's order is total rather than merely mostly-determined.
--
-- `library_ref` is the canonical HEAD sampled when the consultation began — the snapshot id
-- instead for a pinned call, which is the exact form of the same field. Sampled, not pinned:
-- the evidence faces read live state and may advance past it during the call, so the ref
-- says where the reading started rather than one state it all came from. `evidence_handed` and `citations` are arrays
-- of {kind, ref, path} addresses in the one citation grammar (I4) — never text, so a
-- consultation cannot become a second copy of the library. `kind` is one of
-- claim/window/episode/component/document, and `ref` is a claim anchor, a `source_id ¶a-b`
-- span, or a canonical page path (`document`).
CREATE TABLE IF NOT EXISTS consultations (
    user_id         text        NOT NULL,
    consultation_id text        NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    lane            text        NOT NULL,   -- fast|deep|briefing_ask
    visitor_class   text        NOT NULL,   -- audit|business (silent never reaches here)
    question        text        NOT NULL,
    as_of           timestamptz,
    library_ref     text        NOT NULL DEFAULT '',
    evidence_handed jsonb       NOT NULL DEFAULT '[]'::jsonb,
    answer_kind     text,
    answer          text        NOT NULL DEFAULT '',
    citations       jsonb       NOT NULL DEFAULT '[]'::jsonb,
    miss            boolean     NOT NULL DEFAULT false,
    degraded        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    PRIMARY KEY (user_id, consultation_id)
);

CREATE INDEX IF NOT EXISTS consultations_user_created
    ON consultations (user_id, created_at, consultation_id);

-- The reverse lookup: WHICH consultations handed or cited this address. A target is asked
-- for by address (I4) — a claim anchor, a `source_id ¶a-b` span, or a canonical page path —
-- and both jsonb arrays are searched with containment, on `ref` AND on `path`. Both, because
-- a page is reached two ways: opened and read in full (`{kind: document, ref: <path>}`) or
-- through a claim that lives on it (`{kind: claim, ref: c:xxxx, path: <path>}`), and a
-- lookup that only matched `ref` would answer "nothing" for the very page whose access card
-- offered the link. `jsonb_path_ops` is the smaller index and serves exactly `@>`, which is
-- the only operator this predicate uses.
CREATE INDEX IF NOT EXISTS consultations_evidence_handed
    ON consultations USING gin (evidence_handed jsonb_path_ops);

CREATE INDEX IF NOT EXISTS consultations_citations
    ON consultations USING gin (citations jsonb_path_ops);

-- The at-most-once stamp. A `business` consultation is delivered to its consumers by an
-- ordinary queue job (kind `recall_projection`, enqueued in the same transaction as the row
-- above), and that job applies the access statistics and sets this column in ONE
-- transaction. A job that finds it already set is a no-op — so a worker killed mid-job, or
-- a queue self-heal on restart, cannot count the same consultation twice. NULL means "not
-- yet applied", which is also what every row written before delivery existed says.
ALTER TABLE consultations ADD COLUMN IF NOT EXISTS projected_at timestamptz;

-- What the consultation SPENT, as the lane's own usage mapping (input_tokens,
-- output_tokens, total_tokens, cache_read, cache_creation). Tokens and never money: the
-- count is what happened and stays true, while a price is a commercial arrangement that
-- moves without asking this row, so the money is computed when somebody reads out of the
-- rates the deployment declares then. `{}` is what every row written before this column
-- existed says, and it reads back as "nothing reported" rather than as a free call.
ALTER TABLE consultations ADD COLUMN IF NOT EXISTS token_usage jsonb NOT NULL DEFAULT '{}'::jsonb;

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

-- archive_proposals: the Owner's archive/unarchive proposals and their lifecycle
-- (docs/design/archive.md §5). A KEPT RECORD, not a derived layer: it states what was
-- proposed, against which library state, and what the Owner decided — a rebuild replays it
-- and never rewrites it, and nothing recomputes a proposal that was already answered.
--
-- `seeds` is what the Owner named ({documents: [...], sources: [...]}); `items` is the
-- computed closure, one entry per document/source with its role, selection and structured
-- reason, which is what the console renders and what the confirm step executes. Both are
-- jsonb because their shape is the planner's, not the storage layer's.
--
-- `library_ref` is the canonical HEAD the plan was computed against. A confirm whose HEAD
-- has moved is refused as stale: a preview of a library that has since compiled is a
-- preview of something else. `statement_ref` optionally names the `owner-dialogue/v1`
-- source in which the Owner asked for this — provenance in the one addressing scheme.
CREATE TABLE IF NOT EXISTS archive_proposals (
    user_id       text        NOT NULL,
    proposal_id   text        NOT NULL,
    action        text        NOT NULL,   -- archive | unarchive
    seeds         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    items         jsonb       NOT NULL DEFAULT '[]'::jsonb,
    library_ref   text        NOT NULL DEFAULT '',
    status        text        NOT NULL,   -- proposed|stale|confirmed|executed|failed|dropped
    note          text,
    statement_ref text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    confirmed_at  timestamptz,
    executed_at   timestamptz,
    job_id        text,
    detail        text,
    PRIMARY KEY (user_id, proposal_id)
);

-- The listing this table exists for: this Owner's proposals, newest first.
CREATE INDEX IF NOT EXISTS archive_proposals_user_created
    ON archive_proposals (user_id, created_at DESC);

-- kb_snapshots: the knowledge-base snapshot registry (frozen-tenant versioning).
--
-- A snapshot is a FROZEN TENANT, not a filter: L0 (sources/blocks), the L1 lexical index, the
-- L2 vector points and the L3 claim projection are all copied under `tenant_id`, which is
-- never written again. Tenant isolation is a first-class property of every store already, so
-- versioning reuses it instead of inventing a per-layer history mechanism. canonical (L3
-- authority) is the exception and is NOT copied: git already versions it perfectly, so the row
-- pins `canonical_ref` and reads go to the owner's repo at that ref.
--
-- Named `kb_snapshots` rather than `snapshots` on purpose: `snapshot_ref` elsewhere in this
-- schema (compile_jobs, compile_events, canonical_claims, briefings) means a git commit, and
-- reusing the bare word would make every one of those columns ambiguous.
--
-- status is the lifecycle: 'creating' while the copy pipeline runs, 'ready' once every store
-- is complete, 'failed' when a step aborted (the row and its partial tenant are RETAINED so
-- the remains are visible and deletable — a half-copied snapshot must never read as ready).
-- counts is the post-copy scale {sources, blocks, chunks, claims} shown in the picker.
CREATE TABLE IF NOT EXISTS kb_snapshots (
    user_id       text        NOT NULL,
    snapshot_id   text        NOT NULL,
    label         text        NOT NULL,
    tenant_id     text        NOT NULL,
    canonical_ref text        NOT NULL,
    status        text        NOT NULL,   -- creating | ready | failed
    counts        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    detail        text,
    created_at    timestamptz NOT NULL DEFAULT now(),
    ready_at      timestamptz,
    PRIMARY KEY (user_id, snapshot_id)
);

CREATE INDEX IF NOT EXISTS kb_snapshots_user
    ON kb_snapshots (user_id, created_at);

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

-- component_time_blocks: the `time` index component's projection — the first PERSISTED
-- component projection (architecture §6).
--
-- One row per L0 block that has a knowable instant, keyed by the SUBJECT's calendar day.
-- Why not the UTC date: a subject at +08:00 sends messages between 00:00 and 08:00 local
-- that carry the previous UTC date, so "what happened on the 12th" would answer with two
-- wrong halves. `local_day` is the same day ingest already wrote into the block's
-- section_path — one calendar semantics across the whole system (D1).
--
-- `zone` + `zone_source` record WHICH zone this row was normalized under and where that
-- zone came from (profile / provider / deployment default). A later zone change never
-- rewrites rows; the explicit `scripts/ops/rebuild_derived.py` re-derives them, and until
-- it runs the rows honestly say what they were built from (D2). `source_zone` is the
-- source's OWN zone when it carries one (a meeting's `timezone`) — metadata rendered
-- beside the subject's day, never the index key.
--
-- `instant_utc` is NULL for a source with no per-block timestamps (a document library): the
-- source still has an occurrence day, so the row is keyed and range-queryable, it simply has
-- no clock. Derived and rebuildable in full from L0 (I2); user_id first everywhere (I1), and
-- the FK cascade means deleting a source or a user takes its projection with it.
CREATE TABLE IF NOT EXISTS component_time_blocks (
    user_id     text        NOT NULL,
    source_id   text        NOT NULL,
    block_index integer     NOT NULL,
    instant_utc timestamptz,
    local_day   date        NOT NULL,
    zone        text        NOT NULL,
    zone_source text        NOT NULL,
    source_zone text,
    kind        text        NOT NULL,
    PRIMARY KEY (user_id, source_id, block_index),
    FOREIGN KEY (user_id, source_id)
        REFERENCES sources (user_id, source_id) ON DELETE CASCADE
);

-- The range query this table exists for: "every block between two of the owner's calendar
-- days". Without this index a 200-day library answers it by scanning the tenant (D7).
CREATE INDEX IF NOT EXISTS component_time_blocks_day
    ON component_time_blocks (user_id, local_day, source_id, block_index);

-- component_people_terms: the `people` component's projection — HOW the library's turns
-- call someone, accumulated across every source rather than judged inside one.
--
-- One row per (address term → target identity) pair, holding that pair's library-wide
-- support: `answered` + `co_mention` (the two turn-structure signals), how many sources
-- carried it, and the day bounds of those sources. A per-source threshold cannot separate a
-- vocative from any short phrase before a comma — `是的` and `看下` are "answered" by
-- everyone — so the mechanism is CONCENTRATION over this table: a term is reported for a
-- target only when it has enough support, from more than one source, and that target holds
-- most of the term's total support. A term spread thin over twelve targets is reported
-- nowhere, and no word list had to say so.
--
-- `non_vocative` is the second half of that mechanism, and the one concentration cannot
-- supply: the same term counted MID-SENTENCE in the sources that produced the row. Both
-- support signals fire only at the vocative position (a term at the head of a turn, or after
-- an `@`), so `support / (support + non_vocative)` is the share of a term's usage that is
-- address — and a product name or a topic word, which concentrates on whoever habitually
-- answers, fails it while a nickname does not. The count belongs to the TERM and is
-- replicated onto each of its targets by the source that saw it, so read it per row and
-- never sum it across a term's distribution.
--
-- `term` is the comparison key (casefolded; Latin nicknames are one term regardless of
-- spelling). Rows ACCUMULATE: `add_people_terms` adds this source's counts to whatever is
-- there — ONCE per source, which `component_people_indexed` below is what makes true. Still
-- derived and never an authority (I2): `PeopleComponent.rebuild`
-- (scripts/ops/rebuild_derived.py) re-derives the whole table from L0. user_id is first
-- everywhere (I1); every target is a source-boundary identity, so what this indexes still
-- points back at L0 (I4).
CREATE TABLE IF NOT EXISTS component_people_terms (
    user_id         text    NOT NULL,
    term            text    NOT NULL,
    target_identity text    NOT NULL,
    target_name     text    NOT NULL DEFAULT '',
    answered        integer NOT NULL DEFAULT 0,
    co_mention      integer NOT NULL DEFAULT 0,
    non_vocative    integer NOT NULL DEFAULT 0,
    sources         integer NOT NULL DEFAULT 0,
    first_day       date,
    last_day        date,
    reported_since  date,
    PRIMARY KEY (user_id, term, target_identity)
);

-- Additive, for a library whose table predates the mid-sentence count. Zero is the right
-- default and not merely a safe one: a row that has never been re-derived states no
-- mid-sentence usage, so it reports exactly as it did before this column existed, and
-- `rebuild_derived` is what fills it with what L0 actually shows.
ALTER TABLE component_people_terms ADD COLUMN IF NOT EXISTS non_vocative integer NOT NULL DEFAULT 0;

-- `reported_since` is the day a (term → target) pair FIRST crossed the reporting bar — the
-- day the library started asking whether that term is that person's name. It is written once
-- and never moved (`… WHERE reported_since IS NULL`), so a pair whose concentration later
-- shifts keeps the day the question was asked. The forced alias decision runs on it: a term
-- is demanded of a person page only while that page's last commit is EARLIER than this date,
-- so the question is asked once and closed by the page being written. NULL is the honest
-- unknown and means ASK — a row from a library that predates this column has no date, and no
-- page can be shown to have seen a question the table cannot date. `rebuild_derived` is what
-- fills it, by replaying L0 in (occurred_on, source_id) order.
ALTER TABLE component_people_terms ADD COLUMN IF NOT EXISTS reported_since date;

-- "which terms point at these identities" — the source preamble's question, asked once per
-- compile over the identities that source carries.
CREATE INDEX IF NOT EXISTS component_people_terms_target
    ON component_people_terms (user_id, target_identity, term);

-- component_people_indexed: WHICH sources the table above already holds — the manifest that
-- makes an accumulation idempotent.
--
-- The counts add, and the index queue is at-least-once: a worker killed mid-job, a job the
-- queue self-heals on restart, an operator re-importing. While the table was only ever read
-- whole, a source counted twice was merely a number too large, correctable by a rebuild.
-- It stopped being merely that when the archive learned to SUBTRACT: an archived source's
-- contribution is recomputed from L0 and taken back out at the READ, which removes exactly
-- ONE copy — so a source added twice and then archived leaves half of itself behind, and a
-- nickname the Owner retired stays visible in the faces that exist to stop showing it. One
-- row per accumulated source closes that at the write: `add_people_terms` claims the row and
-- applies the counts in ONE transaction, and a second job for the same source claims
-- nothing and adds nothing.
--
-- No foreign key, and keyed exactly like the counts it guards: a term's row belongs to the
-- library rather than to one source, so neither table cascades from `sources` and both are
-- emptied together (`delete_people_terms`, `delete_user`). Derived like the counts, and
-- dropped WITH them — `PeopleComponent.rebuild` clears both before replaying L0, because a
-- rebuild that cleared the counts alone would find every source already claimed and
-- re-derive an empty library.
CREATE TABLE IF NOT EXISTS component_people_indexed (
    user_id    text        NOT NULL,
    source_id  text        NOT NULL,
    indexed_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, source_id)
);

-- One-time backfill, for a library whose counts predate this manifest. The accumulation ran
-- before the table existed, so on the first boot after the upgrade every count in it is held
-- by a manifest that says NOTHING was accumulated — and the next redelivered index job
-- claims a free row and adds its source a second time, which is exactly the doubling the
-- manifest was added to close. So on that first boot every source a counted user owns is
-- recorded as already accumulated, and nothing is counted twice.
--
-- Guarded on the user having counts and NO manifest rows at all: a user whose manifest has
-- begun is a user this already ran for (or one that has only ever run with it), and is left
-- alone. Runs on every start and writes nothing after the first — the second pass finds the
-- rows it wrote and the NOT EXISTS is false.
--
-- Deliberately coarse in the conservative direction: a source that in fact contributed
-- nothing (indexed before the component was enabled, or carrying no address terms) is marked
-- accumulated too, so it stays uncounted until `rebuild_derived`, which re-derives BOTH
-- tables from L0 and settles the pair exactly. A term missing until the next rebuild is a
-- report the library does not yet make; a term counted twice is a number no read can undo.
INSERT INTO component_people_indexed (user_id, source_id)
SELECT s.user_id, s.source_id
  FROM sources s
 WHERE EXISTS (
           SELECT 1 FROM component_people_terms t WHERE t.user_id = s.user_id
       )
   AND NOT EXISTS (
           SELECT 1 FROM component_people_indexed i WHERE i.user_id = s.user_id
       )
ON CONFLICT DO NOTHING;

-- The `people` component once kept a second table here, `component_people_decisions`: the
-- DECLINES, one row per (term → identity) a compile round ruled was not that person's name.
-- Nothing stores a decline any more, here or in canonical. It was a table first, and a row
-- written the moment the tool was called outlived the round that wrote it — a compile that
-- then failed the gate left the decision standing while canonical stayed untouched. It was a
-- person-page frontmatter field next, and that was worse in a quieter way: canonical records
-- what is KNOWN about somebody, and a column of the names that are NOT theirs is a page of
-- distractions. A decline is now the answer to one round and is kept for the length of it
-- (components/people.py); what stops the question returning is `reported_since` above
-- against the day the page was last committed — asked once, closed by writing the page.
--
-- Nothing reads or writes that table any more, and this file does NOT drop it. This schema
-- is applied by every process that boots, on every start: a bootstrap that only ever creates
-- is one an operator can run without reading it, and one `DROP TABLE` in it turns a routine
-- restart into an irreversible deletion of data nobody was asked about. The pre-release
-- table is left where it stands, for the operator to inspect, export and drop when they
-- decide to — `DROP TABLE IF EXISTS component_people_decisions;`, by hand, once.

-- recall_access_hits / recall_access_misses: the FRAMEWORK's access statistics — the
-- built-in consumer of use-side records (docs/design/steward-owner-visitor.md §6, §8).
-- Not a component's: a `business` consultation reaches this ledger whether or not any
-- component is registered, and with every visitor silent there are no consultations at all,
-- so nothing is written. The `attention` component is the faces over these tables, not
-- their owner.
--
-- One row per (target, calendar day): how many times a consultation put that target in
-- front of a model that day. A target is a claim anchor (`c:xxxx`), the canonical document
-- that claim lives on, or a source id — the same three addresses the rest of the system
-- uses (I4), so a hot row joins against canonical and L0 without a translation table.
-- Evidence merely HANDED to the model counts once; evidence the answer went on to CITE
-- counts once more, so the two are distinguishable in aggregate without storing a second
-- column that would have to be kept in step. A DOCUMENT counts at most once per pass,
-- however many of its claims travelled: it is not an evidence item but what the items live
-- on, and counting it per claim would rank pages by their length instead of by their use.
--
-- `last_seen` is the exact instant of the latest consultation that touched the target on
-- that day, so a target's true last access is the MAX over its day rows. Exact last access
-- therefore costs one column on a row that was already being written, instead of a second
-- table restating what these rows already know.
--
-- No score is stored, deliberately. Heat is `Σ hits × 0.5^(age_days / half_life)` computed
-- at READ time (access_stats.py), so the half-life is a knob and not a migration, and the
-- table stays a pure function of the consultations that produced it: a rebuild replays
-- `list_consultations(..., visitor_class='business')` into a replacement set and swaps it
-- in, reproducing these rows byte-for-byte. That is the SECOND legitimate rebuild
-- substrate: use-side records are kept, never derived, and survive `rebuild_derived`
-- unchanged while everything projected from them is re-derived (I2/I7).
--
-- Derived and never an authority: no gate, contract or compile input reads a row here to
-- decide what is true, and NOTHING here is ever written into a canonical file — access
-- metadata is joined at read time, by address, out of the derived layer, because a read
-- must never become a write to the authority. user_id is first everywhere (I1), and no
-- foreign key points at `consultations` — a target may name a document that a later evolve
-- renamed, and a projection whose write path could fail on a stale address would fail the
-- answer it was observing.
CREATE TABLE IF NOT EXISTS recall_access_hits (
    user_id     text        NOT NULL,
    target_kind text        NOT NULL,   -- claim|document|source
    target_ref  text        NOT NULL,
    day         date        NOT NULL,
    hits        integer     NOT NULL DEFAULT 0,
    last_seen   timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, target_kind, target_ref, day)
);

-- The window query this table exists for: "everything attended to in the last N days".
CREATE INDEX IF NOT EXISTS recall_access_hits_day
    ON recall_access_hits (user_id, day, target_kind, target_ref);

-- The other half: the questions the library was asked and could not answer, verbatim, one
-- row per (day, question). Verbatim because a question nobody could answer is the one
-- signal that has no address to be reduced to — what is missing has no `source_id` yet.
-- The question is the primary key, so it is bounded in characters at the write path
-- (access_stats.py) rather than by a length nobody would notice being exceeded.
CREATE TABLE IF NOT EXISTS recall_access_misses (
    user_id  text    NOT NULL,
    day      date    NOT NULL,
    question text    NOT NULL,
    count    integer NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, day, question)
);

-- The two tables above carry the names `component_attention_hits` /
-- `component_attention_misses` had while this ledger was still component-private. Nothing
-- reads or writes those two any more, and — as with `component_people_decisions` above —
-- this file does not drop them: a schema every process applies on every boot may only ever
-- create. They hold a pure projection of `consultations` that one `recall_rebuild` job
-- re-derives in full, so an operator loses nothing by dropping them by hand, once:
-- `DROP TABLE IF EXISTS component_attention_hits, component_attention_misses;`
