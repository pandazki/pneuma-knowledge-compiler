"""A per-case rigor audit of `eval/opc-truth.json` against this example's own inputs.

This is not a scorer and it never touches a built library. Each case of the truth set — the
retrieval cases, the negatives and the structure probe — is handed verbatim to its own
read-only process, whose only admissible evidence is `my-data/` and the owner statement in
`build-record/exercise.py`. The auditor returns a schema-bound JSON verdict saying whether the
case, AS WRITTEN, is a correct and unambiguous test, and what the corrected case should say
where it is not. A truth set is a ruler; this is how the ruler gets checked, case by case,
against the material it claims to measure.

The audit is an input, never an authority. What reaches the truth set is a maintainer's triage
of these verdicts — accept, reject, or modify, item by item — recorded in the truth file's
`ruler_changes` and `supersedes`. The verdicts of the v6 audit are kept beside the reference
line in `build-record/eval/2026-09-03-truth-audit/`.

Requires the Codex CLI (`codex exec`) on PATH; each case is one read-only invocation, and there
is no fallback — a run without it does nothing rather than auditing with something else.

Usage:
  uv run python eval/audit_truth.py [--only case-id,...] [--workers 12] [--dry-run]
  uv run python eval/audit_truth.py --aggregate      # verdicts in var/truth-audit/out → summary.md
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
OPC = Path(__file__).resolve().parents[1]
TRUTH = OPC / "eval" / "opc-truth.json"
SCHEMA = HERE / "audit-verdict.schema.json"
#: Everything a run produces is derived and re-derivable, so it lands in the example's
#: git-ignored scratch directory beside every other run artifact.
WORK = OPC / "var" / "truth-audit"
PROMPTS = WORK / "prompts"
OUT = WORK / "out"
LOGS = WORK / "logs"
SUMMARY = WORK / "summary.md"

COMMON = """You are auditing ONE case of a frozen regression truth set for rigor. You are not
answering the question and not scoring any system. Your job: decide whether the case, as
written, is a correct and unambiguous test against the corpus, and if not, say precisely
what is wrong and what the corrected case should say.

## Evidence rules (strict)
- The ONLY admissible evidence is the example's own inputs:
  1. `my-data/` — 190 Markdown files, filenames start with a date (YYYY-MM-DD-...). This is
     84 days of one person's synthetic working life: meetings, IM, notes, mail. Read
     whatever you need with grep/rg/cat; the corpus is Chinese.
  2. The owner statement: the `OWNER_DIALOGUE` literal in `build-record/exercise.py`
     (dialogue id `dlg-2026-09-01-weikuan`, dated 2026-09-01, which is AFTER every file in
     `my-data/`). Its owner turns are part of the corpus and override earlier state where
     they say so.
- Do NOT read, grep or open: `prebuilt/`, `build-record/eval/`, `build-record/BUILD-LOG.md`,
  `build-record/use-side/`, `var/`, `data/`, `engine/`, or any compiled/canonical output.
  The truth must be judged against inputs only; a compiled library is the thing under
  test and must not bias the truth.
- Do not modify any file. Work read-only.

## What "rigorous" means here
- `question` must be answerable from the corpus alone and unambiguous: one reasonable
  reader should not be able to defend two different answers. Watch especially for TEMPORAL
  ambiguity: if the corpus records several values over time and the question does not fix
  a point in time, the latest state is what "当前/现在" means — but if the question says
  neither, flag it. Also watch for HISTORICAL NOISE: earlier drafts, proposals, rumours,
  or corrected values that a careless answer could pick up; the truth must be the one the
  corpus actually settles on, and if the corpus never settles, the case is wrong.
- Every quote must appear VERBATIM (exact substring, same punctuation) in the named file.
- Search the WHOLE corpus for later files that change, retract, or supersede the value —
  not only the file the case cites. A facet that was true on its as_of date but is
  contradicted by a later file is `facet_superseded` unless the question fixes that date.
- Search for near-miss names and look-alike entities (e.g. 云岭 vs 云麓, 陈昉 vs 陈放):
  the corpus is built with deliberate near-misses.

Use `rg -n` (ripgrep) or `grep -rn` over `my-data/` for every name, number, date and term
in the case before you conclude. Read the full text of every file you cite; do not judge
from grep lines alone.

## Output
Return ONLY the JSON verdict (the schema is enforced). `verdict`:
- `sound` — the case is correct as written; `issues` may still list `minor` items.
- `fix` — at least one `blocking` or `material` issue; each with concrete corpus evidence
  (file + verbatim quote) and a `proposed_change` written as the corrected text.
- `unsure` — you could not settle it from the corpus; say exactly what you could not find.
Severity: `blocking` = the case would grade a correct answer as wrong or a wrong answer as
right; `material` = the case is defensible but a careful author would change it (tag,
wording, missing facet a reasonable answer would include); `minor` = cosmetic.
`facet_id`: the facet in question, or the case id for case-level issues.
`corpus_files_read`: every file you actually read in full.
"""

RETRIEVAL = """
## This case: a POSITIVE retrieval case
Grading rule you are auditing against: an answer is correct when EVERY `core` facet is
entailed by the answer (paraphrase counts; a more specific statement counts); `detail`
facets are counted separately and never fail the case. A judge marks each facet
stated / omitted / contradicted.

