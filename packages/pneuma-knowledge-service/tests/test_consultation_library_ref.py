"""`library_ref` names the canonical HEAD SAMPLED WHEN THE CONSULTATION BEGAN.

The field's defect was a disagreement, not a bug: the code recorded the HEAD resolved before
retrieval started, and the record, the schema and the design page said "HEAD at answer
time". Two readings of one field is one reading too many for an audit chain — and the first
correction, "the state the evidence was READ FROM", was still a promise the code does not
keep: the glance lists canonical with `at=None` and the claim indexes are unversioned, so a
compile landing mid-answer makes a face newer than the ref. The definition that IS
mechanically true is a sample: where the reading started, with a pinned-snapshot call as
the exact form of the same field. This pins both halves — the behaviour, and the four places
that have to say the same thing about it.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from pneuma_knowledge_service.api.routes import v1 as v1_module
from pneuma_knowledge_service.api.routes.v1 import (
    RecallIn,
    drain_recording_tasks,
    recall,
)

_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class _FakeDeepAnswer:
    answer: str = "答案。"
    used_claims: tuple = ()
    used_windows: tuple = ()
    trail: list = field(default_factory=list)
    glance_chars: int = 0
    read_documents: tuple = ()
    image_count: int = 0
    image_mode: str = "caption"
    stages: tuple = ()
    evidence_manifest: tuple = ()
    token_usage: dict = field(default_factory=lambda: {"total_tokens": 1})


class _Store:
    def __init__(self) -> None:
        self.rows: list = []

    async def create_consultation(self, user, record) -> str | None:  # noqa: ANN001
        await asyncio.sleep(0)
        self.rows.append(record)
        return None


class _MovingCanonical:
    """A canonical whose HEAD advances the moment the lane starts running."""

    def __init__(self) -> None:
        self.head = "commit-before"

    async def snapshots(self, user):  # noqa: ANN001
        return [SimpleNamespace(ref=self.head)]


async def _no_profile(user):  # noqa: ANN001
    raise RuntimeError("no profile provider in this test")


def _request(store, canonical) -> SimpleNamespace:  # noqa: ANN001
    ctx = SimpleNamespace(
        canonical=canonical,
        user_info=SimpleNamespace(get_profile=_no_profile),
        langfuse_handler=lambda: None,
        lexical=None,
        vectors=None,
        embeddings=None,
        media=object(),
        store=store,
        get_chat_model=lambda role="default": None,
        settings=SimpleNamespace(
            recall_answer_style="conversational",
            llm_model="scripted:library-ref-test",
            openrouter_api_key="",
        ),
    )
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(ctx=ctx)))


async def test_the_ref_is_the_head_sampled_when_the_consultation_began(monkeypatch):
    """A compile lands while the lane is running. The record keeps the sample it took when
    the consultation began — resolving HEAD again at the end would name a state no face was
    read from either, and would only move the same uncertainty to the other end."""
    store = _Store()
    canonical = _MovingCanonical()

    async def fake_deep(*_args, **_kwargs):
        canonical.head = "commit-after"  # a compile lands while the lane is running
        return _FakeDeepAnswer()

    monkeypatch.setattr(v1_module, "deep_recall", fake_deep)

    await recall(
        "u-mei",
        RecallIn(query="阿宝在盯哪条线？", mode="deep", visitor_class="audit"),
        _request(store, canonical),
    )
    # The route emits and returns; the write is a detached task (routes/v1.py
    # `_spawn_recording`), so the record is read after that task has had its moment.
    await drain_recording_tasks(5.0)

    [record] = store.rows
    assert record.library_ref == "commit-before"


def test_the_record_the_schema_and_the_design_page_say_the_same_thing_about_it():
    """Three copies of one definition, and the finding was that they had drifted apart from
    the code. A wording test is the only mechanical thing there is to hold here, and the
    alternative — leaving it to a reader to notice — is what produced the drift."""
    sources = {
        "dataclass": _ROOT
        / "packages/pneuma-knowledge-core/src/pneuma_knowledge_core/domain/consultation.py",
        "schema": _ROOT / "infra/schema.sql",
        "design (en)": _ROOT / "docs/design/steward-owner-visitor.md",
        "route helper": _ROOT
        / "packages/pneuma-knowledge-service/src/pneuma_knowledge_service/api/routes/v1.py",
    }
    for name, path in sources.items():
        text = path.read_text(encoding="utf-8").lower()
        assert "sampled when the consultation began" in text, (
            f"{name} does not define library_ref"
        )
        assert "read live state" in text or "live state" in text, (
            f"{name} does not say the evidence faces may advance past the sample"
        )

    zh = (_ROOT / "docs/design/steward-owner-visitor.zh-CN.md").read_text(encoding="utf-8")
    assert "咨询开始时采样到的正本 HEAD" in zh
    assert "是采样，不是钉住" in zh
