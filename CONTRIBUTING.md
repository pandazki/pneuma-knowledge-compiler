# Contributing

**English** | [简体中文](CONTRIBUTING.zh-CN.md)

Setup and architecture live in the [README](README.md) and [docs/architecture.md](docs/architecture.md); this page is only what you need before opening a PR.

## Two gates before every commit

```bash
uv run pytest                      # all four packages
cd apps/web && pnpm run build      # when you touched the web app
```

The suite is fully keyless: the root conftest registers the reference contracts, embeddings are pinned to a deterministic `fake:384`, chunking to mechanical `sentence`, and Qdrant uses an isolated test collection — nothing touches your app data or any real provider. Integration tests that need real middleware run when Postgres/Qdrant/Meilisearch are reachable and otherwise skip with an explicit "middleware unreachable" reason. Root-level hygiene and scaffold tests live outside the default testpaths: `uv run pytest tests/`.

## What a change must preserve

New or changed compile behavior needs tests that hold the four load-bearing properties: the canonical/derived boundary, `user_id` isolation, provenance citations, and synthetic honesty. The seven invariants in [architecture §9](docs/architecture.md#9-invariants) take precedence over any local trade-off.

Canonical is written by four bounded verbs and nothing else — `create_document` / `append_block`, `edit_claim`, `supersede_claim` (the world changed, as against I was wrong) and `rewrite_overview`, the one wholesale write, which replaces the document's bounded head and leaves the ledger untouched. It is safe only because the gate grounds every overview block on a ledger claim or a source span and bounds the region in characters. A new write path lands with the gate check that bounds it; a verb whose safety rests on prompt wording is not a contribution the gate can hold.

## Extending the framework

Two seams, and they extend different things. A **schema pack** is an additive contract fragment — it extends the judgement. An **index component** (core `components/`) extends the structure: business-specific structure over one contract family, contributed at the framework's own seams (gate checks, an outline line, field validation, compile and deep-recall tools, routed fast-recall paths, a source preamble line, the `on_source_indexed` / `rebuild` projection channel with its per-job `prepare`, the use-side `on_recall`, and `evolve_evidence`). Every face has a no-op default, so a component implements only the ones it needs, and one that keeps no projection of its own — `attention` is the shipped example — implements no channel at all. A new component must satisfy four things, each testable:

- **derived only** — whatever it persists is re-derived in full by `scripts/ops/rebuild_derived.py`, from the substrate it declares: L0, canonical, and for a use-side projection the kept consultation records;
- **read-only canonical** — the canonical face handed to it at registration is `CanonicalReadOnly`; what it indexes reaches the library only by riding an ordinary compile (I7);
- **fail-soft** — a component that raises costs a stale projection, never a failed job;
- **tests for the seam** — every face it contributes, plus the one that proves an unregistered component changes no seam byte.

The design authority, with the checklist for writing a third, is [docs/design/index-components.md](docs/design/index-components.md).

## Data rules

All example and test data must be synthetic — no credentials, no real personal material, no private brand content. Bundled personas and journeys are labeled synthetic and never presented as real customer evidence. Third-party datasets are never vendored; they live under git-ignored `local/` and are re-fetched.

## Language

Documentation is bilingual: English is primary (`X.md`) with a Chinese mirror (`X.zh-CN.md`) — edits move in pairs. Code and comments are English only. The scaffold's user-facing text is deliberately Chinese; leave it that way.
