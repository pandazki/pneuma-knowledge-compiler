"""The Steward's skill package: a rendering, and a rendering that can be checked.

Every test here is one half of ruling 4 — the skill is a rendering, not a second text — held
mechanically:

* the same inputs render the same bytes, so a hash in a commit trailer identifies something;
* the prose comes from the prompt catalog, so the language pack and a deployment's overlay
  reach the agent's own instructions;
* the command reference comes from the live argparse tree, so a component's tools are in it
  because they are in the CLI;
* the gate reference comes from the gate's own texts, so no refusal is described twice;
* `compile-instructions.md` is byte-for-byte what `pkc draft open` prints, so the reference
  and the round cannot disagree;
* and the SKILL.md carries no rule a command does not enforce.

Keyless: no middleware, no model, no network.
"""

from __future__ import annotations

import io
import json
import re

import pytest
from langchain_core.tools import StructuredTool
from pneuma_knowledge_core.compile.gate import VIOLATION_KINDS
from pneuma_knowledge_core.compile.runner import (
    STEWARD_SKILL_HASH_ENV,
    with_skill_trailer,
)
from pneuma_knowledge_core.components import (
    IndexComponent,
    register_component,
    reset_components,
)
from pneuma_knowledge_core.prompts import (
    chinese_overlay,
    default_catalog,
    override_prompts,
    prompt,
    reset_prompt_overrides,
)
from pneuma_knowledge_core.skill import load_skill_base, render_system_contract
from pneuma_knowledge_core.skill.version import SkillVersion
from pneuma_knowledge_service.cli import build_parser
from pneuma_knowledge_service.cli.draft import EXIT_BUDGET, EXIT_GATE, EXIT_NOTHING, EXIT_REFUSED
from pneuma_knowledge_service.coding_agent import (
    BACKENDS,
    BLOCK_END,
    BLOCK_START,
    install_skill_package,
    render_skill_package,
    verify_skill_package,
)
from pneuma_knowledge_service.coding_agent.install import (
    VERSION_FILE,
    router_block,
    splice_block,
)
from pydantic import BaseModel, Field

from test_draft_cli import SKILL, harness, source

CODEX = BACKENDS["codex"]
CLAUDE = BACKENDS["claude-code"]


def render(backend=CODEX, *, skill=None, components=(), language="en", entry=""):
    return render_skill_package(
        skill=skill or SKILL,
        owner=None,
        time_zone=None,
        components=components,
        backend=backend,
        cli_parser=build_parser(),
        language=language,
        entry=entry,
    )


def text(package, path: str) -> str:
    return package.files[path].decode("utf-8")


# ────────────────────────────────────────────────────────────────────────── determinism


def test_two_renderings_of_the_same_deployment_are_the_same_bytes():
    """The whole point of a hash in a commit trailer: it identifies a text, not a run."""
    first, second = render(), render()
    assert first.files == second.files
    assert first.sha256 == second.sha256
    # And the two backends differ, because their layouts do — the hash is per (inputs ×
    # backend), which is why `skill-version.json` records which one it was rendered for.
    assert render(CLAUDE).sha256 != first.sha256


def test_nothing_in_the_package_reads_a_clock_or_a_directory():
    """A rendered package holds no timestamp; the one wall-clock fact lives beside it."""
    for body in render().files.values():
        assert b"rendered_at" not in body


# ────────────────────────────────────────────────────────────── the prose is the catalog


def test_the_skill_md_is_exactly_the_catalog_surfaces_and_nothing_else():
    """Assembled here from the same keys, so a sentence written into the generator instead of
    the catalog fails rather than shipping."""
    root = CODEX.skill_dir
    expected = "\n\n".join(
        section.strip("\n")
        for section in (
            prompt("steward.skill.who", pkc=f"{root}/scripts/pkc"),
            prompt("steward.skill.consume", consume=f"{root}/references/consume.md"),
            prompt("steward.skill.episodes"),
            prompt("steward.skill.round"),
            prompt("steward.skill.evolve"),
            prompt("steward.skill.door", gate=f"{root}/references/gate.md"),
            prompt(
                "steward.skill.postures",
                session=CODEX.owner_session_command,
                once=CODEX.owner_exec_command,
            ),
            prompt("steward.skill.owner_speech"),
            prompt("steward.skill.archive"),
            prompt("steward.skill.cannot"),
            prompt(
                "steward.skill.references",
                contract=f"{root}/references/contract.md",
                instructions=f"{root}/references/compile-instructions.md",
                consume=f"{root}/references/consume.md",
                cli=f"{root}/references/cli.md",
                gate=f"{root}/references/gate.md",
            ),
        )
    )
    body = text(render(), "SKILL.md")
    assert body.startswith("---\nname: pkc-steward\ndescription: ")
    assert body.endswith(expected + "\n")


