/* Stress S09 (cycle de vie des cadres prefab) : Chrome RÉEL sans tête (`--headless=new`,
   profil jetable `--user-data-dir`), piloté par CDP, sur la page SERVIE par un vrai
   Control Center relié à un vrai Core isolés (ports de scratch, jamais 17653/17654).

   1. 200 cycles créer → cadre monté → archiver → cadre démonté d'une fenêtre
      `jarvis.window` (commandes utilisateur `POST /api/scene/commands`). Mesures :
      nombre de cadres à chaque pas (≤ plafond, 0 à la fin), compteurs du moteur
      (`Memory.getDOMCounters` après GC : documents, nœuds, écouteurs JS) au départ,
      tous les 50 cycles et à la fin, écouteurs `message` de la page (`DOMDebugger`).
   2. 30 fenêtres prefab simultanées : plafond 24 cadres vivants + 6 cartes « En
      pause » ; sélectionner une fenêtre en pause la reprend (une autre passe en
      pause, toujours 24) ; tout archiver → 0.
   3. Rafale d'événements : (a) 100 `emit` synchrones dans un cadre `jarvis.checklist`
      → l'hôte en laisse passer au plus 10/s ; (b) 200 `POST /api/prefabs/events`
      simultanés → Core en enregistre ~30 (seau 30/s), le reste 429 `rate_limited`.
   Le journal de Core (`trace.jsonl` du runtime) est relu après coup par
   `stress_core_journal.py` (erreurs `core.*`, diagnostics de débit).

   Usage : node stress_probe.mjs <url du CC> <chrome.exe> <dossier de sortie>
   Sortie : <dossier>/stress-results.json (aucun chemin de la machine). */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT]=process.argv;
