"""`pkc` — the Steward's whole vocabulary (docs/design/coding-agent-mode.md §5).

The door a coding agent reaches the framework through is a CLI, not a protocol: an agent
already knows how to run a command and read its output, and a command line is the one surface
every harness has (ruling 1). This is that entry point — the same `Settings` the API and the
worker resolve, the same tenant the project states, and one subcommand tree.

Three families live here now (§11 steps 1 and 3): `pkc draft`, the write door; the read
commands — the read half of the HTTP API, over the same service functions and never over
HTTP; and the two ways material enters, `owner say` (the Owner's own statement, as an
ordinary source) and `ingest` (the six contracts). One module per family, registered in one
place, so the tree is read in one screen.

Command names, descriptions and refusal texts come from the prompt catalog keys the langchain
tools use (`compile.tool.*`), so the agent reads ONE vocabulary in the skill, in `--help` and
in every refusal — ruling 4's "the skill is a rendering, not a second text", applied to the
CLI's own help.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ports.canonical_store import CanonicalDirtyError
from pneuma_knowledge_core.prompts import prompt

from . import archive as archive_cmd
from . import check as check_cmd
from . import consult as consult_cmd
from . import config as config_cmd
from . import draft as draft_cmd
from . import ingest as ingest_cmd
from . import owner as owner_cmd
from . import profile as profile_cmd
from . import read as read_cmd
from . import skill as skill_cmd

#: Where a project states which tenant this checkout belongs to. `PNEUMA_KNOWLEDGE_TENANT` is
#: the name the design gives it; `PNEUMA_APP_USER_ID` is the name the scaffold's `app.py`
#: already uses, and both are read so a project generated before this feature keeps working
#: without an edit. `--user` overrides either, and is the only place a user id is typed.
TENANT_ENV = ("PNEUMA_KNOWLEDGE_TENANT", "PNEUMA_APP_USER_ID")
DEFAULT_TENANT = "u-app-owner"


def resolve_tenant(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    for name in TENANT_ENV:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return DEFAULT_TENANT


#: `pkc draft <name>` → the catalog key its description and `--help` come from.
TOOL_HELP = {
    "list-documents": "compile.tool.list_documents",
    "read-document": "compile.tool.read_document",
    "create-document": "compile.tool.create_document",
    "edit-claim": "compile.tool.edit_claim",
    "append-block": "compile.tool.append_block",
    "supersede-claim": "compile.tool.supersede_claim",
    "rewrite-overview": "compile.tool.rewrite_overview",
    "set-fields": "compile.tool.set_fields",
    "search-knowledge": "compile.tool.search_knowledge",
    "search-source": "compile.tool.search_source",
    "finish": "compile.tool.finish_compile",
}


def profile_cmd_settable() -> tuple[str, ...]:
    """The settable profile fields, read from the module that writes them — so `--help` names
    the same list the refusal names."""
    from ..persona_profile import SETTABLE

    return SETTABLE


def _tool_help(name: str) -> str:
    key = TOOL_HELP.get(name)
    return prompt(key) if key else ""


def build_parser(component_tools=()) -> argparse.ArgumentParser:
    """The whole `pkc` tree. `component_tools` are the enabled components' compile tools,
    rendered as subcommands from their own names, descriptions and argument schemas."""
    parser = argparse.ArgumentParser(
        prog="pkc",
        description=(
            "The knowledge library's command line: what the Steward reads, and the one door "
            "it writes through."
        ),
    )
    parser.add_argument(
        "--user",
        default="",
        help=(
            "the tenant to act as; defaults to $PNEUMA_KNOWLEDGE_TENANT (or "
            "$PNEUMA_APP_USER_ID), which is what a project states once"
        ),
    )
    top = parser.add_subparsers(dest="group", required=True)

    draft = top.add_parser(
        "draft",
        help="the claim-level compile draft: open a job, read, write, finish",
        description=(
            "One open compile round. Every command applies exactly one call, post-checks the "
            "page it touched with the gate's own predicates, and spends one call of the "
            "round's budget. Exit codes: 0 ok, 1 nothing to act on, 2 refused, 3 budget "
            "spent, 4 the gate rejected the draft."
        ),
    )
    sub = draft.add_subparsers(dest="command", required=True)

    p = sub.add_parser("open", help="claim the job, render the contract and the task")
    p.add_argument("job_id")

    sub.add_parser(
        "status", help="budget remaining, pages read this draft, what the gate finds owed"
    )
    sub.add_parser("check", help="run the whole gate over the open draft, without finishing")
    p = sub.add_parser("finish", help=_tool_help("finish"))
    p.add_argument("--brief", metavar="FILE|-", help="the Steward brief for this version; non-blank, at most 8000 characters")
    sub.add_parser(
        "abandon", help="release the job back to the queue and delete the draft"
    ).add_argument("--take-over", action="store_true", help="abandon another executor's dead or idle draft after the grace")

    sub.add_parser("list-documents", help=_tool_help("list-documents"))

    p = sub.add_parser("read-document", help=_tool_help("read-document"))
    p.add_argument("path")

    p = sub.add_parser("create-document", help=_tool_help("create-document"))
    p.add_argument("path")
    p.add_argument("--frontmatter", required=True, help="the document's frontmatter as JSON")
    p.add_argument("--body-file", default="", help="the body; stdin when omitted or given as `-`")

    p = sub.add_parser("append-block", help=_tool_help("append-block"))
    p.add_argument("path")
    p.add_argument("--heading", required=True)
    p.add_argument("--text-file", default="", help="the claim text; stdin when omitted or given as `-`")

    for name in ("edit-claim", "supersede-claim"):
        p = sub.add_parser(name, help=_tool_help(name))
        p.add_argument("path")
        p.add_argument("anchor")
        p.add_argument("--text-file", default="", help="the claim text; stdin when omitted or given as `-`")

    p = sub.add_parser("rewrite-overview", help=_tool_help("rewrite-overview"))
    p.add_argument("path")
    p.add_argument(
        "--json-file",
        default="",
        help=(
            "the overview as JSON — definition, summary, introduction, connections, fields; "
            "stdin when omitted or given as `-`"
        ),
    )

    p = sub.add_parser("set-fields", help=_tool_help("set-fields"))
    p.add_argument("path")
    p.add_argument("--json", dest="json_text", default="", help="the fields as JSON")

    for name in ("search-knowledge", "search-source"):
        p = sub.add_parser(name, help=_tool_help(name))
        p.add_argument("query")

    for tool in component_tools:
        p = sub.add_parser(
            tool.name.replace("_", "-"), help=(tool.description or "").strip()
        )
        schema = getattr(tool, "args_schema", None)
        fields = getattr(schema, "model_fields", {}) or {}
        for field_name, info in fields.items():
            p.add_argument(
                f"--{field_name.replace('_', '-')}",
                dest=field_name,
                default=None,
                help=(info.description or "").strip() or None,
            )

    _add_read_commands(top)
    _add_write_commands(top)
    _add_archive_commands(top)
    skill_cmd.add_skill_commands(top)
    return parser


#: `--json` is spelled once and added to every command that reports state, so a workflow
#: never has to remember which of them learned it. It is deliberately NOT on the `draft`
#: write verbs: what they return is a tool's own sentence, and a JSON envelope around a
#: refusal text would be a second rendering of the one vocabulary ruling 4 keeps single.
def _jsonable(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="machine-readable output; the default is the same state as prose",
    )
    # Prose is paged: a reader with a context window gets one page and a footer saying how
    # much more there is, instead of everything at once. JSON is never paged.
    parser.add_argument(
        "--page", type=int, default=1, metavar="N",
        help="which page of a long prose output to print (default 1; the footer names the next)",
    )
    parser.add_argument(
        "--page-chars", type=int, default=read_cmd.PAGE_CHARS, metavar="CHARS",
        help=f"characters per page (default {read_cmd.PAGE_CHARS}; 0 = no paging)",
    )
    parser.add_argument(
        "--all-pages", dest="all_pages", action="store_true",
        help="print the whole prose output, however long",
    )
    return parser


#: `--include-archived` is spelled once and added to every command that SEARCHES or LISTS,
#: because the archive's second ruling is one rule: whatever a lane reads by default, it
#: reads without the archive, and the exception is stated by the caller
#: (docs/design/archive.md §4). It is deliberately NOT on `canonical read` / `canonical
#: history` / `source show` / `source fetch`: those address one thing by name, and an address
#: always resolves (I3, I4) — a flag there would suggest it might not.
def _archivable(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--include-archived",
        dest="include_archived",
        action="store_true",
        help=(
            "read the archive too. Off by default: an archived page or source is one the "
            "owner moved out of the answering set. On, what comes back from the archive is "
            "labelled `[archived]` (`archived` in `--json`), so history never reads as the "
            "present"
        ),
    )
    return parser


def _add_evolve_draft_commands(esub) -> None:
    door = esub.add_parser("draft", help="propose and restructure through the evolve gate")
    sub = door.add_subparsers(dest="evolve_command", required=True)
    p = sub.add_parser("open", help="claim an evolve job; print evidence, contract and gate")
    choice = p.add_mutually_exclusive_group(required=True)
    choice.add_argument("job_id", nargs="?")
    choice.add_argument("--new", action="store_true", help="open an Owner-requested evolve job")
    p.add_argument("--from", dest="from_proposal", default="", help="continue an existing proposal on its pinned base")
    for name, help_text in (
        ("status", "the budget and the gate's findings"),
        ("check", "check the whole evolve draft without finishing"),
        ("finish", "run the evolve gate and write the review proposal"),
        ("abandon", "release the job and delete its ephemeral draft"),
    ):
        parser = sub.add_parser(name, help=help_text)
        if name == "abandon":
            parser.add_argument("--take-over", action="store_true")
    p = sub.add_parser("propose", help="phase-1 judgement as EvolveProposal JSON")
    _evolve_file(p)
    p = sub.add_parser("move-claim", help="move an anchored claim verbatim; create an empty target if needed")
    p.add_argument("from_path")
    p.add_argument("anchor")
    p.add_argument("to_path")
    p = sub.add_parser("rename", help="rename a document, preserving its anchors and identity")
    p.add_argument("path")
    p.add_argument("new_path")
    p = sub.add_parser("retire", help="retire a page; every dropped anchor must be named in the proposal")
    p.add_argument("path")
    p = sub.add_parser("contract", help="revise the contract for adoption as a new version")
    csub = p.add_subparsers(dest="contract_command", required=True)
    _evolve_file(csub.add_parser("edit", help="the revised contract text; bounded to 100000 characters"))


def _evolve_file(parser) -> None:
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--file", help="read text from a file (or - for stdin)")
    choice.add_argument("stdin", nargs="?", choices=["-"], help="read text from stdin")


def _add_read_commands(top) -> None:  # noqa: ANN001
    """§5.1 — the read half of the HTTP API, as commands."""
    index = top.add_parser("index", help="source indexing judgements")
    isub = index.add_subparsers(dest="command", required=True)
    door = isub.add_parser("episodes", help="select grounded episodes through the index door")
    esub = door.add_subparsers(dest="episodes_command", required=True)
    esub.add_parser("open", help="claim one source's episodes job; print structure, rules and budget").add_argument("job_id")
    for name, help_text in (
        ("status", "remaining budget and blocks with no episode"),
        ("finish", "record the manifest, replace L2 vectors and close the job"),
        ("abandon", "release the job and delete its ephemeral draft"),
    ):
        parser = esub.add_parser(name, help=help_text)
        if name == "abandon":
            parser.add_argument("--take-over", action="store_true")
    _evolve_file(esub.add_parser("propose", help="closed intervals with grounded title/description; gaps and [] allowed"))
    for name in ("outline", "glance"):
        description = prompt(f"steward.cli.{name}")
        p = _archivable(_jsonable(top.add_parser(
            name, help=description, description=description,
        )))
        if name == "outline":
            p.add_argument("--family", metavar="TEMPLATE", help="show only this declared path-template family")
            p.add_argument("--definitions", action="store_true", help="add each page's one-line definition when present")

    canonical = top.add_parser("canonical", help="pages, a page, a claim's chain")
    csub = canonical.add_subparsers(dest="command", required=True)
    _archivable(_jsonable(csub.add_parser("ls", help="every canonical page, by path")))
    p = _jsonable(
        csub.add_parser(
            "read",
            help=(
                _tool_help("read-document")
                + " Unconditional: a page addressed by path answers whether or not it is "
                "archived."
            ),
        )
    )
    p.add_argument("path", nargs="+", help="one page, or several read in one process")
    p = _jsonable(
        csub.add_parser(
            "history",
            help="the supersession chains on a page — what a claim used to say",
        )
    )
    p.add_argument("path")
    p.add_argument("anchor", nargs="?", default=None, help="one anchor (c:xxxx); all when omitted")

    source = top.add_parser("source", help="L0: sources, structure, verbatim spans")
    ssub = source.add_subparsers(dest="command", required=True)
    p = _archivable(
        _jsonable(ssub.add_parser("ls", help="this library's sources, newest first"))
    )
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--query", default=None, help="match the title")
    p.add_argument("--kind", default=None)
    for name in ("show", "structure"):
        p = _jsonable(
            ssub.add_parser(
                name,
                help=(
                    "one source: metadata and its structure map — unconditional, whatever the "
                    "owner archived"
                ),
            )
        )
        p.add_argument("source_id")
    p = _jsonable(
        ssub.add_parser(
            "fetch",
            help="verbatim L0 for a block span — unconditional, whatever any plan said",
        )
    )
    p.add_argument("source_id")
    p.add_argument(
        "span", nargs="+",
        help="one or more ¶a-b, ¶a or a-b spans; exactly two bare integers `a b` mean one span",
    )

    p = _archivable(_jsonable(top.add_parser("search", help=_tool_help("search-source"))))
    p.add_argument("query")
    p.add_argument("--lexical", action="store_true", help="L1 only")
    p.add_argument("--semantic", action="store_true", help="L2 only")
    p.add_argument("--fused", action="store_true", help="the RRF fusion `rag` uses (default)")
    p.add_argument("--limit", type=int, default=10)

    p = _jsonable(top.add_parser("jobs", help="the queue, newest first"))
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--status", default=None)
    p.add_argument("--kind", default=None)

    p = _jsonable(top.add_parser("history", help="compile versions, jobs and sources, newest first"))
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--kind", default=None, choices=("patch", "job", "snapshot"))

    p = _jsonable(top.add_parser("brief", help="the post-compile brief of one version"))
    p.add_argument("version", help="a patch ref as `pkc history` shows it; a prefix is enough")

    p = _jsonable(top.add_parser("consultations", help="kept records of use, newest first"))
    p.add_argument("--limit", type=int, default=25)

    p = _jsonable(top.add_parser("spend", help="what the recorded consultations spent, in tokens"))
    p.add_argument("--days", type=int, default=30)

    evolve = top.add_parser("evolve", help="schema-evolve proposals")
    esub = evolve.add_subparsers(dest="command", required=True)
    _jsonable(esub.add_parser("ls", help="every proposal and its state"))
    p = _jsonable(esub.add_parser("show", help="one proposal, whole"))
    p.add_argument("task_id")
    p = esub.add_parser("adopt", help="enqueue the Owner's adoption of a proposal")
    p.add_argument("task_id")
    _add_evolve_draft_commands(esub)

    p = _archivable(
        _jsonable(
            top.add_parser("recall", help="the fast lane — or the context it would answer from")
        )
    )
    p.add_argument("query")
    p.add_argument(
        "--evidence",
        action="store_true",
        help=(
            "print the assembled context instead of answering it: exactly what the lane "
            "would have handed its model, with the same handles and the same manifest"
        ),
    )
    p.add_argument(
        "--visitor-class",
        default=None,
        choices=("silent", "audit", "business"),
        help=(
            "what this call leaves behind in the attention ledger: `silent` records "
            "NOTHING AT ALL (no consultation, nothing for `pkc consultations`, `pkc spend` "
            "or the attention report to see), `business` and `audit` record one "
            "consultation. Default depends on the mode: `--evidence` defaults to "
            "`business`, because a Steward answering the Owner from that context IS the "
            "library being used; `pkc recall` on its own defaults to `silent`, because a "
            "call whose answer nobody reads is an evaluation of the lane, not a use of the "
            "library"
        ),
    )
    p.add_argument("--style", default=None, choices=("concise", "conversational", "detailed"))
    p.add_argument("--as-of", default=None, help="the instant relative time resolves against")

    library = top.add_parser("library", help="the library as a whole")
    lsub = library.add_subparsers(dest="command", required=True)
    _jsonable(
        lsub.add_parser(
            "check",
            help=(
                "the gate's predicates over the committed library — reported, never "
                "repaired; exit 4 when anything is found"
            ),
        )
    )


def _add_write_commands(top) -> None:  # noqa: ANN001
    """§5.3 and §5.4 — the Owner's own statement, and the six contracts."""
    owner = top.add_parser("owner", help="what the Owner says, as a source")
    osub = owner.add_subparsers(dest="command", required=True)
    p = _jsonable(
        osub.add_parser(
            "say",
            help=(
                "record one owner-dialogue/v1 statement and enqueue its compile — every "
                "correction starts here, and no command changes a claim without a job. "
                "Inside the console's Steward session (and only there, where the bridge "
                "holds the transcript) the text must be a verbatim substring of something "
                "the owner typed in that session, whitespace aside; a paraphrase is "
                "refused with exit 2. A terminal session has no transcript to check "
                "against and is unchanged."
            ),
        )
    )
    p.add_argument("--text-file", default="", help="the statement; stdin when omitted or given as `-`")
    p.add_argument(
        "--about",
        action="append",
        default=[],
        help="a canonical page this statement concerns; repeatable, a hint and not a permission",
    )
    p.add_argument("--said-at", default=None, help="when it was said (ISO 8601); now when omitted")

    config = top.add_parser("config", help="the engine's retrieval choice")
    csub = config.add_subparsers(dest="command", required=True)
    p = _jsonable(csub.add_parser("set", help="set semantic retrieval on or off"))
    p.add_argument("key", choices=("semantic_retrieval",))
    p.add_argument("value", choices=("on", "off"))

    profile = top.add_parser(
        "profile",
        help="who the Owner is — the one thing a compile cannot infer from the material",
        description=(
            "The library belongs to one person, and the contract files that person's own "
            "facts on their profile rather than on a page about a stranger — which it can "
            "only do if the profile names them. `show` reports whether it still holds the "
            "generator's placeholder; `set` records what the Owner supplied, writing this "
            "project's engine/persona/profile.yaml and the persisted profile together."
        ),
    )
    psub = profile.add_subparsers(dest="command", required=True)
    _jsonable(
        psub.add_parser(
            "show",
            help=(
                "the profile this library compiles under, and whether it is still the "
                "placeholder"
            ),
        )
    )
    p = _jsonable(
        psub.add_parser(
            "set",
            help=(
                "record the Owner's own information — the same shape "
                "engine/persona/profile.yaml holds, validated the same way, written once"
            ),
        )
    )
    p.add_argument(
        "--file",
        dest="payload_file",
        default=None,
        help="a profile mapping as YAML or JSON; `-` reads stdin",
    )
    p.add_argument(
        "--field",
        dest="fields",
        action="append",
        default=[],
        help=(
            "one field as `name=value`; repeatable. Settable: "
            + ", ".join(profile_cmd_settable())
        ),
    )

    p.add_argument("--provenance", choices=("inferred", "owner"), default=None)
    p.add_argument("payload_stdin", nargs="?", choices=("-",), help="read a profile mapping from stdin")
    p = _jsonable(psub.add_parser("confirm", help="confirm profile fields as the Owner's own"))
    confirm = p.add_mutually_exclusive_group(required=True)
    confirm.add_argument("--field", dest="fields", action="append", default=[])
    confirm.add_argument("--all", dest="all_fields", action="store_true")

    p = _jsonable(top.add_parser("ingest", help="import one payload under one of the six contracts"))
    p.add_argument("--contract", required=True, choices=sorted(ingest_cmd.CONTRACTS))
    p.add_argument("--file", dest="payload_file", default="", help="the payload; stdin when omitted or given as `-`")
    p.add_argument("--intake", default=None, help="override the proposed intake archetype")

    consult = top.add_parser("consult", help="record an answer after handed or direct reading")
    nsub = consult.add_subparsers(dest="command", required=True)
    p = _jsonable(
        nsub.add_parser(
            "answer",
            help=(
                "supply the answer for a handoff and record the consultation — the lane's "
                "own builder and emission, with every citation resolved in this tenant"
            ),
        )
    )
    p.add_argument("handoff_id")
    p.add_argument("--text-file", default="", help="the answer; stdin when omitted or given as `-`")
    p.add_argument("--kind", default="answer", choices=consult_cmd.ANSWER_KINDS)
    p.add_argument("stdin", nargs="?", choices=["-"], help="read the answer from stdin")
    p = _jsonable(nsub.add_parser("record", help="record direct reading without a handoff"))
    p.add_argument("--question", required=True)
    p.add_argument("--text-file", default="", help="the answer; stdin when omitted or given as `-`")
    p.add_argument("stdin", nargs="?", choices=["-"], help="read the answer from stdin")
    p.add_argument("--kind", default="answer", choices=consult_cmd.ANSWER_KINDS)
    p.add_argument(
        "--visitor-class", choices=("business", "audit", "silent"), default="business",
        help="business records and queues attention; audit records only; silent records nothing",
    )
    _jsonable(nsub.add_parser("pending", help="the handoffs still waiting for an answer"))


