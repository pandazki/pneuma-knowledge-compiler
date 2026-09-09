# Owner, Steward, Visitor — the roles above the library

**English** | [简体中文](steward-owner-visitor.zh-CN.md)

## 1. The frame

The library — everything [architecture](../architecture.md) describes — is programmatic. Its
reads, writes, schema construction and evolution are calls, and the architecture does not
change whether a person or an agent makes them. What it does not name is *who* makes them.
Three roles, layered above one tenant's library:

| Role | Does | Sees | Feeds | When nothing is configured |
|---|---|---|---|---|
| **Owner** | provides the sources, states the intent, calibrates (adds, corrects, adopts an evolution) | everything | material → knowledge L0; intent → the contract; every act → an event | the tenant principal: every write through the API is the Owner's |
| **Steward** | compiles, drafts evolution, grooms, answers, keeps a memory | every act of the Owner; visitors' consultations by class | writes → the library, through the same gate as anything else; memory → routing hints and evolve evidence | the **null Steward**: today's compile model and evolve runner, with no memory |
| **Visitor** | reads | the library, as permitted | consultations → events, by class | every read is silent |

Three rulings fix the shape:

- **The Owner acts on the library only by speaking to the Steward.** An Owner statement is a
  *source* — cited like an email — and an *event* — observed like anything else. One act
  satisfies both "cannot fabricate" (the claim cites the statement) and "the Steward sees
  what the Owner did" (the statement is in its event log). There is no Owner write path
  that bypasses the gate; a correction is a statement the Steward turns into `edit_claim` or
  `supersede_claim` with the statement as evidence.
- **The Steward's memory lives in the Steward, not in the library.** The library holds
  knowledge L0, canonical and what derives from them; the Steward holds its event log and
  what derives from *that*. Dependency is one-way, Steward → library, and the library never
  reads the Steward's memory. Whether memory shapes how the Steward compiles is the
  Steward's own affair, in the same category as which model it runs — outside the
  library's attribution, which names the contract, the wording and the components, and
  never claimed to name the model's variance.
- **The contract is written by the Steward from the Owner's intent.** An Owner who wants the
  contract changed instructs the Steward; the instruction is an event; adoption stays an
  explicit act because it triggers the mechanical merge.

With the three defaults stacked — tenant as Owner, null Steward, silent visitors — every
seam renders byte-for-byte as it would without the concept. That is the same discipline
schema packs and index components already follow: unregistered means nonexistent.

## 2. Two kinds of L0

Knowledge L0 is what the Owner put there: sources, verbatim, addressable by
`source_id + ¶ span`. Canonical derives from it and from nothing else.

**Use-side L0** is what the system observed: a source was ingested, a compile ran, a
visitor asked. These are *records* — kept rather than re-derived, and never an authority
over knowledge. Canonical does not derive from them. The Steward's memory does.

The use-side record is the **consultation**: an opening question and handed evidence,
followed by an answer event if one arrives. Handover itself counts as use.

## 3. The consultation record

A `ConsultationRecord` (core `domain/consultation.py`) is a frozen dataclass. It represents
an `opening`, an `answer` event, or their joined `complete` read. `complete` is not a third
kept event: single-call lanes write the two together and the worker delivers them separately.
`pkc recall --evidence` records the opening immediately under `business` or `audit`; its id
is the handoff id. `pkc consult answer` appends the answer once. A handoff may expire, but its
opening stays unanswered. Neither event is rewritten (storage fills only NULL answer columns
under `answered_at IS NULL`). `silent` records neither event.


