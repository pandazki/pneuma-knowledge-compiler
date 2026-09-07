"""Putting a rendered package on disk, and telling whether what is there still is one.

Two guarantees, and both of them are about somebody else's files:

* **the install is wholesale.** The skill directory is removed and rewritten, so a file that
  a previous version rendered and this one does not cannot survive as a stale reference the
  agent will happily read. Nothing outside that directory is removed.
* **the instructions file is spliced, never rewritten.** `AGENTS.md` / `CLAUDE.md` is the
  Owner's own document. One `pkc:start … pkc:end` block is replaced or appended; every byte
  outside the markers is written back exactly as it was read.

`verify_skill_package` is the freshness gate §7 asks for, in the form a command can exit on:
the list of paths where the disk and a fresh rendering disagree. Empty means the installed
skill is the current rendering of the current catalog, contract and components — which is the
only condition under which the hash in a commit trailer means anything.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

from .backends import BLOCK_END, BLOCK_START, SKILL_NAME, BackendManifest
from .skillpack import SkillPackage

#: The file that records what was installed, written BESIDE the skill directory so a
#: wholesale purge of that directory does not take it with it. The shim reads its `sha256`
#: into `PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH`.
VERSION_FILE = "skill-version.json"

#: Which of a package's paths install outside the skill directory, and where. A workflow is
#: not a skill file: the harness looks for it in its own directory, so the package renders it
#: under `workflows/` and the installer maps it onto the manifest's `workflows_dir`.
_WORKFLOW_PREFIX = "workflows/"


def _target(project: Path, backend: BackendManifest, rel: str) -> Path | None:
    """Where one package path lands, or None when this backend has no home for it."""
    if rel.startswith(_WORKFLOW_PREFIX):
        if backend.workflows_dir is None:
            return None
        return project.joinpath(backend.workflows_dir, rel[len(_WORKFLOW_PREFIX) :])
    return project.joinpath(backend.skill_dir, rel)


def _relative(project: Path, path: Path) -> str:
    return path.relative_to(project).as_posix()


def _purge(directory: Path) -> None:
    """Remove a directory and everything under it, tolerating its absence."""
    if not directory.exists():
        return
    for child in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if child.is_dir():
            child.rmdir()
        else:
            child.unlink()
    directory.rmdir()


def _write(path: Path, data: bytes, *, executable: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if executable:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def router_block(backend: BackendManifest) -> str:
    """The `pkc:start … pkc:end` block: a router, not a rulebook (§7).

    It says three things and a fourth the acceptance run put there: what this directory is,
    that the reader is its Steward, where the skill is — spelled as a path under the working
    directory, because a harness that resolves a skill name against a global cache can be
    holding another library's copy of it — and what a session here needs in order for `pkc`
    to reach the library at all. That last one is a router's business precisely because a
    session that cannot run `pkc` never gets as far as reading the skill.
    """
    from pneuma_knowledge_core.prompts import prompt

    body = prompt(
        "steward.router.block",
        skill=f"{backend.skill_dir}/SKILL.md",
        session=backend.owner_session_command,
        once=backend.owner_exec_command,
    ).strip("\n")
    return f"{BLOCK_START}\n{body}\n{BLOCK_END}"


def splice_block(existing: str, block: str) -> str:
    """`existing` with exactly one `block` in it, and every other byte untouched.

    Strip first, then append: a file with two blocks (a hand-merged one, an older install)
    converges on one, and a file with none gains one at the end where an appended section
    belongs. The Owner's own prose is never between the markers, so it is never read here.
    """
    text = existing
    while True:
        start = text.find(BLOCK_START)
        if start < 0:
            break
        end = text.find(BLOCK_END, start)
        if end < 0:
            text = text[:start]
            break
        after = end + len(BLOCK_END)
        # Take the newline that terminated the block with it, so removing and re-appending a
        # block does not accumulate blank lines across installs.
        if text[after : after + 1] == "\n":
            after += 1
        text = text[:start] + text[after:]
    text = text.rstrip("\n")
    return f"{text}\n\n{block}\n" if text else f"{block}\n"


def strip_block(existing: str) -> str:
    """`existing` with no `pkc` block at all — what an uninstall would leave."""
    return splice_block(existing, "").replace("\n\n\n", "\n\n").rstrip("\n") + "\n"


def install_skill_package(
    project_dir: str | Path,
    backend: BackendManifest,
    package: SkillPackage,
    framework_version: str,
    *,
    rendered_at: datetime | None = None,
) -> list[str]:
    """Write the package into `project_dir`. Returns the project-relative paths written.

    `rendered_at` is injectable for the same reason every other timestamp in this codebase is:
    a test that asserts idempotence must be able to render the same install twice. It is
    excluded from the hash by construction — the hash is over the package's files, and this
    is not one of them.
    """
    project = Path(project_dir).expanduser().resolve()
    written: list[str] = []

    _purge(project / backend.skill_dir)
    for rel in sorted(package.files):
        target = _target(project, backend, rel)
        if target is None:
            continue
        _write(target, package.files[rel], executable=rel in package.executable)
        written.append(_relative(project, target))

    version_path = project / backend.skills_dir / VERSION_FILE
    stamp = (rendered_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    version_path.parent.mkdir(parents=True, exist_ok=True)
    version_path.write_text(
        json.dumps(
            {
                "framework_version": framework_version,
                "sha256": package.sha256,
                "backend": backend.name,
                "language": package.language,
                "rendered_at": stamp.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    written.append(_relative(project, version_path))

    instructions = project / backend.instructions_file
    existing = instructions.read_text(encoding="utf-8") if instructions.exists() else ""
    spliced = splice_block(existing, router_block(backend))
    if spliced != existing:
        instructions.parent.mkdir(parents=True, exist_ok=True)
        instructions.write_text(spliced, encoding="utf-8")
    written.append(_relative(project, instructions))
    return written


def verify_skill_package(
    project_dir: str | Path, backend: BackendManifest, expected: SkillPackage
) -> list[str]:
    """Every project-relative path where the install and a fresh rendering disagree.

    Missing, changed, and extra all count, and so does the router block: a skill whose files
    are current but whose instructions file no longer points at it is not installed, it is
    merely present. Sorted, so a caller prints a stable list.
    """
    project = Path(project_dir).expanduser().resolve()
    drift: set[str] = set()

    expected_paths: dict[Path, bytes] = {}
    for rel, data in expected.files.items():
        target = _target(project, backend, rel)
        if target is None:
            continue
        expected_paths[target] = data
        if not target.is_file() or target.read_bytes() != data:
            drift.add(_relative(project, target))

    skill_root = project / backend.skill_dir
    if skill_root.is_dir():
        for path in skill_root.rglob("*"):
            if path.is_file() and path not in expected_paths:
                drift.add(_relative(project, path))
    elif not expected_paths:
        drift.add(backend.skill_dir)

    version_path = project / backend.skills_dir / VERSION_FILE
    recorded = ""
    if version_path.is_file():
        try:
            recorded = str(json.loads(version_path.read_text(encoding="utf-8")).get("sha256"))
        except (OSError, ValueError):
            recorded = ""
    if recorded != expected.sha256:
        drift.add(_relative(project, version_path))

    instructions = project / backend.instructions_file
    existing = instructions.read_text(encoding="utf-8") if instructions.is_file() else ""
    if router_block(backend) not in existing:
        drift.add(backend.instructions_file)

    return sorted(drift)


def installed_hash(project_dir: str | Path, backend: BackendManifest) -> str:
    """The sha256 the install recorded, or "" — what the shim exports, read from Python."""
    path = Path(project_dir).expanduser().resolve() / backend.skills_dir / VERSION_FILE
    if not path.is_file():
        return ""
    try:
        return str(json.loads(path.read_text(encoding="utf-8")).get("sha256") or "")
    except (OSError, ValueError):
        return ""


#: The environment variable the shim exports and `pkc draft finish` stamps into the trailer.
SKILL_HASH_ENV = "PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH"


def steward_skill_hash(environ: "os._Environ[str] | dict[str, str] | None" = None) -> str:
    """The hash this process was started with, or "" — one reader for one variable."""
    env = os.environ if environ is None else environ
    return str(env.get(SKILL_HASH_ENV, "") or "").strip()
