"""Index components — the extension seam for business-specific structure over canonical.

WHAT A COMPONENT IS
-------------------
The framework holds no opinion about people, projects, places or any other kind of subject:
canonical is text documents with frontmatter and anchored, cited claims, and that is all core
knows. A component is the thing that DOES know a kind of subject. It binds to a contract
family (a path template such as `memory/people/{slug}.md`) and contributes, through this
protocol, the mechanical faces the framework calls at its own seams:

- `gate_checks` — write-time rejections over that family's documents (a frontmatter field
  that must be unique across the repository, a value that may only grow, a required shape);
- `outline_tail` — one extra line under a document in the compile outline, so the model
  deciding WHERE TO WRITE sees what the component indexes (an identity, an alias);
- `validate_fields` — the component's say over frontmatter a write face is about to set
  (`set_fields`, and the structured half of `rewrite_overview`), returned as refusal lines.
  Structured fields are written WHOLE, like the prose beside them; what a component may
  still refuse is a FACT it can check — an identity another page already binds, a name that
  is demonstrably somebody else's. The gate re-runs the same judgement as the final arbiter;
  this face is only the same rule said before the round is spent;
- `compile_tools` — read tools the compile model may call while drafting, given the draft and
  the sources of THIS compile (a tool whose answer depends on the material — "which identity
  do this job's turns address by that name" — cannot get it from the draft);
- `recall_tools` — tools the answering lanes (deep) may call, scoped to one user (I1);
- `fast_paths` — routed retrieval paths for the fast lane (recall/paths.py): chosen by one
  tool call, run concurrently with the built-in retrieval, merged as their own face;
- `source_preamble` — one mechanical line under a source in the compile task (what the
  source boundary knows that the transcript cannot show: the identities present in it);
- `prepare` — the ASYNC FACE of the sync seams: the framework tells a component, once per
  job and before any of the sync faces above are rendered, which user this job is for. A
  component whose sync seams read a per-process mirror of its own persisted projection fills
  that mirror here. This is a mechanism, not an optimisation: index and compile are separate
  jobs in separate processes, so a compile process's mirror is ALWAYS cold, and without this
  hook a seam that reads it would silently render the empty library forever;
- `on_source_indexed` / `rebuild` — the PROJECTION CHANNEL: the framework tells a component
  that one source finished indexing, and (on an explicit `rebuild_derived`) that its whole
  projection should be re-derived from L0 + canonical. A component that keeps a persisted
  index of its own owns exactly one write path and one rebuild path, and both are derived
  (I2) — nothing a component stores is ever an authority. The index job is fail-soft over
  these: a component that raises is logged and skipped, never a failed index job.

Canonical reaches a component's recall faces as the already-pinned `documents` the lane
loaded (a snapshot-pinned query stays pinned inside a component — the component never
resolves storage itself).

The framework never imports a component. Like a compile contract (`register_skill_base`),
the APPLICATION registers the components it enables at startup; a component that is not
registered contributes nothing, and every seam renders byte-for-byte as it did before the
concept existed (the compile SystemMessage stays stable per enabled set — invariant I5).

A component may hold structure — identities, edges, counts, spans — never prose knowledge.
Whatever it derives points back to a `source_id + block span` or a claim anchor (I4) and is
rebuildable from L0 and canonical (I2). It indexes; it does not know.

Everything here is a declaration — no I/O and no model calls of its own; the two
projection-channel fan-outs at the bottom only forward a call the framework already makes.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover — typing only, keeps this module import-free
    from langchain_core.tools import StructuredTool

    from ..compile.gate import Violation
    from ..compile.patch import DraftDoc, PatchDraft
    from ..domain.canonical import CanonicalDocument
    from ..domain.source import NormalizedSource
    from ..recall.paths import FastPath


@runtime_checkable
class IndexComponent(Protocol):
    """The faces a component may contribute. Every method has a no-op default meaning
    ("nothing to add") so a component implements only the faces it needs."""

    name: str

    # `gate_checks` is judged over the documents the round TOUCHED, and "touched" has one
    # definition: `compile/patch.py:touched_this_round` — body OR frontmatter differs from
    # base, or the page is new — the same predicate the file table itself is built from. A
    # component that re-derives that answer from one half of the document (the frontmatter
    # alone, say) applies its rule to half the writes it was written for.
    def gate_checks(
        self, docs: Mapping[str, "DraftDoc"], base_docs: Mapping[str, "DraftDoc"]
    ) -> list["Violation"]: ...

    def outline_tail(self, doc: "CanonicalDocument") -> str | None: ...

    def validate_fields(
        self, path: str, fields: Mapping[str, object], docs: Mapping[str, "DraftDoc"]
    ) -> list[str]: ...

    def compile_tools(
        self,
        draft: "PatchDraft",
        *,
        sources: Sequence["NormalizedSource"] = (),
    ) -> list["StructuredTool"]: ...

    def recall_tools(
        self, user_id: str, *, documents: Sequence["CanonicalDocument"] | None = None
    ) -> list["StructuredTool"]: ...

    def fast_paths(self, user_id: str) -> list["FastPath"]: ...

    def source_preamble(self, source: "NormalizedSource") -> str | None: ...

    async def prepare(self, user_id: str) -> None: ...

    async def on_source_indexed(
        self, user_id: str, source: "NormalizedSource"
    ) -> None: ...

    async def rebuild(self, user_id: str) -> None: ...


class BaseComponent:
    """Optional base with the no-op defaults spelled out once."""

    name: str = "component"

    def gate_checks(
        self, docs: Mapping[str, "DraftDoc"], base_docs: Mapping[str, "DraftDoc"]
    ) -> list["Violation"]:
        return []

    def outline_tail(self, doc: "CanonicalDocument") -> str | None:
        return None

    def validate_fields(
        self, path: str, fields: Mapping[str, object], docs: Mapping[str, "DraftDoc"]
    ) -> list[str]:
        return []

    def compile_tools(
        self,
        draft: "PatchDraft",
        *,
        sources: Sequence["NormalizedSource"] = (),
    ) -> list["StructuredTool"]:
        return []

    def recall_tools(
        self, user_id: str, *, documents: Sequence["CanonicalDocument"] | None = None
    ) -> list["StructuredTool"]:
        return []

    def fast_paths(self, user_id: str) -> list["FastPath"]:
        return []

    def source_preamble(self, source: "NormalizedSource") -> str | None:
        return None

    async def prepare(self, user_id: str) -> None:
        return None

    async def on_source_indexed(self, user_id: str, source: "NormalizedSource") -> None:
        return None

    async def rebuild(self, user_id: str) -> None:
        return None


class CanonicalReadOnly:
    """The canonical face a component is given: the reads it needs, and no way to write.

    This is invariant I7's mechanism. A component indexes canonical; it never authors it,
    and whatever it derives reaches the library only by riding an ordinary compile — the
    contract rules on what the component put in front of it, and the same gate judges the
    result. Handing a component the whole `CanonicalStore` would leave `commit_patch` one
    attribute away and reduce that guarantee to "the shipped components happen not to call
    it", which is the shape of promise this project does not accept.

    Deliberately narrow. A component that needs another read adds the method here, and the
    diff says so out loud — widening the face is a decision, never a side effect.
    """

    __slots__ = ("_store",)

    def __init__(self, store: object) -> None:
        self._store = store

    async def list(self, user_id, *, at=None):
        """Every canonical document of one user (I1), optionally at a pinned snapshot."""
        return await self._store.list(user_id, at=at)

    async def written_on(self, user_id, *, prefix: str = ""):
        """path → the day (`YYYY-MM-DD`) that path was last WRITTEN by a committed patch.

        The library's own answer to "has this page been touched since?" — a question a
        component asks when what it derives becomes stale relative to a page rather than
        relative to a source. It reads the commit history, so it states what was actually
        committed: a round that failed the gate wrote nothing and appears nowhere here.

        Read-only like everything on this face, and bounded by `prefix` (a path prefix, the
        component's own family) so a component walks its own corner of the history and not
        the whole library's.
        """
        return await self._store.written_on(user_id, prefix=prefix)


# The application seam. Registration order is the order every seam consults components in,
# so two components' outline tails always render in one deterministic order.
_REGISTERED: dict[str, IndexComponent] = {}

#: The registry-scoped job guard — see `component_job` below.
_JOB_LOCK = asyncio.Lock()


def register_component(component: IndexComponent) -> None:
    """Register (or replace by name) one enabled component. Call at wiring time."""
    _REGISTERED[component.name] = component


def registered_components() -> Sequence[IndexComponent]:
    """The enabled components, in registration order (a copy)."""
    return tuple(_REGISTERED.values())


def reset_components() -> None:
    """Drop every registered component. Tests only."""
    global _JOB_LOCK
    _REGISTERED.clear()
    _JOB_LOCK = asyncio.Lock()


# ------------------------------------------------------------------ projection channel
# The three fan-outs below are the only orchestration in this module, and they exist so the
# fail-soft rule is written ONCE: a component's projection is derived, so a component that
# raises may cost a stale index — never a failed job or a failed rebuild. The caller (the
# compile runner, the index worker, the rebuild script) stays a single line.

_log = logging.getLogger(__name__)


async def prepare_components(user_id: str) -> None:
    """Tell every registered component which user the job about to run is for.

    Called once at the head of a COMPILE job — the one job that renders the sync faces
    (`source_preamble`, `outline_tail`, `compile_tools`). The index job needs nothing: its
    own channel call is async and a component warms itself there. The recall lanes need
    nothing either: their faces are async and read the store directly.

    It runs before any of those faces is rendered, so a component whose sync seams read a
    mirror of its own persisted projection can fill it. Nothing here is a cache warm-up for
    speed: the deployment shape puts index and compile in different processes, so the
    compile process's mirror is cold by construction and this call is the only thing that
    makes a library-wide seam say anything at all.
    """
    for component in registered_components():
        hook = getattr(component, "prepare", None)
        if hook is None:
            continue
        try:
            await hook(user_id)
        except Exception:  # noqa: BLE001 — a component never fails the job it prepares for
            _log.warning(
                "component %r prepare failed for user %s; continuing",
                getattr(component, "name", component),
                user_id,
                exc_info=True,
            )


@asynccontextmanager
async def component_job(user_id: str) -> AsyncIterator[None]:
    """One compile job's component window: `prepare` at the top, the whole job inside it,
    and — while any component is registered — ONE such window open per process at a time.

    `prepare(user_id)` is a per-process announcement, so a component whose sync seams read a
    mirror keyed on "the user this job is for" holds exactly one such answer. Two compiles
    interleaving in one process would therefore make the second one's `prepare` redefine the
    first one's word for `self`, and the first one's gate would judge a page against another
    user's library — invariant I1 says there is no cross-user read path, not that the shipped
    scheduler happens not to take one.

    So the protocol constraint is stated, and made mechanical here: **one compile per process
    at a time when components are enabled.** The shipped worker already drains a user's jobs
    serially; this guard is what makes any other caller of `run_compile` — a script, a test,
    a future parallel worker — wait rather than corrupt. The second guarantee is the
    components' own: a face handed a user of its own (`compile_tools`, `source_preamble`)
    asserts it is the user `prepare` announced, so a caller who ignores this window is
    refused rather than answered from the wrong mirror.

    With NO component registered nothing is serialized: the lock is not taken at all, and a
    framework with no components behaves byte-for-byte as it did before the concept existed.
    """
    if not _REGISTERED:
        await prepare_components(user_id)
        yield
        return
    async with _JOB_LOCK:
        await prepare_components(user_id)
        yield


async def notify_source_indexed(user_id: str, source: "NormalizedSource") -> None:
    """Tell every registered component that one source finished L1/L2 indexing."""
    for component in registered_components():
        hook = getattr(component, "on_source_indexed", None)
        if hook is None:
            continue
        try:
            await hook(user_id, source)
        except Exception:  # noqa: BLE001 — a component never fails the index job
            _log.warning(
                "component %r on_source_indexed failed for source %s; continuing",
                getattr(component, "name", component),
                getattr(getattr(source, "raw", None), "source_id", "?"),
                exc_info=True,
            )


async def rebuild_components(user_id: str) -> list[str]:
    """Re-derive every registered component's projection. Returns the names that ran."""
    done: list[str] = []
    for component in registered_components():
        hook = getattr(component, "rebuild", None)
        if hook is None:
            continue
        name = str(getattr(component, "name", component))
        try:
            await hook(user_id)
            done.append(name)
        except Exception:  # noqa: BLE001 — one component never fails the whole rebuild
            _log.warning("component %r rebuild failed; continuing", name, exc_info=True)
    return done


__all__ = [
    "BaseComponent",
    "CanonicalReadOnly",
    "IndexComponent",
    "component_job",
    "notify_source_indexed",
    "prepare_components",
    "rebuild_components",
    "register_component",
    "registered_components",
    "reset_components",
]
