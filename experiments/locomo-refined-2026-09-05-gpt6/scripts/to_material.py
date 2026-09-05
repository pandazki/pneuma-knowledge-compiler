#!/usr/bin/env python3
"""Lossless admitted-field conversion, verified against the generated parser."""
import ast, hashlib, json, re
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'data/public/conversations.jsonl'
if not DATA.exists():DATA=ROOT/'data/data/public/conversations.jsonl'

def parser():
    p=ROOT/'app-01/app.py';source=p.read_text();tree=ast.parse(source)
    ns={'re':re}
    for node in tree.body:
        if isinstance(node,ast.FunctionDef) and node.name in ['split_frontmatter','parse_conversation_turns']:
            code=ast.get_source_segment(source,node)
            exec(compile(code,str(p),'exec'),ns)
    return ns['split_frontmatter'],ns['parse_conversation_turns']

def load():
    return [json.loads(line) for line in DATA.open()]

def render(c,s):
    date=datetime.strptime(s['date_time'],'%I:%M %p on %d %B, %Y').strftime('%Y-%m-%d')
    out=['---',f'date: {date}','type: conversation',f'title: conversation-{c["conversation_idx"]:02d}-session-{s["session_index"]:03d}', '---','']
    for m in s['messages']:
        pieces=m['text'].split('\n')
        out.append(m['speaker']+': '+pieces[0])
        out.extend('  '+v for v in pieces[1:])
        # Each modality is independent; no images-to-caption dependency.
        for url in m.get('images') or []:out.append('  [images] '+url)
        if m.get('blip_caption'):out.append('  [caption: BLIP derived] '+m['blip_caption'])
        if m.get('query'):out.append('  [query: image search metadata] '+m['query'])
    return '\n'.join(out)+'\n'

def verify(c,s,text):
    split,parse=parser();_,body=split(text);turns=parse(body)
    if len(turns)!=len(s['messages']):raise ValueError('turn count mismatch')
    for i,((speaker,value),m) in enumerate(zip(turns,s['messages'])):
        # Independent expected representation, built directly from original fields.
        expected=m['text']
        for url in m.get('images') or []:expected+='\n[images] '+url
        if m.get('blip_caption'):expected+='\n[caption: BLIP derived] '+m['blip_caption']
        if m.get('query'):expected+='\n[query: image search metadata] '+m['query']
        if speaker!=m['speaker'] or value.encode()!=expected.encode():
            raise ValueError(f'round-trip mismatch c={c["conversation_idx"]} s={s["session_index"]} m={i}; no content disclosed')
    return hashlib.sha256(text.encode()).hexdigest()

def dry_run():
    rows=[]
    for c in load():
        for s in c['sessions']:
            text=render(c,s);digest=verify(c,s,text)
            rows.append({'conversation_idx':c['conversation_idx'],'session_index':s['session_index'],'messages':len(s['messages']),'sha256':digest})
    assert len(rows)==272
    (ROOT/'build-record/roundtrip.json').write_text(json.dumps(rows,indent=2)+'\n')
    print('ROUNDTRIP PASS: 272 sessions; all original text and independent media fields exact')

if __name__=='__main__':
    import sys
    if sys.argv[1]=='dry-run':dry_run()
    else:
        idx,n=int(sys.argv[1]),int(sys.argv[2]);c=next(c for c in load() if c['conversation_idx']==idx)
        s=next(s for s in c['sessions'] if s['session_index']==n)
        text=render(c,s);verify(c,s,text)
        p=ROOT/f'app-{idx+1:02d}/material/s{n:03d}/session-{n:03d}.md'
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text)
        print(f'EMIT c={idx} s={n} roundtrip=pass')
