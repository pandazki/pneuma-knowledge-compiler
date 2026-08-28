"""Post-compile brief (opt-in): one short derived narration per committed compile.

The brief's ONLY input is the mechanical record of the compile — the claim events
`derive_events` computed from the diff, plus the per-source provenance sentences. The
model is allowed to phrase that record, never to extend it: it does not see the compile
conversation, the sources, or the library, so there is nothing beyond the record for it
to narrate. The output is display copy for the History timeline (labelled derived in the
UI), not knowledge: it carries no citations and never replaces the claims themselves.

A brief is best-effort by contract: an empty record yields None without a model call,
and the worker treats any generation failure as "no brief", never as a failed job.
"""

from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from ..domain.canonical import CANONICAL_CITATION_MARKER_RE
from ..domain.ids import ANCHOR_MARK_RE
from ..prompts import prompt
from ..recall.fast import invoke_config
from .runner import _call_model
from .transitions import CompileEvent

# Bounds on the record rendered into the human message: a large compile can carry
# hundreds of events with long claim bodies, and the brief needs only enough of each to
# narrate. Both dimensions are capped mechanically; the remainder is stated as a count.
MAX_RECORD_CLAIMS = 40
CLAIM_CHAR_BUDGET = 240

# Mechanical ceiling on the stored narration. The prompt asks for a few sentences, but
# the bound must not depend on the model honoring that.
BRIEF_CHAR_BUDGET = 800


def _display_text(claim_body: str) -> str:
    """A claim body as display prose: anchor marks and citation markers stripped."""
    text = ANCHOR_MARK_RE.sub("", claim_body)
    text = CANONICAL_CITATION_MARKER_RE.sub("", text)
    return " ".join(text.split())


# The verb the record uses per mechanical event type. A superseded claim is narrated as
# a state change, not as "one claim added" — that is the whole point of the marker.
_EVENT_VERBS = {
    "claim_added": "added",
    "claim_revised": "revised",
    "claim_superseded": "superseded (state changed)",
    # Not a claim change at all: the document's head was re-read off the ledger. The verb
    # says so, or a brief would narrate a re-reading as new knowledge.
    "overview_rewritten": "overview rewritten (the document's current picture)",
}


def render_brief_record(
    events: list[CompileEvent], source_lines: list[str]
) -> str:
    """The mechanical record as the model's whole input, grouped by document."""
    lines: list[str] = []
    if source_lines:
        lines.append("## Sources consumed")
        lines.extend(f"- {line}" for line in source_lines)
    lines.append("## Claim changes (mechanically derived from the diff)")

    by_path: dict[str, list[CompileEvent]] = {}
    for event in events:
        by_path.setdefault(event.path, []).append(event)

    shown = 0
    for path, path_events in by_path.items():
        if shown >= MAX_RECORD_CLAIMS:
            break
        lines.append(f"### {path}")
        for event in path_events:
            if shown >= MAX_RECORD_CLAIMS:
                break
            verb = _EVENT_VERBS.get(event.type, "revised")
            lines.append(f"- {verb}: {_display_text(event.after)[:CLAIM_CHAR_BUDGET]}")
            if event.type == "claim_superseded" and event.before:
                lines.append(
                    f"  (supersedes: {_display_text(event.before)[:CLAIM_CHAR_BUDGET]})"
                )
            shown += 1
    if len(events) > shown:
        lines.append(f"…and {len(events) - shown} further change(s) not shown.")
    return "\n".join(lines)


async def generate_brief(
    *,
    model: BaseChatModel,
    events: list[CompileEvent],
    source_lines: list[str],
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
    # Same per-call wall-clock budget as the compile loop (compile/runner.py): a hung
    # provider connection must not hold the worker. None / 0 = unbounded.
    call_timeout: float | None = None,
) -> str | None:
    """One plain-text model call over the record; None when there is nothing to tell.

    The system message is byte-stable (I5); the record rides the human message.
    """
    if not events:
        return None
    system = SystemMessage(prompt("compile.brief.system"))
    human = HumanMessage(
        prompt(
            "compile.brief.task",
            record=render_brief_record(events, source_lines),
        )
    )
    reply = await _call_model(
        model.ainvoke(
            [system, human],
            config=invoke_config("compile.brief", callbacks, trace_metadata),
        ),
        call_timeout,
    )
    content = reply.content
    text = " ".join((content if isinstance(content, str) else str(content)).split())
    return text[:BRIEF_CHAR_BUDGET] or None
