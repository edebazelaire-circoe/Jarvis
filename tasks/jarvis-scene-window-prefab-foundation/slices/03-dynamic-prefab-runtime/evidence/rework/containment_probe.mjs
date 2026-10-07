/* S3 rework — preuve navigateur du confinement des cadres de prefab (vrai Chrome headless, CDP).
   Usage :
     node containment_probe.mjs hostile    <url du CC> <chrome.exe> <dossier de sortie> <port écouteur>
     node containment_probe.mjs visualizer <url de la page> <chrome.exe> <dossier de sortie> <port écouteur>
   `hostile` : page servie par le vrai CC (Core + CC isolés), prefabs hostiles de
   `install_hostile.py`, écouteur HTTP qui journalise toute requête (aucune attendue).
   `visualizer` : page `index` avec un visualiseur configuré servi par l'écouteur
   (`/faces/board/`) : le cadre du visualiseur charge, une navigation de cadre
   vers une autre origine est bloquée. */
import {spawn} from 'node:child_process';
import http from 'node:http';
import {existsSync, mkdirSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';

const [,,MODE,URL_,CHROME,OUT,LISTEN]=process.argv;
/* Profil Chrome jetable hors du dépôt : `PROBE_PROFILE_DIR` (sinon à côté des résultats). */
const profile=join(process.env.PROBE_PROFILE_DIR||OUT,`chrome-profile-${MODE}`);
mkdirSync(profile,{recursive:true});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const requests=[];
const VIZ=`<!doctype html><title>fake visualizer</title><body>VISUALIZER<script>parent.postMessage({visualizer:'loaded'},'*')</script>`;
const server=http.createServer((req,res)=>{
  requests.push({method:req.method,url:req.url.slice(0,200),dest:req.headers['sec-fetch-dest']||null});
  res.writeHead(200,{'content-type':'text/html'});
  res.end(req.url.startsWith('/faces/board/')?VIZ:'<p>remote page</p>');
});
await new Promise(ok=>server.listen(Number(LISTEN),'127.0.0.1',ok));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});

