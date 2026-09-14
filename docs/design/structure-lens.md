# The structure lens — an outside reading of the library's shape

**English** | [简体中文](structure-lens.zh-CN.md)

## 1. Why

The Steward works inside the library, one source at a time. Every compile is a local
decision made under the contract, and each one can be right while the sum drifts: a
project page that quietly fills with session narration, an evolution page whose dated
sections arrive in ingest order rather than in time, a stray heading that renames a page,
a subject that exists twice under two spellings, a family of pages that nothing links to.
None of these is a fabrication — every claim still cites its span — and none is visible
from where the Steward stands. They are visible only from outside, to a reader who takes
the whole library in at once, carries the framework's own idea of what a good, evolvable
knowledge layout looks like, and does not care how any page came to be the way it is.

The console's Graph view was the first attempt at that reader, and it stopped at the
instrument: it counted dead ends and arrival-blind pages and printed the three largest
numbers. It said nothing about what a number costs the Owner, nothing about what to do,
and nothing reached the Steward, so the same drift continued in the next round. This
document replaces it with the **structure lens**: a derived, model-free reader of the
canonical library whose product is a **report** — findings, each with its evidence, its
cost, and its recommendation — read by the Owner in the console and by anyone, the
Steward included, at the terminal.

Three rulings fix the shape:

- **A finding is addressed to someone and says what to do.** Every finding names the
  pages it is about, the sentences or counts that show it, what it costs a reader or a
  retrieval, and one recommended action with an actor: the Steward in an ordinary round,
  the Owner as a decision, or the mechanism itself. A number with no consequence and no
  action is not a finding.
- **What can be decided mechanically is refused at the write, never advised.** A heading
  inside a claim block, a body with no real line breaks, a title that would shadow a
  sibling — the lens reports the instances a library already holds, and the gate refuses
  new ones. Advising the model to avoid a mechanical fault is the persuasion the framework
  forbids.
- **How a finding reaches the Steward is designed separately, after the Owner has read
  the report.** Putting a finding into another job's context is not a neutral act: it
  changes what the model writes, under a bound it did not choose, about a page it may not
  be reading. This version gives the Steward a face it can consult (`pkc lens`) and
  nothing it cannot decline to look at. The forcing point, the kept decline record and the
  evolve evidence are sketched in §9 as the next design, not built here.

The lens is derived and model-free. It reads canonical and the contract's path templates,
writes nothing to canonical, and is computed from canonical alone; it keeps no state of
its own in this version. It is a core module with two read faces (an HTTP route and a CLI
command); becoming an index component is the step §9 describes.

## 2. What the lens reads

- Every canonical document at one ref (HEAD by default; any ref for snapshot compare),
  through the read-only canonical face. Archived documents are excluded from every count
  and appear only under their own finding.
- The active skill's `path_templates`, to know the families and to fold a closed volume
  (`<doc>/aNN.md`) onto its open page — the same rule as `compile/patch.py::path_allowed`
  and `history_volume_owner`. A **subject** is one open page with its volumes; claims,
  characters and links of a volume belong to the subject.
- **Family roles**, derived from the templates by name: a template whose last segment is
  `overview.md` is the family hub; `evolution.md` the chronology; a directory named
  `features`, `decisions` (or `features/{slug}.md` etc.) a child family; `owner/…` the
  Owner's views; `memory/people`, `memory/topics` the memory families. The lens learns
  what a contract expects of a family from these roles and from nothing else; a contract
  with none of these names gets only the family-agnostic lenses. Roles are a table in
  `core/lens/families.py`, not prose.
- An **edge** is a markdown link whose href ends in `.md`, inside a claim block or in the
  overview region, resolved against the document's directory, fragment stripped; the same
  parser as the gate (`compile/links.py`), used through it. A volume's edges are
  re-attributed to its subject; a subject's link to its own volume is not an edge.
