"""The shared status document: observations only, and never credential values."""

from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import urlopen

from pneuma_knowledge_service.access_stats import RECALL_REBUILD_JOB_KIND
from pneuma_knowledge_service.embedding_key import embedding_key_requirement
from pneuma_knowledge_service.persona_profile import is_placeholder, read_profile_data

from pkc_personal import __version__, console, engine, infra, sync
from pkc_personal.environment import home_environment, resolve_library
from pkc_personal.home import DEFAULT_CALL_TIMEOUT, Home, read_yaml
from pkc_personal.library import Library, engine_components, libraries, pkc_script, posture

# The order the design gives the five steps, whether recorded or derived.
STEP_ORDER = ("infra", "credentials", "profile", "skill", "first_compile")
QUEUE_BUDGET_SECONDS = 1.0


def _jobs(library: Library, *, timeout: float = 1.0, **query: str | int) -> dict:
    if timeout <= 0:
        raise TimeoutError("the queue probe spent its budget")
    url = f"http://127.0.0.1:{library.state.engine.port}/v1/users/{library.state.tenant}/jobs?{urlencode(query)}"
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def _summary(library: Library, *, timeout: float = 1.0) -> dict:
    """`GET /jobs/summary` — the queue's four counts and why the waiting ones wait."""
    if timeout <= 0:
        raise TimeoutError("the queue probe spent its budget")
    url = (f"http://127.0.0.1:{library.state.engine.port}"
           f"/v1/users/{library.state.tenant}/jobs/summary")
    with urlopen(url, timeout=timeout) as response:
        return json.load(response)


def queue_status(library: Library) -> dict | None:
    """Counts and the latest compile, in five bounded reads inside one second."""
    deadline = time.monotonic() + QUEUE_BUDGET_SECONDS

    def left() -> float:
        return deadline - time.monotonic()

    cooling: dict | None = None

    def _pending(state: str) -> int:
        nonlocal cooling
        page = _jobs(library, timeout=left(), limit=1, status=state)["page"]
        # The queue's own answer to "why is nothing moving": a job held back by
        # `not_before` because the harness's subscription is out of room. It rides the page
        # this call already makes, so status costs no extra read for it.
        if state == "queued" and page.get("cooling_until"):
            cooling = {"until": page["cooling_until"], "reason": page.get("cooling_reason") or ""}
        return page["total"]

    try:
        pending = sum(_pending(state) for state in ("queued", "claimed"))
        # Failures are read as one page and counted by kind: forty failed evolve jobs beside
        # fifty-nine successful compiles read as "forty failed" until the kind is named.
        failed_page = _jobs(library, timeout=left(), limit=100, status="failed")
        failed = failed_page["page"]["total"]
        failed_by_kind: dict[str, int] = {}
        for item in failed_page["items"]:
            kind = str(item.get("kind") or "?")
            failed_by_kind[kind] = failed_by_kind.get(kind, 0) + 1
        succeeded = _jobs(library, timeout=left(), limit=1, status="succeeded")["page"]["total"]
        # The derived rebuild, counted on its own: it is the one job an Owner starts by hand
        # (`pkchome rebuild`, and the upgrade that enables a component queues one), so while
        # it waits or runs the report says so rather than folding it into "pending".
        rebuilding = sum(
            _jobs(library, timeout=left(), limit=1, status=state,
                  kind=RECALL_REBUILD_JOB_KIND)["page"]["total"]
            for state in ("queued", "claimed")
        )
        # The endpoint orders by creation, not completion, so ask it for one newest-created
        # page of succeeded compiles and take the latest completion in it. Walking the whole
        # succeeded history to be exact would make every status call grow with the library.
        page = _jobs(library, timeout=left(), limit=20, status="succeeded", kind="compile")
        stamps = [item["completed_at"] for item in page["items"] if item.get("completed_at")]
        # Why anything is WAITING. A job that did not finish goes back to the queue behind a
        # `not_before` with the reason on its row (the engine's `job_retry.py`), so a library
        # whose provider is refusing payment must read as "13 waiting on a payment refusal"
        # rather than as a queue that has silently stopped.
        summary = _summary(library, timeout=left())
        return {"pending": pending, "failed": failed, "failed_by_kind": failed_by_kind,
                "succeeded": succeeded, "rebuilding": rebuilding,
                "last_compile_at": max(stamps, default=None),
                "cooling": cooling, "waiting": summary.get("waiting") or {},
                # The end of that road: work that used up the retry schedule and is now
                # waiting for THIS PERSON. It is the only line in a status report that is a
                # request, so it carries the command that answers it.
                "paused": summary.get("paused") or {}}
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
            # The same kind of recorded choice, and the same rule: what the next engine start
            # obeys. Empty is not a value — it is this library leaving the round's model and
            # effort to the harness's own configuration.
            "agent_model": library.state.choices.model,
            "reasoning_effort": library.state.choices.reasoning_effort,
            "reasoning_effort_episodes": library.state.choices.reasoning_effort_episodes,
            # One round's wall clock, and the default it is measured against: the text face
            # prints it only when this library moved it, because a number every library
            # carries teaches nothing.
            "compile_call_timeout": library.state.choices.compile_call_timeout,
            "compile_call_timeout_default": DEFAULT_CALL_TIMEOUT,
            # Which index components this library's engine enables — read off the engine
            # file, which is the authority, so an Owner who added one by hand sees theirs.
            "components": engine_components(library),
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
    return {"home": {"path": str(home.path), "version": config.install.version if config else __version__,
                     # Machine-wide, like Docker: one built page serves every library here.
                     "console": console.console_state(home)},
            "docker": {"reachable": docker}, "services": services, "libraries": rows}


