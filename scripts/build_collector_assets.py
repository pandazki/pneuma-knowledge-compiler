#!/usr/bin/env python3
"""Package the actual shared decoder and native collector as Worker static assets."""

import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "apps" / "collector-cloud" / "public"
SOURCES = [ROOT / "personal" / "collector" / "collector.py",
           ROOT / "personal" / "collector" / "install.sh",
           ROOT / "personal" / "skill" / "scripts" / "agent_sessions.py"]


def main():
    TARGET.mkdir(parents=True, exist_ok=True)
    files = {}
    for source in SOURCES:
        payload = source.read_bytes()
        files[source.name] = hashlib.sha256(payload).hexdigest()
        shutil.copyfile(source, TARGET / source.name)
    (TARGET / "release.json").write_text(json.dumps({"version": 1, "files": files}, indent=2) + "\n")


if __name__ == "__main__":
    main()
