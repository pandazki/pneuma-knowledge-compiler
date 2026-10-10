"""Project identity reaches compilation without rewriting L0 or crossing tenants."""

from copy import deepcopy
import asyncio
import json
import subprocess
from types import SimpleNamespace

import pytest

from pkc_personal import collection
from pkc_personal.library import render_library
from pkc_personal.project_component import ProjectComponent


def source(user_id, provider="codex", native_id="synthetic-session", path="/desktop/atlas"):
    return SimpleNamespace(raw=SimpleNamespace(user_id=user_id, source_id="s01", kind="agent_session",
        meta={"provider": provider, "session_id": native_id, "project": {"path": path, "name": "atlas"}}))


def test_project_binding_is_available_before_ingest_and_survives_source_aliasing(home, make_library):
    library = make_library()
    observation = {"origin": {"device_id": "desktop", "git_remote": "git@github.com:synthetic/atlas.git"},
                   "provider": "codex", "session_id": "synthetic-session", "project_path": "/desktop/atlas",
                   "material_id": "synthetic", "snapshot_id": "synthetic-snapshot"}
    collection.observer(library)(observation)
    item = source(library.state.tenant)
    before = deepcopy(item.raw.meta)
    component = ProjectComponent(library)
    with pytest.raises(ValueError, match="not prepared"):
        component.source_preamble(item)
    asyncio.run(component.prepare(library.state.tenant))
    line = component.source_preamble(item)
    assert collection.projects(library)[0]["project_id"] in line
    assert "synthetic/atlas" in line
    assert item.raw.meta == before
    assert "s01" not in line
    second = {**observation, "session_id": "remote-session", "project_path": "/remote/atlas",
              "origin": {"device_id": "remote", "git_remote": "https://github.com/synthetic/atlas"}}
    collection.observe(library, [second])
    asyncio.run(component.prepare(library.state.tenant))
    other = component.source_preamble(source(library.state.tenant, native_id="remote-session", path="/remote/atlas"))
    assert json.loads(line.split(": ", 1)[1])["project_id"] == json.loads(other.split(": ", 1)[1])["project_id"]


def test_project_component_refuses_other_tenants_and_rebuild_replays_only_kept_records(home, make_library):
    library = make_library()
    collection.observe(library, [{"origin": {"device_id": "desktop"}, "provider": "codex",
                                 "session_id": "synthetic-session", "project_path": "/desktop/atlas"}])
    records = (library.path / "collection-observations.jsonl").read_bytes()
    project_id = collection.projects(library)[0]["project_id"]
    component = ProjectComponent(library)
    asyncio.run(component.prepare(library.state.tenant))
    with pytest.raises(ValueError, match="tenant mismatch"):
        component.source_preamble(source("another-tenant"))
    with pytest.raises(ValueError, match="tenant mismatch"):
        asyncio.run(component.prepare("another-tenant"))
    with pytest.raises(ValueError, match="not prepared"):
        component.source_preamble(source(library.state.tenant))
    (library.path / "collection-projects.json").unlink()
    asyncio.run(component.rebuild(library.state.tenant))
    assert (library.path / "collection-observations.jsonl").read_bytes() == records
    assert collection.projects(library)[0]["project_id"] == project_id


def test_personal_cli_and_skill_install_share_the_engine_component(home, make_library):
    library = make_library()
    render_library(home, library)
    entry = library.path / "bin" / "pkc"
    assert entry.is_file()
    assert library.show()["entry"] == str(library.skill_dir / "scripts" / "pkc")
    gate = (library.skill_dir / "references" / "gate.md").read_text()
    assert "collection-projects" in gate
    verified = subprocess.run([str(entry), "skill", "verify", "--backend", "codex", "--project", str(library.path)],
                              capture_output=True, text=True)
    assert verified.returncode == 0, verified.stderr
