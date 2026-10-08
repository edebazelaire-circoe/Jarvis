/* Harnais CDP des preuves navigateur de l'inspecteur du Studio (handoff jarvis-interactive-presentation-studio, Slice 07).

   Chrome sans tête (`--headless=new`) contre la VRAIE page du Control Center servie par un Core isole (le test choisit les ports et la
   racine de donnees ; jamais le Jarvis vivant). Dérivé de `_fullscreen_browser.mjs` (même nettoyage), avec ce que l'inspecteur exige :
   VRAIS gestes de souris (appui, déplacements, relâchement : un curseur se glisse vraiment), VRAIES touches avec modificateurs, saisie
   de texte, arbre d'accessibilité, couleurs/mouvement réduit émulés, et TOUTE la console (le test refuse le bruit).

   Usage : node _presentation_studio_inspector_browser.mjs <url> <chrome.exe> <planJSON>
   Environnement : CDP_VIEWPORT=LxH (1280x720 par défaut), CDP_REDUCED_MOTION=1.
   Fin : Chrome est tué AVEC ses enfants (`taskkill /T /F`), puis le profil `jarvis-psi-cdp-*` est effacé.
   Actions : {eval}, {wait}, {click: selecteur}, {key: nom, ctrl?, shift?, alt?}, {hold: {key, ms, interval}} (touche maintenue, répétition automatique), {wheel: {selector, deltaY, count}} (molette sur l'élément), {type: texte}, {focus: selecteur},
     {mouseDown: {selector, frac}}, {mouseMove: {selector, frac}}, {mouseUp: {selector, frac}}, {drag: {selector, from, to, steps, ms}},
     {value: nom, expr}, {until: expr, ms}, {size: [w,h]}, {shot: chemin.png}, {ax: nom, root: selecteur},
     {hashFile: nom, path} (empreinte SHA-256 d'un fichier du Core, lue pendant le plan : prouve qu'un geste n'écrit rien),
     {frameValue: nom, object_id, expr}, {frameUntil: {object_id, expr, ms}} (évalue DANS le cadre de prefab, lu comme un contenu non fiable).
   `frac` : position le long d'un curseur horizontal (0..1), vers le centre de la poignée de 20 px. Sortie : {reads, console, errors}. */
import {execFileSync, spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);
const [VIEW_W,VIEW_H]=(process.env.CDP_VIEWPORT||'1280x720').split('x').map(Number);

