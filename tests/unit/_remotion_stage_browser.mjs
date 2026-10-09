/* Harnais CDP de la Slice 10 (Remotion Player dans Jarvis) : le VRAI Control Center servi par un Core isolé, dans un Chrome sans tête.

   Contrairement à `_fullscreen_browser.mjs`, il s'attache aussi aux cadres hors processus (le bac à sable d'origine dédiée est un
   autre processus : `Target.setAutoAttach`, sessions aplaties) pour lire ce que la scène a réellement produit.

   Usage : node _remotion_stage_browser.mjs <url de la page> <chrome.exe> <planJSON>
   Environnement : CDP_VIEWPORT=LxH (1280x720 par défaut).
   Actions (champ `scope` : "page" par défaut, ou "sandbox" pour le cadre du bac à sable) :
     {eval}, {wait: ms}, {click: selecteur}, {clickAt: [x,y]}, {clickExpr: expr -> {x,y} de la page}, {key: nom}, {value: nom, expr, scope?}, {until: expr, ms, scope?}, {size: [w,h]},
     {shot: chemin.png}, {http: {method, url, headers?, json?}, as: nom} (requête de Node, pour parler à Core entre deux étapes).
   Sortie : {reads, console, errors, targets}. Chrome est tué avec ses enfants, le profil effacé. */
import {execFileSync, spawn} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);
const [VIEW_W,VIEW_H]=(process.env.CDP_VIEWPORT||'1280x720').split('x').map(Number);
const profile=mkdtempSync(join(tmpdir(),'jarvis-rs-cdp-'));
const port=9300+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  let version;
  for(let i=0;i<100&&!version;i++){try{version=await (await fetch(`http://127.0.0.1:${port}/json/version`)).json()}catch(_){await sleep(150)}}
  if(!version)throw new Error('Chrome n a pas ouvert son port de debogage');
  const ws=new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const consoleLines=[],errors=[],iframeSessions=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }else if(msg.method==='Target.attachedToTarget'){
      const info=msg.params.targetInfo;
      if(info.type==='iframe'){
        iframeSessions.push(msg.params.sessionId);
        send('Runtime.enable',{},msg.params.sessionId).catch(()=>{});
        send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true},msg.params.sessionId).catch(()=>{});
      }
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):(a.description||'')).join(' ');
      consoleLines.push((msg.sessionId?'frame ':'page ')+msg.params.type+' '+text.slice(0,300));
    }else if(msg.method==='Runtime.exceptionThrown'){
      errors.push((msg.sessionId?'frame ':'page ')+(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text));
    }
  };
  const send=(method,params={},sessionId)=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify({id:mine,method,params,sessionId}));
  });
  const {targetId}=await send('Target.createTarget',{url:'about:blank'});
  const {sessionId:page}=await send('Target.attachToTarget',{targetId,flatten:true});
  const rawEval=async(sid,expression)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},sid);
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  /* La session du bac à sable : celle des cadres hors processus dont l'adresse est une page `/page/<scène>/<hôte>`. */
  const sandboxSession=async()=>{
    for(const sid of iframeSessions.slice().reverse()){
      try{if(String(await rawEval(sid,'location.href')).includes('/page/scene-'))return sid}catch(_e){/* cible fermée */}
    }
    return null;
  };
  const evaluate=async(expression,scope)=>{
    if(scope==='sandbox'){
      const sid=await sandboxSession();
      if(!sid)throw new Error('pas de cadre de bac a sable');
      return rawEval(sid,expression);
    }
    return rawEval(page,expression);
  };
  const KEYS={ArrowRight:{code:'ArrowRight',keyCode:39},ArrowLeft:{code:'ArrowLeft',keyCode:37},' ':{code:'Space',keyCode:32,text:' '},
    Escape:{code:'Escape',keyCode:27},Enter:{code:'Enter',keyCode:13,text:'\r'},Home:{code:'Home',keyCode:36},End:{code:'End',keyCode:35},
    p:{code:'KeyP',keyCode:80,text:'p'},Tab:{code:'Tab',keyCode:9}};
  const press=async key=>{
    const k=KEYS[key];if(!k)throw new Error('touche inconnue '+key);
    await send('Input.dispatchKeyEvent',{type:'keyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,text:k.text},page);
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode},page);
  };
  /* Un vrai clic CDP (activation utilisateur) : sur un sélecteur de la page, ou {x,y} dans la page. */
  const clickAt=async(x,y)=>{
    for(const type of ['mouseMoved','mousePressed','mouseReleased'])
      await send('Input.dispatchMouseEvent',{type,x,y,button:'left',clickCount:1},page);
  };
  const click=async selector=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
    if(!at)throw new Error('clic : introuvable '+selector);
    await clickAt(at.x,at.y);
  };

  await send('Page.enable',{},page);
  await send('Runtime.enable',{},page);
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true},page);
  await send('Emulation.setDeviceMetricsOverride',{width:VIEW_W,height:VIEW_H,deviceScaleFactor:1,mobile:false},page);
  await send('Page.navigate',{url:PAGE},page);
  for(let i=0;i<200;i++){
    await sleep(50);
    if(await rawEval(page,"document.readyState==='complete'").catch(()=>false))break;
  }
  await sleep(300);
  const reads={};
  for(const action of plan){
    try{
      if(action.eval!==undefined)await evaluate(action.eval,action.scope);
      else if(action.wait!==undefined)await sleep(action.wait);
      else if(action.key!==undefined)await press(action.key);
      else if(action.click!==undefined)await click(action.click);
      else if(action.clickAt!==undefined)await clickAt(action.clickAt[0],action.clickAt[1]);
      else if(action.clickExpr!==undefined){
        const at=await evaluate(action.clickExpr,'page');
        if(!at)throw new Error('clic : expression sans position');
        await clickAt(at.x,at.y);
      }
      else if(action.size!==undefined)
        await send('Emulation.setDeviceMetricsOverride',{width:action.size[0],height:action.size[1],deviceScaleFactor:1,mobile:false},page);
      else if(action.shot!==undefined){
        const shot=await send('Page.captureScreenshot',{format:'png'},page);
        writeFileSync(action.shot,Buffer.from(shot.data,'base64'));
      }else if(action.http!==undefined){
        const h=action.http;
        const response=await fetch(h.url,{method:h.method||'GET',headers:{...(h.headers||{}),...(h.json!==undefined?{'Content-Type':'application/json'}:{})},
          body:h.json!==undefined?JSON.stringify(h.json):undefined});
        let body=null;try{body=await response.json()}catch(_e){body=null}
        reads[action.as||'http']={status:response.status,body};
      }else if(action.value!==undefined)reads[action.value]=await evaluate(action.expr,action.scope);
      else if(action.until!==undefined){
        const end=Date.now()+(action.ms||5000);let ok=false;
        while(Date.now()<end){ok=!!(await evaluate(action.until,action.scope).catch(()=>false));if(ok)break;await sleep(100)}
        reads['until:'+action.until.slice(0,80)]=ok;
      }
    }catch(error){reads.failed={action:JSON.stringify(action).slice(0,200),error:String(error.message||error).slice(0,300)};break}
  }
  ws.close();
  process.stdout.write(JSON.stringify({reads,console:consoleLines.slice(-200),errors}));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));
  killTree(chrome);
  await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){/* le prochain passage ne s en soucie pas */}
}

function killTree(child){
  if(process.platform==='win32'&&child.pid){
    try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore'});return}
    catch(_){/* deja sorti */}
  }
  child.kill();
}
