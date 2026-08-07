"""The rollover (`groom`) service flow, driven off fakes — no git, no docker, no provider.

Two things are locked. The TRIGGER: it is a size check over the documents a compile actually
wrote, it never fires twice for one pending cut, and 0 turns it off. The JOB: it commits the
two files core produced with a skill-stamped trailer and re-projects, and every non-happy path
(document gone, not rollable, model failure, gate refusal) completes the job with the reason
recorded and commits NOTHING — a rollover that quietly did not happen must not look like one
that was never triggered.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.compile.rollover import (
    ARCHIVED_FROM_KEY,
    _OverviewDraft,
    _OverviewPointDraft,
)
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.skill import SkillVersion
from pneuma_knowledge_service.groom_service import (
    GROOM_JOB_KIND,
    heal_volume_links_for_user,
    maybe_trigger_rollover,
    run_groom_job,
    scan_oversized_documents,
)
from pneuma_knowledge_service.settings import Settings

ACTIVE = "work/products/aurora-planner.md"
TEMPLATES = ["memory/profile.md", "work/products/{slug}.md"]


def _anchor(tag: str) -> str:
    return hashlib.sha256(tag.encode()).hexdigest()[:8]


def _claim(i: int) -> str:
    return (
        f"- Sprint {i}: the Aurora launch checklist advanced. "
        f"[cite: src-01 ¶{i}] <!-- c:{_anchor(f'claim-{i}')} -->"
    )


def _active(count: int = 30) -> CanonicalDocument:
    rows = "\n".join(_claim(i) for i in range(count))
    return CanonicalDocument(
        doc_id=DocumentId("d-aurora"),
        path=ACTIVE,
        frontmatter={"doc_id": "d-aurora", "type": "product", "slug": "aurora-planner"},
        body=f"# Aurora planner\n\n## Delivery\n\n{rows}\n",
    )


# ------------------------------------------------------------------------------ the fakes


class _FakeStore:
    def __init__(self, jobs=None):
        self._jobs = jobs or []
        self.enqueued: list[tuple[str, dict]] = []
        self.completed: list[dict] = []

    async def list_jobs(self, user):  # noqa: ARG002
        return self._jobs

    async def enqueue(self, user, kind, payload):  # noqa: ARG002
        self.enqueued.append((kind, payload))
        return f"job-{len(self.enqueued)}"

    async def complete(self, user, job_id, *, ok=True, detail=None, snapshot_ref=None):  # noqa: ARG002
        self.completed.append(
            {"job_id": job_id, "ok": ok, "detail": detail, "snapshot_ref": snapshot_ref}
        )


class _FakeCanonical:
    def __init__(self, docs):
        self._docs = list(docs)
        self.commits: list[tuple[dict[str, str], str]] = []

    async def list(self, user, *, at=None):  # noqa: ARG002
        return list(self._docs)

    async def commit_patch(self, user, files, *, message):  # noqa: ARG002
        self.commits.append((dict(files), message))
        return SnapshotRef(ref="sha-groomed")


class _StubStructured:
    def __init__(self, payload, *, boom=False):
        self.payload, self.boom = payload, boom

    async def ainvoke(self, messages, config=None):  # noqa: ARG002
        if self.boom:
            raise RuntimeError("provider exploded")
        return {"parsed": self.payload}


class _StubModel:
    def __init__(self, payload, *, boom=False):
        self._structured = _StubStructured(payload, boom=boom)

    def with_structured_output(self, schema, include_raw=False):  # noqa: ARG002
        return self._structured


def _skill() -> SkillVersion:
    return SkillVersion(
        skill_id="test-skill",
        version="t1",
        instructions="body",
        path_templates=list(TEMPLATES),
        content_hash="0" * 64,
    )


def _ctx(store, canonical=None, model=None, **over):
    return SimpleNamespace(
        settings=Settings(**over),
        store=store,
        canonical=canonical,
        get_chat_model=lambda role="default": model,
        langfuse_handler=lambda: None,
    )


def _install_stubs(monkeypatch, *, projected=7):
    """Replace the two ports the job flow reaches for outside core: the per-user skill and the
    L3 projection sync. Both have their own tests; here they only need to be observable."""
    calls: dict[str, object] = {}

    async def _skill_for_user(ctx, user):  # noqa: ARG001
        return _skill()

    async def _sync(ctx, user, ref):  # noqa: ARG001
        calls["synced_ref"] = ref
        return SimpleNamespace(total=projected, upserted=0, deleted=0, unchanged=0)

    monkeypatch.setattr("pneuma_knowledge_service.groom_service.skill_for_user", _skill_for_user)
    monkeypatch.setattr("pneuma_knowledge_service.groom_service.sync_projection", _sync)
    return calls


# ------------------------------------------------------------------------------ the trigger


async def test_a_written_document_over_the_threshold_is_enqueued():
    store = _FakeStore()
    files = {ACTIVE: "x" * 41_000, "work/products/other.md": "y" * 100}
    jobs = await maybe_trigger_rollover(
        _ctx(store), "u-x", files, {ACTIVE, "work/products/other.md"}
    )
    assert jobs == ["job-1"]
    assert store.enqueued == [(GROOM_JOB_KIND, {"path": ACTIVE})]


async def test_an_oversized_document_this_compile_did_not_write_is_left_alone():
    """The trigger is deliberately not a sweep: an existing monster rolls over the next time it
    is touched, so enabling the feature cannot set off a stampede of grooms."""
    store = _FakeStore()
    files = {ACTIVE: "x" * 41_000}
    assert await maybe_trigger_rollover(_ctx(store), "u-x", files, set()) == []
    assert store.enqueued == []


async def test_zero_threshold_disables_the_trigger_entirely():
    store = _FakeStore()
    files = {ACTIVE: "x" * 10_000_000}
    ctx = _ctx(store, rollover_threshold_chars=0)
    assert await maybe_trigger_rollover(ctx, "u-x", files, {ACTIVE}) == []
    assert store.enqueued == []


async def test_a_document_already_awaiting_a_groom_is_not_enqueued_twice():
    """A second job for the same path would open a second volume for a cut that has not
    happened yet."""
    store = _FakeStore(
        jobs=[{"kind": GROOM_JOB_KIND, "status": "queued", "payload": {"path": ACTIVE}}]
    )
    files = {ACTIVE: "x" * 41_000}
    assert await maybe_trigger_rollover(_ctx(store), "u-x", files, {ACTIVE}) == []
    # a COMPLETED groom on that path does not block the next one
    store2 = _FakeStore(
        jobs=[{"kind": GROOM_JOB_KIND, "status": "done", "payload": {"path": ACTIVE}}]
    )
    assert await maybe_trigger_rollover(_ctx(store2), "u-x", files, {ACTIVE}) == ["job-1"]


# -------------------------------------------------------------------------- the sweep (#4)
#
# The write trigger's blind spot is permanent by construction: a page that crosses the
# threshold and then goes quiet is never written again, so it is never re-checked. The sweep
# is the same size check over the whole repository, hung off the lowest-frequency pass there
# is rather than added to the write path.


def _sized(path: str, slug: str, chars: int, **extra) -> CanonicalDocument:
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=path,
        frontmatter={"doc_id": f"d-{slug}", "type": "product", "slug": slug, **extra},
        body=f"# {slug}\n\n" + "x" * chars + "\n",
    )


async def test_the_sweep_finds_the_quiet_oversized_page_the_write_trigger_never_revisits():
    quiet = _sized(ACTIVE, "aurora-planner", 41_000)
    small = _sized("work/products/orion.md", "orion", 100)
    # A frozen volume is excluded: history is never rolled over again, so a job for it could
    # only report "cannot be rolled over".
    frozen = _sized(
        "work/products/aurora-planner/a01.md", "a01", 41_000, **{ARCHIVED_FROM_KEY: ACTIVE}
    )
    store = _FakeStore()

    jobs = await scan_oversized_documents(
        _ctx(store, _FakeCanonical([quiet, small, frozen])), "u-x"
    )

    assert jobs == ["job-1"]
    assert store.enqueued == [(GROOM_JOB_KIND, {"path": ACTIVE})]


async def test_the_sweep_shares_the_write_triggers_idempotency_and_its_off_switch():
    docs = [_sized(ACTIVE, "aurora-planner", 41_000)]
    pending = _FakeStore(
        jobs=[{"kind": GROOM_JOB_KIND, "status": "queued", "payload": {"path": ACTIVE}}]
    )
    assert await scan_oversized_documents(_ctx(pending, _FakeCanonical(docs)), "u-x") == []

    off = _FakeStore()
    ctx = _ctx(off, _FakeCanonical(docs), rollover_threshold_chars=0)
    assert await scan_oversized_documents(ctx, "u-x") == []


# ---------------------------------------------------------------------------------- the job


def _job(path: str = ACTIVE):
    return SimpleNamespace(job_id="j-1", kind=GROOM_JOB_KIND, payload={"path": path})


def _good_model():
    return _StubModel(
        _OverviewDraft(
            points=[
                _OverviewPointDraft(
                    text="The launch checklist was driven to done.",
                    anchors=[_anchor("claim-0"), _anchor("claim-3")],
                )
            ]
        )
    )


async def test_a_groom_commits_the_two_files_with_a_skill_trailer_and_reprojects(monkeypatch):
    active = _active(30)
    store, canonical = _FakeStore(), _FakeCanonical([active])
    calls = _install_stubs(monkeypatch)
    ctx = _ctx(store, canonical, _good_model(), rollover_keep_recent_chars=400)

    await run_groom_job(ctx, "u-x", _job())

    assert len(canonical.commits) == 1
    files, message = canonical.commits[0]
    volume = "work/products/aurora-planner/a01.md"
    assert set(files) == {ACTIVE, volume}
    assert message.startswith(f"groom {ACTIVE}: rolled over ")
    assert "Skill-Version: t1" in message  # same two identity axes as a compile commit
    assert f"{ARCHIVED_FROM_KEY}: {ACTIVE}" in files[volume]

    assert calls["synced_ref"] == "sha-groomed"
    done = store.completed[-1]
    assert done["ok"] is True and done["snapshot_ref"] == "sha-groomed"
    assert '"volume":"work/products/aurora-planner/a01.md"' in done["detail"]
    assert '"projected":7' in done["detail"]


async def test_a_document_that_vanished_completes_the_job_instead_of_failing(monkeypatch):
    store, canonical = _FakeStore(), _FakeCanonical([])
    _install_stubs(monkeypatch)
    await run_groom_job(_ctx(store, canonical, _good_model()), "u-x", _job())
    assert canonical.commits == []
    assert store.completed[-1]["ok"] is True
    assert "no longer exists" in store.completed[-1]["detail"]


async def test_a_document_that_cannot_be_rolled_over_is_not_an_error(monkeypatch):
    """A document outside the skill's families has no history directory, so there is nowhere
    legal to archive to."""
    stray = CanonicalDocument(
        doc_id=DocumentId("d-stray"),
        path="stray/note.md",
        frontmatter={"doc_id": "d-stray", "type": "note", "slug": "note"},
        body="# Stray\n\n## Facts\n\n" + "\n".join(_claim(i) for i in range(30)),
    )
    store, canonical = _FakeStore(), _FakeCanonical([stray])
    _install_stubs(monkeypatch)
    ctx = _ctx(store, canonical, _good_model(), rollover_keep_recent_chars=400)

    await run_groom_job(ctx, "u-x", _job("stray/note.md"))
    assert canonical.commits == []
    assert store.completed[-1]["ok"] is True
    assert "cannot be rolled over" in store.completed[-1]["detail"]


async def test_a_failed_history_card_abandons_the_groom_and_commits_nothing(monkeypatch):
    active = _active(30)
    store, canonical = _FakeStore(), _FakeCanonical([active])
    _install_stubs(monkeypatch)
    ctx = _ctx(
        store,
        canonical,
        _StubModel(_OverviewDraft(), boom=True),
        rollover_keep_recent_chars=400,
    )

    await run_groom_job(ctx, "u-x", _job())
    assert canonical.commits == []
    done = store.completed[-1]
    assert done["ok"] is False and done["detail"] == "groom: history card call_failed"


async def test_an_ungroundable_card_abandons_the_groom_rather_than_writing_it(monkeypatch):
    """Every point the model returned named an id it was not shown, so nothing is left to
    write — and a rollover with no history card is a rollover that hid its own archive."""
    active = _active(30)
    store, canonical = _FakeStore(), _FakeCanonical([active])
    _install_stubs(monkeypatch)
    model = _StubModel(
        _OverviewDraft(points=[_OverviewPointDraft(text="Invented.", anchors=["deadbeef"])])
    )
    ctx = _ctx(store, canonical, model, rollover_keep_recent_chars=400)

    await run_groom_job(ctx, "u-x", _job())
    assert canonical.commits == []
    assert store.completed[-1]["ok"] is False
    assert store.completed[-1]["detail"] == "groom: history card empty"


async def test_a_gate_refusal_records_the_violations_and_commits_nothing(monkeypatch):
    """The gate has no repair round: a refusal ends the job with the violation text on it, and
    the next compile that writes the document triggers a fresh attempt."""
    active = _active(30)
    store, canonical = _FakeStore(), _FakeCanonical([active])
    _install_stubs(monkeypatch)
    ctx = _ctx(store, canonical, _good_model(), rollover_keep_recent_chars=400)

    def _tampering_build(plan, points, docs, *, path_templates):  # noqa: ARG001
        from pneuma_knowledge_core.compile.gate import Violation
        from pneuma_knowledge_core.compile.rollover import RolloverResult

        return RolloverResult(
            status="rejected",
            violations=[Violation("groom_bytes", plan.active_path, "not byte-equal")],
        )

    monkeypatch.setattr(
        "pneuma_knowledge_service.groom_service.build_rollover", _tampering_build
    )
    await run_groom_job(ctx, "u-x", _job())
    assert canonical.commits == []
    done = store.completed[-1]
    assert done["ok"] is False
    assert done["detail"] == f"[groom_bytes] {ACTIVE}: not byte-equal"


# ------------------------------------------------------------------------------ the heal pass


def _volume_with_short_links() -> list[CanonicalDocument]:
    """A knowledge base groomed BEFORE the channel compensated for the volume's extra depth."""
    orion = CanonicalDocument(
        doc_id=DocumentId("d-orion"),
        path="memory/topics/orion.md",
        frontmatter={"doc_id": "d-orion", "type": "topic", "slug": "orion"},
        body=f"# Orion\n\n## Scope\n\n{_claim(90)}\n",
    )
    volume = CanonicalDocument(
        doc_id=DocumentId("d-a01"),
        path="work/products/aurora-planner/a01.md",
        frontmatter={
            "doc_id": "d-a01",
            "type": "product",
            "slug": "a01",
            ARCHIVED_FROM_KEY: ACTIVE,
        },
        body=(
            "# Aurora planner\n\n## Delivery\n\n"
            "- Sprint 0: see [Orion](../../memory/topics/orion.md). "
            f"[cite: src-01 ¶0] <!-- c:{_anchor('claim-0')} -->\n"
        ),
    )
    return [_active(1), orion, volume]


