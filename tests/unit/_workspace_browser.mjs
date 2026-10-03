/* Harnais CDP pour `test_workspace_manager_browser.py` (board-memory-workspace-inspector, Slice 07).

   Chrome sans tete ouvre la page SERVIE par un vrai Control Center relie a un
   vrai Core (aucun double de `fetch`) et joue un plan : clics, saisies,
   touches reelles, attentes sur une condition, captures d'ecran. Chaque etape
   est une expression evaluee dans la page.

   AUCUNE ATTENTE A L'AVEUGLE. Sous charge (machine chargee, premier
   lancement de Chrome), une pause fixe est soit trop courte (echec
   intermittent), soit trop longue. Tout ce qui attend attend une CONDITION,
   avec un plafond large : le port de debogage de Chrome (lu dans
   `DevToolsActivePort`, jamais un port tire au hasard qui peut etre pris),
   la page chargee et le module installe, puis chaque `wait` du plan. Un
   plafond depasse dit quelle condition, apres combien de temps, et ce que le
   panneau montrait.

   Usage : node _workspace_browser.mjs <url> <chrome.exe> <planJSON> <dossier des captures>
   Plan : {width, height, waitMs?, steps:[{do}|{wait, ms?}|{get, expr}|{shot}|{key}]}
   `key` : une touche REELLE (CDP `Input.dispatchKeyEvent`, evenement de
   confiance : Entree active le bouton focalise, Echap passe par la page).
   Sortie : {results, console, waits} en JSON ; `waits` donne la duree de
   chaque attente (la plus longue dit ou la charge se fait sentir). */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,PLAN,SHOTS]=process.argv;
const plan=JSON.parse(PLAN);
const WAIT_MS=plan.waitMs??45000;
const BOOT_MS=60000;
const profile=mkdtempSync(join(tmpdir(),'jarvis-wsp-cdp-'));
const chrome=spawn(CHROME,[
  '--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions',
  '--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const KEYS={Enter:{code:'Enter',windowsVirtualKeyCode:13,text:'\r'},Escape:{code:'Escape',windowsVirtualKeyCode:27},
  Tab:{code:'Tab',windowsVirtualKeyCode:9}};

try{
  const target=await debuggerTarget();
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
  const waits=[];
  const until=async(expression,ms,label)=>{
    const started=Date.now(),deadline=started+ms;
    while(Date.now()<deadline){
      let ok=false;
      try{ok=await evaluate(expression)}catch(_){/* page en cours de chargement : on reessaie */}
      if(ok){waits.push({wait:label||expression.slice(0,100),ms:Date.now()-started});return}
      await sleep(100);
    }
    let seen='';
    try{seen=await evaluate("[(document.getElementById('wspStatus')||{textContent:''}).textContent,(document.getElementById('wspPanel')||{textContent:''}).textContent.slice(0,600)].join(' | ')")}catch(_){/* page perdue */}
    throw new Error(`condition jamais vraie en ${Math.round((Date.now()-started)/1000)} s : ${expression}\nla page montrait : ${seen}`);
  };
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:plan.width,height:plan.height,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until("document.readyState==='complete'&&!!window.JarvisWorkspace&&!!document.getElementById('openWorkspace')",BOOT_MS,'page chargee');
  const results={};
  for(const step of plan.steps){
    if(step.do!==undefined){await evaluate(step.do);if(step.ms)await sleep(step.ms);continue}
    if(step.key!==undefined){
      const k=KEYS[step.key];
      if(!k)throw new Error(`touche inconnue du harnais : ${step.key}`);
      await send('Input.dispatchKeyEvent',{type:'keyDown',key:step.key,...k});
      await send('Input.dispatchKeyEvent',{type:'keyUp',key:step.key,code:k.code,windowsVirtualKeyCode:k.windowsVirtualKeyCode});
      continue;
    }
    if(step.wait!==undefined){await until(step.wait,step.ms??WAIT_MS);continue}
    if(step.get!==undefined){results[step.get]=await evaluate(step.expr);continue}
    if(step.shot!==undefined){
      /* Deux images peintes : la capture montre l'etat atteint, pas un rendu a moitie fait. */
      await evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(()=>r(true))))');
      const shot=await send('Page.captureScreenshot',{format:'png'});
      writeFileSync(join(SHOTS,step.shot),Buffer.from(shot.data,'base64'));
      results[`shot:${step.shot}`]=true;
    }
  }
  ws.close();
  process.stdout.write(JSON.stringify({results,console:consoleLines,waits}));
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient le dossier */}
}

/* Chrome ecrit le port choisi dans `DevToolsActivePort` de son profil. */
async function debuggerTarget(){
  const file=join(profile,'DevToolsActivePort'),deadline=Date.now()+BOOT_MS;
  let port=null;
  while(Date.now()<deadline){
    if(!port&&existsSync(file)){
      const first=readFileSync(file,'utf8').split(/\r?\n/)[0];
      if(/^\d+$/.test(first))port=Number(first);
    }
    if(port){
      try{
        const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const page=list.find(t=>t.type==='page');
        if(page&&page.webSocketDebuggerUrl)return page;
      }catch(_){/* Chrome n ecoute pas encore */}
    }
    await sleep(150);
  }
  throw new Error(`Chrome n a pas ouvert son port de debogage en ${BOOT_MS/1000} s`);
}
