"""Relevance ordering, honest truncation and budgeting for component evidence.

WHY THE FRAMEWORK ORDERS, AND THE COMPONENT DOES NOT
-----------------------------------------------------
A component path is an EXACT lookup: `person(alias="贾宁")` knows the whole page, and
`timespan(2026-06-01, 2026-06-30)` knows every span of that month. It has no opinion about
the question — it was never given one — so any cap it applies itself is a cap on DOCUMENT
order, and the claim that answers the question falls past it as often as not. That is the
failure this module exists to remove: **paths return everything they know; ordering,
truncation, dedup and budgeting are framework mechanisms, stated once, here.**

Two properties are non-negotiable. The order is DETERMINISTIC — the same question over the
same lookup produces the same evidence, with no model in the loop. And every truncation is
RECOVERABLE — what fell off is described (which sections, which days, how many), never
silently dropped, so the answer model and the reader both know a lookup had more.

THE SCORE
---------
For one candidate (a claim or a source window):

    score = overlap + label + time

* **overlap** ∈ [0, 1] — the share of the question's tokens the candidate's text and its
  section path cover. Tokenization is unicode-aware: CJK runs become character bigrams
  (`贾宁现在` → `贾宁`,`宁现`,`现在`), Latin/digit runs become lowercase words, and
  stopwords are dropped. ISO-ish dates survive as single tokens.
* **label** — `+CURRENT_BONUS` for a candidate a component marked `current`,
  `-SUPERSEDED_PENALTY` for one marked `superseded`. History therefore sorts after live
  material unless the question's own words hit it harder than the penalty.
* **time** — when the question names a day, month or year AND the candidate's day is known
  (from `source_days` for one of its citations, or from a date written in its own text or
  section path), closeness pays: an exact day beats a shared month beats a shared year.

Ties break by the path's own order (`index`), so a component that returns "current first,
then history" keeps that order wherever the question does not separate two candidates.

When a reranker is wired, its scores replace **overlap** (they are the judgement overlap
approximates) and the label/time terms stay as tie-breaks; the caller normalizes nothing —
`rank_candidates` min-max normalizes the submitted scores into [0, 1] itself, so the two
regimes stay on one scale. A reranker failure means the caller passes `None` and the
lexical score is used: fail-soft, never a failed lookup.

THE BUDGET
----------
`apply_cap` spends a path's declared cap AFTER ordering, across claims and windows
together (interleaved by score — never a fixed 50/50 split), under two floors: at least one
window when the path returned any, and the top-scoring claim of every distinct section, so
a page section never vanishes entirely. `budget_render` then holds the whole component face
under a character budget, cutting over-long windows at BLOCK boundaries and stating the
block range it did not show.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from .fast import RetrievedClaim
    from .rag import RecallHit

#: A component marked this candidate as the state that holds now. The label terms are
#: deliberately smaller than the overlap term's typical range: they break ties between
#: candidates the question does not separate, they do not overrule a question that plainly
#: asks about the older state ("贾宁以前在哪家公司").
CURRENT_BONUS = 0.05
#: …and this one as history canonical has already replaced.
SUPERSEDED_PENALTY = 0.15
#: Time proximity, strongest first: same day, same month, same year.
DAY_BONUS = 0.30
MONTH_BONUS = 0.20
YEAR_BONUS = 0.10

_LATIN_STOPWORDS = frozenset(
    """a an and are as at be been by did do does for from had has have he her his how i in is
    it its me my of on or she that the their them there they this to was we were what when
    where which who whom why will with you your""".split()
)
#: Only consulted for a ONE-character CJK run — a bigram of particles is already harmless.
_CJK_STOPCHARS = frozenset("的了是在和与我你他她它就都也很不有个吗呢啊么等把被将从")

_CJK_RANGES = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x20000, 0x2FA1F),
    (0x3040, 0x30FF),  # kana: same "no spaces" problem, same bigram answer
)

_ISO_DAY_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_ISO_MONTH_RE = re.compile(r"(?<!\d)(\d{4})-(\d{1,2})(?!\d|-)")
_CN_DATE_RE = re.compile(r"(\d{4})\s*年(?:\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?)?")
_CN_MONTH_RE = re.compile(r"(?<!\d)(\d{1,2})\s*月(?!\d)")
_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})(?!\d)")
_MONTH_NAMES = {
    name: index
    for index, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        start=1,
    )
    for name in names
}


def _is_cjk(char: str) -> bool:
    point = ord(char)
    return any(low <= point <= high for low, high in _CJK_RANGES)


def tokenize(text: str) -> list[str]:
    """Question/candidate text → comparable tokens (order kept, duplicates kept).

    CJK runs become character bigrams, everything else becomes lowercase word/number runs.
    Punctuation and Latin stopwords are dropped; a hyphenated ISO date survives whole
    because the digit run keeps its dashes (`2026-06-02`)."""
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    tokens: list[str] = []
    run: list[str] = []
    cjk_run: list[str] = []

    def flush_latin() -> None:
        if not run:
            return
        word = "".join(run)
        run.clear()
        if word and word not in _LATIN_STOPWORDS:
            tokens.append(word)

    def flush_cjk() -> None:
        if not cjk_run:
            return
        chars = list(cjk_run)
        cjk_run.clear()
        if len(chars) == 1:
            if chars[0] not in _CJK_STOPCHARS:
                tokens.append(chars[0])
            return
        tokens.extend(chars[i] + chars[i + 1] for i in range(len(chars) - 1))

    for char in normalized:
        if _is_cjk(char):
            flush_latin()
            cjk_run.append(char)
            continue
        flush_cjk()
        if char.isalnum():
            run.append(char)
        elif char in "-" and run and run[-1].isdigit():
            run.append(char)  # keep `2026-06-02` in one piece
        else:
            flush_latin()
    flush_latin()
    flush_cjk()
    return [t.strip("-") for t in tokens if t.strip("-")]


def date_keys(text: str, *, as_of: datetime | None = None) -> set[str]:
    """Every day/month/year key a text names, normalized (`2026-06-02`, `2026-06`, `2026`).

    A day implies its month and year, a month implies its year — so a question about June
    still matches a claim dated the 12th. A bare month (`6月`, `June`) is read in `as_of`'s
    year when one is given, which is the only calendar assumption this module makes."""
    keys: set[str] = set()

    def add_day(year: int, month: int, day: int) -> None:
        if 1 <= month <= 12 and 1 <= day <= 31:
            keys.add(f"{year:04d}-{month:02d}-{day:02d}")
            add_month(year, month)

    def add_month(year: int, month: int) -> None:
        if 1 <= month <= 12:
            keys.add(f"{year:04d}-{month:02d}")
            keys.add(f"{year:04d}")

    body = unicodedata.normalize("NFKC", text or "")
    for match in _ISO_DAY_RE.finditer(body):
        add_day(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    for match in _ISO_MONTH_RE.finditer(body):
        add_month(int(match.group(1)), int(match.group(2)))
    for match in _CN_DATE_RE.finditer(body):
        year = int(match.group(1))
        if match.group(3):
            add_day(year, int(match.group(2)), int(match.group(3)))
        elif match.group(2):
            add_month(year, int(match.group(2)))
        else:
            keys.add(f"{year:04d}")
    for match in _YEAR_RE.finditer(body):
        keys.add(match.group(1))
    if as_of is not None:
        for match in _CN_MONTH_RE.finditer(body):
            add_month(as_of.year, int(match.group(1)))
        for word in re.findall(r"[a-zA-Z]+", body.casefold()):
            if word in _MONTH_NAMES:
                add_month(as_of.year, _MONTH_NAMES[word])
    return keys


def _time_bonus(question_keys: set[str], candidate_keys: set[str]) -> float:
    if not question_keys or not candidate_keys:
        return 0.0
    shared = question_keys & candidate_keys
    if not shared:
        return 0.0
    if any(len(key) == 10 for key in shared):
        return DAY_BONUS
    if any(len(key) == 7 for key in shared):
        return MONTH_BONUS
    return YEAR_BONUS


def _overlap(question_tokens: Sequence[str], candidate: str) -> float:
    if not question_tokens:
        return 0.0
    wanted = set(question_tokens)
    have = set(tokenize(candidate))
    return len(wanted & have) / len(wanted)


def _label_term(labels: Sequence[str]) -> float:
    term = 0.0
    if "current" in labels:
        term += CURRENT_BONUS
    if "superseded" in labels:
        term -= SUPERSEDED_PENALTY
    return term


def _claim_text(claim: "RetrievedClaim") -> str:
    return " ".join((*(claim.section_path or ()), claim.text))


def _candidate_days(text: str, citations: Sequence, source_days: Mapping[str, str] | None) -> str:
    """Everything dated about one candidate, as one string the date reader can scan: the
    days its citations resolve to (when the caller knows them) plus its own text."""
    parts = [text]
    if source_days:
        parts.extend(
            source_days.get(str(getattr(c, "source_id", "")), "") for c in citations or ()
        )
    return " ".join(p for p in parts if p)


def _normalized(scores: Sequence[float]) -> list[float]:
    """Min-max into [0, 1]; an all-equal list becomes all-1.0 (no signal, no reordering)."""
    if not scores:
        return []
    low, high = min(scores), max(scores)
    if high - low < 1e-12:
        return [1.0 for _ in scores]
    return [(s - low) / (high - low) for s in scores]


@dataclass(frozen=True)
class RankedCandidates:
    """One path's candidates in relevance order, each carrying its score in `.score`."""

    claims: tuple["RetrievedClaim", ...] = ()
    windows: tuple["RecallHit", ...] = ()


