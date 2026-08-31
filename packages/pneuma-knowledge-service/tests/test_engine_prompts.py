"""The Prompt Studio's service half: `/v1/engine/prompts` and its rewrite endpoint.

Same conditions as the rest of the engine surface — a real temporary git repo, no
Postgres/Qdrant/Meili, no provider key. The rewriter runs on a scripted model, so the
endpoint's shape, its keyless refusal and its never-writes promise are all testable
without a credential.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from pathlib import Path

import httpx
import pytest

from pneuma_knowledge_service.api.app import create_app
from pneuma_knowledge_service.settings import Settings

SEED = {
    "README.md": "# engine\n",
    "engine.yaml": "compile: openrouter:x/compile\nrecall: openrouter:x/recall\n",
    "intake/intake.yaml": "chunk_strategy: sentence\n",
    "compile/contract.md": "---\nskill_id: demo\nversion: app-v1\n---\n\nRecord decisions.\n",
    "compile/challenge.yaml": "enabled: false\n",
    "evolve/evolve.yaml": "auto_trigger: true\n",
    "recall/recall.yaml": "answer_style: conversational\n",
    "persona/profile.yaml": "display_name: Someone\n",
    "prompts/overlays.yaml": (
        "overlays:\n"
        "  recall.close.answer_honestly: |\n"
        "    Say what the records say, and say plainly when they say nothing.\n"
    ),
}

OVERRIDDEN = "Say what the records say, and say plainly when they say nothing.\n"


def _seed_engine(root: Path, files: dict[str, str] | None = None) -> Path:
    engine = root / "engine"
    for rel, text in (SEED if files is None else files).items():
        path = engine / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    subprocess.run(["git", "-C", str(engine), "init", "-q"], check=True)
    subprocess.run(
        ["git", "-C", str(engine), "config", "user.email", "engine@local"], check=True
    )
    subprocess.run(
        ["git", "-C", str(engine), "config", "user.name", "pneuma-engine"], check=True
    )
    subprocess.run(["git", "-C", str(engine), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(engine), "commit", "-q", "-m", "engine: initial"], check=True
    )
    return engine


def _client(engine_dir: str, **settings: object) -> httpx.AsyncClient:
    app = create_app(Settings(engine_dir=engine_dir, **settings))
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


def _scripted(tmp_path: Path, draft: str, notes: str) -> str:
    """A one-turn script answering the structured-output call by its class name."""
    path = tmp_path / "rewrite.json"
    path.write_text(
        json.dumps(
            {"turns": [[{"name": "PromptRewrite", "args": {"draft": draft, "notes": notes}}]]}
        ),
        encoding="utf-8",
    )
    return f"scripted:{path}"


@pytest.fixture(autouse=True)
def _no_env_overrides(monkeypatch):
    for name in (
        "PNEUMA_KNOWLEDGE_CHUNK_STRATEGY",
        "PNEUMA_KNOWLEDGE_EMBEDDING_MODEL",
        "PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE",
        "PNEUMA_KNOWLEDGE_LLM_MODEL",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_COMPILE",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_RECALL",
        "PNEUMA_KNOWLEDGE_LLM_MODEL_DEEP",
        "PNEUMA_KNOWLEDGE_PROMPT_LANGUAGE",
    ):
        monkeypatch.delenv(name, raising=False)


# ────────────────────────────────────────────────────── the surfaces (frozen shape)


async def test_prompts_answers_the_frozen_shape(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/prompts")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body) == {"surfaces"}
    for surface in body["surfaces"]:
        assert set(surface) == {
            "id",
            "group",
            "kind",
            "title",
            "summary",
            "note",
            "segments",
            "assembled_framework",
            "assembled_effective",
        }
        assert surface["kind"] in ("assembled", "fragments")
        assert set(surface["title"]) == {"en", "zh"}
        assert set(surface["summary"]) == {"en", "zh"}
        if surface["note"] is not None:
            assert set(surface["note"]) == {"en", "zh"}
            assert surface["kind"] == "assembled", surface["id"]
        assert surface["segments"], f"{surface['id']} has no segments"
        for segment in surface["segments"]:
            assert set(segment) == {
                "key",
                "label",
                "context",
                "framework_text",
                "override_text",
                "placeholders",
                "shared_with",
            }
            assert set(segment["label"]) == {"en", "zh"}
            assert segment["framework_text"]
            if surface["kind"] == "fragments":
                # Nothing in a fragment family's layout says when a clause is used, so the
                # payload has to say it — in both languages, per clause.
                assert set(segment["context"] or {}) == {"en", "zh"}, (
                    f"{surface['id']}:{segment['key']} has no applicability note"
                )


async def test_a_fragment_family_carries_no_assembled_text_at_all(tmp_path):
    """The regression. `source.preamble.*` is 28 conditional alternatives; concatenating
    them produced "the ownera conversationThis is…" and the studio showed it as the prompt.
    Now the family reports empty assembled strings and explains itself clause by clause."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    preamble = next(s for s in body["surfaces"] if s["id"] == "intake.source_preamble")
    assert preamble["kind"] == "fragments"
    assert preamble["assembled_framework"] == ""
    assert preamble["assembled_effective"] == ""

    by_key = {seg["key"]: seg for seg in preamble["segments"]}
    owner = by_key["source.preamble.owner_default"]["framework_text"]
    scene = by_key["source.preamble.stream_scene_default"]["framework_text"]
    # The exact gibberish the concatenation used to produce, nowhere in the payload.
    for surface in body["surfaces"]:
        for rendered in (surface["assembled_framework"], surface["assembled_effective"]):
            assert owner + scene not in rendered, surface["id"]
    # And the two words that were being glued now each say when they are used instead.
    assert "does not know their display name" in by_key[
        "source.preamble.owner_default"
    ]["context"]["en"]
    assert "no scene phrase" in by_key["source.preamble.stream_scene_default"]["context"]["en"]


