/* Harnais CDP pour `test_control_center_presentation_rail_browser.py` (rail des presentations).

   Chrome sans tete, la page SERVIE (composee comme `ControlCenter.index`), une taille imposee. Le relais `/api/presentation-studio/*` est remplace,
   dans la page et avant tout script, par un double en memoire (`window.__rail`) : c'est l'interface qui est mesuree ici ; la chaine reelle
   jusqu'a Core est prouvee par `test_presentation_studio_rail.py` (vrai Core) et par la verification en bac a sable.

   Slice 07 (rail actif, D10) : la route bornee des apercus (`/api/artifacts/{id}/payload`) est doublee aussi, au seul endroit ou la page la
   lit (`img.src`) : une image SVG en memoire tient lieu du PNG que Core servirait ; un id sans image rend une image illisible (le repli est
   ainsi mesure). La chaine reelle (vrai rendu, vrai relais) est prouvee par `test_presentation_rail_e2e_browser.py`.

   Usage : node _presentation_rail_browser.mjs <page.html> <chrome.exe> [dossier des captures]
   Sortie : un objet JSON `{scenario: lectures}` sur la sortie standard. */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit,killChrome,assertSafeTarget} from './_cdp_profile.mjs';

const [,,PAGE,CHROME,SHOTS]=process.argv;
/* Jamais le JARVIS vivant : ni ses ports, ni son dossier d'exécution (QA S09, `_cdp_profile.mjs`). */
assertSafeTarget(PAGE,null);

