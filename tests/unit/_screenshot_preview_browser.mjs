/* Harnais CDP pour `test_screenshot_preview_browser.py` (orbital-ui Slice 05).

   Chrome sans tête sur un VRAI Control Center (URL http) relié à un vrai Core
   aux sources de capture factices (`CaptureStack`) : aucun double dans la page,
   aucune vraie capture d'écran. Le harnais pilote de vrais événements d'entrée
   (`Input.*`) et relit ce que la page produit.

   Usage : node _screenshot_preview_browser.mjs <http://127.0.0.1:port/> <chrome.exe> <stepJSON|@fichier>
   Étape : {width, height, reducedMotion?, forcedColors?, actions: [...]}
   Action : {eval}, {value, expr}, {wait: ms}, {until: js, ms, name}, {shot: chemin.png},
            {click: sélecteur}, {right: sélecteur}, {move: sélecteur}, {at: {x, y}, button?} (clic en un point),
            {hover: {x, y}}, {key, shift?}, {type: texte}, {focus: sélecteur}, {resize: {width, height}},
            {axe: nom, file, selector}.
   Sortie : {reads, console, errors}. */
import {spawn, execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit} from './_cdp_profile.mjs';

const [,,PAGE,CHROME,STEP]=process.argv;
const step=JSON.parse(STEP.startsWith('@')?readFileSync(STEP.slice(1),'utf-8'):STEP);
const profile=mkdtempSync(join(tmpdir(),'jarvis-screenshot-preview-cdp-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const PREFIXES=['[screenshot_preview]','[capture]','[chat]','[presentation-rail]','[tool_wheel]'];

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const consoleLines=[],errors=[];
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):(a.description||'')).join(' ');
      if(PREFIXES.some(p=>text.startsWith(p))||msg.params.type==='error')consoleLines.push(`${msg.params.type} ${text}`);
    }else if(msg.method==='Runtime.exceptionThrown'){
      errors.push(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}))});
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  await send('Page.enable');await send('Runtime.enable');
  await send('Emulation.setEmulatedMedia',{features:[
    ...(step.reducedMotion?[{name:'prefers-reduced-motion',value:'reduce'}]:[]),
    ...(step.forcedColors?[{name:'forced-colors',value:'active'}]:[]),
  ]});
  await send('Emulation.setDeviceMetricsOverride',{width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:PAGE});
  let ready=false;
  for(let i=0;i<300&&!ready;i+=1){
    await sleep(50);
    ready=await evaluate(`document.readyState==='complete'&&!!window.JarvisScreenshotPreview&&!!window.JarvisCaptureRail
      &&window.JarvisCaptureRail.view().settled`).catch(()=>false);
  }
  const reads={ready};
  const point=async where=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(where)});
      if(!el)return null;const r=el.getBoundingClientRect();return r.width?{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}:null})()`);
    if(!at)throw new Error('cible introuvable ou cachée '+where);
    return at;
  };
  const mouse=async(at,button)=>{
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x,y:at.y,button:'none'});
    await sleep(30);
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x:at.x,y:at.y,button,buttons:button==='right'?2:1,clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:at.x,y:at.y,button,buttons:0,clickCount:1});
  };
  const CODES={ArrowDown:40,ArrowUp:38,ArrowLeft:37,ArrowRight:39,Escape:27,Enter:13,Tab:9,Home:36,End:35,' ':32,F10:121};
  for(const action of step.actions){
    try{
      if(action.eval!==undefined)await evaluate(action.eval);
      else if(action.value!==undefined)reads[action.value]=await evaluate(action.expr);
      else if(action.wait!==undefined)await sleep(action.wait);
      else if(action.until!==undefined){
        const end=Date.now()+(action.ms||8000);let ok=false;
        while(Date.now()<end){ok=!!(await evaluate(action.until).catch(()=>false));if(ok)break;await sleep(60)}
        reads['until:'+(action.name||action.until)]=ok;
      }else if(action.shot!==undefined){
        const shot=await send('Page.captureScreenshot',{format:'png'});
        writeFileSync(action.shot,Buffer.from(shot.data,'base64'));
      }else if(action.click!==undefined)await mouse(await point(action.click),'left');
      else if(action.right!==undefined)await mouse(await point(action.right),'right');
      else if(action.at!==undefined)await mouse(action.at,action.button||'left');
      else if(action.move!==undefined){
        const at=await point(action.move);
        await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x,y:at.y,button:'none'});
      }else if(action.hover!==undefined){
        await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:action.hover.x,y:action.hover.y,button:'none'});
      }else if(action.key!==undefined){
        const base={key:action.key,code:action.key===' '?'Space':action.key,windowsVirtualKeyCode:CODES[action.key]||0,
          modifiers:action.shift?8:0};
        await send('Input.dispatchKeyEvent',{type:'keyDown',...base,...(action.key==='Enter'?{text:'\r'}:{})});
        await send('Input.dispatchKeyEvent',{type:'keyUp',...base});
        await sleep(60);
      }else if(action.type!==undefined){
        await send('Input.insertText',{text:action.type});
      }else if(action.focus!==undefined){
        await evaluate(`document.querySelector(${JSON.stringify(action.focus)}).focus()`);
      }else if(action.resize!==undefined){
        await send('Emulation.setDeviceMetricsOverride',{width:action.resize.width,height:action.resize.height,deviceScaleFactor:1,mobile:false});
        await sleep(300);
      }else if(action.axe!==undefined){
        await evaluate(readFileSync(action.file,'utf8'));
        reads['axe:'+action.axe]=await evaluate(`axe.run(document.querySelector(${JSON.stringify(action.selector)}),
          {resultTypes:['violations']}).then(r=>r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.map(n=>n.target.join(' '))})))`);
      }
    }catch(error){reads.failed={action,error:String(error.message||error).slice(0,400)};break}
  }
  ws.close();
  process.stdout.write(JSON.stringify({reads,console:consoleLines,errors}));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));
  killTree(chrome);
  await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){/* Windows tient le dossier */}
}

function killTree(child){
  if(process.platform==='win32'&&child.pid){
    try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore'});return}
    catch(_){/* déjà sorti */}
  }
  child.kill();
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
