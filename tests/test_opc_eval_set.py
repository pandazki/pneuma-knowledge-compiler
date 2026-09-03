"""The OPC regression eval set, guarded mechanically — keyless, offline, no stack.

The set's whole claim is that its answers came from this example's own inputs — `my-data/` plus
the owner statement `build-record/exercise.py` sends — and from nowhere else, and that its
negative suite asks about things the corpus provably does not contain. Both are checkable
without a model, a database or a built library, so they are checked here rather than asserted
in prose:

* every authored quote must occur VERBATIM in the corpus file it names, or — when it carries
  `corpus_source: "owner_statement"` — in the `OWNER_DIALOGUE` literal of the script that sends
  it. The eval runner re-resolves the same quotes against ingested L0 at run time, and this is
  the half of that guarantee that needs no stack;
* every invented name in the `nonexistent_subject` suite must appear in ZERO corpus files.
  A corpus edit that accidentally introduces one would silently turn a fabrication probe into
  an answerable question, and the scorecard would report a regression that was really a
  broken probe;
* every positive case must be faceted: each facet tagged `core` or `detail`, each carrying its
  own corpus evidence, and at least one core facet per case — a case with none would be scored
  correct whatever the answer said;
* every facet must be ONE proposition. The judge returns one verdict per facet, so a facet that
  joins two claims is a facet no verdict can be right about;
* every negative case must declare, in a sentence a judge can be handed, what the material does
  not contain — and prove the absence, by an `absence_proof` pattern or by a quote of the state
  that IS recorded;
* every positive question either fixes its time or asks for the current state. One that does
  neither has to be named, with its reason, in the truth file's own `undated_ok` allowlist —
  a closed set the author signs, so an undated question cannot be added by accident;
* the committed baseline must carry its reconciliation with the line it replaces, and every
  group a moved case can be filed under must be declared;
* the schema the runner reads must hold: known axes, tiers and `expected_via` values, resolvable
  truth ids, and a set whose shape still matches what the task it was authored for asked for;
* the judge's calibration suite must cover every phrasing variant it declares, and must borrow
  nothing from this corpus. A calibration item naming this corpus's people, numbers or files
  would leak the truth set into the judge's context and calibrate the ruler on the very wording
  it is later asked to grade.

This file lives in `tests/` (the repo-hygiene suite) rather than in the eval package's own
tests, for the same reason the dataset lives under `examples/`: the package must not grow a
dependency on one corpus, and this example must not become a package fixture.
"""

from __future__ import annotations

import ast
import json
import re
import unicodedata
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "opc"
TRUTH_PATH = EXAMPLE / "eval" / "opc-truth.json"
CORPUS = EXAMPLE / "my-data"
OWNER_SCRIPT = EXAMPLE / "build-record" / "exercise.py"

AXES = {
    "state",
    "history",
    "chain",
    "set",
    "definition",
    "calendar",
    "aggregate",
    "join",
    "miss",
}
DIFFICULTIES = {"L1", "L2", "L3", "L4", "L5"}
NEGATIVE_SHAPES = {"unanswerable_detail", "nonexistent_subject", "false_premise"}
CATEGORIES = ("durable_facts", "decisions", "commitments", "constraints")
FACET_TAGS = {"core", "detail"}
EXPECTED_VIA = {"canonical", "verbatim"}
#: The negative suite's size is a property of the set, not a floor: it is 22 questions in three
#: shapes, and a question that stops being a negative has to be REPLACED rather than dropped.
#: The MIX may move — v6 re-shaped miss-fp-07 from `false_premise` to `unanswerable_detail`,
#: because at the corpus's latest point the premise is neither recorded nor contradicted, so the
#: rigorous negative is the missing detail. Each shape keeps its own line in the scorecard, which
#: is what the per-shape floor below protects; the total is what is fixed.
NEGATIVE_COUNT = 22


def _normalize(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", text) if not ch.isspace()
    )


