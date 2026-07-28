#!/usr/bin/env bash
# Start the pneuma-knowledge API for local development (M2 UI experiment bench).
#
# Serves the FastAPI app on 127.0.0.1:18000 with autoreload. The vite dev server
# (apps/web) proxies /v1 and /healthz here — see apps/web/vite.config.ts. Requires
# the compose stack up: `docker compose -f infra/docker-compose.yml up -d --wait`.
set -euo pipefail

cd "$(dirname "$0")/.."

HOST="${PNEUMA_KNOWLEDGE_API_HOST:-127.0.0.1}"
PORT="${PNEUMA_KNOWLEDGE_API_PORT:-18000}"

exec uv run uvicorn pneuma_knowledge_service.api.app:create_app \
  --factory --host "$HOST" --port "$PORT" --reload
