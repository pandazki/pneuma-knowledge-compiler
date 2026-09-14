"""What the write mechanism refuses from now on (docs/design/structure-lens.md §6).

Four mechanical faults a real library accumulated, none of which a prompt line ever
prevented: a `# ` heading typed inside a claim (which silently renamed the page), a body
whose line breaks arrived as the two characters `\\n`, a page that took the wrong name and
had no verb to correct it, and a title carrying a character YAML misreads. Each is refused
where the round can still fix it, and each has a gate behind the refusal.
"""

from __future__ import annotations

import pytest

from pneuma_knowledge_core.canonical_glance import document_title, render_canonical_glance
from pneuma_knowledge_core.compile.anchor_ops import AnchorToolError, MAX_LINE_CHARS
from pneuma_knowledge_core.compile.documents import (
    derived_title,
    parse_document,
    render_document,
    set_leading_title,
)
from pneuma_knowledge_core.compile.gate import (
    VIOLATION_KINDS,
    check_heading_in_block,
    check_title_siblings,
    violation_catalog,
)
from pneuma_knowledge_core.compile.patch import PatchDraft
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId

TEMPLATES = ["memory/topics/{slug}.md", "memory/people/{slug}.md"]


def canonical(path: str, body: str, **frontmatter) -> CanonicalDocument:
    frontmatter.setdefault("type", "topic")
    frontmatter.setdefault("slug", path.rsplit("/", 1)[-1].removesuffix(".md"))
    return CanonicalDocument(
        doc_id=DocumentId(path[-12:].rjust(12, "x")),
        path=path,
        frontmatter=frontmatter,
        body=body,
    )


def draft_with(*docs: CanonicalDocument) -> PatchDraft:
    return PatchDraft.from_canonical(list(docs), TEMPLATES)


def a_page(path="memory/topics/atlas.md", title="Atlas") -> CanonicalDocument:
    return canonical(
        path,
        f"# {title}\n\n## Facts\n\nIt exists. [cite: s01 ¶0-1] <!-- c:a1111111 -->",
        title=title,
    )


# ─────────────────────────────────────────────────────────────── heading_in_block


@pytest.mark.parametrize(
    "call",
    [
        lambda d: d.append_block("memory/topics/atlas.md", "Facts", "# Renamed\n\nsomething"),
        lambda d: d.edit_claim("memory/topics/atlas.md", "a1111111", "# Renamed"),
        lambda d: d.supersede_claim(
            "memory/topics/atlas.md", "a1111111", "# Renamed [cite: s01 ¶2-2]"
        ),
    ],
)
def test_a_claim_level_write_refuses_a_heading_that_would_rename_the_page(call):
    draft = draft_with(a_page())
    with pytest.raises(AnchorToolError) as excinfo:
        call(draft)
    assert "Renamed" in str(excinfo.value)
    assert "retitle" in str(excinfo.value)


def test_an_overview_slot_refuses_a_heading_too():
    from pneuma_knowledge_core.compile.documents import Overview

    draft = draft_with(a_page())
    draft.mark_read("memory/topics/atlas.md")
    with pytest.raises(AnchorToolError):
        draft.rewrite_overview(
            "memory/topics/atlas.md",
            Overview(definition="# Renamed c:a1111111"),
        )


def test_create_document_accepts_a_leading_heading_and_refuses_one_below_it():
    draft = draft_with()
    draft.create_document(
        "memory/topics/atlas.md",
        {"type": "topic", "slug": "atlas"},
        "# Atlas\n\n## Facts\n\nIt exists. [cite: s01 ¶0-1]",
    )
    with pytest.raises(AnchorToolError):
        draft.create_document(
            "memory/topics/rift.md",
            {"type": "topic", "slug": "rift"},
            "# Rift\n\n## Facts\n\nIt exists. [cite: s01 ¶0-1]\n\n# Second name",
        )


