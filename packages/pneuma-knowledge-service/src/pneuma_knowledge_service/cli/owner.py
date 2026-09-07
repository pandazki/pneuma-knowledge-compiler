"""`pkc owner say` — owner speech, and the only shape it has (§5.3, ruling 7).

Every correction, refiling, alias and statement of state the Owner makes enters as an
`owner-dialogue/v1` source and is compiled like any other source. There is no command that
changes a claim without a job, and the absence is the mechanism: what the Owner says is
evidence, and evidence is cited, not applied.

One command, one effect. It builds the payload, validates it through the SAME contract the
HTTP import validates against, and imports it through the SAME function
(`ingest_sources.ingest_source_contract`) — so the source id is content-stable, a repeated
statement deduplicates, and L0 + index + compile follow the contract's own intake.

`--about` is a hint and says so: the paths ride the compile job's payload and are rendered
into the round's source guidance (`compile.task.about_pages`). It points the round at the
pages the statement concerns; it changes nothing about what the gate requires there.

**The verbatim check (ruling 13).** Inside the console's Steward view the bridge holds what
the Owner typed and hands the session id down on `PNEUMA_KNOWLEDGE_STEWARD_SESSION`. When
that variable is set this command loads the session's Owner turns and REFUSES a text that is
not a verbatim substring of one of them, whitespace-normalized: a summary of what the Owner
meant is not what the Owner said, and the difference is the only thing this check is for.
Outside a bridge — a terminal session the Owner opened themselves — there is no transcript to
check against and the command behaves exactly as it always did. The library's honesty does not
rest on the check; only the Owner's words do.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, TextIO

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract

from ..coding_agent.steward_turns import SESSION_ENV, is_verbatim

EXIT_OK = 0
EXIT_REFUSED = 2

#: What the refusal says. It names the rule rather than the fix, because there is only one
#: fix: record what the Owner actually typed.
NOT_VERBATIM = (
    "refused: inside a console Steward session, `owner say` records the OWNER's words. "
    "This text is not a verbatim substring of anything the owner typed in this session "
    "(whitespace aside), and a paraphrase of the owner is not the owner's statement. "
    "Quote them, or ask them to say it."
)

#: The contract's own `provider` values. `console` is the browser's Steward view; a terminal
#: is neither, and `mock` is the honest label for "assembled by hand outside a provider".
CLI_PROVIDER = "mock"


def build_owner_dialogue(
    *,
    user_id: UserId,
    text: str,
    said_at: datetime | None = None,
    dialogue_id: str | None = None,
) -> dict[str, Any]:
    """One owner turn carrying `text` VERBATIM, as an `owner-dialogue/v1` payload.

    Trailing newline only — a shell heredoc adds one and nobody typed it. Nothing else is
    touched: leading whitespace, internal blank lines and a trailing space are all things the
    Owner may have meant, and a normalizer that decides otherwise is deciding what someone
    said.
    """
    when = said_at or datetime.now(timezone.utc)
    body = text.rstrip("\n")
    # DERIVED from the statement and the instant, never random: idempotency in this system is
    # content identity (§5.4), and a random id would make a command retried after a failed
    # import record the same statement twice. The same words said again at a different
    # instant are a different statement, and get a different id — which is right, because
    # they were said again.
    minted = hashlib.sha256(f"{when.isoformat()}\n{body}".encode()).hexdigest()[:16]
    return {
        "schema": "pneuma.source.owner-dialogue/v1",
        "provider": CLI_PROVIDER,
        "dialogue_id": dialogue_id or f"owner-say-{minted}",
        "owner_id": str(user_id),
        "turns": [
            {
                "turn_id": "t1",
                "role": "owner",
                "said_at": when.isoformat(),
                "text": body,
            }
        ],
    }


async def cmd_owner_say(
    ctx: Any,
    user_id: UserId,
    *,
    text: str,
    about: list[str] | None = None,
    said_at: str | None = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """Record the statement and enqueue its compile. Returns the exit code."""
    out = out or sys.stdout
    err = err or sys.stderr
    session_id = steward_session()
    if session_id and not await owner_said(ctx, user_id, session_id, text):
        print(NOT_VERBATIM, file=err)
        return EXIT_REFUSED
    when = datetime.fromisoformat(said_at) if said_at else None
    payload = build_owner_dialogue(user_id=user_id, text=text, said_at=when)
    try:
        # Validated at the contract, before anything is written — a blank statement is
        # refused in the contract's own words (`a turn nobody spoke is not a turn`), which is
        # the only place that sentence exists.
        contract = parse_source_contract(payload)
    except Exception as exc:  # noqa: BLE001 — a validation error is the refusal
        print(str(exc), file=err)
        return EXIT_REFUSED

    from ..ingest_sources import ingest_source_contract

    paths = [str(p).strip() for p in (about or []) if str(p).strip()]
    result = await ingest_source_contract(ctx, user_id, contract, about_paths=paths)
    body = {
        "contract_schema": result.contract_schema,
        "sources": [
            {"source_id": str(i.source_id), "deduplicated": i.deduplicated}
            for i in result.sources
        ],
        "about": paths,
        "compile_jobs": list(result.compile_jobs),
    }
    if as_json:
        print(json.dumps(body, ensure_ascii=False, indent=2), file=out)
    else:
        for item in result.sources:
            print(
                f"source {item.source_id}"
                + ("  (already recorded)" if item.deduplicated else ""),
                file=out,
            )
        for job_id in result.compile_jobs:
            print(f"compile job {job_id}", file=out)
        if not result.compile_jobs:
            print(
                "no compile job — this statement is already in the library",
                file=out,
            )
    return EXIT_OK


def steward_session() -> str:
    """The console Steward session this process was started inside, or `""` in a terminal.

    One reading of one variable, in one place, because two doors now depend on it: `owner
    say` and an archive note (`cli/archive.py`) are both the Owner's words recorded by the
    Steward, and a check that lived in only one of them would be a rule with a way around it.
    """
    return str(os.environ.get(SESSION_ENV) or "").strip()


async def owner_said(
    ctx: Any, user_id: UserId, session_id: str, text: str
) -> bool:
    """Did the Owner type this, in this console session? (ruling 13.)

    A transcript that cannot be read is not a licence to skip the check: a bridged session
    whose store is unreachable refuses, because the alternative is a rule that switches
    itself off exactly when it cannot be enforced.
    """
    store = getattr(ctx, "steward_turns", None)
    if store is None:
        return False
    turns = await store.list(user_id, session_id)
    return is_verbatim(text, list(turns))
