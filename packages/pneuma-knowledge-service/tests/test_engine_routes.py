"""The `/v1/engine/*` surface: keyless, middleware-free, over a real temporary git repo.

The engine console reads and writes one directory, so its tests need no Postgres/Qdrant/Meili
and no model — `httpx.ASGITransport` never runs the lifespan, and the routes read
`app.state.settings` rather than the app context on purpose. Git is real here: an apply that
claimed to commit but did not would be exactly the bug worth catching.
"""

from __future__ import annotations

import asyncio
import subprocess
import textwrap
import time
from pathlib import Path

import httpx
import pytest

from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings

SEED = {
    "README.md": "# engine\n\nthis project's engine.\n",
    "engine.yaml": "compile: openrouter:x/compile\nrecall: openrouter:x/recall\n",
    "intake/intake.yaml": "chunk_strategy: sentence\n",
    "compile/contract.md": "---\nskill_id: demo\nversion: app-v1\n---\n\nRecord decisions.\n",
    "compile/challenge.yaml": "enabled: false\nmax_rounds: 2\n",
    "evolve/evolve.yaml": "auto_trigger: true\n",
    "recall/recall.yaml": "answer_style: conversational\nclaim_cap: 64\n",
    "persona/profile.yaml": "display_name: Someone\n",
    # `language:` is stated, as a generated project states it: the shared overlay contract
    # fixture carries it too, so a seed that left it absent would make applying that fixture
    # report a language change it does not make.
    "prompts/overlays.yaml": (
        'language: en\noverlays:\n  gate.anchor_continuity: "an anchor never moves"\n'
    ),
}


def _seed_engine(root: Path, files: dict[str, str] | None = None) -> Path:
    engine = root / "engine"
    for rel, text in (SEED if files is None else files).items():
        path = engine / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    engine.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(engine), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(engine), "config", "user.email", "engine@local"], check=True
    )
    subprocess.run(
        ["git", "-C", str(engine), "config", "user.name", "pneuma-engine"], check=True
    )
    subprocess.run(["git", "-C", str(engine), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(engine), "commit", "-q", "-m", "engine: initial"], check=True
    )
    return engine


def _client(engine_dir: str) -> httpx.AsyncClient:
    app = create_app(Settings(engine_dir=engine_dir))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for name in (
        "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",
        "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL",
        "PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP",
    ):
        monkeypatch.delenv(name, raising=False)


# ------------------------------------------------------------------ unconfigured = no surface


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/v1/engine/schema"),
        ("GET", "/v1/engine/state"),
        ("GET", "/v1/engine/file?path=a.md"),
        ("GET", "/v1/engine/history"),
        ("GET", "/v1/engine/history/0123abc/files"),
        ("POST", "/v1/engine/apply"),
        ("GET", "/v1/engine/prompts"),
        ("POST", "/v1/engine/prompts/rewrite"),
    ],
)
async def test_every_route_404s_without_an_engine_dir(method, path):
    async with _client("") as client:
        resp = await client.request(
            method,
            path,
            json={
                "changes": [{"path": "a.md", "content": "x"}],
                "label": "l",
                "key": "recall.spine",
                "intent": "shorter",
                "locale": "en",
            },
        )
    assert resp.status_code == 404
    assert "engine directory" in resp.json()["detail"]


# ------------------------------------------------------------------ schema / state / history


async def test_schema_is_the_committed_asset(tmp_path):
    from pneuma_knowledge_service.engine.schema import load_schema

    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/schema")
    assert resp.status_code == 200
    assert resp.json() == load_schema()


async def test_state_reports_files_values_resolution_and_version(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/state")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["files"]) == set(SEED)
    assert body["files"]["compile/contract.md"].endswith("Record decisions.\n")
    assert body["values"]["intake.chunk_strategy"] == "sentence"
    assert body["values"]["challenge.max_questions"] == 6  # framework default
    assert body["resolution"]["intake.chunk_strategy"] == "engine"
    assert body["resolution"]["challenge.max_questions"] == "default"
    # A document has no scalar value: it is reachable as a file and nothing else.
    assert "compile.contract" not in body["values"]
    assert len(body["version"]["head"]) == 40
    assert body["version"]["dirty"] is False


async def test_state_reports_env_as_the_origin_when_the_environment_states_a_knob(
    tmp_path, monkeypatch
):
    engine = _seed_engine(tmp_path)
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_CHUNK_STRATEGY", "semantic")
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/state")).json()
    assert body["resolution"]["intake.chunk_strategy"] == "env"
    assert body["values"]["intake.chunk_strategy"] == "semantic"


async def test_state_reports_a_dirty_tree(tmp_path):
    engine = _seed_engine(tmp_path)
    (engine / "recall" / "recall.yaml").write_text("claim_cap: 80\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/state")).json()
    assert body["version"]["dirty"] is True
    assert body["values"]["recall.claim_cap"] == 80


