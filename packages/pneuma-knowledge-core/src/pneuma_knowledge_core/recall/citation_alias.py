"""Query-local citation aliasing — a pre/post hook around the recall LLM call.

The internal source_id stays a stable UUID everywhere (storage, Qdrant, canonical); the
LLM never has to copy it. Long ids are error-prone to transcribe (the blind audit saw
32-char ids truncated 32→31 and two merged into one bracketed token). So, at the LLM
boundary only, the evidence's `[cite: <uuid> …]` markers are re-labelled to short,
QUERY-LOCAL handles `sNN` — assigned per call, valid only for that call, in
first-appearance order over the sources this query actually surfaced (a handful, so two
digits is plenty; there is no need to enumerate all of a user's files).

  pre-LLM  : `alias_sources(evidence)` → (evidence with sNN, {handle: real_uuid})
  post-LLM : the caller returns the handle→uuid map; the business/UI side reverse-binds
             each `[cite: sNN]` in the answer to its real source (or `resolve_handles`
             rewrites them back to uuids). The model only ever copies `sNN`.

Pure string transform, middleware-free — it never touches storage or the id itself.
"""

from __future__ import annotations

import re

# The id sits right after `[cite:` and runs until whitespace, `¶`, or the closing `]`.
_CITE_ID_RE = re.compile(r"(\[cite:\s*)([^\s\]¶]+)")


def alias_sources(text: str) -> tuple[str, dict[str, str]]:
    """Replace each DISTINCT real source id in `[cite: <id> …]` with a short query-local
    handle `sNN` (first-appearance order). Returns (aliased_text, {handle: real_id})."""
    real_to_handle: dict[str, str] = {}

    def repl(m: re.Match) -> str:
        rid = m.group(2)
        handle = real_to_handle.get(rid)
        if handle is None:
            handle = f"s{len(real_to_handle) + 1:02d}"
            real_to_handle[rid] = handle
        return m.group(1) + handle

    aliased = _CITE_ID_RE.sub(repl, text)
    return aliased, {h: r for r, h in real_to_handle.items()}


# Consumption-side answer parsing. DISTINCT from the canonical
# `CANONICAL_CITATION_RE`, which stays strict — one span, `]`-terminated — because it gates
# compiled bodies. A model writing free-text prose sometimes merges spans into ONE
# bracket: `[cite: s01 ¶1-3, ¶5-7]` (one source, several spans) or
# `[cite: s01 ¶1-3, s02 ¶2-4]` (several sources). The strict regex matches none of these,
# silently dropping every span. Here we accept the merged form and expand it — a span
# with no sid of its own inherits the last sid seen inside the same bracket.
_CITE_BRACKET_RE = re.compile(r"\[cite:\s*(?P<body>[^\]]*?)\s*\]")
_CITE_SPAN_RE = re.compile(
    r"(?:(?P<sid>[^\s,;¶]+)\s*)?¶\s*(?P<start>\d+)(?:\s*-\s*(?P<end>\d+))?"
)


def iter_answer_citations(answer: str):
    """Yield (sid, start, end) for every block span in the answer's `[cite: …]` markers,
    expanding merged brackets. Source-level cites with no `¶` span yield nothing (there is
    no block to bind). The sid is returned raw — a query-local handle or a real id; the
    caller reverse-binds it via the handle map."""
    for bracket in _CITE_BRACKET_RE.finditer(answer):
        current_sid: str | None = None
        for span in _CITE_SPAN_RE.finditer(bracket.group("body")):
            sid = span.group("sid") or current_sid
            if sid is None:
                continue
            current_sid = sid
            start = int(span.group("start"))
            end = int(span.group("end")) if span.group("end") else start
            yield sid, start, end


# A bare id inside a `[cite: …]` bracket that carries no `¶` span at all.
_CITE_BARE_SID_RE = re.compile(r"[^\s,;¶\]]+")


def iter_answer_sources(answer: str):
    """Yield the sid of EVERY `[cite: …]` reference, span-carrying or not.

    `iter_answer_citations` is span-oriented and deliberately yields nothing for a
    source-level cite (there is no block to bind). A grounding gate asks a different
    question — "does this text point at a real source at all?" — for which a bare
    `[cite: s02]` counts. Sids repeat if the answer cites the same source twice; the
    caller dedups if it cares."""
    for bracket in _CITE_BRACKET_RE.finditer(answer):
        body = bracket.group("body")
        spans = list(_CITE_SPAN_RE.finditer(body))
        if spans:
            current_sid: str | None = None
            for span in spans:
                sid = span.group("sid") or current_sid
                if sid is None:
                    continue
                current_sid = sid
                yield sid
            continue
        for m in _CITE_BARE_SID_RE.finditer(body):
            yield m.group(0)


def strip_citations(text: str) -> str:
    """Remove every `[cite: …]` marker, tidying the whitespace it leaves behind.

    For surfaces that carry provenance as a STRUCTURED field rather than inline markup
    (the suggestion card: `citations` alongside a clean `body`). Doing this server-side is also
    what keeps a query-local `sNN` handle from ever escaping its evaluation."""
    out = _CITE_BRACKET_RE.sub("", text)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+(?=[，。；、）」！？,.;)])", "", out)
    return "\n".join(line.rstrip() for line in out.split("\n")).strip()


def resolve_handles(answer: str, handle_map: dict[str, str]) -> str:
    """Reverse the alias: rewrite `[cite: sNN …]` → `[cite: <real_id> …]` using the map.
    Unknown handles (a hallucinated/garbled one) are left untouched for the caller to see."""
    if not handle_map:
        return answer

    def repl(m: re.Match) -> str:
        real = handle_map.get(m.group(2))
        return (m.group(1) + real) if real else m.group(0)

    return _CITE_ID_RE.sub(repl, answer)


class SessionAliaser:
    """A stateful aliaser for ONE agentic recall session (e.g. a single briefing ask).

    `alias_sources` is one-shot (fast's single selector call). An agentic ask renders
    evidence more than once — the seed pack, then each tool result — so a source must keep
    the SAME handle across all of them or the chained context becomes inconsistent (s01
    here, s07 there for one source). This carries the real→handle map across every `alias`
    call in the session; `to_real` resolves a handle a tool receives (e.g.
    fetch_verbatim(source_id)) back to the real id; `resolve` maps the final answer back."""

    def __init__(self) -> None:
        self._real_to_handle: dict[str, str] = {}

    def alias(self, text: str) -> str:
        def repl(m: re.Match) -> str:
            rid = m.group(2)
            handle = self._real_to_handle.get(rid)
            if handle is None:
                handle = f"s{len(self._real_to_handle) + 1:02d}"
                self._real_to_handle[rid] = handle
            return m.group(1) + handle

        return _CITE_ID_RE.sub(repl, text)

    def to_real(self, handle_or_id: str) -> str:
        """A handle → its real id; an already-real id (or unknown) passes through."""
        return self.handle_map.get(handle_or_id, handle_or_id)

    def resolve(self, answer: str) -> str:
        return resolve_handles(answer, self.handle_map)

    @property
    def handle_map(self) -> dict[str, str]:
        return {h: r for r, h in self._real_to_handle.items()}
