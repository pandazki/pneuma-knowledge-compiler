"""Query-local citation aliasing: real source ids ↔ short sNN handles at the LLM boundary."""

from __future__ import annotations

from pneuma_knowledge_core.recall.citation_alias import (
    alias_sources,
    iter_answer_citations,
    resolve_handles,
)


def test_alias_relabels_distinct_ids_to_query_local_handles():
    text = (
        "[cite: 6c8e8aec5d704e9d9985b55818ac58cd ¶2-4] 甲\n"
        "[cite: 645073dbe08847689c8b41f87a871618 ¶0-1] 乙\n"
        "[cite: 6c8e8aec5d704e9d9985b55818ac58cd ¶9-9] 甲又一次"
    )
    aliased, handle_map = alias_sources(text)
    # first-appearance order; the same real id reuses its handle
    assert "[cite: s01 ¶2-4]" in aliased
    assert "[cite: s02 ¶0-1]" in aliased
    assert "[cite: s01 ¶9-9]" in aliased
    assert "6c8e8aec5d704e9d9985b55818ac58cd" not in aliased  # long id hidden from the LLM
    assert handle_map == {
        "s01": "6c8e8aec5d704e9d9985b55818ac58cd",
        "s02": "645073dbe08847689c8b41f87a871618",
    }


def test_resolve_reverses_the_answer_handles():
    _, handle_map = alias_sources("[cite: abcdef1234 ¶1-2] x")
    answer = "结论。[cite: s01]"
    assert resolve_handles(answer, handle_map) == "结论。[cite: abcdef1234]"


def test_resolve_leaves_unknown_handles_untouched():
    # a garbled/hallucinated handle the map doesn't know is passed through verbatim.
    assert resolve_handles("答。[cite: s99]", {"s01": "x"}) == "答。[cite: s99]"


def test_empty_text_yields_empty_map():
    aliased, m = alias_sources("没有引用的答案")
    assert aliased == "没有引用的答案" and m == {}


def test_iter_answer_citations_single_span():
    spans = list(iter_answer_citations("结论。[cite: s01 ¶2-4] 尾。"))
    assert spans == [("s01", 2, 4)]


def test_iter_answer_citations_open_ended_span_is_a_single_block():
    assert list(iter_answer_citations("[cite: s01 ¶7]")) == [("s01", 7, 7)]


def test_iter_answer_citations_expands_merged_same_source_spans():
    # the free-text answer merged two spans of one source into one bracket
    spans = list(iter_answer_citations("见 [cite: s01 ¶1-3, ¶5-7] 处。"))
    assert spans == [("s01", 1, 3), ("s01", 5, 7)]


def test_iter_answer_citations_expands_merged_multi_source_bracket():
    spans = list(iter_answer_citations("[cite: s01 ¶1-3, s02 ¶2-4; s03 ¶9]"))
    assert spans == [("s01", 1, 3), ("s02", 2, 4), ("s03", 9, 9)]


def test_iter_answer_citations_ignores_source_level_and_template_tokens():
    # a bare source-level cite has no block span; template placeholders carry no ¶ digit.
    assert list(iter_answer_citations("[cite: s01] 与 [cite: <source_id> ¶a-b]")) == []


def test_session_aliaser_keeps_one_handle_per_source_across_calls():
    from pneuma_knowledge_core.recall.citation_alias import SessionAliaser

    s = SessionAliaser()
    # pack render, then a tool result mentioning one same + one new source
    a1 = s.alias("[cite: uuidA ¶0-1] 甲\n[cite: uuidB ¶2-3] 乙")
    a2 = s.alias("[cite: uuidA ¶9-9] 甲再现\n[cite: uuidC ¶0-0] 丙")
    assert "[cite: s01 ¶0-1]" in a1 and "[cite: s02 ¶2-3]" in a1
    assert "[cite: s01 ¶9-9]" in a2  # same source reuses its handle across renders
    assert "[cite: s03 ¶0-0]" in a2  # a new source gets the next handle
    assert s.handle_map == {"s01": "uuidA", "s02": "uuidB", "s03": "uuidC"}
    # a tool receiving a handle resolves it back to the real id; a real id passes through.
    assert s.to_real("s02") == "uuidB"
    assert s.to_real("uuidZ") == "uuidZ"
    # the final answer's handles map back to real ids.
    assert s.resolve("见 [cite: s01] 和 [cite: s03]") == "见 [cite: uuidA] 和 [cite: uuidC]"
