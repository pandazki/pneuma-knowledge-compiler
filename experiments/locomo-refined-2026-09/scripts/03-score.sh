#!/usr/bin/env bash
# Official scoring followed by post-score whitelist sanitization.
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
EXPECTED=1382
PREDICTIONS="$ROOT/data/outputs/predictions.jsonl"
SCORED="$ROOT/data/outputs/predictions_scored.jsonl"
SUMMARY="$ROOT/data/outputs/predictions_scored_summary.json"

log() {
  printf '%s [03-score] %s\n' "$(date -u +%FT%TZ)" "$*"
}

(cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 1) || exit 1
(cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 2) || exit 1

mkdir -p "$ROOT/data/outputs" "$ROOT/results" "$ROOT/build-record/logs/score"
printf '%s\n' "$$" > "$ROOT/build-record/03-score.pid"
python3 "$ROOT/scripts/setup_evaluator.py" || exit 1
python3 "$ROOT/scripts/assemble_predictions.py" \
  --projection "$ROOT/outputs/questions-projected.jsonl" \
  --answers-dir "$ROOT/outputs/answers" \
  --output "$PREDICTIONS" \
  --evidence-copy "$ROOT/results/predictions.jsonl" \
  --expected "$EXPECTED" || exit 1

scored_count=0
if [ -f "$SCORED" ] && [ -f "$SUMMARY" ]; then
  scored_count=$(wc -l < "$SCORED" | tr -d ' ')
fi
if [ "${1:-}" = "--force" ] || [ "$scored_count" != "$EXPECTED" ]; then
  log "PHASE B SCORE START official=qwen/qwen3-14b concurrency=64"
  # Actual command inside run_official_score.py:
  # ./scripts/run_eval.sh --metrics llm f1 bleu --llm-judge refined --concurrency 64
  python3 "$ROOT/scripts/run_official_score.py" --predictions "$PREDICTIONS" || exit $?
else
  log "official score already complete records=${scored_count}; reusing"
fi

python3 "$ROOT/scripts/sanitize_results.py" \
  --scored "$SCORED" \
  --official-summary "$SUMMARY" \
  --burned "$ROOT/burned-questions.json" \
  --output-dir "$ROOT/results" \
  --expected "$EXPECTED" || exit 1
log "PHASE B SCORE COMPLETE sanitized_records=${EXPECTED}"