def test_the_language_pack_changes_the_skill_and_changes_only_the_catalog_prose():
    english = render()
    try:
        override_prompts(chinese_overlay())
        chinese = render(language="zh")
    finally:
        reset_prompt_overrides()

    assert chinese.sha256 != english.sha256
    # Not merely different — different in the way a language pack makes things different:
    # the SKILL.md is assembled from the SAME keys, resolved through the pack.
    assert text(chinese, "SKILL.md") != text(english, "SKILL.md")
    assert "pkc draft finish" in text(chinese, "SKILL.md")  # the command names stay English
    # The paths a harness opens are identity, not prose: they must survive translation.
    for path in sorted(english.files):
        assert path in chinese.files


def test_every_steward_key_has_a_chinese_translation():
    """The pin the language pack already carries, said about these keys specifically."""
    pack = chinese_overlay()
    for key in default_catalog():
        if key.startswith("steward."):
            assert key in pack, key


@pytest.mark.parametrize("language", ["en", "zh"])
def test_outline_and_glance_help_and_the_three_reading_moments(language, capsys):
    try:
        if language == "zh":
            override_prompts(chinese_overlay())
        package = render(language=language)
        reference = text(package, "references/cli.md")
        parser = build_parser()
        parent_help = " ".join(parser.format_help().split())
        for command in ("outline", "glance"):
            expected = prompt(f"steward.cli.{command}")
            assert expected in reference
            assert "".join(expected.split()) in "".join(parent_help.split())
            with pytest.raises(SystemExit) as caught:
                parser.parse_args([command, "-h"])
            assert caught.value.code == 0
            assert "".join(expected.split()) in "".join(capsys.readouterr().out.split())
        assert reference.index("`pkc outline`") < reference.index("`pkc glance`")
        assert "--definitions" in reference and "--family" in reference

        consume = text(package, "references/consume.md")
        journey = text(package, "SKILL.md")
        assert prompt("steward.consume.when_to_use").strip() in consume
        # The table is keyed by the SHAPE of the question, not by a fixed sequence of moments.
        moments = ("Shape of the question", "Spans several pages", "After `pkc draft finish`") if language == "en" else (
            "\u95ee\u9898\u7684\u5f62\u72b6", "\u8de8\u591a\u4e2a\u9875\u9762", "`pkc draft finish` \u4e4b\u540e",
        )
        for moment in moments:
            assert moment in consume
        for command in (
            "pkc outline", "pkc canonical read <path>", "pkc recall <q> --evidence",
            "pkc search <q> --lexical", "pkc source fetch <sid> \u00b6a-b",
            "pkc glance", "pkc outline --family <template>",
        ):
            assert command in consume and command in journey
        assert "--page N" in consume and "--all-pages" in consume
        assert "top-K" in consume and "top-K" in journey
        round_text = prompt("steward.skill.round")
        assert round_text.index("pkc outline") < round_text.index("pkc draft open")
        assert round_text.index("pkc outline --family") > round_text.index("pkc draft finish --brief")
        assert round_text.strip() in journey
        assert "start here to choose subjects" not in consume
    finally:
        reset_prompt_overrides()


def test_map_help_matches_the_owners_exact_contract():
    assert prompt("steward.cli.outline") == (
        "The complete map: every page under its family, one line each, never cut. "
        "The first command of a session and the check after a compile. "
        "For a budgeted map that picks the top pages, see `glance`."
    )
    assert prompt("steward.cli.glance") == (
        "The budgeted map the answering lanes open with: the top pages per family within "
        "a character budget — it may drop pages and says how many. Use it to choose "
        "subjects when the outline is long; for the whole library, `outline`."
    )


@pytest.mark.parametrize("language", ["en", "zh"])
def test_map_wording_changes_package_hash_without_changing_the_compile_system(language):
    try:
        if language == "zh":
            override_prompts(chinese_overlay())
        package = render(language=language)
        for key in ("steward.cli.outline", "steward.cli.glance", "steward.consume.when_to_use"):
            override_prompts({key: "Synthetic replacement map wording."})
            changed = render(language=language)
            assert changed.sha256 != package.sha256
            assert changed.files["references/compile-instructions.md"] == package.files["references/compile-instructions.md"]
            package = changed
    finally:
        reset_prompt_overrides()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_episodes_journey_and_verbs_are_rendered_from_their_sources(language):
    try:
        if language == "zh":
            override_prompts(chinese_overlay())
        package = render(language=language)
        skill = text(package, "SKILL.md")
        assert prompt("steward.skill.episodes").strip() in skill
        assert skill.index(prompt("steward.skill.episodes").strip()) < skill.index(prompt("steward.skill.round").strip())
        cli = text(package, "references/cli.md")
        for verb in ("open", "status", "propose", "finish", "abandon"):
            assert f"pkc index episodes {verb}" in cli
        assert len(re.findall(r"\bchallenge\b", skill, flags=re.IGNORECASE)) == 1
    finally:
        reset_prompt_overrides()


