#!/usr/bin/env python
"""Run the accepted 84-day v2 corpus as 28 real incremental import/compile batches.

``--mode keyless`` is a fast, deterministic ingestion/index baseline over real
PG/Meili/Qdrant/git. ``--mode real`` also compiles the accepted evidence with the
configured real model and fails closed unless every provider is real. Both modes use
the same source contracts from accepted G01–G28 and persist per-batch metrics.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from examples import _bootstrap  # noqa: F401

from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context, resolve_model_name
from pneuma_knowledge_service.workers.compile_worker import drain_user

from examples.opc.dataset import build_accepted_opc_84d_v2_dataset
from examples.opc.environment import (
    BASE_VERSION,
    DATA_ROOT,
    EXAMPLE_ROOT,
    EXPERIMENT_USER_PREFIX,
    example_settings,
    install_example_subject,
)

USER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")
DEFAULT_USER_PREFIX = EXPERIMENT_USER_PREFIX
DEFAULT_REPORT_DIR = EXAMPLE_ROOT / "var" / "reports"
EXPERIMENT_ID = "opc-84d-v2-accepted"
TRUTH_PATH = DATA_ROOT / "84-day" / "spec" / "evaluation-truth.json"


def _new_user_id() -> UserId:
    """Return a fresh, URL/filesystem-safe tenant for one experiment run."""

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    return UserId(f"{DEFAULT_USER_PREFIX}-{timestamp}-{secrets.token_hex(8)}")


def _require_experiment_user(user_id: UserId) -> None:
    value = str(user_id)
    if not USER_ID_RE.fullmatch(value) or not value.startswith(
        f"{DEFAULT_USER_PREFIX}-"
    ):
        raise ValueError(
            f"user_id must be a safe tenant under the reserved experiment prefix "
            f"{DEFAULT_USER_PREFIX}-"
        )


def _user_id(value: str | None) -> UserId:
    if value is None:
        return _new_user_id()
    if not USER_ID_RE.fullmatch(value):
        raise ValueError(
            "user_id must start with a letter or digit, contain only letters, "
            "digits, '_' or '-', and be at most 96 characters"
        )
    user_id = UserId(value)
    _require_experiment_user(user_id)
    return user_id


def _new_report_path(user_id: UserId, *, kind: str) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    suffix = secrets.token_hex(4)
    return DEFAULT_REPORT_DIR / f"opc-84d-{kind}-{user_id}-{timestamp}-{suffix}.json"


def _json_scalar(value: Any) -> str | int | float | bool | None:
    """Convert a scalar from a numeric library at the report boundary."""

    item = getattr(value, "item", None)
    if callable(item):
        scalar = item()
        if scalar is None or isinstance(scalar, (str, int, float, bool)):
            return scalar
    raise TypeError(
        f"Object of type {value.__class__.__name__} is not JSON serializable"
    )


def _json_text(payload: Any) -> str:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            default=_json_scalar,
        )
        + "\n"
    )


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    """Atomically checkpoint a report without exposing partial JSON."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = _json_text(payload).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _build_dataset():
    """Load only the frozen, compact example corpus."""
    return build_accepted_opc_84d_v2_dataset()


def _contract_payload(contract: Any) -> dict[str, Any]:
    """Round-trip typed assembly output through the official wire validator."""

    return contract.model_dump(mode="json", by_alias=True)


def _required_source_ids(dataset, *, before_batch: int) -> set[str]:
    """Compute the immutable source IDs every earlier batch must have imported."""

    imported_at = datetime(2000, 1, 1, tzinfo=UTC)
    required: set[str] = set()
    for batch_number, batch in enumerate(dataset.batches, start=1):
        if batch_number >= before_batch:
            break
        for payload in batch.contracts:
            contract = parse_source_contract(_contract_payload(payload))
            required.update(
                str(source.raw.source_id)
                for source in normalize_source_contract(
                    contract,
                    UserId("u-opc-resume-preflight"),
                    imported_at=imported_at,
                )
            )
    return required


