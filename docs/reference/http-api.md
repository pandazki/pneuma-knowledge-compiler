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
| GET | `/…/sources/{source_id}` | detail: meta, structure map, blocks, and block-aligned image manifests |
| GET | `/…/sources/{source_id}/blocks/{block_index}/images/{image_id}` | tenant-scoped private image bytes; validates source/block/image membership and the stored digest |
| POST | `/…/sources/{source_id}/fetch` | verbatim L0 fetch by `locator` |
| GET | `/…/summary` | workspace counts: sources, jobs, jobs_failed, documents, claims, snapshots |

## Recall

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/recall` | body `{query, mode: rag\|fast\|deep, limit, as_of?, snapshot?, answer_style?, evidence_strategy?: ranked\|select\|all, answer_format?: text\|structured, include_original_modalities?: ("image")[], visitor_class?: silent\|audit\|business}` |
| POST | `/…/recall/stream` | any mode; SSE — `stage` while the lane runs (plus `token`, and deep's `step`, in the answering lanes), then `done` (or `error`) |
| GET | `/…/access-stats` | `?kind=claim\|document\|source&ref=…` → `{kind, ref, last_accessed_at, hits_7d, hits_30d, heat}` — what this library's readers have done with one target, joined at read time out of the derived layer. Never canonical: nothing here is written into a page. A target nobody has read answers with zeros and `last_accessed_at: null`, because "never read" is an answer |
| GET | `/…/access-stats/top` | `?days=1–365&limit=1–100` → `{window_days, since, until, half_life_days, documents[], misses[]}` — the ledger's face for a dashboard: the hottest canonical pages and the most-asked questions the library answered with nothing |

**`visitor_class`** says who is asking, as far as the RECORD is concerned — it changes
nothing about the answer. `silent` is the default and leaves no trace at all: no row, no
log line, no extra call, so every caller written before this field existed is already a
silent visitor and behaves byte-for-byte as it did. `audit` writes one **consultation
record** — the question, the `as_of` the lane resolved, which library answered (the pinned
snapshot's id, else the canonical HEAD commit), the addresses of everything the lane put in
front of the model, the answer with the citations it kept, and whether it was a miss — and
stops there, so a consultation is reconstructible without steering anything. `business`
writes the record and, in the same transaction, ENQUEUES one `recall_projection` job; the
worker draining it applies the framework's access statistics and then hands the record to any
enabled index component. Nothing is consumed in the request path, and nothing in the request
path waits: the record is emitted as a detached task, so neither the response nor a stream's
`done` frame is held for the write, and a projection lags its consultation by the queue's
drain. The emit is best-effort — a process death in that window loses the record — and it can
never fail, delay or change the answer it is about. `mode: "rag"` records under no class —
it reaches no model, so there is nothing handed to one for a record to be about. The same
field, same values, same default, is on `POST /…/briefings/{id}/ask` and its stream.

`rag` returns `{mode, hits, stages}` — the fused hit list (`source_id`, block span, text, paths, score) and what finding it cost. `fast`/`deep` return both a citation-free semantic `answer_text` and the backward-compatible cited `answer`, plus their evidence: `used_claims`, `used_episode_summaries` (fast), `used_component_evidence` (fast), `stages`, `used_windows`, `trail` (deep), `citation_handles` (`sNN` → real source id), `documents_read`, `snapshot`, `token_usage` and `cost` (what those tokens cost at this deployment's declared rates; `null` when it declared none — see [configuration](configuration.md)). Every episode-summary item carries source title, occurrence time, section and exact block span, plus constant `derived: true` / `verbatim: false` labels so clients cannot mistake generated L2 compression for source text. Both answering lanes echo `mode` and the `as_of` they resolved, `glance_chars` — the size of the knowledge-base glance carried in the prompt, 0 when canonical was empty or unreadable — and `documents_read`, the documents read whole rather than as a retrieved fragment (fast's glance selection, deep's `read_document` walk). `glance_degraded` is fast-only and names a glance selection that failed (`timeout`/`error`); a pass that ran and chose nothing stays null, like every other selection in the lane.

Fast callers may override context composition and the answer wire independently.
`evidence_strategy: "select"` spends one serial structured recall-model call to choose a
bounded mix across broad claim, episode-summary and raw-window candidates (plus known
canonical paths); invalid coordinates are discarded and failure falls back to ranked heads.
`answer_format: "structured"` separates answer kind, answer text and citations, and admits
only exact cited spans present in evidence. The response echoes candidate counts and the
model-selected claim/episode/window counts before safety anchors and provenance rollback,
plus `evidence_strategy`,
`evidence_selection_degraded`, `answer_format`, `answer_kind`, and
`answer_format_degraded`. `evidence_strategy: "all"` makes no selection call: the same
candidate pool is handed to one answer call whole, so the model-selected counts stay 0, the
`select` stage comes back `skipped`, and the only thing that can cut the context is the
assembled-context ceiling — which reports itself as
`evidence_selection_degraded: "all:truncated"`. Under `answer_format: "structured"` that
strategy also returns `deliberation`: the answering call's own bounded evidence review,
written before its answer. It is model output about the evidence, never evidence and never a
citation, and it is null on every other path. Both request fields are fast-only; rag/deep
reject non-null values.

Component paths are a fourth evidence face, not a fifth ranked list. When enabled index
components offer fast paths ([configuration](configuration.md#index-components)), the fast
lane spends one routing tool-call turn: the paths are bound as tools, the recall model emits
zero or more calls with structured arguments in a single turn (no loop), and the chosen paths
run concurrently beside the built-in retrieval, which never waits for them. `route_offered`
lists the path names that turn was shown, `route_chosen` the honoured calls as
`name({json args})`, and `route_degraded` is `timeout` or `error` when the routing call itself
failed — choosing nothing is the normal outcome for a question no path serves, not a
degradation. With no path offered there is no routing call at all: `route_offered` is empty,
`route_degraded` null, and the lane's messages are byte-identical to the lane without the
seam. All of these are response fields of the fast lane; deep leaves them at their defaults
rather than rejecting them.

`used_component_evidence` is the audit trail of what was looked up — one entry per honoured
call, plus one per call that could not be honoured, so what the model tried survives. Each
entry carries `path`, the `args` the router chose, the `claims` and `windows` the lookup
contributed, and `degraded`: `timeout`, `error`, `invalid_args` (an unknown tool name, or
arguments the path's schema rejected) or null. A path returns everything it knows and the
framework decides what is shown, so the entry also states what it did not show: `dropped`
counts the candidates the path's cap and the character budget left out, `dropped_summary`
describes the same omission as `(section-or-day, count)` pairs in relevance order, and
`already_shown` counts the results the ranked faces already carry — hidden here rather than
repeated, which is why a ranked claim may come back with a `via:<path>` entry in
`used_claims[].labels` (a path may also attach its own mechanical labels, e.g. `current`,
`superseded`). Path results never enter the RRF. Every one of them is an ordinary claim
anchor or `source_id + block span` (I4), so citation aliasing, the structured answer's
admission check and the wire echo apply to them unchanged.

Under `evidence_strategy: "select"` the component face joins the candidate pool instead of
bypassing it, and `model_selected_component_items` counts how many of its items the selector
took (0 on the ranked path, where the face is rendered under its own header rather than
selected from; the pool count itself is not echoed). What the selector took is then rendered
as what it is — a claim among the claim notes, a window among the raw excerpts — carrying its
`via:<path>` label, so the face is not shown a second time under its own header.
`used_component_evidence` comes back either way: the record of what was looked up does not
depend on how the context was composed.

`stages` is the answer's per-stage wall-clock, in milliseconds, as a flat list — in the
answering lane's own vocabulary. In **fast**, the vocabulary is fixed and the list arrives in
a fixed order — `plan`, `retrieve` (followed by its children), `route`, `rerank`, `select`,
`assemble`, `answer`, `total`. Every stage is present every time: one that did not run comes
back with `status: "skipped"` and `ms: 0`, so a client can lay out a stable strip and tell
"did not happen" from "was free". `status` is `ran`, `skipped` or `degraded`, and a degraded
stage carries the lane's own reason in `detail` (`timeout`, `error`, `invalid_args`) — the
same reason the matching `*_degraded` field states. The retrieval gather's arms are children
under a dotted name (`retrieve.claims`, `retrieve.windows`, `retrieve.glance`, and one
`retrieve.path:<name>` per routed component path); each reports its OWN duration while
`retrieve` reports the gather's wall-clock, so the children sum to more than their parent and
`route` — a model call inside that same gather — overlaps it. That is the point: only a
per-arm clock says which lane was the slow one. The single arithmetic guarantee is
`total >= every other stage`.

In **deep** there is no fixed vocabulary to send: how many turns the agentic loop took and
which tools it reached for is precisely what the timing reports. The list is the run's own
sequence — `turn:1`, `tool:search_claims`, `tool:read_document`, `turn:2`, …, then `total` —
with `finalize` appearing when the tool budget forced a closing tool-less call (`status:
"degraded"`, `detail: "budget"`). A tool call that failed is `degraded` carrying its reason,
whether it raised or answered with a stated failure. Nothing is ever `skipped` here, because
there is no list of stages that could have run. `total` wraps the AGENTIC LOOP; the seed
retrieval that precedes it is not a loop stage and is not inside that total. The same
arithmetic guarantee holds: `total >= every other stage`.

In **rag** the vocabulary is fixed and it is the shortest of the three, because the lane
reaches no model: `embed` (the query vector), `retrieve` — followed by its children
`retrieve.lexical` and `retrieve.vector` — `fuse` (the RRF pass and the hits it builds),
`expand` (the post-fusion overlap merge that decides which of two overlapping spans owns the
citable region, and the cap), then `total`. Unlike fast's gather these two children are
SEQUENTIAL awaits, so they sum to their parent rather than exceeding it, and a diagram is
right to draw them as a chain. `embed` comes back `skipped` when the caller already held the
query vector. The same arithmetic guarantee holds: `total >= every other stage`.

Beside the duration, a stage may carry a **`preview`**: a small object naming what it was
handed and what came out. A duration says a stage was slow; it never says what it was slow
*at*, and `retrieve.claims 812ms` reads the same whether the face returned two claims or
eighty. `preview` is null when a stage offered none — a stage that did not run, one with
nothing worth a glance, or an older service — which is a different fact from an empty object
and is never faked into one. The keys belong to the stage, not to the wire: a client renders
whatever rows it is given, and a lane that grows a stage does not need a client release.

**A preview says what an item IS, not which item it is.** Where a stage previews a list of
results, each entry is an object in one shared vocabulary — `text` (a bounded head of the
item's own words, markdown, citation spans and anchors stripped), then where it lives (`doc`
for a canonical page, `source` + `span` for a passage), then `id` as a trailing tag:

```json
{"hits": 80, "items": [{"text": "The pilot ends in March.", "doc": "Pilot", "id": "c1a2b3c4"}]}
```

A tool call previews as the call it was — `person(alias="…")`, arguments inline — and a
selection previews as a line per face (`claims 80 → 1, windows 60 → 0`) with the chosen items
listed beneath it, grouped by face.

What each stage previews today:

| Stage | Keys |
|---|---|
| `plan` | `cap`, `queries` — the extra retrieval queries the planning turn wrote, verbatim |
| `retrieve.claims` / `retrieve.windows` | `hits`, `items` (first ≤5 entries), plus the candidate `pool` on the claim face |
| `retrieve.glance` | `offered`, `cap`, `hits`, `items` — each chosen page as its definition under its title |
| `retrieve.path:<name>` | `call` (the lookup as it was called, arguments inline; a rejected one carries its reason), `hits`, `items` |
| `route` | `tool_calls` — one rendered call per chosen path, or the sentence `"no path chosen — offered: person, timespan"` naming the paths the turn declined |
| `rerank` | `candidates`, `kept`, `top` (≤5 entries); the component pass adds `component_*` of the same three |
| `select` | `faces` (`claims 80 → 1, episodes 52 → 0, windows 60 → 0` — a face with no candidates is left out), the chosen entries under `claims` / `episodes` / `windows` / `components` (≤10 in total), `documents` when pages were expanded, and `chosen: "none"` when the selection call failed |
| `assemble` | counts and characters per section, merged across the passes (`windows` / `window_chars`, `episode_summaries` / `episode_chars`, `provenance_passages` / `provenance_chars`, `images`), plus `sections` — the same facts as one line, `claims 8 · windows 12 · episodes 4 · 11.5k chars` |
| `answer` | `format`, `turns` (2 when a structured call fell back to the text contract), `sections`, `input_chars` and the per-face counts that make it up |
| deep/ask `tool:<name>` | `call` the model wrote (arguments inline), `result_chars`, `result` (a ≤120-character head of what came back, as display text) — the SIZE and the opening, never the result |
| deep/ask `turn:N` | `tool_calls` the turn issued, rendered inline, or `"none"` for the closing turn |
| build `retrieve.claims` / `retrieve.passages` | `cap`, `hits`, `items` |
| build `expand` | `passages` / `passage_chars`, `sources` / `source_chars` |
| build `pack` | `documents`, `glance_chars`, `sections`, `pack_chars`, `budget_chars`, `prefix_chars` |
| rag `embed` | `dimensions` |
| rag `retrieve.lexical` / `retrieve.vector` | `candidates`, `hits`, `top` (≤5 entries); the vector arm adds `raw` / `episode` |
| rag `fuse` / `expand` | `rankings` or `fused`, then `hits` and `top` |

A preview is **bounded mechanically, in one place**: the service caps the serialized object at
roughly 1 KB, truncating lists (a cut list ends with `…+N more`), shedding an entry's
decoration in a fixed order — `id`, then `span`, then `doc` / `source` — and eliding strings,
at successively harder rungs, finally dropping trailing keys. **What an entry says outlives
the id beside it**: that order is the squeeze's, not a convention, so a tight budget can never
be spent on ids while the words are cut. So a preview is always small enough to render whole,
and it can never become a second, unbounded way for source text to leave the library —
evidence reaches a reader through the answer and its citations.

Each `trail` record carries the `ms` of the call it describes — the same number the matching
`tool:<name>` stage reports — and it is stamped before the step is streamed, so a client
growing the trail live over `/recall/stream` renders a measured duration rather than one
timed from arrival gaps. The closing `done` event of that stream carries the full `stages`
list, which is the only place the turns between the tool calls become visible.

### Watching a lane run

Every lane that costs a user real seconds has an SSE twin that narrates it: `POST
/…/recall/stream` (all three recall modes), `POST /…/briefings/stream`, `POST
/…/briefings/{id}/ask/stream`. The plain routes are unchanged.

One event vocabulary across all three — and a lane sends only the frames it has:

| Event | Payload | Meaning |
|---|---|---|
| `stage` | `{name, key, phase, at_ms, ms, status, detail, preview}` | a stage began (`phase: "start"`, `ms: null`, `preview: null`) or settled (`phase: "end"`, carrying its `preview`) |
| `token` | `{text}` | a delta of the answer as the model writes it; append in arrival order — never sent by `mode: rag`, which reaches no model |
| `step` | one trail record | deep recall only — one agentic tool call, `ms` already stamped |
| `done` | the lane's full result | byte-for-byte what the plain POST returns for the same request |
| `error` | `{detail}` | the lane failed mid-run; the stream then closes |

`stage` events come from the SAME measure sites that produce the final `stages` list, so the
picture drawn live and the breakdown that arrives with `done` cannot disagree. `at_ms` is
elapsed milliseconds since the lane began, on the server's clock — it places the event on the
lane's timeline. It is not a counter's starting value: a stage that opens three seconds into a
lane has been running for zero, so a client ticks a running node from the frame's arrival and
the `end` event then reports what the server actually measured.

`preview` rides the `end` frame only: a `start` has measured nothing and produced nothing, so
a preview on one would be the only value in the frame that was not observed. The object on
that frame and the one in the `stages` that arrive with `done` come off the same recorder, so
they are one fact rather than two that could drift.

**A structured answer streams as JSON.** `answer_format: "structured"` asks the provider for a
JSON object, and JSON is what it writes token by token, so the `token` deltas of a structured
lane are fragments of `{"answer_kind":…,"answer":"…","citations":[…]}` rather than prose. A
client showing provisional text reads the `answer` string out of the partial object (a partial
escape — a trailing `\`, a half-written `\uXXXX`, one half of a surrogate pair — is held back
rather than printed, and everything after that string closes is not the answer); a `text` lane's
deltas are prose and are shown as they arrive. The `done` frame replaces the provisional text
either way. The route does not label the frames: the buffer's own first character says which
shape it is, and the deployment — not the request — chooses the format.

`key` identifies a NODE and belongs to the lane, not the client. A fixed vocabulary (fast
recall, the briefing build) accumulates by name — `assemble` is measured several times and is
one stage — so there `key == name` and a later `end` supersedes the earlier one for that key.
An agentic lane appends: two calls to one tool are two steps, so it mints a fresh key each
time (`tool:search_claims#3`). A client that keys on `key` and prints `name` is right about
both without knowing which lane it is watching.

