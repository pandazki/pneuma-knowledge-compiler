"""The Prompt Studio's service half: surfaces resolved against one engine directory.

The console's overlay picker used to hand a person a list of ~340 dotted keys and ask them
to guess. What a key IS only becomes legible in the prompt it lands in, so this module
answers with SURFACES — core's `prompts.surfaces` registry, rendered twice per surface
(framework wording, and this engine directory's effective wording) plus, per segment, the
framework original, the current override, its placeholder contract and the other surfaces
it moves.

Two things this module deliberately does NOT do:

* **Resolve through the running process.** `prompt()` reads the overrides `app.py`
  registered at startup, which is the wording of whatever engine directory the process
  booted with — not necessarily the one being edited, and never the uncommitted state of
  it. Both renders take an explicit catalog mapping, so the studio shows the directory it
  is pointed at.
* **Put its own rewriting prompt in the catalog.** The catalog is the inventory of prose
  the knowledge PIPELINE emits — the thing a deployment tunes. The studio's authoring
  assistant is console machinery: catalog-ing it would make the rewriter overridable by
  the very overlay map it exists to edit, and would drag the committed engine schema asset
  (whose overlay enum is the catalog's key list) along behind every wording tweak.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

from pneuma_knowledge_core.prompts import (
    chinese_overlay,
    default_catalog,
    template_fields,
)
from pneuma_knowledge_core.prompts.surfaces import (
    FRAGMENTS,
    SURFACES,
    render_surface,
    segment_context,
    segment_label,
    shared_with,
    surface_note,
)
from pydantic import BaseModel, Field

from .files import EngineFileError, parse_overlays, read_mapping
from .stage_map import STAGES

# How much of a neighbouring clause the rewriter is shown. Enough to hear the register and
# see how the target clause has to compose with what surrounds it; not so much that the
# write contract's ten kilobytes crowd out the clause actually being rewritten.
_NEIGHBOUR_CHARS = 700


class PromptRewrite(BaseModel):
    """The rewriter's structured answer. The class NAME is part of the contract: a
    scripted model matches a structured-output call by it."""

    draft: str = Field(description="the replacement clause body, verbatim, nothing else")
    notes: str = Field(description="one line saying what changed, in the requested locale")


def overlays_file() -> str:
    """The engine-relative path of the overlay map, read off the stage map rather than
    spelled again here."""
    for stage in STAGES:
        for knob in stage.knobs:
            if knob.type == "overlay_map":
                return stage.file
    raise RuntimeError("the stage map declares no overlay_map knob")


def read_overlays(engine_dir: str | Path) -> dict[str, str]:
    """This engine directory's current overlay map: catalog key → replacement clause.

    Reads only the overlay file, not the whole directory: a stage file somebody broke by
    hand must not cost the studio its entire picture, and the overlay map has no
    environment variable, so the file is the only place its value can come from.
    """
    rel = overlays_file()
    return parse_overlays(rel, read_mapping(engine_dir, rel))


def _language_knob():
    """The prompt-language knob, read off the stage map rather than spelled again here."""
    for stage in STAGES:
        for knob in stage.knobs:
            if knob.setting == "prompt_language":
                return knob
    raise RuntimeError("the stage map declares no prompt-language knob")


def active_language(engine_dir: str | Path, environ: Mapping[str, str] | None = None) -> str:
    """Which language pack this engine directory runs under: env > that file > default.

    The same three-level precedence `resolve.engine_overrides` applies, but reading only the
    one stage file — for the reason `read_overlays` gives: a stage file somebody broke by
    hand must not cost the studio its picture of the prompts, and the studio has to know
    which language the framework text is in before it can show any of it.
    """
    env = os.environ if environ is None else environ
    knob = _language_knob()
    if knob.env in env:
        return str(env[knob.env]).strip() or str(knob.enum[0])
    try:
        stated = read_mapping(engine_dir, overlays_file()).get(knob.key)
    except EngineFileError:
        stated = None
    value = str(stated or "").strip()
    return value if value in knob.enum else str(knob.enum[0])


def language_pack(language: str) -> dict[str, str]:
    """The framework's own wording in `language` — English needs no pack, so `{}`.

    One function decides what "the active language pack" means, and both consumers read it
    from here: the startup registration below, and the studio's `framework_text`. Two
    readings of that would be a console showing a person prose the model never receives.
    """
    if str(language).strip() == "zh":
        return dict(chinese_overlay())
    return {}


def framework_catalog(language: str) -> dict[str, str]:
    """The catalog as the framework itself would emit it under `language`.

    This is the layer a deployment's overlays sit ON. The distinction matters to the
    console: below the language pack there is no author, only the framework, so the pack's
    wording is presented as framework text — and an overlay on top of it is presented as an
    override, exactly as it is with the English default.
    """
    return {**default_catalog(), **language_pack(language)}


def apply_prompt_stack(language: str, overlays: Mapping[str, str]) -> int:
    """Register the language pack, then the deployment's overlays. Returns the clause count.

    The ORDER is the contract: a deployment that translated one clause its own way must keep
    that clause, and a pack applied afterwards would silently take it back. Registration is
    the once-at-startup seam `prompts.override_prompts` documents, so this is called from the
    process's assembly point (the generated `app.py`), not per request.
    """
    from pneuma_knowledge_core.prompts import override_prompts

    pack = language_pack(language)
    if pack:
        override_prompts(pack)
    if overlays:
        override_prompts(overlays)
    return len(overlays)


def surface_payload(
    overlays: Mapping[str, str], *, language: str = "en"
) -> list[dict[str, Any]]:
    """Every surface, resolved against `overlays` — the `GET /v1/engine/prompts` body.

    A `fragments` surface reports empty assembled strings, not a concatenation of its
    clauses. `source.preamble.*` is 28 conditional alternatives and word fillers, and
    joining them produced "the ownera conversationThis is…" — the console would have been
    teaching a newcomer a sentence no model has ever received. Each clause carries its own
    `context` instead: the situation in which the model does receive it.
    """
    framework = framework_catalog(language)
    effective = {**framework, **overlays}
    out: list[dict[str, Any]] = []
    for surface in SURFACES:
        fragments = surface.kind == FRAGMENTS
        segments = []
        for segment in surface.segments:
            original = framework[segment.key]
            segments.append(
                {
                    "key": segment.key,
                    "label": segment_label(segment.key),
                    # None where the clause's position in an assembly is its own account of
                    # when the model sees it; a sentence wherever it is not.
                    "context": segment_context(segment),
                    "framework_text": original,
                    "override_text": overlays.get(segment.key),
                    "placeholders": sorted(template_fields(original)),
                    "shared_with": list(shared_with(surface.id, segment.key)),
                }
            )
        out.append(
            {
                "id": surface.id,
                "group": surface.group,
                "kind": surface.kind,
                "title": {"en": surface.title_en, "zh": surface.title_zh},
                "summary": {"en": surface.summary_en, "zh": surface.summary_zh},
                # Present exactly when the assembled bytes are a TEMPLATE rather than the
                # message: runtime substitution, a clause a knob picks, a human turn that is
                # not shown. `null` is the licence to call the preview what the model
                # receives; a sentence withdraws it.
                "note": surface_note(surface),
                "segments": segments,
                "assembled_framework": (
                    "" if fragments else render_surface(surface, catalog=framework)
                ),
                "assembled_effective": (
                    "" if fragments else render_surface(surface, catalog=effective)
                ),
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────── the rewriter


_REWRITE_SYSTEM = """\
You rewrite ONE clause of a knowledge compiler's prompt, for the person who operates this
deployment.

