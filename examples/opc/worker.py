"""Framework compile worker for this project's browsing layer (compose `worker` service).

The browser can ingest material (which writes L0 and enqueues jobs), but a queue with no
worker is a waiting room with no doctor: the Process view would sit on "queued" forever. This
mirrors server.py — register THIS project's contract through the driver's own loader, then
hand off to the stock worker loop — so material dropped in the browser flows L0 → index →
compile with no manual step.

Settings come from the PNEUMA_KNOWLEDGE_* variables docker-compose.yml sets, same as
server.py. An idle worker costs nothing, so it runs in the same profile as the API; a keyless
deployment simply never gives it anything that needs a model.

Machinery: do not edit. Regenerate the project to upgrade it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import app as driver  # noqa: E402 — the neighbouring project driver


def main() -> None:
    from pneuma_knowledge_service.workers.compile_worker import main as worker_main

    skill = driver.load_contract_skill()
    os.environ.setdefault("PNEUMA_KNOWLEDGE_USER_SCHEMA_BASE_VERSION", skill.version)
    driver.apply_prompt_overlays()
    for line in driver.keyless_env(os.environ):
        print(line, flush=True)
    worker_main()


if __name__ == "__main__":
    main()
