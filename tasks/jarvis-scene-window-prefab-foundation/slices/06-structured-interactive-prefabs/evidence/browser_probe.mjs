/* Preuve navigateur de la Slice 06 (`jarvis.checklist`) : Chrome RÉEL sans tête
   (`--headless=new`, profil jetable `--user-data-dir`), piloté par CDP (méthode
   des Slices 03-05), sur la page SERVIE par un vrai Control Center relié à un
   vrai Core isolés (ports de scratch 18993/18994).

   - la page crée, comme l'utilisateur (`POST /api/scene/commands`), `ck-1`
     (6 éléments, une note, un déjà coché) ;
   - a11y : rôles, `aria-checked`, noms, barre de progression, un seul arrêt de
     tabulation, focus visible ;
   - coche à la souris puis au clavier (flèches, Espace) ; écriture lue dans
     Core ; complétion -> `checklist_completed` une fois dans l'anneau ;
   - rechargement -> état gardé (celui de Core) ;
   - Jarvis remplace la liste puis change l'accent par HTTP sur Core (acteur
     `brain`, jeton) -> le MÊME iframe se met à jour (marqueur conservé) ;
     enfin Jarvis vide la liste -> état vide dans le même cadre ;
   - captures dans les deux thèmes du Control Center.
   Aucun glisser : seulement des clics et des touches dans le cadre.

   Usage : node browser_probe.mjs <url du CC> <chrome.exe> <dossier de sortie> <url de Core> <fichier du jeton>
   Sortie : <dossier>/browser-results.json et les captures PNG. */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT,CORE,TOKEN_FILE]=process.argv;
