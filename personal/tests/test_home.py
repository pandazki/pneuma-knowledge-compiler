import io
import json
import stat

import pytest

from pkc_personal import cli, engine, home as home_module, infra, status
from pkc_personal.environment import home_environment
from pkc_personal.home import Config, Home


def test_layout_and_config_roundtrip(home):
    assert {"config.yaml", "infra", "run", "data", "libraries"} <= {p.name for p in home.path.iterdir()}
    assert isinstance(home.config, Config)
    config = home.config
    original = (home.path / "config.yaml").read_bytes()
    home.save_config(config)
    assert (home.path / "config.yaml").read_bytes() == original
    assert Home(home.path).initialize().model_dump() == config.model_dump()
    assert set(config.infra.ports.model_dump().values()) == set(range(24000, 24006))
    assert "credentials" not in {p.name for p in home.path.iterdir()}


def test_credentials_permissions_output_steps_and_status(home, make_library, monkeypatch, capsys):
    library = make_library()
    monkeypatch.setattr("sys.stdin", io.StringIO("synthetic-key\n"))
    assert cli.main(["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin"]) == 0
    assert capsys.readouterr().out == "stored OPENROUTER_API_KEY (13 chars)\n"
    path = home.path / "credentials"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    path.chmod(0o644)
    home.set_credential("EXTRA_KEY", "extra-value")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert home.credentials()["OPENROUTER_API_KEY"] == "synthetic-key"
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(status, "queue_status", lambda _: None)
    monkeypatch.setattr(status, "skill_fresh", lambda *_: None)
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)
    assert cli.main(["status", "--json"]) == 0
    output = capsys.readouterr().out
    assert "synthetic-key" not in output and "extra-value" not in output
    for value in (home.config.infra.pg_password, home.config.infra.meili_key, home.config.infra.rustfs_secret_key):
        assert value not in output
    document = json.loads(output)
    row = document["libraries"][0]
    assert row["steps"]["credentials"] is not None
    assert row["key"] is True
    assert set(row["steps"]) == {"infra", "credentials", "profile", "skill", "first_compile"}
    assert row["steps"]["profile"] is None and row["steps"]["first_compile"] is None


@pytest.mark.parametrize("key,value", [("bad-key", "value"), ("LOWER_key", "value"), ("KEY", "one\ntwo"), ("KEY", "one\0two")])
def test_credentials_refuse_invalid_content(home, key, value):
    with pytest.raises(ValueError):
        home.set_credential(key, value)
    assert not (home.path / "credentials").exists()


def test_environment_precedence_and_no_model_specs(home, make_library, monkeypatch):
    library = make_library()
    home.set_credential("OPENROUTER_API_KEY", "file-key")
    home.set_credential("PNEUMA_KNOWLEDGE_MEILI_KEY", "credential-meili")
    home.set_credential("PNEUMA_KNOWLEDGE_ENV_FILE", "untrusted.env")
    env = home_environment(home, library)
    assert env["PNEUMA_KNOWLEDGE_MEILI_KEY"] == "credential-meili"
    assert env["PNEUMA_KNOWLEDGE_ENV_FILE"] == ""
    assert env["OPENROUTER_API_KEY"] == "file-key"
    assert env["PNEUMA_KNOWLEDGE_PG_DSN"].endswith(":24000/pneuma_knowledge")
    assert env["PNEUMA_KNOWLEDGE_QDRANT_COLLECTION"] == "pkc_personal_chunks"
    assert env["PNEUMA_KNOWLEDGE_WORKER_TENANTS"] == "lib-notes"
    assert env["PNEUMA_KNOWLEDGE_ENGINE_DIR"] == str(library.engine_dir)
    assert env["PNEUMA_KNOWLEDGE_CANONICAL_ROOT"] == str(library.path / "canonical")
    assert "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL" not in env
    assert "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE" not in env
    monkeypatch.setenv("OPENROUTER_API_KEY", "process-key")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_MEILI_KEY", "process-meili")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENV_FILE", "explicit.env")
    env = home_environment(home, library)
    assert env["OPENROUTER_API_KEY"] == "process-key"
    assert env["PNEUMA_KNOWLEDGE_MEILI_KEY"] == "process-meili"
    assert env["PNEUMA_KNOWLEDGE_ENV_FILE"] == "explicit.env"


def test_atomic_write_failure_preserves_old_file(home, monkeypatch):
    home.set_credential("KEY", "old")
    def fail(*_):
        raise OSError("synthetic rename failure")
    monkeypatch.setattr(home_module.os, "replace", fail)
    with pytest.raises(OSError):
        home.set_credential("KEY", "new")
    assert home.credentials() == {"KEY": "old"}
    assert not list(home.path.glob(".*.tmp"))
