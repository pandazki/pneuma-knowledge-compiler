# The library's shape — hooks at the write, the check, and the structure lens

**English** | [简体中文](structure-lens.zh-CN.md)

## 1. Why, and the ruling that shapes it

The Steward works inside the library, one source at a time. Every compile is a local
decision made under the contract, and each one can be right while the sum drifts: a
project page that quietly fills with session narration, an evolution page whose dated
sections arrive in ingest order rather than in time, a stray heading that renames a page,
a subject that exists twice under two spellings, a family of pages that nothing links to.
None of these is a fabrication — every claim still cites its span. The question is who
can see each of them, and that question sorts them into three tiers:

- **What the write can decide** needs nobody. A heading inside a claim block, a body with
  no real line breaks, a title equal to a sibling's, a dated section appended out of order:
  the fault is fully visible in the bytes being written, so the mechanism refuses it or
  normalizes it at the write and no reader ever meets it. This is the framework's first
  discipline — mechanism over persuasion — applied to the library's shape. **Tier one:
  hooks at the write** (§2).
- **What the insider can find by checking** needs a checklist, not a vantage point. A page
  that names another subject twenty times and never links it, an evolution page whose
  turning points cite no decision, a hub that leaves three of its own pages unreachable:
  a Steward standing at the page can see it against the contract and can repair it in a
  round of its own. This is the library's reflection. **Tier two: the check** (§3).
- **What only the whole shows** is what the library is becoming: whether it is walkable
  as a body, where knowledge piles up, how much of it is a log of sessions rather than
  knowledge about subjects, whether it ever corrects itself, whether the structure that
  its accumulating knowledge implies exists yet, and whether what it holds is what people
  ask it. No page shows any of this. **Tier three: the structure lens** (§4).

The ruling: **a finding belongs to the lowest tier that can see it.** A tier-one fault is
never a check item and never a lens reading; a check item is never a lens reading. The
lens is left with the readings that need the god's-eye, which is what it is for.

Everything in the three tiers is derived and model-free: computed from canonical (and,
for one lens reading, the kept consultation records), writing nothing to canonical.

## 2. Tier one — hooks at the write

Each hook is a gate check or a tool-face refusal in core `compile/`, in force whether or
not anything else in this document is deployed. **Refuse** means the write comes back with
a named violation; **normalize** means the mechanism places the bytes deterministically
and the model never has to know the rule.

| hook | at | what |
|---|---|---|
| `heading_in_block` | tool face + gate | a line starting with `# ` inside `append_block`, `edit_claim`, `supersede_claim` or an overview slot is refused; `create_document` accepts `# ` only as the first non-empty body line |
| `escaped_newlines` / `long_line` | tool face | text carrying literal `\n` with no real line break, or any line ≥ 1 000 chars, is refused |
| leading title | serialization | `derived_title` reads only a leading `# `; a closed volume is labelled from its owner (`<owner> · vol. NN`); `title:` is YAML-quoted |
| `title_sibling_collision` | gate | a title equal to another live page's in the same directory is refused |
| `title_degenerate` | gate | a title that is empty, equals a family role word alone (`overview`, `evolution`, `概览`, `演进`, `项目演进`…), or equals the project slug on a page that is not the hub, is refused |
| `title_shared_with_hub` | gate | a chronology page (`evolution.md`) titled exactly as its hub (`overview.md`) is refused |
| chronology order | normalize | `append_block` on a chronology page under a `YYYY-MM-DD` heading lands in the existing section of that date, or opens a new section at its chronological position; the anchor is untouched. `reorder_chronology(path)` is a mechanical write verb for pages that predate the rule (anchors and bytes conserved, only section order moves) |
| `overview_restates` | gate | an overview block whose text, stripped of citations and anchors, equals a ledger claim of the same page is refused — cite the claim instead |
| `definition_empty` | gate | a `definition` block with no prose (references and anchors only) is refused |
| `retitle` | write verb | rewrites the leading `# ` (inserting one when absent) so a page that took the wrong name can be renamed without touching a claim; passes the shadowed- and sibling-title checks |

Family roles (hub, chronology, child families, owner views, memory) are read off the
active `path_templates` by name — a table in core `shape/families.py` shared by all three
tiers, never prose.

Deferred to a contract that declares structure: *a page created under a project's child
family must be linked from the project's hub in the same round.* The gate could refuse
this today, but "the hub links its children" is the personal-projects contract's
expectation, not the framework's, and a contract states its expectations as prose. When a
path template can carry `hub: overview.md`, the rule becomes a hook; until then it is a
check (§3).

## 3. Tier two — the check

### 3.1 What it lists

The check is a list of page-level findings the Steward can act on, each with the page, the
verbatim evidence, what it costs and what to do. Two kinds of item:

