#!/usr/bin/env python3
"""Explicit structural whitelist. Never serialize source containers."""
import json
from pathlib import Path

def project(c):
    return {
        'conversation_idx': int(c['conversation_idx']),
        'speaker_a': str(c['speaker_a']),
        'speaker_b': str(c['speaker_b']),
        'session_count': len(c['sessions']),
        'sessions': [{
            'session_index': int(s['session_index']),
            'date_time': str(s['date_time']),
            'message_count': len(s['messages']),
            'image_count': sum(len(m.get('images') or []) for m in s['messages']),
            'caption_count': sum(bool(m.get('blip_caption')) for m in s['messages']),
            'query_count': sum(bool(m.get('query')) for m in s['messages']),
        } for s in c['sessions']],
    }

def test():
    bait='FORBIDDEN_FULL_TEXT_CANARY'
    c={'conversation_idx':0,'speaker_a':'SyntheticA','speaker_b':'SyntheticB',
       'text':bait,'answer':bait,'sessions':[{'session_index':1,'date_time':'synthetic-date',
       'text':bait,'messages':[{'speaker':'SyntheticA','text':bait,'images':['synthetic-url'],
       'blip_caption':bait,'query':bait}]}]}
    result=project(c)
    assert bait not in json.dumps(result)
    assert set(result)=={'conversation_idx','speaker_a','speaker_b','session_count','sessions'}
    assert set(result['sessions'][0])=={'session_index','date_time','message_count','image_count','caption_count','query_count'}
    assert result['sessions'][0]['image_count']==1
    print('SYNTHETIC WHITELIST TEST PASS')

if __name__=='__main__':
    import sys
    test()
    if '--real' in sys.argv:
        path=Path('data/public/conversations.jsonl')
        if not path.exists(): path=Path('data/data/public/conversations.jsonl')
        rows=[project(json.loads(line)) for line in path.open()]
        Path('logs/structure.json').write_text(json.dumps(rows,indent=2))
        for r in rows:
            print(json.dumps({'conversation_idx':r['conversation_idx'],'speaker_a':r['speaker_a'],'speaker_b':r['speaker_b'],'session_count':r['session_count'],'first_date':r['sessions'][0]['date_time'],'last_date':r['sessions'][-1]['date_time'],'messages':sum(s['message_count'] for s in r['sessions']),'images':sum(s['image_count'] for s in r['sessions']),'captions':sum(s['caption_count'] for s in r['sessions']),'queries':sum(s['query_count'] for s in r['sessions'])}))