- A **claim** is one anchor in the ledger, counted as `canonical_glance.claim_count`
  counts it: overview blocks are not claims. (The old Graph view counted them; the lens
  agrees with core.)

## 3. The report

```
Report
  ref                canonical ref the report was read at
  read_at            ISO time (derived; not part of the finding keys)
  subjects, files, claims, edges         the base counts
  score              0–100, §3.3
  findings[]         Finding, ordered §3.4
  families[]         FamilyRow (name, pages, claims, share)   for the balance table

Finding
  key          stable id: "<lens>:<path or family>:<evidence hash>" — same evidence, same key
  lens         one of the lens ids in §4
  level        "principle" | "drift" | "shape"
  actor        "steward" | "owner" | "mechanism"
  paths[]      the subjects it is about (open-page paths; a volume is named by its page)
  targets[]    the other paths involved (missing link targets, the twin page, …)
  evidence[]   verbatim strings from the library only — a path, a title, a heading, a
               date, an href, a source id — ≤ 5, each ≤ 200 chars; counts and shares are
               fields of `impact`/`action` and are spoken there, never listed bare
  impact       {key, fields, text: {en, zh}}   what it costs — the catalog key, its
               fields, and the sentence rendered from the catalog in both packs
  action       {key, fields, text: {en, zh}}   what to do, addressed to `actor`
  weight       0–1, the share of the base it touches (for ordering)
  decision     null in this version — reserved for the Steward's kept decline (§9)
```

### 3.1 Levels

- **shape** — a page is malformed in a way the write mechanism should have refused. The
  actor is `mechanism`: the gate rule that now refuses it is named, and the existing
  instance is listed for a repair. The Steward is not asked to judge it.
- **drift** — a page falls short of what the contract expects of its family, in a way one
  ordinary round can fix on that page. The actor is `steward`: the action is written to
  the Steward, and reaches it in this version only through `pkc lens` (§5.2).
- **principle** — the library's layout is wrong in a way no single page fixes: a subject
  duplicated across paths, a family with no pages, a project no other page reaches, a
  catch-all page. The actor is `owner`: the console shows it as a decision the Owner
  owns; how it becomes a Steward task is part of §9.

### 3.2 Text through the catalog

`impact` and `action` are prompt-catalog keys (`lens.<lens>.impact`, `lens.<lens>.action`)
with named fields. The report carries each sentence already rendered, in English from the
catalog and in Chinese from the language pack (`text.en`, `text.zh`), so the console shows
the sentence for its locale and keeps no copy of it; `pkc lens` prints the active pack's.
One catalog, one wording, every face — an application that rewords a key through the
overlay seam changes what every reader sees.

### 3.3 Score

One number the Owner can watch between snapshots, and nothing more: **the share of
subjects that no open finding names**, as a whole number 0–100. A subject named by any
finding — in `paths`, whichever the level — is not clean; a principle finding names every
page it is about. It is not a grade and it is not a weighted sum: a weighted sum over a
library with hundreds of findings sits at zero and moves for nothing, while "how much of
the base has nothing to fix" moves by one page each time one page is fixed. The compare
tab shows its delta with the finding counts that moved it.

### 3.4 Order

Principle before drift before shape; within a level by `weight` descending; then by lens
id; then by path. The console's headline — the three things to do first — takes the first
finding of each of the three highest-ranked **lenses**, one per lens, so three islands
never crowd out a duplicate subject and a malformed page.

## 4. The lenses (v1)

Every lens is mechanical and model-free. A predicate named here is the whole predicate.

### 4.1 Navigability

