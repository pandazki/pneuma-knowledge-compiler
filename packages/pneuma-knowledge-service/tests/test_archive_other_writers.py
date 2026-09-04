"""The archive is not offered to the other writers: groom and evolve leave it alone.

docs/design/archive.md §2.1 — "Groom skips archived documents. Evolve enumerates live
documents only and leaves `archive/` exactly as it found it on the branch." Both are
mechanical exclusions rather than instructions, so both are asserted here as facts about
what the two services enumerate and what they commit.
"""

from __future__ import annotations

from types import SimpleNamespace

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.skill import SkillVersion
from pneuma_knowledge_service import evolve_service
from pneuma_knowledge_service.evolve_service import adopt_evolve_job, run_evolve_job
from pneuma_knowledge_service.groom_service import (
    GROOM_JOB_KIND,
    scan_oversized_documents,
)
from pneuma_knowledge_service.settings import Settings

USER = "u-archive-writers"
LIVE = "work/products/aurora.md"
ARCHIVED = "archive/work/products/atlas.md"


def _doc(path: str, body: str) -> CanonicalDocument:
    slug = path.rsplit("/", 1)[-1].removesuffix(".md")
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}"),
        path=path,
        frontmatter={"doc_id": f"d-{slug}", "type": "product", "slug": slug},
        body=body,
    )


def _oversized(path: str) -> CanonicalDocument:
    return _doc(path, f"# {path}\n\n" + "x" * 41_000 + "\n")


class _Canonical:
    """`list` per ref, plus the branch face the adopt path uses."""

    def __init__(self, by_ref: dict[str, list[CanonicalDocument]]) -> None:
        self.by_ref = by_ref
        self.committed: dict[str, str] | None = None
        self.deleted_branches: list[str] = []

    async def list(self, user, *, at=None):
        return list(self.by_ref["HEAD" if at is None else at.ref])

    async def branch_head(self, user, branch):
        return SnapshotRef(ref=branch)

    async def read_meta_at(self, user, path, ref):
        return None

    async def snapshots(self, user):
        return [SnapshotRef(ref="sha-main")]

    async def commit_patch(self, user, files, *, message):
        self.committed = dict(files)
        return SnapshotRef(ref="sha-adopted")

    async def delete_branch(self, user, branch):
        self.deleted_branches.append(branch)


class _Store:
    def __init__(self, task=None) -> None:
        self.task = task
        self.enqueued: list[tuple[str, dict]] = []
        self.completed: list[dict] = []
        self.decided: list[tuple[str, str]] = []
        self.details: list[str] = []

    async def list_jobs(self, user):
        return []

    async def enqueue(self, user, kind, payload):
        self.enqueued.append((kind, payload))
        return f"job-{len(self.enqueued)}"

    async def list_evolve_tasks(self, user):
        return []

    async def list_compile_events(self, user):
        return []

    async def create_evolve_task(self, user, task_id, *, status, **fields):
        self.task = {"task_id": task_id, "status": status, **fields}

    async def get_evolve_task(self, user, task_id):
        return dict(self.task) if self.task else None

    async def update_evolve_detail(self, user, task_id, detail):
        self.details.append(detail)

    async def decide_evolve_task(self, user, task_id, status, *, detail=None):
        self.decided.append((task_id, status))

    async def complete(
        self, user, job_id, *, ok=True, detail=None, snapshot_ref=None, token_usage=None
    ):
        self.completed.append({"job_id": job_id, "ok": ok, "detail": detail})


def _ctx(store: _Store, canonical: _Canonical) -> SimpleNamespace:
    return SimpleNamespace(
        settings=Settings(),
        store=store,
        canonical=canonical,
        get_chat_model=lambda role="default": None,
        langfuse_handler=lambda: None,
    )


def _install_skill(monkeypatch):
    async def _skill_for_user(ctx, user):
        return SkillVersion(
            skill_id="test-skill",
            version="t1",
            instructions="body",
            path_templates=["work/products/{slug}.md"],
            content_hash="0" * 64,
        )

    monkeypatch.setattr(evolve_service, "skill_for_user", _skill_for_user)


# ------------------------------------------------------------------------- the groom


