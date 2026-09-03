# The truth-set rigor audit, as it came

Before truth v6, each of the 84 cases in `eval/opc-truth.json` was handed to its own read-only
process (`eval/audit_truth.py`, one `codex exec` per case) whose only admissible evidence was
this example's own inputs — `my-data/` and the owner statement — never the compiled library.
`verdicts/<case_id>.json` is what each one returned, schema-bound; `summary.md` aggregates them.
Nothing here scores anything, and nothing here is authority: the audit is an input.

What the truth set actually changed is the maintainer's triage of these findings — accept,
reject, or modify, item by item — and that lives in the truth file's `ruler_changes` and
`supersedes`, not in these verdicts. Several findings were read and rejected.
