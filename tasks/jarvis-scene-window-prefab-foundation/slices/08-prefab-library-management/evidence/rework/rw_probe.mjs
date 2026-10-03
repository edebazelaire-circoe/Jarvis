/* QA S08 probe: security, XSS, concurrency, cache, preview spy, deadline, a11y, layout.
   Usage: node qa_probe.mjs <CC url> <chrome> <outdir> <core url> <token file> <phase> */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import http from 'node:http';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT,CORE,TOKEN_FILE,PHASE='main']=process.argv;
const out={phase:PHASE,console:[],steps:{},http:{}};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const token=existsSync(TOKEN_FILE)?readFileSync(TOKEN_FILE,'utf8').trim():'';
const core=async(method,path,body)=>{const r=await fetch(`${CORE}${path}`,{method,headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},
  body:body?JSON.stringify(body):undefined});let b=null;try{b=await r.json()}catch(_){}return {status:r.status,body:b}};
/* raw HTTP to the CC (lets us set Origin freely) */
function cc(method,path,{body,headers={}}={}){
  const u=new URL(path,URL_);
  const data=body===undefined?null:(Buffer.isBuffer(body)?body:Buffer.from(typeof body==='string'?body:JSON.stringify(body)));
  return new Promise((ok,ko)=>{const req=http.request({host:u.hostname,port:u.port,path:u.pathname+u.search,method,
    headers:{'Content-Type':'application/json',...(data?{'Content-Length':data.length}:{}),...headers}},res=>{
      const chunks=[];res.on('data',c=>chunks.push(c));res.on('end',()=>{const t=Buffer.concat(chunks).toString('utf8');
        let j=null;try{j=JSON.parse(t)}catch(_){}ok({status:res.statusCode,body:j||t.slice(0,300)})})});
    req.on('error',e=>ok({status:0,body:String(e)}));if(data)req.write(data);req.end()});
}
const short=r=>({status:r.status,code:r.body&&r.body.error&&r.body.error.code||r.body&&r.body.code||null,
  origin:r.body&&r.body.provenance&&r.body.provenance.origin||null,actor:r.body&&r.body.created_by&&r.body.created_by.actor||
  r.body&&r.body.provenance&&r.body.provenance.created_by&&r.body.provenance.created_by.actor||null,id:r.body&&r.body.prefab_id||null,v:r.body&&r.body.version||null});

