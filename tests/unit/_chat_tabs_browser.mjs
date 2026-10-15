/* Harnais CDP multi-onglets pour `test_control_center_chat_tabs_browser.py` (Slice 06, reprise QA).

   Chrome partage SIX connexions HTTP/1.1 par origine entre tous ses onglets.
   La page du Control Center tient déjà des attentes longues (commandes plein
   écran, explorateur, chronologie…) : une attente de plus par onglet affame
   les requêtes courtes (`/api/status`, `/api/chat/state`, l'envoi). Ce
   harnais ouvre N onglets RÉELS sur un serveur HTTP qui tient vraiment ses
   attentes longues, mesure la latence de `/api/status` dans chacun et envoie
   un message depuis un onglet suiveur.

   Usage : node _chat_tabs_browser.mjs <baseUrl> <chrome.exe> <planJSON>
   Plan : {chatTabs: n, timelineTab: bool, settleMs, sendFrom: index, text}
   Sortie : JSON {latency, roles, inflight, send, bubbles, errors}. */
import {spawn, execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,BASE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const profile=mkdtempSync(join(tmpdir(),'jarvis-chat-tabs-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{const v=await (await fetch(url)).json();if(v)return v}catch(_){/* pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
async function openTab(url){
  const t=await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`,{method:'PUT'})).json();
  const ws=new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const tab={ws,errors:[],requests:new Map(),all:[]};
  ws.onmessage=e=>{
    const m=JSON.parse(e.data);
    if(m.id&&pending.has(m.id)){const {ok,ko}=pending.get(m.id);pending.delete(m.id);m.error?ko(new Error(JSON.stringify(m.error))):ok(m.result);return}
    if(m.method==='Runtime.exceptionThrown')tab.errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
    else if(m.method==='Network.requestWillBeSent'){
      const url=m.params.request.url.replace(/^https?:\/\/[^/]+/,'');
      tab.requests.set(m.params.requestId,{t:Date.now(),url});tab.all.push(m.params.request.method+' '+url);
    }
    else if(m.method==='Network.loadingFinished'||m.method==='Network.loadingFailed')tab.requests.delete(m.params.requestId);
  };
  tab.send=(method,params={})=>new Promise((ok,ko)=>{const k=++id;pending.set(k,{ok,ko});ws.send(JSON.stringify({id:k,method,params}))});
  tab.eval=async expr=>{
    const r=await tab.send('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  tab.until=async(expr,ms)=>{const end=Date.now()+ms;while(Date.now()<end){try{if(await tab.eval(expr))return true}catch(_){/* page en cours */}await sleep(100)}return false};
  await tab.send('Page.enable');await tab.send('Runtime.enable');await tab.send('Network.enable');
  await tab.send('Emulation.setFocusEmulationEnabled',{enabled:true}).catch(()=>{});
  await tab.send('Emulation.setDeviceMetricsOverride',{width:1280,height:800,deviceScaleFactor:1,mobile:false});
  await tab.send('Page.navigate',{url});
  await tab.until(`document.readyState==='complete'&&!!(window.JarvisChat&&window.JarvisChat.instance)`,20000);
  return tab;
}
const latency=tab=>Promise.race([tab.eval(`(async()=>{const t=performance.now();const r=await fetch('/api/status',{cache:'no-store'});await r.text();return Math.round(performance.now()-t)})()`),
  sleep(9000).then(()=>9000)]);

try{
  await poll(`http://127.0.0.1:${port}/json/version`);
  const tabs=[];
  for(let i=0;i<plan.chatTabs;i+=1){
    const tab=await openTab(BASE+'/');
    await tab.eval(plan.chatOpen===false?`JarvisChat.close();1`:`JarvisChat.open();1`);
    tabs.push(tab);
    await sleep(800);
  }
  if(plan.timelineTab){
    const tab=await openTab(BASE+'/');
    await tab.eval(`JarvisChat.close();document.getElementById('openTimeline').click();1`);
    tabs.push(tab);
  }
  await sleep(plan.settleMs||5000);
  const out={latency:[],roles:[],inflight:[],errors:[]};
  /* Attentes longues DEMANDÉES par chaque onglet (paramètre d'attente non nul), par route : comparable chat ouvert / fermé. */
  out.held=tabs.map(tab=>tab.all.filter(u=>/[?&](wait_s|wait_ms|wait)=(?!0(&|$))/.test(u)).map(u=>u.split('?')[0].replace(/^GET /,'')));
  out.chatAsks=tabs.map(tab=>tab.all.filter(u=>u.includes('/api/chat/')||u.includes('projection=chat')));
  for(const tab of tabs)out.latency.push(await latency(tab));
  for(const tab of tabs){
    out.roles.push(await tab.eval(`JarvisChat.isOpen()?JarvisChat.instance.snapshot().feed.role:'closed'`));
    out.inflight.push([...tab.requests.values()].filter(r=>Date.now()-r.t>1500).map(r=>r.url.slice(0,80)));
    out.errors.push(tab.errors);
  }
  if(plan.chatOpen===false){process.stdout.write(JSON.stringify(out));for(const tab of tabs){try{tab.ws.close()}catch(_){/* fermé */}}process.exit(0)}
  const from=tabs[plan.sendFrom];
  await from.eval(`document.getElementById('chatInput').focus();1`);
  await from.send('Input.insertText',{text:plan.text});
  await from.send('Input.dispatchKeyEvent',{type:'keyDown',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13,text:'\r'});
  await from.send('Input.dispatchKeyEvent',{type:'keyUp',key:'Enter',code:'Enter',windowsVirtualKeyCode:13,nativeVirtualKeyCode:13});
  const t0=Date.now();
  const seen=`[...document.querySelectorAll('#chatLog .chat-msg.user')].some(li=>li.textContent.includes(${JSON.stringify(plan.text)}))`;
  out.send={sender:await from.until(seen,12000),senderMs:Date.now()-t0};
  out.send.others=[];
  for(let i=0;i<plan.chatTabs;i+=1)if(i!==plan.sendFrom)out.send.others.push(await tabs[i].until(seen,8000));
  out.send.view=await from.eval(`JarvisChat.instance.snapshot().view`);
  out.send.sendError=await from.eval(`JarvisChat.instance.snapshot().sendError`);
  out.eventsRequests=await Promise.all(tabs.slice(0,plan.chatTabs).map(t=>t.eval(`JarvisChat.instance.snapshot().stats.eventReads`)));
  for(const tab of tabs){try{tab.ws.close()}catch(_){/* fermé */}}
  process.stdout.write(JSON.stringify(out));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));
  if(process.platform==='win32'&&chrome.pid){try{execFileSync('taskkill',['/PID',String(chrome.pid),'/T','/F'],{stdio:'ignore'})}catch(_){chrome.kill()}}
  else chrome.kill();
  await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){/* Windows tient le dossier */}
}
