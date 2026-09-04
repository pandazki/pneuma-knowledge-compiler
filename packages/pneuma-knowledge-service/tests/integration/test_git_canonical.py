"""GitCanonicalStore over real git in a temp dir: round-trip, `at` snapshot reads,
tags, and two-user isolation (invariant I1)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import pathlib
import subprocess
import threading
import time

import pytest

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.ports.canonical_store import (
    CanonicalDirtyError,
    CanonicalMarkerError,
    CanonicalMoveError,
)
from pneuma_knowledge_service.adapters.git_canonical import GitCanonicalStore

U1 = UserId("u-git-alice")
U2 = UserId("u-git-bob")


def _file(doc_id: str, slug: str, body: str) -> str:
    return render_document(
        {"doc_id": doc_id, "type": "person", "slug": slug}, body
    )


def _dead_pid() -> int:
    """A pid nothing is running under: spawned, reaped, and confirmed gone.

    Every recovery branch in the adapter is a statement about a DEAD writer, and the marker's
    pid is what it checks that against, so a test that means "a process died here" has to
    hand it a pid that really is gone. `os.getpid()` — which `_write_marker` stamps — means
    the opposite and is refused, which is what `test_a_claim_whose_process_is_alive_...`
    exercises from the other side.
    """
    done = subprocess.Popen(["/bin/sh", "-c", ":"])
    done.wait()
    for _ in range(500):
        try:
            os.kill(done.pid, 0)
        except ProcessLookupError:
            return done.pid
        time.sleep(0.01)
    raise AssertionError(f"pid {done.pid} is still alive after being reaped")


def _write_dead_marker(
    store: GitCanonicalStore,
    repo: pathlib.Path,
    operation: str,
    *,
    paths: list[str] | None = None,
    pre_existing: list[str] | None = None,
) -> int:
    """The claim a KILLED writer leaves: the operation, ITS FOOTPRINT, and a pid that is gone.

    `paths` is the footprint the real body would have recorded before it wrote anything — the
    recovery reaches exactly this far and no further — and `pre_existing` is the restore's
    inverse of one. Both are written explicitly, because a claim that records no list at all
    is a different thing entirely (it covers nothing, and is refused), and tests want to say
    which of the two they mean. Returns the dead pid.
    """
    pid = _dead_pid()
    body: dict[str, object] = {
        "operation": operation,
        "pid": pid,
        "started_at": "2026-01-01T00:00:00+00:00",
        "paths": sorted(paths or []),
    }
    if pre_existing is not None:
        body["pre_existing"] = sorted(pre_existing)
    store._marker_path(repo).write_text(
        json.dumps(body, sort_keys=True), encoding="utf-8"
    )
    return pid


def _kill_claimant(store: GitCanonicalStore, repo: pathlib.Path) -> int:
    """Restamp the claim standing here with a pid that is gone, keeping everything else.

    The half an in-process simulation cannot do for itself: the claim a live body wrote names
    THIS pid, and a live claimant is not a death. A real kill takes the pid with it and leaves
    the rest of the claim — its operation and its FOOTPRINT — exactly as the body wrote it,
    which is what the next call has to weigh."""
    marker = store._marker_path(repo)
    claim = json.loads(marker.read_text("utf-8"))
    claim["pid"] = _dead_pid()
    marker.write_text(json.dumps(claim, sort_keys=True), encoding="utf-8")
    return claim["pid"]


async def test_commit_and_read_roundtrip(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    assert await store.list(U1) == []  # empty repo, lazily init-ed

    files = {
        "memory/people/cheng-ye.md": _file(
            "d-cheng-ye", "cheng-ye", "- 程野 是后端负责人。[cite: src-01 ¶0] <!-- c:aa11 -->"
        )
    }
    ref = await store.commit_patch(U1, files, message="compile 1")
    assert ref.ref  # a commit sha

    docs = await store.list(U1)
    assert [d.path for d in docs] == ["memory/people/cheng-ye.md"]
    doc = await store.read(U1, DocumentId("d-cheng-ye"))
    assert doc is not None
    assert doc.frontmatter["slug"] == "cheng-ye"
    assert "c:aa11" in doc.body
    assert await store.read(U1, DocumentId("missing")) is None


async def test_list_reads_canonical_tree_with_one_archive_process(
    tmp_path, monkeypatch
):
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1,
        {
            "memory/people/a.md": _file(
                "d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->"
            ),
            "memory/people/b.md": _file(
                "d-b", "b", "- B。[cite: src-02 ¶0] <!-- c:bb22 -->"
            ),
            "skill/manifest.json": '{"base_version":"personal-knowledge-v1"}',
        },
        message="two docs and metadata",
    )

    real_run = subprocess.run
    calls: list[tuple[str, ...]] = []

    def recording_run(args, *positional, **kwargs):
        if args and args[0] == "git":
            calls.append(tuple(args[3:]))
        return real_run(args, *positional, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    docs = await store.list(U1)

    assert [doc.path for doc in docs] == [
        "memory/people/a.md",
        "memory/people/b.md",
    ]
    commands = [call[0] for call in calls]
    assert commands == ["rev-parse", "archive"]
    assert "ls-tree" not in commands
    assert "show" not in commands


async def test_a_document_committed_with_the_legacy_id_key_still_loads(tmp_path):
    """An already-deployed repo has documents whose frontmatter spells the id `pneuma_id`.
    Canonical is never history-rewritten (invariant I2), so the read side folds the legacy
    key onto `doc_id` and such a document keeps its identity — `read` by DocumentId works."""
    store = GitCanonicalStore(str(tmp_path))
    legacy = (
        "---\n"
        "pneuma_id: d-song-yao\n"
        "slug: song-yao\n"
        "type: person\n"
        "---\n"
        "\n"
        "- 宋遥 负责 Atlas 的检索评测。[cite: src-01 ¶0] <!-- c:aa11 -->\n"
    )
    await store.commit_patch(
        U1, {"memory/people/song-yao.md": legacy}, message="pre-rename compile"
    )

    docs = await store.list(U1)
    assert [str(doc.doc_id) for doc in docs] == ["d-song-yao"]
    assert "pneuma_id" not in docs[0].frontmatter
    assert docs[0].frontmatter["doc_id"] == "d-song-yao"
    assert await store.read(U1, DocumentId("d-song-yao")) is not None


async def test_at_snapshot_reads_historical_state(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    v1 = await store.commit_patch(
        U1, {"memory/profile.md": _file("d-p", "profile", "- 版本一。[cite: src-01 ¶0] <!-- c:1111 -->")},
        message="v1",
    )
    await store.commit_patch(
        U1, {"memory/profile.md": _file("d-p", "profile", "- 版本二。[cite: src-02 ¶1] <!-- c:1111 -->")},
        message="v2",
    )
    # HEAD sees v2; the v1 snapshot ref still sees v1.
    assert "版本二" in (await store.list(U1))[0].body
    at_v1 = await store.list(U1, at=v1)
    assert "版本一" in at_v1[0].body

    snaps = await store.snapshots(U1)
    assert [s.label for s in snaps] == ["v2", "v1"]  # newest first


async def test_snapshot_pages_are_bounded_and_stable_during_new_commits(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    for version in range(1, 4):
        await store.commit_patch(
            U1,
            {
                "memory/profile.md": _file(
                    "d-p",
                    "profile",
                    f"- 版本{version}。[cite: src-0{version} ¶0] <!-- c:1111 -->",
                )
            },
            message=f"v{version}",
        )

    first, total, has_more = await store.snapshots_page(U1, limit=1)
    assert ([row.label for row in first], total, has_more) == (["v3"], 3, True)

    # A newer commit arriving after page one must not shift the continuation.
    await store.commit_patch(
        U1,
        {
            "memory/profile.md": _file(
                "d-p",
                "profile",
                "- 版本4。[cite: src-04 ¶0] <!-- c:1111 -->",
            )
        },
        message="v4",
    )

    second, second_total, second_has_more = await store.snapshots_page(
        U1,
        limit=1,
        after_ref=first[-1].ref,
    )
    assert ([row.label for row in second], second_total, second_has_more) == (
        ["v2"],
        4,
        True,
    )
    assert first[0].ref != second[0].ref

    with pytest.raises(ValueError, match="snapshot cursor"):
        await store.snapshots_page(
            U1,
            limit=1,
            after_ref="not-a-snapshot-ref",
        )


def _commit_on(repo, day: str, rel: str, text: str) -> None:
    """One commit stamped with a chosen day, so "the LAST commit wins" is testable in a test
    that runs inside one second."""
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    stamp = f"{day}T12:00:00+0000"
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", f"write {rel}"],
        check=True,
        env={
            **os.environ,
            "GIT_AUTHOR_DATE": stamp,
            "GIT_COMMITTER_DATE": stamp,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        },
    )


async def test_written_on_names_the_day_each_path_was_last_committed(tmp_path):
    """The clock a derived projection is measured against, and it costs nothing to keep: git
    already records when each file last changed. It states what was COMMITTED, and only the
    LAST commit per path — an earlier one is that path's history, not its answer."""
    store = GitCanonicalStore(str(tmp_path))
    assert await store.written_on(U1) == {}  # no HEAD yet

    repo = store.repo_path(U1)
    store._repo(U1)  # lazily init the repo
    _commit_on(repo, "2026-03-01", "memory/people/cheng-ye.md",
               _file("d-1", "cheng-ye", "- a. [cite: s ¶0] <!-- c:a1 -->"))
    _commit_on(repo, "2026-04-02", "memory/topics/q3.md",
               _file("d-2", "q3", "- b. [cite: s ¶0] <!-- c:b1 -->"))
    assert await store.written_on(U1) == {
        "memory/people/cheng-ye.md": "2026-03-01",
        "memory/topics/q3.md": "2026-04-02",
    }

    # …a later commit on one path moves that path's day and no other's
    _commit_on(repo, "2026-06-15", "memory/people/cheng-ye.md",
               _file("d-1", "cheng-ye", "- a2. [cite: s ¶1] <!-- c:a1 -->"))
    assert await store.written_on(U1) == {
        "memory/people/cheng-ye.md": "2026-06-15",
        "memory/topics/q3.md": "2026-04-02",
    }

    # …and a prefix bounds the walk to one family
    assert await store.written_on(U1, prefix="memory/people/") == {
        "memory/people/cheng-ye.md": "2026-06-15"
    }
    # a user with no repo at all answers nothing, and never another user's history (I1)
    assert await store.written_on(U2) == {}


