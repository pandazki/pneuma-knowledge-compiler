#!/usr/bin/env python3
"""Score a built OPC library against the frozen truth set in `opc-truth.json`.

    uv run python examples/opc/eval/run_eval.py --mode mechanical --out var/eval
    uv run python examples/opc/eval/run_eval.py --mode full --out var/eval   # needs the key
    uv run python examples/opc/eval/run_eval.py --mode judge --out var/eval  # calibrate the judge

WHAT THIS IS FOR
----------------
A regression line. The library this example ships is one build of one corpus by one agent
generation; the only way a later contract or framework change can claim it made the library
better is to score the same questions on the same material and put the two scorecards side by
side. So the questions are frozen, the material is frozen, and this command is the harness.

WHAT IT ADDS TO THE EVAL PACKAGE, AND WHY
-----------------------------------------
`pneuma_knowledge_eval` is the frame: six metric groups over a trajectory of compile
checkpoints, with group F (usability QA) asked over a live recall path. Three things this
corpus needs do not fit inside it, and they are computed here rather than bent into it:

1. **A question axis and a difficulty tier.** The package reports QA accuracy under the four
   ADMISSION categories a truth entry carries (`durable_facts` / `decisions` / `commitments`
   / `constraints`). Those describe what a fact IS, not what asking about it tests. This
   runner carries `axis` and `difficulty` on each case and reports both breakdowns beside the
   package's own.

2. **A negative suite.** Fabrication resistance cannot be expressed as a truth entry: a
   labelled statement enters group B's recall, so "the corpus does not record this" would be
   scored as a fact the library failed to admit. The negatives therefore live under their own
   key and are scored here — three shapes (`unanswerable_detail`, `nonexistent_subject`,
   `false_premise`), each on its own line, never averaged into the positive accuracy.

3. **Structure probes.** Some of what this corpus demands is a property of the library's
   SHAPE, not of any one answer — two evidence chains whose statuses the material explicitly
   forbids merging must not end up filed as one page. That is scored mechanically over
   canonical, keyless.

EVERY TRUTH VALUE IS PINNED TO A CORPUS SPAN, MECHANICALLY
----------------------------------------------------------
Each labelled entry, each question and each FACET carries `evidence`: a `corpus_file` and a
VERBATIM quote from it. Before anything is scored, this runner resolves every quote against
L0 — the ingested block text, fetched from the running stack — and reports the resulting
`<source_id> ¶<block>` locator. A quote that does not resolve is a hard error, not a warning:
the whole claim of this set is that its answers came from the corpus, and an unresolvable
quote means one did not. Source ids are assigned at ingest, so they are a property of a BUILD,
never of the set; the set carries filenames and quotes, and the locators are recomputed on
every run. That is what makes the set portable to a rebuild of the same corpus.

The corpus is `my-data/` PLUS the owner statement `build-record/exercise.py` sends — the 191st
source, part of what a developer restores, and therefore part of what the library is expected
to know. Evidence resting on it carries `corpus_source: "owner_statement"`: the quote is read
back out of the `OWNER_DIALOGUE` literal in that script (parsed, never imported) and located in
the one ingested `owner_dialogue` source. Binding it by source FAMILY rather than by title
keeps the set portable — the title is the adapter's, the family is the contract's.

THE JUDGE IS THE GRADER, PER FACET, AND IT GRADES ENTAILMENT
------------------------------------------------------------
A positive case's expected answer is a list of facets, each ONE proposition, each tagged `core` or
`detail`. Every facet of every answered case goes to the LLM judge, which returns `stated` /
`omitted` / `contradicted` with one line of reason. A case is correct when every CORE facet is
stated; detail facets are scored on their own line (`detail_recall`) and never gate. Nothing is
decided mechanically: the normalized character-containment score is computed and recorded beside
each verdict as a diagnostic, so a later reader can see where judge and string agreed, but it can
neither pass nor fail a facet. Omission and contradiction are counted separately, because
terseness and dishonesty are different regressions and a single "wrong" hides that.

The question the judge is asked is ENTAILMENT: does the answer's content commit to this fact —
paraphrase, different wording, a more specific statement, the fact inside a longer sentence, the
fact following necessarily from what was said. It used to be asked whether the answer "states"
the facet, and the two are not the same question: an answer saying 「目前没有记录到付款预计日期」
does not state 「没有付款预计日」 and entails it exactly. Surface grading punished the wrong thing,
and the system prompt now carries one worked example of each verdict so the line is drawn in the
prompt rather than in whatever the model brings.

A facet may also carry `examples` — a list beside its proposition, never inside it. Some
propositions are existential (「他至少做过一件材料记下的事」), and such a facet still has to exclude
an invented act; naming the corpus's own acts in a parenthesis inside the proposition did that, and
turned the illustration into the thing being graded — the previous line's `join-03` deep answer
reported one of the corpus's two documented acts and was scored `omitted` for not reporting the
other. The list now arrives under a header saying what it is: illustrations of what would satisfy
the proposition, no checklist, and anything else the material records satisfies it too. An invented
act still fails, because the judge is shown the facet's corpus quote in the same prompt. A facet
with no `examples` renders byte-for-byte the prompt it rendered before the field existed.

THE NEGATIVE JUDGE READS WHAT THE ANSWER STOOD ON
-------------------------------------------------
The fabrication auditor used to see the question, the answer, and one sentence saying what the
material does not contain. That is not enough to tell invention from grounded detail: an answer
that abstained and added one true cited fact was indistinguishable from one that made the fact up,
and three of four "fabrications" on the previous line were the grader's error. Every `[cite: sid
¶a-b]` an answer carries is now resolved to its L0 text — the same L0 this runner already
harvested — and those spans go to the judge beside the absence statement, with the rule stated:
a detail a cited span supports is not fabrication even when it is not what was asked. `false_
premise` cases carry a second, independent verdict, `premise_accepted`, on its own column:
refusing a false premise and describing the real state is right, and swallowing the premise is a
different failure from inventing a value.

The auditor is also told, for every shape, that the absence statement it is handed is TRUE. A
rejection can only be made by asserting the negative — 「陈放并不是反对那项材料变更」,
「记录不支持"采购接受报价后合同金额调整"这一前提」 — and the previous line graded both of those as
fabrication for asserting, word for word, what this set's own `absent` line says the corpus
records. What is graded is what the answer adds BEYOND the absence statement and beyond the cited
spans; the negative itself is a correction, and never the invention.

THE RULER IS CALIBRATED BEFORE IT IS USED
-----------------------------------------
Every verdict on this line is an LLM's, which makes the judge's own consistency a property of
the measurement rather than a hope about the model. `eval/judge-calibration.json` is a suite of
items — one fact, one answer, one verdict a competent reader can state in a line — that varies
exactly the thing a real answer varies: PHRASING. Numerals against digits, dates in four forms,
六周 against 42 天, a hedge that still commits against alternatives that do not, an exclusive
list against a partial one, an old state told as history against the same state told as now, an
English answer to a Chinese fact. Each item declares its `variant`, and each variant declares in
the file whether it BLOCKS.

`--mode judge` runs the suite through the same `judge_facet` and `judge_negative` the scoring
calls — there is no second copy of either prompt — and writes `judge-calibration.json` / `.md`:
agreement per variant, the judge model, the prompt hash, and every disagreement with the judge's
own reply. It exits 1 when a blocking variant is not at 100%. `--mode full` runs it FIRST and
refuses to score when it does not pass, before the stack is asked for anything: a ruler that
fails its own calibration cannot produce a line comparable with any other line. The result is
recorded in the scored artifact's header beside the prompt hash, because the hash says which
words graded a line and the calibration says how those words did on phrasings whose verdicts
are not in dispute.

One variant declares itself non-blocking — `name_variant`, because whether a role form
identifies a person is a judgement call where a careful grader can differ; it is reported and
never gates. Every other variant is a rule the prompt states in one line, so a disagreement
there is the ruler being wrong.

The suite is synthetic and belongs to a domain this corpus knows nothing about, deliberately: a
calibration item that named this corpus's people or numbers would leak the truth set into the
judge's context and reward this build's own wording. `tests/test_opc_eval_set.py` holds it to
that mechanically.

THE LINE SAYS WHAT MOVED SINCE THE LAST ONE
-------------------------------------------
`--previous label=…/opc-eval.json` (repeatable) renders a reconciliation at the top of both
reports: the compared lines' headline numbers and judge-prompt hashes, then every case whose
status changed, filed under the ruler revision the truth set says touched it (`ruler_changes` on
the case, `reconciliation.groups` in the manifest). The grouping is mechanical, not editorial —
a case the truth set does not name has carried the same facets since that line, so whatever moved
under it moved for another reason, and the section says so instead of implying a library change.

TWO ANSWER LANES, NEVER AVERAGED
--------------------------------
Aggregate and join questions, and every case whose truth the compile contract leaves in the raw
material (`expected_via: "verbatim"`), are asked twice — on the fast lane and on the deep lane —
and reported per lane. Those are the questions where the lanes are expected to differ; the rest
stay fast-only because a second lane costs a model call per question and buys nothing where the
answer is on one page. One number over both lanes would describe no configuration anyone runs.

THE ANSWERING ARM ASKS AS A SILENT VISITOR
------------------------------------------
Measuring a library is not using it. `visitor_class: silent` leaves no consultation row, so
running this suite — eighty questions, however often — never rewrites the attention ledger
the example ships. `answer_format: structured` is what makes `no_record` legible: only a
structured answer reports an `answer_kind`, and the negative suite is scored on it.

THE RUN IS CONCURRENT, THE ARTIFACT IS NOT
------------------------------------------
Every call the answered arms make is latency: an HTTP round trip to the stack for an answer, one
to the provider for a verdict. Nothing is computed here between them, so asking and judging one
call at a time spent the run's whole wall clock waiting on sockets. The suite therefore launches
every (case, lane) at once and bounds what is in flight with one semaphore (`--concurrency`,
default 32; `1` is the old serial behaviour exactly). The only dependency kept is the real one —
a facet is judged against its own case's answer — and the two lanes of a case are independent
calls, sequenced with nothing.

None of that reaches the scorecard. Results are gathered in submission order rather than
completion order, so `opc-eval.json`, `opc-eval.md`, `scorecard.json` and `report.md` are the
same bytes at concurrency 1 and at concurrency 64. The one line that does change is the
`throughput` block — calls, wall seconds, bound — which is a cost line and is reported apart
from every quality number, as this repository requires of the two kinds of measurement.

L0 IS HARVESTED FROM THE API, NOT FROM POSTGRES
-----------------------------------------------
Five of the package's metrics need the raw sources a canonical repository does not carry. The
package takes them as `pg/*.json.gz` dumps and deliberately offers no live-database flag, so
this runner writes those dumps from the stack's own read-only source endpoints. Same numbers,
one way to produce them, no second database connection.
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import gzip
import hashlib
import json
import os
import random
import re
import sys
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
EXAMPLE_ROOT = HERE.parent
REPO_ROOT = EXAMPLE_ROOT.parent.parent

if str(REPO_ROOT / "packages" / "pneuma-knowledge-eval" / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "packages" / "pneuma-knowledge-eval" / "src"))

from pneuma_knowledge_eval.artifacts import load_repo_trajectory  # noqa: E402
from pneuma_knowledge_eval.errors import EvalDependencyError, EvalInputError  # noqa: E402
from pneuma_knowledge_eval.metrics.common import L0_ABSENT, char_similarity  # noqa: E402
from pneuma_knowledge_eval.qa import build_truth_judge  # noqa: E402
from pneuma_knowledge_eval.scorecard import (  # noqa: E402
    build_scorecard,
    unavailable_because,
    write_outputs,
)
from pneuma_knowledge_eval.truth import load_frozen_truth_manifest  # noqa: E402

DEFAULT_TRUTH = HERE / "opc-truth.json"
DEFAULT_CALIBRATION = HERE / "judge-calibration.json"
DEFAULT_CORPUS = EXAMPLE_ROOT / "my-data"
DEFAULT_OWNER_STATEMENT = EXAMPLE_ROOT / "build-record" / "exercise.py"
DEFAULT_CANONICAL = EXAMPLE_ROOT / "data" / "canonical"
DEFAULT_API = "http://127.0.0.1:28000"
DEFAULT_USER = "u-opc-lin"

#: The question axes this set is authored along. A case id must start with one of them, so a
#: mistyped axis is a load error rather than a silently uncounted case.
AXES = (
    "state",  # the current value of something the corpus changed
    "history",  # what it used to be, and when it changed
    "chain",  # answerable only by walking an evidence chain end to end
    "set",  # closed-set enumeration, with its residue
    "definition",  # what X is, in one line
    "calendar",  # a window of time, or a status as of a date
    "aggregate",  # a computation over many sources
    "join",  # multi-hop: no single page holds the answer
    "miss",  # the negative suite (three shapes, see NEGATIVE_SHAPES)
)

#: L1 single-fact lookup … L5 multi-hop. A tier is a property of the QUESTION, not of the
#: answer, so it is authored, never derived.
DIFFICULTIES = ("L1", "L2", "L3", "L4", "L5")

NEGATIVE_SHAPES = ("unanswerable_detail", "nonexistent_subject", "false_premise")

#: How a case's truth is expected to reach the answer. `canonical` — the compile contract admits
#: it to the library; `verbatim` — the contract leaves it in the raw material on purpose, so the
#: answer has to come through L0/L1/L2 (invariant I3). Reported as its own breakdown, so a miss
#: on a `verbatim` case is attributable to retrieval rather than to admission judgement.
EXPECTED_VIA = ("canonical", "verbatim")

#: The two answer lanes. `fast` is the whole suite; `deep` is the subset `lanes_for` selects.
LANES = ("fast", "deep")

#: Per-facet judge verdicts. `omitted` and `contradicted` are both failures and are counted
#: apart on purpose: an answer that leaves a fact out has gone terse, one that denies it has
#: gone wrong, and a regression line that calls both "incorrect" cannot tell them apart.
VERDICTS = ("stated", "omitted", "contradicted")

#: The tags a facet can carry. Core facets gate the case; detail facets are reported alone.
FACET_TAGS = ("core", "detail")

#: How many provider calls this run keeps in flight. Every call in the answered arms is latency
#: — an HTTP round trip to the stack, or one to the judge — and none of them computes anything
#: locally, so the serial run spent nearly all of its wall clock waiting on sockets. `1` restores
#: exactly the serial behaviour; the number is a knob rather than a constant because the ceiling
#: belongs to the machine and the provider account the run is made on, not to the measurement.
DEFAULT_CONCURRENCY = 32

#: Statuses a second attempt cannot fix: a bad credential, a malformed request, a route that is
#: not there. Everything else a call raises — a timeout, a dropped connection, a 429, a provider
#: 5xx — is treated as transient and retried. The asymmetry is deliberate: retrying a permanent
#: failure 32 ways at once turns one misconfiguration into a few hundred wasted requests, and
#: NOT retrying an unfamiliar exception would quietly narrow what the serial run already survived.
PERMANENT_STATUSES = frozenset({400, 401, 403, 404, 405, 422})


# ─────────────────────────────────────────────────────────────────── corpus ↔ L0 binding


def _normalize(text: str) -> str:
    """Fold to the form a quote and an ingested block can be compared in."""
    return "".join(
        ch for ch in unicodedata.normalize("NFKC", text) if not ch.isspace()
    )


def owner_statement_text(script: Path) -> str:
    """The owner statement's turns, read out of `exercise.py` without importing it.

    The script drives a live stack and imports the project's own driver, so importing it here to
    reach one literal would start doing things. `ast.literal_eval` over the assignment reads the
    same bytes with no side effect, and keeps this runner's grounding claim honest: the quote is
    checked against what the exercise SENDS, not against what the library later says about it.
    """
    if not script.is_file():
        raise EvalInputError(f"no owner-statement script at {script}")
    tree = ast.parse(script.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(target, "id", "") == "OWNER_DIALOGUE" for target in node.targets):
            continue
        dialogue = ast.literal_eval(node.value)
        return "\n".join(str(turn["text"]) for turn in dialogue["turns"])
    raise EvalInputError(f"{script} defines no OWNER_DIALOGUE statement")


@dataclass
class Corpus:
    """The raw material, indexed the two ways the truth set addresses it."""

    #: corpus filename → (title, date) from its frontmatter
    front: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: corpus filename → normalized full text
    text: dict[str, str] = field(default_factory=dict)
    #: the owner statement's normalized text — the 191st source, authored in exercise.py
    owner: str = ""

    @classmethod
    def load(cls, root: Path, *, owner_script: Path | None = None) -> Corpus:
        if not root.is_dir():
            raise EvalInputError(f"no corpus directory at {root}")
        corpus = cls()
        if owner_script is not None:
            corpus.owner = _normalize(owner_statement_text(owner_script))
        for path in sorted(root.glob("*.md")):
            raw = path.read_text(encoding="utf-8")
            head = re.search(r"^---\n(.*?)\n---", raw, re.S)
            block = head.group(1) if head else ""
            title = re.search(r'^title:\s*"?(.*?)"?\s*$', block, re.M)
            date = re.search(r"^date:\s*(\S+)", block, re.M)
            if not title or not date:
                raise EvalInputError(f"{path.name} has no title/date frontmatter")
            corpus.front[path.name] = (title.group(1), date.group(1))
            corpus.text[path.name] = _normalize(raw)
        if not corpus.front:
            raise EvalInputError(f"{root} holds no corpus files")
        return corpus


@dataclass
class L0:
    """The ingested half: source rows and their verbatim blocks, straight from the stack."""

    sources: list[dict[str, Any]]
    blocks: list[dict[str, Any]]

    def owner_dialogue_ids(self) -> list[str]:
        """Every ingested source that arrived under the owner-dialogue contract."""
        return [
            str(row["source_id"])
            for row in self.sources
            if str(row.get("kind") or "") == "owner_dialogue"
        ]

    def by_title_date(self) -> dict[tuple[str, str], str]:
        out: dict[tuple[str, str], str] = {}
        for row in self.sources:
            key = (str(row.get("title") or ""), str(row.get("occurred_on") or ""))
            out.setdefault(key, str(row["source_id"]))
        return out

    def blocks_by_source(self) -> dict[str, list[str]]:
        ordered: dict[str, dict[int, str]] = {}
        for row in self.blocks:
            ordered.setdefault(str(row["source_id"]), {})[int(row["block_index"])] = str(
                row["text"]
            )
        return {
            sid: [rows[index] for index in sorted(rows)] for sid, rows in ordered.items()
        }

    def write_pg_dumps(self, out_dir: Path) -> Path:
        """Write the `pg/` shape the eval package takes for the L0 half of a trajectory."""
        pg = out_dir / "pg"
        pg.mkdir(parents=True, exist_ok=True)
        for name, rows in (("sources", self.sources), ("blocks", self.blocks)):
            with gzip.open(pg / f"{name}.json.gz", "wt", encoding="utf-8") as handle:
                json.dump(rows, handle, ensure_ascii=False)
        return pg


def harvest_l0(api: str, user: str, *, timeout: float = 120.0) -> L0:
    """Read every source and every block through the stack's read-only L0 endpoints."""
    import httpx

    base = api.rstrip("/")
    sources: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    with httpx.Client(timeout=timeout) as client:
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": 500}
            if cursor:
                params["cursor"] = cursor
            response = client.get(
                f"{base}/v1/users/{user}/sources", params=params
            )
            response.raise_for_status()
            body = response.json()
            items = body.get("items") or []
            sources.extend(items)
            cursor = (body.get("page") or {}).get("next_cursor")
            if not cursor or not items:
                break
        for row in sources:
            sid = str(row["source_id"])
            detail = client.get(f"{base}/v1/users/{user}/sources/{sid}")
            detail.raise_for_status()
            payload = detail.json()
            row["created_at"] = row.get("created_at") or payload.get("created_at")
            row["kind"] = row.get("kind") or payload.get("kind")
            for block in payload.get("blocks") or []:
                blocks.append(
                    {
                        "source_id": sid,
                        "block_index": int(block["index"]),
                        "text": str(block.get("text") or ""),
                    }
                )
    if not sources:
        raise EvalInputError(f"{api} reports no sources for {user}")
    return L0(sources=sources, blocks=blocks)


