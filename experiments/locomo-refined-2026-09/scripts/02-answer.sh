#!/usr/bin/env bash
# Resumable answer phase over an allowlisted question projection.
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export UV_PROJECT_ENVIRONMENT="$ROOT/.runtime/framework-venv"
POOL=2
MAX_ATTEMPTS=5
BACKOFF_START=15
PROJECTION="$ROOT/outputs/questions-projected.jsonl"
TAG=${TAG:-02-answer}
APP=""
APP_NUMBER=""

log() {
  printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$TAG" "$*"
}

assert_scope() {
  local count
  count=$(grep -c "^PNEUMA_APP_COMPOSE_PROJECT=pneuma-lcr2609-${APP_NUMBER}-" "$APP/.env" 2>/dev/null || true)
  [ "$count" = "1" ] || return 1
  count=$(grep -c '^PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai$' "$APP/.env" 2>/dev/null || true)
  [ "$count" = "1" ] || return 1
  count=$(grep -c 'LCR2609 byte-exact blank-continuation compatibility' "$APP/app.py" 2>/dev/null || true)
  [ "$count" = "1" ] || return 1
}

attempt_run() {
  local label=$1
  shift
  local attempt=1 delay=$BACKOFF_START rc=0
  while :; do
    "$@"
    rc=$?
    [ "$rc" -eq 0 ] && return 0
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
      log "GIVE-UP ${label} rc=${rc} attempts=${attempt}"
      return "$rc"
    fi
    log "RETRY ${label} rc=${rc} attempt=${attempt} backoff=${delay}s"
    sleep "$delay"
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

app_up() {
  assert_scope && (cd "$APP" && ./app.py up)
}

app_down() {
  assert_scope && (cd "$APP" && ./app.py down)
}

cleanup_one() {
  if [ -n "$APP" ] && [ -n "$APP_NUMBER" ]; then
    app_down || log "WARN scoped teardown failed"
  fi
}

answer_one() {
  local number=$1 idx log_path rc=0
  APP_NUMBER=$number
  APP="$ROOT/app-${number}"
  TAG="answer-app-${number}"
  idx=$((10#$number - 1))
  log_path="$ROOT/build-record/logs/answers/app-${number}.log"
  mkdir -p "$ROOT/build-record/logs/answers"
  {
    assert_scope || return 1
    attempt_run up app_up || return 1
    trap cleanup_one EXIT INT TERM
    python3 "$ROOT/scripts/answer_runner.py" "$number" "$idx" "$PROJECTION" \
      --style concise --evidence-strategy select --answer-format structured || rc=$?
    cleanup_one
    trap - EXIT INT TERM
    return "$rc"
  } >> "$log_path" 2>&1
}

(cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 1) || exit 1
(cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 2) || exit 1

completed_sessions=$(find "$ROOT/build-record/state" -type f -name 'session-*.done' 2>/dev/null | wc -l | tr -d ' ')
completed_conversations=$(find "$ROOT/build-record/state" -type f -name conversation.done 2>/dev/null | wc -l | tr -d ' ')
if [ "$completed_sessions" != "272" ] || [ "$completed_conversations" != "10" ]; then
  log "FATAL build incomplete conversations=${completed_conversations}/10 sessions=${completed_sessions}/272"
  exit 1
fi
if [ -f "$ROOT/build-record/state/HARD-BUDGET-STOP" ]; then
  log "FATAL hard budget stop marker exists"
  exit 60
fi

if [ "${1:-}" = "--one" ]; then
  answer_one "$2"
  exit $?
fi

mkdir -p "$ROOT/outputs/answers" "$ROOT/build-record/logs/answers"
printf '%s\n' "$$" > "$ROOT/build-record/02-answer.pid"
python3 "$ROOT/scripts/project_questions.py" \
  "$ROOT/data/data/public/questions.jsonl" "$PROJECTION" --expected 1382 || exit 1
log "PHASE B ANSWER START pool=${POOL} style=concise evidence=select format=structured"
printf '%s\n' 01 02 03 04 05 06 07 08 09 10 \
  | xargs -P "$POOL" -I{} "$ROOT/scripts/02-answer.sh" --one {}
rc=$?
answer_count=$(find "$ROOT/outputs/answers" -type f -name 'app-*.jsonl' -exec wc -l {} + 2>/dev/null | tail -1 | awk '{print $1}')
answer_count=${answer_count:-0}
log "PHASE B ANSWER COMPLETE rc=${rc} answers=${answer_count}/1382"
exit "$rc"
