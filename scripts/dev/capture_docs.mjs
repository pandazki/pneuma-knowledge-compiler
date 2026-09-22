/** Capture the current UI using only synthetic fixtures in a fresh, network-isolated browser. */
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {fixtures,TENANT} from './docs_fixtures.mjs';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const require=createRequire(path.join(root,'apps/web/package.json'));
const {chromium}=require('playwright');
const output=path.join(root,'docs/assets');
const port=Number(process.env.DOCS_SCREENSHOT_PORT || 4179);
const origin=`http://127.0.0.1:${port}`;
const server=spawn('pnpm',['exec','vite','--host','127.0.0.1','--port',String(port),'--strictPort'],{
  cwd:path.join(root,'apps/web'),env:{...process.env,VITE_API_BASE:'',VITE_ENGINE_FIXTURES:'true',PNEUMA_KNOWLEDGE_API_PORT:'9'},stdio:['ignore','pipe','pipe']});
let logs='';for(const stream of [server.stdout,server.stderr])stream.on('data',data=>{logs+=data.toString()});
let browser;
const captures=[];
try {
  for(let i=0;;i++) {
    if(server.exitCode!==null)throw new Error(`Isolated Vite server exited: ${logs}`);
    try {if((await fetch(origin)).ok)break;}catch{}
    if(i>100)throw new Error('Isolated Vite server did not start');
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  browser=await chromium.launch({headless:true,channel:process.env.DOCS_BROWSER_CHANNEL || undefined});
  await mkdir(output,{recursive:true});
  for(const locale of ['en','zh']) for(const theme of ['light','dark']) {
    const f=fixtures(locale);const unexpected=[];const errors=[];
    const context=await browser.newContext({viewport:{width:1440,height:1000},deviceScaleFactor:1,colorScheme:theme,locale:locale==='zh'?'zh-CN':'en-US',timezoneId:'UTC',serviceWorkers:'block'});
    await context.addInitScript(({locale,theme,tenant})=>{
      localStorage.setItem('pneuma-knowledge-locale',locale);localStorage.setItem('pneuma-knowledge-theme',theme);
      localStorage.setItem('pneuma_knowledge-user',tenant);localStorage.setItem('pneuma_knowledge-lens','owner');
    },{locale,theme,tenant:TENANT});
    await context.route('**/*',async route=>{
      const url=new URL(route.request().url());
      if(url.origin!==origin){unexpected.push(url.origin);return route.abort();}
      if(!url.pathname.startsWith('/v1/') && url.pathname!='/healthz')return route.continue();
      const p=url.pathname;const base=`/v1/users/${TENANT}`;let data;let status=200;
      if(p==='/v1/home/status'){status=404;data={detail:'Synthetic project demo'};}
      else if(p==='/v1/users')data=[TENANT];
      else if(p===base+'/profile')data=f.profile;
      else if(p===base+'/dataset')data=f.dataset;
      else if(p===base+'/snapshots')data={items:[],page:{limit:25,total:0,next_cursor:null}};
      else if(p===base+'/kb-snapshots')data=[];
      else if(p===base+'/summary')data={sources:1,jobs:2,documents:4,claims:6,snapshots:0};
      else if(p===base+'/sources')data={items:[f.detail],page:{limit:25,total:1,next_cursor:null}};
      else if(p===base+'/sources/'+f.detail.source_id)data=f.detail;
      else if(p===base+'/access-stats')data={kind:url.searchParams.get('kind'),ref:url.searchParams.get('ref'),last_accessed_at:null,hits_7d:0,hits_30d:0,heat:0};
      else if(p===base+'/history')data=f.history;
      else if(p===base+'/history/activity')data={days:[{date:'2026-09-18',count:1,kinds:{patch:1}},{date:'2026-09-20',count:1,kinds:{patch:1}}]};
      else if(p===base+'/steward')data=f.status;
      else if(p===base+'/call')data={configured:true,reason:null,detail:null,model:'gpt-live-1',voice:'alloy',live:false};
      else {unexpected.push(p);return route.abort();}
      // No request, including one with a mutating method, ever reaches a real service.
      if(route.request().method()!=='GET'){unexpected.push(`${route.request().method()} ${p}`);return route.abort();}
      return route.fulfill({status,contentType:'application/json',body:JSON.stringify(data)});
    });
    await context.routeWebSocket('**/*',socket=>{
      const url=new URL(socket.url());
      if(url.pathname===`/v1/users/${TENANT}/steward`){
        socket.onMessage(message=>{
          const frame=JSON.parse(String(message));
          if(frame.type==='user'){
            socket.send(JSON.stringify({type:'turn_started',turn_id:'demo-turn'}));
            socket.send(JSON.stringify({type:'text_delta',text:f.reply}));
            socket.send(JSON.stringify({type:'turn_finished',usage:null,cost_usd:null,duration_ms:0,error:''}));
          }
        });
        setTimeout(()=>socket.send(JSON.stringify({type:'snapshot',...f.status,session_id:'demo-session',events:[]})),40);
      } else if(url.origin===origin.replace('http:','ws:') && !url.pathname.startsWith('/v1/'))socket.connectToServer();
      else {unexpected.push(`WebSocket ${url.origin}`);socket.close();}
    });
    const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
    async function capture(name,hash,ready){
      await page.goto(`${origin}/?locale=${locale}&theme=${theme}${hash}`);
      await page.getByText(ready,{exact:false}).first().waitFor({timeout:10000}).catch(async error=>{console.error({unexpected,errors,body:(await page.locator('body').innerText()).slice(0,6000)});throw error;});
      await page.evaluate(()=>document.fonts.ready);
      await page.waitForTimeout(350);
      const file=`${name}-${locale}-${theme}.png`;
      await page.screenshot({path:path.join(output,file)});
      captures.push(file);console.log(file);
    }
    await capture('library','#/library/document/harbor-overview',f.docs[0].title);
    await capture('history','#/history/patch/demo0002',f.patch.brief);
    await page.goto(`${origin}/?locale=${locale}&theme=${theme}#/steward`);
    await page.getByRole('textbox').waitFor();
    await page.getByRole('textbox').fill(f.question);
    await page.getByRole('textbox').press('Enter');
    await page.getByText(locale==='zh'?'这是一段合成的文档演示对话。':'This is a synthetic documentation conversation.',{exact:false}).waitFor();
    await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(250);
    const file=`steward-${locale}-${theme}.png`;await page.screenshot({path:path.join(output,file)});captures.push(file);console.log(file);
    assert.deepEqual(unexpected,[],'Only declared synthetic API routes and local static assets may be accessed');
    assert.deepEqual(errors,[],'Screenshots must have no application errors');
    await context.close();
  }
  await writeFile(path.join(output,'screenshots.json'),JSON.stringify({synthetic:true,viewport:{width:1440,height:1000},generator:'scripts/dev/capture_docs.mjs',files:captures},null,2)+'\n');
} finally {
  if(browser)await browser.close();server.kill('SIGTERM');
}
