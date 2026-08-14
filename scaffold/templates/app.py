#!/usr/bin/env python3
"""Driver CLI for the pneuma-knowledge application scaffold.

One command per action; `demo` runs the whole chain end to end:

    ./app.py up                 # start the local middleware stack (compose up + health wait)
    ./app.py init               # detect timezone/language/region from the system, write them
                                #   back into profile.yaml and record their provenance
    ./app.py ingest [dir]       # ingest material (defaults to my-data; the occurrence
                                #   date comes from the frontmatter `date`)
    ./app.py compile            # drain the compile queue (real models)
    ./app.py ask "question"     # fast-path Q&A (--sources also prints the cited raw text)
    ./app.py glance             # print an overview of the current library (no re-ingest)
    ./app.py restore            # restore the library shipped in prebuilt/, if this project
                                #   ships one (no API key needed — nothing here calls a model)
    ./app.py evolve [action]    # schema evolution: list / run / show / adopt / drop proposals
    ./app.py status             # stack and library status
    ./app.py demo [--yes]       # up → init → ingest → compile → demo questions (if any) → glance
    ./app.py preflight          # pre-flight check (is the framework repository reachable?)
    ./app.py down [--volumes]   # stop the stack (--volumes also deletes the data volumes)

Framework dependencies resolve through the uv environment of the pneuma-knowledge-compiler
repository: while the scaffold lives inside the repository the parent directories are probed
automatically; once copied outside it, set PNEUMA_APP_FRAMEWORK_REPO in .env. The top level of
this file uses the standard library only — every framework import is deferred into a subcommand,
and when the environment is missing the process re-execs itself via `uv run --project`.

Strategy is NOT configured here and not in `.env`: it lives in `engine/` — the project's own
versioned unit holding the model roles, chunking, answering, challenge and evolve knobs, the
compile contract, the owner profile and any prompt overlays (see `engine/README.md`). This
driver resolves them through the framework's own precedence chain — process environment >
engine file > framework default — so the CLI, the API and the Engine Console can never
disagree about what this engine is configured to do. `.env` holds only the API key and this
machine's infrastructure.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# This driver is run in place inside the generated project — never leave __pycache__ behind.
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

# ---------------------------------------------------------------- constants and paths

PROJECT_ROOT = Path(__file__).resolve().parent
ENV_PATH = PROJECT_ROOT / ".env"
# The engine: one versioned directory (its own git repository) holding everything that IS
# this project's engine. The two documents inside it are addressed directly because this
# driver parses them itself; the strategy files are read through the framework's resolver.
ENGINE_DIR = PROJECT_ROOT / "engine"
PROFILE_PATH = ENGINE_DIR / "persona" / "profile.yaml"
CONTRACT_PATH = ENGINE_DIR / "compile" / "contract.md"
MY_DATA_DIR = PROJECT_ROOT / "my-data"
DATA_ROOT = PROJECT_ROOT / "data"
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
# Optional: a library that ships with the project (canonical.bundle + l0.jsonl.gz, plus
# media/sha256 when that L0 contains images — authority payloads). Present in a project
# generated with `init.py --demo`, absent otherwise;
# `./app.py restore` says so rather than failing obscurely.
PREBUILT_DIR = PROJECT_ROOT / "prebuilt"
# Optional, written by the generator when the project starts from the example dataset:
# one demo question per line, asked at the end of `demo`. Absent → demo skips the Q&A tail.
DEMO_QUESTIONS_PATH = PROJECT_ROOT / "demo-questions.txt"

# Fallbacks only — the generator (scaffold/init.py) probes free ports at generation time
# and writes the real values into .env; these defaults exist so a hand-assembled project
# still starts.
DEFAULT_PG_PORT = 15436
DEFAULT_QDRANT_PORT = 16373
DEFAULT_MEILI_PORT = 17704
DEFAULT_RUSTFS_PORT = 19004

# The deterministic embedding used when no API key is present. Its dimension matches the
# recommended default embedding model, so a vector collection built keyless stays usable
# after a key arrives. An engine that names an embedding model of a different dimension sets
# PNEUMA_APP_KEYLESS_EMBEDDING=fake:<that dimension> in .env.
KEYLESS_EMBEDDING = "fake:1536"

CONTRACT_RULES = (
    "contract.rule.citation_granularity",
    "contract.rule.citation_shape",
    "contract.rule.strength_labels",
)

# --------------------------- environment bootstrap (stdlib only, before any framework import)


def _extend_no_proxy() -> None:
    """A system-wide proxy would also route 127.0.0.1 middleware requests through it — exempt
    the loopback addresses up front."""
    for name in ("NO_PROXY", "no_proxy"):
        parts = [p.strip() for p in os.environ.get(name, "").split(",") if p.strip()]
        for host in ("localhost", "127.0.0.1", "::1"):
            if host not in parts:
                parts.append(host)
        os.environ[name] = ",".join(parts)


def load_env_file(path: Path) -> list[str]:
    """Load KEY=value lines into os.environ (never overriding an existing value). Returns the
    key names that were loaded."""
    if not path.exists():
        return []
    loaded: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def find_framework_repo() -> Path | None:
    """Locate the pneuma-knowledge-compiler repository: explicit configuration wins, otherwise
    probe upwards through the parent directories."""
    explicit = os.environ.get("PNEUMA_APP_FRAMEWORK_REPO", "").strip()
    if explicit:
        path = Path(explicit).expanduser().resolve()
        return path if path.is_dir() else None
    for candidate in PROJECT_ROOT.parents:
        if (candidate / "packages" / "pneuma-knowledge-service").is_dir():
            return candidate
    return None


def ensure_framework() -> None:
    """When the framework is not importable, re-exec ourselves through the framework
    repository's uv environment (exactly once)."""
    try:
        import pneuma_knowledge_service  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("PNEUMA_APP_REEXEC") == "1":
        sys.exit(
            "error: framework package pneuma_knowledge_service still missing after the uv\n"
            "re-exec. Check that PNEUMA_APP_FRAMEWORK_REPO points at the\n"
            "pneuma-knowledge-compiler repository and that `uv sync` has been run there."
        )
    repo = find_framework_repo()
    if repo is None:
        sys.exit(
            "error: framework repository not found. When this project lives outside the\n"
            "repository, set in .env:\n"
            "  PNEUMA_APP_FRAMEWORK_REPO=/absolute/path/to/pneuma-knowledge-compiler"
        )
    os.environ["PNEUMA_APP_REEXEC"] = "1"
    os.execvpe(
        "uv",
        ["uv", "run", "--project", str(repo), "python", str(Path(__file__).resolve()), *sys.argv[1:]],
        os.environ,
    )


# -------------------------------------------------------- pure functions (unit-testable)


def timezone_from_localtime_link(link: str) -> str | None:
    """`/etc/localtime` symlink target → IANA timezone name (e.g. Asia/Shanghai)."""
    match = re.search(r"zoneinfo(?:\.default)?/(.+)$", link)
    if not match:
        return None
    zone = match.group(1).strip("/")
    return zone or None


def detect_timezone() -> str | None:
    """System timezone: the TZ environment variable wins, otherwise the /etc/localtime
    symlink."""
    tz = os.environ.get("TZ", "").strip()
    if "/" in tz:
        return tz
    try:
        link = os.readlink("/etc/localtime")
    except OSError:
        return None
    return timezone_from_localtime_link(link)


def locale_from_lang(lang: str) -> tuple[str | None, str | None]:
    """$LANG (e.g. zh_CN.UTF-8) → (BCP-47 language, region code); (None, None) when it cannot
    be parsed."""
    match = re.match(r"([A-Za-z]{2,3})[_-]([A-Za-z]{2})\b", lang or "")
    if not match:
        return None, None
    return f"{match.group(1).lower()}-{match.group(2).upper()}", match.group(2).upper()


def strip_html_comments(text: str) -> str:
    """Strip `<!-- … -->` comment blocks. Comments in contract.md are guidance for whoever
    edits the contract, not part of the compile judgement — the instructions handed to the
    model keep the body only, which saves tokens and avoids ambiguity."""
    return re.sub(r"<!--.*?-->\n?", "", text, flags=re.DOTALL)


def split_frontmatter(text: str) -> tuple[str, str]:
    """The YAML frontmatter fenced by `---`, plus the body. Returns ("", original text) when
    there is no frontmatter."""
    if not text.startswith("---"):
        return "", text
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?", text, re.DOTALL)
    if not match:
        return "", text
    return match.group(1), text[match.end() :]