def _one_line(value: str, limit: int = 320) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _public_model_label(model: str) -> str:
    """Keep public run evidence useful without publishing private model routing."""
    if model.startswith("openrouter:"):
        return "openrouter:configured"
    return model


def _settings(mode: str) -> Settings:
    if mode not in {"keyless", "real"}:
        raise ValueError(f"unsupported experiment mode: {mode!r}")
    return example_settings(mode)


async def _reset(ctx, settings: Settings, user_id: UserId) -> None:
    _require_experiment_user(user_id)
    root = Path(settings.canonical_root).resolve()
    target = (root / str(user_id)).resolve()
    if target.parent != root or target.name != str(user_id):
        raise RuntimeError(f"refusing unsafe canonical reset target: {target}")
    # Finish every path/scope preflight before deleting any storage layer. A rejected
    # canonical target must never leave PG/Meili/Qdrant partially erased.
    await ctx.store.delete_user(user_id)
    await ctx.lexical.delete_user(user_id)
    await ctx.vectors.delete_user(user_id)
    if target.exists():
        shutil.rmtree(target)


async def _profile(ctx, user_id: UserId) -> None:
    await install_example_subject(
        ctx,
        user_id,
        experiment_id=EXPERIMENT_ID,
        profile_updates={
            "display_name": "林舟",
            "avatar": {"initial": "林", "color": "#6C8EBF"},
            "level": "staff",
            "occupation": "AI-Native 独立开发者 / Seamlog 维护者",
            "bio": "独立开发、销售和运营变更证据链产品 Seamlog。",
            "interests": ["开源维护", "客户研究", "知识系统", "产品工程"],
            "source": "example",
        },
    )


async def _tenant_footprint(ctx, user_id: UserId) -> dict[str, int]:
    """Return every persisted surface that would make a tenant non-empty."""

    sources = await ctx.store.list(user_id)
    jobs = await ctx.store.list_jobs(user_id)
    profile = await ctx.store.get_user_profile(user_id)
    documents = await ctx.canonical.list(user_id)
    claims = await ctx.store.list_canonical_claims(user_id)
    snapshots = await ctx.canonical.snapshots(user_id)
    return {
        "sources": len(sources),
        "jobs": len(jobs),
        "profile": int(profile is not None),
        "documents": len(documents),
        "claims": len(claims),
        "snapshots": len(snapshots),
    }


async def _require_empty_tenant(ctx, user_id: UserId) -> None:
    footprint = await _tenant_footprint(ctx, user_id)
    occupied = {key: value for key, value in footprint.items() if value}
    if occupied:
        raise RuntimeError(
            f"refusing to start from batch 1 in non-empty tenant {user_id}: "
            f"{occupied}; use a fresh user or explicitly --reset-user"
        )


async def _require_resume_tenant(
    ctx,
    user_id: UserId,
    dataset,
    *,
    from_batch: int,
) -> None:
    profile = await ctx.store.get_user_profile(user_id)
    if not isinstance(profile, dict) or profile.get("experiment_id") != EXPERIMENT_ID:
        raise RuntimeError(
            f"cannot resume {user_id}: tenant is not owned by {EXPERIMENT_ID}"
        )
    existing_ids = {
        str(source.source_id) for source in await ctx.store.list(user_id)
    }
    required_ids = _required_source_ids(dataset, before_batch=from_batch)
    missing_ids = sorted(required_ids - existing_ids)
    if missing_ids:
        preview = ", ".join(missing_ids[:5])
        suffix = "…" if len(missing_ids) > 5 else ""
        raise RuntimeError(
            f"cannot resume {user_id} from batch {from_batch}: "
            f"{len(missing_ids)} prior source(s) are missing "
            f"({preview}{suffix})"
        )
    # A resumed tenant may contain completed prior batches and a partial current
    # batch, but never sources from a later batch or another experiment.
    allowed_ids = _required_source_ids(dataset, before_batch=from_batch + 1)
    unexpected_ids = sorted(existing_ids - allowed_ids)
    if unexpected_ids:
        preview = ", ".join(unexpected_ids[:5])
        suffix = "…" if len(unexpected_ids) > 5 else ""
        raise RuntimeError(
            f"cannot resume {user_id}: {len(unexpected_ids)} foreign source(s) "
            f"are present ({preview}{suffix})"
        )


