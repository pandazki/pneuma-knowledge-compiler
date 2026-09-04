"""AI suggestion service plumbing: briefing-pack stripping, model routing, want_more, vocabulary.

The parts of Stage 2 that are neither session policy nor transport — each one a place
where the service is responsible for something core deliberately refuses to do.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from pneuma_knowledge_core.domain.suggestion import CONTEXT_FOCUSES, SUGGESTION_KINDS
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.recall.briefing import briefing_contract
from pneuma_knowledge_service.adapters.scripted_model import ScriptedChatModel
from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.api.routes.live_context import OUTBOUND_LIMIT, put_drop_oldest
from pneuma_knowledge_service.live_context.engine import briefing_pack, expand_suggestion, run_evaluation
from pneuma_knowledge_service.live_context.session import LiveContextPolicy, LiveContextSession
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import resolve_model_name
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

SRC = "11111111-1111-1111-1111-111111111111"


# ------------------------------------------------------- the briefing pack prefix


PACK = "# 检索知识（scope.query）\n- 某条 claim 注记"


def stored_prefix(pack: str = PACK) -> str:
    """Exactly what `build_briefing` persists (briefing.py:328)."""
    return briefing_contract() + "\n" + pack + "\n" if pack else briefing_contract()


def test_the_stored_briefing_contract_is_stripped_off_the_pack():
    """core takes `pack` as DATA for the Human turn. Handing it the stored `system_prefix`
    whole would paste a second, contradictory contract underneath the suggestion contract: a Q&A
    posture, two tools that are not bound on this call, and the 「无相关记录」 close that
    the suggestion contract exists specifically to replace."""
    assert briefing_pack(stored_prefix()) == PACK

    # The strip has to be total — no fragment of the contract may survive into the pack.
    stripped = briefing_pack(stored_prefix())
    assert "# Pneuma 个人记忆会话" not in stripped
    assert "search_knowledge" not in stripped
    assert "无相关记录" not in stripped
    assert briefing_contract()[:200] not in stripped


def test_a_prefix_that_is_not_contract_prefixed_is_returned_unchanged():
    """An older or hand-written briefing is all pack as far as we can tell, and guessing
    at a boundary that is not there would eat real evidence."""
    assert briefing_pack("just a pack") == "just a pack"


def test_an_empty_pack_is_the_empty_string_never_none():
    """`pack is None` means "full scope, go retrieve" in core; `pack == ""` means
    "briefing scope that happens to be empty, retrieve nothing". A briefing with no pack
    must stay in briefing scope — turning it into a retrieval round is the opposite of
    what the caller asked for."""
    empty = briefing_pack(stored_prefix(""))
    assert empty == ""
    assert empty is not None


async def test_load_briefing_pack_strips_what_the_store_returns():
    """The strip happens on the way OUT of the store, so no caller can forget it."""
    from pneuma_knowledge_service.live_context.engine import load_briefing_pack

    async def get_briefing(user, bid):  # noqa: ANN001
        return {"system_prefix": stored_prefix()} if bid == "bf-1" else None

    ctx = SimpleNamespace(store=SimpleNamespace(get_briefing=get_briefing))
    assert await load_briefing_pack(ctx, "u-1", "bf-1") == PACK
    with pytest.raises(KeyError, match="briefing not found"):
        await load_briefing_pack(ctx, "u-1", "missing")


# ------------------------------------------------------------------ model routing


def test_the_live_context_role_falls_back_to_the_recall_model():
    """Live Context is single-shot and latency-shaped like fast recall, so a deployment that has
    already pointed recall at a fast model should not have to say it twice."""
    s = Settings(llm_model="openai:base", llm_model_recall="openrouter:fast-test")
    assert resolve_model_name(s, "live_context") == "openrouter:fast-test"


def test_the_two_pipeline_roles_fall_back_to_recall_and_can_be_split_off():
    """Both new roles borrow `recall` when unset, so an existing deployment keeps working
    without naming two more models; naming one wins."""
    borrowed = Settings(llm_model="openai:base", llm_model_recall="openrouter:fast-test")
    assert resolve_model_name(borrowed, "live_discover") == "openrouter:fast-test"
    assert resolve_model_name(borrowed, "live_pick") == "openrouter:fast-test"

    split = Settings(
        llm_model="openai:base",
        llm_model_recall="openrouter:fast-test",
        llm_model_live_discover="openrouter:small-reasoning",
        llm_model_live_pick="openrouter:weak-fast",
    )
    assert resolve_model_name(split, "live_discover") == "openrouter:small-reasoning"
    assert resolve_model_name(split, "live_pick") == "openrouter:weak-fast"


def test_a_pinned_reasoning_effort_forks_the_model_cache(monkeypatch):
    """`live_pick` and `recall` routinely resolve to the SAME spec, and the model cache is
    keyed by spec. Without the effort in that key, whichever role built first would silently
    hand the other its reasoning setting — which is the one property these roles differ on."""
    from pneuma_knowledge_service import wiring

    built: list[tuple[str, str | None]] = []

    def fake_build(name, settings, *, reasoning_effort=None, max_tokens=None):  # noqa: ANN001
        built.append((name, reasoning_effort))
        return object()

    monkeypatch.setattr(wiring, "_build_from_name", fake_build)
    ctx = SimpleNamespace(
        settings=Settings(llm_model="openai:one-model"),
        _chat_models={},
        get_chat_model=None,
    )
    # Bind the real method to a bare namespace: this is about the cache key, not the context.
    get = wiring.AppContext.get_chat_model.__get__(ctx, wiring.AppContext)
    discover, pick, recall = get("live_discover"), get("live_pick"), get("recall")

    assert built == [
        ("openai:one-model", "low"),
        ("openai:one-model", "none"),
        ("openai:one-model", None),
    ], "one spec, three distinct instances — the effort is part of the key"
    assert discover is not pick and pick is not recall
    assert get("live_pick") is pick, "and the fork is still a cache"


def test_a_scripted_model_never_carries_a_pinned_effort(monkeypatch):
    """Scripted models are local replay: forking their cache would split the shared replay
    cursor that keyless tests depend on, and there is no provider to send an effort to."""
    from pneuma_knowledge_service import wiring

    ctx = SimpleNamespace(settings=Settings(llm_model="scripted:x.json"), _chat_models={})
    monkeypatch.setattr(
        wiring, "_build_from_name", lambda *a, **k: object()  # noqa: ARG005
    )
    get = wiring.AppContext.get_chat_model.__get__(ctx, wiring.AppContext)
    assert get("live_discover") is get("live_pick") is get("recall")


def test_an_explicit_live_context_model_wins_over_the_recall_fallback():
    s = Settings(
        llm_model="openai:base",
        llm_model_recall="openrouter:fast-test",
        llm_model_live_context="openrouter:flash",
    )
    assert resolve_model_name(s, "live_context") == "openrouter:flash"
    assert resolve_model_name(s, "recall") == "openrouter:fast-test"  # unchanged


def test_live_context_falls_all_the_way_back_to_the_base_model():
    assert resolve_model_name(Settings(llm_model="openai:base"), "live_context") == "openai:base"


def test_answer_role_can_split_from_recall_and_otherwise_borrows_it():
    split = Settings(
        llm_model="openai:base",
        llm_model_recall="openrouter:openai/gpt-5.6-luna",
        llm_model_answer="openrouter:openai/gpt-5.6-luna-pro",
    )
    assert resolve_model_name(split, "recall") == "openrouter:openai/gpt-5.6-luna"
    assert resolve_model_name(split, "answer") == "openrouter:openai/gpt-5.6-luna-pro"

    inherited = Settings(
        llm_model="openai:base",
        llm_model_recall="openrouter:openai/gpt-5.6-luna",
    )
    assert resolve_model_name(inherited, "answer") == "openrouter:openai/gpt-5.6-luna"


def test_a_scripted_base_model_still_hard_overrides_live_context_routing():
    """The existing discipline: a scripted run stays fully keyless and reproducible, so an
    env-set role model must not leak into it."""
    s = Settings(llm_model="scripted:/tmp/x.json", llm_model_live_context="openrouter:flash")
    assert resolve_model_name(s, "live_context") == "scripted:/tmp/x.json"


def test_the_fallback_does_not_leak_into_the_other_roles():
    """Only Live Context borrows. If `deep` started resolving to the recall model, a deployment
    that tuned them separately would silently lose the distinction."""
    s = Settings(llm_model="openai:base", llm_model_recall="openrouter:fast-test")
    assert resolve_model_name(s, "deep") == "openai:base"
    assert resolve_model_name(s, "compile") == "openai:base"
    assert resolve_model_name(s, "default") == "openai:base"


# --------------------------------------------------------------- the vocabularies


def test_the_focus_and_kind_registries_are_served_from_core():
    """The UI fetches the closed sets rather than inlining copies — otherwise the core
    prompt, the route and the client become three vocabularies that drift."""
    # No lifespan: neither endpoint touches app.state.ctx, and running it would need PG.
    client = TestClient(create_app(Settings()))
    focuses = client.get("/v1/live-context/focuses").json()
    assert [f["key"] for f in focuses] == [f.key for f in CONTEXT_FOCUSES]
    assert focuses[0]["label"] == CONTEXT_FOCUSES[0].label

    kinds = client.get("/v1/live-context/kinds").json()
    assert [k["key"] for k in kinds] == [k.key for k in SUGGESTION_KINDS]


# ------------------------------------------------------------------- backpressure


def test_the_outbound_queue_drops_the_oldest_frame():
    """Bounded + drop-oldest. A suggestion whose conversation has already moved on is worth less
    than the one behind it, and blocking instead would let a slow client apply
    backpressure all the way up into the evaluation."""
    q = asyncio.Queue(maxsize=3)
    for i in range(3):
        assert put_drop_oldest(q, i) is False
    assert put_drop_oldest(q, 3) is True  # full: evicts 0
    assert [q.get_nowait() for _ in range(3)] == [1, 2, 3]


def test_the_outbound_limit_is_bounded_at_all():
    assert 0 < OUTBOUND_LIMIT < 1000


# ------------------------------------ the scripted model really does structured output


class FakeEmbeddings:
    def __init__(self) -> None:
        self.document_calls = 0

    async def aembed_documents(self, texts):  # noqa: ANN001
        self.document_calls += 1
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def aembed_query(self, text):  # noqa: ANN001
        raise AssertionError("suggestion must batch its queries, never embed one at a time")


class _EmptyIndex:
    """A claim/window index that is reachable and holds nothing — the shape a fresh
    knowledge base has, and the one the lane must survive without an exception."""

    async def search_claims(self, *_args, **_kwargs):
        return []

    async def search(self, *_args, **_kwargs):
        return []

    async def search_vectors(self, *_args, **_kwargs):
        return []


def _ctx(model, **over):
    ctx = SimpleNamespace(
        settings=Settings(),
        embeddings=FakeEmbeddings(),
        lexical=None,
        vectors=None,
        store=None,
        langfuse_handler=lambda: None,
        get_chat_model=lambda role="default": model,
    )
    for k, v in over.items():
        setattr(ctx, k, v)
    return ctx


def _plan():
    """A one-turn plan, built through the real session so the shape cannot drift."""
    s = LiveContextSession(LiveContextPolicy(quiet_period=0.0))
    s.add_turn(ConversationTurn(speaker="me", text="我们在聊 RAG", role="owner"))
    return s.begin(now=0.0)


def suggestion_call(**args):
    return [
        {
            "name": "SuggestionBatch",
            "args": {
                "suggestions": [
                    {
                        "kind": "concept",
                        "title": "RAG",
                        "body": args.get("body", "检索增强生成"),
                        "trigger": "我们在聊 RAG",
                        "confidence": args.get("confidence", 9),
                    }
                ]
            },
        }
    ]


async def test_a_scripted_model_serves_the_suggestion_structured_output():
    """`ScriptedChatModel` CAN back `with_structured_output` — it overrides `bind_tools`,
    which sidesteps `BaseChatModel`'s NotImplementedError guard. The whole keyless suggestion path
    depends on this, so it is asserted rather than assumed.

    Briefing scope, which is where the one-round contract still lives. The card here is
    ungrounded (no resolvable `[cite: …]`), so gate 2 drops it — and that drop is itself the
    proof the emission PARSED: an unparsed round would have been counted under `unparsed`."""
    model = ScriptedChatModel(turns=[suggestion_call()])
    result = await run_evaluation(_ctx(model), "u-1", _plan(), pack=PACK)
    assert result.dropped["uncited"] == 1
    assert result.dropped["unparsed"] == 0
    assert result.suggestions == ()


async def test_an_exhausted_script_degrades_to_silence():
    """Past its last turn the scripted model answers plain prose, which arrives as
    `parsed=None` under `include_raw=True`. That must be zero suggestions, never an exception —
    a background listener degrades to silence, it does not 500 onto a pair of context clients."""
    model = ScriptedChatModel(turns=[])
    result = await run_evaluation(_ctx(model), "u-1", _plan(), pack=PACK)
    assert result.suggestions == ()
    assert result.dropped["unparsed"] == 1


async def test_briefing_scope_does_no_embedding_at_all():
    """The frozen pack IS the evidence. Zero retrieval and zero embedding is the reason
    briefing scope exists — it is the fastest path, and latency is this feature."""
    model = ScriptedChatModel(turns=[suggestion_call()])
    ctx = _ctx(model)
    await run_evaluation(ctx, "u-1", _plan(), pack=PACK)
    assert ctx.embeddings.document_calls == 0


async def test_full_scope_skips_before_it_embeds_anything():
    """The redesign's whole economic argument, at the service seam: an exhausted script
    answers prose, the discover stage cannot parse it, and the tick ends having embedded
    nothing. The old lane embedded first and asked afterwards."""
    ctx = _ctx(ScriptedChatModel(turns=[]))
    result = await run_evaluation(ctx, "u-1", _plan())
    assert result.skipped == "unparsed"
    assert ctx.embeddings.document_calls == 0


async def test_full_scope_embeds_once_when_the_discover_stage_asks_it_to():
    """One query, one embedding round trip — not one per transcript turn."""
    ctx = _ctx(
        ScriptedChatModel(
            turns=[
                [
                    {
                        "name": "DiscoverResult",
                        "args": {
                            "skip": False,
                            "intent": "what is RAG",
                            "plan": [{"kind": "semantic", "query": "RAG", "args": []}],
                            "worth": 9,
                        },
                    }
                ],
                [{"name": "PickResult", "args": {"choice": 0, "confidence": 1}}],
            ]
        ),
        lexical=_EmptyIndex(),
        vectors=_EmptyIndex(),
    )
    result = await run_evaluation(ctx, "u-1", _plan())
    assert ctx.embeddings.document_calls == 1
    assert result.intent == "what is RAG"
    assert result.plan == ("semantic(RAG)",)


async def test_live_context_skips_the_tick_when_canonical_is_unreadable():
    """`_live_canonical` RAISES, and the tick ends rather than retrieving unpinned.

    The service seam of the pin. The document set this loader returns is what admits an index
    claim (`archive_filter._off_pin`) — a claim is shown only while the set still holds its
    page, which is what drops an L3 row still naming a page the Owner moved. A read that
    failed hands the tick no set, and a tick that retrieved anyway would put those rows on a
    card in a room that never asked for history. So the room is quiet for one turn."""

    async def broken(user, *, at=None):  # noqa: ANN001, ARG001
        raise RuntimeError("git is busy")

    ctx = _ctx(
        ScriptedChatModel(
            turns=[
                [
                    {
                        "name": "DiscoverResult",
                        "args": {
                            "skip": False,
                            "intent": "what is RAG",
                            "plan": [{"kind": "semantic", "query": "RAG", "args": []}],
                            "worth": 9,
                        },
                    }
                ],
                [{"name": "PickResult", "args": {"choice": 1, "confidence": 9}}],
            ]
        ),
        lexical=_EmptyIndex(),
        vectors=_EmptyIndex(),
        canonical=SimpleNamespace(list=broken),
    )
    result = await run_evaluation(ctx, "u-1", _plan())

    assert result.skipped == "canonical_unavailable"
    assert result.dropped == {"canonical_unavailable": 1}
    assert result.suggestions == ()
    # It stops BEFORE stage 2, so a deployment whose git is down pays one discover call and
    # nothing else — no embedding, no index round trip, no pick.
    assert ctx.embeddings.document_calls == 0


# ----------------------------------------------------------------------- want_more


class RecordingStore:
    def __init__(self, texts: dict | None = None) -> None:
        self.calls: list[tuple] = []
        self._texts = texts or {}

    async def fetch(self, user, source_id, locator):  # noqa: ANN001
        self.calls.append((str(user), str(source_id), tuple(locator["blocks"])))
        key = (str(source_id), tuple(locator["blocks"]))
        if key not in self._texts:
            raise KeyError(f"no such span: {key}")
        return self._texts[key]


class RecordingModel:
    """A one-shot chat model that records the message list it was handed."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.seen: list = []

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.seen.append(messages)
        return AIMessage(content=self.content)