| Field | Meaning |
|---|---|
| `consultation_id`, `user_id`, `created_at` | identity (system-assigned) |
| `lane` | `fast` / `deep` / `briefing_ask` / `direct` |
| `visitor_class` | `silent` / `audit` / `business` (§5) |
| `question`, `as_of` | the question as asked, and the reference instant the lane resolved against |
| `library_ref` | **the canonical HEAD sampled when the consultation began** — the snapshot id instead when the call was pinned, which is the exact form of the same field. Sampled, not pinned: the evidence faces read live state, which may advance past the sample during the call (a compile lands mid-answer; the claim indexes are unversioned), so the ref names where the reading started rather than one state the whole answer came from |
| `evidence_handed` | every ADDRESS the lane put in front of the model, and nothing else: `{kind: claim/window/episode/component/document, ref}` where `ref` is a claim anchor with its page, a `source_id ¶a-b` span, or a canonical page path (`document`: a page the lane opened and read in full). It carries the evidence ITEMS and the provenance spans rendered WITH them — a claim note prints its own `[cite: …]` marker and the contract tells the model to copy source references verbatim from those markers, so a span named there is an address the model was shown. The lane publishes it as a manifest at render time (`recall/fast.py:evidence_manifest`) and the builder copies it |
| `answer_kind`, `answer`, `citations` | the answer and its resolving addresses, each with `origin: handed` or `direct`. Model lanes admit against their manifests; agent answers additionally resolve direct reads against tenant-scoped L0 and canonical anchors (below). Unresolved handles are removed from model-lane recorded prose; an agent answer with an invalid citation is refused before recording |
| `citations_direct` | the count of citations whose stored origin is `direct`; handed evidence remains exactly what the lane handed |
| `answered_at`, `state` | the answer event's timestamp, or NULL while `unanswered`; an answered consultation has state `answered` |
| `miss` | NULL while unanswered; once an answer exists, one rule, every lane: `answer_kind == "no_record"`, or nothing reaching the model at all (see below) |
| `degraded` | the lane's degradation flags, copied |
| `token_usage` | what the consultation SPENT, as the lane's own usage mapping in field order. Tokens and never money: the count is what happened and stays true, while a price is a commercial arrangement that moves without asking this record — so the cost is derived when somebody reads, out of the rates the deployment declares then (`MODEL_PRICING`), and is absent rather than zero for a model it never priced |

The record carries no prose the lane did not already emit. It is written by the **service**
(`consultations` in `infra/schema.sql`, adapter beside `briefings`), never by core, because
the record is the Steward's, and the service is the null Steward. Core defines the type, the
event channel, and one pure builder per lane (`recall/consultation.py`, beside the lanes
rather than beside the record: the shape a builder reads is the lane's, and domain → recall
would be the wrong direction). It holds no consultation port and reads no consultation.

**The table above is a UNION across the answering lanes, and no lane fills all of it:**

- **fast** populates everything. Its `citations` are not a field on `FastAnswer` — there is
  none — but the answer's own markers re-parsed through the lane's `citation_handles` map: a
  handle the map does not know is dropped, which is the same rule the lane's own citation
  filter applies. Under `answer_format: structured` those markers are the model's declared
  citations; under `text` they are the markers it wrote into its prose.
- **deep** publishes no `answer_kind`, no degradation flags, and no episode or component
  evidence — its loop re-retrieves across rounds, so the record carries claims and windows
  only, and the two absent fields stay empty rather than being guessed from the text. It
  does not alias source ids either, so its markers are already real and its recorded prose
  is the prose the caller received.
- **briefing_ask** publishes no `answer_kind` and no degradation flags. Its manifest is the
  frozen PACK plus what `search_knowledge` rendered mid-answer plus what the loop fetched:
  the pack is this lane's evidence, so it is published as such rather than the record naming
  the fetches alone. The pack's half is RECORDED WHEN THE PACK IS BUILT and stored with it
  (`Briefing.pack_manifest`, the `briefings.pack_manifest` column): each rendered block —
  claim note, verbatim window, materials card, raw excerpt — carries the addresses it was
  rendered FROM and its byte range in the pack, and after the character budget truncates the
  pack, only the blocks that survived whole enter the manifest. It is never read back off
  the rendered text, because a source is whatever somebody imported and a passage whose body
  contains the literal string `[cite: s01 ¶3-4]` is quoting, not citing — a parser cannot
  tell a marker a renderer printed from one a source happens to hold, and a manifest that
  cannot tell admits citations to evidence nobody retrieved. A briefing stored before its
  pack manifest was recorded carries none, and its ask admits nothing.
  Its `library_ref` is the pack's own pinned commit ref — a briefing is pinned by
  construction, so no HEAD lookup happens.

