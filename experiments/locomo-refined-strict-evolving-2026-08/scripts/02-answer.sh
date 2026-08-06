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
# ANSWERING DOCTRINE — frozen here, general only, never per-question/topic/category:
#   1. answer directly — the exact value asked for, no restated question, no preamble;
#   2. a well-founded inference beats an abstention; only a genuinely unfounded question
#      gets "no relevant record";
#   3. granularity matches the question — a day for a day, a month for a month;
#   4. keep a qualifier only when it is decisive (a negation, an approximation, a boundary,
#      a causal link).
# These are not re-implemented as bespoke prompt text: they are exactly what the framework's
# `concise` answer-style preset already states (recall.style.concise + recall.close.
# answer_honestly), so the doctrine is applied by SELECTING that preset — one of the three
# the framework ships — and nothing about the framework's own wording is rewritten.
#
# STYLE CHOICE: `concise`. The judge's own examples are bare values ("7 May 2023", "2022")
# and its list rule marks unsupported extra items WRONG, so the shortest fully-answering
# phrase is the shape the grader expects. (Read from the official README and src/llm_judge.py
# only after the contracts and 01-build.sh were frozen.)
set -uo pipefail

ROOT=/data/qiwei/lcr-final
POOL=5
STYLE=concise

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
