/* QA S05 — pointer gestures over prefab frames, real CDP mouse events.
   Usage: node drag_probe.mjs <cc url> <chrome.exe> <out dir> <label> <prefabSpec json>
   prefabSpec: {"id":"jarvis.window","data":{...}} — the prefab used for pw-1 / pw-2. */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {join} from 'node:path';
import {tmpdir} from 'node:os';

const [,,URL_,CHROME,OUT,LABEL,SPEC,MODE]=process.argv;const FLAGS=(process.env.QA_CHROME_FLAGS||'').split(' ').filter(Boolean);
const spec=JSON.parse(SPEC);
const SCR=tmpdir();
const profile=mkdtempSync(join(SCR,'s05rw-chrome-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars',...FLAGS,'about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const upsert=(id,title,geometry,payload)=>({schema_version:1,op:'upsert_object',object_id:id,fields:{kind:'window',category:'research',
  representation:'window',geometry,payload:Object.assign({title,summary:'',items:[]},payload)}});
const BODY='Un corps de fenêtre assez long pour remplir.\n\n'+Array.from({length:12},(_,i)=>`- ligne ${i+1} du corps de test`).join('\n');
const COMMANDS=[
  upsert('legacy-1','Legacy',{x:-140,y:-60,w:56,h:50},{summary:BODY}),
  upsert('pw-1','Prefab A',{x:-60,y:-60,w:56,h:50},{summary:'repli',prefab:{id:spec.id,version:1,props:spec.props||{},data:spec.data}}),
  upsert('pw-2','Prefab B',{x:20,y:-60,w:56,h:50},{summary:'repli',prefab:{id:spec.id,version:1,props:spec.props||{},data:spec.data}}),
];
async function debuggerTarget(){
  const file=join(profile,'DevToolsActivePort');const deadline=Date.now()+60000;
  while(Date.now()<deadline){
    if(existsSync(file)){const port=readFileSync(file,'utf8').split('\n')[0].trim();
      try{const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();const page=list.find(t=>t.type==='page');if(page)return page}catch(_){}}
    await sleep(100);
  }
  throw new Error('no chrome');
}
const out={label:LABEL,spec:spec.id,console:[],scenarios:{}};
try{
  const target=await debuggerTarget();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('ws'))});
  let id=0;const pending=new Map();const sessions=new Map();
  ws.onmessage=event=>{const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled'){const text=msg.params.args.map(a=>a.value??a.description??'').join(' ');
      out.console.push({s:msg.sessionId?'frame':'page',type:msg.params.type,text:text.slice(0,240)})}
    if(msg.method==='Runtime.exceptionThrown')out.console.push({s:msg.sessionId?'frame':'page',type:'exception',text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,240)});
    if(msg.method==='Target.attachedToTarget'){const s=msg.params.sessionId;sessions.set(s,msg.params.targetInfo);
      send('Runtime.enable',{},s).catch(()=>{});send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{})}
    if(msg.method==='Target.detachedFromTarget')sessions.delete(msg.params.sessionId);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}};
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;
    const timer=setTimeout(()=>{pending.delete(mine);ko(new Error('timeout '+method))},15000);
    pending.set(mine,{ok:v=>{clearTimeout(timer);ok(v)},ko:e=>{clearTimeout(timer);ko(e)}});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression,session)=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},session);
    if(r.exceptionDetails)throw new Error(expression.slice(0,80)+' -> '+(r.exceptionDetails.exception?.description||r.exceptionDetails.text));return r.result.value};
  const until=async(check,ms=20000,label)=>{const d=Date.now()+ms;while(Date.now()<d){try{const v=await check();if(v)return v}catch(_){}await sleep(150)}throw new Error('never: '+label)};
  const frameSessions=()=>[...sessions].filter(([,i])=>i.url==='about:srcdoc').map(([s])=>s);
  const box=sel=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(sel)});if(!el)return null;const r=el.getBoundingClientRect();
    return {x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2,r:r.right,b:r.bottom}})()`);
  const mouse=(type,x,y,buttons,extra)=>send('Input.dispatchMouseEvent',Object.assign({type,x,y,button:buttons===0&&type==='mouseMoved'?'none':'left',buttons:buttons??(type==='mouseReleased'?0:1),clickCount:1},extra||{}));
  const stored=oid=>evaluate(`fetch('/api/scene',{cache:'no-store'}).then(r=>r.json()).then(b=>{const o=b.snapshot.objects.find(o=>o.object_id===${JSON.stringify(oid)});return o?{revision:b.revision,geometry:o.geometry}:null})`);
  const shot=async name=>{const r=await send('Page.captureScreenshot',{format:'png'});writeFileSync(join(OUT,name),Buffer.from(r.data,'base64'))};

  await send('Page.enable');await send('Runtime.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate('!!window.JarvisScene'),30000,'scene');
  /* fresh scene: delete leftovers */
  for(const oid of ['legacy-1','pw-1','pw-2'])await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema_version:1,op:'remove_object',object_id:${JSON.stringify(oid)}})}).then(r=>r.status)`).catch(()=>{});
  out.created=[];
  for(const c of COMMANDS)out.created.push(await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:${JSON.stringify(JSON.stringify(c))}}).then(async r=>({s:r.status,b:(await r.json()).outcome}))`));
  /* Même scène de scratch que layout_probe.mjs : ses fenêtres sont masquées, les nôtres visibles. */
  const visibility=(oid,v)=>evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema_version:1,op:'set_visibility',object_id:${JSON.stringify(oid)},visibility:${JSON.stringify(v)}})}).then(r=>r.status)`).catch(()=>{});
  for(const oid of ['pw-tall','doc-1','tbl-1','doc-tall'])await visibility(oid,'hidden');
  for(const oid of ['legacy-1','pw-1','pw-2'])await visibility(oid,'visible');
  for(const oid of ['pw-1','pw-2'])await until(()=>evaluate(`!!document.querySelector('[data-object-id="${oid}"] .sc-prefab-slot iframe')`),30000,oid);
  await sleep(1500);
  out.frameCss=await evaluate(`(()=>{const f=document.querySelector('[data-object-id="pw-1"] iframe');const cs=getComputedStyle(f);return {flex:cs.flex,h:f.getBoundingClientRect().height,styleH:f.style.height,slotH:f.parentElement.getBoundingClientRect().height,slotScroll:[f.parentElement.scrollHeight,f.parentElement.clientHeight]}})()`);

  /* page-level probe: log every pointer event + capture state */
  await evaluate(`(()=>{window.__qa=[];const rec=e=>{const t=e.target;window.__qa.push({t:e.type,x:Math.round(e.clientX||0),y:Math.round(e.clientY||0),
     target:t&&t.tagName?(t.tagName+'.'+String(t.className&&t.className.baseVal!==undefined?t.className.baseVal:t.className).split(' ')[0]):String(t),
     cap:(()=>{const n=t&&t.closest&&t.closest('.sc-node');return n&&e.pointerId!==undefined?n.hasPointerCapture(e.pointerId):null})(),
     dragging:document.querySelectorAll('.sc-dragging').length,pe:[...document.querySelectorAll('.sc-prefab-slot iframe')].map(f=>getComputedStyle(f).pointerEvents).join(',')})};
   for(const k of ['pointerdown','pointermove','pointerup','pointercancel','gotpointercapture','lostpointercapture','mouseup','blur'])window.addEventListener(k,rec,true);
   return true})()`);
  const resetLog=()=>evaluate('(window.__qa=[],true)');
  const frameLogInstall=async()=>{for(const s of frameSessions()){try{await evaluate(`(()=>{window.__qaf={};for(const k of ['pointermove','pointerup','pointerdown','mousemove','mouseup','wheel'])addEventListener(k,e=>{window.__qaf[k]=(window.__qaf[k]||0)+1},true);return true})()`,s)}catch(_){}}};
  const frameLogRead=async()=>{const r=[];for(const s of frameSessions()){try{r.push(await evaluate(`(()=>{const v=window.__qaf||{};window.__qaf={};return v})()`,s))}catch(_){}}return r};
  await frameLogInstall();

  const summarize=log=>{const s={};for(const e of log)s[e.t]=(s[e.t]||0)+1;
    const moves=log.filter(e=>e.t==='pointermove');
    return {counts:s,firstMove:moves[0]||null,lastMove:moves[moves.length-1]||null,
      up:log.filter(e=>e.t==='pointerup'||e.t==='lostpointercapture'||e.t==='pointercancel'),
      peDuring:[...new Set(log.map(e=>e.pe))],targetsDuringMove:[...new Set(moves.map(e=>e.target))]}};

  const scenario=async(name,oid,fromSel,dx,dy,opts={})=>{
    await mouse('mouseMoved',1500,950,0);await sleep(150);
    const r0={};const before=await stored(oid);const from=await box(fromSel);const nodeBefore=await box(`[data-object-id="${oid}"]`);
    const start={x:from.cx,y:from.cy};const startEl=await evaluate(`(()=>{const e=document.elementFromPoint(${start.x},${start.y});return e?e.tagName+'.'+String(e.className&&e.className.baseVal!==undefined?e.className.baseVal:e.className).split(' ')[0]:null})()`);
    await resetLog();await frameLogRead();
    const steps=opts.steps||16;const path=[];
    await mouse('mouseMoved',start.x,start.y,0);await sleep(40);
    await mouse('mousePressed',start.x,start.y);await sleep(40);
    for(let i=1;i<=steps;i++){const x=start.x+dx*i/steps,y=start.y+dy*i/steps;
      const at=await evaluate(`(()=>{const e=document.elementFromPoint(${x},${y});return e?e.tagName+'.'+String(e.className&&e.className.baseVal!==undefined?e.className.baseVal:e.className).split(' ')[0]:null})()`);
      path.push(at);await mouse('mouseMoved',x,y);await sleep(30)}
    const mid=await evaluate(`({dragging:document.querySelectorAll('.sc-dragging').length,node:(()=>{const r=document.querySelector('[data-object-id="${oid}"]').getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height),x:Math.round(r.x),y:Math.round(r.y)}})(),
      shield:(document.querySelector('.scene')||{classList:{contains:()=>null}}).classList.contains('sc-gesture'),
      framePE:[...document.querySelectorAll('.sc-prefab-frame')].map(f=>getComputedStyle(f).pointerEvents)})`);
    if(opts.midHook)r0.mid2=await opts.midHook();
    await mouse('mouseReleased',start.x+dx,start.y+dy);await sleep(900);
    const nodeAfter=await box(`[data-object-id="${oid}"]`);
    const release={x:start.x+dx,y:start.y+dy};
    /* where did it land? resize: grip corner offset kept; move: node shifted by the pointer delta */
    const landed=opts.kind==='resize'?{dRight:Math.round((nodeAfter.r-nodeBefore.r)-dx),dBottom:Math.round((nodeAfter.b-nodeBefore.b)-dy)}
      :{dX:Math.round((nodeAfter.x-nodeBefore.x)-dx),dY:Math.round((nodeAfter.y-nodeBefore.y)-dy)};
    const shieldAfter=await evaluate(`({shield:document.querySelector('.scene').classList.contains('sc-gesture'),pe:[...document.querySelectorAll('.sc-prefab-frame')].map(f=>getComputedStyle(f).pointerEvents)})`);
    const after=await stored(oid);const log=await evaluate('window.__qa');
    const r={...r0,release,landed,shieldAfter,nodeBefore,nodeAfter,start,startEl,dx,dy,lost:log.filter(e=>e.t==='lostpointercapture'||e.t==='pointerup'),pathElements:[...new Set(path)],mid,before:before.geometry,after:after.geometry,revision:[before.revision,after.revision],
      committed:JSON.stringify(before.geometry)!==JSON.stringify(after.geometry),pageEvents:summarize(log),frameEvents:await frameLogRead(),
      stuckDragging:await evaluate(`document.querySelectorAll('.sc-dragging').length`)};
    out.scenarios[name]=r;console.log(name,JSON.stringify({landed,shield:mid.shield,framePE:mid.framePE,shieldAfter,mid2:r.mid2,startEl,lost:r.lost,committed:r.committed,counts:r.pageEvents.counts,path:r.pathElements,frame:r.frameEvents,mid,before:r.before,after:r.after}));
    return r;
  };
  const L='[data-object-id="legacy-1"]',A='[data-object-id="pw-1"]',B='[data-object-id="pw-2"]';
  await shot(`${LABEL}-before.png`);
  /* resize: shrink moves pointer up-left into the window body (legacy: summary, prefab: iframe) */
  if(MODE==='fix'){out.fixInjected=await evaluate(`(()=>{const st=document.createElement('style');st.textContent='.sc-node.sc-dragging .sc-prefab-frame,body:has(.sc-dragging) .sc-prefab-frame{pointer-events:none}';document.head.append(st);return true})()`)}
  const ONLY=(process.env.QA_ONLY||'').split(',').filter(Boolean);const want=n=>!ONLY.length||ONLY.includes(n);
  if(want('legacyGrowIntoPrefabFrame'))await scenario('legacyGrowIntoPrefabFrame','legacy-1',`${L} .sc-grip`,220,-60,{kind:'resize'});
  if(want('prefabGrowIntoPrefabFrame'))await scenario('prefabGrowIntoPrefabFrame','pw-1',`${A} .sc-grip`,220,-60,{kind:'resize'});
  if(want('legacyHeadAcrossFrames'))await scenario('legacyHeadAcrossFrames','legacy-1',`${L} .sc-wtitle`,520,60,{kind:'move',steps:24});
  if(want('prefabHeadAcrossFrames'))await scenario('prefabHeadAcrossFrames','pw-2',`${B} .sc-wtitle`,-420,80,{kind:'move',steps:24});
  /* window blur mid-gesture (app switch): gesture cancelled, shield dropped, nothing stored */
  if(want('blurMidDrag'))await scenario('blurMidDrag','pw-1',`${A} .sc-grip`,120,40,{kind:'resize',midHook:async()=>{
    await evaluate('window.dispatchEvent(new Event("blur")),true');await sleep(200);
    return await evaluate(`({shield:document.querySelector('.scene').classList.contains('sc-gesture'),dragging:document.querySelectorAll('.sc-dragging').length,pe:[...document.querySelectorAll('.sc-prefab-frame')].map(f=>getComputedStyle(f).pointerEvents)})`)}});
  /* selection band from empty space, released over a prefab frame */
  if(want('bandAcrossFrames')){
    await mouse('mouseMoved',1500,950,0);await mouse('mousePressed',1500,950);await mouse('mouseReleased',1500,950);await sleep(300);
    const fa=await box(`${A} iframe`),fb=await box(`${B} iframe`);
    const from={x:fa.x-30,y:Math.max(fa.b,fb.b)+90},to={x:fb.cx,y:fb.cy};
    await resetLog();
    await mouse('mouseMoved',from.x,from.y,0);await mouse('mousePressed',from.x,from.y);
    let midShield=null;
    for(let i=1;i<=20;i++){await mouse('mouseMoved',from.x+(to.x-from.x)*i/20,from.y+(to.y-from.y)*i/20);await sleep(30);
      if(i===18)midShield=await evaluate(`({shield:document.querySelector('.scene').classList.contains('sc-gesture'),band:!!document.querySelector('.sc-band'),pe:[...document.querySelectorAll('.sc-prefab-frame')].map(f=>getComputedStyle(f).pointerEvents)})`)}
    await mouse('mouseReleased',to.x,to.y);await sleep(500);
    out.band={from,to,midShield,after:await evaluate(`({band:!!document.querySelector('.sc-band'),shield:document.querySelector('.scene').classList.contains('sc-gesture'),selected:[...document.querySelectorAll('.sc-selected')].map(e=>e.dataset.objectId)})`)};
    console.log('band',JSON.stringify(out.band));
  }
  await shot(`${LABEL}-after.png`);

  /* wheel inside a prefab frame */
  const fA=await box(`${A} iframe`);
  const view=()=>evaluate(`(()=>{const l=document.querySelector('#sceneLayer')||document.querySelector('.scene');const n=document.querySelector('${A}');
    return {layer:l?getComputedStyle(l).transform:null,node:n.style.transform||n.getAttribute('style'),inspect:(window.JarvisScene&&JarvisScene.inspect&&JSON.stringify(JarvisScene.inspect().view||null))}})()`);
  const frameScroll=async()=>{const r=[];for(const s of frameSessions()){try{r.push(await evaluate('({top:document.scrollingElement.scrollTop,max:document.scrollingElement.scrollHeight-document.scrollingElement.clientHeight,id:document.body&&document.body.firstElementChild&&document.body.firstElementChild.id})',s))}catch(_){}}return r};
  const v0=await view(),s0=await frameScroll();
  await mouse('mouseMoved',fA.cx,fA.cy,0);await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:fA.cx,y:fA.cy,deltaX:0,deltaY:300});await sleep(600);
  await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:fA.cx,y:fA.cy,deltaX:0,deltaY:300,modifiers:2});await sleep(600);
  out.wheel={before:{view:v0,frames:s0},after:{view:await view(),frames:await frameScroll()},frameEvents:await frameLogRead()};
  console.log('wheel',JSON.stringify(out.wheel));
  /* click inside frame selects the window? */
  await mouse('mouseMoved',1500,950,0);await mouse('mousePressed',1500,950);await mouse('mouseReleased',1500,950);await sleep(300);
  const fB=await box(`${B} iframe`);
  const selBefore=await evaluate(`[...document.querySelectorAll('.sc-selected')].map(e=>e.dataset.objectId)`);
  await mouse('mouseMoved',fB.cx,fB.cy,0);await mouse('mousePressed',fB.cx,fB.cy);await mouse('mouseReleased',fB.cx,fB.cy);await sleep(600);
  out.clickInFrame={selBefore,selAfter:await evaluate(`[...document.querySelectorAll('.sc-selected')].map(e=>e.dataset.objectId)`),active:await evaluate('document.activeElement&&(document.activeElement.dataset.objectId||document.activeElement.tagName)')};
  console.log('click',JSON.stringify(out.clickInFrame));
}catch(error){out.error=String(error&&error.stack||error);console.log('ERROR',out.error)}
finally{
  writeFileSync(join(OUT,`drag-${LABEL}.json`),JSON.stringify(out,null,1));
  chrome.kill();await sleep(800);try{rmSync(profile,{recursive:true,force:true})}catch(_){}
  process.exit(0);
}
