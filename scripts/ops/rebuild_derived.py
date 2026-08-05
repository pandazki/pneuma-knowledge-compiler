#!/usr/bin/env python
"""Rebuild ALL derived indexes (L1 + L2 + L3) for one or more users from the authorities.

The canonical L0 (PG sources/blocks) and L3 canonical git repos are the only authorities
(invariant I2). Everything else — L1 Meili lexical, L2 Qdrant vectors, and the L3
projection (PG canonical_claims + Meili claims + Qdrant claim layer) — is derived and
rebuildable. Use this after a Qdrant/Meili wipe, a container/version switch, an embedding
model change (dimension change), or a chunk-strategy change, when a single layer is not
enough and you want the whole retrieval surface reconciled to the current config.

What it does per user, reporting before/after so you can eyeball the reconciliation:
  L1  re-index every source's stored blocks into Meili (drops the user's stale index first);
  L2  re-chunk + re-embed every source via the configured strategy (semantic replays its
      chunk manifest for a byte-deterministic rebuild — see docs/getting-started.md);
  L3  re-project canonical HEAD onto PG claims + Meili claims + Qdrant claim layer.

Usage:
    uv run python scripts/ops/rebuild_derived.py <user-id>
    uv run python scripts/ops/rebuild_derived.py --all

Run against the compose stack (docker compose -f infra/docker-compose.yml up -d --wait).
Semantic chunking + embeddings need a real OPENROUTER_API_KEY in .env; the L2 step is the
only one that calls a provider (L1 and L3-lexical are mechanical; L3 vectors re-embed).
"""

from __future__ import annotations

import asyncio
import sys

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
import sys as _sys
from pathlib import Path as _Path

_sys.path.insert(0, str(_Path(__file__).resolve().parent))
import _env  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.chunking import EmbeddedChunk
from pneuma_knowledge_service.projection import rebuild_projection
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context

from reindex_l2 import _chunks_for


async def rebuild_user(ctx, user_id: UserId) -> None:
    sources = await ctx.store.list(user_id)
    l2_before = await ctx.vectors.count_chunks(user_id)
    print(
        f"\n== {user_id}: {len(sources)} source(s) | "
        f"L2 chunks before = {l2_before} =="
    )
    if not sources:
        print("  (no L0 sources — nothing to rebuild)")
        return

    # L1 — drop the user's lexical indexes, then re-index every source's stored blocks.
    await ctx.lexical.delete_user(user_id)
    l1_sources = 0
    for raw in sources:
        normalized = await ctx.store.get(user_id, raw.source_id)
        await ctx.lexical.index_blocks(user_id, raw.source_id, normalized.blocks)
        l1_sources += 1
    print(f"  L1  re-indexed {l1_sources} source(s) into Meili")

    # L2 — drop stale chunk points once, then re-chunk + re-embed every source.
    await ctx.vectors.delete_chunks(user_id)
    l2_chunks = 0
    for raw in sources:
        normalized = await ctx.store.get(user_id, raw.source_id)
        chunks = await _chunks_for(ctx, raw.source_id, normalized, user_id)
        if not chunks:
            continue
        vectors = await ctx.embeddings.aembed_documents([c.text for c in chunks])
        embedded = [
            EmbeddedChunk(
                source_id=c.source_id,
                block_start=c.block_start,
                block_end=c.block_end,
                text=c.text,
                char_start=c.char_start,
                char_end=c.char_end,
                embedding=vec,
            )
            for c, vec in zip(chunks, vectors)
        ]
        await ctx.vectors.upsert_chunks(user_id, embedded)
        l2_chunks += len(chunks)
    l2_after = await ctx.vectors.count_chunks(user_id)
    print(f"  L2  {l2_after} chunk(s) (was {l2_before})")

    # L3 — re-project canonical HEAD onto PG + Meili claims + Qdrant claim layer.
    claim_count = await rebuild_projection(ctx, user_id)
    print(f"  L3  projected {claim_count} claim(s) from canonical HEAD")


async def main() -> int:
    args = sys.argv[1:]
    settings = Settings()
    ctx = await build_context(settings)
    print(
        f"chunk_strategy={settings.chunk_strategy}  "
        f"embedding={settings.embedding_model}  qdrant={settings.qdrant_collection}"
    )
    try:
        if args == ["--all"]:
            users = [UserId(u) for u in await ctx.store.list_users()]
            print(f"rebuilding ALL {len(users)} user(s)")
        elif args and not args[0].startswith("--"):
            users = [UserId(u) for u in args]
        else:
            print(__doc__)
            return 2
        for user in users:
            await rebuild_user(ctx, user)
    finally:
        await ctx.aclose()
    print("\nOK: derived rebuild complete (L1 + L2 + L3)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
