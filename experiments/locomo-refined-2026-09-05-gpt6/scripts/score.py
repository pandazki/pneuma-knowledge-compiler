#!/usr/bin/env python3
"""Invoke untouched official scorer; only publish stripped rows after scores land."""
import fcntl,hashlib,json,os,shutil,subprocess,sys
from runtime import ROOT,PYTHON,atomic,env_for,event,verify_freeze,utc,provider_spend,safe_log
from answer import questions
BURNED=['conv-26#q0000','conv-26#q0001']
SAFE=['qa_id','conversation_idx','predicted_answer','category','is_multi_modality','llm_score','f1_score','bleu_score','llm_judge']

def main():
 lock=open(ROOT/'state/score.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 verify_freeze(1);verify_freeze(2);assert (ROOT/'state/answer.done').exists()
 preds=[json.loads(line) for line in (ROOT/'results/predictions.jsonl').open()]
 ids=[q['qa_id'] for q in questions()]
 assert len(preds)==1382 and len({p['qa_id'] for p in preds})==1382 and {p['qa_id'] for p in preds}==set(ids)
 out=ROOT/'logs/official';out.mkdir(exist_ok=True)
 env=env_for(0);env['EVALUATOR_API_KEY']=env.pop('OPENROUTER_API_KEY')
 env.update({'EVALUATOR_MODEL':'qwen/qwen3-14b','EVALUATOR_API_BASE':'https://openrouter.ai/api/v1','LOCOMO_PYTHON_BIN':PYTHON,'LOCOMO_QUESTIONS_PATH':str(ROOT/'data/data/public/questions.jsonl'),'LOCOMO_PREDICTIONS_PATH':str(ROOT/'results/predictions.jsonl'),'LOCOMO_SCORED_PATH':str(out/'scored.jsonl'),'LOCOMO_SUMMARY_PATH':str(out/'summary.json'),'LOCOMO_MARKDOWN_SUMMARY_PATH':str(out/'summary.md')})
 before=provider_spend();atomic(ROOT/'state/judge-baseline.json',{'utc':utc(),'usage':before})
 event('SCORE_START',model='qwen/qwen3-14b',concurrency=64)
 # Official scorer writes only at completion. An interrupted attempt is rerun in full.
 if not (out/'summary.json').exists():
  r=subprocess.run(['./scripts/run_eval.sh','--metrics','llm','f1','bleu','--llm-judge','refined','--concurrency','64'],cwd=ROOT/'data',env=env,capture_output=True,text=True)
  safe_log(out/'scorer.log',r.stdout+'\n'+r.stderr,r.returncode)
  if r.returncode:raise RuntimeError('official scorer failed; raw judge logs withheld')
 rows=[json.loads(line) for line in (out/'scored.jsonl').open()]
 assert len(rows)==1382 and all(isinstance(r.get('llm_score'),(int,float)) for r in rows)
 # Firewall opens only after the full scored artifact and summary exist.
 atomic(ROOT/'state/scores-landed.json',{'utc':utc(),'rows':len(rows)})
 safe=[{k:r[k] for k in SAFE if k in r} for r in rows]
 (ROOT/'results/scored-stripped.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in safe))
 shutil.copy2(out/'summary.json',ROOT/'results/official-summary.json');shutil.copy2(out/'summary.md',ROOT/'results/official-summary.md')
 remaining=[r for r in safe if r['qa_id'] not in BURNED]
 scores={'official':100*sum(r['llm_score'] for r in safe)/len(safe),'unburned':100*sum(r['llm_score'] for r in remaining)/len(remaining),'total':len(safe),'unburned_count':len(remaining),'burned':BURNED}
 atomic(ROOT/'results/dual-scores.json',scores)
 atomic(ROOT/'results/judge-cost.json',{'before':before,'after':provider_spend(),'scope':'key-wide usage delta during judge'})
 atomic(ROOT/'state/score.done',{'utc':utc(),**scores});event('SCORES_LANDED',**scores)
if __name__=='__main__':main()