A knowledge compiler assembles the prompts its models see out of a catalog of named
clauses. Whatever you return is written verbatim into the prompt at exactly the position
the original clause occupies — so it is not a suggestion, a summary or an explanation. It
is the clause.

Hard rules:

- Return the clause body only. No surrounding quotes, no markdown fence, no preamble, no
  commentary, and no heading you were not given. If the original is a single sentence,
  return a single sentence; if it is a section with headings, keep that shape.
- Preserve every named placeholder in the placeholder contract below, spelled exactly,
  braces included. The framework substitutes real values into them at run time; a clause
  that drops one silently loses that value, and this deployment's write-time check refuses
  the save anyway.
- Introduce no placeholder outside that list. An unrecognised `{name}` is not substituted
  — it reaches the model as literal braces.
- Keep the clause's JOB. It has to keep composing with the clauses around it, shown below:
  same register, same role in the surrounding prompt, and roughly the same length unless
  the operator's intent asks for a different one.
- Do the operator's intent and nothing besides it. Do not smuggle in rules they did not
  ask for, and do not soften a constraint they kept.
- This wording reaches a model that writes into, or answers from, somebody's knowledge
  base. State mechanisms and criteria; never plead ("please remember to…") — a rule that
  is not mechanical does not survive the round it was written for.

{language_rule}
Write `notes` as ONE line, in {locale}, saying what you changed and why.
"""

# The clause goes back into a language pack, so the pack's language — not the language the
# operator happened to type their intent in, and not the console's UI locale — decides what
# the replacement must be written in. The Chinese rule names the terms that were actually
# degraded: a real run rewrote 闸门 / 断言级 into `gate` / `claim-level`, passed the
# placeholder gate (no slots involved) and was appliable, because nothing in the brief said
# the clause had to stay Chinese.
_LANGUAGE_RULES: dict[str, str] = {
    "en": """\
Language: this deployment's prompt pack is ENGLISH, and your clause goes back into it, so
write it in English. Keep the original's terminology: do not swap a term the original
already uses for a synonym of your own, and do not answer in whatever language the operator
happened to write their intent in. Only an explicit request in the intent may change the
language, and then the whole clause changes — never half of it.\
""",
    "zh": """\