const profile=mkdtempSync(join(tmpdir(),'jarvis-s06-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const ITEMS=[
  {id:'cadrage',label:'Relire la note de cadrage du stockage',done:true},
  {id:'wal',label:'Mesurer la latence d’écriture en mode WAL sur le poste portable',
   note:'Trois mesures : à froid, après 1 000 écritures, après redémarrage.\nNoter la médiane.'},
  {id:'index',label:'Ajouter l’index sur scene_objects(updated_at)'},
  {id:'sauvegarde',label:'Vérifier la sauvegarde automatique .bak avant migration'},
  {id:'revue',label:'Faire relire la migration'},
  {id:'decision',label:'Décider : SQLite ou fichiers JSON par version'},
];
const BRAIN_ITEMS=[
  {id:'n1',label:'Nouvelle liste écrite par Jarvis'},
  {id:'n2',label:'Deuxième point, déjà fait',done:true},
  {id:'n3',label:'Troisième point',note:'Ajouté pendant que la fenêtre était ouverte.'},
];
function upsert(id,title,geometry,prefab){
  return {schema_version:1,op:'upsert_object',object_id:id,fields:{kind:'window',category:'research',representation:'window',
    geometry,payload:{title,summary:'Liste de contrôle',items:[],prefab}}};
}
const COMMANDS=[
  upsert('ck-1','Migration du stockage',{x:-90,y:-60,w:64,h:56},{id:'jarvis.checklist',version:1,props:{},data:{items:ITEMS}}),
];

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
  let id=0;const pending=new Map();const sessions=new Map();const contexts=new Map();
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
    /* Deux cadres sandboxés peuvent partager une cible : on garde chaque contexte d'exécution (un par document). */
    if(msg.method==='Runtime.executionContextCreated')contexts.set(`${msg.sessionId||''}:${msg.params.context.id}`,
      {session:msg.sessionId||null,id:msg.params.context.id,origin:msg.params.context.origin,main:!!(msg.params.context.auxData&&msg.params.context.auxData.isDefault)});
    if(msg.method==='Runtime.executionContextDestroyed')contexts.delete(`${msg.sessionId||''}:${msg.params.executionContextId}`);
    if(msg.method==='Runtime.executionContextsCleared')for(const k of [...contexts.keys()])if(k.startsWith(`${msg.sessionId||''}:`))contexts.delete(k);
    if(msg.id&&pending.has(msg.id)){const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result)}
  };
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
  /* Un cadre (origine opaque, hors processus) se lit dans sa session attachée ; on le reconnaît à une condition sur son document. */
  const inFrame=async(match,expression)=>{
    for(const ctx of [...contexts.values()]){
      if(!ctx.main)continue;/* un document par contexte ; celui de la page ne répond pas à `match` */
      try{const r=await send('Runtime.evaluate',{expression:`(${match})?(${expression}):null`,returnByValue:true,awaitPromise:true,contextId:ctx.id},ctx.session||undefined);
        if(r.exceptionDetails)continue;
        const value=r.result.value;
        if(value!==null&&value!==undefined)return value}catch(_){/* contexte parti */}
    }
    return null;
  };
  const MAIN="document.getElementById('ck')&&document.querySelectorAll('.ck-item').length>0";
  const box=(selector)=>evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;
    const r=el.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height,cx:r.x+r.width/2,cy:r.y+r.height/2}})()`);
  const mouse=async(type,x,y,buttons)=>send('Input.dispatchMouseEvent',{type,x,y,button:'left',buttons:buttons??(type==='mouseReleased'?0:1),clickCount:1});
  const click=async(x,y)=>{await mouse('mouseMoved',x,y,0);await mouse('mousePressed',x,y);await mouse('mouseReleased',x,y)};
  const key=async(k,code,vk,modifiers)=>{const extra=modifiers?{modifiers}:{};
    await send('Input.dispatchKeyEvent',{type:'rawKeyDown',key:k,code:code||k,windowsVirtualKeyCode:vk,...extra});
    if(k===' ')await send('Input.dispatchKeyEvent',{type:'char',text:' ',key:' ',code:'Space',windowsVirtualKeyCode:32});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:k,code:code||k,windowsVirtualKeyCode:vk,...extra});await sleep(80)};
  const shot=async(name,clip)=>{const r=await send('Page.captureScreenshot',clip?{format:'png',clip:{...clip,scale:1}}:{format:'png'});
    writeFileSync(join(OUT,name),Buffer.from(r.data,'base64'));return name};
  const union=async(ids)=>{const boxes=[];for(const objectId of ids)boxes.push(await box(`[data-object-id="${objectId}"]`));
    const x=Math.max(0,Math.min(...boxes.map(b=>b.x))-14),y=Math.max(0,Math.min(...boxes.map(b=>b.y))-14);
    return {x,y,width:Math.max(...boxes.map(b=>b.x+b.w))+14-x,height:Math.max(...boxes.map(b=>b.y+b.h))+14-y}};
  const theme=(name)=>evaluate(`(JarvisThemeAPI.activate(${JSON.stringify(name)}),document.documentElement.dataset.jarvisTheme)`);
  const stored=(objectId)=>evaluate(`fetch('/api/scene',{cache:'no-store'}).then(r=>r.json()).then(b=>{
    const o=b.snapshot.objects.find(o=>o.object_id===${JSON.stringify(objectId)});
    return o?{revision:b.revision,items:o.payload.prefab.data.items.map(i=>[i.id,!!i.done]),props:o.payload.prefab.props}:null})`);
  const ring=()=>evaluate("fetch('/api/prefabs/events?object_id=ck-1&limit=50',{cache:'no-store'}).then(r=>r.json()).then(b=>b.events.map(e=>[e.seq,e.event,e.class,e.outcome,e.payload&&e.payload.count]))");
  const frameState=()=>inFrame(MAIN,`(()=>{const rows=[...document.querySelectorAll('.ck-item')];const a=document.activeElement;
    const track=document.getElementById('ck-track');
    return {labels:rows.map(r=>r.querySelector('.ck-label').textContent),checked:rows.map(r=>r.getAttribute('aria-checked')),
      tabindex:rows.map(r=>r.getAttribute('tabindex')),focus:rows.indexOf(a),focusVisible:a&&a.matches?a.matches(':focus-visible'):false,
      focusShadow:a&&a.classList&&a.classList.contains('ck-item')?getComputedStyle(a).boxShadow:null,
      count:document.getElementById('ck-count').textContent,notice:document.getElementById('ck-notice').textContent,
      progress:[track.getAttribute('aria-valuenow'),track.getAttribute('aria-valuemax'),track.getAttribute('aria-valuetext')],
      ratio:getComputedStyle(document.getElementById('ck-fill')).transform,
      accent:getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim(),
      boxBg:getComputedStyle(rows[0].querySelector('.ck-box')).backgroundColor,
      complete:document.getElementById('ck').hasAttribute('data-complete')}})()`);
  const frameRect=()=>box('[data-object-id="ck-1"] iframe');
  /* Premier chargement : la page ajuste encore la fenêtre à son contenu. On attend deux lectures identiques. */
  const settled=async()=>{let last=null;for(let i=0;i<40;i++){const b=await frameRect();const k=b&&[b.x,b.y,b.w,b.h].map(Math.round).join(',');
    if(k&&k===last)return b;last=k;await sleep(250)}throw new Error('frame never settled')};
  const rowPoint=async(index)=>{const f=await frameRect();
    const p=await inFrame(MAIN,`(()=>{const r=document.querySelectorAll('.ck-item')[${index}].querySelector('.ck-label').getBoundingClientRect();return {x:r.x+12,y:r.y+r.height/2}})()`);
    return {x:f.x+p.x,y:f.y+p.y}};

  await send('Page.enable');await send('Runtime.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate("!!window.JarvisScene&&!!window.JarvisThemeAPI"),30000,'scene page');

  /* 0. Les deux listes, créées par la page comme l'utilisateur. */
  out.steps.created=[];
  for(const command of COMMANDS){
    out.steps.created.push(await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},
      body:${JSON.stringify(JSON.stringify(command))}}).then(async r=>({status:r.status,body:await r.json()}))`));
  }
  await until(async()=>(await inFrame(MAIN,"document.querySelectorAll('.ck-item').length"))===6,30000,'six rows');
  await sleep(900);/* ajustement des hauteurs */
  await theme('circuit-board');await sleep(300);
  out.steps.initial=await frameState();
  /* a11y : rôles, noms, description, barre de progression. */
  out.steps.a11y=await inFrame(MAIN,`(()=>{const rows=[...document.querySelectorAll('.ck-item')];
    const name=(r)=>document.getElementById(r.getAttribute('aria-labelledby')).textContent;
    const desc=(r)=>r.getAttribute('aria-describedby')?document.getElementById(r.getAttribute('aria-describedby')).textContent:null;
    const list=document.getElementById('ck-list');const track=document.getElementById('ck-track');
    return {group:[list.getAttribute('role'),list.getAttribute('aria-label')],roles:[...new Set(rows.map(r=>r.getAttribute('role')))],
      names:rows.map(name),descriptions:rows.map(desc).filter(Boolean),tabStops:rows.filter(r=>r.tabIndex===0).length,
      progressbar:[track.getAttribute('role'),track.getAttribute('aria-label'),track.getAttribute('aria-valuetext')],
      status:[document.getElementById('ck-notice').getAttribute('role'),document.getElementById('ck-notice').getAttribute('aria-live')],
      boxHidden:rows.every(r=>r.querySelector('.ck-box').getAttribute('aria-hidden')==='true')}})()`);
  await evaluate("document.querySelector('[data-object-id=\"ck-1\"] iframe').__s06='mark'");
  out.steps.shotInitial=await shot('checklist-initial.png',await union(['ck-1']));

  /* 1. Souris : clic sur la ligne 2 -> cochée tout de suite, écrite dans Core. */
  out.steps.settled=await settled();
  const p1=await rowPoint(1);
  out.steps.clickHit={point:p1,page:await evaluate(`(()=>{const e=document.elementFromPoint(${p1.x},${p1.y});return e?e.tagName+'.'+String(e.className&&e.className.baseVal!==undefined?e.className.baseVal:e.className):null})()`)};
  await click(p1.x,p1.y);
  out.steps.afterMouseClick=await frameState();/* lu juste après le clic, avant toute réponse attendue */
  out.steps.storedAfterMouse=await until(async()=>{const s=await stored('ck-1');return s&&s.items[1][1]?s:null},8000,'mouse tick stored');

  /* 2. Clavier : un seul arrêt de tabulation (Tab sort, Maj+Tab revient sur la ligne), flèches, Espace. */
  await key('Tab','Tab',9);
  out.steps.afterTab=await frameState();
  await key('Tab','Tab',9,8);/* Maj+Tab */
  out.steps.afterShiftTab=await frameState();
  await key('ArrowDown','ArrowDown',40);
  out.steps.afterArrow=await frameState();
  out.steps.shotFocus=await shot('checklist-keyboard-focus.png',await union(['ck-1']));
  await key(' ','Space',32);
  out.steps.afterSpace=await frameState();
  out.steps.storedAfterSpace=await until(async()=>{const s=await stored('ck-1');return s&&s.items[2][1]?s:null},8000,'space tick stored');
  /* Le reste au clavier, une touche à la fois : la liste se complète. */
  for(let i=3;i<6;i++){await key('ArrowDown','ArrowDown',40);await key(' ','Space',32);await sleep(250)}
  out.steps.storedComplete=await until(async()=>{const s=await stored('ck-1');return s&&s.items.every(i=>i[1])?s:null},8000,'all stored');
  out.steps.complete=await until(async()=>{const s=await frameState();return s.complete?s:null},8000,'complete');
  out.steps.ringAfterComplete=await until(async()=>{const r=await ring();return r.some(e=>e[1]==='checklist_completed')?r:null},8000,'completed in ring');
  out.steps.shotComplete=await shot('checklist-complete.png',await union(['ck-1']));
  /* Une mise à jour pendant que la liste est complète n'envoie rien de plus. */
  await sleep(600);
  out.steps.completedCount=(await ring()).filter(e=>e[1]==='checklist_completed').length;

  /* 3. Rechargement : l'état est celui de Core. */
  await send('Page.reload',{ignoreCache:true});
  await until(()=>evaluate("!!window.JarvisScene"),30000,'page after reload');
  await until(async()=>{const s=await frameState();return s&&s.checked.every(c=>c==='true')?s:null},30000,'state after reload');
  out.steps.reloaded=await frameState();
  await evaluate("document.querySelector('[data-object-id=\"ck-1\"] iframe').__s06='mark'");

  /* 4. Jarvis remplace la liste par HTTP sur Core (acteur brain) : même iframe, nouvelles lignes. */
  const token=readFileSync(TOKEN_FILE,'utf8').trim();
  const brain=async(prefab)=>{const r=await fetch(`${CORE}/v1/scene/commands`,{method:'POST',
    headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},
    body:JSON.stringify({...upsert('ck-1','Migration du stockage',undefined,prefab),actor:'brain'})});
    return {status:r.status,body:await r.json()}};
  const mountsBefore=out.console.filter(c=>/scene\.prefab_mounted/.test(c.text)).length;
  out.steps.brainReplace=await brain({id:'jarvis.checklist',version:1,props:{},data:{items:BRAIN_ITEMS}});
  out.steps.afterBrain=await until(async()=>{const s=await frameState();return s&&s.labels[0]===BRAIN_ITEMS[0].label?s:null},10000,'brain list');
  out.steps.sameFrameAfterBrain=await evaluate("document.querySelector('[data-object-id=\"ck-1\"] iframe').__s06==='mark'");
  out.steps.iframesInWindow=await evaluate("document.querySelectorAll('[data-object-id=\"ck-1\"] iframe').length");
  /* Accent changé par Jarvis : aucune ligne de source modifiée, même cadre. */
  out.steps.brainAccent=await brain({id:'jarvis.checklist',version:1,props:{accent:'#ff7a59'},data:{items:BRAIN_ITEMS}});
  out.steps.afterAccent=await until(async()=>{const s=await frameState();return s&&s.accent==='#ff7a59'?s:null},10000,'accent');
  out.steps.sameFrameAfterAccent=await evaluate("document.querySelector('[data-object-id=\"ck-1\"] iframe').__s06==='mark'");
  out.steps.mountsDuringBrain=out.console.filter(c=>/scene\.prefab_mounted/.test(c.text)).length-mountsBefore;
  out.steps.shotBrain=await shot('checklist-brain-accent.png',await union(['ck-1']));
  /* Une coche sur la liste de Jarvis passe (la base du cadre est à jour). */
  const p3=await rowPoint(0);
  await click(p3.x,p3.y);
  out.steps.storedAfterBrainTick=await until(async()=>{const s=await stored('ck-1');return s&&s.items[0][1]?s:null},8000,'tick on brain list');

  /* 5. Thème Cosmos. */
  out.steps.themeCosmos=await theme('cosmos');await sleep(500);
  out.steps.shotCosmos=await shot('checklist-cosmos.png',await union(['ck-1']));
  await theme('circuit-board');await sleep(300);
  out.steps.shotCircuit=await shot('checklist-circuit.png',await union(['ck-1']));
  /* 6. Jarvis vide la liste : état vide dit, dans le même cadre (lu dès la mise à jour). */
  out.steps.brainEmpty=await brain({id:'jarvis.checklist',version:1,props:{accent:'#ff7a59'},data:{items:[]}});
  out.steps.empty=await until(()=>inFrame("!!document.getElementById('ck')",`(()=>{const e=document.getElementById('ck-empty');
    return e.hasAttribute('hidden')?null:{text:e.textContent,rows:document.querySelectorAll('.ck-item').length,
      progressHidden:document.getElementById('ck-progress').hasAttribute('hidden')}})()`),10000,'empty state');
  out.steps.sameFrameWhenEmpty=await evaluate("!!document.querySelector('[data-object-id=\"ck-1\"] iframe')&&document.querySelector('[data-object-id=\"ck-1\"] iframe').__s06==='mark'");
  out.steps.shotEmpty=await shot('checklist-empty.png',await union(['ck-1']));
  /* Constat (hors Slice 06) : l'ajustement de la page réduit ensuite la fenêtre sous le seuil de lisibilité -> capsule. */
  await sleep(2000);
  out.steps.afterFit={stored:await evaluate(`fetch('/api/scene',{cache:'no-store'}).then(r=>r.json()).then(b=>b.snapshot.objects.find(o=>o.object_id==='ck-1').geometry)`),
    className:await evaluate(`document.querySelector('[data-object-id="ck-1"]').className`),
    iframes:await evaluate(`document.querySelectorAll('[data-object-id="ck-1"] iframe').length`)};
  out.steps.shotAfterFit=await shot('checklist-empty-after-fit.png',await union(['ck-1']));
  out.steps.ringFinal=await ring();
  out.steps.problems=out.console.filter(c=>c.type==='exception'||c.type==='error'||/prefab_error|prefab_event_failed/.test(c.text));
  ws.close();
}catch(error){out.error=String(error&&error.stack||error)}
finally{
  chrome.kill();await sleep(300);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome lâche son profil un peu plus tard */}
  writeFileSync(join(OUT,'browser-results.json'),JSON.stringify(out,null,2));
  console.log(JSON.stringify({error:out.error||null,steps:Object.keys(out.steps)}));
}
