"""Phase 1 proposal (schema-evolve §B1): a scripted model over the four outcomes
→ the four reasons. Template validation reuses compose_skill (not re-implemented)."""

from pneuma_knowledge_core.evolve.propose import (
    EvolveProposal,
    _EvolveDraft,
    _ProposedFamily,
    _propose_human,
    _render_doc_tree,
    propose_evolution,
)
from pneuma_knowledge_core.prompts import (
    chinese_overlay,
    default_catalog,
    override_prompts,
    prompt,
    reset_prompt_overrides,
)
from pneuma_knowledge_core.skill import load_skill_base

SKILL = load_skill_base("v1")

RECENT_EVENTS = [
    {"type": "claim_added", "path": "memory/topics/atlas.md"},
    {"type": "claim_added", "path": "memory/topics/lumen.md"},
    {"type": "claim_revised", "path": "memory/topics/nova.md"},
]
DOC_PATHS = [
    "memory/topics/atlas.md",
    "memory/topics/lumen.md",
    "memory/topics/nova.md",
]


class _StructuredStub:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
        if isinstance(self._payload, Exception):
            raise self._payload
        return {"parsed": self._payload, "raw": None}


class _FakeModel:
    def __init__(self, payload):
        self._payload = payload

    def with_structured_output(self, schema, include_raw=False):  # noqa: ANN001, ARG002
        return _StructuredStub(self._payload)


async def _propose(payload):
    return await propose_evolution(
        model=_FakeModel(payload),
        current_skill=SKILL,
        recent_events=RECENT_EVENTS,
        doc_paths=DOC_PATHS,
    )


async def test_no_change_returns_none_no_change():
    proposal, reason, rationale = await _propose(_EvolveDraft(needs_change=False, rationale="证据不足"))
    assert proposal is None
    assert reason == "no_change"
    # The reasoning is the whole product of a no-change round: it must come back even though
    # there is no proposal to carry it, or the round records a verdict and nothing else.
    assert rationale == "证据不足"


async def test_needs_change_but_empty_families_is_no_change():
    proposal, reason, rationale = await _propose(_EvolveDraft(needs_change=True, families=[]))
    assert proposal is None
    assert reason == "no_change"
    assert rationale == ""


async def test_garbage_returns_parse_error():
    # A non-schema payload under include_raw → parse_error (degrade, never raise).
    proposal, reason, rationale = await _propose({"unexpected": "shape"})
    assert proposal is None
    assert reason == "parse_error"
    assert rationale == ""  # nothing was read, so nothing is claimed to have been read


async def test_model_exception_returns_parse_error():
    proposal, reason, rationale = await _propose(RuntimeError("boom"))
    assert proposal is None
    assert reason == "parse_error"
    assert rationale == ""


async def test_invalid_template_shape_returns_invalid_templates():
    # A malformed template (a non-{slug} placeholder) makes compose_skill's additive
    # assertion raise → invalid_templates. The validation is compose_skill's, not a
    # re-implementation.
    draft = _EvolveDraft(
        needs_change=True,
        rationale="r",
        families=[
            _ProposedFamily(
                family="products",
                path_template="memory/{bad}/{slug}.md",  # illegal non-{slug} placeholder
                instructions="收编产品台账。",
                evidence="topics 下已积累 3 个个人产品主题。",
            )
        ],
    )
    proposal, reason, rationale = await _propose(draft)
    assert proposal is None
    assert reason == "invalid_templates"
    # A rejected draft still reports what it was trying to do — that is what makes the
    # rejection reviewable rather than just recorded.
    assert "topics 下已积累 3 个个人产品主题。" in rationale


async def test_valid_proposal_returns_proposed():
    draft = _EvolveDraft(
        needs_change=True,
        rationale="总体理由",
        families=[
            _ProposedFamily(
                family="products",
                path_template="memory/products/{slug}.md",
                instructions="收编产品台账；与 topics 的分界是以个人产品为主体。",
                evidence="topics 下已积累 Atlas、Lumen、Nova 三个个人产品主题。",
            )
        ],
    )
    proposal, reason, rationale = await _propose(draft)
    assert reason == "proposed"
    assert isinstance(proposal, EvolveProposal)
    assert len(proposal.packs) == 1
    pack = proposal.packs[0]
    assert pack.origin == "evolved"
    assert pack.extra_path_templates == ["memory/products/{slug}.md"]
    assert "Atlas" in proposal.rationale  # per-family evidence merged into the rationale
    assert rationale == proposal.rationale  # one text, reachable with or without the proposal


