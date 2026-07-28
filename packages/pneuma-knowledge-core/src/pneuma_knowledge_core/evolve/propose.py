"""Phase 1: schema-draft proposal (schema-evolve §2.2).

A strong model reads the owner's current skill + the compile events accrued since the
last evolve + a canonical document overview, and answers one of two ways: a structured
pack draft (new instructions / path templates / contract rules), or "no change" — the
latter being fully legal and common (a destructive schema change must clear real evidence,
not inertia).

Everything mechanical lives here, never in prose:

- the System contract is the byte-stable phase-1 asset (`contracts.phase1_contract`);
- the event summary is a MECHANICAL render (per-path added/revised counts), not the raw
  rows — the model judges evidence, it does not parse a log format;
- a proposal's templates are validated by REUSING `compose_skill`'s additive assertions
  (not a re-implementation): a template that is malformed or would drop a base family makes
  `compose_skill` raise, and the proposal is rejected.

`propose_evolution` returns `(proposal | None, reason)` where reason ∈
{"no_change", "parse_error", "invalid_templates", "proposed"} — so a caller (and a test)
can tell the four outcomes apart without the core having to log. A parse failure degrades
to "no change" (None), it never raises.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from ..recall.fast import invoke_config
from ..skill.pack import SchemaPack, compose_skill
from ..skill.version import SkillVersion
from .contracts import phase1_contract

ProposeReason = Literal["no_change", "parse_error", "invalid_templates", "proposed"]


class EvolveProposal(BaseModel):
    """A phase-1 schema draft: the new families to add, plus one evidence line each.

    Frozen — a proposal is an immutable artifact handed to phase 2 / the review gate. An
    empty `packs` list is illegal (an empty proposal is "no change", expressed as `None`)."""

    model_config = ConfigDict(frozen=True)

    packs: list[SchemaPack]
    rationale: str


# --------------------------------------------------------- LLM structured output schema


class _ProposedFamily(BaseModel):
    """One proposed new schema family, grounded in the incremental data."""

    family: str  # short kebab-ish family name, e.g. "accounts"
    path_template: str  # e.g. "memory/accounts/{slug}.md"
    instructions: str  # what this family collects / its boundary with topics
    evidence: str  # one line pointing at the concrete ≥3 clusters in the increment


class _EvolveDraft(BaseModel):
    """The model's phase-1 answer: "no change", or one-or-more new families."""

    needs_change: bool = False
    rationale: str = ""
    families: list[_ProposedFamily] = Field(default_factory=list)


# ------------------------------------------------------------------- event rendering


def _render_event_summary(recent_events: Sequence[Mapping]) -> str:
    """Mechanical per-path added/revised tally over the compile-event rows.

    Defensive over the row shape (service supplies dict rows): a path key is read from
    `path`/`document_path`, an event type from `type`/`event_type`/`kind`. Rows are
    counted, never interpreted — the model reads the tally, not the log."""
    added: dict[str, int] = {}
    revised: dict[str, int] = {}
    for row in recent_events:
        if not isinstance(row, Mapping):
            continue
        path = str(row.get("path") or row.get("document_path") or "(未知路径)")
        etype = str(row.get("type") or row.get("event_type") or row.get("kind") or "")
        if "revis" in etype:
            revised[path] = revised.get(path, 0) + 1
        else:  # default: treat anything non-revision as an addition
            added[path] = added.get(path, 0) + 1

    paths = sorted(set(added) | set(revised))
    if not paths:
        return "（自上次 evolve 以来无增量编译事件）"
    lines = [
        f"- {p}：新增 {added.get(p, 0)}、修订 {revised.get(p, 0)}" for p in paths
    ]
    return "\n".join(lines)


def _render_doc_tree(doc_paths: Sequence[str]) -> str:
    if not doc_paths:
        return "（暂无 canonical 文档）"
    return "\n".join(f"- {p}" for p in sorted(doc_paths))


def _propose_human(
    current_skill: SkillVersion,
    recent_events: Sequence[Mapping],
    doc_paths: Sequence[str],
) -> str:
    return "\n\n".join(
        [
            "# 当前 skill 指导（含已组合的 pack 家族）\n"
            + current_skill.instructions.rstrip(),
            "# 当前 path 家族（ownership 模板）\n"
            + "\n".join(f"- {t}" for t in current_skill.path_templates),
            "# 自上次 evolve 以来的增量编译事件摘要\n"
            + _render_event_summary(recent_events),
            "# 当前 canonical 文档清单\n" + _render_doc_tree(doc_paths),
        ]
    )


# ------------------------------------------------------------------------- entrypoint


def _pack_from_family(family: _ProposedFamily) -> SchemaPack:
    return SchemaPack(
        pack_id=f"evolved-{family.family.strip()}",
        origin="evolved",
        extra_instructions=family.instructions.strip(),
        extra_path_templates=[family.path_template.strip()],
        extra_contract_rules=(),
    )


async def propose_evolution(
    *,
    model: BaseChatModel,
    current_skill: SkillVersion,
    recent_events: Sequence[Mapping],
    doc_paths: Sequence[str],
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> tuple[EvolveProposal | None, ProposeReason]:
    """Run the phase-1 inference → `(proposal | None, reason)`.

    - `("no_change")` — the model saw no clear signal, or proposed no families (legal,
      common; the evolve task then terminates and waits for the next trigger);
    - `("parse_error")` — the structured output failed / the model errored (degrade to no
      change, never raise);
    - `("invalid_templates")` — a proposed template is malformed or would drop a base
      family (`compose_skill`'s additive assertions reject it);
    - `("proposed")` — a valid additive pack draft."""
    structured = model.with_structured_output(_EvolveDraft, include_raw=True)
    try:
        raw = await structured.ainvoke(
            [
                SystemMessage(content=phase1_contract()),
                HumanMessage(
                    content=_propose_human(current_skill, recent_events, doc_paths)
                ),
            ],
            config=invoke_config("evolve.propose", callbacks, trace_metadata),
        )
    except Exception:  # noqa: BLE001 — a propose failure degrades to "no change", never 500s
        return None, "parse_error"

    parsed = raw.get("parsed") if isinstance(raw, Mapping) else raw
    if not isinstance(parsed, _EvolveDraft):
        return None, "parse_error"

    if not parsed.needs_change or not parsed.families:
        return None, "no_change"

    packs = [_pack_from_family(f) for f in parsed.families]

    # Reuse compose_skill's mechanical additive assertions (template shape + base-template
    # superset) rather than re-implementing them: a malformed / non-additive template makes
    # it raise, and the whole proposal is rejected.
    try:
        compose_skill(current_skill, packs)
    except ValueError:
        return None, "invalid_templates"

    rationale = (parsed.rationale.strip() + "\n\n") if parsed.rationale.strip() else ""
    rationale += "\n".join(f.evidence.strip() for f in parsed.families if f.evidence.strip())
    return EvolveProposal(packs=packs, rationale=rationale.strip()), "proposed"