#: What the CONFIRM says about the owner's words, in `--help`. The rule is the service's
#: (`422 note_required`) and this door's, and it is spelled once: the record's reason is an
#: `owner-dialogue/v1` statement the record then cites, so it can only be words the owner
#: sent WITH the decision (`cli/archive.py`).
_ARCHIVE_WORDS_HELP = (
    "the owner's own reason, and one of these two is REQUIRED here: `--statement` names the "
    "owner-dialogue source `pkc owner say` printed, `--note-file` carries the same words "
    "(`-` for stdin). The archive record quotes the owner, and there is no default sentence "
    "anywhere to put in their place. Inside a console Steward session a note must be a "
    "verbatim substring of something the owner typed there."
)

#: The same two options at the PLAN, where neither is required. A plan decides nothing and
#: quotes nothing: `--statement` fixes the source the record will cite, `--note-file` is
#: display text kept on the proposal, and the reason itself arrives with the confirm.
_ARCHIVE_PLAN_WORDS_HELP = (
    "optional here — a plan decides nothing, so it quotes no sentence of its own. "
    "`--statement` names the owner-dialogue source `pkc owner say` printed and FIXES what "
    "the record will cite; `--note-file` (`-` for stdin) is a line kept on the proposal for "
    "a listing to show. The reason the record quotes is what `pkc archive confirm` carries. "
    "Inside a console Steward session a note must be a verbatim substring of something the "
    "owner typed there."
)


