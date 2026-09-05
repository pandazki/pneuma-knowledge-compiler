#!/usr/bin/env python3
"""Frozen strict chronological build, two isolated stacks, resumable session units."""
import concurrent.futures,json,subprocess,time,fcntl
from runtime import ROOT,PYTHON,atomic,command,env_for,event,verify_freeze,utc,check_budget,safe_log
from to_material import load,render,verify

def snapshot(i):
 log=ROOT/'logs'/f'snapshot-{i:02d}.log'
 r=subprocess.run([PYTHON,str(ROOT/'scripts/snapshot.py'),str(i)],env=env_for(i),capture_output=True,text=True)
 safe_log(log,r.stdout+'\n'+r.stderr,r.returncode)
 if r.returncode:raise RuntimeError('snapshot failed; inspect only sanitized error classification')
 return json.loads((ROOT/f'build-record/snapshot-{i:02d}.json').read_text())

def budget():
 own_accounted=check_budget(45)
 ins=outs=0
 for p in (ROOT/'build-record').glob('snapshot-*.json'):
  for j in json.loads(p.read_text())['jobs']:ins+=j['input_tokens'];outs+=j['output_tokens']
 cost=ins*.2/1e6+outs*1.2/1e6
 done=len(list((ROOT/'state').glob('c*/session-*.done')))
 data={'utc':utc(),'input_tokens':ins,'output_tokens':outs,'estimated_usd':cost,'completed_sessions':done,'own_accounted_usd':own_accounted,'extrapolated_build_usd':cost*272/max(done,1),'undercounts':True,'conservative_cache_rates':True}
 atomic(ROOT/'results/build-cost.json',data)
 if done>=136 and not (ROOT/'state/midpoint.done').exists():
  with open(ROOT/'RUN-LOG.md','a') as f:f.write(f'\n- {utc()}：构建过半预算检查：{json.dumps(data)}。预定策略：超软顶预测则停止付费推进，保留状态；不调整已冻结配置。\n')
  atomic(ROOT/'state/midpoint.done',data)
 if cost>45 or (done>=136 and data['extrapolated_build_usd']>45):raise RuntimeError('budget stop: build reserve for answering and in-flight work')
 return data

def one(c):
 i=c['conversation_idx'];state=ROOT/f'state/c{i:02d}';state.mkdir(exist_ok=True)
 if (state/'done').exists():return
 command(i,['up'],'up')
 try:
  for s in c['sessions']:
   n=s['session_index'];done=state/f'session-{n:03d}.done'
   if done.exists():continue
   budget();t=time.monotonic();text=render(c,s);verify(c,s,text)
   directory=ROOT/f'app-{i+1:02d}/material/s{n:03d}';directory.mkdir(parents=True,exist_ok=True)
   (directory/f'session-{n:03d}.md').write_text(text)
   command(i,['ingest',str(directory)],f'ingest-{n:03d}')
   command(i,['compile'],f'compile-{n:03d}')
   snap=snapshot(i)
   if snap['pending'] or snap['unresolved']:raise RuntimeError(f'queue not clean c={i} s={n}')
   lastfile=state/'evolve.json';last=json.loads(lastfile.read_text()) if lastfile.exists() else {'claims':0,'session':0}
   force=n==len(c['sessions'])
   if force or (snap['claims']-last['claims']>=60 and n-last['session']>=5):
    command(i,['evolve','step','--policy','adopt-clean'],f'evolve-{n:03d}')
    command(i,['compile'],f'post-evolve-{n:03d}')
    snap=snapshot(i)
    if snap['pending'] or snap['unresolved']:raise RuntimeError('post-evolve queue not clean')
    atomic(lastfile,{'claims':snap['claims'],'session':n});event('EVOLVE_FINISHED',conversation_idx=i,session=n,forced=force)
   record={'utc':utc(),'conversation_idx':i,'session':n,'claims':snap['claims'],'documents':snap['documents'],'sources':snap['sources'],'seconds':round(time.monotonic()-t,2)}
   atomic(done,record);event('SESSION_FINISHED',**record);budget()
  atomic(state/'done',{'utc':utc()});event('CONVERSATION_FINISHED',conversation_idx=i)
 finally:
  command(i,['down'],'down',attempts=1)

def main():
 lock=open(ROOT/'state/build.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 verify_freeze(1);verify_freeze(2);event('BUILD_START')
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(one,load()))
 atomic(ROOT/'state/build.done',{'utc':utc()});event('BUILD_COMPLETE')
if __name__=='__main__':main()
