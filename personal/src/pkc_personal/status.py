"""The shared status document: observations only, and never credential values."""

from __future__ import annotations

import json
import subprocess
import time
from urllib.parse import urlencode
from urllib.request import urlopen

from pneuma_knowledge_service.embedding_key import embedding_key_requirement
from pneuma_knowledge_service.persona_profile import is_placeholder, read_profile_data

from pkc_personal import __version__, engine, infra, sync
from pkc_personal.environment import home_environment, resolve_library
from pkc_personal.home import Home, read_yaml
from pkc_personal.library import Library, libraries, pkc_script, posture

# The order the design gives the five steps, whether recorded or derived.
STEP_ORDER = ("infra", "credentials", "profile", "skill", "first_compile")
QUEUE_BUDGET_SECONDS = 1.0


def _jobs(library: Library, *, timeout: float = 1.0, **query: str | int) -> dict:
    if timeout <= 0:
        raise TimeoutError("the queue probe spent its budget")
    url = f"http://127.0.0.1:{library.state.engine.port}/v1/users/{library.state.tenant}/jobs?{urlencode(query)}"
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def queue_status(library: Library) -> dict | None:
    """Counts and the latest compile, in four bounded reads inside one second."""
    deadline = time.monotonic() + QUEUE_BUDGET_SECONDS

    def left() -> float:
        return deadline - time.monotonic()

    try:
        pending = sum(_jobs(library, timeout=left(), limit=1, status=status)["page"]["total"]
                      for status in ("queued", "claimed"))
        # Failures are read as one page and counted by kind: forty failed evolve jobs beside
        # fifty-nine successful compiles read as "forty failed" until the kind is named.
        failed_page = _jobs(library, timeout=left(), limit=100, status="failed")
        failed = failed_page["page"]["total"]
        failed_by_kind: dict[str, int] = {}
        for item in failed_page["items"]:
            kind = str(item.get("kind") or "?")
            failed_by_kind[kind] = failed_by_kind.get(kind, 0) + 1
        succeeded = _jobs(library, timeout=left(), limit=1, status="succeeded")["page"]["total"]
        # The endpoint orders by creation, not completion, so ask it for one newest-created
        # page of succeeded compiles and take the latest completion in it. Walking the whole
        # succeeded history to be exact would make every status call grow with the library.
        page = _jobs(library, timeout=left(), limit=20, status="succeeded", kind="compile")
        stamps = [item["completed_at"] for item in page["items"] if item.get("completed_at")]
        return {"pending": pending, "failed": failed, "failed_by_kind": failed_by_kind,
                "succeeded": succeeded, "last_compile_at": max(stamps, default=None)}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def canonical_head(library: Library) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(library.canonical_dir), "rev-parse", "--verify", "HEAD"],
            capture_output=True, text=True, timeout=1,
        )
        return result.stdout.strip() if result.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _is_compile_subject(subject: str) -> bool:
    """`compile`, `compile <job id>` — the subject the compile runner commits under."""
    head = subject.strip().split(maxsplit=1)[0] if subject.strip() else ""
    return head.rstrip(":").lower() == "compile"


