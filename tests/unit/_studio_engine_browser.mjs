/* Harnais CDP de la carte « Présentations · moteur » (`test_control_center_presentation_studio_engine_browser.py`, Slice 20).

   Chrome sans tête sur la VRAIE page du Control Center servie par un vrai `ControlCenter` devant un Core isolé (ports libres, racine de
   données jetable). Un plan JSON d'étapes ; chacune est l'une de :
     {nav: true}                          charge l'URL (une fois, au début)
     {viewport: [w, h]}                   impose la taille
     {read: "nom", expr: "..."}           évalue (promesse attendue), garde la valeur
     {click: "css"}                       clic réel (coordonnées du centre, événements souris de Chrome)
     {type: "css", text: "..."}           focus + saisie réelle (Input.insertText) + événement input
     {until: "expr", ms: 8000}            attend que l'expression soit vraie, sinon échoue (avec son nom)
     {wait: ms}   {shot: "chemin.png"}
   Sortie : {reads, network, console}. `network` : chaque requête /api/ émise par la page (méthode, chemin, corps).
   Usage : node _studio_engine_browser.mjs <url> <chrome.exe> <plan.json> */
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,PLAN_FILE]=process.argv;
const plan=JSON.parse(readFileSync(PLAN_FILE,'utf8'));
const profile=mkdtempSync(join(tmpdir(),'jarvis-sve-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const reads={},network=[],consoleLines=[];

try{
  const target=await poll();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refusé'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
    else if(msg.method==='Network.requestWillBeSent'){
      const r=msg.params.request;
      if(r.url.includes('/api/')&&!r.url.includes('/api/status'))network.push({method:r.method,url:r.url.replace(/^https?:\/\/[^/]+/,''),body:r.postData||null});
    }else if(msg.method==='Runtime.consoleAPICalled'){
      consoleLines.push(`${msg.params.type}: ${msg.params.args.map(a=>a.value??a.description??'').join(' ')}`.slice(0,400));
    }else if(msg.method==='Runtime.exceptionThrown'){
      consoleLines.push('exception: '+(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text).slice(0,400));
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}))});
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const center=async css=>{
    const box=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(css)});if(!e)return null;e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,disabled:!!e.disabled}})()`);
    if(!box)throw new Error('introuvable : '+css);
    return box;
  };
  for(const [index,step] of plan.entries()){
    if(step.nav){await send('Page.navigate',{url:URL_});await sleep(1200)}
    else if(step.viewport)await send('Emulation.setDeviceMetricsOverride',{width:step.viewport[0],height:step.viewport[1],deviceScaleFactor:1,mobile:false});
    else if(step.read)reads[step.read]=await evaluate(step.expr);
    else if(step.click){
      const box=await center(step.click);
      if(box.disabled&&!step.allowDisabled)throw new Error('bouton inactif : '+step.click);
      for(const type of ['mouseMoved','mousePressed','mouseReleased'])
        await send('Input.dispatchMouseEvent',{type,x:box.x,y:box.y,button:'left',clickCount:1});
      await sleep(step.after??150);
    }else if(step.type){
      await center(step.type);
      await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(step.type)});e.focus();e.select&&e.select()})()`);
      await send('Input.insertText',{text:step.text});
      await sleep(80);
    }else if(step.until){
      const limit=Date.now()+(step.ms||8000);let ok=false,last=null;
      while(Date.now()<limit){try{last=await evaluate(step.until);if(last){ok=true;break}}catch(e){last=String(e)}await sleep(120)}
      if(!ok)throw new Error(`étape ${index} : condition jamais vraie en ${step.ms||8000} ms : ${step.until} (dernière valeur ${JSON.stringify(last)})`);
    }else if(step.wait)await sleep(step.wait);
    else if(step.shot){const shot=await send('Page.captureScreenshot',{format:'png'});writeFileSync(step.shot,Buffer.from(shot.data,'base64'))}
  }
  ws.close();
  process.stdout.write(JSON.stringify({reads,network,console:consoleLines}));
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient encore le dossier */}
}

async function poll(){
  for(let i=0;i<200;i+=1){
    try{
      const port=readFileSync(join(profile,'DevToolsActivePort'),'utf8').split(/\r?\n/)[0].trim();
      const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      const page=list.find(t=>t.type==='page');
      if(page&&page.webSocketDebuggerUrl)return page;
    }catch(_){/* Chrome n'écoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n’a pas ouvert son port de débogage');
}
