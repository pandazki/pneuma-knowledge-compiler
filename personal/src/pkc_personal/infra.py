"""The shared middleware stack and shallow probes, independent of any engine."""

from __future__ import annotations

import json
import os
import socket
import subprocess

from pneuma_knowledge_service.infra.compose import render_middleware_compose

from pkc_personal.home import Home, atomic_write
from pkc_personal.library import libraries, persist_owner_profile


def docker_reachable() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def tcp_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def pid_alive(pid: int | None) -> bool:
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def render_compose(home: Home) -> bool:
    config = home.config.infra
    ports = config.ports.model_dump()
    ports["pg"] = ports.pop("postgres")
    text = render_middleware_compose(
        project_name=config.compose_project, ports=ports, data_dir=config.data_dir,
        pg_password=config.pg_password, meili_key=config.meili_key,
        rustfs_access_key=config.rustfs_access_key, rustfs_secret_key=config.rustfs_secret_key,
    )
    path = home.path / "infra" / "docker-compose.yml"
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    atomic_write(path, text)
    return True


def compose(home: Home, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", "-f", str(home.path / "infra" / "docker-compose.yml"),
         "-p", home.config.infra.compose_project, *args],
        check=True, capture_output=True, text=True,
    )


def stack_running(home: Home) -> bool:
    try:
        output = compose(home, "ps", "--all", "--format", "json").stdout.strip()
        rows = json.loads(output) if output.startswith("[") else [json.loads(line) for line in output.splitlines()]
        by_service = {row["Service"]: row for row in rows}
        return all(
            by_service.get(name, {}).get("State") == "running"
            and by_service[name].get("Health", "") in {"", "healthy"}
            for name in ("postgres", "qdrant", "meilisearch", "rustfs")
        )
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return False


def up(home: Home) -> None:
    from pkc_personal import engine

    changed = render_compose(home)
    if changed or not stack_running(home):
        compose(home, "up", "-d", "--wait")
    for library in libraries(home):
        library.record_step("infra")
        # A library created while the stack was down has no persisted profile, and an
        # unknown tenant is answered with a synthetic mock person. Write the one the engine
        # directory already holds before the engine that would serve it starts.
        persist_owner_profile(home, library, only_if_missing=True)
        engine.start(home, library)


def down(home: Home) -> None:
    from pkc_personal import engine

    for library in libraries(home):
        engine.stop(home, library)
    if (home.path / "infra" / "docker-compose.yml").is_file():
        compose(home, "down")
