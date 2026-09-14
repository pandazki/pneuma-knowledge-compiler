"""The structure lens: six dimensions, their bands, their movement.

The lens lists no page and carries no score, so these tests assert what it DOES say: which
band each dimension lands in over a library built to land there, which metrics it rests on,
what it shows verbatim, and how a reading moves against the one before it.

Design authority: docs/design/structure-lens.md §4, §5.2.
"""

from __future__ import annotations

import pytest
from pneuma_knowledge_core.lens import (
    DIMENSION_BANDS,
    DIMENSION_IDS,
    Consultation,
    build_reading,
    dimension_of,
    render_direction,
    render_statement,
)
from pneuma_knowledge_core.lens.dimensions import LIVENESS_UNTOUCHED_DAYS
from pneuma_knowledge_core.prompts import (
    chinese_overlay,
    default_catalog,
    template_fields,
)
from test_check import TEMPLATES, claim, doc, healthy, replace


def reading(docs, **kwargs):
    return build_reading(docs, TEMPLATES, **kwargs)


def band(docs, dimension: str, **kwargs) -> str:
    return dimension_of(reading(docs, **kwargs), dimension).band


def metrics(docs, dimension: str, **kwargs) -> dict:
    found = dimension_of(reading(docs, **kwargs), dimension)
    return {metric.name: metric.value for metric in found.metrics}


# ─────────────────────────────────────────────────────────────────── the clean base


def test_a_healthy_library_reads_open_even_and_knowledge_and_is_unread():
    """The floor under the rest: a small, connected, evenly spread library with no dated
    narration and nobody asking it anything."""
    reading_ = reading(healthy(), ref="HEAD", read_at="2026-03-01T00:00:00Z")
    assert [d.id for d in reading_.dimensions] == list(DIMENSION_IDS)
    assert {d.id: d.band for d in reading_.dimensions} == {
        "walkability": "open",
        "shape": "even",
        "knowledge_vs_log": "knowledge",
        # Nothing has ever been superseded in this library, and the lens says so rather
        # than calling six pages written once "living".
        "liveness": "still",
        "type_structure": "aligned",
        # Nobody has asked it anything: not `matched`, and not a zero.
        "demand_supply": "unread",
    }
    assert (reading_.subjects, reading_.files, reading_.claims, reading_.edges) == (
        6,
        6,
        13,
        10,
    )
    assert reading_.previous_ref == ""
    assert all(d.previous_band is None for d in reading_.dimensions)


# ───────────────────────────────────────────────────────────────── 1. walkability


def test_a_project_nothing_outside_reaches_is_an_island_the_reading_shows_verbatim():
    """An island is a library inside the library: no edge crosses its boundary in either
    direction. It is a metric and a piece of evidence, never a page to repair."""
    docs = [
        d
        for d in healthy()
        if d.path not in {"memory/people/mei.md", "memory/topics/flow.md"}
    ]
    docs = replace(
        docs,
        "projects/aurora/overview.md",
        "# Aurora\n\n## What it is\n\n"
        + claim("A water plant control stack.", "a0000001")
        + "\n\n"
        + claim(
            "Its history is in [the timeline](evolution.md), its parts in "
            "[the pump](features/pump.md) and [the tank choice](decisions/tank.md).",
            "a0000002",
        ),
    ) + [
        doc(
            "memory/topics/flow.md",
            "# Flow shaping\n\n## What\n\n" + claim("An idea about demand.", "a000000c"),
        )
    ]
    found = dimension_of(reading(docs), "walkability")
    assert "projects/aurora" in found.evidence
    assert metrics(docs, "walkability")["islands"] == 1
    assert "projects/aurora" not in render_direction(found)  # a lever, never a page


def test_a_library_where_most_pages_lead_nowhere_reads_broken():
    docs = healthy()
    for path in (
        "memory/topics/flow.md",
        "memory/people/mei.md",
        "projects/aurora/decisions/tank.md",
    ):
        docs = replace(
            docs,
            path,
            "# " + path.rsplit("/", 1)[-1].removesuffix(".md") + " page\n\n## What\n\n"
            + claim("It stands alone.", "e" + path[-9:-3].encode().hex()[:7]),
        )
    found = dimension_of(reading(docs), "walkability")
    assert found.band == "broken"
    values = {m.name: m.value for m in found.metrics}
    assert values["dead_end_share"] == pytest.approx(3 / 6, abs=1e-3)


