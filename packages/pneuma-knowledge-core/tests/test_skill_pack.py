"""SchemaPack + compose_skill + matrix/derive (schema-evolve M1).

Covers: compose determinism (order-independent, byte-stable), the additive template
assertion (raise, not warn), empty/no-pack continuity (base contract bytes unchanged),
matrix table lookup from a fixture JSON (+ absent-file tolerance), and the conservative
derive inference (over-budget / garbage / empty → None; valid → a capped pack)."""

from __future__ import annotations

import hashlib
import json

import pytest
from pneuma_knowledge_core.domain.user import Avatar, Locale, Preferences, UserProfile, WorkspaceProfile
from pneuma_knowledge_core.skill import (
    SchemaPack,
    compose_skill,
    derive_pack,
    load_builtin_skill,
    matrix_packs,
    packs_for_profile,
    render_system_contract,
)
from pneuma_knowledge_core.skill.pack import _DerivedPack, _DerivedTemplate


def _pack(pack_id: str, *, instr: str = "", templates=(), rules=()) -> SchemaPack:
    return SchemaPack(
        pack_id=pack_id,
        origin="matrix",
        extra_instructions=instr,
        extra_path_templates=list(templates),
        extra_contract_rules=tuple(rules),
    )


def _profile(source: str = "user", **over) -> UserProfile:
    base = dict(
        user_id="u-test",
        display_name="Test User",
        avatar=Avatar(initial="T", color="#6C8EBF"),
        locale=Locale(city="上海", country="中国", timezone="Asia/Shanghai", language="zh-CN"),
        industry="tech",
        role="engineering",
        level="senior",
        occupation="后端工程师",
        bio="我在做支付系统。",
        interests=["跑步", "开源"],
        workspace=WorkspaceProfile(
            operating_mode="opc",
            primary_stack="Python + TypeScript",
            automation_level="agentic",
            active_since="2024-05-01",
        ),
        preferences=Preferences(response_language="zh-CN", units="metric", privacy_level="standard"),
        joined_at="2024-05-01",
        source=source,
    )
    base.update(over)
    return UserProfile(**base)


# --------------------------------------------------------------------- compose


def test_empty_packs_returns_base_bytewise():
    for version in ("v1", "v2"):
        base = load_builtin_skill(version)
        composed = compose_skill(base, [])
        assert composed is base
        # I5 continuity: a no-pack user's contract == the built-in version's, byte-for-byte.
        want = render_system_contract(load_builtin_skill(version))
        got = render_system_contract(composed)
        assert hashlib.sha256(got.encode()).hexdigest() == hashlib.sha256(want.encode()).hexdigest()


def test_compose_is_deterministic_and_order_independent():
    base = load_builtin_skill("v2")
    p1 = _pack("a-pack", instr="A", templates=["memory/projects/{slug}.md"], rules=("ra",))
    p2 = _pack("b-pack", instr="B", templates=["memory/tech-notes/{slug}.md"], rules=("rb",))
    p3 = _pack("c-pack", instr="C", templates=["notes.md"])

    c_fwd = compose_skill(base, [p1, p2, p3])
    c_rev = compose_skill(base, [p3, p2, p1])
    # Same bytes and same hash regardless of input order.
    assert c_fwd.version == c_rev.version
    assert c_fwd.content_hash == c_rev.content_hash
    assert c_fwd.instructions == c_rev.instructions
    assert c_fwd.path_templates == c_rev.path_templates
    assert c_fwd.contract_rules == c_rev.contract_rules
    assert render_system_contract(c_fwd) == render_system_contract(c_rev)

    # A second compose of the same set reproduces the same hash.
    assert compose_skill(base, [p1, p2, p3]).content_hash == c_fwd.content_hash
    # Version is base + pack digest.
    assert c_fwd.version.startswith("v2+packs.")


def test_compose_is_additive_over_base_templates():
    base = load_builtin_skill("v2")
    composed = compose_skill(base, [_pack("p", templates=["memory/projects/{slug}.md"])])
    assert set(base.path_templates) <= set(composed.path_templates)
    assert "memory/projects/{slug}.md" in composed.path_templates
    # Extra rules ride after the base's, deduped.
    assert composed.contract_rules[: len(base.contract_rules)] == base.contract_rules


def test_compose_dedupes_templates_and_rules():
    base = load_builtin_skill("v1")
    p1 = _pack("a", templates=["memory/profile.md", "shared/{slug}.md"], rules=("r", "r"))
    p2 = _pack("b", templates=["shared/{slug}.md"], rules=("r",))
    composed = compose_skill(base, [p1, p2])
    # "memory/profile.md" already a base template → not duplicated.
    assert composed.path_templates.count("memory/profile.md") == 1
    assert composed.path_templates.count("shared/{slug}.md") == 1
    assert composed.contract_rules.count("r") == 1


def test_compose_rejects_malformed_extra_template():
    base = load_builtin_skill("v2")
    # A brace that is not {slug} is a malformed template → additive assertion raises.
    with pytest.raises(ValueError):
        compose_skill(base, [_pack("bad", templates=["memory/{bogus}/x.md"])])
    with pytest.raises(ValueError):
        compose_skill(base, [_pack("bad2", templates=["/abs/path.md"])])
    with pytest.raises(ValueError):
        compose_skill(base, [_pack("bad3", templates=["../escape/{slug}.md"])])