- **Judgement items** — the contract's expectations no hook can decide:

| id | predicate | evidence |
|---|---|---|
| `nav.hub_incomplete` | a hub that does not link to every page of its own subtree | the missing targets |
| `nav.chronology_unlinked` | a chronology page with ≥ 3 dated sections and no link to any feature or decision page of its project, when such pages exist | the children |
| `nav.decision_unlinked` | a decision page with no outbound link | — |
| `nav.mention_unlinked` | a page whose claim text names another live subject's exact title (≥ 4 chars, not its own) ≥ 3 times and never links it | the title |
| `nav.dead_link` | a link to a path no document has | the href |
| `id.title_duplicate` | two live subjects with the same normalized title, in different directories | the title |
| `corr.single_source` | a subject with ≥ 8 claims all citing one source | the source id |
| `form.legacy_sections` | a page with an overview head that still carries `## definition\|summary\|introduction\|connections` sections | the sections |

- **Legacy instances of tier-one faults** — pages written before a hook existed: a stray
  heading, a collapsed body, a degenerate or hub-shared or child-colliding title, an
  unordered chronology, an overview block that restates a claim, an empty definition, a
  cited line with no anchor. The hook keeps new ones out; the check lists the old ones with
  the verb that repairs each (`retitle`, `reorder_chronology`, an ordinary edit).

The finding shape is the one in §5.1; every sentence is rendered from the prompt catalog
in both packs.

### 3.2 The review round

The check reaches the Steward as **its own round**, never as a note inside another job's
task. A `review` job (canonical lane, like `groom` and `challenge`) opens a draft over the
whole library with no source: its task is the check's report for this library, and its
instruction is to repair what a round can repair — links, titles, order, edits — through
the ordinary draft verbs, under the ordinary gate, and to say in the brief what it left
and why. It is enqueued by the Owner (`pkc jobs enqueue review`, or the console) and by
nothing else in this version; scheduling it is a later decision.

A round that neither repairs a finding nor says why is **incomplete, not ok**: the finish
refuses it (`review_incomplete`), the job is recorded `ok=false` with the harness's own words
on the row, and it comes back under the same bound a harness that died comes back under —
because the one thing a library must never be told is that it was reviewed by a round that
accounted for nothing. Repairing nothing and saying why is a finished round; so is a round
over a library the check found nothing to repair in, which is told exactly that in its task.

This is the insider's reflection: the Steward reading its own library against the
contract and correcting it. It puts nothing into any other job's context.

### 3.3 Faces

- `GET /v1/users/{uid}/review?at=<ref>` and `pkc library review [--path] [--at] [--json]`
  — the report; `--json` is never paged.
- `#/review` in the console: the findings by page, the same row the lens used to show,
  and the last review round's brief.

## 4. Tier three — the structure lens

### 4.1 What it reads

Every canonical document at one ref, the active path templates, and — for one dimension
— the kept consultation records and the attention component's access ledger when they
exist. Subjects, edges and claims are computed once, by the shared `shape/` module, the
same way for the check and the lens (a volume folds onto its page; an edge is a markdown
link inside a claim or the overview region, through the gate's parser; a claim is a ledger
anchor, overview blocks excluded).

### 4.2 The six dimensions

The lens does not list pages. It reads the library along six dimensions and says, for
each, what it sees, what that implies, and how it moved since the previous reading. Each
dimension has a small set of metrics, a **band** chosen by named thresholds, one rendered
**statement** per band, and a **direction** — what the reading implies for the contract or
for evolve — rendered from the catalog like every sentence.

| id | question | metrics | band thresholds |
|---|---|---|---|
| `walkability` | can a reader walk this library, or only look things up by name? | edges per subject; dead-end share; arrival-blind share; share of subjects in the largest connected component; islands (projects with no edge to or from outside) | open: dead-end ≤ 15 % and arrival-blind ≤ 15 %; thin: either ≤ 40 %; broken: otherwise |
| `shape` | where is knowledge piling up? | lead subject's share and lead ratio; each family's claim share against its page share; empty declared families; number of clusters | even: lead ≤ 10 %, no family ≥ 2× its page share; leaning: lead ≤ 20 % or one family ≥ 2×; collapsing: otherwise |
| `knowledge_vs_log` | how much of this is knowledge about subjects, and how much a log of sessions? | share of claims that are dated, single-source narration (the session signature); share of subjects ≥ 60 % narration; share of claims per family | knowledge: narration ≤ 20 %; mixed: ≤ 50 %; log: otherwise |
| `liveness` | does the library ever correct itself? | subjects never written since creation; supersessions per 100 claims; edits per 100 claims; rollovers; overviews rewritten after ≥ 8 claims; median days since last write per subject | living: supersessions ≥ 1 / 100 and ≤ 50 % subjects untouched; still: supersessions < 0.5 / 100 or ≥ 80 % untouched; settling: between |
| `type_structure` | what kind of knowledge is accumulating, and does the structure it implies exist? | dated claims outside any chronology family; decision-shaped sections (`decision`/`rationale`/`scope` headings) outside the decisions family; names recurring across ≥ 3 subjects without a people page (when the people component is registered); declared families with pages vs. without | aligned: each proxy ≤ 5 % of its base; strained: any ≤ 20 %; misfiled: any above |
| `demand_supply` | is what it holds what people ask it? | consultations per family vs claims per family; subjects consulted vs never consulted; consultations answered with no citation (gaps) | read only when consultations exist; matched: gaps ≤ 10 % and the most-asked family is within 2× of its claim share; skewed: otherwise; `unread` when there are no consultations |

