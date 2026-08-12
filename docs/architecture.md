# Architecture

**English** | [简体中文](architecture.zh-CN.md)

The whole system on one page: what it commits to, how data flows, and what is mechanically enforced. Everything else under `docs/` elaborates a section of this page.

## 1. Design stance

Three commitments define the system; each is enforced by a mechanism, not by convention.

**Domain-oriented modeling.** The framework holds no domain opinion. `load_skill_base` raises unless the deployment has registered a compile contract, and the only required setting (`PNEUMA_KNOWLEDGE_USER_SCHEMA_BASE_VERSION`) exists to force that declaration. What gets recorded and in what structure lives in a contract you write — a markdown file plus path templates — while the framework supplies only domain-agnostic machinery: normalization, indexing, retrieval, verification.

**An evolvable model.** Any model fixed up front degrades as data accumulates, distributions shift, and the business pivots. Evolution is therefore infrastructure, not an afterthought: the compiler records events as it works; the framework drafts schema changes from that history on a branch; a human reviews the diff; a mechanical, LLM-free reconciliation merges what was adopted (§8).

**Provenance enforced at the write layer.** The compile model has no whole-file write tool. It can only edit or append individual claims, every claim must carry citations that resolve to exact passages of source material, and a gate verifies this mechanically before anything is committed (§5). Fabrication is not discouraged; it is structurally impossible.

One boundary: this is not an agent memory system. An agent's memory should record that it *has* a knowledge base — how it is built, what it roughly contains, how to query and maintain it — not the knowledge base itself.

And one project-wide discipline behind all three: **mechanism over persuasion**. A constraint that matters is implemented as write-time rejection, system-assigned identity, or deterministic normalization — never as prompt copy asking the model to please remember. If you find yourself writing that prompt, the design is wrong.

## 2. The shape of the system

```
 raw material ──▶ SourceAdapter ──▶ NormalizedSource ──▶ IntakePlan
                                                            │
              ┌─────────────────────────────────────────────┤
              ▼                                             ▼
        index jobs (L1/L2)                          compile jobs (L3)
              │                                             │
              ▼                                             ▼
   Meilisearch / Qdrant                     canonical library (versioned)
              │                                             │
              └────────────────┬────────────────────────────┘
                               ▼
            retrieval lanes: rag · fast · deep · briefing · live context
```

Four packages, one-way dependencies:

- `pneuma-knowledge-core` — pure domain logic and async `Protocol` ports. Depends on pydantic, langchain-core, langchain, chonkie; **no middleware clients**. LLMs and embeddings enter as langchain-core types (`BaseChatModel`, duck-typed `Embeddings`).
- `pneuma-knowledge-service` — the port implementations: FastAPI app, adapters (Postgres, Qdrant, Meilisearch, S3-compatible media, Git-via-subprocess), the background worker, settings.
- `pneuma-knowledge-strategies` — reference compile contracts as a data package. The framework never imports it.
- `apps/web` — a SPA speaking only the HTTP API.

Direction is strict: `service → core`, `web → service API`. Core never imports a middleware client; service never reimplements domain logic.

## 3. Four access levels

Every source is kept verbatim and stays reachable at four levels over the same block sequence. These are parallel views, not fallbacks.

| Level | What | Store | When |
|---|---|---|---|
| L0 | verbatim blocks + structure map + block-aligned original media, fetched by locator | Postgres + private S3-compatible object storage | unconditional |
| L1 | lexical full-text over blocks | Meilisearch (index per user) | unconditional |
| L2 | semantic chunks | Qdrant (one collection, tenant filter injected in the adapter) | per IntakePlan |
| L3 | canonical knowledge compiled under the contract | canonical library (versioned; + derived projections) | per IntakePlan |

An `IntakePlan` is two knobs — `canonical_treatment` (full / distill / card / none) × `semantic_indexing` (full / summary / none) — proposed mechanically from the shape of the source, overridable by the user, and audited. The user-facing intake archetypes name processing intent, not genre — genres are an open set no list can close; an archetype is a named preset of the two knobs. Ingest itself is cheap and synchronous: an import writes L0 and enqueues `index` and `compile` jobs; everything expensive happens in the worker.

## 4. Authoritative vs derived

Only two things are authoritative: the L0 sources, and the canonical library. The canonical library is a **versioned, append-only history**: every compile appends a version, any past state can be snapshotted or rolled back, evolution is reviewed on its own branch, and every version is stamped with the hash of the contract that produced it. Everything else — L1/L2 indexes, L3 projections, glances — is derived and rebuildable from those two.

(The shipped implementation: L0 text, structure and media manifests live in Postgres, while immutable media bytes live in private S3-compatible storage (RustFS in the local stack) behind the `MediaStore` port. The canonical library is one Git repository per user, whose commit/tag/revert/branch map one-to-one onto the semantics above. These are adapters, not architectural commitments.)

