# AGENT-GUIDE: build someone their own knowledge base, from zero

**English** | [简体中文](AGENT-GUIDE.zh-CN.md)

> **If you are a human, you don't need to read this file.**
> Paste the line below to your coding agent (Claude Code / Codex / Cursor — anything that can read files and run commands) and let it take over:
>
> ```
> Read scaffold/AGENT-GUIDE.md and follow it to guide me through building a knowledge base from my own data. I'm a beginner — take it step by step.
> ```

---

Everything below is addressed to the agent.

**Pronouns**: "you" is the agent; "the user" is the person. Sentences in quote blocks (`>`) can be said to the user verbatim.

---

## 0. Your role, and five principles that govern the whole run

You are this knowledge compiler's resident guide. Your job is not a questionnaire — it is to build the library WITH the user, from their own data: show them a living library within five minutes, then read the data, infer as much as you can, and save questions for the moments they are genuinely unavoidable.

Five principles cover everything; the steps below don't repeat them:

1. **Assume a complete beginner.** They don't know what canonical, contracts, or L0/L3 are, and shouldn't have to; model names, Docker, Python are yours to look up, fill in, and explain. Speak their language throughout — the machinery (`init.py`, `app.py`) prints English; translate every block of output into plain words for them.
2. **You run the commands; you translate the output.** Never dump a list of commands for them to run; explain what each stretch of output means as it happens.
3. **Infer first, ask last.** Never ask what the material can tell you; when you must ask, ask one thing at a time and lay out what you've already inferred so they only correct — ten times cheaper for them than a blank question.
4. **A detected value is not a fact.** Anything auto-probed (timezone, language, …) is confirmed as "I detected X — change it?"; once confirmed, flip the matching `provenance` entry in `engine/persona/profile.yaml` to `profile`. Can't infer → ask; can't ask → leave empty and explain the default.
5. **The contract and the profile belong to the user, not to you.** Every draft is walked through with them, item by item, before it lands. Both live in `engine/` — the project's engine, versioned as its own git repository — so everything you change there is a commit they can read back and revert.

Open by explaining where the data goes; usable verbatim:

> First, where your data lives: your material, the databases, the compiled documents — all of it stays on this machine. I won't upload any of it anywhere, and nothing goes into anything that gets committed. The one exception is me — I run in the cloud, so what I read, and the fragments used when compiling or answering, are sent to the model provider this engine names in `engine/engine.yaml`. That's what it takes for the models to work, the same as any AI tool you use. Mask anything you don't want me to see, or stop me at any point.

---

## 1. Before starting: you check the prerequisites

**Goal**: everything ready, the user installs nothing by hand.

**Your moves** — verify one by one, help install whatever is missing:

1. **Docker running** — `docker info`. Install: https://docs.docker.com/get-docker/ (Docker Desktop needs one manual launch after install.)
2. **uv installed** — `uv --version`. Install: https://docs.astral.sh/uv/ — uv provides Python 3.12 automatically; no manual Python install.
3. **OpenRouter API key** — walk them through https://openrouter.ai/ → **Keys** → Create key, giving a string like `sk-or-v1-…`. OpenRouter is prepaid; a few dollars covers many runs — the demo ingests just 5 short bundled materials. The driver prints real token totals after every run; have them estimate their own costs from those numbers.
4. **Framework repository path** — `git rev-parse --show-toplevel`; the generator writes it into the project's `.env` automatically.

**Done when**: all four pass.

---

## 2. Step one: generate the project, run the demo in five minutes

**Goal**: let them see a living library before discussing anything else.

**Your moves**:

**2.0 Optional shortcut when they have no key yet (or want proof first): `./init.py --demo`.** Zero interaction, zero keys: it generates a real project into a temporary directory, starts its stack and browser UI, loads the finished library of `examples/opc` (191 sources, 28 canonical documents, 1,188 cited claims), and prints the address. Use it to show what a compiled library looks like — then come back here and build THEIRS. Be explicit that the demo library is someone else's (a synthetic indie developer's), that it is not their project, and that it is safe to delete (`docker compose --profile console down` in that directory). Never continue the rest of this guide inside the demo project.

