"""Reading and addressing files inside the engine directory.

Two mechanisms live here, and both are write-time/read-time rejections rather than
conventions anybody has to remember:

* **addressing** — `engine_path` is the only way a caller turns a request-supplied string
  into a filesystem path. It refuses absolute paths, `..`, and every dotfile, then proves
  the resolved path is still inside the engine directory (which also defeats a symlink
  planted inside it). No traversal path exists because no other function opens files.
  `engine_relpath` is its companion: ONE canonical spelling per file, so the string a
  validation step looked at cannot be a different string from the one that gets written.
* **shape** — every stage file except a `document` knob's file is a FLAT YAML mapping of
  that stage's knob keys. One rule, no per-file special cases; `read_mapping` is the only
  parser, and malformed YAML raises rather than quietly resolving to defaults.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

# API-key-shaped content, refused on write. The first pattern is verbatim the one
# `scaffold/init.py` applies to answers files — the engine directory is a versioned,
# shareable unit for exactly the same reason an answers file is, so it inherits the same
# shape check. The second covers the `sk-…` family of provider keys more broadly.
KEY_SHAPES = (
    re.compile(r"sk-or-[A-Za-z0-9-]{8,}"),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
)

# A single engine file larger than this is not strategy. The cap keeps a stray blob (a
# dropped PDF, a checked-in dataset) out of every state response instead of turning one
# mistake into an unusable console.
MAX_FILE_BYTES = 512 * 1024


class EnginePathError(ValueError):
    """A change addressed something the engine directory will not accept."""


class EngineFileError(ValueError):
    """An engine file exists but does not say what its shape requires."""


def engine_root(engine_dir: str | Path) -> Path:
    return Path(engine_dir).expanduser().resolve()


def engine_path(engine_dir: str | Path, rel: str) -> Path:
    """An engine-relative path → an absolute path inside the engine directory.

    Raises `EnginePathError` for anything else. The checks are ordered cheapest-first, but
    the last one is the one that actually closes the door: after resolving symlinks the
    path must still be inside the engine root.
    """
    root = engine_root(engine_dir)
    candidate = str(rel).strip()
    if not candidate:
        raise EnginePathError("empty path")
    if "\x00" in candidate:
        raise EnginePathError("path contains a NUL byte")
    if candidate.startswith(("/", "\\")) or PurePosixPath(candidate).is_absolute():
        raise EnginePathError(f"path must be engine-relative, not absolute: {rel!r}")
    if "\\" in candidate:
        raise EnginePathError(f"use / as the path separator: {rel!r}")
    parts = PurePosixPath(candidate).parts
    for part in parts:
        if part in ("..", "."):
            raise EnginePathError(f"path may not traverse: {rel!r}")
        if part.startswith("."):
            # No dotfiles, ever: `.git` is the repository's own business, and every
            # secret-shaped file on a developer's machine (.env, .netrc, .ssh/…) is a
            # dotfile. Refusing the whole class is a mechanism; refusing a denylist of
            # names would be a game of catch-up.
            raise EnginePathError(f"engine files are never dotfiles: {rel!r}")
    resolved = (root / PurePosixPath(candidate)).resolve()
    if resolved != root and root not in resolved.parents:
        raise EnginePathError(f"path resolves outside the engine directory: {rel!r}")
    if resolved == root:
        raise EnginePathError("path is the engine directory itself")
    return resolved


def engine_relpath(engine_dir: str | Path, rel: str) -> str:
    """The one canonical engine-relative spelling of `rel`, derived from the resolved path.

    `engine_path` happily resolves `./recall/recall.yaml` and `recall//recall.yaml` to the
    real file, which is correct — and exactly why every later step (dedupe, stage lookup,
    shape validation, effect planning, the write, the commit) must work from THIS string
    rather than from whatever spelling the request used. Two spellings of one file are two
    chances for the checks and the write to disagree.
    """
    root = engine_root(engine_dir)
    return engine_path(root, rel).relative_to(root).as_posix()


def assert_canonical_path(engine_dir: str | Path, rel: str) -> str:
    """`engine_relpath`, and a refusal when the request did not use that spelling.

    Normalizing silently would be enough for correctness inside this process, but the console
    echoes the path it is about to write and the commit records it: an apply that reviewed
    `./recall/recall.yaml` and committed `recall/recall.yaml` would make the review a
    paraphrase of the write. One spelling, named in the error, keeps them the same string.
    """
    canonical = engine_relpath(engine_dir, rel)
    if canonical != rel:
        raise EnginePathError(
            f"{rel!r} is not how an engine file is addressed — write it as {canonical!r}. "
            "One spelling per file is what keeps the path that was validated and the path "
            "that gets written the same string."
        )
    return canonical


def assert_within_size(rel: str, content: str) -> None:
    """Refuse content the read side would have to skip on the way back out.

    The read side skips anything over `MAX_FILE_BYTES`. Without the same cap on the write side
    an apply could commit a file the console can never show again — and the editor, seeing no
    entry in `state.files`, would offer a blank and overwrite the real content with it. One
    cap, both directions.
    """
    size = len(content.encode("utf-8"))
    if size > MAX_FILE_BYTES:
        raise EnginePathError(
            f"{rel} is {size} bytes, past the {MAX_FILE_BYTES}-byte limit for an engine file. "
            "A file this size is not strategy, and one the console cannot read back is one it "
            "could silently overwrite."
        )


def assert_no_key_shape(rel: str, content: str) -> None:
    """Refuse API-key-shaped content before it can be committed."""
    for shape in KEY_SHAPES:
        if shape.search(content):
            raise EnginePathError(
                f"{rel} contains an API-key-shaped string. Secrets never enter the engine "
                "directory — it is versioned; keys live in the deployment's environment."
            )


@dataclass(frozen=True)
class EngineDirectory:
    """One read of the engine directory: what is editable, and what was left out and why.

    `skipped` exists because "absent from `files`" is not a fact anybody can act on. An
    oversized contract that simply did not come back looks exactly like an empty one to an
    editor, which is how a full document gets overwritten with a blank. A named reason turns
    that into something the console can show and a person can fix.
    """

    files: dict[str, str]
    skipped: dict[str, str]


def read_engine_directory(engine_dir: str | Path) -> EngineDirectory:
    """Every engine file, engine-relative path → text, sorted by path, plus the skips.

    Unreadable entries (binary, oversized, dotfiles, anything the addressing rules refuse) are
    reported rather than raising: the state endpoint's job is to show the console what it can
    edit, and one stray file must not make the whole engine unreadable.
    """
    root = engine_root(engine_dir)
    if not root.is_dir():
        return EngineDirectory(files={}, skipped={})
    out: dict[str, str] = {}
    skipped: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            engine_path(root, rel)
        except EnginePathError:
            # Dotfiles and anything else the addressing rules refuse are not engine files at
            # all, so they are not reported as skipped either — `.git` is not a gap.
            continue
        try:
            size = path.stat().st_size
            if size > MAX_FILE_BYTES:
                skipped[rel] = (
                    f"{size} bytes, past the {MAX_FILE_BYTES}-byte limit for an engine file — "
                    "not shown, and not editable here."
                )
                continue
            out[rel] = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            skipped[rel] = "not UTF-8 text — the console edits text files only."
        except OSError as exc:
            skipped[rel] = f"cannot be read: {exc.strerror or exc}"
    return EngineDirectory(files=out, skipped=skipped)


def read_engine_files(engine_dir: str | Path) -> dict[str, str]:
    """`read_engine_directory().files` — the readable files alone."""
    return read_engine_directory(engine_dir).files


def read_engine_file(engine_dir: str | Path, rel: str) -> tuple[str, str]:
    """(canonical path, text) for ONE engine file, addressed the same way an apply addresses it.

    The repair path: when a hand-broken file makes the whole state unresolvable, this still
    answers, so the console can fetch the file, fix it and apply — without the person having to
    already know its contents. Raises `EnginePathError` for a path the directory will not
    accept, `FileNotFoundError` when there is nothing there, and `EngineFileError` for a file
    that exists but cannot be handed back as text.
    """
    canonical = assert_canonical_path(engine_dir, rel)
    path = engine_path(engine_dir, canonical)
    if not path.is_file():
        raise FileNotFoundError(canonical)
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise EngineFileError(
            f"{canonical} is {size} bytes, past the {MAX_FILE_BYTES}-byte limit for an engine "
            "file — too large to hand back, and too large to edit here."
        )
    try:
        return canonical, path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise EngineFileError(f"{canonical} is not UTF-8 text: {exc}") from exc


def parse_mapping(rel: str, text: str) -> dict[str, Any]:
    """A stage file's text → its flat top-level mapping.

    Empty (or comment-only) is a legitimate "states nothing" and yields `{}`. Anything that
    parses to a non-mapping, or does not parse at all, raises: an engine file that cannot be
    read is not allowed to silently mean "use the framework defaults".

    The parse failure leads with one actionable line in both languages and keeps the parser's
    own text after it. `yaml` reports "expected ',' or ']', but got …, line 2, column 13" —
    precise, and unusable by somebody meeting YAML for the first time, who then sees a raw
    backend exception where the console's other refusals explain themselves.
    """
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise EngineFileError(
            f"{rel} is not valid YAML — use the line and column below to find the spot and fix "
            "it (usually an unclosed bracket or quote, a stray colon, or indentation that does "
            "not line up).\n"
            f"{rel} 不是合法的 YAML——按下方的 行 / 列 提示定位并修复"
            "（常见原因：括号或引号没闭合、多了一个冒号、缩进没对齐）。\n"
            f"{exc}"
        ) from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise EngineFileError(f"{rel} must be a YAML mapping, got {type(loaded).__name__}")
    return {str(key): value for key, value in loaded.items()}


def read_mapping(engine_dir: str | Path, rel: str) -> dict[str, Any]:
    """`parse_mapping` over a stage file on disk; a missing file states nothing."""
    path = engine_path(engine_dir, rel)
    if not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EngineFileError(f"{rel} cannot be read as UTF-8 text: {exc}") from exc
    return parse_mapping(rel, text)


def overlay_catalog_keys() -> tuple[str, ...]:
    """Every prompt-catalog key an overlay may replace, sorted.

    Read from the core catalog rather than listed here: the catalog IS the auditable
    inventory of model-visible prose, and a second hand-kept list of its keys would rot the
    first time a surface is added. Both the schema's picker data and the apply-time
    rejection of an unknown key come from this one call.
    """
    from pneuma_knowledge_core.prompts import default_catalog

    return tuple(sorted(default_catalog()))


def parse_overlays(rel: str, mapping: dict[str, Any]) -> dict[str, str]:
    """The prompt overlay map: catalog key → replacement clause, both strings.

    The overlay file's flat mapping holds a single `overlays` key whose value is the map, so
    the "one stage file is one flat mapping" rule holds here too.
    """
    raw = mapping.get("overlays")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise EngineFileError(f"{rel}: `overlays` must be a mapping of catalog key → clause")
    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(value, str):
            raise EngineFileError(
                f"{rel}: overlay {key!r} must be a string clause (whole-clause replacement "
                "is the only supported form)"
            )
        out[str(key)] = value
    return out