def a_suggestion(citations: list[dict]) -> dict:
    return {
        "kind": "concept",
        "title": "RAG",
        "body": "检索增强生成",
        "trigger": "我们在聊 RAG",
        "confidence": 9,
        "citations": citations,
    }


async def test_want_more_fetches_exactly_the_suggestions_own_citations():
    """Zero retrieval, zero embedding — the client hands back the whole card, and its
    citations already carry real source ids and block spans, so there is nothing left to
    search for. That is also what makes the operation survive a reconnect or a deploy: the
    server need not remember having emitted the card."""
    store = RecordingStore({(SRC, (3, 5)): "原文第三到五块"})
    model = ScriptedChatModel(turns=[{"content": "展开后的正文"}])
    ctx = _ctx(model, store=store)

    detail = await expand_suggestion(
        ctx, "u-1", a_suggestion([{"source_id": SRC, "block_start": 3, "block_end": 5}])
    )

    assert store.calls == [("u-1", SRC, (3, 5))]
    assert ctx.embeddings.document_calls == 0  # and aembed_query would have raised
    assert detail["title"] == "RAG"
    assert detail["detail"] == "展开后的正文"
    assert detail["citations"] == [
        {"source_id": SRC, "block_start": 3, "block_end": 5}
    ]
    assert detail["token_usage"]["total_tokens"] == 18


