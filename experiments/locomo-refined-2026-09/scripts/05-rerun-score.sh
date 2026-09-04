#!/usr/bin/env bash
# Score the follow-up line with the frozen official launcher into isolated paths.
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
LINE_ID=2026-09-04-capability-guidance
ANSWERS_ROOT="$ROOT/outputs/answers-2026-09-04"
RAW_DIR="$ROOT/data/outputs/$LINE_ID"
RESULTS_DIR="$ROOT/results/$LINE_ID"
STATE="$ROOT/build-record/$LINE_ID"
PREDICTIONS="$RAW_DIR/predictions.jsonl"
SCORED="$RAW_DIR/predictions_scored.jsonl"
SUMMARY="$RAW_DIR/predictions_scored_summary.json"
EXPECTED=1382

log() {
  printf '%s [05-rerun-score] %s\n' "$(date -u +%FT%TZ)" "$*"
}

python3 "$ROOT/scripts/verify_original_run.py" || exit 1
(cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 1) || exit 1
(cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 2) || exit 1
[ -f "$STATE/answer.done" ] || { log "FATAL follow-up answers are incomplete"; exit 1; }
mkdir -p "$RAW_DIR" "$RESULTS_DIR" "$STATE"
printf '%s\n' "$$" > "$STATE/05-rerun-score.pid"
python3 "$ROOT/scripts/setup_evaluator.py" || exit 1
python3 "$ROOT/scripts/assemble_predictions.py" \
  --projection "$ROOT/outputs/questions-projected.jsonl" \
  --answers-dir "$ANSWERS_ROOT" \
  --output "$PREDICTIONS" \
  --evidence-copy "$RESULTS_DIR/predictions.jsonl" \
  --expected "$EXPECTED" || exit 1

scored_count=0
if [ -f "$SCORED" ] && [ -f "$SUMMARY" ]; then
  scored_count=$(wc -l < "$SCORED" | tr -d ' ')
fi
if [ "${1:-}" = "--force" ] || [ "$scored_count" != "$EXPECTED" ]; then
  log "RERUN SCORE START official=qwen/qwen3-14b concurrency=64"
  python3 "$ROOT/scripts/run_official_score.py" --predictions "$PREDICTIONS" || exit $?
else
  log "follow-up official score already complete records=${scored_count}; reusing"
fi

python3 "$ROOT/scripts/sanitize_results.py" \
  --scored "$SCORED" \
  --official-summary "$SUMMARY" \
  --burned "$ROOT/burned-questions.json" \
  --output-dir "$RESULTS_DIR" \
  --expected "$EXPECTED" || exit 1
python3 "$ROOT/scripts/verify_original_run.py" || exit 1
touch "$STATE/score.done"
log "RERUN SCORE COMPLETE sanitized_records=${EXPECTED}"
