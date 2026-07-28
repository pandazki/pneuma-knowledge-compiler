import pytest
from pneuma_knowledge_core.domain.intake import (
    BIG_DOCUMENT_CHARS,
    INTAKE_ARCHETYPES,
    IntakePlan,
    archetype_of,
    plan_for_archetype,
    propose_intake,
)


def test_conversation_full_full():
    plan = propose_intake("conversation", "workstream", 5_000, None)
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("full", "full")


def test_note_full_full():
    # A handwritten note declared via declared_type, regardless of carrier kind.
    plan = propose_intake("document", "workstream", 2_000, "note")
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("full", "full")


def test_contract_distill_full():
    # Reference document under the big threshold: contract-scale.
    plan = propose_intake("document", "reference", 12_000, "contract")
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("distill", "full")


def test_novel_card_summary():
    # Reference document over the big threshold: novel-scale.
    plan = propose_intake("document", "reference", BIG_DOCUMENT_CHARS + 1, "novel")
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("card", "summary")


def test_declared_novel_is_card_summary_even_when_short():
    # A declared novel is card/summary regardless of size (M3b: >80k OR declared novel).
    plan = propose_intake("document", "reference", 3_000, "novel")
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("card", "summary")


def test_declared_contract_distills_regardless_of_class():
    # declared_type drives the decision even when source_class is workstream.
    plan = propose_intake("document", "workstream", 5_000, "contract")
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("distill", "full")


def test_workstream_document_full_full():
    plan = propose_intake("document", "workstream", 5_000, None)
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("full", "full")


def test_structured_distill_summary():
    plan = propose_intake("structured", "workstream", 500, None)
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("distill", "summary")


def test_big_threshold_is_strict():
    # Exactly at the threshold is NOT big → contract path.
    plan = propose_intake("document", "reference", BIG_DOCUMENT_CHARS, None)
    assert (plan.canonical_treatment, plan.semantic_indexing) == ("distill", "full")


def test_every_plan_has_rationale():
    plan = propose_intake("conversation", "workstream", 1, None)
    assert plan.rationale
    assert plan.user_confirmed is False


# ---------------------------------------------------------------- archetypes


def test_archetype_registry_is_the_four_expected_intents_in_order():
    assert [a.key for a in INTAKE_ARCHETYPES] == [
        "digest",
        "distill",
        "archive",
        "searchable",
    ]


def test_archetype_knob_pairs_are_all_distinct():
    pairs = {(a.canonical_treatment, a.semantic_indexing) for a in INTAKE_ARCHETYPES}
    assert len(pairs) == len(INTAKE_ARCHETYPES)  # unambiguous reverse lookup


@pytest.mark.parametrize(
    "key,knobs",
    [
        ("digest", ("full", "full")),
        ("distill", ("distill", "full")),
        ("archive", ("card", "summary")),
        ("searchable", ("none", "none")),
    ],
)
def test_plan_for_archetype_maps_to_its_knobs(key, knobs):
    plan = plan_for_archetype(key)
    assert (plan.canonical_treatment, plan.semantic_indexing) == knobs
    assert plan.rationale  # derived from label + summary
    assert plan.user_confirmed is False


def test_plan_for_unknown_archetype_raises():
    with pytest.raises(ValueError):
        plan_for_archetype("nope")


def test_archetype_of_round_trips_every_archetype():
    for a in INTAKE_ARCHETYPES:
        assert archetype_of(plan_for_archetype(a.key)) == a.key


def test_archetype_of_returns_none_for_custom_knob_pair():
    # distill/summary matches no archetype → "custom".
    custom = IntakePlan(
        canonical_treatment="distill", semantic_indexing="summary", rationale="x"
    )
    assert archetype_of(custom) is None


def test_mechanical_document_proposals_map_to_archetypes():
    # Every mechanical document proposal lands on a real archetype (so the UI can highlight).
    assert archetype_of(propose_intake("document", "workstream", 5_000, None)) == "digest"
    assert archetype_of(propose_intake("document", "reference", 12_000, "contract")) == "distill"
    assert (
        archetype_of(propose_intake("document", "reference", BIG_DOCUMENT_CHARS + 1, None))
        == "archive"
    )
