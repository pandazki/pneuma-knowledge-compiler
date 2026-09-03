"""The ARCHIVE at the compile boundary and on the glance (docs/design/archive.md §2.1, §4).

Not the rollover volume, whose rules live in test_rollover.py and whose violation kind is
`archive_frozen`: this is `archive/`, the root the Owner moves a retired subject under. Two
mechanical rules — nothing under `archive/` changes in a compile, and an archived document
shadows its live path AND its own title — each held at BOTH faces: the tool, where the model
still has the round in hand, and the gate, which arbitrates over the produced draft.

The title half is finding O3 of the validation run made mechanical: refused at the shadowed
path, a compile created the same subject at the next free slug under a title identical to the
archived page's and rebuilt it live. "One path, one doc_id" had held; "one subject, one page"
had not. Beside the refusal sits its signal — every archive refusal a round hits reaches the
owner on the compile result and in the job's completion detail.

Beside them, the two read faces: a compile never sees the archive at all, and a glance
excludes it unless the call asked for it and then labels what it shows.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from pneuma_knowledge_core.canonical_glance import render_canonical_glance, render_outline
from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError
from pneuma_knowledge_core.compile.gate import archive_refusals, run_gate
from pneuma_knowledge_core.compile.patch import (
    DraftDoc,
    PatchDraft,
    archived_titles,
    document_title,
)
from pneuma_knowledge_core.compile.runner import _build_tools, _render_outline, run_compile
from pneuma_knowledge_core.domain.archive import normalize_title
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill import SkillVersion

from test_runner import FakeCanonicalStore, ScriptedChatModel, tc  # noqa: E402

TEMPLATES = [
    "memory/profile.md",
    "memory/people/{slug}.md",
    "memory/topics/{slug}.md",
]

SOURCES = [
    NormalizedSource(
        raw=RawSource(
            source_id=SourceId("src-01"),
            user_id=UserId("u-1"),
            kind="conversation",
            title="t",
            mime="text/plain",
            checksum="src-01",
            created_at=datetime(2026, 7, 20, tzinfo=timezone.utc),
        ),
        blocks=[NormalizedBlock(index=i, text=f"b{i}") for i in range(4)],
        structure=StructureMap(),
    )
]


def _anchor(path: str, index: int) -> str:
    return hashlib.sha256(f"{path}:{index}".encode()).hexdigest()[:8]


def _doc(path: str, claims: int = 1, **frontmatter: str) -> CanonicalDocument:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    rows = "\n".join(
        f"- Claim {i} about {slug}. [cite: src-01 ¶{i}] <!-- c:{_anchor(path, i)} -->"
        for i in range(claims)
    )
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{hashlib.sha256(path.encode()).hexdigest()[:10]}"),
        path=path,
        frontmatter={
            "doc_id": f"d-{hashlib.sha256(path.encode()).hexdigest()[:10]}",
            "type": "topic",
            "slug": slug,
            **frontmatter,
        },
        body=f"# {slug}\n\n## Notes\n{rows}\n",
    )


LIVE = _doc("memory/topics/atlas.md", claims=2)
ARCHIVED = _doc("archive/memory/topics/aurora.md", claims=2)


def _draft(*docs: CanonicalDocument) -> PatchDraft:
    return PatchDraft.from_canonical(list(docs), TEMPLATES)


def _kinds(violations) -> set[str]:
    return {v.kind for v in violations}


def _tools(draft: PatchDraft) -> dict:
    return {t.name: t for t in _build_tools(draft)}


# ------------------------------------------------------------------------- the gate


def test_an_untouched_archive_passes_the_gate_and_is_not_judged_unowned():
    """The load-bearing case: `archive/…` matches no path template BY CONSTRUCTION, which is
    what makes `create_document` there impossible. Judging it unowned would abort every
    compile after the Owner's first archive, over a path the round never touched."""
    violations = run_gate(_draft(LIVE, ARCHIVED), SOURCES)
    assert violations == []


