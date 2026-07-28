from pneuma_knowledge_service.experiments.opc_84d_evaluation import (
    canonical_quality,
    char_similarity,
    guarded_statement,
    truth_entries,
)


def test_character_similarity_handles_punctuation_and_wrapping_context():
    truth = "客户原始附件不离开本地试点环境。"
    claim = "【强】约束：客户原始附件不离开本地试点环境（Cedar 试点）。"
    assert char_similarity(truth, claim) >= 0.8


def test_guarded_statement_distinguishes_rejected_history_from_active_claim():
    rejected = "旧设想（已失效）：把实时转写和会议摘要作为首页唯一入口。"
    active = "当前决定：把实时转写和会议摘要作为首页唯一入口。"
    assert guarded_statement(rejected) is True
    assert guarded_statement(active) is False


def test_truth_entries_attach_category_and_filter_current_status():
    manifest = {
        "truth": {
            "durable_facts": [
                {"truth_id": "f1", "value": "事实", "status": "current"}
            ],
            "decisions": [
                {"truth_id": "d1", "value": "旧决定", "status": "superseded"},
                {"truth_id": "d2", "value": "新决定", "status": "current"},
            ],
            "commitments": [],
            "constraints": [],
        }
    }
    rows = truth_entries(manifest)
    assert [(row["truth_id"], row["category"]) for row in rows] == [
        ("f1", "durable_facts"),
        ("d1", "decisions"),
        ("d2", "decisions"),
    ]
    assert [row["truth_id"] for row in truth_entries(manifest, current_only=True)] == [
        "f1",
        "d2",
    ]


def test_canonical_quality_reports_duplicate_and_provenance_debt():
    claims = [
        {
            "document_path": "a.md",
            "anchor": "a1",
            "section_path": ["行动项"],
            "text": "周五前交付。",
            "citations": [{"source_id": "s1"}],
        },
        {
            "document_path": "b.md",
            "anchor": "b1",
            "section_path": ["## 行动项"],
            "text": "周五前交付！",
            "citations": [],
        },
        {
            "document_path": "b.md",
            "anchor": "b2",
            "section_path": ["记录"],
            "text": "残留 [cite: s2 ¶0-¶1]",
            "citations": [],
        },
    ]
    quality = canonical_quality(claims)
    assert quality["exact_duplicate_groups"] == 1
    assert quality["duplicate_rows_excess"] == 1
    assert quality["claims_without_citations"] == 2
    assert quality["citation_marker_residue"] == 1
    assert quality["section_components_with_heading_marker"] == 1
    assert quality["claims_per_document"] == {"a.md": 1, "b.md": 2}
