# The archive — retiring knowledge without deleting it

**English** | [简体中文](archive.zh-CN.md)

## 1. Why

A library that is used for long enough accumulates knowledge its Owner no longer cares
about: a project that shipped, a vendor that was dropped, a team that was disbanded. Nothing
about it is *wrong* — every claim still cites its source, every source is still verbatim —
it is just no longer worth a slot in an answer. Left where it is, it costs every retrieval:
candidate caps are spent on it, the glance lists it, the compile outline offers it as a
place to write, and a question about the present is answered with the past.

The framework forbids deletion: canonical is an append-only history and L0 is the verbatim
record, so "remove it" is not an operation the library has. What it has instead is the
**archive**: a place the Owner moves knowledge to, where it stays whole, cited and
addressable, and from which no ordinary retrieval reads.

Retiring the knowledge is not the same as retiring the SUBJECT, and the difference is the
fourth ruling below. What leaves the answering set is the page and its claims; what stays
is one short record saying the subject was here and the Owner retired it. A question about
Aurora after the archive is still answered — with "Aurora was the delivery programme; it
covered January to June; the owner archived it on the fourth because the team disbanded"
rather than with the page, and rather than with nothing.

Four rulings fix the shape:

- **Archiving is a move, not a mark and not a deletion.** A canonical document is moved,
  byte for byte and with its git history, under one root directory of the library; a source
  keeps every block and gains one timestamp. Both are the authoritative record of the state
  — a rebuild of every derived layer reads the state off them and never off a side table.
- **The default is to exclude; the exception is stated.** Every retrieval face — the four
  lanes, live context, the compile model's view of the library, the source and document
  listings — excludes the archive unless the call says `include_archived`. A lane that
  includes it labels what it shows, so the archive is never presented as the present.
- **An archive is proposed before it is executed.** Knowledge hangs together: a document
  cites sources, a source is cited by documents. The Owner names one thing; the framework
  computes what follows, shows the whole set with the reason for each item, and moves
  nothing until the Owner confirms that exact set against that exact library state.
- **The subject leaves as a record, not as silence.** A page that simply vanishes takes its
  subject with it — and the library did not stop mentioning that subject: other live pages
  still link to it, and a question about it is answered out of whatever mentions happen to
  survive elsewhere, with nothing anywhere saying the Owner retired it. That answer is a
  partial truth the library has no way to label. So the move leaves an **archive record**
  standing at the live path (§2.3): what the subject was, the span it covered, how much it
  held, and the Owner's reason, citing the Owner's own statement. The record is ordinary
  live knowledge — in the glance, projected as claims, retrieved by default — so the subject
  goes on being answered, *as archived*.

