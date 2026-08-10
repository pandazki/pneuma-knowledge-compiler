# AGENTS.md

This file guides coding agents (Claude Code, Codex, Cursor, …) working in this repository.

## What this is

Pneuma Knowledge Compiler turns the raw material of a domain — meetings, documents, chat, email — into an evolvable, citation-backed knowledge base where fabrication is structurally impossible. It is not an agent memory system.

`docs/architecture.md` is the design authority — read it before anything non-trivial. `docs/guides/compile-contract.md` is the authority on writing compile contracts. Documentation is bilingual: English is primary (`X.md`) with a Chinese mirror (`X.zh-CN.md`) — when you edit one, update the other. Code and comments are English only; legacy Chinese comments are being migrated — do not add new ones.

## Commands

```bash
# Setup (Python 3.12 + uv + Docker + Node 18+ + pnpm)
uv sync --all-packages
docker compose -f infra/docker-compose.yml up -d --wait   # Postgres :15432, Qdrant :16333, Meilisearch :17700, RustFS :19000
cd apps/web && pnpm install

# Run locally (three terminals)
bash scripts/dev-api.sh          # FastAPI on 127.0.0.1:18000, autoreload
bash scripts/dev-worker.sh       # async index/compile worker (drains the PG job queue)
cd apps/web && pnpm dev          # Vite on :5173, proxies /v1 to the API

# Tests — fully keyless: the root conftest registers the reference contracts (playing the
# application's part), and the service conftest pins a deterministic embedding mock
# (fake:384), mechanical sentence chunking, and an isolated Qdrant test collection.
uv run pytest                                    # all four packages (root testpaths)
uv run pytest packages/pneuma-knowledge-core/tests/test_foo.py::test_bar   # single test
uv run pytest tests/             # repo-hygiene + scaffold tests (NOT in default testpaths)

# Web
cd apps/web && pnpm run build    # tsc -b && vite build — run before committing web changes
cd apps/web && pnpm test         # node --test tests/*.test.mjs
```

Real-middleware integration tests run when Postgres/Qdrant/Meilisearch are reachable; image round-trip tests additionally require RustFS. Otherwise they skip with an explicit "middleware unreachable" reason. Real model calls need `.env` (copy from `.env.example`); never commit `.env`.

## Workspace layout

uv workspace with four packages plus the app surfaces:

- `packages/pneuma-knowledge-core` — pure domain logic + async `Protocol` ports. Zero middleware dependencies (pydantic, langchain-core, langchain, chonkie only). Subpackages: `domain/`, `ingest/`, `skill/`, `compile/`, `recall/`, `evolve/`, `persona/`, `ports/`, `prompts/`.
- `packages/pneuma-knowledge-service` — port implementations: FastAPI (`api/routes/`), adapters (git_canonical / qdrant / meilisearch / postgres), workers, settings (all `PNEUMA_KNOWLEDGE_*` env vars — [docs/reference/configuration.md](docs/reference/configuration.md)).
- `packages/pneuma-knowledge-strategies` — reference compile contracts as a data-only package; the framework never imports it.
- `packages/pneuma-knowledge-eval` — read-only judgement-quality metrics.
- `apps/web` — React/Vite SPA (Tailwind 4, Radix, zustand).
- `scaffold/` — project generator (`init.py`: interactive TUI or `--answers` single command) that emits a complete knowledge-base project; machinery templates in `templates/`, demo dataset in `example/`.
- `scripts/ops/` — explicit maintenance commands (`import_source`, `rebuild_derived`, `reindex_l2`).
- `examples/` — one example: `opc/`, a complete scaffold-born project (agent-built from the synthetic OPC corpus; prebuilt library restorable keyless via `bootstrap.py`, browsing layer via its compose `web` profile, full build record under `build-record/`).
- `archive/` — git-ignored pre-rebuild documents kept for reference. Do not read or resurrect them unless the user explicitly asks; new docs are written from source.

**Dependency direction is one-way**: `service → core`, `apps/web → service API`. Core never imports middleware clients. No custom LLM abstraction: core functions take langchain-core `BaseChatModel` / `Embeddings` directly; service assembles them via `init_chat_model`. Agentic loops (deep recall, briefing ask) use langchain `create_agent` — do not hand-roll tool loops.