Anything decidable before the lane starts is a status code, not a narrated failure: an unknown
mode, a fast-only knob sent in deep mode, a keyless deployment (503), an unknown briefing
(404). Once the body is streaming the status line has already been sent, so a failure after
that point can only arrive as an `error` event.

`as_of` is the time at which the question is asked, not the source timestamp. Omit it for a
live question. Historical replays must send their original timezone-aware timestamp; the
scaffold CLI exposes the same contract as `./app.py ask '...' --as-of ...`.

`include_original_modalities` is the query tool's explicit cost/attention choice, not a
deployment default inferred from model capability. It is an enum list so the signature can
grow to audio/video without changing shape; today the sole value is `"image"`. Leave it empty
for textual questions. Use `["image"]` when direct visual inspection is necessary, such as
whether an object appears in a picture, its colours, text or layout. Labelled derived
representations remain usable when originals are omitted. The answer echoes what was actually
included through `included_original_modalities` and `original_modality_counts`. Original
delivery applies to `fast` and `deep`; `rag` returns text retrieval hits and rejects a
non-empty list.

Source detail never exposes an object-store key. Each image manifest contains `image_id`, MIME type, SHA-256, size, labelled derived representations and an API URL. The browser and citation sheet fetch that URL through the service; the S3/RustFS bucket remains private.

