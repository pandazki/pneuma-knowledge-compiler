"""One manifest per coding-agent harness — backends are data (ruling 9).

The install layout, the binary and the display label of every harness this version knows,
stated once. The rule the module exists to make keepable: **nothing outside this file
branches on a backend name.** A consumer that needs to know where skills go reads
`skills_dir`; one that needs to know whether a workflow is installable reads
`workflows_dir is None`. When a third harness arrives it is a row here and a line in a doc,
not a search for `== "codex"` across the service.

The probe and the unattended launch shape (§8's other half) are filled in here too: the
liveness command, the headless argv template, which channel the round's system text travels
on, the hermetic config-home variable, the signals that mean "rate limited", and the reader
that turns the harness's own output into token counts. All of it is DATA — the launcher
substitutes placeholders and reads fields, and still nothing outside this file branches on a
backend name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Callable, Mapping, Sequence
from zoneinfo import ZoneInfo

from .harness_output import (
    HarnessReport,
    read_claude_output,
    read_codex_output,
    read_no_output,
)
from .steward_claude import ClaudeStreamAdapter
from .steward_codex import CodexJsonRpcAdapter

# ── the placeholders a launch template may carry ────────────────────────────────────────
#
# One substitution rule, stated once and applied by `render_argv`: a template argument
# containing a placeholder whose value is empty is DROPPED, together with the flag
# immediately before it. That is what lets one template describe both "with a model" and
# "whatever the harness defaults to" without a second template or an `if`.

MODEL = "{model}"
REASONING_EFFORT = "{effort}"
SYSTEM_FILE = "{system_file}"
OUTPUT_FILE = "{output_file}"
PROJECT_DIR = "{project_dir}"
SESSION = "{session}"

#: How a round's system text reaches the harness.
STDIN_PREFIX = "stdin_prefix"  #: no system channel — the text heads the piped prompt
SYSTEM_PROMPT_FILE = "system_prompt_file"  #: a flag naming a file, replacing the preamble

#: What a harness says when the Owner's subscription is out of room. Matched
#: case-insensitively against the process's own stdout and stderr, because neither harness
#: reserves an exit code for it. Shared, because these are the provider's words rather than
#: any one CLI's.
RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "rate limit",
    "rate_limit",
    "rate-limited",
    "429",
    "usage limit",
    "quota exceeded",
    "too many requests",
    "overloaded",
    "try again later",
)

#: The OTHER way a launch never becomes a round, and the reason this is a second list rather
#: than four more rows above: nothing here is about the Owner's subscription. `Selected model
#: is at capacity. Please try a different model.` is the provider saying this model has no
#: room right now — observed live from `codex exec -m gpt-5.6-luna` minutes after a restored
#: quota, arriving as a `turn.failed` event with no tool calls and no draft touched. For the
#: worker the two are one fact ("waiting is the only thing that helps"), so both route into
#: the same backoff and the same `HARNESS_UNAVAILABLE`; they are kept apart HERE because they
#: are different sentences and an operator reading `codex at capacity` on a cooling line
#: should not be told their quota ran out.
#:
#: Unlike a usage limit, none of these names an hour, so the cooldown is the only answer.
UNAVAILABLE_MARKERS: tuple[str, ...] = (
    "at capacity",
    "temporarily unavailable",
    "service unavailable",
    "503",
)


def unavailable_reason(text: str, manifest: "BackendManifest | None" = None) -> str:
    """The short phrase naming WHY a launch could not run, or "" when nothing matched.

    What an operator is shown on a cooling line and what the re-queued job carries as its
    reason. It is the matched MARKER rather than the harness's whole sentence: the sentence
    is the provider's, may be a paragraph, and is already on the job's detail.
    """
    haystack = (text or "").lower()
    rate = manifest.rate_limit_markers if manifest else RATE_LIMIT_MARKERS
    unavailable = manifest.unavailable_markers if manifest else UNAVAILABLE_MARKERS
    for marker in ("usage limit", "quota exceeded", *rate):
        if marker.lower() in haystack:
            return "usage limit" if marker in ("usage limit", "quota exceeded") else "rate limit"
    for marker in unavailable:
        if marker.lower() in haystack:
            return "at capacity" if marker == "at capacity" else "unavailable"
    return ""


#: WHEN the harness said the room comes back, as its own sentence spells it. Codex prints
#: `You've hit your usage limit ... try again at Sep 15th, 2026 9:23 AM` — a local wall-clock
#: instant, in the timezone of the machine the harness ran on. Reading it is worth a regex
#: because the alternative is a guessed cooldown: a worker that waits fifteen minutes for a
#: window that reopens in nine hours spends the night asking a dead quota the same question.
#:
#: Per manifest, because these are one CLI's words. Claude Code's phrasing is not stated
#: here: the framework does not know it for certain, and a pattern that half-matched would
#: parse a wrong instant rather than fall back to the cooldown that is correct when nothing
#: is known.
_MONTHS: Mapping[str, int] = MappingProxyType(
    {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
)

CODEX_USAGE_LIMIT_PATTERNS: tuple[str, ...] = (
    r"try again (?:at|on)\s+"
    r"(?P<month>[A-Za-z]{3,9})\.?\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?,?\s+"
    r"(?P<year>\d{4})"
    r"(?:[\s,]+(?:at\s+)?(?P<hour>\d{1,2}):(?P<minute>\d{2})\s*(?P<meridiem>[AaPp]\.?[Mm]\.?)?)?",
)


def usage_limit_deadline(
    text: str, *, timezone_name: str = "UTC", patterns: Sequence[str] = ()
) -> datetime | None:
    """The instant a harness said its usage limit lifts, or None when it said nothing.

    `timezone_name` is the DEPLOYMENT's default zone (`PNEUMA_KNOWLEDGE_DEFAULT_TIMEZONE`),
    because the harness prints a local wall clock with no offset on it — the machine's own,
    which for a single-machine edition is the deployment's. An unknown zone name is read as
    UTC rather than raising: a cooldown computed from the wrong zone is still a cooldown, and
    a crash in the failure path would turn a rate limit into a stuck worker.

    Returns an aware datetime in that zone. `patterns` defaults to every phrasing this
    module knows; a caller with a manifest in hand passes that backend's own.
    """
    for pattern in (patterns or CODEX_USAGE_LIMIT_PATTERNS):
        found = re.search(pattern, text or "", re.IGNORECASE)
        if not found:
            continue
        fields = found.groupdict()
        month = _MONTHS.get(str(fields.get("month", ""))[:3].lower())
        if month is None:
            continue
        hour = int(fields.get("hour") or 0)
        meridiem = (fields.get("meridiem") or "").replace(".", "").lower()
        if meridiem == "pm" and hour < 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        try:
            zone = ZoneInfo(timezone_name or "UTC")
        except Exception:  # noqa: BLE001 — an unreadable zone is not a reason to fail a job
            zone = timezone.utc
        try:
            return datetime(
                int(fields["year"]), month, int(fields["day"]),
                hour, int(fields.get("minute") or 0), tzinfo=zone,
            )
        except ValueError:
            continue
    return None


@dataclass(frozen=True)
class BackendManifest:
    """Everything the framework knows about one coding-agent harness."""

    #: The spec name, as it appears after `agent:` in a model spec and on `--backend`.
    name: str
    #: The executable a probe and a launcher call. Never version-compared (ruling 9).
    binary: str
    #: Project-relative directory holding installed skills, in the harness's own convention.
    skills_dir: str
    #: Project-relative instructions file the harness reads on entering a directory. The
    #: `pkc:start` router block is spliced into this file and nowhere else.
    instructions_file: str
    #: Project-relative directory for dynamic workflow scripts, or None when the harness has
    #: no such concept. `None` is the whole of the "is a workflow installable" question
    #: (ruling 5: prose is the complete specification; a workflow is an enforcement upgrade
    #: on the one backend that runs it).
    workflows_dir: str | None
    #: How this harness is named to a person — the console, the CLI's own output, an error.
    display_label: str

    # ── the probe and the unattended launcher (§8) ──────────────────────────────────────
    #: The command that answers "is this harness present and logged in", as the arguments
    #: after the binary. LIVENESS, never presence and never a version: `codex login status`
    #: reports the auth state directly, and `claude -p ping` is a real in-family call that
    #: an unauthenticated install cannot answer. Exit 0 within the deadline is the whole
    #: reading. An empty tuple = this backend states no probe, reported as unknown rather
    #: than as a failure.
    probe_command: tuple[str, ...] = ()
    #: The argv template for one unattended round, after the binary. The prompt is NEVER
    #: here: it arrives on stdin from a file (§8). Placeholders above; an argument whose
    #: placeholder resolves empty drops with the flag before it.
    launch_command: tuple[str, ...] = ()
    #: The argv template for a repair round that continues the first round's session, or ()
    #: when this harness cannot resume — the launcher then runs a fresh process fed the
    #: violations, which is the same round with a shorter memory.
    resume_command: tuple[str, ...] = ()
    #: A cheap command that answers "does the installed CLI have the resume surface at all",
    #: asked once per process. Empty = trust `resume_command`.
    resume_probe_command: tuple[str, ...] = ()
    #: How the round's system text reaches the harness: `STDIN_PREFIX` or
    #: `SYSTEM_PROMPT_FILE`.
    system_text_channel: str = ""
    #: The environment variable that moves this harness's whole config/session directory.
    #: The launcher points it at a per-JOB directory it owns, so a round never writes a
    #: session file into the Owner's real home and a job's sessions die with the job.
    config_home_env: str = ""
    #: Where that directory normally is, `~`-relative — what the per-job one is seeded FROM.
    default_config_home: str = ""
    #: How this harness is told how hard to think, as the flag pair carrying `REASONING_EFFORT`
    #: — spliced into `launch_command` and `resume_command`, and stated here as well so the
    #: launcher can ask whether this harness takes an effort at all without knowing its name.
    #: Empty = it does not, and the configured effort is dropped rather than guessed at.
    effort_flags: tuple[str, ...] = ()
    #: The files a per-job config home cannot do without: the harness's credentials, and the
    #: configuration the Owner set it up with. Moving the config home moves the CREDENTIALS
    #: with it, and a hermetic home that holds none is a harness that is suddenly logged out
    #: — which is why these are linked in rather than left behind. Linked, not copied: a
    #: token this round refreshes is refreshed in the Owner's own home, and no secret is
    #: duplicated into a temporary directory. Absent files are simply absent (a harness that
    #: authenticates through the system keychain has no file to link).
    config_seed: tuple[str, ...] = ()
    #: Variables the launcher REMOVES from the child's environment. `CLAUDECODE` is the one
    #: that matters: a Claude Code session that finds it set believes it is nested and
    #: short-circuits, so a round launched from inside a Claude session would never run.
    unset_env: tuple[str, ...] = ()
    #: Exit codes that mean "the subscription is out of room, back off". Neither shipped
    #: harness reserves one; the field exists because a third might, and a launcher that
    #: read only text would have nowhere to put it.
    rate_limit_exit_codes: tuple[int, ...] = ()
    #: Substrings that mean the same thing, matched case-insensitively on the output.
    rate_limit_markers: tuple[str, ...] = RATE_LIMIT_MARKERS
    #: Substrings that mean the harness could not run for a reason that is not the Owner's
    #: subscription and that waiting still fixes — a model with no capacity, a provider
    #: outage. Scanned with the markers above and treated identically by launcher and worker.
    unavailable_markers: tuple[str, ...] = UNAVAILABLE_MARKERS
    #: Regexes that read WHEN this harness said the room comes back, from the same output.
    #: Empty = this backend states no such sentence, and the worker cools for a configured
    #: interval instead of a parsed one.
    usage_limit_patterns: tuple[str, ...] = ()
    #: The harness's own report of what the round cost and which session ran it
    #: (`harness_output.py`). Data on the manifest, so reading usage is not a branch.
    read_output: Callable[[str, str], HarnessReport] = read_no_output

    # ── the INTERACTIVE posture: the console's Steward view (§5.6) ──────────────────────
    #
    # A second launch shape beside the headless one above, and for a different kind of
    # process: not one round that ends, but a session the Owner talks to. Same three
    # questions answered as data — what to run, what it speaks, and who translates it — so
    # that nothing outside this file branches on a backend name here either.
    #: The argv template for one INTERACTIVE session, after the binary. Same placeholder
    #: rules as `launch_command`; the prompt is never here either — a user turn is written
    #: to the process's stdin by the adapter, one frame at a time.
    interactive_command: tuple[str, ...] = ()
    #: What that process speaks, named so a console can say which protocol it is watching.
    #: A label, never a branch: the adapter below is what actually reads it.
    wire_protocol: str = ""
    #: The adapter that turns this harness's wire into the one event vocabulary and writes a
    #: user turn back down it (`steward_events.py`). Called with `project_dir=` and `model=`;
    #: it owns HOW a turn is written and HOW the session/thread id is read back, which is the
    #: whole of what the two protocols disagree about. `None` = this backend has no
    #: interactive posture, which the route reports rather than guesses around.
    interactive_adapter: Callable[..., Any] | None = None

    # ── what the OWNER types, in their own terminal, in the project directory ───────────
    #
    # The launch templates above are the framework's own invocations, made for an empty
    # working directory. What the Owner types is a different command with the same
    # requirement, and it turned out to be the one thing nothing said: a harness started with
    # its default posture cannot open a socket to this project's Postgres, so every `pkc`
    # command fails before it reaches the library — the headline experience of §3, dead on a
    # sandbox default. So the working invocation is DATA here, and the router block, SKILL.md
    # and the generated README all render it from this one field rather than restating it.
    #: One unattended instruction, prompt appended by whoever renders it.
    owner_exec_hint: str = ""
    #: An interactive session in this directory. "" = the harness needs nothing beyond its
    #: own name, which `owner_session_command` is what says.
    owner_session_hint: str = ""

    @property
    def owner_session_command(self) -> str:
        """What the Owner types to open a session here — the hint, or just the binary."""
        return self.owner_session_hint or self.binary

    @property
    def owner_exec_command(self) -> str:
        """What the Owner types to run ONE instruction here, prompt not included."""
        return self.owner_exec_hint or self.binary

    @property
    def skill_dir(self) -> str:
        """Where THIS framework's skill package is installed, project-relative."""
        return f"{self.skills_dir}/{SKILL_NAME}"