def test_the_gate_refuses_a_heading_a_draft_acquired_by_another_path():
    """The write faces are the teaching refusal; the gate is the arbiter over the produced
    draft. It judges the pages this round changed, and only the headings this round
    INTRODUCED — nothing can delete a heading a page already carried, so refusing the page
    for one would be a deadlock."""
    stale = canonical(
        "memory/topics/legacy.md",
        "# Legacy\n\n## Facts\n\nIt exists. <!-- c:a2222222 -->\n\n# Second name\n",
        title="Legacy",
    )
    draft = draft_with(stale)
    assert check_heading_in_block(draft.documents(), draft.base_bodies()) == []
    doc = draft.read("memory/topics/legacy.md")
    doc.body += "\n\nA new fact. [cite: s01 ¶0-1] <!-- c:a3333333 -->"
    # The page changed; the heading it already carried is grandfathered.
    assert check_heading_in_block(draft.documents(), draft.base_bodies()) == []
    doc.body += "\n\n# A third name\n"
    violations = check_heading_in_block(draft.documents(), draft.base_bodies())
    assert [v.kind for v in violations] == ["heading_in_block"]
    assert "A third name" in violations[0].detail


def test_the_two_new_kinds_are_in_the_enumerable_violation_catalog():
    kinds = {kind for kind, _ in VIOLATION_KINDS}
    assert {"heading_in_block", "title_sibling_collision"} <= kinds
    catalog = dict(violation_catalog())
    assert catalog["heading_in_block"] and catalog["title_sibling_collision"]


# ───────────────────────────────────────────────────────────── escaped_newlines


def test_text_whose_line_breaks_arrived_escaped_is_refused_with_the_fault_named():
    draft = draft_with(a_page())
    with pytest.raises(AnchorToolError) as excinfo:
        draft.append_block(
            "memory/topics/atlas.md", "Facts", "one.\\ntwo.\\nthree.\\nfour."
        )
    assert "\\n" in str(excinfo.value)
    assert "3" in str(excinfo.value)


def test_a_single_line_long_enough_to_be_a_document_is_refused():
    draft = draft_with(a_page())
    with pytest.raises(AnchorToolError) as excinfo:
        draft.append_block("memory/topics/atlas.md", "Facts", "x" * MAX_LINE_CHARS)
    assert str(MAX_LINE_CHARS) in str(excinfo.value)


def test_a_body_with_real_line_breaks_and_one_escape_is_accepted():
    """The predicate is "no real line break", not "no backslash-n": a claim may legitimately
    quote the sequence."""
    draft = draft_with(a_page())
    draft.append_block(
        "memory/topics/atlas.md",
        "Facts",
        "The log printed `\\n`. [cite: s01 ¶2-2]\n\nAnd then stopped. [cite: s01 ¶3-3]",
    )


# ───────────────────────────────────────────────── the title is the leading heading


def test_derived_title_reads_the_leading_heading_and_nothing_further_down():
    assert derived_title("# Atlas\n\nbody") == "Atlas"
    assert derived_title("# Atlas <!-- c:a1111111 -->\n\nbody") == "Atlas"
    assert derived_title("body\n\n# Not the name") == ""
    assert derived_title("## A section\n\n# Not the name") == ""


def test_a_closed_volume_is_labelled_from_its_owner_on_the_read_faces():
    owner = canonical("memory/topics/atlas.md", "# Atlas Atlas\n\n## Facts\n\nA. <!-- c:a1 -->")
    volume = canonical(
        "memory/topics/atlas/a02.md",
        "## Earlier\n\nOld. <!-- c:a2 -->",
        type="archive",
        archived_from="memory/topics/atlas.md",
    )
    # On its own a volume is still named by its own filename — nothing invented.
    assert document_title(volume) == "a02"
    # Given the library, it borrows the name of the page it is a volume OF.
    assert document_title(volume, [owner, volume]) == "Atlas Atlas · vol. 02"
    # …and a page that is not a volume is unchanged by the mapping.
    assert document_title(owner, [owner, volume]) == "Atlas Atlas"
    glance = render_canonical_glance([owner, volume], templates=TEMPLATES)
    assert "a02" not in glance


