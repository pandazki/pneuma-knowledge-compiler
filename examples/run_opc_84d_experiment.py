#!/usr/bin/env python
"""Run the 84-day corpus as twelve real incremental import/compile batches.

``--mode scripted`` is the fast, keyless scale baseline: real PG/Meili/Qdrant/git,
deterministic sentence chunks and a truth-aware scripted compiler. ``--mode real`` fails
closed unless every configured provider is real.  Both modes use the same source
contracts and persist per-batch metrics for later comparison.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
from collections import Counter
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.experiments.opc_84d import build_opc_84d_dataset
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context, resolve_model_name
from pneuma_knowledge_service.workers.compile_worker import drain_user

USER = UserId("u-opc-ninghe")
DEFAULT_REPORT = Path("docs/experiments/results/opc-84d-baseline.json")


def _one_line(value: str, limit: int = 320) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _settings(mode: str) -> Settings:
    if mode == "scripted":
        return Settings(
            llm_model="scripted:opc-84d",
            embedding_model="fake:64",
            qdrant_collection="pneuma_knowledge_chunks_opc84d_fake64",
            chunk_strategy="sentence",
            evolve_auto_trigger=False,
        )
    settings = Settings(evolve_auto_trigger=False)
    issues: list[str] = []
    for role in ("compile", "recall", "deep", "live_context", "evolve"):
        if resolve_model_name(settings, role).startswith("scripted:"):
            issues.append(f"{role} is scripted")
    if settings.embedding_model.startswith("fake:"):
        issues.append(f"embedding model is fake: {settings.embedding_model}")
    if not settings.openrouter_api_key:
        issues.append("OPENROUTER_API_KEY is missing")
    if issues:
        raise RuntimeError("real experiment refuses current providers: " + "; ".join(issues))
    return settings


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


async def _profile(ctx) -> None:
    profile = await ctx.user_info.get_profile(USER)
    payload = profile.model_dump(mode="json", exclude={"level_style"})
    display_name = "沈砚"
    payload.update(
        {
            "user_id": str(USER),
            "display_name": display_name,
            "avatar": {
                **payload["avatar"],
                "initial": display_name[0],
            },
            "industry": "tech",
            "role": "other",
            "role_other": "founder",
            "level": "staff",
            "occupation": "AI-native 独立开发者 / RelayForge 维护者",
            "bio": "独立开发、销售和运营可追溯决策产品 RelayForge。",
            "interests": ["开源维护", "客户研究", "知识系统", "产品工程"],
            "source": "user",
        }
    )
    await ctx.store.upsert_user_profile(USER, payload)


def _current_truth_values(manifest: dict[str, Any]) -> tuple[str, ...]:
    truth = manifest["truth"]
    rows = [
        *truth["durable_facts"],
        *truth["decisions"],
        *truth["commitments"],
        *truth["constraints"],
    ]
    return tuple(
        item["value"]
        for item in rows
        if item.get("status") not in {"superseded", "cancelled"}
    )


def _projection_metrics(
    jobs: list[dict[str, Any]], source_ids: list[str]
) -> dict[str, int]:
    current_sources = set(source_ids)
    totals = Counter()
    for job in jobs:
        if job.get("kind") != "compile":
            continue
        payload_sources = {
            str(source_id)
            for source_id in (job.get("payload") or {}).get("source_ids", [])
        }
        if not payload_sources.intersection(current_sources):
            continue
        detail = str(job.get("detail") or "")
        if not detail.startswith("projection:"):
            continue
        metrics = json.loads(detail.removeprefix("projection:"))
        for key in ("upserted", "deleted", "unchanged"):
            totals[key] += int(metrics.get(key, 0))
        totals["syncs"] += 1
        totals["latest_total"] = max(
            totals["latest_total"], int(metrics.get("total", 0))
        )
    return {
        key: int(totals.get(key, 0))
        for key in ("syncs", "upserted", "deleted", "unchanged", "latest_total")
    }


def _batch_failures(
    jobs: list[dict[str, Any]], source_ids: list[str]
) -> list[dict[str, Any]]:
    """Unresolved jobs belonging to this batch, without poisoning later recovery.

    A historical failed job remains in the audit ledger forever. Once its derived state
    has been mechanically reconciled, a later batch must still be runnable; only jobs
    whose payload intersects the current batch decide whether this batch fails closed.
    """
    current_sources = set(source_ids)
    failures: list[dict[str, Any]] = []
    for job in jobs:
        payload_sources = {
            str(source_id)
            for source_id in (job.get("payload") or {}).get("source_ids", [])
        }
        if not payload_sources.intersection(current_sources):
            continue
        if job["status"] == "done" and job.get("ok") is True:
            continue
        failures.append(
            {
                "job_id": job["job_id"],
                "kind": job["kind"],
                "detail": job.get("detail"),
            }
        )
    return failures


async def _scripted_turns(
    ctx, source_ids: list[str], truth_values: tuple[str, ...]
) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    for source_id in source_ids:
        source = await ctx.store.get(USER, SourceId(source_id))
        matches: list[tuple[int, str]] = []
        for block in source.blocks:
            if any(value in block.text for value in truth_values):
                matches.append((block.index, block.text))
        # A noise-only source intentionally becomes a noop: this is the deterministic
        # control baseline for the manifest's negative-control leakage metric.
        if not matches:
            turns.append([{"name": "finish_compile"}])
            continue
        claims = [
            f"- {_one_line(text)} [cite: s01 ¶{index}]"
            for index, text in matches[:6]
        ]
        kind = source.raw.kind.replace("_", "-")
        body = (
            f"# {source.raw.title}\n\n"
            "## 已确认记录\n\n"
            + "\n".join(claims)
        )
        turns.append(
            [
                {
                    "name": "create_document",
                    "args": {
                        "path": f"work/products/relayforge-{kind}-{source_id}.md",
                        "frontmatter": {
                            "type": "source-digest",
                            "slug": source_id,
                            "source_kind": source.raw.kind,
                            "experiment": "opc-84d-relayforge",
                        },
                        "body": body,
                    },
                },
                {"name": "finish_compile"},
            ]
        )
    return turns


async def _counts(ctx) -> dict[str, int]:
    sources = await ctx.store.list(USER)
    jobs = await ctx.store.list_jobs(USER)
    docs = await ctx.canonical.list(USER)
    claims = await ctx.store.list_canonical_claims(USER)
    snapshots = await ctx.canonical.snapshots(USER)
    return {
        "sources": len(sources),
        "jobs": len(jobs),
        "jobs_ok": sum(job.get("ok") is True for job in jobs),
        "jobs_failed": sum(
            job.get("status") == "done" and job.get("ok") is not True for job in jobs
        ),
        "documents": len(docs),
        "claims": len(claims),
        "snapshots": len(snapshots),
    }


async def run(
    *,
    mode: str,
    reset: bool,
    from_batch: int,
    until_batch: int,
    report_path: Path,
) -> dict[str, Any]:
    dataset = build_opc_84d_dataset()
    truth_values = _current_truth_values(dataset.manifest)
    settings = _settings(mode)
    ctx = await build_context(settings)
    started = time.perf_counter()
    batch_reports: list[dict[str, Any]] = []
    try:
        if reset:
            await _reset(ctx, settings)
        await _profile(ctx)
        for batch_number, batch in enumerate(dataset.batches, start=1):
            if batch_number < from_batch:
                continue
            if batch_number > until_batch:
                break
            before = await _counts(ctx)
            batch_started = time.perf_counter()
            source_ids: list[str] = []
            contract_units: list[dict[str, Any]] = []
            for contract in batch.contracts:
                result = await ingest_source_contract(
                    ctx, USER, parse_source_contract(contract)
                )
                ids = [str(item.source_id) for item in result.sources]
                source_ids.extend(ids)
                contract_units.append(
                    {
                        "schema": result.contract_schema,
                        "units": len(result.sources),
                        "deduplicated": sum(item.deduplicated for item in result.sources),
                    }
                )
            model = (
                ctx.get_chat_model("compile")
                if mode == "real"
                else ScriptedChatModel(
                    turns=await _scripted_turns(ctx, source_ids, truth_values)
                )
            )
            processed = await drain_user(
                ctx, model, load_builtin_skill(), USER
            )
            after = await _counts(ctx)
            all_jobs = await ctx.store.list_jobs(USER)
            failures = _batch_failures(all_jobs, source_ids)
            batch_report = {
                "batch_id": batch.batch_id,
                "elapsed_seconds": round(time.perf_counter() - batch_started, 4),
                "contracts": contract_units,
                "new_source_ids": source_ids,
                "processed_jobs": processed,
                "before": before,
                "after": after,
                "delta": {key: after[key] - before[key] for key in after},
                "projection": _projection_metrics(all_jobs, source_ids),
                "failures": failures,
            }
            batch_reports.append(batch_report)
            print(
                f"{batch.batch_id} {batch_report['elapsed_seconds']:>8.2f}s "
                f"+sources={batch_report['delta']['sources']} "
                f"+jobs={batch_report['delta']['jobs']} "
                f"+docs={batch_report['delta']['documents']} "
                f"+claims={batch_report['delta']['claims']} "
                f"failed={after['jobs_failed']}",
                flush=True,
            )
            if failures:
                raise RuntimeError(
                    f"{batch.batch_id} has {len(failures)} failed or unfinished jobs"
                )

        final = await _counts(ctx)
        kinds = Counter(item.kind for item in await ctx.store.list(USER))
        result = {
            "schema": "pneuma.experiment.run/v1",
            "experiment_id": dataset.manifest["experiment_id"],
            "user_id": str(USER),
            "mode": mode,
            "models": {
                role: resolve_model_name(settings, role)
                for role in ("compile", "recall", "deep", "live_context", "evolve")
            },
            "embedding_model": settings.embedding_model,
            "chunk_strategy": settings.chunk_strategy,
            "elapsed_seconds": round(time.perf_counter() - started, 4),
            "dataset_stats": dataset.manifest["stats"],
            "batches": batch_reports,
            "final": final,
            "source_kinds": dict(sorted(kinds.items())),
            "historical_failures": [
                {
                    "job_id": job["job_id"],
                    "kind": job["kind"],
                    "detail": job.get("detail"),
                    "source_ids": list(
                        (job.get("payload") or {}).get("source_ids", [])
                    ),
                }
                for job in await ctx.store.list_jobs(USER)
                if job["status"] == "done" and job.get("ok") is not True
            ],
        }
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return result
    finally:
        await ctx.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("scripted", "real"), default="scripted")
    parser.add_argument("--keep", action="store_true")
    parser.add_argument("--from-batch", type=int, default=1, choices=range(1, 13))
    parser.add_argument("--until-batch", type=int, default=12, choices=range(1, 13))
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = asyncio.run(
        run(
            mode=args.mode,
            reset=not args.keep,
            from_batch=args.from_batch,
            until_batch=args.until_batch,
            report_path=args.report,
        )
    )
    print(json.dumps(result["final"], ensure_ascii=False, indent=2))
    print(f"OK: experiment report → {args.report.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
