"""SchemaPack + compose_skill: thin per-user schema extensions (M1, schema-evolve §1).

A registration profile (industry/role/occupation/bio/interests) buys little, but a owner
should feel "tailored" on day one. So each user gets a **thin, high-confidence** set of
schema extensions layered onto a built-in base skill:

- `SchemaPack` — an additive fragment: a domain instructions paragraph, extra path
  templates, extra contract rules. It never removes anything (invariant: the base's path
  ownership is a stable floor — a v2 modeling change must not orphan v1's anchors).
- `compose_skill(base, packs)` — folds packs onto a base `SkillVersion` deterministically
  (packs sorted by content, templates/rules deduped) and recomputes the content hash, so a
  per-user contract stays byte-stable per (base, pack-set) and earns the provider cache.

Two pack sources, both conservative (schema-evolve §1.2):
- `matrix_packs` — pure table lookup over a deployment-owned `industry × role` matrix. The
  packaged matrix is intentionally empty: examples and deployments opt into their own
  business vocabulary. No LLM; an empty result is always legal.
- `derive_pack` — a ONE-shot LLM inference over occupation/bio/interests, constrained to
  0–3 templates each with a one-line reason; the empty inference → no pack. `level` never
  compiles (it is a recall answer-style knob), and a `source == "mock"` synthetic picture
  is never used to derive a real user's schema.

`packs_for_profile` is the single entry that applies those rules: a mock picture yields no
packs at all (matrix included); a real/persisted picture gets matrix + (optional) derived.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from ..compile.patch import _template_regex
from ..domain.user import UserProfile
from ..prompts import prompt
from ..recall.fast import invoke_config
from .version import SkillVersion

# The derive inference is deliberately capped low (thin, high-confidence). A model that
# overruns the budget is misbehaving → the whole pack is rejected (conservative: a synthetic
# over-assertion must not silently seed a owner's schema). See derive_pack.
_MAX_DERIVED_TEMPLATES = 3


class SchemaPack(BaseModel):
    """An additive per-user schema fragment (frozen: part of a version's identity)."""

    model_config = ConfigDict(frozen=True)

    pack_id: str  # stable identity, e.g. "role-engineering" / "occ-<hash8>"
    # curated matrix · one-shot LLM derive (registration) · schema-evolve phase 1 proposal
    origin: Literal["matrix", "derived", "evolved"]
    extra_instructions: str  # domain paragraph appended after the base instructions
    extra_path_templates: list[str] = Field(default_factory=list)
    extra_contract_rules: tuple[str, ...] = ()


# --------------------------------------------------------------- template shape checks


def _is_valid_template(template: str) -> bool:
    """A legal extra path template: contains exactly `{slug}` or is a fixed single-file
    path, no other placeholder, no path escape, and `_template_regex` compiles it.

    New top-level directories (outside memory/ or materials/) are allowed — a pack may
    declare its own filing location — but the shape must still be a compilable template."""
    if not template or template.startswith("/") or ".." in template.split("/"):
        return False
    # Only `{slug}` is a legal placeholder; any other brace is a malformed template.
    stripped = template.replace("{slug}", "")
    if "{" in stripped or "}" in stripped:
        return False
    try:
        _template_regex(template)
    except re.error:
        return False
    return True


def _require_valid_template(template: str) -> None:
    if not _is_valid_template(template):
        raise ValueError(f"invalid extra path template: {template!r}")


# ------------------------------------------------------------------- content digests


def _pack_digest(pack: SchemaPack) -> str:
    h = hashlib.sha256()
    for part in (
        pack.pack_id,
        pack.origin,
        pack.extra_instructions,
        "\n".join(pack.extra_path_templates),
        "\n".join(pack.extra_contract_rules),
    ):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _packs_digest(ordered: Sequence[SchemaPack]) -> str:
    h = hashlib.sha256()
    for pack in ordered:
        h.update(_pack_digest(pack).encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


# ------------------------------------------------------------------------- compose


def compose_skill(base: SkillVersion, packs: Sequence[SchemaPack]) -> SkillVersion:
    """Fold `packs` onto `base` into a new, byte-stable SkillVersion.

    Deterministic regardless of input order: packs are ordered by (pack_id, content
    digest); instructions concatenate base + each pack paragraph; templates and rules are
    base + extras, deduped preserving first appearance. The content hash is recomputed.

    Empty packs → `base` unchanged (same object): a no-pack user's contract is byte-for-byte
    the built-in version's (I5 continuity).

    Mechanical assertions (raise ValueError, not warn): every extra template is a legal
    template shape, and `set(base.path_templates) ⊆ set(composed.path_templates)` — path
    ownership only ever grows."""
    packs = list(packs)
    if not packs:
        return base

    ordered = sorted(packs, key=lambda p: (p.pack_id, _pack_digest(p)))

    inst_parts = [base.instructions.rstrip()]
    for pack in ordered:
        seg = pack.extra_instructions.strip()
        if seg:
            inst_parts.append(seg)
    instructions = "\n\n".join(inst_parts)

    templates = list(base.path_templates)
    for pack in ordered:
        for template in pack.extra_path_templates:
            _require_valid_template(template)
            if template not in templates:
                templates.append(template)

    rules = list(base.contract_rules)
    for pack in ordered:
        for rule in pack.extra_contract_rules:
            if rule not in rules:
                rules.append(rule)
    rules = tuple(rules)

    # Additive invariant: templates only grow. Cannot fail by construction, but enforced
    # mechanically so any future refactor that violates it fails loud.
    if not set(base.path_templates) <= set(templates):
        missing = sorted(set(base.path_templates) - set(templates))
        raise ValueError(f"composed skill dropped base path templates: {missing}")

    version = f"{base.version}+packs.{_packs_digest(ordered)[:8]}"
    return SkillVersion(
        skill_id=base.skill_id,
        version=version,
        instructions=instructions,
        path_templates=templates,
        contract_rules=rules,
        content_hash=SkillVersion.compute_hash(
            base.skill_id, version, instructions, templates, rules
        ),
    )


# ------------------------------------------------------------------- matrix lookup


def _default_matrix_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "packs" / "matrix.json"


def _load_matrix(matrix_path: str | Path | None) -> list[dict]:
    """Load the deployment-owned ``packs`` list.

    The built-in asset is intentionally empty. Examples and deployments may pass a matrix
    path to opt into domain-specific filing slots without coupling them to the core package.
    An absent packaged default degrades to the base skill; an explicitly configured path is
    part of the deployment contract and therefore fails loud when missing or malformed."""
    explicit = matrix_path is not None
    path = Path(matrix_path) if explicit else _default_matrix_path()
    if not path.is_file():
        if explicit:
            raise FileNotFoundError(f"schema pack matrix not found: {path}")
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        if explicit:
            raise ValueError(f"invalid schema pack matrix {path}: {exc}") from exc
        return []
    if not isinstance(data, Mapping) or not isinstance(data.get("packs", []), list):
        if explicit:
            raise ValueError(
                f"invalid schema pack matrix {path}: expected an object with a packs list"
            )
        return []
    return data.get("packs", [])


def matrix_packs(
    industry: str, role: str, *, matrix_path: str | Path | None = None
) -> list[SchemaPack]:
    """Pure table lookup: packs whose `role ∈ roles` and (`industries` empty or
    `industry ∈ industries`), ordered by pack_id. No match → []."""
    out: list[SchemaPack] = []
    for entry in _load_matrix(matrix_path):
        if not isinstance(entry, Mapping):
            continue
        match = entry.get("match", {}) or {}
        roles = match.get("roles", []) or []
        industries = match.get("industries", []) or []
        if role in roles and (not industries or industry in industries):
            out.append(
                SchemaPack(
                    pack_id=str(entry["pack_id"]),
                    origin="matrix",
                    extra_instructions=str(entry.get("extra_instructions", "")),
                    extra_path_templates=list(entry.get("extra_path_templates", []) or []),
                    extra_contract_rules=tuple(entry.get("extra_contract_rules", []) or ()),
                )
            )
    return sorted(out, key=lambda p: p.pack_id)


# --------------------------------------------------------------------- LLM derive


class _DerivedTemplate(BaseModel):
    path_template: str
    reason: str  # one line: why this owner repeatedly produces this kind of memory


class _DerivedPack(BaseModel):
    """Structured output of the one-shot derive inference (0–3 templates, may be empty)."""

    instructions: str = ""
    templates: list[_DerivedTemplate] = Field(default_factory=list)


def derive_pack_contract() -> str:
    """The byte-stable System contract for the occupation/bio/interests derive inference.

    Resolved through the prompt catalog (`skill.derive_contract`), whose default is the
    packaged `assets/packs/derive_contract.md` bytes — so the asset stays the editable form
    while a deployment can replace the whole contract through the standard seam. No volatile
    content: the profile rides the HumanMessage."""
    return prompt("skill.derive_contract")


def _derive_human(profile: UserProfile) -> str:
    empty = prompt("skill.derive.empty")
    separator = prompt("skill.derive.interest_separator")
    interests = separator.join(profile.interests) if profile.interests else empty
    return prompt(
        "skill.derive.human",
        occupation=profile.occupation or empty,
        bio=profile.bio or empty,
        interests=interests,
    )


def _derived_pack_id(profile: UserProfile) -> str:
    """Stable pack id from the free-text picture — the same owner derives the same id."""
    seed = "\x00".join([profile.occupation or "", profile.bio or "", *profile.interests])
    return "occ-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8]


async def derive_pack(
    model: BaseChatModel,
    profile: UserProfile,
    *,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> SchemaPack | None:
    """One-shot LLM inference: occupation/bio/interests → at most one derived SchemaPack.

    Conservative and fail-soft (mirrors recall/suggestion.py's include_raw parsing):
    - a `source == "mock"` synthetic picture is never derived from → None;
    - a parse failure / non-schema / LLM error → None (degrade, never raise);
    - more than `_MAX_DERIVED_TEMPLATES` templates → None (over-budget = untrusted);
    - malformed template shapes are dropped; no valid template survives → None;
    - an empty inference → None."""
    if profile.source == "mock":
        return None

    structured = model.with_structured_output(_DerivedPack, include_raw=True)
    try:
        raw = await structured.ainvoke(
            [
                SystemMessage(content=derive_pack_contract()),
                HumanMessage(content=_derive_human(profile)),
            ],
            config=invoke_config("skill.derive", callbacks, trace_metadata),
        )
    except Exception:  # noqa: BLE001 — a derive failure degrades to matrix-only, never 500s
        return None

    parsed = raw.get("parsed") if isinstance(raw, Mapping) else raw
    if not isinstance(parsed, _DerivedPack):
        return None
    if len(parsed.templates) > _MAX_DERIVED_TEMPLATES:
        return None

    paths: list[str] = []
    for template in parsed.templates:
        candidate = (template.path_template or "").strip()
        if candidate and _is_valid_template(candidate) and candidate not in paths:
            paths.append(candidate)
    if not paths:
        return None

    return SchemaPack(
        pack_id=_derived_pack_id(profile),
        origin="derived",
        extra_instructions=(parsed.instructions or "").strip(),
        extra_path_templates=paths,
        extra_contract_rules=(),
    )


# ----------------------------------------------------------------- profile → packs


async def packs_for_profile(
    profile: UserProfile,
    *,
    model: BaseChatModel | None = None,
    matrix_path: str | Path | None = None,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> list[SchemaPack]:
    """Derive schema only from declared owner information.

    Mock and unstated profiles add no packs. Declared industry/role may select matrix
    packs; model derivation additionally needs occupation, biography or interests, which
    are the evidence actually sent to that call. An empty profile must not incur a call
    that can invent a domain.
    """
    if profile.source in {"mock", "unstated"}:
        return []
    packs = list(matrix_packs(profile.industry, profile.role, matrix_path=matrix_path))
    if model is not None and any((profile.occupation.strip(), profile.bio.strip(),
                                  any(item.strip() for item in profile.interests))):
        derived = await derive_pack(
            model, profile, callbacks=callbacks, trace_metadata=trace_metadata
        )
        if derived is not None and derived.pack_id not in {p.pack_id for p in packs}:
            packs.append(derived)
    return packs
