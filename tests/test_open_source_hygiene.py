"""Hygiene checks for what this repository publishes."""

from __future__ import annotations

import gzip
import re
import subprocess
import tarfile
import zlib
from pathlib import Path

import pytest


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
    ".pytest_cache",
    ".venv",
    "node_modules",
    "dist",
    "__pycache__",
}
SKIP_NAMES = {".env", "pnpm-lock.yaml"}


DENYLIST_PATH = ROOT / "local" / "hygiene-denylist.txt"

_DENYLIST_MISSING = (
    f"no private denylist at {DENYLIST_PATH.relative_to(ROOT)} — content-specific hygiene "
    "is enforced only where that file exists. The terms a repository must never publish are "
    "themselves private: writing them into a tracked test would publish the very list it "
    "guards. Keep them in that git-ignored file, one regex per line."
)


def _denylist_pattern() -> re.Pattern[str] | None:
    """The private terms this repository must never publish, loaded from outside the repository.

    Deliberately NOT a literal list in tracked code. A denylist names what has to stay
    unpublished, so committing one publishes it — and obfuscating the entries by splicing
    string literals fools a grep, not a reader. The tracked half of this file therefore keeps
    only shape-based checks (secret-shaped strings, absolute local paths, embedded archives),
    which need no knowledge of anyone's private vocabulary; the content-specific half reads
    an operator-local file and skips when it is absent, so an outside contributor is never
    failed by a rule they cannot see.
    """
    if not DENYLIST_PATH.exists():
        return None
    terms = [
        line.strip()
        for line in DENYLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if not terms:
        return None
    return re.compile("|".join(terms), re.IGNORECASE)


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


def test_no_provider_key_shapes_in_tracked_files() -> None:
    """No file git tracks may carry a real provider-key-shaped string.

    Shape-based and public-safe (no private vocabulary needed). This exists because a
    `.env.keyed` variant with a real OpenRouter key was once committed and reached the
    brink of a public push — caught by GitHub push protection, not by this suite, since
    suffix-filtered scans skipped the file. Tracked files are scanned regardless of
    suffix. The length floor (40) deliberately clears the short fake keys test fixtures
    use to prove key-rejection behavior."""
    key_shape = re.compile(r"sk-(?:or-v\d+-)?[A-Za-z0-9]{40,}")
    tracked = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8", errors="surrogateescape")
    violations: list[str] = []
    for name in tracked.split("\0"):
        if not name:
            continue
        path = ROOT / name
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in key_shape.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{name}:{line}")
    assert not violations, "provider-key-shaped strings in tracked files:\n" + "\n".join(violations)


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
    pattern = _denylist_pattern()
    if pattern is None:
        pytest.skip(_DENYLIST_MISSING)
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
    pattern = _denylist_pattern()
    if pattern is None:
        pytest.skip(_DENYLIST_MISSING)
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
    pattern = _denylist_pattern()
    if pattern is None:
        pytest.skip(_DENYLIST_MISSING)
    violations: list[str] = []
    for path in _public_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"{path.relative_to(ROOT).as_posix()}:{line}")
    assert not violations, "private project residue:\n" + "\n".join(violations[:100])


def test_retired_stream_feature_term_is_absent_from_public_text() -> None:
    """The open-source product uses Live Context as its only public feature language.

    Verbatim agent transcripts under build-record/trace/ are historical records, not
    product copy — random ids and ordinary English words trip a substring scan,
    and redacting a record to satisfy a grep would falsify it. Product-language
    surfaces (docs, code, README, the build log itself) stay fully covered.
    """
    retired = "c" + "ue"
    pattern = re.compile(re.escape(retired), re.IGNORECASE)
    violations: list[str] = []
    for path in _public_text_files():
        relative = path.relative_to(ROOT).as_posix()
        if "/build-record/trace/" in f"/{relative}":
            continue
        if pattern.search(relative):
            violations.append(f"path:{relative}")
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            violations.append(f"text:{relative}:{line}")
    assert not violations, "retired stream feature term:\n" + "\n".join(violations[:100])


def test_private_brand_language_is_absent_from_compressed_presets() -> None:
    """Release fixtures are public source too; hiding residue under gzip is still residue."""
    pattern = _denylist_pattern()
    if pattern is None:
        pytest.skip(_DENYLIST_MISSING)
    violations: list[str] = []
    scan_roots = [ROOT / "examples" / "data" / "preset", ROOT / "examples" / "opc" / "prebuilt"]
    gz_paths = [p for root in scan_roots for p in sorted(root.rglob("*.gz")) if root.exists()]
    for path in gz_paths:
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
    pattern = _denylist_pattern()
    if pattern is None:
        pytest.skip(_DENYLIST_MISSING)
    patterns = (pattern,)
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


