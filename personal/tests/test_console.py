"""The console page: where it is found, and how a downloaded one is trusted.

Offline throughout — every download is an injected `fetch`, and the packaged copy (which
really exists in a checkout that has run scripts/personal_console_dist.sh) is monkeypatched
away, so what these tests measure is the code and not the machine they run on.
"""

import hashlib
import io
import json
import tarfile
from types import SimpleNamespace

import pytest

from pkc_personal import cli, console, engine, infra, setup, skill_install, status
from pkc_personal.home import atomic_write, yaml_text


def _tarball(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in entries.items():
            payload = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


PAGE = {"dist/index.html": "<!doctype html>console\n", "dist/assets/app.js": "export {}\n"}


def _fetch(payload: bytes, *, digest: str | None = None, calls: list | None = None):
    url = console.tarball_url()
    published = f"{digest or hashlib.sha256(payload).hexdigest()}  {url.rsplit('/', 1)[-1]}\n"
    files = {url: payload, f"{url}.sha256": published.encode("utf-8")}

    def fetch(requested: str) -> bytes:
        if calls is not None:
            calls.append(requested)
        try:
            return files[requested]
        except KeyError:
            raise console.ConsoleUnavailable(f"console not fetched from {requested}: nothing there") from None

    return fetch


@pytest.fixture(autouse=True)
def unpackaged(monkeypatch, tmp_path):
    """No wheel copy unless a test asks for one: a checkout usually carries a built dist."""
    monkeypatch.setattr(console, "PACKAGED_DIST", tmp_path / "no-wheel-copy" / "dist")


def test_a_verified_tarball_lands_once_and_a_second_call_is_a_no_op(home):
    calls = []
    installed = console.install_console(home, fetch=_fetch(_tarball(PAGE), calls=calls))

    version = console.console_version()
    assert installed == home.path / "console" / version / "dist"
    assert (installed / "index.html").read_text() == PAGE["dist/index.html"]
    assert (installed / "assets" / "app.js").is_file()
    assert console.home_dist(home) == installed
    assert len(calls) == 2

    calls.clear()
    assert console.install_console(home, fetch=_fetch(_tarball(PAGE), calls=calls)) == installed
    assert calls == []
    # Nothing is staged beside the published copy.
    assert [path.name for path in (home.path / "console").iterdir()] == [version]


def test_a_digest_that_does_not_match_is_refused_and_leaves_nothing(home):
    payload = _tarball(PAGE)
    wrong = hashlib.sha256(b"another build").hexdigest()
    with pytest.raises(console.ConsoleUnavailable, match="sha256 mismatch"):
        console.install_console(home, fetch=_fetch(payload, digest=wrong))
    assert console.home_dist(home) is None
    assert not (home.path / "console" / console.console_version()).exists()

    # A sha256 file that is not a digest is refused for the same reason: nothing to trust.
    with pytest.raises(console.ConsoleUnavailable, match="no sha256 digest"):
        console.install_console(home, fetch=_fetch(payload, digest="not-a-digest"))
    assert console.home_dist(home) is None


def test_a_member_that_escapes_the_target_is_refused(home):
    escaping = _tarball({"dist/index.html": "ok\n", "../escaped.html": "no\n"})
    with pytest.raises(console.ConsoleUnavailable):
        console.install_console(home, fetch=_fetch(escaping))
    assert console.home_dist(home) is None
    assert not (home.path.parent / "escaped.html").exists()

    # And a tarball with no dist/ at the top is not a console page.
    with pytest.raises(console.ConsoleUnavailable, match="no dist/"):
        console.install_console(home, fetch=_fetch(_tarball({"index.html": "loose\n"})))
    assert console.home_dist(home) is None


def test_a_symlink_member_is_refused_even_though_it_stays_inside(home):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        payload = b"<!doctype html>\n"
        info = tarfile.TarInfo("dist/index.html")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
        link = tarfile.TarInfo("dist/home.html")
        link.type = tarfile.SYMTYPE
        link.linkname = "index.html"
        archive.addfile(link)
    with pytest.raises(console.ConsoleUnavailable, match="is a link"):
        console.install_console(home, fetch=_fetch(buffer.getvalue()))
    assert console.home_dist(home) is None


def test_macos_resource_forks_are_dropped_rather_than_served(home):
    """The 0.1.0 asset was tarred on a Mac: `._name` beside every entry, and no page in it."""
    installed = console.install_console(home, fetch=_fetch(_tarball(
        {"._dist": "fork\n", "dist/._index.html": "fork\n", **PAGE})))
    assert sorted(path.name for path in installed.rglob("*")) == ["app.js", "assets", "index.html"]
    assert not (home.path / "console" / console.console_version() / "._dist").exists()


def test_the_three_places_are_read_in_one_order(home, monkeypatch, tmp_path):
    assert console.console_dist(home) is None
    assert console.console_state(home) == "missing — run pkchome console install"

    downloaded = console.install_console(home, fetch=_fetch(_tarball(PAGE)))
    assert console.console_dist(home) == downloaded
    assert console.console_state(home) == f"downloaded v{console.console_version()}"

    packaged = tmp_path / "wheel" / "dist"
    (packaged / "assets").mkdir(parents=True)
    (packaged / "index.html").write_text("packaged\n")
    monkeypatch.setattr(console, "PACKAGED_DIST", packaged)
    assert console.console_dist(home) == packaged
    assert console.console_state(home) == "packaged"

    local = tmp_path / "local-console-dist"
    local.mkdir()
    (local / "index.html").write_text("local\n")
    monkeypatch.setenv("PKC_CONSOLE_DIST", str(local))
    assert console.console_dist(home) == local
    assert console.console_state(home) == f"local build at {local}"

    # A developer's override that names nothing is said out loud, never quietly ignored.
    monkeypatch.setenv("PKC_CONSOLE_DIST", str(tmp_path / "typo"))
    with pytest.raises(ValueError, match="not a directory"):
        console.console_dist(home)


def test_the_engine_serves_the_copy_this_home_downloaded(home, make_library, monkeypatch):
    library = make_library()
    monkeypatch.setattr(engine, "Settings", SimpleNamespace(model_fields={"worker_tenants": object()}))
    commands = []
    monkeypatch.setattr(engine.subprocess, "Popen",
                        lambda command, **kwargs: commands.append(command) or SimpleNamespace(
                            pid=515151, poll=lambda: None))
    monkeypatch.setattr(engine, "pid_alive", lambda _: False)

    # With no page anywhere the engine is started without the flag rather than with a bad one.
    assert engine.start(home, library) is True
    assert "--static-dir" not in commands[0]

    downloaded = console.install_console(home, fetch=_fetch(_tarball(PAGE)))
    assert engine.start(home, library) is True
    assert commands[1][-2:] == ["--static-dir", str(downloaded)]


def _setup_answers(tmp_path):
    answers = tmp_path / "answers.yaml"
    atomic_write(answers, yaml_text({"library": "notes", "language": "en", "backend": "codex",
                                     "semantic_retrieval": False}))
    return answers


def _quiet_setup(monkeypatch):
    monkeypatch.setattr(infra, "up", lambda _home: None)
    monkeypatch.setattr(skill_install, "install", lambda *_, **__: [])
    monkeypatch.setattr(setup, "persist_owner_profile", lambda *_, **__: False)
    monkeypatch.setattr(setup, "render_library", lambda *_: None)
    monkeypatch.setattr(setup.engine, "start", lambda *_: True)


def test_setup_fetches_the_page_and_reports_it(home, monkeypatch, tmp_path, capsys):
    _quiet_setup(monkeypatch)
    monkeypatch.setattr(console, "_fetch", _fetch(_tarball(PAGE)))
    setup.setup(home, _setup_answers(tmp_path))
    output = capsys.readouterr().out
    assert "console;" in output and "console skipped" not in output
    assert console.home_dist(home) is not None


def test_a_console_that_cannot_be_fetched_does_not_fail_setup(home, monkeypatch, tmp_path, capsys):
    _quiet_setup(monkeypatch)

    def unreachable(_url: str) -> bytes:
        raise console.ConsoleUnavailable("console not fetched from https://example.invalid: no route")

    monkeypatch.setattr(console, "_fetch", unreachable)
    setup.setup(home, _setup_answers(tmp_path))
    output = capsys.readouterr().out
    assert "console skipped: console not fetched from https://example.invalid: no route" in output
    assert "engine on port" in output
    assert console.home_dist(home) is None


def test_the_install_verb_says_which_of_the_three_it_found(home, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(console, "_fetch", _fetch(_tarball(PAGE)))
    assert cli.main(["console", "install"]) == 0
    first = capsys.readouterr().out
    assert first == f"console: installed v{console.console_version()} at {console.home_dist(home)}\n"

    assert cli.main(["console", "install"]) == 0
    assert capsys.readouterr().out == "console: already installed\n"

    packaged = tmp_path / "wheel" / "dist"
    packaged.mkdir(parents=True)
    (packaged / "index.html").write_text("packaged\n")
    monkeypatch.setattr(console, "PACKAGED_DIST", packaged)
    assert cli.main(["console", "install"]) == 0
    assert capsys.readouterr().out == "console: packaged\n"

    local = tmp_path / "local-console-dist"
    local.mkdir()
    (local / "index.html").write_text("local\n")
    monkeypatch.setenv("PKC_CONSOLE_DIST", str(local))
    assert cli.main(["console", "install"]) == 0
    assert capsys.readouterr().out == "console: local build\n"


def test_opening_the_console_fetches_it_first_and_exits_3_when_it_cannot(home, make_library, monkeypatch, capsys):
    make_library()
    opened = []
    monkeypatch.setattr(cli.webbrowser, "open", lambda url: opened.append(url))

    def unreachable(url: str) -> bytes:
        raise console.ConsoleUnavailable(f"console not fetched from {url}: no route")

    monkeypatch.setattr(console, "_fetch", unreachable)
    assert cli.main(["console", "--library", "notes"]) == 3
    assert opened == [] and "no route" in capsys.readouterr().err

    monkeypatch.setattr(console, "_fetch", _fetch(_tarball(PAGE)))
    assert cli.main(["console", "--library", "notes"]) == 0
    assert console.home_dist(home) is not None
    port = cli.resolve_library(home, "notes").state.engine.port
    assert opened == [f"http://127.0.0.1:{port}"]


def test_status_names_the_page_the_machine_has(home, make_library, monkeypatch, capsys):
    make_library()
    monkeypatch.setattr(infra, "docker_reachable", lambda: False)
    monkeypatch.setattr(status, "queue_status", lambda _: None)
    assert cli.main(["status", "--json"]) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["home"]["console"] == "missing — run pkchome console install"
    assert "Console: missing — run pkchome console install" in status.render_text(document)

    console.install_console(home, fetch=_fetch(_tarball(PAGE)))
    assert "Console: downloaded v" in status.render_text(status.status_document(home))
