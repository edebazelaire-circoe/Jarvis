/* Harnais CDP de `test_presentation_studio_reload_browser.py` (studio de presentation, Slice 06).

   Chrome sans tete (`--headless=new`), la page servie par le pont de test (`http://127.0.0.1:<port>/`), de VRAIS clics CDP
   et des evaluations `Runtime.evaluate`. Les cadres de prefab sont `sandbox="allow-scripts"` donc ISOLES dans leur propre
   processus : le harnais s'y attache (`Target.setAutoAttach`, `flatten`) et evalue DANS un cadre, reconnu par
   `jarvis.instance.object_id` (l'objet de scene qu'il affiche). Rien de ce que le cadre contient n'est lu autrement que par
   ce chemin : le cadre est traite comme n'importe quel contenu non fiable.

   Usage : node _presentation_studio_reload_browser.mjs <url> <chrome.exe> <plan.json>
   Actions : {eval}, {wait: ms}, {until: expr, ms}, {value: nom, expr}, {click: selecteur}, {key: nom}, {shot: chemin},
   {frameValue: nom, object_id, expr, index?} (evalue DANS le cadre, `index` -1 = le dernier cree), {frameEval}, {frameUntil: {object_id, expr, ms}},
   {framesValue: nom, expr} (dans CHAQUE cadre : {object_id: [resultats]}), {clickInFrame: {object_id, selector}},
   {heap: nom} (ramasse-miettes puis tas utilise de la page), {listeners: nom} (ecouteurs de la page principale).
   Sortie : {reads, console, errors, frames, sessions}. */
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,PLAN_FILE]=process.argv;
const plan=JSON.parse(readFileSync(PLAN_FILE,'utf8'));
const profile=mkdtempSync(join(tmpdir(),'jarvis-reload-cdp-'));
const port=9400+Math.floor(Math.random()*400);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();
  const consoleLines=[],errors=[],frames=[];   // frames : sessions des cadres, dans l'ordre de creation
  const send=(method,params={},sessionId)=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify(Object.assign({id:mine,method,params},sessionId?{sessionId}:{})));
  });
  const textOf=a=>a.value!==undefined?String(a.value):(a.description||a.type||'');
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
      return;
    }
    const where=msg.sessionId?'frame':'page';
    if(msg.method==='Runtime.consoleAPICalled'){
      consoleLines.push({where,type:msg.params.type,text:(msg.params.args||[]).map(textOf).join(' ')});
    }else if(msg.method==='Runtime.exceptionThrown'){
      const text=msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text;
      (where==='frame'?consoleLines:errors).push(where==='frame'?{where,type:'exception',text}:text);
    }else if(msg.method==='Log.entryAdded'){
      consoleLines.push({where,type:'log-'+msg.params.entry.level,text:msg.params.entry.text+' '+(msg.params.entry.url||'')});
    }else if(msg.method==='Target.attachedToTarget'){
      const info=msg.params.targetInfo;
      const session={sessionId:msg.params.sessionId,type:info.type,url:info.url,alive:true,objectId:null};
      if(info.type==='iframe'){
        frames.push(session);
        send('Runtime.enable',{},session.sessionId).catch(()=>{});
        send('Log.enable',{},session.sessionId).catch(()=>{});
      }
    }else if(msg.method==='Target.detachedFromTarget'){
      const found=frames.find(s=>s.sessionId===msg.params.sessionId);
      if(found)found.alive=false;
    }
  };
  const evaluate=async(expression,sessionId,extra)=>{
    const r=await send('Runtime.evaluate',Object.assign({expression,returnByValue:true,awaitPromise:true},extra||{}),sessionId);
    if(r.exceptionDetails)
      throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const objectOf=async session=>{
    try{return await evaluate(`typeof jarvis==='object'&&jarvis.instance?jarvis.instance.object_id:null`,session.sessionId)}
    catch(_){return null}
  };
  const liveFrames=async()=>{
    const out=[];
    for(const session of frames.filter(s=>s.alive)){
      const objectId=await objectOf(session);
      if(objectId)out.push({session,objectId});
    }
    return out;
  };
  const pickFrame=async(objectId,index)=>{
    const matching=(await liveFrames()).filter(f=>f.objectId===objectId);
    if(!matching.length)throw new Error('cadre introuvable : '+objectId);
    return matching.at(index===undefined?-1:index).session;
  };
  const KEYS={ArrowRight:{code:'ArrowRight',keyCode:39},ArrowLeft:{code:'ArrowLeft',keyCode:37},' ':{code:'Space',keyCode:32,text:' '},
    Escape:{code:'Escape',keyCode:27},Enter:{code:'Enter',keyCode:13,text:'\r'},Home:{code:'Home',keyCode:36}};
  const press=async key=>{
    const k=KEYS[key];
    await send('Input.dispatchKeyEvent',{type:'keyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,
      nativeVirtualKeyCode:k.keyCode,text:k.text});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,
      nativeVirtualKeyCode:k.keyCode});
  };
  const mouse=async(x,y)=>{
    for(const type of ['mouseMoved','mousePressed','mouseReleased'])
      await send('Input.dispatchMouseEvent',{type,x,y,button:'left',clickCount:1});
  };
  const click=async selector=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
    if(!at)throw new Error('clic : introuvable '+selector);
    await mouse(at.x,at.y);
  };
  const clickInFrame=async({object_id,selector})=>{
    const session=await pickFrame(object_id,-1);
    const inner=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`,session.sessionId);
    if(!inner)throw new Error('clic dans le cadre : introuvable '+selector);
    const outer=await evaluate(`(()=>{const host=document.querySelector('[data-object-id="${object_id}"]');
      const frames=[...host.querySelectorAll('iframe')].filter(f=>!f.className.includes('sc-prefab-staged')&&f.style.visibility!=='hidden');
      const r=frames[frames.length-1].getBoundingClientRect();return {x:r.left,y:r.top}})()`);
    await mouse(outer.x+inner.x,outer.y+inner.y);
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1100,height:760,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  for(let i=0;i<200;i+=1){
    await sleep(50);
    const ready=await evaluate(`document.readyState==='complete'&&!!window.__bridgeReady`).catch(()=>false);
    if(ready)break;
  }
  const reads={};
  for(const action of plan){
   try{
    if(action.eval!==undefined)await evaluate(action.eval);
    else if(action.wait!==undefined)await sleep(action.wait);
    else if(action.key!==undefined)await press(action.key);
    else if(action.click!==undefined)await click(action.click);
    else if(action.clickInFrame!==undefined)await clickInFrame(action.clickInFrame);
    else if(action.shot!==undefined){
      const shot=await send('Page.captureScreenshot',{format:'png'});
      writeFileSync(action.shot,Buffer.from(shot.data,'base64'));
    }
    else if(action.frameValue!==undefined){
      const session=await pickFrame(action.object_id,action.index);
      reads[action.frameValue]=await evaluate(action.expr,session.sessionId,{includeCommandLineAPI:true});
    }
    else if(action.frameUntil!==undefined){
      const spec=action.frameUntil;const end=Date.now()+(spec.ms||5000);let ok=false;
      while(Date.now()<end){
        try{const session=await pickFrame(spec.object_id,spec.index);
          ok=!!(await evaluate(spec.expr,session.sessionId,{includeCommandLineAPI:true}));}catch(_){ok=false}
        if(ok)break;await sleep(50);
      }
      reads['frameUntil:'+spec.object_id+':'+spec.expr]=ok;
    }
    else if(action.frameEval!==undefined){
      const session=await pickFrame(action.object_id,action.index);
      await evaluate(action.frameEval,session.sessionId,{includeCommandLineAPI:true});
    }
    else if(action.framesValue!==undefined){
      const out={};
      for(const {session,objectId} of await liveFrames()){
        (out[objectId]=out[objectId]||[]).push(await evaluate(action.expr,session.sessionId,{includeCommandLineAPI:true}));
      }
      reads[action.framesValue]=out;
    }
    else if(action.heap!==undefined){
      await send('HeapProfiler.collectGarbage');
      const usage=await send('Runtime.getHeapUsage');
      reads[action.heap]=usage.usedSize;
    }
    else if(action.listeners!==undefined){
      reads[action.listeners]=await evaluate(
        `Object.entries(getEventListeners(window)).map(([k,v])=>[k,v.length]).sort()`,undefined,{includeCommandLineAPI:true});
    }
    else if(action.value!==undefined)reads[action.value]=await evaluate(action.expr);
    else if(action.until!==undefined){
      const end=Date.now()+(action.ms||5000);let ok=false;
      while(Date.now()<end){ok=!!(await evaluate(action.until));if(ok)break;await sleep(50)}
      reads['until:'+action.until]=ok;
    }
   }catch(error){reads.failed={action:Object.keys(action)[0],error:String(error.message||error).slice(0,300)};break}
  }
  ws.close();
  process.stdout.write(JSON.stringify({reads,console:consoleLines,errors,
    sessions:frames.map(s=>({alive:s.alive,type:s.type}))}));
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient le dossier */}
}

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{
      const list=await (await fetch(url)).json();
      const page=list.find(t=>t.type==='page');
      if(page&&page.webSocketDebuggerUrl)return page;
    }catch(_){/* Chrome n ecoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
