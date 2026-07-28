from pneuma_knowledge_core.domain.ids import extract_anchors


def test_extracts_basic_anchor():
    assert extract_anchors("text <!-- c:abcd --> more") == ["abcd"]


def test_requires_at_least_four_hex():
    # 3 hex digits: below the 4+ floor, not an anchor.
    assert extract_anchors("<!-- c:abc -->") == []
    # exactly 4 hex: the boundary, accepted.
    assert extract_anchors("<!-- c:abcd -->") == ["abcd"]
    # longer hex accepted.
    assert extract_anchors("<!-- c:0123456789ab -->") == ["0123456789ab"]


def test_lowercase_hex_only():
    # Uppercase hex is not matched (regex is [0-9a-f]).
    assert extract_anchors("<!-- c:ABCD -->") == []
    assert extract_anchors("<!-- c:AbCd -->") == []


def test_whitespace_variants():
    assert extract_anchors("<!--c:abcd-->") == ["abcd"]
    assert extract_anchors("<!--   c:abcd   -->") == ["abcd"]
    assert extract_anchors("<!--\tc:abcd\t-->") == ["abcd"]


def test_order_and_duplicates_preserved():
    md = "a <!-- c:aaaa --> b <!-- c:bbbb --> c <!-- c:aaaa -->"
    assert extract_anchors(md) == ["aaaa", "bbbb", "aaaa"]


def test_no_anchors():
    assert extract_anchors("plain text, no marks") == []
