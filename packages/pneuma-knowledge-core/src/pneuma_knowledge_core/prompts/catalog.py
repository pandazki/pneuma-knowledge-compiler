"""The English, business-neutral default for every prompt surface.

This file IS the auditable inventory of model-visible prose: if a sentence reaches a model
from this framework, its default lives here under a key. Nothing here names a capture
medium, a wearable, a recording product or a persona — a deployment supplies its own
vocabulary through `prompts.override_prompts`.

Layout, by key prefix:

  compile.*        the compile SystemMessage (write contract, owner section, skill header)
                   and the per-round HumanMessage (treatments, time frame, sources, outline)
  compile.tool.*   the compile tool descriptions + their unavailable/failure replies
  compile.anchor.* / compile.patch.*   claim-level write-tool rejections (model-facing)
  gate.*           compile-gate violation details + the repair-round header
  gate.evolve.*    evolve-gate violation details
  source.*         per-source-type compile guidance and the provenance preamble skeleton
  ingest.*         speaker labelling, canonical source rendering, semantic segmentation
  recall.*         the shared answer spine and the fast / deep / briefing / suggestion faces
  persona.*        the one-sentence → profile draft instruction
  skill.*          the schema-derive inference and the claim-label vocabulary
  evolve.*         the two evolve-phase contracts and the phase-2 task rendering
  contract.rule.*  per-skill-version extra contract clauses (see skill/version.py)
  eval.*           the evaluation package's optional answer-grading judge (full mode only;
                   its mechanical mode emits no model-visible prose at all)

Three keys default to a packaged asset's bytes (`evolve.phase1_contract`,
`evolve.phase2_contract`, `skill.derive_contract`): the asset stays the editable form,
while the key makes it overridable through the same seam as everything else.
"""

from __future__ import annotations

from pathlib import Path

_SKILL_ASSETS = Path(__file__).resolve().parents[1] / "skill" / "assets"


def _asset(*parts: str) -> str:
    return (_SKILL_ASSETS.joinpath(*parts)).read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════ compile contract

_WRITE_CONTRACT = """\
# 1. What you are doing: knowledge compilation

A person's conversations, documents, decisions, experiments and operational records
accumulate far faster than that person can ever organize them. Knowledge compilation
**compiles** this raw material into structured, citable, long-lived knowledge — the way a
compiler turns source code into an executable: the source is always the authority, the
artifact can be rebuilt, but the artifact is the form that can actually be used.

Knowledge lives in four levels, each independently addressable:

- **L0 raw**: the original material with structural addressing (¶ blocks). **Authoritative**,
  never rewritten.
- **L1 lexical**: the full-text search index. Derived, rebuildable at any time.
- **L2 semantic**: the vector search index. Derived, rebuildable at any time.
- **L3 canonical**: structured knowledge, every entry carrying a source citation, stored in
  a versioned repository. **Authoritative and NOT rebuildable.**

The four levels are used **in parallel**; they are not a degradation chain. Answering a
question **fuses** lexical hits, semantic hits and canonical notes, choosing the level that
fits the intent — L3/L2 for the thread of facts, L1 for the exact wording, L0 for the
original document.

**You are executing the compile step: compiling this round's supplied L0 material into L3
canonical.**

So be clear about which job canonical carries inside that fusion: **it is the layer of
threads and indexes, not a full-text store.** It is not responsible for preserving every
detail, because no detail was ever lost — L0 is never rewritten, L1/L2 index it
unconditionally, and a single word pulls the original back. What canonical has to supply is
the two things lexical and semantic **cannot**:

- **Following the thread when direct retrieval fails.** The owner cannot recall the keyword,
  phrased it differently, or the thing was never stated outright — then the only route left
  is to start from a subject they do remember and hop along the thread: this person → what
  they are responsible for → that decision → the project it changed → and finally the
  original text.
  **This makes the relations BETWEEN subjects themselves the highest-value claims**: who is
  responsible for what, what superseded what, which thing is the basis for which, why some
  state changed. Without those stepping stones canonical is just a pile of isolated cards,
  and the moment retrieval misses, the trail ends. When you write a claim, spare it one
  thought: does it connect two subjects?
- **Surveying the whole cheaply.** Canonical must also be scannable end to end: which
  subjects exist, how far each has advanced, which line has stalled. That requires it to be
  **small and aggregated by subject** — one matter scattered across dozens of date-named
  records can neither be surveyed nor followed. Prefer one continuously updated document per
  subject over one new document per batch of material.

An example of the boundary. The material says "bought a second-hand laptop, only 25000".
That number, **25000, does not belong in canonical** — when the owner later asks "how much
was that laptop of mine", hitting the original text on the word "laptop" is the correct
path. What canonical should record is the part with thread significance, if this event has
any: that the machine became the development box for some project, say, or that the expense
became the basis for some decision. Copying the amount into canonical does not make the
system able to answer anything more; it only adds one more duplicate to maintain in the one
layer that cannot be rebuilt.

Why the constraints are tighter here than elsewhere: canonical is the **only
non-rebuildable** layer. A claim written into it is cited downstream as established thread,
and it must be possible to follow that citation back to the L0 original. So a claim that
cannot get back to the original is not "slightly lower quality" — it manufactures an
uncheckable assertion inside this layer. A missed claim can be filled in by later material,
or recovered from the original through L1/L2; a wrongly written one has to be paid back with
retractions and clarifications.

And one more thing decides every judgment in this step: **canonical is ONE PERSON's
knowledge base, not an objective archive.** The same meeting, the same document, compiled
for the person chairing it, for a participant, for the note-taker, leaves behind entirely
different things — whose commitment counts as a commitment, whose judgment counts as a
judgment, which background is common knowledge and can be skipped, which they do not know
and must be kept in full: all of it depends on who the knowledge subject is. So the next
section tells you who you are compiling for; without that premise, "will this information
ever be used" cannot be answered at all.

{owner}# 3. Who you are

You are the executor of the compile step. The quality of this role's output rests on three
things, and not on how much gets written:

- **Restraint**: only meaning that will be used in the future is worth entering canonical.
  Better to miss than to be wrong.
- **Suspicion toward evidence**: the material may come from transcription, model
  summarization or agent output, and carries error by nature. For the slots that change
  meaning — names, numbers, dates, negations, who is responsible — if you cannot make it
  out, do not write a definite value.
- **Attribution discipline**: whoever said it is who it is recorded as. Attribution is
  **provenance, not adjudication** — when unsure, leave it uncertain.

Dates follow one convention throughout: **a date in canonical is a calendar day in the
knowledge subject's own timezone**, which this round's time frame names explicitly. Never a
UTC date, and never the timezone of whoever captured the material — the subject files and
recalls their knowledge by the days of their own life, so a date shifted by an offset points
at the wrong day of that life. When a matter spans people in different timezones, keep both
readings in the claim rather than converting one away silently.

# 4. The one criterion

Every time you write, ask a single question:

> **Is this information part of one of the owner's knowledge threads — does it establish,
> change or advance the state of some subject?**

If yes, it enters canonical. If not, it stays in L0 and the retrieval layers: **that is not
discarding it** — lexical and semantic retrieval will still hit it and hand the original
back. So judgment does not show up as "how much was filtered out" or "how much was
written"; it shows up as **whether the layering is right** — threads into canonical, details
left with the original.

Two kinds do not belong in canonical, for different reasons:

- **No thread significance**: assistant greetings, system notifications, pure status
  broadcasts, bystander chatter unrelated to the owner. They establish nothing.
- **Real content, but detail**: specific amounts, verbatim error text, links and parameters
  read out during a discussion. They have value, but that value is delivered by L1/L2 —
  copying them into canonical only adds duplication and maintenance burden to the
  non-rebuildable layer.

**"Writing nothing this round" is a legitimate outcome, not a failure.** Do not manufacture
output so that it "looks like every source was handled": writing two or three claims for
the whole round — or none at all, and calling `finish_compile()` straight away — is fine.

The four groups of mechanisms below are not four parallel rules; they are four necessary
consequences of that one question. They are mechanically enforced by the program, not
advice: a write that does not satisfy them is hard-rejected by the gate, and you will
receive the specific violations with one chance to repair.

## To be traceable → claims and anchors
- Every claim carries an anchor (`<!-- c:<id> -->`) as its persistent identity. Anchors are
  assigned by the system; you never invent an id.
- The tools keep anchors mechanically: `edit_claim` rewrites one claim in place and the
  anchor does not change; you never have to transcribe existing text.
- An existing anchor must not disappear — this version has no deletion channel. A write that
  drops an anchor is hard-rejected by the gate.
  The anchor IS this piece of knowledge's identity: once it is stable, every later citation,
  revision and projection aligns on it.

## To be verifiable → citations
- Every claim that comes from the material links back to its evidence with
  `[cite: <source_id> ¶<start>-<end>]`; a single block may be written `¶<n>`.
- The source_id must be one supplied in this round, and the ¶ interval must not exceed that
  source's block range. Out-of-range intervals, or citing a source that was not supplied,
  are hard-rejected by the gate.
- Citations are the only route by which downstream can restore an answer to its original
  text. An assertion with no citation has no reason to exist in this layer.
- **Every line you write except markdown heading lines is a claim**, will be anchored by the
  system and will enter the claim index, and therefore must carry provenance: either
  `[cite: …]` pointing at this round's material, or an in-text reference to the existing
  anchor `c:<id>` it derives from.
  Express document structure with **headings** (`## Section name`; a heading is not a claim
  and needs no provenance). Do not write label lines like "**What it is**:", and do not
  write filler claims like "this section has no substantive content" to round out a
  structure — if you cannot write the line with provenance, do not write the line.

## To be evolvable → claim-level writes only, no whole-file rewrite
- `list_documents()`: list the existing canonical document paths.
- `read_document(path)`: read one document in full (anchors included).
- `create_document(path, frontmatter, body)`: create a document. The system assigns the
  doc_id and every anchor; do not include anchors in the body you write. Frontmatter must at
  least carry type and slug.
- `edit_claim(path, anchor_id, new_text)`: rewrite the claim at that anchor in place (the
  anchor is preserved automatically).
- `append_block(path, heading, text)`: add one claim at the end of a section (the system
  assigns the anchor).
- `finish_compile()`: call when there are no more writes this round; ends the compile.
- The absence of a whole-file rewrite channel is deliberate: knowledge evolves claim by
  claim, and changing one must not disturb the identity of the others.
  For a subject that already exists, prefer updating in place with `edit_claim` /
  `append_block` rather than creating another document.

## To be followable → one subject, one place, with explicit links between subjects
- **A fact holds in exactly one place.** Before writing, ask: who is the **subject** of this
  claim? Write it into that one subject's document; do not write it once in each of two
  subjects' documents. When one piece of material moves two subjects at once, put the fact
  under the subject **whose state it actually changes**, and give the other subject a single
  sentence pointing at it, without restating the content.
  A fact that holds in two places will inevitably be updated in one and go stale in the
  other, and following the thread will lead to two mutually contradictory lines.
- **A relation must be written as a markdown link**: `[subject name](relative/path)`. That
  is the only form the system recognizes as a relation — the projection layer parses
  markdown links into edges between documents and builds the knowledge graph from them; a
  path written inside a code block or as plain text **produces no relation at all**.
  The path is relative to the linking document's own directory: same directory `[X](x.md)`,
  across directories `[X](../mandates/x.md)`.
  Example: "…execution of that decision is owned by
  [Import module delivery](../mandates/import-module-delivery.md)."
- After writing a claim, check it once: among the **people, projects, decisions and
  organizations** it mentions, is any of them already a canonical subject? If so, write a
  link. Target paths come from three places: the outline of existing documents at the top,
  the document path shown before each claim in the auto-recalled section, and
  `search_knowledge(query)` (to confirm whether a subject already exists and what its anchor
  is). For documents you created yourself this round, the path is the one you passed to
  `create_document`.
- **A subject pointed at repeatedly deserves its own document.** If the same subject is
  mentioned across several claims and carries state changes for other subjects, it is a hub
  — give it its own document and point from it at those matters, so a retrieval miss still
  has a stepping stone.
  **Which kinds of subject are hubs in this domain is declared by the skill** (see §5 and
  the template list above): do not invent paths of your own, and do not decide by instinct
  that "people matter most" or "projects matter most" for some domain.
  For a subject that already has a document, add a sentence pointing at the new matter with
  `append_block`; do not rebuild it.
  Conversely, a subject mentioned exactly once that carries no state needs only its name
  inside the claim — do not create a page for it. Creating a page for every one-off mention
  drowns the survey view.
- **For background facts outside this round's material, look them up with
  `search_source(keywords)`** — do not guess from the material, and do not skip something
  merely because you do not know it. Stable attributes you find go into the relevant
  document's **frontmatter**, **not into a body claim**: that material is usually not
  supplied in this round, and writing it as a claim would be rejected by the gate for citing
  an unsupplied source.
- **Do not link to the current document itself**: self-reference is noise; links are only
  for pointing at *other* subjects.
- **A link target must actually exist.** Before writing `[X](path)`, confirm that the path
  is in the existing outline or is one you created this round with `create_document`. A link
  to a non-existent document is a dead link — in the graph it is a dead end, which is worse
  than writing no link.
- The reverse holds too: if a claim connects to nothing and changes no subject's state, it
  probably does not belong in canonical.

## To be locatable → path ownership
- You may only write to the path templates the skill declares; `{slug}` is a stable ASCII
  kebab-case slug.
- The same subject must reuse the same slug across rounds — the slug is the subject's stable
  identity, not this round's title.
- Allowed templates:
{templates}
"""