const FAKE=`(()=>{
  /* Chaque chargement repart d'une page vierge (le rail et le Chat memorisent leur etat) ; \`window.name='keep'\` garde le stockage d'un rechargement. */
  if(window.name!=='keep'){try{localStorage.clear()}catch(_){/* sans stockage */}}
  const PID=n=>'pst_'+String(n).padStart(32,'0');
  const rows=[
    {presentation_id:PID(1),title:'Lancement produit automne',active_variant_id:'psv_'+'1'.repeat(32),variant_count:2,engine:'remotion',revision:1,updated_at:'2026-10-10T10:00:00Z',hidden:false,archived:false,work:{state:'working',label:'presentation_edit',age_s:3}},
    {presentation_id:PID(2),title:'Bilan',active_variant_id:'psv_'+'2'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T09:00:00Z',hidden:false,archived:false,work:{state:'done',label:'',age_s:null}},
    {presentation_id:PID(3),title:'Roadmap',active_variant_id:'psv_'+'3'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T08:00:00Z',hidden:false,archived:false,work:{state:'problem',label:'presentation_edit',age_s:30,code:'presentation_studio_storage_io',message:'disque plein'}},
    {presentation_id:PID(4),title:'Brouillon cache',active_variant_id:'psv_'+'4'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T07:00:00Z',hidden:true,archived:false,work:{state:'done',label:'',age_s:null}},
    {presentation_id:PID(5),title:'Ancienne',active_variant_id:'psv_'+'5'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T06:00:00Z',hidden:false,archived:true,work:{state:'done',label:'',age_s:null}},
  ];
  /* What Core sends since Slice 07 (D10): type, preview (none here), unreviewed (none here). */
  rows.forEach(r=>{r.type={engine:r.engine};r.preview=null;r.unreviewed=null});
  if(location.hash==='#calm')rows.forEach(r=>{r.work={state:'done',label:'',age_s:null}});
  const STILL='jart_'+'a'.repeat(32),STILL2='jart_'+'b'.repeat(32),SHOT='jart_'+'c'.repeat(32);
  if(location.hash==='#cards'){
    /* Every state at once: working + preview, unreviewed + preview, problem, done (Slidecar, no render), unknown (no work state). */
    rows[0].preview={artifact_id:STILL,kind:'presentation_still',width:1280,height:720};
    rows[1].unreviewed={since:'2026-10-16T09:00:00Z',label:'presentation_edit'};rows[1].preview={artifact_id:STILL2,kind:'presentation_still',width:1280,height:720};
    rows[3].hidden=false;rows[3].engine='slidecar';rows[3].type={engine:'slidecar'};rows[3].title='Notes de recherche';
    rows.push({presentation_id:PID(6),title:'Architecture technique',active_variant_id:'psv_'+'6'.repeat(32),variant_count:3,engine:'remotion',type:{engine:'remotion'},revision:2,
      updated_at:'2026-10-09T08:00:00Z',hidden:false,archived:false,preview:null,unreviewed:null});
  }
  const slide=(a,b,title)=>'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="'+a+'"/><stop offset="1" stop-color="'+b+'"/></linearGradient></defs><rect width="1280" height="720" fill="url(#g)"/><text x="96" y="380" font-family="Segoe UI,sans-serif" font-size="120" font-weight="700" fill="#fff">'+title+'</text><rect x="96" y="430" width="420" height="16" rx="8" fill="#ffffff88"/></svg>';
  const rail=window.__rail={rows,calls:[],reports:[],ui:{seq:0,request:null,reported:null},down:false,refuse:null,playing:null,commands:[],payloads:[],purges:[],purgeRefuse:null,wsDeletes:[],wsDependents:[],
    previews:{[STILL]:slide('#1d2b64','#f8cdda','JARVIS'),[STILL2]:slide('#0f2027','#2c5364','Bilan'),[SHOT]:slide('#134e5e','#71b280','Capture')},boardArtifacts:{}};
  /* Stage B: the Board-linked artifacts the workspace route returns, per Board (only with #cards; empty Boards otherwise). */
  if(location.hash==='#cards')rail.boardArtifacts.b=[
    {artifact_id:SHOT,kind:'screenshot',state:'complete',mime_type:'image/png',has_payload:true,created_at:'2026-10-16T08:00:00Z'},
    {artifact_id:'jart_'+'d'.repeat(32),kind:'upload',state:'complete',mime_type:'application/vnd.openxmlformats-officedocument.presentationml.presentation',preview:'Roadmap Q4.pptx',has_payload:true,created_at:'2026-10-15T08:00:00Z'},
    {artifact_id:'jart_'+'e'.repeat(32),kind:'link',state:'complete',preview:'https://docs.google.com/presentation/d/abc/edit',has_payload:false,created_at:'2026-10-14T08:00:00Z'},
    {artifact_id:'jart_'+'f'.repeat(32),kind:'upload',state:'pending',mime_type:'video/mp4',preview:'demo.mp4',has_payload:true,created_at:'2026-10-16T10:00:00Z'},
    {artifact_id:'jart_'+'0'.repeat(31)+'9',kind:'upload',state:'failed',mime_type:'application/pdf',preview:'contrat.pdf',has_payload:true,created_at:'2026-10-13T08:00:00Z'}];
  /* Double of the bounded payload route, where the page reads it: an <img> src. */
  const srcDesc=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');
  Object.defineProperty(HTMLImageElement.prototype,'src',{configurable:true,enumerable:true,get(){return srcDesc.get.call(this)},set(v){
    const m=String(v).match(/^\\/api\\/artifacts\\/([^/]+)\\/payload$/);
    if(m){rail.payloads.push(m[1]);const svg=rail.previews[m[1]];v=svg?'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(svg):'data:image/png;base64,AAAA';}
    srcDesc.set.call(this,v)}});
  const json=(status,obj)=>new Response(JSON.stringify(obj),{status,headers:{'Content-Type':'application/json'}});
  const sorted=()=>[...rows].sort((a,b)=>(a.archived-b.archived)||(a.hidden-b.hidden));
  window.fetch=async(url,init)=>{
    const u=String(url),method=(init&&init.method)||'GET';
    /* Suppression definitive d'un Artifact (Core : DELETE /v1/artifacts/{id}) : un derive demande \`cascade=true\`. */
    let wd=u.match(/^\\/api\\/artifacts\\/([^/?]+)(\\?cascade=true)?$/);
    if(wd&&method==='DELETE'){
      rail.wsDeletes.push(method+' '+u);
      if(rail.wsRefuse)return json(rail.wsRefuse.status,{error:{code:rail.wsRefuse.code,message:'refus'}});
      if(rail.wsDependents.includes(wd[1])&&!wd[2])return json(409,{error:{code:'artifact_has_dependents',message:'a des derives'}});
      let found=false;for(const b of Object.keys(rail.boardArtifacts)){const n=rail.boardArtifacts[b].length;rail.boardArtifacts[b]=rail.boardArtifacts[b].filter(a=>a.artifact_id!==wd[1]);found=found||n!==rail.boardArtifacts[b].length}
      if(!found)return json(404,{error:{code:'artifact_not_found',message:'inconnu'}});
      return json(200,{artifact_id:wd[1],deleted:[wd[1]],cascade:!!wd[2],orphan_folders:[]});
    }
    if(u.startsWith('/api/workspace/artifacts?')){
      const board=new URL('http://x'+u).searchParams.get('board_id');rail.calls.push({method,url:u,body:null});
      if(rail.down)throw new TypeError('Failed to fetch');
      return json(200,{artifacts:rail.boardArtifacts[board]||[],scope:{board_id:board},next_cursor:null});
    }
    if(!u.startsWith('/api/presentation-studio'))throw new TypeError('Failed to fetch');
    rail.calls.push({method,url:u,body:init&&init.body||null});
    if(rail.down)throw new TypeError('Failed to fetch');
    if(u==='/api/presentation-studio/rail'&&method==='GET')
      return json(200,{presentations:sorted(),problems:[],work_revision:1,ui:rail.ui,playing:rail.playing});
    if(u==='/api/presentation-studio/rail/purge-plan'&&method==='POST'){
      const b=JSON.parse(init.body);rail.purges.push({step:'plan',body:b});
      if(rail.purgeRefuse)return json(rail.purgeRefuse.status,{error:{code:rail.purgeRefuse.code,message:'refus'}});
      const row=rows.find(r=>r.presentation_id===(b.presentation_ids||[])[0]);
      if(!row)return json(404,{error:{code:'presentation_studio_unknown_presentation',message:'no'}});
      if(!row.archived)return json(409,{error:{code:'presentation_studio_not_archived',message:'pas archivee'}});
      return json(200,{plan:{presentations:[{presentation_id:row.presentation_id,title:row.title}],count:1,irreversible:true},confirmation:'ppk_'+row.presentation_id.slice(4,24),expires_in_s:600});
    }
    if(u==='/api/presentation-studio/rail/purge'&&method==='POST'){
      const b=JSON.parse(init.body);rail.purges.push({step:'purge',body:b});
      if(b.confirmed!==true||!/^ppk_/.test(b.confirmation||''))return json(400,{error:{code:'presentation_studio_confirmation_required',message:'jeton'}});
      const gone=rows.filter(r=>(b.presentation_ids||[]).includes(r.presentation_id)&&r.archived);
      for(const g of gone)rows.splice(rows.indexOf(g),1);
      return json(200,{purged:gone.map(g=>g.presentation_id),count:gone.length,deleted:{presentations:gone.length},backup:'backups/purge-presentations-x',failed:[],complete:true});
    }
    if(u==='/api/presentation-studio/rail/display-state'&&method==='POST'){rail.reports.push(JSON.parse(init.body));return json(200,{seq:rail.ui.seq});}
    let m=u.match(/^\\/api\\/presentation-studio\\/presentations\\/(pst_[0-9a-f]{32})\\/rail$/);
    if(m&&method==='POST'){
      const body=JSON.parse(init.body);const row=rows.find(r=>r.presentation_id===m[1]);
      if(rail.refuse)return json(rail.refuse.status,{error:{code:rail.refuse.code,message:rail.refuse.message}});
      if(!row)return json(404,{error:{code:'presentation_studio_unknown_presentation',message:'no'}});
      if(body.action==='hide')row.hidden=true;else if(body.action==='show')row.hidden=false;
      else if(body.action==='archive')row.archived=true;else if(body.action==='restore')row.archived=false;
      else if(body.action==='rename')row.title=body.title;
      else if(body.action==='acknowledge')row.work={state:'done',label:'',age_s:null};
      else if(body.action==='review')row.unreviewed=null;
      return json(200,{presentation_id:row.presentation_id,action:body.action,changed:true,hidden:row.hidden,archived:row.archived});
    }
    m=u.match(/^\\/api\\/presentation-studio\\/presentations\\/(pst_[0-9a-f]{32})$/);
    if(m&&method==='GET'){
      const row=rows.find(r=>r.presentation_id===m[1]);if(!row)return json(404,{error:{code:'presentation_studio_unknown_presentation',message:'no'}});
      const scenes=['Accroche','Chiffres','Appel'].map((t,i)=>({scene_id:'pss_00000000000'+(i+1),title:t,prefab:{id:'jarvis.fake',version:1},props:{},data:{}}));
      return json(200,{presentation:{presentation_id:row.presentation_id,title:row.title,active_variant_id:row.active_variant_id,revision:1},
        variants:[{variant_id:row.active_variant_id,variant_number:2,revision:rail.variantRevision||3,title:'v',scenes}]});
    }
    if(u.startsWith('/api/presentation-studio/playback/')&&method==='POST'){
      const verb=u.split('/').pop();rail.commands.push({verb,body:JSON.parse(init.body)});
      return json(200,{status:'applied',state:{running:true,phase:'playing',presentation_id:JSON.parse(init.body).presentation_id||null}});
    }
    return json(404,{error:{code:'not_found',message:u}});
  };
})()`;

