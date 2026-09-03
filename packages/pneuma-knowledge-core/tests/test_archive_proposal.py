"""The archive PROPOSAL planner (docs/design/archive.md §5).

The Owner names a seed; the framework computes what follows mechanically from the
citations already in the library and shows the whole set with a reason per item. Nothing
here executes anything — these tests are about the closure and nothing else: which items
appear, which are selected, and why.
"""

from __future__ import annotations

import hashlib

from pneuma_knowledge_core.archive import (
    NOTE_ALREADY_ARCHIVED,
    NOTE_ALREADY_LIVE,
    NOTE_FULLY_DEPENDENT,
    NOTE_ORPHANED,
    NOTE_PARTIALLY_DEPENDENT,
    NOTE_RESTORED_WITH_PAGE,
    NOTE_SEED,
    NOTE_STILL_CITED,
    NOTE_UNKNOWN,
    plan_archive,
)
from pneuma_knowledge_core.compile.documents import (
    Overview,
    render_overview,
    set_overview_region,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId

TITLES = {
    "src-a": "The Aurora kickoff",
    "src-b": "The shared vendor review",
    "src-c": "The Atlas standup",
    "src-d": "The Aurora retro",
}


def _anchor(path: str, index: int) -> str:
    return hashlib.sha256(f"{path}:{index}".encode()).hexdigest()[:8]


def _doc(path: str, *claims: tuple[str, ...]) -> CanonicalDocument:
    """A canonical document whose i-th ledger claim cites `claims[i]`'s source ids."""
    stem = path.rsplit("/", 1)[-1].removesuffix(".md")
    lines = [f"# {stem.replace('-', ' ').title()}", ""]
    for i, sources in enumerate(claims):
        cites = " ".join(f"[cite: {sid} ¶0]" for sid in sources)
        lines.append(f"- claim {i} of {stem}. {cites} <!-- c:{_anchor(path, i)} -->")
    return CanonicalDocument(
        doc_id=DocumentId(hashlib.sha256(path.encode()).hexdigest()[:12]),
        path=path,
        frontmatter={"type": "topic", "slug": stem},
        body="\n".join(lines),
    )


def _with_overview(doc: CanonicalDocument, definition: str) -> CanonicalDocument:
    region = render_overview(Overview(definition=definition), document_path=doc.path)
    return doc.model_copy(update={"body": set_overview_region(doc.body, region)})


def _item(proposal, kind: str, ref: str):
    return next(i for i in proposal.items if i.kind == kind and i.ref == ref)


def _refs(proposal, kind: str) -> list[str]:
    return [i.ref for i in proposal.items if i.kind == kind]


# ----------------------------------------------------------------- from a document


def test_a_document_seed_selects_the_sources_only_it_cited():
    """The first closure rule. `src-a` is Aurora's alone, so archiving Aurora retires it;
    `src-b` is the vendor review Atlas also cites, so it is LISTED with the document that
    kept it and is not selected — the Owner sees the whole set, including what stays."""
    docs = [
        _doc("work/aurora.md", ("src-a",), ("src-b",)),
        _doc("work/atlas.md", ("src-b",), ("src-c",)),
    ]
    proposal = plan_archive(
        "archive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=(),
        seed_documents=["work/aurora.md"],
    )
    assert proposal.selected_documents() == ("work/aurora.md",)
    assert proposal.selected_sources() == ("src-a",)

    seed = _item(proposal, "document", "work/aurora.md")
    assert (seed.role, seed.reason.note, seed.title) == ("seed", NOTE_SEED, "Aurora")

    orphan = _item(proposal, "source", "src-a")
    assert (orphan.role, orphan.selected, orphan.reason.note) == (
        "cascade",
        True,
        NOTE_ORPHANED,
    )
    assert orphan.title == TITLES["src-a"]

    kept = _item(proposal, "source", "src-b")
    assert (kept.selected, kept.reason.note) == (False, NOTE_STILL_CITED)
    assert kept.reason.cited_by_live == ("work/atlas.md",)
    # `src-c` is nothing to do with Aurora and never enters the proposal at all.
    assert "src-c" not in _refs(proposal, "source")


def test_a_documents_rollover_volumes_ride_with_it_and_are_never_items():
    """A volume is the document's own frozen history, so it moves as part of the item —
    and the sources only the volume cites are retired with it."""
    active = _doc("work/aurora.md", ("src-a",))
    volume = _doc("work/aurora/a01.md", ("src-d",))
    volume = volume.model_copy(
        update={"frontmatter": {**volume.frontmatter, "archived_from": active.path}}
    )
    proposal = plan_archive(
        "archive",
        documents=[active, volume],
        source_titles=TITLES,
        archived_sources=(),
        seed_documents=["work/aurora.md"],
    )
    assert proposal.selected_documents() == ("work/aurora.md",)
    assert _item(proposal, "document", "work/aurora.md").volumes == ("work/aurora/a01.md",)
    assert "work/aurora/a01.md" not in _refs(proposal, "document")
    # the volume's own source is orphaned by the same move
    assert proposal.selected_sources() == ("src-a", "src-d")


# ------------------------------------------------------------------- from a source


def test_a_source_seed_selects_a_fully_dependent_document_and_lists_a_partial_one():
    """The second rule and its ratio. Everything `work/vendor.md` says rests on the
    seeded source, so it goes; `work/atlas.md` is half about something else, so it is
    listed with `1/2` and left for the Owner to decide."""
    docs = [
        _doc("work/vendor.md", ("src-b",), ("src-b",)),
        _doc("work/atlas.md", ("src-b",), ("src-c",)),
    ]
    proposal = plan_archive(
        "archive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=(),
        seed_sources=["src-b"],
    )
    assert proposal.selected_sources() == ("src-b",)
    assert proposal.selected_documents() == ("work/vendor.md",)

    whole = _item(proposal, "document", "work/vendor.md")
    assert (whole.role, whole.reason.note, whole.reason.dependence) == (
        "cascade",
        NOTE_FULLY_DEPENDENT,
        (2, 2),
    )
    partial = _item(proposal, "document", "work/atlas.md")
    assert (partial.selected, partial.reason.note, partial.reason.dependence) == (
        False,
        NOTE_PARTIALLY_DEPENDENT,
        (1, 2),
    )


def test_the_overview_is_excluded_from_the_dependence_denominator():
    """The head is a reading of the ledger, not a claim of its own: a document whose two
    LEDGER claims both rest on the seeded source is fully dependent even though its
    overview cites a source too."""
    doc = _with_overview(
        _doc("work/vendor.md", ("src-b",), ("src-b",)),
        "The vendor relationship. [cite: src-c ¶0]",
    )
    proposal = plan_archive(
        "archive",
        documents=[doc],
        source_titles=TITLES,
        archived_sources=(),
        seed_sources=["src-b"],
    )
    item = _item(proposal, "document", "work/vendor.md")
    assert (item.selected, item.reason.dependence) == (True, (2, 2))
    # …and the head's own source is still SEEN as a source this document cites: it is a
    # candidate like any other, and orphaned here because nothing else cites it.
    assert _item(proposal, "source", "src-c").reason.note == NOTE_ORPHANED


def test_the_closure_runs_to_a_fixed_point_over_the_selected_set():
    """`src-d` is reachable only THROUGH a document that the first pass selects.

    Pass one: the seeded `src-b` pulls in `work/vendor.md` (2/2). Pass two: that document's
    other source, which nothing else cites, is now orphaned and goes too. A single pass
    over the seeds would have left it indexed and answering.
    """
    docs = [
        _doc("work/vendor.md", ("src-b",), ("src-b", "src-d")),
        _doc("work/atlas.md", ("src-c",)),
    ]
    proposal = plan_archive(
        "archive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=(),
        seed_sources=["src-b"],
    )
    assert proposal.selected_documents() == ("work/vendor.md",)
    assert proposal.selected_sources() == ("src-b", "src-d")
    assert _item(proposal, "source", "src-d").reason.note == NOTE_ORPHANED


def test_a_document_is_selected_only_once_every_one_of_its_sources_is():
    """The same document, judged against one seed source and then against both."""
    docs = [_doc("work/pair.md", ("src-a",), ("src-b",))]
    one = plan_archive(
        "archive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=(),
        seed_sources=["src-a"],
    )
    assert one.selected_documents() == ()
    assert _item(one, "document", "work/pair.md").reason.dependence == (1, 2)

    both = plan_archive(
        "archive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=(),
        seed_sources=["src-a", "src-b"],
    )
    assert both.selected_documents() == ("work/pair.md",)
    assert _item(both, "document", "work/pair.md").reason.dependence == (2, 2)


# --------------------------------------------------------------------- unarchive


def test_unarchive_mirrors_the_two_rules():
    """A document coming back brings the archived sources it cites with it, and a second
    archived document comes back only when every source it cites would then be live."""
    docs = [
        _doc("archive/work/aurora.md", ("src-a",), ("src-a",)),
        _doc("archive/work/echo.md", ("src-a",), ("src-a",)),
        _doc("archive/work/mixed.md", ("src-a",), ("src-d",)),
    ]
    proposal = plan_archive(
        "unarchive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=["src-a", "src-d"],
        seed_documents=["archive/work/aurora.md"],
    )
    assert proposal.selected_sources() == ("src-a",)
    source = _item(proposal, "source", "src-a")
    assert (source.selected, source.reason.note) == (True, NOTE_RESTORED_WITH_PAGE)
    # The pages that bring it back are ARCHIVED pages, and the reason says so in the field
    # that means that. `cited_by_live` answers "which live documents would lose this source"
    # and no live document is involved here, so it stays empty rather than being filled with
    # `archive/…` paths that would read as live ones.
    assert source.reason.cited_by_archived == (
        "archive/work/aurora.md",
        "archive/work/echo.md",
    )
    assert source.reason.cited_by_live == ()

    # echo rests on nothing but the returning source; mixed still leans on one that stays.
    assert proposal.selected_documents() == (
        "archive/work/aurora.md",
        "archive/work/echo.md",
    )
    assert _item(proposal, "document", "archive/work/echo.md").reason.dependence == (2, 2)
    mixed = _item(proposal, "document", "archive/work/mixed.md")
    assert (mixed.selected, mixed.reason.note, mixed.reason.dependence) == (
        False,
        NOTE_PARTIALLY_DEPENDENT,
        (1, 2),
    )


def test_a_returning_source_names_the_archived_pages_and_no_live_one():
    """The mirror direction says something DIFFERENT, so it gets its own code and its own
    field. A live page may well cite an archived source — archiving a source does not touch
    the claims that rest on it — but it is not why the source comes back, and naming it
    under `cited_by_live` would answer the archive direction's question in the unarchive
    direction's proposal."""
    docs = [
        _doc("archive/work/aurora.md", ("src-a",)),
        _doc("work/atlas.md", ("src-a",), ("src-c",)),  # live, and cites the same source
    ]
    proposal = plan_archive(
        "unarchive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=["src-a"],
        seed_documents=["archive/work/aurora.md"],
    )
    source = _item(proposal, "source", "src-a")
    assert (source.selected, source.reason.note) == (True, NOTE_RESTORED_WITH_PAGE)
    assert source.reason.cited_by_archived == ("archive/work/aurora.md",)
    assert source.reason.cited_by_live == ()
    # The live page is not in the proposal at all: nothing about it moves, and the archive
    # direction's cascade rule (a document that depends on what is leaving) has no mirror
    # here — a source coming back takes nothing away from anybody.
    assert _refs(proposal, "document") == ["archive/work/aurora.md"]


def test_the_two_reason_fields_never_name_a_path_from_the_other_side():
    """One property over both directions, because this is the bug the field split fixes:
    whatever `cited_by_live` names must be readable as a live page, and whatever
    `cited_by_archived` names must be readable as an archived one."""
    docs = [
        _doc("work/aurora.md", ("src-a",), ("src-b",)),
        _doc("work/atlas.md", ("src-b",)),
        _doc("archive/work/echo.md", ("src-d",)),
    ]
    archiving = plan_archive(
        "archive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=["src-d"],
        seed_documents=["work/aurora.md"],
    )
    kept = _item(archiving, "source", "src-b")
    assert (kept.selected, kept.reason.note) == (False, NOTE_STILL_CITED)
    assert kept.reason.cited_by_live == ("work/atlas.md",)
    assert kept.reason.cited_by_archived == ()

    unarchiving = plan_archive(
        "unarchive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=["src-d"],
        seed_documents=["archive/work/echo.md"],
    )
    for proposal in (archiving, unarchiving):
        for item in proposal.items:
            assert all(
                not path.startswith("archive/") for path in item.reason.cited_by_live
            ), item
            assert all(
                path.startswith("archive/") for path in item.reason.cited_by_archived
            ), item
    # …and `still_cited` belongs to one direction only now: the unarchive side has its own.
    assert NOTE_STILL_CITED not in {i.reason.note for i in unarchiving.items}
    assert NOTE_RESTORED_WITH_PAGE not in {i.reason.note for i in archiving.items}


def test_a_seed_already_in_the_target_state_is_listed_and_not_selected():
    """A complete answer about the seeds: the Owner asked, and the reason says why nothing
    moves — not silence, and not an error.

    These two codes look unused from the outside because a console that reads the archive
    listing and the live glance never HAS a seed in the target state to send. They are the
    answer for the caller that does — a Steward acting on a stale reading, a re-sent request,
    an Owner naming a page twice in two spellings — and the assertions below are where they
    are produced."""
    docs = [_doc("archive/work/aurora.md", ("src-a",))]
    archiving = plan_archive(
        "archive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=["src-a"],
        seed_documents=["archive/work/aurora.md"],
        seed_sources=["src-a"],
    )
    assert archiving.selected_documents() == () and archiving.selected_sources() == ()
    archived_doc = _item(archiving, "document", "archive/work/aurora.md")
    assert archived_doc.reason.note == NOTE_ALREADY_ARCHIVED
    assert (archived_doc.role, archived_doc.selected) == ("seed", False)
    archived_src = _item(archiving, "source", "src-a")
    assert archived_src.reason.note == NOTE_ALREADY_ARCHIVED
    assert (archived_src.role, archived_src.selected) == ("seed", False)
    # Listed with the reason and nothing else: an item in the target state cascades to
    # nothing, because nothing about it is moving.
    assert len(archiving.items) == 2

    live = [_doc("work/aurora.md", ("src-a",))]
    unarchiving = plan_archive(
        "unarchive",
        documents=live,
        source_titles=TITLES,
        archived_sources=(),
        seed_documents=["work/aurora.md"],
        seed_sources=["src-a"],
    )
    assert unarchiving.selected_documents() == () and unarchiving.selected_sources() == ()
    live_doc = _item(unarchiving, "document", "work/aurora.md")
    assert live_doc.reason.note == NOTE_ALREADY_LIVE
    assert (live_doc.role, live_doc.selected) == ("seed", False)
    live_src = _item(unarchiving, "source", "src-a")
    assert live_src.reason.note == NOTE_ALREADY_LIVE
    assert (live_src.role, live_src.selected) == ("seed", False)
    assert len(unarchiving.items) == 2


def test_either_spelling_of_a_moved_path_names_the_same_document():
    """The Owner reads a live path off the glance and an archived one off the archive
    listing; a move renames the document, so both spellings resolve to the one subject."""
    docs = [_doc("archive/work/aurora.md", ("src-a",))]
    proposal = plan_archive(
        "unarchive",
        documents=docs,
        source_titles=TITLES,
        archived_sources=["src-a"],
        seed_documents=["work/aurora.md"],
    )
    assert proposal.selected_documents() == ("archive/work/aurora.md",)


# ------------------------------------------------------------- unknown, and stability


def test_an_unknown_seed_is_reported_rather_than_dropped():
    """A typo must not silently shrink the plan the Owner is about to confirm."""
    proposal = plan_archive(
        "archive",
        documents=[_doc("work/aurora.md", ("src-a",))],
        source_titles=TITLES,
        archived_sources=(),
        seed_documents=["work/nope.md"],
        seed_sources=["src-nope"],
    )
    assert proposal.selected_documents() == () and proposal.selected_sources() == ()
    assert _item(proposal, "document", "work/nope.md").reason.note == NOTE_UNKNOWN
    assert _item(proposal, "source", "src-nope").reason.note == NOTE_UNKNOWN


def test_the_same_tree_and_the_same_seeds_produce_the_same_proposal():
    """Deterministic to the item: seeds in the order given, then the cascade by (kind, ref).
    The proposal is confirmed against an exact library state, so two renders of one plan
    that differ are two plans."""
    docs = [
        _doc("work/vendor.md", ("src-b",), ("src-b", "src-d")),
        _doc("work/atlas.md", ("src-b",), ("src-c",)),
        _doc("work/aurora.md", ("src-a",)),
    ]
    kwargs = dict(
        documents=docs,
        source_titles=TITLES,
        archived_sources=(),
        seed_documents=["work/aurora.md"],
        seed_sources=["src-b"],
    )
    first = plan_archive("archive", **kwargs)
    second = plan_archive("archive", **{**kwargs, "documents": list(reversed(docs))})
    assert first == second
    # seeds first, in the order the Owner gave them; then the cascade sorted by (kind, ref)
    assert [(i.kind, i.ref) for i in first.items[:2]] == [
        ("document", "work/aurora.md"),
        ("source", "src-b"),
    ]
    cascade = [(i.kind, i.ref) for i in first.items[2:]]
    assert cascade == sorted(cascade)


def test_duplicate_archive_seeds_are_idempotent():
    """Naming a subject twice is naming it once — including under both of its spellings.

    A proposal is a set the Owner confirms and a job then executes, so a repeated seed that
    survived into the items would show the same page twice with the same reason and, through
    `selected_documents()`, hand the executor the same move twice. The identity is the
    RESOLVED subject, not the string: a console that sends the live path it read off the
    glance and the archived path it read off `GET /archive` has named one document.
    """
    docs = [
        _doc("archive/work/aurora.md", ("src-a",)),
        _doc("work/atlas.md", ("src-c",)),
    ]
    kwargs = dict(
        documents=docs,
        source_titles=TITLES,
        archived_sources=["src-a"],
    )
    once = plan_archive(
        "unarchive",
        **kwargs,
        seed_documents=["archive/work/aurora.md"],
        seed_sources=["src-a"],
    )
    twice = plan_archive(
        "unarchive",
        **kwargs,
        # the same page under both spellings, and the same source three times over
        seed_documents=[
            "archive/work/aurora.md",
            "work/aurora.md",
            "archive/work/aurora.md",
        ],
        seed_sources=["src-a", "src-a", "src-a"],
    )

    assert twice == once, "a seed named twice is the same proposal, item for item"
    assert twice.seeds_documents == ("archive/work/aurora.md",)
    assert twice.seeds_sources == ("src-a",)
    assert _refs(twice, "document") == ["archive/work/aurora.md"]
    assert twice.selected_documents() == ("archive/work/aurora.md",)
    assert twice.selected_sources() == ("src-a",)


def test_a_repeated_unknown_seed_is_reported_once():
    """The dedup is over subjects, and a ref that resolves to nothing is its own subject —
    so two DIFFERENT typos still get two rows, and one typo twice gets one."""
    proposal = plan_archive(
        "archive",
        documents=[_doc("work/aurora.md", ("src-a",))],
        source_titles=TITLES,
        archived_sources=(),
        seed_documents=["work/nope.md", "work/nope.md", "work/other-nope.md"],
        seed_sources=["src-nope", "src-nope"],
    )
    assert _refs(proposal, "document") == ["work/nope.md", "work/other-nope.md"]
    assert [i.ref for i in proposal.items if i.kind == "source"] == ["src-nope"]