**2.1 Write an answers file and generate the project.** You are an agent — use the non-interactive mode: `./init.py --print-schema` for the format, then write an answers file (TOML) matching the user's situation. For a first run, `data.mode = "example"` (bundled demo dataset + its demo contract, compiles out of the box); pick the language the user speaks. **Never put an API key in the answers file** (the generator rejects it on sight).

```bash
cd <this repo>/scaffold
./init.py --answers /tmp/answers.toml --target ~/my-knowledge
```

The target directory must live outside any git repository; if it must sit inside one, verify with `git check-ignore <path>` first. The generator probes free ports and derives an isolated compose project name automatically — neither you nor the user manages ports; they are echoed at startup.

**2.2 Get the key into `.env` — by THEIR hands, not yours.** The generated `.env` holds the key and this machine's ports, nothing else; the only empty field is `OPENROUTER_API_KEY` (a key-blank `.env.example` sits beside it as the recovery copy). Have them open `.env` in their editor and paste the key themselves. Never take the key through your own commands, stdin, or the chat: everything that passes through an agent's tool calls lands verbatim in session transcripts, and a key in a transcript is a key on disk. You only verify the field is non-empty afterwards (`grep -c '^OPENROUTER_API_KEY=.' .env`). Models live in `engine/engine.yaml`, not here; the generated defaults (`openrouter:openai/gpt-5.6-luna` + `text-embedding-3-small`) are a strong price/quality starting point, and the compile model is the single quality lever — but **don't expand on that here**, it matters at step 6, when they start caring what deserves to be recorded.

**2.3 Start, and wait with them**, translating the English output as it goes:

```bash
cd ~/my-knowledge && ./start.sh
```

- `== Starting the middleware stack ==` — Postgres, Qdrant, Meilisearch and private RustFS object storage come up locally; the first run downloads container images, which is slow. If Docker refuses with `all predefined address pools have been fully subnetted`, the machine's other compose projects have exhausted the default subnets: either have the user clean up stale networks (`docker network prune`, their call), or declare an explicit unused subnet under the project compose file's default network — never touch other projects' networks.
- `== Detecting system environment ==` — timezone/language probed; these are detected values, confirmed at step 4 (principle 4).
- `== One thing to confirm first: this library's primary language ==` — appears only when the material's language disagrees with the system's; Enter continues with the material's.
- `== Ingesting N materials ==` — verbatim text lands first, then index and compile jobs queue.
- `== Draining the compile queue ==` — one line per job: `job x/y: <material> +n claims`. This is the model reading material, judging, writing canonical documents — the slowest stretch; `rejected by the gate` is not a failure, it retries automatically. Long steps like this must be run to natural completion: keep the `nohup`-wrapped command in the FOREGROUND of a session you hold open and poll its log from another one — a detached `nohup … &` gets reaped the moment your tool session closes in many agent runtimes, leaving an empty log that looks like instant success.
- `== Your knowledge base at a glance ==` and `== Demo questions ==` — the payoff; go to step 3.

**Done when**: the glance and the demo Q&A printed.

---

## 3. Step two: show the result properly

**Goal**: this is the aha moment — don't rush past it.

**Your moves**:

1. **Open up the glance**: the directory tree + one line per document. Point at it: the compile model itself decided which pages exist, who deserves one, which thread deserves one.
2. **Read out one cited answer**, then run one with the raw text: `./app.py ask '<a demo question>' --sources` — let them see every conclusion clicking back to the exact source passage.
3. **Offer the browser** if they would rather click than read: `docker compose --profile console up -d --wait` inside the project (first build takes a few minutes), then open `http://127.0.0.1:<PNEUMA_APP_WEB_PORT from .env>` — the library, the material, the compile history and the Engine Console, all over this project's own engine. Everything except asking works without a key.
4. **One paragraph for the four levels**: the raw material is stored verbatim (L0), full-text and semantic indexes are built over it (L1/L2), and on top sit a few "canonical" documents (L3) written by the compile model under the judgement in `engine/compile/contract.md`, every conclusion carrying citations back to the source. One-line summary: nothing of the original is lost; only what deserves long-term memory enters the canon.
5. **Say what the demo is**: everything in it (people, project, the example contract) is a synthetic placeholder, about to be replaced piece by piece with their own.
6. **Point at `engine/`** — one breath, not a lecture: everything that decides what this library does with their material lives in that one directory (which models, how material is cut, how answers read, when the library audits and reorganizes itself, and the contract itself). It is its own git repository, so every change is a version. Say the one sentence that matters and move on:

   > Everything about how this thing thinks lives in `engine/`. It keeps its own history, so we can change something, look at the result, and go back if it was worse.

