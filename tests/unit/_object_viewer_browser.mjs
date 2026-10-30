/* Focused real Chromium input/visual harness. Uses canonical profile-scoped cleanup;
   never taskkill /T or the user's browser/runtime. */
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {assertSafeTarget,disposeChromeOnExit,killChrome} from './_cdp_profile.mjs';
const [,,url,binary,rawPlan]=process.argv;assertSafeTarget(url,null);
const plan=JSON.parse(rawPlan),profile=mkdtempSync(join(tmpdir(),'jarvis-viewer-cdp-')),port=9600+Math.floor(Math.random()*300);
const chrome=spawn(binary,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
try{
  let target;
  for(let i=0;i<150;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');if(target)break}catch{}await sleep(50)}
  if(!target)throw new Error('Chrome CDP indisponible');
  const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((ok,fail)=>{ws.onopen=ok;ws.onerror=fail});
  let id=0;const pending=new Map(),errors=[],logs=[];
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id&&pending.has(message.id)){const item=pending.get(message.id);pending.delete(message.id);message.error?item.fail(new Error(JSON.stringify(message.error))):item.ok(message.result)}
    else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.exception?.description||message.params.exceptionDetails.text);
    else if(message.method==='Runtime.consoleAPICalled')logs.push({type:message.params.type,text:message.params.args.map(arg=>String(arg.value||arg.description||'')).join(' ')});
  };
  const send=(method,params={})=>new Promise((ok,fail)=>{const number=++id;pending.set(number,{ok,fail});ws.send(JSON.stringify({id:number,method,params}))});
  const evaluate=async expression=>{const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw new Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value};
  const point=selector=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)throw Error('Élément absent');const r=el.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  const click=async selector=>{const at=await point(selector);for(const type of ['mouseMoved','mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,...at,button:'left',clickCount:1})};
  const key=async action=>{
    const names={Tab:9,Escape:27,Enter:13,ArrowLeft:37,ArrowRight:39,ArrowUp:38,ArrowDown:40};
    const code=action.key.length===1?'Key'+action.key.toUpperCase():action.key,keyCode=names[action.key]||action.key.toUpperCase().charCodeAt(0),modifiers=action.shift?8:0;
    for(const type of ['keyDown','keyUp'])await send('Input.dispatchKeyEvent',{type,key:action.key,code,windowsVirtualKeyCode:keyCode,modifiers,
      ...(type==='keyDown'&&action.key.length===1?{text:action.key}:{})});
  };
  await send('Page.enable');await send('Runtime.enable');await send('Emulation.setDeviceMetricsOverride',{width:1280,height:800,deviceScaleFactor:1,mobile:false});await send('Page.navigate',{url});
  let ready=false;
  for(let i=0;i<100;i++){if(await evaluate("document.readyState==='complete'&&!!window.viewer").catch(()=>false)){ready=true;break}await sleep(50)}
  if(!ready)throw new Error('Viewer non chargé : '+JSON.stringify(errors));
  const reads={};
  for(const action of plan){
    if(action.eval!==undefined)await evaluate(action.eval);
    else if(action.read)reads[action.read]=await evaluate(action.expr);
    else if(action.click)await click(action.click);
    else if(action.key)await key(action);
    else if(action.size)await send('Emulation.setDeviceMetricsOverride',{width:action.size[0],height:action.size[1],deviceScaleFactor:1,mobile:false});
    else if(action.media)await send('Emulation.setEmulatedMedia',{features:[{name:'prefers-reduced-motion',value:action.media}]});
    else if(action.shot){await sleep(100);const shot=await send('Page.captureScreenshot',{format:'png'});writeFileSync(action.shot,Buffer.from(shot.data,'base64'))}
    else if(action.wait)await sleep(action.wait);
    else if(action.until){const deadline=Date.now()+(action.ms||5000);let ok=false;while(Date.now()<deadline){if(await evaluate(action.until)){ok=true;break}await sleep(30)}if(!ok)throw new Error('Condition non atteinte : '+action.until)}
    else if(action.drag){const at=await point(action.drag),to={x:at.x+(action.dx||0),y:at.y+(action.dy||0)};await send('Input.dispatchMouseEvent',{type:'mousePressed',...at,button:'left',clickCount:1});await send('Input.dispatchMouseEvent',{type:'mouseMoved',...to,button:'left',buttons:1});await send('Input.dispatchMouseEvent',{type:'mouseReleased',...to,button:'left',clickCount:1})}
    else if(action.wheel){const at=await point(action.wheel);await send('Input.dispatchMouseEvent',{type:'mouseWheel',...at,deltaX:action.dx||0,deltaY:action.dy||0});await sleep(100)}
  }
  ws.close();process.stdout.write(JSON.stringify({reads,errors,logs}));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));killChrome(chrome,profile);await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:8,retryDelay:200})}catch{/* A locked disposable profile may remain; no broader deletion. */}
}
