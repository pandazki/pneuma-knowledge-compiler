"""`include_archived` on the recall routes: it reaches the lane, the documents, and the echo.

The lanes themselves are covered against fake ports in core (`test_archive_recall.py`). What
could silently go wrong HERE is the wiring: a flag that reaches `fast_recall` but not the
document set would show an archived claim under a glance that does not list its page, and a
flag that reaches neither would answer out of the archive while the response says it did not.
So these tests monkeypatch the lanes and assert exactly the three hand-offs.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_service.api.routes import v1 as v1_module
from pneuma_knowledge_service.api.routes.v1 import RecallIn, recall

from test_kb_snapshot_routes import OWNER, _FakeFastAnswer, _request, _row

LIVE_DOC = "memory/projects/aurora-next.md"
ARCHIVED_DOC = "archive/memory/projects/aurora.md"


def _doc(path: str) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(path.replace("/", "-")),
        path=path,
        frontmatter={"title": path.rsplit("/", 1)[-1]},
        body="# page\n\n- a claim.\n",
    )


@pytest.fixture
def captured(monkeypatch):
    """What each lane was handed, plus the canonical documents that reached it."""
    seen: dict = {}

    #: The RAW keyword, kept beside the paths: `[]` and "never handed one" are different
    #: instructions to the lane (core `recall/archive_filter._off_pin`) and `or ()` renders
    #: them identically, so the distinction is captured before it is flattened.
    absent = object()

    async def fake_fast_recall(user, question, **kwargs):  # noqa: ANN001
        seen["include_archived"] = kwargs.get("include_archived")
        seen["archive_active"] = kwargs.get("archive_active", absent)
        seen["documents_arg"] = kwargs.get("documents", absent)
        seen["documents_absent"] = seen["documents_arg"] is absent
        seen["documents"] = [d.path for d in (kwargs.get("documents") or ())]
        return _FakeFastAnswer()

    async def fake_deep_recall(user, question, **kwargs):  # noqa: ANN001
        seen["include_archived"] = kwargs.get("include_archived")
        seen["archive_active"] = kwargs.get("archive_active", absent)
        seen["documents_arg"] = kwargs.get("documents", absent)
        seen["documents_absent"] = seen["documents_arg"] is absent
        seen["documents"] = [d.path for d in (kwargs.get("documents") or ())]
        return SimpleNamespace(
            answer="答案",
            used_claims=(),
            used_windows=(),
            trail=(),
            glance_chars=0,
            read_documents=(),
            image_count=0,
            image_mode="caption",
            stages=(),
            token_usage={"total_tokens": 1},
        )

    async def fake_rag_recall(user, query, **kwargs):  # noqa: ANN001
        seen["include_archived"] = kwargs.get("include_archived")
        seen["content"] = kwargs.get("content", "<not passed>")
        return []

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    monkeypatch.setattr(v1_module, "deep_recall", fake_deep_recall)
    monkeypatch.setattr(v1_module, "rag_recall", fake_rag_recall)
    monkeypatch.setattr(v1_module, "_render_profile", lambda ctx, user: _none())
    return seen


async def _none():
    return None


def _with_documents():
    """The snapshot-route request stub, with a live page and an archived one in canonical."""
    request = _request(_row())
    ctx = request.app.state.ctx
    reads = ctx.canonical_reads

    async def canonical_list(user, *, at=None):  # noqa: ANN001
        reads.append((str(user), at))
        return [_doc(LIVE_DOC), _doc(ARCHIVED_DOC)]

    ctx.canonical = SimpleNamespace(snapshots=ctx.canonical.snapshots, list=canonical_list)
    return request


def _with_only_live_documents():
    """A library that has never archived anything — the state every library starts in."""
    request = _request(_row())
    ctx = request.app.state.ctx
    reads = ctx.canonical_reads

    async def canonical_list(user, *, at=None):  # noqa: ANN001
        reads.append((str(user), at))
        return [_doc(LIVE_DOC)]

    ctx.canonical = SimpleNamespace(snapshots=ctx.canonical.snapshots, list=canonical_list)
    return request


def _with_only_archived_documents():
    """Canonical holds pages, and the Owner archived every one of them."""
    request = _request(_row())
    ctx = request.app.state.ctx
    reads = ctx.canonical_reads

    async def canonical_list(user, *, at=None):  # noqa: ANN001
        reads.append((str(user), at))
        return [_doc(ARCHIVED_DOC)]

    ctx.canonical = SimpleNamespace(snapshots=ctx.canonical.snapshots, list=canonical_list)
    return request


def _with_an_empty_library():
    """Canonical holds nothing at all, and nothing was ever archived."""
    request = _request(_row())
    ctx = request.app.state.ctx
    reads = ctx.canonical_reads

    async def canonical_list(user, *, at=None):  # noqa: ANN001
        reads.append((str(user), at))
        return []

    ctx.canonical = SimpleNamespace(snapshots=ctx.canonical.snapshots, list=canonical_list)
    return request


def _with_a_broken_canonical():
    """The read itself fails — and the answering lane refuses rather than running unpinned."""
    request = _request(_row())
    ctx = request.app.state.ctx

    async def canonical_list(user, *, at=None):  # noqa: ANN001
        raise RuntimeError("git is busy")

    ctx.canonical = SimpleNamespace(snapshots=ctx.canonical.snapshots, list=canonical_list)
    return request


def _client(request):
    """The same stub ctx behind a REAL app, so a refusal can be read as a status code.

    The route tests above call the handler directly, which is enough while the answer is an
    object. A refusal is not — its whole content is the status and the machine code the
    `ArchiveRequestError` handler in `api/app.py` renders — so those two assertions have to
    be made through the app that renders them."""
    import httpx
    from pneuma_knowledge_service.api.app import create_app

    app = create_app()
    app.state.ctx = request.app.state.ctx
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_a_library_whose_every_page_is_archived_hands_the_lane_an_EMPTY_set(captured):
    """`_glance_inputs` yields `[]`, never None and never nothing.

    This is the whole of the empty-set finding at the service door. The lane reads "not
    handed a set" as "pin nothing", so omitting the keyword here would let a stale L3 row —
    one still carrying the archived page's old live path — answer as though it were live, in
    exactly the library where every row is stale by construction."""
    out = await recall(OWNER, RecallIn(query="q", mode="fast"), _with_only_archived_documents())

    assert captured["documents_absent"] is False, "the keyword was handed over"
    assert captured["documents_arg"] == [], "and it is an empty LIST, not None"
    assert out.include_archived is False


@pytest.mark.parametrize("mode", ["fast", "deep"])
async def test_an_empty_library_with_no_archive_keeps_the_pre_archive_shape(captured, mode):
    """The owner's rule: nothing archived, nothing different. Before the archive existed an
    empty library handed the lane NO `documents` keyword and no glance; that exact shape is
    kept, byte for byte, when the tree is empty AND no archive stands beside it. The empty
    list above is handed only because an archive does."""
    await recall(OWNER, RecallIn(query="q", mode=mode), _with_an_empty_library())

    assert captured["documents_absent"] is True, "no keyword, as before the archive existed"
    assert captured["archive_active"] is not True, "and no archive was reported"


async def test_deep_is_handed_the_same_empty_set(captured):
    await recall(
        OWNER, RecallIn(query="q", mode="deep"), _with_only_archived_documents()
    )

    assert captured["documents_absent"] is False
    assert captured["documents_arg"] == []


@pytest.mark.parametrize("mode", ["fast", "deep"])
@pytest.mark.parametrize("path", ["recall", "recall/stream"])
async def test_a_failed_canonical_read_refuses_the_answering_lane(captured, mode, path):
    """FAIL CLOSED. The pin is a correctness boundary, so an unreadable library is a refusal.

    The glance used to be advisory all the way down: a canonical store that was down degraded
    to the retrieval-only prompt. It cannot any more. The document set is what admits an
    index claim (`archive_filter._off_pin`), so a lane handed none pins nothing and every
    stale L3 row — a moved page's rows still carrying its old live path — answers as though
    it were live, with nothing in the response to say so. "Fail the lane rather than answer
    out of the archive" is the rule (docs/design/archive.md §3), and it holds on the stream
    too: canonical is read before the response opens, so the refusal is a status code there
    and not an `error` frame narrated over a 200 that was already sent."""
    async with _client(_with_a_broken_canonical()) as client:
        out = await client.post(
            f"/v1/users/{OWNER}/{path}", json={"query": "q", "mode": mode}
        )

    assert out.status_code == 503, out.text
    body = out.json()
    assert body["code"] == "canonical_unavailable"
    assert "git is busy" in body["detail"], "the cause is named, not swallowed"
    assert captured == {}, "and no lane ran at all"


@pytest.mark.parametrize("mode", ["fast", "deep"])
async def test_skill_load_failure_still_hands_documents(captured, monkeypatch, mode):
    """The OTHER half of `_glance_inputs`, and it is still fail-soft.

    Only the canonical read is the boundary. The composed skill and the raw packs are the
    glance's decoration — losing them costs the family lines above the outline and nothing
    else — so a lane still gets its documents, still pins to them, and still answers."""

    async def broken(ctx, user):  # noqa: ANN001, ARG001
        raise RuntimeError("skill store is down")

    monkeypatch.setattr(v1_module, "skill_for_user", broken)
    monkeypatch.setattr(v1_module, "packs_for_user", broken)

    await recall(OWNER, RecallIn(query="q", mode=mode), _with_documents())

    assert captured["documents_absent"] is False, "the pin survives a lost skill"
    assert captured["documents"] == [LIVE_DOC]


async def test_the_default_recall_is_a_live_one_and_says_so(captured):
    out = await recall(OWNER, RecallIn(query="q", mode="fast"), _with_documents())

    assert captured["include_archived"] is False
    assert captured["documents"] == [LIVE_DOC], "the archived page never reaches the lane"
    assert out.include_archived is False


async def test_asking_for_the_archive_reaches_the_lane_and_the_document_set(captured):
    out = await recall(
        OWNER,
        RecallIn(query="q", mode="fast", include_archived=True),
        _with_documents(),
    )

    assert captured["include_archived"] is True
    assert captured["documents"] == [LIVE_DOC, ARCHIVED_DOC]
    assert out.include_archived is True


async def test_the_episode_summary_face_carries_its_archive_flag_onto_the_wire(
    captured, monkeypatch
):
    """The derived-summary face says on the wire what it says in the prompt.

    `EpisodeSummaryOut` is the response model, so a field it does not declare is STRIPPED by
    FastAPI — the flag reached the answer object and died at the door, and a client rendering
    `used_episode_summaries` showed a paraphrase of retired material beside a live one with
    nothing to tell them apart. Default `False` keeps every pre-archive client, fixture and
    lane (which may hand back a summary object with no such attribute at all) unchanged."""

    async def fake_fast_recall(user, question, **kwargs):  # noqa: ANN001, ARG001
        return _FakeFastAnswer(
            used_episode_summaries=(
                SimpleNamespace(
                    source_id="src-live",
                    block_start=1,
                    block_end=2,
                    text="live summary",
                    score=0.9,
                    source_title="live",
                    source_occurred_on="2026-06-01",
                    section_path=(),
                    archived=False,
                ),
                SimpleNamespace(
                    source_id="src-old",
                    block_start=3,
                    block_end=4,
                    text="archived summary",
                    score=0.8,
                    source_title="old",
                    source_occurred_on="2025-01-01",
                    section_path=(),
                    archived=True,
                ),
                # A lane, fixture or component written before the flag existed: no attribute
                # at all, and it reads as live rather than raising.
                SimpleNamespace(
                    source_id="src-legacy",
                    block_start=5,
                    block_end=6,
                    text="legacy summary",
                    score=0.7,
                    source_title="legacy",
                    source_occurred_on="2024-01-01",
                    section_path=(),
                ),
            )
        )

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    out = await recall(
        OWNER,
        RecallIn(query="q", mode="fast", include_archived=True),
        _with_documents(),
    )

    assert [(s.source_id, s.archived) for s in out.used_episode_summaries] == [
        ("src-live", False),
        ("src-old", True),
        ("src-legacy", False),
    ]
    # …and it survives the response model rather than being validated away.
    assert out.model_dump()["used_episode_summaries"][1]["archived"] is True


async def test_an_admitted_archived_claim_says_archived_on_the_wire(captured, monkeypatch):
    """The claim face carries the mark under the SAME name as the other two.

    The label was on the wire inside `labels`, and only there: a client reading one response
    got `archived: true` on a window and on an episode summary, and on a claim got a list it
    had to know to look inside — so the console beside this one ended up telling the two
    apart by the `archive/` prefix on `document_path`, a second implementation of the one
    rule the assembly filter owns (validation B-S9-1). The field is DERIVED from the label
    and never from the path: `mark_archived_claims` is the only authority on what was
    admitted out of the archive."""

    async def fake_fast_recall(user, question, **kwargs):  # noqa: ANN001, ARG001
        return _FakeFastAnswer(
            used_claims=(
                SimpleNamespace(
                    anchor="c:aaaa0001",
                    document_path=LIVE_DOC,
                    section_path=(),
                    text="a live claim.",
                    citations=(),
                    paths=("vector",),
                    score=0.9,
                    labels=(),
                ),
                SimpleNamespace(
                    anchor="c:bbbb0002",
                    document_path=ARCHIVED_DOC,
                    section_path=(),
                    text="an archived claim.",
                    citations=(),
                    paths=("lexical",),
                    score=0.8,
                    labels=("archived",),
                ),
                # A component face, a fixture or a lane written before the label existed:
                # no `labels` attribute at all, and it reads as live rather than raising.
                SimpleNamespace(
                    anchor="c:cccc0003",
                    document_path=LIVE_DOC,
                    section_path=(),
                    text="a legacy claim.",
                    citations=(),
                    paths=("vector",),
                    score=0.7,
                ),
            ),
        )

    monkeypatch.setattr(v1_module, "fast_recall", fake_fast_recall)
    out = await recall(
        OWNER,
        RecallIn(query="q", mode="fast", include_archived=True),
        _with_documents(),
    )

    assert [(c.anchor, c.archived) for c in out.used_claims] == [
        ("c:aaaa0001", False),
        ("c:bbbb0002", True),
        ("c:cccc0003", False),
    ]
    # The label stays where it was — this adds a name, it does not move one.
    assert out.used_claims[1].labels == ["archived"]
    # …and both survive the response model rather than being validated away.
    claim = out.model_dump()["used_claims"][1]
    assert claim["archived"] is True and claim["labels"] == ["archived"]


async def test_deep_carries_the_same_flag_and_the_same_document_set(captured):
    out = await recall(
        OWNER,
        RecallIn(query="q", mode="deep", include_archived=True),
        _with_documents(),
    )

    assert captured["include_archived"] is True
    assert captured["documents"] == [LIVE_DOC, ARCHIVED_DOC]
    assert out.include_archived is True


async def test_rag_carries_the_flag_to_the_indexes_and_echoes_it(captured):
    out = await recall(
        OWNER,
        RecallIn(query="q", mode="rag", include_archived=True),
        _with_documents(),
    )

    assert captured["include_archived"] is True
    assert out.include_archived is True


async def test_rag_is_handed_the_store_so_the_lane_can_filter_at_assembly(captured):
    """The wiring for rag's SECOND half of the archive rule.

    The two index filters are a flag on rows in Meilisearch and Qdrant, flipped by a write
    that can fail; without the store the lane has no way to check them and a default answer
    would carry the archive with the response saying it did not. `content` is what turns
    that from a property of two backends into a property of the code, and it is passed on
    BOTH rag routes because the stream route runs through this same helper."""
    request = _with_documents()
    store = request.app.state.ctx.store

    for body in (
        RecallIn(query="q", mode="rag"),
        RecallIn(query="q", mode="rag", include_archived=True),
    ):
        await recall(OWNER, body, request)
        assert captured["content"] is store, "the lane cannot read a mark it was never handed"


# ---------------------------------------------------------------- briefings: the scope


async def test_the_briefing_scope_stores_the_choice_and_every_ask_inherits_it(monkeypatch):
    """A pack is built once and asked over many times, so the choice belongs to the SCOPE.

    An ask that could reach into the archive over a pack built without it would answer half
    out of the present and half out of the past, with nothing in the text to say which."""
    import httpx
    from pneuma_knowledge_core.recall.briefing import AskAnswer
    from pneuma_knowledge_service.api.app import create_app

    from test_briefing_pack_manifest_route import OWNER as PACK_OWNER
    from test_briefing_pack_manifest_route import SOURCE, _Canonical, _Store

    seen: dict = {}

    async def fake_ask(briefing, question, **kwargs):  # noqa: ANN001, ARG001
        seen["include_archived"] = briefing.include_archived
        return AskAnswer(answer="ok", citations=(), verbatim_fetches=(), token_usage={})

    monkeypatch.setattr(v1_module, "briefing_ask", fake_ask)
    monkeypatch.setattr(v1_module, "_render_profile", lambda ctx, user: _none())

    store = _Store()
    app = create_app()
    app.state.ctx = SimpleNamespace(
        store=store,
        canonical=_Canonical(),
        lexical=None,
        vectors=None,
        embeddings=None,
        settings=SimpleNamespace(briefing_citation_alias=False),
        user_info=SimpleNamespace(get_profile=None),
        get_chat_model=lambda role: None,
        langfuse_handler=lambda: None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        built = await client.post(
            f"/v1/users/{PACK_OWNER}/briefings",
            json={"source_ids": [SOURCE], "include_archived": True},
        )
        briefing_id = built.json()["briefing_id"]
        asked = await client.post(
            f"/v1/users/{PACK_OWNER}/briefings/{briefing_id}/ask",
            json={"question": "?"},
        )

    assert asked.status_code == 200, asked.text
    assert store.created[0]["scope"]["include_archived"] is True
    assert seen["include_archived"] is True


async def test_a_briefing_stored_before_the_key_existed_reads_back_as_a_live_pack(monkeypatch):
    """No backfill and no guess: a row with no `include_archived` was built without one."""
    import httpx
    from pneuma_knowledge_core.recall.briefing import AskAnswer
    from pneuma_knowledge_service.api.app import create_app

    from test_briefing_pack_manifest_route import BRIEFING_ID, PACK
    from test_briefing_pack_manifest_route import OWNER as PACK_OWNER
    from test_briefing_pack_manifest_route import SOURCE, _Canonical, _Store

    seen: dict = {}

    async def fake_ask(briefing, question, **kwargs):  # noqa: ANN001, ARG001
        seen["include_archived"] = briefing.include_archived
        return AskAnswer(answer="ok", citations=(), verbatim_fetches=(), token_usage={})

    monkeypatch.setattr(v1_module, "briefing_ask", fake_ask)
    monkeypatch.setattr(v1_module, "_render_profile", lambda ctx, user: _none())

    store = _Store(
        {
            (PACK_OWNER, BRIEFING_ID): {
                "briefing_id": BRIEFING_ID,
                "scope": {"source_ids": [SOURCE]},
                "snapshot_ref": "9f1c2d",
                "system_prefix": PACK,
                "created_at": None,
                "stages": [],
            }
        }
    )
    app = create_app()
    app.state.ctx = SimpleNamespace(
        store=store,
        canonical=_Canonical(),
        lexical=None,
        vectors=None,
        embeddings=None,
        settings=SimpleNamespace(briefing_citation_alias=False),
        user_info=SimpleNamespace(get_profile=None),
        get_chat_model=lambda role: None,
        langfuse_handler=lambda: None,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        asked = await client.post(
            f"/v1/users/{PACK_OWNER}/briefings/{BRIEFING_ID}/ask", json={"question": "?"}
        )

    assert asked.status_code == 200, asked.text
    assert seen["include_archived"] is False


# --------------------------------- the flag that makes the whole filter inert (§3)


@pytest.mark.parametrize("mode", ["fast", "deep"])
async def test_the_lane_is_told_whether_this_library_has_an_archive_at_all(captured, mode):
    """`_glance_inputs` is the ONE read that sees the full tree, so it is the only place the
    fact can be established — and it has to be handed on, because the live document set the
    lane receives looks identical either way.

    It is what turns the assembly filter's document pin on. With nothing ever archived the
    filter is inert and the lane answers byte-for-byte as it did before the archive existed
    (core `recall/archive_filter._pin`); the first archived page turns it on."""
    await recall(OWNER, RecallIn(query="q", mode=mode), _with_only_live_documents())
    assert captured["archive_active"] is False, "nothing archived, nothing pinned"

    await recall(OWNER, RecallIn(query="q", mode=mode), _with_documents())
    assert captured["archive_active"] is True, "one page under archive/ is enough"
    assert captured["documents"] == [LIVE_DOC], "and the lane still sees only live pages"


async def test_the_flag_is_read_before_the_archive_is_filtered_out_of_the_set(captured):
    """The order is the whole mechanism: after `live_documents` there is nothing left to see.

    A library whose every page the Owner archived is the case that proves it — the lane is
    handed `[]`, which says nothing about an archive, and the flag is the only thing that
    still does."""
    await recall(
        OWNER, RecallIn(query="q", mode="fast"), _with_only_archived_documents()
    )

    assert captured["documents"] == []
    assert captured["archive_active"] is True


async def test_asking_for_the_archive_does_not_change_what_the_flag_reports(captured):
    """`include_archived` says which plane to answer over; the flag says whether there is a
    second plane at all. They are different questions and one must not stand in for the
    other — an opt-in call in a library with nothing archived asked for nothing, and must get
    the answer it got before this feature existed."""
    await recall(
        OWNER,
        RecallIn(query="q", mode="fast", include_archived=True),
        _with_only_live_documents(),
    )

    assert captured["include_archived"] is True
    assert captured["archive_active"] is False


async def test_the_briefing_build_reads_the_flag_off_its_own_snapshot(monkeypatch):
    """A pack pins to the snapshot it was built from, so that snapshot answers the question.

    The build reads canonical itself (its set is `at=`-pinned) and filters the archive out of
    it before handing it on, so the flag has to be taken BEFORE that filter — after it, an
    archived document is exactly the one thing that is gone."""
    from test_live_stage_streams import _FakeStore
    from test_live_stage_streams import _request as _stream_request
    from pneuma_knowledge_service.api.routes.v1 import BriefingBuildIn, post_briefing

    seen: dict = {}

    class _Briefing:
        system_prefix = "contract\npack"
        claims_count = 0
        source_count = 0
        stages = ()
        include_archived = False
        char_count = 0
        pack_manifest = ()

    async def fake_build(user, scope, **kwargs):  # noqa: ANN001
        seen["archive_active"] = kwargs.get("archive_active")
        seen["snapshot_docs"] = [d.path for d in kwargs.get("snapshot_docs") or ()]
        return _Briefing()

    monkeypatch.setattr(v1_module, "build_briefing", fake_build)

    def request_over(docs):
        request = _stream_request(_FakeStore())
        async def listing(user, at=None):  # noqa: ANN001, ARG001
            return docs
        request.app.state.ctx.canonical = SimpleNamespace(
            snapshots=request.app.state.ctx.canonical.snapshots, list=listing
        )
        return request

    await post_briefing(OWNER, BriefingBuildIn(query="q"), request_over([_doc(LIVE_DOC)]))
    assert seen["archive_active"] is False
    assert seen["snapshot_docs"] == [LIVE_DOC]

    await post_briefing(
        OWNER,
        BriefingBuildIn(query="q"),
        request_over([_doc(LIVE_DOC), _doc(ARCHIVED_DOC)]),
    )
    assert seen["archive_active"] is True
    assert seen["snapshot_docs"] == [LIVE_DOC], "the pack itself still holds live pages only"
