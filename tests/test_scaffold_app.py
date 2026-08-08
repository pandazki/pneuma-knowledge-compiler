"""Unit tests for the scaffold machinery driver (scaffold/templates/app.py).

The driver is a template, not a package: only the framework-free helpers that carry
real judgment — locale detection parsing, provenance stamping, stack isolation, and the
material-file grammar — are worth pinning. The module is loaded by path; its top level is
stdlib-only by design, so this import must never pull the framework in.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "scaffold" / "templates" / "app.py"


def _load_by_path(name: str, path: Path):
    # Never write bytecode into the scaffold: it is a template shipped by copy, and a
    # __pycache__/ written here by the test run would ride along into every generated
    # project.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


app = _load_by_path("scaffold_app_under_test", APP_PATH)


def test_scaffold_app_top_level_is_framework_free():
    # Loading the module must not import the framework: the bootstrap path (system
    # python, before the uv re-exec) depends on it. Checked in a fresh interpreter —
    # inside the suite, sys.modules is already polluted by other tests.
    import subprocess

    script = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.spec_from_file_location('scaffold_app', {str(APP_PATH)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "assert 'pneuma_knowledge_service' not in sys.modules\n"
        "assert 'pneuma_knowledge_core' not in sys.modules\n"
        "assert 'yaml' not in sys.modules\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


def test_machinery_speaks_english_only():
    # The machinery files are language-neutral by contract: all user-facing copy is
    # English, and localization lives in the generated docs / the guiding agent. The one
    # allowed Han occurrences are functional Unicode ranges inside regex patterns.
    import re

    for name in (
        "app.py",
        "start.sh",
        "docker-compose.yml",
        "gitignore",
        "server.py",
        "worker.py",
    ):
        text = (ROOT / "scaffold" / "templates" / name).read_text(encoding="utf-8")
        lines = [
            line
            for line in text.splitlines()
            if re.search(r"[一-鿿]", line) and "一-鿿" not in line
        ]
        assert not lines, f"Chinese text left in machinery {name}: {lines[:3]}"


def test_timezone_from_localtime_link_parses_macos_and_linux_shapes():
    assert (
        app.timezone_from_localtime_link("/var/db/timezone/zoneinfo/Asia/Shanghai")
        == "Asia/Shanghai"
    )
    assert (
        app.timezone_from_localtime_link("../usr/share/zoneinfo/Europe/Berlin")
        == "Europe/Berlin"
    )
    assert (
        app.timezone_from_localtime_link("/usr/share/zoneinfo.default/UTC") == "UTC"
    )
    assert app.timezone_from_localtime_link("/etc/somewhere-else") is None


def test_locale_from_lang_parses_bcp47_and_region():
    assert app.locale_from_lang("zh_CN.UTF-8") == ("zh-CN", "CN")
    assert app.locale_from_lang("en_US") == ("en-US", "US")
    assert app.locale_from_lang("C") == (None, None)
    assert app.locale_from_lang("") == (None, None)


def test_split_frontmatter_round_trip():
    front, body = app.split_frontmatter("---\ndate: 2026-07-06\n---\n正文\n")
    assert front == "date: 2026-07-06"
    assert body == "正文\n"
    front, body = app.split_frontmatter("没有 frontmatter\n")
    assert front == ""
    assert body == "没有 frontmatter\n"


def test_strip_html_comments_removes_editor_guidance_only():
    text = "# 标题\n<!-- 单行引导 -->\n正文一\n<!-- 跨行\n引导 -->\n正文二\n"
    assert app.strip_html_comments(text) == "# 标题\n正文一\n正文二\n"


def test_example_contract_has_operative_body_after_comment_stripping():
    # The bundled demo contract must still teach the model something once the
    # human-facing guidance comments are stripped.
    _front, body = app.split_frontmatter(
        (ROOT / "scaffold" / "example" / "contract.md").read_text(encoding="utf-8")
    )
    stripped = app.strip_html_comments(body).strip()
    assert "主体族" in stripped
    assert "<!--" not in stripped
    assert "TODO" not in stripped  # the example is filled, not a skeleton
    assert len(stripped) > 500


def test_contract_skeletons_carry_todo_slots_and_guidance():
    for name in ("contract.zh.md", "contract.en.md"):
        text = (ROOT / "scaffold" / "templates" / name).read_text(encoding="utf-8")
        assert "{{SKILL_ID}}" in text
        assert "TODO" in text
        assert "aurora-planner" not in text  # no demo residue in the skeleton


def test_parse_conversation_turns_grammar():
    turns = app.parse_conversation_turns("甲：第一句。\n乙: second\n跨行续上。\n")
    assert turns == [("甲", "第一句。"), ("乙", "second\n跨行续上。")]
    assert app.parse_conversation_turns("只有叙述，没有冒号行\n") == []


def test_parse_conversation_turns_accepts_multi_word_capitalized_speakers():
    # Found by the EverMemBench full run: "Weihua Zhang: …" was folded into the previous
    # turn, dissolving whole English transcripts. Capitalized multi-token names are
    # speakers; lowercase prose before a colon still folds as continuation.
    turns = app.parse_conversation_turns(
        "Weihua Zhang: kickoff at nine.\n"
        "Mary Jane Watson: noted.\n"
        "note that: this is prose, not a speaker\n"
    )
    assert turns[0] == ("Weihua Zhang", "kickoff at nine.")
    assert turns[1][0] == "Mary Jane Watson"
    assert "note that: this is prose" in turns[1][1]  # folded, not a new speaker


def test_isolation_accepts_the_projects_own_ports():
    assert (
        app.isolation_problems(
            "postgresql://u:p@localhost:15436/db",
            "http://localhost:16373",
            "http://localhost:17704",
            str(app.PROJECT_ROOT / "data" / "canonical"),
        )
        == []
    )


def test_isolation_refuses_ports_that_are_not_this_projects():
    # Ports are project-private (probed at generation): any URL pointing elsewhere —
    # which is exactly what pointing at some other stack on the machine looks like —
    # is refused before anything connects.
    problems = app.isolation_problems(
        "postgresql://u:p@localhost:15432/db",
        "http://localhost:16333",
        "http://localhost:17700",
        str(app.PROJECT_ROOT / "data" / "canonical"),
    )
    assert len(problems) == 3
    assert all("does not point at this project's own port" in p for p in problems)


def test_isolation_refuses_canonical_root_outside_project(tmp_path):
    problems = app.isolation_problems(
        "postgresql://u:p@localhost:15436/db",
        "http://localhost:16373",
        "http://localhost:17704",
        str(tmp_path / "canonical"),
    )
    assert any("canonical_root" in p for p in problems)


PROFILE_TEMPLATE = """display_name: "示例"
locale:
  city: ""
  country: ""         # 注释保留
  timezone: ""
  language: ""
