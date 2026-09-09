import shutil
import stat
from pathlib import Path

import pytest

from pkc_personal import cli, infra, setup, skill_install
from pkc_personal.home import asset_path, atomic_write, yaml_text
from pkc_personal.library import Library
from pneuma_knowledge_service.coding_agent.backends import BLOCK_START
from pneuma_knowledge_service.coding_agent.install import SkillWriteRefused


def test_global_skill_assets_shim_and_install(home):
    shim = asset_path("skill/scripts/pkc")
    assert shim.read_text() == '#!/bin/sh\nexec pkchome exec -- pkc "$@"\n'
    for language in ("en", "zh"):
        text = asset_path(f"skill/SKILL.{language}.md").read_text()
        for phrase in ("pkchome status", "pkchome setup --answers", "--provenance inferred", "pkchome library show"):
            assert phrase in text
    files = skill_install.install(home, "codex")
    installed = Path.home() / ".codex" / "skills" / "pkc-steward"
    assert files == [installed / "SKILL.md"]
    assert BLOCK_START in files[0].read_text()
    assert (installed / "scripts" / "pkc").read_bytes() == shim.read_bytes()
    assert stat.S_IMODE((installed / "scripts" / "pkc").stat().st_mode) & stat.S_IXUSR
    converter = installed / "scripts" / "agent_sessions.py"
    assert converter.read_bytes() == asset_path("skill/scripts/agent_sessions.py").read_bytes()
    assert stat.S_IMODE(converter.stat().st_mode) & stat.S_IXUSR
    assert not (Path.home() / "AGENTS.md").exists()
    skill_install.install(home, "codex")
    atomic_write(installed / "SKILL.md", "Owner's custom text\n")
    with pytest.raises(SkillWriteRefused, match="--force"):
        skill_install.install(home, "codex")
    assert (installed / "SKILL.md").read_text() == "Owner's custom text\n"
    skill_install.install(home, "codex", force=True)
    assert BLOCK_START in (installed / "SKILL.md").read_text()


def test_refresh_re_renders_our_own_package_and_still_refuses_a_stranger(home):
    installed = Path.home() / ".codex" / "skills" / "pkc-steward"
    # What the installer leaves behind: our files, and our marker beside them.
    skill_install.install(home, "codex")
    assert skill_install.is_ours(installed)
    atomic_write(installed / "SKILL.md", "Owner's edit of our own package\n")
    with pytest.raises(SkillWriteRefused, match="--force"):
        skill_install.install(home, "codex")
    skill_install.install(home, "codex", refresh=True)
    assert BLOCK_START in (installed / "SKILL.md").read_text()
    # A directory with no marker of ours is somebody's work; refresh is not permission.
    for path in sorted(installed.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        path.unlink() if path.is_file() else path.rmdir()
    atomic_write(installed / "SKILL.md", "Somebody else's pkc-steward\n")
    assert not skill_install.is_ours(installed)
    with pytest.raises(SkillWriteRefused, match="--force"):
        skill_install.install(home, "codex", refresh=True)
    assert (installed / "SKILL.md").read_text() == "Somebody else's pkc-steward\n"


def test_skill_autodetect_does_not_create_unselected_harness(home):
    (Path.home() / ".claude").mkdir(parents=True)
    files = skill_install.install(home)
    assert files == [Path.home() / ".claude" / "skills" / "pkc-steward" / "SKILL.md"]
    assert not (Path.home() / ".codex").exists()


def test_setup_answers_and_owned_steps(home, monkeypatch, tmp_path, capsys):
    operations = []
    def up(_home):
        operations.append("up")
        from pkc_personal.library import libraries
        for library in libraries(_home):
            library.record_step("infra")
    monkeypatch.setattr(infra, "up", up)
    monkeypatch.setattr(skill_install, "install", lambda *_, **kw: operations.append(
        f"skill(refresh={kw.get('refresh', False)})"))
    monkeypatch.setattr(setup, "persist_owner_profile",
                        lambda *_, **__: operations.append("profile") or True)
    monkeypatch.setattr(setup, "render_library", lambda *_: operations.append("render"))
    monkeypatch.setattr(setup.engine, "start", lambda *_: operations.append("engine"))
    answers = tmp_path / "answers.yaml"
    atomic_write(answers, yaml_text({"library": "notes", "language": "zh", "backend": "claude-code",
                                    "semantic_retrieval": False, "embedding_key": "synthetic-key",
                                    "watch": [str(tmp_path)]}))
    setup.setup(home, answers)
    # The order §3.1 names, and the engine last: nothing above it can stop it from starting.
    # No "render": creating the library rendered its package, so the repair step is a no-op.
    assert operations == ["up", "profile", "skill(refresh=True)", "engine"]
    library = Library.load(home, "notes")
    assert library.state.choices.language == "zh" and library.state.choices.backend == "claude-code"
    assert library.state.steps.infra and library.state.steps.credentials
    assert [watch.path for watch in library.state.watch] == [str(tmp_path)]
    # Setup owns three steps and no more: the two derived ones are not writable state.
    assert set(library.state.steps.model_dump()) == {"infra", "credentials", "skill"}
    assert "profile" not in (library.path / "library.yaml").read_text(encoding="utf-8")
    assert home.current == "notes"
    assert "synthetic-key" not in (home.path / "config.yaml").read_text()
    assert "synthetic-key" not in (library.path / "library.yaml").read_text()
    output = capsys.readouterr().out
    assert "--provenance inferred" in output and "synthetic-key" not in output
    assert "library notes (created)" in output and "engine on port" in output
    # A second setup on the same home completes nothing new: same list, same library, no
    # second creation, and the engine start that a mid-list refusal used to skip.
    operations.clear()
    setup.setup(home, answers, no_skill=True)
    assert operations == ["up", "profile", "engine"]
    assert "library notes (already present)" in capsys.readouterr().out
    assert Library.load(home, "notes").state.created == library.state.created
    # A setup interrupted before its package was written repairs it on the next run.
    shutil.rmtree(library.skill_dir)
    operations.clear()
    setup.setup(home, answers, no_skill=True)
    assert operations == ["up", "profile", "render", "engine"]


def test_noninteractive_setup_requires_answers(home, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["setup"]) == 2
    assert "--answers" in capsys.readouterr().err


def test_cli_config_and_console(home, make_library, monkeypatch, capsys):
    library = make_library()
    assert cli.main(["config", "set", "semantic_retrieval", "on", "--library", "notes"]) == 0
    assert cli.main(["config", "get", "semantic_retrieval", "--library", "notes"]) == 0
    assert capsys.readouterr().out == "on\n"
    urls = []
    monkeypatch.setattr(cli.webbrowser, "open", urls.append)
    assert cli.main(["console", "--library", "notes"]) == 0
    assert urls == [f"http://127.0.0.1:{library.state.engine.port}"]
