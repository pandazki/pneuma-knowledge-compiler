"""Prompt catalog: every model-visible prose surface, addressable by key.

WHY THIS EXISTS
---------------
The framework has to ship *some* wording for the compile contract, the gate feedback, the
recall answer posture, the per-source preambles. Those defaults are English and
business-neutral: they name no capture medium, no product, no persona. But a deployment
that builds a real knowledge base on top of this framework has its own vocabulary, and
its tuned wording is usually the thing that makes the system work at all. Before this
module existed, that meant forking the strings — which is how a business's wording and
the framework's wording drift into two half-maintained copies.

So: one default per surface, one seam to replace it, and the seam is the SAME for every
surface. `catalog()` is the auditable list of everything a deployment may rewrite.

  from pneuma_knowledge_core.prompts import prompt
  ...
  prompt("gate.anchor_continuity", anchor=anchor)

  # at startup (wiring), business side:
  override_prompts({"gate.anchor_continuity": "..."})

CONTRACT
--------
Overrides are registered ONCE at startup (wiring) and treated as read-only afterwards.
Nothing enforces that at runtime — instead `prompt_overlay_hash()` is stamped into the
canonical commit trailer next to the skill `content_hash`, so the bytes the model saw
stay reproducible on two axes (skill hash × overlay hash) and any drift is auditable.

Invariant I5 (byte-stable SystemMessage) survives because resolution is a pure dict
lookup: the same (skill, owner, overlay) renders the same bytes every time.

LANGUAGE PACKS
--------------
`chinese_overlay()` (`prompts.lang_zh`) is a TOTAL overlay: every catalog key translated,
same placeholders. It goes through this same seam, and it goes through it FIRST — a
deployment's own clauses are registered after it and win over it. So the layering a person
sees is: English catalog → active language pack (the "framework text") → their overrides.

FIELD SUBSTITUTION
------------------
`prompt(key)` with no fields returns the template verbatim — never formatted — so a
template containing literal braces (`{"blocks": [start, end]}`) is safe.

`prompt(key, **fields)` substitutes ONLY the named placeholders it was given: `{name}` is
replaced for each `name` in `fields`, and every other brace in the template is left
byte-for-byte alone. This is deliberately narrower than `str.format`: the compile write
contract interpolates `{owner}`/`{templates}` while also *teaching* the `{slug}` path
placeholder in its own prose, and a whole-template `str.format` would either explode on
`{slug}` or require brace-escaping that an override author has to remember to reproduce.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator, Mapping

from .catalog import DEFAULTS
from .lang_zh import chinese_overlay

__all__ = [
    "catalog",
    "chinese_overlay",
    "default_catalog",
    "override_prompt",
    "override_prompts",
    "prompt",
    "prompt_overlay_hash",
    "reset_prompt_overrides",
    "resolve_or_verbatim",
    "substitute",
    "template_fields",
]

# Registered overrides. Empty on a fresh process; written at wiring time, read thereafter.
_OVERRIDES: dict[str, str] = {}

# A named placeholder: `{identifier}`. Anything else between braces (JSON, `{}`, a nested
# brace) is not a placeholder and is never touched.
_FIELD_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def template_fields(template: str) -> frozenset[str]:
    """The named placeholders a template declares — the unit of the override subset check."""
    return frozenset(_FIELD_RE.findall(template))


def substitute(template: str, fields: Mapping[str, object]) -> str:
    """Replace `{name}` for each supplied name; leave every other brace verbatim.

    Public because `prompts.surfaces` composes a surface out of several catalog templates
    and has to substitute into a template it resolved itself (from a deployment's overlay
    map rather than from the process's registered overrides). One substitution rule for
    both, or the studio's preview is a paraphrase of what the model receives.
    """

    def repl(match: re.Match[str]) -> str:
        name = match.group(1)
        return str(fields[name]) if name in fields else match.group(0)

    return _FIELD_RE.sub(repl, template)


_substitute = substitute


def prompt(key: str, /, **fields: object) -> str:
    """Resolve a prompt surface: the registered override if any, else the English default.

    With `fields` → the named placeholders are substituted (see module docstring); without
    → the template is returned verbatim, so literal braces are safe.

    Raises KeyError for an unknown key: a typo must fail loud rather than silently emit an
    empty surface to the model.
    """
    template = _OVERRIDES.get(key)
    if template is None:
        try:
            template = DEFAULTS[key]
        except KeyError:
            raise KeyError(f"unknown prompt key: {key!r}") from None
    return _substitute(template, fields) if fields else template


def resolve_or_verbatim(key_or_text: str) -> str:
    """`prompt(key_or_text)` when it names a catalog surface, else the string itself.

    The seam that lets a per-version contract clause be *either* a catalog key (the
    built-in versions, so the clause is overridable) *or* a literal sentence (a
    business-authored `SkillVersion` that just writes its own rule inline)."""
    if key_or_text in _OVERRIDES or key_or_text in DEFAULTS:
        return prompt(key_or_text)
    return key_or_text


def override_prompt(key: str, template: str) -> None:
    """Register one override. The business seam; call at startup, before serving.

    Raises ValueError for an unknown key (a silent no-op override is the worst outcome:
    the framework wording keeps reaching the model while the deployment believes it does
    not), and for a template that uses a placeholder the default does not declare — a
    superset would substitute nothing and leave a literal `{oops}` in the prompt. A SUBSET
    is legal: an override may legitimately drop a field it does not want to render.
    """
    if key not in DEFAULTS:
        raise ValueError(f"unknown prompt key: {key!r}")
    extra = template_fields(template) - template_fields(DEFAULTS[key])
    if extra:
        raise ValueError(
            f"override for {key!r} uses placeholders the default does not declare: "
            f"{sorted(extra)}"
        )
    _OVERRIDES[key] = template


def override_prompts(mapping: Mapping[str, str]) -> None:
    """Register a whole overlay (the usual entry point). Validated per key."""
    for key, template in mapping.items():
        override_prompt(key, template)


def prompt_overlay_hash() -> str | None:
    """sha256 over the sorted (key, template) pairs, or None when nothing is overridden.

    Stamped into the canonical commit trailer next to the skill content_hash so the exact
    prose the model saw is identifiable after the fact (two-axis identity)."""
    if not _OVERRIDES:
        return None
    h = hashlib.sha256()
    for key in sorted(_OVERRIDES):
        h.update(key.encode("utf-8"))
        h.update(b"\x00")
        h.update(_OVERRIDES[key].encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def catalog() -> Mapping[str, str]:
    """Every surface and its CURRENTLY EFFECTIVE template (defaults + overrides).

    Enumerable on purpose: this is how a deployment discovers what it may rewrite, and how
    a test asserts that a coverage overlay is complete."""
    return {**DEFAULTS, **_OVERRIDES}


def default_catalog() -> Mapping[str, str]:
    """The English defaults, ignoring any registered override."""
    return dict(DEFAULTS)


def overridden_keys() -> Iterator[str]:
    """The keys a deployment has actually replaced, sorted."""
    return iter(sorted(_OVERRIDES))


def reset_prompt_overrides() -> None:
    """Drop every override. Tests only — the startup contract is register-once."""
    _OVERRIDES.clear()
