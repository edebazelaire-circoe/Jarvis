/* Harnais CDP pour `test_board_alerts_browser.py` (handoff board-session, Slice 07).

   Meme mecanique que `_boards_browser.mjs` : Chrome sans tete, la page SERVIE,
   un `fetch` double. Le statut porte ici un bloc `background` (non-vus, et
   leurs Boards sources) et `/api/background` rend les alertes : le vrai
   `refreshStatus` nourrit les vraies pastilles, et le vrai « Aller au Board »
   passe par le vrai contrôle Boards.

   Usage : node _board_alerts_browser.mjs <page.html> <chrome.exe> <planJSON>
   Sortie : un tableau JSON, un objet par etape. */
import {spawn} from 'node:child_process';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN);

/* Le serveur double. Une alerte `failed` du Board `default` ; on est sur
   `board_b`. `window.__alerts` laisse l'etape piloter la bascule. */
const SERVER=`(()=>{
  const S=window.__alerts={active:'board_b',boards:[
    {board_id:'default',title:'Jarvis',status:'active'},
    {board_id:'board_b',title:'Projet B',status:'active'}],
    switchPlan:null,calls:[],bodies:[]};
  const json=(status,body)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  const title=()=>S.boards.find(b=>b.board_id===S.active).title;
  const event={seq:1,ts:new Date().toISOString(),category:'failed',kind:'agent.subagent.finished',
    label:'Sous-agent en échec après 4 s : Build',detail:'Build',task_id:'',board_id:'default',board_title:'Jarvis',unread:true};
  window.fetch=async(path,init)=>{
    const method=(init&&init.method)||'GET';S.calls.push(method+' '+path);
    if(init&&init.body)S.bodies.push({path,body:JSON.parse(init.body)});
    if(path==='/api/status')return json(200,{voice_state:'idle',voice_online:false,agent:{name:'claude',state:'running'},
      agent_cli:'claude',error_count:0,
      background:{seq:1,unread:1,counts:{failed:1},sources:[{board_id:'default',title:'Jarvis',counts:{failed:1}}]},
      boards:S.dropBoards?{available:false,active:null,jarvis_session_id:null,bindings:[],
        error:{code:'core_unreachable',message:'down'}}:{available:true,active:{board_id:S.active,title:title()},jarvis_session_id:'jsess_1',
        bindings:[{board_id:S.active,lifecycle:'foreground',agent_cli:'claude',closed:false}],error:null}});
    if(path.startsWith('/api/background?'))return json(200,{ok:true,seq:1,acknowledged:0,unread:1,counts:{failed:1},events:[event]});
    if(path.split('?')[0]==='/api/boards'&&!(init&&init.method&&init.method!=='GET'))return json(200,{boards:S.boards,active_board_id:S.active});
    if(path==='/api/boards/switch'){
      if(S.switchPlan==='fail')return json(502,{error:{code:'board_activation_failed',message:'host said no'}});
      await new Promise(r=>setTimeout(r,1500));
      S.active=JSON.parse(init.body).board_id;return json(200,{changed:true});
    }
    return json(404,{error:{code:'http_error',message:'not stubbed'}});
  };
  return 'ok';
})()`;

const READ=`(()=>{
  const q=s=>document.querySelector(s);
  const pill=q('#bgPills .bgpill');
  const pop=q('#bgPop');
  const row=q('#bgPop .bgrow');
  const go=q('#bgPop [data-bg-go]');
  const note=q('#bgPop .bggo-note');
  const rect=el=>{if(!el)return null;const r=el.getBoundingClientRect();return {l:r.left,t:r.top,r:r.right,b:r.bottom}};
  return {
    pill:pill?{cls:pill.className,label:pill.getAttribute('aria-label')}:null,
    popOpen:!!(pop&&!pop.hidden),
    chip:(q('#bgPop .bgboard')||{}).textContent||null,
    rowCls:row?row.className:null,
    go:go?{text:go.textContent,busy:go.getAttribute('aria-busy'),label:go.getAttribute('aria-label'),rect:rect(go)}:null,
    note:note&&!note.hidden?note.textContent:'',
    popRect:rect(pop),
    title:(q('#boardsTitle')||{}).textContent||null,
    calls:window.__alerts.calls.filter(c=>!c.endsWith('/api/status')),
    bodies:window.__alerts.bodies,
    viewport:{w:innerWidth,h:innerHeight},
  };
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-alerts-cdp-'));
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
    seen.console=consoleLines.filter(l=>l.type==='error'||l.type==='exception'||/\[(boards|background)\]/.test(l.text));
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
