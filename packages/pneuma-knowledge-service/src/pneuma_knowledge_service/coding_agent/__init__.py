"""Coding agent mode: the skill package a coding-agent Steward is installed with.

`docs/design/coding-agent-mode.md` §7 and §8. Three modules, one direction:

    backends.py       what a harness IS (data: layout, probe, launch shape; nothing else
                      branches on a name)
    skillpack.py      the catalog + the live CLI parser + the gate → a set of bytes
    install.py        those bytes onto disk, and the check that what is on disk is still them
    deployment.py     what THIS deployment renders from, resolved once for every caller
    probe.py          is a harness installed AND logged in — liveness, never a version
    harness_output.py what a finished harness said it spent, per backend
    launcher.py       one harness process run as a round: timeout, backoff, reaping, usage
    round_runner.py   one compile job unattended: open the draft, launch, read it back

`round_runner` is deliberately NOT re-exported here: it is the only module in the package
that reaches back into `cli/`, and importing it eagerly would make every consumer of a
backend manifest pull the whole command tree. The worker imports it where it uses it.

Ruling 4 is the whole design: the skill is a RENDERING, not a second text. Every sentence in
it comes from the prompt catalog, every command in it from the argparse tree that answers
`pkc`, every refusal in it from the gate's own strings. Nothing is written twice, so nothing
can drift.
"""

from __future__ import annotations

from .backends import BACKENDS, BLOCK_END, BLOCK_START, SKILL_NAME, BackendManifest, backend
from .deployment import refresh_skill_installs, resolve_deployment
from .install import install_skill_package, verify_skill_package
from .launcher import LaunchRequest, LaunchResult, launch_round
from .probe import ProbeResult, probe
from .skillpack import SkillPackage, render_skill_package

__all__ = [
    "BACKENDS",
    "BLOCK_END",
    "BLOCK_START",
    "SKILL_NAME",
    "BackendManifest",
    "LaunchRequest",
    "LaunchResult",
    "ProbeResult",
    "SkillPackage",
    "backend",
    "launch_round",
    "probe",
    "install_skill_package",
    "refresh_skill_installs",
    "resolve_deployment",
    "render_skill_package",
    "verify_skill_package",
]