def parse_conversation_turns(body: str) -> list[tuple[str, str]]:
    """A sequence of `speaker: content` lines → [(speaker, text)]; a line without a colon is
    folded into the previous turn.

    Multi-word Western names ("Weihua Zhang: …") are speakers too — the previous
    single-token rule silently folded every such line into the prior turn and dissolved
    whole English transcripts (found by the EverMemBench full run). Kept deliberately
    tighter than "anything before a colon": a multi-word speaker requires every token
    capitalized (or CJK), so a prose line like "Note that: …" still folds as
    continuation; single tokens keep the original permissive rule."""
    turns: list[tuple[str, str]] = []
    cap_token = r"[A-Z一-鿿][\w.\-']*"
    multi_re = re.compile(rf"^({cap_token}(?: {cap_token}){{1,3}})[：:]\s*(.*)$")
    single_re = re.compile(r"^([^\s：:]{1,24})[：:]\s*(.*)$")
    for line in body.splitlines():
        line = line.rstrip()
        if not line.strip():
            continue
        match = multi_re.match(line)
        if match and len(match.group(1)) > 48:
            match = None
        match = match or single_re.match(line)
        if match:
            turns.append((match.group(1), match.group(2)))
        elif turns:
            speaker, text = turns[-1]
            turns[-1] = (speaker, f"{text}\n{line.strip()}")
    return turns


def isolation_problems(
    pg_dsn: str,
    qdrant_url: str,
    meili_url: str,
    canonical_root: str,
    media_endpoint_url: str | None = None,
) -> list[str]:
    """Every connection target must land on this project's own stack — the ports written
    into .env (probed free at generation time). A configuration that drifted toward some
    other stack on this machine is caught right here, before anything connects."""
    problems: list[str] = []
    expected_pg = f":{stack_port('PNEUMA_APP_PG_PORT', DEFAULT_PG_PORT)}/"
    if expected_pg not in pg_dsn:
        problems.append(f"pg_dsn does not point at this project's own port (expected {expected_pg.strip(':/')}): {pg_dsn}")
    expected_qdrant = f":{stack_port('PNEUMA_APP_QDRANT_PORT', DEFAULT_QDRANT_PORT)}"
    if expected_qdrant not in qdrant_url:
        problems.append(
            f"qdrant_url does not point at this project's own port (expected {expected_qdrant.strip(':')}): {qdrant_url}"
        )
    expected_meili = f":{stack_port('PNEUMA_APP_MEILI_PORT', DEFAULT_MEILI_PORT)}"
    if expected_meili not in meili_url:
        problems.append(
            f"meili_url does not point at this project's own port (expected {expected_meili.strip(':')}): {meili_url}"
        )
    if media_endpoint_url is not None:
        expected_rustfs = f":{stack_port('PNEUMA_APP_RUSTFS_PORT', DEFAULT_RUSTFS_PORT)}"
        if expected_rustfs not in media_endpoint_url:
            problems.append(
                "media endpoint does not point at this project's own port "
                f"(expected {expected_rustfs.strip(':')}): {media_endpoint_url}"
            )
    root = Path(canonical_root).resolve()
    if not str(root).startswith(str(PROJECT_ROOT)):
        problems.append(f"canonical_root lands outside the project directory: {root}")
    return problems


def stamp_profile_text(text: str, detected: dict[str, str | None]) -> tuple[str, list[str]]:
    """Write the detected timezone/language/region into the profile.yaml text, marking them
    as deployment_default.

    A field is only written when its provenance is unstated or deployment_default — values the
    user has confirmed (provenance: profile) are never touched. Line-by-line text replacement
    rather than a YAML rewrite, so the comments in the file survive.
    Returns (new text, list of field names actually written).
    """
    field_by_locale_key = {"timezone": "timezone", "language": "language", "country": "region"}
    provenance = current_provenance(text)
    writable = {
        field
        for field, source in provenance.items()
        if source in ("unstated", "deployment_default")
    }
    lines = text.splitlines()
    block: str | None = None
    stamped: list[str] = []
    for i, line in enumerate(lines):
        top = re.match(r"^([A-Za-z_]+):", line)
        if top:
            block = top.group(1)
        entry = re.match(r"^(\s+)([A-Za-z_]+):\s*(\"[^\"]*\"|[^#\n]*?)(\s*#.*)?$", line)
        if not entry:
            continue
        indent, key, _, comment = entry.group(1), entry.group(2), entry.group(3), entry.group(4) or ""
        if block == "locale" and key in field_by_locale_key:
            field = field_by_locale_key[key]
            value = detected.get(field)
            if field in writable and value:
                lines[i] = f'{indent}{key}: "{value}"{comment}'
                if field not in stamped:
                    stamped.append(field)
        elif block == "provenance" and key in ("timezone", "language", "region"):
            if key in writable and detected.get(key):
                lines[i] = f"{indent}{key}: deployment_default{comment}"
    return "\n".join(lines) + "\n", stamped


def current_provenance(profile_text: str) -> dict[str, str]:
    """The provenance block of profile.yaml (no yaml dependency, for the pure-function path)."""
    result = {"timezone": "unstated", "language": "unstated", "region": "unstated"}
    block = None
    for line in profile_text.splitlines():
        top = re.match(r"^([A-Za-z_]+):", line)
        if top:
            block = top.group(1)
        if block != "provenance":
            continue
        entry = re.match(r"^\s+(timezone|language|region):\s*([A-Za-z_]+)", line)
        if entry:
            result[entry.group(1)] = entry.group(2)
    return result


