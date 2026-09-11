# Deployment

**English** | [简体中文](deployment.zh-CN.md)

## Local development

Four middleware containers plus two host processes:

```bash
docker compose -f infra/docker-compose.yml up -d --wait   # Postgres, Qdrant, Meilisearch, RustFS
bash scripts/dev-api.sh          # uvicorn on 127.0.0.1:18000, autoreload
bash scripts/dev-worker.sh       # compile worker (drains the job queue)
cd apps/web && pnpm dev          # Vite on :5173, proxies /v1 and /healthz to :18000
```

All containers bind loopback only, with healthchecks (so `--wait` works). Ports are deliberately offset from common defaults, and each runnable stack in the repository owns a disjoint port block:

| Stack | Compose project | Postgres / Qdrant / Meili / RustFS | Extra |
|---|---|---|---|
| dev (this page) | `pneuma-knowledge-compiler` | 15432 / 16333 / 17700 / 19000 | API 18000, Vite 5173; RustFS console 19001 |
| generated projects (`scaffold/init.py`) | `pneuma-<name>-<hex>` | all probed free at generation | RustFS console also probed |
| `examples/opc/` | `pneuma-opc-example` | 25432 / 26333 / 27700 / 29000 | text-only example; API 28000, web 24173; RustFS console 29001 |

## Container image

One backend image, two tiers by command:

- **API tier** (default `CMD`): `uvicorn … --host 0.0.0.0 --port 8080`.
- **Worker tier**: override the command with `python -m pneuma_knowledge_service.workers.compile_worker`. Both are stateless; scale the API horizontally, run the worker as at least one replica (per-user job serialization is handled by the queue, not by replica count).

Two things are baked into the Dockerfile and are easy to trip over when building your own:

1. **The image ships the whole repository and runs via `uv run`.** One option rather than a requirement: the service wheel now carries the bootstrap schema inside the package (`pneuma_knowledge_service/infra/schema.sql`), and the Postgres adapter reads that packaged copy first, falling back to `infra/schema.sql` in a source checkout. So an installed edition works too; ship the repository when you want the checkout layout — tests, ops scripts, compose files — to survive into the image.
2. **The runtime needs the `git` binary** (the canonical adapter shells out), plus `git config --system --add safe.directory '*'` for volumes whose uid doesn't match the container user. Canonical data lives on a persistent volume at `PNEUMA_KNOWLEDGE_CANONICAL_ROOT=/data/canonical`.

Startup is deliberately fail-closed and network-dependent: `build_context()` creates the schema, probes the embedding dimension with one real embedding call, and connects to Meilisearch and Qdrant before serving anything — budget a generous startup window. The S3 client is lazy; the first image import creates or verifies its private bucket, while compose health still keeps RustFS ready before the stack reports healthy. The probed dimension is load-bearing: switching `EMBEDDING_MODEL` means a new collection name and a derived rebuild; mixed dimensions cannot share a collection.

## Web tier

`docker/web.Dockerfile` builds `apps/web` and serves it with nginx on 8080:

- `/v1/` and `/healthz` proxy to the API service; buffering is off and `proxy_read_timeout` is 600 s so deep-recall SSE streams survive.
- The Live Context WebSocket path (`/v1/users/*/live-context/ws`) has its own location with `proxy_read_timeout 3600s`.
- SPA history fallback for everything else; `/_nginx_health` is served locally.

The API also pings WebSocket clients (~30 s), which keeps intermediaries with idle timeouts (e.g. Cloudflare's ~100 s) from dropping live connections.

## Operations

- **Everything derived is rebuildable**: `scripts/ops/rebuild_derived.py <user-id>|--all` rebuilds L1 + L2 and the projections above them from the substrate each declares — the two authorities (L0 spans Postgres and S3; canonical is Git), and for a use-side projection the kept consultation records — with before/after accounting. Records are kept rather than re-derived: a rebuild replays them and leaves them untouched. Use after wiping or upgrading middleware, switching embedding models (new collection), or changing chunking.
- **Re-chunk only**: `scripts/ops/reindex_l2.py <user-id>` re-runs L2 chunking/embedding alone.
- **Job self-healing** is built in: on restart the worker re-queues jobs orphaned by a dead process; any exception completes the job as failed rather than wedging the per-user queue. A coding-agent draft that a dead launch left holding work is kept with its re-queued job, and the next launch continues it instead of starting over. The same sweep also runs on a clock while the worker works (`WORKER_SELFHEAL_S`, 60 s; `0` turns it off), skipping the claims that worker is running, so a claim nobody can account for comes back within a minute instead of at the next process start.
- **Infrastructure outages do not stop the engine.** When Postgres, Qdrant, Meilisearch or RustFS drops or restarts, the worker logs one line (`[compile-worker] infrastructure unavailable (postgres: <reason>); retrying in 2s`). It backs off from 2 s, doubling to 60 s, probes the service that failed, and resumes once the service answers (`… infrastructure back after Ns; resuming (job <id> requeued)`). **A claim outlives no outage**: the job the worker was holding goes back on the queue whatever raised between claiming it and completing it — its round, or the derived work that follows one — and if that job's work had already finished, its completion is written instead. Either way the job is neither lost nor run twice, and the resume line always names what became of it (`(job <id> requeued)`, `(job <id> completed)`, `(no job in flight)`). A transport error that reaches the worker without its client's wrapper is the same fact and is treated as one (`http: <reason>`, every peer probed, because a bare one does not say which went away). A job that does fail for its own reasons always says so: the row carries the exception's message, or its class when it has none (`worker error: httpx.ReadError`), and the worker log carries the traceback with the lane and job id. Meanwhile the API answers affected requests with `503 {"code": "infrastructure_unavailable"}` and recovers without a restart, because the Postgres pool checks every connection before handing it out. If a worker is stopped by an outage outside its drain, the engine restarts it in place (`[engine] worker stopped: …; restarting in Ns`) and keeps serving the API. Each Postgres connection names its process role in `application_name` (`pkc-engine-api`, `pkc-engine-worker`, `pkc-api`, `pkc-worker`, `pkc-cli:<command>`), unless the DSN or `PGAPPNAME` already sets one.
- **Tracing** (Langfuse) activates only when all three `LANGFUSE_*` variables are set; the worker flushes after every job.
