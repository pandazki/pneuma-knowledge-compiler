from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_SOURCES = (
    ROOT / "packages" / "pneuma-knowledge-core" / "src",
    ROOT / "packages" / "pneuma-knowledge-service" / "src",
    ROOT / "packages" / "pneuma-knowledge-eval" / "src",
)
FRAMEWORK_UI_SOURCE = ROOT / "apps" / "web" / "src"


def test_framework_sources_do_not_import_the_opc_example() -> None:
    for source_root in (*PACKAGE_SOURCES, FRAMEWORK_UI_SOURCE):
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx"}:
                continue
            text = path.read_text(encoding="utf-8")
            assert "examples.opc" not in text


def test_fictional_opc_story_identity_is_example_owned() -> None:
    forbidden = (
        "u-opc-lin",
        "seamlog",
        "relayforge",
        "orion",
        "林舟",
        "林知远",
    )
    for source_root in (*PACKAGE_SOURCES, FRAMEWORK_UI_SOURCE):
        for path in source_root.rglob("*"):
            if not path.is_file() or path.suffix not in {
                ".py",
                ".md",
                ".json",
                ".ts",
                ".tsx",
            }:
                continue
            text = path.read_text(encoding="utf-8").casefold()
            assert not any(value.casefold() in text for value in forbidden), path
