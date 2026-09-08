# Coding agent mode — a coding agent as the Steward

**English** | [简体中文](coding-agent-mode.zh-CN.md)

Status: design; §11 steps 1 to 4 are built on the feature branch — the draft state form,
`pkc draft`, the `open`/`finish` lifecycle and byte equality; the `RoundRunner` extraction,
`agent:<backend>` as a model spec, the worker's behaviour under it and the process view's
waiting-for-Steward state; then the per-command post-check, `pkc draft check` and `pkc library
check`, the read commands with `pkc recall --evidence` and its handoff, `pkc owner say` and
`pkc ingest`; and now the skill package — the backend manifests, the generator, `pkc skill
install / verify / show`, the `pkc:start` block, the `Executor-Skill:` trailer, the scaffold's
"who compiles" question and the re-install on engine apply. and now the backends themselves — the
liveness probe and `pkc skill probe`, the unattended launcher (timeout, backoff, hermetic
per-job config home, reaped process group, usage from the harness's own JSON), the agent round
runner and the worker's unattended posture, and `open`'s trailer audit. And now the console's
Steward view (step 5b): the `WS /v1/users/{id}/steward` bridge and its `GET`, one live
harness session per Owner held in the API process, two protocol adapters (Codex's app-server
JSON-RPC, Claude Code's stream-json) normalizing both wires into one event vocabulary, the
Owner lens's Steward view rendering it, the invalidation that moves the history / process /
sources views while the Steward is still typing, and the verbatim check on `pkc owner say`.
And now the archive at this door (step 5c): `pkc archive propose / confirm / ls / show /
drop / inventory` over the upstream archive service, `--include-archived` on every read
command that lists or searches, and the skill's own section for it. The evolve door (§5.7) now runs on the same agent, and compile briefs can be the Steward's own text. Read
[steward-owner-visitor.md](steward-owner-visitor.md) first:
this page fills the Steward role with a body, and everything here rests on that frame.

## 0. Why this page exists

Every model call in the framework today goes through langchain: a `BaseChatModel` the
service assembles per role from `engine.yaml`. Coding agents — Claude Code, Codex — are now
strong enough to do the same work, and they bring two things an API model does not: the
Owner's own subscription, and whichever model that subscription reaches. The library does
not care. Its authority is L0 and canonical, its attribution names the contract, the wording
and the components and has never claimed to name the model
([architecture §6](../architecture.md#6-the-compile-contract-skill)), and the Steward frame
already says which model the Steward runs is the Steward's own affair. So *who executes a
model round* is a Steward-internal choice, and this page designs the second body the
Steward can have: **a coding agent, taught by a generated skill, acting through the
framework's own CLI**.

Three rulings fix the shape before any mechanism is described:

- **The door is a CLI, not a protocol.** The agent reaches everything through `pkc`, a
  command-line face over the framework, and the skill teaches it that face. No MCP server:
  a coding agent already knows how to run a command and read its output, and a CLI is the
  one surface every harness has.
- **The Steward reads everything and writes through one door.** As the library's Steward,
  the agent may read any L0 block, any index, any canonical page, any kept record. It writes
  canonical through the same claim-level draft the langchain compile uses, under the same
  gate. Context completeness is a mechanism, not a request: the door refuses a write to a
  page the draft has not read.
- **Codex and Claude Code first, Codex first among them.** Kimi's headless mode cannot yet
  carry a structured flow and reports no token split; it stays out of the first version.
  Early testing runs on Codex.

## 1. Roles, and what moves each of them

The frame names three roles; a deployment adds a fourth that the frame folds into the Owner
when one person does everything. Stories below are written against these motivations, and
every mechanism in §5 onward traces back to a story (§12).

### Owner

The person the library exists for. Provides the material, states the intent, calibrates.

| | Motivation | What "good" feels like |
|---|---|---|
| O1 | **Build** a trustworthy library from raw material without learning the machinery | "I pointed my agent at my data and had a library in an afternoon" |
| O2 | **Understand** what the library knows and how it is organized | a glance, a page, a history — and the shape makes sense |
| O3 | **Ask** and get answers that cite their evidence | the answer says where it comes from, and the citation resolves |
| O4 | **Correct** anything that is wrong — a fact, a state, a filing, a name — by *telling* the Steward, and see it land with provenance | "I said the amount was 5,400, and the page now shows that, with the old figure kept as history" |
| O5 | **Shape** what gets recorded and how — the contract, the families, the structure | the library reorganizes on a branch, I read the diff, I adopt |
| O6 | **Keep it alive** without babysitting: new material compiled on schedule, and be told what changed | a morning brief, not a morning of work |
| O7 | **Choose the model and the bill**: use my subscription, use a better model, switch later, lose nothing | "I moved from an API key to Codex; the library did not notice" |
| O8 | **Trust and audit**: every claim cites, every change is dated, every question is on record, a bad compile can be rolled back | nothing in the library got there without a trail |
| O9 | **Keep it private**: data stays local; only the model provider sees fragments; the agent leaks nothing | one sentence at setup, and it stays true |
| O10 | **Delegate standing work**: "every morning, pull yesterday's chats from this IM and the mail from these people, and file them as these libraries" — without waiting for the framework to grow a connector, and cancellable any time | I described the routine once; the Steward runs it; stopping it is one sentence |
| O11 | **Retire what no longer holds**: a project that ended, a topic that was wrong — out of the current picture, kept as history | the page is archived and dated, not deleted, and stops surfacing |
| O12 | **Talk to the Steward where the library is**: one conversation in the console, in my words, and watch what it does to the library as it does it | I said it in the chat; the history view moved while the Steward was still typing |

### Steward

The agent that compiles, answers, drafts evolution, grooms. In this design its body is a
coding agent running under the Owner's account. Its motivations are the conditions under
which it can do the job well.

| | Motivation | Without it |
|---|---|---|
| S1 | **Complete context before any write**: the contract, the outline, the sources of the job, the pages it is about to touch | a claim filed on the wrong page, a state superseded that was never read |
| S2 | **A door that refuses at the write**, naming what is wrong | a whole round spent before the gate says no |
| S3 | **Read access to everything**: L0 verbatim, L1/L2 search, canonical, glance, consultations, compile events, jobs | it answers from what it happens to have been shown |
| S4 | **Own its round**: claim the work, know the budget, know what is owed, finish, repair | it does not know when it is done |
| S5 | **Turn the Owner's speech into acts**: a statement becomes a cited source and a compile; an intent becomes a contract draft; never a bypass, however the Owner phrased it | "just fix it" writes an uncited claim |
| S6 | **Report** what it did, what it could not, what it cost | the Owner reads git to find out |
| S7 | **Work in either posture** — sitting with the Owner, or unattended on a queue — with the same tools | two tool faces, two behaviours |
| S8 | **Be told, after every act, whether the library is still whole** — not asked to keep it whole. It may misread, it may misfile; what it cannot do is leave dangling or uncited content behind, because the command that would have refuses and says why | correctness rests on the agent's diligence |
| S9 | **Do the Owner's non-standard work with its own hands** — fetch, transform, schedule — and enter the framework only through the official input boundary | either the framework grows a connector per upstream, or the Steward writes into the library directly |

### Visitor

Reads, as permitted. This design changes nothing for Visitors and adds one boundary: the
coding agent is the Owner's Steward instance; Visitors reach the library through the API and
the console, never through the Owner's agent session.

| | Motivation |
|---|---|
| V1 | Ask and get a cited answer |
| V2 | Leave a trace or none — `business` counts as use, `silent` leaves nothing |
| V3 | Browse the library, never the machinery |

### Operator

Runs the stack. In a personal deployment this is the Owner, and the Steward — being a coding
agent — can do most of it when told to.

| | Motivation |
|---|---|
| P1 | Stand up, tear down, restore, upgrade machinery, rebuild derived layers — canonical untouched throughout |
| P2 | See health: jobs waiting, *who is expected to act on them*, what is stuck |
| P3 | Keys and secrets never enter a versioned file |

## 2. Stories

Each story names the role, what they do, and what they see. Stories marked **v1** are in the
first version; **v2** are designed here with their shape stated and built next.

### Owner directs the Steward to change the library (O4, O5 — the main flow)

- **2.1 A wrong figure (v1).** The Owner, in a Codex session in the project directory, says
  *"the contract amount is 5,400, not 5,000."* The Steward records the statement as an
  `owner-dialogue/v1` source, opens the compile it enqueued, reads the page that holds the
  claim, and writes `supersede_claim` citing the statement. The Owner sees the page's current
  view show 5,400 and the old claim still there, frozen, with its date; the history view
  shows one `claim_superseded` event citing `¶1` of their own statement.
- **2.2 A misfiling (v1).** *"That decision belongs to the Harbour project, not to the person."*
  Same path: a statement, a compile; the Steward appends the claim to the project page citing
  the original source **and** the statement, and edits the person page's claim to record the
  refiling. Nothing is deleted; the ledger says what moved and why.
- **2.3 A name (v1).** *"阿宝 is Zhang Wei."* The statement compiles into the person page's
  overview `aliases` under the `people` component's checks — the same refusals a daily compile
  meets if the alias is somebody else's identity.
- **2.4 "Just delete it" (v1).** The Owner asks the Steward to remove a claim. The Steward
  cannot: the ledger has no delete, and the skill says so in one sentence, offering the two
  things it can do — supersede it with a statement, or edit it in place if it was wrong when
  written. The refusal is the door's, not the agent's politeness.
- **2.5 Merge two pages (v1).** *"These two people are the same person."* Structure, not
  content: the Steward opens an **evolve draft** on a branch, moves the claims, retires one
  page, and the evolve gate accounts for every anchor. The Owner reads the diff in the console
  and adopts; the three-way merge lands it. Same door, evolve mode.
- **2.6 Change what is recorded (v1).** *"Start keeping a timeline for every project."* The
  Steward drafts the contract change and the affected path templates as an evolve proposal;
  the Owner reviews the rationale and the diff, adopts, and future compiles follow it.
  Canonical is never rewritten by this.

- **2.5b Retire a subject (v1).** *"The Harbour project is over; archive it."* `pkc owner
  say` records what the Owner actually said and prints the source id. `pkc archive propose
  --document memory/topics/harbour.md --statement <sid>` computes what follows from it — the
  sources only that page cites, the pages leaning on those sources — and shows, under the
  page, the record it would leave: what Harbour was, what it held, and the Owner's reason.
  The Steward reads that closure back and confirms what the Owner named; one job moves the
  page and its closed volumes under `archive/` with their history and writes the record at
  the vacated path, in one commit. From then on the PAGE is out of the default retrieval
  scope — not in the glance, not in fast's claim face, not in a briefing pack, not in `pkc
  search` — and the SUBJECT is still answered, as archived, out of that record. *"Un-archive
  it"* is `--action unarchive`: the page comes back and the record goes away.
- **2.5b′ Retire the material too (v1).** *"…and the Harbour chat logs with it."* Nothing
  separate to run: the sources are in the same proposal as the page's cascade — the ones no
  live page still cites selected, the ones another page leans on listed with those pages
  named — and `--cascade` is how the Owner says yes to them. An archived source leaves the
  default scope of L1 and L2 search and of every lane's windows; it keeps every block in L0,
  its citations keep resolving, `pkc source fetch` reaches it unconditionally, and
  `--include-archived` puts it back into a search.

### Owner delegates standing work (O10)

- **2.5c A daily pull (v1).** *"Every morning at seven, fetch yesterday's messages from our
  team's IM through its API, and the mail between me and these three suppliers, and file the
  chats into this library as IM and the mail as email."* The Steward writes the task under
  `steward/tasks/`: a fetch script using the upstream API, a transform into `im/v1` and
  `email/v1` payloads, the target tenant and intake, and a schedule. It runs the task once with
  the Owner watching, `pkc ingest` accepts the payloads, and the compile queue takes over. The
  framework did not change: the five source contracts were the door, and `pkc ingest` was the
  hand. Scheduling is the harness's or the machine's cron, never the framework's worker.
- **2.5d Cancel it (v1).** *"Stop the supplier mail pull."* The task is removed from the
  task list and its schedule. What it already ingested stays: L0 is authority, and knowledge
  compiled from it stays until the Owner retires it (2.5b). Re-running a task later is harmless —
  a source's identity is its content, and a payload the library already holds is a no-op.
- **2.5e A task the Owner cannot see (v1).** Every task is a directory the Owner can read,
  versioned with the project; its upstream credentials live in `.env` or the machine's
  keychain, never in the task files. A task cannot touch `data/`: it produces payloads and
  calls `pkc ingest`, and the skill says so in the one place tasks are described.

### Owner talks to the Steward in the console (O12, O3, O4)

- **2.5f The conversation (v1).** Under the Owner lens the console has a **Steward** view: a
  conversation with the agent, running in the project with the same skill a terminal session
  would load. The Owner types *"what came in this week, and is anything about the tender
  contradictory?"*; the Steward's turns stream in, and each command it runs — `pkc jobs`, `pkc
  recall --evidence …`, `pkc draft append-block …` — renders as a step with its result folded
  under it. When a command changes the library, the history and process views update in the
  same browser without a reload.
- **2.5g A statement in the chat (v1).** *"By the way, Li left the supplier in June."* The
  Steward records it with `pkc owner say`. In the console posture the bridge holds the
  transcript, so the command **verifies mechanically that the recorded text is a verbatim
  substring of what the Owner typed** — a paraphrase of the Owner is not the Owner's statement
  and is refused. The Owner sees the refusal as a step like any other, and sees the source
  appear under Sources when it passes.
- **2.5h Leave and come back (v1).** Closing the tab does not lose the Steward: the session
  is the harness's own, and reopening the view resumes it. A Visitor lens never has this view;
  the Steward is the Owner's.

### Owner builds and keeps a library (O1, O6, O7)

- **2.7 First library, Codex compiling (v1).** `./init.py` asks for the embedding key as it
  does today, and one new question: who compiles — an API model, or the Owner's coding agent.
  The Owner picks Codex; the generator probes `codex login status`, installs the skill into
  the project, and writes `compile: agent:codex` into the engine (§3.1). `./start.sh` ingests the demo material and the Owner opens Codex in the
  project: *"compile what's pending."* They watch the Steward open the job, read the sources,
  write claims one command at a time — each with its citation visible in the terminal — and
  finish. The console's history view shows the commit.
- **2.8 Unattended (v1).** The Owner drops a week of material into `my-data/` and runs
  `./app.py compile`. Under an agent executor the worker claims each job and spawns the
  harness headless with the same skill; the Owner reads the brief the next morning. Nothing
  about the queue, the per-user single writer or the self-heal changes.
- **2.9 Sitting with the Steward (v1).** Same material, but the Owner wants to steer: *"compile
  today's, and the meeting about the tender is the one that matters."* The Steward compiles
  interactively and the Owner corrects mid-way; the door is the same, the budget is the same,
  the gate is the same.
- **2.10 Switch executors (v1).** The Owner moves `compile` from an OpenRouter model to
  `agent:codex` in `engine.yaml`. The Engine Console states the blast radius — restart, and
  future compiles only — and the library is byte-identical afterwards. Moving back is the same
  edit.
- **2.11 A better model (v1).** The subscription's model is whatever the harness runs. The
  Owner changes it in the harness, not in the engine; the compile record says which one ran.

### Owner understands, asks, audits (O2, O3, O8)

- **2.12 Ask the Steward (v1).** *"Who owns the tender now?"* With an answer model configured
  the Steward runs the fast lane. Without one, it asks the CLI for the assembled evidence —
  claims, verbatim windows, glance — and answers from that, citing the handles the CLI gave
  it. Either way the Owner gets a cited answer in the same session they compile in.
- **2.13 What did you do? (v1).** After a compile the Steward reads the post-compile brief
  and tells the Owner what changed, in the Owner's language; the Owner can open the same
  brief in the console.
- **2.14 Why is this here? (v1).** The Owner points at a claim; the Steward fetches the cited
  span verbatim and shows it. That is the L0 fetch the framework already has, reached by CLI.
- **2.15 What did it cost? (v1, partial).** Unattended runs record the harness's token usage
  on the job. Interactive runs cannot see the harness's counters; the job records the
  executor and *no* usage, absent rather than zero — tokens are never guessed.
- **2.16 Roll back (v1).** A compile landed nonsense. The Owner says so; the Steward names the
  version and the Owner reverts in the console, or tells the Steward to. Derived layers
  rebuild; canonical history keeps the reverted version.

### Steward doing its work (S1–S7)

- **2.17 Open a job (v1).** `pkc draft open <job>` claims the job, renders the contract and
  the task — the same bytes the langchain compile would put in its system and human messages
  — and creates the draft on disk. Until this has run, no write command exists for the job.
- **2.18 Refused at the write (v1).** `pkc draft append-block` with an uncited text, a bad
  span, a path outside the templates, or on a page not yet read this draft — refused with the
  same text the langchain tool would have returned, exit non-zero, nothing written.
- **2.18b Checked after the write (v1).** A write that passed its argument checks is applied,
  and then the command runs the gate's predicates over the page it touched — anchors, every
  citation on the page resolving into this job's sources or grandfathered, path ownership, the
  overview's rules, the components' checks. If any fails, the draft is not persisted, the
  refusal is printed, and the command exits non-zero. The Steward reads what it did wrong and
  retries. Nothing dangling ever survives a command; `finish` still runs the whole gate once
  more, over every page, as the final arbiter.
- **2.19 Budget (v1).** Every command spends one call from the round's budget, the same
  formula as today. `pkc draft status` says what remains and what the gate already finds owed;
  once the low-water mark is crossed each write's result carries that notice.
- **2.20 Finish (v1).** `pkc draft finish` runs the overview floor, then the gate. Clean: it
  commits, emits events and the brief, deletes the draft, completes the job. Violations: it
  prints them with the repair budget and keeps the draft open for one repair round; a second
  failure aborts the job and canonical is untouched.
- **2.21 Read anything (v1).** `pkc source fetch`, `pkc search`, `pkc canonical read`,
  `pkc glance`, `pkc history`, `pkc consultations`, `pkc jobs` — the read half of the HTTP API
  as commands, every one taking the tenant from the project.
- **2.22 Unattended, the same hands (v1).** The worker spawns `codex exec` with the skill's
  system text and the rendered task on stdin; the process runs the same `pkc draft` commands.
  The launcher owns timeout, backoff on rate limits, process-group cleanup and usage capture.

### Visitor, Operator

- **2.23 A Visitor asks (unchanged).** Through the console or the API, with the class they
  chose. The coding agent is not a Visitor surface.
- **2.24 Jobs waiting for a Steward (v1).** Under an agent executor a compile job does not
  drain itself. The console's process view says so: *"3 compile jobs waiting for the Steward
  — open your agent in the project, or run `./app.py compile`."*
- **2.25 Rebuild derived (v1).** The Steward can run `rebuild_derived` when told to; it is a
  derived-only operation and needs no model.

### Cold start: what the Steward already knows (O1, O2, S1)

- **2.26 The Steward already knows the Owner (v1).** The harness the Steward runs in is the
  one the Owner has been talking to for months: its session history, its memory files, the
  preference stores of the other skills the Owner uses. Before the first compile the Steward
  reads what it already holds about the Owner and what the material shows — who speaks in the
  first person, who every message is addressed to, which language, which timezone — and
  writes the profile with `pkc profile set … --provenance inferred`: name, occupation, a
  bio, interests, locale. Then, when the Owner is present, it lays the inference out and asks
  them to correct it, one thing at a time; a confirmed field flips to `owner`. The compile
  system message renders each field with its provenance, so a model reading an inferred name
  knows it is inferred. Nothing about the Owner enters the LIBRARY this way: the profile is
  registration-level self-introduction; a substantive fact the Steward knows from elsewhere
  becomes knowledge only when the Owner says it (`pkc owner say`, in the Owner's words).
- **2.27 Semantic retrieval is a choice, not a default (v1).** No embedding key is present.
  The Steward asks: *"I can run this library without semantic retrieval — lexical search and
  the compiled pages only — or you give me an OpenRouter key now."* The answer is recorded
  once (`pkc config set semantic_retrieval off`, or the key into the home's credentials) and
  never asked again; with the choice `off`, no embedding is built, every intake plan is
  `semantic_indexing: none`, and every lane runs on L1 plus canonical. A key added later and
  `semantic_retrieval on` plus `rebuild_derived` fills L2 in; canonical never moves.
- **2.28 A new session finds the library (v1).** The Owner opens Codex in some other
  directory weeks later. The global skill's first move is `pkc home status`: the libraries
  registered on this machine, each probed — stack reachable, framework repository present,
  key present, skill installed and fresh — and the Steward continues in the one the Owner
  means rather than proposing to create another.
- **2.29 Init is remembered (v1).** Each registered project carries its init state in the
  home: the stack's ports and compose project, the retrieval choice, the backend, which
  steps are done (stack started, profile confirmed, skill installed, first compile). A
  Steward that finds them done does not redo them, and an Owner is never asked a second time
  what they answered the first.
- **2.30 Facts the Steward knows from elsewhere (v1).** The Steward has read, in another
  session, that the Owner moved teams. It cannot write that into the library — it is not a
  source — but it can say so and ask; the Owner's *"yes, since May"* is the statement
  (`pkc owner say`, verbatim under the console's check), and the compile files it.

## 3. What the Owner experiences, in one walk-through

The question this section answers: *I use the new version and Codex is my Steward — what is
it like?*

**Setup.** `cd scaffold && ./init.py`. The keys are asked for as today; the one new question
is *who compiles*: an API model or a coding agent on this machine. Choosing Codex runs a
probe — the CLI is present and logged in — and the generator writes `compile: agent:codex`
into `engine/engine.yaml`, installs the skill into `.agents/skills/pkc-steward/` and a
`pkc:start` block into the project's `AGENTS.md` (and their Claude Code counterparts, so
either agent can be opened in the same project). Keys and the executor compose (§3.1).

**Building.** `./start.sh` brings the stack up and ingests the bundled material. The Owner
opens Codex in the project directory. Codex reads `AGENTS.md`, knows it is this library's
Steward, and knows where the skill is. The Owner types *"compile what's pending"*. Codex runs
`pkc jobs`, sees the compile jobs, and for each: `pkc draft open`, which prints the contract
and the task; it reads them; it writes claims with `pkc draft append-block …`, each command's
text and citation visible in the terminal; `pkc draft finish`. The Owner watches a compile
happen as a sequence of small, legible, refusable steps — which is the whole write discipline
of the framework, now on screen. When the console is open, history fills in as commits land.

**Living with it.** New material goes into `my-data/`; `./app.py ingest` and either
`./app.py compile` for an unattended run, or a sentence to Codex for a steered one. Questions
go to Codex or to the console. Corrections are sentences: *"that figure is wrong, it's
5,400"* — and the Owner can watch the Steward record the statement, open the compile, read
the page and supersede the claim, refused if it tries anything the gate would refuse.

**What it does not do.** It does not let the Steward edit a page directly, however clearly
the Owner asked — the door has no such command. It does not delete knowledge. It does not
guess what a run cost when it cannot know. And it does not make Codex a requirement: the API
executor stays exactly as it is, and the two can be switched at any time.

### 3.1 Keys stay where they are; the executor is a separate question

Choosing a coding agent replaces the compile model, not the deployment's keys. `init.py` still
asks for the embedding key (and, optionally, the answer model's) exactly as today, writes them
to `.env`, and `pkc` reads that file as the API and the worker do — so when the Steward runs
`pkc ingest`, L1 and L2 are built with the configured embedding, and the skill only has to say
that ingest indexes. The two questions compose freely: an OpenRouter key for embeddings and
recall with Codex compiling is the expected shape.

A coding agent drives compile, episodes and, by default, evolve; briefs are the Steward's text.
With semantic retrieval on, episode judgement runs through the index door (§5.12) and the
configured embedding still builds L2. `semantic_retrieval: off` (§5.9) skips that work and
needs no embedding key. For an enabled provider embedding that lacks a key, startup resolves
the embedding spec (`wiring.warn_missing_embedding_key`, beside `check_executors`), and when
that spec needs a key the deployment has not set, it logs one WARNING naming the setting
(`PNEUMA_KNOWLEDGE_EMBEDDING_MODEL`), the variable (`OPENROUTER_API_KEY`) and what will fail —
semantic indexing and semantic recall, at the first embed call. The same sentence is printed
by the generator when its answers left the key empty, and by `./app.py up` / `./app.py
preflight`; `pkc` says it once per process at the same startup point, since it shares
`build_context`. A reminder, never a refusal: L0 and L1 stay unconditional (I3), canonical
still compiles, and setting the key plus `rebuild_derived` fills L2 in. A keyless spec
(`fake:<dim>`, the scripted and test configurations) needs no key and produces nothing. A
local embedding adapter — the thing that would make a keyless deployment whole at L2 — is a
follow-up (§13).

## 4. Rulings

1. **The executor is a Steward-internal choice, configured as a model spec.** A role's model
   may name `agent:codex` or `agent:claude-code` exactly where it names
   `openrouter:…` or `scripted:…` today (`wiring.resolve_model_name`). The compile and evolve roles
   honour it; an unset evolve role inherits compile's executor. Episodes use the compile
   executor's harness through the index door (§5.12). Briefs are the Steward's text.
   Challenge is skipped under an agent compile executor: no job, door or skill step,
   even if an API challenge model is configured. The library's attribution trailer does not change; the job record
   gains `executor`.
   **Under an agent executor, consumption is the agent's reading, guided by
   `references/consume.md`; the API lanes are quality-testing tools for a keyed console.**
2. **One door, two postures.** The claim-level draft with its write tools and the gate is the
   only path into canonical for either executor. The langchain loop and the CLI are two
   clients of it. Whatever the CLI can refuse, the langchain tool refuses with the same text,
   and the same test sequence produces the same files through both.
3. **The draft lives on disk while an agent holds it.** A CLI has no memory between
   invocations, so `PatchDraft` gains a serialization and a home per job. It is neither
   canonical nor a kept record: ephemeral, deleted on finish or abort, and a second `open` on
   a job whose draft exists resumes it only for the same executor; another executor is refused.
4. **The skill is a rendering, not a second text.** Everything the agent reads that shapes
   its judgement — the contract, the compile instructions, the tool descriptions, the
   component preambles — already lives in the prompt catalog, byte-pinned per (contract ×
   wording × components). The skill package is generated from it; its hash is stamped beside
   the overlay hash. Nothing is hand-written twice.
5. **Prose is the complete specification; a workflow is an enforcement upgrade on the one
   backend that runs it.** The SKILL.md carries the whole procedure for every harness. Claude
   Code additionally gets a dynamic workflow that makes read-then-plan-then-write the only
   order of work. Codex follows the same words.
6. **Context completeness is refused, not requested.** Three mechanisms: no write command
   exists before `open` rendered the task; a write to an existing page is refused until that
   page was read in this draft (today's `mark_read` rule, widened from the overview verbs to
   every verb); a citation must resolve to a source of this job or be grandfathered from a
   previous commit (the gate as it stands).
7. **Owner speech enters as a source, never as an edit.** Every correction, refiling, alias
   and statement of state is an `owner-dialogue/v1` source first and a compile second. The
   CLI's `owner say` command does exactly that and nothing else; there is no command that
   changes a claim without a job.
8. **Structural change is the evolve door.** Merging, splitting, renaming pages, changing
   families or the contract: the Steward authors an evolve draft on a branch, the evolve gate
   accounts for anchors, the Owner adopts. Built in v1 (§5.7).
9. **Backends are data.** Each harness is described by one manifest — binary, install layout,
   headless launch shape, capabilities — and nothing outside the manifest branches on its
   name. Probes test liveness, never version numbers.
10. **Correctness is the framework's, and it is told after every act.** The Steward may err
    and may misunderstand; the errors the framework does not permit are caught by the command
    that would commit them, after it has applied the change and before it persists it. Every
    write command post-checks the page it touched with the gate's own predicates and rolls back
    on failure; `pkc draft check` runs the whole gate over the open draft at any time; `pkc
    library check` runs the repository-wide predicates over the committed library. A skill
    never carries a rule a command does not enforce.
11. **The Steward's standing work lives outside the framework.** Fetching from an upstream,
    transforming it, scheduling it, deciding which library it feeds: all of it is the Steward's
    own code and the harness's own scheduler, kept in the project under `steward/`. It enters
    the framework only through the five source contracts and `pkc ingest`. A new upstream
    never requires a framework change, and a task never touches `data/` or canonical.
12. **The archive is the upstream mechanism; at this door the reason is always the Owner's
    words, and the Steward confirms only what the Owner named.** Archiving is a move under
    `archive/` plus a record left standing at the vacated path, and nothing is deleted
    ([archive.md](archive.md)) — this feature adds no state, no filter and no arithmetic of
    its own — the statement-or-note rule is the SERVICE's (`422 note_required` at the
    confirm, `statement_missing` in the job), because the framework composes no sentence
    anywhere. What this feature adds is a posture at the CLI, and it is two refusals: `pkc
    archive confirm` refuses without `--statement` or `--note-file` before it asks the
    service, naming `pkc owner say` as where the Owner's words come from; and a confirm ticks
    the items the Owner NAMED, listing what follows either way and confirming it only under
    `--cascade`. Reading the past is one flag, `--include-archived`,
    on every command that lists or searches — and no flag at all to address one thing by name,
    which is what I3 and I4 already promised.
13. **The console's Steward view is a face over the same harness session, not a second
    Steward.** The service spawns the harness in the project with the same skill and bridges
    its stream to the browser; the agent acts through the same `pkc` commands; the library
    updates the same way. What the bridge adds is one mechanism the terminal cannot have:
    because it holds the transcript, an Owner statement recorded from the conversation must
    be a verbatim substring of an Owner turn. The conversation itself is the harness's
    session, not a kept record of the library.
14. **The profile is the Steward's first inference and the Owner's to confirm.** Every
    profile field carries a provenance — `inferred` (the Steward read it off its own memory
    of the Owner or off the material), `detected` (the system probed it), `owner` (the Owner
    confirmed or wrote it) — and the compile system message renders the word beside the
    value. The Steward writes the profile before it asks; the Owner corrects rather than
    fills in. What the Steward knows about the Owner from outside the material reaches the
    library only as the Owner's own statement.
15. **Semantic retrieval is a recorded choice.** `semantic_retrieval: on | off` is an engine
    knob. Off means no embedding model is built, every intake plan is `semantic_indexing:
    none`, and every lane and the index job skip L2 — not fake vectors, not a failing call.
    The choice is asked once, by the generator or by the Steward, and recorded; turning it on
    later with a key is one edit plus `rebuild_derived`.
16. **`~/.pkc` is the machine's home for libraries, and it is state, not knowledge.** A
    registry of the projects on this machine with each one's init state, the credentials
    the Owner provided once (mode 0600, read by settings as the lowest layer under the
    process environment and the project's `.env`), and the Owner's defaults. A Steward
    started anywhere reads it, probes what it names, and continues; nothing in it is a
    source, a claim, or a record of the library, and a project stays complete without it.

## 5. The `pkc` CLI

A console script in `pneuma-knowledge-service` (`pkc = pneuma_knowledge_service.cli:main`),
reading the same settings the API and worker read, so a project's `.env` and `engine/`
resolve it exactly as they resolve them. The scaffold emits a `bin/pkc` shim that loads the
project's `.env` and runs the framework's entry point. **`pkc` is the Steward's whole
vocabulary**: the skill, the `pkc:start` block and every refusal name `pkc` commands and
nothing else. `app.py` stays the Owner's project shell — stack up and down, the demo — and no
agent-facing text mentions it; whatever the Steward needs to do, `pkc` does. Every command takes its tenant from
the project (`PNEUMA_KNOWLEDGE_TENANT`, as `app.py` does today); a `--user` override exists
for multi-tenant deployments and is the only place a user id is typed.

### 5.1 Reading — the Steward's eyes

The read half of the HTTP API, as commands. Same handlers, same shapes, JSON on request:

| Command | Reads |
|---|---|
| `pkc outline` (`--json`, `--family <template>`, `--definitions`, `--include-archived`) | the complete map: every page under its family, one line each, no top-K or character budget; session start and the check after a compile |
| `pkc glance` (`--include-archived`) | the answering lanes' budgeted map (`canonical_glance`): top pages per family, with omission counts; choose subjects when outline is too long to scan |
| `pkc canonical ls` (`--include-archived`) / `read <path>` / `history <path>` | pages, a page, a claim chain — `read` and `history` are unconditional: an address resolves whether or not it is archived |
| `pkc source ls` (`--include-archived`) / `show <id>` / `fetch <id> ¶a-b` | L0: sources, structure, verbatim spans — `show` and `fetch` are unconditional |
| `pkc archive propose` / `confirm` / `ls` / `show` / `drop` / `inventory` | retiring a subject and bringing it back (§5.5) — a proposal, a confirmation, and one job on the ordinary queue |
| `pkc search <q>` (`--lexical` / `--semantic` / fused; `--include-archived`) | L1 / L2, in the default scope unless asked |
| `pkc recall <q> --evidence` (`--include-archived`) | the fast lane's assembled context without the answer call: claims, windows, episode summaries, glance, with query-local handles |
| `pkc recall <q>` (`--include-archived`) | the fast lane with the configured answer model, when one is configured |
| `pkc jobs` / `pkc history` / `pkc brief <version>` | the queue, compile versions, the post-compile brief |
| `pkc consult answer <handoff_id> --text-file <f>` / `pkc consult record --question <q> --text-file <f>` (or `-`; `--kind no_record`) | close a handed answer or record direct reading without a hand-over; every citation must resolve |
| `pkc consultations` / `pkc spend` | kept records of use, handed evidence and direct citation counts, and what they cost |
| `pkc evolve ls` / `show` | proposals and their diffs |
| `pkc library check` | the repository-wide predicates over the committed library: anchor uniqueness and continuity, citation shape and resolvability, path ownership, overview rules, component checks, trailer presence on every commit — reported, never repaired |

Both maps omit archived pages unless asked, retain live archive records, and label admitted
archived pages under the family of their live path, after live pages. Outline names empty
families in contract declaration order, counts closed volumes beside their page, and marks
records `[record]` and admitted archived pages `[archived]`. Its JSON is a family tree with
a total page count; pages outside declared families remain visible under a null template.
It derives metadata from one canonical listing, with no per-document reads or model calls.
The current listing loads document bodies; a persisted header index is a later optimization.

`pkc recall --evidence` returns what the fast lane would have
handed its answer model, and nothing the lane would not have: the model-free half of the
lane, exposed.

What the hand-over records is a **pending handoff**, not a consultation. A `ConsultationRecord`
is frozen and `is_miss` reads `answer_kind`, so a record written before the answer exists
would have to be rewritten when it arrived — which a kept record never is — or would state a
miss the lane never observed. So `--evidence` persists the material a record would be built
from (the question, `as_of`, the library ref sampled the way the lane samples it, the evidence
manifest, the query-local handle map, the visitor class) and hands back a `handoff_id`. `pkc
consult answer <handoff_id>` supplies the answer, builds the record through the fast lane's
own builder. A handle resolves through that map; a real source span or canonical anchor
resolves against this tenant's L0 block bounds or canonical anchors. Handed citations retain
`origin: "handed"`; resolving direct reads outside the manifest carry `origin: "direct"`,
without expanding `evidence_handed`. Under an agent executor the agent's reading IS retrieval,
so manifest membership cannot stand in for resolution. Invalid citations refuse the answer
with exit 4 and leave the hand-over open for correction. A valid answer is emitted through
`_spawn_recording`, the same path `/recall` uses. The handoff row is deleted then; one nobody
came back to expires
under `PNEUMA_KNOWLEDGE_RECALL_HANDOFF_TTL`, swept by the same self-heal that sweeps drafts.
**A question the Steward never answered therefore leaves no consultation at all**, and that is
stated rather than hidden: the alternative was a half-record, which would have had to lie in
one direction or the other. Which visitor class a `pkc recall` runs under decides whether the
answered handoff records anything, and the two faces default differently: `--evidence`
defaults to `business` — a Steward about to answer the Owner from that context IS the library
being used, which is what the use-side ledger exists to hold — while `pkc recall` on its own
defaults to `silent`, because a lane called for its own answer is being evaluated rather than
consulted; both say so in `--help` and on the handoff line, since a default that quietly
records nothing is how the attention ledger stays empty without anyone noticing.

When no `recall --evidence` ran, `pkc consult record --question <q> --text-file <f>` (or `-`)
uses that same resolution, builder and emission with lane `direct` and no hand-over. It
accepts `--visitor-class business|audit|silent`, defaults to `business`, and accepts
`--kind no_record`. One question, one record: correct a refused answer instead of re-running
recall to fix it. Keyless `recall --evidence` builds no model and reports which arms ran and
which were skipped (`arms` in JSON), including the unavailable glance pick; an empty or thin
manifest does not mean the agent cannot read the library directly.

### 5.2 Writing — the one door

```
pkc draft open <job-id>                      claim the job; render contract + task; create the draft
pkc draft status                             budget remaining, pages read, what the gate finds owed
pkc draft list-documents
pkc draft read-document <path>               marks the page read for this draft
pkc draft create-document <path> --frontmatter <json> --body-file <f>
pkc draft append-block <path> --heading <h> --text-file <f>
pkc draft edit-claim <path> <anchor> --text-file <f>
pkc draft supersede-claim <path> <anchor> --text-file <f>
pkc draft rewrite-overview <path> --json-file <f>
pkc draft set-fields <path> --json <json>
pkc draft search-knowledge <q> | search-source <q>
pkc draft <component-tool> …                 whatever the enabled components contribute
pkc draft check                              the whole gate over the open draft, without finishing
pkc draft finish [--brief <f>|-]              overview floor → gate → commit | violations; Steward brief
pkc draft abandon [--take-over]              release the job; delete the draft; explicit recovery of another owner
```

Text arrives through files or stdin, never argv: a claim is a paragraph, and a shell quoting
error is not a compile error the agent should be spending its round on. Command names,
descriptions and refusal texts come from the prompt catalog keys the langchain tools use
(`compile.tool.*`), so the agent reads one vocabulary in the skill, in `--help` and in every
refusal.

Each command loads the draft, runs the components' `prepare` for the job's user, applies
one tool function — the same closures `_build_tools` builds — **post-checks the touched page
with the gate's predicates**, and only then persists the draft and exits. A refusal at the
argument face is the tool's own `AnchorToolError` text on stderr with exit code 2; a
post-check failure is exit 2 as well, with the violation rendered as the gate renders it, and
the draft on disk is the one from before the command; budget exhausted is exit 3 with the
`compile.budget.call_refused` text; a gate failure at `finish` or `check` is exit 4 with the
rendered violations. Exit codes are the mechanism that lets a workflow script branch without
parsing prose, and the post-check is what makes "the library is still whole" a fact the
Steward is told rather than a duty it is given.

`finish --brief <f>` (or `--brief -`) accepts the Steward's own narration for the version:
non-blank, at most 8,000 characters, stored as derived text on the successful compile job.
It survives a repair round. Under an agent executor no brief model is called. Unattended,
the launcher's last message fills a successful version's missing brief under the same
bound; an explicit brief wins. Aborts, abandoned drafts and no-op rounds gain no brief.

### 5.3 Owner speech

```
pkc owner say --text-file <f> [--about <path>…]   record an owner-dialogue/v1 source; enqueue its compile
```

One command, one effect. `--about` is a hint carried into the job's source guidance so the
compile task names the pages the statement concerns; it changes nothing about what the gate
requires. The skill tells the Steward that every correction starts here, and the absence of
any other write path is what makes that true.

**The owner's own profile.** Who the owner IS is the one thing no material states, and the
contract cannot file their own facts on their profile rather than on a page about a stranger
unless the profile names them. The acceptance run proved the cost: the Owner was compiled into
`memory/people/chen-wan.md` because `engine/persona/profile.yaml` still said
`display_name: "Someone"`.

```
pkc profile show [--json]                       the profile this library compiles under; says
                                                whether it is still the placeholder
pkc profile set --file <f>|-                    a profile mapping (YAML or JSON), the same
                                                shape the file holds
pkc profile set --field name=value …            one field at a time, for the common case
```

`is_placeholder` is the mechanical half — the generator's own `display_name` with no facts
beside it — and it is what `show` reports, what `pkc draft open` prints ONE line about above
the round (a notice, never a refusal; the surfaces the harness is handed are byte-identical),
and what the skill's own first rule turns on. `set` is a single write:
`persona_profile.save_owner_profile` edits the project's `persona/profile.yaml` as text (its
comments are the documentation a person reads) and upserts the persisted `UserProfile` the
round is rendered with, so the file and the record cannot drift. `app.py init` writes through
the same functions. A page that turns out to BE the owner is retired like any other page —
after the facts worth keeping are on the profile and the owner has said so.

### 5.4 Ingest and standing tasks — the Steward's own realm

```
pkc ingest --contract im/v1|email/v1|meeting/v1|document-library/v1|owner-dialogue/v1 --file <f> [--intake <archetype>] [--user <tenant>]
```

`pkc ingest` is the CLI face of `/sources/import`: a payload under one of the five contracts,
an optional intake override, the tenant. It is the whole input boundary, and it is enough,
because what arrives shaped as a contract is the framework's business and how it came to be
shaped is not.

Everything upstream of it is the Steward's:

```
steward/
  tasks.yaml                    enabled tasks, each with its schedule and its target (tenant, contract, intake)
  tasks/<name>/TASK.md          what this task does, for the Owner to read
  tasks/<name>/fetch.*          the Steward's own code against the upstream API
  tasks/<name>/transform.*      upstream records → contract payload
```

The skill describes this realm in one section: a task is a directory; it reads its
credentials from `.env` or the keychain and never stores them; it produces payloads and calls
`pkc ingest`; it is scheduled by the harness's scheduler where one exists or by the machine's
cron running the harness headless; it is cancelled by removing it from `tasks.yaml`. The
framework's worker never runs a fetch. Idempotency is the framework's: a source's identity is
its content, so a payload the library already holds is accepted and changes nothing, and a
task may be re-run after a failure without care. `steward/` is versioned with the project so
the Owner can read every task and every change to it; it is not `engine/`, because a task is
an operation and not a strategy, and a task's change does not alter how anything is compiled.

The boundary this draws is the one the architecture already has — the SourceAdapter is "the
only layer allowed to grow with input types" — moved to where growth is cheapest: the
Steward writes the adapter for the Owner's one upstream, in the Owner's project, and the
framework's five contracts stay five.

### 5.5 Retiring knowledge — the archive at this door

*The mechanism is upstream and is stated once, in [archive.md](archive.md): archiving is a
MOVE under `archive/` plus a short record left standing at the vacated path, a source is
marked by `archived_at`, nothing is deleted, every address still resolves, and the set is
COMPUTED from what the Owner named and confirmed against one library state. Nothing in this
section adds to that — no state, no filter, no arithmetic of its own.*

What this feature adds is the face. `pkc archive` is six commands over the same
`archive_service` functions the HTTP routes call, never over HTTP:

| Command | What it does |
|---|---|
| `pkc archive propose (--document <path>)… (--source <id>)… [--action archive\|unarchive] [--statement <sid>] [--note-file <f>]` | computes the closure and keeps it; prints every item with its structured reason in words, and under each page the record it would leave — definition, facts line, reason |
| `pkc archive confirm <id> [--cascade] [--deselect <ref>]… (--statement <sid> \| --note-file <f>)` | accepts it and queues the one job, printing its id; `409 stale` is exit 2 naming the HEAD that moved |
| `pkc archive ls` / `show <id>` / `drop <id>` | the kept proposals (`stale` computed against the current HEAD), one whole with its job, and closing one nobody will act on |
| `pkc archive inventory` | what is in the archive now: pages with the day they went in and the record standing at their live path, sources with `archived_at` |

Beside them, `--include-archived` on every read command that LISTS or SEARCHES: `pkc
glance`, `pkc canonical ls`, `pkc source ls`, `pkc search` in all three modes, and `pkc
recall` in both faces. It is passed to the ports and the lanes exactly as the routes pass it,
and what comes back from the archive is labelled the way the wire labels it — `archived` in
`--json`, `[archived]` in the prose. `pkc recall --evidence` keeps the scope on the pending
handoff, so `pkc consult answer` closes it as a consultation over the scope the reading
actually covered. Addressing ONE thing by name takes no flag at all — `pkc canonical read`,
`pkc canonical history`, `pkc source show`, `pkc source fetch` (I3, I4) — and the absence of a
flag there is the promise.

**Two rules belong to this door and not to the wire.**

**The reason is always the Owner's words.** The record's third block quotes somebody
(archive.md §2.3), and that somebody is never the framework — nowhere, now: the framework
composes no sentence at all, `archive_service` refuses a confirm carrying neither a note nor a
`statement_ref` (`422 note_required`) and the archive job refuses one defensively
(`statement_missing`). So the rule is the service's as well as this door's, and what the door
adds is where it is said: `pkc archive confirm` refuses with neither `--statement` nor
`--note-file` before it asks the service, in words that name `pkc owner say` — the command a
Steward records the Owner with. `propose` is not held to it: a plan decides nothing and quotes
nothing, its `--note-file` is display text, and asking for the Owner's words at a moment that
cannot use them would teach a Steward that the note they gave is the one the record will
quote. Inside a console Steward session a `--note-file` passes the
same verbatim check `pkc owner say` applies (ruling 13) — the note is quoted into a claim on a
live page, which is exactly what that check is for. A note given beside a statement is
compared against its ¶0 by the service and refused `statement_mismatch` rather than silently
resolved, and the statement itself is fixed when the set is computed: a confirm may only name
the one the proposal already names, or supply the words as a note.

**Seeds by default; the cascade is asked for.** The planner computes what FOLLOWS from the
seeds, and what follows is not what the Owner said. So a confirm ticks the `seed` items and
unticks every `cascade` one unless `--cascade` says otherwise; `--deselect <ref>` leaves one
more where it is. Both kinds are listed either way — in the proposal, and again in the
confirm's own output — because a Steward confirming less than it showed would be hiding the
closure it was handed. This is a narrowing expressed through the confirm's ordinary per-item
override, so nothing is added to a set by hand: widening one is a re-plan with more seeds.

What the Steward does with it, in order: `pkc owner say` (keep the source id) → `pkc archive
propose --statement <sid>` → read the closure and the record preview back to the Owner →
`pkc archive confirm <id> --statement <sid>`, with `--cascade` only if the Owner said yes to
what follows. The record page is read-only afterwards, and a write refused under
`archived_path` is a fact about the library rather than an obstacle: the subject is retired,
and the Owner unmakes that by unarchiving it.

### 5.6 The Steward view in the console

One WebSocket per Owner session, `/v1/users/{user_id}/steward`, bridged to a harness process
the service spawns in the project directory: Claude Code over `--print --input-format
stream-json --output-format stream-json`, Codex over `app-server` JSON-RPC. The bridge
normalizes both into one event vocabulary the console renders — a turn, a step (command,
result, duration), a permission request, a turn's end with usage — and forwards the Owner's
messages down. The per-backend adapter is data on the backend manifest (§8), the same
manifest the unattended launcher reads; the wire-level differences (Claude announces its
session only after the first prompt, Codex synthesizes no turn-end and reports cumulative
versus last-request tokens, model switching on Claude is a control request) live in the
adapter and nowhere else.

The console side sits under the Owner lens only, beside the views it moves: a step that ran
`pkc draft finish` is followed by the history view gaining a commit, because both read the same
API. Steps are the agent's own tool calls, rendered — the console adds nothing the agent did
not do, and hides nothing it did. A disconnected tab leaves the harness session alive for
`STEWARD_SESSION_IDLE` and resumes it on reconnect; a killed harness is reported as such,
never silently restarted into a fresh session.

**What the build settled, beside what §5.6 already said.**

- **A second attach JOINS the session; it is not refused.** Two tabs on one library are one
  person at two windows, and both watch the same conversation — each is repainted from the
  session's own bounded event tail (200 events) rather than starting blank. Refusing the
  second tab would have protected nothing: what must not happen is two harnesses compiling
  one library at once, and one session per Owner is already that.
- **A restart is a message, not a reconnect.** "Never silently restarted" needs somewhere for
  the Owner's decision to live, so the socket takes `{"type":"start"}` and the view's "start
  again" is the only thing that sends it. A reconnect after an exit hands back the same dead
  session and its transcript, which is what lets the page show what happened before offering
  a new one.
- **The interactive launch shape is data, like the headless one.** The manifest gained
  `interactive_command`, `wire_protocol` and `interactive_adapter`; the adapter carries the
  two things a template cannot — how a user turn is written down the wire, and how the
  session or thread id is read back. Nothing outside `backends.py` branches on a backend name
  here either.
- **The Owner's turn is written before the harness sees it.** `steward_turns` is appended to
  first, in memory and in Postgres, because `pkc owner say` runs INSIDE the turn it is
  quoting: a transcript written afterwards would be one turn behind exactly when it is read.
  A bridged session whose transcript cannot be read REFUSES rather than skipping the check —
  a rule that switched itself off when it could not be enforced would not be one.
- **The bridge runs the harness in the project, not in an empty directory.** The unattended
  launcher's empty `mkdtemp` exists because nobody is watching; here the Owner is watching
  every command, and the harness needs `AGENTS.md` / `CLAUDE.md` and the installed skill,
  which are in the project. `PNEUMA_KNOWLEDGE_PROJECT_DIR` names it, defaulting to the API's
  own working directory.

The verbatim check (ruling 13): `pkc owner say` in a bridged session receives the session id
through the environment the bridge sets, asks the bridge for the Owner turns, and refuses a
text that is not a substring of one of them, whitespace-normalized. Outside a bridge — a
terminal session — the command has no transcript to check against and says so in the skill;
the statement is still a source, cited and dated, and the library's honesty does not rest on
the check, only the Owner's words do.

What is deliberately not built: a second chat surface (live context's room stays what it is —
a room the library listens to, not the Steward's conversation), a Visitor-facing agent, and any
storage of the conversation inside the library. The alternative of hosting the library console
as a mode inside a general agent shell was weighed; the console already owns the lens model
and the views that must move while the Steward types, so the bridge comes to it.

### 5.7 Structure — the evolve door (v1)

```
pkc evolve draft open (<job-id> | --new) [--from <proposal>]
pkc evolve draft status
pkc evolve draft propose (--file <f> | -)
pkc evolve draft move-claim <from-path> <anchor> <to-path>
pkc evolve draft rename <path> <new-path>
pkc evolve draft retire <path>
pkc evolve draft contract edit (--file <f> | -)
pkc evolve draft check
pkc evolve draft finish
pkc evolve draft abandon
pkc evolve adopt <id>
```

`open` claims an evolve job with the queue's per-user lock, or creates an Owner-requested
job with `--new`. It stores a `DraftSession` of kind `evolve` in the same DraftStore as
compile, protected by `COMPILE_DRAFT_TTL`; abandonment and expiry release the job without
writing canonical. Resuming reprints the pinned surfaces. `--from` copies a review
proposal's working documents and judgement on its original base; it does not adopt it.

The task contains the current contract, templates and packs, the mechanical summary of
recent compile events, the document tree, and component `evolve_evidence` blocks. Those
volatile inputs stay in the task; the two evolve contracts and the door's rules form a
byte-stable system message (I5). The Steward reads the evidence, submits the phase-1
judgement as `EvolveProposal` JSON, then restructures. Its required fields remain `packs`
and `rationale`. The optional `retire_packs`, `rename_packs`, and complete `path_templates`
list express changes to existing structure; `dropped_anchors` explicitly names losses.
Malformed JSON, an invalid model, unknown pack names and malformed templates are refused.
An empty pack list and a rationale, without structural changes, records a no-change round.

Move carries a claim and its citations verbatim, creating an empty destination when needed;
rename preserves document identity; retire removes a page only when its lost anchors were
named. Archive records and closed volumes retain their existing protection: their exact
base paths remain readable to the gate, and their content cannot change. Renaming or retiring
a page with closed volumes is refused. Every write
runs the evolve gate's predicates and rolls back the whole command on a new violation,
charging the compile door's shared budget transaction even on refusal. A family being
retired can remain temporarily while commands move its pages; `check` and `finish` require
the final template set. The default evolve budget is 120 calls; an explicit
`COMPILE_MAX_TOOL_CALLS` overrides it. One fresh repair budget follows a failed finish.

`contract edit` accepts non-blank text up to 100,000 characters, optionally with contract
frontmatter declaring `path_templates`. The framework assigns its version and retains it
in this user's proposed manifest. On adopt, that version becomes the tenant's registered
contract through the canonical manifest, including after a process restart; it never
changes another tenant's registry or edits the deployment's engine file. Contract and
schema changes apply to future compiles; the structural commands preserve existing claims.

`finish` runs the same `run_evolve_gate`, accounts for every anchor and citation, then uses
the same branch and review-record writer as the model path. Rename and retire explicitly
remove their old paths in that branch; adoption carries those deletions in the same atomic
commit as the merged files. `pkc evolve ls/show`, the console and the existing mechanical
three-way reconciliation read the ordinary record. **Adopt remains the Owner's decision**:
`pkc evolve adopt <id>` queues that reconciliation. No sibling of `workflows/compile.js`
is needed: the bilingual skill journey and the argparse-generated CLI reference teach this
door to both harnesses.

### 5.8 The profile — `pkc profile`

```
pkc profile show [--json]                        every field with its provenance; says when it is the placeholder
pkc profile set (--file <f>|-) | --field k=v…   --provenance inferred|owner (default: inferred inside a Steward session, owner otherwise)
pkc profile confirm --field k…                   flip fields to owner; --all
```

One write path (`persona_profile.save_owner_profile`): the engine's `persona/profile.yaml`
and the persisted `UserProfile` move together, and `provenance` is a map over every field the
Steward may set, not only the three locale keys. `render_system_contract` renders the
provenance word beside each inferred value (`display_name: 陈晚 (inferred)`), which is what
lets a model treat an inferred owner as a hypothesis. Confirmed values retain their previous
rendering, so an all-owner profile keeps the earlier system contract byte-for-byte.
`pkc draft open` prints one notice when the
profile is the placeholder or holds unconfirmed inferences; it refuses nothing.

An unknown Owner is `UserProfile.unstated()`: a blank name, blank personal facts and dates,
`source="unstated"`, and `placeholder` provenance for every settable field. Blank, `Someone`
and `Owner` are placeholder names; a declared industry alone still makes a profile, even
without a name. Engine declarations give each stated field `owner` provenance and each blank
field `placeholder`; legacy locale `profile` markers map to `owner`, while detected or
unstated locale values stay out of the personal profile. Steward writes carry `inferred`
until confirmed, including when only one field is set. Owner API/CLI edits keep `source="user"`.
No loader supplies a join date, active-since date or personal preference that nobody stated.
The personal edition persists its untouched engine template as unstated and derives a
settled profile from two facts: it is no longer a placeholder, and no field is `inferred`.

The skill's first-round rule is mechanism-backed on both ends: the placeholder is
detectable, and the provenance is rendered. What the Steward reads to infer is its own —
the harness's memory of the Owner, the material's first-person voice, the address terms the
`people` component already reports — and the skill says only that it does, and that the
Owner is asked afterwards, one field at a time, with what was inferred laid out.

### 5.9 The retrieval choice — `semantic_retrieval`

`PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL` (engine key `intake.semantic_retrieval`, `on` by
default). `off`: `build_embeddings` is never called and no embedding key is required; the
intake proposal forces `semantic_indexing: none` and the archetype picker offers only those;
the index job writes L1 and skips L2; the fast, rag, deep and briefing lanes and live context
run without the vector arms and without episode summaries (the lexical arm and the claim
face carry the answer; the response's stage timings show the arms as `skipped`, not as
failed); `rebuild_derived` skips L2. `pkc config set semantic_retrieval on|off` writes the
engine knob (blast radius `restart` + `derived_rebuild`). The startup reminder from
`embedding_key.py` becomes a question the Steward can answer: with no key and the choice
`on`, `pkc` says which of the two edits resolves it.

### 5.10 The home — `~/.pkc`

The personal edition: an application over the library, with one shared infrastructure per
machine, libraries as tenants on it, the skill installed into the harness rather than into a
project, and every choice and every init step recorded once under `~/.pkc` so no later
session asks again. Its own command is `pkchome`; `pkc` stays the library's and gains
nothing from it. It has its own page, [single-machine-edition.md](single-machine-edition.md);
the profile flow (§5.8) and the retrieval choice (§5.9) are the two cold-start questions it
asks.

### 5.11 The skill package — `pkc skill`

```
pkc skill install [--backend codex|claude-code|all] [--project <dir>]     the files into a project, plus the router block
pkc skill render --out <dir> [--backend …] [--language en|zh] [--force]   the same package into a directory; nothing installed, no instructions file
pkc skill verify [--backend …] [--project <dir> | --dir <dir>]            re-render and compare bytes; exit 4 listing what drifted
pkc skill show [--backend …] [--project <dir>]                            the hash, the contract and the file list
pkc skill probe [--backend …] [--deadline <s>]                            is the harness live? exit 4 when it is not
```

`render` is the install without the install, for a package somebody reads rather than one a
harness was opened onto: the personal edition renders each library's reference package under
`~/.pkc/libraries/<name>/skill/` with it
([single-machine-edition.md](single-machine-edition.md) §4.9). Same deployment resolution,
same rendering call, same `skill-version.json`, so the hash it prints is the hash `install`
would have stamped — which is why it is this command and not a second renderer. `verify
--dir` asks that directory the same freshness question, minus the router block there is no
instructions file to hold. What the package *contains* is §7.

### 5.12 Episodes — the index door

Episode judgement is the agent's step before compile. An index job still writes L1
unconditionally. When semantic retrieval is on and the source's IntakePlan requests L2
(`full` or `summary`), an agent compile executor enqueues one `episodes` job for that source;
the current index job already holds exactly one source. It never substitutes a mechanical
partition for the agent's judgement. A matching kept manifest is replayed, and an outstanding
episodes job is not duplicated by an index retry. With retrieval off, or the source's plan
set to `none`, there is no episodes job. The API executor's model and keyless fallback paths
retain their existing behavior. Compile reads L0 and never waits on episodes; the skill's
reading order does not add a queue dependency.

```
pkc index episodes open <job>
pkc index episodes status
pkc index episodes propose (--file <f> | -)
pkc index episodes finish
pkc index episodes abandon
```

`open` claims the source's job and persists a draft of kind `episodes` in the same
Postgres DraftStore as compile and evolve. It prints the structure map, every numbered
block with the contract's role/kind metadata when present, the episode rules, and the budget.
The rule text is byte-stable; source content and budget travel in the task. The shared
command transaction charges refusals, rolls back rejected proposals, and uses the compile
budget, exit codes and TTL. `status` is free; `abandon` releases the claim. A missing proposal
at finish receives one repair round, then aborts: silence never means an empty selection.

`propose` replaces the whole selection with an array of
`{"start": a, "end": b, "title": "…", "description": "…"}` objects. The chunker's gates
check real ordered endpoints, strictly increasing starts, at most three shared blocks between
neighbours, and no more episodes than blocks. **Gapless coverage is deliberately omitted.**
Every violation is named at the write, titles and descriptions must be non-blank and bounded,
and uncovered blocks are listed as `no episode`. `[]` is a valid, explicit judgement. The
agent grounds its wording in the supplied blocks; the mechanical guarantee is real source
coordinates and a derived representation, not a semantic truth test over generated prose.
Nothing here writes L0 or canonical.

`finish` writes the same `chunk_manifests` table and semantic replay key (tenant, source,
compile executor spec and content digest). Its v3 envelope explicitly records `producer:
agent`, `coverage: partial`, smart overlap, the executor and `Executor-Skill` hash, plus the
splitter settings used for this observation. The hash comes from the installed shim or
package; a finish without that identity is refused rather than inventing attribution.
Agent intervals always use this smart-overlap contract; the API's `semantic_overlap` switch
does not reinterpret them. Rebuild reads the record, including an empty array, and never
fills gaps, calls a model, or rewrites the record. Section refinement and long-episode
sub-splitting remain mechanical and cannot extend coverage into omitted blocks.

The embedding step produces the ordinary raw and episode vectors, replacing only this
tenant's L2 points for this source so old vectors cannot survive an omission. If embedding
or vector storage fails after the manifest was published, the kept judgement remains;
retrying finish (including after abandonment or TTL recovery) resumes that same record
instead of accepting a new proposal. With retrieval switched off during an open round,
finish retains its manifest without building vectors; a later rebuild can replay it.

Attended jobs wait for `open`; unattended jobs use the same launcher and draft lifecycle as
compile and evolve, with `steward.unattended.episodes_task`. The generated skill adds
“Episodes before compile”, and `references/cli.md` learns the verbs from the live parser.

## 6. The draft on disk

`PatchDraft` today is an in-memory object: base documents, working documents, read marks,
path templates, the overview budget. It gains `to_state()` / `from_state()` over a JSON
document that also carries what the runner holds beside it: the job id and user, the source
handle map (`sNN` ↔ real ids), the round (`first` / `repair`), calls spent and the round's
budget, whether the low-water notice has been given, and the rendered task's hash — so a
draft opened under one contract cannot be finished under another. It lives in Postgres, one
row per job (`compile_drafts(user_id, job_id, state, round, updated_at)`), beside the queue it
belongs to: the per-user lock, the TTL and the self-heal that govern jobs govern their drafts
in the same place, and a draft never touches `engine/` or canonical. Core defines the state
form; the service's Postgres adapter stores it.

**One draft, one executor.** The session inside `state` also records an opaque `executor`,
`opened_at`, and the worker posture at opening. This is distinct from the job's
`agent:<backend>` accounting label. CLI identity comes from `PKC_DRAFT_EXECUTOR` when set,
otherwise the installed skill hash plus the Steward session token the shim exports
(`PKC_STEWARD_SESSION`, using a harness thread id or the parent shell's pid and host);
a direct CLI invocation without a session falls back to `pid@host`. An unattended runner
mints `worker:<harness>:<launch id>` and exports that exact token to every child command,
including the repair round. Repeated `open` resumes only for that executor. Another executor
gets exit 2 naming the holder, opening time, idle seconds, worker posture and the recovery
command. Status, reads, writes, checks, finish and abandon enforce the same ownership.
Legacy drafts with no executor are held by `legacy:unknown`, never silently adopted.

`pkc draft abandon --take-over` (also on the evolve and episodes doors) explicitly discards
another executor's draft and releases its job. It is refused until the draft has been idle
for `max(60, COMPILE_DRAFT_TTL / 12)` seconds, unless the owning worker launch has gone.
The job's operational payload records the previous holder, who took over, when, and the
mechanical reason; the audit survives deletion of the ephemeral draft. A per-tenant PG
advisory lock serializes each entire command, including gate and commit, against takeover
and recovery. A command already executing cannot lose ownership midway through its write.

Two commands hold the lifecycle. `open` claims the job in the queue exactly as the worker
does (`FOR UPDATE SKIP LOCKED`, one in-flight job per user), so the per-user single writer
holds whichever body the Steward has; a job held by a draft is invisible to the worker.
`finish` replays what the end of `run_compile` does today: the overview floor, the gate,
`commit_patch` with the skill trailer, `derive_events`, the brief; on violations it writes
the repair budget into the draft and returns them. An abandoned or expired draft — the queue's
self-heal treats a draft older than `COMPILE_DRAFT_TTL` as orphaned — releases the job.
A worker launch holds a separate PG advisory lease for its entire run; process death drops
that lease. Startup recovery preserves a live launch until the full TTL expires, even when
it has been idle longer than the takeover grace, and requeues a dead launch immediately.
With TTL zero, idle-draft protection is disabled but a live launch's lease still protects it.
The claim query refuses any tenant with an open draft, including one whose queue row was
mistakenly requeued. Completed jobs cannot be claimed or reopened through `claim=False`;
a late completion preserves the existing outcome, and a late worker failure can end only
its own claim. The runner pins the job id as well as the executor, so a return after finish
cannot act on the tenant's next draft.
The worker's failure tail removes only its own terminal draft under that same lock; startup
recovery also removes terminal drafts left by earlier crashes, without reopening their jobs.

**Byte equality is the acceptance test.** The same sequence of tool calls, run once through
the langchain loop with a scripted model and once through `pkc draft` commands, produces the
same committed files, the same events and the same violations. The test exists before the
CLI has a user.

A second difference, and an improvement the CLI makes first: the langchain loop gates only
at `finish`, so a dangling claim can sit in the draft for a whole round; the CLI gates every
write on the page it touched (ruling 10). The final gate is identical, so byte equality of the
committed result holds; what differs is how early a wrong write is named, and the langchain
loop can adopt the same per-call check later without changing its result.

One stated difference. The langchain loop delivers the low-water notice as a human message
in the middle of a round; a CLI cannot speak between the agent's turns. The notice is
instead appended to the result of the write that crosses the mark and repeated in `status`.
Both renderings come from the same catalog key; the two executors are pinned separately.

## 7. The skill package

Generated by `scaffold/init.py` and regenerated on every engine apply, from the same inputs
that render the compile system message: the composed contract, the prompt language and
overlays, the enabled components. Blast radius `future_compiles`. Its layout follows the
harness's own conventions, which are data on the backend manifest (§8):

```
.agents/skills/pkc-steward/            Codex           .claude/skills/pkc-steward/   Claude Code
  SKILL.md                             the journey: who you are, reading, the round, the door, the postures, owner speech, the archive
  references/consume.md                the library's design, reading primitives, resolved domain families and consultation procedure
  references/contract.md               the composed contract, verbatim
  references/compile-instructions.md   the rendered compile system message, verbatim
  references/cli.md                    every command, its description, what it refuses, its exit codes
  references/gate.md                   what `finish` rejects, as facts
  scripts/pkc                          the shim
  workflows/compile.js                 Claude Code only: read → plan → write → finish as an order of work
AGENTS.md / CLAUDE.md                  one `pkc:start … pkc:end` block: this is a library, you are its Steward, the skill is at <path>
```

`references/consume.md` is rendered from `steward.consume.*` in the prompt catalog, with
families and `owner_voice` markings enumerated from the resolved contract's path templates.
It teaches three moments explicitly: session start uses the complete `pkc outline`; answering
uses outline to find pages, `canonical read` to read them, `recall --evidence` for fast-lane
evidence, `search` for names and phrases, and `source fetch` for ground truth. The budgeted
`glance` is only for an outline too long to scan. After `draft finish`, run
`outline --family <template>` for each family written to see the new pages in place. These
moments also appear in the SKILL.md journey, including the compile round's before/after steps.
Both command descriptions come from the bilingual catalog and appear in CLI help and
`references/cli.md`, so completeness versus budget is visible at the command itself.
It shares the package hash and introduces no system-message content (I5). Reading follows
citations and links through `pkc` primitives; `recall --evidence` assembles context without
constructing a chat model, and `consult answer` closes the handoff into a consultation.
With semantic retrieval off, no embeddings are built either. Outline, glance and evidence read the
composed contract without deriving packs or writing a manifest.

What the SKILL.md may and may not contain follows one test, the same one the compile-contract
guide gives contract authors: *if breaking a rule gets the write refused, it is mechanism and
is described as a fact about the door; if only a reader can tell right from wrong, it is
judgement and belongs to the contract.* The skill therefore holds the procedure — open, read
the task, read the pages you will touch, write, `status` when unsure, `finish`, repair once —
the description of each refusal, the two postures, and the sentence about what the Steward
cannot do (delete, edit without a job). It holds no "remember to cite". The archive's own section (§5.5) is the same test applied
once more: the sequence and the two refusals are the door's, and "move nothing under
`archive/`" is one more line in what the Steward cannot do — the gate refuses it as
`archived_path`. A test greps the
generated SKILL.md for the catalog's refusal texts and asserts each is described, and for the
imperative forms the project bans ("always", "never forget") and asserts none appear outside
a quoted refusal.

The `pkc:start` block is a router, not a rulebook: what this directory is, where the skill
is, and the one rule the harness needs about reading skill files from the project rather than
a global cache. It is spliced between markers and never touches text outside them; a
re-generation replaces the block and leaves the Owner's own `AGENTS.md` prose alone.

The package's sha256 is stamped into every canonical commit the agent executor produces,
as `Executor-Skill:` beside the overlay hash. A freshness test renders the package from the
catalog and asserts it equals the one installed, so a skill that drifted from its catalog
fails the suite instead of compiling under different words.

Versioning: `skill-version.json` beside the install records the framework version, the
package hash, the backend and the language pack it was rendered under; `pkc skill install`
regenerates; a session already running does not see a rewritten skill or workflow until it
restarts, which the skill says.

**What was built differs from the sketch above in six places**, each because the code said so:

- The workflow installs to the manifest's `workflows_dir` (`.claude/workflows/compile.js`),
  not under the skill directory as the tree draws it: that is where the harness looks for it.
  The package still renders it under `workflows/`, and the installer maps the one onto the
  other, so `workflows_dir is None` stays the whole of "is a workflow installable".
- `skill-version.json` sits BESIDE the skill directory (`<skills dir>/skill-version.json`)
  rather than inside it, because the install purges that directory wholesale and would
  otherwise take the record of itself with it.
- A workflow script has no shell and no filesystem. The Open and Finish "script steps" are
  therefore single-purpose agents whose entire prompt is one command to run and its output to
  return. The phases — and so the order of work — are enforced exactly as designed; what a
  workflow cannot add is determinism *inside* a step.
- The scaffold emits `bin/pkc` as a two-line pointer at whichever installed skill's
  `scripts/pkc` exists, rather than as a second shim. One shim is rendered by the framework;
  the short name a person types points at it.
- The package is rendered per DEPLOYMENT, not per tenant: `pkc skill` reads the engine
  directory and never a database, which is what lets `init.py` install into a project that has
  never been started. The composed contract is read back from the tenant's canonical
  repository when one exists on disk, and falls back to the deployment's base when it does
  not — the same resolution `path_templates_for` performs, one level up.
- The framework registers no contract of its own, so `pkc skill install` needed a
  framework-side loader for the engine's `compile/contract.md` (`engine/contract.py`). It is a
  fallback: a process that already registered a contract keeps it.

## 8. Backends

One manifest per harness, data first:

| | codex | claude-code |
|---|---|---|
| binary | `codex` | `claude` |
| skills dir / instructions file | `.agents/skills` / `AGENTS.md` | `.claude/skills` / `CLAUDE.md` |
| workflows dir | — | `.claude/workflows` |
| probe | `codex login status` exits 0 | `claude -p ping --output-format text` answers within the deadline |
| headless launch | `codex exec --skip-git-repo-check --color never --json --sandbox workspace-write -c sandbox_workspace_write.network_access=true [-m <model>] --output-last-message <f> -` | `claude -p --output-format json --tools "Bash,Read" --permission-mode bypassPermissions [--model <m>] --add-dir <project> --system-prompt-file <f>` |
| system text | prepended to stdin (no system channel) | `--system-prompt-file`, replacing the harness's own preamble |
| usage | token counts from `--json` events; no cost | `result.usage` and `total_cost_usd` |
| session | new thread per round; the repair round is `codex exec resume --last` under a per-job `CODEX_HOME`, else a fresh process fed the violations | `--resume <session>` (from `result.session_id`) under a per-job `CLAUDE_CONFIG_DIR`, deleted with the draft |
| what the OWNER types, interactive | `codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true` | `claude` — nothing special; allow Bash when it asks |
| what the OWNER types, one instruction | `codex exec --skip-git-repo-check --sandbox workspace-write -c sandbox_workspace_write.network_access=true "…"` | `claude -p --permission-mode bypassPermissions "…"` |

The last two rows are on the manifest because the end-to-end acceptance run found them to be
the single biggest gap in the feature: **a harness started in its default posture cannot open
a socket to the project's Postgres**, so `pkc` fails before it reaches the library and the
headline experience of §3 — the Owner opening Codex in the project directory and typing
*compile what's pending* — does not work out of the box. Codex sandboxes both the filesystem
and the network by default; Claude Code sandboxes neither and asks instead, which is why its
interactive column is empty and only its one-shot `-p` form needs a permission mode (there is
nobody there to answer a prompt). The flags are stated in exactly three places, all rendered
from these two fields: the `pkc:start` router block, `SKILL.md`'s posture section, and the
generated project README — and the generator prints them at the end of generation. Nothing
retypes them.

The **unattended launcher** (topology 2.8) owns what a harness will not: a wall-clock timeout
per round (`COMPILE_CALL_TIMEOUT` reused), backoff with jitter on the exit codes and messages
that mean rate limit, a fresh `mkdtemp` working directory holding nothing but the shim and the
project's `.env` path, the process spawned as its own group and reaped TERM→KILL on the
worker's exit, and usage read from the harness's JSON result into the job record. The prompt
travels on stdin from a file, never in argv. A probe failure at startup is fatal and names the
missing thing; an unknown protocol surface degrades and is logged; a version number is never
compared.

In the **interactive posture** none of this runs: the Owner's harness is already up, and the
skill is the launcher. `PNEUMA_KNOWLEDGE_AGENT_UNATTENDED` is which posture a worker takes,
and it defaults to unattended because a worker is by definition unattended.

Four things the build settled that the table above did not say, and each of them is data on
the manifest rather than a branch anywhere:

- **the harness gets a shell, not the open world.** The single-shot leaf this launcher is
  modelled on runs Claude with `--tools ""`; a compile round cannot, because running `pkc` IS
  the round. So: `--tools "Bash,Read"` and `--permission-mode bypassPermissions` on Claude
  (unattended in an empty directory, a permission prompt has nobody to answer it), and
  `--sandbox workspace-write` with network access on Codex — it may execute, and the only
  place it may write is the empty working directory the launcher made.
- **a hermetic config home is about sessions, not credentials.** Moving `CODEX_HOME` /
  `CLAUDE_CONFIG_DIR` moves the harness's whole world, and an empty one is a harness that is
  suddenly logged out. The manifest names the files that must be there (`auth.json`,
  `config.toml`; `.credentials.json`, `settings.json`) and the launcher LINKS them from the
  Owner's real home: no secret is copied into a temporary directory, a token the round
  refreshes is refreshed where the Owner's own sessions will find it, and everything else —
  sessions, logs, caches — lands in the per-job directory and dies with the job.
- **`CLAUDECODE` is unset in the child.** A Claude Code session that finds it set believes it
  is nested and short-circuits, so a worker started from inside one would launch rounds that
  do nothing.
- **two providers, two token vocabularies.** Anthropic reports cache reads and writes BESIDE
  `input_tokens`, so they are added; OpenAI reports `cached_input_tokens` as the cached
  PORTION of `input_tokens` and `reasoning_output_tokens` as the reasoning portion of the
  output, so adding either would count it twice. Codex states its counts on
  `turn.completed`; where a version states a cumulative `total_token_usage` instead, the last
  one is the total. Nothing found means `usage is None` — never a zero.

What the harness's own tools can reach is stated rather than assumed. Unattended, the
working directory is empty and the harness is held to Bash and Read (Claude) or to a sandbox
whose only writable place is that empty directory (Codex), which leaves the `pkc` shim as the
only hand. Interactive, the agent sits in the project and could edit files
under `data/`; the door there is two mechanical refusals rather than a convention. An
UNCOMMITTED edit is refused by the canonical adapter before any write: every mutating method
records the footprint it is about to touch, and a dirty tree is recovered only when its
claimant is provably dead and every dirty path lies inside what that claim recorded —
anything else is `canonical_dirty`, naming the paths, having written nothing
([archive.md](archive.md) §3.1). A COMMITTED one is caught at `pkc draft open`, which refuses
a repository whose HEAD lacks the framework's trailer and names the commit. So a write that
went around the gate is stopped before the next round builds on it, rather than compounded.

## 9. Where it plugs in

- **`agent:<backend>` as a model spec.** `resolve_model_name` returns it unchanged;
  `build_chat_model_for` refuses to build a chat model from it (an executor is not a model),
  and the worker asks `executor_for(settings, role)` for compile and evolve. Other roles
  naming `agent:` explicitly fail at startup. Episodes share compile's executor and their
  own draft door; challenge is skipped under it, and the agent supplies its own brief.
- **`RoundRunner` in core.** `run_compile` keeps everything around the loop — aliasing,
  `prepare`, the draft, the gate, the commit — and delegates the loop to a protocol with one
  method: run a round under a budget over a draft's tool face, return calls spent, whether
  it was cut off, usage. `LangchainRoundRunner` is today's `tool_loop`, moved. The CLI
  executor does not implement it in-process: the worker's `AgentRoundRunner` writes the draft
  to disk, spawns the harness, waits, and reads the draft back. Core knows the protocol and
  the draft's state form; the subprocess lives in service.
- **Where the unattended round finishes, and why it is not `run_compile`.** `RoundRunner`
  takes a message list and a tool face and returns what the round spent — a shape that means
  something when the loop and the draft live inside one function call, and means nothing when
  the draft lives in a `DraftStore` and the calls are typed by another process. Driving
  `run_compile` from the worker would mean building a message list nobody reads and a tool
  face nobody calls, so that its `finalize_compile` could run a second finish over a draft the
  harness already finished. That is a fake round and a second code path that ends a draft. So
  the unattended worker bypasses `run_compile`: it opens the draft through the CLI's own
  `open_round`, launches, and then reads the store — draft gone means the harness ran `pkc
  draft finish` and the job is complete only when the job row confirms that outcome;
  a released or replaced draft ends this launch's authority. Its own draft still open means
  it stopped, and the worker
  runs the same `cmd_finish` so the gate still judges; draft open in `repair` (or refused by
  the overview floor) means one more launch carrying what the gate said, then `cmd_finish`
  again, and a second failure aborts exactly as today. `cmd_finish` is the one function that
  ends a draft, whoever calls it. Ownership and terminal-state checks prevent a late runner
  from reopening a completed job or finishing a replacement executor's draft.
- **`open` audits the library HEAD before it claims.** Every canonical write channel this
  framework has stamps a `Skill-Version` trailer, so a HEAD without one is a commit nothing
  here made: `pkc draft open` refuses with exit 2 naming the commit and its subject rather
  than building claims on a change nothing can attribute. A repository with no commits opens
  normally — the git adapter runs `git init` and makes no bootstrap commit of its own, so
  "no commits" is the only exempt state there is.
- **The API.** Gains the Steward WebSocket and the bridge (§5.6). The API stays stateless
  about the library; what it holds is a handle to a harness process per Owner session, as the
  live-context socket already holds a run — and the harness's session, not the API, is where
  the conversation lives.
- **The worker.** Under an agent executor compile, evolve and episodes jobs are claimed and handed to
  the same launcher (unattended), or left queued for their respective draft `open` commands
  (interactive) — the
  process view says which is expected. `PNEUMA_KNOWLEDGE_AGENT_UNATTENDED` is resolved afresh
  at each worker start and logged. An open Steward draft is skipped before claiming, with
  one log message per holder; the SQL claim enforces the same exclusion. A repeated `open`
  resumes for the same executor; another executor is refused and shown the owning worker's
  recorded posture. Index writes L1 and queues episode judgement (§5.12);
  projection and rebuild jobs remain mechanical.
- **`engine.yaml` and the console.** `models.compile: agent:codex` is a strategy value like
  any other; the engine schema gains the `agent:` form, the console shows the probe's result
  beside it, and the process view gains the waiting-for-Steward state.
- **Single-shot roles (v2).** A `LeafChatModel` over the same launcher makes `agent:` usable
  for fast and live: system text to the harness's system channel, messages
  on stdin, structured output as a schema in the prompt validated by the pydantic model with
  one re-ask. Not in v1; the shape is stated so the manifest and launcher are built once.

## 10. Invariants and disciplines

- **I1.** Every command derives its user from the project or the one `--user` flag; the draft
  file is keyed by job and job by user; `open` claims through the same per-user lock the
  worker uses.
- **I2 / I7.** The draft is ephemeral, neither authority nor record; the skill package is
  derived from the catalog and rebuilt on apply; components are untouched.
- **I3.** Unchanged in what it guarantees: no plan or strategy decides reachability. The
  archive is the Owner's decision, applied as a default and reversed by one flag; `fetch` by
  locator, `source show`, `canonical read` and `canonical history` never filter.
- **I4.** The CLI speaks `source_id ¶a-b` and `c:xxxx` and nothing else; `recall --evidence`
  hands out the same query-local handles the lane does.
- **I5.** The system text the agent receives is the byte-stable contract; on Claude Code it
  replaces the harness preamble, on Codex it heads the stdin. Task content stays in the task.
  The interactive posture reads the same bytes from `open`'s output.
- **I6.** Unchanged; the eval package does not learn about executors.
- **Mechanism over persuasion.** Every "must" in the skill is a refusal in the CLI; the test in
  §7 holds the two together.
- **Cost and quality apart.** An agent-compiled library is compared to an API-compiled one
  only on the same corpus, same contract, same harness; this page claims no quality
  difference.

## 11. Testing and order of work

Keyless by default, as the rest of the suite:

- **Byte equality** (§6) between the langchain loop and `pkc draft` over the same scripted
  tool sequence — the first test written.
- **Refusal parity**: every `AnchorToolError` the tools raise is reproduced through the CLI
  with the same text and exit code.
- **Fake harnesses**: a `codex` and a `claude` on `PATH` that replay a recorded sequence of
  `pkc draft` commands, so the unattended launcher, the timeout, the backoff and the usage
  capture are exercised without a subscription — the `scripted:` idea one process out.
- **Skill freshness and content**: the generated package equals a fresh rendering; refusal
  texts described; banned imperatives absent.
- **Live suite**, gated by `PNEUMA_KNOWLEDGE_TEST_LIVE_AGENT=codex`, outside the default
  testpaths: one real compile of the scaffold's demo material.

Order, Codex first throughout:

1. `PatchDraft` state form; `pkc draft` commands; `open`/`finish` lifecycle; byte equality.
2. `RoundRunner` extraction; `agent:` model spec; worker behaviour; process-view state.
3. Per-command post-check, `pkc draft check`, `pkc library check`; the read commands,
   `owner say`, `pkc ingest`. (The archive face that once rode here moved to step 5c, once
   the mechanism itself had landed on `main`.)
4. Skill package generator; scaffold integration; `pkc:start` block; hash in trailer;
   freshness test.
5. Codex manifest, probe, unattended launcher, fake harness; then the Claude Code manifest
   and the workflow. **Done.** Both manifests are filled in; `pkc skill probe` reports
   liveness; the launcher owns the timeout, the backoff, the reaping and the usage; the agent
   round runner and the worker's unattended posture end every round through one `cmd_finish`;
   `open` audits the HEAD trailer. Keyless coverage runs against fake `codex` / `claude`
   binaries on `PATH`; one integration test drives a real subprocess round against Postgres;
   `PNEUMA_KNOWLEDGE_TEST_LIVE_AGENT=codex uv run pytest tests/live` compiles a tiny fixture
   through the real CLI, outside the default testpaths.
5b. The console's Steward view: Codex bridge first, then Claude Code; the verbatim check on
   `owner say`; resume on reconnect. **Done.** One `StewardSession` per Owner in the API
   process, spawned in `PROJECT_DIR` with the launcher's own hermetic config home and
   `CLAUDECODE` unset; two adapters normalizing the two wires into one nine-event vocabulary;
   `WS /v1/users/{id}/steward` with a `snapshot` on attach and a `GET` for the view's
   empty/disabled state; the Owner-lens view rendering each step as the agent's own command
   with its result folded under it; the five library-changing commands moving the history,
   process and sources views without a reload; and `pkc owner say` refusing a text that is not
   a verbatim substring of an Owner turn. Keyless throughout: the fake `codex` / `claude` from
   step 5 gained an interactive mode and speak the real protocols on `PATH`.
5c. The archive at this door (§5.5). **Done.** `pkc archive propose / confirm / ls / show /
   drop / inventory` over `archive_service`'s own functions; the two Steward-posture rules —
   the Owner's words required at propose and confirm, and seeds confirmed by default with the
   computed cascade listed and left — `--include-archived` on `pkc glance`, `pkc canonical
   ls`, `pkc source ls`, `pkc search` and both faces of `pkc recall`, labelled as the wire
   labels it and carried on the `--evidence` handoff into the consultation; and the skill's
   own section, rendered from the catalog in both languages like every other one.
6. Real runs on Codex over the demo corpus; then the OPC corpus as a same-harness comparison
   against the API executor, recorded under `examples/opc/build-record/`.
7. Documentation: this page kept current, [configuration](../reference/configuration.md),
   [architecture](../architecture.md) §6/§10 one paragraph each, the scaffold guide.

## 12. Traceability

| Story | Mechanism |
|---|---|
| 2.1–2.3 | `pkc owner say` → owner-dialogue source → `pkc draft` under the gate (§5.3, §5.2) |
| 2.4 | no delete command; refusal text in the skill's "what you cannot do" (§5.2, §7) |
| 2.5, 2.6 | evolve door (§5.7), v1 |
| 2.5f–2.5h | the Steward view: bridge over the harness session, steps as the agent's own commands, verbatim check on `owner say`, resume on reconnect (§5.6) |
| 2.5b, 2.5b′ | the upstream archive (a move + a record, `include_archived` through every lane) reached through `pkc archive propose / confirm / ls / show / drop / inventory`, plus `--include-archived` on the read commands; the two door rules: the Owner's words required, seeds confirmed by default (§5.5) |
| 2.5c–2.5e | `pkc ingest`, the `steward/` realm, content-identity idempotency, secrets outside task files (§5.4) |
| 2.18b | per-command post-check with the gate's predicates, rollback on failure; `pkc draft check`, `pkc library check` (§5.1, §5.2) |
| 2.7 | `init.py` executor question beside the key questions, probe, skill install (§3, §7, §8) |
| 2.8, 2.22 | unattended launcher, worker under `agent:` (§8, §9) |
| 2.9 | interactive posture: same commands, same draft (§5.2, §6) |
| 2.10, 2.11 | `agent:` model spec, blast radius, executor on the job record (§9, §4.1) |
| 2.12 | `pkc recall --evidence`, consultation recorded at hand-over (§5.1) |
| 2.13, 2.14 | `pkc brief`, `pkc source fetch` (§5.1) |
| 2.15 | usage from the harness JSON unattended; absent interactively (§8) |
| 2.16 | existing snapshot revert, reached by CLI (§5.1) |
| 2.17–2.20 | draft lifecycle, refusals, budget, finish (§5.2, §6) |
| 2.21 | read commands (§5.1) |
| 2.24 | process view's waiting state (§9) |
| 2.25 | `rebuild_derived` unchanged |
| 2.26, 2.30 | `pkc profile set/confirm` with provenance, rendered into the compile system message; substantive facts only via `owner say` (§5.8) |
| 2.27 | `semantic_retrieval` engine knob, the off path through intake, index and every lane, `pkc config set` (§5.9) |
| 2.28, 2.29 | `~/.pkc` registry with init state, `pkc home status` probing, the global `pkc-home` skill (§5.10) |

## 13. Boundaries and what comes after

- **Single-shot roles on an agent** (§9) remain deferred to v2. Structural evolution
  already runs through the evolve draft door (§5.7).
- **Standing tasks are the Steward's, not the framework's.** The framework offers `pkc
  ingest` and the five contracts; it does not schedule, fetch, transform, or know a task
  exists. A task the Owner wants shared across deployments is a skill to distribute, not a
  framework feature to add.
- **The home holds state, never knowledge.** `~/.pkc` names projects and remembers
  choices and credentials; it holds no source, no claim, no record. A second machine starts
  with an empty home and a project directory that is complete without one.
- **Retiring is not removing.** The archive takes pages and sources out of what a lane
  reads by default and leaves a record standing where the page was; nothing takes a claim out
  of the ledger or a byte out of L0, and source deletion remains undesigned. Changing the
  mechanism itself — what the default statement says, how a dirty tree is recovered — belongs
  to [archive.md](archive.md), not to this door.
- **Steward memory** stays where the frame left it: the CLI exposes the kept records; nothing
  here gives the agent a memory of its own beyond the harness's session.
- **A local embedding adapter** would make a keyless deployment whole at L2; it is a separate
  feature.
- **Kimi** waits for a headless mode that carries a structured flow and reports tokens.
- **Source deletion** (a privacy request that removes L0 and everything citing it) is not
  designed here; the Steward cannot perform it.
- **Subscription terms and limits** are the provider's. The launcher backs off and reports;
  it does not work around them.
