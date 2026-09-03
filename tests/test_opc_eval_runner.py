"""The OPC eval runner's machinery, guarded keylessly — no stack, no model, no network.

Three properties live here, and none of them needs a library: the run's determinism under
concurrency, what the two judges are handed, and what a reconciliation may claim.

The runner asks ~83 questions through the example API and sends every facet of every answer to
an LLM judge. Those calls run under a bounded concurrency (`--concurrency`, default 32), which
buys wall clock and costs the one thing a regression line cannot afford: if a row's place in the
artifact depended on when its call came back, two runs of the same build would write different
bytes and no diff between them would mean anything.

So the ordering is a mechanism, not a hope — `asyncio.gather` returns results in SUBMISSION
order — and this file holds it to that with stub answerers and a stub judge that finish in
deliberately scrambled order. The stubs are the point: the property is about assembly, so it can
be checked without a library, a key or a socket.

The retry guards are here for the same reason. A transient provider failure has to cost a retry
and not a run; a permanent one (a bad credential) has to fail immediately rather than be
multiplied by the bound; and a call that exhausts its attempts has to stop the run naming the
case that made it, never be dropped into a row that looks like a wrong answer.

The grading guards are the same kind of claim about a different part of the ruler. A fabrication
verdict must be reached with the answer's own cited L0 text in front of the judge, an answer that
asserts the absence the case declares must not be read as inventing it, a facet's illustrations
must reach the judge as illustrations rather than as the thing to entail, a false premise must get
its own verdict rather than be folded into the fabrication count, and a reconciliation section must
file a moved case under the ruler revision the truth set says touched it — so that a change in the
measurement can never be read as a change in the library.

The calibration guards are the last group, and they are about the ruler certifying itself. The
judge's calibration suite (`--mode judge`) only means anything while it runs through the SAME
prompts the scoring runs through, so the two paths are held to sending identical bytes; and its
blocking rule has to cut both ways — a blocking variant's disagreement stops the run, a
non-blocking one is reported and does not. All keyless: stub judges, hand-built suites.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "opc"
RUNNER = EXAMPLE / "eval" / "run_eval.py"
TRUTH_PATH = EXAMPLE / "eval" / "opc-truth.json"


def _load_runner():
    """Import `run_eval.py` by path: it is a script inside an example, not a package module."""
    spec = importlib.util.spec_from_file_location("opc_run_eval", RUNNER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def ev():
    return _load_runner()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(TRUTH_PATH.read_text(encoding="utf-8"))


def _digest(text: str) -> int:
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


class ScrambledAnswers:
    """An answerer whose calls finish in an order unrelated to the order they were made.

    The delay is derived from the question, so the scrambling is the same on every run and this
    test cannot pass or fail by luck; what it is not derived from is the position of the case in
    the truth set, which is precisely the order the artifact has to come back in.
    """

    def __init__(self, lane: str, *, gate, completions: list[str]) -> None:
        self.lane = lane
        self.gate = gate
        self.completions = completions
        self.asked: list[str] = []

    async def ask(self, question: str, as_of: str | None = None, *, label: str = "") -> dict:
        self.asked.append(label)

        async def call() -> dict:
            await asyncio.sleep((_digest(question) % 17) * 0.002)
            self.completions.append(label)
            return {
                "answer": f"[{self.lane}] {question[:24]} — stub answer with [cite: s01]",
                "answer_kind": "no_record" if _digest(question) % 4 == 0 else "grounded",
                "citation_handles": {"s01": "0" * 32},
                "used_claims": [
                    {
                        "document_path": f"stub/{self.lane}.md",
                        "citations": [{"source_id": "0" * 32}],
                    }
                ],
            }

        # Through the gate, exactly as the real answerer goes: the bound and the tally are what
        # this test is about, so a stub that stepped around them would measure nothing.
        return await self.gate.run(call, label=label)


class ScrambledJudge:
    """A judge whose verdict is a function of the prompt and whose latency is scrambled."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, messages):
        human = messages[1][1]
        seed = _digest(human)
        self.calls += 1
        await asyncio.sleep((seed % 13) * 0.002)
        if "does NOT contain" in human:
            head = "yes" if seed % 3 == 0 else "no"
        else:
            head = ("stated", "omitted", "contradicted")[seed % 3]
        return SimpleNamespace(content=f"{head}\nstub rationale {seed % 97}")


def _score(ev, manifest, concurrency: int) -> tuple[dict, dict, list[str], object]:
    """Score both answered arms against the stubs at one bound, and report what happened."""
    completions: list[str] = []
    gate = ev.CallGate(concurrency)
    answers = {
        lane: ScrambledAnswers(lane, gate=gate, completions=completions) for lane in ev.LANES
    }
    judge = ScrambledJudge()
    positive, negatives = asyncio.run(ev.score_answered_arms(manifest, answers, judge, gate))
    return positive, negatives, completions, gate


