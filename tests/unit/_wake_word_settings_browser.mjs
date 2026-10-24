/* Harnais CDP pour `test_wake_word_settings_browser.py` (Slice 07 de jarvis-wake-word).

   Chrome sans tete contre un VRAI Control Center (instance isolee, runtime
   temporaire, port libre) : la page fait ses vrais appels, `/api/wake-word`
   ecrit le vrai fichier de reglages. Les entrees sont de VRAIS evenements
   (CDP `Input.*`), pas des `click()` JavaScript : c'est le seul niveau ou
   « le clavier atteint ce que la souris atteint » veut dire quelque chose.
   Aucun micro n'est ouvert : la page n'en demande jamais un ici.

   Usage : node _wake_word_settings_browser.mjs <url> <chrome.exe> <planJSON>
   Plan : une liste d'etapes `{width,height,deviceScaleFactor,reducedMotion,forcedColors,stubs,actions:[...]}`.
   `stubs` (fixtures deterministes, refonte-ui-settings Slice 01) : `[{path,method?,status?,json}]` ; une requete
   de la page dont le chemin (sans requete) et la methode correspondent recoit `json` sans toucher le serveur,
   les autres passent. Aide Python : `tests/unit/settings_visual.py`.
   Chaque action peut porter un `id` repris dans sa reponse.
   Sortie : `{"steps":[{"actions":[...]}],"requests":[...],"console":[...]}`.

   Actions :
     {"a":"eval","expr":"..."}                          -> {value}
     {"a":"wait","expr":"...","timeoutMs":4000}         -> {ok,ms}
     {"a":"click","selector":"..."}                     (vrai clic souris, au centre)
     {"a":"key","key":"Tab","shift":false,"ctrl":false} (vraie frappe clavier) -> {focused}
     {"a":"type","selector":"...","text":"1.5"}         (selectionne puis insere le texte)
     {"a":"shot","path":"...png"}                       (`.jpg` : JPEG qualite 82, plus leger pour les preuves)
     {"a":"script","path":"...js","then":"expr"}        (evalue un fichier de fixture puis `then` ; plan court)
     {"a":"freeze"}                                     (animations a leur etat final, transitions et caret coupes)
     {"a":"theme","id":"cosmos"}                        (API de theme de la page, sans persister) */
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit,killChrome,assertSafeTarget} from './_cdp_profile.mjs';

