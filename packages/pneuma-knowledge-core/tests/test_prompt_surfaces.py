"""The five pins that keep `prompts/surfaces.py` a mechanism instead of a description.

1. **Byte pin** — every surface of kind `assembled` renders byte-for-byte identically to
   the real composition function. A contract that gains a section, loses a clause or
   reorders two of them fails here until the map says the same thing.
2. **Kind pin** — the byte-pinned set and the `assembled` set are the same set. A family
   nobody can pin against a composition function is a family the studio must show as
   independent fragments, not as prose: concatenating `source.preamble.*` produced "the
   ownera conversationThis is…", a sentence no model has ever received.
3. **Context pin** — every fragment and every variant states in words when the model
   receives it. Those are the clauses whose position explains nothing.
4. **Coverage pin** — every catalog key belongs to at least one surface. A new key with no
   surface fails on the commit that introduces it.
5. **Note pin** — an assembly the byte pin had to hand runtime values to, or one that offers
   a clause the deployment picks between, is a TEMPLATE and says so. This is the pin the
   verification pass asked for: the studio had been showing `compile.system` with
   `{instructions}` still in it under the words "what the model received".
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.compile.challenge import (
    ChallengeGap,
    render_compensation_guidance,
)
from pneuma_knowledge_core.evolve.contracts import phase1_contract, phase2_contract
from pneuma_knowledge_core.ingest.source_types import _context_stream_guidance
from pneuma_knowledge_core.prompts import (
    DEFAULTS,
    override_prompts,
    prompt,
    reset_prompt_overrides,
)
from pneuma_knowledge_core.prompts.surfaces import (
    ASSEMBLED,
    BLOCK,
    FRAGMENTS,
    GROUPS,
    SLOT,
    SURFACES,
    VARIANT,
    render_surface,
    segment_context,
    segment_label,
    segments_missing_context,
    shared_with,
    surface_by_id,
    surface_keys,
    surface_note,
    surfaces_missing_note,
    uncovered_keys,
    variant_keys,
)
from pneuma_knowledge_core.recall.briefing import briefing_contract
from pneuma_knowledge_core.recall.deep import deep_contract
from pneuma_knowledge_core.recall.fast import selector_contract, structured_answer_contract
from pneuma_knowledge_core.recall.suggestion import detail_contract, live_context_contracts
from pneuma_knowledge_core.skill.contract import render_system_contract
from pneuma_knowledge_core.skill.version import SkillVersion

# The compile SystemMessage is the one assembly whose non-catalog halves are runtime data
# (a skill's own domain section, its path templates, its identity). The pin supplies them
# and compares the whole thing.
SKILL = SkillVersion.from_parts(
    skill_id="pin-demo",
    version="v1",
    instructions="# Domain\n\nRecord decisions and who owns them.\n",
    path_templates=["people/{slug}.md", "decisions/{slug}.md"],
)

COMPILE_FIELDS = {
    "templates": "\n".join(f"  - {t}" for t in SKILL.path_templates),
    "skill_id": SKILL.skill_id,
    "version": SKILL.version,
    "instructions": SKILL.instructions.rstrip(),
}

CHALLENGE_CONTRACT = "the compile contract body"
CHALLENGE_GAPS = [
    ChallengeGap(question="who owns the migration?", missing_fact="the owner is unstated")
]


def _compensation_gaps_field() -> str:
    return "\n".join(
        f"- {g.question}\n  missing: {g.missing_fact}" for g in CHALLENGE_GAPS
    )


# (surface id, the real composition function, the runtime fields it was given)
ASSEMBLIES: tuple[tuple[str, object, dict[str, str]], ...] = (
    ("recall.fast", lambda: selector_contract(), {}),
    ("recall.fast_structured", lambda: structured_answer_contract(), {}),
    (
        "recall.fast_deliberated",
        lambda: structured_answer_contract(deliberate=True),
        {},
    ),
    ("recall.deep", lambda: deep_contract(), {}),
    ("recall.briefing", lambda: briefing_contract(), {}),
    ("recall.suggestion", lambda: live_context_contracts()["general"], {}),
    ("recall.suggestion_detail", lambda: detail_contract(), {}),
    ("evolve.phase1", lambda: phase1_contract(), {}),
    ("evolve.phase2", lambda: phase2_contract(), {}),
    ("compile.system", lambda: render_system_contract(SKILL), COMPILE_FIELDS),
    (
        "compile.groom_contract",
        lambda: prompt("compile.groom.contract"),
        {},
    ),
    (
        "challenge.questions",
        lambda: prompt("compile.challenge.questions_system", contract=CHALLENGE_CONTRACT),
        {"contract": CHALLENGE_CONTRACT},
    ),
    ("challenge.reflect", lambda: prompt("compile.challenge.reflect_system"), {}),
    (
        "challenge.compensation",
        lambda: render_compensation_guidance(CHALLENGE_GAPS),
        {"gaps": _compensation_gaps_field()},
    ),
    (
        "intake.source_guidance",
        lambda: _context_stream_guidance().render(),
        {},
    ),
    ("persona.profile", lambda: prompt("persona.profile_instruction"), {}),
)


@pytest.fixture(autouse=True)
def _clean_overrides():
    reset_prompt_overrides()
    yield
    reset_prompt_overrides()


# ───────────────────────────────────────────────────────────────────── pin 1: bytes


@pytest.mark.parametrize(("surface_id", "compose", "fields"), ASSEMBLIES)
def test_the_registry_renders_the_real_composition_byte_for_byte(
    surface_id, compose, fields
):
    surface = surface_by_id(surface_id)
    assert surface.pinned, f"{surface_id} is byte-pinned, so it must declare pinned=True"
    assert render_surface(surface, fields=fields) == compose()


# ────────────────────────────────────────────────────────────────────── pin 2: kind


def test_the_assembled_surfaces_are_exactly_the_byte_pinned_ones():
    """Reading a surface as prose has to be EARNED by a composition function checking it.

    Both directions matter. A surface claiming `assembled` with no pin is an unverified
    claim about what the model receives; a pin on a surface declared `fragments` would be
    a pin nobody looks at. So the two sets are one set.
    """
    pinned = {surface_id for surface_id, _, _ in ASSEMBLIES}
    assert {s.id for s in SURFACES if s.pinned} == pinned
    assert {s.id for s in SURFACES if s.kind == ASSEMBLED} == pinned


def test_every_surface_declares_one_of_the_two_kinds():
    for surface in SURFACES:
        assert surface.kind in (ASSEMBLED, FRAGMENTS), surface.id


def test_a_fragment_family_refuses_to_render_an_assembly():
    """The fix for "the ownera conversationThis is…", stated as a mechanism: the
    concatenation is not available to be shown, here or anywhere downstream."""
    surface = surface_by_id("intake.source_preamble")
    assert surface.kind == FRAGMENTS
    with pytest.raises(ValueError, match="fragment family"):
        render_surface(surface)


def test_no_assembled_surface_ever_concatenates_two_preamble_alternatives():
    """The regression proper. The two shortest alternatives of the family are a word each
    ("the owner", "a conversation"); if any surface's rendered text ever puts them back
    to back, the gibberish is back."""
    joined = prompt("source.preamble.owner_default") + prompt(
        "source.preamble.stream_scene_default"
    )
    for surface in SURFACES:
        if surface.kind != ASSEMBLED:
            continue
        assert joined not in render_surface(surface), surface.id


# ─────────────────────────────────────────────────────────────────── pin 3: context


def test_every_fragment_and_variant_says_when_the_model_receives_it():
    missing = segments_missing_context()
    assert not missing, (
        f"{len(missing)} clause(s) a reader cannot place: a fragment family's clauses and "
        "every variant need a bilingual context sentence, because nothing about their "
        "position explains when they are used — "
        + ", ".join(f"{sid}:{key}" for sid, key in missing)
    )


def test_a_context_sentence_is_not_the_label_said_twice():
    """A label names the clause; a context says WHEN it is used. A context that only
    repeats the label teaches a newcomer nothing, which is the defect this pin exists for."""
    for surface in SURFACES:
        for segment in surface.segments:
            context = segment_context(segment)
            if context is None:
                continue
            label = segment_label(segment.key)
            where = f"{surface.id}:{segment.key}"
            assert context["en"] != label["en"] and context["zh"] != label["zh"], where
            # A sentence, not a stub: enough room to have said an actual condition.
            assert len(context["en"]) >= 24 and len(context["zh"]) >= 6, where


def test_an_assembled_block_needs_no_context_because_its_position_is_one():
    """Stated so the asymmetry is deliberate rather than an omission somebody 'fixes'."""
    fast = surface_by_id("recall.fast")
    head = next(seg for seg in fast.segments if seg.key == "recall.fast.contract_head")
    assert head.role == BLOCK and segment_context(head) is None


def test_an_overlay_reaches_the_assembled_render_the_same_way_it_reaches_the_code():
    """The registry resolves through the same seam the framework does — otherwise the
    studio's 'effective' preview would be a paraphrase of what the model receives."""
    override_prompts({"recall.cite.source_level": "cite the source id and stop there."})
    assert render_surface(surface_by_id("recall.fast")) == selector_contract()
    assert "cite the source id and stop there." in selector_contract()