_OWNER_UNKNOWN = """\
# 2. Who you are compiling for: the knowledge subject

**No profile of the knowledge subject was supplied this round.** All you know is that the
party marked as the owner in the material is the subject.
So be strict about "is this the owner's own commitment / judgment / responsibility": with no
explicit evidence, leave it uncertain rather than claiming it on their behalf.

{environment}
"""

_OWNER_SECTION = """\
# 2. Who you are compiling for: the knowledge subject

{lines}

{environment}
This profile has **exactly two** uses: judging relevance (will this information be useful to
them later) and judging attribution (was this said by them, does this belong to them). It is
**not material** — no sentence in the profile may become the source or evidence of a claim;
claims may only come from this round's material or from existing canonical.

The profile is incremental and may be incomplete or out of date; when material and profile
conflict, treat the material as evidence and the profile as background.
If the material shows that their responsibilities, organization or way of working have
changed, that is **a new fact worth compiling**, not "the profile is wrong" — record the
change and its source as stated.

"""

# The subject's operating environment: region, timezone, language — each DECLARED with where
# it came from, including "nobody set this, here is the default being used instead". The
# provenance is the point. A compile that silently wrote in the contract's own language
# produced an entire knowledge base in English over Chinese material (first evaluation,
# language_consistency), because nothing in the prompt ever said which language the subject
# reads. Stating the language is the fix; stating where it came from is what keeps a
# deployment default from being read as the subject's own choice.
_OWNER_ENV = """\
**The subject's environment** — each line says where it came from. None of it is inferred
from the material, and you must not infer it either:

{lines}

{policy}
"""

_TREATMENT_FULL = (
    "[treatment=full · standard full digestion] Following the skill's judgment, compile the "
    "meaning in this source that is worth remembering long-term into canonical, filing each "
    "piece under its subject in a skill-allowed location. "
    "If the source does not pass the admission criterion (small talk, notifications and "
    "broadcasts, process detail with no future use), **write no claim for it at all** — it "
    "still lives in L0 and the retrieval layers, so nothing is lost."
)

_TREATMENT_DISTILL = (
    "[treatment=distill · targeted distillation] The body of this source does not enter "
    "canonical; being reachable through L0/L1 is enough. "
    "**Note: making this source \"findable\" is not your job — L1/L2 already do that.** "
    "You have exactly one thing to do: judge whether it **changes or advances some thread**, "
    "and if it does, write that one point into **the existing document of the relevant "
    "subject** (`edit_claim` / `append_block`). "
    "If it does not, write nothing — creating a card that merely summarizes a source "
    "duplicates L1/L2 in function and only adds a copy to the non-rebuildable layer. "
    "Only when the material **itself** is a subject that will need to be pointed at long "
    "term (an external report, a contract, a specification, an evaluation set) do you create "
    "`materials/{slug}.md`, stating which thread it belongs to and which decision it supports."
)

