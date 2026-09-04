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


class OriginalRunGuardTests(unittest.TestCase):
    def test_detects_any_baseline_artifact_change(self) -> None:
        guard = load_script("verify_original_run.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "protected.txt"
            target.write_text("baseline\n", encoding="utf-8")
            digest = guard.sha256_path(target)
            self.assertEqual(guard.verify(root, {"protected.txt": digest}), 1)
            target.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                guard.verify(root, {"protected.txt": digest})


class ParallelAnswerTests(unittest.TestCase):
    def test_worker_allocation_is_ten_projects_and_exactly_32(self) -> None:
        runner = load_script("rerun_answer_runner.py")
        self.assertEqual(set(runner.WORKERS), {f"{number:02d}" for number in range(1, 11)})
        self.assertEqual(sum(runner.WORKERS.values()), 32)
        self.assertGreaterEqual(min(runner.WORKERS.values()), 3)

    def test_command_keeps_frozen_answer_flags_on_fast_lane(self) -> None:
        runner = load_script("rerun_answer_runner.py")
        command = runner.build_ask_command("unchanged question")
        self.assertEqual(command[0:3], ["./app.py", "ask", "unchanged question"])
        self.assertIn("concise", command)
        self.assertIn("select", command)
        self.assertIn("structured", command)
        self.assertNotIn("--deep", command)
        self.assertNotIn("--include-original", command)

    def test_atomic_records_resume_only_new_line_and_assemble_in_projection_order(self) -> None:
        runner = load_script("rerun_answer_runner.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = root / "records"
            rows = [("q2", "second?"), ("q1", "first?")]
            runner.write_record_atomic(
                records,
                {
                    "qa_id": "q1",
                    "predicted_answer": "one",
                    "token_usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                },
            )
            loaded = runner.load_records(records, {"q1", "q2"})
            self.assertEqual(set(loaded), {"q1"})
            output = root / "app-01.jsonl"
            with self.assertRaises(ValueError):
                runner.assemble_app_answers(rows, loaded, output)
            runner.write_record_atomic(
                records,
                {
                    "qa_id": "q2",
                    "predicted_answer": "two",
                    "token_usage": {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
                },
            )
            loaded = runner.load_records(records, {"q1", "q2"})
            runner.assemble_app_answers(rows, loaded, output)
            assembled = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertEqual([row["qa_id"] for row in assembled], ["q2", "q1"])

    def test_rate_limit_retries_with_exponential_backoff(self) -> None:
        runner = load_script("rerun_answer_runner.py")
        attempts: list[int] = []
        delays: list[int] = []

        def flaky(_question: str):
            attempts.append(1)
            if len(attempts) < 3:
                raise runner.AskError("rate_limit")
            return runner.ParsedResult(
                "value", {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}
            )

        record = runner.answer_with_retry(
            "q1", "question", ask_fn=flaky, sleep_fn=delays.append
        )
        self.assertEqual(record["predicted_answer"], "value")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(delays, [15, 30])


class RerunCostTests(unittest.TestCase):
    def test_cost_scans_only_atomic_rerun_records(self) -> None:
        cost = load_script("rerun_cost.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            record_dir = root / "records" / "app-01"
            record_dir.mkdir(parents=True)
            (record_dir / "one.json").write_text(
                json.dumps(
                    {
                        "qa_id": "q1",
                        "predicted_answer": "x",
                        "token_usage": {
                            "input_tokens": 1_000_000,
                            "output_tokens": 1_000_000,
                            "total_tokens": 2_000_000,
                        },
                    }
                ),
                encoding="utf-8",
            )
            summary = cost.summarize(root, expected=2)
            self.assertEqual(summary["completed_answers"], 1)
            self.assertEqual(summary["observed_usd"], 1.4)
            self.assertEqual(summary["projected_usd"], 2.8)


class RerunComparisonTests(unittest.TestCase):
    def test_pairs_sanitized_rows_and_reports_score_transitions(self) -> None:
        comparison = load_script("rerun_comparison.py")
        baseline = [
            {
                "qa_id": "q1",
                "predicted_answer": "a longer baseline",
                "llm_score": 0.0,
                "category": 1,
                "is_multi_modality": False,
            },
            {
                "qa_id": "q2",
                "predicted_answer": "same",
                "llm_score": 1.0,
                "category": 2,
                "is_multi_modality": True,
            },
        ]
        rerun = [
            {
                "qa_id": "q1",
                "predicted_answer": "short",
                "llm_score": 1.0,
                "category": 1,
                "is_multi_modality": False,
            },
            {
                "qa_id": "q2",
                "predicted_answer": "same",
                "llm_score": 0.0,
                "category": 2,
                "is_multi_modality": True,
            },
        ]
        payload = comparison.build_comparison(baseline, rerun)
        self.assertEqual(
            payload["llm_score_transitions"],
            {"0_to_0": 0, "0_to_1": 1, "1_to_0": 1, "1_to_1": 0},
        )
        self.assertEqual(payload["prediction_text"]["changed_count"], 1)
        self.assertEqual(payload["prediction_text"]["identical_count"], 1)
        self.assertEqual(
            payload["identical_prediction_llm_score_transitions"],
            {"0_to_0": 0, "0_to_1": 0, "1_to_0": 1, "1_to_1": 0},
        )
        self.assertEqual(payload["by_category"]["1"]["0_to_1"], 1)
        self.assertEqual(payload["by_modality"]["multimodal_available"]["1_to_0"], 1)


class RerunShellContractTests(unittest.TestCase):
    def test_shells_isolate_outputs_pin_32_and_reuse_frozen_scorer(self) -> None:
        answer = (ROOT / "scripts" / "04-rerun-answer.sh").read_text(encoding="utf-8")
        score = (ROOT / "scripts" / "05-rerun-score.sh").read_text(encoding="utf-8")
        down = (ROOT / "scripts" / "06-rerun-down.sh").read_text(encoding="utf-8")
        self.assertIn("answers-2026-09-04", answer)
        self.assertIn("WORKERS_01=4", answer)
        self.assertIn("WORKERS_10=3", answer)
        self.assertIn("verify_original_run.py", answer)
        self.assertNotIn('"$ROOT/outputs/answers"', answer)
        self.assertIn("2026-09-04-capability-guidance", score)
        self.assertIn("run_official_score.py", score)
        self.assertIn("sanitize_results.py", score)
        self.assertIn("verify_original_run.py", score)
        self.assertIn("app.py down", down)
        self.assertNotIn("docker system", answer + score + down)
        self.assertNotIn("down -v", answer + score + down)


if __name__ == "__main__":
    unittest.main()
