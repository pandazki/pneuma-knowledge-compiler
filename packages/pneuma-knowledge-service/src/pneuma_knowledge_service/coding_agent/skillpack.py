"""The skill package: a rendering of what already exists (§7, ruling 4).

Nothing in this module writes a sentence of its own. `SKILL.md` is the prompt catalog's
`steward.skill.*` surfaces concatenated; `references/contract.md` is the composed contract's
own instructions; `references/compile-instructions.md` is the exact bytes `pkc draft open`
prints above the task; `references/cli.md` is walked out of the live argparse tree, so a
component's compile tools appear because they are IN that tree; `references/gate.md` is the
gate's own violation texts. The one thing the module authors is the shim, and a shell script
is machinery, not prose.

That is what makes a freshness check meaningful: if the installed package differs from a
fresh rendering, something drifted from its source — and the source is the only place a fix
belongs.

Determinism is a property, not an aspiration: same inputs → same bytes → same sha256. Nothing
here reads a clock, a directory listing or a random source. The one wall-clock fact a package
carries (`rendered_at`) lives beside it in `skill-version.json` and is excluded from the hash
(`install.py`).
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from pneuma_knowledge_core.compile.gate import violation_catalog
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.skill.contract import render_system_contract
from pneuma_knowledge_core.skill.version import SkillVersion

from .backends import SKILL_NAME, BackendManifest

def _exit_meanings() -> tuple[tuple[int, str], ...]:
    """The exit codes `pkc draft` uses, each with the one sentence it means.

    The numbers are READ from the CLI's own module, never retyped, so the reference cannot
    say 3 where the code says 4. Imported inside the function because `cli/__init__` builds
    the whole command tree — including `pkc skill`, which lands back here — and a module-level
    import would close that circle at import time.
    """
    from ..cli.draft import (
        EXIT_BUDGET,
        EXIT_GATE,
        EXIT_NOTHING,
        EXIT_OK,
        EXIT_REFUSED,
    )

    return (
        (EXIT_OK, "the command did what it says"),
        (EXIT_NOTHING, "nothing to act on — no open draft, or no such job for this library"),
        (
            EXIT_REFUSED,
            "refused: the call was rejected, or applied and rolled back by the post-check "
            "on the page it touched",
        ),
        (EXIT_BUDGET, "the round's call budget is spent"),
        (EXIT_GATE, "the gate rejected what it judged"),
    )


@dataclass(frozen=True)
class SkillPackage:
    """One rendered package: its files, and the identity of those exact bytes.

    `files` maps a path RELATIVE TO THE SKILL DIRECTORY (`SKILL.md`,
    `references/cli.md`, `scripts/pkc`, `workflows/compile.js`) to its bytes. Paths are
    POSIX-spelled here and joined per-platform by the installer, so the hash of a package is
    the same on every machine that renders it.
    """

    files: Mapping[str, bytes]
    #: Which files must carry the executable bit when written. A property of the package,
    #: not of the installer: the shim IS an executable, wherever it lands.
    executable: frozenset[str]
    #: Which language pack the prose was rendered under, recorded because a package rendered
    #: under another one is a different package. The hash already says they differ; this says
    #: why.
    language: str
    #: The backend this layout was rendered for.
    backend: str

    @property
    def sha256(self) -> str:
        """Over the sorted `(path, bytes)` pairs — order-independent, content-complete."""
        h = hashlib.sha256()
        for path in sorted(self.files):
            h.update(path.encode("utf-8"))
            h.update(b"\x00")
            h.update(self.files[path])
            h.update(b"\x00")
        return h.hexdigest()


# ───────────────────────────────────────────────────────────────────────────── SKILL.md


def _frontmatter(description: str) -> str:
    """YAML frontmatter with the two fields a harness reads.

    `name` is the directory name, deliberately not translated: it is an identifier a harness
    matches on and a path on disk. `description` is prose and comes from the catalog, folded
    onto one line because YAML plain scalars end at a newline.
    """
    one_line = " ".join(description.split())
    return f"---\nname: {SKILL_NAME}\ndescription: {one_line}\n---\n"


#: The `pkc` a session runs when the project advertises one of its own. The scaffold writes
#: `bin/pkc` and its own README, generator output and prose all name it, so the skill naming
#: a second path for the same command taught two entry names for one door. The skill-relative
#: shim stays installed and stays the fallback: a project that is not scaffold-shaped (a bare
#: directory somebody ran `pkc skill install` in) has no `bin/pkc` to point at.
PROJECT_ENTRY = "bin/pkc"


def project_entry(project: "str | Path | None") -> str:
    """`bin/pkc` when this project has one, else "" — the whole of the decision."""
    if project is None:
        return ""
    return PROJECT_ENTRY if (Path(project) / PROJECT_ENTRY).is_file() else ""


def skill_entry(backend: BackendManifest, project_relative_entry: str = "") -> str:
    """The path SKILL.md tells the Steward to run `pkc` as, project-relative."""
    return project_relative_entry or f"{backend.skill_dir}/scripts/pkc"


def render_skill_md(*, backend: BackendManifest, entry: str = "") -> str:
    """The journey, in the order §7 states it, every section straight from the catalog."""
    root = f"{backend.skill_dir}"
    sections = [
        prompt("steward.skill.who", pkc=skill_entry(backend, entry)),
        prompt("steward.skill.consume", consume=f"{root}/references/consume.md"),
        prompt("steward.skill.episodes"),
        prompt("steward.skill.round"),
        prompt("steward.skill.evolve"),
        prompt("steward.skill.door", gate=f"{root}/references/gate.md"),
        prompt(
            "steward.skill.postures",
            session=backend.owner_session_command,
            once=backend.owner_exec_command,
        ),
        prompt("steward.skill.owner_speech"),
        # The archive: how a subject leaves, and what stands where it stood. After owner
        # speech because that is the order the act has — the owner says it, and the reason
        # the record quotes is that statement — and before "what you cannot do", which is
        # where the archive's two absences are stated.
        prompt("steward.skill.archive"),
        prompt("steward.skill.cannot"),
        prompt(
            "steward.skill.references",
            contract=f"{root}/references/contract.md",
            instructions=f"{root}/references/compile-instructions.md",
            consume=f"{root}/references/consume.md",
            cli=f"{root}/references/cli.md",
            gate=f"{root}/references/gate.md",
        ),
    ]
    if backend.workflows_dir is not None:
        sections.append(
            prompt("steward.skill.workflow", workflow=f"{backend.workflows_dir}/compile.js")
        )
    body = "\n\n".join(section.strip("\n") for section in sections)
    return _frontmatter(prompt("steward.skill.description")) + "\n" + body + "\n"


# ─────────────────────────────────────────────────────────────────── references/consume.md


def render_consume_md(skill: SkillVersion) -> str:
    """Reading procedure from the catalog, families from the resolved contract.

    A family is its path template, as in the canonical glance. No domain names or paths
    are inferred from prose; declaration order and owner-voice constraints come from the
    same SkillVersion the package's compile instructions render.
    """
    families = "\n".join(
        f"- `{template}`"
        + (prompt("steward.consume.owner_voice") if template in skill.owner_voice_templates else "")
        for template in skill.path_templates
    ) or prompt("steward.consume.no_families")
    return "\n\n".join(
        section.strip("\n")
        # Philosophy and what the library establishes → this deployment's domain schema →
        # best practice by the shape of the question → the tools and what each returns →
        # recording. The Owner's ruling on what a skill is: those three parts, in that order,
        # and the rest is the model's.
        for section in (
            prompt("steward.consume.library"),
            prompt(
                "steward.consume.schema",
                skill_id=skill.skill_id,
                version=skill.version,
                families=families,
            ),
            prompt("steward.consume.when_to_use"),
            prompt("steward.consume.primitives"),
            prompt("steward.consume.answering"),
        )
    ) + "\n"


# ─────────────────────────────────────────────────────────────────────── references/cli.md


def _subparser_action(parser: argparse.ArgumentParser):  # noqa: ANN001, ANN201
    for action in parser._actions:  # noqa: SLF001 — argparse exposes no public tree walk
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            return action
    return None


def _argument_lines(parser: argparse.ArgumentParser) -> list[str]:
    """One bullet per argument this command takes, in declaration order."""
    lines: list[str] = []
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, (argparse._HelpAction, argparse._SubParsersAction)):  # noqa: SLF001
            continue
        if action.option_strings:
            name = ", ".join(action.option_strings)
            if action.nargs != 0:
                name = f"{name} <{(action.metavar or action.dest).lower()}>"
        else:
            name = f"<{(action.metavar or action.dest).lower()}>"
            if action.nargs in ("+", "*"):
                name = f"{name}…"
        detail = " ".join((action.help or "").split())
        if action.choices:
            detail = (
                f"{detail} (one of: {', '.join(str(c) for c in action.choices)})"
                if detail
                else f"one of: {', '.join(str(c) for c in action.choices)}"
            )
        lines.append(f"- `{name}` — {detail}" if detail else f"- `{name}`")
    return lines


def _command_sections(
    parser: argparse.ArgumentParser, *, path: str, depth: int, help_text: str
) -> list[str]:
    """`parser` and everything under it, depth-first in declaration order."""
    heading = "#" * min(depth, 6)
    body: list[str] = [f"{heading} `{path}`"]
    described = " ".join((parser.description or help_text or "").split())
    if described:
        body.append(described)
    arguments = _argument_lines(parser)
    if arguments:
        body.append("\n".join(arguments))
    sections = ["\n\n".join(body)]
    sub = _subparser_action(parser)
    if sub is None:
        return sections
    helps = {a.dest: (a.help or "") for a in getattr(sub, "_choices_actions", [])}
    seen: set[int] = set()
    for name, child in sub.choices.items():
        if id(child) in seen:
            continue  # an alias for a parser already rendered
        seen.add(id(child))
        sections.extend(
            _command_sections(
                child, path=f"{path} {name}", depth=depth + 1, help_text=helps.get(name, "")
            )
        )
    return sections


def render_cli_md(parser: argparse.ArgumentParser) -> str:
    """Every command in the tree, plus the exit-code table."""
    sections = _command_sections(parser, path="pkc", depth=2, help_text="")
    exits = "\n".join(f"- `{code}` — {meaning}" for code, meaning in _exit_meanings())
    return (
        prompt("steward.reference.cli_header").strip("\n")
        + "\n\n"
        + "\n\n".join(sections)
        + "\n\n"
        + prompt("steward.reference.cli_exit_header").strip("\n")
        + "\n\n"
        + exits
        + "\n"
    )


# ────────────────────────────────────────────────────────────────────── references/gate.md


def render_gate_md(components: Sequence[object] = ()) -> str:
    """One section per violation kind, in the gate's own words, plus the enabled components."""
    parts = [prompt("steward.reference.gate_header").strip("\n")]
    for kind, texts in violation_catalog():
        body = "\n".join(f"- {' '.join(text.split())}" for text in texts)
        parts.append(f"## `{kind}`\n\n{body}")
    if components:
        lines = "\n".join(
            f"- `{getattr(c, 'name', '')}`" for c in components if getattr(c, "name", "")
        )
        if lines:
            parts.append(
                prompt("steward.reference.gate_components_header").strip("\n") + "\n\n" + lines
            )
    return "\n\n".join(parts) + "\n"