def test_a_mid_body_heading_no_longer_becomes_a_volumes_stored_title():
    """A closed volume's body opens with a `## ` section, so the leading-only rule leaves it
    with no title of its own — which is the point: it is named from its owner."""
    body = "## 2026-01\n\nOld. <!-- c:a2 -->\n\n# A heading somebody typed\n"
    from pneuma_knowledge_core.compile.documents import with_derived_title

    assert with_derived_title({"type": "archive"}, body) == {"type": "archive"}


# ─────────────────────────────────────────────────────── a title YAML can read back


@pytest.mark.parametrize(
    "title",
    [
        "Aurora: phase two",
        "C# migration",
        'It said "no"',
        "It's fine",
        "# not a heading",
        "a literal \\n inside",
        "- leading dash",
        "plain name",
        "小范围邀请：首次成功",
    ],
)
def test_a_title_round_trips_through_the_frontmatter_whatever_it_carries(title):
    text = render_document({"slug": "x", "title": title}, f"# {title}")
    frontmatter, _ = parse_document(text)
    assert frontmatter["title"] == title


def test_only_the_title_is_quoted_so_no_other_field_moves_a_byte():
    text = render_document({"slug": "x", "note": "a: b", "title": "plain"}, "# plain")
    assert "note: a: b" in text
    assert "title: plain" in text


# ───────────────────────────────────────────────────────────────────────── retitle


def test_retitle_rewrites_the_leading_heading_and_the_derived_frontmatter():
    draft = draft_with(a_page())
    doc = draft.retitle("memory/topics/atlas.md", "Atlas of currents")
    assert doc.body.startswith("# Atlas of currents\n")
    assert doc.frontmatter["title"] == "Atlas of currents"
    assert "c:a1111111" in doc.body  # not one claim was touched


def test_retitle_inserts_a_heading_when_the_page_has_none():
    page = canonical(
        "memory/topics/atlas.md", "## Facts\n\nIt exists. <!-- c:a1111111 -->", title=""
    )
    draft = draft_with(page)
    doc = draft.retitle("memory/topics/atlas.md", "Atlas")
    assert doc.body.split("\n")[0] == "# Atlas"
    assert "## Facts" in doc.body


def test_set_leading_title_keeps_the_system_markers_on_the_heading_line():
    assert (
        set_leading_title("# Old <!-- c:a1111111 -->\n\nbody", "New")
        == "# New <!-- c:a1111111 -->\n\nbody"
    )


def test_retitle_refuses_an_empty_name():
    draft = draft_with(a_page())
    with pytest.raises(AnchorToolError) as excinfo:
        draft.retitle("memory/topics/atlas.md", "   ")
    assert "memory/topics/atlas.md" in str(excinfo.value)


def test_retitle_refuses_a_closed_volume_and_an_archived_page_and_a_record():
    volume = canonical(
        "memory/topics/atlas/a02.md",
        "## Earlier\n\nOld. <!-- c:a2222222 -->",
        archived_from="memory/topics/atlas.md",
    )
    archived = canonical("archive/memory/topics/old.md", "# Old\n\n## A\n\nx <!-- c:a3333333 -->")
    record = canonical(
        "memory/topics/gone.md",
        "# Gone\n\n## A\n\nx <!-- c:a4444444 -->",
        type="archived",
        archive_of="archive/memory/topics/gone.md",
    )
    draft = draft_with(a_page(), volume, archived, record)
    for path in (volume.path, archived.path, record.path):
        with pytest.raises(AnchorToolError):
            draft.retitle(path, "Anything")


def test_retitle_refuses_a_name_an_archived_subject_already_carries():
    archived = canonical(
        "archive/memory/topics/old.md",
        "# Retired idea\n\n## A\n\nx <!-- c:a3333333 -->",
        title="Retired idea",
    )
    draft = draft_with(a_page(), archived)
    with pytest.raises(AnchorToolError) as excinfo:
        draft.retitle("memory/topics/atlas.md", "Retired idea")
    assert "Retired idea" in str(excinfo.value)
    assert draft.archive_refusals and draft.archive_refusals[0]["kind"] == "title"


