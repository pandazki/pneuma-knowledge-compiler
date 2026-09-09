"""`pkc ingest` — the CLI face of `/sources/import` (§5.4).

The whole input boundary, and it is enough: what arrives shaped as one of the six contracts
is the framework's business, and how it came to be shaped is the Steward's. Everything
upstream — fetching, transforming, scheduling — lives in the project under `steward/` and
never touches `data/` or canonical (ruling 11).

Same validation, same import function, same intake override, same answer as the route. The
one thing this face adds is the refusal a route gets for free from its path: an unknown
contract is named and rejected BEFORE the payload is read, because "which of the six is
this" is a question about the argument and not about the file.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_core.ingest.source_contracts import parse_source_contract

EXIT_OK = 0
EXIT_REFUSED = 2

#: The six versioned provider-neutral contracts, by the name a caller types and the
#: `schema` value the payload must carry. The framework's input boundary IS this table
#: (docs/reference/source-contracts.md); a new entry is a framework change and a new
#: upstream is not.
CONTRACTS = {
    "meeting/v1": "pneuma.source.meeting/v1",
    "document-library/v1": "pneuma.source.document-library/v1",
    "im/v1": "pneuma.source.im/v1",
    "email/v1": "pneuma.source.email/v1",
    "owner-dialogue/v1": "pneuma.source.owner-dialogue/v1",
    "agent-session/v1": "pneuma.source.agent-session/v1",
}


async def cmd_ingest(
    ctx: Any,
    user_id: UserId,
    *,
    contract_name: str,
    payload_text: str,
    intake: str | None = None,
    as_json: bool = False,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    out = out or sys.stdout
    err = err or sys.stderr
    schema = CONTRACTS.get(str(contract_name or "").strip())
    if schema is None:
        print(
            f"unknown contract {contract_name!r} — the six are: "
            + ", ".join(sorted(CONTRACTS)),
            file=err,
        )
        return EXIT_REFUSED
    try:
        payload = json.loads(payload_text)
    except ValueError as exc:
        print(f"the payload is not JSON: {exc}", file=err)
        return EXIT_REFUSED
    declared = str((payload or {}).get("schema") or "")
    if declared and declared != schema:
        print(
            f"this payload declares {declared!r}, not {schema!r} — "
            "`--contract` names which of the six it is, and the two must agree",
            file=err,
        )
        return EXIT_REFUSED
    if isinstance(payload, dict):
        payload.setdefault("schema", schema)
    try:
        parsed = parse_source_contract(payload)
    except Exception as exc:  # noqa: BLE001 — a validation error is the refusal
        print(str(exc), file=err)
        return EXIT_REFUSED

    from ..ingest_sources import ingest_source_contract

    try:
        result = await ingest_source_contract(
            ctx, user_id, parsed, intake_archetype=intake or None
        )
    except ValueError as exc:
        # `plan_for_archetype` refuses an unknown name; that is an argument error, not a
        # failed import, and nothing was written before it raised.
        print(str(exc), file=err)
        return EXIT_REFUSED
    body = {
        "contract_schema": result.contract_schema,
        "sources": [
            {
                "source_id": str(i.source_id),
                "intake_plan": i.intake_plan.model_dump(),
                "deduplicated": i.deduplicated,
            }
            for i in result.sources
        ],
        "compile_jobs": list(result.compile_jobs),
    }
    if as_json:
        print(json.dumps(body, ensure_ascii=False, indent=2), file=out)
    else:
        for item in body["sources"]:
            print(
                f"source {item['source_id']}"
                + ("  (already recorded)" if item["deduplicated"] else ""),
                file=out,
            )
        for job_id in body["compile_jobs"]:
            print(f"compile job {job_id}", file=out)
    return EXIT_OK

