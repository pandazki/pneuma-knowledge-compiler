# Observability — Langfuse tracing

**English** | [简体中文](observability.zh-CN.md)

Every model call in the framework can be traced to Langfuse without `pneuma-knowledge-core` ever importing a tracing library. Core call sites accept langchain's `callbacks` + `trace_metadata`; the service builds a Langfuse `CallbackHandler` in [`wiring.py`](../../packages/pneuma-knowledge-service/src/pneuma_knowledge_service/wiring.py) and injects it. Unconfigured, the whole thing is a byte-for-byte no-op.

## Turning it on

Three **unprefixed** variables (same convention as `OPENROUTER_API_KEY`, so a Langfuse project's own variable names work verbatim), in `.env` or the process environment:

| Variable | Meaning |
|---|---|
| `LANGFUSE_SECRET_KEY` | project secret key |
| `LANGFUSE_PUBLIC_KEY` | project public key |
| `LANGFUSE_BASE_URL` | Langfuse host (e.g. `http://localhost:3000`) |

A scaffold project passes these variables into both the API and worker containers. For a
self-hosted Langfuse bound to the Docker host, keep the host-facing value unchanged and set
`PNEUMA_APP_LANGFUSE_BASE_URL_CONTAINER=http://host.docker.internal:<port>`. If that Langfuse
also signs media-upload URLs with `localhost`, set
`PNEUMA_APP_LANGFUSE_LOCALHOST_GATEWAY=host-gateway`; this explicit opt-in lets the
containers upload traced image attachments without rewriting credentials or signed URLs.

`build_langfuse_handler(settings)` returns a handler only when **all three** are non-empty; otherwise it returns `None`. Missing one is treated as **off, not as an error**: `llm_call_config` yields `callbacks: []`, every core call runs exactly as it did before tracing existed, and `flush_traces()` opens no socket. Values are never logged or echoed.

Because a partially configured trace looks identical to a working one until the spans turn out to be missing, treat the three variables as all-or-nothing in any paid pipeline.

Tracing is model-agnostic. Keyless `scripted:` / fake chat models go through langchain's ordinary `BaseChatModel` path, so injected callbacks fire on them exactly as on a real provider — **no model-side code was changed to make tracing work**, and a scripted replay produces real spans. (Embedding calls carry no callbacks; only chat-model and agent runs are traced.)

## What gets traced

`llm_call_config(ctx, operation=…, user_id=…, extra=…)` stamps the `operation` metadata key; core stamps a `run_name` on the langchain run. The two differ where one operation makes several distinct kinds of call.

| `operation` | `run_name`(s) | Triggered by | Spans per invocation |
|---|---|---|---|
| `compile` | `compile` | `compile` job in the worker (also the challenge compensation compile) | one per tool-loop turn — a job is N traces, joined by session |
| `compile.challenge` | `compile.challenge.questions`, `compile.challenge.reflect` | `challenge` job, enqueued after a committed compile when `CHALLENGE_ENABLED` | two per audit round (up to `CHALLENGE_MAX_ROUNDS`) |
| `compile.groom` | `compile.groom.overview` | `groom` job — a document past `ROLLOVER_THRESHOLD_CHARS` | one (the overview rewrite) |
| `chunk.semantic` | `chunk.semantic` | `index` job under `CHUNK_STRATEGY=semantic`, first ingest or a genuine content/model change only — a manifest replay calls no model | one per block window |
| `evolve.propose` | `evolve.propose` | `evolve` job, phase 1 | one structured call |
| `evolve.reorganize` | `evolve` | `evolve` job, phase 2 (same job as propose) | one per tool-loop turn |
| `recall.fast` | `recall.fast`, `recall.fast.select` | `POST /v1/users/{user_id}/recall` with `mode=fast` | one answer call, plus one selector call when the selector runs |
| `recall.deep` | `recall.deep` | `POST /v1/users/{user_id}/recall` `mode=deep`, and `POST …/recall/stream` | one root chain run per ask; every agent turn is a nested span |
| `briefing.ask` | `briefing.ask` | `POST /v1/users/{user_id}/briefings/{briefing_id}/ask` | same shape as deep — root chain run plus one nested span per turn |
| `profile.generate` | `profile.generate` | `POST /v1/profile/generate` | one structured call |
| `live_context.evaluate` | `recall.suggestion` | each Live Context evaluation (`…/live-context/ws` and `…/live-context/stream`) | one structured call per evaluation |
| `live_context.expand` | `live_context.expand` | Live Context `want_more` (card expansion) | one call |


Not traced today: `skill.derive` (the derive-pack inference) accepts `callbacks`/`trace_metadata`, but `skills.skill_for_user` calls `packs_for_profile` without them, so the call produces no spans; its spend is unattributed. Everything mechanical — ingest, L1/L2 writes, gates, projections, `evolve_adopt` reconciliation — makes no model call and therefore no trace.

## Metadata (what you can filter by)

`llm_call_config` returns `{"callbacks": [...], "trace_metadata": {...}}`. Four keys are always present:

| Key | Value |
|---|---|
| `operation` | the logical operation name from the table above |
| `user_id` | the tenant id (invariant I1's first dimension) |
| `env` | `local` (a constant today, not yet a setting) |
| `app` | `pneuma-knowledge-compiler` |

Per-operation additions (`extra`; `None`-valued entries are dropped, so an absent value never becomes a `null` facet):

| Operation | Extra keys |
|---|---|
| `compile` | `skill_version`, `skill_id`, `job_id`, `source_count`, `image_count`, `image_mode` |
| `compile.challenge` | `job_id` |
| `compile.groom` | `job_id`, `document_path`, `volume_path`, `archived_claims`, `skill_version` |
| `evolve.propose` | `skill_version` |
| `evolve.reorganize` | `task_id`, `skill_version` |
| `recall.fast` | `snapshot_ref`, `kb_snapshot_id`, `image_count`, `image_mode` (answer call) |
| `recall.deep` | `snapshot_ref`, `kb_snapshot_id` |
| `briefing.ask` | `snapshot_ref`, `briefing_id` |
| `live_context.evaluate` | `focus`, `briefing_id` |
| `chunk.semantic`, `profile.generate`, `live_context.expand` | none |

langchain folds in its own `ls_*` / `lc_versions` keys; ours sit alongside them.

## Sessions (grouping a multi-round loop)

Every `invoke` inside a tool loop creates its own root trace, so a compile job's rounds would land as N unrelated traces. `llm_call_config` therefore synthesizes langchain-Langfuse's reserved metadata keys:

- `langfuse_session_id = f"{operation}:{session}"`, where `session` is the **first present** of `job_id`, `briefing_id`, `snapshot_ref`. No such key in `extra` ⇒ no session id.
- `langfuse_user_id = user_id`, always.

Consequences worth knowing: `briefing.ask` groups by `briefing_id` (not `snapshot_ref`, which is also present but later in the order); `recall.fast` / `recall.deep` group by `snapshot_ref`, so all asks against one snapshot share a session; `evolve.reorganize` has `task_id` — which is *not* a session key — so its rounds get no session; `kb_snapshot_id` is likewise never a session key. Both keys are additive and inert when tracing is off.

## Trace-size discipline

**Metadata carries ids, counts and bounded mode enums only — never a key, never a slab of canonical body.** `user_id`, `job_id`, `snapshot_ref`, `source_count`, `archived_claims`, `image_mode`: enough to slice traces, nothing that bloats them or leaks a secret. The prompt and response bodies langchain reports as span content are the model I/O itself, not metadata; keep our added metadata to identifiers and finite machine states. If an `extra` value is prose a human would read, it does not belong there.

## Flushing, by process type

The Langfuse SDK batches spans on a background thread, so a process that exits promptly must flush or lose the batch. `AppContext.flush_traces()` drains the client (`langfuse.get_client().flush()`, wrapped in `to_thread` because the SDK is synchronous). It does **not** force-build the handler: a context that never ran a traced call flushes nothing and touches no network.

| Process | Flush |
|---|---|
| Worker | after **every** job, in a `finally` (`drain_user`, `drain_index_jobs`) — a sweep may exit right after, so the background batch is never relied on |
| API server | long-lived; the background batch suffices, and the lifespan shutdown calls `ctx.aclose()` → `flush_traces()` |
| Scripts / examples | explicit `await ctx.flush_traces()` (or `aclose()`) before exit |
| Pure ingest | no model call ⇒ no handler ever built ⇒ nothing flushed, no network touched |

## Design invariant

`pneuma-knowledge-core` never imports `langfuse` — its dependencies stay pydantic + langchain-core + langchain (architecture.md §2). `langfuse` is a dependency of `pneuma-knowledge-service` only, imported lazily behind `wiring._import_langfuse()` so the keyless path never loads it.