# ─────────────────────────────────────────────────────────────────────────── scripts/pkc


def render_shim(backend: BackendManifest) -> str:
    """The `pkc` a session in this project runs: project `.env`, skill hash, framework `pkc`.

    It loads the project's `.env` the way the project's own driver
    does (so the tenant, the engine directory and this machine's ports resolve identically);
    it exports the installed package's hash, which is what puts `Executor-Skill:` in the
    commit trailer; and it hands off to the framework's own entry point through the runner
    the project already configured. It holds no framework logic, because a shim that knew
    anything would be a second implementation to keep in step.
    """
    # How far the skill's `scripts/` directory sits below the project root, derived from the
    # manifest rather than assumed: `.agents/skills` and `.claude/skills` are two segments
    # today and a third harness may not be.
    depth = len(backend.skill_dir.split("/")) + 1
    up = "/".join([".."] * depth)
    return f"""\
#!/bin/sh
# The Steward's `pkc`, generated by `pkc skill install` for {backend.display_label}.
#
# Do not edit: `pkc skill verify` compares this file against a fresh rendering, and an edit
# here is drift like any other. Re-render with `pkc skill install`.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
project=$(CDPATH= cd -- "$script_dir/{up}" && pwd)
cd "$project"

# The project's own environment: the tenant, the engine directory (stated relative to the
# project root, which is why the `cd` above happens first) and this machine's ports.
if [ -f "$project/.env" ]; then
    set -a
    . "$project/.env"
    set +a
fi

# The identity of the words the Steward was taught, stamped into every commit this session
# produces. Read from the file the installer wrote beside the skill, so a re-install moves
# the hash and a hand-edited skill does not.
version_file="$script_dir/../../skill-version.json"
if [ -f "$version_file" ]; then
    hash=$(sed -n 's/.*"sha256"[[:space:]]*:[[:space:]]*"\\([0-9a-f]*\\)".*/\\1/p' \\
        "$version_file" | head -n 1)
    if [ -n "$hash" ]; then
        PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH="$hash"
        export PNEUMA_KNOWLEDGE_STEWARD_SKILL_HASH
    fi
fi

# Session identity survives the shim's exec and repeated commands. Harness thread ids win;
# a terminal without one uses its parent shell's pid and host as the session token.
PKC_STEWARD_SESSION="${{PKC_STEWARD_SESSION:-${{CODEX_THREAD_ID:-${{CLAUDE_SESSION_ID:-$PPID@$(hostname)}}}}}}"
export PKC_STEWARD_SESSION

# uv's cache. Its default is under the invoking user's HOME, which a sandboxed harness cannot
# write — a Codex round then dies on the dependency cache rather than on anything about the
# library, and both acceptance sessions had to invent this variable themselves. Pointed here
# whenever nobody named one, rather than probing whether the default happens to be writable:
# one writable place, the same one for every session, and a cache warmed by the Owner's own
# `pkc` is the cache the harness's `pkc` reuses. The scaffold gitignores it.
if [ -z "${{UV_CACHE_DIR:-}}" ]; then
    UV_CACHE_DIR="$project/.uv-cache"
    export UV_CACHE_DIR
fi

# The framework's entry point, through the runner the project configured. Without a framework
# repository stated, `pkc` is expected on PATH (an installed framework, a container).
if [ -n "${{PNEUMA_APP_FRAMEWORK_REPO:-}}" ]; then
    exec uv run --project "$PNEUMA_APP_FRAMEWORK_REPO" pkc "$@"
fi
exec pkc "$@"
"""


