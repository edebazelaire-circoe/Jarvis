/* Harnais CDP pour `test_board_drop_browser.py` (handoff jarvis-unified-chat-and-board-drop, Slice 08).

   Chrome sans tête sur un VRAI Control Center (URL http) relié à un vrai Core :
   aucun double dans la page. Le harnais pilote un vrai glisser-déposer
   (`Input.dispatchDragEvent` : fichiers réels sur disque ou `text/uri-list`),
   de vrais gestes de souris sur la scène et relève chaque requête réseau de la
   page (`Network.requestWillBeSent`) : une URL déposée ne doit jamais partir.

   Usage : node _board_drop_browser.mjs <http://127.0.0.1:port/> <chrome.exe> <stepJSON>
   Étape : {width, height, setup?: js, ready?: js, reducedMotion?: bool, actions: [...]}
   Action : {eval}, {value, expr}, {wait: ms}, {until: js, ms, name}, {shot: chemin.png}, {click: sélecteur},
            {hover: cible, paths?|url?} (dragEnter + dragOver), {cancel: cible} (dragCancel),
            {drop: cible, paths?|url?} (dragEnter, dragOver, drop), {mouseDrag: sélecteur, dx, dy},
            {reload: true}, {resize: {width, height}}
   Cible : un sélecteur CSS, ou 'free' = un point du fond de la scène (ni commande, ni nœud).
   Sortie : {reads, console, errors, requests}. */
import {spawn, execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,STEP]=process.argv;
const step=JSON.parse(STEP);
const profile=mkdtempSync(join(tmpdir(),'jarvis-board-drop-cdp-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

/* Un point du fond : `elementFromPoint` y rend `#app`, `.face` ou la scène, jamais un nœud ni une commande. */
const FREE=`(()=>{
  const ok=el=>{if(!el)return false;if(el.closest&&el.closest('.sc-node'))return false;
    const scene=document.getElementById('sceneLayer');return el.id==='app'||el.classList.contains('face')||(scene&&scene.contains(el))};
  for(const fy of [.55,.45,.65,.35,.75])for(const fx of [.4,.3,.5,.6,.25,.7]){
    const x=Math.round(innerWidth*fx),y=Math.round(innerHeight*fy);
    if(ok(document.elementFromPoint(x,y)))return {x,y};
  }
  return null;
})()`;

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const consoleLines=[],errors=[],requests=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):(a.description||'')).join(' ');
      if(text.startsWith('[board-drop]')||text.startsWith('[chat]')||msg.params.type==='error')consoleLines.push(msg.params.type+' '+text);
    }else if(msg.method==='Network.requestWillBeSent'){
      requests.push(msg.params.request.method+' '+msg.params.request.url);
    }else if(msg.method==='Runtime.exceptionThrown'){
      errors.push(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}));
  });
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const point=async where=>{
    const at=where==='free'?await evaluate(FREE):await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(where)});
      if(!el)return null;const r=el.getBoundingClientRect();return r.width?{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}:null})()`);
    if(!at)throw new Error('cible introuvable ou cachée '+where);
    return at;
  };
  const dragData=action=>action.url!==undefined
    ?{items:[{mimeType:'text/uri-list',data:action.url},{mimeType:'text/plain',data:action.url}],dragOperationsMask:1}
    :{items:[],files:action.paths,dragOperationsMask:1};
  const ready=async()=>{
    for(let i=0;i<200;i+=1){
      await sleep(50);
      if(await evaluate(`document.readyState==='complete'&&!!(window.JarvisBoardDrop&&window.JarvisBoardDrop.instance)&&(${step.ready||'true'})`).catch(()=>false))return true;
    }
    return false;
  };
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
  if(step.setup)await send('Page.addScriptToEvaluateOnNewDocument',{source:step.setup});
  await send('Emulation.setEmulatedMedia',{features:step.reducedMotion?[{name:'prefers-reduced-motion',value:'reduce'}]:[]});
  await send('Emulation.setDeviceMetricsOverride',{width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:PAGE});
  const reads={ready:await ready()};
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
      }else if(action.click!==undefined){
        const at=await point(action.click);
        for(const type of ['mouseMoved','mousePressed','mouseReleased'])
          await send('Input.dispatchMouseEvent',{type,x:at.x,y:at.y,button:'left',clickCount:1});
      }else if(action.hover!==undefined){
        const at=await point(action.hover),data=dragData(action);
        await send('Input.dispatchDragEvent',{type:'dragEnter',x:at.x,y:at.y,data,modifiers:0});
        await send('Input.dispatchDragEvent',{type:'dragOver',x:at.x,y:at.y,data,modifiers:0});
        reads.lastPoint=at;
      }else if(action.cancel!==undefined){
        const at=await point(action.cancel);
        await send('Input.dispatchDragEvent',{type:'dragCancel',x:at.x,y:at.y,data:{items:[],dragOperationsMask:1},modifiers:0});
      }else if(action.drop!==undefined){
        const at=await point(action.drop),data=dragData(action);
        for(const type of ['dragEnter','dragOver','drop'])
          await send('Input.dispatchDragEvent',{type,x:at.x,y:at.y,data,modifiers:0});
        reads.lastPoint=at;
      }else if(action.mouseDrag!==undefined){
        const at=await point(action.mouseDrag),steps=12;
        await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x,y:at.y,button:'none'});
        await send('Input.dispatchMouseEvent',{type:'mousePressed',x:at.x,y:at.y,button:'left',buttons:1,clickCount:1});
        for(let i=1;i<=steps;i+=1){
          await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x+action.dx*i/steps,y:at.y+action.dy*i/steps,button:'left',buttons:1});
          await sleep(16);
        }
        await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:at.x+action.dx,y:at.y+action.dy,button:'left',buttons:0,clickCount:1});
        reads.dragFrom=at;
      }else if(action.reload!==undefined){
        await send('Page.reload',{ignoreCache:true});
        reads['reloaded']=await ready();
      }else if(action.resize!==undefined){
        await send('Emulation.setDeviceMetricsOverride',{width:action.resize.width,height:action.resize.height,deviceScaleFactor:1,mobile:false});
        await sleep(300);
      }
    }catch(error){reads.failed={action,error:String(error.message||error).slice(0,400)};break}
  }
  ws.close();
  process.stdout.write(JSON.stringify({reads,console:consoleLines,errors,requests}));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));
  killTree(chrome);
  await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){/* Windows tient le dossier */}
}

function killTree(child){
  if(process.platform==='win32'&&child.pid){
    try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore'});return}
    catch(_){/* deja sorti */}
  }
  child.kill();
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
