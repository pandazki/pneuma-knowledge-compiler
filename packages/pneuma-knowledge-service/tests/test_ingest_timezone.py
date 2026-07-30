"""The ingest boundary actually consults the subject's timezone.

The core adapters are tested directly in the core package; what could silently break here is
the WIRING — ingest resolving the subject's zone from the profile and handing it to the
adapter. Without it the feature exists and is never used, which is indistinguishable from
not having it. Keyless: a fake store + the mock profile provider, no middleware.
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.domain.user import Locale, UserProfile
from pneuma_knowledge_core.ingest.adapters import (
    AdapterRegistry,
    PlainConversationAdapter,
)
from pneuma_knowledge_service.ingest import ingest_conversation

USER = UserId("u-tz-ingest")


class _FakeStore:
    """Accepts one source and records the enqueued jobs; nothing else is exercised."""

    def __init__(self) -> None:
        self.sources: list = []
        self.jobs: list[tuple[str, dict]] = []

    async def add(self, user_id, normalized):
        self.sources.append(normalized)
        return normalized.raw.source_id

    async def enqueue(self, user_id, kind, payload):
        self.jobs.append((kind, payload))


def _profile(zone: str) -> UserProfile:
    return UserProfile(
        user_id=USER,
        display_name="Subject",
        avatar={"initial": "S", "color": "#6C8EBF"},
        locale=Locale(city="Shanghai", country="China", timezone=zone, language="zh-CN"),
        industry="tech",
        role="engineering",
        level="senior",
        occupation="engineer",
        bio="b",
        workspace={
            "operating_mode": "opc",
            "primary_stack": "Python",
            "automation_level": "agentic",
            "active_since": "2024-05-01",
        },
        preferences={
            "response_language": "zh-CN",
            "units": "metric",
            "privacy_level": "standard",
        },
        joined_at="2024-05-01",
    )


def _ctx(
    zone: str | None, *, raises: bool = False, default_timezone: str = "UTC"
) -> tuple[SimpleNamespace, _FakeStore]:
    store = _FakeStore()
    registry = AdapterRegistry()
    registry.register(PlainConversationAdapter(), kind="conversation")

    async def get_profile(user_id):
        if raises:
            raise RuntimeError("profile provider is down")
        return _profile(zone or "UTC")

    return (
        SimpleNamespace(
            store=store,
            registry=registry,
            user_info=SimpleNamespace(get_profile=get_profile),
            settings=SimpleNamespace(
                context_stream_render_roles=True,
                context_stream_compile_guidance=True,
                default_timezone=default_timezone,
            ),
        ),
        store,
    )


def _turns() -> list[ConversationTurn]:
    # 13:00 and 16:30 UTC — the same UTC day, but 21:00 on the 30th and 00:30 on the 31st
    # in Shanghai, i.e. two different days of the subject's life.
    return [
        ConversationTurn(
            speaker="Alice", text="a", at=datetime(2026, 7, 30, 13, 0, tzinfo=timezone.utc)
        ),
        ConversationTurn(
            speaker="Alice", text="b", at=datetime(2026, 7, 30, 16, 30, tzinfo=timezone.utc)
        ),
    ]


async def test_ingest_sections_by_the_profiles_timezone():
    ctx, store = _ctx("Asia/Shanghai")
    await ingest_conversation(ctx, USER, _turns(), title="evening thread")
    normalized = store.sources[0]
    assert [b.section_path for b in normalized.blocks] == [["2026-07-30"], ["2026-07-31"]]
    # occurred_on is derived by the framework at the same boundary, in the same zone.
    assert normalized.raw.meta["occurred_on"] == "2026-07-30"


async def test_ingest_falls_back_to_utc_when_the_profile_zone_is_utc():
    ctx, store = _ctx("UTC")
    await ingest_conversation(ctx, USER, _turns(), title="evening thread")
    assert {tuple(b.section_path) for b in store.sources[0].blocks} == {("2026-07-30",)}


async def test_a_failing_profile_lookup_degrades_to_utc_rather_than_failing_ingest():
    ctx, store = _ctx(None, raises=True)
    result = await ingest_conversation(ctx, USER, _turns(), title="evening thread")
    assert result.deduplicated is False
    assert {tuple(b.section_path) for b in store.sources[0].blocks} == {("2026-07-30",)}


async def test_with_no_profile_zone_the_deployment_default_cuts_the_sections():
    """The last link of the chain is a DEPLOYMENT fact, not UTC: an installation serving one
    region says so once (Settings.default_timezone) and every subject it knows nothing about
    is filed in that region's days instead of a third of their evenings landing a day early."""
    ctx, store = _ctx(None, raises=True, default_timezone="Asia/Shanghai")
    await ingest_conversation(ctx, USER, _turns(), title="evening thread")
    assert [b.section_path for b in store.sources[0].blocks] == [
        ["2026-07-30"],
        ["2026-07-31"],
    ]


async def test_an_explicit_occurred_on_from_the_caller_survives_ingest():
    ctx, store = _ctx("Asia/Shanghai")
    await ingest_conversation(
        ctx, USER, _turns(), title="backfill", meta={"occurred_on": "2026-01-09"}
    )
    assert store.sources[0].raw.meta["occurred_on"] == "2026-01-09"