def _current_truth_evidence(manifest: dict[str, Any]) -> tuple[str, ...]:
    """Return the reviewed source wording for every non-terminal truth row.

    The truth value is an evaluator-authored paraphrase and is not expected to occur
    verbatim in L0. Its evidence quotes are frozen excerpts from L0, so they provide a
    deterministic, non-semantic keyless control without injecting the expected answer
    into canonical.
    """

    truth = manifest["truth"]
    rows = [
        *truth["durable_facts"],
        *truth["decisions"],
        *truth["commitments"],
        *truth["constraints"],
    ]
    quotes: list[str] = []
    for item in rows:
        if item.get("status") in {"superseded", "cancelled"}:
            continue
        for evidence in item.get("evidence", []):
            quote = " ".join(str(evidence.get("quote") or "").split())
            if quote and quote not in quotes:
                quotes.append(quote)
    return tuple(quotes)


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
    ctx,
    user_id: UserId,
    source_ids: list[str],
    truth_evidence: tuple[str, ...],
) -> list[list[dict[str, Any]]]:
    turns: list[list[dict[str, Any]]] = []
    for source_id in source_ids:
        source = await ctx.store.get(user_id, SourceId(source_id))
        matches: list[tuple[int, str]] = []
        for block in source.blocks:
            block_text = " ".join(block.text.split())
            if any(quote in block_text for quote in truth_evidence):
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
                        "path": f"work/products/seamlog-{kind}-{source_id}.md",
                        "frontmatter": {
                            "type": "source-digest",
                            "slug": source_id,
                            "source_kind": source.raw.kind,
                            "experiment": "opc-84d-v2-seamlog",
                        },
                        "body": body,
                    },
                },
                {"name": "finish_compile"},
            ]
        )
    return turns