Nothing here is the rollover mechanism of [architecture §5](../architecture.md#5-canonical-write-mechanics).
A rollover volume is a **closed volume** of the same work: a long-lived page becomes a work in
several volumes, the closed ones live beside the open one (`<doc>/aNN.md`), and every lane
indexes, retrieves and lists them as the live knowledge they are. The archive is a different
question — not "this book got long" but "this subject is no longer ours" — and a page goes
into the archive with its volumes. The two never share a word: only the archive is called
archiving.

## 2. The approach: nothing is deleted

Deletion is not an operation this library has. Canonical is append-only history and L0 is
the verbatim record, so no write path removes a claim or a block — and the archive does not
add one. What it changes is ATTENTION, and it changes it the only way a system with no
delete can: **two authoritative marks, and a default that reads them.**

**The two marks.** A canonical document is archived iff its path sits under `archive/`; a
source is archived iff `sources.archived_at` is not null. That is the whole of the state.
Both marks sit on an authority — a path in the git library, a column on L0 — so no side
table has to be kept in step, and every derived layer reads the state off them (I2).

**Every derived store carries the mark as one field it re-derives.** L1 blocks, L2 chunks
and the L3 claim projection each hold one boolean, written from the two marks and re-derived
from the same two by `rebuild_derived`. The field exists so each store's OWN search can
exclude the archive at the index: a post-filter alone would let archived items eat the
candidate caps (80 claims, 60 spans) before the answer ever saw a live one.

**Every search excludes it by default.** Each store filters in the dialect it has —
`archived_at IS NULL` in SQL, `NOT archived = true` in Meilisearch, `must_not archived =
true` in Qdrant — so the exclusion costs a predicate rather than a pass over results, and
the four lanes, live context, the compile model's view of the library and the source and
document listings all inherit it.

**One post-filter in core covers the evidence the two indexes do not produce.** Retrieval is
not only those indexes: a routed component path reads its own projection and L0, and a
briefing pack is built once from whatever it was handed. So the lanes apply one model-free
filter at evidence assembly, over the two authoritative facts they already hold — the
archived source ids and the `archive/` prefix on the documents they were given. The same
filter closes the window between the archive commit and the L3 sync behind it, by pinning
every claim to the document set the lane was handed (§3.9).

**`include_archived` is the stated exception, and it labels what it admits.** One boolean,
default `false`, on every request that reads (§4). A lane that admits the archive places it
after the live evidence and carries the `archived` label into the prompt and onto the wire,
so history is never readable as the present.

**And the whole mechanism is inert while the archive is empty.** No source is in an empty
set of archived ids and no path starts with `archive/` in a tree that has no `archive/`, so
every check is already a no-op; the one part that would not be — the document-set pin — is
switched off until a view is ACTIVE (`ArchiveView.active`: an archived source on L0, or an
archived document in the tree). The Owner who archives nothing runs the same questions
before and after this feature and sees no difference at all.

**What leaves the storage is nothing; what leaves retrieval is the default.** An archived
claim keeps its anchor, an archived source keeps every block, and both answer when addressed
by id or asked for by name. Section 3 states, store by store, what that costs each one.

### 2.1 The document mark: a path under `archive/`

The library root gains one reserved directory, `archive/`. Archiving `work/products/aurora.md`
moves it to `archive/work/products/aurora.md`; its closed volumes
`work/products/aurora/aNN.md` move to `archive/work/products/aurora/aNN.md`. Unarchiving is
the same move back.

The path IS the state. `archive/` is stated once, in core (`domain/archive.py`), and every
reader derives "is this archived" from the path prefix and nothing else. That is what makes
the mark rebuildable: `rebuild_derived` reads the tree and sees the prefix.

Why a move and not a frontmatter flag. The compile model writes frontmatter through
`set_fields` and `rewrite_overview`; a flag there is one more reserved key to guard. A path
under `archive/` is outside every contract's path templates by construction — path
templates are exact patterns, and a contract has no reason to declare a family there — so
the existing ownership predicate already refuses `create_document` into it, and the tree
shape tells the whole story to anyone reading the repository with no framework at hand.

### 2.2 The source mark: `archived_at`

`sources` gains one nullable column, `archived_at timestamptz`. Blocks, structure map, media
and chunk manifest are untouched; `RawSource` carries the value. L0 fetch by locator stays
unconditional (I3): a claim citing an archived source still resolves to its exact passage,
and `GET /sources/{id}` still answers. What changes is the search face — L1, L2 — and the
listing default.

Nothing is left behind on the L0 side. A source is not a subject — it is material — and the
record that keeps a *subject* answerable (§2.3) is written for the document that was about
it. A sources-only proposal therefore writes no record and ingests no statement.

### 2.3 The archive record

Moving the page retires it. It also, on its own, makes the subject **vanish**, and that is
the failure the record exists to fix: `work/atlas.md` goes on linking to
`work/products/aurora.md`, a question about Aurora is answered out of the scraps that
survived on its neighbours, and no face anywhere says the Owner retired it. So the same
commit that moves the page to `archive/<path>` writes a short **record** at `<path>`.

The record is LIVE. It is in the glance, its blocks are projected as claims, every lane
retrieves it by default, and no lane treats it specially — so "what happened to Aurora?"
answers *this was X; it covered A–B; the owner archived it on D because R*, with a citation
for the last part. It is not writable: every compile write verb refuses it, and the gate
refuses any diff on it.

**Mechanical, no model.** The record is written by the archive job through its own narrow
channel with its own gate, exactly as rollover writes a machine-managed document
([architecture §5](../architecture.md#5-canonical-write-mechanics)). Every byte is derived
from the page being archived, from the Owner's own statement and from a clock; the channel
writes nothing else, and a record rendered twice from the same inputs is byte-identical.

Frontmatter: `doc_id` — the RECORD's own, derived from a key no path can equal
(`record_doc_id`), because the move puts two documents in the tree and an id derived from the
live path alone would be the one the moved copy is already carrying, leaving
`read(user, doc_id)` to answer with whichever the listing reached first — `type: archived`,
`slug`, `title`, plus `archive_of: archive/<path>`
(the full copy), `archived_on: YYYY-MM-DD`, `archive_statement: <source_id>`, and the
machine facts — `archive_span: <from>/<to>` (absent when no cited source states a day),
`archive_claims`, `archive_sources`, `archive_volumes`, `archive_inbound`.

Body: three anchored blocks, anchors SYSTEM-assigned and deterministic per `(path, slot)`
— the rollover derivation, so a rebuild is a no-op and the ids are unique repository-wide,
against the full copy's own anchors included.

1. **What the subject was.** The page's overview `definition`, verbatim, with its own
   grounding references carried over (they name anchors that now live under `archive/`,
   still unique repository-wide), followed by the marker "— archived". A page with no
   definition contributes its first CURRENT ledger claim (`first_current_claim`) — also
   verbatim, its `[cite: …]` markers included, and NOT the glance's `ledger:` line, which is
   display text and strips them: a record's blocks are projected as claims, so a sentence
   that arrived here with its provenance removed would be an ungrounded assertion standing in
   every default answer (I4). A page with NEITHER contributes its title, and that one case is
   the only one the gate's grounding floor exempts (`GROUNDING_EXEMPT`) — nothing in such a
   page exists to ground on. The record renderer copies existing text and adds mechanical
   labels; it does not generate new claims about the retired subject. This preserves the
   existing wording and provenance, but does not verify the semantic truth of the copied text.
2. **What it held.** One mechanical line: `Covered {from}–{to} · ledger claims {claims} ·
   sources {sources} · closed volumes {volumes} · linked from live pages {inbound}` —
   labelled numbers, the figure last, because a channel with no model in it cannot inflect
   for number and each label has to say WHICH count it is (`claims` is the ledger's, this
   page and its closed volumes; the library view states a number for the same page that also
   counts the overview's projected blocks). The
   span is min/max `occurred_on` over the sources the page's claims cite (via
   `RawSource.occurred_on()`); with no dated source the span clause is omitted rather than
   guessed. `inbound` counts the live pages whose bodies link to the path and are not
   themselves leaving in the same commit — and "leaving" is the set the Owner FINALLY
   confirmed, which is why the job recomputes every number at execution through the same pure
   function the planner previewed them with (`record_facts_in_move`). `library_ref` pins the
   tree, so nothing derived from a page can drift; it says nothing about the set, and
   unticking a page that another selected page links to changes that page's `inbound`. **This block cites nothing**, and the exemption is
   a named rule (`FACTS_EXEMPT`), not a gap: its provenance is the frontmatter above, which
   carries every one of those numbers as a machine key, and the gate checks that the two
   agree.
3. **Why it left.** `Archived by the owner on {date}: «{note}»`, citing
   `[cite: <statement_sid> ¶0]` — the Owner's statement, one block, so the one sentence a
   reader quotes back is the one that rests on evidence. The quoted words are ¶0's own
   (`statement_quote`), never a sentence typed beside it — the turn text with its ROLE LABEL
   stripped and its whitespace folded, deliberately not byte-verbatim: the label is
   `owner-dialogue/v1`'s framing of who is speaking rather than a word the Owner typed, and a
   record block is one line. No word is dropped. The note is the Owner's prose and
   is treated as prose: a note carrying the system's own machinery — an HTML comment, an
   `__AUTO__` — is refused at `plan` and at `confirm` (`422 note_machinery`) by the compile
   gate's own predicate, because the text is interpolated into a block the projection indexes
   as a claim; the renderer sanitizes anyway (comments removed, a `[cite: …]` reduced to plain
   text, not a word deleted), so a row written before that refusal cannot put a second
   citation into the one block that carries one.

**The statement.** The Owner acts on the library only by speaking
([Owner/Steward/Visitor §1](steward-owner-visitor.md#1-the-frame)), so the reason needs a
source to cite. At execution the job ingests ONE `owner-dialogue/v1` source per proposal —
one owner turn carrying the confirm-time note, or a default sentence naming the archived
titles when the Owner wrote none — through the ordinary `ingest_source_contract` path, with
one override: `canonical_treatment: none`, `semantic_indexing: full`. The record IS that
statement's canonical expression, written mechanically in the same commit as the move; a
compile of the same text would paraphrase the decision onto whatever pages the model
believed it touched. Every field of that contract is derived from the PROPOSAL — the
`dialogue_id`, the turn id, and `said_at`, which is the proposal's `confirmed_at` and never a
wall clock — so two runs of the step build one contract, `ContentStore.add`'s checksum dedup
answers with one source id, and a worker killed between the ingest and the write of
`statement_ref` re-derives the statement it already made rather than minting a second one.
The id is stored on the proposal row immediately after the ingest and before the commit, so
the resumed run cites it rather than re-deriving it.

An Owner who supplied a `statement_ref` at plan time already spoke: the record cites THAT
source and nothing is ingested. Either way the ref is CHECKED — at `plan`, and again at
execution — to be this user's, to be an `owner_dialogue` source, and to have a block 0
(`422`/`statement_unknown`, `statement_not_owner`); a note given beside a statement that says
something else is refused rather than silently resolved (`statement_mismatch`). The statement
and the record say the same sentence, because a record quoting something its cited source does
not say would be a fabrication with a citation on it.

**The channel's gate** (`archive/record.py: run_archive_record_gate`) hard-rejects, and any
violation writes nothing at all: the anchors are the system-assigned ones for `(path, slot)`
and none is taken anywhere in the repository; the third block cites the statement; the first
block carries every grounding reference the definition rested on AND rests on something at
all (the one exemption above); no block's text carries the system's own machinery, judged by
the compile gate's own predicate; every machine key is present, `archive_of` names the full
copy, and each stated number equals the one the second block says in words — read in BOTH
directions, the keys against the facts this render was made from and then the second block
PARSED off the page and required to be the line those keys produce, because `FACTS_EXEMPT` is
a promise about what stands on the page and a body written from anything but that object is
exactly the page it has to hold for; the record's `doc_id` IS the one this channel derives
for the path (`record_doc_id`) and is taken by no other document in the tree — the derivation
check is what makes the collision check mean anything, since an id from anywhere else may be
the very one the archived copy is carrying; and the copy under `archive/` is byte-identical
to the page that stood at the live path — archiving is a move, never a rewrite.

**At the compile boundary** a record is READ-ONLY. Every write verb refuses it at the tool
face and the gate refuses any diff on it, both under the `archived_path` kind with the
record's own message ("this subject is archived; its record is read-only; the owner restores
it by unarchiving"), and both are collected as `archive_refusals` under the code `record`.
It IS listed in the outline, with a line stating what it is, and `read_document` returns it
under a read-only notice — because that is how a round learns the subject is *retired*
rather than absent, which is the whole reason the record is not simply hidden.
`list_documents` lists it. The record and the full copy are two documents with two ids, so
`read(user, doc_id)` stays a question with one answer. Path shadowing is now implied by the
record's existence (the live path is occupied); the title-shadow rule still holds for other slugs, so a subject refused at
its own path is not rebuilt at the next free one.

**On the glance** the record is an ordinary live page, with one tail marker — the same
`archived` label an item admitted from the archive carries, read off the document rather
than asked for by the call — so a reader deciding what to open sees that this page is a
record rather than the subject itself.

**Unarchiving replaces the record with the page it stood in for**: `git rm <path>` plus
`git mv archive/<path> <path>` in one commit, volumes included. The record's anchors RETIRE
with it, for the same reason an overview region's do — they carry no permanent identity, and
the page whose identity they stood in for is back. The projection's loss guardrail is told
so: the job passes `retired_anchors` to `sync_projection`, the second and narrow exemption
beside the overview's, DECLARED by the channel that retired them rather than inferred
(anything else that vanished is still loss and still refuses). A job RESUMING after its move
commit already landed reads those anchors out of the tree at `library_ref`: the records are
gone from HEAD and gone from the new claim set, so the plan-time tree is the only place left
that holds them, and without that read the one step still to run would be the one that
refuses. No new statement is ingested: the Owner is undoing a decision, not making a second
one.

## 3. Store by store: the requirement and the implementation

| Store | What carries the state | Default read | Written by |
|---|---|---|---|
| Canonical (git library) | the path itself: `archive/<path>` | live tree only (`live_documents`) | `move_documents`, one commit |
| L0 (Postgres `sources`) | `archived_at timestamptz`, NULL = live | `list_sources_page`: `archived_at IS NULL` | `set_source_archived` |
| L1 blocks (Meilisearch `blocks_<uid>`) | `archived: bool` on every block document | `NOT archived = true` | `index_blocks`; flipped by `update_documents` |
| L2 chunks (Qdrant, `layer=chunk`) | `archived: bool` in the payload | `must_not archived = true` | `upsert_chunks`; flipped by `set_payload` |
| L3 claims (Meili `claims_<uid>` + Qdrant `layer=claim` + PG `canonical_claims`) | `archived: bool`, derived from `document_path` | the same two filters | the claim projection |
| Component projections (`time`, `people`, `attention`) | nothing — no field at all | the READ joins, subtracts or pins against the live set | rebuilt from L0 as before (I7) |
| Kept records (`archive_proposals`, the owner statement) | the decision itself, not a derived flag | — | the API and the archive job |

Each subsection states the same four things: the **requirement** and the invariant it
serves, the **implementation** that meets it, how **legacy data** written before the mark
existed behaves, and the test that **verifies** it.

### 3.1 Canonical — the git library

**Requirement.** The path is the authoritative mark (I2), so the move must be a move: byte
for byte, history intact, one commit, and never a partial tree. Nothing under `archive/`
may change afterwards, and the vacated live path must not be re-occupied by a rewrite.

**Implementation.** `CanonicalStore.move_documents` takes moves, writes and removals and
commits them as ONE commit with the ordinary skill trailer plus `Archive-Proposal: <id>`.
Archiving is moves + writes (the page to `archive/<path>`, the record onto the live path the
move just vacated); unarchiving is removals + moves (the record out, the page back). The
verb applies removals, then moves, then writes — the one order in which both directions
express themselves with no intermediate state on disk — and refuses a write onto a path that
survives both. `git mv` keeps `git log --follow` reading straight through, and frontmatter,
body, anchors and `doc_id` are untouched. Every refusal is decided in a preflight that
SIMULATES the whole sequence over an overlay, before the first rename; a failure part-way
undoes exactly the renames, writes and removals this call made, in reverse, and never resets
the tree. A write is recorded as this call's the moment the file is on disk, BEFORE its
`git add` — an `add` that failed with the record made after it would leave the rollback's one
authority silent about the only file this call could have written, and the next writer's
`add -A` would commit it under an unrelated message. The queue is not the only writer — the skill manifest is written from the API
process, off it — so the adapter holds one advisory lock per repository
(`.git/pneuma.lock`) for the whole of every mutating sequence; a multi-host deployment is
outside what a file lock can serialize and is a known residual. Under that lock a dirty tree
at the ENTRY of a mutating method has exactly one explanation — a dead writer's residue — so
it is RECOVERED there (`reset --hard HEAD` + `clean -fd`, never touching `.git`, every path
logged at WARNING) rather than refused: `commit_patch` stages with `add -A`, so a crashed
archive's staged renames would otherwise ride into the next unrelated compile's commit.
After the commit, and outside the rollback's reach, the directories the move drained are
pruned. Three gate rules keep the tree that way, all mechanical and all under the kind
`archived_path`:

- **Nothing under `archive/` changes in a compile.** A round whose draft differs from base
  on any archived path is refused — the same shape as check 5b for closed volumes.
- **An archived path shadows its live path.** While `archive/work/products/aurora.md` exists,
  `create_document("work/products/aurora.md")` is refused at the tool face and at the gate:
  the document has an id derived from its path, and two documents with one id is the one
  thing a move must never produce. The subject comes back by unarchiving, not by rewriting.
- **An archived title shadows its subject.** A path is cheap to change, and a model refused
  at the shadowed path will pick another slug and rebuild the subject live under the same
  name — observed on the reference corpus: `threads/small-group-invitation.md` archived,
  `threads/small-scale-invitation.md` created with the identical title. So a new document
  whose normalized title (NFKC, casefold, whitespace and a fixed set of separator and
  terminal punctuation removed — symbols such as `#`, `&`, `+` stay, so `C#` and `C` are two
  subjects) equals an archived document's title is refused too, at the tool face and at the
  gate, and the refusal names the two legal moves: record a genuinely new fact on the live
  page it belongs to, or leave it — the owner restores the subject by unarchiving. Equality,
  not similarity: a paraphrased title escapes the rule by construction, which is why the
  refusal is also a **signal** — every archived-path or archived-title refusal a round hit is
  collected on the compile result as `archive_refusals` and written into the job's completion
  detail, so the owner can see that new material is touching an archived subject and decide.

The compile model never sees the archive. `PatchDraft` still holds every document — anchor
continuity and repository-wide uniqueness are judged over the whole tree — but the outline
rendered into the task, `list_documents` and `read_document` are over live documents only,
and a read of an archived path answers with the refusal rather than the text. Groom skips
archived documents. Evolve enumerates live documents only and leaves `archive/` exactly as
it found it on the branch.

**Legacy data.** There is none to migrate: the state is the tree, read fresh on every list,
and a library with no `archive/` directory is a library with nothing archived. What predates
the RECORD is handled by name — an unarchive removes only a path that actually holds one
(`_record_removals`), so a page archived before records existed comes back with nothing
removed, and a proposal planned then ingests no statement.

**Verified by** `packages/pneuma-knowledge-service/tests/integration/test_git_canonical.py`
(the move with its volumes and its history, the record written onto the vacated path, the
unarchive as one commit, the scoped rollbacks, the residue recovery, the manifest write and
the move not absorbing each other), `packages/pneuma-knowledge-core/tests/test_archive_gate.py`
(the three `archived_path` rules) and
`packages/pneuma-knowledge-service/tests/test_archive_other_writers.py` (groom, evolve and
adopt leaving the archive alone).

### 3.2 L0 — Postgres `sources`

**Requirement.** L0 is the verbatim record and its reachability is unconditional (I3), so
the mark may change a LISTING and a search face but never an address. And it must be the
authority every derived flag is re-derived from (I2).

**Implementation.** One nullable column, `archived_at timestamptz` — NULL is live, a
timestamp is the day the Owner retired the material. `PostgresStore.set_source_archived`
sets or clears it and returns what the row now holds; `archived_source_ids` reads this
user's archived ids in one query, which is the read every retrieval's assembly filter makes
once (§3.9). Reachability is unconditional exactly where the invariant says: `get` returns
an archived source like any other (`RawSource.archived_at` carries the value), `fetch`
resolves a locator to its block interval with no predicate at all, and `list` — the
authority's own enumeration — hides nothing and lets its reader filter. The face that
defaults to excluding is the paginated LISTING: `list_sources_page` appends
`archived_at IS NULL` unless `include_archived=True`, and either way every returned row
carries `archived_at` so a caller can label what it shows. One more predicate is not about
reading but about writing: `undigested_source_ids` excludes `archived_at IS NOT NULL`, so an
archived source that was never compiled is not offered to `POST /compile` again — the Owner
has said the material is not current, and compiling it would write live claims about an
archived subject. A snapshot tenant copies the column with the row (`copy_tenant`), so a
frozen tenant holds the archive state its source library had; the `archive_proposals` rows
are deliberately not copied, because a frozen tenant refuses every write and a proposal
there could never be confirmed.

**Legacy data.** The column is added by `ALTER TABLE sources ADD COLUMN IF NOT EXISTS`
(the schema file is the migration), so every row written before it existed reads NULL, which
is live. Nothing has to be backfilled and no rebuild is required for a source to keep
answering exactly as it did.

**Verified by** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`
(`test_the_l0_mark_round_trips_and_leaves_reachability_alone`,
`test_the_listing_excludes_the_archive_unless_the_call_says_otherwise`,
`test_an_archived_source_is_not_offered_to_compile_again`).

### 3.3 L1 — the Meilisearch blocks index

**Requirement.** Indexing stays unconditional (I3): an archived source is indexed like any
other and needs no re-index to come back. What changes is the default SEARCH, and it has to
change at the index — a filter applied after the fact would let the archive spend the
candidate cap first.

**Implementation.** Every block document carries `archived: bool`, written by `index_blocks`
from the L0 mark the caller passes. `set_source_archived` flips one source without
re-indexing its text: a PARTIAL `update_documents` over the deterministic
`{source_id}_{block_index}` ids, one request, and it cannot disturb the verbatim text it does
not mention (the caller passes the block count, because L0 is the authority on how many
blocks a source has and this index is derived). `search` passes
`filter="NOT archived = true"` unless the call says `include_archived`. The expression is
`NOT … = true` and not `= false` on purpose, verified empirically against Meilisearch v1.11:
a document carrying NO `archived` attribute is RETURNED by `NOT archived = true`, and
DROPPED by `archived = false`. `filterable_attributes` is what makes the filter legal at all
— Meilisearch refuses a filter on an unconfigured attribute rather than ignoring it — so
`blocks_<uid>` declares `["archived", "source_id"]`, `source_id` beside the flag so a flip
can be addressed by source. Because a process that only ever SEARCHES (the API, while the
worker owns indexing) would otherwise filter against whatever settings the index happened to
be created with, the read path calls `_configure_for_read`: it probes existence first, so a
search never CREATES an index, then applies the settings to an index it finds. And exactly
one API error means absence — `index_not_found`. Every other error propagates, because
`except MeilisearchApiError: return []` would read an auth failure or a connection reset as
"this user has nothing indexed" and answer as if the library held no lexical material.

**Legacy data.** Documents written before the attribute existed read as LIVE under the
filter, so a deployment that has not yet rebuilt its derived layer keeps answering exactly as
it did; and an index created by an older build gets the current settings applied the first
time this process reads it.

**Verified by** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`
(`test_meili_default_search_keeps_legacy_documents_and_drops_the_archive`,
`test_meili_flips_one_source_without_touching_its_text`,
`test_a_search_only_process_configures_an_index_an_older_build_created`).

### 3.4 L2 — the Qdrant chunk layer

**Requirement.** Same as L1: the state rides the point, the default search excludes it at
the index, and an archive is a change of attention rather than of content — nothing may be
re-embedded to express it.

**Implementation.** `upsert_chunks` writes `archived` into the payload from the L0 mark.
`set_source_archived` merges the one key with `set_payload` over a selector that is the
tenant clause (I1) plus `source_id`, minus `layer = claim`: a claim's archive state is a
property of its DOCUMENT's path and is written by the projection, so a source-addressed flip
must not reach a claim point even when a claim in the same tenant cites that source. The
vectors, the verbatim text and the char spans are untouched. Both searches exclude with
`must_not archived = true` — the same shape as the existing `must_not layer = claim` clause,
and for the same reason. Every field a filter here names is a declared payload index —
`user_id`, `source_id`, `archived`, `layer` — and `ensure_collection` declares them on an
EXISTING collection too, not only a new one: a deployment that already holds one predates
every index added since it was created, and an early return would mean the collection that
most needs the index is the one that never gets it. `create_payload_index` is idempotent, so
re-declaring costs one no-op call per boot.

**Legacy data.** A point written before the field existed carries no `archived` key, does
not match the condition, and therefore stays LIVE — which is why the clause is `must_not …
= true` and not a positive `must archived = false`.

**Verified by** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`
(`test_qdrant_archives_one_source_of_a_tenant_and_brings_it_back`,
`test_qdrant_points_written_before_the_flag_existed_read_as_live`,
`test_ensure_collection_declares_payload_indexes_on_an_existing_collection`).

### 3.5 L3 — the claim projection

**Requirement.** A claim is archived iff its PAGE is, so the flag must be derived from the
document path and from nothing else (I2) — and a MOVE must not read as knowledge loss to the
projection's own guardrail.

**Implementation.** `project_snapshot_claims` sets `archived = is_archived_path(doc.path)`
on every claim of a document under `archive/`; the flag then rides one row into all three
faces of L3 — PG `canonical_claims.archived`, the Meilisearch `claims_<uid>` document, and
the Qdrant `layer=claim` payload — each filtered by the store's own clause from §3.3 and
§3.4. The projection needs nothing new to notice a move: its key is `(document_path,
anchor)`, so an archived page's claims are deleted under the old key and upserted under the
new one on the ordinary incremental sync after the archive commit. The loss guardrail counts
ANCHORS rather than keys (`_lost_anchors`), and an anchor is repo-unique and survives the
move, so archiving a library's biggest document loses nothing and is not refused — the same
property that makes a rollover safe. `archived` is a field of BOTH signature functions
(`_claim_signature` / `_row_signature`), which is what makes a sync that flips only the flag
reach the indexes instead of reporting "unchanged". The one narrow exemption is
`retired_anchors`: an unarchive removes the record whose three blocks carried no permanent
identity, so the archive job DECLARES those anchors to `sync_projection` rather than the
function inferring them — anything else that vanished is still loss and still refuses.
`claims_<uid>` declares `document_path` filterable beside `archived`, so the archive's unit —
a page — is addressable here the way a source is addressable in the blocks index.

**Legacy data.** `canonical_claims.archived` is an additive `ADD COLUMN IF NOT EXISTS …
NOT NULL DEFAULT false`, and `_row_signature` reads a missing value as `False`, so rows
written before the archive existed read as live and a rebuild re-derives the truth from the
path.

**Verified by** `packages/pneuma-knowledge-service/tests/test_projection_sync.py`
(`test_archiving_a_page_re_keys_its_claims_and_is_not_a_loss`,
`test_a_flag_flip_alone_still_reaches_the_indexes`) and
`tests/integration/test_archive_marks.py`
(`test_meili_claims_exclude_the_archive_by_default`,
`test_qdrant_claim_layer_excludes_the_archive_by_default`).

### 3.6 Component projections — `time`, `people`, `attention`

**Requirement.** No component learns that the archive exists and none is given
`include_archived` (I7); its projection stays derived from all of L0 and rebuildable from
the substrate it declares (I2). But a component face returns PROSE — verbatim block text,
identities, document lines — which the framework's assembly filter cannot redact after the
fact. So each face must read only what the library still shows, and the exclusion has to
happen one level down, at the read.

**Implementation.** Three shapes, one rule.

- **`time`.** The projection row has a `source_id`, so the exclusion is a join:
  `time_blocks_in_range` selects `LEFT JOIN sources … AND s.archived_at IS NULL`. The rows
  themselves keep every source and are rebuilt from all of L0 — the archive is a property of
  the read, not of the rows. (`LEFT JOIN` plus `IS NULL` also keeps a projected block whose
  source row is gone, exactly as before.)
- **`people`.** `enumerate_identities` is a closed-world enumeration over live sources. The
  address-term table is the one place it costs arithmetic: `component_people_terms` is an
  ACCUMULATION, one row per `(term → target)` pair for the whole library, so it carries no
  source column to join on and its primary key is the pair. But what built it is addition,
  and addition is invertible: the archived sources' contribution is recomputed from L0 by
  the same pure `term_rows` the write path uses, and SUBTRACTED at every read
  (`subtract_term_rows`). That is exact only because the accumulation is at-most-once per
  source — `component_people_indexed` is the manifest, claimed `ON CONFLICT DO NOTHING` in
  the same transaction as the counts, and a source added twice would leave half of itself in
  every read that excludes it. A pair the archive accounted for entirely is DROPPED rather
  than zeroed, and comes back whole on unarchive; counts are clamped at zero rather than
  trusted. The archived set is read once per call and the recomputation is held until the id
  set itself changes.
- **`attention`.** A ledger row is a fact about a past consultation and outlives the page it
  names, so both faces are pinned to the documents they were handed — the deep tool through
  `recall_tools(..., documents=)`, the fast path through `run(..., documents=)`, and a call
  handed none reads the LIVE tree off the read-only canonical face. A handed set is filtered
  again, because the rule is a property of the face and not of its caller. A target that set
  does not contain is DROPPED, not annotated: this block is read by an evolve round and by an
  agentic lane, and a path neither can open is not evidence either can act on.

In all three, the failure mode of a broken read is named rather than swallowed: a store that
raises while building its archived-id set must not be indistinguishable from one with
nothing to build, so only the ABSENCE of the method — decided by introspection — reads as
"no archive".

**Legacy data.** None of these projections gains a field, so there is nothing to migrate and
nothing to backfill; each is rebuilt from L0 (and, for a use-side projection, from the kept
consultation records) by the same `rebuild_derived` as before. The `attention` pin is the one
rule here that is NOT a no-op on an untouched library — a ledger row can name a page a later
compile deleted or renamed — so it turns on only once the FULL tree holds an archived
document (`any_archived`), and until then the report is byte-for-byte the one it always was.

**Verified by** `packages/pneuma-knowledge-service/tests/integration/test_component_time_pg.py`
(`test_deep_timeline_excludes_archived_source_blocks`),
`tests/integration/test_component_people_pg.py`
(`test_enumerate_identities_excludes_archived_sources`,
`test_a_term_only_archived_sources_support_is_no_longer_reported`,
`test_archiving_one_of_a_terms_sources_leaves_the_rest_of_its_support`) and
`tests/test_attention_component.py`
(`test_the_report_names_no_page_that_is_in_the_archive`,
`test_with_nothing_archived_the_report_is_byte_for_byte_the_one_it_always_was`).

### 3.7 Kept records — the proposal and the owner's statement

**Requirement.** What the Owner proposed, against which library state, and what they decided
is a KEPT record (I2): a rebuild replays it and never rewrites it, and nothing recomputes a
decision that was already answered. The decision and the job that executes it must never
exist without each other.

**Implementation.** `archive_proposals(user_id, proposal_id, action, seeds, items,
library_ref, status, note, statement_ref, created_at, confirmed_at, executed_at, job_id,
detail)`, keyed `(user_id, proposal_id)` and listed newest-first per user. `seeds` and
`items` are jsonb because their shape is the planner's, not the storage layer's;
`library_ref` is the canonical HEAD the plan was computed against. The lifecycle is
`proposed → confirmed → executed | failed`, with `dropped` and `stale` beside it, and every
transition is a predicated write: `confirm_archive_proposal` flips the row and inserts the
job in ONE transaction under `status = 'proposed'`, minting the job id once and writing it
into both rows; the job's terminal write is guarded by `status = 'confirmed'`. `stale` is
COMPUTED at read (`library_ref != HEAD`) rather than swept, and only ever WRITTEN by the
confirm that refuses `409 stale` — see §5, which states the whole lifecycle and why.

The Owner's statement is the second kept thing, and it is an ordinary source rather than a
row: one `owner-dialogue/v1` contract per proposal, one owner turn, ingested through the
ordinary `ingest_source_contract` path with `dialogue_id = proposal_id` so the statement and
the decision address each other in the one scheme. Every field of that contract is a function
of the proposal, `said_at` included (the row's `confirmed_at`), so the contract is the same
bytes on a retry and the checksum dedup returns the same source id — the statement is a kept
thing that a crash cannot duplicate. The single override is the intake plan
(`STATEMENT_INTAKE`): `canonical_treatment: none`, because the record already IS that
statement's canonical expression and a compile of the same text would paraphrase the decision
onto whatever pages the model believed it touched; `semantic_indexing: full`, because the
statement is L0 like any other L0 — searchable, addressable, quotable.

**Legacy data.** A proposal planned before records existed carries no `record` field on its
items; the job then writes no record and, guarded on there being a record to write, ingests
no statement — a statement nothing cites would be L0 the Owner never asked for. The same
guard covers a sources-only proposal, which is not legacy but the same shape.

**Verified by** `packages/pneuma-knowledge-service/tests/integration/test_archive_marks.py`
(`test_archive_proposals_are_kept_and_advance_without_losing_earlier_stages`,
`test_the_lifecycle_predicate_lets_exactly_one_writer_win`,
`test_the_confirm_writes_the_decision_and_its_job_in_one_transaction`,
`test_a_confirm_that_loses_the_predicate_queues_nothing_at_all`) and
`packages/pneuma-knowledge-service/tests/test_archive_job.py`.

### 3.8 Rebuild

**Requirement.** Every archive flag in every derived store is derived, so
`scripts/ops/rebuild_derived.py` must recover all of it from the two authoritative marks
alone (I2) — and a rebuild of a library whose archive has not changed must not change what
that library answers.

**Implementation.** L1 replays the mark from L0: the script drops the user's lexical index
and calls `index_blocks(..., archived=raw.archived_at is not None)` per source, and reports
how many were archived. L2 does the same on `upsert_chunks`, over chunks the semantic
strategy replays from the stored chunk manifest, so the L2 rebuild is byte-deterministic.
L3 needs nothing extra at all — `rebuild_projection` re-projects canonical HEAD and each
claim's `archived` is read off its document's path. The component projections are re-derived
in the same pass, as one `recall_rebuild` job drained by the script so it cannot interleave
with that user's in-flight `recall_projection` jobs.

Measured on the OPC library during the archive validation run, over two archived documents:
after `rebuild_derived`, the flags came back re-derived on every store — 29 archived Qdrant
points, 27 archived Meilisearch block documents, 15 archived claim documents, and the
`canonical_claims` rows for both archived pages. The same rag query before and after the
rebuild returned the same 20 hits, the same `(source_id, block_start, block_end)` on each and
in the same ORDER; the only difference anywhere was three RRF scores moving in the fourth
decimal place, a rank shift inside a single lane that the fusion absorbed. The default lane
returned no archived hit either time.

**Legacy data.** This IS the answer to legacy data everywhere else on this page: a
deployment whose stores predate the archive keeps answering correctly because every filter
reads a missing flag as live (§3.3, §3.4, §3.5), and one `rebuild_derived` replaces "reads as
live" with the flag actually derived from the two marks.

**Verified by** the per-store replays above (§3.2–§3.5), by
`packages/pneuma-knowledge-service/tests/test_rebuild_derived_reachability.py` for the
component pass reaching every tenant through the queue, and by
`tests/integration/test_archive_e2e.py`
(`test_one_confirmed_proposal_moves_a_subject_out_of_every_default_face`), which re-projects
and then re-reads every default face against live middleware. The script itself is an
operator command and is exercised end to end by a validation run rather than by a test.

### 3.9 The core post-filter, and the switch that keeps it off

**One post-filter in core, beside the index filters.** Retrieval is not only the two
indexes: a routed component path (`timespan`, `person`) reads its own projection and L0,
and a briefing pack is built once from whatever it was handed. So the lanes also apply one
model-free filter at evidence assembly, over the two authoritative facts they already hold —
the archived source ids (`ContentStore.archived_source_ids`) and the `archive/` prefix on
the documents they were given. A claim on an archived page, a window or span from an
archived source, a component result pointing at either, is dropped there and counted, the
way `hide_already_shown` counts. The index filters make the common case cheap; the
assembly filter makes the property hold wherever evidence comes from, including a component
written before the archive existed.

The same filter carries one more mechanical check: a claim whose `document_path` is not in
the document set the lane was handed is dropped too, and counted under the same
`archive_hidden` figure. This closes the window between the archive commit and the L3 sync
that follows it — the moved page's rows still carry the old live path until the sync lands,
and if the sync fails they carry it indefinitely — because a page the lane cannot see is not
evidence the lane can show. Two lanes carry no document set at all and skip the check: rag,
which returns hits rather than an answer over pages, and a briefing's `ask` over a stored
pack. The answering lanes are always handed one, and when canonical cannot be read they
REFUSE (`503 canonical_unavailable`) rather than answer unpinned; live context skips the
tick for the same reason (`canonical_unavailable`).

**The two empties are not the same, and reading them as one fails open.** *No document set*
is None and pins nothing. An *empty* document set is a set, and it says the answering library
holds no page the lane may show — so it pins to nothing, and every claim the index proposes
is dropped. That is the correct reading of the state the Owner creates by archiving the last
live page: the authoritative answer is "nothing", while every L3 row still carrying an old
live path is stale by construction. The service therefore ALWAYS hands the answering lanes a
set: `_glance_inputs` returns the live document list however short it is.

**And a read that FAILED is neither empty — it is no answer at all.** Once the document set
is the pin, a lane handed none because git was busy admits every stale row, which is the
outcome the check exists to prevent — so the failure is not degraded, it is refused. The
canonical read is the one part of `_glance_inputs` that is not advisory: it raises
`CanonicalUnavailable` and both `POST /recall` and `/recall/stream` answer
`503 {"detail": …, "code": "canonical_unavailable"}` (the stream reads canonical before the
response opens, so an unreadable library is a status code there too, not an `error` frame
narrated over a 200), as does a briefing build over a library it cannot read. Live context
makes the same refusal in its own currency: the tick skips with `canonical_unavailable`
instead of retrieving, and the room is quiet for one turn. What stays fail-soft is only the
rest of the glance — a skill or a pack that fails to load degrades the glance and the
documents still reach the lane. In production the pin is always on, or the lane did not run.

**And the whole filter — the pin included — is INERT while the archive is empty.** Every
other check here is already a no-op in a library that has never archived anything: no source
is in an empty set of archived ids, and no path starts with `archive/` in a tree that has no
`archive/`. The pin was the exception, and a real one — it drops a claim whose page the
lane's document set does not hold, which happens with no archive anywhere in sight: a compile
landing while the answer is being assembled, or an index searched live under a past-version
`at=` pin. But the pin exists to close one window, between an archive commit and the L3 sync
behind it, and a library with no archived source and no archived document has never opened
it. So the filter carries a switch: the pin runs only on an ACTIVE view, and a view is active
once there is an archived source (`ContentStore.archived_source_ids`) or an archived document
(read off the FULL tree by `_glance_inputs`, which is the one read that sees it, and handed
to each lane as `archive_active`). This is the same discipline index components hold to —
unregistered means nonexistent — and it is what lets the Owner run the same questions before
and after this feature, with nothing archived, and see no difference at all.

**Verified by** `packages/pneuma-knowledge-core/tests/test_archive_recall.py`
(the drops and the labels on every lane, the component faces, the two empties, the broken
store, and `test_with_an_empty_archive_the_pin_is_off_on_every_lane` /
`test_the_pin_turns_on_with_the_first_archived_document_or_source`) and
`packages/pneuma-knowledge-service/tests/test_archive_recall_routes.py`.

## 4. `include_archived`

One boolean, default `false`, on every request that reads:

| Surface | Where | Off (default) | On |
|---|---|---|---|
| `POST /recall` (rag · fast · deep), `/recall/stream` | `RecallIn.include_archived` | archive excluded at index and assembly; glance over live documents | archived claims, windows, derived episode summaries and glance entries admitted, each labelled `archived` |
| `POST /briefings` | `BriefingBuildIn.include_archived`, stored in the scope | pack built over live only | archived admitted and labelled; `ask` inherits the pack's choice |
| Live context | — | always excluded | not offered: nobody asked a question here, and a room is never served the past by default |
| `GET /sources` | query `include_archived` | archived sources omitted; `SourceOut.archived_at` present on every row | included |
| `GET /dataset` | — | every document, with `archived: bool` on the record | the console decides how to show the archive |
| Component deep tools / fast paths | — | live sources only | not offered |
| Compile · groom · evolve | — | live documents only | not offered |
| The archive RECORD (§2.3) | — | **always included** — it is a live page | n/a |

The last row is the one exception worth stating in a table about exclusion: the record is
not in the archive, it is what STANDS IN FOR the archive on the live side. No lane filters
it, no call has to ask for it, and the `archived` label it carries is a label on live
knowledge — "this subject is retired" — not the label an admitted archived item wears.

The label is the `superseded` discipline applied again ([architecture §7](../architecture.md#7-retrieval)):
an item the lane admits from the archive is placed after the live ones and carries the
`archived` label into the prompt and onto the wire, so a model that was handed history
knows it, and a reader of the answer can see which is which.

**On the wire the mark has one name on every face.** A window and an episode summary carry
`archived: bool`; an admitted claim carries the same field beside its `labels`
(`UsedClaimOut.archived`, derived from the label and never re-derived from the path). The
three faces arrive in one response and a client that had to read the claim's differently
would end up parsing the `archive/` prefix itself — a second implementation of the one rule
this section exists to state once.

## 5. The proposal

`POST /archive/proposals` takes the Owner's seeds and returns the computed set:

```json
{
  "action": "archive",
  "documents": ["work/products/aurora.md"],
  "sources": [],
  "note": "Aurora shipped in June; the team is disbanded.",
  "statement_ref": "src_…"
}
```

`statement_ref` is optional and names the `owner-dialogue/v1` source in which the Owner
asked for this — the proposal's provenance in the one scheme, when the request came through
the Steward rather than the console.

The planner (`archive/proposal.py`, pure core) reads the whole canonical tree once, parses
every claim's citations, and computes the closure:

- **From a document.** Every source its claims cite is a candidate. A source cited by no
  live document outside the selected set is **selected**; a source some other live document
  still cites is **listed but not selected**, with those documents named.
- **From a source.** Every live document citing it is a candidate, with its **dependence**:
  claims citing selected sources over all ledger claims (overview blocks excluded). A
  document at dependence `1.0` is selected; a lower one is listed with the ratio.
- The two rules run to a fixed point over the selected set, so a document that becomes
  fully dependent once its second source is selected is caught. The set only grows, so the
  computation terminates, and it is deterministic — the same tree and the same seeds
  produce the same proposal byte for byte.
- A document's closed volumes are part of its item, never items of their own.
- `unarchive` mirrors it: an archived document's archived sources are candidates and
  selected; a source's archived documents are candidates, selected when every source they
  cite would be live after the move.

Every item carries `kind` (`document` / `source`), `ref`, `title`, `role` (`seed` /
`cascade`), `selected`, and a structured `reason` (`cited_by_live: [...]`,
`cited_by_archived: [...]`, `dependence: {cited, total}`, `note`), so the console can render
the reason beside the checkbox and a Steward can read it.

**The two `cited_by_*` fields are one field per side of the library, and the split is not
cosmetic.** `cited_by_live` answers "which LIVE pages would lose this source" — the archive
direction's question, and the reason a `still_cited` source is listed unselected.
`cited_by_archived` answers "which ARCHIVED pages bring this source back with them" — the
unarchive direction's, under its own note `restored_with_page`. One field carrying both would
be a list of paths whose meaning depends on the action, and a reader deciding whether to
untick a box would be reading `archive/…` paths under a name that says live. The `note`
vocabulary is therefore: `seed`, `orphaned`, `still_cited`, `restored_with_page`,
`fully_dependent`, `partially_dependent`, `already_archived` / `already_live` (a seed already
in the state the action would put it in — listed, never selected), and `unknown`.

A DOCUMENT item of an `archive` proposal carries one more field: `record`
(`{title, definition, span: [from, to] | null, claims, sources, volumes, inbound, reason}`) —
what the archive record for that page will say (§2.3), computed here so the console can
preview the page each checkbox creates before anything moves. `reason` is the exact line the
record's third block will quote (the note, the block 0 of a supplied `statement_ref`, or the
default sentence): the one part of the page that is a fact about the DECISION rather than
about the document, so it is decided at this layer and moves with the note when a confirm
replaces it. The job QUOTES this kept line rather than recomputing one from the note, so the
sentence the Owner confirmed and the sentence on the page are one string by construction. The planner takes one extra input for
it, `source_occurrence: Mapping[source_id, occurred_on]`, which the service supplies off the
source inventory: the day a source is ABOUT belongs to L0, and a pure planner derives nothing
date-shaped of its own. `inbound` excludes the pages this plan is itself moving — a link from
a page that is leaving too is not a link the record is left holding — which also makes the
number stable under the one override a confirm allows.

These numbers are a PREVIEW. `library_ref` pins the tree the plan was computed over and a
confirm against any other is refused, so nothing derived from a page can drift — but it says
nothing about the SET, and the one override a confirm allows changes it: unticking a page that
another selected page links to turns that page's `inbound` from "a link that is leaving too"
into "a link this record is left holding". So the job recomputes every fact at execution over
the final selected set, through the same pure function this preview came from
(`record_facts_in_move`) — one definition, two callers, and the page states what was true of
the tree the commit is about to change. An `unarchive` item carries no `record`: it REPLACES
the record with the page the record stood in for.

The proposal is **kept**: `archive_proposals(user_id, proposal_id, action, seeds, items,
library_ref, status, note, statement_ref, created_at, confirmed_at, executed_at, job_id,
detail)`. `library_ref` is the canonical HEAD the plan was computed against.

`POST /archive/proposals/{id}/confirm` optionally overrides `selected` per item — to leave a
selected item where it is — and enqueues one `archive` job. Adding an item the plan listed
but did not select is done by re-planning with it as a seed, so its own cascade is computed
rather than skipped; the console does exactly that when a checkbox is ticked. It refuses (`409 stale`) when HEAD has moved since the plan — a preview of
a library that has since compiled is a preview of something else, and the Owner re-plans.

**The decision and the job it queues are ONE TRANSACTION**, under the predicate `status =
'proposed'` (`PostgresStore.confirm_archive_proposal`). That settles two things at once. The
predicate decides the transition — two confirms, or a confirm and a drop, have exactly one
winner rather than two jobs for one move, because the read above the write cannot tell them
apart. And the two halves cannot exist alone: never a `confirmed` proposal with no job (a
decision nothing executes and nothing reports — invisible rather than stuck), never a job
for a decision nobody made. The job id is minted once and written into both rows, so nothing
has to attach it afterwards and no worker can finish inside the gap that second write would
open. A failure rolls both back, which is why there is no compensation path and no refusal
code for one: it is an ordinary 500 over a proposal that is still open.

A confirm's `note` has three states and they are stored as three: ABSENT (`None`) says
nothing about it and the plan-time note stays; GIVEN replaces it; and GIVEN AS EMPTY clears
it, storing NULL on purpose. The store takes a `note_given` flag beside the value for exactly
that reason — `COALESCE` cannot spell the difference between silence and an erasure, and
reading the second as the first left the preview computed with the default sentence while the
row still held the old note for the record to quote.

A note and a `statement_ref` are checked where they are typed. A note carrying the system's
own machinery is `422 note_machinery`; a `statement_ref` this library does not hold, or one
that is not an `owner-dialogue/v1` source with a block to quote, is `422 statement_unknown` /
`422 statement_not_owner`; a note that says something other than the named statement's block
0 is `422 statement_mismatch`, because the record quotes the source it cites and picking one
of the two silently would be the framework deciding what the Owner meant. All four are made
at `plan` and again at `confirm`, and again in the job — the request and the execution are
separated by a queue.

`POST /archive/proposals/{id}/drop` closes one unexecuted. `GET /archive` lists what is in
the archive now: documents by path with the day they were archived and `record_path` plus
the facts the record states (read off its own frontmatter — nothing stores the join, because
the record's `archive_of` and the copy point at each other already), sources with
`archived_at`.

**A proposal the library outran reads as `stale`, and is COMPUTED, not swept.** `proposed`
means "still awaiting a decision", and a row previewing a HEAD the library has moved past can
never be confirmed — a listing that showed it as open would report decisions nobody can make,
and the console's own opened-and-cancelled dialogues would accumulate there forever. But
`library_ref != HEAD` is the entire definition, and every read already holds both halves of
it: so `GET /archive/proposals` and `GET /archive/proposals/{id}` present the status `stale`
over a row that still stores `proposed`. Nothing writes it on their behalf. A sweep would be
a write that races every confirm in flight to say something any reader can derive, and it
would have to guess about rows nobody has touched.

The one place it IS written is the confirm that refuses `409 stale`: that call compared
against the HEAD it refused on, so recording the refusal is a fact about a decision actually
attempted. It moves the row before it answers and returns the moved proposal in the error
body, so a console reading only the error is not left holding a `proposed` copy. Either
spelling — the stored `stale` or the computed one — is confirmable by nothing and droppable
by the Owner, which is the whole of what is left to do with it.

## 6. Execution

The `archive` job runs on the per-user queue like every canonical writer, so it never races
a compile (single in-flight job per user is the single-writer guarantee). It re-checks
`library_ref` against HEAD and fails `stale` rather than moving against a tree the Owner did
not see — unless this proposal's OWN move commit is already in the history. A worker killed
between the move commit and the terminal write is requeued on restart, and the drift it then
sees is its own work; the move commit's `Archive-Proposal` trailer says so by name, so the job
records the move as `already_landed` and finishes the steps after it (every one of which is
idempotent) rather than failing `stale` over a move that is standing in the tree. The
resumption searches the RANGE since the plan's ref for the proposal's own commit rather than
reading HEAD alone, so a manifest write landing above it — `write_meta` runs in the API
process, off the queue — does not strand the job. Then, in order:

1. **The Owner's statement**, before anything moves (§2.3): one `owner-dialogue/v1` source
   per proposal, ingested through the ordinary contract path with `canonical_treatment:
   none`, and its id written onto the proposal row in the same step, before the commit — so a
   job that crashes and is requeued cites the statement it already ingested rather than
   minting a second one. That write-back is predicated on the row still being `confirmed`, and
   a LOST predicate refuses the whole job (`statement_ref_unsaved`) before anything moves:
   carrying on would commit a record citing a source the decision does not name, and the
   terminal write would lose the same predicate and say nothing about it. The contract itself is derived from the proposal, `said_at`
   included, so even the retry that gets there before the row was written re-derives the same
   bytes and the checksum dedup answers with the same source id.
   Guarded on there being a RECORD to write, and that is the whole condition: a sources-only
   proposal, or one planned before records existed, ingests none, because a statement
   nothing cites would be L0 the Owner never asked for. A statement the Owner supplied at
   plan time is cited as it stands and nothing is ingested.
2. `CanonicalStore.move_documents` — one commit moving every selected document and its
   volumes **and writing the record onto the live path the move just vacated**, with the
   ordinary skill trailer plus `Archive-Proposal: <id>`. Archiving is moves + writes;
   unarchiving is removals + moves (the record out, the page back onto its path). One commit
   either way, because the record and the move are one act: a tree in which the page has
   left and the record has not arrived is the state this whole mechanism exists to prevent.
   The verb applies removals, then moves, then writes, and refuses a write onto a path that
   survives both — the record only ever lands where the move made room for it. A failure
   part-way undoes only what this call did — the renames it made, the files it wrote, the
   files it removed — never a whole-tree reset.
   The queue is not the only writer — the skill manifest is written from the API process,
   off it — so the git adapter holds one advisory lock per repository (`.git/pneuma.lock`)
   for the whole of every mutating sequence, and a manifest write and a move can no longer
   commit each other's staged paths (a multi-host deployment is outside what a file lock
   can serialize, and is a known residual). Under that lock a dirty tree at the ENTRY of a
   mutating method has exactly one explanation — every writer commits what it wrote, and the
   lock excludes a live one — so it is a dead writer's residue, and it is RECOVERED there
   (`reset --hard` + `clean -fd`, with every path logged at WARNING) rather than refused.
   Leaving it is the worse option and not the safer one: `commit_patch` stages with
   `add -A`, so a crashed archive's staged renames would otherwise ride into the next
   unrelated compile's commit, under its message.
3. `sources.archived_at` set (or cleared) for every selected source.
4. L1 and L2 flags flipped per source; the L3 projection synced from the new HEAD — which is
   also how the record's own blocks reach the claim indexes: it is a live page, so nothing
   here has to tell the projection it is special.
5. The proposal marked `executed` with the commit ref, or `failed` with the detail — which
   still names the ref and the steps that landed, so a failure after the move commit is
   legible against the tree it produced. `archive_records_written` and
   `archive_records_removed` are stated on EVERY path, zero included and the resumed run
   included; on a resume the numbers are reconstructed from the plan-time tree and the
   confirmed set, because the commit that wrote them is already in the history.
   Both terminal writes are guarded by `status = confirmed`: anything that moved the row
   while the job ran has a claim on it that a finished job does not get to overwrite. The
   confirm needs no such guard for the job id, because the id is written in the same
   statement as the flip — there is no window in which a `confirmed` row is waiting to be
   told which job it belongs to, and therefore no way for a fast worker to be walked back
   to `confirmed` by a bookkeeping write.

A snapshot tenant (`kbsnap-` prefix) refuses the whole path, as it refuses every write.

## 7. What this touches in the invariants

- **I1** — every new port method and table is `user_id`-first; the Meilisearch filter rides
  the per-user index, the Qdrant filter is composed inside the adapter with the tenant clause.
- **I2** — the two marks are on the two authorities (a path in canonical, a column on L0);
  every index field is derived from them and `rebuild_derived` re-derives it; the proposal
  row is a kept record and is never rebuilt.
- **I3** — L0 fetch by locator and L1's *indexing* stay unconditional; what the archive
  changes is the default of a search, never reachability by address.
- **I4** — an archived claim's citations and an archived source's spans are the same
  addresses they were; a live claim citing an archived source still resolves.
- **I5** — `include_archived` changes what evidence is assembled, never the system message.
- **I7** — no component learns of the archive; the assembly filter in core is what keeps a
  component's evidence honest, and a component's projection is rebuilt as before.

## 8. Boundaries

The archive is the Owner's judgement about attention, and the framework computes only what
follows mechanically from citations. It does not guess that a subject has gone quiet — the
`attention` component reports what is unread, and an Owner or Steward reads that report and
proposes. Nothing is ever removed: a claim in the archive keeps its anchor, a source in the
archive keeps its blocks, and both keep answering when addressed by id or when a call says
`include_archived`.

And the SUBJECT keeps answering with no call saying anything: the record (§2.3) is a live
page, and it is what makes archiving a change of what the library says about a subject
rather than a hole where the subject was. What the archive removes from a default answer is
the DETAIL — every claim, every span, every hop into the material — never the fact that the
subject existed, what it was, or that the Owner retired it and why. The record is the
smallest honest thing that can stand there, and it is bounded by construction: three blocks
derived from the page, the Owner's statement and a day, with no channel that can grow it.
