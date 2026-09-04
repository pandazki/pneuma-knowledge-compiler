#!/usr/bin/env bash
# 03-score.sh — LoCoMo-Refined full run, scoring phase.
#
# The official scorer is invoked as shipped:
#   ./scripts/run_eval.sh --metrics llm f1 bleu --llm-judge refined --concurrency 64
# Nothing about the benchmark's own code, prompts or thresholds is touched. The gold answers
# are read only by that scorer, inside its own process.
#
# The judge is the official one, Qwen/Qwen3-14B, served through OpenRouter as
# `qwen/qwen3-14b` — an accepted alias, so the scorer's own Qwen check passes without a
# non-Qwen confirmation prompt. The API key is mapped into the scorer's process environment
# from the project .env at run time; it is never echoed, never written to a file, never
# passed on a command line.
#
# Resumable: the official scorer runs the whole set in one call (that is what "invoked as
# shipped" means), so the resumable unit here is the scoring run itself — a completed,
# record-complete scored file is detected and not recomputed. Pass --force to rescore.
set -uo pipefail

ROOT=/data/qiwei/lcr-final
DATA=$ROOT/data
EXPECTED=1382
FORCE=${1:-}

log() { printf '%s [03-score] %s\n' "$(date -u +%FT%TZ)" "$*"; }

# ---------------------------------------------------------------- 1. assemble predictions
mkdir -p "$DATA/outputs" "$ROOT/outputs"
PRED=$DATA/outputs/predictions.jsonl

log "assembling predictions from outputs/answers/"
python3 - "$ROOT" "$PRED" "$EXPECTED" <<'PY'
import json, sys, pathlib
root, pred_path, expected = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), int(sys.argv[3])
seen, rows = set(), []
for path in sorted((root / "outputs/answers").glob("app-*.jsonl")):
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        qa_id = str(record["qa_id"])
        if qa_id in seen:          # a resumed run may have appended a qa_id twice
            continue
        seen.add(qa_id)
        rows.append({"qa_id": qa_id, "predicted_answer": str(record.get("predicted_answer") or "")})

# every qa_id in the official question file must be present exactly once
official = [json.loads(line)["qa_id"] for line in
            (root / "data/data/public/questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
missing = [q for q in official if q not in seen]
extra = [q for q in seen if q not in set(official)]
order = {q: i for i, q in enumerate(official)}
rows.sort(key=lambda r: order.get(r["qa_id"], 10**9))
pred_path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
empty = sum(1 for r in rows if not r["predicted_answer"].strip())
print(f"  predictions={len(rows)} expected={expected} missing={len(missing)} extra={len(extra)} empty={empty}")
if missing:
    print(f"  first missing: {missing[:5]}")
if len(rows) != expected or missing or extra:
    raise SystemExit("error: prediction set is not complete — refusing to score a partial run")
PY
[ $? -eq 0 ] || { log "FATAL prediction assembly failed"; exit 1; }

# ---------------------------------------------------------------- 2. skip if already scored
SCORED=$DATA/outputs/predictions_scored.jsonl
SUMMARY=$DATA/outputs/predictions_scored_summary.json
if [ "$FORCE" != "--force" ] && [ -f "$SCORED" ] && [ -f "$SUMMARY" ]; then
  have=$(wc -l < "$SCORED")
  if [ "$have" = "$EXPECTED" ]; then
    log "already scored ($have records) — skipping. Pass --force to rescore."
    cp "$SCORED" "$SUMMARY" "$ROOT/outputs/" 2>/dev/null
    cp "$DATA/outputs/predictions_scored_summary.md" "$ROOT/outputs/" 2>/dev/null
    exit 0
  fi
  log "scored file has $have records, expected $EXPECTED — rescoring"
fi

# ---------------------------------------------------------------- 3. official scorer
log "running the official scorer (judge=Qwen3-14B, refined prompt, concurrency=64)"
cd "$DATA" || { log "FATAL dataset repo missing"; exit 1; }

# credentials are mapped in-process from the project .env; nothing is printed
eval "$(python3 - <<'PY'
import pathlib, shlex
env = {}
for raw in pathlib.Path("/data/qiwei/lcr-final/app-01/.env").read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if line and not line.startswith("#") and "=" in line:
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip("'\"")
print("export EVALUATOR_API_KEY=" + shlex.quote(env["OPENROUTER_API_KEY"]))
PY
)"
export EVALUATOR_MODEL="qwen/qwen3-14b"
export EVALUATOR_API_BASE="https://openrouter.ai/api/v1"
export LOCOMO_PYTHON_BIN="$ROOT/repo/.venv/bin/python"
export LOCOMO_PREDICTIONS_PATH="$PRED"

./scripts/run_eval.sh --metrics llm f1 bleu --llm-judge refined --concurrency 64
rc=$?
unset EVALUATOR_API_KEY
log "official scorer exited rc=$rc"
[ $rc -eq 0 ] || exit $rc

cp "$SCORED" "$SUMMARY" "$ROOT/outputs/" 2>/dev/null
cp "$DATA/outputs/predictions_scored_summary.md" "$ROOT/outputs/" 2>/dev/null
log "03-score.sh done — results in $ROOT/outputs/"
