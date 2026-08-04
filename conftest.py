"""Suite-wide startup wiring: the test harness plays the part an application plays.

The framework ships no domain contract. `load_skill_base(version)` returns only what an
application registered at startup, and raises otherwise — see
`packages/pneuma-knowledge-core/src/pneuma_knowledge_core/skill/version.py`. Every
mechanism test that needs *a* contract to compile against therefore needs someone to have
done that wiring, and in this suite that someone is this file: it registers the
reference `personal-knowledge` contracts shipped by `pneuma-knowledge-strategies` under
their own version strings, exactly as the scaffold driver (`scaffold/templates/app.py`) or `examples/opc`
register theirs.

Registration is redone before EVERY test rather than once per session, because
`reset_skill_bases()` is process-wide: a test that exercises the empty-registry failure
path would otherwise leave the rest of the suite unwired. Tests that want the unwired
state call `reset_skill_bases()` themselves and get it for the duration of that test only.

This is harness convenience, not a hidden default — that the framework itself supplies
nothing is asserted directly in `packages/pneuma-knowledge-core/tests/test_skill_contract.py`
and `tests/test_strategy_provenance.py`.
"""

from __future__ import annotations

import pytest
from pneuma_knowledge_core.skill import SkillVersion, register_skill_base
from pneuma_knowledge_strategies import list_strategies

REFERENCE_SKILL_ID = "personal-knowledge"


def skill_from_strategy(strategy) -> SkillVersion:
    """One shipped strategy → a runnable SkillVersion, hash included.

    Kept in one place because the argument list IS the provenance: the resulting
    `content_hash` is what lands in the canonical commit's `Skill-Content-Hash` trailer,
    and a suite that reconstructed it differently in each module would not be testing the
    same contract the published evaluations ran.
    """
    return SkillVersion.from_parts(
        skill_id=strategy.skill_id,
        version=strategy.version,
        instructions=strategy.read_text(),
        path_templates=strategy.path_templates,
        contract_rules=strategy.contract_rules,
    )


def register_reference_skill_bases() -> dict[str, SkillVersion]:
    """Register every shipped personal-knowledge contract as a suite skill base."""
    bases = {
        s.version: skill_from_strategy(s)
        for s in list_strategies(REFERENCE_SKILL_ID)
    }
    for version, skill in bases.items():
        register_skill_base(version, skill)
    return bases


# At import, not only per test: several modules bind a skill at module scope
# (`SKILL = load_skill_base("v1")`), which runs during collection — before any fixture.
register_reference_skill_bases()


@pytest.fixture(autouse=True)
def reference_skill_bases() -> dict[str, SkillVersion]:
    """Autouse: every test starts from a wired registry. Also usable as a fixture value."""
    return register_reference_skill_bases()
