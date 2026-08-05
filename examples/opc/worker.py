"""Framework compile worker for the OPC example's browsing layer (compose `worker` service).

The web layer accepts uploads (ingest writes L0 and enqueues jobs), but a queue without a
worker is a waiting room with no doctor: nothing ever compiled, and the Process view sat
on "queued" forever. This entrypoint mirrors server.py — register THIS project's contract
through the scaffold driver's own loader, then hand off to the stock worker loop — so a
document dropped in the browser flows L0 → index → compile without any manual step.

Settings come from PNEUMA_KNOWLEDGE_* environment variables set in docker-compose.yml
(service-name hosts), same as server.py. Keyless deployments simply don't start this
service; browsing never needs it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as scaffold_app  # noqa: E402 — the neighboring scaffold driver


def main() -> None:
    from pneuma_knowledge_service.workers.compile_worker import main as worker_main

    skill = scaffold_app.load_contract_skill()
    os.environ.setdefault("PNEUMA_KNOWLEDGE_USER_SCHEMA_BASE_VERSION", skill.version)
    worker_main()


if __name__ == "__main__":
    main()