def test_the_gate_refuses_any_change_under_the_archive():
    draft = _draft(LIVE, ARCHIVED)
    draft.documents()[ARCHIVED.path].body += "\n- Snuck in. [cite: src-01 ¶0] <!-- c:99ff -->\n"
    violations = run_gate(draft, SOURCES)
    assert "archived_path" in _kinds(violations)
    hit = next(v for v in violations if v.kind == "archived_path")
    assert hit.path == ARCHIVED.path
    assert hit.detail == prompt("gate.archived_path")


def test_the_gate_refuses_a_frontmatter_only_change_under_the_archive():
    """`touched_this_round`, not a body comparison: a page answers for what it declares."""
    draft = _draft(LIVE, ARCHIVED)
    draft.documents()[ARCHIVED.path].frontmatter["status"] = "revived"
    assert "archived_path" in _kinds(run_gate(draft, SOURCES))


def test_the_gate_refuses_a_new_document_on_a_path_the_archive_shadows():
    """One path is one document id. The subject comes back by being unarchived."""
    draft = _draft(LIVE, ARCHIVED)
    live_twin = "memory/topics/aurora.md"
    # Poked straight into the working set: no tool can produce this state (the tool face
    # refuses it two tests down), and the gate is the arbiter for whatever reaches a draft
    # without passing through the tools.
    draft._working[live_twin] = DraftDoc(
        path=live_twin,
        doc_id=DocumentId("d-twin"),
        frontmatter={"doc_id": "d-twin", "type": "topic", "slug": "aurora"},
        body="# aurora\n\n- Rewritten. [cite: src-01 ¶0] <!-- c:abcd1234 -->\n",
    )
    violations = run_gate(draft, SOURCES)
    hit = next(v for v in violations if v.kind == "archived_path" and v.path == live_twin)
    assert hit.detail == prompt("gate.archived_path_shadowed", archived=ARCHIVED.path)


# -------------------------------------------------------------------- the tool face


@pytest.mark.parametrize(
    "op,call",
    [
        ("append_block", dict(heading="Notes", text="- New. [cite: src-01 ¶0]")),
        ("edit_claim", dict(anchor_id=_anchor(ARCHIVED.path, 0), new_text="- Edited.")),
        ("supersede_claim", dict(anchor_id=_anchor(ARCHIVED.path, 0), new_text="- Now.")),
        ("set_fields", dict(fields={"status": "revived"})),
    ],
)
def test_every_write_tool_refuses_an_archived_path_before_the_round_is_spent(op, call):
    tools = _tools(_draft(LIVE, ARCHIVED))
    with pytest.raises(AnchorToolError) as err:
        tools[op].func(path=ARCHIVED.path, **call)
    assert str(err.value) == prompt("compile.patch.archived_path", op=op, path=ARCHIVED.path)


def test_create_document_refuses_the_archive_root_with_the_real_reason():
    """Not the ownership message. `archive/…` is outside every template too, so the
    ownership refusal would be true and would teach the model to go hunting for a template
    that lets it write there."""
    tools = _tools(_draft(LIVE, ARCHIVED))
    path = "archive/memory/topics/new.md"
    with pytest.raises(AnchorToolError) as err:
        tools["create_document"].func(path=path, frontmatter={"type": "topic"}, body="- x")
    assert str(err.value) == prompt(
        "compile.patch.archived_path", op="create_document", path=path
    )


def test_create_document_refuses_a_path_the_archive_shadows():
    tools = _tools(_draft(LIVE, ARCHIVED))
    with pytest.raises(AnchorToolError) as err:
        tools["create_document"].func(
            path="memory/topics/aurora.md",
            frontmatter={"type": "topic", "slug": "aurora"},
            body="- Rewritten. [cite: src-01 ¶0]",
        )
    assert str(err.value) == prompt(
        "compile.patch.archived_path_shadowed",
        path="memory/topics/aurora.md",
        archived=ARCHIVED.path,
    )
    # and an unshadowed sibling still creates
    tools["create_document"].func(
        path="memory/topics/borealis.md",
        frontmatter={"type": "topic", "slug": "borealis"},
        body="- Fresh. [cite: src-01 ¶0]",
    )