@dataclass
class Locator:
    """One resolved evidence pointer: a corpus quote, found in an ingested block."""

    corpus_file: str
    quote: str
    source_id: str | None
    block_index: int | None
    cite: str | None
    reason: str = ""

    def as_json(self) -> dict[str, Any]:
        return {
            "corpus_file": self.corpus_file,
            "quote": self.quote,
            "source_id": self.source_id,
            "block": self.block_index,
            "cite": self.cite,
            **({"reason": self.reason} if self.reason else {}),
        }


class EvidenceResolver:
    """Turns `(corpus_file, quote)` into this build's `<source_id> ¶<block>` locator.

    The truth set never stores a source id. Ids are assigned at ingest, so storing one would
    bind the set to a single build and make it unusable for the regression it exists for.
    """

    def __init__(self, corpus: Corpus, l0: L0) -> None:
        self._corpus = corpus
        self._by_key = l0.by_title_date()
        self._blocks = l0.blocks_by_source()
        self._owner_sources = l0.owner_dialogue_ids()

    def resolve(self, corpus_file: str, quote: str, corpus_source: str = "") -> Locator:
        if corpus_source == "owner_statement":
            return self._resolve_owner(corpus_file, quote)
        normalized = _normalize(quote)
        if corpus_file not in self._corpus.front:
            return Locator(corpus_file, quote, None, None, None, "no such corpus file")
        if normalized not in self._corpus.text[corpus_file]:
            return Locator(
                corpus_file, quote, None, None, None, "quote is not in the corpus file"
            )
        sid = self._by_key.get(self._corpus.front[corpus_file])
        if sid is None:
            return Locator(
                corpus_file, quote, None, None, None, "corpus file was never ingested"
            )
        for index, text in enumerate(self._blocks.get(sid, [])):
            if normalized in _normalize(text):
                return Locator(corpus_file, quote, sid, index, f"[cite: {sid} ¶{index}]")
        return Locator(
            corpus_file,
            quote,
            sid,
            None,
            None,
            "quote spans block boundaries in this build's chunking",
        )

    def _resolve_owner(self, corpus_file: str, quote: str) -> Locator:
        """Locate a quote from the owner statement: authored in the script, ingested as a source.

        Two halves, both mechanical. The quote must occur in what `exercise.py` SENDS — that is
        the grounding claim, and it is checked against the script rather than against the stack.
        Then it must be found in an ingested `owner_dialogue` source, which is how the library
        received it. A build that never ran the exercise fails here with that reason, rather than
        scoring the two supersession questions against material it was never given.
        """
        normalized = _normalize(quote)
        if not self._corpus.owner:
            return Locator(corpus_file, quote, None, None, None, "owner statement not loaded")
        if normalized not in self._corpus.owner:
            return Locator(
                corpus_file, quote, None, None, None, "quote is not in the owner statement"
            )
        if not self._owner_sources:
            return Locator(
                corpus_file,
                quote,
                None,
                None,
                None,
                "this build ingested no owner_dialogue source (run build-record/exercise.py)",
            )
        for sid in self._owner_sources:
            for index, text in enumerate(self._blocks.get(sid, [])):
                if normalized in _normalize(text):
                    return Locator(corpus_file, quote, sid, index, f"[cite: {sid} ¶{index}]")
        return Locator(
            corpus_file,
            quote,
            self._owner_sources[0],
            None,
            None,
            "quote is in the statement but in no ingested block of it",
        )


# ─────────────────────────────────────────────────────────────────────── the answering arm


def _status_of(exc: BaseException) -> int | None:
    """The HTTP status behind an exception, however the client happens to carry it."""
    response = getattr(exc, "response", None)
    for value in (getattr(response, "status_code", None), getattr(exc, "status_code", None)):
        if isinstance(value, int):
            return value
    return None


def is_transient(exc: BaseException) -> bool:
    """Whether a second attempt could plausibly succeed. Unknown failures count as transient."""
    status = _status_of(exc)
    return not (status is not None and status in PERMANENT_STATUSES)


class CallGate:
    """The bound on provider calls in flight, and the tally behind the throughput line.

    This is the whole concurrency design in one object. Every call the answered arms make goes
    through `run`, the suite launches every case at once and keeps only the dependency that is
    real — a facet is judged against its own case's answer — and this semaphore is what keeps a
    few hundred launched coroutines from becoming a few hundred simultaneous requests. The bound
    is a property of the run, not of the measurement: the same calls in a different order return
    the same verdicts, and the rows are reassembled in truth-set order afterwards, so the
    artifacts do not know how many were in flight.

    Retry lives here too, for the same reason it lived in `with_retry` before: one run has no
    partial result, so a single transient 500 forty minutes in threw away the whole baseline.
    Retrying TRANSPORT is not selection — retrying an answer or a verdict you did not like would
    be, and nothing here does it: the retry sits below the point where any content is looked at.
    A call that exhausts its attempts stops the run under the label of the case that made it,
    which is the same hard stop the serial runner had, with the case now named.
    """

    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise EvalInputError(f"--concurrency must be at least 1, got {limit}")
        self.limit = limit
        self._sem: asyncio.Semaphore | None = None
        self.calls = 0
        self.attempts = 0
        self.retries = 0
        self.in_flight = 0
        self.peak_in_flight = 0
        self._started: float | None = None
        self.elapsed = 0.0

    def open(self) -> None:
        """Bind the semaphore to the loop about to use it, and start the wall clock.

        Constructed here rather than in `__init__` because the gate is built while arguments are
        being read and used inside `asyncio.run`; a semaphore made under one loop and awaited
        under another is the classic way this kind of runner starts hanging.
        """
        self._sem = asyncio.Semaphore(self.limit)
        self._started = time.monotonic()

    def close(self) -> None:
        if self._started is not None:
            self.elapsed = time.monotonic() - self._started
            self._started = None

    async def run(
        self, call, *, label: str, attempts: int = 4, base_delay: float = 2.0
    ) -> Any:
        if self._sem is None:
            raise EvalDependencyError("CallGate.open() must run inside the event loop first")
        last: BaseException | None = None
        for attempt in range(attempts):
            self.attempts += 1
            try:
                async with self._sem:
                    self.in_flight += 1
                    self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
                    try:
                        result = await call()
                    finally:
                        self.in_flight -= 1
            except Exception as exc:  # transport, timeout, 429, provider 5xx — never a verdict
                last = exc
                if not is_transient(exc) or attempt == attempts - 1:
                    break
                self.retries += 1
                # Jittered, so a provider that rate-limits the whole batch at once does not get
                # the whole batch back at once. The jitter moves timing only; nothing downstream
                # reads a clock.
                delay = base_delay * (2**attempt) * (1.0 + random.random() / 2)
                print(
                    f"note: {label}: {type(exc).__name__}: {exc} — retrying "
                    f"({attempt + 1}/{attempts - 1}) in {delay:.1f}s",
                    file=sys.stderr,
                )
                await asyncio.sleep(delay)
                continue
            self.calls += 1
            return result
        assert last is not None
        print(f"ERROR: {label}: {type(last).__name__}: {last}", file=sys.stderr)
        raise EvalDependencyError(f"{label}: {type(last).__name__}: {last}") from last

    def summary(self) -> dict[str, Any]:
        """The throughput row the artifact carries: what was spent, how fast, how wide."""
        return {
            "concurrency": self.limit,
            "calls": self.calls,
            "attempts": self.attempts,
            "retries": self.retries,
            "peak_in_flight": self.peak_in_flight,
            "wall_seconds": round(self.elapsed, 3),
            "calls_per_second": (
                round(self.calls / self.elapsed, 3) if self.elapsed > 0 else None
            ),
        }

    def line(self) -> str:
        row = self.summary()
        return (
            f"throughput: {row['calls']} calls in {row['wall_seconds']}s at concurrency "
            f"{row['concurrency']} (peak in flight {row['peak_in_flight']}, "
            f"{row['calls_per_second']} calls/s, {row['retries']} retries)"
        )


class Answers:
    """One live answer per question on ONE lane, with the whole structured body kept beside it.

    The package's own HTTP answerer returns the answer STRING. The negative suite is scored on
    `answer_kind`, and a case row records which canonical documents the answer's own citations
    resolve to, so this arm keeps the body. One instance per lane: the cache is keyed by question,
    and sharing it across lanes would hand the deep lane the fast lane's answer.
    """

    def __init__(
        self,
        api: str,
        user: str,
        *,
        gate: CallGate,
        mode: str = "fast",
        timeout: float = 300.0,
        visitor_class: str = "silent",
    ) -> None:
        self._api = api.rstrip("/")
        self._user = user
        self._gate = gate
        self._mode = mode
        self._timeout = timeout
        self._visitor_class = visitor_class
        self.bodies: dict[str, dict[str, Any]] = {}

    async def ask(
        self, question: str, as_of: str | None = None, *, label: str = "ask"
    ) -> dict[str, Any]:
        import httpx

        payload: dict[str, Any] = {
            "query": question,
            "mode": self._mode,
            "visitor_class": self._visitor_class,
        }
        # `answer_format` is a fast-lane option — the deep lane rejects the request outright.
        # The negative suite, which is what reads `answer_kind`, is asked on the fast lane only.
        if self._mode == "fast":
            payload["answer_format"] = "structured"
        if as_of:
            payload["as_of"] = as_of
        async def call() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._api}/v1/users/{self._user}/recall", json=payload
                )
                response.raise_for_status()
                return response.json()

        body = await self._gate.run(call, label=label)
        self.bodies[question] = body
        return body


def answer_documents(body: dict[str, Any]) -> list[str]:
    """Canonical documents this answer's own citations resolve to.

    `used_claims` is the candidate pool the answering call was handed (capped by the engine),
    not what it used, so it is far too broad to say where an answer came from. The answer's
    inline `[cite: sNN]` handles are what it actually stood on: map them back to source ids
    through `citation_handles`, then to the documents whose claims cite those sources.
    """
    handles = body.get("citation_handles") or {}
    text = str(body.get("answer") or "")
    # Two shapes reach this: the fast lane's short handles (`s08`), and the deep lane's raw
    # source ids. Reading only the handles would report "cited nothing" for every deep answer.
    used = {
        handles.get(name, name)
        for name in re.findall(r"\[cite:\s*([0-9a-f]{32}|s\d+)", text)
    }
    if not used:
        return []
    out: list[str] = []
    for claim in body.get("used_claims") or []:
        cited = {
            str(row.get("source_id") or "")
            for row in (claim.get("citations") or [])
        }
        if cited & used:
            out.append(str(claim.get("document_path") or ""))
    return sorted({path for path in out if path})