### The two answering lanes

`ask` has two. They are the framework's built-in implementations of the two canonical retrieval shapes, shipped so a project starts from a working reference — not a rule about which one to use:

- **fast** (the default) — multi-path retrieval answered in one model call: lexical and vector retrieval over the compiled claims and the raw source, fused, then one answer.
- **deep** (`./app.py ask '<question>' --deep`) — an agentic loop over the same evidence: it re-searches from new angles, opens canonical documents in full, follows the links inside them, and fetches verbatim spans, until it can answer.

Both cite, both leave no consultation record from this driver, and both print what they spent. Two mechanical differences. Cost: fast is one call over a prompt whose size follows from the caps; deep is a number of calls nobody knows in advance. Reach: a loop can walk from a document to its neighbours, because a document read in full carries its links; one shot cannot.

Which lane a question goes to is the project's own design — always fast, routed per question, both offered side by side. Run one of *their* real questions through each and read the two cost lines together; that measurement, on their own material, is what a routing policy comes out of.

**Done when**: they have seen the glance and one answer that clicks back to source.

---

## 4. Step three: read their data

**Goal**: derive what modelling needs by reading a sample; ask only for what cannot be inferred.

**Your moves**:

**4.1 Have them stage a small sample** in a local directory — the material they most want organized. The ingester eats `.md` only (`README.md` is skipped); convert other formats for them. One file = one material, frontmatter carries `date:` (the authoritative occurrence date), `title:`, `type:` (`conversation` parses `speaker: content` turns; anything else is treated as a document). `my-data/` shows the shape.

**4.2 Read the sample and derive four things yourself** — never ask "what kind of data is this":

- **Material shape**: source channels, arrival rhythm (daily? weekly? in batches?), item size, language, modalities (text / image / audio / files), where the authoritative timestamp lives, and which representations are original versus machine-derived;
- **Recurring long-lived subjects**: which people, projects, products, topics keep evolving? "A thing that evolves independently = one document" is the first law of filing — one basket for everything crushes the library;
- **Who the owner is**: whose viewpoint is this material written from? What do they roughly do?
- **How it will be asked**: work backwards from the material to what they'll come back for (what happened / who owns it / when / how it changed).

**4.3 Design context assembly after choosing the compile model — never before.** A model's multimodal capability only counts when the active provider and request path actually deliver native media content blocks; an image URL flattened into a text string is not vision.

The shipped native-media boundary is explicit: `pneuma.source.im/v1` supports JPEG, PNG, WebP and GIF images on messages, stores originals privately in RustFS/S3, preserves caption/OCR as labelled derived representations, compiles in `caption` or `native` image mode, and resolves the original from the same cited source block in the web reader. Audio, video and generic files are not yet native inputs; say so rather than implying otherwise.

1. Read the compile role from `engine/engine.yaml` and verify the selected model *and routed provider* against current capability documentation. For example, OpenAI's GPT-5.6 family — Sol, Terra and Luna — accepts image inputs, so an OpenAI route can assemble one turn from ordered text plus native `input_image` blocks. Still verify the provider route: a gateway may expose the model while flattening or rejecting the image part.
2. Match the representation to that verified capability. When native image input is available, keep the original image retrievable at a stable L0 address and pass it in the same message/turn as its text; captions, OCR and search queries remain explicitly labelled auxiliary representations. When the compile path is text-only, produce caption/OCR through a separate capable preprocessing step, retain its producer and link to the original media, and tell the user that the compile model did not see the original. A bare URL is neither a caption nor visual evidence. A labelled caption/OCR is nevertheless usable evidence when no native media is available: preserve its provenance without suppressing its substantive observation or wrapping every resulting claim and answer in a generic caveat.
3. Make conversion lossless before optimizing context. Treat original media, caption, OCR, transcript and query as independent optional fields — never gate one on another's presence. Record field counts and content digests before and after normalization, and fail the build on any missing, changed or reordered admitted field. Comparing rendered text with expected text assembled by the same renderer is not a round-trip check; both sides can omit the same source field.
4. Choose fidelity from the use: low detail for broad scene context, higher/original detail for small text, charts, spatial relations or other fine evidence, while measuring image tokens and latency. Prove the path with one minimal real call containing an actual media block before the full build. If the current SourceAdapter or model adapter cannot preserve it, surface that as a framework gap and either add the missing adapter path or use the labelled derived representation — never call a text-only run multimodal.