async def _counts(ctx, user_id: UserId) -> dict[str, int]:
    sources = await ctx.store.list(user_id)
    jobs = await ctx.store.list_jobs(user_id)
    docs = await ctx.canonical.list(user_id)
    claims = await ctx.store.list_canonical_claims(user_id)
    snapshots = await ctx.canonical.snapshots(user_id)
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
    user_id: UserId,
    mode: str,
    reset: bool,
    from_batch: int,
    until_batch: int,
    report_path: Path,
) -> dict[str, Any]:
    _require_experiment_user(user_id)
    if reset and from_batch > 1:
        raise ValueError("reset cannot be combined with from_batch > 1")
    dataset = _build_dataset()
    truth_manifest = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    truth_evidence = _current_truth_evidence(truth_manifest)
    settings = _settings(mode)
    ctx = await build_context(settings)
    started = time.perf_counter()
    batch_reports: list[dict[str, Any]] = []
    try:
        # Resolve the provider before any profile, source, index or canonical
        # mutation, while still guaranteeing that the context is closed if
        # provider construction itself fails.
        compile_model = ctx.get_chat_model("compile") if mode == "real" else None
        if reset:
            await _reset(ctx, settings, user_id)
        elif from_batch > 1:
            await _require_resume_tenant(
                ctx, user_id, dataset, from_batch=from_batch
            )
        else:
            await _require_empty_tenant(ctx, user_id)
        await _profile(ctx, user_id)
        for batch_number, batch in enumerate(dataset.batches, start=1):
            if batch_number < from_batch:
                continue
            if batch_number > until_batch:
                break
            before = await _counts(ctx, user_id)
            batch_started = time.perf_counter()
            source_ids: list[str] = []
            contract_units: list[dict[str, Any]] = []
            for contract in batch.contracts:
                result = await ingest_source_contract(
                    ctx, user_id, parse_source_contract(_contract_payload(contract))
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
                compile_model
                if mode == "real"
                else ScriptedChatModel(
                    turns=await _scripted_turns(
                        ctx, user_id, source_ids, truth_evidence
                    )
                )
            )
            processed = await drain_user(
                ctx,
                model,
                load_builtin_skill(BASE_VERSION),
                user_id,
            )
            after = await _counts(ctx, user_id)
            all_jobs = await ctx.store.list_jobs(user_id)
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
            checkpoint = {
                "schema": "pneuma.experiment.run/v1",
                "experiment_id": EXPERIMENT_ID,
                "user_id": str(user_id),
                "mode": mode,
                "execution": {
                    "from_batch": from_batch,
                    "until_batch": until_batch,
                    "executed_batch_count": len(batch_reports),
                    "executed_contract_count": sum(
                        len(item["contracts"]) for item in batch_reports
                    ),
                    "status": "running",
                },
                "batches": batch_reports,
            }
            _write_report(report_path, checkpoint)
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

        final = await _counts(ctx, user_id)
        kinds = Counter(item.kind for item in await ctx.store.list(user_id))
        result = {
            "schema": "pneuma.experiment.run/v1",
            "experiment_id": EXPERIMENT_ID,
            "user_id": str(user_id),
            "mode": mode,
            "models": {
                role: _public_model_label(resolve_model_name(settings, role))
                for role in ("compile", "recall", "deep", "live_context", "evolve")
            },
            "embedding_model": _public_model_label(settings.embedding_model),
            "chunk_strategy": settings.chunk_strategy,
            "elapsed_seconds": round(time.perf_counter() - started, 4),
            "dataset_stats": {
                "batch_count": len(dataset.batches),
                "source_contract_count": sum(
                    len(batch.contracts) for batch in dataset.batches
                ),
                "accepted_group_ids": [batch.batch_id for batch in dataset.batches],
            },
            "batches": batch_reports,
            "execution": {
                "from_batch": from_batch,
                "until_batch": until_batch,
                "executed_batch_count": len(batch_reports),
                "executed_contract_count": sum(
                    len(item["contracts"]) for item in batch_reports
                ),
                "status": "completed",
            },
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
                for job in await ctx.store.list_jobs(user_id)
                if job["status"] == "done" and job.get("ok") is not True
            ],
        }
        _write_report(report_path, result)
        return result
    finally:
        await ctx.aclose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("keyless", "real"), default="keyless")
    parser.add_argument(
        "--user",
        help=(
            "target user tenant; omitted creates a fresh "
            f"{DEFAULT_USER_PREFIX}-<timestamp>-<suffix> user"
        ),
    )
    reset_group = parser.add_mutually_exclusive_group()
    reset_group.add_argument(
        "--reset-user",
        action="store_true",
        help="explicitly delete and rebuild the selected --user before importing",
    )
    reset_group.add_argument(
        "--keep",
        action="store_true",
        help="deprecated compatibility flag; preserving the selected user is now default",
    )
    parser.add_argument("--from-batch", type=int, default=1, choices=range(1, 29))
    parser.add_argument("--until-batch", type=int, default=28, choices=range(1, 29))
    parser.add_argument(
        "--report",
        type=Path,
        help="report path; defaults to examples/opc/var/reports",
    )
    args = parser.parse_args()
    if args.from_batch > 1 and args.user is None:
        parser.error("--from-batch > 1 requires --user to resume an existing tenant")
    if args.reset_user and args.user is None:
        parser.error("--reset-user requires an explicit --user")
    if args.reset_user and args.from_batch > 1:
        parser.error("--reset-user cannot be combined with --from-batch > 1")
    try:
        user_id = _user_id(args.user)
    except ValueError as exc:
        parser.error(str(exc))
    report_path = args.report or _new_report_path(user_id, kind="run")
    result = asyncio.run(
        run(
            user_id=user_id,
            mode=args.mode,
            reset=args.reset_user,
            from_batch=args.from_batch,
            until_batch=args.until_batch,
            report_path=report_path,
        )
    )
    print(json.dumps(result["final"], ensure_ascii=False, indent=2))
    print(f"OK: user={user_id} experiment report → {report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