| id | level | predicate | evidence |
|---|---|---|---|
| `nav.dead_end` | drift | subject with out-degree 0 | — |
| `nav.arrival_blind` | drift | subject with in-degree 0 | claims it holds |
| `nav.dead_link` | shape | a link to a path no document has | the href |
| `nav.hub_incomplete` | drift | a family hub (`overview.md`) that does not link to every page in its own subtree (features, decisions, evolution) | the missing targets |
| `nav.chronology_unlinked` | drift | an `evolution.md` with ≥ 3 dated sections and no link to any feature or decision page of its project, when such pages exist | count of children |
| `nav.decision_unlinked` | drift | a `decisions/*.md` page with no outbound link | — |
| `nav.mention_unlinked` | drift | a page whose claim text names another live subject's exact title (≥ 4 chars, not its own) N ≥ 3 times and never links it | the title, N |
| `nav.island` | principle | a project directory none of whose pages has an edge to or from any page outside the project | pages, claims |

`nav.dead_end` and `nav.arrival_blind` are each **one finding for the whole library**
(`paths` = every subject affected, evidence = the count and the share), not one per page:
on their own they say nothing about which link is owed, so a row per page would be a
number repeated a hundred times. The four contract-role lenses are the ones whose action
names a page, and they are one finding per page.

### 4.2 Identity

