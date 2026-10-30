"""Read immutable Git objects. Never open or mutate a canonical working tree file."""

from __future__ import annotations
import subprocess
from pathlib import Path


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(
        ["git", "--no-optional-locks", "-C", str(repo), *args],
        text=True,
        stderr=subprocess.PIPE,
        timeout=30,
    )


def observe(repo: Path, previous: str | None) -> tuple[str, list[str], int]:
    head = git(repo, "rev-parse", "--verify", "HEAD").strip()
    if head == previous:
        return head, [], 0
    if previous:
        try:
            git(repo, "merge-base", "--is-ancestor", previous, head)
            paths = git(repo, "diff", "--name-only", "-z", previous, head).split("\0")
            count = int(git(repo, "rev-list", "--count", f"{previous}..{head}"))
        except subprocess.CalledProcessError:
            paths = git(repo, "ls-tree", "-r", "--name-only", "-z", head).split("\0")
            count = 1
    else:
        paths = git(repo, "ls-tree", "-r", "--name-only", "-z", head).split("\0")
        count = 1
    allowed = {
        p
        for p in paths
        if p.endswith(".md") and not p.startswith(("archive/", "skill/", "."))
    }
    # On bootstrap, recent knowledge reaches the first board before the older backlog.
    recent = git(repo, "log", "-100", "--format=", "--name-only", "-z", head).split(
        "\0"
    )
    ordered = list(
        dict.fromkeys(p.strip("\n") for p in recent if p.strip("\n") in allowed)
    )
    return head, ordered + sorted(allowed - set(ordered)), count


def collect(repo: Path, pending: dict[str, str], *, limit: int = 16) -> list[dict]:
    documents = []
    for path, head in list(pending.items())[:limit]:
        try:
            content = git(repo, "show", f"{head}:{path}")
            deleted = False
        except subprocess.CalledProcessError:
            content, deleted = "", True
        # Keep the full evidence in the record; the prompt explicitly marks its bounded excerpt.
        documents.append(
            {
                "path": path,
                "head": head,
                "ref": f"canonical:{head}:{path}",
                "text": content,
                "deleted": deleted,
                "committed_at": git(
                    repo, "log", "-1", "--format=%cI", head, "--", path
                ).strip(),
            }
        )
    return documents


def prompt_documents(documents: list[dict]) -> list[dict]:
    return [
        dict(
            d,
            text=d["text"][:16000],
            truncated=d.get("truncated", False) or len(d["text"]) > 16000,
        )
        for d in documents
    ]


def validate_sources(snapshot: dict, before: dict, documents: list[dict]):
    """New references must resolve to supplied evidence. This is not an entailment check."""
    known = {d["ref"] for d in documents}
    for item in before["items"].values():
        known.update(s["ref"] for s in item.get("sources", []) if s.get("ref"))
    for item in snapshot["items"].values():
        for source in item.get("sources", []):
            if source.get("ref") not in known:
                raise ValueError("unknown attention source reference")
        if (
            item["status"] == "active"
            and item["id"] not in before["items"]
            and not item.get("sources")
        ):
            raise ValueError("new attention items require a supplied canonical source")
