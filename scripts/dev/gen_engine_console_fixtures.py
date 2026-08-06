#!/usr/bin/env python3
"""Regenerate the Engine Console's web fixtures from the real engine machinery.

The console ships mock fixtures (apps/web/src/engine/fixtures/) so the UI runs and
demos without a backend. Hand-written fixtures drift; these are produced by the same
code that serves /v1/engine/* — scaffold-generate a project, drive a few applies
through `apply_changes`, then dump schema/state/history/prompts byte-realistically.

`prompts.json` matters most here: the Prompt Studio renders framework wording verbatim,
so a hand-mocked fixture would put invented prompts in front of anybody demoing it. This
one comes out of core's surface registry resolved against the generated project's own
overlay file, which is exactly what `GET /v1/engine/prompts` answers. There is no
rewrite fixture — that endpoint calls a model, and the fixture mode mocks it client-side.

Usage: uv run python scripts/dev/gen_engine_console_fixtures.py
(regenerates in place; commit the diff if it looks right)
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "apps" / "web" / "src" / "engine" / "fixtures"

sys.path.insert(0, str(REPO / "packages" / "pneuma-knowledge-service" / "src"))
sys.path.insert(0, str(REPO / "packages" / "pneuma-knowledge-core" / "src"))

from pneuma_knowledge_service.engine.apply import Change, apply_changes  # noqa: E402
from pneuma_knowledge_service.engine.files import read_engine_files  # noqa: E402
from pneuma_knowledge_service.engine.gitops import history, version  # noqa: E402
from pneuma_knowledge_service.engine.prompts import (  # noqa: E402
    read_overlays,
    surface_payload,
)
from pneuma_knowledge_service.engine.resolve import resolve_engine  # noqa: E402
from pneuma_knowledge_service.engine.schema import load_schema  # noqa: E402
from pneuma_knowledge_service.settings import Settings  # noqa: E402
from pneuma_knowledge_service.wiring import usable_model_name  # noqa: E402

# One env-pinned knob so the console demonstrates the `env` origin badge.
DEMO_ENV = {"PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP": "80"}

ANSWERS = """\
language = "en"
project_name = "fieldnotes-kb"
[owner]
display_name = "Alex Fieldnotes"
bio = "Solo consultant compiling client fieldnotes"
[data]
mode = "example"
[advanced]
answer_style = "conversational"
challenge_enabled = true
"""


def _dump(name: str, payload: object) -> None:
    path = FIXTURES / name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {path.relative_to(REPO)}")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        answers = Path(tmp) / "answers.toml"
        answers.write_text(ANSWERS)
        target = Path(tmp) / "fieldnotes-kb"
        subprocess.run(
            [sys.executable, str(REPO / "scaffold" / "init.py"),
             "--answers", str(answers), "--target", str(target)],
            check=True, capture_output=True,
        )
        engine = target / "engine"

        # A few realistic applies so the version timeline has a story to tell.
        recall = (engine / "recall" / "recall.yaml").read_text()
        apply_changes(engine, [Change(
            path="recall/recall.yaml",
            content=recall.replace("answer_style: conversational", "answer_style: concise"),
        )], label="Answer style: concise for the grading harness")
        overlays = (engine / "prompts" / "overlays.yaml").read_text()
        apply_changes(engine, [Change(
            path="prompts/overlays.yaml",
            content=overlays.replace(
                "overlays: {}",
                "overlays:\n"
                "  recall.close.answer_honestly: |\n"
                "    When the records do not answer the question, say so plainly and point\n"
                "    to the nearest recorded fact instead of guessing.\n",
            ),
        )], label="Custom honest-close wording")
        recall2 = (engine / "recall" / "recall.yaml").read_text()
        apply_changes(engine, [Change(
            path="recall/recall.yaml",
            content=recall2.replace("answer_style: concise", "answer_style: conversational"),
        )], label="Back to conversational for daily use")

        root = engine.resolve()
        resolved = resolve_engine(root, DEMO_ENV)
        files = read_engine_files(root)
        head = version(root)
        commits = history(root, 50)

        # Per-sha file snapshots. Still a fixture-only FIELD — the real `/history` response is
        # a flat commit list — but no longer fixture-only DATA: `GET /history/{sha}/files`
        # answers exactly this per commit, so fixture mode and the live console can show the
        # same thing (and "load this version into the draft" works in both).
        snapshots: dict[str, dict[str, str]] = {}
        for commit in commits:
            listing = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", commit.sha],
                cwd=root, check=True, capture_output=True, text=True,
            ).stdout.split()
            snapshots[commit.sha] = {
                rel: subprocess.run(
                    ["git", "show", f"{commit.sha}:{rel}"],
                    cwd=root, check=True, capture_output=True, text=True,
                ).stdout
                for rel in listing
            }

        # `keyless` exactly as `GET /v1/engine/state` computes it. The fixture demonstrates a
        # KEYED deployment — the keyless notice has its own test with its own fixture state —
        # so the key a real deployment keeps in .env is supplied here as an init argument,
        # which also keeps the field independent of whatever .env this machine happens to have.
        # (the field's validation alias is the bare variable name, so that is how it is passed)
        keyless = not usable_model_name(
            Settings(**resolved.overrides, OPENROUTER_API_KEY="demo-key"), "recall"
        )

        _dump("schema.json", load_schema())
        _dump("state.json", {
            "keyless": keyless,
            "files": files,
            "values": resolved.values,
            "resolution": resolved.resolution,
            "version": {"head": head.head, "dirty": head.dirty},
        })
        _dump("history.json", {
            "entries": [
                {"sha": c.sha, "label": c.label, "at": c.at, "files": c.files}
                for c in commits
            ],
            "snapshots": snapshots,
        })
        # The studio's own fixture, resolved against this project's overlay file — so the
        # one overridden clause above shows up as an override here too, exactly as the
        # live endpoint would report it.
        _dump("prompts.json", {"surfaces": surface_payload(read_overlays(root))})


if __name__ == "__main__":
    main()
