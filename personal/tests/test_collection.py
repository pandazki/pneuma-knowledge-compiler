"""Source configuration and collection observations are isolated from evidence identity."""

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from pkc_personal import collection, sync
from pkc_personal.collection_routes import build_router
from pkc_personal.library import Library, Watch, watch_project
from test_agent_sessions import provider_files, sessions


@pytest.fixture
def client(home, make_library):
    library = make_library()
    app = FastAPI()
    app.include_router(build_router(home, library))
    return TestClient(app, base_url="http://127.0.0.1"), library


def test_configuration_is_library_local_and_credentials_are_write_only(home, make_library, monkeypatch):
    one, two = make_library(), make_library("second")
    calls = []
    def cloud(value, path, **kwargs):
        calls.append((value, path, kwargs))
        return {"protocol": "pneuma.collector/v1", "status": "ok"} if path == "/v1/health" else {}
    monkeypatch.setattr(collection, "cloud_request", cloud)
    collection.set_cloud(one, "https://synthetic.example/", "synthetic-host-token")
    data = collection.document(home, one)
    assert data["cloud"] == {"url": "https://synthetic.example", "configured": True}
    assert "synthetic-host-token" not in json.dumps(data)
    assert collection.document(home, two)["cloud"]["configured"] is False
    assert (one.path / "collection.json").stat().st_mode & 0o777 == 0o600
    assert all("lib-notes" in path or path == "/v1/health" for _, path, _ in calls)


@pytest.mark.parametrize("url", ["http://external.example", "https://x.example/path", "https://user:secret@x.example",
                                  "https://x.example/?secret=token", "https://x.example/#token"])
def test_cloud_url_refuses_insecure_or_credential_bearing_origins(url):
    with pytest.raises(ValueError):
        collection.validate_cloud_url(url)


def test_failed_cloud_configuration_does_not_replace_working_credentials(home, make_library, monkeypatch):
    library = make_library()
    original = {"cloud": {"url": "https://old.example", "host_token": "old-synthetic"}}
    collection.save_config(library, original)
    def fail(*args, **kwargs):
        raise ValueError("cloud unavailable")
    monkeypatch.setattr(collection, "cloud_request", fail)
    with pytest.raises(ValueError):
        collection.set_cloud(library, "https://new.example", "new-synthetic")
    assert collection.read_config(library) == original


def test_invitation_is_scoped_and_does_not_put_host_credential_in_command(home, make_library, monkeypatch):
    library = make_library()
    collection.save_config(library, {"cloud": {"url": "https://synthetic.example", "host_token": "host-secret"}})
    calls = []
    def request(cloud, path, **kwargs):
        calls.append((path, kwargs))
        return {"invitation_id": "inv_synthetic", "invite_token": "short-lived-synthetic", "expires_at": "2026-10-10T12:00:00Z"}
    monkeypatch.setattr(collection, "cloud_request", request)
    result = collection.invite(library, label="Remote", processor_id=collection.PROCESSOR_ID,
                              scope=collection.Scope(projects=["/work/synthetic"], harnesses=["codex"]))
    assert "host-secret" not in json.dumps(result)
    assert "short-lived-synthetic" in result["command"]
    assert calls[0][1]["body"]["policy"]["scope"]["projects"] == ["/work/synthetic"]
    assert calls[0][0] == "/v1/libraries/lib-notes/invitations"


def test_local_watches_and_shared_processor_keep_existing_defaults(home, make_library, tmp_path):
    library = make_library()
    watch_project(library, str(tmp_path))
    before = (library.path / "library.yaml").read_bytes()
    data = collection.document(home, library)
    assert data["sources"][0]["scope"]["projects"] == [str(tmp_path)]
    assert collection.processor(home, library).min_owner_turns == home.config.sync.min_owner_turns
    collection.set_processor(home, library, {"min_owner_turns": 4})
    assert collection.processor(home, library).min_owner_turns == 4
    assert (library.path / "library.yaml").read_bytes() == before
    collection.set_local(library, False, collection.Scope(projects=[str(tmp_path)]))
    assert collection.document(home, library)["sources"][0]["enabled"] is False
    assert sync.status(home, Library.load(home, library.state.name))["next_due"] is None
    collection.save_config(library, {"local_enabled": False, "cloud": {"url": "https://synthetic.example"}})
    assert sync.status(home, library)["watching"] == ["cloud"]