async def test_state_400s_on_hand_broken_yaml_instead_of_guessing(tmp_path):
    engine = _seed_engine(tmp_path)
    (engine / "recall" / "recall.yaml").write_text("claim_cap: [oops\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/state")
    assert resp.status_code == 400
    assert "recall/recall.yaml" in resp.json()["detail"]


async def test_codex_an_oversized_file_is_a_named_gap_not_a_silent_empty_one(tmp_path):
    """codex review #8: the read side skipped >512 KiB files with no cap on the write side.

    A 513 KiB contract could be committed, vanished from the next /state, and the editor —
    reading a missing entry as an empty string — was one save away from overwriting it.
    """
    from pneuma_knowledge_service.engine.files import MAX_FILE_BYTES

    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        refused = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/contract.md", "content": "x" * (MAX_FILE_BYTES + 1)}
                ],
                "label": "a whole dataset",
            },
        )
        # The write side is closed, so the read side's diagnostic is reachable only for a file
        # somebody put there by hand — which is exactly when it has to be legible.
        (engine / "notes").mkdir()
        (engine / "notes" / "blob.md").write_text("y" * (MAX_FILE_BYTES + 1), encoding="utf-8")
        (engine / "notes" / "binary.md").write_bytes(b"\xff\xfe\x00\x01not utf-8")
        state = (await client.get("/v1/engine/state")).json()
    assert refused.status_code == 400, refused.text
    assert "past the" in refused.json()["detail"]
    assert (engine / "compile" / "contract.md").read_text(encoding="utf-8") == SEED[
        "compile/contract.md"
    ], "a rejected apply writes nothing"
    assert "notes/blob.md" not in state["files"]
    assert "bytes, past the" in state["skipped"]["notes/blob.md"]
    assert "UTF-8" in state["skipped"]["notes/binary.md"]
    # `.git` and other dotfiles are not engine files at all, so they are not reported as gaps.
    assert not any(path.startswith(".") for path in state["skipped"])


async def test_state_reports_no_skips_for_a_healthy_directory(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        assert (await client.get("/v1/engine/state")).json()["skipped"] == {}


# ------------------------------------------------------------------ file: the repair path


async def test_codex_a_broken_engine_can_be_repaired_without_leaving_the_console(tmp_path):
    """CODEX-E2E-UX flow 3: after /state 400s, the console had no way back in.

    The audit could only recover because it already knew the file's original contents and was
    calling the API by hand. `GET /file` answers per file with no resolution involved, so read →
    fix → apply closes the loop, and the repair lands as an ordinary labelled version.
    """
    engine = _seed_engine(tmp_path)
    (engine / "recall" / "recall.yaml").write_text("claim_cap: [oops\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        broken = await client.get("/v1/engine/state")
        # Everything else still answers — the console keeps its picture and its history.
        assert (await client.get("/v1/engine/schema")).status_code == 200
        assert (await client.get("/v1/engine/history")).status_code == 200

        raw = await client.get("/v1/engine/file", params={"path": "recall/recall.yaml"})
        repaired = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "recall/recall.yaml", "content": "answer_style: concise\nclaim_cap: 64\n"}
                ],
                "label": "repair malformed yaml",
            },
        )
        fixed = await client.get("/v1/engine/state")
    assert broken.status_code == 400
    assert "recall/recall.yaml" in broken.json()["detail"], "the detail names the file to repair"
    assert raw.status_code == 200
    assert raw.json() == {"path": "recall/recall.yaml", "content": "claim_cap: [oops\n"}
    assert repaired.status_code == 200, repaired.text
    assert fixed.status_code == 200
    assert fixed.json()["values"]["recall.claim_cap"] == 64


@pytest.mark.parametrize(
    ("path", "status"),
    [
        ("recall/recall.yaml", 200),
        ("./recall/recall.yaml", 400),  # one canonical spelling, same as apply
        ("../escape.md", 400),
        ("/etc/passwd", 400),
        (".env", 400),
        ("nope/missing.yaml", 404),
    ],
)
async def test_file_addresses_exactly_what_an_apply_addresses(tmp_path, path, status):
    engine = _seed_engine(tmp_path)
    (engine / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-nope\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/file", params={"path": path})
    assert resp.status_code == status, resp.text


async def test_file_refuses_a_file_it_cannot_hand_back_as_text(tmp_path):
    from pneuma_knowledge_service.engine.files import MAX_FILE_BYTES

    engine = _seed_engine(tmp_path)
    (engine / "notes").mkdir()
    (engine / "notes" / "blob.md").write_text("y" * (MAX_FILE_BYTES + 1), encoding="utf-8")
    (engine / "notes" / "binary.md").write_bytes(b"\xff\xfe\x00\x01")
    async with _client(str(engine)) as client:
        big = await client.get("/v1/engine/file", params={"path": "notes/blob.md"})
        binary = await client.get("/v1/engine/file", params={"path": "notes/binary.md"})
    assert big.status_code == 400 and "past the" in big.json()["detail"]
    assert binary.status_code == 400 and "UTF-8" in binary.json()["detail"]


async def test_history_lists_commits_newest_first_with_their_files(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": "claim_cap: 80\n"}],
                "label": "raise the claim budget",
            },
        )
        resp = await client.get("/v1/engine/history?limit=10")
    assert resp.status_code == 200
    commits = resp.json()
    assert [c["label"] for c in commits] == ["raise the claim budget", "engine: initial"]
    assert commits[0]["files"] == ["recall/recall.yaml"]
    assert commits[0]["at"]  # ISO timestamp from git


