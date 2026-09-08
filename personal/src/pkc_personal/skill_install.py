"""Install the application's global router skill into the Owner's harnesses."""

from __future__ import annotations

import tempfile
from pathlib import Path

from pneuma_knowledge_service.coding_agent.backends import BLOCK_END, BLOCK_START, backend as manifest
from pneuma_knowledge_service.coding_agent.install import (
    VERSION_FILE, SkillWriteRefused, splice_block, write_skill_package,
)
from pneuma_knowledge_service.coding_agent.skillpack import SkillPackage

from pkc_personal import __version__
from pkc_personal.home import Home, asset_path, replace_directory


def global_skill_dir(backend: str) -> Path:
    harness = ".claude" if backend == "claude-code" else ".codex"
    return Path.home() / harness / "skills" / "pkc-steward"


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
        name for name, folder in (("codex", ".codex"), ("claude-code", ".claude"))
        if (Path.home() / folder).is_dir()
    ]
    language = home.config.defaults.language if home.configured else "en"
    text = asset_path(f"skill/SKILL.{language}.md").read_text(encoding="utf-8")
    text = splice_block(text, f"{BLOCK_START}\nManaged by pkchome skill install.\n{BLOCK_END}")
    files = {"SKILL.md": text.encode(), **{
        f"scripts/{name}": asset_path(f"skill/scripts/{name}").read_bytes()
        for name in ("pkc", "agent_sessions.py")
    }}
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