def test_a_supplied_catalog_renders_without_registering_anything_in_this_process():
    """How the console renders a deployment's overlays: resolution comes from a mapping,
    not from this process's registered overrides (which stay empty here)."""
    catalog = {**DEFAULTS, "recall.close.answer_honestly": "Say what the records say."}
    rendered = render_surface(surface_by_id("recall.fast"), catalog=catalog)
    assert "Say what the records say." in rendered
    assert "Say what the records say." not in selector_contract()


def test_runtime_placeholders_stay_literal_until_a_field_is_supplied():
    """The studio renders them as chips; the pin supplies them. Both from one renderer."""
    preview = render_surface(surface_by_id("compile.system"))
    assert "{templates}" in preview and "{instructions}" in preview
    assert "{templates}" not in render_surface(
        surface_by_id("compile.system"), fields=COMPILE_FIELDS
    )


# ────────────────────────────────────────────────────────────────────── pin 5: note

# surface id → "its byte pin had to supply runtime values", read off the pin table above so
# the two cannot disagree: a surface the pin has to hand `{instructions}` to is by definition
# a surface whose preview is missing `{instructions}`.
RUNTIME_FIELDS = {surface_id: bool(fields) for surface_id, _, fields in ASSEMBLIES}


def test_an_assembly_that_is_really_a_template_says_so():
    """The defect this pin exists for: the studio showed `compile.system` with `{templates}`,
    `{skill_id}`, `{version}`, `{instructions}` unfilled and "no profile supplied" in §2,
    under a heading promising the model's own message. Two mechanical triggers — the byte pin
    having to supply runtime fields, and a variant clause the deployment picks instead — and
    either one obliges the registry to carry the banner."""
    missing = surfaces_missing_note(RUNTIME_FIELDS)
    assert not missing, (
        f"{len(missing)} assembled surface(s) are templates presented as finished messages: "
        + ", ".join(missing)
    )


