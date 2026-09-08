"""Cross-application shape checks belong here, outside the standalone personal project."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_personal_engine_has_the_scaffold_engine_file_shape(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "personal" / "src"))
    from pkc_personal import home as home_module, library as library_module
    from pkc_personal.home import Home

    monkeypatch.setattr(home_module, "probe_free_ports", lambda count: list(range(31000, 31000 + count)))
    monkeypatch.setattr(library_module, "probe_free_ports", lambda count: [32000])
    monkeypatch.setattr(library_module, "render_library", lambda *_: None)
    home = Home(tmp_path / "home")
    home.initialize()
    library = library_module.create_library(home, "notes", backend="api")
    answers = tmp_path / "answers.json"
    answers.write_text(json.dumps({"language": "en", "compiler": "api", "data": {"mode": "none"}}))
    target = tmp_path / "generated"
    # Run the real answers-file command with only the OS port/subnet probes replaced.
    # This comparison concerns file layout, and runs in sandboxes that forbid socket.bind.
    harness = """
import importlib.util, sys
sys.argv = sys.argv[1:]
spec = importlib.util.spec_from_file_location('generator', sys.argv[0])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.probe_free_ports = lambda count: list(range(33000, 33000 + count))
module.probe_free_subnet = lambda: '10.222.221.0/24'
module.main()
"""
    result = subprocess.run(
        [sys.executable, "-c", harness, str(ROOT / "scaffold" / "init.py"), "--answers", str(answers), "--target", str(target)],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout

    def files(engine):
        return {p.relative_to(engine).as_posix() for p in engine.rglob("*")
                if p.is_file() and ".git" not in p.relative_to(engine).parts}

    assert files(library.engine_dir) == files(target / "engine")


def test_personal_is_not_a_root_workspace_member_and_owns_only_pkchome():
    import tomllib

    root = tomllib.loads((ROOT / "pyproject.toml").read_text())
    personal = tomllib.loads((ROOT / "personal" / "pyproject.toml").read_text())
    assert "personal" not in root["tool"]["uv"]["workspace"]["members"]
    assert personal["tool"]["uv"]["workspace"]["members"] == []
    assert personal["project"]["scripts"] == {"pkchome": "pkc_personal.cli:main"}
    assert (ROOT / "personal" / "uv.lock").is_file()
