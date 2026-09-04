#!/usr/bin/env bash
# Resumable LoCoMo-Refined build: two isolated conversations at a time, sessions serial.
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
export UV_PROJECT_ENVIRONMENT="$ROOT/.runtime/framework-venv"
POOL=2
EVOLVE_MIN_NEW_CLAIMS=80
EVOLVE_MIN_SESSIONS=6
MAX_ATTEMPTS=5
BACKOFF_START=15
TOTAL_SESSIONS=272
HALF_SESSIONS=136

TAG=${TAG:-main}
APP=""
STATE=""
APP_NUMBER=""
ACTIVE_COMPILE_LOG=""

log() {
  printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$TAG" "$*"
}

assert_scope() {
  local expected count
  expected="PNEUMA_APP_COMPOSE_PROJECT=pneuma-lcr2609-${APP_NUMBER}-"
  count=$(grep -c "^${expected}" "$APP/.env" 2>/dev/null || true)
  if [ "$count" != "1" ]; then
    log "FATAL project scope guard failed for app-${APP_NUMBER}"
    return 1
  fi
  count=$(grep -c '^PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER=openai$' "$APP/.env" 2>/dev/null || true)
  if [ "$count" != "1" ]; then
    log "FATAL provider guard failed for app-${APP_NUMBER}"
    return 1
  fi
  count=$(grep -c 'LCR2609 byte-exact blank-continuation compatibility' "$APP/app.py" 2>/dev/null || true)
  if [ "$count" != "1" ]; then
    log "FATAL generated parser compatibility guard failed for app-${APP_NUMBER}"
    return 1
  fi
}

