# The engine directory and the Engine Console

**English** | [简体中文](engine-console.zh-CN.md)

This is the design authority for the engine directory (the framework concept) and the Engine
Console (the surface that renders it). For the runtime contract of `ENGINE_DIR` see
[configuration](../reference/configuration.md); for where it sits in the system see
[architecture §11](../architecture.md#11-the-engine-directory).

## Why it exists

A generated project's strategy used to be scattered by accident of implementation: model
roles and chunking in `.env`, judgement in `contract.md`, the owner in `profile.yaml`, and
several knobs nowhere at all because `app.py` hardcoded them. Nothing about that was
inspectable and nothing about it was revertible — a person iterating their knowledge base
could not answer "what is my engine configured to do, and what did I change last week?".

The engine directory answers both by construction: one directory, its own git repository,
one commit per change. The console then makes it legible — the lifecycle each file
configures, drawn from a schema the code derives, with each value's origin and blast radius
stated next to it.

## Ruling 1 — everything that IS the engine lives in one directory

```
engine/                    # its own git repo; one commit per apply
  README.md                # orientation: what the engine is, each file's blast radius
  engine.yaml              # the four model roles — quality levers are strategy
  intake/intake.yaml       # chunk_strategy
  compile/contract.md      # the constitution — a DOCUMENT, never decomposed into knobs
  compile/challenge.yaml   # enabled, max_rounds, max_questions, compensate
  evolve/evolve.yaml       # auto_trigger, trigger_topic_docs, trigger_new_claims, draft_ttl_hours
  recall/recall.yaml       # answer_style, claim_cap, window_cap, plan_queries, rerank_*
  persona/profile.yaml     # the owner profile
  prompts/overlays.yaml    # catalog key → replacement clause (the prompt extension point)
```

**Not in `engine/`**: `.env` (API key, ports, subnet, compose project, framework repo path,
tenant id) — secrets and infrastructure never enter a versioned unit. `my-data/` (data),
`data/` (runtime state), `app.py` / `docker-compose.yml` / `start.sh` (machinery) stay where
they are.

**File shape is one rule, uniformly applied.** Every stage file except a document is a FLAT
YAML mapping of that stage's knob keys — no nesting, no per-file special cases, one parser.
`prompts/overlays.yaml` holds a single `overlays` key whose value is the map, which is the
same rule (a flat mapping whose value happens to be a mapping). `compile/contract.md` and
`persona/profile.yaml` are documents: raw text, never parsed as knobs.

**Precedence: process env > engine file > framework default.** Explicit environment wins so a
benchmark harness can override any knob per run without dirtying the versioned unit; the
engine file is the durable truth a person edits; unset everywhere falls to the framework
default — which is why an empty or absent engine directory is byte-for-byte the pre-engine
behavior. Enforced at settings assembly (`get_settings` → `engine_overrides`): engine values
are handed to `Settings` as init kwargs only for keys `os.environ` leaves unstated, because
init kwargs outrank environment in pydantic-settings. An entry present-but-empty in the
environment counts as an environment-level statement; a value from a `.env` FILE is not
process env and ranks below the engine file.

## Ruling 2 — the contract is a document, not knobs

`compile/contract.md` renders in the console as a first-class document node with version
history and an editor, NEVER as toggles or a form. Knowledge modelling is judgement, and
pretending it is checkbox configuration is the one lie this project cannot afford: a contract
teaches a model what deserves long-term memory *in this domain* and on which page, which no
form can express. The legitimate "strategy picker" surface is `prompts/overlays.yaml` —
whole-clause replacement per catalog key, built on the existing overlay mechanism — plus the
enum knobs that already exist (`answer_style`, `chunk_strategy`).

## Ruling 3 — the map is derived, never drawn

`engine-schema.json` is the single source the console and the docs consume. Hand-drawn
diagrams rot; this one is generated from `Settings` field metadata plus a hand-authored stage
map (`engine/stage_map.py`) and committed as a package asset, with tests pinning them
together. Regenerate with:

```bash
uv run python scripts/generate_engine_schema.py           # write
uv run python scripts/generate_engine_schema.py --check   # exit 1 if stale
```

Five tripwires make the pin real. The committed asset must equal what the code derives (so a
changed default or a retitled stage fails until regenerated). Every `Settings` field must be
either a knob or listed in `NON_ENGINE_SETTINGS` **with the reason it is not** (so adding a
strategy knob forces a classification decision instead of slipping past the console). Every
edge condition must name a real bool knob (an arrow the console cannot evaluate would render
as permanently off). Every access route must land on `recall` and name a gate that exists — a
bool knob, or a real field of core's `IntakePlan`. And every stage's `doc` deep link must
resolve to a file and a heading that exists in this repository.

### engine-schema.json (FROZEN shape)

```jsonc
{
  "schema_version": 1,
  "stages": [
    {
      "id": "intake",                      // intake | compile | challenge | evolve | recall | models | persona | prompts
      "title": {"en": "...", "zh": "..."},
      "summary": {"en": "...", "zh": "..."},
      "doc": "docs/architecture.md#...",   // repo-relative deep link
      "file": "intake/intake.yaml",        // engine-relative
      "knobs": [
        {
          "key": "chunk_strategy",          // key inside the engine file
          "env": "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",  // the env var it maps to ("" if none)
          "type": "enum|bool|int|string|document|overlay_map",
          "enum": ["semantic", "sentence", "recursive"],  // enum values; for overlay_map, the allowed KEYS
          "default": "semantic",
          "apply": "hot|restart|future_compiles|derived_rebuild",
          "label": {"en": "...", "zh": "..."},
          "description": {"en": "...", "zh": "..."}
        }
      ]
    }
  ],
  "edges": [                               // the pipeline arrows the map renders
    {"from": "intake", "to": "compile", "label": {"en": "...", "zh": "..."}},
    {"from": "compile", "to": "challenge", "condition": "challenge.enabled", "label": {...}},
    {"from": "challenge", "to": "compile", "condition": "challenge.compensate", "label": {"en": "compensation compile", "zh": "补偿编译"}},
    {"from": "compile", "to": "evolve", "condition": "evolve.auto_trigger", "label": {...}},
    {"from": "compile", "to": "recall", "label": {...}}
  ],
  "access_routes": [                       // the four levels the same material stays reachable at
    {"id": "l0", "from": "intake",  "to": "recall", "title": {...}, "summary": {...}},
    {"id": "l1", "from": "intake",  "to": "recall", "title": {...}, "summary": {...}},
    {"id": "l2", "from": "intake",  "to": "recall", "condition": "intake_plan.semantic_indexing", "title": {...}, "summary": {...}},
    {"id": "l3", "from": "compile", "to": "recall", "condition": "intake_plan.canonical_treatment", "title": {...}, "summary": {...}}
  ]
}
```

Notes on the shape as built:

- `models`, `persona` and `prompts` are stages with no edges — configuration groups rather
  than flow nodes, rendered as cards beside the pipeline. The five flow stages come first, in
  edge order.
- The overlay knob's `enum` carries the framework's ~340 prompt-catalog keys, read from
  core's `default_catalog()` at build time. The catalog IS the auditable inventory of
  model-visible prose; a second hand-kept list of its keys would rot immediately.
- `int` knobs are integers even where the backing setting is a float
  (`evolve_draft_ttl_hours`): the frozen type vocabulary has no float, the console has integer
  steppers, and a fractional draft TTL has no use.
- **`edges` and `access_routes` answer different questions, and a map with only the first is
  a wrong map.** `edges` is what the pipeline DOES to material; `access_routes` is how the
  same material stays reachable afterwards — L0 verbatim, L1 full-text, L2 semantic, and the
  L3 canonical compile route. Drawn without them, the console said `intake → compile →
  recall` and a newcomer read the whole system as "material → LLM compile → answer", which is
  the architecture's central claim (§3: four parallel views, fused per question) inverted.
  Three properties are asserted rather than described: every route lands on `recall`, because
  the fusion happening at answer time is what makes these parallel views instead of a
  fallback chain; L0 and L1 declare no condition, because invariant I3 makes them
  unconditional and a console offering to toggle them would be offering to break it; and an
  `intake_plan.<field>` condition must name a real field of core's `IntakePlan` — the two
  kinds of gate are spelled apart because a bool knob is a deployment switch while the intake
  plan decides per source and no setting overrides it.

### Apply semantics

Every edit states its blast radius. This is the console's honesty feature and it is invariant
I2 surfaced in UI copy:

| Value | Meaning |
|---|---|
| `hot` | the next process to read the engine files picks it up — no rebuild, no migration. In the scaffold flow (a CLI that reads the directory per command) this means the next command; a long-running API process reads its settings once at boot, so there it means the next start |
| `restart` | API/worker rewiring (model roles, prompt overlays) |
| `future_compiles` | governs future compiles only; canonical is never rewritten (the contract, challenge, evolve, the owner profile) |
| `derived_rebuild` | new material at once, existing material after `scripts/ops/rebuild_derived.py` (`chunk_strategy`) |

The console states both halves of `hot` rather than the flattering half: a CLI re-reads the
directory per command, a long-running API or worker reads its settings once at boot. And the I2
line ("canon is never rewritten") appears only under `future_compiles` / `derived_rebuild`
knobs, the two kinds that are actually statements about already-recorded knowledge — under a
model name it is not a reassurance, it is noise, and noise is how honest copy stops being read.

## Service API (FROZEN)

Root-level and **deployment-scoped**: no `user_id`, because the engine is the installation's
own configuration rather than a tenant's knowledge, and the scaffold that ships it is
single-owner. Invariant I1 is untouched — no user's data is reachable through these routes.
Every route is a 404 unless `PNEUMA_KNOWLEDGE_ENGINE_DIR` is set, so a deployment that never
adopted the concept gains no surface at all.

- `GET /v1/engine/schema` → the committed `engine-schema.json` (stages, knobs, `edges`, `access_routes`)
- `GET /v1/engine/state` → `{"files": {"<engine-relative path>": "<content>"}, "skipped": {"<engine-relative path>": "<why it is not in files>"}, "values": {"<stage>.<key>": resolved_value}, "resolution": {"<stage>.<key>": "env|engine|default"}, "version": {"head": "<sha|null>", "dirty": bool}}`
- `GET /v1/engine/file?path=<engine-relative path>` → `{"path": "<canonical path>", "content": "<content>"}` — one file verbatim, no resolution involved: the repair path when `/state` cannot resolve. Addressed exactly as an apply addresses it (one canonical spelling, inside the directory, no dotfiles); 404 when there is nothing there
- `GET /v1/engine/history?limit=50` → `[{"sha", "label", "at", "files": ["..."]}]`
- `GET /v1/engine/history/{sha}/files` → `{"sha": "<full sha>", "files": {"<engine-relative path>": "<content>"}}` — one version's files as that commit had them, via `git show`: HEAD and the working tree are untouched. This is the read half of "how do I undo this": restoring is loading a version's content into the draft and applying it with a label, so there is no revert primitive and the repository still only ever moves forward. `sha` may be abbreviated; a sha this repository does not have is **404**, and so is a revision expression git itself would evaluate (`HEAD~1`, `main@{yesterday}`) — the route resolves a commit id rather than evaluating git's grammar. The listing is filtered by the same addressing rules a read of the directory applies, so a version can never offer content the apply path would refuse
- `GET /v1/engine/prompts` → `{"surfaces": [{"id", "group", "kind": "assembled|fragments", "title": {en,zh}, "summary": {en,zh}, "note": {en,zh}|null, "segments": [{"key", "label": {en,zh}, "context": {en,zh}|null, "framework_text", "override_text|null", "placeholders": ["cite", …], "shared_with": ["<surface id>", …]}], "assembled_framework", "assembled_effective"}]}` — `kind: "fragments"` means the clauses reach the model one at a time, so both assembled strings are `""` and each clause carries a `context` saying when it is used; `note` is present when the assembled bytes are a runtime template rather than a finished message; see [the Prompt Studio](#the-prompt-studio) below
- `POST /v1/engine/prompts/rewrite` body `{"key", "intent", "locale": "zh|en"}` → `{"draft", "notes"}` — a model-drafted replacement clause. **Never writes.** Keyless is **503**, an unknown catalog key **400**, an unusable model reply **502**
- `POST /v1/engine/apply` body `{"changes": [{"path": "...", "content": "..."}], "label": "<=60 chars", "expected_head": "<sha|null>"}` → `{"sha": "...", "effects": [{"key": "...", "apply": "..."}]}`. `expected_head` is the HEAD the change set was composed against; a mismatch is **409** naming both shas, because the payload carries whole files and applying it onto a version somebody else moved would silently revert them. `null` (or absent) means no precondition, which is what the CLI wants

Behavioral commitments behind those shapes:

- **`values` / `resolution` cover exactly the non-document knobs.** A document has no resolved
  scalar — it IS a file, reachable in `files` and nowhere else. Values are read back off a
  `Settings` built with the resolved overrides, so what the console displays is exactly what
  the framework would use, including every type coercion.
- **State is re-read per request**, not reported off the running process's settings: right
  after an apply the files are the truth, and a `restart` knob should show its new value next
  to a badge saying a restart is pending.
- **Effects are computed against what is on disk**, so re-applying an unchanged file reports
  no effect and an apply that changes nothing mints no commit (the current HEAD is returned).
- **Git identity is the repository's own** (`pneuma-engine <engine@local>`, written into the
  local config at init and passed on every commit), so an apply never depends on — or records
  — the machine's git config.
- **An apply commits exactly the files it validated**, by path. `git add -A` would sweep in
  whatever a developer left modified or untracked and hand it a label; the partial commit leaves
  everything else as dirty as it was, and `version()` keeps saying so.
- **One apply at a time per deployment.** The precondition check, the writes and the commit are
  one critical section behind a process-wide lock: `to_thread` gives each request its own thread,
  which is the opposite of mutual exclusion.
- **The console degrades per region, not as a page.** Schema, state and history load
  independently, so an unparsable engine file costs you the values — not the map, the history and
  the way back in.

### Every rejection is a write-time rejection

Validation is total and happens before the first byte is written, so a rejected apply leaves
the directory exactly as it was, and the console can never leave the engine in a state it
cannot read back:

| Refused | Why |
|---|---|
| absolute paths, `..`, `\`, NUL | no traversal path exists because nothing else opens files |
| any dotfile component | `.git` is the repository's business, and every secret-shaped file on a developer's machine is a dotfile — refusing the whole class is a mechanism, a denylist of names is a game of catch-up |
| a path that resolves outside the root | defeats a symlink planted inside the directory |
| API-key-shaped content | the same `sk-or-…` shape `scaffold/init.py` refuses in answers files, plus the broader `sk-…` family |
| a key a stage does not declare | a key the framework never reads would sit there looking effective forever |
| a value outside a knob's enum, or of the wrong type | the same rejection `Settings` would make later, made earlier |
| malformed YAML | otherwise the console's next `GET /state` is a dead end |
| an overlay key the prompt catalog does not have | a silent no-op override is the worst outcome: framework wording keeps reaching the model while the deployment believes it does not |
| an overlay that drops, or invents, a named placeholder | a dropped `{slot}` deletes a value the framework computed, silently, in prose nobody re-reads; an invented one is never substituted and reaches the model as literal braces at the next start, after the commit |
| the same path twice in one apply, or two spellings of one file | ambiguous — and one canonical spelling per file is what keeps the path that was validated and the path that gets written the same string |
| a path that is not the canonical spelling of its file (`./x`, `x//y`, `x/`) | it resolves to the real file, so accepting it means the checks and the write can be looking at different strings |
| content past the 512 KiB engine-file cap | the same cap the read side enforces: a file the console cannot read back is one it could silently overwrite with the blank it displayed |
| a candidate directory that would not build a `Settings` | the total check, run over disk plus the pending changes through the same resolution `/state` uses, so "committed, then unreadable" is unreachable rather than a class of bug to keep catching one knob at a time |

Reading is deliberately more forgiving in one direction only: `read_engine_directory` reports
oversized or undecodable files in `skipped` rather than failing, so one stray file cannot make
the whole engine unreadable — and the gap is named rather than silent, because a file missing
from `files` is otherwise indistinguishable from an empty one. Resolution is not forgiving at
all: malformed YAML raises, because an engine file that cannot be read must never silently mean
"use the framework defaults".

## The Prompt Studio

The overlays picker shipped as a list of ~340 dotted catalog keys with their default text.
Every one of them is genuinely overridable and none of them is legible: a person reading
`recall.cite.source_level` cannot tell which prompt it lands in, what stands either side of
it, or that rewriting it also changes the deep lane and the briefing session. The verdict
was blunt and correct — "too hard to guess; users have no idea what they are changing."

### The inversion

**The unit of OVERRIDE stays the catalog key.** The overlay mechanism, the file, the apply
semantics and the versioning are untouched. **The unit of UNDERSTANDING becomes the
surface**: one assembled, model-visible prompt (the fast-recall System contract, the compile
SystemMessage, the coverage audit's question pass) composed from ordered catalog segments.
A person browses surfaces, reads the prompt as the model will receive it, and overrides a
clause *in place*.

### Two kinds of surface: prose, and a family of clauses

Not every group of keys is a prompt. `source.preamble.*` is 28 **conditional alternatives**
and word fillers — at runtime one lead sentence is chosen and a few fillers substituted into
it. Concatenating them produced `the ownera conversationThis is…`, and the studio presented
that as the prompt a model reads. A map that renders gibberish is worse than no map: it
teaches a newcomer something false, which by the acceptance bar of this UI is a defect of the
highest severity.

So a surface declares `kind`:

| kind | Meaning | `assembled_framework` / `assembled_effective` |
|---|---|---|
| `assembled` | a real composition function produces exactly these bytes in exactly this order | the bytes, rendered twice |
| `fragments` | independent clauses the model receives one at a time — the alternative preambles, a tool face, the sections of a human turn, a gate's rejection lines | `""` — there is nothing to assemble |

`kind: assembled` cannot be claimed, only earned: the byte-pinned set and the `assembled` set
are the same set (below), so a family nobody can check against a composition function is
shown as what it is. `render_surface()` refuses a fragment family outright, which is why the
concatenation cannot come back through some other caller. 14 surfaces are assembled; 26 are
fragment families.

Inside an `assembled` surface a segment plays one of three roles, which is what lets a map
cover assembly rather than just listing keys:

| Role | Meaning |
|---|---|
| block | concatenated into the assembled text, in order, with its literal glue |
| slot | substituted into a named placeholder of a sibling (`recall.spine`'s `{cite}` / `{close}`); fillers nest |
| variant | listed but not in *this* rendering — the two answer styles the deployment did not pick, the subject-profile section that appears only when a profile was supplied, the per-version contract clauses |

Placeholders the framework fills from runtime data (`{templates}` from the skill's path
families, `{question}`, `{instructions}`) are left literal in the preview and reported per
segment, so the studio can render them as chips instead of pretending to know their values.

### `note`: an assembly is a template, and the preview says so

The first verification pass opened `compile.system` under a heading promising the order and
the original as the model receives them, and read `{templates}`, `{skill_id}`, `{version}`,
`{instructions}` unfilled and a §2 saying no subject profile was supplied — while the engine
directory plainly held `persona/profile.yaml`. The bytes were right. The sentence above them
was not, and it was pointed at the single thing that surface exists to explain.

So a surface may carry `note` — one bilingual banner stating what the reader is looking at:
what the framework substitutes per call (the contract in force, the owner profile, the round's
dates), which clause a knob picks instead of the one rendered, and what arrives separately in
the HumanMessage. `null` means the assembled bytes really are the message, and only then may
the console say so. 13 of the 14 assemblies carry one; `intake.source_guidance` does not,
because its bytes are inserted whole. A fragment family never carries one — it has no
assembled text to caveat.

It is not left to diligence. The note pin reads **the same field table the byte pin uses**: a
surface the pin has to hand runtime values to is by definition a surface whose preview is
missing them, and a surface offering a variant is one rendering a branch. Either obliges the
banner, so the assembly that most needed it is the one that cannot ship without it.

### `context`: when the model receives this clause

A block of an assembled prompt is explained by where it stands. A clause of a fragment family
and a `variant` have no position to speak for them, so each carries `context` — one bilingual
sentence naming the situation in which the model receives it ("Fills `{scene}` of the lead
when the ingest side supplied no scene phrase", "When a newly written claim links back to
nothing"). It is required mechanically: a fragment or a variant without one fails the suite,
and a `context` that merely restates the label fails too. 308 of them (280 fragment clauses + 28 variants), hand-written, because
"when is this used" is exactly the thing no derivation can produce.

`context` is `null` for an assembled surface's blocks and slots — deliberately, not as an
omission: the assembled preview above them already answers the question.

### The map cannot drift from the code

`prompts/surfaces.py` lives in **core**, next to the catalog it describes, and is a mechanism
rather than documentation because five tests hold it to the code:

- **Byte pin** — every surface of kind `assembled` renders byte-for-byte identically to the
  real composition function (`selector_contract()`, `deep_contract()`, `briefing_contract()`,
  `live_context_contracts()`, `detail_contract()`, `render_system_contract()`, the two evolve
  contracts, the three coverage-audit passes, the rollover history card, the context-stream
  guidance, the profile expansion). A contract that gains a section, loses a clause or
  reorders two of them fails until the map says the same thing.
- **Kind pin** — the byte-pinned set and the `assembled` set are identical, in both
  directions. A surface claiming to be prose with no pin is an unverified claim about what
  the model receives; the flag is a promise, and this is the test that collects on it.
- **Context pin** — no clause of a fragment family and no variant without its bilingual "when
  is this used", and none whose note is the label said twice.
- **Coverage pin** — every catalog key belongs to at least one surface. A new key with no
  surface is prose nobody can find in the studio, so it fails on the commit that introduces
  it rather than on the day somebody goes looking for it.
- **Note pin** — an assembly whose byte pin supplies runtime fields, or which declares a
  variant, carries `note`. Both triggers are read off the pin table rather than restated, so a
  contract that grows a runtime slot starts owing a banner on the same commit.

Surfaces carry bilingual titles and summaries by hand. Segment labels are **derived** from
one bilingual name per key-prefix family plus the humanized key tail (`gate.groom.anchor_lost`
→ "Rollover gate · anchor lost" / "归档闸门 · anchor lost"), with the surfaces a person
actually opens refined by hand. 338 hand-written labels would be 338 chances to rot.

Lifecycle groups, as the console lists them: `intake`, `compile`, `challenge`, `evolve`,
`recall`, `persona`, `skill`, `feedback`, `eval`.

### Resolution, and the two things the endpoint refuses to do

`GET /v1/engine/prompts` resolves against **the engine directory's overlay file on disk** —
not the running process's registered overrides (the process booted with whatever directory it
was pointed at, and the studio has to show the one being edited) and not the client's unsaved
draft (which stays client-side and flows through the ordinary apply, exactly like the rest of
the console's editing). Only the overlay file is read, so an unrelated stage file somebody
broke by hand costs `/state` its values without costing the studio its picture.

The studio's own rewriting prompt is deliberately **not** in the catalog. The catalog is the
inventory of prose the knowledge *pipeline* emits — the thing a deployment tunes. Cataloguing
the authoring assistant would make it overridable by the very overlay map it exists to edit,
and would drag the committed engine schema asset (whose overlay enum is the catalog's key
list) behind every wording tweak.

### The language pack

The framework ships one alternative to the English catalog: a **Chinese language pack**
(`prompts.lang_zh.chinese_overlay()`), every catalog key translated with the same named
placeholders. It is selected by the `prompts.language` knob
(`PNEUMA_KNOWLEDGE_PROMPT_LANGUAGE`, `en` | `zh`, `apply=restart`), and it is not a second
mechanism — it goes through the ordinary overlay seam, and it goes through it **first**:

```
English catalog  →  active language pack  →  this deployment's overlays
                    ("the framework text")   ("an override")
```

That order is the whole design. A clause somebody wrote for their domain must survive the
pack, not be taken back by it. And it is what keeps the studio honest: `framework_text`
follows the active pack, because below the pack there is no author, only the framework.
Showing the English default as "framework" under a Chinese engine would present the pack's own
sentences as somebody's override, and every real override would read as a diff against prose
the model never sees. `en` registers no overlay at all, so the English path stays byte-for-byte
what it was — same `prompt_overlay_hash()` (None), same commit trailer.

Two mechanical pins hold a pack to the catalog (`tests/test_prompt_lang_zh.py`): the key set
matches in **both** directions, and every translation declares exactly its original's
placeholders. Totality is the point — a single untranslated key leaves an English sentence
inside a ten-kilobyte Chinese contract, which is precisely the kind of thing nobody re-reads
a prompt to find. What deliberately stays English is what a *program* reads, not a model: the
`[cite: …]` marker, the JSON locator shapes, and the eval judges' `YES` verdict token.

**English is the measured baseline, and the pack is not claimed to be equivalent.** Every
number published in this repository — the LoCoMo-refined tuning runs behind
`recall.close.answer_honestly`, the claim-budget sweet band, the reranker's measured
no-gain — was taken on the English catalog. The Chinese pack exists for two other reasons:
an operator who reads Chinese can actually audit the prompts their models receive, and a
Chinese material domain reads its instructions in its own language. Its scoring equivalence
is **unverified**; nothing here asserts it is as good, or better, or worse. A deployment that
cares should measure it on its own harness against the English baseline, which is the same
discipline this project applies to every other quality claim.

### AI rewrite, and why it cannot save

`POST /v1/engine/prompts/rewrite` drafts one replacement clause on the deployment's
recall-role model. It is given the clause's position inside its surface, the text of the
segment either side of it, the framework original **as the active language pack states it**,
the override in force, the placeholder contract it must preserve, and the operator's intent. It returns `{draft, notes}` and
**writes nothing** — the draft goes back through draft → review → labelled apply like every
other edit, because an assistant that could commit its own wording would put model output
into the versioned unit unread. A keyless deployment gets a 503 saying so; browsing and
editing stay fully served, and only the assistance is unavailable.

**The pack's language decides what the clause is written in** — not `locale`, which only says
who reads `notes`, and not the language the operator happened to type their intent in. The
first version resolved the original through `default_catalog()` and then asked the model to
keep the original's language, so under a Chinese engine it was shown English prose and
complied: asked to make a gate rejection more direct, it returned "gate 已拒绝 … 使用
claim-level 工具修复", which has no placeholders, passed every check, and was appliable. The
brief now resolves through the active pack and names the terms that must survive it (闸门 not
gate, 断言 not claim, 正本 not canonical, 锚点 not anchor), while exempting the things that are
not terminology at all — tool names, field names, enum values, placeholders. An English console
over a Chinese pack is a normal setup, which is why one value could never have answered both
questions.

### The placeholder gate

The gate that makes the loop safe is mechanical and lives in the existing apply validation
path: **an overlay must declare exactly the named placeholders its original declares.**
Dropping one is not "simplifying the wording" — it deletes a value the framework computed,
in the one layer nobody re-reads. Inventing one is worse: nothing substitutes it, so literal
braces reach the model, and only at the next process start, after the commit. Both are
refused by name, before the first byte is written.

This is deliberately stricter than `prompts.override_prompt`, which tolerates a subset. That
seam is a library call an author writes with the default in front of them; this is a form
somebody fills from an intent, having never seen what the framework was going to put there.

## Scaffold integration

`scaffold/init.py` generates `engine/`, `git init`s it and commits `engine: initial`. Every
value it writes is stated explicitly, including values equal to the framework default: the
point of the directory is that a person can read what their engine does without knowing what
the framework would otherwise have chosen. `evolve.auto_trigger: false` states what
`build_settings` used to hardcode — same behavior, now visible and editable.

`templates/app.py` resolves strategy through the framework's own resolver rather than a second
reading of the same YAML, so the CLI, the API and the console cannot disagree; it registers
the contract from `engine/compile/contract.md`, reads and writes the profile at
`engine/persona/profile.yaml`, and applies `prompts/overlays.yaml` through `override_prompts`
(without which that file would be decoration). Note that `app.py` loads `.env` into the
process environment before anything reads it, so a `PNEUMA_KNOWLEDGE_*` strategy key placed
there would outrank the engine file — which is exactly why the generated `.env` carries none.

The compose template gains an optional `console` profile — the whole browsing layer, not just
the console: the framework API and a compile worker running the project's own entrypoints
(`server.py` / `worker.py`, so its compile contract is registered), plus the web UI on its own
probed port. The project directory is mounted at `/project`, which is what makes
`PNEUMA_KNOWLEDGE_ENGINE_DIR=/project/engine` read-write (applying writes files and commits
them). The everyday pipeline stays the CLI.

`./init.py --demo` is the zero-interaction way in: it generates an ordinary project whose
`engine/` holds `examples/opc`'s real contract and profile and whose `prebuilt/` holds that
project's compiled library, starts the profile above, and restores the library with no API key
(`./app.py restore`, through the framework's own restore flow). A demo project differs from any
other generated project only in the payload it ships — which is what makes the console it opens
a real one, over a real engine, with a real library behind it.

`examples/opc` deliberately keeps its own pre-engine copy of the machinery: it is an
already-generated project shipping a prebuilt library, and regenerating it would rebuild that
library. Its api service therefore serves no engine directory, and its web image is built with
`VITE_ENGINE_FIXTURES=true` so its console view stays honestly on mock fixtures.

## Console UI

A top-level view in `apps/web`: the pipeline map from `stages` + `edges` (conditional edges
dimmed when their condition is off, so toggling the challenge switch visibly wires and unwires
that part of the machine), stage cards with live values, origin badges and apply-semantics
badges, the contract as a document node with an editor and history, the Prompt Studio, and a
draft → review effects → apply(label) flow landing in a git timeline.

The studio is entered from the prompts stage node and takes the whole canvas: surface list
grouped by lifecycle on the left, the assembled preview in the centre (toggling framework
wording against effective wording, segments delimited, overridden ones tinted, placeholders
as chips), and the segment editor on the right — human explanation, which surfaces share this
clause, the framework original read-only, the override editor behind an explicit "edit" the
way documents are protected, and the AI-rewrite block. Saves accumulate in the existing
engine draft as overlay entries and flow through the standard review → labelled apply;
nothing new in versioning.

A `fragments` surface takes a different centre pane: a one-line statement that this family is
selected by condition and that the clauses never join into one text, then the clauses
itemized — applicability sentence, framework wording in the active language pack, the override
in force beneath it. No assembled preview and no framework/effective toggle, because neither
exists. The left column, the override counts and the right-hand editor are unchanged, and the
editor leads with the clause's own `context` wherever it has one.