# ──────────────────────────────────────────────────────────────────── workflows/compile.js

_WORKFLOW_HEADER = """\
/**
 * compile — one `pkc` compile round as an order of work that cannot be reordered.
 *
 * Generated by `pkc skill install` for a harness that runs dynamic workflows. Do not edit:
 * `pkc skill verify` compares it against a fresh rendering.
 *
 * Ruling 5: the SKILL.md prose is the complete specification and every harness follows it.
 * This file adds NO rule. What it adds is that read-then-plan-then-write is the only path
 * to `finish` — an agent under pressure can skip a paragraph, and it cannot skip a phase.
 * Every prompt below therefore points at the installed SKILL.md and its references by path
 * instead of restating them; if a sentence here disagreed with that file, the file wins and
 * this one is a bug.
 *
 * Phases:
 *   Open     read what `pkc draft open <job>` printed — the contract and the task.
 *   Read     one agent reads the task and every page it names, and returns a filing plan.
 *   Write    one agent executes that plan through `pkc draft` commands and nothing else.
 *   Finish   `pkc draft finish`; on the gate's exit code, ONE repair pass, then finish again.
 *            A second rejection stops and reports — it is not a third attempt.
 *
 * How to call it:
 *   Workflow({ name: 'compile', args: { job, cwd, pkc } })
 *   Workflow({ scriptPath: '<project>/{workflows_dir}/compile.js', args: { job, cwd } })
 * `args.job` is required. `args.cwd` is the project directory (the sandbox has no `process`
 * global, so it is passed in). `args.pkc` overrides the shim path.
 *
 * One shape note, because the sandbox is narrower than it looks: a workflow script has no
 * filesystem and no shell. The two "script steps" below are therefore single-purpose agents
 * whose whole prompt is one command to run and its output to return — deterministic in what
 * they are asked for, and the phase boundary is what is being enforced either way. And
 * `agent()` resolves to `null` when a subagent dies or is skipped, so every result is
 * checked before it is read.
 */
"""


