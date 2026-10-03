/* Preuve navigateur de la reprise QA des Slices 04 et 06 : Chrome RÉEL sans tête
   (`--headless=new`, profil jetable `--user-data-dir`), piloté par CDP (harnais de
   la preuve S06), sur la page SERVIE par un vrai Control Center relié à un vrai
   Core isolés (ports de scratch 18963/18964). Le prefab de test `test.counter`
   est installé dans la bibliothèque de la racine de données avant le démarrage.

   Slice 04 (sortie <OUT4>) :
   - A3 : un compteur créé par la page avec `props: {}`, `data: {count: 3}` est
     stocké complété de ses défauts ;
   - A2 : le premier clic « +1 » est `applied` ;
   - A4 : deux écritures sur la même basis (émises dans le cadre) -> la seconde
     est `stale` ; le cadre reçoit `event_result` puis un `update` forcé,
     immédiatement (horodatages du cadre) ;
   - A6 : une checklist vidée par Jarvis reste une fenêtre après l'ajustement
     (cadre monté), pas une capsule.
   Slice 06 (sortie <OUT6>) :
   - B6 : 64 éléments de ~95 caractères ; la dernière ligne cochée à la souris
     après défilement dans le cadre, écrite dans Core ;
   - B3 : liste défilée en bas, Core injoignable (la page refuse le POST) -> la
     note (`role=status`) est visible dans la tête collée, en français ;
   - B2 : le POST retardé de 6,5 s -> note « pas encore confirmée » au bout de
     5 s, puis confirmation tardive : note effacée, coche gardée ;
   - captures dans les thèmes Circuit et Cosmos.

   Usage : node rework_probe.mjs <url du CC> <chrome.exe> <OUT4> <OUT6> <url de Core> <fichier du jeton> */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT4,OUT6,CORE,TOKEN_FILE]=process.argv;
