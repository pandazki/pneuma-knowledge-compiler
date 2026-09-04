"""What a Meilisearch error is allowed to MEAN on the read path.

`except MeilisearchApiError: return []` reads an expired key, a refused connection or a 500
as "this user has nothing indexed". The lane goes quiet, the answer is assembled as if the
library held no lexical material, and nothing anywhere says so — the one failure mode a
citation-backed system must not have silently. Absence has exactly one code
(`index_not_found`); everything else is a real failure and propagates.
"""

from __future__ import annotations

import httpx
import pytest
from meilisearch_python_sdk.errors import MeilisearchApiError
from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.meilisearch import (
    _BLOCK_SETTINGS,
    MeiliLexicalIndex,
)

USER = UserId("u-meili-errors")


def _api_error(code: str, *, status: int = 400) -> MeilisearchApiError:
    """A real `MeilisearchApiError`, built the way the client builds one: from a response."""
    response = httpx.Response(
        status,
        json={"message": f"{code} happened", "code": code, "type": "auth", "link": ""},
        request=httpx.Request("GET", "http://meili.invalid/indexes/x"),
    )
    return MeilisearchApiError(code, response)


class _FailingIndex:
    def __init__(self, error: Exception) -> None:
        self._error = error

    async def fetch_info(self):
        raise self._error

    async def search(self, *args, **kwargs):
        raise self._error


class _FakeClient:
    """Only what the read path touches; every call is the one error under test."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def index(self, uid: str) -> _FailingIndex:
        return _FailingIndex(self.error)


def _index(error: Exception) -> MeiliLexicalIndex:
    store = MeiliLexicalIndex("http://meili.invalid", "")
    store._client = _FakeClient(error)  # type: ignore[assignment]
    return store


async def test_configure_for_read_propagates_non_not_found_meili_errors():
    store = _index(_api_error("invalid_api_key", status=403))
    with pytest.raises(MeilisearchApiError) as excinfo:
        await store._configure_for_read("blocks_u", _BLOCK_SETTINGS)
    assert excinfo.value.code == "invalid_api_key"


async def test_only_index_not_found_reads_as_absence():
    store = _index(_api_error("index_not_found", status=404))
    assert await store._configure_for_read("blocks_u", _BLOCK_SETTINGS) is False
    # …and a user with no index still gets the honest empty answer, not an exception.
    assert await store.search(USER, "aurora") == []
    assert await store.search_claims(USER, "aurora") == []


async def test_a_search_over_a_configured_index_propagates_a_real_failure():
    store = _index(_api_error("internal", status=500))
    # Pretend the index was configured earlier this process, so the search itself is what
    # raises — the second swallow, on the other side of `_configure_for_read`.
    store._configured.add("blocks_u-meili-errors")
    store._configured.add("claims_u-meili-errors")
    with pytest.raises(MeilisearchApiError):
        await store.search(USER, "aurora")
    with pytest.raises(MeilisearchApiError):
        await store.search_claims(USER, "aurora")
