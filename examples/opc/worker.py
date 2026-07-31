"""Compile-worker entrypoint with the OPC example configuration registered first."""

from __future__ import annotations

import os

from pneuma_knowledge_service.workers.compile_worker import main

from .environment import example_settings


if __name__ == "__main__":
    mode = os.environ.get("PNEUMA_OPC_EXAMPLE_MODE", "keyless")
    if mode not in {"keyless", "real"}:
        raise RuntimeError(f"invalid PNEUMA_OPC_EXAMPLE_MODE: {mode!r}")
    settings = example_settings(mode)  # type: ignore[arg-type]
    # The generic worker constructs Settings at process start. Export the
    # mode-specific collection chosen by this example before handing off.
    os.environ["PNEUMA_KNOWLEDGE_QDRANT_COLLECTION"] = settings.qdrant_collection
    main()
