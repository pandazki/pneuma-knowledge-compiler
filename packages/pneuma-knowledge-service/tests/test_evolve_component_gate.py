"""A component's canonical field invariants hold on EVERY authoring channel, not only on
the daily compile — evolve (whole-KB reorganization) and adopt (the merge that makes a
reviewed reorganization canonical) are judged by the same fan-out.

Driven with the shipped `people` component, keyless: a reorganization that creates a person
page binding two speakers of one conversation, or an identity another page already holds, is
refused exactly as a compile would refuse it; a cold mirror refuses rather than passing
blind; and the review window's own writes are re-judged at adopt, where the branch — built
against an older main — is the half nobody has checked against what main holds now.
"""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import count
from types import SimpleNamespace

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from pneuma_knowledge_core.components import register_component, reset_components
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.evolve.propose import EvolveProposal
from pneuma_knowledge_core.evolve.runner import run_evolve
from pneuma_knowledge_core.ingest.canonical_sources import normalize_source_contract
from pneuma_knowledge_core.ingest.source_contracts import ImSource
from pneuma_knowledge_core.skill import load_skill_base
from pneuma_knowledge_service.components.people import PeopleComponent
from pneuma_knowledge_service.evolve_service import adopt_evolve_job
from pneuma_knowledge_service.settings import Settings

FAMILY = "memory/people/{slug}.md"
MEI_PATH = "memory/people/mei-lin.md"
RAVI_PATH = "memory/people/ravi-seth.md"
USER = UserId("u-evolve-people")

_ids = count()


@pytest.fixture(autouse=True)
def _clean():
    reset_components()
    yield
    reset_components()


# ------------------------------------------------------------------------------ fixtures


def _im_source():
    """One synthetic group chat through the REAL contract normalizer: two non-owner
    identities each take a turn, which is the fact `people.identity_cospeakers` rests on."""
    payload = {
        "schema": "pneuma.source.im/v1",
        "provider": "mock",
        "archive_id": "grp-1",
        "owner_user_ids": ["u_owner"],
        "users": [
            {"user_id": "u_owner", "display_name": "Ke ZHOU"},
            {"user_id": "u_mei", "display_name": "Mei LIN"},
            {"user_id": "u_ravi", "display_name": "Ravi SETH"},
        ],
        "conversations": [
            {
                "conversation_id": "c-grp-1",
                "conversation_type": "group_dm",
                "title": "运营群",
                "member_ids": ["u_owner", "u_mei", "u_ravi"],
                "messages": [
                    {
                        "message_id": "m0",
                        "sender_id": "u_owner",
                        "sent_at": "2026-05-12T09:00:00+00:00",
                        "text": "这版排期谁来定？",
                    },
                    {
                        "message_id": "m1",
                        "sender_id": "u_mei",
                        "sent_at": "2026-05-12T09:02:00+00:00",
                        "text": "我来定，今天发群里。",
                    },
                    {
                        "message_id": "m2",
                        "sender_id": "u_ravi",
                        "sent_at": "2026-05-12T09:05:00+00:00",
                        "text": "物料清单我这边跟。",
                    },
                ],
            }
        ],
    }
    [source] = normalize_source_contract(
        ImSource.model_validate(payload),
        USER,
        imported_at=datetime(2026, 5, 13, tzinfo=timezone.utc),
    )
    return source


SOURCE = _im_source()
SID = str(SOURCE.raw.source_id)


class _L0:
    """L0 as the component's `prepare` reads it: the raw sources, and nothing else. A
    `fail=True` store is the transient outage — the mirror never loads."""

    def __init__(self, sources=(), *, fail: bool = False) -> None:
        self._sources = list(sources)
        self.fail = fail
        self.calls = 0

    async def list(self, user_id):
        assert user_id == USER
        self.calls += 1
        if self.fail:
            raise RuntimeError("L0 unavailable")
        return [getattr(s, "raw", s) for s in self._sources]


def tc(name: str, **args) -> dict:
    return {"name": name, "args": args, "id": f"call-{next(_ids)}", "type": "tool_call"}