#: The one skill this framework installs. A literal, not a catalog key: it is an identifier
#: the harness matches on and a directory name on disk, so translating it would rename a
#: path.
SKILL_NAME = "pkc-steward"

#: The marker pair the router block is spliced between, in the instructions file. Everything
#: outside them is somebody else's prose and is never touched.
BLOCK_START = "<!-- pkc:start -->"
BLOCK_END = "<!-- pkc:end -->"

# The sandbox a Codex round runs under. `workspace-write` over an EMPTY working directory is
# the shape §8 asks for: the harness can execute, and the only thing it can write is a
# scratch directory that holds nothing. Network access is switched on because the one hand it
# has — the `pkc` shim — reaches Postgres and the indexes, and a sandbox that refused those
# would refuse the whole job rather than protect anything.
_CODEX_SANDBOX: tuple[str, ...] = (
    "--sandbox",
    "workspace-write",
    "-c",
    "sandbox_workspace_write.network_access=true",
)

# How hard a Codex round thinks. A `-c` override rather than a flag of its own, because that
# is the only channel the CLI has for it: unset, the round inherits `model_reasoning_effort`
# from the config home it was seeded from — the Owner's own — which is what
# `PNEUMA_KNOWLEDGE_AGENT_REASONING_EFFORT` exists to stop being the only answer.
_CODEX_EFFORT: tuple[str, ...] = ("-c", f"model_reasoning_effort={REASONING_EFFORT}")

