#!/usr/bin/env bash
# 01-build.sh — LoCoMo-Refined full run, strict / evolving protocol, build phase.
#
# Ten conversations, ten independent projects, ten independent contracts. Conversations run
# in parallel (POOL slots); inside a conversation the sessions are strictly serial and
# strictly in order: convert one session -> ingest it -> drain the queue to zero -> only then
# the next session. Nothing is read ahead; session i is materialised at the moment it is due.
#
# The evolution policy is frozen into this script and is data-driven, never wall-clock:
#   a round fires when, since the previous round, the canonical library has gained at least
#   EVOLVE_MIN_NEW_CLAIMS claims AND at least EVOLVE_MIN_SESSIONS sessions have landed.
#   Rationale: the calibration run measured ~11 claims from one session, so 50 claims is
#   roughly four to five sessions of accrual — enough evidence for a structural proposal to
#   see a genuinely new family, cheap enough not to reorganise on every session. The session
#   floor stops a single information-dense session from firing a round on its own. One final
#   round is forced after a conversation's last session so the finished structure reflects
#   all of the material. Drafts are disposed automatically by `evolve step --policy
#   adopt-clean` — the gate decides; no human judgement enters phase B.
#
# Everything is resumable: a session is marked done only after its queue reached zero, so a
# restart re-runs exactly the unfinished unit (ingest dedupes, and the compile drain re-queues
# historically failed compile jobs by itself). Retryable errors back off inside the script.
set -uo pipefail

ROOT=/data/qiwei/lcr-final
POOL=5
EVOLVE_MIN_NEW_CLAIMS=50
EVOLVE_MIN_SESSIONS=4
MAX_ATTEMPTS=5
BACKOFF_START=20

TAG=${TAG:-main}
log() { printf '%s [%s] %s\n' "$(date -u +%FT%TZ)" "$TAG" "$*"; }

# ---------------------------------------------------------------- retry with backoff
attempt_run() {   # attempt_run <label> <command...>
  local label=$1; shift
  local attempt=1 delay=$BACKOFF_START rc=0
  while :; do
    "$@"; rc=$?
    [ $rc -eq 0 ] && return 0
    if [ $attempt -ge $MAX_ATTEMPTS ]; then
      log "GIVE-UP $label rc=$rc after $attempt attempts"
      return $rc
    fi
    log "RETRY $label rc=$rc attempt=$attempt backoff=${delay}s"
    sleep $delay
    attempt=$((attempt + 1))
    delay=$((delay * 2))
  done
}

# ---------------------------------------------------------------- library probes
status_line() { ( cd "$APP" && ./app.py status 2>/dev/null | grep -m1 '^user=' ); }
probe() {   # probe <key>   e.g. probe claims / probe 'jobs pending'
  status_line | grep -o "$1=[0-9]*" | head -1 | cut -d= -f2
}

drain_to_zero() {
  local round pending
  for round in 1 2 3 4; do
    attempt_run "compile" bash -c "cd '$APP' && ./app.py compile"
    pending=$(probe 'jobs pending')
    if [ "${pending:-x}" = "0" ]; then
      return 0
    fi
    log "queue not empty after compile (pending=${pending:-?}) — draining again (round $round)"
  done
  log "ERROR queue still not empty after 4 drain rounds"
  return 1
}

run_evolve() {
  local rc
  ( cd "$APP" && ./app.py evolve step --policy adopt-clean )
  rc=$?
  # 0 = progress or nothing to do; 2 = a draft was left for review (cannot happen under
  # adopt-clean, but it is not a failure either). Anything else is a real error.
  if [ $rc -ne 0 ] && [ $rc -ne 2 ]; then return $rc; fi
  return 0
}

maybe_evolve() {   # maybe_evolve <claims_now> <session_no> <force 0|1>
  local claims=$1 session=$2 force=$3
  local last_claims=0 last_session=0 d_claims d_sessions
  if [ -f "$STATE/evolve.state" ]; then
    read -r last_claims last_session < "$STATE/evolve.state"
  fi
  d_claims=$((claims - last_claims))
  d_sessions=$((session - last_session))
  if [ "$force" = "1" ] || { [ $d_claims -ge $EVOLVE_MIN_NEW_CLAIMS ] && [ $d_sessions -ge $EVOLVE_MIN_SESSIONS ]; }; then
    log "EVOLVE fire  session=$session new_claims=$d_claims sessions_since=$d_sessions force=$force"
    attempt_run "evolve" run_evolve
    echo "$claims $session" > "$STATE/evolve.state"
    printf '%s,%s,%s,%s,%s\n' "$(date -u +%FT%TZ)" "$session" "$d_claims" "$d_sessions" "$force" \
      >> "$STATE/evolve-history.csv"
    # adoption rebuilds derived layers through the queue
    drain_to_zero || log "WARN post-evolve drain incomplete"
  fi
}

