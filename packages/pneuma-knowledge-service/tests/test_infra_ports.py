"""Ports and subnets are probed, never assumed.

Two libraries standing up on one machine must not collide, and nobody is asked to pick a
number. Both probes are random draws checked against the machine itself; these tests pin
what a caller may rely on.
"""

from __future__ import annotations

import ipaddress
import socket

import pytest

from pneuma_knowledge_service.infra import ports


def test_probed_ports_are_distinct_in_range_and_actually_bindable():
    probed = ports.probe_free_ports(6)
    assert len(set(probed)) == 6
    lo, hi = ports.DEFAULT_PORT_RANGE
    for port in probed:
        assert lo <= port <= hi
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))


def test_an_exhausted_range_refuses_instead_of_looping_forever():
    # One port wide and already taken: the probe must give up with a stated reason rather
    # than spin, which is what a caller turns into its own error message.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as taken:
        taken.bind(("127.0.0.1", 0))
        port = taken.getsockname()[1]
        with pytest.raises(ports.NoFreePorts):
            ports.probe_free_ports(1, lo=port, hi=port + 1)


def test_the_probed_subnet_is_a_private_slash_24():
    network = ipaddress.ip_network(ports.probe_free_subnet())
    assert network.prefixlen == 24
    assert network.is_private
    assert str(network).startswith("10.")


def test_the_fallback_subnet_is_the_compose_templates_own_default():
    assert ports.FALLBACK_SUBNET == "10.222.222.0/24"