def _report(ev, manifest, positive: dict, negatives: dict) -> str:
    """Render the artifact the way `run()` does, so the assertion is over shipped bytes."""
    suite = ev.summarize(
        positive,
        ev.case_categories(manifest),
        negatives,
        {"status": "ok", "total": 0, "passed": 0, "probes": []},
    )
    payload = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "mode": "full",
        "truth_set": "opc-truth.json",
        "corpus_key": "stub",
        "canonical": "stub",
        "api": "stub",
        "user": "stub",
        "visitor_class": "silent",
        "judge_model": "stub",
        "judge_provider_pinned": False,
        "judge_prompt_sha256": ev.judge_prompt_fingerprint(),
        "suite": suite,
        "evidence": {"total": 0, "resolved": 0, "unresolved": [], "locators": []},
    }
    return json.dumps(suite, ensure_ascii=False, sort_keys=True) + ev.render_opc_report(payload)


def test_the_suite_is_assembled_in_truth_set_order_however_the_calls_complete(
    ev, manifest
) -> None:
    """The determinism guard: same bytes at concurrency 32 and at concurrency 1.

    Both runs see identical stub answers and identical stub verdicts; the only difference is how
    many calls were in flight and therefore the order they landed in. If a single row, facet or
    breakdown were assembled in completion order, the two rendered reports would differ.
    """
    fast, fast_negatives, completions, gate = _score(ev, manifest, 32)
    serial, serial_negatives, serial_completions, serial_gate = _score(ev, manifest, 1)

    assert gate.peak_in_flight > 1, "concurrency 32 never had two calls in flight"
    assert serial_gate.peak_in_flight == 1, "concurrency 1 must stay serial"
    assert completions != serial_completions, (
        "the stubs did not actually complete out of order, so this proves nothing"
    )

    expected = [
        (case["case_id"], lane)
        for case in manifest["truth"]["retrieval_cases"]
        for lane in ev.lanes_for(case)
    ]
    assert [(row["case_id"], row["lane"]) for row in fast["rows"]] == expected
    assert [row["case_id"] for row in fast_negatives["cases"]] == [
        case["case_id"] for case in manifest["truth"]["negatives"]
    ]
    for row in fast["rows"]:
        case = next(
            entry
            for entry in manifest["truth"]["retrieval_cases"]
            if entry["case_id"] == row["case_id"]
        )
        assert [facet["facet_id"] for facet in row["facets"]] == [
            facet["facet_id"] for facet in case["facets"]
        ], f"{row['case_id']}: facets came back in completion order"

    assert fast["rows"] == serial["rows"]
    assert fast_negatives == serial_negatives
    assert _report(ev, manifest, fast, fast_negatives) == _report(
        ev, manifest, serial, serial_negatives
    )


def test_the_throughput_line_counts_every_call_and_says_how_wide_it_ran(ev, manifest) -> None:
    """The cost line is reported, and it is a cost line: it names calls, seconds and the bound.

    The count is checked against the suite's own shape rather than a frozen number, so adding a
    question moves it without touching this test — what must not drift is that every ask and
    every verdict is tallied.
    """
    positive, negatives, _, gate = _score(ev, manifest, 32)
    asks = len(positive["rows"]) + len(negatives["cases"])
    verdicts = sum(len(row["facets"]) for row in positive["rows"]) + len(negatives["cases"])
    row = gate.summary()
    assert row["calls"] == asks + verdicts
    assert row["retries"] == 0
    assert row["concurrency"] == 32
    assert row["wall_seconds"] > 0
    assert "calls in" in gate.line() and "concurrency 32" in gate.line()


class SpanJudge:
    """A judge that answers `yes`/`no` and, when asked, commits to the premise line too."""

    def __init__(self, head: str, premise: str | None = None) -> None:
        self.head = head
        self.premise = premise
        self.prompts: list[tuple[str, str]] = []

    async def ainvoke(self, messages):
        self.prompts.append((messages[0][1], messages[1][1]))
        reply = f"{self.head}\nstub rationale"
        if self.premise:
            reply += f"\npremise: {self.premise}"
        return SimpleNamespace(content=reply)


class StubL0:
    def __init__(self, blocks: dict[str, list[str]]) -> None:
        self._blocks = blocks

    def blocks_by_source(self) -> dict[str, list[str]]:
        return self._blocks


def test_the_negative_judge_is_shown_the_l0_text_behind_the_answers_own_citations(ev) -> None:
    """Ruling C, mechanically: what the answer stood on reaches the grader.

    The auditor used to see only the question, the answer and the absence statement, so a
    grounded detail and an invention looked the same to it. The spans are resolved from the L0
    this runner already harvested, through the answer's own `citation_handles`, and both citation
    shapes the two lanes write — the fast lane's short handle and the deep lane's raw source id —
    have to resolve or the fix reaches only half the suite.
    """
    sid = "a" * 32
    other = "b" * 32
    spans = ev.CitedSpans(
        StubL0({sid: ["block zero", "block one", "block two"], other: ["far block"]})
    )
    resolved = spans.resolve(
        {
            "answer": f"见证人栏仍为空 [cite: s07 ¶1-2] and again [cite: s07 ¶1-2] "
            f"and [cite: {other} ¶0]",
            "citation_handles": {"s07": sid},
        }
    )
    assert [row["cite"] for row in resolved] == [
        f"[cite: {sid} ¶1-2]",
        f"[cite: {other} ¶0-0]",
    ], "a repeated citation is one span, and a raw source id resolves like a handle"
    assert resolved[0]["text"] == "block one\nblock two"

    judge = SpanJudge("no")
    gate = ev.CallGate(1)
    case = {
        "case_id": "miss-ud-99",
        "shape": "unanswerable_detail",
        "difficulty": "L1",
        "question": "见证人是谁？",
        "absent": "材料从未记过见证人。",
    }

    class OneAnswer:
        async def ask(self, question, as_of=None, *, label=""):
            return {
                "answer": "记录中没有见证人；见证人栏仍为空。 [cite: s07 ¶1-2]",
                "answer_kind": "no_record",
                "citation_handles": {"s07": sid},
            }

    async def once():
        gate.open()
        try:
            return await ev.score_negative_case(case, OneAnswer(), judge, gate, spans)
        finally:
            gate.close()

    row = asyncio.run(once())
    assert row["cited_spans"], "the row must record what the judge was shown"
    assert "block one" in judge.prompts[0][1], "the cited L0 text never reached the judge"
    assert row["premise_accepted"] is None, "only a false_premise case carries that verdict"


