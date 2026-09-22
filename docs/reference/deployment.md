# Deployment

**English** | [简体中文](deployment.zh-CN.md)

## Local development

Use Python 3.12, uv, Docker, Node 18+ and pnpm. From the repository root:

```bash
uv sync --all-packages
cp .env.example .env             # configure the chosen models and contract; never commit .env
docker compose -f infra/docker-compose.yml up -d --wait
cd apps/web && pnpm install
```

Run these in three terminals, each starting at the repository root:

```bash
bash scripts/dev-api.sh          # API on 127.0.0.1:18000, autoreload
bash scripts/dev-worker.sh       # worker: canonical and derived job lanes
cd apps/web && VITE_ENGINE_FIXTURES=false pnpm dev  # Vite on :5173
```

The flag connects Engine Console to the actual engine; without it that view uses bundled fixtures. Other views use the API. For a managed single-machine installation, use the [personal edition](../../personal/README.md).

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

Only the engine's own processes create the schema: the bootstrap batch is DDL (`CREATE INDEX IF NOT EXISTS` takes a ShareLock on its table even when the index is already there), so every other process — every `pkc` command, every `scripts/ops/` command — instead reads the `schema_applied` marker row, which holds the sha256 of the schema text that was last applied, and runs the batch only when that hash is not this build's (a fresh database, or an upgrade before the engine restarted).

Startup applies the database schema and assembles the configured adapters. With semantic retrieval enabled, normal engine startup probes the embedding dimension and ensures the Qdrant collection; a `fake:<dim>` embedding is local and keyless. `SEMANTIC_RETRIEVAL=off` skips embeddings and Qdrant. The S3 client is lazy: the first image import creates or verifies its private bucket. Switching embedding models requires a compatible collection and a derived rebuild; different dimensions cannot share a collection. See [configuration](configuration.md).

## Web tier

`docker/web.Dockerfile` builds `apps/web` and serves it with nginx on 8080:

- `/v1/` and `/healthz` proxy to the API service; buffering is off and `proxy_read_timeout` is 600 s so deep-recall SSE streams survive.
- The Live Context WebSocket path (`/v1/users/*/live-context/ws`) has its own location with `proxy_read_timeout 3600s`.
- SPA history fallback for everything else; `/_nginx_health` is served locally.

Live Context sends periodic WebSocket pings. Steward chat also requires WebSocket upgrade forwarding; the bundled `docker/nginx.conf` currently has a dedicated upgrade location only for Live Context, so extend your deployment proxy for `/v1/users/*/steward` before exposing that view through it. The Vite proxy and personal engine already support this route.

## Operations

- **Everything derived is rebuildable**: `scripts/ops/rebuild_derived.py <user-id>|--all` rebuilds L1 + L2 and the projections above them from the substrate each declares — the two authorities (L0 spans Postgres and S3; canonical is Git), and for a use-side projection the kept consultation records — with before/after accounting. Records are kept rather than re-derived: a rebuild replays them and leaves them untouched. Use after wiping or upgrading middleware, switching embedding models (new collection), or changing chunking.
- **Re-chunk only**: `scripts/ops/reindex_l2.py <user-id>` re-runs L2 chunking/embedding alone.
- **Job recovery**: orphaned claims are re-queued on restart and by a periodic sweep (`WORKER_SELFHEAL_S`, default 60 s; `0` disables it). A retained coding-agent draft travels with its job so the next launch can continue it.
- **Retry, pause, resume**: recoverable failures wait 1 minute, 5 minutes, 15 minutes, 1 hour, 4 hours and 24 hours between attempts, then pause. Fix the reported cause and use `pkc jobs resume --job JOB_ID`. Explicit terminal errors, such as a missing source or unsupported job kind, fail without retry. Inspect `pkc jobs` for the reason and state.
- **Infrastructure outages**: the worker probes failed services with a 2–60 second backoff, records whether its in-flight job was re-queued or completed, and resumes when they return. Repeated interruption of a job enters its retry schedule. The API returns `503 {"code": "infrastructure_unavailable"}` for affected requests and can recover without restart. Connection `application_name` identifies the process role unless explicitly overridden.
- **Tracing** (Langfuse) activates only when all three `LANGFUSE_*` variables are set; the worker flushes after every job.
