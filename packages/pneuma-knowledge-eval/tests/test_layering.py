"""Group C: compression, duplication, verbatim reproduction, language consistency."""

from __future__ import annotations

from _fixtures import claim, document, source, trajectory
from pneuma_knowledge_eval.metrics.layering import (
    compression,
    detail_leakage,
    duplication,
    language_consistency,
    layering_metrics,
    verbatim_reproduction,
)

LONG_BLOCK = (
    "The pilot is fixed price, runs for two weeks, covers four source adapters, cited "
    "retrieval and a decision timeline, and excludes automated write-back entirely."
)


def test_compression_uses_prose_characters_and_reports_the_markup_it_excluded():
    files = {
        "memory/topics/a.md": document(
            "memory/topics/a.md", [claim("A short thread.", "aaaa0001", cite="s1 ¶0")]
        )
    }
    sources = {"s1": source("s1", [LONG_BLOCK])}
    report = compression(trajectory([files], sources=sources, consumed=[["s1"]]))
    head = report["series"][-1]

    assert head["l0_chars"] == len(LONG_BLOCK)
    assert head["prose_chars"] < head["canonical_chars"]
    assert head["markup_chars"] > 0
    assert head["compression_ratio"] < head["raw_compression_ratio"]


def test_compression_is_unavailable_without_a_denominator():
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "bbbb0001")])}
    assert compression(trajectory([files]))["status"] == "unavailable"
    # sources present but no round declares consumption: still no honest denominator
    with_sources = trajectory([files], sources={"s1": source("s1", ["x"])})
    assert compression(with_sources)["status"] == "unavailable"


def test_cross_document_duplication_is_counted_separately_from_within_document():
    same = "Acceptance runs twenty reviewed questions at the end of week two."
    within = {
        "memory/topics/a.md": document(
            "memory/topics/a.md", [claim(same, "cccc0001"), claim(same, "cccc0002")]
        )
    }
    across = {
        "memory/topics/a.md": document("memory/topics/a.md", [claim(same, "cccc0001")]),
        "work/products/p.md": document("work/products/p.md", [claim(same, "cccc0003")]),
    }
    report = duplication(trajectory([within, across]))

    first, second = report["series"]
    assert first["near_duplicate_groups"] == 1
    assert first["cross_document_groups"] == 0
    assert first["exact_duplicate_groups"] == 1
    assert second["cross_document_groups"] == 1
    assert report["invariants"]["no_cross_document_duplicates_at_head"] is False


def test_distinct_claims_are_not_reported_as_duplicates():
    files = {
        "memory/topics/a.md": document(
            "memory/topics/a.md",
            [
                claim("Deletion evidence must be verifiable.", "dddd0001"),
                claim("The retainer is invoiced monthly.", "dddd0002"),
            ],
        )
    }
    report = duplication(trajectory([files]))
    assert report["head"]["near_duplicate_groups"] == 0
    assert report["head"]["duplicate_row_rate"] == 0.0


def test_verbatim_reproduction_flags_a_transcript_and_spares_a_paraphrase():
    sources = {"s1": source("s1", [LONG_BLOCK])}
    files = {
        "memory/topics/a.md": document(
            "memory/topics/a.md",
            [
                claim(LONG_BLOCK, "eeee0001", cite="s1 ¶0"),
                claim("Two-week fixed-price pilot; no write-back.", "eeee0002", cite="s1 ¶0"),
            ],
        )
    }
    report = verbatim_reproduction(trajectory([files], sources=sources, consumed=[["s1"]]))
    head = report["head"]
    assert head["claims_judged"] == 2
    assert head["transcribed"] == 1
    assert head["longest_run_max"] >= 40
    assert head["transcription_rate"] == 0.5


def test_verbatim_reproduction_only_judges_claims_with_resolvable_support():
    sources = {"s1": source("s1", [LONG_BLOCK])}
    files = {
        "memory/topics/a.md": document(
            "memory/topics/a.md",
            [claim("No citation here.", "ffff0001"), claim("Unknown source.", "ffff0002", cite="s9 ¶0")],
        )
    }
    report = verbatim_reproduction(trajectory([files], sources=sources, consumed=[["s1"]]))
    assert report["head"]["claims_judged"] == 0
    assert report["head"]["claims_total"] == 2
    assert report["head"]["transcription_rate"] is None


def test_detail_leakage_needs_labels():
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "1a1a0001")])}
    assert detail_leakage(trajectory([files]), None)["status"] == "unavailable"


def test_group_entry_point_returns_all_four_sections():
    files = {"memory/topics/a.md": document("memory/topics/a.md", [claim("A.", "2b2b0001")])}
    report = layering_metrics(trajectory([files]))
    assert report["group"] == "C_layering"
    assert set(report) >= {
        "compression",
        "duplication",
        "verbatim_reproduction",
        "detail_leakage",
    }


# ─────────────────────────────────────────────────────────────── language consistency

CN_BLOCK = "吴岚明确表示这份回复不构成同意延长，附录仍然需要签字确认后才能生效。"
CN_CLAIM = "【firm】吴岚未同意延长，附录仍待签字。"
EN_CLAIM = "Wu Lan has not agreed to the extension; the appendix still awaits signature."
# Substantive weight in BOTH scripts, which is what the real bilingual claims looked like: an
# English sentence and a Chinese clause carrying different parts of the same statement.
MIXED_CLAIM = (
    "【firm】The appendix still awaits a signature and the final payment has no recorded date; "
    "吴岚明确表示这份回复不构成同意延长，三项条件仍须分别回到各自来源确认。"
)