@pytest.mark.parametrize("language", ["en", "zh"])
def test_consume_renders_the_resolved_families_and_owner_voice(language):
    skill = SkillVersion.from_parts(
        skill_id="synthetic-projects",
        version="v-test",
        instructions="Project subjects and the Owner's stated views.",
        path_templates=[
            "projects/{slug}/overview.md",
            "projects/{slug}/decisions/{slug}.md",
            {"path": "owner/views/{slug}.md", "owner_voice": True},
            "memory/people/{slug}.md",
        ],
    )
    try:
        if language == "zh":
            override_prompts(chinese_overlay())
        package = render(skill=skill, language=language)
        reference = text(package, "references/consume.md")
        expected_families = "\n".join(
            f"- `{template}`"
            + (prompt("steward.consume.owner_voice") if template in skill.owner_voice_templates else "")
            for template in skill.path_templates
        )
        assert expected_families in reference
        assert reference.count("`owner_voice`") == 1
        assert "synthetic-projects" in reference and "v-test" in reference
        assert "pkc recall <q> --evidence" in reference
        assert "pkc consult answer <handoff_id> --text-file <f>" in reference
        assert f"{CODEX.skill_dir}/references/consume.md" in text(package, "SKILL.md")
        assert reference == text(render(skill=skill, language=language), "references/consume.md")

        changed = SkillVersion.from_parts(
            skill_id=skill.skill_id,
            version=skill.version,
            instructions=skill.instructions,
            path_templates=[*skill.path_templates, "projects/{slug}/evolution.md"],
            owner_voice_templates=skill.owner_voice_templates,
        )
        assert "- `projects/{slug}/evolution.md`" in text(render(skill=changed), "references/consume.md")
        assert render(skill=changed).sha256 != package.sha256

        unmarked = SkillVersion.from_parts(
            skill_id=skill.skill_id, version=skill.version, instructions=skill.instructions,
            path_templates=skill.path_templates,
        )
        assert "`owner_voice`" not in text(render(skill=unmarked), "references/consume.md")
        assert render(skill=unmarked).sha256 != package.sha256
    finally:
        reset_prompt_overrides()


def test_consume_catalog_changes_are_hashed_without_changing_the_system_message():
    before = render()
    system = render_system_contract(SKILL)
    try:
        override_prompts({"steward.consume.library": "A synthetic reading reference."})
        after = render()
        assert text(after, "references/consume.md").startswith("A synthetic reading reference.")
        assert after.sha256 != before.sha256
        assert render_system_contract(SKILL) == system
        assert after.files["references/compile-instructions.md"] == before.files["references/compile-instructions.md"]
    finally:
        reset_prompt_overrides()


# ───────────────────────────────────────────────────────────────────── the CLI reference


def test_the_cli_reference_names_every_command_in_the_tree():
    reference = text(render(), "references/cli.md")
    import argparse

    def subparsers(parser):
        return next(
            (a for a in parser._actions if isinstance(a, argparse._SubParsersAction)),  # noqa: SLF001
            None,
        )

    top = subparsers(build_parser())
    for group_name, group in top.choices.items():
        assert f"`pkc {group_name}`" in reference, group_name
        sub = subparsers(group)
        if sub is None:
            continue
        for command in sub.choices:
            assert f"`pkc {group_name} {command}`" in reference, f"{group_name} {command}"


def test_the_cli_reference_states_every_exit_code_the_draft_commands_use():
    reference = text(render(), "references/cli.md")
    for code in (0, EXIT_NOTHING, EXIT_REFUSED, EXIT_BUDGET, EXIT_GATE):
        assert f"- `{code}` — " in reference


class _NoteArgs(BaseModel):
    subject: str = Field(description="who the note is about")


class _FakeComponent:
    """The smallest thing that satisfies the component protocol's tool seam."""

    name = "notes"

    def compile_tools(self, draft, *, sources=()):  # noqa: ANN001
        return [
            StructuredTool.from_function(
                func=lambda subject: subject,
                name="note_subject",
                description="record who a claim is about",
                args_schema=_NoteArgs,
            )
        ]


def test_a_registered_component_puts_its_compile_tool_in_the_reference():
    """The component seam is not special-cased anywhere in the generator: the tool is in the
    reference because `build_parser` put it in the tree."""
    reset_components()
    try:
        register_component(_FakeComponent())
        from pneuma_knowledge_service.cli.draft import component_tool_specs

        parser = build_parser(component_tool_specs())
        package = render_skill_package(
            skill=SKILL,
            owner=None,
            time_zone=None,
            components=[_FakeComponent()],
            backend=CODEX,
            cli_parser=parser,
            language="en",
        )
    finally:
        reset_components()
    reference = text(package, "references/cli.md")
    assert "`pkc draft note-subject`" in reference
    assert "record who a claim is about" in reference
    assert "`--subject <subject>`" in reference
    assert "`notes`" in text(package, "references/gate.md")