def stack_port(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


def dominant_script(text: str) -> str | None:
    """Rough guess at the dominant language of a text: "zh" (mostly Han characters) /
    "en" (mostly Latin letters) / None (can't tell).

    One Han character is roughly one word, and an English word is roughly five letters — the
    two sides are weighed with that crude conversion. A cheap heuristic for the demo flow only;
    no linguistic rigour intended."""
    han = len(re.findall(r"[一-鿿]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    zh_units, en_units = han, latin / 5
    if zh_units + en_units < 20:
        return None
    if zh_units > en_units * 2:
        return "zh"
    if en_units > zh_units * 2:
        return "en"
    return None


def material_language(directory: Path) -> str | None:
    """Dominant language of the .md material in an ingest directory (the opening chunk of each
    file, README excluded)."""
    if not directory.is_dir():
        return None
    samples: list[str] = []
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        try:
            samples.append(path.read_text(encoding="utf-8", errors="ignore")[:4000])
        except OSError:
            continue
    if not samples:
        return None
    return dominant_script("\n".join(samples))


def language_agrees(detected: str | None, material: str | None) -> bool:
    """Whether the detected language and the material's language agree (compared on the primary
    subtag, e.g. en-US → en). If either side is missing, treat them as agreeing."""
    if not detected or not material:
        return True
    return detected.split("-")[0].lower() == material.split("-")[0].lower()


def set_profile_language(text: str, language: str, provenance: str) -> str:
    """Write locale.language and provenance.language into the profile.yaml text (keeping the
    comments intact)."""
    lines = text.splitlines()
    block: str | None = None
    for i, line in enumerate(lines):
        top = re.match(r"^([A-Za-z_]+):", line)
        if top:
            block = top.group(1)
        entry = re.match(r"^(\s+)language:\s*(\"[^\"]*\"|[^#\n]*?)(\s*#.*)?$", line)
        if not entry:
            continue
        indent, comment = entry.group(1), entry.group(3) or ""
        if block == "locale":
            lines[i] = f'{indent}language: "{language}"{comment}'
        elif block == "provenance":
            lines[i] = f"{indent}language: {provenance}{comment}"
    return "\n".join(lines) + "\n"


def profile_language(text: str) -> str:
    """The current value of locale.language in profile.yaml (empty string when unset)."""
    block: str | None = None
    for line in text.splitlines():
        top = re.match(r"^([A-Za-z_]+):", line)
        if top:
            block = top.group(1)
        entry = re.match(r"^\s+language:\s*\"?([^\"#\n]*?)\"?\s*(#.*)?$", line)
        if block == "locale" and entry:
            return entry.group(1).strip()
    return ""


def cited_handles(answer: str) -> list[str]:
    """The short citation handles (s01, s02, …) actually used in the answer text, deduplicated
    in order of first appearance."""
    seen: list[str] = []
    for bracket in re.findall(r"\[cite:\s*([^\]]*)\]", answer):
        for handle in re.findall(r"\bs\d{2,}\b", bracket):
            if handle not in seen:
                seen.append(handle)
    return seen


def citation_legend_lines(
    answer: str, handle_map: dict[str, str], source_info: dict[str, tuple[str, str]]
) -> list[str]:
    """Citation legend: one line per handle used, `s01 = material title（2026-07-11）`.

    `handle_map` is {handle: real source id}, `source_info` is {source id: (title, date)}.
    A handle that cannot be resolved is reported as such rather than guessed at."""
    lines: list[str] = []
    for handle in cited_handles(answer):
        sid = handle_map.get(handle)
        if sid is None:
            lines.append(f"{handle} = (unknown source)")
            continue
        title, date = source_info.get(sid, ("", ""))
        label = title or sid[:8] + "…"
        lines.append(f"{handle} = {label}（{date}）" if date else f"{handle} = {label}")
    return lines


def claims_from_detail(detail: str | None) -> int | None:
    """The number of claims inserted/updated, taken from a finished compile job's detail
    (detail looks like `projection:{...}`)."""
    if not detail or not detail.startswith("projection:"):
        return None
    try:
        payload = json.loads(detail[len("projection:") :])
    except (ValueError, TypeError):
        return None
    value = payload.get("upserted")
    return int(value) if isinstance(value, (int, float)) else None


# -------------------------------------------- configuration assembly (framework layer)


def load_profile() -> dict:
    import yaml

    data = yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        sys.exit(f"error: {PROFILE_PATH} must be a YAML mapping")
    return data


def resolved_timezone(profile: dict) -> tuple[str, str]:
    """(timezone, provenance). Provenance is one of: profile / deployment_default / unstated."""
    locale = profile.get("locale") or {}
    provenance = profile.get("provenance") or {}
    zone = str(locale.get("timezone") or "").strip()
    source = str(provenance.get("timezone") or "unstated").strip()
    if zone and source == "profile":
        return zone, "profile"
    if zone:
        return zone, "deployment_default"
    return "UTC", "unstated"


def user_id() -> str:
    return os.environ.get("PNEUMA_APP_USER_ID", "u-app-owner").strip() or "u-app-owner"


def engine_strategy() -> dict:
    """Every strategy knob the engine directory resolves, as `Settings` init kwargs.

    The framework's own resolver is used rather than a second reading of the same YAML:
    precedence (process environment > engine file > framework default) then has exactly one
    implementation across this CLI, the API and the Engine Console. Note that `.env` is
    loaded into the process environment before anything here runs, so a PNEUMA_KNOWLEDGE_*
    strategy key placed there would outrank the engine file — which is precisely why the
    generated `.env` carries none."""
    from pneuma_knowledge_service.engine.resolve import engine_overrides

    overrides, _resolution = engine_overrides(ENGINE_DIR, os.environ)
    return overrides


def apply_prompt_overlays() -> int:
    """engine/prompts/overlays.yaml → the framework's prompt catalog. Returns how many
    clauses were replaced.

    Two layers, in this order: the `language` knob's language pack becomes the framework's
    own wording, and then this project's overlay clauses are registered on top of it. The
    order is the point — a clause written here must survive the pack, not be taken back by
    it.

    Without this call both would be decoration. An unknown catalog key raises rather than
    being ignored: a silent no-op override is the worst outcome, because the framework's own
    wording keeps reaching the model while the project believes it does not."""
    from pneuma_knowledge_service.engine.files import parse_overlays, read_mapping
    from pneuma_knowledge_service.engine.prompts import active_language, apply_prompt_stack

    overlays = parse_overlays(
        "prompts/overlays.yaml", read_mapping(ENGINE_DIR, "prompts/overlays.yaml")
    )
    return apply_prompt_stack(active_language(ENGINE_DIR, os.environ), overlays)


def keyless_env(env) -> list[str]:
    """Without an API key, configure the whole model-free path. Returns lines to print.

    Browsing a compiled library must never depend on a credential. Chat-model roles are
    deliberately NOT blanked here: the framework treats "openrouter spec without a key"
    as unusable at every dispatch point (asking answers 503, semantic chunking degrades
    mechanically), so the engine file keeps naming this project's models and the console
    shows that truth instead of an env lock. Only the embedding is pinned: its probe runs
    eagerly at startup and the vector collection's dimension is fixed at creation, so the
    keyless process must state a deterministic one.

    Shared by the read-only CLI commands and the compose entrypoints (server.py / worker.py),
    so "what keyless means" has exactly one definition."""
    if env.get("OPENROUTER_API_KEY", "").strip():
        return []
    embedding = env.get("PNEUMA_APP_KEYLESS_EMBEDDING", "").strip() or KEYLESS_EMBEDDING
    env["PNEUMA_KNOWLEDGE_EMBEDDING_MODEL"] = embedding
    return [
        f"  (no OPENROUTER_API_KEY: browsing only — deterministic embeddings {embedding},",
        "   mechanical chunking. The library, its sources and every citation are fully",
        "   readable; asking questions, compiling and AI rewrite need a key.)",
    ]


def require_models(*, require_key: bool = True) -> dict[str, str]:
    """The model roles as the engine resolves them, or a loud exit naming what is
    missing. `answer` and `deep` may legitimately borrow the recall role.

    `require_key=False` is for the paths that call no chat model at all (restore, status,
    glance): there, blank roles are the configuration, not an error."""
    from pneuma_knowledge_service.engine.resolve import resolve_engine

    values = resolve_engine(ENGINE_DIR, os.environ).values
    roles = {
        role: str(values.get(f"models.{role}") or "").strip()
        for role in ("compile", "recall", "embedding")
    }
    missing = [f"engine.yaml: {role}" for role, value in roles.items() if not value]
    if not os.environ.get("OPENROUTER_API_KEY", "").strip():
        missing.append(".env: OPENROUTER_API_KEY")
    if missing and require_key:
        sys.exit(
            "error: this engine is missing required settings:\n  "
            + "\n  ".join(missing)
            + "\nModels live in engine/engine.yaml; the key lives in .env. See README.md."
        )
    roles["answer"] = str(values.get("models.answer") or "").strip() or roles["recall"]
    roles["deep"] = str(values.get("models.deep") or "").strip() or roles["recall"]
    return roles


def build_settings(base_version: str = "", *, require_key: bool = True):
    """App-wide Settings: this machine's infrastructure + everything the engine resolves.

    `base_version` must be the registered contract version whenever the worker may process
    job kinds beyond `compile` (groom/evolve/challenge): those resolve their skill from
    settings rather than from the explicitly passed one, and an empty version fails loudly
    at the first such job."""
    from pneuma_knowledge_service.settings import Settings

    models = require_models(require_key=require_key)
    apply_prompt_overlays()
    profile = load_profile()
    zone, _source = resolved_timezone(profile)
    pg_port = stack_port("PNEUMA_APP_PG_PORT", DEFAULT_PG_PORT)
    qdrant_port = stack_port("PNEUMA_APP_QDRANT_PORT", DEFAULT_QDRANT_PORT)
    meili_port = stack_port("PNEUMA_APP_MEILI_PORT", DEFAULT_MEILI_PORT)
    rustfs_port = stack_port("PNEUMA_APP_RUSTFS_PORT", DEFAULT_RUSTFS_PORT)
    canonical = DATA_ROOT / "canonical"
    canonical.mkdir(parents=True, exist_ok=True)
    kwargs = engine_strategy()
    kwargs.update(
        engine_dir=str(ENGINE_DIR),
        pg_dsn=(
            "postgresql://pneuma_knowledge:"
            f"{os.environ.get('PNEUMA_APP_PG_PASSWORD', 'pneuma_knowledge')}"
            f"@localhost:{pg_port}/pneuma_knowledge"
        ),
        qdrant_url=f"http://localhost:{qdrant_port}",
        qdrant_collection=os.environ.get("PNEUMA_APP_QDRANT_COLLECTION", "pneuma_app_chunks"),
        meili_url=f"http://localhost:{meili_port}",
        meili_key=os.environ.get("PNEUMA_APP_MEILI_KEY", "masterKey_change_me"),
        media_s3_endpoint_url=f"http://localhost:{rustfs_port}",
        media_s3_access_key=os.environ.get("PNEUMA_APP_RUSTFS_ACCESS_KEY", ""),
        media_s3_secret_key=os.environ.get("PNEUMA_APP_RUSTFS_SECRET_KEY", ""),
        canonical_root=str(canonical),
        default_timezone=zone,
        user_schema_packs=False,
        user_schema_base_version=base_version,
        # The base spec and the roles nobody chose in engine.yaml: compile is the strongest
        # thing this project has, so it is the sane fallback, and `deep` empty means "answer
        # deep questions with the recall model".
        llm_model=models["compile"],
        llm_model_deep=models["deep"],
        llm_model_skill="",
        llm_model_evolve="",
        llm_model_live_context="",
    )
    settings = Settings(**kwargs)
    problems = isolation_problems(
        settings.pg_dsn,
        settings.qdrant_url,
        settings.meili_url,
        settings.canonical_root,
        settings.media_s3_endpoint_url,
    )
    if problems:
        sys.exit("error: stack isolation check failed:\n  - " + "\n  - ".join(problems))
    return settings


def load_contract_skill():
    """contract.md → SkillVersion, registered as this deployment's skill base."""
    import yaml
    from pneuma_knowledge_core.skill import SkillVersion, register_skill_base

    frontmatter, body = split_frontmatter(CONTRACT_PATH.read_text(encoding="utf-8"))
    meta = yaml.safe_load(frontmatter) or {}
    skill_id = str(meta.get("skill_id") or "my-knowledge")
    version = str(meta.get("version") or "app-v1")
    templates = [str(t) for t in (meta.get("path_templates") or [])]
    if not templates:
        sys.exit(f"error: frontmatter of {CONTRACT_PATH} is missing path_templates")
    body = strip_html_comments(body).strip()
    if not body:
        sys.exit(f"error: {CONTRACT_PATH} has an empty body (guidance comments do not count)")
    skill = SkillVersion(
        skill_id=skill_id,
        version=version,
        instructions=body,
        path_templates=templates,
        contract_rules=CONTRACT_RULES,
        content_hash=SkillVersion.compute_hash(skill_id, version, body, templates, CONTRACT_RULES),
    )
    register_skill_base(version, skill)
    return skill


async def upsert_owner_profile(ctx, uid) -> None:
    """profile.yaml → UserProfile, persisted. A timezone whose provenance is
    deployment_default is left out of the subject's profile (blank) so the framework can
    honestly declare it as a deployment default."""
    from pneuma_knowledge_core.domain.user import UserProfile

    profile = load_profile()
    locale = profile.get("locale") or {}
    provenance = profile.get("provenance") or {}
    preferences = profile.get("preferences") or {}
    display_name = str(profile.get("display_name") or "Owner").strip() or "Owner"
    zone = str(locale.get("timezone") or "").strip()
    if str(provenance.get("timezone") or "") != "profile":
        # A timezone the subject has not confirmed only takes effect as a deployment default
        # (build_settings already carries it).
        zone = ""
    language = str(locale.get("language") or "").strip()
    payload = {
        "user_id": str(uid),
        "display_name": display_name,
        "avatar": {"initial": display_name[0], "color": "#6C8EBF"},
        "locale": {
            "city": str(locale.get("city") or "").strip(),
            "country": str(locale.get("country") or "").strip(),
            "timezone": zone,
            "language": language,
            "timezone_history": [],
        },
        "industry": str(profile.get("industry") or "other"),
        "role": str(profile.get("role") or "other"),
        "level": str(profile.get("level") or "mid"),
        "occupation": str(profile.get("occupation") or ""),
        "bio": str(profile.get("bio") or ""),
        "interests": [str(x) for x in (profile.get("interests") or [])],
        "workspace": {
            "operating_mode": "independent",
            "primary_stack": "",
            "automation_level": "assisted",
            "active_since": datetime.now(timezone.utc).date().isoformat(),
        },
        "preferences": {
            "response_language": str(preferences.get("response_language") or "").strip()
            or language
            or "zh-CN",
            "units": "metric",
            "privacy_level": "standard",
        },
        "joined_at": datetime.now(timezone.utc).date().isoformat(),
        "source": "user",
    }
    validated = UserProfile.model_validate(payload)
    await ctx.store.upsert_user_profile(uid, validated.model_dump(mode="json", exclude={"level_style"}))


# ---------------------------------------------------------------- subcommands


def cmd_up(_args) -> int:
    if not COMPOSE_FILE.exists():
        sys.exit(f"error: {COMPOSE_FILE} not found")
    print("== Starting the middleware stack (postgres / qdrant / meilisearch / rustfs) ==")
    result = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--wait"],
        cwd=PROJECT_ROOT,
    )
    if result.returncode != 0:
        print("docker compose failed to start", file=sys.stderr)
        return result.returncode
    print(
        "  Stack ready: "
        f"pg :{stack_port('PNEUMA_APP_PG_PORT', DEFAULT_PG_PORT)}  "
        f"qdrant :{stack_port('PNEUMA_APP_QDRANT_PORT', DEFAULT_QDRANT_PORT)}  "
        f"meili :{stack_port('PNEUMA_APP_MEILI_PORT', DEFAULT_MEILI_PORT)}"
        f"  rustfs :{stack_port('PNEUMA_APP_RUSTFS_PORT', DEFAULT_RUSTFS_PORT)}"
    )
    return 0


def cmd_down(args) -> int:
    cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "down"]
    if args.volumes:
        cmd.append("-v")
    return subprocess.run(cmd, cwd=PROJECT_ROOT).returncode


def cmd_init(_args) -> int:
    print("== Detecting system environment into profile.yaml ==")
    tz = detect_timezone()
    language, region = locale_from_lang(os.environ.get("LANG", ""))
    detected = {"timezone": tz, "language": language, "region": region}
    for field, value in detected.items():
        print(f"  detected {field}: {value or '(not detected)'}")
    text = PROFILE_PATH.read_text(encoding="utf-8")
    new_text, stamped = stamp_profile_text(text, detected)
    if stamped:
        PROFILE_PATH.write_text(new_text, encoding="utf-8")
        print(f"  wrote {', '.join(stamped)}, provenance marked deployment_default (system-detected).")
        print("  These are detected values, not your own settings — confirm or edit")
        print("  profile.yaml, then flip the matching provenance entries to profile.")
    else:
        print("  nothing to write (already confirmed, or nothing was detected).")
    return 0


LANGUAGE_NAMES = {"zh": "Chinese", "en": "English"}


def confirm_language(ingest_dir: Path, *, assume_yes: bool) -> None:
    """Put the library's primary language on the table before compiling, so a system-detected
    value never gets to decide it silently.

    When the material's dominant language disagrees with the system-detected one, stop and ask:
    Enter = go with the material's language; a language code can also be typed directly. A
    language the user confirmed out loud is recorded as provenance: profile. The
    non-interactive paths (--yes, or a closed stdin) continue with the material's language but
    keep the provenance at deployment_default — an unconfirmed value must not masquerade as the
    person's own setting."""
    text = PROFILE_PATH.read_text(encoding="utf-8")
    provenance = current_provenance(text)
    if provenance.get("language") == "profile":
        return  # never ask again about a language the user has confirmed
    detected = profile_language(text)
    material = material_language(ingest_dir)
    if language_agrees(detected, material):
        return
    material_name = LANGUAGE_NAMES.get(material or "", material or "")
    print("\n== One thing to confirm first: this library's primary language ==")
    print(f"  The material looks {material_name} ({ingest_dir.name}/), while the system")
    print(f"  language was detected as {detected or '(not detected)'} — they disagree.")
    print("  The primary language shapes how compiles write and which language answers use.")
    if assume_yes:
        choice, confirmed = material or detected, False
        print(f"  (--yes: continuing with the material's language {choice}.)")
    else:
        try:
            raw = input(f"  Which one? [Enter = the material's language {material}; or type a code like en-US] > ")
        except EOFError:
            raw, confirmed = "", False
            choice = material or detected
            print(f"  (not interactive: continuing with the material's language {choice}.)")
        else:
            choice = raw.strip() or (material or detected)
            confirmed = True
    if not choice:
        return
    new_provenance = "profile" if confirmed else "deployment_default"
    PROFILE_PATH.write_text(
        set_profile_language(text, choice, new_provenance), encoding="utf-8"
    )
    source_note = "confirmed by you, provenance set to profile" if confirmed else "unconfirmed, provenance stays deployment_default"
    print(f"  Language set to {choice} ({source_note}).")


async def _ingest(directory: Path) -> int:
    from zoneinfo import ZoneInfo

    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_core.domain.source import ConversationTurn
    from pneuma_knowledge_service.ingest import ingest_conversation
    from pneuma_knowledge_service.ingest_document import ingest_document
    from pneuma_knowledge_service.wiring import build_context

    settings = build_settings()
    profile = load_profile()
    zone, _ = resolved_timezone(profile)
    try:
        tzinfo = ZoneInfo(zone)
    except Exception:  # noqa: BLE001 — unknown timezone falls back to UTC; ingest must not fail over it
        tzinfo = timezone.utc
    files = sorted(
        p
        for p in directory.glob("*.md")
        if p.is_file() and p.name.lower() != "readme.md"
    )
    if not files:
        print(f"error: no ingestable .md files in {directory}", file=sys.stderr)
        return 1
    ctx = await build_context(settings)
    try:
        uid = UserId(user_id())
        await upsert_owner_profile(ctx, uid)
        print(f"== Ingesting {len(files)} materials (user={uid}, timezone {zone}) ==")
        for path in files:
            frontmatter, body = split_frontmatter(path.read_text(encoding="utf-8"))
            import yaml

            meta = yaml.safe_load(frontmatter) or {}
            date = str(meta.get("date") or "").strip()
            if not date:
                match = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name)
                date = match.group(1) if match else ""
            title = str(meta.get("title") or path.stem)
            kind = str(meta.get("type") or "note").strip()
            source_meta = {"occurred_on": date} if date else {}
            if kind == "conversation":
                at = None
                if date:
                    at = datetime.fromisoformat(date).replace(hour=12, tzinfo=tzinfo)
                turns = [
                    ConversationTurn(speaker=speaker, text=text, at=at)
                    for speaker, text in parse_conversation_turns(body)
                ]
                if not turns:
                    print(f"  skipping {path.name}: no conversation turns parsed")
                    continue
                result = await ingest_conversation(ctx, uid, turns, title=title, meta=source_meta)
            else:
                result = await ingest_document(
                    ctx, uid, title=title, text=body.strip(), declared_type="note", meta=source_meta
                )
            flag = " (duplicate, skipped)" if result.deduplicated else ""
            print(f"  {path.name} → source {str(result.source_id)[:8]}… {flag}")
        print("  Ingest done. Index and compile jobs queued — next: `./app.py compile`.")
    finally:
        await ctx.aclose()
    return 0


