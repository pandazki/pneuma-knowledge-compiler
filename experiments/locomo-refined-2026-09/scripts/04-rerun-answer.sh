#!/usr/bin/env bash
# Maintainer-ordered post-protocol answer line: ten projects, 32 asks in flight.
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export UV_PROJECT_ENVIRONMENT="$ROOT/.runtime/framework-venv"
LINE_ID=2026-09-04-capability-guidance
ANSWERS_ROOT="$ROOT/outputs/answers-2026-09-04"
PROJECTION="$ROOT/outputs/questions-projected.jsonl"
STATE="$ROOT/build-record/$LINE_ID"
TEMPLATE="$ROOT/repo/scaffold/templates/app.py"
FRAMEWORK_HEAD=212a8fe46da3a8e6f29d36ed82dd7cb38b39736a
TEMPLATE_SHA256=67f43f2ef0d71dba9d6499071b134b5b44ad60449a4ad6d2c938cb27fd5e1f92
PROJECTION_SHA256=42bcc322da30d8ca9cf9862c9b9be8471c023f74ab6fb902b55a1d995c0b6410
WORKERS_01=4
WORKERS_02=4
WORKERS_03=3
WORKERS_04=3
WORKERS_05=3
WORKERS_06=3
WORKERS_07=3
WORKERS_08=3
WORKERS_09=3
WORKERS_10=3

log() {
  printf '%s [04-rerun-answer] %s\n' "$(date -u +%FT%TZ)" "$*"
}

workers_for() {
  case "$1" in
    01) printf '%s\n' "$WORKERS_01" ;;
    02) printf '%s\n' "$WORKERS_02" ;;
    03) printf '%s\n' "$WORKERS_03" ;;
    04) printf '%s\n' "$WORKERS_04" ;;
    05) printf '%s\n' "$WORKERS_05" ;;
    06) printf '%s\n' "$WORKERS_06" ;;
    07) printf '%s\n' "$WORKERS_07" ;;
    08) printf '%s\n' "$WORKERS_08" ;;
    09) printf '%s\n' "$WORKERS_09" ;;
    10) printf '%s\n' "$WORKERS_10" ;;
    *) return 1 ;;
  esac
}

assert_scope() {
  local number=$1 app="$ROOT/app-$1" count actual
  count=$(grep -c "^PNEUMA_APP_COMPOSE_PROJECT=pneuma-lcr2609-${number}-" "$app/.env" 2>/dev/null || true)
  [ "$count" = "1" ] || return 1
  count=$(grep -c '^PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai$' "$app/.env" 2>/dev/null || true)
  [ "$count" = "1" ] || return 1
  actual=$(shasum -a 256 "$app/app.py" | awk '{print $1}')
  [ "$actual" = "$TEMPLATE_SHA256" ] || return 1
  cmp -s "$TEMPLATE" "$app/app.py"
}

verify_line() {
  local actual number
  python3 "$ROOT/scripts/verify_original_run.py" || return 1
  (cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 1) || return 1
  (cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 2) || return 1
  [ "$(git -C "$ROOT/repo" rev-parse HEAD)" = "$FRAMEWORK_HEAD" ] || return 1
  [ -z "$(git -C "$ROOT/repo" status --porcelain)" ] || return 1
  actual=$(shasum -a 256 "$PROJECTION" | awk '{print $1}')
  [ "$actual" = "$PROJECTION_SHA256" ] || return 1
  for number in 01 02 03 04 05 06 07 08 09 10; do
    assert_scope "$number" || return 1
  done
}

initialize_answers_root() {
  local marker="$ANSWERS_ROOT/.line-owned"
  mkdir -p "$ANSWERS_ROOT"
  if [ ! -f "$marker" ]; then
    if find "$ANSWERS_ROOT" -mindepth 1 -maxdepth 1 -print -quit | grep -q .; then
      log "FATAL fresh answer directory is non-empty and has no ownership marker"
      return 1
    fi
    printf '%s|%s|%s|32\n' "$LINE_ID" "$FRAMEWORK_HEAD" "$PROJECTION_SHA256" > "$marker"
  fi
  [ "$(cat "$marker")" = "$LINE_ID|$FRAMEWORK_HEAD|$PROJECTION_SHA256|32" ]
}

