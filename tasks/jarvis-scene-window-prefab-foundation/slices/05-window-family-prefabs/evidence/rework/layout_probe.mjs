/* Preuve navigateur de la reprise QA de la Slice 05 (F3, F4, F5, F8) : Chrome RÉEL
   sans tête (`--headless=new`, profil jetable `--user-data-dir`), piloté par CDP, sur
   la page servie par un vrai Control Center relié à un vrai Core isolés (18963/18964).

   - F4 parité : `legacy-1` (fenêtre classique) et `pw-1` (`jarvis.window@1`), même
     titre, même corps long, mêmes entrées, même boîte 280 × 220 px : les entrées
     restent en bas, le corps défile et s'efface au-dessus ; captures dans les deux
     thèmes ; molette dans le corps du cadre ; hauteur rapportée = hauteur naturelle.
   - F3 : références `docs/local-data.md` et `r1` entières à côté d'un libellé long.
   - F5 : anneau de focus clavier du document (`doc-1`).
   - F8 : tableau choisi puis tableau défilé et choisi (captures différentes) ;
     polices réellement utilisées (`CSS.getPlatformFontsForNode`).

   Usage : node layout_probe.mjs <url du CC> <chrome.exe> <dossier de sortie>  */
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT]=process.argv;
const profile=mkdtempSync(join(tmpdir(),'jarvis-s05rw-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const TITLE='Migration du stockage';
const BODY='Trois pistes pour **la migration** du stockage, relues après la revue :\n\n'+
  Array.from({length:9},(_,n)=>`- piste ${n+1} : une ligne de corps assez longue pour passer à la ligne ;`).join('\n')+'\n\nFIN-DU-CORPS.';
const ITEMS=[
  {label:'Note de cadrage du stockage, version relue après la revue du 2 octobre',ref:'docs/local-data.md'},
  {label:'Mesure de la latence d’écriture en mode WAL sur le poste portable',url:'https://www.sqlite.org/wal.html',ref:'WAL'},
  {label:'Décision attendue sur la migration, avec un libellé qui passe à la ligne',ref:'r1'},
];
const DOC='# Lecture\n\n'+Array.from({length:6},(_,n)=>`Paragraphe ${n+1} du document, assez long pour passer à la ligne dans la fenêtre.`).join('\n\n');
const COLUMNS=[{label:'Fichier'},{label:'Taille',align:'right'},{label:'Statut',align:'center'},{label:'Commentaire'}];
const ROWS=Array.from({length:40},(_,r)=>[`jarvis/module_${String(r+1).padStart(2,'0')}.py`,`${(r*37%90)+3} Ko`,['ok','modifié','nouveau'][r%3],
  r%5===0?'Commentaire plus long qui passe à la ligne':'—']);
function upsert(id,title,geometry,payload,category){
  return {schema_version:1,op:'upsert_object',object_id:id,fields:{kind:'window',category:category||'research',representation:'window',
    geometry,payload:Object.assign({title,summary:'',items:[]},payload)}};
}
const COMMANDS=[
  upsert('legacy-1',TITLE,{x:-140,y:-66,w:56,h:44},{summary:BODY,items:ITEMS.map(i=>({label:i.label,ref:i.ref||'',url:i.url||''}))}),
  upsert('pw-1',TITLE,{x:-80,y:-66,w:56,h:44},{summary:'Repli de capture.',prefab:{id:'jarvis.window',version:1,props:{},data:{body:BODY,items:ITEMS}}}),
  upsert('pw-tall','Fenêtre plus haute que son contenu',{x:-140,y:-14,w:56,h:60},{summary:'Repli.',prefab:{id:'jarvis.window',version:1,props:{},
    data:{body:'Court.',items:ITEMS.slice(0,2)}}}),
  upsert('doc-1','Rapport de lecture',{x:-20,y:-66,w:56,h:44},{prefab:{id:'jarvis.document',version:1,props:{},data:{body:DOC}}},'doc'),
  upsert('tbl-1','Fichiers modifiés',{x:40,y:-66,w:80,h:50},{prefab:{id:'jarvis.table',version:1,props:{},data:{columns:COLUMNS,rows:ROWS}}},'code'),
];
const IDS=COMMANDS.map(c=>c.object_id);

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
  let id=0;const pending=new Map();const sessions=new Map();
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled'){
      const text=msg.params.args.map(a=>a.value??a.description??(a.preview?JSON.stringify(a.preview.properties.map(p=>[p.name,p.value])):'')).join(' ');
      out.console.push({session:msg.sessionId?'frame':'page',type:msg.params.type,text:text.slice(0,300)});
    }
    if(msg.method==='Runtime.exceptionThrown')out.console.push({session:msg.sessionId?'frame':'page',type:'exception',
      text:(msg.params.exceptionDetails.exception?.description||msg.params.exceptionDetails.text||'').slice(0,300)});
    if(msg.method==='Target.attachedToTarget'){
      const s=msg.params.sessionId;sessions.set(s,msg.params.targetInfo);
      send('Runtime.enable',{},s).catch(()=>{});
      send('Runtime.runIfWaitingForDebugger',{},s).catch(()=>{});
    }
    if(msg.method==='Target.detachedFromTarget')sessions.delete(msg.params.sessionId);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
  /* Une commande CDP sans réponse en 15 s échoue (sinon la preuve attendrait sans fin). */
  function send(method,params={},sessionId){return new Promise((ok,ko)=>{const mine=++id;
    const timer=setTimeout(()=>{pending.delete(mine);ko(new Error(`CDP ${method} timed out`))},15000);
    pending.set(mine,{ok:(v)=>{clearTimeout(timer);ok(v)},ko:(e)=>{clearTimeout(timer);ko(e)}});
    ws.send(JSON.stringify(sessionId?{id:mine,method,params,sessionId}:{id:mine,method,params}))})}
  const evaluate=async(expression,session)=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},session);
    if(r.exceptionDetails)throw new Error(`${expression.slice(0,100)} -> ${r.exceptionDetails.exception?.description||r.exceptionDetails.text}`);
    return r.result.value;
  };
  const until=async(check,ms=20000,label)=>{const deadline=Date.now()+ms;let last;
    while(Date.now()<deadline){try{last=await check();if(last)return last}catch(_){}await sleep(150)}
    throw new Error('never true: '+(label||check.toString().slice(0,120)))};
  /* Chaque cadre (origine opaque, hors processus) est lu dans sa session attachée ; on le reconnaît à son gabarit. */
  const inFrame=async(marker,expression)=>{
    for(const [session,info] of sessions){
      if(info.url!=='about:srcdoc')continue;
      try{const value=await evaluate(`document.getElementById(${JSON.stringify(marker)})?(${expression}):null`,session);
        if(value!==null&&value!==undefined)return value}catch(_){/* cible partie */}
    }
    return null;
  };
  const box=(selector)=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;
    const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}})()`);
  const mouse=async(type,x,y,buttons)=>send('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:buttons??(type==='mouseReleased'?0:1),clickCount:1});
  const click=async(x,y)=>{await mouse('mouseMoved',x,y,0);await mouse('mousePressed',x,y);await mouse('mouseReleased',x,y)};
  const key=async(k,code,vk)=>{await send('Input.dispatchKeyEvent',{type:'rawKeyDown',key:k,code:code||k,windowsVirtualKeyCode:vk});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:k,code:code||k,windowsVirtualKeyCode:vk});await sleep(60)};
  const drag=async(from,dx,dy)=>{
    await mouse('mouseMoved',from.x,from.y,0);await mouse('mousePressed',from.x,from.y);
    for(let i=1;i<=12;i++){await mouse('mouseMoved',from.x+dx*i/12,from.y+dy*i/12);await sleep(16)}
    await mouse('mouseReleased',from.x+dx,from.y+dy);
  };
  const shot=async(name,clip)=>{const r=await send('Page.captureScreenshot',clip?{format:'png',clip:{...clip,scale:1}}:{format:'png'});
    writeFileSync(join(OUT,name),Buffer.from(r.data,'base64'));return name};
  const stored=(objectId)=>evaluate(`fetch('/api/scene',{cache:'no-store'}).then(r=>r.json()).then(b=>{
    const o=b.snapshot.objects.find(o=>o.object_id===${JSON.stringify(objectId)});return o?{revision:b.revision,geometry:o.geometry}:null})`);
  const theme=(name)=>evaluate(`(JarvisThemeAPI.activate(${JSON.stringify(name)}),document.documentElement.dataset.jarvisTheme)`);
  const union=async(ids)=>{const boxes=[];for(const objectId of ids)boxes.push(await box(`[data-object-id="${objectId}"]`));
    const x=Math.max(0,Math.min(...boxes.map(b=>b.x))-14),y=Math.max(0,Math.min(...boxes.map(b=>b.y))-14);
    return {x,y,width:Math.max(...boxes.map(b=>b.x+b.w))+14-x,height:Math.max(...boxes.map(b=>b.y+b.h))+14-y}};

  await send('Page.enable');await send('Runtime.enable');await send('DOM.enable');await send('CSS.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate('!!window.JarvisScene'),30000,'scene');
  /* Objets d'autres sondes sur la même scène de scratch : masqués (les nôtres sont réécrits par `upsert`). */
  for(const oid of ['pw-2','doc-tall'])await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema_version:1,op:'set_visibility',object_id:${JSON.stringify(oid)},visibility:'hidden'})}).then(r=>r.status)`).catch(()=>{});
  out.created=[];
  for(const c of COMMANDS)out.created.push(await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:${JSON.stringify(JSON.stringify(c))}}).then(async r=>({status:r.status,outcome:(await r.json()).outcome}))`));
  /* Masquées par drag_probe.mjs sur la même scène : les nôtres redeviennent visibles. */
  for(const oid of IDS)await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({schema_version:1,op:'set_visibility',object_id:${JSON.stringify(oid)},visibility:'visible'})}).then(r=>r.status)`).catch(()=>{});
  for(const oid of ['pw-1','pw-tall','doc-1','tbl-1'])await until(()=>evaluate(`!!document.querySelector('[data-object-id="${oid}"] .sc-prefab-slot iframe')`),30000,oid);
  await sleep(2500);
  /* Session d'un cadre : reconnu à son gabarit et à un texte qui n'est qu'à lui. */
  const frameOf=async(marker,text)=>{
    for(const [session,info] of sessions){if(info.url!=='about:srcdoc')continue;
      try{const ok=await evaluate(`!!document.getElementById(${JSON.stringify(marker)})&&document.body.textContent.includes(${JSON.stringify(text)})`,session);
        if(ok)return session}catch(_){/* cible partie */}}
    throw new Error('no frame for '+marker+' '+text)};
  const S={'pw-1':await frameOf('win','piste 9'),'pw-tall':await frameOf('win','Court.'),'doc-1':await frameOf('doc','Paragraphe 6'),
    'tbl-1':await frameOf('tbl-body','module_01')};

  /* --- F4 : parité de mise en page, F3 : références entières ------------------------------- */
  const legacyLayout=()=>evaluate(`(()=>{const n=document.querySelector('[data-object-id="legacy-1"]');const nb=n.getBoundingClientRect();
    const s=n.querySelector('.sc-summary'),l=n.querySelector('.sc-items');const lr=l.getBoundingClientRect();
    return {box:[Math.round(nb.width),Math.round(nb.height)],summary:{h:s.clientHeight,scroll:s.scrollHeight},
      items:[...l.querySelectorAll('li')].map(li=>li.getBoundingClientRect().bottom<=lr.bottom+0.5),
      itemsBottomGap:Math.round(nb.bottom-lr.bottom),itemsH:Math.round(lr.height),
      refs:[...l.querySelectorAll('.sc-item-ref,.sc-item-link-ref')].map(e=>({text:e.textContent,w:Math.round(e.getBoundingClientRect().width),cut:e.scrollWidth>e.clientWidth}))}})()`);
  const prefabLayout=(oid)=>evaluate(`(()=>{const b=document.getElementById('win-body'),l=document.getElementById('win-items');
    const lr=l.getBoundingClientRect();
    return {viewport:innerHeight,sizer:document.getElementById('win-sizer').style.height,bodyRect:Math.round(document.body.getBoundingClientRect().height),
      body:{h:b.clientHeight,scroll:b.scrollHeight,top:b.scrollTop,more:b.hasAttribute('data-more')},
      items:[...l.querySelectorAll('.win-item')].map(li=>li.getBoundingClientRect().bottom<=Math.min(innerHeight,lr.bottom)+0.5),
      itemsBottomGap:Math.round(innerHeight-lr.bottom),itemsH:Math.round(lr.height),htmlScroll:document.scrollingElement.scrollTop,
      refs:[...l.querySelectorAll('.win-ref')].map(e=>({text:e.textContent,w:Math.round(e.getBoundingClientRect().width),cut:e.scrollWidth>e.clientWidth})),
      labelHeights:[...l.querySelectorAll('.win-main')].map(e=>Math.round(e.getBoundingClientRect().height))}})()`,S[oid]);
  const iframeOf=(oid)=>evaluate(`(()=>{const f=document.querySelector('[data-object-id="${oid}"] iframe');const s=f.parentElement;
    return {styleH:f.style.height,drawnH:Math.round(f.getBoundingClientRect().height),slotH:Math.round(s.getBoundingClientRect().height)}})()`);
  out.steps.themeDefault=await theme('circuit-board');await sleep(600);
  out.steps.parity={legacy:await legacyLayout(),prefab:await prefabLayout('pw-1'),frame:await iframeOf('pw-1')};
  out.steps.tall={prefab:await prefabLayout('pw-tall'),frame:await iframeOf('pw-tall')};
  /* Polices réellement rastérisées (pas la pile CSS) : CSS.getPlatformFontsForNode. */
  const fonts=async(sel,session)=>{try{await send('DOM.enable',{},session);await send('CSS.enable',{},session);
    const doc=await send('DOM.getDocument',{depth:-1},session);
    const q=await send('DOM.querySelector',{nodeId:doc.root.nodeId,selector:sel},session);
    if(!q.nodeId)return null;const f=await send('CSS.getPlatformFontsForNode',{nodeId:q.nodeId},session);return f.fonts.map(x=>x.familyName)}
    catch(error){return 'error: '+String(error).slice(0,120)}};
  out.steps.fonts={legacySummary:await fonts('[data-object-id="legacy-1"] .sc-summary li'),legacyItem:await fonts('[data-object-id="legacy-1"] .sc-item-label'),
    prefabBody:await fonts('#win-body li',S['pw-1']),prefabItem:await fonts('.win-label',S['pw-1'])};
  out.steps.shots=[];
  out.steps.shots.push(await shot('side-by-side-circuit.png',await union(['legacy-1','pw-1'])));
  out.steps.theme=await theme('cosmos');await sleep(900);
  out.steps.shots.push(await shot('side-by-side-cosmos.png',await union(['legacy-1','pw-1'])));
  out.steps.cosmos={legacy:await legacyLayout(),prefab:await prefabLayout('pw-1')};
  out.steps.themeBack=await theme('circuit-board');await sleep(900);
  out.steps.shots.push(await shot('window-taller-than-content.png',await union(['pw-tall'])));

  /* Molette dans le corps du cadre : le corps défile, la page ne bouge pas, le fondu tombe au bout. */
  const fb=await box('[data-object-id="pw-1"] iframe');
  const pageView=()=>evaluate(`document.querySelector('[data-object-id="pw-1"]').style.transform`);
  const v0=await pageView();
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:fb.cx,y:fb.y+30});
  for(let i=0;i<4;i++){await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:fb.cx,y:fb.y+30,deltaX:0,deltaY:400});await sleep(250)}
  await sleep(500);
  out.steps.wheel={after:await prefabLayout('pw-1'),pageMoved:(await pageView())!==v0,
    lastLineVisible:await evaluate(`(()=>{const b=document.getElementById('win-body');const r=[...b.querySelectorAll('p')].pop().getBoundingClientRect();return r.bottom<=b.getBoundingClientRect().bottom+1})()`,S['pw-1'])};
  out.steps.shots.push(await shot('window-body-scrolled-to-end.png',await union(['legacy-1','pw-1'])));

  /* --- F5 : anneau de focus clavier du document ------------------------------------------- */
  const db=await box('[data-object-id="doc-1"] iframe');
  await click(db.cx,db.cy);await sleep(300);
  await evaluate(`(document.activeElement&&document.activeElement.blur(),true)`,S['doc-1']);
  await key('Tab','Tab',9);await sleep(300);
  out.steps.docFocus=await evaluate(`(()=>{const d=document.getElementById('doc');const cs=getComputedStyle(d);
    return {active:document.activeElement===d,focusVisible:d.matches(':focus-visible'),outline:cs.outlineStyle+' '+cs.outlineWidth+' '+cs.outlineColor,
      offset:cs.outlineOffset,top:Math.round(d.getBoundingClientRect().top)}})()`,S['doc-1']);
  out.steps.shots.push(await shot('document-focus-ring.png',await union(['doc-1'])));

  /* --- F8 : tableau choisi, puis défilé et choisi ----------------------------------------- */
  const tb=await box('[data-object-id="tbl-1"] iframe');
  const row3=await evaluate(`(()=>{const r=document.querySelectorAll('tbody tr')[2].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`,S['tbl-1']);
  await click(tb.x+row3.x,tb.y+row3.y);await sleep(500);
  const tblState=()=>evaluate(`({top:document.scrollingElement.scrollTop,selected:[...document.querySelectorAll('tbody tr')].findIndex(r=>r.getAttribute('aria-selected')==='true')})`,S['tbl-1']);
  out.steps.tableSelected=await tblState();
  const a=await shot('table-selected.png',await union(['tbl-1']));
  for(let i=0;i<14;i++)await key('ArrowDown','ArrowDown',40);
  await key('Enter','Enter',13);await sleep(600);
  out.steps.tableScrolled=await tblState();
  const b=await shot('table-scrolled-selected.png',await union(['tbl-1']));
  const hash=f=>createHash('sha256').update(readFileSync(join(OUT,f))).digest('hex').slice(0,16);
  out.steps.tableShotsDiffer={selected:hash(a),scrolled:hash(b),differ:hash(a)!==hash(b)};
  out.steps.shots.push(a,b);
  out.errors=out.console.filter(c=>c.type==='error'||c.type==='exception');
}catch(error){out.error=String(error&&error.stack||error)}
finally{
  writeFileSync(join(OUT,'layout-results.json'),JSON.stringify(out,null,1));
  console.log(JSON.stringify({error:out.error||null,steps:out.steps,errors:out.errors},null,0));
  chrome.kill();await sleep(800);try{rmSync(profile,{recursive:true,force:true})}catch(_){}
  process.exit(0);
}