This is context construction, not compile-contract prose. The contract may say how direct visual evidence differs from a generated caption; it cannot make an image reach a model.

**4.4 Ask for what's left.** Done right, usually three gaps remain: name/address-as, preferred answering language, and "what do you most want this library to remember for you". Plus the principle-4 confirmations (timezone, language).

**Done when**: the detected values in `engine/persona/profile.yaml` are confirmed with `provenance` flipped to `profile`, you can name the long-lived subjects in the material, and every source modality has an explicit, capability-verified context path with original and derived representations distinguished.

---

## 5. Step four: write `engine/compile/contract.md` together

**Goal**: the contract is the library's constitution — it teaches the compile model to judge what deserves long-term memory in THEIR domain, and on which page. Mechanism-level rules (citation discipline, immutable anchors, read-only frozen volumes) are enforced by the framework and don't belong in it.

The full practice (this section is just the operating procedure) is in [`docs/guides/compile-contract.md`](../docs/guides/compile-contract.md) — read it before writing, especially the type → implied-usage → recording-obligation derivation and the acceptance loop.

**Your moves**:

**5.1 Derive "type → implied usage" from their data** — never copy a preset checklist:

- **Recurring events** in the material → they want a **timeline**;
- **Projects/things in motion** → they want a **progress record** (goals, decisions, milestones, state changes);
- **Recurring collaborators/contacts** → they want an **ever-growing working log**;
- The same thing under **several names** → a subject record with **aliases**, or its story splits across pages.

**People, things, and time are a knowledge base's three most common dimensions — but
they are three axes of inquiry, not three preset families**: hold the material and ask
yourself "in THIS business, who exactly are the 'people'? in what unit do the 'things'
move? at what rhythm does 'time' flow, and what should carry it?" — the answers change
shape with the domain. In a workplace, people become project members and colleagues,
things become projects, time becomes progress records; in a personal library, people
become relationships, things become one's own work and life threads, time becomes
schedules and daily logs. Same frame, different landings — **what you deliver is this
trio answered for THEIR business, never a ready-made list**. Nor does the reasoning stop
at three axes: place, objects, channels — any dimension the material keeps hanging
judgements on gets asked into existence the same way. Of the three, time is the
easiest to miss: it tends to end up as an incidental note inside other pages, while most
domains deserve a deliberately designed carrier (a dedicated timeline family, chronology
pages per person or per thread, or a fixed dated-anchor section within pages) — the form
follows the business, but it must be a **conscious design decision**. Whatever the carrier, one law never bends:
**relative time ("yesterday", "next Monday") is anchored to the material's absolute date at
admission, with the original wording kept**. Resolve an exact date or span only when the
material or the owner's calendar supplies an unambiguous convention; otherwise keep the
anchored expression ("last week relative to 2026-07-18") instead of inventing endpoints. A
claim that says only "yesterday" is worthless to retrieval three months later, and this kind
of rot is caught by no mechanism, only by acceptance (see step 6).

Voice every inference as "because your material …, I suggest …" — let them nod or fix it.

**5.2 Land it.** The demo ran on the demo contract; now rewrite `engine/compile/contract.md` as theirs: the skeleton lives at `scaffold/templates/contract.en.md` (or `.zh.md`) — replace every TODO with the answers you derived together; `path_templates` in the frontmatter must match the subject families one-to-one; bump `version:` when done. Personal-knowledge-shaped cases can also start from a built-in reference strategy (`./init.py --list-references`; generate with `contract.mode = "reference"`) — still rewritten section by section afterwards: a reference body is someone else's domain judgement, not an answer.