def test_the_gate_refuses_a_title_a_live_sibling_already_carries():
    draft = draft_with(a_page(), a_page("memory/topics/rift.md", "Rift"))
    assert check_title_siblings(draft.documents(), draft.base_documents()) == []
    draft.retitle("memory/topics/rift.md", "Atlas")
    violations = check_title_siblings(draft.documents(), draft.base_documents())
    assert [v.kind for v in violations] == ["title_sibling_collision"]
    assert violations[0].path == "memory/topics/rift.md"
    assert "memory/topics/atlas.md" in violations[0].detail


def test_a_sibling_collision_two_untouched_pages_carried_already_does_not_abort_a_round():
    """Judged for the pages this round TOUCHED. A collision two legacy pages have carried for
    months is the lens's `id.title_duplicate` to report, not a reason to refuse a compile
    that never looked at either."""
    draft = draft_with(a_page(), a_page("memory/topics/rift.md", "Atlas"))
    assert check_title_siblings(draft.documents(), draft.base_documents()) == []


def test_retitle_is_in_the_compile_tool_face_with_a_typed_argument_schema():
    from pneuma_knowledge_core.compile.runner import build_compile_tool_face

    draft = draft_with(a_page())
    tools = {tool.name: tool for tool in build_compile_tool_face(draft)}
    assert "retitle" in tools
    assert set(tools["retitle"].args_schema.model_fields) == {"path", "title"}
    assert "Atlas of currents" in tools["retitle"].func(
        path="memory/topics/atlas.md", title="Atlas of currents"
    )


# ─────────────────────────────── a name that says where the page sits, not what it is

#: A contract that declares the family roles, so the gate can read them (shape/families.py).
PROJECT_TEMPLATES = [
    "projects/{slug}/overview.md",
    "projects/{slug}/evolution.md",
    "projects/{slug}/features/{slug}.md",
    "memory/topics/{slug}.md",
]


def project_draft(*docs: CanonicalDocument) -> PatchDraft:
    return PatchDraft.from_canonical(list(docs), PROJECT_TEMPLATES)


def a_project(hub_title="Aurora", chronology_title="Aurora timeline"):
    return (
        canonical(
            "projects/aurora/overview.md",
            f"# {hub_title}\n\n## What\n\nIt exists. [cite: s01 ¶0-1] <!-- c:a1111111 -->",
            title=hub_title,
        ),
        canonical(
            "projects/aurora/evolution.md",
            f"# {chronology_title}\n\n## 2026-01-04\n\nIt began. <!-- c:a2222222 -->",
            title=chronology_title,
        ),
    )


def test_the_gate_refuses_a_title_that_names_the_family_role_instead_of_the_subject():
    from pneuma_knowledge_core.compile.gate import check_title_degenerate

    hub, chronology = a_project()
    draft = project_draft(hub, chronology)
    assert (
        check_title_degenerate(
            draft.documents(), draft.base_documents(), path_templates=PROJECT_TEMPLATES
        )
        == []
    )
    draft.retitle("projects/aurora/evolution.md", "Evolution")
    violations = check_title_degenerate(
        draft.documents(), draft.base_documents(), path_templates=PROJECT_TEMPLATES
    )
    assert [v.kind for v in violations] == ["title_degenerate"]
    assert "Evolution" in violations[0].detail and "retitle" in violations[0].detail


def test_the_gate_refuses_the_project_slug_on_a_page_that_is_not_the_hub():
    from pneuma_knowledge_core.compile.gate import check_title_degenerate

    hub, chronology = a_project()
    draft = project_draft(hub, chronology)
    draft.retitle("projects/aurora/evolution.md", "aurora")
    assert [
        v.kind
        for v in check_title_degenerate(
            draft.documents(), draft.base_documents(), path_templates=PROJECT_TEMPLATES
        )
    ] == ["title_degenerate"]
    # …and the hub itself IS the project, so carrying that name there is right.
    draft.retitle("projects/aurora/overview.md", "Aurora")
    assert not [
        v
        for v in check_title_degenerate(
            draft.documents(), draft.base_documents(), path_templates=PROJECT_TEMPLATES
        )
        if v.path == "projects/aurora/overview.md"
    ]


