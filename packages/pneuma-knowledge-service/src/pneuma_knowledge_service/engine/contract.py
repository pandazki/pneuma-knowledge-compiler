"""The engine directory's `compile/contract.md`, as a registered `SkillVersion`.

The framework ships no domain contract: an application registers one at startup
(`register_skill_base`), and the scaffold's generated `app.py` does exactly that from
`engine/compile/contract.md`. That leaves one gap, and this module closes it — a framework
entry point invoked AGAINST a project (`pkc skill install --project <dir>`) has no
application to import, and without a contract it can render nothing.

So: the same file, the same frontmatter, the same rules, read by the framework itself. It is
deliberately a fallback and not a replacement — `register_engine_contract` is called only
when nothing is registered, so a process that HAS an application keeps the contract that
application registered, with whatever it composed into it.
"""

from __future__ import annotations

import re
from pathlib import Path

from pneuma_knowledge_core.skill.version import SkillVersion, register_skill_base

from .files import engine_path

#: The contract clauses every built-in contract carries, as catalog KEYS (so each stays
#: overridable through the ordinary prompt seam). The same tuple the generated `app.py`
#: passes; stated here because the framework now has its own reason to build this object.
CONTRACT_RULES: tuple[str, ...] = (
    "contract.rule.citation_granularity",
    "contract.rule.citation_shape",
    "contract.rule.strength_labels",
)

CONTRACT_FILE = "compile/contract.md"

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_COMMENT_RE = re.compile(r"<!--.*?-->\n?", re.DOTALL)


def load_engine_contract(engine_dir: str | Path) -> SkillVersion | None:
    """`<engine>/compile/contract.md` → a SkillVersion, or None when there is no readable one.

    Returns None rather than raising for every "there is nothing here" state — no engine
    directory, no contract file, no frontmatter, no path templates, an empty body once the
    editing guidance comments are stripped. Each of those is a project that has not stated a
    contract yet, which a caller reports in its own words; a contract that is present but
    malformed is the same non-answer, because guessing at one would register prose the
    deployment never approved.
    """
    if not str(engine_dir or "").strip():
        return None
    path = engine_path(engine_dir, CONTRACT_FILE)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return None
    import yaml

    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    templates = [str(t) for t in (meta.get("path_templates") or [])]
    body = _COMMENT_RE.sub("", text[match.end() :]).strip()
    if not templates or not body:
        return None
    skill_id = str(meta.get("skill_id") or "my-knowledge")
    version = str(meta.get("version") or "app-v1")
    return SkillVersion(
        skill_id=skill_id,
        version=version,
        instructions=body,
        path_templates=templates,
        contract_rules=CONTRACT_RULES,
        content_hash=SkillVersion.compute_hash(
            skill_id, version, body, templates, CONTRACT_RULES
        ),
    )


def register_engine_contract(engine_dir: str | Path, settings=None) -> SkillVersion | None:  # noqa: ANN001
    """Load and register the engine's contract, and point `settings` at its version.

    `settings` is mutated in place when given, because the version a deployment compiles
    under is read off it everywhere else and a registration nothing names is a registration
    nobody uses. Returns the registered version, or None when there was nothing to register.
    """
    skill = load_engine_contract(engine_dir)
    if skill is None:
        return None
    register_skill_base(skill.version, skill)
    if settings is not None:
        try:
            settings.user_schema_base_version = skill.version
        except (AttributeError, TypeError, ValueError):  # pragma: no cover — frozen settings
            pass
    return skill


def bootstrap_engine(settings) -> str:  # noqa: ANN001
    """Give a bare framework process this project's wording and contract. Returns the language.

    A process that imported an application has both already: the generated `app.py` registers
    the contract and applies the prompt overlays before it starts anything
    (`scaffold/templates/app.py`). A framework ENTRY POINT standing in a project has neither —
    and `pkc` is exactly that, because the shim runs the framework's own `pkc` rather than the
    project's driver (docs/design/coding-agent-mode.md §7). Without this, a `pkc draft` round
    would render the default wording under no contract while the skill the agent was installed
    with was rendered from the deployment's — two renderings of one deployment, which ruling 4
    exists to prevent.

    Both halves are fallbacks and neither is a replacement: an already-registered contract is
    kept, and an engine directory that states nothing leaves the process exactly as it was.
    """
    from pneuma_knowledge_core.skill import load_skill_base

    from .files import EngineFileError, parse_overlays, read_mapping
    from .prompts import active_language, apply_prompt_stack, overlays_file

    engine_dir = (getattr(settings, "engine_dir", "") or "").strip()
    language = "en"
    if engine_dir:
        language = active_language(engine_dir)
        try:
            overlays = parse_overlays(
                overlays_file(), read_mapping(engine_dir, overlays_file())
            )
        except (EngineFileError, OSError):
            overlays = {}
        apply_prompt_stack(language, overlays)
    try:
        load_skill_base(getattr(settings, "user_schema_base_version", ""))
    except LookupError:
        register_engine_contract(engine_dir, settings)
    return language
