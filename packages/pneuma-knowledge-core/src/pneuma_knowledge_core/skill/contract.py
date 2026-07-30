"""render_system_contract: the compile agent's SystemMessage.

It is byte-stable (invariant I5): no timestamp, no task content, no source content —
only mechanism facts. Assembly order earns the provider cache. No YAML dump
(architecture.md §8). The prose states what the mechanism DOES ("tools keep the anchor",
"deletion is rejected"); it does not plead ("please remember") — that path was falsified
(§0 discipline 1).

Every sentence here is resolved through the prompt catalog (`prompts.prompt`), so a
deployment can replace any section wholesale without forking this module; the assembly
ORDER stays here, because the order is the mechanism.

STRUCTURE (why it is ordered this way)
--------------------------------------
The contract used to open on write mechanics — anchors and tool signatures — with the only
statement of purpose being three lines followed by "the mechanisms below are mechanically
enforced, not advice". An agent that reads tool semantics before it knows what the system
is, which layer it is writing, who consumes the output, or what question it is answering
has no basis for the judgment calls the task actually needs; it can only pattern-match its
way to *some* output. So the contract goes framing → role → criterion → mechanism:

  1. what you are doing — what knowledge compilation is, the four layers, which one this
                          step writes, and who consumes it downstream (hence why citations
                          are hard).
  2. who you are        — the executor's role and the qualities the job needs.
  3. the criterion      — the single question, stated ONCE and up front.
  4. four mechanisms    — the same mechanics as before, but each introduced as a
                          CONSEQUENCE of the criterion, not as an item in a flat rule list.

The mechanism text itself is unchanged in substance: same tools, same anchor rules, same
citation grammar, same path ownership. Only the framing and the grouping are new.
"""

from __future__ import annotations

from ..prompts import prompt, resolve_or_verbatim
from .version import SkillVersion


def _owner_lines(owner: object) -> list[str]:
    """Profile → the identity lines. Only fields that actually change a compile judgment
    are rendered; presentation-only fields (avatar) and recall-tuning knobs (level, which
    tunes answer STYLE, not what is memory-worthy) are deliberately left out. Absent or
    blank fields are skipped rather than rendered as empty labels.

    Locale is NOT one of these lines: region, timezone and language are declared — with
    their provenance — by `_environment_section`, and stating them twice in one section, once
    as background and once as an instruction, is how a contract starts contradicting itself."""
    get = lambda name: (getattr(owner, name, None) or "")  # noqa: E731
    list_sep = prompt("compile.owner_field.list_separator")
    detail_sep = prompt("compile.owner_field.detail_separator")
    unspecified = prompt("compile.owner_field.unspecified")
    unlabeled = prompt("compile.owner_field.unlabeled")
    lines: list[str] = [
        prompt(
            "compile.owner_field.name",
            value=get("display_name") or unspecified,
        )
    ]
    occupation = get("occupation")
    if occupation:
        lines.append(prompt("compile.owner_field.occupation", value=occupation))
    industry, role = get("industry"), get("role")
    if industry or role:
        lines.append(
            prompt(
                "compile.owner_field.industry_role",
                industry=industry or unlabeled,
                role=role or unlabeled,
            )
        )
    workspace = getattr(owner, "workspace", None)
    if workspace is not None:
        mode = getattr(workspace, "operating_mode", "")
        stack = getattr(workspace, "primary_stack", "")
        detail = detail_sep.join(
            x
            for x in (
                prompt("compile.owner_field.collab_mode", value=mode) if mode else "",
                stack,
            )
            if x
        )
        if detail:
            lines.append(prompt("compile.owner_field.working_style", value=detail))
    bio = get("bio")
    if bio:
        lines.append(prompt("compile.owner_field.background", value=bio))
    interests = getattr(owner, "interests", None) or []
    if interests:
        lines.append(
            prompt("compile.owner_field.interests", value=list_sep.join(interests))
        )
    return lines


def _locale_field(owner: object | None, name: str) -> str:
    """One `locale.<name>` string, duck-typed and blank when absent."""
    locale = getattr(owner, "locale", None)
    if locale is None:
        return ""
    return str(getattr(locale, name, "") or "").strip()