def test_a_page_with_no_heading_at_all_is_not_refused_by_the_gate():
    """The check lists untitled pages (`id.title_degenerate`) and `retitle` repairs them.
    Refusing them here would abort every round whose model opens a body on a `## ` section,
    which is how pages have been created for as long as the tool face has existed."""
    from pneuma_knowledge_core.compile.gate import check_title_degenerate

    draft = project_draft()
    draft.create_document(
        "memory/topics/rift.md",
        {"type": "topic", "slug": "rift"},
        "## Facts\n\nIt exists. [cite: s01 ¶0-1]",
    )
    assert (
        check_title_degenerate(
            draft.documents(), draft.base_documents(), path_templates=PROJECT_TEMPLATES
        )
        == []
    )


def test_the_gate_refuses_a_chronology_wearing_its_hubs_name():
    from pneuma_knowledge_core.compile.gate import check_title_shared_with_hub

    hub, chronology = a_project()
    draft = project_draft(hub, chronology)
    assert (
        check_title_shared_with_hub(
            draft.documents(), draft.base_documents(), path_templates=PROJECT_TEMPLATES
        )
        == []
    )
    draft.retitle("projects/aurora/evolution.md", "Aurora")
    violations = check_title_shared_with_hub(
        draft.documents(), draft.base_documents(), path_templates=PROJECT_TEMPLATES
    )
    assert [v.kind for v in violations] == ["title_shared_with_hub"]
    assert violations[0].path == "projects/aurora/evolution.md"
    assert "projects/aurora/overview.md" in violations[0].detail


# ──────────────────────────────────────────── the overview head against its own ledger


def _page_with_overview(definition: str, claim_text: str) -> CanonicalDocument:
    return canonical(
        "memory/topics/atlas.md",
        "# Atlas\n\n"
        "<!-- overview -->\n\n"
        "<!-- overview:definition -->\n### Definition\n\n"
        f"{definition} <!-- c:a9999999 -->\n\n"
        "<!-- /overview -->\n\n"
        f"## Facts\n\n{claim_text} [cite: s01 ¶0-1] <!-- c:a1111111 -->",
        title="Atlas",
    )


def test_the_gate_refuses_an_overview_block_that_repeats_a_ledger_claim():
    from pneuma_knowledge_core.compile.documents import Overview
    from pneuma_knowledge_core.compile.gate import check_overview_restates

    page = _page_with_overview("What the currents do to a harbour.", "A chart of the currents.")
    draft = draft_with(page)
    assert check_overview_restates(draft.documents(), draft.base_bodies()) == []
    draft.mark_read("memory/topics/atlas.md")
    draft.rewrite_overview(
        "memory/topics/atlas.md", Overview(definition="A chart of the currents. c:a1111111")
    )
    violations = check_overview_restates(draft.documents(), draft.base_bodies())
    assert [v.kind for v in violations] == ["overview_restates"]
    assert "definition" in violations[0].detail


def test_an_overview_block_that_reads_the_ledger_rather_than_repeating_it_passes():
    from pneuma_knowledge_core.compile.documents import Overview
    from pneuma_knowledge_core.compile.gate import check_overview_restates

    page = _page_with_overview("An older reading.", "A chart of the currents.")
    draft = draft_with(page)
    draft.mark_read("memory/topics/atlas.md")
    draft.rewrite_overview(
        "memory/topics/atlas.md",
        Overview(definition="What the currents do to a harbour. c:a1111111"),
    )
    assert check_overview_restates(draft.documents(), draft.base_bodies()) == []