def rank_candidates(
    question: str,
    claims: Sequence["RetrievedClaim"],
    windows: Sequence["RecallHit"],
    *,
    as_of: datetime | None = None,
    reranker_scores: Sequence[float] | None = None,
    source_days: Mapping[str, str] | None = None,
) -> RankedCandidates:
    """Order one path's exact results against the question (see the module docstring).

    `reranker_scores`, when given, is one score per candidate in `[*claims, *windows]`
    order; it replaces the lexical overlap term and is min-max normalized here. Anything
    else — labels, time proximity, the path's own order — behaves identically in both
    regimes, so a reranker outage changes the ranking's sharpness, never its rules."""

    question_tokens = tokenize(question)
    question_days = date_keys(question, as_of=as_of)
    total = len(claims) + len(windows)
    supplied: list[float] | None = None
    if reranker_scores is not None and len(reranker_scores) == total:
        supplied = _normalized(list(reranker_scores))

    def relevance(position: int, text: str) -> float:
        if supplied is not None:
            return supplied[position]
        return _overlap(question_tokens, text)

    scored_claims: list[tuple[float, int, "RetrievedClaim"]] = []
    for index, claim in enumerate(claims):
        text = _claim_text(claim)
        score = (
            relevance(index, text)
            + _label_term(claim.labels)
            + _time_bonus(
                question_days,
                date_keys(
                    _candidate_days(text, claim.citations, source_days), as_of=as_of
                ),
            )
        )
        scored_claims.append((score, index, claim))

    scored_windows: list[tuple[float, int, "RecallHit"]] = []
    for index, window in enumerate(windows):
        day = (source_days or {}).get(str(window.source_id), "")
        score = relevance(len(claims) + index, window.text) + _time_bonus(
            question_days, date_keys(f"{window.text} {day}", as_of=as_of)
        )
        scored_windows.append((score, index, window))

    scored_claims.sort(key=lambda row: (-row[0], row[1]))
    scored_windows.sort(key=lambda row: (-row[0], row[1]))
    return RankedCandidates(
        claims=tuple(replace(c, score=score) for score, _, c in scored_claims),
        windows=tuple(replace(w, score=score) for score, _, w in scored_windows),
    )