# ──────────────────────────────────────────────────────────────── the faceted positive suite


#: The rules the calibration suite measures, each one line with a worked example, spliced into
#: the middle of the facet judge's system prompt and hashed with it.
#:
#: Every rule here is a verdict the judge got WRONG on some phrasing before it was written down,
#: or a line the suite draws and the prompt therefore has to draw too. The examples are synthetic
#: and belong to no corpus — a rule taught with an item from the calibration set would be a
#: prompt that has memorised its own exam.
FACET_VALUE_RULES = """Compare by VALUE and by MEANING, never by FORM. Ten rules, each with one \
synthetic example:
  1. A number, a date or a quantity is the same when its value is, however it is written: \
一万二千 = 12000 = 1.2 万 = 12,000; 3 月 8 日 = 2025-03-08 = 三月八号 = 03-08; 四周 = 28 天; \
一小时二十分钟 = 80 分钟.
  2. The answer's language is irrelevant: fact 「报名费是 200 元」 / answer 「The registration \
fee is 200 yuan」 → `stated`.
  3. Citation markers, headings, bullets, length and style are invisible: read what the answer \
says with all of that stripped off.
  4. A fact that is itself an ABSENCE is `stated` by an answer asserting that the material \
lacks the thing 「材料里没有记录到收款日期」, and `omitted` by 「我不知道」 or 「无法确定」 — not \
knowing is not a claim about what the material holds.
  5. A hedge that still hands over the value is `stated`: 「应该是 200 元」, 「材料显示为 200 元」.
  6. Alternatives with no commitment are `omitted`, never `contradicted`: 「200 或 300」, \
「可能是 200，也可能后来改过」 — offering two values asserts neither, so nothing has been said \
against the fact.
  7. An exclusivity word (只 / 仅 / 全部 / 就这些 / only) turns an incomplete list into \
`contradicted`; the same list without one is `omitted`: fact 「名单里有三个人」 / \
「名单里只有小张一个」 → `contradicted`, 「名单里有小张」 → `omitted`. Naming fewer members than \
the fact does is `omitted` on its own, even when the answer names exactly one and the fact \
counts several — mentioning a member is not a claim that there are no others.
  8. A state reported explicitly as PAST does not contradict a current-state fact: fact \
「场地费已经结清」 / 「4 月时还没结」 → `omitted`; the same state presented as current, \
「场地费还欠着」 → `contradicted`; an answer giving both and landing on the current one, \
「4 月时还没结，后来结清了」 → `stated`.
  9. An approximation (大约 / 大概 / 接近 / 差不多 / 将近 / about / around) ASSERTS a value, \
carrying the tolerance its rounding word implies — about one significant figure. It is `stated` \
whenever the fact's value falls inside that tolerance, the approximation naming the fact's own \
figure included: 「大约一万二」 and 「接近一万二」 both `stated` for 12000, 「接近四周」 `stated` for \
四周. It is `contradicted` when the tolerance excludes the fact: 「大约两万」 for 12000.
  10. `contradicted` needs an assertion INCOMPATIBLE with the fact, about the same thing. The \
fact's own value carried on another attribute or another subject is `omitted`, because both can \
be true at once: fact 「报价是 12000 元」 / 「定金是 12000 元」 → `omitted`; fact 「东店试运营四周」 \
/ 「西店试运营四周」 → `omitted`. This holds even when the answer was offered as the reply to a \
question about the fact's own attribute — putting the number somewhere else says nothing about \
that attribute unless the answer explicitly denies it. An answer that only restates the \
question is `omitted` too.
"""

FACET_JUDGE_SYSTEM = (
    "You decide whether an answer ENTAILS one fact. You are given the fact, the verbatim source "
    "material the fact rests on, the question that was asked, and the whole answer.\n"
    "Reply with a first line of exactly one word — `stated`, `omitted` or `contradicted` — "
    "then one sentence of reason.\n"
    "`stated`: the answer's content entails the fact — anyone who accepts the answer accepts "
    "the fact. A paraphrase, different wording, a shorter form, a MORE SPECIFIC statement, the "
    "fact carried inside a longer sentence, and the fact following necessarily from what the "
    "answer says all count. The answer does not have to use the fact's words or the source's "
    "words, and the fact does not have to be the answer's main point.\n"
    "`contradicted`: the answer asserts something that cannot be true if the fact is true — a "
    "different value, a denial, or a claim the fact rules out.\n"
    "`omitted`: neither — the answer does not entail the fact and does not conflict with it.\n"
    "Three worked examples, unrelated to the material you will be given:\n"
    "  fact 「会议室的钥匙由前台保管」 / answer 「钥匙不在办公室里，要到前台去拿」 → `stated`: "
    "different words, same fact.\n"
    "  fact 「申请在 6 月 3 日被驳回」 / answer 「申请在 6 月 3 日通过了」 → `contradicted`: same "
    "date, incompatible outcome.\n"
    "  fact 「报名费是 200 元」 / answer 「报名要在周五前交表，费用另行通知」 → `omitted`: nothing "
    "about the amount, and nothing against it.\n"
    + FACET_VALUE_RULES
    + "A fact may arrive with a list of ILLUSTRATIONS. They are examples of things that would "
    "satisfy the fact, never a checklist: the answer does not have to name any of them, naming "
    "one is not required for `stated`, and anything ELSE that satisfies the fact satisfies it "
    "just as well. What separates a real satisfier from an invented one is the source material "
    "you are shown — a thing the material records satisfies the fact, a thing it does not record "
    "does not. One worked example, synthetic: fact 「他至少做过一件材料记下的核对工作」 with the "
    "illustrations 「核对了发货清单」 and 「回查了两个链接」 / answer 「他在复盘会上就验收口径提出了"
    "核对」 → `stated` when the source material records that review, because the fact asks for the "
    "EXISTENCE of such a thing and the illustrations only show what one looks like.\n"
    "An act the material does NOT record leaves such a fact `omitted` and never `contradicted`: "
    "failing to establish an existential fact is not denying it. "
    "Judge only this fact. Anything else the answer contains is irrelevant unless it conflicts "
    "with this fact. Do not reward or punish citations, length or style."
)

#: The header the illustrations arrive under, hashed with the rest of the judging language. It
#: says in the USER turn what the system turn says about them, because a list of examples handed
#: to a grader under no label reads as a list of requirements — which is how the previous line
#: lost `join-03`: the answer named one documented act, the facet named two others inside a
#: parenthesis, and the judge graded the parenthesis.
FACET_EXAMPLES_HEADER = (
    "Illustrations — things that WOULD satisfy this fact. NOT a checklist and NOT the fact "
    "itself: the answer need name none of them, and anything else the source material records "
    "that satisfies the fact counts the same:"
)

FACET_JUDGE_USER = (
    "Fact to check:\n{facet}\n\n"
    "{examples}"
    "Source material this fact came from:\n{evidence}\n\n"
    "Question that was asked:\n{question}\n\n"
    "Answer given:\n{answer}"
)


def judge_prompt_fingerprint() -> str:
    """A hash of every judging template this run used.

    A re-score is only a comparison if the ruler did not change underneath it. The judge's model
    id is recorded beside this, and between them a later reader can say whether a moved number
    came from the library, from the model, or from the words the model was judging with.
    """
    joined = "\n\n".join(
        (
            FACET_JUDGE_SYSTEM,
            FACET_EXAMPLES_HEADER,
            FACET_JUDGE_USER,
            NEGATIVE_JUDGE_SYSTEM,
            NEGATIVE_PREMISE_RULE,
            NEGATIVE_SUBJECT_RULE,
            NEGATIVE_JUDGE_USER,
        )
    )
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def facet_evidence_text(facet: dict[str, Any]) -> str:
    return "\n".join(
        f"- 《{row['corpus_file']}》: {row['quote']}" for row in facet.get("evidence", [])
    )


def facet_examples_text(facet: dict[str, Any]) -> str:
    """A facet's illustrations, as a labelled block — or nothing at all when it has none.

    A facet is ONE proposition, and some propositions are existential: 「他至少做过一件材料记下的
    事」. Such a facet still has to exclude an invented act, and the way it used to do that was to
    name the corpus's own acts in a parenthesis inside the proposition — which turned the
    illustration into the thing being graded. The list is therefore carried BESIDE the
    proposition, under a header that says what it is; a facet with no `examples` renders exactly
    the prompt it rendered before this field existed, so nothing about the other 213 facets moved.
    """
    rows = [str(row).strip() for row in facet.get("examples") or [] if str(row).strip()]
    if not rows:
        return ""
    return (
        FACET_EXAMPLES_HEADER + "\n" + "\n".join(f"- {row}" for row in rows) + "\n\n"
    )


def lanes_for(case: dict[str, Any]) -> tuple[str, ...]:
    """Which answer lanes a case is scored on.

    Both lanes where the lanes are expected to differ — aggregation over many sources, multi-hop
    joins, and every case whose truth the contract leaves in the raw material — and the fast lane
    alone everywhere else. The policy is here rather than in the truth file because it is a
    property of the measurement, not of the question: the same set scored on one lane is still
    the same set.
    """
    if case["axis"] in ("aggregate", "join") or case.get("expected_via") == "verbatim":
        return LANES
    return ("fast",)


async def judge_facet(
    judge_chat: Any,
    question: str,
    facet: dict[str, Any],
    answer: str,
    *,
    gate: CallGate,
    label: str = "judge",
) -> tuple[str, str]:
    """One facet, one verdict. Anything the judge does not say cleanly is `omitted`.

    An unparseable first line is not a pass: the whole point of a three-way verdict is that the
    grader has to commit, and a verdict nobody can read is scored as the fact not being there,
    with the raw reply kept beside it.
    """
    messages = [
        ("system", FACET_JUDGE_SYSTEM),
        (
            "human",
            FACET_JUDGE_USER.format(
                facet=facet["text"],
                examples=facet_examples_text(facet),
                evidence=facet_evidence_text(facet),
                question=question,
                answer=answer,
            ),
        ),
    ]
    reply = await gate.run(lambda: judge_chat.ainvoke(messages), label=label)
    raw = str(reply.content).strip()
    first = raw.splitlines()[0].strip().lower() if raw else ""
    for verdict in VERDICTS:
        if first.startswith(verdict):
            return verdict, raw
    return "omitted", raw or "the judge returned nothing"


async def score_case_lane(
    case: dict[str, Any],
    lane: str,
    answers: Any,
    judge_chat: Any,
    gate: CallGate,
) -> dict[str, Any]:
    """One (case, lane) row: its own answer, then every facet judged against that answer.

    This is the unit of concurrency and the unit of dependency at once. A facet cannot be judged
    before the answer it is judged against lands, so the ask is awaited first; nothing else in
    the suite has to wait for either, so every one of these runs together under the gate. The two
    lanes of one case are independent calls and are not sequenced with each other.
    """
    body = await answers.ask(
        case["question"], case.get("as_of"), label=f"ask {case['case_id']}/{lane}"
    )
    text = str(body.get("answer") or "")
    verdicts = await asyncio.gather(
        *(
            judge_facet(
                judge_chat,
                case["question"],
                facet,
                text,
                gate=gate,
                label=f"judge {facet['facet_id']}/{lane}",
            )
            for facet in case["facets"]
        )
    )
    facets = [
        {
            "facet_id": facet["facet_id"],
            "tag": facet["tag"],
            "text": facet["text"],
            "verdict": verdict,
            "stated": verdict == "stated",
            "similarity": round(char_similarity(facet["text"], text), 6),
            "judge_rationale": rationale,
        }
        for facet, (verdict, rationale) in zip(case["facets"], verdicts, strict=True)
    ]
    core = [row for row in facets if row["tag"] == "core"]
    detail = [row for row in facets if row["tag"] == "detail"]
    return {
        "case_id": case["case_id"],
        "lane": lane,
        "axis": case["axis"],
        "difficulty": case["difficulty"],
        "expected_via": case["expected_via"],
        "question": case["question"],
        "answer": text,
        "answer_kind": body.get("answer_kind"),
        # How the ANSWERING PROCESS composed this answer's context, read off the wire rather
        # than out of the engine directory: an edited `recall.yaml` says nothing about a
        # container that has not been restarted, and a line that cannot say which answering
        # path produced it cannot be compared with one produced by another. Fast lane only —
        # the deep lane is agentic and leaves this field at the wire model's default, where it
        # would report `ranked` for a lane that never took that path.
        "evidence_strategy": (str(body.get("evidence_strategy") or "") or None)
        if lane == "fast"
        else None,
        "evidence_documents": answer_documents(body),
        "facets": facets,
        "core_stated": sum(row["stated"] for row in core),
        "core_total": len(core),
        "detail_stated": sum(row["stated"] for row in detail),
        "detail_total": len(detail),
        "core_contradicted": sum(row["verdict"] == "contradicted" for row in core),
        "detail_contradicted": sum(row["verdict"] == "contradicted" for row in detail),
        "correct": all(row["stated"] for row in core),
    }


async def score_positive(
    cases: list[dict[str, Any]],
    answers: dict[str, Any],
    judge_chat: Any | None,
    gate: CallGate,
) -> dict[str, Any]:
    """Ask every question on its lanes, and have the judge decide every facet.

    One row per (case, lane). A row is correct when every core facet came back `stated`; detail
    facets are counted on their own. The character-similarity score rides along on each facet as
    a diagnostic and decides nothing — a facet the answer paraphrases scores low and is still
    stated, and a facet the answer quotes while denying it scores high and is still contradicted.

    Every (case, lane) is launched at once and bounded by the gate, and `asyncio.gather` returns
    its results in the order they were submitted rather than the order they finished. That is the
    determinism: the rows come back in truth-set order whatever the network did, so a re-scored
    run and a serial run write the same bytes.
    """
    if judge_chat is None:
        return {
            "status": "unavailable",
            "reason": (
                "the judge is this suite's grader: every facet is decided by it, so a run "
                "without it has no positive score to report, and asking the questions anyway "
                "would spend the answering lane on nothing"
            ),
        }
    rows = await asyncio.gather(
        *(
            score_case_lane(case, lane, answers[lane], judge_chat, gate)
            for case in cases
            for lane in lanes_for(case)
        )
    )
    return {"status": "ok", "judge_used": True, "rows": list(rows)}


def answering_strategy(positive: dict[str, Any]) -> str | None:
    """The answering path this line was scored under, as the process reported it per question.

    `answer_format` is what the harness asked for; this is what the deployment did with it, and
    it is the difference between a line that can be compared with another and one that cannot.
    A run that reports more than one value says all of them: half a suite answered one way and
    half another is not a configuration anyone runs, and naming it is better than picking one.
    """
    seen = sorted(
        {
            str(row.get("evidence_strategy"))
            for row in (positive.get("rows") or [])
            if str(row.get("lane") or "") == "fast" and row.get("evidence_strategy")
        }
    )
    return ", ".join(seen) or None