def test_one_page_of_six_leading_nowhere_is_thin_rather_than_broken():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n" + claim("Smoothing demand.", "a000000c"),
    )
    assert band(docs, "walkability") == "thin"
    assert metrics(docs, "walkability")["dead_end_share"] == pytest.approx(1 / 6, abs=1e-3)


# ──────────────────────────────────────────────────────────────────────── 2. shape


def test_one_subject_holding_most_of_the_claims_reads_collapsing():
    blocks = "\n\n".join(claim(f"Fact {n}.", f"b{n:07d}") for n in range(30))
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + blocks
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    found = dimension_of(reading(docs), "shape")
    assert found.band == "collapsing"
    assert "memory/topics/flow.md" in found.evidence
    values = {m.name: m.value for m in found.metrics}
    assert values["lead_share"] > 0.2 and values["lead_ratio"] > 2
    # The statement names the subject; the direction names the lever and no page.
    assert "Flow shaping" in render_statement(found)
    assert "memory/topics/flow.md" not in render_direction(found)


def test_a_small_library_is_not_called_collapsing_for_holding_one_extra_paragraph():
    """A share only means concentration when there are enough subjects for a share to mean
    anything: the lead subject of the healthy library holds 23% of thirteen claims and is
    1.4× an even share, which is a page with one more paragraph."""
    assert band(healthy(), "shape") == "even"


# ────────────────────────────────────────────────────────────── 3. knowledge vs log


def test_dated_single_source_entries_read_as_a_log():
    entries = "\n\n".join(
        claim(f"2026-01-0{n}，did a thing.", f"d{n:07d}") for n in range(1, 7)
    )
    docs = replace(
        healthy(), "memory/topics/flow.md", "# Flow shaping\n\n## Log\n\n" + entries
    )
    docs = replace(
        docs,
        "memory/people/mei.md",
        "# Mei Lark\n\n## Log\n\n"
        + "\n\n".join(
            claim(f"2026-02-0{n}，did another thing.", f"b{n:07d}") for n in range(1, 7)
        ),
    )
    found = dimension_of(reading(docs), "knowledge_vs_log")
    assert found.band == "log"
    values = {m.name: m.value for m in found.metrics}
    assert values["narration_share"] > 0.5
    assert values["log_subject_share"] == pytest.approx(2 / 6, abs=1e-3)
    # Evidence is verbatim library text: the subjects, and the dated openings themselves.
    assert any(item.startswith("2026-") for item in found.evidence)


# ───────────────────────────────────────────────────────────────────── 4. liveness


