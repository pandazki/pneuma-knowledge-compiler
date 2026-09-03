"""The archive, on the answering side: what every lane excludes by default and how it says so.

The one property under test is stated in docs/design/archive.md §3-4: **the default is to
exclude, and the exception is stated**. So each test below hands a lane an index that has
never heard of the archive — it returns the archived claim exactly as it returns the live one
— and asserts the lane itself is what keeps it out. That is the whole point of the
assembly-time filter: the two real indexes do filter, but a component path, a briefing pack
and a fake written last year do not, and the property has to hold for all of them.

The `include_archived` half is asserted just as hard: an admitted archived item is LABELLED
and placed last, and the SystemMessage is byte-identical either way (I5) — the flag changes
what evidence is assembled, never the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel, Field

from pneuma_knowledge_core.domain.canonical import CanonicalDocument, Citation
from pneuma_knowledge_core.domain.ids import AnchorId, DocumentId, SourceId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import NormalizedSource
from pneuma_knowledge_core.recall import briefing as briefing_module
from pneuma_knowledge_core.recall.archive_filter import (
    ARCHIVED_LABEL,
    archive_view,
    filter_path_result,
)
from pneuma_knowledge_core.recall.briefing import BriefingScope, build_briefing
from pneuma_knowledge_core.recall.deep import deep_recall
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.fast import (
    RetrievedClaim,
    fast_recall,
    render_episode_summaries,
)
from pneuma_knowledge_core.recall.paths import PathResult
from pneuma_knowledge_core.recall.rag import rag_recall

from test_deep_recall import ScriptedToolModel  # noqa: E402
from test_fast_paths import _Model as RoutingModel  # noqa: E402
from test_fast_recall import FakeEmbeddings, LexHit, VecHit  # noqa: E402

_USER = UserId("u-archive")
_AS_OF = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

LIVE_SOURCE = "src-live"
ARCHIVED_SOURCE = "src-old"
LIVE_DOC = "memory/projects/aurora-next.md"
ARCHIVED_DOC = "archive/memory/projects/aurora.md"


# --------------------------------------------------------------------------- fakes


@dataclass
class ClaimStub:
    """A claim hit exactly as an index that never heard of the archive returns one."""

    anchor: str
    document_path: str
    text: str
    section_path: list[str] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    score: float = 0.0


class BlindClaimIndex:
    """Both claim faces, and DELIBERATELY blind to `include_archived`.

    It accepts the keyword and ignores it, which is the case the assembly filter exists for:
    an index (or a component, or a fake) that never learned the flag must not be able to put
    the archive into an answer that did not ask for it."""

    def __init__(self, claims: list[ClaimStub]) -> None:
        self._claims = claims
        self.scopes: list[bool] = []

    async def search_claims(  # noqa: ANN001
        self, user_id, query_or_embedding, *, limit=40, include_archived=False
    ):
        self.scopes.append(include_archived)
        return self._claims[:limit]


class BlindLexical:
    def __init__(self, hits: list[LexHit]) -> None:
        self._hits = hits
        self.scopes: list[bool] = []

    async def search(self, user_id, query, *, limit=20, include_archived=False):  # noqa: ANN001
        self.scopes.append(include_archived)
        return self._hits[:limit]


@dataclass
class EpiHit:
    """An episode-representation point: a derived description with the span it indexes."""

    source_id: SourceId
    block_start: int
    block_end: int
    text: str
    episode_summary_text: str
    score: float = 1.0


class BlindVector:
    def __init__(self, hits: list[VecHit], episodes: list[EpiHit] | None = None) -> None:
        self._hits = hits
        self._episodes = episodes or []
        self.scopes: list[bool] = []

    async def search(  # noqa: ANN001
        self, user_id, embedding, *, limit=20, representation="raw", include_archived=False
    ):
        self.scopes.append(include_archived)
        if representation == "raw":
            return self._hits[:limit]
        if representation == "episode":
            return self._episodes[:limit]
        return []


def _source(source_id: str, blocks: dict[int, str]) -> NormalizedSource:
    return NormalizedSource.model_validate(
        {
            "raw": {
                "source_id": source_id,
                "user_id": str(_USER),
                "kind": "document",
                "origin": "mock",
                "title": f"{source_id} record",
                "mime": "text/markdown",
                "checksum": "fixture",
                "created_at": "2026-06-01T00:00:00Z",
            },
            "blocks": [
                {"index": index, "text": text} for index, text in sorted(blocks.items())
            ],
            "structure": {"sections": []},
        }
    )


_SOURCES = {
    LIVE_SOURCE: _source(LIVE_SOURCE, {1: "The successor ships in Q4."}),
    ARCHIVED_SOURCE: _source(ARCHIVED_SOURCE, {3: "Aurora shipped in June."}),
}


class ArchiveAwareContent:
    """A ContentStore that knows one archived source — the L0 half of the mark."""

    def __init__(self, archived: tuple[str, ...] = (ARCHIVED_SOURCE,)) -> None:
        self.archived = frozenset(SourceId(s) for s in archived)
        self.reads = 0

    async def archived_source_ids(self, user_id):  # noqa: ANN001
        self.reads += 1
        return self.archived

    async def get(self, user_id, source_id):  # noqa: ANN001
        return _SOURCES[str(source_id)]

    async def fetch(self, user_id, source_id, locator):  # noqa: ANN001
        return f"raw text for {source_id}"


class BlindContent(ArchiveAwareContent):
    """A store written before the archive existed: no `archived_source_ids` at all."""

    archived_source_ids = None  # type: ignore[assignment]


def _doc(path: str, body: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(path.replace("/", "-")),
        path=path,
        frontmatter={"title": path.rsplit("/", 1)[-1]},
        body=body,
    )


LIVE_PAGE = _doc(LIVE_DOC, "# Aurora Next\n\n- The successor ships in Q4.\n")
ARCHIVED_PAGE = _doc(ARCHIVED_DOC, "# Aurora\n\n- Aurora shipped in June.\n")


def _claims() -> list[ClaimStub]:
    return [
        ClaimStub(
            anchor="1111",
            document_path=LIVE_DOC,
            text="The successor ships in Q4.",
            citations=[
                {"source_id": LIVE_SOURCE, "block_start": 1, "block_end": 2}
            ],
            score=1.0,
        ),
        ClaimStub(
            anchor="2222",
            document_path=ARCHIVED_DOC,
            text="Aurora shipped in June.",
            citations=[
                {"source_id": ARCHIVED_SOURCE, "block_start": 3, "block_end": 4}
            ],
            score=0.9,
        ),
    ]


class CapturingModel(GenericFakeChatModel):
    """Records the exact message list it answered over — the I5 evidence."""

    seen: list = []

    async def ainvoke(self, messages, *args, **kwargs):  # noqa: ANN001, ANN002
        type(self).seen.append(list(messages))
        return await super().ainvoke(messages, *args, **kwargs)


def _model(answer: str = "ok") -> CapturingModel:
    CapturingModel.seen = []
    return CapturingModel(messages=iter([AIMessage(content=answer)]))


#: The two derived episode descriptions the L2 episode representation would return for the
#: same two spans the raw hits above cover — one live, one from the retired source.
LIVE_EPISODE = "[episode title] The successor\n[episode description] Ship date for Q4."
ARCHIVED_EPISODE = "[episode title] Aurora\n[episode description] The June ship."


def _episodes() -> list[EpiHit]:
    return [
        EpiHit(
            SourceId(LIVE_SOURCE), 1, 1, "The successor ships in Q4.", LIVE_EPISODE
        ),
        EpiHit(
            SourceId(ARCHIVED_SOURCE), 3, 3, "Aurora shipped in June.", ARCHIVED_EPISODE
        ),
    ]


async def _fast(*, include_archived: bool, content=None, episodes=None, **extra):
    claim_index = BlindClaimIndex(_claims())
    lexical = BlindLexical(
        [
            LexHit(SourceId(LIVE_SOURCE), 1, "The successor ships in Q4."),
            LexHit(SourceId(ARCHIVED_SOURCE), 3, "Aurora shipped in June."),
        ]
    )
    vectors = BlindVector(
        [
            VecHit(SourceId(LIVE_SOURCE), 1, 1, "The successor ships in Q4."),
            VecHit(SourceId(ARCHIVED_SOURCE), 3, 3, "Aurora shipped in June."),
        ],
        episodes,
    )
    answer = await fast_recall(
        _USER,
        "what is happening with aurora",
        as_of=_AS_OF,
        claim_lexical=claim_index,
        claim_vectors=claim_index,
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        model=_model(),
        content=content if content is not None else ArchiveAwareContent(),
        include_archived=include_archived,
        **extra,
    )
    return answer, claim_index, lexical, vectors


# ------------------------------------------------------------------- rag: the index face


async def test_rag_recall_states_the_exception_at_both_indexes_and_never_by_default():
    """rag reaches no model, so its whole archive scope IS the two index filters."""
    lexical = BlindLexical([LexHit(SourceId(LIVE_SOURCE), 1, "live")])
    vectors = BlindVector([VecHit(SourceId(LIVE_SOURCE), 1, 1, "live")])

    await rag_recall(
        _USER, "q", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings()
    )
    # Off is the port's own default, so the keyword is not passed at all — the call is
    # byte-for-byte what it was before the flag existed.
    assert lexical.scopes == [False] and vectors.scopes == [False, False]

    await rag_recall(
        _USER,
        "q",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        include_archived=True,
    )
    assert lexical.scopes[-1] is True
    assert vectors.scopes[-2:] == [True, True]


# ------------------------------------------------------------------------ fast recall


async def test_fast_drops_a_claim_whose_page_is_in_the_archive_and_a_window_from_one():
    answer, claim_index, _, _ = await _fast(include_archived=False)

    assert [c.document_path for c in answer.used_claims] == [LIVE_DOC]
    assert [str(w.source_id) for w in answer.used_windows] == [LIVE_SOURCE]
    # The index was asked WITHOUT the flag — the default is off at the index too.
    assert claim_index.scopes == [False, False]


async def test_fast_admits_the_archive_when_asked_labelled_and_after_the_live_claims():
    answer, claim_index, _, _ = await _fast(include_archived=True)

    paths = [c.document_path for c in answer.used_claims]
    assert paths == [LIVE_DOC, ARCHIVED_DOC], "history is placed after the present"
    archived_claim = answer.used_claims[-1]
    assert ARCHIVED_LABEL in archived_claim.labels
    assert claim_index.scopes == [True, True]

    admitted = {str(w.source_id): w for w in answer.used_windows}
    assert set(admitted) == {LIVE_SOURCE, ARCHIVED_SOURCE}
    assert admitted[ARCHIVED_SOURCE].archived is True
    assert admitted[LIVE_SOURCE].archived is False


# ------------------------------------------- fast: the derived episode-summary face


async def test_an_episode_summary_from_an_archived_source_is_dropped_by_default():
    """The face that PARAPHRASES a source is filtered like the one that quotes it."""
    answer, _, _, _ = await _fast(include_archived=False, episodes=_episodes())

    assert [str(s.source_id) for s in answer.used_episode_summaries] == [LIVE_SOURCE]
    assert all(s.archived is False for s in answer.used_episode_summaries)


async def test_an_admitted_episode_summary_carries_the_archive_flag_and_the_marker():
    """The finding: an admitted archived window became a summary WITHOUT its flag, so the
    one evidence face that is model-written compression reached the answer looking exactly
    like the present. The flag rides the window it was lifted from, and it renders."""
    answer, _, _, _ = await _fast(include_archived=True, episodes=_episodes())

    by_source = {str(s.source_id): s for s in answer.used_episode_summaries}
    assert set(by_source) == {LIVE_SOURCE, ARCHIVED_SOURCE}
    assert by_source[ARCHIVED_SOURCE].archived is True
    assert by_source[LIVE_SOURCE].archived is False

    # …and the marker is the SAME one the windows carry, in the same place: right after the
    # `[cite: …]` token on the item's provenance line.
    rendered = render_episode_summaries(list(by_source.values()))
    marker = prompt("recall.passage_in_archive")
    assert f"[cite: {ARCHIVED_SOURCE} ¶3-3] {marker}" in rendered
    assert f"[cite: {LIVE_SOURCE} ¶1-1]\n" in rendered

    # The human turn the model actually answered over says it too — under the per-round
    # source aliases the prompt uses, so the span is what identifies the item here.
    human = CapturingModel.seen[-1][-1].content
    assert f"¶3-3] {marker}\n{ARCHIVED_EPISODE}" in human
    assert f"¶1-1]\n{LIVE_EPISODE}" in human


async def test_with_nothing_archived_the_summary_face_renders_as_it_always_did():
    """Inertness, on this face too: an empty archive leaves not one byte of marker."""
    answer, _, _, _ = await _fast(
        include_archived=True, content=_no_archive(), episodes=_episodes()
    )

    assert {str(s.source_id) for s in answer.used_episode_summaries} == {
        LIVE_SOURCE,
        ARCHIVED_SOURCE,
    }
    assert all(s.archived is False for s in answer.used_episode_summaries)
    rendered = render_episode_summaries(list(answer.used_episode_summaries))
    assert prompt("recall.passage_in_archive") not in rendered


async def test_the_system_message_is_byte_identical_with_the_flag_on_and_off():
    """I5. `include_archived` changes what evidence is assembled, never the contract."""
    await _fast(include_archived=False)
    off = CapturingModel.seen[-1][0].content
    await _fast(include_archived=True)
    on = CapturingModel.seen[-1][0].content

    assert off == on
    assert "archiv" not in str(off).lower()


async def test_the_glance_follows_the_flag_and_the_human_turn_shows_the_difference():
    documents = [LIVE_PAGE, ARCHIVED_PAGE]
    await _fast(include_archived=False, documents=documents)
    off = str(CapturingModel.seen[-1][1].content)
    await _fast(include_archived=True, documents=documents)
    on = str(CapturingModel.seen[-1][1].content)

    assert ARCHIVED_DOC not in off
    assert ARCHIVED_DOC in on


async def test_a_store_that_never_heard_of_the_archive_still_answers():
    """Fail-soft on the PORT: the document half of the filter runs regardless."""
    answer, _, _, _ = await _fast(include_archived=False, content=BlindContent())

    assert [c.document_path for c in answer.used_claims] == [LIVE_DOC]
    # No source mark is knowable, so both windows stand — an honest degradation, not a lie.
    assert {str(w.source_id) for w in answer.used_windows} == {
        LIVE_SOURCE,
        ARCHIVED_SOURCE,
    }


# ------------------------------------------------------------------- the component face


class _Args(BaseModel):
    alias: str = Field(default="")


class ArchiveBlindPath:
    """A component path that reads its own projection and has never heard of the archive."""

    name = "person"
    description = "look up one person page"
    args_schema = _Args
    cap = 8

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        return PathResult(
            claims=(
                RetrievedClaim(
                    anchor=AnchorId("3333"),
                    document_path=ARCHIVED_DOC,
                    section_path=("ledger",),
                    text="Aurora shipped in June.",
                    citations=(
                        Citation(
                            source_id=SourceId(ARCHIVED_SOURCE),
                            block_start=3,
                            block_end=4,
                        ),
                    ),
                ),
            )
        )


async def test_a_component_path_result_pointing_at_the_archive_is_dropped():
    """I7 in one assertion: no component learns of the archive, and none has to."""
    view = await archive_view(_USER, ArchiveAwareContent())
    result = await ArchiveBlindPath().run(str(_USER), _Args())

    filtered, dropped = filter_path_result(result, view)

    assert dropped == 1
    assert filtered.claims == ()


async def test_a_component_window_from_an_archived_source_is_dropped_too():
    view = await archive_view(_USER, ArchiveAwareContent())
    from pneuma_knowledge_core.recall.rag import RecallHit

    result = PathResult(
        windows=(
            RecallHit(
                source_id=SourceId(ARCHIVED_SOURCE),
                block_start=3,
                block_end=4,
                text="Aurora shipped in June.",
                paths=("person",),
                score=1.0,
            ),
            RecallHit(
                source_id=SourceId(LIVE_SOURCE),
                block_start=1,
                block_end=2,
                text="The successor ships in Q4.",
                paths=("person",),
                score=1.0,
            ),
        )
    )
    filtered, dropped = filter_path_result(result, view)

    assert dropped == 1
    assert [str(w.source_id) for w in filtered.windows] == [LIVE_SOURCE]


# ------------------------------------------------------------------------ deep recall


async def _deep(
    *,
    include_archived: bool,
    turns,
    documents=(LIVE_PAGE, ARCHIVED_PAGE),
    content=None,
    claims=None,
    **extra,
):
    claim_index = BlindClaimIndex(list(claims) if claims is not None else _claims())
    return await deep_recall(
        _USER,
        "what is happening with aurora",
        as_of=_AS_OF,
        claim_lexical=claim_index,
        claim_vectors=claim_index,
        embeddings=FakeEmbeddings(),
        model=ScriptedToolModel(turns=list(turns), seen=[]),
        content=content if content is not None else ArchiveAwareContent(),
        lexical=BlindLexical(
            [LexHit(SourceId(ARCHIVED_SOURCE), 3, "Aurora shipped in June.")]
        ),
        vectors=BlindVector(
            [VecHit(SourceId(ARCHIVED_SOURCE), 3, 3, "Aurora shipped in June.")]
        ),
        documents=list(documents),
        include_archived=include_archived,
        **extra,
    )


async def test_deep_seeds_over_live_knowledge_only_and_lists_no_archived_path():
    answer = await _deep(
        include_archived=False,
        turns=[
            AIMessage(
                content="",
                tool_calls=[{"name": "list_documents", "args": {}, "id": "t1"}],
            ),
            AIMessage(content="done"),
        ],
    )

    assert [c.document_path for c in answer.used_claims] == [LIVE_DOC]
    assert answer.used_windows == ()
    listed = next(step for step in answer.trail if step["tool"] == "list_documents")
    assert LIVE_DOC in listed["result"] and ARCHIVED_DOC not in listed["result"]


async def test_reading_an_archived_page_is_a_stated_absence_not_a_miss():
    """The page exists — saying "no document there" would be false, and silence worse."""
    answer = await _deep(
        include_archived=False,
        turns=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_document",
                        "args": {"path": ARCHIVED_DOC},
                        "id": "t1",
                    }
                ],
            ),
            AIMessage(content="done"),
        ],
    )

    step = next(s for s in answer.trail if s["tool"] == "read_document")
    assert step["archived"] is True
    assert "archive" in step["result"].lower()
    assert "Aurora shipped in June" not in step["result"]
    assert answer.read_documents == ()


async def test_deep_admits_the_archive_when_asked():
    answer = await _deep(
        include_archived=True,
        turns=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "read_document",
                        "args": {"path": ARCHIVED_DOC},
                        "id": "t1",
                    }
                ],
            ),
            AIMessage(content="done"),
        ],
    )

    assert [c.document_path for c in answer.used_claims] == [LIVE_DOC, ARCHIVED_DOC]
    assert answer.used_claims[-1].labels[-1] == ARCHIVED_LABEL
    assert answer.read_documents == (ARCHIVED_DOC,)


# --------------------------------------------------------------------------- briefing


async def _briefing(*, include_archived: bool):
    claim_index = BlindClaimIndex(_claims())
    return await build_briefing(
        _USER,
        BriefingScope(query="aurora", include_archived=include_archived),
        snapshot=SnapshotRef(ref="sha-1"),
        snapshot_docs=[LIVE_PAGE] if not include_archived else [LIVE_PAGE, ARCHIVED_PAGE],
        content=ArchiveAwareContent(),
        claim_lexical=claim_index,
        claim_vectors=claim_index,
        embeddings=FakeEmbeddings(),
    )


async def test_a_pack_built_without_the_archive_holds_no_archived_claim():
    briefing = await _briefing(include_archived=False)

    assert "Aurora shipped in June" not in briefing.system_prefix
    assert "The successor ships in Q4" in briefing.system_prefix
    assert briefing.claims_count == 1
    assert briefing.include_archived is False


async def test_a_pack_built_with_the_archive_carries_the_choice_to_every_ask():
    briefing = await _briefing(include_archived=True)

    assert "Aurora shipped in June" in briefing.system_prefix
    # The pack was built once; the ask inherits, so the two halves of one answer cannot come
    # from two different planes.
    assert briefing.include_archived is True


async def test_the_ask_tool_inherits_the_packs_choice_rather_than_taking_its_own():
    claim_index = BlindClaimIndex(_claims())
    view = await archive_view(_USER, ArchiveAwareContent())
    sink: list[dict] = []
    tool = briefing_module._search_knowledge_tool(
        _USER,
        source_ids=(),
        claim_lexical=claim_index,
        claim_vectors=claim_index,
        embeddings=FakeEmbeddings(),
        content=ArchiveAwareContent(),
        sink=sink,
        view=view,
        include_archived=False,
    )

    out = await tool.ainvoke({"query": "aurora"})

    assert "The successor ships in Q4" in out
    assert "Aurora shipped in June" not in out
    assert sink[0]["archive_hidden"] == 1


# ----------------------------------------------------------------------- live context


async def test_the_live_pipeline_is_never_offered_the_archive_and_says_what_it_hid():
    """No `include_archived` here, and there will not be one: nobody asked a question in a
    room, so there is no call on which to state the exception (archive.md §4)."""
    from test_live_pipeline import (  # noqa: E402
        FakeClaimVectors,
        FakeStructured,
        discovered,
        other,
        semantic_plan,
    )
    from pneuma_knowledge_core.domain.suggestion import PickResult
    from pneuma_knowledge_core.recall.live_pipeline import evaluate_live_pipeline

    class Blind:
        """A claim face that returns the archived claim exactly as it returns the live one."""

        async def search_claims(self, user_id, query, *, limit=40):  # noqa: ANN001
            return _claims()[:limit]

    result = await evaluate_live_pipeline(
        _USER,
        [other("aurora 现在到哪一步了？")],
        as_of=_AS_OF,
        discover_model=FakeStructured(
            [discovered(intent="aurora status", plan=semantic_plan("aurora"), worth=9)]
        ),
        pick_model=FakeStructured(
            [PickResult(choice=1, lede="下一代在 Q4。", citations=[1], confidence=9)]
        ),
        embeddings=FakeEmbeddings(),
        claim_lexical=Blind(),
        claim_vectors=FakeClaimVectors(),
        content=ArchiveAwareContent(),
    )

    assert result.dropped.get("archived") == 1, "an omission nobody can see is not reported"
    for card in result.candidates:
        assert ARCHIVED_DOC not in card.body
        assert "Aurora shipped in June" not in card.body


# ------------------------------------------------- rag: the assembly half of the same rule


class ArchiveBlindLexical(BlindLexical):
    """A lexical index that accepts `include_archived` and IGNORES it.

    Not a strawman: the flag is a Meilisearch filter over a field flipped by an
    `update_documents` call after the move, and a call that failed, an index built before the
    field existed, or a deployment mid-migration all behave exactly like this."""

    async def search(self, user_id, query, *, limit=20, include_archived=False):  # noqa: ANN001
        self.scopes.append(include_archived)
        return self._hits[:limit]


class ArchiveBlindVector(BlindVector):
    """The Qdrant half of the same failure: a `set_payload` that never landed."""

    async def search(  # noqa: ANN001
        self, user_id, embedding, *, limit=20, representation="raw", include_archived=False
    ):
        self.scopes.append(include_archived)
        return self._hits[:limit] if representation == "raw" else []


def _rag_indexes() -> tuple[ArchiveBlindLexical, ArchiveBlindVector]:
    return (
        ArchiveBlindLexical(
            [
                LexHit(SourceId(LIVE_SOURCE), 1, "The successor ships in Q4."),
                LexHit(SourceId(ARCHIVED_SOURCE), 3, "Aurora shipped in June."),
            ]
        ),
        ArchiveBlindVector(
            [
                VecHit(SourceId(LIVE_SOURCE), 1, 1, "The successor ships in Q4."),
                VecHit(SourceId(ARCHIVED_SOURCE), 3, 3, "Aurora shipped in June."),
            ]
        ),
    )


async def test_rag_postfilters_blind_index_hits_and_labels_opt_in_hits():
    """The rag lane may not rest on the two index filters ALONE.

    Every other lane applies the archive rule a second time at assembly; rag used to trust
    the backends, which made "no archive in a default answer" a property of a payload flag in
    two systems rather than of this code. Handed the store, it keeps the property itself: off
    drops the archived hit, on ADMITS it carrying `archived=True`, so the client holding the
    opt-in list can tell the two apart."""
    lexical, vectors = _rag_indexes()

    default = await rag_recall(
        _USER,
        "aurora",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        content=ArchiveAwareContent(),
    )

    assert [str(h.source_id) for h in default] == [LIVE_SOURCE], "the index lied; the lane did not"
    assert all(h.archived is False for h in default)

    admitted = await rag_recall(
        _USER,
        "aurora",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        content=ArchiveAwareContent(),
        include_archived=True,
    )

    labelled = {str(h.source_id): h.archived for h in admitted}
    assert labelled == {LIVE_SOURCE: False, ARCHIVED_SOURCE: True}


async def test_rag_without_a_store_is_byte_for_byte_the_lane_it_always_was():
    """`content` is optional, so no existing caller changes behaviour by being recompiled."""
    lexical, vectors = _rag_indexes()

    hits = await rag_recall(
        _USER, "aurora", lexical=lexical, vectors=vectors, embeddings=FakeEmbeddings()
    )

    assert {str(h.source_id) for h in hits} == {LIVE_SOURCE, ARCHIVED_SOURCE}


async def test_rag_states_what_the_assembly_filter_hid():
    """An omission nobody can see is not reported. It rides the stage this lane already has."""
    from pneuma_knowledge_core.recall.rag import (
        RAG_RETRIEVE_CHILDREN,
        RAG_STAGE_ORDER,
    )
    from pneuma_knowledge_core.recall.stage_timing import StageRecorder

    lexical, vectors = _rag_indexes()
    timer = StageRecorder(RAG_STAGE_ORDER, RAG_RETRIEVE_CHILDREN)
    await rag_recall(
        _USER,
        "aurora",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        content=ArchiveAwareContent(),
        stages=timer,
    )

    expand = next(st for st in timer.emit() if st.name == "expand")
    assert expand.preview["archive_hidden"] == 1


# --------------------------------------------------- the port: soft, but never swallowing


class BrokenContent(ArchiveAwareContent):
    """A REAL adapter that breaks inside its own body — not one that lacks the method."""

    async def archived_source_ids(self, user_id):  # noqa: ANN001
        self.reads += 1
        raise TypeError("unhashable type: 'list'")


class BrokenAttributeContent(ArchiveAwareContent):
    async def archived_source_ids(self, user_id):  # noqa: ANN001
        raise AttributeError("'NoneType' object has no attribute 'fetch'")


class StubbedContent(ArchiveAwareContent):
    """The last honest shape of "not implemented": the method is there and returns None."""

    def archived_source_ids(self, user_id):  # noqa: ANN001
        return None


async def test_archive_view_propagates_internal_type_errors():
    """"The port lacks the method" is decided by INTROSPECTION, never by an exception type.

    Catching `TypeError` / `AttributeError` around the CALL could not tell a store with no
    archive to report from an adapter that broke halfway through building its set — and it
    resolved that ambiguity by returning the empty view, which is fail-OPEN: the answer goes
    out with archived sources in it and nothing anywhere saying so. A store that has the
    method owns what it raises."""
    broken = BrokenContent()
    with pytest.raises(TypeError):
        await archive_view(_USER, broken)
    assert broken.reads == 1, "the failure came from inside the call, not from finding it"

    with pytest.raises(AttributeError):
        await archive_view(_USER, BrokenAttributeContent())

    # The two shapes that ARE "no archive here" still degrade softly, and only they.
    assert (await archive_view(_USER, BlindContent())).sources == frozenset()
    assert (await archive_view(_USER, StubbedContent())).sources == frozenset()
    assert (await archive_view(_USER, None)).sources == frozenset()


async def test_a_broken_store_fails_the_lane_rather_than_answering_out_of_the_archive():
    """The consequence, stated at the lane: a retrieval that cannot read the mark stops."""
    with pytest.raises(TypeError):
        await _fast(include_archived=False, content=BrokenContent())


# ------------------------------------------ the index lags the move: pin to the documents


MOVED_LIVE_PATH = "work/products/aurora.md"
MOVED_ARCHIVED_PATH = "archive/work/products/aurora.md"
MOVED_PAGE = _doc(MOVED_ARCHIVED_PATH, "# Aurora\n\n- Aurora shipped in June.\n")


def _stale_claims() -> list[ClaimStub]:
    """What the L3 index returns while the projection has not caught up with the move."""
    return [
        ClaimStub(
            anchor="4444",
            document_path=MOVED_LIVE_PATH,  # the OLD path — the row predates the sync
            text="Aurora shipped in June.",
            citations=[{"source_id": LIVE_SOURCE, "block_start": 1, "block_end": 2}],
            score=1.0,
        )
    ]


async def _fast_over(
    claims: list[ClaimStub], *, documents, include_archived: bool, content=None, **extra
):
    index = BlindClaimIndex(claims)
    answer = await fast_recall(
        _USER,
        "what is happening with aurora",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        lexical=BlindLexical([]),
        vectors=BlindVector([]),
        embeddings=FakeEmbeddings(),
        model=_model(),
        content=content if content is not None else ArchiveAwareContent(),
        documents=documents,
        include_archived=include_archived,
        **extra,
    )
    return answer


async def test_projection_failure_after_move_cannot_expose_old_path_claims():
    """The move is the state; the index is derived, and derived LAGS.

    After `work/products/aurora.md` becomes `archive/work/products/aurora.md`, its L3 rows
    keep the old live path until the incremental projection lands — and a projection that
    failed keeps it indefinitely. Read off the row, that path says "live", so the archive
    rule as written on the row alone would pass the claim straight into a default answer.

    So the lane reads it the other way round: a claim is admitted only when the canonical
    document set it was handed still holds its page. That set is authoritative and current;
    the index only proposes.

    The view here is ACTIVE — `ArchiveAwareContent` reports one archived source — and that is
    load-bearing since the pin became conditional: with nothing ever archived there is no
    window between a move and its projection to close, and the pin does not run at all
    (`archive_filter._pin`, and the empty-archive tests at the bottom of this file)."""
    answer = await _fast_over(
        _stale_claims(), documents=[MOVED_PAGE], include_archived=False
    )

    assert answer.used_claims == (), "the stale row named a page canonical no longer has"

    # The control, so the assertion above cannot pass for the wrong reason: the SAME claim,
    # against a library where the page really is still live.
    live_page = _doc(MOVED_LIVE_PATH, "# Aurora\n\n- Aurora shipped in June.\n")
    kept = await _fast_over(
        _stale_claims(), documents=[live_page], include_archived=False
    )
    assert [c.document_path for c in kept.used_claims] == [MOVED_LIVE_PATH]


async def test_a_lane_handed_no_document_set_is_not_pinned():
    """`live_paths=None` is not an empty set: a caller with NO documents pins nothing.

    This is the distinction the pin rests on, so it is pinned from both sides — the empty
    set below drops everything, and "not handed a set at all" (rag, a briefing's ask over a
    stored pack, a core caller that never loaded canonical) drops nothing."""
    answer = await _fast_over(_stale_claims(), documents=None, include_archived=False)

    assert [c.document_path for c in answer.used_claims] == [MOVED_LIVE_PATH]


async def test_an_empty_live_library_pins_every_index_claim_out():
    """The Owner archived the LAST live page. The authoritative answer is "nothing".

    An empty document set is a set, and it says the answering library holds no page. Read as
    "no pin" — which is what `if documents else None` did — the empty case fails OPEN: the
    one library where every L3 row is stale by construction is the one where the stale row
    reaches the answer. So it pins to nothing, and the drop is counted like every other.

    Note WHICH library this is: one whose every page the Owner archived, so the view is
    ACTIVE (`ArchiveAwareContent` reports an archived source) and the pin runs. An empty
    document set in a library that never archived anything is a different state entirely —
    the pin is off there and the claim stands (`_pin`, and the empty-archive tests below)."""
    answer = await _fast_over(_stale_claims(), documents=[], include_archived=False)

    assert answer.used_claims == ()
    retrieve = next(st for st in answer.stages if st.name == "retrieve")
    assert retrieve.preview["archive_hidden"] == 1


async def test_deep_over_an_empty_live_library_pins_its_search_out_too():
    """The same fact through deep's own counted channel — the tool trail.

    Deep runs a bounded loop over the same index, so an empty library that failed open here
    would put the archived page back in front of the model one `search_claims` later. Active
    view again, and for the same reason as the fast case above."""
    answer = await _deep(
        include_archived=False,
        documents=[],
        turns=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_claims", "args": {"query": "aurora"}, "id": "t1"}
                ],
            ),
            AIMessage(content="done"),
        ],
    )

    assert answer.used_claims == (), "the seed pinned out too"
    step = next(s for s in answer.trail if s["tool"] == "search_claims")
    assert step["hits"] == 0 and step["archive_hidden"] == 2


async def test_asking_for_the_archive_pins_to_the_whole_tree_archived_pages_included():
    """`include_archived=True` hands the lane the FULL set, so the archive is pinned, not
    filtered — otherwise the opt-in would drop exactly what it asked for."""
    answer, _, _, _ = await _fast(
        include_archived=True, documents=[LIVE_PAGE, ARCHIVED_PAGE]
    )

    assert [c.document_path for c in answer.used_claims] == [LIVE_DOC, ARCHIVED_DOC]


# ------------------------------------- the component face on the OPT-IN path: labelled too


def _routing_model() -> RoutingModel:
    """A model whose FIRST (tool-bound) turn routes to the component path."""
    return RoutingModel(
        answer="ok",
        route_calls=[
            {"name": "person", "args": {"alias": "aurora"}, "id": "t1", "type": "tool_call"}
        ],
    )


class ArchivedWindowPath(ArchiveBlindPath):
    """One component result carrying both halves out of the archive."""

    async def run(self, user_id, args, *, scope=None, documents=None, as_of=None):  # noqa: ANN001
        from pneuma_knowledge_core.recall.rag import RecallHit

        return PathResult(
            claims=(
                RetrievedClaim(
                    anchor=AnchorId("3333"),
                    document_path=ARCHIVED_DOC,
                    section_path=("ledger",),
                    text="Aurora shipped in June.",
                    citations=(
                        # A span OUTSIDE the window below, so the claim stands as a claim:
                        # the face folds a claim whose evidence its own window already covers.
                        Citation(
                            source_id=SourceId(ARCHIVED_SOURCE),
                            block_start=9,
                            block_end=10,
                        ),
                    ),
                ),
                RetrievedClaim(
                    anchor=AnchorId("5555"),
                    document_path=LIVE_DOC,
                    section_path=("ledger",),
                    text="The successor ships in Q4.",
                    citations=(
                        Citation(
                            source_id=SourceId(LIVE_SOURCE),
                            block_start=1,
                            block_end=2,
                        ),
                    ),
                ),
            ),
            windows=(
                RecallHit(
                    source_id=SourceId(ARCHIVED_SOURCE),
                    block_start=3,
                    block_end=4,
                    text="Aurora shipped in June.",
                    paths=("person",),
                    score=1.0,
                ),
            ),
        )


async def test_fast_component_opt_in_labels_archived_claims():
    """The opt-in path used to SKIP the component face entirely rather than mark it.

    That left a routed path's evidence as the one face reaching the model unlabelled and in
    live-first position — history presented as the present, which is precisely what the
    `archived` label exists to prevent. A component knows nothing of the archive (I7), so the
    label is applied here or nowhere."""
    index = BlindClaimIndex([])
    answer = await fast_recall(
        _USER,
        "what is happening with aurora",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        lexical=BlindLexical([]),
        vectors=BlindVector([]),
        embeddings=FakeEmbeddings(),
        model=_routing_model(),
        content=ArchiveAwareContent(),
        fast_paths=[ArchivedWindowPath()],
        include_archived=True,
    )

    [evidence] = answer.used_component_evidence
    # Live first, history after it — the same ordering the ranked faces get.
    assert [c.document_path for c in evidence.claims] == [LIVE_DOC, ARCHIVED_DOC]
    assert ARCHIVED_LABEL in evidence.claims[-1].labels
    assert ARCHIVED_LABEL not in evidence.claims[0].labels
    assert [w.archived for w in evidence.windows] == [True]


async def test_fast_component_default_still_drops_what_it_would_have_labelled():
    """The other half of the same switch, so neither can be changed without the other."""
    index = BlindClaimIndex([])
    answer = await fast_recall(
        _USER,
        "what is happening with aurora",
        as_of=_AS_OF,
        claim_lexical=index,
        claim_vectors=index,
        lexical=BlindLexical([]),
        vectors=BlindVector([]),
        embeddings=FakeEmbeddings(),
        model=_routing_model(),
        content=ArchiveAwareContent(),
        fast_paths=[ArchivedWindowPath()],
        include_archived=False,
    )

    [evidence] = answer.used_component_evidence
    assert [c.document_path for c in evidence.claims] == [LIVE_DOC]
    assert evidence.windows == ()


# ------------------------------- an empty archive: the whole mechanism is inert (§3)


#: A store that KNOWS the archive and reports none — the state every library starts in and
#: most stay in. Not the same fake as `BlindContent`, which lacks the method entirely: this
#: one answers the question, and the answer is "nothing has been archived".
def _no_archive() -> ArchiveAwareContent:
    return ArchiveAwareContent(archived=())


#: A claim on a page NO document set below contains. In a library with an archive this is
#: the stale L3 row the pin exists to drop; in a library WITHOUT one it is an ordinary
#: index/canonical race — a page compiled while this answer was being assembled, or an index
#: searched live under a past-version `at=` pin — and dropping it is a regression the Owner
#: would see as an answer that used to be given and now is not.
def _off_set_claims() -> list[ClaimStub]:
    return _stale_claims()


async def test_with_an_empty_archive_the_pin_is_off_on_every_lane():
    """NOTHING ARCHIVED, NOTHING DIFFERENT — on every lane and on every code path.

    The archive filter is a no-op over an empty view everywhere by construction except one
    place: the `live_paths` pin, which drops a claim whose page the lane's own document set
    does not hold. That drop is correct only while there is a window between an archive
    commit and the L3 sync behind it. With nothing ever archived there is no such window, so
    the pin does not run — and the Owner who archived nothing can compare an answer from
    before and after this feature and find no difference (`archive_filter._pin`).

    Each lane below is HANDED a document set (so `live_paths` is a real set, not None) and a
    store that reports no archived source, and each is asked about a claim on a page that set
    does not contain. Every one of them must answer with it."""
    # ── fast
    answer = await _fast_over(
        _off_set_claims(),
        documents=[LIVE_PAGE],
        include_archived=False,
        content=_no_archive(),
    )
    assert [c.document_path for c in answer.used_claims] == [MOVED_LIVE_PATH]
    retrieve = next(st for st in answer.stages if st.name == "retrieve")
    assert "archive_hidden" not in (retrieve.preview or {}), "nothing reported as hidden"

    # ── fast, `include_archived=True` over the same empty archive. The opt-in path runs the
    # pin on its own (`pin_claims`), so it is the one that failed for a caller who asked for
    # an archive their library does not have.
    admitted = await _fast_over(
        _off_set_claims(),
        documents=[LIVE_PAGE],
        include_archived=True,
        content=_no_archive(),
    )
    assert [c.document_path for c in admitted.used_claims] == [MOVED_LIVE_PATH]

    # ── deep: the seed AND the loop's own `search_claims`, which re-retrieves.
    deep_answer = await _deep(
        include_archived=False,
        documents=[LIVE_PAGE],
        content=_no_archive(),
        claims=_off_set_claims(),
        turns=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_claims", "args": {"query": "aurora"}, "id": "t1"}
                ],
            ),
            AIMessage(content="done"),
        ],
    )
    assert [c.document_path for c in deep_answer.used_claims] == [MOVED_LIVE_PATH]
    step = next(s for s in deep_answer.trail if s["tool"] == "search_claims")
    assert step["hits"] == 1 and "archive_hidden" not in step

    # ── rag. It holds no document set at all, so it has no pin surface to turn off; the
    # assertion is that the lane is untouched — every hit the two blind indexes proposed
    # stands, because no source is archived.
    lexical, vectors = _rag_indexes()
    hits = await rag_recall(
        _USER,
        "aurora",
        lexical=lexical,
        vectors=vectors,
        embeddings=FakeEmbeddings(),
        content=_no_archive(),
    )
    assert {str(h.source_id) for h in hits} == {LIVE_SOURCE, ARCHIVED_SOURCE}
    assert all(h.archived is False for h in hits)

    # ── briefing build. Its pin is the snapshot's own pages and is NEVER None, so an
    # inactive view is the only thing that can keep an off-snapshot claim in the pack.
    index = BlindClaimIndex(_off_set_claims())
    pack = await build_briefing(
        _USER,
        BriefingScope(query="aurora"),
        snapshot=SnapshotRef(ref="sha-1"),
        snapshot_docs=[LIVE_PAGE],
        content=_no_archive(),
        claim_lexical=index,
        claim_vectors=index,
        embeddings=FakeEmbeddings(),
    )
    assert "Aurora shipped in June" in pack.system_prefix
    assert pack.claims_count == 1

    # ── live context. Same shape: a tree was handed, and the claim names a page outside it.
    from test_live_pipeline import (  # noqa: E402
        FakeClaimVectors,
        FakeStructured,
        discovered,
        other,
        semantic_plan,
    )
    from pneuma_knowledge_core.domain.suggestion import PickResult
    from pneuma_knowledge_core.recall.live_pipeline import evaluate_live_pipeline

    class OffSet:
        async def search_claims(self, user_id, query, *, limit=40):  # noqa: ANN001
            return _off_set_claims()[:limit]

    tick = await evaluate_live_pipeline(
        _USER,
        [other("aurora 现在到哪一步了？")],
        as_of=_AS_OF,
        discover_model=FakeStructured(
            [discovered(intent="aurora status", plan=semantic_plan("aurora"), worth=9)]
        ),
        pick_model=FakeStructured(
            [PickResult(choice=1, lede="六月发布了。", citations=[1], confidence=9)]
        ),
        embeddings=FakeEmbeddings(),
        claim_lexical=OffSet(),
        claim_vectors=FakeClaimVectors(),
        content=_no_archive(),
        documents=[LIVE_PAGE],
    )
    assert tick.dropped.get("archived") is None, "nothing was hidden from the room"
    assert any(
        "Aurora shipped in June" in card.body for card in tick.candidates
    ), "the claim reached the pick stage"


async def test_the_pin_turns_on_with_the_first_archived_document_or_source():
    """Two triggers, either sufficient — the two authoritative marks (archive.md §2).

    The mechanism has to switch ON the moment there is something to protect, and there are
    two independent ways for that to become true: an L0 source with `archived_at`, and a
    canonical document under `archive/`. The lane learns the first from the store and the
    second from the caller that listed the full tree, because the live set it is handed looks
    identical either way."""
    # ── trigger 1: one archived SOURCE. Nothing in canonical is archived here.
    by_source = await _fast_over(
        _off_set_claims(),
        documents=[LIVE_PAGE],
        include_archived=False,
        content=ArchiveAwareContent(),  # reports ARCHIVED_SOURCE
    )
    assert by_source.used_claims == (), "the pin ran"
    retrieve = next(st for st in by_source.stages if st.name == "retrieve")
    assert retrieve.preview["archive_hidden"] == 1

    # ── trigger 2: one archived DOCUMENT, stated by the caller. No archived source at all,
    # and the document set handed to the lane is entirely live — which is exactly why the
    # flag has to be passed rather than inferred.
    by_document = await _fast_over(
        _off_set_claims(),
        documents=[LIVE_PAGE],
        include_archived=False,
        content=_no_archive(),
        archive_active=True,
    )
    assert by_document.used_claims == ()

    # ── and deep takes the same flag, so the loop's own re-retrieval is pinned too.
    deep_answer = await _deep(
        include_archived=False,
        documents=[LIVE_PAGE],
        content=_no_archive(),
        claims=_off_set_claims(),
        archive_active=True,
        turns=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "search_claims", "args": {"query": "aurora"}, "id": "t1"}
                ],
            ),
            AIMessage(content="done"),
        ],
    )
    assert deep_answer.used_claims == ()
    step = next(s for s in deep_answer.trail if s["tool"] == "search_claims")
    assert step["hits"] == 0 and step["archive_hidden"] == 1


async def test_the_view_states_both_triggers_and_nothing_else():
    """`ArchiveView.active`, alone, so the switch is readable without running a lane."""
    from pneuma_knowledge_core.domain.archive import ArchiveView, any_archived
    from pneuma_knowledge_core.recall.archive_filter import filter_claims, pin_claims

    assert ArchiveView.empty().active is False
    assert ArchiveView(sources=frozenset({SourceId(ARCHIVED_SOURCE)})).active is True
    assert ArchiveView(documents_archived=True).active is True

    # `any_archived` is what the service reads it off, and it reads the FULL tree.
    assert any_archived([LIVE_PAGE]) is False
    assert any_archived([LIVE_PAGE, ARCHIVED_PAGE]) is True

    # And the two functions that hold the pin agree about it.
    claims = _off_set_claims()
    pinned = frozenset({LIVE_DOC})
    assert filter_claims(claims, ArchiveView.empty(), live_paths=pinned) == (claims, 0)
    assert pin_claims(claims, pinned, ArchiveView.empty()) == (claims, 0)
    assert filter_claims(
        claims, ArchiveView(documents_archived=True), live_paths=pinned
    ) == ([], 1)
    assert pin_claims(claims, pinned, ArchiveView(documents_archived=True)) == ([], 1)


async def test_the_live_lane_learns_the_flag_from_the_read_that_loads_the_tree():
    """`load_documents` is awaited late, so the flag rides back on it (`LoadedDocuments`).

    The live lane reads canonical only once a tick has a real plan — a skip is its steady
    state and must stay free — so it cannot be told at call time what a read it has not made
    yet will find. The loader answers both questions at once, and a loader that returns a
    plain sequence (every pre-archive caller) reads as "no archive"."""
    from test_live_pipeline import (  # noqa: E402
        FakeClaimVectors,
        FakeStructured,
        discovered,
        other,
        semantic_plan,
    )
    from pneuma_knowledge_core.domain.archive import LoadedDocuments
    from pneuma_knowledge_core.domain.suggestion import PickResult
    from pneuma_knowledge_core.recall.live_pipeline import evaluate_live_pipeline

    class OffSet:
        async def search_claims(self, user_id, query, *, limit=40):  # noqa: ANN001
            return _stale_claims()[:limit]

    async def run(loader):
        return await evaluate_live_pipeline(
            _USER,
            [other("aurora 现在到哪一步了？")],
            as_of=_AS_OF,
            discover_model=FakeStructured(
                [discovered(intent="aurora status", plan=semantic_plan("aurora"), worth=9)]
            ),
            pick_model=FakeStructured(
                [PickResult(choice=1, lede="六月发布了。", citations=[1], confidence=9)]
            ),
            embeddings=FakeEmbeddings(),
            claim_lexical=OffSet(),
            claim_vectors=FakeClaimVectors(),
            content=_no_archive(),
            load_documents=loader,
        )

    async def plain():
        return [LIVE_PAGE]

    async def with_an_archive():
        return LoadedDocuments([LIVE_PAGE], True)

    assert (await run(plain)).dropped.get("archived") is None
    assert (await run(with_an_archive)).dropped.get("archived") == 1
