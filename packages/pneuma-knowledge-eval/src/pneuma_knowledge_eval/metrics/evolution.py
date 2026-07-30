"""Group E — evolution: does the structure notice misfit, and respond proportionally?

This is the group with no prior art in this repository, and it is the one that decides
whether "evolvable" is a property of the system or a slogan. It is built around one
correction learned the hard way: **do not reward having acted.**

An evolve run that returns `no_change` is very often the CORRECT output — a schema that
still fits its material should not be reorganized, and a metric that scores "proposed" above
"no_change" would train the system toward churn, which is the exact failure the review gate
exists to prevent. So this group separates two measurements that a naive score would merge:

- PRESSURE (a property of the material and the current schema): what share of each round's
  new claims lands in a catch-all family, and how many near-duplicate clusters straddle
  family boundaries. High sustained pressure is the signal that the schema no longer fits.
- RESPONSE (a property of the system's judgement): given the pressure series, was the
  observed decision aligned? No proposal under low pressure is aligned. No proposal under
  sustained high pressure is a miss. A proposal under low pressure is churn. Alignment is
  reported as a labelled verdict per window, never as a single score that could be gamed by
  acting more.

When a trajectory contains no evolve event at all — the common case, because evolve is
triggered by business rhythm rather than by every compile — this group reports exactly that,
with the pressure series intact. "No evolution observed" is a finding; an empty section or a
crash is not.

Also here, because they are only meaningful across an evolve boundary: MOVE FIDELITY (a
moved claim must be moved, not rewritten — byte-identical text, anchor preserved) and SCHEMA
STABILITY (the family floor only grows; a removed family would silently orphan every
document under it).
"""

from __future__ import annotations

from typing import Any

from ..artifacts import Checkpoint, Trajectory, family_of, is_catchall
from .common import (
    NEAR_DUPLICATE_THRESHOLD,
    Matcher,
    char_similarity,
    cluster,
    memoized,
    near_duplicate_pairs,
    rate,
)

#: A round whose new claims land in catch-all families at or above this share is "under
#: pressure". Half of everything arriving with no family that owns it is the point at which a
#: reader can no longer predict where a fact lives.
HIGH_PRESSURE_SHARE = 0.5

#: How many consecutive high-pressure rounds constitute "sustained" — i.e. the point where
#: NOT proposing a schema change becomes a miss rather than restraint.
SUSTAINED_ROUNDS = 3


def _new_claims(previous: Checkpoint | None, current: Checkpoint) -> list[Any]:
    """Claims whose anchor did not exist anywhere in the previous snapshot."""
    before = previous.anchor_set if previous is not None else frozenset()
    return [claim for claim in current.claims if str(claim.anchor) not in before]


def catchall_pressure(trajectory: Trajectory) -> dict[str, Any]:
    """Share of each round's NEW claims that landed in a catch-all family.

    Measured on new claims only: counting all claims would let a large well-organized past
    mask a badly-fitting present, which is the opposite of what this signal is for.
    """
    templates = list(trajectory.path_templates)
    series: list[dict[str, Any]] = []
    for previous, current in zip((None, *trajectory.checkpoints), trajectory.checkpoints):
        new_claims = _new_claims(previous, current)
        by_family: dict[str, int] = {}
        catchall = 0
        unowned = 0
        for claim in new_claims:
            template = family_of(claim.document_path, templates)
            key = template or "(unowned)"
            by_family[key] = by_family.get(key, 0) + 1
            if template is None:
                unowned += 1
            elif is_catchall(template):
                catchall += 1
        share = rate(catchall, len(new_claims))
        series.append(
            {
                "checkpoint": current.label,
                "new_claims": len(new_claims),
                "catchall_claims": catchall,
                "catchall_share": share,
                "unowned_claims": unowned,
                "by_family": dict(sorted(by_family.items())),
                "under_pressure": bool(share is not None and share >= HIGH_PRESSURE_SHARE),
            }
        )
    longest_run = 0
    run = 0
    for row in series:
        run = run + 1 if row["under_pressure"] else 0
        longest_run = max(longest_run, run)
    shares = [row["catchall_share"] for row in series if row["catchall_share"] is not None]
    return {
        "status": "ok",
        "high_pressure_share": HIGH_PRESSURE_SHARE,
        "series": series,
        "rounds_under_pressure": sum(1 for row in series if row["under_pressure"]),
        "longest_pressure_run": longest_run,
        "sustained": longest_run >= SUSTAINED_ROUNDS,
        "mean_catchall_share": round(sum(shares) / len(shares), 6) if shares else None,
    }


