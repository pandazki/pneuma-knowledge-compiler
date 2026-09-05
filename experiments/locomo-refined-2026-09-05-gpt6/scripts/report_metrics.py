#!/usr/bin/env python3
"""Post-score numeric analysis only; never opens the question bank."""
import collections,csv,json
from pathlib import Path
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1]

def table(rows,field):
 groups=collections.defaultdict(list)
 for row in rows:groups[str(row.get(field))].append(row)
 out=['| 分组 | 题数 | 正确 | LLM % | F1 % | BLEU % |','|---|---:|---:|---:|---:|---:|']
 for key,items in sorted(groups.items()):
  n=len(items);a=sum(r['llm_score'] for r in items)
  out.append(f'| {key} | {n} | {a:g} | {100*a/n:.2f} | {100*sum(r["f1_score"] for r in items)/n:.2f} | {100*sum(r["bleu_score"] for r in items)/n:.2f} |')
 return '\n'.join(out)

def main():
 assert (ROOT/'state/scores-landed.json').exists(),'Scoring firewall is still closed'
 rows=[json.loads(x) for x in (ROOT/'results/scored-stripped.jsonl').open()]
 scores=json.loads((ROOT/'results/dual-scores.json').read_text())
 events=[json.loads(x) for x in (ROOT/'build-record/events.jsonl').open()]
 sessions=[json.loads(p.read_text()) for p in sorted((ROOT/'state').glob('c*/session-*.done'))]
 with (ROOT/'build-record/session-progress.csv').open('w') as f:
  fields=['utc','conversation_idx','session','claims','documents','sources','seconds'];w=csv.DictWriter(f,lineterminator='\n',fieldnames=fields);w.writeheader();w.writerows(sessions)
 role=collections.defaultdict(lambda:collections.Counter())
 for p in (ROOT/'build-record').glob('snapshot-*.json'):
  for j in json.loads(p.read_text())['jobs']:
   c=role[j['kind']];c['jobs']+=1;c['ok']+=j['ok'];c['input_tokens']+=j['input_tokens'];c['output_tokens']+=j['output_tokens'];c['jobs_with_usage']+=int(j['input_tokens']+j['output_tokens']>0)
 answer_stats=[json.loads(p.read_text()) for p in (ROOT/'build-record/answers').glob('*.json')]
 for r in answer_stats:
  c=role['answer'];c['jobs']+=1;c['input_tokens']+=r['input_tokens'];c['output_tokens']+=r['output_tokens'];c['jobs_with_usage']+=int(r['input_tokens']+r['output_tokens']>0)
 costs={k:{**v,'usd':v['input_tokens']*.2/1e6+v['output_tokens']*1.2/1e6 if v['jobs_with_usage'] else None,'scope':'Recorded usage only; missing usage is not zero cost'} for k,v in role.items()}
 (ROOT/'results/stage-costs.json').write_text(json.dumps(costs,indent=2)+'\n')
 costtable=['| 环节 | job/题数 | input token | output token | 估算 USD |','|---|---:|---:|---:|---:|']
 for k,r in costs.items():
  amount=f'{r["usd"]:.4f}' if r['usd'] is not None else '未记录，非免费'
  costtable.append(f'| {k} | {r["jobs"]} | {r["input_tokens"]:,} | {r["output_tokens"]:,} | {amount} |')
 durations=[];stoppages=[]
 for phase in ['build','answer','score']:
  starts=[r for r in events if r['event']=='PHASE_START' and r.get('phase')==phase]
  ends=[r for r in events if r['event']=='PHASE_COMPLETE' and r.get('phase')==phase]
  if starts and ends:
   seconds=(datetime.fromisoformat(ends[-1]['utc'])-datetime.fromisoformat(starts[0]['utc'])).total_seconds()
   pause=0;pause_lower=0
   failures=[{**json.loads(p.read_text()),'incident':p.parent.name} for p in (ROOT/'state/history').glob('*/progress.json')]
   for previous,current in zip(starts,starts[1:]):
    failures_between=[x for x in failures if x.get('phase')==phase and x.get('status') in ['failed','interrupted'] and previous['utc']<x['updated_at']<current['utc']]
    assert failures_between, 'Missing interruption endpoint; do not invent active duration'
    stopped=max(failures_between,key=lambda x:x['updated_at'])
    seconds_paused=(datetime.fromisoformat(current['utc'])-datetime.fromisoformat(stopped['updated_at'])).total_seconds()
    pause+=seconds_paused
    bounded=stopped.get('pause_duration_is_upper_bound',False)
    pause_lower+=0 if bounded else seconds_paused
    stoppages.append({'phase':phase,'incident':stopped['incident'],'stopped_utc':stopped['updated_at'],'resumed_utc':current['utc'],'seconds':seconds_paused,'seconds_lower_bound':0 if bounded else seconds_paused,'duration_is_upper_bound':bounded,'timestamp_basis':stopped.get('timestamp_basis','pipeline failure timestamp')})
   durations.append({'phase':phase,'start':starts[0]['utc'],'end':ends[-1]['utc'],'wall_seconds':seconds,'active_seconds':seconds-pause,'active_seconds_upper_bound':seconds-pause_lower,'pause_seconds':pause,'pause_seconds_lower_bound':pause_lower,'attempts':len(starts)})
 (ROOT/'results/durations.json').write_text(json.dumps(durations,indent=2)+'\n')
 (ROOT/'results/stoppages.json').write_text(json.dumps(stoppages,indent=2)+'\n')
 out=['# 数值附表','',f'官方全量 {scores["official"]:.4f}%；剔除烧题 {scores["unburned"]:.4f}%（{scores["unburned_count"]} 题）。','', '## 分 conversation','',table(rows,'conversation_idx'),'','## 分 category','',table(rows,'category'),'','## 分模态','',table(rows,'is_multi_modality'),'','## 成本','', '\n'.join(costtable),'','Own accounting undercounts (approximately 40% was observed at 07:16Z); key-level figures are not attributable while the key is shared.','','## 耗时','','| 阶段 | 总经过秒 | 活跃秒 | 暂停秒 | UTC 开始 | UTC 结束 |','|---|---:|---:|---:|---|---|']
 for d in durations:
  active=f'{d["active_seconds"]:.1f}' if d['active_seconds']==d['active_seconds_upper_bound'] else f'{d["active_seconds"]:.1f}–{d["active_seconds_upper_bound"]:.1f}'
  paused=f'{d["pause_seconds"]:.1f}' if d['pause_seconds']==d['pause_seconds_lower_bound'] else f'{d["pause_seconds_lower_bound"]:.1f}–{d["pause_seconds"]:.1f}'
  out.append(f'| {d["phase"]} | {d["wall_seconds"]:.1f} | {active} | {paused} | {d["start"]} | {d["end"]} |')
 out+=['','## 停顿拆分','','| 原因 | 停止 UTC | 恢复 UTC | 秒 |','|---|---|---|---:|']
 for d in stoppages:
  bound='≤' if d['duration_is_upper_bound'] else ''
  out.append(f'| {d["incident"]} | {d["stopped_utc"]} | {d["resumed_utc"]} | {bound}{d["seconds"]:.1f} |')
 out+=['','Codex退出时刻未单独落盘；其停顿以上一进程最后完成答案至编排者原样重启的间隔作上界。编排者重启是恢复端点，不另加一段重复停顿。']
 out+=['','## 运行事件','',f'- evolve step 完成次数：{sum(e["event"]=="EVOLVE_FINISHED" for e in events)}',f'- 命令非零返回次数：{sum(e["event"]=="COMMAND" and e["rc"]!=0 for e in events)}',f'- 答题重试次数：{sum(e["event"]=="ANSWER_RETRY" for e in events)}']
 (ROOT/'results/metrics-tables.md').write_text('\n'.join(out)+'\n')
 print(json.dumps(scores))
if __name__=='__main__':main()