async def test_tag_creates_readable_ref(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    ref = await store.commit_patch(
        U1, {"memory/profile.md": _file("d-p", "profile", "- x。[cite: src-01 ¶0] <!-- c:1111 -->")},
        message="v1",
    )
    tag = await store.tag(U1, ref, "release-1")
    assert tag.ref == "release-1"
    docs = await store.list(U1, at=tag)
    assert docs and docs[0].path == "memory/profile.md"


async def test_two_users_are_isolated(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1, {"memory/people/a.md": _file("d-a", "a", "- alice。[cite: src-01 ¶0] <!-- c:aaaa -->")},
        message="alice",
    )
    await store.commit_patch(
        U2, {"memory/people/b.md": _file("d-b", "b", "- bob。[cite: src-01 ¶0] <!-- c:bbbb -->")},
        message="bob",
    )
    alice_paths = {d.path for d in await store.list(U1)}
    bob_paths = {d.path for d in await store.list(U2)}
    assert alice_paths == {"memory/people/a.md"}
    assert bob_paths == {"memory/people/b.md"}
    # No cross-user visibility.
    assert await store.read(U1, DocumentId("d-b")) is None


# --- branch operations (evolve; plumbing-only, working tree pinned) -------------------


def _rev_parse(repo, ref: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _porcelain(repo) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


async def test_branch_commit_leaves_head_and_worktree_untouched(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    base = await store.commit_patch(
        U1,
        {
            "memory/profile.md": _file("d-p", "profile", "- 基线。[cite: src-01 ¶0] <!-- c:aa11 -->"),
            "memory/people/cheng-ye.md": _file("d-e", "cheng-ye", "- 程野。[cite: src-01 ¶0] <!-- c:bb22 -->"),
        },
        message="base",
    )
    repo = store._repo(U1)
    head_before = _rev_parse(repo, "HEAD")

    # Overlay only profile.md onto base; add a new doc.
    branch_ref = await store.branch_commit(
        U1,
        "evolve/t1",
        {
            "memory/profile.md": _file("d-p", "profile", "- 改写。[cite: src-02 ¶1] <!-- c:aa11 -->"),
            "memory/products/atlas.md": _file("d-a", "atlas", "- 产品台账。[cite: src-01 ¶0] <!-- c:cc33 -->"),
        },
        "evolve t1",
        base=base,
    )

    # HEAD and the working tree never moved — the whole point of the plumbing path.
    assert _rev_parse(repo, "HEAD") == head_before
    assert _porcelain(repo) == ""

    # branch_head reports the new commit; it is not HEAD.
    head = await store.branch_head(U1, "evolve/t1")
    assert head is not None and head.ref == branch_ref.ref
    assert head.ref != head_before

    # Overlay semantics: reading the branch shows the overlaid + the untouched + the new path.
    from pneuma_knowledge_core.domain.snapshot import SnapshotRef

    branch_docs = {d.path: d for d in await store.list(U1, at=SnapshotRef(ref="evolve/t1"))}
    assert "改写。" in branch_docs["memory/profile.md"].body  # overlaid
    assert "程野。" in branch_docs["memory/people/cheng-ye.md"].body  # preserved (not in files)
    assert "memory/products/atlas.md" in branch_docs  # new path added

    # The main line still sees the base content (branch is isolated).
    main_docs = {d.path: d for d in await store.list(U1)}
    assert "基线。" in main_docs["memory/profile.md"].body
    assert "memory/products/atlas.md" not in main_docs


async def test_branch_commit_repoints_and_delete_tolerates_missing(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    base = await store.commit_patch(
        U1, {"memory/profile.md": _file("d-p", "profile", "- x。[cite: src-01 ¶0] <!-- c:aa11 -->")},
        message="base",
    )
    r1 = await store.branch_commit(
        U1, "evolve/t1",
        {"memory/profile.md": _file("d-p", "profile", "- v1。[cite: src-01 ¶0] <!-- c:aa11 -->")},
        "evolve v1",
        base=base,
    )
    # Re-running the same branch force-repoints it (an evolve re-run overwrites its branch).
    r2 = await store.branch_commit(
        U1, "evolve/t1",
        {"memory/profile.md": _file("d-p", "profile", "- v2。[cite: src-01 ¶0] <!-- c:aa11 -->")},
        "evolve v2",
        base=base,
    )
    assert r2.ref != r1.ref
    head = await store.branch_head(U1, "evolve/t1")
    assert head is not None and head.ref == r2.ref

    # read_meta_at reads a non-.md meta file off any ref.
    await store.write_meta(U1, "skill/manifest.json", '{"base_version": "v3"}', message="m")
    assert await store.read_meta_at(U1, "skill/manifest.json", "HEAD") == '{"base_version": "v3"}'

    # delete removes the branch; a second delete (and a never-existed branch) is tolerated.
    await store.delete_branch(U1, "evolve/t1")
    assert await store.branch_head(U1, "evolve/t1") is None
    await store.delete_branch(U1, "evolve/t1")
    await store.delete_branch(U1, "evolve/never")


async def test_branch_commit_works_with_relative_canonical_root(tmp_path, monkeypatch):
    """The deployed default is canonical_root=./data/canonical — RELATIVE. `git -C <repo>`
    chdirs before resolving GIT_INDEX_FILE, so a relative throwaway-index path gets
    re-rooted inside the repo and every plumbing call dies with exit 128. This pins the
    absolute-index fix; it is exactly the shape the local dev stack runs with."""
    monkeypatch.chdir(tmp_path)
    store = GitCanonicalStore("./data/canonical")
    base = await store.commit_patch(
        U1,
        {"memory/profile.md": _file("d-p", "profile", "- 基线。[cite: src-01 ¶0] <!-- c:aa11 -->")},
        message="base",
    )
    branch_ref = await store.branch_commit(
        U1,
        "evolve/rel",
        {"memory/topics/t.md": _file("d-t", "t", "- 新增。[cite: src-01 ¶0] <!-- c:bb22 -->")},
        "evolve rel",
        base=base,
    )
    head = await store.branch_head(U1, "evolve/rel")
    assert head is not None and head.ref == branch_ref.ref


# ============================================== the archive's write verb: move_documents


async def test_move_documents_archives_a_page_with_its_volumes_and_keeps_its_history(
    tmp_path,
):
    """A `git mv`, not a rewrite (docs/design/archive.md §2.1): same bytes, same anchors,
    same `doc_id`, and `git log --follow` reads straight through the boundary."""
    store = GitCanonicalStore(str(tmp_path))
    body = "- Aurora 已交付。[cite: src-01 ¶0] <!-- c:aa11 -->"
    volume_body = "- Aurora 的早期决定。[cite: src-02 ¶0] <!-- c:bb22 -->"
    first = await store.commit_patch(
        U1,
        {
            "work/products/aurora.md": _file("d-aurora", "aurora", body),
            "work/products/aurora/a01.md": _file("d-aurora-a01", "aurora", volume_body),
            "work/products/borealis.md": _file("d-borealis", "borealis", body),
        },
        message="compile 1",
    )
    before = {doc.path: doc for doc in await store.list(U1)}

    moved = await store.move_documents(
        U1,
        [
            ("work/products/aurora.md", "archive/work/products/aurora.md"),
            (
                "work/products/aurora/a01.md",
                "archive/work/products/aurora/a01.md",
            ),
        ],
        message="archive: Aurora shipped in June\n\nSkill-Version: v1",
    )
    assert moved.ref != first.ref

    after = {doc.path: doc for doc in await store.list(U1)}
    assert sorted(after) == [
        "archive/work/products/aurora.md",
        "archive/work/products/aurora/a01.md",
        "work/products/borealis.md",
    ]
    # Byte-for-byte the same document on the other side of the move.
    original = before["work/products/aurora.md"]
    archived = after["archive/work/products/aurora.md"]
    assert archived.doc_id == original.doc_id
    assert archived.body == original.body
    assert archived.frontmatter == original.frontmatter
    assert after["archive/work/products/aurora/a01.md"].body == before[
        "work/products/aurora/a01.md"
    ].body

    repo = store.repo_path(U1)
    # The tree on DISK, not only in the commit. git tracks files, so the `aurora/` folder the
    # volume left behind is git's business no longer — it would simply sit there empty. The
    # move prunes what it emptied and stops the moment a directory still holds something:
    # `work/products/` keeps borealis, so it stays.
    assert not (repo / "work" / "products" / "aurora").exists()
    assert (repo / "work" / "products" / "borealis.md").is_file()

    follow = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "log",
            "--follow",
            "--format=%H",
            "--",
            "archive/work/products/aurora.md",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert first.ref in follow, "--follow must reach the pre-archive commit"

    # Unarchiving is the same call with the pairs reversed.
    await store.move_documents(
        U1,
        [
            ("archive/work/products/aurora.md", "work/products/aurora.md"),
            (
                "archive/work/products/aurora/a01.md",
                "work/products/aurora/a01.md",
            ),
        ],
        message="unarchive: Aurora is current again",
    )
    back = {doc.path: doc for doc in await store.list(U1)}
    assert sorted(back) == sorted(before)
    assert back["work/products/aurora.md"].body == original.body
    # And the archive shell is gone with the last page in it: an empty `archive/` in the
    # working tree is a folder that names a subject the library is no longer keeping there.
    assert not (repo / "archive").exists()
    assert (repo / "work" / "products" / "aurora" / "a01.md").is_file()
    # Nothing was pruned into the commit: the prune touches untracked empty directories only,
    # so the repository is clean afterwards exactly as it was before.
    assert not subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


async def test_a_move_writes_the_record_onto_the_path_it_just_vacated(tmp_path):
    """Archiving is ONE commit carrying both halves of the act: the page leaves for
    `archive/`, and the record lands on the live path the move freed. A tree in which the
    page has gone and the record has not arrived is the state this verb exists to prevent
    (docs/design/archive.md §2.3)."""
    store = GitCanonicalStore(str(tmp_path))
    page = _file("d-aurora", "aurora", "- Aurora 已交付。[cite: src-01 ¶0] <!-- c:aa11 -->")
    record = _file("d-aurora", "aurora", "- Aurora 曾是交付项目 —— 已归档 <!-- c:cc33 -->")
    await store.commit_patch(U1, {"work/aurora.md": page}, message="compile 1")

    moved = await store.move_documents(
        U1,
        [("work/aurora.md", "archive/work/aurora.md")],
        message="archive Aurora",
        writes={"work/aurora.md": record},
    )

    repo = store.repo_path(U1)
    assert (repo / "archive" / "work" / "aurora.md").read_text(encoding="utf-8") == page
    assert (repo / "work" / "aurora.md").read_text(encoding="utf-8") == record
    assert _porcelain(repo) == ""  # one commit, nothing left staged or dirty
    # One commit for the whole act, and the log shows the rename beside the new file.
    names = subprocess.run(
        ["git", "-C", str(repo), "show", "--name-status", "--format=", moved.ref],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "archive/work/aurora.md" in names and "work/aurora.md" in names


async def test_unarchiving_removes_the_record_and_moves_the_page_back_in_one_commit(
    tmp_path,
):
    store = GitCanonicalStore(str(tmp_path))
    page = _file("d-aurora", "aurora", "- Aurora 已交付。[cite: src-01 ¶0] <!-- c:aa11 -->")
    record = _file("d-aurora", "aurora", "- Aurora 曾是交付项目 —— 已归档 <!-- c:cc33 -->")
    await store.commit_patch(U1, {"work/aurora.md": page}, message="compile 1")
    await store.move_documents(
        U1,
        [("work/aurora.md", "archive/work/aurora.md")],
        message="archive Aurora",
        writes={"work/aurora.md": record},
    )

    await store.move_documents(
        U1,
        [("archive/work/aurora.md", "work/aurora.md")],
        message="unarchive Aurora",
        removals=["work/aurora.md"],
    )

    repo = store.repo_path(U1)
    # BYTE FOR BYTE: the page that went in is the page that came back.
    assert (repo / "work" / "aurora.md").read_text(encoding="utf-8") == page
    assert not (repo / "archive").exists()
    assert _porcelain(repo) == ""


async def test_a_write_onto_a_path_that_survives_the_moves_is_refused(tmp_path):
    """The record only ever lands where the move made room for it. A write that would
    overwrite a page is a write that could lose one, so it is refused before anything
    happens."""
    store = GitCanonicalStore(str(tmp_path))
    page = _file("d-aurora", "aurora", "- Aurora 已交付。<!-- c:aa11 -->")
    await store.commit_patch(U1, {"work/aurora.md": page}, message="compile 1")

    with pytest.raises(CanonicalMoveError) as err:
        await store.move_documents(
            U1, [], message="never", writes={"work/aurora.md": "overwritten"}
        )
    assert err.value.reason == "write path already exists"
    repo = store.repo_path(U1)
    assert (repo / "work" / "aurora.md").read_text(encoding="utf-8") == page
    assert _porcelain(repo) == ""


async def test_removing_a_path_the_library_does_not_hold_is_refused(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1, {"work/aurora.md": _file("d", "aurora", "- x <!-- c:aa11 -->")}, message="c"
    )
    with pytest.raises(CanonicalMoveError) as err:
        await store.move_documents(U1, [], message="never", removals=["work/ghost.md"])
    assert err.value.reason == "path is not in the library"


async def test_a_failed_commit_rolls_back_the_record_and_the_removal_too(
    tmp_path, monkeypatch
):
    """The rollback is SCOPED to what this call did — all three kinds of it. A record left
    on disk after a failed archive would ride into the next unrelated compile's `add -A`."""
    store = GitCanonicalStore(str(tmp_path))
    page = _file("d-aurora", "aurora", "- Aurora 已交付。<!-- c:aa11 -->")
    record = _file("d-aurora", "aurora", "- 已归档 <!-- c:cc33 -->")
    await store.commit_patch(
        U1,
        {"work/aurora.md": page, "work/atlas.md": _file("d-atlas", "atlas", "- y <!-- c:bb22 -->")},
        message="compile 1",
    )
    _fail_on(monkeypatch, lambda args: "commit" in args)

    with pytest.raises(Exception):
        await store.move_documents(
            U1,
            [("work/aurora.md", "archive/work/aurora.md")],
            message="archive Aurora",
            writes={"work/aurora.md": record},
            removals=["work/atlas.md"],
        )

    repo = store.repo_path(U1)
    assert (repo / "work" / "aurora.md").read_text(encoding="utf-8") == page
    assert (repo / "work" / "atlas.md").is_file()
    assert not (repo / "archive").exists()
    assert _porcelain(repo) == ""


async def test_a_write_that_fails_its_own_add_is_still_removed_by_the_rollback(
    tmp_path, monkeypatch
):
    """The file exists the moment `write_text` returns, not the moment `git add` succeeds.

    Recorded after the `add`, an `add` that failed left `written` — the rollback's ONE
    authority over the files this call created — silent about a file only this call could
    have written. It then stays on disk untracked, and the next writer's `add -A` commits it
    under an unrelated message. Asserted over a write onto a path this call did not also
    vacate, because that is the case where the authority is the only thing that removes it:
    a record landing on a path a move emptied is additionally overwritten by the rename's own
    fallback, which would hide the defect rather than fix it.
    """
    store = GitCanonicalStore(str(tmp_path))
    page = _file("d-aurora", "aurora", "- Aurora 已交付。<!-- c:aa11 -->")
    await store.commit_patch(U1, {"work/aurora.md": page}, message="compile 1")
    _fail_on(monkeypatch, lambda args: bool(args) and args[0] == "add")

    with pytest.raises(Exception):
        await store.move_documents(
            U1,
            [],
            message="write one page",
            writes={"work/atlas.md": _file("d-atlas", "atlas", "- 已归档 <!-- c:cc33 -->")},
        )

    repo = store.repo_path(U1)
    assert not (repo / "work" / "atlas.md").exists()
    assert (repo / "work" / "aurora.md").read_text(encoding="utf-8") == page
    # Nothing left for the next writer's `add -A` to sweep into its own commit.
    assert _porcelain(repo) == ""


async def test_a_move_prunes_only_what_it_emptied(tmp_path):
    """The one place this adapter removes something it did not create, so its bounds are
    their own test: a sibling page keeps its folder, and an untracked file does too."""
    store = GitCanonicalStore(str(tmp_path))
    body = "- 一条 claim。[cite: src-01 ¶0] <!-- c:aa11 -->"
    await store.commit_patch(
        U1,
        {
            "work/threads/aurora.md": _file("d-aurora", "aurora", body),
            "work/threads/echo.md": _file("d-echo", "echo", body),
            "work/notes/atlas.md": _file("d-atlas", "atlas", body),
        },
        message="compile 1",
    )
    repo = store.repo_path(U1)
    # A file this adapter never wrote and does not read, committed so the tree stays clean
    # (a move refuses over a dirty repository, which is a different guarantee tested above).
    keep = repo / "work" / "notes" / "keep.txt"
    keep.write_text("someone else's file", encoding="utf-8")
    for args in (["add", "--", "work/notes/keep.txt"], ["commit", "-q", "-m", "stray"]):
        subprocess.run(
            ["git", "-C", str(repo), "-c", "user.email=t@local", "-c", "user.name=t"]
            + args,
            check=True,
            capture_output=True,
        )

    await store.move_documents(
        U1,
        [("work/threads/aurora.md", "archive/work/threads/aurora.md")],
        message="archive one of two",
    )
    # echo is still there, so nothing above it is empty and nothing is removed.
    assert (repo / "work" / "threads").is_dir()

    await store.move_documents(
        U1,
        [
            ("work/threads/echo.md", "archive/work/threads/echo.md"),
            ("work/notes/atlas.md", "archive/work/notes/atlas.md"),
        ],
        message="archive the rest",
    )
    # `threads/` is empty now and goes; `notes/` holds a file nobody here wrote, so it stays
    # — `rmdir` refusing IS the check, and the walk stops there rather than at `work/`.
    assert not (repo / "work" / "threads").exists()
    assert (repo / "work" / "notes").is_dir()
    assert keep.is_file()
    assert (repo / "work").is_dir()


async def test_move_documents_refuses_a_taken_destination_and_commits_nothing(tmp_path):
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1,
        {
            "work/a.md": _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->"),
            "archive/work/a.md": _file(
                "d-a-old", "a", "- 旧的 A。[cite: src-02 ¶0] <!-- c:bb22 -->"
            ),
            "work/b.md": _file("d-b", "b", "- B。[cite: src-03 ¶0] <!-- c:cc33 -->"),
        },
        message="base",
    )
    head_before = (await store.snapshots(U1))[0].ref
    tree_before = {doc.path: doc.body for doc in await store.list(U1)}

    with pytest.raises(CanonicalMoveError) as taken:
        await store.move_documents(
            U1,
            [
                ("work/b.md", "archive/work/b.md"),
                ("work/a.md", "archive/work/a.md"),  # already occupied
            ],
            message="archive both",
        )
    assert taken.value.path == "archive/work/a.md"

    with pytest.raises(CanonicalMoveError) as missing:
        await store.move_documents(
            U1,
            [("work/nowhere.md", "archive/work/nowhere.md")],
            message="archive a ghost",
        )
    assert missing.value.path == "work/nowhere.md"

    # Both refusals happened before the first `git mv`: nothing moved, nothing committed.
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before


def _tree_status(store: GitCanonicalStore, user: UserId) -> str:
    return subprocess.run(
        ["git", "-C", str(store.repo_path(user)), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _fail_on(monkeypatch, predicate):
    """Make `_run` raise the first time `predicate(args)` holds; real git otherwise.

    The preflight rules out what it can SEE before the first rename; it cannot rule out the
    filesystem refusing a later one, or the commit itself failing. This is that case, and
    what it is here to prove is that the tree does not stay half-renamed."""
    real = GitCanonicalStore._run
    fired: list[bool] = []

    def run(repo, *args):
        if predicate(args) and not fired:
            fired.append(True)
            raise subprocess.CalledProcessError(1, ["git", *args], stderr="boom")
        return real(repo, *args)

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(run))


async def _two_movable_documents(store: GitCanonicalStore):
    await store.commit_patch(
        U1,
        {
            "work/a.md": _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->"),
            "work/b.md": _file("d-b", "b", "- B。[cite: src-02 ¶0] <!-- c:bb22 -->"),
        },
        message="base",
    )
    head = (await store.snapshots(U1))[0].ref
    tree = {doc.path: doc.body for doc in await store.list(U1)}
    return head, tree


async def test_move_documents_rolls_back_after_second_mv_failure(tmp_path, monkeypatch):
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)

    moves = [
        ("work/a.md", "archive/work/a.md"),
        ("work/b.md", "archive/work/b.md"),
    ]
    seen: list[int] = []

    def second_mv(args):
        if args and args[0] == "mv":
            seen.append(1)
            return len(seen) == 2
        return False

    _fail_on(monkeypatch, second_mv)

    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(U1, moves, message="archive both")

    # The first rename LANDED and was then undone — by its own inverse, not by a `reset
    # --hard`: the working tree is clean, HEAD has not moved, and every document is at the
    # path it was at.
    assert _tree_status(store, U1) == ""
    assert not (store.repo_path(U1) / "archive").exists()
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before

    # And the repository is usable straight after: the same move succeeds unpatched.
    monkeypatch.undo()
    moved = await store.move_documents(U1, moves, message="archive both")
    assert moved.ref != head_before
    assert sorted(doc.path for doc in await store.list(U1)) == [
        "archive/work/a.md",
        "archive/work/b.md",
    ]


async def test_move_documents_rolls_back_after_commit_failure(tmp_path, monkeypatch):
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)

    _fail_on(monkeypatch, lambda args: "commit" in args)

    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(
            U1,
            [
                ("work/a.md", "archive/work/a.md"),
                ("work/b.md", "archive/work/b.md"),
            ],
            message="archive both",
        )

    # Every rename was staged and none of them committed — the exact state that would
    # otherwise ride into the NEXT writer's commit as an unrelated, unexplained move. The
    # inverse renames unstage both sides as they go, so the index comes back with the tree.
    assert _tree_status(store, U1) == ""
    assert not (store.repo_path(U1) / "archive").exists()
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before


async def test_residue_from_a_crashed_move_is_recovered_at_the_next_write(
    tmp_path, caplog
):
    """Staged renames left by a process that died are DISCARDED by the next writer.

    This is the one thing they must not be allowed to do: `commit_patch` stages with
    `add -A`, so residue left in place would ride into the next unrelated compile's commit —
    a crashed archive landing inside a compile, under its message. The licence to discard is
    the IN-FLIGHT MARKER the dead writer left beside the mess: it says the mess is this
    adapter's own. The record of what was removed is the WARNING line, which names every
    path and the operation that made them.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    # A crash mid-`move_documents`: the marker is written (as the real sequence writes it
    # before its first git command), the first rename is staged, and the process is gone —
    # gone being the operative word, so the claim names a pid that really has exited.
    _write_dead_marker(
        store,
        repo,
        "move_documents",
        paths=["work/a.md", "archive/work/a.md"],
    )
    (repo / "archive" / "work").mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(repo), "mv", "--", "work/a.md", "archive/work/a.md"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert _tree_status(store, U1) != ""

    with caplog.at_level("WARNING"):
        ref = await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="an unrelated compile",
        )

    # The commit is EXACTLY the compile's own file — the residue is not in it.
    assert _commit_names(repo, ref.ref) == {"work/c.md"}
    # …and the residue is gone rather than left for the commit after this one.
    assert _tree_status(store, U1) == ""
    assert (repo / "work/a.md").is_file()
    assert not (repo / "archive").exists()
    assert {doc.path for doc in await store.list(U1)} == {
        "work/a.md",
        "work/b.md",
        "work/c.md",
    }
    assert ref.ref != head_before
    assert tree_before  # the base this all started from

    # …and the claim went with it: nothing is in flight over a clean tree.
    assert not store._marker_path(repo).exists()

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "crash residue" in message
        and "commit_patch" in message  # the operation that found it
        and "move_documents" in message  # the operation that left it, off the marker
        and "archive/work/a.md" in message
        # …and the footprint it was allowed to reach, which is the line's other half now.
        and "footprint was: archive/work/a.md, work/a.md" in message
        for message in warnings
    ), warnings


# ------------------------------------------------- the in-flight marker: whose mess is it


def _read_marker(store: GitCanonicalStore, user: UserId) -> dict:
    return json.loads(store._marker_path(store.repo_path(user)).read_text("utf-8"))


async def test_a_dirty_tree_with_no_marker_is_refused_and_left_byte_identical(tmp_path):
    """The correction. Uncommitted work this adapter cannot prove it made is NOT residue.

    The old premise was "only this adapter writes", which was never true of a git repository
    sitting in a working directory: a person editing `data/canonical/<user>/`, or a coding
    agent with a shell in the project directory, leaves exactly this state — and the next
    compile's `reset --hard` erased it, with one WARNING line as the only trace. Now the
    absence of the in-flight marker IS the proof that the work is somebody else's, and the
    write is refused having touched nothing.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    # Somebody edits a page by hand and leaves a new one beside it. No marker: nothing in
    # this framework is mid-write.
    edited = repo / "work/a.md"
    edited.write_text(edited.read_text("utf-8") + "\n- 手写的一句。\n", encoding="utf-8")
    (repo / "work/scratch.md").write_text("draft\n", encoding="utf-8")
    before = {path: (repo / path).read_text("utf-8") for path in ("work/a.md", "work/scratch.md")}
    head_before = (await store.snapshots(U1))[0].ref

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="a compile that must not run",
        )
    # It NAMES what it refused over — both paths, so the operator can go and look.
    assert set(refused.value.paths) == {"work/a.md", "work/scratch.md"}
    assert refused.value.detail.startswith("canonical_dirty:")
    assert "work/a.md" in str(refused.value)

    # Byte for byte: their edits, and the library, exactly as they were.
    for path, text in before.items():
        assert (repo / path).read_text("utf-8") == text
    assert (await store.snapshots(U1))[0].ref == head_before
    assert not (repo / "work/c.md").exists()

    # Every other mutating verb answers the same way, because they all enter the same way.
    with pytest.raises(CanonicalDirtyError):
        await store.move_documents(
            U1, [("work/b.md", "archive/work/b.md")], message="archive b"
        )
    with pytest.raises(CanonicalDirtyError):
        await store.write_meta(U1, "skill/manifest.json", "{}\n", message="skill")
    assert (repo / "work/scratch.md").is_file()

    # …and once the person commits their own work, the framework writes again.
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=a@b", "-c", "user.name=a",
         "commit", "-q", "-m", "mine"],
        check=True,
        capture_output=True,
    )
    ref = await store.commit_patch(
        U1,
        {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
        message="the compile, now",
    )
    assert _commit_names(repo, ref.ref) == {"work/c.md"}


async def test_a_stale_marker_over_a_clean_tree_is_dropped_and_the_write_proceeds(
    tmp_path,
):
    """A marker with nothing behind it is not a fault: a call that failed AFTER its rollback
    got the tree back leaves exactly this. The clean tree is the answer — there is nothing to
    recover and nothing to refuse — so the claim is dropped and the sequence runs."""
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    store._write_marker(repo, "move_documents", paths=["work/a.md"])
    assert store._marker_path(repo).exists()

    ref = await store.commit_patch(
        U1,
        {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
        message="an ordinary compile",
    )
    assert _commit_names(repo, ref.ref) == {"work/c.md"}
    assert not store._marker_path(repo).exists()


async def test_a_crash_between_the_marker_and_the_commit_is_recovered_by_the_next_call(
    tmp_path, monkeypatch, caplog
):
    """End to end, with no hand-written marker: the real sequence claims the tree, the
    PROCESS DIES after its first `git mv`, and the NEXT mutating call recognizes the mess as
    this adapter's own and clears it.

    Process death is simulated exactly, and the simulation is the point: the rollback is made
    to fail (nothing is undone) AND `_clear_marker` is made a no-op, because a killed process
    runs no `finally`. That is the ONLY way a claim survives a call now — see
    `test_a_refused_move_leaves_no_claim_behind`, where the same adapter, still alive,
    releases its claim on the way out of a refusal.

    This is the pair the two branches hang on. The same dirty tree without the claim is the
    test above, and it is refused."""
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    # Die immediately after the first rename — inside `move_documents`, past the marker.
    monkeypatch.setattr(
        GitCanonicalStore,
        "_rollback",
        lambda self, *a, **k: (_ for _ in ()).throw(RuntimeError("killed")),
    )
    # The process is GONE: no `finally` runs, so the claim it wrote stays standing.
    monkeypatch.setattr(
        GitCanonicalStore, "_clear_marker", lambda self, repo, operation=None: None
    )
    _fail_on(monkeypatch, lambda args: args[:1] == ("mv",) and args[-1].startswith("archive/work/b"))
    with pytest.raises(Exception):
        await store.move_documents(
            U1,
            [("work/a.md", "archive/work/a.md"), ("work/b.md", "archive/work/b.md")],
            message="an archive that dies",
        )

    # The state a killed writer leaves: a dirty tree AND its own claim on it.
    assert _tree_status(store, U1) != ""
    assert _read_marker(store, U1)["operation"] == "move_documents"
    # The one thing this in-process simulation cannot simulate: the claim it just wrote names
    # THIS still-running pid, and a live claimant is not a death (the next call would refuse
    # it — `test_a_claim_whose_process_is_alive_is_refused_not_recovered`). A real kill takes
    # the pid with it and leaves the rest of the claim — including the FOOTPRINT the real body
    # recorded before its first rename, which is what the recovery is then bounded by.
    dead = _kill_claimant(store, repo)
    assert set(_read_marker(store, U1)["paths"]) == {
        "work/a.md",
        "work/b.md",
        "archive/work/a.md",
        "archive/work/b.md",
    }
    monkeypatch.undo()

    with caplog.at_level("WARNING"):
        ref = await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert _commit_names(repo, ref.ref) == {"work/c.md"}
    assert _tree_status(store, U1) == ""
    assert not store._marker_path(repo).exists()
    assert {doc.path for doc in await store.list(U1)} == {
        "work/a.md",
        "work/b.md",
        "work/c.md",
    }
    assert any(
        "crash residue" in r.getMessage() and str(dead) in r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING"
    )


async def test_a_claim_whose_process_is_alive_is_refused_not_recovered(tmp_path):
    """A CLAIM IS A LICENCE ONLY ONCE ITS CLAIMANT IS GONE.

    The recovery branch means one thing — "the process writing here died mid-write" — and a
    marker whose pid still answers `kill(pid, 0)` says the opposite out loud. Taking the
    file's mere presence as proof was the hole: a `_clear_marker` whose unlink failed left a
    whole claim standing after an ORDERLY exit, and the next writer would then `reset --hard`
    + `clean -fd` a human's later edits away on the strength of it. So the pid is checked, our
    own included — it is the likeliest live answer, since the flock already excludes a second
    live adapter process on this repository.
    """
    store = GitCanonicalStore(str(tmp_path))
    head, tree = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    # A claim naming a process that is very much alive — this one — over a dirty tree.
    store._write_marker(repo, "move_documents", paths=["work/a.md", "work/new.md"])
    assert _read_marker(store, U1)["pid"] == os.getpid()
    (repo / "work" / "a.md").write_text("an afternoon of somebody's edits\n", encoding="utf-8")
    (repo / "work" / "new.md").write_text("and a page they started\n", encoding="utf-8")

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert set(refused.value.paths) == {"work/a.md", "work/new.md"}
    # One machine string across every face; the claim rides in the text, because "there is a
    # marker and it was still refused" is otherwise unreadable.
    assert refused.value.detail == "canonical_dirty:work/a.md,work/new.md"
    assert "move_documents" in str(refused.value)
    assert str(os.getpid()) in str(refused.value)

    # NOTHING was discarded, and nothing was written.
    assert (repo / "work" / "a.md").read_text(encoding="utf-8") == (
        "an afternoon of somebody's edits\n"
    )
    assert (repo / "work" / "new.md").is_file()
    assert (await store.snapshots(U1))[0].ref == head
    assert not (repo / "work" / "c.md").exists()
    assert tree  # the base this all started from
    # The claim standing here is this call's OWN, and it is gone: the entry order writes the
    # claim before it reads the tree (which is how a `.git/` that will not take one stops a
    # mutation before it can destroy anything), and the `finally` releases it on this refusal
    # like on every other exit. The previous claim was replaced, which is sound under the
    # lock — no other live body of this adapter can be inside a mutation here — and the next
    # call meets a dirty tree with NO claim at all, which refuses just the same.
    assert not store._marker_path(repo).exists()


async def test_a_claim_whose_process_is_gone_is_still_recovered(tmp_path, caplog):
    """The other half of both rules, stated on its own: a DEAD claimant over STAGED residue
    still licenses the recovery, exactly as before. The two checks narrow the branch to real
    deaths of this adapter's own writers; they do not close it — residue left by a killed
    writer would otherwise ride into the next unrelated commit's `add -A` forever.

    The residue is staged because a real one always is: every mutating body of this adapter
    stages before it commits (`add -A`, the move's own `rm`/`mv`/`add`, the manifest's one
    path), so the index is what separates a dead writer's leftovers from a person's edit."""
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    dead = _write_dead_marker(store, repo, "move_documents", paths=["work/a.md"])
    (repo / "work" / "a.md").write_text("a dead writer's half-written page\n", encoding="utf-8")
    _stage(repo, "work/a.md")  # …and it got as far as staging, as every writer here does

    with caplog.at_level("WARNING"):
        ref = await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert _commit_names(repo, ref.ref) == {"work/c.md"}
    assert _tree_status(store, U1) == ""
    assert not store._marker_path(repo).exists()
    assert any(
        "crash residue" in r.getMessage() and str(dead) in r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING"
    )


# ------------------------------- the claim is not the whole proof: WHAT WAS THIS WRITER ON?
#
# A claim answers WHO DIED. On its own it cannot answer WHAT THEY WERE TOUCHING — and a
# repository is not one writer's: a dead writer's own residue and a person's later file land
# in the same `git status`, so a whole-tree `reset --hard` + `clean -fd` took both. Every
# mutating body here knows its paths BEFORE it writes any of them, so the claim records them,
# the recovery runs only while nothing outside that list is dirty, and it reaches only inside
# it when it runs.


def _stage(repo: pathlib.Path, *paths: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), "add", "--", *paths], check=True, capture_output=True
    )