up_one() {
  local number=$1 app="$ROOT/app-$1"
  assert_scope "$number" || return 1
  (cd "$app" && ./app.py up)
}

answer_one() {
  local number=$1 idx workers log_path
  idx=$((10#$number - 1))
  workers=$(workers_for "$number") || return 1
  log_path="$STATE/logs/answers/app-${number}.log"
  python3 "$ROOT/scripts/rerun_answer_runner.py" \
    "$number" "$idx" "$PROJECTION" "$ANSWERS_ROOT" --workers "$workers" \
    > "$log_path" 2>&1
}

if [ "${1:-}" = "--up-one" ]; then
  up_one "$2"
  exit $?
fi

verify_line || { log "FATAL follow-up invariant check failed"; exit 1; }
initialize_answers_root || exit 1
mkdir -p "$STATE/logs/answers" "$STATE/logs/up"
printf '%s\n' "$$" > "$STATE/04-rerun-answer.pid"
log "RERUN ANSWER START projects=10 total_in_flight=32 output=answers-2026-09-04"

printf '%s\n' 01 02 03 04 05 06 07 08 09 10 \
  | xargs -P 10 -I{} sh -c '"$1" --up-one "$2" > "$3/up-app-$2.log" 2>&1' _ \
      "$ROOT/scripts/04-rerun-answer.sh" {} "$STATE/logs/up"
up_rc=$?
if [ "$up_rc" -ne 0 ]; then
  log "FATAL stack startup failed rc=$up_rc"
  exit "$up_rc"
fi
log "all ten scoped stacks are up"

run_all() {
  local number pid rc=0
  local pids=""
  for number in 01 02 03 04 05 06 07 08 09 10; do
    answer_one "$number" &
    pid=$!
    pids="$pids $pid"
  done
  for pid in $pids; do
    wait "$pid" || rc=1
  done
  return "$rc"
}

run_all &
pool_pid=$!
soft_disclosed=0
while kill -0 "$pool_pid" 2>/dev/null; do
  python3 "$ROOT/scripts/rerun_cost.py" \
    --answers-root "$ANSWERS_ROOT" --expected 1382 --out "$STATE/cost-current.json" \
    > "$STATE/cost-current.stdout" || { log "FATAL cost accounting failed"; exit 1; }
  completed=$(find "$ANSWERS_ROOT/records" -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
  projected_soft=$(python3 -c 'import json,sys; print(int(json.load(open(sys.argv[1]))["soft_ceiling_projected"]))' "$STATE/cost-current.json")
  if [ "$projected_soft" = "1" ] && [ "$soft_disclosed" = "0" ]; then
    log "SOFT CEILING projected at completed=$completed; continuing because this is a soft ceiling"
    touch "$STATE/SOFT-CEILING-DISCLOSED"
    soft_disclosed=1
  fi
  log "progress answers=${completed}/1382"
  sleep 30
done
wait "$pool_pid"
answer_rc=$?
python3 "$ROOT/scripts/rerun_cost.py" \
  --answers-root "$ANSWERS_ROOT" --expected 1382 --out "$STATE/cost-final.json" \
  > "$STATE/cost-final.stdout" || exit 1
completed=$(find "$ANSWERS_ROOT/records" -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
app_files=$(find "$ANSWERS_ROOT" -maxdepth 1 -type f -name 'app-*.jsonl' | wc -l | tr -d ' ')
if [ "$answer_rc" -ne 0 ] || [ "$completed" != "1382" ] || [ "$app_files" != "10" ]; then
  log "RERUN ANSWER FAILED rc=$answer_rc answers=${completed}/1382 apps=${app_files}/10"
  exit 1
fi
verify_line || { log "FATAL post-answer invariant check failed"; exit 1; }
touch "$STATE/answer.done"
log "RERUN ANSWER COMPLETE answers=1382/1382 apps=10/10"
