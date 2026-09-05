# OPC — a complete, agent-built knowledge base

**English** | [简体中文](README.zh-CN.md)

This directory is exactly what the scaffold flow produces: a knowledge-base project for one synthetic owner — 林舟 (Lin Zhou), an indie developer building a change-evidence product called Seamlog — compiled into 28 canonical documents and 1,188 cited claims over 191 sources. The library ships with the project; it opens in a browser in about a minute, without an API key.

## Where this came from

The contract that governs this library was written by an **autonomous agent** (Claude Opus 5 running in Claude Code) that started from a pristine copy of [`scaffold/`](../../scaffold/), followed [`AGENT-GUIDE.md`](../../scaffold/AGENT-GUIDE.md), and received exactly two inputs: the material in `my-data/` and a three-sentence owner self-introduction. It read all 190 files, derived [`engine/compile/contract.md`](engine/compile/contract.md) from what it read, compiled, judged the result against the [acceptance loop](../../docs/guides/compile-contract.md#8-the-acceptance-loop), and spent its one allowed revision when the first build violated a rule the material itself states.

The contract has since been extended — not rewritten — where new mechanisms needed judgement: what the owner's own words are worth, what each family's overview head should say, and what counts as a name for a person. [`build-record/`](build-record/) holds the build: the task book, the build log, the cost accounting, and the use-side session that produced the records a visitor leaves behind.

Treat this build as a **reference line, not a ceiling**: it is what one agent generation produced on one corpus. Point a stronger agent at the same data and the same guide, and the library may well come out better — the contract judgement is where agents differ.

## Try it

**1. Browse — no API key**

```bash
cp .env.example .env
./app.py up && ./app.py restore
docker compose --profile console up -d --build   # first image build takes a few minutes
```

Open <http://127.0.0.1:24173>. Everything is drillable: 191 sources verbatim, the compile history, every claim's citation back to the exact source passage, and the engine that produced all of it.

**2. Ask — needs a key**

An OpenRouter key in `.env` (`OPENROUTER_API_KEY`) turns on the lanes that call a model, from the CLI or from the browser:

```bash
./app.py ask '第一条证据链现在卡在什么条件上？' --sources
docker compose --profile console up -d api            # the browser's answering lanes
```

**3. Recompile with your own parameters — needs a key, costs real money**

Editing `engine/` (the contract, the models, the components) and rebuilding from the same material is the whole point of shipping the engine beside the library. What the reference build spent is accounted in [`build-record/`](build-record/):

```bash
./app.py down --volumes && rm -rf data/
./app.py up && ./app.py init
./app.py ingest my-data && ./app.py compile
```

`./demo.sh` wraps all three stages in an interactive menu.

## What this example now shows

The library is only half of it. The other half is what happens above the library — who is acting on it, what that act leaves behind, and what it cost.

**The lens is an identity, not a per-question setting.** One switch at the foot of the contents rail — Owner / Visitor / Silent visitor — decides both what the console shows and what class its questions carry. Owner is the cockpit: every view. Visitor and Silent visitor are the reading room: the answering surface and read-only browsing, nothing else. A deep link into a cockpit view under a visitor lens lands back in the reading room.

**Asking is recorded by class, and the ledger fills as it happens.** Owner and Visitor both ask as `business` — a question asked here is the library being used, and a use nobody counted leaves the library reporting itself unread. Silent visitor asks as `silent` and says so on the badge and on the page. The consultations view (§08) lists what was asked, what evidence travelled, what came back empty, and what each answer spent. `build-record/use-side/session.json` is the run that first filled it here: six business questions, one audit, three silent — and the silent three are absent from the ledger, which is what silent means.

**A page says when it was last read.** Every document carries an access card: last access, hits in the last seven and thirty days, and a heat that fades on a fourteen-day half-life. No score is stored — heat is computed when the ledger is read, so changing the half-life rewrites nothing. Above the consultations list, the usage panel gives the same ledger in the aggregate: the hottest pages, the questions that came back empty, and the window's spend.

**The owner corrects the library by speaking to it.** `engine/compile/contract.md` §3 says what an owner statement is worth, and the console's owner-statement form sends one as an ordinary source (`owner-dialogue/v1`) — cited like an email, compiled like anything else. In this library 林舟 reports that a balance the ledger recorded as outstanding has since been paid; the compile supersedes the stale claim citing his statement, and the superseded claim stays byte-for-byte where it was. The history view marks it as a supersession; the page shows both, in order.

**Live Context listens to a conversation instead of being asked.** The Live Context view takes a transcript turn by turn and, when the conversation gives it something to work with, offers a card from the library with its citations. Its per-tick telemetry says what the tick spent.

**Where the money went.** `engine/engine.yaml` declares what this deployment pays for its four models — that declaration is the only place a price enters, and an undeclared model is reported in tokens with no figure beside it rather than a zero. Compile is the big spender by an order of magnitude, and every compile job on the process view carries its own tokens and cost; the consultations view carries the answering side. The Live Context tick shows tokens and no money on purpose: its two calls run on two models this engine prices differently, and there is no per-role split inside one tick's usage, so a figure there would be invented money wearing a derived label.

**What answering costs here, and why.** This example answers with `evidence_strategy: select`. On a corpus this small retrieval scores are nearly flat, so "the top six windows" is very nearly an arbitrary six and one selection call earns its place; it is paid for with a second serial model call per question, and the deep lane costs more again. What each lane actually spent here is in `build-record/use-side/session.json`, beside the run that measured it. Change the strategy in `engine/recall/recall.yaml`, or for one question with `./app.py ask '…' --evidence-strategy ranked`.

## The corpus

`my-data/` is 84 days of one person's working life, fully synthetic (no real people, brands or credentials): 18 meetings and 48 IM conversations as transcripts, 81 notes and 43 mail threads as documents. Its defining trait — and the reason it makes a good test of this framework — is that half of its information is **negative facts**: what was not approved, not signed, not confirmed, not found. A compiler that flattens "proposed" into "decided" turns this corpus into fiction; the shipped contract exists to prevent exactly that.

## Regression eval

`eval/opc-truth.json` is a frozen truth set over this corpus, and `eval/run_eval.py` scores a built library against it. It exists because "the library got better" is not a claim anyone can check from a diff: the only way a later contract or framework change can be said to have improved this build is the same questions on the same material, compared to a committed baseline.

**What it covers.** 83 questions. Eight positive axes — current state, history, chain integrity, closed sets, definitions, calendar, aggregates, and multi-hop joins — plus a negative suite of 22, in three shapes: a detail the corpus genuinely never records, a subject that does not exist (near-misses of real names: 云岭 for 云麓, 陈昉 for 陈放), and a question with a false premise built in. Every question carries a difficulty tier, L1 (a fact stated in one place) through L5 (a chain walked end to end). Beside the questions, one structure probe. The corpus forbids merging the two evidence chains' STATUS into a single pass mark; this example's own compile contract goes further and gives each chain its own page (`chains/{slug}.md` … 「各自一页，永不合并」), so the probe checks the build against the contract: the document carrying most of one chain must not be the document carrying most of the other.

**How an answer is graded.** A positive question's expected answer is a list of facets — one proposition each, tagged `core` or `detail`. The case is correct when every core facet is stated, and the details are counted on their own line, so an answer that gave what was asked is not marked wrong for leaving out what was not. An LLM judge reports each facet as `stated`, `omitted` or `contradicted`, which keeps a terse answer and a false one apart, and is asked for entailment rather than surface, so a paraphrase states the fact. A facet may carry an `examples` list beside its proposition, and the judge is told what such a list is — illustrations of what would satisfy the fact, never a checklist.

**How a refusal is graded.** The negative suite's fabrication auditor is shown the L0 text behind the answer's own citations, so a cited detail is not read as an invention, and it is told that the absence statement it is handed is true: a rejection can only be made by asserting the negative, so an answer that states the absence, or the corpus fact that contradicts a false premise, is correcting the question rather than inventing anything. A false-premise question additionally carries `premise_accepted`, because refusing a premise and inventing a value are different failures. On a nonexistent-subject question the line is drawn explicitly: handing over a value for the invented subject without naming the real subject it belongs to has answered inside the invented one, which is fabrication however carefully it avoids saying the subject exists — while correcting the question to the real subject, or refusing, is not.

**The judge is calibrated before it grades.** `eval/judge-calibration.json` is a suite of 112 synthetic items in a domain this corpus knows nothing about, each varying the one thing a real answer varies — phrasing: 两万一千 against 21000, 六周 against 42 天, a hedge that still commits against alternatives that do not, an old state told as history against the same state told as now. `--mode judge` runs it through the same judging code the scoring uses and reports agreement per variant; `--mode full` runs it first and refuses to score when a blocking variant disagrees, because a ruler that fails its own calibration cannot produce a comparable line.

**The truth basis is this example's own inputs**: the 190 files in `my-data/` plus the owner statement `build-record/exercise.py` sends — the 191st source, part of what a developer restores, and the one that makes 尾款 a supersession rather than an open question. No canonical document was read while authoring, so the set cannot reward this build's phrasing, and each of the 501 authored quotes is resolved against ingested L0 before anything is scored — a quote that does not bind stops the run. Before v6 the set was audited a question at a time against those same inputs — one read-only process per case, inputs only, never the built library (`eval/audit_truth.py`) — and the 84 verdicts are kept beside the line in [`build-record/eval/2026-09-03-truth-audit/`](build-record/eval/2026-09-03-truth-audit/), with the maintainer's triage of them recorded in the truth set itself.

**The command.** The stack must be up and restored (`./app.py up && ./app.py restore`).

```bash
# keyless: groups A-E over the compile trajectory, plus the structure probes
uv run python eval/run_eval.py --mode mechanical --out var/eval

# with the key: adds the 83 answered questions, their facet judging, and the negative suite
uv run python eval/run_eval.py --mode full --out var/eval
```

It takes `--api`, `--user` and `--canonical`, so it scores **any** build of this example, not only the shipped one. Questions are asked as a silent visitor: measuring a library is not using it, and a silent question leaves no consultation row, so running the suite never rewrites the attention ledger. Most are asked on the fast lane; aggregates, joins, and the questions whose truth the contract leaves in the raw material are asked on both lanes and reported per lane, never averaged. The asks and judge calls are latency rather than compute, so they go out under a bounded concurrency — `--concurrency N`, default 32, `1` for serial — and the rows are reassembled in truth-set order afterwards, so the bound moves the wall clock and nothing in the score.

**The discipline.** The reference line lives in [`build-record/eval/`](build-record/eval/), recorded as it came, with each earlier line kept beside the current one under its own dated folder; what that line does and does not answer is stated there. A quality claim is the comparison, not the number: run the same command against your build, and diff it against that baseline (AGENTS.md — cost and quality are measured separately, and a quality claim needs a same-harness baseline). The scorecard has no overall score and no pass/fail on purpose, and the baseline is not a target.

## Reproduce it with your own agent

The whole point of this example is that you can. Give a coding agent the scaffold, the two guides ([contract](../../docs/guides/compile-contract.md), [AGENT-GUIDE](../../scaffold/AGENT-GUIDE.md)) and `my-data/`, and let it walk the same road — `build-record/TASKBOOK.md` is the exact instruction that started the reference build. Expect a library of a similar shape, not an identical one: the families and calibers it derives are its judgement.

## What's next

- Write a contract for **your** domain: [docs/guides/compile-contract.md](../../docs/guides/compile-contract.md)
- Build your own project from your own data: [`scaffold/`](../../scaffold/README.md)
- Understand the machine underneath: [docs/architecture.md](../../docs/architecture.md)

## Files

| File | What it is |
|---|---|
| `app.py`, `start.sh`, `server.py`, `worker.py`, `docker-compose.yml` | byte copies of `scaffold/templates/` — the replay story is literal |
| `engine/` | this project's engine, and the real one: the API and worker read it as `PNEUMA_KNOWLEDGE_ENGINE_DIR`, and the `console` profile browses and edits the same directory. It holds the model roles and their prices, the components (`people`, `time`, `attention`), chunking, answering (`evidence_strategy: select`), the compile contract and the owner profile. Versioned twice over — its files belong to this repository, and the console's own commits land in a `.git` this project ignores |
| `my-data/` | the synthetic corpus, in scaffold ingest format |
| `prebuilt/canonical.bundle`, `prebuilt/l0.jsonl.gz` | the two authorities from the build: the compiled canonical library (git bundle) and the verbatim L0 source rows its citations bind to (source ids are content-addressed, so identical material re-ingests to the same ids, and a restore keeps the stored ones exactly) |
| `build-record/` | task book, build log, cost accounting, the use-side session, and the two scripts that produced them |
| `eval/` | the frozen regression truth set over this corpus and the runner that scores a build against it |

## Running and auditing the reference build

The runtime files follow the current scaffold templates. `./start.sh` now builds material;
use `./demo.sh` for the interactive tour and `./app.py ask "…" --sources` for questions.
The prebuilt bundle preserves the historical reference build, including its imperfections.
`./app.py audit` reports seven existing dangling overview references across five pages:
`people/jianing.md`, `product/migration-guide.md`, `product/seamlog.md`,
`threads/export-and-project-removal.md`, and `threads/small-group-invitation.md`.
These unchanged regions do not block an unrelated compile. Rewriting a region requires
repairing it, and retiring a previously valid basis requires repairing its dependants.
The audit does not alter the shipped artifact or claim that mechanical validity proves fidelity.
