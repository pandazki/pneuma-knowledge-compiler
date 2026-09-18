"""The voice call's pure half: the ledger, ask formation, and what a voice may be handed.

Keyless throughout — the only model here is a fake whose `with_structured_output` returns
scripted envelopes, and everything else is a list of strings. Each test states one rule the
delegate keeps; the rules exist because the provider's delegation event carries no question
text, so the transcript, the vocabulary and the chunking are the whole input to retrieval.

All names are invented: the Ferry Scheduling Rebuild, Harbour Quay Notes and the people in
them are synthetic fixtures, not anybody's library.
"""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from pneuma_knowledge_core.prompts import prompt
from pneuma_knowledge_core.recall.call import (
    OWNER,
    ROW_GAP_MS,
    VOICE,
    Ask,
    AskDecision,
    Exchange,
    Ledger,
    SpokenChunker,
    ask_contract,
    ask_messages,
    form_ask,
    speakable,
    vocabulary_of,
)

OWNER_LABEL = prompt("call.ask.label.owner")
VOICE_LABEL = prompt("call.ask.label.voice")


# ── fakes ──────────────────────────────────────────────────────────────────────────────────


class FakeAskModel:
    """Stands in for `model.with_structured_output(AskDecision, include_raw=True)`.

    Returns the scripted `include_raw` envelopes in order, records every message list it was
    handed, and can be told to sleep or to raise instead — the three ways a helper call fails
    in production."""

    def __init__(
        self,
        envelopes: list | None = None,
        *,
        delay: float = 0.0,
        raises: BaseException | None = None,
    ) -> None:
        self._envelopes = list(envelopes or [])
        self._delay = delay
        self._raises = raises
        self.calls: list[list] = []
        self.schemas: list = []
        self.include_raw: list[bool] = []

    def with_structured_output(self, schema, *, include_raw: bool = False):  # noqa: ANN001
        self.schemas.append(schema)
        self.include_raw.append(include_raw)
        outer = self

        class _Runnable:
            async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                outer.calls.append(messages)
                if outer._delay:
                    await asyncio.sleep(outer._delay)
                if outer._raises is not None:
                    raise outer._raises
                return outer._envelopes.pop(0)

        return _Runnable()


def envelope(decision, *, usage: dict | None = None) -> dict:
    raw = AIMessage(content="", usage_metadata=usage) if usage else AIMessage(content="")
    return {"raw": raw, "parsed": decision, "parsing_error": None}


def ledger_of(*fragments) -> Ledger:
    """`(speaker, text, start_ms, end_ms)` tuples → a Ledger, in arrival order."""
    ledger = Ledger()
    for speaker, text, start_ms, end_ms in fragments:
        ledger.add(speaker, text, start_ms, end_ms)
    return ledger


# ── the ledger: what was heard, grouped the way a reader reads it ──────────────────────────


def test_two_fragments_of_one_speaker_inside_the_row_gap_are_one_row():
    ledger = ledger_of(
        (OWNER, "the ferry scheduling ", 0, 900),
        (OWNER, "rebuild", 900 + ROW_GAP_MS, 2600),
    )
    rows = ledger.rows()
    assert len(rows) == 1
    assert rows[0].text == "the ferry scheduling rebuild"
    assert (rows[0].start_ms, rows[0].end_ms) == (0, 2600)


def test_a_silence_longer_than_the_row_gap_starts_a_new_row():
    """A row is a display-and-context grouping, so the only thing that may end one is a gap:
    the provider states no turn boundary at all."""
    ledger = ledger_of(
        (OWNER, "the ferry scheduling rebuild", 0, 900),
        (OWNER, "how far did it get", 900 + ROW_GAP_MS + 1, 2600),
    )
    rows = ledger.rows()
    assert [row.text for row in rows] == ["the ferry scheduling rebuild", "how far did it get"]


def test_a_backchannel_from_the_voice_does_not_split_the_owners_sentence():
    """The two speakers group INDEPENDENTLY. A full-duplex call overlaps constantly, and a
    listening sound from one side arriving mid-sentence must not cut the other's line in two —
    ask formation would then read half a question."""
    ledger = ledger_of(
        (OWNER, "about the ferry scheduling rebuild, ", 0, 1000),
        (VOICE, "mm-hm", 1100, 1300),
        (OWNER, "how far did it get?", 1400, 2600),
    )
    rows = ledger.rows()
    assert [(row.speaker, row.text) for row in rows] == [
        (OWNER, "about the ferry scheduling rebuild, how far did it get?"),
        (VOICE, "mm-hm"),
    ]


