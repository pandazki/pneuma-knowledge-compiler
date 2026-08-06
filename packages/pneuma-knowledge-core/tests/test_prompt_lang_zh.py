"""The Chinese language pack, held to the English catalog by two mechanical pins.

A language pack is the one kind of overlay that must be TOTAL: a missing key silently
leaves an English sentence inside an otherwise Chinese contract, and nobody re-reads a
10-kilobyte prompt to notice. So the key set is pinned to `default_catalog()` in both
directions, and every translation's placeholder contract is pinned to its original's —
the same check `override_prompt` and the console's apply gate run, applied to all of it
at once instead of one clause at a time.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.prompts import (
    chinese_overlay,
    default_catalog,
    override_prompts,
    prompt,
    reset_prompt_overrides,
    template_fields,
)


@pytest.fixture(autouse=True)
def _clean_overrides():
    reset_prompt_overrides()
    yield
    reset_prompt_overrides()


def test_the_pack_covers_exactly_the_catalog_no_key_more_no_key_less():
    """Both directions on purpose. A catalog key with no translation leaves English prose
    in a Chinese prompt; a stale key here is a translation of a surface that no longer
    exists, which `override_prompts` would refuse at startup — after the deployment already
    believed it had a Chinese engine."""
    catalog = set(default_catalog())
    pack = set(chinese_overlay())
    assert sorted(pack - catalog) == [], "translations for keys the catalog does not declare"
    assert sorted(catalog - pack) == [], "catalog surfaces with no Chinese translation"


def test_every_translation_declares_exactly_its_originals_placeholders():
    """`{owner}`, `{templates}`, `{cite}` are values the framework computes and substitutes.
    A translation that drops one renders short in the one layer nobody re-reads; one that
    invents one reaches the model as literal braces. Neither is a wording preference, so
    neither is left to review."""
    catalog = default_catalog()
    pack = chinese_overlay()
    problems = {
        key: (sorted(template_fields(catalog[key])), sorted(template_fields(pack[key])))
        for key in sorted(catalog)
        if template_fields(catalog[key]) != template_fields(pack[key])
    }
    assert problems == {}


def test_the_pack_registers_through_the_ordinary_overlay_seam():
    """It is an overlay like any other — which is what lets a deployment's own clauses sit
    on top of it, and what puts its bytes into `prompt_overlay_hash()`."""
    override_prompts(chinese_overlay())
    assert prompt("compile.rules_header").startswith("## 要可呈现")
    # a substituted surface still substitutes
    rendered = prompt("compile.skill_header", skill_id="biz", version="v1")
    assert "biz v1" in rendered and "{" not in rendered


def test_the_machine_read_tokens_are_not_translated():
    """Three classes of catalog value are read by a program, not by a model: the eval
    judges' verdict token, the `[cite: …]` marker taught to the compiler, and the JSON
    locator shape the deep tools take. Translating any of them would break the parser that
    consumes it, so they are asserted rather than trusted to review."""
    pack = chinese_overlay()
    assert pack["eval.qa.judge_verdict_yes"] == "YES"
    assert pack["eval.truth_judge.verdict_yes"] == "YES"
    assert "[cite: <source_id> ¶<start>-<end>]" in pack["compile.write_contract"]
    assert '{"blocks": [start, end]}' in pack["recall.deep.contract_head"]


# ─────────────────────────────────── the claims the verification pass found untrue or unreadable
#
# Each of these was a sentence a reader had to resolve for themselves. They are asserted in
# both packs, because a fix in one language is half a fix: the model receives whichever pack
# the deployment runs.


def test_the_authority_boundary_reads_the_same_in_both_packs():
    """VERIFY #4. §1 likened the compiled artifact to an executable that "can be rebuilt",
    then defined canonical as authoritative and NOT rebuildable."""
    for pack in (default_catalog(), chinese_overlay()):
        contract = pack["compile.write_contract"]
        # the analogy now names where it stops
        assert ("Where the analogy" in contract) or ("这个类比在哪里停下" in contract)
        # and no clause claims the index levels cover every source unconditionally
        assert "unconditionally" not in contract
        assert "无条件" not in contract


def test_l2_is_stated_as_per_source_and_l1_as_total():
    for pack in (default_catalog(), chinese_overlay()):
        contract = pack["compile.write_contract"]
        assert ("intake plan" in contract) or ("接收方案" in contract)


def test_the_snapshot_declaration_reads_in_one_pass():
    """VERIFY #9: "一份自拍下之后从未改变" — the core boundary sentence of snapshot-scoped
    answering opened with something a Chinese reader parses as "selfie" on the first pass."""
    zh = chinese_overlay()["recall.snapshot.declaration"]
    assert "自拍下之后" not in zh
    assert "从拍下那一刻起就没有变过" in zh


def test_the_briefing_head_no_longer_calls_an_in_range_search_a_route_outside_the_pack():
    """VERIFY #10: it announced two routes "for what lies outside" the pack and then defined
    the first as searching within the pack's own range."""
    en = default_catalog()["recall.briefing.contract_head"]
    zh = chinese_overlay()["recall.briefing.contract_head"]
    assert "reach past what it laid out" in en and "SAMPLE" in en
    assert "越过它摊开的这部分" in zh and "样本" in zh
    # and each route now states its own reach
    assert "session's source range" in en and "any source's original text verbatim by id" in en
    assert "本次会话的来源范围" in zh and "按 id 逐字取出任意来源" in zh


def test_the_card_expansion_says_what_the_boundary_becomes_with_no_citation():
    """VERIFY #17: the contract promises the expansion stays inside the cited source text; in
    the no-citation branch there is none, and nothing said what replaced that bound."""
    en = default_catalog()["recall.suggestion.detail_no_sources"]
    zh = chinese_overlay()["recall.suggestion.detail_no_sources"]
    assert "the whole boundary" in en and "add no detail" in en
    assert "就是全部边界" in zh and "不要添加" in zh


def test_the_segmenter_rubric_names_no_industry():
    """VERIFY #16: the lowest-level segmentation rubric used "one candidate" twice, putting a
    recruiting scene into a framework that claims to be domain-neutral — and into the model's
    prior about where a topic boundary is."""
    en = default_catalog()["ingest.semantic.rubric"]
    zh = chinese_overlay()["ingest.semantic.rubric"]
    assert "candidate" not in en
    assert "候选人" not in zh
    # the rubric itself is unchanged otherwise: the unit is still "one natural unit"
    assert "one natural unit" in en and "一个自然单元" in zh


def test_the_zh_pack_says_正本_and_never_正典():
    """VERIFY #8: the Chinese vocabulary drifted between 正本 / 正典 / canonical with no
    declaration that they are one thing, so a first-time reader had to guess whether they were
    synonyms or layers. One word in the pack, asserted rather than reviewed."""
    for key, clause in sorted(chinese_overlay().items()):
        assert "正典" not in clause, key


def test_断言_carries_its_english_gloss_where_a_reader_first_meets_it():
    """A gloss further down the document is a gloss for somebody who already knew. This checks
    the FIRST occurrence in every clause that glosses the term at all."""
    for key, clause in sorted(chinese_overlay().items()):
        gloss = clause.find("（claim")
        if gloss < 0:
            continue
        first = clause.find("断言")
        assert first >= 0 and gloss - first <= 2, (
            f"{key}: 断言 appears at {first} and its gloss only at {gloss} — a reader meets the "
            "term before it is explained"
        )
