#!/usr/bin/env python3
"""Verify completed artifacts without model calls or printing protected content."""
import csv
import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

from answer import questions
from runtime import ROOT, atomic, utc


def read(name):
    return json.loads((ROOT / name).read_text())


def digest(name):
    return hashlib.sha256((ROOT / name).read_bytes()).hexdigest()


def run(args):
    return subprocess.run(args, cwd=ROOT, capture_output=True, text=True, check=True).stdout


def verify_hashes(manifest):
    assert all(digest(name) == value for name, value in manifest.items()), 'Sealed hash mismatch'
    return len(manifest)


def assert_stripped(value, file, trail=()):
    if isinstance(value, dict):
        for key, child in value.items():
            # This key names a cost stage, not a gold response field.
            stage = file == 'results/stage-costs.json' and trail == () and key == 'answer'
            assert stage or key not in {'question', 'answer', 'evidence', 'evidence_messages', 'matched_answer'}, 'Protected field found'
            assert_stripped(child, file, (*trail, key))
    elif isinstance(value, list):
        for child in value:
            assert_stripped(child, file, trail)


def main():
    for marker in ['build.done', 'answer.done', 'score.done', 'scores-landed.json', 'post-score-audit.done']:
        assert (ROOT / 'state' / marker).exists(), 'Required phase incomplete'
    freeze = {str(i): verify_hashes(read(f'state/freeze{i}.json')) for i in [1, 2]}
    assert freeze == {'1': 191, '2': 14}
    sealed = {str(n): verify_hashes(read(f'state/resume-{n}-checkpoints.json')['checkpoints']) for n in [118, 213]}
    assert sealed == {'118': 118, '213': 213}
    assert len(list((ROOT / 'state').glob('c*/session-*.done'))) == 272
    assert len(list((ROOT / 'state').glob('c*/done'))) == 10
    with (ROOT / 'build-record/session-progress.csv').open() as stream:
        assert len(list(csv.DictReader(stream))) == 272
    audits = [read(f'build-record/post-score-audit-{i:02d}.json') for i in range(10)]
    assert all(a['pending'] == a['unresolved'] == a['consultation_records'] == a['business_consultation_records'] == 0 for a in audits)
    assert sum(a['historical_http402_jobs_retained'] for a in audits) == 16
    assert sum(a['http402_jobs_still_unresolved'] for a in audits) == 0

    predicted = [json.loads(line) for line in (ROOT / 'results/predictions.jsonl').read_text().splitlines()]
    scored = [json.loads(line) for line in (ROOT / 'results/scored-stripped.jsonl').read_text().splitlines()]
    expected_ids = {q['qa_id'] for q in questions()}  # Frozen mechanical projection only.
    atomic_answers = [json.loads(p.read_text()) for p in (ROOT / 'results/answers').glob('*.json')]
    usage = [json.loads(p.read_text()) for p in (ROOT / 'build-record/answers').glob('*.json')]
    for collection in [predicted, scored, atomic_answers, usage]:
        assert len(collection) == 1382 and {r['qa_id'] for r in collection} == expected_ids
    by_id = {r['qa_id']: r['predicted_answer'] for r in predicted}
    assert all(r['predicted_answer'] == by_id[r['qa_id']] for r in scored + atomic_answers)
    assert digest('results/predictions.jsonl') == read('state/predictions-validated.json')['sha256']
    scores = read('results/dual-scores.json')
    assert all(r['llm_score'] in [0, 1] for r in scored)
    correct = sum(r['llm_score'] for r in scored)
    unburned = [r for r in scored if r['qa_id'] not in scores['burned']]
    assert correct == 1082 and len(unburned) == 1380 and sum(r['llm_score'] for r in unburned) == 1080
    assert math.isclose(scores['official'], correct / 1382 * 100)
    assert math.isclose(scores['unburned'], 1080 / 1380 * 100)
    raw = [json.loads(line) for line in (ROOT / 'logs/official/scored.jsonl').read_text().splitlines()]
    assert len(raw) == 1382 and all(r['success'] is True and not r['errors'] for r in raw)
    assert {r['qa_id'] for r in raw} == expected_ids
    raw_by_id = {r['qa_id']: r for r in raw}
    assert all(all(v == raw_by_id[r['qa_id']][k] for k, v in r.items()) for r in scored)
    for suffix in ['json', 'md']:
        assert digest(f'results/official-summary.{suffix}') == digest(f'logs/official/summary.{suffix}')
    for file in (ROOT / 'results').rglob('*'):
        if file.suffix == '.json':
            assert_stripped(json.loads(file.read_text()), str(file.relative_to(ROOT)))
        elif file.suffix == '.jsonl':
            for line in file.read_text().splitlines():
                assert_stripped(json.loads(line), str(file.relative_to(ROOT)))
    own = sum(c['usd'] or 0 for c in read('results/stage-costs.json').values())
    assert math.isclose(own, read('results/own-cost.json')['own_accounted_usd'])
    disclosure = 'Own accounting undercounts (approximately 40% was observed at 07:16Z); key-level figures are not attributable while the key is shared.'
    assert all(disclosure in (ROOT / name).read_text() for name in ['RUN-LOG.md', 'RUN-REPORT.md', 'README.md'])

    assert not run(['git', '-C', str(ROOT / 'repo'), 'status', '--porcelain']), 'Framework modified'
    assert run(['git', '-C', str(ROOT / 'repo'), 'rev-parse', 'HEAD']).strip() == 'c58efd5618d3734fa97e535895ac07019d37e5cd'
    assert not run(['git', 'diff', 'HEAD', '--', 'TASKBOOK.md', 'reference/prev-run']), 'Protocol reference modified'
    containers = run(['docker', 'ps', '-a', '--filter', 'name=lr6r2-', '--format', '{{.Names}}']).splitlines()
    assert not containers, 'Own containers remain'
    volumes = run(['docker', 'volume', 'ls', '--filter', 'name=lr6r2-', '--format', '{{.Name}}']).splitlines()
    assert len(volumes) == 40 and all(re.fullmatch(r'lr6r2-(0[1-9]|10)_(meili|postgres|qdrant|rustfs)_data', name) for name in volumes)

    # Scan staged/tracked files and report counts only; never echo credential values.
    files = run(['git', 'ls-files', '-z']).split('\0')[:-1]
    assert all(Path(p).parts[0] not in {'repo', 'data', 'material', 'secrets', 'logs'} and not Path(p).parts[0].startswith('app-') and not any(x.startswith('.env') for x in Path(p).parts) for p in files)
    secrets = []
    for line in (ROOT / 'secrets/.env').read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        value = value.strip().strip('"').strip("'")
        if re.search(r'KEY|TOKEN|SECRET|PASSWORD', key, re.I) and len(value) >= 12:
            secrets.append(value)
    assert secrets, 'No credential patterns available for required count scan'
    matches = 0
    for offset in range(0, len(files), 64):
        result = subprocess.run(['grep', '-I', '-c', '-F', '-f', '-', '--', *files[offset:offset + 64]], cwd=ROOT, input='\n'.join(secrets) + '\n', capture_output=True, text=True)
        assert result.returncode in [0, 1], 'Credential count scan failed'
        matches += sum(int(line.rsplit(':', 1)[-1]) for line in result.stdout.splitlines())
    assert matches == 0, 'Credential matches detected; values withheld'
    run(['git', 'diff', '--cached', '--check'])
    result = {'utc': utc(), 'status': 'verified', 'freeze_files': freeze, 'sealed_checkpoints': sealed, 'completed_sessions': 272, 'completed_libraries': 10, 'atomic_answers': 1382, 'official_correct': correct, 'official_score': scores['official'], 'unburned_score': scores['unburned'], 'judge_successes': 1382, 'judge_error_rows': 0, 'unresolved_jobs': 0, 'http402_historical_retained': 16, 'http402_unresolved': 0, 'consultation_records': 0, 'framework_clean': True, 'own_containers_remaining': containers, 'own_volumes_preserved': len(volumes), 'credential_grep_count': matches, 'scanned_git_files': len(files), 'protected_result_fields': 0, 'official_summaries_byte_identical': True, 'own_recorded_usd': own, 'report_sha256': digest('RUN-REPORT.md'), 'predictions_sha256': digest('results/predictions.jsonl')}
    atomic(ROOT / 'results/final-verification.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