async def test_history_of_a_directory_without_a_repo_is_empty(tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    async with _client(str(engine)) as client:
        assert (await client.get("/v1/engine/history")).json() == []


# ------------------------------------------------------- one version's files ("how do I undo")


async def test_a_versions_files_are_what_that_commit_held(tmp_path):
    """VERIFY #3: the timeline said what changed and offered no way back, because the API had
    no answer for "what did this file used to say". With the contents in reach, undo is the
    ordinary path — load the old content into the draft, review, apply with a label."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        first = (await client.get("/v1/engine/history")).json()[0]["sha"]
        applied = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/challenge.yaml", "content": "enabled: false\nmax_rounds: 3\n"}
                ],
                "label": "challenge rounds 2 → 3",
            },
        )
        second = applied.json()["sha"]
        before = await client.get(f"/v1/engine/history/{first}/files")
        after = await client.get(f"/v1/engine/history/{second}/files")
    assert before.status_code == 200 and after.status_code == 200
    assert before.json()["sha"] == first
    # The old value, verbatim — which is the whole point.
    assert before.json()["files"]["compile/challenge.yaml"] == "enabled: false\nmax_rounds: 2\n"
    assert after.json()["files"]["compile/challenge.yaml"] == "enabled: false\nmax_rounds: 3\n"
    # Every other engine file of that version is there too, so a whole version can be restored.
    assert set(before.json()["files"]) == set(SEED)


async def test_undo_is_composed_from_a_version_and_goes_through_the_ordinary_apply(tmp_path):
    """Stated as a flow, because the endpoint's justification is that it adds no primitive:
    the restore is a normal labelled apply, and the repository only ever moves forward."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        base = (await client.get("/v1/engine/history")).json()[0]["sha"]
        await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/challenge.yaml", "content": "enabled: false\nmax_rounds: 9\n"}
                ],
                "label": "an apply somebody regrets",
            },
        )
        old = (await client.get(f"/v1/engine/history/{base}/files")).json()["files"]
        head = (await client.get("/v1/engine/state")).json()["version"]["head"]
        restore = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {
                        "path": "compile/challenge.yaml",
                        "content": old["compile/challenge.yaml"],
                    }
                ],
                "label": "restore challenge rounds",
                "expected_head": head,
            },
        )
        state = (await client.get("/v1/engine/state")).json()
        commits = (await client.get("/v1/engine/history")).json()
    assert restore.status_code == 200
    assert state["values"]["challenge.max_rounds"] == 2
    # Forward only: three commits, none rewritten, the restore is one of them.
    assert [c["label"] for c in commits] == [
        "restore challenge rounds",
        "an apply somebody regrets",
        "engine: initial",
    ]