# ------------------------------------------------------------------------ group labels


def claim_group(claim: "RetrievedClaim") -> str:
    """What a dropped claim belongs to, for the "not shown" line: its section, else its
    document."""
    return " › ".join(claim.section_path) if claim.section_path else claim.document_path


def window_group(window: "RecallHit") -> str:
    """The same for a window: the calendar day its first line leads with when it has one
    (every time-component span does), else the source it came from."""
    head = (window.text or "").splitlines()[0] if window.text else ""
    match = _ISO_DAY_RE.match(head.strip())
    if match:
        return match.group(0)
    return str(window.source_id)


# ------------------------------------------------------------------------ the cap


@dataclass(frozen=True)
class CappedCandidates:
    """What one path contributes after its declared cap is spent on the ORDERED results."""

    claims: tuple["RetrievedClaim", ...] = ()
    windows: tuple["RecallHit", ...] = ()
    dropped: int = 0
    #: `(group, count)` per section (claims) or day/source (windows), most relevant group
    #: first — what was omitted, described rather than merely counted.
    dropped_summary: tuple[tuple[str, int], ...] = ()


def _summarize(
    claims: Sequence["RetrievedClaim"], windows: Sequence["RecallHit"]
) -> tuple[tuple[str, int], ...]:
    counts: dict[str, int] = {}
    for claim in claims:
        counts[claim_group(claim)] = counts.get(claim_group(claim), 0) + 1
    for window in windows:
        counts[window_group(window)] = counts.get(window_group(window), 0) + 1
    return tuple(counts.items())


