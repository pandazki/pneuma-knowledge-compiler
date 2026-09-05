#!/usr/bin/env python3
"""Shared protocol mechanics: locks, atomic state, isolated process environments."""
import json,os,subprocess,time,hashlib,fcntl,tempfile,urllib.request
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
PYTHON=str(ROOT/'repo/.venv/bin/python')
MODEL='openrouter:openai/gpt-5.6-luna'

def utc():return datetime.now(timezone.utc).isoformat()
def atomic(path,data):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 tmp=Path(tempfile.mkstemp(prefix=path.name,dir=path.parent)[1]);tmp.write_text(json.dumps(data,indent=2)+'\n');os.replace(tmp,path)
def event(kind,**fields):
 row={'utc':utc(),'event':kind,**fields}
 with open(ROOT/'build-record/events.jsonl','a') as f:
  fcntl.flock(f,fcntl.LOCK_EX);f.write(json.dumps(row)+'\n');f.flush()
 print(json.dumps(row),flush=True)
def env_for(i):
 env=os.environ.copy()
 # Drop inherited framework settings so each project remains isolated.
 for k in list(env):
  if k.startswith('PNEUMA_'):del env[k]
 for line in (ROOT/f'app-{i+1:02d}/.env').read_text().splitlines():
  if line and not line.startswith('#') and '=' in line:
   k,v=line.split('=',1);env[k.strip()]=v.strip().strip('"').strip("'")
 for k in list(env):
  if k.startswith('PNEUMA_KNOWLEDGE_'):del env[k]
 for role in ['COMPILE','RECALL','ANSWER','DEEP','SKILL','EVOLVE','CHALLENGE','BRIEF','LIVE_CONTEXT','LIVE_DISCOVER','LIVE_PICK']:
  env['PNEUMA_KNOWLEDGE_LLM_MODEL_'+role]=MODEL
 env['PNEUMA_KNOWLEDGE_LLM_MODEL']=MODEL
 env['PNEUMA_KNOWLEDGE_EMBEDDING_MODEL']='openrouter:openai/text-embedding-3-small'
 env['PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER']='openai'
 env['PNEUMA_KNOWLEDGE_ENGINE_DIR']=str(ROOT/f'app-{i+1:02d}/engine')
 env['PNEUMA_KNOWLEDGE_COMPONENTS']='people,time'
 env['PNEUMA_KNOWLEDGE_COMPILE_IMAGE_MODE']='caption'
 env['PYTHONDONTWRITEBYTECODE']='1';env['PYTHONUNBUFFERED']='1'
 return env

def verify_freeze(number):
 manifest=json.loads((ROOT/f'state/freeze{number}.json').read_text())
 for p,h in manifest.items():
  if hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=h:raise RuntimeError('frozen hash mismatch: '+p)
 event('FREEZE_VERIFIED',number=number,files=len(manifest))

def command(i,args,label,attempts=4,timeout=7200):
 if args[0] in ['compile','evolve','ingest']:check_budget(45)
 app=ROOT/f'app-{i+1:02d}';log=ROOT/'logs'/f'{i:02d}-{label}-{time.time_ns()}.log'
 for attempt in range(1,attempts+1):
  try:
   r=subprocess.run([PYTHON,str(app/'app.py'),*args],cwd=app,env=env_for(i),capture_output=True,text=True,timeout=timeout)
   rc=r.returncode
   safe_log(log,r.stdout+'\n'+r.stderr,rc)
  except subprocess.TimeoutExpired:
   rc=124;safe_log(log,'',rc)
  event('COMMAND',conversation_idx=i,label=label,attempt=attempt,rc=rc,log=log.name)
  if rc==0:return log
  if attempt<attempts:time.sleep(15*2**(attempt-1))
 raise RuntimeError(f'command failed c={i} label={label} rc={rc}; raw log intentionally withheld')


def provider_spend():
 key=env_for(0)['OPENROUTER_API_KEY']
 req=urllib.request.Request('https://openrouter.ai/api/v1/key',headers={'Authorization':'Bearer '+key})
 with urllib.request.urlopen(req,timeout=30) as response:data=json.load(response)['data']
 return float(data['usage'])

def check_budget(limit=50):
 # Only this experiment's persisted job/answer usage is attributable on a shared key.
 build_input=build_output=answer_input=answer_output=0
 for path in (ROOT/'build-record').glob('snapshot-*.json'):
  for job in json.loads(path.read_text())['jobs']:
   build_input+=int(job.get('input_tokens',0) or 0)
   build_output+=int(job.get('output_tokens',0) or 0)
 for path in (ROOT/'build-record/answers').glob('*.json'):
  row=json.loads(path.read_text())
  answer_input+=int(row.get('input_tokens',0) or 0)
  answer_output+=int(row.get('output_tokens',0) or 0)
 total=(build_input+answer_input)*.20/1e6+(build_output+answer_output)*1.20/1e6
 atomic(ROOT/'results/own-cost.json',{
  'utc':utc(),'build_input_tokens':build_input,'build_output_tokens':build_output,
  'answer_input_tokens':answer_input,'answer_output_tokens':answer_output,
  'own_accounted_usd':total,'soft_ceiling_usd':50,'hard_ceiling_usd':60,
  'effective_stop_usd':min(limit,50),'undercounts':True,
  'scope':'Own recorded job/answer token usage at declared prices; judge excluded',
  'limitation':'Own accounting undercounts (approximately 40% was observed at 07:16Z); key-level figures are not attributable while the key is shared.'})
 if total>=60:raise RuntimeError('own accounting hard budget ceiling reached')
 if total>=min(limit,50):raise RuntimeError('own accounting budget reserve or soft ceiling reached')
 return total


def safe_log(path,text,rc):
 import re
 facts=[]
 for line in text.splitlines():
  m=re.fullmatch(r'\s*Compile-model tokens: input=(\d+) output=(\d+) total=(\d+)',line)
  if m:facts.append({'event':'compile_tokens','input_tokens':int(m[1]),'output_tokens':int(m[2]),'total_tokens':int(m[3])})
  m=re.fullmatch(r'\s*Processed (\d+) jobs in ([0-9.]+)s; (\d+) canonical documents, (\d+) claims\.',line)
  if m:facts.append({'event':'compile_counts','jobs':int(m[1]),'seconds':float(m[2]),'documents':int(m[3]),'claims':int(m[4])})
  m=re.fullmatch(r'Scoring: (\d+)/(\d+)',line)
  if m:facts.append({'event':'scoring_progress','completed':int(m[1]),'total':int(m[2])})
  m=re.match(r'^([A-Za-z_][A-Za-z_0-9.]*(?:Error|Exception)):',line)
  if m:facts.append({'event':'exception_class','class':m[1]})
 facts.append({'event':'exit','rc':rc})
 with open(path,'a') as f:
  for row in facts:f.write(json.dumps(row)+'\n')
