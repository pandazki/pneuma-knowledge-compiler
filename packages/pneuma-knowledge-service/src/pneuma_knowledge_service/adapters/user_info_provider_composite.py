"""Read declared profiles; an absent profile remains unstated, never synthesized."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import UserProfile


class UnstatedUserInfoProvider:
    async def get_profile(self, user_id: UserId) -> UserProfile:
        return UserProfile.unstated(user_id)


class PersistedUserInfoProvider:
    def __init__(
        self, persisted_lookup: Callable[[str], Awaitable[dict[str, Any] | None]],
    ) -> None:
        self._persisted_lookup = persisted_lookup

    async def get_profile(self, user_id: UserId) -> UserProfile:
        stored = await self._persisted_lookup(str(user_id))
        if stored is not None:
            return UserProfile.model_validate(stored)
        return UserProfile.unstated(user_id)