def test_the_auditor_is_told_that_asserting_the_absence_is_a_correction(ev) -> None:
    """The clause that keeps a rejection from being scored as an invention, on every shape.

    `miss-fp-06` and `miss-fp-07` REJECTED their false premises — 「陈放并不是反对那项材料变更」,
    「记录不支持…这一前提」 — and were graded `fabricated` for asserting, word for word, what the
    set's own `absent` line says the corpus records. A rejection can only be made by asserting the
    negative, so the negative is never the invention. The rule reaches every shape (a
    `nonexistent_subject` refusal and an `unanswerable_detail` abstention assert an absence too),
    and it is hashed with the rest of the judging language so a line scored under it can never be
    read beside one that was not.
    """
    for shape in ev.NEGATIVE_SHAPES:
        judge = SpanJudge("no", "rejected" if shape == "false_premise" else None)
        row = _negative_row(
            ev,
            dict(_ns_case(f"miss-{shape}-99"), shape=shape),
            "材料里没有这件事的记录；材料记下的是另一回事。",
            judge,
        )
        prompt = judge.prompts[0][0]
        assert "THE ABSENCE STATEMENT ABOVE IS TRUE" in prompt, (
            f"{shape}: the clause never reached the judge"
        )
        assert "BEYOND the absence statement" in prompt, (
            f"{shape}: the rule has to say what IS graded, not only what is not"
        )
        assert "合同是什么时候终止的？" in prompt, (
            f"{shape}: the worked example is the clause's teeth and has to travel with it"
        )
        assert row["correct"] is True

    before = ev.judge_prompt_fingerprint()
    original = ev.NEGATIVE_JUDGE_SYSTEM
    try:
        ev.NEGATIVE_JUDGE_SYSTEM = original.replace(
            "THE ABSENCE STATEMENT ABOVE IS TRUE", "the absence statement may be wrong"
        )
        assert ev.NEGATIVE_JUDGE_SYSTEM != original, "the clause is not where this test looks"
        assert ev.judge_prompt_fingerprint() != before, (
            "the clause must be inside the fingerprint the artifact records, or a judge change "
            "would look like a library change"
        )
    finally:
        ev.NEGATIVE_JUDGE_SYSTEM = original


class PropositionJudge:
    """A grader that reads the `Fact to check:` block as the thing to be entailed, and nothing else.

    This is not a caricature: it is what the real judge did on the previous line, and it is why
    `join-03`'s deep answer — which reported one of the corpus's two documented acts — came back
    `omitted`. The stub makes that reading mechanical. It looks for a specific act INSIDE the fact
    block and requires the answer to carry whatever it finds there, so a proposition with its acts
    parenthesised inside it fails an answer that names a third documented act, and the same
    proposition with those acts beside it, under the illustration header, does not.
    """

    def __init__(self, acts: tuple[str, ...]) -> None:
        self.acts = acts
        self.prompts: list[tuple[str, str]] = []

    async def ainvoke(self, messages):
        human = messages[1][1]
        self.prompts.append((messages[0][1], human))
        fact = human.split("Fact to check:\n", 1)[1].split("\n\n", 1)[0]
        answer = human.split("Answer given:\n", 1)[1]
        required = [act for act in self.acts if act in fact]
        head = "stated" if all(act in answer for act in required) else "omitted"
        return SimpleNamespace(content=f"{head}\ngraded against: {fact}")


#: An existential facet in the two shapes it can be authored in: the acts inside the proposition
#: (what the previous line shipped) and the acts beside it (what this line does). Synthetic — the
#: shipped facets are checked separately, against the set itself.
PROPOSITION = "他在工作那一侧至少做过一件材料记下的事"
ACT_A = "回查了两个链接"
ACT_B = "在阶段复盘上提出核对"
#: A third act, documented in the same corpus file the facet rests on and named by neither
#: illustration. Answering with it satisfies the proposition and satisfies no example.
ACT_C = "把待发信里的顺序从头点了一遍"


def _existential_facet(*, examples: bool) -> dict:
    return {
        "facet_id": "join-99-b",
        "tag": "core",
        "text": PROPOSITION if examples else f"{PROPOSITION}（{ACT_A}，或{ACT_B}）",
        **({"examples": [ACT_A, ACT_B]} if examples else {}),
        "evidence": [{"corpus_file": "2026-05-05-两个链接回查.md", "quote": ACT_C}],
    }


