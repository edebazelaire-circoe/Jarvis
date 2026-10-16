import {spawn, execFileSync} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

export const sleep=ms=>new Promise(r=>setTimeout(r,ms));
import {existsSync} from 'node:fs';
const CHROME=['C:/Program Files/Google/Chrome/Application/chrome.exe','C:/Program Files (x86)/Google/Chrome/Application/chrome.exe'].find(p=>existsSync(p));

export async function launch(){
  const profile=mkdtempSync(join(tmpdir(),'s9-cdp-'));
  const port=9800+Math.floor(Math.random()*400);
  const proc=spawn(CHROME,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
    '--no-first-run','--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
  const base=`http://127.0.0.1:${port}`;
  for(let i=0;i<100;i++){try{await (await fetch(base+'/json/version')).json();break}catch(_){await sleep(150)}}
  const pages=[];
  const browser={proc,profile,base,pages,
    async newPage(url,{width=1440,height=900,pre=null}={}){
      const t=await (await fetch(base+'/json/new?about:blank',{method:'PUT'})).json();
      const p=await connect(t,url,width,height,pre);p.targetId=t.id;p.closeTab=async()=>{try{p.ws.close()}catch(_){}await fetch(base+'/json/close/'+t.id)};pages.push(p);return p;
    },
    async close(){
      for(const p of pages){try{p.ws.close()}catch(_){}}
      const exited=new Promise(r=>proc.once('exit',r));
      try{execFileSync('taskkill',['/PID',String(proc.pid),'/T','/F'],{stdio:'ignore'})}catch(_){proc.kill()}
      await Promise.race([exited,sleep(4000)]);
      try{rmSync(profile,{recursive:true,force:true,maxRetries:10,retryDelay:300})}catch(_){}
    }};
  return browser;
}

async function connect(target,url,width,height,pre){
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('ws'))});
  let id=0;const pending=new Map();
  const page={ws,console:[],errors:[],requests:[],responses:new Map(),hooks:{},choosers:[]};
  ws.onmessage=e=>{
    const m=JSON.parse(e.data);
    if(m.id&&pending.has(m.id)){const {ok,ko}=pending.get(m.id);pending.delete(m.id);m.error?ko(new Error(JSON.stringify(m.error))):ok(m.result);return}
    if(m.method&&page.hooks[m.method])page.hooks[m.method](m.params);
    if(m.method==='Page.fileChooserOpened')page.choosers.push(m.params);
    if(m.method==='Runtime.consoleAPICalled'){
      const text=(m.params.args||[]).map(a=>a.value!==undefined?String(a.value):(a.description||'')).join(' ');
      page.console.push({t:Date.now(),type:m.params.type,text:text.slice(0,500)});
    }else if(m.method==='Runtime.exceptionThrown'){
      page.errors.push(m.params.exceptionDetails.exception?.description||m.params.exceptionDetails.text);
    }else if(m.method==='Network.requestWillBeSent'){
      const r=m.params.request;
      page.requests.push({t:Date.now(),id:m.params.requestId,method:r.method,url:r.url,body:r.postData||null});
    }else if(m.method==='Network.responseReceived'){
      page.responses.set(m.params.requestId,m.params.response.status);
    }else if(m.method==='Network.loadingFailed'){
      page.responses.set(m.params.requestId,'failed:'+m.params.errorText);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{const k=++id;pending.set(k,{ok,ko});ws.send(JSON.stringify({id:k,method,params}))});
  page.send=send;
  page.inflight=()=>page.requests.filter(r=>!page.responses.has(r.id)).map(r=>({age:Date.now()-r.t,url:r.url.replace(/^https?:\/\/[^/]+/,'').slice(0,90)}));
  page.eval=async expr=>{
    const r=await send('Runtime.evaluate',{expression:expr,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const KEYS={Enter:{code:'Enter',keyCode:13,text:'\r'},Tab:{code:'Tab',keyCode:9},Escape:{code:'Escape',keyCode:27},Space:{key:' ',code:'Space',keyCode:32,text:' '}};
  page.press=async combo=>{
    const shift=combo.startsWith('Shift+'),name=shift?combo.slice(6):combo,k=KEYS[name];
    const key=k.key||name;
    await send('Input.dispatchKeyEvent',{type:'keyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,text:k.text,modifiers:shift?8:0});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,modifiers:shift?8:0});
  };
  page.type=text=>send('Input.insertText',{text});
  page.click=async sel=>{
    const at=await page.eval(`(()=>{const el=document.querySelector(${JSON.stringify(sel)});if(!el)return null;const r=el.getBoundingClientRect();return r.width?{x:r.left+r.width/2,y:r.top+r.height/2}:null})()`);
    if(!at)throw new Error('click: not found '+sel);
    for(const type of ['mouseMoved','mousePressed','mouseReleased'])await send('Input.dispatchMouseEvent',{type,x:at.x,y:at.y,button:'left',clickCount:1});
  };
  page.shot=async path=>{const s=await send('Page.captureScreenshot',{format:'png'});writeFileSync(path,Buffer.from(s.data,'base64'))};
  page.until=async(expr,ms=10000)=>{const end=Date.now()+ms;while(Date.now()<end){try{if(await page.eval(expr))return true}catch(_){}await sleep(100)}return false};
  page.size=async(width,height)=>send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
  page.goto=async u=>{await send('Page.navigate',{url:u});
    for(let i=0;i<200;i++){await sleep(100);if(await page.eval(`document.readyState==='complete'&&!!(window.JarvisChat&&window.JarvisChat.instance)`).catch(()=>false))break}};
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');await send('DOM.enable');
  await send('Page.setInterceptFileChooserDialog',{enabled:true});
  page.answerChooser=async(paths,ms=5000)=>{const n=page.choosers.length;const end=Date.now()+ms;
    while(Date.now()<end){if(page.choosers.length>n||page.choosers.some(c=>!c.used)){const c=page.choosers.find(c=>!c.used);c.used=true;
      await send('DOM.setFileInputFiles',{files:paths,backendNodeId:c.backendNodeId});return true}await sleep(50)}return false};
  page.drop=async(sel,paths,{x,y}={})=>{
    let at={x,y};
    if(sel){at=await page.eval(`(()=>{const el=document.querySelector(${JSON.stringify(sel)});if(!el)return null;const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);}
    if(!at)throw new Error('drop: not found '+sel);
    const data={items:[],files:paths,dragOperationsMask:1};
    for(const type of ['dragEnter','dragOver'])await send('Input.dispatchDragEvent',{type,x:at.x,y:at.y,data});
    const overlay=await page.eval(`!document.querySelector('#chatDrop').hidden`).catch(()=>null);
    await send('Input.dispatchDragEvent',{type:'drop',x:at.x,y:at.y,data});
    return {at,overlayDuringDrag:overlay};
  };
  page.throttle=kbps=>send('Network.emulateNetworkConditions',kbps?{offline:false,latency:20,downloadThroughput:-1,uploadThroughput:kbps*1024/8*8}:{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  await send('Emulation.setFocusEmulationEnabled',{enabled:true}).catch(()=>{});
  await page.size(width,height);
  if(pre)await send('Page.addScriptToEvaluateOnNewDocument',{source:pre});
  if(url)await page.goto(url);
  return page;
}