async def test_want_more_refuses_to_deliver_an_empty_expansion():
    """A blank expansion is the one failure that must never reach the client.

    The owner tapped a card and is waiting; handing back an empty one is worse than
    saying it failed, and it contradicts the discipline the whole feature rests on —
    never push an empty card. The WS handler turns this raise into a non-fatal `error`
    frame, so the socket survives and the card stays as it was.

    Found by end-to-end smoke, not by unit tests: a scripted turn that carried a tool
    call instead of text produced `content == ""`, and the server cheerfully emitted
    `suggestion_detail` with an empty body."""
    store = RecordingStore({(SRC, (3, 5)): "原文第三到五块"})
    ctx = _ctx(ScriptedChatModel(turns=[{"content": "   "}]), store=store)

    with pytest.raises(ValueError, match="empty"):
        await expand_suggestion(
            ctx, "u-1", a_suggestion([{"source_id": SRC, "block_start": 3, "block_end": 5}])
        )


async def test_want_more_puts_the_fetched_verbatim_in_front_of_the_model():
    """The expansion is only worth anything if the original text actually reaches the
    prompt — otherwise it is the model reciting the card back with more words."""
    store = RecordingStore({(SRC, (3, 5)): "被引用来源里的一段独特原文"})
    model = RecordingModel("ok")
    await expand_suggestion(
        _ctx(model, store=store),
        "u-1",
        a_suggestion([{"source_id": SRC, "block_start": 3, "block_end": 5}]),
    )

    system, human_msg = model.seen[0]
    assert "# Context briefing · expanded" in str(system.content)
    human = str(human_msg.content)
    assert "被引用来源里的一段独特原文" in human
    assert "RAG" in human  # the card itself is there too


