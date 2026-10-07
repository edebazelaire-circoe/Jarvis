/* Preuve navigateur de la Slice 03 (runtime des prefabs) : Chrome RÉEL (sans tête,
   piloté par CDP, même méthode que tests/unit/_workspace_browser.mjs) sur la page
   SERVIE par un vrai Control Center relié à un vrai Core isolés (ports de scratch).

   Dans la page : un conteneur de scratch, `JarvisPrefabHost.createPrefabHost` avec
   `bundleFetcher(fetch)` (relais /api/prefabs/.../bundle), puis trois montages :
   test.counter (catalogue seul), test.netprobe (sondes du bac à sable),
   test.netprobe avec `crash: true` (bande d'erreur). Le DOM de chaque cadre est
   lu par CDP (monde isolé du cadre, ou cible attachée si le cadre est hors processus).

   Usage : node browser_probe.mjs <url> <chrome.exe> <dossier de sortie>
   Sortie : <dossier>/browser-results.json, <dossier>/prefab-runtime.png */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT]=process.argv;
const profile=mkdtempSync(join(tmpdir(),'jarvis-pfb-cdp-'));
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

const out={console:[],log:[],frames:{}};
try{
  const target=await debuggerTarget();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refused'))});
  let id=0;const pending=new Map();const sessions=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled')out.console.push({session:msg.sessionId||'page',type:msg.params.type,
      text:msg.params.args.map(a=>a.value??a.description??'').join(' ').slice(0,400)});
    if(msg.method==='Log.entryAdded')out.log.push({session:msg.sessionId||'page',source:msg.params.entry.source,
      level:msg.params.entry.level,text:msg.params.entry.text.slice(0,400)});
    if(msg.method==='Runtime.exceptionThrown')out.console.push({session:msg.sessionId||'page',type:'exception',
      text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,400)});
    if(msg.method==='Target.attachedToTarget'){
      const s=msg.params.sessionId;sessions.set(s,msg.params.targetInfo);
      for(const m of ['Runtime.enable','Log.enable'])send(m,{},s).catch(()=>{});
      send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{});
    }
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression,extra={})=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true,...extra.params},extra.session);
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,100)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);
    return r.result.value;
  };
  const until=async(expression,ms=20000)=>{const deadline=Date.now()+ms;
    while(Date.now()<deadline){try{if(await evaluate(expression))return}catch(_){}await sleep(100)}
    throw new Error('never true: '+expression)};

  await send('Page.enable');await send('Runtime.enable');await send('Log.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1280,height:900,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until("!!(window.JarvisPrefabHost&&window.JarvisPrefabProtocol&&document.body)");

  out.setup=await evaluate(`(()=>{
    const stage=document.createElement('div');stage.id='pfbStage';
    stage.style.cssText='position:fixed;left:24px;top:24px;z-index:2147483600;display:flex;gap:16px;align-items:flex-start;'+
      'padding:14px;background:#05080b;border:1px solid rgba(110,231,255,.25);border-radius:10px;font:12px ui-monospace,Consolas,monospace;color:#dcecf4';
    window.__pfb={logs:[],resizes:[],preview:[]};
    const host=JarvisPrefabHost.createPrefabHost({fetchBundle:JarvisPrefabHost.bundleFetcher(fetch.bind(window)),document,window,mode:'preview',
      log:(k,d)=>__pfb.logs.push({key:k,data:d}),onResize:(o,h)=>__pfb.resizes.push([o,h]),onPreviewEvent:(e)=>__pfb.preview.push(e)});
    window.__pfb.host=host;
    const cards={};
    for(const [id,label] of [['obj_counter','test.counter@1'],['obj_probe','test.netprobe@1'],['obj_crash','test.netprobe@1 crash']]){
      const card=document.createElement('div');card.style.cssText='width:360px;border-radius:7px;background:rgba(4,10,15,.9);box-shadow:inset 0 0 0 1px rgba(110,231,255,.2)';
      const head=document.createElement('div');head.textContent=label;head.style.cssText='padding:11px 13px 8px;font-weight:600;color:#f1f8fb';
      const slot=document.createElement('div');slot.id='slot_'+id;
      card.append(head,slot);stage.append(card);cards[id]=slot;
    }
    document.body.append(stage);
    host.mount(cards.obj_counter,{object_id:'obj_counter',title:'Counter',prefab:{id:'test.counter',version:1},
      props:{label:'Count',accent:'#6fe3a4'},data:{count:3,notes:'Mounted **from the catalogue** only.'}});
    host.mount(cards.obj_probe,{object_id:'obj_probe',title:'Probe',prefab:{id:'test.netprobe',version:1},
      props:{accent:'#ffb85c',crash:false},data:{notes:'Each line is **one attempt** to leave the sandbox.'}});
    host.mount(cards.obj_crash,{object_id:'obj_crash',title:'Crash',prefab:{id:'test.netprobe',version:1},
      props:{accent:'#ff6b7d',crash:true},data:{notes:'This one throws in its init handler.'}});
    return true;
  })()`);
  await until("['obj_counter','obj_probe','obj_crash'].every(id=>__pfb.host.state(id)==='ready'||__pfb.host.state(id)==='error')");
  await sleep(1500);  // fetch rejection and violation reports are asynchronous

  out.page=await evaluate(`(()=>{
    const frames=[...document.querySelectorAll('#pfbStage iframe')];
    return {
      sandbox:frames.map(f=>f.getAttribute('sandbox')),
      srcdocStartsWithCsp:frames.map(f=>/^<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy"/.test(f.srcdoc)),
      heights:frames.map(f=>f.style.height),
      states:['obj_counter','obj_probe','obj_crash'].map(id=>[id,__pfb.host.state(id),__pfb.host.height(id)]),
      bands:[...document.querySelectorAll('#pfbStage .sc-prefab-error')].map(b=>b.textContent),
      logs:__pfb.logs,resizes:__pfb.resizes,preview:__pfb.preview,stats:__pfb.host.stats(),
      parentCanBeReadByFrame:false
    };
  })()`);

  /* DOM de chaque cadre : les cadres sandboxés tournent hors processus (cibles attachées) ;
     lu dans la session de chaque cadre, contexte principal du cadre. */
  for(const [session,info] of sessions){
    if(info.url!=='about:srcdoc')continue;
    try{
      out.frames[session]=await evaluate("({origin:location.origin,jarvis:typeof window.jarvis,props:window.jarvis&&window.jarvis.props,"+
        "probes:[...document.querySelectorAll('[data-probe]')].map(li=>[li.getAttribute('data-probe'),li.getAttribute('data-outcome'),li.textContent]),"+
        "accent:getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim(),"+
        "button:(()=>{const b=document.querySelector('button');if(!b)return null;const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()})",
        {session});
    }catch(error){out.frames[session]={error:String(error.message||error)}}
  }
  out.attachedTargets=[...sessions.values()].map(t=>({type:t.type,url:t.url}));

  /* Un vrai clic (CDP Input, événement de confiance) sur « +1 » du compteur : l'événement d'état
     part du cadre, l'hôte en mode aperçu le garde localement avec sa base (jamais envoyé à Core). */
  const counter=Object.values(out.frames).find(f=>f&&f.button);
  if(counter){
    const rect=await evaluate("(()=>{const r=document.querySelector('#slot_obj_counter iframe').getBoundingClientRect();return {x:r.x,y:r.y}})()");
    const x=rect.x+counter.button.x,y=rect.y+counter.button.y;
    for(const type of ['mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,x,y,button:'left',clickCount:1});
    await until("__pfb.preview.some(e=>e.event==='incremented')",5000);
    out.click=await evaluate("__pfb.preview.filter(e=>e.event==='incremented')");
  }

  const shot=await send('Page.captureScreenshot',{format:'png',clip:{x:0,y:0,width:1200,height:520,scale:1}});
  writeFileSync(join(OUT,'prefab-runtime.png'),Buffer.from(shot.data,'base64'));
  ws.close();
}catch(error){out.error=String(error&&error.stack||error)}
finally{
  chrome.kill();await sleep(300);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome lâche son profil un peu plus tard */}
  writeFileSync(join(OUT,'browser-results.json'),JSON.stringify(out,null,2));
  console.log(JSON.stringify({error:out.error||null,frames:Object.keys(out.frames).length}));
}
