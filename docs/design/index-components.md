# Index components

**English** | [简体中文](index-components.zh-CN.md)

This is the design authority for **index components** — the framework's second extension
seam. For where it sits in the system see [architecture §6](../architecture.md#6-the-compile-contract-skill)
and [§7](../architecture.md#7-retrieval); for the knobs see
[configuration](../reference/configuration.md#index-components); for the judgement a
contract author owes the `people` family see
[the compile-contract guide](../guides/compile-contract.md).

## 1. Why the seam exists

The framework holds no domain opinion, and that is deliberate: canonical is text documents
with frontmatter and anchored, cited claims, and that is all core knows. It does not know
what a person is, or a project, or a place. That neutrality is what lets one framework serve
a sales team and a research group without either inheriting the other's model.

It also has a cost, and the cost is structural rather than stylistic. Some questions are not
about *relevance* at all:

- *"Who from the supplier side has been in any conversation since March?"* is a question
  about a **closed set**. Search returns hits; a hit list has no residue, so an answer built
  from one cannot say who it missed. The set exists — it is written on every source's
  boundary, in the participant list — but nothing in L0/L1/L2/L3 indexes it as a set.
- *"What happened between June and August?"* is a question about the owner's **calendar**.
  Canonical has no calendar. Answering it from lexical or semantic search means hoping the
  word "June" appears in the text of something that happened in June.
- *"Which page is 阿宝?"* is a question about **identity**. A nickname that never appears in
  any document is nevertheless unambiguous across a library, because the turns it opens are
  answered by the same person a hundred times.

Each of these is answerable *mechanically* from material the system already holds. None of
them is answerable by better ranking. A component is the thing that indexes that material —
and it is a seam rather than a feature because *which* structure is worth indexing is a
business question, and the framework is the wrong place to answer it.

## 2. What a component is, and what it is not

**A component holds structure and pointers — identities, edges, counts, spans, each
resolving to a source span or a claim anchor — never prose knowledge. It indexes; it does
not know.**

That sentence is the whole design constraint, and every rule below follows from it.

| A component may | A component may not |
|---|---|
| derive a projection from its declared substrate — L0, canonical, kept consultation records | hold a fact that is not derivable from what it declared |
| return identities, days, counts, spans, anchors | return a summary, a judgement, or a narration |
| reject a write at the gate over its own family | write canonical, in any form (I7) |
| offer tools and lookup paths to the lanes | decide how much of what it returned a prompt sees |
| state what it observed under a source in the compile task | tell the compile model what to conclude from it |

The last two rows are the ones that are easy to get wrong, so they have their own sections
(§5 and §7).

A component is also not a *job*. The worker drains eight job kinds; a component rides the
ones that already exist (§4) — `index` and `compile` on the knowledge side,
`recall_projection` and `recall_rebuild` on the use side.

## 3. The faces

A component is a Python object satisfying the `IndexComponent` protocol
(`pneuma_knowledge_core/components/__init__.py`). Every face has a no-op default, so a
component implements only the ones it needs, and `BaseComponent` spells the defaults out
once.

| Face | When the framework calls it | What it contributes |
|---|---|---|
| `gate_checks(docs, base_docs)` | inside `run_gate`, before a draft becomes a commit | write-time rejections over the documents of its family **the round touched** (§4) — a frontmatter field unique across the library, a required shape, a value that is demonstrably somebody else's |
| `outline_tail(doc)` | rendering the compile outline | one extra line under a document of its family, so the model deciding WHERE to write sees what the component indexes |
| `validate_fields(path, fields, docs)` | inside `set_fields` and `rewrite_overview`, before a byte is written | refusal lines over the frontmatter a write is about to set — the gate's rule said early, so a fact the component can prove wrong costs one call instead of a round |
| `compile_tools(draft, sources=)` | building the compile tool face | read tools for the compile model, given the draft **and this round's sources** |
| `recall_tools(user_id, documents=)` | building deep recall's tools | tools for the agentic lane, scoped to one user (I1), over the lane's already-pinned documents. A tool may DECLARE the addresses it returned (`RECALL_EVIDENCE_KEY` under its langchain `metadata`, entries `(kind, ref, path)`) and only then do they reach the consultation record's evidence manifest — the framework cannot read addresses out of a component's own prose, so a tool that declares nothing contributes nothing and a citation copied out of its result is not admitted into the record |
| `fast_paths(user_id)` | assembling fast recall | routed lookup paths (§7) |
| `source_preamble(source)` | rendering the compile task | one mechanical line under a source: what the source *boundary* knows and the transcript cannot show |
| `prepare(user_id)` | at the head of a compile job, before any sync face renders, inside the job window (§4) | the async face of the sync seams (§4) |
| `on_source_indexed(user_id, source)` | when one source finishes L1/L2 | the projection channel's incremental write |
| `on_recall(user_id, record)` | on the WORKER, when it drains the projection job one business-classed answering-lane call enqueued | the use-side twin of `on_source_indexed`: one `ConsultationRecord` — the question, the addresses of what was handed to the model, what the answer cited. A record is not knowledge and never becomes any; it says the library was ASKED something, which is the one thing L0 and canonical cannot say |
| `evolve_evidence(user_id)` | assembling a schema-evolve proposal | one mechanical block beside the compile events and the document list, reporting what the component knows about the library's USE. It reaches the model in the human turn and only when non-empty (I5) |
| `rebuild(user_id)` | on an explicit `rebuild_derived` | re-derive the whole projection from its declared substrate |

Two properties of the set matter more than any individual face.

**The framework never imports a component.** Like a compile contract, the *application*
registers what it enables (`register_components` in service wiring, driven by
`PNEUMA_KNOWLEDGE_COMPONENTS`). An unknown name fails loudly at startup. With none
registered, every seam above renders byte-for-byte as it did before the concept existed —
including the compile SystemMessage, which stays byte-stable per enabled set (I5).

**The enabled set is stamped into every canonical commit's trailer**, beside the contract
and prompt-overlay hashes. A commit therefore states which contract, which wording, and
which components produced it.

## 4. The projection channel

A component that wants to answer a question in one lookup needs an index of its own, and an
index needs a write path and a rebuild path. The channel is exactly those two calls, plus
one that solves a deployment problem.

- **`on_source_indexed`** — the incremental write. The index job calls it after L1/L2 land.
- **`on_recall`** — the same write, from the use side, and delivered the same way: the
  answering route only EMITS (a row plus one `recall_projection` job, in one transaction),
  and the worker draining that job is what calls this. Fail-soft on the index channel's
  exact terms — a component that raises is logged and costs a stale ledger, never the job,
  and never the answer, which was returned long before any of this ran.
- **`rebuild`** — the full re-derivation. `scripts/ops/rebuild_derived.py` calls it.
- **`prepare`** — the async face of the sync seams.

**A projection is rebuildable from its declared substrate.** For every projection the
framework shipped first, that substrate is L0 + canonical, and I2/I7 were written in those
terms. `on_recall` adds a second one: the use-side records the service keeps (the
`consultations` table). They are not L0 and not canonical, and they are not derived either —
nothing can regenerate the fact that somebody asked something, so `rebuild_derived` leaves
them exactly where they are while re-deriving everything projected FROM them. Nothing about
authority moves: a consultation is never an authority over knowledge, canonical still derives
from knowledge L0 alone, and everything projected over the records is derived like any other
projection — replaced and replayed by the same rebuild as the rest. The framework's own
access statistics are the first such projection and are not a component's at all (they
accumulate with nothing registered); a component may keep one of its own beside them, and
`attention` instead reads the framework's. The roles this second
substrate belongs to are described in
[Owner, Steward, Visitor](steward-owner-visitor.md); the mechanical rule is the sentence
above.

`prepare` is a mechanism, not an optimisation, and it is worth being explicit about why.
Three of the faces above (`source_preamble`, `outline_tail`, `compile_tools`) are rendered
*synchronously* inside prompt assembly: they cannot await a database read. A component whose
projection lives in Postgres therefore reads a per-process mirror. Index and compile are
separate jobs in separate processes — often on separate machines — so the compile process's
mirror is cold **by construction**. Without `prepare`, a library-wide seam would silently
render the empty library forever, and the failure would look exactly like "there was nothing
to say".

**One compile per process at a time, and the guard makes it explicit.** `prepare` is a
*per-process announcement* of whose job is running, so a component whose sync seams read a
mirror holds exactly one answer to "which user is this". Two compiles interleaving in one
process would have the second one's `prepare` redefine the first one's word for *self*, and
the first one's gate would judge a page against another user's library. I1 says there is no
cross-user read path — not that the shipped scheduler happens not to take one. So the
constraint is stated as a protocol constraint and held mechanically: `run_compile` runs
inside `component_job(user_id)`, a registry-scoped asyncio lock spanning `prepare` to the end
of the job, and a second compile in that process waits. Two consequences worth knowing: with
**no** component registered the lock is not taken at all (a framework without components is
unchanged, as everywhere else), and a component face that receives a user of its own
(`compile_tools` via its sources, `source_preamble`) **asserts** it is the user `prepare`
announced and raises otherwise — a caller who ignores the window is refused rather than
answered out of the wrong mirror.

**And what a job may keep.** A component may mirror what it read from L0 across jobs, keyed
on **real source ids**. It may not key anything on what the compile task shows the model: the
runner aliases source ids to per-job `sNN` handles and hands components the *aliased* sources,
so `s01` means a different source in the next compile, and a cross-job structure keyed on it
would have one job's evidence silently overwritten by the next. Anything read off this job's
sources is job-local and thrown away with the job. Nothing is lost by that: L0 is written
before a compile is enqueued, so `prepare` refreshing from `ContentStore.list` already sees
this job's own sources under their real ids.

**Per job, not per process.** What a mirror holds must be refreshed on every `prepare`, not
once when the process first hears of a user — a worker lives for days and the index jobs
writing that projection run elsewhere the whole time. The two halves may refresh differently
according to what can change: `people` folds in only the L0 sources it has not seen (a
source's speakers and display names are what its envelope says, and never change), and
re-reads its address-term counts whole (a count is exactly what every later index job
changes). Read once per process, the second shape leaves a long-lived worker stating its
first job's library forever, and nothing about that looks wrong from inside.

**And incremental means incremental at the storage boundary.** "Only what I have not seen"
is not a property of a filter written after every row has crossed the wire — that is a full
library transfer per job, with the saving spent on CPU alone. The read itself takes a
cursor: `ContentStore.list_since(user_id, after=(created_at, source_id))`, oldest first. The
cursor is the PAIR, never the timestamp: sources imported in one batch share a wall clock,
and a `> created_at` cursor drops all but one of them for good. It is safe as a cursor
because `created_at` is the INGEST clock, stamped when the source is written, so it only
moves forward; the material's own day lives in `meta.occurred_on` and is not a cursor. A
cursor is dropped with the mirror it describes — one that outlived its mirror would resume
from the end of a library the process no longer holds.

**What "the round touched this page" means.** `gate_checks` is judged over the documents the
round wrote, and there is exactly one predicate for that — the framework's own,
`compile/patch.py:touched_this_round`: **the page's body OR its frontmatter differs from what
it held at the head of the round, or the page is new.** The same predicate the committed file
table is built from. A component that re-derives the answer from one half of the document
(comparing frontmatter only, say) applies its rule to half the writes it was written for — a
claim appended to a page whose fields nobody edited is a write like any other, and it was the
commonest future write of exactly the pages such a rule exists to correct. The other side of
grandfathering still holds: a page **nobody** wrote is left as it stands, so one old wrong
page cannot make every later compile in that library unpassable, and the repair is always
available inside the round that touches it.

**Every channel that authors canonical runs these checks.** A component's gate check is a
canonical FIELD invariant, and canonical does not know which process wrote it. So one shared
fan-out runs at all three write channels: the daily compile (`compile/gate.py`), a whole-KB
reorganization (`evolve/gate.py`, over the reorganized tree against the base it evolved from)
and the **adopt** that lands a reviewed reorganization (`evolve_service.adopt_evolve_job`,
over the reconciled tree against current main — the branch passed its own gate against an
older main, and the review window's daily compiles are exactly what it has not been judged
against). Each of them opens the components' own window first (`component_job` → `prepare`),
because a job whose process never ran a compile holds a cold mirror, and an unprepared check
would render the empty library and pass every page blind. Leaving evolve out was not a gap in
coverage but a hole in the rule: a page it created could bind two co-speakers, review would
land it, and grandfathering would keep it there.

Three rules hold over the whole channel:

1. **Everything a component stores is derived (I2).** Nothing in the framework reads a
   component's projection as an authority.
2. **It is fail-soft where it presents, and fail-closed where it judges.** All three fan-outs
   log and continue: a component that raises may cost a stale projection or a thinner prompt;
   it never costs a failed index job, a failed rebuild, or a failed compile. A component's
   *write-time* faces are the exception, and must be: a library-wide fact read from a mirror
   that failed to load is not a weaker check, it is a different and always-true one. A
   component whose required reads did not succeed refuses the round (`people.not_ready`) —
   nothing is written, and the next compile reads again. **Readiness is per RULE, not per
   component**: a component with more than one mirror tracks them separately and demands
   each only from the round that needs it. One readiness bit for two mirrors makes a
   briefly-unreadable derived table refuse work that needed nothing from it (a topic-only
   compile, an evolve over the taxonomy, an empty library) — and, worse, makes a failed read
   of one mirror clear the other, healthy one.
3. **A component never writes canonical (I7).** This is enforced rather than expected: the
   canonical object a component is handed at registration is `CanonicalReadOnly`, which
   exposes `list` and nothing else. Widening that face is a visible decision in a diff, not
   a side effect.

## 5. Derived facts serve retrieval; canonical is reached only by riding a compile

This is the principle that keeps a component from becoming a second authority, and it is the
one most worth understanding before writing one.

A component derives facts continuously, as sources arrive. Those facts are immediately
useful **to retrieval**: the `people` component's address terms resolve a nickname in the
fast lane the moment the library supports them, labelled as derived. Nothing had to approve
them, because nothing about retrieval is permanent — a query is answered and gone.

Canonical is the opposite kind of object, and so it is reached the opposite way. A derived
fact reaches the library **only by riding an ordinary compile**: the component states, under
a source in the compile task, what it observed; the contract rules on it; the write goes
through the same gate as every other write. There is no promotion step, no review model, no
"confirm these 40 aliases" queue.

Two vocabularies therefore exist side by side and are never merged:

| | derived (`component_people_terms`) | canonical (`aliases` frontmatter) |
|---|---|---|
| written by | the index job, mechanically | an ordinary compile, in the overview's fields |
| means | *the library's turns address this name at this target, with this support* | *this person is known by this name* |
| serves | retrieval, labelled derived | knowledge, cited and permanent |
| removable | yes — it is rebuildable | yes — the overview is a snapshot, rewritten whole |

The temptation the design refuses is a batch that turns high-support terms into aliases
automatically. It would be cheap and it would be wrong: the term after an `@` may name a
third person, the count is evidence and not a finding, and a library that promotes counts
has quietly made its index an author.

## 6. `people` and `time`, as reference implementations

### `people` — who a subject is

Binds to a contract family (`PNEUMA_KNOWLEDGE_PEOPLE_FAMILY`, one of the skill's own path
templates).

- **Frontmatter as a machine key.** `identities` (`scheme:value` — `mailto:` / `im:` /
  `meeting:` as the source contracts record them) and `aliases`. Both belong to the
  document's overview — its picture of the subject now — and are written whole by
  `rewrite_overview(fields=…)` / `set_fields`: nothing here only grows, because a snapshot's
  wrong entry is gone after the next rewrite and an only-growing one is not. There is no
  third field, and deliberately none: canonical records what is KNOWN about a person, so a
  list of the names that are *not* theirs is a column of distractions on the page a reader
  came to for the person.
- **The facts the component refuses mechanically**, at the write face
  (`validate_fields`) and again at the gate as the final arbiter: an identity is
  `scheme:value` and at most one page in the library binds it (`people.identity_shape`,
  `people.identity_duplicate`); an alias is not somebody else's name — not another person
  page's alias, title or slug, and not a display name the library's sources record for an
  identity this page does not hold (`people.alias_collision`). A group chat titled "Yong
  BAI, Jie WANG, Fan WANG" is three people, and the page for one of them may not take the
  other two. Both are judged over the pages a round TOUCHED (§4: body or frontmatter, or the
  page is new) — an untouched page keeps whatever it already carries, so one old wrong page
  cannot make every later compile in that library unpassable — while the other side of a
  collision is always compared against the whole library. Everything else about these fields
  is the contract's judgement.
- **Two PERSON IDS that both SPEAK in one conversation are two people**
  (`people.identity_cospeakers`). The rule above cannot see this case: a page that swallowed
  three ids lifted from a group chat's title collides with nothing, because the other two
  people hold no page of their own. It is read from L0 metadata alone, kept as one frozenset
  of speakers per source, and two things have to hold before a turn is evidence.

  *Speaking, not membership.* A member list says who is in the room, and two ids from it may
  still be one person reached two ways — which is the whole reason a page binds several. A
  turn is different: a message with a sender, a meeting segment with a speaker.

  *And a person id, not merely an identifier.* The id has to be the channel's own handle for
  one participant — the thing it would use to say "these two messages are the same human".
  IM `sender_id` and meeting `speaker_id` are exactly that, validated by their contracts
  against the archive's user list and the meeting's participants. An **email address is
  not**, and `email` is the one channel this fact stays silent about: one human commonly
  writes from `alex@work.example` and `alex@personal.example`, the correct person page binds
  both, and `email/v1` carries no stable actor id and no equivalence relation from which
  "two senders are two people" could be derived. A hard refusal resting on something the
  contract does not establish leaves only two ways past it — discard a truthful identity, or
  turn the rule off. Should a contract version arrive with a person-level sender id, that is
  what this would be keyed on.

  The refusal names both identities and one conversation where both of them spoke. The same
  fact answers from the alias side: a name the sources record for an identity that speaks
  beside this page's own is that other person's name — even when this page's own identity
  carries that name too, which is exactly when a count would otherwise have forgiven it.
  Judged over the pages a round TOUCHED, like the facts above, and for the same reason twice
  over: the page this rule was written for already exists, wrong, in a real library, and its
  commonest future write edits no field at all.
- **The one decision the gate makes unavoidable** (`people.alias_undecided`), and it is
  asked ONCE. A fact the component can check is refused; a *decision* nobody but the
  contract can make is demanded instead. For every identity this compile's sources carry
  that a person page binds, each address term the library REPORTS for that identity must end
  the round either recorded in that page's `aliases` (case-insensitively) or **declined**
  through the compile tool `decline_alias(path, term, reason)`. Otherwise one violation per
  (page, term), naming the term, its support and the two ways out — capped at eight per
  round with the remainder counted, so a large library cannot flood a repair round. The
  measurement behind the rule: a term reported under 31 sources for 88 days never reached
  the person's page while ten other documents' claims already used it. Nothing was wrong
  with the evidence, the prompt or the contract — a model does what the gate forces and
  skips maintenance nothing forces. What the answer IS stays the contract's judgement
  entirely.
- **A decline stores nothing, and the question closes when the page is written.** A decline
  is not knowledge — an honorific several people earn is a real term, simply not this
  person's name — so `decline_alias` records the decision in the JOB's own state, satisfies
  this round's gate, and writes nothing at all: no claim, no alias, no field. The commit
  carries no trace of it, which is the point.

  What stops the question returning forever is a pair of dates the library already holds,
  both derived and both rebuildable (I7). The projection records `reported_since` — the day
  a (term → target) pair first crossed the reporting bar — and the canonical repository
  records, free, the day each page was last committed (`written_on`, one `git log` walk
  bounded to the family). The rule is one line: a term is demanded of a page only while that
  page's last commit is EARLIER than the day the term became reported. A page written since
  has been shown the question — the term was under its source in the preamble and in the
  violation the round had to clear — and what that round decided is that round's business.
  A page created this round has no committed day, and a projection row from a library that
  predates the stamp has no date: both unknowns mean ASK, because silence is only ever
  earned by two dates that exist and order the right way.

  So the honest cost is visible rather than hidden: a round that declines and then writes
  nothing to the page is asked again next round — nothing committed, nothing answered — and
  a round that declines and aborts leaves the question exactly where it stood. Recording the
  term in `aliases` is still how the answer becomes *yes*, and it is the only half worth
  keeping, because a confirmation is knowledge and a refusal is not.

  This is the third shape the decision has had, and the first two are why. It rode a table of
  its own once: the row was written the moment the tool was called, so a round that then
  failed the gate left a durable decision behind while canonical stayed untouched. It was a
  person-page field next (`declined_terms`), which tied it to the commit and cost the write
  faces a whole ownership mechanism to protect — and put on every person's page a column
  saying what they are not called. The component's ONE store is the derived counts (I7), and
  the answer worth storing is the alias.
- **`people.not_ready`, the refusal that has no page.** Every rule above is measured against
  a library-wide mirror that `prepare` loads at the head of the job — and there are TWO of
  them, demanded separately. The SOURCE BOUNDARY (who the sources record, who spoke with
  whom) is what the identity and alias rules are measured against, and is required when this
  round wrote a person page declaring those fields or its sources carry an identity at all.
  The ADDRESS-TERM PROJECTION is what the forced alias decision is measured against, and is
  required only when that decision applies — an identity present in this round's sources. A
  round that asks neither (a topic-only compile, an empty library) is not refused by either.
  When a required load fails, the component does not fall back to what it happens to hold:
  an empty mirror would turn each hard refusal into a check that is different and always
  true, allowing exactly the writes those rules exist to refuse. The round is refused
  instead, nothing is written, and the next compile reads again. So the
  component's full rule set is six kinds: `people.identity_shape`,
  `people.identity_duplicate`, `people.identity_cospeakers`, `people.alias_collision`,
  `people.alias_undecided`, `people.not_ready`.
- **`find_person`** for the compile model: canonical exact first, then the contact-book name
  keys below, then the address projection.
- **`enumerate_identities`** for deep recall: the closed set of external identities the
  sources record in a date range, each with its source count, first/last occurrence, display
  names, and the person page bound to it — or `(unbound)`. This is what makes "everyone
  who…" a judgement over a complete candidate list whose residue is visible, rather than
  over search hits.
- **`person_profile`** for deep recall and a **`person` fast path**: the whole page, current
  claims first, superseded history labelled.
- **`people_around`**, a `people_around(subject)` fast path and its deep twin: the other
  question a library is asked about people, and the one `person` cannot take. 「能不能邀请
  lumenlab 的同学来分享一下?」 names no person at all — it names a **subject**, and the answer
  is the people the library already wrote around it. Pure derivation, no model: the subject
  resolves by exact match under one normalisation (case, whitespace, punctuation — no pinyin,
  a project has no second convention to be written in) against every document's path, title,
  `slug` and filename, across **all** families, not only this one's; then the person pages
  canonical LINKS with it come back in **both directions** — a person page's own claim
  pointing at the subject (`links-to`) and the subject's own claim pointing at the person
  (`linked-from`, which an overview `connections` line is) — each with the line that says who
  they are and every linking claim, verbatim and cited. The linking claim IS the evidence: a
  compile already read the material, decided the two subjects are related, and wrote a cited
  sentence saying how; returning the edge without that sentence would return the half nobody
  can check. Edges are read with the gate's own regex and resolver (`compile/links.py`), so
  what is enumerated is exactly what the write side validated. Superseded linking claims are
  kept and labelled, as `person_profile` keeps a page's history, and rank last. A tie of three
  documents or fewer comes back whole with every row labelled by the subject it answers for;
  more than three, a name the library does not hold, and a subject nobody is linked with are
  all an empty face rather than a guess.
- **Contact-book name matching**, the one normaliser every people lookup goes through
  (`find_person`, the `person` fast path, `person_profile`). Exact matching alone made a
  question written in one convention miss a page written in another: a page titled
  `Kexin ZHOU`, bound to `im:Kexin ZHOU`, is unreachable by 「可欣」 — which is the form the
  people who work with them would actually type. So each of a page's own names (title,
  confirmed aliases, slug, and the display-name half of its identities) is expanded into a
  set of **keys**, and the query is expanded by the same function: a latin name gives each
  token, both orders spaced and concatenated, and the initials; a CJK name gives the name
  whole, its surname and given halves — compound surnames respected, so 「欧阳锋」 is 欧阳 +
  锋 and never 欧 + 阳锋 — and the toneless pinyin of all three, in both orders, spaced and
  concatenated. The two scripts **meet on the pinyin**, which is what lets a Chinese question
  reach an English page and an English question reach a Chinese one, with neither side
  storing the other's spelling. Two tiers: a key both sides hold, or every query token being
  a token of the page, is **tier 1**; a query key of two characters or more that *prefixes* a
  page key is **tier 2** — and a one-character query is matched exactly and never as a
  prefix, so 「周」 is a surname key rather than the first letter of half the library. Pages
  rank by tier, then by the longest key that met, then by how many met. **A tie is returned,
  not resolved**: where several pages match equally well the fast path returns up to three of
  them with their definition lines, labelled `via:name-match tier<n>`, and the lane holding
  the question chooses between them — this lookup cannot. An honorific comes off the
  *question* (「可欣姐」 → 「可欣」) only where the raw form does not reach tier 1, and only
  after the address-term projection has had its turn: a term the whole library concentrates
  on one person is evidence out of the corpus, while stripping an honorific is a guess about
  the question. Nothing here is a similarity score, nothing is written, and the strict key
  stays strict — the alias-collision rules are about FACTS and still compare names exactly.
- **Address terms**, the persisted projection. A term that opens a turn addressing X, or
  that the next speaker answers, is counted per (term → target identity) pair with its
  library-wide support. What is worth *saying* is decided by **concentration, not
  frequency**: a term is reported for a target only when it has enough support, from more
  than one source, and that target holds most of the term's total. The reason is empirical —
  inside one conversation a nickname and a common phrase are indistinguishable, while across
  a library `是的` is answered by everyone and `阿宝` keeps landing on one person. Concentration
  alone still lets a topic word through — a product name that opens messages the target then
  answers looks, by reply rate, exactly like a nickname — so the projection also counts the
  same term at the **non-vocative position** (mid-sentence, not after an `@`), and a term is
  reported only when at least half of its uses are vocative (`REPORT_MIN_VOCATIVE_SHARE`): a way
  of addressing someone lives at the head of a turn; a topic lives everywhere in it. A term
  this source repeats that the library cannot yet back is stated separately as *emerging*.
- **Names nothing structural can target**, the weakest line of the three and labelled as
  such. A nickname can be a vocative once and a third-person mention fifty times (`和 momo
  商量`), and no turn structure can point those fifty at anybody. So the preamble simply
  lists this source's repeated name-shaped tokens that match no present identity, no name
  the library already accounts for and no term it states elsewhere — no target, no support,
  capped and counted. It is a discovery aid for the contract's contextual judgement, and the
  route into the library stays the ordinary one: an `aliases` entry on somebody's page.

### `time` — the owner's calendar as an index

- One derived row per L0 block: the block's UTC instant, and the calendar day it falls on
  **in the subject's timezone** — the same day ingest wrote into the block's section, never
  the UTC date, because for a subject at +08:00 everything sent between midnight and 08:00
  local carries the previous UTC date. Each row also records the zone it was normalized
  under and where that zone came from, so changing a subject's timezone never silently mixes
  two calendars.
- A **`timespan(since, until)` fast path**, and the deep pair **`timeline`** (a day-by-day
  or week-by-week digest, with `granularity="verbatim"` reading ONE day block by block so a
  day can be *read* rather than sampled) and **`as_of(date, …)`**, which walks a subject's
  supersession chains and reports what was in force on a date.
- One line per source in the compile task: its span in the owner's day and clock, plus the
  source's own zone when the two differ.
- **It never parses natural-language time.** The routing turn — which sees `as_of` and the
  subject's zone — resolves "last quarter" into ISO days before an argument reaches the
  component; a non-ISO argument becomes an `invalid_args` audit row rather than a quietly
  different range. The component's seven day rules are enumerated in its module docstring.

## 7. Retrieval: the component decides what it knows, the framework decides what is shown

The built-in retrieval paths are homogeneous ranked lists and fuse by reciprocal rank. A
component path is different in kind: it answers a *structured* query (`person(alias="…")`,
`timespan(since, until)`) with exact results that carry no rank. So it is neither run blind
nor fused.

**Fast** spends one routing tool-call turn when at least one path is offered — the paths
bound as tools, zero or more calls emitted in a single turn, never a loop — and runs the
chosen paths concurrently with the built-in retrieval, which never waits for them. Their
results form a fourth evidence face under their own header. Every candidate is an ordinary
claim anchor or `source_id + block span` (I4), so citation aliasing and the structured
answer's admission check apply unchanged.

Then comes the rule that gives this section its title. **A path returns everything it
knows** — the whole page, the whole range — and core decides what is shown:

1. one deterministic, model-free ordering against the question (lexical overlap on
   unicode-aware tokens, a `current`/`superseded` term, time proximity, the path's own order
   as tie-break; a wired reranker replaces the overlap term and fails soft back to it);
2. the path's declared cap spent on **that** order, under two floors — one window whenever
   the path returned any, and the top claim of every distinct section;
3. a character budget over the whole face (`RECALL_COMPONENT_BUDGET_CHARS`), because an item
   count bounds how many things a path contributes and not how large they are.

Every truncation is **described rather than counted**: which sections, which days, and an
over-long excerpt cut at a block boundary that names the blocks it left out. A lookup that
silently returns its first N items reads as "that was everything", which is the one thing an
enumeration must never say falsely.

A cap spent on *document* order is exactly how the one claim that answers the question ends
up just past the edge. That is why ordering, truncation, dedup and budgeting are stated once
in core and never inside a component.

Three more rules complete the merge:

- **Dedup never disturbs the ranked faces.** They carry relevance order and the selector or
  reranker has already judged them. So the component face hides what they already show and
  says how many, and a ranked claim a lookup also returned is labelled `via:<path>` —
  corroboration without a second copy.
- **Under `evidence_strategy=select`** the component results join the numbered candidate
  pool as their own group instead of bypassing the selector; what it picks renders inside
  the ordinary faces.
- **Deep takes the opposite discipline** — completeness over caps. Its component tools
  paginate and every response ends with the exact call that fetches the rest.

What the router chose, with which arguments, what it rejected as malformed, and any path
that timed out are telemetry, not silence: they reach the HTTP answer and the Recall UI.
With no path offered — or `RECALL_COMPONENT_PATHS` off — there is no routing call and the
lane is byte-identical to the lane without the seam.

## 8. Writing one: a checklist

1. **State the question it answers that ranking cannot.** If better retrieval would answer
   it, the answer is better retrieval. A component earns its place by turning a search into
   a lookup, or an open set into a closed one.
2. **Bind it to a contract family**, by path template. The family is the scope of its gate
   checks and its outline lines.
3. **Decide what it stores, and prove it is derivable.** Write the `rebuild` first: if the
   projection cannot be re-derived from the substrate it declares — L0, canonical, and for
   a use-side projection the kept consultation records — it is not a projection, it is an
   authority, and the design is wrong. A component that needs no store of its own declares
   no substrate and implements no `rebuild`: `attention` is the shipped example, faces over
   a ledger the framework keeps.
4. **Implement only the faces you need.** Every one has a no-op default. Resist the urge to
   fill the table.
5. **Keep the canonical face read-only.** It is `CanonicalReadOnly` at registration; if you
   need another read, add the method there, in a diff that says so.
6. **Make the seams fail-soft in fact, not just in the fan-out.** The framework guarantees a
   raising component does not fail the job; it does not guarantee your projection is
   coherent afterwards. Prefer idempotent writes and an explicit rebuild.
7. **Return everything; cap nothing.** A path's `cap` is a declaration the framework spends;
   truncating inside the component takes the ordering decision away from the only layer that
   sees the question.
8. **Say what you observed, never what to conclude.** A tool description states where things
   come from and what the tool does. Judgement belongs to the contract — if you find
   yourself writing "bind this only when…", that sentence belongs in the compile-contract
   guide, not in a tool description. (Mechanism over persuasion, applied to a component.)
9. **Test the seam, not just the logic.** At minimum: the gate rejection, the projection's
   rebuild reproducing the incremental result, per-tenant isolation (I1), and that with the
   component unregistered every surface is unchanged.

## 9. Measuring a component

A component is measured the way anything else here is: a same-harness A/B, the two arms
byte-identical apart from the component set — same contract, same models, same answering
path, same judge, the same fully paired questions — with the threshold that would count as a
material gain declared before the run, and a paired significance test rather than a
difference of two percentages.

**Verify the seam is exercised before the aggregate is worth arguing about.** How often
routing was offered and chose a path, how often component evidence was non-empty, how many
answers carried a `via:` label, and how many dropped items truncation reported instead of
cutting silently are counts rather than estimates. A component whose faces are barely reached
has not been measured yet, whatever the score did.

**Then read the aggregate for what it can hold.** A component's value is largely invisible to
an average over a benchmark whose questions were not written to need it: a closed-set
enumeration matters on the questions that have a residue, a calendar index on the questions
that name a period, and averaging those in with a thousand others dilutes exactly the effect
being measured. That is an argument for declaring the slices in advance and correcting for
multiple comparisons, not an excuse for the aggregate. "Heavily used and did not degrade
quality" is a claim a run of this shape can carry; "improves accuracy" needs an effect the
test can resolve.
