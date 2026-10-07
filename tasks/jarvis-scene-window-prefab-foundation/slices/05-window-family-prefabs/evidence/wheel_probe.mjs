/* Contrôle complémentaire de la Slice 05 : la molette fait défiler le tableau 8 × 64 dans son cadre
   (avant et après le focus d'une ligne). Même harnais que browser_probe.mjs ; à lancer après lui (les
   fenêtres existent déjà dans la scène). Sortie : <dossier>/browser-results.json.

   Harnais d'origine :
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
  ['ok','modifié','nouveau'][r%3],['Utilisateur','Jarvis','Agent QA'][r%3],`${String(1+r%28).padStart(2,'0')}/10`,`${r%2?'+':'−'}${r*3%41}`,
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
  await until(async()=>(await inFrame('tbl',"document.querySelectorAll('#tbl-body tr').length"))===64,30000,'table rows');
  await sleep(800);
  const f=await box('[data-object-id="tbl-1"] iframe');
  const st=()=>inFrame('tbl',"Math.round(document.scrollingElement.scrollTop)");
  out.steps.before=await st();
  await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:f.x+200,y:f.y+120});
  await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:f.x+200,y:f.y+120,deltaX:0,deltaY:500});await sleep(800);
  out.steps.afterWheelNoFocus=await st();
  const p=await inFrame('tbl',"(()=>{const r=document.querySelectorAll('#tbl-body tr')[2].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()");
  await click(f.x+p.x,f.y+p.y);await sleep(200);
  await send('Input.dispatchMouseEvent',{type:'mouseWheel',x:f.x+200,y:f.y+120,deltaX:0,deltaY:500});await sleep(800);
  out.steps.afterWheelFocused=await st();
  ws.close();
}catch(error){out.error=String(error&&error.stack||error)}
finally{
  chrome.kill();await sleep(300);
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Chrome lâche son profil un peu plus tard */}
  writeFileSync(join(OUT,'browser-results.json'),JSON.stringify(out,null,2));
  console.log(JSON.stringify({error:out.error||null,steps:Object.keys(out.steps)}));
}
