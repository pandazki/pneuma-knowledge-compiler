"""The installer, run for real under a temporary HOME: only Docker is faked.

`uv` is the real one and the package is installed from this checkout (`PKC_SOURCE`), so
what these tests exercise is what the one sentence in the README triggers on a machine.
"""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "personal" / "install.sh"
LAUNCHER_TEXT = '#!/bin/sh\nexec pkchome exec -- pkc "$@"\n'
NEXT_BLOCK = (
    "== next (for the agent) ==\n"
    "skill installed: ~/.codex/skills/pkc-steward/SKILL.md\n"
    "run: pkchome status\n"
    'then: pkchome setup --answers <file>   # see the skill\'s "Cold start" section\n'
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH"),
]


@pytest.fixture
def machine(tmp_path):
    """A temporary HOME with a Codex harness present and a fake `docker` on PATH."""
    owner = tmp_path / "owner"
    (owner / ".codex").mkdir(parents=True)
    # The console step must not depend on the network (or on whether this checkout happens
    # to carry a built dist): PKC_CONSOLE_DIST is the developer path, and it answers offline.
    console = tmp_path / "console-dist"
    console.mkdir()
    (console / "index.html").write_text("<!doctype html>\n")
    tools = owner / "fake-bin"
    tools.mkdir()
    real_home = Path(os.path.expanduser("~"))

    def docker(exit_code: int) -> None:
        fake = tools / "docker"
        fake.write_text(f"#!/bin/sh\nexit {exit_code}\n")
        fake.chmod(0o755)

    docker(0)

    def run(*arguments: str, expected: int = 0) -> subprocess.CompletedProcess:
        environment = {
            "HOME": str(owner),
            "PATH": os.pathsep.join([str(tools), str(Path(shutil.which("uv")).parent), "/usr/bin", "/bin"]),
            "PKC_SOURCE": str(ROOT / "personal"),
            "PKC_CONSOLE_DIST": str(console),
            # The real cache keeps a warm install warm; nothing else escapes the temporary HOME.
            "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(real_home / ".cache" / "uv")),
        }
        completed = subprocess.run(["sh", str(INSTALLER), *arguments], env=environment,
                                   capture_output=True, text=True, timeout=900)
        assert completed.returncode == expected, completed.stdout + completed.stderr
        return completed

    run.home = owner
    run.docker = docker
    return run


def _steps(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line and not line.startswith("== next")
            and not line.startswith(("skill installed:", "run:", "then:"))]


def test_the_installer_installs_the_edition_the_launcher_and_the_skill(machine):
    home = machine.home
    first = machine()

    # uv put pkchome in the temporary HOME, and the launcher sits beside it.
    launcher = home / ".local" / "bin" / "pkc"
    assert (home / ".local" / "bin" / "pkchome").is_file()
    assert launcher.read_text() == LAUNCHER_TEXT
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o755

    # The skill lands in the harness that exists, and no harness is invented.
    assert (home / ".codex" / "skills" / "pkc-steward" / "SKILL.md").is_file()
    assert not (home / ".claude").exists()

    # Every step accounts for itself, and the agent's block is the last thing on stdout.
    assert all(line.startswith(("ok:", "skip:")) for line in _steps(first.stdout)), first.stdout
    assert first.stdout.endswith(NEXT_BLOCK)
    assert "skip: no ~/.claude" in first.stdout
    assert "ok: console local build" in first.stdout


def _written(home: Path) -> dict:
    """What the installer itself writes — not uv's own console script, which uv rewrites."""
    skill = home / ".codex" / "skills" / "pkc-steward"
    written = {path: path.read_bytes() for path in skill.rglob("*")
               if path.is_file() and path.name != "skill-version.json"}
    # The stamp records when it was rendered; the hash is what says it is the same package.
    version = json.loads((skill / "skill-version.json").read_text(encoding="utf-8"))
    written["skill"] = {key: value for key, value in version.items() if key != "rendered_at"}
    written[home / ".local" / "bin" / "pkc"] = (home / ".local" / "bin" / "pkc").read_bytes()
    written["bin"] = sorted(path.name for path in (home / ".local" / "bin").iterdir())
    return written


def test_a_second_run_changes_nothing_and_says_so(machine):
    home = machine.home
    machine()
    before = _written(home)

    second = machine()
    assert _written(home) == before
    assert (home / ".local" / "bin" / "pkchome").is_file()
    assert all(line.startswith(("ok:", "skip:")) for line in _steps(second.stdout)), second.stdout
    assert "skip: pkc launcher already at ~/.local/bin/pkc" in second.stdout
    assert second.stdout.endswith(NEXT_BLOCK)

    # --quiet leaves the agent's block and nothing else.
    assert machine("--quiet").stdout == NEXT_BLOCK


def test_an_unreachable_docker_stops_with_exit_3_after_the_skill_is_installed(machine):
    machine()
    skill = machine.home / ".codex" / "skills" / "pkc-steward"
    shutil.rmtree(skill)

    machine.docker(1)
    failed = machine(expected=3)

    # The skill step ran before the probe, and what it wrote stays written.
    assert (skill / "SKILL.md").is_file()
    assert "docker" in failed.stderr and "OrbStack" in failed.stderr
    assert "== next" not in failed.stdout


def test_a_pkc_that_is_not_ours_is_refused_rather_than_replaced(machine):
    machine()
    launcher = machine.home / ".local" / "bin" / "pkc"
    launcher.write_text("#!/bin/sh\necho somebody else's command\n")

    refused = machine(expected=1)

    assert launcher.read_text() == "#!/bin/sh\necho somebody else's command\n"
    assert "refused" in refused.stderr
