#!/usr/bin/env python3
"""Generate and configure the ten isolated experiment projects."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from merge_env import merge_env, read_env


ROOT = Path(__file__).resolve().parents[1]
SCAFFOLD = ROOT / "repo" / "scaffold" / "init.py"
SECRETS = ROOT / "secrets" / ".env"
ENGINE_SAMPLE = ROOT / "contracts" / "engine"
FRAMEWORK_COMMIT = "0646268bea1ed51f546112461d01519892975326"
PARTICIPANTS = [
    ("Caroline", "Melanie"),
    ("Jon", "Gina"),
    ("John", "Maria"),
    ("Joanna", "Nate"),
    ("Tim", "John"),
    ("Audrey", "Andrew"),
    ("James", "John"),
    ("Deborah", "Jolene"),
    ("Evan", "Sam"),
    ("Calvin", "Dave"),
]
PARSER_PATCH_MARKER = "# LCR2609 byte-exact blank-continuation compatibility"


def patch_parser_source(source: str) -> str:
    """Make the generated parser preserve internal blank lines in a conversation turn."""
    if PARSER_PATCH_MARKER in source:
        return source
    old = """        if not line.strip():
            continue
"""
    new = f"""        if not line.strip():
            {PARSER_PATCH_MARKER}
            if turns:
                speaker, text = turns[-1]
                turns[-1] = (speaker, f\"{{text}}\\n\")
            continue
"""
    if source.count(old) != 1:
        raise ValueError("generated parser blank-line block is not uniquely patchable")
    return source.replace(old, new, 1)


def project_name(number: int) -> str:
    return f"lcr2609-{number:02d}"


def user_id(number: int) -> str:
    return f"u-lcr2609-{number:02d}"


def compose_prefix(number: int) -> str:
    return f"pneuma-{project_name(number)}-"


def render_answers(number: int, speaker_a: str, speaker_b: str) -> str:
    display = json.dumps(f"{speaker_a} and {speaker_b} conversation", ensure_ascii=False)
    return f'''language = "en"
project_name = "{project_name(number)}"

[owner]
display_name = {display}
industry = "other"
role = "other"
level = "mid"

[data]
mode = "none"

[contract]
mode = "skeleton"

[models]
compile = "openrouter:openai/gpt-5.6-luna"
recall = "openrouter:openai/gpt-5.6-luna"
answer = "openrouter:openai/gpt-5.6-luna"
embedding = "openrouter:openai/text-embedding-3-small"
deep = "openrouter:openai/gpt-5.6-luna"
live_discover = "openrouter:openai/gpt-5.6-luna"
live_pick = "openrouter:openai/gpt-5.6-luna"

[advanced]
user_id = "{user_id(number)}"
chunk_strategy = "semantic"
semantic_overlap = "smart"
challenge_enabled = true
compile_image_mode = "caption"
answer_style = "conversational"
prompt_language = "en"
'''


def render_profile(number: int, speaker_a: str, speaker_b: str) -> str:
    display = json.dumps(f"{speaker_a} and {speaker_b} conversation", ensure_ascii=False)
    return f'''# This benchmark conversation has no declared single owner or timezone.
display_name: {display}
occupation: ""
bio: "Longitudinal conversation {number:02d} between {speaker_a} and {speaker_b}."
interests: []
industry: other
role: other
level: mid
locale:
  city: ""
  country: ""
  timezone: "UTC"
  language: "en-US"
provenance:
  timezone: deployment_default
  language: deployment_default
  region: unstated
preferences:
  response_language: "en-US"
'''


def ensure_prerequisites() -> None:
    if not SCAFFOLD.is_file():
        raise ValueError(f"scaffold not found: {SCAFFOLD}")
    if not SECRETS.is_file():
        raise ValueError(f"secret file not found: {SECRETS}")
    commit = subprocess.run(
        ["git", "-C", str(ROOT / "repo"), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if commit != FRAMEWORK_COMMIT:
        raise ValueError(f"framework worktree is at unexpected commit: {commit}")
    if len(list(ROOT.glob("contracts/app-??.md"))) != 10:
        raise ValueError("exactly ten app contracts are required")


def generate_project(number: int, speaker_a: str, speaker_b: str, app_dir: Path) -> None:
    runtime = ROOT / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".toml", dir=runtime, delete=False
    ) as handle:
        answers = Path(handle.name)
        handle.write(render_answers(number, speaker_a, speaker_b))
    try:
        subprocess.run(
            [str(SCAFFOLD), "--answers", str(answers), "--target", str(app_dir)],
            cwd=ROOT,
            check=True,
        )
    finally:
        answers.unlink(missing_ok=True)


def assert_project_identity(number: int, app_dir: Path) -> None:
    app_py = app_dir / "app.py"
    env_path = app_dir / ".env"
    if not app_py.is_file() or not env_path.is_file() or not (app_dir / "engine" / ".git").exists():
        raise ValueError(f"existing project is incomplete and will not be overwritten: {app_dir}")
    env = read_env(env_path)
    compose = env.get("PNEUMA_APP_COMPOSE_PROJECT", "")
    if not compose.startswith(compose_prefix(number)):
        raise ValueError(f"compose project lacks experiment prefix: app-{number:02d}")
    if env.get("PNEUMA_APP_USER_ID") != user_id(number):
        raise ValueError(f"tenant id mismatch: app-{number:02d}")


def patch_generated_parser(app_dir: Path) -> None:
    app_py = app_dir / "app.py"
    source = app_py.read_text(encoding="utf-8")
    patched = patch_parser_source(source)
    if patched != source:
        app_py.write_text(patched, encoding="utf-8")


def install_engine(number: int, speaker_a: str, speaker_b: str, app_dir: Path) -> None:
    engine = app_dir / "engine"
    for source in sorted(ENGINE_SAMPLE.rglob("*")):
        if not source.is_file():
            continue
        relative = source.relative_to(ENGINE_SAMPLE)
        destination = engine / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
    shutil.copy2(ROOT / "contracts" / f"app-{number:02d}.md", engine / "compile" / "contract.md")
    (engine / "persona" / "profile.yaml").write_text(
        render_profile(number, speaker_a, speaker_b), encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(engine), "add", "-A"], check=True)
    status = subprocess.run(
        ["git", "-C", str(engine), "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status.strip():
        subprocess.run(
            ["git", "-C", str(engine), "commit", "-m", "engine: freeze LoCoMo experiment design"],
            check=True,
        )


def grep_count(pattern: str, path: Path) -> int:
    result = subprocess.run(
        ["grep", "-c", pattern, str(path)], capture_output=True, text=True, check=False
    )
    if result.returncode not in (0, 1):
        raise ValueError(f"grep validation failed for {path}")
    return int(result.stdout.strip() or "0")


def configure_project(number: int, speaker_a: str, speaker_b: str) -> None:
    app_dir = ROOT / f"app-{number:02d}"
    if not app_dir.exists():
        generate_project(number, speaker_a, speaker_b, app_dir)
    assert_project_identity(number, app_dir)
    patch_generated_parser(app_dir)
    install_engine(number, speaker_a, speaker_b, app_dir)
    summary = merge_env(app_dir / ".env", SECRETS, app_dir / ".env")
    key_count = grep_count(r"^OPENROUTER_API_KEY=.", app_dir / ".env")
    provider_count = grep_count(
        r"^PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai$", app_dir / ".env"
    )
    if key_count != 1 or provider_count != 1:
        raise ValueError(f"credential/provider validation failed for app-{number:02d}")
    subprocess.run([str(app_dir / "app.py"), "preflight"], cwd=app_dir, check=True)
    print(
        f"app-{number:02d}: {summary} key_count={key_count} "
        f"provider_count={provider_count} engine_clean=1"
    )


def main() -> int:
    try:
        ensure_prerequisites()
        for number, (speaker_a, speaker_b) in enumerate(PARTICIPANTS, start=1):
            configure_project(number, speaker_a, speaker_b)
        print("SETUP COMPLETE: 10/10 isolated projects")
        return 0
    except (OSError, UnicodeError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