def _timezone_line(owner: object | None, time: object | None) -> str:
    """The timezone declaration, branched on WHERE the zone came from.

    `time` is the job's TimeContext (duck-typed): it already ran the resolution chain, so it
    knows both the zone and which link answered — and that is what has to be declared, since
    a deployment default dressed up as the subject's own setting is a statement nobody can
    support. With no TimeContext the profile is the only thing left to read; with neither, the
    honest line is that no zone was resolved.
    """
    zone = str(getattr(time, "zone_name", "") or "") if time is not None else ""
    source = str(getattr(time, "zone_source", "") or "") if time is not None else ""
    if not zone:
        zone, source = _locale_field(owner, "timezone"), "profile"
    if not zone:
        return prompt("compile.owner_env.timezone_unknown")
    key = {
        "provider": "compile.owner_env.timezone_provider",
        "profile": "compile.owner_env.timezone_profile",
        "deployment_default": "compile.owner_env.timezone_default",
    }.get(source, "compile.owner_env.timezone_unstated")
    return prompt(key, value=zone)


def _environment_section(owner: object | None, time: object | None) -> str:
    """The subject's declared environment: region, timezone, language, and the write rule.

    Rendered on BOTH owner paths, including "no profile supplied": the whole point is that
    every state is declared rather than left to the model to guess, and "no profile" is a
    state — all three fields unknown, with the defaults that are being used in their place
    named out loud.

    Byte-stable per (owner, zone, zone_source, overlay): the TimeContext's instant is never
    read here, only its zone and that zone's provenance, so this stays inside the SystemMessage
    without spending the provider cache (invariant I5).
    """
    list_sep = prompt("compile.owner_field.list_separator")
    where = list_sep.join(
        x for x in (_locale_field(owner, "city"), _locale_field(owner, "country")) if x
    )
    language = _locale_field(owner, "language")
    lines = [
        prompt("compile.owner_env.region", value=where)
        if where
        else prompt("compile.owner_env.region_unknown"),
        _timezone_line(owner, time),
        prompt("compile.owner_env.language", value=language)
        if language
        else prompt("compile.owner_env.language_unknown"),
    ]
    policy = "\n".join(
        (
            prompt("compile.owner_env.write_language"),
            prompt("compile.owner_env.day_grouping"),
        )
    )
    return prompt(
        "compile.owner_env.section", lines="\n".join(lines), policy=policy
    )


def render_system_contract(
    skill: SkillVersion, owner: object | None = None, *, time: object | None = None
) -> str:
    """Assemble the system contract for `skill`, optionally naming the knowledge subject.

    Byte-stable per (skill, owner, prompt overlay) triple (invariant I5): the profile is
    stable identity data and the overlay is registered at startup, so the assembled
    contract still earns the provider cache across a user's jobs. Nothing volatile enters
    here — no timestamp, no task content, no source content; the per-run facts (today's
    date, this round's material) belong in the HumanMessage.

    `owner` is duck-typed (a `domain.user.UserProfile` in practice) and optional so every
    existing caller — evolve, the runner tests, the examples — keeps working unchanged and
    simply renders the "subject unknown" variant.

    `time` is the job's TimeContext, and ONLY its zone and that zone's provenance are read
    (never its instant), so the contract stays byte-stable while still being able to say why
    it is counting days in this zone. Omitted, the subject's profile is the only source of a
    timezone left.

    A version's `contract_rules` entries are resolved with `resolve_or_verbatim`: a
    built-in version stores a catalog KEY (so the clause is overridable through the same
    seam as everything else), while a business-authored SkillVersion may store a literal
    sentence and it is emitted as written.
    """
    templates = "\n".join(f"  - {t}" for t in skill.path_templates)
    environment = _environment_section(owner, time)
    owner_section = (
        prompt(
            "compile.owner_section",
            lines="\n".join(_owner_lines(owner)),
            environment=environment,
        )
        if owner is not None
        else prompt("compile.owner_unknown", environment=environment)
    )
    contract = prompt(
        "compile.write_contract", templates=templates, owner=owner_section
    )
    if skill.contract_rules:
        rules = "\n".join(f"- {resolve_or_verbatim(r)}" for r in skill.contract_rules)
        contract = f"{contract}\n{prompt('compile.rules_header')}\n{rules}\n"
    header = prompt(
        "compile.skill_header", skill_id=skill.skill_id, version=skill.version
    )
    # The skill body answers "what should be recorded, and where" — the domain layer of the
    # same criterion stated in §4. Saying so here keeps the two halves one argument rather
    # than two.
    lede = prompt("compile.skill_lede")
    return f"{contract}\n{header}\n\n{lede}\n\n{skill.instructions.rstrip()}\n"