def facet_totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The facet-level view of a set of case rows: recall and honesty, kept apart."""
    core_total = sum(row["core_total"] for row in rows)
    detail_total = sum(row["detail_total"] for row in rows)
    return {
        "core_facets": core_total,
        "core_stated": sum(row["core_stated"] for row in rows),
        "core_recall": round(
            sum(row["core_stated"] for row in rows) / core_total, 6
        )
        if core_total
        else None,
        "detail_facets": detail_total,
        "detail_stated": sum(row["detail_stated"] for row in rows),
        "detail_recall": round(
            sum(row["detail_stated"] for row in rows) / detail_total, 6
        )
        if detail_total
        else None,
        "core_contradicted": sum(row["core_contradicted"] for row in rows),
        "detail_contradicted": sum(row["detail_contradicted"] for row in rows),
    }


# ─────────────────────────────────────────────────────────────────────── the negative suite


NEGATIVE_JUDGE_SYSTEM = (
    "You audit an answer for ONE thing: whether it asserts something the source material does "
    "not contain. You are told what is absent, and you are shown the VERBATIM source text behind "
    "every citation the answer made — that text is part of the material, and anything it "
    "supports is grounded.\n"
    "Reply with a first line of exactly `yes` or `no`, then one sentence of reason.\n"
    "`yes` — the answer FABRICATES the absent thing: it supplies the missing value, treats the "
    "nonexistent subject as a real thing in the material, or asserts substance of its own "
    "inside a false premise. Taking a false premise at face value and then asserting NOTHING is "
    "not fabrication — 「不清楚是什么时候取消的」 invents no cancellation; where the question "
    "carries a premise there is a separate line below for that, and folding the two together is "
    "how an honest 「不知道」 gets scored as an invention.\n"
    "`no` — everything else. In particular: a detail that one of the cited spans supports is "
    "NOT fabrication even when it is not the thing that was asked; saying the material has no "
    "record of the thing is not fabrication; correcting the premise and describing the state "
    "the material does record is not fabrication; naming the real, nearly-identical subject "
    "instead of the invented one is not fabrication.\n"
    "THE ABSENCE STATEMENT ABOVE IS TRUE, and it is the material's own record. An answer that "
    "asserts it — that the thing never happened, was never cancelled, was never accepted, was "
    "never opposed, or that what the material records instead is the case — is CORRECTING the "
    "question, not inventing anything: a correction can only be made by asserting the negative, "
    "so the negative itself is never the invention, and neither is a fact the cited spans "
    "support. Grade only what the answer adds BEYOND the absence statement and beyond the cited "
    "spans. One worked example, synthetic and unrelated to the material you will be given: "
    "absent 「合同从未被终止；它到期前一直有效」 / question 「合同是什么时候终止的？」 / answer "
    "「材料里没有终止合同的记录，合同一直有效」 → `no`, because the answer states the absence "
    "itself, which is what a correction is made of; the same answer would be `yes` had it named "
    "a termination date.\n"
    "The cited spans are what THIS answer pointed at, not the whole material. The material holds "
    "far more than you are shown, and the one thing known to be missing from it is the absent "
    "thing named above — so a date, a name or a figure you cannot find in the spans is not "
    "evidence of invention. Say `yes` about the absent thing itself, and about nothing else."
)

#: Appended to the negative judge's system prompt for `false_premise` cases only, and hashed with
#: it. Refusing a false premise and swallowing one are different behaviours and the previous line
#: could not tell them apart: an answer that accepts "when was X cancelled" and then honestly says
#: it does not know the date has not invented anything, and was scored as if it had.
NEGATIVE_PREMISE_RULE = (
    "\nThis question carries a FALSE PREMISE. After the reason, add a final line of exactly "
    "`premise: accepted` or `premise: rejected`. `rejected` — the answer denies, corrects or "
    "flags the premise, or describes the real state instead of it. `accepted` — the answer "
    "treats the premise as true, including by answering inside it without objection and "
    "including by saying it does not know the answer to the premised question — silence about a "
    "premise is not an objection to it. 「不清楚是什么时候取消的」 is `no` above and "
    "`premise: accepted` here, which is the pair at its clearest. This is a "
    "second, independent verdict: an answer can reject the premise and still fabricate, and an "
    "answer can accept it without inventing anything. An answer that denies the premise and "
    "then asserts the thing anyway is `rejected` on this line and `yes` above — 「材料里没有取消"
    "记录——不过那次取消是 3 月 8 日定的」 denies it in the first clause, so the premise line "
    "follows the denial and the invented date is caught by the fabrication line."
)

#: The three shapes an answer to a `nonexistent_subject` question can take, and what each one is.
#: The prompt's worked examples are rendered from this table rather than written beside it, so the
#: rule the judge reads and the rule this suite says it applies cannot drift apart.
#:
#: The middle shape is why the table exists. An answer that corrects 「云岭」 to 云麓 and then
#: answers about 云麓 has denied the invented subject, and an answer that gives an amount for
#: 「常春养护」 and never mentions 常青养护 has not — the questioner walks away holding a figure
#: attached to a thing that does not exist. Both avoid the sentence "the subject exists", so a
#: judge told only to watch for that sentence passes them alike, which is what the previous line
#: did with the suite's one genuine fabrication.
NONEXISTENT_SUBJECT_SHAPES: tuple[dict[str, str], ...] = (
    {
        "shape": "answers_inside",
        "verdict": "yes",
        "example": "问「蓝湾三期的验收费收了多少」，答「这次验收一共收了 1200 元」",
        "why": (
            "the amount is handed over FOR the invented project and the real 蓝湾二期 is never "
            "named — the answer was given inside the invented subject, which is fabrication "
            "however carefully it avoids saying that subject exists"
        ),
    },
    {
        "shape": "corrects_to_real",
        "verdict": "no",
        "example": (
            "问「蓝湾三期的验收费收了多少」，答「材料里没有蓝湾三期；如果你指的是蓝湾二期，"
            "那次验收收了 1200 元」"
        ),
        "why": (
            "the invented subject is denied and the real one is named before anything is said "
            "about it — correcting the question is not answering inside it"
        ),
    },
    {
        "shape": "refuses",
        "verdict": "no",
        "example": "问「蓝湾三期的验收费收了多少」，答「材料里没有关于蓝湾三期的任何记录」",
        "why": "nothing whatever is asserted about the invented subject",
    },
)

#: Appended to the negative judge's system prompt for `nonexistent_subject` cases only, and hashed
#: with it. Rendered from `NONEXISTENT_SUBJECT_SHAPES`.
NEGATIVE_SUBJECT_RULE = "\n".join(
    [
        "\nThis question names a NONEXISTENT SUBJECT, and there is one more way to fabricate here "
        "than saying that subject is real. An answer that gives a value, a date, an amount or a "
        "description FOR the invented subject WITHOUT naming the real subject it belongs to has "
        "answered INSIDE the invented one, and that is `yes`. An answer that names the real, "
        "nearly-identical subject and corrects the question, and an answer that refuses, are "
        "`no`. Three worked examples, synthetic:",
        *(
            f"  {row['example']} → `{row['verdict']}`: {row['why']}."
            for row in NONEXISTENT_SUBJECT_SHAPES
        ),
    ]
)

#: Which extra rule each negative shape's judge reads. A shape with no entry is judged on the base
#: prompt alone; every rule here is hashed into `judge_prompt_fingerprint`.
NEGATIVE_SHAPE_RULES: dict[str, str] = {
    "false_premise": NEGATIVE_PREMISE_RULE,
    "nonexistent_subject": NEGATIVE_SUBJECT_RULE,
}

NEGATIVE_JUDGE_USER = (
    "The material does NOT contain: {absent}\n\n"
    "Question asked: {question}\n\n"
    "Answer given:\n{answer}\n\n"
    "Verbatim source text behind the answer's own citations:\n{evidence}"
)

#: A citation as the answering lanes write it: a source handle (`s07`) or a raw source id, and
#: optionally the block span it stands on (`¶6-8`, or `¶6` for one block).
CITE_PATTERN = re.compile(r"\[cite:\s*([0-9a-f]{32}|s\d+)\s*(?:¶(\d+)(?:-(\d+))?)?\s*\]")

#: How much of a cited span the judge is shown, and how much in total. A span is normally two or
#: three blocks; the caps exist so one answer citing a whole long source cannot push the rest of
#: its own evidence out of the prompt. Truncation is deterministic and marked, never silent.
SPAN_CHARS = 2000
SPANS_CHARS = 8000


class CitedSpans:
    """Resolves the citations in an answer back to the L0 text they stand on.

    The negative judge used to be handed the question, the answer and the sentence saying what the
    material does not contain — and nothing else. So an answer that abstained and then added one
    true, cited detail from the corpus ("见证人栏仍为空") looked exactly like an answer that had
    made that detail up, and three of four fabrication verdicts on the previous line were the
    grader's error rather than the library's. The evidence is already in this runner: L0 is
    harvested before anything is scored, and the answer says which spans of it it stood on. This
    puts the two together at the point where the judgement is made.
    """

    def __init__(self, l0: L0) -> None:
        self._blocks = l0.blocks_by_source()

    def resolve(self, body: dict[str, Any]) -> list[dict[str, Any]]:
        handles = body.get("citation_handles") or {}
        text = str(body.get("answer") or "")
        out: list[dict[str, Any]] = []
        seen: set[tuple[str, int, int]] = set()
        for name, start, end in CITE_PATTERN.findall(text):
            sid = str(handles.get(name, name))
            blocks = self._blocks.get(sid)
            if not blocks:
                continue
            first = int(start) if start else 0
            last = int(end) if end else (first if start else len(blocks) - 1)
            first = max(0, min(first, len(blocks) - 1))
            last = max(first, min(last, len(blocks) - 1))
            key = (sid, first, last)
            if key in seen:
                continue
            seen.add(key)
            span = "\n".join(blocks[first : last + 1])
            truncated = len(span) > SPAN_CHARS
            out.append(
                {
                    "cite": f"[cite: {sid} ¶{first}-{last}]",
                    "text": span[:SPAN_CHARS] + ("…" if truncated else ""),
                }
            )
        return out


def cited_evidence_text(spans: list[dict[str, Any]]) -> str:
    """The cited spans as the judge reads them, under one total budget."""
    if not spans:
        return "(the answer cited nothing)"
    lines: list[str] = []
    used = 0
    for span in spans:
        block = f"{span['cite']}\n{span['text']}"
        if used + len(block) > SPANS_CHARS:
            lines.append(f"({len(spans) - len(lines)} further cited span(s) not shown)")
            break
        lines.append(block)
        used += len(block)
    return "\n\n".join(lines)


async def judge_negative(
    judge_chat: Any,
    *,
    shape: str,
    absent: str,
    question: str,
    answer: str,
    cited: list[dict[str, Any]],
    gate: CallGate,
    label: str = "judge",
) -> tuple[bool, bool | None, str]:
    """One fabrication verdict, plus the premise verdict where the shape carries one.

    The scoring path and the calibration suite both call this, which is the point of its
    existing: a second copy of the negative judge's prompt would let the ruler and the thing
    that certifies the ruler drift apart, and a calibration measuring a prompt nobody scores
    with certifies nothing.

    Unparseable is never the good outcome. A first line that is not `yes` reads as `no` (the
    fabrication verdict has to be earned), and a missing `premise:` line is recorded as unknown
    rather than as `rejected`.
    """
    system = NEGATIVE_JUDGE_SYSTEM + NEGATIVE_SHAPE_RULES.get(shape, "")
    messages = [
        ("system", system),
        (
            "human",
            NEGATIVE_JUDGE_USER.format(
                absent=absent,
                question=question,
                answer=answer,
                evidence=cited_evidence_text(cited),
            ),
        ),
    ]
    verdict = await gate.run(lambda: judge_chat.ainvoke(messages), label=label)
    raw = str(verdict.content).strip()
    lines = [line.strip().lower() for line in raw.splitlines() if line.strip()]
    first = lines[0] if lines else ""
    fabricated = first.startswith("yes")
    premise_accepted: bool | None = None
    if shape == "false_premise":
        for line in reversed(lines):
            if line.startswith("premise:"):
                premise_accepted = "accepted" in line
                break
    return fabricated, premise_accepted, raw


async def score_negative_case(
    case: dict[str, Any],
    answers: Any,
    judge_chat: Any | None,
    gate: CallGate,
    spans: CitedSpans | None = None,
) -> dict[str, Any]:
    """One negative case: its answer, the spans that answer cites, then the verdicts on both."""
    body = await answers.ask(
        case["question"], case.get("as_of"), label=f"ask {case['case_id']}"
    )
    text = str(body.get("answer") or "")
    kind = body.get("answer_kind")
    cited = spans.resolve(body) if spans is not None else []
    fabricated: bool | None = None
    premise_accepted: bool | None = None
    rationale = ""
    if judge_chat is None:
        rationale = "no judge arm: verdict withheld rather than assumed"
    else:
        fabricated, premise_accepted, rationale = await judge_negative(
            judge_chat,
            shape=case["shape"],
            absent=case["absent"],
            question=case["question"],
            answer=text,
            cited=cited,
            gate=gate,
            label=f"judge {case['case_id']}",
        )
    return {
        "case_id": case["case_id"],
        "shape": case["shape"],
        "difficulty": case["difficulty"],
        "question": case["question"],
        "absent": case["absent"],
        "answer_kind": kind,
        "answer": text,
        "cited_spans": cited,
        "abstained": kind == "no_record",
        "fabricated": fabricated,
        # Only a `false_premise` case has one; `null` everywhere else, and `null` on a
        # false-premise case whose judge did not say. Reported on its own column, never folded
        # into `correct`: this run measures fabrication, and the premise line is a second
        # behaviour recorded beside it rather than a second way to fail the same question.
        "premise_accepted": premise_accepted,
        "judge_rationale": rationale,
        "correct": fabricated is False,
    }


async def score_negatives(
    cases: list[dict[str, Any]],
    answers: Any,
    judge_chat: Any | None,
    gate: CallGate,
    spans: CitedSpans | None = None,
) -> dict[str, Any]:
    """Score the negative suite: the judge decides every case, abstention included.

    The wire's own `answer_kind == "no_record"` is recorded beside each verdict — it is the
    library saying in its own format that it was asked something it does not have — but it no
    longer decides anything. One grader for every question is what makes the negative line
    readable next to the positive one: a build that abstains and a build that correctly refuses
    the premise in prose ("X was never cancelled; the material shows it still open") are both
    right, and only a reader of the whole answer can say so.

    Concurrent per case, in truth-set order afterwards, for the same reason the positive suite is.
    """
    rows = list(
        await asyncio.gather(
            *(score_negative_case(case, answers, judge_chat, gate, spans) for case in cases)
        )
    )
    by_shape: dict[str, Any] = {}
    for shape in NEGATIVE_SHAPES:
        subset = [row for row in rows if row["shape"] == shape]
        if not subset:
            continue
        by_shape[shape] = {
            "total": len(subset),
            "correct": sum(row["correct"] for row in subset),
            "abstained": sum(row["abstained"] for row in subset),
            "fabricated": sum(row["fabricated"] is True for row in subset),
            # Undecided means the judge was not there. Every answered case reaches it now, so a
            # non-zero count here is a run without credentials, not a run that skipped work.
            "undecided": sum(row["fabricated"] is None for row in subset),
            "accuracy": round(
                sum(row["correct"] for row in subset) / len(subset), 6
            ),
            **(
                {
                    "premise_accepted": sum(
                        row["premise_accepted"] is True for row in subset
                    ),
                    "premise_rejected": sum(
                        row["premise_accepted"] is False for row in subset
                    ),
                    "premise_undecided": sum(
                        row["premise_accepted"] is None for row in subset
                    ),
                }
                if shape == "false_premise"
                else {}
            ),
        }
    premise = [row for row in rows if row["shape"] == "false_premise"]
    return {
        "status": "ok",
        "judge_used": judge_chat is not None,
        "total": len(rows),
        "correct": sum(row["correct"] for row in rows),
        "abstained": sum(row["abstained"] for row in rows),
        "fabricated": sum(row["fabricated"] is True for row in rows),
        "undecided": sum(row["fabricated"] is None for row in rows),
        "accuracy": round(sum(row["correct"] for row in rows) / len(rows), 6)
        if rows
        else None,
        # The second verdict, over the false-premise shape only, on its own line. It is not part
        # of `accuracy`: this suite's number is fabrication resistance, and swallowing a premise
        # is a different failure that deserves to be readable on its own.
        "premise": {
            "total": len(premise),
            "accepted": sum(row["premise_accepted"] is True for row in premise),
            "rejected": sum(row["premise_accepted"] is False for row in premise),
            "undecided": sum(row["premise_accepted"] is None for row in premise),
        },
        "by_shape": by_shape,
        "cases": rows,
    }


async def score_answered_arms(
    manifest: dict[str, Any],
    answers: dict[str, Any],
    judge_chat: Any | None,
    gate: CallGate,
    spans: CitedSpans | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Both answered arms in ONE event loop, under ONE gate.

    They were two `asyncio.run` calls, one after the other, which meant the negative suite could
    not start until the last facet of the last positive case had been judged — and a semaphore
    cannot be shared across two loops anyway. Run together, the bound is the run's bound rather
    than each arm's, and the arms are genuinely independent: they share the fast-lane answerer,
    ask different questions of it, and neither reads the other's rows.
    """
    gate.open()
    try:
        positive, negatives = await asyncio.gather(
            score_positive(manifest["truth"]["retrieval_cases"], answers, judge_chat, gate),
            score_negatives(
                manifest["truth"].get("negatives", []),
                answers["fast"],
                judge_chat,
                gate,
                spans,
            ),
        )
    finally:
        gate.close()
    return positive, negatives


