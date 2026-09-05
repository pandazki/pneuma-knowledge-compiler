#!/usr/bin/env python3
"""Post-score read-only count audit; emits no source, question, or job detail text."""
import asyncio
import collections
import json
import re
import subprocess
import sys
from runtime import ROOT, PYTHON, atomic, command, env_for, safe_log, utc
from snapshot import app_module


async def inspect(i):
    assert (ROOT / 'state/scores-landed.json').exists(), 'Scoring firewall is closed'
    app = app_module(i)
    from pneuma_knowledge_core.domain.ids import UserId
    from pneuma_knowledge_service.wiring import build_context
    skill = app.load_contract_skill()
    ctx = await build_context(app.build_settings(base_version=skill.version))
    try:
        user = UserId(app.user_id())
        jobs = await ctx.store.list_jobs(user)
        tasks = await ctx.store.list_evolve_tasks(user)
        consultations = await ctx.store.list_consultations(user, limit=10000)
        assert len(consultations) < 10000, 'Consultation audit needs pagination'
        challenge = []
        for job in jobs:
            if job.get('kind') != 'challenge':
                continue
            detail = job.get('detail') or ''
            try:
                data = json.loads(detail)
            except (ValueError, TypeError):
                data = {}
            degraded = data.get('degraded')
            match = re.match(r'^([A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception)):', str(degraded))
            challenge.append({
                'job_id': str(job['job_id']),
                'rounds': int(data.get('rounds', 0)),
                'questions': int(data.get('questions', 0)),
                'gaps': len(data.get('gaps', [])),
                'compensation_enqueued': data.get('compensation_enqueued') is True,
                'exhausted': data.get('exhausted') is True,
                'degraded': bool(degraded),
                'degraded_class': match[1] if match else None,
                'detail_parsed': bool(data),
            })
        statuses = {'no_change', 'aborted', 'draft', 'adopted', 'dropped', 'expired'}
        unresolved = app._unresolved_failures(jobs)
        incident = ROOT / f'build-record/infrastructure-errors-{i:02d}.json'
        original_402_ids = set()
        if incident.exists():
            original_402_ids = {j['job_id'] for j in json.loads(incident.read_text())['failed_jobs'] if 'http_402' in j['tags']}
        assert original_402_ids <= {str(j['job_id']) for j in jobs}, 'Historical provider failures must remain auditable'
        result = {
            'utc': utc(), 'conversation_idx': i,
            'job_counts': dict(collections.Counter(str(j.get('kind')) for j in jobs)),
            'historical_failed_jobs': sum(j.get('ok') is False for j in jobs),
            'pending': sum(j.get('status') != 'done' for j in jobs),
            'unresolved': len(unresolved),
            'historical_http402_jobs_retained': len(original_402_ids),
            'http402_jobs_still_unresolved': len(original_402_ids & {str(j['job_id']) for j in unresolved}),
            'evolve_status_counts': dict(collections.Counter(t['status'] if t['status'] in statuses else 'other' for t in tasks)),
            'evolve_proposals': sum(bool(t.get('proposal')) for t in tasks),
            'evolve_dropped_items': sum(len(t.get('dropped') or []) for t in tasks),
            'challenge': challenge,
            'consultation_records': len(consultations),
            'business_consultation_records': sum(c.visitor_class == 'business' for c in consultations),
        }
        atomic(ROOT / f'build-record/post-score-audit-{i:02d}.json', result)
        print(json.dumps({'conversation_idx': i, 'audit_complete': True}))
    finally:
        await ctx.aclose()


def main():
    assert (ROOT / 'state/scores-landed.json').exists(), 'Scoring firewall is closed'
    if len(sys.argv) == 2:
        asyncio.run(inspect(int(sys.argv[1])))
        return
    for i in range(10):
        if (ROOT / f'build-record/post-score-audit-{i:02d}.json').exists():
            continue
        command(i, ['up'], 'post-score-audit-up')
        try:
            result = subprocess.run([PYTHON, __file__, str(i)], env=env_for(i), capture_output=True, text=True)
            safe_log(ROOT / f'logs/post-score-audit-{i:02d}.log', result.stdout + '\n' + result.stderr, result.returncode)
            if result.returncode:
                raise RuntimeError('Post-score audit failed; consult sanitized error class')
        finally:
            command(i, ['down'], 'post-score-audit-down', attempts=1)
    atomic(ROOT / 'state/post-score-audit.done', {'utc': utc(), 'libraries': 10})


if __name__ == '__main__':
    main()