const [,,URL_,CHROME,PLAN]=process.argv;
/* Jamais le JARVIS vivant : ni ses ports, ni son dossier d'exécution (QA S09, `_cdp_profile.mjs`). */
assertSafeTarget(URL_,null);
const plan=JSON.parse(PLAN);
const profile=mkdtempSync(join(tmpdir(),'jarvis-ww-cdp-'));
const port=9800+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions',
  '--hide-scrollbars','--mute-audio','about:blank',
],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const requests=[];
let stubs=[],fetching=false;
const consoleErrors=[];

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
      return;
    }
    if(msg.method==='Network.requestWillBeSent'){
      const r=msg.params.request;
      requests.push({method:r.method,path:new URL(r.url).pathname,body:r.postData||null});
    }else if(msg.method==='Fetch.requestPaused'){
      fulfil(msg.params).catch(error=>consoleErrors.push('stub: '+error.message));
    }else if(msg.method==='Runtime.exceptionThrown'){
      const d=msg.params.exceptionDetails;
      consoleErrors.push('exception: '+(d.exception&&d.exception.description||d.text));
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
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');
  /* Une requete arretee par `Fetch` : la fixture du plan si elle correspond, sinon la requete continue. */
  async function fulfil({requestId,request}){
    const path=new URL(request.url).pathname;
    const hit=stubs.find(s=>s.path===path&&(!s.method||s.method.toUpperCase()===request.method));
    if(!hit)return send('Fetch.continueRequest',{requestId});
    return send('Fetch.fulfillRequest',{requestId,responseCode:hit.status||200,
      responseHeaders:[{name:'Content-Type',value:'application/json; charset=utf-8'}],
      body:Buffer.from(JSON.stringify(hit.json===undefined?null:hit.json)).toString('base64')});
  }

  const steps=[];
  for(const step of plan){
    await send('Emulation.setEmulatedMedia',{features:[
      ...(step.reducedMotion?[{name:'prefers-reduced-motion',value:'reduce'}]:[]),
      ...(step.forcedColors?[{name:'forced-colors',value:'active'}]:[])]});
    await send('Emulation.setDeviceMetricsOverride',
      {width:step.width||1440,height:step.height||900,deviceScaleFactor:step.deviceScaleFactor||1,mobile:false});
    stubs=Array.isArray(step.stubs)?step.stubs:[];
    if(stubs.length){await send('Fetch.enable',{patterns:stubs.map(s=>({urlPattern:'*'+s.path+'*',requestStage:'Request'}))});fetching=true}
    else if(fetching){await send('Fetch.disable');fetching=false}
    await send('Page.navigate',{url:URL_});
    await sleep(step.settleMs||1100);
    const out={actions:[]};
    for(const action of step.actions||[])out.actions.push({...await act(action),id:action.id});
    steps.push(out);
  }
  ws.close();
  process.stdout.write(JSON.stringify({steps,requests,console:consoleErrors}));

  async function act(action){
    switch(action.a){
      case 'eval':
        return {a:'eval',value:await evaluate(action.expr)};
      case 'wait':{
        const started=Date.now();
        for(;;){
          let value=null;
          try{value=await evaluate(action.expr)}catch(_){/* page en cours de rendu */}
          if(value)return {a:'wait',ok:true,ms:Date.now()-started};
          if(Date.now()-started>(action.timeoutMs||4000))return {a:'wait',ok:false,ms:Date.now()-started,expr:action.expr};
          await sleep(30);
        }
      }
      case 'click':{
        const box=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(action.selector)});
          if(!el)return null;el.scrollIntoView({block:'center'});
          const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
        if(!box)return {a:'click',missing:action.selector};
        for(const type of ['mouseMoved','mousePressed','mouseReleased'])
          await send('Input.dispatchMouseEvent',{type,x:box.x,y:box.y,button:'left',clickCount:1});
        await sleep(80);
        return {a:'click'};
      }
      case 'key':{
        const codes={ArrowDown:40,ArrowUp:38,ArrowRight:39,ArrowLeft:37,Escape:27,Enter:13,Tab:9,Home:36,End:35,Delete:46,' ':32,F10:121,F11:122};
        const base={key:action.key,code:action.key===' '?'Space':action.key,
          windowsVirtualKeyCode:codes[action.key]||0,modifiers:(action.shift?8:0)|(action.ctrl?2:0)};
        await send('Input.dispatchKeyEvent',{type:'keyDown',...base,
          ...(action.key==='Enter'?{text:'\r'}:action.key===' '?{text:' '}:{})});
        await send('Input.dispatchKeyEvent',{type:'keyUp',...base});
        await sleep(80);
        return {a:'key',focused:await evaluate(`(()=>{const e=document.activeElement;
          return e?(e.id||e.getAttribute('data-ww-save')!==null&&'ww_save'||e.tagName):null})()`)};
      }
      case 'type':{
        await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(action.selector)});el.focus();
          if(el.select)el.select()})()`);
        await send('Input.insertText',{text:String(action.text)});
        await sleep(60);
        return {a:'type'};
      }
      case 'theme':
        return {a:'theme',value:await evaluate(`window.JarvisThemeAPI.activate(${JSON.stringify(action.id)},{persist:false})`)};
      case 'script':
        return {a:'script',value:await evaluate(readFileSync(action.path,'utf8')+';\n'+(action.then||'undefined'))};
      case 'freeze':
        return {a:'freeze',value:await evaluate(`(()=>{const s=document.createElement('style');s.dataset.visualFreeze='';
          s.textContent='*,*::before,*::after{animation-duration:0s!important;animation-delay:0s!important;'
            +'transition:none!important;caret-color:transparent!important;scroll-behavior:auto!important}';
          document.head.append(s);return true})()`)};
      case 'shot':{
        const jpeg=/\.jpe?g$/i.test(action.path);
        const {data}=await send('Page.captureScreenshot',jpeg?{format:'jpeg',quality:82}:{format:'png'});
        writeFileSync(action.path,Buffer.from(data,'base64'));
        return {a:'shot',path:action.path};
      }
      default:
        throw new Error('action inconnue : '+action.a);
    }
  }
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
