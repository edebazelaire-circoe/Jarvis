/* Preuve navigateur de la Slice 05 (prefabs de base de la famille fenêtre) :
   Chrome RÉEL sans tête (`--headless=new`, profil jetable `--user-data-dir`),
   piloté par CDP (méthode des Slices 03-04), sur la page SERVIE par un vrai
   Control Center relié à un vrai Core isolés (ports de scratch 18993/18994).

   La page crée elle-même, comme l'utilisateur (`POST /api/scene/commands`) :
   - `legacy-1` : fenêtre classique (titre, résumé markdown, entrées) ;
   - `pw-1`     : `jarvis.window@1` avec le même titre, le même corps, les mêmes entrées ;
   - `doc-1`    : `jarvis.document@1`, un texte long (~11 000 caractères) ;
   - `tbl-1`    : `jarvis.table@1`, 8 colonnes × 64 lignes.
   Puis : côte à côte (les deux thèmes du Control Center), document lu jusqu'au
   bout au clavier dans le cadre, tableau choisi au clic et au clavier
   (`row_selected` lu dans l'anneau de Core), redimensionnement et ajustement.

   Usage : node browser_probe.mjs <url du CC> <chrome.exe> <dossier de sortie>
   Sortie : <dossier>/browser-results.json et les captures PNG. */