class ScriptedChatModel(BaseChatModel):
    """The scripted evolve model, plus what it HEARD: the gate's feedback round is the only
    place a violation is said out loud to the caller of `run_evolve`."""

    turns: list = []
    heard: list = []
    _cursor: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ARG002
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001, ARG002
        self.heard.extend(
            str(m.content) for m in messages if m.__class__.__name__ == "HumanMessage"
        )
        usage = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        if self._cursor < len(self.turns):
            calls = self.turns[self._cursor]
            self._cursor += 1
            msg = AIMessage(content="", tool_calls=calls, usage_metadata=usage)
        else:
            msg = AIMessage(content="done", usage_metadata=usage)
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _topic(anchor: str = "aa11") -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId("d-atlas"),
        path="memory/topics/atlas.md",
        frontmatter={"doc_id": "d-atlas", "type": "topic", "slug": "atlas"},
        body=f"# Atlas\n\n- 排期当天定完。[cite: {SID} ¶1] <!-- c:{anchor} -->",
    )


def _person(slug: str, identities: str, anchor: str = "b001") -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=f"memory/people/{slug}.md",
        frontmatter={
            "doc_id": f"d-{slug}",
            "type": "person",
            "slug": slug,
            "identities": identities,
        },
        body=f"# {slug}\n\n- 物料清单他跟到底。[cite: {SID} ¶2] <!-- c:{anchor} -->",
    )


def _proposal() -> EvolveProposal:
    return EvolveProposal(packs=[], rationale="人物页应当从主题页里独立出来。")


async def _bounds(source_id: str) -> int | None:
    return {SID: 3}.get(source_id)


async def _evolve(component, base_docs, turns):
    register_component(component)
    model = ScriptedChatModel(turns=turns, heard=[])
    result = await run_evolve(
        user_id=USER,
        model=model,
        base_docs=base_docs,
        new_skill=load_skill_base("v1"),
        proposal=_proposal(),
        source_bounds=_bounds,
    )
    return result, model


def _create_mei(identities: str):
    return [
        tc(
            "create_document",
            path=MEI_PATH,
            frontmatter={"type": "person", "slug": "mei-lin", "identities": identities},
            body=f"# Mei LIN\n\n- 排期当天定完。[cite: {SID} ¶1]",
        ),
        tc("finish_evolve"),
    ]


# ------------------------------------------------- evolve: judged like any other compile


async def test_evolve_cannot_create_a_page_that_binds_two_co_speakers():
    """The reorganization has no sources of its own — its evidence for "these two are two
    people" is the LIBRARY mirror `prepare` filled, which is exactly the channel a compile
    would have used for a conversation it is not reading this round."""
    result, model = await _evolve(
        PeopleComponent(FAMILY, content=_L0([SOURCE])),
        [_topic()],
        [_create_mei("im:u_mei, im:u_ravi")],
    )
    assert result.status == "aborted"  # nothing lands; the service must not land a branch
    feedback = "\n".join(model.heard)
    assert "[people.identity_cospeakers] " + MEI_PATH in feedback
    assert "运营群" in feedback  # the refusal names the conversation, as a compile's does


async def test_evolve_cannot_create_a_page_holding_an_identity_another_page_binds():
    result, model = await _evolve(
        PeopleComponent(FAMILY, content=_L0([SOURCE])),
        [_topic(), _person("ravi-seth", "im:u_ravi")],
        [
            [
                tc(
                    "create_document",
                    path=MEI_PATH,
                    frontmatter={
                        "type": "person",
                        "slug": "mei-lin",
                        "identities": "im:u_ravi",
                    },
                    body=f"# Mei LIN\n\n- 排期当天定完。[cite: {SID} ¶1]",
                ),
                tc("finish_evolve"),
            ]
        ],
    )
    assert result.status == "aborted"
    feedback = "\n".join(model.heard)
    assert "[people.identity_duplicate] " + MEI_PATH in feedback
    assert RAVI_PATH in feedback
    # …and only the page this round wrote answers for it: the page that already held the
    # identity is untouched, and an old page never makes a reorganization unpassable.
    assert "[people.identity_duplicate] " + RAVI_PATH not in feedback


async def test_evolve_with_a_cold_mirror_refuses_rather_than_passing_blind():
    """`prepare` is fail-soft (it logs and the job continues), so the WRITE-TIME face is what
    keeps a failed read from becoming an open gate: a component that could not load what it
    judges by says so, and the reorganization aborts."""
    store = _L0([SOURCE], fail=True)
    result, model = await _evolve(
        PeopleComponent(FAMILY, content=store),
        [_topic()],
        [_create_mei("im:u_mei")],  # a page that is fine — and still not judgeable
    )
    assert store.calls >= 1
    assert result.status == "aborted"
    assert "[people.not_ready] " + FAMILY in "\n".join(model.heard)


