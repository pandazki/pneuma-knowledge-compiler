#!/usr/bin/env python3
"""Read only typed/count telemetry; never emit canonical or source text."""
import asyncio,importlib.util,json,os,sys
from pathlib import Path
from runtime import ROOT,atomic

def app_module(i):
 path=ROOT/f'app-{i+1:02d}/app.py';spec=importlib.util.spec_from_file_location('experiment_app',path)
 app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app);app._extend_no_proxy();return app
async def main(i):
 app=app_module(i)
 from pneuma_knowledge_service.wiring import build_context
 from pneuma_knowledge_core.domain.ids import UserId
 skill=app.load_contract_skill();ctx=await build_context(app.build_settings(base_version=skill.version))
 try:
  uid=UserId(app.user_id());jobs=await ctx.store.list_jobs(uid)
  rows=[]
  for j in jobs:
   # token_usage is structured telemetry, detail is intentionally never copied.
   usage=j.get('token_usage') or {}
   rows.append({'job_id':str(j['job_id']),'kind':str(j.get('kind')),'status':str(j.get('status')),'ok':j.get('ok') is True,'input_tokens':int(usage.get('input_tokens',0) or 0),'output_tokens':int(usage.get('output_tokens',0) or 0)})
  result={'conversation_idx':i,'sources':len(await ctx.store.list(uid)),'documents':len(await ctx.canonical.list(uid)),'claims':len(await ctx.store.list_canonical_claims(uid)),'pending':sum(j['status']!='done' for j in rows),'unresolved':len(app._unresolved_failures(jobs)),'jobs':rows}
  atomic(ROOT/f'build-record/snapshot-{i:02d}.json',result)
  print(json.dumps({k:result[k] for k in ['conversation_idx','sources','documents','claims','pending','unresolved']}))
 finally:await ctx.aclose()
if __name__=='__main__':asyncio.run(main(int(sys.argv[1])))