@pytest.fixture(scope="module")
def truth() -> dict:
    return json.loads(TRUTH_PATH.read_text(encoding="utf-8"))["truth"]


@pytest.fixture(scope="module")
def corpus_text() -> dict[str, str]:
    return {
        path.name: _normalize(path.read_text(encoding="utf-8"))
        for path in sorted(CORPUS.glob("*.md"))
    }


@pytest.fixture(scope="module")
def owner_statement() -> str:
    """The owner statement's turns, parsed out of the script that sends them.

    Parsed rather than imported: `exercise.py` imports the example's driver and exists to drive a
    live stack, and a repo-hygiene test must not do either.
    """
    tree = ast.parse(OWNER_SCRIPT.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            getattr(target, "id", "") == "OWNER_DIALOGUE" for target in node.targets
        ):
            dialogue = ast.literal_eval(node.value)
            return _normalize("\n".join(str(turn["text"]) for turn in dialogue["turns"]))
    raise AssertionError(f"{OWNER_SCRIPT} defines no OWNER_DIALOGUE statement")


def _all_evidence(truth: dict):
    for category in CATEGORIES:
        for entry in truth.get(category, []):
            for row in entry.get("evidence", []):
                yield entry["truth_id"], row
    for case in truth.get("retrieval_cases", []):
        for row in case.get("evidence", []):
            yield case["case_id"], row
        for facet in case.get("facets", []):
            for row in facet.get("evidence", []):
                yield facet["facet_id"], row
    for case in truth.get("negatives", []):
        for row in case.get("evidence", []):
            yield case["case_id"], row
    for probe in truth.get("structure_probes", []):
        yield probe["probe_id"], probe["corpus_basis"]


def test_every_authored_quote_occurs_verbatim_in_the_corpus_file_it_names(
    truth, corpus_text, owner_statement
) -> None:
    """The set's grounding, checked without a stack.

    A truth value the corpus does not carry is not a miss the library should be scored on —
    it is a defect in the ruler. The runner enforces the same binding against ingested L0;
    this enforces it against the shipped material, so a corpus edit breaks the test rather
    than quietly changing what a question means. The owner statement is held to the same rule
    against the script that sends it, which is where its text is authored.
    """
    broken: list[str] = []
    for owner, row in _all_evidence(truth):
        name = row["corpus_file"]
        if row.get("corpus_source") == "owner_statement":
            if _normalize(row["quote"]) not in owner_statement:
                broken.append(f"{owner}: quote not in the owner statement: {row['quote'][:40]}…")
        elif name not in corpus_text:
            broken.append(f"{owner}: no such corpus file {name}")
        elif _normalize(row["quote"]) not in corpus_text[name]:
            broken.append(f"{owner}: quote not in {name}: {row['quote'][:40]}…")
    assert not broken, "authored evidence does not bind to the corpus:\n" + "\n".join(broken)


def test_the_corpus_block_names_both_halves_of_the_basis(truth, corpus_text) -> None:
    """The set says what it was authored against, and the count is the real one.

    The previous version's truths were authored on the 190 files alone, while the shipped library
    also holds the owner statement — so two questions the corpus could no longer support were
    being scored as fabrication resistance. Naming the basis in the file is what keeps that
    mistake from being invisible next time.
    """
    manifest = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    corpus = manifest["corpus"]
    assert isinstance(corpus, dict), "the corpus basis must be stated, not implied by a path"
    assert corpus["file_count"] == len(corpus_text), (
        f"the corpus block claims {corpus['file_count']} files, my-data holds {len(corpus_text)}"
    )
    statement = corpus["owner_statement"]
    assert Path(EXAMPLE / statement["authored_in"]).is_file()
    assert statement["symbol"] == "OWNER_DIALOGUE"
    assert corpus["sources_expected"] == corpus["file_count"] + 1


