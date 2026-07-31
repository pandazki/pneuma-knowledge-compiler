"""Migration acceptance tests for the public repository contract.

These checks intentionally run before implementation during the RED phase.
"""

from __future__ import annotations

import gzip
import re
import subprocess
import tarfile
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    "",
    ".css",
    ".example",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".sql",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
SKIP_PARTS = {
    ".git",
    ".impeccable",
    ".pytest_cache",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
}
SKIP_NAMES = {".env", "pnpm-lock.yaml"}


def _private_brand_pattern() -> re.Pattern[str]:
    upstream = "e" + "ven"
    lookalike = "e" + "van"
    alternatives = [
        rf"{upstream}[\s_-]*realities",
        rf"{upstream}[\s_-]*(?:ai|agent|hub|trace)",
        rf"{lookalike}[\s_-]*ai",
        rf"\b{lookalike}\b",
        rf"{upstream}[\s_-]*(?:app|glass(?:es)?|kb|knowledge)",
        rf"smart[\s_-]*glass(?:es)?",
        rf"{upstream}kb",
        rf"{upstream}_user_id",
        rf"{upstream}userid",
        "glass" + "es",
        "vibe" + "coding",
        "眼" + "镜",
        "佩" + "戴者",
    ]
    return re.compile("|".join(alternatives), re.IGNORECASE)


def _legacy_demo_pattern() -> re.Pattern[str]:
    """Reject the migrated enterprise demo vocabulary, not generic business concepts."""
    alternatives = [
        "ac" + "me",
        "apo" + "llo",
        "alice" + r"\s+" + "chen",
        "bob" + r"\s+" + "lee",
        "vendor" + r"[-_ ]*" + "k",
        "u-demo-" + "(?:mei|alex)",
    ]
    return re.compile("|".join(alternatives), re.IGNORECASE)


def _private_project_residue_pattern() -> re.Pattern[str]:
    """Non-brand identifiers that previously exposed private fixtures or operations."""
    alternatives = [
        r"\b" + "el" + "khorn" + r"\b",
        r"\b" + "lu" + "na" + r"\b",
        "gpt-" + r"5\.6-(?:lu" + "na|s" + "ol)",
        "private" + r"[\s_-]*" + "gold",
        "u-" + r"(?:alice|bob|chen|marcus|shen|dana|zhou)\b",
        r"\breal-\d+-t\d+\b",
        r"\b" + "s-" + "001" + r"\b",
        "paint" + r"\s+" + "brush",
        "heat" + r"\s+" + "some" + r"\s+" + "oil",
        "智能" + "手环",
        "智能" + "硬件公司",
    ]
    return re.compile("|".join(alternatives), re.IGNORECASE)


def _git_ignored(paths: list[Path]) -> set[Path]:
    """Paths git considers ignored — i.e. content this repository never publishes.

    The hygiene invariant is about what ships, so a deliberately private working-tree path
    must not be judged as public text. `.gitignore` already excludes per-user canonical
    repositories (`/data/`), local experiment projects and benchmark run outputs, all of
    which legitimately hold real material; scanning them made the check fail on content
    that is not part of the open repository at all. Asking git keeps this list from drifting
    away from `.gitignore`.
    """
    if not paths:
        return set()
    # `-z` on both sides: without it git C-quotes any path containing non-ASCII bytes
    # (`"local/…\344\270\216…"`), which silently fails to match the path we asked about —
    # so ignored files with CJK names would be scanned anyway.
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin", "-z"],
        cwd=ROOT,
        input="\0".join(str(p) for p in paths).encode("utf-8"),
        capture_output=True,
        check=False,
    )
    # exit 0 = some ignored (listed on stdout), 1 = none ignored, >1 = real error.
    if proc.returncode > 1:
        raise RuntimeError(f"git check-ignore failed: {proc.stderr.decode(errors='replace').strip()}")
    out = proc.stdout.decode("utf-8", errors="surrogateescape")
    return {Path(entry) for entry in out.split("\0") if entry}


def _public_text_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if (
            not path.is_file()
            or path.name in SKIP_NAMES
            or any(part in SKIP_PARTS for part in path.parts)
        ):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            files.append(path)
    ignored = _git_ignored(files)
    return [path for path in files if path not in ignored]


def test_public_package_topology_matches_spec() -> None:
    expected = [
        ROOT / "packages" / "pneuma-knowledge-core",
        ROOT / "packages" / "pneuma-knowledge-service",
        ROOT / "apps" / "web",
        ROOT / "infra",
        ROOT / "examples",
    ]
    missing = [str(path.relative_to(ROOT)) for path in expected if not path.exists()]
    assert not missing, f"missing migrated architecture: {missing}"


