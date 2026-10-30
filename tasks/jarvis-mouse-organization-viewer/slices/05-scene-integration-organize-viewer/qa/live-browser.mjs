/* S05 independent live-app CDP probe. No fetch substitution. Mutation evidence
   comes from Network events and actual Core snapshots. Chrome cleanup is
   canonical/profile-scoped; never the user's runtime or browser. */
import {spawn} from 'node:child_process';
import {mkdtempSync,rmSync,writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {assertSafeTarget,disposeChromeOnExit,killChrome} from '../../../../../tests/unit/_cdp_profile.mjs';
const [,,url,binary,rawPlan]=process.argv,plan=JSON.parse(rawPlan);assertSafeTarget(url,null);
const profile=mkdtempSync(join(tmpdir(),'jarvis-s05-live-')),port=9700+Math.floor(Math.random()*200);
const chrome=spawn(binary,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
try{
  let target;
  for(let i=0;i<150;i++){try{target=(await(await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page');if(target)break}catch{/* Chrome startup: retry under bounded deadline. */}await sleep(50)}
  if(!target)throw new Error('Chrome CDP unavailable');
  const ws=new WebSocket(target.webSocketDebuggerUrl);await new Promise((ok,fail)=>{ws.onopen=ok;ws.onerror=fail});
  let sequence=0;const pending=new Map(),errors=[],logs=[],requests=[],responses=[];
  ws.onmessage=event=>{
    const message=JSON.parse(event.data);
    if(message.id&&pending.has(message.id)){const item=pending.get(message.id);pending.delete(message.id);clearTimeout(item.timer);message.error?item.fail(new Error(JSON.stringify(message.error))):item.ok(message.result)}
    else if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.exception?.description||message.params.exceptionDetails.text);
    else if(message.method==='Runtime.consoleAPICalled')logs.push({type:message.params.type,text:message.params.args.map(arg=>String(arg.value||arg.description||'')).join(' ')});
    else if(message.method==='Network.requestWillBeSent'){
      const req=message.params.request;if(req.url.startsWith(url.replace(/\/$/,'')))requests.push({id:message.params.requestId,method:req.method,path:new URL(req.url).pathname,body:req.postData||null});
    }else if(message.method==='Network.responseReceived')responses.push({id:message.params.requestId,status:message.params.response.status,path:new URL(message.params.response.url).pathname});
  };
  const send=(method,params={})=>new Promise((ok,fail)=>{const id=++sequence,timer=setTimeout(()=>{pending.delete(id);fail(new Error('CDP timeout: '+method))},15000);pending.set(id,{ok,fail,timer});ws.send(JSON.stringify({id,method,params}))});
  const evaluate=async expression=>{const out=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(out.exceptionDetails)throw new Error(out.exceptionDetails.exception?.description||out.exceptionDetails.text);return out.result.value};
  const point=selector=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)throw Error('Missing selector '+${JSON.stringify(selector)});el.scrollIntoView({block:'nearest',inline:'nearest'});const r=el.getBoundingClientRect();return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  const click=async action=>{const at=await point(action.click),button=action.button||'left',clickCount=action.count||1,modifiers=(action.ctrl?2:0)+(action.shift?8:0);await send('Input.dispatchMouseEvent',{type:'mouseMoved',...at});await send('Input.dispatchMouseEvent',{type:'mousePressed',...at,button,clickCount,modifiers});await send('Input.dispatchMouseEvent',{type:'mouseReleased',...at,button,clickCount,modifiers})};
  const key=async action=>{
    const codes={Tab:9,Escape:27,Enter:13,ArrowLeft:37,ArrowRight:39,ArrowUp:38,ArrowDown:40,Delete:46};
    const code=action.key.length===1?'Key'+action.key.toUpperCase():action.key,virtual=codes[action.key]||action.key.toUpperCase().charCodeAt(0),modifiers=(action.ctrl?2:0)+(action.shift?8:0)+(action.alt?1:0);
    for(const type of ['keyDown','keyUp'])await send('Input.dispatchKeyEvent',{type,key:action.key,code,windowsVirtualKeyCode:virtual,modifiers,...(type==='keyDown'&&action.key.length===1&&!action.ctrl&&!action.alt?{text:action.key}:{})});
  };
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');
  const view=plan.find(action=>action.view)?.view||{orbit:false,breathe:false};
  await send('Page.addScriptToEvaluateOnNewDocument',{source:"localStorage.setItem('jarvis.scene.view',"+JSON.stringify(JSON.stringify({version:1,view}))+" );localStorage.setItem('jarvis.ui.theme','cosmos');"});
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});await send('Page.navigate',{url});
  for(let i=0;i<160;i++){if(await evaluate("document.readyState==='complete'&&!!window.JarvisScene").catch(()=>false))break;await sleep(50)}
  const reads={};
  for(const action of plan){
    if(action.eval!==undefined)await evaluate(action.eval);
    else if(action.read)reads[action.read]=await evaluate(action.expr);
    else if(action.click)await click(action);
    else if(action.key)await key(action);
    else if(action.type){await click({click:action.type});await key({key:'a',ctrl:true});await send('Input.insertText',{text:action.text})}
    else if(action.wait)await sleep(action.wait);
    else if(action.until){const deadline=Date.now()+(action.ms||8000);let reached=false;while(Date.now()<deadline){if(await evaluate(action.until)){reached=true;break}await sleep(40)}if(!reached)throw new Error('Condition not reached: '+action.until)}
    else if(action.wheel){const at=await point(action.wheel);await send('Input.dispatchMouseEvent',{type:'mouseWheel',...at,deltaX:action.dx||0,deltaY:action.dy||0});await sleep(100)}
    else if(action.shot){const shot=await send('Page.captureScreenshot',{format:'png'});writeFileSync(action.shot,Buffer.from(shot.data,'base64'))}
    else if(action.size)await send('Emulation.setDeviceMetricsOverride',{width:action.size[0],height:action.size[1],deviceScaleFactor:1,mobile:false});
  }
  ws.close();process.stdout.write(JSON.stringify({reads,errors,logs,requests,responses}));
}finally{
  const exited=new Promise(resolve=>chrome.once('exit',resolve));killChrome(chrome,profile);await Promise.race([exited,sleep(4000)]);
  try{rmSync(profile,{recursive:true,force:true,maxRetries:8,retryDelay:200})}catch{/* Locked disposable profile only; no wider cleanup. */}
}
