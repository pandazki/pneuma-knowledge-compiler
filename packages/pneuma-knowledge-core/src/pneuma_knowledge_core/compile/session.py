"""DraftSession: everything one compile round holds BESIDE its draft.

`run_compile` keeps the round in local variables — the source handle map, the round and its
budget, whether the low-water notice was given, whether the round was cut off, the gate's
violations waiting for the repair round. A langchain round can: it lives for the whole round
inside one function call. A round driven from a command line cannot — each command is a fresh
process — so the same facts need a form that survives between invocations
(docs/design/coding-agent-mode.md ruling 3, §6).

This is that form, and it is deliberately a plain frozen record with a JSON document on
either side of it: the session is ephemeral, neither an authority nor a kept record (I2),
and it is deleted when the round ends however it ends. Two hashes ride along — the rendered
task and the skill's content hash — so a draft opened under one contract cannot be finished
under another, which is the one thing a resumable round could otherwise get wrong silently.

Core defines the state form; the service stores it (a row per job, beside the queue it
belongs to).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

Round = Literal["first", "repair"]


def _handle_order(handle: str) -> int:
    """The supply position one `sNN` handle names. Numeric, not lexical: `s100` comes after
    `s99`, and a job with a hundred sources is a job the ordering still has to describe."""
    digits = handle.removeprefix("s")
    return int(digits) if digits.isdigit() else 0


def content_sha256(text: str) -> str:
    """The digest form the session pins its two renderings with."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DraftSession:
    """One open compile round, as data.

    `handle_by_real` is the compile-boundary alias map (`runner.run_compile`): real source id
    → the per-job `sNN` handle the task text and the model's citations use. Both directions
    are derived from this one mapping rather than stored twice, because two stored maps are
    two things that can disagree about the same job.
    """

    user_id: str
    job_id: str
    #: real source id → `sNN`, in the order the sources were supplied.
    handle_by_real: dict[str, str] = field(default_factory=dict)
    round: Round = "first"
    budget: int = 0
    spent: int = 0
    #: has this round's low-water notice already been delivered?
    noticed: bool = False
    #: did the previous round end by exhausting its budget rather than by finishing?
    cut_off: bool = False
    #: sha256 of the rendered task content and of the skill's own content hash — the two
    #: axes of "the same job under the same contract".
    task_sha256: str = ""
    skill_id: str = ""
    skill_version: str = ""
    skill_content_hash: str = ""
    #: the compile options this round was opened under, carried so every command judges by
    #: the numbers `open` resolved rather than by whatever the environment says now.
    overview_budget_chars: int = 0
    overview_required_after_claims: int = 0
    max_tool_calls: int = 0
    #: the gate's findings from a failed `finish`, waiting for the repair round.
    violations: tuple[tuple[str, str, str], ...] = ()
    commit_message: str = "compile"

    # --- derived -------------------------------------------------------------

    @property
    def source_ids(self) -> tuple[str, ...]:
        """This job's source ids, in supply order (the order the handles were minted in)."""
        return tuple(
            real
            for real, _ in sorted(
                self.handle_by_real.items(), key=lambda kv: _handle_order(kv[1])
            )
        )

    @property
    def real_by_handle(self) -> dict[str, str]:
        """`sNN` → real source id — the alias map the gate resolves citations through."""
        return {handle: real for real, handle in self.handle_by_real.items()}

    @property
    def remaining(self) -> int:
        return max(self.budget - self.spent, 0)

    def spend(self, calls: int = 1) -> "DraftSession":
        return replace(self, spent=self.spent + calls)

    def with_notice(self) -> "DraftSession":
        return replace(self, noticed=True)

    # --- state form ----------------------------------------------------------

    def to_state(self) -> dict:
        return {
            "user_id": self.user_id,
            "job_id": self.job_id,
            "handle_by_real": dict(self.handle_by_real),
            "round": self.round,
            "budget": int(self.budget),
            "spent": int(self.spent),
            "noticed": bool(self.noticed),
            "cut_off": bool(self.cut_off),
            "task_sha256": self.task_sha256,
            "skill_id": self.skill_id,
            "skill_version": self.skill_version,
            "skill_content_hash": self.skill_content_hash,
            "overview_budget_chars": int(self.overview_budget_chars),
            "overview_required_after_claims": int(self.overview_required_after_claims),
            "max_tool_calls": int(self.max_tool_calls),
            "violations": [list(v) for v in self.violations],
            "commit_message": self.commit_message,
        }

    @classmethod
    def from_state(cls, state: Mapping[str, object]) -> "DraftSession":
        round_ = str(state.get("round") or "first")
        return cls(
            user_id=str(state.get("user_id") or ""),
            job_id=str(state.get("job_id") or ""),
            handle_by_real={
                str(k): str(v)
                for k, v in dict(state.get("handle_by_real") or {}).items()
            },
            round="repair" if round_ == "repair" else "first",
            budget=int(state.get("budget") or 0),
            spent=int(state.get("spent") or 0),
            noticed=bool(state.get("noticed")),
            cut_off=bool(state.get("cut_off")),
            task_sha256=str(state.get("task_sha256") or ""),
            skill_id=str(state.get("skill_id") or ""),
            skill_version=str(state.get("skill_version") or ""),
            skill_content_hash=str(state.get("skill_content_hash") or ""),
            overview_budget_chars=int(state.get("overview_budget_chars") or 0),
            overview_required_after_claims=int(
                state.get("overview_required_after_claims") or 0
            ),
            max_tool_calls=int(state.get("max_tool_calls") or 0),
            violations=tuple(
                (str(v[0]), str(v[1]), str(v[2]))
                for v in (state.get("violations") or ())
                if len(tuple(v)) == 3
            ),
            commit_message=str(state.get("commit_message") or "compile"),
        )


def handles_for(source_ids: Sequence[str]) -> dict[str, str]:
    """real source id → `sNN`, minted exactly as `run_compile` mints them.

    One derivation, called by both executors: the handle a citation is written against is a
    fact about the job, and two implementations of it would be two jobs.
    """
    return {str(sid): f"s{i + 1:02d}" for i, sid in enumerate(source_ids)}


__all__ = ["DraftSession", "Round", "content_sha256", "handles_for"]
