/* Harnais CDP pour `test_workspace_manager_browser.py` (board-memory-workspace-inspector, Slice 07).

   Chrome sans tete ouvre la page SERVIE par un vrai Control Center relie a un
   vrai Core (aucun double de `fetch`) et joue un plan : clics, saisies,
   attentes sur une condition, captures d'ecran. Chaque etape est une
   expression evaluee dans la page.

   Usage : node _workspace_browser.mjs <url> <chrome.exe> <planJSON> <dossier des captures>
   Plan : {width, height, steps:[{do}|{wait, ms?}|{get, expr}|{shot}]}
   Sortie : {results, console} en JSON. */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,PLAN,SHOTS]=process.argv;
const plan=JSON.parse(PLAN);
const profile=mkdtempSync(join(tmpdir(),'jarvis-wsp-cdp-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions',
  '--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const consoleLines=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled')
      consoleLines.push({type:msg.params.type,text:msg.params.args.map(a=>a.value??a.description??'').join(' ')});
    if(msg.method==='Runtime.exceptionThrown')
      consoleLines.push({type:'exception',text:JSON.stringify(msg.params.exceptionDetails).slice(0,600)});
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}));
  });
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,120)} -> ${r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails)}`);
    return r.result.value;
  };
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:plan.width,height:plan.height,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await sleep(1500);
  const results={};
  for(const step of plan.steps){
    if(step.do!==undefined){await evaluate(step.do);await sleep(step.ms??250);continue}
    if(step.wait!==undefined){
      const until=Date.now()+(step.ms??15000);
      let seen=false;
      while(Date.now()<until){if(await evaluate(step.wait)){seen=true;break}await sleep(120)}
      if(!seen)throw new Error(`condition jamais vraie : ${step.wait}`);
      continue;
    }
    if(step.get!==undefined){results[step.get]=await evaluate(step.expr);continue}
    if(step.shot!==undefined){
      await sleep(200);
      const shot=await send('Page.captureScreenshot',{format:'png'});
      writeFileSync(join(SHOTS,step.shot),Buffer.from(shot.data,'base64'));
      results[`shot:${step.shot}`]=true;
    }
  }
  ws.close();
  process.stdout.write(JSON.stringify({results,console:consoleLines}));
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient le dossier */}
}

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{
      const list=await (await fetch(url)).json();
      const page=list.find(t=>t.type==='page');
      if(page&&page.webSocketDebuggerUrl)return page;
    }catch(_){/* Chrome n ecoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
