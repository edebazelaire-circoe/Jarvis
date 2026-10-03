/* Slice 08 — preuve navigateur de la bibliothèque des prefabs (vue `PFB`).

   Vrai Chrome `--headless=new`, profil jetable, piloté par CDP (harnais des
   Slices 03-06). Contre un Core et un Control Center isolés (18993/18994,
   racines de scratch neuves) :
   - ouvrir PFB au clic du dock ; noms accessibles (arbre d'accessibilité) ;
   - chercher « check » au clavier, ↓ puis Entrée sur la checklist ;
   - aperçu : vrai clic dans le cadre -> événement dans le journal local,
     RIEN dans l'anneau d'événements de Core ;
   - « Placer sur la scène » -> objet dans la scène de Core, origine `user` ;
   - « Forker » avec `jarvis.checklist-red` -> refus `base_protected` affiché ;
     puis `team.checklist-red`, accent rouge -> listé, badge Fork, parent ;
   - un prefab publié par Core au nom du cerveau (`POST /v1/prefabs`, acteur
     brain) apparaît après fermeture et réouverture ;
   - base modifiée (`jarvis.table` v2, faite par la porte réelle au lancement
     de Core, voir core_with_witness.py) : badge + mots cités ;
   - Échap, `/`, ↑ ↓, retour du focus ; thèmes Circuit et Cosmos ; étroit.

   Usage : node browser_probe.mjs <url du CC> <chrome.exe> <dossier de sortie> <url de Core> <fichier du jeton> */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT,CORE,TOKEN_FILE]=process.argv;
