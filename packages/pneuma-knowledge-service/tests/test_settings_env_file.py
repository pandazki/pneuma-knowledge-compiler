"""Dotenv selection comes only from the process environment, in both settings passes."""

import pytest

from pneuma_knowledge_service.settings import Settings, get_settings


@pytest.mark.parametrize("with_engine", [False, True])
@pytest.mark.parametrize("selection", [None, "", "selected.env"])
def test_dotenv_selection(monkeypatch, tmp_path, with_engine, selection):
    monkeypatch.chdir(tmp_path)
    for name in ("ENV_FILE", "ENGINE_DIR", "CANONICAL_ROOT", "RECALL_CLAIM_CAP"):
        monkeypatch.delenv(f"PNEUMA_KNOWLEDGE_{name}", raising=False)
    (tmp_path / ".env").write_text(
        "PNEUMA_KNOWLEDGE_CANONICAL_ROOT=from-cwd\n"
        "PNEUMA_KNOWLEDGE_ENV_FILE=ignored.env\n",
        encoding="utf-8",
    )
    (tmp_path / "selected.env").write_text(
        "PNEUMA_KNOWLEDGE_CANONICAL_ROOT=from-selected\n", encoding="utf-8"
    )
    if selection is not None:
        monkeypatch.setenv(
            "PNEUMA_KNOWLEDGE_ENV_FILE", str(tmp_path / selection) if selection else ""
        )
    if with_engine:
        engine = tmp_path / "engine"
        (engine / "recall").mkdir(parents=True)
        (engine / "recall/recall.yaml").write_text("claim_cap: 73\n", encoding="utf-8")
        monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", str(engine))

    settings = get_settings()

    assert settings.canonical_root == {
        None: "from-cwd",
        "": Settings.model_fields["canonical_root"].default,
        "selected.env": "from-selected",
    }[selection]
    if with_engine:
        assert settings.recall_claim_cap == 73


def test_selected_dotenv_can_locate_engine_without_overriding_process_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PNEUMA_KNOWLEDGE_ENGINE_DIR", raising=False)
    monkeypatch.delenv("PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP", raising=False)
    engine = tmp_path / "engine"
    (engine / "recall").mkdir(parents=True)
    (engine / "recall/recall.yaml").write_text("claim_cap: 73\n", encoding="utf-8")
    selected = tmp_path / "selected.env"
    selected.write_text(
        f"PNEUMA_KNOWLEDGE_ENGINE_DIR={engine}\n"
        "PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP=55\n"
        "PNEUMA_KNOWLEDGE_CANONICAL_ROOT=from-selected\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_ENV_FILE", str(selected))
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_CANONICAL_ROOT", "from-process")

    settings = get_settings()

    assert settings.engine_dir == str(engine)
    assert settings.recall_claim_cap == 73
    assert settings.canonical_root == "from-process"