**Under an agent executor, the agent's reading IS retrieval.** A hand-over's manifest
cannot enumerate subsequent `canonical read` and `source fetch` calls; keyless retrieval may
hand an empty manifest because the glance pick needs a model. Membership was a proxy for
resolution, and direct reading makes it the wrong proxy. `pkc consult answer` resolves every
marker through the hand-over's handle map when applicable, otherwise as a real
`[cite: <sid> ¶a-b]` address or a `c:xxxx` anchor. The source must exist in this tenant's L0
with `1 <= a <= b <= block count`, or the anchor must exist in this tenant's canonical.
Manifest membership (anchor equality or span containment) keeps `origin: "handed"`;
resolving addresses outside it carry `origin: "direct"`. An invented interval on a real
source is refused with exit 4, naming the citation; no answer event or answer projection job is emitted,
and the pending hand-over stays open for a corrected answer. `evidence_handed` is unchanged.

`pkc consult record --question <q> --text-file <f>` (or `-` for stdin) records an answer when
no hand-over was made: lane `direct`, empty handed evidence, every citation direct, the same
resolution, fast record builder and `_spawn_recording` emission. It samples `library_ref` at
recording and leaves `as_of` absent; it cannot reconstruct the earlier reading snapshot.
Both commands accept `--kind no_record`. Direct recording defaults to `business` and accepts
`audit` or `silent`, with the same row/job rules as a handed answer. One question, one id, two kept events:
a failed close leaves the answer correctable; re-running recall to fix it creates another
hand-over instead. No kept record is rewritten.

**A map of where something is is not evidence.** The library GLANCE — every page's path,
title and one-line definition, which fast, deep and the briefing pack all open with — is
deliberately absent from every manifest: it is how a model decides what to read, counting it
would make every consultation touch every page, and it carries no citation marker or anchor
at all (`canonical_glance` strips both). The pages the glance then SELECTS for reading in
full are manifest `document` items with every span their bodies carry, because those are the
pages whose text actually reached the model. A source section's structure outline in a
briefing pack (`- <section>  ¶a-b`) is out for the same reason as the glance.

**`miss` is computed only when an answer exists**, with one rule for every lane: `answer_kind == "no_record"`, or nothing reaching the
model at all — neither handed evidence nor resolving direct citations. The shared predicate
is `domain/consultation.py:is_miss(answer_kind, evidence_handed, citations)`. The predicate
is mechanical rather than each caller's discretion, because everything counting "what the
library could not answer" is only as truthful as it is.

## 4. Delivery, and the two use-side seams on the component protocol

**A consultation is EMITTED, never processed in the request path.** The route builds the
record, creates a detached task and returns; the task writes the row and — for a `business`
visitor — enqueues one `recall_projection` job in the same transaction. Consuming that job
is the worker's, on the per-user queue the ingest side already drains. The response, and the
terminal frame of a stream, wait on nothing: not the write, not a consumer, not a timeout
bounding either. What that costs is stated rather than hidden — the record is best-effort
fire-and-forget, and a process death between the answer and the task's commit loses it. What
it can never cost is the answer. Explicit CLI recording instead awaits persistence with
`strict=True`: evidence is not published as recorded, nor a handoff consumed, until the write
succeeds. Projection still runs only on the worker.

Neither half of the emit can exist alone: the row and the job commit together, so no job
names a consultation that is not there, and no `business` record is written with nobody
scheduled to read it. Handoff jobs carry `consultation_id` and `event` (`opening` or `answer`).
Single-call jobs retain their existing id-only payload; the worker splits the joined record
into opening and answer deliveries.