def cross_family_duplication(
    trajectory: Trajectory,
    *,
    threshold: float = NEAR_DUPLICATE_THRESHOLD,
    matcher: Matcher = char_similarity,
) -> dict[str, Any]:
    """Near-duplicate clusters that straddle family boundaries — the second misfit signal.

    The same statement filed under two different families means neither family owns the
    subject: either a family is missing, or two existing ones overlap. Distinct from group C's
    duplication count, which asks about redundancy regardless of where it sits.
    """
    templates = list(trajectory.path_templates)
    scored = memoized(matcher)
    series: list[dict[str, Any]] = []
    head_samples: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        texts = {
            f"{claim.document_path}#{claim.anchor}": claim.text for claim in checkpoint.claims
        }
        groups = cluster(near_duplicate_pairs(texts, threshold=threshold, matcher=scored))
        straddling: list[dict[str, Any]] = []
        for members in groups:
            families = {
                family_of(member.split("#", 1)[0], templates) or "(unowned)"
                for member in members
            }
            if len(families) > 1:
                straddling.append({"members": members, "families": sorted(families)})
        series.append(
            {
                "checkpoint": checkpoint.label,
                "duplicate_clusters": len(groups),
                "cross_family_clusters": len(straddling),
                "claims_total": len(checkpoint.claims),
            }
        )
        head_samples = straddling[:10]
    return {
        "status": "ok",
        "threshold": threshold,
        "series": series,
        "head": series[-1],
        "head_samples": head_samples,
    }


def _evolve_checkpoints(trajectory: Trajectory) -> list[Checkpoint]:
    """Checkpoints that are not compile commits — i.e. candidate evolve commits.

    Identified structurally (no `compile <job_id>` subject) rather than by commit prose,
    because the evolve commit message is an overridable prompt surface and a deployment's
    wording must not change what the evaluator can see.
    """
    return [cp for cp in trajectory.checkpoints if cp.job_id is None and cp.index > 0]


def evolution_response(trajectory: Trajectory) -> dict[str, Any]:
    """Alignment between observed pressure and the observed schema decision.

    Verdicts, not scores: `aligned_restraint` (low pressure, no change), `missed_pressure`
    (sustained pressure, no change), `responded` (change under pressure), `churn` (change
    without pressure). A single number here would inevitably reward acting.
    """
    pressure = catchall_pressure(trajectory)
    evolve_commits = _evolve_checkpoints(trajectory)
    tasks = list(trajectory.evolve_tasks)
    task_statuses: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "unknown")
        task_statuses[status] = task_statuses.get(status, 0) + 1
    observed_change = bool(evolve_commits) or bool(
        [task for task in tasks if str(task.get("status")) in {"adopted", "accepted", "applied"}]
    )
    if not evolve_commits and not tasks:
        verdict = "missed_pressure" if pressure["sustained"] else "aligned_restraint"
        return {
            "status": "no_evolution_events",
            "reason": (
                "the trajectory records no evolve commit and no evolve task: schema response "
                "cannot be scored, and no score is imputed"
            ),
            "verdict": verdict,
            "pressure": pressure,
            "evolve_commits": [],
            "evolve_task_statuses": {},
        }
    if observed_change:
        verdict = "responded" if pressure["sustained"] else "churn"
    else:
        verdict = "missed_pressure" if pressure["sustained"] else "aligned_restraint"
    return {
        "status": "ok",
        "verdict": verdict,
        "pressure": pressure,
        "evolve_commits": [
            {"checkpoint": cp.label, "ref": cp.ref, "subject": cp.subject}
            for cp in evolve_commits
        ],
        "evolve_task_statuses": dict(sorted(task_statuses.items())),
    }


