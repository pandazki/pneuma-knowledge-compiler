#!/usr/bin/env python3
"""Generate isolated projects; merge credentials without exposing values."""
import json, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODEL='openrouter:openai/gpt-5.6-luna'

def main():
    for i in range(10):
        app=ROOT/f'app-{i+1:02d}'
        config={'language':'en','project_name':f'lr6r2-{i+1:02d}',
                'owner':{'display_name':f'Conversation {i+1:02d}'},
                'data':{'mode':'none'},'contract':{'mode':'skeleton'},
                'models':{k:MODEL for k in ['compile','recall','answer','deep','live_discover','live_pick']},
                'advanced':{'user_id':f'lr6r2-{i+1:02d}','chunk_strategy':'semantic','challenge_enabled':True,'compile_image_mode':'caption'}}
        cfg=ROOT/'contracts'/f'scaffold-{i+1:02d}.json'
        cfg.write_text(json.dumps(config,indent=2)+'\n')
        if not app.exists():
            subprocess.run(['python3',str(ROOT/'repo/scaffold/init.py'),'--answers',str(cfg),'--target',str(app)],check=True,stdout=subprocess.DEVNULL)
        env=app/'.env'
        entries={}
        for line in env.read_text().splitlines():
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1);entries[k]=v
        for line in (ROOT/'secrets/.env').read_text().splitlines():
            if line and not line.startswith('#') and '=' in line:
                k,v=line.split('=',1)
                if k=='OPENROUTER_API_KEY' or k.startswith('PNEUMA_KNOWLEDGE_'):entries[k]=v
        entries['PNEUMA_KNOWLEDGE_OPENROUTER_PROVIDER_ORDER']='openai'
        entries['PNEUMA_APP_COMPOSE_PROJECT']=f'lr6r2-{i+1:02d}'
        env.write_text('\n'.join(k+'='+v for k,v in entries.items())+'\n');env.chmod(0o600)
        print(f'generated app-{i+1:02d}')
if __name__=='__main__':main()