def test_a_rows_text_is_its_fragments_concatenated_byte_for_byte():
    """Nothing is trimmed and nothing is inserted: the provider's deltas carry their own
    spacing, and a recognizer's repeated word is part of what was heard."""
    parts = ["  the ferry  ", "scheduling", " rebuild,", " the ", "the rebuild"]
    ledger = ledger_of(*[(OWNER, part, index * 10, index * 10 + 5) for index, part in enumerate(parts)])
    assert ledger.rows()[0].text == "".join(parts)


def test_a_fragment_with_no_text_is_not_recorded_at_all():
    ledger = ledger_of((OWNER, "", 0, 10), (OWNER, "the quay notes", 20, 900))
    assert len(ledger.fragments) == 1


def test_rows_are_ordered_by_when_each_line_began():
    ledger = ledger_of(
        (VOICE, "hello, what would you like to look up?", 0, 1500),
        (OWNER, "the harbour quay notes", 1700, 2600),
        (VOICE, "looking", 2800, 3200),
    )
    assert [row.start_ms for row in ledger.rows()] == [0, 1700, 2800]
    assert [row.speaker for row in ledger.rows()] == [VOICE, OWNER, VOICE]


def test_two_lines_that_began_at_the_same_moment_read_with_the_owner_first():
    ledger = ledger_of((VOICE, "mm-hm", 500, 700), (OWNER, "and the second point", 500, 1800))
    assert [row.speaker for row in ledger.rows()] == [OWNER, VOICE]


def test_the_tail_labels_every_line_with_who_spoke_and_reads_oldest_first():
    ledger = ledger_of(
        (OWNER, "how far did the ferry scheduling rebuild get?", 0, 2000),
        (VOICE, "three things landed this week.", 2200, 4000),
        (OWNER, "and the second one?", 4200, 5200),
    )
    assert ledger.tail() == (
        f"{OWNER_LABEL}: how far did the ferry scheduling rebuild get?\n"
        f"{VOICE_LABEL}: three things landed this week.\n"
        f"{OWNER_LABEL}: and the second one?"
    )


def test_the_tail_drops_the_oldest_lines_to_stay_inside_its_budget():
    ledger = ledger_of(
        (OWNER, "x" * 60, 0, 1000),
        (VOICE, "y" * 60, 4000, 6000),
        (OWNER, "z" * 60, 9000, 11000),
    )
    tail = ledger.tail(max_chars=140)
    assert tail.count("\n") == 1
    assert tail.startswith(f"{VOICE_LABEL}: yyy")
    assert tail.endswith("z" * 60)


def test_the_tail_keeps_the_newest_line_even_when_it_alone_exceeds_the_budget():
    """A budget that could return nothing would leave ask formation with no transcript, which
    is the one input it cannot do without."""
    ledger = ledger_of((OWNER, "q" * 400, 0, 9000))
    assert ledger.tail(max_chars=50).endswith("q" * 400)


def test_owner_last_words_are_what_the_owner_said_since_the_voice_last_spoke():
    ledger = ledger_of(
        (OWNER, "how far did the ferry scheduling rebuild get?", 0, 2000),
        (VOICE, "three things landed this week.", 2200, 4000),
        (OWNER, "and the second one?", 4200, 5200),
    )
    assert ledger.owner_last_words() == "and the second one?"


def test_owner_last_words_span_every_owner_line_that_no_voice_line_separates():
    ledger = ledger_of(
        (VOICE, "go ahead.", 0, 800),
        (OWNER, "the quay notes,", 1000, 2000),
        (OWNER, "what did we decide about the ramp?", 2000 + ROW_GAP_MS + 1, 4000),
    )
    assert ledger.owner_last_words() == "the quay notes, what did we decide about the ramp?"


def test_owner_last_words_are_empty_when_the_owner_has_not_spoken_since():
    ledger = ledger_of((VOICE, "hello there.", 0, 900))
    assert ledger.owner_last_words() == ""


# ── the vocabulary: the words a recognizer gets wrong ──────────────────────────────────────


def test_titles_that_share_words_with_what_was_heard_come_first():
    """A misheard name usually keeps most of its words, so those words choose what is shown —
    a cut in path order drops the very page being asked about as often as not."""
    titles = ["Harbour Quay Notes", "Lantern Depot Roster", "Ferry Scheduling Rebuild"]
    listed = vocabulary_of(titles, heard="how far did the ferry scheduling rebuild get").split("\n")
    assert listed[0] == "- Ferry Scheduling Rebuild"
    assert set(listed) == {f"- {title}" for title in titles}


def test_with_nothing_heard_the_titles_keep_the_order_they_were_given_in():
    titles = ["Harbour Quay Notes", "Lantern Depot Roster", "Ferry Scheduling Rebuild"]
    assert vocabulary_of(titles) == "\n".join(f"- {title}" for title in titles)