def test_every_positive_case_is_faceted_and_can_fail(truth) -> None:
    """Facets, tags, and the gate.

    A case is correct when every CORE facet is stated, so a case with no core facet is a case
    that cannot fail, and an untagged facet is a facet nobody can say gates or not. Each facet
    carries its own evidence for the same reason the case does: the judge is shown the corpus
    span the facet came from, and a facet with no span would be graded on the eval's own wording.
    """
    for case in truth["retrieval_cases"]:
        facets = case.get("facets") or []
        assert facets, f"{case['case_id']}: no facets — nothing to grade"
        assert case.get("expected_via") in EXPECTED_VIA, (
            f"{case['case_id']}: unknown expected_via {case.get('expected_via')!r}"
        )
        ids = [facet["facet_id"] for facet in facets]
        assert len(set(ids)) == len(ids), f"{case['case_id']}: duplicate facet ids"
        for facet in facets:
            assert facet["tag"] in FACET_TAGS, f"{facet['facet_id']}: unknown tag {facet['tag']}"
            assert facet["text"].strip(), f"{facet['facet_id']}: empty facet text"
            assert facet.get("evidence"), f"{facet['facet_id']}: no corpus evidence"
            examples = facet.get("examples")
            if examples is None:
                continue
            # An existential facet carries its illustrations BESIDE the proposition, under a
            # header telling the judge what they are. An illustration left inside the facet text
            # is the thing this field exists to end: it turns an example of what would satisfy
            # the fact into the fact, and an answer that satisfies the proposition with the
            # corpus's other documented act is then scored as having omitted it.
            assert isinstance(examples, list) and examples, (
                f"{facet['facet_id']}: `examples` must be a non-empty list"
            )
            for example in examples:
                assert str(example).strip(), f"{facet['facet_id']}: an empty example"
                assert str(example) not in facet["text"], (
                    f"{facet['facet_id']}: an illustration is still inside the proposition"
                )
        assert any(facet["tag"] == "core" for facet in facets), (
            f"{case['case_id']}: no core facet — the case could not fail"
        )


def test_every_invented_name_is_absent_from_the_whole_corpus(truth, corpus_text) -> None:
    """Fabrication probes are only probes while their subject does not exist.

    Each `nonexistent_subject` case names the pattern that must occur in zero files. These are
    deliberate near-misses of real names (云岭/云麓, 陈昉/陈放, candidate-k288/candidate-k271),
    so a single character drifting into the corpus would make the question answerable and the
    baseline unreadable.
    """
    joined = "\n".join(corpus_text.values())
    present: list[str] = []
    checked = 0
    for case in truth.get("negatives", []):
        proof = case.get("absence_proof")
        if not proof:
            continue
        checked += 1
        pattern = _normalize(str(proof["pattern"]))
        if pattern in joined:
            present.append(f"{case['case_id']}: {proof['pattern']} occurs in my-data")
    assert not present, "a fabrication probe's subject exists after all:\n" + "\n".join(present)
    assert checked == sum(
        case["shape"] == "nonexistent_subject" for case in truth.get("negatives", [])
    ), "every nonexistent_subject case must carry an absence_proof"