def cmd_ingest(args) -> int:
    directory = Path(args.directory).resolve() if args.directory else MY_DATA_DIR
    if not directory.is_dir():
        sys.exit(f"error: directory does not exist: {directory}")
    return asyncio.run(_ingest(directory))


def _attach_usage_tracker(model):
    from langchain_core.callbacks import UsageMetadataCallbackHandler

    tracker = UsageMetadataCallbackHandler()
    existing = list(getattr(model, "callbacks", None) or [])
    model.callbacks = existing + [tracker]
    return tracker


def _usage_totals(tracker) -> dict[str, int]:
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    for usage in (tracker.usage_metadata or {}).values():
        for key in totals:
            totals[key] += int(usage.get(key, 0) or 0)
    return totals


def _unresolved_failures(jobs: list[dict]) -> list[dict]:
    """Jobs that ended in failure, minus the ones a later retry resolved: once every source of
    a failed compile job is covered by a successful job, that failure is just history and no
    longer counts as unresolved."""
    ok_sources: set[str] = set()
    for job in jobs:
        if job.get("kind") == "compile" and job.get("ok") is True:
            ok_sources.update(str(s) for s in (job.get("payload") or {}).get("source_ids", []))
    unresolved: list[dict] = []
    for job in jobs:
        if job.get("status") != "done" or job.get("ok") is True:
            continue
        sources = {str(s) for s in (job.get("payload") or {}).get("source_ids", [])}
        if job.get("kind") == "compile" and sources and sources <= ok_sources:
            continue
        unresolved.append(job)
    return unresolved