def _snapshot_of(repo: pathlib.Path) -> dict[str, str]:
    """Every file in the working tree except `.git/`, so a refusal can be shown to be inert."""
    return {
        str(path.relative_to(repo)): path.read_text("utf-8")
        for path in sorted(repo.rglob("*"))
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    }


async def test_a_dead_claim_over_an_edit_outside_its_footprint_is_refused(tmp_path):
    """A provably dead claim standing over a HAND EDIT it never named: refused.

    The claim is real proof of a death — the pid is gone — and the residue is still not that
    writer's: what it was writing was `work/c.md`, which it recorded before it wrote a byte,
    and `work/a.md` is somebody's uncommitted work that happens to share the repository.
    Under the rule this replaces the pid alone was the licence, and this edit went with it."""
    store = GitCanonicalStore(str(tmp_path))
    head_before, _tree = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    edited = repo / "work" / "a.md"
    edited.write_text(edited.read_text("utf-8") + "\n- 手写的一句。\n", encoding="utf-8")
    before = _snapshot_of(repo)
    _write_dead_marker(store, repo, "commit_patch", paths=["work/c.md"])

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="a compile that must not run",
        )
    assert set(refused.value.paths) == {"work/a.md"}
    assert refused.value.detail == "canonical_dirty:work/a.md"
    # The message says WHICH half of the proof was missing, and what the claim DID cover —
    # "there is a claim, its writer is gone, and it was still refused" is otherwise
    # unreadable.
    assert refused.value.claimed_by == "commit_patch"
    assert refused.value.unproven is None
    assert refused.value.outside == ("work/a.md",)
    assert refused.value.covered == ("work/c.md",)
    assert "OUTSIDE what it recorded" in str(refused.value)
    assert "That claim covered: work/c.md." in str(refused.value)

    assert _snapshot_of(repo) == before  # byte for byte
    assert (await store.snapshots(U1))[0].ref == head_before


async def test_a_dead_claim_over_untracked_files_outside_its_footprint_is_refused(tmp_path):
    """The same rule for the other thing a person or an agent leaves: files git never saw.

    `clean -fd` is what would have taken these, and an untracked file is exactly what an
    agent writing into `data/canonical/<user>/` leaves behind. The claim beside them names a
    page in `work/`, so a whole untracked `notes/` directory is outside it — and every file
    in it is NAMED, one by one, because `_dirty_paths` asks for `--untracked-files=all`
    rather than letting git collapse the directory to `notes/`."""
    store = GitCanonicalStore(str(tmp_path))
    head_before, _tree = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    (repo / "work" / "scratch.md").write_text("someone's draft\n", encoding="utf-8")
    (repo / "notes").mkdir()
    (repo / "notes" / "plan.md").write_text("an agent's plan\n", encoding="utf-8")
    before = _snapshot_of(repo)
    _write_dead_marker(store, repo, "commit_patch", paths=["work/c.md"])

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.move_documents(
            U1, [("work/a.md", "archive/work/a.md")], message="archive a"
        )
    # Every untracked file individually, not the directory shorthand.
    assert set(refused.value.paths) == {"notes/plan.md", "work/scratch.md"}
    assert set(refused.value.outside or ()) == {"notes/plan.md", "work/scratch.md"}
    assert "OUTSIDE what it recorded" in str(refused.value)

    assert _snapshot_of(repo) == before
    assert not (repo / "archive").exists()
    assert (await store.snapshots(U1))[0].ref == head_before


async def test_a_mixed_tree_of_real_residue_and_a_later_file_is_refused_whole(tmp_path):
    """THE FINDING. A dead writer's residue AND somebody's later untracked file, together.

    Every part of the old proof holds here: the claimant is provably dead, and the residue is
    STAGED — a real crashed `move_documents` with its rename in the index. And beside it sits
    a file nobody in this framework wrote. Under "provably dead AND something is staged" the
    whole tree was reset and cleaned, and that file went with the residue.

    The footprint separates them without having to judge: the dead writer declared both sides
    of its rename and nothing else, so `notes/plan.md` is outside it. The refusal is WHOLE —
    the recoverable half is not recovered either — because a claim is a precondition on the
    state of the tree, not a filter over it: a call that cleaned the part it recognized would
    be deciding on its own which half of a mess it had made."""
    store = GitCanonicalStore(str(tmp_path))
    head_before, _tree = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    # The genuine article: a crashed `move_documents`, its first rename staged.
    _write_dead_marker(
        store, repo, "move_documents", paths=["work/a.md", "archive/work/a.md"]
    )
    (repo / "archive" / "work").mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(repo), "mv", "--", "work/a.md", "archive/work/a.md"],
        check=True,
        capture_output=True,
    )
    # …and a person's, or an agent's, file that has nothing to do with it.
    (repo / "notes").mkdir()
    (repo / "notes" / "plan.md").write_text("an afternoon of somebody's work\n", encoding="utf-8")
    before = _snapshot_of(repo)
    staged_before = _tree_status(store, U1)

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the compile that must not run",
        )
    assert refused.value.outside == ("notes/plan.md",)
    assert set(refused.value.covered or ()) == {"work/a.md", "archive/work/a.md"}
    assert "OUTSIDE what it recorded" in str(refused.value)

    # BOTH intact: the person's file, and the residue that WAS recoverable, byte for byte.
    assert _snapshot_of(repo) == before
    assert _tree_status(store, U1) == staged_before
    assert (repo / "notes" / "plan.md").read_text("utf-8") == (
        "an afternoon of somebody's work\n"
    )
    assert (repo / "archive" / "work" / "a.md").is_file()
    assert not (repo / "work" / "c.md").exists()
    assert (await store.snapshots(U1))[0].ref == head_before


async def test_a_hand_git_add_outside_the_footprint_is_refused(tmp_path):
    """The other half of the same finding: STAGED is not proof of authorship either.

    A person, or a coding agent with a shell in the project directory, runs `git add`. The
    index is then dirty on a path no writer of this framework ever declared, and the old rule
    — "the claimant is provably dead AND something is staged" — read that as the dead
    writer's own work and deleted it. The footprint says otherwise, and says it without
    having to guess what a human would or would not stage."""
    store = GitCanonicalStore(str(tmp_path))
    head_before, _tree = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    _write_dead_marker(store, repo, "write_meta", paths=["skill/manifest.json"])
    (repo / "work" / "mine.md").write_text("someone's page, staged by hand\n", encoding="utf-8")
    _stage(repo, "work/mine.md")
    before = _snapshot_of(repo)

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the compile that must not run",
        )
    assert refused.value.paths == ("work/mine.md",)
    assert refused.value.outside == ("work/mine.md",)
    assert refused.value.covered == ("skill/manifest.json",)

    assert _snapshot_of(repo) == before
    assert _tree_status(store, U1) != ""  # still staged, exactly as they left it
    assert (await store.snapshots(U1))[0].ref == head_before


async def test_a_ref_only_claims_empty_footprint_licenses_nothing(tmp_path):
    """An EMPTY footprint is a licence over nothing, and it is recorded rather than omitted.

    `tag`, `branch_commit`, `delete_branch` and the repository initialization write objects
    and refs inside `.git/` and touch not one working-tree path, so their claims say so. A
    dead one of those standing over a dirty tree — however convincingly the residue is staged
    — covers none of it and recovers none of it."""
    store = GitCanonicalStore(str(tmp_path))
    head_before, _tree = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    _write_dead_marker(store, repo, "tag", paths=[])
    (repo / "work" / "a.md").write_text("residue that looks like ours\n", encoding="utf-8")
    _stage(repo, "work/a.md")
    before = _snapshot_of(repo)

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the compile that must not run",
        )
    assert refused.value.paths == ("work/a.md",)
    assert refused.value.claimed_by == "tag"
    assert refused.value.covered == ()
    assert "recorded an EMPTY footprint" in str(refused.value)

    assert _snapshot_of(repo) == before
    assert (await store.snapshots(U1))[0].ref == head_before


