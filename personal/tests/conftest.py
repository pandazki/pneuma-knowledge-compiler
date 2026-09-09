"""Keyless home fixtures; middleware, port allocation and providers never touch the machine."""

import itertools
import os
import subprocess
from types import SimpleNamespace

import pytest

from pkc_personal import home as home_module, library as library_module, setup as setup_module
from pkc_personal.home import Home
from pkc_personal.library import pkc_script


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "owner"))
    monkeypatch.setenv("PKC_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("PKC_LIBRARY", raising=False)
    # The console's two overrides are the developer's own; no test inherits the machine's.
    monkeypatch.delenv("PKC_CONSOLE_DIST", raising=False)
    monkeypatch.delenv("PKC_CONSOLE_URL", raising=False)
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


class _Provider:
    """The embedding provider's verdict on a candidate key, faked in one place.

    Installed for every test and unreachable by default: a test that stores the embedding
    key states what the provider answers (`accepts()` / `refuses(error)`), and a test that
    stores one without saying so fails loudly rather than opening a socket.
    """

    def __init__(self, monkeypatch) -> None:
        self._monkeypatch = monkeypatch
        self.calls: list[tuple[str, str]] = []
        self._install(self._unreachable)

    @staticmethod
    def _unreachable() -> None:
        raise AssertionError(
            "a test reached the embedding provider; state the verdict with "
            "provider.accepts() or provider.refuses(...)"
        )

    def _install(self, verdict) -> None:
        def probe(spec: str, value: str, **_kwargs) -> None:
            self.calls.append((spec, value))
            verdict()

        self._monkeypatch.setattr(library_module, "probe_embedding_key", probe)

    def accepts(self) -> "_Provider":
        self._install(lambda: None)
        return self

    def refuses(self, error: BaseException | None = None) -> "_Provider":
        failure = error or RuntimeError("synthetic provider refusal")

        def raise_it() -> None:
            raise failure

        self._install(raise_it)
        return self


@pytest.fixture(autouse=True)
def provider(monkeypatch):
    return _Provider(monkeypatch)


@pytest.fixture
def pkc(monkeypatch):
    """Every `pkc profile` call, answered by the test; every other subprocess really runs."""
    real = subprocess.run

    class Runner:
        def __init__(self):
            self.calls: list[list[str]] = []
            self.answers: dict[str, SimpleNamespace] = {}
            self.default = SimpleNamespace(returncode=0, stdout="", stderr="")

        def answer(self, verbs: str, *, returncode: int = 0, stdout: str = "", stderr: str = ""):
            self.answers[verbs] = SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
            return self

        def __call__(self, command, **kwargs):
            if list(command)[:2] != [pkc_script(), "profile"]:
                return real(command, **kwargs)
            self.calls.append(list(command))
            return self.answers.get(" ".join(command[1:3]), self.default)

        def fields(self, provenance: str) -> list[str]:
            for command in self.calls:
                if command[1:3] == ["profile", "set"] and command[-1] == provenance:
                    return [command[index + 1] for index, item in enumerate(command)
                            if item == "--field"]
            return []

    runner = Runner()
    monkeypatch.setattr(setup_module.subprocess, "run", runner)
    return runner
