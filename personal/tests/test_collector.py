"""A device journals immutable material and retries enrollment/upload without data loss."""

from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_agent_sessions import provider_files, sessions

SPEC = importlib.util.spec_from_file_location("test_native_collector", Path(__file__).parents[1] / "collector" / "collector.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)
POLICY = {"processor_id": "agent-sessions", "scope": {"projects": ["all"], "harnesses": ["codex", "claude-code"], "since": None},
          "interval_seconds": 300}


def test_uncertain_enrollment_reuses_persisted_identity_and_private_permissions(tmp_path, monkeypatch):
    calls = []
    def request(base, path, **kwargs):
        calls.append(kwargs["body"])
        if len(calls) == 1:
            raise ValueError("lost response")
        return {"device_id": kwargs["body"]["device_id"], "library_id": "lib-synthetic", "policy": POLICY}
    monkeypatch.setattr(collector, "request", request)
    with pytest.raises(ValueError):
        collector.enroll(tmp_path, "https://synthetic.example", "invitation")
    collector.enroll(tmp_path, "https://synthetic.example", "invitation")
    assert calls[0] == calls[1]
    config_path = tmp_path / "device.json"
    assert config_path.stat().st_mode & 0o777 == 0o600
    assert "invitation" not in config_path.read_text()


@pytest.fixture
def enrolled(tmp_path, provider_files, monkeypatch):
    snapshot = sessions.capture_snapshot("claude-code", provider_files.claude_file, provider_files.project)
    collector.save(tmp_path / "device.json", {"url": "https://synthetic.example", "device_id": "dev_synthetic",
                   "device_secret": "synthetic-secret", "label": "Synthetic device", "policy": POLICY,
                   "status": "active", "library_id": "lib-synthetic"})
    monkeypatch.setattr(collector, "converter", lambda _: SimpleNamespace(
        iter_snapshots=lambda *_, **__: iter([deepcopy(snapshot)]), claude_session_roots=lambda _: [],
        codex_session_roots=lambda _: [], decode_snapshot=sessions.decode_snapshot,
        excluded_project=sessions.excluded_project, timestamp=sessions.timestamp))
    return tmp_path, snapshot


def test_upload_response_loss_retries_exact_journal_even_if_origin_changes(enrolled, monkeypatch):
    directory, snapshot = enrolled
    uploads = []
    def request(base, path, **kwargs):
        if path.endswith("policy"):
            return {"policy": POLICY, "status": "active"}
        data = kwargs["body"]
        uploads.append(data)
        if len(uploads) == 1:
            raise ValueError("response lost after cloud commit")
        return {"snapshot_id": json.loads(data)["snapshot_id"], "sha256": hashlib.sha256(data).hexdigest(),
                "device_id": "dev_synthetic", "library_id": "lib-synthetic", "sequence": 1}
    monkeypatch.setattr(collector, "request", request)
    first = collector.collect_once(directory, directory)
    assert first["pending"] == 1 and first["uploaded"] == 0
    snapshot["origin"]["git_remote"] = "https://example.com/new-name"
    second = collector.collect_once(directory, directory)
    assert second["uploaded"] == 1 and second["pending"] == 0
    assert uploads[0] == uploads[1]
    assert collector.collect_once(directory, directory)["uploaded"] == 0
    assert len(uploads) == 2


def test_offline_scan_keeps_material_and_pause_never_uploads_pending(enrolled, monkeypatch):
    directory, snapshot = enrolled
    def offline(*args, **kwargs):
        raise ValueError("offline")
    monkeypatch.setattr(collector, "request", offline)
    assert collector.collect_once(directory, directory)["pending"] == 1
    calls = []
    def paused(base, path, **kwargs):
        calls.append(path)
        return {"policy": POLICY, "status": "paused"}
    monkeypatch.setattr(collector, "request", paused)
    assert collector.collect_once(directory, directory)["status"] == "paused"
    assert calls == ["/v1/device/policy"]
    assert len(list((directory / "outbox").glob("*.json"))) == 1


@pytest.mark.parametrize("scope", [{"projects": [], "harnesses": ["codex"]},
                                    {"projects": ["all", "/work"], "harnesses": ["codex"]},
                                    {"projects": ["all"], "harnesses": ["unknown"]}])
def test_invalid_scope_is_refused_without_widening(scope):
    with pytest.raises(ValueError):
        collector.checked_scope({"scope": scope})


@pytest.mark.parametrize("restriction", ["project", "harness", "since", "exclude"])
def test_policy_narrowing_holds_queued_bytes_without_blocking_allowed_material(
        enrolled, monkeypatch, restriction):
    directory, queued = enrolled
    policy = deepcopy(POLICY)
    session = sessions.decode_snapshot(queued)
    permitted = replace(session, session_id="synthetic-permitted-session")
    if restriction == "project":
        # An exact parent path must not authorize the queued child project.
        permitted = replace(permitted, project=session.project.parent)
        policy["scope"]["projects"] = [str(permitted.project)]
    elif restriction == "harness":
        permitted = replace(permitted, provider="codex")
        policy["scope"]["harnesses"] = ["codex"]
    elif restriction == "since":
        policy["scope"]["since"] = "2026-09-02T00:00:00+00:00"
        permitted = replace(permitted, turns=[
            {**turn, "at": (sessions.timestamp(turn["at"]) + timedelta(days=1)).isoformat()}
            for turn in session.turns
        ], last_at=session.last_at + timedelta(days=1))
    else:
        permitted = replace(permitted, project=session.project.with_name("allowed-project"))
        policy["exclude"] = [str(session.project) + "/**"]
    allowed = sessions.session_snapshot(permitted)
    discovered = [queued]
    monkeypatch.setattr(collector, "converter", lambda _: SimpleNamespace(
        iter_snapshots=lambda *_, **__: iter(deepcopy(discovered)), claude_session_roots=lambda _: [],
        codex_session_roots=lambda _: [], decode_snapshot=sessions.decode_snapshot,
        excluded_project=sessions.excluded_project, timestamp=sessions.timestamp))

    def offline(*_args, **_kwargs):
        raise ValueError("synthetic network outage")

    monkeypatch.setattr(collector, "request", offline)
    assert collector.collect_once(directory, directory)["pending"] == 1
    path = directory / "outbox" / (queued["snapshot_id"] + ".json")
    retained = path.read_bytes()
    discovered[:] = [allowed]
    uploaded = []

    def online(_base, endpoint, **kwargs):
        if endpoint.endswith("policy"):
            return {"policy": policy, "status": "active"}
        payload = kwargs["body"]
        value = json.loads(payload)
        uploaded.append(payload)
        return {"snapshot_id": value["snapshot_id"], "sha256": hashlib.sha256(payload).hexdigest(),
                "device_id": "dev_synthetic", "library_id": "lib-synthetic", "sequence": len(uploaded)}

    monkeypatch.setattr(collector, "request", online)
    narrowed = collector.collect_once(directory, directory)
    assert narrowed["uploaded"] == 1 and narrowed["held"] == 1 and narrowed["pending"] == 1
    assert narrowed["errors"] == []
    assert [json.loads(payload)["snapshot_id"] for payload in uploaded] == [allowed["snapshot_id"]]
    assert path.read_bytes() == retained
    assert queued["snapshot_id"] not in collector.read(directory / "publisher.json")["sent"]

    # The held item remains silent on later polls and can resume with its exact
    # original bytes after the Owner explicitly restores its authorization.
    assert collector.collect_once(directory, directory)["held"] == 1
    assert len(uploaded) == 1 and path.read_bytes() == retained
    policy = deepcopy(POLICY)
    restored = collector.collect_once(directory, directory)
    assert restored["uploaded"] == 1 and restored["held"] == 0 and restored["pending"] == 0
    assert uploaded[1] == retained
    assert collector.read(directory / "publisher.json")["sent"][queued["snapshot_id"]] == hashlib.sha256(retained).hexdigest()
