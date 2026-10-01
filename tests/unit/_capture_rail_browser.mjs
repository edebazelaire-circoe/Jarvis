/* Harnais CDP pour `test_capture_rail_browser.py` (session-context-recording, Slice 10).

   Chrome sans tete, la page SERVIE (composee comme `ControlCenter.index`), une
   taille imposee, et des rectangles, attributs et styles CALCULES. Le relais
   `/api/captures/*` est remplace, dans la page et avant tout script, par un
   double en memoire (`window.__cap`) : la page n'a pas de Core sous `file://`,
   et c'est l'interface qui est mesuree ici, pas Core (la chaine reelle est
   prouvee par `test_capture_relay.py` et par la validation en direct).

   Usage : node _capture_rail_browser.mjs <page.html> <chrome.exe> <planJSON>
   Un objet par etape du plan sur la sortie standard : `{reads:{nom: lecture}}`.
   Actions d'une etape : `{eval}`, `{wait}`, `{key}` (vraie frappe CDP),
   `{click: selecteur}` (vrai clic souris au centre), `{read: nom}`. */
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);

/* Le double du relais. Etat des captures en memoire ; `down` simule un
   Control Center / Core injoignable ; `refuse[canal]` un refus de Core avec
   son enveloppe ; `hold[canal]` retient une ecriture jusqu'a liberation. */
const FAKE_RELAY=`(()=>{
  const cap=window.__cap={open:[],stuck:[],recent:[],down:false,refuse:{},hold:{},release:{},calls:[],seq:0};
  const iso=()=>new Date().toISOString();
  const json=(status,obj)=>new Response(JSON.stringify(obj),{status,headers:{'Content-Type':'application/json'}});
  const held=key=>cap.hold[key]?new Promise(ok=>{cap.release[key]=ok}):null;
  window.fetch=async(url,init)=>{
    const u=String(url),method=(init&&init.method)||'GET';
    if(!u.startsWith('/api/captures'))throw new TypeError('Failed to fetch');
    cap.calls.push({method,url:u,body:init&&init.body||null});
    if(cap.down)throw new TypeError('Failed to fetch');
    if(u.startsWith('/api/captures/status'))
      return json(200,{captures:cap.open,stuck:cap.stuck,recent:cap.recent,recovery:null,enrichment:{state:'idle'}});
    if(u==='/api/captures/start'&&method==='POST'){
      const ch=JSON.parse(init.body).channel;
      const wait=held(ch);if(wait)await wait;
      const r=cap.refuse[ch];
      if(r&&r.viaRow){
        /* Comme Core : la ligne existe (« starting » puis « stopping ») le
           temps que la source refuse, puis finit « failed ». */
        const row={capture_id:'jcap_'+ch+'_refused',channel:ch,mode:'continuous',state:'stopping',
          created_at:iso(),activated_at:null,stop_requested_at:iso()};
        cap.open.push(row);
        await new Promise(ok=>setTimeout(ok,r.viaRow));
        cap.open=cap.open.filter(x=>x!==row);
        cap.recent.unshift({...row,state:'failed',error_code:r.code,stop_reason:'start_failed',ended_at:iso()});
      }
      if(r)return json(r.status,{error:{code:r.code,message:r.message}});
      const holder=cap.open.find(c=>c.channel===ch);
      if(holder)return json(409,{error:{code:'already_active',message:'held',capture_id:holder.capture_id}});
      const now=iso();
      const c={capture_id:'jcap_'+ch+'_'+(++cap.seq),channel:ch,mode:'continuous',source:'fake',device:'default',
        state:'active',created_at:now,updated_at:now,activated_at:now,stop_requested_at:null,ended_at:null,
        error_code:null,stop_reason:null,gaps:0,bytes_written:0,data:{},artifact_id:'jart_'+cap.seq};
      cap.open.push(c);
      return json(201,{capture:c});
    }
    if(u==='/api/captures/screenshot'&&method==='POST'){
      const wait=held('screenshot');if(wait)await wait;
      const r=cap.refuse.screenshot;
      if(r)return json(r.status,{error:{code:r.code,message:r.message}});
      return json(201,{capture:{capture_id:'jcap_shot_'+(++cap.seq),channel:'screen',mode:'one_shot',state:'complete'},
        artifact:{artifact_id:'jart_shot_'+cap.seq}});
    }
    const m=u.match(/^\\/api\\/captures\\/([^/]+)\\/stop$/);
    if(m&&method==='POST'){
      const id=decodeURIComponent(m[1]);
      const c=cap.open.find(x=>x.capture_id===id);
      const wait=held('stop:'+(c?c.channel:''));if(wait)await wait;
      if(cap.refuse.stop)return json(cap.refuse.stop.status,{error:{code:cap.refuse.stop.code,message:'x'}});
      if(!c)return json(404,{error:{code:'capture_not_found',message:id}});
      cap.open=cap.open.filter(x=>x!==c);cap.stuck=cap.stuck.filter(x=>x.capture_id!==id);
      const done={...c,state:'complete',ended_at:iso(),stop_reason:'user'};
      cap.recent.unshift(done);
      return json(200,{capture:done});
    }
    return json(404,{error:{code:'not_found',message:u}});
  };
})()`;

