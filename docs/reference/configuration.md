# Configuration

**English** | [简体中文](configuration.zh-CN.md)

All framework settings are environment variables with the `PNEUMA_KNOWLEDGE_` prefix (a local `.env` is read by default; unknown keys are ignored). Names below drop the prefix. Copy [`.env.example`](../../.env.example) to start.

One optional layer sits between environment and default: the **engine directory** (`ENGINE_DIR`, [architecture §11](../architecture.md#11-the-engine-directory)). Precedence is **process env > engine file > framework default**, and it is enforced at settings assembly: the engine file's values reach `Settings` only for keys `os.environ` leaves unstated. Two consequences worth knowing: an entry present-but-empty in the environment is still an environment-level statement, and a value from a `.env` FILE is not process env, so it ranks BELOW the engine file. `ENGINE_DIR` unset (the default) means the whole layer does not exist and every setting resolves exactly as it did before the concept.

## Required

| Setting | Meaning |
|---|---|
| `USER_SCHEMA_BASE_VERSION` | The compile-contract version this deployment registered via `register_skill_base`. Deliberately has no default: the framework carries no domain contract, so the deployment must declare its own — an empty value fails loudly on the first compile. |

## Storage and middleware

| Setting | Default | Meaning |
|---|---|---|
| `ENV_FILE` | `.env` in the working directory | Process-environment control for `get_settings()`: unset preserves local `.env` loading; an empty string disables dotenv entirely; a path loads that file instead. Set `PNEUMA_KNOWLEDGE_ENV_FILE=` when running from an arbitrary directory to ignore its `.env`. Read only from the process environment, never from dotenv or the engine directory |
| `PG_DSN` | `postgresql://pneuma_knowledge:pneuma_knowledge@localhost:15432/pneuma_knowledge` | Postgres (L0, jobs, projections, registries) |
| `QDRANT_URL` | `http://localhost:16333` | vector store |
| `QDRANT_COLLECTION` | `pneuma_knowledge_chunks` | one collection; its embedding dimension is fixed at creation — switching embedding models means a new collection name |
| `MEILI_URL` | `http://localhost:17700` | lexical index |
| `MEILI_KEY` | `masterKey_change_me` | change in production |
| `MEDIA_S3_ENDPOINT_URL` | `http://localhost:19000` | private S3-compatible L0 image store (RustFS in the local stack) |
| `MEDIA_S3_ACCESS_KEY` / `_SECRET_KEY` | development values | S3 credentials; scaffold projects generate isolated random values |
| `MEDIA_S3_BUCKET` / `_REGION` | `pneuma-media` / `us-east-1` | S3 bucket and signing region |
| `MEDIA_MAX_IMAGE_BYTES` | `20971520` | maximum bytes accepted for one original image |
| `CANONICAL_ROOT` | `./data/canonical` | canonical store root (one repository per user); `/data/canonical` in the container image |
| `ENGINE_DIR` | (empty) | the engine directory: one versioned unit holding this deployment's strategy files, compile contract, prompt overlays and owner profile ([architecture §11](../architecture.md#11-the-engine-directory), [design](../design/engine-console.md)). Empty = the deployment has none: zero behavior change, and `/v1/engine/*` returns 404. Set it and the eight `/v1/engine/*` endpoints serve the directory; every strategy setting below that the directory states resolves from it unless the process environment says otherwise |

## Models

| Setting | Default | Meaning |
|---|---|---|
| `LLM_MODEL` | `openrouter:openai/gpt-5.6-luna` | base model spec and fallback for all roles |
| `LLM_MODEL_COMPILE` / `_RECALL` / `_ANSWER` / `_DEEP` / `_SKILL` / `_EVOLVE` / `_LIVE_CONTEXT` / `_LIVE_DISCOVER` / `_LIVE_PICK` / `_CHALLENGE` / `_BRIEF` | empty | per-role overrides; `answer` is only the final fast-answer generation and otherwise borrows `recall` |
| `ANSWER_REASONING_EFFORT` | empty | reasoning effort sent only on the final fast-answer call; generated projects also leave it empty to preserve the provider default |
| `LLM_TIMEOUT` | `600` | seconds; guards against hangs, not slowness |
| `LLM_MAX_RETRIES` | `3` | transient-error retries (langchain) |
| `EMBEDDING_MODEL` | `fake:384` | `fake:<dim>` (deterministic, keyless) or `openrouter:<model>`. A spec that needs a key nobody set is not a supported "no-L2" mode: startup logs one WARNING naming this setting, the variable (`OPENROUTER_API_KEY`) and the fact that semantic indexing and semantic recall will fail until it is set — a reminder, never a refusal |
| `MODEL_PRICING` | (empty) | what THIS deployment pays for the models above, one entry per line (or `;`-separated for a one-line variable): `<model id> = <input>/<output>/<cache_read>/<cache_creation> <CURRENCY>`, each rate per 1M tokens. Empty = no prices declared: every face that shows what a call spent shows tokens and no money. Engine key: `models.pricing` |
| `COMPILE_CALL_TIMEOUT` | `600` | seconds a single model call inside a compile job (tool loop, repair round, post-compile brief) may take. Sits above `LLM_TIMEOUT`, the provider-client guardrail: a hung connection otherwise holds the job `claimed` until the worker restarts; on timeout the job completes as failed and canonical is untouched. `0` = no timeout. Engine key: `models.compile_call_timeout` |
| `COMPILE_MAX_TOOL_CALLS` | `0` | tool calls ONE round of a compile may spend — the first round and its repair round alike. `0` is not unbounded: it means the number is derived from the job, `max(40, 3 x sources)`, because a first round must be able to read every supplied source and append at least twice per source (a fixed 40 cut a 36-source day group mid-append on a real rebuild and cost 14 day groups their place in the library). Any value > 0 is used as the absolute ceiling. The repair round is never handed what the first round left over: it gets its own fresh allowance, `max(12, 3 x violations)`, capped by this same number — one knob bounds both rounds. Engine key: `models.compile_max_tool_calls` |
| `OVERVIEW_BUDGET_CHARS` | `2000` | characters a canonical document's overview region may occupy — the bounded head a compile rewrites whole when the picture of the subject changed. Over it, the `rewrite_overview` tool refuses the call and the compile gate rejects the round: it is a head, not a second ledger. Engine key: `models.overview_budget_chars` |
| `OVERVIEW_REQUIRED_AFTER_CLAIMS` | `8` | ledger claims a document may hold before a compile that TOUCHES it must give it an overview (`definition` at least) — the floor under the budget above. `finish_compile` refuses first and the gate refuses after, naming the page and its claim count; pages the round never touched are not judged. A model maintains a head that exists and does not start one (measured: 41 of 85 pages on a real library had none, some at 20–31 claims). `0` disables it. Engine key: `models.overview_required_after_claims` |
| `COMPILE_IMAGE_MODE` | `auto` | `caption` = labelled caption/OCR only; `native` = derived text plus actual image blocks; `auto` = use the compile model profile, falling back to `caption` when unknown. Engine key: `models.image_mode` |

Model spec forms: `scripted:<path>` (local replay, keyless — and it hard-overrides every role, so a scripted run is fully deterministic), `openrouter:<model>` (needs `OPENROUTER_API_KEY`), or any provider prefix `init_chat_model` understands (e.g. `anthropic:claude-sonnet-5`, `openai:gpt-5.6-luna`). Role fallback is a single hop: `answer → recall`, `live_context → recall`, `live_discover → recall`, `live_pick → recall`, `evolve → compile`, `challenge → compile`, `brief → compile`, then `LLM_MODEL`.

Two of those roles are the full-scope Live Context lane's, and they exist because that lane is two small calls per tick rather than one large one (architecture §7). `LLM_MODEL_LIVE_DISCOVER` (engine key `models.live_discover`) runs stage ① — it reads the pending conversation and decides whether the tick retrieves at all — and wants a **small reasoning** model: its output is a few dozen tokens and what it needs is fast judgement about a conversation. `LLM_MODEL_LIVE_PICK` (engine key `models.live_pick`) runs stage ③ — choose one of the already-assembled candidate cards or none, write one short lede, prune the citations, score it — and wants a **weak fast** model, because there is nothing to reason about: the evidence is in front of it and it may not rewrite a word of it. The generated engine names `openrouter:openai/gpt-5.6-sol` and `openrouter:openai/gpt-5.6-luna` respectively; both empty borrows `recall`, which keeps an existing deployment working unchanged. Their reasoning effort is **pinned in the framework** (`low` for discover, off for pick) and is deliberately not a knob: an effort a deployment could raise would change what the lane costs per tick, and cheapness is the whole argument for spending a call before retrieving rather than after. `LLM_MODEL_LIVE_CONTEXT` still routes the briefing-scope round and the card expansion, which are one call each and unchanged. The scaffold defaults `recall` to Luna and leaves `answer` and `answer_reasoning_effort` empty: the final fast answer borrows `recall` with the provider's default effort. A separate answer model or explicit effort is an optional deployment choice.

### `agent:<backend>` — a coding agent instead of a model

`LLM_MODEL_COMPILE` (engine key `models.compile`) accepts one further form: `agent:codex` or `agent:claude-code`. It names an **executor** rather than a model — the round is driven by that coding agent on this machine, under the Owner's own subscription, through the same claim-level draft and the same gate as a model executor ([coding-agent-mode](../design/coding-agent-mode.md) ruling 1). The change takes effect after `restart` for future compile jobs and evolve jobs that inherit their executor. Moving back is the same one-line edit.

This changes four behaviors:

- **Compile and evolve have agent doors.** `LLM_MODEL_EVOLVE` accepts `agent:<backend>` and inherits compile's executor when empty. Both roles use the harness and their own persisted draft gate. Challenge still skips a borrowed agent spec and uses the base API model; it remains off by default. Other roles explicitly naming `agent:`, or a base `LLM_MODEL` naming it, are refused at startup.
- **The worker's posture covers both doors.** With `AGENT_UNATTENDED=true`, it opens and hands compile/evolve jobs to the harness. With `false`, agent jobs stay queued for `pkc draft open` or `pkc evolve draft open`. Index, projection and adopt jobs drain as usual. The same per-user single-writer lock governs either body.
- **An agent compile supplies its own brief.** `pkc draft finish --brief <f>` / `--brief -` accepts non-blank text up to 8,000 characters; unattended, the harness's last message fills a successful version's missing brief under the same bound. No brief API model is called, and an explicit brief is never overwritten. This does not depend on the API narration switch `BRIEF_ENABLED`.
- **Semantic chunking degrades.** A coding agent does not answer an `ainvoke`, so `CHUNK_STRATEGY=semantic` falls back to mechanical sentence chunking exactly as it does for a scripted or keyless deployment; the engine file keeps saying `semantic`, and a later key plus `rebuild_derived` fills it in.

| Setting | Default | Meaning |
|---|---|---|
| `EXECUTOR_BACKEND` | (empty) | which coding agent is typing the `pkc draft` commands, set by whoever launched that session. It is a **label on what happened**, never a switch: what a deployment runs on is `LLM_MODEL_COMPILE`. A job finished through the CLI records `executor = agent:<backend>`, and `agent` alone when this is unset — an Owner's own terminal session names no harness rather than guessing one. Not an engine knob (deployment wiring) |
| `AGENT_UNATTENDED` | `true` | whether the WORKER runs compile and evolve jobs through their coding agents itself. A worker is by definition unattended — nobody is at a terminal where it runs — so under an `agent:` executor it claims a compile job, opens its draft and hands it to a harness it launches ([coding-agent-mode](../design/coding-agent-mode.md) §9). `false` is the interactive posture: agent compile/evolve jobs stay queued and the Owner's session opens them through their respective draft commands; other jobs drain as usual. Under a model executor this decides nothing. Not an engine knob (deployment wiring) |
| `AGENT_PROBE_ON_START` | `true` | probe the configured compile harness when the stack starts, and refuse to start when it is not usable. A harness that is installed but not logged in drops into an interactive flow and waits forever, so "is it live" is a question a deployment answers before it queues work rather than on the first compile. Liveness, never a version comparison. Only the unattended posture probes — a `pkc` process never launches a harness, so it never does. `false` for tests and CI, where the binary on PATH is a fake and a login is not a thing that exists. Not an engine knob |
| `AGENT_RETRIES` | `3` | how many times the unattended launcher may relaunch a round the harness refused with a RATE LIMIT — and only that. Any other refusal is reported rather than retried (it will be refused again), and a timeout is not retried either, because the wall clock is the statement that the round is over. Waits are exponential with jitter and bounded by the launcher's own ceiling; a model at capacity is spaced wider (15 s, 30 s, 60 s), because capacity usually returns within minutes. Every wait is logged. `0` means one attempt and no backoff. Not an engine knob |
| `AGENT_TASK_STRUCTURE_CHARS` | `60000` | how much numbered source text a coding agent's compile task carries before it stops and names the rest: one line per cut source says which blocks are not shown and the exact `pkc source fetch <id> ¶a-b --page N` that reads them, by the library's id rather than the round's `sNN` handle. Only the agent round is bounded — a model executor has no second way to read material, so its task is unchanged byte for byte. What the round may cite is unchanged too: the gate bounds citations against L0, not against the task. `0` = no bound. Not an engine knob |
| `AGENT_EPISODES_WINDOW_CHARS` | `400000` | how much of one source a coding agent's **episodes** task carries. An episodes round's task is the material it judges, so a longer source is not cut but judged in consecutive windows of whole blocks — one episodes job and one round per window, each judgement a kept record of its own, the source's L2 written once every window is recorded. Measured on the task's rendered block and section entries, not the bare text. The default is the order of the personal edition's `max_part_chars` and leaves the system text and skill room under Codex's 1,048,576-character input cap. `0` = one window, no bound. Not an engine knob |
| `AGENT_RATE_LIMIT_COOLDOWN_S` | `900` | how long the worker leaves a tenant's agent-path jobs alone after the harness said the subscription is out of room AND said nothing about when it comes back. Doubles per consecutive hit up to `AGENT_RATE_LIMIT_COOLDOWN_MAX_S`, and is forgotten by the first round that actually runs. It is the fallback, not the rule: when the harness names a deadline (Codex prints `try again at Sep 15th, 2026 9:23 AM`, read in `DEFAULT_TIMEZONE`) that instant wins, because it is the provider's own answer and this is a guess. The wait is a `not_before` on the re-queued row, so nothing sleeps and a restart reads the same answer. Not an engine knob |
| `AGENT_RATE_LIMIT_COOLDOWN_MAX_S` | `21600` | the ceiling that doubling stops at — six hours. Guessing short is the expensive mistake: 853 jobs went through a dead quota in four hours before this existed. Not an engine knob |
| `AGENT_UNAVAILABLE_COOLDOWN_S` | `120` | the same wait when the harness said the MODEL is at capacity (Codex: `Selected model is at capacity`) rather than that the subscription is spent. Capacity comes and goes within minutes, so this is its own short wait: it doubles per consecutive capacity refusal up to `AGENT_UNAVAILABLE_COOLDOWN_MAX_S` and is forgotten by the first round that actually runs. Before the tenant cools at all, the launcher spaces its own relaunches for this refusal at 15 s, 30 s and 60 s (with jitter), so a brief dip is usually absorbed inside one launch. A usage limit is unaffected. Not an engine knob |
| `AGENT_UNAVAILABLE_COOLDOWN_MAX_S` | `900` | the ceiling that capacity doubling stops at: fifteen minutes, not the usage limit's six hours. Not an engine knob |
| `AGENT_MODEL` | (empty) | WHICH model the launched harness runs, passed as the launch template's model flag (`-m` / `--model`). Empty leaves it to the harness — which means the Owner's own global harness configuration, because the per-job config home is seeded from it. Name it when a library's rounds are not to inherit whatever the Owner set for their own terminal. Not an engine knob |
| `AGENT_REASONING_EFFORT` | (empty) | how hard that harness is told to think: `minimal`, `low`, `medium`, `high` or `xhigh`, refused at boot when it is anything else. Codex carries it as `-c model_reasoning_effort=<e>`; the Claude Code CLI has no such flag in this version and drops it. Empty is the harness's own default. Not an engine knob |
| `AGENT_REASONING_EFFORT_EPISODES` | (empty) | the same effort for **episodes** rounds alone (L2 episode boundaries for one source) — a simpler judgement than a compile that otherwise costs a compile round's context. Same accepted set, refused at boot likewise; empty inherits `AGENT_REASONING_EFFORT`. Compile and evolve rounds are unaffected. Not an engine knob |
| `AGENT_KEEP_WORKDIR` | `false` | keep the launcher's per-round working directory (the system text, the task, the harness's last message) instead of deleting it. Debugging only: those files hold the library's material, so leaving them in `/tmp` is a decision an operator makes on purpose. Not an engine knob |
| `PROJECT_DIR` | (the API's cwd) | where the console's Steward view spawns its harness ([coding-agent-mode](../design/coding-agent-mode.md) §5.6). The project the skill was installed into, so the harness reads this deployment's `AGENTS.md` / `CLAUDE.md` and finds the skill beside them — the same convention `pkc` and the unattended worker follow. Stated as a setting because the API and the worker need not share a working directory. Not an engine knob (deployment wiring) |
| `STEWARD_SESSION_IDLE` | `1800` | seconds a console Steward session outlives the browser tab that opened it. Closing a tab is not ending a conversation: the harness process stays up and a reconnect re-attaches to it, repainting from the session's own event tail. Past this the process GROUP is reaped TERM→KILL and the session's transcript (`steward_turns`) is deleted with it; the next attach starts a new session. `0` reaps a session the moment its last socket goes away. Not an engine knob |
| `STEWARD_SKILL_HASH` | (empty) | the sha256 of the skill package the Steward's session was taught with. Exported by the shim `pkc skill install` writes (`<skills dir>/pkc-steward/scripts/pkc`), read once, and stamped into every canonical commit that session produces as the `Executor-Skill:` trailer — beside `Skill-Content-Hash` and `Prompt-Overlay-Hash`, so the words the executor read are as identifiable after the fact as the words the contract gave it. Unset, no trailer line is written and a model-compiled commit is byte-for-byte what it has always been. Nothing sets it for you: an agent session that did not come through the shim is honestly unidentified rather than guessed at. Not an engine knob (session wiring) |

**The skill package.** Under an agent executor the Steward is taught by a generated skill — `SKILL.md`, the composed contract, the compile instructions, the command reference, the gate reference and the shim — installed into the project by `pkc skill install [--backend codex|claude-code|all] [--project <dir>]`. It is a *rendering* of this deployment (contract × prompt overlays × language × components × command tree) and never hand-written, so `pkc skill verify` re-renders and exits `4` listing what drifted; `pkc skill show` prints the hash and the file list. The scaffold installs it at generation time when you answer `compiler = codex | claude-code | all`, and an engine apply re-installs it, blast radius `future_compiles` — a session already running keeps the words it started with until it restarts. All three commands read the engine directory only: no database, no key, no running stack.

**`executor` on a job.** Every finished job records who ran its round: `langchain:<resolved model spec>` from the worker's own loop, `agent:<backend>` from a coding agent. It sits beside `token_usage` because the two answer one question together — an agent-executed job names its executor and reports **no** usage at all, since the harness's counters belong to the Owner's subscription and this process never saw them. Absent, never zero: a zero there would be a claim that the round was free. Both fields are readable on `GET /jobs` and in the console's process view.

Beside those three there is a fourth, optional model on the same lane: `LIVE_WEB_SEARCH` (engine key `models.live_web_search`, default `false`) opens a **supplementary** internet face beside the library, and `LIVE_WEB_SEARCH_MODEL` (engine key `models.live_web_search_model`, default `openai/gpt-5.6-luna`) names the OpenRouter model that serves it, with that provider's own native web search behind it. It reuses `OPENROUTER_API_KEY` — no second secret — and with no key the search reports itself unavailable and the `web` lookup is never offered, whatever the flag says. Enabling it here opens the possibility rather than turning it on: **both** the deployment and the individual connection must say yes before the discover contract even advertises the lookup, and the `ready` frame echoes what was granted rather than what was asked (see [http-api.md](http-api.md)). It bills per search, and what the searches cost rides the tick record.

`native` is an explicit assertion that the selected model and routed provider accept LangChain image content blocks; an incompatible provider fails instead of silently flattening the image. `caption` requires the importer to supply labelled `caption`/`ocr` representations and never claims that the compile model saw the original. `auto` recognizes the full GPT-5.6 family on direct OpenAI and OpenRouter routes as native-image capable even when a gateway omits LangChain's model profile; other unknown profiles stay on the conservative `auto → caption` path.

### What a call costs

The framework holds no price opinion, and `MODEL_PRICING` is where a deployment states its
own. All four rates are required — leaving the cache rates off is not saying they are free —
and so is the currency, because a defaulted `USD` would be the framework guessing about a
deployment that may bill in anything. A declaration that cannot be read is refused at boot
and at the engine console's apply, with the offending entry named, rather than quietly
showing no money.

```yaml
# engine.yaml
pricing: |
  openrouter:openai/gpt-5.6-luna = 1.25/10/0.125/1.25 USD
  openrouter:openai/gpt-5.6-sol  = 0.25/2/0.025/0.25 USD
```

A spec is looked up exactly as it is routed (`openrouter:openai/gpt-5.6-luna`) and then by
the bare model id after the provider prefix, so a rate card quoted per model still prices a
model bought through a gateway — and an exact entry always wins, for a deployment that
really does pay two gateways differently.

Money is **derived when it is read** and never stored: correcting a rate corrects every
figure at once, and no record carries an amount nobody can reproduce a quarter later. What
is stored is the token usage itself (`token_usage` on a consultation, on a compile job).

Two refusals are deliberate. An **undeclared model** is reported in tokens with no money
beside it — never a zero, which would claim the call was free. And a lane whose model roles
resolve to **two different prices** is reported in tokens too: a lane's usage is one sum over
every call it made (fast spends on `recall` and `answer`, a Live Context tick on
`live_discover` and `live_pick`), there is no per-role split inside that number, so applying
one of two applicable rates would be invented money wearing a derived label. Roles that agree
on one price price the lane exactly.

## L2 chunking

| Setting | Default | Meaning |
|---|---|---|
| `SEMANTIC_RETRIEVAL` | `on` | `on` / `off`; engine key `intake.semantic_retrieval`. Changing it requires `restart` + `derived_rebuild` |
| `CHUNK_STRATEGY` | `semantic` | `semantic` = one compile-role call returns topic/episode boundaries plus a grounded title/description for L2 retrieval and derived answer context (falls back to `sentence` under `scripted:` models); `sentence` / `recursive` = mechanical, zero LLM cost |
| `SEMANTIC_OVERLAP` | `smart` | `semantic` only. `smart` = the model returns closed block intervals, so a hinge block belongs to both neighbouring segments; `off` = the original zero-overlap cut |
| `CHUNK_SIZE` | `768` | maximum embedding-unit size after semantic boundary detection; tokens, ~1 token/char for CJK |
| `CHUNK_OVERLAP` | `128` | tokens |

**`SEMANTIC_RETRIEVAL`.** Set `PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL=off`, or run
`pkc config set semantic_retrieval off` to write `semantic_retrieval: "off"` in
`intake/intake.yaml`. The command works before middleware starts. Explicit process environment
still overrides the engine file. With `off`, startup builds neither an embedding client nor a
vector client, so no embedding key is needed. Intake proposals force `semantic_indexing: none`
and the archetype picker offers only presets with that value. Indexing still writes L1; it
creates neither L2 chunks nor chunk manifests. Fast, rag, deep, briefing and live context use
lexical source search and the canonical claim face; vector arms and episode summaries are
skipped, with skipped stage timings. `pkc search --mode semantic` explains the disabled lane.
Both ops rebuild commands print that L2 was skipped, while `rebuild_derived` still rebuilds
L1, the lexical/PG claim projection, and components.

Restart after changing the setting. To enable semantics for existing sources, run
`pkc config set semantic_retrieval on`, configure the embedding key when the chosen model
requires it, restart, and run `rebuild_derived`. Intake records keep
`semantic_indexing_requested` when the deployment ceiling changed a non-`none` plan, so this
rebuild restores that source's requested mode without rewriting L0. An explicitly lexical-only
source stays lexical-only. Absent manifests are computed and recorded on the first semantic
rebuild; subsequent rebuilds replay them. Existing manifests are left untouched while off.

**`SEMANTIC_OVERLAP`.** A hinge — the sentence that closes one topic while opening the next, the answer that also sets up the following question — reads as part of both segments, and a cut has to put it in one of them. `smart` stops making that choice: every returned episode object ends with `start`, `end` closed-interval coordinates, and neighbouring intervals may share the hinge. How much to share is judged per boundary, not a fixed stride.

**Episode representation.** In the same structured response, each semantic segment returns fields in meaning-first order: `title`, `description`, then `start`/`end` coordinates (`off` omits `end`, which is implied by the next start). The description follows the source only: concrete people, time, place, events, decisions, emotions, reasons, plans and outcomes. A known source occurrence date anchors relative time, but exact period endpoints are emitted only under an unambiguous calendar convention. Raw/caption text and episode title/description are embedded as separate L2 representations and ranked independently; the episode point also retains its title/description as dense **derived L2 content**. Ordinary RRF is followed by rank-ordered source-span overlap suppression. When an episode-only hit overlaps raw/caption or lexical evidence, the precise evidence span is retained and inherits at most the episode's rank. Fast recall can render up to `RECALL_EPISODE_SUMMARY_CAP` high-ranked descriptions in a dedicated `derived episode summaries` section. Every item says that it is generated rather than verbatim and carries mechanically resolved source title, occurrence time, section, and exact `source_id + block span`; raw/claim evidence wins any exact-detail conflict. Context assembly does not expand semantic spans again and, by default, merges only true overlaps; a bare lexical-only block expands by one following block by default. New v3 manifests replay coordinates and descriptions without a model call; an older boundary-only manifest receives one fixed-span description call whose returned coordinates must match exactly.

The degenerate reading of "segments may overlap" is that every segment should be the whole document, which would guarantee each one contains the answer and collapse L2 into N copies of the source. That is refused by a gate, not by prompt wording: every returned interval list must have real ordered endpoints, strictly increasing starts, gapless cover of the window, at most **three** shared blocks between neighbours, and no more segments than blocks. One violation rejects the whole output, and that window degrades to the zero-overlap partition built from the starts the model did report — the overlap is refused, the segmentation is not.

`off` retains the original zero-overlap geometry. The episode-producing prompt is a new pinned baseline, so measurements made with the former boundary-only prompt are intentionally retired rather than compared as if the harness were unchanged.

Overlap duplicates a block across two L2 chunks. That duplication is derived-layer only: L0 is untouched, both chunks address the same source blocks through the one addressing scheme, and retrieval suppresses the lower-ranked overlapping result, so a hinge retrieved through both chunks reads once. The chunk manifest records which mode produced its spans, so flipping this knob and running `rebuild_derived` genuinely re-cuts instead of replaying the old layout. Older records keep their coordinates exactly; only their missing derived description is added during the one-time v3 migration.

## Evolution and grooming

| Setting | Default | Meaning |
|---|---|---|
| `EVOLVE_AUTO_TRIGGER` | `true` | compile-driven evolution triggering |
| `EVOLVE_TRIGGER_TOPIC_DOCS` | `5` | new-document threshold (AND-ed with the next) |
| `EVOLVE_TRIGGER_NEW_CLAIMS` | `30` | new-claim threshold |
| `EVOLVE_DRAFT_TTL_HOURS` | `24` | draft lifetime |
| `COMPILE_DRAFT_TTL` | `21600` | seconds an OPEN compile or evolve draft (`pkc draft open` / `pkc evolve draft open`, [coding-agent-mode](../design/coding-agent-mode.md) §6) may go quiet before the queue's self-heal treats it as abandoned. A draft is rewritten by every `pkc draft` command, so its `updated_at` is the liveness signal for a round somebody is actually driving; past the TTL the draft is deleted and its job requeued — the same outcome a worker killed mid-job gets, and never a canonical write, because an unfinished round wrote nothing. `0` disables draft protection: every claimed job is requeued on worker start, exactly as before drafts existed |
| `RECALL_HANDOFF_TTL` | `86400` | seconds a PENDING RECALL HANDOFF waits for its answer before the same startup self-heal deletes it. `pkc recall --evidence` ([coding-agent-mode](../design/coding-agent-mode.md) §5.1) hands the fast lane's assembled context to the Steward and records the hand-over — question, instant, library ref, evidence manifest — so `pkc consult answer` can turn it into a consultation later. A day is long enough for a Steward to come back after a night and short enough that questions nobody answered do not accumulate; past it the row is gone and that question simply left no consultation, which is what actually happened. `0` disables the sweep |
| `ROLLOVER_THRESHOLD_CHARS` | `40000` | document size that enqueues a groom job; `0` disables |
| `ROLLOVER_KEEP_RECENT_CHARS` | `12000` | tail kept in the active document |
| `RECALL_CLAIM_CANDIDATE_CAP` | `80` | claim retrieval depth before containment dedup, optional reranking, and final context truncation |
| `RECALL_CLAIM_CAP` | `40` | compiled claims admitted to the final fast-answer context |
| `RECALL_WINDOW_CANDIDATE_CAP` | `60` | fused lexical/raw/episode source spans retained after retrieval |
| `RECALL_EPISODE_SUMMARY_CAP` | `16` | explicitly derived, metadata-rich episode summaries admitted to final context |
| `RECALL_WINDOW_CAP` | `6` | exact verbatim source windows admitted to final context |
| `RECALL_EVIDENCE_STRATEGY` | `ranked` | fast-only context composition: `ranked` keeps fixed retrieval heads; `select` adds one structured recall-model call that selects a bounded mix across claims, episode summaries, raw windows, and known canonical documents; `all` makes no selection call at all and hands that whole candidate pool to the answer, bounded only by `RECALL_ALL_CONTEXT_CHARS`. Per-call override: `evidence_strategy` |
| `RECALL_ALL_CONTEXT_CHARS` | `120000` | read only by `RECALL_EVIDENCE_STRATEGY=all`, whose only bound it is: characters the assembled evidence faces may occupy. Over it the lane drops windows, then episode summaries, then the lowest-ranked claims, marks the answer `evidence_selection_degraded="all:truncated"` and states the per-face counts in the `assemble` stage preview. `0` = no ceiling |
| `RECALL_ANSWER_FORMAT` | `text` | fast-only answer wire: `text` is the existing free-text call; `structured` separates answer kind, clean answer text, and precise citations, then admits only exact evidence spans. Per-call override: `answer_format` |
| `RECALL_SELECTION_REASONING_EFFORT` | (empty) | optional provider reasoning-effort hint for the `select` call; empty sends no override |
| `RECALL_PLAN_QUERIES` | `0` | `0` off; N>0 = one planning call derives up to N extra retrieval queries, pooled by one RRF fusion |
| `RECALL_RERANK_MODEL` | (empty) | empty off; `llm` = LLM reranker on the recall model at reasoning effort `none`; `llm:<spec>` picks the model; a bare model name (e.g. `cohere/rerank-4-pro`) uses the OpenRouter `/rerank` endpoint |
| `RECALL_RERANK_CANDIDATES` | `120` | per-query/per-face retrieval depth when reranking; the reranker scores the full deduped union (hard cap 1000) |
| `RECALL_ANSWER_STYLE` | `conversational` | answer-style preset for fast/deep answers: `concise` = the bare exact value/phrase (graders, scripts), `conversational` = a natural chat reply, `detailed` = a self-contained written note. Shape only — truth discipline is style-independent. A recall request may override per call (`answer_style`) |

`select` is a quality/latency trade-off, not a different retrieval authority. The selector
returns candidate indexes and known paths only; the framework validates them, unions a small
deterministic ranked safety head, and follows selected claim/episode provenance back to
bounded L0 passages. Timeout or schema/provider failure falls back to ranked context and is
reported as degraded telemetry. Because this call is serial between retrieval and answering,
measure selector latency separately before making it a deployment default. `ranked + text`
remains the compatibility and lowest-latency profile.

`all` is the opposite trade: it spends no selection call and no retrieval-order truncation,
so the candidate pool `select` would have judged goes to the answer whole — one answer call,
the same faces in the same order and format, a longer prompt and a bigger input bill. It buys
the failure mode where the right evidence was retrieved and then not picked; it costs input
tokens and answer-side attention. Under `structured` its schema opens with one bounded
`deliberation` field, so the evidence review no selector performed happens inside the
answering call, before the answer commits; the review is returned on the wire as
`deliberation` and never enters the SystemMessage. The ceiling is the only thing that can cut
this context, and it never cuts silently.

Which of the three to run for a given business, and what `deliberation` and the two reasoning-effort knobs are worth: [guides/recall-strategies.md](../guides/recall-strategies.md).

## Prompt language

| Setting | Default | Meaning |
|---|---|---|
| `PROMPT_LANGUAGE` | `en` | which language the FRAMEWORK's own prompt clauses arrive in: `en` = the English catalog, `zh` = core's Chinese language pack (`prompts.lang_zh.chinese_overlay()`, every catalog key translated with the same placeholders). Applied as an overlay UNDER a deployment's own overlays, so a hand-written clause always wins over the pack. `en` registers no overlay at all, so it is byte-for-byte the pre-language-pack behavior |

It changes the prose the models read, and nothing else — no policy, no mechanism, no
placeholder contract. In particular it does **not** decide what language a knowledge base is
written in: that follows the subject's own declared language (`compile.owner_env.write_language`).


## Post-compile coverage challenge

| Setting | Default | Meaning |
|---|---|---|
| `CHALLENGE_ENABLED` | `false` | after each committed compile, run a coverage audit: blind question generation over the material, claim-face probing, reflection |
| `CHALLENGE_MAX_ROUNDS` | `2` | question/reflection rounds per audit (either stage can end early by declaring exhaustion) |
| `CHALLENGE_MAX_QUESTIONS` | `6` | questions per round |
| `CHALLENGE_MAX_OUTPUT_TOKENS` | `32768` | completion budget for the audit's structured passes — a runaway generation fails cheaply instead of at the provider ceiling (observed live: 65,536 tokens); `0` = provider default |
| `CHALLENGE_COMPENSATE` | `true` | confirmed gaps enqueue one compensation compile (its writes pass the ordinary citation gate) |
| `LLM_MODEL_CHALLENGE` | empty | model for question generation and reflection; empty borrows the compile role |

The audit's judgement is extensible: its three prompts — `compile.challenge.questions_system`, `compile.challenge.reflect_system`, `compile.challenge.compensation_preamble` — live in the prompt catalog and can be replaced wholesale via `override_prompts` at startup, like any other model-visible wording.

## Post-compile brief

| Setting | Default | Meaning |
|---|---|---|
| `BRIEF_ENABLED` | `false` | for an API executor, after each committed compile, one model call narrates the compile's mechanical claim events into a short brief, stored on the job row and shown on the History timeline (labelled derived) |
| `LLM_MODEL_BRIEF` | empty | model for the narration; empty borrows the compile role |

The API-generated brief's only input is the mechanical record — the claim events derived from the diff plus the per-source provenance sentences — never the compile conversation, so there is nothing beyond the record for it to narrate. It is display copy, not knowledge: no citations, no canonical write, and a generation failure degrades to no brief rather than a failed job. Its prompts (`compile.brief.system`, `compile.brief.task`) live in the prompt catalog like any other model-visible wording.

## Recall access statistics

The framework's own consumer of use-side records: per-target access metadata — last access,
hits in the last 7 and 30 days — kept in the derived layer and joined at read time. Not a
component's, and needing none registered: every `business` consultation reaches it. Inert by
default all the same, because the default visitor class is `silent` and a silent visitor
records nothing at all.

| Setting | Default | Meaning |
|---|---|---|
| `ATTENTION_HALF_LIFE_DAYS` | `14` | how fast recorded attention fades: a read this many days old counts half of today's. No score is stored (heat is computed when the ledger is read), so changing this rewrites nothing. `0` = no decay. Read by the `access-stats` endpoint and by the `attention` component's report alike |

Delivery is the ordinary job queue. An answering route writes the consultation row and, for a
`business` visitor, enqueues one `recall_projection` job in the same transaction; the compile
worker drains it, applies the statistics and the record's `projected_at` stamp in one
transaction, then tells any registered component. Nothing is processed in the request path,
so the answer waits on none of it — and a projection therefore lags its consultation by the
queue's drain (per user, FIFO, one job in flight per lane, and a projection is in the derived
lane: seconds on an idle library, and no longer behind a compile, which drains in the other
one — architecture.md §5). `scripts/ops/rebuild_derived.py` re-derives the ledger by enqueueing one
`recall_rebuild` job and draining it, so the replay takes the same per-user claim and cannot
interleave with a projection in flight.

## Index components

| Setting | Default | Meaning |
|---|---|---|
| `COMPONENTS` | empty | comma-separated names of enabled index components (architecture §6); empty = none. Shipped: `people`, `time`, `attention` |
| `PEOPLE_FAMILY` | `memory/people/{slug}.md` | the contract path template the `people` component binds to — one of the skill's `path_templates` |
| `ATTENTION_WINDOW_DAYS` | `60` | how far back the `attention` report reads. Older days stay in the table, outside the question |
| `ATTENTION_EVIDENCE_CHARS` | `1500` | character ceiling on the block `attention` hands a schema-evolve proposal. Cut on a line boundary, with what did not fit counted |
| `RECALL_COMPONENT_PATHS` | `true` | fast lane: when enabled components offer lookup paths, one routing tool-call turn chooses which run (architecture §7). No path offered = no routing call. `false` ignores component paths |
| `RECALL_COMPONENT_BUDGET_CHARS` | `6000` | character ceiling on the whole component face. A path's own cap bounds item counts; this bounds the context they may occupy. Over it, the lowest-ranked items fall off and long excerpts are cut at block boundaries — both stated in the face, never silent |

`COMPONENTS`, `PEOPLE_FAMILY` and the three `ATTENTION_*` knobs live in the engine directory's `engine.yaml`; the two recall knobs live in `recall/recall.yaml`. The full design — what a component is, the faces it may fill, and how to write one — is [design/index-components.md](../design/index-components.md). Enabling a component adds its gate checks, its outline lines and its tools on the next process start; disabling it removes them and leaves canonical untouched — a component holds no knowledge, only structure derived from the substrate it declares. With `people` on, person pages carry `identities` (`scheme:value`; `mailto:` / `im:` / `meeting:` as the source contracts record them) and `aliases` as comma-separated frontmatter. Both belong to the document's overview and are written whole with it (`rewrite_overview(fields=…)` / `set_fields`) — a snapshot, never only-growing. Three facts about them are refused mechanically at the write face and again at the gate, over the pages a round **touched** — body or frontmatter differs from what it held at the head of the round, or the page is new (`people.identity_shape`, `people.identity_duplicate`, `people.identity_cospeakers`, `people.alias_collision`): an identity is `scheme:value` and is bound by at most one page; two person ids that both SPEAK in one conversation are two people, so one page may not bind both — an IM `sender_id` and a meeting `speaker_id` are person ids, an email address is not (one human writing from two addresses is ordinary, and `email/v1` establishes no equivalence between them), so email threads contribute no co-speaking evidence; and an alias is not somebody else's name (another person page's alias, title or slug, or a display name the sources record for an identity this page does not hold). A fourth rule is a decision rather than a fact, and it is asked ONCE: every address term the library reports for a person this compile's sources carry must end the round either recorded in that page's `aliases` or declined with `decline_alias(path, term, reason)`. A decline writes nothing — no claim, no alias, no field, nothing on the page — because canonical records what is known about a person, not the names that are not theirs; it answers the round that calls it and is stored nowhere. What closes the question is the page being WRITTEN, judged on two derived facts: the projection's `reported_since` (the day the term → identity pair first crossed the reporting bar) against the day canonical last committed that page (`written_on`, one `git log` walk bounded to the family). A page committed on or after that day has been shown the question and is never asked again, whatever it decided; a page created this round, or a projection row from a library that predates the column, has no date — and both unknowns mean ask. So a round that declines and writes nothing is asked again next round, which is correct: nothing was committed, so nothing was answered. A fifth kind belongs to no page: `people.not_ready` refuses a round whose library-wide mirror could not be loaded, because judging those facts against an empty library would allow exactly the writes they exist to refuse — nothing is written and the next compile reads again. There are two such mirrors and each is demanded only by the round that needs it: the source boundary (required when this round wrote a person page declaring these fields, or its sources carry an identity) and the address-term projection (required only when a term decision applies), so a topic-only compile is not refused by a projection outage it asks nothing of. One further operational note: while any component is enabled, one compile runs per process at a time (the framework holds a lock from `prepare` to the end of the job), so a deployment scales compiles by adding worker processes rather than by running them concurrently in one. The compile model gets `find_person` and `decline_alias`; deep recall gets `enumerate_identities`, computed on demand over the user's L0 source metadata, and `person_profile(alias, identity, section, offset, limit)`. Both fast paths return everything they know — the whole page, the whole range — and the framework orders that against the question before spending the path's cap on it (architecture §7); both deep tools paginate and end every response with the exact call that fetches the rest, because a cap in an agentic lane must never be a dead end. `people` also keeps a persisted projection (PG `component_people_terms`): one row per **address term → target identity** pair read off turn structure, with its library-wide support. A term is reported for a target only when it has enough support, from more than one source, and that target holds most of the term's total — concentration, not frequency, which is what separates a nickname from any short phrase before a comma. Reported terms appear under each source in the compile task with their whole distribution and beside each identity in `enumerate_identities`; a term this source repeats but the library cannot yet back is labelled *emerging*. A third, weaker line lists the repeated name-shaped tokens of a source that match no present identity, with no target attached — the mentions no turn structure can point at anybody. The rows accumulate as sources are indexed, each source exactly once: a manifest table beside them (`component_people_indexed`) is claimed in the same transaction as the counts, so a redelivered index job adds nothing — and that idempotence is what lets an archived source's contribution be recomputed from L0 and subtracted exactly at the read. Upgrading a library whose counts predate the manifest performs one backfill on the first boot — every source that library already owns is recorded as accumulated, so nothing already counted is counted again, and a source that had in fact contributed nothing stays uncounted until the next rebuild. `scripts/ops/rebuild_derived.py` re-derives both tables from L0, starting from nothing. Each row also carries `reported_since`, the day that pair first crossed the reporting bar — the clock the one-time alias decision runs on, written once, never moved, and re-derived by the same rebuild (a row from a library that predates the column has none, and is asked about until a rebuild fills it). That one table is all it keeps; a decline is stored nowhere.