def _judge_one_facet(ev, facet: dict, answer: str, judge) -> tuple[str, str]:
    gate = ev.CallGate(1)

    async def once():
        gate.open()
        try:
            return await ev.judge_facet(judge, "他还在工作那一侧做过什么事？", facet, answer, gate=gate)
        finally:
            gate.close()

    return asyncio.run(once())


def test_a_facet_with_examples_is_judged_on_its_proposition(ev, manifest) -> None:
    """The facet contract: illustrations are illustrations, and the proposition is the fact.

    An existential facet still has to exclude an invented act, and the way it used to do that was
    to name the corpus's own acts inside the proposition — which made the illustration the thing
    being graded. The list now travels beside the fact under a header that says what it is, and
    the fact block carries the proposition alone. Both halves are checked here: the verdict flips
    between the two authorings under a grader that reads the fact block, and the examples are in
    the prompt, labelled.
    """
    answer = f"他{ACT_C}。"
    acts = (ACT_A, ACT_B)

    beside = PropositionJudge(acts)
    verdict, _ = _judge_one_facet(ev, _existential_facet(examples=True), answer, beside)
    assert verdict == "stated", (
        "an answer naming a documented act that is not one of the illustrations satisfies an "
        "existential proposition"
    )

    inside = PropositionJudge(acts)
    was, _ = _judge_one_facet(ev, _existential_facet(examples=False), answer, inside)
    assert was == "omitted", (
        "this test proves nothing unless the old authoring actually graded the parenthesis"
    )

    prompt = beside.prompts[0][1]
    fact_block = prompt.split("Fact to check:\n", 1)[1].split("\n\n", 1)[0]
    assert fact_block == PROPOSITION, "the fact block must be the proposition and nothing else"
    assert ev.FACET_EXAMPLES_HEADER in prompt, "the illustrations reached the judge unlabelled"
    assert "NOT a checklist" in ev.FACET_EXAMPLES_HEADER
    for act in acts:
        assert f"- {act}" in prompt, "an illustration never reached the prompt"
        assert act not in fact_block
    assert "ILLUSTRATIONS" in beside.prompts[0][0], (
        "the system turn has to say what such a list is, not only the user turn"
    )

    plain = PropositionJudge(acts)
    _judge_one_facet(
        ev,
        {k: v for k, v in _existential_facet(examples=True).items() if k != "examples"},
        answer,
        plain,
    )
    assert ev.FACET_EXAMPLES_HEADER not in plain.prompts[0][1], (
        "a facet with no examples must render the prompt it rendered before the field existed"
    )

    shipped = [
        facet
        for case in manifest["truth"]["retrieval_cases"]
        for facet in case["facets"]
        if facet.get("examples")
    ]
    assert shipped, "the shipped set must actually use the field this contract is written for"
    for facet in shipped:
        assert all(example not in facet["text"] for example in facet["examples"]), (
            f"{facet['facet_id']}: an illustration is still inside the proposition"
        )

    before = ev.judge_prompt_fingerprint()
    original = ev.FACET_EXAMPLES_HEADER
    try:
        ev.FACET_EXAMPLES_HEADER = "some other header"
        assert ev.judge_prompt_fingerprint() != before, (
            "the header is judging language and belongs in the hash the artifact records"
        )
    finally:
        ev.FACET_EXAMPLES_HEADER = original


def test_a_false_premise_case_carries_a_second_verdict_of_its_own(ev) -> None:
    """`premise_accepted` is asked for, parsed, and kept out of the fabrication number.

    Refusing a false premise and inventing a value are different behaviours, and one number over
    both would hide whichever moved. An answer can reject the premise and still fabricate, so the
    two verdicts are parsed independently and a missing premise line stays `None` rather than
    defaulting to the flattering answer.
    """
    gate = ev.CallGate(1)
    case = {
        "case_id": "miss-fp-99",
        "shape": "false_premise",
        "difficulty": "L2",
        "question": "供应商审批是什么时候被取消的？",
        "absent": "供应商审批从未被取消。",
    }

    class OneAnswer:
        async def ask(self, question, as_of=None, *, label=""):
            return {"answer": "它没有被取消。", "answer_kind": "inference"}

    def run(judge):
        async def once():
            gate.open()
            try:
                return await ev.score_negative_case(case, OneAnswer(), judge, gate, None)
            finally:
                gate.close()

        return asyncio.run(once())

    rejected = run(SpanJudge("no", "rejected"))
    assert rejected["premise_accepted"] is False and rejected["correct"] is True
    assert "premise: rejected" in rejected["judge_rationale"], (
        "the raw verdict is kept beside the parse, so a later reader can check the parse"
    )

    accepted = run(SpanJudge("yes", "accepted"))
    assert accepted["premise_accepted"] is True and accepted["correct"] is False

    silent = run(SpanJudge("no"))
    assert silent["premise_accepted"] is None, "a verdict nobody gave is not a verdict"


#: One answer of each shape a `nonexistent_subject` question draws, on the suite's own near-miss
#: pair (常春养护 is invented; 常青养护 is real). These are the fixtures, not the prompt: the
#: worked examples the judge reads are synthetic and name a different pair, so this file cannot
#: pass by quoting the prompt back at itself.
NS_ANSWER_FIXTURES = {
    "refuses": "材料里没有关于常春养护的任何记录，这个问题答不了。",
    "corrects_to_real": "材料里没有常春养护；名字相近的是常青养护，那次保养收了 680 元。",
    "answers_inside": "这次保养一共收了 680 元。",
}
NS_REAL_SUBJECT = "常青养护"