def _add_archive_commands(top) -> None:  # noqa: ANN001
    """§5.5 — the archive, over `archive_service`'s own functions (docs/design/archive.md)."""
    archive = top.add_parser(
        "archive",
        help="retire knowledge without deleting it: propose, confirm, and what is archived now",
        description=(
            "Archiving is a MOVE, never a deletion: the page goes under `archive/` with its "
            "history, a short record stays at its old path saying what the subject was and "
            "why the owner retired it, and a source keeps every block and gains a date. The "
            "set is computed from what the owner named, shown whole, and moves nothing until "
            "it is confirmed against the same library state. Exit codes: 0 ok, 1 no such "
            "proposal, 2 refused."
        ),
    )
    asub = archive.add_subparsers(dest="command", required=True)

    p = _jsonable(
        asub.add_parser(
            "propose",
            help=(
                "compute what retiring these pages and sources would take — the seeds, "
                "everything that follows from them, and the record each page would leave"
            ),
        )
    )
    p.add_argument(
        "--document",
        dest="documents",
        action="append",
        default=[],
        help="a canonical page to retire, by path; repeatable",
    )
    p.add_argument(
        "--source",
        dest="sources",
        action="append",
        default=[],
        help="a source to retire, by id; repeatable",
    )
    p.add_argument(
        "--action",
        default="archive",
        choices=("archive", "unarchive"),
        help="which direction; `unarchive` brings a page back and removes its record",
    )
    p.add_argument(
        "--statement", dest="statement_ref", default=None, help=_ARCHIVE_PLAN_WORDS_HELP
    )
    p.add_argument("--note-file", default=None, help=_ARCHIVE_PLAN_WORDS_HELP)

    p = _jsonable(asub.add_parser("ls", help="every archive proposal and its state"))
    p.add_argument("--limit", type=int, default=50)

    p = _jsonable(
        asub.add_parser(
            "show",
            help=(
                "one proposal whole: its status as it reads now, every item with the reason "
                "it is there, and the job when one was queued"
            ),
        )
    )
    p.add_argument("proposal_id")

    p = _jsonable(
        asub.add_parser(
            "confirm",
            help=(
                "accept a proposal and queue the one job that executes it — the items the "
                "owner NAMED, and the ones that follow only with `--cascade`"
            ),
        )
    )
    p.add_argument("proposal_id")
    p.add_argument(
        "--cascade",
        action="store_true",
        help=(
            "confirm the items the planner computed from the seeds too. Without it they are "
            "listed and left where they are"
        ),
    )
    p.add_argument(
        "--deselect",
        action="append",
        default=[],
        help="untick one item the plan selected, by ref; repeatable",
    )
    p.add_argument("--statement", dest="statement_ref", default=None, help=_ARCHIVE_WORDS_HELP)
    p.add_argument("--note-file", default=None, help=_ARCHIVE_WORDS_HELP)

    p = _jsonable(
        asub.add_parser("drop", help="close one proposal nobody is going to act on")
    )
    p.add_argument("proposal_id")

    _jsonable(
        asub.add_parser(
            "inventory",
            help=(
                "what is in the archive now: pages with the day they went in and the record "
                "standing at their live path, and sources with the day they were retired"
            ),
        )
    )


