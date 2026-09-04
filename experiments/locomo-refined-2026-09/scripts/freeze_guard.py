#!/usr/bin/env python3
"""Write and verify SHA-256 freeze blocks embedded in FROZEN.md."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FROZEN = ROOT / "FROZEN.md"


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def phase_markers(phase: int) -> tuple[str, str]:
    if phase not in (1, 2):
        raise ValueError("phase must be 1 or 2")
    return f"<!-- FREEZE{phase}:START -->", f"<!-- FREEZE{phase}:END -->"


def render_block(root: Path, phase: int, files: list[Path]) -> str:
    start, end = phase_markers(phase)
    entries: list[tuple[str, Path]] = []
    for candidate in files:
        path = candidate.resolve()
        try:
            relative = path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"freeze target is outside experiment root: {path}") from exc
        if not path.is_file():
            raise ValueError(f"freeze target is not a file: {relative}")
        entries.append((relative.as_posix(), path))
    names = [name for name, _path in entries]
    if len(names) != len(set(names)):
        raise ValueError("duplicate freeze target")
    lines = [start, "```text"]
    lines.extend(f"{digest(path)}  {name}" for name, path in sorted(entries))
    lines.extend(["```", end])
    return "\n".join(lines)


def block_pattern(phase: int) -> re.Pattern[str]:
    start, end = phase_markers(phase)
    return re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)


def write_phase(
    frozen_path: Path,
    root: Path,
    phase: int,
    files: list[Path],
    *,
    reason: str = "",
) -> None:
    new_block = render_block(root, phase, files)
    if frozen_path.exists():
        document = frozen_path.read_text(encoding="utf-8")
    else:
        document = "# FROZEN\n\n## FREEZE#1\n\n## FREEZE#2\n\n## Burned questions\n\nNone recorded yet.\n"
    pattern = block_pattern(phase)
    old = pattern.search(document)
    if old:
        if old.group(0) == new_block:
            return
        if not reason.strip():
            raise ValueError("re-freeze requires a non-empty reason")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        history = (
            f"\n\n### FREEZE#{phase} superseded at {stamp}\n\n"
            f"Reason: {reason.strip()}\n\n{old.group(0)}\n"
        )
        document = document[: old.start()] + new_block + document[old.end() :] + history
    else:
        heading = f"## FREEZE#{phase}"
        position = document.find(heading)
        if position < 0:
            document = document.rstrip() + f"\n\n{heading}\n\n{new_block}\n"
        else:
            insertion = document.find("\n", position) + 1
            document = document[:insertion] + "\n" + new_block + document[insertion:]
    frozen_path.write_text(document.rstrip() + "\n", encoding="utf-8")


def parse_phase(frozen_path: Path, phase: int) -> list[tuple[str, str]]:
    if not frozen_path.is_file():
        raise ValueError(f"freeze document not found: {frozen_path}")
    match = block_pattern(phase).search(frozen_path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"FREEZE#{phase} block not found")
    entries = re.findall(r"^([0-9a-f]{64})  ([^\n]+)$", match.group(0), re.MULTILINE)
    if not entries:
        raise ValueError(f"FREEZE#{phase} contains no hashes")
    paths = [path for _sha, path in entries]
    if len(paths) != len(set(paths)):
        raise ValueError(f"FREEZE#{phase} contains duplicate paths")
    return entries


def verify_phase(frozen_path: Path, root: Path, phase: int) -> int:
    entries = parse_phase(frozen_path, phase)
    for expected, relative in entries:
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError(f"frozen path escapes experiment root: {relative}") from exc
        if not path.is_file():
            raise ValueError(f"frozen file is missing: {relative}")
        actual = digest(path)
        if actual != expected:
            raise ValueError(f"frozen hash mismatch: {relative}")
    return len(entries)


def cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("write", "verify"):
        command = sub.add_parser(name)
        command.add_argument("--phase", type=int, choices=(1, 2), required=True)
        command.add_argument("--frozen", type=Path, default=DEFAULT_FROZEN)
    write = sub.choices["write"]
    write.add_argument("--reason", default="")
    write.add_argument("files", nargs="+", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = cli_parser().parse_args(argv)
    try:
        if args.command == "write":
            write_phase(args.frozen, ROOT, args.phase, args.files, reason=args.reason)
            count = verify_phase(args.frozen, ROOT, args.phase)
            print(f"FREEZE#{args.phase} WRITTEN: {count} files")
        else:
            count = verify_phase(args.frozen, ROOT, args.phase)
            print(f"FREEZE#{args.phase} VERIFIED: {count} files")
        return 0
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