Check, in order:
1. Each facet's `evidence[].quote` is a verbatim substring of `evidence[].corpus_file`.
2. Each facet `text` is entailed by the corpus (the cited quote in context, or the
   corpus as a whole), and is a SINGLE proposition (no "X：Y", "X，也 Y", "X 而不是 Y"
   where both halves are separate claims).
3. Each facet is still true as of the latest corpus state (or as of the date the
   question fixes). Search for later files.
4. Tagging: a `core` facet must be exactly a thing the question asks for. A core facet
   the question does not ask for is `over_narrow_core` (it would fail a correct answer).
   A thing the question plainly asks for that no facet captures is `missing_core` (a wrong
   or incomplete answer would pass). Something merely related is `detail`.
5. The question itself: unambiguous; not answerable in two defensible ways; if it says
   "当前/现在/目前", the corpus must have a single latest value; if it asks for a set
   ("哪些"), the set must be closed in the corpus.
6. `axis` and `difficulty` are the author's classification — flag only if plainly wrong.
   `expected_via` (canonical vs verbatim) is a contract judgement — do not audit it.

Case (verbatim):
"""

NEGATIVE = """
## This case: a NEGATIVE case (the correct behaviour is to refuse / correct the question)
Shapes: `unanswerable_detail` — the corpus never records the thing asked;
`nonexistent_subject` — the subject does not exist in the corpus (often a near-miss of a
real name); `false_premise` — the question presupposes something the corpus contradicts.
Grading rule you are auditing against: `absent` is handed to a judge as a TRUE statement;
an answer that asserts the absent thing (gives the value, treats the subject as real,
accepts the premise) is `fabricated`; stating the absence or the corrective corpus fact is
correct.

Check, in order:
1. `absent` is actually true: grep the whole corpus (and the owner statement) for the
   value / subject / premise, including numerals in Chinese and Arabic forms, synonyms and
   near-miss spellings. If ANY file gives the thing asked, the case is `absent_is_present`
   (blocking). For `nonexistent_subject`, name the real subject it is a near-miss of and
   confirm the invented name occurs nowhere. For `false_premise`, confirm the premise is
   contradicted (not merely unmentioned) and that the corrective fact in `absent` is
   itself correct and current.
2. Every sentence of `absent` beyond the bare absence is a corpus fact with a verbatim
   basis — `absent` is handed to the judge as truth, so an error inside it becomes a
   grading error.
3. `evidence[].quote` verbatim in `evidence[].corpus_file`.
4. The question does not accidentally have a legitimate answer (e.g. a value that exists
   under a slightly different name, or a premise that is true in an earlier file).

Case (verbatim):
"""

PROBE = """
## This case: a STRUCTURE probe
It asserts a rule of the material (two things the corpus says must stay separate) and is
checked mechanically against the built library. Audit only `corpus_basis` and `note`: is
the rule really stated by the corpus, verbatim where quoted, and still in force at the
latest corpus state? `probe_basis_wrong` if not.