def _tool_call(args: argparse.Namespace, component_tools=()) -> tuple[str, dict] | None:
    """One parsed command → the tool name and arguments to apply, or None when the command is
    not a tool call (`open`, `status`, `check`, `finish`, `abandon`)."""
    command = args.command
    if command == "list-documents":
        return "list_documents", {}
    if command == "read-document":
        return "read_document", {"path": args.path}
    if command == "create-document":
        return "create_document", {
            "path": args.path,
            "frontmatter": draft_cmd.read_json_arg(args.frontmatter),
            "body": draft_cmd.read_text_arg(args.body_file or None),
        }
    if command == "append-block":
        return "append_block", {
            "path": args.path,
            "heading": args.heading,
            "text": draft_cmd.read_text_arg(args.text_file or None),
        }
    if command in ("edit-claim", "supersede-claim"):
        return command.replace("-", "_"), {
            "path": args.path,
            "anchor_id": args.anchor,
            "new_text": draft_cmd.read_text_arg(args.text_file or None),
        }
    if command == "rewrite-overview":
        payload = dict(draft_cmd.read_json_arg(None, args.json_file or None))
        payload["path"] = args.path
        # The same argument shape `_RewriteOverviewArgs` declares: the four prose slots, the
        # connections, and the structured fields beside them. Unknown keys are dropped rather
        # than forwarded, so a typo is refused by the parser here instead of by a TypeError
        # from a closure.
        allowed = ("path", "definition", "summary", "introduction", "connections", "fields")
        return "rewrite_overview", {k: payload[k] for k in allowed if k in payload}
    if command == "set-fields":
        return "set_fields", {
            "path": args.path,
            "fields": draft_cmd.read_json_arg(args.json_text or None),
        }
    if command in ("search-knowledge", "search-source"):
        return command.replace("-", "_"), {"query": args.query}
    for tool in component_tools:
        if tool.name.replace("_", "-") != command:
            continue
        schema = getattr(tool, "args_schema", None)
        fields = getattr(schema, "model_fields", {}) or {}
        supplied = {}
        for field_name, info in fields.items():
            value = getattr(args, field_name, None)
            if value is None:
                continue
            # A string field takes the argument as typed; anything else is JSON, because a
            # list or an object cannot be typed as a bare word and guessing which is which is
            # how a tool ends up with a string where it declared a number.
            supplied[field_name] = (
                value if info.annotation is str else draft_cmd.read_json_arg(value)
            )
        return tool.name, supplied
    return None