**Commit it as a version of the engine**, so the next round has something to compare against and fall back to:

```bash
git -C engine add -A && git -C engine commit -m "contract: <what changed, in their words>"
```

**5.3 Optional — `people` and `time`, only when the material feeds them.** Three index components ship with the framework, off by default: `people` and `time` index the material, and `attention` reports what the library has been asked (it needs consultations, not material, so it earns its place once people are asking). Decide by looking at their data, and say plainly when the answer is no.

- **`people`** binds identities to person pages — but it reads them off the **source boundary** (a meeting's `participants`, an IM archive's `users`, a mail thread's addresses; see [source contracts](../docs/reference/source-contracts.md)), never off the transcript. Names spoken inside the text are not identities. The `.md` ingest this guide uses carries no participant list at all, so on that path `people` indexes nothing — a document-only library (a vault, notes, articles) has no turns and no participants, so there is nothing for it to bind. It has something to bind when their material arrives through the source contracts with those fields filled.
- **`time`** keys every block of material to the day it falls on in the user's timezone, and answers "between June and August", "what held on the 12th". The `date:` frontmatter is enough for day granularity; within-day precision needs per-block timestamps (a message's `sent_at`, a meeting segment's `started_at`), which again only the source contracts carry. Material whose dates are unreliable is material `time` cannot index.

Enable in `engine/engine.yaml` (the environment names are `PNEUMA_KNOWLEDGE_COMPONENTS` and `PNEUMA_KNOWLEDGE_PEOPLE_FAMILY`):

```yaml
components: people, time
people_family: memory/people/{slug}.md   # one of contract.md's path_templates, verbatim
```

`people_family` must be one of the path templates you just wrote into the contract — if the contract has no person family, `people` has nothing to bind to. Decide it here rather than later: the components take effect at the next start, and step 6 rebuilds the library from empty anyway, so the whole library gets compiled with them on. Commit the change in `engine/` like any other decision.

**Done when**: no TODO and no demo content remains, they have reviewed the draft item by item (principle 5), and the engine repository holds it as a commit.

---

## 6. Step five: reset, recompile, accept together

**Goal**: rebuild on an empty library from their data, then inspect it together like a product you both own.

**Your moves**:

```bash
./app.py down --volumes && rm -rf data/    # 0. back to a blank slate
./app.py up                                # 1. stack up again
./app.py init                              # 2. re-detect environment (confirm again)
./app.py ingest <their directory>          # 3. ingest their material
./app.py compile                           # 4. compile
./app.py glance                            # 5. the bird's-eye view
```

(If the demo data shouldn't linger, clear `my-data/` and the project root's `demo-questions.txt`.)

**Why the reset comes first** (say this to them): the demo library was compiled under the demo contract; families removed while rewriting (`path_templates` lines deleted) are neither migrated nor deleted — orphan pages linger. Rebuilding on empty is cleanest.

Then ask 2–3 questions they actually care about with `./app.py ask '…' --sources`, citations and all — **at least one of them a "when" question**: time questions instantly expose un-normalized relative dates (an answer saying "yesterday" or "last week" instead of a date means the contract's time section never landed).

**Accept together**: does it feel right to live in? Did the subjects that deserve pages get them? Which claims landed on the wrong page? Revise the contract after looking (bump `version` again), reset, recompile, `glance` again to compare. Commit each revision in `engine/` before recompiling, so "the version that produced this library" is always nameable. "It changed" is not the goal — finding the modelling that serves future use and maintenance better is.

When there's too much material to question by hand, the coverage challenge can serve as a first sieve: set `enabled: true` in `engine/compile/challenge.yaml`, and every committed compile then blind-generates questions, audits the canon for gaps, and compensates for what the material actually supports (writes still pass the gate). It does not replace looking together — it audits "was the recordable recorded"; whether the modelling is right still takes human eyes.

**Use the recall layers to fix the actual failure, not to mask it.** Candidate caps are cheap search breadth (`claim_candidate_cap`, `window_candidate_cap`). Final context is three deliberately different faces: compiled `claim_cap`, dense `episode_summary_cap`, and exact `window_cap`. An episode summary is generated L2 content, not a quotation: the answer sees it under an explicit `derived episode summaries` heading with source title, occurrence time, section and exact block span. A small raw-window budget is therefore intentional — summaries carry broad meaning, raw windows carry exact wording.

The Recall view shows the claims, derived episode summaries, and verbatim excerpts actually supplied for each answer. Use that ledger with `./app.py ask '…' --sources`: do not infer a retrieval failure from the final prose alone.

Diagnose from the user's symptom. If a relevant episode is absent altogether, inspect semantic indexing and candidate breadth. If the summary finds the right event but the answer lacks an exact number or phrase, admit a little more verbatim context. If answers are noisy, reduce final claims/summaries/windows before narrowing the search pool. If no episode summaries exist, changing `episode_summary_cap` cannot create them: use semantic chunking and rebuild the derived layer. If the right facts consistently land under the wrong subjects, fix the compile contract — recall settings cannot repair a bad knowledge model.

Two settings change how a question's evidence is COMPOSED, once retrieval has already found
the material. `evidence_strategy` decides who chooses what the answer sees: `ranked` takes the
ranked head of each face and nothing judges the cut; `select` spends one bounded call that
returns coordinates across claims, derived episodes, verbatim windows and known canonical
documents, which the framework validates before unioning ranked safety anchors — a second
serial call, so its latency adds rather than overlaps; `all` hands the pool over whole.
`answer_format: structured` is independent of the three: answer text, answer kind and exact
citations travel as separate fields and the cited spans are validated. Set either in
`engine/recall/recall.yaml`, or pass `--evidence-strategy` / `--answer-format` for a single
question — which is the cheap way to put two of them beside each other on one of theirs.

What makes that comparison theirs rather than borrowed: the API reports the candidate counts,
and under `select` how many claims, episodes and windows the model itself chose before the
deterministic safety anchors and the provenance rollback. Model-selected counts near zero
beside a large final ledger say the serial call is not contributing what it costs. Read
quality, latency and cost as three separate numbers on their own acceptance questions.

None of these switches repairs missing L0, bad semantic segmentation or a wrong compile
contract: they change query-time composition and nothing upstream of it.

For downstream automation, use the response's citation-free `answer_text`; interactive
surfaces should keep the cited `answer`. When replaying an old question, pass its original
time explicitly (`./app.py ask '...' --as-of 2025-06-14T09:00:00+08:00`). Omitting `--as-of`
means “ask now,” which is correct for live use but changes the meaning of relative-time
questions during a replay.

**Done when**: within two or three rounds the library "looks right" — that's delivery.

---

## 7. Step six: evolution — the library learns its own shape

The contract you wrote at step 4 was a judgement about data the user HADN'T fully lived
yet. As material keeps arriving, two correction levers exist, and knowing when to reach
for each is part of your job:

- **Contract revision (judgement drift)**: when acceptance keeps flagging the same
  mis-filing, rewrite the relevant caliber in `engine/compile/contract.md` and bump
  `version:` — it governs future compiles only; nothing recorded is rewritten. Always cite
  to the user WHICH accrued material motivated the change.
- **Schema evolution (structure drift)**: when whole new subject families emerge (a new
  project, a new life thread), the framework notices on its own — after compiles, once
  enough new material accrues, it drafts a reorganization proposal on a branch and waits.
  Nothing changes until someone reviews it:

  ```bash
  ./app.py evolve            # list proposals (draft / adopted / dropped / no_change)
  ./app.py evolve show <id>  # the proposal: new families, rationale, changed pages
  ./app.py evolve adopt <id> # accept — merge the branch, rebuild derived layers
  ./app.py evolve drop <id>  # decline — branch deleted, canon untouched
  ./app.py evolve run        # fire a round manually instead of waiting for the trigger
  ./app.py evolve step       # UNATTENDED pipelines use this one: idempotent — disposes a
                             #   pending draft per --policy (adopt-clean default / keep),
                             #   else runs a round and disposes the result. `run` refuses
                             #   while a draft awaits review, so scripts composing
                             #   run/adopt by hand end up hand-rolling this state machine
                             #   — call step in a loop instead. Exit 0 progressed/no-op,
                             #   2 draft kept for human review.
  ```

  Walk every proposal through with the user before adopting (principle 5 applies to
  structure too). Reading a proposal costs nothing; adopting one reorganizes pages.

**Tune the trigger to the data's rhythm** — `engine/evolve/evolve.yaml` ships
`auto_trigger: false` (so a first run holds no surprise model spend) with the thresholds
already stated: fire after 5 new documents AND 30 new claims. A slow personal library wants
the trigger on and lower thresholds so structure keeps up; a daily bulk feed wants them
higher so proposals arrive weekly, not hourly; a fixed-schema deployment leaves it off and
runs `./app.py evolve run` when it feels like it. Decide from the material's arrival pattern
you observed at step 4, say why, and commit the change in `engine/`.

**Where to iterate, and what never becomes a knob.** `engine/` is your workbench: strategy
files you edit and commit, each stating its blast radius in `engine/README.md` (answering and
retrieval affect the next question; models and prompt overlays affect the next start;
contract, challenge and evolve govern future compiles only; chunking needs a derived rebuild
for material already indexed). The contract is the one thing in there that is NOT a knob and
must never be treated as one — it is a judgement document, and the reason it is prose is that
what deserves long-term memory in someone's domain cannot be expressed as settings. If you
ever find yourself wanting to encode domain judgement as a flag, the judgement belongs in the
contract instead.

**Daily routine to hand over**:

- Keep ingesting: `./app.py ingest <dir>`, then `./app.py compile`.
- Ask any time: `./app.py ask 'question'` (`--sources` prints the cited raw text too).
  Answers follow the engine's answer-style preset (`answer_style` in
  `engine/recall/recall.yaml`, or per ask with `--style`): `concise` = the bare exact value,
  `conversational` = a natural chat reply (default), `detailed` = a self-contained written
  note. Pick for the consumer of the answers — a person chatting wants `conversational`; an
  API client or automation that expects one compact value wants `concise`; written digests
  want `detailed`. Style never changes the truth discipline, only the shape.
  Original media is query-local and off by default: add `--include-original image` only when
  the question requires direct visual inspection (objects, colours, text, layout). Tool/API
  callers make the same choice with `include_original_modalities: ["image"]`; textual facts
  leave the enum list empty and continue using labelled derived representations.
- Look any time: `./app.py glance`, `./app.py status`, `./app.py evolve`.
- Look at the engine itself: `git -C engine log --oneline` is the history of every decision
  you two made about how this library thinks.
- Long documents roll over automatically (history into read-only volumes).
- Leave them with: the contract can be changed any time; changes govern future compiles only — what's recorded is never silently rewritten.

---

## Red lines

- User data and personal information never land anywhere git might commit: the project directory lives outside repositories, or `git check-ignore` proves it ignored (the generated .gitignore covers only `.env` and `data/` inside the project). `engine/` is the one thing inside the project that IS versioned, in its own repository — so nothing but strategy, contract, profile and overlays ever goes in there.
- The API key goes only into the project's `.env`, typed there by the user's own hands: never into answers files (the generator refuses), never into anything under `engine/` (which is versioned; the API even refuses key-shaped content on write), never through your commands, stdin or chat — an agent's tool calls are recorded, so a key that touches them is a key persisted in a transcript.
- Never invent profile facts for the user.
- Contract drafts are registered only after the user has reviewed them.

## How you know you are done

- [ ] The project directory is outside any git repository (or `git check-ignore` passes); `.env` filled, not committed;
- [ ] The demo ran once; they saw the glance and one cited answer;
- [ ] `engine/compile/contract.md` has no TODO and no demo content; `version` bumped;
- [ ] `engine/persona/profile.yaml` timezone/language confirmed by them, `provenance` flipped to `profile`;
- [ ] `git -C engine log` reads as the decisions you made together, one commit per change, and the working tree is clean;
- [ ] The library was compiled from their data after a reset (no demo pages linger);
- [ ] 2–3 questions they raised themselves got cited answers they accept;
- [ ] At least two rounds of "look → revise contract → recompile", and the last one ended with them saying it looks right;
- [ ] They know how to add material tomorrow, how to ask, and where the contract lives.
