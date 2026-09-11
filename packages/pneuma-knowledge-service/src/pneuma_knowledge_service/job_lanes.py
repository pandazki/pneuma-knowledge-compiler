"""The two lanes one library's queue drains in (architecture.md §5).

A library's queue used to hand out exactly one job at a time, whatever it was. That rule
exists for ONE reason — the per-user canonical library has a single writer, and the claim is
what makes it single — and it was paid by every job that never touches canonical: on the
machine this was written for, 273 `episodes` rounds of six to eight minutes each stood behind
271 compile rounds, two and a half days of a queue in which half the jobs could not have
written a byte of the library.

So the kinds are classified, mechanically, into two lanes:

- the **canonical lane** — every kind that CAN write the library. Its rule is byte-for-byte
  the rule the whole queue used to have: one job in flight, and no open draft of its own
  lane. The git single writer is exactly as strict as it was.
- the **derived lane** — kinds that never open canonical. One job in flight here too, and
  it is a DIFFERENT slot, so one derived job and one canonical job may run at the same time.

Two facts make the classification safe to trust rather than to remember:

1. `lane_of` answers CANONICAL for any kind it does not know. A kind added later is in the
   strict lane until somebody classifies it here, so forgetting this table can only cost
   parallelism — never the single writer.
2. Every predicate that used to say "this tenant has a job in flight" now says "this
   tenant has a job in flight IN THIS LANE", expressed as one SQL fragment over
   `DERIVED_LANE_KINDS` in both polarities (`lane_sql`). There is one list, and the two
   lanes are its two sides.

The kind strings are literals here on purpose: this module is read by the Postgres adapter
AND by the worker, and importing the modules that define the constants
(`workers/compile_worker.py`, `groom_service.py`, …) from something the adapter imports would
close an import cycle. `tests/test_job_lanes.py` pins every one of those constants against
this table, so the duplication cannot drift in silence.
"""

from __future__ import annotations

#: Names, in the fixed order anything that must hold both lanes takes them (a claim that is
#: not lane-scoped, the startup self-heal) — one order, so two such bodies cannot deadlock.
CANONICAL_LANE = "canonical"
DERIVED_LANE = "derived"
LANES: tuple[str, ...] = (CANONICAL_LANE, DERIVED_LANE)

#: Every job kind this worker dispatches, its lane, and why it is in that lane. The reason is
#: the reviewable part: a kind is in the derived lane only when nothing it does can reach the
#: canonical library, and "reach" includes the branch an evolve round writes.
JOB_LANES: dict[str, tuple[str, str]] = {
    "compile": (
        CANONICAL_LANE,
        "the round's whole product is canonical commits through the citation gate",
    ),
    "evolve": (
        CANONICAL_LANE,
        "phase 2 commits the reorganization onto a review branch of the canonical repository",
    ),
    "evolve_adopt": (
        CANONICAL_LANE,
        "adoption merges that branch and commits the new schema manifest",
    ),
    "groom": (
        CANONICAL_LANE,
        "a rollover rewrites the page and commits its closed volume",
    ),
    "archive": (
        CANONICAL_LANE,
        "one commit moves the document under archive/ and writes the archive record",
    ),
    "challenge": (
        CANONICAL_LANE,
        "it commits nothing itself, but it judges coverage against canonical HEAD and queues "
        "the compensation compile — it belongs in the lane of the compile it is about",
    ),
    "index": (
        DERIVED_LANE,
        "L1 rows, L2 vectors and component projections: derived, rebuildable, never canonical",
    ),
    "episodes": (
        DERIVED_LANE,
        "records a kept chunk manifest and replaces that source's L2 vectors; canonical is "
        "never opened",
    ),
    "recall_projection": (
        DERIVED_LANE,
        "one consultation folded into the derived use-side ledger",
    ),
    "recall_rebuild": (
        DERIVED_LANE,
        "the same ledger re-derived from the kept consultation records",
    ),
}

#: The derived lane as a list, for the one SQL parameter both lane predicates are built from.
DERIVED_LANE_KINDS: tuple[str, ...] = tuple(
    kind for kind, (lane, _) in JOB_LANES.items() if lane == DERIVED_LANE
)

#: The one place the two lanes have to wait for each other, named here because it is a fact
#: about the lanes rather than about storage: a `compile` is not claimed while the derived
#: lane still has work queued or claimed about one of its OWN sources. PR #28 put
#: index → episodes → compile in order through `order_at`; with two lanes that ordering can
#: no longer hold a compile back, because those two jobs drain in the other lane.
#:
#: BOTH derived kinds, not just `episodes`: the episodes job does not exist yet when a source
#: is imported — the index job is what commissions it — so a compile that waited only for a
#: queued episodes job would overtake the index job instead and compile a source whose
#: semantic episodes were never judged, which is the regression PR #28 was about. They are
#: also the only two derived kinds whose `source_id` is an L0 source (a `recall_projection`
#: names a consultation), which is why the list is explicit rather than "the derived lane".
COMPILE_KIND = "compile"
SOURCE_DERIVED_KINDS: tuple[str, ...] = ("index", "episodes")


def lane_of(kind: str) -> str:
    """Which lane a job of `kind` drains in — CANONICAL for anything unclassified.

    The default is the strict lane and not the fast one: a kind nobody has classified yet may
    write the library for all this function knows, and the cost of being wrong that way is a
    queue that is slower than it could be, against a second writer on a git repository."""
    entry = JOB_LANES.get(kind)
    return entry[0] if entry is not None else CANONICAL_LANE


def lane_reason(kind: str) -> str:
    """Why `kind` is in its lane, for a message a person reads. Empty when unclassified."""
    entry = JOB_LANES.get(kind)
    return entry[1] if entry is not None else ""


def lane_sql(column: str, lane: str) -> str:
    """`column` (a job's `kind`) belongs to `lane`, as one SQL fragment.

    Consumes exactly one parameter — `list(DERIVED_LANE_KINDS)` — whichever lane is asked
    for, so the two lanes are two polarities of one list and cannot disagree about a kind.
    A NULL kind (a draft whose job row is gone) is canonical, by the same rule `lane_of`
    applies to a kind it does not know.
    """
    if lane == DERIVED_LANE:
        return f"({column} = ANY(%s))"
    return f"(NOT COALESCE({column} = ANY(%s), FALSE))"


def same_lane_sql(left: str, right: str) -> str:
    """`left` and `right` (two job `kind` columns) are in the SAME lane.

    For a claim that is about ONE named job rather than about a lane: the lane it must respect
    is the lane of the row it is claiming, and that is a fact of the row rather than of the
    caller. Consumes two parameters, both `list(DERIVED_LANE_KINDS)`.
    """
    return (
        f"(COALESCE({left} = ANY(%s), FALSE) = COALESCE({right} = ANY(%s), FALSE))"
    )