async def _draft_command(rt, args: argparse.Namespace, component_tools) -> int:  # noqa: ANN001
    if args.command == "open":
        return await draft_cmd.cmd_open(rt, args.job_id)
    if args.command == "status":
        return await draft_cmd.cmd_status(rt)
    if args.command == "check":
        return await draft_cmd.cmd_check(rt)
    if args.command == "finish":
        brief_file = getattr(args, "brief", None)
        return await draft_cmd.cmd_finish(
            rt, brief=draft_cmd.read_text_arg(brief_file) if brief_file is not None else None,
        )
    if args.command == "abandon":
        return await draft_cmd.cmd_abandon(rt, take_over=getattr(args, "take_over", False))
    call = _tool_call(args, component_tools)
    if call is None:
        print(f"unknown draft command: {args.command}", file=sys.stderr)
        return draft_cmd.EXIT_NOTHING
    name, tool_args = call
    return await draft_cmd.run_tool(rt, name, tool_args)


#: What `pkc recall` records when the Owner did not say (§5.1). Two modes, two answers, and
#: the difference is who reads the answer. `--evidence` hands the assembled context to a
#: Steward who is about to answer the Owner with it: that is the library being used, and the
#: use-side ledger — consultations, spend, the attention report — exists to hold exactly that.
#: `pkc recall` on its own calls the answer model and prints the answer to whoever typed it,
#: which is how the lane is EVALUATED rather than how the library is consulted, so it records
#: nothing unless asked to.
RECALL_VISITOR_DEFAULTS: dict[bool, str] = {True: "business", False: "silent"}


