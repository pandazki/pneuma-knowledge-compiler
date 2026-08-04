#!/usr/bin/env python3
"""Restore the prebuilt OPC library — no API key required.

What ships is only the canonical library (prebuilt/canonical.bundle, a git bundle): the
one thing that cannot be recomputed. Everything else is rebuilt from the two authorities,
exactly as the architecture promises:

  1. canonical  — cloned from the bundle into ./data/canonical/<user>/;
  2. L0        — loaded from prebuilt/l0.jsonl.gz, the build-time NormalizedSource rows
                  verbatim: source ids and block spans are exactly the ones the restored
                  canonical cites. (Source ids are system-assigned at ingest, so a
                  re-ingest of my-data/ could never reproduce them — the L0 authority
                  ships alongside the canonical authority, as the architecture's
                  "two authorities" reading actually demands. my-data/ remains the
                  human-readable corpus and the input for your own recompiles.)
  3. L1/L2 + L3 — lexical/chunk indexes and the projection rebuilt with a deterministic
                  fake embedding whose dimension (1536) matches the recommended real
                  model, so a later keyed run reuses the same collection;
  4. any queued jobs are settled as "prebuilt" and the sources marked digested — a later
     `./app.py compile` never re-compiles the restored library.

Run from this directory, stack up first:  ./app.py up && ./bootstrap.py
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import app as scaffold_app  # noqa: E402 — the neighboring scaffold driver

BUNDLE = HERE / "prebuilt" / "canonical.bundle"
FAKE_EMBEDDING = "fake:1536"  # dimension-matched to openrouter:openai/text-embedding-3-small


def keyless_settings():
    """Settings for the restore path: deterministic embeddings, no chat models.

    Chat model roles are cleared on purpose — nothing here may call a model, so the
    restore works with an empty OPENROUTER_API_KEY. A later keyed compile overwrites
    the same deterministic vector ids in place.
    """
    from pneuma_knowledge_service.settings import Settings

    skill = scaffold_app.load_contract_skill()
    profile = scaffold_app.load_profile()
    zone, _ = scaffold_app.resolved_timezone(profile)
    pg = scaffold_app.stack_port("PNEUMA_APP_PG_PORT", scaffold_app.DEFAULT_PG_PORT)
    qd = scaffold_app.stack_port("PNEUMA_APP_QDRANT_PORT", scaffold_app.DEFAULT_QDRANT_PORT)
    ml = scaffold_app.stack_port("PNEUMA_APP_MEILI_PORT", scaffold_app.DEFAULT_MEILI_PORT)
    # Deliberately NOT build_settings(): that path requires an API key, and the whole
    # point of the restore is that browsing needs none.
    return Settings(
        pg_dsn=f"postgresql://pneuma_knowledge:pneuma_knowledge@127.0.0.1:{pg}/pneuma_knowledge",
        qdrant_url=f"http://127.0.0.1:{qd}",
        meili_url=f"http://127.0.0.1:{ml}",
        canonical_root=str(scaffold_app.DATA_ROOT / "canonical"),
        default_timezone=zone or "UTC",
        user_schema_base_version=skill.version,
        user_schema_packs=False,
        evolve_auto_trigger=False,
        challenge_enabled=False,
        chunk_strategy="sentence",
        embedding_model=FAKE_EMBEDDING,
        llm_model="",
        llm_model_compile="",
        llm_model_recall="",
        llm_model_deep="",
        llm_model_skill="",
        llm_model_evolve="",
        llm_model_live_context="",
        llm_model_challenge="",
    )


def restore_canonical(user_id: str, canonical_root: Path) -> None:
    target = canonical_root / user_id
    if (target / ".git").exists():
        print(f"  canonical 已存在（{target}），跳过恢复。")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--quiet", str(BUNDLE), str(target)], check=True)
    print(f"  canonical 已从 bundle 恢复：{target}")


async def main() -> int:
    if not BUNDLE.exists():
        sys.exit(f"错误：找不到 {BUNDLE} —— 预编译包缺失。")

    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.projection import rebuild_projection
    from pneuma_knowledge_service.wiring import build_context

    settings = keyless_settings()
    uid = UserId(scaffold_app.user_id())

    print("== 恢复正本（git bundle） ==")
    restore_canonical(str(uid), Path(settings.canonical_root).resolve())

    ctx = await build_context(settings)
    try:
        print("== 装载 L0（构建期原始来源，零密钥） ==")
        await scaffold_app.upsert_owner_profile(ctx, uid)
        code = await _load_l0(ctx, uid)
        if code != 0:
            return code

        print("== 结账：清空队列，全部来源标记已编译 ==")
        # Dirty-state proof: re-queue stale claimed jobs, settle everything queued, and
        # digest every source explicitly — the prebuilt canonical already covers them.
        await ctx.store.requeue_claimed_jobs()
        settled = 0
        while True:
            job = await ctx.store.claim_next(uid)
            if job is None:
                break
            await ctx.store.complete(uid, job.job_id, ok=True, detail="bootstrap: prebuilt library")
            settled += 1
        sources = await ctx.store.list(uid)
        await ctx.store.mark_digested(
            uid, [str(s.source_id) for s in sources], datetime.now(timezone.utc)
        )
        print(f"  结账 {settled} 个任务；{len(sources)} 份来源已标记为已编译。")

        print("== 重建 L1/L2 索引（确定性向量） ==")
        from pneuma_knowledge_core.ingest.chunking import EmbeddedChunk
        from pneuma_knowledge_service.wiring import full_l2_chunks

        await ctx.vectors.delete_chunks(uid)
        indexed = 0
        for raw in sources:
            normalized = await ctx.store.get(uid, raw.source_id)
            await ctx.lexical.index_blocks(uid, raw.source_id, normalized.blocks)
            chunks = await full_l2_chunks(
                ctx, raw.source_id, normalized.blocks, normalized.structure, uid
            )
            if chunks:
                vectors = await ctx.embeddings.aembed_documents([c.text for c in chunks])
                await ctx.vectors.upsert_chunks(uid, [
                    EmbeddedChunk(
                        source_id=c.source_id, block_start=c.block_start,
                        block_end=c.block_end, text=c.text,
                        char_start=c.char_start, char_end=c.char_end, embedding=vec,
                    )
                    for c, vec in zip(chunks, vectors)
                ])
            indexed += 1
        print(f"  {indexed} 份来源的 L1/L2 已重建。")

        print("== 重建 L3 投影 ==")
        count = await rebuild_projection(ctx, uid, allow_wipe=True)
        print(f"  投影 claims：{count}")

        docs = await ctx.canonical.list(uid)
        print(f"\n完成：canonical 文档 {len(docs)} 篇，claims {count} 条。")
        print("下一步：docker compose --profile web up -d --build api web，然后打开 Web。")
        return 0
    finally:
        await ctx.aclose()


async def _load_l0(ctx, uid) -> int:
    """Load the build-time L0 rows verbatim from prebuilt/l0.jsonl.gz.

    Restoring by re-ingesting my-data/ is structurally wrong twice over: source ids are
    system-assigned (uuid4) so citations can never re-bind, and any change to the parsing
    machinery would shift block boundaries out from under the canonical's cited spans.
    The dump carries the exact NormalizedSource rows the citations were written against."""
    import gzip
    import json

    from pneuma_knowledge_core.domain.source import NormalizedSource

    dump = HERE / "prebuilt" / "l0.jsonl.gz"
    if not dump.exists():
        print(f"错误：找不到 {dump}", file=sys.stderr)
        return 1
    count = 0
    with gzip.open(dump, "rt", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            normalized = NormalizedSource.model_validate(json.loads(line))
            stored = await ctx.store.add(uid, normalized)
            if str(stored) != str(normalized.raw.source_id):
                print(
                    f"错误：来源 {normalized.raw.source_id} 落库后 id 变成 {stored}",
                    file=sys.stderr,
                )
                return 1
            count += 1
    print(f"  装载 {count} 份来源（id 与正本引用逐一对应）。")
    return 0


def _ensure_framework_for_self() -> None:
    """Like app.ensure_framework, but re-execs THIS file — the driver's version re-execs
    app.py by its own __file__, which turns a borrowed call into `app.py` with no args."""
    import os
    try:
        import pneuma_knowledge_service  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("PNEUMA_APP_REEXEC") == "1":
        sys.exit("错误：经 uv 重启后仍找不到框架包。确认 PNEUMA_APP_FRAMEWORK_REPO 并已 `uv sync`。")
    repo = scaffold_app.find_framework_repo()
    if repo is None:
        sys.exit("错误：找不到框架仓库。请在 .env 设置 PNEUMA_APP_FRAMEWORK_REPO。")
    os.environ["PNEUMA_APP_REEXEC"] = "1"
    os.execvpe("uv", ["uv", "run", "--project", str(repo), "python", str(Path(__file__).resolve())], os.environ)


if __name__ == "__main__":
    scaffold_app.load_env_file(HERE / ".env")
    _ensure_framework_for_self()
    raise SystemExit(asyncio.run(main()))