# -------------------------------------------------------------------- the read faces


def test_the_compile_read_face_hides_the_archive_entirely():
    draft = _draft(LIVE, ARCHIVED)
    tools = _tools(draft)
    assert tools["list_documents"].func() == LIVE.path

    reply = tools["read_document"].func(path=ARCHIVED.path)
    assert reply == prompt("compile.tool.read_document_archived", path=ARCHIVED.path)
    # …and it did NOT count as reading the page: the whole-region writes still refuse it,
    # which is what keeps "was this observed" an honest question.
    with pytest.raises(AnchorToolError):
        tools["rewrite_overview"].func(path=ARCHIVED.path, definition="- x")


def test_the_compile_outline_never_offers_an_archived_document_or_its_volumes():
    volume = _doc("archive/memory/topics/aurora/a01.md", claims=1)
    volume = volume.model_copy(
        update={
            "frontmatter": {**volume.frontmatter, "archived_from": "memory/topics/aurora.md"}
        }
    )
    lines = render_outline([LIVE, ARCHIVED, volume])
    assert lines == render_outline([LIVE])
    assert all("archive/" not in line for line in lines)
    assert _render_outline([LIVE, ARCHIVED, volume]) == lines


def test_an_outline_of_nothing_but_archive_says_the_base_is_empty():
    assert render_outline([ARCHIVED]) == [prompt("compile.task.outline_empty")]


# ------------------------------------------------------------------------ the glance


def _skill() -> SkillVersion:
    return SkillVersion(
        skill_id="test-skill",
        version="t1",
        instructions="body",
        path_templates=list(TEMPLATES),
        content_hash="0" * 64,
    )


def test_the_glance_is_byte_identical_when_the_library_has_no_archive():
    """The whole feature is invisible to a library that never used it."""
    docs = [LIVE, _doc("memory/people/ada-quill.md", claims=1, type="person")]
    assert render_canonical_glance(docs, _skill()) == render_canonical_glance(
        docs, _skill(), include_archived=True
    )


def test_the_glance_excludes_the_archive_by_default():
    docs = [LIVE, ARCHIVED]
    rendered = render_canonical_glance(docs, _skill())
    assert ARCHIVED.path not in rendered
    assert rendered == render_canonical_glance([LIVE], _skill())


def test_include_archived_admits_the_archive_labelled_and_after_the_live_entries():
    docs = [LIVE, ARCHIVED]
    rendered = render_canonical_glance(docs, _skill(), include_archived=True)
    assert ARCHIVED.path in rendered
    archived_line = next(
        line for line in rendered.splitlines() if ARCHIVED.path in line
    )
    assert archived_line.endswith(prompt("recall.glance.entry_tail_in_archive") + ")")
    # filed under the family of the path it will have again, and after the live document
    assert rendered.index(LIVE.path) < rendered.index(ARCHIVED.path)
    assert "memory/topics/{slug}.md" in rendered
    assert prompt("recall.glance.unfiled_heading") not in rendered


def test_an_archived_document_keeps_its_volumes_collapsed_onto_its_own_line():
    """A volume travelled into the archive with its document and kept the stamp naming the
    LIVE path. Unpaired it would be listed on its own, its `a01` filename standing in for a
    subject name — the exact failure the rollover collapse exists to prevent."""
    volume = _doc("archive/memory/topics/aurora/a01.md", claims=1)
    volume = volume.model_copy(
        update={
            "frontmatter": {**volume.frontmatter, "archived_from": "memory/topics/aurora.md"}
        }
    )
    rendered = render_canonical_glance(
        [LIVE, ARCHIVED, volume], _skill(), include_archived=True
    )
    assert volume.path not in rendered
    assert prompt("recall.glance.entry_tail_volumes", count=1) in rendered


