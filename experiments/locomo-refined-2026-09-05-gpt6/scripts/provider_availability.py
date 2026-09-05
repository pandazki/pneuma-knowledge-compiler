#!/usr/bin/env python3
"""Read-only service availability diagnosis; never used as the budget guard."""
import json
import urllib.error
import urllib.request
from runtime import ROOT, atomic, env_for, utc


def main():
    key = env_for(0)['OPENROUTER_API_KEY']
    result = {'utc': utc(), 'scope': 'Shared account service availability only; not attributable experiment spend'}
    for name, path, fields in [
        ('key', 'key', ['limit', 'limit_remaining', 'usage', 'is_free_tier', 'is_management_key']),
        ('credits', 'credits', ['total_credits', 'total_usage']),
    ]:
        request = urllib.request.Request('https://openrouter.ai/api/v1/' + path,
                                         headers={'Authorization': 'Bearer ' + key})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                data = json.load(response).get('data', {})
            result[name] = {f: data[f] for f in fields if f in data and isinstance(data[f], (int, float, bool, type(None)))}
        except urllib.error.HTTPError as exc:
            result[name] = {'http_status': exc.code}
    history = ROOT / 'results/incidents/provider-availability.jsonl'
    if not history.exists() and (ROOT / 'results/provider-availability.json').exists():
        history.write_text(json.dumps(json.loads((ROOT / 'results/provider-availability.json').read_text())) + '\n')
    with history.open('a') as stream:
        stream.write(json.dumps(result) + '\n')
    atomic(ROOT / 'results/provider-availability.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
