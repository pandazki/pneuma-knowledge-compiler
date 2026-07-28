"""Ambient-environment isolation for the example scripts. Import this FIRST.

Same job as `packages/pneuma-knowledge-service/tests/conftest.py` does for the suite, for the same
reason — these scripts are the other class of consumer that talks to middleware on
localhost directly, they just don't run under pytest.

**The proxy trap.** httpx defaults to `trust_env=True`, and on macOS
`urllib.request.getproxies()` reads the SYSTEM proxy configuration. A machine running a
global proxy (Surge / Clash / et al) therefore tunnels even `127.0.0.1:17700` through it.
Worse, macOS keeps `localhost` and `127.0.0.0/8` in the proxy's `ExceptionsList`, but
`getproxies()` does not report exceptions and httpx honours only the `NO_PROXY` env var —
so the bypass the OS thinks is in effect is invisible to every client here.

The failure is silent and badly misdirected: qdrant-client surfaces it as a bare
`ResponseHandlingException` naming neither the proxy nor the port, so it reads as "Qdrant
is broken". `rag_e2e.py` is advertised in examples/README.md as the fastest keyless smoke
for a NEW developer — who, behind any global proxy, would hit that wall on step one.

`setdefault`, not assignment: anyone genuinely proxying localhost can still override it
from their own environment.

**The fake-IP escape hatch.** A local TUN proxy can also publish a synthetic
``198.18.0.0/15`` DNS answer while its route for one upstream is temporarily broken.
Example scripts may opt into a process-local OpenRouter address override with
``PNEUMA_KNOWLEDGE_OPENROUTER_RESOLVE_IP``. The URL hostname and TLS SNI stay
``openrouter.ai``; only ``socket.getaddrinfo`` for that one host is redirected. This is
deliberately opt-in and never edits system DNS or ``/etc/hosts``.
"""

import os
import socket

os.environ.setdefault("NO_PROXY", "localhost,127.0.0.1")
os.environ.setdefault("no_proxy", "localhost,127.0.0.1")

_openrouter_ip = os.getenv("PNEUMA_KNOWLEDGE_OPENROUTER_RESOLVE_IP", "").strip()
if _openrouter_ip:
    _system_getaddrinfo = socket.getaddrinfo

    def _example_getaddrinfo(host, port, *args, **kwargs):  # noqa: ANN001
        if host in {"openrouter.ai", b"openrouter.ai"}:
            host = _openrouter_ip
        return _system_getaddrinfo(host, port, *args, **kwargs)

    socket.getaddrinfo = _example_getaddrinfo
