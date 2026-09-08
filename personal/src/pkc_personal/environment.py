"""One environment and one explicit library resolution for every personal command."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from pneuma_knowledge_service.settings import Settings

from pkc_personal.home import Home
from pkc_personal.library import Library, libraries, validate_name


class LibraryNotChosen(ValueError):
    pass


def home_environment(home: Home, library: Library) -> dict[str, str]:
    config = home.config.infra
    ports = config.ports
    prefix = "PNEUMA_KNOWLEDGE_"
    values = {
        "PG_DSN": f"postgresql://pneuma_knowledge:{quote(config.pg_password, safe='')}@127.0.0.1:{ports.postgres}/pneuma_knowledge",
        "QDRANT_URL": f"http://127.0.0.1:{ports.qdrant}",
        "QDRANT_COLLECTION": "pkc_personal_chunks",
        "MEILI_URL": f"http://127.0.0.1:{ports.meili}",
        "MEILI_KEY": config.meili_key,
        "MEDIA_S3_ENDPOINT_URL": f"http://127.0.0.1:{ports.rustfs}",
        "MEDIA_S3_ACCESS_KEY": config.rustfs_access_key,
        "MEDIA_S3_SECRET_KEY": config.rustfs_secret_key,
        "TENANT": library.state.tenant,
        "ENGINE_DIR": str(library.engine_dir),
        "CANONICAL_ROOT": str(library.path / "canonical"),
        "WORKER_TENANTS": library.state.tenant,
        # The worker reads its posture once, at start, so this is the whole mechanism behind
        # `pkchome config set unattended`: the recorded choice becomes the engine process's
        # environment, and changing it restarts the engine (`library.set_config`).
        "AGENT_UNATTENDED": "true" if library.state.choices.unattended else "false",
    }
    if "project_dir" in Settings.model_fields:
        values["PROJECT_DIR"] = str(library.path)
    if "semantic_retrieval" in Settings.model_fields:
        values["SEMANTIC_RETRIEVAL"] = "on" if library.state.choices.semantic_retrieval else "off"
    env = {prefix + key: value for key, value in values.items()}
    env.update(home.credentials())
    env[prefix + "ENV_FILE"] = ""
    env.update(os.environ)
    return env


def resolve_library(
    home: Home, explicit: str | None = None, environ: dict[str, str] | None = None,
    cwd: str | Path | None = None,
) -> Library:
    env = os.environ if environ is None else environ
    name = explicit if explicit is not None else env.get("PKC_LIBRARY")
    if name is None:
        directory = Path(cwd or Path.cwd()).resolve()
        for ancestor in (directory, *directory.parents):
            binding = ancestor / ".pkc"
            if binding.is_file():
                name = binding.read_text(encoding="utf-8").strip()
                break
    if name is None:
        name = home.current
    if name:
        try:
            validate_name(name)
            return Library.load(home, name)
        except (ValueError, FileNotFoundError):
            pass
    available = ", ".join(library.state.name for library in libraries(home)) or "(none)"
    reason = f"library {name!r} does not exist" if name is not None else "no library chosen"
    raise LibraryNotChosen(
        f"{reason}. Libraries: {available}. Choose with --library NAME, PKC_LIBRARY=NAME, "
        "or pkchome library use NAME. Bind a directory with pkchome library bind NAME ."
    )
