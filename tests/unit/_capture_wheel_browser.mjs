/* Harnais CDP pour `test_capture_wheel_browser.py` (orbital-ui Slice 04).

   Chrome sans tête sur un VRAI Control Center (URL http) relié à un vrai Core
   aux sources de capture factices (`CaptureStack`) : aucun double dans la
   page, aucune vraie capture d'écran ni de micro. Le harnais pilote de vrais
   événements d'entrée (`Input.*` : clic gauche, clic droit — un vrai
   `contextmenu` —, frappes avec Maj) et relit ce que la cascade produit.

   Usage : node _capture_wheel_browser.mjs <http://127.0.0.1:port/> <chrome.exe> <stepJSON|@fichier>
   Étape : {width, height, reducedMotion?, forcedColors?, actions: [...]}
   Action : {eval}, {value, expr}, {read: nom} (relevé complet, voir READ),
            {wait: ms}, {until: js, ms, name}, {shot: chemin.png},
            {click: sélecteur}, {right: sélecteur} (clic droit), {move: sélecteur},
            {key, shift?}, {focus: sélecteur}, {reload: true}, {resize: {width, height}},
            {open: true} (nouvel onglet sur la même page, devient l'onglet courant),
            {use: index} (change d'onglet), {axe: nom, file, selector}.
   Sortie : {reads, console, errors}. */
import {spawn, execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit,killChrome,assertSafeTarget} from './_cdp_profile.mjs';