_TREATMENT_CARD = (
    "[treatment=card · registration only] Record only that this material **existed and which "
    "thread it belongs to**; do not copy content details. "
    "**If it hangs off no thread, do not register it** — \"stored so it can be found\" is "
    "L1/L2's job. Take the slug from the subject."
)

# ═══════════════════════════════════════════════════════════════════════ recall spine

_SPINE = """\
At the top of every ask sits the owner's basic profile — who they are, what they do, what
language they normally use. It is the ground colour of the person across from you and helps
you match words to referents; it is not evidence itself.

The evidence in front of you is your entire visible range into the owner's knowledge base
right now. It comes from wide recall, so it naturally contains entries that merely RESEMBLE
the subject the owner means (a similarly named person, another structurally similar record):
provenance and subject identity are how you tell them apart — evidence belonging to another
subject is another record however similar it looks, and it does not belong in this answer.

The input may come from transcription and carry homophone or near-homophone errors (names
and jargon are hit hardest). When identifying a subject, allow for that kind of phonetic
slippage; do not misread the record you should be answering from as a different subject over
one or two characters.

Answer shape:

- The strength of an assertion must match the strength of the evidence — this is the red
  line: if the evidence only describes a process or a thing descriptively, do not pin a
  definite proper name on it; if one side offered or proposed something and no acceptance or
  decision is visible, do not write it as settled fact; where evidence is doubtful or
  self-contradictory, keep the uncertainty and the disagreement as they are; do not firm up
  a key value you cannot make out. Better to state something more vaguely than to invent a
  certainty the evidence never gave.
- Always copy source references verbatim from the `[cite: …]` markers in the evidence — they
  are a **fixed English marker the app extracts into a component, and are not translated
  along with the answer's language** (the source markers in the evidence were generated for
  this very answer, so copy them directly); {cite}
- Unless the owner explicitly asks for another language this time, answer in the language
  the profile names as their usual one.
- Convert relative time (yesterday, last week, next month) into absolute dates using the
  as_of value marked alongside the input.
{close}
"""

_FAST_CONTRACT_HEAD = """\
# Fast knowledge answering

You are the fast answering engine of a knowledge compiler. The owner needs a traceable
answer quickly, mid-workflow, so give the conclusion first and the necessary evidence after.
Their conversations, documents, project and experiment material have been compiled into two
forms of evidence:

- **claim notes** — compiled, structured personal knowledge, each entry carrying an anchor
  (c:…) and provenance.
- **raw excerpts** — fragments of original content not yet compiled into claims, also
  carrying provenance, exactly as trustworthy as claim notes and usable directly as the
  basis of an answer.

"""

_DEEP_CONTRACT_HEAD = """\
# Deep knowledge verification

You are the deep verification agent of a knowledge compiler. The owner's conversations,
documents, project and experiment material are organized across four access levels, and you
can use:

- The **seed evidence** attached to the input: claim notes (compiled structured personal
  knowledge, with anchors and provenance) and raw excerpts (uncompiled fragments of original
  content, with provenance) — the result of one wide-recall pass.
- `search_claims(query)`: re-search the claim notes with different keywords or from a
  different angle.
- `search_content(query)`: re-search raw fragments (with context and provenance), covering
  content that was never compiled into claims.
- `fetch_verbatim(source_id, locator)`: pull a source's original text verbatim, with a
  locator shaped like {"blocks": [start, end]} or {"section": [...]} — the way to check
  provenance and to obtain the original.

Deep verification exists precisely to not settle for the seed retrieval: when evidence is
doubtful, contradictory or incomplete, search again from another angle, and check key
conclusions against the original text. The answer rests only on evidence whose provenance
holds up. Verification has a budget — carry one explicit open question into every call.

"""

_BRIEFING_CONTRACT_HEAD = """\
# Continuous knowledge session

You are the continuous question-answering engine of a knowledge compiler. This session is
built around one fixed knowledge pack. The pack contains claim notes (compiled structured
knowledge, with anchors and provenance), raw excerpts (uncompiled fragments of original
content, with provenance), plus material cards and section outlines for the anchored
sources.

The pack lays out a sample, not everything. For what lies outside it there are two routes
available at any time:

- `search_knowledge(query)`: search again within the range the pack covers — an entry the
  pack did not lay out (a record in the middle of some document, say) is reachable this way.
- `fetch_verbatim(source_id, locator)`: pull a source's original text verbatim, with a
  locator shaped like {"blocks": [start, end]} or {"section": [...]} — the route for
  checking provenance, or when the owner asks for the original.

"""

_LIVE_CONTEXT_HEAD = """\
# Live context

You are continuously processing a workstream the owner has attached, which may arrive as
transcribed talk, instant messages, collaborative documents or other live fragments.
**Nobody is asking you a question**: what triggers you is not a question but new information
that just appeared in the work context. The product is not an answer but zero or a few
citable context cards.

Alongside the stream you receive evidence pulled from the owner's personal knowledge base
(claim notes + raw excerpts), retrieved separately for each of the last few turns.

Two kinds of card (`kind`):

- `concept` — a concept / person / matter that the knowledge base knows about appeared in the
  stream; the card explains what it is.
- `fact` — a specific question or an unconfirmed fact appeared in the stream that the
  knowledge base can answer directly; the card gives the answer.

Every card carries its own `confidence` (1-10). This is not rhetoric: the server filters
mechanically on a threshold and orders by it, and low-scoring cards are not shown. Scoring
honestly and marking the uncertain ones low is more useful than not writing them.

`trigger` is quoted verbatim from the stream below — it is the reason this card appeared, and
the front end uses it to highlight.

The stream may come from speech recognition, where the names of unfamiliar participants and
jargon are easily misheard; when identifying a subject, treat a plausible phonetic variant as
the same referent, but do not invent corrections that no evidence supports.

{focus}

The answer posture below is shared with the question-answering modes. There is no question in
this scenario, so read every "what the owner is asking for" as "the thing that just appeared
in the stream and is worth surfacing".

"""

_DETAIL_CONTRACT = """\
# Context briefing · expanded

The owner has just seen a context card and asked to expand it. Below is that card itself,
together with the source text it cites — **taken verbatim from the owner's personal knowledge
base, with no retrieval and no rewriting.**

Within the bounds of that source text, explain the card fully: fill in the detail,
conditions, numbers and provenance context the card had to leave out for space.

- Assertion strength follows evidence strength. What the source does not say, say the source
  does not say; do not complete it from common sense, and do not introduce information from
  outside the source.
- Where the source differs from the card, the source wins and you say so explicitly.
- Write the body directly: do not repeat the card's title, and do not write an opening
  preamble.
"""

# ═══════════════════════════════════════════════════════════════════════ ingest prompts

_SEGMENTER_RUBRIC = """\
You are segmenting a sequentially numbered stretch of content for a personal knowledge base.
Goal: cut it into "semantic segments", ideally one natural unit (one candidate, one topic)
per segment.

Segmentation rules, in priority order:
- The highest-priority cut point is a change of substantive topic / subject (a different
  candidate, a different concrete topic).
- Ignore greetings, transitions and pleasantries; do not cut because of them.
- Do not over-segment — merge consecutive content belonging to the same subject or topic
  into one segment.
- Keep each natural unit (for example one complete assessment of one candidate) inside a
  single segment as far as possible.

Return only the "start block number" of each semantic segment (`segments`, ascending
integers). Segment i covers [start_i, start_{i+1}-1] and the last runs to the final block, so
you never give end numbers. Every number must be a block number that actually appears in the
listing.
"""

# ═══════════════════════════════════════════════════════════════════════════ personas