def test_a_title_listed_twice_is_shown_once():
    listed = vocabulary_of(["Harbour Quay Notes", "Harbour Quay Notes  ", "Lantern Depot Roster"])
    assert listed == "- Harbour Quay Notes\n- Lantern Depot Roster"


def test_the_vocabulary_stays_inside_its_budget_and_never_cuts_a_title_in_half():
    """Half a title is worse than no title: it is a name the model may repair TOWARDS."""
    titles = ["Ferry Scheduling Rebuild", "Harbour Quay Notes", "Lantern Depot Roster"]
    listed = vocabulary_of(titles, max_chars=30).split("\n")
    assert all(line.removeprefix("- ") in titles for line in listed)
    assert sum(len(line.removeprefix("- ")) for line in listed) <= 30


# ── speakable: what a voice may be handed ──────────────────────────────────────────────────


def test_a_citation_marker_is_never_handed_to_a_voice():
    """The screen carries the answer with every marker resolved; a voice handed
    `[cite: s3 ¶4-9]` reads it out loud."""
    assert speakable("The ramp was widened [cite: s3 ¶4-9].") == "The ramp was widened."


def test_emphasis_headings_bullets_and_backticks_leave_and_the_sentence_survives():
    said = speakable("## Decision\n- **Ferry** scheduling moved to `weekly` batches.")
    assert said == "Decision Ferry scheduling moved to weekly batches."


def test_a_link_is_spoken_as_its_text_and_never_as_its_address():
    said = speakable("See [the quay notes](https://example.invalid/quay) for the ramp decision.")
    assert said == "See the quay notes for the ramp decision."


def test_line_breaks_become_spaces_so_one_hand_over_is_one_line():
    assert speakable("First line.\n\nSecond line.") == "First line. Second line."


# ── the spoken chunker: token deltas → hand-overs ──────────────────────────────────────────


def test_a_preamble_waits_for_the_facts_it_introduces():
    chunker = SpokenChunker()
    assert chunker.feed("这两天你主要做了三类工作：") == []
    assert chunker.feed("渡口排班重写、码头扩建、航线调整。") == [
        "这两天你主要做了三类工作：渡口排班重写、码头扩建、航线调整。"
    ]


def test_short_follow_on_sentences_do_not_wait_for_the_end_of_generation():
    chunker = SpokenChunker()
    assert chunker.feed("渡口排班重写已经做完了。") == ["渡口排班重写已经做完了。"]
    assert chunker.feed("码头扩建还没开始。") == ["码头扩建还没开始。"]


def test_a_bracket_still_open_holds_the_release_back():
    """A citation marker cut in half would be spoken as its first half."""
    chunker = SpokenChunker()
    assert chunker.feed("The ramp was widened [cite: s3 ") == []
    assert chunker.feed("¶4-9]. ") == ["The ramp was widened."]


def test_flush_emits_the_tail_that_never_finished_a_sentence():
    chunker = SpokenChunker()
    assert chunker.feed("排班重写做完了") == []
    assert chunker.flush() == ["排班重写做完了"]


def test_flush_emits_nothing_when_nothing_is_pending():
    chunker = SpokenChunker()
    assert chunker.feed("渡口排班重写已经做完了。") == ["渡口排班重写已经做完了。"]
    assert chunker.flush() == []


def test_an_over_long_chunk_is_split_so_no_hand_over_exceeds_the_providers_bound():
    chunker = SpokenChunker(max_chars=20)
    chunks = chunker.feed("x" * 45 + "。")
    assert [len(chunk) for chunk in chunks] == [20, 20, 6]
    assert "".join(chunks) == "x" * 45 + "。"


# ── ask formation: the transcript's tail → one standalone question ─────────────────────────


def asking_ledger() -> Ledger:
    return ledger_of(
        (VOICE, "three things landed this week.", 0, 2000),
        (OWNER, "and what came of the second one?", 2200, 4000),
    )


async def test_a_model_that_is_ready_gives_the_question_it_wrote():
    model = FakeAskModel(
        [envelope(AskDecision(ready=True, question="  What came of the ferry  ramp decision? "))]
    )
    ask = await form_ask(model, asking_ledger())
    assert ask.question == "What came of the ferry ramp decision?"
    assert ask.ready is True
    assert ask.clarify == "" and ask.degraded is None


async def test_a_model_that_is_not_ready_gives_a_clarify_and_no_question():
    """`ready=False` is a judgement, not a failure: the voice asks the owner instead of the
    library, and retrieval is never run on a question nobody established."""
    model = FakeAskModel(
        [envelope(AskDecision(ready=False, clarify="Which of the three do you mean?"))]
    )
    ask = await form_ask(model, asking_ledger())
    assert ask.ready is False
    assert ask.question == ""
    assert ask.clarify == "Which of the three do you mean?"
    assert ask.degraded is None


