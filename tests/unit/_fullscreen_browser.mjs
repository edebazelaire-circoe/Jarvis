/* Harnais CDP de `test_fullscreen_browser.py` (studio de présentation, Slice 03).

   Chrome sans tête (`--headless=new`), la page fournie, de VRAIS clics et de VRAIES touches CDP
   (`Input.dispatchMouseEvent` / `Input.dispatchKeyEvent` donnent l'activation utilisateur transitoire que l'API
   Fullscreen exige), et des évaluations `Runtime.evaluate` SANS geste (activation absente). Le relais
   `/api/fullscreen/*` est remplacé AVANT tout script par un double (`window.__fs`) : la page n'a pas de Control
   Center sous `file://` ; la chaîne HTTP réelle est prouvée par `test_fullscreen_commands.py`.

   Usage : node _fullscreen_browser.mjs <page.html> <chrome.exe> <planJSON>
   Actions : {eval}, {wait: ms}, {click: selecteur}, {key: nom}, {value: nom, expr}, {until: expr, ms},
   {size: [w,h]}, {shot: chemin.png}. Sortie : {reads, console, errors}. */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);

const FAKE_RELAY=`(()=>{
  const fs=window.__fs={queue:[],posts:[],gets:0,toasts:[],postStatus:200,armed:null};
  const json=(status,obj)=>new Response(JSON.stringify(obj),{status,headers:{'Content-Type':'application/json'}});
  const real=window.fetch.bind(window);
  window.fetch=async(url,init)=>{
    const u=String(url),method=(init&&init.method)||'GET';
    if(!u.startsWith('/api/fullscreen'))return real(url,init);
    if(method==='GET'){
      fs.gets++;
      const deadline=Date.now()+400;
      while(!fs.queue.length&&Date.now()<deadline)await new Promise(r=>setTimeout(r,25));
      return json(200,{command:fs.queue.length?fs.queue.shift():null,armed:fs.armed});
    }
    fs.posts.push({url:u,body:init&&init.body?JSON.parse(init.body):null,t:Date.now()});
    /* Comme le serveur : un reçu needs_gesture arme, tout autre état rapporté désarme. */
    const sent=fs.posts[fs.posts.length-1].body;
    if(sent&&sent.state==='needs_gesture'&&u.includes('/commands/'))fs.armed=u.split('/').pop().slice(0,8);
    else if(sent&&sent.state&&sent.state!=='needs_gesture')fs.armed=null;
    return json(fs.postStatus,fs.postStatus===200?{ok:true}:{error:{code:'fullscreen_bad_receipt',message:'refusé'}});
  };
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-fs-cdp-'));
const port=9300+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions',
  '--allow-file-access-from-files','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const consoleLines=[],errors=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):'').join(' ');
      /* [studio] : la bande de lecture (Slice 12) rejoue ce harnais pour sa propre preuve navigateur. */
      if(text.startsWith('[fullscreen]')||text.startsWith('[studio]'))consoleLines.push(msg.params.type+' '+text);
    }else if(msg.method==='Runtime.exceptionThrown'){
      errors.push(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify({id:mine,method,params}));
  });
  /* SANS userGesture : c'est exactement un appel de la voix ou d'un agent. */
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)
      throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const KEYS={ArrowRight:{code:'ArrowRight',keyCode:39},ArrowLeft:{code:'ArrowLeft',keyCode:37},' ':{code:'Space',keyCode:32,text:' '},
    Escape:{code:'Escape',keyCode:27},Enter:{code:'Enter',keyCode:13,text:'\r'},Home:{code:'Home',keyCode:36},
    End:{code:'End',keyCode:35},p:{code:'KeyP',keyCode:80,text:'p'},ArrowUp:{code:'ArrowUp',keyCode:38}};
  const press=async key=>{
    const k=KEYS[key];
    await send('Input.dispatchKeyEvent',{type:'keyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,
      nativeVirtualKeyCode:k.keyCode,text:k.text});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,
      nativeVirtualKeyCode:k.keyCode});
  };
  const click=async selector=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
    if(!at)throw new Error('clic : introuvable '+selector);
    for(const type of ['mouseMoved','mousePressed','mouseReleased'])
      await send('Input.dispatchMouseEvent',{type,x:at.x,y:at.y,button:'left',clickCount:1});
  };

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:FAKE_RELAY});
  await send('Emulation.setDeviceMetricsOverride',{width:1000,height:700,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:'file:///'+PAGE.replace(/\\/g,'/')});
  for(let i=0;i<200;i+=1){
    await sleep(50);
    const ready=await evaluate(`document.readyState==='complete'&&!!window.JarvisFullscreen`).catch(()=>false);
    if(ready)break;
  }
  await sleep(200);
  const reads={};
  for(const action of plan){
   try{
    if(action.eval!==undefined)await evaluate(action.eval);
    else if(action.wait!==undefined)await sleep(action.wait);
    else if(action.key!==undefined)await press(action.key);
    else if(action.click!==undefined)await click(action.click);
    else if(action.size!==undefined)
      await send('Emulation.setDeviceMetricsOverride',{width:action.size[0],height:action.size[1],deviceScaleFactor:1,mobile:false});
    else if(action.shot!==undefined){
      const shot=await send('Page.captureScreenshot',{format:'png'});
      writeFileSync(action.shot,Buffer.from(shot.data,'base64'));
    }
    else if(action.value!==undefined)reads[action.value]=await evaluate(action.expr);
    else if(action.until!==undefined){
      const end=Date.now()+(action.ms||5000);let ok=false;
      while(Date.now()<end){ok=!!(await evaluate(action.until));if(ok)break;await sleep(50)}
      reads['until:'+action.until]=ok;
    }
   }catch(error){reads.failed={action,error:String(error.message||error).slice(0,300)};break}
  }
  ws.close();
  process.stdout.write(JSON.stringify({reads,console:consoleLines,errors}));
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
