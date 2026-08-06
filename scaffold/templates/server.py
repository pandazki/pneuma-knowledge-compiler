"""Framework API server for this project's browsing layer (compose `api` service).

The everyday flow is the CLI and needs none of this. This entrypoint exists so the project
can be opened in a browser — the library, its sources, every citation, and the Engine Console
over engine/ — which needs the framework HTTP API running with THIS project's compile
contract registered: the framework ships no domain contract, so an unregistered API could
serve sources but never a skill. The contract is loaded through the driver's own loader
(`app.load_contract_skill`), keeping one parsing path between the CLI and the server.

Settings come from the PNEUMA_KNOWLEDGE_* variables docker-compose.yml sets (service-name
hosts, container paths for engine/ and the canonical library) — deliberately NOT from
`app.build_settings()`, whose localhost ports are right on the host and wrong in a container.

Machinery: do not edit. Regenerate the project to upgrade it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as driver  # noqa: E402 — the neighbouring project driver


def main() -> None:
    import uvicorn
    from pneuma_knowledge_service.api.app import create_app

    skill = driver.load_contract_skill()
    os.environ.setdefault("PNEUMA_KNOWLEDGE_USER_SCHEMA_BASE_VERSION", skill.version)
    driver.apply_prompt_overlays()
    # Keyless browsing is a first-class state, not a degraded one: with no key the API serves
    # the whole library, its sources and its citations, and only the lanes that call a model
    # (ask / deep recall / compile) are unavailable.
    for line in driver.keyless_env(os.environ):
        print(line, flush=True)
    uvicorn.run(create_app(), host="0.0.0.0", port=8080)


if __name__ == "__main__":
    main()