async def test_an_abbreviated_sha_resolves_and_echoes_back_the_full_one(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        full = (await client.get("/v1/engine/history")).json()[0]["sha"]
        resp = await client.get(f"/v1/engine/history/{full[:8]}/files")
    assert resp.status_code == 200
    assert resp.json()["sha"] == full


@pytest.mark.parametrize(
    "sha",
    [
        "0" * 40,  # well-formed, and not in this repository
        "HEAD",  # git would resolve it; a version is named by its sha
        "HEAD~1",
        "main@{yesterday}",
        "nothexatall",
    ],
)
async def test_a_version_this_repository_does_not_have_is_a_404(tmp_path, sha):
    """Including the revision expressions git itself would happily evaluate: this route
    resolves a commit id, it is not a place where a URL composes a git expression."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/history/" + sha + "/files")
    assert resp.status_code == 404, resp.text


async def test_a_directory_without_a_repo_has_no_versions_to_read(tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/history/" + "0" * 40 + "/files")
    assert resp.status_code == 404
    assert "not a git repository" in resp.json()["detail"]


async def test_a_versions_listing_holds_only_what_the_console_could_write_back(tmp_path):
    """Same addressing rules as a read of the directory: `.gitignore` is not an engine file,
    and neither is a blob that is not UTF-8 text. A listing containing one would offer the
    console content it must refuse on the way back in."""
    engine = _seed_engine(tmp_path)
    (engine / ".gitignore").write_text("local/\n", encoding="utf-8")
    (engine / "notes").mkdir(parents=True, exist_ok=True)
    (engine / "notes" / "binary.md").write_bytes(b"\xff\xfe\x00\x01")
    subprocess.run(["git", "-C", str(engine), "add", "-Af"], check=True)
    subprocess.run(
        ["git", "-C", str(engine), "commit", "-q", "-m", "add a dotfile and a blob"], check=True
    )
    async with _client(str(engine)) as client:
        head = (await client.get("/v1/engine/state")).json()["version"]["head"]
        files = (await client.get(f"/v1/engine/history/{head}/files")).json()["files"]
    assert ".gitignore" not in files
    assert "notes/binary.md" not in files
    assert "recall/recall.yaml" in files


async def test_reading_a_version_touches_neither_head_nor_the_working_tree(tmp_path):
    engine = _seed_engine(tmp_path)
    (engine / "recall" / "recall.yaml").write_text("answer_style: concise\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        before = (await client.get("/v1/engine/state")).json()["version"]
        sha = (await client.get("/v1/engine/history")).json()[0]["sha"]
        await client.get(f"/v1/engine/history/{sha}/files")
        after = (await client.get("/v1/engine/state")).json()
    assert after["version"] == before
    # The uncommitted edit is still uncommitted, and still on disk.
    assert after["version"]["dirty"] is True
    assert (engine / "recall" / "recall.yaml").read_text() == "answer_style: concise\n"


# ------------------------------------------------------------------ apply


async def test_apply_writes_commits_and_reports_effects(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/challenge.yaml", "content": "enabled: true\nmax_rounds: 3\n"},
                    {"path": "recall/recall.yaml", "content": "answer_style: concise\nclaim_cap: 64\n"},
                ],
                "label": "turn the audit on",
            },
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["sha"]) == 40
    effects = {e["key"]: e["apply"] for e in body["effects"]}
    assert effects == {
        "challenge.enabled": "future_compiles",
        "challenge.max_rounds": "future_compiles",
        "recall.answer_style": "hot",
    }
    assert "recall.claim_cap" not in effects, "an unchanged value has no blast radius"
    assert (engine / "compile" / "challenge.yaml").read_text(encoding="utf-8").startswith(
        "enabled: true"
    )


async def test_apply_of_the_contract_document_reports_future_compiles_only(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (
            await client.post(
                "/v1/engine/apply",
                json={
                    "changes": [
                        {
                            "path": "compile/contract.md",
                            "content": "---\nskill_id: demo\nversion: app-v2\n---\n\nRecord decisions and their owners.\n",
                        }
                    ],
                    "label": "contract v2",
                },
            )
        ).json()
    assert body["effects"] == [{"key": "compile.contract", "apply": "future_compiles"}]


async def test_apply_that_changes_nothing_mints_no_commit(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        before = (await client.get("/v1/engine/state")).json()["version"]["head"]
        body = (
            await client.post(
                "/v1/engine/apply",
                json={
                    "changes": [
                        {"path": "intake/intake.yaml", "content": SEED["intake/intake.yaml"]}
                    ],
                    "label": "no-op",
                },
            )
        ).json()
        history = (await client.get("/v1/engine/history")).json()
    assert body["sha"] == before
    assert body["effects"] == []
    assert len(history) == 1


async def test_apply_initializes_a_repository_that_does_not_have_one(tmp_path):
    engine = tmp_path / "engine"
    (engine / "intake").mkdir(parents=True)
    (engine / "intake" / "intake.yaml").write_text("chunk_strategy: semantic\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        body = (
            await client.post(
                "/v1/engine/apply",
                json={
                    "changes": [
                        {"path": "intake/intake.yaml", "content": "chunk_strategy: sentence\n"}
                    ],
                    "label": "first apply",
                },
            )
        ).json()
        history = (await client.get("/v1/engine/history")).json()
    assert len(body["sha"]) == 40
    assert [c["label"] for c in history] == ["first apply"]
    # The identity is the repository's own, so a commit never depends on the machine's config.
    author = subprocess.run(
        ["git", "-C", str(engine), "log", "-1", "--pretty=format:%an <%ae>"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert author == "pneuma-engine <engine@local>"


async def test_apply_can_create_a_new_free_file(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "notes/why.md", "content": "why we chose sentence\n"}],
                "label": "note the reasoning",
            },
        )
    assert resp.status_code == 200
    assert resp.json()["effects"] == []  # a free file governs nothing
    assert (engine / "notes" / "why.md").is_file()


# ------------------------------------------------------------------ apply: rejections


@pytest.mark.parametrize(
    "path",
    [
        "../escape.md",
        "/etc/passwd",
        "recall/../../escape.yaml",
        "a/../../b.md",
        ".env",
        ".git/config",
        "nested/.env",
        "",
    ],
)
async def test_apply_refuses_paths_that_leave_or_hide(tmp_path, path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={"changes": [{"path": path, "content": "x\n"}], "label": "nope"},
        )
    assert resp.status_code == 400, resp.text
    assert not (tmp_path / "escape.md").exists()
    assert not (tmp_path.parent / "escape.yaml").exists()


async def test_apply_refuses_a_symlink_that_points_out_of_the_engine(tmp_path):
    engine = _seed_engine(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (engine / "away").symlink_to(outside, target_is_directory=True)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={"changes": [{"path": "away/x.md", "content": "x\n"}], "label": "nope"},
        )
    assert resp.status_code == 400
    assert not (outside / "x.md").exists()


async def test_apply_refuses_api_key_shaped_content(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "notes/keys.md", "content": "key: sk-or-v1-0123456789abcdef0123\n"}
                ],
                "label": "oops",
            },
        )
    assert resp.status_code == 400
    assert "API-key-shaped" in resp.json()["detail"]
    assert not (engine / "notes").exists(), "a rejected apply writes nothing at all"


async def test_apply_refuses_an_unknown_key_in_a_stage_file(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "recall/recall.yaml", "content": "answer_stile: concise\n"}
                ],
                "label": "typo",
            },
        )
    assert resp.status_code == 400
    assert "unknown key" in resp.json()["detail"]
    assert "answer_style" in resp.json()["detail"]


async def test_apply_refuses_a_value_outside_a_knobs_enum(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": "answer_style: shouty\n"}],
                "label": "bad enum",
            },
        )
    assert resp.status_code == 400
    assert "must be one of" in resp.json()["detail"]


async def test_apply_refuses_a_wrongly_typed_value(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/challenge.yaml", "content": "enabled: maybe\n"}
                ],
                "label": "bad bool",
            },
        )
    assert resp.status_code == 400
    assert "true or false" in resp.json()["detail"]


async def test_codex_a_fractional_int_knob_is_refused_before_it_can_be_committed(tmp_path):
    """codex review #5: `claim_cap: 1.5` passed apply's type check and only failed on the
    NEXT /state, after it had been committed — the console breaking itself one apply later."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        before = (await client.get("/v1/engine/state")).json()["version"]["head"]
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "recall/recall.yaml", "content": "answer_style: concise\nclaim_cap: 1.5\n"}
                ],
                "label": "fractional cap",
            },
        )
        after = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 400, resp.text
    assert "whole number" in resp.json()["detail"]
    assert after["version"]["head"] == before
    assert after["values"]["recall.claim_cap"] == 64


