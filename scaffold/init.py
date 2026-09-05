#!/usr/bin/env python3
"""Generate a pneuma-knowledge project — the scaffold's single entry point.

Three modes over the same generator:

    ./init.py                                 # interactive: guided setup for a person
    ./init.py --answers my.toml --target DIR  # single command: a coding agent (or CI)
                                              #   supplies the same answers as TOML/JSON
    ./init.py --demo                          # zero interaction, zero keys: a project that
                                              #   already has a compiled library, started for
                                              #   you (--target DIR / --no-start to control it)
    ./init.py --print-schema                  # print a commented answers-file template

What generation does: copy the runtime machinery verbatim (app.py / start.sh /
docker-compose.yml — users never edit these), render the user-owned files (README.md,
AGENTS.md, .env) in the chosen documentation language, build the project's `engine/`
directory — its own git repository holding the model roles, strategy, compile contract and
owner profile — probe free localhost ports for the middleware stack (users never think
about ports — they are random, private to the project, and echoed on startup), and print
the next steps.

Standard library only: this script must run before any environment exists.
"""

from __future__ import annotations

import os
import sys

# The generator needs Python 3.11+ (tomllib); macOS system python3 is 3.9, and that is
# exactly what a bare `python3 scaffold/init.py` picks up. Re-exec through uv (a stated
# prerequisite) instead of dying on an ImportError nobody asked for.
if sys.version_info < (3, 11):
    if os.environ.get("PNEUMA_INIT_REEXEC") == "1":
        sys.exit("error: init.py needs Python 3.11+ and the uv re-exec did not provide it.")
    os.environ["PNEUMA_INIT_REEXEC"] = "1"
    os.execvpe(
        "uv",
        ["uv", "run", "--python", "3.12", "--no-project", "python", __file__, *sys.argv[1:]],
        os.environ,
    )

import argparse
import getpass
import json
import random
import re
import secrets
import shutil
import socket
from pathlib import Path

sys.dont_write_bytecode = True

SCAFFOLD_DIR = Path(__file__).resolve().parent
TEMPLATES = SCAFFOLD_DIR / "templates"
EXAMPLE = SCAFFOLD_DIR / "example"

MACHINERY = ("app.py", "start.sh", "docker-compose.yml", "server.py", "worker.py")
EXECUTABLE = ("app.py", "start.sh", "server.py", "worker.py")

# --------------------------------------------------------------------- demo mode
# `--demo` generates an ordinary project that already HAS a library: the example project's
# real contract, its owner profile, and the two authorities of its compiled library (the
# canonical git bundle + the verbatim L0 rows), which `./app.py restore` loads with no API
# key. Structurally it is a plain generated project; what it adds is a payload.
DEMO_EXAMPLE = ("examples", "opc")
DEMO_PROJECT_NAME = "knowledge-demo"
# One id, one library: the shipped canonical belongs to this tenant.
DEMO_USER_ID = "u-opc-lin"
# The example is itself a generated project, so its contract and owner profile live where
# every generated project keeps them — inside its own engine directory.
DEMO_CONTRACT = "engine/compile/contract.md"
DEMO_PROFILE = "engine/persona/profile.yaml"
# The shipped library's vectors are deterministic, which is what makes keyless browsing
# (and a keyless rebuild) possible. Stated in engine.yaml like every other choice.
DEMO_EMBEDDING = "fake:1536"
# Raw material left in my-data/: the bait for "I want to watch a compile happen". Three files
# from the same corpus the library was compiled from — enough to run the pipeline end to end
# on a real contract without waiting for 190 sources.
DEMO_MATERIAL = (
    "2026-05-20-阶段复盘后的条件核对.md",
    "2026-05-21-数据处理附录-红线版与待签状态.md",
    "2026-05-24-未解项交接卡.md",
)

DEFAULT_MODELS = {
    "compile": "openrouter:openai/gpt-5.6-luna",
    "recall": "openrouter:openai/gpt-5.6-luna",
    # Fast answers borrow the recall role by default. A separate answer model and explicit
    # reasoning effort remain available deployment choices, but they should be justified by
    # the deployment's own validation rather than imposed on every generated project.
    "answer": "",
    "answer_reasoning_effort": "",
    "embedding": "openrouter:openai/text-embedding-3-small",
    # The agentic deep-search lane defaults to the stronger sibling: it reasons across
    # multiple retrieval rounds, where the model tier is worth its price.
    "deep": "openrouter:openai/gpt-5.6-terra",
    # Discovery can skip retrieval; pick runs only when candidates exist.
    # discover — a small REASONING model: it decides whether the tick retrieves at all, in a
    #   few dozen tokens. sol is that shape; its effort is pinned LOW in the framework.
    # pick — a WEAK FAST model: it chooses between cards that are already assembled and may
    #   not rewrite a word of them. Reasoning is pinned off.
    "live_discover": "openrouter:openai/gpt-5.6-sol",
    "live_pick": "openrouter:openai/gpt-5.6-luna",
    # The optional supplementary internet face. Named here even though `live_web_search` is
    # off, so a person turning it on finds a model already stated rather than a blank.
    "live_web_search_model": "openai/gpt-5.6-luna",
}

# Answers files must never carry credentials: they are meant to be shareable and replayable
# (an agent may keep one in a task record). The key travels via prompt or --key-from-env.
KEY_SHAPE = re.compile(r"sk-or-[A-Za-z0-9-]{8,}")


# ------------------------------------------------------------------ tiny TUI toolkit