async def test_an_assembled_surface_still_carries_the_bytes_the_model_receives(tmp_path):
    """The other half: marking families as fragments must not cost the real assemblies
    their preview, which is the studio's whole reason to exist."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    assembled = [s for s in body["surfaces"] if s["kind"] == "assembled"]
    # +3: the Live Context pick contract and BOTH shapes of its discover contract — one
    # with the supplementary web lookup offered and one without, pinned separately because
    # the toggle changes which SystemMessage renders and nothing else.
    assert len(assembled) == 19
    for surface in assembled:
        assert surface["assembled_framework"].strip(), surface["id"]
        assert surface["assembled_effective"].strip(), surface["id"]
    fragments = [s for s in body["surfaces"] if s["kind"] == "fragments"]
    # +1: the supplementary web search's own instruction — a third model, so a family of
    # its own rather than a section of the two-call pipeline input.
    assert len(fragments) == 32


async def test_a_template_preview_carries_the_banner_that_stops_it_reading_as_the_message(
    tmp_path,
):
    """The verification pass's first P1: the studio showed `compile.system` with `{templates}`
    and `{instructions}` still unfilled, and §2 saying no profile was supplied, under the
    words "the order and the original as the model receives them". The payload now names what
    is substituted per call, so the UI has something to say instead of that."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    system = next(s for s in body["surfaces"] if s["id"] == "compile.system")
    assert system["note"] is not None
    for face in ("en", "zh"):
        note = system["note"][face]
        # the four values the framework substitutes, named where the reader can see the braces
        for slot in ("{skill_id}", "{version}", "{templates}", "{instructions}"):
            assert slot in note, (face, slot)
    assert "{slug}" in system["note"]["en"], "the one brace that is NOT an injection point"
    assert "assembly template" in system["note"]["en"].lower()
    assert "装配模板" in system["note"]["zh"]
    # A fragment family has no assembled text, so it has nothing to caveat.
    preamble = next(s for s in body["surfaces"] if s["id"] == "intake.source_preamble")
    assert preamble["note"] is None


