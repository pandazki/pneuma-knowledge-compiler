"""Framework API server for the OPC example's browsing layer (compose `api` service).

The plain scaffold flow is CLI-only. This example adds a browser on top, which needs the
framework HTTP API running with THIS project's contract registered — the framework ships
no domain contract, so an unregistered API could serve sources but never a skill. This
entrypoint reuses the scaffold driver's own loader (`app.load_contract_skill`), keeping
one parsing path between the CLI and the server, then hands off to the stock FastAPI app.

Settings come from PNEUMA_KNOWLEDGE_* environment variables set in docker-compose.yml
(service-name hosts) — deliberately NOT from app.build_settings(), whose localhost DSNs
are correct on the host but wrong inside a container.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as scaffold_app  # noqa: E402 — the neighboring scaffold driver

def main() -> None:
    import uvicorn
    from pneuma_knowledge_service.api.app import create_app

    skill = scaffold_app.load_contract_skill()
    os.environ.setdefault("PNEUMA_KNOWLEDGE_USER_SCHEMA_BASE_VERSION", skill.version)
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        # Keyless browsing: deterministic embeddings (dimension-matched to the
        # recommended real model) and no chat models — the library stays fully
        # browsable; ask/recall simply need a key.
        os.environ["PNEUMA_KNOWLEDGE_EMBEDDING_MODEL"] = "fake:1536"
        for role in ("", "_COMPILE", "_RECALL", "_DEEP", "_SKILL", "_EVOLVE", "_LIVE_CONTEXT", "_CHALLENGE"):
            os.environ[f"PNEUMA_KNOWLEDGE_LLM_MODEL{role}"] = ""
    uvicorn.run(create_app(), host="0.0.0.0", port=8080)

if __name__ == "__main__":
    main()