# ---------------------------------------------------------------- one conversation
build_one() {
  local n=$1
  local idx=$((10#$n - 1))
  APP=$ROOT/app-$n
  STATE=$ROOT/state/app-$n
  TAG="app-$n"
  mkdir -p "$STATE"
  [ -f "$STATE/evolve-history.csv" ] || echo "utc,session,new_claims,sessions_since,forced" > "$STATE/evolve-history.csv"
  [ -f "$STATE/progress.csv" ] || echo "utc,session,claims,documents,sources,seconds" > "$STATE/progress.csv"

  local total
  total=$(python3 "$ROOT/to_material.py" count "$idx") || { log "FATAL cannot read session count"; return 1; }
  log "START conversation idx=$idx sessions=$total"

  # the stack must be up before anything touches it
  attempt_run "up" bash -c "cd '$APP' && ./app.py up" || { log "FATAL stack will not start"; return 1; }

  local i si t0 t1 claims docs sources
  for i in $(seq 1 "$total"); do
    si=$(printf '%03d' "$i")
    if [ -f "$STATE/session-$si.done" ]; then
      continue
    fi
    t0=$(date +%s)
    log "session $i/$total: convert"
    attempt_run "emit-$si" python3 "$ROOT/to_material.py" emit "$idx" "$i" "$APP/material/s$si" \
      || { log "FATAL conversion/round-trip failed at session $i"; return 1; }
    log "session $i/$total: ingest"
    attempt_run "ingest-$si" bash -c "cd '$APP' && ./app.py ingest material/s$si" \
      || { log "ERROR ingest failed at session $i — leaving it unmarked and stopping this conversation"; return 1; }
    log "session $i/$total: compile"
    if ! drain_to_zero; then
      log "ERROR compile queue never reached zero at session $i — leaving it unmarked and stopping this conversation"
      return 1
    fi
    claims=$(probe claims); docs=$(probe 'canonical documents'); sources=$(probe sources)
    t1=$(date +%s)
    printf '%s,%s,%s,%s,%s,%s\n' "$(date -u +%FT%TZ)" "$i" "${claims:-?}" "${docs:-?}" "${sources:-?}" "$((t1 - t0))" \
      >> "$STATE/progress.csv"
    log "session $i/$total: done in $((t1 - t0))s (claims=${claims:-?} docs=${docs:-?})"
    touch "$STATE/session-$si.done"
    maybe_evolve "${claims:-0}" "$i" 0
  done

  # One forced round after the last session, so the finished structure reflects all of the
  # material. Kept outside the loop and separately marked, so a crash during it is resumable.
  if [ ! -f "$STATE/final-evolve.done" ]; then
    maybe_evolve "$(probe claims)" "$total" 1
    touch "$STATE/final-evolve.done"
  fi
  log "FINISH conversation idx=$idx claims=$(probe claims) documents=$(probe 'canonical documents')"
  touch "$STATE/conversation.done"
  return 0
}

# ---------------------------------------------------------------- entry points
if [ "${1:-}" = "--one" ]; then
  n=$2
  mkdir -p "$ROOT/logs"
  build_one "$n" >> "$ROOT/logs/app-$n.log" 2>&1
  rc=$?
  echo "app-$n exited rc=$rc"
  exit $rc
fi

mkdir -p "$ROOT/logs" "$ROOT/state"
log "01-build.sh start — pool=$POOL evolve=(claims>=$EVOLVE_MIN_NEW_CLAIMS and sessions>=$EVOLVE_MIN_SESSIONS)"
printf '%s\n' 01 02 03 04 05 06 07 08 09 10 \
  | xargs -P "$POOL" -I{} "$ROOT/01-build.sh" --one {}
rc=$?
done_count=$(ls "$ROOT"/state/app-*/conversation.done 2>/dev/null | wc -l)
log "01-build.sh end rc=$rc — conversations finished: $done_count/10"
exit $rc