async def test_the_heal_pass_commits_the_rewritten_volume_and_reprojects(monkeypatch):
    canonical = _FakeCanonical(_volume_with_short_links())
    calls = _install_stubs(monkeypatch)
    # no model is wired at all: a heal is pure mechanics, and would explode if it called one
    ctx = _ctx(_FakeStore(), canonical, None)

    summary = await heal_volume_links_for_user(ctx, "u-x")

    assert summary["status"] == "ready"
    assert summary["healed_links"] == 1
    assert (summary["dead_before"], summary["dead_after"]) == (1, 0)
    files, message = canonical.commits[0]
    assert set(files) == {"work/products/aurora-planner/a01.md"}
    assert message.startswith("groom-heal: rewrote 1 volume link(s)")
    assert "Skill-Version: t1" in message  # the same identity axes a groom commit carries
    assert "(../../../memory/topics/orion.md)" in files[
        "work/products/aurora-planner/a01.md"
    ]
    assert calls["synced_ref"] == "sha-groomed"
    assert summary["projected"] == 7


async def test_a_heal_with_nothing_to_repair_writes_no_commit_at_all(monkeypatch):
    """Idempotence at the service seam: running the repair twice must not leave a second,
    empty commit in the one non-rebuildable layer."""
    canonical = _FakeCanonical([_active(1)])
    _install_stubs(monkeypatch)
    summary = await heal_volume_links_for_user(_ctx(_FakeStore(), canonical, None), "u-x")
    assert summary["status"] == "clean" and summary["healed_links"] == 0
    assert canonical.commits == []