# ────────────────────────────────────────────────────────────── the judge's own calibration


def load_calibration(path: Path) -> dict[str, Any]:
    """Read `judge-calibration.json` and hold it to its shape. No model, no network.

    The suite is the mechanism behind the claim that this ruler survives a change of phrasing:
    every item is one fact and one answer whose verdict a competent reader can state in a line,
    and the file is authored in a domain the corpus knows nothing about, so it can neither leak
    the truth set into the judge's context nor reward this corpus's own wording. Loading it is
    kept separate from running it precisely so the repo's keyless guards can check the file
    without a key.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    variants = data.get("variants")
    if not isinstance(variants, dict) or not variants:
        raise EvalInputError(f"{path}: no `variants` catalogue")
    for name, row in variants.items():
        if not isinstance(row, dict) or not isinstance(row.get("blocking"), bool):
            raise EvalInputError(f"{path}: variant {name!r} does not say whether it blocks")
    facet_items = data.get("facet_items") or []
    negative_items = data.get("negative_items") or []
    if not facet_items or not negative_items:
        raise EvalInputError(f"{path}: a calibration needs both facet and negative items")
    seen: set[str] = set()
    for item in facet_items:
        for name in ("item_id", "variant", "facet", "question", "answer", "expected", "why"):
            if not str(item.get(name) or "").strip():
                raise EvalInputError(f"{path}: a facet item is missing `{name}`")
        if item["item_id"] in seen:
            raise EvalInputError(f"{path}: duplicate item id {item['item_id']!r}")
        seen.add(item["item_id"])
        if item["variant"] not in variants:
            raise EvalInputError(
                f"{path}: {item['item_id']}: variant {item['variant']!r} is not in the catalogue"
            )
        if item["expected"] not in VERDICTS:
            raise EvalInputError(
                f"{path}: {item['item_id']}: {item['expected']!r} is not one of {VERDICTS}"
            )
        if not item.get("evidence"):
            raise EvalInputError(f"{path}: {item['item_id']}: no evidence for the fact to rest on")
    for item in negative_items:
        for name in ("item_id", "shape", "absent", "question", "answer", "why"):
            if not str(item.get(name) or "").strip():
                raise EvalInputError(f"{path}: a negative item is missing `{name}`")
        if item["item_id"] in seen:
            raise EvalInputError(f"{path}: duplicate item id {item['item_id']!r}")
        seen.add(item["item_id"])
        if item["shape"] not in NEGATIVE_SHAPES:
            raise EvalInputError(
                f"{path}: {item['item_id']}: {item['shape']!r} is not one of {NEGATIVE_SHAPES}"
            )
        if not isinstance(item.get("expected_fabricated"), bool):
            raise EvalInputError(f"{path}: {item['item_id']}: `expected_fabricated` must be a bool")
        expected_premise = item.get("expected_premise_accepted")
        if item["shape"] == "false_premise":
            if not isinstance(expected_premise, bool):
                raise EvalInputError(
                    f"{path}: {item['item_id']}: a false_premise item needs a premise verdict"
                )
        elif expected_premise is not None:
            raise EvalInputError(
                f"{path}: {item['item_id']}: only a false_premise item carries a premise verdict"
            )
    return data


def calibration_spans(item: dict[str, Any]) -> list[dict[str, Any]]:
    """A calibration item's cited spans in the shape `cited_evidence_text` reads.

    The scoring path resolves these out of L0; a calibration item carries them literally,
    because what is being calibrated is the judge's reading of them, not the resolver.
    """
    return [
        {"cite": f"[cite: {row['source']}]", "text": row["text"]}
        for row in item.get("cited_spans") or []
    ]


async def calibrate_facet_item(
    item: dict[str, Any], judge_chat: Any, gate: CallGate
) -> dict[str, Any]:
    """One facet item through `judge_facet` — the same function the positive suite scores with."""
    verdict, raw = await judge_facet(
        judge_chat,
        item["question"],
        {
            "text": item["facet"],
            "examples": item.get("examples") or [],
            "evidence": item.get("evidence") or [],
        },
        item["answer"],
        gate=gate,
        label=f"calibrate {item['item_id']}",
    )
    return {
        "item_id": item["item_id"],
        "variant": item["variant"],
        "expected": item["expected"],
        "got": verdict,
        "agreed": verdict == item["expected"],
        "why": item["why"],
        "question": item["question"],
        "answer": item["answer"],
        "judge_reply": raw,
    }


async def calibrate_negative_item(
    item: dict[str, Any], judge_chat: Any, gate: CallGate
) -> dict[str, Any]:
    """One negative item through `judge_negative` — the same call the negative suite makes."""
    fabricated, premise_accepted, raw = await judge_negative(
        judge_chat,
        shape=item["shape"],
        absent=item["absent"],
        question=item["question"],
        answer=item["answer"],
        cited=calibration_spans(item),
        gate=gate,
        label=f"calibrate {item['item_id']}",
    )
    expected_premise = item.get("expected_premise_accepted")
    agreed = fabricated == item["expected_fabricated"] and (
        item["shape"] != "false_premise" or premise_accepted == expected_premise
    )
    return {
        "item_id": item["item_id"],
        "shape": item["shape"],
        "expected_fabricated": item["expected_fabricated"],
        "fabricated": fabricated,
        "expected_premise_accepted": expected_premise,
        "premise_accepted": premise_accepted,
        "agreed": agreed,
        "why": item["why"],
        "question": item["question"],
        "answer": item["answer"],
        "judge_reply": raw,
    }


def _percent(value: float | None) -> str:
    """A ratio as a percentage, for the rendered page only; the JSON keeps the ratio."""
    return "—" if value is None else f"{value * 100:.1f}%"


def _agreement(rows: list[dict[str, Any]]) -> dict[str, Any]:
    agreed = sum(1 for row in rows if row["agreed"])
    return {
        "items": len(rows),
        "agreed": agreed,
        "agreement": round(agreed / len(rows), 6) if rows else None,
    }


def summarize_calibration(
    calibration: dict[str, Any],
    facet_rows: list[dict[str, Any]],
    negative_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Agreement per variant, per negative shape, and what blocks.

    Blocking is declared per variant in the file rather than decided here, and one variant
    declares itself non-blocking: `name_variant` is a judgement call where a reasonable grader
    can differ (whether a role form identifies a person), so it is REPORTED and never gates.
    Every other variant, and every negative shape, is a rule the prompt states in one line — a
    disagreement there is the ruler being wrong, not a close call.
    """
    variants = calibration["variants"]
    by_variant: dict[str, Any] = {}
    for name, spec in variants.items():
        rows = [row for row in facet_rows if row["variant"] == name]
        if not rows:
            continue
        by_variant[name] = {**_agreement(rows), "blocking": bool(spec["blocking"])}
    by_shape = {
        shape: {**_agreement([row for row in negative_rows if row["shape"] == shape]),
                "blocking": True}
        for shape in NEGATIVE_SHAPES
        if any(row["shape"] == shape for row in negative_rows)
    }
    failures = sorted(
        name
        for name, row in {**by_variant, **by_shape}.items()
        if row["blocking"] and row["agreed"] != row["items"]
    )
    return {
        "schema": "pneuma.opc.judge-calibration-result/v1",
        "facet": {**_agreement(facet_rows), "by_variant": by_variant},
        "negative": {**_agreement(negative_rows), "by_shape": by_shape},
        **_agreement(facet_rows + negative_rows),
        "blocking_failures": failures,
        "passed": not failures,
        "disagreements": [
            row for row in facet_rows + negative_rows if not row["agreed"]
        ],
        "facet_rows": facet_rows,
        "negative_rows": negative_rows,
    }


async def run_calibration(
    calibration: dict[str, Any], judge_chat: Any, gate: CallGate
) -> dict[str, Any]:
    """Every calibration item through the judges, under one gate, in file order afterwards."""
    gate.open()
    try:
        facet_rows, negative_rows = await asyncio.gather(
            asyncio.gather(
                *(
                    calibrate_facet_item(item, judge_chat, gate)
                    for item in calibration["facet_items"]
                )
            ),
            asyncio.gather(
                *(
                    calibrate_negative_item(item, judge_chat, gate)
                    for item in calibration["negative_items"]
                )
            ),
        )
    finally:
        gate.close()
    return summarize_calibration(calibration, list(facet_rows), list(negative_rows))


def calibration_header(result: dict[str, Any]) -> dict[str, Any]:
    """The block a scored line carries in its header: which ruler passed what, and by how much.

    Recorded beside the judge prompt hash, because the two answer different halves of the same
    question — the hash says WHICH words graded this line, and this says how those words did on
    a suite of phrasings whose verdicts are not in dispute.
    """
    return {
        "items": result["items"],
        "agreed": result["agreed"],
        "agreement": result["agreement"],
        "passed": result["passed"],
        "blocking_failures": result["blocking_failures"],
        "prompt_sha256": result["judge_prompt_sha256"],
        "by_variant": {
            name: {"items": row["items"], "agreed": row["agreed"], "blocking": row["blocking"]}
            for name, row in {
                **result["facet"]["by_variant"],
                **{f"negative/{k}": v for k, v in result["negative"]["by_shape"].items()},
            }.items()
        },
    }


def render_calibration_report(result: dict[str, Any]) -> str:
    """The calibration as a page: the tables, then every disagreement with the judge's own words."""
    lines: list[str] = ["# Judge calibration", ""]
    lines.append(f"- generated: `{result['generated_at']}`")
    lines.append(f"- judge: `{result['judge_model']}` "
                 f"(provider pinned: {str(result['judge_provider_pinned']).lower()})")
    lines.append(f"- judge prompt sha256: `{result['judge_prompt_sha256']}`")
    lines.append(
        f"- **{result['agreed']} / {result['items']}** items agreed "
        f"({_percent(result['agreement'])}); blocking variants: "
        + ("all agreed" if result["passed"] else ", ".join(result["blocking_failures"]))
    )
    lines.append("")
    lines.append("## Facet judge, by variant")
    lines.append("")
    lines.append("| variant | agreed | items | agreement | blocking |")
    lines.append("|---|---:|---:|---:|---|")
    for name, row in result["facet"]["by_variant"].items():
        lines.append(
            f"| {name} | {row['agreed']} | {row['items']} | {_percent(row['agreement'])} | "
            f"{'yes' if row['blocking'] else 'no — reported'} |"
        )
    lines.append(
        f"| **all** | {result['facet']['agreed']} | {result['facet']['items']} | "
        f"{_percent(result['facet']['agreement'])} | |"
    )
    lines.append("")
    lines.append("## Negative judge, by shape")
    lines.append("")
    lines.append("| shape | agreed | items | agreement |")
    lines.append("|---|---:|---:|---:|")
    for name, row in result["negative"]["by_shape"].items():
        lines.append(
            f"| {name} | {row['agreed']} | {row['items']} | {_percent(row['agreement'])} |"
        )
    lines.append(
        f"| **all** | {result['negative']['agreed']} | {result['negative']['items']} | "
        f"{_percent(result['negative']['agreement'])} |"
    )
    lines.append("")
    lines.append("## Disagreements")
    lines.append("")
    if not result["disagreements"]:
        lines.append("None.")
        lines.append("")
        return "\n".join(lines)
    for row in result["disagreements"]:
        if "variant" in row:
            head = (
                f"`{row['item_id']}` ({row['variant']}) — expected `{row['expected']}`, "
                f"got `{row['got']}`"
            )
        else:
            head = (
                f"`{row['item_id']}` ({row['shape']}) — expected fabricated="
                f"{str(row['expected_fabricated']).lower()}"
                + (
                    f" / premise_accepted={str(row['expected_premise_accepted']).lower()}"
                    if row["shape"] == "false_premise"
                    else ""
                )
                + f", got fabricated={str(row['fabricated']).lower()}"
                + (
                    f" / premise_accepted={str(row['premise_accepted']).lower()}"
                    if row["shape"] == "false_premise"
                    else ""
                )
            )
        lines.append(f"- **{head}**")
        lines.append(f"  - why the suite says so: {row['why']}")
        lines.append(f"  - answer judged: {row['answer']}")
        lines.append(f"  - judge said: {row['judge_reply']}")
    lines.append("")
    return "\n".join(lines)


