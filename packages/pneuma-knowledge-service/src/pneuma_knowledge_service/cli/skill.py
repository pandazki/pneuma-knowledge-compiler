"""`pkc skill` — render this deployment's Steward skill, install it, check it is still fresh.

Three commands over one rendering (§7):

    pkc skill install [--backend codex|claude-code|all] [--project <dir>]
    pkc skill verify  [--backend …] [--project <dir>]     exit 4 listing drift, 0 when fresh
    pkc skill show    [--backend …] [--project <dir>]     the hash and the file list
    pkc skill probe   [--backend …] [--deadline <s>]      is the harness live? exit 4 if not

What makes this an honest freshness gate is that `verify` re-renders from the same inputs
`install` rendered from and compares bytes. So there is exactly one place those inputs are
resolved — `coding_agent.deployment.resolve_deployment` — and every caller goes through it,
the engine's own apply hook included.

Deliberately DATABASE-FREE. The package is a rendering of the engine — the contract, the
wording, the language, the components, the command tree — and none of those live in Postgres.
That is what lets `scaffold/init.py` install a skill into a project that has never been
started, through the framework's own entry point rather than through a second renderer inside
the generator.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from ..coding_agent.backends import BACKENDS, backend as backend_manifest
from ..coding_agent.probe import DEFAULT_DEADLINE_S, probe
from ..coding_agent.install import install_skill_package, verify_skill_package
from ..coding_agent.deployment import (
    SkillRenderError,
    backend_names,
    packages,
    resolve_deployment,
)
from .draft import EXIT_GATE, EXIT_NOTHING, EXIT_OK

#: `pkc draft finish` exits 4 when the gate rejected the draft; `pkc skill verify` exits 4
#: when the installed package is not what the catalog renders today. Same code, same meaning
#: to a script: "a mechanical check found something and the text says what".
EXIT_DRIFT = EXIT_GATE


def add_skill_commands(top) -> None:  # noqa: ANN001
    """`pkc skill …`, registered from the one place the tree is assembled."""
    skill = top.add_parser(
        "skill",
        help="the Steward skill a coding agent reads: render it, install it, check it",
        description=(
            "The skill package is generated from this deployment's own contract, wording, "
            "components and command tree — never written by hand. `install` puts it in a "
            "project; `verify` exits 4 when what is installed is no longer what those inputs "
            "render."
        ),
    )
    sub = skill.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("install", "render the package and write it into a project"),
        ("verify", "re-render and list what drifted; exit 4 when anything did"),
        ("show", "the package's hash and file list, without touching a project"),
        (
            "probe",
            "is the harness installed and logged in? liveness, never a version — exit 4 "
            "when it is not usable",
        ),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--backend",
            default="codex",
            choices=(*sorted(BACKENDS), "all"),
            help="which harness's layout to use; `all` does every shipped one",
        )
        if name == "probe":
            p.add_argument(
                "--deadline",
                type=float,
                default=DEFAULT_DEADLINE_S,
                help=(
                    "seconds the liveness command gets before its process group is reaped; "
                    "an unfinished login looks exactly like a hang"
                ),
            )
        if name != "probe":
            # `show` takes it too, and reads nothing: the project decides which path the
            # rendered SKILL.md names as `pkc`, so a `show` that ignored it would print a
            # different hash than the `install` beside it (`deployment.packages`).
            p.add_argument(
                "--project",
                default=".",
                help="the project directory to act on; the current directory by default",
            )
        p.add_argument(
            "--json",
            dest="as_json",
            action="store_true",
            help="machine-readable output; the default is the same state as prose",
        )


# ───────────────────────────────────────────────────────────────────────────── the commands


async def cmd_skill_install(
    settings,  # noqa: ANN001
    *,
    user: str,
    project: str,
    choice: str,
    parser_for,  # noqa: ANN001
    as_json: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    deployment = await resolve_deployment(settings, user=user, parser_for=parser_for)
    report = []
    for manifest, package in packages(deployment, backend_names(choice), project=project):
        written = install_skill_package(
            project, manifest, package, deployment.framework_version
        )
        report.append(
            {
                "backend": manifest.name,
                "sha256": package.sha256,
                "files": written,
                # What the Owner types in this directory. On the report because the caller
                # that most needs it is a generator with no framework import
                # (`scaffold/init.py`), and a second copy of these flags anywhere else is
                # the one thing the manifest exists to prevent.
                "session_command": manifest.owner_session_command,
                "exec_command": manifest.owner_exec_command,
            }
        )
    if as_json:
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK
    for entry in report:
        out.write(f"{entry['backend']}: {entry['sha256']}\n")
        for path in entry["files"]:
            out.write(f"  {path}\n")
    return EXIT_OK


async def cmd_skill_verify(
    settings,  # noqa: ANN001
    *,
    user: str,
    project: str,
    choice: str,
    parser_for,  # noqa: ANN001
    as_json: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    deployment = await resolve_deployment(settings, user=user, parser_for=parser_for)
    report = []
    drifted = False
    for manifest, package in packages(deployment, backend_names(choice), project=project):
        drift = verify_skill_package(project, manifest, package)
        drifted = drifted or bool(drift)
        report.append({"backend": manifest.name, "sha256": package.sha256, "drift": drift})
    if as_json:
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return EXIT_DRIFT if drifted else EXIT_OK
    for entry in report:
        if not entry["drift"]:
            out.write(f"{entry['backend']}: fresh ({entry['sha256']})\n")
            continue
        err.write(
            f"{entry['backend']}: the installed skill is not what this deployment renders "
            f"today ({entry['sha256']}). Run `pkc skill install` to bring it back:\n"
        )
        for path in entry["drift"]:
            err.write(f"  {path}\n")
    return EXIT_DRIFT if drifted else EXIT_OK


async def cmd_skill_show(
    settings,  # noqa: ANN001
    *,
    user: str,
    project: str,
    choice: str,
    parser_for,  # noqa: ANN001
    as_json: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    deployment = await resolve_deployment(settings, user=user, parser_for=parser_for)
    report = [
        {
            "backend": manifest.name,
            "sha256": package.sha256,
            "language": package.language,
            "contract": f"{deployment.skill.skill_id}@{deployment.skill.version}",
            "components": [getattr(c, "name", "") for c in deployment.components],
            "files": sorted(package.files),
        }
        for manifest, package in packages(deployment, backend_names(choice), project=project)
    ]
    if as_json:
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK
    for entry in report:
        out.write(
            f"{entry['backend']}: {entry['sha256']}\n"
            f"  contract: {entry['contract']}   language: {entry['language']}\n"
        )
        if entry["components"]:
            out.write(f"  components: {', '.join(entry['components'])}\n")
        for path in entry["files"]:
            out.write(f"  {path}\n")
    return EXIT_OK


async def cmd_skill_probe(
    *,
    choice: str,
    deadline: float,
    as_json: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    """Run each named harness's liveness command and report what it found.

    Deliberately free of `resolve_deployment`: whether Codex is logged in has nothing to do
    with this library's contract, and asking the question must not require a renderable
    deployment. Exit 4 when any probed harness is unusable — the same code `verify` uses for
    "a mechanical check found something and the text says what".
    """
    report = []
    for name in backend_names(choice):
        result = await probe(backend_manifest(name), deadline_s=deadline)
        report.append(
            {
                "backend": result.backend,
                "ok": result.ok,
                "reason": result.reason,
                "binary_path": result.binary_path,
            }
        )
    if as_json:
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    else:
        for entry in report:
            stream = out if entry["ok"] else err
            where = f" ({entry['binary_path']})" if entry["binary_path"] else ""
            stream.write(
                f"{entry['backend']}: {'live' if entry['ok'] else 'unusable'}{where} — "
                f"{entry['reason']}\n"
            )
    return EXIT_OK if all(entry["ok"] for entry in report) else EXIT_DRIFT


async def dispatch_skill(
    settings,  # noqa: ANN001
    args: argparse.Namespace,
    *,
    user: str,
    parser_for,  # noqa: ANN001
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    as_json = bool(getattr(args, "as_json", False))
    try:
        return await _dispatch(
            settings, args, user=user, parser_for=parser_for, as_json=as_json, out=out, err=err
        )
    except SkillRenderError as exc:
        err.write(f"{exc}\n")
        return EXIT_NOTHING


async def _dispatch(
    settings,  # noqa: ANN001
    args: argparse.Namespace,
    *,
    user: str,
    parser_for,  # noqa: ANN001
    as_json: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    if args.command == "install":
        return await cmd_skill_install(
            settings,
            user=user,
            project=args.project,
            choice=args.backend,
            parser_for=parser_for,
            as_json=as_json,
            out=out,
            err=err,
        )
    if args.command == "verify":
        return await cmd_skill_verify(
            settings,
            user=user,
            project=args.project,
            choice=args.backend,
            parser_for=parser_for,
            as_json=as_json,
            out=out,
            err=err,
        )
    if args.command == "probe":
        return await cmd_skill_probe(
            choice=args.backend,
            deadline=args.deadline,
            as_json=as_json,
            out=out,
            err=err,
        )
    if args.command == "show":
        return await cmd_skill_show(
            settings,
            user=user,
            project=args.project,
            choice=args.backend,
            parser_for=parser_for,
            as_json=as_json,
            out=out,
            err=err,
        )
    err.write(f"unknown skill command: {args.command}\n")
    return EXIT_NOTHING
