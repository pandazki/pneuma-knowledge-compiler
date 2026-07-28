#!/usr/bin/env bash
# Start the pneuma-knowledge compile worker for local development (M3b).
#
# Single process, per-user serial: it drains the PG compile queue, runs run_compile
# against the git canonical layer, persists events, and marks sources digested.
# Requires the compose stack up and (for a keyless run) a scripted model:
#   PNEUMA_KNOWLEDGE_LLM_MODEL=scripted:/abs/path/to/script.json bash scripts/dev-worker.sh
# A real provider needs its key + e.g. PNEUMA_KNOWLEDGE_LLM_MODEL=anthropic:claude-sonnet-5.
set -euo pipefail

cd "$(dirname "$0")/.."

exec uv run python -m pneuma_knowledge_service.workers.compile_worker