async def test_the_recovery_is_path_scoped_and_never_resets_or_cleans_the_tree(
    tmp_path, monkeypatch
):
    """What a recovery actually RUNS: pathspecs, and nothing repository-wide.

    The tree is deliberately more than the residue — a page the dead writer never named, an
    ignored file nobody tracks — and after the recovery every one of them is byte-identical.
    That much a `reset --hard` + `clean -fd` could also have managed here; what it could
    never manage is the SHAPE of the commands, so that is asserted directly: no `--hard`, no
    `clean`, no bare `reset HEAD`, and every destructive command bounded by a `--` after
    which only the claim's own paths appear."""
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    await store.commit_patch(
        U1, {".gitignore": "local/\n"}, message="ignore the operator's scratch space"
    )
    (repo / "local").mkdir()
    (repo / "local" / "notes.md").write_text("an operator's scratch file\n", encoding="utf-8")
    before = _snapshot_of(repo)

    footprint = ["work/a.md", "archive/work/a.md"]
    _write_dead_marker(store, repo, "move_documents", paths=footprint)
    (repo / "archive" / "work").mkdir(parents=True)
    subprocess.run(
        ["git", "-C", str(repo), "mv", "--", "work/a.md", "archive/work/a.md"],
        check=True,
        capture_output=True,
    )

    ran: list[tuple[str, ...]] = []
    real = GitCanonicalStore._run

    def run(repo_arg, *args):
        ran.append(args)
        return real(repo_arg, *args)

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(run))
    await store.commit_patch(
        U1,
        {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
        message="the next compile",
    )
    monkeypatch.undo()

    # Nothing repository-wide, in any spelling.
    assert not any(args[:1] == ("clean",) for args in ran), ran
    assert not any("--hard" in args for args in ran), ran
    assert not any(
        args[:1] == ("reset",) and "--" not in args for args in ran
    ), ran
    # Every reset/checkout/rm names a `--` and, after it, only the footprint — and names it
    # as `:(literal)`, so git reads each string as the one path it is and never as a glob.
    for args in ran:
        if args[:1] not in (("reset",), ("checkout",), ("rm",)):
            continue
        assert "--" in args, args
        spec = args[args.index("--") + 1 :]
        assert all(item.startswith(":(literal)") for item in spec), args
        assert {item[len(":(literal)") :] for item in spec} <= set(footprint), args

    # And the tree bears it out: the residue is gone, everything else is untouched.
    assert _tree_status(store, U1) == ""
    assert not (repo / "archive").exists()
    after = _snapshot_of(repo)
    assert {path: text for path, text in after.items() if path != "work/c.md"} == before



async def test_a_staged_rename_with_one_half_outside_the_footprint_is_refused(tmp_path):
    """`R  <dest>\\0<src>\\0` is ONE status entry naming TWO dirty paths, and both count.

    A staged rename is dirty at BOTH ends: the destination is staged-added, the source is
    staged-DELETED. Reading only the destination — which is what the `-z` parser did while it
    skipped the source field — let a foreign rename whose destination happened to land inside
    a dead writer's footprint read as fully covered. The recovery would then put the
    destination back, leave the source staged-deleted, and the next `commit_patch`'s `add -A`
    would carry somebody's deletion into an unrelated commit under an unrelated message.

    Here the footprint names only the destination, and the whole call refuses on the source.
    """
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1,
        {
            "work/a.md": _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->"),
            "work/outside.md": _file(
                "d-out", "out", "- OUT。[cite: src-02 ¶0] <!-- c:bb22 -->"
            ),
        },
        message="base",
    )
    repo = store.repo_path(U1)

    # A dead writer that was touching ONE path — and somebody else's staged rename that
    # happens to land on it, out of a page the claim never mentions.
    _write_dead_marker(store, repo, "move_documents", paths=["work/inside.md"])
    subprocess.run(
        ["git", "-C", str(repo), "mv", "--", "work/outside.md", "work/inside.md"],
        capture_output=True,
        text=True,
        check=True,
    )
    before = _snapshot_of(repo)
    staged_before = _tree_status(store, U1)

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    # BOTH halves are reported, and the one the claim never named is what refuses.
    assert set(refused.value.paths) == {"work/inside.md", "work/outside.md"}
    assert refused.value.outside == ("work/outside.md",)
    assert refused.value.covered == ("work/inside.md",)

    # Nothing moved, nothing was unstaged: the rename is exactly as its writer left it.
    assert _snapshot_of(repo) == before
    assert _tree_status(store, U1) == staged_before
    assert "work/outside.md -> work/inside.md" in staged_before


@pytest.mark.parametrize(
    "unclaimable",
    ["../x", "/etc/x", "a/../../b", "", "notes/", "work/scratch\u0000.md"],
    ids=["parent", "absolute", "escaping", "empty", "collapsed", "nul"],
)
async def test_a_claim_naming_an_unclaimable_path_is_refused_not_recovered(
    tmp_path, unclaimable
):
    """A footprint string is a live git PATHSPEC and a filesystem JOIN. Neither is safe raw.

    The claim is a JSON file this process did not write — a crash wrote it, an editor may
    have touched it, a filesystem may have half-written it — and every string in it is about
    to be handed to `reset`/`checkout`/`rm` and to `repo / rel` + `unlink`. `../x` and
    `a/../../b` resolve OUTSIDE the repository; `/etc/x` is not repo-relative at all; the
    empty string names the repository root; `notes/` is `git status`'s collapsed spelling for
    a directory and not a path any writer of this adapter records; a NUL cannot survive the
    NUL-separated forms this adapter parses.

    So the shape is checked at the READ, and a list holding one such string reads as
    unreadable WHOLE — taking the readable remainder would be this adapter deciding which
    half of a corrupted claim to believe. The dirty path is left exactly where it is.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    (repo / "work" / "scratch.md").write_text("a dead writer's half page\n", encoding="utf-8")
    before = _snapshot_of(repo)

    # The claim names the real residue AND one string it may not act on.
    _write_dead_marker(
        store, repo, "commit_patch", paths=["work/scratch.md", unclaimable]
    )

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert refused.value.paths == ("work/scratch.md",)
    # The WHOLE list is unreadable, not just the bad entry — so the claim covers nothing.
    assert refused.value.covered is None
    assert refused.value.outside == ("work/scratch.md",)
    assert "recorded NO paths at all" in str(refused.value)
    assert _snapshot_of(repo) == before


async def test_a_footprint_that_is_a_glob_matches_nothing_and_refuses(tmp_path):
    """A claim naming `work/*.md` covers `work/*.md`, which is a file nobody has.

    Every footprint path reaches git as `:(literal)`, so a string in a claim is the one path
    it spells and never a family. The consequence is what this asserts: a glob in a claim
    matches no dirty path, so the residue is OUTSIDE the footprint and the call refuses —
    rather than a recovery reaching every `.md` under `work/` on the strength of one
    character.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    (repo / "work" / "scratch.md").write_text("a dead writer's half page\n", encoding="utf-8")
    before = _snapshot_of(repo)

    _write_dead_marker(store, repo, "commit_patch", paths=["work/*.md"])

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert refused.value.outside == ("work/scratch.md",)
    assert refused.value.covered == ("work/*.md",)
    assert _snapshot_of(repo) == before


async def test_a_path_holding_a_glob_character_is_recovered_verbatim(tmp_path, caplog):
    """…and the other side of the same rule: `work/a[1].md` is a PAGE, not a pattern.

    `[1]` is a character class to git's default pathspec, and a library page may be named
    with one. The recovery must still put that exact file back, so this is the fix's own
    regression test: `:(literal)` (or a `--pathspec-from-file` spelling of it) has to leave
    an ordinary odd name working, not merely stop a glob from spreading. Git's own matcher
    tries a literal comparison before it wildmatches, which is why this particular name
    survived the unspelt form too — the harm of the default pathspec is the paths a `*`
    would ADD, and that is asserted where the commands themselves are
    (`test_the_recovery_is_path_scoped_and_never_resets_or_cleans_the_tree`).
    """
    store = GitCanonicalStore(str(tmp_path))
    odd = "work/a[1].md"
    await store.commit_patch(
        U1, {odd: _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->")}, message="base"
    )
    repo = store.repo_path(U1)
    committed = (repo / odd).read_text("utf-8")

    # A dead writer caught mid-edit on that page, with the page on its footprint.
    (repo / odd).write_text("half an edit\n", encoding="utf-8")
    _write_dead_marker(store, repo, "commit_patch", paths=[odd])

    with caplog.at_level("WARNING"):
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert (repo / odd).read_text("utf-8") == committed
    assert _tree_status(store, U1) == ""
    assert odd in " ".join(
        record.getMessage() for record in caplog.records if record.levelname == "WARNING"
    )


async def test_an_untracked_directory_holding_an_unnamed_symlink_is_refused(tmp_path):
    """A broken symlink beside a page the claim named is an outsider, and refuses the call.

    `is_file()` follows symlinks and answers False for a broken one, for a link to a
    directory, and for a fifo. Each of those is somebody's, and each used to survive a
    recovery that never named it. TWO mechanisms now keep this `notes/` — one ordinary page
    the claim named, one symlink pointing out of the repository that it did not — from
    reading as covered, and this exercises both.

    The primary one is the read: `--untracked-files=all` makes git name the link itself, so
    the comparison is against a real path and the collapsed spelling never arises. The
    belt-and-braces one is `_within_footprint`'s expansion, asserted directly below because
    no call site produces `notes/` any more: it counts ENTRIES, not files, so the link is an
    outsider there too if a collapsed entry ever reaches it from some other producer.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    (repo / "notes").mkdir()
    (repo / "notes" / "a.md").write_text("the dead writer's own page\n", encoding="utf-8")
    # Broken on purpose: `is_file()` answers False for it, which is exactly how it used to
    # pass through an expansion that only counted files.
    os.symlink(str(tmp_path / "not-here"), repo / "notes" / "escape")
    before = _snapshot_of(repo)

    _write_dead_marker(store, repo, "commit_patch", paths=["notes/a.md"])

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert set(refused.value.paths) == {"notes/a.md", "notes/escape"}
    assert refused.value.outside == ("notes/escape",)
    assert refused.value.covered == ("notes/a.md",)
    # Both of them are still there — the page the claim named as well, because a mixed tree
    # is refused whole rather than cleaned in part.
    assert _snapshot_of(repo) == before
    assert (repo / "notes" / "escape").is_symlink()

    # The second mechanism, directly: a collapsed entry from any other producer is covered
    # only when every entry under it — the link included — is named.
    assert not store._within_footprint(repo, "notes/", ("notes/a.md",))
    assert store._within_footprint(repo, "notes/", ("notes/a.md", "notes/escape"))


async def test_a_footprint_recording_the_collapsed_spelling_covers_nothing(tmp_path):
    """A claim naming `notes/` names something no writer of this adapter ever wrote.

    Every footprint is built from FILE paths — a patch's map, a move's pairs, a meta write's
    one path — so `notes/` can only have come from somewhere else, and reading it as a
    licence over a whole directory is the licence `_within_footprint` exists to withhold: it
    would cover whatever anybody has since put in there. It is refused at the claim's read,
    which makes the list unreadable whole.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    (repo / "notes").mkdir()
    (repo / "notes" / "a.md").write_text("somebody's note\n", encoding="utf-8")
    before = _snapshot_of(repo)

    _write_dead_marker(store, repo, "commit_patch", paths=["notes/"])

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert refused.value.paths == ("notes/a.md",)
    assert refused.value.covered is None
    assert _snapshot_of(repo) == before


async def test_a_claim_naming_something_inside_dot_git_covers_nothing(tmp_path):
    """`.git` is not the library, and no claim may reach into it — in any casing.

    The claim is a JSON file, and everything downstream reads its strings as live git
    pathspecs AND as filesystem joins. `.git/config` is a legal-looking string in both, and
    under a footprint that named it the recovery would `checkout` over, or UNLINK, the
    repository's own config, index, hooks or refs — including the lock file a waiter is
    blocked on. No writer of this adapter ever records such a path, so a claim carrying one
    is a claim nobody can vouch for: the list reads as unreadable WHOLE, the call refuses,
    and `.git/` is untouched.

    The comparison is case-folded because macOS and Windows resolve `.GIT/` to the same
    directory git uses, so a byte-exact check would refuse the spelling and admit the path.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    config_before = (repo / ".git" / "config").read_text("utf-8")

    # Something real for the recovery to bite on: without the guard the footprint below
    # covers this file, the recovery runs, and it reaches `.git/config` on the way past.
    (repo / "work" / "scratch.md").write_text("somebody's draft\n", encoding="utf-8")
    before = _snapshot_of(repo)

    for named in (".git/config", ".GIT/config", "work/.git/x"):
        _write_dead_marker(
            store, repo, "commit_patch", paths=[named, "work/scratch.md"]
        )
        with pytest.raises(CanonicalDirtyError) as refused:
            await store.commit_patch(
                U1,
                {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
                message="the next compile",
            )
        assert refused.value.paths == ("work/scratch.md",)
        assert refused.value.covered is None

    # The repository's own machinery, byte for byte, and the working tree with it.
    assert (repo / ".git" / "config").read_text("utf-8") == config_before
    assert _snapshot_of(repo) == before
    # …and the rule itself, at the one place that decides it.
    for named in (".git/config", ".GIT/config", ".Git", "work/.git/x", "a/.GIT/b"):
        assert not GitCanonicalStore._is_claimable_path(named)
    assert GitCanonicalStore._is_claimable_path("work/git/x")


async def test_status_showuntrackedfiles_no_cannot_hide_an_outsider(tmp_path):
    """A config that hides untracked files hides them from the READ, never from the WRITE.

    `status.showUntrackedFiles=no` is a legitimate thing for a person to set on a repository
    they also open by hand, and it silences exactly the entries this adapter's precondition
    is made of. An `add` over those paths stages them regardless, so a library configured
    that way would let a writer commit residue the status read had just declared absent. The
    read asks for `--untracked-files=all` and the config cannot reach it.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    subprocess.run(
        ["git", "-C", str(repo), "config", "status.showUntrackedFiles", "no"],
        check=True,
        capture_output=True,
    )
    # Proof the config really does silence a default read.
    assert _tree_status(store, U1) == ""

    (repo / "notes").mkdir()
    (repo / "notes" / "plan.md").write_text("an agent's plan\n", encoding="utf-8")

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the compile that must not run",
        )
    assert refused.value.paths == ("notes/plan.md",)
    assert (repo / "notes" / "plan.md").read_text("utf-8") == "an agent's plan\n"
    assert not (repo / "work" / "c.md").exists()

async def test_a_claim_that_outlived_its_clear_cannot_destroy_a_later_hand_edit(
    tmp_path, monkeypatch, caplog
):
    """The window end to end, and the finding this closes.

    A clear whose unlink AND atomic replace BOTH fail leaves a WHOLE claim standing after an
    orderly exit. That process then exits, so its pid reads as dead, and the pid rule alone
    reads the claim as positive proof of a death — while the tree it stands over is whatever
    somebody edited afterwards. Writing the claim first does not help: the next call writes
    its own claim successfully and walks straight into the recovery.

    So the claim is left standing exactly that way (the double failure is real, and logged at
    ERROR), the pid is restamped to one that is genuinely gone — which is what the exit does,
    leaving the claim's FOOTPRINT as its body wrote it — and a person then edits a tracked
    file the dead body never named. The write is REFUSED and the edit is still there."""
    store = GitCanonicalStore(str(tmp_path))
    head_before, _tree = await _two_movable_documents(store)
    repo = store.repo_path(U1)
    marker = store._marker_path(repo)

    # Both halves of the clear fail: the unlink and the release rewrite's replace.
    real_unlink = pathlib.Path.unlink

    def refuse_unlink(self, missing_ok=False):
        if self == marker:
            raise PermissionError("read-only .git")
        return real_unlink(self, missing_ok=missing_ok)

    def refuse_replace(src, dst):
        raise PermissionError("read-only marker")

    monkeypatch.setattr(pathlib.Path, "unlink", refuse_unlink)
    monkeypatch.setattr(os, "replace", refuse_replace)
    with caplog.at_level("ERROR"):
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="an ordinary compile whose clear cannot land",
        )
    monkeypatch.undo()

    # A WHOLE claim survived an orderly exit — the state the finding is about — and it is
    # named at ERROR, which is now an operational warning rather than a hazard.
    assert _read_marker(store, U1)["operation"] == "commit_patch"
    assert _read_marker(store, U1)["paths"] == ["work/c.md"]
    assert "released" not in _read_marker(store, U1)
    assert any(
        "could not clear the in-flight marker" in r.getMessage()
        for r in caplog.records
        if r.levelname == "ERROR"
    )

    # The process exits: its pid is gone, and the claim now reads as proof of a death.
    dead = _kill_claimant(store, repo)
    assert store._claimant_is_gone(store._read_marker(repo)) is True

    # A person edits a tracked page in the library — one that claim never names.
    edited = repo / "work" / "a.md"
    edited.write_text(edited.read_text("utf-8") + "\n- 一个下午的工作。\n", encoding="utf-8")
    before = _snapshot_of(repo)
    head_after_compile = (await store.snapshots(U1))[0].ref

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.move_documents(
            U1, [("work/a.md", "archive/work/a.md")], message="an archive that must not run"
        )
    assert set(refused.value.paths) == {"work/a.md"}
    assert refused.value.outside == ("work/a.md",)
    assert refused.value.covered == ("work/c.md",)
    assert "OUTSIDE what it recorded" in str(refused.value)
    assert str(dead) not in str(refused.value)  # the pid is not the argument any more

    # The afternoon's work is still there, byte for byte, and nothing was committed.
    assert _snapshot_of(repo) == before
    assert (await store.snapshots(U1))[0].ref == head_after_compile != head_before
    assert not (repo / "archive").exists()