def test_local_console_refuses_cross_origin_and_dns_rebinding(client):
    http, library = client
    assert http.get("/home/collection").status_code == 200
    assert http.get("/home/collection", headers={"host": "evil.example"}).status_code == 403
    assert http.put("/home/collection/local", headers={"origin": "https://evil.example"},
                    json={"enabled": True, "scope": {"projects": ["all"]}}).status_code == 403
    assert http.put("/home/collection/processors/agent-sessions", json={
        "min_owner_turns": 2, "min_owner_chars": 200, "ack_max_words": 1,
        "max_part_chars": 400000}).status_code == 422
    assert not (library.path / "collection.json").exists()


def test_pause_preserves_every_legacy_watch_rule(client, tmp_path):
    http, library = client
    library.state.watch = [Watch(path=str(tmp_path), recursive=True, harnesses=["codex"], since="2024-01-01T00:00:00Z"),
                           Watch(path="all", harnesses=["claude-code"], since="2026-01-01T00:00:00Z")]
    library.save()
    before = (library.path / "library.yaml").read_bytes()
    data = http.get("/home/collection").json()["sources"][0]
    assert data["complex_scope"] is True and data["watches"][0]["recursive"] is True
    assert http.put("/home/collection/local", json={"enabled": False}).status_code == 200
    assert (library.path / "library.yaml").read_bytes() == before
    assert http.put("/home/collection/local", json={"enabled": True}).status_code == 200
    assert (library.path / "library.yaml").read_bytes() == before


def test_cached_observer_merges_an_interleaved_observer(home, make_library):
    library = make_library()
    cached = collection.observer(library)
    cached({"origin": {"device_id": "a"}, "project_path": "/a", "source_id": "s1"})
    collection.observe(library, [{"origin": {"device_id": "b"}, "project_path": "/b", "source_id": "s2"}])
    cached({"origin": {"device_id": "a"}, "project_path": "/a", "source_id": "s3"})
    assert len(collection.projects(library)) == 2
    assert collection.projects(library) == collection.replay_projects(library)


def test_source_observations_do_not_expand_to_other_sessions_in_the_project(home, make_library):
    library = make_library()
    observations = [
        {"origin": {"device_id": "dev_one", "git_remote": "git@github.com:synthetic/atlas.git"},
         "project_path": "/one/Atlas", "source_ids": ["source-one"], "snapshot_id": "v1"},
        {"origin": {"device_id": "dev_two", "git_remote": "https://github.com/synthetic/atlas"},
         "project_path": "/two/Atlas", "source_ids": ["source-two"], "snapshot_id": "v2"},
        {"origin": {"git_remote": "https://github.com/synthetic/atlas"},
         "project_path": "/local/Atlas", "source_ids": ["source-one"], "snapshot_id": "v1"},
    ]
    collection.observe(library, observations)
    kept = library.path / "collection-observations.jsonl"
    before = kept.read_bytes()
    result = collection.source_observations(library, "source-one")
    assert result["user_id"] == library.state.tenant
    assert result["relation"] == "session_observation"
    assert [(row["device_id"], row["transport"]) for row in result["observations"]] == [
        ("dev_one", "remote"), ("local", "local")]
    assert len({row["project_id"] for row in result["observations"]}) == 1
    assert result["observations"][0]["remotes"] == ["github.com/synthetic/atlas"]
    assert "/two/Atlas" not in json.dumps(result)
    assert collection.source_observations(library, "unknown")["observations"] == []
    assert kept.read_bytes() == before
    (library.path / "collection-projects.json").unlink()
    assert collection.source_observations(library, "source-one") == result


def test_source_observation_times_are_record_times_and_locations_remain_distinct(home, make_library, monkeypatch):
    library = make_library()
    times = iter(["2026-10-10T12:00:00Z", "2026-10-10T13:00:00Z", "2026-10-10T14:00:00Z"])
    monkeypatch.setattr(collection, "now", lambda: next(times))
    first = {"origin": {"device_id": "dev_one", "git_remote": "git@github.com:synthetic/atlas.git"},
             "project_path": "/one/Atlas", "source_ids": ["source-one"], "snapshot_id": "v1"}
    collection.observe(library, [first])
    collection.observe(library, [{**first, "snapshot_id": "v2"}])
    collection.observe(library, [{**first, "project_path": "/moved/Atlas"}])
    rows = collection.source_observations(library, "source-one")["observations"]
    assert len(rows) == 2
    assert rows[0]["first_observed_at"] == "2026-10-10T12:00:00Z"
    assert rows[0]["last_observed_at"] == "2026-10-10T13:00:00Z"
    assert rows[1]["project_path"] == "/moved/Atlas"


