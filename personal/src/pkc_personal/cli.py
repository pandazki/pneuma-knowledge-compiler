"""pkchome: machine setup and library selection around the library's own pkc."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import shlex
import subprocess
import sys
import webbrowser

from pneuma_knowledge_service.coding_agent.install import SKILL_HASH_ENV, SkillWriteRefused

from pkc_personal import infra, setup, skill_install, status, sync
from pkc_personal.environment import LibraryNotChosen, home_environment, resolve_library
from pkc_personal.home import Choices, Home, KEY_PATTERN
from pkc_personal.library import (
    bind_library, create_library, libraries, pkc_script, render_library, set_config,
    unbind_library, use_library,
    watch_project,
)


def _library_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--library", default=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pkchome", description=__doc__)
    _library_flag(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup")
    p.add_argument("--answers")
    p.add_argument("--non-interactive", action="store_true")
    p.add_argument("--no-skill", action="store_true")
    for verb in ("up", "down", "restart", "console", "tray"):
        p = sub.add_parser(verb)
        _library_flag(p)
    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")
    _library_flag(p)
    p = sub.add_parser("sync")
    _library_flag(p)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--rewritten", choices=("report", "reingest"), default="report")
    p = sub.add_parser("watch")
    _library_flag(p)
    commands = p.add_subparsers(dest="action", required=True)
    for verb in ("add", "ls", "rm"):
        p = commands.add_parser(verb)
        _library_flag(p)
        if verb != "ls":
            p.add_argument("directory")
        if verb == "add":
            p.add_argument("--harnesses", nargs="+", choices=("claude-code", "codex"))
            p.add_argument("--since")
    p = sub.add_parser("env")
    p.add_argument("--export", action="store_true")
    _library_flag(p)
    p = sub.add_parser("exec")
    _library_flag(p)
    p.add_argument("argv", nargs=argparse.REMAINDER)
    p = sub.add_parser("library")
    commands = p.add_subparsers(dest="action", required=True)
    p = commands.add_parser("create")
    p.add_argument("name")
    p.add_argument("--from", dest="from_library")
    p.add_argument("--language", choices=("en", "zh"))
    p.add_argument("--contract", help="personal-projects (default), personal-knowledge, or a contract path")
    p.add_argument("--backend", choices=("codex", "claude-code", "api"))
    commands.add_parser("ls")
    for verb in ("show", "render"):
        p = commands.add_parser(verb)
        p.add_argument("name", nargs="?")
    p = commands.add_parser("use")
    p.add_argument("name")
    p = commands.add_parser("bind")
    p.add_argument("name")
    p.add_argument("directory", nargs="?", default=".")
    p = commands.add_parser("unbind")
    p.add_argument("directory", nargs="?", default=".")
    p = sub.add_parser("config")
    commands = p.add_subparsers(dest="action", required=True)
    for verb in ("get", "set"):
        p = commands.add_parser(verb)
        p.add_argument("key", choices=(*Choices.model_fields, "sync.interval_minutes", "sync.enabled"))
        if verb == "set":
            p.add_argument("value")
        _library_flag(p)
    p = sub.add_parser("credentials")
    commands = p.add_subparsers(dest="action", required=True)
    p = commands.add_parser("set")
    p.add_argument("key")
    p.add_argument("--from-stdin", action="store_true")
    p = sub.add_parser("skill")
    commands = p.add_subparsers(dest="action", required=True)
    p = commands.add_parser("install")
    p.add_argument("--backend", choices=("codex", "claude-code", "all"))
    p.add_argument("--force", action="store_true")
    for verb in ("register", "forget"):
        p = sub.add_parser(verb)
        p.add_argument("directory")
    return parser


def _exec(home: Home, explicit: str | None, argv: list[str]) -> None:
    library = resolve_library(home, explicit)
    argv = argv[1:] if argv and argv[0] == "--" else argv
    if not argv:
        raise ValueError("exec needs -- <command> [args...]")
    library.touch_last_used()
    env = home_environment(home, library)
    if argv[0] == "pkc":
        argv = [pkc_script(), *argv[1:]]
        # The library's installer writes the version record beside the skill directory
        # (`<project>/<skills_dir>/skill-version.json`), not inside the package.
        version = library.skill_dir.parent / "skill-version.json"
        if version.is_file():
            recorded = json.loads(version.read_text(encoding="utf-8"))
            env.setdefault(SKILL_HASH_ENV, str(recorded["sha256"]))
    os.execvpe(argv[0], argv, env)


def _dispatch(args: argparse.Namespace, home: Home) -> None:
    explicit = getattr(args, "library", None)
    if args.command == "setup":
        setup.setup(home, args.answers, no_skill=args.no_skill, non_interactive=args.non_interactive)
    elif args.command in {"up", "down", "restart"}:
        if args.command in {"down", "restart"}:
            infra.down(home)
        if args.command in {"up", "restart"}:
            infra.up(home)
    elif args.command == "status":
        document = status.status_document(home, explicit)
        print(json.dumps(document, ensure_ascii=False, indent=2) if args.json else status.render_text(document))
    elif args.command == "sync":
        report = sync.run(home, resolve_library(home, explicit), dry_run=args.dry_run, rewritten=args.rewritten)
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else sync.converter().render_sync(report))
        if any(row["status"] == "error" for row in report["sessions"]):
            raise RuntimeError("sync had errors; failed parts remain retryable")
    elif args.command == "watch":
        library = resolve_library(home, explicit)
        if args.action == "ls":
            print(json.dumps([item.model_dump() for item in library.state.watch], ensure_ascii=False, indent=2))
        else:
            watch_project(library, args.directory, remove=args.action == "rm",
                          harnesses=getattr(args, "harnesses", None), since=getattr(args, "since", None))
    elif args.command == "exec":
        _exec(home, explicit, args.argv)
    elif args.command == "env":
        env = home_environment(home, resolve_library(home, explicit))
        for key, value in sorted(env.items()):
            print(f"{'export ' if args.export else ''}{key}={shlex.quote(value)}")
    elif args.command == "library":
        if args.action == "create":
            library = create_library(home, args.name, from_library=args.from_library,
                                     language=args.language, contract=args.contract, backend=args.backend)
            print(json.dumps(library.show(), ensure_ascii=False, indent=2))
        elif args.action == "ls":
            for library in libraries(home):
                print(f"{library.state.name}{' (current)' if home.current == library.state.name else ''}")
        elif args.action == "use":
            use_library(home, args.name)
        elif args.action == "bind":
            bind_library(home, args.name, args.directory)
        elif args.action == "unbind":
            unbind_library(home, args.directory)
        else:
            library = resolve_library(home, args.name or explicit)
            if args.action == "render":
                render_library(home, library)
            print(json.dumps(library.show(), ensure_ascii=False, indent=2))
    elif args.command == "config":
        library = resolve_library(home, explicit) if explicit is not None else None
        if args.action == "set":
            note = set_config(home, args.key, args.value, library)
            if note:
                print(note)
        else:
            if args.key.startswith("sync."):
                if library:
                    raise ValueError("sync settings belong to the home; omit --library")
                value = getattr(home.config.sync, args.key.split(".")[1])
            else:
                value = getattr(library.state.choices if library else home.config.defaults, args.key)
            print("on" if value is True else "off" if value is False else value)
    elif args.command == "credentials":
        if not KEY_PATTERN.fullmatch(args.key):
            raise ValueError("credential name must match [A-Z][A-Z0-9_]*")
        value = sys.stdin.read().rstrip("\r\n") if args.from_stdin or not sys.stdin.isatty() else getpass.getpass(f"{args.key}: ")
        home.set_credential(args.key, value)
        print(f"stored {args.key} ({len(value)} chars)")
    elif args.command == "skill":
        paths = skill_install.install(home, args.backend, force=args.force)
        print("\n".join(str(path) for path in paths) if paths else "No harness directories found; use --backend to choose one.")
    elif args.command == "console":
        library = resolve_library(home, explicit)
        webbrowser.open(f"http://127.0.0.1:{library.state.engine.port}")
    elif args.command == "tray":
        from pathlib import Path

        candidates = (Path.home() / "Applications" / "PKC.app", Path("/Applications/PKC.app"))
        application = next((path for path in candidates if path.is_dir()), None)
        if sys.platform == "darwin" and application is not None:
            subprocess.run(["open", str(application)], check=True)
        else:
            print("Get PKC desktop: https://github.com/pandazki/pneuma-knowledge-compiler/releases")
    elif args.command in {"register", "forget"}:
        print(f"{args.command}: v2")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _dispatch(args, Home())
        return 0
    except (LibraryNotChosen, SkillWriteRefused, ValueError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        # Captured subprocess output may contain connection secrets; never echo it.
        print(f"command failed (exit {exc.returncode}): {exc.cmd[0]}", file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