def recall_visitor_class(args: argparse.Namespace) -> str:
    """The `--visitor-class` this call runs under: what was typed, else the mode's default."""
    stated = getattr(args, "visitor_class", None)
    return str(stated) if stated else RECALL_VISITOR_DEFAULTS[bool(getattr(args, "evidence", False))]


async def dispatch(ctx, args: argparse.Namespace, *, out=None, err=None) -> int:  # noqa: ANN001
    """Every command group but `draft`, over an already-built context.

    One function, so the tree has ONE place that maps a parsed command onto a handler; the
    tests drive it with a stand-in context, which is what lets the whole surface be exercised
    keyless. `out`/`err` default to the process streams and are injected by those tests for
    the same reason `DraftRuntime` takes them: a command's output is part of what it does.
    """
    out = out or sys.stdout
    err = err or sys.stderr
    user = UserId(resolve_tenant(args.user))
    as_json = bool(getattr(args, "as_json", False))
    group = args.group
    command = getattr(args, "command", "")

    if group == "index" and command == "episodes":
        from . import episodes

        rt = await episodes.build_runtime(ctx, user)
        rt.out, rt.err = out, err
        verb = args.episodes_command
        if verb == "open":
            return await episodes.cmd_open(rt, args.job_id)
        if verb == "status":
            return await episodes.cmd_status(rt)
        if verb == "propose":
            return await episodes.cmd_propose(rt, file=args.file or "-")
        if verb == "finish":
            return await episodes.cmd_finish(rt)
        return await draft_cmd.cmd_abandon(rt, take_over=getattr(args, "take_over", False))

    if group == "evolve" and command in ("draft", "adopt"):
        from . import evolve as evolve_cmd

        if command == "adopt":
            return await evolve_cmd.cmd_adopt(ctx, user, args.task_id, out=out, err=err)
        rt = await evolve_cmd.build_runtime(ctx, user)
        rt.out, rt.err = out, err
        verb = args.evolve_command
        if verb == "open":
            return await evolve_cmd.cmd_open(rt, args.job_id or "", new=args.new, from_proposal=args.from_proposal)
        if verb == "status":
            return await evolve_cmd.cmd_status(rt)
        if verb == "check":
            return await evolve_cmd.cmd_check(rt)
        if verb == "finish":
            return await evolve_cmd.cmd_finish(rt)
        if verb == "abandon":
            return await draft_cmd.cmd_abandon(rt, take_over=getattr(args, "take_over", False))
        values = {key: getattr(args, key) for key in ("from_path", "anchor", "to_path", "path", "new_path") if hasattr(args, key)}
        if verb in ("propose", "contract"):
            values["file"] = args.file or "-"
        return await evolve_cmd.run_command(rt, verb, **values)

    if group in ("outline", "glance", "canonical", "source", "search", "jobs", "history", "brief",
                 "consultations", "spend", "evolve", "recall"):
        rt = read_cmd.ReadRuntime(
            user_id=user, ctx=ctx, as_json=as_json, out=out, err=err,
            page=getattr(args, "page", 1), page_chars=getattr(args, "page_chars", read_cmd.PAGE_CHARS),
            all_pages=bool(getattr(args, "all_pages", False)),
        )
        include_archived = bool(getattr(args, "include_archived", False))
        if group == "outline":
            return await read_cmd.cmd_outline(
                rt, family=args.family, definitions=args.definitions,
                include_archived=include_archived,
            )
        if group == "glance":
            return await read_cmd.cmd_glance(rt, include_archived=include_archived)
        if group == "canonical":
            if command == "ls":
                return await read_cmd.cmd_canonical_ls(
                    rt, include_archived=include_archived
                )
            if command == "read":
                return await read_cmd.cmd_canonical_read(rt, args.path)
            return await read_cmd.cmd_canonical_history(rt, args.path, args.anchor)
        if group == "source":
            if command == "ls":
                return await read_cmd.cmd_source_ls(
                    rt,
                    limit=args.limit,
                    query=args.query,
                    kind=args.kind,
                    include_archived=include_archived,
                )
            if command in {"show", "structure"}:
                return await read_cmd.cmd_source_show(rt, args.source_id)
            return await read_cmd.cmd_source_fetch(
                rt, args.source_id, args.span
            )
        if group == "search":
            mode = (
                "lexical" if args.lexical else "semantic" if args.semantic else "fused"
            )
            return await read_cmd.cmd_search(
                rt,
                args.query,
                mode=mode,
                limit=args.limit,
                include_archived=include_archived,
            )
        if group == "jobs":
            return await read_cmd.cmd_jobs(
                rt, limit=args.limit, status=args.status, kind=args.kind
            )
        if group == "history":
            return await read_cmd.cmd_history(rt, limit=args.limit, kind=args.kind)
        if group == "brief":
            return await read_cmd.cmd_brief(rt, args.version)
        if group == "consultations":
            return await read_cmd.cmd_consultations(rt, limit=args.limit)
        if group == "spend":
            return await read_cmd.cmd_spend(rt, days=args.days)
        if group == "evolve":
            if command == "ls":
                return await read_cmd.cmd_evolve_ls(rt)
            return await read_cmd.cmd_evolve_show(rt, args.task_id)
        if args.evidence:
            return await read_cmd.cmd_recall_evidence(
                rt,
                args.query,
                handoffs=_handoffs(ctx),
                visitor_class=recall_visitor_class(args),
                as_of=args.as_of,
                style=args.style,
                include_archived=include_archived,
            )
        return await read_cmd.cmd_recall(
            rt,
            args.query,
            visitor_class=recall_visitor_class(args),
            as_of=args.as_of,
            style=args.style,
            include_archived=include_archived,
            emit_consultation=_recall_recorder(ctx, user),
        )

    if group == "library":
        return await check_cmd.cmd_library_check(
            ctx, user, as_json=as_json, out=out, err=err
        )
    if group == "owner":
        return await owner_cmd.cmd_owner_say(
            ctx,
            user,
            text=draft_cmd.read_text_arg(args.text_file or None),
            about=list(args.about or []),
            said_at=args.said_at,
            as_json=as_json,
            out=out,
            err=err,
        )
    if group == "config":
        return config_cmd.cmd_config_set(
            ctx.settings, args.key, args.value, as_json=as_json, out=out, err=err
        )
    if group == "profile":
        if command == "show":
            return await profile_cmd.cmd_profile_show(
                ctx, user, as_json=as_json, out=out, err=err
            )
        if command == "confirm":
            return await profile_cmd.cmd_profile_confirm(
                ctx, user, fields=args.fields, all_fields=args.all_fields,
                as_json=as_json, out=out, err=err,
            )
        if args.payload_stdin is not None:
            if args.payload_file is not None or args.fields:
                print("refused: use one of --file, -, or --field", file=err)
                return draft_cmd.EXIT_REFUSED
            args.payload_file = args.payload_stdin
        if args.payload_file is not None and args.fields:
            print("refused: use one of --file, -, or --field", file=err)
            return draft_cmd.EXIT_REFUSED
        # `--file` is OPTIONAL here, so it is read only when it was given: an omitted flag
        # means "no payload", never "read stdin" — a `--field`-only call must not hang on a
        # terminal.
        payload = (
            draft_cmd.read_text_arg(args.payload_file)
            if getattr(args, "payload_file", None) is not None
            else None
        )
        return await profile_cmd.cmd_profile_set(
            ctx,
            user,
            payload_text=payload,
            fields=list(args.fields or []),
            provenance=args.provenance,
            as_json=as_json,
            out=out,
            err=err,
        )
    if group == "ingest":
        return await ingest_cmd.cmd_ingest(
            ctx,
            user,
            contract_name=args.contract,
            payload_text=draft_cmd.read_text_arg(args.payload_file or None),
            intake=args.intake,
            as_json=as_json,
            out=out,
            err=err,
        )
    if group == "archive":
        # `--note-file` is OPTIONAL here, so it is read only when it was given: an omitted
        # flag means "no note", never "read stdin" — the two spellings `pkc draft` collapses
        # would make a propose with only `--statement` hang on a terminal.
        note = (
            draft_cmd.read_text_arg(args.note_file).rstrip("\n")
            if getattr(args, "note_file", None) is not None
            else None
        )
        if command == "propose":
            return await archive_cmd.cmd_archive_propose(
                ctx,
                user,
                action=args.action,
                documents=list(args.documents or []),
                sources=list(args.sources or []),
                statement_ref=args.statement_ref,
                note=note,
                as_json=as_json,
                out=out,
                err=err,
            )
        if command == "ls":
            return await archive_cmd.cmd_archive_ls(
                ctx, user, limit=args.limit, as_json=as_json, out=out, err=err
            )
        if command == "show":
            return await archive_cmd.cmd_archive_show(
                ctx, user, args.proposal_id, as_json=as_json, out=out, err=err
            )
        if command == "drop":
            return await archive_cmd.cmd_archive_drop(
                ctx, user, args.proposal_id, as_json=as_json, out=out, err=err
            )
        if command == "inventory":
            return await archive_cmd.cmd_archive_inventory(
                ctx, user, as_json=as_json, out=out, err=err
            )
        return await archive_cmd.cmd_archive_confirm(
            ctx,
            user,
            args.proposal_id,
            cascade=bool(args.cascade),
            deselect=list(args.deselect or []),
            statement_ref=args.statement_ref,
            note=note,
            as_json=as_json,
            out=out,
            err=err,
        )
    if group == "consult":
        if command == "pending":
            return await consult_cmd.cmd_consult_pending(
                ctx, user, handoffs=_handoffs(ctx), as_json=as_json, out=out, err=err
            )
        if args.stdin and args.text_file:
            print("choose --text-file or `-` for stdin, not both", file=err)
            return consult_cmd.EXIT_REFUSED
        if command == "record":
            return await consult_cmd.cmd_consult_record(
                ctx, user, question=args.question,
                text=draft_cmd.read_text_arg(args.text_file or None), kind=args.kind,
                visitor_class=args.visitor_class, as_json=as_json, out=out, err=err,
            )
        return await consult_cmd.cmd_consult_answer(
            ctx,
            user,
            args.handoff_id,
            handoffs=_handoffs(ctx),
            text=draft_cmd.read_text_arg(args.text_file or None),
            kind=args.kind,
            as_json=as_json,
            out=out,
            err=err,
        )
    print(f"unknown command group: {group}", file=err)
    return draft_cmd.EXIT_NOTHING