def _negative_row(ev, case: dict, answer: str, judge) -> dict:
    """One negative case scored end to end against a stub judge, with no stack and no key."""
    gate = ev.CallGate(1)

    class OneAnswer:
        async def ask(self, question, as_of=None, *, label=""):
            return {"answer": answer, "answer_kind": "grounded"}

    async def once():
        gate.open()
        try:
            return await ev.score_negative_case(case, OneAnswer(), judge, gate, None)
        finally:
            gate.close()

    return asyncio.run(once())


def _ns_case(case_id: str = "miss-ns-99") -> dict:
    return {
        "case_id": case_id,
        "shape": "nonexistent_subject",
        "difficulty": "L2",
        "question": "常春养护这次保养一共收了多少钱？",
        "absent": "材料里没有叫「常春养护」的商家。名字相近的是常青养护。",
    }


def test_the_auditor_is_told_that_answering_inside_an_invented_subject_is_fabrication(
    ev, manifest, monkeypatch
) -> None:
    """The clause the previous line was missing, and the hash that makes it attributable.

    22/22 was a ceiling: `miss-ns-06` gives a figure for a shop that does not exist, never names
    the real one, and passed because it "did not claim the shop exists". The rule now says what
    `miss-ns-01` and `miss-ns-03` show by contrast — correcting to the real subject is not
    fabrication, answering inside the invented one is — and it reaches the shape it is about and
    no other shape. It is hashed with the rest of the judging language, so a line scored under it
    can never be read beside one that was not.
    """
    judge = SpanJudge("no")
    _negative_row(ev, _ns_case(), NS_ANSWER_FIXTURES["answers_inside"], judge)
    prompt = judge.prompts[0][0]
    assert "answered INSIDE the invented one" in prompt, "the clause never reached the judge"
    assert all(row["example"] in prompt for row in ev.NONEXISTENT_SUBJECT_SHAPES), (
        "the worked examples are the rule's teeth and have to be in the prompt with it"
    )
    assert any(
        case["shape"] == "nonexistent_subject" for case in manifest["truth"]["negatives"]
    ), "the shipped suite must actually have the shape this rule is written for"

    other = SpanJudge("no")
    _negative_row(
        ev,
        dict(_ns_case(), case_id="miss-ud-99", shape="unanswerable_detail"),
        "记录里没有这一项。",
        other,
    )
    assert "answered INSIDE the invented one" not in other.prompts[0][0], (
        "a shape rule that reaches every shape is not a shape rule"
    )

    before = ev.judge_prompt_fingerprint()
    monkeypatch.setattr(ev, "NEGATIVE_SUBJECT_RULE", "\nsomething else entirely")
    assert ev.judge_prompt_fingerprint() != before, (
        "the clause must be inside the fingerprint the artifact records, or a judge change "
        "would look like a library change"
    )
    monkeypatch.undo()
    positive, negatives, _, _ = _score(ev, manifest, 4)
    assert before[:12] in _report(ev, manifest, positive, negatives), (
        "the artifact has to carry the hash of the language it was graded with"
    )


def test_the_three_shapes_of_a_nonexistent_subject_answer_are_the_three_the_prompt_names(
    ev,
) -> None:
    """Refuse, correct to the real subject, answer inside the invented one — and only one is `yes`.

    The prompt's worked examples are rendered from the same table this reads, so the rule the
    judge is given cannot drift from the rule the suite says it applies. The shapes are then
    pinned to the mechanical trait that separates them — a figure handed over with no real
    subject named — rather than to the words the table happens to use, and each is carried
    through `score_negative_case` so that a `yes` on this shape lands as a failed case.
    """
    shapes = {row["shape"]: row for row in ev.NONEXISTENT_SUBJECT_SHAPES}
    assert set(shapes) == set(NS_ANSWER_FIXTURES), (
        "the fixtures and the prompt must name the same three shapes"
    )
    assert {name: row["verdict"] for name, row in shapes.items()} == {
        "answers_inside": "yes",
        "corrects_to_real": "no",
        "refuses": "no",
    }

    inside = {
        name
        for name, answer in NS_ANSWER_FIXTURES.items()
        if any(char.isdigit() for char in answer) and NS_REAL_SUBJECT not in answer
    }
    assert inside == {name for name, row in shapes.items() if row["verdict"] == "yes"}, (
        "the shape called fabrication must be exactly the one that gives a value for the "
        "invented subject without naming the real one"
    )

    for name, answer in NS_ANSWER_FIXTURES.items():
        judge = SpanJudge(shapes[name]["verdict"])
        row = _negative_row(ev, _ns_case(f"miss-ns-{name}"), answer, judge)
        assert row["fabricated"] is (shapes[name]["verdict"] == "yes")
        assert row["correct"] is (shapes[name]["verdict"] == "no"), (
            f"{name}: a verdict on this shape must decide the case"
        )
        assert row["premise_accepted"] is None, "only a false_premise case carries that verdict"


