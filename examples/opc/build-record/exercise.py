#!/usr/bin/env python3
"""Use the library the way the roles above it are meant to use it, and keep the record.

A build record that only counts claims says what was written and nothing about what the
library is FOR. This script drives the example's own API — the browsing layer's `console`
profile, on this project's ports — through one pass of every use-side mechanism the
framework grew after the first build, and writes down what came back:

  * consultations by visitor class — `business`, `audit`, `silent` — so the ledger, the
    access statistics and the spend report are real rows a developer can open, not claims
    in a README;
  * one `owner-dialogue/v1` statement from 林舟, which the compile turns into a correction
    or a supersession under the contract, citing the statement;
  * one Live Context session over a short synthetic conversation, whose spend is on the
    tick or nowhere.

Everything it says is synthetic, like the corpus. Run it with the stack and the console
profile up, after the library is compiled:

    docker compose --profile console up -d --wait api worker web
    ./build-record/exercise.py            # writes build-record/use-side/
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
OUT = HERE / "use-side"
sys.path.insert(0, str(PROJECT))
import app as driver  # noqa: E402 — the project's own driver, for .env and the tenant id


# ── the questions ────────────────────────────────────────────────────────────────────────
# Real questions about Seamlog, derived from the material, one per thing a reader of this
# library actually comes back for (the contract's §0 list). The last business question is
# one the material genuinely never answers: a miss is the other half of an access ledger,
# and a library that never records what it was asked for and did not have cannot report it.

BUSINESS = [
    ("fast", "第一条证据链现在卡在什么条件上？"),
    ("fast", "3 月 10 日吴岚允许我用副本做什么，明确不包括什么？"),
    ("deep", "为什么砍掉自动周报？谁质疑的，依据是什么？"),
    ("fast", "六周延长卡在哪几件事，各自在等谁？"),
    ("fast", "680 元这个数字是怎么来的，覆盖什么？"),
    ("fast", "Seamlog 的安卓客户端是哪个版本上线的？"),
]
AUDIT = [("deep", "同姓记录错误关联事故，从发现到恢复只读依次发生了什么？")]
SILENT = [
    ("fast", "4 月 22 日的报价不包含什么？"),
    ("fast", "删除演练还差哪一格没确认？"),
    ("fast", "孙秋的红线批注能替客户下结论吗？"),
]

# ── the owner's statement ────────────────────────────────────────────────────────────────
# 林舟 speaking to his own library: the world moved on, so the claim that the balance is
# outstanding is no longer true — and the successor has to cite this statement. Written as
# a dialogue because that is what the contract is: turns, roles, aware timestamps, verbatim.

OWNER_DIALOGUE = {
    "schema": "pneuma.source.owner-dialogue/v1",
    "provider": "console",
    "dialogue_id": "dlg-2026-09-01-weikuan",
    "owner_id": "lin-zhou",
    "steward_id": "seamlog-steward",
    "turns": [
        {
            "turn_id": "t1",
            "role": "owner",
            "said_at": "2026-09-01T10:12:00+08:00",
            "text": (
                "尾款到了。采购 8 月 28 日付的，到账日 8 月 29 日，金额 5400 元，"
                "付款说明写的是「云麓受限试点尾款」，我这边看到的是银行流水第 4 行。"
                "库里记着尾款未到、只有「在内部流程」这句话——那是 5 月 24 日的状态，"
                "现在不成立了。"
            ),
        },
        {
            "turn_id": "t2",
            "role": "steward",
            "said_at": "2026-09-01T10:12:20+08:00",
            "text": "明白。这算世界变了，不是当时记错了——我去取代那一条，并引用你这段话。",
        },
        {
            "turn_id": "t3",
            "role": "owner",
            "said_at": "2026-09-01T10:13:05+08:00",
            "text": (
                "对，5 月 24 日那条在它的时点上是对的，别改它。另外说清楚：到账的只有尾款，"
                "六周延长的附录签字和删除演练那两项，采购一句都没提，仍然是没答复。"
            ),
        },
    ],
    "metadata": {"channel": "console", "synthetic": True},
}

# ── the live conversation ────────────────────────────────────────────────────────────────
# Three turns of a synthetic working conversation, eager: the density that asks whether the
# library has something to say on nearly every turn.

LIVE_TURNS = [
    {"speaker": "林舟", "role": "owner", "text": "竹影那边刚问附录还差什么才能签。"},
    {"speaker": "贾宁", "role": "other", "text": "红线版不是早就发过去了吗？"},
    {
        "speaker": "林舟",
        "role": "owner",
        "text": "发过去不等于签。删除演练那边也还没有一格是能确认的。",
    },
]


def base_url() -> str:
    port = driver.stack_port("PNEUMA_APP_API_PORT", 28000)
    return f"http://127.0.0.1:{port}"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


async def ask(client, uid: str, mode: str, question: str, visitor_class: str) -> dict:
    response = await client.post(
        f"/v1/users/{uid}/recall",
        json={"query": question, "mode": mode, "visitor_class": visitor_class},
        timeout=600.0,
    )
    response.raise_for_status()
    body = response.json()
    return {
        "visitor_class": visitor_class,
        "mode": mode,
        "question": question,
        "answer": body.get("answer", ""),
        "answer_kind": body.get("answer_kind"),
        "citations": body.get("citations", []),
        "token_usage": body.get("token_usage"),
        "cost": body.get("cost"),
    }


async def wait_for_jobs(client, uid: str, *, kinds: tuple[str, ...], seconds: float = 900.0):
    """Poll until this tenant has no queued or claimed job of the named kinds."""
    waited = 0.0
    while waited < seconds:
        response = await client.get(f"/v1/users/{uid}/jobs", params={"limit": 100})
        response.raise_for_status()
        jobs = response.json().get("items", [])
        pending = [
            j for j in jobs if j.get("kind") in kinds and j.get("status") not in ("done",)
        ]
        if not pending:
            return jobs
        await asyncio.sleep(5.0)
        waited += 5.0
    raise TimeoutError(f"jobs of kind {kinds} did not finish within {seconds}s")


async def live_session(uid: str, port: int) -> list[dict]:
    """One Live Context session over the socket, eager, telemetry on.

    `quiet_period: 0` makes every turn a tick — this is a record, not a demonstration of
    the throttle. Frames are captured verbatim; the session ends by closing the socket,
    because there is no goodbye frame and a listener leaves nothing behind but this log.
    """
    import websockets

    frames: list[dict] = []
    url = f"ws://127.0.0.1:{port}/v1/users/{uid}/live-context/ws"
    async with websockets.connect(url, max_size=8 * 1024 * 1024) as socket:
        frames.append(json.loads(await socket.recv()))  # ready
        await socket.send(
            json.dumps(
                {
                    "type": "config",
                    "density": "eager",
                    "quiet_period": 0,
                    "stats": True,
                    "focus": "general",
                }
            )
        )
        frames.append(json.loads(await socket.recv()))  # ready, echoing the policy
        for turn in LIVE_TURNS:
            await socket.send(json.dumps({"type": "turn", **turn}))
            # Evaluate this turn now rather than waiting out a quiet period: a record wants
            # one tick per turn, not the throttle's judgement about when a pause is real.
            await socket.send(json.dumps({"type": "flush"}))
            while True:
                try:
                    frame = json.loads(await asyncio.wait_for(socket.recv(), timeout=120.0))
                except asyncio.TimeoutError:
                    break
                if frame.get("type") == "ping":
                    continue
                frames.append(frame)
                if frame.get("type") == "stats":  # the tick is over, whatever it delivered
                    break
    return frames


async def main() -> int:
    import httpx

    uid = driver.user_id()
    OUT.mkdir(parents=True, exist_ok=True)
    record: dict = {"ran_at": now(), "user_id": uid, "api": base_url()}

    async with httpx.AsyncClient(base_url=base_url(), timeout=120.0) as client:
        health = await client.get("/healthz")
        health.raise_for_status()

        print("== consultations ==")
        record["consultations"] = []
        for group, visitor_class in ((BUSINESS, "business"), (AUDIT, "audit"), (SILENT, "silent")):
            for mode, question in group:
                answer = await ask(client, uid, mode, question, visitor_class)
                record["consultations"].append(answer)
                print(f"  [{visitor_class}/{mode}] {question}  → {answer['answer_kind']}")

        # The projection lags its consultation by the queue's drain; the ledger is only
        # honest once the jobs a business visitor enqueued have actually run.
        print("== waiting for the projection jobs ==")
        await wait_for_jobs(client, uid, kinds=("recall_projection",))

        for name, path, params in (
            ("ledger", f"/v1/users/{uid}/consultations", {"limit": 50}),
            ("spend", f"/v1/users/{uid}/consultations/spend", {"days": 30}),
            ("access_top", f"/v1/users/{uid}/access-stats/top", {"days": 30, "limit": 15}),
        ):
            response = await client.get(path, params=params)
            response.raise_for_status()
            record[name] = response.json()
        print(
            f"  ledger: {record['ledger']['page']['total']} recorded consultation(s); "
            f"spend: {record['spend']['cost']}"
        )

        print("== the owner's statement ==")
        response = await client.post(f"/v1/users/{uid}/sources/import", json=OWNER_DIALOGUE)
        response.raise_for_status()
        record["owner_dialogue"] = {"payload": OWNER_DIALOGUE, "import": response.json()}
        print(f"  imported: {record['owner_dialogue']['import']}")
        await wait_for_jobs(client, uid, kinds=("index", "compile"), seconds=1800.0)
        response = await client.get(f"/v1/users/{uid}/history", params={"kind": "patch", "limit": 5})
        response.raise_for_status()
        history = response.json()
        record["owner_dialogue"]["history"] = history
        verbs = [
            claim.get("type")
            for item in history.get("items", [])
            for claim in (item.get("payload") or {}).get("claims", [])
        ]
        print(f"  what the compile did with it: {sorted(set(verbs))}")

        # The verb is not the point; the citation is. A supersession whose successor does
        # not rest on the statement would be the compile taking the owner's word for it,
        # which is the one thing the gate exists to refuse.
        dialogue_sid = record["owner_dialogue"]["import"]["sources"][0]["source_id"]
        response = await client.get(f"/v1/users/{uid}/dataset", params={"audit": "false"})
        response.raise_for_status()
        pages = (response.json().get("documents") or {}).get("documents", [])
        touched = [
            {
                "path": page.get("path"),
                "body": page.get("body", ""),
                "supersedes": "supersedes: c:" in page.get("body", ""),
                "cites_the_statement": dialogue_sid[:8] in page.get("body", ""),
            }
            for page in pages
            if "supersedes: c:" in page.get("body", "") or dialogue_sid[:8] in page.get("body", "")
        ]
        record["owner_dialogue"]["source_id"] = dialogue_sid
        record["owner_dialogue"]["pages"] = touched
        for page in touched:
            print(
                f"  {page['path']}: supersession={page['supersedes']} "
                f"cites-the-statement={page['cites_the_statement']}"
            )

        print("== live context ==")
        record["live_context"] = await live_session(
            uid, driver.stack_port("PNEUMA_APP_API_PORT", 28000)
        )
        print(f"  {len(record['live_context'])} frame(s) captured")

        response = await client.get(f"/v1/users/{uid}/jobs", params={"kind": "compile", "limit": 100})
        response.raise_for_status()
        record["compile_jobs"] = response.json()
        # What the ledger made of the ten questions, in its own words rather than the
        # client's: which were recorded at all, and which the library reported it could
        # not answer.
        response = await client.get(f"/v1/users/{uid}/consultations", params={"limit": 50})
        response.raise_for_status()
        record["ledger"] = response.json()

    (OUT / "session.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\nwrote {OUT / 'session.json'}")
    return 0


def _reexec_through_the_framework_env() -> None:
    """Re-exec THIS file through the framework repository's uv environment when httpx and
    websockets are not importable — the driver's own version re-execs `app.py`."""
    import os

    try:
        import httpx  # noqa: F401
        import websockets  # noqa: F401

        return
    except ModuleNotFoundError:
        pass
    if os.environ.get("PNEUMA_APP_REEXEC") == "1":
        sys.exit("error: httpx/websockets still missing after the uv re-exec.")
    repo = driver.find_framework_repo()
    if repo is None:
        sys.exit("error: framework repository not found. Set PNEUMA_APP_FRAMEWORK_REPO in .env.")
    os.environ["PNEUMA_APP_REEXEC"] = "1"
    os.execvpe(
        "uv",
        ["uv", "run", "--project", str(repo), "python", str(Path(__file__).resolve()), *sys.argv[1:]],
        os.environ,
    )


if __name__ == "__main__":
    driver.load_env_file(PROJECT / ".env")
    _reexec_through_the_framework_env()
    raise SystemExit(asyncio.run(main()))
