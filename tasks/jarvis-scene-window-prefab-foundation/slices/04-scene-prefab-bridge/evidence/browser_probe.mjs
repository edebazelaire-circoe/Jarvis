/* Preuve navigateur de la Slice 04 (pont scène ↔ prefab) : Chrome RÉEL sans tête
   (`--headless=new`, profil jetable `--user-data-dir`), piloté par CDP, sur la page
   SERVIE par un vrai Control Center relié à un vrai Core isolés (ports de scratch).

   Préalable : la fenêtre `counter-1` (`test.counter@1`, data {count: 3}) créée par
   `POST /api/scene/commands` (acteur user), voir EVIDENCE.md.

   Dans la page : la scène dessine la fenêtre ; on lit le cadre (cible attachée),
   on sélectionne, glisse et redimensionne par la tête et la poignée (vrais
   événements CDP), on tient la fenêtre par la couture Bare Hands
   (`JarvisScene.frames`), on clique « +1 » dans le cadre (événement de confiance),
   on recharge la page, puis Core demande une capture (acteur brain) que la page
   meneuse rend et envoie.

   Usage : node browser_probe.mjs <url du CC> <chrome.exe> <dossier de sortie> <url de Core> <fichier du jeton>
   Sortie : <dossier>/browser-results.json, scene-prefab.png, scene-prefab-reloaded.png, scene-capture.png */
