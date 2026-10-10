"""Edition-owned material sources, processors, enrollment and collection observations.

Transport credentials and device observations never enter evidence contracts. The existing
converter still owns incremental ingestion; a cloud snapshot is another input to that same
processor, not another canonical writer.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
import fcntl
import hashlib
import json
from pathlib import Path
import re
import shlex
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from pydantic import Field, field_validator

from pkc_personal.home import Home, Model, atomic_write, now
from pkc_personal.library import Library, Watch

MAX_RESPONSE = 20 * 1024 * 1024
PROCESSOR_ID = "agent-sessions"
PROTOCOL = "pneuma.collector/v1"


class Scope(Model):
    projects: list[str] = Field(default_factory=lambda: ["all"], min_length=1, max_length=100)
    harnesses: list[str] = Field(default_factory=lambda: ["codex", "claude-code"], min_length=1)
    since: str | None = None

    @field_validator("projects")
    @classmethod
    def project_scope(cls, values):
        if any(not x.strip() or "\x00" in x for x in values):
            raise ValueError("project scope must contain nonempty paths or all")
        if "all" in values and values != ["all"]:
            raise ValueError("all cannot be combined with individual projects")
        return list(dict.fromkeys(values))

    @field_validator("harnesses")
    @classmethod
    def harness_scope(cls, values):
        if any(x not in ("codex", "claude-code") for x in values):
            raise ValueError("unsupported session harness")
        return list(dict.fromkeys(values))

    @field_validator("since")
    @classmethod
    def timestamp(cls, value):
        if value is not None and datetime.fromisoformat(value).utcoffset() is None:
            raise ValueError("since must include a timezone")
        return value


class Processor(Model):
    id: str = PROCESSOR_ID
    label: str = "Agent sessions"
    material_type: str = "agent-session"
    min_owner_turns: int = Field(default=3, ge=3)
    min_owner_chars: int = Field(default=200, ge=0)
    ack_max_words: int = Field(default=1, ge=1)
    max_part_chars: int = Field(default=400_000, ge=1000)


@contextmanager
def locked(library: Library):
    library.path.mkdir(parents=True, exist_ok=True)
    with (library.path / "collection.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def read_config(library: Library) -> dict:
    path = library.path / "collection.json"
    return json.loads(path.read_text()) if path.exists() else {"version": 1}


def save_config(library: Library, config: dict) -> None:
    atomic_write(library.path / "collection.json", json.dumps(config, ensure_ascii=False, indent=2) + "\n")


def processor(home: Home, library: Library) -> Processor:
    config = read_config(library)
    defaults = {k: getattr(home.config.sync, k) for k in
                ("min_owner_turns", "min_owner_chars", "ack_max_words", "max_part_chars")}
    return Processor.model_validate(config.get("processor", defaults))


def set_processor(home: Home, library: Library, values: dict) -> dict:
    with locked(library):
        selected = Processor.model_validate({**processor(home, library).model_dump(), **values})
        if selected.id != PROCESSOR_ID or selected.material_type != "agent-session":
            raise ValueError("unsupported processor")
        config = read_config(library)
        config["processor"] = selected.model_dump()
        save_config(library, config)
    return selected.model_dump()


def validate_cloud_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    local = parsed.hostname in ("127.0.0.1", "localhost", "::1")
    if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or not parsed.hostname:
        raise ValueError("cloud URL must use HTTPS (HTTP is allowed only for localhost development)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("cloud URL must be an origin, without credentials, path or query")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def cloud_request(cloud: dict, path: str, *, method: str = "GET", body=None, raw: bool = False,
                  timeout: float = 30):
    """Bounded authenticated HTTP; a redirect never forwards an Owner credential."""
    base = validate_cloud_url(cloud.get("url", ""))
    token = cloud.get("host_token", "")
    if not token:
        raise ValueError("configure the cloud connection first")
    payload = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    request = urllib.request.Request(base + path, data=payload, method=method, headers={
        "Authorization": "Bearer " + token, "Accept": "application/json", "Content-Type": "application/json",
        "User-Agent": "pkc-host/1"})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            data = response.read(MAX_RESPONSE + 1)
    except urllib.error.HTTPError as exc:
        raise ValueError(f"cloud request failed (HTTP {exc.code})") from None
    except (OSError, urllib.error.URLError):
        raise ValueError("cloud connection unavailable") from None
    if len(data) > MAX_RESPONSE:
        raise ValueError("cloud response exceeds the material limit")
    if raw:
        return data
    result = json.loads(data)
    if not isinstance(result, dict):
        raise ValueError("cloud response must be a JSON object")
    return result


def set_cloud(library: Library, url: str, host_token: str) -> dict:
    if not host_token.strip() or len(host_token) > 4096 or any(c.isspace() for c in host_token):
        raise ValueError("provide the cloud host token")
    cloud = {"url": validate_cloud_url(url), "host_token": host_token}
    health = cloud_request(cloud, "/v1/health")
    if health.get("protocol") != PROTOCOL or health.get("status") != "ok":
        raise ValueError("cloud service does not support pneuma.collector/v1")
    with locked(library):
        config = read_config(library)
        config["cloud"] = cloud
        save_config(library, config)
    return {"url": cloud["url"], "configured": True}


def cloud_path(library: Library, tail: str) -> str:
    return f"/v1/libraries/{urllib.parse.quote(library.state.tenant, safe='')}/{tail}"


def cloud_for(library: Library) -> dict:
    cloud = read_config(library).get("cloud")
    if not cloud:
        raise ValueError("configure the cloud connection first")
    return cloud


def cloud_devices(library: Library, cloud: dict, *, timeout: float = 30) -> list[dict]:
    """Read the registry and cache only its display names, never credentials or policy."""
    devices = cloud_request(cloud, cloud_path(library, "devices"), timeout=timeout).get("devices", [])
    if not isinstance(devices, list) or any(not isinstance(row, dict) for row in devices):
        raise ValueError("cloud device registry must return a list of devices")
    labels = {row["device_id"]: row["label"] for row in devices
              if isinstance(row.get("device_id"), str) and isinstance(row.get("label"), str)}
    atomic_write(library.path / "collection-device-labels.json", json.dumps({
        "url": cloud["url"], "user_id": library.state.tenant, "fetched_at": time.time(), "labels": labels}))
    return devices


def device_labels(library: Library) -> dict[str, str]:
    """Optional current names; a registry outage must not hide locally kept observations."""
    cloud = read_config(library).get("cloud")
    if not cloud:
        return {}
    path = library.path / "collection-device-labels.json"
    try:
        cached = json.loads(path.read_text())
    except (OSError, ValueError):
        cached = {}
    if not isinstance(cached, dict):
        cached = {}
    if cached.get("url") != cloud["url"] or cached.get("user_id") != library.state.tenant:
        cached = {}
    labels = cached.get("labels", {})
    if not isinstance(labels, dict):
        labels = {}
    labels = {key: value for key, value in labels.items() if isinstance(key, str) and isinstance(value, str)}
    fetched_at = cached.get("fetched_at")
    if isinstance(fetched_at, (float, int)) and 0 <= time.time() - fetched_at < 300:
        return labels
    try:
        devices = cloud_devices(library, cloud, timeout=3)
        return {row["device_id"]: row["label"] for row in devices
                if isinstance(row.get("device_id"), str) and isinstance(row.get("label"), str)}
    except (OSError, ValueError):
        return labels


def invite(library: Library, *, label: str, scope: Scope, processor_id: str) -> dict:
    if processor_id != PROCESSOR_ID:
        raise ValueError("unsupported processor")
    if not label.strip() or len(label) > 100:
        raise ValueError("device label must contain 1–100 characters")
    if any(path != "all" and not path.startswith("/") for path in scope.projects):
        raise ValueError("remote projects need absolute paths on the target computer")
    cloud = cloud_for(library)
    result = cloud_request(cloud, cloud_path(library, "invitations"), method="POST", body={
        "label": label.strip(), "policy": {"processor_id": processor_id,
        "scope": scope.model_dump(), "interval_seconds": 300,
        "exclude": list(library.home.config.sync.exclude)}})
    base = cloud["url"]
    command = (f"curl -fsSL --max-redirs 0 {shlex.quote(base + '/install.sh')} | sh -s -- --url "
               f"{shlex.quote(base)} --invite {shlex.quote(result['invite_token'])}")
    instruction = (
        "请在这台电脑执行以下 PKC 采集器接入指令，并检查后台服务是否正常。"
        "采集范围已由我的宿主机设置；不要扩大范围或上传其他文件。一次性邀请过期时请让我重新生成。"
        if library.state.choices.language == "zh" else
        "Run this PKC collector enrollment command on this computer and verify the background service. "
        "My host has already selected the collection scope; keep that scope. "
        "If the one-time invitation has expired, ask me to generate another.")
    return {"invitation_id": result["invitation_id"], "expires_at": result["expires_at"],
            "command": command, "ai_prompt": instruction + "\n" + command}


def change_device(library: Library, device_id: str, status: str) -> dict:
    if status not in ("active", "paused", "revoked"):
        raise ValueError("unsupported device status")
    return cloud_request(cloud_for(library), cloud_path(library, "devices/" +
                         urllib.parse.quote(device_id, safe="")), method="PATCH", body={"status": status})


def revoke_invite(library: Library, invitation_id: str) -> dict:
    return cloud_request(cloud_for(library), cloud_path(library, "invitations/" +
                         urllib.parse.quote(invitation_id, safe="")), method="DELETE")


def local_scope(library: Library) -> dict:
    watches = Library.load(library.home, library.state.name).state.watch
    return {"projects": [w.path for w in watches],
            "harnesses": list(dict.fromkeys(h for w in watches for h in w.harnesses)),
            "since": watches[0].since if watches and all(w.since == watches[0].since for w in watches) else None}


def set_local(library: Library, enabled: bool, scope: Scope | None = None) -> dict:
    watches = ([Watch(path=path, harnesses=scope.harnesses, since=scope.since) for path in scope.projects]
               if scope is not None else [])
    for watch in watches:
        if watch.path != "all" and not Path(watch.path).is_dir():
            raise ValueError("local source needs existing project directories")
    with locked(library):
        current = Library.load(library.home, library.state.name)
        if scope is not None:
            current.state.watch = watches
            current.save()
        config = read_config(library)
        config["local_enabled"] = enabled
        save_config(library, config)
    return {"enabled": enabled, "scope": local_scope(current)}


def normalize_remote(raw: str) -> str | None:
    """Conservative SSH/HTTPS alias matching; preserve repository path case and forks."""
    raw = raw.strip()
    if re.match(r"^[^/@\s]+@[^/:\s]+:", raw):
        host, path = raw.split("@", 1)[1].split(":", 1)
    else:
        parsed = urllib.parse.urlsplit(raw)
        if parsed.scheme not in ("https", "http", "ssh", "git") or not parsed.hostname:
            return None
        host, path = parsed.hostname, parsed.path
        if parsed.port and parsed.port not in (22, 80, 443):
            host += ":" + str(parsed.port)
    path = path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path or ".." in path.split("/"):
        return None
    return host.lower() + "/" + path


def projects(library: Library, *, _locked: bool = False) -> list[dict]:
    if not _locked:
        with locked(library):
            return projects(library, _locked=True)
    path = library.path / "collection-projects.json"
    history = library.path / "collection-observations.jsonl"
    if path.exists():
        cached = json.loads(path.read_text())
        if cached.get("history_bytes") == (history.stat().st_size if history.exists() else 0):
            return cached.get("projects", [])
    return replay_projects(library, _locked=True)


def replay_projects(library: Library, *, _locked: bool = False) -> list[dict]:
    if not _locked:
        with locked(library):
            return replay_projects(library, _locked=True)
    # The inventory is a projection. Assigned identities and observations survive its loss.
    history = library.path / "collection-observations.jsonl"
    if not history.exists():
        return []
    result = {}
    with history.open() as stream:
        for line in stream:
            row = json.loads(line)
            project = result.setdefault(row["project_id"], {"project_id": row["project_id"],
                "name": Path(row["project_path"]).name, "remotes": [], "locations": [], "source_ids": []})
            place = {"device_id": row["device_id"], "path": row["project_path"]}
            if place not in project["locations"]:
                project["locations"].append(place)
            if row["git_remote"] and row["git_remote"] not in project["remotes"]:
                project["remotes"].append(row["git_remote"])
            project["source_ids"] = list(dict.fromkeys([*project["source_ids"], *row["source_ids"]]))
    return list(result.values())


def download_snapshots(library: Library, *, persist: bool = True, stream: bool = False):
    """Replay the committed feed, persisting only verified objects before its read cursor.

    This is an observation cursor, not an ingest ACK. The latest complete material remains
    available on every pass, including when it is held or ingestion has failed.
    """
    cloud = read_config(library).get("cloud")
    if not cloud:
        return []
    from pkc_personal.sync import converter
    script = converter()
    directory = library.path / "collection-cache"
    index_path = directory / "index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"cursor": None, "materials": {}, "pending": []}
    # Changing cloud installations cannot reuse another installation's read position.
    if index.get("url") != cloud["url"]:
        index = {"url": cloud["url"], "cursor": None, "materials": {}, "pending": []}
    index.setdefault("pending", [])
    cursor = index["cursor"]
    fetched = {}
    while True:
        query = "?limit=100" + ("&cursor=" + urllib.parse.quote(str(cursor), safe="") if cursor else "")
        page = cloud_request(cloud, cloud_path(library, "snapshots") + query)
        items = page.get("items", [])
        for entry in items:
            sid, did = entry["snapshot_id"], entry["device_id"]
            key = hashlib.sha256((did + ":" + sid).encode()).hexdigest()
            payload_path = directory / (key + ".json")
            payload = cloud_request(cloud, cloud_path(library, "snapshots/" + urllib.parse.quote(sid, safe=""))
                                    + "?device_id=" + urllib.parse.quote(did, safe=""), raw=True)
            if hashlib.sha256(payload).hexdigest() != entry["sha256"]:
                raise ValueError("cloud snapshot digest mismatch; read position was not advanced")
            snapshot = json.loads(payload)
            script.decode_snapshot(snapshot)
            if snapshot["snapshot_id"] != sid:
                raise ValueError("cloud snapshot identity mismatch")
            snapshot.setdefault("origin", {})["device_id"] = did
            if persist:
                atomic_write(payload_path, json.dumps(snapshot, ensure_ascii=False))
            if not persist:
                fetched[key] = snapshot
            material_key = did + ":" + snapshot["material_id"] + ":" + (snapshot["session"]["project_path"] or "")
            index["materials"][material_key] = key
            if key not in index["pending"]:
                index["pending"].append(key)
        following = page.get("next_cursor")
        if page.get("has_more") and (not following or following == cursor):
            raise ValueError("cloud snapshot pagination did not advance")
        if following:
            cursor = following
        index["cursor"] = cursor
        if persist:
            atomic_write(index_path, json.dumps(index))
        if not page.get("has_more", False):
            break
    keys = list(dict.fromkeys([*index["pending"], *index["materials"].values()]))
    result = (fetched[key] if key in fetched else json.loads((directory / (key + ".json")).read_text()) for key in keys)
    return result if stream else list(result)


def cached_snapshots(library: Library, *, stream: bool = False):
    directory = library.path / "collection-cache"
    path = directory / "index.json"
    if not path.exists():
        return []
    index = json.loads(path.read_text())
    if index.get("url") != read_config(library).get("cloud", {}).get("url"):
        return []
    keys = list(dict.fromkeys([*index.get("pending", []), *index["materials"].values()]))
    result = (json.loads((directory / (key + ".json")).read_text()) for key in keys)
    return result if stream else list(result)


def acknowledge_snapshots(library: Library, report: dict) -> None:
    """Release observed queue entries; retained latest snapshots still support held/retry."""
    acknowledged = set()
    for row in report.get("sessions", []):
        origin = row.get("origin") or {}
        if row.get("status") in ("error", "retry") or not row.get("snapshot_id") or not origin.get("device_id"):
            continue
        acknowledged.add(hashlib.sha256((origin["device_id"] + ":" + row["snapshot_id"]).encode()).hexdigest())
    if not acknowledged:
        return
    with locked(library):
        path = library.path / "collection-cache" / "index.json"
        if path.exists():
            index = json.loads(path.read_text())
            index["pending"] = [key for key in index.get("pending", []) if key not in acknowledged]
            atomic_write(path, json.dumps(index))


def observer(library: Library):
    """One pass's observer; initialize lazily after the converter acquires its sync lock."""
    state = {}
    return lambda row: observe(library, [row], _state=state)