def _job_progress_line(
    job: dict, index: int, total: int, titles: dict[str, str], eta: float | None
) -> str:
    """One progress line per finished job: index, material name, outcome (claim count), plus an
    estimated time remaining when one is available."""
    sources = [str(s) for s in (job.get("payload") or {}).get("source_ids", [])]
    if not sources and (job.get("payload") or {}).get("source_id"):
        sources = [str(job["payload"]["source_id"])]
    names = ", ".join(titles.get(s, s[:8] + "…") for s in sources) or "(no matching material)"
    kind = job.get("kind")
    if kind == "index":
        outcome = "indexed"
    elif job.get("ok") is True:
        claims = claims_from_detail(job.get("detail"))
        outcome = f"+{claims} claims" if claims is not None else "done"
    else:
        outcome = "rejected by the gate (auto-retried later)"
    tail = f" (~{max(1, round(eta))}s left)" if eta and eta > 0 else ""
    return f"  job {index}/{total}: {names} {outcome}{tail}"


async def _drain_with_progress(ctx, model, skill, uid) -> int:
    """Drain the queue, but not in silence: print one progress line per finished job.

    The framework's drain is a black box that runs to completion in one go — so it is put on a
    background task while the main coroutine peeks at the job table every two seconds, reports
    newly finished jobs one by one, and roughly estimates the time remaining from the average
    per-job duration."""
    from pneuma_knowledge_service.workers.compile_worker import drain_user

    jobs = await ctx.store.list_jobs(uid)
    reported = {j["job_id"] for j in jobs if j.get("status") == "done"}
    total = len([j for j in jobs if j.get("status") != "done"])
    titles = {str(s.source_id): s.title for s in await ctx.store.list(uid)}
    started = time.perf_counter()
    finished = 0
    drain = asyncio.create_task(drain_user(ctx, model, skill, uid))
    try:
        while True:
            done = drain.done()
            jobs = await ctx.store.list_jobs(uid)
            pending = [j for j in jobs if j.get("status") != "done"]
            fresh = [
                j
                for j in reversed(jobs)  # list_jobs is newest-first; reverse it to report in completion order
                if j.get("status") == "done" and j["job_id"] not in reported
            ]
            total = max(total, finished + len(fresh) + len(pending))  # retries add new jobs
            for job in fresh:
                reported.add(job["job_id"])
                finished += 1
                remaining = total - finished
                eta = (
                    (time.perf_counter() - started) / finished * remaining
                    if remaining > 0
                    else None
                )
                print(_job_progress_line(job, finished, total, titles, eta))
            if done:
                return await drain
            await asyncio.sleep(2.0)
    finally:
        if not drain.done():
            drain.cancel()


