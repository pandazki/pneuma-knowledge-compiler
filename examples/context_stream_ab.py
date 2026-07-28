#!/usr/bin/env python
"""Synthetic A/B for the public `context_stream` source type.

A fictional OPC developer's release-planning fragment is ingested twice: once as generic
`upload`, once as `context_stream`. Content, skill and configured model are identical; only
the source type differs. This is a mechanism smoke, not a benchmark or effectiveness claim.

Review properties instead of exact wording:
  · the owner's publication commitment stays attributed to the owner;
  · a proposal and a participant's tentative response do not become a decided feature;
  · the owner's question does not become a fact;
  · an unresolved team-permissions request stays unresolved;
  · filler and background noise do not become knowledge.

Prereqs: `.env` with OPENROUTER_API_KEY + the compose stack up
(`docker compose -f infra/docker-compose.yml up -d --wait`). Idempotent: re-runs dedup by
checksum and just re-print the canonical.

    uv run python examples/context_stream_ab.py                # the real-LLM A/B
    uv run python examples/context_stream_ab.py --show-prompt  # keyless: render the compile prompt

See docs/first-party-context-stream.md for the full re-test guide.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

# Must precede every pneuma_knowledge import: pins the localhost proxy bypass before any
# middleware client is constructed. See _bootstrap.py.
import _bootstrap  # noqa: F401  (import for side effect)

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.domain.source import ConversationTurn
from pneuma_knowledge_core.skill import load_builtin_skill
from pneuma_knowledge_service.ingest import ingest_conversation
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context
from pneuma_knowledge_service.workers.compile_worker import drain_user

U_BASE = UserId("u-opc-context-base")
U_CONV = UserId("u-opc-context-first-party")

# (diarization channel, text). `self/*` = the owner's mic; `others/*` = interlocutors.
FIXTURE: list[tuple[str, str]] = [
    ("others/1", "Atlas 的公开仓库今天能发吗？"),
    ("self/1", "我明天完成许可证扫描后发布仓库，这件事我来做。"),
    ("others/2", "呃……[键盘声]"),
    ("self/1", "首版也许只保留本地导出，云同步先不做。"),
    ("others/1", "可以，先按这个方向看看。"),
    ("self/2", "等等，合成评测集已经固定版本了吗？"),
    ("others/1", "还有人提了团队权限，但我们没有决定是否进入 MVP。"),
    ("others/2", "啊啊……听不清。"),  # noise / cross-talk
    ("others/1", "生产构建已经通过，README 的恢复路径还需要补一段。"),
    ("self/1", "我今晚补 README，发布仍以许可证扫描通过为前提。"),
]


def _turns() -> list[ConversationTurn]:
    at = datetime(2026, 6, 30, 14, tzinfo=timezone.utc)
    # speaker carries the diarization channel; role is left unknown so BOTH variants take
    # the same input — the context_stream type's load() types the role from `self/others`.
    return [ConversationTurn(speaker=ch, text=t, at=at) for ch, t in FIXTURE]


async def build(ctx, user: UserId, origin: str) -> None:
    await ingest_conversation(ctx, user, _turns(), title="Atlas 开源发布复盘", origin=origin)
    n = await drain_user(ctx, ctx.get_chat_model("compile"), load_builtin_skill(), user)
    print(f"  {user}: drained {n} job(s)")


async def dump(ctx, user: UserId, label: str) -> None:
    docs = await ctx.canonical.list(user)
    claims = await ctx.store.list_canonical_claims(user)
    print(f"\n{'='*72}\n[{label}]  {user} — {len(docs)} doc(s), {len(claims)} claim(s)\n{'='*72}")
    if not docs:
        print("  (compile committed nothing — the owner's memory was not extracted)")
    for d in docs:
        print(f"\n----- {d.path} -----\n{d.body.strip()[:1800]}")


def show_prompt() -> int:
    """Keyless: render the ACTUAL compile prompt the context_stream type produces (system
    write-contract + skill + the per-source first-party guidance + owner/other blocks),
    with NO model call. Inspect the layout instead of imagining it from the code."""
    from datetime import timezone as _tz

    from pneuma_knowledge_core.compile.runner import _render_task
    from pneuma_knowledge_core.domain.ids import SourceId
    from pneuma_knowledge_core.domain.source import RawSource
    from pneuma_knowledge_core.ingest.adapters import CONTEXT_STREAM_MIME
    from pneuma_knowledge_core.ingest.source_types import ContextStreamSourceType
    from pneuma_knowledge_core.skill.contract import render_system_contract

    raw = RawSource(
        source_id=SourceId("opc-context-demo"), user_id=UserId("u-opc-demo"),
        kind="conversation", origin="context_stream", title="Atlas 开源发布复盘",
        mime=CONTEXT_STREAM_MIME, checksum="c",
        created_at=datetime(2026, 6, 30, tzinfo=_tz.utc),
    )
    ct = ContextStreamSourceType()
    norm = ct.format(raw, ct.load(_turns()))
    print("###### SYSTEM MESSAGE (write-contract + skill) — head ######")
    print("\n".join(render_system_contract(load_builtin_skill()).splitlines()[:20]))
    print("\n###### HUMAN MESSAGE (per-source first-party guidance + blocks) ######")
    print(_render_task([norm], [], treatments={"opc-context-demo": "full"},
                       source_guidance={"opc-context-demo": ct.compile_guidance().render()}))
    return 0


async def main() -> int:
    # `show_prompt` is pure string rendering (no I/O, no model call), so it stays sync and
    # returns before any adapter/event-loop resource is built.
    if "--show-prompt" in sys.argv[1:]:
        return show_prompt()
    ctx = await build_context(Settings())
    try:
        print("== BASELINE compile (generic upload: `self/1:` verbatim, no guidance) ==")
        await build(ctx, U_BASE, "upload")
        print("== CONTEXT_STREAM compile (first-party type: owner/other + guidance) ==")
        await build(ctx, U_CONV, "context_stream")
        await dump(ctx, U_BASE, "BASELINE")
        await dump(ctx, U_CONV, "CONTEXT_STREAM")
        print("\nRead the two canonicals against the PROPERTIES in this file's docstring — "
              "not for byte-identical text.")
    finally:
        await ctx.aclose()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
