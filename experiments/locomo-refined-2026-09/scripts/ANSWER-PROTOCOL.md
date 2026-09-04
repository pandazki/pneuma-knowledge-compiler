# Frozen answer and scoring protocol

`TASKBOOK.md` remains authoritative. This protocol was written only after FREEZE#1 and after
reading the official README, refined judge prompt, evaluator, runtime, summarizer, and blank
submission template.

## Answer doctrine

- Route each projected question to its own conversation library and use the scaffold's silent
  visitor path. The projection contains exactly `qa_id`, `conversation_idx`, and `question`.
- Ask the original question unchanged. Use `--style concise --evidence-strategy select
  --answer-format structured`; do not enable original-image retrieval.
- Return the bare requested value or phrase. Match the question's time granularity, preserve
  relative time as relative, cover every distinct requested list item, and add no unsupported
  details. For preference/benefit questions, a supported direct reason is preferable to a broad
  list.
- Store the citation-free semantic answer by mechanically removing only framework `[cite: …]`
  markers from the CLI answer. Missing answer text or token usage is a retryable failure, never a
  successful empty record.

## Resumption and budget

Ten project workers run with a process pool of two; questions are serial within each project.
Each answer is appended and synced as one JSONL record containing only its id, prediction, and
token usage. Valid existing ids resume without another model call. Five bounded attempts use
exponential backoff. Every project stack is prefix-guarded and torn down without deleting
volumes. After each answer, observed compile-plus-answer tokens are checked against the frozen
USD 60 hard ceiling.

## Official scoring and evidence hygiene

Predictions are assembled in official order with exactly `qa_id` and `predicted_answer`. The
shipped scorer is invoked unchanged as:

```text
./scripts/run_eval.sh --metrics llm f1 bleu --llm-judge refined --concurrency 64
```

The official judge is `qwen/qwen3-14b` over OpenRouter. Gold-bearing raw scored output remains
under ignored `data/outputs/` and is never displayed. Only after scoring completes, a whitelist
sanitizer writes evidence-repository results and rejects any occurrence of `question`, `answer`,
`evidence`, `evidence_messages`, or `matched_answer`. It reports both the official score and the
score excluding the two README-burned ids. Its isolated ignored Python environment pins
`openai==1.109.1` and `tenacity==9.1.4`; application commands use a separate ignored framework
environment outside the read-only framework worktree.
