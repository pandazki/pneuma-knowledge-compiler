"""`pkc jobs requeue` — put work back that was recorded as finished without being done.

The queue is honest about what it was told and nothing more. A job row says `done ok=true`
because something completed it that way; if the thing that completed it never ran a round,
the row is a true record of a false event, and every reading built on it — digestion, the
"uncompiled sources" count, the Owner's belief that the material is in the library — inherits
that. The night this command was written, 296 compile jobs of one real library carried
exactly that shape: `done`, `ok=true`, `projection:{…"upserted":0…}; rounds:1`, no snapshot,
sources stamped digested, and not one claim written.

`round_runner.HARNESS_UNAVAILABLE` is the mechanism that stops it happening again. This is
the other half: the verb that repairs a library where it already did. It re-queues the
selected jobs' payloads as new rows and clears the digestion stamp their sources carry, so
the same material is compiled again by whatever runs next. It writes nothing to canonical and
judges nothing — a re-queued job is judged by the gate like any other.

Selection is deliberately mechanical and deliberately narrow: only TERMINAL rows are
selectable, so the command can never duplicate work that is still queued or in flight.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Sequence

from pneuma_knowledge_core.domain.ids import UserId

from .draft import EXIT_NOTHING, EXIT_OK, EXIT_REFUSED

#: What an "empty round" looks like on a job row: the projection moved nothing, one round
#: ran, and no commit came out of it. Three facts rather than one, because each on its own
#: has an innocent reading — a compile that legitimately wrote nothing new is a noop with a
#: snapshot behind it, and a two-round job that upserted nothing was judged and refused.
EMPTY_ROUND_MARKERS: tuple[str, ...] = ('"upserted":0', "rounds:1")


def _is_empty_round(row: dict[str, Any]) -> bool:
    detail = row.get("detail") or ""
    return (
        row.get("status") == "done"
        and row.get("ok") is True
        and not row.get("snapshot_ref")
        and all(marker in detail for marker in EMPTY_ROUND_MARKERS)
    )


def _selected(
    rows: Iterable[dict[str, Any]],
    *,
    status: str,
    kind: str,
    empty_rounds: bool,
    detail_like: str,
    job_ids: Sequence[str] = (),
) -> list[dict[str, Any]]:
    """The terminal rows every stated selector agrees on. Selectors AND, never OR."""
    named = {str(j) for j in job_ids if j}
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "done":
            continue  # never duplicate work that is still queued or in flight
        if named and str(row.get("job_id")) not in named:
            continue
        if status == "failed" and row.get("ok") is not False:
            continue
        if kind and row.get("kind") != kind:
            continue
        if empty_rounds and not _is_empty_round(row):
            continue
        if detail_like and detail_like not in (row.get("detail") or ""):
            continue
        out.append(row)
    return out


def _source_ids(row: dict[str, Any]) -> list[str]:
    payload = row.get("payload") or {}
    return [str(s) for s in (payload.get("source_ids") or [])]


async def cmd_jobs_requeue(
    ctx,  # noqa: ANN001
    user_id: UserId,
    *,
    status: str = "",
    kind: str = "",
    empty_rounds: bool = False,
    detail_like: str = "",
    job_ids: Sequence[str] = (),
    dry_run: bool = False,
    as_json: bool = False,
    out=None,  # noqa: ANN001
    err=None,  # noqa: ANN001
) -> int:
    """Re-queue the selected finished jobs and reopen the material they claimed to digest.

    Exit codes: 0 ok, 1 nothing matched, 2 refused (no selector — see below).

    At least one selector is required. `pkc jobs requeue` with none would re-queue a
    library's entire history, which is not a recovery but an accident, and the place to
    refuse an accident is before it happens.

    `job_ids` (`--job`, repeatable) is the narrowest selector there is: exactly the jobs
    named, and still only when they are finished. A named job that is not a finished job of
    this user is said so on stderr rather than silently skipped.
    """
    if not (status or kind or empty_rounds or detail_like or job_ids):
        print(
            "requeue needs at least one selector: --status, --kind, --empty-rounds, "
            "--detail-like or --job",
            file=err,
        )
        return EXIT_REFUSED

    rows = await ctx.store.list_jobs(user_id)
    selected = _selected(
        rows,
        status=status,
        kind=kind,
        empty_rounds=empty_rounds,
        detail_like=detail_like,
        job_ids=job_ids,
    )
    finished = {str(r.get("job_id")) for r in rows if r.get("status") == "done"}
    for job_id in dict.fromkeys(str(j) for j in job_ids if j):
        if job_id not in finished:
            print(f"job {job_id} is not a finished job of this user; not requeued", file=err)
    if not selected:
        print("no finished job matches those selectors", file=err)
        return EXIT_NOTHING

    by_kind: dict[str, int] = {}
    reopened: list[str] = []
    requeued: list[dict[str, str]] = []
    for row in selected:
        job_kind = str(row.get("kind") or "compile")
        by_kind[job_kind] = by_kind.get(job_kind, 0) + 1
        sources = _source_ids(row) if job_kind == "compile" else []
        reopened.extend(s for s in sources if s not in reopened)
        new_id = ""
        if not dry_run:
            new_id = await ctx.store.enqueue(
                user_id, job_kind, dict(row.get("payload") or {})
            )
            if sources:
                # Digestion is a claim about what canonical holds. The round that made it
                # wrote nothing, so the claim comes off with the job — otherwise the material
                # stays invisible to every "what is still uncompiled" reading there is.
                undigest = getattr(ctx.store, "mark_undigested", None)
                if undigest is not None:
                    await undigest(user_id, sources)
        requeued.append({"from": str(row.get("job_id")), "job_id": new_id, "kind": job_kind})

    line = (
        f"{'would requeue' if dry_run else 'requeued'} {len(selected)} "
        + "(" + ", ".join(f"{k} {n}" for k, n in sorted(by_kind.items())) + ")"
        + f"; sources reopened {len(reopened)}"
    )
    if as_json:
        print(
            json.dumps(
                {
                    "dry_run": dry_run,
                    "requeued": requeued,
                    "by_kind": by_kind,
                    "sources_reopened": reopened,
                    "summary": line,
                },
                ensure_ascii=False,
            ),
            file=out,
        )
    else:
        print(line, file=out)
    return EXIT_OK


async def cmd_jobs_resume(
    ctx,  # noqa: ANN001
    user_id: UserId,
    *,
    job_id: str = "",
    reason_like: str = "",
    every: bool = False,
    as_json: bool = False,
    out=None,  # noqa: ANN001
    err=None,  # noqa: ANN001
) -> int:
    """Start paused jobs again with a fresh retry schedule (`job_retry.py`).

    The end of the retry schedule is a pause, not a verdict: a job that failed six times over
    a day and a half stops asking and waits for a person, because what it is waiting for — an
    account with no money on it, a harness nobody logged in, a tree somebody left dirty —
    does not change by being asked a seventh time. This command is the person saying they
    have done that thing, so the schedule starts over from one minute.

    Exit codes: 0 ok, 1 nothing matched, 2 refused (no selector).

    A selector is required for the same reason `requeue` requires one: `pkc jobs resume` with
    nothing stated would restart a whole library's paused work by accident, and the place to
    refuse an accident is before it happens.
    """
    if not (job_id or reason_like or every):
        print(
            "resume needs a selector: --job, --reason-like or --all",
            file=err,
        )
        return EXIT_REFUSED

    resumed = await ctx.store.resume_jobs(
        user_id, job_id=job_id or None, reason_like=reason_like, every=every
    )
    if not resumed:
        print("no paused job matches those selectors", file=err)
        return EXIT_NOTHING
    line = f"resumed {resumed} paused job{'s' if resumed != 1 else ''}"
    if as_json:
        print(json.dumps({"resumed": resumed, "summary": line}, ensure_ascii=False), file=out)
    else:
        print(line, file=out)
    return EXIT_OK


__all__ = ["cmd_jobs_requeue", "cmd_jobs_resume"]
