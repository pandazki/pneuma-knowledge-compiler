"""The demo's docker path, end to end: generate → start → restore → serve.

Opt-in, because it builds two images and starts six containers (minutes, gigabytes). Enable
with PNEUMA_DEMO_DOCKER_TEST=1; without it, and without a reachable docker daemon, the test
skips with the reason stated — the same discipline the service package's integration tests
follow (probe, skip only when unreachable).

What it proves that the keyless generation tests cannot: the compose `console` profile really
serves this project — the SPA, the API through nginx's proxy, and the Engine Console's routes
over the generated engine/ — and `./app.py restore` really loads the shipped library with no
API key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INIT_PATH = ROOT / "scaffold" / "init.py"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    return (
        subprocess.run(
            ["docker", "info"], capture_output=True, text=True
        ).returncode
        == 0
    )


def _get(url: str) -> object:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _env_value(project: Path, key: str) -> str:
    for line in (project / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{key} missing from the generated .env")


@pytest.mark.skipif(
    os.environ.get("PNEUMA_DEMO_DOCKER_TEST") != "1",
    reason="opt-in: set PNEUMA_DEMO_DOCKER_TEST=1 (builds images and starts containers)",
)
def test_demo_starts_and_serves_the_shipped_library(tmp_path):
    if not _docker_ready():
        pytest.skip("docker daemon unreachable")

    project = tmp_path / "demo"
    generated = subprocess.run(
        [sys.executable, str(INIT_PATH), "--demo", "--target", str(project)],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    try:
        assert generated.returncode == 0, generated.stderr or generated.stdout
        web = _env_value(project, "PNEUMA_APP_WEB_PORT")
        assert f"http://127.0.0.1:{web}" in generated.stdout, "the address must be echoed"

        base = f"http://127.0.0.1:{web}"
        assert _get(f"{base}/healthz")["status"] == "ok"
        # Everything reachable through nginx on the web port: same origin, no CORS surface.
        assert _get(f"{base}/v1/users") == [_env_value(project, "PNEUMA_APP_USER_ID")]
        summary = _get(f"{base}/v1/users/{_env_value(project, 'PNEUMA_APP_USER_ID')}/summary")
        assert summary["sources"] > 100 and summary["documents"] > 1 and summary["claims"] > 100
        assert summary["jobs"] == 0, "a restored library leaves nothing queued"

        # The Engine Console's routes serve the generated engine, committed and clean.
        state = _get(f"{base}/v1/engine/state")
        assert "compile/contract.md" in state["files"]
        assert state["version"]["head"] and state["version"]["dirty"] is False
        assert state["values"]["intake.chunk_strategy"] == "sentence"
        assert [stage["id"] for stage in _get(f"{base}/v1/engine/schema")["stages"]][0] == "intake"

        # The SPA itself is served, and its shell is never cached (hash-routed app).
        with urllib.request.urlopen(f"{base}/index.html", timeout=30) as response:
            assert "no-cache" in response.headers.get("Cache-Control", "")
            assert b"<div id=\"root\">" in response.read()
    finally:
        if (project / "docker-compose.yml").is_file():
            subprocess.run(
                ["docker", "compose", "--profile", "console", "down", "-v", "--rmi", "local"],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=900,
            )
