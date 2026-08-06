#!/usr/bin/env python3
"""Restore the prebuilt OPC library — no API key required.

What ships is only the two authorities, the things that cannot be recomputed:
`prebuilt/canonical.bundle` (the compiled canonical library as a git bundle) and
`prebuilt/l0.jsonl.gz` (the build-time NormalizedSource rows verbatim, so the source ids and
block spans are exactly the ones the restored canonical cites — a re-ingest of `my-data/`
could never reproduce them, because source ids are system-assigned at ingest).

The restore itself belongs to the framework (`pneuma_knowledge_service.prebuilt`), which any
project shipping a library uses — including the ones `scaffold/init.py --demo` generates. This
file only supplies the settings that make it keyless: deterministic embeddings whose dimension
(1536) matches the recommended real model, so a later keyed run reuses the same collection, and
no chat model at all, so an empty OPENROUTER_API_KEY is enough.

Run from this directory, stack up first:  ./app.py up && ./bootstrap.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import app as scaffold_app  # noqa: E402 — the neighboring scaffold driver

PREBUILT = HERE / "prebuilt"
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
    )


async def main() -> int:
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.prebuilt import PrebuiltUnavailable, restore_prebuilt
    from pneuma_knowledge_service.wiring import build_context

    settings = keyless_settings()
    uid = UserId(scaffold_app.user_id())
    ctx = await build_context(settings)
    try:
        print("== 恢复预编译库（正本 bundle + L0，零密钥） ==")
        await scaffold_app.upsert_owner_profile(ctx, uid)
        try:
            report = await restore_prebuilt(ctx, uid, PREBUILT, log=print)
        except PrebuiltUnavailable as exc:
            print(f"错误：{exc}", file=sys.stderr)
            return 1
        print(
            f"\n完成：canonical 文档 {report.documents} 篇，claims {report.claims} 条，"
            f"来源 {report.sources} 份。"
        )
        print("下一步：docker compose --profile web up -d --build api web，然后打开 Web。")
        return 0
    finally:
        await ctx.aclose()


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