def _handoffs(ctx):  # noqa: ANN001
    """The pending-handoff store, wrapped at the call site — the same place `pkc draft`
    wraps the draft store (`cli/runtime.py`), and for the same reason: it is an ephemeral
    row beside the queue, not a field of the deployment."""
    from ..adapters.postgres import PostgresRecallHandoffStore

    return PostgresRecallHandoffStore(ctx.store)


def _recall_recorder(ctx, user: UserId):  # noqa: ANN001
    """The answering routes' own recording, for `pkc recall`: build with the fast lane's
    builder, write through the store that also enqueues the `recall_projection` job."""
    import uuid as _uuid
    from datetime import datetime, timezone

    from pneuma_knowledge_core.recall.consultation import consultation_from_fast

    async def record(answer, *, question: str, as_of, visitor_class: str) -> None:  # noqa: ANN001
        if visitor_class == "silent":
            return
        snaps = await ctx.canonical.snapshots(user)
        await ctx.store.create_consultation(
            user,
            consultation_from_fast(
                answer,
                user_id=str(user),
                lane="fast",
                visitor_class=visitor_class,
                question=question,
                as_of=as_of,
                library_ref=snaps[0].ref if snaps else "",
                consultation_id=_uuid.uuid4().hex,
                created_at=datetime.now(timezone.utc),
            ),
        )

    return record


