import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from pneuma_knowledge_service.coding_agent.backends import BLOCK_END, BLOCK_START, backend as backend_manifest
from pneuma_knowledge_service.coding_agent.round_runner import AgentRoundRunner
from pneuma_knowledge_service.engine.contract import load_engine_contract
from pneuma_knowledge_service.settings import get_settings

from pkc_personal import cli, library as library_module
from pkc_personal.environment import LibraryNotChosen, home_environment, resolve_library
from pkc_personal.home import atomic_write, read_yaml
from pkc_personal.library import Library, bind_library, create_library, render_library, set_config, unbind_library, use_library


def test_resolution_order_and_ancestor_binding(home, make_library, tmp_path):
    for name in ("explicit", "environment", "bound", "current"):
        make_library(name)
    directory = tmp_path / "work" / "child"
    directory.mkdir(parents=True)
    bind_library(home, "bound", directory.parent)
    use_library(home, "current")
    assert resolve_library(home, "explicit", {"PKC_LIBRARY": "environment"}, directory).state.name == "explicit"
    assert resolve_library(home, None, {"PKC_LIBRARY": "environment"}, directory).state.name == "environment"
    assert resolve_library(home, None, {}, directory).state.name == "bound"
    unbind_library(home, directory.parent)
    assert resolve_library(home, None, {}, directory).state.name == "current"
    assert Library.load(home, "bound").state.bindings == []
    with pytest.raises(LibraryNotChosen, match="does not exist"):
        resolve_library(home, "missing", {}, directory)
    (home.path / "current").unlink()
    with pytest.raises(LibraryNotChosen) as refusal:
        resolve_library(home, None, {}, directory)
    for text in ("Libraries:", "explicit", "--library", "PKC_LIBRARY", "pkchome library use"):
        assert text in str(refusal.value)


def test_exec_refusal_and_venv_resolution(home, make_library, monkeypatch, tmp_path, capsys):
    library = make_library()
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(os, "execvpe", lambda *args: calls.append(args))
    assert cli.main(["exec", "--", "pkc", "jobs"]) == 2
    assert not calls
    assert "notes" in capsys.readouterr().err
    atomic_write(library.skill_dir.parent / "skill-version.json", json.dumps({"sha256": "synthetic-hash"}))
    # `pkc` runs in THIS process (no second interpreter), under the library's environment,
    # from the library directory; anything else is exec'd.
    seen = {}
    import pneuma_knowledge_service.cli as pkc_cli
    monkeypatch.setattr(pkc_cli, "main", lambda argv: seen.update(argv=argv, env=dict(os.environ), cwd=os.getcwd()) or 0)
    with pytest.raises(SystemExit) as stop:
        cli.main(["exec", "--library", "notes", "--", "pkc", "jobs"])
    assert stop.value.code == 0 and not calls
    assert seen["argv"] == ["jobs"] and seen["cwd"] == str(library.path)
    assert seen["env"]["PNEUMA_KNOWLEDGE_TENANT"] == "lib-notes"
    assert seen["env"]["PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH"] == "synthetic-hash"
    assert seen["env"]["PKC_STEWARD_SESSION"]
    assert Library.load(home, "notes").state.last_used is not None
    assert cli.main(["exec", "--library", "notes", "--", "echo", "hello"]) == 0
    assert calls[-1][0] == "echo"


@pytest.mark.parametrize("name", ["Notes", "../bad", "", "a" * 33, "two_words", "with space"])
def test_invalid_library_name_does_not_write(home, name):
    with pytest.raises(ValueError):
        create_library(home, name)
    assert list((home.path / "libraries").iterdir()) == []


def test_create_model_specs_contract_git_and_inheritance(home, make_library):
    source = make_library()
    profile = source.engine_dir / "persona" / "profile.yaml"
    atomic_write(profile, profile.read_text().replace('"Owner"', '"Synthetic Owner"'))
    atomic_write(source.engine_dir / "prompts" / "custom.yaml", "custom: clause\n")
    atomic_write(source.canonical_dir / "owner-work.md", "Synthetic owner work\n")
    copied = make_library("second", from_library="notes", backend="claude-code", language="zh")
    assert copied.state.tenant == "lib-second"
    assert "Synthetic Owner" not in (copied.engine_dir / "persona" / "profile.yaml").read_text()
    assert not (copied.canonical_dir / "owner-work.md").exists()
    assert (copied.engine_dir / "prompts" / "custom.yaml").read_text() == "custom: clause\n"
    assert (copied.engine_dir / "compile" / "contract.md").read_bytes() == (source.engine_dir / "compile" / "contract.md").read_bytes()
    assert load_engine_contract(copied.engine_dir) is not None
    assert read_yaml(copied.engine_dir / "engine.yaml")["compile"] == "agent:claude-code"
    assert read_yaml(copied.engine_dir / "prompts" / "overlays.yaml")["language"] == "zh"
    assert read_yaml(source.engine_dir / "engine.yaml")["embedding"] == home.config.defaults.embedding
    assert (copied.canonical_dir / ".git" / "HEAD").is_file()
    assert subprocess.run(["git", "-C", str(copied.engine_dir), "status", "--porcelain"], capture_output=True, text=True).stdout == ""
    assert not list(copied.canonical_dir.glob("*.md"))
    with pytest.raises(ValueError, match="already exists"):
        make_library("second")