# ──────────────────────────────────────────────────────────────────── the gate reference


def test_the_gate_reference_has_a_section_for_every_violation_kind():
    reference = text(render(), "references/gate.md")
    for kind, _keys in VIOLATION_KINDS:
        assert f"## `{kind}`" in reference, kind


def test_the_gate_reference_holds_every_compile_gate_text_the_catalog_declares():
    """The mechanical pin: a gate text added to the catalog without an entry in
    `VIOLATION_KINDS` fails here rather than going undescribed.

    The excluded prefixes are the OTHER channels' gates — evolve, groom, and the archive
    record — each judging a draft no compile round writes. A Steward cannot earn one of
    their findings (the record channel has no model in it at all), so describing them in the
    reference an agent reads before it writes would name failures it cannot cause.
    """
    declared = {key for _kind, keys in VIOLATION_KINDS for key in keys}
    compile_gate_keys = {
        key
        for key in default_catalog()
        if key.startswith("gate.")
        and not key.startswith(("gate.evolve.", "gate.groom.", "gate.archive_record."))
        and key not in ("gate.feedback_header", "gate.previous_round_cut_off")
    }
    assert compile_gate_keys - declared == set()


# ────────────────────────────────────────────────────────── the contract, byte for byte


def test_the_compile_instructions_are_what_pkc_draft_open_prints():
    """Same skill, same owner, same zone → the same system text in both places (I5)."""
    package = render()
    rendered = text(package, "references/compile-instructions.md")
    assert rendered.endswith(render_system_contract(SKILL, owner=None, time=None))
    assert text(package, "references/contract.md").endswith(
        SKILL.instructions.rstrip("\n") + "\n"
    )


async def test_the_reference_and_the_round_show_the_same_contract():
    h = await harness([source()])
    from pneuma_knowledge_service.cli import draft as draft_cmd

    assert await draft_cmd.cmd_open(h.rt, h.job_id) == 0
    printed = h.out()
    system_text = render_system_contract(SKILL, owner=None, time=None)
    assert printed.startswith(system_text + "\n\n")
    assert text(render(), "references/compile-instructions.md").endswith(system_text)


# ───────────────────────────────────────────────────── what the SKILL.md may not contain

#: Imperatives the project bans in model-facing prose: a "must" that no command enforces is
#: persuasion, and persuasion is the thing this design replaces with refusals.
BANNED = ("always", "never forget", "remember to", "make sure", "be sure to")


def test_the_skill_carries_no_imperative_the_door_does_not_enforce():
    body = text(render(), "SKILL.md")
    # A quoted refusal is the door's own words and may say anything the door says; it is
    # marked as a quotation, which is what makes this exclusion mechanical rather than a
    # judgement call about which sentence "counts".
    prose = "\n".join(
        line for line in body.splitlines() if not line.lstrip().startswith(">")
    )
    for phrase in BANNED:
        assert not re.search(re.escape(phrase), prose, re.IGNORECASE), phrase


def test_the_skill_states_the_stewards_first_question_and_the_command_that_answers_it():
    """The rule the acceptance run was missing, and the only kind of rule this skill carries:
    one that a command reports mechanically (`pkc profile show` says `placeholder`) and that a
    command records (`pkc profile set`)."""
    body = text(render(), "SKILL.md")
    assert "pkc profile show" in body
    assert "pkc profile set" in body
    # Retiring a page that turns out to be the owner is the archive's own procedure, said
    # where the archive is said.
    assert body.count("pkc profile set") >= 2


def test_the_language_pack_carries_the_profile_rule_too():
    """en/zh parity for the clauses added here: the same commands, in the other language."""
    try:
        override_prompts(chinese_overlay())
        chinese = text(render(language="zh"), "SKILL.md")
    finally:
        reset_prompt_overrides()
    assert "pkc profile show" in chinese
    assert "pkc profile set" in chinese


def test_the_skill_states_every_exit_code_the_door_answers_with():
    body = text(render(), "SKILL.md")
    for code in (0, EXIT_NOTHING, EXIT_REFUSED, EXIT_BUDGET, EXIT_GATE):
        assert f"`{code}`" in body


# ─────────────────────────────────────────────────────────────────────────────── install