attempt_run() {
  local label=$1
  shift
  local attempt=1 delay=$BACKOFF_START rc=0
  while :; do
    "$@"
    rc=$?
    if [ "$rc" -eq 0 ]; then
      return 0
    fi
    if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
      log "GIVE-UP ${label} rc=${rc} after ${attempt} attempts"
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

app_ingest() {
  local relative=$1
  assert_scope && (cd "$APP" && ./app.py ingest "$relative")
}

app_compile() {
  assert_scope || return 1
  (cd "$APP" && ./app.py compile) 2>&1 | tee -a "$ACTIVE_COMPILE_LOG"
}

app_status_line() {
  assert_scope || return 1
  (cd "$APP" && ./app.py status 2>/dev/null | grep -m1 '^user=')
}

probe() {
  local key=$1 line
  line=$(app_status_line) || return 1
  printf '%s\n' "$line" | grep -o "${key}=[0-9]*" | head -1 | cut -d= -f2
}

app_evolve() {
  local rc
  assert_scope || return 1
  (cd "$APP" && ./app.py evolve step --policy adopt-clean)
  rc=$?
  if [ "$rc" -eq 0 ] || [ "$rc" -eq 2 ]; then
    return 0
  fi
  return "$rc"
}

drain_to_zero() {
  local round pending
  for round in 1 2 3 4; do
    attempt_run "compile" app_compile || return 1
    pending=$(probe 'jobs pending') || return 1
    if [ "$pending" = "0" ]; then
      return 0
    fi
    log "queue not empty after compile pending=${pending} drain_round=${round}"
  done
  log "ERROR queue still not empty after four drain rounds"
  return 1
}

maybe_evolve() {
  local claims=$1 session=$2 force=$3
  local last_claims=0 last_session=0 delta_claims delta_sessions
  if [ -f "$STATE/evolve.state" ]; then
    read -r last_claims last_session < "$STATE/evolve.state"
  fi
  delta_claims=$((claims - last_claims))
  delta_sessions=$((session - last_session))
  if [ "$force" = "1" ] || {
    [ "$delta_claims" -ge "$EVOLVE_MIN_NEW_CLAIMS" ] &&
      [ "$delta_sessions" -ge "$EVOLVE_MIN_SESSIONS" ]
  }; then
    log "EVOLVE session=${session} new_claims=${delta_claims} sessions_since=${delta_sessions} force=${force}"
    attempt_run "evolve" app_evolve || return 1
    printf '%s %s\n' "$claims" "$session" > "$STATE/evolve.state"
    printf '%s,%s,%s,%s,%s\n' "$(date -u +%FT%TZ)" "$session" "$delta_claims" "$delta_sessions" "$force" \
      >> "$STATE/evolve-history.csv"
    ACTIVE_COMPILE_LOG="$ROOT/build-record/logs/compile/app-${APP_NUMBER}/evolve-${session}-${force}.log"
    drain_to_zero || return 1
  fi
}

completed_session_count() {
  find "$ROOT/build-record/state" -type f -name 'session-*.done' 2>/dev/null | wc -l | tr -d ' '
}

budget_gate() {
  local completed=$1 budget_out rc=0
  if [ "$completed" -ge "$HALF_SESSIONS" ] && [ ! -f "$ROOT/build-record/state/budget-half.done" ]; then
    if mkdir "$ROOT/build-record/state/budget-half.lock" 2>/dev/null; then
      budget_out="$ROOT/build-record/cost-half.json"
      python3 "$ROOT/scripts/budget.py" \
        --compile-root "$ROOT/build-record/logs/compile" \
        --completed "$completed" --total "$TOTAL_SESSIONS" --out "$budget_out" || rc=$?
      if [ "$rc" -eq 0 ]; then
        touch "$ROOT/build-record/state/budget-half.done"
      fi
      rmdir "$ROOT/build-record/state/budget-half.lock" 2>/dev/null || true
      [ "$rc" -eq 0 ] || return "$rc"
    fi
  fi
  python3 "$ROOT/scripts/budget.py" \
    --compile-root "$ROOT/build-record/logs/compile" \
    --completed "$completed" --total "$TOTAL_SESSIONS" \
    --out "$ROOT/build-record/cost-current.json" --enforce-hard
  rc=$?
  if [ "$rc" -eq 60 ]; then
    touch "$ROOT/build-record/state/HARD-BUDGET-STOP"
    log "HARD budget ceiling reached; no new session will start"
  fi
  return "$rc"
}

cleanup_one() {
  if [ -n "$APP" ] && [ -n "$APP_NUMBER" ]; then
    app_down || log "WARN scoped teardown failed"
  fi
}

build_one() {
  local number=$1 idx total session padded started ended claims documents sources completed
  APP_NUMBER=$number
  APP="$ROOT/app-${number}"
  STATE="$ROOT/build-record/state/app-${number}"
  TAG="app-${number}"
  mkdir -p "$STATE" "$ROOT/build-record/logs/compile/app-${number}"
  if [ ! -f "$STATE/evolve-history.csv" ]; then
    printf 'utc,session,new_claims,sessions_since,forced\n' > "$STATE/evolve-history.csv"
  fi
  if [ ! -f "$STATE/progress.csv" ]; then
    printf 'utc,session,claims,documents,sources,seconds\n' > "$STATE/progress.csv"
  fi
  if [ -f "$STATE/conversation.done" ]; then
    log "SKIP conversation already complete"
    return 0
  fi
  if [ -f "$ROOT/build-record/state/HARD-BUDGET-STOP" ]; then
    log "STOP hard budget marker exists"
    return 60
  fi
  assert_scope || return 1
  idx=$((10#$number - 1))
  total=$(python3 "$ROOT/scripts/to_material.py" count "$idx") || return 1
  log "START conversation idx=${idx} sessions=${total}"
  attempt_run "up" app_up || return 1
  trap cleanup_one EXIT INT TERM

  for session in $(seq 1 "$total"); do
    padded=$(printf '%03d' "$session")
    if [ -f "$STATE/session-${padded}.done" ]; then
      continue
    fi
    if [ -f "$ROOT/build-record/state/HARD-BUDGET-STOP" ]; then
      log "STOP before session ${session}: hard budget marker exists"
      return 60
    fi
    started=$(date +%s)
    log "session ${session}/${total}: convert"
    attempt_run "emit-${padded}" python3 "$ROOT/scripts/to_material.py" emit \
      "$idx" "$session" "$APP/material/s${padded}" --parser-app "$APP/app.py" || return 1
    log "session ${session}/${total}: ingest"
    attempt_run "ingest-${padded}" app_ingest "material/s${padded}" || return 1
    log "session ${session}/${total}: compile"
    ACTIVE_COMPILE_LOG="$ROOT/build-record/logs/compile/app-${number}/session-${padded}.log"
    drain_to_zero || return 1
    claims=$(probe claims) || return 1
    documents=$(probe 'canonical documents') || return 1
    sources=$(probe sources) || return 1
    ended=$(date +%s)
    printf '%s,%s,%s,%s,%s,%s\n' "$(date -u +%FT%TZ)" "$session" "$claims" "$documents" "$sources" "$((ended - started))" \
      >> "$STATE/progress.csv"
    touch "$STATE/session-${padded}.done"
    log "session ${session}/${total}: done seconds=$((ended - started)) claims=${claims} documents=${documents}"
    maybe_evolve "$claims" "$session" 0 || return 1
    completed=$(completed_session_count)
    budget_gate "$completed" || return $?
  done

  if [ ! -f "$STATE/final-evolve.done" ]; then
    claims=$(probe claims) || return 1
    maybe_evolve "$claims" "$total" 1 || return 1
    touch "$STATE/final-evolve.done"
  fi
  log "FINISH conversation idx=${idx} claims=$(probe claims) documents=$(probe 'canonical documents')"
  touch "$STATE/conversation.done"
  cleanup_one
  trap - EXIT INT TERM
}

run_child() {
  local number=$1 log_path rc=0
  mkdir -p "$ROOT/build-record/logs/operations"
  log_path="$ROOT/build-record/logs/operations/app-${number}.log"
  build_one "$number" >> "$log_path" 2>&1 || rc=$?
  printf 'app-%s exited rc=%s\n' "$number" "$rc"
  return "$rc"
}

if [ "${1:-}" = "--one" ]; then
  run_child "$2"
  exit $?
fi

(cd "$ROOT" && python3 scripts/freeze_guard.py verify --phase 1) || exit 1
mkdir -p "$ROOT/build-record/logs" "$ROOT/build-record/state"
printf '%s\n' "$$" > "$ROOT/build-record/01-build.pid"
log "PHASE B BUILD START pool=${POOL} evolve_claims=${EVOLVE_MIN_NEW_CLAIMS} evolve_sessions=${EVOLVE_MIN_SESSIONS}"
printf '%s\n' 01 02 03 04 05 06 07 08 09 10 \
  | xargs -P "$POOL" -I{} "$ROOT/scripts/01-build.sh" --one {}
rc=$?
done_count=$(find "$ROOT/build-record/state" -type f -name conversation.done 2>/dev/null | wc -l | tr -d ' ')
log "PHASE B BUILD COMPLETE rc=${rc} conversations=${done_count}/10 sessions=$(completed_session_count)/${TOTAL_SESSIONS}"
exit "$rc"
