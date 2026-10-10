"""The personal library's CLI entry, registering the same application faces as its engine."""

from __future__ import annotations

import argparse
import json
import os

from pneuma_knowledge_core.components import register_component
from pneuma_knowledge_service.coding_agent.install import SKILL_HASH_ENV

from pkc_personal.environment import home_environment
from pkc_personal.home import Home
from pkc_personal.library import Library
from pkc_personal.project_component import ProjectComponent


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", required=True)
    parser.add_argument("--library", required=True)
    parser.add_argument("argv", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    home = Home(args.home)
    library = Library.load(home, args.library)
    env = home_environment(home, library)
    env["PKC_HOME"] = str(home.path)
    env["PKC_LIBRARY"] = library.state.name
    version = library.skill_dir.parent / "skill-version.json"
    if version.exists():
        env.setdefault(SKILL_HASH_ENV, str(json.loads(version.read_text())["sha256"]))
    os.environ.update(env)
    os.chdir(library.path)
    register_component(ProjectComponent(library))
    from pneuma_knowledge_service.cli import main as pkc_main
    remaining = args.argv[1:] if args.argv[:1] == ["--"] else args.argv
    return pkc_main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