def test_engine_settings_layer_and_stranger_dotenv(home, make_library, monkeypatch, tmp_path):
    library = make_library()
    atomic_write(tmp_path / ".env", "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE=stranger:model\n")
    monkeypatch.chdir(tmp_path)
    for key, value in home_environment(home, library).items():
        monkeypatch.setenv(key, value)
    settings = get_settings()
    assert settings.llm_model_compile == "agent:codex"
    assert settings.embedding_model == home.config.defaults.embedding
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE", "scripted:explicit")
    assert get_settings().llm_model_compile == "scripted:explicit"


def test_render_installs_into_the_library_directory_and_owns_the_step(home, make_library, monkeypatch):
    library = make_library()
    assert library.state.steps.skill is None
    calls = []
    def install(command, **kwargs):
        calls.append((command, kwargs))
        project = Path(command[command.index("--project") + 1])
        atomic_write(project / ".agents" / "skills" / "pkc-steward" / "SKILL.md", "installed\n")
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(library_module.subprocess, "run", install)
    render_library(home, library)
    command, options = calls[0]
    # An install into the library directory, not a render into a directory of our own naming.
    assert command[1:3] == ["skill", "install"]
    assert command[command.index("--project") + 1] == str(library.path)
    assert "--out" not in command
    assert options["env"]["PNEUMA_KNOWLEDGE_TENANT"] == "lib-notes"
    assert options["env"]["PNEUMA_KNOWLEDGE_PROJECT_DIR"] == str(library.path)
    assert library.skill_dir == library.path / ".agents" / "skills" / "pkc-steward"
    assert (library.skill_dir / "SKILL.md").read_text() == "installed\n"
    assert Library.load(home, "notes").state.steps.skill is not None
    monkeypatch.setattr(library_module.subprocess, "run",
                        lambda *_, **__: SimpleNamespace(returncode=4, stderr="refused"))
    with pytest.raises(RuntimeError, match="skill install failed"):
        render_library(home, library)


def test_a_backend_change_installs_into_the_new_harness_and_removes_the_old(home, make_library, monkeypatch):
    library = make_library()
    # `make_library` silences rendering for creation; `set_config` must reach the real one.
    monkeypatch.setattr(library_module, "render_library", render_library)
    def install(command, **kwargs):
        manifest = backend_manifest(command[command.index("--backend") + 1])
        project = Path(command[command.index("--project") + 1])
        atomic_write(project / manifest.skill_dir / "SKILL.md", "installed\n")
        atomic_write(project / manifest.skills_dir / "skill-version.json", "{}\n")
        atomic_write(project / manifest.instructions_file,
                     f"Owner's own prose\n\n{BLOCK_START}\nrouter\n{BLOCK_END}\n")
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(library_module.subprocess, "run", install)
    render_library(home, library)
    codex = backend_manifest("codex")
    assert (library.path / codex.skill_dir / "SKILL.md").is_file()
    set_config(home, "backend", "claude-code", library)
    library = Library.load(home, "notes")
    assert (library.skill_dir / "SKILL.md").is_file()
    assert library.skill_dir == library.path / ".claude" / "skills" / "pkc-steward"
    # The harness that is no longer chosen keeps neither its package nor its router block.
    assert not (library.path / codex.skills_dir).exists()
    assert BLOCK_START not in (library.path / codex.instructions_file).read_text()
    assert "Owner's own prose" in (library.path / codex.instructions_file).read_text()