def test_the_surfaces_whose_pin_supplies_runtime_values_are_the_ones_with_slots_left():
    """The trigger is not a hand-kept list: a surface needs runtime fields exactly when its
    own render still has placeholders the framework fills. Stated so that adding a runtime
    slot to a contract cannot quietly stop obliging a note."""
    from pneuma_knowledge_core.prompts import template_fields

    for surface_id, _, fields in ASSEMBLIES:
        surface = surface_by_id(surface_id)
        left = template_fields(render_surface(surface))
        for name in fields:
            assert name in left, f"{surface_id} does not declare {{{name}}} at all"


def test_a_note_belongs_to_an_assembly_and_is_never_the_summary_again():
    for surface in SURFACES:
        note = surface_note(surface)
        if note is None:
            continue
        assert surface.kind == ASSEMBLED, (
            f"{surface.id} is a fragment family: it has no assembled text to caveat, so a "
            "template banner would be explaining something the payload does not carry"
        )
        assert note["en"] != surface.summary_en and note["zh"] != surface.summary_zh
        assert len(note["en"]) >= 40 and len(note["zh"]) >= 20, surface.id


def test_the_assemblies_with_no_note_are_the_ones_that_need_none():
    """Stated positively, so "no note" stays a claim somebody made rather than an omission:
    these two render bytes the model receives whole, with nothing substituted and no branch."""
    for surface_id in ("intake.source_guidance",):
        surface = surface_by_id(surface_id)
        assert surface_note(surface) is None
        assert not RUNTIME_FIELDS[surface_id] and not variant_keys(surface)