def observe(library: Library, observations: list[dict], *, _state: dict | None = None) -> None:
    """Keep collection provenance outside immutable L0; project IDs survive alias changes."""
    if not observations:
        return
    with locked(library):
        path = library.path / "collection-observations.jsonl"
        revision = (path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None
        if _state and _state.get("revision") != revision:
            _state.clear()
        inventory = _state["projects"] if _state and "projects" in _state else projects(library, _locked=True)
        known = _state["known"] if _state and "known" in _state else set()
        if path.exists() and not (_state and "known" in _state):
            with path.open() as stream:
                known = {json.loads(line)["observation_id"] for line in stream if line.strip()}
        additions = []
        for item in observations:
            origin = item.get("origin") or {}
            location = item.get("project_path")
            if not location:
                continue
            device_id = origin.get("device_id") or "local"
            remote = normalize_remote(origin.get("git_remote") or "")
            place = {"device_id": device_id, "path": location}
            match = next((p for p in inventory if remote and remote in p["remotes"]), None)
            if match is None:
                match = next((p for p in inventory if place in p["locations"]
                              and (not remote or not p["remotes"])), None)
            if match is None:
                match = {"project_id": "prj_" + uuid.uuid4().hex, "name": Path(location).name,
                         "remotes": [], "locations": [], "source_ids": []}
                inventory.append(match)
            if remote and remote not in match["remotes"]:
                match["remotes"].append(remote)
            if place not in match["locations"]:
                match["locations"].append(place)
            ids = list(item.get("source_ids") or [])
            if item.get("source_id"):
                ids.append(item["source_id"])
            match["source_ids"] = list(dict.fromkeys([*match["source_ids"], *ids]))
            record = {"project_id": match["project_id"], "device_id": device_id,
                      "project_path": location, "git_remote": remote, "source_ids": ids,
                      "provider": item.get("provider"), "session_id": item.get("session_id"),
                      "material_id": item.get("material_id"), "snapshot_id": item.get("snapshot_id")}
            digest = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
            if digest not in known:
                additions.append({"observation_id": digest, "observed_at": now(), **record})
                known.add(digest)
        if additions:
            path.touch(mode=0o600, exist_ok=True)
            with path.open("a") as stream:
                for row in additions:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                stream.flush()
                import os
                os.fsync(stream.fileno())
        projection = json.dumps({"version": 1, "history_bytes": path.stat().st_size if path.exists() else 0,
                                 "projects": inventory}, ensure_ascii=False, indent=2) + "\n"
        if _state is None or _state.get("projection") != projection:
            atomic_write(library.path / "collection-projects.json", projection)
        if _state is not None:
            _state.update(projects=inventory, known=known, projection=projection,
                          revision=(path.stat().st_mtime_ns, path.stat().st_size) if path.exists() else None)


def project_bindings(library: Library) -> dict:
    """Replay native session attribution, including the observation made before ingest."""
    with locked(library):
        inventory = {p["project_id"]: p for p in projects(library, _locked=True)}
        path = library.path / "collection-observations.jsonl"
        bindings = {}
        if path.exists():
            with path.open() as stream:
                for line in stream:
                    row = json.loads(line)
                    if row.get("provider") and row.get("session_id"):
                        key = (row["provider"], row["session_id"], row["project_path"])
                        bindings[key] = inventory[row["project_id"]]
        return bindings


def source_observations(library: Library, source_id: str) -> dict:
    """Session observations associated with a source, not exclusive import provenance.

    A cursor can associate older source IDs with a newly observed copy of its session.
    Match the kept rows themselves: the project's other sessions and locations are not
    observations of this source. Record times are not device last-seen or upload times.
    """
    result = {"user_id": library.state.tenant, "source_id": source_id,
              "relation": "session_observation", "observations": []}
    with locked(library):
        path = library.path / "collection-observations.jsonl"
        if not path.exists():
            return result
        inventory = {project["project_id"]: project for project in projects(library, _locked=True)}
        grouped = {}
        with path.open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                if source_id not in row.get("source_ids", []):
                    continue
                key = (row["device_id"], row["project_id"], row["project_path"])
                project = inventory[row["project_id"]]
                entry = grouped.setdefault(key, {
                    "transport": "local" if row["device_id"] == "local" else "remote",
                    "device_id": row["device_id"], "device_label": None,
                    "project_id": row["project_id"], "project_name": project["name"],
                    "project_path": row["project_path"], "remotes": [],
                    "first_observed_at": row["observed_at"], "last_observed_at": row["observed_at"]})
                if row.get("git_remote") and row["git_remote"] not in entry["remotes"]:
                    entry["remotes"].append(row["git_remote"])
                entry["first_observed_at"] = min(entry["first_observed_at"], row["observed_at"])
                entry["last_observed_at"] = max(entry["last_observed_at"], row["observed_at"])
        result["observations"] = list(grouped.values())
    # Optional registry reads never hold the processor's collection lock.
    labels = device_labels(library) if any(row["transport"] == "remote" for row in result["observations"]) else {}
    for row in result["observations"]:
        row["device_label"] = labels.get(row["device_id"])
    return result


def rebuild_projects(library: Library) -> None:
    """Rebuild the disposable inventory without changing any recorded identity."""
    with locked(library):
        path = library.path / "collection-projects.json"
        # Derive into memory before replacement; the kept stream, never this projection,
        # assigns identities. Reading through a separate helper avoids a destructive gap.
        inventory = replay_projects(library, _locked=True)
        history = library.path / "collection-observations.jsonl"
        atomic_write(path, json.dumps({"version": 1, "history_bytes": history.stat().st_size if history.exists() else 0,
                                      "projects": inventory}, ensure_ascii=False, indent=2) + "\n")


def document(home: Home, library: Library) -> dict:
    config = read_config(library)
    cloud = config.get("cloud") or {}
    status = {"url": cloud.get("url", ""), "configured": bool(cloud)}
    devices, invitations = [], []
    if cloud:
        try:
            devices = cloud_devices(library, cloud)
            invitations = cloud_request(cloud, cloud_path(library, "invitations")).get("invitations", [])
        except (OSError, ValueError) as exc:
            status["error"] = str(exc)
    watches = Library.load(home, library.state.name).state.watch
    mixed = (any(w.recursive for w in watches)
             or len({(tuple(w.harnesses), w.since) for w in watches}) > 1
             or (len(watches) > 1 and any(w.path == "all" for w in watches)))
    sources = [{"id": "local", "label": "This computer", "kind": "local",
                "processor_id": PROCESSOR_ID, "enabled": bool(watches) and config.get("local_enabled", True),
                "scope": local_scope(library), "watches": [w.model_dump() for w in watches], "complex_scope": mixed}]
    if cloud:
        sources.append({"id": "cloud", "label": "Cloud material source", "kind": "r2",
                        "processor_id": PROCESSOR_ID, "enabled": True, "scope": None})
    return {"cloud": status, "sources": sources, "processors": [processor(home, library).model_dump()],
            "devices": devices, "invitations": invitations, "projects": projects(library)}