With `time` on, the component keeps a persisted projection (PG `component_time_blocks`): one row per L0 block, holding the block's UTC instant and the calendar day it falls on **in the subject's timezone** — the same day ingest wrote into the block's section, never the UTC date, because for a subject at +08:00 everything sent between 00:00 and 08:00 local carries the previous UTC date. Each row also records the zone it was normalized under and where that zone came from (`DEFAULT_TIMEZONE`, the profile, or a registered provider), so changing a subject's timezone never silently mixes two calendars: existing rows keep saying what they were built from, and `scripts/ops/rebuild_derived.py` re-derives them explicitly. Fast recall gets a `timespan(since, until)` path, deep recall gets `timeline(since, until, granularity, offset, limit)` — `granularity="verbatim"` reads ONE day block by block instead of digesting it — and `as_of(date, alias, identity)`, and the compile task gets one line per source stating its span in the owner's day and clock (plus the source's own zone when the two differ). Every date argument is an ISO `YYYY-MM-DD` day in the subject's zone: the component never parses natural-language time — the routing turn, which sees `as_of` and the subject's zone, resolves "last quarter" into ISO days first, and a non-ISO argument becomes an `invalid_args` row in the answer's audit trail rather than a quietly different range.

## Behavior switches

| Setting | Default | Meaning |
|---|---|---|
| `DEFAULT_TIMEZONE` | `UTC` | calendar-day zone when the profile doesn't state one |
| `LOG_LEVEL` | `INFO` | how loud this deployment's own loggers are — `pneuma_knowledge_service`, plus any logger an application standing over the library names when it starts the engine. Configured once where the engine process is assembled (`engine_process.configure_logging`), to stderr, one line each with the logger's name; uvicorn keeps its own handlers and is never doubled. Before it existed the compile worker's account of an unattended round (`round finished: exit 1`, `cooling until …`) went to a logger nobody had configured, so the engine log held only `print()`ed lines and uvicorn's INFO. An unknown name reads as `INFO` rather than refusing to start. Not an engine knob |
| `USER_SCHEMA_PACKS` | `true` | per-user schema-pack composition |
| `USER_SCHEMA_MATRIX_PATH` | unset | deployment pack-matrix JSON; unset uses the built-in |
| `CONTEXT_STREAM_RENDER_ROLES` | `true` | render owner/participant labels at ingest |
| `CONTEXT_STREAM_COMPILE_GUIDANCE` | `true` | inject per-type compile guidance |
| `BRIEFING_CITATION_ALIAS` | `true` | alias real source ids to `sNN` handles in briefings |
| `WORKER_TENANTS` | (empty) | which tenants this worker drains, comma-separated user ids. Empty is every tenant — one worker over one stack, exactly as it has always behaved. It exists because one Postgres can carry more than one library and a library IS a tenant ([single-machine-edition](../design/single-machine-edition.md) §11.7): each library's engine process registers its own compile contract, so a worker claiming a neighbour's job would compile that knowledge under the wrong contract. The restriction is one predicate in the claim query, never a claim followed by a release — a job put back has still spent that tenant's single in-flight slot. The startup orphan sweep is bounded the same way: another engine's claimed job is that engine's work in flight, not an orphan of this one. Set, it is stated once in the worker's startup lines. Not an engine knob (deployment wiring) |
| `CORS_ALLOW_ORIGIN_REGEX` | `https?://(localhost\|127\.0\.0\.1)(:\d+)?` | empty string disables CORS entirely |