def test_supersessions_make_the_library_read_as_living():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + claim("Smoothing demand before it reaches a pump.", "a000000c")
        + "\n\n"
        + claim("It now smooths demand at the tank. <!-- supersedes: c:a000000c -->", "a000000e")
        + "\n\n"
        + claim("It shows up in [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    found = dimension_of(reading(docs), "liveness")
    assert found.band == "living"
    values = {m.name: m.value for m in found.metrics}
    assert values["supersessions_per_100_claims"] > 1
    # No write dates were supplied, so the two metrics that need history say so.
    assert values["untouched_subject_share"] is None
    assert values["median_days_since_write"] is None


def test_write_dates_fill_the_liveness_metrics_that_need_history():
    docs = healthy()
    written_on = {
        "projects/aurora/overview.md": "2026-02-20",
        "projects/aurora/evolution.md": "2026-02-20",
        "projects/aurora/features/pump.md": "2026-02-20",
        "projects/aurora/decisions/tank.md": "2020-01-01",
        "memory/people/mei.md": "2020-01-01",
        "memory/topics/flow.md": "2020-01-01",
    }
    values = metrics(
        docs, "liveness", written_on=written_on, read_at="2026-03-01T00:00:00Z"
    )
    assert values["untouched_subject_share"] == pytest.approx(0.5, abs=1e-3)
    assert values["median_days_since_write"] > LIVENESS_UNTOUCHED_DAYS


# ─────────────────────────────────────────────────────────────── 5. type structure


def test_dated_claims_outside_a_chronology_and_an_unused_family_strain_the_structure():
    entries = "\n\n".join(
        claim(f"2026-01-0{n}，did a thing.", f"d{n:07d}") for n in range(1, 4)
    )
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n"
        + entries
        + "\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    found = dimension_of(reading(docs), "type_structure")
    assert found.band in {"strained", "misfiled"}
    values = {m.name: m.value for m in found.metrics}
    assert values["dated_outside_chronology_share"] > 0.05
    assert "evolve" in render_direction(found)


def test_a_declared_family_nothing_was_ever_filed_under_is_a_type_structure_proxy():
    docs = [d for d in healthy() if d.path != "memory/people/mei.md"]
    found = dimension_of(reading(docs), "type_structure")
    values = {m.name: m.value for m in found.metrics}
    assert values["empty_family_share"] == pytest.approx(1 / 6, abs=1e-3)
    assert "memory/people/{slug}.md" in found.evidence


def test_decision_shaped_sections_outside_the_decisions_family_are_counted():
    docs = replace(
        healthy(),
        "memory/topics/flow.md",
        "# Flow shaping\n\n## Decision\n\n"
        + claim("We smooth at the tank.", "a000000c")
        + "\n\n## Rationale\n\n"
        + claim("See [the plant](../../projects/aurora/overview.md).", "a000000d"),
    )
    found = dimension_of(reading(docs), "type_structure")
    values = {m.name: m.value for m in found.metrics}
    assert values["decision_shaped_outside_share"] > 0
    assert "Decision" in found.evidence


# ──────────────────────────────────────────────────────────────── 6. demand/supply


def test_with_no_consultations_the_use_side_is_unread_and_says_nothing_else():
    found = dimension_of(reading(healthy()), "demand_supply")
    assert found.band == "unread"
    values = {m.name: m.value for m in found.metrics}
    assert values["consultations"] == 0
    assert values["uncited_share"] is None and values["lead_family_demand_ratio"] is None


def test_consultations_that_match_the_library_read_matched():
    consultations = [
        Consultation(paths=("projects/aurora/overview.md",), cited=True, at="2026-03-01"),
        Consultation(paths=("memory/people/mei.md",), cited=True, at="2026-03-01"),
        Consultation(paths=("memory/topics/flow.md",), cited=True, at="2026-03-02"),
        Consultation(
            paths=("projects/aurora/features/pump.md",), cited=True, at="2026-03-02"
        ),
    ]
    found = dimension_of(
        reading(healthy(), consultations=consultations), "demand_supply"
    )
    assert found.band == "matched"
    values = {m.name: m.value for m in found.metrics}
    assert values["consultations"] == 4
    assert values["consulted_subject_share"] == pytest.approx(4 / 6, abs=1e-3)


def test_asking_one_family_over_and_over_and_citing_nothing_reads_skewed():
    consultations = [
        Consultation(paths=("memory/people/mei.md",), cited=False, at="2026-03-01")
        for _ in range(6)
    ]
    found = dimension_of(
        reading(healthy(), consultations=consultations), "demand_supply"
    )
    assert found.band == "skewed"
    values = {m.name: m.value for m in found.metrics}
    assert values["uncited_share"] == 1.0
    assert values["lead_family_demand_ratio"] > 2
    assert "memory/people/{slug}.md" in found.evidence


# ──────────────────────────────────────────────────────────────────── 4.3 the trend


def test_a_previous_reading_gives_every_metric_its_movement_and_names_the_band_it_left():
    before = healthy()
    after = replace(
        before,
        "memory/topics/flow.md",
        "# Flow shaping\n\n## What\n\n" + claim("Smoothing demand.", "a000000c"),
    )
    found = dimension_of(
        reading(after, ref="HEAD", previous=(before, "HEAD~1")), "walkability"
    )
    assert found.band == "thin" and found.previous_band == "open"
    dead = next(m for m in found.metrics if m.name == "dead_end_share")
    assert dead.previous == 0.0
    assert dead.delta == pytest.approx(1 / 6, abs=1e-3)
    assert reading(after, previous=(before, "HEAD~1")).previous_ref == "HEAD~1"


def test_a_metric_the_previous_reading_could_not_take_moves_by_an_unknown_amount():
    """`previous` is documents and a ref — no consultations of its own — so the use-side
    metrics have no previous value, and a null delta is the honest answer rather than a
    fall to zero."""
    docs = healthy()
    found = dimension_of(
        reading(
            docs,
            previous=(docs, "HEAD~1"),
            consultations=[Consultation(paths=("memory/people/mei.md",), cited=True)],
        ),
        "demand_supply",
    )
    gap = next(m for m in found.metrics if m.name == "uncited_share")
    assert gap.value == 0.0 and gap.previous is None and gap.delta is None


# ─────────────────────────────────────────────────────── the reading's own mechanics


def test_to_dict_is_the_wire_shape_the_faces_code_against():
    payload = reading(healthy(), ref="HEAD", read_at="2026-03-01T00:00:00Z").to_dict()
    assert set(payload) == {
        "ref",
        "read_at",
        "previous_ref",
        "subjects",
        "files",
        "claims",
        "edges",
        "dimensions",
    }
    # No findings and no score anywhere: a page-level finding is the check's (§4.5).
    assert "findings" not in payload and "score" not in payload
    dimension = payload["dimensions"][0]
    assert set(dimension) == {
        "id",
        "band",
        "previous_band",
        "statement",
        "direction",
        "metrics",
        "evidence",
    }
    assert set(dimension["statement"]) == {"key", "fields", "text"}
    assert set(dimension["statement"]["text"]) == {"en", "zh"}
    assert dimension["statement"]["key"] == "lens.walkability.open.statement"
    assert set(dimension["metrics"][0]) == {"name", "value", "previous", "delta"}


def test_a_contract_that_declares_none_of_the_family_roles_still_reads_every_dimension():
    docs = [
        doc("notes/one.md", "# One\n\n## A\n\n" + claim("Alpha.", "a1111111")),
        doc("notes/two.md", "# Two\n\n## A\n\n" + claim("Beta.", "a2222222")),
    ]
    found = build_reading(docs, ["notes/{slug}.md"])
    assert [d.id for d in found.dimensions] == list(DIMENSION_IDS)
    assert all(d.band in DIMENSION_BANDS[d.id] for d in found.dimensions)


def test_the_reading_is_a_function_of_the_documents_and_not_of_their_order():
    docs = healthy()
    first = reading(docs).to_dict()
    again = reading(list(reversed(docs))).to_dict()
    assert first == again


# ────────────────────────────────────────────── every band has both of its sentences


@pytest.mark.parametrize(
    "dimension,band_id",
    [(d, b) for d, bands in DIMENSION_BANDS.items() for b in bands],
)
def test_every_band_carries_a_statement_and_a_direction_in_both_packs(dimension, band_id):
    english, chinese = default_catalog(), chinese_overlay()
    for key in (
        f"lens.{dimension}.{band_id}.statement",
        f"lens.{dimension}.{band_id}.direction",
    ):
        assert key in english and english[key].strip()
        assert key in chinese and chinese[key].strip()


@pytest.mark.parametrize(
    "dimension,band_id",
    [(d, b) for d, bands in DIMENSION_BANDS.items() for b in bands],
)
def test_no_direction_names_a_page(dimension, band_id):
    """§4.2: the direction names a lever — a contract clause, an evolve, a groom, a review
    round — and never a page. Mechanically: it may not interpolate a path or a title, in
    either pack, so no wording of it can end up addressed to one document."""
    english, chinese = default_catalog(), chinese_overlay()
    for pack in (english, chinese):
        declared = template_fields(pack[f"lens.{dimension}.{band_id}.direction"])
        assert not declared & {"path", "title", "target", "paths"}, (
            f"lens.{dimension}.{band_id}.direction is addressed to a page"
        )


def test_every_rendered_sentence_fills_every_placeholder_it_declares():
    libraries = [
        healthy(),
        replace(
            healthy(),
            "memory/topics/flow.md",
            "# Flow shaping\n\n## What\n\n" + claim("2026-01-01，did a thing.", "a000000c"),
        ),
    ]
    catalog = default_catalog()
    for docs in libraries:
        for found in reading(docs).dimensions:
            for half in (found.statement, found.direction):
                rendered = half.text()
                for language, text in rendered.items():
                    assert text.strip(), (found.id, half.key, language)
                    for name in template_fields(catalog[half.key]):
                        assert "{" + name + "}" not in text, (
                            f"{half.key} ({language}) left {{{name}}} unfilled"
                        )
                assert rendered["zh"] != rendered["en"]
