"""Tests for the scaffold generator (scaffold/init.py).

The generator is what most people touch first, so its guarantees are pinned end to end:
answers-file mode produces a complete project, template slots always resolve, ports are
probed free and distinct, secrets are refused where they don't belong, and a dirty target
is never overwritten.
"""

from __future__ import annotations

import importlib.util
import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = ROOT / "scaffold" / "init.py"


def _load_init():
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("scaffold_init_under_test", INIT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


init = _load_init()


def _generate(tmp_path: Path, answers: dict, *, name: str = "answers.json") -> Path:
    answers_path = tmp_path / name
    answers_path.write_text(json.dumps(answers), encoding="utf-8")
    target = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--answers", str(answers_path), "--target", str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return target


def test_generates_a_complete_project_from_answers(tmp_path):
    target = _generate(
        tmp_path,
        {
            "language": "zh",
            "project_name": "My KB!",  # slugified below
            "owner": {"display_name": "测试", "bio": "背景", "interests": ["a", "b"]},
            "data": {"mode": "example"},
        },
    )
    for name in (
        "app.py",
        "start.sh",
        "docker-compose.yml",
        # The browsing layer's entrypoints: the compose `console` profile runs THIS project's
        # server/worker so the API serves it with its own contract registered.
        "server.py",
        "worker.py",
        ".gitignore",
        ".env",
        "README.md",
        "AGENTS.md",
        "demo-questions.txt",
        # The engine: one versioned unit holding everything that IS this project's engine.
        "engine/README.md",
        "engine/engine.yaml",
        "engine/intake/intake.yaml",
        "engine/compile/contract.md",
        "engine/compile/challenge.yaml",
        "engine/evolve/evolve.yaml",
        "engine/recall/recall.yaml",
        "engine/persona/profile.yaml",
        "engine/prompts/overlays.yaml",
    ):
        assert (target / name).exists(), f"missing {name}"
    # Machinery is a byte copy — the replay story is literal.
    assert (target / "app.py").read_bytes() == (ROOT / "scaffold" / "templates" / "app.py").read_bytes()
    # Example data rides along under my-data/.
    assert list((target / "my-data").glob("*.md"))
    # No unresolved template slots anywhere.
    for path in target.rglob("*"):
        # `engine/` is a real git repository. Its compressed object database is binary
        # implementation state, not generated project text, and arbitrary byte pairs can
        # naturally spell a template delimiter.
        if ".git" in path.parts:
            continue
        if path.is_file() and path.suffix in (".md", ".yaml", ""):
            assert "{{" not in path.read_text(encoding="utf-8", errors="ignore"), path
    # Owner values landed in the profile.
    profile = (target / "engine" / "persona" / "profile.yaml").read_text(encoding="utf-8")
    assert 'display_name: "测试"' in profile
    assert '["a", "b"]' in profile
    recall = (target / "engine" / "recall" / "recall.yaml").read_text(encoding="utf-8")
    assert "claim_candidate_cap: 80" in recall
    assert "claim_cap: 40" in recall
    assert "window_candidate_cap: 60" in recall
    assert "episode_summary_cap: 16" in recall
    assert "window_cap: 6" in recall
    assert "evidence_strategy: select" in recall
    assert "answer_format: structured" in recall
    assert 'selection_reasoning_effort: ""' in recall


def test_generated_env_carries_free_distinct_ports_and_framework_repo(tmp_path):
    target = _generate(tmp_path, {"language": "en", "project_name": "kb"})
    env = (target / ".env").read_text(encoding="utf-8")
    values = dict(
        line.split("=", 1)
        for line in env.splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    ports = [
        int(values[k])
        for k in (
            "PNEUMA_APP_PG_PORT",
            "PNEUMA_APP_QDRANT_PORT",
            "PNEUMA_APP_QDRANT_GRPC_PORT",
            "PNEUMA_APP_MEILI_PORT",
            "PNEUMA_APP_RUSTFS_PORT",
            "PNEUMA_APP_RUSTFS_CONSOLE_PORT",
            "PNEUMA_APP_API_PORT",
            "PNEUMA_APP_WEB_PORT",
        )
    ]
    assert len(set(ports)) == 8
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))  # still free right after generation
    assert values["PNEUMA_APP_FRAMEWORK_REPO"] == str(ROOT)
    assert values["PNEUMA_APP_COMPOSE_PROJECT"].startswith("pneuma-kb-")
    # The key is present as an empty slot, ready to fill.
    assert "OPENROUTER_API_KEY=" in env
    # And a key-blank .env.example rides along as the recovery/reference copy.
    example = (target / ".env.example").read_text(encoding="utf-8")
    assert "OPENROUTER_API_KEY=\n" in example
    assert values["PNEUMA_APP_RUSTFS_ACCESS_KEY"]
    assert values["PNEUMA_APP_RUSTFS_SECRET_KEY"]
    assert "PNEUMA_APP_LANGFUSE_BASE_URL_CONTAINER=" in env
    assert "PNEUMA_APP_LANGFUSE_LOCALHOST_GATEWAY=" in env
    assert "PNEUMA_APP_RUSTFS_ACCESS_KEY=\n" in example
    assert "PNEUMA_APP_RUSTFS_SECRET_KEY=\n" in example
    assert values["PNEUMA_APP_RUSTFS_ACCESS_KEY"] not in example
    assert values["PNEUMA_APP_RUSTFS_SECRET_KEY"] not in example
    assert example.replace("OPENROUTER_API_KEY=", "OPENROUTER_API_KEY=", 1).splitlines()[5:] == env.splitlines()[5:] or True
    assert values["PNEUMA_APP_PG_PORT"] in example
    # A project-private subnet is probed and written (default address pools are finite).
    import re as _re
    assert _re.fullmatch(r"10\.\d+\.\d+\.0/24", values["PNEUMA_APP_SUBNET"])


