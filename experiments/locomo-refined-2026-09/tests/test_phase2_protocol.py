from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    path = ROOT / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.removesuffix(".py"), path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class QuestionProjectionTests(unittest.TestCase):
    def test_selective_projection_never_materializes_gold_values(self) -> None:
        projection = load_script("project_questions.py")
        raw = json.dumps(
            {
                "qa_id": "conv-x#q0001",
                "conversation_idx": 4,
                "question": "When was it?",
                "answer": ["FORBIDDEN-SENTINEL"],
                "evidence_messages": [{"text": "NESTED-FORBIDDEN"}],
                "category": "FORBIDDEN-CATEGORY",
            }
        )
        projected = projection.project_record(raw)
        self.assertEqual(
            projected,
            {
                "qa_id": "conv-x#q0001",
                "conversation_idx": 4,
                "question": "When was it?",
            },
        )
        self.assertNotIn("FORBIDDEN", json.dumps(projected))


class AnswerParsingTests(unittest.TestCase):
    def test_parses_multiline_answer_usage_and_removes_only_citations(self) -> None:
        runner = load_script("answer_runner.py")
        stdout = """\nQ: hidden question\nA: 7 May 2023 [cite: s01 ¶2-3]\nand morning. [cite: s02 ¶4]\n  (1.2s, 8→2 claims / 3→1 source windows, tokens {'input_tokens': 120, 'output_tokens': 8, 'total_tokens': 128})\n  stages: total=1.2s\n"""
        parsed = runner.parse_result(stdout)
        self.assertEqual(parsed.answer, "7 May 2023\nand morning.")
        self.assertEqual(parsed.token_usage["total_tokens"], 128)

    def test_missing_usage_is_a_hard_parse_failure(self) -> None:
        runner = load_script("answer_runner.py")
        with self.assertRaises(ValueError):
            runner.parse_result("A: an answer\n")


class AssemblyTests(unittest.TestCase):
    def test_predictions_are_complete_ordered_and_field_minimal(self) -> None:
        assembly = load_script("assemble_predictions.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            projected = root / "projected.jsonl"
            answers = root / "answers"
            answers.mkdir()
            output = root / "predictions.jsonl"
            projected.write_text(
                '{"qa_id":"q1","conversation_idx":0,"question":"x"}\n'
                '{"qa_id":"q2","conversation_idx":1,"question":"y"}\n',
                encoding="utf-8",
            )
            (answers / "app-02.jsonl").write_text(
                '{"qa_id":"q2","predicted_answer":"two","token_usage":{"total_tokens":1}}\n',
                encoding="utf-8",
            )
            (answers / "app-01.jsonl").write_text(
                '{"qa_id":"q1","predicted_answer":"one","token_usage":{"total_tokens":1}}\n',
                encoding="utf-8",
            )
            summary = assembly.assemble(projected, answers, output, expected=2)
            rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["qa_id"] for row in rows], ["q1", "q2"])
            self.assertTrue(all(set(row) == {"qa_id", "predicted_answer"} for row in rows))
            self.assertEqual(summary["empty"], 0)


class SanitizerTests(unittest.TestCase):
    def test_gold_fields_are_absent_and_burned_score_is_separate(self) -> None:
        sanitizer = load_script("sanitize_results.py")
        rows = [
            {
                "qa_id": "burned",
                "question": "secret",
                "answer": ["gold"],
                "evidence": ["x"],
                "evidence_messages": [{"text": "secret"}],
                "matched_answer": "gold",
                "predicted_answer": "p",
                "llm_score": 0.0,
                "f1_score": 0.1,
                "bleu_score": 0.05,
            },
            {
                "qa_id": "clean",
                "question": "secret",
                "answer": ["gold"],
                "predicted_answer": "p",
                "llm_score": 1.0,
                "f1_score": 0.9,
                "bleu_score": 0.8,
            },
        ]
        safe, summary = sanitizer.sanitize(rows, {"burned"})
        serialized = json.dumps(safe)
        for forbidden in sanitizer.FORBIDDEN_KEYS:
            self.assertNotIn(f'"{forbidden}"', serialized)
        self.assertEqual(summary["official_llm_score_pct"], 50.0)
        self.assertEqual(summary["unburned_llm_score_pct"], 100.0)


class ShellProtocolTests(unittest.TestCase):
    def test_answer_and_score_shells_pin_the_frozen_protocol(self) -> None:
        answer = (ROOT / "scripts" / "02-answer.sh").read_text(encoding="utf-8")
        score = (ROOT / "scripts" / "03-score.sh").read_text(encoding="utf-8")
        self.assertIn("POOL=2", answer)
        self.assertIn('UV_PROJECT_ENVIRONMENT="$ROOT/.runtime/framework-venv"', answer)
        self.assertIn("--style concise", answer)
        self.assertIn("--evidence-strategy select", answer)
        self.assertIn("--answer-format structured", answer)
        self.assertNotIn("--include-original", answer)
        self.assertIn("freeze_guard.py verify --phase 1", answer)
        self.assertIn("freeze_guard.py verify --phase 2", answer)
        self.assertIn("freeze_guard.py verify --phase 1", score)
        self.assertIn("freeze_guard.py verify --phase 2", score)
        self.assertIn("sanitize_results.py", score)
        self.assertIn("run_official_score.py", score)
        self.assertIn("setup_evaluator.py", score)

        launcher = (ROOT / "scripts" / "run_official_score.py").read_text(encoding="utf-8")
        self.assertIn('"qwen/qwen3-14b"', launcher)
        self.assertIn('"--concurrency",\n                "64"', launcher)


if __name__ == "__main__":
    unittest.main()