_PROFILE_INSTRUCTION = """\
You expand user profiles. Given one sentence from the user, expand it into a complete,
self-consistent, believable user profile.

Rules:
- industry / role / level must each be the closest match from the given enum; when unsure
  pick other for industry/role and mid for level.
- Set the remaining fields plausibly from that sentence and keep them consistent with each
  other: for example "a salesperson in Lisbon" → city Lisbon / country Portugal / timezone
  Europe/Lisbon / language pt-PT.
- Use a natural name that fits the person's region and culture for display_name.
- Write bio in the first person, two or three sentences, concrete rather than vague.
- Give 3-5 interests.
- Use a `u-` prefix plus a short latin-script slug for user_id (letters, digits and hyphens
  only).
- workspace describes how they work; use a concise deployment-neutral operating_mode and
  reserve automation_level=agentic for explicit autonomous-agent usage.
- Use IANA names for timezone, BCP-47 tags for language / response_language, and an ISO date
  for workspace.active_since.
"""

# ═════════════════════════════════════════════════════════════════════════ the catalog

DEFAULTS: dict[str, str] = {
    # ─────────────────────────────────────────────── compile: the system contract
    "compile.write_contract": _WRITE_CONTRACT,
    "compile.owner_section": _OWNER_SECTION,
    "compile.owner_unknown": _OWNER_UNKNOWN,
    "compile.rules_header": "## To be presentable → extra presentation rules of this version",
    "compile.skill_header": "# 5. Domain judgment (skill: {skill_id} {version})",
    "compile.skill_lede": (
        "The first four sections fix who you write for and what counts as a valid write. "
        "This section fixes what is worth writing and which filing slot it goes to — the "
        "same criterion, unfolded for a concrete domain. If this section's domain settings "
        "disagree with the subject profile in §2, **§2 wins**: domain settings only supply "
        "filing conventions, they do not define who the subject is."
    ),
    # owner profile lines
    "compile.owner_field.name": "- **Name**: {value}",
    "compile.owner_field.occupation": "- **Occupation**: {value}",
    "compile.owner_field.industry_role": "- **Domain / role**: {industry} / {role}",
    "compile.owner_field.working_style": "- **Way of working**: {value}",
    "compile.owner_field.background": "- **Background**: {value}",
    "compile.owner_field.interests": "- **Long-standing interests**: {value}",
    "compile.owner_field.collab_mode": "collaboration mode {value}",
    "compile.owner_field.unspecified": "not provided",
    "compile.owner_field.unlabeled": "unlabeled",
    "compile.owner_field.list_separator": ", ",
    "compile.owner_field.detail_separator": "; ",
    # ───────────────────────────────── compile: the subject's declared environment (§2)
    # One key per state of each field, full sentences rather than a composed
    # "{value} — {origin}": an overlay in another language has to be able to reorder the
    # clause, and a half-translated sentence assembled from fragments is how that breaks.
    "compile.owner_env.section": _OWNER_ENV,
    "compile.owner_env.region": "- **Region**: {value} — on record for the subject.",
    "compile.owner_env.region_unknown": (
        "- **Region**: unknown — no city or country is on record for the subject. Do not "
        "infer one from the material; read local references (holidays, forms of address, "
        "office names) as unconfirmed context rather than as an established location."
    ),
    "compile.owner_env.timezone_provider": (
        "- **Timezone**: {value} — resolved for this material by this deployment."
    ),
    "compile.owner_env.timezone_profile": (
        "- **Timezone**: {value} — on record for the subject."
    ),
    "compile.owner_env.timezone_default": (
        "- **Timezone**: unknown — no timezone is on record for the subject, so this "
        "deployment's default **{value}** is in use. Dates are still counted in that zone, "
        "but it is the installation's assumption, not the subject's own setting."
    ),
    "compile.owner_env.timezone_unstated": "- **Timezone**: {value}.",
    "compile.owner_env.timezone_unknown": (
        "- **Timezone**: unknown — none was resolved for this round. Keep dates as the "
        "material words them and do not compute a calendar day of your own."
    ),
    "compile.owner_env.language": (
        "- **Language**: {value} — on record for the subject."
    ),
    "compile.owner_env.language_unknown": (
        "- **Language**: unknown — no language is on record for the subject, so **English** "
        "is used by default. That is a default, not a finding about the subject."
    ),
    "compile.owner_env.write_language": (
        "Write every claim and every document in the subject's language declared above — not "
        "in the language of this contract, and not in whichever language a given source "
        "happens to be in. Wording quoted verbatim from the material keeps its original "
        "language inside the quotation marks; everything you write around it — the claim "
        "itself, headings, labels, summaries — is in the subject's language."
    ),
    # Deliberately does NOT restate "every date you write is a day in that zone" — the task's
    # time anchor (compile.task.time_now) already says that, next to the actual date. This line
    # answers the other half, the one no anchor can: WHY this zone and not another.
    "compile.owner_env.day_grouping": (
        "The material of each round is grouped by calendar day in the timezone declared "
        "above; the task's time frame states which day \"today\" is in that zone."
    ),
    # ─────────────────────────────────────────────── compile: per-source treatments
    "compile.treatment.full": _TREATMENT_FULL,
    "compile.treatment.distill": _TREATMENT_DISTILL,
    "compile.treatment.card": _TREATMENT_CARD,
    # ─────────────────────────────────────────────── compile: the task (human turn)
    "compile.task.guidance_header": (
        "# Source-type notes for this round (apply to all material below)\n"
    ),
    "compile.task.treatment_header": "# Treatments used this round\n",
    "compile.task.time_header": "# Time frame for this round\n",
    "compile.task.time_now": (
        "- **This compile runs on**: {date} — the subject's own calendar day, in timezone "
        "{zone}. Every date below, and every date you write, is a day in that zone."
    ),
    "compile.task.time_zone_changed": (
        "- **The subject's timezone changed**: from {from_zone} to {to_zone} on {at}. Dates "
        "already recorded before that day were normalized under {from_zone} and are **not** "
        "rewritten — read them in that zone, and do not \"correct\" them."
    ),
    "compile.task.time_window": "- **This round's material occurred on**: {span} ({days} day(s))",
    "compile.task.time_relative_rule": (
        "- Normalize relative time in the material (\"yesterday\", \"last week\", \"next "
        "Monday\") to absolute dates **against the material's own occurrence date**, not "
        "against the compile date; when the reference point is unreliable, keep the original "
        "wording and mark it as unconfirmed."
    ),
    "compile.task.time_unknown": (
        "- **This round's material carries no occurrence time**: do not infer absolute dates; "
        "keep relative time as originally worded and mark it unconfirmed."
    ),
    "compile.task.sources_header": "# Material supplied to this compile\n",
    "compile.task.source_heading": "## source {source_id} — {title}",
    "compile.task.treatment_tag": "→ Treatment: **treatment={treatment}** (explained above)",
    "compile.task.block_line": "¶{index} {text}",
    "compile.task.outline_header": "# The whole of existing canonical (outline)\n",
    "compile.task.outline_note": (
        "These are all the documents currently in the owner's knowledge base, structure only, "
        "no bodies. Look here first for whether a subject already exists: **if it does, update "
        "it in place with `edit_claim` / `append_block` instead of creating another "
        "document**; when you need a body, get it with `read_document(path)` or "
        "`search_knowledge(query)`."
    ),
    "compile.task.outline_empty": "(no existing canonical yet; create documents with create_document)",
    "compile.task.outline_entry": "- `{path}` (type={doc_type}, {claims} claim(s)){tail}",
    "compile.task.outline_entry_tail": ": {headings}",
    "compile.task.retrieved_header": (
        "\n# Existing claims related to this round's material (auto-recalled, for alignment "
        "and updating)\n"
    ),
    "compile.task.retrieved_note": (
        "The claims below are existing knowledge retrieved against this round's material and "
        "**are not evidence for this round** — their purpose is to let you notice which entry "
        "should be updated and to avoid establishing a duplicate synonymous claim. Citing "
        "evidence still means going back to a ¶ interval in this round's material."
    ),
    # ─────────────────────────────────────────────── compile: tool descriptions
    "compile.tool.list_documents": "List the existing canonical document paths.",
    "compile.tool.read_document": "Read one document in full (anchors included).",
    "compile.tool.create_document": (
        "Create a document; the system assigns the doc_id and every anchor."
    ),
    "compile.tool.edit_claim": (
        "Rewrite the claim at the given anchor in place; the anchor is preserved automatically."
    ),
    "compile.tool.append_block": (
        "Add one claim at the end of a section; the anchor is assigned by the system."
    ),
    "compile.tool.finish_compile": "Call when there are no more writes; ends this compile.",
    "compile.tool.search_knowledge": (
        "Search **existing canonical claims** (L3) by query; returns the anchors of matching "
        "claims and the document paths they live in. Use it to judge whether a subject has "
        "already been recorded and which anchor to update, instead of creating another document."
    ),
    "compile.tool.search_source": (
        "Search the **raw material** (L1/L2) by query, to find corroboration or fill in "
        "context across sources. Note: only material supplied this round may be used as a "
        "citation source_id."
    ),
    "compile.tool.search_knowledge_unavailable": (
        "(no L3 retrieval port is wired this run, so search_knowledge is unavailable; you can "
        "still use read_document with an exact path)"
    ),
    "compile.tool.search_source_unavailable": (
        "(no L1/L2 retrieval port is wired this run, so search_source is unavailable; only "
        "the material supplied this round can be used)"
    ),
    "compile.tool.call_failed": "tool {name} call failed: {error}",
    # ─────────────────────────────────────────────── compile: write-tool results
    #
    # A tool's REPLY is as model-visible as its description: the agent reads it and decides
    # the next call from it. So the two travel together through the catalog — a deployment
    # that rewrites the descriptions but not the replies would still put framework wording
    # in front of the model on every successful write.
    "compile.tool.list_documents_empty": "(no documents yet)",
    "compile.tool.create_document_result": (
        "created {path} (doc_id={doc_id}); system-assigned anchors: {anchors}"
    ),
    "compile.tool.edit_claim_result": "edited claim c:{anchor_id} in {path} (anchor preserved)",
    "compile.tool.append_block_result": (
        "appended claim to {path} under '{heading}'; assigned anchor: {anchors}"
    ),
    "compile.tool.finish_compile_result": "compile finished",
    "compile.tool.unknown_tool": "unknown tool: {name}",
    # ─────────────────────────────────────────────── compile: write-tool rejections
    "compile.anchor.none": "(none)",
    "compile.anchor.edit_unknown_anchor": (
        "edit_claim rejected: anchor c:{anchor_id} is not in this document. Existing anchors: "
        "{existing}."
    ),
    "compile.anchor.edit_duplicate_anchor": (
        "edit_claim rejected: anchor c:{anchor_id} occurs more than once in the document; fix "
        "the duplicate anchor first."
    ),
    "compile.anchor.edit_extra_anchor": (
        "edit_claim rejected: new_block contains other anchors. One edit_claim rewrites "
        "exactly one claim; use append_block to add a claim."
    ),
    "compile.anchor.append_empty_heading": "append_block rejected: the section heading cannot be empty.",
    "compile.anchor.append_anchor_present": (
        "append_block rejected: a new block does not need to carry an anchor, the system "
        "assigns it. To rewrite an existing claim use edit_claim."
    ),
    "compile.anchor.move_unknown_anchor": (
        "claim move/merge rejected: anchor c:{anchor_id} is not in this document. Existing "
        "anchors: {existing}."
    ),
    "compile.anchor.move_duplicate_anchor": (
        "claim move/merge rejected: anchor c:{anchor_id} occurs more than once in the "
        "document; fix the duplicate anchor first."
    ),
    "compile.anchor.move_missing_anchor": (
        "claim move rejected: the target block carries no anchor, so it cannot be moved as an "
        "existing claim."
    ),
    "compile.patch.read_missing": "read_document rejected: document {path} does not exist.",
    "compile.patch.create_path_not_allowed": (
        "create_document rejected: path {path} is not within the skill's ownership templates. "
        "Allowed templates: {templates}."
    ),
    "compile.patch.create_exists": (
        "create_document rejected: document {path} already exists; rewrite an existing claim "
        "with edit_claim, add a claim with append_block."
    ),
    "compile.patch.move_target_missing": (
        "move_claim rejected: target document {to_path} does not exist; create_document first, "
        "then move."
    ),
    # ─────────────────────────────────────────────── compile gate feedback
    "gate.feedback_header": (
        "# gate rejected: the mechanical checks below did not pass. Repair with the "
        "claim-level tools, then call finish_compile again."
    ),
    "gate.anchor_continuity": (
        "existing anchor c:{anchor} disappeared after this compile (v1 has no deletion "
        "channel; claims are only added or revised, never removed)."
    ),
    "gate.anchor_uniqueness": (
        "anchor c:{anchor} is duplicated (also in {other_path}); an anchor is a repo-unique "
        "identity."
    ),
    "gate.frontmatter_missing": "frontmatter is missing the required field {key}.",
    "gate.anchor_coverage": (
        "content block has no anchor and will not enter the claim index: \"{preview}…\". "
        "Every claim block needs a system anchor."
    ),
    "gate.citation_unknown_source": (
        "citation refers to source_id={source_id}, which was not supplied this round."
    ),
    "gate.citation_out_of_range": (
        "citation [{source_id} ¶{start}-{end}] is out of range (that source has {count} "
        "blocks, legal interval 0..{last})."
    ),
    "gate.claim_without_provenance": (
        "newly created claim has no provenance at all: \"{preview}…\" (anchor c:{anchor}). "
        "Every claim added this round must link back to its basis — either `[cite: "
        "<source_id> ¶a-b]` pointing at this round's material, or an in-text reference to the "
        "existing anchor `c:<id>` it derives from; if it is only a section label or a "
        "structural line, do not write it as a standalone claim block."
    ),
    "gate.link_self_reference": (
        "link points at the current document itself: `{href}`. Links are only for pointing at "
        "other subjects; self-reference is noise and the projection layer discards it."
    ),
    "gate.link_dead": (
        "link target does not exist: `{href}` (resolves to `{target}`). Either create that "
        "subject's document with create_document first, or do not write the link — a dead "
        "link is a dead end in the knowledge graph."
    ),
    "gate.path_not_owned": (
        "path is not within the skill's ownership templates: {templates}."
    ),
    # ─────────────────────────────────────────────── evolve gate feedback
    "gate.evolve.feedback_header": (
        "# evolve gate rejected: the mechanical checks below did not pass. Repair with the "
        "tools, then call finish_evolve again."
    ),
    "gate.evolve.citation_unknown_source": (
        "citation refers to source_id={source_id}, which does not exist in the store."
    ),
    "gate.evolve.citation_out_of_range": (
        "citation [{source_id} ¶{start}-{end}] is out of range (that source has {count} "
        "blocks, legal interval 0..{last})."
    ),
    "gate.evolve.path_not_owned": (
        "path is not within the new skill's ownership templates: {templates}."
    ),
    # ─────────────────────────────────────────────── source types (ingest seam)
    "source.guidance_header": (
        "[First-party data notes]\n"
        "· Data shape: {data_context}\n"
        "· Feature intent: {app_context}"
    ),
    "source.context_stream.data_context": (
        "This is a structured work-context stream. Speakers have already been separated by "
        "channel into the owner and numbered participants (the same number refers to the same "
        "person throughout). The stream may have been produced by an upstream recognizer and "
        "can carry crosstalk and recognition errors — the words that change meaning (names, "
        "numbers, dates, negations, who is responsible) are often the unreliable ones."
    ),
    "source.context_stream.app_context": (
        "A context stream exists to settle the work the owner takes part in into knowledge "
        "that is later actionable, explainable and auditable: product hypotheses, technical "
        "decisions, experiments, commitments, risks and open questions. The owner is the "
        "subject of this knowledge — surface what will be useful in the future out of a large "
        "volume of context; do not produce verbatim minutes. "
        "Record provenance as it stands, whoever spoke: attribution is **tracing, not "
        "adjudication** — when unsure whether something is the owner's, leave it uncertain "
        "rather than concluding either way. Record commitments at the certainty they actually "
        "had: a proposal is not a settled decision, an unclear key value stays pending, and "
        "nothing gets promoted to fact."
    ),
    "source.preamble.owner_default": "the owner",
    "source.preamble.stream_scene_default": "a conversation",
    "source.preamble.stream_lead": (
        "This is {owner} {when}in {scene}, {blocks} message(s){part}."
    ),
    "source.preamble.stream_part": ", part {part}/{part_count} that day",
    "source.preamble.stream_role_spoke": "{owner} spoke {turns} time(s)",
    "source.preamble.stream_role_silent": "{owner} was present but did not speak in this part",
    "source.preamble.stream_mentions": ", was @-mentioned {mentions} time(s)",
    "source.preamble.stream_replies": ", {replied} message(s) reply to them",
    "source.preamble.stream_tail": "{lead} {role}.",
    "source.preamble.document_kind_default": "document",
    "source.preamble.document_other_author": "someone else",
    "source.preamble.document_title": ", titled \"{title}\"",
    "source.preamble.document_parent": ", filed under the parent document \"{parent_title}\"",
    "source.preamble.document_created": "created on {created}",
    "source.preamble.document_updated": "last updated {updated}",
    "source.preamble.document_created_and_updated": "{created}, {updated}",
    "source.preamble.document_lead": "This is a {kind} by {who}{when}{title}{parent}. ",
    "source.preamble.document_when": " {when}",
    "source.preamble.document_stance_owner": (
        "{owner} is the author, so judgments in it belong to them by default."
    ),
    "source.preamble.document_stance_other": (
        "{owner} is a reader and not the author; judgments in it belong to {author} and must "
        "not be recorded as their own decisions."
    ),
    "source.preamble.reference": (
        "This is external material{title} supplied for {owner} to consult, not their own "
        "statement. The claims in it belong to its author; compile it only where it really "
        "constitutes a fact useful to them later, and label the source as it stands."
    ),
    "source.preamble.document_unknown": (
        "This is a document{title} imported by {owner}; the material supplies no author and no "
        "authoring time, so judgments in it must not be assumed to be their own."
    ),
    "source.preamble.fallback": (
        "This is a piece of material{title} in {owner}'s knowledge base; the material supplies "
        "no provenance and no time, so attribution and time both stay pending."
    ),
    "source.preamble.title_quoted": " \"{title}\"",
    # ─────────────────────────────────────────────── ingest rendering
    "ingest.owner_label": "Owner",
    "ingest.other_label": "Participant{n}{suffix}",
    "ingest.speaker_alias": " ({speaker_id})",
    "ingest.owner_wrapped": "Owner ({label})",
    "ingest.turn_line": "{label}: {text}",
    "ingest.email.subject": "Subject: {subject}",
    "ingest.email.attachments": "Attachments: ",
    "ingest.semantic.rubric": _SEGMENTER_RUBRIC,
    "ingest.semantic.human": (
        "Below are content blocks numbered {lo}..{hi} ({count} blocks). Each line is "
        "\"number:content\" (the number before the colon, as with grep -n). Return the start "
        "number of each semantic segment:\n\n{listing}"
    ),
    # ─────────────────────────────────────────────── recall: the shared spine
    "recall.spine": _SPINE,
    "recall.cite.source_level": (
        "source level is enough in this scenario (`[cite: <source_id>]`, the ¶ paragraph may be "
        "omitted; include a source when you reliably have one, do not force one when you do "
        "not) — it is a thread left for later tracing, not a hard target of this scenario."
    ),
    "recall.cite.precise": "cite down to the paragraph (`[cite: <source_id> ¶a-b]`).",
    "recall.close.answer_honestly": (
        "- When the evidence in front of you does not cover what the owner is asking for, \"no "
        "relevant record\" is the faithful answer; do not restate the input or add prefixes\n"
        "  like \"according to the records\"."
    ),
    "recall.close.suggestion": (
        "- A context card is an unsolicited addition to the context. It has to stand on its\n"
        "  own — do not restate the input stream, do not announce what is coming, and do not "
        "write empty cards saying \"no relevant record\"; when there is no card to write, "
        "suggestions is simply an empty list,\n"
        "  and an empty list is this interface's normal return value."
    ),
    # ─────────────────────────────────────────────── recall: the mode contracts
    "recall.fast.contract_head": _FAST_CONTRACT_HEAD,
    "recall.deep.contract_head": _DEEP_CONTRACT_HEAD,
    "recall.briefing.contract_head": _BRIEFING_CONTRACT_HEAD,
    "recall.suggestion.contract_head": _LIVE_CONTEXT_HEAD,
    "recall.suggestion.detail_contract": _DETAIL_CONTRACT,
    "recall.suggestion.focus.general": (
        "**Scope of attention this round**: any concept or fact in the whole workstream worth "
        "adding, whoever said it."
    ),
    "recall.suggestion.focus.owner": (
        "**Scope of attention this round**: generate cards only for what the owner put in.\n"
        "Participants' content is still read in full, but only as context for understanding — "
        "do not generate cards for things only participants mentioned."
    ),
    "recall.suggestion.focus.other": (
        "**Scope of attention this round**: generate cards only for what the participants put "
        "in.\nThe owner's content is still read in full, but only as context for understanding "
        "— do not generate cards for things only the owner mentioned."
    ),
    # ─────────────────────────────────────────────── recall: human-turn sections
    "recall.section.profile_header": "# Owner profile",
    "recall.section.claims_header": "# claim notes ({count})",
    "recall.section.claims_empty": "(no hits this retrieval)",
    "recall.section.windows_header": "# raw excerpts ({count})",
    "recall.section.input": "Owner input: {question}",
    "recall.section.transcript_header": "# Stream transcript (last {turns} turn(s))",
    "recall.section.already_shown_header": (
        "# Already surfaced in this conversation (do not repeat a card)"
    ),
    "recall.section.passages_header": "raw excerpts",
    "recall.passage_truncated": (
        "\n…(truncated; this block is long — deep can fetch the full text with fetch_verbatim)"
    ),
    # ─────────────────────────────────────────────── recall: knowledge base glance
    # The library's SHAPE, present for every question: which filing families exist, what is
    # filed under each, how developed each document is. Not the contents — this is what makes
    # "open that document and follow its links" and "what does this base even hold" possible
    # from the answering side, which retrieval hits alone never conveyed.
    "recall.glance.header": "# Knowledge base at a glance",
    "recall.glance.note": (
        "The layout of the compiled knowledge base: the filing families it declares, the "
        "documents filed under each, and how many claims each carries. This is the shape, not "
        "the contents — open a document to read it."
    ),
    "recall.glance.empty": (
        "(the knowledge base holds no documents yet; the families below are where material "
        "will be filed)"
    ),
    "recall.glance.family_heading": "## {template}",
    "recall.glance.family_blurb": "  ↳ {blurb}",
    "recall.glance.family_empty": "  (no documents filed here yet)",
    "recall.glance.entry": "- `{path}` — {title} ({claims} claim(s){tail})",
    "recall.glance.entry_tail_updated": ", updated {updated}",
    "recall.glance.family_more": "- …and {count} more document(s) in this family",
    "recall.glance.unfiled_heading": "## (documents outside every declared family)",
    "recall.glance.flat_heading": "## Documents",
    "recall.glance.truncated": "…({count} more line(s) omitted at the glance budget)",
    # ─────────────────────────────────────────────── recall: fast's glance selection pass
    # A single small call that runs CONCURRENTLY with retrieval: given the glance and the
    # question, name the documents worth reading in full. Selecting nothing is the normal
    # answer — retrieval already covers most questions, and this pass exists only for the
    # ones where the whole of one document is the evidence.
    "recall.fast.select.contract": (
        "You are given the layout of a compiled knowledge base and one question. Your only job "
        "is to name the documents that must be read IN FULL to answer it well.\n\n"
        "You are not answering the question and you are not searching. A separate retrieval "
        "pass is already fetching the individual claims and raw excerpts that match the "
        "question's wording. You exist for what that pass cannot do: recognise, from the "
        "layout alone, that one whole document IS the subject being asked about — because the "
        "question names it, or names the person/product/topic it holds, or asks something "
        "(a history, a comparison, an overall state) that only the full document answers.\n\n"
        "Return an empty list when no document stands out that way. That is the normal result, "
        "not a failure: a question already covered by matching fragments needs nothing here, "
        "and naming a document just because it is loosely related crowds out the evidence that "
        "does match. Choose at most {cap}, fewest first, in order of how central they are.\n\n"
        "Return the paths exactly as they appear in the layout. A path that is not in the "
        "layout does not exist and will be discarded."
    ),
    "recall.fast.select.request": (
        "{glance}\n\nQuestion: {question}\n\n"
        "Which of the documents above must be read in full to answer this? Paths only, at most "
        "{cap}, empty if none."
    ),
    "recall.fast.select.documents_header": "# full documents ({count})",
    "recall.fast.select.document_heading": "## {path}",
    # ─────────────────────────────────────────────── recall: deep's document tools
    # Same names and same shapes as the compile tool face (one addressing vocabulary across
    # the system): the answerer walks canonical exactly the way the compiler does.
    "recall.deep.tool.list_documents": (
        "List the knowledge base's document paths, so you can open one by path."
    ),
    "recall.deep.tool.list_documents_doc": (
        "List every canonical document path in the knowledge base. Use it when the glance was "
        "truncated or you need the exact spelling of a path."
    ),
    "recall.deep.tool.list_documents_empty": "(the knowledge base holds no documents)",
    "recall.deep.tool.read_document": (
        "Read one document in full by path — claims, anchors and its links to other documents, "
        "which you can follow by reading those paths in turn."
    ),
    "recall.deep.tool.read_document_doc": (
        "Read one canonical document in full by path. The text keeps its claim anchors and its "
        "markdown links to other documents; follow a link by calling read_document on its "
        "target path."
    ),
    "recall.deep.tool.read_document_not_found": (
        "(no document at {path}; use list_documents for the exact paths)"
    ),
    "recall.agentic.budget_notice": (
        "The retrieval budget is spent — answer directly from the evidence already obtained."
    ),
    # ─────────────────────────────────────────────── recall: deep tools
    "recall.deep.tool.search_claims": (
        "Re-search the claim notes (the structured knowledge face) with different keywords or "
        "from a different angle."
    ),
    "recall.deep.tool.search_claims_doc": (
        "Re-search the claim notes (structured personal knowledge) with different keywords or "
        "angles; returns hits with anchors and provenance."
    ),
    "recall.deep.tool.search_claims_empty": (
        "(no claim notes matched; try different keywords, or use search_content to search "
        "uncompiled original text)"
    ),
    "recall.deep.tool.search_content": (
        "Search raw fragments (the uncompiled content face, with context and provenance)."
    ),
    "recall.deep.tool.search_content_doc": (
        "Search raw fragments (with context and provenance), covering original content never "
        "compiled into claims."
    ),
    "recall.deep.tool.search_content_empty": (
        "(no raw fragments matched; try different keywords, or use search_claims to search "
        "structured knowledge)"
    ),
    "recall.deep.tool.fetch_verbatim": (
        "Pull a fragment of a source's original text verbatim (checking provenance / getting "
        "the original)."
    ),
    "recall.deep.tool.fetch_verbatim_doc": (
        "Pull a fragment of a source's original text verbatim. The locator is shaped like "
        "{\"blocks\": [start, end]} or {\"section\": [...]}."
    ),
    "recall.deep.tool.fetch_verbatim_failed": (
        "fetch_verbatim failed: {error}. Take source_id from the source id labelled in the "
        "evidence's provenance; the locator is shaped like {\"blocks\": [start, end]} or "
        "{\"section\": [...]}"
    ),
    "recall.deep.tool.fetch_verbatim_empty": "(that locator returned no content)",
    # ─────────────────────────────────────────────── recall: briefing pack + tools
    "recall.briefing.query_section_header": "# Retrieved knowledge (scope.query)",
    "recall.briefing.query_claims_header": "## Retrieved related claim notes (query: {query})",
    "recall.briefing.query_excerpts_header": "## Retrieved related raw excerpts",
    "recall.briefing.source_section_header": "# Source anchoring (scope.source_ids)",
    "recall.briefing.source_heading": "### source {source_id}",
    "recall.briefing.material_cards_header": "Material cards:",
    "recall.briefing.citing_claims_header": "claim notes citing this source:",
    "recall.briefing.outline_header": "Document structure (section outline):",
    "recall.briefing.outline_more": "- …({count} more section(s), omitted)",
    "recall.briefing.excerpts_header": "Raw excerpts:",
    "recall.briefing.provenance_suffix": "  (source {cites})",
    "recall.briefing.budget_truncated": "\n…(truncated by budget)",
    "recall.briefing.tool.fetch_verbatim": (
        "L0 verbatim fetch of a fragment of the named source."
    ),
    "recall.briefing.tool.fetch_verbatim_doc": (
        "L0 verbatim fetch: return the original text of the given source's locator fragment. "
        "The locator is shaped like {\"section\": [...]} or {\"blocks\": [start, end]}."
    ),
    "recall.briefing.tool.fetch_verbatim_failed": "fetch_verbatim failed: {error}",
    "recall.briefing.tool.search_knowledge": (
        "Search related claims and raw fragments within the knowledge pack's range (with "
        "context and provenance)."
    ),
    "recall.briefing.tool.search_knowledge_doc": (
        "Search the knowledge pack's range for claims and raw fragments related to the query "
        "(with context), returning result text with provenance."
    ),
    "recall.briefing.tool.claims_header": "## matching claim notes",
    "recall.briefing.tool.passages_header": "matching raw excerpts",
    "recall.briefing.tool.search_empty": (
        "(nothing relevant found within the knowledge pack's range; try different keywords, or "
        "use fetch_verbatim to pull the original text of a known source)"
    ),
    # ─────────────────────────────────────────────── recall: the owner profile block
    "recall.profile.name": "Name: {value}",
    "recall.profile.industry_role": "Industry · role · level: {value}",
    "recall.profile.occupation": "Occupation: {value}",
    "recall.profile.location": "Based in: {value}",
    "recall.profile.response_language": (
        "Reply language: {value} (unless this input asks otherwise)"
    ),
    # ─────────────────────────────────────────────── live context expansion (service)
    "recall.suggestion.detail_card": (
        "# Card\nkind: {kind}\nTitle: {title}\nBody: {body}\nTrigger fragment: {trigger}"
    ),
    "recall.suggestion.detail_sources_header": "# Cited source text ({count} passage(s))",
    "recall.suggestion.detail_source_head": (
        "source {source_id} blocks [{block_start}, {block_end}]"
    ),
    "recall.suggestion.detail_no_sources": (
        "# Cited source text\n(this card has no directly fetchable citation, so it can only be "
        "expanded from the card itself)"
    ),
    # ─────────────────────────────────────────────── persona generation
    "persona.profile_instruction": _PROFILE_INSTRUCTION,
    # ─────────────────────────────────────────────── skill: derive + labels
    "skill.derive_contract": _asset("packs", "derive_contract.md"),
    "skill.derive.human": (
        "occupation: {occupation}\nbio: {bio}\ninterests: {interests}"
    ),
    "skill.derive.empty": "(none)",
    "skill.derive.interest_separator": ", ",
    "skill.claim_label.clause_marker": "strength prefix label",
    "skill.claim_label.strong.label": "firm",
    "skill.claim_label.strong.name": "Established",
    "skill.claim_label.strong.description": (
        "An owner, condition or time is explicit, or the relationship/decision is confirmed by "
        "both sides. It is re-tiered forward as evidence changes, keeping the old tier rather "
        "than silently erasing it."
    ),
    "skill.claim_label.medium.label": "forming",
    "skill.claim_label.medium.name": "In progress",
    "skill.claim_label.medium.description": (
        "The direction is clear but one key slot is missing (time undecided / awaiting written "
        "confirmation / verbal agreement not yet acted on). Once the key slot is filled it is "
        "promoted forward to Established as the evidence allows."
    ),
    "skill.claim_label.weak.label": "loose",
    "skill.claim_label.weak.name": "Mentioned only",
    "skill.claim_label.weak.description": (
        "A one-off idea, a hypothesis, a second-hand account, or a proposal that was not "
        "accepted. It is promoted forward once supported; when unsure, drop a tier rather than "
        "raise one."
    ),
    # ─────────────────────────────────────────────── evolve
    "evolve.phase1_contract": _asset("evolve", "phase1_contract.md"),
    "evolve.phase2_contract": _asset("evolve", "phase2_contract.md"),
    "evolve.task_header": "# This task: schema evolve",
    "evolve.task.docs_header": "# Existing canonical documents (all of them)",
    "evolve.task.docs_empty": "(no documents yet)",
    "evolve.task.rationale_header": "# Basis for this schema evolve",
    "evolve.task.families_header": (
        "# Newly added template families (move meaning that belongs in these families out of "
        "topics and into place)"
    ),
    "evolve.task.families_empty": "(none)",
    "evolve.tool.list_documents": "List the existing canonical document paths.",
    "evolve.tool.read_document": "Read one document in full (anchors included).",
    "evolve.tool.create_document": (
        "Create a document; the system assigns the doc_id and every anchor."
    ),
    "evolve.tool.move_claim": (
        "Move an anchored claim block verbatim to the end of the named section of the target "
        "document, anchor unchanged; the target must exist (create_document first)."
    ),
    "evolve.tool.edit_claim": (
        "Rewrite the claim at the given anchor in place; the anchor is preserved automatically."
    ),
    "evolve.tool.append_block": (
        "Add one claim at the end of a section; the anchor is assigned by the system."
    ),
    "evolve.tool.delete_claim": (
        "Remove a claim block entirely (only for merging equivalent redundancy; the anchor "
        "enters the dropped list)."
    ),
    "evolve.tool.search_knowledge": (
        "Search the knowledge base again by query (L1/L2/L3) to find evidence from another "
        "angle."
    ),
    "evolve.tool.fetch_source": (
        "Fetch the original text of a source's block interval verbatim, to check a citation."
    ),
    "evolve.tool.finish_evolve": (
        "Call when there is nothing more to do; ends this reorganization."
    ),
    "evolve.tool.search_unavailable": (
        "(no retrieval port is wired this run, so search_knowledge is unavailable)"
    ),
    "evolve.tool.fetch_unavailable": (
        "(no source-text port is wired this run, so fetch_source is unavailable)"
    ),
    "evolve.tool.call_failed": "tool {name} call failed: {error}",
    "evolve.tool.delete_claim_result": (
        "deleted c:{anchor_id} from {path} (merged/discarded; the anchor will enter the "
        "dropped list)"
    ),
    # The rest of the evolve write-tool replies, for the same reason as the compile ones.
    "evolve.tool.anchors_none": "(none)",
    "evolve.tool.list_documents_empty": "(no documents yet)",
    "evolve.tool.create_document_result": (
        "created {path} (doc_id={doc_id}); system-assigned anchors: {anchors}"
    ),
    "evolve.tool.move_claim_result": (
        "moved c:{anchor_id} from {from_path} to {to_path} under '{heading}' "
        "(anchor preserved verbatim)"
    ),
    "evolve.tool.edit_claim_result": "edited claim c:{anchor_id} in {path} (anchor preserved)",
    "evolve.tool.append_block_result": (
        "appended claim to {path} under '{heading}'; assigned anchor: {anchors}"
    ),
    "evolve.tool.finish_evolve_result": "evolve finished",
    "evolve.tool.unknown_tool": "unknown tool: {name}",
    "evolve.propose.skill_header": "# Current skill guidance (composed pack families included)",
    "evolve.propose.templates_header": "# Current path families (ownership templates)",
    "evolve.propose.events_header": "# Incremental compile events since the last evolve",
    "evolve.propose.events_empty": "(no incremental compile events since the last evolve)",
    "evolve.propose.event_line": "- {path}: {added} added, {revised} revised",
    "evolve.propose.unknown_path": "(unknown path)",
    "evolve.propose.docs_header": "# Current canonical document list",
    "evolve.propose.docs_empty": "(no canonical documents yet)",
    "evolve.recovery_heading": "Window update",
    "evolve.commit_message": (
        "schema evolve: reorganized {moved} claim(s) into {new_documents} new document(s), "
        "merged {merged}."
    ),
    "evolve.service.fetch_failed": "(fetch_source failed: {error})",
    "evolve.service.search_empty": "(no raw fragment matched \"{query}\".)",
    # ─────────────────────────────────────────────── compile worker retrieval replies
    "compile.worker.search_failed": "(retrieval failed: {error})",
    "compile.worker.knowledge_empty": "(no hits for \"{query}\" in existing canonical.)",
    "compile.worker.source_empty": "(no hits for \"{query}\" in the raw material.)",
    # ─────────────────────────────────────────────── per-version contract clauses
    "contract.rule.citation_granularity": (
        "Each claim links back only to the source ¶ intervals that directly support it; when "
        "several independent passages support it, list them separately in ascending ¶ order as "
        "`[cite: <sid> ¶a-b]` rather than merging them into one large interval spanning "
        "unrelated paragraphs."
    ),
    "contract.rule.citation_shape": (
        "One `[cite: …]` marker holds exactly one source_id and one ¶ interval. For several "
        "supporting passages, place several markers side by side (`[cite: <sid> ¶0-2] [cite: "
        "<sid> ¶7]`); do not pile ranges into one marker with commas, and do not list several "
        "sources in one marker with semicolons."
    ),
    "contract.rule.strength_labels": (
        "Commitment and relationship claims open with the skill's controlled strength prefix "
        "label (【firm】/【forming】/【loose】), which the projection layer uses to tier the "
        "presentation; use only those three tiers."
    ),
    # ───────────────────────────────────────────────── evaluation (optional judge arms)
    # The evaluation package is read-only and its mechanical mode never calls a model. These
    # six keys are the ONLY model-visible prose it can emit, and only in its `full` mode: two
    # judges, each consulted for exactly one thing the character matcher already rejected.
    #
    # `eval.qa.*` grades an ANSWER produced for a question. `eval.truth_judge.*` grades a
    # CANONICAL CLAIM, which was written for a reader rather than for a question — a
    # distinction worth its own prose, because the similarity threshold group B applies was
    # calibrated on short label-shaped claims and a compiler that legitimately rewrites a fact
    # into 170 characters of threaded prose scores below it while stating the fact perfectly.
    # The judge arm is what stops that from reading as a recall failure.
    "eval.qa.judge_system": (
        "You are grading one answer against one expected statement, and nothing else.\n\n"
        "Answer YES only when the answer actually carries the expected statement — the same "
        "fact, not merely the same topic, and not a weaker or hedged version of it. Answer NO "
        "when the answer omits it, contradicts it, states it about a different subject or "
        "period, or only gestures at where it might be found.\n\n"
        "You are not judging style, completeness, or whether the answer is useful. Extra "
        "correct material is not a fault; a missing expected statement is.\n\n"
        "Reply with YES or NO on the first line, then one short line naming the evidence in "
        "the answer that decided it."
    ),
    "eval.qa.judge_user": (
        "Question:\n{question}\n\n"
        "Expected statement:\n{expected}\n\n"
        "Answer under grading:\n{answer}"
    ),
    "eval.qa.judge_verdict_yes": "YES",
    "eval.truth_judge.system": (
        "You are checking one written claim against one labelled fact, and nothing else.\n\n"
        "Answer YES when the claim states that fact — the same fact about the same subject and "
        "the same period — however differently it is worded, ordered, or embedded in "
        "surrounding prose. Paraphrase is not a defect. A claim that carries the fact plus "
        "additional correct material still answers YES.\n\n"
        "Answer NO when the claim omits the fact, contradicts it, states it about a different "
        "subject or period, states only a weaker or hedged version of it, or merely names the "
        "topic the fact belongs to. A claim that says a decision was made without saying what "
        "was decided does not carry the decision.\n\n"
        "You are not judging wording, completeness, or whether the claim is well written.\n\n"
        "Reply with YES or NO on the first line, then one short line naming what in the claim "
        "decided it."
    ),
    "eval.truth_judge.user": (
        "Labelled fact:\n{statement}\n\n"
        "Claim under check:\n{claim}"
    ),
    "eval.truth_judge.verdict_yes": "YES",
}
