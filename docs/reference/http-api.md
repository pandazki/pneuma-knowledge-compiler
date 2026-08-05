# HTTP API

**English** | [简体中文](http-api.zh-CN.md)

Conventions:

- All business routes live under `/v1/users/{user_id}/…` — tenant isolation is in the path, not a header. The only global routes are listed first.
- Writes against a frozen snapshot tenant return **409** (a global handler; frozen means frozen). A `snapshot` parameter that cannot be resolved returns **404**; a snapshot not yet ready returns **409** — a pinned query never silently falls back to live data.
- Validation errors return **422** (strict enums, length caps, unknown fields on contracts).
- Cursors are resumption points, not offsets: `/snapshots` continues along the ancestry of the last returned ref, so commits landing after page one never shift later pages. A malformed or context-mismatched cursor returns **422** — never a silent first page.
- A running API documents itself: Swagger UI at `/docs`, schema at `/openapi.json`.

## Global

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | liveness: `{status, version}` |
| GET | `/v1/users` | user ids that have data (UI user switcher) |
| POST | `/v1/profile/generate` | one sentence → full `UserProfile` draft (LLM); **not persisted** |
| GET | `/v1/intake/archetypes` | intake archetype registry |
| GET | `/v1/live-context/focuses`, `/v1/live-context/kinds` | Live Context vocabularies |

## Profile

| Method | Path | Purpose |
|---|---|---|
| GET | `/…/profile` | persisted profile, else a deterministic mock |
| PUT | `/…/profile` | partial merge (nested objects merge per sub-field); server keeps `timezone_history` append-only, forces `source="user"`; invalid enum values → 422 |

## Sources (L0)

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/sources/import` | import an official [source contract](source-contracts.md); bundle expands into one entry per source |
| POST | `/…/sources/document/preview` | normalize + propose an IntakePlan, zero side effects |
| POST | `/…/sources/document` | ingest a document (accepts `plan_override`) |
| POST | `/…/sources/conversation` | conversation ingest — **deprecated**, prefer contracts |
| GET | `/…/sources` | catalog, keyset-cursor pagination (`limit` 1–500, `cursor`, `query`, `kind`) |
| GET | `/…/sources/activity` | ingest calendar heatmap (`offset_minutes` −840…840) |
| GET | `/…/sources/{source_id}` | detail: meta, structure map, blocks |
| POST | `/…/sources/{source_id}/fetch` | verbatim L0 fetch by `locator` |
| GET | `/…/summary` | workspace counts: sources, jobs, documents, claims, snapshots |

## Recall

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/recall` | body `{query, mode: rag\|fast\|deep, limit, as_of?, snapshot?}` |
| POST | `/…/recall/stream` | deep only; SSE — one `event: step` per finished tool call, then `done` (or `error`). Step-level streaming, not token streaming |

`rag` returns hit lists (`source_id`, block span, text, paths, score). `fast`/`deep` return an answer plus its evidence: `used_claims`, `used_windows`, `trail` (deep), `citation_handles` (`sNN` → real source id), `documents_read`, `snapshot`, `token_usage`.

## Compile, jobs, history

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/compile` | enqueue one compile job per undigested source (idempotent) |
| GET | `/…/jobs` | queue pagination (`status`, `kind` filters) |
| GET | `/…/history` | unified timeline of patches, jobs and snapshots, with counts |
| GET | `/…/history/activity` | timeline calendar |

## Snapshots — two distinct concepts

| Method | Path | Purpose |
|---|---|---|
| GET | `/…/snapshots` | **canonical version history** — read-only browsing, free |
| GET | `/…/kb-snapshots` | **frozen tenant copies** (status `creating`/`ready`/`failed`, counts) |
| POST | `/…/kb-snapshots` | freeze the whole library → **202**, copies in background; `{label}` required |
| DELETE | `/…/kb-snapshots/{id}` | remove the frozen copy from all stores; canonical history untouched |
| GET | `/…/dataset` | canonical + audit assembled for the UI's views (`at`, `audit`) |

`/dataset` exists because the Library/Graph views legitimately need every document of one snapshot; the canonical adapter serves that with a single `git archive` read of the whole tree.

## Briefings

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/briefings` | build a stable evidence pack on a pinned snapshot: `{query?, source_ids[], budget_chars, snapshot?}` |
| GET | `/…/briefings` | list |
| POST | `/…/briefings/{id}/ask` | ask against the stored pack: `{question}` → answer + citations |
| DELETE | `/…/briefings/{id}` | delete |

## Evolve and skill

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/evolve` | trigger a round; a pending draft or in-flight job → **409** (single-flight) |
| GET | `/…/evolve` | task list (lazy TTL sweep first) |
| GET | `/…/evolve/{task_id}` | review payload: proposal, rationale, `changed_files[{path, old_body, new_body}]`, `dropped[]` |
| POST | `/…/evolve/{task_id}/adopt` | enqueue mechanical adoption → **202**; non-draft → 409 |
| POST | `/…/evolve/{task_id}/drop` | discard the draft immediately |
| GET | `/…/skill` | the effective composed contract: version, `content_hash`, `path_templates`, packs, claim labels |

## Live Context

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/live-context/stream` | one-shot SSE over a transcript window: one `event: suggestion` per surviving card, then `done` with gate stats |
| WS | `/…/live-context/ws` | long-lived listener. Client sends `config` / `turn` / `flush` / `want_more` / `ping`; server sends `ready` / `suggestion` / `suggestion_detail` / `stats` / `error` (never fatal) / `ping` (~30 s keepalive). The full protocol is documented in the module docstring of [`api/routes/live_context.py`](../../packages/pneuma-knowledge-service/src/pneuma_knowledge_service/api/routes/live_context.py) |
