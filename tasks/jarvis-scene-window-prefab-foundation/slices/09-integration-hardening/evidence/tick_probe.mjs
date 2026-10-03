/* Trace S09 — « l'utilisateur coche à l'écran » : Chrome RÉEL sans tête (`--headless=new`, profil
   jetable), piloté par CDP, sur la page servie par le Control Center isolé de la trace. Coche les
   <n> premiers éléments non cochés de la fenêtre `jarvis.checklist` <object_id> par de VRAIS clics
   souris (`Input.dispatchMouseEvent`) au centre de chaque ligne du cadre sandboxé : cadre → hôte →
   `POST /api/prefabs/events` (acteur forcé user) → Core. Attend que Core ait écrit chaque coche.

   Usage : node tick_probe.mjs <url du CC> <chrome.exe> <object_id> <n>
   Sortie (stdout, dernière ligne) : {ok, clicked:[labels], stored:[[id,done]], ring:[...], errors} — sans chemin. */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,ID,COUNT='2']=process.argv;
const profile=mkdtempSync(join(tmpdir(),'jarvis-s09-tick-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const out={ok:false,object_id:ID,clicked:[],errors:[]};

async function debuggerTarget(){
  const file=join(profile,'DevToolsActivePort');const deadline=Date.now()+60000;
  while(Date.now()<deadline){
    if(existsSync(file)){const port=readFileSync(file,'utf8').split('\n')[0].trim();
      try{const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const page=list.find(t=>t.type==='page');if(page)return page}catch(_){/* Chrome démarre */}}
    await sleep(100);
  }
  throw new Error('Chrome debugger never came up');
}

try{
  const target=await debuggerTarget();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refused'))});
  let id=0;const pending=new Map();const contexts=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.exceptionThrown')out.errors.push((msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,300));
    if(msg.method==='Runtime.consoleAPICalled'&&msg.params.type==='error')out.errors.push(msg.params.args.map(a=>a.value??a.description??'').join(' ').slice(0,300));
    if(msg.method==='Target.attachedToTarget'){const s=msg.params.sessionId;
      send('Runtime.enable',{},s).catch(()=>{});send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{})}
    if(msg.method==='Runtime.executionContextCreated')contexts.set(`${msg.sessionId||''}:${msg.params.context.id}`,
      {session:msg.sessionId||null,id:msg.params.context.id,main:!!(msg.params.context.auxData&&msg.params.context.auxData.isDefault)});
    if(msg.method==='Runtime.executionContextDestroyed')contexts.delete(`${msg.sessionId||''}:${msg.params.executionContextId}`);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;
    const timer=setTimeout(()=>{pending.delete(mine);ko(new Error(`CDP ${method} timed out`))},15000);
    pending.set(mine,{ok:v=>{clearTimeout(timer);ok(v)},ko:e=>{clearTimeout(timer);ko(e)}});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression)=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||r.exceptionDetails.text);return r.result.value};
  const until=async(check,ms=20000,label)=>{const deadline=Date.now()+ms;
    while(Date.now()<deadline){try{const v=await check();if(v)return v}catch(_){}await sleep(150)}
    throw new Error('never true: '+label)};
  /* Le cadre de CETTE fenêtre : son shim connaît l'instance reçue dans `init`. */
  const MATCH=`window.jarvis&&jarvis.instance&&jarvis.instance.object_id===${JSON.stringify(ID)}&&document.querySelectorAll('.ck-item').length>0`;
  const inFrame=async(expression)=>{
    for(const ctx of [...contexts.values()]){
      if(!ctx.main)continue;
      try{const r=await send('Runtime.evaluate',{expression:`(${MATCH})?(${expression}):null`,returnByValue:true,awaitPromise:true,contextId:ctx.id},ctx.session||undefined);
        if(!r.exceptionDetails&&r.result.value!==null&&r.result.value!==undefined)return r.result.value}catch(_){/* contexte parti */}
    }
    return null;
  };
  const mouse=(type,x,y,buttons)=>send('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:buttons??(type==='mouseReleased'?0:1),clickCount:1});
  const stored=()=>evaluate(`fetch('/api/scene',{cache:'no-store'}).then(r=>r.json()).then(b=>{
    const o=b.snapshot.objects.find(o=>o.object_id===${JSON.stringify(ID)});return o?o.payload.prefab.data.items.map(i=>[i.id,!!i.done]):null})`);

  await send('Page.enable');await send('Runtime.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  const sel=`[data-object-id="${ID}"] .sc-prefab-slot iframe`;
  await until(()=>evaluate(`!!document.querySelector(${JSON.stringify(sel)})`),30000,'checklist frame drawn');
  await until(()=>inFrame('1'),20000,'checklist frame ready');
  await sleep(800);/* géométrie stable avant le premier clic (constat S06) */
  const n=Number(COUNT);
  for(let k=0;k<n;k++){
    const before=await stored();
    const row=await inFrame(`(()=>{const r=[...document.querySelectorAll('.ck-item')].find(x=>x.getAttribute('aria-checked')!=='true');
      if(!r)return {none:true};r.scrollIntoView({block:'center'});const b=r.getBoundingClientRect();
      return {x:b.x+Math.min(40,b.width/2),y:b.y+b.height/2,label:r.querySelector('.ck-label').textContent}})()`);
    if(!row||row.none)break;
    const frame=await evaluate(`(()=>{const f=document.querySelector(${JSON.stringify(sel)});f.scrollIntoView({block:'center'});const b=f.getBoundingClientRect();return {x:b.x,y:b.y}})()`);
    const x=frame.x+row.x,y=frame.y+row.y;
    await mouse('mouseMoved',x,y,0);await mouse('mousePressed',x,y);await mouse('mouseReleased',x,y);
    out.clicked.push(row.label);
    const doneBefore=before.filter(i=>i[1]).length;
    await until(async()=>(await stored()).filter(i=>i[1]).length>doneBefore,10000,`Core wrote tick ${k+1}`);
  }
  out.stored=await stored();
  out.ring=await evaluate(`fetch('/api/prefabs/events?object_id=${encodeURIComponent(ID)}&limit=50',{cache:'no-store'}).then(r=>r.json()).then(b=>b.events.map(e=>[e.seq,e.event,e.class,e.outcome]))`);
  out.ok=out.clicked.length===n;
}catch(error){
  out.error=String(error&&error.message||error);
}finally{
  chrome.kill();await sleep(800);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome tient encore un fichier */}
  console.log(JSON.stringify(out));
  process.exit(0);
}