async def test_every_assembly_with_a_slot_left_in_it_carries_a_note(tmp_path):
    """Mechanism, not per-surface diligence: an unfilled placeholder in the preview IS the
    definition of a template, so the payload may never show one without the banner."""
    from pneuma_knowledge_core.prompts import template_fields

    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    for surface in body["surfaces"]:
        if surface["kind"] != "assembled":
            continue
        left = template_fields(surface["assembled_effective"])
        if left:
            assert surface["note"] is not None, f"{surface['id']} leaves {sorted(left)} unfilled"


async def test_the_override_in_the_engine_directory_is_what_effective_renders(tmp_path):
    """The point of the whole surface: a person sees what THIS engine's models receive."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    fast = next(s for s in body["surfaces"] if s["id"] == "recall.fast")
    close = next(
        seg for seg in fast["segments"] if seg["key"] == "recall.close.answer_honestly"
    )
    assert close["override_text"] == OVERRIDDEN
    assert OVERRIDDEN.strip() in fast["assembled_effective"]
    assert OVERRIDDEN.strip() not in fast["assembled_framework"]
    # And a clause nobody touched reports no override at all — `null`, not `""`.
    head = next(seg for seg in fast["segments"] if seg["key"] == "recall.fast.contract_head")
    assert head["override_text"] is None


async def test_a_shared_clause_names_the_other_prompts_it_moves(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    fast = next(s for s in body["surfaces"] if s["id"] == "recall.fast")
    spine = next(seg for seg in fast["segments"] if seg["key"] == "recall.spine")
    assert set(spine["shared_with"]) == {
        "recall.deep",
        "recall.briefing",
        "recall.suggestion",
        "recall.fast_structured",
        "recall.fast_deliberated",
    }
    assert spine["placeholders"] == ["cite", "close"]


async def test_runtime_placeholders_are_reported_and_left_visible(tmp_path):
    """The compile contract's `{templates}` is filled from the skill at run time, so the
    preview shows it as a placeholder rather than pretending to know its value."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    system = next(s for s in body["surfaces"] if s["id"] == "compile.system")
    contract = next(
        seg for seg in system["segments"] if seg["key"] == "compile.write_contract"
    )
    # `{slug}` is in there too: the contract TEACHES the path placeholder in its own prose,
    # and the gate holds an override to the same set rather than trying to tell the two
    # kinds of brace apart.
    assert contract["placeholders"] == ["owner", "slug", "templates"]
    assert "{templates}" in system["assembled_framework"]


async def test_every_catalog_key_is_reachable_through_some_surface(tmp_path):
    from pneuma_knowledge_core.prompts import default_catalog

    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    reachable = {seg["key"] for s in body["surfaces"] for seg in s["segments"]}
    assert reachable == set(default_catalog())


