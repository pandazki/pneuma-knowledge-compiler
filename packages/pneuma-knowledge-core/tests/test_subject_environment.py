"""The subject's declared environment: region, timezone, language — and the write rule.

WHY THIS IS TESTED AT ALL
-------------------------
The first evaluation of a real Chinese-language knowledge base found 100% of the claims in the
first ten compile rounds written in English. Nothing was broken: the contract was English, the
skill body was Chinese, and no sentence anywhere told the model what language the subject reads.
The fix is a declaration, so what has to be tested is that the declaration is actually THERE —
in every state, including the states where the answer is "nobody set this" — and that it says
where each value came from, because a deployment default presented as the subject's own setting
is a claim nobody can support.

The environment block lives on the SYSTEM side, so these also pin invariant I5: the block is
byte-stable per (owner, zone, provenance), and the TimeContext's instant never leaks into it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from pneuma_knowledge_core.compile.runner import run_compile
from pneuma_knowledge_core.domain.ids import SourceId, UserId
from pneuma_knowledge_core.domain.source import (
    NormalizedBlock,
    NormalizedSource,
    RawSource,
    StructureMap,
)
from pneuma_knowledge_core.domain.time_context import TimeContext
from pneuma_knowledge_core.prompts import (
    override_prompt,
    prompt,
    reset_prompt_overrides,
)
from pneuma_knowledge_core.skill import load_skill_base, render_system_contract

TOKYO = ZoneInfo("Asia/Tokyo")
SHANGHAI = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean_overrides():
    reset_prompt_overrides()
    yield
    reset_prompt_overrides()


class _Locale:
    def __init__(self, **fields: str) -> None:
        self.city = fields.get("city", "")
        self.country = fields.get("country", "")
        self.timezone = fields.get("timezone", "")
        self.language = fields.get("language", "")


class _Owner:
    """A synthetic subject; only the fields the contract reads are present."""

    display_name = "Mira Halden"
    occupation = "harbour operations lead"

    def __init__(self, locale: _Locale | None = None) -> None:
        self.locale = locale


def _section(contract: str) -> str:
    """§2 of the contract — where the environment block lives."""
    return contract[contract.index("# 2.") : contract.index("# 3.")]


def _render(owner: object | None, time: TimeContext | None) -> str:
    return _section(render_system_contract(load_skill_base("v1"), owner, time=time))


def _timezone_line(section: str) -> str:
    return next(line for line in section.splitlines() if "**Timezone**" in line)


# ────────────────────────────────────────────────────── the three states, declared


def test_a_fully_known_environment_declares_all_three_with_their_provenance():
    locale = _Locale(
        city="Bayside", country="Northland", timezone="Asia/Tokyo", language="ja-JP"
    )
    section = _render(
        _Owner(locale), TimeContext(now_utc=NOW, zone=TOKYO, zone_source="profile")
    )
    assert "- **Region**: Bayside, Northland — on record for the subject." in section
    assert "- **Timezone**: Asia/Tokyo — on record for the subject." in section
    assert "- **Language**: ja-JP — on record for the subject." in section


def test_a_half_known_environment_names_the_defaults_standing_in_for_the_gaps():
    """The user's own framing: use a default when a setting is missing, but say so and say why.
    A blank line where the language should be is what produced an English knowledge base for a
    Chinese-reading subject; a line that reads "unknown, English by default" cannot."""
    section = _render(
        _Owner(_Locale(city="Bayside")),
        TimeContext(now_utc=NOW, zone=SHANGHAI, zone_source="deployment_default"),
    )
    assert "- **Region**: Bayside — on record for the subject." in section
    assert "no timezone is on record for the subject" in section
    assert "deployment's default **Asia/Shanghai** is in use" in section
    assert "no language is on record for the subject" in section
    assert "**English** is used by default" in section


def test_with_no_profile_at_all_the_block_still_renders_every_line():
    """The `_OWNER_UNKNOWN` path. "No profile" is a state of the environment, not an excuse to
    omit the declaration — omitting it is exactly how the model was left to guess."""
    section = _render(None, TimeContext(now_utc=NOW, zone=ZoneInfo("UTC"), zone_source="deployment_default"))
    assert "No profile of the knowledge subject was supplied" in section
    assert "no city or country is on record" in section
    assert "deployment's default **UTC** is in use" in section
    assert "**English** is used by default" in section


def test_a_provider_resolved_zone_is_not_declared_as_the_subjects_own_setting():
    section = _render(
        _Owner(_Locale(city="Bayside", language="ja-JP")),
        TimeContext(now_utc=NOW, zone=TOKYO, zone_source="provider"),
    )
    assert (
        _timezone_line(section)
        == "- **Timezone**: Asia/Tokyo — resolved for this material by this deployment."
    )


def test_without_a_time_context_the_profiles_own_zone_is_declared():
    section = _render(_Owner(_Locale(timezone="Asia/Tokyo")), None)
    assert "- **Timezone**: Asia/Tokyo — on record for the subject." in section


def test_with_neither_a_time_context_nor_a_profile_zone_no_zone_is_invented():
    section = _render(_Owner(_Locale(city="Bayside")), None)
    assert "- **Timezone**: unknown — none was resolved for this round." in section
    assert "do not compute a calendar day of your own" in section


def test_a_bare_time_context_declares_its_zone_without_inventing_a_provenance():
    """A hand-built TimeContext (evolve, a script, a test) carries no provenance. The line states
    the zone and stops — the one thing it must not do is pick a story."""
    section = _render(_Owner(_Locale(city="Bayside")), TimeContext(now_utc=NOW, zone=TOKYO))
    assert _timezone_line(section) == "- **Timezone**: Asia/Tokyo."


# ───────────────────────────────────────────────── the write rule, on the system side


def test_the_write_language_rule_reaches_the_system_contract():
    contract = render_system_contract(
        load_skill_base("v1"),
        _Owner(_Locale(language="ja-JP")),
        time=TimeContext(now_utc=NOW, zone=TOKYO, zone_source="profile"),
    )
    assert prompt("compile.owner_env.write_language") in contract
    assert prompt("compile.owner_env.day_grouping") in contract
    # …and it reaches the no-profile path too, where the default is what is being enforced.
    assert prompt("compile.owner_env.write_language") in render_system_contract(
        load_skill_base("v1")
    )


def test_the_contract_never_asserts_that_a_round_is_one_calendar_day():
    """The byte-stable contract cannot know the round's grouping, so it must not claim one.

    It used to say "the material of each round is grouped by calendar day" — true under
    `group_by: day|source`, FALSE under a batched round, and false in the direction that
    makes the compiler trust a single implied day for material spanning several. The shape
    is a per-round fact and lives in the task; this line only names the zone and points at
    the per-source dates.
    """
    line = prompt("compile.owner_env.day_grouping")
    assert "grouped by calendar day" not in line
    assert "one day of material or several" in line
    assert "each source states its own date" in line


def test_the_locale_is_declared_once_and_not_repeated_as_a_profile_line():
    """Region/timezone/language used to also appear in the identity lines as "Based in: …;
    timezone …; language …". Saying the same three facts twice in one section — once as
    background, once as an instruction — is how a contract starts disagreeing with itself."""
    section = _render(
        _Owner(_Locale(city="Bayside", country="Northland", timezone="Asia/Tokyo", language="ja-JP")),
        TimeContext(now_utc=NOW, zone=TOKYO, zone_source="profile"),
    )
    assert section.count("Bayside") == 1
    assert section.count("Asia/Tokyo") == 1
    assert section.count("ja-JP") == 1


# ──────────────────────────────────────────────────────── I5: per-owner byte stability


def test_the_block_is_byte_stable_across_instants_of_the_same_job_shape():
    """Only the zone and its provenance are read from the TimeContext. If the instant leaked in,
    every job would render a new SystemMessage and the provider cache would be spent for nothing.
    """
    owner = _Owner(_Locale(city="Bayside", timezone="Asia/Tokyo", language="ja-JP"))
    skill = load_skill_base("v1")
    early = render_system_contract(
        skill, owner, time=TimeContext(now_utc=NOW, zone=TOKYO, zone_source="profile")
    )
    later = render_system_contract(
        skill,
        owner,
        time=TimeContext(now_utc=NOW + timedelta(days=400), zone=TOKYO, zone_source="profile"),
    )
    assert early == later
    # I5, narrowly: no date from the job's clock reaches the environment block.
    assert "2026-" not in _section(early)


def test_a_different_zone_provenance_is_a_different_contract():
    """The counterpart: provenance is content, not decoration. Same zone, different answer to
    "who said so", different bytes — because the model is being told something different."""
    owner = _Owner(_Locale(city="Bayside", language="ja-JP"))
    skill = load_skill_base("v1")
    from_profile = render_system_contract(
        skill, owner, time=TimeContext(now_utc=NOW, zone=TOKYO, zone_source="profile")
    )
    from_default = render_system_contract(
        skill, owner, time=TimeContext(now_utc=NOW, zone=TOKYO, zone_source="deployment_default")
    )
    assert from_profile != from_default


# ──────────────────────────────────────────── the wiring: it reaches an actual compile


class _RecordingModel(BaseChatModel):
    """Records the messages it is handed and finishes the compile immediately."""

    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def bind_tools(self, tools, **kwargs):  # noqa: ANN001
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        self.seen.append(list(messages))
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "finish_compile",
                                "args": {},
                                "id": "call-1",
                                "type": "tool_call",
                            }
                        ],
                        usage_metadata={
                            "input_tokens": 1,
                            "output_tokens": 1,
                            "total_tokens": 2,
                        },
                    )
                )
            ]
        )

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # noqa: ANN001
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class _EmptyStore:
    async def list(self, user_id, *, at=None):
        return []

    async def read(self, user_id, document_id, *, at=None):
        return None

    async def commit_patch(self, user_id, files, *, message):  # pragma: no cover - unused
        return "0" * 40, []


async def test_the_jobs_resolved_zone_and_its_provenance_reach_the_system_message():
    """The wiring that can rot silently: `run_compile` has the job's TimeContext, and the
    environment block is the only place its PROVENANCE is stated. Drop the argument and the block
    quietly falls back to the profile — declaring a deployment default as the subject's setting."""
    model = _RecordingModel(seen=[])
    source = NormalizedSource(
        raw=RawSource(
            source_id=SourceId("s-env-01"),
            user_id=UserId("u-env"),
            kind="conversation",
            title="harbour rota",
            mime="text/plain",
            checksum="c",
            created_at=NOW,
        ),
        blocks=[NormalizedBlock(index=0, text="b0")],
        structure=StructureMap(),
    )
    await run_compile(
        user_id=UserId("u-env"),
        model=model,
        store=_EmptyStore(),
        sources=[source],
        skill=load_skill_base("v1"),
        owner=_Owner(_Locale(city="Bayside", language="ja-JP")),
        time=TimeContext(now_utc=NOW, zone=SHANGHAI, zone_source="deployment_default"),
    )
    system = str(model.seen[0][0].content)
    assert "deployment's default **Asia/Shanghai** is in use" in system
    assert "- **Language**: ja-JP — on record for the subject." in system
    assert prompt("compile.owner_env.write_language") in system


# ─────────────────────────────────────────────────────────── the override seam holds


def test_every_environment_line_is_overridable_through_the_catalog():
    override_prompt("compile.owner_env.language", "- **语言**：{value}（档案里设定的）。")
    override_prompt(
        "compile.owner_env.timezone_default",
        "- **时区**：未知——用部署默认的 {value}。",
    )
    section = _render(
        _Owner(_Locale(language="zh-CN")),
        TimeContext(now_utc=NOW, zone=SHANGHAI, zone_source="deployment_default"),
    )
    assert "- **语言**：zh-CN（档案里设定的）。" in section
    assert "- **时区**：未知——用部署默认的 Asia/Shanghai。" in section
