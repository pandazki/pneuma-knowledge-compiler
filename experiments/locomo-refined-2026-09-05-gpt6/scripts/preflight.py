#!/usr/bin/env python3
"""Verify settings and a synthetic model call without exposing credentials."""
import sys,os,asyncio,json
from runtime import env_for,atomic,ROOT
from snapshot import app_module
async def main():
 os.environ.update(env_for(0));app=app_module(0)
 skill=app.load_contract_skill();s=app.build_settings(base_version=skill.version)
 assert s.llm_model_compile=='openrouter:openai/gpt-5.6-luna'
 assert s.components=='people,time'
 import urllib.request
 body={'model':'openai/gpt-5.6-luna','messages':[{'role':'user','content':'Reply with the single word OK.'}],'max_tokens':32,'provider':{'order':['openai'],'allow_fallbacks':False}}
 req=urllib.request.Request('https://openrouter.ai/api/v1/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY'],'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=90) as r:data=json.load(r)
 atomic(ROOT/'build-record/preflight.json',{'success':bool(data.get('choices')),'model':data.get('model'),'usage':{k:data.get('usage',{}).get(k) for k in ['prompt_tokens','completion_tokens','total_tokens','cost']}})
 print('SYNTHETIC PROVIDER PREFLIGHT PASS')
if __name__=='__main__':asyncio.run(main())