`GET /…/access-stats/top` ranks on the window you ask for and reports on the read face's
own: `heat` is over the last `days` days, while `hits_7d` / `hits_30d` / `last_accessed_at`
are the same three numbers `GET /…/access-stats` gives for that page, so a document reads the
same on a dashboard as on its own page. `half_life_days` is echoed because heat is computed
at read time from a knob rather than stored — the same rows report a different number under a
different half-life. A target with no hit inside the window is left out rather than ranked at
zero, and a library nobody has consulted answers with two empty lists rather than a 404.

## Consultations (use-side L0)

A consultation is one answering-lane call, kept as the audit chain needs it — the question,
which library answered, every address the lane put in front of the model, the answer, and
which of those addresses it cited. Written only for a non-`silent` visitor (see
`visitor_class` above), frozen once written, never re-derived, and never an authority over
knowledge: reading these changes nothing, and no gate, contract or compile input joins
against them.

| Method | Path | Purpose |
|---|---|---|
| GET | `/…/consultations` | one page of summaries, newest first: `limit` 1–100, `cursor`, and the filters `lane` (`fast\|deep\|briefing_ask`), `visitor_class` (`audit\|business`), `miss`, `target` |
| GET | `/…/consultations/{id}` | the whole record: `as_of`, `answer`, `evidence_handed[]`, `citations[]`, `degraded[]` beside the summary fields |
| GET | `/…/consultations/spend` | what the recorded consultations of the last `days` (1–365, default 30) spent, grouped by lane and by visitor class |

