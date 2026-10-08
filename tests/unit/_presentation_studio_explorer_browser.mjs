/* Harnais CDP des preuves navigateur de l'explorateur de variantes (handoff jarvis-interactive-presentation-studio, Slice 18).

   Chrome sans tête (`--headless=new`) contre la VRAIE page du Control Center servie par un Core isolé (le test choisit les ports et la racine de
   données ; jamais le Jarvis vivant). Dérivé de `_fullscreen_browser.mjs` et du harnais de l'inspecteur (même nettoyage : Chrome est tué AVEC ses
   enfants, puis le profil `jarvis-pse-cdp-*` est effacé), avec ce que l'explorateur exige : VRAIS clics (gauche et droit) et VRAIES touches avec
   modificateurs (le clic donne l'activation utilisateur que l'API Fullscreen exige), saisie de texte, arbre d'accessibilité, mouvement réduit
   émulé, TOUTE la console (le test refuse le bruit), requêtes HTTP faites par le plan lui-même (la demande d'un agent vers le Control Center,
   pendant que la page attend sa commande) et empreinte d'un arbre de fichiers (prouve qu'un geste n'écrit rien).

   Usage : node _presentation_studio_explorer_browser.mjs <url> <chrome.exe> <planJSON>
   Environnement : CDP_VIEWPORT=LxH (1280x720 par défaut), CDP_REDUCED_MOTION=1, CDP_READY=<expression> (défaut : le module est installé).
   Actions : {eval}, {wait}, {click: sel}, {rclick: sel}, {key: nom, ctrl?, shift?, alt?}, {type: texte}, {focus: sel}, {value: nom, expr},
     {until: expr, ms}, {size: [w,h]}, {shot: chemin.png}, {ax: nom, root: sel}, {hashTree: nom, path}, {hashFile: nom, path},
     {http: {name, method, path, body}} (le plan appelle le Control Center ; la réponse est lue sous `reads[name]`),
     {frameValue: nom, object_id, expr}, {frameUntil: {object_id, expr, ms}} (évalue DANS le cadre de prefab, lu comme un contenu non fiable).
   Sortie : {reads, console, errors}. */
import {execFileSync, spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);
const [VIEW_W,VIEW_H]=(process.env.CDP_VIEWPORT||'1280x720').split('x').map(Number);

const profile=mkdtempSync(join(tmpdir(),'jarvis-pse-cdp-'));
const port=9600+Math.floor(Math.random()*150);
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
    Tab:{code:'Tab',keyCode:9},Delete:{code:'Delete',keyCode:46},F2:{code:'F2',keyCode:113},ContextMenu:{code:'ContextMenu',keyCode:93},
    F10:{code:'F10',keyCode:121}};
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
  const centre=async selector=>{
    const at=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});
      if(!el)return null;el.scrollIntoView({block:'nearest',inline:'nearest'});const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
    if(!at)throw new Error('introuvable '+selector);
    return at;
  };
  const click=async (selector,button='left')=>{
    const at=await centre(selector);
    const buttons=button==='right'?2:1;
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x,y:at.y,button:'none',buttons:0});
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x:at.x,y:at.y,button,buttons,clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:at.x,y:at.y,button,buttons:0,clickCount:1});
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
  const hashTree=(dir)=>{
    const h=createHash('sha256');
    const walk=(d,rel)=>{
      for(const name of readdirSync(d).sort()){
        const full=join(d,name),r=rel?rel+'/'+name:name;
        const st=statSync(full);
        if(st.isDirectory()){h.update('D:'+r+'\n');walk(full,r)}
        else{h.update('F:'+r+':'+st.size+'\n');h.update(readFileSync(full))}
      }
    };
    walk(dir,'');
    return h.digest('hex');
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
  const ready=process.env.CDP_READY||`!!window.JarvisStudioExplorer&&!!window.JarvisFullscreen&&!!window.JarvisPrefabHost`;
  for(let i=0;i<300;i+=1){
    await sleep(50);
    const ok=await evaluate(`document.readyState==='complete'&&(${ready})`).catch(()=>false);
    if(ok)break;
  }
  await sleep(200);
  const reads={};
  for(const action of plan){
   try{
    if(action.eval!==undefined)await evaluate(action.eval);
    else if(action.wait!==undefined)await sleep(action.wait);
    else if(action.key!==undefined)await press(action.key,action);
    else if(action.type!==undefined)await send('Input.insertText',{text:action.type});
    else if(action.focus!==undefined)await evaluate(`document.querySelector(${JSON.stringify(action.focus)}).focus()`);
    else if(action.click!==undefined)await click(action.click);
    else if(action.rclick!==undefined)await click(action.rclick,'right');
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
    else if(action.hashTree!==undefined)reads[action.hashTree]=hashTree(action.path);
    else if(action.hashFile!==undefined)reads[action.hashFile]=createHash('sha256').update(readFileSync(action.path)).digest('hex');
    else if(action.http!==undefined){
      const spec=action.http;
      const response=await fetch(new URL(spec.path,PAGE),{method:spec.method||'GET',headers:spec.body?{'Content-Type':'application/json'}:undefined,
        body:spec.body?JSON.stringify(spec.body):undefined});
      let body=null;
      try{body=await response.json()}catch(_){body=null}
      reads[spec.name]={status:response.status,body};
    }
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