# ---------------------------------------------------- the components' demand section


def test_the_human_turn_is_byte_identical_when_no_component_reported_anything():
    """The seam's whole byte-identity guarantee, at the one place it can be checked: with
    `demand_evidence=None` the proposal's human message is the message this deployment has
    always sent, character for character. `None` is the absence of a block — not an empty
    one."""
    baseline = _propose_human(SKILL, RECENT_EVENTS, DOC_PATHS)

    assert _propose_human(SKILL, RECENT_EVENTS, DOC_PATHS, None) == baseline
    assert prompt("evolve.propose.demand_header") not in baseline
    assert baseline.endswith(_render_doc_tree(DOC_PATHS))  # the document list is still last


def test_a_reported_block_lands_as_a_fourth_section_after_the_document_list():
    """It rides the HUMAN turn (I5: the byte-stable System contract never moves), last, so
    the model reads what the library HOLDS before what it was asked for."""
    block = "## attention\n热文档 memory/people/mei-lin.md heat 12"
    text = _propose_human(SKILL, RECENT_EVENTS, DOC_PATHS, block)

    assert text.startswith(_propose_human(SKILL, RECENT_EVENTS, DOC_PATHS))
    assert text.endswith(prompt("evolve.propose.demand_header") + "\n" + block)


def test_the_demand_header_is_translated_like_every_other_segment():
    """A language pack is total by construction (test_prompt_lang_zh pins both directions);
    this pins the one thing that check cannot see — that the key is really reached through
    the catalog rather than written into the module as a literal."""
    assert "evolve.propose.demand_header" in default_catalog()
    assert "evolve.propose.demand_header" in chinese_overlay()
    try:
        override_prompts(chinese_overlay())
        zh = _propose_human(SKILL, RECENT_EVENTS, DOC_PATHS, "命中：3")
        assert prompt("evolve.propose.demand_header") in zh
        assert "评估" not in zh  # no leaked English header from the untranslated catalog
    finally:
        reset_prompt_overrides()


async def test_the_evidence_reaches_the_model_through_propose_evolution():
    """The parameter is not decoration: what a caller passes is what the model receives."""
    seen: list[str] = []

    class _Capturing(_StructuredStub):
        async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
            seen.append(messages[-1].content)
            return {"parsed": _EvolveDraft(needs_change=False, rationale="r"), "raw": None}

    class _Model:
        def with_structured_output(self, schema, include_raw=False):  # noqa: ANN001, ARG002
            return _Capturing(None)

    await propose_evolution(
        model=_Model(),
        current_skill=SKILL,
        recent_events=RECENT_EVENTS,
        doc_paths=DOC_PATHS,
        demand_evidence="## attention\nmiss ×4: 阿宝的报销流程是什么？",
    )
    assert "miss ×4: 阿宝的报销流程是什么？" in seen[0]

    await propose_evolution(
        model=_Model(), current_skill=SKILL, recent_events=RECENT_EVENTS, doc_paths=DOC_PATHS
    )
    assert seen[1] == _propose_human(SKILL, RECENT_EVENTS, DOC_PATHS)


def test_the_family_bar_is_a_judgement_and_the_count_is_evidence_for_it():
    """2026-09-04: the bar read "only when `memory/topics/` already contains three or more
    independent topic clusters of the same shape" — a fixed number standing where the
    judgement belongs, in the one contract whose whole job is judging a structure nobody can
    enumerate in advance.

    What decides is recurrence, stability of shape, and fitting no current family; a count is
    evidence for that judgement and never the decision. The two things this contract must not
    lose while saying so: "no change" stays the default, and the phase stays additive."""
    from pneuma_knowledge_core.evolve.contracts import phase1_contract

    en = phase1_contract()
    assert "What a new family has to show" in en
    assert "one shape RECURRING in `memory/topics/`" in en
    assert "A count is evidence for it and never the decision" in en
    assert "three or more independent topic clusters of the same shape" not in en
    # the two loads it still carries
    assert '**"No change" is the default' in en
    assert "Propose **additive** changes only" in en

    zh = chinese_overlay()["evolve.phase1_contract"]
    assert "一个新族要拿出什么" in zh
    assert "数量是判断的证据，从来不是判断本身" in zh
    assert "三个及以上同形的独立主题簇" not in zh
    assert "「不改」是默认答案" in zh
    assert "只提**增量**改动" in zh