## Unprefixed (read directly)

| Variable | Meaning |
|---|---|
| `OPENROUTER_API_KEY` | shared by `openrouter:` chat and embedding specs — and by the Live Context supplementary web search (`LIVE_WEB_SEARCH`), which needs no second secret |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL` | tracing; if any is missing, tracing is a no-op |

## Scripts and compose only (not read by the service)

| Variable | Default | Used by |
|---|---|---|
| `PNEUMA_KNOWLEDGE_API_HOST` / `_API_PORT` | `127.0.0.1` / `18000` | `scripts/dev-api.sh` |
| `PNEUMA_KNOWLEDGE_PG_PASSWORD` / `_MEILI_KEY` | `pneuma_knowledge` / — | `infra/docker-compose.yml` |

## Owner profile provenance

`pkc profile show [--json]` reports every editable field and its provenance, and identifies the
placeholder. `pkc profile set --field display_name="Chen Wan" --provenance inferred` writes
values and markers to both `persona/profile.yaml` and the persisted profile. A YAML/JSON payload
can be supplied with `--file <path>`, `--file -`, or `-`. With no explicit marker, a process
carrying `PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH` writes `inferred`; other processes write `owner`.
`pkc profile confirm --field display_name` confirms that field alone; `--all` confirms every
editable field without changing their values.

The provenance map uses the same dotted names as `--field`, including `locale.timezone` and
`preferences.response_language`. Values are `inferred`, `owner`, or `placeholder`; existing
`profile`, `deployment_default`, and `unstated` values and the legacy locale keys remain readable.
A dotted entry takes precedence over its legacy alias. Inferred values are marked in the compile
system text, while an all-owner profile retains the historical rendering bytes. Draft opening
prints one notice for a placeholder or unconfirmed profile and still opens the round. Profile
edits never write canonical; substantive evidence enters through `pkc owner say`.