# A claim licenses `reset --hard` + `clean -fd` only on POSITIVE PROOF that its writer died:
# an integer pid above zero that answers `kill(pid, 0)` with `ProcessLookupError`. These are
# the shapes that are NOT that proof and used to read as one, because the question asked was
# "is it alive?" — which answers every ambiguity with "no" and then deletes.
_UNPROVABLE_CLAIMS = {
    "truncated mid-write": '{"operation": "move_documents", "pid": 41',
    "not json at all": "\x00\x00\x00 half a write",
    "not an object": '["move_documents", 4131]',
    "no pid at all": '{"operation": "move_documents", "started_at": "2026-01-01T00:00:00Z"}',
    "pid 0": '{"operation": "move_documents", "pid": 0}',
    "pid -1": '{"operation": "move_documents", "pid": -1}',
    "a string pid": '{"operation": "move_documents", "pid": "4131"}',
    "a float pid": '{"operation": "move_documents", "pid": 4131.0}',
    "a boolean pid": '{"operation": "move_documents", "pid": true}',
}


@pytest.mark.parametrize("shape", sorted(_UNPROVABLE_CLAIMS))
async def test_a_claim_that_does_not_prove_a_death_is_refused_not_recovered(tmp_path, shape):
    """THE QUESTION IS NOT "IS IT ALIVE?" BUT "IS IT PROVABLY DEAD?"

    Every shape here is a claim nobody can read a death out of, and every one of them used to
    fall through to the recovery: a truncated marker, a marker naming no pid or a nonsensical
    one, a marker that is not even an object. The release rewrite is a way to produce one —
    interrupt it and what is left is exactly the first line of this table — so the shape is
    not hypothetical, and what stood behind "not alive" was `reset --hard` + `clean -fd` over
    a working tree. A GENUINELY DEAD WRITER WHOSE MARKER GOT CORRUPTED REFUSES TOO, and that
    is the direction to fail in: an operator looks at a mess nobody can prove the shape of.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, _ = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    store._marker_path(repo).write_text(_UNPROVABLE_CLAIMS[shape], encoding="utf-8")
    edited = repo / "work" / "a.md"
    edited.write_text("an afternoon of somebody's edits\n", encoding="utf-8")
    (repo / "work" / "scratch.md").write_text("and a page they started\n", encoding="utf-8")
    before = {
        path: (repo / path).read_text("utf-8")
        for path in ("work/a.md", "work/b.md", "work/scratch.md")
    }

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert set(refused.value.paths) == {"work/a.md", "work/scratch.md"}
    # One machine string across every face, whatever the claim turned out to say.
    assert refused.value.detail == "canonical_dirty:work/a.md,work/scratch.md"
    # The message names what could and could not be read, because "there is a marker and it
    # was still refused" is otherwise unreadable.
    assert refused.value.unproven
    assert "NOT PROOF" in str(refused.value)

    # BYTE-IDENTICAL: nothing recovered, nothing written, nothing committed.
    for path, text in before.items():
        assert (repo / path).read_text("utf-8") == text
    assert not (repo / "work" / "c.md").exists()
    assert (await store.snapshots(U1))[0].ref == head_before


@pytest.mark.parametrize(
    "probe_error",
    [
        PermissionError(1, "Operation not permitted"),
        OSError(4, "Interrupted system call"),
    ],
    ids=["permission denied", "an unexpected errno"],
)
async def test_a_claim_whose_pid_cannot_be_probed_is_refused(
    tmp_path, monkeypatch, probe_error
):
    """A probe that does not answer is not an answer of "dead".

    The marker here is WELL FORMED and its pid really is gone — the same claim the test below
    recovers — so the only thing under test is the probe. `PermissionError` means a process
    with that number exists and belongs to somebody else; any other errno means the question
    could not be asked at all. Neither is `ProcessLookupError`, so neither licenses a
    deletion, and the refusal names the paths.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, _ = await _two_movable_documents(store)
    repo = store.repo_path(U1)
    dead = _write_dead_marker(store, repo, "move_documents")
    (repo / "work" / "a.md").write_text("an afternoon of somebody's edits\n", encoding="utf-8")
    before = (repo / "work" / "a.md").read_text("utf-8")

    real_kill = os.kill

    def kill(pid, sig):
        if pid == dead:
            raise probe_error
        return real_kill(pid, sig)

    monkeypatch.setattr(os, "kill", kill)

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert refused.value.paths == ("work/a.md",)
    assert refused.value.detail == "canonical_dirty:work/a.md"
    assert str(dead) in str(refused.value)

    monkeypatch.undo()
    assert (repo / "work" / "a.md").read_text("utf-8") == before
    assert not (repo / "work" / "c.md").exists()
    assert (await store.snapshots(U1))[0].ref == head_before


async def test_the_release_rewrite_lands_whole_or_not_at_all(tmp_path, monkeypatch):
    """The release is written to a sibling and RENAMED onto the marker.

    A release written in place can be interrupted, and what a partial one leaves is a
    TRUNCATED claim — the first row of `_UNPROVABLE_CLAIMS`. So the degrade path would itself
    manufacture the ambiguity the entry check then has to refuse, and under the old "is it
    alive?" question it manufactured a licence to delete. `os.replace` within one directory
    is atomic: the file on disk is only ever the whole old claim or the whole release.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    marker = store._marker_path(repo)

    real_unlink = pathlib.Path.unlink

    def unlink(self, *args, **kwargs):
        if self == marker:
            raise PermissionError("a read-only directory defeats the unlink")
        return real_unlink(self, *args, **kwargs)

    writes: list[tuple[pathlib.Path, str]] = []
    real_write_text = pathlib.Path.write_text

    def write_text(self, data, *args, **kwargs):
        writes.append((self, data))
        return real_write_text(self, data, *args, **kwargs)

    renames: list[tuple[pathlib.Path, pathlib.Path]] = []
    real_replace = os.replace

    def replace(src, dst, **kwargs):
        renames.append((pathlib.Path(src), pathlib.Path(dst)))
        return real_replace(src, dst, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    monkeypatch.setattr(pathlib.Path, "write_text", write_text)
    monkeypatch.setattr(os, "replace", replace)

    ref = await store.commit_patch(
        U1,
        {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
        message="an ordinary compile",
    )
    monkeypatch.undo()
    assert _commit_names(repo, ref.ref) == {"work/c.md"}

    # The release NEVER went through the marker path itself: it landed by rename.
    assert not [data for path, data in writes if path == marker and "released" in data]
    onto_marker = [pair for pair in renames if pair[1] == marker]
    assert len(onto_marker) == 1
    source = onto_marker[0][0]
    assert source != marker and source.parent == marker.parent  # atomic within one directory

    # What is on disk parses, and reads as released — which is no claim at all.
    assert json.loads(marker.read_text("utf-8"))["released"] is True
    assert store._read_marker(repo) is None
    # And no staging file was left behind beside it.
    assert sorted(path.name for path in (repo / ".git").glob("pneuma.inflight*")) == [
        "pneuma.inflight"
    ]


async def test_a_claim_that_cannot_be_written_stops_the_call_before_it_reads_the_tree(
    tmp_path, monkeypatch
):
    """The claim is written FIRST, and that ordering is itself a safety property.

    The tree here is dirty under a claim whose writer is provably dead — the one state that
    licenses `reset --hard` + `clean -fd` — so if anything downstream of the claim ran, the
    residue would be gone. It cannot run: `_write_marker` fails, and at that instant no status
    has been read, nothing has been weighed and nothing deleted. That is what closes the last
    route to the destructive branch on a filesystem where clears cannot land — a repository
    that will not take a claim can never authorize one either.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, _ = await _two_movable_documents(store)
    repo = store.repo_path(U1)
    _write_dead_marker(store, repo, "move_documents", paths=["work/a.md"])
    claim = store._marker_path(repo).read_text("utf-8")
    (repo / "work" / "a.md").write_text("a dead writer's half-written page\n", encoding="utf-8")
    before = (repo / "work" / "a.md").read_text("utf-8")

    reads: list[str] = []
    monkeypatch.setattr(
        GitCanonicalStore,
        "_dirty_paths",
        lambda self, repo: (reads.append("status"), [])[1],
    )

    def refuse(self, repo, operation, **claim):
        raise CanonicalMarkerError(str(self._marker_path(repo)))

    monkeypatch.setattr(GitCanonicalStore, "_write_marker", refuse)

    with pytest.raises(CanonicalMarkerError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert "pneuma.inflight" in refused.value.path
    monkeypatch.undo()

    assert reads == []  # the tree was never even read, let alone recovered
    assert (repo / "work" / "a.md").read_text("utf-8") == before
    assert not (repo / "work" / "c.md").exists()
    assert (await store.snapshots(U1))[0].ref == head_before
    # The dead writer's claim is untouched: this call had no licence over anything.
    assert store._marker_path(repo).read_text("utf-8") == claim


async def test_a_clear_that_cannot_unlink_degrades_the_claim_to_released(
    tmp_path, monkeypatch, caplog
):
    """The second layer. A clear that cannot remove the file REWRITES it as released, and a
    released marker reads as no claim at all.

    Swallowing the failure and leaving the claim whole was the fault: the file would outlive
    an orderly exit and become the licence that discards somebody's later edits. Unlink and
    rewrite fail independently — a read-only directory defeats the first, a read-only file
    the second — so the second half is a real second chance, not a retry.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    real_unlink = pathlib.Path.unlink
    refused_once: list[int] = []

    def unlink(self, *args, **kwargs):
        if self.name == "pneuma.inflight" and not refused_once:
            refused_once.append(1)
            raise PermissionError("read-only .git")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(pathlib.Path, "unlink", unlink)
    with caplog.at_level("WARNING"):
        ref = await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="a commit whose clear cannot unlink",
        )
    monkeypatch.undo()
    assert refused_once  # the unlink really was the one that failed

    # The file is still there — and it is no longer a claim.
    assert store._marker_path(repo).is_file()
    assert _read_marker(store, U1)["released"] is True
    assert store._read_marker(repo) is None
    assert any(
        "released" in r.getMessage()
        for r in caplog.records
        if r.levelname == "WARNING"
    )

    # And the proof that matters: a hand edit made after that exit is somebody else's work,
    # refused, not residue recovered on the strength of a marker that could not be removed.
    (repo / "work" / "a.md").write_text("a person's later edit\n", encoding="utf-8")
    with pytest.raises(CanonicalDirtyError) as after:
        await store.commit_patch(
            U1,
            {"work/d.md": _file("d-d", "d", "- D。[cite: src-04 ¶0] <!-- c:dd44 -->")},
            message="the call after",
        )
    assert after.value.paths == ("work/a.md",)
    assert after.value.claimed_by is None  # a released marker names nothing
    assert (repo / "work" / "a.md").read_text(encoding="utf-8") == "a person's later edit\n"
    assert ref.ref  # the commit that landed before all this

    # …and a clean tree under a released marker proceeds, because there is no claim to weigh.
    (repo / "work" / "a.md").write_text(
        _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->"), encoding="utf-8"
    )
    assert _tree_status(store, U1) == ""
    await store.commit_patch(
        U1,
        {"work/e.md": _file("d-e", "e", "- E。[cite: src-05 ¶0] <!-- c:ee55 -->")},
        message="after the released marker",
    )
    assert not store._marker_path(repo).exists()


async def test_a_released_marker_over_a_dirty_tree_is_refused(tmp_path):
    """A released marker is a claim its own writer gave up ON THE RECORD, which is the
    opposite of one a death left standing. Every reader treats it as absence, so the tree
    beneath it is unclaimed work — refused, byte for byte, like any other."""
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    store._marker_path(repo).write_text(
        json.dumps(
            {"released": True, "operation": "move_documents", "pid": os.getpid()},
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    assert store._read_marker(repo) is None
    (repo / "work" / "a.md").write_text("somebody's edit\n", encoding="utf-8")

    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert refused.value.paths == ("work/a.md",)
    assert refused.value.claimed_by is None
    assert (repo / "work" / "a.md").read_text(encoding="utf-8") == "somebody's edit\n"


async def test_a_restore_refuses_a_claim_whose_process_is_still_alive(tmp_path):
    """The pid rule where it bites hardest: the restore branch that DELETES a directory and
    the files in it. "A dead restore's own half-materialized checkout" is a statement about a
    death, and a claimant that is still running refutes it — so the leftovers stay and the
    call refuses, naming the paths."""
    source = GitCanonicalStore(str(tmp_path / "source"))
    await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    (repo / "work").mkdir()
    (repo / "work" / "mine.md").write_text("someone's draft", encoding="utf-8")
    # A restore's OWN claim — the one that licenses the deletion — but its process is alive.
    target._write_marker(repo, "restore_repository", paths=(), pre_existing=[])

    with pytest.raises(CanonicalDirtyError) as refused:
        await target.restore_repository(U2, bundle=bundle)
    assert refused.value.paths == ("work/mine.md",)
    assert refused.value.detail == "canonical_dirty:work/mine.md"
    assert str(os.getpid()) in str(refused.value)
    assert (repo / "work" / "mine.md").read_text(encoding="utf-8") == "someone's draft"
    assert not (repo / ".git" / "HEAD").exists()


async def test_a_restore_refuses_its_own_claim_when_the_death_is_not_proven(tmp_path):
    """The same rule on the branch that DELETES A DIRECTORY AND THE FILES IN IT.

    The claim names `restore_repository`, so it is the only kind of claim this branch will
    ever destroy for — and it still refuses, because `pid: 0` names no process and therefore
    proves no death. Anything short of `ProcessLookupError` on an integer pid above zero
    lands here: a pid that cannot be read, cannot be probed, or is simply alive.
    """
    source = GitCanonicalStore(str(tmp_path / "source"))
    await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    (repo / "work").mkdir()
    (repo / "work" / "mine.md").write_text("someone's draft", encoding="utf-8")
    target._marker_path(repo).write_text(
        json.dumps({"operation": "restore_repository", "pid": 0}, sort_keys=True),
        encoding="utf-8",
    )

    with pytest.raises(CanonicalDirtyError) as refused:
        await target.restore_repository(U2, bundle=bundle)
    assert refused.value.paths == ("work/mine.md",)
    assert refused.value.detail == "canonical_dirty:work/mine.md"
    assert "NOT PROOF" in str(refused.value)

    assert (repo / "work" / "mine.md").read_text(encoding="utf-8") == "someone's draft"
    assert not (repo / ".git" / "HEAD").exists()


async def test_a_refused_move_leaves_no_claim_behind(tmp_path):
    """A LIVE PROCESS ALWAYS RELEASES ITS CLAIM — an orderly refusal included.

    This is the fault the `finally` closes. The claim used to be dropped only on the success
    path, so a preflight refusal (here: a destination that is already taken) walked out
    leaving `pneuma.inflight` standing over a perfectly clean tree. The marker then no longer
    meant "a process died here"; it meant "something failed here once" — and the next writer
    read A PERSON'S EDIT, made long afterwards, as this adapter's own residue and `reset
    --hard`ed it away. Released on the way out, the marker survives exactly one event:
    process death.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    await store.commit_patch(
        U1,
        {"archive/work/a.md": _file("d-x", "x", "- X。[cite: src-09 ¶0] <!-- c:xx99 -->")},
        message="something already stands at the destination",
    )
    head = (await store.snapshots(U1))[0].ref

    with pytest.raises(CanonicalMoveError) as refused:
        await store.move_documents(
            U1, [("work/a.md", "archive/work/a.md")], message="a move that cannot run"
        )
    assert refused.value.reason == "destination path already exists"
    # Nothing moved, and — the point — nothing is claiming the tree.
    assert _tree_status(store, U1) == ""
    assert not store._marker_path(repo).exists()
    assert (await store.snapshots(U1))[0].ref == head

    # Now somebody edits the library by hand. With the stale claim standing this was read as
    # the refused move's own residue and destroyed; with no claim it is what it is.
    edited = repo / "work/b.md"
    mine = edited.read_text("utf-8") + "\n- 手写的一句。\n"
    edited.write_text(mine, encoding="utf-8")

    with pytest.raises(CanonicalDirtyError) as blocked:
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the compile that must not run",
        )
    assert blocked.value.paths == ("work/b.md",)
    assert edited.read_text("utf-8") == mine
    # A refusal claims nothing either: it never got as far as writing one.
    assert not store._marker_path(repo).exists()