provenance:
  timezone: unstated
  language: unstated
  region: unstated
"""


def test_stamp_writes_detected_values_with_deployment_default_provenance():
    detected = {"timezone": "Asia/Shanghai", "language": "zh-CN", "region": "CN"}
    new_text, stamped = app.stamp_profile_text(PROFILE_TEMPLATE, detected)
    assert set(stamped) == {"timezone", "language", "region"}
    assert 'timezone: "Asia/Shanghai"' in new_text
    assert 'language: "zh-CN"' in new_text
    assert 'country: "CN"         # 注释保留' in new_text  # comments survive stamping
    provenance = app.current_provenance(new_text)
    # The exact core vocabulary (domain/time_context.py ZoneSource), not an invented term.
    assert provenance == {
        "timezone": "deployment_default",
        "language": "deployment_default",
        "region": "deployment_default",
    }


def test_stamp_never_touches_a_user_confirmed_field():
    confirmed = PROFILE_TEMPLATE.replace('timezone: ""', 'timezone: "Asia/Tokyo"').replace(
        "timezone: unstated", "timezone: profile"
    )
    detected = {"timezone": "America/New_York", "language": "en-US", "region": "US"}
    new_text, stamped = app.stamp_profile_text(confirmed, detected)
    assert "timezone" not in stamped
    assert 'timezone: "Asia/Tokyo"' in new_text
    assert app.current_provenance(new_text)["timezone"] == "profile"


def test_stamp_restamps_a_deployment_default_field():
    once, _ = app.stamp_profile_text(
        PROFILE_TEMPLATE, {"timezone": "Asia/Shanghai", "language": None, "region": None}
    )
    twice, stamped = app.stamp_profile_text(
        once, {"timezone": "Europe/Berlin", "language": None, "region": None}
    )
    assert "timezone" in stamped
    assert 'timezone: "Europe/Berlin"' in twice


def test_skip_unparseable_detection_leaves_file_unchanged():
    new_text, stamped = app.stamp_profile_text(
        PROFILE_TEMPLATE, {"timezone": None, "language": None, "region": None}
    )
    assert stamped == []
    assert new_text.rstrip("\n") == PROFILE_TEMPLATE.rstrip("\n")


# ------------------------------------------------------- material-language heuristic


def test_dominant_script_calls_the_obvious_cases():
    zh = "把第一个里程碑定下来了：八月十五日，内部可用版。内容就两块：周视图与拖拽排程。"
    en = (
        "We agreed the first milestone is the internal build on August 15. "
        "It covers the week view and drag-based scheduling only."
    )
    assert app.dominant_script(zh * 2) == "zh"
    assert app.dominant_script(en * 2) == "en"
    # Too little signal, or genuinely mixed → no verdict, so no prompt fires on it.
    assert app.dominant_script("ok 好") is None
    assert app.dominant_script(zh + en * 3) is None


def test_material_language_reads_md_files_and_skips_readme(tmp_path):
    (tmp_path / "2026-07-01-笔记.md").write_text(
        "今天把排程器的第一个原型跑通了，下一步是把周视图接上真实数据。" * 5,
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text(
        "This folder holds demo notes for the sample application. " * 30,
        encoding="utf-8",
    )
    assert app.material_language(tmp_path) == "zh"
    assert app.material_language(tmp_path / "missing") is None


def test_material_language_of_bundled_example_data_is_chinese():
    assert app.material_language(ROOT / "scaffold" / "example" / "data") == "zh"


def test_language_agrees_compares_primary_subtags():
    assert app.language_agrees("zh-CN", "zh")
    assert not app.language_agrees("en-US", "zh")
    # Missing either side → agree (nothing to confront the user with).
    assert app.language_agrees(None, "zh")
    assert app.language_agrees("en-US", None)


def test_set_profile_language_updates_value_and_provenance_keeping_comments():
    text = PROFILE_TEMPLATE.replace('language: ""', 'language: ""      # 注释在')
    updated = app.set_profile_language(text, "zh", "profile")
    assert 'language: "zh"      # 注释在' in updated
    assert app.current_provenance(updated)["language"] == "profile"
    assert app.profile_language(updated) == "zh"
    # Timezone/region lines untouched.
    assert app.current_provenance(updated)["timezone"] == "unstated"


# ------------------------------------------------------------------ citation legend


def test_cited_handles_are_ordered_and_deduped():
    answer = (
        "里程碑定在 8 月 15 日 [cite: s02 ¶3-5]。分工先前谈妥 "
        "[cite: s01 ¶1-2, s02 ¶7]，后来又确认过一次 [cite: s01 ¶4]。"
    )
    assert app.cited_handles(answer) == ["s02", "s01"]
    assert app.cited_handles("没有引用的回答。") == []


def test_citation_legend_maps_handles_to_titles_and_dates():
    answer = "答案 [cite: s01 ¶1-3] 和 [cite: s02 ¶2] 以及 [cite: s03 ¶9]。"
    handle_map = {"s01": "uuid-aaa", "s02": "uuid-bbb"}
    source_info = {
        "uuid-aaa": ("2026-07-12-里程碑.md", "2026-07-12"),
        "uuid-bbb": ("与林知远定分工", ""),
    }
    lines = app.citation_legend_lines(answer, handle_map, source_info)
    assert lines[0] == "s01 = 2026-07-12-里程碑.md（2026-07-12）"
    assert lines[1] == "s02 = 与林知远定分工"  # no date → no empty parens
    assert lines[2] == "s03 = (unknown source)"  # an unresolvable handle is not guessed


def test_claims_from_detail_parses_projection_payload():
    assert app.claims_from_detail('projection:{"total":9,"upserted":4,"deleted":0,"unchanged":5}') == 4
    assert app.claims_from_detail("noop") is None
    assert app.claims_from_detail(None) is None
    assert app.claims_from_detail("projection:not-json") is None


def test_demo_questions_ride_with_the_data_not_the_machinery(tmp_path, monkeypatch):
    # No demo-questions.txt → no questions, and that is not an error.
    monkeypatch.setattr(app, "DEMO_QUESTIONS_PATH", tmp_path / "missing.txt")
    assert app.demo_questions() == []
    path = tmp_path / "demo-questions.txt"
    path.write_text("问题一？\n\n问题二？\n", encoding="utf-8")
    monkeypatch.setattr(app, "DEMO_QUESTIONS_PATH", path)
    assert app.demo_questions() == ["问题一？", "问题二？"]


# ------------------------------------------------------------------- CLI surface


def test_glance_command_exists_in_the_cli():
    import subprocess

    result = subprocess.run(
        [sys.executable, str(APP_PATH), "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "glance" in result.stdout
    assert "preflight" in result.stdout
    assert "restore" in result.stdout


# ------------------------------------------------- the browsing layer (console profile)


def test_console_profile_starts_api_worker_and_web_over_this_project():
    """One `--profile console up` must give a browser the whole project.

    The three services build from the framework repository, and the API/worker run THIS
    project's entrypoints so its compile contract is registered — an API without it can serve
    sources but never a skill."""
    import yaml

    compose = yaml.safe_load(
        (ROOT / "scaffold" / "templates" / "docker-compose.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    for name in ("api", "worker", "web"):
        assert services[name]["profiles"] == ["console"], name
        assert "${PNEUMA_APP_FRAMEWORK_REPO" in services[name]["build"]["context"], name

    assert services["api"]["command"] == ["python", "/project/server.py"]
    assert services["worker"]["command"] == ["python", "/project/worker.py"]
    # The whole project is mounted: server.py, app.py, engine/ and data/ are all one unit.
    for name in ("api", "worker"):
        assert services[name]["volumes"] == ["./:/project"]
        env = services[name]["environment"]
        assert env["PNEUMA_KNOWLEDGE_ENGINE_DIR"] == "/project/engine"
        assert env["PNEUMA_KNOWLEDGE_CANONICAL_ROOT"] == "/project/data/canonical"

    # The web image is the framework's shared compose asset, on its own probed port, and it
    # waits for a healthy API (nginx proxies /v1 to it).
    web = services["web"]
    assert web["build"]["dockerfile"] == "docker/compose-web.Dockerfile"
    assert (ROOT / "docker" / "compose-web.Dockerfile").is_file()
    assert (ROOT / "docker" / "nginx.compose.conf").is_file()
    assert web["ports"] == ["127.0.0.1:${PNEUMA_APP_WEB_PORT:-18081}:80"]
    assert web["depends_on"] == {"api": {"condition": "service_healthy"}}


def test_the_compose_web_image_talks_to_the_real_engine_routes():
    """The console UI defaults to mock fixtures so it could be built before the API existed.
    A project image always has the API beside it, so its build states the real routes."""
    dockerfile = (ROOT / "docker" / "compose-web.Dockerfile").read_text(encoding="utf-8")
    assert "ARG VITE_ENGINE_FIXTURES=false" in dockerfile
    assert "docker/nginx.compose.conf" in dockerfile
    nginx = (ROOT / "docker" / "nginx.compose.conf").read_text(encoding="utf-8")
    # The upstream is a VARIABLE on purpose: a literal hostname is resolved once at
    # startup and goes stale when the api container is recreated (502s until restart).
    assert "set $api_upstream http://api:8080" in nginx
    assert "proxy_pass $api_upstream" in nginx
    assert "resolver 127.0.0.11" in nginx
    # index.html must not be cached: the SPA navigates by hash and would otherwise keep
    # running a stale bundle in a long-lived tab.
    assert 'location = /index.html' in nginx and 'Cache-Control "no-cache"' in nginx


def test_keyless_means_model_free_deterministic_and_stated_in_the_environment():
    """No key is a first-class state: nothing may call a model, embeddings are deterministic,
    and the values are stated in the ENVIRONMENT so the engine file keeps saying what this
    project would use with a key (env outranks the engine file by framework design)."""
    env = {"OPENROUTER_API_KEY": ""}
    notes = app.keyless_env(env)
    assert notes, "a keyless run must say so"
    assert env["PNEUMA_KNOWLEDGE_EMBEDDING_MODEL"] == app.KEYLESS_EMBEDDING
    # Chunking is deliberately NOT env-pinned: the framework's L2 dispatch degrades
    # semantic mechanically when no compile model resolves, so the engine file stays
    # the console-visible truth.
    assert "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY" not in env
    # Chat-model roles are deliberately NOT blanked: dispatch-level keyless handling
    # (usable_model_name) keeps the engine file the console-visible truth.
    assert not any(k.startswith("PNEUMA_KNOWLEDGE_LLM_MODEL") for k in env)

    # A collection built with another dimension can say so.
    env = {"OPENROUTER_API_KEY": "", "PNEUMA_APP_KEYLESS_EMBEDDING": "fake:3072"}
    app.keyless_env(env)
    assert env["PNEUMA_KNOWLEDGE_EMBEDDING_MODEL"] == "fake:3072"

    # With a key it is a no-op: the engine's own models are used, untouched.
    env = {"OPENROUTER_API_KEY": "sk-or-test-not-a-real-key"}
    assert app.keyless_env(env) == []
    assert env == {"OPENROUTER_API_KEY": "sk-or-test-not-a-real-key"}


def test_restore_says_so_when_the_project_ships_no_prebuilt_library(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(app, "PREBUILT_DIR", tmp_path / "prebuilt")
    assert app.cmd_restore(None) == 1
    assert "no prebuilt library" in capsys.readouterr().err


def _run_preflight(cwd: Path, extra_env: dict[str, str]) -> "subprocess.CompletedProcess":
    import os
    import subprocess

    env = {k: v for k, v in os.environ.items() if k != "PNEUMA_APP_FRAMEWORK_REPO"}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, str(cwd / "app.py"), "preflight"],
        capture_output=True,
        text=True,
        env=env,
        cwd=cwd,
    )


def test_preflight_catches_project_generated_outside_the_repo(tmp_path):
    import shutil

    copy = tmp_path / "my-knowledge"
    copy.mkdir()
    shutil.copy(APP_PATH, copy / "app.py")

    # Outside the repo, no PNEUMA_APP_FRAMEWORK_REPO → refuse up front, friendly message.
    result = _run_preflight(copy, {})
    assert result.returncode == 1
    assert "PNEUMA_APP_FRAMEWORK_REPO" in result.stderr

    # Pointing the variable at the framework repo satisfies the check.
    result = _run_preflight(copy, {"PNEUMA_APP_FRAMEWORK_REPO": str(ROOT)})
    assert result.returncode == 0

    # Inside the repo the parent-probe finds the framework without configuration.
    result = _run_preflight(ROOT / "scaffold" / "templates", {})
    assert result.returncode == 0


# ------------------------------------------------------------------- the engine directory


ENGINE_FILES = {
    "engine.yaml": 'compile: openrouter:openai/x\nrecall: openrouter:openai/x\ndeep: ""\nembedding: openrouter:openai/y\n',
    "intake/intake.yaml": "chunk_strategy: sentence\n",
    "compile/challenge.yaml": "enabled: true\nmax_rounds: 3\nmax_questions: 6\ncompensate: true\n",
    "evolve/evolve.yaml": "auto_trigger: false\ntrigger_topic_docs: 5\ntrigger_new_claims: 30\ndraft_ttl_hours: 24\n",
    "recall/recall.yaml": 'answer_style: concise\nclaim_cap: 80\nwindow_cap: 8\nplan_queries: 2\nrerank_model: ""\nrerank_candidates: 120\n',
    "persona/profile.yaml": 'display_name: "T"\n',
}


def _engine(monkeypatch, tmp_path, files: dict[str, str] | None = None) -> Path:
    """A generated project's engine directory, pointed at by the driver under test.

    In a real project `engine/` sits beside app.py; loaded from `templates/` there is none,
    so one is materialized here and the module's paths are redirected at it.
    """
    engine = tmp_path / "engine"
    for rel, text in (ENGINE_FILES if files is None else files).items():
        path = engine / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(app, "ENGINE_DIR", engine)
    monkeypatch.setattr(app, "PROFILE_PATH", engine / "persona" / "profile.yaml")
    monkeypatch.setattr(app, "CONTRACT_PATH", engine / "compile" / "contract.md")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    for name in (
        "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",
        "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL",
        "PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE",
        "PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP",
        "PNEUMA_KNOWLEDGE_PROMPT_LANGUAGE",
    ):
        monkeypatch.delenv(name, raising=False)
    return engine


def test_driver_addresses_the_contract_and_profile_inside_the_engine():
    assert app.CONTRACT_PATH == app.ENGINE_DIR / "compile" / "contract.md"
    assert app.PROFILE_PATH == app.ENGINE_DIR / "persona" / "profile.yaml"
    assert app.ENGINE_DIR == app.PROJECT_ROOT / "engine"


def test_build_settings_resolves_strategy_from_the_engine_directory(monkeypatch, tmp_path):
    _engine(monkeypatch, tmp_path)
    settings = app.build_settings()
    assert settings.engine_dir == str(tmp_path / "engine")
    assert settings.chunk_strategy == "sentence"
    assert settings.recall_answer_style == "concise"
    assert settings.recall_claim_cap == 80
    assert settings.recall_plan_queries == 2
    assert settings.challenge_enabled is True
    assert settings.challenge_max_rounds == 3
    assert settings.evolve_auto_trigger is False
    assert settings.llm_model_compile == "openrouter:openai/x"
    assert settings.embedding_model == "openrouter:openai/y"
    # `deep` empty in the engine file means "answer deep questions with the recall model".
    assert settings.llm_model_deep == "openrouter:openai/x"


def test_the_environment_still_outranks_the_engine_file_in_the_driver(monkeypatch, tmp_path):
    """The precedence rule is the framework's, and the driver uses the framework's resolver
    rather than a second reading — so a one-off experiment works the same way everywhere."""
    _engine(monkeypatch, tmp_path)
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_RECALL_CLAIM_CAP", "128")
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_CHUNK_STRATEGY", "semantic")
    settings = app.build_settings()
    assert settings.recall_claim_cap == 128
    assert settings.chunk_strategy == "semantic"
    assert settings.recall_answer_style == "concise"  # untouched by the environment


def test_missing_models_name_the_engine_file_not_the_env(monkeypatch, tmp_path):
    files = dict(ENGINE_FILES)
    files["engine.yaml"] = 'compile: ""\nrecall: ""\nembedding: ""\n'
    _engine(monkeypatch, tmp_path, files)
    with pytest.raises(SystemExit) as exc:
        app.require_models()
    message = str(exc.value)
    assert "engine.yaml: compile" in message
    assert "engine/engine.yaml" in message


def test_prompt_overlays_reach_the_framework_catalog(monkeypatch, tmp_path):
    from pneuma_knowledge_core.prompts import catalog, reset_prompt_overrides

    key = "compile.challenge.questions_system"
    files = dict(ENGINE_FILES)
    files["prompts/overlays.yaml"] = f'overlays:\n  {key}: "ask the hard ones"\n'
    _engine(monkeypatch, tmp_path, files)
    try:
        assert app.apply_prompt_overlays() == 1
        assert catalog()[key] == "ask the hard ones"
    finally:
        # The catalog is process-global; restore it so no later test inherits the overlay.
        reset_prompt_overrides()


def test_the_language_pack_is_the_framework_text_and_the_project_overrides_it(
    monkeypatch, tmp_path
):
    """Two layers in one call, in this order. The project's own clause has to survive the
    pack — a pack applied afterwards would take it back, silently, in the layer nobody
    re-reads."""
    from pneuma_knowledge_core.prompts import (
        catalog,
        chinese_overlay,
        reset_prompt_overrides,
    )

    key = "compile.challenge.questions_system"
    files = dict(ENGINE_FILES)
    files["prompts/overlays.yaml"] = (
        f'language: zh\noverlays:\n  {key}: "ask the hard ones"\n'
    )
    _engine(monkeypatch, tmp_path, files)
    try:
        assert app.apply_prompt_overlays() == 1
        effective = catalog()
        assert effective[key] == "ask the hard ones"
        assert effective["compile.rules_header"] == chinese_overlay()["compile.rules_header"]
    finally:
        reset_prompt_overrides()


def test_the_environment_can_pin_the_prompt_language_for_one_run(monkeypatch, tmp_path):
    from pneuma_knowledge_core.prompts import (
        catalog,
        default_catalog,
        reset_prompt_overrides,
    )

    files = dict(ENGINE_FILES)
    files["prompts/overlays.yaml"] = "language: zh\noverlays: {}\n"
    _engine(monkeypatch, tmp_path, files)
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_PROMPT_LANGUAGE", "en")
    try:
        assert app.apply_prompt_overlays() == 0
        assert catalog()["compile.rules_header"] == default_catalog()["compile.rules_header"]
    finally:
        reset_prompt_overrides()


def test_an_unknown_overlay_key_is_refused_rather_than_ignored(monkeypatch, tmp_path):
    files = dict(ENGINE_FILES)
    files["prompts/overlays.yaml"] = 'overlays:\n  not.a.real.key: "x"\n'
    _engine(monkeypatch, tmp_path, files)
    with pytest.raises(ValueError, match="unknown prompt key"):
        app.apply_prompt_overlays()


def test_build_settings_carries_the_contract_version(monkeypatch, tmp_path):
    """Job kinds beyond `compile` (groom/evolve/challenge) resolve their skill from
    settings.user_schema_base_version — an empty version bricks the first groom job.
    Found by the clean-room example build: a document crossed the rollover threshold
    and the groom job died on `no skill base registered for an empty version string`."""
    _engine(monkeypatch, tmp_path)
    settings = app.build_settings(base_version="app-v7")
    assert settings.user_schema_base_version == "app-v7"
    # And the default stays deliberately empty: compile passes its skill explicitly,
    # so a version only matters when the caller registered one.
    assert app.build_settings().user_schema_base_version == ""


async def _run_step(monkeypatch, *, drafts, enqueue_codes, policy="adopt-clean"):
    """Drive _evolve_step against a scripted draft/enqueue sequence; returns
    (exit_code, enqueue_calls). `drafts` is what successive pending-draft checks see."""
    draft_seq = list(drafts)
    codes = list(enqueue_codes)
    calls: list[tuple[str, dict]] = []

    async def fake_pending():
        return draft_seq.pop(0) if draft_seq else None

    async def fake_enqueue(kind, payload):
        calls.append((kind, payload))
        return codes.pop(0) if codes else 0

    monkeypatch.setattr(app, "_evolve_pending_draft", fake_pending)
    monkeypatch.setattr(app, "_evolve_enqueue", fake_enqueue)
    return await app._evolve_step(policy), calls


async def test_evolve_step_disposes_a_stuck_pending_draft_instead_of_hammering_run(monkeypatch):
    """The observed live failure: a retry loop calling `evolve run` eight times against
    the same pending draft. `step` adopts it and never touches `run`."""
    code, calls = await _run_step(
        monkeypatch, drafts=["t-1", None], enqueue_codes=[0]
    )
    assert code == 0
    assert calls == [("evolve_adopt", {"task_id": "t-1"})]


async def test_evolve_step_runs_then_disposes_the_new_draft(monkeypatch):
    code, calls = await _run_step(
        monkeypatch, drafts=[None, "t-2", None], enqueue_codes=[0, 0]
    )
    assert code == 0
    assert calls == [("evolve", {}), ("evolve_adopt", {"task_id": "t-2"})]


async def test_evolve_step_reports_nothing_to_do_and_keep_policy(monkeypatch):
    code, calls = await _run_step(monkeypatch, drafts=[None, None], enqueue_codes=[0])
    assert code == 0 and calls == [("evolve", {})]

    code, calls = await _run_step(monkeypatch, drafts=["t-3"], enqueue_codes=[], policy="keep")
    assert code == 2 and calls == []


async def test_evolve_step_surfaces_a_failed_adopt_instead_of_claiming_progress(monkeypatch):
    # Adopt job ran (code 0) but the draft is still pending afterwards → exit 2.
    code, calls = await _run_step(
        monkeypatch, drafts=["t-4", "t-4"], enqueue_codes=[0]
    )
    assert code == 2
    assert calls == [("evolve_adopt", {"task_id": "t-4"})]


def test_compile_drain_heals_orphaned_claims_first():
    """An interrupted `./app.py compile` leaves its job 'claimed'; claim_next then skips
    that user's queue forever. For a scaffold project this in-process drain is the ONLY
    drain path (no worker restart to self-heal), so it must requeue orphans before
    draining — without this, one Ctrl-C mid-compile bricks the project permanently."""
    src = APP_PATH.read_text(encoding="utf-8")
    compile_body = src.split("async def _compile(")[1].split("\nasync def ")[0]
    heal = compile_body.index("requeue_orphaned_jobs")
    drain = compile_body.index("_drain_with_progress")
    assert heal < drain


def test_gate_retry_carries_the_per_source_treatments():
    """The one retry round must not overrule the intake decision.

    A compile job's payload can carry `treatments` — per source, whether it is digested in
    full or only distilled. Re-enqueuing with source_ids alone drops that map, so the retry
    compiles at the plan's default and a distil-only source gets fully digested. The retry
    is a second attempt at the SAME job, not a different one."""
    src = APP_PATH.read_text(encoding="utf-8")
    body = src.split("async def _compile(")[1].split("\nasync def ")[0]
    retry = body[body.index("rejected by the gate") : body.index("_drain_with_progress", body.index("rejected by the gate"))]
    assert "treatments" in retry, "the retry drops the per-source treatments map"
    assert 'ctx.store.enqueue(uid, "compile", {"source_ids": sources})' not in retry
