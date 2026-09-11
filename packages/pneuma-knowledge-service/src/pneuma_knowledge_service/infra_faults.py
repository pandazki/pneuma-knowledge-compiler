"""Which failures are infrastructure going away for a moment, and which are not.

A Postgres restart, a Qdrant or Meilisearch container being recreated, RustFS dropping a
connection: none of these says anything about the job that happened to be running, or about
the request that happened to arrive. They say "the stack is not there right now", and the
answer to that is to wait and try again — not to fail the job, not to take the engine down.

This module is the one place that tells the two apart, so the worker's drain loop, the
engine's task supervision and the API's 503 handler all mean the same thing by "transient".
It is deliberately narrow: the client exceptions each adapter raises when its peer is
unreachable or dropped the connection, plus — checked last, when none of them claimed it —
a bare httpx transport error, which is the same fact with no client's name attached.
Anything else — a constraint violation, a statement timeout, a malformed request, an API
error the server answered with — is not classified, so it keeps whatever behaviour it had
before this module existed.

The client libraries are looked up in `sys.modules` rather than imported: an exception can
only be an instance of a class whose module is loaded, so a process that never imported
botocore (every `pkc` command that touches no media) pays nothing to ask.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

#: SQLSTATEs psycopg raises as `OperationalError` that mean the server went away or is
#: coming back — connection exceptions (class 08), an administrator or crash shutdown, a
#: server still starting up, and a server out of connection slots. Every other
#: `OperationalError` with a SQLSTATE (a statement timeout, a lock timeout, a deadlock) is an
#: answer about the work and is left alone.
_PG_TRANSIENT_SQLSTATES = frozenset({"57P01", "57P02", "57P03", "53300"})

#: How much of a client's message a log line or a 503 body carries.
_REASON_CHARS = 160


@dataclass(frozen=True)
class InfraFault:
    """One transient infrastructure failure: which service, and what its client said."""

    #: postgres | qdrant | meilisearch | s3 | http — the last being a transport error that
    #: reached us without its client's wrapper, so which peer went away is not known and
    #: every one this body holds is asked (`compile_worker._probe`).
    kind: str
    reason: str

    def describe(self) -> str:
        return f"{self.kind}: {self.reason}"


class InfrastructureInterrupted(Exception):
    """A claimed job's body met a transient infrastructure failure.

    Raised by the drain in place of failing the job, and carrying which job it was: the
    drain loop that catches it is the only body that knows the job is its own, and it needs
    the id to put that job back once the stack answers again.
    """

    def __init__(self, fault: InfraFault, *, user_id: str, job_id: str) -> None:
        super().__init__(f"job {job_id} interrupted: infrastructure unavailable ({fault.describe()})")
        self.fault = fault
        self.user_id = str(user_id)
        self.job_id = job_id


def _short(exc: BaseException) -> str:
    text = str(exc).strip()
    line = next((part.strip() for part in text.splitlines() if part.strip()), "")
    line = line or type(exc).__name__
    return line if len(line) <= _REASON_CHARS else line[: _REASON_CHARS - 1] + "…"


def _is_instance(exc: BaseException, module: str, *names: str) -> bool:
    loaded = sys.modules.get(module)
    if loaded is None:
        return False
    classes = tuple(c for c in (getattr(loaded, n, None) for n in names) if isinstance(c, type))
    return bool(classes) and isinstance(exc, classes)


def _httpx_transport(exc: BaseException | None) -> bool:
    return exc is not None and _is_instance(exc, "httpx", "TransportError")


def _classify_one(exc: BaseException) -> InfraFault | None:
    if isinstance(exc, InfrastructureInterrupted):
        return exc.fault
    # psycopg_pool's own errors are OperationalError subclasses. A CLOSED pool is this
    # process shutting down, not the database going away, and retrying against it would
    # never end.
    if _is_instance(exc, "psycopg_pool", "PoolClosed"):
        return None
    if _is_instance(exc, "psycopg", "OperationalError"):
        sqlstate = getattr(exc, "sqlstate", None)
        if sqlstate is None or sqlstate.startswith("08") or sqlstate in _PG_TRANSIENT_SQLSTATES:
            return InfraFault("postgres", _short(exc))
        return None
    if _is_instance(exc, "psycopg", "InterfaceError"):
        return InfraFault("postgres", _short(exc))
    # qdrant-client wraps every exception its transport raised in one class, a validation
    # error included; only a transport failure underneath it is the server being away.
    if _is_instance(exc, "qdrant_client.http.exceptions", "ResponseHandlingException"):
        source = getattr(exc, "source", None)
        return InfraFault("qdrant", _short(source)) if _httpx_transport(source) else None
    if _is_instance(exc, "meilisearch_python_sdk.errors", "MeilisearchCommunicationError"):
        return InfraFault("meilisearch", _short(exc))
    # A read error or read timeout reaches the SDK's generic branch, which re-raises it as a
    # plain MeilisearchError chained from the httpx transport error.
    if _is_instance(exc, "meilisearch_python_sdk.errors", "MeilisearchError") and _httpx_transport(
        exc.__cause__
    ):
        return InfraFault("meilisearch", _short(exc))
    # botocore: `ConnectionError` covers refused/unreachable endpoints and connect timeouts,
    # `HTTPClientError` a connection closed or a read that timed out mid-response. An SSL
    # error is a configuration problem and is left alone.
    if _is_instance(exc, "botocore.exceptions", "SSLError"):
        return None
    if _is_instance(exc, "botocore.exceptions", "ConnectionError", "HTTPClientError"):
        return InfraFault("s3", _short(exc))
    # Last: a transport error with nobody's name on it. Every http client in this stack
    # speaks through httpx, and "the peer did not answer" is the same fact whether the client
    # wrapped it or let it through bare. It is checked after every client-specific rule
    # above, so a fault that CAN name its service still does.
    #
    # What made it necessary: a Qdrant blip raised `httpx.ReadError()` directly, outside the
    # `ResponseHandlingException` this module knew to look inside. Unclassified, it was not
    # an outage to wait out but an error about the work — and since `ReadError` carries an
    # empty message, the job was completed `worker error: ` with no reason on it at all.
    if _httpx_transport(exc):
        return InfraFault("http", _short(exc))
    return None


def infrastructure_fault(exc: BaseException) -> InfraFault | None:
    """The transient infrastructure failure `exc` is, or None when it is anything else.

    Follows the explicit `raise … from` chain, because an adapter that re-raises a client
    error as its own exception still failed for the client's reason. The implicit context
    (an exception raised while handling another) is not followed: that is a second failure,
    and it is the one that decides.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        fault = _classify_one(current)
        if fault is not None:
            return fault
        current = current.__cause__
    return None


def infrastructure_exception_types() -> tuple[type[BaseException], ...]:
    """The exception classes that CAN be transient, for a framework that dispatches handlers
    by class (FastAPI). Each handler still asks `infrastructure_fault`, because the same class
    also carries failures that are not transient (a statement timeout is an OperationalError).
    Imports here are real: a process that registers handlers is one that serves requests."""
    import botocore.exceptions as boto
    import httpx
    import psycopg
    from meilisearch_python_sdk.errors import MeilisearchError
    from qdrant_client.http.exceptions import ResponseHandlingException

    return (
        InfrastructureInterrupted,
        psycopg.OperationalError,
        psycopg.InterfaceError,
        ResponseHandlingException,
        MeilisearchError,
        boto.ConnectionError,
        boto.HTTPClientError,
        httpx.TransportError,
    )


__all__ = [
    "InfraFault",
    "InfrastructureInterrupted",
    "infrastructure_exception_types",
    "infrastructure_fault",
]