# --------------------------------------------- the archive shadows its TITLE, not just its path
#
# Finding O3, made mechanical. The path rule held "one path, one doc_id" and could not hold
# "one subject, one page": refused at `threads/small-group-invitation.md`, the compile created
# `threads/small-scale-invitation.md` with a byte-identical title and rebuilt the retired
# subject live, overview and all.

ARCHIVED_TITLE = "Small-group invitation — the first success"
TWIN_PATH = "memory/topics/small-scale-invitation.md"


def _titled(doc: CanonicalDocument, title: str) -> CanonicalDocument:
    """The same document under a real name: `# ` heading and `title` frontmatter together,
    exactly as every write path leaves it (`with_derived_title`)."""
    body = doc.body.split("\n", 1)[1]
    return doc.model_copy(
        update={
            "frontmatter": {**doc.frontmatter, "title": title},
            "body": f"# {title}\n{body}",
        }
    )


NAMED = _titled(_doc("archive/memory/topics/small-group-invitation.md", claims=2), ARCHIVED_TITLE)


def _create(tools: dict, path: str, title: str, slug: str = "twin") -> str:
    return tools["create_document"].func(
        path=path,
        frontmatter={"type": "topic", "slug": slug},
        body=f"# {title}\n\n- Rebuilt live. [cite: src-01 ¶0]",
    )


def test_the_normalization_rule_is_equality_over_the_name_minus_its_separators():
    """Case, spacing and separator punctuation — ASCII and CJK alike — cannot dodge it."""
    assert normalize_title("Small-group invitation") == normalize_title("small group INVITATION")
    assert normalize_title("小范围邀请：首次成功") == normalize_title("小范围邀请，首次成功")
    assert normalize_title("数据「结构」…—— 与算法") == normalize_title("数据结构，与算法")
    # …and it is not a similarity measure: a paraphrase is a different title, by design.
    assert normalize_title("Small-group invitation") != normalize_title("Small-scale invitation")


def test_a_fullwidth_spelling_folds_onto_the_ascii_one():
    """NFKC first, so the same name typed on a CJK keyboard is the same name."""
    assert normalize_title("Ｑ３ launch") == normalize_title("q3launch")
    assert normalize_title("Ｃ＃ 指南") == normalize_title("C# 指南")


def test_a_symbol_that_carries_the_name_survives_normalization():
    """The reason the dropped set is a FIXED list and not "every `P*` category": under a
    category rule `C#` normalizes to `c`, and an archived C# page would then refuse a live
    `C` page it has nothing to do with. Symbols are meaning; only separators go."""
    assert normalize_title("C#") != normalize_title("C")
    assert normalize_title("C++") != normalize_title("C")
    assert normalize_title("R&D roadmap") != normalize_title("RD roadmap")
    # …and they are not merely different — they survive intact.
    assert normalize_title("C# — the guide") == "c#theguide"


def test_create_document_refuses_an_archived_subjects_title_at_another_path():
    tools = _tools(_draft(LIVE, NAMED))
    with pytest.raises(AnchorToolError) as err:
        _create(tools, TWIN_PATH, ARCHIVED_TITLE, slug="small-scale-invitation")
    assert str(err.value) == prompt(
        "compile.patch.archived_title_shadowed",
        path=TWIN_PATH,
        title=ARCHIVED_TITLE,
        archived=NAMED.path,
    )


@pytest.mark.parametrize(
    "title",
    [
        ARCHIVED_TITLE.upper(),
        "  Small-group   invitation —   the first success  ",
        "Small group invitation: the first success!",
        "Ｓmall-group invitation — the first success",
    ],
)
def test_a_title_that_differs_only_in_case_spacing_or_punctuation_is_the_same_subject(title):
    tools = _tools(_draft(LIVE, NAMED))
    with pytest.raises(AnchorToolError) as err:
        _create(tools, TWIN_PATH, title, slug="small-scale-invitation")
    assert NAMED.path in str(err.value)


def test_a_different_title_at_a_free_path_still_creates():
    """The rule is equality, and it costs a genuinely new subject nothing."""
    draft = _draft(LIVE, NAMED)
    tools = _tools(draft)
    _create(tools, "memory/topics/borealis.md", "Borealis pilot", slug="borealis")
    assert run_gate(draft, SOURCES) == []
    assert draft.archive_refusals == []