def test_config_updates_engine_and_refreshes_language_backend(home, make_library, monkeypatch):
    library = make_library()
    calls = []
    monkeypatch.setattr(library_module, "render_library", lambda *args: calls.append(args))
    set_config(home, "backend", "api", library)
    assert read_yaml(library.engine_dir / "engine.yaml")["compile"].startswith("openrouter:")
    set_config(home, "language", "zh", library)
    assert read_yaml(library.engine_dir / "prompts" / "overlays.yaml")["language"] == "zh"
    assert len(calls) == 2
    set_config(home, "semantic_retrieval", "on", library)
    set_config(home, "embedding", "fake:384", library)
    assert read_yaml(library.engine_dir / "engine.yaml")["embedding"] == "fake:384"
    assert Library.load(home, "notes").state.choices.semantic_retrieval is True
    assert len(calls) == 2
    set_config(home, "language", "zh")
    assert home.config.defaults.language == "zh"


def test_the_worker_posture_is_a_recorded_choice_the_environment_states(home, make_library):
    library = make_library()
    # Today's behaviour is the default, so a library created before the knob reads the same.
    assert library.state.choices.unattended is True
    assert home_environment(home, library)["PNEUMA_KNOWLEDGE_AGENT_UNATTENDED"] == "true"
    note = set_config(home, "unattended", "off", library)
    # Nothing was running, so the command says where the choice will take effect.
    assert note and "not running" in note and "attended" in note
    reloaded = Library.load(home, "notes")
    assert reloaded.state.choices.unattended is False
    assert home_environment(home, reloaded)["PNEUMA_KNOWLEDGE_AGENT_UNATTENDED"] == "false"
    # It is not an engine knob: the engine directory states models and wording, not posture.
    assert "unattended" not in read_yaml(library.engine_dir / "engine.yaml")
    set_config(home, "unattended", "off")
    assert home.config.defaults.unattended is False
    with pytest.raises(ValueError, match="unattended must be on or off"):
        set_config(home, "unattended", "sometimes", reloaded)
    assert Library.load(home, "notes").state.choices.unattended is False


def test_custom_contract_rejected_before_publication(home, make_library, tmp_path):
    contract = tmp_path / "contract.md"
    atomic_write(contract, "No frontmatter")
    with pytest.raises(ValueError, match="contract needs"):
        make_library(contract=contract)
    assert not (home.path / "libraries" / "notes").exists()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_library_create_defaults_to_projects_and_selects_knowledge(home, make_library, language):
    default = make_library(language=language)
    assert load_engine_contract(default.engine_dir).skill_id == "personal-projects"
    alternative = make_library("second", contract="personal-knowledge", language=language)
    assert load_engine_contract(alternative.engine_dir).skill_id == "personal-knowledge"
    explicit = make_library("third", contract="personal-projects", from_library="second", language=language)
    assert load_engine_contract(explicit.engine_dir).skill_id == "personal-projects"


def test_library_create_cli_default_and_named_alternative(home, make_library, capsys):
    assert cli.main(["library", "create", "notes"]) == 0
    assert load_engine_contract(Library.load(home, "notes").engine_dir).skill_id == "personal-projects"
    assert cli.main(["library", "create", "second", "--contract", "personal-knowledge"]) == 0
    assert load_engine_contract(Library.load(home, "second").engine_dir).skill_id == "personal-knowledge"


def test_real_keyless_install_and_verify(home):
    from pkc_personal.status import skill_fresh

    library = create_library(home, "notes")
    assert (library.skill_dir / "references" / "contract.md").is_file()
    # The library directory is the project: the router block lands in its instructions file.
    assert BLOCK_START in (library.path / library.manifest.instructions_file).read_text()
    assert Library.load(home, "notes").state.steps.skill is not None
    assert skill_fresh(home, library) is True
    contract = library.engine_dir / "compile" / "contract.md"
    atomic_write(contract, contract.read_text() + "\nSynthetic additional domain instruction.\n")
    assert skill_fresh(home, library) is False
    render_library(home, library)
    assert skill_fresh(home, library) is True


def test_the_installed_shim_is_the_path_the_unattended_round_runs(home):
    """`library show`'s `entry` is what `AgentRoundRunner._shim()` computes, or the round no-ops.

    The worker hands the round `os.getcwd()` as its project (`compile_worker`), and the
    engine process is started with `cwd=library.path` (`pkc_personal.engine.start`) — so the
    project for this library is the library directory, and the runner's own expression is
    asked here rather than restated.
    """
    library = create_library(home, "notes")
    runner = AgentRoundRunner(manifest=library.manifest, project_dir=str(library.path),
                              timeout_s=1.0)
    entry = library.show()["entry"]
    assert entry == runner._shim()
    assert Path(entry).is_file() and os.access(entry, os.X_OK)
    assert library.show()["skill_dir"] == str(library.skill_dir)