Case (verbatim):
"""

SEV_ORDER = {"blocking": 0, "material": 1, "minor": 2}


def load_cases() -> list[tuple[str, str, dict]]:
    """Every case of the truth set, in the three shapes the auditor is briefed on."""
    truth = json.loads(TRUTH.read_text(encoding="utf-8"))["truth"]
    cases: list[tuple[str, str, dict]] = []
    for case in truth["retrieval_cases"]:
        cases.append((case["case_id"], "retrieval", case))
    for case in truth["negatives"]:
        cases.append((case["case_id"], "negative", case))
    for probe in truth["structure_probes"]:
        cases.append((probe["probe_id"], "probe", probe))
    return cases


def prompt_for(kind: str, case: dict) -> str:
    body = {"retrieval": RETRIEVAL, "negative": NEGATIVE, "probe": PROBE}[kind]
    return (
        COMMON + body + "\n```json\n"
        + json.dumps(case, ensure_ascii=False, indent=2)
        + "\n```\n"
    )


def run_one(case_id: str, kind: str, case: dict, dry: bool) -> tuple[str, str, float]:
    """One case, one read-only process. A verdict already on disk is kept, not re-asked."""
    for directory in (PROMPTS, OUT, LOGS):
        directory.mkdir(parents=True, exist_ok=True)
    prompt = prompt_for(kind, case)
    (PROMPTS / f"{case_id}.md").write_text(prompt, encoding="utf-8")
    out = OUT / f"{case_id}.json"
    log = LOGS / f"{case_id}.log"
    if dry:
        return case_id, "dry", 0.0
    if out.exists() and out.stat().st_size > 0:
        return case_id, "cached", 0.0
    cmd = [
        "codex", "exec",
        "--sandbox", "read-only",
        "--skip-git-repo-check",
        "-C", str(OPC),
        "--output-schema", str(SCHEMA),
        "-o", str(out),
        prompt,
    ]
    started = time.time()
    with open(log, "w", encoding="utf-8") as handle, open(os.devnull) as devnull:
        proc = subprocess.run(cmd, stdin=devnull, stdout=handle, stderr=subprocess.STDOUT)
    elapsed = time.time() - started
    ok = proc.returncode == 0 and out.exists() and out.stat().st_size > 0
    return case_id, "ok" if ok else f"rc={proc.returncode}", elapsed


def aggregate() -> str:
    """The verdicts on disk, counted and then listed in full — the triage's working page."""
    rows: list[dict] = []
    for path in sorted(OUT.glob("*.json")):
        try:
            rows.append(json.loads(path.read_text(encoding="utf-8")))
        except json.JSONDecodeError as error:
            # A verdict that will not parse is reported as a case needing a decision rather
            # than dropped: a silently missing case is the one failure this page cannot have.
            rows.append(
                {
                    "case_id": path.stem,
                    "verdict": "PARSE_ERROR",
                    "issues": [],
                    "notes": str(error),
                }
            )
    verdicts = Counter(row["verdict"] for row in rows)
    issues = [issue for row in rows for issue in row.get("issues", [])]
    by_severity = Counter(issue["severity"] for issue in issues)
    by_kind = Counter((issue["severity"], issue["kind"]) for issue in issues)

    lines = ["# Truth-set rigor audit — aggregate", ""]
    lines.append(f"cases audited: {len(rows)}")
    lines.append(
        "verdicts: " + ", ".join(f"{name} {n}" for name, n in sorted(verdicts.items()))
    )
    lines.append(
        "issues by severity: "
        + ", ".join(
            f"{name} {n}"
            for name, n in sorted(
                by_severity.items(), key=lambda kv: SEV_ORDER.get(kv[0], 9)
            )
        )
    )
    lines += ["", "| severity | kind | n |", "|---|---|---|"]
    for (severity, kind), n in sorted(
        by_kind.items(), key=lambda kv: (SEV_ORDER.get(kv[0][0], 9), -kv[1])
    ):
        lines.append(f"| {severity} | {kind} | {n} |")
    lines += ["", "## Cases needing a decision (fix / unsure), most severe first", ""]
    flagged = [row for row in rows if row["verdict"] in ("fix", "unsure", "PARSE_ERROR")]
    flagged.sort(
        key=lambda row: min(
            (SEV_ORDER.get(issue["severity"], 9) for issue in row.get("issues", [])),
            default=9,
        )
    )
    for row in flagged:
        lines.append(f"### {row['case_id']} — {row['verdict']}")
        for issue in row.get("issues", []):
            lines.append(
                f"- **{issue['severity']} / {issue['kind']}** "
                f"({issue['facet_id']}): {issue['detail']}"
            )
            for evidence in issue.get("corpus_evidence", []):
                lines.append(f"  - `{evidence['file']}`: “{evidence['quote']}”")
            if issue.get("proposed_change"):
                lines.append(f"  - proposed: {issue['proposed_change']}")
        if row.get("notes"):
            lines.append(f"- notes: {row['notes']}")
        lines.append("")
    lines += ["## Sound cases with minor notes", ""]
    for row in rows:
        if row["verdict"] == "sound" and row.get("issues"):
            lines.append(f"### {row['case_id']}")
            for issue in row["issues"]:
                lines.append(
                    f"- {issue['severity']} / {issue['kind']} "
                    f"({issue['facet_id']}): {issue['detail']}"
                )
                if issue.get("proposed_change"):
                    lines.append(f"  - proposed: {issue['proposed_change']}")
            lines.append("")
    lines += ["## Sound, no issues", ""]
    lines.append(
        ", ".join(
            row["case_id"]
            for row in rows
            if row["verdict"] == "sound" and not row.get("issues")
        )
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default="", help="comma-separated case ids")
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true", help="write prompts, ask nothing")
    parser.add_argument(
        "--aggregate",
        action="store_true",
        help="skip the audit and render the verdicts already on disk into summary.md",
    )
    args = parser.parse_args(argv)

    if args.aggregate:
        WORK.mkdir(parents=True, exist_ok=True)
        SUMMARY.write_text(aggregate(), encoding="utf-8")
        print(f"OK: {SUMMARY}")
        return 0

    cases = load_cases()
    if args.only:
        keep = {name.strip() for name in args.only.split(",") if name.strip()}
        cases = [case for case in cases if case[0] in keep]
    print(f"{len(cases)} cases, {args.workers} workers", flush=True)
    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(run_one, case_id, kind, case, args.dry_run)
            for case_id, kind, case in cases
        ]
        for future in as_completed(futures):
            case_id, status, elapsed = future.result()
            if status not in ("ok", "cached", "dry"):
                failures += 1
            print(f"{case_id:16s} {status:8s} {elapsed:6.0f}s", flush=True)
    print(f"done, {failures} failures", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