async def test_prompts_400s_on_a_hand_broken_overlay_file(tmp_path):
    engine = _seed_engine(tmp_path)
    (engine / "prompts" / "overlays.yaml").write_text("overlays: [oops\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        resp = await client.get("/v1/engine/prompts")
    assert resp.status_code == 400
    assert "prompts/overlays.yaml" in resp.json()["detail"]


async def test_an_unrelated_broken_stage_file_does_not_cost_the_studio_its_picture(tmp_path):
    """Only the overlay file is read here — `/state` is where a broken knob file bites."""
    engine = _seed_engine(tmp_path)
    (engine / "recall" / "recall.yaml").write_text("answer_style: [oops\n", encoding="utf-8")
    async with _client(str(engine)) as client:
        assert (await client.get("/v1/engine/state")).status_code == 400
        assert (await client.get("/v1/engine/prompts")).status_code == 200


# ─────────────────────────────────────────────────────────── the active language pack


ZH_SEED = {
    **SEED,
    "prompts/overlays.yaml": (
        "language: zh\n"
        "overlays:\n"
        "  recall.close.answer_honestly: |\n"
        "    Say what the records say, and say plainly when they say nothing.\n"
    ),
}


async def test_framework_text_follows_the_active_language_pack(tmp_path):
    """Below the pack there is no author, only the framework. So under a zh engine the pack's
    own sentence IS the framework text — presenting the English default there would show the
    pack's wording as somebody's override and make every real override a diff against prose
    the model never receives."""
    from pneuma_knowledge_core.prompts import chinese_overlay, default_catalog

    engine = _seed_engine(tmp_path, ZH_SEED)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    system = next(s for s in body["surfaces"] if s["id"] == "compile.system")
    contract = next(
        seg for seg in system["segments"] if seg["key"] == "compile.write_contract"
    )
    assert contract["framework_text"] == chinese_overlay()["compile.write_contract"]
    assert contract["framework_text"] != default_catalog()["compile.write_contract"]
    assert contract["override_text"] is None
    assert "知识编译" in system["assembled_framework"]
    # and the placeholder contract is unchanged, which is what makes the two interchangeable
    assert contract["placeholders"] == ["owner", "slug", "templates"]


async def test_an_override_stays_an_override_on_top_of_the_pack(tmp_path):
    """The layering the studio must show: pack = framework, this project's clause = override.
    Both renders exist, and only the effective one carries the project's sentence."""
    engine = _seed_engine(tmp_path, ZH_SEED)
    async with _client(str(engine)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    segment, surface = next(
        (seg, s)
        for s in body["surfaces"]
        for seg in s["segments"]
        if seg["key"] == "recall.close.answer_honestly"
    )
    assert segment["override_text"] == OVERRIDDEN
    assert segment["framework_text"].startswith("- 面前的证据")
    assert OVERRIDDEN.strip() in surface["assembled_effective"]
    assert OVERRIDDEN.strip() not in surface["assembled_framework"]
    assert "- 面前的证据" in surface["assembled_framework"]


async def test_english_is_the_default_and_the_env_still_outranks_the_file(tmp_path, monkeypatch):
    from pneuma_knowledge_core.prompts import default_catalog
    from pneuma_knowledge_service.engine.prompts import active_language

    plain = _seed_engine(tmp_path / "a")
    assert active_language(plain, {}) == "en"
    zh = _seed_engine(tmp_path / "b", ZH_SEED)
    assert active_language(zh, {}) == "zh"
    assert active_language(zh, {"PNEUMA_KNOWLEDGE_PROMPT_LANGUAGE": "en"}) == "en"
    monkeypatch.setenv("PNEUMA_KNOWLEDGE_PROMPT_LANGUAGE", "en")
    async with _client(str(zh)) as client:
        body = (await client.get("/v1/engine/prompts")).json()
    system = next(s for s in body["surfaces"] if s["id"] == "compile.system")
    contract = next(
        seg for seg in system["segments"] if seg["key"] == "compile.write_contract"
    )
    assert contract["framework_text"] == default_catalog()["compile.write_contract"]


def test_the_startup_stack_registers_the_pack_first_and_the_project_second():
    """The ORDER is the contract, so it is asserted rather than described in a comment: a
    project's own clause must survive the language pack, not be taken back by it."""
    from pneuma_knowledge_core.prompts import (
        chinese_overlay,
        prompt,
        reset_prompt_overrides,
    )
    from pneuma_knowledge_service.engine.prompts import apply_prompt_stack

    reset_prompt_overrides()
    try:
        count = apply_prompt_stack("zh", {"recall.cite.precise": "cite the paragraph."})
        assert count == 1
        # the project's clause won
        assert prompt("recall.cite.precise") == "cite the paragraph."
        # every other surface came from the pack
        assert prompt("compile.rules_header") == chinese_overlay()["compile.rules_header"]
    finally:
        reset_prompt_overrides()


def test_the_english_stack_registers_nothing_it_does_not_have_to():
    """`en` must stay byte-for-byte the pre-language-pack behavior: no overlay registered at
    all, so `prompt_overlay_hash()` is still None and the commit trailer is unchanged."""
    from pneuma_knowledge_core.prompts import (
        prompt_overlay_hash,
        reset_prompt_overrides,
    )
    from pneuma_knowledge_service.engine.prompts import apply_prompt_stack

    reset_prompt_overrides()
    try:
        assert apply_prompt_stack("en", {}) == 0
        assert prompt_overlay_hash() is None
    finally:
        reset_prompt_overrides()


# ──────────────────────────────────────────────────────────────────── the rewriter


async def test_rewrite_returns_a_draft_and_writes_nothing(tmp_path):
    engine = _seed_engine(tmp_path)
    spec = _scripted(tmp_path, "Cite the source id, and nothing more.", "shorter, same rule")
    async with _client(str(engine), llm_model=spec) as client:
        before = (await client.get("/v1/engine/state")).json()["version"]
        resp = await client.post(
            "/v1/engine/prompts/rewrite",
            json={
                "key": "recall.cite.source_level",
                "intent": "make it one sentence",
                "locale": "en",
            },
        )
        after = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "draft": "Cite the source id, and nothing more.",
        "notes": "shorter, same rule",
    }
    # Never writes: same HEAD, same clean tree, and the overlay file is untouched.
    assert after["version"] == before
    assert after["version"]["dirty"] is False
    assert (engine / "prompts" / "overlays.yaml").read_text(encoding="utf-8") == SEED[
        "prompts/overlays.yaml"
    ]


async def test_rewrite_503s_when_the_deployment_runs_keyless(tmp_path):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine), llm_model="", llm_model_recall="") as client:
        resp = await client.post(
            "/v1/engine/prompts/rewrite",
            json={"key": "recall.cite.precise", "intent": "shorter", "locale": "zh"},
        )
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "OPENROUTER_API_KEY" in detail
    assert "browsing and editing stay fully served" in detail


