"""GitCanonicalStore over real git in a temp dir: round-trip, `at` snapshot reads,
tags, and two-user isolation (invariant I1)."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import pathlib
import shutil
import subprocess
import threading
import time

import pytest

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.ports.canonical_store import CanonicalMoveError
from pneuma_knowledge_service.adapters.git_canonical import GitCanonicalStore

U1 = UserId("u-git-alice")
U2 = UserId("u-git-bob")


def _file(doc_id: str, slug: str, body: str) -> str:
    return render_document(
        {"doc_id": doc_id, "type": "person", "slug": slug}, body
    )


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
    a crashed archive landing inside a compile, under its message. Under the repository lock
    a dirty tree at the entry of a mutating method has exactly one explanation (every writer
    commits; the lock excludes a live one), so the recovery is safe and the record of what
    it removed is the WARNING line, which names every path.
    """
    store = GitCanonicalStore(str(tmp_path))
    head_before, tree_before = await _two_movable_documents(store)
    repo = store.repo_path(U1)

    # A crash mid-`move_documents`: the first rename is staged (and the directory it made
    # is on disk), the process is gone.
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

    warnings = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert any(
        "crash residue" in message
        and "commit_patch" in message
        and "archive/work/a.md" in message
        for message in warnings
    ), warnings


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
            "work/a.md",
            "archive/work/a.md",
            "work/b.md",
            "archive/work/b.md",
        )
    ]
    assert ("reset", "-q", "HEAD") not in calls

    monkeypatch.undo()
    assert _tree_status(store, U1) == ""
    assert (await store.snapshots(U1))[0].ref == head_before
    assert {doc.path: doc.body for doc in await store.list(U1)} == tree_before


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
        if args[:2] == ("add", "--") and args[2:] == ("skill/manifest.json",):
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

    class _PausingShutil:
        """The real `shutil`, stopped on the one move the whole ordering is about."""

        @staticmethod
        def move(src, dst):
            target = pathlib.Path(dst)
            if target.name == "HEAD" and target.parent.name == ".git":
                repo = target.parent.parent
                observed["git"] = sorted(p.name for p in (repo / ".git").iterdir())
                observed["work"] = sorted(
                    str(p.relative_to(repo)) for p in repo.rglob("*.md")
                )
                at_head.set()
                assert release.wait(timeout=30)
            return shutil.move(src, dst)

        @staticmethod
        def rmtree(*args, **kwargs):
            return shutil.rmtree(*args, **kwargs)

    monkeypatch.setattr(
        "pneuma_knowledge_service.adapters.git_canonical.shutil", _PausingShutil
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