def test_the_reconciliation_files_a_moved_case_under_the_revision_that_moved_it(
    ev, manifest, tmp_path
) -> None:
    """Ruling D: the section is computed, not narrated.

    The case lists are the diff of two runs' per-case verdicts, and each moved case is filed
    under the ruler revision the truth set says touched it — so the one thing the section must
    never do is let a change in the ruler read as a change in the library.
    """
    previous = tmp_path / "opc-eval.json"
    previous.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-01T00:00:00+00:00",
                "corpus_key": "opc-my-data-v2",
                "judge_prompt_sha256": "0" * 64,
                "suite": {
                    "positive": {"by_lane": {"fast": {"correct": 1, "total": 2}}},
                    "cases": [
                        {"case_id": "state-08", "lane": "fast", "correct": False},
                        {"case_id": "chain-01", "lane": "fast", "correct": True},
                    ],
                    "negative": {"correct": 1, "total": 1},
                    "negative_cases": [{"case_id": "miss-ud-07", "correct": False}],
                },
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "generated_at": "2026-09-02T00:00:00+00:00",
        "mode": "full",
        "corpus_key": "opc-my-data-v3",
        "judge_prompt_sha256": ev.judge_prompt_fingerprint(),
        "suite": {
            "positive": {"by_lane": {"fast": {"correct": 2, "total": 2}}},
            "cases": [
                {"case_id": "state-08", "lane": "fast", "correct": True},
                {"case_id": "chain-01", "lane": "fast", "correct": True},
            ],
            "negative": {"correct": 1, "total": 1},
            "negative_cases": [{"case_id": "miss-ud-07", "correct": True}],
        },
    }
    line = ev.read_previous_line(f"truth-v2={previous}")
    section = ev.reconciliation_section(payload, manifest, [line])
    # The headline and the basis line are the truth set's own declarations, not the renderer's
    # opinion: what changed underneath two lines is a property of the set being scored, and a
    # line whose numbers moved because the deployment changed has to be able to say so.
    assert section.startswith(
        f"## Reconciliation — {manifest['reconciliation']['headline']}"
    )
    assert manifest["reconciliation"]["basis"] in section
    assert "`state-08` | miss | pass" in section, "a moved case must be listed"
    assert "chain-01" not in section, "a case that did not move is not a change"
    assert "facet split" in section, "state-08 was re-cut in v3 and must be filed under it"
    assert "judge calibration" in section, (
        "miss-ud-07 kept its facets, so its move is the judge's and must say so"
    )
    assert ev.judge_prompt_fingerprint()[:12] in section, "the ruler's hash, before and after"
    assert "0" * 12 in section

    mechanical = dict(payload, mode="mechanical")
    mechanical["suite"] = dict(payload["suite"], cases=[])
    assert "not rendered" in ev.reconciliation_section(mechanical, manifest, [line])


@pytest.mark.parametrize("now_key", ["opc-my-data-v3", "opc-my-data-v4"])
def test_a_revision_the_compared_line_already_carried_cannot_be_blamed(
    ev, manifest, tmp_path, now_key
) -> None:
    """A moved case is filed only under a revision that lies BETWEEN the two lines.

    `state-08` declares `v3-facet-split`, and that split is real — against the v2 line it is why
    the case moved. Against a line already scored on v3 it cannot be, whether this run is scored
    on v3 (nothing at all lies between) or on a later set (the split lies before both): the
    facets were byte-identical on both lines, so what is left is a change outside the truth set
    and the answering lane's own noise, which is what the fallback for that key names. Without
    this the section would report a facet split as having moved a case whose facets never moved.
    """
    previous = tmp_path / "opc-eval.json"
    previous.write_text(
        json.dumps(
            {
                "generated_at": "2026-09-02T00:00:00+00:00",
                "corpus_key": "opc-my-data-v3",
                "judge_prompt_sha256": "0" * 64,
                "suite": {
                    "positive": {"by_lane": {"fast": {"correct": 0, "total": 1}}},
                    "cases": [{"case_id": "state-08", "lane": "fast", "correct": False}],
                    "negative": {"correct": 1, "total": 1},
                    "negative_cases": [{"case_id": "miss-ns-06", "correct": True}],
                },
            }
        ),
        encoding="utf-8",
    )
    payload = {
        "generated_at": "2026-09-02T00:00:00+00:00",
        "mode": "full",
        "corpus_key": now_key,
        "judge_prompt_sha256": ev.judge_prompt_fingerprint(),
        "suite": {
            "positive": {"by_lane": {"fast": {"correct": 1, "total": 1}}},
            "cases": [{"case_id": "state-08", "lane": "fast", "correct": True}],
            "negative": {"correct": 0, "total": 1},
            "negative_cases": [{"case_id": "miss-ns-06", "correct": False}],
        },
    }
    section = ev.reconciliation_section(
        payload, manifest, [ev.read_previous_line(f"truth-v3-earlier={previous}")]
    )
    config = manifest["reconciliation"]
    fallback = next(
        group
        for group in config["groups"]
        if group["key"] == config["unattributed_group_for"]["opc-my-data-v3"]
    )
    heading = section.find(f"#### {fallback['title']}")
    assert heading > 0 and "#### facet split" not in section, (
        "both moved cases belong to the group the truth set names for a v3 comparison"
    )
    assert section.index("`state-08`") > heading and section.index("`miss-ns-06`") > heading