@pytest.mark.parametrize(
    "value", ["1.5", "true", '"32"', "[]"]
)
async def test_apply_refuses_a_non_integer_for_an_int_knob(tmp_path, value):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": f"claim_cap: {value}\n"}],
                "label": "bad int",
            },
        )
    assert resp.status_code == 400, resp.text


def test_the_candidate_state_is_checked_by_the_same_resolution_state_uses(tmp_path):
    """The total check, on its own: a candidate directory that would not build a `Settings`.

    Per-knob checks are the fast, specific rejections; this one is what makes "apply
    succeeded, then /state was 400" structurally unreachable rather than a bug to remember.
    It runs over the whole candidate directory (disk + the pending changes) through the same
    `engine_overrides` → `Settings` path the state endpoint resolves with.
    """
    from pneuma_knowledge_service.engine.files import EngineFileError
    from pneuma_knowledge_service.engine.resolve import assert_candidate_settings

    engine = _seed_engine(tmp_path)
    assert_candidate_settings(engine, {"recall/recall.yaml": "claim_cap: 80\n"}, {})
    with pytest.raises(EngineFileError, match="do not validate as settings"):
        assert_candidate_settings(engine, {"recall/recall.yaml": "answer_style: shouty\n"}, {})


async def test_an_untouched_broken_file_does_not_block_an_unrelated_apply(tmp_path):
    """The total check reads files it is not replacing leniently, on purpose.

    Otherwise one file broken by hand would freeze every knob in the directory — the opposite
    of the repair path the console needs.
    """
    engine = _seed_engine(tmp_path)
    (engine / "compile" / "challenge.yaml").write_text("enabled: [oops\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": "claim_cap: 80\n"}],
                "label": "unrelated knob",
            },
        )
    assert resp.status_code == 200, resp.text


