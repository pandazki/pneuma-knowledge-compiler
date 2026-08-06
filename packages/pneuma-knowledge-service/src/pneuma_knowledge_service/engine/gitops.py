"""The engine directory's own git repository: one commit per apply.

The engine directory is versioned as its own repository, separate from the canonical
libraries (`adapters/git_canonical.py`) — different lifetime, different owner, different
contents. The identity is pinned in the repository's local config at init AND passed on
every commit, so an apply never depends on (or inherits) the machine's git config: a
deployment with no global `user.email` still commits, and a developer's own name never
lands in the engine's history.

Everything here is synchronous `git` in a subprocess. Callers that run inside the event
loop wrap the whole sequence in one `asyncio.to_thread` hop (see `apply.py`), because a
multi-command sequence must stay atomic inside one thread rather than interleave mid-commit.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .files import MAX_FILE_BYTES, EnginePathError, engine_path

_GIT_ID = ("-c", "user.email=engine@local", "-c", "user.name=pneuma-engine")

# A commit is named by its hex object id and nothing else. Git's revision grammar would also
# accept `HEAD~3`, `main@{yesterday}` and `--output=…`, and this value arrives in a URL: a
# read route must not be a place where a request composes a git expression. Abbreviations are
# allowed because a person reading the timeline copies a short prefix.
_SHA = re.compile(r"\A[0-9a-fA-F]{4,40}\Z")

# Record and field separators for the one-pass history read. \x00 cannot appear in a commit
# subject or a path, so parsing needs no quoting rules.
_REC = "\x00"
_SEP = "\x1f"
# The same two bytes as git's own format escapes: a literal NUL in an argv is rejected by
# the OS, so the separators are asked for, not passed in.
_REC_FMT = "%x00"
_SEP_FMT = "%x1f"


class EngineGitError(RuntimeError):
    """A git command inside the engine directory failed."""


class EngineUnknownCommit(LookupError):
    """The engine repository holds no commit by that name.

    Deliberately NOT an `EngineGitError`: git did not fail, the caller named a version this
    repository does not have (a sha from another clone, a truncated paste, a directory that is
    not a repository yet). That is a 404, not a 500.
    """


class EngineHeadMismatch(RuntimeError):
    """An apply named a HEAD the engine repository has moved on from.

    Deliberately NOT an `EngineGitError`: nothing failed. Somebody else's version landed
    between the read this apply was composed against and the write, and the console sends
    whole files — so proceeding would roll their edit back without a word.
    """

    def __init__(self, expected: str, current: str | None) -> None:
        super().__init__(
            f"the engine has moved on: this change was composed against {expected}, "
            f"but HEAD is now {current or '(no commit)'}. Reload the engine state and "
            "re-apply, so you are not silently reverting somebody else's version."
        )
        self.expected = expected
        self.current = current


@dataclass(frozen=True)
class Version:
    head: str | None
    dirty: bool


@dataclass(frozen=True)
class Commit:
    sha: str
    label: str
    at: str
    files: list[str]


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True
    )
    if check and result.returncode != 0:
        raise EngineGitError(
            f"git {' '.join(args)} failed in {repo}: {result.stderr.strip() or result.stdout.strip()}"
        )
    return result


def is_repo(repo: Path) -> bool:
    return (repo / ".git").exists()


def ensure_repo(repo: Path) -> None:
    """`git init` the engine directory if it is not a repository yet, with a pinned identity.

    Idempotent, and only ever called from a write path: a GET must not create a repository
    as a side effect of being read. The scaffold generator initializes it at generation, so
    this is the recovery path for a hand-assembled engine directory.
    """
    repo.mkdir(parents=True, exist_ok=True)
    if is_repo(repo):
        return
    _run(repo, "init", "-q")
    _run(repo, "config", "user.email", "engine@local")
    _run(repo, "config", "user.name", "pneuma-engine")


def version(repo: Path) -> Version:
    """The current HEAD sha and whether the working tree diverges from it.

    A directory that is not a repository (or has no commits) reports `head=None` and is
    dirty exactly when it holds anything at all — everything in it is uncommitted.
    """
    if not is_repo(repo):
        return Version(head=None, dirty=any(repo.rglob("*")) if repo.is_dir() else False)
    head = _run(repo, "rev-parse", "--verify", "-q", "HEAD", check=False)
    sha = head.stdout.strip() or None
    status = _run(repo, "status", "--porcelain")
    return Version(head=sha, dirty=bool(status.stdout.strip()))


def history(repo: Path, limit: int) -> list[Commit]:
    """The newest `limit` commits, each with the files it touched. Newest first."""
    if not is_repo(repo):
        return []
    result = _run(
        repo,
        "log",
        f"-n{max(1, limit)}",
        f"--pretty=format:{_REC_FMT}%H{_SEP_FMT}%s{_SEP_FMT}%aI",
        "--name-only",
        check=False,
    )
    if result.returncode != 0:
        return []  # no commits yet
    commits: list[Commit] = []
    for record in result.stdout.split(_REC):
        if not record.strip():
            continue
        header, _, tail = record.partition("\n")
        fields = header.split(_SEP)
        if len(fields) != 3:
            continue
        sha, label, at = fields
        files = [line.strip() for line in tail.splitlines() if line.strip()]
        commits.append(Commit(sha=sha, label=label, at=at, files=files))
    return commits


def commit_files(repo: Path, sha: str) -> tuple[str, dict[str, str]]:
    """(full sha, engine-relative path → content) as that version had it.

    The read half of "how do I undo this". The timeline could already say what changed; it
    could not say what the file used to hold, so undoing meant remembering the old value by
    hand. With the contents in reach, restoring a version is composing the ordinary apply from
    them — one review, one label, one new commit forward. No write primitive is added here, and
    nothing in the working tree is touched: `git show` reads the object database.

    Filtered by the same addressing rules a read of the directory applies, so a version's
    listing cannot contain something the console would refuse to write back: dotfiles and
    anything outside the directory are not engine files, and a blob that is oversized or not
    UTF-8 text is not editable here either.
    """
    if not _SHA.match(str(sha).strip()):
        raise EngineUnknownCommit(
            f"{sha!r} is not a commit id — a version is named by its hex sha, as the "
            "timeline reports it."
        )
    if not is_repo(repo):
        raise EngineUnknownCommit(
            f"the engine directory at {repo} is not a git repository yet, so it has no versions"
        )
    resolved = _run(repo, "rev-parse", "--verify", "-q", f"{sha}^{{commit}}", check=False)
    full = resolved.stdout.strip()
    if not full:
        raise EngineUnknownCommit(f"the engine repository has no commit {sha}")
    listing = _run(repo, "ls-tree", "-r", "-z", "--name-only", full)
    files: dict[str, str] = {}
    for rel in sorted(entry for entry in listing.stdout.split("\0") if entry):
        try:
            engine_path(repo, rel)
        except EnginePathError:
            continue  # not an engine file (a dotfile, say) — the same skip a read applies
        blob = subprocess.run(
            ["git", "-C", str(repo), "show", f"{full}:{rel}"],
            capture_output=True,
        )
        if blob.returncode != 0 or len(blob.stdout) > MAX_FILE_BYTES:
            continue
        try:
            files[rel] = blob.stdout.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return full, files


def commit_paths(repo: Path, label: str, paths: Sequence[str]) -> str:
    """Commit exactly `paths` (engine-relative) as one version; returns the HEAD sha.

    ONLY those paths. An apply validates the files it was handed, so those are the only files
    it may version: `git add -A` would sweep in whatever a developer left modified or
    untracked — a hand-broken contract, a stray `.env` — and hand it a label and a place in
    the history without any of it passing a single check. `git commit -- <paths>` is a partial
    commit: anything else in the working tree stays exactly as dirty as it was, and `version()`
    keeps reporting it.

    `add -f` because the write already happened and was already validated: a version that
    silently omitted one of its own files would misreport what it contains.

    An apply that changes nothing does not mint an empty commit — the current HEAD is
    returned instead, so "apply" is idempotent rather than a history-inflating no-op.
    """
    ensure_repo(repo)
    listed = list(paths)
    if listed:
        _run(repo, "add", "-f", "--", *listed)
        if _run(repo, "status", "--porcelain", "--", *listed).stdout.strip():
            _run(repo, *_GIT_ID, "commit", "-q", "-m", label, "--", *listed)
    head = _run(repo, "rev-parse", "--verify", "-q", "HEAD", check=False).stdout.strip()
    if not head:
        raise EngineGitError(f"the engine repository at {repo} has no commit after apply")
    return head
