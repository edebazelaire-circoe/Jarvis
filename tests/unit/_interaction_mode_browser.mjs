/* Harnais CDP pour `test_interaction_mode_hud_browser.py`.

   Chrome sans tete, une taille imposee, et des RECTANGLES et des STYLES
   CALCULES. Lire une feuille de style comme du texte a deja cache trois
   defauts dans cette Slice ; ce fichier existe pour ne plus jamais avoir a le
   faire. Il vit en JavaScript parce que le WebSocket dont il a besoin est celui
   que node fournit depuis la v22 — aucune dependance a installer.

   Usage : node _interaction_mode_browser.mjs <page> <chrome.exe> <planJSON> [runtimeRoot]
   Il ecrit sur la sortie standard un tableau JSON, un objet par etape du plan.

   `<page>` est un fichier compose, ou l'URL d'un VRAI Control Center
   (`http://127.0.0.1:<port>/`, Slice 03 de 2026-10) : la page fait alors son
   propre sondage a 1 Hz sur le vrai `/api/status`, et ses ecritures passent
   par la vraie route. `runtimeRoot` est le dossier d'execution de ce Control
   Center : le harnais y tient `.voice_heartbeat` a jour (Voice « en ligne »)
   et y ecrit `.voice_presentation` quand le plan le demande — exactement ce
   que `VisualSignalBus` ferait depuis Voice.

   Une etape peut porter `actions`, executees dans l'ordre apres le
   chargement ; chacune pousse son resultat dans `step.actions` :
     {"a":"write","file":".voice_presentation","value":{...}|null}
     {"a":"post","path":"/api/interaction-mode","body":{...}}   -> statut HTTP
     {"a":"wait","expr":"...","timeoutMs":3000}                 -> {ok,ms}
     {"a":"click","selector":"..."}      (vrai clic souris, au centre)
     {"a":"focus","selector":"..."}
     {"a":"key","key":"ArrowDown"}       (vraie frappe clavier)
     {"a":"ax","selector":"..."}         -> {role,name,description} calcules
     {"a":"eval","expr":"..."}
     {"a":"read"}
     {"a":"shot","path":"...png"} */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync, renameSync, unlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN,RUNTIME]=process.argv;
const plan=JSON.parse(PLAN);
const REMOTE=/^https?:\/\//.test(PAGE);

/* Ecriture atomique, comme `VisualSignalBus._atomic_text` : le Control Center
   relit ces fichiers a chaque battement, et une lecture a moitie ecrite
   rendrait `presentation: null` pour un battement. */
function atomic(file,text){
  const path=join(RUNTIME,file),tmp=`${path}.${process.pid}.tmp`;
  writeFileSync(tmp,text,'utf-8');
  for(let i=0;i<20;i+=1){
    try{renameSync(tmp,path);return}
    catch(_){/* Windows : le lecteur tient le fichier un instant */}
  }
  throw new Error(`ecriture impossible : ${file}`);
}
function heartbeat(){
  try{atomic('.voice_heartbeat',`${Date.now()/1000}\n`)}catch(_){/* le battement suivant reessaie */}
}
const beating=RUNTIME?(heartbeat(),setInterval(heartbeat,400)):null;

/* La palette Bare Hands n'existe que si Bare Hands se monte — camera, MediaPipe,
   rien de tout cela sous node. On pose donc son emplacement et on installe SA
   feuille, la vraie, celle que son module exporte, puis de vrais boutons
   d'outil. La geometrie mesuree est alors celle que la page produit. Trois
   outils : le plancher, pas le pire des cas. */
const MOUNT_PALETTE=`(()=>{
  const H=window.JarvisBarehandsHud;
  if(!H||!H.STYLE)return 'pas de module hud';
  const style=document.createElement('style');
  style.textContent=H.STYLE;
  document.head.appendChild(style);
  const host=document.getElementById(H.DOM.paletteId);
  if(!host)return 'pas d emplacement';
  const strip=document.createElement('div');
  strip.className='bh-tools';
  for(let i=0;i<3;i+=1){
    const button=document.createElement('button');
    button.className='bh-tool';button.type='button';
    strip.appendChild(button);
  }
  host.appendChild(strip);
  return 'ok';
})()`;

/* Une infusion reelle : elles montent depuis le bas et sont au rang 70, donc
   au-dessus de ce controle. « Les notifications » sont nommees dans la
   verification humaine de cette Slice. */
