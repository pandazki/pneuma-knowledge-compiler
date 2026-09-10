"""Install the application's global router skill into the Owner's harnesses."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from pneuma_knowledge_service.coding_agent.backends import (
    BACKENDS, BLOCK_END, BLOCK_START, SKILL_NAME, backend as manifest,
)
from pneuma_knowledge_service.coding_agent.install import (
    VERSION_FILE, SkillWriteRefused, splice_block, write_skill_package,
)
from pneuma_knowledge_service.coding_agent.skillpack import SkillPackage

from pkc_personal import __version__
from pkc_personal.home import Home, asset_path, replace_directory


def config_home(backend: str) -> Path:
    """The harness's own config home — `$CODEX_HOME` / `$CLAUDE_CONFIG_DIR`, else its default."""
    harness = manifest(backend)
    return Path(os.environ.get(harness.config_home_env, "").strip()
                or harness.default_config_home).expanduser()


def global_skill_dir(backend: str) -> Path:
    """`<config home>/skills/pkc-steward`, the harness's own user-level skill directory.

    Deliberately the config home and never `~/.agents/skills`: an unattended round runs under
    a per-job config home, so a copy here is one the round cannot see, while Codex reads
    `~/.agents/skills` from HOME whatever `CODEX_HOME` says. (Where a harness directory is a
    symlink into such a shared root, the round's launcher switches the copy off by path —
    `launcher.foreign_skill_copies` — so the round still sees only its library's package.)
    """
    return config_home(backend) / "skills" / SKILL_NAME


#: The line the global render carries inside its managed block, and nothing else does: a
#: library's own package is rendered from the deployment, with its version file one level up.
MANAGED_NOTE = "Managed by pkchome skill install."


def is_global_render(target: Path) -> bool:
    """Is this directory a GLOBAL render of this edition — marker and managed note both?"""
    if not is_ours(target) or not (target / "SKILL.md").is_file():
        return False
    return MANAGED_NOTE in (target / "SKILL.md").read_text(encoding="utf-8", errors="replace")


def remove_stale_global_copies() -> list[Path]:
    """Remove a global render of ours left in a skill root an unattended round reads from HOME.

    `~/.agents/skills` is read by Codex whatever `CODEX_HOME` says, so a copy of the router
    there sits beside every round's own package. Whatever shape the root has — a directory, a
    symlink to anywhere, missing, dangling — only a `pkc-steward` carrying this edition's global
    marker is removed, and never one that IS a harness's live global install reached through a
    shared directory (that one the round's launcher switches off instead). A `pkc-steward` that
    is itself a symlink loses the link, not what it points at.
    """
    live = {global_skill_dir(name).resolve() for name in BACKENDS}
    removed: list[Path] = []
    for root in dict.fromkeys(root for harness in BACKENDS.values() for root in harness.home_skill_roots):
        candidate = Path(root).expanduser() / SKILL_NAME
        if not candidate.is_dir() or candidate.resolve() in live or not is_global_render(candidate):
            continue
        if candidate.is_symlink():
            candidate.unlink()
        else:
            shutil.rmtree(candidate)
        removed.append(candidate)
    return removed


def tilde(path: Path) -> str:
    home = str(Path.home())
    return "~" + str(path)[len(home):] if str(path).startswith(home + os.sep) else str(path)


def is_ours(target: Path) -> bool:
    """Did this directory come from a rendering of ours, or is it somebody else's?

    `skill-version.json` is written by `write_skill_package` and by nothing else, so its
    presence is a mark rather than a guess. It is what lets `refresh=True` re-render an
    installation of ours without also giving it permission to delete a directory that merely
    happens to be named `pkc-steward`.
    """
    return (target / VERSION_FILE).is_file()


def install(home: Home, backend: str | None = None, *, force: bool = False,
            refresh: bool = False) -> list[Path]:
    """Write the global router skill into each harness found (or the one named).

    `force` replaces whatever is there. `refresh` is the weaker permission the cold start
    needs: re-render an installation that carries our own marker — the installer has usually
    just written one, and `pkchome setup` must not abort on the bytes it put there itself —
    while a directory with no marker of ours is still refused, because it is somebody's work.
    """
    names = ["codex", "claude-code"] if backend == "all" else [backend] if backend else [
        name for name in ("codex", "claude-code") if config_home(name).is_dir()
    ]
    language = home.config.defaults.language if home.configured else "en"
    text = asset_path(f"skill/SKILL.{language}.md").read_text(encoding="utf-8")
    text = splice_block(text, f"{BLOCK_START}\n{MANAGED_NOTE}\n{BLOCK_END}")
    files = {"SKILL.md": text.encode(), **{
        f"scripts/{name}": asset_path(f"skill/scripts/{name}").read_bytes()
        for name in ("pkc", "agent_sessions.py")
    }}
    # Stderr, because the installer reads stdout as the installed path.
    for path in remove_stale_global_copies():
        print(f"ok: removed the old global skill at {tilde(path)}", file=sys.stderr)
    written = []
    # Preflight all targets before publishing any of them.
    for name in names:
        target = global_skill_dir(name)
        if target.exists() and not target.is_dir():
            raise SkillWriteRefused(f"{target} is not a directory")
        if target.is_dir() and any(target.iterdir()) and not force and not (refresh and is_ours(target)):
            same = all((target / rel).is_file() and (target / rel).read_bytes() == body for rel, body in files.items())
            extra = {p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()} - set(files) - {VERSION_FILE}
            if not same or extra:
                raise SkillWriteRefused(f"{target} already has different files; pass --force to replace them")
    for name in names:
        target = global_skill_dir(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".pkc-steward-", dir=target.parent) as temporary:
            staged = Path(temporary) / "skill"
            package = SkillPackage(files=files, executable=frozenset({"scripts/pkc", "scripts/agent_sessions.py"}),
                                   language=language, backend=name)
            write_skill_package(staged, manifest(name), package, __version__)
            replace_directory(staged, target)
        written.append(target / "SKILL.md")
    return written