def test_the_question_suite_holds_its_declared_shape(truth) -> None:
    """Axes, tiers, id resolution, and the balance the set was authored to.

    The counts are asserted as floors rather than exact numbers: adding questions is how this
    set stays useful, dropping the negative suite or collapsing the tiers is how it stops
    measuring anything.
    """
    ids = {
        entry["truth_id"] for category in CATEGORIES for entry in truth.get(category, [])
    }
    assert len(ids) == sum(len(truth.get(category, [])) for category in CATEGORIES), (
        "duplicate truth ids"
    )

    cases = truth["retrieval_cases"]
    negatives = truth["negatives"]
    for case in cases:
        assert case["axis"] in AXES, f"{case['case_id']}: unknown axis {case['axis']}"
        assert case["difficulty"] in DIFFICULTIES, f"{case['case_id']}: unknown tier"
        unknown = set(case["expected_truth_ids"]) - ids
        assert not unknown, f"{case['case_id']} expects unknown truth {sorted(unknown)}"
    for case in negatives:
        assert case["shape"] in NEGATIVE_SHAPES, f"{case['case_id']}: unknown shape"
        assert case["difficulty"] in DIFFICULTIES, f"{case['case_id']}: unknown tier"
        assert case["absent"].strip(), f"{case['case_id']}: no statement of what is absent"

    all_ids = [case["case_id"] for case in cases] + [case["case_id"] for case in negatives]
    assert len(set(all_ids)) == len(all_ids), "duplicate case ids"

    total = len(cases) + len(negatives)
    assert total >= 80, f"the suite shrank to {total} questions"
    assert len(negatives) == NEGATIVE_COUNT, (
        "the negative suite is 22 questions: a question that stops being a negative (because the "
        f"corpus grew an answer to it) is replaced, not dropped — it is now {len(negatives)}"
    )
    for shape in NEGATIVE_SHAPES:
        assert sum(case["shape"] == shape for case in negatives) >= 5, (
            f"negative shape {shape} must keep its own line in the scorecard"
        )
    tiers = {tier: 0 for tier in DIFFICULTIES}
    for case in cases + negatives:
        tiers[case["difficulty"]] += 1
    assert all(tiers.values()), f"a difficulty tier went empty: {tiers}"
    assert tiers["L1"] <= total // 2, (
        f"single-fact lookups must stay a minority: L1 is {tiers['L1']}/{total}"
    )


#: A facet is one proposition. These are the joiners that bundle two of them into one string —
#: 「X：Y」, 「X；Y」, 「X，也 Y」, 「X 而不是 Y」 — and a facet that carries one is a facet the judge
#: cannot answer with a single verdict. The check is deliberately conservative: a plain 「，」 is
#: how Chinese writes one clause, so flagging it would fail honest facets and teach nobody
#: anything.
COMPOUND_JOINER = re.compile(r"[：；]|，也|而不是")

#: Quoted terms are stripped before the check rather than whitelisted by facet id. 「客户复核：
#: 未开始」 is a page's own label, not two claims, and a list of exempt ids would have to be
#: maintained by hand and would go stale the moment a facet is renumbered.
QUOTED = (("「", "」"), ("“", "”"), ("（", "）"), ("(", ")"))


def _outside_quotes(text: str) -> str:
    for opener, closer in QUOTED:
        text = re.sub(
            re.escape(opener) + "[^" + re.escape(closer) + "]*" + re.escape(closer), "", text
        )
    return text


def test_no_facet_bundles_two_claims_into_one_proposition(truth) -> None:
    """One facet, one proposition — the property the whole grading rests on.

    The judge returns ONE verdict per facet, so a facet that joins two claims makes that verdict
    unanswerable: an answer that gives the half the question asked and not the qualifier is
    neither `stated` nor `contradicted`, and whichever the judge picks is wrong. The previous
    baseline lost four cases to exactly that (`state-08`'s 「没有付款预计日：没有人给出过这个日期」
    among them), and no amount of judge calibration fixes a facet that cannot be judged.
    """
    bundled = [
        f"{facet['facet_id']}: {facet['text']}"
        for case in truth["retrieval_cases"]
        for facet in case["facets"]
        if COMPOUND_JOINER.search(_outside_quotes(facet["text"]))
    ]
    assert not bundled, (
        "a facet joins two claims and must be split into one facet per proposition:\n"
        + "\n".join(bundled)
    )


#: A question either fixes its time or asks for the current state. These are the tokens that do
#: one or the other — 截至 / 时 / 日 pin it, 当前 / 现在 / 目前 / 最后 / 最新 ask for the latest —
#: and a question carrying none of them is asking about a world that may have moved since the
#: answer was authored.
TIMED_QUESTION = re.compile(r"当前|现在|目前|最后|最新|截至|时|日")