# --------------------------------------------------------------------- matrix


def _write_matrix(tmp_path) -> str:
    data = {
        "packs": [
            {
                "pack_id": "role-engineering",
                "match": {"roles": ["engineering"], "industries": []},
                "extra_instructions": "eng paragraph",
                "extra_path_templates": ["memory/projects/{slug}.md"],
                "extra_contract_rules": [],
            },
            {
                "pack_id": "health-admin",
                "match": {"roles": ["admin"], "industries": ["healthcare"]},
                "extra_instructions": "shifts",
                "extra_path_templates": ["memory/shifts/{slug}.md"],
                "extra_contract_rules": [],
            },
        ]
    }
    path = tmp_path / "matrix.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_matrix_lookup_role_and_industry(tmp_path):
    mp = _write_matrix(tmp_path)
    # role match, industries empty → matches any industry.
    got = matrix_packs("tech", "engineering", matrix_path=mp)
    assert [p.pack_id for p in got] == ["role-engineering"]
    # industry-scoped pack: matches only the listed industry.
    assert matrix_packs("healthcare", "admin", matrix_path=mp)[0].pack_id == "health-admin"
    assert matrix_packs("tech", "admin", matrix_path=mp) == []
    # no role match at all → empty.
    assert matrix_packs("tech", "design", matrix_path=mp) == []


def test_matrix_absent_file_is_empty(tmp_path):
    assert matrix_packs("tech", "engineering", matrix_path=str(tmp_path / "nope.json")) == []


# --------------------------------------------------------------------- derive


class _FakeStructured:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
        return self._payload


class _FakeModel:
    """Returns a scripted include_raw={'parsed': ...} envelope, counting invocations."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def with_structured_output(self, schema, include_raw=False):  # noqa: ANN001, ARG002
        self._counting = True
        return _CountingStructured(self)


class _CountingStructured:
    def __init__(self, model):
        self._model = model

    async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
        self._model.calls += 1
        return {"parsed": self._model._payload, "raw": None}


def _derived(instructions="", *templates) -> _DerivedPack:
    return _DerivedPack(
        instructions=instructions,
        templates=[_DerivedTemplate(path_template=t, reason="r") for t in templates],
    )


async def test_derive_valid_builds_capped_pack():
    model = _FakeModel(_derived("专业段落", "memory/deals/{slug}.md", "memory/accounts/{slug}.md"))
    pack = await derive_pack(model, _profile())
    assert pack is not None
    assert pack.origin == "derived" and pack.pack_id.startswith("occ-")
    assert pack.extra_path_templates == ["memory/deals/{slug}.md", "memory/accounts/{slug}.md"]
    assert pack.extra_instructions == "专业段落"


async def test_derive_over_budget_rejected():
    model = _FakeModel(
        _derived("x", "memory/a/{slug}.md", "memory/b/{slug}.md", "memory/c/{slug}.md", "memory/d/{slug}.md")
    )
    assert await derive_pack(model, _profile()) is None


async def test_derive_empty_returns_none():
    assert await derive_pack(_FakeModel(_derived("")), _profile()) is None


async def test_derive_garbage_returns_none():
    # parsed is not a _DerivedPack → None (parse failure degrades to silence).
    assert await derive_pack(_FakeModel({"not": "a pack"}), _profile()) is None


async def test_derive_drops_malformed_templates():
    model = _FakeModel(_derived("", "memory/{bogus}/x.md", "memory/ok/{slug}.md"))
    pack = await derive_pack(model, _profile())
    assert pack is not None
    assert pack.extra_path_templates == ["memory/ok/{slug}.md"]


async def test_derive_skips_mock_source():
    model = _FakeModel(_derived("x", "memory/deals/{slug}.md"))
    assert await derive_pack(model, _profile(source="mock")) is None
    assert model.calls == 0  # never even called the LLM


# --------------------------------------------------------------- packs_for_profile


async def test_packs_for_profile_mock_yields_nothing(tmp_path):
    mp = _write_matrix(tmp_path)
    model = _FakeModel(_derived("x", "memory/deals/{slug}.md"))
    # mock picture: NO packs at all — matrix disabled too.
    assert await packs_for_profile(_profile(source="mock"), model=model, matrix_path=mp) == []
    assert model.calls == 0


async def test_packs_for_profile_real_matrix_plus_derive(tmp_path):
    mp = _write_matrix(tmp_path)
    model = _FakeModel(_derived("x", "memory/deals/{slug}.md"))
    packs = await packs_for_profile(_profile(source="user"), model=model, matrix_path=mp)
    ids = {p.pack_id for p in packs}
    assert "role-engineering" in ids  # matrix
    assert any(p.origin == "derived" for p in packs)  # derive
    # Composes cleanly onto the base.
    composed = compose_skill(load_builtin_skill("v2"), packs)
    assert "memory/deals/{slug}.md" in composed.path_templates


async def test_packs_for_profile_matrix_only_without_model(tmp_path):
    mp = _write_matrix(tmp_path)
    packs = await packs_for_profile(_profile(source="user"), model=None, matrix_path=mp)
    assert all(p.origin == "matrix" for p in packs)