class Flaky:
    """A call that fails a fixed number of times before succeeding."""

    def __init__(self, failures: int, exc: BaseException) -> None:
        self.failures = failures
        self.exc = exc
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.exc
        return "ok"


def _http_error(status: int) -> Exception:
    exc = RuntimeError(f"HTTP {status}")
    exc.response = SimpleNamespace(status_code=status)  # type: ignore[attr-defined]
    return exc


def _through(ev, gate, call, **kwargs):
    async def once():
        gate.open()
        try:
            return await gate.run(call, label="judge f-1", base_delay=0.001, **kwargs)
        finally:
            gate.close()

    return asyncio.run(once())


def test_a_transient_failure_costs_a_retry_and_a_permanent_one_fails_immediately(ev) -> None:
    """Backoff is bounded and selective, and neither shape is ever swallowed.

    A 503 is retried — one full run has no partial result, so a single blip must not throw away
    the baseline. A 401 is not: retrying a bad credential thirty-two ways at once turns one
    misconfiguration into hundreds of refused requests, and the answer would not change.
    """
    gate = ev.CallGate(4)
    transient = Flaky(2, _http_error(503))
    assert _through(ev, gate, transient) == "ok"
    assert transient.calls == 3
    assert gate.summary()["retries"] == 2
    assert gate.summary()["calls"] == 1

    permanent_gate = ev.CallGate(4)
    permanent = Flaky(99, _http_error(401))
    with pytest.raises(ev.EvalDependencyError) as caught:
        _through(ev, permanent_gate, permanent)
    assert permanent.calls == 1, "a permanent status must not be retried"
    assert "judge f-1" in str(caught.value), "the failure must name the call that made it"
    assert permanent_gate.summary()["retries"] == 0


def test_a_call_that_never_succeeds_stops_the_run_instead_of_becoming_a_wrong_answer(ev) -> None:
    """Exhausted attempts are an error, not a verdict.

    Recording a dead call as `omitted` would make an outage read as a library regression, which
    is the one failure mode a regression line must never have. An unfamiliar exception with no
    status is retried like a transient one, so the bound never narrows what the serial runner
    already survived.
    """
    gate = ev.CallGate(2)
    dead = Flaky(99, TimeoutError("read timed out"))
    with pytest.raises(ev.EvalDependencyError):
        _through(ev, gate, dead)
    assert dead.calls == 4, "bounded: four attempts, not an unbounded loop"
    assert gate.summary()["calls"] == 0


# ─────────────────────────────────────────────────────── the judge's own calibration suite


