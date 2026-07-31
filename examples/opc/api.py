"""FastAPI entrypoint with the OPC example's deployment-owned assets registered."""

from __future__ import annotations

import os

from pneuma_knowledge_service.api.app import create_app

from .environment import example_settings


MODE = os.environ.get("PNEUMA_OPC_EXAMPLE_MODE", "keyless")
if MODE not in {"keyless", "real"}:
    raise RuntimeError(f"invalid PNEUMA_OPC_EXAMPLE_MODE: {MODE!r}")

app = create_app(example_settings(MODE))  # type: ignore[arg-type]