def render_workflow_js(backend: BackendManifest) -> str:
    """The Claude Code enforcement upgrade. Only rendered when the manifest has a home."""
    assert backend.workflows_dir is not None
    header = _WORKFLOW_HEADER.replace("{workflows_dir}", backend.workflows_dir)
    skill_md = f"{backend.skill_dir}/SKILL.md"
    cli_md = f"{backend.skill_dir}/references/cli.md"
    gate_md = f"{backend.skill_dir}/references/gate.md"
    shim = f"{backend.skill_dir}/scripts/pkc"
    return (
        header
        + """
export const meta = {
  name: 'compile',
  description:
    'Run one pkc compile job as fixed phases: open the draft, read the task and every page it names into a filing plan, execute that plan through pkc draft commands, then finish through the gate with at most one repair pass.',
  phases: [
    { title: 'Open', detail: 'pkc draft open <job> — the contract and the task' },
    { title: 'Read', detail: 'the task and the pages it names → a filing plan' },
    { title: 'Write', detail: 'the plan, through pkc draft commands only' },
    { title: 'Finish', detail: 'pkc draft finish; one repair pass on a gate rejection' },
  ],
}

const A = typeof args === 'string' ? JSON.parse(args) : args || {}
const JOB = String(A.job || '').trim()
const CWD = A.cwd || '.'
const PKC = A.pkc || `${CWD}/__SHIM__`
const SKILL = `${CWD}/__SKILL__`
const CLI = `${CWD}/__CLI__`
const GATE = `${CWD}/__GATE__`

if (!JOB) {
  return { status: 'FAILED', reason: 'compile needs `job` — the id `pkc jobs` lists.' }
}

// The one paragraph every agent in this workflow is handed. Stated once, because a rule
// worded differently to the reader and to the writer is a rule they can disagree about —
// and it points at the skill rather than restating it, for the same reason.
const GROUND = `You are this library's Steward. Read ${SKILL} first: it is the whole
procedure and this workflow adds nothing to it. The command reference is ${CLI}.

Run the library's own shim, exactly as spelled: \\`${PKC}\\`. It is the only way you reach
the library — no other command, no file edit, no git.`

const RUN = (cmd, expect) => `${GROUND}

Run exactly this command, once, from ${CWD}:

    ${cmd}

Then return what it printed and the exit code it ended with. ${expect}
Do not run anything else. Do not repair anything.`

const PLAN_SCHEMA = {
  type: 'object',
  required: ['pages', 'reasoning'],
  properties: {
    reasoning: { type: 'string', description: 'why this filing follows the contract' },
    pages: {
      type: 'array',
      description: 'one entry per canonical page this round will touch',
      items: {
        type: 'object',
        required: ['path', 'exists'],
        properties: {
          path: { type: 'string', description: 'the canonical path, as the outline spells it' },
          exists: { type: 'boolean', description: 'true when the page is already in the library' },
          read: { type: 'boolean', description: 'true when this draft has read it already' },
          claims: {
            type: 'array',
            description: 'claims to add to this page',
            items: {
              type: 'object',
              required: ['heading', 'text', 'citation'],
              properties: {
                heading: { type: 'string' },
                text: { type: 'string', description: 'the claim as it should read' },
                citation: {
                  type: 'string',
                  description: 'the source span it rests on, as [cite: <sid> \\u00b6a-b]',
                },
              },
            },
          },
          supersedes: {
            type: 'array',
            description: 'claims this round replaces because the world changed',
            items: {
              type: 'object',
              required: ['anchor', 'text', 'citation'],
              properties: {
                anchor: { type: 'string', description: 'the existing anchor, c:xxxx' },
                text: { type: 'string' },
                citation: { type: 'string' },
              },
            },
          },
          overview: {
            type: 'string',
            description: 'empty unless this page owes a head or its picture changed',
          },
        },
      },
    },
  },
}

const RESULT_SCHEMA = {
  type: 'object',
  required: ['exit_code', 'output'],
  properties: {
    exit_code: { type: 'integer', description: 'the exit code the command ended with' },
    output: { type: 'string', description: 'everything it printed, verbatim' },
  },
}

phase('Open')
const opened = await agent(
  RUN(
    `${PKC} draft open ${JOB}`,
    'What it prints is the contract you write under and the task of this round; return both whole.',
  ),
  { label: `open:${JOB}`, phase: 'Open', schema: RESULT_SCHEMA },
)
if (!opened) return { status: 'FAILED', reason: 'the open step returned nothing' }
if (opened.exit_code !== 0) {
  return { status: 'FAILED', reason: `pkc draft open exited ${opened.exit_code}`, output: opened.output }
}

phase('Read')
const plan = await agent(
  `${GROUND}

This is what \\`pkc draft open ${JOB}\\` printed — the contract you write under, then the task:

${opened.output}

Read every canonical page the task's outline names that this filing will touch, with
\\`${PKC} draft read-document <path>\\`. A write to a page this draft has not read is refused,
so this reading is the work, not preparation for it. Read the material spans you intend to
cite with \\`${PKC} source fetch\\` where the task did not already give them to you.

Then return the filing plan: which pages, which claims with the source span each one rests
on, which existing claims the material has moved past. Write NOTHING in this phase — no
append, no edit, no supersede.`,
  { label: `read:${JOB}`, phase: 'Read', schema: PLAN_SCHEMA },
)
if (!plan) return { status: 'FAILED', reason: 'the read step returned no plan' }
log(`plan: ${plan.pages?.length || 0} page(s)`)

phase('Write')
const written = await agent(
  `${GROUND}

The draft for job ${JOB} is open and the pages below have been read. Execute this plan
through \\`${PKC} draft\\` commands and nothing else, one command per change:

${JSON.stringify(plan, null, 2)}

The contract and the task, as \\`open\\` printed them:

${opened.output}

A command that exits non-zero told you something true about the library — read it, adjust,
and continue. Do NOT run \\`${PKC} draft finish\\`; the next phase does that. Return what you
wrote and anything the door refused.`,
  { label: `write:${JOB}`, phase: 'Write' },
)
if (written === null) log('WARNING — the write step returned nothing; finishing anyway so the gate reports the truth')

phase('Finish')
let finished = await agent(
  RUN(`${PKC} draft finish`, 'Return its findings whole if it rejected the draft.'),
  { label: `finish:${JOB}`, phase: 'Finish', schema: RESULT_SCHEMA },
)
if (!finished) return { status: 'FAILED', reason: 'the finish step returned nothing' }

if (finished.exit_code === __EXIT_GATE__) {
  log('the gate rejected the draft — one repair pass')
  const repaired = await agent(
    `${GROUND}

\\`${PKC} draft finish\\` rejected the draft. These are its findings; ${GATE} says what each
kind means:

${finished.output}

Repair exactly what it named, through \\`${PKC} draft\\` commands. Do not run \\`finish\\`.`,
    { label: `repair:${JOB}`, phase: 'Finish' },
  )
  if (repaired === null) log('WARNING — the repair step returned nothing')
  finished = await agent(
    RUN(`${PKC} draft finish`, 'Return its findings whole if it rejected the draft again.'),
    { label: `finish:${JOB}:2`, phase: 'Finish', schema: RESULT_SCHEMA },
  )
  if (!finished) return { status: 'FAILED', reason: 'the second finish returned nothing' }
  if (finished.exit_code === __EXIT_GATE__) {
    return {
      status: 'FAILED',
      reason: 'the gate rejected the draft twice; the round stops here and reports',
      findings: finished.output,
    }
  }
}

return { status: finished.exit_code === 0 ? 'OK' : 'FAILED', job: JOB, output: finished.output }
"""
        .replace("__SHIM__", shim)
        .replace("__SKILL__", skill_md)
        .replace("__CLI__", cli_md)
        .replace("__GATE__", gate_md)
        .replace("__EXIT_GATE__", str(_exit_meanings()[-1][0]))
    )