async def test_a_second_groom_opens_the_next_volume_and_leaves_the_first_frozen(monkeypatch):
    active = _active(30)
    store, canonical = _FakeStore(), _FakeCanonical([active])
    _install_stubs(monkeypatch)
    ctx = _ctx(store, canonical, _good_model(), rollover_keep_recent_chars=400)
    await run_groom_job(ctx, "u-x", _job())

    # feed the committed state back in, grown by more compile activity
    from pneuma_knowledge_core.compile.documents import parse_document

    files = canonical.commits[0][0]
    docs = []
    for path, text in files.items():
        frontmatter, body = parse_document(text)
        if path == ACTIVE:
            body = body.rstrip("\n") + "\n" + "\n".join(_claim(i) for i in range(30, 45))
        docs.append(
            CanonicalDocument(
                doc_id=DocumentId(str(frontmatter["doc_id"])),
                path=path,
                frontmatter=frontmatter,
                body=body,
            )
        )
    canonical2 = _FakeCanonical(docs)
    ctx2 = _ctx(store, canonical2, _good_model(), rollover_keep_recent_chars=400)
    await run_groom_job(ctx2, "u-x", _job())

    second = canonical2.commits[0][0]
    assert set(second) == {ACTIVE, "work/products/aurora-planner/a02.md"}
    assert "work/products/aurora-planner/a01.md" not in second
    # and the frozen volume's bytes on disk are exactly what the first groom wrote
    assert render_document(*parse_document(files["work/products/aurora-planner/a01.md"])) == (
        files["work/products/aurora-planner/a01.md"]
    )


