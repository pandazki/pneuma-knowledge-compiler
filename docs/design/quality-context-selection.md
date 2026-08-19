# Quality context selection

**English** | [简体中文](quality-context-selection.zh-CN.md)

Status: accepted implementation contract.

## 1. Objective

Fast recall currently turns each independently ranked evidence face into a fixed head. That
is the lowest-latency path, but a question can require a small join across canonical claims,
dense episode descriptions, verbatim source windows, and occasionally one whole canonical
document. The framework needs an opt-in quality path that lets the recall model compose that
evidence before the answer call, without creating another authority or hiding its serial
latency.

This is a general knowledge-base capability. It must not contain dataset, category, topic,
question-pattern, or scorer-specific behavior.

## 2. Public contract

Fast recall gains two independent request/deployment choices:

- `evidence_strategy`: `ranked` or `select`. `ranked` is the existing fixed-head path and
  remains the default. `select` adds one structured recall-model call over all evidence
  faces and the canonical glance.
- `answer_format`: `text` or `structured`. `text` is the existing free-text answer and
  remains the default. `structured` asks for an answer kind, answer-only text, and source
  markers in separate fields. The public result exposes both `answer_text` (semantic answer
  only) and the backward-compatible cited `answer` used by interactive product surfaces.

Per-request values override deployment settings. The fields are valid only for `mode=fast`;
`rag` and `deep` reject non-null values rather than pretending to honor them.

Deployment settings:

- `PNEUMA_KNOWLEDGE_RECALL_EVIDENCE_STRATEGY`
- `PNEUMA_KNOWLEDGE_RECALL_ANSWER_FORMAT`
- `PNEUMA_KNOWLEDGE_RECALL_SELECTION_REASONING_EFFORT` (empty means provider default)

The existing candidate and final caps remain the only evidence-budget knobs. A deployment
that wants the measured quality shape uses 80 claim candidates, 60 source candidates, and
final caps of 16 claims, 10 episode summaries, and 10 verbatim windows. Those values describe
an operating profile, not a hidden benchmark rule.

## 3. Selection behavior

`select` runs after broad retrieval and before source assembly:

1. The selector sees numbered claim, episode-summary, and raw-window candidates, plus the
   canonical glance when one exists. It receives the question last.
2. Its schema contains only candidate indexes and known document paths. It never answers.
3. Unknown paths, out-of-range indexes, duplicates, and over-cap values are discarded
   mechanically.
4. A deterministic safety head is unioned before the final cap: at most 8 claims, 4 episode
   summaries, and 4 raw windows from retrieval order. Selection can improve composition but
   cannot erase the strongest ranked evidence.
5. Empty model selections fall back to their safety heads. Timeout, provider, or schema
   failure falls back to the ordinary ranked heads and records `evidence_selection_degraded`.
6. Selected claim citations and episode spans are followed back to L0, deduplicated against
   independently retrieved windows, and admitted under bounded provenance-expansion caps.
   Derived text remains labelled; L0 bytes remain authoritative.
7. Original media is fetched only from the selected verbatim windows and only when the
   caller requested that modality. Selection never makes media unconditional.

The selector operation is traced as `recall.fast.evidence_select`; its usage is included in
the returned aggregate token usage. Candidate counts, model-selected counts, final counts,
strategy and degraded reason are response telemetry and contain no source text. Model-selected
counts are reported before deterministic safety heads and provenance rollback, so an operator
can measure whether the serial model step actually contributes evidence.

## 4. Structured answer behavior

The structured schema contains:

- `answer_kind`: `fact`, `list`, `time`, `duration`, `yes_no`, `inference`, or `no_record`;
- `answer`: user-visible answer text obeying the requested answer style, with no citation
  markup or process commentary;
- `citations`: complete `[cite: sNN ¶a-b]` markers copied from the presented evidence.

Only citation markers whose handle and exact block span occurred in the aliased evidence are
admitted. Unknown or widened references are dropped mechanically. `answer_text` is the clean
answer body; valid markers are appended only to `answer` in their returned order, preserving
the existing API/UI citation contract. Text-mode and structured-fallback results derive
`answer_text` with the shared citation parser, never an ad-hoc regular expression. A provider
or schema failure falls back to the existing text call and records `answer_format_degraded`;
it never silently masquerades as structured output.

Callers replaying a historical question must provide the question's `as_of` explicitly. The
API already accepts it; the scaffold CLI exposes `--as-of`. Omitting it intentionally means
the current wall-clock instant, which is correct for a live question but not for a replay.

Both structured and text SystemMessages remain byte-stable. Question, `as_of`, snapshot and
evidence stay in the HumanMessage.

## 5. Compatibility and failure contract

- `ranked + text` is the default and must remain byte-for-byte compatible.
- No new middleware or authority is introduced; selection is ephemeral query state.
- Every selected claim/summary/window keeps `source_id + block span` provenance and tenant
  filtering remains inside adapters.
- An additive selector failure cannot fail the answer. Its degradation is observable.
- A source lookup required for selected provenance is not silently swallowed; L0 absence is
  an invariant failure and follows the existing request error path.
- The extra selector is serial and must be reported separately from answer latency/cost.

## 6. Acceptance examples

1. With defaults, the answer prompt and output are identical to the pre-change path.
2. Given candidates where the relevant claim, episode and raw span are not all in their
   fixed heads, a valid structured selection admits them, unions the safety head, and never
   exceeds the configured final caps.
3. Invalid selector indexes and paths never reach storage or the answer prompt.
4. Selector timeout returns a ranked answer with `evidence_selection_degraded="timeout"`.
5. Structured citations can only name exact spans presented to the answer model.
6. A caption-only call reads no original image bytes; a caller-requested selected image still
   performs the existing digest-verified L0 media round trip.
7. Langfuse receives separate selector and answer observations with one shared trace context.
8. `answer_text` contains no admitted citation markup while `answer` retains the same cited
   rendering and both refer to the same citation ledger.
9. A historical CLI ask forwards its explicit `--as-of`; a live ask without it uses current
   UTC time.

## 7. Operating guidance

`select` is an opt-in serial step, not a generic quality synonym. Start with `ranked`; enable
`select` only when measurements on the deployment's own acceptance set show that broad
candidates contain the needed evidence but the ranked final context misses a cross-face join.
Compare model-selected counts with final counts: when safety heads and provenance rollback
supply most evidence, the selector may add cost and latency without earning its place. Quality,
latency and cost are separate acceptance axes and require a same-harness comparison.