def _language_trajectory(claim_texts):
    files = {
        "memory/topics/pilot.md": document(
            "memory/topics/pilot.md",
            [
                claim(text, f"aaaa{index:04d}", cite="s1 ¶0")
                for index, text in enumerate(claim_texts, start=1)
            ],
        )
    }
    return trajectory(
        [files], sources={"s1": source("s1", [CN_BLOCK])}, consumed=[["s1"]]
    )


def test_claims_are_judged_against_the_declared_language_not_the_material():
    report = language_consistency(
        _language_trajectory([CN_CLAIM]), declared_language="zh-CN"
    )
    assert report["status"] == "ok"
    assert report["declared_language"] == "zh-CN"
    assert report["declared_script"] == "cjk"
    assert report["declared_language_source"] == "argument"
    assert report["head"]["declared_language_rate"] == 1.0
    assert report["head"]["diverged_from_declared"] == 0
    assert report["invariants"]["head_fully_in_declared_language"] is True
    # the material's script is reported, but it decided nothing
    assert report["material_script"] == "cjk"


def test_the_material_script_is_reference_only_and_does_not_move_the_target():
    """The regression this re-basing prevents: a Chinese-reading subject's base scored a clean
    1.0 for claims written in the language of whichever source arrived. The declaration is the
    target, so the same claims over the same material score differently for a different subject."""
    report = language_consistency(
        _language_trajectory([CN_CLAIM, EN_CLAIM]), declared_language="en-US"
    )
    head = report["head"]
    assert report["material_script"] == "cjk"  # unchanged material
    assert report["declared_script"] == "latin"
    assert head["in_declared_language"] == 1
    assert head["diverged_from_declared"] == 1
    assert report["diverged_claims_at_head"][0]["script"] == "cjk"


def test_english_is_the_default_when_no_language_is_declared():
    """Same rule the compile contract states to the model (`compile.owner_env.language_unknown`):
    a subject who declared no language gets English, so English is what the compile is held to."""
    report = language_consistency(_language_trajectory([CN_CLAIM, EN_CLAIM]))
    assert report["declared_language"] == "en"
    assert report["declared_language_source"] == "default"
    assert report["head"]["in_declared_language"] == 1
    assert report["head"]["diverged_from_declared"] == 1


def test_a_claim_outside_the_declared_language_is_reported_as_diverged():
    """The failure is a thread the only reader it exists for cannot read — and no
    character-level metric can match it against the rest of the base."""
    report = language_consistency(
        _language_trajectory([CN_CLAIM, EN_CLAIM]), declared_language="zh-CN"
    )
    head = report["head"]
    assert head["claims_total"] == 2
    assert head["in_declared_language"] == 1
    assert head["diverged_from_declared"] == 1
    assert head["declared_language_rate"] == 0.5
    assert head["by_script"] == {"cjk": 1, "latin": 1}
    sample = report["diverged_claims_at_head"][0]
    assert sample["anchor"] == "aaaa0002" and sample["script"] == "latin"
    assert report["documents_at_head"] == {"memory/topics/pilot.md": 1}
    assert report["invariants"]["head_fully_in_declared_language"] is False


def test_a_genuinely_bilingual_claim_is_counted_as_mixed_not_as_diverged():
    """`mixed` is its own bucket: a claim carrying real weight in both scripts is a different
    defect from one written wholly in the wrong language, and collapsing them would hide both."""
    report = language_consistency(
        _language_trajectory([CN_CLAIM, MIXED_CLAIM]), declared_language="zh-CN"
    )
    head = report["head"]
    assert head["mixed"] == 1
    assert head["diverged_from_declared"] == 0  # mixed is excluded from diverged
    assert head["in_declared_language"] == 1
    assert not report["diverged_claims_at_head"]


def test_a_stray_latin_token_does_not_make_a_chinese_claim_diverged():
    """Dates, product names and identifiers are Latin in any corpus; the floor keeps them from
    reading as a language switch."""
    report = language_consistency(
        _language_trajectory(["【firm】附录在 2026-05-24 仍未签字，尾款没有付款结果。"]),
        declared_language="zh-CN",
    )
    assert report["head"]["declared_language_rate"] == 1.0


def test_language_consistency_is_available_without_l0():
    """It no longer needs a corpus to be consistent WITH: the declared language is known
    whether or not the trajectory carries its L0, which is the point of declaring it."""
    report = language_consistency(
        trajectory([{"memory/topics/pilot.md": document("memory/topics/pilot.md", [claim("X.", "aaaa0001")])}]),
        declared_language="zh-CN",
    )
    assert report["status"] == "ok"
    assert report["material_script"] is None
    assert report["head"]["claims_total"] == 1


def test_the_declared_language_reaches_the_group_c_entry_point():
    groups = layering_metrics(
        _language_trajectory([CN_CLAIM, EN_CLAIM]), declared_language="zh-CN"
    )
    assert groups["language_consistency"]["head"]["diverged_from_declared"] == 1