class _FlakyStructured:
    """First card is ungroundable (names an anchor it may not name), the second is clean."""

    def __init__(self, bad, good) -> None:
        self._replies = [bad, good]
        self.calls = 0

    async def ainvoke(self, messages, config=None):  # noqa: ARG002
        self.calls += 1
        return {"parsed": self._replies[min(self.calls - 1, len(self._replies) - 1)]}


class _FlakyModel:
    def __init__(self, bad, good) -> None:
        self.structured = _FlakyStructured(bad, good)

    def with_structured_output(self, schema, include_raw=False):  # noqa: ARG002
        return self.structured


async def test_a_refused_history_card_is_rewritten_once_before_the_groom_is_abandoned(
    monkeypatch,
):
    """A rollover refused by the gate must get the same second chance a compile gets.

    Nothing retries a groom job: a failed one stays failed, its document stays oversized, and
    every later drain keeps reporting the same unresolved failure (seen on a real corpus,
    where the identical card passed on a plain re-run). One rewrite, then judge again."""
    active = _active(30)
    store, canonical = _FakeStore(), _FakeCanonical([active])
    calls = _install_stubs(monkeypatch)
    ungroundable = _OverviewDraft(
        points=[
            _OverviewPointDraft(
                text="Cites a claim that is not being archived.",
                anchors=[_anchor("claim-not-in-this-rollover")],
            )
        ]
    )
    clean = _OverviewDraft(
        points=[
            _OverviewPointDraft(
                text="The launch checklist was driven to done.",
                anchors=[_anchor("claim-0"), _anchor("claim-3")],
            )
        ]
    )
    model = _FlakyModel(ungroundable, clean)
    ctx = _ctx(store, canonical, model, rollover_keep_recent_chars=400)

    await run_groom_job(ctx, "u-x", _job())

    assert model.structured.calls == 2  # rewritten exactly once
    assert len(canonical.commits) == 1  # and the retry's card is what got committed
    assert store.completed[-1]["ok"] is True
    assert calls["synced_ref"] == "sha-groomed"


async def test_a_twice_refused_history_card_still_fails_the_job(monkeypatch):
    active = _active(30)
    store, canonical = _FakeStore(), _FakeCanonical([active])
    _install_stubs(monkeypatch)
    ungroundable = _OverviewDraft(
        points=[
            _OverviewPointDraft(
                text="Cites a claim that is not being archived.",
                anchors=[_anchor("claim-not-in-this-rollover")],
            )
        ]
    )
    model = _FlakyModel(ungroundable, ungroundable)
    ctx = _ctx(store, canonical, model, rollover_keep_recent_chars=400)

    await run_groom_job(ctx, "u-x", _job())

    assert model.structured.calls == 2
    assert canonical.commits == []
    assert store.completed[-1]["ok"] is False