Language: 本部署的提示词语言包是**中文**，你交回的这一条会写回这个包里，所以整条都要用中文写。
已经是中文的术语必须保持中文，不得替换成英文对应词——「闸门」不写成 gate，「断言」不写成 claim
或 claim-level，「正本」不写成 canonical，「锚点」不写成 anchor，「引用」不写成 citation，
「来源」不写成 source，「编译」不写成 compile。这是模型读到的中文提示词，混进英文术语会让同一
份包里出现两套词汇，读的人得先在心里翻译一遍。
不是术语、必须原样保留的：代码标识符、工具名、字段名、枚举值与占位符（`finish_compile`、
`edit_claim`、`type`、`{anchor}`）。中文与拉丁字母之间留一个空格。
只有当操作者明确要求换语言时才换，而且要整条换，不能只换一半。\
""",
}


def _language_rule(language: str) -> str:
    return _LANGUAGE_RULES.get(str(language).strip(), _LANGUAGE_RULES["en"])


def _excerpt(text: str, limit: int = _NEIGHBOUR_CHARS) -> str:
    body = text.strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + "\n…(truncated for context)"


def _surfaces_holding(key: str):
    return [s for s in SURFACES if any(seg.key == key for seg in s.segments)]


def _neighbour_lines(key: str, catalog: Mapping[str, str]) -> list[str]:
    """The target's position inside its primary surface: the ordered segment list, and the
    text of the segment either side of it. Position is most of what "what is this clause
    for" means — a clause read alone is a clause anybody can reword into something that no
    longer fits between its neighbours.

    Except in a fragment family, where there is no "between": the clauses are alternatives
    and independent emissions. Telling the rewriter that `source.preamble.owner_default`
    sits after `title_quoted` and before `stream_tail` would be a false brief, and a
    rewriter briefed falsely writes a clause that reads like prose in a slot that takes a
    noun. So that case gets its own account: the family, and this clause's own situation.
    """
    holders = _surfaces_holding(key)
    if not holders:
        return []
    surface = holders[0]
    keys = [seg.key for seg in surface.segments]
    index = keys.index(key)
    target = surface.segments[index]
    fragments = surface.kind == FRAGMENTS
    lines = [
        (
            f"# The clause family this belongs to: {surface.title_en}"
            if fragments
            else f"# The prompt this clause belongs to: {surface.title_en}"
        ),
        surface.summary_en,
    ]
    if fragments:
        lines += [
            "",
            "These clauses are NOT a prose prompt read top to bottom: they are independent, "
            "reached one at a time — often exactly one of them per run. Keep this clause "
            "usable in its own situation and do not make it read as a continuation of any "
            "other.",
        ]
    lines += [
        "",
        (
            "The family's clauses (→ marks the one being rewritten):"
            if fragments
            else "Its clauses, in order (→ marks the one being rewritten):"
        ),
    ]
    for position, seg in enumerate(surface.segments):
        marker = "→" if position == index else " "
        role = "" if seg.role == "block" else f" [{seg.role}]"
        lines.append(f"{marker} {seg.key} — {segment_label(seg.key)['en']}{role}")
    context = segment_context(target)
    if context is not None:
        lines += ["", "# When the model receives this clause", context["en"]]
    if not fragments:
        for label, offset in (("before", -1), ("after", 1)):
            pos = index + offset
            if 0 <= pos < len(surface.segments):
                neighbour = surface.segments[pos]
                lines += [
                    "",
                    f"## The clause immediately {label} it ({neighbour.key})",
                    _excerpt(catalog.get(neighbour.key, "")),
                ]
    if len(holders) > 1:
        others = ", ".join(s.title_en for s in holders[1:])
        lines += [
            "",
            "This clause is SHARED: rewriting it also changes " + others + ".",
        ]
    return lines


def rewrite_messages(
    key: str,
    intent: str,
    locale: str,
    overlays: Mapping[str, str],
    *,
    language: str = "en",
) -> tuple[str, str]:
    """(system, human) for one rewrite call, resolved against this engine's overlays.

    `language` is the engine directory's ACTIVE PROMPT LANGUAGE, and it decides two things
    the rewriter used to get wrong. It picks the framework wording the model is shown — under
    a Chinese engine the brief used to carry the English default, so the rewriter was being
    asked to "keep the original's language" while looking at prose the deployment does not
    use. And it picks the language rule, because the clause is written back into that pack.

    `locale` stays the console's UI locale: it is who reads `notes`, not what the clause is
    written in. The two are independent (an English UI over a Chinese pack is a normal
    setup), which is exactly why one value could not answer both questions.
    """
    framework = framework_catalog(language)
    original = framework[key]
    slots = sorted(template_fields(original))
    sections = _neighbour_lines(key, {**framework, **overlays})
    sections += [
        "",
        f"# The framework's original wording for `{key}`",
        original,
        "",
        "# Placeholder contract",
        (
            "This clause declares these named placeholders, and your replacement must "
            "contain every one of them, spelled exactly: " + ", ".join(f"{{{s}}}" for s in slots)
            if slots
            else "This clause declares no placeholders. Do not introduce any."
        ),
        "",
        "# The override currently in force",
        overlays.get(key) or "(none — the framework wording is what the model sees today)",
        "",
        "# What the operator wants",
        intent.strip(),
        "",
        f"Return the replacement clause for `{key}`.",
    ]
    system = _REWRITE_SYSTEM.replace("{language_rule}", _language_rule(language)).replace(
        "{locale}", locale
    )
    return system, "\n".join(sections)
