"""What this deployment renders a skill package FROM, resolved once.

`install`, `verify`, `show` and the engine's own apply hook must all render from identical
inputs — otherwise the freshness check reports drift that is really just two callers
disagreeing about which contract, which wording, which components. So there is one function
that answers "what is this deployment", and every caller goes through it.

Deliberately DATABASE-FREE. A package is a rendering of the engine — contract, wording,
language, components, command tree — and none of that lives in Postgres. That is what lets
`scaffold/init.py` install a skill into a project that has never been started, through the
framework's own entry point rather than through a second renderer inside the generator.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.time_context import TimeContext
from pneuma_knowledge_core.skill.version import SkillVersion

from .backends import BACKENDS, BackendManifest, backend as backend_manifest
from .install import VERSION_FILE, install_skill_package
from .skillpack import SkillPackage, project_entry, render_skill_package

_log = logging.getLogger(__name__)


class SkillRenderError(RuntimeError):
    """A deployment that cannot be rendered — reported as one sentence, never a traceback."""


@dataclass(frozen=True)
class Deployment:
    """The inputs a package is rendered from, resolved once."""

    skill: SkillVersion
    owner: object | None
    time: TimeContext | None
    components: tuple[Any, ...]
    parser: argparse.ArgumentParser
    language: str
    framework_version: str
    user_id: UserId


#: A fixed instant for the TimeContext handed to the contract renderer. `render_system_contract`
#: reads a TimeContext's ZONE and that zone's provenance and never its instant (invariant I5),
#: so pinning it is not a lie about time — it is the mechanism that keeps two renderings of
#: the same deployment byte-identical.
_PINNED_INSTANT = datetime(2000, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class _Workspace:
    operating_mode: str
    primary_stack: str


@dataclass(frozen=True)
class _Locale:
    city: str
    country: str
    timezone: str
    language: str


@dataclass(frozen=True)
class _EngineOwner:
    """The owner as the engine's `persona/profile.yaml` states them.

    Duck-typed against exactly the attributes `render_system_contract` reads, and filled from
    the same file and with the same rules the generated `app.py` persists a `UserProfile`
    from — so the contract this renders is the contract a compile round renders, whether or
    not anything has been written to the database yet.
    """

    display_name: str
    occupation: str
    bio: str
    interests: tuple[str, ...]
    industry: str
    role: str
    locale: _Locale
    workspace: _Workspace


def owner_from_engine(engine_dir: str) -> tuple[_EngineOwner | None, str, str]:
    """`(owner, zone, zone_source)` from the engine's persona file, or `(None, "", "")`.

    A timezone the subject has not confirmed is NOT presented as theirs: `app.py` drops it
    from the profile and lets the deployment default declare itself, and that branch is
    reproduced here rather than approximated, because which of the two lines the contract
    carries is a statement about evidence.
    """
    if not (engine_dir or "").strip():
        return None, "", ""
    from ..engine.files import EngineFileError, read_mapping

    try:
        profile = read_mapping(engine_dir, "persona/profile.yaml")
    except (EngineFileError, OSError):
        return None, "", ""
    if not profile:
        return None, "", ""
    locale = dict(profile.get("locale") or {})
    provenance = dict(profile.get("provenance") or {})
    zone = str(locale.get("timezone") or "").strip()
    stated = str(provenance.get("timezone") or "") == "profile"
    owner = _EngineOwner(
        display_name=str(profile.get("display_name") or "Owner").strip() or "Owner",
        occupation=str(profile.get("occupation") or ""),
        bio=str(profile.get("bio") or ""),
        interests=tuple(str(x) for x in (profile.get("interests") or [])),
        industry=str(profile.get("industry") or "other"),
        role=str(profile.get("role") or "other"),
        locale=_Locale(
            city=str(locale.get("city") or "").strip(),
            country=str(locale.get("country") or "").strip(),
            timezone=zone if stated else "",
            language=str(locale.get("language") or "").strip(),
        ),
        workspace=_Workspace(operating_mode="independent", primary_stack=""),
    )
    return owner, (zone if stated else ""), ("profile" if stated else "")


async def resolve_deployment(settings, *, user: str, parser_for) -> Deployment:  # noqa: ANN001
    """Everything a rendering needs, from settings alone — no database, no model."""
    from importlib.metadata import PackageNotFoundError, version as package_version

    from pneuma_knowledge_core.components import registered_components
    from pneuma_knowledge_core.skill import load_skill_base

    from ..engine.contract import CONTRACT_FILE, register_engine_contract
    from ..engine.prompts import active_language, apply_prompt_stack
    from ..skills import composed_skill_readonly
    from ..wiring import register_components

    engine_dir = (settings.engine_dir or "").strip()
    language = "en"
    if engine_dir:
        from ..engine.files import EngineFileError, read_mapping
        from ..engine.prompts import overlays_file

        language = active_language(engine_dir)
        try:
            from ..engine.files import parse_overlays

            overlays = parse_overlays(
                overlays_file(), read_mapping(engine_dir, overlays_file())
            )
        except (EngineFileError, OSError):
            overlays = {}
        apply_prompt_stack(language, overlays)

    # The contract. A deployment that already registered one (a process that imported its
    # application) keeps it; otherwise the engine directory's own `compile/contract.md` is
    # the contract, which is what makes this command runnable from the framework against a
    # project that has never been started.
    try:
        load_skill_base(settings.user_schema_base_version)
    except LookupError:
        if register_engine_contract(engine_dir, settings) is None:
            raise SkillRenderError(
                "this deployment states no compile contract, so there is nothing to render a "
                "skill from. Point PNEUMA_KNOWLEDGE_ENGINE_DIR at an engine directory whose "
                f"`{CONTRACT_FILE}` has frontmatter with `path_templates` and a non-empty "
                "body, or run this from a process that registered one."
            ) from None

    user_id = UserId(user or _default_tenant())
    canonical = None
    root = (settings.canonical_root or "").strip()
    if root and Path(root).expanduser().exists():
        from ..adapters.git_canonical import GitCanonicalStore

        canonical = GitCanonicalStore(root)
    skill = await composed_skill_readonly(settings, canonical, user_id)

    try:
        register_components(settings, store=None, canonical=None)
    except Exception:  # noqa: BLE001 — a component that cannot register leaves the package
        # without its lines, which `verify` then reports as drift; it must not stop the
        # install of everything else.
        pass
    components = tuple(registered_components())

    owner, zone, zone_source = owner_from_engine(engine_dir)
    if not zone:
        zone, zone_source = str(settings.default_timezone or "UTC"), "deployment_default"
    time = _time_context(zone, zone_source)

    try:
        framework_version = package_version("pneuma-knowledge-service")
    except PackageNotFoundError:  # pragma: no cover — an uninstalled checkout
        framework_version = "0"

    return Deployment(
        skill=skill,
        owner=owner,
        time=time,
        components=components,
        parser=parser_for(),
        language=language,
        framework_version=framework_version,
        user_id=user_id,
    )


def _time_context(zone: str, zone_source: str) -> TimeContext | None:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        info = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError, KeyError):
        return None
    return TimeContext(now_utc=_PINNED_INSTANT, zone=info, zone_source=zone_source)  # type: ignore[arg-type]


def packages(
    deployment: Deployment,
    names: Sequence[str],
    *,
    project: str | Path | None = None,
) -> list[tuple[BackendManifest, Any]]:
    """One rendered package per named backend, for `project`.

    `project` decides ONE thing — which path SKILL.md tells the Steward to run `pkc` as. A
    scaffold project has a `bin/pkc` of its own and every other document names it, so the
    skill names it too; anywhere else the skill's own shim is the entry (`project_entry`).
    Passed rather than inferred so `install`, `verify` and `show` render the same bytes for
    the same directory — a hash that changed between installing and verifying would say
    "drift" about a project nobody touched.
    """
    entry = project_entry(project)
    out = []
    for name in names:
        manifest = backend_manifest(name)
        out.append(
            (
                manifest,
                render_skill_package(
                    skill=deployment.skill,
                    owner=deployment.owner,
                    time_zone=deployment.time,
                    components=deployment.components,
                    backend=manifest,
                    cli_parser=deployment.parser,
                    language=deployment.language,
                    entry=entry,
                ),
            )
        )
    return out


def backend_names(choice: str) -> list[str]:
    return sorted(BACKENDS) if choice == "all" else [choice]


def default_parser() -> argparse.ArgumentParser:
    """The live `pkc` tree, components included — the thing `references/cli.md` describes.

    Built here rather than passed in for the callers that have no parser of their own (the
    engine's apply hook). The CLI passes the parser the process is actually running under,
    which is the same tree.
    """
    from ..cli import build_parser
    from ..cli.draft import component_tool_specs

    try:
        tools = component_tool_specs()
    except Exception:  # noqa: BLE001 — a component that cannot declare its tools leaves them
        # out of the reference, exactly as it leaves them out of the CLI.
        tools = ()
    return build_parser(tools)


def project_dir_for(settings) -> Path | None:  # noqa: ANN001
    """The project directory an engine directory belongs to — its parent.

    The scaffold's layout is `<project>/engine`, and that is the only layout in which a
    project HAS a skill install: the install is a set of files beside the engine, addressed
    from the working directory a harness is opened in. With no engine directory configured
    there is no project to speak of.
    """
    engine = str(getattr(settings, "engine_dir", "") or "").strip()
    if not engine:
        return None
    root = Path(engine).expanduser().resolve()
    return root.parent if root.name and root.parent != root else None


def installed_backends(project: Path) -> list[BackendManifest]:
    """The harnesses this project ALREADY has a skill installed for.

    A refresh re-renders what is there; it never installs a skill into a project that chose
    not to have one. The `skill-version.json` beside a skills directory is the record of that
    choice, and reading it is how the hook stays a refresh rather than a decision.
    """
    return [
        manifest
        for manifest in BACKENDS.values()
        if (project / manifest.skills_dir / VERSION_FILE).is_file()
    ]


async def refresh_skill_installs(settings) -> list[str]:  # noqa: ANN001
    """Re-render and re-install every skill this project already has. Returns what changed.

    Called after an engine apply: the contract, the overlays, the components and the language
    are exactly the inputs a package is rendered from, so an apply that moves any of them
    leaves the installed skill describing an engine that no longer exists. Blast radius is
    `future_compiles`, like every other knob that shapes what a compile reads — a session
    already running keeps the words it started with until it restarts, which the skill says.

    A deployment whose compile role is a MODEL has no Steward to teach, so nothing happens.
    Neither does anything happen for a project that never installed one.
    """
    from ..wiring import executor_for

    if not executor_for(settings, "compile").is_agent:
        return []
    project = project_dir_for(settings)
    if project is None:
        return []
    manifests = installed_backends(project)
    if not manifests:
        return []
    deployment = await resolve_deployment(
        settings, user="", parser_for=default_parser
    )
    written: list[str] = []
    for manifest, package in packages(
        deployment, [m.name for m in manifests], project=project
    ):
        written.extend(
            install_skill_package(project, manifest, package, deployment.framework_version)
        )
    return written


def _default_tenant() -> str:
    """The tenant a caller with no `--user` acts as — the CLI's own resolution, reused."""
    from ..cli import resolve_tenant

    return resolve_tenant(None)
