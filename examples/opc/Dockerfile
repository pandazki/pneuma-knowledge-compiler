FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
COPY packages/pneuma-knowledge-core/pyproject.toml packages/pneuma-knowledge-core/
COPY packages/pneuma-knowledge-service/pyproject.toml packages/pneuma-knowledge-service/
COPY packages/pneuma-knowledge-eval/pyproject.toml packages/pneuma-knowledge-eval/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --all-packages --no-install-project

COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --all-packages

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    PNEUMA_KNOWLEDGE_CANONICAL_ROOT=/data/canonical

RUN git config --system --add safe.directory '*' \
    && git config --system user.email "opc-example@pneuma.local" \
    && git config --system user.name "Pneuma OPC example"

EXPOSE 8080
CMD ["uvicorn", "examples.opc.api:app", "--host", "0.0.0.0", "--port", "8080"]
