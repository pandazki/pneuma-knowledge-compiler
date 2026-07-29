"""The shared recall answer-contract spine (fast / deep / briefing / suggestion).

One worldview written ONCE: the owner's profile → the evidence in front of you IS the whole
visible range + telling near-miss subjects apart by identity → tolerance for transcription
homophones → the red line (assertion strength = evidence strength, never invent) → link
provenance with `[cite:]` markers → answer posture (language / relative time / honest "not
found"). Each mode = a head stating "role + evidence forms + tool face" + this spine (with
its own citation granularity injected).

Centralizing it here is what stops the three contracts drifting: they began as copies of one
posture, and when they were patched one at a time, briefing lost the red line first and then
lost the `[cite:]` instruction (the model started writing human-readable labels like "source
s-010" instead, so the API's citations came back empty).

`spine(...)` produces a fixed value at call time, and every mode's System stays byte-stable
per prompt overlay (I5 / prompt-cache).
"""

from __future__ import annotations

from ..prompts import prompt, resolve_or_verbatim

# The one differing clause: fast cites to the source (¶ optional); deep/briefing cite the
# exact block span. Injected into the spine's citation bullet. Resolved lazily via the
# catalog so an overlay reaches them too.
CITE_SOURCE_LEVEL = "recall.cite.source_level"
CITE_PRECISE = "recall.cite.precise"

# The second injection point: the closing clause of the answer shape. Q&A modes
# (fast/deep/briefing) close on "nothing found is a faithful answer" — right when the owner
# ASKED something. A listening mode (suggestion) has no question, so that clause would make
# it push a visible card literally reading "no relevant record"; it needs its own close. Same
# mechanism as `{cite}`: one spine, one differing clause per mode, never a forked copy.
CLOSE_ANSWER_HONESTLY = "recall.close.answer_honestly"
CLOSE_SUGGESTION = "recall.close.suggestion"


def spine(cite: str, close: str) -> str:
    """The shared spine with a mode's citation-granularity + closing clauses injected.

    Both are REQUIRED, deliberately: a default `close` would silently hand the Q&A closing
    to a mode that has no question (see CLOSE_ANSWER_HONESTLY). Making it positional forces
    every mode to state which closing it is.

    Each argument may be a catalog key (the module constants above) or a literal clause; keys
    resolve through the overlay so a deployment rewrites the clause once."""
    return prompt(
        "recall.spine",
        cite=resolve_or_verbatim(cite),
        close=resolve_or_verbatim(close),
    )