const profile=mkdtempSync(join(tmpdir(),'jarvis-s46rw-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

function upsert(id,title,geometry,prefab){
  return {schema_version:1,op:'upsert_object',object_id:id,fields:{kind:'window',category:'research',representation:'window',
    geometry,payload:{title,summary:'',items:[],prefab}}};
}
const LONG=Array.from({length:64},(_,n)=>({id:`item-${String(n).padStart(2,'0')}`,
  label:(`Élément ${String(n).padStart(2,'0')} `+'à vérifier avant la livraison '.repeat(4)).slice(0,95)}));

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

const out4={console:[],steps:{}},out6={steps:{}};
try{
  const target=await debuggerTarget();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refused'))});
  let id=0;const pending=new Map();const contexts=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled'){
      const text=msg.params.args.map(a=>a.value??a.description??(a.preview?JSON.stringify(a.preview.properties.map(p=>[p.name,p.value])):'')).join(' ');
      out4.console.push({session:msg.sessionId?'frame':'page',type:msg.params.type,text:text.slice(0,300)});
    }
    if(msg.method==='Runtime.exceptionThrown')out4.console.push({session:msg.sessionId?'frame':'page',type:'exception',
      text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,300)});
    if(msg.method==='Target.attachedToTarget'){
      const s=msg.params.sessionId;
      send('Runtime.enable',{},s).catch(()=>{});
      send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{});
    }
    if(msg.method==='Runtime.executionContextCreated')contexts.set(`${msg.sessionId||''}:${msg.params.context.id}`,
      {session:msg.sessionId||null,id:msg.params.context.id,main:!!(msg.params.context.auxData&&msg.params.context.auxData.isDefault)});
    if(msg.method==='Runtime.executionContextDestroyed')contexts.delete(`${msg.sessionId||''}:${msg.params.executionContextId}`);
    if(msg.method==='Runtime.executionContextsCleared')for(const k of [...contexts.keys()])if(k.startsWith(`${msg.sessionId||''}:`))contexts.delete(k);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;
    const timer=setTimeout(()=>{pending.delete(mine);ko(new Error(`CDP ${method} timed out`))},15000);
    pending.set(mine,{ok:(v)=>{clearTimeout(timer);ok(v)},ko:(e)=>{clearTimeout(timer);ko(e)}});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,100)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);
    return r.result.value;
  };
  const until=async(check,ms=20000,label)=>{const deadline=Date.now()+ms;
    while(Date.now()<deadline){try{const v=await check();if(v)return v}catch(_){}await sleep(150)}
    throw new Error('never true: '+(label||check.toString().slice(0,120)))};
  /* Un cadre (origine opaque, hors processus) se lit dans sa session ; reconnu par une condition sur son document. */
  const inFrame=async(match,expression)=>{
    for(const ctx of [...contexts.values()]){
      if(!ctx.main)continue;
      try{const r=await send('Runtime.evaluate',{expression:`(${match})?(${expression}):null`,returnByValue:true,awaitPromise:true,contextId:ctx.id},ctx.session||undefined);
        if(r.exceptionDetails)continue;
        const value=r.result.value;
        if(value!==null&&value!==undefined)return value}catch(_){/* contexte parti */}
    }
    return null;
  };
  const box=(selector)=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;
    const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()`);
  const mouse=async(type,x,y,buttons)=>send('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:buttons??(type==='mouseReleased'?0:1),clickCount:1});
  const click=async(x,y)=>{await mouse('mouseMoved',x,y,0);await mouse('mousePressed',x,y);await mouse('mouseReleased',x,y)};
  const shot=async(dir,name,clip)=>{const r=await send('Page.captureScreenshot',clip?{format:'png',clip:{...clip,scale:1}}:{format:'png'});
    writeFileSync(join(dir,name),Buffer.from(r.data,'base64'));return name};
  const around=async(objectId)=>{const b=await box(`[data-object-id="${objectId}"]`);
    return {x:Math.max(0,b.x-14),y:Math.max(0,b.y-14),width:b.w+28,height:b.h+28}};
  const theme=(name)=>evaluate(`(JarvisThemeAPI.activate(${JSON.stringify(name)}),document.documentElement.dataset.jarvisTheme)`);
  const object=(objectId)=>evaluate(`fetch('/api/scene',{cache:'no-store'}).then(r=>r.json()).then(b=>{
    const o=b.snapshot.objects.find(o=>o.object_id===${JSON.stringify(objectId)});
    return o?{revision:b.revision,prefab:o.payload.prefab,geometry:o.geometry,representation:o.representation}:null})`);
  const ring=(objectId)=>evaluate(`fetch('/api/prefabs/events?object_id=${objectId}&limit=50',{cache:'no-store'}).then(r=>r.json()).then(b=>b.events.map(e=>[e.seq,e.event,e.outcome,e.reason||null]))`);
  const create=(command)=>evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},
      body:${JSON.stringify(JSON.stringify(command))}}).then(async r=>({status:r.status,body:await r.json()}))`);
  const token=readFileSync(TOKEN_FILE,'utf8').trim();
  const brain=async(command)=>{const r=await fetch(`${CORE}/v1/scene/commands`,{method:'POST',
    headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},body:JSON.stringify({...command,actor:'brain'})});
    return {status:r.status,body:await r.json()}};
  const frameRect=(objectId)=>box(`[data-object-id="${objectId}"] iframe`);
  const settled=async(objectId)=>{let last=null;for(let i=0;i<40;i++){const b=await frameRect(objectId);const k=b&&[b.x,b.y,b.w,b.h].map(Math.round).join(',');
    if(k&&k===last)return b;last=k;await sleep(250)}throw new Error('frame never settled')};

  await send('Page.enable');await send('Runtime.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate("!!window.JarvisScene&&!!window.JarvisThemeAPI"),30000,'scene page');
  await theme('circuit-board');

  /* ================================================================ Slice 04 */
  const S4=out4.steps;
  const COUNTER="typeof __jvLoad==='function'&&!!document.querySelector('button')&&!document.getElementById('ck')";
  S4.created=await create(upsert('ctr-1','Compteur',{x:30,y:-90,w:44,h:30},{id:'test.counter',version:1,props:{},data:{count:3}}));
  S4.storedDefaulted=(await object('ctr-1')).prefab;                       // A3
  await until(()=>inFrame(COUNTER,"document.body.textContent.includes('3')"),30000,'counter frame');
  await settled('ctr-1');
  /* Écoute posée dans le cadre (l'API publique du shim) : issues et mises à jour, horodatées. */
  await inFrame(COUNTER,`(window.__rw=[],jarvis.on('event_result',r=>__rw.push(['result',r.outcome,r.reason||null,performance.now()])),
    jarvis.on('update',c=>__rw.push(['update',!!c.changed.forced,c.data.count,performance.now()])),true)`);
  const button=await inFrame(COUNTER,"(()=>{const r=document.querySelector('button').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()");
  const f=await settled('ctr-1');
  S4.clickHit={frame:f,button,page:await evaluate(`(()=>{const e=document.elementFromPoint(${f.x+button.x},${f.y+button.y});return e?e.tagName+'.'+e.className:null})()`)};
  await click(f.x+button.x,f.y+button.y);                                  // A2 : premier clic
  S4.firstClick=await until(async()=>{const r=await ring('ctr-1');return r.length?r:null},8000,'first event');
  S4.afterFirstClick=(await object('ctr-1')).prefab.data;
  await until(()=>inFrame(COUNTER,"__rw.some(e=>e[0]==='update'&&e[2]===4)"),8000,'count 4 in frame');
  /* A4 : deux écritures sur la même basis, émises dans le cadre au même instant. */
  await inFrame(COUNTER,"(__rw.length=0,jarvis.emit('incremented',{count:7}),jarvis.emit('incremented',{count:8}),true)");
  S4.staleTrace=await until(()=>inFrame(COUNTER,"__rw.filter(e=>e[0]==='result').length>=2&&__rw.some(e=>e[1]===true)?__rw:null"),8000,'stale + forced');
  const staleAt=S4.staleTrace.find(e=>e[0]==='result'&&e[1]==='stale');
  const forcedAt=S4.staleTrace.find(e=>e[0]==='update'&&e[1]===true);
  S4.staleToForcedMs=staleAt&&forcedAt?Math.round((forcedAt[3]-staleAt[3])*10)/10:null;
  S4.ringAfterStale=await ring('ctr-1');
  S4.storedAfterStale=(await object('ctr-1')).prefab.data.count;
  S4.shotCounter=await shot(OUT4,'counter-after-stale.png',await around('ctr-1'));
  /* A6 : une checklist courte vidée par Jarvis reste une fenêtre (cadre monté) après l'ajustement. */
  S4.shortCreated=await create(upsert('ck-short','Liste courte',{x:-110,y:-90,w:56,h:60},{id:'jarvis.checklist',version:1,props:{},
    data:{items:[{id:'a',label:'Un'},{id:'b',label:'Deux'}]}}));
  await until(()=>inFrame("!!document.getElementById('ck')&&document.querySelectorAll('.ck-item').length===2","true"),30000,'short list');
  S4.brainEmptied=await brain(upsert('ck-short','Liste courte',undefined,{id:'jarvis.checklist',version:1,props:{},data:{items:[]}}));
  await sleep(3000);                                                         // resize du cadre + ajustement de la page
  S4.afterFit={stored:(await object('ck-short')).geometry,className:await evaluate(`document.querySelector('[data-object-id="ck-short"]').className`),
    iframes:await evaluate(`document.querySelectorAll('[data-object-id="ck-short"] iframe').length`),
    drawnHeight:(await box('[data-object-id="ck-short"]')).h,
    empty:await inFrame("!!document.getElementById('ck')&&!document.getElementById('ck-empty').hasAttribute('hidden')","document.getElementById('ck-empty').textContent")};
  S4.shotShort=await shot(OUT4,'short-list-after-fit.png',await around('ck-short'));
  S4.archivedShort=(await create({schema_version:1,op:'archive',object_id:'ck-short'})).body.outcome;

  /* ================================================================ Slice 06 */
  const S6=out6.steps;
  const LONGCK="!!document.getElementById('ck')&&document.querySelectorAll('.ck-item').length===64";
  S6.created=await create(upsert('ck-64','Livraison',{x:-40,y:-95,w:64,h:84},{id:'jarvis.checklist',version:1,props:{},data:{items:LONG}}));
  await until(()=>inFrame(LONGCK,"true"),30000,'64 rows');
  await sleep(900);await settled('ck-64');
  S6.shotTop=await shot(OUT6,'long-list-top.png',await around('ck-64'));
  /* B6 : dernière ligne amenée dans la vue du cadre, cliquée à la souris. */
  const lastPoint=async(index)=>{const fr=await frameRect('ck-64');
    const p=await inFrame(LONGCK,`(()=>{const row=document.querySelectorAll('.ck-item')[${index}];row.scrollIntoView({block:'nearest'});
      const r=row.querySelector('.ck-label').getBoundingClientRect();return {x:r.x+12,y:r.y+r.height/2}})()`);
    return {x:fr.x+p.x,y:fr.y+p.y}};
  let p=await lastPoint(63);await sleep(300);p=await lastPoint(63);
  await click(p.x,p.y);
  S6.storedLast=await until(async()=>{const o=await object('ck-64');return o.prefab.data.items[63].done?{revision:o.revision,done:o.prefab.data.items.filter(i=>i.done).length}:null},8000,'row 63 stored');
  S6.ringAfterLast=await ring('ck-64');
  /* B3 : Core injoignable (la page refuse le POST) : la note se lit dans la tête collée, liste défilée en bas. */
  await evaluate(`(window.__fetch=window.fetch,window.fetch=(u,o)=>String(u).includes('/api/prefabs/events')&&o&&o.method==='POST'
    ?Promise.reject(new TypeError('Failed to fetch')):window.__fetch(u,o),true)`);
  p=await lastPoint(62);await sleep(300);p=await lastPoint(62);
  await click(p.x,p.y);
  S6.unreachable=await until(()=>inFrame(LONGCK,`(()=>{const n=document.getElementById('ck-notice');if(!n.textContent)return null;
    const r=n.getBoundingClientRect(),h=document.getElementById('ck-head').getBoundingClientRect();
    return {notice:n.textContent,role:n.getAttribute('role'),scrollTop:document.scrollingElement.scrollTop,
      noticeTop:r.top,noticeBottom:r.bottom,viewport:innerHeight,headTop:h.top,
      headBg:getComputedStyle(document.getElementById('ck-head')).backgroundColor,
      row62:document.querySelectorAll('.ck-item')[62].getAttribute('aria-checked')}})()`),8000,'notice when unreachable');
  S6.shotScrolledNotice=await shot(OUT6,'long-list-scrolled-notice.png',await around('ck-64'));
  await evaluate("(window.fetch=window.__fetch,true)");
  /* B2 : POST retardé de 6,5 s : « pas encore confirmée » à 5 s, puis confirmation tardive. */
  await sleep(500);
  await evaluate(`(window.fetch=(u,o)=>String(u).includes('/api/prefabs/events')&&o&&o.method==='POST'
    ?new Promise(r=>setTimeout(r,6500)).then(()=>window.__fetch(u,o)):window.__fetch(u,o),true)`);
  p=await lastPoint(61);await sleep(300);p=await lastPoint(61);
  const t0=Date.now();
  await click(p.x,p.y);
  S6.pending=await until(()=>inFrame(LONGCK,`(()=>{const n=document.getElementById('ck-notice').textContent;
    return n.includes('pas encore')?{notice:n,row61:document.querySelectorAll('.ck-item')[61].getAttribute('aria-checked')}:null})()`),9000,'pending note');
  S6.pending.afterMs=Date.now()-t0;
  S6.shotPending=await shot(OUT6,'late-confirmation-pending.png',await around('ck-64'));
  S6.late=await until(()=>inFrame(LONGCK,`(()=>{const n=document.getElementById('ck-notice').textContent;
    const c=document.querySelectorAll('.ck-item')[61].getAttribute('aria-checked');return !n&&c==='true'?{notice:n,row61:c}:null})()`),12000,'late confirmation');
  S6.late.afterMs=Date.now()-t0;
  S6.storedLate=(await object('ck-64')).prefab.data.items[61].done;
  S6.shotLate=await shot(OUT6,'late-confirmation-confirmed.png',await around('ck-64'));
  await evaluate("(window.fetch=window.__fetch,true)");
  /* Thèmes. */
  S6.cosmos=await theme('cosmos');await sleep(500);
  S6.shotCosmos=await shot(OUT6,'long-list-cosmos.png',await around('ck-64'));
  S6.circuit=await theme('circuit-board');await sleep(400);
  S6.shotCircuit=await shot(OUT6,'long-list-circuit.png',await around('ck-64'));
  S6.ringFinal=await ring('ck-64');
  out4.steps.problems=out4.console.filter(c=>c.type==='exception'||c.type==='error'||/prefab_error/.test(c.text));
  ws.close();
}catch(error){out4.error=String(error&&error.stack||error)}
finally{
  chrome.kill();await sleep(300);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome lâche son profil un peu plus tard */}
  out6.console=out4.console;
  writeFileSync(join(OUT4,'browser-results.json'),JSON.stringify(out4,null,2));
  writeFileSync(join(OUT6,'browser-results.json'),JSON.stringify(out6,null,2));
  console.log(JSON.stringify({error:out4.error||null,s4:Object.keys(out4.steps),s6:Object.keys(out6.steps)}));
}
