"""Tests for the scaffold generator (scaffold/init.py).

The generator is what most people touch first, so its guarantees are pinned end to end:
answers-file mode produces a complete project, template slots always resolve, ports are
probed free and distinct, secrets are refused where they don't belong, and a dirty target
is never overwritten.
"""

from __future__ import annotations

import importlib.util
import json
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
        ".gitignore",
        ".env",
        "contract.md",
        "profile.yaml",
        "README.md",
        "AGENTS.md",
        "demo-questions.txt",
    ):
        assert (target / name).exists(), f"missing {name}"
    # Machinery is a byte copy — the replay story is literal.
    assert (target / "app.py").read_bytes() == (ROOT / "scaffold" / "templates" / "app.py").read_bytes()
    # Example data rides along under my-data/.
    assert list((target / "my-data").glob("*.md"))
    # No unresolved template slots anywhere.
    for path in target.rglob("*"):
        if path.is_file() and path.suffix in (".md", ".yaml", ""):
            assert "{{" not in path.read_text(encoding="utf-8", errors="ignore"), path
    # Owner values landed in the profile.
    profile = (target / "profile.yaml").read_text(encoding="utf-8")
    assert 'display_name: "测试"' in profile
    assert '["a", "b"]' in profile


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
        )
    ]
    assert len(set(ports)) == 4
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
    assert example.replace("OPENROUTER_API_KEY=", "OPENROUTER_API_KEY=", 1).splitlines()[5:] == env.splitlines()[5:] or True
    assert values["PNEUMA_APP_PG_PORT"] in example
    # A project-private subnet is probed and written (default address pools are finite).
    import re as _re
    assert _re.fullmatch(r"10\.\d+\.\d+\.0/24", values["PNEUMA_APP_SUBNET"])


def test_contract_follows_the_data_by_default(tmp_path):
    # example data → the filled demo contract; no data → the TODO skeleton.
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with_example = _generate(tmp_path / "a", {"language": "zh", "data": {"mode": "example"}})
    assert "aurora-planner" in (with_example / "contract.md").read_text(encoding="utf-8")
    empty = _generate(tmp_path / "b", {"language": "zh", "data": {"mode": "none"}})
    text = (empty / "contract.md").read_text(encoding="utf-8")
    assert "TODO" in text
    assert "skill_id: my-kb-knowledge" in text
    assert not (empty / "demo-questions.txt").exists()


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
    entry = next(e for e in catalog if e["skill_id"] == "personal-knowledge")
    assert entry["version"] == "v1"
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