def local_time(stamp: str) -> str:
    """An ISO instant as the Owner's own clock reads it — this machine's local time.

    The engine answers in UTC because storage is UTC everywhere; the person reading the line
    is deciding whether to wait, and "09:23 tomorrow" is the answer to that question while
    "01:23Z" is a conversion exercise.
    """
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return str(stamp)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone().strftime("%Y-%m-%d %H:%M")


def clock_time(stamp: str) -> str:
    """An ISO instant as a clock reads it — `14:05` today, `09-16 14:05` any other day.

    The question a waiting line answers is "how long do I wait", and a full date on every
    entry of a five-entry line is four dates nobody needed.
    """
    rendered = local_time(stamp)
    today = datetime.now().astimezone().strftime("%Y-%m-%d")
    if rendered.startswith(today + " "):
        return rendered[len(today) + 1:]
    return rendered[5:] if rendered[:4].isdigit() else rendered


def waiting_line(library: dict) -> str:
    """`13 · codex usage limit ×9 (next 14:05) · …`, or "" when nothing is waiting.

    Reasons as the engine grouped them, biggest first, bounded to the five that matter: a
    line that names every distinct provider sentence is a line nobody finishes reading.
    """
    waiting = (library.get("queue") or {}).get("waiting") or {}
    count = int(waiting.get("count", 0) or 0)
    if not count:
        return ""
    parts = [str(count)]
    for entry in (waiting.get("reasons") or [])[:5]:
        when = entry.get("next_retry_at")
        parts.append(
            f"{entry.get('reason') or 'unstated'} ×{entry.get('count', 0)}"
            + (f" (next {clock_time(when)})" if when else "")
        )
    return " · ".join(parts)


def paused_line(library: dict) -> str:
    """`3 · codex usage limit ×3 — pkc jobs resume`, or "" when nothing is paused.

    A paused job is the one thing in a library that will not move until the Owner does
    something, so the line ends in the command rather than leaving them to find it.
    """
    paused = (library.get("queue") or {}).get("paused") or {}
    count = int(paused.get("count", 0) or 0)
    if not count:
        return ""
    parts = [str(count)]
    for entry in (paused.get("reasons") or [])[:5]:
        parts.append(f"{entry.get('reason') or 'unstated'} ×{entry.get('count', 0)}")
    return " · ".join(parts) + " — pkc jobs resume"


def worker_line(library: dict) -> str:
    """The worker's posture, and what is holding it back when something is.

    A worker that is claiming nothing looks exactly like a worker that is broken, which is
    the whole reason this line says more than one word: a cooling period is a stated wait
    with an end on it, and an Owner who can see it does not go looking for a fault.
    """
    line = posture(library["unattended"])
    cooling = (library.get("queue") or {}).get("cooling") if library.get("queue") else None
    if not cooling:
        return line
    reason = cooling.get("reason") or "the harness is unavailable"
    return f"{line} — cooling until {local_time(cooling['until'])} ({reason})"


def rounds_line(library: dict) -> str:
    """The model and effort the library's rounds run at, and episodes' own effort when set."""
    line = (f"{library['agent_model'] or 'the harness default model'}"
            f" at {library['reasoning_effort'] or 'the harness default effort'}")
    episodes = library.get("reasoning_effort_episodes")
    if episodes:
        line = f"{line} (episodes {episodes})"
    timeout = library.get("compile_call_timeout")
    default = library.get("compile_call_timeout_default", DEFAULT_CALL_TIMEOUT)
    if timeout and timeout != default:
        line = f"{line}, up to {timeout}s each"
    return line


def render_text(document: dict) -> str:
    def state(value):
        return "unknown" if value is None else "up" if value else "down"

    def step(value):
        return "done" if value is True else (value or "not completed")

    lines = [f"Home: {document['home']['path']} (v{document['home']['version']})",
             f"Console: {document['home'].get('console', 'unknown')}",
             f"Docker: {state(document['docker']['reachable'])}"]
    for name, probe in document["services"].items():
        lines.append(f"{name}: {state(probe['up'])} (port {probe['port'] or 'unconfigured'})")
    for library in document["libraries"]:
        lines.extend(["", f"{library['name']}{' (current)' if library['current'] else ''}",
                      f"  Engine: {state(library['engine']['up'])} (port {library['engine']['port']})",
                      f"  Worker: {worker_line(library)}",
                      f"  Rounds: {rounds_line(library)}",
                      f"  Components: {library['components'] or 'none'}",
                      f"  Engine directory: {library['engine_dir']}",
                      f"  Embedding key: {'present' if library['key'] else 'absent'}",
                      f"  Canonical HEAD: {library['canonical_head'] or 'empty'}",
                      f"  Skill: {'unknown' if library['skill_fresh'] is None else 'fresh' if library['skill_fresh'] else 'drifted'}",
                      f"  Queue: {json.dumps(library['queue']) if library['queue'] is not None else 'unknown'}"])
        rebuilding = (library.get("queue") or {}).get("rebuilding") or 0
        if rebuilding:
            # A rebuild is the one job whose progress the Owner is waiting on directly: they
            # ran `pkchome rebuild`, or an upgrade enabled a component and queued one, and
            # until it finishes the library answers dated questions about part of itself.
            lines.append(f"  Rebuild: {rebuilding} derived rebuild job(s) in the queue")
        waiting = waiting_line(library)
        if waiting:
            lines.append(f"  Waiting: {waiting}")
        paused = paused_line(library)
        if paused:
            lines.append(f"  Paused: {paused}")
        lines.append(f"  Last used: {library['last_used'] or 'never'}")
        lines.extend(f"  {name}: {step(stamp)}" for name, stamp in library["steps"].items())
    return "\n".join(lines)