_TTY = sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\x1b[{code}m{text}\x1b[0m" if _TTY else text


def bold(text: str) -> str:
    return _c("1", text)


def dim(text: str) -> str:
    return _c("2", text)


def cyan(text: str) -> str:
    return _c("36", text)


def say(text: str = "") -> None:
    print(text)


def header(step: int, total: int, title: str) -> None:
    print()
    print(bold(cyan(f"── {step}/{total} · {title} ")) + bold(cyan("─" * max(1, 50 - len(title)))))


def ask(prompt: str, default: str = "") -> str:
    suffix = dim(f" [{default}]") if default else ""
    try:
        raw = input(f"  {prompt}{suffix} > ").strip()
    except EOFError:
        raw = ""
    return raw or default


def echo_choice(label: str, value: str) -> None:
    print(dim(f"  ✓ {label}: ") + value)


# ------------------------------------------------------------------ answers loading

def load_answers(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if KEY_SHAPE.search(text):
        sys.exit(
            "error: the answers file contains an API-key-shaped string. Keys never belong in "
            "answers files —\nuse --key-from-env VAR_NAME, or fill .env after generation."
        )
    if path.suffix.lower() == ".json":
        return json.loads(text)
    if path.suffix.lower() == ".toml":
        import tomllib

        return tomllib.loads(text)
    sys.exit(f"error: unrecognized answers format (supported: .toml / .json): {path}")


SCHEMA_TOML = """\
# Answers file (TOML) for the pneuma-knowledge scaffold.
# Usage: ./init.py --answers this-file --target target-dir
# Every field except language may be omitted — omission takes the default shown here.
# NEVER put an API key in this file (pass --key-from-env VAR_NAME, or fill .env afterwards).

language = "en"            # documentation language of the generated project: zh | en
project_name = "my-kb"     # project name (lowercase letters/digits/hyphens); default dir name

[owner]
display_name = ""          # optional; leave unknown owner details unstated
occupation = ""            # one-line occupation
bio = ""                   # a sentence or two of background
interests = []             # long-term interest keywords, e.g. ["hiking", "open source"]
industry = ""              # optional: tech/finance/sports/creative/education/healthcare/marketing/other
role = ""                  # optional: engineering/marketing/product_management/sales/design/support/admin/other
level = ""                 # optional: entry/junior/mid/senior/staff/principal

[data]
mode = "none"              # example = bundled demo dataset | path = my own directory | none = empty
                           # demo = what ./init.py --demo generates (a shipped, already-compiled
                           #   library plus a few raw materials); normally set by --demo, not here
path = ""                  # absolute path when mode = "path"; read at ingest time, never copied

[contract]
mode = "auto"              # auto = follow the data (example data → demo contract, else starter)
                           # starter = usable source-grounded contract | example = bundled demo contract
                           # demo = the example project's real, agent-authored contract
                           # reference = start from a built-in strategy (fill reference below)
reference = ""             # e.g. "personal-knowledge@v2" (list with ./init.py --list-references)

[models]
compile = "openrouter:openai/gpt-5.6-luna"        # compile model (must support tool calling)
recall = "openrouter:openai/gpt-5.6-luna"         # retrieval planning/glance model
answer = ""                                       # empty = final answer borrows recall
answer_reasoning_effort = ""                      # empty = preserve provider default
embedding = "openrouter:openai/text-embedding-3-small"
deep = "openrouter:openai/gpt-5.6-terra"  # deep-recall (agentic) model; empty falls back to recall
live_discover = "openrouter:openai/gpt-5.6-sol"   # Live Context stage 1: small reasoning, LOW effort
live_pick = "openrouter:openai/gpt-5.6-luna"      # Live Context stage 3: weak + fast, reasoning off
live_web_search_model = "openai/gpt-5.6-luna"     # supplementary internet search (off unless enabled)

[advanced]
user_id = "u-app-owner"    # tenant id: a different id is a different, empty library
chunk_strategy = "semantic"  # semantic = LLM episode boundary + retrieval description | sentence = mechanical
semantic_overlap = "smart" # semantic only: smart = neighbouring segments may share a hinge
                           # block (default) | off = original zero-overlap geometry
challenge_enabled = false  # post-compile coverage challenge (extra model calls per compile)
compile_image_mode = "auto" # auto = use model profile | native = send image blocks |
                           # caption = labelled caption/OCR text only
answer_style = "conversational"  # how Q&A answers read: concise = one compact value
                           # for API/automation consumers | conversational = natural chat reply |
                           # detailed = self-contained written note
prompt_language = "en"     # language of the FRAMEWORK's own prompts: en (default) |
                           # zh (Chinese language pack). Not the language your
                           # library is written in — that follows the owner profile.
"""


# ------------------------------------------------------------------ pure helpers

def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "my-kb"


def find_framework_repo() -> Path | None:
    for candidate in SCAFFOLD_DIR.parents:
        if (candidate / "packages" / "pneuma-knowledge-service").is_dir():
            return candidate
    return None


def demo_example(repo: Path) -> Path:
    """The example project the demo is made of, verified to still carry its library.

    The demo does not own a copy of anything: it reuses the example's contract, owner profile,
    material and prebuilt authorities, so there is one corpus in this repository and no second
    one to keep in sync."""
    source = repo.joinpath(*DEMO_EXAMPLE)
    for required in (
        DEMO_CONTRACT,
        DEMO_PROFILE,
        "prebuilt/canonical.bundle",
        "prebuilt/l0.jsonl.gz",
    ):
        if not (source / required).is_file():
            sys.exit(f"error: demo mode needs {source / required}, which is missing.")
    return source


def probe_free_ports(count: int, *, lo: int = 20000, hi: int = 59999) -> list[int]:
    """Distinct localhost ports that are free right now. Random draws instead of a fixed
    block: two projects generated on the same machine must never collide with each other,
    or with anything else already listening. Users are never asked about ports."""
    ports: list[int] = []
    attempts = 0
    while len(ports) < count:
        attempts += 1
        if attempts > 500:
            sys.exit("error: could not find enough free localhost ports (tried 500 times).")
        port = random.randrange(lo, hi)
        if port in ports:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
        ports.append(port)
    return ports


def probe_free_subnet() -> str:
    """A random private /24 for the project's Docker network, checked (best-effort)
    against the host routing table. Random for the same reason ports are: two projects
    generated on one machine must not collide, and Docker's default address pools are a
    finite resource that many-project machines exhaust."""
    import subprocess

    routed = ""
    for probe_cmd in (["netstat", "-rn", "-f", "inet"], ["ip", "route"]):
        try:
            routed = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5).stdout
            break
        except (OSError, subprocess.TimeoutExpired):
            continue
    for _ in range(200):
        second, third = random.randrange(128, 255), random.randrange(0, 255)
        subnet = f"10.{second}.{third}.0/24"
        if f"10.{second}.{third}." not in routed and subnet != "10.222.222.0/24":
            return subnet
    return "10.222.222.0/24"  # fallback: the template's own default


def render(template: str, slots: dict[str, str]) -> str:
    out = template
    for key, value in slots.items():
        out = out.replace("{{" + key + "}}", value)
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", out)
    if leftover:
        raise ValueError(f"unfilled template slots: {sorted(set(leftover))}")
    return out


def strategies_catalog(repo: Path) -> list[dict]:
    """The built-in strategy catalog, read as data (pneuma-knowledge-strategies is a
    data-only package, so no environment is needed to list it)."""
    root = (
        repo
        / "packages"
        / "pneuma-knowledge-strategies"
        / "src"
        / "pneuma_knowledge_strategies"
        / "strategies"
    )
    found: list[dict] = []
    for manifest_path in sorted(root.glob("*/strategy.json")):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for generation in manifest.get("generations", []):
            body_path = manifest_path.parent / str(generation.get("file", ""))
            if not body_path.is_file():
                continue
            found.append(
                {
                    "skill_id": str(manifest.get("skill_id", "")),
                    "version": str(generation.get("version", "")),
                    "domain": str(manifest.get("domain", "")),
                    "summary": str(generation.get("summary") or manifest.get("summary", "")),
                    "path_templates": [str(t) for t in manifest.get("path_templates", [])],
                    "body_path": body_path,
                }
            )
    return found


def reference_contract_text(strategy: dict, *, skill_id: str) -> str:
    """contract.md started from a reference strategy — with the USER'S own identity.
    skill_id/version stay the user's, never the reference's: provenance is attributed to
    this library's own contract from its very first commit."""
    body = strategy["body_path"].read_text(encoding="utf-8").strip()
    templates = "\n".join(f"  - {t}" for t in strategy["path_templates"])
    ref = f"{strategy['skill_id']}@{strategy['version']}"
    return f"""---
# Body referenced from built-in strategy {ref}. skill_id and version identify YOUR library:
# provenance is attributed to your own contract from the first commit (never the reference's).
skill_id: {skill_id}
# Bump the version after rewriting the body; registration takes effect under the new version.
version: app-v1
path_templates:
{templates}
---

<!-- The body below comes from the built-in reference strategy {ref}. It is a starting
     point, not an answer: a contract written for someone else's domain cannot know what
     counts as high-value versus noise in yours. Run it first, then rewrite it section by
     section against your own material — the full practice lives in the framework
     repository's docs/guides/compile-contract.md. -->

{body}
"""


def yaml_string_list(items: list[str]) -> str:
    return "[" + ", ".join('"' + item.replace('"', "'") + '"' for item in items) + "]"


def sample_material(directory: Path, *, files: int = 4, lines: int = 3) -> list[str]:
    """A one-screen peek at a material directory: a few file names, and the first content
    lines of the first file — enough for the user to recognize what data they are about
    to build on, not a full listing."""
    paths = sorted(p for p in directory.iterdir() if p.is_file()
                   and p.suffix.lower() in {".md", ".json"} and p.name.lower() != "readme.md")
    out = [f"  {len(paths)} material files (.md / .json), e.g.:"]
    for path in paths[:files]:
        out.append(f"    · {path.name}")
    if len(paths) > files:
        out.append(f"    · … and {len(paths) - files} more")
    if paths:
        content = [l for l in paths[0].read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
        out.append(f"  first lines of {paths[0].name}:")
        for line in content[:lines]:
            out.append(dim(f"    | {line[:76]}"))
    return out


# ------------------------------------------------------------------ config assembly

ENUMS = {
    "industry": {"tech", "finance", "sports", "creative", "education", "healthcare", "marketing", "other"},
    "role": {"engineering", "marketing", "product_management", "sales", "design", "support", "admin", "other"},
    "level": {"entry", "junior", "mid", "senior", "staff", "principal"},
}


def build_config(answers: dict, *, target: str | None) -> dict:
    """Normalize an answers mapping (from a file or the interactive flow) into the full
    generation config, applying defaults and validating enums."""
    language = str(answers.get("language") or "zh")
    if language not in ("zh", "en"):
        sys.exit(f"error: language must be zh or en, got {language!r}")
    project_name = slugify(str(answers.get("project_name") or "my-kb"))

    owner_in = dict(answers.get("owner") or {})
    owner = {
        "display_name": str(owner_in.get("display_name") or ""),
        "occupation": str(owner_in.get("occupation") or ""),
        "bio": str(owner_in.get("bio") or ""),
        "interests": [str(i) for i in (owner_in.get("interests") or [])],
    }
    for enum_field, allowed in ENUMS.items():
        value = str(owner_in.get(enum_field) or "")
        if value and value not in allowed:
            sys.exit(f"error: owner.{enum_field} value {value!r} not in {sorted(allowed)}")
        owner[enum_field] = value

    data_in = dict(answers.get("data") or {})
    data_mode = str(data_in.get("mode") or "none")
    if data_mode not in ("example", "path", "none", "demo"):
        sys.exit(f"error: data.mode must be example / path / none / demo, got {data_mode!r}")
    data_path = str(data_in.get("path") or "")
    if data_mode == "path":
        if not data_path:
            sys.exit("error: data.mode = path requires data.path")
        resolved = Path(data_path).expanduser().resolve()
        if not resolved.is_dir():
            sys.exit(f"error: data.path is not a directory: {resolved}")
        if not any(resolved.glob("*.md")) and not any(resolved.glob("*.json")):
            print(f"  note: no .md or source-contract .json files in {resolved} yet.")
        data_path = str(resolved)

    contract_in = dict(answers.get("contract") or {})
    contract_mode = str(contract_in.get("mode") or "auto")
    if contract_mode == "auto":
        contract_mode = {"example": "example", "demo": "demo"}.get(data_mode, "starter")
    if contract_mode not in ("starter", "example", "reference", "demo"):
        sys.exit(
            "error: contract.mode must be auto / starter / example / reference / demo, "
            f"got {contract_mode!r}"
        )
    reference = str(contract_in.get("reference") or "")
    if contract_mode == "reference" and "@" not in reference:
        sys.exit("error: contract.mode = reference requires contract.reference (like skill_id@version)")

    models_in = dict(answers.get("models") or {})
    models = {key: str(models_in.get(key) or default) for key, default in DEFAULT_MODELS.items()}

    advanced_in = dict(answers.get("advanced") or {})
    chunk_strategy = str(advanced_in.get("chunk_strategy") or "semantic")
    if chunk_strategy not in ("semantic", "sentence"):
        sys.exit(f"error: advanced.chunk_strategy must be semantic / sentence, got {chunk_strategy!r}")
    semantic_overlap = str(advanced_in.get("semantic_overlap") or "smart")
    if semantic_overlap not in ("off", "smart"):
        sys.exit(f"error: advanced.semantic_overlap must be off / smart, got {semantic_overlap!r}")
    answer_style = str(advanced_in.get("answer_style") or "conversational")
    if answer_style not in ("concise", "conversational", "detailed"):
        sys.exit(
            "error: advanced.answer_style must be concise / conversational / detailed, "
            f"got {answer_style!r}"
        )
    prompt_language = str(advanced_in.get("prompt_language") or "en")
    if prompt_language not in ("en", "zh"):
        sys.exit(f"error: advanced.prompt_language must be en / zh, got {prompt_language!r}")
    compile_image_mode = str(advanced_in.get("compile_image_mode") or "auto")
    if compile_image_mode not in ("auto", "caption", "native"):
        sys.exit(
            "error: advanced.compile_image_mode must be auto / caption / native, "
            f"got {compile_image_mode!r}"
        )
    # OpenRouter model ids do not always carry LangChain model profiles. The shipped compile
    # default is an explicitly multimodal GPT-5.6 route, so record that declaration in the
    # generated project instead of silently degrading its image inputs to caption-only.
    if (
        compile_image_mode == "auto"
        and models["compile"].startswith("openrouter:openai/gpt-5.6")
    ):
        compile_image_mode = "native"

    return {
        "language": language,
        "project_name": project_name,
        "target": str(Path(target).expanduser() if target else Path.home() / project_name),
        "owner": owner,
        "data_mode": data_mode,
        "data_path": data_path,
        # A demo project ships a compiled library; everything else about it is an ordinary
        # generated project, which is why this is one flag and not a second code path.
        "demo": data_mode == "demo",
        "contract_mode": contract_mode,
        "reference": reference,
        "models": models,
        "user_id": str(advanced_in.get("user_id") or "u-app-owner"),
        "chunk_strategy": chunk_strategy,
        "semantic_overlap": semantic_overlap,
        "answer_style": answer_style,
        "prompt_language": prompt_language,
        "compile_image_mode": compile_image_mode,
        "challenge_enabled": bool(advanced_in.get("challenge_enabled") or False),
        "api_key": "",
    }


# ------------------------------------------------------------------ generation

def make_env_text(config: dict, ports: dict[str, int], compose_project: str, repo: Path) -> str:
    """The project's `.env`: the API key and this machine's infrastructure, nothing else.

    Strategy deliberately does NOT live here. It lives in `engine/`, which is versioned —
    and `.env`, which holds a credential, must never be. Keeping the two apart is what makes
    the engine directory shareable and the key un-shareable."""
    return "\n".join(
        [
            f"# Environment for {config['project_name']} — generated by scaffold/init.py.",
            "# The API key lives in this file only (gitignored), never committed.",
            "#",
            "# Strategy is NOT here: model roles, chunking, answer style, the compile contract",
            "# and your profile all live in engine/ — this project's own versioned unit (see",
            "# engine/README.md). This file holds only the key and this machine's infrastructure.",
            "# app.py loads it into the process environment, so a PNEUMA_KNOWLEDGE_* strategy key",
            "# placed here would outrank the engine file — reserve that for temporary operations.",
            "",
            "# OpenRouter API key (https://openrouter.ai/keys)",
            f"OPENROUTER_API_KEY={config['api_key']}",
            "",
            "# This project's engine directory, so the framework API (and its Engine Console)",
            "# serves this engine when started from the project root.",
            "PNEUMA_KNOWLEDGE_ENGINE_DIR=./engine",
            "",
            "# Framework repository (app.py runs via its uv environment).",
            f"PNEUMA_APP_FRAMEWORK_REPO={repo}",
            "# Optional external material directory. Empty means this project's my-data/.",
            f"PNEUMA_APP_DATA_DIR={config['data_path']}",
            "",
            "# Compose project name and ports — free ports probed at generation time, private to",
            "# this project. The project name owns the docker volumes; renaming orphans them.",
            f"PNEUMA_APP_COMPOSE_PROJECT={compose_project}",
            f"PNEUMA_APP_PG_PORT={ports['pg']}",
            f"PNEUMA_APP_QDRANT_PORT={ports['qdrant']}",
            f"PNEUMA_APP_QDRANT_GRPC_PORT={ports['qdrant_grpc']}",
            f"PNEUMA_APP_MEILI_PORT={ports['meili']}",
            f"PNEUMA_APP_RUSTFS_PORT={ports['rustfs']}",
            f"PNEUMA_APP_RUSTFS_CONSOLE_PORT={ports['rustfs_console']}",
            f"PNEUMA_APP_RUSTFS_ACCESS_KEY={config['rustfs_access_key']}",
            f"PNEUMA_APP_RUSTFS_SECRET_KEY={config['rustfs_secret_key']}",
            "# The browsing layer (framework API + web UI), started only by the optional",
            "# `console` compose profile:  docker compose --profile console up -d --wait",
            f"PNEUMA_APP_API_PORT={ports['api']}",
            f"PNEUMA_APP_WEB_PORT={ports['web']}",
            "# Optional container-side override for a Langfuse server on this host.",
            "# Example: http://host.docker.internal:3205 when host-side BASE_URL is localhost.",
            "PNEUMA_APP_LANGFUSE_BASE_URL_CONTAINER=",
            "# If that self-hosted Langfuse signs media URLs with localhost, set this to",
            "# host-gateway so API/worker containers can upload the traced attachments.",
            "PNEUMA_APP_LANGFUSE_LOCALHOST_GATEWAY=",
            "# Without a key, every process runs model-free and embeds with a deterministic",
            "# vector. Its dimension must match the collection: uncomment and set fake:<dim>",
            "# if this engine's embedding model has a dimension other than 1536.",
            "# PNEUMA_APP_KEYLESS_EMBEDDING=fake:1536",
            "# Project-private Docker subnet (probed unused; avoids default address-pool exhaustion).",
            f"PNEUMA_APP_SUBNET={config['subnet']}",
            "",
            "# Tenant id: a different id is a different, empty library.",
            f"PNEUMA_APP_USER_ID={config['user_id']}",
            "",
        ]
    )


def contract_text(config: dict, repo: Path) -> tuple[str, str]:
    """(contract.md text, one-line hint for the README) per contract_mode."""
    zh = config["language"] == "zh"
    skill_id = f"{config['project_name']}-knowledge"
    if config["contract_mode"] == "example":
        text = (EXAMPLE / "contract.md").read_text(encoding="utf-8")
        hint = (
            "当前是内置演示契约；换你自己的数据时照 docs/guides/compile-contract.zh-CN.md 整段重写。"
            if zh
            else "Currently the bundled demo contract; rewrite it per docs/guides/compile-contract.md when you switch to your own data."
        )
        return text, hint
    if config["contract_mode"] == "demo":
        text = (demo_example(repo) / DEMO_CONTRACT).read_text(encoding="utf-8")
        hint = (
            "这是示例项目 examples/opc 的真实契约（一个 agent 通读 190 份材料后写的，"
            "自带的库就是按它编出来的）；它是判断力的样本，不是模板——换你自己的材料要整段重写。"
            if zh
            else "The example project's real contract (an agent wrote it after reading all 190 "
            "materials; the shipped library was compiled with it). Read it as a sample of "
            "judgement, not a template — rewrite it for your own material."
        )
        return text, hint
    if config["contract_mode"] == "reference":
        catalog = strategies_catalog(repo)
        wanted = config["reference"]
        for entry in catalog:
            if f"{entry['skill_id']}@{entry['version']}" == wanted:
                hint = (
                    f"起点参考自内置策略 {wanted}；照你的材料整段改写。"
                    if zh
                    else f"Started from built-in strategy {wanted}; rewrite it against your own material."
                )
                return reference_contract_text(entry, skill_id=skill_id), hint
        sys.exit(f"error: no built-in strategy named {wanted} (list them with ./init.py --list-references).")
    template = (TEMPLATES / ("contract.zh.md" if zh else "contract.en.md")).read_text(encoding="utf-8")
    hint = (
        "可直接运行的起始契约；读过代表性材料后，再具体化用途与主体族。"
        if zh
        else "Usable starter contract; specialize its purpose and subject families after reading representative sources."
    )
    return render(template, {"SKILL_ID": skill_id}), hint


def engine_files(config: dict, contract: str, profile: str) -> dict[str, str]:
    """The engine directory's contents, engine-relative path → text.

    Each strategy file is a flat mapping of the keys the framework's engine schema declares
    for that stage (`GET /v1/engine/schema`), which is how the console, the CLI and this
    generator stay one story. Comments are English like the rest of the machinery; the
    orientation document beside them is written in the project's own language.

    Every value written here is stated explicitly, including the ones that equal the
    framework default: the point of the engine directory is that a person can read what
    their engine does without knowing what the framework would otherwise have chosen."""
    zh = config["language"] == "zh"
    models = config["models"]
    readme = (TEMPLATES / ("engine-README.zh.md" if zh else "engine-README.en.md")).read_text(
        encoding="utf-8"
    )
    deep = models["deep"]
    return {
        "README.md": render(readme, {"PROJECT_NAME": config["project_name"]}),
        "engine.yaml": f"""\
# Model roles and framework limits. See README.md for behavior and change scope.
# Compile requires tool calling; native images require a model that accepts image content.
compile: {models["compile"]}
image_mode: {config["compile_image_mode"]}
# Per-call timeout in seconds; 0 disables the timeout.
compile_call_timeout: 600
# 0 derives a bounded budget from the job; it does not mean unlimited.
compile_max_tool_calls: 0
overview_budget_chars: 2000
# Applies to touched pages; 0 disables the presence threshold, not reference checks.
overview_required_after_claims: 8
recall: {models["recall"]}
answer: {models["answer"] if models["answer"] else '""'}
answer_reasoning_effort: {models["answer_reasoning_effort"] if models["answer_reasoning_effort"] else '""'}
deep: {deep if deep else '""'}
# Discovery may decide no retrieval is needed; pick runs only when candidates exist.
live_discover: {models["live_discover"] if models["live_discover"] else '""'}
live_pick: {models["live_pick"] if models["live_pick"] else '""'}
# External search is opt-in and also gated by each Live Context connection.
live_web_search: false
live_web_search_model: {models["live_web_search_model"]}
# Changing model requires rebuilding vectors, even when its dimensions are unchanged.
embedding: {models["embedding"]}

# Optional rates per 1M tokens; an undeclared rate yields tokens, not an invented cost.
pricing: ""

# Enable only when source semantics and contract families support the component.
components: ""
# Inactive until people is enabled; set to an actual person-family path template.
people_family: memory/people/{{slug}}.md
attention_half_life_days: 14
attention_window_days: 60
attention_evidence_chars: 1500
""",
        "intake/intake.yaml": f"""\
# New-source segmentation. Semantic indexing can use several bounded model calls.
# Derived rebuilds replay already-kept semantic manifests rather than choosing new cuts.
chunk_strategy: {config["chunk_strategy"]}

semantic_overlap: "{config["semantic_overlap"]}"
""",
        "compile/contract.md": contract,
        "compile/challenge.yaml": f"""\
# Optional coverage probes and compensation; extra model calls on future compiles.
enabled: {"true" if config["challenge_enabled"] else "false"}
max_rounds: 2
max_questions: 6
max_output_tokens: 32768
compensate: true
""",
        "evolve/evolve.yaml": """\
# Proposals are drafts. CLI evolve step keeps them unless explicitly told to adopt.
auto_trigger: false
trigger_topic_docs: 5
trigger_new_claims: 30
draft_ttl_hours: 24
""",
        "recall/recall.yaml": f"""\
# Broad retrieval, bounded answer context, structured answer/citation validation.
# Override one ask with --style / --evidence-strategy / --answer-format.
answer_style: {config["answer_style"]}

evidence_strategy: ranked
answer_format: structured
selection_reasoning_effort: ""
# Used only by all; 0 means no character ceiling.
all_context_chars: 120000

claim_candidate_cap: 80
claim_cap: 40
window_candidate_cap: 60
episode_summary_cap: 16
window_cap: 6
# 0 disables planning; positive values add a query-planning call.
plan_queries: 0
# Empty disables reranking. Measure before adding the model call.
rerank_model: ""
rerank_candidates: 120

component_paths: true
component_budget_chars: 6000
""",
        "persona/profile.yaml": profile,
        "prompts/overlays.yaml": f"""\
# Framework wording language, independent of answer language.
# Whole-clause replacements; unknown keys are rejected. Domain judgment belongs in the contract.
language: {config["prompt_language"]}
overlays: {{}}
""",
    }



def demo_readme_section(zh: bool) -> str:
    """A prebuilt demonstration is separate from a real-material compilation."""
    if zh:
        return """
> **这是独立演示项目。** `prebuilt/` 保存 `examples/opc` 的正本 git bundle 和所引用的
> L0 来源。`./app.py restore` 无需 API key 即可恢复并浏览 191 份来源、28 份正本文档。
> 派生层使用确定性向量，只用于无 key 展示。已有的 3 份示例原料再次导入会被去重。
> 要编译自己的材料，请另生成一个项目，使用起始契约与真实 embedding，无需删除此演示库。
"""
    return """
> **This is a separate demonstration project.** `prebuilt/` holds the canonical git bundle
> and cited L0 of `examples/opc`. `./app.py restore` restores 191 sources and 28 documents
> for keyless browsing. Its deterministic vectors are for demonstration, not retrieval-quality
> measurement. Re-importing the 3 already-kept example inputs deduplicates them. Build your
> own material in a fresh project with the starter contract and real embeddings; keep this demo.
"""


def git_init_engine(engine: Path) -> str:
    """`git init` the engine directory and commit its generated state.

    The identity is written into the repository's own config so a commit here never depends
    on (or records) the machine's git config. Returns a one-line report; a machine without
    git still gets a complete project, just an unversioned engine, and is told so."""
    import subprocess

    steps = (
        ["init", "-q"],
        ["config", "user.email", "engine@local"],
        ["config", "user.name", "pneuma-engine"],
        ["add", "-A"],
        ["commit", "-q", "-m", "engine: initial"],
    )
    try:
        for args in steps:
            result = subprocess.run(
                ["git", "-C", str(engine), *args], capture_output=True, text=True
            )
            if result.returncode != 0:
                return f"engine/ left unversioned: git {args[0]} failed ({result.stderr.strip()[:80]})"
    except OSError as exc:
        return f"engine/ left unversioned: git is not available ({exc})"
    return "engine/ initialized as its own git repository (commit: engine: initial)"


def generate(config: dict) -> Path:
    repo = find_framework_repo()
    if repo is None:
        sys.exit("error: framework repository not found — init.py must run from inside the pneuma-knowledge-compiler repo.")

    target = Path(config["target"]).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        sys.exit(f"error: target directory exists and is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    zh = config["language"] == "zh"
    pg, qdrant, qdrant_grpc, meili, rustfs, rustfs_console, api, web = probe_free_ports(8)
    ports = {
        "pg": pg,
        "qdrant": qdrant,
        "qdrant_grpc": qdrant_grpc,
        "meili": meili,
        "rustfs": rustfs,
        "rustfs_console": rustfs_console,
        "api": api,
        "web": web,
    }
    config["subnet"] = probe_free_subnet()
    config["rustfs_access_key"] = f"pneuma-{secrets.token_hex(8)}"
    config["rustfs_secret_key"] = secrets.token_urlsafe(32)
    compose_project = f"pneuma-{config['project_name']}-{random.randrange(16**4):04x}"

    # 1) machinery, verbatim
    for name in MACHINERY:
        shutil.copy2(TEMPLATES / name, target / name)
    shutil.copy2(TEMPLATES / "gitignore", target / ".gitignore")

    # 2) engine/ — the project's own versioned unit: strategy, contract, profile, overlays
    text, contract_hint = contract_text(config, repo)
    if config["demo"]:
        # The shipped library is one particular person's. Its owner profile is copied verbatim
        # rather than rendered from answers, so the engine and the restored canonical agree
        # about whose library this is.
        profile = (demo_example(repo) / DEMO_PROFILE).read_text(encoding="utf-8")
    else:
        profile_template = (
            TEMPLATES / ("profile.zh.yaml" if zh else "profile.en.yaml")
        ).read_text(encoding="utf-8")
        profile = render(
            profile_template,
            {
                "DISPLAY_NAME": config["owner"]["display_name"].replace('"', "'"),
                "OCCUPATION": config["owner"]["occupation"].replace('"', "'"),
                "BIO": config["owner"]["bio"].replace('"', "'"),
                "INTERESTS": yaml_string_list(config["owner"]["interests"]),
                "INDUSTRY": config["owner"]["industry"],
                "ROLE": config["owner"]["role"],
                "LEVEL": config["owner"]["level"],
            },
        )
    engine = target / "engine"
    for rel, body in engine_files(config, text, profile).items():
        path = engine / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
    engine_note = git_init_engine(engine)

    # 3) data
    my_data = target / "my-data"
    if config["data_mode"] == "example":
        shutil.copytree(EXAMPLE / "data", my_data)
        shutil.copy2(EXAMPLE / "demo-questions.txt", target / "demo-questions.txt")
    elif config["data_mode"] == "demo":
        # A shipped library (the two authorities) plus a few raw materials from the same
        # corpus: the library is browsable with no key, the materials are there for whoever
        # wants to watch a compile run on a real contract.
        source = demo_example(repo)
        my_data.mkdir()
        for name in DEMO_MATERIAL:
            shutil.copy2(source / "my-data" / name, my_data / name)
        shutil.copytree(source / "prebuilt", target / "prebuilt")
    else:
        my_data.mkdir()

    # 4) docs
    readme_template = (TEMPLATES / ("README.project.zh.md" if zh else "README.project.en.md")).read_text(encoding="utf-8")
    agents_template = (TEMPLATES / ("AGENTS.project.zh.md" if zh else "AGENTS.project.en.md")).read_text(encoding="utf-8")
    slots = {
        "PROJECT_NAME": config["project_name"],
        "FRAMEWORK_REPO": str(repo),
        "CONTRACT_HINT": contract_hint,
        # Empty for an ordinary project: the section exists only for a project that ships a
        # prebuilt library, and an unused slot must render as nothing rather than as a hole.
        "DEMO_SECTION": demo_readme_section(zh) if config["demo"] else "",
    }
    (target / "README.md").write_text(render(readme_template, slots), encoding="utf-8")
    (target / "AGENTS.md").write_text(render(agents_template, slots), encoding="utf-8")

    # 5) .env — plus a key-blank .env.example as the reference/recovery copy: the project
    # README names the editable files, not every env key, so a deleted .env must be
    # recoverable from inside the project itself.
    env_text = make_env_text(config, ports, compose_project, repo)
    (target / ".env").write_text(env_text, encoding="utf-8")
    os.chmod(target / ".env", 0o600)
    example_text = re.sub(r"(?m)^OPENROUTER_API_KEY=.*$", "OPENROUTER_API_KEY=", env_text)
    example_text = re.sub(
        r"(?m)^PNEUMA_APP_RUSTFS_(?:ACCESS|SECRET)_KEY=.*$",
        lambda match: match.group(0).split("=", 1)[0] + "=",
        example_text,
    )
    (target / ".env.example").write_text(example_text, encoding="utf-8")
    for name in EXECUTABLE:
        os.chmod(target / name, 0o755)

    # 6) next steps
    say()
    say(bold(f"✓ Project generated: {target}"))
    say(dim(f"  stack: compose project {compose_project} · ports pg {pg} / qdrant {qdrant},{qdrant_grpc} / meili {meili} / rustfs {rustfs},{rustfs_console} / api {api} / web {web} · subnet {config['subnet']}"))
    say(dim("  (ports were probed free and written into .env — nothing for you to manage)"))
    say(dim(f"  {engine_note}"))
    if config["demo"]:
        # A demo has its own next steps (it starts the stack and restores the library itself),
        # and telling someone to fill a key here would contradict the whole point.
        return target
    say()
    say(bold("Next steps:"))
    say(f"  cd {target}")
    if not config["api_key"]:
        say("  $EDITOR .env      " + dim("# fill OPENROUTER_API_KEY (https://openrouter.ai/keys)"))
    say("  ./start.sh        " + dim("# validate inputs → start stack → ingest/compile each file"))
    if config["data_mode"] == "path":
        say("  " + dim(f"source directory: {config['data_path']} (saved in .env; start.sh uses it)"))
    if config["data_mode"] == "none":
        say("  " + dim("put source-contract .json or .md notes in my-data/, then run ./start.sh"))
    return target


# ------------------------------------------------------------------ demo mode


def env_value(project: Path, key: str) -> str:
    """One value out of a generated `.env` — read back from the file rather than passed
    around, so what is echoed is what the project will actually use."""
    for line in (project / ".env").read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return ""


def demo_config(*, target: str | None, language: str) -> dict:
    """The answers a demo takes. Nobody is asked anything, and no key is involved."""
    answers = {
        "language": language,
        "project_name": DEMO_PROJECT_NAME,
        # The owner profile is the example's own, copied verbatim (see generate()).
        "data": {"mode": "demo"},
        "contract": {"mode": "demo"},
        "models": {"embedding": DEMO_EMBEDDING},
        "advanced": {
            "user_id": DEMO_USER_ID,
            # Semantic is the product default. Keyless it falls back to mechanical
            # sentence chunking automatically (framework behavior), so the shipped
            # library's keyless restore stays deterministic — and the moment a key
            # lands in .env, fresh ingests get LLM boundary detection.
            "chunk_strategy": "semantic",
            "challenge_enabled": False,
            "answer_style": "conversational",
            # A demo generated with --lang zh is a Chinese project end to end: its README,
            # its contract guidance and — since the framework ships a pack for it — the
            # prompts its models read.
            "prompt_language": language,
        },
    }
    return build_config(answers, target=target)


def demo_start(project: Path) -> int:
    """Start the stack + browsing layer, restore the shipped library, print where to look."""
    import subprocess

    web_port = env_value(project, "PNEUMA_APP_WEB_PORT")
    say()
    say(bold("Starting the stack and the browsing layer…"))
    say(dim("  (the first image build takes a few minutes; nothing here needs an API key)"))
    up = subprocess.run(
        ["docker", "compose", "--profile", "console", "up", "-d", "--wait"], cwd=project
    )
    if up.returncode != 0:
        say()
        say("docker compose failed. Once docker is healthy, finish by hand:")
        say(f"  cd {project}")
        say("  docker compose --profile console up -d --wait")
        say("  ./app.py restore")
        return up.returncode
    say()
    say(bold("Loading the shipped library (no model calls)…"))
    restored = subprocess.run(["./app.py", "restore"], cwd=project)
    if restored.returncode != 0:
        say()
        say(f"the library did not restore. Retry with:  cd {project} && ./app.py restore")
        return restored.returncode

    say()
    say(bold(f"✓ Demo ready:  http://127.0.0.1:{web_port}"))
    say()
    say(bold("Three things to try:"))
    say("  1. " + bold("Read the library") + " — open a canonical document and click any")
    say("     citation: it lands on the exact passage of the raw material it came from.")
    say("  2. " + bold("Look at the material") + " — 190 sources, verbatim, with the compile")
    say("     history beside them: what was compiled, when, and into what.")
    say("  3. " + bold("Open the Engine Console") + " — the projection of engine/: change one")
    say("     knob, read its stated blast radius, apply once with a label, and watch the")
    say("     version appear on the timeline (engine/ is its own git repository).")
    say()
    say(dim("Want to watch a compile? Put an OpenRouter key in .env, then:"))
    say(dim(f"  cd {project} && ./app.py ingest my-data && ./app.py compile"))
    say(dim("Stop everything:  ") + f"cd {project} && docker compose --profile console down")
    return 0


def demo(*, target: str | None, language: str, start: bool) -> int:
    """Zero-interaction demo: generate a real project that already has a library.

    Same generator, same machinery, same engine layout as any project — the difference is the
    payload it arrives with (a compiled library plus a few raw materials) and the fact that
    nothing is asked and no key is needed. The default target is a fresh temporary directory,
    echoed as an absolute path, because a demo should leave nothing where you keep your work."""
    import shutil as _shutil
    import tempfile

    if start:
        missing = [tool for tool in ("docker", "uv") if _shutil.which(tool) is None]
        if missing:
            sys.exit(
                "error: demo mode starts a stack and needs " + " and ".join(missing) + ".\n"
                "Install them (https://docs.docker.com/get-docker/, https://docs.astral.sh/uv/)\n"
                "or generate without starting: ./init.py --demo --no-start"
            )
    destination = target or tempfile.mkdtemp(prefix="pneuma-demo-")
    config = demo_config(target=destination, language=language)
    say(bold("pneuma-knowledge · demo"))
    say(dim("  A complete knowledge base that is already compiled: no questions, no API key."))
    say(dim(f"  Project directory: {Path(config['target']).expanduser().resolve()}"))
    project = generate(config)
    if start:
        return demo_start(project)
    say()
    say(bold("Start it whenever you like:"))
    say(f"  cd {project}")
    say("  docker compose --profile console up -d --wait   " + dim("# first build: a few minutes"))
    say("  ./app.py restore                               " + dim("# load the shipped library"))
    say(f"  open http://127.0.0.1:{env_value(project, 'PNEUMA_APP_WEB_PORT')}")
    return 0


# ------------------------------------------------------------------ interactive flow

def interactive(preset_lang: str | None) -> dict:
    """Feature-guided setup: each step introduces what a thing is FOR in one breath, offers
    the example as the default, echoes what was chosen, and moves on. Nobody is asked about
    anything they cannot be expected to have an opinion on (ports, tenant ids, chunking)."""
    if not sys.stdin.isatty():
        sys.exit(
            "stdin is not a terminal: interactive mode needs a person. "
            "Agents/scripts use --answers FILE (--print-schema shows the format)."
        )
    total = 6
    say(bold("pneuma-knowledge · project generator"))
    say(dim("  Turns your raw material (notes, chats, mail) into a compiled, citation-backed"))
    say(dim("  knowledge base you can browse and ask. Enter accepts the suggestion at every step."))

    header(1, total, "Project")
    say(dim("  A project is one self-contained folder: your data, your contract, one stack."))
    name = slugify(ask("Project name", "my-kb"))
    target = ask("Generate into", str(Path.home() / name))
    echo_choice("project", f"{name} → {target}")

    header(2, total, "Documentation language")
    say(dim("  The generated README / contract guidance can be Chinese or English."))
    lang = preset_lang or ("zh" if ask("1) 中文  2) English", "2") == "1" else "en")
    say(dim("  The prompts the MODELS read are a separate knob (engine/prompts/overlays.yaml,"))
    say(dim("  `language`) and stay English by default; a Chinese pack ships too."))
    echo_choice("language", "中文" if lang == "zh" else "English")

    header(3, total, "Owner")
    say(dim("  Owner details are optional. A team or topic library need not impersonate a person."))
    say(dim("  Keep unknown facts blank; facts in the material belong in the sources."))
    display_name = ask("Owner display name (optional)", "")
    bio = ask("One line about them (occupation, what they do — optional)", "")
    echo_choice("owner", display_name + (f" — {bio}" if bio else ""))

    header(4, total, "Data")
    say(dim("  Import source-contract JSON or Markdown notes. Use ordered filenames for replay."))
    say(dim("  Enter leaves my-data/ empty for your material. The demo is an optional separate start."))
    use_example = ask("Material directory (or y for bundled example; Enter for empty)", "")
    if not use_example:
        data_mode, data_path = "none", ""
        echo_choice("data", "empty my-data/ directory")
    elif use_example.lower() in ("y", "yes"):
        data_mode, data_path = "example", ""
        for line in sample_material(EXAMPLE / "data"):
            say(line)
        echo_choice("data", "bundled demo dataset (shown above)")
    else:
        candidate = Path(use_example).expanduser()
        if candidate.is_dir():
            data_mode, data_path = "path", str(candidate.resolve())
            for line in sample_material(candidate):
                say(line)
            echo_choice("data", f"your directory {data_path} (sampled above)")
        else:
            say(f"  (not a directory: {candidate} — starting empty; drop .md files into my-data/ later)")
            data_mode, data_path = "none", ""
            echo_choice("data", "empty for now")

    header(5, total, "Answer style")
    say(dim("  How Q&A answers read. 1) concise — one compact value for API/automation"))
    say(dim("  consumers  2) conversational — a natural chat reply (default)  3) detailed —"))
    say(dim("  a self-contained written note. Changeable later in engine/recall/recall.yaml"))
    say(dim("  (or the Engine Console), and per question with ./app.py ask --style."))
    style_pick = ask("Answer style (1/2/3)", "2").strip()
    answer_style = {"1": "concise", "2": "conversational", "3": "detailed"}.get(
        style_pick, "conversational"
    )
    echo_choice("answer style", answer_style)

    header(6, total, "Models & key")
    say(dim("  Everything runs through OpenRouter with one key. The compile model must support"))
    say(dim("  tool calling; these defaults do. engine/engine.yaml is where you change the model"))
    say(dim("  roles later, and compare them on your own material (the Engine Console edits the"))
    say(dim("  same file)."))
    echo_choice("models", f"compile/recall {DEFAULT_MODELS['compile'].split(':', 1)[1]}, embeddings {DEFAULT_MODELS['embedding'].split(':', 1)[1]}")
    try:
        api_key = getpass.getpass("  OpenRouter API key (hidden; Enter to skip — .env holds the key) > ").strip()
    except EOFError:
        api_key = ""
    echo_choice("key", "provided" if api_key else "skipped — fill .env before ./start.sh")

    answers = {
        "language": lang,
        "project_name": name,
        "owner": {"display_name": display_name, "bio": bio},
        "data": {"mode": data_mode, "path": data_path},
        "advanced": {"answer_style": answer_style},
    }
    config = build_config(answers, target=target)
    config["api_key"] = api_key

    say()
    contract_note = "bundled demo contract" if config["contract_mode"] == "example" else "source-grounded starter for your domain"
    say(bold("About to generate: ") + f"{config['target']}  ·  docs {lang}  ·  data {data_mode}  ·  contract {contract_note}")
    if ask("Proceed? (y/n)", "y").lower() not in ("y", "yes"):
        sys.exit("cancelled.")
    return config


# ------------------------------------------------------------------ entry point

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a pneuma-knowledge project")
    parser.add_argument("--answers", help="answers file (.toml / .json) — non-interactive mode")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="zero-interaction demo: generate a project that already has a compiled library, "
        "start it, and print where to look (no questions, no API key)",
    )
    parser.add_argument(
        "--no-start",
        action="store_true",
        help="with --demo: generate only, do not start docker",
    )
    parser.add_argument("--target", help="target directory (overrides answers.target / default ~/<name>)")
    parser.add_argument("--lang", choices=("zh", "en"), help="preselect the documentation language")
    parser.add_argument("--key-from-env", metavar="VAR", help="read OPENROUTER_API_KEY from this environment variable")
    parser.add_argument("--print-schema", action="store_true", help="print a commented answers-file template and exit")
    parser.add_argument("--list-references", action="store_true", help="list built-in reference strategies and exit")
    args = parser.parse_args()

    if args.print_schema:
        print(SCHEMA_TOML, end="")
        return 0
    if args.list_references:
        repo = find_framework_repo()
        for entry in strategies_catalog(repo) if repo else []:
            print(f"{entry['skill_id']}@{entry['version']}  —  {entry['domain']}: {entry['summary']}")
        return 0

    if args.demo:
        if args.answers:
            sys.exit("error: --demo takes no answers file (it is the answers).")
        return demo(target=args.target, language=args.lang or "zh", start=not args.no_start)

    if args.answers:
        answers = load_answers(Path(args.answers).expanduser())
        if args.lang:
            answers["language"] = args.lang
        config = build_config(answers, target=args.target)
        if args.key_from_env:
            config["api_key"] = os.environ.get(args.key_from_env, "").strip()
            if not config["api_key"]:
                sys.exit(f"error: environment variable {args.key_from_env} is empty.")
    else:
        config = interactive(args.lang)
        if args.target:
            config["target"] = str(Path(args.target).expanduser())

    generate(config)
    return 0


if __name__ == "__main__":
    sys.exit(main())
