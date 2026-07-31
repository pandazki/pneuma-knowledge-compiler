# pneuma-knowledge-compiler — one image, command-differentiated (uvicorn API / compile worker).
#
# Two constraints drive the shape of this file:
#   1. adapters/postgres.py resolves infra/schema.sql via Path(__file__).parents[5],
#      i.e. it assumes the packages/pneuma-knowledge-service/src/... source layout at RUNTIME.
#      So we copy the whole repo and run via `uv run` — never a bare wheel install.
#   2. The canonical store shells out to `git`, so the git binary must exist in runtime.
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependency layer — cached until the lockfile changes.
COPY pyproject.toml uv.lock ./
COPY packages/pneuma-knowledge-core/pyproject.toml packages/pneuma-knowledge-core/
COPY packages/pneuma-knowledge-service/pyproject.toml packages/pneuma-knowledge-service/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-install-project

# Source (includes infra/schema.sql and runnable example/ops modules).
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --all-packages

FROM python:3.12-slim AS runtime
# git: canonical per-user repos are written via `git` subprocess (adapters/git_canonical.py)
# curl/ca-certificates: probes + OpenRouter TLS
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY --from=base /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    PNEUMA_KNOWLEDGE_CANONICAL_ROOT=/data/canonical

# git refuses to operate on a repo owned by another uid (PVC mounts). Demo-scope fix.
RUN git config --system --add safe.directory '*' \
    && git config --system user.email "worker@pneuma-knowledge.local" \
    && git config --system user.name "pneuma-knowledge worker"

EXPOSE 8080

# Default = API tier. The worker tier overrides `command:` with:
#   python -m pneuma_knowledge_service.workers.compile_worker
CMD ["uvicorn", "pneuma_knowledge_service.api.app:create_app", "--factory", \
     "--host", "0.0.0.0", "--port", "8080"]