async def test_a_ready_model_with_an_empty_question_is_treated_as_not_ready():
    model = FakeAskModel([envelope(AskDecision(ready=True, question="   ", clarify="About what?"))])
    ask = await form_ask(model, asking_ledger())
    assert ask.ready is False and ask.clarify == "About what?"


async def test_a_timeout_degrades_to_the_owners_own_last_words():
    """A helper call that failed must never silence the delegate: the owner's own words are a
    worse question than a formed one, and they are still the owner's."""
    model = FakeAskModel([envelope(AskDecision(ready=True, question="never arrives"))], delay=0.5)
    ask = await form_ask(model, asking_ledger(), timeout=0.01)
    assert ask.question == "and what came of the second one?"
    assert ask.degraded == "timeout"


async def test_a_provider_exception_degrades_to_the_owners_own_last_words():
    model = FakeAskModel(raises=RuntimeError("the provider hung up"))
    ask = await form_ask(model, asking_ledger())
    assert ask.question == "and what came of the second one?"
    assert ask.degraded == "error"


async def test_with_no_model_at_all_the_owners_own_words_are_the_ask():
    ask = await form_ask(None, asking_ledger())
    assert ask.question == "and what came of the second one?"
    assert ask.degraded == "no model"


async def test_a_model_that_answers_off_schema_degrades_instead_of_raising():
    """A model that writes prose instead of the structured object returns `parsed=None`; that
    is the commonest failure of structured output and it arrives as a value, not an error."""
    model = FakeAskModel([envelope(None)])
    ask = await form_ask(model, asking_ledger())
    assert ask.question == "and what came of the second one?"
    assert ask.degraded == "error"


async def test_a_model_that_returns_something_else_entirely_still_degrades():
    class _Whatever:
        def with_structured_output(self, schema, **kwargs):  # noqa: ANN001, ARG002
            class _Runnable:
                async def ainvoke(self, messages, config=None):  # noqa: ANN001, ARG002
                    return "a bare string, from an adapter that does not use include_raw"

            return _Runnable()

    ask = await form_ask(_Whatever(), asking_ledger())
    assert ask.question == "and what came of the second one?"
    assert ask.degraded == "error"


@pytest.mark.parametrize(
    "model",
    [
        None,
        FakeAskModel(raises=RuntimeError("down")),
        FakeAskModel([envelope(None)]),
    ],
)
async def test_no_failure_of_ask_formation_ever_reaches_the_caller_as_an_exception(model):
    ask = await form_ask(model, asking_ledger(), timeout=0.05)
    assert isinstance(ask, Ask)


async def test_the_token_usage_of_the_formation_call_is_carried_on_the_ask():
    model = FakeAskModel(
        [
            envelope(
                AskDecision(ready=True, question="What came of the ramp decision?"),
                usage={"input_tokens": 120, "output_tokens": 8, "total_tokens": 128},
            )
        ]
    )
    ask = await form_ask(model, asking_ledger())
    assert ask.token_usage["input_tokens"] == 120
    assert ask.token_usage["total_tokens"] == 128


async def test_ask_formation_asks_for_the_structured_decision_with_the_raw_response():
    model = FakeAskModel([envelope(AskDecision(ready=True, question="What about the ramp?"))])
    await form_ask(model, asking_ledger())
    assert model.schemas == [AskDecision]
    assert model.include_raw == [True]


def test_everything_volatile_rides_the_human_turn_so_the_contract_bytes_are_stable():
    """I5: the System message is byte-stable, and the transcript, the vocabulary and this
    call's earlier asks are all per-call."""
    messages = ask_messages(
        f"{OWNER_LABEL}: and the second one?",
        earlier=[Exchange(question="What landed this week?", said="Three things landed.")],
        vocabulary="- Ferry Scheduling Rebuild",
    )
    system, human = messages
    assert isinstance(system, SystemMessage) and isinstance(human, HumanMessage)
    assert system.content == ask_contract()
    for volatile in ("and the second one?", "Ferry Scheduling Rebuild", "What landed this week?"):
        assert volatile in human.content
        assert volatile not in system.content


def test_with_no_vocabulary_and_no_earlier_asks_the_human_turn_says_so():
    human = ask_messages("Owner: hello")[1]
    assert human.content.count(prompt("call.ask.none")) == 2


@pytest.mark.parametrize("text", ["𠀀" * 300, "🛳️" * 200, "港" * 420])
def test_append_size_is_bounded_in_bytes_even_for_multibyte_text(text):
    chunks = SpokenChunker().feed(text + "。")
    assert "".join(chunks) == text + "。"
    assert all(len(chunk.encode("utf-8")) <= 480 for chunk in chunks)


def test_unclosed_citation_is_never_read_aloud_even_at_successful_stream_end():
    assert speakable("The ramp opened [cite: s01 ¶") == "The ramp opened"
