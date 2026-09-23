/* Harnais CDP pour `test_interaction_mode_hud_browser.py`.

   Chrome sans tete, une taille imposee, et des RECTANGLES et des STYLES
   CALCULES. Lire une feuille de style comme du texte a deja cache trois
   defauts dans cette Slice ; ce fichier existe pour ne plus jamais avoir a le
   faire. Il vit en JavaScript parce que le WebSocket dont il a besoin est celui
   que node fournit depuis la v22 — aucune dependance a installer.

   Usage : node _interaction_mode_browser.mjs <page.html> <chrome.exe> <planJSON>
   Il ecrit sur la sortie standard un tableau JSON, un objet par etape du plan. */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);

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
  const host=document.getElementById('interactionModeHud');
  const mark=host&&host.querySelector('.im-mark');
  const wait=host&&host.querySelector('.im-wait');
  const button=host&&host.querySelector('.im-btn');
  const pop=host&&host.querySelector('.im-pop');
  /* Le halo et le balayage vivent sur des pseudo-elements : c'est le second
     argument de getComputedStyle qui les atteint, et c'est precisement ce
     qu'une lecture de la feuille ne peut pas faire. */
  seen.motion={
    halo:mark?getComputedStyle(mark,'::after').animation:null,
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
  const out=[];
  for(const step of plan){
    await send('Emulation.setEmulatedMedia',{features:step.reducedMotion
      ?[{name:'prefers-reduced-motion',value:'reduce'}]:[]});
    await send('Page.navigate',{url:'file:///'+PAGE.replace(/\\/g,'/')});
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
    out.push(await evaluate(READ));
  }
  ws.close();
  process.stdout.write(JSON.stringify(out));
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