const [,,PAGE,CHROME,STEP]=process.argv;
/* Jamais le JARVIS vivant : ni ses ports, ni son dossier d'exécution (QA S09, `_cdp_profile.mjs`). */
assertSafeTarget(PAGE,null);
const step=JSON.parse(STEP.startsWith('@')?readFileSync(STEP.slice(1),'utf-8'):STEP);
const profile=mkdtempSync(join(tmpdir(),'jarvis-capture-wheel-cdp-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars',
  '--use-fake-ui-for-media-stream','--use-fake-device-for-media-stream','about:blank',
],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

/* Le relevé : roue, secteurs, sous-arc, indicateurs, note, modèle publié,
   commandes voisines (boîtes), focus. */
const READ=`(()=>{
  const q=s=>document.querySelector(s);
  const box=el=>{if(!el)return null;const r=el.getBoundingClientRect();
    return r.width||r.height?{l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}:null};
  const shown=el=>!!el&&!el.closest('[hidden]')&&getComputedStyle(el).display!=='none'&&getComputedStyle(el).visibility!=='hidden'&&!!box(el);
  const W=window.JarvisToolWheel,C=window.JarvisCaptureRail;
  const host=q('#toolWheel'),ind=q('#recIndicators');
  const wedges={};
  for(const b of document.querySelectorAll('#toolWheel .tw-wedge')){
    const badge=b.querySelector('.tw-badge');
    wedges[b.dataset.twSlot]={role:b.getAttribute('role'),checked:b.getAttribute('aria-checked'),label:b.getAttribute('aria-label'),
      disabled:b.getAttribute('aria-disabled'),badge:badge&&!badge.hidden?(badge.getAttribute('data-tw-tone')+':'+badge.textContent):null,
      dotBorder:getComputedStyle(b.querySelector('.tw-dot')).borderTopColor};
  }
  /* Refonte S03 : Vidéo, Capture d'écran et Audio sont des entrées de l'arbre de Capture ; ce qu'en dit
     chaque canal (relu sur JarvisCaptureViews) se lit ici comme avant, sous leur ancien nom de secteur. */
  const V=window.JarvisCaptureViews;
  const names={video:'Vidéo',screenshot:'Capture d’écran',audio:'Audio'};
  const channels=V&&typeof V.channels==='function'?V.channels():{};
  for(const [slot,label] of Object.entries(names)){
    const st=channels[slot]||null,checked=st&&typeof st.checked==='boolean'?st.checked:(slot==='screenshot'?null:false);
    wedges[slot]={role:checked===null?'menuitem':'menuitemcheckbox',checked:checked===null?null:String(checked),
      label:st&&st.text?label+' — '+st.text:label,disabled:null,
      badge:st&&(st.tone==='error'||st.tone==='unknown')?st.tone+':'+(st.tone==='error'?'!':'?'):st&&st.tone==='wait'?'wait:':null,
      dotBorder:null};
  }
  const items=[...document.querySelectorAll('#toolWheel .tw-item')].map(b=>({id:b.dataset.twItem||null,text:b.textContent,
    label:b.getAttribute('aria-label')||b.textContent,role:b.getAttribute('role'),disabled:b.getAttribute('aria-disabled'),
    tone:b.getAttribute('data-tw-tone'),tabindex:b.getAttribute('tabindex'),box:box(b)}));
  const chips=[...document.querySelectorAll('#recIndicators .ri-chip')].map(el=>{
    const p=s=>el.querySelector(s);const cs=getComputedStyle(el);
    const describedby=el.getAttribute('aria-describedby');
    return {key:el.dataset.riKey,channel:el.dataset.riChannel,state:el.dataset.riState,label:el.getAttribute('aria-label'),
      title:el.title,disabled:el.getAttribute('aria-disabled'),describedby,
      detail:describedby?(document.getElementById(describedby)||{}).textContent:null,
      tag:shown(p('.ri-tag'))?p('.ri-tag').textContent:null,time:shown(p('.ri-time'))?p('.ri-time').textContent:null,
      dev:shown(p('.ri-dev'))?p('.ri-dev').textContent:null,mark:shown(p('.ri-mark'))?p('.ri-mark').textContent:null,
      stopShown:shown(p('.ri-stop')),waitShown:shown(p('.ri-wait')),
      glyph:(p('svg')||{getAttribute:()=>null}).getAttribute('data-ri-glyph'),dot:shown(p('.ri-dot')),
      dotAnimation:p('.ri-dot')?getComputedStyle(p('.ri-dot')).animationName:null,
      waitAnimation:p('.ri-wait')?getComputedStyle(p('.ri-wait'),'::after').animationName:null,
      border:cs.borderTopStyle,borderWidth:cs.borderTopWidth,color:cs.color,box:box(el)};
  });
  const note=q('#recIndicatorsNote');
  const view=C?C.view():null;
  const ae=document.activeElement;
  const anchor=q('#toolWheel .tw-anchor');
  return {
    open:W?W.isOpen():null,wheelHidden:host?host.hidden:null,z:host?getComputedStyle(host).zIndex:null,
    anchor:anchor?{label:anchor.getAttribute('aria-label'),tone:anchor.getAttribute('data-tw-tone'),box:box(anchor)}:null,
    wedges,items,subLabel:(q('#toolWheel .tw-sub')||{getAttribute:()=>null}).getAttribute('aria-label'),
    indicators:ind?{hidden:ind.hidden,z:getComputedStyle(ind).zIndex,box:shown(ind)?box(ind):null,role:ind.getAttribute('role'),
      label:ind.getAttribute('aria-label')}:null,
    chips,note:note?{hidden:note.hidden,text:note.firstChild?note.firstChild.textContent:'',tone:note.getAttribute('data-ri-tone'),
      box:shown(note)?box(note):null}:null,
    live:(q('#recIndicatorsLive')||{}).textContent||'',
    view:view?{reachable:view.reachable,caption:view.caption,
      controls:Object.fromEntries(Object.entries(view.controls).map(([k,c])=>[k,{state:c.state,action:c.action,pressed:c.pressed,
        captureId:c.captureId,timer:c.timer,captures:(c.captures||[]).map(x=>({id:x.captureId,device:x.device,state:x.state,timer:x.timer}))}])),
      shot:view.shot?{artifact:view.shot.artifact,capture:view.shot.capture&&view.shot.capture.capture_id,device:view.shot.device}:null}:null,
    boxes:{boardCard:box(q('#boardsButton')),chat:box(q('#chatTab')),
      pills:shown(q('#bgPills'))?box(q('#bgPills')):null,dock:box(q('.dock')),tray:shown(q('#boardDropTray'))?box(q('#boardDropTray')):null,
      scene:shown(q('#sceneLayer>.sc-status'))?box(q('#sceneLayer>.sc-status')):null},
    bareHands:{hud:shown(q('#barehandsHud')),palette:shown(q('#barehandsPalette'))},
    oldRail:!!q('#captureRail'),
    bhToolsInWheel:document.querySelectorAll('#toolWheel [data-bh-tool],#recIndicators [data-bh-tool]').length,
    focus:ae?{slot:ae.dataset&&ae.dataset.twSlot||null,item:ae.classList&&ae.classList.contains('tw-item')?ae.textContent:null,
      chip:ae.dataset&&ae.dataset.riKey||null,anchor:!!(ae.classList&&ae.classList.contains('tw-anchor')),tag:ae.tagName}:null,
    overflowX:document.documentElement.scrollWidth>innerWidth,vw:innerWidth,vh:innerHeight,
  };
})()`;

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const consoleLines=[],errors=[];
  const tabs=[];
  let tab=null;
  async function connect(wsUrl){
    const ws=new WebSocket(wsUrl);
    await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
    let id=0;const pending=new Map();const index=tabs.length;
    ws.onmessage=event=>{
      const msg=JSON.parse(event.data);
      if(msg.id&&pending.has(msg.id)){
        const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
        msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
      }else if(msg.method==='Runtime.consoleAPICalled'){
        const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):(a.description||'')).join(' ');
        if(text.startsWith('[capture]')||text.startsWith('[tool_wheel]')||msg.params.type==='error')
          consoleLines.push(`${index} ${msg.params.type} ${text}`);
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
    const t={ws,send,evaluate};
    await send('Page.enable');await send('Runtime.enable');
    await send('Emulation.setEmulatedMedia',{features:[
      ...(step.reducedMotion?[{name:'prefers-reduced-motion',value:'reduce'}]:[]),
      ...(step.forcedColors?[{name:'forced-colors',value:'active'}]:[]),
    ]});
    await send('Emulation.setDeviceMetricsOverride',{width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
    tabs.push(t);
    return t;
  }
  const ready=async()=>{
    for(let i=0;i<200;i+=1){
      await sleep(50);
      if(await tab.evaluate(`document.readyState==='complete'&&!!window.JarvisCaptureViews&&!!window.JarvisToolWheel
        &&!document.getElementById('toolWheel').hidden`).catch(()=>false))return true;
    }
    return false;
  };
  const point=async(where,corner)=>{
    const at=await tab.evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(where)});
      if(!el)return null;const r=el.getBoundingClientRect();return r.width?{x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)}:null})()`);
    if(!at)throw new Error('cible introuvable ou cachée '+where);
    return at;
  };
  const mouse=async(at,button)=>{
    await tab.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x,y:at.y,button:'none'});
    await sleep(30);
    await tab.send('Input.dispatchMouseEvent',{type:'mousePressed',x:at.x,y:at.y,button,buttons:button==='right'?2:1,clickCount:1});
    await tab.send('Input.dispatchMouseEvent',{type:'mouseReleased',x:at.x,y:at.y,button,buttons:0,clickCount:1});
  };
  const CODES={ArrowDown:40,ArrowUp:38,ArrowLeft:37,ArrowRight:39,Escape:27,Enter:13,Tab:9,Home:36,End:35,' ':32,
    F10:121,ContextMenu:93};

  tab=await connect(target.webSocketDebuggerUrl);
  await tab.send('Page.navigate',{url:PAGE});
  const reads={ready:await ready()};
  for(const action of step.actions){
    try{
      if(action.eval!==undefined)await tab.evaluate(action.eval);
      else if(action.value!==undefined)reads[action.value]=await tab.evaluate(action.expr);
      else if(action.read!==undefined)reads[action.read]=await tab.evaluate(READ);
      else if(action.wait!==undefined)await sleep(action.wait);
      else if(action.until!==undefined){
        const end=Date.now()+(action.ms||8000);let ok=false;
        while(Date.now()<end){ok=!!(await tab.evaluate(action.until).catch(()=>false));if(ok)break;await sleep(60)}
        reads['until:'+(action.name||action.until)]=ok;
      }else if(action.shot!==undefined){
        const shot=await tab.send('Page.captureScreenshot',{format:'png'});
        writeFileSync(action.shot,Buffer.from(shot.data,'base64'));
      }else if(action.click!==undefined)await mouse(await point(action.click),'left');
      else if(action.right!==undefined)await mouse(await point(action.right),'right');
      else if(action.move!==undefined){
        const at=await point(action.move);
        await tab.send('Input.dispatchMouseEvent',{type:'mouseMoved',x:at.x,y:at.y,button:'none'});
      }else if(action.key!==undefined){
        const base={key:action.key,code:action.key===' '?'Space':action.key,windowsVirtualKeyCode:CODES[action.key]||0,
          modifiers:action.shift?8:0};
        await tab.send('Input.dispatchKeyEvent',{type:'keyDown',...base,
          ...(action.key==='Enter'?{text:'\r'}:action.key===' '?{text:' '}:{})});
        await tab.send('Input.dispatchKeyEvent',{type:'keyUp',...base});
        await sleep(60);
      }else if(action.focus!==undefined){
        await tab.evaluate(`document.querySelector(${JSON.stringify(action.focus)}).focus()`);
      }else if(action.reload!==undefined){
        await tab.send('Page.reload',{ignoreCache:true});
        reads['reloaded:'+tabs.indexOf(tab)]=await ready();
      }else if(action.resize!==undefined){
        await tab.send('Emulation.setDeviceMetricsOverride',{width:action.resize.width,height:action.resize.height,
          deviceScaleFactor:1,mobile:false});
        await sleep(300);
      }else if(action.open!==undefined){
        const made=await (await fetch(`http://127.0.0.1:${port}/json/new?about:blank`,{method:'PUT'})).json();
        tab=await connect(made.webSocketDebuggerUrl);
        await tab.send('Page.navigate',{url:PAGE});
        reads['opened:'+(tabs.length-1)]=await ready();
      }else if(action.use!==undefined){
        tab=tabs[action.use];
        await tab.send('Page.bringToFront');
      }else if(action.axe!==undefined){
        await tab.evaluate(readFileSync(action.file,'utf8'));
        reads['axe:'+action.axe]=await tab.evaluate(`axe.run(document.querySelector(${JSON.stringify(action.selector)}),
          {resultTypes:['violations']}).then(r=>r.violations.map(v=>({id:v.id,impact:v.impact,
          nodes:v.nodes.map(n=>n.target.join(' ')),html:v.nodes.map(n=>n.html.slice(0,160))})))`);
      }
    }catch(error){reads.failed={action,error:String(error.message||error).slice(0,400)};break}
  }
  for(const t of tabs)t.ws.close();
  process.stdout.write(JSON.stringify({reads,console:consoleLines,errors}));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));
  killTree(chrome);
  await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){/* Windows tient le dossier */}
}

/* Chrome de CE harnais seulement (profil jetable) : jamais `taskkill /PID … /T` sur un PID mémorisé (QA S09). */
function killTree(child){killChrome(child,profile)}

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