const CYCLES=200,SIMULTANEOUS=30,LIVE_CAP=24;
const profile=mkdtempSync(join(tmpdir(),'jarvis-s09-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function debuggerTarget(){
  const file=join(profile,'DevToolsActivePort');
  const deadline=Date.now()+60000;
  while(Date.now()<deadline){
    if(existsSync(file)){
      const port=readFileSync(file,'utf8').split('\n')[0].trim();
      try{const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const page=list.find(t=>t.type==='page');if(page)return page}catch(_){/* Chrome démarre */}
    }
    await sleep(100);
  }
  throw new Error('Chrome debugger never came up');
}

const out={console:[],cycles:{},simultaneous:{},flood:{},ok:false};
const t0=Date.now();
try{
  const target=await debuggerTarget();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refused'))});
  let id=0;const pending=new Map();const sessions=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled'&&!msg.sessionId){
      const text=msg.params.args.map(a=>a.value??a.description??'').join(' ');
      out.console.push({type:msg.params.type,text:text.slice(0,300)});
    }
    if(msg.method==='Runtime.exceptionThrown')out.console.push({session:msg.sessionId?'frame':'page',type:'exception',
      text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,300)});
    if(msg.method==='Target.attachedToTarget'){
      const s=msg.params.sessionId;sessions.set(s,msg.params.targetInfo);
      send('Runtime.enable',{},s).catch(()=>{});
      send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{});
    }
    if(msg.method==='Target.detachedFromTarget')sessions.delete(msg.params.sessionId);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression,session)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},session);
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,100)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);
    return r.result.value;
  };
  const until=async(check,ms=20000,label)=>{const deadline=Date.now()+ms;let last;
    while(Date.now()<deadline){try{last=await check();if(last)return last}catch(_){}await sleep(40)}
    throw new Error('never true: '+(label||check.toString().slice(0,120)))};
  const frameEval=async(expression,predicate)=>{
    for(const [session,info] of sessions){
      if(info.url!=='about:srcdoc')continue;
      try{const value=await evaluate(expression,session);if(value!==null&&value!==undefined&&(!predicate||predicate(value)))return value}catch(_){/* cible partie */}
    }
    return null;
  };
  const command=(body)=>evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify(${JSON.stringify(body)})}).then(async r=>({status:r.status,body:await r.json()}))`);
  const windowCmd=(objectId,geometry,prefab,title)=>({schema_version:1,op:'upsert_object',object_id:objectId,
    fields:{kind:'window',category:'note',representation:'window',geometry,
      payload:{title,summary:'',items:[],prefab}}});
  const archive=(objectId)=>({schema_version:1,op:'archive',object_id:objectId});
  const dom=()=>evaluate(`(()=>({frames:document.querySelectorAll('.sc-prefab-slot iframe').length,
    paused:document.querySelectorAll('.sc-prefab-paused').length,
    windows:document.querySelectorAll('.sc-prefab-window').length}))()`);
  /* Écouteurs `message` posés sur `window` de la page (l'hôte en pose un seul, au premier montage). */
  const messageListeners=async()=>{
    const {result}=await send('Runtime.evaluate',{expression:'window'});
    const {listeners}=await send('DOMDebugger.getEventListeners',{objectId:result.objectId});
    await send('Runtime.releaseObject',{objectId:result.objectId});
    return listeners.filter(l=>l.type==='message').length;
  };
  const counters=async()=>{
    await send('HeapProfiler.collectGarbage');await sleep(200);await send('HeapProfiler.collectGarbage');
    const c=await send('Memory.getDOMCounters');
    return {documents:c.documents,nodes:c.nodes,jsEventListeners:c.jsEventListeners,messageListeners:await messageListeners(),
      targets:[...sessions.values()].filter(i=>i.url==='about:srcdoc').length,...await dom()};
  };

  await send('Page.enable');await send('Runtime.enable');await send('HeapProfiler.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate(`!!(window.JarvisScene&&window.JarvisScene.inspect().revision!==null)`),30000,'scene loaded');

  /* --------------------------------------------------------------- 1. 200 cycles */
  const W={prefab:{id:'jarvis.window',version:1,props:{},data:{body:'Cycle de stress S09.',items:[{label:'élément'}]}}};
  const geometry={x:-30,y:-20,w:56,h:34};
  // Un premier cycle hors mesure : il pose l'écouteur unique de l'hôte et met le paquet en cache.
  await command(windowCmd('stress-warm',geometry,W.prefab,'Chauffe'));
  await until(async()=>(await dom()).frames===1,20000,'warm frame');
  await until(()=>frameEval("document.body&&document.body.childElementCount>0?1:null"),20000,'warm frame ready');
  await command(archive('stress-warm'));
  await until(async()=>(await dom()).frames===0,20000,'warm frame gone');
  const samples=[{cycle:0,...await counters()}];
  let maxFrames=0,maxTargets=0,refused=0;const started=Date.now();
  for(let i=1;i<=CYCLES;i++){
    const oid=`stress-${i}`;
    const created=await command(windowCmd(oid,geometry,W.prefab,`Stress ${i}`));
    if(created.body.outcome!=='applied')refused++;
    await until(async()=>(await dom()).frames>=1,20000,`frame ${i} mounted`);
    const seen=await dom();maxFrames=Math.max(maxFrames,seen.frames);
    maxTargets=Math.max(maxTargets,[...sessions.values()].filter(x=>x.url==='about:srcdoc').length);
    const archived=await command(archive(oid));
    if(archived.body.outcome!=='applied')refused++;
    await until(async()=>(await dom()).frames===0&&(await dom()).windows===0,20000,`frame ${i} unmounted`);
    if(i%50===0)samples.push({cycle:i,...await counters()});
  }
  await sleep(500);
  const end={cycle:'end',...await counters()};samples.push(end);
  out.cycles={cycles:CYCLES,refused,maxFramesDuringCycles:maxFrames,maxFrameTargets:maxTargets,seconds:Math.round((Date.now()-started)/1000),
    samples,growth:{documents:end.documents-samples[0].documents,nodes:end.nodes-samples[0].nodes,
      jsEventListeners:end.jsEventListeners-samples[0].jsEventListeners,messageListeners:end.messageListeners-samples[0].messageListeners}};

  /* --------------------------------------------------- 2. 30 fenêtres simultanées */
  const ids=[];
  for(let i=0;i<SIMULTANEOUS;i++){
    const oid=`many-${i+1}`;ids.push(oid);
    const g={x:-150+(i%6)*52,y:-90+Math.floor(i/6)*40,w:46,h:32};
    const r=await command(windowCmd(oid,g,{id:'jarvis.window',version:1,props:{},data:{body:`Fenêtre ${i+1}`,items:[]}},`Fenêtre ${i+1}`));
    if(r.body.outcome!=='applied')throw new Error(`many ${i+1}: ${JSON.stringify(r.body)}`);
  }
  await until(async()=>{const d=await dom();return d.windows===SIMULTANEOUS&&d.frames+d.paused===SIMULTANEOUS},30000,'30 windows drawn');
  await sleep(1500);
  const many=await dom();
  const pausedIds=await evaluate(`[...document.querySelectorAll('.sc-prefab-paused')].map(p=>p.closest('[data-object-id]').dataset.objectId)`);
  /* Reprendre une fenêtre en pause par une vraie sélection (clic sur sa tête). */
  const resumeId=pausedIds[0];
  const head=await evaluate(`(()=>{const el=document.querySelector('[data-object-id="${resumeId}"] .sc-wtitle');el.scrollIntoView({block:'center'});
    const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:head.x,y:head.y,button:'none'});
  await send('Input.dispatchMouseEvent',{type:'mousePressed',x:head.x,y:head.y,button:'left',buttons:1,clickCount:1});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:head.x,y:head.y,button:'left',buttons:0,clickCount:1});
  await until(()=>evaluate(`!!document.querySelector('[data-object-id="${resumeId}"] .sc-prefab-slot iframe')`),10000,'paused window resumed');
  await sleep(500);
  const afterResume=await dom();
  const stillPaused=await evaluate(`[...document.querySelectorAll('.sc-prefab-paused')].map(p=>p.closest('[data-object-id]').dataset.objectId)`);
  const placeholderText=await evaluate(`(document.querySelector('.sc-prefab-paused')||{}).textContent||''`);
  const shot=await send('Page.captureScreenshot',{format:'png'});
  writeFileSync(join(OUT,'stress-30-windows.png'),Buffer.from(shot.data,'base64'));
  for(const oid of ids){const r=await command(archive(oid));if(r.body.outcome!=='applied')throw new Error(`archive ${oid}`)}
  await until(async()=>{const d=await dom();return d.frames===0&&d.windows===0&&d.paused===0},20000,'30 windows gone');
  const afterMany=await counters();
  out.simultaneous={windows:SIMULTANEOUS,cap:LIVE_CAP,live:many.frames,paused:many.paused,pausedIds,resumed:resumeId,
    afterResume:{live:afterResume.frames,paused:afterResume.paused,resumedIsLive:!stillPaused.includes(resumeId)},
    placeholderText:placeholderText.slice(0,200),afterArchive:afterMany};

  /* ------------------------------------------------------------- 3. rafale d'événements */
  const items=[{id:'a',label:'Un',done:false},{id:'b',label:'Deux',done:false}];
  const fr=await command(windowCmd('flood-1',{x:-30,y:-20,w:56,h:40},{id:'jarvis.checklist',version:1,props:{},data:{items}},'Rafale'));
  if(fr.body.outcome!=='applied')throw new Error('flood window refused');
  await until(async()=>(await dom()).frames===1,20000,'flood frame');
  await until(()=>frameEval("document.querySelectorAll('[role=checkbox]').length===2?1:null"),20000,'checklist ready');
  /* Anneau entier de `flood-1`, page par page (≤ 50 par lecture), plus anciennes d'abord. */
  const ring=()=>evaluate(`(async()=>{const all=[];let after=0;for(;;){
    const b=await (await fetch('/api/prefabs/events?object_id=flood-1&limit=50&after='+after,{cache:'no-store'})).json();
    all.push(...b.events);if(b.events.length<50)return all;after=b.events[b.events.length-1].seq}})()`);
  const before=(await ring()).length;
  /* (a) l'hôte : 100 sorties synchrones depuis le cadre. */
  const emitted=await frameEval(`(()=>{if(!window.jarvis||!document.querySelector('[role=checkbox]'))return null;
    for(let i=0;i<100;i++)jarvis.emit('checklist_completed',{count:2});return 100})()`);
  await sleep(2500);
  const hostRing=await ring();
  const hostConsole=out.console.filter(c=>/prefab_event_rate_limited|prefab_message_dropped/.test(c.text)).length;
  /* (b) Core : 200 envois simultanés par le relais (acteur forcé user). */
  await sleep(1200); // le seau de Core se remplit
  const coreFlood=await evaluate(`Promise.all(Array.from({length:200},()=>fetch('/api/prefabs/events',{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify({object_id:'flood-1',prefab:{id:'jarvis.checklist',version:1},
    event:'checklist_completed',payload:{count:2}})}).then(async r=>({status:r.status,body:await r.json().catch(()=>null)}))))
    .then(list=>{const by={};for(const x of list){const k=x.status+':'+(x.body&&(x.body.outcome||x.body.error||x.body.code||x.body.reason)||'?');by[k]=(by[k]||0)+1}return by})`);
  await sleep(1500);
  const afterCoreRing=await ring();
  const ok200=await evaluate(`fetch('/api/prefabs/events',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({object_id:'flood-1',prefab:{id:'jarvis.checklist',version:1},event:'checklist_completed',payload:{count:2}})}).then(r=>r.status)`);
  await command(archive('flood-1'));
  out.flood={host:{emitted,recordedFromFrame:hostRing.length-before,rateConsoleLines:hostConsole,outcomes:[...new Set(hostRing.map(e=>e.outcome))]},
    core:{sent:200,byStatus:coreFlood,ringAfter:afterCoreRing.length,afterBurstStatus:ok200}};
  out.final=await counters();
  out.pageErrors=out.console.filter(c=>c.type==='error'||c.type==='exception');
  out.ok=true;
}catch(error){
  out.error=String(error&&error.stack||error);
}finally{
  out.totalSeconds=Math.round((Date.now()-t0)/1000);
  writeFileSync(join(OUT,'stress-results.json'),JSON.stringify(out,null,1));
  chrome.kill();await sleep(800);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome tient encore un fichier */}
  console.log(JSON.stringify({ok:out.ok,error:out.error,cycles:out.cycles&&out.cycles.growth,simultaneous:out.simultaneous&&{live:out.simultaneous.live,paused:out.simultaneous.paused},flood:out.flood}));
  process.exit(0);
}