def test_the_gate_refuses_a_definition_made_of_references_alone():
    from pneuma_knowledge_core.compile.documents import Overview
    from pneuma_knowledge_core.compile.gate import check_definition_empty

    page = _page_with_overview("A real sentence.", "A chart of the currents.")
    draft = draft_with(page)
    assert check_definition_empty(draft.documents(), draft.base_bodies()) == []
    draft.mark_read("memory/topics/atlas.md")
    draft.rewrite_overview("memory/topics/atlas.md", Overview(definition="c:a1111111"))
    violations = check_definition_empty(draft.documents(), draft.base_bodies())
    assert [v.kind for v in violations] == ["definition_empty"]


# ───────────────────── a hook judges what the round CHANGED, never what it inherited


def test_a_legacy_overview_fault_does_not_refuse_a_retitle_on_the_same_page():
    """The failure a real review round hit: three pages carried an overview block repeating
    one of their own claims, and the Steward's `retitle` — which does not touch the head —
    came back refused for it. A page with one legacy fault would then be unrepairable, one
    write at a time, including by the write that repairs it."""
    from pneuma_knowledge_core.compile.gate import post_write_violations, run_gate

    page = _page_with_overview("A chart of the currents.", "A chart of the currents.")
    draft = draft_with(page)
    before = run_gate(draft, [])
    draft.retitle("memory/topics/atlas.md", "Atlas of currents")
    assert (
        post_write_violations(draft, [], "memory/topics/atlas.md", baseline=before) == []
    )


def test_a_legacy_overview_fault_does_not_refuse_a_reorder_of_the_same_pages_sections():
    from pneuma_knowledge_core.compile.gate import post_write_violations, run_gate

    page = canonical(
        "projects/aurora/evolution.md",
        "# Aurora timeline\n\n"
        "<!-- overview -->\n\n"
        "<!-- overview:definition -->\n### Definition\n\n"
        "It began. <!-- c:a9999999 -->\n\n"
        "<!-- /overview -->\n\n"
        "## 2026-03-04\n\nIt shipped. [cite: s01 ¶1-2] <!-- c:a2222222 -->\n\n"
        "## 2026-01-04\n\nIt began. [cite: s01 ¶0-1] <!-- c:a1111111 -->",
        title="Aurora timeline",
    )
    draft = project_draft(page)
    before = run_gate(draft, [])
    assert any(v.kind == "overview_restates" for v in before) is False
    draft.reorder_chronology("projects/aurora/evolution.md")
    assert (
        post_write_violations(draft, [], "projects/aurora/evolution.md", baseline=before)
        == []
    )


def test_a_new_page_answers_for_the_overview_it_is_created_with():
    """A page this round created inherited nothing, so every byte of it is this round's."""
    from pneuma_knowledge_core.compile.documents import Overview
    from pneuma_knowledge_core.compile.gate import check_overview_restates

    draft = draft_with()
    draft.create_document(
        "memory/topics/rift.md",
        {"type": "topic", "slug": "rift"},
        "# Rift\n\n## Facts\n\nA tear in the shelf. [cite: s01 ¶0-1]",
    )
    anchor = next(
        line.split("c:")[1].split(" ")[0].rstrip("->").strip()
        for line in draft.read("memory/topics/rift.md").body.split("\n")
        if "c:" in line and "A tear" in line
    )
    draft.rewrite_overview(
        "memory/topics/rift.md", Overview(definition=f"A tear in the shelf. c:{anchor}")
    )
    violations = check_overview_restates(draft.documents(), draft.base_bodies())
    assert [v.kind for v in violations] == ["overview_restates"]