| id | level | predicate | evidence |
|---|---|---|---|
| `id.title_duplicate` | principle | two live subjects with the same normalized title (`normalize_title`) | both paths |
| `id.title_child_collision` | shape | a page whose title equals the title of a page in its own subtree (the evolution page that took a decision's name) | the child path |
| `id.title_degenerate` | drift | a title that is empty, equals its family role word alone (`演进`, `Evolution`, `项目演进`, `Overview`…), or equals the project slug | the title |
| `id.title_shared_with_hub` | drift | an `evolution.md` whose title equals its `overview.md` title | — |

### 4.3 Form

| id | level | predicate | evidence |
|---|---|---|---|
| `form.collapsed_body` | shape | a body line ≥ 1 000 chars, or a body containing the two characters `\n` more than twice with fewer real line breaks than escaped ones | line length, count |
| `form.stray_heading` | shape | a `# ` line that is not the first non-empty body line | line number, the heading |
| `form.unanchored_citation` | shape | a line carrying `[cite: …]` in the ledger with no anchor in its block | count |
| `form.overview_restates` | drift | an overview block whose text equals, byte for byte after stripping citations and anchors, a ledger claim of the same page | the slot |
| `form.legacy_sections` | drift | a page with an overview head that still carries `## definition|summary|introduction|connections` sections below it | the sections |
| `form.definition_empty` | shape | a `definition` block with no prose (only references / anchors) | — |
| `form.unordered_chronology` | drift | an `evolution.md` whose `## YYYY-MM-DD` sections are not in ascending order, or repeat a date | the first inversion, repeats |

### 4.4 Concentration and balance

| id | level | predicate | evidence |
|---|---|---|---|
| `conc.catch_all` | principle | a subject holding > 20 % of claims and > 3 × the even share, or the lead over 4 × the second (≥ 5 subjects) | share, ratio |
| `bal.family_heavy` | principle | a family with claim share ÷ page share ≥ 2 and claim share > 20 % | shares |
| `bal.family_empty` | principle | a declared family with no page | template |
| `bal.session_shaped` | drift | a subject ≥ 60 % of whose claims each cite exactly one source and carry a date prefix (`YYYY-MM-DD，`) — the signature of session narration filed as knowledge | share |

`bal.session_shaped` is the one heuristic lens; its evidence is counted, not judged, and
its action is a question ("is this subject a project or a log of sessions using it?")
rather than an instruction.

### 4.5 Corroboration

| id | level | predicate | evidence |
|---|---|---|---|
| `corr.single_source` | drift | a subject with ≥ 8 claims all citing one source id | the source id |

## 5. The two faces

### 5.1 The console

`#/lens` replaces `#/graph` (which redirects; `#/graph/node/<id>` still resolves to its
document). One view, two tabs:

- **Reading** — the score, then **the three things to do first**: the top findings by
  §3.4, each as a sentence, its impact, its action, and its actor; then every finding
  grouped principle / drift / shape, with the pages (click into the document) and the
  evidence.
- **Compare** — two refs (HEAD, any commit, any frozen snapshot); the score delta, the base
  counts delta, findings resolved / new / still open by key, and new edges each with the
  sentence that made it. Same lens on both sides, same templates.

The report comes from the service (`GET /v1/users/{uid}/lens?at=`); the console computes
nothing of its own, so the number the Owner sees is the number a Steward running
`pkc lens` sees. `lib/structureLens.ts` keeps only what the Library view's neighborhood
card needs.

### 5.2 `pkc lens`

`pkc lens [--path <doc>] [--json] [--at <ref>]` renders the same report at the terminal —
the score and counts, then the findings by level with their pages, evidence, impact and
action; `--path` narrows to one page. It is a read face like `pkc outline`: nothing calls
it for the Steward, nothing is refused because of it, and nothing it says enters a task.

## 6. What the mechanism refuses from now on

These land in the core gate and tool face, independent of whether the component is
registered. Each has a `shape` lens that lists the instances a library already holds.

- `heading_in_block` — `append_block`, `edit_claim`, `supersede_claim` and every overview
  slot refuse text containing a line that starts with `# `; `create_document` accepts a
  `# ` line only as the first non-empty line of the body.
- `escaped_newlines` — a body or block whose text contains the two characters `\n` while
  holding no real line break, or any single line ≥ 1 000 characters, is refused at the
  tool face with a message naming the fault; it is not silently accepted as one block.
- **Title is the leading heading only.** `derived_title` reads a `# ` line only when it is
  the first non-empty line of the body; a heading anywhere else is text. A closed volume
  has no title of its own on any read face: the glance, the outline, the dataset and the
  lens label it `<owner title> · vol. NN`, from its owner. A page's `title:` is written
  YAML-quoted when it contains a character YAML would misread.
- `retitle(path, title)` — a new write verb that rewrites the leading `# ` line (inserting
  one when the page has none), so a page that took the wrong name can be given the right
  one without touching a claim; it passes the gate's shadowed-title checks like
  `create_document`, and the gate refuses a title equal to a live sibling's. It is the
  repair for the pages the `id.title_child_collision` and `form.stray_heading` lenses list.

Existing closed volumes stay byte-identical: their stray headings are reported and their
titles are read from their owner, which is all the repair they need.

## 7. Faces

- `GET /v1/users/{uid}/lens?at=<ref>` → `Report` (JSON, the shape in §3).
- `pkc lens [--path <doc>] [--json] [--at <ref>]` — the report, or one page's findings.
- The thresholds in §4 are constants of the lens module, named once, and the console does
  not repeat them. No setting, no table, no component registration in this version.

## 8. Measuring it

Same discipline as every component: the report over a fixed library is byte-stable for a
fixed ref; the eval suite's group D (`navigability.reachability`) and the lens agree on
dead ends and arrival-blind pages by construction (they share the parser and the volume
rule). Whether the notes change what the Steward writes is measured as any quality claim
is — same harness, with and without the component — and is not asserted here.

## 9. Next: reaching the Steward (not built here)

The report is worth little if the same drift continues in the next round, and the
framework's answer to "the model reliably does what is enforced and verified" is a
forcing point, not a note. But a finding placed into a compile task is a change to what
the Steward writes, and it has to be designed with the same care as a contract clause:
which findings may enter a task at all, in what words, under what bound, and what the
Steward's answer is recorded as. The shape under consideration, to be decided once the
Owner has read this version's report against a real library:

- the lens becomes an index component (`lens`), with `outline_tail` carrying at most one
  bounded line for a page with an open drift finding;
- a forcing point at the gate for pages the round wrote — satisfy the finding or decline
  it with a reason — mirroring the people component's `alias_undecided`, with the decline
  a **kept record** (`component_lens_decisions`), which is where the `decision` field
  reserved in §3 is filled;
- the principle findings as `evolve_evidence`, in the console's own wording;
- a Hand-to-Steward act in the console that prefills, and never sends, a brief.

None of this is in the current version; a Steward sees the report only by asking for it.

