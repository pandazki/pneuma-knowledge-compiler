#!/usr/bin/env bash
# 02-answer.sh — LoCoMo-Refined full run, answering phase.
#
# Each question is routed by `conversation_idx` to that conversation's own project
# (idx 0 -> app-01 … idx 9 -> app-10) and answered by that project's own library through
# `./app.py ask` — the framework's traced command surface, so every call lands in Langfuse.
# Projects run in parallel (POOL slots); within a project the questions are serial.
#
# PROJECTION. Only `qa_id`, `conversation_idx` and `question` are ever read out of
# questions.jsonl (enforced in answer_runner.py). `answer`, `evidence`, `evidence_messages`
# and `category` are never loaded — no gold reaches the model, and no question text reaches
# the experimenter.
#
# [REDACTED by the orchestrator] The frozen answering doctrine and the style-choice
# rationale stood here. Both derived from the previous run's exam phase (the official
# README and judge prompt, read only after FREEZE#1) and quoted two answer values the
# README burns. This run must reach its own doctrine and style in its own exam phase.
set -uo pipefail

ROOT=/data/qiwei/lcr-final
POOL=5
STYLE=__CHOOSE_IN_YOUR_EXAM_PHASE__

TAG=${TAG:-main}
log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$TAG" "$*"; }

if [ "${1:-}" = "--one" ]; then
  n=$2
  idx=$((10#$n - 1))
  mkdir -p "$ROOT/logs" "$ROOT/outputs/answers"
  TAG="app-$n"
  {
    log "START answering conversation idx=$idx style=$STYLE"
    # the stack has to be up for the library to answer
    ( cd "$ROOT/app-$n" && ./app.py up ) || log "WARN stack start reported a problem"
    python3 "$ROOT/answer_runner.py" "$n" "$idx" "$STYLE"
    rc=$?
    log "FINISH answering conversation idx=$idx rc=$rc"
    exit $rc
  } >> "$ROOT/logs/answer-app-$n.log" 2>&1
fi

mkdir -p "$ROOT/logs" "$ROOT/outputs/answers"
log "02-answer.sh start — pool=$POOL style=$STYLE"
printf '%s\n' 01 02 03 04 05 06 07 08 09 10 \
  | xargs -P "$POOL" -I{} "$ROOT/02-answer.sh" --one {}
rc=$?

total=$(cat "$ROOT"/outputs/answers/app-*.jsonl 2>/dev/null | wc -l)
log "02-answer.sh end rc=$rc — answers written: $total"
exit $rc