async def test_a_rollback_that_left_the_tree_dirty_still_releases_the_claim(
    tmp_path, monkeypatch
):
    """The one case that looks like an exception and is not.

    When the rollback could not get the tree back, the claim is released like on every other
    exit — so the next call meets a dirty tree with NO marker and REFUSES rather than
    auto-cleaning it. That is deliberate: the mess is half this call's renames and half
    whatever git would not undo, a state no automatic recovery is entitled to interpret. An
    operator has to look at it.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)
    head = (await store.snapshots(U1))[0].ref

    # A rollback that undoes nothing and says so honestly: the tree stays half-renamed.
    monkeypatch.setattr(
        GitCanonicalStore,
        "_rollback",
        lambda self, repo, *a, **k: self._first_dirty_path(repo),
    )
    _fail_on(
        monkeypatch,
        lambda args: args[:1] == ("mv",) and args[-1].startswith("archive/work/b"),
    )
    with pytest.raises(CanonicalMoveError) as failed:
        await store.move_documents(
            U1,
            [("work/a.md", "archive/work/a.md"), ("work/b.md", "archive/work/b.md")],
            message="an archive whose undo fails",
        )
    assert failed.value.reason == "rollback left the repository dirty"
    monkeypatch.undo()

    assert _tree_status(store, U1) != ""
    assert not store._marker_path(repo).exists()

    # …so the next writer refuses instead of discarding it, and the half-renamed tree is
    # exactly as the failure left it for the operator to read.
    with pytest.raises(CanonicalDirtyError):
        await store.commit_patch(
            U1,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="the next compile",
        )
    assert (repo / "archive/work/a.md").is_file()
    assert (await store.snapshots(U1))[0].ref == head


async def test_a_restore_refuses_a_target_claimed_by_a_different_operation(tmp_path):
    """The restore's destructive branch acts ONLY on a restore's own claim.

    Every other recovery in this adapter discards uncommitted CHANGES in a repository it is
    committing to, and any operation's claim is proof enough there — every operation writes
    into that same repository. This branch DELETES A DIRECTORY AND THE FILES IN IT, and only
    a restore ever materializes a checkout there. A crashed `init_repository` claims a bare
    `.git/` and writes nothing else, so accepting its claim would authorize wiping files that
    predate it entirely — which is exactly what this refuses.
    """
    source = GitCanonicalStore(str(tmp_path / "source"))
    await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    (repo / "work").mkdir()
    (repo / "work" / "mine.md").write_text("someone's draft", encoding="utf-8")
    # An `init_repository` that died: its claim stands, and it never wrote a single one of
    # the files beside it — its footprint is empty, as every ref-only operation's is.
    target._write_marker(repo, "init_repository", paths=())

    with pytest.raises(CanonicalDirtyError) as refused:
        await target.restore_repository(U2, bundle=bundle)
    assert refused.value.paths == ("work/mine.md",)
    # `detail` stays the one machine string; the operation the claim names rides in the text,
    # because "there is a marker and it was still refused" is otherwise unreadable.
    assert refused.value.detail == "canonical_dirty:work/mine.md"
    assert "init_repository" in str(refused.value)
    # Byte-for-byte, and no repository made over the top of it.
    assert (repo / "work" / "mine.md").read_text(encoding="utf-8") == "someone's draft"
    assert not (repo / ".git" / "HEAD").exists()


async def test_restore_repository_claims_the_tree_and_releases_it(tmp_path):
    """The restore writes a whole working tree, so it claims one like every other writer: a
    restore killed mid-graft leaves a half-materialized checkout that the next mutating call
    must be able to recognize as this framework's own rather than refuse forever."""
    source = GitCanonicalStore(str(tmp_path / "src"))
    await source.commit_patch(
        U1,
        {"work/a.md": _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->")},
        message="base",
    )
    bundle = tmp_path / "kb.bundle"
    subprocess.run(
        ["git", "-C", str(source.repo_path(U1)), "bundle", "create", str(bundle), "--all"],
        check=True,
        capture_output=True,
    )

    target = GitCanonicalStore(str(tmp_path / "dst"))
    seen: list[bool] = []
    real_graft = GitCanonicalStore._graft

    def graft(staging, repo):
        # The claim is standing WHILE the tree is being materialized, which is the whole
        # point of writing it before the clone.
        seen.append((repo / ".git" / "pneuma.inflight").is_file())
        real_graft(staging, repo)

    GitCanonicalStore._graft = staticmethod(graft)
    try:
        assert await target.restore_repository(U2, bundle=bundle) is True
    finally:
        GitCanonicalStore._graft = staticmethod(real_graft)

    assert seen == [True]
    assert not target._marker_path(target.repo_path(U2)).exists()
    assert {doc.path for doc in await target.list(U2)} == {"work/a.md"}
    # …and an ordinary write over the restored library runs, rather than meeting a claim
    # nobody released.
    await target.commit_patch(
        U2,
        {"work/b.md": _file("d-b", "b", "- B。[cite: src-02 ¶0] <!-- c:bb22 -->")},
        message="after restore",
    )
    assert _tree_status(target, U2) == ""


async def test_every_mutating_method_leaves_the_tree_clean(tmp_path):
    """The invariant the residue rule rests on: between operations, this repository is
    clean. Asserted over every mutating method there is, because the recovery's licence to
    discard is exactly "no writer here leaves anything behind"."""
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    head = (await store.snapshots(U1))[0].ref

    await store.commit_patch(
        U1,
        {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
        message="commit",
    )
    assert _tree_status(store, U1) == ""

    await store.move_documents(
        U1, [("work/c.md", "archive/work/c.md")], message="archive c"
    )
    assert _tree_status(store, U1) == ""

    await store.write_meta(U1, "skill/manifest.json", "{}\n", message="skill")
    assert _tree_status(store, U1) == ""

    await store.tag(U1, SnapshotRef(ref=head), "kb-v1")
    assert _tree_status(store, U1) == ""

    branch_ref = await store.branch_commit(
        U1,
        "evolve/t-1",
        {"work/d.md": _file("d-d", "d", "- D。[cite: src-04 ¶0] <!-- c:dd44 -->")},
        "evolve draft",
        base=SnapshotRef(ref=head),
    )
    assert (await store.branch_head(U1, "evolve/t-1")).ref == branch_ref.ref
    assert _tree_status(store, U1) == ""

    await store.delete_branch(U1, "evolve/t-1")
    assert _tree_status(store, U1) == ""
    assert await store.branch_head(U1, "evolve/t-1") is None


async def test_rollback_after_partial_moves_restores_only_the_moved_paths(
    tmp_path, monkeypatch
):
    """Fail on the third of three: the two that landed come back, and nothing else moves."""
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1,
        {
            "work/a.md": _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->"),
            "work/b.md": _file("d-b", "b", "- B。[cite: src-02 ¶0] <!-- c:bb22 -->"),
            "work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->"),
            "work/kept.md": _file("d-k", "kept", "- K。[cite: src-04 ¶0] <!-- c:dd44 -->"),
        },
        message="base",
    )
    head_before = (await store.snapshots(U1))[0].ref
    tree_before = {doc.path: doc.body for doc in await store.list(U1)}
    repo = store.repo_path(U1)

    moves = [
        ("work/a.md", "archive/work/a.md"),
        ("work/b.md", "archive/work/b.md"),
        ("work/c.md", "archive/work/c.md"),
    ]
    seen: list[int] = []

    def third_mv(args):
        if args and args[0] == "mv":
            seen.append(1)
            return len(seen) == 3
        return False

    _fail_on(monkeypatch, third_mv)

    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(U1, moves, message="archive three")

    # The two renames that landed were undone in reverse, and only they were touched.
    assert _tree_status(store, U1) == ""
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before
    for path in ("work/a.md", "work/b.md", "work/c.md", "work/kept.md"):
        assert (repo / path).is_file()
    # The destination directory the loop created on its way is gone with it.
    assert not (repo / "archive").exists()

    monkeypatch.undo()
    moved = await store.move_documents(U1, moves, message="archive three")
    assert moved.ref != head_before
    assert sorted(doc.path for doc in await store.list(U1)) == [
        "archive/work/a.md",
        "archive/work/b.md",
        "archive/work/c.md",
        "work/kept.md",
    ]


async def test_rollback_falls_back_to_head_when_the_inverse_rename_also_fails(
    tmp_path, monkeypatch
):
    """`git mv` back is the first attempt, not the only one.

    When git refuses every rename — the failure that broke the move is still in force — the
    pair is rebuilt from HEAD instead: unstage both sides, check the original path out, drop
    the destination. The tree still comes back, and it still comes back scoped.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    real = GitCanonicalStore._run
    seen: list[int] = []

    def run(repo_path, *args):
        if args and args[0] == "mv":
            seen.append(1)
            if len(seen) >= 2:  # the second forward mv and every rollback mv
                raise subprocess.CalledProcessError(1, ["git", *args], stderr="boom")
        return real(repo_path, *args)

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(run))

    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(
            U1,
            [("work/a.md", "archive/work/a.md"), ("work/b.md", "archive/work/b.md")],
            message="archive both",
        )

    monkeypatch.undo()
    assert _tree_status(store, U1) == ""
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before
    assert not (repo / "archive").exists()


async def test_rollback_prunes_the_directory_created_for_the_failing_move(
    tmp_path, monkeypatch
):
    """The pair that FAILED left a directory behind too, and only it knows about it.

    `git mv` needs its destination directory to exist, so the loop creates it a moment
    before the rename it is for. When that rename is the one that fails, the pair never
    reaches `performed` — so a cleanup that walked up from the renames that landed would
    leave an empty `archive/y/` in the library forever, with nothing that could name it.
    The directories this call created are tracked in their own right, and every one of them
    is pruned.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    # Two destinations under DIFFERENT new directories, so the failing pair's directory is
    # not swept up by the cleanup of the pair that landed.
    moves = [
        ("work/a.md", "archive/x/a.md"),
        ("work/b.md", "archive/y/b.md"),
    ]
    seen: list[int] = []

    def second_mv(args):
        if args and args[0] == "mv":
            seen.append(1)
            return len(seen) == 2
        return False

    _fail_on(monkeypatch, second_mv)

    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(U1, moves, message="archive both")

    # `archive/y/` was created for the move that never happened; it is gone with the rest.
    assert not (repo / "archive" / "y").exists()
    assert not (repo / "archive" / "x").exists()
    assert not (repo / "archive").exists()
    assert _tree_status(store, U1) == ""
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before


async def test_status_read_failure_refuses_the_move(tmp_path, monkeypatch):
    """A status read that fails is not a clean tree — it is a tree this call cannot see.

    Answering "clean" there would let the move run against a repository whose state is
    unknown, which is the exact thing the preflight exists to prevent. It fails closed.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    _fail_on(monkeypatch, lambda args: bool(args) and args[0] == "status")

    with pytest.raises(CanonicalMoveError) as unreadable:
        await store.move_documents(
            U1, [("work/a.md", "archive/work/a.md")], message="archive a"
        )
    assert unreadable.value.reason == "could not read repository status"
    assert unreadable.value.path == ""

    monkeypatch.undo()
    assert not (repo / "archive").exists()
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before


async def test_rollback_reset_is_scoped_to_the_moved_paths(tmp_path, monkeypatch):
    """The unstage is a pathspec, never a repository-wide `git reset HEAD`.

    A bare reset would also unstage whatever else is in the index — after a crash, the only
    record that another writer got as far as staging. The tree is clean either way, so the
    scoping cannot be read off the outcome: what is asserted here is the argv the rollback
    issues. `_index_differs` is forced true so the branch that issues it always runs.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)
    moves = [
        ("work/a.md", "archive/work/a.md"),
        ("work/b.md", "archive/work/b.md"),
    ]

    calls: list[tuple[str, ...]] = []
    real = GitCanonicalStore._run

    def record(repo, *args):
        calls.append(args)
        if "commit" in args:
            raise subprocess.CalledProcessError(1, ["git", *args], stderr="boom")
        return real(repo, *args)

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(record))
    monkeypatch.setattr(
        GitCanonicalStore, "_index_differs", lambda self, repo: True
    )

    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(U1, moves, message="archive both")

    resets = [args for args in calls if args and args[0] == "reset"]
    assert resets == [
        (
            "reset",
            "-q",
            "HEAD",
            "--",
            ":(literal)work/a.md",
            ":(literal)archive/work/a.md",
            ":(literal)work/b.md",
            ":(literal)archive/work/b.md",
        )
    ]
    assert ("reset", "-q", "HEAD") not in calls

    monkeypatch.undo()
    assert _tree_status(store, U1) == ""
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before


async def test_commit_patch_never_commits_a_file_that_appeared_mid_flight(
    tmp_path, monkeypatch
):
    """A compile commits WHAT IT WROTE. A file that arrived while it ran is not that.

    `_begin_mutation` established a clean tree at the lock entry, and that is a statement
    about ONE INSTANT: the lock excludes this framework's writers, not a person or an agent
    with a shell in `data/canonical/<user>/`. A bare `add -A` stages the whole tree, so a
    file dropped in that window rode into this compile's commit, under this compile's
    message and attributed to its skill version — a commit saying something that never
    happened. Staging is scoped to the patch's own paths, so the newcomer stays untracked,
    and the next mutation meets it outside every footprint and refuses it by name.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    real = GitCanonicalStore._run
    dropped: list[bool] = []

    def run(target, *args):
        # The window: after the precondition, before the staging.
        if args[:1] == ("add",) and not dropped:
            dropped.append(True)
            (target / "notes").mkdir(exist_ok=True)
            (target / "notes" / "agent.md").write_text(
                "an agent's file\n", encoding="utf-8"
            )
        return real(target, *args)

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(run))
    await store.commit_patch(
        U1,
        {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
        message="a compile that must carry only its own page",
    )
    monkeypatch.undo()
    assert dropped == [True]

    assert _commit_names(repo, "HEAD") == {"work/c.md"}
    # Still there, still untracked — and refused by name at the next write, which is this
    # adapter's answer to work it did not make.
    assert (repo / "notes" / "agent.md").read_text("utf-8") == "an agent's file\n"
    with pytest.raises(CanonicalDirtyError) as refused:
        await store.commit_patch(
            U1,
            {"work/d.md": _file("d-d", "d", "- D。[cite: src-04 ¶0] <!-- c:dd44 -->")},
            message="the next compile",
        )
    assert refused.value.paths == ("notes/agent.md",)


async def test_commit_patch_still_stages_a_deletion_of_one_of_its_own_paths(
    tmp_path, monkeypatch
):
    """Scoping the staging must not cost the `-A`, which is what stages a DELETION.

    `add -A -- <p>` makes the index match the working tree for that path, which for a
    tracked file that is not on disk means staging its removal. The pathspec narrows WHERE
    the flag looks; the flag is what keeps every state of those paths expressible, and it is
    kept explicit because git 2.0 changed a plain `add`'s answer to this same question —
    what the index holds for the patch's own paths must not ride on a default that has moved
    once. Simulated by removing one of the patch's own files in the same mid-flight window
    as the test above.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    real = GitCanonicalStore._run
    fired: list[bool] = []

    def run(target, *args):
        if args[:1] == ("add",) and not fired:
            fired.append(True)
            (target / "work" / "a.md").unlink()
        return real(target, *args)

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(run))
    await store.commit_patch(
        U1,
        {
            "work/a.md": _file("d-a", "a", "- A2。[cite: src-01 ¶1] <!-- c:aa11 -->"),
            "work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->"),
        },
        message="one page rewritten, one page gone",
    )
    monkeypatch.undo()
    assert fired == [True]

    # Both paths are in the commit — one added, one DELETED — and the tree is clean, which
    # is only true if the removal was staged rather than skipped.
    assert _commit_names(repo, "HEAD") == {"work/a.md", "work/c.md"}
    assert _tree_status(store, U1) == ""
    assert {doc.path for doc in await store.list(U1)} == {"work/b.md", "work/c.md"}


async def test_a_rollback_whose_recorded_path_escapes_removes_nothing_outside(tmp_path):
    """The rollback's deletions go through `_unlink_inside`, like every other one here.

    `performed` and `written` are this call's own records, but "our own" is a claim about
    PROVENANCE, not about where a string resolves: `repo / "../x"` lands outside the
    library, and a bare `(repo / path).unlink()` would follow it there. One place decides
    that question for this adapter, and the rollback asks it too — so an escaping path is
    refused and the file outside the repository is still there.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _two_movable_documents(store)
    repo = store.repo_path(U1)

    outsider = repo.parent / "outside.md"
    outsider.write_text("not the library's\n", encoding="utf-8")
    before = _snapshot_of(repo)

    # Both deleting branches, with a path that escapes: the write the rollback unlinks, and
    # the rename destination it removes when the inverse `git mv` will not run.
    store._rollback(repo, performed=[], written=["../outside.md"])
    store._rollback(repo, performed=[("work/a.md", "../outside.md")])

    assert outsider.read_text("utf-8") == "not the library's\n"
    assert _snapshot_of(repo) == before
    assert _tree_status(store, U1) == ""


# ------------------------------------------- a page whose NAME is a glob, at every write verb


_ODD = "work/products/a[1].md"
_NEIGHBOUR = "work/products/a1.md"


async def _a_page_named_like_a_glob(store: GitCanonicalStore):
    """The base every test below starts from: the odd page and the page its name matches.

    `a[1].md` is an ordinary title on disk; read as git's DEFAULT pathspec it is the
    character class that names `a1.md` instead. Both files exist here, so any verb that
    reaches for one and gets the other is caught by the neighbour rather than by a comment.
    """
    await store.commit_patch(
        U1,
        {
            _ODD: _file("d-a1", "a-1", "- A1。[cite: src-01 ¶0] <!-- c:aa11 -->"),
            _NEIGHBOUR: _file("d-a", "a", "- A。[cite: src-02 ¶0] <!-- c:bb22 -->"),
        },
        message="base",
    )
    head = (await store.snapshots(U1))[0].ref
    return head, _snapshot_of(store.repo_path(U1))


async def test_a_page_named_like_a_glob_round_trips_and_never_reaches_its_neighbour(
    tmp_path, monkeypatch
):
    """`work/products/a[1].md` is a PAGE, and `work/products/a1.md` is a different page.

    Every path these verbs hand to git came from a document — a patch's file map, an archive
    proposal's move pair, the record write, the rollback's own record of what it just did —
    so each one names ONE file and nothing else. A user's search pattern would be a different
    kind of string and would be spelled differently; none of these is one. Under git's
    default pathspec `a[1].md` is instead a character class matching `a1.md`, which would
    make the ACT wider than the decision: an archive of one page unstaging, checking out or
    removing another that no proposal ever named. `:(literal)` is that decision spelled to
    git, and this is the test that the whole round trip — archive, unarchive, and the
    rollback of a failure in either direction — carries the odd page through byte-for-byte
    while the neighbour beside it is never touched at all.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _a_page_named_like_a_glob(store)
    repo = store.repo_path(U1)
    archived_path = f"archive/{_ODD}"
    record = _file("d-a1", "a-1", "- A1 曾是交付项目 —— 已归档 <!-- c:cc33 -->")

    # 1. An archive that fails at the commit: the rollback unstages and removes the record
    #    it wrote, renames the page back, and reaches neither of those through `a1.md`.
    _fail_on(monkeypatch, lambda args: "commit" in args)
    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(
            U1,
            [(_ODD, archived_path)],
            message="archive: a[1] is done",
            writes={_ODD: record},
        )
    monkeypatch.undo()
    assert _tree_status(store, U1) == ""
    assert (await store.snapshots(U1))[0].ref == head_before
    assert _snapshot_of(repo) == tree_before

    # 2. The archive that lands: the page moves, the record takes its live path.
    await store.move_documents(
        U1,
        [(_ODD, archived_path)],
        message="archive: a[1] is done",
        writes={_ODD: record},
    )
    archived = _snapshot_of(repo)
    assert archived[archived_path] == tree_before[_ODD]
    assert archived[_ODD] == record
    assert archived[_NEIGHBOUR] == tree_before[_NEIGHBOUR]
    archived_head = (await store.snapshots(U1))[0].ref

    # 3. An unarchive that fails at the commit: the rollback checks the removed record back
    #    out of HEAD and renames the page back to `archive/`, again only those paths.
    _fail_on(monkeypatch, lambda args: "commit" in args)
    with pytest.raises(subprocess.CalledProcessError):
        await store.move_documents(
            U1,
            [(archived_path, _ODD)],
            message="unarchive: a[1] is current again",
            removals=[_ODD],
        )
    monkeypatch.undo()
    assert _tree_status(store, U1) == ""
    assert (await store.snapshots(U1))[0].ref == archived_head
    assert _snapshot_of(repo) == archived

    # 4. The unarchive that lands: byte-for-byte the page that went in, and `a1.md` has sat
    #    through all four steps without a single git command naming it.
    await store.move_documents(
        U1,
        [(archived_path, _ODD)],
        message="unarchive: a[1] is current again",
        removals=[_ODD],
    )
    assert _snapshot_of(repo) == tree_before
    assert not (repo / "archive").exists()
    assert _tree_status(store, U1) == ""
    assert {doc.path for doc in await store.list(U1)} == {_ODD, _NEIGHBOUR}


