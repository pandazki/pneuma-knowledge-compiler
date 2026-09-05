#!/usr/bin/env python3
"""Durable stage launcher; each phase is independently idempotent."""
import fcntl,json,subprocess,os
from runtime import ROOT,PYTHON,atomic,event,utc

def main():
 lock=open(ROOT/'state/pipeline.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 atomic(ROOT/'state/pipeline-pid.json',{'pid':os.getpid(),'utc':utc()})
 for phase in ['build','answer','score']:
  if (ROOT/f'state/{phase}.done').exists():continue
  atomic(ROOT/'state/progress.json',{'phase':phase,'status':'running','freeze1':True,'freeze2':True,'updated_at':utc()})
  with open(ROOT/'RUN-LOG.md','a') as f:f.write(f'\n- {utc()}：阶段 {phase} 起跑；冻结脚本自行验哈希，pid={os.getpid()}，stdout 仅白名单事件。\n')
  event('PHASE_START',phase=phase)
  r=subprocess.run([PYTHON,str(ROOT/f'scripts/{phase}.py')],cwd=ROOT)
  if r.returncode:
   atomic(ROOT/'state/progress.json',{'phase':phase,'status':'failed','exit_code':r.returncode,'freeze1':True,'freeze2':True,'updated_at':utc()})
   with open(ROOT/'RUN-LOG.md','a') as f:f.write(f'\n- {utc()}：阶段 {phase} 返回 {r.returncode}，暂停后续阶段。查看白名单 events 和状态；不读取原始语料/判分中间产物。\n')
   raise SystemExit(r.returncode)
  with open(ROOT/'RUN-LOG.md','a') as f:f.write(f'\n- {utc()}：阶段 {phase} 完成。\n')
  event('PHASE_COMPLETE',phase=phase)
 atomic(ROOT/'state/progress.json',{'phase':'analysis','status':'ready','freeze1':True,'freeze2':True,'updated_at':utc()})
 event('ANALYSIS_READY')
if __name__=='__main__':main()