import {spawn} from 'node:child_process';
import {copyFileSync, existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT,CORE,TOKEN_FILE]=process.argv;
const ID='counter-1';
const profile=mkdtempSync(join(tmpdir(),'jarvis-s04-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function debuggerTarget(){
  const file=join(profile,'DevToolsActivePort');
  const deadline=Date.now()+60000;
  while(Date.now()<deadline){
    if(existsSync(file)){
      const port=readFileSync(file,'utf8').split('\n')[0].trim();
      try{const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const page=list.find(t=>t.type==='page');if(page)return page}catch(_){/* Chrome démarre */}
    }
    await sleep(100);
  }
  throw new Error('Chrome debugger never came up');
}

const out={console:[],steps:{}};
try{
  const target=await debuggerTarget();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refused'))});
  let id=0;const pending=new Map();const sessions=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled'){
      const text=msg.params.args.map(a=>a.value??a.description??(a.preview?JSON.stringify(a.preview.properties.map(p=>[p.name,p.value])):'')).join(' ');
      out.console.push({session:msg.sessionId?'frame':'page',type:msg.params.type,text:text.slice(0,400)});
    }
    if(msg.method==='Runtime.exceptionThrown')out.console.push({session:msg.sessionId?'frame':'page',type:'exception',
      text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,400)});
    if(msg.method==='Target.attachedToTarget'){
      const s=msg.params.sessionId;sessions.set(s,msg.params.targetInfo);
      send('Runtime.enable',{},s).catch(()=>{});
      send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{});
    }
    if(msg.method==='Target.detachedFromTarget')sessions.delete(msg.params.sessionId);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression,session)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},session);
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,100)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);
    return r.result.value;
  };
  const until=async(check,ms=20000,label)=>{const deadline=Date.now()+ms;let last;
    while(Date.now()<deadline){try{last=await check();if(last)return last}catch(_){}await sleep(150)}
    throw new Error('never true: '+(label||check.toString().slice(0,120)))};
  /* Le cadre tourne hors processus (origine opaque) : lu dans sa session attachée. */
  const frameEval=async(expression)=>{
    for(const [session,info] of sessions){
      if(info.url!=='about:srcdoc')continue;
      try{const value=await evaluate(expression,session);if(value!==null&&value!==undefined)return value}catch(_){/* cible partie */}
    }
    return null;
  };
  const countInFrame=()=>frameEval("(()=>{const c=document.querySelector('.count');return c?c.textContent:null})()");
  const sel=`[data-object-id="${ID}"]`;
  const centerOf=(selector)=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;
    const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,w:r.width,h:r.height}})()`);
  const mouse=async(type,x,y,buttons)=>send('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:buttons??(type==='mouseReleased'?0:1),clickCount:1});
  const drag=async(from,dx,dy)=>{
    await mouse('mouseMoved',from.x,from.y,0);await mouse('mousePressed',from.x,from.y);
    for(let i=1;i<=12;i++){await mouse('mouseMoved',from.x+dx*i/12,from.y+dy*i/12);await sleep(16)}
    await mouse('mouseReleased',from.x+dx,from.y+dy);
  };
  const stored=()=>evaluate(`fetch('/api/scene',{cache:'no-store'}).then(r=>r.json()).then(b=>{
    const o=b.snapshot.objects.find(o=>o.object_id===${JSON.stringify(ID)});
    return {revision:b.revision,geometry:o.geometry,pinned:o.constraints.pinned_by_user,data:o.payload.prefab.data,title:o.payload.title}})`);
  const markFrame=()=>evaluate(`(()=>{const f=document.querySelector('${sel} .sc-prefab-slot iframe');if(!f)return false;f.__s04=f.__s04||'mark';return true})()`);
  const sameFrame=()=>evaluate(`(()=>{const f=document.querySelector('${sel} .sc-prefab-slot iframe');return !!f&&f.__s04==='mark'&&f.isConnected})()`);

  await send('Page.enable');await send('Runtime.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1280,height:800,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});

  /* 1. La scène dessine la fenêtre prefab ; le cadre est prêt. */
  await until(()=>evaluate(`!!document.querySelector('${sel} .sc-prefab-slot iframe')`),30000,'prefab iframe drawn');
  await until(async()=>(await countInFrame())==='3',20000,'frame shows count 3');
  await markFrame();
  out.steps.drawn=await evaluate(`(()=>{const el=document.querySelector('${sel}');const f=el.querySelector('iframe');
    return {classes:el.className,children:[...el.children].map(c=>c.className),sandbox:f.getAttribute('sandbox'),
      frameHeight:f.style.height,representation:el.dataset.representation,head:el.querySelector('.sc-cat').textContent,
      title:el.querySelector('.sc-wtitle').textContent,innerHTMLFree:!/innerHTML/.test(String(window.JarvisScene))}})()`);
  out.steps.frame=await frameEval("({origin:location.origin,count:document.querySelector('.count').textContent,label:document.querySelector('h2').textContent,"+
    "accent:getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim()})");
  out.steps.before=await stored();
  const shot1=await send('Page.captureScreenshot',{format:'png'});
  writeFileSync(join(OUT,'scene-prefab.png'),Buffer.from(shot1.data,'base64'));

  /* 2. Sélection par un clic sur la tête. */
  const title=await centerOf(`${sel} .sc-wtitle`);
  await mouse('mouseMoved',title.x,title.y,0);await mouse('mousePressed',title.x,title.y);await mouse('mouseReleased',title.x,title.y);
  out.steps.selected=await until(()=>evaluate(`document.querySelector('${sel}').classList.contains('sc-selected')&&JarvisScene.inspect().selected`),5000,'selected');

  /* 3. Glisser par la tête : déplacement commis, objet épinglé (Décision 9), cadre jamais remonté. */
  const head=await centerOf(`${sel} .sc-cat`);
  await drag(head,140,70);
  out.steps.moved=await until(async()=>{const s=await stored();
    return s.geometry.x!==out.steps.before.geometry.x&&s.pinned?s:null},8000,'moved and pinned');
  out.steps.movedSameFrame=await sameFrame();
  out.steps.pinIcon=await evaluate(`!!document.querySelector('${sel} .sc-head .sc-pin')`);

  /* 4. Redimensionner par la poignée. */
  const grip=await centerOf(`${sel} .sc-grip`);
  await drag({x:grip.x-2,y:grip.y-2},90,60);
  out.steps.resized=await until(async()=>{const s=await stored();
    return s.geometry.w>out.steps.moved.geometry.w&&s.geometry.h>out.steps.moved.geometry.h?s:null},8000,'resized');
  out.steps.resizedSameFrame=await sameFrame();

  /* 5. Bare Hands : la couture `JarvisScene.frames` tient la fenêtre prefab comme une autre. */
  out.steps.barehands=await evaluate(`(async()=>{const held=JarvisScene.frames.begin(${JSON.stringify(ID)});
    if(!held)return {held:null};
    const box={...held.box,x:held.box.x-40,y:held.box.y+20};
    JarvisScene.frames.preview(${JSON.stringify(ID)},box,'move');
    JarvisScene.frames.commit(${JSON.stringify(ID)},box,'move');
    return {held:{representation:held.representation,box:held.box}}})()`);
  out.steps.barehandsMoved=await until(async()=>{const s=await stored();
    return s.geometry.x!==out.steps.resized.geometry.x?s:null},8000,'bare hands commit');
  out.steps.barehandsSameFrame=await sameFrame();

  /* 6. Vrai clic sur « +1 » dans le cadre : événement d'état -> Core -> scène -> `update`. */
  const button=await frameEval("(()=>{const b=document.querySelector('button');if(!b)return null;const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()");
  const frameBox=await evaluate(`(()=>{const r=document.querySelector('${sel} iframe').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()`);
  out.steps.button={button,frameBox};
  const bx=frameBox.x+button.x,by=frameBox.y+button.y;
  await mouse('mouseMoved',bx,by,0);await mouse('mousePressed',bx,by);await mouse('mouseReleased',bx,by);
  out.steps.clicked=await until(async()=>(await countInFrame())==='4'?await stored():null,8000,'frame shows 4');
  out.steps.clickedSameFrame=await sameFrame();
  out.steps.events=await evaluate("fetch('/api/prefabs/events?limit=10',{cache:'no-store'}).then(r=>r.json())");
  /* Basis périmée envoyée par la page elle-même : `stale`, rien d'écrit. Clé non déclarée : refusé. */
  out.steps.stale=await evaluate(`fetch('/api/prefabs/events',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({actor:'brain',object_id:${JSON.stringify(ID)},prefab:{id:'test.counter',version:1},event:'incremented',
      payload:{count:9},basis:{count:3}})}).then(async r=>({status:r.status,body:await r.json()}))`);
  out.steps.refused=await evaluate(`fetch('/api/prefabs/events',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({object_id:${JSON.stringify(ID)},prefab:{id:'test.counter',version:1},event:'incremented',
      payload:{notes:'x'},basis:{notes:''}})}).then(async r=>({status:r.status,body:await r.json()}))`);
  out.steps.afterProbes=await stored();
  const shot2=await send('Page.captureScreenshot',{format:'png'});
  writeFileSync(join(OUT,'scene-prefab-clicked.png'),Buffer.from(shot2.data,'base64'));

  /* 7. Rechargement : l'état du compteur est celui de Core (persisté), pas celui du cadre. */
  await send('Page.reload',{ignoreCache:true});
  await sleep(500);
  await until(()=>evaluate(`!!document.querySelector('${sel} .sc-prefab-slot iframe')`),30000,'iframe after reload');
  out.steps.reloaded={count:await until(async()=>{const c=await countInFrame();return c==='4'?c:null},20000,'count 4 after reload'),
    stored:await stored(),pinIcon:await evaluate(`!!document.querySelector('${sel} .sc-head .sc-pin')`)};
  const shot3=await send('Page.captureScreenshot',{format:'png'});
  writeFileSync(join(OUT,'scene-prefab-reloaded.png'),Buffer.from(shot3.data,'base64'));

  /* 8. Capture demandée par le cerveau (Core) : la page meneuse dessine le repli prefab. */
  const token=readFileSync(TOKEN_FILE,'utf8').trim();
  await until(()=>evaluate("JarvisScene.inspect().leader.held"),10000,'leader');
  const capture=await fetch(`${CORE}/v1/scene/captures`,{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},
    body:JSON.stringify({schema_version:1,actor:'brain'})});
  out.steps.capture={status:capture.status,body:await capture.json()};
  if(capture.status===200&&out.steps.capture.body.path)copyFileSync(out.steps.capture.body.path,join(OUT,'scene-capture.png'));
  out.steps.captureCommands=await evaluate(`(()=>{const s=JarvisScene.inspect();return s.captures})()`);
  out.steps.finalSameFrameAfterReload=await evaluate(`!!document.querySelector('${sel} iframe')&&!document.querySelector('${sel} iframe').__s04`);
  ws.close();
}catch(error){out.error=String(error&&error.stack||error)}
finally{
  chrome.kill();await sleep(300);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome lâche son profil un peu plus tard */}
  writeFileSync(join(OUT,'browser-results.json'),JSON.stringify(out,null,2));
  console.log(JSON.stringify({error:out.error||null,steps:Object.keys(out.steps)}));
}