def move_fidelity(trajectory: Trajectory) -> dict[str, Any]:
    """Across every checkpoint boundary: was a relocated claim MOVED or silently rewritten?

    "Move, do not rewrite" is the evolve discipline that keeps L3 projection, compile events
    and git blame continuous. A claim whose anchor changed document while its text changed
    too is a rewrite wearing a move's identity, and it is invisible to the gate (both states
    are individually legal).
    """
    moved: list[dict[str, Any]] = []
    rewritten: list[dict[str, Any]] = []
    for previous, current in zip(trajectory.checkpoints, trajectory.checkpoints[1:]):
        before = {str(claim.anchor): claim for claim in previous.claims}
        for claim in current.claims:
            anchor = str(claim.anchor)
            old = before.get(anchor)
            if old is None or old.document_path == claim.document_path:
                continue
            record = {
                "anchor": anchor,
                "from": old.document_path,
                "to": claim.document_path,
                "at": current.label,
            }
            moved.append(record)
            # The projection folds section context into `text` under v2; compare the raw
            # claim body only, which is what "byte-identical move" means in canonical.
            if old.text != claim.text:
                rewritten.append(record)
    dropped_reported = sum(len(task.get("dropped") or []) for task in trajectory.evolve_tasks)
    return {
        "status": "ok" if moved or trajectory.evolve_tasks else "no_moves_observed",
        "moves_observed": len(moved),
        "moves_verbatim": len(moved) - len(rewritten),
        "verbatim_rate": rate(len(moved) - len(rewritten), len(moved)),
        "rewritten_while_moving": rewritten[:10],
        "dropped_anchors_reported_by_tasks": dropped_reported,
        "samples": moved[:10],
    }


def schema_stability(trajectory: Trajectory) -> dict[str, Any]:
    """The monotone-floor audit: families and claim identities may be added, never removed.

    Mirrors the ratchet the composition mechanism enforces on the schema (a composed skill's
    templates are a superset of its base's). Here it is checked against the ARTIFACTS: if a
    family stopped being used AND its documents disappeared, the floor moved down and
    something was silently orphaned.
    """
    templates = list(trajectory.path_templates)
    series: list[dict[str, Any]] = []
    previous_families: set[str] = set()
    previous_anchors: frozenset[str] = frozenset()
    violations: list[dict[str, Any]] = []
    for checkpoint in trajectory.checkpoints:
        families = {
            family_of(path, templates) or "(unowned)" for path in checkpoint.files
        }
        lost_families = sorted(previous_families - families)
        lost_anchors = sorted(previous_anchors - checkpoint.anchor_set)
        if lost_families:
            violations.append(
                {"checkpoint": checkpoint.label, "kind": "family_removed", "detail": lost_families}
            )
        if lost_anchors:
            violations.append(
                {
                    "checkpoint": checkpoint.label,
                    "kind": "anchor_removed",
                    "detail": lost_anchors[:10],
                }
            )
        series.append(
            {
                "checkpoint": checkpoint.label,
                "families_in_use": len(families),
                "families_added": len(families - previous_families),
                "families_removed": len(lost_families),
                "anchors": len(checkpoint.anchor_set),
            }
        )
        previous_families = families
        previous_anchors = checkpoint.anchor_set
    return {
        "status": "ok",
        "series": series,
        "family_churn_events": sum(row["families_removed"] for row in series),
        "floor_violations": violations,
        "invariants": {
            "family_floor_is_monotone": not any(
                row["kind"] == "family_removed" for row in violations
            ),
            "anchor_floor_is_monotone": not any(
                row["kind"] == "anchor_removed" for row in violations
            ),
        },
    }


def evolution_metrics(
    trajectory: Trajectory, *, matcher: Matcher = char_similarity
) -> dict[str, Any]:
    """Group E entry point: pressure, response alignment, move fidelity, schema stability."""
    return {
        "group": "E_evolution",
        "response": evolution_response(trajectory),
        "cross_family_duplication": cross_family_duplication(trajectory, matcher=matcher),
        "move_fidelity": move_fidelity(trajectory),
        "schema_stability": schema_stability(trajectory),
    }


__all__ = [
    "HIGH_PRESSURE_SHARE",
    "SUSTAINED_ROUNDS",
    "catchall_pressure",
    "cross_family_duplication",
    "evolution_metrics",
    "evolution_response",
    "move_fidelity",
    "schema_stability",
]
