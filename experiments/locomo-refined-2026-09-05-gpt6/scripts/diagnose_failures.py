#!/usr/bin/env python3
"""Read-only infrastructure error tags; no arbitrary job detail reaches output."""
import asyncio
import json
import sys
from runtime import ROOT, atomic, utc
from snapshot import app_module


async def main(i):
    app = app_module(i)
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.wiring import build_context
    skill = app.load_contract_skill()
    ctx = await build_context(app.build_settings(base_version=skill.version))
    try:
        jobs = await ctx.store.list_jobs(UserId(app.user_id()))
        rows = []
        patterns = {
            'insufficient_credits': ['insufficient credits', 'insufficient credit'],
            'credit_limit': ['credit limit', 'credits required'],
            'rate_limit': ['rate limit', 'ratelimiterror'],
            'authentication': ['authenticationerror', 'invalid api key'],
            'timeout': ['timeouterror', 'timed out', 'timeout'],
            'connection': ['apiconnectionerror', 'connection refused', 'connection reset'],
            'http_402': ['error code: 402', 'status code: 402', '402 payment required'],
            'http_429': ['error code: 429', 'status code: 429', '429 too many'],
            'http_500': ['error code: 500', 'status code: 500'],
            'http_502': ['error code: 502', 'status code: 502'],
            'http_503': ['error code: 503', 'status code: 503'],
            'http_504': ['error code: 504', 'status code: 504'],
        }
        for job in jobs:
            if job.get('ok') is not False:
                continue
            detail = str(job.get('detail') or '').lower()
            rows.append({'job_id': str(job['job_id']), 'kind': str(job.get('kind')),
                         'tags': [name for name, terms in patterns.items() if any(t in detail for t in terms)]})
        result = {'utc': utc(), 'conversation_idx': i, 'failed_jobs': rows}
        atomic(ROOT / f'build-record/infrastructure-errors-{i:02d}.json', result)
        print(json.dumps(result))
    finally:
        await ctx.aclose()


if __name__ == '__main__':
    asyncio.run(main(int(sys.argv[1])))
