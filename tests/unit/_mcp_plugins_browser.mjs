/* Harnais CDP pour les tests de mise en page de l'onglet « Plugins externes »
   (`test_control_center_mcp_plugins_js.py`, generic-mcp-plugin-runtime Slice 06).

   Même principe que `_interaction_mode_browser.mjs` : Chrome sans tête, une
   taille imposée, des mesures CALCULÉES. Chaque étape du plan charge la page
   servie, impose sa taille, puis évalue `script` (une expression JavaScript,
   éventuellement asynchrone) dont la valeur est rendue telle quelle.

   Usage : node _mcp_plugins_browser.mjs <page.html> <chrome.exe> <plan.json>
   (un fichier : les données posées dépassent la longueur d'une ligne de commande Windows).
   Sortie : un tableau JSON, une valeur par étape. */
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN_FILE]=process.argv;
const plan=JSON.parse(readFileSync(PLAN_FILE,'utf8'));
const profile=mkdtempSync(join(tmpdir(),'jarvis-mcpp-cdp-'));
const port=9722+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu',
  '--disable-extensions','--allow-file-access-from-files','--hide-scrollbars',
  'about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refusé'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify({id:mine,method,params}));
  });
  await send('Page.enable');
  await send('Runtime.enable');
  const out=[];
  for(const step of plan){
    await send('Emulation.setDeviceMetricsOverride',
      {width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:'file:///'+PAGE.replace(/\\/g,'/')});
    await sleep(900);
    const r=await send('Runtime.evaluate',{expression:step.script,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)
      throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    out.push(r.result.value);
  }
  ws.close();
  process.stdout.write(JSON.stringify(out));
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient encore le dossier */}
}

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{
      const list=await (await fetch(url)).json();
      const page=list.find(t=>t.type==='page');
      if(page&&page.webSocketDebuggerUrl)return page;
    }catch(_){/* Chrome n'écoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n’a pas ouvert son port de débogage');
}