/* La palette Bare Hands telle que son module la dessine, sans camera : sa
   feuille, ses trois boutons et sa legende ; et un bloc de 64x82 pour le
   controle de cycle de vie au-dessus (bouton 64 + 7 + legende 11). */
const MOUNT_PALETTE=`(()=>{
  const H=window.JarvisBarehandsHud;
  if(!H||!H.STYLE)return 'pas de module hud';
  if(!document.getElementById('bhTestStyle')){
    const style=document.createElement('style');style.id='bhTestStyle';
    style.textContent=H.STYLE;document.head.appendChild(style);
  }
  const host=document.getElementById(H.DOM.paletteId);
  if(!host)return 'pas d emplacement';
  host.textContent='';
  const strip=document.createElement('div');
  strip.className='bh-tools';strip.id=H.DOM.paletteStripId;strip.setAttribute('role','toolbar');
  for(let i=0;i<3;i+=1){
    const button=document.createElement('button');
    button.className='bh-tool';button.type='button';button.setAttribute('aria-label','outil '+i);
    button.setAttribute(H.DOM.toolAttribute,['pointer','pan','select'][i]);
    strip.appendChild(button);
  }
  host.appendChild(strip);
  const cap=document.createElement('span');cap.className='bh-tool-cap';cap.textContent='POINTEUR';
  host.appendChild(cap);
  const hud=document.getElementById(H.DOM.hostId);
  if(hud&&!hud.firstChild){
    const block=document.createElement('div');block.style.cssText='width:64px;height:82px';
    hud.appendChild(block);
  }
  return 'ok';
})()`;

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
  const box=el=>{
    if(!el)return null;
    const r=el.getBoundingClientRect();
    if(!r.width&&!r.height)return null;
    return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height};
  };
  const q=s=>document.querySelector(s);
  seen.rail=box(q('#captureRail'));
  seen.strip=box(q('#captureRailStrip'));
  seen.palette=box(q('#barehandsPalette'));
  seen.paletteStrip=box(q('#barehandsPaletteStrip'));
  seen.bhHud=box(q('#barehandsHud'));
  seen.modeBtn=box(q('#interactionModeButton'));
  seen.dock=box(q('.dock'));
  seen.pills=box(q('.bgpills'));
  seen.hint=box(q('.voicehint'));
  seen.toast=box(q('.toasts .toast'));
  seen.card=box(q('.pa-card'));
  seen.topbar=[...document.querySelectorAll('.topbar>*')].map(box).filter(Boolean);
  const rail=q('#captureRail');
  seen.slot=rail&&rail.getAttribute('data-capture-slot');
  seen.fits=rail&&rail.getAttribute('data-capture-fits');
  seen.z=rail&&getComputedStyle(rail).zIndex;
  seen.caption=(q('#captureRailCaption')||{}).textContent||null;
  seen.toolbar=q('#captureRailStrip')&&{role:q('#captureRailStrip').getAttribute('role'),
    label:q('#captureRailStrip').getAttribute('aria-label'),
    orientation:q('#captureRailStrip').getAttribute('aria-orientation')};
  seen.buttons={};
  for(const el of document.querySelectorAll('#captureRail [data-capture-control]')){
    const svg=el.querySelector('svg');
    seen.buttons[el.getAttribute('data-capture-control')]={
      tag:el.tagName,type:el.getAttribute('type'),
      state:el.getAttribute('data-capture-state'),pressed:el.getAttribute('aria-pressed'),
      disabled:el.getAttribute('aria-disabled'),label:el.getAttribute('aria-label'),title:el.getAttribute('title'),
      tabindex:el.getAttribute('tabindex'),describedby:el.getAttribute('aria-describedby'),
      time:(el.querySelector('.cr-time')||{}).textContent||'',
      badge:(el.querySelector('.cr-badge')||{}).textContent||'',
      badgeShown:getComputedStyle(el.querySelector('.cr-badge')).display!=='none',
      glyph:svg&&svg.getAttribute('data-cr-glyph'),
      stopShown:getComputedStyle(el.querySelector('.cr-stop')).display!=='none',
      stopBox:box(el.querySelector('.cr-stop')),
      stopOpacity:getComputedStyle(el.querySelector('.cr-stop')).opacity,
      detail:(el.querySelector('.cr-sr')||{}).textContent||'',
      detailId:(el.querySelector('.cr-sr')||{}).id||null,
      border:getComputedStyle(el).borderTopStyle,
      color:getComputedStyle(el).color,
      railAnimation:getComputedStyle(el,'::before').animationName,
      railContent:getComputedStyle(el,'::before').content,
      sweepShown:getComputedStyle(el.querySelector('.cr-wait')).display!=='none',
      sweepAnimation:getComputedStyle(el.querySelector('.cr-wait'),'::after').animationName,
      transition:getComputedStyle(el).transitionDuration,
      box:box(el),
    };
  }
  const note=q('#captureRailNote');
  seen.note=note&&{hidden:note.hidden,text:note.textContent.replace('×','').trim(),tone:note.getAttribute('data-cr-tone'),
    box:box(note)};
  seen.announce=(q('#captureRailAnnounce')||{}).textContent||'';
  const a=document.activeElement;
  seen.focus=a?{control:a.getAttribute&&a.getAttribute('data-capture-control'),cls:a.className||null,
    tool:a.getAttribute&&a.getAttribute('data-bh-tool')}:null;
  seen.bhToolsInRail=document.querySelectorAll('#captureRail [data-bh-tool]').length;
  seen.captureInPalette=document.querySelectorAll('#barehandsPalette [data-capture-control],#barehandsPaletteStrip [data-capture-control]').length;
  seen.calls=window.__cap?window.__cap.calls.filter(c=>c.method!=='GET').map(c=>c.method+' '+c.url+(c.body&&c.body!=='{}'?' '+c.body:'')):[];
  seen.statusCalls=window.__cap?window.__cap.calls.filter(c=>c.method==='GET').length:0;
  seen.api=window.JarvisCaptureRail?window.JarvisCaptureRail.view():null;
  seen.viewport={w:innerWidth,h:innerHeight};
  return seen;
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-cr-cdp-'));
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
  let id=0;const pending=new Map();const consoleLines=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):'').join(' ');
      if(text.startsWith('[capture]'))consoleLines.push(msg.params.type+' '+text);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});
    ws.send(JSON.stringify({id:mine,method,params}));
  });
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)
      throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const KEYS={Tab:{code:'Tab',keyCode:9},Enter:{code:'Enter',keyCode:13,text:'\r'},' ':{code:'Space',keyCode:32,text:' '},
    ArrowDown:{code:'ArrowDown',keyCode:40},ArrowUp:{code:'ArrowUp',keyCode:38},Home:{code:'Home',keyCode:36},
    End:{code:'End',keyCode:35},Escape:{code:'Escape',keyCode:27}};
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
  const out=[];
  for(const step of plan){
    await send('Emulation.setEmulatedMedia',{features:[
      ...(step.reducedMotion?[{name:'prefers-reduced-motion',value:'reduce'}]:[]),
      ...(step.forcedColors?[{name:'forced-colors',value:'active'}]:[]),
    ]});
    await send('Emulation.setDeviceMetricsOverride',
      {width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:'file:///'+PAGE.replace(/\\/g,'/')});
    /* Attendre la page **installée**, pas un délai : sous charge, 900 ms ne
       suffisaient pas toujours. */
    for(let i=0;i<200;i+=1){
      await sleep(50);
      const ready=await evaluate(`document.readyState==='complete'&&!!window.JarvisCaptureRail`).catch(()=>false);
      if(ready)break;
    }
    await sleep(300);
    if(step.mountPalette){
      const said=await evaluate(MOUNT_PALETTE);
      if(said!=='ok')throw new Error('palette : '+said);
    }
    if(step.toast){
      const said=await evaluate(MOUNT_TOAST);
      if(said!=='ok')throw new Error('infusion : '+said);
    }
    await sleep(300);
    const reads={};
    for(const action of step.actions||[]){
      if(action.eval!==undefined)await evaluate(action.eval);
      else if(action.wait!==undefined)await sleep(action.wait);
      else if(action.key!==undefined)await press(action.key);
      else if(action.click!==undefined)await click(action.click);
      else if(action.read!==undefined)reads[action.read]=await evaluate(READ);
      else if(action.axe!==undefined){
        /* axe-core n'est pas une dépendance du dépôt : le test le passe par
           `JARVIS_AXE_JS` quand il est présent, et se saute sinon. */
        await evaluate(readFileSync(action.file,'utf8'));
        reads[action.axe]=await evaluate(`axe.run(document.querySelector('#captureRail'),
          {resultTypes:['violations']}).then(r=>r.violations.map(v=>({id:v.id,impact:v.impact,
          nodes:v.nodes.map(n=>n.target.join(' '))})))`);
      }
    }
    if(!Object.keys(reads).length)reads.end=await evaluate(READ);
    out.push({reads,console:consoleLines.splice(0)});
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