Two consequences worth internalizing:

- Rebuilds are byte-deterministic even where an LLM was involved. Semantic chunking (the default `semantic` strategy; its boundary philosophy is inspired by [nemori](https://github.com/nemori-ai/nemori)) uses one structured LLM response to return each topic/episode's search-friendly title, factual third-person description, and block coordinates. The description preserves concrete participants, time, place, events, decisions, emotions, reasons, plans and outcomes that the covered blocks support; known source occurrence dates anchor relative-time normalization, and absent dates are never guessed. This generated representation is derived retrieval text, not source: chunk text remains a verbatim slice addressed exactly like mechanical chunks. The v3 manifest records coordinates plus title/description and replays them on rebuild. A boundary-only older manifest is upgraded once by describing its **fixed** spans; a mechanical equality check refuses any attempted boundary change. An episode longer than `CHUNK_SIZE` is sentence-sub-split before embedding. Scripted/keyless models still fall back to mechanical sentence chunking. L2 stores two independently ranked representations: raw vectors embed source context plus labelled caption/OCR and the verbatim chunk, while one episode vector embeds source context plus the title/description. Every point resolves to its corresponding verbatim L0 span; generated prose is never stored or shown as evidence. Retrieval fuses lexical, raw-vector and episode-vector rankings with ordinary RRF, then suppresses lower-ranked overlapping source spans without widening the winner or adding duplicate score. Better search meaning therefore never dilutes the raw vector or creates a second authority or citation space.

  Segments may also *overlap* (`SEMANTIC_OVERLAP`, factory default `smart`): the model returns closed block intervals, so a hinge — the sentence that closes one topic while opening the next — is indexed as part of both neighbouring segments, judged per boundary rather than as a fixed stride. Whether that is allowed to degenerate is not left to the prompt: five write-time gates (real ordered endpoints, strictly increasing starts, gapless cover, at most three shared blocks, no more segments than blocks) reject the whole output, and the window falls back to the zero-overlap partition. The duplication a hinge causes is purely derived — both chunks address the same source blocks (I4), and retrieval suppresses the lower-ranked overlapping result. `off` retains the zero-overlap geometry, but adding the episode representation intentionally creates a new prompt baseline; earlier boundary-only measurements are not presented as same-harness results for this version.
- Upgrades never rewrite the canonical layer. A new projection strategy, a new index, a new render — all rebuild derived artifacts; the canonical history stands.
- The routine commit path syncs projections incrementally: the fresh snapshot is diffed against the last recorded projection manifest and only the delta lands in the indexes (only added or changed claims are re-embedded). The full rebuild (`scripts/ops/rebuild_derived.py`) is the explicit repair and migration path, not the daily one — and either way, the increment is a cost optimization, never a new source of truth.

## 5. Canonical write mechanics

The unit of canonical knowledge is a **claim**: a text block carrying an **anchor** (an HTML comment `<!-- c:xxxx -->` embedded in the markdown) and one or more **citations** written `[cite: <source-id> ¶a-b]`, where `¶a-b` is a block span in the cited source. Anchors are content-addressed and system-assigned — the model never mints one — and once assigned they are immutable.

An image does not invent a second citation language. It is attached to the message's ordinary block, so the same `source_id + ¶ span` resolves the verbatim text, original image bytes, digest, MIME type, and any explicitly labelled caption/OCR representation with its producer. The compile path can send caption/OCR only or real image content blocks according to the active compile model; native mode re-reads and verifies the stored bytes before the model call. A caption remains derived evidence and never impersonates direct image inspection.

The compile model works through claim-level tools only (`edit_claim`, `append_block`, `create_document`, plus read tools), against an in-memory patch draft. Before a draft becomes a commit it must pass the **gate**: a mechanical check of anchor continuity and uniqueness, citation resolvability and shape, provenance on every new claim, link-target existence, frontmatter completeness, path ownership under the contract's templates, and the immutability of frozen archive volumes. Citation checks apply to what this round introduces — citations carried verbatim from earlier commits are grandfathered (they were verified when first written), so a forward compile is never rejected over a source it was not given; anchor uniqueness, by contrast, is checked repository-wide with no grandfathering. Violations trigger one repair round; if violations remain, the compile aborts and the canonical layer is untouched.

Documents that grow past a size threshold are rolled over: older claims move byte-for-byte into frozen archive volumes (`<doc>/aNN.md`), the active document keeps a recent tail plus a machine-managed overview, and a dedicated gate asserts byte conservation and exact anchor survival across the move.

An optional **coverage challenge** (off by default) audits each compile right after it lands: questions are generated blind — from the material and the contract, never from the compiled result — probed against the recorded claims, and judged with the material as ground truth. Confirmed gaps feed one compensation compile whose writes pass the same gate as any other; the audit points, the gate enforces.

## 6. The compile contract (skill)

A contract is registered as a `SkillVersion`: skill id, version, instructions (the judgement — what deserves to be recorded, at what granularity, under what wording), path templates (the directory skeleton of the library, and the sole basis of write permission), and contract rules. The whole thing is hashed; the hash is stamped into every canonical commit, so any library state is attributable to the exact contract text that produced it.

Per-user extension happens through **schema packs** — additive fragments composed onto the base contract deterministically (a pack can add families, never remove them). Every model-visible string in the framework lives in a prompt catalog and can be overridden at startup; the override set is hashed and stamped alongside the skill hash, giving each deployment a two-axis identity: *which contract, which wording*.

The rendered system message is byte-stable: no timestamps, no task content — those travel in the human message. This is what makes provider prompt caching effective and compile behaviour attributable.

How to actually write a contract is a craft of its own: see [guides/compile-contract.md](guides/compile-contract.md).

## 7. Retrieval

Four lanes over the same library, increasing in cost:

- **rag** — L1 + L2 in parallel, fused by reciprocal rank; returns hits, no LLM.
- **fast** — one LLM call over assembled evidence: a glance of the library, L3 claims, and L1/L2 body windows.
- **deep** — a bounded agentic loop seeded with fast's evidence, with search/fetch/read tools and a forced conclusion when the budget runs out; returns its trail.
- **briefing** — a byte-stable evidence pack built once on a pinned snapshot, then asked many times.

L1 lexical hits, L2 raw/caption vectors and L2 episode-description vectors are three
independent rankings. Each path supplies twice the final cap so post-retrieval dedup can
backfill instead of shrinking recall. Ordinary equal-path RRF rewards agreement, while exact
lexical-only identifiers and dates can still outrank a broad episode-only match. The fused pool is then
deduplicated by rank-ordered overlap suppression on `source_id + block span`. An overlapping
raw/caption or lexical span always owns the citable result over an episode-only span; the
episode may raise its rank, but cannot replace its more precise evidence. Multiple
representations therefore improve rank without consuming duplicate answer-window slots or
chaining overlapping episodes into a mega-window. No retrieval path receives a fixed quota.
During context assembly, semantic raw/episode spans remain the natural units recorded at
ingest: they are not expanded a second time, and only genuinely overlapping spans coalesce by
default. Forward expansion remains available for a bare lexical-only block hit; bridging
disjoint nearby spans requires an explicit measured override.

Answering recall never includes original media merely because its model can consume it. The
query tool owns that cost/attention decision through the enum-list argument
`include_original_modalities` (empty by default; currently `image`). When `image` is selected,
fast and deep's seed evidence replay images attached to the selected L1/L2 body windows:
immutable L0 bytes are re-read and verified before becoming real image content blocks. When it
is omitted, fast keeps labelled caption/OCR representations in text form and no original media
bytes are read. Images outside the selected windows never enter the call, duplicate digests are
collapsed, and the volatile question remains the final human-message content block.

The fast lane's claim face carries two opt-in stages around its dual-path retrieval (both off by default; the off path is byte-identical). **Planning** (`RECALL_PLAN_QUERIES`): one small call derives extra keyword queries from a multi-aspect question, every query retrieves at full strength, and one RRF fusion pools the union — result-driven multi-round retrieval stays deep's job. **Reranking** (`RECALL_RERANK_MODEL`): a `Reranker` port (core) scores the pooled candidates against the original question and the best `RECALL_CLAIM_CAP` enter the prompt — rank-then-drop, with RRF kept only for dedup, backfill, and the failure fallback. Two providers ship: `llm` (default — the recall-role model pinned to reasoning effort `none`; input-heavy, output-tiny, no extra service) and an OpenRouter `/rerank` endpoint model name (dedicated cross-encoder, billed per search unit). The knob defaults off for a measured reason: on LoCoMo-refined neither provider beat plain capped retrieval — the answering model's own attention over a well-sized claim budget (release default 64, measured sweet band 40–80) is already the effective reranker. Candidate pools are also deduplicated by text containment: an equal or contained claim statement is dropped for the more complete one, which keeps re-filed facts from burning budget slots.

Plus **live context**: given an ongoing conversation window, propose zero or more grounded suggestion cards, filtered through mechanical gates — silence is the norm, not a failure.

Everything resolves through one addressing scheme — `source_id + block span` — so a lexical hit, a semantic chunk, a claim citation, a verbatim fetch, and block-aligned media all point into the same block sequence. Answers cite via query-local handles (`s01`, `s02`…) that never leak across one evaluation. Retrieval can be pinned to a snapshot — either a past version (read-only browse) or a frozen copy of the whole tenant — and a pinned query never silently falls back to live data.

## 8. Evolution

The evolution loop, end to end:

1. Compile events accumulate (what was added, revised, where).
2. A trigger fires — thresholds of new documents and claims since the last look, or a manual request.
3. The framework drafts a proposal: revised families, path templates, page restructuring — and rebuilds the library accordingly on an `evolve/<task-id>` branch.
4. A human reviews the diff: rationale, changed files, and any anchors that would be dropped, surfaced explicitly.
5. Adopt merges via a three-way, LLM-free reconciliation and rebuilds derived layers; drop deletes the branch. Drafts expire on a TTL.

Claims are never rewritten by evolution; what evolves is the model — the contract, the families, the shape of the library.

## 9. Invariants

Five guarantees that hold everywhere in the code — safe to build on, and they take precedence over any local trade-off when changing the framework.

1. **User isolation everywhere.** `user_id` is the first parameter of every port method; each user gets their own canonical library and lexical indexes; the vector store's tenant filter is injected inside the adapter with no unfiltered public path.
2. **Canonical and derived are distinct types.** Strategy or render upgrades rebuild derived artifacts only.
3. **L0/L1 reachability is unconditional**, regardless of what the IntakePlan decides about L2/L3.
4. **One addressing scheme.** All knowledge links back via `source_id + block span`; one citation syntax with one shared parser. Block-aligned media resolves through that address rather than through an uncited side channel.
5. **The system message is byte-stable.** Volatile content travels in the human message.

## 10. Process topology

Four middleware containers (Postgres, Qdrant, Meilisearch, RustFS) plus two stateless processes:

- **API** (FastAPI / uvicorn) — ingest, retrieval, review surfaces; also serves SSE streams and the live-context WebSocket.
- **Worker** — drains the job queue per user, strictly serially (`FOR UPDATE SKIP LOCKED`; one in-flight job per user doubles as the single-writer guarantee for the canonical store). Six job kinds: `compile`, `index`, `challenge`, `evolve`, `evolve_adopt`, `groom`. On restart it re-queues orphaned jobs; any exception completes the job as failed rather than leaving it claimed.

The Git binary is a runtime requirement (the canonical adapter shells out). Async discipline is full-stack: ports and everything touching them are `async`; pure helpers stay sync; unavoidably blocking work (git subprocess, chunking) is wrapped in threads inside adapters.

Model wiring is role-based — compile, recall, deep, skill, evolve, challenge, live-context — each independently configurable, with a single one-hop fallback and a shared default. A `scripted:` model spec replays recorded responses for keyless, deterministic runs; embeddings accept a deterministic `fake:<dim>` for the same purpose. Tracing (Langfuse) is a no-op unless fully configured.

## 11. The engine directory

Everything that IS a deployment's engine — strategy, the compile contract, prompt overlays, the owner profile — can live in one directory, versioned as its own git repository, separate from data, secrets and machinery. `PNEUMA_KNOWLEDGE_ENGINE_DIR` points at it; unset (the default) means the deployment has none and every strategy key resolves exactly as it did before the concept existed.

```
engine/                    # its own git repo; one commit per apply
  engine.yaml              # model roles + compile image delivery mode
  intake/intake.yaml       # chunk_strategy, semantic_overlap
  compile/contract.md      # the constitution — a DOCUMENT, never decomposed into knobs
  compile/challenge.yaml   # coverage-challenge knobs
  evolve/evolve.yaml       # evolve trigger knobs
  recall/recall.yaml       # answer style and retrieval budgets
  persona/profile.yaml     # the owner profile
  prompts/overlays.yaml    # prompt language + catalog key → replacement clause
                           # (the prompt extension point)
```

Three properties make it a mechanism rather than a convention:

- **Precedence is fixed at three levels: process env > engine file > framework default.** Explicit environment wins so a benchmark harness can override per run without dirtying the versioned unit; the engine file is the durable truth a person edits. It is enforced at settings assembly — the engine file's values are handed to `Settings` only for keys the environment leaves unstated.
- **Secrets and infrastructure never enter it.** Connection targets, ports and API keys stay in the deployment's environment; every write refuses a dotfile path and API-key-shaped content.
- **The picture is derived, never drawn.** A machine-readable engine schema (stages, knobs with their defaults and env names, apply semantics, pipeline edges) is generated from `Settings` metadata plus a hand-authored stage map, and a test pins the two in sync — adding a strategy knob without covering it fails the suite.

Each edit states its blast radius, which is invariant I2 made visible: `hot` (the next process to read the files picks it up), `restart` (API/worker rewiring), `future_compiles` (governs future compiles only; canonical is never rewritten), `derived_rebuild` (takes full effect for existing content after `rebuild_derived`). The contract stays a document with version history and an editor, never a form of toggles: knowledge modelling is judgement, and pretending it is checkbox configuration would be the one lie this framework cannot afford. Full design: [docs/design/engine-console.md](design/engine-console.md).
