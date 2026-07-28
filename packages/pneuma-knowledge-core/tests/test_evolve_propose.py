"""Phase 1 proposal (schema-evolve §B1): a scripted model over the four outcomes
→ the four reasons. Template validation reuses compose_skill (not re-implemented)."""

from pneuma_knowledge_core.evolve.propose import (
    EvolveProposal,
    _EvolveDraft,
    _ProposedFamily,
    propose_evolution,
)
from pneuma_knowledge_core.skill import load_builtin_skill

SKILL = load_builtin_skill()

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
    proposal, reason = await _propose(_EvolveDraft(needs_change=False, rationale="证据不足"))
    assert proposal is None
    assert reason == "no_change"


async def test_needs_change_but_empty_families_is_no_change():
    proposal, reason = await _propose(_EvolveDraft(needs_change=True, families=[]))
    assert proposal is None
    assert reason == "no_change"


async def test_garbage_returns_parse_error():
    # A non-schema payload under include_raw → parse_error (degrade, never raise).
    proposal, reason = await _propose({"unexpected": "shape"})
    assert proposal is None
    assert reason == "parse_error"


async def test_model_exception_returns_parse_error():
    proposal, reason = await _propose(RuntimeError("boom"))
    assert proposal is None
    assert reason == "parse_error"


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
    proposal, reason = await _propose(draft)
    assert proposal is None
    assert reason == "invalid_templates"


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
    proposal, reason = await _propose(draft)
    assert reason == "proposed"
    assert isinstance(proposal, EvolveProposal)
    assert len(proposal.packs) == 1
    pack = proposal.packs[0]
    assert pack.origin == "evolved"
    assert pack.extra_path_templates == ["memory/products/{slug}.md"]
    assert "Atlas" in proposal.rationale  # per-family evidence merged into the rationale