_CODEX_COMMON: tuple[str, ...] = (
    "--skip-git-repo-check",  # the working directory is a fresh mkdtemp, not a repo
    "--color",
    "never",
    "--json",  # the token counts ride these events; there is no other channel
    *_CODEX_SANDBOX,
    *_CODEX_EFFORT,
    "-m",
    MODEL,
    "--output-last-message",
    OUTPUT_FILE,
    "-",  # the prompt comes from stdin, never from argv
)

# What a Claude round may hold. NOT `--tools ""` as the single-shot leaf uses: this round's
# whole job is to run `pkc`, so it needs a shell — and nothing else. `Read` rides along
# because the skill it was installed with is a set of files it may need to re-read.
_CLAUDE_TOOLS: tuple[str, ...] = ("--tools", "Bash,Read")

_CLAUDE_COMMON: tuple[str, ...] = (
    "-p",
    "--output-format",
    "json",  # `result.usage` and `total_cost_usd` live in this object
    *_CLAUDE_TOOLS,
    # Unattended in an empty directory with no interactive channel: a permission prompt has
    # nobody to answer it, and would hang the round until the launcher's timeout killed it.
    "--permission-mode",
    "bypassPermissions",
    "--model",
    MODEL,
    # The project is where the shim and the installed skill live; the working directory is
    # deliberately not the project, so the one directory the file tools may reach is named.
    "--add-dir",
    PROJECT_DIR,
)