def test_every_undated_question_is_signed_for_in_the_allowlist() -> None:
    """The v6 rule, made mechanical: an undated question is a decision, not an oversight.

    Half of the rigor audit's blocking findings were the same defect — a question with no date,
    scored against a state the corpus later changed, so a library that answered with the CURRENT
    value was marked wrong for being right. The fix per case is to pin the question (and its
    `as_of`) or to re-target the truth at the latest state. What keeps the fix from decaying is
    this: a question that neither pins a date nor asks for the current state must be named in
    the truth file's `undated_ok`, with the reason its answer cannot go stale. Some questions
    honestly belong there — a superseded wording, a closed incident's evidence chain, an
    existential 'did they ever' — and the point is that each one was decided rather than
    forgotten. An entry for a case that no longer needs it is a stale signature and fails too.
    """
    manifest = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    allowlist = manifest["undated_ok"]
    assert isinstance(allowlist, dict), "`undated_ok` must be a map of case id to reason"
    undated = {
        case["case_id"]
        for case in manifest["truth"]["retrieval_cases"]
        if not TIMED_QUESTION.search(case["question"])
    }
    unsigned = sorted(undated - set(allowlist))
    assert not unsigned, (
        "a positive question neither fixes its time nor asks for the current state, and is not "
        f"signed for in `undated_ok`: {unsigned}"
    )
    stale = sorted(set(allowlist) - undated)
    assert not stale, f"`undated_ok` names cases whose questions now carry a time: {stale}"
    for case_id, reason in allowlist.items():
        assert str(reason).strip(), f"{case_id}: an allowlist entry with no reason explains nothing"


def test_the_structure_probe_names_the_rule_it_tests(truth) -> None:
    """A shape probe has to say whose rule it enforces, and the rule has to still be there.

    The corpus forbids MERGING the two chains' status into one pass marker; it does not require
    two canonical documents — it says the two rows may sit side by side as long as each keeps its
    own provenance. What requires separate pages is this example's own compile contract, so the
    probe tests contract conformance, and it says so. Checking the contract quote here is what
    keeps the two from drifting: rewrite the chains family, and this probe fails until someone
    decides whether the shape it asserts is still the one the contract asks for.
    """
    for probe in truth.get("structure_probes", []):
        basis = probe.get("contract_basis")
        assert probe["kind"] != "distinct_documents" or basis, (
            f"{probe['probe_id']}: a document-separation probe must name the CONTRACT rule it "
            "enforces — the corpus forbids merging the two statuses, not sharing one page"
        )
        if basis is None:
            continue
        contract = (EXAMPLE / basis["contract_file"]).read_text(encoding="utf-8")
        assert _normalize(basis["quote"]) in _normalize(contract), (
            f"{probe['probe_id']}: the contract no longer says {basis['quote']!r}"
        )
        assert "契约" in probe["note"], (
            f"{probe['probe_id']}: a probe resting on the contract must say so in its note"
        )


def test_every_negative_case_declares_what_is_absent(truth) -> None:
    """The negative suite's whole content is the absence, and the judge is told it verbatim.

    `absent` is not commentary: it is the sentence handed to the fabrication judge as the thing
    the material does not contain. A missing or lazy one (an echo of the question, a few words)
    turns a fabrication probe into a vibe check, and the resulting verdict would be recorded as
    the library's honesty.
    """
    for case in truth["negatives"]:
        absent = str(case.get("absent") or "").strip()
        assert absent, f"{case['case_id']}: no statement of what is absent"
        assert len(absent) >= 12, f"{case['case_id']}: `absent` is too thin to judge against"
        assert absent != case["question"].strip(), (
            f"{case['case_id']}: `absent` restates the question instead of saying what is missing"
        )
        assert case.get("evidence") or case.get("absence_proof"), (
            f"{case['case_id']}: an absence has to be proven — a corpus quote for the state that "
            "IS recorded, or an absence_proof pattern that occurs nowhere"
        )