async def test_rewrite_400s_on_a_key_the_catalog_does_not_have(tmp_path):
    engine = _seed_engine(tmp_path)
    spec = _scripted(tmp_path, "x", "y")
    async with _client(str(engine), llm_model=spec) as client:
        resp = await client.post(
            "/v1/engine/prompts/rewrite",
            json={"key": "not.a.real.key", "intent": "shorter", "locale": "en"},
        )
    assert resp.status_code == 400
    assert "not a prompt-catalog key" in resp.json()["detail"]


async def test_rewrite_502s_rather_than_handing_back_an_empty_clause(tmp_path):
    engine = _seed_engine(tmp_path)
    spec = _scripted(tmp_path, "   ", "nothing")
    async with _client(str(engine), llm_model=spec) as client:
        resp = await client.post(
            "/v1/engine/prompts/rewrite",
            json={"key": "recall.cite.precise", "intent": "shorter", "locale": "en"},
        )
    assert resp.status_code == 502
    assert "Nothing was written" in resp.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"key": "", "intent": "x", "locale": "en"},
        {"key": "recall.spine", "intent": "", "locale": "en"},
        {"key": "recall.spine", "intent": "x", "locale": "fr"},
    ],
)
async def test_rewrite_validates_the_request_body(tmp_path, body):
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        assert (await client.post("/v1/engine/prompts/rewrite", json=body)).status_code == 422


def test_the_rewrite_prompt_carries_the_context_a_clause_cannot_be_judged_without():
    """The unit the endpoint composes: position, neighbours, original, slots, intent."""
    from pneuma_knowledge_service.engine import rewrite_messages

    system, human = rewrite_messages(
        "recall.spine",
        "drop the transcription-homophone paragraph",
        "zh",
        {"recall.spine": "A shorter spine. {cite} {close}"},
    )
    assert "Write `notes` as ONE line, in zh" in system
    assert "Preserve every named placeholder" in system
    # Where it sits, and what it sits between.
    assert "→ recall.spine" in human
    assert "recall.fast.contract_head" in human
    assert "# The clause immediately before it (recall.fast.contract_head)" in human
    assert "# The clause immediately after it (recall.cite.source_level)" in human
    # Its own original, its slot contract, the override in force, and the intent.
    assert "At the top of every ask sits the owner's basic profile" in human
    assert "{cite}, {close}" in human
    assert "A shorter spine. {cite} {close}" in human
    assert "drop the transcription-homophone paragraph" in human
    # And that rewriting it moves three other prompts.
    assert "This clause is SHARED" in human


