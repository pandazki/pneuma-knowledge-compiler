#!/usr/bin/env python3
"""Read-only silent CLI answering; global 32, two libraries, idempotent QA files."""
import ast,concurrent.futures,fcntl,hashlib,json,re,subprocess,time
from runtime import ROOT,PYTHON,atomic,command,env_for,event,verify_freeze,utc,check_budget,safe_log
QUESTIONS=ROOT/'data/data/public/questions.jsonl'

def project(record):
 return {'qa_id':str(record['qa_id']),'conversation_idx':int(record['conversation_idx']),'question':str(record['question'])}
def questions():
 return [project(json.loads(line)) for line in QUESTIONS.open()]
def parse(stdout):
 lines=stdout.splitlines();start=next((i for i,s in enumerate(lines) if s.startswith('A: ')),None)
 if start is None:raise ValueError('no CLI answer')
 end=next((i for i in range(start+1,len(lines)) if re.match(r'^\s*\(\d+(?:\.\d+)?s,',lines[i])),None)
 if end is None:raise ValueError('no CLI token statistics')
 usage=ast.literal_eval(lines[end].split('tokens ',1)[1].rsplit(')',1)[0])
 answer='\n'.join([lines[start][3:],*lines[start+1:end]]).strip()
 # Generic citation removal, independent of question content.
 answer=re.sub(r'\[cite:[^\]]+\]','',answer)
 answer=re.sub(r'<!--.*?-->','',answer,flags=re.S).strip()
 return answer,{k:int(usage.get(k,0) or 0) for k in ['input_tokens','output_tokens','total_tokens']}
def result_path(q):return ROOT/'results/answers'/(hashlib.sha256(q['qa_id'].encode()).hexdigest()+'.json')

def one(q):
 dest=result_path(q)
 if dest.exists():return
 i=q['conversation_idx'];app=ROOT/f'app-{i+1:02d}';env=env_for(i)
 env.update({'PNEUMA_KNOWLEDGE_RECALL_PLAN_QUERIES':'3','PNEUMA_KNOWLEDGE_RECALL_CLAIM_CANDIDATE_CAP':'80','PNEUMA_KNOWLEDGE_RECALL_WINDOW_CANDIDATE_CAP':'60','PNEUMA_KNOWLEDGE_RECALL_ALL_CONTEXT_CHARS':'120000','PNEUMA_KNOWLEDGE_ANSWER_REASONING_EFFORT':'high'})
 started=time.monotonic()
 for attempt in range(1,6):
  check_budget(50)
  log=ROOT/'logs'/f'ask-{dest.stem}-{attempt}.log'
  try:
   r=subprocess.run([PYTHON,str(app/'app.py'),'ask',q['question'],'--style','concise','--evidence-strategy','all','--answer-format','structured'],cwd=app,env=env,capture_output=True,text=True,timeout=900)
   safe_log(log,r.stderr,r.returncode)
   if r.returncode!=0:raise RuntimeError('CLI nonzero')
   answer,usage=parse(r.stdout)
   atomic(dest,{'qa_id':q['qa_id'],'predicted_answer':answer})
   atomic(ROOT/'build-record/answers'/(dest.stem+'.json'),{'qa_id':q['qa_id'],'conversation_idx':i,'utc':utc(),'attempts':attempt,'seconds':round(time.monotonic()-started,2),**usage})
   event('ANSWER_FINISHED',qa_id=q['qa_id'],conversation_idx=i,attempt=attempt)
   return
  except (subprocess.TimeoutExpired,RuntimeError,ValueError,SyntaxError) as exc:
   event('ANSWER_RETRY',qa_id=q['qa_id'],attempt=attempt,error_class=type(exc).__name__)
   if attempt==5:raise RuntimeError('answer retries exhausted; no fabricated completion') from None
   time.sleep(15*2**(attempt-1))

def assemble(rows):
 ids=[q['qa_id'] for q in rows]
 assert len(ids)==1382 and len(set(ids))==1382
 preds=[json.loads(result_path(q).read_text()) for q in rows]
 assert len(preds)==1382 and {p['qa_id'] for p in preds}==set(ids)
 output=ROOT/'results/predictions.jsonl';tmp=output.with_suffix('.tmp')
 tmp.write_text(''.join(json.dumps(p,ensure_ascii=False)+'\n' for p in preds));tmp.replace(output)
 atomic(ROOT/'state/predictions-validated.json',{'rows':1382,'unique':1382,'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'utc':utc()})

def main():
 lock=open(ROOT/'state/answer.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 verify_freeze(1);verify_freeze(2)
 assert (ROOT/'state/build.done').exists()
 event('ANSWER_START',concurrency=32,visitor_class='silent');rows=questions()
 for base in range(0,10,2):
  active=[i for i in [base,base+1] if any(q['conversation_idx']==i and not result_path(q).exists() for q in rows)]
  if not active:continue
  for i in active:command(i,['up'],'answer-up')
  try:
   groups=[[q for q in rows if q['conversation_idx']==i] for i in active]
   todo=[g[n] for n in range(max(map(len,groups))) for g in groups if n<len(g) and not result_path(g[n]).exists()]
   with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:list(pool.map(one,todo))
  finally:
   for i in active:command(i,['down'],'answer-down',attempts=1)
 assemble(rows);atomic(ROOT/'state/answer.done',{'utc':utc()});event('ANSWER_COMPLETE',rows=1382)
if __name__=='__main__':main()
