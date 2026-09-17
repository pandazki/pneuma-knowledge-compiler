"""The voice call's delegate: what the library does when a live voice asks it for help.

WHY THIS EXISTS
---------------
A full-duplex voice model conducts the conversation — it listens and speaks at once, and it
is good at that and at nothing else the library cares about: it knows none of the library's
content, its context is small, and it will happily improvise. So the call is split the way
its provider splits it (docs/design/voice-call.md): the voice is a mouth and ears, and
everything the library knows reaches it through a **delegate** that this framework runs —
the ordinary fast lane, in a posture built for speech.

The provider's delegation event carries NO task text: it says *that* the voice wants help
and *when* on the session timeline, never *what about*. Three things therefore have to
happen here before any retrieval can, and each is a pure function of what the call has
heard so far:

* the **ledger** keeps both speakers' transcript fragments on the session timeline, because
  the question is in there and nowhere else;
* **ask formation** turns the ledger's tail into the one standalone question the owner wants
  looked up — resolving "the second point", applying the owner's latest correction,
  repairing a misheard page title against the library's own vocabulary — or says the
  transcript does not establish one yet;
* the **spoken chunker** turns the answering model's token stream into a few speakable
  hand-overs: citations and markup stripped (the screen carries them, a voice cannot), the
  first sentence released the moment it is complete so the owner is not waiting on the last.

Nothing in this module speaks to a provider or touches an index. The service runs the
session; this is the part that can be tested with a list of strings.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No "quiet notes" for follow-ups. The provider offers a channel for context the voice should
hold but not say; measured against the real model, anything put there beside a result was
spoken — label and all — and a voice holding half-remembered detail answered a follow-up
from its own imagination instead of asking again. The delegate hands over what is to be
said and nothing else, and a follow-up is a new ask.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from ..prompts import prompt
from .citation_alias import strip_citations
from .fast import extract_usage, invoke_config, zero_usage

__all__ = [
    "OWNER",
    "VOICE",
    "Ask",
    "AskDecision",
    "Exchange",
    "Fragment",
    "Ledger",
    "Row",
    "SpokenChunker",
    "ask_contract",
    "ask_messages",
    "form_ask",
    "speakable",
    "vocabulary_of",
    "voice_context",
    "voice_instructions",
]

Speaker = Literal["owner", "voice"]
OWNER: Speaker = "owner"
VOICE: Speaker = "voice"

#: Same-speaker fragments closer than this on the session timeline are one row. The
#: provider states no turn boundary (a fragment "is not a complete user turn"), so a row is a
#: display-and-context grouping, never a claim that somebody finished speaking.
ROW_GAP_MS = 1200

#: How much of the conversation ask formation reads. A follow-up needs the answer it follows
#: up on, and a correction needs what it corrects; a whole call does not fit and would bury
#: both. Characters, newest kept.
TAIL_CHARS = 1800

#: How much of the library's vocabulary ask formation is shown — page titles, the words a
#: speech recognizer most often gets wrong.
VOCABULARY_CHARS = 2400

DEFAULT_ASK_TIMEOUT_SECONDS = 6.0


# ───────────────────────────────────────────────────────────────────────── the ledger


@dataclass(frozen=True)
class Fragment:
    """One transcript delta, exactly as the provider sent it."""

    speaker: Speaker
    text: str
    start_ms: int
    end_ms: int


@dataclass(frozen=True)
class Row:
    """Consecutive fragments of one speaker, read as one line of the conversation."""

    speaker: Speaker
    text: str
    start_ms: int
    end_ms: int


@dataclass
class Ledger:
    """Both speakers' fragments on the session timeline, in arrival order.

    Text is kept byte-for-byte: the provider's fragments carry their own spacing and a
    recognizer's repeated word is part of what was heard, so nothing is trimmed and nothing
    is inserted between two of them.
    """

    fragments: list[Fragment] = field(default_factory=list)

    def add(self, speaker: Speaker, text: str, start_ms: int, end_ms: int) -> None:
        if text:
            self.fragments.append(Fragment(speaker, text, int(start_ms), int(end_ms)))

    def last_end_ms(self, speaker: Speaker) -> int | None:
        for fragment in reversed(self.fragments):
            if fragment.speaker == speaker:
                return fragment.end_ms
        return None

    def rows(self, *, gap_ms: int = ROW_GAP_MS) -> list[Row]:
        """The conversation as lines, ordered by when each line began.

        Speakers are grouped independently — they overlap in a full-duplex call, and a
        listening sound from one must not cut the other's sentence in two.
        """
        open_rows: dict[str, list[Fragment]] = {}
        done: list[list[Fragment]] = []
        for fragment in self.fragments:
            current = open_rows.get(fragment.speaker)
            if current and fragment.start_ms - current[-1].end_ms > gap_ms:
                done.append(current)
                current = None
            if current is None:
                current = []
                open_rows[fragment.speaker] = current
            current.append(fragment)
        done.extend(row for row in open_rows.values() if row)
        rows = [
            Row(
                speaker=row[0].speaker,
                text="".join(fragment.text for fragment in row),
                start_ms=row[0].start_ms,
                end_ms=row[-1].end_ms,
            )
            for row in done
        ]
        return sorted(rows, key=lambda row: (row.start_ms, row.speaker != OWNER))

    def tail(self, *, max_chars: int = TAIL_CHARS) -> str:
        """The newest rows that fit, oldest first, each labelled with who spoke."""
        labels = {OWNER: prompt("call.ask.label.owner"), VOICE: prompt("call.ask.label.voice")}
        lines: list[str] = []
        used = 0
        for row in reversed(self.rows()):
            text = " ".join(row.text.split())
            if not text:
                continue
            line = f"{labels[row.speaker]}: {text}"
            if lines and used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(reversed(lines))

    def owner_last_words(self) -> str:
        """What the owner said since the voice last finished a line — the mechanical ask."""
        rows = self.rows()
        said: list[str] = []
        for row in reversed(rows):
            if row.speaker == VOICE and said:
                break
            if row.speaker == OWNER:
                said.append(" ".join(row.text.split()))
        return " ".join(reversed(said)).strip()


# ───────────────────────────────────────────────────────────────────── ask formation


@dataclass(frozen=True)
class Exchange:
    """One earlier ask of this call and what the library handed the voice for it."""

    question: str
    said: str


class AskDecision(BaseModel):
    """Structured output of ask formation: a question, or the reason there is none yet."""

    ready: bool = Field(description="true when the transcript establishes what to look up")
    question: str = Field(default="", description="the standalone question, when ready")
    clarify: str = Field(
        default="", description="when not ready: the one short question the voice should ask"
    )


@dataclass(frozen=True)
class Ask:
    """What the delegate will look up — or, with `question` empty, what it cannot yet."""

    question: str
    clarify: str = ""
    #: None = the model wrote it; otherwise why the owner's own last words stand in.
    degraded: str | None = None
    token_usage: Mapping[str, int] = field(default_factory=zero_usage)

    @property
    def ready(self) -> bool:
        return bool(self.question)


def ask_contract() -> str:
    """The System contract of ask formation. I5: no fields, byte-stable per overlay."""
    return prompt("call.ask.contract")


def vocabulary_of(
    titles: Sequence[str], *, heard: str = "", max_chars: int = VOCABULARY_CHARS
) -> str:
    """Page titles as one bounded list — the words a recognizer gets wrong — with the titles
    that share words with what was HEARD first.

    A library outgrows any fixed budget of titles, and a cut in path order drops exactly the
    page being asked about as often as not: on a real library a four-word project name, heard
    with its first word wrong, went unrepaired because its title sat past the cut — and the
    answer was about a period instead of about that project. A misheard name usually keeps
    most of its words, so those words
    choose what is shown. Deterministic — the ranker's own tokenizer, no model — and the
    rest of the list follows in its given order while room remains.
    """
    from .component_rank import tokenize  # local: the ranker imports fast, which this sits beside

    heard_tokens = set(tokenize(heard))
    unique: dict[str, int] = {}
    for title in titles:
        title = " ".join(str(title or "").split())
        if title and title not in unique:
            unique[title] = len(heard_tokens.intersection(tokenize(title))) if heard_tokens else 0
    ordered = sorted(unique, key=lambda title: -unique[title])  # stable: ties keep their order
    lines: list[str] = []
    used = 0
    for title in ordered:
        if used + len(title) > max_chars:
            break
        lines.append(f"- {title}")
        used += len(title)
    return "\n".join(lines)


def ask_messages(
    tail: str, *, earlier: Sequence[Exchange] = (), vocabulary: str = ""
) -> list[BaseMessage]:
    """[SystemMessage(the contract), HumanMessage(vocabulary → earlier asks → transcript)].

    The transcript goes last because it is what the instruction is about, and everything
    volatile lives in the human turn so the system bytes stay cacheable (I5).
    """
    exchanges = "\n".join(
        prompt("call.ask.exchange", question=exchange.question, said=exchange.said)
        for exchange in earlier
    )
    return [
        SystemMessage(content=ask_contract()),
        HumanMessage(
            content=prompt(
                "call.ask.request",
                vocabulary=vocabulary or prompt("call.ask.none"),
                earlier=exchanges or prompt("call.ask.none"),
                transcript=tail,
            )
        ),
    ]


async def form_ask(
    model: BaseChatModel | None,
    ledger: Ledger,
    *,
    earlier: Sequence[Exchange] = (),
    vocabulary: str = "",
    timeout: float | None = DEFAULT_ASK_TIMEOUT_SECONDS,
    callbacks: list | None = None,
    trace_metadata: dict | None = None,
) -> Ask:
    """The ledger's tail → the one question to look up.

    Fail-soft toward the owner's own words: a timeout, a provider error, a model without
    structured output or no model at all degrade to what the owner said since the voice last
    spoke. That is a worse question than a formed one — a bare "the second point" retrieves
    little — but it is the owner's, and a delegate that went silent because a helper call
    failed would leave the voice with nothing to say.
    """
    fallback = ledger.owner_last_words()
    if model is None:
        return Ask(question=fallback, degraded="no model")
    messages = ask_messages(ledger.tail(), earlier=earlier, vocabulary=vocabulary)
    config = invoke_config("call.ask", callbacks, trace_metadata)
    try:
        structured = model.with_structured_output(AskDecision, include_raw=True)
        call = structured.ainvoke(messages, config=config)
        raw = await (asyncio.wait_for(call, timeout) if timeout else call)
    except asyncio.TimeoutError:
        return Ask(question=fallback, degraded="timeout")
    except Exception:  # noqa: BLE001 — a helper call never silences the delegate
        return Ask(question=fallback, degraded="error")

    usage = zero_usage()
    parsed: object = raw
    if isinstance(raw, Mapping):
        response = raw.get("raw")
        if isinstance(response, BaseMessage):
            usage = extract_usage(response)
        parsed = raw.get("parsed")
    if not isinstance(parsed, AskDecision):
        return Ask(question=fallback, degraded="error", token_usage=usage)
    question = " ".join(parsed.question.split())
    if parsed.ready and question:
        return Ask(question=question, token_usage=usage)
    return Ask(question="", clarify=" ".join(parsed.clarify.split()), token_usage=usage)


# ───────────────────────────────────────────────────────────── what is said, and how


def voice_instructions() -> str:
    """The voice model's whole standing prompt. No fields: what changes per call (the date,
    the zone) is seeded as conversation context, so these bytes are one per language."""
    return prompt("call.voice.instructions")


def voice_context(*, today: str, weekday: str, zone: str) -> str:
    """The one developer message a call starts with: what day it is, where."""
    return prompt("call.voice.context", today=today, weekday=weekday, zone=zone)


_MARKUP_RE = re.compile(r"(\*\*|__|`|^#{1,6}\s+|^\s*[-*•]\s+|^\s*\d+[.)]\s+)", re.MULTILINE)
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
#: A sentence ends at CJK or Latin terminal punctuation, or a line break. A Latin full stop
#: counts only when whitespace follows it, which is what keeps `3.5` and `v1.2` whole.
_SENTENCE_END_RE = re.compile(r"[。！？!?]+[”’」』）)]*|\.(?=\s)|\n+")
#: The FIRST hand-over may also end at a strong clause boundary. An answering model asked for
#: three sentences often writes one long one ("…三类工作：A；B；C。"), and waiting for its full
#: stop measured three and a half seconds of silence that "这两天你主要做了三类工作：" ends at
#: the first second of. The voice says the clause and the rest arrives while it is speaking.
_CLAUSE_END_RE = re.compile(r"[。！？!?]+[”’」』）)]*|\.(?=\s)|\n+|[：；;]|:(?=\s)")


def speakable(text: str) -> str:
    """Answer text → what a voice can be handed: no citations, no markup, one line.

    The citations are not lost — the card on screen carries the answer with every marker
    resolved. A voice that was handed `[cite: s3 ¶4-9]` reads it out.
    """
    text = strip_citations(text)
    text = _LINK_RE.sub(r"\1", text)
    text = _MARKUP_RE.sub("", text)
    return " ".join(text.split())


@dataclass
class SpokenChunker:
    """Token deltas in, speakable hand-overs out.

    `feed` is synchronous and cheap on purpose: it is called from inside the answering
    call's streaming loop (`TokenSink` must not block), and returns the chunks that became
    complete with this delta. The FIRST chunk is released at the first finished sentence —
    time to the first useful spoken word is what the owner experiences — and later ones are
    coalesced, because every hand-over is a point where the voice may re-phrase.

    A sentence is never released while a `[` stands open in the pending text: a citation
    marker cut in half would otherwise be spoken as its first half.
    """

    first_min_chars: int = 8
    later_min_chars: int = 40
    #: The provider bounds one hand-over at 500 tokens. Characters are the conservative
    #: proxy that needs no tokenizer: CJK runs near one token a character.
    max_chars: int = 420
    _pending: str = ""
    _emitted: int = 0

    def feed(self, delta: str) -> list[str]:
        self._pending += delta
        return self._release(final=False)

    def flush(self) -> list[str]:
        return self._release(final=True)

    def _release(self, *, final: bool) -> list[str]:
        chunks: list[str] = []
        while True:
            cut = self._cut(final=final)
            if cut is None:
                break
            raw, self._pending = self._pending[:cut], self._pending[cut:]
            text = speakable(raw)
            if not text:
                continue
            for start in range(0, len(text), self.max_chars):
                chunks.append(text[start : start + self.max_chars])
                self._emitted += 1
        return chunks

    def _cut(self, *, final: bool) -> int | None:
        pending = self._pending
        if final:
            return len(pending) if pending.strip() else None
        first = self._emitted == 0
        need = self.first_min_chars if first else self.later_min_chars
        for match in (_CLAUSE_END_RE if first else _SENTENCE_END_RE).finditer(pending):
            end = match.end()
            head = pending[:end]
            if head.count("[") > head.count("]"):
                continue
            if len(speakable(head)) >= need:
                return end
        return None