async def _compile() -> tuple[int, dict[str, int]]:
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.wiring import build_context

    skill = load_contract_skill()
    settings = build_settings(base_version=skill.version)
    ctx = await build_context(settings)
    usage: dict[str, int] = {}
    try:
        uid = UserId(user_id())
        await upsert_owner_profile(ctx, uid)
        # A drain killed mid-job (Ctrl-C, agent timeout, machine sleep) leaves its claim
        # orphaned, and claim_next then refuses this user's queue forever — the worker
        # service self-heals on startup, but this in-process drain is many users' ONLY
        # drain path, so it must heal too or one interrupted compile bricks the project.
        from pneuma_knowledge_service.workers.compile_worker import requeue_orphaned_jobs

        await requeue_orphaned_jobs(ctx, label="app-compile")
        model = ctx.get_chat_model("compile")
        tracker = _attach_usage_tracker(model)
        print(f"== Draining the compile queue (user={uid}, contract {skill.skill_id}@{skill.version}) ==")
        started = time.perf_counter()
        processed = await _drain_with_progress(ctx, model, skill, uid)
        # The compile gate (citation traceability and friends) occasionally rejects a single
        # model output — give the gate-rejected compile jobs one more round before passing
        # judgement. Only what still fails after the retry is reported as a failure.
        failures = _unresolved_failures(await ctx.store.list_jobs(uid))
        retriable = [j for j in failures if j.get("kind") == "compile"]
        if retriable:
            print(f"  {len(retriable)} compile jobs rejected by the gate — one retry round…")
            seen: set[str] = set()
            for job in retriable:
                payload = job.get("payload") or {}
                sources = [
                    str(s)
                    for s in payload.get("source_ids", [])
                    if str(s) not in seen
                ]
                if not sources:
                    continue
                seen.update(sources)
                # Carry the per-source treatments over: without them the retry compiles at
                # the plan's default, so a source the caller asked to only DISTIL gets
                # digested in full — the retry would quietly overrule the intake decision.
                treatments = {
                    sid: t
                    for sid, t in (payload.get("treatments") or {}).items()
                    if str(sid) in set(sources)
                }
                retry_payload = {"source_ids": sources}
                if treatments:
                    retry_payload["treatments"] = treatments
                await ctx.store.enqueue(uid, "compile", retry_payload)
            processed += await _drain_with_progress(ctx, model, skill, uid)
            failures = _unresolved_failures(await ctx.store.list_jobs(uid))
        elapsed = time.perf_counter() - started
        usage = _usage_totals(tracker)
        docs = await ctx.canonical.list(uid)
        claims = await ctx.store.list_canonical_claims(uid)
        print(
            f"  Processed {processed} jobs in {elapsed:.1f}s; "
            f"{len(docs)} canonical documents, {len(claims)} claims."
        )
        print(
            f"  Compile-model tokens: input={usage['input_tokens']} "
            f"output={usage['output_tokens']} total={usage['total_tokens']}"
        )
        if failures:
            print("  Unresolved failed jobs:")
            for job in failures:
                print(f"    job {job.get('job_id')} kind={job.get('kind')} detail={str(job.get('detail'))[:120]}")
            return 1, usage
        await ctx.flush_traces()
    finally:
        await ctx.aclose()
    return 0, usage


def cmd_compile(_args) -> int:
    code, _usage = asyncio.run(_compile())
    return code


# ---------------------------------------------------------------- schema evolution

async def _evolve_ctx():
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.wiring import build_context

    skill = load_contract_skill()
    settings = build_settings(base_version=skill.version)
    ctx = await build_context(settings)
    return ctx, UserId(user_id())


async def _evolve_list() -> int:
    from pneuma_knowledge_service.evolve_service import list_tasks_with_expiry

    ctx, uid = await _evolve_ctx()
    try:
        tasks = await list_tasks_with_expiry(ctx, uid)
        if not tasks:
            print("No evolve tasks yet. The trigger fires after compiles once enough new")
            print("material accrues (see EVOLVE_* in .env), or run `./app.py evolve run`.")
            return 0
        for task in tasks:
            line = f"  {task['task_id']}  {task['status']:<10}  {task.get('summary') or task.get('detail') or ''}"
            print(line[:120])
        print("Inspect one: ./app.py evolve show <task_id>   adopt/drop: ./app.py evolve adopt|drop <task_id>")
    finally:
        await ctx.aclose()
    return 0


async def _evolve_show(task_id: str) -> int:
    from pneuma_knowledge_service.evolve_service import get_task_with_expiry

    ctx, uid = await _evolve_ctx()
    try:
        task = await get_task_with_expiry(ctx, uid, task_id)
        if task is None:
            print(f"error: evolve task not found: {task_id}", file=sys.stderr)
            return 1
        print(f"task    {task['task_id']}  status={task['status']}")
        if task.get("summary"):
            print(f"summary {task['summary']}")
        proposal = task.get("proposal") or {}
        rationale = proposal.get("rationale") if isinstance(proposal, dict) else None
        if not rationale and task["status"] == "no_change":
            rationale = task.get("detail")
        if rationale:
            print(f"why     {rationale}")
        if isinstance(proposal, dict):
            for family in proposal.get("families", []) or []:
                print(f"family  {family}")
            for tpl in proposal.get("path_templates", []) or []:
                print(f"path    {tpl}")
        if task.get("branch"):
            print(f"branch  {task['branch']}  (draft changes live here until adopted)")
    finally:
        await ctx.aclose()
    return 0


async def _evolve_enqueue(kind: str, payload: dict) -> int:
    from pneuma_knowledge_service.evolve_service import has_pending_evolve

    ctx, uid = await _evolve_ctx()
    try:
        if kind == "evolve" and await has_pending_evolve(ctx, uid):
            print("error: an evolve draft is already awaiting review (adopt or drop it first).", file=sys.stderr)
            return 1
        await ctx.store.enqueue(uid, kind, payload)
    finally:
        await ctx.aclose()
    # The queue's doctor is the compile drain — reuse it so the job runs to completion
    # right here instead of sitting queued until the next compile.
    code, _usage = await _compile()
    return code


async def _evolve_drop(task_id: str) -> int:
    from pneuma_knowledge_service.evolve_service import drop_task, get_task_with_expiry

    ctx, uid = await _evolve_ctx()
    try:
        task = await get_task_with_expiry(ctx, uid, task_id)
        if task is None:
            print(f"error: evolve task not found: {task_id}", file=sys.stderr)
            return 1
        ok = await drop_task(ctx, uid, task_id)
        if not ok:
            print(f"error: task status is {task['status']}; only a live draft can be dropped.", file=sys.stderr)
            return 1
        print("Draft dropped; its branch is deleted. The canon is untouched.")
    finally:
        await ctx.aclose()
    return 0


async def _evolve_pending_draft():
    """The live draft's task_id, or None. One place answers "is something awaiting review"."""
    from pneuma_knowledge_service.evolve_service import list_tasks_with_expiry

    ctx, uid = await _evolve_ctx()
    try:
        tasks = await list_tasks_with_expiry(ctx, uid)
    finally:
        await ctx.aclose()
    for task in tasks:
        if task["status"] == "draft":
            return str(task["task_id"])
    return None


async def _evolve_step(policy: str) -> int:
    """One idempotent evolution step — the verb unattended pipelines should call.

    `evolve run` refuses while a draft awaits review, so a script composing run/adopt by
    hand must carry that state machine itself; every automation writing it fresh is a
    bug factory (observed live: a retry loop hammering `run` against the same pending
    draft eight times). `step` owns the whole cycle instead:

      pending draft?  → dispose it per --policy (adopt-clean: adopt now; keep: leave it
                        and say so with exit 2)
      no draft        → trigger one evolve run, then dispose any NEW draft the same way

    Safe to call repeatedly from a loop or a data-driven trigger: every invocation either
    makes progress, reports "nothing to do", or names the draft a human must look at.
    Exit codes: 0 progressed / nothing to do · 1 real failure · 2 draft kept for review.
    """
    pending = await _evolve_pending_draft()
    if pending is None:
        code = await _evolve_enqueue("evolve", {})
        if code != 0:
            return code
        pending = await _evolve_pending_draft()
        if pending is None:
            print("evolve step: no draft produced (no_change or below thresholds).")
            return 0
    if policy == "keep":
        print(f"evolve step: draft {pending} awaits review (policy=keep). "
              f"Inspect: ./app.py evolve show {pending}")
        return 2
    # adopt-clean: adoption itself runs the ordinary gate; a failing adopt leaves the
    # draft in place and this returns nonzero rather than pretending progress.
    code = await _evolve_enqueue("evolve_adopt", {"task_id": pending})
    if code != 0:
        return code
    if await _evolve_pending_draft() == pending:
        print(f"evolve step: adopt did not land; draft {pending} kept for review.",
              file=sys.stderr)
        return 2
    print(f"evolve step: draft {pending} adopted.")
    return 0


def cmd_evolve(args) -> int:
    action = args.action or "list"
    if action in ("show", "adopt", "drop") and not args.task_id:
        sys.exit(f"error: `evolve {action}` needs a <task_id> (see `./app.py evolve`)")
    if action == "list":
        return asyncio.run(_evolve_list())
    if action == "show":
        return asyncio.run(_evolve_show(args.task_id))
    if action == "run":
        return asyncio.run(_evolve_enqueue("evolve", {}))
    if action == "step":
        return asyncio.run(_evolve_step(getattr(args, "policy", "adopt-clean") or "adopt-clean"))
    if action == "adopt":
        return asyncio.run(_evolve_enqueue("evolve_adopt", {"task_id": args.task_id}))
    if action == "drop":
        return asyncio.run(_evolve_drop(args.task_id))
    sys.exit(f"error: unknown evolve action {action!r}")