def test_install_writes_each_backends_own_layout(tmp_path):
    for backend in (CODEX, CLAUDE):
        install_skill_package(tmp_path, backend, render(backend), "test")
        assert (tmp_path / backend.skill_dir / "SKILL.md").is_file()
        assert (tmp_path / backend.skill_dir / "references" / "cli.md").is_file()
        assert (tmp_path / backend.skill_dir / "scripts" / "pkc").is_file()
        assert (tmp_path / backend.skills_dir / VERSION_FILE).is_file()
        assert (tmp_path / backend.instructions_file).is_file()
    assert (tmp_path / ".claude" / "workflows" / "compile.js").is_file()
    assert not (tmp_path / ".agents" / "workflows").exists()
    assert "workflows/compile.js" not in render(CODEX).files


def test_the_shim_is_executable_and_exports_the_installed_hash(tmp_path):
    package = render()
    install_skill_package(tmp_path, CODEX, package, "test")
    shim = tmp_path / CODEX.skill_dir / "scripts" / "pkc"
    assert shim.stat().st_mode & 0o111
    body = shim.read_text(encoding="utf-8")
    assert STEWARD_SKILL_HASH_ENV in body
    recorded = json.loads(
        (tmp_path / CODEX.skills_dir / VERSION_FILE).read_text(encoding="utf-8")
    )
    assert recorded["sha256"] == package.sha256
    assert recorded["backend"] == "codex"
    assert recorded["framework_version"] == "test"
    assert "rendered_at" in recorded


def test_reinstalling_leaves_the_same_files_and_removes_what_is_no_longer_rendered(tmp_path):
    package = render()
    first = install_skill_package(tmp_path, CODEX, package, "test")
    stale = tmp_path / CODEX.skill_dir / "references" / "gone.md"
    stale.write_text("from an older version", encoding="utf-8")
    second = install_skill_package(tmp_path, CODEX, package, "test")
    assert first == second
    assert not stale.exists()
    assert verify_skill_package(tmp_path, CODEX, package) == []


def test_the_owners_own_prose_outside_the_markers_survives_every_install(tmp_path):
    instructions = tmp_path / CODEX.instructions_file
    instructions.write_text(
        "# My notes\n\nDo not touch this paragraph.\n", encoding="utf-8"
    )
    package = render()
    install_skill_package(tmp_path, CODEX, package, "test")
    install_skill_package(tmp_path, CODEX, package, "test")
    body = instructions.read_text(encoding="utf-8")
    assert body.startswith("# My notes\n\nDo not touch this paragraph.\n")
    assert body.count(BLOCK_START) == 1
    assert body.count(BLOCK_END) == 1
    assert router_block(CODEX) in body


def test_a_block_written_by_hand_twice_converges_on_one():
    doubled = f"a\n\n{router_block(CODEX)}\n\nb\n\n{router_block(CODEX)}\n"
    once = splice_block(doubled, router_block(CODEX))
    assert once.count(BLOCK_START) == 1
    assert "a" in once and "b" in once


# ──────────────────────────────────────────────────────────────────────────────── verify


def test_verify_is_silent_when_fresh_and_names_what_drifted(tmp_path):
    package = render()
    install_skill_package(tmp_path, CODEX, package, "test")
    assert verify_skill_package(tmp_path, CODEX, package) == []

    edited = tmp_path / CODEX.skill_dir / "references" / "cli.md"
    edited.write_text(edited.read_text(encoding="utf-8") + "\nhand-written\n", encoding="utf-8")
    assert verify_skill_package(tmp_path, CODEX, package) == [
        f"{CODEX.skill_dir}/references/cli.md"
    ]


def test_verify_reports_a_missing_install_and_a_removed_router_block(tmp_path):
    package = render()
    assert verify_skill_package(tmp_path, CODEX, package)
    install_skill_package(tmp_path, CODEX, package, "test")
    (tmp_path / CODEX.instructions_file).write_text("nothing here\n", encoding="utf-8")
    assert CODEX.instructions_file in verify_skill_package(tmp_path, CODEX, package)


def test_a_contract_change_is_drift(tmp_path):
    package = render()
    install_skill_package(tmp_path, CODEX, package, "test")
    other = SKILL.model_copy(update={"instructions": SKILL.instructions + "\nOne more rule.\n"})
    drift = verify_skill_package(tmp_path, CODEX, render(skill=other))
    assert f"{CODEX.skill_dir}/references/contract.md" in drift


# ─────────────────────────────────────────────────────────────────────────────── trailer


def test_the_trailer_names_the_executors_skill_only_when_a_shim_started_it(monkeypatch):
    monkeypatch.delenv(STEWARD_SKILL_HASH_ENV, raising=False)
    without = with_skill_trailer("compile", SKILL)
    assert "Executor-Skill" not in without
    assert without.splitlines()[-3:] == [
        f"Skill-Version: {SKILL.version}",
        f"Skill-Id: {SKILL.skill_id}",
        f"Skill-Content-Hash: {SKILL.content_hash}",
    ]

    monkeypatch.setenv(STEWARD_SKILL_HASH_ENV, "deadbeef")
    with_hash = with_skill_trailer("compile", SKILL)
    assert with_hash == without + "\nExecutor-Skill: deadbeef"