def test_an_inherited_degenerate_title_does_not_refuse_an_append_to_the_same_page():
    """The same rule over the title hooks: a page that arrived under a family role word keeps
    it until somebody retitles it, and a round that appends one claim is not the round that
    named it. The CHECK lists those pages; the review round repairs them with retitle."""
    from pneuma_knowledge_core.compile.gate import (
        check_title_degenerate,
        check_title_shared_with_hub,
        check_title_siblings,
    )

    hub, _chronology = a_project()
    chronology = canonical(
        "projects/aurora/evolution.md",
        "# Evolution\n\n## 2026-01-04\n\nIt began. <!-- c:a2222222 -->",
        title="Evolution",
    )
    twin = canonical(
        "projects/aurora/features/screen.md",
        "# Aurora\n\n## What\n\nIt exists. <!-- c:a3333333 -->",
        title="Aurora",
    )
    draft = project_draft(hub, chronology, twin)
    draft.append_block("projects/aurora/evolution.md", "2026-02-04", "It grew. [cite: s01 ¶1-2]")
    documents, base = draft.documents(), draft.base_documents()
    assert (
        check_title_degenerate(documents, base, path_templates=PROJECT_TEMPLATES) == []
    )
    assert (
        check_title_shared_with_hub(documents, base, path_templates=PROJECT_TEMPLATES)
        == []
    )
    assert check_title_siblings(documents, base) == []
    # …and the moment the round DOES name the page, the hook has its say. (A retitle to the
    # name the page already had changes nothing, so it is nothing the round wrote.)
    draft.retitle("projects/aurora/evolution.md", "项目演进")
    assert [
        v.kind
        for v in check_title_degenerate(
            draft.documents(), base, path_templates=PROJECT_TEMPLATES
        )
    ] == ["title_degenerate"]


def test_the_four_new_kinds_are_in_the_enumerable_violation_catalog():
    kinds = {kind for kind, _ in VIOLATION_KINDS}
    assert {
        "title_degenerate",
        "title_shared_with_hub",
        "overview_restates",
        "definition_empty",
    } <= kinds
    catalog = dict(violation_catalog())
    for kind in (
        "title_degenerate",
        "title_shared_with_hub",
        "overview_restates",
        "definition_empty",
    ):
        assert catalog[kind] and all(text.strip() for text in catalog[kind])


# ─────────────────────────────────────────────────── a chronology keeps its own order


def a_chronology(*dates: str) -> CanonicalDocument:
    sections = "\n\n".join(
        f"## {date}\n\nSomething happened. [cite: s01 ¶0-1] <!-- c:a{index}111111 -->"
        for index, date in enumerate(dates, start=1)
    )
    return canonical(
        "projects/aurora/evolution.md",
        f"# Aurora timeline\n\n{sections}",
        title="Aurora timeline",
    )


def test_an_append_under_a_date_the_page_already_has_joins_that_section():
    draft = project_draft(a_chronology("2026-01-04", "2026-03-04"))
    doc = draft.append_block(
        "projects/aurora/evolution.md", "2026-01-04", "And then this. [cite: s01 ¶2-3]"
    )
    lines = [line for line in doc.body.split("\n") if line.startswith("## ")]
    assert lines == ["## 2026-01-04", "## 2026-03-04"]  # no second section of that date
    first, second = doc.body.index("And then this."), doc.body.index("## 2026-03-04")
    assert first < second


def test_an_append_of_an_older_date_opens_its_section_before_the_newer_one():
    draft = project_draft(a_chronology("2026-01-04", "2026-03-04"))
    doc = draft.append_block(
        "projects/aurora/evolution.md", "2026-02-04", "The middle. [cite: s01 ¶2-3]"
    )
    assert [line for line in doc.body.split("\n") if line.startswith("## ")] == [
        "## 2026-01-04",
        "## 2026-02-04",
        "## 2026-03-04",
    ]
    doc = draft.append_block(
        "projects/aurora/evolution.md", "2025-12-01", "Before all of it. [cite: s01 ¶3-4]"
    )
    assert [line for line in doc.body.split("\n") if line.startswith("## ")] == [
        "## 2025-12-01",
        "## 2026-01-04",
        "## 2026-02-04",
        "## 2026-03-04",
    ]
    # The anchors that stood are untouched: placement moves nothing that was written.
    assert "c:a1111111" in doc.body and "c:a2111111" in doc.body


