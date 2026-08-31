# Configuration

**English** | [简体中文](configuration.zh-CN.md)

All framework settings are environment variables with the `PNEUMA_KNOWLEDGE_` prefix (a local `.env` is read; unknown keys are ignored). Names below drop the prefix. Copy [`.env.example`](../../.env.example) to start.

One optional layer sits between environment and default: the **engine directory** (`ENGINE_DIR`, [architecture §11](../architecture.md#11-the-engine-directory)). Precedence is **process env > engine file > framework default**, and it is enforced at settings assembly: the engine file's values reach `Settings` only for keys `os.environ` leaves unstated. Two consequences worth knowing: an entry present-but-empty in the environment is still an environment-level statement, and a value from a `.env` FILE is not process env, so it ranks BELOW the engine file. `ENGINE_DIR` unset (the default) means the whole layer does not exist and every setting resolves exactly as it did before the concept.

## Required

| Setting | Meaning |
|---|---|
| `USER_SCHEMA_BASE_VERSION` | The compile-contract version this deployment registered via `register_skill_base`. Deliberately has no default: the framework carries no domain contract, so the deployment must declare its own — an empty value fails loudly on the first compile. |

## Storage and middleware

| Setting | Default | Meaning |
|---|---|---|
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
| `ENGINE_DIR` | (empty) | the engine directory: one versioned unit holding this deployment's strategy files, compile contract, prompt overlays and owner profile ([architecture §11](../architecture.md#11-the-engine-directory), [design](../design/engine-console.md)). Empty = the deployment has none: zero behavior change, and `/v1/engine/*` returns 404. Set it and those four routes serve the directory; every strategy setting below that the directory states resolves from it unless the process environment says otherwise |

## Models

| Setting | Default | Meaning |
|---|---|---|
| `LLM_MODEL` | `openrouter:openai/gpt-5.6-luna` | base model spec and fallback for all roles |
| `LLM_MODEL_COMPILE` / `_RECALL` / `_ANSWER` / `_DEEP` / `_SKILL` / `_EVOLVE` / `_LIVE_CONTEXT` / `_CHALLENGE` / `_BRIEF` | empty | per-role overrides; `answer` is only the final fast-answer generation and otherwise borrows `recall` |
| `ANSWER_REASONING_EFFORT` | empty | reasoning effort sent only on the final fast-answer call; empty preserves the provider default. Generated projects state `high` explicitly |
| `LLM_TIMEOUT` | `600` | seconds; guards against hangs, not slowness |
| `LLM_MAX_RETRIES` | `3` | transient-error retries (langchain) |
| `EMBEDDING_MODEL` | `fake:384` | `fake:<dim>` (deterministic, keyless) or `openrouter:<model>` |
| `COMPILE_CALL_TIMEOUT` | `600` | seconds a single model call inside a compile job (tool loop, repair round, post-compile brief) may take. Sits above `LLM_TIMEOUT`, the provider-client guardrail: a hung connection otherwise holds the job `claimed` until the worker restarts; on timeout the job completes as failed and canonical is untouched. `0` = no timeout. Engine key: `models.compile_call_timeout` |
| `COMPILE_MAX_TOOL_CALLS` | `0` | tool calls ONE round of a compile may spend — the first round and its repair round alike. `0` is not unbounded: it means the number is derived from the job, `max(40, 3 x sources)`, because a first round must be able to read every supplied source and append at least twice per source (a fixed 40 cut a 36-source day group mid-append on a real rebuild and cost 14 day groups their place in the library). Any value > 0 is used as the absolute ceiling. The repair round is never handed what the first round left over: it gets its own fresh allowance, `max(12, 3 x violations)`, capped by this same number — one knob bounds both rounds. Engine key: `models.compile_max_tool_calls` |
| `OVERVIEW_BUDGET_CHARS` | `2000` | characters a canonical document's overview region may occupy — the bounded head a compile rewrites whole when the picture of the subject changed. Over it, the `rewrite_overview` tool refuses the call and the compile gate rejects the round: it is a head, not a second ledger. Engine key: `models.overview_budget_chars` |
| `OVERVIEW_REQUIRED_AFTER_CLAIMS` | `8` | ledger claims a document may hold before a compile that TOUCHES it must give it an overview (`definition` at least) — the floor under the budget above. `finish_compile` refuses first and the gate refuses after, naming the page and its claim count; pages the round never touched are not judged. A model maintains a head that exists and does not start one (measured: 41 of 85 pages on a real library had none, some at 20–31 claims). `0` disables it. Engine key: `models.overview_required_after_claims` |
| `COMPILE_IMAGE_MODE` | `auto` | `caption` = labelled caption/OCR only; `native` = derived text plus actual image blocks; `auto` = use the compile model profile, falling back to `caption` when unknown. Engine key: `models.image_mode` |

Model spec forms: `scripted:<path>` (local replay, keyless — and it hard-overrides every role, so a scripted run is fully deterministic), `openrouter:<model>` (needs `OPENROUTER_API_KEY`), or any provider prefix `init_chat_model` understands (e.g. `anthropic:claude-sonnet-5`, `openai:gpt-5.6-luna`). Role fallback is a single hop: `answer → recall`, `live_context → recall`, `live_discover → recall`, `live_pick → recall`, `evolve → compile`, `challenge → compile`, `brief → compile`, then `LLM_MODEL`.

Two of those roles are the full-scope Live Context lane's, and they exist because that lane is two small calls per tick rather than one large one (architecture §7). `LLM_MODEL_LIVE_DISCOVER` (engine key `models.live_discover`) runs stage ① — it reads the pending conversation and decides whether the tick retrieves at all — and wants a **small reasoning** model: its output is a few dozen tokens and what it needs is fast judgement about a conversation. `LLM_MODEL_LIVE_PICK` (engine key `models.live_pick`) runs stage ③ — choose one of the already-assembled candidate cards or none, write one short lede, prune the citations, score it — and wants a **weak fast** model, because there is nothing to reason about: the evidence is in front of it and it may not rewrite a word of it. The generated engine names `openrouter:openai/gpt-5.6-sol` and `openrouter:openai/gpt-5.6-luna` respectively; both empty borrows `recall`, which keeps an existing deployment working unchanged. Their reasoning effort is **pinned in the framework** (`low` for discover, off for pick) and is deliberately not a knob: an effort a deployment could raise would change what the lane costs per tick, and cheapness is the whole argument for spending a call before retrieving rather than after. `LLM_MODEL_LIVE_CONTEXT` still routes the briefing-scope round and the card expansion, which are one call each and unchanged. The scaffold keeps retrieval planning/glance on standard Luna and sends only the final answer to Luna Pro at explicit `high` effort.

Beside those three there is a fourth, optional model on the same lane: `LIVE_WEB_SEARCH` (engine key `models.live_web_search`, default `false`) opens a **supplementary** internet face beside the library, and `LIVE_WEB_SEARCH_MODEL` (engine key `models.live_web_search_model`, default `openai/gpt-5.6-luna`) names the OpenRouter model that serves it, with that provider's own native web search behind it. It reuses `OPENROUTER_API_KEY` — no second secret — and with no key the search reports itself unavailable and the `web` lookup is never offered, whatever the flag says. Enabling it here opens the possibility rather than turning it on: **both** the deployment and the individual connection must say yes before the discover contract even advertises the lookup, and the `ready` frame echoes what was granted rather than what was asked (see [http-api.md](http-api.md)). It bills per search, and what the searches cost rides the tick record.

`native` is an explicit assertion that the selected model and routed provider accept LangChain image content blocks; an incompatible provider fails instead of silently flattening the image. `caption` requires the importer to supply labelled `caption`/`ocr` representations and never claims that the compile model saw the original. `auto` recognizes the full GPT-5.6 family on direct OpenAI and OpenRouter routes as native-image capable even when a gateway omits LangChain's model profile; other unknown profiles stay on the conservative `auto → caption` path.

## L2 chunking

| Setting | Default | Meaning |
|---|---|---|
| `CHUNK_STRATEGY` | `semantic` | `semantic` = one compile-role call returns topic/episode boundaries plus a grounded title/description for L2 retrieval and derived answer context (falls back to `sentence` under `scripted:` models); `sentence` / `recursive` = mechanical, zero LLM cost |
| `SEMANTIC_OVERLAP` | `smart` | `semantic` only. `smart` = the model returns closed block intervals, so a hinge block belongs to both neighbouring segments; `off` = the original zero-overlap cut |
| `CHUNK_SIZE` | `768` | maximum embedding-unit size after semantic boundary detection; tokens, ~1 token/char for CJK |
| `CHUNK_OVERLAP` | `128` | tokens |

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

Which of the three to run for a given business, what `deliberation` and the two reasoning-effort knobs are worth, and one measured latency/cost/breadth comparison: [guides/recall-strategies.md](../guides/recall-strategies.md).

## Prompt language

| Setting | Default | Meaning |
|---|---|---|
| `PROMPT_LANGUAGE` | `en` | which language the FRAMEWORK's own prompt clauses arrive in: `en` = the English catalog, `zh` = core's Chinese language pack (`prompts.lang_zh.chinese_overlay()`, every catalog key translated with the same placeholders). Applied as an overlay UNDER a deployment's own overlays, so a hand-written clause always wins over the pack. `en` registers no overlay at all, so it is byte-for-byte the pre-language-pack behavior |

It changes the prose the models read, and nothing else — no policy, no mechanism, no
placeholder contract. In particular it does **not** decide what language a knowledge base is
written in: that follows the subject's own declared language (`compile.owner_env.write_language`).

**English is the baseline.** Every measurement published in this repository was taken on the
English catalog. The Chinese pack exists for readability and for fitting a Chinese material
domain; its scoring equivalence is unverified. See [engine console design](../design/engine-console.md#the-language-pack).

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
| `BRIEF_ENABLED` | `false` | after each committed compile, one model call narrates the compile's mechanical claim events into a short brief, stored on the job row and shown on the History timeline (labelled derived) |
| `LLM_MODEL_BRIEF` | empty | model for the narration; empty borrows the compile role |

The brief's only input is the mechanical record — the claim events derived from the diff plus the per-source provenance sentences — never the compile conversation, so there is nothing beyond the record for it to narrate. It is display copy, not knowledge: no citations, no canonical write, and a generation failure degrades to no brief rather than a failed job. Its prompts (`compile.brief.system`, `compile.brief.task`) live in the prompt catalog like any other model-visible wording.

## Index components

| Setting | Default | Meaning |
|---|---|---|
| `COMPONENTS` | empty | comma-separated names of enabled index components (architecture §6); empty = none. Shipped: `people`, `time` |
| `PEOPLE_FAMILY` | `memory/people/{slug}.md` | the contract path template the `people` component binds to — one of the skill's `path_templates` |
| `RECALL_COMPONENT_PATHS` | `true` | fast lane: when enabled components offer lookup paths, one routing tool-call turn chooses which run (architecture §7). No path offered = no routing call. `false` ignores component paths |
| `RECALL_COMPONENT_BUDGET_CHARS` | `6000` | character ceiling on the whole component face. A path's own cap bounds item counts; this bounds the context they may occupy. Over it, the lowest-ranked items fall off and long excerpts are cut at block boundaries — both stated in the face, never silent |

The first two live in the engine directory's `engine.yaml`, the two recall knobs in `recall/recall.yaml`. The full design — what a component is, the faces it may fill, and how to write one — is [design/index-components.md](../design/index-components.md). Enabling a component adds its gate checks, its outline lines and its tools on the next process start; disabling it removes them and leaves canonical untouched — a component holds no knowledge, only structure derived from L0 and canonical. With `people` on, person pages carry `identities` (`scheme:value`; `mailto:` / `im:` / `meeting:` as the source contracts record them) and `aliases` as comma-separated frontmatter. Both belong to the document's overview and are written whole with it (`rewrite_overview(fields=…)` / `set_fields`) — a snapshot, never only-growing. Three facts about them are refused mechanically at the write face and again at the gate, over the pages a round **touched** — body or frontmatter differs from what it held at the head of the round, or the page is new (`people.identity_shape`, `people.identity_duplicate`, `people.identity_cospeakers`, `people.alias_collision`): an identity is `scheme:value` and is bound by at most one page; two person ids that both SPEAK in one conversation are two people, so one page may not bind both — an IM `sender_id` and a meeting `speaker_id` are person ids, an email address is not (one human writing from two addresses is ordinary, and `email/v1` establishes no equivalence between them), so email threads contribute no co-speaking evidence; and an alias is not somebody else's name (another person page's alias, title or slug, or a display name the sources record for an identity this page does not hold). A fourth rule is a decision rather than a fact, and it is asked ONCE: every address term the library reports for a person this compile's sources carry must end the round either recorded in that page's `aliases` or declined with `decline_alias(path, term, reason)`. A decline writes nothing — no claim, no alias, no field, nothing on the page — because canonical records what is known about a person, not the names that are not theirs; it answers the round that calls it and is stored nowhere. What closes the question is the page being WRITTEN, judged on two derived facts: the projection's `reported_since` (the day the term → identity pair first crossed the reporting bar) against the day canonical last committed that page (`written_on`, one `git log` walk bounded to the family). A page committed on or after that day has been shown the question and is never asked again, whatever it decided; a page created this round, or a projection row from a library that predates the column, has no date — and both unknowns mean ask. So a round that declines and writes nothing is asked again next round, which is correct: nothing was committed, so nothing was answered. A fifth kind belongs to no page: `people.not_ready` refuses a round whose library-wide mirror could not be loaded, because judging those facts against an empty library would allow exactly the writes they exist to refuse — nothing is written and the next compile reads again. There are two such mirrors and each is demanded only by the round that needs it: the source boundary (required when this round wrote a person page declaring these fields, or its sources carry an identity) and the address-term projection (required only when a term decision applies), so a topic-only compile is not refused by a projection outage it asks nothing of. One further operational note: while any component is enabled, one compile runs per process at a time (the framework holds a lock from `prepare` to the end of the job), so a deployment scales compiles by adding worker processes rather than by running them concurrently in one. The compile model gets `find_person` and `decline_alias`; deep recall gets `enumerate_identities`, computed on demand over the user's L0 source metadata, and `person_profile(alias, identity, section, offset, limit)`. Both fast paths return everything they know — the whole page, the whole range — and the framework orders that against the question before spending the path's cap on it (architecture §7); both deep tools paginate and end every response with the exact call that fetches the rest, because a cap in an agentic lane must never be a dead end. `people` also keeps a persisted projection (PG `component_people_terms`): one row per **address term → target identity** pair read off turn structure, with its library-wide support. A term is reported for a target only when it has enough support, from more than one source, and that target holds most of the term's total — concentration, not frequency, which is what separates a nickname from any short phrase before a comma. Reported terms appear under each source in the compile task with their whole distribution and beside each identity in `enumerate_identities`; a term this source repeats but the library cannot yet back is labelled *emerging*. A third, weaker line lists the repeated name-shaped tokens of a source that match no present identity, with no target attached — the mentions no turn structure can point at anybody. The rows accumulate as sources are indexed, so a re-index without a rebuild counts a source twice — `scripts/ops/rebuild_derived.py` re-derives the table from L0 exactly. Each row also carries `reported_since`, the day that pair first crossed the reporting bar — the clock the one-time alias decision runs on, written once, never moved, and re-derived by the same rebuild (a row from a library that predates the column has none, and is asked about until a rebuild fills it). One table is all it keeps: an earlier pre-release build also created `component_people_decisions`, which nothing reads or writes any more (nothing stores a decline at all now) and which `infra/schema.sql` deliberately does NOT drop — the schema is applied on every process start, and a bootstrap that only creates is one a restart can never destroy data with. Drop it by hand once you have looked at it: `DROP TABLE IF EXISTS component_people_decisions;`.

With `time` on, the component keeps a persisted projection (PG `component_time_blocks`): one row per L0 block, holding the block's UTC instant and the calendar day it falls on **in the subject's timezone** — the same day ingest wrote into the block's section, never the UTC date, because for a subject at +08:00 everything sent between 00:00 and 08:00 local carries the previous UTC date. Each row also records the zone it was normalized under and where that zone came from (`DEFAULT_TIMEZONE`, the profile, or a registered provider), so changing a subject's timezone never silently mixes two calendars: existing rows keep saying what they were built from, and `scripts/ops/rebuild_derived.py` re-derives them explicitly. Fast recall gets a `timespan(since, until)` path, deep recall gets `timeline(since, until, granularity, offset, limit)` — `granularity="verbatim"` reads ONE day block by block instead of digesting it — and `as_of(date, alias, identity)`, and the compile task gets one line per source stating its span in the owner's day and clock (plus the source's own zone when the two differ). Every date argument is an ISO `YYYY-MM-DD` day in the subject's zone: the component never parses natural-language time — the routing turn, which sees `as_of` and the subject's zone, resolves "last quarter" into ISO days first, and a non-ISO argument becomes an `invalid_args` row in the answer's audit trail rather than a quietly different range.

## Behavior switches

| Setting | Default | Meaning |
|---|---|---|
| `DEFAULT_TIMEZONE` | `UTC` | calendar-day zone when the profile doesn't state one |
| `USER_SCHEMA_PACKS` | `true` | per-user schema-pack composition |
| `USER_SCHEMA_MATRIX_PATH` | unset | deployment pack-matrix JSON; unset uses the built-in |
| `CONTEXT_STREAM_RENDER_ROLES` | `true` | render owner/participant labels at ingest |
| `CONTEXT_STREAM_COMPILE_GUIDANCE` | `true` | inject per-type compile guidance |
| `BRIEFING_CITATION_ALIAS` | `true` | alias real source ids to `sNN` handles in briefings |
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