- `on_recall(user_id, record)` — the use-side twin of `on_source_indexed`, called by the
  WORKER when it drains that job. `notify_recall` fans out with the same fail-soft rule: a
  component that raises is logged, never a failed job. Called only for `business`
  consultations, once for each event; the opening carries no answer or miss classification.
- `evolve_evidence(user_id) -> str | None` — one mechanical block a component may
  contribute to the evolve proposal's evidence. Core assembles the blocks
  (`components.collect_evolve_evidence`, one header per component, fail-soft per component,
  `None` when nothing came back) and the service's evolve runner hands `propose_evolution` a
  single `demand_evidence: str | None`; the human message gains a fourth section only when it
  is not `None` (I5 holds: nothing enters the system message).

`rebuild` keeps its name and gains a second legitimate substrate (§8).

## 5. Visitor classes, and the console lens

A request field on `/recall` and `/briefings/{id}/ask`: `visitor_class`, default `silent`.

| Class | What the request path does | Meant for |
|---|---|---|
| `silent` | nothing — not a row, not a job, not even a task | evaluation harnesses, benchmarks, auditors who must leave no trace — the default, so a caller that sends no field is byte-identical |
| `audit` | row only | callers whose consultations must be reconstructible but must not steer the Steward |
| `business` | row + projection job | the people the library exists for |

Recording and influence are two axes; these are the three points on them that matter, and
weighting is left to the application.

**At the web console the lens derives the class.** Role there is an identity, not a per-request
choice: one top-level switch — Owner / Visitor / Silent visitor — decides both what the app
shows and what class its questions carry, and there is no selector beside a question. Owner
is the cockpit, every view the console has. Visitor and Silent visitor are the reading room:
the answering surface and read-only canonical browsing, and nothing else. Both the navigation
and the router derive that from one declaration (`apps/web/src/lib/lenses.ts`), so a deep link
into the cockpit under a visitor lens lands back in the reading room rather than on a page
that lens was never meant to have. Owner and Visitor both ask as `business` — a question asked
at this console is the library being used, and a use nobody counted leaves the library
reporting itself unread — while Silent visitor asks as `silent` and says so on the badge and
on the page, because a stance whose whole point is that nothing is recorded has to be legible
to the person taking it. There is no `audit` lens: audit is an API caller's stance, not a
person sitting at a console. The `silent` default above is the API's, for callers that send no
field at all; the console always sends one.

**A projection therefore lags its consultation by the queue's drain**, and the honest
statement of that lag is the queue's own: per user, FIFO, single job in flight. An idle
library is seconds behind. A library whose owner just imported a corpus is behind by
whatever that user's compiles take, because a projection queued after them is claimed after
them. Nothing reading the ledger may assume it names the last question asked.

## 6. The access ledger, and the `attention` component over it

The ledger is the FRAMEWORK's and it is built in — the default consumer at the end of the
queue, applied for every `business` consultation whether or not any component is registered.
Default-on and inert by default: with every visitor `silent` there are no consultations at
all, so nothing is written and every seam renders byte-for-byte as it would without the
concept. Two derived tables (service `access_stats.py`):

- `recall_access_hits(user_id, target_kind, target_ref, day, hits, last_seen)` —
  `target_kind` is `claim` / `document` / `source`; one row per target per calendar day,
  where `day` is the event's instant in UTC (`created_at` for opening, `answered_at` for answer). The ledger holds no zone opinion: `time`
  owns the subject's calendar, and a second answer to "which day is this" is exactly what
  makes two projections disagree about one afternoon. Rows are written from a record's
  `evidence_handed` ∪ `citations` (a cited item counts once more than one merely handed
  over), and a target is dispatched on its ADDRESS rather than on its `kind` — `kind` says
  how a lane reached an item (`component` covers both a routed claim lookup and a routed
  span), the grammar says what it is: `c:xxxx` is a claim, `<source_id> ¶a-b` is a span. A
  document counts at most once per pass however many of its claims travelled, because
  counted per claim a nine-claim page reads nine times hotter than a one-claim page
  consulted just as often, which measures length rather than attention; claims and sources
  are items and are counted as they come. `last_seen` is the exact instant of the latest
  consultation that touched the target that day, so its true last access is the MAX over its
  rows — exact last-access tracking as one column on a row that was being written anyway,
  rather than a second table restating it.
