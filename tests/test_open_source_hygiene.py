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


def test_the_eval_package_is_a_leaf_and_cannot_leak_into_what_it_judges() -> None:
    """Invariant I6, as a fact about the import graph rather than a discipline.

    An eval dataset holds the answers, the rubrics and the expected evidence. Nothing in a
    compile or a recall input may come from there, and the mechanism is the package
    direction: `eval` depends on `core`, and neither `core` nor `service` — nor the ops
    scripts, nor the scaffold — may name it. A leak would need an import that does not
    exist, and this test is what keeps it from being added by accident.
    """
    watched = [
        ROOT / "packages" / "pneuma-knowledge-core" / "src",
        ROOT / "packages" / "pneuma-knowledge-service" / "src",
        ROOT / "packages" / "pneuma-knowledge-strategies" / "src",
        ROOT / "scripts",
        ROOT / "scaffold",
    ]
    offenders: list[str] = []
    for root in watched:
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            for line_no, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if not (stripped.startswith("import ") or stripped.startswith("from ")):
                    continue
                if "pneuma_knowledge_eval" in stripped:
                    offenders.append(f"{path.relative_to(ROOT)}:{line_no}")
    assert not offenders, (
        "the eval package must stay a leaf (I6); imported from:\n" + "\n".join(offenders)
    )
    # …and the dependency it declares runs the other way.
    manifest = (
        ROOT / "packages" / "pneuma-knowledge-eval" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert "pneuma-knowledge-core" in manifest


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




#: The one content-specific list this repository keeps in tracked code, and the exception
#: proves the rule stated in `_denylist_pattern` above: a denylist is normally private
#: because committing it publishes the very terms it guards. These terms are different —
#: they ALREADY leaked into this tree (real people's names, nicknames and one address from
#: a private corpus, carried in through task specs), and they have been replaced by
#: synthetic equivalents everywhere. Publishing them once more as a five-line regression set
#: costs nothing they have not already cost, and it is the only thing that stops the same
#: scrub from having to be done twice. The synthetic replacements, for anyone adding a
#: fixture: Hao WEN, Lan LIU, Tian QIAO, Yong BAI, Kun YAO / 姚昆 / kun.yao@example.com,
#: 阿宝, momo, 周总, 文哥, 白哥, Jie WANG, Fan WANG, and Acme for the company name.
#:
#: Matched case-sensitively and as plain substrings: every entry is a name as it was
#: actually written, and case-insensitive matching would fire on random base64 inside the
#: verbatim agent transcripts under `build-record/trace/`.
SCRUBBED_IDENTIFIERS = (
    "Huazheng",
    "Ling LV",
    "Tianqiao",
    "Yingbo",
    "KunLun",
    "Kunlun",
    "yaokunlun",
    "姚昆仑",
    "花花",
    "koko",
    "Koko",
    "KOKO",
    "陈总",
    "华哥",
    "江哥",
    "Jack WANG",
    "Evermind",
    "EverMind",
    "evermind",
    "Frank WANG",
    "Hua ZHANG",
    "Junjie WU",
    "Jiang WANG",
    "Yafeng DENG",
    "Cody SONG",
    "Frank WANG",
    "Tanka",
    "TANKA",
    "tanka",
)


def test_scrubbed_private_identifiers_never_come_back() -> None:
    """Always on — unlike the operator-local denylist above, this list ships with the repo.

    It is the "never again" set of a one-time scrub: these strings reached the tree through
    earlier task specs, were replaced with synthetic equivalents, and must not reappear when
    someone writes the next people/alias fixture from memory of the old one.
    """
    this_file = Path(__file__).resolve()
    violations: list[str] = []
    for path in _public_text_files():
        if path.resolve() == this_file:  # the list itself is not a violation of the list
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for term in SCRUBBED_IDENTIFIERS:
            index = text.find(term)
            if index >= 0:
                line = text.count("\n", 0, index) + 1
                violations.append(f"{path.relative_to(ROOT).as_posix()}:{line}: {term}")
    assert not violations, (
        "scrubbed private identifiers are back — replace them with the synthetic "
        "equivalents listed beside SCRUBBED_IDENTIFIERS:\n" + "\n".join(violations[:100])
    )
