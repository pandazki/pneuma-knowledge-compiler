#!/usr/bin/env bash
# Tear down only this experiment's ten scoped stacks, preserving volumes.
set -uo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TEMPLATE_SHA256=67f43f2ef0d71dba9d6499071b134b5b44ad60449a4ad6d2c938cb27fd5e1f92

assert_scope() {
  local number=$1 app="$ROOT/app-$1" count actual
  count=$(grep -c "^PNEUMA_APP_COMPOSE_PROJECT=pneuma-lcr2609-${number}-" "$app/.env" 2>/dev/null || true)
  [ "$count" = "1" ] || return 1
  actual=$(shasum -a 256 "$app/app.py" | awk '{print $1}')
  [ "$actual" = "$TEMPLATE_SHA256" ] || return 1
}

down_one() {
  local number=$1 app="$ROOT/app-$1"
  assert_scope "$number" || return 1
  (cd "$app" && ./app.py down)
}

if [ "${1:-}" = "--one" ]; then
  down_one "$2"
  exit $?
fi

printf '%s\n' 01 02 03 04 05 06 07 08 09 10 \
  | xargs -P 10 -I{} "$ROOT/scripts/06-rerun-down.sh" --one {}
rc=$?
owned=$(docker ps --filter name=pneuma-lcr2609 --format '{{.Names}}' | wc -l | tr -d ' ')
printf '%s [06-rerun-down] complete rc=%s owned_running=%s\n' "$(date -u +%FT%TZ)" "$rc" "$owned"
[ "$rc" -eq 0 ] && [ "$owned" = "0" ]