- `recall_access_misses(user_id, day, question, count)` — the question whitespace-normalized
  and capped at 400 characters with truncation marked, bounded at the write path because it
  is this table's primary key.

**Access metadata never touches a canonical file.** It lives in the derived layer, keyed by
address, joined at read time — a read must never become a write to the authority. The read
face is `access_stats(user_id, pairs) -> {last_accessed_at, hits_7d, hits_30d, heat}` per
target, bulk by construction (a single target is a page of one), exposed as
`GET /v1/users/{user_id}/access-stats` for one target and `/access-stats/top` for the
ranked window. `last_accessed_at` is the whole history's answer and not the window's: a page
last read forty-five days ago has a real last access and no recent hits.

No score is stored. Heat is computed at read time as `Σ hits × 0.5^(age_days / half_life)`
with `ATTENTION_HALF_LIFE_DAYS` (default 14). Handed addresses count on opening; citations
and misses count on answer. The report separately counts openings, handed addresses, answers,
citations, misses and unanswered consultations in its window; unanswered is not a miss.

**Only stamped events are replayed**, in time order through `list_consultation_events`, with
opening before answer on a tie. `opening_projected_at` and the answer's `projected_at` are
independent: rebuilding while a later answer is queued preserves the already-applied opening
and leaves that answer to its own delivery. Each bounded page is folded into running sums
and dropped, and the rebuilt rows are swapped atomically.

**At most once per `(consultation_id, event)`.** Each event's increments and its stamp commit
in one transaction. Claiming only a NULL stamp makes duplicate deliveries no-ops. Rebuild
leaves both stamps and all kept fields untouched. It runs under this user's one in-flight
queue claim, so no projection can interleave with the scan and swap.
`scripts/ops/rebuild_derived.py` enqueues and drains that same `recall_rebuild` job.

What the stamp does not cover, stated plainly because a guarantee nobody can check is worse
than none: a process death between the commit and the component fan-out that follows it
loses that notification for good. That is the at-most-once trade this delivery model chose,
in place of the at-least-once one that would double every count it recovered — and the
stats, which are the half a rebuild can repair, are the half that commits.

The **`attention` component** is the FACES over that ledger and owns none of its rows. Its
`on_recall` and `rebuild` are explicit no-ops: a component that also incremented those
tables would double every count the day an operator switched it on, and a ledger of use that
depended on which faces were enabled would be measuring the deployment rather than the
readers. Unregister it and the stats keep accumulating; only the faces go.

- `evolve_evidence` — hot documents grouped by contract family; families with claims and no
  hits in the window (cold); the top misses with counts. Bounded in characters; renders
  `None` when the buffer is empty. Emptiness is checked on the TABLES rather than on whether
  there would be something to say: a library nobody has asked yet has cold families by
  definition, and reporting them would build an argument out of the absence of evidence, so
  the cold scan sits behind a non-empty window. The families come from the contract, through
  a service lookup — `canonical_glance.family_of` over the user's composed `path_templates`,
  resolved by `skills.path_templates_for`, a read-only sibling of `skill_for_user` that
  never writes a manifest and never calls a model, injected the way `user_info` is. Reading a
  user's skill is a service concern, and a component that could not get one still renders,
  under one unfiled group.
- `recall_tools` — `attention_report(days)` for the deep lane, the same text.
- `fast_paths` — `attention`: the hottest claims as a labelled component face, each resolving
  to its anchor, never fused into RRF.

## 7. `owner-dialogue/v1`

The Owner's statements as a source contract (`pneuma.source.owner-dialogue/v1`): one
dialogue, turns with `role: owner | steward`, aware timestamps, verbatim text; normalized to
one block per turn so a claim cites `[cite: <sid> ¶n]` exactly as it cites a chat message.
Intake is full canonical treatment and full semantic indexing. The compile task's mechanical
source line states the kind, so a model reading a source that looks like a transcript knows
it is a statement without being told to remember it. What an Owner statement *deserves* — a
correction, a supersession, a new page — is the contract's judgement, as it should be.

