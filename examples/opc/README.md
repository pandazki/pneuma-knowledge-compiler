# OPC example environment

This directory is a self-contained example application built on top of
`pneuma-knowledge-core` and `pneuma-knowledge-service`. It is the only owner of
the fictional OPC developer, the Seamlog 84-day story, its Chinese strategy
wording, and the experiment-specific quality contract.

The framework packages provide mechanisms only. They must not import this
directory or name its persona, companies, projects, story beats, evaluation
truth, or experiment identifiers.

## Runtime contract

The example declares every deployment-owned input in one place:

- `assets/profile.json` — the fictional owner profile and locale;
- `assets/strategy.md` — the OPC compilation strategy registered as
  `opc-example-v1`;
- `assets/schema-matrix.json` — additive profile-derived filing families;
- `assets/prompt-overlay.json` — Chinese wording for selected model-visible
  surfaces; unspecified catalog keys retain the framework defaults;
- `.env.example` — operation-level model routes, chunking, schema-evolve and
  isolated infrastructure settings;
- `compose.yaml` — an isolated Postgres, Qdrant, Meilisearch, API, worker and
  Web UI stack;
- `nginx.conf` — same-origin API, SSE and WebSocket proxying for the example Web UI;
- `data/demo/` — the small four-source keyless walkthrough;
- `data/84-day/` — the frozen 28-group longitudinal corpus and evaluation truth.
- `evaluation-v1.md` — the experiment-specific evaluation contract.

`environment.configure_example()` must run before the API, worker, CLI or
experiment code asks the framework to load a skill or render a prompt.
Configuration is process-local and deterministic. Canonical commits therefore
record both the example skill content hash and the prompt overlay hash.

## Commands

All commands run from the repository root:

```bash
# Inspect the command surface without starting infrastructure.
uv run python -m examples.opc --help

# Start the isolated browsing stack (the demo seeder compiles in-process).
docker compose -f examples/opc/compose.yaml up -d --build

# Populate the small four-source tenant with deterministic local models.
docker compose -f examples/opc/compose.yaml --profile tools run --rm cli seed

# For normal asynchronous ingestion, enable the long-running compile worker.
docker compose -f examples/opc/compose.yaml --profile worker up -d worker

# Run a fresh keyless 84-day tenant in the same isolated stack.
# Reports are written to examples/opc/var/reports on the host.
docker compose -f examples/opc/compose.yaml --profile tools run --rm cli \
  run --mode keyless

# Run and evaluate a real-provider tenant after configuring examples/opc/.env.
docker compose --env-file examples/opc/.env -f examples/opc/compose.yaml \
  --profile tools run --rm cli \
  run --mode real
docker compose --env-file examples/opc/.env -f examples/opc/compose.yaml \
  --profile tools run --rm cli \
  evaluate --mode real --user <run-user-id>

# Browse and query the real-provider collection through the API/Web stack.
PNEUMA_OPC_EXAMPLE_MODE=real \
  docker compose --env-file examples/opc/.env -f examples/opc/compose.yaml \
  up -d --build
```

Copy `.env.example` to `.env` only when real providers are needed. The checked-in
configuration contains no credential and defaults to deterministic local
models. Real mode fails before mutating a tenant if any routed chat model is
scripted, the embedding model is fake, or an OpenRouter route has no key. To
reuse the repository root `.env` instead, replace
`--env-file examples/opc/.env` with `--env-file .env`.

The keyless 84-day run is a plumbing control, not a semantic-quality result. It
compiles only blocks containing the frozen truth set's reviewed evidence quotes,
never injects evaluator-authored truth paraphrases, and is expected to score poorly
on semantic recall with fake embeddings. Use it to verify ingestion, projections,
versioning and citation replay; use real mode for knowledge-quality experiments.

## Isolation invariants

1. The Compose project, ports, database, Qdrant collection, Meilisearch key,
   canonical volume and user-id prefix are distinct from the root development
   stack. Keyless and real modes additionally use separate Qdrant collections,
   because fake and provider embeddings can have different dimensions.
2. A run creates a fresh `u-opc-seamlog-v2-*` tenant unless an explicit reserved
   experiment id is supplied. It never resets an arbitrary user.
3. The frozen 84-day corpus is imported from final accepted groups only.
   Authoring drafts, superseded reviews and failed run logs are not runtime
   assets.
4. `examples.opc` may import public framework contracts. Framework packages
   must never import `examples.opc`.
5. Keyless and real modes use the same source contracts, profile, strategy,
   prompt overlay and filing schema; only provider bindings differ.