CODEX = BackendManifest(
    name="codex",
    binary="codex",
    skills_dir=".agents/skills",
    instructions_file="AGENTS.md",
    workflows_dir=None,
    display_label="Codex",
    probe_command=("login", "status"),
    launch_command=("exec", *_CODEX_COMMON),
    # `--last` under a per-JOB `CODEX_HOME` is unambiguous: the only session that home holds
    # is this job's first round.
    resume_command=("exec", "resume", "--last", *_CODEX_COMMON),
    resume_probe_command=("exec", "resume", "--help"),
    system_text_channel=STDIN_PREFIX,
    # The interactive posture: `app-server` is a long-lived JSON-RPC process, and the
    # thread it holds is the conversation. No model flag here — Codex picks the model per
    # turn, and the adapter puts it on `thread/start` / `turn/start` where it belongs.
    interactive_command=("app-server",),
    wire_protocol="jsonrpc",
    interactive_adapter=CodexJsonRpcAdapter,
    config_home_env="CODEX_HOME",
    default_config_home="~/.codex",
    effort_flags=_CODEX_EFFORT,
    config_seed=("auth.json", "config.toml"),
    usage_limit_patterns=CODEX_USAGE_LIMIT_PATTERNS,
    read_output=read_codex_output,
    # `--skip-git-repo-check` because a library need not be a git repository (the canonical
    # store's own repository is under `data/`, not at the project root), and the two sandbox
    # flags because Codex defaults to a restricted filesystem AND a restricted network: with
    # the defaults, `pkc` cannot reach this project's Postgres and the round ends having read
    # nothing.
    owner_exec_hint=(
        "codex exec --skip-git-repo-check --sandbox workspace-write "
        "-c sandbox_workspace_write.network_access=true"
    ),
    owner_session_hint=(
        "codex --sandbox workspace-write -c sandbox_workspace_write.network_access=true"
    ),
)