async def _glance_text(ctx, uid, skill) -> str:
    from pneuma_knowledge_core.canonical_glance import render_canonical_glance

    docs = await ctx.canonical.list(uid)
    return render_canonical_glance(docs, skill)


async def _ask(
    question: str,
    *,
    show_sources: bool = False,
    style: str | None = None,
    evidence_strategy: str | None = None,
    answer_format: str | None = None,
    include_original_modalities: tuple[str, ...] = (),
) -> tuple[int, dict[str, int]]:
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_core.recall.fast import fast_recall
    from pneuma_knowledge_service.wiring import (
        build_context,
        llm_call_config,
    )

    skill = load_contract_skill()
    settings = build_settings(base_version=skill.version)
    ctx = await build_context(settings)
    try:
        uid = UserId(user_id())
        started = time.perf_counter()
        recall_model = ctx.get_chat_model("recall")
        answer_model = ctx.get_chat_model("answer")
        include_original_images = "image" in include_original_modalities
        answer = await fast_recall(
            uid,
            question,
            as_of=datetime.now(timezone.utc),
            claim_lexical=ctx.lexical,
            claim_vectors=ctx.vectors,
            lexical=ctx.lexical,
            vectors=ctx.vectors,
            content=ctx.store,
            media=ctx.media if include_original_images else None,
            image_mode="native" if include_original_images else "caption",
            embeddings=ctx.embeddings,
            model=recall_model,
            answer_model=answer_model,
            cap=settings.recall_claim_cap,
            claim_candidate_cap=settings.recall_claim_candidate_cap,
            window_cap=settings.recall_window_cap,
            window_candidate_cap=settings.recall_window_candidate_cap,
            episode_summary_cap=settings.recall_episode_summary_cap,
            evidence_strategy=evidence_strategy or settings.recall_evidence_strategy,
            selection_reasoning_effort=settings.recall_selection_reasoning_effort or None,
            answer_format=answer_format or settings.recall_answer_format,
            answer_style=style or settings.recall_answer_style,
            plan_queries_cap=settings.recall_plan_queries,
            reranker=ctx.get_reranker(),
            rerank_candidates=settings.recall_rerank_candidates,
            reasoning_effort=settings.answer_reasoning_effort or None,
            **llm_call_config(ctx, operation="recall.fast", user_id=str(uid)),
        )
        elapsed = time.perf_counter() - started
        print(f"\nQ: {question}")
        print(f"A: {answer.answer}")
        print(
            f"  ({elapsed:.1f}s, {answer.claim_candidates}→{len(answer.used_claims)} claims / "
            f"{len(answer.used_episode_summaries)} episode summaries / "
            f"{answer.window_candidates}→{len(answer.used_windows)} source windows, "
            f"tokens {answer.token_usage})"
        )
        if show_sources and answer.used_episode_summaries:
            print("  Derived episode summaries supplied to the answer (not verbatim):")
            for summary in answer.used_episode_summaries:
                section = " / ".join(summary.section_path) or "(root)"
                occurred_on = summary.source_occurred_on or "(unknown date)"
                print(
                    f"    [{summary.source_id} ¶{summary.block_start}-{summary.block_end}] "
                    f"{summary.source_title or '(untitled)'} · {occurred_on} · {section}"
                )
                for text_line in summary.text.strip().splitlines():
                    print(f"      {text_line}")
        # Citation legend: map each [cite: s01 ¶…] short handle in the answer back to its
        # material's title and date, so a citation is something you can actually follow rather
        # than a string of secret codes.
        handle_map = dict(answer.citation_handles or {})
        if handle_map and cited_handles(answer.answer):
            source_info = {
                str(s.source_id): (s.title, str((s.meta or {}).get("occurred_on") or ""))
                for s in await ctx.store.list(uid)
            }
            legend = citation_legend_lines(answer.answer, handle_map, source_info)
            if legend:
                print("  Citations:")
                for line in legend:
                    print(f"    {line}")
            if show_sources:
                real_to_handle = {v: k for k, v in handle_map.items()}
                cited_ids = {handle_map[h] for h in cited_handles(answer.answer) if h in handle_map}
                shown = 0
                for w in answer.used_windows:
                    sid = str(w.source_id)
                    if sid not in cited_ids:
                        continue
                    if shown == 0:
                        print("  Cited source windows:")
                    shown += 1
                    handle = real_to_handle.get(sid, sid[:8] + "…")
                    print(f"    [{handle} ¶{w.block_start}-{w.block_end}]")
                    for text_line in w.text.strip().splitlines():
                        print(f"      {text_line}")
                if shown == 0:
                    print("  (all citations point at compiled claims; no raw source window to show.)")
        await ctx.flush_traces()
        return 0, dict(answer.token_usage or {})
    finally:
        await ctx.aclose()


def cmd_ask(args) -> int:
    code, _usage = asyncio.run(
        _ask(
            args.question,
            show_sources=args.sources,
            style=args.style,
            evidence_strategy=args.evidence_strategy,
            answer_format=args.answer_format,
            include_original_modalities=tuple(args.include_original),
        )
    )
    return code


async def _status() -> int:
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.wiring import build_context

    subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "ps"], cwd=PROJECT_ROOT, check=False
    )
    for line in keyless_env(os.environ):  # counting what is there needs no model
        print(line)
    try:
        settings = build_settings(require_key=False)
        ctx = await build_context(settings)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — with the stack down, status reports rather than crashes
        print(f"(library unreachable: {type(exc).__name__}: {exc})")
        return 0
    try:
        uid = UserId(user_id())
        sources = await ctx.store.list(uid)
        jobs = await ctx.store.list_jobs(uid)
        pending = [j for j in jobs if j.get("status") != "done"]
        docs = await ctx.canonical.list(uid)
        claims = await ctx.store.list_canonical_claims(uid)
        print(
            f"user={uid}  sources={len(sources)}  jobs pending={len(pending)}  "
            f"canonical documents={len(docs)}  claims={len(claims)}"
        )
    finally:
        await ctx.aclose()
    return 0


def cmd_status(_args) -> int:
    return asyncio.run(_status())


async def _glance() -> int:
    """The same overview demo prints at the end, available on its own at any time: it only
    reads the current library — no re-ingest, no compile, and no key needed."""
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.wiring import build_context

    for line in keyless_env(os.environ):
        print(line)
    skill = load_contract_skill()
    settings = build_settings(base_version=skill.version, require_key=False)
    ctx = await build_context(settings)
    try:
        uid = UserId(user_id())
        print("== Your knowledge base at a glance ==")
        print(await _glance_text(ctx, uid, skill))
    finally:
        await ctx.aclose()
    return 0


def cmd_glance(_args) -> int:
    return asyncio.run(_glance())


async def _restore() -> int:
    """Restore the library this project ships (prebuilt/) into the running stack.

    Model-free by construction: a restore must cost nothing and reproduce the shipped library
    rather than recompute it, so the chat roles are cleared for this process even when a key
    is present. The framework owns the actual restore (canonical bundle + verbatim L0 and
    original media in, derived state rebuilt); this command only supplies the settings and
    the report."""
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.prebuilt import PrebuiltUnavailable, restore_prebuilt
    from pneuma_knowledge_service.wiring import build_context

    for line in keyless_env(os.environ):
        print(line)
    # Even WITH a key this process stays model-free: a restore reproduces the shipped
    # library (its vectors are the shipped deterministic embedding, its chunk boundaries
    # replay mechanically), so chat roles are cleared for THIS process and the embedding
    # pinned to the keyless one. The engine file is untouched — env outranks it only here.
    for role in ("", "_COMPILE", "_RECALL", "_DEEP", "_SKILL", "_EVOLVE", "_LIVE_CONTEXT", "_CHALLENGE"):
        os.environ[f"PNEUMA_KNOWLEDGE_LLM_MODEL{role}"] = ""
    os.environ["PNEUMA_KNOWLEDGE_EMBEDDING_MODEL"] = (
        os.environ.get("PNEUMA_APP_KEYLESS_EMBEDDING", "").strip() or KEYLESS_EMBEDDING
    )
    skill = load_contract_skill()
    settings = build_settings(base_version=skill.version, require_key=False)
    ctx = await build_context(settings)
    try:
        uid = UserId(user_id())
        print("== Restoring the prebuilt library (no model calls) ==")
        await upsert_owner_profile(ctx, uid)
        try:
            report = await restore_prebuilt(ctx, uid, PREBUILT_DIR, log=print)
        except PrebuiltUnavailable as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(
            f"\nRestored: {report.documents} canonical document(s), {report.claims} claim(s), "
            f"{report.sources} source(s), {report.images} image object(s) — all readable "
            "without an API key."
        )
        print("  ./app.py glance            # the library overview")
        print("  ./app.py ask '...'         # needs a key (asking calls a model)")
    finally:
        await ctx.aclose()
    return 0


