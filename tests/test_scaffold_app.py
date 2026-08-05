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

    for name in ("app.py", "start.sh", "docker-compose.yml", "gitignore"):
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


def test_build_settings_carries_the_contract_version(monkeypatch, tmp_path):
    """Job kinds beyond `compile` (groom/evolve/challenge) resolve their skill from
    settings.user_schema_base_version — an empty version bricks the first groom job.
    Found by the clean-room example build: a document crossed the rollover threshold
    and the groom job died on `no skill base registered for an empty version string`."""
    # In a generated project profile.yaml sits beside app.py; under templates/ it is a
    # language-variant template, so materialize one for the settings assembly to read.
    profile = tmp_path / "profile.yaml"
    profile.write_text('display_name: "T"\n', encoding="utf-8")
    monkeypatch.setattr(app, "PROFILE_PATH", profile)
    monkeypatch.setenv("PNEUMA_APP_COMPILE_MODEL", "openrouter:openai/x")
    monkeypatch.setenv("PNEUMA_APP_RECALL_MODEL", "openrouter:openai/x")
    monkeypatch.setenv("PNEUMA_APP_EMBEDDING_MODEL", "openrouter:openai/y")
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    settings = app.build_settings(base_version="app-v7")
    assert settings.user_schema_base_version == "app-v7"
    # And the default stays deliberately empty: compile passes its skill explicitly,
    # so a version only matters when the caller registered one.
    assert app.build_settings().user_schema_base_version == ""
