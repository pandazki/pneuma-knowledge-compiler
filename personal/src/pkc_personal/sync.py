"""Application sync and status over the stdlib converter shipped in the global skill."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import importlib.util
import sys

from pkc_personal.home import Home, asset_path
from pkc_personal.library import Library


@lru_cache(maxsize=1)
def converter():
    spec = importlib.util.spec_from_file_location(
        "pkc_personal._agent_sessions", asset_path("skill/scripts/agent_sessions.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run(home: Home, library: Library, *, dry_run: bool = False, rewritten: str = "report") -> dict:
    from pkc_personal.engine_app import pkchome_command

    return converter().sync_pass(
        library.show(), [item.model_dump() for item in library.state.watch],
        dry_run=dry_run, rewritten=rewritten, pkchome=pkchome_command(home))


def status(home: Home, library: Library) -> dict:
    script = converter()
    state = script.read_sync_state(library.path / "sync-state.json")
    config = home.config.sync
    watching = [item.path for item in library.state.watch]
    last = state.get("last_run_at")
    next_due = None
    if watching and config.enabled:
        # No run means due immediately; epoch is stable across polls and process restarts.
        next_due = ((datetime.fromisoformat(last) + timedelta(minutes=config.interval_minutes))
                    if last else datetime.fromtimestamp(0, timezone.utc)).isoformat()
    # Counts only, whatever an older state file holds: a full report here is what made a
    # status document weigh half a megabyte.
    result = state.get("last_result")
    if isinstance(result, dict):
        result = {key: result[key] for key in script.SYNC_COUNTS if key in result}
    return {"last_run_at": last, "last_result": result,
            "watching": watching, "next_due": next_due,
            "next_due_ms": int(datetime.fromisoformat(next_due).timestamp() * 1000) if next_due else None,
            "running": script.sync_running(home.path / "run" / f"{library.state.name}.sync.lock"),
            "held": sum(entry.get("held") is not None for entry in state["sessions"].values())}