async def test_an_empty_string_knob_is_accepted_quoted_and_refused_as_null(tmp_path):
    """The service side of codex review #7: `""` is a supported value, `key:` is not.

    Empty `rerank_model` is how reranking is turned off, so the console must be able to write
    it — which it can only do by quoting (`rerank_model: ""`). Bare `rerank_model:` is YAML
    null and stays refused, so the two spellings cannot be confused for each other.
    """
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        ok = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": 'rerank_model: ""\n'}],
                "label": "no reranking",
            },
        )
        state = (await client.get("/v1/engine/state")).json()
        bad = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": "rerank_model:\n"}],
                "label": "null reranking",
            },
        )
    assert ok.status_code == 200, ok.text
    assert state["values"]["recall.rerank_model"] == ""
    assert bad.status_code == 400
    assert "must be a string" in bad.json()["detail"]


async def test_apply_refuses_malformed_yaml_so_the_console_cannot_break_itself(tmp_path):
    engine = _seed_engine(tmp_path)
    original = (engine / "recall" / "recall.yaml").read_text(encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": "claim_cap: [oops\n"}],
                "label": "broken",
            },
        )
    assert resp.status_code == 400
    assert (engine / "recall" / "recall.yaml").read_text(encoding="utf-8") == original


async def test_a_bad_yaml_refusal_says_what_to_do_before_it_quotes_the_parser(tmp_path):
    """VERIFY #12: the 409 stale-head refusal read like a product (what happened, why, what
    next) and the 400 next to it handed back raw PyYAML — `expected ',' or ']'`, `flow
    sequence`, `stream end`. Same write path, two different levels of maturity.

    The parser's precision is kept, and it now sits behind one actionable line in both
    languages: the file, what is wrong, and where to look."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/challenge.yaml", "content": "enabled: false\nmax_rounds: [broken\n"}
                ],
                "label": "a paste that lost a bracket",
            },
        )
        state = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    first, *rest = detail.splitlines()
    # The file, in the first line, where an error callout will show it.
    assert first.startswith("compile/challenge.yaml is not valid YAML")
    assert "line and column below" in first
    assert "不是合法的 YAML" in detail and "行 / 列" in detail
    # And the parser's own text, kept: the line and column are the actionable part.
    assert any("line 2" in line and "column" in line for line in rest), detail
    assert state["version"]["dirty"] is False, "a rejected apply writes nothing"


async def test_apply_refuses_a_non_string_overlay_clause(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "prompts/overlays.yaml", "content": "overlays:\n  a.b:\n    c: d\n"}
                ],
                "label": "bad overlay",
            },
        )
    assert resp.status_code == 400
    assert "whole-clause replacement" in resp.json()["detail"]


async def test_apply_can_repair_a_file_somebody_broke_by_hand(tmp_path):
    """The old side of the effect comparison is forgiving on purpose: a file broken outside
    the console must not make the change that fixes it un-appliable."""
    engine = _seed_engine(tmp_path)
    (engine / "recall" / "recall.yaml").write_text("claim_cap: [oops\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "recall/recall.yaml", "content": "answer_style: concise\nclaim_cap: 64\n"}
                ],
                "label": "repair",
            },
        )
    assert resp.status_code == 200, resp.text
    effects = {e["key"] for e in resp.json()["effects"]}
    assert effects == {"recall.answer_style", "recall.claim_cap"}
    # And the repaired engine reads back cleanly, so the console is out of the dead end.
    async with _client(str(engine)) as client:
        state = await client.get("/v1/engine/state")
    assert state.status_code == 200
    assert state.json()["values"]["recall.claim_cap"] == 64


async def test_codex_the_console_written_overlay_file_is_accepted_verbatim(tmp_path):
    """The other half of the overlay contract (codex review #4).

    `apps/web/tests/contract/overlays.expected.yaml` is the exact file the console's
    `engineYaml` helpers produce for add → edit → remove over the scaffold's own
    `prompts/overlays.yaml`; the web test pins those bytes, and this one requires the service
    to accept them. The audit's failure was invisible precisely because each surface only ever
    tested against its own idea of the format.
    """
    contract = (
        Path(__file__).parents[3] / "apps" / "web" / "tests" / "contract" / "overlays.expected.yaml"
    )
    assert contract.is_file(), f"the shared overlay contract fixture is missing: {contract}"
    written = contract.read_text(encoding="utf-8")
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "prompts/overlays.yaml", "content": written}],
                "label": "override the citation clause",
            },
        )
        state = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 200, resp.text
    assert resp.json()["effects"] == [{"key": "prompts.overlays", "apply": "restart"}]
    assert state["values"]["prompts.overlays"] == {
        "gate.claim_without_provenance": 'Every claim cites its blocks: "{preview}…" (c:{anchor}).\n'
    }


async def test_apply_refuses_an_overlay_key_the_catalog_does_not_have(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {
                        "path": "prompts/overlays.yaml",
                        "content": 'overlays:\n  not.a.real.key: "x"\n',
                    }
                ],
                "label": "bad key",
            },
        )
    assert resp.status_code == 400
    assert "not prompt-catalog keys" in resp.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"changes": [], "label": "empty"},
        {"changes": [{"path": "a.md", "content": "x"}], "label": ""},
        {"changes": [{"path": "a.md", "content": "x"}], "label": "l" * 61},
    ],
)
async def test_apply_validates_the_request_body(tmp_path, body):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post("/v1/engine/apply", json=body)
    assert resp.status_code == 422


# ------------------------------------------------------------------ apply: concurrency
#
# codex review #3: the console sends whole files, so two tabs composing against the same read
# meant last-write-wins with no sign of it — and nothing serialized the write/commit sequence
# across requests either.


async def test_codex_two_tabs_on_one_read_do_not_silently_revert_each_other(tmp_path):
    """The audit's reproduction: tab A raises max_rounds, tab B saves its older snapshot."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        read = (await client.get("/v1/engine/state")).json()
        head = read["version"]["head"]
        tab_a = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/challenge.yaml", "content": "enabled: false\nmax_rounds: 5\n"}
                ],
                "label": "tab a: more rounds",
                "expected_head": head,
            },
        )
        tab_b = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "compile/challenge.yaml", "content": "enabled: true\nmax_rounds: 2\n"}
                ],
                "label": "tab b: enable the audit",
                "expected_head": head,
            },
        )
        after = (await client.get("/v1/engine/state")).json()
    assert tab_a.status_code == 200, tab_a.text
    assert tab_b.status_code == 409, tab_b.text
    detail = tab_b.json()["detail"]
    assert head in detail and tab_a.json()["sha"] in detail, "the 409 names both versions"
    assert after["values"]["challenge.max_rounds"] == 5, "tab A's version stands"


