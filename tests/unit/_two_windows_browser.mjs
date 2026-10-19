/* Harnais CDP « deux fenêtres visibles » sur un VRAI Control Center (Slice 08 de la refonte roue/Dossier, QA B1).

   Chrome partage six connexions HTTP/1.1 par origine entre toutes ses fenêtres. Ce harnais ouvre DEUX fenêtres
   (`Target.createTarget {newWindow:true}`) sur la page servie, mesure dans chacune la durée de chaque lecture de
   `/api/status` (enveloppe de `fetch` posée avant tout script), puis, après un temps de repos, demande une
   ouverture du Dossier comme le ferait l'outil `dossier_view` (POST sans Origin, comme le serveur MCP) et relève
   combien de pages l'ont exécutée.

   Usage : node _two_windows_browser.mjs <url> <chrome.exe> <planJSON>
     plan : {settleMs, sampleMs, width, height, nav:{board_id, entry_id}}
   Sortie : {pages:[{status:[ms...], stats, docs, visibility}], receipt:{status, body, ms}} */
import {spawn} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit} from './_cdp_profile.mjs';

const [,,URL_,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const profile=mkdtempSync(join(tmpdir(),'jarvis-two-windows-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions',
  '--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows',
  'about:blank'],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);

async function poll(url){
  for(let i=0;i<100;i+=1){try{const r=await fetch(url);if(r.ok)return await r.json()}catch(_e){/* Chrome démarre */}await sleep(100)}
  throw new Error('Chrome injoignable');
}

const TIMING=`(()=>{window.__statusMs=[];window.__statusSince=null;const real=window.fetch.bind(window);
  window.__inflight={};
  window.fetch=(input,init)=>{const url=String(input&&input.url||input);const p=real(input,init);
    let key;try{key=new URL(url,location.href).pathname}catch(_e){key=url}window.__inflight[key]=(window.__inflight[key]||0)+1;
    const done=()=>{window.__inflight[key]-=1};p.then(done,done);
    if(url.includes('/api/status')){const t0=performance.now();
      p.then(()=>{if(window.__statusSince!==null&&t0>=window.__statusSince)window.__statusMs.push(Math.round(performance.now()-t0))},
             ()=>{if(window.__statusSince!==null&&t0>=window.__statusSince)window.__statusMs.push(Math.round(performance.now()-t0))})}
    return p};})()`;

try{
  const version=await poll(`http://127.0.0.1:${port}/json/version`);
  const ws=new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refusé'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}};
  const send=(method,params={},sessionId)=>new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))});
  const evaluate=async(sessionId,expression)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},sessionId);
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const sessions=[];
  for(let i=0;i<2;i+=1){
    const {targetId}=await send('Target.createTarget',{url:'about:blank',newWindow:true,width:plan.width,height:plan.height});
    const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
    await send('Page.enable',{},sessionId);await send('Runtime.enable',{},sessionId);
    await send('Emulation.setFocusEmulationEnabled',{enabled:true},sessionId);
    await send('Emulation.setDeviceMetricsOverride',{width:plan.width,height:plan.height,deviceScaleFactor:1,mobile:false},sessionId);
    await send('Page.addScriptToEvaluateOnNewDocument',{source:TIMING},sessionId);
    await send('Page.navigate',{url:URL_},sessionId);
    sessions.push(sessionId);
  }
  await sleep(plan.settleMs);
  for(const s of sessions)await evaluate(s,'window.__statusSince=performance.now();1');
  await sleep(Math.round(plan.sampleMs/2));
  const t0=Date.now();
  let receipt;
  try{
    const r=await fetch(new URL('/api/dossier/navigation/commands',URL_),{method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify(plan.nav)});
    receipt={status:r.status,body:await r.json().catch(()=>null),ms:Date.now()-t0};
  }catch(error){receipt={status:0,error:String(error),ms:Date.now()-t0}}
  await sleep(Math.round(plan.sampleMs/2));
  const pages=[];
  for(const s of sessions)pages.push(await evaluate(s,`(()=>({status:window.__statusMs.slice(),
    stats:window.JarvisDossier?JarvisDossier.channel.stats():null,visibility:document.visibilityState,
    inflight:Object.fromEntries(Object.entries(window.__inflight).filter(([,n])=>n>0)),
    docs:[...document.querySelectorAll('#dossierView article.dsr-doc')].map(a=>a.dataset.entry)}))()`));
  process.stdout.write(JSON.stringify({pages,receipt}));
  ws.close();
}finally{
  try{chrome.kill()}catch(_e){/* déjà parti */}
}