The thresholds are constants of the lens module, named once; the console does not repeat
them. A dimension's statement is written to the Owner, in the register of an outside
reader: what it sees and what it would ask, not a list of pages. The `direction` names the
lever — a contract clause, an evolve, a groom, a review round — never a page.

### 4.3 Trend

A reading carries the previous reading when one exists — the previous canonical commit by
default, any ref or frozen snapshot on request — and each dimension states its movement:
which metrics moved, in which direction, and whether the band changed. The score of the
old view is gone; the six bands and their movement are the whole summary.

### 4.4 The lens and evolve

The `type_structure` reading is exactly the evidence the design philosophy asks evolve to
weigh — which knowledge is accumulating whose implied structure does not exist. Rendering
it as `evolve_evidence` is the lens's one intended exit toward the library's own process,
and it is not built in this version: it is designed with the review round's scheduling.

### 4.5 Faces

- `GET /v1/users/{uid}/lens?at=<ref>&previous=<ref>` and `pkc lens [--at] [--previous]
  [--json]` — the reading.
- `#/lens` in the console: six sections, one per dimension — the band as a word, the
  statement, the metrics as a short table with their movement, the direction — and a
  ref picker for the previous reading. No list of findings anywhere on the page; the
  check has its own.

## 5. Shapes

### 5.1 A check finding

```
Finding
  key          "<id>:<path or scope>:<evidence hash>" — same evidence, same key
  id           one of §3.1, or the legacy id of a tier-one fault
  kind         "judgement" | "legacy"
  paths[]      the pages it is about (open-page paths)
  targets[]    other paths involved
  evidence[]   verbatim strings from the library only (a path, a title, a heading, a
               date, an href, a source id); counts live in the fields
  impact       {key, fields, text: {en, zh}}
  action       {key, fields, text: {en, zh}}   naming the repairing verb when there is one
```

```
CheckReport
  ref, read_at, subjects, files, claims, edges
  findings[]   ordered: legacy first (a hook fault is unambiguous), then judgement;
               within a kind by id, then path
```

### 5.2 A lens reading

```
LensReading
  ref, read_at, previous_ref
  subjects, files, claims, edges
  dimensions[]
    id            one of §4.2
    band          the band id
    statement     {key, fields, text: {en, zh}}
    direction     {key, fields, text: {en, zh}}
    metrics[]     {name, value, previous, delta}      previous/delta null without a previous
    evidence[]    verbatim strings (the lead subject's path, an island's directory, …)
```

Text through the catalog: every sentence is a prompt-catalog key with named fields,
rendered in both packs at the source, so the console keeps no copy and an application
that rewords a key through the overlay seam changes what every reader sees.

## 6. Faces, summarized

| face | tier | read / write |
|---|---|---|
| gate + tool face (`compile/`) | one | write-time refusal / normalization |
| `pkc draft retitle`, `pkc draft reorder-chronology` | one | repair verbs |
| `GET /review`, `pkc library review`, `#/review` | two | read |
| `review` job, `pkc jobs enqueue review` | two | the Steward's own round |
| `GET /lens`, `pkc lens`, `#/lens` | three | read |

No component registration, no note in any compile task, no gate rule on a finding's
account. `#/graph` redirects to `#/lens`; `#/graph/node/<id>` resolves to its document.

## 7. Measuring it

The check and the lens over a fixed library are byte-stable for a fixed ref; the eval
suite's group D (`navigability.reachability`) agrees with the walkability metrics by
construction (shared parser, shared volume rule). Whether the review round improves what
the check lists is measured as any quality claim is — the same library, a reading before
and after the round — and is not asserted here.

## 8. Next, not built here

- The review round on a schedule, or after N compiles, once its unattended behaviour has
  been watched on a real library.
- `type_structure` as `evolve_evidence`.
- A contract seam for structural expectations (`hub:` on a path template), which turns
  the hub-links-its-children check into a hook.
- The people-name proxy of `type_structure` when the people component is not registered.