def test_the_gate_refuses_the_same_title_when_the_tool_face_is_bypassed():
    draft = _draft(LIVE, NAMED)
    # Poked straight into the working set: no tool can produce this state (the face refuses
    # it above), and the gate is the arbiter for whatever reaches a draft another way.
    draft._working[TWIN_PATH] = DraftDoc(
        path=TWIN_PATH,
        doc_id=DocumentId("d-twin"),
        frontmatter={"doc_id": "d-twin", "type": "topic", "slug": "small-scale-invitation"},
        body=f"# {ARCHIVED_TITLE}\n\n- Rebuilt live. [cite: src-01 ¶0] <!-- c:abcd1234 -->\n",
    )
    violations = run_gate(draft, SOURCES)
    hit = next(v for v in violations if v.kind == "archived_path" and v.path == TWIN_PATH)
    assert hit.detail == prompt(
        "gate.archived_title_shadowed", title=ARCHIVED_TITLE, archived=NAMED.path
    )


def test_the_title_rule_judges_only_NEW_documents():
    """A live page that has carried its name since before the archive existed is not
    retroactively refused — the rule is about creating a second page for a retired subject."""
    live_twin = _titled(_doc("memory/topics/reunion.md", claims=1), ARCHIVED_TITLE)
    draft = _draft(live_twin, NAMED)
    assert run_gate(draft, SOURCES) == []


# ------------------------------------------------------- inert while the archive is empty


def test_with_no_archive_nothing_about_the_compile_face_changes():
    """The whole rule is a no-op in a library that has never archived anything: no path is
    under `archive/`, so the title map is empty and every name is free."""
    docs = [LIVE, _titled(_doc("memory/topics/aurora.md", claims=1), ARCHIVED_TITLE)]
    draft = PatchDraft.from_canonical(docs, TEMPLATES)
    tools = _tools(draft)
    assert archived_titles(draft.base_documents().values()) == {}
    assert tools["list_documents"].func() == "\n".join(sorted(d.path for d in docs))
    assert render_outline(docs) == _render_outline(docs)
    # …including creating a page that carries a LIVE page's title, which is somebody else's
    # rule (or nobody's) and never this one.
    _create(tools, "memory/topics/reunion.md", ARCHIVED_TITLE, slug="reunion")
    assert draft.archive_refusals == []
    assert [v for v in run_gate(draft, SOURCES) if v.kind == "archived_path"] == []


# ------------------------------------------------- the refusal is a signal the owner reads


def test_every_archive_refusal_is_collected_from_both_faces_and_deduplicated():
    draft = _draft(LIVE, NAMED)
    tools = _tools(draft)
    for _ in range(2):  # a refused model tries again; that is one fact, not two
        with pytest.raises(AnchorToolError):
            _create(tools, TWIN_PATH, ARCHIVED_TITLE, slug="small-scale-invitation")
    with pytest.raises(AnchorToolError):
        _create(tools, "memory/topics/small-group-invitation.md", "Something else", slug="s")
    with pytest.raises(AnchorToolError):
        tools["append_block"].func(path=NAMED.path, heading="Notes", text="- x [cite: src-01 ¶0]")

    records = archive_refusals(run_gate(draft, SOURCES), draft)
    assert records == [
        {
            "kind": "title",
            "path": TWIN_PATH,
            "archived": NAMED.path,
            "title": ARCHIVED_TITLE,
            "attempted": ARCHIVED_TITLE,
        },
        {
            "kind": "path",
            "path": "memory/topics/small-group-invitation.md",
            "archived": NAMED.path,
            "title": ARCHIVED_TITLE,
            "attempted": None,
        },
        {
            "kind": "path",
            "path": NAMED.path,
            "archived": NAMED.path,
            "title": ARCHIVED_TITLE,
            "attempted": None,
        },
    ]