async def test_apply_without_an_expected_head_keeps_working(tmp_path):
    """No precondition is a legitimate request: the CLI has no read to be stale."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": "claim_cap: 80\n"}],
                "label": "no precondition",
            },
        )
    assert resp.status_code == 200, resp.text


async def test_apply_head_precondition_on_a_repository_without_commits(tmp_path):
    engine = tmp_path / "engine"
    engine.mkdir()
    async with _client(str(engine)) as client:
        stale = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "notes/a.md", "content": "a\n"}],
                "label": "expects a version",
                "expected_head": "0" * 40,
            },
        )
        fresh = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "notes/a.md", "content": "a\n"}],
                "label": "expects nothing yet",
                "expected_head": None,
            },
        )
    assert stale.status_code == 409
    assert "no commit" in stale.json()["detail"]
    assert fresh.status_code == 200, fresh.text


async def test_applies_are_mutually_exclusive_across_requests(tmp_path, monkeypatch):
    """Two concurrent applies never run inside each other's write-then-commit window."""
    from pneuma_knowledge_service.api.routes import engine as engine_routes

    engine = _seed_engine(tmp_path)
    real = engine_routes.apply_changes
    inflight = 0
    overlaps = 0

    def instrumented(*args, **kwargs):
        nonlocal inflight, overlaps
        inflight += 1
        if inflight > 1:
            overlaps += 1
        try:
            time.sleep(0.05)  # a real apply is filesystem + several git subprocesses
            return real(*args, **kwargs)
        finally:
            inflight -= 1

    monkeypatch.setattr(engine_routes, "apply_changes", instrumented)
    async with _client(str(engine)) as client:
        first, second = await asyncio.gather(
            client.post(
                "/v1/engine/apply",
                json={
                    "changes": [{"path": "notes/a.md", "content": "a\n"}],
                    "label": "first",
                },
            ),
            client.post(
                "/v1/engine/apply",
                json={
                    "changes": [{"path": "notes/b.md", "content": "b\n"}],
                    "label": "second",
                },
            ),
        )
        history = (await client.get("/v1/engine/history")).json()
    assert overlaps == 0, "two applies were inside the critical section at once"
    assert first.status_code == 200 and second.status_code == 200
    # Two distinct versions, each holding exactly its own file.
    assert sorted(c["files"][0] for c in history[:2]) == ["notes/a.md", "notes/b.md"]


# ------------------------------------------------------------------ apply: what it commits
#
# codex review #2: apply validated `changes` but committed with `git add -A`, so anything a
# developer had left modified or untracked rode along into the labelled version without
# passing a single check — including a dotfile /state would never show back.