async def test_a_clean_reorganization_still_completes_with_the_component_registered():
    """The other side of the rule: the checks refuse what a compile would refuse and nothing
    else. In particular the alias decision — which is asked about the people THIS round's
    SOURCES carry — demands nothing of a reorganization, which reads no source at all."""
    result, model = await _evolve(
        PeopleComponent(FAMILY, content=_L0([SOURCE])),
        [_topic()],
        [_create_mei("im:u_mei")],
    )
    assert result.status == "completed"
    assert not [line for line in model.heard if "[people." in line]
    assert "identities: im:u_mei" in result.files[MEI_PATH]


# --------------------------------------------------------- adopt: judged against main NOW


class _Canonical:
    """The canonical face an adopt reads: three pinned views of the same repo."""

    def __init__(self, base, branch, main) -> None:
        self._at = {"base-ref": base, "evolve/t-1": branch}
        self._main = main
        self.commits: list[dict] = []

    async def list(self, user, *, at=None):  # noqa: ARG002
        if at is None:
            return list(self._main)
        return list(self._at[at.ref])

    async def branch_head(self, user, branch):  # noqa: ARG002
        return "branch-head"

    async def snapshots(self, user):  # noqa: ARG002
        return []

    async def read_meta_at(self, user, path, ref):  # noqa: ARG002
        return None

    async def commit_patch(self, user, files, *, message):  # noqa: ARG002
        self.commits.append(dict(files))
        raise AssertionError("a refused adopt must not commit")

    async def delete_branch(self, user, branch):  # noqa: ARG002
        return None


class _Store:
    def __init__(self, task) -> None:
        self.task = dict(task)
        self.completed: list[dict] = []
        self.decided: list[str] = []

    async def get_evolve_task(self, user, task_id):  # noqa: ARG002
        return dict(self.task)

    async def update_evolve_detail(self, user, task_id, detail):  # noqa: ARG002
        self.task["detail"] = detail

    async def decide_evolve_task(self, user, task_id, status, *, detail=None):  # noqa: ARG002
        self.decided.append(status)

    async def complete(  # noqa: ARG002
        self, user, job_id, *, ok=True, detail=None, snapshot_ref=None, token_usage=None
    ):
        self.completed.append({"ok": ok, "detail": detail})


async def test_adopt_is_refused_when_the_review_window_bound_the_identity_elsewhere():
    """The branch passed the gate against the base it was built from. What no one has judged
    is the branch against main NOW: a daily compile inside the review window gave the same
    identity a page of its own, and the mechanical catch-up merge — which judges nothing —
    would otherwise make two pages holding one identity canonical."""
    register_component(PeopleComponent(FAMILY, content=_L0([SOURCE])))
    base = [_topic()]
    # the reorganization gave Mei a page of her own, binding her IM identity
    branch = [_topic(), _person("mei-lin", "im:u_mei", anchor="b002")]
    # …and inside the review window a daily compile did the same, under another slug
    main = [_topic(), _person("lin-mei", "im:u_mei", anchor="c003")]

    store = _Store(
        {"task_id": "t-1", "status": "draft", "branch": "evolve/t-1", "base_ref": "base-ref"}
    )
    canonical = _Canonical(base, branch, main)
    ctx = SimpleNamespace(settings=Settings(), store=store, canonical=canonical)
    job = SimpleNamespace(job_id="j-1", kind="evolve_adopt", payload={"task_id": "t-1"})

    await adopt_evolve_job(ctx, USER, job)

    assert canonical.commits == []  # nothing became canonical
    assert store.decided == []  # the task stays a draft, adoptable after a repair
    [completion] = store.completed
    assert completion["ok"] is False
    assert "[people.identity_duplicate] " + MEI_PATH in completion["detail"]
    # …and only the half this adopt actually writes answers for it: the window's own page is
    # carried over byte-identical to main, so it is untouched and is judged by nothing —
    # it is NAMED by the refusal (the rule says where the identity already lives) and never
    # charged with it.
    assert "[people.identity_duplicate] memory/people/lin-mei.md" not in completion["detail"]
    assert "bound by `memory/people/lin-mei.md`" in completion["detail"]
    assert store.task["detail"] == completion["detail"]