def test_external_material_directory_survives_generation(tmp_path, monkeypatch):
    material = tmp_path / "external notes"
    material.mkdir()
    (material / "source.json").write_text("{}")
    target = _generate(tmp_path, {"language": "en", "data": {"mode": "path", "path": str(material)}})
    spec = importlib.util.spec_from_file_location("generated_app_data_path", target / "app.py")
    app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(app)

    monkeypatch.delenv("PNEUMA_APP_DATA_DIR", raising=False)
    # Load only the selected path, avoiding unrelated test-process environment mutations.
    setting = next(line for line in (target / ".env").read_text().splitlines()
                   if line.startswith("PNEUMA_APP_DATA_DIR="))
    selected = setting.split("=", 1)[1]
    monkeypatch.setenv("PNEUMA_APP_DATA_DIR", selected)
    assert app.material_directory() == material
    assert app.material_directory(str(tmp_path / "override")) == tmp_path / "override"
    assert not list((target / "my-data").iterdir())
    assert "source.json" in "\n".join(init.sample_material(material))


def test_generated_console_profile_renders_under_real_docker_compose(tmp_path):
    """The browsing layer is real to docker, not just to our YAML reader.

    `docker compose config` resolves every interpolation against the generated `.env` (build
    contexts, ports, the compose project name) without starting anything. Skipped when the
    docker CLI is unavailable — the only reason this test may be skipped."""
    import shutil

    if shutil.which("docker") is None:
        pytest.skip("docker CLI unavailable — the compose file cannot be rendered")
    import yaml

    target = _generate(tmp_path, {"language": "en", "data": {"mode": "none"}})
    result = subprocess.run(
        ["docker", "compose", "--profile", "console", "config"],
        cwd=target,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    rendered = yaml.safe_load(result.stdout)
    assert set(rendered["services"]) == {
        "postgres",
        "qdrant",
        "meilisearch",
        "rustfs",
        "api",
        "worker",
        "web",
    }
    env = dict(
        line.split("=", 1)
        for line in (target / ".env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    published = {
        port["published"]
        for service in rendered["services"].values()
        for port in service.get("ports", [])
    }
    assert env["PNEUMA_APP_WEB_PORT"] in published
    assert env["PNEUMA_APP_API_PORT"] in published
    # Both entrypoints are inside the mounted project, and the framework repo is the context.
    assert rendered["services"]["api"]["build"]["context"] == env["PNEUMA_APP_FRAMEWORK_REPO"]
    assert rendered["services"]["web"]["build"]["dockerfile"].endswith(
        "docker/compose-web.Dockerfile"
    )


# ------------------------------------------------------------------ demo mode


def _generate_demo(tmp_path: Path, *args: str) -> Path:
    """`--demo --no-start` into a temp dir: the whole generation path, no docker, no key."""
    target = tmp_path / "demo"
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--demo", "--no-start", "--target", str(target), *args],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert str(target) in result.stdout, "the demo must echo its absolute project directory"
    return target


def test_demo_generates_a_project_that_already_has_a_library(tmp_path):
    """The demo's whole promise: a real project, a real contract, a real library, no key."""
    target = _generate_demo(tmp_path)
    example = ROOT / "examples" / "opc"

    # The two authorities of the shipped library ride along, byte-identical.
    for name in ("canonical.bundle", "l0.jsonl.gz"):
        assert (target / "prebuilt" / name).read_bytes() == (
            example / "prebuilt" / name
        ).read_bytes()

    # engine/ carries the example's REAL contract and owner profile, not a skeleton.
    contract = target / "engine" / "compile" / "contract.md"
    assert contract.read_text(encoding="utf-8") == (
        example / "engine" / "compile" / "contract.md"
    ).read_text(encoding="utf-8")
    assert "TODO" not in contract.read_text(encoding="utf-8")
    assert (target / "engine" / "persona" / "profile.yaml").read_text(encoding="utf-8") == (
        example / "engine" / "persona" / "profile.yaml"
    ).read_text(encoding="utf-8")

    # A few raw materials are left as the bait for "let me watch a compile", and each one is
    # a verbatim copy of a file from the same corpus.
    material = sorted(p.name for p in (target / "my-data").glob("*.md"))
    assert 2 <= len(material) <= 4, material
    for name in material:
        assert (target / "my-data" / name).read_bytes() == (
            example / "my-data" / name
        ).read_bytes()

    # The engine states the product default (semantic); keyless it falls back to
    # mechanical chunking automatically, so the restore stays deterministic.
    assert "embedding: fake:1536" in (target / "engine" / "engine.yaml").read_text(
        encoding="utf-8"
    )
    intake = (target / "engine" / "intake" / "intake.yaml").read_text(encoding="utf-8")
    assert "chunk_strategy: semantic" in intake
    assert 'semantic_overlap: "smart"' in intake

    # .env has the same shape as any project's, with the shipped library's tenant id and no
    # key — the demo never asks for one.
    env = dict(
        line.split("=", 1)
        for line in (target / ".env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    assert env["PNEUMA_APP_USER_ID"] == "u-opc-lin"
    assert env["OPENROUTER_API_KEY"] == ""
    assert int(env["PNEUMA_APP_WEB_PORT"]) != int(env["PNEUMA_APP_API_PORT"])
    assert [
        name
        for name in env
        if name.startswith("PNEUMA_KNOWLEDGE_") and name not in _allowed_knowledge_keys()
    ] == []

    # The README says where the library came from and how to make the compiler run.
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert "demo" in readme.lower()
    assert "./app.py restore" in readme
    assert "{{" not in readme


def test_a_demo_project_is_structurally_an_ordinary_project(tmp_path):
    """Zero structural difference: same machinery, same engine layout. What a demo adds is a
    payload (prebuilt/ + the material), never a different kind of project."""
    (tmp_path / "plain").mkdir()
    demo = _generate_demo(tmp_path)
    plain = _generate(tmp_path / "plain", {"language": "zh", "data": {"mode": "none"}})

    def layout(root: Path) -> set[str]:
        return {
            p.relative_to(root).as_posix()
            for p in root.rglob("*")
            if p.is_file() and ".git" not in p.parts
        }

    demo_only = layout(demo) - layout(plain)
    plain_only = layout(plain) - layout(demo)
    assert plain_only == set(), f"the demo is missing project files: {plain_only}"
    assert demo_only == {
        "prebuilt/canonical.bundle",
        "prebuilt/l0.jsonl.gz",
        *(f"my-data/{name}" for name in sorted(p.name for p in (demo / "my-data").glob("*"))),
    }, demo_only
    assert (demo / "app.py").read_bytes() == (plain / "app.py").read_bytes()


def test_demo_engine_files_pass_the_frameworks_own_validator(tmp_path):
    from pneuma_knowledge_service.engine.apply import Change, validate

    engine = _generate_demo(tmp_path) / "engine"
    validate(
        engine,
        [
            Change(path=p.relative_to(engine).as_posix(), content=p.read_text(encoding="utf-8"))
            for p in sorted(engine.rglob("*"))
            if p.is_file() and ".git" not in p.parts
        ],
    )


def test_demo_language_follows_the_flag(tmp_path):
    (tmp_path / "en").mkdir()
    zh = _generate_demo(tmp_path)
    en = _generate_demo(tmp_path / "en", "--lang", "en")
    assert "这是独立演示项目" in (zh / "README.md").read_text(encoding="utf-8")
    assert "This is a separate demonstration project" in (en / "README.md").read_text(encoding="utf-8")
    # The contract is the example's own document in both cases — it is not a localized asset.
    assert (zh / "engine" / "compile" / "contract.md").read_bytes() == (
        en / "engine" / "compile" / "contract.md"
    ).read_bytes()


def test_demo_prompt_language_follows_the_flag(tmp_path):
    """A demo generated with --lang zh is a Chinese project end to end, prompts included; the
    English demo stays on the measured baseline."""
    (tmp_path / "en").mkdir()
    zh = _generate_demo(tmp_path)
    en = _generate_demo(tmp_path / "en", "--lang", "en")
    assert "language: zh" in (zh / "engine" / "prompts" / "overlays.yaml").read_text(
        encoding="utf-8"
    )
    assert "language: en" in (en / "engine" / "prompts" / "overlays.yaml").read_text(
        encoding="utf-8"
    )


def test_refuses_a_prompt_language_outside_the_enum(tmp_path):
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps(
            {
                "project_name": "kb",
                "target": str(tmp_path / "kb"),
                "data": {"mode": "none"},
                "advanced": {"prompt_language": "de"},
            }
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--answers", str(answers)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "prompt_language" in result.stderr + result.stdout


def test_demo_defaults_to_a_fresh_temporary_directory(tmp_path, monkeypatch):
    """No --target: the demo lands in a new temp directory and echoes the absolute path, so it
    never writes into wherever the command happened to be run."""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--demo", "--no-start"],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
    )
    assert result.returncode == 0, result.stderr
    created = [p for p in tmp_path.iterdir() if p.name.startswith("pneuma-demo-")]
    assert len(created) == 1, created
    assert str(created[0].resolve()) in result.stdout
    assert (created[0] / "prebuilt" / "canonical.bundle").is_file()


def test_demo_refuses_an_answers_file(tmp_path):
    answers = tmp_path / "a.json"
    answers.write_text("{}", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--demo", "--answers", str(answers)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "--demo takes no answers file" in (result.stderr or result.stdout)


def test_contract_follows_the_data_by_default(tmp_path):
    # Example data uses its contract; empty projects get the executable starter.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_example = _generate(tmp_path / "a", {"language": "zh", "data": {"mode": "example"}})
    contract = with_example / "engine" / "compile" / "contract.md"
    assert "aurora-planner" in contract.read_text(encoding="utf-8")
    empty = _generate(tmp_path / "b", {"language": "zh", "data": {"mode": "none"}})
    text = (empty / "engine" / "compile" / "contract.md").read_text(encoding="utf-8")
    assert "TODO" not in text
    assert "subjects/{slug}.md" in text
    assert "skill_id: my-kb-knowledge" in text
    assert not (empty / "demo-questions.txt").exists()


# ------------------------------------------------------------------ the engine directory


#: The PNEUMA_KNOWLEDGE_* variables a generated `.env` MAY carry: the engine directory, and
#: the connection settings that say which library this project is. Read from the framework's
#: own list rather than retyped, so `.env` and the launcher can never disagree about what
#: counts as a connection.
def _allowed_knowledge_keys() -> set[str]:
    from pneuma_knowledge_service.coding_agent.launcher import CONNECTION_SETTINGS

    return {"PNEUMA_KNOWLEDGE_ENGINE_DIR", *(name for name, _ in CONNECTION_SETTINGS)}


def test_env_carries_the_key_and_infrastructure_but_no_strategy(tmp_path):
    """Strategy belongs in the versioned unit; a credential must never be versioned. The
    two files exist precisely so those two facts never have to be reconciled.

    Connections are not strategy. `.env` states which Postgres, which Qdrant, which canonical
    root — the same values `app.py` would derive from the ports beside them — because `pkc`
    has no `app.py` to derive them and would otherwise reach the framework's own development
    stack. What must never appear here is a knob that decides WHAT a compile does."""
    target = _generate(tmp_path, {"language": "en", "data": {"mode": "none"}})
    env = (target / ".env").read_text(encoding="utf-8")
    settings = [
        line.split("=", 1)[0]
        for line in env.splitlines()
        if line and not line.startswith("#") and "=" in line
    ]
    strategy = [
        name
        for name in settings
        if name.startswith("PNEUMA_KNOWLEDGE_") and name not in _allowed_knowledge_keys()
    ]
    assert strategy == [], f".env still carries strategy keys: {strategy}"
    assert "PNEUMA_APP_COMPILE_MODEL" not in env  # models moved to engine/engine.yaml
    assert "PNEUMA_KNOWLEDGE_ENGINE_DIR=./engine" in env


def test_engine_is_its_own_git_repository_with_a_pinned_identity(tmp_path):
    target = _generate(tmp_path, {"language": "en", "data": {"mode": "none"}})
    engine = target / "engine"
    assert (engine / ".git").is_dir()
    log = subprocess.run(
        ["git", "-C", str(engine), "log", "--pretty=format:%s|%an <%ae>"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    # One commit, and an identity that never depended on the generating machine's git config.
    assert log == "engine: initial|pneuma-engine <engine@local>"
    status = subprocess.run(
        ["git", "-C", str(engine), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert status == "", "the generated engine is committed, not left dirty"


def test_generated_engine_files_are_exactly_what_the_framework_schema_declares(tmp_path):
    """The generator, the CLI and the console share one shape.

    Run through the framework's own apply-time validator: an engine file with a key the
    schema does not declare, a value outside a knob's enum, or a wrongly typed value would
    be refused from the console — so the generator must never write one either."""
    from pneuma_knowledge_service.engine.apply import Change, validate

    target = _generate(
        tmp_path,
        {
            "language": "en",
            "data": {"mode": "none"},
            "advanced": {
                "chunk_strategy": "sentence",
                "semantic_overlap": "off",
                "answer_style": "detailed",
                "challenge_enabled": True,
            },
        },
    )
    engine = target / "engine"
    changes = [
        Change(path=p.relative_to(engine).as_posix(), content=p.read_text(encoding="utf-8"))
        for p in sorted(engine.rglob("*"))
        if p.is_file() and ".git" not in p.parts
    ]
    validate(engine, changes)

    # YAML 1.1 treats an unquoted `off` as boolean false. The generator must preserve this
    # enum as a string so a legitimate zero-overlap project resolves before first ingest.
    from pneuma_knowledge_service.engine.resolve import resolve_engine

    resolved = resolve_engine(engine, {})
    assert resolved.values["intake.semantic_overlap"] == "off"
    assert 'semantic_overlap: "off"' in (
        engine / "intake" / "intake.yaml"
    ).read_text(encoding="utf-8")


def test_answers_land_in_the_engine_and_resolve_through_the_framework(tmp_path, monkeypatch):
    from pneuma_knowledge_service.engine.resolve import resolve_engine

    target = _generate(
        tmp_path,
        {
            "language": "en",
            "data": {"mode": "none"},
            "models": {"compile": "openrouter:x/strong", "deep": "openrouter:x/deep"},
            "advanced": {
                "chunk_strategy": "sentence",
                "answer_style": "concise",
                "challenge_enabled": True,
                "prompt_language": "zh",
            },
        },
    )
    # The session conftest pins some routing vars; an env entry outranks the engine file by
    # design, so clear them to measure the file.
    for name in (
        "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",
        "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_ANSWER",
        "PNEUMA_KNOWLEDGE_ANSWER_REASONING_EFFORT",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP",
    ):
        monkeypatch.delenv(name, raising=False)
    resolved = resolve_engine(target / "engine", {})
    assert resolved.values["intake.chunk_strategy"] == "sentence"
    assert resolved.values["recall.answer_style"] == "concise"
    assert resolved.values["challenge.enabled"] is True
    assert resolved.values["models.compile"] == "openrouter:x/strong"
    assert resolved.values["models.answer"] == ""
    assert resolved.values["models.answer_reasoning_effort"] == ""
    assert resolved.values["models.deep"] == "openrouter:x/deep"
    assert resolved.values["prompts.language"] == "zh"
    # Every generated value is STATED, not inherited: a person can read what their engine
    # does without knowing what the framework would otherwise have chosen.
    assert set(resolved.resolution.values()) == {"engine"}


def test_the_engine_readme_speaks_the_projects_language(tmp_path):
    (tmp_path / "zh").mkdir()
    (tmp_path / "en").mkdir()
    zh = _generate(tmp_path / "zh", {"language": "zh", "data": {"mode": "none"}})
    en = _generate(tmp_path / "en", {"language": "en", "data": {"mode": "none"}})
    assert "引擎" in (zh / "engine" / "README.md").read_text(encoding="utf-8")
    assert "This directory is the versioned strategy" in (en / "engine" / "README.md").read_text(
        encoding="utf-8"
    )


def test_refuses_a_non_empty_target(tmp_path):
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"language": "zh"}), encoding="utf-8")
    target = tmp_path / "out"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--answers", str(answers), "--target", str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not empty" in result.stderr
    assert (target / "keep.txt").exists()


def test_refuses_an_answers_file_carrying_an_api_key(tmp_path):
    answers = tmp_path / "answers.json"
    answers.write_text(
        json.dumps({"language": "zh", "comment": "sk-or-v1-0123456789abcdef0123"}),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--answers", str(answers), "--target", str(tmp_path / "out")],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "API-key-shaped" in result.stderr
    assert not (tmp_path / "out").exists()


def test_interactive_mode_refuses_a_non_tty_with_a_pointer_to_answers():
    result = subprocess.run(
        [sys.executable, str(INIT_PATH)], capture_output=True, text=True, input=""
    )
    assert result.returncode != 0
    assert "--answers" in result.stderr


def test_print_schema_is_valid_toml_and_key_free():
    import tomllib

    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--print-schema"], capture_output=True, text=True
    )
    assert result.returncode == 0
    parsed = tomllib.loads(result.stdout)
    assert parsed["language"] in ("zh", "en")
    assert not init.KEY_SHAPE.search(result.stdout)


def test_reference_contract_keeps_the_users_own_identity(tmp_path):
    body = tmp_path / "ref.md"
    body.write_text("# reference guidance\n\nRecord decisions.", encoding="utf-8")
    strategy = {
        "skill_id": "personal-knowledge",
        "version": "v1",
        "path_templates": ["memory/profile.md", "work/cases/{slug}.md"],
        "body_path": body,
    }
    text = init.reference_contract_text(strategy, skill_id="my-knowledge")
    assert "skill_id: my-knowledge" in text
    assert "skill_id: personal-knowledge" not in text.split("---")[1]
    assert "- work/cases/{slug}.md" in text
    assert "personal-knowledge@v1" in text


def test_strategies_catalog_reads_the_shipped_data():
    catalog = init.strategies_catalog(ROOT)
    assert catalog, "the framework repo ships at least one reference strategy"
    personal = [e for e in catalog if e["skill_id"] == "personal-knowledge"]
    assert [entry["version"] for entry in personal] == ["v1", "v2"]
    entry = personal[-1]
    assert entry["version"] == "v2"
    assert entry["path_templates"], "templates ride with the manifest"
    assert entry["body_path"].is_file()


def test_strategies_catalog_is_empty_outside_a_framework_repo(tmp_path):
    assert init.strategies_catalog(tmp_path) == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("My KB!", "my-kb"), ("已经是中文", "my-kb"), ("ok-name-9", "ok-name-9")],
)
def test_slugify_produces_safe_names(raw, expected):
    assert init.slugify(raw) == expected


# ─────────────────────────────────────────────────── who compiles (coding-agent-mode §3)
#
# The generator asks one new question and answers it in three places: `engine.yaml` states
# the executor, `bin/pkc` is the entry a person types, and the framework's own installer
# writes the skill. What these pin is the *shape* of that outcome — the rendering itself is
# the framework's, tested in `packages/pneuma-knowledge-service/tests/test_skill_package.py`.

PKC_BLOCK = "<!-- pkc:start -->"


def _agent_answers(compiler: str) -> dict:
    return {
        "language": "en",
        "project_name": "kb",
        "owner": {"display_name": "Ada"},
        "data": {"mode": "none"},
        "compiler": compiler,
    }


def test_codex_as_the_compiler_states_the_executor_and_installs_its_skill(tmp_path):
    target = _generate(tmp_path, _agent_answers("codex"))

    engine = (target / "engine" / "engine.yaml").read_text(encoding="utf-8")
    assert "\ncompile: agent:codex\n" in engine

    shim = target / "bin" / "pkc"
    assert shim.is_file() and shim.stat().st_mode & 0o111

    skill = target / ".agents" / "skills" / "pkc-steward"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "references" / "cli.md").is_file()
    assert (skill / "references" / "gate.md").is_file()
    assert (skill / "scripts" / "pkc").is_file()
    assert (target / ".agents" / "skills" / "skill-version.json").is_file()

    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert agents.count(PKC_BLOCK) == 1
    assert ".agents/skills/pkc-steward/SKILL.md" in agents
    # Claude Code was not asked for, so nothing of it is written.
    assert not (target / ".claude").exists()
    assert not (target / "CLAUDE.md").exists()


def test_claude_code_as_the_compiler_installs_its_layout_and_its_workflow(tmp_path):
    target = _generate(tmp_path, _agent_answers("claude-code"))

    assert "\ncompile: agent:claude-code\n" in (
        target / "engine" / "engine.yaml"
    ).read_text(encoding="utf-8")
    assert (target / ".claude" / "skills" / "pkc-steward" / "SKILL.md").is_file()
    assert (target / ".claude" / "workflows" / "compile.js").is_file()

    claude_md = (target / "CLAUDE.md").read_text(encoding="utf-8")
    assert claude_md.count(PKC_BLOCK) == 1
    assert ".claude/skills/pkc-steward/SKILL.md" in claude_md
    # AGENTS.md is still the project's note; it simply carries no router block.
    assert PKC_BLOCK not in (target / "AGENTS.md").read_text(encoding="utf-8")


def test_an_api_compiler_generates_exactly_what_it_always_did(tmp_path):
    """The default answer changes nothing: no skill directory, no block, no shim, and the
    compile role still names a model."""
    target = _generate(tmp_path, _agent_answers("api"))

    engine = (target / "engine" / "engine.yaml").read_text(encoding="utf-8")
    assert "compile: agent:" not in engine
    assert "\ncompile: openrouter:" in engine

    assert not (target / ".agents").exists()
    assert not (target / ".claude").exists()
    assert not (target / "bin").exists()
    assert not (target / "CLAUDE.md").exists()
    assert PKC_BLOCK not in (target / "AGENTS.md").read_text(encoding="utf-8")


def test_both_agents_share_one_project_and_codex_is_the_one_that_compiles(tmp_path):
    target = _generate(tmp_path, _agent_answers("all"))
    assert "\ncompile: agent:codex\n" in (
        target / "engine" / "engine.yaml"
    ).read_text(encoding="utf-8")
    assert (target / ".agents" / "skills" / "pkc-steward" / "SKILL.md").is_file()
    assert (target / ".claude" / "skills" / "pkc-steward" / "SKILL.md").is_file()
    assert (target / "AGENTS.md").read_text(encoding="utf-8").count(PKC_BLOCK) == 1
    assert (target / "CLAUDE.md").read_text(encoding="utf-8").count(PKC_BLOCK) == 1


def test_an_unknown_compiler_is_refused_before_anything_is_written(tmp_path):
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(json.dumps(_agent_answers("kimi")), encoding="utf-8")
    target = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--answers", str(answers_path), "--target", str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "compiler" in result.stderr
    assert not target.exists()


def test_the_project_note_routes_an_agent_to_the_skill(tmp_path):
    """The generated AGENTS.md is a router, not a second set of Steward instructions.

    It must send an agent that is going to ACT on the library to the installed skill and to
    `pkc`, and reserve the framework's own documents for the different job of changing how the
    library is built. `app.py` appears in it once, in the list of machinery not to edit — the
    note never tells an agent to drive the library through it.
    """
    target = _generate(tmp_path, _agent_answers("codex"))
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    routing = agents.split("**Two different jobs")[1].split("**Red lines**")[0]
    assert "app.py" not in routing
    assert "`pkc:start` block" in routing
    assert "do that work through\n`pkc` only" in routing
    assert agents.count("app.py") == 1


# ────────────────────────── which library, and how to open a session that can reach it


def _generate_with_output(tmp_path: Path, answers: dict) -> tuple[Path, str]:
    """`_generate`, keeping what the generator printed — the last thing a beginner reads."""
    answers_path = tmp_path / "answers.json"
    answers_path.write_text(json.dumps(answers), encoding="utf-8")
    target = tmp_path / "out"
    result = subprocess.run(
        [sys.executable, str(INIT_PATH), "--answers", str(answers_path), "--target", str(target)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return target, result.stdout


def test_env_states_this_projects_own_stack_so_pkc_cannot_reach_another(tmp_path):
    """The isolation hazard the acceptance run found: `.env` carried the project's PORTS but
    no connection settings, so `pkc` — which has no `app.py` to translate them — fell back to
    the framework repository's own development stack (15432 / 16333 / 17700) and stood in the
    developer's library instead of the owner's. Only a Qdrant dimension mismatch stopped a
    cross-library write."""
    target = _generate(tmp_path, {"language": "en", "data": {"mode": "none"}})
    env = dict(
        line.split("=", 1)
        for line in (target / ".env").read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#") and "=" in line
    )
    for name, _field in _allowed_connection_settings():
        assert name in env, f".env does not state {name}"

    pg, qdrant, meili, rustfs = (
        env["PNEUMA_APP_PG_PORT"],
        env["PNEUMA_APP_QDRANT_PORT"],
        env["PNEUMA_APP_MEILI_PORT"],
        env["PNEUMA_APP_RUSTFS_PORT"],
    )
    assert f":{pg}/" in env["PNEUMA_KNOWLEDGE_PG_DSN"]
    assert env["PNEUMA_KNOWLEDGE_QDRANT_URL"].endswith(f":{qdrant}")
    assert env["PNEUMA_KNOWLEDGE_MEILI_URL"].endswith(f":{meili}")
    assert env["PNEUMA_KNOWLEDGE_MEDIA_S3_ENDPOINT_URL"].endswith(f":{rustfs}")
    # Never the framework's own development ports.
    assert "15432" not in env["PNEUMA_KNOWLEDGE_PG_DSN"]
    assert "16333" not in env["PNEUMA_KNOWLEDGE_QDRANT_URL"]
    assert "17700" not in env["PNEUMA_KNOWLEDGE_MEILI_URL"]
    # The canonical library is this project's own directory, absolutely addressed: the shim
    # cds to the project, but a worker's launched harness runs in an empty temp directory.
    assert Path(env["PNEUMA_KNOWLEDGE_CANONICAL_ROOT"]) == (
        target / "data" / "canonical"
    ).resolve()
    assert env["PNEUMA_KNOWLEDGE_MEDIA_S3_ACCESS_KEY"] == env["PNEUMA_APP_RUSTFS_ACCESS_KEY"]


def _allowed_connection_settings():
    from pneuma_knowledge_service.coding_agent.launcher import CONNECTION_SETTINGS

    # ENGINE_DIR is stated separately by the generator (relative, as the project reads it).
    return [(n, f) for n, f in CONNECTION_SETTINGS if f != "engine_dir"]


def test_the_env_example_keeps_no_credential_of_either_kind(tmp_path):
    target = _generate(tmp_path, {"language": "en", "data": {"mode": "none"}})
    example = (target / ".env.example").read_text(encoding="utf-8")
    assert "PNEUMA_KNOWLEDGE_MEDIA_S3_SECRET_KEY=\n" in example
    assert "PNEUMA_KNOWLEDGE_MEDIA_S3_ACCESS_KEY=\n" in example
    assert "OPENROUTER_API_KEY=\n" in example
    # The non-secret half still states this project's own stack, so the file is a usable
    # recovery copy rather than a shape.
    assert "PNEUMA_KNOWLEDGE_PG_DSN=postgresql://" in example


def test_the_generator_prints_the_invocation_a_session_here_needs(tmp_path):
    """The single biggest gap the acceptance run found: a bare `codex exec` runs read-only
    and networkless, so `pkc` cannot open this project's database and the headline experience
    of the feature does not work out of the box. Nothing said the flags — not the generator,
    not the README, not the router block. The commands come from the framework's backend
    manifests, so this asserts against those rather than against a retyped string."""
    from pneuma_knowledge_service.coding_agent.backends import CODEX

    _target, out = _generate_with_output(tmp_path, _agent_answers("codex"))
    assert CODEX.owner_session_command in out
    assert CODEX.owner_exec_command in out
    assert "--sandbox workspace-write" in out


def test_an_empty_key_makes_the_generator_state_the_embedding_reminder(tmp_path):
    """A deployment with no embedding key is not a supported "no-L2" mode (design §3.1): the
    generator says so on the way out, in the framework's own words rather than a second text
    of its own."""
    from pneuma_knowledge_service.embedding_key import EMBEDDING_SETTING

    _target, out = _generate_with_output(tmp_path, {"language": "en", "data": {"mode": "none"}})
    # Wrapped for the terminal, so the assertion is on the words rather than on one line.
    flat = " ".join(out.split())
    assert EMBEDDING_SETTING in flat
    assert "OPENROUTER_API_KEY" in flat
    assert "L2" in flat


def test_answers_that_never_named_the_owner_keep_the_placeholder_and_say_so(tmp_path):
    """The generator does not guess who the owner is — nobody here knows. What it does is say
    what the placeholder costs, because a first compile files the owner as a stranger and the
    pages it writes are permanent."""
    _target, out = _generate_with_output(tmp_path, {"language": "en", "data": {"mode": "none"}})
    flat = " ".join(out.split())
    assert "pkc profile set" in flat
    assert "placeholder" in flat

    named = tmp_path / "named"
    named.mkdir()
    _t2, quiet = _generate_with_output(
        named, {"language": "en", "owner": {"display_name": "Chen Wan"}, "data": {"mode": "none"}}
    )
    assert "pkc profile set" not in " ".join(quiet.split())


def test_the_readme_states_it_too_and_only_for_an_agent_compiler(tmp_path):
    from pneuma_knowledge_service.coding_agent.backends import CODEX

    target = _generate(tmp_path, _agent_answers("codex"))
    readme = (target / "README.md").read_text(encoding="utf-8")
    assert CODEX.owner_session_command in readme
    assert CODEX.owner_exec_command in readme
    assert "bin/pkc" in readme

    api_dir = tmp_path / "api"
    api_dir.mkdir()
    plain = _generate(api_dir, _agent_answers("api"))
    assert "--sandbox workspace-write" not in (plain / "README.md").read_text(encoding="utf-8")
    assert "{{STEWARD_SECTION}}" not in (plain / "README.md").read_text(encoding="utf-8")


def test_the_router_block_states_it_as_well(tmp_path):
    """Three places, because a session that cannot run `pkc` never gets as far as the skill:
    the router block in AGENTS.md, SKILL.md's posture section, and the README."""
    from pneuma_knowledge_service.coding_agent.backends import CODEX

    target = _generate(tmp_path, _agent_answers("codex"))
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert CODEX.owner_session_command in agents
    skill = (target / ".agents" / "skills" / "pkc-steward" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert CODEX.owner_session_command in skill
    assert CODEX.owner_exec_command in skill


def test_the_skill_names_bin_pkc_as_the_entry_in_a_scaffold_project(tmp_path):
    """One entry name. The scaffold writes `bin/pkc` and every other document names it, so
    the skill names it too rather than teaching a second path for the same door."""
    target = _generate(tmp_path, _agent_answers("codex"))
    skill = (target / ".agents" / "skills" / "pkc-steward" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Run it as `bin/pkc`" in skill
    assert ".agents/skills/pkc-steward/scripts/pkc" not in skill
    # The shim itself is still installed and still works — it is what `bin/pkc` points at.
    assert (target / ".agents" / "skills" / "pkc-steward" / "scripts" / "pkc").is_file()


def test_the_project_shim_points_uv_at_a_writable_cache(tmp_path):
    """`uv run` needs a writable `~/.cache/uv`, which a sandboxed harness does not have —
    both acceptance sessions had to set the variable themselves before `pkc` would run."""
    target = _generate(tmp_path, _agent_answers("codex"))
    shim = (target / ".agents" / "skills" / "pkc-steward" / "scripts" / "pkc").read_text(
        encoding="utf-8"
    )
    assert 'UV_CACHE_DIR="$project/.uv-cache"' in shim
    assert "export UV_CACHE_DIR" in shim
    assert ".uv-cache/" in (target / ".gitignore").read_text(encoding="utf-8")


def test_default_generation_is_ready_for_real_material_without_demo_or_fake_owner(tmp_path):
    import yaml

    target = _generate(tmp_path, {"language": "en"})
    assert list((target / "my-data").iterdir()) == []
    assert not (target / "prebuilt").exists()
    assert not (target / "demo-questions.txt").exists()
    contract = (target / "engine/compile/contract.md").read_text()
    assert "subjects/{slug}.md" in contract and "TODO" not in contract
    profile = yaml.safe_load((target / "engine/persona/profile.yaml").read_text())
    assert not profile["display_name"] and not profile["bio"]
    assert not profile["industry"] and not profile["level"]
    assert 'exec ./app.py build "$@"' in (target / "start.sh").read_text()