def test_a_blank_hash_is_not_a_trailer_line(monkeypatch):
    monkeypatch.setenv(STEWARD_SKILL_HASH_ENV, "   ")
    assert "Executor-Skill" not in with_skill_trailer("compile", SKILL)


# ───────────────────────────────────────────────────────── re-install on an engine apply


def _settings(tmp_path, *, compile_spec: str):
    from pneuma_knowledge_service.settings import Settings

    return Settings(
        engine_dir=str(tmp_path / "engine"),
        llm_model_compile=compile_spec,
        user_schema_base_version=SKILL.version,
    )


async def test_a_model_executor_has_no_steward_to_re_teach(tmp_path):
    from pneuma_knowledge_service.coding_agent import refresh_skill_installs

    (tmp_path / "engine").mkdir()
    install_skill_package(tmp_path, CODEX, render(), "test")
    assert await refresh_skill_installs(_settings(tmp_path, compile_spec="scripted:x")) == []


async def test_an_apply_re_installs_only_the_backends_the_project_already_chose(tmp_path):
    from pneuma_knowledge_service.coding_agent import refresh_skill_installs

    (tmp_path / "engine").mkdir()
    settings = _settings(tmp_path, compile_spec="agent:codex")
    # Nothing installed yet: an apply must not decide, on its own, that this project wants a
    # coding agent's skill in it.
    assert await refresh_skill_installs(settings) == []

    install_skill_package(tmp_path, CODEX, render(), "test")
    written = await refresh_skill_installs(settings)
    assert f"{CODEX.skill_dir}/SKILL.md" in written
    assert not any(path.startswith(".claude") for path in written)

    # What it wrote is what THIS deployment renders — the same resolution `pkc skill verify`
    # performs, which is the whole point of the two going through one function.
    from pneuma_knowledge_service.coding_agent.deployment import (
        default_parser,
        packages,
        resolve_deployment,
    )

    deployment = await resolve_deployment(settings, user="", parser_for=default_parser)
    (_manifest, package), = packages(deployment, ["codex"])
    assert verify_skill_package(tmp_path, CODEX, package) == []


# ────────────────────────────────────────────────────────── one entry name for one door (S4)


def test_the_skill_names_the_projects_own_pkc_when_the_project_has_one(tmp_path):
    """`SKILL.md` said "run it as `<skills_dir>/scripts/pkc` — that path, spelled exactly"
    while the scaffold advertises `bin/pkc` and the generator prints it. Two names for one
    door; the project's own wins where it exists."""
    from pneuma_knowledge_service.coding_agent.deployment import packages
    from pneuma_knowledge_service.coding_agent.skillpack import project_entry

    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pkc").write_text("#!/bin/sh\n", encoding="utf-8")
    assert project_entry(tmp_path) == "bin/pkc"
    assert project_entry(tmp_path / "elsewhere") == ""
    assert project_entry(None) == ""

    with_entry = render(entry="bin/pkc")
    body = text(with_entry, "SKILL.md")
    assert "Run it as `bin/pkc`" in body
    assert f"{CODEX.skill_dir}/scripts/pkc" not in body
    # Still installed, and still what `bin/pkc` points at.
    assert "scripts/pkc" in with_entry.files


def test_without_a_project_entry_the_skills_own_shim_is_the_entry():
    body = text(render(), "SKILL.md")
    assert f"Run it as `{CODEX.skill_dir}/scripts/pkc`" in body
    assert "bin/pkc" not in body


def test_the_entry_is_part_of_the_hash_so_verify_can_see_it_change():
    assert render(entry="bin/pkc").sha256 != render().sha256


# ─────────────────────────────────────── the invocation a session here needs (S1) and uv (S2)


def test_the_skill_states_the_invocation_a_session_needs():
    """A bare `codex exec` runs read-only and networkless, so `pkc` cannot open the project's
    Postgres and the feature's headline experience does not work. Said in the skill, said in
    the router block, and said in the generated README (tests/test_scaffold_init.py)."""
    body = text(render(), "SKILL.md")
    assert CODEX.owner_session_command in body
    assert CODEX.owner_exec_command in body
    assert "--sandbox workspace-write" in body
    assert "sandbox_workspace_write.network_access=true" in body

    claude_body = text(render(CLAUDE), "SKILL.md")
    # Claude Code sandboxes nothing and asks instead: the interactive command is its own name.
    assert CLAUDE.owner_session_command == "claude"
    assert CLAUDE.owner_exec_command in claude_body
    assert "--sandbox" not in claude_body


def test_the_router_block_states_it_too():
    for manifest in (CODEX, CLAUDE):
        block = router_block(manifest)
        assert manifest.owner_session_command in block
        assert manifest.owner_exec_command in block


