/* Harnais CDP pour `test_boards_hud_browser.py` (handoff board-session, Slice 06).

   Chrome sans tete, une taille imposee, la page SERVIE (composee comme
   `ControlCenter.index`), et un `fetch` double qui repond `/api/status` et les
   routes Boards : le vrai `refreshStatus` de la page nourrit donc le vrai
   module, au vrai battement d'une seconde. On releve des RECTANGLES, des
   STYLES CALCULES et `elementFromPoint` — ce qu'une lecture de la feuille ne
   peut pas prouver (la barre du haut coupe les evenements de pointeur).

   Usage : node _boards_browser.mjs <page.html> <chrome.exe> <planJSON>
   Sortie : un tableau JSON, un objet par etape. */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);

/* Le serveur double, pose avant tout appel de la page. `window.__boards`
   laisse l'etape piloter la reponse de la bascule. */
const SERVER=`(()=>{
  const S=window.__boards={active:'default',boards:[
    {board_id:'default',title:'Jarvis',status:'active'},
    {board_id:'board_b',title:'Projet Atlas — refonte du tableau de bord',status:'active'}],
    switchPlan:null,calls:[]};
  const json=(status,body)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  const title=()=>S.boards.find(b=>b.board_id===S.active).title;
  window.fetch=async(path,init)=>{
    const method=(init&&init.method)||'GET';S.calls.push(method+' '+path);
    if(path==='/api/status')return json(200,{voice_state:'idle',voice_online:false,agent:{name:'claude',state:'running'},
      agent_cli:'claude',error_count:0,background:null,
      boards:{available:true,active:{board_id:S.active,title:title()},jarvis_session_id:'jsess_1',
        bindings:[{board_id:S.active,lifecycle:'foreground',agent_cli:'claude',closed:false}],error:null}});
    if(path==='/api/boards')return json(200,{boards:S.boards,active_board_id:S.active});
    if(path==='/api/sessions/current')return json(200,{session:{jarvis_session_id:'jsess_1',
      started_at:new Date().toISOString(),visited_board_ids:['default']}});
    if(path==='/api/boards/switch'){
      if(S.switchPlan==='hang')return new Promise(()=>{});
      if(S.switchPlan==='fail')return json(502,{error:{code:'board_activation_failed',message:'host said no'}});
      S.active=JSON.parse(init.body).board_id;return json(200,{changed:true});
    }
    return json(404,{error:{code:'http_error',message:'not stubbed'}});
  };
  return 'ok';
})()`;

const READ=`(()=>{
  const seen={};
  const box=(name,el)=>{
    if(!el){seen[name]=null;return}
    const r=el.getBoundingClientRect();
    if(!r.width&&!r.height){seen[name]=null;return}
    seen[name]={l:r.left,t:r.top,r:r.right,b:r.bottom,w:r.width,h:r.height,z:getComputedStyle(el).zIndex};
  };
  const q=s=>document.querySelector(s);
  box('trigger',q('#boardsButton'));box('state',q('.topbar .state'));box('dock',q('.dock'));
  box('panel',q('#boardsPanel'));box('brand',q('.topbar .brand'));
  const t=q('#boardsButton');
  if(t){const r=t.getBoundingClientRect();const hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
    seen.triggerHit=!!(hit&&t.contains(hit))}
  const p=q('#boardsPanel');
  if(p&&!p.hidden){const r=p.getBoundingClientRect();const hit=document.elementFromPoint(r.right-20,r.top+r.height/2);
    seen.panelHit=!!(hit&&p.contains(hit))}
  seen.title=(q('#boardsTitle')||{}).textContent||null;
  seen.sub=(q('#boardsSub')||{}).textContent||null;
  seen.tone=q('#boardsHud')&&q('#boardsHud').getAttribute('data-bd-tone');
  seen.rows=[...document.querySelectorAll('#boardsList [data-bd-action=switch]')].map(b=>({
    id:b.getAttribute('data-board-id'),current:b.getAttribute('aria-current')==='true'}));
  seen.note=(()=>{const n=q('#boardsNote');return n&&!n.hidden?n.textContent:''})();
  const wait=q('#boardsHud .bd-wait');
  seen.motion={sweep:wait?getComputedStyle(wait,'::after').animationName:null,
    pop:p?getComputedStyle(p).animationName:null};
  seen.viewport={w:innerWidth,h:innerHeight};
  return seen;
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-boards-cdp-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu',
  '--disable-extensions','--allow-file-access-from-files','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
const sleep=ms=>new Promise(r=>setTimeout(r,ms));

try{
  const target=await poll(`http://127.0.0.1:${port}/json/list`);
  const ws=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((ok,ko)=>{ws.onopen=ok;ws.onerror=()=>ko(new Error('websocket refuse'))});
  let id=0;const pending=new Map();const consoleLines=[];
  ws.onmessage=event=>{
    const msg=JSON.parse(event.data);
    if(msg.method==='Runtime.consoleAPICalled')
      consoleLines.push({type:msg.params.type,text:msg.params.args.map(a=>a.value??a.description??'').join(' ')});
    if(msg.method==='Runtime.exceptionThrown')
      consoleLines.push({type:'exception',text:JSON.stringify(msg.params.exceptionDetails).slice(0,400)});
    if(msg.id&&pending.has(msg.id)){
      const {ok,ko}=pending.get(msg.id);pending.delete(msg.id);
      msg.error?ko(new Error(JSON.stringify(msg.error))):ok(msg.result);
    }
  };
  const send=(method,params={})=>new Promise((ok,ko)=>{
    const mine=++id;pending.set(mine,{ok,ko});ws.send(JSON.stringify({id:mine,method,params}));
  });
  const evaluate=async expression=>{
    const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
    if(r.exceptionDetails)throw new Error(r.exceptionDetails.exception?.description||JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  await send('Page.enable');await send('Runtime.enable');
  /* Le double de `fetch` doit etre en place AVANT le premier `refreshStatus`. */
  await send('Page.addScriptToEvaluateOnNewDocument',{source:SERVER});
  const out=[];
  for(const step of plan){
    consoleLines.length=0;
    await send('Emulation.setEmulatedMedia',{features:step.reducedMotion
      ?[{name:'prefers-reduced-motion',value:'reduce'}]:[]});
    await send('Emulation.setDeviceMetricsOverride',
      {width:step.width,height:step.height,deviceScaleFactor:1,mobile:false});
    await send('Page.navigate',{url:'file:///'+PAGE.replace(/\\/g,'/')});
    await sleep(1400);
    const results={};
    for(const [name,expr,wait] of (step.actions||[])){
      results[name]=await evaluate(expr);
      await sleep(wait||300);
    }
    const seen=await evaluate(READ);
    seen.results=results;
    seen.console=consoleLines.filter(l=>l.type==='error'||l.type==='exception'||/\[boards\]/.test(l.text));
    out.push(seen);
  }
  ws.close();
  process.stdout.write(JSON.stringify(out));
}finally{
  chrome.kill();
  try{rmSync(profile,{recursive:true,force:true})}catch(_){/* Windows tient le dossier */}
}

async function poll(url){
  for(let i=0;i<100;i+=1){
    try{
      const list=await (await fetch(url)).json();
      const page=list.find(t=>t.type==='page');
      if(page&&page.webSocketDebuggerUrl)return page;
    }catch(_){/* Chrome n ecoute pas encore */}
    await sleep(150);
  }
  throw new Error('Chrome n a pas ouvert son port de debogage');
}
