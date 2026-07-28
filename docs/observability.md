# Observability — Langfuse tracing

Every LLM / agent step in pneuma-knowledge-compiler can be traced to Langfuse without the core
package ever importing a tracing library. `pneuma-knowledge-core` depends only on langchain's
callback abstraction (architecture.md §2: core zero middleware deps); the service injects
a Langfuse `CallbackHandler` at the call sites. With no keys configured the whole thing
degrades to a byte-for-byte no-op.

## What is covered

Each traced core function threads a langchain `config` into every `model.invoke` /
`bind_tools(...).invoke`, carrying `callbacks`, `metadata`, and a `run_name`:

| Operation | `run_name` | Where | Notes |
|---|---|---|---|
| compile | `compile` | `compile/runner.py` `run_compile` | every turn of the tool loop (multi-round tool calls all traced) |
| fast recall | `recall.fast` | `recall/fast.py` `fast_recall` | one selector invoke |
| deep recall | `recall.deep` | `recall/deep.py` `deep_recall` | every turn of the bounded agentic tool loop (search_claims / search_content / fetch_verbatim) |
| briefing ask | `briefing.ask` | `recall/briefing.py` `briefing_ask` | every turn of the fetch_verbatim tool loop |

Injection points (service side, `pneuma-knowledge-service`):

- **compile worker** (`workers/compile_worker.py` `process_job`) — injects for `run_compile`.
- **API routes** (`api/routes/v1.py`) — inject for `recall` (fast/deep) and briefing `ask`.
- **examples** (`examples/briefing_e2e.py`) — inject for fast/deep/briefing calls; the
  compile examples trace through `drain_user`.

## Metadata schema (what you can filter by)

`wiring.llm_call_config(ctx, *, operation, user_id, extra)` produces
`{"callbacks": [...], "trace_metadata": {...}}`. Every trace's metadata carries:

| Key | Always | Value |
|---|---|---|
| `operation` | yes | logical op name (mirrors `run_name`, e.g. `compile`, `recall.fast`) |
| `user_id` | yes | the tenant id (invariant I1's first dimension) |
| `env` | yes | `local` |
| `app` | yes | `pneuma-knowledge-compiler` |
| `skill_version` | compile | e.g. `v1` (plus `skill_id`, `job_id`, `source_count`) |
| `snapshot_ref` | recall / briefing | the git snapshot sha (plus `briefing_id` for asks) |

langchain also folds in its own `ls_*` / `lc_versions` keys; ours sit alongside them.

## Trace-size discipline

**Never put a key or a slab of canonical body into metadata.** Metadata carries ids and
counts only (`user_id`, `snapshot_ref`, `source_count`, …) — enough to slice traces,
nothing that bloats them or leaks secrets. None-valued `extra` entries are dropped.
(The prompt/response bodies langchain sends as span content are the model I/O itself, not
metadata; keep our added metadata to identifiers.)

## Environment configuration

Three variables, read **unprefixed** (no `PNEUMA_KNOWLEDGE_`), matching the local Langfuse
project's own names (same convention as `OPENROUTER_API_KEY`):

- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_BASE_URL`

Set them in `.env` (or the process environment). Values are never logged or echoed.

## Keyless / degraded behavior

`wiring.build_langfuse_handler(settings)` returns `None` unless **all three** variables
are non-empty. When it returns `None`:

- `llm_call_config` yields `callbacks: []`;
- every core call site runs with `callbacks=[]` — identical to the pre-tracing path;
- `ctx.flush_traces()` is a no-op.

So the keyless test suite and any deployment without keys are unaffected. A partial
configuration (one or two of the three) is treated as **off**, not as an error.

## Flushing (short-lived processes)

Langfuse batches spans on a background thread; a process that exits promptly must flush or
lose the batch. `AppContext.flush_traces()` drains the client
(`langfuse.get_client().flush()`), and only when a handler was actually built during real
work (a pure-ingest context flushes nothing and touches no network):

- **compile worker** — flushes after every job (`drain_user`, in a `finally`).
- **examples** — flush on `ctx.close()` before exit.
- **API server** — long-lived; the background batch suffices, and `ctx.close()` flushes on
  shutdown.

## Design invariant

`pneuma-knowledge-core` never imports `langfuse` — its dependencies stay `pydantic` +
`langchain-core`. `langfuse` is a dependency of `pneuma-knowledge-service` only. The scripted /
fake keyless chat models go through langchain's standard `BaseChatModel.generate`, so the
injected callbacks fire on them exactly as on a real provider — no model-side change was
needed to make tracing work.
