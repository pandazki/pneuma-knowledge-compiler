#!/usr/bin/env python3
"""A stdlib-only background publisher for the material feed protocol.

No knowledge engine, model key or R2 account credential is installed on this computer.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import plistlib
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_BYTES = 8 * 1024 * 1024


def atomic(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".pending-")
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(name).unlink(missing_ok=True)


def save(path: Path, document):
    atomic(path, json.dumps(document, ensure_ascii=False, sort_keys=True).encode())


def read(path: Path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CloudHTTPError(ValueError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(f"cloud HTTP {status}; no upload progress acknowledged")


@contextmanager
def device_lock(directory: Path):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "device.lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def origin(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    if not parsed.hostname or (parsed.scheme != "https" and not
            (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1", "::1"))):
        raise ValueError("collector URL must use HTTPS")
    if parsed.username or parsed.password or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("collector URL must be an origin")
    return value.rstrip("/")


def request(base: str, path: str, *, token=None, body=None, raw=False):
    headers = {"Accept": "application/json", "User-Agent": "pkc-collector/1"}
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        body = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        if len(body) > MAX_BYTES:
            raise ValueError("material snapshot exceeds 8 MiB")
        headers.update({"Content-Type": "application/json", "X-Content-SHA256": hashlib.sha256(body).hexdigest()})
    req = urllib.request.Request(origin(base) + path, data=body, headers=headers)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=60) as response:
            payload = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise CloudHTTPError(exc.code) from None
    except OSError:
        raise ValueError("cloud unavailable; material retained locally") from None
    if len(payload) > MAX_BYTES:
        raise ValueError("cloud response exceeds 8 MiB")
    return payload if raw else json.loads(payload)


def converter(runtime: Path):
    spec = importlib.util.spec_from_file_location("pkc_collector_sessions", runtime / "agent_sessions.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def enroll(directory: Path, base: str, invitation: str, *, label: str | None = None):
    """An uncertain claim always retries with the same persisted device key."""
    with device_lock(directory):
        return _enroll(directory, base, invitation, label=label)


def _enroll(directory: Path, base: str, invitation: str, *, label: str | None = None):
    config_path = directory / "device.json"
    config = read(config_path)
    if config and config["url"] != origin(base):
        raise ValueError("this collector directory belongs to a different cloud")
    if not config:
        config = {"url": origin(base), "device_id": "dev_" + uuid.uuid4().hex,
                  "device_secret": secrets.token_urlsafe(32), "label": label or socket.gethostname()}
        save(config_path, config)
    result = request(base, "/v1/enroll", body={"invite_token": invitation,
                     "device_id": config["device_id"], "device_secret": config["device_secret"],
                     "label": config["label"]})
    if result["device_id"] != config["device_id"]:
        raise ValueError("enrollment returned a different device identity")
    config.update(library_id=result["library_id"], policy=result["policy"],
                  status=result.get("status", config.get("status", "active")))
    save(config_path, config)
    return config


def checked_scope(policy: dict) -> list[dict]:
    scope = policy["scope"]
    paths, harnesses = scope["projects"], scope["harnesses"]
    if not paths or ("all" in paths and paths != ["all"]) or not harnesses:
        raise ValueError("invalid collection scope")
    if any(h not in ("codex", "claude-code") for h in harnesses):
        raise ValueError("unsupported collection harness")
    if any(not isinstance(p, str) or not p.strip() for p in paths):
        raise ValueError("empty collection project scope")
    return [{"path": p, "harnesses": harnesses, "since": scope.get("since")} for p in paths]


def snapshot_allowed(snapshot: dict, policy: dict, script) -> bool:
    """Recheck retained material against current policy without changing its bytes."""
    session = script.decode_snapshot(snapshot)
    scope = policy["scope"]
    if session.provider not in scope["harnesses"]:
        return False
    project = session.project
    if "all" not in scope["projects"] and (
            project is None or os.path.normpath(str(project)) not in
            {os.path.normpath(path) for path in scope["projects"]}):
        return False
    if project is not None and script.excluded_project(
            project, roots=[(Path.home() / ".pkc").resolve()], patterns=policy.get("exclude", [])):
        return False
    since = script.timestamp(scope["since"]) if scope.get("since") else None
    return since is None or bool(session.turns and script.timestamp(session.turns[-1]["at"]) >= since)


def collect_once(directory: Path, runtime: Path) -> dict:
    config = read(directory / "device.json")
    if not config or "policy" not in config:
        raise ValueError("collector is not enrolled")
    result = {"queued": 0, "uploaded": 0, "held": 0, "errors": []}
    online = True
    try:
        current = request(config["url"], "/v1/device/policy", token=config["device_secret"])
        with device_lock(directory):
            config = read(directory / "device.json")
            config["policy"] = current["policy"]
            config["status"] = current.get("status", "active")
            save(directory / "device.json", config)
    except CloudHTTPError as exc:
        online = False
        result["errors"].append(str(exc))
        if exc.status in (401, 403):
            with device_lock(directory):
                config = read(directory / "device.json")
                config["status"] = "revoked" if exc.status == 403 else "unauthorized"
                save(directory / "device.json", config)
    except ValueError as exc:
        online = False
        result["errors"].append(str(exc))
    if config.get("status") != "active":
        result["status"] = config["status"]
        save(directory / "status.json", {"at": time.time(), **result})
        return result
    script = converter(runtime)
    watches = checked_scope(config["policy"])
    state_path = directory / "publisher.json"
    state = read(state_path, {"sent": {}})
    pending = directory / "outbox"
    pending.mkdir(parents=True, exist_ok=True, mode=0o700)
    diagnostics = []
    roots = config.get("roots", {})
    snapshots = script.iter_snapshots(watches, home=str(Path.home() / ".pkc"),
                                     exclude=config["policy"].get("exclude", []),
                                     claude_roots=script.claude_session_roots(roots.get("claude", [])),
                                     codex_roots=script.codex_session_roots(roots.get("codex", [])),
                                     diagnostics=diagnostics)
    for snapshot in snapshots:
        sid = snapshot["snapshot_id"]
        if sid in state["sent"]:
            continue
        path = pending / (sid + ".json")
        if not path.exists():
            snapshot.setdefault("origin", {}).update(device_id=config["device_id"], device_label=config["label"])
            payload = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            if len(payload) > MAX_BYTES:
                result["errors"].append("material exceeds 8 MiB; retained at source")
                continue
            atomic(path, payload)
            result["queued"] += 1
    if diagnostics:
        result["errors"].append(f"{len(diagnostics)} session files could not be decoded")
    # FIFO by file creation time preserves observed revisions within a material stream.
    # Keep exact bytes through ambiguous network failures, including a server commit whose
    # HTTP response was lost. Only a matching durable cloud receipt advances this cursor.
    if online:
        for path in sorted(pending.glob("*.json"), key=lambda p: (p.stat().st_mtime_ns, p.name)):
            payload = path.read_bytes()
            expected = hashlib.sha256(payload).hexdigest()
            try:
                if not snapshot_allowed(json.loads(payload), config["policy"], script):
                    # A narrowed policy also governs material queued while offline.
                    # Retain it without an ACK; other permitted streams can proceed.
                    result["held"] += 1
                    continue
                receipt = request(config["url"], "/v1/device/snapshots", token=config["device_secret"], body=payload)
                if (receipt.get("sha256") != expected or receipt.get("snapshot_id") != path.stem
                        or receipt.get("device_id") != config["device_id"]
                        or receipt.get("library_id") != config["library_id"]
                        or type(receipt.get("sequence")) is not int or receipt["sequence"] < 1):
                    raise ValueError("cloud receipt does not match the pending material")
                state["sent"][path.stem] = expected
                save(state_path, state)
                path.unlink()
                result["uploaded"] += 1
            except ValueError as exc:
                result["errors"].append(str(exc))
                break
    result["pending"] = len(list(pending.glob("*.json")))
    result["status"] = "connected" if online and not result["errors"] else "retrying"
    save(directory / "status.json", {"at": time.time(), **result})
    return result


def run(directory: Path, runtime: Path, *, once=False):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (directory / "collector.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("this collector is already running") from None
        while True:
            try:
                result = collect_once(directory, runtime)
                print(json.dumps(result), flush=True)
            except (OSError, ValueError, KeyError) as exc:
                # Diagnostics name the failed operation, never dump material or credentials.
                print(json.dumps({"status": "retrying", "error": type(exc).__name__}), flush=True)
                if once:
                    raise
            if once:
                return
            config = read(directory / "device.json", {})
            interval = max(30, min(3600, config.get("policy", {}).get("interval_seconds", 300)))
            time.sleep(interval)


def install_service(directory: Path, runtime: Path):
    label = "com.pneuma.collector." + directory.name
    command = [sys.executable, str(runtime / "collector.py"), "run", "--directory", str(directory),
               "--runtime", str(runtime)]
    system = platform.system()
    if system == "Darwin":
        path = Path.home() / "Library" / "LaunchAgents" / (label + ".plist")
        document = {"Label": label, "ProgramArguments": command, "RunAtLoad": True,
                    "KeepAlive": True, "ThrottleInterval": 30,
                    "StandardOutPath": str(directory / "collector.log"),
                    "StandardErrorPath": str(directory / "collector.log")}
        atomic(path, plistlib.dumps(document))
        target = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", target + "/" + label], capture_output=True)
        subprocess.run(["launchctl", "bootstrap", target, str(path)], check=True)
    elif system == "Linux" and shutil.which("systemctl"):
        def unit_quote(value):
            return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'
        path = Path.home() / ".config" / "systemd" / "user" / (label + ".service")
        content = ("[Unit]\nDescription=PKC material collector\n[Service]\nType=simple\nExecStart="
                   + " ".join(unit_quote(x) for x in command)
                   + "\nRestart=on-failure\nRestartSec=30\n[Install]\nWantedBy=default.target\n")
        atomic(path, content.encode())
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "--now", path.name], check=True)
    else:
        raise ValueError("automatic background service requires macOS or Linux with systemd --user")
    return label


def install(args):
    base = origin(args.url)
    instance = hashlib.sha256((base + ":" + args.invite).encode()).hexdigest()[:20]
    directory = args.state_root.expanduser() / instance
    runtime = directory / "runtime"
    manifest = request(base, "/release.json")
    for name in ("collector.py", "agent_sessions.py"):
        data = request(base, "/" + name, raw=True)
        if hashlib.sha256(data).hexdigest() != manifest["files"][name]:
            raise ValueError("collector release digest mismatch")
        atomic(runtime / name, data)
    config = enroll(directory, base, args.invite, label=args.label)
    script = converter(runtime)
    with device_lock(directory):
        config = read(directory / "device.json")
        if "roots" not in config:
            config["roots"] = {"codex": [str(p) for p in script.codex_session_roots()],
                               "claude": [str(p) for p in script.claude_session_roots()]}
            save(directory / "device.json", config)
    checked_scope(config["policy"])
    if not args.no_service:
        service = install_service(directory, runtime)
        print(f"Collector enrolled; background service {service}. Status: {directory / 'status.json'}")
    else:
        print(f"Collector enrolled: {directory}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    p = commands.add_parser("install")
    p.add_argument("--url", required=True)
    p.add_argument("--invite", required=True)
    p.add_argument("--label")
    p.add_argument("--state-root", type=Path, default=Path.home() / ".local" / "share" / "pkc-collector")
    p.add_argument("--no-service", action="store_true")
    p = commands.add_parser("run")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--runtime", type=Path, default=Path(__file__).resolve().parent)
    p.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "install":
            install(args)
        else:
            run(args.directory, args.runtime, once=args.once)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Collector: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
