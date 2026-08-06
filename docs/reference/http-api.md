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

## Engine Console

Deployment-scoped, not per-user: the engine directory is the installation's own configuration rather than a tenant's knowledge, and there is no `user_id` because nothing reachable here belongs to a user (invariant I1 untouched). Every route returns **404** unless `PNEUMA_KNOWLEDGE_ENGINE_DIR` is set — a deployment that did not adopt the concept gains no surface. Design: [design/engine-console.md](../design/engine-console.md).

| Method | Path | Purpose |
|---|---|---|
| GET | `/v1/engine/schema` | the derived engine schema: stages, knobs (env name, default, enum, apply semantics, bilingual labels), pipeline `edges`, and `access_routes` |
| GET | `/v1/engine/state` | `files` (engine-relative path → content), `skipped` (path → why it is not in `files`: oversized, not UTF-8, unreadable — an explicit gap, since a silent one reads as an empty file), `values` and `resolution` (`<stage>.<key>` → value / `env`\|`engine`\|`default`), `version` (`head`, `dirty`). Re-read from disk per request; documents appear in `files` only |
| GET | `/v1/engine/file?path=…` | one engine file verbatim, no resolution involved — the repair path when `/state` cannot resolve: `{path, content}`. Addressed exactly as an apply addresses it (one canonical spelling, inside the directory, no dotfiles); **404** when nothing is there, **400** for a path the directory refuses or a file that cannot be handed back as text |
| GET | `/v1/engine/history?limit=50` | commits, newest first: `sha`, `label`, `at`, `files` |
| GET | `/v1/engine/history/{sha}/files` | one version's engine files as that commit had them: `{sha, files: {path: content}}` via `git show` — HEAD and the working tree untouched. This is what makes undo an ordinary apply: load a version's content into the draft, review it, apply it with a label; there is no revert primitive and no history rewrite. `sha` may be abbreviated and is echoed back resolved. The listing is filtered by the same addressing rules a read of the directory applies (no dotfiles, nothing oversized, nothing that is not UTF-8 text), so a version never offers content the apply path would refuse. **404** for a sha this repository does not have, including a revision expression git itself would evaluate (`HEAD~1`, `main@{yesterday}`) — the route resolves a commit id, it does not evaluate git's grammar |
| GET | `/v1/engine/prompts` | the Prompt Studio's read side: `{surfaces: [{id, group, kind: "assembled"\|"fragments", title{en,zh}, summary{en,zh}, note{en,zh}\|null, segments: [{key, label{en,zh}, context{en,zh}\|null, framework_text, override_text\|null, placeholders, shared_with}], assembled_framework, assembled_effective}]}`. A **surface** is one model-visible prompt composed from ordered catalog segments — the override unit stays the catalog key, the understanding unit becomes the prompt it lands in. `kind: "assembled"` surfaces carry the bytes a composition function really produces (byte-pinned in core); `kind: "fragments"` surfaces are families of clauses the model receives ONE AT A TIME (conditional preambles, a tool face, a gate's rejection lines) — both assembled strings are `""`, because concatenating alternatives would show prose no model ever received, and each clause carries `context`, a bilingual sentence naming when it is used (`null` only where a clause's position in an assembly already says it). Resolved against the engine directory's overlay file on disk (not the running process's registered overrides, and not the client's unsaved draft, which flows through the ordinary apply). Runtime placeholders stay literal in the assembled text and are reported per segment, and `note` is what stops a reader taking that for the finished message: a bilingual banner naming what the framework substitutes per call (the contract in force, the owner profile), which clause a knob picks instead, and what arrives separately in the human turn. `null` means the bytes really are what the model receives — 13 of the 14 assemblies carry a note, and a fragment family never does, having no assembled text to caveat. **400** for an overlay file that does not parse; an unrelated broken stage file does not cost this route its answer |
| POST | `/v1/engine/prompts/rewrite` | `{key, intent, locale: "zh"\|"en"}` → `{draft, notes}` — one replacement clause drafted on the deployment's recall-role model, given the clause's position in its surface, its neighbours, the framework original **as the engine's own language pack states it**, the override in force and the placeholder contract it must preserve. The pack's language — not `locale`, which is only who reads `notes` — decides what the clause is written in, and the brief names the terms that must survive it, so a Chinese pack does not degrade into English jargon by way of the assistant. **Never writes**: the draft goes back through the ordinary draft → review → labelled apply. **503** when the deployment runs keyless (browsing and editing stay served), **400** for a key the prompt catalog does not have, **502** when the model returns no usable clause |
| POST | `/v1/engine/apply` | `{changes: [{path, content}], label, expected_head?}` → `{sha, effects: [{key, apply}]}`. Writes, then one commit of **exactly those paths** under the engine repository's own identity — anything else left dirty in the directory stays dirty and out of the version. One apply at a time per deployment. **409** when `expected_head` no longer matches (the read is stale, not the request wrong; `null`/absent = no precondition). **400** for a path that leaves or hides (traversal, absolute, dotfile, symlink escape) or is not its file's canonical spelling (`./x`, `x//y`), key-shaped content, content past the 512 KiB engine-file cap, an undeclared stage key, an out-of-enum or wrongly typed value (an `int` knob means a whole number), malformed YAML, an overlay key the prompt catalog does not have, an overlay that drops or invents a named placeholder its original does not declare, or a resulting directory that would not resolve as settings — validated in full before the first byte is written. A change set that alters nothing mints no commit and returns the current head with no effects |
