#!/usr/bin/env python3
"""Langfuse probe / cost aggregation. Credentials are loaded from a project .env
and never printed.

    python3 lf.py probe  <project-dir> [minutes]
    python3 lf.py cost   <project-dir> [--from ISO8601] [--out out.json]
"""
from __future__ import annotations

import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path


def load_creds(project_dir: Path) -> tuple[str, str, str]:
    env = project_dir / ".env"
    values: dict[str, str] = {}
    for raw in env.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        values[k.strip()] = v.strip().strip("'\"")
    pub = values.get("LANGFUSE_PUBLIC_KEY", "")
    sec = values.get("LANGFUSE_SECRET_KEY", "")
    base = values.get("LANGFUSE_BASE_URL", "").rstrip("/")
    if not (pub and sec and base):
        raise SystemExit("error: LANGFUSE_* incomplete in " + str(env))
    return pub, sec, base


def api_get(base: str, pub: str, sec: str, path: str, params: dict) -> dict:
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    token = base64.b64encode(f"{pub}:{sec}".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {token}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def cmd_probe(project_dir: Path, minutes: int) -> int:
    pub, sec, base = load_creds(project_dir)
    since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()
    try:
        data = api_get(base, pub, sec, "/api/public/traces",
                       {"limit": 20, "fromTimestamp": since})
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()[:300]}", file=sys.stderr)
        return 1
    items = data.get("data", [])
    print(f"traces in last {minutes}min: {len(items)}")
    for t in items[:20]:
        md = t.get("metadata") or {}
        print(f"  {t.get('timestamp')}  name={t.get('name')}  "
              f"op={md.get('operation')}  user={t.get('userId')}  "
              f"session={t.get('sessionId')}")
    return 0 if items else 3


def cmd_cost(project_dir: Path, since: str | None, out: Path | None) -> int:
    import time

    pub, sec, base = load_creds(project_dir)
    params_base: dict = {"limit": 100}
    if since:
        params_base["fromStartTime"] = since   # v1 accepts this as the lower bound
    agg: dict[str, dict] = {}
    page = 1
    total = 0
    while True:
        params = dict(params_base, page=page)
        data = None
        for attempt in range(8):
            try:
                data = api_get(base, pub, sec, "/api/public/observations", params)
                time.sleep(4.5)   # the API allows 15 reads/min
                break
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    body = exc.read().decode()
                    wait = 40
                    try:
                        wait = int(json.loads(body)["details"]["retryAfterSeconds"]) + 3
                    except Exception:  # noqa: BLE001
                        pass
                    print(f"  rate limited, waiting {wait}s (page {page})", file=sys.stderr)
                    time.sleep(wait)
                    continue
                print(f"HTTP {exc.code}: {exc.read().decode()[:300]}", file=sys.stderr)
                return 1
        if data is None:
            print("error: gave up after repeated rate limits", file=sys.stderr)
            return 1
        items = data.get("data", [])
        if not items:
            break
        for o in items:
            md = o.get("metadata") or {}
            op = md.get("operation") or o.get("name") or "unknown"
            uid = o.get("userId") or md.get("user_id") or "unknown"
            key = f"{uid}|{op}"
            slot = agg.setdefault(key, {"user_id": uid, "operation": op, "calls": 0,
                                        "input": 0, "output": 0, "total": 0, "cost_usd": 0.0})
            usage = o.get("usage") or {}
            slot["calls"] += 1
            slot["input"] += usage.get("input") or 0
            slot["output"] += usage.get("output") or 0
            slot["total"] += usage.get("total") or 0
            cost = o.get("calculatedTotalCost")
            if cost is None:
                cost = (o.get("costDetails") or {}).get("total")
            slot["cost_usd"] += float(cost or 0.0)
        total += len(items)
        meta = data.get("meta") or {}
        if page >= (meta.get("totalPages") or page):
            break
        page += 1
    rows = sorted(agg.values(), key=lambda r: (r["user_id"], r["operation"]))
    print(f"observations scanned: {total}")
    print(f"{'user_id':24s} {'operation':22s} {'calls':>7s} {'input':>12s} {'output':>10s} {'total':>12s} {'cost_usd':>10s}")
    for r in rows:
        print(f"{r['user_id']:24s} {r['operation']:22s} {r['calls']:7d} {r['input']:12d} "
              f"{r['output']:10d} {r['total']:12d} {r['cost_usd']:10.4f}")
    if out:
        out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"written: {out}")
    return 0


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, proj = sys.argv[1], Path(sys.argv[2])
    if not proj.is_absolute():
        proj = Path(__file__).resolve().parent / proj
    if cmd == "probe":
        minutes = int(sys.argv[3]) if len(sys.argv) > 3 else 30
        return cmd_probe(proj, minutes)
    if cmd == "cost":
        since = out = None
        args = sys.argv[3:]
        for i, a in enumerate(args):
            if a == "--from" and i + 1 < len(args):
                since = args[i + 1]
            if a == "--out" and i + 1 < len(args):
                out = Path(args[i + 1])
        return cmd_cost(proj, since, out)
    print(f"unknown command {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