A summary carries `consultation_id`, `created_at`, `lane`, `visitor_class`, `question`,
`miss`, `answer_kind`, `library_ref`, `citation_count`, `evidence_count`, `token_usage` and
`cost`. The evidence itself stays on the detail route: a listing that carried every manifest
would be the detail route N times over — but the usage does not, because "what has this
library been costing me" is a question about a list.

**The recorded `answer` is not the wire answer byte-for-byte.** A lane that aliases source
ids writes the record back through that map: handles resolve to real source ids, and a
bracket still naming a handle the map does not know is removed from the recorded prose.
`citations[]` is filtered the same way and admitted only against `evidence_handed[]`, so a
marker naming a span nobody was shown is prose in the answer and absent from the list. What
the caller received is untouched.

**`token_usage` is stored; `cost` is derived.** The record keeps what the call spent in
tokens, which is what happened and stays true. The money is computed when the record is read,
out of the rates this deployment declares (`MODEL_PRICING`, [configuration](configuration.md)),
and is `null` when it declared none for the models that lane used — tokens with no figure
beside them, never a `0` that would claim the call was free. A record written before usage
was kept reports `{}` and the same `null`.

`GET /…/consultations/spend` sums the same rows over a window: `window_days`, `since`,
`until`, `consultations`, `with_usage`, `incomplete`, `token_usage`, `cost`, and the two
groupings `by_lane` / `by_visitor_class` (each `{key, consultations, with_usage, incomplete,
token_usage, cost}`). It is read out of the consultations table alone — no counter is
incremented anywhere, so it cannot drift from the records it describes. It is the spend of
**recorded consultations**, which is not the deployment's bill: a `silent` visitor leaves no
row, and the Live Context lane records none. A group whose models are not all priced, or
which mixes currencies, reports its tokens and no cost.