The rules that follow from that:

- **At least one turn must be the Owner's, and it must say something.** Everything above
  rests on the subject having spoken for themselves — the role label, the kind line, the
  full canonical treatment. A payload of `steward` turns alone is a document the Steward
  wrote about the Owner, and compiling it under this contract would make Steward-written
  text the Owner's canonical knowledge. A BLANK Owner turn satisfies the rule as a
  formality and changes nothing about the payload: the dialogue is still materially
  Steward-only, and an empty turn cannot become a block anything can cite. So the contract
  requires a non-blank Owner turn, and refuses a blank turn of either role outright —
  naming the turn and its role rather than filtering it away, because a payload that
  declares a turn nobody spoke believes something this contract does not. The import form
  disables submit until a non-blank Owner turn is written: the same rule at the tool face,
  before the gate.
- **Order is validated, not repaired — the one place this contract parts from `im/v1`.**
  Every other contract sorts what it is handed, because a provider archive's order is an
  artefact of the export. A dialogue's order IS its content: a sentence that qualifies the
  one before it stops qualifying it once the two are swapped. A payload whose `said_at`
  goes backwards is rejected.
- **A block has no metadata to keep the ids in.** `NormalizedBlock` carries `index`, `text`,
  `section_path`, `images` and nothing else, by design — so `owner_id` / `steward_id` and
  the turn ids ride the source's `meta` envelope and are rejoined to blocks in normalized
  order, exactly as `im/v1`'s `messages` envelope is. Either way the ids never enter the
  text a model reads, which sees a ROLE.
- **The contract has no title, and `RawSource` requires one.** The dialogue carries only the
  application's `dialogue_id`, so the stored title is minted from it through a prompt key
  (`ingest.owner_dialogue.title`) rather than by inlining English in core. Titles are not
  hashed into the source id, so a deployment switching prompt language does not fork
  its own dedup.
- **The kind line is the per-source preamble, not the outline.** `describe_source` builds
  one sentence per source and the compile worker hands it to the task above that source's
  blocks; the outline is the canonical layout and says nothing about sources. The line
  states the kind and the stance only — what the statement deserves is left out of it on
  purpose, because that is the contract's half.
- **A fifth contract is not purely additive at the data layer.** It carries its own
  `SourceKind` (`owner_dialogue`) and `SourceOrigin` (`console`); the kind-keyed lookups in
  the `people` and `time` components fall through to "no signal", which is the right answer
  — an Owner statement structurally names no third party. The reference contract's sentence
  naming this kind lives in `v2`; `v1` stays byte-stable.

## 8. What this touches in the invariants

I2 and I7 say a projection is rebuildable "from L0 and canonical". The access ledger
rebuilds from consultations, which are neither. The reading that holds instead:
**a projection is rebuildable from its declared substrate**, and use-side records are a
substrate — kept, not derived, surviving `rebuild_derived` unchanged. Nothing about
authority moves: consultations are not an authority over knowledge, and canonical still
derives from knowledge L0 alone.

Everything else holds unchanged: I1 (every table and method here is keyed by `user_id`
first), I3, I4 (every address in a record is the one scheme), I5 (the evolve section is
in the human message and only when non-empty), I6 (an evaluation harness is a `silent`
visitor by default — leak discipline has a name on the read side too).

## 9. Boundaries

The frame reaches further than the mechanism does, and the line is worth stating. The
Steward has an event log and no **notes** — no model-written judgement layer over the ledger;
notes without a ledger under them are self-report. Memory feeds routing hints and evolve
evidence, never compile. Components have no HTTP surface of their own; the ledger is read
through the framework's routes and through scripts. Visitor classes are the three above,
unweighted, and `pinned` targets are the application's extension point rather than a
framework table.