async function debuggerTarget(){
  const file=join(profile,'DevToolsActivePort');
  const deadline=Date.now()+60000;
  while(Date.now()<deadline){
    if(existsSync(file)){
      const port=readFileSync(file,'utf8').split('\n')[0].trim();
      try{const page=(await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');if(page)return page}catch(_){}
    }
    await sleep(100);
  }
  throw new Error('Chrome debugger never came up');
}

const out={mode:MODE,console:[],log:[],steps:{}};
try{
  const ws=new WebSocket((await debuggerTarget()).webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refused'))});
  let id=0;const pending=new Map();
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled')out.console.push(msg.params.args.map(a=>a.value??a.description??'').join(' ').slice(0,200));
    if(msg.method==='Log.entryAdded')out.log.push({source:msg.params.entry.source,level:msg.params.entry.level,text:msg.params.entry.text.slice(0,240)});
    if(msg.method==='Target.attachedToTarget'){
      const s=msg.params.sessionId;
      for(const m of ['Runtime.enable','Log.enable'])send(m,{},s).catch(()=>{});
      send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{});
    }
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  const evaluate=async(expression)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,80)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);
    return r.result.value;
  };
  const until=async(expression,ms=20000)=>{const deadline=Date.now()+ms;
    while(Date.now()<deadline){try{if(await evaluate(expression))return true}catch(_){}await sleep(100)}return false};

  await send('Page.enable');await send('Runtime.enable');await send('Log.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.addScriptToEvaluateOnNewDocument',{source:"window.__msgs=[];addEventListener('message',e=>{if(e.data&&e.data.visualizer)__msgs.push({data:e.data,origin:e.origin})})"});
  await send('Page.navigate',{url:URL_});
  await until("document.readyState==='complete'");
  out.steps.header=await evaluate(`fetch(location.href).then(r=>r.headers.get('content-security-policy'))`);

  if(MODE==='visualizer'){
    await sleep(2500);
    out.steps.visualizer=await evaluate(`({iframe:(document.querySelector('iframe.face')||{}).src||null,messages:__msgs})`);
    // Une navigation de cadre vers une AUTRE origine que le visualiseur reste bloquée.
    await evaluate(`(()=>{window.__loads=0;const f=document.createElement('iframe');f.setAttribute('sandbox','allow-scripts');
      f.addEventListener('load',()=>{__loads++});f.id='navtest';
      f.srcdoc='<!doctype html><body><script>setTimeout(()=>{location.href="http://127.0.0.1:18973/nav-other-origin"},100)<\\/script>';
      document.body.appendChild(f);return true})()`);
    await sleep(2000);
    out.steps.otherOrigin={loads:await evaluate('window.__loads')};
  }else{
    await until("!!(window.JarvisPrefabHost&&window.JarvisPrefabProtocol&&document.body)");
    await evaluate(`(()=>{
      const stage=document.createElement('div');stage.id='qaStage';
      stage.style.cssText='position:fixed;left:8px;top:8px;z-index:2147483600;display:flex;flex-wrap:wrap;gap:8px;width:1580px;background:#05080b;color:#dcecf4;font:11px monospace;padding:8px';
      window.__qa={logs:[],resizes:0,opened:[],gaps:[],slots:{}};
      let last=performance.now();setInterval(()=>{const t=performance.now();__qa.gaps.push(Math.round(t-last));last=t},50);
      const host=JarvisPrefabHost.createPrefabHost({fetchBundle:JarvisPrefabHost.bundleFetcher(fetch.bind(window)),document,window,mode:'preview',
        log:(k,d)=>__qa.logs.push({key:k,data:JSON.parse(JSON.stringify(d))}),onResize:()=>{__qa.resizes++},onPreviewEvent:()=>{},
        openUrl:(u)=>__qa.opened.push(u)});
      __qa.host=host;document.body.append(stage);
      __qa.mount=(oid,pid,data)=>{const card=document.createElement('div');card.style.cssText='width:300px;border:1px solid #234;padding:4px';
        const h=document.createElement('div');h.textContent=oid+' — '+pid;const slot=document.createElement('div');slot.id='slot_'+oid;card.append(h,slot);stage.append(card);
        __qa.slots[oid]=slot;host.mount(slot,{object_id:oid,title:oid,prefab:{id:pid,version:1},props:{label:'Count'},data:data||{}})};
      return true})()`);
    await evaluate(`(()=>{__qa.mount('obj_counter','test.counter',{count:3});
      __qa.mount('obj_nav','qa.navexfil',{notes:'SECRET-NOTES-123'});
      __qa.mount('obj_area','qa.domarea',{notes:'SECRET-AREA-456'});
      __qa.mount('obj_reready','qa.reready',{notes:'reready'});
      __qa.mount('obj_open','qa.openlocal',{notes:'open'});return true})()`);
    await sleep(5000);
    const snapshot=`({states:Object.fromEntries(Object.keys(__qa.slots).map(i=>[i,__qa.host.state(i)])),
      frames:Object.fromEntries(Object.keys(__qa.slots).map(i=>[i,__qa.slots[i].querySelectorAll('iframe').length])),
      bands:Object.fromEntries(Object.keys(__qa.slots).map(i=>[i,(__qa.slots[i].querySelector('.sc-prefab-error')||{}).textContent||null])),
      errors:__qa.logs.filter(l=>l.key==='scene.prefab_error').map(l=>[l.data.object_id,l.data.reason,l.data.message]),
      opened:__qa.opened.slice(),stats:__qa.host.stats()})`;
    out.steps.afterHostile=await evaluate(snapshot);
    out.steps.requestsAfterHostile=requests.slice();
    // F1 : « Recharger » remonte un cadre neuf, et la même violation se reproduit (sans requête).
    await evaluate(`(()=>{__qa.slots.obj_nav.querySelector('.sc-prefab-retry').click();return true})()`);
    await sleep(3000);
    out.steps.afterRetry=await evaluate(`({state:__qa.host.state('obj_nav'),errors:__qa.logs.filter(l=>l.key==='scene.prefab_error'&&l.data.object_id==='obj_nav').length})`);
    // F2 : 64 MiB + 2000 resize.
    await evaluate(`(()=>{__qa.gaps.length=0;__qa.resizes=0;__qa.mount('obj_big','qa.bigmsg',{notes:'big'});return true})()`);
    await sleep(6000);
    out.steps.afterBig=await evaluate(`({state:__qa.host.state('obj_big'),maxGapMs:Math.max(...__qa.gaps),resizes:__qa.resizes,
      band:(__qa.slots.obj_big.querySelector('.sc-prefab-error')||{}).textContent||null,
      dropped:__qa.logs.filter(l=>l.data&&l.data.object_id==='obj_big'&&l.key==='scene.prefab_message_dropped').map(l=>l.data.reason),
      errorLen:(__qa.logs.find(l=>l.key==='scene.prefab_error'&&l.data.object_id==='obj_big')||{data:{message:''}}).data.message.length})`);
    out.steps.final=await evaluate(snapshot);
    const shot=await send('Page.captureScreenshot',{format:'png',clip:{x:0,y:0,width:1600,height:520,scale:1}});
    writeFileSync(join(OUT,'containment.png'),Buffer.from(shot.data,'base64'));
  }
  out.inits=out.console.filter(t=>t.startsWith('INIT-RECEIVED')).reduce((a,t)=>{const k=t.split(' ')[1];a[k]=(a[k]||0)+1;return a},{});
  ws.close();
}catch(error){out.error=String(error&&error.stack||error)}
finally{
  out.requests=requests;
  chrome.kill();await sleep(500);server.close();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){}
  writeFileSync(join(OUT,`containment-${MODE}.json`),JSON.stringify(out,null,2));
  console.log(JSON.stringify({error:out.error||null,requests}));
  process.exit(0);
}