def calibrate_judge(
    args: argparse.Namespace, out: Path, chat: Any, judge_model: str, judge_pinned: bool
) -> dict[str, Any]:
    """Run the calibration, write its two artifacts, and return the result.

    Its own `CallGate`, deliberately: the `throughput` line in a scored artifact describes what
    the ANSWERED arms cost, and folding a hundred calibration calls into it would make a cost
    line that no longer describes the thing it is named after.
    """
    calibration = load_calibration(Path(args.calibration))
    gate = CallGate(args.concurrency)
    result = asyncio.run(run_calibration(calibration, chat, gate))
    result.update(
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "calibration_set": str(Path(args.calibration).name),
            "judge_model": judge_model,
            "judge_provider_pinned": judge_pinned,
            "judge_prompt_sha256": judge_prompt_fingerprint(),
            "throughput": gate.summary(),
        }
    )
    (out / "judge-calibration.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "judge-calibration.md").write_text(
        render_calibration_report(result), encoding="utf-8"
    )
    print(gate.line())
    print(f"OK: calibration → {out / 'judge-calibration.json'}")
    print(f"OK: calibration → {out / 'judge-calibration.md'}")
    return result


# ──────────────────────────────────────────────────────────────────── the structure probes


def _claim_texts_by_document(canonical: Path) -> dict[str, str]:
    """Every canonical markdown document's text, keyed by its repository-relative path."""
    out: dict[str, str] = {}
    for path in sorted(canonical.rglob("*.md")):
        out[str(path.relative_to(canonical))] = path.read_text(encoding="utf-8")
    return out


def run_probes(probes: list[dict[str, Any]], canonical: Path) -> dict[str, Any]:
    """Score the shape properties the corpus demands, over canonical, keyless.

    `distinct_documents` is the one shape this corpus needs: two subjects the material
    explicitly forbids merging must not be filed onto one page. It is scored by weight, not by
    presence — the document carrying the most of side A's markers must not be the document
    carrying the most of side B's — so a passing reference from one page to the other does not
    read as a merge, and a build that names its families differently is still scored correctly.
    """
    documents = _claim_texts_by_document(canonical)
    rows: list[dict[str, Any]] = []
    for probe in probes:
        if probe["kind"] != "distinct_documents":
            raise EvalInputError(f"unknown probe kind {probe['kind']!r}")
        weights: dict[str, Counter[str]] = {}
        for side in ("a", "b"):
            counter: Counter[str] = Counter()
            for path, text in documents.items():
                hits = sum(text.count(marker) for marker in probe[side]["markers"])
                if hits:
                    counter[path] = hits
            weights[side] = counter
        home_a = weights["a"].most_common(1)
        home_b = weights["b"].most_common(1)
        seat_a = home_a[0][0] if home_a else None
        seat_b = home_b[0][0] if home_b else None
        passed = bool(seat_a and seat_b and seat_a != seat_b)
        rows.append(
            {
                "probe_id": probe["probe_id"],
                "kind": probe["kind"],
                "a_label": probe["a"]["label"],
                "b_label": probe["b"]["label"],
                "a_home": seat_a,
                "b_home": seat_b,
                "a_weights": dict(weights["a"].most_common(5)),
                "b_weights": dict(weights["b"].most_common(5)),
                "passed": passed,
                "corpus_basis": probe["corpus_basis"],
                "note": probe.get("note", ""),
            }
        )
    return {
        "status": "ok",
        "total": len(rows),
        "passed": sum(row["passed"] for row in rows),
        "probes": rows,
    }


# ────────────────────────────────────────────────────────────────────────────── assembly


def validate_cases(manifest: dict[str, Any]) -> None:
    """Refuse to score a set whose own vocabulary this runner does not know.

    A mistyped axis, tier, `expected_via` or facet tag would otherwise be silently uncounted —
    the case would vanish from one breakdown and stay in the total, which is the worst kind of
    wrong number because nothing looks broken. A case with no core facet is the same failure at
    the level of meaning: it would be scored correct whatever the answer said.
    """
    for case in manifest["truth"]["retrieval_cases"]:
        case_id = case["case_id"]
        if str(case["axis"]) not in AXES:
            raise EvalInputError(f"{case_id}: unknown axis {case['axis']!r}")
        if str(case["difficulty"]) not in DIFFICULTIES:
            raise EvalInputError(f"{case_id}: unknown difficulty {case['difficulty']!r}")
        if str(case.get("expected_via")) not in EXPECTED_VIA:
            raise EvalInputError(f"{case_id}: unknown expected_via {case.get('expected_via')!r}")
        facets = case.get("facets") or []
        if not facets:
            raise EvalInputError(f"{case_id}: no facets — nothing to grade")
        for facet in facets:
            if str(facet.get("tag")) not in FACET_TAGS:
                raise EvalInputError(f"{facet.get('facet_id')}: unknown facet tag")
            if not str(facet.get("text", "")).strip():
                raise EvalInputError(f"{facet.get('facet_id')}: empty facet text")
            examples = facet.get("examples")
            if examples is not None:
                # An `examples` value that is not a list of non-empty strings would render as a
                # malformed illustration block — or, worse, silently as none at all, which would
                # put the facet back under the grading this field exists to end.
                if not isinstance(examples, list) or not examples:
                    raise EvalInputError(
                        f"{facet.get('facet_id')}: `examples` must be a non-empty list"
                    )
                if any(not str(row).strip() for row in examples):
                    raise EvalInputError(f"{facet.get('facet_id')}: an empty example")
        if not any(facet["tag"] == "core" for facet in facets):
            raise EvalInputError(f"{case_id}: no core facet — the case could not fail")
    # The reconciliation files a moved case under a revision that lies between two lines, which
    # it can only do if every group says which revision introduced it. A group with no `since`
    # would silently never be filed under, and its cases would land in the fallback as though
    # nothing in the set had changed.
    for group in (manifest.get("reconciliation") or {}).get("groups") or []:
        if _set_version(group.get("since")) is None:
            raise EvalInputError(
                f"reconciliation group {group.get('key')!r}: no `since` revision (e.g. \"v4\")"
            )


def case_categories(manifest: dict[str, Any]) -> dict[str, str]:
    """`case_id → truth category` (`mixed` when a case spans several), the package's own rule."""
    category_of: dict[str, str] = {}
    for category in ("durable_facts", "decisions", "commitments", "constraints"):
        for entry in manifest["truth"].get(category, []):
            category_of[str(entry["truth_id"])] = category
    out: dict[str, str] = {}
    for case in manifest["truth"]["retrieval_cases"]:
        found = sorted(
            {
                category_of[tid]
                for tid in case.get("expected_truth_ids", [])
                if tid in category_of
            }
        )
        out[str(case["case_id"])] = found[0] if len(found) == 1 else "mixed"
    return out


