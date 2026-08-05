# Configuration

**English** | [简体中文](configuration.zh-CN.md)

All framework settings are environment variables with the `PNEUMA_KNOWLEDGE_` prefix (a local `.env` is read; unknown keys are ignored). Names below drop the prefix. Copy [`.env.example`](../../.env.example) to start.

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
| `CANONICAL_ROOT` | `./data/canonical` | canonical store root (one repository per user); `/data/canonical` in the container image |

## Models

| Setting | Default | Meaning |
|---|---|---|
| `LLM_MODEL` | `openai:gpt-4o-mini` | base model spec and fallback for all roles |
| `LLM_MODEL_COMPILE` / `_RECALL` / `_DEEP` / `_SKILL` / `_EVOLVE` / `_LIVE_CONTEXT` / `_CHALLENGE` | empty | per-role overrides |
| `LLM_TIMEOUT` | `600` | seconds; guards against hangs, not slowness |
| `LLM_MAX_RETRIES` | `3` | transient-error retries (langchain) |
| `EMBEDDING_MODEL` | `fake:384` | `fake:<dim>` (deterministic, keyless) or `openrouter:<model>` |

Model spec forms: `scripted:<path>` (local replay, keyless — and it hard-overrides every role, so a scripted run is fully deterministic), `openrouter:<model>` (needs `OPENROUTER_API_KEY`), or any provider prefix `init_chat_model` understands (e.g. `anthropic:claude-sonnet-5`, `openai:gpt-4o-mini`). Role fallback is a single hop: `live_context → recall`, `evolve → compile`, `challenge → compile`, then `LLM_MODEL`.

## L2 chunking

| Setting | Default | Meaning |
|---|---|---|
| `CHUNK_STRATEGY` | `semantic` | `semantic` = LLM topic/episode boundary detection (compile-role model; falls back to `sentence` automatically under `scripted:` models); `sentence` / `recursive` = mechanical, zero LLM cost |
| `CHUNK_SIZE` | `768` | tokens; ~1 token/char for CJK |
| `CHUNK_OVERLAP` | `128` | tokens |

## Evolution and grooming

| Setting | Default | Meaning |
|---|---|---|
| `EVOLVE_AUTO_TRIGGER` | `true` | compile-driven evolution triggering |
| `EVOLVE_TRIGGER_TOPIC_DOCS` | `5` | new-document threshold (AND-ed with the next) |
| `EVOLVE_TRIGGER_NEW_CLAIMS` | `30` | new-claim threshold |
| `EVOLVE_DRAFT_TTL_HOURS` | `24` | draft lifetime |
| `ROLLOVER_THRESHOLD_CHARS` | `40000` | document size that enqueues a groom job; `0` disables |
| `ROLLOVER_KEEP_RECENT_CHARS` | `12000` | tail kept in the active document |
| `RECALL_CLAIM_CAP` | `64` | fast-recall claim budget per ask (release default inside the measured 40–80 sweet band; 80 = measured optimum when tokens are no object) |
| `RECALL_WINDOW_CAP` | `8` | fast-recall body-window budget per ask |
| `RECALL_PLAN_QUERIES` | `0` | `0` off; N>0 = one planning call derives up to N extra retrieval queries, pooled by one RRF fusion |
| `RECALL_RERANK_MODEL` | (empty) | empty off (default: measured no gain on claim-level retrieval); `llm` = LLM reranker on the recall model at reasoning effort `none` (default provider); `llm:<spec>` picks the model; a bare model name (e.g. `cohere/rerank-4-pro`) uses the OpenRouter `/rerank` endpoint |
| `RECALL_RERANK_CANDIDATES` | `120` | per-query/per-face retrieval depth when reranking; the reranker scores the full deduped union (hard cap 1000) |
| `RECALL_ANSWER_STYLE` | `conversational` | answer-style preset for fast/deep answers: `concise` = the bare exact value/phrase (graders, scripts), `conversational` = a natural chat reply, `detailed` = a self-contained written note. Shape only — truth discipline is style-independent. A recall request may override per call (`answer_style`) |

## Post-compile coverage challenge

| Setting | Default | Meaning |
|---|---|---|
| `CHALLENGE_ENABLED` | `false` | after each committed compile, run a coverage audit: blind question generation over the material, claim-face probing, reflection |
| `CHALLENGE_MAX_ROUNDS` | `2` | question/reflection rounds per audit (either stage can end early by declaring exhaustion) |
| `CHALLENGE_MAX_QUESTIONS` | `6` | questions per round |
| `CHALLENGE_COMPENSATE` | `true` | confirmed gaps enqueue one compensation compile (its writes pass the ordinary citation gate) |
| `LLM_MODEL_CHALLENGE` | empty | model for question generation and reflection; empty borrows the compile role |

The audit's judgement is extensible: its three prompts — `compile.challenge.questions_system`, `compile.challenge.reflect_system`, `compile.challenge.compensation_preamble` — live in the prompt catalog and can be replaced wholesale via `override_prompts` at startup, like any other model-visible wording.

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
| `OPENROUTER_API_KEY` | shared by `openrouter:` chat and embedding specs |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_BASE_URL` | tracing; if any is missing, tracing is a no-op |

## Scripts and compose only (not read by the service)

| Variable | Default | Used by |
|---|---|---|
| `PNEUMA_KNOWLEDGE_API_HOST` / `_API_PORT` | `127.0.0.1` / `18000` | `scripts/dev-api.sh` |
| `PNEUMA_KNOWLEDGE_PG_PASSWORD` / `_MEILI_KEY` | `pneuma_knowledge` / — | `infra/docker-compose.yml` |
