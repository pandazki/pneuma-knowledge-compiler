"""`pkc skill` — render this deployment's Steward skill, install it, check it is still fresh.

Five commands over one rendering (§7):

    pkc skill install [--backend codex|claude-code|all] [--project <dir>]
    pkc skill render  --out <dir> [--backend …] [--language en|zh] [--force]
    pkc skill verify  [--backend …] [--project <dir> | --dir <dir>]
                                                         exit 4 listing drift, 0 when fresh
    pkc skill show    [--backend …] [--project <dir>]     the hash and the file list
    pkc skill probe   [--backend …] [--deadline <s>]      is the harness live? exit 4 if not

`render` is `install` without the install: the same deployment, resolved by the same
function, rendered into the same bytes, written to a directory of the caller's naming with
no project entered and no instructions file touched — for an application that wants the
package as files (a reference copy, a diff, a package shipped elsewhere), and the hash it
prints is the hash `install` would have stamped — which is the whole reason it is this
command and not a second renderer.

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
from pathlib import Path
from typing import TextIO

from pneuma_knowledge_core.prompts import prompt

from ..coding_agent.backends import BACKENDS, backend as backend_manifest
from ..coding_agent.probe import DEFAULT_DEADLINE_S, probe
from ..coding_agent.install import (
    SkillWriteRefused,
    install_skill_package,
    verify_rendered_package,
    verify_skill_package,
    write_skill_package,
)
from ..coding_agent.deployment import (
    SkillRenderError,
    backend_names,
    packages,
    resolve_deployment,
)
from ..engine.prompts import prompt_languages
from .draft import EXIT_GATE, EXIT_NOTHING, EXIT_OK, EXIT_REFUSED

#: `pkc draft finish` exits 4 when the gate rejected the draft; `pkc skill verify` exits 4
#: when the installed package is not what the catalog renders today. Same code, same meaning
#: to a script: "a mechanical check found something and the text says what".
EXIT_DRIFT = EXIT_GATE


def add_skill_commands(top) -> None:  # noqa: ANN001
    """`pkc skill …`, registered from the one place the tree is assembled."""
    skill = top.add_parser(
        "skill",
        help=prompt("steward.cli.skill"),
        description=prompt("steward.cli.skill_description"),
    )
    sub = skill.add_subparsers(dest="command", required=True)

    for name, help_text in (
        ("install", prompt("steward.cli.skill_install")),
        (
            "render",
            prompt("steward.cli.skill_render"),
        ),
        ("verify", prompt("steward.cli.skill_verify")),
        ("show", prompt("steward.cli.skill_show")),
        (
            "probe",
            prompt("steward.cli.skill_probe"),
        ),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--backend",
            # The same default `install` carries, deliberately: the two commands render the
            # same package for the same deployment, and a default that disagreed would make
            # `render --out` and the install beside it two different sets of bytes.
            default="codex",
            # `all` writes several layouts, which one directory cannot hold: `render` names
            # one harness or none.
            choices=sorted(BACKENDS) if name == "render" else (*sorted(BACKENDS), "all"),
            help=(
                prompt("steward.cli.render_backend")
                if name == "render"
                else prompt("steward.cli.backend")
            ),
        )
        if name == "probe":
            p.add_argument(
                "--deadline",
                type=float,
                default=DEFAULT_DEADLINE_S,
                help=prompt("steward.cli.deadline"),
            )
        if name == "render":
            p.add_argument(
                "--out",
                required=True,
                help=prompt("steward.cli.out"),
            )
            p.add_argument(
                "--language",
                default="",
                # Read off the engine's own prompt-language knob, never retyped here: the
                # choice this command offers and the choice an apply accepts are one list.
                choices=("", *prompt_languages()),
                help=prompt("steward.cli.language"),
            )
            p.add_argument(
                "--force",
                action="store_true",
                help=prompt("steward.cli.force"),
            )
        elif name != "probe":
            # `show` takes it too, and reads nothing: the project decides which path the
            # rendered SKILL.md names as `pkc`, so a `show` that ignored it would print a
            # different hash than the `install` beside it (`deployment.packages`).
            p.add_argument(
                "--project",
                default=".",
                help=prompt("steward.cli.project"),
            )
        if name == "verify":
            p.add_argument(
                "--dir",
                dest="directory",
                default="",
                help=prompt("steward.cli.verify_dir"),
            )
        p.add_argument(
            "--json",
            dest="as_json",
            action="store_true",
            help=prompt("steward.cli.json"),
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


async def cmd_skill_render(
    settings,  # noqa: ANN001
    *,
    user: str,
    out_dir: str,
    choice: str,
    language: str,
    force: bool,
    parser_for,  # noqa: ANN001
    as_json: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    """`install`'s rendering, written to a directory and installed nowhere.

    The deployment is resolved by the same function `install` resolves it with and the
    package is rendered by the same call, so the hash printed here is the hash `install`
    would have stamped for this backend. The one input that differs is the ENTRY: there is
    no project, so `SKILL.md` names the package's own `scripts/pkc` — which is what
    `packages(…)` renders when it is handed no project, and the reason this command does not
    take `--project` at all.
    """
    deployment = await resolve_deployment(
        settings, user=user, parser_for=parser_for, language=language or None
    )
    ((manifest, package),) = packages(deployment, [choice])
    written = write_skill_package(
        out_dir, manifest, package, deployment.framework_version, force=force
    )
    directory = str(Path(out_dir).expanduser().absolute())
    report = {
        "backend": manifest.name,
        "sha256": package.sha256,
        "language": package.language,
        "out": directory,
        "files": written,
        # The same two lines `install` reports, for the same reason: a caller assembling an
        # environment around this package must not restate the manifest's flags.
        "session_command": manifest.owner_session_command,
        "exec_command": manifest.owner_exec_command,
    }
    if as_json:
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return EXIT_OK
    out.write(
        f"{manifest.name}: {package.sha256}\n"
        f"  {len(written)} files under {directory} (language: {package.language})\n"
    )
    return EXIT_OK


async def cmd_skill_verify(
    settings,  # noqa: ANN001
    *,
    user: str,
    project: str,
    directory: str,
    choice: str,
    parser_for,  # noqa: ANN001
    as_json: bool,
    out: TextIO,
    err: TextIO,
) -> int:
    """Re-render, compare bytes, and name every path where the two disagree.

    `--dir` asks the same question of a directory `pkc skill render --out` wrote: the same
    deployment, the same rendering, and drift reported the same way. What it cannot ask
    about is the router block — nothing was installed, so there is no instructions file for
    one to be missing from — and the package is rendered with no project, exactly as
    `render` rendered it.
    """
    deployment = await resolve_deployment(settings, user=user, parser_for=parser_for)
    report = []
    drifted = False
    rendered = bool(directory)
    where = directory if rendered else project
    if rendered and choice == "all":
        err.write(
            "error: --dir names one directory and `--backend all` renders several layouts "
            "into it. Verify one backend at a time.\n"
        )
        return EXIT_REFUSED
    for manifest, package in packages(
        deployment, backend_names(choice), project=None if rendered else project
    ):
        drift = (
            verify_rendered_package(directory, manifest, package)
            if rendered
            else verify_skill_package(project, manifest, package)
        )
        drifted = drifted or bool(drift)
        report.append(
            {
                "backend": manifest.name,
                "sha256": package.sha256,
                "where": where,
                "drift": drift,
            }
        )
    if as_json:
        out.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        return EXIT_DRIFT if drifted else EXIT_OK
    for entry in report:
        if not entry["drift"]:
            out.write(f"{entry['backend']}: fresh ({entry['sha256']})\n")
            continue
        err.write(
            f"{entry['backend']}: the skill in {entry['where']} is not what this deployment "
            f"renders today ({entry['sha256']}). Run "
            f"`pkc skill {'render --out <dir> --force' if rendered else 'install'}` to "
            "bring it back:\n"
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
    except SkillWriteRefused as exc:
        # A directory somebody else's files are in. Refused at the face, before a byte is
        # written, and reported as the one sentence that names the way past it.
        err.write(f"error: {exc}\n")
        return EXIT_REFUSED


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
    if args.command == "render":
        return await cmd_skill_render(
            settings,
            user=user,
            out_dir=args.out,
            choice=args.backend,
            language=args.language,
            force=args.force,
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
            directory=args.directory,
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
