#!/usr/bin/env python
"""Preprocess canonical speech terms with deployment environment variables.

uv run python scripts/ops/build_speech_lexicon.py USER --model openrouter:openai/gpt-6-luna
Use --dry-run to inspect the read budget; --confusion 'Canonical=misheard' adds an explicit
operator spelling hint. This writes only a derived cache, never canonical frontmatter.
"""
import argparse
import asyncio
import json

from pneuma_knowledge_service.settings import get_settings
from pneuma_knowledge_service.engine.contract import bootstrap_engine
from pneuma_knowledge_service.wiring import build_context, _build_from_name
from pneuma_knowledge_service.call.librarian import LibraryLibrarian
from pneuma_knowledge_service.call.speech_lexicon import rebuild, cache_path
from pneuma_knowledge_core.recall.speech_lexicon import chunks, live_documents, spelling


async def main(args):
    settings = get_settings()
    bootstrap_engine(settings)
    ctx = await build_context(settings, probe_agent=False, probe_embedding=False, apply_schema=False)
    try:
        librarian = LibraryLibrarian(ctx, args.user)
        documents = live_documents((await librarian._inputs()).get("documents") or [])
        print(json.dumps({"documents": len(documents), "chunks": sum(sum(1 for _ in chunks(d)) for d in documents),
                          "body_characters": sum(len(d.body) for d in documents)}, ensure_ascii=False), flush=True)
        if args.dry_run:
            return
        confusions = None
        if args.confusion:
            confusions = {}
            for value in args.confusion:
                term, separator, alias = value.partition("=")
                if not separator or not spelling(term) or not spelling(alias):
                    raise ValueError("confusion must be a bounded Canonical=misheard pair")
                confusions.setdefault(term, []).append(alias)
        model = _build_from_name(args.model, settings, reasoning_effort="none", max_tokens=2500)
        data = await rebuild(settings, args.user, documents, model, model_name=args.model, confusions=confusions,
                             on_progress=lambda path, n: print(json.dumps({"page": path, "terms": n}), flush=True))
        from pneuma_knowledge_service.call.speech_activity import refresh_activity
        await refresh_activity(settings, args.user, documents, ctx.store, force=True)
        print(json.dumps({"cache": str(cache_path(settings, args.user)), "pages": len(data['documents']),
                          "failures": data['failures']}, ensure_ascii=False), flush=True)
        if data["failures"]:
            raise SystemExit(1)
    finally:
        await ctx.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("user")
    parser.add_argument("--model", default="openrouter:openai/gpt-6-luna")
    parser.add_argument("--confusion", action="append")
    parser.add_argument("--dry-run", action="store_true")
    asyncio.run(main(parser.parse_args()))
