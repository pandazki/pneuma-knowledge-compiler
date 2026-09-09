"""Free localhost ports and a free private subnet, probed rather than assumed.

Users are never asked about ports, and no application here owns a fixed block: two stacks
generated on the same machine must not collide with each other, or with whatever else is
already listening. Both probes are therefore random draws checked against the machine.

Standard library only — the scaffold's generator loads this module before any environment
exists, and the personal edition calls it as an ordinary import.
"""

from __future__ import annotations

import random
import socket
import subprocess

#: The default draw range for a probed port: high enough to sit above the well-known and
#: registered ranges people actually run things on, below the ephemeral top.
DEFAULT_PORT_RANGE = (20000, 59999)

#: The subnet handed back when the routing table refuses to yield an unused candidate. It
#: is also the compose templates' own literal default, so a hand-assembled stack and a
#: fallback here land on the same network.
FALLBACK_SUBNET = "10.222.222.0/24"


class NoFreePorts(RuntimeError):
    """The machine would not yield the requested number of free localhost ports."""


def probe_free_ports(count: int, *, lo: int = DEFAULT_PORT_RANGE[0], hi: int = DEFAULT_PORT_RANGE[1]) -> list[int]:
    """Distinct localhost ports that are free right now.

    Random draws instead of a fixed block: two projects generated on the same machine must
    never collide with each other, or with anything else already listening. Users are never
    asked about ports.
    """
    ports: list[int] = []
    attempts = 0
    while len(ports) < count:
        attempts += 1
        if attempts > 500:
            raise NoFreePorts("could not find enough free localhost ports (tried 500 times).")
        port = random.randrange(lo, hi)
        if port in ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        ports.append(port)
    return ports


def probe_free_subnet() -> str:
    """A random private /24 for a stack's Docker network, checked (best-effort) against the
    host routing table.

    Random for the same reason ports are: two stacks on one machine must not collide, and
    Docker's default address pools are a finite resource that many-project machines exhaust.
    """
    routed = ""
    for probe_cmd in (["netstat", "-rn", "-f", "inet"], ["ip", "route"]):
        try:
            routed = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5).stdout
            break
        except (OSError, subprocess.TimeoutExpired):
            continue
    for _ in range(200):
        second, third = random.randrange(128, 255), random.randrange(0, 255)
        subnet = f"10.{second}.{third}.0/24"
        if f"10.{second}.{third}." not in routed and subnet != FALLBACK_SUBNET:
            return subnet
    return FALLBACK_SUBNET  # fallback: the compose template's own default


__all__ = [
    "DEFAULT_PORT_RANGE",
    "FALLBACK_SUBNET",
    "NoFreePorts",
    "probe_free_ports",
    "probe_free_subnet",
]
