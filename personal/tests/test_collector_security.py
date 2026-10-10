"""Adversarial enrollment, receipt, and bootstrap checks use only synthetic material."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Barrier, Lock, Thread
import time
from types import SimpleNamespace

import pytest

from test_agent_sessions import provider_files, sessions


SPEC = importlib.util.spec_from_file_location(
    "collector_security_subject", Path(__file__).parents[1] / "collector" / "collector.py"
)
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
POLICY = {
    "processor_id": "agent-sessions",
    "scope": {"projects": ["all"], "harnesses": ["codex", "claude-code"], "since": None},
    "interval_seconds": 300,
}


def test_concurrent_invitation_retries_keep_one_persisted_device_key(tmp_path, monkeypatch):
    start = Barrier(2)
    guard = Lock()
    generated = []
    claims = []

    def generate_key(_size):
        with guard:
            value = "synthetic-device-secret-" + str(len(generated)).zfill(32)
            generated.append(value)
        # Widen the read-before-save race: without the enrollment lock both callers
        # create a key before either can save it or claim the invitation.
        time.sleep(0.05)
        return value

    def claim(_base, path, *, body):
        assert path == "/v1/enroll"
        persisted = collector.read(tmp_path / "device.json")
        assert persisted["device_id"] == body["device_id"]
        assert persisted["device_secret"] == body["device_secret"]
        with guard:
            claims.append(deepcopy(body))
        return {
            "device_id": body["device_id"], "library_id": "synthetic-library",
            "policy": POLICY, "status": "active",
        }

    monkeypatch.setattr(collector.secrets, "token_urlsafe", generate_key)
    monkeypatch.setattr(collector, "request", claim)

    def enroll():
        start.wait(timeout=5)
        return collector.enroll(tmp_path, "https://synthetic.example", "synthetic-invitation")

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(enroll) for _ in range(2)]
        results = [future.result(timeout=10) for future in futures]
    assert len(generated) == 1
    assert claims[0] == claims[1]
    assert results[0]["device_secret"] == results[1]["device_secret"]
    assert collector.read(tmp_path / "device.json")["device_secret"] == generated[0]
    assert (tmp_path / "device.json").stat().st_mode & 0o777 == 0o600
    assert "synthetic-invitation" not in (tmp_path / "device.json").read_text()


@pytest.fixture
def enrolled(tmp_path, provider_files, monkeypatch):
    snapshot = sessions.capture_snapshot("claude-code", provider_files.claude_file, provider_files.project)
    collector.save(tmp_path / "device.json", {
        "url": "https://synthetic.example", "device_id": "synthetic-device",
        "device_secret": "synthetic-secret", "label": "Synthetic device",
        "library_id": "synthetic-library", "policy": POLICY, "status": "active",
    })
    module = SimpleNamespace(
        iter_snapshots=lambda *_, **__: iter([deepcopy(snapshot)]),
        claude_session_roots=lambda _: [], codex_session_roots=lambda _: [],
        decode_snapshot=sessions.decode_snapshot, excluded_project=sessions.excluded_project,
        timestamp=sessions.timestamp,
    )
    monkeypatch.setattr(collector, "converter", lambda _: module)
    return tmp_path, snapshot


@pytest.mark.parametrize("status,expected", [(403, "revoked"), (401, "unauthorized")])
def test_revocation_stops_scanning_and_stays_stopped_while_offline(enrolled, monkeypatch, status, expected):
    directory, _snapshot = enrolled
    calls = []

    def rejected(_base, path, **_kwargs):
        calls.append(path)
        raise collector.CloudHTTPError(status)

    def never_scan(_runtime):
        pytest.fail("a revoked or unauthorized device must not load the scanner")

    monkeypatch.setattr(collector, "request", rejected)
    monkeypatch.setattr(collector, "converter", never_scan)
    result = collector.collect_once(directory, directory)
    assert result["status"] == expected
    assert collector.read(directory / "device.json")["status"] == expected
    assert calls == ["/v1/device/policy"]
    assert not (directory / "outbox").exists()

    def offline(*_args, **_kwargs):
        raise ValueError("synthetic network outage")

    monkeypatch.setattr(collector, "request", offline)
    assert collector.collect_once(directory, directory)["status"] == expected
    assert not (directory / "outbox").exists()


@pytest.mark.parametrize("conflict", [
    {"library_id": "different-library"}, {"device_id": "different-device"},
    {"sequence": 0}, {"sequence": True},
])
def test_wrong_tenant_device_or_commit_receipt_never_acknowledges_material(enrolled, monkeypatch, conflict):
    directory, snapshot = enrolled

    def wrong_receipt(_base, path, **kwargs):
        if path.endswith("policy"):
            return {"policy": POLICY, "status": "active"}
        assert path == "/v1/device/snapshots"
        payload = kwargs["body"]
        return {
            "sha256": hashlib.sha256(payload).hexdigest(), "snapshot_id": snapshot["snapshot_id"],
            "library_id": "synthetic-library", "device_id": "synthetic-device", "sequence": 1,
            **conflict,
        }

    monkeypatch.setattr(collector, "request", wrong_receipt)
    result = collector.collect_once(directory, directory)
    assert result["uploaded"] == 0 and result["pending"] == 1
    assert "receipt does not match" in result["errors"][0]
    assert collector.read(directory / "publisher.json", {"sent": {}})["sent"] == {}
    pending = directory / "outbox" / (snapshot["snapshot_id"] + ".json")
    assert pending.is_file()
    assert json.loads(pending.read_bytes())["snapshot_id"] == snapshot["snapshot_id"]


@contextmanager
def bootstrap_server(marker: Path, *, redirect=False):
    requested = []
    code = f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n".encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requested.append(self.path)
            if redirect and self.path == "/collector.py":
                self.send_response(302)
                self.send_header("Location", "/unexpected-redirect")
                self.end_headers()
                return
            payload = json.dumps({"version": 1, "files": {"collector.py": "0" * 64}}).encode() \
                if self.path == "/release.json" else code
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requested
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("redirect", [False, True])
def test_bootstrap_refuses_bad_digest_or_redirect_before_executing_collector(tmp_path, redirect):
    marker = tmp_path / "executed"
    bin_path = tmp_path / "bin"
    bin_path.mkdir()
    (bin_path / "python3").symlink_to(sys.executable)
    environment = {**os.environ, "PATH": str(bin_path) + os.pathsep + os.environ.get("PATH", "")}
    installer = Path(__file__).parents[1] / "collector" / "install.sh"
    with bootstrap_server(marker, redirect=redirect) as (base, requested):
        result = subprocess.run(
            ["/bin/sh", str(installer), "--url", base, "--invite", "synthetic-one-time-invitation"],
            env=environment, capture_output=True, text=True, timeout=15,
        )
    assert result.returncode != 0
    assert not marker.exists()
    if redirect:
        assert requested == ["/collector.py"]
    else:
        assert requested == ["/collector.py", "/release.json"]
        assert "Collector bootstrap digest mismatch" in result.stderr