import {spawn} from 'node:child_process';
import {existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,URL_,CHROME,OUT]=process.argv;
const profile=mkdtempSync(join(tmpdir(),'jarvis-s05-cdp-'));
const chrome=spawn(CHROME,['--headless=new','--remote-debugging-port=0',`--user-data-dir=${profile}`,'--no-first-run',
  '--no-default-browser-check','--disable-gpu','--disable-extensions','--hide-scrollbars','about:blank'],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

const TITLE='Migration du stockage';
const BODY='Trois pistes pour **la migration** du stockage :\n\n- garder SQLite, ajouter un index ;\n- passer aux fichiers JSON par version ;\n- attendre la mesure de `scene.sqlite3`.';
const ITEMS=[
  {label:'Note de cadrage du stockage, version relue après la revue du 2 octobre',ref:'docs/local-data.md'},
  {label:'Mesure de la latence d’écriture en mode WAL sur le poste portable',url:'https://www.sqlite.org/wal.html',ref:'WAL'},
  {label:'Décision attendue'},
];
const LONG_DOC=['# Rapport de lecture intégrale','',
  'Ce document est **long à dessein** : il dépasse la fenêtre plusieurs fois et doit se lire en entier, au défilement ou au clavier.','',
  ...Array.from({length:18},(_,n)=>[`## Section ${n+1} — ${['Contexte','Mesures','Risques','Décision','Suite','Annexe'][n%6]}`,'',
    'La scène affiche des fenêtres dont le corps est un prefab : défini une fois, validé par Core, rendu dans un cadre isolé. '+
    'Chaque paragraphe passe à la ligne au lieu d’être coupé, et la position de lecture suit le défilement.','',
    `- point ${n+1}.1 : le texte reste sélectionnable et lisible ;`,`- point ${n+1}.2 : Page bas avance de 85 % de la hauteur visible ;`,
    `- point ${n+1}.3 : \`Fin\` mène à la dernière ligne.`,'',
    n%3===0?'> Une citation, pour vérifier les retraits et la teinte atténuée.\n':'',
  ].join('\n')),
  '## Fin du document','','Dernière ligne : FIN-DU-DOCUMENT.'].join('\n');
const COLUMNS=[{label:'Fichier'},{label:'Taille',align:'right'},{label:'Lignes',align:'right'},{label:'Statut',align:'center'},
  {label:'Auteur'},{label:'Modifié',align:'right'},{label:'Δ',align:'right'},{label:'Commentaire'}];
const ROWS=Array.from({length:64},(_,r)=>[`jarvis/module_${String(r+1).padStart(2,'0')}.py`,`${(r*37%90)+3},${r%10} Ko`,String(120+r*13),
  ['ok','modifié','nouveau'][r%3],['Clarice','Jarvis','Agent QA'][r%3],`${String(1+r%28).padStart(2,'0')}/10`,`${r%2?'+':'−'}${r*3%41}`,
  r%7===0?'Commentaire plus long qui doit passer à la ligne dans sa cellule sans élargir le tableau':'—']);

function upsert(id,title,geometry,payload,category){
  return {schema_version:1,op:'upsert_object',object_id:id,fields:{kind:'window',category:category||'research',representation:'window',
    geometry,payload:Object.assign({title,summary:'',items:[]},payload)}};
}
const COMMANDS=[
  upsert('legacy-1',TITLE,{x:-140,y:-66,w:56,h:44},{summary:BODY,items:ITEMS.map(i=>({label:i.label,ref:i.ref||'',url:i.url||''}))}),
  upsert('pw-1',TITLE,{x:-80,y:-66,w:56,h:44},{summary:'Repli de capture : trois pistes de migration.',
    prefab:{id:'jarvis.window',version:1,props:{},data:{body:BODY,items:ITEMS}}}),
  upsert('doc-1','Rapport de lecture',{x:-20,y:-66,w:56,h:64},{prefab:{id:'jarvis.document',version:1,props:{},data:{body:LONG_DOC}}},'doc'),
  upsert('tbl-1','Fichiers modifiés',{x:40,y:-66,w:96,h:70},{prefab:{id:'jarvis.table',version:1,props:{},data:{columns:COLUMNS,rows:ROWS}}},'code'),
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

  await send('Page.enable');await send('Runtime.enable');
  await send('Target.setAutoAttach',{autoAttach:true,waitForDebuggerOnStart:false,flatten:true});
  await send('Emulation.setDeviceMetricsOverride',{width:1600,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:URL_});
  await until(()=>evaluate("!!window.JarvisScene&&!!window.JarvisThemeAPI"),30000,'scene page');

  /* 0. Les quatre fenêtres, créées par la page comme l'utilisateur. */
  out.steps.created=[];
  for(const command of COMMANDS){
    out.steps.created.push(await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},
      body:${JSON.stringify(JSON.stringify(command))}}).then(async r=>({status:r.status,body:await r.json()}))`));
  }
  for(const objectId of ['pw-1','doc-1','tbl-1'])
    await until(()=>evaluate(`!!document.querySelector('[data-object-id="${objectId}"] .sc-prefab-slot iframe')`),30000,objectId+' frame');
  await until(async()=>(await inFrame('win',"document.querySelectorAll('.win-item').length"))===3,20000,'window items');
  await until(async()=>(await inFrame('tbl',"document.querySelectorAll('#tbl-body tr').length"))===64,20000,'table rows');
  await until(async()=>(await inFrame('doc',"document.querySelectorAll('.jv-md-h').length"))>10,20000,'document blocks');
  await sleep(900);/* ajustement des hauteurs (resize -> fitBrainWindows) */

  /* 1. Côte à côte, thème Circuit imprimé (défaut) puis Cosmos. */
  out.steps.themeDefault=await theme('circuit-board');await sleep(400);
  const pair=await union(['legacy-1','pw-1']);
  out.steps.pairCircuit=await shot('side-by-side-circuit.png',pair);
  out.steps.overviewCircuit=await shot('overview-circuit.png');
  out.steps.compare=await evaluate(`(()=>{const L=document.querySelector('[data-object-id="legacy-1"]'),W=document.querySelector('[data-object-id="pw-1"]');
    const labels=[...L.querySelectorAll('.sc-item-label')].map(e=>({text:e.textContent.slice(0,30),clipped:e.scrollWidth>e.clientWidth+1}));
    const r=(el)=>{const b=el.getBoundingClientRect();return {w:Math.round(b.width),h:Math.round(b.height)}};
    return {legacy:r(L),prefab:r(W),legacyLabels:labels,head:[L.querySelector('.sc-cat').textContent,W.querySelector('.sc-cat').textContent],
      titles:[L.querySelector('.sc-wtitle').textContent,W.querySelector('.sc-wtitle').textContent]}})()`);
  out.steps.prefabWindow=await inFrame('win',`(()=>{const items=[...document.querySelectorAll('.win-item')];
    const lh=parseFloat(getComputedStyle(items[0]).lineHeight);
    return {items:items.length,rowHeights:items.map(i=>Math.round(i.getBoundingClientRect().height)),lineHeight:lh,
      wrapped:items.map(i=>i.querySelector('.win-label').getBoundingClientRect().height>lh*1.5),
      host:document.querySelector('.win-host')&&document.querySelector('.win-host').textContent,
      accent:getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim(),
      strong:document.querySelector('#win-body strong').textContent,font:getComputedStyle(document.body).fontFamily,
      bodyColor:getComputedStyle(document.querySelector('.jv-md-p')).color,
      labelColor:getComputedStyle(document.querySelector('.win-label')).color,
      overflow:document.documentElement.scrollHeight>document.documentElement.clientHeight}})()`);
  out.steps.legacyTypography=await evaluate(`(()=>{const s=document.querySelector('[data-object-id="legacy-1"] .sc-summary p');
    const l=document.querySelector('[data-object-id="legacy-1"] .sc-item-label');
    return {font:getComputedStyle(s).fontFamily,bodyColor:getComputedStyle(s).color,size:getComputedStyle(s).fontSize,
      labelColor:getComputedStyle(l).color,labelSize:getComputedStyle(l).fontSize}})()`);
  out.steps.themeCosmos=await theme('cosmos');await sleep(500);
  out.steps.pairCosmos=await shot('side-by-side-cosmos.png',await union(['legacy-1','pw-1']));
  out.steps.overviewCosmos=await shot('overview-cosmos.png');
  out.steps.radius=await evaluate(`getComputedStyle(document.querySelector('[data-object-id="pw-1"]')).borderRadius`);
  await theme('circuit-board');await sleep(400);

  /* 2. Document : plus long que sa fenêtre, il défile dans le cadre ; clavier dans le cadre jusqu'à la fin. */
  const docSel='[data-object-id="doc-1"]';
  out.steps.docLayout=await evaluate(`(()=>{const el=document.querySelector('${docSel}'),slot=el.querySelector('.sc-prefab-slot'),f=slot.querySelector('iframe');
    return {window:Math.round(el.getBoundingClientRect().height),slotScroll:[slot.scrollHeight,slot.clientHeight],
      frame:Math.round(f.getBoundingClientRect().height),reported:f.style.height}})()`);
  const docState=()=>inFrame('doc',`(()=>{const s=document.scrollingElement;const last=[...document.querySelectorAll('.jv-md-p')].pop();
    const r=last.getBoundingClientRect();return {top:Math.round(s.scrollTop),max:s.scrollHeight-s.clientHeight,view:s.clientHeight,
      lastVisible:r.bottom<=innerHeight+1&&r.top>=0,lastText:last.textContent,track:document.getElementById('doc-track').dataset.on,
      progress:document.getElementById('doc-progress').style.transform,focus:document.activeElement&&document.activeElement.id}})()`);
  out.steps.docStart=await docState();
  const docFrame=await box(`${docSel} iframe`);
  await click(docFrame.x+40,docFrame.y+30);await sleep(150);
  out.steps.docShotTop=await shot('document-top.png',await union(['doc-1']));
  out.steps.docKeys=[];
  for(const [k,code,vk] of [['PageDown','PageDown',34],['PageDown','PageDown',34],['PageUp','PageUp',33],['End','End',35]]){
    await key(k,code,vk);await sleep(120);out.steps.docKeys.push({key:k,...await docState()});
  }
  out.steps.docShotEnd=await shot('document-end.png',await union(['doc-1']));
  await key('Home','Home',36);await sleep(120);
  out.steps.docHome=await docState();
  /* Molette dans le cadre : le texte défile, pas la page. */
  await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:docFrame.x+60,y:docFrame.y+80,deltaX:0,deltaY:600});await sleep(300);
  out.steps.docWheel=await docState();

  /* 3. Tableau 8 × 64 : en-tête fixe au défilement, choix au clic puis au clavier -> `row_selected` dans Core. */
  const tblSel='[data-object-id="tbl-1"]';
  out.steps.tableShot=await shot('table-8x64.png',await union(['tbl-1']));
  const tblFrame=await box(`${tblSel} iframe`);
  const rowPoint=await inFrame('tbl',"(()=>{const r=document.querySelectorAll('#tbl-body tr')[2].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()");
  await click(tblFrame.x+rowPoint.x,tblFrame.y+rowPoint.y);await sleep(200);
  await key('ArrowDown','ArrowDown',40);await key('ArrowDown','ArrowDown',40);await key('Enter','Enter',13);await sleep(200);
  out.steps.tableSelectedShot=await shot('table-selected.png',await union(['tbl-1']));
  await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:tblFrame.x+200,y:tblFrame.y+120,deltaX:0,deltaY:500});await sleep(350);
  out.steps.table=await inFrame('tbl',`(()=>{const th=document.querySelector('th').getBoundingClientRect();
    const sel=[...document.querySelectorAll('#tbl-body tr')].map((r,i)=>r.getAttribute('aria-selected')==='true'?i:-1).filter(i=>i>=0);
    const cols=[...document.querySelectorAll('th')].map(t=>Math.round(t.getBoundingClientRect().width));
    return {rows:document.querySelectorAll('#tbl-body tr').length,cols:cols.length,colWidths:cols,headerTop:Math.round(th.top),
      scrollTop:Math.round(document.scrollingElement.scrollTop),selected:sel,foot:document.getElementById('tbl-foot').textContent,
      tableWidth:Math.round(document.getElementById('tbl').getBoundingClientRect().width),view:innerWidth,
      focus:document.activeElement&&document.activeElement.tagName}})()`);
  out.steps.tableScrolledShot=await shot('table-scrolled-selected.png',await union(['tbl-1']));
  out.steps.events=await until(async()=>{const b=await evaluate("fetch('/api/prefabs/events?object_id=tbl-1&limit=10',{cache:'no-store'}).then(r=>r.json())");
    const list=b.events||b.entries||b;return Array.isArray(list)&&list.length>=2?list:null},8000,'two row_selected events');

  /* 4. Redimensionner : plus petit, le cadre suit et défile lui-même (jamais le conteneur) ; plus grand, il remplit. */
  const pwSel='[data-object-id="pw-1"]';
  out.steps.fitBefore=await stored('pw-1');
  const pwTitle=await box(`${pwSel} .sc-wtitle`);
  await click(pwTitle.cx,pwTitle.cy);await sleep(200);
  out.steps.pwSelected=await evaluate(`document.querySelector('${pwSel}').classList.contains('sc-selected')`);
  const grip=await box(`${pwSel} .sc-grip`);
  out.steps.gripHit=await evaluate(`(()=>{const e=document.elementFromPoint(${grip.cx-2},${grip.cy-2});return e?(e.className&&e.className.baseVal!==undefined?e.className.baseVal:e.className)+'|'+e.tagName:null})()`);
  const layoutOf=()=>evaluate(`(()=>{const el=document.querySelector('${pwSel}'),slot=el.querySelector('.sc-prefab-slot'),f=slot.querySelector('iframe');
    return {window:Math.round(el.getBoundingClientRect().height),slotScroll:[slot.scrollHeight,slot.clientHeight],frame:Math.round(f.getBoundingClientRect().height)}})()`);
  const frameOf=()=>inFrame('win',"({scroll:document.scrollingElement.scrollHeight,view:document.scrollingElement.clientHeight,width:innerWidth,"+
    "rows:[...document.querySelectorAll('.win-item')].map(i=>Math.round(i.getBoundingClientRect().height))})");
  /* Agrandir puis rétrécir par la couture `JarvisScene.frames` (chemin Bare Hands, comme la Slice 04). Agrandie, la fenêtre montre tout. */
  const resize=(dw,dh)=>evaluate(`(()=>{const held=JarvisScene.frames.begin('pw-1');if(!held)return null;
    const box={...held.box,w:held.box.w+${dw},h:held.box.h+${dh}};
    JarvisScene.frames.preview('pw-1',box,'resize');JarvisScene.frames.commit('pw-1',box,'resize');return {from:held.box,to:box}})()`);
  out.steps.mouseGripAttempt='mouse drag on .sc-grip does not complete under headless CDP (see EVIDENCE.md); resize goes through JarvisScene.frames';
  out.steps.grow=await resize(24,22);await sleep(700);
  out.steps.grown={stored:await stored('pw-1'),layout:await layoutOf(),frame:await frameOf()};
  out.steps.grownShot=await shot('window-grown.png',await union(['pw-1']));
  /* Accent et densité changés par l'utilisateur : même cadre, mis à jour par message. */
  await evaluate(`document.querySelector('${pwSel} iframe').__s05='mark'`);
  out.steps.patched=await evaluate(`fetch('/api/scene/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(
    ${JSON.stringify(upsert('pw-1',TITLE,undefined,{summary:'Repli de capture : trois pistes de migration.',
      prefab:{id:'jarvis.window',version:1,props:{accent:'#f0cf78',density:'compact'},data:{body:BODY,items:ITEMS}}}))})}).then(r=>r.json())`);
  await until(async()=>(await inFrame('win',"getComputedStyle(document.documentElement).getPropertyValue('--jv-accent').trim()"))==='#f0cf78',8000,'accent update');
  out.steps.afterPatch={sameFrame:await evaluate(`document.querySelector('${pwSel} iframe').__s05==='mark'`),
    density:await inFrame('win',"document.getElementById('win').dataset.density")};
  out.steps.patchedShot=await shot('window-accent-compact.png',await union(['pw-1']));
  /* Rétrécir : le cadre suit la fenêtre et défile lui-même, jamais le conteneur. */
  out.steps.shrink=await resize(-30,-40);await sleep(700);
  out.steps.shrunk={stored:await stored('pw-1'),layout:await layoutOf(),frame:await frameOf()};
  out.steps.shrunkShot=await shot('window-shrunk.png',await union(['pw-1']));
  out.steps.resizeLogs=out.console.filter(c=>/user_resized|user_moved/.test(c.text)).map(c=>c.text);
  out.steps.finalOverview=await shot('overview-final.png');
  ws.close();
}catch(error){out.error=String(error&&error.stack||error)}
finally{
  chrome.kill();await sleep(300);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome lâche son profil un peu plus tard */}
  writeFileSync(join(OUT,'browser-results.json'),JSON.stringify(out,null,2));
  console.log(JSON.stringify({error:out.error||null,steps:Object.keys(out.steps)}));
}