const profile=mkdtempSync(join(tmpdir(),'jarvis-s08-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

async function debuggerTarget(){
  const file=join(profile,'DevToolsActivePort');
  const deadline=Date.now()+60000;
  while(Date.now()<deadline){
    if(existsSync(file)){
      const port=readFileSync(file,'utf8').split('\n')[0].trim();
      try{const list=await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
        const page=list.find(t=>t.type==='page');if(page)return page}catch(_){/* Chrome démarre */}
    }
    await sleep(100);
  }
  throw new Error('Chrome debugger never came up');
}

const out={console:[],steps:{}};
try{
  const target=await debuggerTarget();
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refused'))});
  let id=0;const pending=new Map();const contexts=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled'){
      const text=msg.params.args.map(a=>a.value??a.description??'').join(' ');
      out.console.push({session:msg.sessionId?'frame':'page',type:msg.params.type,text:text.slice(0,300)});
    }
    if(msg.method==='Runtime.exceptionThrown')out.console.push({session:msg.sessionId?'frame':'page',type:'exception',
      text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,300)});
    if(msg.method==='Target.attachedToTarget'){
      const s=msg.params.sessionId;
      send('Runtime.enable',{},s).catch(()=>{});
      send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{});
    }
    if(msg.method==='Runtime.executionContextCreated')contexts.set(`${msg.sessionId||''}:${msg.params.context.id}`,
      {session:msg.sessionId||null,id:msg.params.context.id,main:!!(msg.params.context.auxData&&msg.params.context.auxData.isDefault)});
    if(msg.method==='Runtime.executionContextDestroyed')contexts.delete(`${msg.sessionId||''}:${msg.params.executionContextId}`);
    if(msg.method==='Runtime.executionContextsCleared')for(const k of [...contexts.keys()])if(k.startsWith(`${msg.sessionId||''}:`))contexts.delete(k);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;
    const timer=setTimeout(()=>{pending.delete(mine);ko(new Error(`CDP ${method} timed out`))},15000);
    pending.set(mine,{ok:(v)=>{clearTimeout(timer);ok(v)},ko:(e)=>{clearTimeout(timer);ko(e)}});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,100)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);
    return r.result.value;
  };
  const until=async(check,ms=20000,label)=>{const deadline=Date.now()+ms;let last;
    while(Date.now()<deadline){try{last=await check();if(last)return last}catch(_){}await sleep(150)}
    throw new Error('never true: '+(label||check.toString().slice(0,120)))};
  const inFrame=async(match,expression)=>{
    for(const ctx of [...contexts.values()]){
      if(!ctx.main)continue;
      try{const r=await send('Runtime.evaluate',{expression:`(${match})?(${expression}):null`,returnByValue:true,awaitPromise:true,contextId:ctx.id},ctx.session||undefined);
        if(r.exceptionDetails)continue;
        const value=r.result.value;
        if(value!==null&&value!==undefined)return value}catch(_){/* contexte parti */}
    }
    return null;
  };
  const box=(selector)=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;
    const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}})()`);
  const mouse=async(type,x,y,buttons)=>send('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:buttons??(type==='mouseReleased'?0:1),clickCount:1});
  const click=async(x,y)=>{await mouse('mouseMoved',x,y,0);await mouse('mousePressed',x,y);await mouse('mouseReleased',x,y);await sleep(60)};
  const clickOn=async(selector)=>{await until(()=>box(selector),8000,selector);
    await evaluate(`document.querySelector(${JSON.stringify(selector)}).scrollIntoView({block:'center'})`);await sleep(120);
    const b=await box(selector);await click(b.cx,b.cy);return b};
  const clickField=async(selector)=>clickOn(selector);
  const KEYS={Escape:27,Enter:13,ArrowDown:40,ArrowUp:38,Tab:9,'/':191,Backspace:8,Home:36,End:35};
  const key=async(k,modifiers)=>{const extra=modifiers?{modifiers}:{};const vk=KEYS[k]||0;
    const text=k.length===1?k:k==='Enter'?String.fromCharCode(13):null;
    await send('Input.dispatchKeyEvent',{type:text?'keyDown':'rawKeyDown',key:k,code:k==='/'?'Slash':k,windowsVirtualKeyCode:vk,...(text?{text}:{}),...extra});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:k,code:k,windowsVirtualKeyCode:vk,...extra});await sleep(90)};
  const type=async(text)=>{await send('Input.insertText',{text});await sleep(60)};
  const shot=async(name,clip)=>{const r=await send('Page.captureScreenshot',clip?{format:'png',clip:{...clip,scale:1}}:{format:'png'});
    writeFileSync(join(OUT,name),Buffer.from(r.data,'base64'));return name};
  const theme=(name)=>evaluate(`(JarvisThemeAPI.activate(${JSON.stringify(name)}),document.documentElement.dataset.jarvisTheme)`);
  const active=()=>evaluate(`(()=>{const a=document.activeElement;return a?{tag:a.tagName,id:a.id||null,text:(a.textContent||'').trim().slice(0,60),
    label:a.getAttribute('aria-label')}:null})()`);
  const rows=()=>evaluate(`[...document.querySelectorAll('#pfbList .pfb-row')].map(r=>({id:r.dataset.id,selected:r.classList.contains('is-selected'),
    badges:[...r.querySelectorAll('.pfb-badge')].map(b=>b.textContent),parent:r.querySelector('.pfb-parent')?.textContent||null}))`);
  const settled=()=>until(()=>evaluate(`(()=>{const L=window.JarvisPrefabLibrary;if(!L)return false;const S=L.state;
    return S.list.status==='ready'&&!L.library.waiting()})()`),20000,'library settled');
  const token=readFileSync(TOKEN_FILE,'utf8').trim();
  const core=async(method,path,body)=>{const r=await fetch(`${CORE}${path}`,{method,headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},
    body:body?JSON.stringify(body):undefined});return {status:r.status,body:await r.json()}};

  await send('Page.enable');await send('Runtime.enable');await send('Accessibility.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate("!!window.JarvisPrefabLibrary&&!!window.JarvisThemeAPI&&!!window.JarvisPrefabHost"),30000,'page');
  await theme('circuit-board');await sleep(300);
  out.steps.dockCircuit=await shot('dock-circuit.png',await (async()=>{const b=await box('.dock');return {x:b.x-12,y:b.y-12,width:b.w+24,height:b.h+24}})());

  /* 1. Ouvrir au clic du dock. */
  out.steps.coreBaseEdit=(await core('GET','/v1/prefabs/jarvis.table')).body.history.map(h=>[h.version,h.origin,h.base_edit&&h.base_edit.user_request]);
  await clickOn('#openPrefabs');
  await settled();await sleep(300);
  out.steps.opened={expanded:await evaluate("document.getElementById('openPrefabs').getAttribute('aria-expanded')"),
    hidden:await evaluate("document.getElementById('prefabLibrary').hidden"),focus:await active(),rows:await rows(),
    inertDock:await evaluate("document.querySelector('.dock').closest('[inert]')!==null")};
  out.steps.shotOpen=await shot('library-open.png');

  /* Noms accessibles : arbre d'accessibilité de Chrome. */
  const ax=(await send('Accessibility.getFullAXTree',{})).nodes;
  const named=role=>ax.filter(n=>n.role&&n.role.value===role&&!n.ignored).map(n=>n.name&&n.name.value).filter(Boolean);
  out.steps.a11y={dialog:named('dialog'),searchbox:named('searchbox'),combobox:named('combobox'),
    buttons:named('button').filter(n=>!/^\d/.test(n)).slice(0,40),lists:named('list'),regions:named('region'),
    complementary:named('complementary'),group:named('group')};

  /* 2. Chercher « check » au clavier, ↓ puis Entrée. */
  await type('check');
  await until(async()=>(await rows()).length&&(await evaluate("window.JarvisPrefabLibrary.state.query"))==='check',8000,'query sent');
  await settled();await sleep(200);
  out.steps.search={rows:await rows()};
  out.steps.shotSearch=await shot('search-check.png');
  await key('ArrowDown');
  out.steps.afterArrow=await active();
  await key('Enter');
  await until(()=>evaluate("window.JarvisPrefabLibrary.state.selected==='jarvis.checklist'"),5000,'checklist selected');
  /* L'aperçu : un cadre dont le document est la checklist. */
  const MAIN="document.getElementById('ck')&&document.querySelectorAll('.ck-item').length>0";
  await until(()=>inFrame(MAIN,"document.querySelectorAll('.ck-item').length"),20000,'preview frame ready');
  await sleep(700);
  out.steps.preview={frames:await evaluate("document.querySelectorAll('#pfbDetail iframe').length"),
    sandbox:await evaluate("document.querySelector('#pfbDetail iframe').getAttribute('sandbox')"),
    items:await inFrame(MAIN,"[...document.querySelectorAll('.ck-item .ck-label')].map(n=>n.textContent)"),
    guard:await evaluate("document.querySelector('.pfb-guardzone .pfb-guard')?.innerText||null"),
    baseEditButtons:await evaluate("[...document.querySelectorAll('#prefabLibrary button')].filter(b=>/modifier|éditer|edit/i.test(b.textContent)).map(b=>b.textContent)")};
  out.steps.shotDetail=await shot('checklist-detail.png');

  /* 3. Vrai clic dans le cadre : journal local, rien chez Core. */
  const ringBefore=(await core('GET','/v1/prefabs/events?limit=50')).body.events.length;
  const frameBox=await box('#pfbDetail iframe');
  const rowPt=await inFrame(MAIN,"(()=>{const r=document.querySelectorAll('.ck-item')[1].getBoundingClientRect();return {x:r.x+20,y:r.y+r.height/2}})()");
  await click(frameBox.x+rowPt.x,frameBox.y+rowPt.y);
  await until(()=>evaluate("document.querySelectorAll('.pfb-logs li').length>0"),5000,'preview event logged');
  await sleep(300);
  out.steps.previewEvent={log:await evaluate("[...document.querySelectorAll('.pfb-logs li')].map(li=>li.innerText.replace(/\\s+/g,' '))"),
    ringBefore,ringAfter:(await core('GET','/v1/prefabs/events?limit=50')).body.events.length};
  out.steps.shotPreviewEvent=await shot('preview-event-log.png',await (async()=>{const b=await box('.pfb-preview');return {x:b.x-10,y:b.y-10,width:b.w+20,height:b.h+20}})());

  /* 4. Placer sur la scène. */
  await clickOn('#pfbPlace');
  await until(()=>evaluate("!!document.querySelector('.pfb-placed')"),10000,'placed');
  const placedId=await evaluate("document.querySelector('.pfb-placed code').textContent");
  const snap=(await core('GET','/v1/scene/snapshot')).body.snapshot;
  const obj=snap.objects.find(o=>o.object_id===placedId);
  out.steps.place={objectId:placedId,origin:obj&&obj.origin,kind:obj&&obj.kind,prefab:obj&&obj.payload.prefab&&[obj.payload.prefab.id,obj.payload.prefab.version,
    obj.payload.prefab.data.items.length],text:await evaluate("document.querySelector('.pfb-placed').innerText")};
  out.steps.shotPlaced=await shot('placed.png',await (async()=>{const b=await box('.pfb-actions');return {x:b.x-10,y:b.y-10,width:b.w+20,height:b.h+20}})());

  /* 5. Fork : d'abord un id réservé (refus de Core affiché), puis team.checklist-red rouge. */
  await clickOn('#pfbForkOpen');
  await until(()=>evaluate("document.activeElement&&document.activeElement.name==='id'"),5000,'id field focused');
  await type('jarvis.checklist-red');
  out.steps.forkWarn=await evaluate("document.querySelector('.pfb-fieldwarn').textContent");
  await key('Enter');
  await until(()=>evaluate("!!document.querySelector('.pfb-form .pfb-error')"),10000,'fork refused');
  await evaluate("document.querySelector('.pfb-form').scrollIntoView({block:'start'})");await sleep(150);
  out.steps.forkRefused={text:await evaluate("document.querySelector('.pfb-form .pfb-error').innerText"),
    invalid:await evaluate("document.querySelector('.pfb-form [name=id]').getAttribute('aria-invalid')"),focus:await active()};
  out.steps.shotForkRefused=await shot('fork-base-protected.png',await (async()=>{const b=await box('.pfb-form');return {x:b.x-10,y:Math.max(0,b.y-10),width:b.w+20,height:Math.min(1000,b.h+20)}})());
  await evaluate("(()=>{const f=document.querySelector('.pfb-form');f.querySelector('[name=id]').value='';f.querySelector('[name=title]').value='';})()");
  await clickField('.pfb-form [name=id]');
  await type('team.checklist-red');
  await clickField('.pfb-form [name=title]');
  await type('Checklist rouge');
  await clickField('.pfb-form [name=description]');
  await key('End');await type(' Variante rouge pour l’équipe.');
  await evaluate("(()=>{const t=document.querySelector('.pfb-form [data-def=accent]');t.value='';t.focus()})()");
  await type('#ff4d5e');
  await evaluate("document.querySelector('.pfb-form').scrollIntoView({block:'start'})");await sleep(150);
  out.steps.shotForkForm=await shot('fork-form.png',await (async()=>{const b=await box('.pfb-form');return {x:b.x-10,y:Math.max(0,b.y-10),width:b.w+20,height:Math.min(1000,b.h+20)}})());
  await clickOn('.pfb-form button[type=submit]');
  await until(()=>evaluate("window.JarvisPrefabLibrary.state.selected==='team.checklist-red'&&!window.JarvisPrefabLibrary.state.fork"),15000,'fork published');
  await settled();
  await until(()=>inFrame("document.getElementById('ck')&&getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim()==='#ff4d5e'","true"),20000,'red preview');
  await sleep(600);
  const pub=(await core('GET','/v1/prefabs/team.checklist-red')).body;
  out.steps.fork={rows:await rows(),notice:await evaluate("document.querySelector('.pfb-notice')?.innerText||null"),
    chain:await evaluate("document.querySelector('.pfb-chain')?.innerText||null"),
    core:pub.history.map(h=>[h.version,h.origin,h.derived_from,h.created_by]),focus:await active(),
    frames:await evaluate("document.querySelectorAll('#pfbDetail iframe').length"),
    accent:await inFrame("document.getElementById('ck')&&getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim()==='#ff4d5e'","'#ff4d5e'")};
  out.steps.shotFork=await shot('fork-listed.png');

  /* Lien de parent : ouvre la base. */
  await clickOn('.pfb-chain .pfb-link');
  await until(()=>evaluate("window.JarvisPrefabLibrary.state.selected==='jarvis.checklist'"),5000,'parent link');
  out.steps.parentLink=await active();

  /* 6. Un prefab publié par Core au nom du cerveau apparaît à la réouverture. */
  const src=(await core('GET','/v1/prefabs/jarvis.window/1?include_source=1')).body;
  const brainManifest={...src.manifest,id:'lab.brief-window',version:1,title:'Fenêtre de brief',description:'Publiée par JARVIS pendant que la vue était fermée.',aliases:[]};
  await key('Escape');
  out.steps.closed={hidden:await evaluate("document.getElementById('prefabLibrary').hidden"),focus:await active()};
  out.steps.brainSave=(await core('POST','/v1/prefabs',{actor:'brain',candidate:{manifest:brainManifest,...src.files}})).status;
  await key('Enter');/* le focus est revenu sur PFB : Entrée rouvre */
  await settled();await sleep(300);
  /* La recherche « check » est gardée d'une ouverture à l'autre (la case la montre) : `/` puis effacer. */
  out.steps.reopenedWithQuery={query:await evaluate("document.getElementById('pfbSearch').value"),rows:(await rows()).map(r=>r.id)};
  await evaluate("document.getElementById('pfbSearch').blur()");
  await key('/');
  out.steps.slashFocus=await active();
  await key('Backspace');
  await until(()=>evaluate("window.JarvisPrefabLibrary.state.query===''"),5000,'query cleared');
  await settled();await sleep(300);
  out.steps.reopened={rows:(await rows()).map(r=>[r.id,r.badges.join('|')])};
  out.steps.shotReopened=await shot('brain-prefab-after-reopen.png');

  /* 7. Base modifiée : filtre, badge, mots cités. */
  await clickOn('#pfbKinds [data-kind="base_edited"]');
  await sleep(200);
  out.steps.editedFilter=await rows();
  await clickOn('#pfbList .pfb-row');
  await until(()=>evaluate("!!document.querySelector('.pfb-quote')"),10000,'quote');
  await evaluate("document.querySelector('.pfb-versions').scrollIntoView({block:'start'})");await sleep(300);
  out.steps.baseEdited={guard:await evaluate("document.querySelector('.pfb-guardzone .pfb-guard').innerText"),
    quote:await evaluate("document.querySelector('.pfb-quote').innerText"),
    versions:await evaluate("[...document.querySelectorAll('.pfb-vlist>li .pfb-vline')].map(n=>n.innerText.replace(/\\s+/g,' '))")};
  out.steps.shotBaseEdited=await shot('base-edited-history.png');
  await evaluate("document.getElementById('pfbDetail').scrollTop=0");await sleep(200);
  out.steps.shotBaseEditedTop=await shot('base-edited-top.png');

  /* 8. Clavier dans la liste : ↑ ↓ sélectionnent. */
  await clickOn('#pfbKinds [data-kind="all"]');await sleep(200);
  const first=await box('#pfbList .pfb-row');await click(first.cx,first.cy);
  await key('ArrowDown');await key('ArrowDown');
  const afterDown=await evaluate("window.JarvisPrefabLibrary.state.selected");
  await key('ArrowUp');
  out.steps.listKeys={afterDown,afterUp:await evaluate("window.JarvisPrefabLibrary.state.selected"),focus:await active()};

  /* 9. Cosmos + étroit. */
  await key('Escape');
  await theme('cosmos');await sleep(500);
  out.steps.dockCosmos=await shot('dock-cosmos.png',{x:1000,y:0,width:600,height:80});
  out.steps.cosmosDock=await evaluate("(()=>{const b=document.getElementById('openPrefabs');const r=b.getBoundingClientRect();return {svg:!!b.querySelector('svg'),label:b.getAttribute('aria-label'),x:r.x,y:r.y}})()");
  await clickOn('#openPrefabs');await settled();
  await clickOn('#pfbList .pfb-row[data-id="team.checklist-red"]');
  await until(()=>inFrame("document.getElementById('ck')&&getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim()==='#ff4d5e'","true"),20000,'cosmos red preview');
  await sleep(600);
  out.steps.shotCosmos=await shot('library-cosmos.png');
  await send('Emulation.setDeviceMetricsOverride',{width:760,height:1000,deviceScaleFactor:1,mobile:false});await sleep(500);
  out.steps.narrow=await evaluate("({scrollW:document.getElementById('prefabLibrary').scrollWidth,clientW:document.getElementById('prefabLibrary').clientWidth})");
  out.steps.shotNarrow=await shot('library-narrow.png');
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await key('Escape');await theme('circuit-board');

  out.errors=out.console.filter(c=>c.type==='error'||c.type==='exception');
  out.ok=true;
}catch(error){
  out.ok=false;out.error=String(error&&error.stack||error);
}finally{
  writeFileSync(join(OUT,'browser-results.json'),JSON.stringify(out,null,2));
  chrome.kill();
  await sleep(500);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome libère son profil */}
  process.exit(out.ok?0:1);
}
