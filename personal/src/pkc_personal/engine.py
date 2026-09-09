"""One detached library engine, using this installation's own Python interpreter."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from pneuma_knowledge_service.settings import Settings

from pkc_personal.environment import home_environment
from pkc_personal.home import Home, atomic_write
from pkc_personal.infra import pid_alive
from pkc_personal.library import Library


def pid_path(home: Home, library: Library) -> Path:
    return home.path / "run" / f"{library.state.name}.pid"


def status(home: Home, library: Library) -> dict:
    path = pid_path(home, library)
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        pid = None
    up = pid_alive(pid)
    return {"pid": pid, "up": up, "port": library.state.engine.port,
            "uptime": max(0.0, time.time() - path.stat().st_mtime) if up else None}


def start(home: Home, library: Library) -> bool:
    if status(home, library)["up"]:
        return False
    if "worker_tenants" not in Settings.model_fields:
        raise RuntimeError(
            "engine startup refused: this library version has no worker_tenants setting; "
            "its worker would drain other libraries' jobs. Upgrade the library tenant-filter seam."
        )
    home.ensure_layout()
    # The edition's own entry, not the library's: it serves the library's application with
    # the home's routes added to it (`pkc_personal.engine_app`), so a console served here has
    # its home face and a library engine keeps serving exactly one library.
    command = [sys.executable, "-m", "pkc_personal.engine_app",
               "--library", library.state.name,
               "--port", str(library.state.engine.port)]
    static = Path(__file__).resolve().parent / "console" / "dist"
    if static.is_dir():
        command.extend(["--static-dir", str(static)])
    with (home.path / "run" / f"{library.state.name}.log").open("ab") as log:
        process = subprocess.Popen(
            command, env=home_environment(home, library), cwd=library.path,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    try:
        if process.poll() is not None:
            raise RuntimeError(f"engine {library.state.name} exited; see its log under {home.path / 'run'}")
        atomic_write(pid_path(home, library), f"{process.pid}\n")
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
        raise
    return True


def stop(home: Home, library: Library) -> bool:
    state = status(home, library)
    path = pid_path(home, library)
    if not state["up"]:
        path.unlink(missing_ok=True)
        return False
    pid = state["pid"]
    # Only our detached process group is stoppable; a stale pid cannot name another group.
    try:
        if os.getpgid(pid) != pid:
            raise RuntimeError(f"refusing to stop pid {pid}: it is not an owned engine process group")
        os.killpg(pid, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while pid_alive(pid) and time.monotonic() < deadline:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass
            time.sleep(0.05)
        if pid_alive(pid):
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    path.unlink(missing_ok=True)
    return True
