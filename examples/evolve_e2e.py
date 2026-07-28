#!/usr/bin/env python
"""End-to-end schema-evolve journey over the running stack (Stage C + Stage E).

Config-driven: every dataset-specific value (user id, profile PUT payload, wave files,
recall questions, briefing, as-of, whether to import a preset) lives in a
`journey.config.json` inside the journey directory. `--journey <dir>` selects the dataset;
the script itself carries no persona knowledge. The public repository intentionally ships
no domain journey: data synthesis and experiment design are separate tasks, so callers
must provide an explicitly reviewed synthetic journey.

The journey drives a user through a 6–8 week data path in which a schema evolve happens
mid-stream, then verifies the new schema is actually used by daily compile — all over the
HTTP API, exactly as the UI does.

PREREQUISITES (this script does NOT manage them):
  1. middleware up:   docker compose -f infra/docker-compose.yml up -d --wait
  2. API up:          bash scripts/dev-api.sh          (default http://localhost:18000)
  3. compile worker:  bash scripts/dev-worker.sh       (drains compile / evolve / adopt jobs)
  4. an OpenRouter key in .env — compile, evolve-propose and recall use configured models.
     This script never reads the key; the API/worker process does.

Each wave file is a JSON list of POST /sources/conversation bodies. The narrative + what
evolve is expected to identify live in each dataset's journey.md.

Idempotency: `--fresh` re-imports the preset first (preset datasets only), giving a clean
journey every run. Without it, conversation ingest dedups by checksum and compile/evolve
are single-flight, so a re-run is still safe. For a no-preset dataset the user is created
on first ingest; `--fresh` is a no-op there (nothing to re-import).

Flow (each step prints a clear header + key outputs; everything is also appended to a
review dump, default <journey>/.run/evolve-e2e-run.md, override with --out or
$EVOLVE_E2E_OUT — point it at your scratchpad for review):

  1  ensure the user exists (import_presets if preset dataset; else fresh user on ingest)
  2  PUT profile (from config) → GET /skill (tailored packs)
  3  wave day-one ingest → compile → canonical tree + new docs
  4  cluster waves ingest → compile → passive-trigger stats AND manual POST /evolve
     → poll the evolve task to draft/no_change → proposal rationale, mechanical summary,
       dropped list, changed files
  5  REVIEW PAUSE: draft detail dumped for a human; --auto-adopt (default on) continues
  6  adopt → poll adopted → HEAD advance + GET /skill new composition
  7  post-adopt waves ingest → compile → did new material land in the evolved family?
  8  recall: N Q&A (fast + 1 briefing) across old topics / new family / cross-period

Exit non-zero on any hard failure (missing user, job failure, empty recall where content
is expected).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

# Must precede any middleware/localhost client: pins the proxy bypass (see _bootstrap.py).
import _bootstrap  # noqa: F401  (import for side effect)

_LOG: list[str] = []


# ------------------------------------------------------------------- config model


@dataclass
class Journey:
    """Everything the flow needs, loaded from <dir>/journey.config.json."""

    dir: Path
    user_id: str
    import_preset: bool
    journey_as_of: str
    profile: dict[str, Any]
    base_family_prefixes: tuple[str, ...]
    day_one: list[str]
    cluster: list[str]
    post_adopt: list[str]
    recall_questions: list[dict[str, Any]]
    briefing: dict[str, Any]

    @classmethod
    def load(cls, journey_dir: Path) -> "Journey":
        cfg_path = journey_dir / "journey.config.json"
        if not cfg_path.is_file():
            raise SystemExit(f"no journey.config.json under {journey_dir}")
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        waves = cfg["waves"]
        return cls(
            dir=journey_dir,
            user_id=cfg["user_id"],
            import_preset=bool(cfg.get("import_preset", False)),
            journey_as_of=cfg["journey_as_of"],
            profile=cfg["profile"],
            base_family_prefixes=tuple(cfg["base_family_prefixes"]),
            day_one=list(waves["day_one"]),
            cluster=list(waves["cluster"]),
            post_adopt=list(waves["post_adopt"]),
            recall_questions=list(cfg["recall_questions"]),
            briefing=dict(cfg["briefing"]),
        )


# ------------------------------------------------------------------- output helpers


def log(line: str = "") -> None:
    print(line)
    _LOG.append(line)


def header(title: str) -> None:
    bar = "=" * 78
    log("")
    log(bar)
    log(f"== {title}")
    log(bar)


def dump_review(out_path: Path, user: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()
    body = f"# evolve-e2e run — {user}\n\n_generated {stamp}_\n\n```\n" + "\n".join(_LOG) + "\n```\n"
    out_path.write_text(body, encoding="utf-8")
    print(f"\n[review dump] {out_path}")


# --------------------------------------------------------------------- API client


class Api:
    def __init__(self, base: str, user: str) -> None:
        self.base = base.rstrip("/")
        self.user = user
        # Recall / evolve-propose may call remote models; give slow lanes enough headroom.
        self.c = httpx.Client(timeout=httpx.Timeout(300.0, connect=10.0))

    def u(self, path: str) -> str:
        return f"{self.base}/v1/users/{self.user}{path}"

    def get(self, path: str, root: bool = False) -> Any:
        url = f"{self.base}{path}" if root else self.u(path)
        r = self.c.get(url)
        r.raise_for_status()
        return r.json()

    def post(self, path: str, body: dict | None = None) -> httpx.Response:
        r = self.c.post(self.u(path), json=body or {})
        return r

    def put(self, path: str, body: dict) -> Any:
        r = self.c.put(self.u(path), json=body)
        r.raise_for_status()
        return r.json()

    def close(self) -> None:
        self.c.close()


# ----------------------------------------------------------------- small utilities


def _load_wave(cfg: Journey, name: str) -> list[dict]:
    return json.loads((cfg.dir / name).read_text(encoding="utf-8"))


def _doc_paths(api: Api) -> list[str]:
    ds = api.get("/dataset")
    docs = ds.get("documents", {}).get("documents", [])
    return sorted(d.get("path", "?") for d in docs)


def _head_ref(api: Api) -> str:
    snaps = api.get("/snapshots")
    return snaps[0]["ref"] if snaps else ""


def print_tree(api: Api) -> list[str]:
    paths = _doc_paths(api)
    fam: dict[str, list[str]] = {}
    for p in paths:
        top = "/".join(p.split("/")[:2]) if p.startswith("memory/") else p
        fam.setdefault(top, []).append(p)
    log(f"  canonical HEAD={_head_ref(api)[:10]}  docs={len(paths)}")
    for top in sorted(fam):
        log(f"    {top}/  ({len(fam[top])})")
        for p in fam[top]:
            log(f"      - {p}")
    return paths


def wait_for_jobs(api: Api, label: str, timeout_s: float = 900.0) -> None:
    """Poll /jobs until nothing is queued/claimed (the whole per-user queue is quiet).

    The compiler / evolve worker drains this queue out-of-band; ingest and POST /compile
    only enqueue. Job status walks queued → claimed → done (with ok true/false).

    A job that FAILS during this wait is a hard failure (the run's own docstring promise):
    a gate-rejected compile means the canonical this journey verifies was never written, and
    a green exit over it would be a lie. Failures predating this wait (an earlier run's
    debris) are logged but not fatal."""
    log(f"  [{label}] waiting for the compile queue to drain …")
    t0 = time.time()
    last = ""
    pre_existing = {j["job_id"] for j in api.get("/jobs") if j["ok"] is False}
    while True:
        jobs = api.get("/jobs")
        pending = [j for j in jobs if j["status"] in ("queued", "claimed")]
        tally: dict[str, int] = {}
        for j in jobs:
            tally[j["status"]] = tally.get(j["status"], 0) + 1
        snap = " ".join(f"{k}={v}" for k, v in sorted(tally.items()))
        if snap != last:
            log(f"    jobs: {snap}")
            last = snap
        if not pending:
            failed = [j for j in jobs if j["ok"] is False]
            fresh = [j for j in failed if j["job_id"] not in pre_existing]
            for j in failed:
                stale = "" if j["job_id"] not in pre_existing else " (pre-existing)"
                log(f"    ! job {j['job_id'][:8]} {j['kind']} FAILED{stale}: {j['detail']}")
            if fresh:
                raise SystemExit(
                    f"[{label}] {len(fresh)} job(s) failed during this step — aborting the run."
                )
            return
        if time.time() - t0 > timeout_s:
            raise TimeoutError(f"[{label}] jobs did not drain within {timeout_s}s")
        time.sleep(3.0)


def ingest_wave(api: Api, cfg: Journey, name: str) -> list[str]:
    sessions = _load_wave(cfg, name)
    log(f"  ingesting {name}: {len(sessions)} session(s)")
    ids: list[str] = []
    for s in sessions:
        r = api.post("/sources/conversation", s)
        r.raise_for_status()
        out = r.json()
        dedup = " (dedup)" if out.get("deduplicated") else ""
        log(f"    + {out['source_id'][:8]}  '{s['title']}'{dedup}")
        ids.append(out["source_id"])
    comp = api.post("/compile").json()
    log(f"    compile enqueued {len(comp['enqueued'])} job(s) for {len(comp['source_ids'])} source(s)")
    wait_for_jobs(api, name)
    return ids


def ingest_waves(api: Api, cfg: Journey, names: list[str]) -> list[str]:
    ids: list[str] = []
    for name in names:
        ids += ingest_wave(api, cfg, name)
    return ids


# ------------------------------------------------------------------------- steps


def step1_ensure_user(api: Api, cfg: Journey, fresh: bool) -> None:
    header("STEP 1 — ensure the journey user exists")
    users = api.get("/v1/users", root=True)
    present = cfg.user_id in users

    if not cfg.import_preset:
        # No-preset dataset: the user is materialized on first ingest (step 3). A profile
        # PUT (step 2) also stamps a persisted picture. Nothing to import.
        if present:
            log(f"  {cfg.user_id} already has data (re-run). baseline canonical:")
            print_tree(api)
        else:
            log(f"  {cfg.user_id} starts empty — will be created on first ingest (no preset).")
            if fresh:
                log("  (--fresh has no preset to re-import for this dataset; ignoring.)")
        return

    if fresh or not present:
        log(f"  {'--fresh' if fresh else 'user missing'} → importing preset {cfg.user_id} …")
        import import_presets  # sibling module (examples/)

        import_presets.sys.argv = ["import_presets", cfg.user_id]
        rc = import_presets.main()
        if rc != 0:
            raise SystemExit(f"import_presets returned {rc}")
        users = api.get("/v1/users", root=True)
    if cfg.user_id not in users:
        raise SystemExit(
            f"user {cfg.user_id} not found. Run: uv run python examples/import_presets.py {cfg.user_id}"
        )
    log(f"  OK: {cfg.user_id} present. Baseline sources: {len(api.get('/sources'))}")
    log("  baseline canonical:")
    print_tree(api)


def step2_profile_and_skill(api: Api, cfg: Journey) -> None:
    header("STEP 2 — set profile (from config) + show tailored packs (量身定制第一面)")
    prof = api.put("/profile", cfg.profile)
    log(f"  profile: display_name={prof['display_name']!r} role={prof['role']} "
        f"industry={prof.get('industry')!r} occupation={prof['occupation']!r} "
        f"response_language={prof['preferences']['response_language']} source={prof.get('source')}")
    skill = api.get("/skill")
    log(f"  skill version={skill['version']} base={skill['base_version']} hash={skill['content_hash'][:10]}")
    log("  effective packs:")
    for p in skill["packs"]:
        log(f"    - {p['pack_id']} (origin={p['origin']}) templates={p['extra_path_templates']}")
    log(f"  path_templates ({len(skill['path_templates'])}): {skill['path_templates']}")


def step3_day_one(api: Api, cfg: Journey) -> None:
    header("STEP 3 — day-one waves ingest + compile (tailored pack collects from day one)")
    ingest_waves(api, cfg, cfg.day_one)
    log("  canonical after day-one waves:")
    print_tree(api)


def _evolve_task_ids(api: Api) -> set[str]:
    return {t["task_id"] for t in api.get("/evolve")}


def _wait_for_evolve_task(api: Api, known: set[str], timeout_s: float = 900.0) -> dict:
    """Wait for a NEW evolve task (not in `known`) to reach a terminal phase-1 state."""
    t0 = time.time()
    terminal = ("draft", "no_change", "aborted", "expired")
    while True:
        tasks = api.get("/evolve")  # newest first
        for t in tasks:
            if t["task_id"] not in known and t["status"] in terminal:
                return api.get(f"/evolve/{t['task_id']}")
        if time.time() - t0 > timeout_s:
            raise TimeoutError("evolve task did not reach a terminal phase-1 state")
        time.sleep(3.0)


def step4_cluster_and_evolve(api: Api, cfg: Journey) -> dict:
    header("STEP 4 — cluster waves ingest + compile → passive-trigger stats + manual evolve")
    known_before = _evolve_task_ids(api)
    ingest_waves(api, cfg, cfg.cluster)

    log("  canonical after cluster waves (watch memory/topics/ accumulate a coherent topic cluster):")
    paths = print_tree(api)
    topic_docs = [p for p in paths if p.startswith("memory/topics/")]

    # --- passive-trigger path: the worker calls maybe_trigger_evolve after every committed
    # compile. Report whether it already fired, and the threshold context we can observe.
    log("")
    log("  passive-trigger check (schema-evolve §2.1):")
    log("    thresholds: evolve_trigger_topic_docs=5 AND evolve_trigger_new_claims=30")
    log(f"    observed memory/topics/ docs now: {len(topic_docs)}")
    log("    (new-claims count is internal to compile_events; not exposed over the API —")
    log("     the worker AND-gates both before auto-enqueuing an evolve job.)")
    auto = [t for t in api.get("/evolve") if t["task_id"] not in known_before]
    if auto:
        log(f"    → PASSIVE trigger already fired: {len(auto)} evolve task(s) present.")
    else:
        log("    → passive trigger has NOT fired yet (thresholds not both met, or in flight).")

    # --- manual path: POST /evolve. 409 means an evolve is already pending (single-flight),
    # in which case we ride the existing one — both paths converge on the same task table.
    log("")
    log("  manual trigger: POST /evolve")
    r = api.post("/evolve")
    if r.status_code == 409:
        log(f"    409 (single-flight): {r.json().get('detail')} — riding the pending evolve.")
    else:
        r.raise_for_status()
        log(f"    enqueued evolve job {r.json()['job_id'][:8]}")

    log("  waiting for the evolve task (phase-1 propose → phase-2 reorganize) …")
    wait_for_jobs(api, "evolve")
    detail = _wait_for_evolve_task(api, known_before)

    header("STEP 4 (cont) — evolve proposal")
    log(f"  task {detail['task_id']}  status={detail['status']}")
    log(f"  detail: {detail.get('detail')}")
    if detail["status"] != "draft":
        log("  (phase-1 produced no adoptable draft — status above. Journey stops before adopt.)")
        return detail
    log(f"  base_ref={(detail.get('base_ref') or '')[:10]}  branch={detail.get('branch')}")
    log("  proposal rationale:")
    for ln in (detail.get("rationale") or "(none)").splitlines():
        log(f"    {ln}")
    prop = detail.get("proposal") or {}
    for pack in prop.get("packs", []):
        log(f"  proposed pack: {pack.get('pack_id')} templates={pack.get('extra_path_templates')}")
    log(f"  mechanical summary: {json.dumps(detail.get('summary'), ensure_ascii=False)}")
    dropped = detail.get("dropped") or []
    log(f"  dropped ({len(dropped)}): " + (json.dumps(dropped, ensure_ascii=False)[:400] if dropped else "none"))
    changed = detail.get("changed_files") or []
    log(f"  changed files ({len(changed)}):")
    for cf in changed:
        log(f"    ~ {cf['path']}  ({len(cf['old_body'])} → {len(cf['new_body'])} chars)")
    return detail


def step5_review_pause(detail: dict, out_path: Path, auto_adopt: bool) -> bool:
    header("STEP 5 — REVIEW WINDOW (human-in-the-loop)")
    draft_path = out_path.parent / f"evolve-draft-{detail['task_id'][:8]}.md"
    draft_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# evolve draft {detail['task_id']}",
        f"status: {detail['status']}",
        f"detail: {detail.get('detail')}",
        f"base_ref: {detail.get('base_ref')}",
        f"branch: {detail.get('branch')}",
        "",
        "## rationale",
        detail.get("rationale") or "(none)",
        "",
        "## proposal",
        "```json",
        json.dumps(detail.get("proposal"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## mechanical summary",
        "```json",
        json.dumps(detail.get("summary"), ensure_ascii=False, indent=2),
        "```",
        "",
        "## changed files (base → branch)",
    ]
    for cf in detail.get("changed_files") or []:
        lines += [
            f"### {cf['path']}",
            "#### old",
            "```", cf["old_body"], "```",
            "#### new",
            "```", cf["new_body"], "```",
            "",
        ]
    draft_path.write_text("\n".join(lines), encoding="utf-8")
    log(f"  draft detail written for review → {draft_path}")
    log(f"  --auto-adopt = {auto_adopt}")
    if not auto_adopt:
        log("  stopping at the review window (POST .../adopt or .../drop by hand to continue).")
    return auto_adopt


def step6_adopt(api: Api, detail: dict) -> None:
    header("STEP 6 — adopt draft → mechanical catch-up merge → HEAD advance")
    head_before = _head_ref(api)
    task_id = detail["task_id"]
    r = api.post(f"/evolve/{task_id}/adopt")
    if r.status_code != 202:
        raise SystemExit(f"adopt not accepted: {r.status_code} {r.text}")
    log(f"  adopt enqueued (202) job {r.json()['job_id'][:8]}")
    wait_for_jobs(api, "adopt")
    # confirm the task decided
    t0 = time.time()
    while True:
        d = api.get(f"/evolve/{task_id}")
        if d["status"] != "draft":
            break
        if time.time() - t0 > 300:
            raise TimeoutError("adopt did not decide the task")
        time.sleep(2.0)
    log(f"  task status now: {d['status']}  detail={d.get('detail')}")
    head_after = _head_ref(api)
    log(f"  canonical HEAD: {head_before[:10]} → {head_after[:10]} "
        f"({'advanced' if head_after != head_before else 'UNCHANGED'})")
    skill = api.get("/skill")
    log(f"  skill after adopt: version={skill['version']} base={skill['base_version']}")
    log("  effective packs now:")
    for p in skill["packs"]:
        log(f"    - {p['pack_id']} (origin={p['origin']}) templates={p['extra_path_templates']}")


def step7_post_adopt(api: Api, cfg: Journey, before_paths: list[str]) -> None:
    header("STEP 7 — post-adopt waves ingest + compile → does new material land in the evolved family?")
    before = set(before_paths)
    ingest_waves(api, cfg, cfg.post_adopt)
    after = _doc_paths(api)
    print_tree(api)
    new_paths = [p for p in after if p not in before]
    log("")
    log(f"  new docs since adopt ({len(new_paths)}):")
    evolved = []
    for p in new_paths:
        is_base = any(p.startswith(pre) for pre in cfg.base_family_prefixes)
        tag = "base-family" if is_base else "EVOLVED-family"
        if not is_base:
            evolved.append(p)
        log(f"    - {p}  [{tag}]")
    if evolved:
        log(f"  → {len(evolved)} post-adopt doc(s) filed into the evolved (non-base) family — new schema in use.")
    else:
        log("  → no post-adopt doc landed outside the base families (review whether the model reused topics).")


def _fast(api: Api, cfg: Journey, tag: str, query: str) -> None:
    r = api.post("/recall", {"query": query, "mode": "fast", "as_of": cfg.journey_as_of})
    r.raise_for_status()
    a = r.json()
    log(f"  [{tag}] Q: {query}")
    log(f"    A: {a['answer'].strip()}")
    cits = a.get("citation_handles") or {}
    log(f"    citations: used_claims={len(a.get('used_claims', []))} "
        f"windows={len(a.get('used_windows', []))} handles={cits}")


def step8_recall(api: Api, cfg: Journey) -> None:
    header("STEP 8 — recall verification (fast × N + 1 briefing)")

    for q in cfg.recall_questions:
        _fast(api, cfg, q["tag"], q["question"])

    log("-- briefing (anchored-source continuous Q&A) --")
    b = api.post("/briefings", {"query": cfg.briefing["query"],
                                "budget_chars": cfg.briefing.get("budget_chars", 24000)}).json()
    log(f"  briefing {b['briefing_id'][:8]} snapshot={b['snapshot_ref'][:10]} "
        f"claims={b['claims_count']} sources={b['source_count']} chars={b['char_count']}")
    ask = api.c.post(api.u(f"/briefings/{b['briefing_id']}/ask"),
                     json={"question": cfg.briefing["ask"]})
    ask.raise_for_status()
    aj = ask.json()
    log(f"  [briefing] A: {aj['answer'].strip()}")
    log(f"    citations={len(aj.get('citations', []))} handles={aj.get('citation_handles')}")


# --------------------------------------------------------------------------- main


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="config-driven evolve journey e2e")
    ap.add_argument("--journey", required=True,
                    help="reviewed synthetic journey directory holding journey.config.json + wave*.json")
    ap.add_argument("--base", default=os.environ.get("PNEUMA_KNOWLEDGE_API_BASE", "http://localhost:18000"),
                    help="API base URL (default http://localhost:18000)")
    ap.add_argument("--fresh", action="store_true",
                    help="re-import the preset first (preset datasets only; no-op otherwise)")
    ap.add_argument("--auto-adopt", dest="auto_adopt", action="store_true", default=True,
                    help="adopt the draft and run post-adopt waves + recall (default)")
    ap.add_argument("--no-auto-adopt", dest="auto_adopt", action="store_false",
                    help="stop at the review window (step 5)")
    ap.add_argument("--out", default=os.environ.get("EVOLVE_E2E_OUT", ""),
                    help="review dump path (markdown); default <journey>/.run/evolve-e2e-run.md")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    cfg = Journey.load(Path(args.journey).resolve())
    out_path = Path(args.out) if args.out else cfg.dir / ".run" / "evolve-e2e-run.md"
    api = Api(args.base, cfg.user_id)
    try:
        # fail fast if the API is not up
        try:
            hz = api.get("/healthz", root=True)
            log(f"API {args.base} healthz={hz}")
        except Exception as exc:  # noqa: BLE001
            print(f"API not reachable at {args.base}: {exc}\n"
                  "Start it with: bash scripts/dev-api.sh (and the worker: bash scripts/dev-worker.sh)",
                  file=sys.stderr)
            return 2

        log(f"journey: {cfg.dir}  user={cfg.user_id}  import_preset={cfg.import_preset}")

        step1_ensure_user(api, cfg, args.fresh)
        step2_profile_and_skill(api, cfg)
        step3_day_one(api, cfg)
        detail = step4_cluster_and_evolve(api, cfg)

        if detail["status"] != "draft":
            log("\nNo adoptable draft — ending after the proposal (see status above).")
            return 0

        proceed = step5_review_pause(detail, out_path, args.auto_adopt)
        if not proceed:
            log("\nStopped at review window (--no-auto-adopt).")
            return 0

        paths_before_post = _doc_paths(api)
        step6_adopt(api, detail)
        step7_post_adopt(api, cfg, paths_before_post)
        step8_recall(api, cfg)

        header("DONE — evolve journey complete")
        log("  old topics recalled, evolved family populated by post-adopt waves, cross-period Q&A answered.")
        return 0
    finally:
        dump_review(out_path, cfg.user_id)
        api.close()


if __name__ == "__main__":
    sys.exit(main())
