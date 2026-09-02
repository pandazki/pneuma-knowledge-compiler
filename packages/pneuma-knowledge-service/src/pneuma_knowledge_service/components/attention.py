"""The `attention` component: what the library is actually being asked for.

WHAT IT ADDS
------------
Every other layer of this system describes what the library HOLDS. Compiling reports what
it wrote, the glance reports what exists, evolve reads both and proposes structure. None of
them can see the other half of the question — which of those pages anybody reads, which
family has not been consulted since it was created, and which questions came back empty.
That knowledge is not in L0 and not in canonical, because it is not knowledge about the
owner's world at all: it is knowledge about the library's USE.

THE LEDGER IS NOT THIS COMPONENT'S
----------------------------------
It is the framework's, and it is built in: the worker's `recall_projection` handler applies
`recall_access_hits` / `recall_access_misses` for every `business` consultation, with no
component registered and none required (`access_stats.py`). This component is the FACES over
that ledger — a report for evolve, a deep tool, a fast path — and it owns none of its rows.

Which is why `on_recall` here is a no-op and `rebuild` has nothing to redo. A component
whose channel also incremented the framework's tables would count every consultation twice
the day it was registered, and the counts would then depend on which components an operator
had switched on — the one thing a ledger measuring use must not depend on.

Unregister it and the stats keep accumulating; only the faces go.

WHY NO SCORE IS STORED
----------------------
Heat is `Σ hits × 0.5^(age_days / half_life)`, computed at read time by the pure `heat` in
`access_stats.py`. Storing it would make the half-life a migration instead of a knob, and —
worse — would make the tables something other than a function of the records that produced
them. As they stand, a `recall_rebuild` job replays this user's `business` consultations
into a replacement set and swaps it in, reproducing the tables byte-for-byte. That replay is
the whole argument for calling this projection derived (I2/I7) while its substrate is
neither L0 nor canonical: use-side records are KEPT, never derived, and everything projected
from them is rebuilt from them by the same `rebuild_derived` as every other derived layer.

WHAT IT REPORTS AND WHAT IT DOES NOT
------------------------------------
`evolve_evidence` is the payoff: the evolve proposal already reads what was written, and
now reads what was read. The block is a REPORT — hot documents with their integer heat,
families holding real claims that nobody consulted, unanswered questions with their counts —
in plain lines, with no prose and no advice. Whether a cold family should be dissolved or a
repeated miss deserves a new one is exactly the judgement the evolve model exists to make,
and a component that argued for a conclusion would be answering it in advance.

WHAT IT READS IS NEVER AN AUTHORITY
-----------------------------------
Nothing here reaches canonical. No gate, contract or compile input reads a row of the
ledger; the canonical face this component holds is read-only (I7) and is used for exactly
two questions — which documents exist and how many claims they hold. Every target is an
ordinary address (a claim anchor, a document path, a source id — I4), user_id is first
everywhere (I1), and with the component unregistered every seam renders as it did before it
existed.

TIME
----
`day` is the record's `created_at` in UTC (`access_stats.utc_day`), and neither the ledger
nor this component holds a zone opinion on purpose: the `time` component owns the subject's
calendar and resolves it from the owner's profile, and a second, divergent answer to "which
day is this" is precisely the thing that makes two projections disagree about the same
afternoon. A decay measured in half-lives of days is insensitive to the boundary; an index
keyed by a day is not, which is why the one that has to be right is `time`'s and this one
states its own rule out loud.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta, timezone

from langchain_core.tools import StructuredTool
from pneuma_knowledge_core.canonical_glance import family_of
from pneuma_knowledge_core.components import BaseComponent
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.recall.fast import RetrievedClaim
from pneuma_knowledge_core.recall.paths import PathResult
from pneuma_knowledge_core.recall.projection import project_document_claims
from pydantic import BaseModel, Field

from ..access_stats import heat

_log = logging.getLogger(__name__)

#: A family is COLD only if it holds a document with real accumulated content — a page with
#: two claims that nobody reads is a page that was just created, not a family nobody wants.
COLD_FAMILY_MIN_CLAIMS = 8

#: Output bounds for the rendered block. Each is paired with an explicit "…and N more" line:
#: a report that silently stops reads as "that was everything".
HOT_DOCUMENT_LINES = 20
MISS_LINES = 10

#: The fast path's own depth. The framework ranks what comes back against the question and
#: spends the path's `cap` on that order (core recall/component_rank.py), so this bounds the
#: LEDGER walk, not the answer.
DEFAULT_PATH_LIMIT = 40


# ------------------------------------------------------------------------ args schemas


class AttentionArgs(BaseModel):
    limit: int = Field(
        default=DEFAULT_PATH_LIMIT,
        description="how many of the hottest claims to walk (default 40)",
    )


# ------------------------------------------------------------------------ the component


class AttentionComponent(BaseComponent):
    name = "attention"

    def __init__(
        self,
        *,
        content=None,
        canonical=None,
        templates=None,
        half_life_days: float = 14.0,
        window_days: int = 60,
        evidence_chars: int = 1500,
    ) -> None:
        self._content = content
        self._canonical = canonical
        # `templates(user_id) -> Sequence[str]`: the user's composed path templates, so the
        # report groups documents by the families the CONTRACT declares rather than by a
        # second notion of ownership invented here. Injected by the application (wiring), for
        # the same reason `user_info` is: reading a user's skill is a service concern, and a
        # component that cannot get one still renders — under one unfiled group.
        self._templates = templates
        self._half_life_days = float(half_life_days)
        self._window_days = max(1, int(window_days))
        self._evidence_chars = max(0, int(evidence_chars))

    # --- face: the use-side projection channel -----------------------------------------

    async def on_recall(self, user_id: str, record) -> None:  # noqa: ANN001
        """Nothing. The ledger this component reads is the framework's, and the framework
        applies it — for every `business` consultation, whether or not this component is
        registered (`access_stats.apply_record`, run by the `recall_projection` job).

        Kept as an explicit no-op rather than inherited silently, because the absence is the
        design: a component that also incremented those tables would double every count the
        day an operator switched it on, and a ledger of USE that depended on which faces
        were enabled would be measuring the deployment rather than the readers.
        """
        return None

    async def rebuild(self, user_id: str) -> None:
        """Nothing here either, and for the same reason: this component owns no rows.

        The ledger is re-derived by `access_stats.rebuild_access_stats`, which the
        `recall_rebuild` job runs BEFORE it reaches any component — so by the time this is
        called, the tables these faces read have already been replayed from
        `consultations`. Replaying them again here would do the same work twice and produce
        the same rows; delegating means owning no second copy of the replay at all.
        """
        return None

    # --- reading the ledger ------------------------------------------------------------

    async def _window(self, user_id: UserId, *, days: int) -> tuple[list[dict], list[dict], date, date]:
        """The user's rows for the last `days` days, plus the window's own bounds.

        CLOSED at both ends. The report prints `window A..B`, so reading rows dated after B
        made the header a false statement about its own contents — and those rows have a
        negative age, which is exactly the input the decay curve turns into amplification.
        """
        today = datetime.now(timezone.utc).date()
        since = today - timedelta(days=max(1, int(days)) - 1)
        hits: list[dict] = []
        misses: list[dict] = []
        if self._content is not None and hasattr(self._content, "access_hits_since"):
            hits = await self._content.access_hits_since(user_id, since, until=today)
        if self._content is not None and hasattr(self._content, "access_misses_since"):
            misses = await self._content.access_misses_since(user_id, since, until=today)
        return hits, misses, since, today

    def _heat_by_target(
        self, rows: Sequence[Mapping], kind: str, *, now: date
    ) -> dict[str, float]:
        by_ref: dict[str, dict[date, int]] = {}
        for row in rows:
            if str(row.get("target_kind") or "") != kind:
                continue
            ref = str(row.get("target_ref") or "")
            by_ref.setdefault(ref, {})[row["day"]] = int(row.get("hits") or 0)
        return {
            ref: heat(days, now=now, half_life_days=self._half_life_days)
            for ref, days in by_ref.items()
        }

    async def _families(self, user_id: UserId) -> list[str]:
        if self._templates is None:
            return []
        try:
            return [str(t) for t in (await self._templates(str(user_id)) or ())]
        except Exception:  # noqa: BLE001 — a report never fails on the contract lookup
            _log.warning("path templates unavailable for %s; reporting unfiled", user_id)
            return []

    async def _claim_counts(self, user_id: UserId) -> dict[str, int]:
        """path → how many claims that document holds. The one canonical read the cold half
        needs: a family is only cold if something real in it is going unread."""
        if self._canonical is None:
            return {}
        try:
            docs = await self._canonical.list(user_id)
        except Exception:  # noqa: BLE001 — a report never fails on a canonical read
            _log.warning("canonical unavailable for %s; reporting no cold family", user_id)
            return {}
        return {doc.path: len(list(project_document_claims(doc))) for doc in docs}

    def _cap(self, lines: list[str]) -> str:
        """The block, cut to the character budget on a LINE boundary, and said out loud.

        Cutting mid-line would hand the evolve model half a path and a heat with no target.
        What does not fit is counted, because a report that silently stops is a report that
        claims the library is smaller than it is.
        """
        text = "\n".join(lines)
        if self._evidence_chars <= 0 or len(text) <= self._evidence_chars:
            return text
        kept: list[str] = []
        used = 0
        for line in lines:
            if used + len(line) + 1 > self._evidence_chars:
                break
            kept.append(line)
            used += len(line) + 1
        # Counted BEFORE the notice joins `kept`, or the notice counts itself as one of the
        # lines it is apologising for and the report understates the cut by one.
        omitted = len(lines) - len(kept)
        kept.append(f"(cut to {self._evidence_chars} characters; {omitted} more line(s) not shown)")
        return "\n".join(kept)

    async def report(self, user_id: UserId, *, days: int) -> str | None:
        """The whole rendering: hot documents by family, cold families, unanswered questions.

        `None` when the window holds nothing at all. That emptiness is checked on the TABLES
        and not on whether there would be something to say: a library with no recorded
        consultations has cold families by definition, and reporting them would tell an
        evolve round that nobody reads a library nobody has yet asked.
        """
        uid = UserId(user_id)
        hits, misses, since, today = await self._window(uid, days=days)
        if not hits and not misses:
            return None

        lines = [
            f"window {since.isoformat()}..{today.isoformat()} "
            f"({max(1, int(days))} day(s)); heat = hits halved every "
            f"{self._half_life_days:g} day(s)"
        ]

        document_heat = self._heat_by_target(hits, "document", now=today)
        templates = await self._families(uid)
        grouped: dict[str, list[tuple[str, float]]] = {}
        for path, value in document_heat.items():
            owner = family_of(path, templates) if templates else None
            grouped.setdefault(owner or "(unfiled)", []).append((path, value))

        lines.append("# documents read, hottest first")
        if not document_heat:
            lines.append("- (no canonical document was consulted in this window)")
        shown = 0
        for family in sorted(grouped, key=lambda f: (f == "(unfiled)", f)):
            members = sorted(grouped[family], key=lambda item: (-item[1], item[0]))
            lines.append(f"{family}")
            for path, value in members:
                if shown >= HOT_DOCUMENT_LINES:
                    break
                lines.append(f"- {path} heat {int(value)}")
                shown += 1
        if len(document_heat) > shown:
            lines.append(f"  …and {len(document_heat) - shown} more document(s).")

        claim_counts = await self._claim_counts(uid)
        touched_families = {
            family_of(path, templates)
            for path in document_heat
            if templates and family_of(path, templates)
        }
        cold: list[tuple[str, int, int]] = []
        for template in templates:
            if template in touched_families:
                continue
            members = {
                path: count
                for path, count in claim_counts.items()
                if family_of(path, templates) == template
            }
            if not any(count >= COLD_FAMILY_MIN_CLAIMS for count in members.values()):
                continue
            cold.append((template, len(members), sum(members.values())))
        if cold:
            lines.append(
                f"# families with claims and no reads in this window "
                f"(at least one document holding {COLD_FAMILY_MIN_CLAIMS}+ claims)"
            )
            for template, documents, claims in cold:
                lines.append(f"- {template}: {documents} document(s), {claims} claim(s)")

        by_question: dict[str, int] = {}
        for row in misses:
            question = str(row.get("question") or "")
            by_question[question] = by_question.get(question, 0) + int(row.get("count") or 0)
        if by_question:
            lines.append("# questions answered with nothing, most asked first")
            ordered = sorted(by_question.items(), key=lambda item: (-item[1], item[0]))
            for question, count in ordered[:MISS_LINES]:
                lines.append(f"- {count}× {question}")
            if len(ordered) > MISS_LINES:
                lines.append(f"  …and {len(ordered) - MISS_LINES} more question(s).")

        return self._cap(lines)

    # --- face: evolve evidence ---------------------------------------------------------

    async def evolve_evidence(self, user_id: str) -> str | None:
        """What this library was asked for, for the schema-evolve proposal to judge.

        Facts only — paths, integers, questions verbatim. What a cold family or a repeated
        miss MEANS is the evolve model's ruling, and a component that phrased it as a
        recommendation would be making that ruling in a place with no gate over it.
        """
        try:
            return await self.report(UserId(user_id), days=self._window_days)
        except Exception:  # noqa: BLE001 — a component never fails the evolve round
            _log.warning("attention report failed for %s; contributing nothing", user_id)
            return None

    # --- face: deep-recall tools ---------------------------------------------------------

    def recall_tools(self, user_id: str, *, documents=None) -> list[StructuredTool]:
        component = self
        uid = UserId(user_id)

        async def attention_report(days: int = 30) -> str:
            report = await component.report(uid, days=days)
            if report is None:
                return (
                    f"no consultation was recorded in the last {max(1, int(days))} day(s), "
                    "so nothing is known about what this library is being asked for."
                )
            return report

        return [
            StructuredTool.from_function(
                coroutine=attention_report,
                name="attention_report",
                description=(
                    "What this library has been ASKED for lately, as opposed to what it "
                    "holds: the documents consultations actually read (hottest first, "
                    "grouped by the contract family that owns them), the families holding "
                    "real claims that nobody consulted in the window, and the questions "
                    "that came back with nothing, verbatim and counted. Use it for "
                    "questions about the library's own use — what is being worked on, what "
                    "has gone quiet, what people keep asking and not getting. It reports "
                    "counts and never judges them. days is a whole number of days back "
                    "from today, default 30."
                ),
            )
        ]

    # --- face: the fast path -------------------------------------------------------------

    async def hottest_claims(
        self, user_id: UserId, *, limit: int = DEFAULT_PATH_LIMIT, documents=None
    ) -> PathResult:
        """The claims consultations have been reading, hottest first.

        Everything the ledger knows, in heat order, up to the walk's own depth — the
        framework ranks it against the question and spends the path's cap on that order
        (core recall/component_rank.py). A claim whose anchor no longer resolves against the
        pinned documents is DROPPED rather than rendered as an address with no text: the
        ledger is derived and may name a claim a later compile superseded away.
        """
        uid = UserId(user_id)
        hits, _misses, _since, today = await self._window(uid, days=self._window_days)
        claim_heat = self._heat_by_target(hits, "claim", now=today)
        if not claim_heat:
            return PathResult()

        if documents is not None:
            docs = list(documents)
        elif self._canonical is not None:
            docs = list(await self._canonical.list(uid))
        else:
            return PathResult()
        projected = {
            str(claim.anchor): claim
            for doc in docs
            for claim in project_document_claims(doc)
        }

        ordered = sorted(claim_heat.items(), key=lambda item: (-item[1], item[0]))
        claims: list[RetrievedClaim] = []
        for ref, value in ordered[: max(1, int(limit))]:
            claim = projected.get(ref.removeprefix("c:"))
            if claim is None:
                continue
            claims.append(
                RetrievedClaim(
                    anchor=claim.anchor,
                    document_path=claim.document_path,
                    section_path=claim.section_path,
                    text=claim.text,
                    citations=claim.citations,
                    paths=("attention",),
                    score=1.0,
                    labels=(f"heat {int(value)}",),
                )
            )
        return PathResult(claims=tuple(claims))

    def fast_paths(self, user_id: str):
        component = self
        uid = UserId(user_id)

        class AttentionPath:
            name = "attention"
            description = (
                "The claims this library's own readers have been consulting lately, "
                "hottest first — recency-weighted counts over what past answers were built "
                "from, not a relevance estimate. It answers \"what is being worked on\", "
                "\"what has everyone been looking at\", \"what is current around here\": a "
                "question about the library's ATTENTION rather than about its subject "
                "matter. It knows nothing about a topic it has not been asked about, so a "
                "question naming a subject is better served by ordinary retrieval. limit "
                "is how many of the hottest claims to walk."
            )
            args_schema = AttentionArgs
            cap = 12

            async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):
                return await component.hottest_claims(
                    uid, limit=args.limit, documents=documents
                )

        return [AttentionPath()]


__all__ = [
    "COLD_FAMILY_MIN_CLAIMS",
    "AttentionArgs",
    "AttentionComponent",
]
