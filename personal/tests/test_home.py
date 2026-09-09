import io
import os
import json
import stat

import httpx
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


def test_credentials_permissions_output_steps_and_status(home, make_library, monkeypatch, capsys, provider):
    library = make_library()
    provider.accepts()
    monkeypatch.setattr("sys.stdin", io.StringIO("synthetic-key\n"))
    assert cli.main(["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin"]) == 0
    assert capsys.readouterr().out == (
        "stored OPENROUTER_API_KEY (13 chars) — verified openrouter:openai/text-embedding-3-small\n"
    )
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


def test_storing_a_credential_replaces_every_running_engine(home, make_library, monkeypatch, capsys, provider):
    """A key reaches an engine only as its environment: saving one while the engine runs
    must replace the process, or recall goes on answering keyless until someone restarts."""
    up, idle = make_library("up"), make_library("idle")
    provider.accepts()
    events: list[tuple[str, str]] = []
    monkeypatch.setattr(engine, "status", lambda _home, library: {"up": library.state.name == "up", "pid": 1, "port": 1, "uptime": 1.0})
    monkeypatch.setattr(engine, "stop", lambda _home, library: events.append(("stop", library.state.name)))
    monkeypatch.setattr(engine, "start", lambda _home, library: events.append(("start", library.state.name)))
    monkeypatch.setattr("sys.stdin", io.StringIO("synthetic-key\n"))
    assert cli.main(["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin"]) == 0
    assert capsys.readouterr().out == (
        "stored OPENROUTER_API_KEY (13 chars) — verified openrouter:openai/text-embedding-3-small\n"
        "restarted engine up so it holds the key\n"
    )
    assert events == [("stop", "up"), ("start", "up")]
    assert home.credentials()["OPENROUTER_API_KEY"] == "synthetic-key"
    assert idle.state.name == "idle"


def _rejection(status: int = 401) -> RuntimeError:
    """What the adapter raises when the provider has decided: a chained HTTP status."""
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/embeddings")
    refusal = RuntimeError(f"OpenRouter embeddings failed after 1 try: {status}")
    refusal.__cause__ = httpx.HTTPStatusError(
        "client error", request=request, response=httpx.Response(status, request=request)
    )
    return refusal


def test_a_refused_key_is_not_stored_and_no_engine_is_touched(home, make_library, monkeypatch, capsys, provider):
    """The incident, mechanically. A pasted URL was stored over a working key, every engine
    was restarted, the command reported success, and the engine then died at startup on a
    401 with the queue standing still. A refused candidate must change nothing at all."""
    make_library("up")
    provider.accepts()
    monkeypatch.setattr("sys.stdin", io.StringIO("working-key\n"))
    assert cli.main(["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin"]) == 0
    capsys.readouterr()
    path = home.path / "credentials"
    before = path.read_bytes()

    touched: list[str] = []
    for verb in ("status", "stop", "start"):
        monkeypatch.setattr(engine, verb, lambda *_a, _verb=verb, **_kw: touched.append(_verb))
    pasted = "https://example.invalid/pasted-by-mistake"
    provider.refuses(_rejection())
    monkeypatch.setattr("sys.stdin", io.StringIO(pasted + "\n"))

    assert cli.main(["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin"]) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == (
        "refused: OPENROUTER_API_KEY was not stored — openrouter rejected it "
        "(401 Unauthorized); the previous key, if any, is unchanged\n"
    )
    assert pasted not in output.err
    assert path.read_bytes() == before
    assert home.credentials()["OPENROUTER_API_KEY"] == "working-key"
    assert touched == []
    assert provider.calls[-1] == ("openrouter:openai/text-embedding-3-small", pasted)


def test_a_refused_first_key_leaves_no_credentials_file(home, make_library, capsys, monkeypatch, provider):
    """Nothing to preserve is still nothing to write: an unreachable provider is a refusal."""
    make_library()
    provider.refuses(TimeoutError("synthetic"))
    monkeypatch.setattr("sys.stdin", io.StringIO("candidate-key\n"))
    assert cli.main(["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin"]) == 1
    assert capsys.readouterr().err == (
        "refused: OPENROUTER_API_KEY was not stored — openrouter did not answer "
        "(TimeoutError); the previous key, if any, is unchanged\n"
    )
    assert not (home.path / "credentials").exists()


def test_a_credential_no_provider_claims_is_stored_unprobed(home, make_library, monkeypatch, capsys, provider):
    """Only the embedding key of the configured spec has somewhere to be checked; the line
    says which of the two happened rather than letting silence stand for a verdict."""
    make_library()
    monkeypatch.setattr("sys.stdin", io.StringIO("synthetic-token\n"))
    assert cli.main(["credentials", "set", "LANGFUSE_SECRET_KEY", "--from-stdin"]) == 0
    assert capsys.readouterr().out == (
        "stored LANGFUSE_SECRET_KEY (15 chars) — not verified: no probe for this credential\n"
    )
    assert provider.calls == []
    assert home.credentials()["LANGFUSE_SECRET_KEY"] == "synthetic-token"


def test_no_verify_stores_the_key_and_says_it_was_not_checked(home, make_library, monkeypatch, capsys, provider):
    """The offline case, named in the output: a key stored unchecked never reads as verified."""
    make_library()
    monkeypatch.setattr("sys.stdin", io.StringIO("offline-key\n"))
    assert cli.main(["credentials", "set", "OPENROUTER_API_KEY", "--from-stdin", "--no-verify"]) == 0
    assert capsys.readouterr().out == "stored OPENROUTER_API_KEY (11 chars) — not verified (--no-verify)\n"
    assert provider.calls == []
    assert home.credentials()["OPENROUTER_API_KEY"] == "offline-key"


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


def test_the_deployment_default_calendar_is_this_machines_zone(home, make_library, monkeypatch):
    """A personal edition runs on the Owner's machine: the engine and every `pkc` read count
    days in this machine's zone unless the profile declares one. Process env still wins."""
    from pkc_personal import environment
    library = make_library()
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(os, "readlink", lambda path: "/var/db/timezone/zoneinfo/Asia/Shanghai")
    assert home_environment(home, library)["PNEUMA_KNOWLEDGE_DEFAULT_TIMEZONE"] == "Asia/Shanghai"
    monkeypatch.setattr(os, "readlink", lambda path: (_ for _ in ()).throw(OSError()))
    assert environment.local_timezone_name() == "UTC"
    monkeypatch.setenv("TZ", "Europe/Berlin")
    assert environment.local_timezone_name() == "Europe/Berlin"
