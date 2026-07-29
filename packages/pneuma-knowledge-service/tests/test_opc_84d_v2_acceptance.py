from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "examples" / "accept_opc_84d_v2_group.py"


def _load_acceptor():
    spec = importlib.util.spec_from_file_location("opc_84d_v2_acceptor", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, verdict: str = "PASS") -> dict[str, Path]:
    paths = {
        "group": tmp_path / "G01.json",
        "report": tmp_path / "deterministic.json",
        "review": tmp_path / "review.md",
        "beats": tmp_path / "daily-beats.json",
        "schema": tmp_path / "group.schema.json",
        "rubric": tmp_path / "qa-rubric.md",
        "story": tmp_path / "story-bible.md",
        "accepted": tmp_path / "accepted",
        "evidence": tmp_path / "qa-accepted",
    }
    paths["group"].write_bytes(
        b'{\n  "group_id": "G01",\n  "body": "original bytes"\n}\n'
    )
    paths["beats"].write_text('{"days":[]}\n', encoding="utf-8")
    paths["schema"].write_text('{"type":"object"}\n', encoding="utf-8")
    paths["rubric"].write_text("# rubric\n", encoding="utf-8")
    paths["story"].write_text("# story\n", encoding="utf-8")
    report = {
        "status": "structural_pass",
        "findings": [],
        "detector": {
            "version": "opc-84d-v2-deterministic/3",
        },
        "input_hashes": {
            str(paths["group"]): _sha(paths["group"]),
            str(paths["beats"]): _sha(paths["beats"]),
        },
        "schema_hash": _sha(paths["schema"]),
        "groups": [{"group_id": "G01", "findings": []}],
    }
    paths["report"].write_text(json.dumps(report), encoding="utf-8")
    paths["review"].write_text(
        "\n".join(
            [
                "# G01 independent review",
                "",
                f"- 结论：**{verdict}**",
                "- 复审时间：2026-07-29T03:02:17Z",
                "- 复审者：Codex `reviewer-a`（非 G01 作者）",
                "",
                "| 输入 | SHA-256 |",
                "|---|---|",
                f"| `groups/G01.json` | `{_sha(paths['group'])}` |",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return paths


def _accept(module, paths: dict[str, Path]):
    return module.accept_group(
        group_path=paths["group"],
        report_path=paths["report"],
        review_path=paths["review"],
        beats_path=paths["beats"],
        schema_path=paths["schema"],
        rubric_path=paths["rubric"],
        story_path=paths["story"],
        accepted_dir=paths["accepted"],
        evidence_dir=paths["evidence"],
    )


def _write_g11_v3_shaped_review(paths: dict[str, Path]) -> None:
    paths["review"].write_text(
        "\n".join(
            [
                "# G01 independent content review — revision 3",
                "",
                "## Verdict: **PASS**",
                "",
                "- Reviewer: Codex / `reviewer-a`",
                "- Independence: non-author; I did not author or revise G01 source text",
                "- Reviewed at: `2026-07-29T03:18:04Z`",
                "",
                "## Current hashes",
                "",
                "| Input | SHA-256 |",
                "| --- | --- |",
                f"| `groups/G01.json` | `{_sha(paths['group'])}` |",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _write_g20_v3_shaped_review(paths: dict[str, Path]) -> None:
    paths["review"].write_text(
        "\n".join(
            [
                "# G01 third-round minimal review — PASS",
                "",
                "- Reviewer: Codex `reviewer-a`",
                "- Reviewer role: **non-author independent reviewer**",
                "- Reviewed at (UTC): `2026-07-29T03:49:07Z`",
                "- Repository SHA: `05f5ac3759e0393274c6ebdf01a4fba53b0d5dde`",
                "- Decision: **PASS**",
                "",
                "## Current hashes",
                "",
                "| Input | SHA-256 |",
                "| --- | --- |",
                f"| `groups/G01.json` | `{_sha(paths['group'])}` |",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_acceptance_accepts_g20_v3_decision_review_shape(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _write_g20_v3_shaped_review(paths)
    module = _load_acceptor()

    evidence = _accept(module, paths)

    assert evidence["status"] == "accepted"
    assert evidence["review"]["verdict"] == "PASS"
    assert evidence["review"]["reviewer"] == "Codex `reviewer-a`"
    assert evidence["review"]["reviewed_at"] == "2026-07-29T03:49:07Z"
    assert evidence["review"]["non_author_evidence"] == "non-author"


def test_acceptance_rejects_decision_pass_in_prose_not_metadata(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    _write_g20_v3_shaped_review(paths)
    review = paths["review"].read_text(encoding="utf-8")
    paths["review"].write_text(
        review.replace(
            "- Decision: **PASS**",
            "The review narrative happens to say Decision: **PASS**.",
        ),
        encoding="utf-8",
    )
    module = _load_acceptor()

    with pytest.raises(module.AcceptanceError, match="verdict metadata"):
        _accept(module, paths)
    assert not (paths["accepted"] / "G01.json").exists()


def test_acceptance_accepts_g11_v3_english_review_shape(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _write_g11_v3_shaped_review(paths)
    module = _load_acceptor()

    evidence = _accept(module, paths)

    assert evidence["status"] == "accepted"
    assert evidence["review"]["verdict"] == "PASS"
    assert evidence["review"]["reviewer"] == "Codex / `reviewer-a`"
    assert evidence["review"]["non_author_attested"] is True


def test_acceptance_rejects_incidental_pass_in_review_body(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    _write_g11_v3_shaped_review(paths)
    review = paths["review"].read_text(encoding="utf-8")
    paths["review"].write_text(
        review.replace(
            "## Verdict: **PASS**",
            "## Notes\n\nThe word PASS appears here only as prose.",
        ),
        encoding="utf-8",
    )
    module = _load_acceptor()

    with pytest.raises(module.AcceptanceError, match="verdict metadata"):
        _accept(module, paths)
    assert not (paths["accepted"] / "G01.json").exists()


def test_acceptance_rejects_stale_deterministic_report(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    paths["group"].write_bytes(paths["group"].read_bytes() + b"\n")
    module = _load_acceptor()
    with pytest.raises(module.AcceptanceError, match="deterministic input hash"):
        _accept(module, paths)
    assert not (paths["accepted"] / "G01.json").exists()


def test_acceptance_rejects_an_obsolete_deterministic_detector(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    report = json.loads(paths["report"].read_text(encoding="utf-8"))
    report["detector"]["version"] = "opc-84d-v2-deterministic/2"
    paths["report"].write_text(json.dumps(report), encoding="utf-8")
    module = _load_acceptor()

    with pytest.raises(module.AcceptanceError, match="detector version"):
        _accept(module, paths)

    assert not (paths["accepted"] / "G01.json").exists()


def test_acceptance_rejects_return_review(tmp_path: Path) -> None:
    paths = _fixture(tmp_path, verdict="RETURN")
    module = _load_acceptor()
    with pytest.raises(module.AcceptanceError, match="review verdict"):
        _accept(module, paths)


def test_acceptance_rejects_review_group_hash_mismatch(tmp_path: Path) -> None:
    paths = _fixture(tmp_path)
    review = paths["review"].read_text(encoding="utf-8")
    paths["review"].write_text(
        review.replace(_sha(paths["group"]), "0" * 64),
        encoding="utf-8",
    )
    module = _load_acceptor()
    with pytest.raises(module.AcceptanceError, match="review group hash"):
        _accept(module, paths)


def test_acceptance_atomically_copies_original_bytes_and_writes_evidence(
    tmp_path: Path,
) -> None:
    paths = _fixture(tmp_path)
    original = paths["group"].read_bytes()
    module = _load_acceptor()
    evidence = _accept(module, paths)
    accepted_path = paths["accepted"] / "G01.json"
    evidence_path = paths["evidence"] / "G01.json"
    assert accepted_path.read_bytes() == original
    assert json.loads(evidence_path.read_text(encoding="utf-8")) == evidence
    assert evidence["status"] == "accepted"
    assert evidence["group_sha256"] == hashlib.sha256(original).hexdigest()
    assert evidence["review"]["reviewer"].startswith("Codex")
    assert evidence["review"]["non_author_attested"] is True