def cmd_restore(_args) -> int:
    if not PREBUILT_DIR.is_dir():
        print(
            f"no prebuilt library in this project ({PREBUILT_DIR} does not exist) — nothing to\n"
            "restore. Projects that ship one carry prebuilt/canonical.bundle and\n"
            "prebuilt/l0.jsonl.gz, plus prebuilt/media/sha256 when L0 contains images; yours "
            "is built from my-data/ with ./app.py ingest + compile.",
            file=sys.stderr,
        )
        return 1
    return asyncio.run(_restore())


def cmd_preflight(_args) -> int:
    """Pre-flight check: when the scaffold has been copied outside the repository and never
    told where the framework repository is, say so at the very first step."""
    if find_framework_repo() is None:
        print(
            "error: framework repository not found. When this project lives outside the\n"
            "repository, set in .env:\n"
            "  PNEUMA_APP_FRAMEWORK_REPO=/absolute/path/to/pneuma-knowledge-compiler",
            file=sys.stderr,
        )
        return 1
    return 0


def demo_questions() -> list[str]:
    """Demo questions ride with the data, not the machinery: one per line in
    demo-questions.txt (written by the generator alongside the example dataset).
    No file → no Q&A tail, and that is not an error."""
    try:
        lines = DEMO_QUESTIONS_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    return [line.strip() for line in lines if line.strip()]


async def _demo_tail() -> int:
    """The tail of demo: glance + the demo questions (when the project ships any)."""
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.wiring import build_context

    skill = load_contract_skill()
    settings = build_settings(base_version=skill.version)
    ctx = await build_context(settings)
    try:
        uid = UserId(user_id())
        print("\n== Your knowledge base at a glance ==")
        print(await _glance_text(ctx, uid, skill))
    finally:
        await ctx.aclose()
    questions = demo_questions()
    if not questions:
        return 0
    total_usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    print("== Demo questions (fast lane) ==")
    for question in questions:
        code, usage = await _ask(question)
        if code != 0:
            return code
        for key in total_usage:
            total_usage[key] += int(usage.get(key, 0) or 0)
    print(f"\n  Q&A token total: {total_usage}")
    return 0


def cmd_demo(args) -> int:
    started = time.perf_counter()
    steps: list[tuple[str, float]] = []
    assume_yes = bool(getattr(args, "yes", False))

    def mark(label: str, t0: float) -> None:
        steps.append((label, time.perf_counter() - t0))

    require_models()  # surface missing configuration before any time-consuming step
    t0 = time.perf_counter()
    if cmd_up(None) != 0:
        return 1
    mark("up", t0)
    t0 = time.perf_counter()
    if cmd_init(None) != 0:
        return 1
    confirm_language(MY_DATA_DIR, assume_yes=assume_yes)
    mark("init", t0)
    t0 = time.perf_counter()
    if asyncio.run(_ingest(MY_DATA_DIR)) != 0:
        return 1
    mark("ingest", t0)
    t0 = time.perf_counter()
    code, compile_usage = asyncio.run(_compile())
    if code != 0:
        return code
    mark("compile", t0)
    t0 = time.perf_counter()
    if asyncio.run(_demo_tail()) != 0:
        return 1
    mark("Q&A+glance", t0)
    total = time.perf_counter() - started
    print("\n== Demo complete ==")
    for label, seconds in steps:
        print(f"  {label:12s} {seconds:8.1f}s")
    print(f"  total {total:.1f}s; compile token total {compile_usage or '(none)'}")
    print("\nYour turn:")
    print("  ./app.py ask '...'         # ask anything (--sources also shows the cited raw text)")
    print("  ./app.py glance            # look at the library overview any time")
    print("  engine/                    # this engine's strategy and contract, versioned (see engine/README.md)")
    print("  Switching to your own data: see README.md (or let your AI guide walk you through)")
    print("  Reset and start over: ./app.py down --volumes && rm -rf data/")
    return 0


# ---------------------------------------------------------------- entry point


def main() -> int:
    # Output is often piped away (tee / CI); line buffering keeps progress visible in real time,
    # and child processes inherit it.
    try:
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
    except AttributeError:
        pass
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    _extend_no_proxy()
    load_env_file(ENV_PATH)
    # The generator writes an explicit PNEUMA_APP_COMPOSE_PROJECT into .env; this fallback
    # derives one from the directory name so even a hand-assembled project never lands on a
    # name shared with some other stack on the machine.
    fallback_project = "pneuma-" + re.sub(r"[^a-z0-9]+", "-", PROJECT_ROOT.name.lower()).strip("-")
    os.environ.setdefault("PNEUMA_APP_COMPOSE_PROJECT", fallback_project or "pneuma-app")
    parser = argparse.ArgumentParser(description="pneuma-knowledge application driver")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("up", help="start the middleware stack")
    down = sub.add_parser("down", help="stop the middleware stack")
    down.add_argument("--volumes", action="store_true", help="also delete the data volumes")
    sub.add_parser("init", help="detect timezone/language/region into profile.yaml")
    ingest = sub.add_parser("ingest", help="ingest a directory of .md material")
    ingest.add_argument("directory", nargs="?", help="defaults to my-data/")
    sub.add_parser("compile", help="drain the compile queue")
    ask = sub.add_parser("ask", help="fast-lane Q&A")
    ask.add_argument("question")
    ask.add_argument("--sources", action="store_true", help="also print the cited source windows")
    ask.add_argument(
        "--style",
        choices=["concise", "conversational", "detailed"],
        help="answer style for this ask (default: PNEUMA_KNOWLEDGE_RECALL_ANSWER_STYLE in .env)",
    )
    ask.add_argument(
        "--evidence-strategy",
        choices=["ranked", "select"],
        help=(
            "context composition for this ask: ranked keeps fixed retrieval heads; select "
            "uses one bounded cross-face selection call"
        ),
    )
    ask.add_argument(
        "--answer-format",
        choices=["text", "structured"],
        help=(
            "answer wire for this ask: text is free text; structured validates separate "
            "answer text, kind, and citations"
        ),
    )
    ask.add_argument(
        "--include-original",
        action="append",
        choices=["image"],
        default=[],
        metavar="MODALITY",
        help=(
            "include one original modality in this ask; currently: image. Repeatable for "
            "future modalities. Omit it to use labelled derived representations only"
        ),
    )
    sub.add_parser("glance", help="print the library overview (no re-ingest)")
    sub.add_parser(
        "restore", help="restore the library this project ships in prebuilt/ (no key needed)"
    )
    evolve = sub.add_parser("evolve", help="schema evolution: list / step / run / show / adopt / drop")
    evolve.add_argument("action", nargs="?", default="list",
                        choices=["list", "step", "run", "show", "adopt", "drop"])
    evolve.add_argument("task_id", nargs="?")
    evolve.add_argument(
        "--policy",
        choices=["adopt-clean", "keep"],
        default="adopt-clean",
        help="evolve step only: dispose a draft by adopting it (gate decides), or keep it for review (exit 2)",
    )
    sub.add_parser("status", help="stack and library status")
    demo = sub.add_parser("demo", help="end to end: up → init → ingest → compile → Q&A")
    demo.add_argument("--yes", action="store_true", help="no prompts, take every default (CI/non-interactive)")
    sub.add_parser("preflight", help="pre-flight check (is the framework repository reachable?)")
    args = parser.parse_args()

    if args.command in ("up", "down", "init", "preflight"):
        handler = {
            "up": cmd_up,
            "down": cmd_down,
            "init": cmd_init,
            "preflight": cmd_preflight,
        }[args.command]
        return handler(args)
    ensure_framework()
    handler = {
        "ingest": cmd_ingest,
        "compile": cmd_compile,
        "ask": cmd_ask,
        "glance": cmd_glance,
        "restore": cmd_restore,
        "evolve": cmd_evolve,
        "status": cmd_status,
        "demo": cmd_demo,
    }[args.command]
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