const READ=`(()=>{
  const box=el=>{if(!el)return null;const r=el.getBoundingClientRect();if(!r.width&&!r.height)return null;return {l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height}};
  const q=s=>document.querySelector(s),qa=s=>[...document.querySelectorAll(s)];
  const host=q('#presentationRail');
  const wsItems=qa('#presentationRail .jvr-ws .jvr-item').map(b=>({id:b.dataset.id,ws:b.dataset.ws,state:b.dataset.state,name:b.querySelector('.jvr-name').textContent,
    meta:(b.querySelector('.jvr-meta')||{}).textContent||'',stateText:(b.querySelector('.jvr-state')||{}).textContent||'',
    thumb:(t=>({kind:t.dataset.kind,badge:(t.querySelector('.jvr-badge')||{}).textContent||'',img:(i=>i?{ok:i.complete&&i.naturalWidth>0}:null)(t.querySelector('img'))}))(b.querySelector('.jvr-thumb')),
    dot:getComputedStyle(b.querySelector('.jvr-dot')).backgroundColor}));
  const items=qa('#presentationRail .jvr-item:not([data-ws])').map(b=>({id:b.dataset.id,state:b.dataset.state,open:b.dataset.open,dim:b.dataset.dim||null,name:b.querySelector('.jvr-name').textContent,
    full:b.title,label:b.getAttribute('aria-label'),dot:getComputedStyle(b.querySelector('.jvr-dot')).backgroundColor,dotAnim:getComputedStyle(b.querySelector('.jvr-dot')).animationName,
    thumb:(t=>({kind:t.dataset.kind,badge:(t.querySelector('.jvr-badge')||{}).textContent||'',img:(i=>i?{ok:i.complete&&i.naturalWidth>0,payload:/^data:image\\/svg/.test(i.getAttribute('src')||'')}:null)(t.querySelector('img'))}))(b.querySelector('.jvr-thumb')),
    stateText:(b.querySelector('.jvr-state')||{}).textContent||'',when:(b.querySelector('.jvr-when')||{}).textContent||'',meta:(b.querySelector('.jvr-meta')||{}).textContent||'',
    dotShape:getComputedStyle(b.querySelector('.jvr-dot')).clipPath,dotMask:(cs=>cs.maskImage||cs.webkitMaskImage||'none')(getComputedStyle(b.querySelector('.jvr-dot'))),dotBorder:getComputedStyle(b.querySelector('.jvr-dot')).borderTopStyle,
    more:!!b.parentElement.querySelector('.jvr-more'),del:!!b.parentElement.querySelector('.jvr-del'),
    texts:[...b.querySelectorAll('.jvr-body *')].map(n=>n.className)}));
  const win=q('#jvPresWindow');
  return {visible:!!host&&!host.hidden,box:box(host),items,
    folds:qa('#presentationRail .jvr-fold').map(b=>b.textContent.trim()),
    note:(q('#presentationRail .jvr-note')||{}).textContent||'',noteHidden:!!(q('#presentationRail .jvr-note')||{}).hidden,
    menu:(()=>{const m=q('.jvr-menu');return m&&!m.hidden?{items:[...m.querySelectorAll('button')].map(b=>({act:b.dataset.act,text:b.textContent,disabled:b.getAttribute('aria-disabled')})),head:(m.querySelector('.jvr-mhead')||{}).textContent,box:box(m)}:null})(),
    confirm:(()=>{const c=q('#confirmBack');return c&&!c.hidden?{title:q('#confirmTitle').textContent,text:[...c.querySelectorAll('#confirmBody li')].map(l=>l.textContent).join(' '),
      buttons:[q('#confirmCancel').textContent,q('#confirmGo').textContent],danger:q('#confirmDialog').classList.contains('danger')}:null})(),
    tab:(t=>t?{expanded:t.getAttribute('aria-expanded'),label:t.getAttribute('aria-label'),box:box(t),mark:(m=>m&&!m.hidden?m.dataset.state||null:null)(t.querySelector('.jvr-urgent'))}:null)(q('#presentationRailTab')),
    chatTab:(t=>t?{expanded:t.getAttribute('aria-expanded'),label:t.getAttribute('aria-label'),box:box(t),text:t.textContent.trim()}:null)(q('#chatTab')),
    railDock:box(q('#railDock')),chatPanel:(p=>p&&p.classList.contains('open')?box(p):null)(q('#chatPanel')),
    archBtn:(b=>b&&!b.hidden?{text:b.textContent,pressed:b.getAttribute('aria-pressed')}:null)(q('#presentationRail .jvr-arch')),
    archived:qa('#presentationRail [data-section=archived] .jvr-item').map(b=>b.querySelector('.jvr-name').textContent),
    archivedHead:((q('#presentationRail [data-section=archived] .jvr-fold')||{}).textContent)||null,
    dialog:(()=>{const d=q('.jvr-dialog-back');return d&&!d.hidden?{title:(d.querySelector('h2')||{}).textContent,text:(d.querySelector('p')||{}).textContent,buttons:[...d.querySelectorAll('button')].map(b=>b.textContent),input:(d.querySelector('input')||{}).value||null}:null})(),
    window:win&&!win.hidden?{box:box(win),title:win.querySelector('.jvw-title').textContent,chip:win.querySelector('.jvw-chip').textContent,pips:win.querySelectorAll('.jvw-pip').length,
      count:win.querySelector('.jvw-count').textContent,veil:win.querySelector('.jvw-veil').hidden?'':win.querySelector('.jvw-veil strong').textContent,
      dot:getComputedStyle(win.querySelector('.jvw-dot')).backgroundColor,buttons:[...win.querySelectorAll('.jvw-bar button')].map(b=>b.textContent)}:null,
    studioClass:document.documentElement.classList.contains('jvr-studio'),
    density:host&&host.dataset.density,
    explorer:box(q('#jvStudioExplorer')),
    payloads:window.__rail.payloads.slice(),wsItems,wsHead:(f=>f?f.textContent.trim():null)(q('#presentationRail .jvr-ws .jvr-fold')),
    wsCalls:window.__rail.calls.filter(c=>c.url.startsWith('/api/workspace/')).map(c=>new URL('http://x'+c.url).searchParams.get('board_id')),
    api:window.JarvisPresentationRail?window.JarvisPresentationRail.state():null,
    wsDeletes:window.__rail.wsDeletes.slice(),purges:window.__rail.purges.map(p=>p.step+' '+JSON.stringify(p.body)),
    store:(()=>{try{return JSON.parse(localStorage.getItem('jarvis.presentationRail.v1')||'null')}catch(_){return 'illisible'}})(),
    zRail:host&&getComputedStyle(host).zIndex,
    writes:window.__rail.calls.filter(c=>c.method==='POST').map(c=>c.url.replace('/api/presentation-studio','')+' '+c.body),
    reports:window.__rail.reports.slice(-3),
    commands:window.__rail.commands,
    active:document.activeElement?{tag:document.activeElement.tagName,cls:document.activeElement.className}:null};
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-pr-cdp-'));
const port=9722+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,['--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,'--no-first-run','--no-default-browser-check',
  '--disable-gpu','--disable-extensions','--allow-file-access-from-files','--hide-scrollbars','about:blank'],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

let out={},consoleLines=[];
try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
    else if(msg.method==='Runtime.consoleAPICalled'){
      const text=(msg.params.args||[]).map(a=>a.value!==undefined?String(a.value):'').join(' ');
      if(text.startsWith('[presentation-rail]')||text.startsWith('[presentation-window]'))consoleLines.push(msg.params.type+' '+text);
    }else if(msg.method==='Runtime.exceptionThrown')consoleLines.push('EXCEPTION '+JSON.stringify(msg.params.exceptionDetails.exception&&msg.params.exceptionDetails.exception.description||msg.params.exceptionDetails.text));
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}))});
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  const KEYS={Enter:{code:'Enter',keyCode:13,text:'\r'},Escape:{code:'Escape',keyCode:27},ArrowRight:{code:'ArrowRight',keyCode:39},ArrowDown:{code:'ArrowDown',keyCode:40},Delete:{code:'Delete',keyCode:46}};
  const press=async key=>{const k=KEYS[key];
    await send('Input.dispatchKeyEvent',{type:'keyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,text:k.text});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode})};
  const at=async selector=>{
    const p=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;if(el.closest('.jvr-scroll'))el.scrollIntoView({block:'nearest'});const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
    if(!p)throw new Error('introuvable '+selector);return p;
  };
  const mouse=async (selector,button)=>{
    const p=await at(selector);
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:p.x,y:p.y});
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x:p.x,y:p.y,button,buttons:button==='right'?2:1,clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:p.x,y:p.y,button,buttons:0,clickCount:1});
  };
  const click=s=>mouse(s,'left'),rightClick=s=>mouse(s,'right');
  const item=n=>`#presentationRail .jvr-item[data-id="pst_${String(n).padStart(32,'0')}"]`;
  const shot=async name=>{if(!SHOTS)return;const r=await send('Page.captureScreenshot',{format:'png'});writeFileSync(join(SHOTS,name),Buffer.from(r.data,'base64'))};
  const poll1=async (expr,ms=6000)=>{const t0=Date.now();while(Date.now()-t0<ms){if(await evaluate(expr))return true;await sleep(80)}return false};
  let loads=0;
  const load=async (width,height,setup,hash)=>{
    await send('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});
    loads+=1;
    await send('Page.navigate',{url:'file:///'+PAGE.replace(/\\/g,'/')+'?load='+loads+(hash||'')});
    for(let i=0;i<200;i+=1){await sleep(50);const ready=await evaluate(`document.readyState==='complete'&&!!window.JarvisPresentationRail`).catch(()=>false);if(ready)break}
    if(setup)await evaluate(setup);
    await poll1(`window.JarvisPresentationRail.state().loaded===true`);
    await sleep(250);
  };

  await send('Page.enable');await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:FAKE});
  out={};
  const PRES_BOARD=`window.JarvisPresentationRail.gate({boards:{available:true,active:{board_id:'b',board_kind:'presentation'}},interaction_mode:{mode:'assistant'},voice_state:'listening',voice_online:true})`;

  /* 1. Pas dans un Board de presentation, rien ne travaille : le rail reste discret (cache). */
  await load(1440,900,"window.JarvisPresentationRail.gate({boards:{available:true,active:null}})",'#calm');
  out.auto_idle=await evaluate(READ);

  /* 2. Dans un Board de presentation : visible, groupes, pastilles, a droite de la palette. */
  await load(1440,900,PRES_BOARD);
  await sleep(300);
  out.board=await evaluate(READ);
  out.board.paletteRight=await evaluate(`(()=>{const p=document.querySelector('#barehandsPalette');const r=p.getBoundingClientRect();return {l:r.left,r:r.right,w:r.width}})()`);

  /* 3. Clic droit : menu complet ; Masquer ; la ligne passe sous « Masquees ». */
  await rightClick(item(2));await sleep(150);
  out.menu=await evaluate(READ);
  await click('.jvr-menu button[data-act="hide"]');
  await poll1(`document.querySelectorAll('#presentationRail .jvr-item').length===2`);
  out.after_hide=await evaluate(READ);
  /* ... reafficher par le pli. */
  await click('#presentationRail .jvr-fold');await sleep(150);
  out.hidden_fold=await evaluate(READ);

  /* 4. Archive : menu -> Supprimer -> dialogue -> annuler -> rien ; confirmer -> archivee. */
  await rightClick(item(3));await sleep(100);
  await click('.jvr-menu button[data-act="archive"]');await sleep(150);
  out.archive_dialog=await evaluate(READ);
  await press('Escape');await sleep(120);
  out.archive_cancelled=await evaluate(READ);
  await rightClick(item(3));await sleep(100);
  await click('.jvr-menu button[data-act="archive"]');await sleep(100);
  await click('#confirmGo');
  await poll1(`window.__rail.rows.find(r=>r.title==='Roadmap').archived===true`);await sleep(300);
  out.archived=await evaluate(READ);

  /* 5. Renommer : champ prérempli, Entrée. */
  await rightClick(item(2));await sleep(100);
  await click('.jvr-menu button[data-act="rename"]');await sleep(150);
  out.rename_dialog=await evaluate(READ);
  await evaluate(`(()=>{const i=document.querySelector('.jvr-dialog input');i.value='Bilan 2026';})()`);
  await press('Enter');
  await poll1(`window.__rail.rows.find(r=>r.presentation_id.endsWith('2')).title==='Bilan 2026'`);await sleep(300);
  out.renamed=await evaluate(READ);

  /* 6. Clic = Variantes (native-studio-playback-fix Slice 09 : la fenetre flottante est retiree). Variantes est remplace par un double qui
     note ses ouvertures : c'est le geste du rail qui est mesure ici, Variantes a ses propres preuves. « Presenter » lance la lecture. */
  const STUB_VARIANTS=`window.__opens=[];window.JarvisStudioExplorer={open:o=>{window.__opens.push(o);return Promise.resolve({state:'opened',mode:'windowed'})},
    close:()=>({state:'closed'}),isOpen:()=>false,state:()=>({open:false,presentation_id:null})}`;
  await load(1440,900,PRES_BOARD+';'+STUB_VARIANTS);
  await click(item(1));await poll1(`window.__opens.length>=1`);await sleep(200);
  out.opened=await evaluate(READ);out.opened.opens=await evaluate(`window.__opens`);
  out.opened.windowNode=await evaluate(`!!document.querySelector('#jvPresWindow')`);
  await rightClick(item(1));await sleep(100);
  await click('.jvr-menu button[data-act="play"]');
  await poll1(`window.__rail.commands.length>=1`);await sleep(300);
  out.played=await evaluate(READ);

  /* 7. Demandes d'ecran du cerveau : masquer puis reafficher le rail ; l'ancienne `open_window` n'ouvre plus rien (MCP : Variantes). */
  await load(1440,900,PRES_BOARD+';'+STUB_VARIANTS);
  await evaluate(`window.__rail.ui={seq:1,request:{seq:1,action:'open_window',presentation_id:window.__rail.rows[1].presentation_id,age_s:1,fresh:true},reported:null}`);
  await sleep(4800);
  out.brain_open=await evaluate(READ);out.brain_open.opens=await evaluate(`window.__opens.length`);
  await evaluate(`window.__rail.ui={seq:2,request:{seq:2,action:'hide_rail',presentation_id:null,age_s:1,fresh:true},reported:null}`);
  await poll1(`window.JarvisPresentationRail.state().pref==='hidden'`);await sleep(900);
  out.brain_hide=await evaluate(READ);
  await evaluate(`window.__rail.ui={seq:3,request:{seq:3,action:'show_rail',presentation_id:null,age_s:1,fresh:true},reported:null}`);
  await poll1(`window.JarvisPresentationRail.state().pref==='shown'`);await sleep(900);
  out.brain_show=await evaluate(READ);

  /* 8. Une requete vieille (page rechargee longtemps apres) n'est PAS rejouee. */
  await load(1440,900,PRES_BOARD);
  out.stale_request=await evaluate(`(async()=>{window.__rail.ui={seq:9,request:{seq:9,action:'hide_rail',presentation_id:null,age_s:600,fresh:false},reported:null};
    await new Promise(r=>setTimeout(r,4600));return window.JarvisPresentationRail.state().pref==='hidden'})()`);

  /* 9. Une presentation passe en travail : le rail le montre (pastille), il n'ouvre rien de lui-meme (concentration retiree, Slice 09). */
  await load(1440,900,PRES_BOARD+';'+STUB_VARIANTS);
  await evaluate(`window.__rail.rows[1].work={state:'working',label:'presentation_edit',age_s:1}`);
  await sleep(4800);
  out.focus=await evaluate(READ);out.focus.opens=await evaluate(`window.__opens.length`);

  /* 10. Studio ouvert : le rail se range a gauche, hors de la zone inerte. */
  await load(1440,900,PRES_BOARD);
  await evaluate(`window.dispatchEvent(new CustomEvent('jarvis:studio-explorer-opened',{detail:{}}))`);await sleep(250);
  out.studio=await evaluate(READ);
  await evaluate(`window.dispatchEvent(new CustomEvent('jarvis:studio-explorer-closed',{detail:{}}))`);await sleep(250);
  out.studio_closed=await evaluate(READ);

  /* 11. Relais injoignable : etat dit, pas d'etat confirme. Echec d'ecriture : dit a l'ecran. */
  await load(1440,900,PRES_BOARD);
  await evaluate(`window.__rail.refuse={status:409,code:'presentation_studio_variant_in_playback',message:'jouee'}`);
  await rightClick(item(1));await sleep(100);
  await click('.jvr-menu button[data-act="hide"]');await sleep(500);
  out.write_failed=await evaluate(READ);
  await evaluate(`window.__rail.refuse=null;window.__rail.down=true`);
  await sleep(10500);
  out.lost=await evaluate(READ);

  /* 12. Petit ecran (375 px) : le rail reste dans la page. */
  await load(375,700,PRES_BOARD);
  out.narrow_auto=await evaluate(READ);
  await click('#presentationRailTab');await sleep(300);
  out.narrow=await evaluate(READ);

  /* 13. Studio sur un ecran etroit : le rail se range en bande de vignettes. */
  await load(1000,600,PRES_BOARD+";JarvisPresentationRail.setPref('auto')");
  await evaluate(`window.dispatchEvent(new CustomEvent('jarvis:studio-explorer-opened',{detail:{}}))`);await sleep(250);
  out.studio_narrow=await evaluate(READ);
  await load(800,600,PRES_BOARD+";JarvisPresentationRail.setPref('auto')");
  await evaluate(`window.dispatchEvent(new CustomEvent('jarvis:studio-explorer-opened',{detail:{}}))`);await sleep(250);
  out.studio_tiny=await evaluate(READ);

  /* 14. Zone droite : a chaque taille, la bande du rail est pleine hauteur, de largeur fixe, au bord droit ; ni le lanceur (haut-gauche), ni la puce, ni les
     boutons des rails, ni la colonne gauche ne sont recouverts. */
  const ZONE=`(()=>{const box=el=>{if(!el||el.hidden)return null;const r=el.getBoundingClientRect();if(!r.width&&!r.height)return null;return {l:r.left,t:r.top,r:r.right,b:r.bottom}};
    const q=s=>document.querySelector(s);const pills=q('#bgPills');
    return {rail:box(q('#presentationRail')),dock:box(q('.dock')),railDock:box(q('#railDock')),pills:pills&&!pills.hidden?box(pills):null,palette:box(q('#barehandsPalette')),
      wheel:box(q('#toolWheel')),density:q('#presentationRail').dataset.density,vw:innerWidth,vh:innerHeight,
      cards:document.querySelectorAll('#presentationRail .jvr-item').length,radius:getComputedStyle(q('#presentationRail')).borderTopLeftRadius,
      position:getComputedStyle(q('#presentationRail')).position,resize:getComputedStyle(q('#presentationRail')).resize,
      scroll:(l=>l?{overflowY:getComputedStyle(l).overflowY,canScroll:l.scrollHeight>l.clientHeight}:null)(q('#presentationRail .jvr-scroll'))}})()`;
  out.zones={};
  for(const [w,h] of [[1440,900],[1280,720],[900,600],[600,800]]){
    await load(w,h,PRES_BOARD);
    /* 700 px et moins : sans choix de l'utilisateur le rail reste replie (la bande couvrirait la scene) ; le bouton l'ouvre. */
    if(w<=700){out.zones[`${w}x${h}_auto`]=await evaluate(ZONE);await click('#presentationRailTab');await sleep(300)}
    out.zones[`${w}x${h}`]=await evaluate(ZONE);
  }

  /* 14b. Replie = disparu : il ne reste que le bouton ; le bouton le deplie ; le choix est memorise (stockage) et survit a un rechargement. */
  await load(1440,900,PRES_BOARD);
  out.open_before=await evaluate(READ);
  await click('#presentationRail .jvr-tool');await sleep(300);
  out.folded=await evaluate(READ);
  out.folded.hiddenAttr=await evaluate(`document.getElementById('presentationRail').hidden&&getComputedStyle(document.getElementById('presentationRail')).display==='none'`);
  await shot('rail-folded-1440.png');
  await evaluate(`window.name='keep'`);
  await load(1440,900,PRES_BOARD);
  out.folded_reload=await evaluate(READ);
  await click('#presentationRailTab');await sleep(300);
  out.unfolded=await evaluate(READ);
  await click('#presentationRailTab');await sleep(300);
  out.refolded=await evaluate(READ);
  await evaluate(`window.name=''`);

  /* 14c. Deux bandes : le Chat est toujours le plus a droite ; le rail se range a sa gauche ; les boutons restent a gauche de la bande ouverte. */
  await load(1440,900,PRES_BOARD);
  await click('#chatTab');await sleep(700);
  out.two_rails=await evaluate(READ);
  out.two_rails.chatBox=await evaluate(`(()=>{const r=document.getElementById('chatPanel').getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom,radius:getComputedStyle(document.getElementById('chatPanel')).borderTopLeftRadius,bg:getComputedStyle(document.getElementById('chatPanel')).backgroundImage.slice(0,60)}})()`);
  await shot('rail-two-bands-1440.png');
  await click('#chatTab');await sleep(500);
  out.chat_closed=await evaluate(READ);
  await click('#presentationRailTab');await sleep(300);
  await click('#chatTab');await sleep(600);
  out.chat_only=await evaluate(READ);
  /* Etroit (moins de 900 px) : l'un ferme l'autre. */
  await load(800,600,PRES_BOARD);
  out.narrow_rail=await evaluate(READ);
  await click('#chatTab');await sleep(700);
  out.narrow_chat=await evaluate(READ);
  await click('#presentationRailTab');await sleep(500);
  out.narrow_rail_again=await evaluate(READ);

  /* 14d. Archives cachees par defaut ; le bouton du pied les montre dans une section « Archives », puis les recache. */
  await load(1440,900,PRES_BOARD);
  out.archived_hidden=await evaluate(READ);
  out.archived_hidden.domCards=await evaluate(`document.querySelectorAll('#presentationRail [data-id="pst_${'5'.padStart(32,'0')}"]').length`);
  await click('#presentationRail .jvr-arch');await sleep(300);
  out.archived_shown=await evaluate(READ);
  await shot('rail-archived-1440.png');
  await click('#presentationRail .jvr-arch');await sleep(300);
  out.archived_hidden_again=await evaluate(READ);

  /* 14e. Suppression definitive d'une presentation : menu -> dialogue de la page (annulable) -> archivage, plan, purge ; echec dit a l'ecran. */
  await load(1440,900,PRES_BOARD);
  await rightClick(item(3));await sleep(120);
  out.delete_menu=await evaluate(READ);
  await click('.jvr-menu button[data-act="delete"]');await sleep(200);
  out.delete_dialog=await evaluate(READ);
  await press('Escape');await sleep(150);
  out.delete_cancelled=await evaluate(READ);
  out.delete_cancelled.rows=await evaluate(`window.__rail.rows.length`);
  await rightClick(item(3));await sleep(100);
  await click('.jvr-menu button[data-act="delete"]');await sleep(150);
  await click('#confirmGo');
  await poll1(`!window.__rail.rows.some(r=>r.title==='Roadmap')`);await sleep(500);
  out.deleted=await evaluate(READ);
  out.deleted.rows=await evaluate(`window.__rail.rows.map(r=>r.title)`);
  await evaluate(`window.__rail.purgeRefuse={status:409,code:'presentation_studio_variant_in_playback',message:'jouee'}`);
  await rightClick(item(2));await sleep(100);
  await click('.jvr-menu button[data-act="delete"]');await sleep(150);
  await click('#confirmGo');await sleep(900);
  out.delete_failed=await evaluate(READ);
  out.delete_failed.rows=await evaluate(`window.__rail.rows.map(r=>[r.title,r.archived])`);
  await evaluate(`window.__rail.purgeRefuse=null`);
  /* La corbeille d'une carte archivee : pas d'archivage, seulement le plan et la purge ; la touche Suppr passe par la meme confirmation. */
  await click('#presentationRail .jvr-arch');await sleep(300);
  await evaluate(`document.querySelector('#presentationRail [data-section=archived] .jvr-item').focus()`);
  await press('Delete');await sleep(200);
  out.delete_key=await evaluate(READ);
  await press('Escape');await sleep(150);
  await click('#presentationRail [data-section=archived] .jvr-card .jvr-del');await sleep(200);
  await click('#confirmGo');
  await poll1(`!window.__rail.rows.some(r=>r.title==='Bilan')`);await sleep(500);
  out.trash_archived=await evaluate(READ);
  out.trash_archived.rows=await evaluate(`window.__rail.rows.map(r=>r.title)`);

  /* 15. Cartes, dans les deux themes : apercu reel (double de la route bornee), vignette typee, badge, metadonnee, chaque etat avec son
     libelle, puis Variantes ouvert (double de l'hote) : le rail se range a DROITE, Variantes a sa gauche. */
  /* The host's own sheet places it (`inset:0`, rank 9000): a stylesheet rule here too, so the rail's docking rule can move its right edge. */
  const FAKE_EXPLORER=`(()=>{const st=document.createElement('style');st.textContent='#jvStudioExplorer{position:fixed;inset:0;z-index:9000;background:linear-gradient(135deg,#071019,#0d2233)}';document.head.appendChild(st);
    const x=document.createElement('div');x.id='jvStudioExplorer';document.body.appendChild(x);
    window.dispatchEvent(new CustomEvent('jarvis:studio-explorer-opened',{detail:{}}))})()`;
  for(const theme of ['circuit-board','cosmos']){
    await load(1440,900,`window.JarvisThemeAPI&&window.JarvisThemeAPI.activate('${theme}',{persist:false});`+PRES_BOARD,'#cards');
    await poll1(`[...document.querySelectorAll('#presentationRail .jvr-thumb img')].every(i=>i.complete)`);await sleep(400);
    out['cards_'+theme]=await evaluate(READ);
    out['cards_'+theme].theme=await evaluate(`document.documentElement.getAttribute('data-jarvis-theme')||''`);
    await shot(`rail-cards-${theme}-1440.png`);
    await evaluate(FAKE_EXPLORER);await sleep(300);
    out['studio_'+theme]=await evaluate(READ);
    await shot(`rail-studio-${theme}-1440.png`);
    await load(1000,700,`window.JarvisThemeAPI&&window.JarvisThemeAPI.activate('${theme}',{persist:false});`+PRES_BOARD,'#cards');
    await sleep(400);
    out['narrow_'+theme]=await evaluate(READ);
    await shot(`rail-1000-${theme}.png`);
  }

  /* 16. Les gestes de la carte : « ⋯ » ouvre le meme menu ; « Marquer comme vu » ecrit `review` ; ouvrir depuis le rail ecrit `review`. */
  await load(1440,900,PRES_BOARD+';'+STUB_VARIANTS,'#cards');
  await click(`${item(1)} ~ .jvr-more`);await sleep(150);
  out.more_menu=await evaluate(READ);
  await press('Escape');await sleep(100);
  await rightClick(item(2));await sleep(150);
  out.review_menu=await evaluate(READ);
  await click('.jvr-menu button[data-act="review"]');
  await poll1(`window.__rail.rows[1].unreviewed===null&&document.querySelector('${item(2)}').dataset.state==='done'`);await sleep(200);
  out.reviewed=await evaluate(READ);
  await evaluate(`window.__rail.rows[1].unreviewed={since:'2026-10-16T10:00:00Z',label:'presentation_edit'};JarvisPresentationRail.refresh()`);
  await poll1(`document.querySelector('${item(2)}').dataset.state==='unreviewed'`);
  await click(item(2));
  await poll1(`window.__rail.rows[1].unreviewed===null`);await sleep(300);
  out.open_reviews=await evaluate(READ);out.open_reviews.opens=await evaluate(`window.__opens`);

  /* 17. Une image d'apercu illisible : la carte retombe sur la vignette typee et le journal le dit. */
  await load(1440,900,`window.__rail.previews={};`+PRES_BOARD,'#cards');
  await poll1(`document.querySelector('${item(1)} .jvr-thumb').dataset.kind==='placeholder'`);await sleep(200);
  out.broken_preview=await evaluate(READ);

  /* 18. Etape B : les Artifacts du Board actif (double de la route du workspace), type par MIME / hote, etat sans jaune ; clic sur une
     image = visionneuse de l'apercu des captures (Slice 05, `JarvisScreenshotPreview.openLightbox`), le reste = inspecteur (double de
     JarvisWorkspace) ; changer de Board vide puis relit, sans fuite. */
  const STUB_WS=`window.__wsOpen=[];window.JarvisWorkspace={open:()=>{window.__wsOpen.push(['open'])},act:(n,d)=>{window.__wsOpen.push([n,d&&d.id]);return Promise.resolve()}}`;
  await load(1440,900,STUB_WS+';'+PRES_BOARD,'#cards');
  await poll1(`document.querySelectorAll('#presentationRail .jvr-ws .jvr-item').length===5`);
  await poll1(`[...document.querySelectorAll('#presentationRail .jvr-ws .jvr-thumb img')].every(i=>i.complete)`);await sleep(200);
  out.board_items=await evaluate(READ);
  await evaluate(`document.querySelector('#presentationRail .jvr-ws').scrollIntoView({block:'end'})`);
  await shot('rail-board-items-1440.png');
  await click(`#presentationRail .jvr-ws .jvr-item[data-id="jart_${'c'.repeat(32)}"]`);await sleep(150);
  out.board_open=await evaluate(`window.__wsOpen`);
  out.board_lightbox=await evaluate(`(lb=>lb?{open:lb.classList.contains('open'),href:lb.querySelector('a').getAttribute('href')}:null)(document.getElementById('screenshotLightbox'))`);
  await press('Escape');await sleep(100);
  await rightClick(`#presentationRail .jvr-ws .jvr-item[data-id="jart_${'e'.repeat(32)}"]`);await sleep(150);
  out.board_menu=await evaluate(READ);
  await press('Escape');
  await evaluate(`window.JarvisPresentationRail.gate({boards:{available:true,active:{board_id:'c',board_kind:'presentation'}},interaction_mode:{mode:'assistant'},voice_state:'listening',voice_online:true})`);
  out.board_switched_now=await evaluate(READ);
  await sleep(500);
  out.board_switched=await evaluate(READ);

  /* 18b. Tout element du Board se supprime definitivement : la corbeille de la carte (image), le dialogue de la page, DELETE /api/artifacts/{id} ;
     un derive demande un second accord (cascade=true) ; un refus est dit ; Suppr au clavier passe par la meme confirmation. */
  const WS_CARD=c=>`#presentationRail .jvr-ws .jvr-item[data-id="jart_${c.repeat(32)}"]`;
  await load(1440,900,STUB_WS+';'+PRES_BOARD,'#cards');
  await poll1(`document.querySelectorAll('#presentationRail .jvr-ws .jvr-item').length===5`);
  await click(`${WS_CARD('c')} ~ .jvr-del`);await sleep(200);
  out.ws_delete_dialog=await evaluate(READ);
  await click('#confirmCancel');await sleep(150);
  out.ws_delete_cancelled=await evaluate(READ);
  await click(`${WS_CARD('c')} ~ .jvr-del`);await sleep(150);
  await click('#confirmGo');
  await poll1(`document.querySelectorAll('#presentationRail .jvr-ws .jvr-item').length===4`);await sleep(200);
  out.ws_deleted=await evaluate(READ);
  await evaluate(`window.__rail.wsDependents=['jart_${'d'.repeat(32)}']`);
  await rightClick(WS_CARD('d'));await sleep(120);
  out.ws_menu=await evaluate(READ);
  await click('.jvr-menu button[data-act="ws-delete"]');await sleep(150);
  await click('#confirmGo');await sleep(400);
  out.ws_dependents_dialog=await evaluate(READ);
  await click('#confirmGo');
  await poll1(`document.querySelectorAll('#presentationRail .jvr-ws .jvr-item').length===3`);await sleep(200);
  out.ws_cascaded=await evaluate(READ);
  await evaluate(`window.__rail.wsRefuse={status:409,code:'artifact_still_pending',message:'en cours'}`);
  await evaluate(`document.querySelector('${WS_CARD('f')}').focus()`);
  await press('Delete');await sleep(200);
  await click('#confirmGo');await sleep(500);
  out.ws_refused=await evaluate(READ);

  /* 19. Le focus survit aux relevés pour TOUTE carte du rail (Sur ce Board, plis) ; Echap depuis le menu d'une carte du Board y rend le focus,
     meme si la carte a ete redessinee pendant que le menu etait ouvert. */
  const ACTIVE=`(()=>{const a=document.activeElement;return a&&a.classList&&a.classList.contains('jvr-item')?a.dataset.id:(a?a.tagName:null)})()`;
  const SHOT_CARD=`#presentationRail .jvr-ws .jvr-item[data-id="jart_${'c'.repeat(32)}"]`;
  await load(1440,900,STUB_WS+';'+PRES_BOARD,'#cards');
  await poll1(`!!document.querySelector('${SHOT_CARD}')`);
  await evaluate(`document.querySelector('${SHOT_CARD}').focus()`);
  const polls0=await evaluate(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length`);
  await poll1(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length>=${polls0}+2`,9000);await sleep(150);
  out.focus_board={active:await evaluate(ACTIVE),polls:(await evaluate(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length`))-polls0};
  await evaluate(`(()=>{const b=document.querySelector('#presentationRail .jvr-arch');if(b.getAttribute('aria-pressed')!=='true')b.click()})()`);await sleep(150);
  const FOLDED=`#presentationRail [data-section=archived] .jvr-item[data-id="pst_${'5'.padStart(32,'0')}"]`;
  await evaluate(`document.querySelector('${FOLDED}').focus()`);
  const polls1=await evaluate(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length`);
  await poll1(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length>=${polls1}+2`,9000);await sleep(150);
  out.focus_folded={active:await evaluate(ACTIVE),polls:(await evaluate(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length`))-polls1};
  await rightClick(SHOT_CARD);await sleep(150);
  out.menu_open_active=await evaluate(`document.activeElement&&document.activeElement.closest('.jvr-menu')?'menu':null`);
  const polls2=await evaluate(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length`);
  await poll1(`window.__rail.calls.filter(c=>c.url==='/api/presentation-studio/rail').length>=${polls2}+1`,9000);await sleep(150);
  await press('Escape');await sleep(150);
  out.focus_after_menu=await evaluate(ACTIVE);

  ws.close();
  process.stdout.write(JSON.stringify({results:out,console:consoleLines}));
}catch(error){
  const keys=Object.keys(out);process.stderr.write('PARTIAL '+keys.join(',')+' | derniere lecture '+(l=>JSON.stringify({menu:l&&l.menu,confirm:l&&l.confirm,note:l&&l.note,ws:l&&l.wsItems&&l.wsItems.map(i=>i.name),deletes:l&&l.wsDeletes,active:l&&l.active,dlg:out.ws_delete_dialog&&out.ws_delete_dialog.confirm,canc:out.ws_delete_cancelled&&out.ws_delete_cancelled.confirm}))(out[keys[keys.length-1]])+' | '+String(error.stack||error)+' | '+JSON.stringify(consoleLines.slice(-12)).slice(0,1500));process.exitCode=1;
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient le dossier */}
}

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{const list=await (await fetch(url)).json();const page=list.find(t=>t.type==='page');if(page&&page.webSocketDebuggerUrl)return page}catch(_){/* Chrome n ecoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