# ───────────────────────────────────────────────────────────────────────── the whole package


def render_skill_package(
    *,
    skill: SkillVersion,
    owner: object | None,
    time_zone: object | None,
    components: Iterable[object] = (),
    backend: BackendManifest,
    cli_parser: argparse.ArgumentParser,
    language: str = "en",
    entry: str = "",
) -> SkillPackage:
    """Every file of the package, for one (contract × wording × components × backend).

    `owner` and `time_zone` are the same two things the compile round is given — a duck-typed
    profile and a `TimeContext` — so `references/compile-instructions.md` is byte-for-byte
    what `pkc draft open` prints as the system text for this deployment. Passing neither
    renders the "subject unknown" variant, which is a real deployment state and not a
    degraded one.

    `entry` is the project-relative path SKILL.md tells the Steward to run `pkc` as —
    `bin/pkc` in a scaffold project, and the skill's own shim when there is no such file
    (`project_entry`). It is part of the rendering, so it is part of the hash: a project that
    gained a `bin/pkc` renders a different package, and `pkc skill verify` says so.
    """
    enabled = tuple(components)
    files: dict[str, bytes] = {
        "SKILL.md": render_skill_md(backend=backend, entry=entry).encode("utf-8"),
        "references/contract.md": (
            prompt("steward.reference.contract_header").strip("\n")
            + "\n\n"
            + skill.instructions.rstrip("\n")
            + "\n"
        ).encode("utf-8"),
        "references/compile-instructions.md": (
            prompt("steward.reference.instructions_header").strip("\n")
            + "\n\n"
            + render_system_contract(skill, owner=owner, time=time_zone)
        ).encode("utf-8"),
        "references/cli.md": render_cli_md(cli_parser).encode("utf-8"),
        "references/consume.md": render_consume_md(skill).encode("utf-8"),
        "references/gate.md": render_gate_md(enabled).encode("utf-8"),
        "scripts/pkc": render_shim(backend).encode("utf-8"),
    }
    if backend.workflows_dir is not None:
        files["workflows/compile.js"] = render_workflow_js(backend).encode("utf-8")
    return SkillPackage(
        files=dict(sorted(files.items())),
        executable=frozenset({"scripts/pkc"}),
        language=language,
        backend=backend.name,
    )
