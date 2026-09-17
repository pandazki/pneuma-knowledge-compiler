"""Application sync and status over the stdlib converter shipped in the global skill."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache
import importlib.util
from pathlib import Path
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


#: The triage thresholds the home records and the converter applies. Named here so the two
#: spellings cannot drift: a threshold the Owner sets and the pass ignores is worse than none.
THRESHOLDS = ("min_owner_turns", "min_owner_chars", "ack_max_words")

#: The harnesses a root can belong to, as `sync.roots` spells them. `claude-code` is the same
#: harness under the name the watch list uses, accepted so one spelling works in both places.
HARNESSES = ("codex", "claude")
HARNESS_ALIASES = {"claude-code": "claude"}


def run(home: Home, library: Library, *, dry_run: bool = False, rewritten: str = "report") -> dict:
    from pkc_personal.engine_app import pkchome_command

    config = home.config.sync
    script = converter()
    return script.sync_pass(
        library.show(), [item.model_dump() for item in library.state.watch],
        dry_run=dry_run, rewritten=rewritten, pkchome=pkchome_command(home),
        claude_roots=script.claude_session_roots(config.roots.claude),
        codex_roots=script.codex_session_roots(config.roots.codex),
        exclude=list(config.exclude), home=str(home.path),
        options={key: getattr(config, key) for key in THRESHOLDS},
        max_part_chars=config.max_part_chars)


def harness(name: str) -> str:
    """One harness name as `sync.roots` spells it, or a refusal naming the set."""
    chosen = HARNESS_ALIASES.get(name.strip(), name.strip())
    if chosen not in HARNESSES:
        raise ValueError(f"harness must be one of {', '.join(HARNESSES)}")
    return chosen


def roots(home: Home) -> list[dict]:
    """Every directory this home's next pass will read, in scan order.

    Discovered and configured together, each saying which it is and whether it exists today,
    because the question this answers is the Owner's: is the directory my sessions actually
    land in being read at all?
    """
    script = converter()
    config = home.config.sync
    listed = []
    for name, found in (("codex", script.codex_session_roots(config.roots.codex)),
                        ("claude", script.claude_session_roots(config.roots.claude))):
        configured = {str(Path(path).expanduser().resolve()) for path in getattr(config.roots, name)}
        listed += [{"harness": name, "path": str(path), "exists": path.is_dir(),
                    "source": "configured" if str(path) in configured else "discovered"}
                   for path in found]
    return listed


def set_root(home: Home, name: str, directory: str, *, remove: bool = False) -> None:
    """Add or remove one extra root. Discovered roots are not on this list and cannot be
    removed from it: they are found again on the next pass, which is the point of finding them."""
    chosen = harness(name)
    path = str(Path(directory).expanduser().resolve())
    if not remove and not Path(path).is_dir():
        raise ValueError("sync roots add needs an existing directory")
    config = home.config
    current = list(getattr(config.sync.roots, chosen))
    setattr(config.sync.roots, chosen,
            [item for item in current if item != path] if remove
            else current if path in current else [*current, path])
    home.save_config(config)


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
