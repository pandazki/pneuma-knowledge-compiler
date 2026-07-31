#!/usr/bin/env python
"""Re-index a user's L2 semantic vectors with the configured chonkie chunker.

Existing users' L2 chunks were produced by the old block-packing chunker; this rebuilds
them with the current chonkie sentence chunker (sentence boundaries + overlap). L1
(Meili, block-addressed) and L3 (claim projection) are left untouched — only the L2
chunk layer is deleted and rebuilt.

For each source we use the stored normalized blocks + structure (the persisted L0 — this
is exactly what a fresh ingest produced, so the block-joined char offsets match a fresh
ingest byte-for-byte), re-chunk, re-embed, and re-upsert. Then we delete the user's old
L2 chunk points once and re-upsert every source's fresh chunks.

Usage:
    uv run python -m examples.ops.reindex_l2 <user-id> [<user-id> ...]
Run against the compose stack (docker compose -f infra/docker-compose.yml up -d --wait).
"""

from __future__ import annotations

import asyncio
import sys

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
from examples import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.chunking import EmbeddedChunk
from pneuma_knowledge_service.ingest_document import _summary_chunks
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context, full_l2_chunks

async def _chunks_for(ctx, source_id, normalized, user_id):
    """Mirror the ingest L2 path: full → strategy dispatch (sentence/recursive/semantic);
    summary → section heads. `full_l2_chunks` routes to the semantic LLM segmenter when
    PNEUMA_KNOWLEDGE_CHUNK_STRATEGY=semantic, so re-index matches a fresh ingest under any strategy."""
    plan = normalized.raw.intake_plan or {}
    semantic = plan.get("semantic_indexing", "full")
    if semantic == "full":
        return await full_l2_chunks(
            ctx, source_id, normalized.blocks, normalized.structure, user_id
        )
    if semantic == "summary":
        return _summary_chunks(source_id, normalized)
    return []


async def reindex_user(ctx, user_id: UserId) -> None:
    before = await ctx.vectors.count_chunks(user_id)
    sources = await ctx.store.list(user_id)
    print(f"\n== {user_id}: {len(sources)} source(s), L2 chunks before = {before} ==")

    # Delete the user's stale L2 chunk points once (claims/L1 untouched), then rebuild.
    await ctx.vectors.delete_chunks(user_id)

    sample: list = []
    for raw in sources:
        normalized = await ctx.store.get(user_id, raw.source_id)
        chunks = await _chunks_for(ctx, raw.source_id, normalized, user_id)
        if not chunks:
            print(f"  {raw.source_id[:8]}… '{raw.title}': no L2 chunks (plan)")
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
        print(
            f"  {raw.source_id[:8]}… '{raw.title}': "
            f"{len(normalized.blocks)} blocks → {len(chunks)} chunks"
        )
        if not sample:
            sample = chunks

    after = await ctx.vectors.count_chunks(user_id)
    print(f"  L2 chunks after = {after}")

    # Eyeball boundaries + overlap on the first source's first few chunks.
    if sample:
        print("  -- sample chunk boundaries (first source) --")
        for c in sample[:4]:
            head = c.text[:34].replace("\n", "⏎")
            tail = c.text[-24:].replace("\n", "⏎")
            print(
                f"     [{c.char_start:>5}-{c.char_end:<5}] blocks {c.block_start}-{c.block_end} "
                f"len={len(c.text):>4}  «{head}…{tail}»"
            )
        for a, b in zip(sample[:4], sample[1:5]):
            ov = a.char_end - b.char_start
            shared = (
                a.text[len(a.text) - ov :] if ov > 0 else "(none)"
            )
            print(
                f"     overlap chunk[{a.char_start}] → chunk[{b.char_start}]: "
                f"{max(0, ov)} chars shared «{shared[:24].replace(chr(10), '⏎')}»"
            )


async def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    users = [UserId(u) for u in sys.argv[1:]]
    settings = Settings()
    ctx = await build_context(settings)
    # Do NOT pre-build a chunker here: strategy="semantic" has no standalone chonkie
    # chunker (build_chunker would raise). full_l2_chunks owns the per-strategy dispatch.
    print(
        f"chunker: strategy={settings.chunk_strategy} size={settings.chunk_size} "
        f"overlap={settings.chunk_overlap}"
    )
    try:
        for user in users:
            await reindex_user(ctx, user)
    finally:
        await ctx.aclose()
    print("\nOK: reindex complete")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
