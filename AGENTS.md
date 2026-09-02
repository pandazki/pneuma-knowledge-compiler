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

**Do not edit framework code while a production build is running.** A build in flight is reading this working tree, so an edit mid-run changes what is being measured and leaves the run unattributable — neither the result nor the diff can be trusted afterwards. If a fix cannot wait for the run to finish, record the reproduction and the diff first, so what changed under the run is nameable.

## Workspace layout

uv workspace with four packages plus the app surfaces:

- `packages/pneuma-knowledge-core` — pure domain logic + async `Protocol` ports. Zero middleware dependencies (pydantic, langchain-core, langchain, chonkie only). Subpackages: `domain/`, `ingest/`, `skill/`, `compile/`, `recall/`, `evolve/`, `persona/`, `ports/`, `prompts/`.
- `packages/pneuma-knowledge-service` — port implementations: FastAPI (`api/routes/`), adapters (git_canonical / qdrant / meilisearch / postgres), workers, settings (all `PNEUMA_KNOWLEDGE_*` env vars — [docs/reference/configuration.md](docs/reference/configuration.md)).
- `packages/pneuma-knowledge-strategies` — reference compile contracts as a data-only package; the framework never imports it.
- `packages/pneuma-knowledge-eval` — read-only judgement-quality metrics.
- `apps/web` — React/Vite SPA (Tailwind 4, Radix, zustand).
- `scaffold/` — project generator (`init.py`: interactive TUI or `--answers` single command) that emits a complete knowledge-base project; machinery templates in `templates/`, demo dataset in `example/`.
- `scripts/ops/` — explicit maintenance commands (`import_source`, `rebuild_derived`, `reindex_l2`).
- `examples/` — one example: `opc/`, a complete scaffold-born project (agent-built from the synthetic OPC corpus; prebuilt library restorable keyless via `./app.py restore`, browsing layer via its compose `console` profile, full build record under `build-record/`).
- `archive/` — git-ignored pre-rebuild documents kept for reference. Do not read or resurrect them unless the user explicitly asks; new docs are written from source.

**Dependency direction is one-way**: `service → core`, `apps/web → service API`. Core never imports middleware clients. No custom LLM abstraction: core functions take langchain-core `BaseChatModel` / `Embeddings` directly; service assembles them via `init_chat_model`. Agentic loops (deep recall, briefing ask) use langchain `create_agent` — do not hand-roll tool loops.

## Architecture essentials

**Four access levels over the same source** (parallel views, not fallbacks):
- L0 raw verbatim fetch (Postgres source blocks + structure map) — unconditional
- L1 lexical full-text (Meilisearch, index per user) — unconditional
- L2 semantic chunks (Qdrant, single collection + mechanically injected tenant filter) — per IntakePlan
- L3 canonical claims (LLM compile behind a citation gate, per-user canonical library) — per IntakePlan