async def test_every_caller_path_reaches_git_as_a_literal_pathspec(tmp_path, monkeypatch):
    """The command SHAPE, because a tree that came back clean cannot prove the spelling.

    git's own matcher tries a literal comparison before it wildmatches, so a name like
    `a[1].md` survives the unspelt form by luck; the harm of a default pathspec is the paths
    a pattern would ADD, and the only place that is visible is the argv. So: every pathspec
    a caller's path reaches — `add`, `rm`, `reset`, `checkout`, `status` — is
    `:(literal)`-prefixed, and the bare path never appears after a `--`.

    `git mv` is the one exception, asserted rather than skipped: it is not a pathspec verb.
    It reads its two arguments as plain paths already (so the glob hazard does not arise) and
    REFUSES the magic outright — `fatal: bad source` — so spelling it `:(literal)` would
    break the move it was meant to protect.
    """
    store = GitCanonicalStore(str(tmp_path))
    await _a_page_named_like_a_glob(store)
    record = _file("d-a1", "a-1", "- A1 曾是交付项目 —— 已归档 <!-- c:cc33 -->")
    archived_path = f"archive/{_ODD}"

    calls: list[tuple[str, ...]] = []
    real = GitCanonicalStore._run

    def record_call(repo, *args):
        calls.append(args)
        return real(repo, *args)

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(record_call))
    await store.write_meta(
        U1, "skill/manifest.json", '{"version": 1}\n', message="skill: manifest v1"
    )
    await store.move_documents(
        U1,
        [(_ODD, archived_path)],
        message="archive: a[1] is done",
        writes={_ODD: record},
    )
    await store.move_documents(
        U1,
        [(archived_path, _ODD)],
        message="unarchive: a[1] is current again",
        removals=[_ODD],
    )
    monkeypatch.undo()

    pathspec_verbs = {"add", "rm", "reset", "checkout", "status"}
    scoped = [
        args
        for args in calls
        if args and args[0] in pathspec_verbs and "--" in args
    ]
    assert scoped, calls  # the assertion below is worthless over an empty list
    for args in scoped:
        spec = args[args.index("--") + 1 :]
        assert spec, args
        assert all(item.startswith(":(literal)") for item in spec), args

    # The odd path did reach git, and only ever in that spelling.
    assert any(f":(literal){_ODD}" in args for args in scoped), calls
    assert not any(_ODD in args for args in calls if args[:1] != ("mv",)), calls

    # …and `git mv` names its two paths plainly, because pathspec magic is not a thing it
    # accepts. The moves above landed, which is the proof that this is the right spelling.
    moves = [args for args in calls if args[:1] == ("mv",)]
    assert moves == [
        ("mv", "--", _ODD, archived_path),
        ("mv", "--", archived_path, _ODD),
    ]

async def test_the_dirty_path_reads_back_verbatim_through_spaces_quotes_and_renames(
    tmp_path, caplog
):
    """`--porcelain -z`, because the default porcelain format is not a path format.

    Without `-z` git QUOTES and C-escapes any path holding a space, a quote or a non-ASCII
    byte, and writes a staged rename as `old -> new` inside one field — so a library with a
    Chinese page title would be refused over a path no filesystem ever held, and an operator
    would go looking for a file that does not exist. In `-z` every path is verbatim and a
    rename's source rides as its own field after the destination.
    """
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1,
        {"work/a.md": _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->")},
        message="base",
    )
    repo = store.repo_path(U1)
    assert store._first_dirty_path(repo) is None

    spaced = "work/notes with space.md"
    (repo / spaced).write_text("scratch\n", encoding="utf-8")
    assert store._first_dirty_path(repo) == spaced
    (repo / spaced).unlink()
    assert store._first_dirty_path(repo) is None

    # A staged rename onto a name with a quote AND non-ASCII in it — both halves of what
    # the default format would have mangled, in the one entry that carries two paths.
    odd = 'work/a "quoted" 名字.md'
    # The dead writer's claim on the mess — and its FOOTPRINT holds the same odd path
    # verbatim, because the footprint is what the recovery is bounded by: a name mangled on
    # its way into the claim would read as somebody else's work and refuse.
    _write_dead_marker(store, repo, "move_documents", paths=["work/a.md", odd])
    subprocess.run(
        ["git", "-C", str(repo), "mv", "--", "work/a.md", odd],
        capture_output=True,
        text=True,
        check=True,
    )
    assert store._first_dirty_path(repo) == odd

    # And the recovery names that exact path, not an escaped rendering of it — the warning
    # line is the whole record of what was discarded, so it has to be a path a person can
    # actually go and look for.
    with caplog.at_level("WARNING"):
        await store.move_documents(
            U1, [("work/a.md", "archive/work/a.md")], message="archive a"
        )
    assert odd in " ".join(
        record.getMessage() for record in caplog.records if record.levelname == "WARNING"
    )
    # …and the staged rename is gone: `a.md` came back from HEAD and then moved as asked.
    assert not (repo / odd).exists()
    assert {doc.path for doc in await store.list(U1)} == {"archive/work/a.md"}


def _commit_names(repo, ref: str) -> set[str]:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "show",
            "--format=",
            "--name-only",
            "--no-renames",
            ref,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return {line.strip() for line in out.splitlines() if line.strip()}


