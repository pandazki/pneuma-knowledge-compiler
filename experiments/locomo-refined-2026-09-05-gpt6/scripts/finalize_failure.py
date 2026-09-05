#!/usr/bin/env python3
"""Finalize numeric failure evidence without opening any scoring data or gold fields."""
import collections,csv,json,subprocess
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]

def main():
 state=json.loads((ROOT/'state/progress.json').read_text())
 assert state['phase']=='build' and state['status']=='failed'
 assert not (ROOT/'state/answer.done').exists() and not (ROOT/'state/scores-landed.json').exists()
 sessions=[json.loads(p.read_text()) for p in sorted((ROOT/'state').glob('c*/session-*.done'))]
 totals=[19,19,32,29,29,28,31,30,25,30]
 conv=[];stages=collections.defaultdict(collections.Counter)
 for i,total in enumerate(totals):
  p=ROOT/f'build-record/snapshot-{i:02d}.json'
  snap=json.loads(p.read_text()) if p.exists() else {'sources':0,'claims':0,'documents':0,'pending':0,'unresolved':0,'jobs':[]}
  conv.append({'conversation_idx':i,'completed_sessions':sum(r['conversation_idx']==i for r in sessions),'total_sessions':total,'sources':snap['sources'],'claims':snap['claims'],'documents':snap['documents'],'complete':(ROOT/f'state/c{i:02d}/done').exists(),'snapshot_available':p.exists()})
  for j in snap['jobs']:
   c=stages[j['kind']];c['jobs']+=1;c['ok']+=j['ok'];c['input_tokens']+=j['input_tokens'];c['output_tokens']+=j['output_tokens'];c['jobs_with_usage']+=bool(j['input_tokens'] or j['output_tokens'])
 for r in stages.values():
  r['estimated_usd']=r['input_tokens']*.2/1e6+r['output_tokens']*1.2/1e6 if r['jobs_with_usage'] else None
 events=[json.loads(x) for x in (ROOT/'build-record/events.jsonl').open()]
 starts=[r for r in events if r['event']=='BUILD_START']
 start=starts[0]['utc'];end=state['updated_at']
 cost=json.loads((ROOT/'results/provider-cost.json').read_text())
 final={'status':'stopped_by_frozen_budget_guard','official_score':None,'unburned_score':None,'completed_sessions':len(sessions),'total_sessions':272,'completed_libraries':sum(r['complete'] for r in conv),'answered_questions':0,'judged_questions':0,'burned_qa_ids':['conv-26#q0000','conv-26#q0001'],'conversations':conv,'stages':dict(stages),'recorded_compile_usd':stages['compile']['estimated_usd'],'provider_key_delta_at_stop_usd':cost['delta_usd'],'provider_delta_attributable_to_experiment':False,'build_start_utc':start,'build_end_utc':end,'build_seconds':(datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds(),'evolve_steps_completed':sum(r['event']=='EVOLVE_FINISHED' for r in events),'evolve_adoption_jobs':stages.get('evolve_adopt',{}).get('jobs',0),'midpoint_reached':False}
 (ROOT/'results/failure-summary.json').write_text(json.dumps(final,indent=2)+'\n')
 with (ROOT/'build-record/session-progress.csv').open('w') as f:
  w=csv.DictWriter(f,lineterminator='\n',fieldnames=['utc','conversation_idx','session','claims','documents','sources','seconds']);w.writeheader();w.writerows(sessions)
 # Only resources with this run's prefix; no operations on other projects.
 p=subprocess.run(['docker','ps','-a','--filter','name=lr6r2-','--format','{{.Names}}'],capture_output=True,text=True,check=True)
 names=p.stdout.splitlines();assert not names,'Own containers unexpectedly remain'
 framework=subprocess.run(['git','-C',str(ROOT/'repo'),'status','--porcelain'],capture_output=True,text=True,check=True)
 assert not framework.stdout,'Framework tracked source changed'
 (ROOT/'state/closure.json').write_text(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'pipeline_exit_code':1,'own_containers_remaining':names,'framework_clean':True,'volumes_preserved':True,'firewall_still_closed':True,'do_not_resume_without_revised_budget_protocol':True},indent=2)+'\n')
 print(json.dumps({k:final[k] for k in ['completed_sessions','completed_libraries','recorded_compile_usd','provider_key_delta_at_stop_usd','build_seconds','evolve_steps_completed']}))
if __name__=='__main__':main()