**Three persistent categories**: only two things are authoritative — L0 in Postgres and the per-user canonical library (shipped adapter: one Git repository per user). Beside them sit **kept records** — chunk manifests, compile events, consultations — stored observations that a rebuild replays and never rewrites. Everything else (L1/L2 indexes, L3 projections, component projections) is **derived**, rebuildable from the substrate it declares (`scripts/ops/rebuild_derived.py`). The default L2 strategy is `semantic` — LLM topic/episode boundary detection (philosophy inspired by nemori; the model returns each episode's boundaries plus a derived title and description for embedding, and the chunk text stays verbatim); first-time boundaries are recorded in PG `chunk_manifests` and replayed on rebuild, making rebuilds byte-deterministic. Scripted/keyless models fall back to mechanical sentence chunking automatically.

**Ingest pipeline**: SourceAdapter (the only layer allowed to grow with input types) → NormalizedSource → IntakePlan (`canonical_treatment` × `semantic_indexing`, archetypes in core `domain/intake.py`) → index/compile jobs. The official input boundary is five versioned provider-neutral contracts: `meeting/v1`, `document-library/v1`, `im/v1`, `email/v1`, `owner-dialogue/v1` (the library owner's own statement — an ordinary source, no privileged write path) ([docs/reference/source-contracts.md](docs/reference/source-contracts.md)).

**Canonical has two parts.** The **ledger** is append-only: anchored, cited claims, immutable anchors, no deletion. The **overview** is a bounded head above it — four slots (`definition`, `summary`, `introduction`, `connections`) the compile model may rewrite whole with `rewrite_overview`. That single wholesale write is safe for a mechanical reason and not a hopeful one: the gate requires every overview block to rest on a ledger claim (`c:xxxx`) or a source span, and bounds the region in characters (`OVERVIEW_BUDGET_CHARS`), so the head cannot grow into a second ledger. Beside `create_document` / `append_block` and `edit_claim`, the third write verb is `supersede_claim` — *the world changed*, as against *I was wrong*: the old claim stays byte-for-byte as frozen history, the successor names it (`<!-- supersedes: c:xxxx -->`) and must cite new evidence.

**Two extension seams.** Schema packs extend the *judgement* (additive contract fragments, composed per user); **index components** extend the *structure* — business-specific structure over a contract family, contributed through one protocol (core `components/`) at the framework's own seams: gate checks, an outline line under the family's documents, compile tools, deep-recall tools, routed fast-recall paths, one source preamble line in the compile task, a projection channel (`on_source_indexed` / `rebuild`, with `prepare` as its per-job async face — a compile process's mirror of a projection written by the index process is always cold), the use-side notification `on_recall` (one answering call happened, as a `ConsultationRecord`), and `evolve_evidence` (one mechanical block in front of the schema-evolve proposal). The application registers what it enables (`PNEUMA_KNOWLEDGE_COMPONENTS`); core knows no component, and with none registered every seam renders byte-for-byte as it did before the concept existed. Shipped: `people` and `time`, which own projections, and `attention`, face-only — the report, deep tool and fast path over the framework's own access ledger. The design authority is [docs/design/index-components.md](docs/design/index-components.md).

**Async everything**: import requests only write L0 + enqueue `index`/`compile` jobs; the worker processes them per-user serially (PG `FOR UPDATE SKIP LOCKED`) and self-heals stuck jobs on restart. API and worker are stateless. But **a function that awaits nothing is not a coroutine** — spine/gate/patch/projection/domain/render helpers stay sync; unavoidably-blocking work (git subprocess, chonkie) is wrapped in `to_thread` inside adapters. Pytest runs with `asyncio_mode = "auto"` — bare `async def test_*` works without decorators.

## Invariants (violating any of these = review rejection)

From `docs/architecture.md` §9 — enforced expectations, not aspirations:

- **I1** — `user_id` isolation everywhere: first parameter of every port method, per-user canonical library / Meili index, Qdrant tenant filter injected at the adapter layer. No cross-user read path exists.
- **I2** — canonical, kept records and derived are distinct types; strategy/render upgrades rebuild derived only, each layer from the substrate it declares, and never rewrite canonical or a record.
- **I3** — L0/L1 reachability is unconditional regardless of IntakePlan.
- **I4** — all knowledge links back via `source_id + block span`; one addressing scheme across claims, chunks, lexical hits, structure maps. Citation syntax is `[cite: <sid> ¶a-b]` with one shared parser for gate and projection.
- **I5** — SystemMessage is byte-stable (no timestamps or volatile content); question/as_of/session deltas go in HumanMessage.
- **I6** — eval answers/rubrics/evidence fields never enter compile or recall inputs (leak discipline). The mechanism is package direction: the eval package is a leaf — `eval → core`, and neither core nor service imports it (`tests/test_open_source_hygiene.py::test_the_eval_package_is_a_leaf_and_cannot_leak_into_what_it_judges`).
- **I7** — a component's projection is derived and rebuildable: it is re-derived by the same `rebuild_derived` as every other derived layer, from the substrate it declares (L0, canonical, and for a use-side projection the kept consultation records), and a component never writes canonical — the canonical face it is handed at registration is read-only (`CanonicalReadOnly` in core `components/`), so what it indexes reaches the library only by riding an ordinary compile, under the contract and the gate.

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
