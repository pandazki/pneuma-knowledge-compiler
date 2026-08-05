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

New or changed compile behavior needs tests that hold the four load-bearing properties: the canonical/derived boundary, `user_id` isolation, provenance citations, and synthetic honesty. The five invariants in [architecture §9](docs/architecture.md#9-invariants) take precedence over any local trade-off.

## Data rules

All example and test data must be synthetic — no credentials, no real personal material, no private brand content. Bundled personas and journeys are labeled synthetic and never presented as real customer evidence. Third-party datasets are never vendored; they live under git-ignored `local/` and are re-fetched.

## Language

Documentation is bilingual: English is primary (`X.md`) with a Chinese mirror (`X.zh-CN.md`) — edits move in pairs. Code and comments are English only. The scaffold's user-facing text is deliberately Chinese; leave it that way.
