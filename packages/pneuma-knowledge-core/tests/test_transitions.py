"""derive_events: mechanical add/revise derivation from the base→new body diff."""

from pneuma_knowledge_core.compile.transitions import derive_events


def test_new_anchor_yields_claim_added():
    base = {"memory/people/cheng-ye.md": "- 原始。[cite: src-01 ¶0] <!-- c:aa11 -->"}
    new = {
        "memory/people/cheng-ye.md": (
            "- 原始。[cite: src-01 ¶0] <!-- c:aa11 -->\n- 新增。[cite: src-02 ¶1] <!-- c:bb22 -->"
        )
    }
    events = derive_events(base, new)
    assert [(e.type, e.anchor) for e in events] == [("claim_added", "bb22")]
    added = events[0]
    assert added.before is None and "新增" in added.after
    assert added.path == "memory/people/cheng-ye.md"


def test_same_anchor_text_change_yields_claim_revised():
    base = {"memory/people/cheng-ye.md": "- 后端负责人。[cite: src-01 ¶0] <!-- c:aa11 -->"}
    new = {"memory/people/cheng-ye.md": "- 转任架构师。[cite: src-02 ¶3] <!-- c:aa11 -->"}
    events = derive_events(base, new)
    assert [(e.type, e.anchor) for e in events] == [("claim_revised", "aa11")]
    assert "后端负责人" in events[0].before and "架构师" in events[0].after


def test_unchanged_anchor_yields_no_event():
    body = {"memory/people/cheng-ye.md": "- 稳定。[cite: src-01 ¶0] <!-- c:aa11 -->"}
    assert derive_events(body, body) == []


def test_new_document_added_claims():
    base: dict[str, str] = {}
    new = {"memory/topics/q3.md": "- 承诺 A。[cite: src-01 ¶0] <!-- c:cc33 -->"}
    events = derive_events(base, new)
    assert [(e.type, e.anchor) for e in events] == [("claim_added", "cc33")]


def test_mixed_add_and_revise():
    base = {"d.md": "- A 旧。[cite: src-01 ¶0] <!-- c:aa11 -->"}
    new = {
        "d.md": (
            "- A 新。[cite: src-02 ¶1] <!-- c:aa11 -->\n- B 新增。[cite: src-02 ¶2] <!-- c:bb22 -->"
        )
    }
    events = sorted(derive_events(base, new), key=lambda e: e.anchor)
    assert [(e.type, e.anchor) for e in events] == [
        ("claim_revised", "aa11"),
        ("claim_added", "bb22"),
    ]