async def test_the_repository_sweep_never_proposes_a_rollover_for_an_archived_page():
    """An oversized page in the archive stays oversized. Splitting retired knowledge into a
    second volume is a canonical write, with a model call, on material nobody reads."""
    store = _Store()
    canonical = _Canonical({"HEAD": [_oversized(LIVE), _oversized(ARCHIVED)]})
    # Both are oversized as COMMITTED bytes, which is what the sweep measures.
    for doc in canonical.by_ref["HEAD"]:
        assert (
            len(render_document(doc.frontmatter, doc.body))
            > Settings().rollover_threshold_chars
        )

    await scan_oversized_documents(_ctx(store, canonical), USER)

    assert store.enqueued == [(GROOM_JOB_KIND, {"path": LIVE})]


# ------------------------------------------------------------------------ the evolve


async def test_the_evolve_proposal_is_shown_live_documents_only(monkeypatch):
    _install_skill(monkeypatch)
    seen: dict = {}

    async def fake_propose(**kwargs):
        seen["doc_paths"] = list(kwargs["doc_paths"])
        return None, "no_change", "nothing is under pressure"

    monkeypatch.setattr(evolve_service, "propose_evolution", fake_propose)

    store = _Store()
    canonical = _Canonical({"HEAD": [_doc(LIVE, "# a\n"), _doc(ARCHIVED, "# b\n")]})

    await run_evolve_job(
        _ctx(store, canonical),
        USER,
        SimpleNamespace(job_id="j-1", kind="evolve", payload={}),
    )

    assert seen["doc_paths"] == [LIVE]
    assert store.task["status"] == "no_change"


async def test_an_adopt_leaves_every_archived_document_untouched(monkeypatch):
    """The three-way merge is over live documents on all three sides, so no archived path
    enters the commit — the archive comes out of an adopt byte-for-byte, by not being in it."""
    monkeypatch.setattr(evolve_service, "skill_for_user", None, raising=False)

    async def fake_rebuild(ctx, user, ref, **kwargs):
        return SimpleNamespace(total=0)

    monkeypatch.setattr(evolve_service, "rebuild_projection", fake_rebuild)

    archived = _doc(ARCHIVED, "# Atlas\n\n- retired claim <!-- c:aaaa1111 -->\n")
    base = [_doc(LIVE, "# Aurora\n\n- live claim <!-- c:bbbb2222 -->\n"), archived]
    branch = [
        _doc("work/products/aurora-v2.md", "# Aurora\n\n- live claim <!-- c:bbbb2222 -->\n"),
        archived,
    ]
    canonical = _Canonical({"sha-base": base, "evolve/t-1": branch, "HEAD": base})
    store = _Store(
        task={
            "task_id": "t-1",
            "status": "draft",
            "branch": "evolve/t-1",
            "base_ref": "sha-base",
        }
    )

    await adopt_evolve_job(
        _ctx(store, canonical),
        USER,
        SimpleNamespace(job_id="j-2", kind="evolve_adopt", payload={"task_id": "t-1"}),
    )

    assert store.decided == [("t-1", "adopted")]
    assert canonical.committed is not None
    # The reorganized live page is committed; the archived one is not in the file set at
    # all, which is exactly what "left as it was found" means for a path-addressed commit.
    assert set(canonical.committed) == {"work/products/aurora-v2.md"}
    assert not any(path.startswith("archive/") for path in canonical.committed)


# ------------------------------------------------- the evolve, and the RECORD

RECORD = "work/products/atlas.md"


def _record(live_path: str, body: str) -> CanonicalDocument:
    """The short live page the archive job leaves standing at a retired page's path."""
    slug = live_path.rsplit("/", 1)[-1].removesuffix(".md")
    return CanonicalDocument(
        doc_id=DocumentId(f"d-{slug}-record"),
        path=live_path,
        frontmatter={
            "doc_id": f"d-{slug}-record",
            "type": "archived",
            "slug": slug,
            "title": slug.title(),
            "archive_of": "archive/" + live_path,
            "archived_on": "2026-09-04",
        },
        body=f"# {slug.title()}\n\n- {slug.title()} was archived. <!-- c:cccc3333 -->\n",
    )