async def test_a_meta_write_and_a_move_do_not_absorb_each_other(tmp_path, monkeypatch):
    """The one race the per-user job queue does not cover, and the lock does.

    `write_meta` runs in the API process, off the queue; `move_documents` runs on it. Both
    stage paths and then run `git commit`, which commits the whole index — so unserialized,
    whichever committed second would carry the other's staged paths into a commit nobody
    wrote, and the move's dirty-tree preflight would refuse over a manifest it has no
    business seeing. Under the repository lock the two sequences are whole: two commits,
    each holding exactly its own paths.

    Deterministic on purpose: the manifest write is slowed while it holds the lock, so the
    move genuinely arrives mid-write. Without the lock it would read that staged manifest
    and raise; with it, it waits.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, _ = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    real = GitCanonicalStore._run
    staged = threading.Event()

    def slow_manifest_add(repo_path, *args):
        result = real(repo_path, *args)
        if args[:2] == ("add", "--") and args[2:] == (":(literal)skill/manifest.json",):
            staged.set()  # the manifest is in the index and the lock is held
            time.sleep(0.5)  # long enough for the move to arrive mid-write
        return result

    monkeypatch.setattr(GitCanonicalStore, "_run", staticmethod(slow_manifest_add))

    # Two store instances over one root, as the API process and the worker are.
    writer = GitCanonicalStore(str(tmp_path))
    mover = GitCanonicalStore(str(tmp_path))

    def write_the_manifest():
        return asyncio.run(
            writer.write_meta(
                U1,
                "skill/manifest.json",
                '{"version": 3}\n',
                message="skill: manifest v3",
            )
        )

    def move_the_document():
        # Not a sleep: the move starts once the manifest is PROVABLY staged, so the
        # interleaving under test happens on every run and on every machine.
        assert staged.wait(timeout=30)
        return asyncio.run(
            mover.move_documents(
                U1,
                [("work/a.md", "archive/work/a.md")],
                message="archive: a is done",
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        meta_future = pool.submit(write_the_manifest)
        move_future = pool.submit(move_the_document)
        meta_ref = meta_future.result(timeout=30)
        move_ref = move_future.result(timeout=30)

    monkeypatch.undo()

    # Two commits, in the order the lock granted them, and neither is empty.
    assert meta_ref.ref != move_ref.ref != head_before
    history = [snapshot.ref for snapshot in await store.snapshots(U1)]
    assert history[:3] == [move_ref.ref, meta_ref.ref, head_before]

    # Neither absorbed the other's paths.
    assert _commit_names(repo, meta_ref.ref) == {"skill/manifest.json"}
    assert _commit_names(repo, move_ref.ref) == {
        "work/a.md",
        "archive/work/a.md",
    }
    assert _tree_status(store, U1) == ""
    assert sorted(doc.path for doc in await store.list(U1)) == [
        "archive/work/a.md",
        "work/b.md",
    ]


# --------------------------------------------- finding a commit by its trailer, in a range


async def test_find_commit_with_trailer_reads_the_range_not_just_head(tmp_path):
    """The resume question is "is my commit in the history", and HEAD alone cannot answer it.

    `write_meta` runs in the API process, off the per-user queue, so a manifest write can
    land on top of an archive's move commit. Reading HEAD's trailer would then say "not
    mine"; the range since the state the caller planned against says "there it is, one commit
    down". Exclusive of `since` on purpose — that commit is the one the caller already saw.
    """
    store = GitCanonicalStore(str(tmp_path))
    planned, _ = await _two_movable_documents(store)

    move = await store.move_documents(
        U1,
        [("work/a.md", "archive/work/a.md")],
        message="archive 1 document\n\nSkill-Version: v1\nArchive-Proposal: p-1",
    )
    manifest = await store.write_meta(
        U1, "skill/manifest.json", '{"version": 3}\n', message="skill: manifest v3"
    )
    assert (await store.snapshots(U1))[0].ref == manifest.ref  # HEAD is NOT the move

    found = await store.find_commit_with_trailer(
        U1, key="Archive-Proposal", value="p-1", since=SnapshotRef(ref=planned)
    )
    assert found is not None and found.ref == move.ref

    # HEAD's own trailer is absent, which is exactly the answer that used to strand the job.
    assert await store.commit_trailer(U1, SnapshotRef(ref=manifest.ref), "Archive-Proposal") is None

    # A value nobody wrote is not found, however wide the walk.
    assert (
        await store.find_commit_with_trailer(
            U1, key="Archive-Proposal", value="p-nobody", since=SnapshotRef(ref=planned)
        )
        is None
    )
    assert (
        await store.find_commit_with_trailer(U1, key="Archive-Proposal", value="p-nobody")
        is None
    )

    # No `since` walks the whole history and finds the same commit.
    assert (
        await store.find_commit_with_trailer(U1, key="Archive-Proposal", value="p-1")
    ).ref == move.ref

    # `since` is EXCLUSIVE: bounded to what happened after the move, the move is not in range.
    assert (
        await store.find_commit_with_trailer(
            U1, key="Archive-Proposal", value="p-1", since=SnapshotRef(ref=move.ref)
        )
        is None
    )

    # An empty library has no commit to find, and answers so rather than failing.
    assert (
        await store.find_commit_with_trailer(U2, key="Archive-Proposal", value="p-1")
        is None
    )


# ------------------------------------------------------ restoring a prebuilt library


def _bundle_of(tmp_path, store: GitCanonicalStore, user: UserId):
    bundle = tmp_path / "canonical.bundle"
    subprocess.run(
        ["git", "-C", str(store.repo_path(user)), "bundle", "create", str(bundle), "--all"],
        capture_output=True,
        text=True,
        check=True,
    )
    return bundle


async def test_restore_repository_clones_a_bundle_and_never_overwrites(tmp_path):
    source = GitCanonicalStore(str(tmp_path / "source"))
    head, tree = await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    assert await target.restore_repository(U2, bundle=bundle) is True
    assert {doc.path: doc.body for doc in await target.list(U2)} == tree
    assert (await target.snapshots(U2))[0].ref == head
    assert _tree_status(target, U2) == ""
    # The identity a restored library commits under is pinned locally, exactly as it is for a
    # repository this adapter creates itself.
    repo = target.repo_path(U2)
    assert (
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        == "pneuma_knowledge@local"
    )
    # The lock file survived the graft — it is the file a concurrent writer is blocked on.
    assert (repo / ".git" / "pneuma.lock").is_file()

    # Canonical is authoritative: a second restore refuses and writes nothing.
    assert await target.restore_repository(U2, bundle=bundle) is False
    assert (await target.snapshots(U2))[0].ref == head

    # And the restored repository is an ordinary one from here on.
    after = await target.commit_patch(
        U2, {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
        message="compile after restore",
    )
    assert after.ref != head


async def test_a_restore_over_a_grafted_head_drops_a_stale_claim_and_does_nothing(tmp_path):
    """Branch (i). `.git/HEAD` is the LAST thing the graft moves, so its presence means a
    restore completed — including one killed in the instant between the graft and its own
    marker clear. That reads as done, not as a crash: the claim is dropped and the call
    answers False, leaving the library byte-for-byte."""
    source = GitCanonicalStore(str(tmp_path / "source"))
    head, tree = await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    assert await target.restore_repository(U2, bundle=bundle) is True
    # The state a crash between the graft and the clear leaves behind.
    repo = target.repo_path(U2)
    target._write_marker(repo, "restore_repository", paths=(), pre_existing=[])

    assert await target.restore_repository(U2, bundle=bundle) is False
    assert not target._marker_path(repo).exists()
    assert (await target.snapshots(U2))[0].ref == head
    assert {doc.path: doc.body for doc in await target.list(U2)} == tree
    # …and the next ordinary write meets a clean tree with no claim on it.
    await target.commit_patch(
        U2, {"work/z.md": _file("d-z", "z", "- Z。[cite: src-09 ¶0] <!-- c:zz99 -->")},
        message="after the stale claim",
    )
    assert _tree_status(target, U2) == ""


async def test_a_restore_into_a_directory_holding_unclaimed_files_is_refused(tmp_path):
    """Branch (ii). Files with no claim beside them are somebody's — a half-copied library, a
    directory reused by hand — and a clone that overwrote them would be this adapter
    discarding work it did not make. Refused, naming every path, having written nothing."""
    source = GitCanonicalStore(str(tmp_path / "source"))
    await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / "work").mkdir(parents=True)
    (repo / "work" / "mine.md").write_text("someone's draft", encoding="utf-8")
    (repo / "notes.txt").write_text("and their notes", encoding="utf-8")

    with pytest.raises(CanonicalDirtyError) as refused:
        await target.restore_repository(U2, bundle=bundle)
    assert set(refused.value.paths) == {"notes.txt", "work/mine.md"}
    assert refused.value.detail.startswith("canonical_dirty:")
    # Byte-for-byte, and no repository made over the top of it.
    assert (repo / "work" / "mine.md").read_text(encoding="utf-8") == "someone's draft"
    assert (repo / "notes.txt").read_text(encoding="utf-8") == "and their notes"
    assert not (repo / ".git" / "HEAD").exists()
    assert not target._marker_path(repo).exists()


async def test_a_restore_recovers_its_own_half_grafted_checkout(tmp_path, caplog):
    """Branch (iii). A dead restore's claim with no HEAD, over files it did not record as
    already-here, is this adapter's own half-materialized checkout: `git clone` refuses a
    non-empty target and a graft over a partial one would mix two clones' objects in one
    `.git/`, so those leftovers are logged at WARNING and removed — file by file, keeping the
    lock and the claim — and this restore then runs to completion.

    `pre_existing` is the restore's half of the same two-part proof every other recovery here
    requires. A restore cannot enumerate its own footprint — nobody knows what a clone will
    materialize until it has — so it records the inverse, and what it did not record is what
    it made."""
    source = GitCanonicalStore(str(tmp_path / "source"))
    head, tree = await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    # What a restore killed mid-graft leaves: some of the clone's `.git/` children and some
    # of its working tree, and NO `.git/HEAD` — plus its own claim.
    (repo / ".git" / "objects").mkdir()
    (repo / ".git" / "objects" / "half").write_text("truncated", encoding="utf-8")
    (repo / ".git" / "index").write_bytes(b"DIRC")
    (repo / "work").mkdir()
    (repo / "work" / "a.md").write_text("half a document", encoding="utf-8")
    # The claim records what the target held BEFORE that restore began — nothing — so
    # everything here now is its own clone's, and all of it may go.
    _write_dead_marker(target, repo, "restore_repository", pre_existing=[])

    with caplog.at_level("WARNING"):
        assert await target.restore_repository(U2, bundle=bundle) is True

    assert {doc.path: doc.body for doc in await target.list(U2)} == tree
    assert (await target.snapshots(U2))[0].ref == head
    assert _tree_status(target, U2) == ""
    assert not target._marker_path(repo).exists()
    # The paths are NAMED, because a line an operator cannot act on is not a record.
    warned = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any("work/a.md" in line and ".git/objects/half" in line for line in warned)


async def test_a_restore_refuses_a_target_its_claim_accounts_for_nothing_in(tmp_path):
    """A restore's own claim, a claimant that is provably gone — and NO `pre_existing` list.

    This branch DELETES FILES, so the claim has to say which of them the dead restore made.
    A restore cannot record a footprint the way every other operation does, so it records the
    inverse — what the target held before it began — and everything else is its own. A claim
    that recorded no such list accounts for nothing: it cannot tell a dead clone's leftovers
    from a half-copied library, a directory reused by hand, or an agent's scratch files. And
    a claim can outlive its process in an orderly way (a clear that could neither unlink nor
    replace its file), so its pid reading as dead is not enough on its own. Refused, and the
    files stay."""
    source = GitCanonicalStore(str(tmp_path / "source"))
    await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    (repo / "work").mkdir()
    (repo / "work" / "a.md").write_text("somebody's half-copied page\n", encoding="utf-8")
    (repo / "handover.md").write_text("an agent's note\n", encoding="utf-8")
    before = _snapshot_of(repo)
    _write_dead_marker(target, repo, "restore_repository")  # no pre_existing recorded

    with pytest.raises(CanonicalDirtyError) as refused:
        await target.restore_repository(U2, bundle=bundle)
    assert set(refused.value.paths) == {"handover.md", "work/a.md"}
    assert refused.value.claimed_by == "restore_repository"
    assert refused.value.unproven is None
    assert set(refused.value.outside or ()) == {"handover.md", "work/a.md"}
    assert refused.value.covered is None
    assert "recorded NO paths at all" in str(refused.value)

    # Byte for byte, and the refusal released its own claim on the way out.
    assert _snapshot_of(repo) == before
    assert not target._marker_path(repo).exists()
    assert not (repo / ".git" / "HEAD").exists()

    # …and with the list a real restore would have recorded, the same target IS recovered.
    _write_dead_marker(target, repo, "restore_repository", pre_existing=[])
    assert await target.restore_repository(U2, bundle=bundle) is True
    assert {doc.path for doc in await target.list(U2)} == {"work/a.md", "work/b.md"}


async def test_a_restore_keeps_what_its_claim_recorded_as_already_here(tmp_path):
    """The scoping, on the branch that deletes. A dead restore's claim recorded one file as
    already-here; that file is not the dead clone's, and it survives.

    Everything else the target holds is what that restore materialized itself, and only that
    is removed. The whole-directory wipe this replaces could not tell them apart and took
    both — which is the same fault as a whole-tree `reset --hard`, in the one place where it
    deletes files rather than rolling changes back."""
    source = GitCanonicalStore(str(tmp_path / "source"))
    head, tree = await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    # What the operator left in the directory before any restore ran…
    (repo / "handover.md").write_text("read me first\n", encoding="utf-8")
    # …and what a restore that died mid-graft then materialized on top of it.
    (repo / ".git" / "objects").mkdir()
    (repo / ".git" / "objects" / "half").write_text("truncated", encoding="utf-8")
    (repo / ".git" / "index").write_bytes(b"DIRC")
    (repo / "work").mkdir()
    (repo / "work" / "a.md").write_text("half a document", encoding="utf-8")
    _write_dead_marker(
        target, repo, "restore_repository", pre_existing=["handover.md"]
    )

    assert await target.restore_repository(U2, bundle=bundle) is True

    # The operator's file is still there, untouched…
    assert (repo / "handover.md").read_text("utf-8") == "read me first\n"
    # …and the dead clone's leftovers are gone, replaced by a whole library.
    assert not (repo / ".git" / "objects" / "half").exists()
    assert {doc.path: doc.body for doc in await target.list(U2)} == tree
    assert (await target.snapshots(U2))[0].ref == head
    assert not target._marker_path(repo).exists()
    # And the honest consequence, stated rather than smoothed over: keeping somebody's file
    # leaves it UNTRACKED in the restored library, so the next writer meets a dirty tree with
    # no claim on it and refuses. That is the same answer this adapter gives anywhere else it
    # meets work it did not make — the operator commits it, moves it, or removes it.
    assert _tree_status(target, U2) == "?? handover.md"
    with pytest.raises(CanonicalDirtyError) as blocked:
        await target.commit_patch(
            U2,
            {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
            message="a compile over the restored library",
        )
    assert blocked.value.paths == ("handover.md",)


async def test_a_restore_lists_and_keeps_the_non_files_its_claim_recorded(tmp_path):
    """The restore's listing counts ENTRIES, so a non-file cannot slip past it either way.

    `is_file()` follows symlinks and answers False for a broken link, for a link to a
    directory, and for a fifo — and answers False for a directory outright. Under a
    file-only listing each of those was invisible in BOTH readings at once: absent from the
    `pre_existing` a claim records, so a later restore could delete it as residue it never
    made, and absent from the `present_now` that decides, so one that appeared in the window
    between them could never be noticed.

    An empty directory is the case that has to be listed rather than inferred: nothing else
    accounts for it, it is what a graft killed between its `mkdir` and its children leaves,
    and the next graft's `mkdir` collides with it. So one the claim recorded is KEPT and one
    it did not is removed with the rest of the dead clone's residue.
    """
    source = GitCanonicalStore(str(tmp_path / "source"))
    head, tree = await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    # What the operator left before any restore ran: a BROKEN symlink and an EMPTY directory.
    os.symlink(str(tmp_path / "nowhere"), repo / "handover-link")
    (repo / "keep-dir").mkdir()
    # …and what a restore that died mid-graft materialized on top of it, an empty directory
    # of its own among it.
    (repo / ".git" / "objects").mkdir()
    (repo / ".git" / "objects" / "half").write_text("truncated", encoding="utf-8")
    (repo / "ghost-dir").mkdir()

    # Both non-files are LISTED — the listing is the evidence the claim is written from.
    listed = target._restore_leftovers(repo)
    assert set(listed) == {"handover-link", "keep-dir", ".git/objects/half", "ghost-dir"}

    _write_dead_marker(
        target, repo, "restore_repository", pre_existing=["handover-link", "keep-dir"]
    )

    assert await target.restore_repository(U2, bundle=bundle) is True

    # Kept, because the claim recorded them: the broken link is still a broken link, and the
    # empty directory is still there.
    assert (repo / "handover-link").is_symlink()
    assert not (repo / "handover-link").exists()  # still broken, not replaced
    assert (repo / "keep-dir").is_dir()
    # Removed, because nothing recorded them: the dead clone's own residue, the empty
    # directory it left included.
    assert not (repo / ".git" / "objects" / "half").exists()
    assert not (repo / "ghost-dir").exists()
    # And a whole library on top.
    assert {doc.path: doc.body for doc in await target.list(U2)} == tree
    assert (await target.snapshots(U2))[0].ref == head
    assert not target._marker_path(repo).exists()



async def test_a_restore_refuses_a_file_that_appeared_after_its_claim(tmp_path, monkeypatch):
    """The list that DECIDED is not the list that ACTS — so the target is read again.

    `leftovers` is read before the claim is written and before three branches are weighed,
    and the lock excludes only this framework's own writers: a person or an agent with a
    shell in the directory can drop a file in during that window. Deleting off the stale
    snapshot would take it (it falls outside `pre_existing`) or miss it. Anything that
    appeared since the claim cannot be the dead clone's — that clone stopped writing when it
    died — so it is refused by name, and nothing is deleted.
    """
    source = GitCanonicalStore(str(tmp_path / "source"))
    await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)
    (repo / ".git").mkdir(parents=True)
    (repo / "work").mkdir()
    (repo / "work" / "a.md").write_text("half a document", encoding="utf-8")
    _write_dead_marker(target, repo, "restore_repository", pre_existing=[])

    real = GitCanonicalStore._restore_leftovers
    calls: list[int] = []

    def listing(self, repo_arg):
        # The second read is the one taken immediately before the deletion; somebody writes
        # into the directory in the instant before it.
        calls.append(1)
        if len(calls) == 2:
            (repo_arg / "handover.md").write_text("an agent's note\n", encoding="utf-8")
        return real(self, repo_arg)

    monkeypatch.setattr(GitCanonicalStore, "_restore_leftovers", listing)

    with pytest.raises(CanonicalDirtyError) as refused:
        await target.restore_repository(U2, bundle=bundle)
    monkeypatch.undo()

    assert refused.value.outside == ("handover.md",)
    assert refused.value.claimed_by == "restore_repository"
    # Nothing was deleted — not the intruder, and not the dead clone's own leftovers either:
    # a target holding work this call cannot account for is refused whole.
    assert (repo / "handover.md").read_text("utf-8") == "an agent's note\n"
    assert (repo / "work" / "a.md").read_text("utf-8") == "half a document"
    assert not (repo / ".git" / "HEAD").exists()
    assert not target._marker_path(repo).exists()


async def test_the_graft_refuses_a_destination_that_appeared_concurrently(
    tmp_path, monkeypatch
):
    """The refusal is the MOVE, not a check in front of it.

    `if destination.exists(): raise` then `shutil.move` is two syscalls with a window between
    them, and the move CLOBBERS — so a file appearing in that window was silently overwritten
    by the very branch that exists to preserve such files. Each landing is now the POSIX
    primitive that fails EEXIST by itself: `link` for a file, `symlink` for a link, `mkdir`
    for a directory. Here the destination is created in the last possible instant, INSIDE the
    call to `os.link`'s wrapper, and the link itself is what refuses.
    """
    source = GitCanonicalStore(str(tmp_path / "source"))
    await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    target = GitCanonicalStore(str(tmp_path / "target"))
    repo = target.repo_path(U2)

    real_link = os.link
    raced: dict[str, pathlib.Path] = {}

    def racing_link(src, dst, **kwargs):
        if not raced:
            raced["path"] = pathlib.Path(dst)
            pathlib.Path(dst).write_text("somebody got here first\n", encoding="utf-8")
        return real_link(src, dst, **kwargs)

    monkeypatch.setattr(os, "link", racing_link)
    with pytest.raises(CanonicalMoveError) as refused:
        await target.restore_repository(U2, bundle=bundle)
    monkeypatch.undo()

    landed = raced["path"]
    assert refused.value.path == str(landed.relative_to(repo))
    # Byte for byte: the graft stopped rather than writing over it…
    assert landed.read_text("utf-8") == "somebody got here first\n"
    # …and the target is still not a repository to anyone, because HEAD moves last.
    assert not (repo / ".git" / "HEAD").exists()
    assert not target._marker_path(repo).exists()

async def test_a_write_that_cannot_claim_the_tree_does_not_run(tmp_path, monkeypatch):
    """The marker is MANDATORY. Unmarked, this call's own crash residue would arrive at the
    next writer as somebody else's work — refused, and refused again until a person
    intervenes — so a claim that cannot be written stops the write instead."""
    store = GitCanonicalStore(str(tmp_path))
    await store.commit_patch(
        U1, {"work/a.md": _file("d-a", "a", "- A。[cite: src-01 ¶0] <!-- c:aa11 -->")},
        message="base",
    )
    head = (await store.snapshots(U1))[0].ref

    # A claim path that cannot be written: its parent directory does not exist.
    monkeypatch.setattr(
        GitCanonicalStore,
        "_marker_path",
        staticmethod(lambda repo: repo / ".git" / "nowhere" / "pneuma.inflight"),
    )
    with pytest.raises(CanonicalMarkerError) as refused:
        await store.commit_patch(
            U1, {"work/b.md": _file("d-b", "b", "- B。[cite: src-02 ¶0] <!-- c:bb22 -->")},
            message="unclaimable",
        )
    assert "pneuma.inflight" in refused.value.path
    # In the move family, so every caller that reports a refused write already catches it.
    assert isinstance(refused.value, CanonicalMoveError)
    # NOTHING was written: no commit, no file, no dirty tree.
    assert (await store.snapshots(U1))[0].ref == head
    assert _tree_status(store, U1) == ""
    assert not (store.repo_path(U1) / "work" / "b.md").exists()


async def test_a_restore_and_a_commit_on_the_same_repo_serialize(tmp_path, monkeypatch):
    """A restore materializes a whole working tree; the lock is what keeps that from being a
    second writer.

    Outside the lock, `commit_patch` would run its `add -A` — and before it, the residue
    recovery that reads any uncommitted change as a dead writer's leftovers and DISCARDS it —
    over a half-materialized checkout. Under the lock the restore is one whole step from the
    adapter's point of view: the compile either waits for a finished library and commits on
    top of it, or (restoring into a repository that already exists) is refused and the
    compile is untouched. Either order is a real state; a mixture is not.

    Deterministic on purpose: the clone is slowed while it holds the lock, so the commit
    genuinely arrives mid-restore.
    """
    source = GitCanonicalStore(str(tmp_path / "source"))
    head, tree = await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    real_graft = GitCanonicalStore._graft
    cloned = threading.Event()

    def slow_graft(staging, repo):
        cloned.set()  # the clone is on disk in staging and the lock is held
        time.sleep(0.5)  # long enough for the compile to arrive mid-restore
        real_graft(staging, repo)

    monkeypatch.setattr(GitCanonicalStore, "_graft", staticmethod(slow_graft))

    # Two store instances over one root, as the restore script and the worker are.
    restorer = GitCanonicalStore(str(tmp_path / "target"))
    compiler = GitCanonicalStore(str(tmp_path / "target"))

    def restore():
        return asyncio.run(restorer.restore_repository(U2, bundle=bundle))

    def compile_one():
        assert cloned.wait(timeout=30)  # not a sleep: the restore is PROVABLY mid-flight
        return asyncio.run(
            compiler.commit_patch(
                U2,
                {"work/c.md": _file("d-c", "c", "- C。[cite: src-03 ¶0] <!-- c:cc33 -->")},
                message="compile during restore",
            )
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        restore_future = pool.submit(restore)
        compile_future = pool.submit(compile_one)
        restored = restore_future.result(timeout=30)
        commit = compile_future.result(timeout=30)

    monkeypatch.undo()

    assert restored is True
    # The compile waited and committed ON TOP of the restored library, rather than into a
    # half-materialized one: the bundle's head is still in the history, under its commit.
    history = [snapshot.ref for snapshot in await restorer.snapshots(U2)]
    assert history[:2] == [commit.ref, head]
    assert _tree_status(restorer, U2) == ""
    paths = {doc.path: doc.body for doc in await restorer.list(U2)}
    assert set(paths) == set(tree) | {"work/c.md"}
    for path, body in tree.items():
        assert paths[path] == body  # nothing the restore brought was swept away


async def test_a_reader_never_sees_a_half_grafted_restore(tmp_path, monkeypatch):
    """The restore's OTHER concurrent party: a reader, which never takes the lock.

    `_repo` treats `.git/HEAD` as the marker that a repository is there and returns without
    locking the moment it exists, so every read path — `list`, `read`, `snapshots` — runs
    beside a restore rather than behind it. That makes the order the graft moves things in
    load-bearing: HEAD moves LAST, after the refs, the objects and the checked-out documents,
    so the state a lock-free reader can observe is either "no repository yet" (and it blocks
    in `_repo`, on the lock the restore holds) or a repository that is already whole. There
    is no third state to see, and a `git archive` over a half-arrived one has no reader.

    Deterministic on purpose: the graft is paused ON the move that publishes HEAD, and the
    reader is sent in while it is held there.
    """
    source = GitCanonicalStore(str(tmp_path / "source"))
    head, tree = await _two_movable_documents(source)
    bundle = _bundle_of(tmp_path, source, U1)

    at_head = threading.Event()
    release = threading.Event()
    observed: dict[str, list[str]] = {}

    real_graft_one = GitCanonicalStore._graft_one

    def paused_graft_one(source, destination, repo_arg):
        """The real graft, stopped on the one landing the whole ordering is about."""
        if destination.name == "HEAD" and destination.parent.name == ".git":
            repo = destination.parent.parent
            observed["git"] = sorted(p.name for p in (repo / ".git").iterdir())
            observed["work"] = sorted(
                str(p.relative_to(repo)) for p in repo.rglob("*.md")
            )
            at_head.set()
            assert release.wait(timeout=30)
        return real_graft_one(source, destination, repo_arg)

    monkeypatch.setattr(
        GitCanonicalStore, "_graft_one", staticmethod(paused_graft_one)
    )

    # Two store instances over one root, as the restore script and the API process are.
    restorer = GitCanonicalStore(str(tmp_path / "target"))
    reader = GitCanonicalStore(str(tmp_path / "target"))

    def restore():
        return asyncio.run(restorer.restore_repository(U2, bundle=bundle))

    def read_mid_restore():
        assert at_head.wait(timeout=30)  # not a sleep: the graft is PROVABLY at HEAD
        return asyncio.run(reader.list(U2))

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        restore_future = pool.submit(restore)
        read_future = pool.submit(read_mid_restore)
        assert at_head.wait(timeout=30)
        time.sleep(0.5)  # long enough for the reader to reach the repository first
        release.set()
        restored = restore_future.result(timeout=30)
        mid = read_future.result(timeout=30)

    monkeypatch.undo()

    assert restored is True
    # Everything else had already arrived when HEAD was still in staging — the ordering
    # itself, read at the only instant it can be read.
    assert "HEAD" not in observed["git"]
    assert {"objects", "refs"} <= set(observed["git"])
    assert observed["work"] == sorted(tree)
    # The reader saw one of the two real states and never a partial tree: it either found no
    # repository at all (empty) or waited and read the finished one.
    assert not mid or {doc.path: doc.body for doc in mid} == tree
    # …and once the graft is done it lists the restored library.
    assert {doc.path: doc.body for doc in await restorer.list(U2)} == tree
    assert (await restorer.snapshots(U2))[0].ref == head
    assert _tree_status(restorer, U2) == ""
