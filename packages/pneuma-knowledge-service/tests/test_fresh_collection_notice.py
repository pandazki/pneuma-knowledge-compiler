"""A vector collection that had to be created says so — the one failure that was silent.

Renaming the collection (or upgrading into a build that reads a different setting for its
name) leaves every answer working and every vector unreachable. Nothing raises, because an
empty index is a legitimate state, so the only mechanism available is saying it once."""

from pneuma_knowledge_service.embedding_key import (
    COLLECTION_SETTING,
    fresh_collection_notice,
)
from pneuma_knowledge_service.wiring import warn_fresh_collection


def test_the_notice_names_the_collection_the_setting_and_what_stops_working():
    notice = fresh_collection_notice("demo_chunks")
    assert "demo_chunks" in notice
    assert COLLECTION_SETTING in notice
    assert "PNEUMA_APP_QDRANT_COLLECTION" in notice  # the scaffold's own spelling
    assert "rebuild_derived" in notice  # what to run, not only what broke


def test_it_is_warned_once_per_collection(caplog):
    warn_fresh_collection("spoken_once")
    caplog.clear()
    with caplog.at_level("WARNING"):
        warn_fresh_collection("spoken_once")
    assert not [r for r in caplog.records if "spoken_once" in r.getMessage()]
    caplog.clear()
    with caplog.at_level("WARNING"):
        returned = warn_fresh_collection("spoken_twice")
    said = [r for r in caplog.records if "spoken_twice" in r.getMessage()]
    assert len(said) == 1
    assert returned == said[0].getMessage()  # the caller may print the same text


async def test_ensure_collection_reports_whether_it_created_one(monkeypatch):
    """The adapter's own half: found → False, created → True. It is the only party that
    knows, and the caller cannot ask afterwards without a second round trip."""
    from pneuma_knowledge_service.adapters import qdrant as mod

    created: list[str] = []

    class FakeClient:
        def __init__(self, exists: bool) -> None:
            self._exists = exists

        async def collection_exists(self, name):
            return self._exists

        async def get_collection(self, name):
            class Vectors:
                size = 1536

            class Params:
                vectors = Vectors()

            class Config:
                params = Params()

            class Info:
                config = Config()

            return Info()

        async def create_collection(self, name, vectors_config=None):
            created.append(name)

        async def create_payload_index(self, *a, **kw):
            return None

    index = mod.QdrantVectorIndex.__new__(mod.QdrantVectorIndex)
    index._collection, index._dim, index._upsert_batch = "kb_chunks", 1536, 64

    index._client = FakeClient(exists=True)
    assert await index.ensure_collection() is False
    assert created == []

    index._client = FakeClient(exists=False)
    assert await index.ensure_collection() is True
    assert created == ["kb_chunks"]
