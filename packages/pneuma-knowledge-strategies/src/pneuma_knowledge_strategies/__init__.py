"""Shipped starting-point strategies: domain contracts as data, plus a loader.

WHAT THIS IS. A strategy is one domain's compile contract — the prose that tells the
compile agent what is worth recording and where it goes — together with the structural
facts that identify it (`skill_id`, `version`, `path_templates`, `contract_rules`). This
package ships a few such contracts so an application does not have to start from a blank
file, and offers exactly two operations over them: list what is available, and read one.

WHAT THIS IS NOT. It is not part of the framework. It does not import
`pneuma_knowledge_core`, it never will, and nothing in core or the service imports it — a
framework that shipped a domain contract would be handing every user an opinion about
their own domain. The conversion from a strategy record into a runnable `SkillVersion`
therefore happens in the APPLICATION, in three lines, and the application is where the
choice of contract is made. See `docs/guides/compile-contract.md`.

LAYOUT. One directory per domain under `strategies/`, each holding a `strategy.json`
manifest and one markdown body per contract. Serving a different kind of user means
adding a strategy (a new directory), not stacking versions of an existing one. Adding a
domain is adding a directory; no code here changes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = [
    "Strategy",
    "get_strategy",
    "list_strategies",
    "load_strategy_text",
    "strategies_root",
]

_ROOT = Path(__file__).resolve().parent / "strategies"


@dataclass(frozen=True)
class Strategy:
    """One generation of one domain's contract — metadata plus a pointer to the body.

    The four structural fields (`skill_id`, `version`, `path_templates`,
    `contract_rules`) are carried here, not left to the caller to retype, because they are
    part of the contract's identity: a consumer hashes them together with the body to get
    the `Skill-Content-Hash` that ends up in canonical commit trailers. Retyping them is
    how a provenance hash silently stops matching.
    """

    skill_id: str
    version: str
    domain: str
    summary: str
    path_templates: tuple[str, ...]
    contract_rules: tuple[str, ...]
    path: Path

    def read_text(self) -> str:
        """The contract body, verbatim."""
        return self.path.read_text(encoding="utf-8")


def strategies_root() -> Path:
    """The directory holding one subdirectory per domain."""
    return _ROOT


@lru_cache(maxsize=1)
def _catalog() -> tuple[Strategy, ...]:
    found: list[Strategy] = []
    for manifest_path in sorted(_ROOT.glob("*/strategy.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        directory = manifest_path.parent
        skill_id = str(manifest["skill_id"])
        domain = str(manifest["domain"])
        templates = tuple(str(t) for t in manifest["path_templates"])
        for generation in manifest["generations"]:
            found.append(
                Strategy(
                    skill_id=skill_id,
                    version=str(generation["version"]),
                    domain=domain,
                    summary=str(generation.get("summary") or manifest.get("summary") or ""),
                    path_templates=templates,
                    contract_rules=tuple(str(r) for r in generation.get("contract_rules", ())),
                    path=directory / str(generation["file"]),
                )
            )
    return tuple(found)


def list_strategies(skill_id: str | None = None) -> tuple[Strategy, ...]:
    """Every shipped strategy, optionally narrowed to one domain, in catalog order."""
    catalog = _catalog()
    if skill_id is None:
        return catalog
    return tuple(s for s in catalog if s.skill_id == skill_id)


def get_strategy(skill_id: str, version: str) -> Strategy:
    """One strategy by domain id and generation. Unknown ids fail loud and list what exists."""
    for strategy in _catalog():
        if strategy.skill_id == skill_id and strategy.version == version:
            return strategy
    available = ", ".join(f"{s.skill_id}@{s.version}" for s in _catalog()) or "(none)"
    raise LookupError(
        f"no shipped strategy {skill_id!r}@{version!r}; available: {available}"
    )


def load_strategy_text(skill_id: str, version: str) -> str:
    """The raw contract body for one strategy."""
    return get_strategy(skill_id, version).read_text()