async def test_a_failing_fetch_yields_a_partial_expansion_not_an_error():
    """Someone mid-conversation is better served by a thinner expansion than by an error
    frame, so a span that no longer resolves is skipped."""
    store = RecordingStore({(SRC, (3, 5)): "只有这一段还在"})
    model = ScriptedChatModel(turns=[{"content": "ok"}])
    detail = await expand_suggestion(
        _ctx(model, store=store),
        "u-1",
        a_suggestion(
            [
                {"source_id": SRC, "block_start": 3, "block_end": 5},
                {"source_id": SRC, "block_start": 90, "block_end": 91},
            ]
        ),
    )
    assert len(store.calls) == 2
    assert detail["citations"] == [{"source_id": SRC, "block_start": 3, "block_end": 5}]


async def test_a_malformed_citation_is_skipped_not_raised():
    store = RecordingStore()
    model = ScriptedChatModel(turns=[{"content": "ok"}])
    detail = await expand_suggestion(
        _ctx(model, store=store), "u-1", a_suggestion([{"source_id": SRC}, "nonsense"])
    )
    assert store.calls == []
    assert detail["citations"] == []
    assert detail["detail"] == "ok"


async def test_live_canonical_reports_the_archive_beside_the_live_documents():
    """The live lane learns BOTH facts from the one read it makes, or it learns neither.

    `_live_canonical` filters the archive out — a room is never served the past by default —
    which is precisely why it cannot then be asked whether an archive exists: the evidence
    was just removed. So it hands back `LoadedDocuments`, and core reads the flag off it
    (`recall/archive_filter._pin`). With nothing archived the assembly filter is inert and
    the tick retrieves byte-for-byte as it did before the archive existed."""
    from pneuma_knowledge_core.domain.canonical import CanonicalDocument
    from pneuma_knowledge_core.domain.ids import DocumentId, UserId
    from pneuma_knowledge_service.live_context.engine import _live_canonical

    def doc(path: str) -> CanonicalDocument:
        return CanonicalDocument(
            doc_id=DocumentId(path.replace("/", "-")),
            path=path,
            frontmatter={"title": "p"},
            body="# p\n\n- a claim.\n",
        )

    def ctx_over(docs):
        async def listing(user, *, at=None):  # noqa: ANN001, ARG001
            return docs
        return SimpleNamespace(canonical=SimpleNamespace(list=listing))

    live_only = await _live_canonical(ctx_over([doc("work/x.md")]), UserId("u-1"))
    assert [d.path for d in live_only.documents] == ["work/x.md"]
    assert live_only.archive_active is False

    with_archive = await _live_canonical(
        ctx_over([doc("work/x.md"), doc("archive/work/y.md")]), UserId("u-1")
    )
    assert [d.path for d in with_archive.documents] == ["work/x.md"], "still live only"
    assert with_archive.archive_active is True, "and the room's pin is switched on"
