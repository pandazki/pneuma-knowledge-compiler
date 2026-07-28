"""build_dataset: canonical + PG audit → the M2 four-view shape (M3b), over fakes."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from pneuma_knowledge_core.domain.canonical import CanonicalDocument
from pneuma_knowledge_core.domain.ids import DocumentId, UserId, SourceId
from pneuma_knowledge_core.domain.snapshot import SnapshotRef
from pneuma_knowledge_core.domain.source import RawSource
from pneuma_knowledge_service.dataset import build_dataset

USER = UserId("u-it-ds")
TS = datetime(2026, 7, 20, 9, 0, tzinfo=timezone.utc)

CHENG_YE = CanonicalDocument(
    pneuma_id=DocumentId("doc-cheng-ye"),
    path="memory/people/cheng-ye.md",
    frontmatter={"pneuma_id": "doc-cheng-ye", "type": "person", "slug": "cheng-ye"},
    body=(
        "## 程野\n\n"
        "- 程野 是后端负责人。[cite: src-01 ¶3] <!-- c:aa11 -->\n"
        "- 详见 [Q3 主题](../topics/q3-launch.md)。 <!-- c:bb22 -->"
    ),
)
Q3 = CanonicalDocument(
    pneuma_id=DocumentId("doc-q3"),
    path="memory/topics/q3-launch.md",
    frontmatter={"pneuma_id": "doc-q3", "type": "topic", "slug": "q3-launch"},
    body="## 承诺\n\n- 下周交付演示稿。[cite: src-01 ¶4] <!-- c:cc33 -->",
)


class _FakeCanonical:
    async def list(self, user_id, *, at: SnapshotRef | None = None):
        return [CHENG_YE, Q3]

    async def read_meta(self, user_id, path):
        return None  # no persisted skill manifest → base version falls to settings default


class _FakeStore:
    async def list(self, user_id):
        return [
            RawSource(
                source_id=SourceId("src-01"),
                user_id=USER,
                kind="conversation",
                source_class="workstream",
                title="契约会议",
                mime="text/plain",
                checksum="k1",
                created_at=TS,
            )
        ]

    async def list_jobs(self, user_id):
        return [
            {
                "job_id": "job-1",
                "kind": "compile",
                "payload": {"source_ids": ["src-01"]},
                "status": "done",
                "created_at": TS,
                "claimed_at": TS,
                "completed_at": TS,
                "ok": True,
                "detail": None,
                "snapshot_ref": "sha-1",
            }
        ]

    async def list_compile_events(self, user_id):
        return [
            {"job_id": "job-1", "seq": 0, "snapshot_ref": "sha-1", "type": "claim_added",
             "path": "memory/people/cheng-ye.md", "anchor": "aa11", "before": None,
             "after": "- 程野 是后端负责人。", "created_at": TS},
            {"job_id": "job-1", "seq": 1, "snapshot_ref": "sha-1", "type": "claim_added",
             "path": "memory/people/cheng-ye.md", "anchor": "bb22", "before": None,
             "after": "- 详见 …", "created_at": TS},
            {"job_id": "job-1", "seq": 2, "snapshot_ref": "sha-1", "type": "claim_added",
             "path": "memory/topics/q3-launch.md", "anchor": "cc33", "before": None,
             "after": "- 下周交付演示稿。", "created_at": TS},
        ]


def _ctx():
    return SimpleNamespace(
        canonical=_FakeCanonical(),
        store=_FakeStore(),
        settings=SimpleNamespace(
            llm_model="scripted:demo", user_schema_base_version="v3"
        ),
    )


async def test_documents_carry_claims_with_citations():
    ds = await build_dataset(_ctx(), USER)
    docs = {d["path"]: d for d in ds["documents"]["documents"]}
    assert set(docs) == {"memory/people/cheng-ye.md", "memory/topics/q3-launch.md"}
    cheng_ye = docs["memory/people/cheng-ye.md"]
    assert cheng_ye["document_id"] == "doc-cheng-ye"
    assert cheng_ye["title"] == "cheng-ye"
    anchors = {c["anchor"] for c in cheng_ye["claims"]}
    assert anchors == {"aa11", "bb22"}
    aa11 = next(c for c in cheng_ye["claims"] if c["anchor"] == "aa11")
    assert aa11["citations"][0]["source_id"] == "src-01"
    assert (aa11["citations"][0]["from"], aa11["citations"][0]["to"]) == (3, 3)


async def test_graph_has_doc_and_source_nodes_with_link_and_citation_edges():
    ds = await build_dataset(_ctx(), USER)
    g = ds["graph"]
    ids = {n["id"] for n in g["nodes"]}
    assert {"doc-cheng-ye", "doc-q3", "src:src-01"} <= ids
    edges = {(e["source"], e["target"], e["type"]) for e in g["edges"]}
    # inter-document markdown link cheng-ye -> q3
    assert ("doc-cheng-ye", "doc-q3", "link") in edges
    # citation edges doc -> source card
    assert ("doc-cheng-ye", "src:src-01", "relationship") in edges
    assert ("doc-q3", "src:src-01", "relationship") in edges


async def test_timeline_snapshots_jobs_and_patches():
    ds = await build_dataset(_ctx(), USER)
    tl = ds["timeline"]
    assert [s["source_id"] for s in tl["snapshots"]] == ["src-01"]
    assert tl["jobs"][0]["status"] == "compiled"
    assert tl["jobs"][0]["patch_id"] == "sha-1"
    assert len(tl["patches"]) == 1
    patch = tl["patches"][0]
    assert set(patch["changed_paths"]) == {
        "memory/people/cheng-ye.md",
        "memory/topics/q3-launch.md",
    }
    assert all(ch["change_type"] == "created" for ch in patch["documents"])
    assert len(patch["claims"]) == 3
    assert patch["sources_consumed"] == ["src-01"]


async def test_journal_has_events_and_a_commit_marker():
    ds = await build_dataset(_ctx(), USER)
    types = [e["type"] for e in ds["journal"]]
    assert types.count("claim_added") == 3
    assert "patch_committed" in types
    assert all(e["job_id"] == "job-1" for e in ds["journal"])


async def test_dataset_meta_carries_skill_declared_claim_labels():
    # The dataset top-level meta ships the effective skill's claim-prefix vocabulary
    # (v3 §5强/中/弱) so the dataset-driven views render badges without a second request.
    ds = await build_dataset(_ctx(), USER)
    labels = ds["claim_labels"]
    assert [x["label"] for x in labels] == ["强", "中", "弱"]
    assert [x["tier"] for x in labels] == ["solid", "outline", "muted"]
    assert all({"label", "name", "description", "tier"} <= x.keys() for x in labels)