def test_a_title_refusal_names_the_ARCHIVED_page_and_keeps_the_attempted_spelling():
    """B5. Two attempts differing only in punctuation are ONE fact: they normalize to the
    same subject, so the record is deduplicated on `(kind, path, archived)`. And what the
    record is ABOUT is the retired subject — so `title` is the archived page's own name, not
    whichever spelling the round happened to reach for; that spelling travels beside it as
    `attempted`, so nothing the round did is lost."""
    draft = _draft(LIVE, NAMED)
    tools = _tools(draft)
    attempts = [
        "Small group invitation: the first success",
        "Small-group invitation, the first success!",
    ]
    for attempt in attempts:
        assert attempt != ARCHIVED_TITLE
        with pytest.raises(AnchorToolError):
            _create(tools, TWIN_PATH, attempt, slug="small-scale-invitation")

    assert archive_refusals(run_gate(draft, SOURCES), draft) == [
        {
            "kind": "title",
            "path": TWIN_PATH,
            "archived": NAMED.path,
            "title": ARCHIVED_TITLE,
            "attempted": attempts[0],
        }
    ]


def test_a_gate_only_refusal_is_collected_too():
    """The tool face saw nothing — the draft was written another way — and the owner still
    hears about it, because the collector reads the gate's own violations."""
    draft = _draft(LIVE, NAMED)
    draft._working[TWIN_PATH] = DraftDoc(
        path=TWIN_PATH,
        doc_id=DocumentId("d-twin"),
        frontmatter={"doc_id": "d-twin", "type": "topic", "slug": "small-scale-invitation"},
        body=f"# {ARCHIVED_TITLE}\n\n- Rebuilt live. [cite: src-01 ¶0] <!-- c:abcd1234 -->\n",
    )
    assert draft.archive_refusals == []
    assert archive_refusals(run_gate(draft, SOURCES), draft) == [
        {
            "kind": "title",
            "path": TWIN_PATH,
            "archived": NAMED.path,
            "title": ARCHIVED_TITLE,
            "attempted": ARCHIVED_TITLE,
        }
    ]


async def test_the_compile_result_carries_the_refusals_the_round_hit():
    """End to end through `run_compile`: the model goes looking for a retired subject, is
    refused, writes elsewhere, and the committed result still says what it went looking for."""
    store = FakeCanonicalStore([LIVE, NAMED])
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path=TWIN_PATH,
                    frontmatter={"type": "topic", "slug": "small-scale-invitation"},
                    body=f"# {ARCHIVED_TITLE}\n\n- Back again. [cite: src-01 ¶0]",
                ),
                tc(
                    "create_document",
                    path="memory/topics/borealis.md",
                    frontmatter={"type": "topic", "slug": "borealis"},
                    body="# Borealis pilot\n\n- A genuinely new subject. [cite: src-01 ¶1]",
                ),
                tc("finish_compile"),
            ]
        ]
    )
    result = await run_compile(
        user_id=UserId("u-1"),
        model=model,
        store=store,
        sources=SOURCES,
        skill=_skill(),
    )
    assert result.status == "committed"
    assert TWIN_PATH not in result.files
    assert result.archive_refusals == [
        {
            "kind": "title",
            "path": TWIN_PATH,
            "archived": NAMED.path,
            "title": ARCHIVED_TITLE,
            "attempted": ARCHIVED_TITLE,
        }
    ]


async def test_a_library_with_no_archive_reports_no_refusals():
    store = FakeCanonicalStore([LIVE])
    model = ScriptedChatModel(
        turns=[
            [
                tc(
                    "create_document",
                    path="memory/topics/borealis.md",
                    frontmatter={"type": "topic", "slug": "borealis"},
                    body="# Borealis pilot\n\n- New. [cite: src-01 ¶1]",
                ),
                tc("finish_compile"),
            ]
        ]
    )
    result = await run_compile(
        user_id=UserId("u-1"), model=model, store=store, sources=SOURCES, skill=_skill()
    )
    assert result.status == "committed"
    assert result.archive_refusals == []