const profile=mkdtempSync(join(tmpdir(),'jarvis-psi-cdp-'));
const port=9800+Math.floor(Math.random()*150);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const consoleLines=[],errors=[];const frames=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    const where=msg.sessionId?'frame':'page';
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):(a.description||'')).join(' ');
      consoleLines.push({where,type:msg.params.type,text});
    }else if(msg.method==='Log.entryAdded'){
      const e=msg.params.entry;
      if(e.level==='error'||e.level==='warning')consoleLines.push({where,type:'log-'+e.level,text:`${e.source}: ${e.text} ${e.url||''}`.trim()});
    }else if(msg.method==='Runtime.exceptionThrown'){
      const text=msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text;
      if(where==='frame')consoleLines.push({where,type:'exception',text});else errors.push(text);
    }else if(msg.method==='Target.attachedToTarget'){
      const info=msg.params.targetInfo;
      if(info.type==='iframe'){
        const session={sessionId:msg.params.sessionId,alive:true};
        frames.push(session);
        send('Runtime.enable',{},session.sessionId).catch(()=>{});
        send('Log.enable',{},session.sessionId).catch(()=>{});
      }
    }else if(msg.method==='Target.detachedFromTarget'){
      const found=frames.find(f=>f.sessionId===msg.params.sessionId);
      if(found)found.alive=false;
    }
  };
  const send=(method,params={},sessionId)=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify(Object.assign({id:mine,method,params},sessionId?{sessionId}:{})));
  });
  const evaluate=async (expression,sessionId)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},sessionId);
    if(r.exceptionDetails)
      throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const KEYS_BASE={ArrowRight:{code:'ArrowRight',keyCode:39},ArrowLeft:{code:'ArrowLeft',keyCode:37},' ':{code:'Space',keyCode:32,text:' '},
    Escape:{code:'Escape',keyCode:27},Enter:{code:'Enter',keyCode:13,text:'\r'},Home:{code:'Home',keyCode:36},
    End:{code:'End',keyCode:35},ArrowUp:{code:'ArrowUp',keyCode:38},ArrowDown:{code:'ArrowDown',keyCode:40},
    PageDown:{code:'PageDown',keyCode:34},PageUp:{code:'PageUp',keyCode:33},Backspace:{code:'Backspace',keyCode:8},
    Tab:{code:'Tab',keyCode:9},Delete:{code:'Delete',keyCode:46}};
  const keyOf=key=>{
    if(KEYS_BASE[key])return KEYS_BASE[key];
    if(/^[A-Za-z]$/.test(key))return {code:'Key'+key.toUpperCase(),keyCode:key.toUpperCase().charCodeAt(0),text:key};
    if(/^[0-9]$/.test(key))return {code:'Digit'+key,keyCode:key.charCodeAt(0),text:key};
    throw new Error('touche inconnue '+key);
  };
  const press=async (key,mods={})=>{
    const k=keyOf(key);
    const modifiers=(mods.alt?1:0)|(mods.ctrl?2:0)|(mods.meta?4:0)|(mods.shift?8:0);
    const text=(mods.ctrl||mods.alt||mods.meta)?undefined:k.text;
    await send('Input.dispatchKeyEvent',{type:text?'keyDown':'rawKeyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,
      nativeVirtualKeyCode:k.keyCode,text,modifiers});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,
      nativeVirtualKeyCode:k.keyCode,modifiers});
  };
  /* Touche maintenue : keyDown répétés (autoRepeat) toutes les `interval` ms pendant `ms`, puis un seul keyUp, comme le clavier. */
  const hold=async (key,ms,interval)=>{
    const k=keyOf(key);const end=Date.now()+ms;let first=true;
    while(Date.now()<end){
      await send('Input.dispatchKeyEvent',{type:'rawKeyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,autoRepeat:!first});
      first=false;await sleep(interval);
    }
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode});
  };
  const rectOf=async selector=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;el.scrollIntoView({block:'center',inline:'nearest'});const r=el.getBoundingClientRect();return {l:r.left,t:r.top,w:r.width,h:r.height}})()`);
    if(!at)throw new Error('introuvable '+selector);
    return at;
  };
  const centre=async selector=>{const r=await rectOf(selector);return {x:r.l+r.w/2,y:r.t+r.h/2}};
  const pointAt=async (selector,frac)=>{
    const r=await rectOf(selector);
    const thumb=10;       /* la poignée fait 20 px : son centre va de 10 px au bord à 10 px de l'autre bord */
    return {x:r.l+thumb+(r.w-2*thumb)*frac,y:r.t+r.h/2};
  };
  const click=async selector=>{
    const at=await centre(selector);
    for(const type of ['mouseMoved','mousePressed','mouseReleased'])
      await send('Input.dispatchMouseEvent',{type,x:at.x,y:at.y,button:'left',clickCount:1});
  };
  let buttons=0;
  const mouse=async (type,at)=>{
    await send('Input.dispatchMouseEvent',{type,x:at.x,y:at.y,button:type==='mouseMoved'&&!buttons?'none':'left',buttons,clickCount:type==='mouseMoved'?0:1});
  };

  const frameOf=async objectId=>{
    for(const session of frames.filter(f=>f.alive).reverse()){
      try{
        const found=await evaluate(`typeof jarvis==='object'&&jarvis.instance?jarvis.instance.object_id:null`,session.sessionId);
        if(found===objectId)return session;
      }catch(_){/* cadre en cours de chargement */}
    }
    throw new Error('cadre introuvable : '+objectId);
  };
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Log.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('DOM.enable').catch(()=>{});
  await send('Accessibility.enable').catch(()=>{});
  await send('Emulation.setDeviceMetricsOverride',{width:VIEW_W,height:VIEW_H,deviceScaleFactor:1,mobile:false});
  if(process.env.CDP_REDUCED_MOTION==='1')
    await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:'reduce'}]});
  await send('Page.navigate',{url:PAGE});
  for(let i=0;i<300;i+=1){
    await sleep(50);
    const ready=await evaluate(`document.readyState==='complete'&&!!window.JarvisStudioInspector&&!!window.JarvisStudioInspector.instance`).catch(()=>false);
    if(ready)break;
  }
  await sleep(200);
  const reads={};
  for(const action of plan){
   try{
    if(action.eval!==undefined)await evaluate(action.eval);
    else if(action.wait!==undefined)await sleep(action.wait);
    else if(action.key!==undefined)await press(action.key,action);
    else if(action.hold!==undefined)await hold(action.hold.key,action.hold.ms,action.hold.interval||33);
    else if(action.wheel!==undefined){
      const at=await centre(action.wheel.selector);
      await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x,y:at.y,button:'none',buttons:0});
      for(let i=0;i<(action.wheel.count||1);i+=1){
        await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:at.x,y:at.y,deltaX:0,deltaY:action.wheel.deltaY||-100});
        await sleep(action.wheel.interval||40);
      }
    }
    else if(action.type!==undefined)await send('Input.insertText',{text:action.type});
    else if(action.focus!==undefined)await evaluate(`document.querySelector(${JSON.stringify(action.focus)}).focus()`);
    else if(action.click!==undefined)await click(action.click);
    else if(action.mouseDown!==undefined){
      const at=await pointAt(action.mouseDown.selector,action.mouseDown.frac);
      await mouse('mouseMoved',at);buttons=1;await mouse('mousePressed',at);
    }
    else if(action.mouseMove!==undefined){
      const at=await pointAt(action.mouseMove.selector,action.mouseMove.frac);
      await mouse('mouseMoved',at);
    }
    else if(action.mouseUp!==undefined){
      const at=await pointAt(action.mouseUp.selector,action.mouseUp.frac);
      await mouse('mouseReleased',at);buttons=0;
    }
    else if(action.drag!==undefined){
      const d=action.drag,steps=d.steps||30;
      await mouse('mouseMoved',await pointAt(d.selector,d.from));buttons=1;
      await mouse('mousePressed',await pointAt(d.selector,d.from));
      for(let i=1;i<=steps;i+=1){
        await mouse('mouseMoved',await pointAt(d.selector,d.from+(d.to-d.from)*i/steps));
        if(d.ms)await sleep(d.ms);
      }
      if(d.hold)await sleep(d.hold);
      await mouse('mouseReleased',await pointAt(d.selector,d.to));buttons=0;
    }
    else if(action.size!==undefined)
      await send('Emulation.setDeviceMetricsOverride',{width:action.size[0],height:action.size[1],deviceScaleFactor:1,mobile:false});
    else if(action.shot!==undefined){
      const shot=await send('Page.captureScreenshot',{format:'png'});
      writeFileSync(action.shot,Buffer.from(shot.data,'base64'));
    }
    else if(action.ax!==undefined){
      const tree=await send('Accessibility.getFullAXTree');
      const nodes=tree.nodes||[];
      const byId=new Map(nodes.map(n=>[n.nodeId,n]));
      const rootInfo=await send('Runtime.evaluate',{expression:`document.querySelector(${JSON.stringify(action.root)})`});
      const described=await send('DOM.describeNode',{objectId:rootInfo.result.objectId}).catch(()=>null);
      const backendId=described&&described.node&&described.node.backendNodeId;
      const inside=n=>{
        for(let cur=n;cur;cur=byId.get(cur.parentId)){if(cur.backendDOMNodeId===backendId)return true}
        return false;
      };
      reads[action.ax]=nodes.filter(n=>!n.ignored&&backendId&&inside(n)).map(n=>({
        role:n.role?.value,name:n.name?.value||'',value:n.value?.value??null,
        props:Object.fromEntries((n.properties||[]).map(p=>[p.name,p.value?.value]))}));
    }
    else if(action.axe!==undefined){
      /* axe-core n'est pas dans le dépôt : si JARVIS_AXE_JS le désigne, on l'exécute sur le panneau ; sinon la lecture est `null`. */
      const file=process.env.JARVIS_AXE_JS;
      if(!file)reads[action.axe]=null;
      else{
        await evaluate(readFileSync(file,'utf8'));
        reads[action.axe]=await evaluate(`axe.run(document.querySelector(${JSON.stringify(action.root)}),{resultTypes:['violations']}).then(r=>r.violations.map(v=>({id:v.id,impact:v.impact,nodes:v.nodes.length})))`);
      }
    }
    else if(action.hashFile!==undefined)reads[action.hashFile]=createHash('sha256').update(readFileSync(action.path)).digest('hex');
    else if(action.frameValue!==undefined)reads[action.frameValue]=await evaluate(action.expr,(await frameOf(action.object_id)).sessionId);
    else if(action.frameUntil!==undefined){
      const spec=action.frameUntil;const end=Date.now()+(spec.ms||5000);let ok=false;
      while(Date.now()<end){
        try{ok=!!(await evaluate(spec.expr,(await frameOf(spec.object_id)).sessionId))}catch(_){ok=false}
        if(ok)break;await sleep(50);
      }
      reads['frameUntil:'+spec.expr]=ok;
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
  const exited=new Promise(resolve=>chrome.once('exit',resolve));
  killTree(chrome);
  await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){/* dernier recours : il reste, le test le signale */}
}

function killTree(child){
  if(process.platform==='win32'&&child.pid){
    try{execFileSync('taskkill',['/PID',String(child.pid),'/T','/F'],{stdio:'ignore'});return}
    catch(_){/* deja sorti, ou taskkill refuse : on retombe sur kill() */}
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
