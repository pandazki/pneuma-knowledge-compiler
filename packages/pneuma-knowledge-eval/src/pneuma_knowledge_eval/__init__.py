"""Evaluation for an evolvable knowledge structure: what the mechanism cannot enforce.

WHY THIS PACKAGE EXISTS
-----------------------
The purpose of a durable knowledge structure is that cognition stays **explicit,
grounded, auditable, evolvable and usable without rereading the raw evidence** — and that
this keeps holding while both the data and the models change underneath it.

The division of labour is deliberate: **the mechanism enforces, evaluation measures what
the mechanism cannot enforce.** The compile gate already hard-rejects structural
violations (anchor continuity, anchor uniqueness, citation legality, provenance on new
claims, dead links, frontmatter, path ownership); `compose_skill` keeps the schema floor
monotone; canonical is forward-only. Re-testing those invariants would only re-test the
gate. So this package does two things instead:

1. an **honesty audit** of the artifacts the mechanism claims to guarantee — a gate is a
   claim about the future, an artifact is evidence about the past, and history predates
   any given gate rule, so a snapshot may legitimately violate a rule added later. Those
   are reported as-is, never repaired;
2. the actual measurement target: **judgement quality** — what got admitted, how it was
   layered, whether the structure stayed navigable, and how it responded to pressure.
   None of that is decidable by a mechanical gate.

EVALUATING A TRAJECTORY, NOT A SNAPSHOT
---------------------------------------
The quality of an evolving structure is a property of its **trajectory**. A terminal
snapshot cannot distinguish convergence from luck: a knowledge base that got the right
answer on round 12 after thrashing through rounds 1-11 is not the same artifact as one
that was right from round 3 and stayed right. Canonical's git history hands us a free
checkpoint sequence — one commit per compile — so every metric here is a **time series
over compile checkpoints**, not a single number at HEAD.

SIX METRIC GROUPS
-----------------
A. grounded      — provenance honesty: citation resolvability, anchor continuity, links
B. admission     — admission judgement against a labelled corpus: recall over time, noise
                   exclusion, admission latency, supersession correctness
C. layering      — thread-vs-detail boundary: compression, duplication, verbatim leakage
D. navigability  — canonical's two jobs: follow-the-thread reachability, bird's-eye
                   sublinearity, slug/family health
E. evolution     — misfit pressure, response alignment, move fidelity, schema stability.
                   Deliberately does NOT reward "having acted": `no_change` under low
                   pressure is a correct output.
F. usability_qa  — outcome question answering (accuracy by category), the optional LLM arm

MODES
-----
`mechanical` is pure and offline: zero LLM, zero network, deterministic, CI-runnable.
`full` adds the embedding matcher and the LLM judge; when credentials are missing it
**refuses loudly** rather than silently degrading to the mechanical matcher, because a
silent degradation would publish a weaker number under the stronger label.

Metric functions are pure `(artifacts) -> numbers`. They judge artifacts, never the
process that produced them, so a preset bundle and a live stack are the same input type.
"""

from __future__ import annotations

from .artifacts import (
    Checkpoint,
    PgDumps,
    Snapshot,
    SourceRecord,
    Trajectory,
    build_trajectory,
    load_git_trajectory,
    load_pg_dumps,
    load_preset_trajectory,
    load_repo_trajectory,
)
from .errors import EvalDependencyError, EvalInputError
from .scorecard import build_scorecard, render_report
from .truth import TruthSet, load_84d_truth_set, load_frozen_truth_manifest

__all__ = [
    "Checkpoint",
    "EvalDependencyError",
    "EvalInputError",
    "PgDumps",
    "Snapshot",
    "SourceRecord",
    "Trajectory",
    "TruthSet",
    "build_scorecard",
    "build_trajectory",
    "load_84d_truth_set",
    "load_frozen_truth_manifest",
    "load_git_trajectory",
    "load_pg_dumps",
    "load_preset_trajectory",
    "load_repo_trajectory",
    "render_report",
]