def test_a_neighbour_that_was_itself_overridden_is_shown_as_overridden():
    """Context has to be this engine's context, not the framework's: a person rewriting a
    clause needs to see the wording it will actually sit next to."""
    from pneuma_knowledge_service.engine import rewrite_messages

    _, human = rewrite_messages(
        "recall.cite.source_level",
        "shorter",
        "en",
        {"recall.close.answer_honestly": OVERRIDDEN},
    )
    assert OVERRIDDEN.strip() in human


def test_a_fragment_is_briefed_as_an_alternative_and_never_as_a_neighbour():
    """A clause of a fragment family has no "before" and no "after". Briefing the rewriter
    with neighbours would make it write a continuation of a sentence that is not there —
    `source.preamble.owner_default` is a NOUN standing in for a name."""
    from pneuma_knowledge_service.engine import rewrite_messages

    _, human = rewrite_messages("source.preamble.owner_default", "warmer", "en", {})
    assert "# The clause family this belongs to" in human
    assert "reached one at a time" in human
    assert "# When the model receives this clause" in human
    assert "does not know their display name" in human
    assert "The clause immediately before it" not in human
    assert "The clause immediately after it" not in human


def test_the_zh_brief_forbids_swapping_a_chinese_term_for_its_english_equivalent():
    """VERIFY #5. Under a Chinese engine a real rewrite of `gate.feedback_header` came back as
    "gate 已拒绝 … 使用 claim-level 工具修复", passed the placeholder check (no slots) and was
    appliable — the Chinese pack degraded by a mechanism meant to help. The brief now names
    the pack's language and the terms that must survive it."""
    from pneuma_knowledge_service.engine import rewrite_messages

    system, _ = rewrite_messages(
        "gate.feedback_header", "说得更直接一点", "zh", {}, language="zh"
    )
    assert "语言包是**中文**" in system
    for term, english in (
        ("闸门", "gate"),
        ("断言", "claim"),
        ("正本", "canonical"),
        ("锚点", "anchor"),
    ):
        assert term in system and english in system, term
    # …while the things that are NOT terminology are exempted by name, so the rule cannot be
    # read as "translate the tool names too".
    assert "`finish_compile`" in system
    assert "Write `notes` as ONE line, in zh" in system


def test_the_zh_brief_shows_the_pack_wording_and_not_the_english_default():
    """The other half of the same defect: the rewriter used to be handed the English default
    as "the framework's original" under a Chinese engine, and then told to keep the original's
    language. It was doing what it was asked."""
    from pneuma_knowledge_core.prompts import chinese_overlay, default_catalog
    from pneuma_knowledge_service.engine import rewrite_messages

    _, human = rewrite_messages(
        "gate.feedback_header", "说得更直接一点", "zh", {}, language="zh"
    )
    assert chinese_overlay()["gate.feedback_header"].strip() in human
    assert default_catalog()["gate.feedback_header"].strip() not in human


def test_an_english_engine_is_told_it_is_an_english_pack():
    from pneuma_knowledge_service.engine import rewrite_messages

    system, _ = rewrite_messages("recall.cite.precise", "shorter", "zh", {})
    assert "prompt pack is ENGLISH" in system
    # The UI locale still decides who the notes are for — the two are independent.
    assert "Write `notes` as ONE line, in zh" in system


