"""The shipped strategies: the catalog API, and the bytes it must never change.

This package is data plus a loader, so the tests are about exactly that — what is listed,
what a lookup returns, and that a contract body can never change silently. The sha256
values below are frozen deliberately: they are the bytes that produce the
`Skill-Content-Hash` trailers in canonical repositories (see
`tests/test_strategy_provenance.py` for the hash those bytes roll up into).
"""

from __future__ import annotations

import hashlib

import pytest
from pneuma_knowledge_strategies import (
    Strategy,
    get_strategy,
    list_strategies,
    load_strategy_text,
    strategies_root,
)

# sha256 of each contract body. Pinned so an edit cannot happen silently: changing a
# contract fails this test until the change is acknowledged here, in a commit saying why.
# Lineage: on 2026-08-03 (pre-release) the old three-generation catalog was collapsed to
# v1 — mechanism prose stripped, first-class beginnings and obligation chains added.
# v2 adds modality provenance without changing the bytes named by v1. Its pre-merge
# experiment used body hash cc0cd1e0…; the final body keeps derived representations usable.
# On 2026-08-10 it was narrowed to the image types the runtime actually supports and names
# audio/video/files as unsupported, replacing the earlier aspirational generic-media line.
# On 2026-08-12 v2 stopped fabricating exact endpoints for relative periods whose calendar
# convention is not supplied. v1 remains byte-stable; the retired v2 body was 3e75f9d4….
# Retired historical body hashes: v1 bedea7b4…, v2 aeae8203…, v3 187d0201… (full values
# in git history).
FROZEN_BODY_SHA256 = {
    "v1": "b81c08e9184f2dc7a502d620203b8bf2386f548b0a77edb19d381498767ba9b1",
    "v2": "9f04453f638ab1046600be73f157d76854d63c4f737a215776f6a17d3248c9a0",
}

PERSONAL_KNOWLEDGE_TEMPLATES = (
    "memory/profile.md",
    "memory/people/{slug}.md",
    "work/products/{slug}.md",
    "work/experiments/{slug}.md",
    "work/operations/{slug}.md",
    "memory/topics/{slug}.md",
    "materials/{slug}.md",
)


def test_the_personal_knowledge_contract_is_listed():
    listed = list_strategies("personal-knowledge")
    assert [s.version for s in listed] == ["v1", "v2"]
    assert {s.skill_id for s in listed} == {"personal-knowledge"}
    # a listing is only useful if it says what each one is
    assert all(s.domain.strip() and s.summary.strip() for s in listed)


def test_listing_without_a_filter_is_the_whole_catalog():
    assert set(list_strategies()) >= set(list_strategies("personal-knowledge"))


def test_bodies_cannot_change_silently():
    """Provenance: a canonical repo's `Skill-Content-Hash` is computed from these bytes.
    A whitespace fix here silently invalidates every trailer written under them."""
    for version, expected in FROZEN_BODY_SHA256.items():
        body = load_strategy_text("personal-knowledge", version)
        digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
        assert digest == expected, f"{version} body changed: {digest}"


def test_structural_metadata_rides_with_the_body():
    """`path_templates` and `contract_rules` are part of the contract's identity, so the
    package carries them rather than making every consumer retype them."""
    strategies = list_strategies("personal-knowledge")
    for strategy in strategies:
        assert strategy.path_templates == PERSONAL_KNOWLEDGE_TEMPLATES
        assert strategy.contract_rules == (
            "contract.rule.citation_granularity",
            "contract.rule.citation_shape",
            "contract.rule.strength_labels",
        )
    assert get_strategy("personal-knowledge", "v2").contract_rules == (
        "contract.rule.citation_granularity",
        "contract.rule.citation_shape",
        "contract.rule.strength_labels",
    )


def test_get_strategy_returns_a_frozen_record_pointing_at_a_real_file():
    strategy = get_strategy("personal-knowledge", "v1")
    assert isinstance(strategy, Strategy)
    assert strategy.path.is_file()
    assert strategy.path.parent.parent == strategies_root()
    with pytest.raises(Exception):
        strategy.version = "v9"  # type: ignore[misc]


def test_unknown_lookup_fails_loud_and_says_what_exists():
    with pytest.raises(LookupError) as excinfo:
        get_strategy("personal-knowledge", "v9")
    assert "personal-knowledge@v1" in str(excinfo.value)
    assert "personal-knowledge@v2" in str(excinfo.value)
    with pytest.raises(LookupError):
        get_strategy("no-such-domain", "v1")


def test_the_package_does_not_depend_on_the_framework():
    """The whole point of the split: a strategy is data, and data cannot import the thing
    it is data for. If this ever fails, core has an opinion about someone's domain again."""
    source = (strategies_root().parent / "__init__.py").read_text(encoding="utf-8")
    assert "import pneuma_knowledge_core" not in source
    assert "from pneuma_knowledge_core" not in source