`with_usage` is how many of those consultations reported any counter at all, and
`incomplete` is `with_usage < consultations`. It exists because a provider that reports no
usage stores `{}`: every sum over it is null and coalesces to zero, so after the summation
an unmeasured call is indistinguishable from one that was genuinely free. An incomplete
window (or group) reports its tokens as a floor and `cost: null` — never a total over the
measured half presented as exact.

`visitor_class` takes only the two classes that leave a record. `silent` writes nothing at
all, so filtering by it would name an empty set a reader could mistake for "nobody asked".

**`target` is the reverse lookup** — which consultations handed or cited ONE address — and it
takes an address in the ordinary grammar (I4): a claim anchor `c:xxxx`, a `<source_id> ¶a-b`
span, or a canonical page path. A page matches BOTH ways it is reached: opened and read in
full (its path is the address itself) and through a claim that lives on it (its path rides
along on the claim). A lookup that matched only the address would answer "nothing" for
exactly the page whose access card offered the link.

Cursors follow the same contract as every other collection: the filter set is bound into the
cursor, so changing a filter mid-walk is a 422 rather than a silent first page of another
list.

## Compile, jobs, history

| Method | Path | Purpose |
|---|---|---|
| POST | `/…/compile` | enqueue one compile job per undigested source (idempotent) |
| GET | `/…/jobs` | queue pagination (`status`, `kind` filters); each job carries `token_usage` (the compile loop's own sum over its rounds) and the derived `cost`. The compile loop counts input, output and total only — no cache split — so a priced compile is billed as if none of its prompt was cached, which OVERSTATES it wherever the provider did cache |
| GET | `/…/history` | unified timeline of patches, jobs and snapshots, with counts |
| GET | `/…/history/activity` | timeline calendar |

The job queue stores three statuses — `queued`, `claimed`, `done` — and *failed* is not one
of them: a compile the gate rejects finishes `done` like any other job and says which it was
in `ok`. `GET /…/jobs?status=` therefore accepts two derived names beside the three stored
ones:

| `status=` | Selects |
|---|---|
| `queued` / `claimed` / `done` | the stored value, verbatim; `done` is still both outcomes |
| `succeeded` | `done` and `ok=true` — the job committed |
| `failed` | `done` and `ok=false` — the job finished without committing (a gate rejection, an aborted round) |

`GET /…/summary` carries the same set as `jobs_failed`, so a workspace whose compiles are all
aborting is visible without listing the queue. The `status` value is bound into the pagination
cursor: changing it mid-page is a 422, ask again from the first page.

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
| POST | `/…/briefings` | build a stable evidence pack on a pinned snapshot: `{query?, source_ids[], budget_chars>0, snapshot?}` |
| POST | `/…/briefings/stream` | the same build, SSE — `stage` events as it runs, then `done` with the same body |
| GET | `/…/briefings` | list |
| GET | `/…/briefings/{id}` | read one back: `{briefing_id, snapshot_ref, created_at, char_count, scope, text, stages}` — `text` is the literal pack |
| POST | `/…/briefings/{id}/ask` | ask against the stored pack: `{question, visitor_class?: silent\|audit\|business}` → answer + citations, with `token_usage` and the derived `cost` |
| POST | `/…/briefings/{id}/ask/stream` | the same ask, SSE — `stage` and `token` events, then `done` |
| DELETE | `/…/briefings/{id}` | delete |

`visitor_class` means exactly what it means on recall (above); an ask's consultation record
names the pack's pinned snapshot as the library that answered.

Both stream routes follow the vocabulary above. The build's row is persisted **before** `done`
is sent, so a client that saw the frame can always read the briefing back.

Both halves report their cost as `stages`, in the same shape the answering lanes use
(`{name, ms, status, detail}`), each in the shape its own work has.

A **build** is mechanical — retrieval, expansion, assembly, no model call anywhere — so it has
a fixed vocabulary and sends it complete, in order: `retrieve` (followed by its children
`retrieve.claims` and `retrieve.passages`), `expand`, `pack`, `total`. A stage that did not run
is present with `status: "skipped"` and `ms: 0`, so a scope with no `query` half says so rather
than dropping it. Unlike fast recall's concurrent gather, the two lookups here run in sequence
and therefore sum to their parent. `expand` is what turns hits and anchored source ids into
evidence with provenance (context windows, materials cards, the citation reverse lookup, L0
excerpts) and accumulates once per anchored source; `pack` is the glance, the segment join and
the budget truncation. `total` wraps the whole build.

The build's breakdown is **persisted with the briefing**, so `GET /…/briefings/{id}` returns it
for a pack built weeks ago — as measured, never re-derived. A briefing stored before the column
existed reads back with `stages: []`, which is "not recorded" and not "took no time".

An **ask** is an agentic loop and reports like deep recall: the run's own sequence — `turn:1`,
`tool:search_knowledge`, `tool:fetch_verbatim`, `turn:2`, …, `total` — with `finalize`
(`status: "degraded"`, `detail: "budget"`) when the tool budget forced a closing tool-less call,
and a failed tool call `degraded` with its reason whether it raised or answered with a stated
failure. Each `verbatim_fetches` record carries the `ms` of its own call, the same number the
matching `tool:fetch_verbatim` stage reports. `total` wraps the LOOP only: the pack was built
earlier — possibly days earlier — and charging an ask for it would misname where the seconds
went. In both halves the one arithmetic guarantee holds: `total >= every other stage`.

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
| POST | `/…/live-context/stream` | one-shot SSE over a transcript window: one `event: suggestion` per surviving card, then `done` carrying what the tick did |
| WS | `/…/live-context/ws` | long-lived listener. Client sends `config` / `turn` / `flush` / `reset` / `want_more` / `ping`; server sends `ready` / `suggestion` / `suggestion_detail` / `stats` / `error` (never fatal) / `ping` (~30 s keepalive). `reset` says the conversation was cleared: the session drops the pending run, the context tail, the subject ledger, the mined list and the seq, invalidates any evaluation in flight, and answers with a fresh `ready` — the policy is untouched. Without it a client's clear empties only its own half, and the next mention of a subject from before the clear is skipped `already_mined` against a card nobody can still see. The full protocol is documented in the module docstring of [`api/routes/live_context.py`](../../packages/pneuma-knowledge-service/src/pneuma_knowledge_service/api/routes/live_context.py) |

A delivered card carries two text fields with two different authors, and they are separate because that distinction is the point: `body` is the **lede** — one or two sentences guessing why this matters to this reader now, written by the pick model and capped mechanically — and `evidence` is the verbatim claim text and excerpts underneath it, rendered mechanically from what was retrieved and rewritten by nobody. `subject` names the canonical document or source the card is about, and a client replays it in `already_shown` so a reconnect does not re-introduce a subject the reader has already met.

**Two citation shapes, and `kind` says which.** `concept` and `fact` cards carry `citations` — the one addressing scheme over the owner's own material, `{source_id, block_start, block_end}` (I4). A `kind: "web"` card carries `web_citations` — `{title, url}` — because it rests on pages rather than on source blocks, and a URL is not an address in that scheme: it resolves to nothing the store can fetch and it must never be squeezed into a `Citation`. A card never carries both, and both fields are always present as lists, so a client tests a field rather than sniffing for one. Everything else about the evidence surface is identical across the two: the same numbered rows, the same collapsed section, and the pick's citation subset selects into either list by the same index rule (an empty or wholly out-of-range subset falls back to all of them rather than stripping the card). Only the affordance differs — a source span opens in-app, a URL opens in a new tab — and `want_more` is unavailable on a web card, because there is no source block to fetch verbatim and expand within.

`stats` (WS, opt-in) and `done` (SSE) both carry the tick's **processing record**: `skipped` (`""` on a delivery, else which door closed — a discover reason `small_talk` / `already_mined` / `nothing_new`, or one of `low_worth`, `no_plan`, `no_candidates`, `no_coverage`, `none_chosen`, `low_confidence`, `uncited`, `duplicate`, `unparsed`, `pick_failed`), `intent`, `worth`, `plan` (the lookups that ran), `rejected` (plan entries naming no enabled path), `candidates` (each `{index, kind, title, subject, origin, provenance, citations}`), `chosen`, `web` (`{tier, searches, cost, pages}` — see below), and `stages` (`discover` / `retrieve` / `retrieve.semantic` / `retrieve.web` / `retrieve.path:<name>` / `pick` / `total`, each with `ms` and `status`). `no_coverage` is the pick's own `choice: 0` — it read every candidate against the intent and none of them covers it — and is deliberately distinct from `low_confidence` (a weak answer held back) and from `none_chosen` (a malformed index), because the three look identical on a silent tick and mean different things. `dropped` is still there and is the briefing round's four-gate accounting; it is empty for the full-scope lane, whose equivalent is `skipped`.

Policy fields on `config` and `ready`: `focus`, `min_confidence` (one number, two doors — discover's `worth` floor and pick's `confidence` floor), `max_pending_turns`, `quiet_period`, `web_search`, `briefing_id`, `stats`. `web_search` asks for the supplementary internet path; the `ready` echo is the **effective** value, because the deployment has its own answer (`PNEUMA_KNOWLEDGE_LIVE_WEB_SEARCH`) and a client that asked for `true` and reads `false` back has been told no mechanically rather than left to infer it from the absence of web cards. The tick's `web` record then says what that path did: `tier` is `off`, `planned` (discover asked for the lookup, so it ran concurrently with the library faces) or `fallback` (discover did not ask, the library came back with an empty candidate pool, so it ran after), alongside `searches`, `cost`, and `pages` — how many pages those searches came back naming. `pages: 0` beside a non-zero `cost` is the one outcome that would otherwise be invisible: a search that ran, was billed, and cited nothing, so its answer was refused at construction and no candidate ever appeared. `turn_window` is accepted as the old name of `max_pending_turns`, and `max_suggestions` is accepted and ignored — the full-scope lane delivers exactly one card per tick by construction.

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