def test_source_labels_survive_cloud_outage_without_caching_secrets(home, make_library, monkeypatch):
    library = make_library()
    cloud = {"url": "https://synthetic.example", "host_token": "synthetic-host-secret"}
    collection.save_config(library, {"cloud": cloud})
    collection.observe(library, [{"origin": {"device_id": "dev_one"}, "project_path": "/one/Atlas",
                                  "source_ids": ["source-one"]}])
    seen = []
    def registry(config, path, **kwargs):
        seen.append(path)
        assert path == "/v1/libraries/lib-notes/devices"
        return {"devices": [{"device_id": "dev_one", "label": "Synthetic laptop",
                              "device_secret": "must-not-cache", "policy": {"scope": "must-not-cache"}}]}
    monkeypatch.setattr(collection, "cloud_request", registry)
    result = collection.source_observations(library, "source-one")
    assert result["observations"][0]["device_label"] == "Synthetic laptop"
    path = library.path / "collection-device-labels.json"
    cached = json.loads(path.read_text())
    assert "secret" not in path.read_text() and "must-not-cache" not in path.read_text()
    assert path.stat().st_mode & 0o777 == 0o600
    cached["fetched_at"] = 0
    path.write_text(json.dumps(cached))
    def unavailable(*args, **kwargs):
        raise ValueError("cloud unavailable")
    monkeypatch.setattr(collection, "cloud_request", unavailable)
    assert collection.source_observations(library, "source-one") == result
    collection.save_config(library, {"cloud": {**cloud, "url": "https://different.example"}})
    assert collection.source_observations(library, "source-one")["observations"][0]["device_label"] is None
    assert len(seen) == 1


def test_source_observation_route_checks_tenant_before_reading(client, monkeypatch):
    http, library = client
    collection.observe(library, [{"origin": {"device_id": "dev_one"}, "project_path": "/one/Atlas",
                                  "source_ids": ["source-one"]}])
    result = http.get("/home/collection/sources/source-one", params={"user_id": library.state.tenant})
    assert result.status_code == 200
    assert result.json()["observations"][0]["device_id"] == "dev_one"
    def forbidden(*args, **kwargs):
        pytest.fail("mismatched tenant reached collection storage")
    monkeypatch.setattr(collection, "source_observations", forbidden)
    assert http.get("/home/collection/sources/source-one", params={"user_id": "lib-other"}).status_code == 404
    assert http.get("/home/collection/sources/source-one").status_code == 422


@pytest.mark.parametrize("cached", [None, [], "invalid cache"])
def test_optional_label_cache_damage_does_not_hide_observations(home, make_library, monkeypatch, cached):
    library = make_library()
    collection.save_config(library, {"cloud": {"url": "https://synthetic.example", "host_token": "synthetic"}})
    collection.observe(library, [{"origin": {"device_id": "dev_one"}, "project_path": "/one/Atlas",
                                  "source_ids": ["source-one"]}])
    (library.path / "collection-device-labels.json").write_text(json.dumps(cached))
    def unavailable(*args, **kwargs):
        raise ValueError("cloud unavailable")
    monkeypatch.setattr(collection, "cloud_request", unavailable)
    records = collection.source_observations(library, "source-one")["observations"]
    assert records[0]["device_id"] == "dev_one"
    assert records[0]["device_label"] is None


def test_project_identity_groups_origin_aliases_and_keeps_device_observations(home, make_library):
    library = make_library()
    observations = [{"origin": {"device_id": "desktop", "git_remote": "git@github.com:synthetic/atlas.git"},
                     "project_path": "/desktop/Atlas", "material_id": "m1", "snapshot_id": "v1", "source_ids": ["s1"]},
                    {"origin": {"device_id": "remote", "git_remote": "https://github.com/synthetic/atlas"},
                     "project_path": "/remote/Atlas", "material_id": "m2", "snapshot_id": "v2", "source_id": "s2"}]
    collection.observe(library, observations)
    project = collection.projects(library)[0]
    assert len(collection.projects(library)) == 1
    assert project["source_ids"] == ["s1", "s2"]
    assert len(project["locations"]) == 2
    before = (library.path / "collection-observations.jsonl").read_bytes()
    collection.observe(library, observations)
    assert (library.path / "collection-observations.jsonl").read_bytes() == before
    assert collection.projects(library)[0]["project_id"] == project["project_id"]
    (library.path / "collection-projects.json").unlink()
    assert collection.projects(library)[0] == project
    fork = {**observations[1], "origin": {"device_id": "fork", "git_remote": "git@github.com:another/atlas.git"}}
    collection.observe(library, [fork])
    assert len(collection.projects(library)) == 2
    reused = {**observations[1], "origin": {"device_id": "remote", "git_remote": "git@github.com:third/atlas.git"}}
    collection.observe(library, [reused])
    assert len(collection.projects(library)) == 3