def test_a_newer_date_still_lands_at_the_end_and_other_pages_are_unchanged():
    draft = project_draft(
        a_chronology("2026-01-04", "2026-03-04"),
        canonical(
            "memory/topics/atlas.md",
            "# Atlas\n\n## Facts\n\nIt exists. [cite: s01 ¶0-1] <!-- c:a7777777 -->",
            title="Atlas",
        ),
    )
    doc = draft.append_block(
        "projects/aurora/evolution.md", "2026-05-04", "Later. [cite: s01 ¶2-3]"
    )
    assert doc.body.rstrip().split("\n## ")[-1].startswith("2026-05-04")
    # A page that is not a chronology keeps the ordinary end-of-section append, and a
    # heading that is not a date is an ordinary section wherever it sits.
    other = draft.append_block(
        "memory/topics/atlas.md", "2026-01-01", "A dated note. [cite: s01 ¶1-2]"
    )
    assert other.body.index("## Facts") < other.body.index("## 2026-01-01")


def test_reorder_chronology_puts_the_sections_in_order_and_conserves_every_line():
    draft = project_draft(a_chronology("2026-03-04", "2026-01-04", "2026-02-04"))
    before = draft.read("projects/aurora/evolution.md").body
    doc = draft.reorder_chronology("projects/aurora/evolution.md")
    assert [line for line in doc.body.split("\n") if line.startswith("## ")] == [
        "## 2026-01-04",
        "## 2026-02-04",
        "## 2026-03-04",
    ]
    # A permutation of whole sections: the same lines, and every anchor still on its claim.
    assert sorted(before.split("\n")) == sorted(doc.body.split("\n"))
    assert doc.body.split("\n")[0] == "# Aurora timeline"
    for anchor in ("c:a1111111", "c:a2111111", "c:a3111111"):
        assert anchor in doc.body


def test_reorder_chronology_is_idempotent_and_refuses_a_page_with_nothing_to_order():
    draft = project_draft(a_chronology("2026-01-04", "2026-02-04"))
    once = draft.reorder_chronology("projects/aurora/evolution.md").body
    twice = draft.reorder_chronology("projects/aurora/evolution.md").body
    assert once == twice
    flat = project_draft(
        canonical(
            "memory/topics/atlas.md",
            "# Atlas\n\n## Facts\n\nIt exists. [cite: s01 ¶0-1] <!-- c:a1111111 -->",
            title="Atlas",
        )
    )
    with pytest.raises(AnchorToolError) as excinfo:
        flat.reorder_chronology("memory/topics/atlas.md")
    assert "memory/topics/atlas.md" in str(excinfo.value)


def test_reorder_chronology_refuses_a_closed_volume_an_archived_page_and_a_record():
    volume = canonical(
        "projects/aurora/evolution/a02.md",
        "## 2026-01-04\n\nOld. <!-- c:a2222222 -->\n\n## 2025-01-04\n\nOlder. <!-- c:a3333333 -->",
        archived_from="projects/aurora/evolution.md",
    )
    archived = canonical(
        "archive/projects/aurora/evolution.md",
        "# Old\n\n## 2026-01-04\n\nx <!-- c:a4444444 -->\n\n## 2025-01-04\n\ny <!-- c:a5555555 -->",
    )
    record = canonical(
        "memory/topics/gone.md",
        "# Gone\n\n## 2026-01-04\n\nx <!-- c:a6666666 -->\n\n## 2025-01-04\n\ny <!-- c:a7777777 -->",
        type="archived",
        archive_of="archive/memory/topics/gone.md",
    )
    draft = project_draft(a_chronology("2026-01-04", "2026-02-04"), volume, archived, record)
    for path in (volume.path, archived.path, record.path):
        with pytest.raises(AnchorToolError):
            draft.reorder_chronology(path)


def test_reorder_chronology_is_in_the_compile_tool_face_with_a_typed_argument_schema():
    from pneuma_knowledge_core.compile.runner import build_compile_tool_face

    draft = project_draft(a_chronology("2026-03-04", "2026-01-04"))
    tools = {tool.name: tool for tool in build_compile_tool_face(draft)}
    assert "reorder_chronology" in tools
    assert set(tools["reorder_chronology"].args_schema.model_fields) == {"path"}
    answer = tools["reorder_chronology"].func(path="projects/aurora/evolution.md")
    assert "2026-01-04" in answer and "2026-03-04" in answer