const MOUNT_TOAST=`(()=>{
  const host=document.getElementById('toasts');
  if(!host)return 'pas d emplacement';
  const toast=document.createElement('div');
  toast.className='toast';
  toast.innerHTML='<strong>Test</strong><span>Une notification de hauteur ordinaire</span>';
  host.appendChild(toast);
  return 'ok';
})()`;

const READ=`(()=>{
  const seen={};
  const box=(name,selector)=>{
    const el=document.querySelector(selector);
    if(!el){seen[name]=null;return}
    const r=el.getBoundingClientRect();
    if(!r.width&&!r.height){seen[name]=null;return}
    seen[name]={l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height,
      z:getComputedStyle(el).zIndex};
  };
  box('modeBtn','#interactionModeButton');
  box('palette','#barehandsPalette');
  box('bhHud','#barehandsHud');
  box('dock','.dock');
  box('pills','.bgpills');
  box('hint','.voicehint');
  box('toast','.toasts .toast');
  box('pres','#interactionModePresence');
  box('presText','#interactionModePresence .im-pres-text');
  const host=document.getElementById('interactionModeHud');
  /* La ligne de la seance (Slice 03 de 2026-10) : ce qu'elle dit, son code, et
     si son texte est coupe (largeur de defilement > largeur visible). */
  const pres=document.getElementById('interactionModePresence');
  const presText=pres&&pres.querySelector('.im-pres-text');
  seen.presence={
    state:host&&host.getAttribute('data-im-presence'),
    hidden:pres?pres.hidden:null,
    text:presText?presText.textContent:null,
    title:pres?pres.getAttribute('title'):null,
    clipped:presText?presText.scrollWidth>presText.clientWidth+1:null,
    color:pres?getComputedStyle(pres).color:null,
    dot:pres?getComputedStyle(pres.querySelector('.im-pres-dot')).animationName:null,
  };
  seen.mode=host&&host.getAttribute('data-im-mode');
  const trig=document.getElementById('interactionModeButton');
  seen.button={title:trig?trig.getAttribute('title'):null,label:trig?trig.getAttribute('aria-label'):null};
  const hintNode=document.getElementById('interactionModeHint');
  seen.chooserHint=hintNode?hintNode.textContent:null;
  const mark=host&&host.querySelector('.im-mark');
  const wait=host&&host.querySelector('.im-wait');
  const button=host&&host.querySelector('.im-btn');
  const pop=host&&host.querySelector('.im-pop');
  /* Le halo et le balayage vivent sur des pseudo-elements : c'est le second
     argument de getComputedStyle qui les atteint, et c'est precisement ce
     qu'une lecture de la feuille ne peut pas faire. */
  seen.motion={
    halo:mark?getComputedStyle(mark,'::after').animation:null,
    haloOpacity:mark?getComputedStyle(mark,'::after').opacity:null,
    glow:button?getComputedStyle(button).boxShadow:null,
    sweep:wait?getComputedStyle(wait,'::after').animation:null,
    popAnimation:pop?getComputedStyle(pop).animation:null,
    buttonTransition:button?getComputedStyle(button).transition:null,
  };
  seen.viewport={w:innerWidth,h:innerHeight};
  return seen;
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-im-cdp-'));
const port=9222+Math.floor(Math.random()*500);
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
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
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
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',
      {expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)
      throw new Error(r.exceptionDetails.exception?.description
        ||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };

  await send('Page.enable');
  await send('Runtime.enable');
  /* « Dans un battement » se compte en battements, pas en millisecondes : la
     page partage ses connexions avec ses autres sondages, et une horloge
     murale mesurerait la charge de la machine. On compte donc les reponses de
     `/api/status` que la page a VRAIMENT recues, avant son propre code. */
  await send('Page.addScriptToEvaluateOnNewDocument',{source:`(()=>{
    window.__statusDone=0;
    const real=window.fetch.bind(window);
    window.fetch=(input,init)=>{
      const url=String(input&&input.url||input);
      const pending=real(input,init);
      if(url.includes('/api/status'))
        pending.then(()=>{window.__statusDone+=1},()=>{window.__statusDone+=1});
      return pending;
    };
  })()`});
  const out=[];
  for(const step of plan){
    await send('Emulation.setEmulatedMedia',{features:step.reducedMotion
      ?[{name:'prefers-reduced-motion',value:'reduce'}]:[]});
    await send('Emulation.setDeviceMetricsOverride',
      {width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:REMOTE?PAGE:'file:///'+PAGE.replace(/\\/g,'/')});
    await sleep(900);
    await send('Emulation.setDeviceMetricsOverride',
      {width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
    await sleep(250);
    if(step.mountPalette){
      const said=await evaluate(MOUNT_PALETTE);
      if(said!=='ok')throw new Error('palette : '+said);
    }
    if(step.toast){
      const said=await evaluate(MOUNT_TOAST);
      if(said!=='ok')throw new Error('infusion : '+said);
    }
    if(step.tone)
      await evaluate(`document.getElementById('interactionModeHud')
        .setAttribute('data-im-tone',${JSON.stringify(step.tone)})`);
    await sleep(150);
    const seen=await evaluate(READ);
    if(step.actions){
      seen.actions=[];
      for(const action of step.actions)seen.actions.push(await act(action));
    }
    out.push(seen);
  }
  ws.close();
  process.stdout.write(JSON.stringify(out));

  /* Une action du plan. Les entrees sont de VRAIS evenements d'entree (CDP
     `Input.*`), pas des `click()` appeles en JavaScript : c'est le seul niveau
     ou « le clavier atteint ce que la souris atteint » veut dire quelque chose. */
  async function act(action){
    switch(action.a){
      case 'write':
        if(action.value===null){try{unlinkSync(join(RUNTIME,action.file))}catch(_){/* deja absent */}}
        /* `ageS` : un relevé daté du passé, comme un refus laissé par une séance précédente. */
        else atomic(action.file,JSON.stringify({...action.value,ts:Date.now()/1000-(action.ageS||0)}));
        return {a:'write'};
      case 'post':{
        const origin=new URL(PAGE).origin;
        const res=await fetch(origin+action.path,{method:'POST',
          headers:{'Content-Type':'application/json',Origin:origin},
          body:JSON.stringify(action.body)});
        return {a:'post',status:res.status};
      }
      case 'wait':{
        /* `polls` : les reponses de statut recues pendant l'attente. */
        const started=Date.now(),before=await evaluate('window.__statusDone||0');
        for(;;){
          let value=null;
          try{value=await evaluate(action.expr)}catch(_){/* page en cours de rendu */}
          const polls=(await evaluate('window.__statusDone||0'))-before;
          if(value)return {a:'wait',ok:true,ms:Date.now()-started,polls};
          if(Date.now()-started>(action.timeoutMs||3000))
            return {a:'wait',ok:false,ms:Date.now()-started,polls};
          await sleep(25);
        }
      }
      case 'click':{
        const box=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(action.selector)})
          .getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
        for(const type of ['mouseMoved','mousePressed','mouseReleased'])
          await send('Input.dispatchMouseEvent',{type,x:box.x,y:box.y,button:'left',clickCount:1});
        await sleep(60);
        return {a:'click'};
      }
      case 'focus':
        await evaluate(`document.querySelector(${JSON.stringify(action.selector)}).focus()`);
        return {a:'focus'};
      case 'key':{
        const codes={ArrowDown:40,ArrowUp:38,Escape:27,Enter:13,Tab:9,Home:36,End:35,' ':32};
        const base={key:action.key,code:action.key===' '?'Space':action.key,
          windowsVirtualKeyCode:codes[action.key]||0};
        await send('Input.dispatchKeyEvent',{type:'keyDown',...base,
          ...(action.key==='Enter'?{text:'\r'}:action.key===' '?{text:' '}:{})});
        await send('Input.dispatchKeyEvent',{type:'keyUp',...base});
        await sleep(60);
        return {a:'key',focused:await evaluate(`(()=>{const e=document.activeElement;
          return e?(e.getAttribute('data-im-mode')||e.id||e.tagName):null})()`)};
      }
      case 'ax':{
        const {root}=await send('DOM.getDocument',{depth:0});
        const {nodeId}=await send('DOM.querySelector',{nodeId:root.nodeId,selector:action.selector});
        if(!nodeId)return {a:'ax',missing:true};
        const {nodes}=await send('Accessibility.getPartialAXTree',{nodeId,fetchRelatives:false});
        const node=nodes[0]||{};
        return {a:'ax',role:node.role&&node.role.value,name:node.name&&node.name.value,
          description:node.description&&node.description.value,
          ignored:!!node.ignored};
      }
      case 'eval':
        return {a:'eval',value:await evaluate(action.expr)};
      case 'read':
        return {a:'read',value:await evaluate(READ)};
      case 'shot':{
        const {data}=await send('Page.captureScreenshot',{format:'png'});
        writeFileSync(action.path,Buffer.from(data,'base64'));
        return {a:'shot',path:action.path};
      }
      default:
        throw new Error('action inconnue : '+action.a);
    }
  }
}finally{
  if(beating)clearInterval(beating);
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
