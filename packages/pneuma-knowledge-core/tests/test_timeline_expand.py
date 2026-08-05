"""Subject-timeline expansion (`fast_recall(timeline_expand=N)`): the temporal lever.

What is locked here is the flag's mechanics, not any wording:

- OFF by default, and the off path is byte-for-byte the lane without the section — same
  Human payload, empty telemetry;
- sibling claims render in document (projection) order, whole document when it fits the cap;
- over the cap, the kept window centres on the retrieved hits and still reads in document
  order;
- the document fan-out is capped and ranked by hit count, and total added claims are
  mechanically ≤ per_doc × doc_cap;
- a hit whose path is not in the supplied canonical set never expands (the canonical set is
  the authority, the hit's path is derived data).
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.fast import (
    RetrievedClaim,
    build_subject_timelines,
    fast_recall,
    recall_human,
    render_subject_timelines,
    select_timeline_claims,
    subject_timeline_paths,
    timeline_subject,
)
from pneuma_knowledge_core.recall.projection import project_document_claims

from test_fast_recall import ClaimStub, FakeClaimIndex, FakeEmbeddings

_AS_OF = datetime(2026, 7, 20, 12, 0, 0)
_USER = UserId("u-timeline")


def _anchor(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:8]


def _doc(path: str, entries: int, slug: str) -> CanonicalDocument:
    """A subject document whose N dated claims sit in chronological body order."""
    lines = [f"# {slug}", ""]
    for i in range(entries):
        anchor = _anchor(f"{slug}-{i}")
        lines.append(
            f"- On 2025-{(i % 12) + 1:02d}-{(i % 27) + 1:02d} {slug} did thing {i}. "
            f"[cite: {'a' * 32} ¶{i}-{i}] <!-- c:{anchor} -->"
        )
    return CanonicalDocument(
        doc_id=DocumentId("d" * 12), path=path, frontmatter={}, body="\n".join(lines)
    )


def _hit(doc: CanonicalDocument, index: int, slug: str) -> RetrievedClaim:
    return RetrievedClaim(
        anchor=_anchor(f"{slug}-{index}"),
        document_path=doc.path,
        section_path=(),
        text=f"{slug} did thing {index}.",
        citations=(),
    )


def _model(answer: str) -> GenericFakeChatModel:
    return GenericFakeChatModel(messages=iter([AIMessage(content=answer)]))


# --------------------------------------------------------------------- claim selection


def test_whole_document_kept_in_document_order_when_under_cap():
    doc = _doc("memory/people/ada.md", 5, "ada")
    claims = project_document_claims(doc)
    kept = select_timeline_claims(claims, {str(claims[2].anchor)}, cap=10)
    assert kept == claims  # all of them, untouched order


def test_over_cap_keeps_a_window_around_the_hits_in_document_order():
    doc = _doc("memory/people/ada.md", 20, "ada")
    claims = project_document_claims(doc)
    hit = {str(claims[10].anchor)}
    kept = select_timeline_claims(claims, hit, cap=5)
    assert len(kept) == 5
    positions = [claims.index(c) for c in kept]
    assert positions == sorted(positions)  # document order preserved
    assert 10 in positions  # the hit itself is kept
    assert max(abs(p - 10) for p in positions) <= 2  # a tight window around the hit


def test_cap_zero_selects_nothing():
    doc = _doc("memory/people/ada.md", 3, "ada")
    assert select_timeline_claims(project_document_claims(doc), set(), cap=0) == []


# --------------------------------------------------------------------- document fan-out


def test_doc_cap_and_hit_count_ranking():
    ada = _doc("memory/people/ada.md", 4, "ada")
    bob = _doc("memory/people/bob.md", 4, "bob")
    eve = _doc("memory/people/eve.md", 4, "eve")
    by_path = {d.path: d for d in (ada, bob, eve)}
    # bob hit twice, ada and eve once each — bob first, then ada (earlier first hit), eve cut.
    hits = [_hit(ada, 0, "ada"), _hit(bob, 1, "bob"), _hit(eve, 2, "eve"), _hit(bob, 3, "bob")]
    blocks = build_subject_timelines(hits, by_path, per_doc=10, doc_cap=2)
    assert [b.document_path for b in blocks] == [bob.path, ada.path]
    assert sum(len(b.claims) for b in blocks) <= 10 * 2


def test_hit_outside_the_canonical_set_never_expands():
    ada = _doc("memory/people/ada.md", 4, "ada")
    ghost = _doc("memory/people/ghost.md", 4, "ghost")
    hits = [_hit(ghost, 0, "ghost")]
    assert build_subject_timelines(hits, {ada.path: ada}, per_doc=10) == []


def test_flag_off_builds_nothing():
    ada = _doc("memory/people/ada.md", 4, "ada")
    hits = [_hit(ada, 0, "ada")]
    assert build_subject_timelines(hits, {ada.path: ada}, per_doc=0) == []


# ------------------------------------------------------- volume-aware subject expansion
#
# A rolled-over subject is one active page plus a same-name directory of frozen `aNN.md`
# volumes (compile/rollover.py). What is locked here: a hit on ANY shard expands the whole
# subject (volumes oldest-first, then the active page) as ONE block under the active page's
# path; shards count as one subject for the fan-out ranking; the per-subject cap bounds the
# subject's pages together; and a volume whose active page is absent stays its own subject.


def _subject_with_volumes(slug: str, *, volumes: int, per_page: int):
    """(active page, [volume docs]) — each page carries `per_page` dated claims."""
    base = f"work/products/{slug}"
    docs = [
        _doc(f"{base}/a{n:02d}.md", per_page, f"{slug}-a{n:02d}")
        for n in range(1, volumes + 1)
    ]
    return _doc(f"{base}.md", per_page, slug), docs


def test_timeline_subject_maps_a_volume_to_its_active_page():
    active, (a01,) = _subject_with_volumes("planner", volumes=1, per_page=2)
    by_path = {active.path: active, a01.path: a01}
    assert timeline_subject(a01.path, by_path) == active.path
    assert timeline_subject(active.path, by_path) == active.path
    # A volume whose active page is not in the canonical set is its own subject.
    assert timeline_subject(a01.path, {a01.path: a01}) == a01.path
    # A non-volume filename inside a directory is never remapped.
    assert timeline_subject("work/products/planner/notes.md", by_path) == "work/products/planner/notes.md"


def test_subject_timeline_paths_reads_volumes_oldest_first_then_the_active_page():
    active, (a01, a02) = _subject_with_volumes("planner", volumes=2, per_page=2)
    by_path = {a02.path: a02, active.path: active, a01.path: a01}
    assert subject_timeline_paths(active.path, by_path) == [a01.path, a02.path, active.path]


def test_a_hit_on_one_shard_expands_the_whole_subject():
    active, (a01, a02) = _subject_with_volumes("planner", volumes=2, per_page=3)
    by_path = {d.path: d for d in (active, a01, a02)}
    # The retrieval touched only the FIRST archive volume.
    blocks = build_subject_timelines(
        [_hit(a01, 1, "planner-a01")], by_path, per_doc=40
    )
    assert [b.document_path for b in blocks] == [active.path]
    (block,) = blocks
    assert block.total_claims == 9  # all three pages
    assert len(block.claims) == 9  # under the cap: the whole subject timeline
    texts = [c.text for c in block.claims]
    # Volumes oldest-first, active page last — approximate chronology preserved.
    assert "planner-a01 did thing 0." in texts[0]
    assert "planner did thing 2." in texts[-1]


def test_shards_count_as_one_subject_for_the_fan_out_ranking():
    active, (a01,) = _subject_with_volumes("planner", volumes=1, per_page=2)
    other = _doc("memory/people/ada.md", 2, "ada")
    by_path = {d.path: d for d in (active, a01, other)}
    # planner: one hit on the active page + one on its volume = 2 for ONE subject;
    # ada: one hit. doc_cap=1 keeps planner only — the shards were not two competitors.
    hits = [_hit(other, 0, "ada"), _hit(active, 1, "planner"), _hit(a01, 0, "planner-a01")]
    blocks = build_subject_timelines(hits, by_path, per_doc=10, doc_cap=1)
    assert [b.document_path for b in blocks] == [active.path]


def test_the_per_subject_cap_bounds_all_pages_together():
    active, (a01, a02) = _subject_with_volumes("planner", volumes=2, per_page=10)
    by_path = {d.path: d for d in (active, a01, a02)}
    blocks = build_subject_timelines(
        [_hit(a02, 4, "planner-a02")], by_path, per_doc=5, doc_cap=2
    )
    (block,) = blocks
    assert len(block.claims) == 5  # per_doc caps the SUBJECT, not each page
    assert block.total_claims == 30
    # The kept window still centres on the hit (which lives in a02, the middle page).
    assert any("planner-a02 did thing 4." in c.text for c in block.claims)


def test_a_volume_without_its_active_page_stays_its_own_subject():
    _, (a01,) = _subject_with_volumes("planner", volumes=1, per_page=3)
    blocks = build_subject_timelines(
        [_hit(a01, 0, "planner-a01")], {a01.path: a01}, per_doc=10
    )
    assert [b.document_path for b in blocks] == [a01.path]
    assert blocks[0].total_claims == 3


# --------------------------------------------------------------------- rendering


def test_rendering_carries_header_counts_dates_and_anchors():
    ada = _doc("memory/people/ada.md", 30, "ada")
    blocks = build_subject_timelines(
        [_hit(ada, 3, "ada")], {ada.path: ada}, per_doc=8
    )
    text = render_subject_timelines(blocks)
    assert prompt("recall.section.timelines_header", count=1) in text
    assert (
        prompt(
            "recall.fast.timeline.document",
            path="memory/people/ada.md",
            shown=8,
            total=30,
        )
        in text
    )
    assert "On 2025-04-04 ada did thing 3." in text  # dates live in the claim text
    assert f"〔c:{_anchor('ada-3')}〕" in text  # anchor provenance
    assert f"[cite: {'a' * 32} ¶3-3]" in text  # first citation kept


def test_recall_human_without_timelines_is_byte_identical():
    claims: list[RetrievedClaim] = []
    without = recall_human("q", claims, as_of=_AS_OF)
    with_empty = recall_human("q", claims, as_of=_AS_OF, timelines=())
    assert without == with_empty
    assert prompt("recall.section.timelines_header", count=0).split(" (")[0] not in without


# --------------------------------------------------------------------- the lane end-to-end


async def test_fast_recall_off_by_default_and_on_when_asked():
    ada = _doc("memory/people/ada.md", 6, "ada")
    stub = ClaimStub(
        _anchor("ada-2"), ada.path, "ada did thing 2.", citations=[]
    )
    index = FakeClaimIndex([stub])

    off = await fast_recall(
        _USER,
        "q",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=_model("a1"),
        documents=[ada],
        glance_timeout=0.01,
    )
    assert off.timeline_documents == ()
    assert off.timeline_claims == 0

    on = await fast_recall(
        _USER,
        "q",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=_model("a2"),
        documents=[ada],
        glance_timeout=0.01,
        timeline_expand=40,
    )
    assert on.timeline_documents == (ada.path,)
    assert on.timeline_claims == 6  # the whole subject document, it fits the cap


async def test_fast_recall_without_documents_never_expands():
    """The expansion reads canonical; with no canonical supplied the flag is inert."""
    stub = ClaimStub(_anchor("ada-0"), "memory/people/ada.md", "ada did thing 0.")
    index = FakeClaimIndex([stub])
    result = await fast_recall(
        _USER,
        "q",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
        model=_model("a"),
        timeline_expand=40,
    )
    assert result.timeline_documents == ()
    assert result.timeline_claims == 0
