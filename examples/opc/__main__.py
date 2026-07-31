"""Command dispatcher for the self-contained OPC example."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable


def _commands() -> dict[str, Callable[[], int]]:
    from .evaluate import main as evaluate
    from .run import main as run
    from .seed import main as seed

    return {
        "seed": seed,
        "run": run,
        "evaluate": evaluate,
    }


def main() -> int:
    commands = _commands()
    if len(sys.argv) > 1 and sys.argv[1] in commands:
        command_name = sys.argv[1]
        sys.argv = [f"python -m examples.opc {command_name}", *sys.argv[2:]]
        return commands[command_name]()

    parser = argparse.ArgumentParser(
        prog="python -m examples.opc",
        description="Fictional OPC demo and 84-day experiment environment.",
    )
    parser.add_argument("command", nargs="?", choices=tuple(commands))
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 0
    return commands[args.command]()


if __name__ == "__main__":
    raise SystemExit(main())
