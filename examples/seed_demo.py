#!/usr/bin/env python
"""Build the synthetic OPC demo from all four official source contracts.

The data is synthetic, but the path is real: canonical JSON mock adapters validate the
same contracts as Zoom/Obsidian/Slack/RFC 5322 adapters, natural citation units enter
L0, the worker builds L1/L2, a scripted compiler writes cited L3 documents, and all
derived projections are persisted for the API and Web UI.

The named demo tenant is reset by default. Pass ``--keep`` to exercise source dedup.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from collections import Counter
from pathlib import Path

import _bootstrap  # noqa: F401  (localhost proxy bypass before middleware imports)

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.adapters.source_imports import CanonicalJsonSourceAdapter
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context, resolve_model_name
from pneuma_knowledge_service.workers.compile_worker import drain_user

USER = UserId("u-opc-lin")
DATA_ROOT = Path("examples/data/opc-demo")
RECALL_SCRIPT = DATA_ROOT / "recall-script.json"
SOURCE_FIXTURES = [
    DATA_ROOT / "sources/meeting.json",
    DATA_ROOT / "sources/document-library.json",
    DATA_ROOT / "sources/im.json",
    DATA_ROOT / "sources/email.json",
]


def _one_line(value: str, limit: int = 220) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


async def _compile_turns(ctx, source_ids: list[str]) -> list[list[dict]]:
    """One deterministic, cited canonical document per expanded source."""

    turns: list[list[dict]] = []
    for index, source_id in enumerate(source_ids, start=1):
        source = await ctx.store.get(USER, SourceId(source_id))
        kind_slug = source.raw.kind.replace("_", "-")
        blocks = source.blocks
        claims = [f"- {_one_line(blocks[0].text)} [cite: s01 ¶0]"]
        if len(blocks) > 1:
            last = len(blocks) - 1
            claims.append(
                f"- {_one_line(blocks[last].text)} [cite: s01 ¶{last}]"
            )
        body = (
            f"# {source.raw.title}\n\n"
            "## 编译摘要\n\n"
            + "\n".join(claims)
        )
        turns.append(
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": f"work/products/source-{index:02d}-{kind_slug}.md",
                        "frontmatter": {
                            "type": "source-digest",
                            "slug": f"source-{index:02d}-{kind_slug}",
                            "source_kind": source.raw.kind,
                            "synthetic": True,
                        },
                        "body": body,
                    },
                },
                {"name": "finish_compile"},
            ]
        )
    return turns


async def _reset(ctx, settings: Settings) -> None:
    await ctx.store.delete_user(USER)
    await ctx.lexical.delete_user(USER)
    await ctx.vectors.delete_user(USER)

    root = Path(settings.canonical_root).resolve()
    target = (root / str(USER)).resolve()
    if target.parent != root or target.name != str(USER):
        raise RuntimeError(f"refusing unsafe canonical reset target: {target}")
    if target.exists():
        shutil.rmtree(target)


def _demo_settings(*, real: bool) -> Settings:
    if not real:
        return Settings(
            llm_model=f"scripted:{RECALL_SCRIPT.as_posix()}",
            embedding_model="fake:64",
            chunk_strategy="sentence",
            evolve_auto_trigger=False,
        )

    settings = Settings(evolve_auto_trigger=False)
    issues: list[str] = []
    scripted_roles = [
        role
        for role in ("compile", "recall", "deep", "live_context", "evolve")
        if resolve_model_name(settings, role).startswith("scripted:")
    ]
    if scripted_roles:
        issues.append(
            "real demo refuses scripted LLM roles: " + ", ".join(scripted_roles)
        )
    if settings.embedding_model.startswith("fake:"):
        issues.append(
            f"real demo refuses fake embeddings: {settings.embedding_model}"
        )
    if not settings.openrouter_api_key:
        issues.append("real demo requires OPENROUTER_API_KEY")
    if issues:
        raise RuntimeError("; ".join(issues))
    return settings


def _failed_job_details(jobs: list[dict]) -> list[str]:
    failures: list[str] = []
    for job in jobs:
        if job.get("status") != "done" or job.get("ok") is not True:
            detail = job.get("detail") or f"status={job.get('status')}"
            failures.append(
                f"{job.get('kind', 'unknown')} {job.get('job_id', 'unknown')}: "
                f"{detail}"
            )
    return failures


async def run(*, reset: bool = True, real: bool = False) -> int:
    settings = _demo_settings(real=real)
    ctx = await build_context(settings)
    try:
        if reset:
            await _reset(ctx, settings)

        profile = await ctx.user_info.get_profile(USER)
        await ctx.store.upsert_user_profile(
            USER, profile.model_dump(mode="json", exclude={"level_style"})
        )

        mock = CanonicalJsonSourceAdapter()
        source_ids: list[str] = []
        for fixture in SOURCE_FIXTURES:
            contract = mock.load(fixture)
            result = await ingest_source_contract(ctx, USER, contract)
            for item in result.sources:
                source_ids.append(str(item.source_id))
            state = (
                "dedup"
                if result.sources and all(item.deduplicated for item in result.sources)
                else "ingest"
            )
            print(
                f"  {state:6} {result.contract_schema:<42} "
                f"units={len(result.sources)}"
            )

        model = (
            ctx.get_chat_model("compile")
            if real
            else ScriptedChatModel(turns=await _compile_turns(ctx, source_ids))
        )
        processed = await drain_user(ctx, model, load_builtin_skill(), USER)
        failures = _failed_job_details(await ctx.store.list_jobs(USER))
        if failures:
            raise RuntimeError(
                "demo pipeline has failed or unfinished jobs:\n- "
                + "\n- ".join(failures)
            )

        sources = await ctx.store.list(USER)
        claims = await ctx.store.list_canonical_claims(USER)
        documents = await ctx.canonical.list(USER)
        snapshots = await ctx.canonical.snapshots(USER)
        kinds = Counter(source.kind for source in sources)
        print(
            "  pipeline "
            f"sources={len(sources)} jobs={processed} docs={len(documents)} "
            f"claims={len(claims)} snapshots={len(snapshots)}"
        )
        print("  source kinds " + ", ".join(f"{k}={v}" for k, v in sorted(kinds.items())))

        if reset and not real:
            assert kinds == {
                "meeting": 1,
                "document_library": 5,
                "im": 3,
                "email": 2,
            }
            assert len(sources) == 11
            assert processed == 22
            assert len(documents) == 11
            assert len(claims) == 22
            assert len(snapshots) == 11
        elif reset:
            assert kinds == {
                "meeting": 1,
                "document_library": 5,
                "im": 3,
                "email": 2,
            }
            assert len(sources) == 11
            assert processed == 22
            assert documents
            assert claims
            assert snapshots
        assert all(source_ids)
    finally:
        await ctx.aclose()

    mode = "real providers" if real else "scripted/keyless providers"
    print(f"OK: four-source synthetic OPC demo ready ({mode}) → {USER}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--keep",
        action="store_true",
        help="keep the existing tenant and exercise source dedup instead of resetting",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help=(
            "use configured real providers; fail closed instead of accepting scripted "
            "LLMs or fake embeddings"
        ),
    )
    args = parser.parse_args()
    return asyncio.run(run(reset=not args.keep, real=args.real))


if __name__ == "__main__":
    sys.exit(main())