def test_the_recorded_baseline_carries_its_reconciliation(truth) -> None:
    """A re-scored line says what moved since the last one, in the artifacts themselves.

    The reference line is read by people who were not here: the two committed reports must open
    with the comparison and with the one sentence that keeps a ruler change from being read as a
    library change. The declaration behind that section is checked too — every group a case can
    be filed under has to exist, or a moved case would land in a heading with no explanation.
    """
    manifest = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    config = manifest["reconciliation"]
    for name in ("report.md", "opc-eval.md"):
        text = (EXAMPLE / "build-record" / "eval" / name).read_text(encoding="utf-8")
        assert "## Reconciliation" in text, f"{name} carries no reconciliation section"
        # The headline is the set's own, not a fixed sentence: a line whose numbers moved
        # because the DEPLOYMENT changed has to say that, and one whose ruler moved has to say
        # that instead. What is enforced is that the committed report carries the declaration
        # the set makes, so the two cannot drift apart.
        assert str(config["headline"]) in text, (
            f"{name}'s reconciliation does not carry the headline the truth set declares"
        )
        assert str(config["basis"]) in text, (
            f"{name}'s reconciliation does not say what did and did not change underneath it"
        )

    keys = {str(group["key"]) for group in config["groups"]}
    for group in config["groups"]:
        assert group["title"].strip() and group["note"].strip(), (
            f"{group['key']}: a group with no note explains nothing"
        )
        # Every group names the truth-set revision that introduced it, so a moved case is filed
        # under a change that lies BETWEEN the two lines compared rather than under one both
        # were already scored with.
        assert re.fullmatch(r"v\d+", str(group.get("since") or "")), (
            f"{group['key']}: no `since` revision (e.g. \"v4\")"
        )
    assert set(config["unattributed_group_for"].values()) <= keys
    for case_id, changes in config.get("retired_cases", {}).items():
        assert set(changes) <= keys, f"{case_id}: retired under an unknown group"
    declared = {
        change
        for case in truth["retrieval_cases"] + truth["negatives"]
        for change in case.get("ruler_changes", [])
    }
    assert declared <= keys, f"a case is filed under an undeclared group: {declared - keys}"


def test_the_recorded_line_was_answered_by_the_shipped_engine_config() -> None:
    """The reference numbers came from the engine this example ships, not from a flag.

    `evidence_strategy` is what composes the context an answer stands on, so a baseline
    produced with a value other than the committed one measures a deployment nobody gets. The
    runner records what the ANSWERING PROCESS reported per question, so this compares the file
    a developer reads with what actually answered — which also catches the honest mistake of
    editing `recall.yaml` and forgetting to restart the container that serves it.
    """
    engine = (EXAMPLE / "engine" / "recall" / "recall.yaml").read_text(encoding="utf-8")
    declared = re.search(r"^evidence_strategy:\s*(\S+)", engine, re.MULTILINE)
    assert declared, "the example's recall.yaml states no evidence_strategy"
    payload = json.loads(
        (EXAMPLE / "build-record" / "eval" / "opc-eval.json").read_text(encoding="utf-8")
    )
    assert payload.get("answering_evidence_strategy") == declared.group(1), (
        "the committed line was answered under "
        f"{payload.get('answering_evidence_strategy')!r} while the shipped engine states "
        f"{declared.group(1)!r}"
    )


def test_the_set_never_enters_the_ingested_material(truth) -> None:
    """I6, at the level of file placement: the answers must not be importable as sources.

    `my-data/` is what gets ingested. A truth set placed there would be compiled into the very
    library it grades, and every question would become a lookup of its own answer.
    """
    assert not (CORPUS / "opc-truth.json").exists()
    assert not list(CORPUS.glob("*eval*"))
    assert TRUTH_PATH.is_file() and TRUTH_PATH.parent.name == "eval"
    assert truth["retrieval_cases"], "sanity: the loaded manifest is the real one"


# ──────────────────────────────────────────────────────── the judge's own calibration suite