def test_private_brand_language_is_absent_from_paths_and_text() -> None:
    pattern = _private_brand_pattern()
    violations: list[str] = []
    for path in _public_text_files():
        relative = path.relative_to(ROOT).as_posix()
        if pattern.search(relative):
            violations.append(f"path:{relative}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"text:{relative}:{line}")
    assert not violations, "private brand residue:\n" + "\n".join(violations[:100])


def test_legacy_enterprise_demo_is_absent_from_public_product_assets() -> None:
    """Public defaults stay free of the separated enterprise demo."""
    pattern = _legacy_demo_pattern()
    roots = [
        ROOT / "apps" / "web" / "public",
        ROOT / "apps" / "web" / "src",
        ROOT / "examples",
        ROOT / "scripts",
        ROOT / "docs",
        ROOT / "README.md",
        ROOT / "PRODUCT.md",
        ROOT / "DESIGN.md",
    ]
    violations: list[str] = []
    candidates: list[Path] = []
    for root in roots:
        if root.is_file():
            candidates.append(root)
        elif root.exists():
            candidates.extend(
                path
                for path in root.rglob("*")
                if path.is_file()
                and not any(part in SKIP_PARTS for part in path.parts)
                and path.suffix.lower() in TEXT_SUFFIXES
            )
    ignored = _git_ignored(candidates)
    for path in candidates:
        if path in ignored:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        match = pattern.search(text)
        if match:
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
    assert not violations, "legacy enterprise demo residue:\n" + "\n".join(violations)


def test_private_project_identifiers_are_absent_from_public_text() -> None:
    pattern = _private_project_residue_pattern()
    violations: list[str] = []
    for path in _public_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
    assert not violations, "private project residue:\n" + "\n".join(violations[:100])


def test_retired_stream_feature_term_is_absent_from_public_text() -> None:
    """The open-source product uses Live Context as its only public feature language."""
    retired = "c" + "ue"
    pattern = re.compile(re.escape(retired), re.IGNORECASE)
    violations: list[str] = []
    for path in _public_text_files():
        relative = path.relative_to(ROOT).as_posix()
        if pattern.search(relative):
            violations.append(f"path:{relative}")
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"text:{relative}:{line}")
    assert not violations, "retired stream feature term:\n" + "\n".join(violations[:100])


def test_private_brand_language_is_absent_from_compressed_presets() -> None:
    """Release fixtures are public source too; hiding residue under gzip is still residue."""
    pattern = _private_brand_pattern()
    violations: list[str] = []
    preset_root = ROOT / "examples" / "data" / "preset"
    for path in sorted(preset_root.rglob("*.gz")):
        try:
            payload = gzip.decompress(path.read_bytes()).decode("utf-8", errors="ignore")
        except (OSError, EOFError):
            continue
        if pattern.search(payload):
            violations.append(path.relative_to(ROOT).as_posix())
    assert not violations, "private brand residue in compressed presets:\n" + "\n".join(
        violations
    )


def test_private_residue_is_absent_from_tar_members_and_embedded_git_objects() -> None:
    """A canonical tar contains compressed loose Git objects; scan their real payloads."""
    patterns = (_private_brand_pattern(), _private_project_residue_pattern())
    violations: list[str] = []
    for archive in sorted(ROOT.rglob("*.tar.gz")):
        if any(part in SKIP_PARTS for part in archive.parts):
            continue
        with tarfile.open(archive, mode="r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                stream = tar.extractfile(member)
                if stream is None:
                    continue
                payload = stream.read()
                if re.search(r"(?:^|/)\.git/objects/[0-9a-f]{2}/[0-9a-f]{38}$", member.name):
                    try:
                        payload = zlib.decompress(payload)
                    except zlib.error:
                        pass
                text = payload.decode("utf-8", errors="ignore")
                if any(pattern.search(text) for pattern in patterns):
                    violations.append(
                        f"{archive.relative_to(ROOT).as_posix()}::{member.name}"
                    )
    assert not violations, "private residue in tar payloads:\n" + "\n".join(violations)


def test_product_and_migration_contracts_exist() -> None:
    assert (ROOT / "PRODUCT.md").is_file()
    assert (ROOT / "docs" / "specs" / "open-source-migration.md").is_file()
    assert (ROOT / "docs" / "ubiquitous-language.md").is_file()