def test_the_shim_points_uv_at_a_cache_a_sandboxed_harness_can_write():
    """`uv run` needs a writable `~/.cache/uv`, which no sandboxed harness has: both
    acceptance sessions had to invent this variable before `pkc` would run at all."""
    shim = text(render(), "scripts/pkc")
    assert 'UV_CACHE_DIR="$project/.uv-cache"' in shim
    assert "export UV_CACHE_DIR" in shim
    # An Owner who set their own cache keeps it.
    assert 'if [ -z "${UV_CACHE_DIR:-}" ]; then' in shim
    # And it is set BEFORE the hand-off that needs it.
    assert shim.index("UV_CACHE_DIR") < shim.index("exec uv run")


# ──────────────────────────────────────── the same package, written out and installed nowhere
#
# `pkc skill render --out <dir>` is `install` without the install (single-machine-edition.md
# §4.9, §11 item 4). The tests below hold the one property that makes it that and not a
# second renderer: the bytes, and the recorded hash, are the install's.


def _installed_at(project, backend, rel: str):
    """Where `install` puts one package-relative path — the layout, stated from the manifest."""
    if rel.startswith("workflows/"):
        return project / backend.workflows_dir / rel[len("workflows/") :]
    return project / backend.skill_dir / rel


def _render_settings(tmp_path):
    (tmp_path / "engine").mkdir(exist_ok=True)
    return _settings(tmp_path, compile_spec="agent:codex")


async def _skill(settings, argv):
    """One `pkc skill …` invocation, through the parser and the dispatcher the CLI uses."""
    from pneuma_knowledge_service.cli.skill import dispatch_skill
    from pneuma_knowledge_service.coding_agent.deployment import default_parser

    args = build_parser().parse_args(["skill", *argv])
    stdout, stderr = io.StringIO(), io.StringIO()
    code = await dispatch_skill(
        settings, args, user="", parser_for=default_parser, out=stdout, err=stderr
    )
    return code, stdout.getvalue(), stderr.getvalue()


async def _render(settings, out_dir, *, backend_name="codex", language="", force=False):
    argv = ["render", "--out", str(out_dir), "--backend", backend_name, "--json"]
    if language:
        argv += ["--language", language]
    if force:
        argv.append("--force")
    return await _skill(settings, argv)


@pytest.mark.parametrize("backend_name", sorted(BACKENDS))
async def test_render_out_writes_byte_for_byte_what_install_writes_into_a_project(
    tmp_path, backend_name
):
    """The whole claim of the command: one rendering reaching two different disks."""
    from pneuma_knowledge_service.coding_agent.deployment import default_parser

    settings = _render_settings(tmp_path)
    manifest = BACKENDS[backend_name]
    project = tmp_path / "project"
    project.mkdir()
    out = tmp_path / "rendered"

    code, body, _err = await _skill(
        settings,
        ["install", "--project", str(project), "--backend", backend_name, "--json"],
    )
    assert code == 0
    installed = json.loads(body)[0]

    code, rendered_json, _ = await _render(settings, out, backend_name=backend_name)
    rendered = json.loads(rendered_json)
    assert code == 0
    assert rendered["sha256"] == installed["sha256"]

    # Every file of the package, on both disks, the same bytes.
    from pneuma_knowledge_service.coding_agent.deployment import packages, resolve_deployment

    deployment = await resolve_deployment(settings, user="", parser_for=default_parser)
    ((_m, package),) = packages(deployment, [backend_name])
    assert package.sha256 == installed["sha256"]
    for rel in sorted(package.files):
        assert (out / rel).read_bytes() == package.files[rel]
        assert _installed_at(project, manifest, rel).read_bytes() == package.files[rel]
    assert sorted(rendered["files"]) == sorted([*package.files, VERSION_FILE])

    # And `skill-version.json` records the same five facts, `rendered_at` excepted — the one
    # of them that moves between two renderings of one package.
    def record(path):
        body = json.loads(path.read_text(encoding="utf-8"))
        body.pop("rendered_at")
        return body

    assert record(out / VERSION_FILE) == record(project / manifest.skills_dir / VERSION_FILE)

    # Nothing was installed: no instructions file, and no harness directory.
    assert not (out / manifest.instructions_file).exists()
    assert not (out / manifest.skills_dir.split("/")[0]).exists()


async def test_a_rendered_package_names_its_own_shim_as_the_entry(tmp_path):
    """There is no project here, so there is no `bin/pkc` to name: the entry is the shim the
    package itself carries, which is what `packages(…)` renders when handed no project."""
    settings = _render_settings(tmp_path)
    # A `bin/pkc` sitting in the working directory must not reach the rendering — the command
    # takes no `--project` at all, and this is what that absence means.
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "pkc").write_text("#!/bin/sh\n", encoding="utf-8")

    out = tmp_path / "rendered"
    await _render(settings, out)
    body = (out / "SKILL.md").read_text(encoding="utf-8")
    assert f"Run it as `{CODEX.skill_dir}/scripts/pkc`" in body
    assert "bin/pkc" not in body