CALIBRATION_PATH = EXAMPLE / "eval" / "judge-calibration.json"
VERDICTS = {"stated", "omitted", "contradicted"}
#: The one variant the suite reports rather than gates on. Whether a role form identifies a
#: person is a judgement call; every other variant, `approximate` now included, is a rule the
#: judge's prompt states in one line, so a disagreement there is the ruler being wrong.
NON_BLOCKING = {"name_variant"}
#: Items per variant. Three is the floor because one item is an anecdote and two cannot show a
#: verdict holding across a change of wording.
MIN_ITEMS_PER_VARIANT = 3

#: Chinese numerals, so a figure is compared by VALUE and not by glyph. The truth set writes
#: the pilot quote as 一万八千元 and the calibration wrote it as 18000: one figure in two
#: spellings, which a comparison over Arabic digits alone reads as two different numbers — and
#: did, until this converter closed the hole. Enough of the system for a corpus of records:
#: digits, the three small units, and the section units.
_CJK_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
    "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CJK_UNITS = {"十": 10, "百": 100, "千": 1000}
_CJK_SECTIONS = {"万": 10000, "亿": 100000000}
_CJK_RUN = re.compile(
    "[" + "".join((*_CJK_DIGITS, *_CJK_UNITS, *_CJK_SECTIONS)) + "]+"
)


def _cjk_value(run: str) -> int:
    """The value of one run of Chinese numerals: 一万八千 → 18000, 五千四百 → 5400, 六 → 6."""
    total = section = number = 0
    for char in run:
        if char in _CJK_DIGITS:
            number = _CJK_DIGITS[char]
        elif char in _CJK_UNITS:
            section += (number or 1) * _CJK_UNITS[char]
            number = 0
        else:
            section = (section + number) * _CJK_SECTIONS[char]
            total += section
            section = number = 0
    return total + section + number


def _figures(text: str) -> set[str]:
    """Every figure of three or more digits in a text, in whichever script it is written."""
    found = set(re.findall(r"[0-9]{3,}", text))
    for match in _CJK_RUN.finditer(text):
        value = _cjk_value(match.group(0))
        if value >= 100:
            found.add(str(value))
    return found


@pytest.fixture(scope="module")
def calibration() -> dict:
    return json.loads(CALIBRATION_PATH.read_text(encoding="utf-8"))


def _calibration_text(calibration: dict) -> str:
    """Every model-visible string in the suite, joined — what a leak would have to hide in."""
    parts: list[str] = []
    for item in calibration["facet_items"]:
        parts += [item["facet"], item["question"], item["answer"]]
        parts += [str(row) for row in item.get("examples") or []]
        for row in item.get("evidence") or []:
            parts += [row["corpus_file"], row["quote"]]
    for item in calibration["negative_items"]:
        parts += [item["absent"], item["question"], item["answer"]]
        for row in item.get("cited_spans") or []:
            parts += [row["source"], row["text"]]
    return "\n".join(parts)


def test_the_judge_calibration_covers_every_variant_it_declares(calibration) -> None:
    """The suite's shape: every variant carries items, every item carries a legal verdict.

    A calibration file is only a mechanism while it is complete. A variant declared in the
    catalogue and then left with one item — or with none — reads in the report as a phrasing the
    judge was held to, and is not one; and an item whose `expected` is not a verdict the runner
    can produce could never agree with anything.
    """
    variants = calibration["variants"]
    assert variants, "no variant catalogue"
    assert {
        name for name, row in variants.items() if not row["blocking"]
    } == NON_BLOCKING, "the non-blocking variants are a stated judgement call, not a free list"

    counts: dict[str, int] = {name: 0 for name in variants}
    ids: set[str] = set()
    for item in calibration["facet_items"]:
        assert item["item_id"] not in ids, f"duplicate item id {item['item_id']}"
        ids.add(item["item_id"])
        assert item["variant"] in variants, f"{item['item_id']}: variant off the catalogue"
        assert item["expected"] in VERDICTS, f"{item['item_id']}: {item['expected']!r}"
        assert item.get("evidence"), f"{item['item_id']}: the fact rests on nothing"
        assert str(item.get("why") or "").strip(), f"{item['item_id']}: no reason recorded"
        counts[item["variant"]] += 1
    thin = {name: n for name, n in counts.items() if n < MIN_ITEMS_PER_VARIANT}
    assert not thin, f"variants with fewer than {MIN_ITEMS_PER_VARIANT} items: {thin}"

    for item in calibration["negative_items"]:
        assert item["item_id"] not in ids, f"duplicate item id {item['item_id']}"
        ids.add(item["item_id"])
        assert item["shape"] in NEGATIVE_SHAPES, f"{item['item_id']}: {item['shape']!r}"
        assert isinstance(item["expected_fabricated"], bool), item["item_id"]
        premise = item.get("expected_premise_accepted")
        if item["shape"] == "false_premise":
            assert isinstance(premise, bool), (
                f"{item['item_id']}: a false_premise item carries both verdicts"
            )
        else:
            assert premise is None, (
                f"{item['item_id']}: only a false_premise item has a premise verdict"
            )
    for shape in NEGATIVE_SHAPES:
        assert sum(
            item["shape"] == shape for item in calibration["negative_items"]
        ) >= MIN_ITEMS_PER_VARIANT, f"the negative suite is thin on {shape}"