class RecordingJudge:
    """A judge that answers the same thing every time and keeps what it was handed."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen: list[tuple[str, str]] = []

    async def ainvoke(self, messages):
        self.seen.append((messages[0][1], messages[1][1]))
        return SimpleNamespace(content=self.reply)


def _under_gate(ev, work):
    """Run one coroutine under an opened `CallGate`, the way both suites do."""

    async def main():
        gate = ev.CallGate(4)
        gate.open()
        try:
            return await work(gate)
        finally:
            gate.close()

    return asyncio.run(main())


NEG_ABSENT = "材料里没有取消的记录；那次评审一直有效"
NEG_QUESTION = "那次评审是什么时候取消的？"
NEG_ANSWER = "材料里没有取消记录，评审一直有效。"
NEG_SPANS = [{"cite": "[cite: s01 ¶1-2]", "text": "评审在四月照常进行，没有取消。"}]


def test_the_calibration_and_the_scoring_ask_the_judge_in_exactly_the_same_words(ev) -> None:
    """One negative-judge code path, proved by the bytes it sends.

    The calibration exists to certify the ruler that scores the line. A second copy of the
    judge's prompt — one for scoring, one for calibrating — would let the two drift a word at a
    time, and the suite would then certify a prompt nobody grades with. So the scoring path and
    the calibration path go through `judge_negative`, and this holds them to producing the same
    system and human turns for the same case.
    """
    item = {
        "item_id": "cal-neg-x",
        "shape": "false_premise",
        "absent": NEG_ABSENT,
        "question": NEG_QUESTION,
        "answer": NEG_ANSWER,
        "cited_spans": [{"source": "s01 ¶1-2", "text": NEG_SPANS[0]["text"]}],
        "expected_fabricated": False,
        "expected_premise_accepted": False,
        "why": "stub",
    }
    calibration = {
        "variants": {"paraphrase": {"blocking": True}},
        "facet_items": [],
        "negative_items": [item],
    }
    calibrating = RecordingJudge("no\nstub reason\npremise: rejected")
    _under_gate(ev, lambda gate: ev.run_calibration(calibration, calibrating, gate))

    case = {
        "case_id": "miss-fp-x",
        "shape": "false_premise",
        "difficulty": "L2",
        "question": NEG_QUESTION,
        "absent": NEG_ABSENT,
    }

    async def ask(question, as_of=None, *, label=""):
        return {"answer": NEG_ANSWER, "answer_kind": "grounded"}

    scoring = RecordingJudge("no\nstub reason\npremise: rejected")
    row = _under_gate(
        ev,
        lambda gate: ev.score_negative_case(
            case,
            SimpleNamespace(ask=ask),
            scoring,
            gate,
            SimpleNamespace(resolve=lambda body: NEG_SPANS),
        ),
    )
    assert calibrating.seen and calibrating.seen == scoring.seen, (
        "the calibration and the scoring sent the judge different prompts"
    )
    assert ev.NEGATIVE_PREMISE_RULE in scoring.seen[0][0], (
        "a false-premise case must carry its shape rule into the prompt"
    )
    assert row["fabricated"] is False and row["premise_accepted"] is False


def test_a_calibration_item_is_judged_by_the_facet_judge_the_positive_suite_uses(ev) -> None:
    """The facet half of the same property, plus the illustrations header a facet may carry."""
    item = {
        "item_id": "cal-x",
        "variant": "paraphrase",
        "facet": "钥匙由前台保管",
        "examples": ["前台交接过一次"],
        "evidence": [{"corpus_file": "stub.md", "quote": "钥匙一直放在前台。"}],
        "question": "钥匙在哪里？",
        "answer": "在前台。",
        "expected": "stated",
        "why": "stub",
    }
    judge = RecordingJudge("stated\nstub reason")
    result = _under_gate(
        ev,
        lambda gate: ev.run_calibration(
            {
                "variants": {"paraphrase": {"blocking": True}},
                "facet_items": [item],
                "negative_items": [],
            },
            judge,
            gate,
        ),
    )
    system, human = judge.seen[0]
    assert system == ev.FACET_JUDGE_SYSTEM
    assert ev.FACET_EXAMPLES_HEADER in human and "钥匙一直放在前台。" in human
    assert result["facet"]["by_variant"]["paraphrase"]["agreed"] == 1
    assert result["passed"] is True


def test_a_disagreement_gates_only_where_the_suite_says_it_gates(ev) -> None:
    """Blocking is declared per variant in the file, and it decides the exit code.

    Both halves matter. A blocking variant that disagrees has to stop the run — a ruler that
    cannot hold its own verdict across a rephrasing produces a line comparable with nothing. A
    non-blocking one has to be reported and NOT stop it, because `name_variant` is a judgement
    call, and a suite that gated on it would make every prompt edit a negotiation with a
    borderline case. The mechanism is read off the file, so this test names a variant of its
    own rather than whichever the shipped suite currently leaves ungated.
    """
    item = {
        "item_id": "cal-y",
        "variant": "approximate",
        "facet": "报名费是 200 元",
        "evidence": [{"corpus_file": "stub.md", "quote": "报名费 200 元。"}],
        "question": "报名费多少？",
        "answer": "大概两百。",
        "expected": "stated",
        "why": "stub",
    }
    judge = RecordingJudge("omitted\nstub reason")

    def run(blocking: bool):
        return _under_gate(
            ev,
            lambda gate: ev.run_calibration(
                {
                    "variants": {"approximate": {"blocking": blocking}},
                    "facet_items": [item],
                    "negative_items": [],
                },
                judge,
                gate,
            ),
        )

    reported = run(False)
    assert reported["passed"] is True
    assert [row["item_id"] for row in reported["disagreements"]] == ["cal-y"]
    assert reported["agreed"] == 0 and reported["items"] == 1

    gating = run(True)
    assert gating["passed"] is False and gating["blocking_failures"] == ["approximate"]
    header = ev.calibration_header({**gating, "judge_prompt_sha256": "stub"})
    assert header["by_variant"]["approximate"] == {
        "items": 1,
        "agreed": 0,
        "blocking": True,
    }
    assert header["prompt_sha256"] == "stub" and header["passed"] is False


def test_mode_judge_is_wired_and_the_shipped_calibration_loads_without_a_model(ev) -> None:
    """The keyless half of `--mode judge`: the flag exists and the suite parses.

    `load_calibration` is separated from `run_calibration` precisely so this can be checked with
    no key, no stack and no network — a malformed calibration file must be a load error in CI
    rather than a surprise forty questions into a scored run.
    """
    args = ev.build_parser().parse_args(["--mode", "judge", "--out", "var/x"])
    assert args.mode == "judge" and args.calibration == ev.DEFAULT_CALIBRATION

    calibration = ev.load_calibration(ev.DEFAULT_CALIBRATION)
    assert calibration["facet_items"] and calibration["negative_items"]
    assert set(calibration["variants"]) >= {row["variant"] for row in calibration["facet_items"]}

    for broken, complaint in (
        ({"variants": {}, "facet_items": [], "negative_items": []}, "variants"),
        (
            {
                "variants": {"paraphrase": {"blocking": True}},
                "facet_items": [
                    {
                        "item_id": "x",
                        "variant": "paraphrase",
                        "facet": "f",
                        "question": "q",
                        "answer": "a",
                        "expected": "maybe",
                        "why": "w",
                        "evidence": [{"corpus_file": "s", "quote": "q"}],
                    }
                ],
                "negative_items": [
                    {
                        "item_id": "y",
                        "shape": "unanswerable_detail",
                        "absent": "a",
                        "question": "q",
                        "answer": "a",
                        "cited_spans": [],
                        "expected_fabricated": False,
                        "expected_premise_accepted": None,
                        "why": "w",
                    }
                ],
            },
            "maybe",
        ),
    ):
        path = Path(tempfile.mkdtemp()) / "judge-calibration.json"
        path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        with pytest.raises(Exception) as excinfo:
            ev.load_calibration(path)
        assert complaint in str(excinfo.value)
