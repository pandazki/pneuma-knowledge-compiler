from pneuma_knowledge_service.experiments.opc_84d_evaluation import (
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
