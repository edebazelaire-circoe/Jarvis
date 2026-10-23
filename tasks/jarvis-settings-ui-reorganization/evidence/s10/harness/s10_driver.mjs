/* Harnais CDP de la QA S10 (bac à sable seulement). Dérivé de tests/unit/_wake_word_settings_browser.mjs :
   - zoom réel : `zoom` (1 ou 1.25) -> largeur CSS = width/zoom, deviceScaleFactor = zoom ;
   - script injecté avant la page (`init`), pour instrumenter minuteurs/écoutes/fetch ;
   - touches supplémentaires (lettres, modificateurs alt/ctrl/shift) ;
   - `shot` en PNG.
   Usage : node s10_driver.mjs <url> <chrome.exe> <plan.json> <out.json> */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit,assertSafeTarget} from 'file:///C:/Projects/jarvis/setui/tests/unit/_cdp_profile.mjs';

const [,,URL_,CHROME,PLAN_FILE,OUT]=process.argv;
assertSafeTarget(URL_,null);
const plan=JSON.parse(readFileSync(PLAN_FILE,'utf8'));
const profile=mkdtempSync(join(tmpdir(),'jarvis-s10-cdp-'));
const port=9300+Math.floor(Math.random()*400);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions',
  '--hide-scrollbars','--mute-audio','about:blank',
],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);
const FOCUSED=`(()=>{const e=document.activeElement;if(!e)return null;const sh=document.getElementById('settingsShell');
  const cs=getComputedStyle(e);return {id:e.id||null,tag:e.tagName,text:(e.textContent||'').trim().slice(0,40),
  inShell:!!sh&&sh.contains(e),outline:cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>=1,role:e.getAttribute('role'),
  ds:Object.keys(e.dataset||{}).slice(0,3).join(',')}})()`;
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const requests=[],consoleMsgs=[],exceptions=[];

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);return;
    }
    if(msg.method==='Network.requestWillBeSent'){
      const r=msg.params.request;
      requests.push({method:r.method,path:new URL(r.url).pathname,body:r.postData?r.postData.slice(0,400):null});
    }else if(msg.method==='Runtime.exceptionThrown'){
      const d=msg.params.exceptionDetails;exceptions.push(d.exception&&d.exception.description||d.text);
    }else if(msg.method==='Runtime.consoleAPICalled'){
      const p=msg.params;if(['error','warning','warn'].includes(p.type))
        consoleMsgs.push({type:p.type,text:p.args.map(a=>a.value!==undefined?String(a.value):(a.description||a.type)).join(' ').slice(0,300)});
    }else if(msg.method==='Log.entryAdded'){
      const e=msg.params.entry;if(e.level==='error'||e.level==='warning')consoleMsgs.push({type:'log.'+e.level,text:(e.text+' '+(e.url||'')).slice(0,300)});
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}))});
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');await send('Log.enable');
  if(plan.init)await send('Page.addScriptToEvaluateOnNewDocument',{source:plan.init});
  const steps=[];
  for(const step of plan.steps){
    const zoom=step.zoom||1,W=step.width||1440,H=step.height||900;
    await send('Emulation.setEmulatedMedia',{features:[
      {name:'prefers-reduced-motion',value:step.reducedMotion?'reduce':'no-preference'},
      {name:'forced-colors',value:step.forcedColors?'active':'none'}]});
    await send('Emulation.setDeviceMetricsOverride',{width:Math.round(W/zoom),height:Math.round(H/zoom),deviceScaleFactor:zoom,mobile:false});
    if(!step.noNavigate){await send('Page.navigate',{url:URL_});await sleep(step.settleMs||1500)}
    const out={name:step.name,actions:[]};
    for(const action of step.actions||[]){
      try{out.actions.push({...await act(action),id:action.id})}
      catch(e){out.actions.push({a:action.a,id:action.id,error:String(e.message||e).slice(0,400)})}
    }
    steps.push(out);
  }
  ws.close();
  writeFileSync(OUT,JSON.stringify({steps,requests,console:consoleMsgs,exceptions},null,1));

  async function act(action){
    switch(action.a){
      case 'eval':return {a:'eval',value:await evaluate(action.expr)};
      case 'sleep':await sleep(action.ms||200);return {a:'sleep'};
      case 'wait':{
        const started=Date.now();
        for(;;){
          let value=null;try{value=await evaluate(action.expr)}catch(_){}
          if(value)return {a:'wait',ok:true,ms:Date.now()-started};
          if(Date.now()-started>(action.timeoutMs||6000))return {a:'wait',ok:false,expr:action.expr};
          await sleep(40);
        }
      }
      case 'click':{
        const box=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(action.selector)});
          if(!el)return null;el.scrollIntoView({block:'center'});const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
        if(!box)return {a:'click',missing:action.selector};
        for(const type of ['mouseMoved','mousePressed','mouseReleased'])
          await send('Input.dispatchMouseEvent',{type,x:box.x,y:box.y,button:'left',clickCount:1});
        await sleep(120);return {a:'click'};
      }
      case 'key':{
        const k=action.key;
        const codes={ArrowDown:40,ArrowUp:38,ArrowRight:39,ArrowLeft:37,Escape:27,Enter:13,Tab:9,Home:36,End:35,Delete:46,' ':32,F9:120,F10:121};
        const single=k.length===1;
        const vk=codes[k]||(single?k.toUpperCase().charCodeAt(0):0);
        const code=k===' '?'Space':single&&/[a-z]/i.test(k)?'Key'+k.toUpperCase():k;
        const mods=(action.alt?1:0)|(action.ctrl?2:0)|(action.meta?4:0)|(action.shift?8:0);
        const base={key:k,code,windowsVirtualKeyCode:vk,nativeVirtualKeyCode:vk,modifiers:mods};
        const text=k==='Enter'?'\r':single&&!action.ctrl&&!action.alt?k:undefined;
        await send('Input.dispatchKeyEvent',{type:text?'keyDown':'rawKeyDown',...base,...(text?{text,unmodifiedText:text}:{})});
        await send('Input.dispatchKeyEvent',{type:'keyUp',...base});
        await sleep(action.after||120);
        return {a:'key',key:k,focused:await evaluate(FOCUSED)};
      }
      case 'keyUntil':{
        /* Presse `key` jusqu'à ce que `expr` soit vrai (max `max`), relève chaque focus traversé. */
        const trail=[];
        for(let i=0;i<(action.max||40);i++){
          let done=false;try{done=await evaluate(action.expr)}catch(_){}
          if(done)return {a:'keyUntil',ok:true,presses:i,trail};
          const r=await act({a:'key',key:action.key,shift:action.shift,ctrl:action.ctrl,alt:action.alt,after:action.after});
          trail.push(r.focused);
        }
        let done=false;try{done=await evaluate(action.expr)}catch(_){}
        return {a:'keyUntil',ok:!!done,presses:action.max||40,trail};
      }
      case 'shot':{
        const {data}=await send('Page.captureScreenshot',{format:'png'});
        writeFileSync(action.path,Buffer.from(data,'base64'));return {a:'shot',path:action.path};
      }
      default:throw new Error('action inconnue : '+action.a);
    }
  }
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){}
}

async function poll(url){
  for(let i=0;i<120;i+=1){
    try{const list=await (await fetch(url)).json();const page=list.find(t=>t.type==='page');if(page&&page.webSocketDebuggerUrl)return page}catch(_){}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