def first_compile_at(library: Library) -> str | None:
    """Derived, never recorded: the oldest compile commit in the canonical repository.

    `pkc draft finish` is the library's command and cannot write `library.yaml`, so the
    completion is read where it actually landed — the canonical history itself.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(library.canonical_dir), "log", "--format=%cI\x1f%s"],
            capture_output=True, text=True, timeout=1,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    stamp = None
    for line in result.stdout.splitlines():
        date, separator, subject = line.partition("\x1f")
        if separator and _is_compile_subject(subject):
            stamp = date  # the log runs newest first, so the last match is the first compile
    return stamp or None


def profile_settled(home: Home, library: Library) -> bool | None:
    """Derived, never recorded: the library's own answer about its Owner profile.

    Done means the profile is no longer the placeholder AND no field is still an
    unconfirmed inference. An unreachable or unreadable library answers null, not false:
    status reports what it observed, and it observed nothing.

    The engine file and persisted profile must both be settled. The personal edition's
    untouched template is unstated even when it carries legacy Owner/other/mid slots.
    """
    from pneuma_knowledge_core.persona.provenance import inferred_fields
    from pneuma_knowledge_service.engine.files import parse_mapping
    from pneuma_knowledge_service.persona_profile import owner_profile
    from pkc_personal.library import _engine_files

    try:
        data = read_profile_data(library.engine_dir)
        template = _engine_files(library.state.name, library.state.choices, "")["persona/profile.yaml"]
        if data == parse_mapping("persona/profile.yaml", template):
            return None
        declared = owner_profile(library.state.tenant, data)
        if is_placeholder(declared) or inferred_fields(declared):
            return None
    except (OSError, ValueError):
        return None
    try:
        result = subprocess.run(
            [pkc_script(), "profile", "show", "--json"],
            env=home_environment(home, library), cwd=library.path,
            capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict) or payload.get("placeholder") is not False:
        return None
    profile = payload.get("profile")
    if not isinstance(profile, dict):
        return None
    if is_placeholder(profile):
        return None
    # Older records carry no provenance map at all; what was never marked was never inferred.
    provenance = profile.get("provenance") or {}
    if not isinstance(provenance, dict):
        return None
    if any(value == "inferred" for value in provenance.values()):
        return None
    return True


def steps_document(home: Home, library: Library, *, probe_profile: bool) -> dict:
    """Three recorded steps and two derived ones, under the five names status always shows."""
    recorded = library.state.steps.model_dump(mode="json")
    derived = {"profile": profile_settled(home, library) if probe_profile else None,
               "first_compile": first_compile_at(library)}
    return {name: recorded.get(name, derived.get(name)) for name in STEP_ORDER}


def skill_fresh(home: Home, library: Library) -> bool | None:
    if library.state.steps.skill is None and not library.skill_dir.exists():
        return None
    try:
        result = subprocess.run(
            # A project verify, not `--dir`: the package is INSTALLED into the library
            # directory (the project a harness stands in here), so the router block in its
            # instructions file is part of the question — a skill whose files are current
            # but which nothing points at is present, not installed.
            [pkc_script(), "skill", "verify", "--project", str(library.path),
             "--backend", library.skill_backend],
            env=home_environment(home, library), cwd=library.path, capture_output=True, timeout=30,
        )
        return True if result.returncode == 0 else False if result.returncode == 4 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def status_document(home: Home, explicit: str | None = None) -> dict:
    docker = infra.docker_reachable()
    config = home.config if home.configured else None
    services = {}
    for name in ("postgres", "qdrant", "meili", "rustfs"):
        port = getattr(config.infra.ports, name) if config else None
        services[name] = {"port": port, "up": infra.tcp_port_open("127.0.0.1", port) if docker and port else None}
    selected = [resolve_library(home, explicit)] if explicit is not None else libraries(home)
    credentials = home.credentials()
    rows = []
    for library in selected:
        engine_state = engine.status(home, library)
        model = read_yaml(library.engine_dir / "engine.yaml").get("embedding", library.state.choices.embedding)
        requirement = embedding_key_requirement(model)
        rows.append({
            "name": library.state.name, "tenant": library.state.tenant,
            "current": home.current == library.state.name,
            "engine": engine_state,
            # The recorded posture, not a probe of the running worker: it is the choice the
            # next engine start obeys, and `config set unattended` restarts to make them one.
            "unattended": library.state.choices.unattended,
            # No probe of an engine port whose pid is dead: a status taken with nothing up
            # must cost nothing but the reads that can still answer.
            "queue": queue_status(library) if engine_state["up"] else None,
            "key": bool(requirement and credentials.get(requirement[0], "").strip()),
            "engine_dir": str(library.engine_dir), "canonical_head": canonical_head(library),
            "skill_fresh": skill_fresh(home, library),
            # The profile lives in the library's store, so the question is only askable
            # while the store is reachable.
            "steps": steps_document(home, library, probe_profile=bool(services["postgres"]["up"])),
            "last_used": library.state.last_used,
            "sync": sync.status(home, library),
        })
    return {"home": {"path": str(home.path), "version": config.install.version if config else __version__},
            "docker": {"reachable": docker}, "services": services, "libraries": rows}


def render_text(document: dict) -> str:
    def state(value):
        return "unknown" if value is None else "up" if value else "down"

    def step(value):
        return "done" if value is True else (value or "not completed")

    lines = [f"Home: {document['home']['path']} (v{document['home']['version']})",
             f"Docker: {state(document['docker']['reachable'])}"]
    for name, probe in document["services"].items():
        lines.append(f"{name}: {state(probe['up'])} (port {probe['port'] or 'unconfigured'})")
    for library in document["libraries"]:
        lines.extend(["", f"{library['name']}{' (current)' if library['current'] else ''}",
                      f"  Engine: {state(library['engine']['up'])} (port {library['engine']['port']})",
                      f"  Worker: {posture(library['unattended'])}",
                      f"  Engine directory: {library['engine_dir']}",
                      f"  Embedding key: {'present' if library['key'] else 'absent'}",
                      f"  Canonical HEAD: {library['canonical_head'] or 'empty'}",
                      f"  Skill: {'unknown' if library['skill_fresh'] is None else 'fresh' if library['skill_fresh'] else 'drifted'}",
                      f"  Queue: {json.dumps(library['queue']) if library['queue'] is not None else 'unknown'}",
                      f"  Last used: {library['last_used'] or 'never'}"])
        lines.extend(f"  {name}: {step(stamp)}" for name, stamp in library["steps"].items())
    return "\n".join(lines)
