"""The retrieval choice, editable before middleware or embeddings can start."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import TextIO

from ..engine.apply import Change, apply_changes
from ..engine.files import engine_path


def cmd_config_set(settings, key: str, value: str, *, out: TextIO | None = None,
                   err: TextIO | None = None, as_json: bool = False) -> int:
    out, err = out or sys.stdout, err or sys.stderr
    if key != "semantic_retrieval" or value not in {"on", "off"}:
        print("refused: use `pkc config set semantic_retrieval on|off`", file=err)
        return 2
    root = settings.engine_dir
    if not root:
        print("refused: this deployment has no engine directory; set "
              "PNEUMA_KNOWLEDGE_ENGINE_DIR or PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL", file=err)
        return 2
    try:
        path = engine_path(root, "intake/intake.yaml")
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        # Quote the enum: YAML 1.1 otherwise reads on/off as booleans.
        line = f"semantic_retrieval: {json.dumps(value)}"
        pattern = r"(?m)^semantic_retrieval:[^\n]*"
        content = re.sub(pattern, line, text) if re.search(pattern, text) else text.rstrip() + "\n" + line + "\n"
        sha, effects = apply_changes(root, [Change("intake/intake.yaml", content)],
                                     f"Set semantic retrieval {value}")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"refused: {exc}", file=err)
        return 2
    override = os.environ.get("PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL")
    if as_json:
        print(json.dumps({"key": "intake.semantic_retrieval", "value": value,
                          "commit": sha, "effects": [e.__dict__ for e in effects],
                          "environment_override": override}), file=out)
    else:
        print(f"intake.semantic_retrieval = {value}; restart API/worker; "
              "run rebuild_derived after enabling for existing sources", file=out)
        if override is not None:
            print(f"PNEUMA_KNOWLEDGE_SEMANTIC_RETRIEVAL={override} overrides the engine file; "
                  "update or unset it before restarting", file=out)
    return 0
