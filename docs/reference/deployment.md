# Deployment

**English** | [简体中文](deployment.zh-CN.md)

## Local development

Three middleware containers plus two host processes:

```bash
docker compose -f infra/docker-compose.yml up -d --wait   # Postgres, Qdrant, Meilisearch
bash scripts/dev-api.sh          # uvicorn on 127.0.0.1:18000, autoreload
bash scripts/dev-worker.sh       # compile worker (drains the job queue)
cd apps/web && pnpm dev          # Vite on :5173, proxies /v1 and /healthz to :18000
```

All containers bind loopback only, with healthchecks (so `--wait` works). Ports are deliberately offset from common defaults, and each runnable stack in the repository owns a disjoint port block:

| Stack | Compose project | Postgres / Qdrant / Meili | Extra |
|---|---|---|---|
| dev (this page) | `pneuma-knowledge-compiler` | 15432 / 16333 / 17700 | API 18000, Vite 5173 |
| generated projects (`scaffold/init.py`) | `pneuma-<name>-<hex>` | probed free at generation | |
| `examples/opc/` | `pneuma-opc-example` | 25432 / 26333 / 27700 | API 28000, web 24173 |

## Container image

One backend image, two tiers by command:

- **API tier** (default `CMD`): `uvicorn … --host 0.0.0.0 --port 8080`.
- **Worker tier**: override the command with `python -m pneuma_knowledge_service.workers.compile_worker`. Both are stateless; scale the API horizontally, run the worker as at least one replica (per-user job serialization is handled by the queue, not by replica count).

Two constraints are baked into the Dockerfile and are easy to trip over when building your own:

1. **Ship the whole repository and run via `uv run`.** The Postgres adapter locates `infra/schema.sql` relative to its own source path, so a bare-wheel install does not work — the source layout must survive into the image.
2. **The runtime needs the `git` binary** (the canonical adapter shells out), plus `git config --system --add safe.directory '*'` for volumes whose uid doesn't match the container user. Canonical data lives on a persistent volume at `PNEUMA_KNOWLEDGE_CANONICAL_ROOT=/data/canonical`.

Startup is deliberately fail-closed and network-dependent: `build_context()` creates the schema, probes the embedding dimension with one real embedding call, and connects to Meilisearch and Qdrant before serving anything — budget a generous startup window. The probed dimension is load-bearing: switching `EMBEDDING_MODEL` means a new collection name and a derived rebuild; mixed dimensions cannot share a collection.

## Web tier

`docker/web.Dockerfile` builds `apps/web` and serves it with nginx on 8080:

- `/v1/` and `/healthz` proxy to the API service; buffering is off and `proxy_read_timeout` is 600 s so deep-recall SSE streams survive.
- The Live Context WebSocket path (`/v1/users/*/live-context/ws`) has its own location with `proxy_read_timeout 3600s`.
- SPA history fallback for everything else; `/_nginx_health` is served locally.

The API also pings WebSocket clients (~30 s), which keeps intermediaries with idle timeouts (e.g. Cloudflare's ~100 s) from dropping live connections.

## Operations

- **Everything derived is rebuildable**: `scripts/ops/rebuild_derived.py <user-id>|--all` rebuilds L1 + L2 + the L3 projection from the two authoritative stores, with before/after accounting. Use after wiping or upgrading middleware, switching embedding models (new collection), or changing chunking.
- **Re-chunk only**: `scripts/ops/reindex_l2.py <user-id>` re-runs L2 chunking/embedding alone.
- **Job self-healing** is built in: on restart the worker re-queues jobs orphaned by a dead process; any exception completes the job as failed rather than wedging the per-user queue.
- **Tracing** (Langfuse) activates only when all three `LANGFUSE_*` variables are set; the worker flushes after every job.