async def test_the_rewrite_endpoint_follows_the_engines_pack_not_the_request_locale(tmp_path):
    """The endpoint reads the language off the engine directory, so a console in English over
    a Chinese pack still gets a Chinese clause asked for."""
    from pneuma_knowledge_service.engine import active_language

    engine = _seed_engine(tmp_path, ZH_SEED)
    assert active_language(engine, {}) == "zh"
    spec = _scripted(tmp_path, "闸门已拒绝：下面这些机械检查没有通过。", "更直接")
    async with _client(str(engine), llm_model=spec) as client:
        resp = await client.post(
            "/v1/engine/prompts/rewrite",
            json={"key": "gate.feedback_header", "intent": "更直接", "locale": "en"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["draft"] == "闸门已拒绝：下面这些机械检查没有通过。"


def test_a_clause_with_no_placeholders_says_so_rather_than_listing_nothing():
    from pneuma_knowledge_service.engine import rewrite_messages

    _, human = rewrite_messages("recall.cite.precise", "shorter", "en", {})
    assert "declares no placeholders" in human
    assert "(none — the framework wording is what the model sees today)" in human


# ────────────────────────────────────────────────────────────── the placeholder gate


def _overlay_file(key: str, clause: str) -> str:
    body = "\n".join(f"    {line}" for line in clause.splitlines())
    return f"overlays:\n  {key}: |\n{body}\n"


async def test_apply_refuses_an_override_that_drops_a_placeholder(tmp_path):
    """`{preview}` and `{anchor}` are where the gate names the offending claim. An
    override without them renders a rejection nobody can act on."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {
                        "path": "prompts/overlays.yaml",
                        "content": _overlay_file(
                            "gate.claim_without_provenance", "Every claim cites its blocks."
                        ),
                    }
                ],
                "label": "shorter provenance rejection",
            },
        )
        state = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "{preview}" in detail and "{anchor}" in detail
    assert "gate.claim_without_provenance" in detail
    assert state["version"]["dirty"] is False, "a rejected apply writes nothing"


async def test_apply_accepts_an_override_that_keeps_every_placeholder(tmp_path):
    engine = _seed_engine(tmp_path)
    clause = 'Every claim cites its blocks: "{preview}…" (c:{anchor}).'
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {
                        "path": "prompts/overlays.yaml",
                        "content": _overlay_file("gate.claim_without_provenance", clause),
                    }
                ],
                "label": "shorter provenance rejection",
            },
        )
        state = (await client.get("/v1/engine/state")).json()
    assert resp.status_code == 200, resp.text
    assert state["values"]["prompts.overlays"] == {
        "gate.claim_without_provenance": clause + "\n"
    }


async def test_apply_refuses_an_override_that_invents_a_placeholder(tmp_path):
    """Nothing substitutes it, so it reaches the model as literal braces — and it would
    only be caught at the next process start, after the commit."""
    engine = _seed_engine(tmp_path)
    async with _client(str(engine)) as client:
        resp = await client.post(
            "/v1/engine/apply",
            json={
                "changes": [
                    {
                        "path": "prompts/overlays.yaml",
                        "content": _overlay_file(
                            "recall.cite.precise", "Cite {source_id} down to the block."
                        ),
                    }
                ],
                "label": "invent a slot",
            },
        )
    assert resp.status_code == 400
    assert "{source_id}" in resp.json()["detail"]
    assert "literal braces" in resp.json()["detail"]


def test_the_gate_is_exactly_the_core_seams_startup_check_plus_the_missing_half():
    """The console is stricter than `override_prompt` on purpose: that seam is a library
    call written with the default in front of you, this is a form filled from an intent."""
    from pneuma_knowledge_core.prompts import override_prompt, reset_prompt_overrides
    from pneuma_knowledge_service.engine.apply import _assert_slots_preserved
    from pneuma_knowledge_service.engine.files import EngineFileError

    reset_prompt_overrides()
    # A subset is legal at the library seam …
    override_prompt("gate.claim_without_provenance", "no provenance on c:{anchor}.")
    reset_prompt_overrides()
    # … and refused at the console.
    with pytest.raises(EngineFileError, match=r"\{preview\}"):
        _assert_slots_preserved(
            "prompts/overlays.yaml",
            {"gate.claim_without_provenance": "no provenance on c:{anchor}."},
        )