CLAUDE_CODE = BackendManifest(
    name="claude-code",
    binary="claude",
    skills_dir=".claude/skills",
    instructions_file="CLAUDE.md",
    workflows_dir=".claude/workflows",
    display_label="Claude Code",
    probe_command=("-p", "ping", "--output-format", "text"),
    launch_command=(*_CLAUDE_COMMON, "--system-prompt-file", SYSTEM_FILE),
    # A resumed session already holds the system text; re-stating it would be a second
    # rendering of bytes I5 keeps single.
    resume_command=(*_CLAUDE_COMMON, "--resume", SESSION),
    system_text_channel=SYSTEM_PROMPT_FILE,
    # The interactive posture: streaming NDJSON in BOTH directions, which is what keeps one
    # process open across many turns. `--verbose` is required by the CLI whenever
    # `--print` and `stream-json` meet; `--include-partial-messages` is what makes the
    # Steward's prose arrive as it is written rather than in one block at the end.
    interactive_command=(
        "--print",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--permission-mode",
        "bypassPermissions",
        "--model",
        MODEL,
        "--add-dir",
        PROJECT_DIR,
    ),
    wire_protocol="stream-json",
    interactive_adapter=ClaudeStreamAdapter,
    config_home_env="CLAUDE_CONFIG_DIR",
    default_config_home="~/.claude",
    # No `effort_flags`: this version of the Claude Code CLI has no reasoning-effort flag,
    # and inventing one would be a round that dies in argv. A configured effort is dropped.
    config_seed=(".credentials.json", "settings.json"),
    unset_env=("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"),
    read_output=read_claude_output,
    # Claude Code sandboxes nothing and asks instead, so an interactive session in the
    # project needs no flags at all — allow Bash the first time it asks. A one-shot `-p` run
    # has nobody to ask, which is the only reason a permission mode appears here; `--tools`
    # and `--add-dir` are the unattended launcher's, and they exist because THAT round runs
    # in an empty directory outside the project.
    owner_exec_hint="claude -p --permission-mode bypassPermissions",
    # Nothing: Claude Code sandboxes nothing and asks instead, so an interactive session in
    # the project needs only that Bash be allowed the first time it asks.
    owner_session_hint="",
)

#: Every harness this version knows, in the order they were built (Codex first, §0).
BACKENDS: Mapping[str, BackendManifest] = MappingProxyType(
    {CODEX.name: CODEX, CLAUDE_CODE.name: CLAUDE_CODE}
)


def render_argv(
    template: tuple[str, ...], values: Mapping[str, str]
) -> list[str]:
    """A launch template with its placeholders filled, and its empty ones removed.

    One rule, applied here and nowhere else: an argument that still contains an UNFILLED
    placeholder — a model nobody named, a session there is none of — is dropped along with
    the flag immediately before it. That is what lets `("-m", "{model}")` describe both "run
    this model" and "run whatever the harness defaults to" without a second template.
    """
    out: list[str] = []
    for argument in template:
        rendered = argument
        empty = False
        for token, value in values.items():
            if token not in rendered:
                continue
            if not value:
                empty = True
                break
            rendered = rendered.replace(token, value)
        if empty:
            if out and out[-1].startswith("-"):
                out.pop()
            continue
        out.append(rendered)
    return out


def backend(name: str) -> BackendManifest:
    """The manifest for `name`, or a ValueError naming what is shipped."""
    key = (name or "").strip()
    try:
        return BACKENDS[key]
    except KeyError:
        raise ValueError(
            f"unknown coding agent {name!r}; shipped backends: {', '.join(BACKENDS)}"
        ) from None