let chrome,profile;
try{
  const src=PHASE==='main'?(await core('GET','/v1/prefabs/jarvis.checklist/1?include_source=1')).body:{};
  const cand=(m)=>({manifest:{...src.manifest,version:1,aliases:[],...m},...src.files});
  if(PHASE==='main'){
    /* ---------------- HTTP security on the relay */
    const H=out.http;
    H.actorForced=short(await cc('POST','/api/prefabs',{body:{actor:'brain',candidate:cand({id:'qa.actor-test',title:'Actor test'})}}));
    H.actorForcedCore=(await core('GET','/v1/prefabs/qa.actor-test')).body?.history?.map(h=>[h.version,h.origin,h.created_by]);
    H.originNull=short(await cc('POST','/api/prefabs',{body:{candidate:cand({id:'qa.o-null',title:'x'})},headers:{Origin:'null'}}));
    H.originEvil=short(await cc('POST','/api/prefabs',{body:{candidate:cand({id:'qa.o-evil',title:'x'})},headers:{Origin:'http://evil.example'}}));
    H.originEvilGet=short(await cc('GET','/api/prefabs',{headers:{Origin:'http://evil.example'}}));
    H.originNullWritten=(await core('GET','/v1/prefabs/qa.o-null')).status;
    H.tooBig=short(await cc('POST','/api/prefabs',{body:Buffer.from(JSON.stringify({candidate:cand({id:'qa.big',title:'x'}),pad:'x'.repeat(530*1024)}))}));
    H.baseEditRoute=short(await cc('POST','/api/prefabs/jarvis.table/base-edits',{body:{candidate:cand({id:'jarvis.table'}),user_request:'Jarvis modifie la table stp',confirmed_by_user:true}}));
    H.validateRoute=short(await cc('POST','/api/prefabs/validate',{body:{candidate:cand({id:'qa.v'})}}));
    H.baseProtected=short(await cc('POST','/api/prefabs',{body:{candidate:cand({id:'jarvis.rw-qa-x',title:'x'})}}));
    H.baseProtectedWritten=(await core('GET','/v1/prefabs/jarvis.rw-qa-x')).status;
    H.baseIdExisting=short(await cc('POST','/api/prefabs',{body:{candidate:cand({id:'jarvis.checklist',version:2,title:'x'})}}));
    H.smuggleGateFields=short(await cc('POST','/api/prefabs',{body:{candidate:cand({id:'qa.smuggle',title:'x'}),user_request:'Jarvis modifie la base stp',confirmed_by_user:true}}));
    H.smuggleOrigin=short(await cc('POST','/api/prefabs',{body:{candidate:cand({id:'qa.smuggle2',title:'x'}),origin:'base_edit'}}));
    H.query=short(await cc('POST','/api/prefabs?x=1',{body:{candidate:cand({id:'qa.q',title:'x'})}}));
    H.array=short(await cc('POST','/api/prefabs',{body:[1]}));
    H.notJson=short(await cc('POST','/api/prefabs',{body:'{"a":1,"a":2}'}));
    H.sceneActor=short(await cc('POST','/api/scene/commands',{body:{schema_version:1,op:'upsert_object',object_id:'rw-qa-actor-obj',actor:'brain',
      fields:{kind:'window',category:'prefab',representation:'window',payload:{title:'t',summary:'',items:[],prefab:{id:'jarvis.checklist',version:1,props:{},data:src.manifest.sample.data}}}}}));
    const snap=(await core('GET','/v1/scene/snapshot')).body.snapshot;
    H.sceneActorOrigin=(snap.objects.find(o=>o.object_id==='rw-qa-actor-obj')||{}).origin;

    /* ---------------- seed: hostile strings, fork chain, several customs */
    const evilTitle='<img src=x onerror="window.__xss=1">‮evil';
    const evilDesc='<script>window.__xss=2</script> <b>gras</b> '+'A'.repeat(300)+' ‮desserp sruoc‬ fin '+'mot '.repeat(40);
    const m=JSON.parse(JSON.stringify(src.manifest));
    m.inputs.props.properties.accent.description='<img src=x onerror="window.__xss=3">';
    const evIdx=Object.keys(m.events)[0];m.events[evIdx].summary='<svg onload="window.__xss=4">';
    out.steps.seed={
      evil:short(await core('POST','/v1/prefabs',{actor:'brain',candidate:{...src.files,manifest:{...m,id:'qa.evil',version:1,title:evilTitle.slice(0,80),
        description:evilDesc.slice(0,600),aliases:['<b>alias</b>','‮evil-alias','rw-qa-unique-alias'],tags:['<i>t</i>']}}})),
      fork1:short(await core('POST','/v1/prefabs',{actor:'brain',candidate:cand({id:'qa.fork1',title:'Fork un'}),derived_from:{id:'jarvis.checklist',version:1}})),
      fork2:short(await core('POST','/v1/prefabs',{actor:'brain',candidate:cand({id:'qa.fork2',title:'Fork deux'}),derived_from:{id:'qa.fork1',version:1}})),
    };
    for(let i=1;i<=6;i++)out.steps.seed[`c${i}`]=short(await core('POST','/v1/prefabs',{actor:'brain',candidate:cand({id:`qa.c${i}`,title:`Custom ${i}`})}));
  }

  /* ---------------- browser */
  profile=mkdtempSync(join(tmpdir(),'rw-s08-cdp-'));
  chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
    '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
  const file=join(profile,'DevToolsActivePort');let target;
  for(const end=Date.now()+60000;Date.now()<end&&!target;){
    if(existsSync(file)){const port=readFileSync(file,'utf8').split('\n')[0].trim();
      try{target=(await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t=>t.type==='page')}catch(_){}}
    await sleep(100);
  }
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('ws'))});
  let id=0;const pending=new Map();const contexts=new Map();
  ws.onmessage=event=>{const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled')out.console.push({s:msg.sessionId?'frame':'page',type:msg.params.type,
      text:msg.params.args.map(a=>a.value??a.description??'').join(' ').slice(0,300)});
    if(msg.method==='Runtime.exceptionThrown')out.console.push({s:msg.sessionId?'frame':'page',type:'exception',
      text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,300)});
    if(msg.method==='Target.attachedToTarget'){const s=msg.params.sessionId;send('Runtime.enable',{},s).catch(()=>{});send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{})}
    if(msg.method==='Runtime.executionContextCreated')contexts.set(`${msg.sessionId||''}:${msg.params.context.id}`,
      {session:msg.sessionId||null,id:msg.params.context.id,main:!!(msg.params.context.auxData&&msg.params.context.auxData.isDefault)});
    if(msg.method==='Runtime.executionContextDestroyed')contexts.delete(`${msg.sessionId||''}:${msg.params.executionContextId}`);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}};
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;
    const t=setTimeout(()=>{pending.delete(mine);ko(new Error(`CDP ${method} timeout`))},20000);
    pending.set(mine,{ok:v=>{clearTimeout(t);ok(v)},ko:e=>{clearTimeout(t);ko(e)}});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression)=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,100)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);return r.result.value};
  const until=async(check,ms=20000,label)=>{const end=Date.now()+ms;while(Date.now()<end){try{const v=await check();if(v)return v}catch(_){}await sleep(150)}
    throw new Error('never true: '+(label||''))};
  const inFrame=async(match,expression)=>{for(const ctx of [...contexts.values()]){if(!ctx.main)continue;
    try{const r=await send('Runtime.evaluate',{expression:`(${match})?(${expression}):null`,returnByValue:true,awaitPromise:true,contextId:ctx.id},ctx.session||undefined);
      if(r.exceptionDetails)continue;const v=r.result.value;if(v!==null&&v!==undefined)return v}catch(_){}}return null};
  const box=s=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(s)});if(!e)return null;const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}})()`);
  const mouse=(type,x,y,b)=>send('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:b??(type==='mouseReleased'?0:1),clickCount:1});
  const click=async(x,y)=>{await mouse('mouseMoved',x,y,0);await mouse('mousePressed',x,y);await mouse('mouseReleased',x,y);await sleep(80)};
  const clickOn=async s=>{await until(()=>box(s),8000,s);await evaluate(`document.querySelector(${JSON.stringify(s)}).scrollIntoView({block:'center'})`);await sleep(120);const b=await box(s);await click(b.cx,b.cy);return b};
  const KEYS={Escape:27,Enter:13,ArrowDown:40,ArrowUp:38,Tab:9,'/':191,Backspace:8};
  const key=async(k,mods)=>{const vk=KEYS[k]||0;const text=k.length===1?k:k==='Enter'?'\r':null;const extra=mods?{modifiers:mods}:{};
    await send('Input.dispatchKeyEvent',{type:text?'keyDown':'rawKeyDown',key:k,code:k,windowsVirtualKeyCode:vk,...(text?{text}:{}),...extra});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:k,code:k,windowsVirtualKeyCode:vk,...extra});await sleep(90)};
  const type=async t=>{await send('Input.insertText',{text:t});await sleep(60)};
  const shot=async(name,clip)=>{const r=await send('Page.captureScreenshot',clip?{format:'png',clip:{...clip,scale:1}}:{format:'png'});writeFileSync(join(OUT,name),Buffer.from(r.data,'base64'));return name};
  const theme=n=>evaluate(`(JarvisThemeAPI.activate(${JSON.stringify(n)}),document.documentElement.dataset.jarvisTheme)`);
  const active=()=>evaluate(`(()=>{const a=document.activeElement;return a?{tag:a.tagName,id:a.id||null,cls:a.className&&String(a.className).slice(0,40),text:(a.textContent||'').trim().slice(0,50),label:a.getAttribute('aria-label')}:null})()`);
  const rows=()=>evaluate(`[...document.querySelectorAll('#pfbList .pfb-row')].map(r=>({id:r.dataset.id,badges:[...r.querySelectorAll('.pfb-badge')].map(b=>b.textContent),parent:r.querySelector('.pfb-parent')?.textContent||null}))`);
  const settled=()=>until(()=>evaluate(`(()=>{const L=window.JarvisPrefabLibrary;return L&&L.state.list.status==='ready'&&!L.library.waiting()})()`),25000,'settled');
  const SPY=`(()=>{if(window.__spy)return;const s=window.__spy={calls:[],inflight:0,maxDetail:0,detailNow:0,hang:null};const orig=window.fetch.bind(window);
    window.fetch=(input,opts={})=>{const url=typeof input==='string'?input:input.url;const method=(opts.method||'GET').toUpperCase();
      const isDetail=method==='GET'&&/^\\/api\\/prefabs\\/[^/?]+$/.test(url);
      s.calls.push({method,url,body:opts.body?String(opts.body).slice(0,400):null,t:Date.now()});
      if(s.fail&&new RegExp(s.fail).test(url))return Promise.resolve(new Response(JSON.stringify({error:{code:'storage_io',message:'disque illisible (probe)'}}),{status:500,headers:{'Content-Type':'application/json'}}));
      if(s.slow&&new RegExp(s.slow).test(url))return new Promise(r=>setTimeout(r,2500)).then(()=>orig(input,opts));
      if(s.hang&&new RegExp(s.hang).test(url))return new Promise((ok,ko)=>{if(opts.signal)opts.signal.addEventListener('abort',()=>ko(new DOMException('aborted','AbortError')))});
      if(isDetail){s.detailNow++;s.maxDetail=Math.max(s.maxDetail,s.detailNow)}
      const slow=isDetail?new Promise(r=>setTimeout(r,250)):Promise.resolve();
      return slow.then(()=>orig(input,opts)).finally(()=>{if(isDetail)s.detailNow--})}})()`;

  await send('Page.enable');await send('Runtime.enable');await send('Accessibility.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate("!!window.JarvisPrefabLibrary&&!!window.JarvisThemeAPI&&!!window.JarvisPrefabHost"),30000,'page');
  await theme('circuit-board');await evaluate(SPY);
  await evaluate("window.__spy.fail='^/api/prefabs/qa\\.c4$'");

  if(PHASE==='down'){
    await clickOn('#openPrefabs');
    await until(()=>evaluate("window.JarvisPrefabLibrary.state.list.status==='error'"),25000,'error');await sleep(300);
    out.steps.down={status:await evaluate("document.getElementById('pfbStatus').innerText"),box:await evaluate("document.querySelector('#pfbListState').innerText")};
    await shot('rw-qa-core-down.png');
    throw 'done';
  }

  /* 1. open, concurrency */
  await clickOn('#openPrefabs');await settled();await sleep(400);
  out.steps.open={rows:await rows(),maxDetail:await evaluate('window.__spy.maxDetail'),
    detailGets:await evaluate("window.__spy.calls.filter(c=>c.method==='GET'&&/^\\/api\\/prefabs\\/[^/?]+$/.test(c.url)).length")};
  /* R1. provenance failure */
  out.steps.rwUnknown={row:(await rows()).find(r=>r.id==='qa.c4')};
  for(const k of ['fork','custom']){await evaluate(`document.querySelector('#pfbKinds [data-kind="${k}"]').click()`);await sleep(200);
    out.steps.rwUnknown[k]=(await rows()).map(r=>r.id).includes('qa.c4')}
  await shot('rw-provenance-unknown-filter.png');
  await evaluate(`document.querySelector('#pfbKinds [data-kind="all"]').click()`);await sleep(200);
  await clickOn('#pfbList .pfb-row[data-id="qa.c4"]');await sleep(500);
  out.steps.rwUnknown.detail=await evaluate("document.querySelector('#pfbDetail .pfb-error')?.innerText||null");
  await shot('rw-provenance-unknown-detail.png');
  await evaluate("window.__spy.fail=null");
  await clickOn('#pfbDetail .pfb-error button');await settled();await sleep(300);
  out.steps.rwUnknown.afterRetry=(await rows()).find(r=>r.id==='qa.c4');

  /* 2. XSS */
  out.steps.xss={flag:await evaluate('window.__xss===undefined?null:window.__xss'),imgs:await evaluate("document.querySelectorAll('#prefabLibrary img,#prefabLibrary script,#prefabLibrary b,#prefabLibrary i').length"),
    rowText:await evaluate("document.querySelector('#pfb-row-qa\\\\.evil')?.innerText||null"),
    rowLabel:await evaluate("document.querySelector('#pfb-row-qa\\\\.evil')?.getAttribute('aria-label')||null")};
  await shot('rw-qa-list-evil.png');
  await clickOn('#pfbList .pfb-row[data-id="qa.evil"]');await settled();await sleep(800);
  out.steps.xssDetail={flag:await evaluate('window.__xss===undefined?null:window.__xss'),
    imgs:await evaluate("document.querySelectorAll('#prefabLibrary img,#prefabLibrary script,#prefabLibrary svg[onload]').length"),
    overflow:await evaluate("(()=>{const d=document.getElementById('pfbDetail');const l=document.getElementById('pfbList');return {detail:[d.scrollWidth,d.clientWidth],list:[l.scrollWidth,l.clientWidth],page:[document.documentElement.scrollWidth,innerWidth]}})()"),
    frameXss:await inFrame("true","window.__xss===undefined?'none':window.__xss")};
  await shot('rw-qa-detail-evil.png');
  await clickOn('#pfbForkOpen');await sleep(400);
  await shot('rw-qa-fork-evil.png');
  out.steps.forkEvilHeading=await evaluate("document.querySelector('.pfb-form h4').innerText");
  await key('Escape');await sleep(200);
  out.steps.escapeForkFocus=await active();

  /* 3. search by alias */
  for(const q of ['todo','liste de contrôle','rw-qa-unique-alias']){
    await evaluate(`(()=>{const s=document.getElementById('pfbSearch');s.value=${JSON.stringify(q)};s.dispatchEvent(new Event('input'))})()`);
    await until(()=>evaluate(`window.JarvisPrefabLibrary.state.query===${JSON.stringify(q)}`),5000,'q');await settled();await sleep(150);
    out.steps[`alias:${q}`]=(await rows()).map(r=>r.id);
  }
  await evaluate(`(()=>{const s=document.getElementById('pfbSearch');s.value='';s.dispatchEvent(new Event('input'))})()`);
  await until(()=>evaluate(`window.JarvisPrefabLibrary.state.query===''`),5000,'q0');await settled();

  /* 4. chain fork of fork */
  await clickOn('#pfbList .pfb-row[data-id="qa.fork2"]');await settled();await sleep(300);
  out.steps.chain={text:await evaluate("document.querySelector('.pfb-chain')?.innerText||null"),
    links:await evaluate("[...document.querySelectorAll('.pfb-chain .pfb-link')].map(b=>[b.textContent,b.title])")};

  /* 5. preview spy: real click inside the frame */
  await clickOn('#pfbList .pfb-row[data-id="jarvis.checklist"]');await settled();
  const MAIN="document.getElementById('ck')&&document.querySelectorAll('.ck-item').length>0";
  await until(()=>inFrame(MAIN,"true"),20000,'frame');await sleep(600);
  const ringBefore=(await core('GET','/v1/prefabs/events?limit=50')).body.events.length;
  const fb=await box('#pfbDetail iframe');
  const pt=await inFrame(MAIN,"(()=>{const r=document.querySelectorAll('.ck-item')[1].getBoundingClientRect();return {x:r.x+20,y:r.y+r.height/2}})()");
  await click(fb.x+pt.x,fb.y+pt.y);
  await until(()=>evaluate("document.querySelectorAll('.pfb-logs li').length>0"),6000,'logged');await sleep(400);
  /* Escape with focus inside the frame */
  await key('Escape');await sleep(300);
  out.steps.escapeInFrame={hidden:await evaluate("document.getElementById('prefabLibrary').hidden")};
  out.steps.preview={log:await evaluate("document.querySelectorAll('.pfb-logs li').length"),
    eventPosts:await evaluate("window.__spy.calls.filter(c=>/\\/api\\/prefabs\\/events/.test(c.url)).length"),
    ringBefore,ringAfter:(await core('GET','/v1/prefabs/events?limit=50')).body.events.length};
  if(await evaluate("document.getElementById('prefabLibrary').hidden")){await clickOn('#openPrefabs');await settled()}

  /* 6. place: request body actor */
  await evaluate("window.JarvisPrefabLibrary.select('jarvis.checklist')");await settled();
  await clickOn('#pfbPlace');await until(()=>evaluate("!!document.querySelector('.pfb-placed')"),10000,'placed');
  out.steps.place={body:await evaluate("(window.__spy.calls.filter(c=>c.url==='/api/scene/commands').pop()||{}).body")};

  /* 7. cache invalidation: revision on qa.c1, Actualiser */
  await evaluate("window.__spy.calls.length=0");
  out.steps.revision=short(await core('POST','/v1/prefabs',{actor:'brain',candidate:cand({id:'qa.c1',version:2,title:'Custom 1 rev'})}));
  await clickOn('#pfbRefresh');await settled();await sleep(400);
  out.steps.refresh={detailGets:await evaluate("window.__spy.calls.filter(c=>c.method==='GET'&&/^\\/api\\/prefabs\\/[^/?]+$/.test(c.url)).map(c=>c.url)"),
    c1:(await rows()).find(r=>r.id==='qa.c1')};

  /* 8. fork via UI from qa.c1 */
  await clickOn('#pfbList .pfb-row[data-id="qa.c1"]');await settled();
  await clickOn('#pfbForkOpen');await until(()=>evaluate("document.activeElement&&document.activeElement.name==='id'"),5000,'idf');
  await type('team.rw-qa-fork');await key('Enter');
  await until(()=>evaluate("window.JarvisPrefabLibrary.state.selected==='team.rw-qa-fork'&&!window.JarvisPrefabLibrary.state.fork"),20000,'forked');await settled();await sleep(300);
  out.steps.fork={post:await evaluate("(()=>{const c=window.__spy.calls.filter(c=>c.method==='POST'&&c.url==='/api/prefabs').pop();return c?c.body.slice(0,80)+' … hasActor='+/\"actor\"/.test(c.body):null})()"),
    row:(await rows()).find(r=>r.id==='team.rw-qa-fork'),core:(await core('GET','/v1/prefabs/team.rw-qa-fork')).body.history.map(h=>[h.version,h.origin,h.derived_from,h.created_by])};
  await shot('rw-qa-fork-done.png');

  /* R2. fork outcomes while elsewhere, French refusals */
  out.steps.rwLate=short(await core('POST','/v1/prefabs',{actor:'brain',candidate:cand({id:'qa.late',title:'Publié après la lecture'})}));
  const forkFrom=async(id,newId,away)=>{
    await evaluate(`window.JarvisPrefabLibrary.select(${JSON.stringify(id)})`);await settled();
    await clickOn('#pfbForkOpen');await until(()=>evaluate("document.activeElement&&document.activeElement.name==='id'"),5000,'idf');
    await type(newId);await sleep(150);
    const warn=await evaluate("document.querySelector('.pfb-fieldwarn')?.textContent||''");
    if(away)await evaluate("window.__spy.slow='^/api/prefabs$'");
    await key('Enter');
    let during=null;
    if(away){await sleep(500);await clickOn(`#pfbList .pfb-row[data-id="${away}"]`);await sleep(300);
      during={status:await evaluate("document.getElementById('pfbStatus').innerText"),form:await evaluate("!!document.getElementById('pfbForkForm')")};
      await shot(`rw-fork-pending-away-${newId}.png`,{x:0,y:0,width:1600,height:70});}
    await until(()=>evaluate("!window.JarvisPrefabLibrary.state.publication"),40000,'published');await settled();await sleep(400);
    await evaluate("window.__spy.slow=null");
    return {warn,during,selected:await evaluate("window.JarvisPrefabLibrary.state.selected"),
      notice:await evaluate("document.querySelector('.pfb-notice')?.innerText||null"),
      noticeTone:await evaluate("document.querySelector('.pfb-notice')?.className||null"),
      formError:await evaluate("document.querySelector('.pfb-form .pfb-error')?.innerText||null")};
  };
  out.steps.rwRefusedAway=await forkFrom('jarvis.checklist','qa.late','qa.c2');
  await shot('rw-fork-refused-away.png');
  await evaluate("window.JarvisPrefabLibrary.select('qa.c3')");await settled();await sleep(200);
  out.steps.rwRefusedAway.keptOnNextSelection=await evaluate("document.querySelector('.pfb-notice')?.innerText||null");
  await evaluate("document.querySelector('.pfb-notice .pfb-x')?.click()");await sleep(150);
  out.steps.rwPublishedAway=await forkFrom('jarvis.checklist','perso.checklist-rouge','qa.c3');
  await shot('rw-fork-published-away.png');
  await evaluate("document.querySelector('.pfb-notice .pfb-x')?.click()");await sleep(150);
  out.steps.rwBaseProtected=await forkFrom('jarvis.checklist','jarvis.mine',null);
  await shot('rw-fork-base-protected.png');
  await key('Escape');await sleep(150);
  out.steps.rwTakenLocal=await forkFrom('jarvis.checklist','perso.checklist-rouge',null);
  out.steps.rwTakenLocal.posts=await evaluate("window.__spy.calls.filter(c=>c.method==='POST'&&c.url==='/api/prefabs').length");
  await shot('rw-fork-id-taken.png');
  await key('Escape');await sleep(150);
  /* witness folded, chain tooltips */
  await evaluate("window.JarvisPrefabLibrary.select('jarvis.table')");await settled();await sleep(400);
  out.steps.rwWitness=await evaluate("(()=>{const w=document.querySelector('.pfb-witness');return w?{tag:w.tagName,open:w.open,visibleText:w.innerText,quote:document.querySelector('.pfb-quote blockquote').innerText}:null})()");
  await evaluate("document.querySelector('.pfb-versions').scrollIntoView({block:'start'})");await sleep(200);
  await shot('rw-base-edit-history.png');
  await evaluate("window.JarvisPrefabLibrary.select('qa.fork2')");await settled();await sleep(300);
  out.steps.rwChain=await evaluate("[...document.querySelectorAll('.pfb-chain .pfb-link')].map(b=>[b.textContent,b.title])");
  /* preview keyboard hint */
  await evaluate("window.JarvisPrefabLibrary.select('jarvis.checklist')");await settled();
  out.steps.rwStageHint=await evaluate("document.querySelector('.pfb-stagehint')?.innerText||null");
  out.steps.rwAfterFrame=await evaluate("(()=>{const f=document.querySelector('#pfbDetail iframe');const all=[...document.querySelectorAll('#prefabLibrary button:not([disabled]):not([tabindex=\"-1\"]),#prefabLibrary summary,#prefabLibrary iframe')];const n=all[all.indexOf(f)+1];return n?(n.id||n.textContent):null})()");
  await clickOn('#pfbStageClose');await sleep(300);
  out.steps.rwStageClose={hidden:await evaluate("document.getElementById('prefabLibrary').hidden"),focus:(await active())};
  await clickOn('#openPrefabs');await settled();
  /* headings: accessible names keep their case */
  const axh=(await send('Accessibility.getFullAXTree',{})).nodes.filter(n=>!n.ignored&&n.role&&n.role.value==='heading').map(n=>n.name&&n.name.value);
  out.steps.rwHeadings=axh;

  /* 9. agent prefab while closed -> reopen */
  await key('Escape');
  out.steps.agentSave=short(await core('POST','/v1/prefabs',{actor:'brain',candidate:cand({id:'qa.after',title:'Après réouverture'})}));
  await clickOn('#openPrefabs');await settled();
  out.steps.reopen={has:(await rows()).some(r=>r.id==='qa.after')};

  /* 10. a11y tree + tab order */
  const ax=(await send('Accessibility.getFullAXTree',{})).nodes.filter(n=>!n.ignored);
  const named=role=>ax.filter(n=>n.role&&n.role.value===role).map(n=>n.name&&n.name.value);
  out.steps.a11y={dialog:named('dialog'),region:named('region'),complementary:named('complementary'),group:named('group'),
    buttons:named('button').slice(0,30),unnamedButtons:named('button').filter(n=>!n).length,list:named('list'),
    textboxes:named('textbox'),searchbox:named('searchbox'),combobox:named('combobox')};
  await evaluate("document.getElementById('pfbSearch').focus()");
  const order=[];for(let i=0;i<14;i++){await key('Tab');order.push(await active())}
  out.steps.tabOrder=order.map(a=>a&&(a.label||a.id||a.text||a.tag));

  /* 11. one at a time */
  out.steps.oneAtATime={dockInert:await evaluate("!!document.querySelector('.dock').closest('[inert]')")};
  await evaluate("document.getElementById('openMcpInspector').click()");await sleep(500);
  out.steps.oneAtATime.programmaticMcp=await evaluate("({mcp:!document.getElementById('mcpInspector').hidden,pfb:!document.getElementById('prefabLibrary').hidden})");
  await evaluate("(()=>{const m=document.getElementById('mcpInspector');if(!m.hidden)document.getElementById('mcpInspector').querySelector('.tl-x,[aria-label^=Fermer]')?.click()})()");await sleep(300);
  await key('Escape');await sleep(200);
  await clickOn('#openWorkspace');await sleep(600);
  out.steps.oneAtATime.wspOpen={wsp:await evaluate("!document.getElementById('workspaceManager').hidden"),
    pfbBtnInert:await evaluate("!!document.getElementById('openPrefabs').closest('[inert]')")};
  await key('Escape');await sleep(300);
  out.steps.oneAtATime.afterEsc=await evaluate("({wsp:!document.getElementById('workspaceManager').hidden,pfb:!document.getElementById('prefabLibrary').hidden,mcp:!document.getElementById('mcpInspector').hidden})");

  /* 12. layout dock/top bar both themes, 1280 */
  for(const th of ['circuit-board','cosmos']){
    await theme(th);await send('Emulation.setDeviceMetricsOverride',{width:1280,height:720,deviceScaleFactor:1,mobile:false});await sleep(500);
    out.steps[`layout:${th}`]=await evaluate(`(()=>{const r=e=>{if(!e)return null;const b=e.getBoundingClientRect();return [Math.round(b.left),Math.round(b.top),Math.round(b.right),Math.round(b.bottom)]};
      const btns=[...document.querySelectorAll('.dock button')].map(b=>[b.id||b.dataset.panel,r(b)]);
      return {topbar:r(document.querySelector('.topbar')),dock:r(document.querySelector('.dock')),pills:r(document.getElementById('bgPills')),btns}})()`);
    await shot(`rw-qa-dock-${th}.png`);
    await send('Emulation.setDeviceMetricsOverride',{width:1280,height:600,deviceScaleFactor:1,mobile:false});await sleep(300);
    out.steps[`layoutShort:${th}`]=await evaluate(`(()=>{const b=[...document.querySelectorAll('.dock button')];const l=b[b.length-1].getBoundingClientRect();return {lastBottom:Math.round(l.bottom),vh:innerHeight}})()`);
    await shot(`rw-qa-dock-short-${th}.png`);
  }
  await theme('circuit-board');

  /* R3. detail in both themes, 1600 */
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  if(await evaluate("document.getElementById('prefabLibrary').hidden")){await clickOn('#openPrefabs');await settled()}
  for(const th of ['circuit-board','cosmos']){
    await theme(th);await evaluate("window.JarvisPrefabLibrary.select('qa.evil')");await settled();await sleep(500);
    out.steps[`rwOverflow1600:${th}`]=await evaluate("(()=>{const d=document.getElementById('pfbDetail');return {detail:[d.scrollWidth,d.clientWidth],page:[document.documentElement.scrollWidth,innerWidth]}})()");
    await shot(`rw-evil-1600-${th}.png`);
    await evaluate("window.JarvisPrefabLibrary.select('jarvis.table')");await settled();await sleep(400);
    await shot(`rw-table-1600-${th}.png`);
  }
  await theme('circuit-board');
  if(!await evaluate("document.getElementById('prefabLibrary').hidden"))await key('Escape');

  /* 13. narrow 420 */
  await send('Emulation.setDeviceMetricsOverride',{width:420,height:860,deviceScaleFactor:1,mobile:false});await sleep(300);
  await clickOn('#openPrefabs');await settled();
  await evaluate("window.JarvisPrefabLibrary.select('qa.evil')");await settled();await sleep(500);
  out.steps.narrow420=await evaluate("({page:[document.documentElement.scrollWidth,innerWidth],pfb:[document.getElementById('prefabLibrary').scrollWidth,document.getElementById('prefabLibrary').clientWidth],detail:[document.getElementById('pfbDetail').scrollWidth,document.getElementById('pfbDetail').clientWidth],header:document.querySelector('#prefabLibrary .tl-bar').scrollWidth})");
  await shot('rw-qa-narrow-420.png');
  await evaluate("window.JarvisPrefabLibrary.select('jarvis.table')");await settled();await sleep(400);
  out.steps.narrow420table=await evaluate("({page:[document.documentElement.scrollWidth,innerWidth],detail:[document.getElementById('pfbDetail').scrollWidth,document.getElementById('pfbDetail').clientWidth]})");
  await shot('rw-qa-narrow-420-table.png');
  await theme('cosmos');await sleep(300);await shot('rw-narrow-420-table-cosmos.png');await theme('circuit-board');
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});

  /* 14. deadline: list hangs */
  await evaluate("window.__spy.hang='^/api/prefabs\\\\?'");
  const t0=Date.now();await clickOn('#pfbRefresh');await sleep(3200);
  out.steps.deadlineWhile=await evaluate("document.getElementById('pfbStatus').innerText");
  await shot('rw-qa-deadline-waiting.png',{x:0,y:0,width:1600,height:70});
  await until(()=>evaluate("window.JarvisPrefabLibrary.state.list.status==='error'"),25000,'deadline');
  out.steps.deadline={afterMs:Date.now()-t0,code:await evaluate("window.JarvisPrefabLibrary.state.list.error.code"),
    status:await evaluate("document.getElementById('pfbStatus').innerText"),box:await evaluate("document.getElementById('pfbListState').innerText"),
    rowsStillShown:(await rows()).length};
  await shot('rw-qa-deadline-error.png');
  await evaluate("window.__spy.hang=null");
  out.errors=out.console.filter(c=>c.type==='error'||c.type==='exception');
  out.ok=true;
}catch(error){
  if(error==='done')out.ok=true;else{out.ok=false;out.error=String(error&&error.stack||error)}
}finally{
  writeFileSync(join(OUT,`rw-results-${PHASE}.json`),JSON.stringify(out,null,2));
  if(chrome)chrome.kill();await sleep(600);
  if(profile)try{rmSync(profile,{recursive:true,force:true})}catch(_){}
  process.exit(0);
}