def test_committed_snapshot_download_verifies_bytes_before_advancing_and_retains_held_material(
        home, make_library, provider_files, monkeypatch):
    library = make_library()
    collection.save_config(library, {"cloud": {"url": "https://synthetic.example", "host_token": "synthetic"}})
    snapshot = sessions.capture_snapshot("claude-code", provider_files.claude_file, provider_files.project)
    encoded = json.dumps(snapshot).encode()
    manifest = {"device_id": "dev_synthetic", "snapshot_id": snapshot["snapshot_id"],
                "sha256": hashlib.sha256(encoded).hexdigest()}
    pages = []
    def request(cloud, path, **kwargs):
        if kwargs.get("raw"):
            return encoded
        pages.append(path)
        return {"items": [manifest] if "cursor=" not in path else [], "next_cursor": "1", "has_more": False}
    monkeypatch.setattr(collection, "cloud_request", request)
    downloaded = collection.download_snapshots(library)
    assert downloaded[0]["origin"]["device_id"] == "dev_synthetic"
    assert collection.download_snapshots(library) == downloaded
    assert "cursor=1" in pages[-1]
    assert collection.cached_snapshots(library) == downloaded
    index = library.path / "collection-cache" / "index.json"
    before = index.read_bytes()
    def bad_request(cloud, path, **kwargs):
        return b"corrupt" if kwargs.get("raw") else {"items": [manifest], "next_cursor": "2", "has_more": False}
    monkeypatch.setattr(collection, "cloud_request", bad_request)
    with pytest.raises(ValueError, match="digest mismatch"):
        collection.download_snapshots(library)
    assert index.read_bytes() == before


def test_remote_dry_run_validates_without_creating_a_cache(home, make_library, provider_files, monkeypatch):
    library = make_library()
    collection.save_config(library, {"cloud": {"url": "https://synthetic.example", "host_token": "synthetic"}})
    snapshot = sessions.capture_snapshot("claude-code", provider_files.claude_file, provider_files.project)
    data = json.dumps(snapshot).encode()
    def request(cloud, path, **kwargs):
        return data if kwargs.get("raw") else {"items": [{"snapshot_id": snapshot["snapshot_id"],
            "device_id": "dev_synthetic", "sha256": hashlib.sha256(data).hexdigest()}],
            "next_cursor": "1", "has_more": False}
    monkeypatch.setattr(collection, "cloud_request", request)
    assert len(collection.download_snapshots(library, persist=False)) == 1
    assert not (library.path / "collection-cache").exists()


def test_every_device_and_intermediate_revision_survives_until_processor_ack(
        home, make_library, provider_files, monkeypatch):
    from copy import deepcopy
    from test_sync import append
    library = make_library()
    collection.save_config(library, {"cloud": {"url": "https://synthetic.example", "host_token": "synthetic"}})
    first = sessions.capture_snapshot("claude-code", provider_files.claude_file, provider_files.project)
    append(provider_files, "claude-code")
    second = sessions.capture_snapshot("claude-code", provider_files.claude_file, provider_files.project)
    rows, payloads = [], {}
    for index, (device, value) in enumerate([("a", first), ("a", second), ("b", second)], 1):
        snapshot = deepcopy(value)
        snapshot["origin"]["device_id"] = device
        data = json.dumps(snapshot).encode()
        rows.append({"device_id": device, "snapshot_id": snapshot["snapshot_id"], "sha256": hashlib.sha256(data).hexdigest()})
        payloads[(device, snapshot["snapshot_id"])] = data
    def request(cloud, path, **kwargs):
        if kwargs.get("raw"):
            device = path.rsplit("device_id=", 1)[1]
            sid = path.split("?")[0].rsplit("/", 1)[1]
            return payloads[(device, sid)]
        return {"items": rows if "cursor=" not in path else [], "next_cursor": "3", "has_more": False}
    monkeypatch.setattr(collection, "cloud_request", request)
    downloaded = collection.download_snapshots(library)
    assert [(s["origin"]["device_id"], s["snapshot_id"]) for s in downloaded] == [
        ("a", first["snapshot_id"]), ("a", second["snapshot_id"]), ("b", second["snapshot_id"])]
    assert len(collection.download_snapshots(library)) == 3
    collection.acknowledge_snapshots(library, {"sessions": [
        {"origin": s["origin"], "snapshot_id": s["snapshot_id"], "status": "held"} for s in downloaded]})
    retained = collection.download_snapshots(library)
    assert [(s["origin"]["device_id"], s["snapshot_id"]) for s in retained] == [
        ("a", second["snapshot_id"]), ("b", second["snapshot_id"])]