async def test_the_evolve_proposal_is_not_shown_the_record_of_a_retired_subject(
    monkeypatch,
):
    """A record is live, so `live_documents` keeps it — and it is still not part of the
    shape a reorganization reasons about: a family is not crowded by the subjects that left
    it, and no claim of a record's may be re-filed anywhere."""
    _install_skill(monkeypatch)
    seen: dict = {}

    async def fake_propose(**kwargs):
        seen["doc_paths"] = list(kwargs["doc_paths"])
        return None, "no_change", "nothing is under pressure"

    monkeypatch.setattr(evolve_service, "propose_evolution", fake_propose)

    store = _Store()
    canonical = _Canonical(
        {
            "HEAD": [
                _doc(LIVE, "# a\n"),
                _record(RECORD, ""),
                _doc("archive/" + RECORD, "# b\n"),
            ]
        }
    )

    await run_evolve_job(
        _ctx(store, canonical),
        USER,
        SimpleNamespace(job_id="j-1", kind="evolve", payload={}),
    )

    assert seen["doc_paths"] == [LIVE]


def _adopt_ctx(monkeypatch, store, canonical):
    monkeypatch.setattr(evolve_service, "skill_for_user", None, raising=False)

    async def fake_rebuild(ctx, user, ref, **kwargs):
        return SimpleNamespace(total=0)

    monkeypatch.setattr(evolve_service, "rebuild_projection", fake_rebuild)
    return _ctx(store, canonical)


def _draft_task() -> dict:
    return {
        "task_id": "t-1",
        "status": "draft",
        "branch": "evolve/t-1",
        "base_ref": "sha-base",
    }


async def test_an_adopt_carries_an_archive_record_through_byte_for_byte(monkeypatch):
    """The record is in the commit and identical to what stood on main. It is a live page —
    the merge carries it rather than skipping it — and not one byte of it is the
    reorganization's to write."""
    record = _record(RECORD, "")
    copy = _doc("archive/" + RECORD, "# Atlas\n\n- retired claim <!-- c:aaaa1111 -->\n")
    aurora = _doc(LIVE, "# Aurora\n\n- live claim <!-- c:bbbb2222 -->\n")
    renamed = _doc(
        "work/products/aurora-v2.md", "# Aurora\n\n- live claim <!-- c:bbbb2222 -->\n"
    )
    canonical = _Canonical(
        {
            "sha-base": [aurora, record, copy],
            "evolve/t-1": [renamed, record, copy],
            "HEAD": [aurora, record, copy],
        }
    )
    store = _Store(task=_draft_task())

    await adopt_evolve_job(
        _adopt_ctx(monkeypatch, store, canonical),
        USER,
        SimpleNamespace(job_id="j-2", kind="evolve_adopt", payload={"task_id": "t-1"}),
    )

    assert store.decided == [("t-1", "adopted")]
    assert set(canonical.committed) == {"work/products/aurora-v2.md", RECORD}
    assert canonical.committed[RECORD] == render_document(
        record.frontmatter, record.body
    )


async def test_an_adopt_does_not_resurrect_a_subject_archived_during_the_review_window(
    monkeypatch,
):
    """The branch was built before the Owner retired Atlas and still holds the live page.
    Main holds the record at that path. A merge that carried the branch's copy would commit
    the retired page back over the record — the subject resurrected by a mechanical merge,
    with nobody having asked for it."""
    atlas = _doc(RECORD, "# Atlas\n\n- Atlas ships weekly. <!-- c:dddd4444 -->\n")
    record = _record(RECORD, "")
    copy = _doc("archive/" + RECORD, atlas.body)
    aurora = _doc(LIVE, "# Aurora\n\n- live claim <!-- c:bbbb2222 -->\n")
    renamed = _doc(
        "work/products/aurora-v2.md", "# Aurora\n\n- live claim <!-- c:bbbb2222 -->\n"
    )
    canonical = _Canonical(
        {
            "sha-base": [aurora, atlas],
            "evolve/t-1": [renamed, atlas],
            # The window: the archive job moved Atlas and left its record behind.
            "HEAD": [aurora, record, copy],
        }
    )
    store = _Store(task=_draft_task())

    await adopt_evolve_job(
        _adopt_ctx(monkeypatch, store, canonical),
        USER,
        SimpleNamespace(job_id="j-3", kind="evolve_adopt", payload={"task_id": "t-1"}),
    )

    assert store.decided == [("t-1", "adopted")]
    assert set(canonical.committed) == {"work/products/aurora-v2.md", RECORD}
    # The record stands, unchanged; the page it replaced is nowhere in the commit.
    assert canonical.committed[RECORD] == render_document(
        record.frontmatter, record.body
    )
    assert not any("c:dddd4444" in text for text in canonical.committed.values())
