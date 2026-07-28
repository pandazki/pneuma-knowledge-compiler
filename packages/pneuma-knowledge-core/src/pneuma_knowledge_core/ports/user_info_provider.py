"""UserInfoProvider port — user_id → UserProfile (architecture.md §6).

The user picture is a core domain object (domain/user.py); user_id is its
unique key. v1 has a mock implementation (service adapters/user_info_mock.py)
that returns a rich picture for every id — named personas for known ids and a
deterministic, idempotent synthesis for any new id. There is therefore no "not
found": get_profile always returns a UserProfile.
"""

from __future__ import annotations

from typing import Protocol

from ..domain.ids import UserId
from ..domain.user import UserProfile


class UserInfoProvider(Protocol):
    async def get_profile(self, user_id: UserId) -> UserProfile: ...