async def _run(args: argparse.Namespace, component_tools, parser_for) -> int:
    """One context for the whole process, whichever family the command belongs to."""
    from ..engine.contract import bootstrap_engine
    from ..settings import get_settings
    from ..wiring import build_context
    from .isolation import isolation_refusal, project_isolation_problems

    settings = get_settings()
    # Which library is this? `app.py` has always refused to connect when its settings drifted
    # off the ports the generator probed for this project; `pkc` is the command an agent
    # actually runs, so it refuses on the same terms. Before `bootstrap_engine`, before any
    # connection: a cross-library read is not better than a cross-library write.
    problems = project_isolation_problems(settings)
    if problems:
        print(isolation_refusal(problems), file=sys.stderr)
        return draft_cmd.EXIT_REFUSED
    if args.group == "config":
        return config_cmd.cmd_config_set(
            settings, args.key, args.value, as_json=getattr(args, "as_json", False)
        )
    # This project's wording and contract, for a process that has no application to import.
    # `pkc` is the framework's own entry point run against a project (the shim hands off to
    # it), so nothing else in this process would have registered either — and a round rendered
    # under different words from the skill the agent reads would be two renderings of one
    # deployment. Both halves no-op when something already registered them (`pkc skill`
    # resolves its own deployment the same way).
    bootstrap_engine(settings)
    if args.group == "skill":
        # Deliberately BEFORE `build_context`: the skill package is a rendering of the engine
        # — contract, wording, components, command tree — and none of that lives in a
        # database. Installing into a project that has never been started is the whole point
        # (`scaffold/init.py` calls exactly this), so a middleware connection here would make
        # generation depend on a running stack.
        return await skill_cmd.dispatch_skill(
            settings, args, user=resolve_tenant(args.user), parser_for=parser_for
        )
    # `probe_agent=False`: a `pkc` process never launches a harness — it IS the harness's
    # hand. Probing one here would cost seconds on every command and, inside a session of
    # that very harness, would start it from within itself. The worker, which does launch,
    # probes at startup (`wiring.probe_compile_executor`).
    ctx = await build_context(settings, probe_agent=False, probe_embedding=False)
    try:
        if args.group == "draft":
            from .runtime import build_runtime

            rt = await build_runtime(ctx, UserId(resolve_tenant(args.user)))
            return await _draft_command(rt, args, component_tools)
        return await dispatch(ctx, args)
    except draft_cmd.TextArgError as exc:
        # A `--text-file` / `--body-file` / `--json-file` that names nothing readable is a
        # refusal at the argument face, in the shape §5.2 gives every other one: one line on
        # stderr and exit 2, never a traceback the Steward has to interpret.
        print(f"error: {exc}", file=sys.stderr)
        return draft_cmd.EXIT_REFUSED
    except CanonicalDirtyError as exc:
        # The library holds uncommitted changes this framework did not make, and the canonical
        # adapter refused before writing anything. HERE and not at each command, for the same
        # reason `api/app.py` handles it in one place: the ADAPTER raises it, so every door
        # that commits — `draft finish`, `draft abandon`, `owner say`, `ingest`, an archive
        # confirm's job on the queue — reaches it, including doors written later. `exc.detail`
        # is the machine form the job rows carry (`canonical_dirty:<paths>`) and the message
        # opens with it, so a Steward and a job completion name the same paths; exit 2 is
        # §5.2's refusal, and a traceback would be neither.
        print(f"refused: {exc}", file=sys.stderr)
        return draft_cmd.EXIT_REFUSED
    finally:
        await ctx.aclose()


def main(argv: list[str] | None = None) -> int:
    """Process entry point (`pkc`). Returns the exit code; `sys.exit` is the caller's."""
    # Components are registered by the runtime the commands run under, but the PARSER needs
    # their tool names before a command runs. `build_context` is where registration happens,
    # so the parser is built after settings say which components are enabled.
    from ..settings import get_settings
    from ..wiring import register_components

    settings = get_settings()
    try:
        register_components(settings, store=None, canonical=None)
        component_tools = draft_cmd.component_tool_specs()
    except Exception:  # noqa: BLE001 — a component that cannot declare its tools must not
        # take the whole CLI down; its subcommands are then simply absent and every framework
        # command still works.
        component_tools = ()
    parser = build_parser(component_tools)
    args = parser.parse_args(argv)
    # The parser is handed on as a THUNK rather than as a value: `pkc skill` renders the
    # command reference out of this very tree, and passing the object the process is running
    # under is what makes the reference describe the deployment instead of a reconstruction
    # of it.
    return asyncio.run(_run(args, component_tools, lambda: parser))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
