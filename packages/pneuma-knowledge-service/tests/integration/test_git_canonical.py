"""GitCanonicalStore over real git in a temp dir: round-trip, `at` snapshot reads,
tags, and two-user isolation (invariant I1)."""

from __future__ import annotations

import subprocess

import pytest

from pneuma_knowledge_core.compile.documents import render_document
from pneuma_knowledge_core.domain.ids import DocumentId, UserId
from pneuma_knowledge_service.adapters.git_canonical import GitCanonicalStore

U1 = UserId("u-git-alice")
U2 = UserId("u-git-bob")


def _file(pneuma_id: str, slug: str, body: str) -> str:
    return render_document(
        {"pneuma_id": pneuma_id, "type": "person", "slug": slug}, body
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
            "skill/manifest.json": '{"base_version":"opc-developer-v1"}',
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
