from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
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


class MergeEnvContractTests(unittest.TestCase):
    def test_secret_wins_and_provider_is_pinned_without_value_output(self) -> None:
        merge_env = load_script("merge_env.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            generated = root / "generated.env"
            secret = root / "secret.env"
            destination = root / ".env"
            generated.write_text("A=generated\nOPENROUTER_API_KEY=\n", encoding="utf-8")
            secret.write_text("A=secret\nOPENROUTER_API_KEY=synthetic-key\n", encoding="utf-8")

            summary = merge_env.merge_env(generated, secret, destination)

            content = destination.read_text(encoding="utf-8")
            self.assertIn("A=secret\n", content)
            self.assertIn("OPENROUTER_API_KEY=synthetic-key\n", content)
            self.assertEqual(
                content.count("PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai\n"), 1
            )
            self.assertNotIn("synthetic-key", summary)
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)


class MaterialProjectionTests(unittest.TestCase):
    def test_caption_and_query_live_in_context_without_mutating_source_text(self) -> None:
        material = load_script("to_material.py")
        message = {
            "speaker": "Ada",
            "text": "Exact source text.",
            "images": [],
            "blip_caption": "a diagram with a red arrow",
            "query": "red arrow diagram",
        }

        lines = material.message_lines(message)
        media = material.media_lines([message])

        self.assertEqual(lines, ["Ada: Exact source text."])
        self.assertTrue(any("kind=caption" in line and "a diagram" in line for line in media))
        self.assertTrue(any("kind=query" in line and "red arrow" in line for line in media))
        self.assertEqual(material.expected_turn(message), ("Ada", "Exact source text."))

    def test_source_text_with_an_internal_blank_line_is_exact(self) -> None:
        material = load_script("to_material.py")
        app_path = ROOT / "app-01" / "app.py"
        split_frontmatter, parse_turns = material.framework_parser(app_path)
        message = {"speaker": "Ada", "text": "first\n\nthird", "images": []}
        session = {
            "session_index": 1,
            "date_time": "1:00 pm on 8 May, 2023",
            "messages": [message],
        }
        conversation = {
            "conversation_idx": 0,
            "speaker_a": "Ada",
            "speaker_b": "Grace",
            "sessions": [session],
        }
        text = material.render(conversation, session)
        material.verify(text, conversation, session, split_frontmatter, parse_turns)
        _frontmatter, body = split_frontmatter(text)
        self.assertEqual(parse_turns(body)[1], ("Ada", "first\n\nthird"))

    def test_parser_round_trip_uses_real_generated_functions(self) -> None:
        material = load_script("to_material.py")
        app_path = ROOT / "app-01" / "app.py"
        split_frontmatter, parse_turns = material.framework_parser(app_path)
        message = {
            "speaker": "Ada Lovelace",
            "text": "First line",
            "images": ["https://example.invalid/a.png"],
            "blip_caption": "caption",
            "query": "query",
        }
        session = {"session_index": 1, "date_time": "1:00 pm on 8 May, 2023", "messages": [message]}
        conversation = {
            "conversation_idx": 0,
            "speaker_a": "Ada Lovelace",
            "speaker_b": "Grace Hopper",
            "sessions": [session],
        }

        text = material.render(conversation, session)
        material.verify(text, conversation, session, split_frontmatter, parse_turns)


class ShellSafetyTests(unittest.TestCase):
    def test_build_script_has_required_guards_and_no_forbidden_docker_commands(self) -> None:
        script = (ROOT / "scripts" / "01-build.sh").read_text(encoding="utf-8")
        self.assertIn("freeze_guard.py verify --phase 1", script)
        self.assertIn("PNEUMA_APP_COMPOSE_PROJECT=pneuma-lcr2609-", script)
        self.assertIn("LCR2609 byte-exact blank-continuation compatibility", script)
        self.assertIn("POOL=2", script)
        self.assertIn('UV_PROJECT_ENVIRONMENT="$ROOT/.runtime/framework-venv"', script)
        self.assertIn("evolve step --policy adopt-clean", script)
        self.assertNotIn("docker system prune", script)
        self.assertNotIn("docker network prune", script)
        self.assertNotIn("down --volumes", script)
        self.assertNotIn("docker rm", script)
        self.assertNotIn("docker stop", script)


class SetupContractTests(unittest.TestCase):
    def test_project_identity_is_prefix_scoped(self) -> None:
        setup = load_script("00-setup.py")
        self.assertEqual(setup.project_name(1), "lcr2609-01")
        self.assertEqual(setup.user_id(10), "u-lcr2609-10")
        self.assertEqual(setup.compose_prefix(3), "pneuma-lcr2609-03-")

    def test_profile_is_honest_about_unknown_timezone(self) -> None:
        setup = load_script("00-setup.py")
        profile = setup.render_profile(2, "Jon", "Gina")
        self.assertIn('display_name: "Jon and Gina conversation"', profile)
        self.assertIn('timezone: "UTC"', profile)
        self.assertIn("timezone: deployment_default", profile)
        self.assertIn("language: deployment_default", profile)

    def test_generated_parser_patch_is_deterministic_and_preserves_blank_lines(self) -> None:
        setup = load_script("00-setup.py")
        original = """def parse_conversation_turns(body: str):
    turns = []
    for line in body.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
"""
        patched = setup.patch_parser_source(original)
        self.assertIn(setup.PARSER_PATCH_MARKER, patched)
        self.assertEqual(setup.patch_parser_source(patched), patched)


class FreezeGuardTests(unittest.TestCase):
    def test_verification_detects_a_changed_file(self) -> None:
        freeze = load_script("freeze_guard.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact = root / "artifact.txt"
            artifact.write_text("frozen\n", encoding="utf-8")
            frozen = root / "FROZEN.md"
            freeze.write_phase(frozen, root, 1, [artifact])
            freeze.verify_phase(frozen, root, 1)
            artifact.write_text("changed\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                freeze.verify_phase(frozen, root, 1)


class BudgetTests(unittest.TestCase):
    def test_compile_usage_and_projection_are_conservative(self) -> None:
        budget = load_script("budget.py")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "build.log"
            log.write_text(
                "Compile-model tokens: input=1000000 output=100000 total=1100000\n",
                encoding="utf-8",
            )
            usage = budget.collect_compile_usage(root)
            summary = budget.summarize(usage, answered_usage={}, completed=5, total=10)
            self.assertEqual(usage["input_tokens"], 1_000_000)
            self.assertAlmostEqual(summary["observed_usd"], 0.32)
            self.assertAlmostEqual(summary["projected_usd"], 0.64)


if __name__ == "__main__":
    unittest.main()
