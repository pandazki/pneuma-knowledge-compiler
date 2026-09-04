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


# ------------------------------------------------- the archive: a ledger outlives a page


def _page(path: str, anchors: list[str], doc_id: str) -> CanonicalDocument:
    """A second page shape, with its own id — `_doc` above is a singleton by construction."""
    body = "\n".join(
        f"- 定价在三月改过。 [cite: src-02 ¶{i}] <!-- {a} -->"
        for i, a in enumerate(anchors)
    )
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return CanonicalDocument(
        doc_id=doc_id,
        path=path,
        frontmatter={"doc_id": doc_id, "type": "topic", "slug": slug},
        body=f"# {slug}\n\n## 台账\n\n{body}\n",
    )


LIVE_PAGE = "memory/topics/pricing.md"
#: The path the ledger recorded. The consultation happened while the page was live, and a
#: ledger row is a fact about the past: archiving moves the page and does not rewrite it.
RETIRED_PAGE = "memory/topics/aurora.md"
ARCHIVED_PAGE = "archive/memory/topics/aurora.md"


def _use_ledger(today: date) -> _Ledger:
    return _Ledger(
        [
            {"target_kind": "document", "target_ref": LIVE_PAGE, "day": today, "hits": 9},
            {"target_kind": "document", "target_ref": RETIRED_PAGE, "day": today, "hits": 4},
            {"target_kind": "claim", "target_ref": "c:aa11", "day": today, "hits": 9},
            {"target_kind": "claim", "target_ref": "c:dd44", "day": today, "hits": 7},
        ]
    )


def _pages(*paths: str) -> list[CanonicalDocument]:
    ids = {LIVE_PAGE: "d-1", RETIRED_PAGE: "d-2", ARCHIVED_PAGE: "d-2"}
    anchors = {LIVE_PAGE: ["c:aa11"], RETIRED_PAGE: ["c:dd44"], ARCHIVED_PAGE: ["c:dd44"]}
    return [_page(path, anchors[path], ids[path]) for path in paths]


async def test_the_report_names_no_page_that_is_in_the_archive():
    """The finding: the ledger holds `memory/topics/aurora.md` because that is where the
    page WAS, and the report printed it under "documents read, hottest first" — the past,
    with a heat figure, at an address the reader can no longer open."""
    today = datetime.now(timezone.utc).date()
    component = AttentionComponent(
        content=_use_ledger(today),
        canonical=_Canonical(_pages(LIVE_PAGE, ARCHIVED_PAGE)),
        templates=_templates,
    )

    report = await component.report("u-lynx-1", days=30)

    assert f"- {LIVE_PAGE} heat 9" in report
    assert RETIRED_PAGE not in report
    assert "archive/" not in report


async def test_with_nothing_archived_the_report_is_byte_for_byte_the_one_it_always_was():
    """Inertness, and it is the whole reason the pin has a switch. A ledger naming a page
    canonical does not hold happens with no archive in sight — a page a later compile
    renamed or deleted — and dropping those lines would be a change the Owner never asked
    for. So the pin turns on with the first archived DOCUMENT and not before."""
    today = datetime.now(timezone.utc).date()

    def _component(canonical):
        return AttentionComponent(
            content=_use_ledger(today), canonical=canonical, templates=_templates
        )

    # canonical holds ONLY the live page; the ledger names both, and nothing is archived.
    report = await _component(_Canonical(_pages(LIVE_PAGE))).report("u-lynx-1", days=30)

    assert f"- {RETIRED_PAGE} heat 4" in report, "an unpinned report, exactly as before"
    # …and the same library with an empty canonical face reports the same lines.
    assert report == await _component(_Canonical([])).report("u-lynx-1", days=30)


async def test_the_deep_tool_is_pinned_to_the_documents_the_lane_handed_it():
    """`recall_tools(..., documents=)` is the lane's own set. The tool returns PROSE, which
    the framework's assembly filter cannot redact after the fact, so the drop is made here."""
    today = datetime.now(timezone.utc).date()
    component = AttentionComponent(
        content=_use_ledger(today),
        canonical=_Canonical(_pages(LIVE_PAGE, ARCHIVED_PAGE)),
        templates=_templates,
    )

    [tool] = component.recall_tools("u-lynx-1", documents=_pages(LIVE_PAGE))
    report = await tool.ainvoke({"days": 30})

    assert f"- {LIVE_PAGE} heat 9" in report
    assert RETIRED_PAGE not in report


async def test_the_fast_path_projects_no_claim_off_an_archived_page():
    """The claim half of the same rule, on the face that is handed the lane's document set
    through `run(..., documents=)` — and on the fallback, where the component reads the tree
    itself and must read the LIVE half of it."""
    today = datetime.now(timezone.utc).date()
    component = AttentionComponent(
        content=_use_ledger(today),
        canonical=_Canonical(_pages(LIVE_PAGE, ARCHIVED_PAGE)),
        templates=_templates,
    )

    # handed no document set: the component reads the live tree for itself
    result = await component.hottest_claims("u-lynx-1")
    assert [c.anchor for c in result.claims] == ["aa11"]

    # …and through the path, with the lane's set
    [path] = component.fast_paths("u-lynx-1")
    result = await path.run(
        "u-lynx-1", path.args_schema(), documents=_pages(LIVE_PAGE, ARCHIVED_PAGE)
    )
    assert [c.anchor for c in result.claims] == ["aa11"]


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
