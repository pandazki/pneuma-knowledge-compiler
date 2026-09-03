"""`path_templates_for` — the read-only contract lookup a component groups its report by.

It absorbs the failures that mean "this user has no declared families" and nothing else.
A bare `except Exception` made those indistinguishable from a programming error in manifest
composition: every path in every report went unfiled, with no log line anywhere and the
component's own fail-soft wrapper never seeing that anything had failed at all.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.skill import SkillVersion, register_skill_base

from pneuma_knowledge_service.skills import path_templates_for

_BASE = "test-templates-v1"


@pytest.fixture(autouse=True)
def base():
    register_skill_base(
        _BASE,
        SkillVersion.from_parts(
            skill_id="test-templates",
            version=_BASE,
            instructions="body",
            path_templates=["memory/people/{slug}.md"],
        ),
    )


def _settings(*, packs: bool = True) -> SimpleNamespace:
    return SimpleNamespace(user_schema_base_version=_BASE, user_schema_packs=packs)


class _Canonical:
    def __init__(self, raw) -> None:  # noqa: ANN001
        self._raw = raw

    async def read_meta(self, user_id, path):  # noqa: ANN001
        if isinstance(self._raw, Exception):
            raise self._raw
        return self._raw


async def test_a_user_with_no_manifest_gets_the_deployments_own_base():
    assert await path_templates_for(_settings(), _Canonical(None), "u-mei") == [
        "memory/people/{slug}.md"
    ]


async def test_a_manifest_that_will_not_parse_is_no_families_and_says_so(caplog):
    with caplog.at_level(logging.WARNING):
        assert await path_templates_for(_settings(), _Canonical("{not json"), "u-mei") == []
    assert "u-mei" in caplog.text


async def test_an_unreachable_canonical_is_no_families_and_says_so(caplog):
    with caplog.at_level(logging.WARNING):
        assert (
            await path_templates_for(
                _settings(), _Canonical(OSError("git repo unreachable")), "u-mei"
            )
            == []
        )
    assert "u-mei" in caplog.text


async def test_a_programming_error_reaches_the_callers_own_fail_soft_boundary():
    """The finding. A bug in manifest composition used to be swallowed here and reported as
    "this user declares no families" — silently, and identically to the legitimate cases
    above. It now propagates to the boundary that logs it with a traceback (the attention
    component's `_families`), which renders the same ungrouped report and leaves a trace."""

    class _Exploding:
        async def read_meta(self, user_id, path):  # noqa: ANN001
            raise RuntimeError("manifest composition is broken")

    with pytest.raises(RuntimeError, match="manifest composition is broken"):
        await path_templates_for(_settings(), _Exploding(), "u-mei")


async def test_the_component_still_renders_when_the_lookup_raises(caplog):
    """The other half of the same promise: propagating does not mean failing a report."""
    from pneuma_knowledge_service.components.attention import AttentionComponent

    async def templates(user_id):  # noqa: ANN001
        raise RuntimeError("manifest composition is broken")

    component = AttentionComponent(templates=templates)
    with caplog.at_level(logging.WARNING):
        assert await component._families("u-mei") == []
    assert "path templates unavailable" in caplog.text


async def test_a_pack_of_the_wrong_shape_is_still_a_malformed_manifest(caplog):
    """The named half of `TypeError`: `SchemaPack(**p)` raises it before pydantic validates
    anything when the entry is not a mapping of the model's fields. That is a manifest
    somebody has to repair, so it reads as no families and says the user's id out loud."""
    with caplog.at_level(logging.WARNING):
        assert (
            await path_templates_for(
                _settings(), _Canonical('{"packs": [{"not_a_field": 1}]}'), "u-mei"
            )
            == []
        )
    assert "u-mei" in caplog.text


async def test_a_typeerror_inside_composition_is_a_bug_and_travels_on(monkeypatch):
    """The unnamed half, and the finding. `TypeError` was caught over the whole body, so a
    programming error inside `compose_skill` was reported as "this user declares no
    families" — the exact failure the narrowing above was written to end, one layer down."""
    from pneuma_knowledge_service import skills as skills_module

    def broken(base, packs):  # noqa: ANN001, ARG001
        raise TypeError("compose_skill got an unexpected keyword")

    monkeypatch.setattr(skills_module, "compose_skill", broken)
    with pytest.raises(TypeError, match="unexpected keyword"):
        await path_templates_for(_settings(), _Canonical('{"packs": []}'), "u-mei")
