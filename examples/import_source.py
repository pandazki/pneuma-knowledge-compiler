#!/usr/bin/env python
"""Import one real provider source or canonical mock contract into a user tenant."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import _bootstrap  # noqa: F401

from pneuma_knowledge_core.domain.ids import UserId
from pneuma_knowledge_service.adapters.source_imports import (
    CanonicalJsonSourceAdapter,
    ObsidianVaultAdapter,
    Rfc822EmailAdapter,
    SlackExportAdapter,
    ZoomVttAdapter,
)
from pneuma_knowledge_service.ingest_sources import ingest_source_contract
from pneuma_knowledge_service.settings import Settings
from pneuma_knowledge_service.wiring import build_context


def _contract(args):
    source = Path(args.source)
    if args.provider == "mock":
        return CanonicalJsonSourceAdapter().load(source)
    if args.provider == "obsidian":
        return ObsidianVaultAdapter().load(
            source, library_id=args.library_id, title=args.title
        )
    if args.provider == "slack":
        return SlackExportAdapter().load(
            source, owner_user_ids=set(args.owner_user_id)
        )
    if args.provider == "email":
        return Rfc822EmailAdapter().load(
            source, owner_addresses=set(args.owner_address)
        )
    if args.provider == "zoom":
        if not args.metadata:
            raise ValueError("--metadata is required for the Zoom adapter")
        return ZoomVttAdapter().load(
            Path(args.metadata),
            source,
            owner_emails=set(args.owner_address),
            owner_participant_ids=set(args.owner_user_id),
        )
    raise ValueError(f"unsupported provider: {args.provider}")


async def run(args) -> int:
    contract = _contract(args)
    ctx = await build_context(Settings())
    try:
        result = await ingest_source_contract(ctx, UserId(args.user), contract)
        print(f"contract={result.contract_schema} units={len(result.sources)}")
        for item in result.sources:
            state = "deduplicated" if item.deduplicated else "queued"
            print(f"  {state:12} {item.source_id}")
    finally:
        await ctx.aclose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Translate a provider source to a canonical contract and enqueue it."
    )
    parser.add_argument(
        "provider", choices=["mock", "zoom", "obsidian", "slack", "email"]
    )
    parser.add_argument(
        "source",
        help="JSON/VTT/vault/export/email path, depending on provider",
    )
    parser.add_argument("--user", required=True, help="target user tenant")
    parser.add_argument("--metadata", help="Zoom recording metadata JSON")
    parser.add_argument("--library-id", help="stable Obsidian library id")
    parser.add_argument("--title", help="Obsidian library title")
    parser.add_argument("--owner-user-id", action="append", default=[])
    parser.add_argument("--owner-address", action="append", default=[])
    args = parser.parse_args()
    try:
        return asyncio.run(run(args))
    except ValueError as exc:
        parser.error(str(exc))
    return 2


if __name__ == "__main__":
    sys.exit(main())