# ────────────────────────────────────────────────────────────────── pin 4: coverage


def test_every_catalog_key_belongs_to_at_least_one_surface():
    missing = uncovered_keys()
    assert not missing, (
        f"{len(missing)} prompt catalog key(s) belong to no surface, so nobody can find "
        f"them in the Prompt Studio: {', '.join(missing)}"
    )


def test_no_surface_names_a_key_the_catalog_does_not_have():
    for surface in SURFACES:
        for key in surface_keys(surface):
            assert key in DEFAULTS, f"{surface.id} names {key!r}, which is not a catalog key"


def test_a_key_is_never_declared_twice_inside_one_surface():
    for surface in SURFACES:
        keys = surface_keys(surface)
        assert len(keys) == len(set(keys)), f"{surface.id} declares a key twice"


# ────────────────────────────────────────────────────────────────── registry shape


def test_surface_ids_are_unique_and_every_group_is_declared():
    ids = [surface.id for surface in SURFACES]
    assert len(ids) == len(set(ids))
    groups = {gid for gid, _, _ in GROUPS}
    for surface in SURFACES:
        assert surface.group in groups, f"{surface.id} is in undeclared group {surface.group!r}"


def test_every_surface_states_a_bilingual_title_and_summary():
    for surface in SURFACES:
        for value in (surface.title_en, surface.title_zh, surface.summary_en, surface.summary_zh):
            assert value.strip()


def test_every_segment_has_a_readable_bilingual_label():
    for surface in SURFACES:
        for key in surface_keys(surface):
            label = segment_label(key)
            assert label["en"].strip() and label["zh"].strip()
            # Derived labels carry the family name; neither face may fall back to the raw
            # dotted key, which would be a label that teaches nothing.
            assert label["en"] != key and label["zh"] != key


def test_every_segment_role_is_one_of_the_three():
    for surface in SURFACES:
        for segment in surface.segments:
            assert segment.role in (BLOCK, SLOT, VARIANT)


def test_a_slot_filler_is_declared_as_a_slot_segment_of_the_same_surface():
    """The renderer refuses a dangling filler; this states it as a registry invariant."""
    for surface in SURFACES:
        by_key = {segment.key: segment for segment in surface.segments}
        for segment in surface.segments:
            for slot in segment.slots:
                for key in slot.keys:
                    assert key in by_key, f"{surface.id}: {segment.key} fills from unlisted {key}"
                    assert by_key[key].role == SLOT


def test_the_shared_spine_reports_every_surface_it_moves():
    assert set(shared_with("recall.fast", "recall.spine")) == {
        "recall.deep",
        "recall.briefing",
        "recall.suggestion",
        "recall.fast_structured",
        "recall.fast_deliberated",
    }
    assert shared_with("recall.fast", "recall.fast.contract_head") == (
        "recall.fast_structured",
        "recall.fast_deliberated",
    )


def test_shared_spine_uses_source_time_for_recorded_relative_expressions():
    """The evidence clock and live-input clock must never collapse into one as_of clock."""
    english = DEFAULTS["recall.spine"]
    assert "expressions in recorded evidence" in english
    assert "source's occurrence date" in english
    assert "owner's live input use the as_of value" in english
    assert "old source's \"yesterday\" or \"last week\"" in english
    assert "unambiguous calendar convention" in english
    assert "instead of inventing endpoints" in english

    from pneuma_knowledge_core.prompts import chinese_overlay

    chinese = chinese_overlay()["recall.spine"]
    assert "已记录证据里的表达以该来源的发生日" in chinese
    assert "本轮输入里的表达才以输入旁边标注的 as_of 值" in chinese
    assert "不能用本轮提问时间重新解释旧来源" in chinese
    assert "只有证据给出了无歧义的日历口径" in chinese
    assert "不要编造区间端点" in chinese
