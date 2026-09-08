"""Keyless home fixtures; middleware and port allocation never touch the machine."""

import itertools
import os

import pytest

from pkc_personal import home as home_module, library as library_module
from pkc_personal.home import Home


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "owner"))
    monkeypatch.setenv("PKC_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PKC_LIBRARY", raising=False)
    for key in list(os.environ):
        if key.startswith("PNEUMA_KNOWLEDGE_"):
            monkeypatch.delenv(key)
    ports = itertools.count(24000)
    probe = lambda count: [next(ports) for _ in range(count)]
    monkeypatch.setattr(home_module, "probe_free_ports", probe)
    monkeypatch.setattr(library_module, "probe_free_ports", probe)
    result = Home()
    result.initialize()
    return result


@pytest.fixture
def make_library(home, monkeypatch):
    monkeypatch.setattr(library_module, "render_library", lambda *_: None)
    return lambda name="notes", **kwargs: library_module.create_library(home, name, **kwargs)