async def test_the_rendered_shim_is_executable(tmp_path):
    import os

    settings = _render_settings(tmp_path)
    out = tmp_path / "rendered"
    await _render(settings, out)
    assert os.access(out / "scripts" / "pkc", os.X_OK)


async def test_a_non_empty_directory_is_refused_and_force_replaces_it_wholesale(tmp_path):
    settings = _render_settings(tmp_path)
    out = tmp_path / "rendered"
    out.mkdir()
    (out / "somebody-elses.md").write_text("mine\n", encoding="utf-8")

    code, _out, stderr = await _skill(settings, ["render", "--out", str(out)])
    assert code == EXIT_REFUSED
    assert "--force" in stderr
    # Refused before a byte was written.
    assert sorted(p.name for p in out.iterdir()) == ["somebody-elses.md"]

    await _render(settings, out, force=True)
    assert not (out / "somebody-elses.md").exists()
    assert (out / "SKILL.md").is_file()


async def test_verify_dir_is_silent_when_fresh_and_names_what_drifted(tmp_path):
    from pneuma_knowledge_service.cli.skill import EXIT_DRIFT

    settings = _render_settings(tmp_path)
    out = tmp_path / "rendered"
    await _render(settings, out)

    async def verify():
        code, body, _err = await _skill(
            settings, ["verify", "--dir", str(out), "--json"]
        )
        return code, json.loads(body)[0]

    code, report = await verify()
    assert code == 0
    assert report["drift"] == []

    (out / "references" / "cli.md").write_text("edited\n", encoding="utf-8")
    (out / "references" / "invented.md").write_text("mine\n", encoding="utf-8")
    code, report = await verify()
    assert code == EXIT_DRIFT
    assert report["drift"] == ["references/cli.md", "references/invented.md"]


async def test_a_rendered_language_is_the_pack_the_prose_was_read_under(tmp_path):
    """`--language` moves the pack, never the label: the bytes really are in that language."""
    settings = _render_settings(tmp_path)
    english, chinese = tmp_path / "en", tmp_path / "zh"
    try:
        await _render(settings, english)
        _code, body, _err = await _render(settings, chinese, language="zh")
    finally:
        reset_prompt_overrides()

    report = json.loads(body)
    assert report["language"] == "zh"
    assert json.loads((chinese / VERSION_FILE).read_text(encoding="utf-8"))["language"] == "zh"
    assert report["sha256"] != json.loads(
        (english / VERSION_FILE).read_text(encoding="utf-8")
    )["sha256"]
    assert (chinese / "SKILL.md").read_bytes() != (english / "SKILL.md").read_bytes()
    # A path a harness opens is identity, not prose, and survives the translation.
    assert sorted(p.name for p in (chinese / "references").iterdir()) == sorted(
        p.name for p in (english / "references").iterdir()
    )


@pytest.mark.parametrize("backend", [CODEX, CLAUDE])
def test_evolve_verbs_are_rendered_from_the_parser_and_no_workflow_is_added(backend):
    package = render(backend)
    cli = text(package, "references/cli.md")
    for verb in ("open", "status", "propose", "move-claim", "rename", "retire", "check", "finish", "abandon"):
        assert "pkc evolve draft " + verb in cli
    assert "pkc evolve draft contract edit" in cli
    assert "pkc evolve adopt" in cli
    assert prompt("steward.skill.evolve").strip() in text(package, "SKILL.md")
    assert "workflows/evolve.js" not in package.files


@pytest.mark.parametrize("language", ["en", "zh"])
def test_consume_answering_explains_direct_resolution_and_changes_the_package_hash(language):
    overlay = chinese_overlay() if language == "zh" else {}
    try:
        override_prompts(overlay)
        package = render(language=language)
        reference = text(package, "references/consume.md")
        paragraph = prompt("steward.consume.answering").strip()
        assert paragraph in reference
        assert "pkc consult record --question <q>" in paragraph
        assert 'origin: "direct"' in paragraph and "evidence_handed" in paragraph
        assert ("One question, one record" if language == "en" else "一个问题，一条记录") in paragraph
        assert ("exit 4" if language == "en" else "退出码 4") in paragraph
        system = render_system_contract(SKILL)
        override_prompts({**overlay, "steward.consume.answering": "Synthetic previous recording rule."})
        before = render(language=language)
        assert before.sha256 != package.sha256
        assert before.files["references/compile-instructions.md"] == package.files["references/compile-instructions.md"]
        assert render_system_contract(SKILL) == system
    finally:
        reset_prompt_overrides()
