"""Per-source treatment instruction rendering (M3b, architecture.md §4).

The mapping is mechanical (fixed strings), rides the HumanMessage task (not the
byte-stable SystemMessage), and defaults to `full` when unspecified.
"""

from datetime import datetime, timezone

from pneuma_knowledge_core.skill import load_builtin_skill, render_system_contract
from pneuma_knowledge_core.compile.runner import _treatment_instruction, _render_task
from pneuma_knowledge_core.domain.ids import UserId, SourceId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)


def _source(sid: str) -> NormalizedSource:
    return NormalizedSource(
        raw=RawSource(
            source_id=SourceId(sid),
            user_id=UserId("u-1"),
            kind="document",
            title=f"doc-{sid}",
            mime="text/markdown",
            checksum=sid,
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=0, text="body")],
        structure=StructureMap(),
    )


def test_each_treatment_emits_its_fixed_instruction():
    sources = [_source("a"), _source("b"), _source("c")]
    treatments = {"a": "full", "b": "distill", "c": "card"}
    task = _render_task(sources, [], treatments)
    assert _treatment_instruction("full") in task
    assert _treatment_instruction("distill") in task
    assert _treatment_instruction("card") in task


def test_distill_names_materials_card_only():
    task = _render_task([_source("a")], [], {"a": "distill"})
    assert "materials/{slug}.md" in task
    assert "targeted distillation" in task


def test_missing_or_unknown_treatment_defaults_to_full():
    default_task = _render_task([_source("a")], [], {})
    unknown_task = _render_task([_source("a")], [], {"a": "bogus"})
    assert _treatment_instruction("full") in default_task
    assert _treatment_instruction("full") in unknown_task


def test_treatment_rides_human_task_not_system_contract():
    # _render_task builds the HumanMessage body; the fixed strings live only here.
    # Asserted on the treatment's own marker rather than a phrase from its prose, so
    # rewording a treatment's guidance does not break a test about WHERE it is rendered.
    task = _render_task([_source("a")], [], {"a": "card"})
    assert _treatment_instruction("card") in task
    assert "treatment=card" in task
    assert "treatment=card" not in render_system_contract(load_builtin_skill())
