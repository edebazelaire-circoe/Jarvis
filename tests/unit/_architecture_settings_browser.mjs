/* Harnais CDP partagé des onglets Architecture et Sous-agents (`test_architecture_settings_browser.py`,
   `test_brain_config_panel_browser.py`, `test_subagent_settings_browser.py` ; jarvis-architecture-agents-settings-editor
   Slices 04 à 07 : le harnais de la Slice 06 en était une copie, fusionnée ici à la Slice 07, Alt compris).

   Charge une page STATIQUE (fichier local : le module et son adaptateur de fixture, jamais le Control Center
   vivant) dans Chrome sans tête et rejoue un plan de VRAIES entrées : touches (Tab, Maj+F10, Entrée, Échap,
   flèches), clic droit, glisser à la souris, captures d'écran. Chaque étape rend une valeur :

     {"eval": "<expression JS, éventuellement asynchrone>"}            -> sa valeur
     {"key": "Tab", "shift": false, "alt": false}                       -> null
     {"click": "<sélecteur>", "button": "left"|"right"}                 -> null
     {"drag": "<sélecteur>", "dx": 120, "dy": 40}                       -> null
     {"shot": "<chemin.png>"}                                           -> le chemin
     {"wait": 300}                                                      -> null

   Usage : node _architecture_settings_browser.mjs <page.html> <chrome.exe> <plan.json>
   Plan : {"width", "height", "reducedMotion": bool, "steps": [...]}. Sortie : tableau JSON des valeurs. */
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit,killChrome,assertSafeTarget} from './_cdp_profile.mjs';

const [,,PAGE,CHROME,PLAN_FILE]=process.argv;
assertSafeTarget(PAGE,null);
const plan=JSON.parse(readFileSync(PLAN_FILE,'utf8'));
const profile=mkdtempSync(join(tmpdir(),'jarvis-arch-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--allow-file-access-from-files','--hide-scrollbars','about:blank'],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const KEYS={Tab:[9,'Tab'],Enter:[13,'Enter'],Escape:[27,'Escape'],F10:[121,'F10'],ArrowDown:[40,'ArrowDown'],ArrowUp:[38,'ArrowUp'],
  ArrowLeft:[37,'ArrowLeft'],ArrowRight:[39,'ArrowRight'],ContextMenu:[93,'ContextMenu'],' ':[32,'Space']};

try{
  const target=await poll();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refusé'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{const msg=JSON.parse(event.data);if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}};
  const send=(method,params={})=>new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}))});
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const center=async sel=>{
    const v=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(sel)});if(!e)return null;e.scrollIntoView({block:'nearest',inline:'nearest'});const r=e.getBoundingClientRect();return {x:r.left+Math.min(r.width/2,40),y:r.top+Math.min(r.height/2,18)}})()`);
    if(!v)throw new Error('élément absent : '+sel);
    return v;
  };
  const mouse=(type,x,y,button='left',buttons=0,clickCount=1)=>send('Input.dispatchMouseEvent',{type,x,y,button,buttons,clickCount,pointerType:'mouse'});
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:plan.width,height:plan.height,deviceScaleFactor:1,mobile:false});
  if(plan.reducedMotion)await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await send('Page.navigate',{url:'file:///'+PAGE.replace(/\\/g,'/')});
  await sleep(700);
  const out=[];
  for(const step of plan.steps){
    if(step.eval!=null){out.push(await evaluate(step.eval));continue}
    if(step.wait!=null){await sleep(step.wait);out.push(null);continue}
    if(step.key){
      const [code,name]=KEYS[step.key]||[0,step.key];const modifiers=(step.shift?8:0)|(step.alt?1:0);
      const base={key:step.key,code:name,windowsVirtualKeyCode:code,nativeVirtualKeyCode:code,modifiers};
      await send('Input.dispatchKeyEvent',{type:'rawKeyDown',...base});
      if(step.key===' '||step.key==='Enter')await send('Input.dispatchKeyEvent',{type:'char',...base,text:step.key===' '?' ':'\r'});
      await send('Input.dispatchKeyEvent',{type:'keyUp',...base});
      await sleep(80);out.push(null);continue;
    }
    if(step.click){
      const p=await center(step.click),b=step.button||'left',bs=b==='right'?2:1;
      await mouse('mouseMoved',p.x,p.y);await mouse('mousePressed',p.x,p.y,b,bs);await mouse('mouseReleased',p.x,p.y,b,0);
      await sleep(120);out.push(null);continue;
    }
    if(step.drag){
      const p=await center(step.drag);
      await mouse('mouseMoved',p.x,p.y);await mouse('mousePressed',p.x,p.y,'left',1);
      for(let i=1;i<=8;i+=1)await mouse('mouseMoved',p.x+step.dx*i/8,p.y+step.dy*i/8,'left',1);
      await mouse('mouseReleased',p.x+step.dx,p.y+step.dy,'left',0);
      await sleep(150);out.push(null);continue;
    }
    if(step.shot){
      const r=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
      writeFileSync(step.shot,Buffer.from(r.data,'base64'));out.push(step.shot);continue;
    }
    throw new Error('étape inconnue : '+JSON.stringify(step));
  }
  ws.close();
  process.stdout.write(JSON.stringify(out));
}finally{
  killChrome(chrome,profile);
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