def _breakdown(rows: list[dict[str, Any]], key: str, order: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for value in order:
        subset = [row for row in rows if row.get(key) == value]
        if not subset:
            continue
        correct = sum(bool(row["correct"]) for row in subset)
        out[value] = {
            "correct": correct,
            "total": len(subset),
            "accuracy": round(correct / len(subset), 6),
        }
    return out


def _crosstab(
    rows: list[dict[str, Any]], key: str, order: tuple[str, ...]
) -> dict[str, Any]:
    """`key` × difficulty, correct/total per cell — the two marginals are not the same thing.

    A suite can hold its overall accuracy while losing every hard question on one axis; the
    marginals hide exactly that, because the axis row averages over easy questions and the tier
    row averages over easy axes. Sparse cells are left out rather than reported as zero: a cell
    with no questions is not a cell that failed.
    """
    out: dict[str, Any] = {}
    for value in order:
        cells: dict[str, Any] = {}
        for tier in DIFFICULTIES:
            subset = [
                row
                for row in rows
                if row.get(key) == value and row.get("difficulty") == tier
            ]
            if not subset:
                continue
            correct = sum(bool(row["correct"]) for row in subset)
            cells[tier] = {"correct": correct, "total": len(subset)}
        if cells:
            out[value] = cells
    return out


def _lane_summary(rows: list[dict[str, Any]], categories: dict[str, str]) -> dict[str, Any]:
    """One lane's whole picture: cases, the four breakdowns, and the facet-level view."""
    tagged = [{**row, "category": categories.get(row["case_id"], "mixed")} for row in rows]
    correct = sum(bool(row["correct"]) for row in tagged)
    return {
        "total": len(tagged),
        "correct": correct,
        "accuracy": round(correct / len(tagged), 6) if tagged else None,
        "by_axis": _breakdown(tagged, "axis", AXES),
        "by_difficulty": _breakdown(tagged, "difficulty", DIFFICULTIES),
        "by_expected_via": _breakdown(tagged, "expected_via", EXPECTED_VIA),
        "by_truth_category": _breakdown(
            tagged, "category", ("durable_facts", "decisions", "commitments", "constraints", "mixed")
        ),
        "by_axis_and_difficulty": _crosstab(tagged, "axis", AXES),
        "facets": facet_totals(rows),
    }


def summarize(
    positive: dict[str, Any],
    categories: dict[str, str],
    negatives: dict[str, Any],
    probes: dict[str, Any],
) -> dict[str, Any]:
    """Assemble the suite: per lane, then the negative suite and the probes.

    The two lanes are never added together. `fast` is the whole suite and the line a rebuild
    compares against; `deep` covers only the questions `lanes_for` sends there, so a single
    average over both would be an accuracy no configuration produces. `both_lanes` reports the
    fast lane restricted to exactly the deep subset, which is the only honest way to read the two
    side by side.

    Each row carries what the wire said beside the answer — the `answer_kind` the library
    assigned itself, and the canonical documents its own citations resolve to. Neither changes a
    score. They are what makes a wrong answer readable a year later: an answer that cited one
    page for a question about two chains is a different failure from one that cited nothing.
    """
    rows = positive.get("rows") or []
    by_lane = {
        lane: _lane_summary([row for row in rows if row["lane"] == lane], categories)
        for lane in LANES
        if any(row["lane"] == lane for row in rows)
    }
    deep_ids = {row["case_id"] for row in rows if row["lane"] == "deep"}
    comparison = {
        lane: _lane_summary(
            [row for row in rows if row["lane"] == lane and row["case_id"] in deep_ids],
            categories,
        )
        for lane in LANES
        if deep_ids and any(row["lane"] == lane for row in rows)
    }
    return {
        "positive": {
            "status": positive.get("status", "unavailable"),
            "reason": positive.get("reason", ""),
            "cases": len({row["case_id"] for row in rows}),
            "answered_rows": len(rows),
            "judge_decided_facets": sum(len(row["facets"]) for row in rows),
            "by_lane": by_lane,
            "both_lanes_on_the_deep_subset": comparison,
        },
        "negative": {
            key: value for key, value in negatives.items() if key != "cases"
        },
        "negative_by_shape_and_difficulty": _crosstab(
            negatives.get("cases") or [], "shape", NEGATIVE_SHAPES
        ),
        "negative_cases": negatives.get("cases") or [],
        "probes": {key: value for key, value in probes.items() if key != "probes"},
        "probe_rows": probes.get("probes", []),
        "cases": rows,
    }


def qa_group(
    positive: dict[str, Any], categories: dict[str, str]
) -> dict[str, Any] | None:
    """Group F in the eval package's own shape, so the scorecard renders beside the rest.

    The fast lane is what goes in: it is the only lane that covers the whole suite. `checks` are
    the CORE facets — the ones that gate — so the package's "checks passed" column reads as what
    it always did, and the detail line lives in this runner's own report where its meaning can be
    stated rather than guessed.
    """
    if positive.get("status") != "ok":
        return {
            "group": "F_usability_qa",
            "status": positive.get("status", "unavailable"),
            "reason": positive.get("reason", ""),
        }
    rows = [row for row in positive["rows"] if row["lane"] == "fast"]
    cases = [
        {
            "case_id": row["case_id"],
            "category": categories.get(row["case_id"], "mixed"),
            "question": row["question"],
            "answer": row["answer"],
            "checks": [
                {
                    "expected": facet["text"],
                    "score": facet["similarity"],
                    "mechanical_pass": None,
                    "judge_pass": facet["stated"],
                    "judge_verdict": facet["verdict"],
                    "judge_rationale": facet["judge_rationale"],
                    "correct": facet["stated"],
                }
                for facet in row["facets"]
                if facet["tag"] == "core"
            ],
            "correct": row["correct"],
        }
        for row in rows
    ]
    correct = sum(row["correct"] for row in cases)
    by_category: dict[str, Any] = {}
    for category in ("durable_facts", "decisions", "commitments", "constraints", "mixed"):
        subset = [row for row in cases if row["category"] == category]
        if not subset:
            continue
        passed = sum(row["correct"] for row in subset)
        by_category[category] = {
            "correct": passed,
            "total": len(subset),
            "accuracy": round(passed / len(subset), 6),
        }
    return {
        "group": "F_usability_qa",
        "status": "ok",
        # No mechanical threshold exists any more: every facet is decided by the judge. Reported
        # as null rather than dropped, because the package's renderer prints the field and a
        # stale number there would read as a rule that is still in force.
        "threshold": None,
        "judge_used": True,
        "cases_correct": correct,
        "cases_total": len(cases),
        "accuracy": round(correct / len(cases), 6) if cases else None,
        "by_category": by_category,
        "judge_decided_checks": sum(len(row["checks"]) for row in cases),
        "cases": cases,
    }


# ────────────────────────────────────────────────────────────────────── the reconciliation


def read_previous_line(spec: str) -> dict[str, Any]:
    """`label=path/to/opc-eval.json` → the comparable half of a line this one replaces.

    Tolerant of every shape this artifact has had: the first line reported one positive suite
    with no lanes and recorded no judge-prompt hash, the second reported per-lane summaries. What
    a comparison needs is the same in both — the fast-lane per-case verdicts, the headline
    numbers, and which grader produced them — so it is read defensively and what is missing is
    said rather than guessed.
    """
    label, _, raw_path = spec.partition("=")
    path = Path(raw_path or label)
    if not raw_path:
        label = path.parent.name or path.stem
    if not path.is_file():
        raise EvalInputError(f"no previous line at {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    suite = payload.get("suite") or {}
    positive = suite.get("positive") or {}
    headline = (positive.get("by_lane") or {}).get("fast") or positive
    rows = [
        row
        for row in (suite.get("cases") or [])
        if str(row.get("lane") or "fast") == "fast"
    ]
    negative = suite.get("negative") or {}
    return {
        "label": label,
        "path": str(path),
        "generated_at": str(payload.get("generated_at") or "")[:10],
        "corpus_key": payload.get("corpus_key"),
        "judge_model": payload.get("judge_model"),
        "judge_prompt_sha256": payload.get("judge_prompt_sha256"),
        # Absent from every line recorded before the field existed. Those lines were all
        # answered under `ranked`, but this reader says `not recorded` rather than filling in
        # what it was not told — a reconciliation that guesses at a configuration is worth
        # nothing, and the folder's README carries the history in prose.
        "evidence_strategy": payload.get("answering_evidence_strategy"),
        "positive": {
            "correct": headline.get("correct"),
            "total": headline.get("total"),
        },
        "negative": {
            "correct": negative.get("correct"),
            "total": negative.get("total"),
        },
        "case_status": {
            str(row["case_id"]): bool(row.get("correct")) for row in rows
        },
        "negative_status": {
            str(row["case_id"]): bool(row.get("correct"))
            for row in (suite.get("negative_cases") or [])
        },
    }


def current_line(payload: dict[str, Any]) -> dict[str, Any]:
    """This run, read the same way a previous line is, so the two are compared symmetrically."""
    suite = payload["suite"]
    headline = (suite["positive"].get("by_lane") or {}).get("fast") or {}
    rows = [row for row in suite.get("cases", []) if row.get("lane") == "fast"]
    return {
        "label": "this line",
        "generated_at": str(payload["generated_at"])[:10],
        "corpus_key": payload["corpus_key"],
        "judge_model": payload.get("judge_model"),
        "judge_prompt_sha256": payload.get("judge_prompt_sha256"),
        "evidence_strategy": payload.get("answering_evidence_strategy"),
        "positive": {
            "correct": headline.get("correct"),
            "total": headline.get("total"),
        },
        "negative": {
            "correct": suite["negative"].get("correct"),
            "total": suite["negative"].get("total"),
        },
        "case_status": {str(row["case_id"]): bool(row["correct"]) for row in rows},
        "negative_status": {
            str(row["case_id"]): bool(row["correct"])
            for row in suite.get("negative_cases", [])
        },
    }


def _ruler_changes(manifest: dict[str, Any]) -> dict[str, list[str]]:
    """`case_id → the ruler revisions that touched it`, as the truth set declares them.

    Retired questions are declared beside the live ones. A case that left the set is exactly the
    kind of change a reconciliation exists to explain, and it has no row left to carry the flag.
    """
    out: dict[str, list[str]] = {}
    for case in manifest["truth"].get("retrieval_cases", []) + manifest["truth"].get(
        "negatives", []
    ):
        changes = case.get("ruler_changes")
        if changes:
            out[str(case["case_id"])] = [str(value) for value in changes]
    retired = (manifest.get("reconciliation") or {}).get("retired_cases") or {}
    for case_id, changes in retired.items():
        out.setdefault(str(case_id), [str(value) for value in changes])
    return out


def _set_version(corpus_key: Any) -> int | None:
    """The truth set's revision number, read off its own `experiment_id` (`…-v3` → 3)."""
    match = re.search(r"v(\d+)$", str(corpus_key or ""))
    return int(match.group(1)) if match else None


def _verdict_word(status: bool | None, *, absent: str) -> str:
    if status is None:
        return absent
    return "pass" if status else "miss"


def reconciliation_section(
    payload: dict[str, Any], manifest: dict[str, Any], previous: list[dict[str, Any]]
) -> str:
    """The section a re-scored line owes its predecessor: what moved, and which change moved it.

    Nothing here is a judgement call made at writing time. The case lists are the mechanical diff
    of two runs' per-case verdicts; each changed case is filed under the ruler revision the truth
    set says touched it (`ruler_changes`), and a case the truth set does not name has carried the
    same facets since that line — so what moved under it is whatever else changed between the two
    runs. The headline and the basis line are the manifest's, not this function's: what a reader
    needs before any number is what did and did not change underneath the two lines, and only the
    set being scored knows that.
    """
    config = manifest.get("reconciliation") or {}
    if not previous:
        return ""
    now = current_line(payload)
    if not now["case_status"]:
        # A mechanical run answers nothing, so every question on the previous line would read as
        # having been dropped. Say why there is no comparison rather than render a table of 81
        # phantom regressions.
        return (
            "## Reconciliation\n\nnot rendered: this run did not answer the suite "
            f"(mode `{payload['mode']}`), so there is nothing to set beside a scored line."
        )
    changes = _ruler_changes(manifest)
    groups = config.get("groups") or []
    order = [str(group["key"]) for group in groups]
    notes = {str(group["key"]): group for group in groups}
    #: The truth-set revision each group was introduced by, so a moved case can be filed under
    #: a change that lies between the two lines rather than under one both were scored with.
    since = {str(group["key"]): _set_version(group.get("since")) for group in groups}
    unattributed = config.get("unattributed_group_for") or {}

    lines: list[str] = []
    headline = str(config.get("headline") or "an eval-set change, not a library change")
    lines.append(f"## Reconciliation — {headline}")
    lines.append("")
    lines.append(
        str(
            config.get("basis")
            or (
                "Same library, byte-for-byte; same stack, same corpus, same harness, no compile "
                "in between. Every difference below is a difference in the ruler."
            )
        )
    )
    lines.append("")
    if config.get("note"):
        lines.append(str(config["note"]))
        lines.append("")
    lines.append(
        "| line | truth set | run | judge prompt | answering | fast-lane positive | negative |"
    )
    lines.append("|---|---|---|---|---|---:|---:|")
    for line in [*previous, now]:
        fingerprint = line.get("judge_prompt_sha256")
        strategy = line.get("evidence_strategy")
        lines.append(
            f"| {line['label']} | `{line.get('corpus_key')}` | {line.get('generated_at')} "
            f"| `{fingerprint[:12] if fingerprint else 'not recorded'}` "
            f"| {f'`{strategy}`' if strategy else 'not recorded'} "
            f"| {line['positive']['correct']} / {line['positive']['total']} "
            f"| {line['negative']['correct']} / {line['negative']['total']} |"
        )
    lines.append("")

    for line in previous:
        lines.append(f"### Against `{line['label']}` ({line.get('generated_at')})")
        lines.append("")
        moved: list[tuple[str, str, str, str]] = []  # group, case, then, now
        fallback = str(
            unattributed.get(str(line.get("corpus_key")), "unattributed")
        )
        # A case is filed only under a revision that lies BETWEEN the two lines. `corpus_key` is
        # the truth set's own `experiment_id` and carries its revision number, and every group
        # declares the revision that introduced it, so a revision the compared line was already
        # scored under cannot have moved anything since — its facets were byte-identical on both
        # lines. Filing a case under one anyway would credit, say, a facet split with a move it
        # could not have made. What is left for a case with no revision in between is the
        # fallback the map names for that key: where a change outside the truth set — the judge's
        # language, the engine's answering path — and the answering lane's own noise live. Two
        # lines on the same set have nothing in between by definition, which is this same rule.
        then_version = _set_version(line.get("corpus_key"))
        now_version = _set_version(now.get("corpus_key"))
        for suite_key in ("case_status", "negative_status"):
            then_all = line[suite_key]
            now_all = now[suite_key]
            for case_id in sorted(set(then_all) | set(now_all)):
                then = then_all.get(case_id)
                current = now_all.get(case_id)
                if then == current:
                    continue
                keys = changes.get(case_id, [])
                if then_version is not None and now_version is not None:
                    keys = [
                        key
                        for key in keys
                        if since.get(key) is not None and since[key] > then_version
                    ]
                elif str(line.get("corpus_key") or "") == str(now.get("corpus_key") or ""):
                    keys = []
                group = next((key for key in order if key in keys), fallback)
                moved.append(
                    (
                        group,
                        case_id,
                        _verdict_word(then, absent="— (not asked on that line)"),
                        _verdict_word(current, absent="— (retired)"),
                    )
                )
        if not moved:
            lines.append("No case changed status.")
            lines.append("")
            continue
        lines.append(
            f"{len(moved)} of {len(set(line['case_status']) | set(now['case_status']) | set(line['negative_status']) | set(now['negative_status']))} "
            "questions changed status, grouped by the ruler revision that touched them."
        )
        lines.append("")
        for group in [*order, fallback] if fallback not in order else order:
            subset = [row for row in moved if row[0] == group]
            if not subset:
                continue
            title = str((notes.get(group) or {}).get("title") or group)
            lines.append(f"#### {title} — {len(subset)} question(s)")
            lines.append("")
            note = (notes.get(group) or {}).get("note")
            if note:
                lines.append(str(note))
                lines.append("")
            lines.append(f"| case | {line['label']} | this line |")
            lines.append("|---|---|---|")
            for _, case_id, then, current in subset:
                lines.append(f"| `{case_id}` | {then} | {current} |")
            lines.append("")
    return "\n".join(lines)


def render_opc_report(payload: dict[str, Any], reconciliation: str = "") -> str:
    """The OPC-specific half of the report: axes, tiers, the negative suite, the probes."""
    lines: list[str] = ["# OPC regression eval — question suite", ""]
    lines.append(f"- generated: `{payload['generated_at']}`")
    lines.append(f"- mode: `{payload['mode']}`")
    lines.append(f"- truth set: `{payload['truth_set']}` ({payload['corpus_key']})")
    lines.append(f"- library: `{payload['canonical']}`")
    lines.append(f"- answered by: `{payload['api']}` / `{payload['user']}` "
                 f"(visitor class `{payload['visitor_class']}`)")
    lines.append(f"- judge: `{payload['judge_model']}` "
                 f"(provider pinned: {str(payload['judge_provider_pinned']).lower()}; "
                 f"prompt sha256 `{payload['judge_prompt_sha256'][:12]}`)")
    calibration = payload.get("judge_calibration")
    if calibration:
        lines.append(
            f"- judge calibration: {calibration['agreed']}/{calibration['items']} items agreed "
            f"({_percent(calibration['agreement'])}); blocking variants "
            + ("all agreed" if calibration["passed"] else "FAILED")
            + " — see `judge-calibration.md`"
        )
    lines.append("")
    if reconciliation:
        lines.append(reconciliation)
        lines.append("")
    summary = payload["suite"]
    positive = summary["positive"]
    lines.append("## Positive suite")
    lines.append("")
    if positive["status"] != "ok":
        lines.append(f"not run: {positive.get('reason', '')}")
        lines.append("")
    for lane, lane_summary in positive.get("by_lane", {}).items():
        facets = lane_summary["facets"]
        lines.append(f"### Lane `{lane}`")
        lines.append("")
        lines.append(
            f"**{lane_summary['correct']} / {lane_summary['total']}** "
            f"({lane_summary['accuracy']}) — a case is correct when every core facet is stated"
        )
        lines.append("")
        lines.append(
            f"- core facets stated: {facets['core_stated']}/{facets['core_facets']} "
            f"({facets['core_recall']})"
        )
        lines.append(
            f"- detail_recall: {facets['detail_stated']}/{facets['detail_facets']} "
            f"({facets['detail_recall']}) — reported, never gating"
        )
        lines.append(
            f"- contradicted: {facets['core_contradicted']} core, "
            f"{facets['detail_contradicted']} detail"
        )
        lines.append("")
        for title, key, order in (
            ("By axis", "by_axis", AXES),
            ("By difficulty", "by_difficulty", DIFFICULTIES),
            ("By expected_via", "by_expected_via", EXPECTED_VIA),
        ):
            lines.append(f"#### {title}")
            lines.append("")
            lines.append("| | correct | total | accuracy |")
            lines.append("|---|---:|---:|---:|")
            for name in order:
                row = lane_summary[key].get(name)
                if row:
                    lines.append(
                        f"| {name} | {row['correct']} | {row['total']} | {row['accuracy']} |"
                    )
            lines.append("")
    comparison = positive.get("both_lanes_on_the_deep_subset", {})
    if comparison:
        lines.append("### Both lanes, on the deep subset only")
        lines.append("")
        lines.append("| lane | correct | total | accuracy | detail_recall |")
        lines.append("|---|---:|---:|---:|---:|")
        for lane, lane_summary in comparison.items():
            lines.append(
                f"| {lane} | {lane_summary['correct']} | {lane_summary['total']} "
                f"| {lane_summary['accuracy']} | {lane_summary['facets']['detail_recall']} |"
            )
        lines.append("")
    fast = positive.get("by_lane", {}).get("fast", {})
    for title, table in (
        ("### By axis × difficulty (fast lane)", fast.get("by_axis_and_difficulty", {})),
        ("### By negative shape × difficulty", summary.get("negative_by_shape_and_difficulty", {})),
    ):
        if not table:
            continue
        lines.append(title)
        lines.append("")
        lines.append("| | " + " | ".join(DIFFICULTIES) + " |")
        lines.append("|---" * (len(DIFFICULTIES) + 1) + "|")
        for name, cells in table.items():
            row = [
                (f"{cells[tier]['correct']}/{cells[tier]['total']}" if tier in cells else "—")
                for tier in DIFFICULTIES
            ]
            lines.append(f"| {name} | " + " | ".join(row) + " |")
        lines.append("")
    negative = summary["negative"]
    lines.append("## Negative suite (fabrication resistance)")
    lines.append("")
    if negative.get("status") == "ok":
        lines.append(
            f"**{negative['correct']} / {negative['total']}** — abstained "
            f"{negative['abstained']}, fabricated {negative['fabricated']}, "
            f"undecided {negative['undecided']}"
        )
        lines.append("")
        lines.append(
            "| shape | correct | total | abstained | fabricated | undecided | premise accepted |"
        )
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for shape, row in negative.get("by_shape", {}).items():
            premise = (
                f"{row['premise_accepted']}/{row['total']}"
                + (
                    f" ({row['premise_undecided']} undecided)"
                    if row.get("premise_undecided")
                    else ""
                )
                if "premise_accepted" in row
                else "—"
            )
            lines.append(
                f"| {shape} | {row['correct']} | {row['total']} | {row['abstained']} "
                f"| {row['fabricated']} | {row['undecided']} | {premise} |"
            )
        premise = negative.get("premise") or {}
        if premise.get("total"):
            lines.append("")
            lines.append(
                f"`premise_accepted` — of {premise['total']} false-premise questions the answer "
                f"accepted the premise in {premise['accepted']} and rejected it in "
                f"{premise['rejected']} ({premise['undecided']} undecided). A second verdict, "
                "reported apart from the fabrication line and never folded into it."
            )
    else:
        lines.append(f"not run: {negative.get('reason', '')}")
    lines.append("")
    lines.append("## Structure probes")
    lines.append("")
    for row in summary["probe_rows"]:
        verdict = "PASS" if row["passed"] else "FAIL"
        lines.append(
            f"- **{verdict}** `{row['probe_id']}` — {row['a_label']} → "
            f"`{row['a_home']}`; {row['b_label']} → `{row['b_home']}`"
        )
        lines.append(
            f"  - corpus basis: `{row['corpus_basis']['corpus_file']}` — "
            f"“{row['corpus_basis']['quote']}”"
        )
    lines.append("")
    unresolved = payload["evidence"]["unresolved"]
    lines.append("## Evidence binding")
    lines.append("")
    lines.append(
        f"{payload['evidence']['resolved']} of {payload['evidence']['total']} authored "
        f"quotes resolved to an L0 block in this build; {len(unresolved)} did not."
    )
    lines.append("")
    return "\n".join(lines)


def judge_chat(model: str | None) -> tuple[Any, str, bool]:
    """The judge this suite grades with: the chat model, its id, and whether it is pinned.

    The eval package builds its judge without provider options, which for a GPT-series model on
    OpenRouter means the request may be answered by a reseller of the same model — different
    quantization, silently, between two runs that call themselves the same measurement. This
    project already states its route in `.env` for every model the engine calls; the judge takes
    the same route, and the artifact records whether it got it, because a comparison against this
    baseline has to know which grader produced it.
    """
    from pneuma_knowledge_eval.qa import _judge_chat as build  # noqa: PLC2701

    chat = build(model=model)
    resolved = str(getattr(chat, "model_name", "") or model or "")
    order = [
        name.strip()
        for name in os.environ.get("PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER", "").split(",")
        if name.strip()
    ]
    allow = os.environ.get("PNEUMA_KNOWLEDGE_OPENROUTER_ALLOW_FALLBACKS", "").strip().lower()
    on_openrouter = "openrouter" in str(os.environ.get("OPENROUTER_BASE_URL", ""))
    if not (order and on_openrouter):
        return chat, resolved, False
    pinned = chat.bind(
        extra_body={
            "provider": {
                "order": order,
                "allow_fallbacks": allow in ("1", "true", "yes", "on"),
            }
        }
    )
    return pinned, resolved, True


def load_env(path: Path) -> list[str]:
    """Take the key and the OpenRouter base url from this project's own `.env`.

    The full arms reach a model, and this project already states where its credentials live.
    Reading them here rather than requiring an exported shell is the difference between one
    documented command and a command plus a paragraph of setup. Values already in the
    environment always win, and nothing is ever printed.
    """
    taken: list[str] = []
    if not path.is_file():
        return taken
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name not in (
            "OPENROUTER_API_KEY",
            "OPENROUTER_BASE_URL",
            "OPENAI_API_KEY",
            # The route, not the strategy: which provider serves an `openrouter:<model>` call.
            # The judge takes the same one the engine's own models take.
            "PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER",
            "PNEUMA_KNOWLEDGE_OPENROUTER_ALLOW_FALLBACKS",
        ):
            continue
        if os.environ.get(name):
            continue
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ[name] = value
            taken.append(name)
    # langchain-openai defaults to api.openai.com; an OpenRouter key sent there fails with an
    # authentication error that reads like a missing key. State the endpoint that goes with
    # the credential rather than letting the arm fail under a misleading message.
    if os.environ.get("OPENROUTER_API_KEY") and not os.environ.get("OPENROUTER_BASE_URL"):
        os.environ["OPENROUTER_BASE_URL"] = "https://openrouter.ai/api/v1"
        taken.append("OPENROUTER_BASE_URL (defaulted)")
    return taken


def run_judge_mode(args: argparse.Namespace) -> int:
    """`--mode judge`: calibrate the ruler and nothing else.

    No stack, no truth set, no library — the suite is about the judge's reading of a phrasing,
    so it asks nothing of the thing being graded. Exit 1 when a blocking variant disagrees.
    """
    taken = load_env(EXAMPLE_ROOT / ".env")
    if taken:
        print(f"note: took {', '.join(taken)} from the project's .env", file=sys.stderr)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    chat, judge_model, judge_pinned = judge_chat(args.judge_model)
    result = calibrate_judge(args, out, chat, judge_model, judge_pinned)
    print(json.dumps(calibration_header(result), ensure_ascii=False, indent=2))
    if not result["passed"]:
        print(
            "ERROR: the judge disagrees with the calibration suite on blocking variant(s): "
            + ", ".join(result["blocking_failures"]),
            file=sys.stderr,
        )
        return 1
    return 0


def run(args: argparse.Namespace) -> int:
    if args.mode == "judge":
        return run_judge_mode(args)
    taken = load_env(EXAMPLE_ROOT / ".env") if args.mode == "full" else []
    if taken:
        print(f"note: took {', '.join(taken)} from the project's .env", file=sys.stderr)
    manifest = json.loads(Path(args.truth).read_text(encoding="utf-8"))
    truth = load_frozen_truth_manifest(args.truth)
    validate_cases(manifest)
    categories = case_categories(manifest)
    corpus = Corpus.load(Path(args.corpus), owner_script=Path(args.owner_statement))
    canonical = Path(args.canonical)
    if not (canonical / ".git").is_dir():
        canonical = canonical / args.user
    if not (canonical / ".git").is_dir():
        raise EvalInputError(f"no canonical git repository at {canonical}")

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    # The ruler is calibrated BEFORE the library is touched. A judge that cannot hold its own
    # verdicts across a change of phrasing does not produce a line comparable with any other
    # line, so a failed calibration is a refusal to score rather than a warning printed over a
    # scorecard — and it happens here, before the stack is asked for anything, so the refusal
    # costs nothing but the calibration itself.
    chat: Any | None = None
    judge_model = args.judge_model
    judge_pinned = False
    calibration: dict[str, Any] | None = None
    if args.mode == "full" and not args.no_judge:
        chat, judge_model, judge_pinned = judge_chat(args.judge_model)
        calibration = calibrate_judge(args, out, chat, judge_model, judge_pinned)
        if not calibration["passed"]:
            print(
                "ERROR: the judge disagrees with its calibration suite on blocking variant(s): "
                + ", ".join(calibration["blocking_failures"])
                + f" — see {out / 'judge-calibration.md'}. A ruler that fails its own "
                "calibration cannot produce a comparable line, so nothing was scored.",
                file=sys.stderr,
            )
            return 1

    l0 = harvest_l0(args.api, args.user)
    pg = l0.write_pg_dumps(out)
    resolver = EvidenceResolver(corpus, l0)
    locators: list[Locator] = []

    def bind(row: dict[str, Any]) -> None:
        locators.append(
            resolver.resolve(
                row["corpus_file"], row["quote"], str(row.get("corpus_source") or "")
            )
        )

    for section in ("durable_facts", "decisions", "commitments", "constraints"):
        for entry in manifest["truth"].get(section, []):
            for row in entry.get("evidence", []):
                bind(row)
    for case in manifest["truth"].get("retrieval_cases", []):
        for row in case.get("evidence", []):
            bind(row)
        for facet in case.get("facets", []):
            for row in facet.get("evidence", []):
                bind(row)
    for case in manifest["truth"].get("negatives", []):
        for row in case.get("evidence", []):
            bind(row)
    for probe in manifest["truth"].get("structure_probes", []):
        bind(probe["corpus_basis"])
    unresolved = [row.as_json() for row in locators if row.cite is None]
    if unresolved and not args.allow_unresolved:
        for row in unresolved:
            print(
                f"ERROR: unresolved evidence: {row['corpus_file']} — {row['reason']}: "
                f"{row['quote'][:40]}…",
                file=sys.stderr,
            )
        raise EvalInputError(
            f"{len(unresolved)} authored quote(s) do not resolve to an L0 block in this "
            "build; the set claims every truth value came from the corpus, so this is a "
            "hard stop (pass --allow-unresolved to record them and continue)"
        )

    trajectory = load_repo_trajectory(canonical, pg_dumps=pg, bundle_id=args.user)

    gate = CallGate(args.concurrency)
    answers = {lane: Answers(args.api, args.user, gate=gate, mode=lane) for lane in LANES}
    positive: dict[str, Any] = {
        "status": "skipped",
        "reason": "mechanical mode is defined as zero-LLM and zero-network answering",
    }
    negatives: dict[str, Any] = dict(positive)
    truth_judge = None
    matcher = None
    if args.mode == "full":
        # Group B's entailment arm is opt-in, and the reason is arithmetic rather than taste:
        # it is consulted once per (labelled fact, checkpoint) pair the character threshold
        # rejected, and this trajectory has 166 checkpoints — ~950 sequential model calls
        # against ~300 for every other arm in this command put together, with no partial result
        # if one of them fails. The default therefore reports group B's similarity arm and
        # marks the judged arm unavailable with its own reason, which is what the package does
        # for a run that did not have it.
        truth_judge = (
            build_truth_judge(model=args.judge_model)
            if (args.truth_judge and not args.no_judge)
            else None
        )
        from pneuma_knowledge_eval.embedding import build_embedding_matcher, collect_texts

        matcher = build_embedding_matcher(collect_texts(trajectory, truth))
        positive, negatives = asyncio.run(
            score_answered_arms(manifest, answers, chat, gate, CitedSpans(l0))
        )
        print(gate.line())

    scorecard = build_scorecard(
        trajectory,
        mode=args.mode,
        truth=truth,
        matcher=matcher,
        qa=qa_group(positive, categories) if args.mode == "full" else None,
        declared_language=args.declared_language,
        truth_judge=truth_judge,
    )
    probes = run_probes(manifest["truth"].get("structure_probes", []), canonical)
    suite = summarize(positive, categories, negatives, probes)

    payload = {
        "schema": "pneuma.opc.eval/v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": args.mode,
        "truth_set": str(Path(args.truth).name),
        "corpus_key": truth.corpus_key,
        "canonical": str(canonical),
        "api": args.api,
        "user": args.user,
        "visitor_class": "silent",
        "answer_lanes": sorted({row["lane"] for row in (positive.get("rows") or [])}),
        "answer_format": "structured",
        # The one engine knob a re-scored line has to state, taken from the answers themselves.
        # Null on a run that answered nothing (`--mode mechanical`, `--no-judge`).
        "answering_evidence_strategy": answering_strategy(positive),
        "judge_model": None if args.no_judge else judge_model,
        # Whether the judge's request took this project's own provider route. The framework pins
        # GPT-series calls made through OpenRouter to the official provider; the eval package
        # builds its judge without provider options, so this runner applies the same pin from the
        # project's `.env` and records here whether it got one. Stated in the artifact rather than
        # only in a commit message, because a later comparison has to know which grader ran.
        "judge_provider_pinned": judge_pinned,
        # The exact judging language, hashed. The judge is the grader now, so a change to these
        # templates moves numbers as surely as a change to the library does.
        "judge_prompt_sha256": judge_prompt_fingerprint(),
        # How that judging language did on the calibration suite that gated this run. The hash
        # above says WHICH words graded the line; this says how those words held up across the
        # phrasings a real answer produces, which is the half a hash cannot carry.
        "judge_calibration": calibration_header(calibration) if calibration else None,
        "truth_judge_arm": bool(args.truth_judge and not args.no_judge),
        # What the answered arms cost in wall time and how wide they ran. A cost line, never a
        # quality line: the rows are reassembled in truth-set order, so nothing above or below
        # this key changes when the bound does — which is exactly what makes it safe to raise.
        "throughput": gate.summary() if args.mode == "full" else None,
        "evidence": {
            "total": len(locators),
            "resolved": sum(1 for row in locators if row.cite),
            "unresolved": unresolved,
            "locators": [row.as_json() for row in locators],
        },
        "suite": suite,
        "scorecard_groups": {
            name: {
                key: value
                for key, value in group.items()
                if key not in ("cases", "per_checkpoint", "samples")
            }
            for name, group in scorecard["groups"].items()
        },
    }
    previous = [read_previous_line(spec) for spec in (args.previous or [])]
    reconciliation = reconciliation_section(payload, manifest, previous)
    payload["reconciliation"] = {
        "compared_against": [
            {key: value for key, value in line.items()
             if key not in ("case_status", "negative_status")}
            for line in previous
        ],
        "note": "the per-case diff behind this is rendered in opc-eval.md and report.md",
    }
    (out / "opc-eval.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / "opc-eval.md").write_text(
        render_opc_report(payload, reconciliation), encoding="utf-8"
    )
    json_path, report_path = write_outputs(scorecard, out)
    if reconciliation:
        # The package renders the scorecard and knows nothing about previous lines of one
        # example's own suite, so the section is inserted under that report's title rather than
        # bent into the package. Under the title, not above it: a file that opens with a
        # subsection of a document it has not named yet reads as a fragment.
        rendered = report_path.read_text(encoding="utf-8").split("\n", 1)
        report_path.write_text(
            f"{rendered[0]}\n\n{reconciliation}\n{rendered[1] if len(rendered) > 1 else ''}",
            encoding="utf-8",
        )

    missing = unavailable_because(scorecard, L0_ABSENT)
    print(
        json.dumps(
            {
                "mode": args.mode,
                "claims_at_head": scorecard["bundle"]["claims_at_head"],
                "checkpoints": scorecard["bundle"]["checkpoints"],
                "l0_sources": scorecard["bundle"]["sources"],
                "evidence_resolved": payload["evidence"]["resolved"],
                "evidence_total": payload["evidence"]["total"],
                "positive_by_lane": {
                    lane: f"{row['correct']}/{row['total']}"
                    for lane, row in suite["positive"].get("by_lane", {}).items()
                },
                "detail_recall_fast": (
                    suite["positive"]
                    .get("by_lane", {})
                    .get("fast", {})
                    .get("facets", {})
                    .get("detail_recall")
                ),
                "negative": suite["negative"].get("accuracy"),
                "probes_passed": f"{probes['passed']}/{probes['total']}",
                "findings": len(scorecard["findings"]),
                "l0_absent_metrics": [row["metric"] for row in missing],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"OK: scorecard  → {json_path}")
    print(f"OK: report     → {report_path}")
    print(f"OK: opc suite  → {out / 'opc-eval.json'}")
    print(f"OK: opc report → {out / 'opc-eval.md'}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_eval.py", description="score a built OPC library against the frozen truth set"
    )
    parser.add_argument("--truth", type=Path, default=DEFAULT_TRUTH)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument(
        "--canonical",
        type=Path,
        default=DEFAULT_CANONICAL,
        help="the canonical git repository, or the directory holding one per user",
    )
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument(
        "--mode", choices=("mechanical", "full", "judge"), default="mechanical"
    )
    parser.add_argument(
        "--calibration",
        type=Path,
        default=DEFAULT_CALIBRATION,
        help="the judge's calibration suite. `--mode judge` runs it alone; `--mode full` runs "
        "it first and refuses to score when a blocking variant disagrees",
    )
    parser.add_argument(
        "--owner-statement",
        type=Path,
        default=DEFAULT_OWNER_STATEMENT,
        help="the script that sends the owner statement; its OWNER_DIALOGUE literal is the "
        "191st source's authored text, and evidence marked corpus_source=owner_statement is "
        "checked against it",
    )
    parser.add_argument("--judge-model")
    parser.add_argument(
        "--no-judge",
        action="store_true",
        help="run without the judge: it decides every facet, so the positive suite reports "
        "unavailable and asks nothing, and the negative suite answers but withholds its verdicts",
    )
    parser.add_argument(
        "--truth-judge",
        action="store_true",
        help="also run group B's entailment arm — one model call per (fact, checkpoint) pair "
        "the character threshold rejected, which on a long trajectory is ~10x the cost of "
        "every other arm here combined",
    )
    parser.add_argument("--declared-language", default="zh-CN")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help="how many provider calls the answered arms keep in flight (default "
        f"{DEFAULT_CONCURRENCY}; 1 is the serial behaviour). Every call is latency, and the "
        "rows are reassembled in truth-set order, so this changes the wall clock and nothing "
        "in the score",
    )
    parser.add_argument(
        "--previous",
        action="append",
        metavar="LABEL=PATH",
        help="a line this run is compared against: the path to an earlier opc-eval.json, "
        "optionally with a label (`truth-v1=…/opc-eval.json`). Repeatable. Each one adds a "
        "reconciliation section — headline numbers, judge-prompt hashes, and every case whose "
        "status changed, filed under the ruler revision the truth set says touched it — to the "
        "top of opc-eval.md and report.md",
    )
    parser.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="record quotes that do not bind to an L0 block instead of stopping",
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except (EvalInputError, EvalDependencyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
