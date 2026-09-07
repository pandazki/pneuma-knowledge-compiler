"""Which library is this `pkc` standing in, and what it refuses when it cannot tell.

Two guards, one question, both found by the end-to-end acceptance run of coding agent mode:

* `pkc` had no equivalent of `app.py`'s `isolation_problems`, so a project whose `.env`
  stated its ports but not its DSNs sent every command to the FRAMEWORK's own development
  stack. Only a Qdrant vector-dimension mismatch stopped a cross-library write.
* a refusal at the argument face must be a refusal — one line and exit 2 — and not a Python
  traceback, because a Steward mid-round reads what the command printed.

Keyless: the guard is a pure function of settings plus environment, and the exit-code test
substitutes the context the command would have connected with.
"""

from __future__ import annotations

from pathlib import Path

from pneuma_knowledge_service.cli import main
from pneuma_knowledge_service.cli.isolation import (
    isolation_refusal,
    project_isolation_problems,
    read_env_file,
)
from pneuma_knowledge_service.settings import Settings

#: The framework's own development stack — what the built-in defaults are, and precisely the
#: library a generated project must never reach.
FRAMEWORK_DEFAULTS = Settings(
    pg_dsn="postgresql://pneuma_knowledge:pneuma_knowledge@localhost:15432/pneuma_knowledge",
    qdrant_url="http://localhost:16333",
    meili_url="http://localhost:17700",
    media_s3_endpoint_url="http://localhost:19000",
    canonical_root="./data/canonical",
)


def _project(tmp_path: Path, *, ports: dict[str, int], knowledge: dict[str, str] | None = None):
    """A generated project's `.env`, as the generator writes it."""
    lines = [f"PNEUMA_APP_{name.upper()}_PORT={port}" for name, port in ports.items()]
    lines += [f"{k}={v}" for k, v in (knowledge or {}).items()]
    (tmp_path / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


PORTS = {"pg": 52180, "qdrant": 57897, "meili": 44322, "rustfs": 48304}


def test_a_directory_that_is_not_a_project_is_not_checked(tmp_path):
    """No `PNEUMA_APP_*` ports stated is not a generated project — the framework's own
    development use, a container, a hand-assembled deployment. All behave exactly as they did
    before this guard existed."""
    assert project_isolation_problems(FRAMEWORK_DEFAULTS, environ={}, project=tmp_path) == []


def test_the_default_dev_ports_beside_a_projects_env_are_refused(tmp_path):
    """The acceptance case, exactly: ports written for this project, settings resolved to the
    framework's own stack."""
    root = _project(tmp_path, ports=PORTS)
    problems = project_isolation_problems(FRAMEWORK_DEFAULTS, environ={}, project=root)
    # Four services, plus the canonical root: the default `./data/canonical` resolves against
    # the working directory, and a `pkc` whose working directory is not the project is
    # standing somewhere else too.
    assert len(problems) == 5
    joined = "\n".join(problems)
    assert "canonical_root" in joined
    for label, port in (
        ("Postgres", 52180),
        ("Qdrant", 57897),
        ("Meilisearch", 44322),
        ("the media store", 48304),
    ):
        assert label in joined and str(port) in joined

    refusal = isolation_refusal(problems)
    assert "refuses to run" in refusal
    assert "PNEUMA_KNOWLEDGE_PG_DSN" in refusal  # the message names the fix
    assert "re-running the generator" in refusal


def test_a_project_whose_env_states_its_own_stack_passes(tmp_path):
    root = _project(
        tmp_path,
        ports=PORTS,
        knowledge={
            "PNEUMA_KNOWLEDGE_PG_DSN": "postgresql://u:p@localhost:52180/pneuma_knowledge",
            "PNEUMA_KNOWLEDGE_QDRANT_URL": "http://localhost:57897",
            "PNEUMA_KNOWLEDGE_MEILI_URL": "http://localhost:44322",
            "PNEUMA_KNOWLEDGE_MEDIA_S3_ENDPOINT_URL": "http://localhost:48304",
        },
    )
    settings = Settings(
        pg_dsn="postgresql://u:p@localhost:52180/pneuma_knowledge",
        qdrant_url="http://localhost:57897",
        meili_url="http://localhost:44322",
        media_s3_endpoint_url="http://localhost:48304",
        canonical_root=str(root / "data" / "canonical"),
    )
    assert project_isolation_problems(settings, environ={}, project=root) == []


def test_the_environment_outranks_the_file_because_the_shim_sources_it(tmp_path):
    """The skill's shim `set -a; . .env` — so what a command actually runs under is the
    environment, and a stale file must not answer for it."""
    root = _project(tmp_path, ports=PORTS)
    settings = Settings(
        pg_dsn="postgresql://u:p@localhost:60001/pneuma_knowledge",
        qdrant_url="http://localhost:57897",
        meili_url="http://localhost:44322",
        media_s3_endpoint_url="http://localhost:48304",
        canonical_root=str(root / "data" / "canonical"),
    )
    problems = project_isolation_problems(
        settings, environ={"PNEUMA_APP_PG_PORT": "60001"}, project=root
    )
    assert problems == []


def test_a_canonical_root_outside_the_project_is_refused(tmp_path):
    root = _project(tmp_path, ports=PORTS)
    settings = Settings(
        pg_dsn="postgresql://u:p@localhost:52180/pneuma_knowledge",
        qdrant_url="http://localhost:57897",
        meili_url="http://localhost:44322",
        media_s3_endpoint_url="http://localhost:48304",
        canonical_root="/tmp/somebody-elses-library",
    )
    problems = project_isolation_problems(settings, environ={}, project=root)
    assert len(problems) == 1 and "canonical_root" in problems[0]


def test_the_env_reader_is_the_shims_own_and_tolerates_a_file_it_cannot_read(tmp_path):
    (tmp_path / ".env").write_text(
        '# a comment\n\nA=1\nB="quoted"\nC=\nnot-an-assignment\n', encoding="utf-8"
    )
    assert read_env_file(tmp_path / ".env") == {"A": "1", "B": "quoted", "C": ""}
    assert read_env_file(tmp_path / "absent") == {}


# ─────────────────────────────────────────── the other refusal: exit 2, never a traceback


def test_an_unreadable_text_file_exits_two_with_one_line(monkeypatch, capsys, tmp_path):
    """`pkc owner say --text-file /nope` used to die in `open()`. The Steward reads exit
    codes and one line of prose; a traceback is neither."""
    from pneuma_knowledge_service import wiring
    from pneuma_knowledge_service.engine import contract as engine_contract

    class _Ctx:
        async def aclose(self):
            return None

    async def _build_context(_settings, **_kw):
        return _Ctx()

    monkeypatch.setattr(wiring, "build_context", _build_context)
    monkeypatch.setattr(engine_contract, "bootstrap_engine", lambda _settings: None)
    monkeypatch.chdir(tmp_path)

    missing = str(tmp_path / "statement.txt")
    code = main(["owner", "say", "--text-file", missing])
    assert code == 2
    err = capsys.readouterr().err
    assert err.count("\n") == 1  # exactly one line
    assert err.startswith("error: cannot read")
    assert "Traceback" not in err