## Architecture essentials

**Four access levels over the same source** (parallel views, not fallbacks):
- L0 raw verbatim fetch (Postgres source blocks + structure map) — unconditional
- L1 lexical full-text (Meilisearch, index per user) — unconditional
- L2 semantic chunks (Qdrant, single collection + mechanically injected tenant filter) — per IntakePlan
- L3 canonical claims (LLM compile behind a citation gate, per-user canonical library) — per IntakePlan

**Authority vs derived**: only two things are authoritative — L0 in Postgres and the per-user canonical library (shipped adapter: one Git repository per user). Everything else (L1/L2 indexes, L3 projections) is derived and rebuildable (`scripts/ops/rebuild_derived.py`). The default L2 strategy is `semantic` — LLM topic/episode boundary detection (philosophy inspired by nemori; the model returns block indexes only, chunk text stays verbatim); first-time boundaries are recorded in PG `chunk_manifests` and replayed on rebuild, making rebuilds byte-deterministic. Scripted/keyless models fall back to mechanical sentence chunking automatically.

**Ingest pipeline**: SourceAdapter (the only layer allowed to grow with input types) → NormalizedSource → IntakePlan (`canonical_treatment` × `semantic_indexing`, archetypes in core `domain/intake.py`) → index/compile jobs. The official input boundary is four versioned provider-neutral contracts: `meeting/v1`, `document-library/v1`, `im/v1`, `email/v1` ([docs/reference/source-contracts.md](docs/reference/source-contracts.md)).

**Async everything**: import requests only write L0 + enqueue `index`/`compile` jobs; the worker processes them per-user serially (PG `FOR UPDATE SKIP LOCKED`) and self-heals stuck jobs on restart. API and worker are stateless. But **a function that awaits nothing is not a coroutine** — spine/gate/patch/projection/domain/render helpers stay sync; unavoidably-blocking work (git subprocess, chonkie) is wrapped in `to_thread` inside adapters. Pytest runs with `asyncio_mode = "auto"` — bare `async def test_*` works without decorators.

## Invariants (violating any of these = review rejection)

From `docs/architecture.md` §9 — enforced expectations, not aspirations:

- **I1** — `user_id` isolation everywhere: first parameter of every port method, per-user canonical library / Meili index, Qdrant tenant filter injected at the adapter layer. No cross-user read path exists.
- **I2** — canonical vs derived are distinct types; strategy/render upgrades only rebuild derived, never rewrite canonical.
- **I3** — L0/L1 reachability is unconditional regardless of IntakePlan.
- **I4** — all knowledge links back via `source_id + block span`; one addressing scheme across claims, chunks, lexical hits, structure maps. Citation syntax is `[cite: <sid> ¶a-b]` with one shared parser for gate and projection.
- **I5** — SystemMessage is byte-stable (no timestamps or volatile content); question/as_of/session deltas go in HumanMessage.
- **I6** — eval answers/rubrics/evidence fields never enter compile or recall inputs (leak discipline).

Two project-wide disciplines: (1) **mechanism over persuasion** — constraints must be mechanical (write-time rejection, system-assigned IDs, deterministic normalization), never "please remember to X" prompt copy; if you're writing that prompt, the design is wrong. (2) Cost/latency metrics and quality metrics are proposed and measured separately; quality claims need a same-harness baseline.

## Conventions

- New/changed compile behavior needs tests preserving: canonical/derived boundary, `user_id` isolation, provenance citations, and synthetic honesty. All example data must be synthetic — no credentials, real personal material, or private brand content.
- The content-hygiene denylist is operator-local (`local/hygiene-denylist.txt`); the hygiene tests skip when it is absent.
- Third-party datasets and runtime state live under `local/` (fully git-ignored); they are re-fetched, never vendored.
- Bilingual docs move in pairs: an edit to `X.md` lands together with `X.zh-CN.md`.

## 帮用户构建知识库

If the user asks you to help them build their own knowledge base (rather than develop this framework), read `scaffold/AGENT-GUIDE.md` and follow it — it is the single source of truth for that flow, written for any coding agent. The prompt a beginner is told to paste is:

```
请阅读 scaffold/AGENT-GUIDE.md 并按它引导我，用我自己的数据建一个知识库。我是新手，请一步步来。
```