def test_the_calibration_borrows_no_name_or_number_from_this_corpus(
    calibration, corpus_text
) -> None:
    """The leak guard, conservative by construction and mechanical in both directions.

    Names first: the corpus's cast is read off the transcripts themselves — every speaker label
    at the head of a line — together with the near-miss subjects the negative suite invents.
    None of them may occur anywhere in the calibration. Numbers second: every figure of three or
    more digits the calibration uses must be declared in its own `numbers` list, and no declared
    figure may be one the truth set uses — in EITHER script, because the truth set writes the
    pilot quote as 一万八千元 and a comparison over Arabic digits alone let that figure through
    into the calibration and call it clean. Three digits rather than one because 「一个」 and a
    two-digit day are the vocabulary of any Chinese sentence; the check is deliberately
    conservative — it cannot catch a coincidence of everyday words, and it does catch every
    proper noun and every distinctive figure, which is where a leak would live.

    The suite calibrates the ruler. An item wearing this corpus's names would put the truth
    set's own material in front of the judge and reward this build's wording, which is the one
    thing a calibration must not do.
    """
    truth_source = TRUTH_PATH.read_text(encoding="utf-8")
    corpus_join = "\n".join(corpus_text.values())
    names = {
        match.group(1)
        for text in corpus_text.values()
        for match in re.finditer(r"(?m)^([一-鿿]{2,4})\s*[:：]", text)
    }
    truth_manifest = json.loads(truth_source)
    for case in truth_manifest["truth"].get("negatives", []):
        proof = case.get("absence_proof")
        if proof:
            names.add(str(proof["pattern"]))
    assert len(names) > 5, "sanity: no cast could be read off the corpus"

    text = _calibration_text(calibration)
    normalized = _normalize(text)
    borrowed = sorted(name for name in names if _normalize(name) in normalized)
    assert not borrowed, f"the calibration names this corpus's own subjects: {borrowed}"

    declared = set(calibration["cast"])
    assert declared, "the calibration declares no cast"
    present = sorted(
        name for name in declared if _normalize(name) in _normalize(corpus_join + truth_source)
    )
    assert not present, f"a calibration name exists in the corpus after all: {present}"

    used = set(re.findall(r"[0-9]{3,}", text))
    undeclared = sorted(used - set(calibration["numbers"]))
    assert not undeclared, f"figures used but not declared in `numbers`: {undeclared}"
    shared = sorted(set(calibration["numbers"]) & _figures(truth_source))
    assert not shared, f"the calibration reuses the truth set's own figures: {shared}"


def test_the_calibration_never_enters_the_ingested_material() -> None:
    """Same placement rule as the truth set: a calibration item must not become a source."""
    assert CALIBRATION_PATH.is_file() and CALIBRATION_PATH.parent.name == "eval"
    assert not (CORPUS / CALIBRATION_PATH.name).exists()
