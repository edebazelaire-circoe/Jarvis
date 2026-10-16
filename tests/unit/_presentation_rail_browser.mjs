/* Harnais CDP pour `test_control_center_presentation_rail_browser.py` (rail des presentations).

   Chrome sans tete, la page SERVIE (composee comme `ControlCenter.index`), une taille imposee. Le relais `/api/presentation-studio/*` est remplace,
   dans la page et avant tout script, par un double en memoire (`window.__rail`) : c'est l'interface qui est mesuree ici ; la chaine reelle
   jusqu'a Core est prouvee par `test_presentation_studio_rail.py` (vrai Core) et par la verification en bac a sable.

   Usage : node _presentation_rail_browser.mjs <page.html> <chrome.exe>
   Sortie : un objet JSON `{scenario: lectures}` sur la sortie standard. */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit} from './_cdp_profile.mjs';

const [,,PAGE,CHROME]=process.argv;

const FAKE=`(()=>{
  const PID=n=>'pst_'+String(n).padStart(32,'0');
  const rows=[
    {presentation_id:PID(1),title:'Lancement produit automne',active_variant_id:'psv_'+'1'.repeat(32),variant_count:2,engine:'remotion',revision:1,updated_at:'2026-10-10T10:00:00Z',hidden:false,archived:false,work:{state:'working',label:'presentation_edit',age_s:3}},
    {presentation_id:PID(2),title:'Bilan',active_variant_id:'psv_'+'2'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T09:00:00Z',hidden:false,archived:false,work:{state:'done',label:'',age_s:null}},
    {presentation_id:PID(3),title:'Roadmap',active_variant_id:'psv_'+'3'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T08:00:00Z',hidden:false,archived:false,work:{state:'problem',label:'presentation_edit',age_s:30,code:'presentation_studio_storage_io',message:'disque plein'}},
    {presentation_id:PID(4),title:'Brouillon cache',active_variant_id:'psv_'+'4'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T07:00:00Z',hidden:true,archived:false,work:{state:'done',label:'',age_s:null}},
    {presentation_id:PID(5),title:'Ancienne',active_variant_id:'psv_'+'5'.repeat(32),variant_count:1,engine:'remotion',revision:1,updated_at:'2026-10-10T06:00:00Z',hidden:false,archived:true,work:{state:'done',label:'',age_s:null}},
  ];
  if(location.hash==='#calm')rows.forEach(r=>{r.work={state:'done',label:'',age_s:null}});
  const rail=window.__rail={rows,calls:[],reports:[],ui:{seq:0,request:null,reported:null},down:false,refuse:null,playing:null,commands:[]};
  const json=(status,obj)=>new Response(JSON.stringify(obj),{status,headers:{'Content-Type':'application/json'}});
  const sorted=()=>[...rows].sort((a,b)=>(a.archived-b.archived)||(a.hidden-b.hidden));
  window.fetch=async(url,init)=>{
    const u=String(url),method=(init&&init.method)||'GET';
    if(!u.startsWith('/api/presentation-studio'))throw new TypeError('Failed to fetch');
    rail.calls.push({method,url:u,body:init&&init.body||null});
    if(rail.down)throw new TypeError('Failed to fetch');
    if(u==='/api/presentation-studio/rail'&&method==='GET')
      return json(200,{presentations:sorted(),problems:[],work_revision:1,ui:rail.ui,playing:rail.playing});
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
  const items=qa('#presentationRail .jvr-item').map(b=>({id:b.dataset.id,state:b.dataset.state,open:b.dataset.open,dim:b.dataset.dim||null,name:b.querySelector('.jvr-name').textContent,
    full:b.title,label:b.getAttribute('aria-label'),dot:getComputedStyle(b.querySelector('.jvr-dot')).backgroundColor,dotAnim:getComputedStyle(b.querySelector('.jvr-dot')).animationName,
    thumb:b.querySelector('.jvr-thumb').textContent}));
  const win=q('#jvPresWindow');
  return {visible:!!host&&!host.hidden,box:box(host),items,
    folds:qa('#presentationRail .jvr-fold').map(b=>b.textContent.trim()),
    note:(q('#presentationRail .jvr-note')||{}).textContent||'',noteHidden:!!(q('#presentationRail .jvr-note')||{}).hidden,
    menu:(()=>{const m=q('.jvr-menu');return m&&!m.hidden?{items:[...m.querySelectorAll('button')].map(b=>({act:b.dataset.act,text:b.textContent,disabled:b.getAttribute('aria-disabled')})),head:(m.querySelector('.jvr-mhead')||{}).textContent,box:box(m)}:null})(),
    dialog:(()=>{const d=q('.jvr-dialog-back');return d&&!d.hidden?{title:(d.querySelector('h2')||{}).textContent,text:(d.querySelector('p')||{}).textContent,buttons:[...d.querySelectorAll('button')].map(b=>b.textContent),input:(d.querySelector('input')||{}).value||null}:null})(),
    window:win&&!win.hidden?{box:box(win),title:win.querySelector('.jvw-title').textContent,chip:win.querySelector('.jvw-chip').textContent,pips:win.querySelectorAll('.jvw-pip').length,
      count:win.querySelector('.jvw-count').textContent,veil:win.querySelector('.jvw-veil').hidden?'':win.querySelector('.jvw-veil strong').textContent,
      dot:getComputedStyle(win.querySelector('.jvw-dot')).backgroundColor,buttons:[...win.querySelectorAll('.jvw-bar button')].map(b=>b.textContent)}:null,
    studioClass:document.documentElement.classList.contains('jvr-studio'),
    api:window.JarvisPresentationRail?window.JarvisPresentationRail.state():null,
    voice:((q('#presentationRail .jvr-voice')||{}).dataset||{}).v||'',
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
  const KEYS={Enter:{code:'Enter',keyCode:13,text:'\r'},Escape:{code:'Escape',keyCode:27},ArrowRight:{code:'ArrowRight',keyCode:39},ArrowDown:{code:'ArrowDown',keyCode:40}};
  const press=async key=>{const k=KEYS[key];
    await send('Input.dispatchKeyEvent',{type:'keyDown',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode,text:k.text});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key,code:k.code,windowsVirtualKeyCode:k.keyCode,nativeVirtualKeyCode:k.keyCode})};
  const at=async selector=>{
    const p=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
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
  await click('.jvr-dialog button[data-danger]');
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
  await poll1(`window.JarvisPresentationRail.state().pref==='shown'`);await sleep(300);
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
  out.narrow=await evaluate(READ);

  /* 13. Studio sur un ecran etroit : le rail se range en bande de vignettes. */
  await load(1000,600,PRES_BOARD+";JarvisPresentationRail.setPref('auto')");
  await evaluate(`window.dispatchEvent(new CustomEvent('jarvis:studio-explorer-opened',{detail:{}}))`);await sleep(250);
  out.studio_narrow=await evaluate(READ);
  out.studio_narrow.slim=await evaluate(`document.documentElement.classList.contains('jvr-slim')`);
  await load(800,600,PRES_BOARD+";JarvisPresentationRail.setPref('auto')");
  await evaluate(`window.dispatchEvent(new CustomEvent('jarvis:studio-explorer-opened',{detail:{}}))`);await sleep(250);
  out.studio_tiny=await evaluate(READ);

  ws.close();
  process.stdout.write(JSON.stringify({results:out,console:consoleLines}));
}catch(error){
  process.stderr.write('PARTIAL '+JSON.stringify(out).slice(0,6000)+' | '+String(error.stack||error)+' | '+JSON.stringify(consoleLines).slice(0,3000));process.exitCode=1;
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
