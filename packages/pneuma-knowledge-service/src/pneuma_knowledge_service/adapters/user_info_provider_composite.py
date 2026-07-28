"""Composite UserInfoProvider: persisted-first, mock-fallback.

The onboarding-editable profile layer. `get_profile`:

  1. Persisted — if the user filled in / edited their profile in the UI, it was
     upserted to PG (source="user"); that stored picture wins.
  2. Mock fallback — otherwise the deterministic mock synthesizes a picture
     (named persona or hash-derived), exactly as before (source="mock").

The persisted lookup is injected as an async callable (str id → profile dict | None)
so this adapter stays free of any store/PG import — build_context wires it to
PostgresStore.get_user_profile.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.user import UserProfile

from .user_info_mock import MockUserInfoProvider


class PersistedThenMockUserInfoProvider:
    """Satisfies the UserInfoProvider protocol: a persisted picture when present,
    else the mock synthesis. Always returns a UserProfile."""

    def __init__(
        self,
        persisted_lookup: Callable[[str], Awaitable[dict[str, Any] | None]],
        mock: MockUserInfoProvider,
    ) -> None:
        self._persisted_lookup = persisted_lookup
        self._mock = mock

    async def get_profile(self, user_id: UserId) -> UserProfile:
        stored = await self._persisted_lookup(str(user_id))
        if stored is not None:
            # Validate back into the domain object (computed fields recomputed; the
            # persisted source="user" is carried through).
            return UserProfile.model_validate(stored)
        return await self._mock.get_profile(user_id)
