"""Checkpoint extraction: the git walk, the preset bundle, and the reconciliation guard."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pneuma_knowledge_eval.artifacts import (
    family_of,
    is_catchall,
    load_git_trajectory,
    load_preset_trajectory,
    unowned_paths,
)
from pneuma_knowledge_eval.errors import EvalInputError

from _fixtures import claim, document, source, trajectory


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "eval",
            "GIT_AUTHOR_EMAIL": "eval@example.com",
            "GIT_COMMITTER_NAME": "eval",
            "GIT_COMMITTER_EMAIL": "eval@example.com",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        },
    )


def _commit(repo: Path, files: dict[str, str], subject: str, trailer: str = "v1") -> None:
    for path, text in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", f"{subject}\n\nSkill-Version: {trailer}\n")


def test_git_walk_reads_every_commit_as_a_checkpoint(tmp_path: Path):
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(
        repo,
        {"memory/profile.md": document("memory/profile.md", [claim("Owner.", "aaaa1111")])},
        "compile " + "1" * 32,
    )
    _commit(
        repo,
        {
            "memory/topics/x.md": document(
                "memory/topics/x.md", [claim("Second round.", "bbbb2222", cite="s1 ¶0")]
            )
        },
        "compile " + "2" * 32,
    )

    loaded = load_git_trajectory(repo, consumed_by_job={"2" * 32: ["s1"]})

    assert [cp.label for cp in loaded.checkpoints] == ["r01", "r02"]
    assert loaded.checkpoints[0].job_id == "1" * 32
    assert loaded.checkpoints[1].consumed_source_ids == ("s1",)
    # the file table is cumulative, exactly as committed
    assert set(loaded.head.files) == {"memory/profile.md", "memory/topics/x.md"}
    assert loaded.head.anchor_set == {"aaaa1111", "bbbb2222"}
    # the skill version rides the trailer, so families come from the version that compiled
    assert loaded.checkpoints[1].trailers["Skill-Version"] == "v1"
    assert "memory/profile.md" in loaded.path_templates


def test_a_non_compile_commit_has_no_job_id(tmp_path: Path):
    """Evolve commits are identified structurally: the commit MESSAGE is an overridable
    prompt surface, so a deployment's wording must not change what the evaluator sees."""
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _commit(repo, {"memory/profile.md": document("memory/profile.md", [claim("A.", "a1a1a1a1")])}, "compile " + "3" * 32)
    _commit(
        repo,
        {"memory/topics/y.md": document("memory/topics/y.md", [claim("B.", "b1b1b1b1")])},
        "schema evolve: reorganized 4 claims",
    )

    loaded = load_git_trajectory(repo)

    assert loaded.checkpoints[0].job_id is not None
    assert loaded.checkpoints[1].job_id is None


def test_empty_repository_fails_loud(tmp_path: Path):
    repo = tmp_path / "canonical"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    # git itself refuses to log an unborn branch; either way the loader must not return an
    # empty trajectory that every later rate would silently divide by.
    with pytest.raises(EvalInputError, match="commits"):
        load_git_trajectory(repo)


def test_missing_repository_fails_loud(tmp_path: Path):
    with pytest.raises(EvalInputError, match="not a canonical git repository"):
        load_git_trajectory(tmp_path / "nowhere")


def test_prose_chars_excludes_citation_and_anchor_markup():
    """The compression numerator must not count the provenance backbone as verbosity."""
    body = document(
        "memory/topics/t.md",
        [claim("Twelve chars.", "c0ffee11", cite="abcdef0123456789 ¶0-2")],
    )
    loaded = trajectory([{"memory/topics/t.md": body}])
    head = loaded.head
    assert head.prose_chars < head.canonical_chars
    # the markup delta covers at least the anchor comment plus the citation marker
    assert head.canonical_chars - head.prose_chars >= len(
        "<!-- c:c0ffee11 -->"
    ) + len("[cite: abcdef0123456789 ¶0-2]")


def test_family_and_ownership_use_the_gate_matcher():
    templates = (
        "memory/profile.md",
        "memory/people/{slug}.md",
        "memory/topics/{slug}.md",
        "materials/{slug}.md",
    )
    assert family_of("memory/people/ann-lee.md", templates) == "memory/people/{slug}.md"
    assert family_of("memory/profile.md", templates) == "memory/profile.md"
    assert family_of("work/products/x.md", templates) is None
    assert is_catchall("memory/topics/{slug}.md")
    assert not is_catchall("memory/people/{slug}.md")

    loaded = trajectory([{"stray/file.md": document("stray/file.md", [claim("X.", "9999aaaa")])}])
    assert unowned_paths(loaded.head, loaded.path_templates) == ("stray/file.md",)


def test_l0_chars_needs_both_sources_and_declared_consumption():
    files = {"memory/topics/t.md": document("memory/topics/t.md", [claim("A.", "1111aaaa")])}
    without_sources = trajectory([files])
    assert without_sources.l0_chars_through(0) is None

    without_consumption = trajectory([files], sources={"s1": source("s1", ["0123456789"])})
    assert without_consumption.l0_chars_through(0) is None

    complete = trajectory(
        [files], sources={"s1": source("s1", ["0123456789"])}, consumed=[["s1"]]
    )
    assert complete.l0_chars_through(0) == 10


# ────────────────────────────────────────────────────────────────── the shipped bundle


def test_preset_bundle_loads_and_reconciles(preset_trajectory):
    manifest = json.loads(
        (Path(preset_trajectory.origin["bundle_path"]) / "manifest.json").read_text("utf-8")
    )
    counts = manifest["counts"]
    assert len(preset_trajectory.checkpoints) == counts["canonical_commits"]
    assert len(preset_trajectory.head.claims) == counts["pg"]["canonical_claims"]
    assert len(preset_trajectory.sources) == counts["pg"]["sources"]
    assert sum(r.block_count for r in preset_trajectory.sources.values()) == counts["pg"]["blocks"]
    # every compile checkpoint names the source that round consumed
    assert all(cp.consumed_source_ids for cp in preset_trajectory.checkpoints)


def test_preset_reconciliation_rejects_a_truncated_bundle(tmp_path: Path, preset_bundle: Path):
    """A short archive must fail rather than produce a scorecard over the wrong denominator."""
    import shutil

    copy = tmp_path / "bundle"
    shutil.copytree(preset_bundle, copy)
    manifest = json.loads((copy / "manifest.json").read_text("utf-8"))
    manifest["counts"]["canonical_commits"] += 5
    (copy / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvalInputError, match="canonical commits"):
        load_preset_trajectory(copy)


def test_missing_preset_manifest_fails_loud(tmp_path: Path):
    with pytest.raises(EvalInputError, match="no preset manifest"):
        load_preset_trajectory(tmp_path)
