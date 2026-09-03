"""The `attention` component's faces: the report, the deep tool, the fast path, the wiring.

The component owns no rows any more — the ledger it reads is the framework's built-in
access statistics (`access_stats.py`), applied by the worker whether or not this component
is registered. What is left here is what a FACE is: a function of the rows it was handed,
which is why all of it runs without middleware. The rows themselves, their write path and
their replay live in `test_access_stats.py` and, against a real postgres, in
`tests/integration/test_access_stats_pg.py`.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from pneuma_knowledge_core.domain.canonical import CanonicalDocument

from pneuma_knowledge_service.components.attention import AttentionComponent

TODAY = date(2026, 8, 31)


# ------------------------------------------------------------------------- the faces

class _Ledger:
    """The store face the component uses, in memory and ordered like the real one."""

    def __init__(self, hits: list[dict], misses: list[dict] | None = None) -> None:
        self.hits = hits
        self.misses = misses or []

    async def access_hits_since(self, user_id, since, *, until=None):
        return [
            r
            for r in self.hits
            if r["day"] >= since and (until is None or r["day"] <= until)
        ]

    async def access_misses_since(self, user_id, since, *, until=None):
        return [
            r
            for r in self.misses
            if r["day"] >= since and (until is None or r["day"] <= until)
        ]


class _Canonical:
    def __init__(self, docs) -> None:
        self._docs = docs

    async def list(self, user_id, *, at=None):
        return list(self._docs)


def _doc(path: str, anchors: list[str]) -> CanonicalDocument:
    body = "\n".join(
        f"- 三月改过定价。 [cite: src-01 ¶{i}] <!-- {a} -->"
        for i, a in enumerate(anchors)
    )
    return CanonicalDocument(
        doc_id="d-1",
        path=path,
        frontmatter={"doc_id": "d-1", "type": "topic", "slug": "pricing"},
        body=f"# 定价\n\n## 台账\n\n{body}\n",
    )


async def _templates(user_id):
    return ["memory/topics/{slug}.md"]


async def test_the_report_is_none_when_the_window_holds_nothing():
    component = AttentionComponent(content=_Ledger([]), templates=_templates)
    assert await component.report("u-lynx-1", days=30) is None
    assert await component.evolve_evidence("u-lynx-1") is None


async def test_a_component_with_no_store_reports_nothing_instead_of_failing():
    assert await AttentionComponent().evolve_evidence("u-lynx-1") is None


async def test_the_hottest_claims_travel_as_ordinary_retrieved_claims():
    """The fast path returns everything it knows in heat order; the framework ranks it
    against the question and spends the path's cap on that order."""
    today = datetime.now(timezone.utc).date()
    ledger = _Ledger(
        [
            {"target_kind": "claim", "target_ref": "c:aa11", "day": today, "hits": 1},
            {"target_kind": "claim", "target_ref": "c:bb22", "day": today, "hits": 9},
            # an anchor a later compile superseded away: it has no text to render
            {"target_kind": "claim", "target_ref": "c:cc33", "day": today, "hits": 5},
            {"target_kind": "document", "target_ref": "memory/topics/pricing.md", "day": today, "hits": 9},
        ]
    )
    component = AttentionComponent(
        content=ledger,
        canonical=_Canonical([_doc("memory/topics/pricing.md", ["c:aa11", "c:bb22"])]),
        templates=_templates,
    )

    result = await component.hottest_claims("u-lynx-1")

    assert [c.anchor for c in result.claims] == ["bb22", "aa11"]
    assert result.claims[0].labels == ("heat 9",)
    assert result.claims[0].paths == ("attention",)
    assert result.windows == ()


async def test_the_fast_path_and_the_deep_tool_are_offered_under_their_own_names():
    component = AttentionComponent(content=_Ledger([]), templates=_templates)
    assert [p.name for p in component.fast_paths("u-lynx-1")] == ["attention"]
    assert [t.name for t in component.recall_tools("u-lynx-1")] == ["attention_report"]


async def test_the_deep_tool_says_the_ledger_is_empty_rather_than_returning_nothing():
    component = AttentionComponent(content=_Ledger([]), templates=_templates)
    [tool] = component.recall_tools("u-lynx-1")
    assert "no consultation was recorded" in await tool.ainvoke({"days": 7})


async def test_the_reported_window_does_not_reach_past_the_day_it_says_it_ends_on():
    """The report prints `window A..B`. A row dated after B was counted in a window whose
    own header says it does not contain it."""
    ledger = _Ledger(
        [
            {"target_kind": "document", "target_ref": "memory/topics/pricing.md",
             "day": TODAY + timedelta(days=5), "hits": 99},
        ]
    )
    component = AttentionComponent(content=ledger, templates=_templates)
    assert await component.report("u-lynx-1", days=30) is None


def test_the_cut_report_counts_the_lines_it_dropped_and_not_its_own_notice():
    """`_cap` says how many lines it left out. The notice used to be appended to `kept`
    before the subtraction, so it counted itself as one of the lines it had dropped and
    every capped report understated the cut by one."""
    component = AttentionComponent(evidence_chars=20)
    lines = [f"line-{i}" for i in range(10)]  # 7 characters each, 8 with the newline

    text = component._cap(lines)

    kept = [line for line in text.splitlines() if not line.startswith("(cut to")]
    assert len(kept) == 2
    assert "8 more line(s) not shown" in text


# ------------------------------------------------------------------------ the wiring


def test_attention_is_registrable_by_name_and_contributes_nothing_until_it_is():
    """The seam's discipline, at the one place it is decided: enabled by name, and with the
    name absent nothing is registered — so every prompt and every lane renders as it did
    before the component existed."""
    import pytest
    from pneuma_knowledge_core.components import registered_components, reset_components

    from pneuma_knowledge_service.settings import Settings
    from pneuma_knowledge_service.wiring import register_components

    reset_components()
    try:
        assert register_components(Settings(components=""), store=None, canonical=None) == []
        assert registered_components() == ()

        settings = Settings(components="attention")
        assert register_components(settings, store=None, canonical=None) == ["attention"]
        [component] = registered_components()
        assert component.name == "attention"
        # the three knobs reach the component rather than being read again at each call
        assert component._half_life_days == float(settings.attention_half_life_days)
        assert component._window_days == settings.attention_window_days
        assert component._evidence_chars == settings.attention_evidence_chars

        reset_components()
        with pytest.raises(ValueError, match="unknown index component"):
            register_components(
                Settings(components="attention,graph"), store=None, canonical=None
            )
    finally:
        reset_components()
