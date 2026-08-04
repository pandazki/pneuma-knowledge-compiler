#!/usr/bin/env python3
"""Generate a pneuma-knowledge project — the scaffold's single entry point.

Two modes over the same generator:

    ./init.py                                 # interactive: guided setup for a person
    ./init.py --answers my.toml --target DIR  # single command: a coding agent (or CI)
                                              #   supplies the same answers as TOML/JSON
    ./init.py --print-schema                  # print a commented answers-file template

What generation does: copy the runtime machinery verbatim (app.py / start.sh /
docker-compose.yml — users never edit these), render the user-owned files (contract.md,
profile.yaml, README.md, AGENTS.md, .env) in the chosen documentation language, probe
free localhost ports for the middleware stack (users never think about ports — they are
random, private to the project, and echoed on startup), and print the next steps.

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
import shutil
import socket
from pathlib import Path

sys.dont_write_bytecode = True

SCAFFOLD_DIR = Path(__file__).resolve().parent
TEMPLATES = SCAFFOLD_DIR / "templates"
EXAMPLE = SCAFFOLD_DIR / "example"

MACHINERY = ("app.py", "start.sh", "docker-compose.yml")

DEFAULT_MODELS = {
    "compile": "openrouter:openai/gpt-5.6-luna",
    "recall": "openrouter:openai/gpt-5.6-luna",
    "embedding": "openrouter:openai/text-embedding-3-small",
    "deep": "",
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
display_name = "Someone"   # how the owner is addressed
occupation = ""            # one-line occupation
bio = ""                   # a sentence or two of background
interests = []             # long-term interest keywords, e.g. ["hiking", "open source"]
industry = "other"         # tech/finance/sports/creative/education/healthcare/marketing/other
role = "other"             # engineering/marketing/product_management/sales/design/support/admin/other
level = "mid"              # entry/junior/mid/senior/staff/principal

[data]
mode = "example"           # example = bundled demo dataset | path = my own directory | none = empty
path = ""                  # absolute path when mode = "path"; read at ingest time, never copied

[contract]
mode = "auto"              # auto = follow the data (example data → demo contract, else skeleton)
                           # skeleton = TODO-slot skeleton | example = bundled demo contract
                           # reference = start from a built-in strategy (fill reference below)
reference = ""             # e.g. "personal-knowledge@v1" (list with ./init.py --list-references)

[models]
compile = "openrouter:openai/gpt-5.6-luna"        # compile model (must support tool calling; the quality lever)
recall = "openrouter:openai/gpt-5.6-luna"         # Q&A model (fast and cheap is fine)
embedding = "openrouter:openai/text-embedding-3-small"
deep = ""                  # deep-recall model; empty falls back to recall

[advanced]
user_id = "u-app-owner"    # tenant id: a different id is a different, empty library
chunk_strategy = "semantic"  # semantic = LLM boundary detection (default) | sentence = mechanical
challenge_enabled = false  # post-compile coverage challenge (extra model calls per compile)
answer_style = "conversational"  # how Q&A answers read: concise = the bare exact answer
                           # (graders/scripts) | conversational = natural chat reply |
                           # detailed = self-contained written note
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
    paths = sorted(p for p in directory.glob("*.md") if p.name.lower() != "readme.md")
    out = [f"  {len(paths)} .md files, e.g.:"]
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
        "display_name": str(owner_in.get("display_name") or "Someone"),
        "occupation": str(owner_in.get("occupation") or ""),
        "bio": str(owner_in.get("bio") or ""),
        "interests": [str(i) for i in (owner_in.get("interests") or [])],
    }
    for enum_field, allowed in ENUMS.items():
        value = str(owner_in.get(enum_field) or ("mid" if enum_field == "level" else "other"))
        if value not in allowed:
            sys.exit(f"error: owner.{enum_field} value {value!r} not in {sorted(allowed)}")
        owner[enum_field] = value

    data_in = dict(answers.get("data") or {})
    data_mode = str(data_in.get("mode") or "example")
    if data_mode not in ("example", "path", "none"):
        sys.exit(f"error: data.mode must be example / path / none, got {data_mode!r}")
    data_path = str(data_in.get("path") or "")
    if data_mode == "path":
        if not data_path:
            sys.exit("error: data.mode = path requires data.path")
        resolved = Path(data_path).expanduser().resolve()
        if not resolved.is_dir():
            sys.exit(f"error: data.path is not a directory: {resolved}")
        if not list(resolved.glob("*.md")):
            print(f"  note: no .md files in {resolved} yet (the ingester reads .md only).")
        data_path = str(resolved)

    contract_in = dict(answers.get("contract") or {})
    contract_mode = str(contract_in.get("mode") or "auto")
    if contract_mode == "auto":
        contract_mode = "example" if data_mode == "example" else "skeleton"
    if contract_mode not in ("skeleton", "example", "reference"):
        sys.exit(f"error: contract.mode must be auto / skeleton / example / reference, got {contract_mode!r}")
    reference = str(contract_in.get("reference") or "")
    if contract_mode == "reference" and "@" not in reference:
        sys.exit("error: contract.mode = reference requires contract.reference (like skill_id@version)")

    models_in = dict(answers.get("models") or {})
    models = {key: str(models_in.get(key) or default) for key, default in DEFAULT_MODELS.items()}

    advanced_in = dict(answers.get("advanced") or {})
    chunk_strategy = str(advanced_in.get("chunk_strategy") or "semantic")
    if chunk_strategy not in ("semantic", "sentence"):
        sys.exit(f"error: advanced.chunk_strategy must be semantic / sentence, got {chunk_strategy!r}")
    answer_style = str(advanced_in.get("answer_style") or "conversational")
    if answer_style not in ("concise", "conversational", "detailed"):
        sys.exit(
            "error: advanced.answer_style must be concise / conversational / detailed, "
            f"got {answer_style!r}"
        )

    return {
        "language": language,
        "project_name": project_name,
        "target": str(Path(target).expanduser() if target else Path.home() / project_name),
        "owner": owner,
        "data_mode": data_mode,
        "data_path": data_path,
        "contract_mode": contract_mode,
        "reference": reference,
        "models": models,
        "user_id": str(advanced_in.get("user_id") or "u-app-owner"),
        "chunk_strategy": chunk_strategy,
        "answer_style": answer_style,
        "challenge_enabled": bool(advanced_in.get("challenge_enabled") or False),
        "api_key": "",
    }


# ------------------------------------------------------------------ generation

def make_env_text(config: dict, ports: dict[str, int], compose_project: str, repo: Path) -> str:
    lines = [
        f"# Environment for {config['project_name']} — generated by scaffold/init.py.",
        "# The API key lives in this file only (gitignored), never committed.",
        "",
        "# OpenRouter API key (https://openrouter.ai/keys)",
        f"OPENROUTER_API_KEY={config['api_key']}",
        "",
        "# Compile model: must support tool calling. This is the quality lever —",
        "# a stronger model directly produces a better library.",
        f"PNEUMA_APP_COMPILE_MODEL={config['models']['compile']}",
        "# Q&A model: fast and cheap is fine.",
        f"PNEUMA_APP_RECALL_MODEL={config['models']['recall']}",
        "# Embedding model (same key).",
        f"PNEUMA_APP_EMBEDDING_MODEL={config['models']['embedding']}",
    ]
    if config["models"]["deep"]:
        lines += [f"PNEUMA_APP_DEEP_MODEL={config['models']['deep']}"]
    else:
        lines += ["# Deep-recall model: empty falls back to RECALL.", "# PNEUMA_APP_DEEP_MODEL="]
    lines += [
        "",
        "# Framework repository (app.py runs via its uv environment).",
        f"PNEUMA_APP_FRAMEWORK_REPO={repo}",
        "",
        "# Compose project name and ports — free ports probed at generation time, private to",
        "# this project. The project name owns the docker volumes; renaming orphans them.",
        f"PNEUMA_APP_COMPOSE_PROJECT={compose_project}",
        f"PNEUMA_APP_PG_PORT={ports['pg']}",
        f"PNEUMA_APP_QDRANT_PORT={ports['qdrant']}",
        f"PNEUMA_APP_QDRANT_GRPC_PORT={ports['qdrant_grpc']}",
        f"PNEUMA_APP_MEILI_PORT={ports['meili']}",
        "# Project-private Docker subnet (probed unused; avoids default address-pool exhaustion).",
        f"PNEUMA_APP_SUBNET={config['subnet']}",
        "",
        "# Tenant id: a different id is a different, empty library.",
        f"PNEUMA_APP_USER_ID={config['user_id']}",
        "# L2 chunking: semantic = LLM boundary detection (default); sentence = mechanical (no LLM cost).",
        f"PNEUMA_APP_CHUNK_STRATEGY={config['chunk_strategy']}",
        "# Q&A answer style: concise = the bare exact answer (graders/scripts) |",
        "# conversational = natural chat reply | detailed = self-contained written note.",
        "# Per-ask override: ./app.py ask '...' --style concise",
        f"PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE={config['answer_style']}",
        "",
        "# Schema evolution: after compiles, the framework may propose reorganizing the",
        "# library once enough new material accrues; proposals wait as reviewable drafts",
        "# (./app.py evolve). On by default; tune the thresholds to your data's rhythm —",
        "# lower them for slow-trickle libraries, raise them for daily bulk feeds.",
        "# PNEUMA_KNOWLEDGE_EVOLVE_AUTO_TRIGGER=true",
        "# PNEUMA_KNOWLEDGE_EVOLVE_TRIGGER_TOPIC_DOCS=5",
        "# PNEUMA_KNOWLEDGE_EVOLVE_TRIGGER_NEW_CLAIMS=30",
        "# PNEUMA_KNOWLEDGE_EVOLVE_DRAFT_TTL_HOURS=24",
    ]
    if config["challenge_enabled"]:
        lines += [
            "# Post-compile coverage challenge: blind questions, gap audit, compensation compiles.",
            "PNEUMA_KNOWLEDGE_CHALLENGE_ENABLED=true",
        ]
    else:
        lines += ["# PNEUMA_KNOWLEDGE_CHALLENGE_ENABLED=true"]
    return "\n".join(lines) + "\n"


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
        "现在还是骨架：标着 TODO 的地方，通读你的材料后用你自己的答案写掉。"
        if zh
        else "Still a skeleton: read your material, then replace every TODO with your own answer."
    )
    return render(template, {"SKILL_ID": skill_id}), hint


def generate(config: dict) -> Path:
    repo = find_framework_repo()
    if repo is None:
        sys.exit("error: framework repository not found — init.py must run from inside the pneuma-knowledge-compiler repo.")

    target = Path(config["target"]).expanduser().resolve()
    if target.exists() and any(target.iterdir()):
        sys.exit(f"error: target directory exists and is not empty: {target}")
    target.mkdir(parents=True, exist_ok=True)

    zh = config["language"] == "zh"
    pg, qdrant, qdrant_grpc, meili = probe_free_ports(4)
    ports = {"pg": pg, "qdrant": qdrant, "qdrant_grpc": qdrant_grpc, "meili": meili}
    config["subnet"] = probe_free_subnet()
    compose_project = f"pneuma-{config['project_name']}-{random.randrange(16**4):04x}"

    # 1) machinery, verbatim
    for name in MACHINERY:
        shutil.copy2(TEMPLATES / name, target / name)
    shutil.copy2(TEMPLATES / "gitignore", target / ".gitignore")

    # 2) contract + profile
    text, contract_hint = contract_text(config, repo)
    (target / "contract.md").write_text(text, encoding="utf-8")
    profile_template = (TEMPLATES / ("profile.zh.yaml" if zh else "profile.en.yaml")).read_text(encoding="utf-8")
    (target / "profile.yaml").write_text(
        render(
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
        ),
        encoding="utf-8",
    )

    # 3) data
    my_data = target / "my-data"
    if config["data_mode"] == "example":
        shutil.copytree(EXAMPLE / "data", my_data)
        shutil.copy2(EXAMPLE / "demo-questions.txt", target / "demo-questions.txt")
    else:
        my_data.mkdir()

    # 4) docs
    readme_template = (TEMPLATES / ("README.project.zh.md" if zh else "README.project.en.md")).read_text(encoding="utf-8")
    agents_template = (TEMPLATES / ("AGENTS.project.zh.md" if zh else "AGENTS.project.en.md")).read_text(encoding="utf-8")
    slots = {
        "PROJECT_NAME": config["project_name"],
        "FRAMEWORK_REPO": str(repo),
        "CONTRACT_HINT": contract_hint,
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
    (target / ".env.example").write_text(example_text, encoding="utf-8")
    os.chmod(target / "app.py", 0o755)
    os.chmod(target / "start.sh", 0o755)

    # 6) next steps
    say()
    say(bold(f"✓ Project generated: {target}"))
    say(dim(f"  stack: compose project {compose_project} · ports pg {pg} / qdrant {qdrant},{qdrant_grpc} / meili {meili} · subnet {config['subnet']}"))
    say(dim("  (ports were probed free and written into .env — nothing for you to manage)"))
    say()
    say(bold("Next steps:"))
    say(f"  cd {target}")
    if not config["api_key"]:
        say("  $EDITOR .env      " + dim("# fill OPENROUTER_API_KEY (https://openrouter.ai/keys)"))
    say("  ./start.sh        " + dim("# end to end: start stack → ingest → compile → demo Q&A"))
    if config["data_mode"] == "path":
        say(f"  ./app.py ingest {config['data_path']}")
        say("                    " + dim("# your material directory (start.sh ingests my-data/ by default)"))
    if config["data_mode"] == "none":
        say("  " + dim("drop .md material into my-data/ (with date: frontmatter), then run ./start.sh"))
    return target


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
    echo_choice("language", "中文" if lang == "zh" else "English")

    header(3, total, "Owner")
    say(dim("  The library belongs to one person; compiles read their profile to know whose"))
    say(dim("  perspective the material is written from. Facts stay in the material — this is"))
    say(dim("  just the introduction line."))
    display_name = ask("Name to address the owner by", "Someone")
    bio = ask("One line about them (occupation, what they do — optional)", "")
    echo_choice("owner", display_name + (f" — {bio}" if bio else ""))

    header(4, total, "Data")
    say(dim("  The compiler eats .md files (one file = one material, date: in frontmatter)."))
    say(dim("  No data ready? Start with the bundled demo dataset — two weeks of a fictional"))
    say(dim("  indie developer's notes and chats — and swap in your own later."))
    use_example = ask("Use the bundled demo dataset? (y = demo, or paste a directory path)", "y")
    if use_example.lower() in ("y", "yes", ""):
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
    say(dim("  How Q&A answers read. 1) concise — the bare exact answer (for graders and"))
    say(dim("  scripts)  2) conversational — a natural chat reply (default)  3) detailed —"))
    say(dim("  a self-contained written note. Changeable later in .env, or per ask with --style."))
    style_pick = ask("Answer style (1/2/3)", "2").strip()
    answer_style = {"1": "concise", "2": "conversational", "3": "detailed"}.get(
        style_pick, "conversational"
    )
    echo_choice("answer style", answer_style)

    header(6, total, "Models & key")
    say(dim("  Everything runs through OpenRouter with one key. The compile model is the only"))
    say(dim("  quality lever — defaults are sensible, and .env is where you change them later."))
    echo_choice("models", f"compile/recall {DEFAULT_MODELS['compile'].split(':', 1)[1]}, embeddings {DEFAULT_MODELS['embedding'].split(':', 1)[1]}")
    try:
        api_key = getpass.getpass("  OpenRouter API key (hidden; Enter to skip and fill .env later) > ").strip()
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
    contract_note = "bundled demo contract" if config["contract_mode"] == "example" else "TODO skeleton for your own domain"
    say(bold("About to generate: ") + f"{config['target']}  ·  docs {lang}  ·  data {data_mode}  ·  contract {contract_note}")
    if ask("Proceed? (y/n)", "y").lower() not in ("y", "yes"):
        sys.exit("cancelled.")
    return config


# ------------------------------------------------------------------ entry point

def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a pneuma-knowledge project")
    parser.add_argument("--answers", help="answers file (.toml / .json) — non-interactive mode")
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