async def test_codex_a_preexisting_untracked_file_is_not_carried_into_the_version(tmp_path):
    """The audit's reproduction: an untracked `.env` beside one legitimate apply.

    The commit used to contain both, and /state's dotfile filter meant nobody could see it.
    """
    engine = _seed_engine(tmp_path)
    (engine / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-real-looking\n", encoding="utf-8")
    (engine / "stray.md").write_text("a note nobody reviewed\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "recall/recall.yaml", "content": "claim_cap: 80\n"}],
                "label": "raise the claim budget",
            },
        )
        history = (await client.get("/v1/engine/history")).json()
        state = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 200, resp.text
    assert history[0]["files"] == ["recall/recall.yaml"], "only the reviewed file is versioned"
    tracked = subprocess.run(
        ["git", "-C", str(engine), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()
    assert ".env" not in tracked and "stray.md" not in tracked
    # And the console does not pretend the tree is clean: the leftovers are still there.
    assert state["version"]["dirty"] is True
    assert (engine / ".env").is_file()


async def test_apply_does_not_carry_a_hand_broken_file_into_an_unrelated_version(tmp_path):
    """A knob edit must not smuggle a broken neighbour past its own validation."""
    engine = _seed_engine(tmp_path)
    (engine / "compile" / "challenge.yaml").write_text("enabled: [oops\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "intake/intake.yaml", "content": "chunk_strategy: semantic\n"}
                ],
                "label": "switch chunking",
            },
        )
        history = (await client.get("/v1/engine/history")).json()
    assert resp.status_code == 200, resp.text
    assert history[0]["files"] == ["intake/intake.yaml"]
    committed = subprocess.run(
        ["git", "-C", str(engine), "show", "HEAD:compile/challenge.yaml"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert committed == SEED["compile/challenge.yaml"], "the broken file stayed uncommitted"


# ------------------------------------------------------------------ apply: path aliasing
#
# codex review #1: `engine_path()` resolves an equivalent spelling to the real file, but the
# checks used to run against the request's own string — so an alias reached the real stage
# file as an unrecognized "free file" and skipped YAML, unknown-key and type validation.


async def test_codex_alias_path_with_malformed_yaml_is_refused_and_leaves_head_alone(tmp_path):
    """The exact reproduction from the audit: `./recall/recall.yaml` + broken YAML.

    It returned 200 and committed unreadable YAML into the real file, after which /state was
    400 and the whole console was unusable.
    """
    engine = _seed_engine(tmp_path)
    original = (engine / "recall" / "recall.yaml").read_text(encoding="utf-8")
    async with _client(str(engine)) as client:
        before = (await client.get("/v1/engine/state")).json()["version"]["head"]
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": "./recall/recall.yaml", "content": "not: [valid"}],
                "label": "codex e2e: alias malformed yaml",
            },
        )
        after = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 400, resp.text
    assert "recall/recall.yaml" in resp.json()["detail"]
    assert (engine / "recall" / "recall.yaml").read_text(encoding="utf-8") == original
    assert after["version"]["head"] == before
    assert after["version"]["dirty"] is False


@pytest.mark.parametrize(
    "alias",
    [
        "./recall/recall.yaml",
        "recall//recall.yaml",
        "./recall/./recall.yaml",
        "recall/recall.yaml/",
    ],
)
async def test_apply_refuses_a_non_canonical_spelling_of_a_real_file(tmp_path, alias):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [{"path": alias, "content": "claim_cap: 80\n"}],
                "label": "alias",
            },
        )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "recall/recall.yaml" in detail
    # Refused for the spelling, not by luck: the content itself is perfectly valid.
    assert (engine / "recall" / "recall.yaml").read_text(encoding="utf-8") == SEED[
        "recall/recall.yaml"
    ]


async def test_apply_refuses_two_spellings_of_the_same_target_in_one_request(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "recall/recall.yaml", "content": "claim_cap: 80\n"},
                    {"path": "./recall/recall.yaml", "content": "claim_cap: 90\n"},
                ],
                "label": "two spellings",
            },
        )
        history = (await client.get("/v1/engine/history")).json()
    assert resp.status_code == 400, resp.text
    assert len(history) == 1, "nothing was committed"


def test_validate_returns_the_canonical_set_it_checked(tmp_path):
    """The unit-level guarantee: the caller writes what validate handed back."""
    from pneuma_knowledge_service.engine.apply import Change as C
    from pneuma_knowledge_service.engine.apply import validate

    engine = _seed_engine(tmp_path)
    checked = validate(engine, [C(path="recall/recall.yaml", content="claim_cap: 80\n")])
    assert [c.path for c in checked] == ["recall/recall.yaml"]


async def test_apply_refuses_the_same_path_twice(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {"path": "recall/recall.yaml", "content": "claim_cap: 80\n"},
                    {"path": "recall/recall.yaml", "content": "claim_cap: 90\n"},
                ],
                "label": "ambiguous",
            },
        )
    assert resp.status_code == 400
    assert "twice" in resp.json()["detail"]