def apply_cap(ranked: RankedCandidates, cap: int) -> CappedCandidates:
    """Spend `cap` items across claims and windows by relevance, under two floors.

    1. **Window floor** — one window is reserved whenever the path returned any, so a face
       that is mostly claims never loses its verbatim material entirely.
    2. **Section floor** — the top-scoring claim of every distinct section survives before
       any section gets a second slot (highest-scoring sections first when the cap cannot
       hold them all), so a page section never vanishes without a trace.
    3. The rest of the cap fills by interleaved score across both kinds — never a fixed
       split, which is what made `timespan` return a fixed six claims and six spans.
    """
    claims, windows = list(ranked.claims), list(ranked.windows)
    cap = max(int(cap), 0)
    if cap <= 0:
        return CappedCandidates(
            dropped=len(claims) + len(windows),
            dropped_summary=_summarize(claims, windows),
        )

    chosen: list[tuple[str, int]] = []

    def take(item: tuple[str, int]) -> None:
        if item not in chosen and len(chosen) < cap:
            chosen.append(item)

    if windows:
        take(("window", 0))
    seen_sections: set[str] = set()
    for index, claim in enumerate(claims):
        group = claim_group(claim)
        if group in seen_sections:
            continue
        seen_sections.add(group)
        take(("claim", index))
    merged = sorted(
        [("claim", i, c.score) for i, c in enumerate(claims)]
        + [("window", i, w.score) for i, w in enumerate(windows)],
        key=lambda row: (-row[2], row[0] != "claim", row[1]),
    )
    for kind, index, _score in merged:
        take((kind, index))

    claim_slots = sorted(i for kind, i in chosen if kind == "claim")
    window_slots = sorted(i for kind, i in chosen if kind == "window")
    kept_claims = [claims[i] for i in claim_slots]
    kept_windows = [windows[i] for i in window_slots]
    dropped_claims = [c for i, c in enumerate(claims) if i not in set(claim_slots)]
    dropped_windows = [w for i, w in enumerate(windows) if i not in set(window_slots)]
    return CappedCandidates(
        claims=tuple(kept_claims),
        windows=tuple(kept_windows),
        dropped=len(dropped_claims) + len(dropped_windows),
        dropped_summary=_summarize(dropped_claims, dropped_windows),
    )


# ------------------------------------------------------------------------ window cuts


def truncate_window(window: "RecallHit", limit: int) -> tuple["RecallHit", tuple[int, int] | None]:
    """Cut one over-long window at a BLOCK boundary; return it with the omitted block range.

    A window's text is its blocks joined by newlines, sometimes under one label line, so
    lines map to blocks whenever `len(lines) - block_count` is 0 or 1 (no block carries an
    internal newline). Under that alignment the cut is exact and the omitted range is real
    (`¶12-25 not shown`). Without it the text is cut at the last whole line that fits and
    no block range is claimed — a truncation that cannot be stated precisely is stated
    vaguely, never invented.
    """
    text = window.text or ""
    if limit <= 0 or len(text) <= limit:
        return window, None
    lines = text.splitlines()
    blocks = window.block_end - window.block_start + 1
    offset = len(lines) - blocks  # 0 = pure blocks, 1 = one label line on top
    kept: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > limit and kept:
            break
        kept.append(line)
        used += len(line) + 1
    body = "\n".join(kept)
    if len(body) > limit:
        # One line longer than the whole allowance: cut inside it and claim no block range —
        # a partial block is not a block boundary.
        return replace(window, text=body[:limit]), None
    cut = replace(window, text=body)
    if offset in (0, 1) and blocks > 0:
        kept_blocks = max(len(kept) - offset, 0)
        if kept_blocks < blocks:
            return cut, (window.block_start + kept_blocks, window.block_end)
    return cut, None


__all__ = [
    "CURRENT_BONUS",
    "CappedCandidates",
    "DAY_BONUS",
    "MONTH_BONUS",
    "RankedCandidates",
    "SUPERSEDED_PENALTY",
    "YEAR_BONUS",
    "apply_cap",
    "claim_group",
    "date_keys",
    "rank_candidates",
    "tokenize",
    "truncate_window",
    "window_group",
]
