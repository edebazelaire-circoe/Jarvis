/* Harnais CDP pour `test_status_centre_browser.py` (orbital UI, Slice 06).

   Chrome sans tete, la page SERVIE (composee comme `ControlCenter.index`), un
   `fetch` double installe avant le premier script : `/api/status` (pastilles,
   Boards, scene allumee), `/api/background` et son acquittement, les captures
   (`/api/captures/status`, `/start`, `/{id}/stop`, `/targets`) et la scene
   (`/api/scene` instantane, `/api/scene/patches` tenu jusqu'a une commande,
   `/api/scene/commands` applique et rejoue en patch). Les vrais modules de la
   page lisent ces reponses : pastilles, popover, indicateurs, scene, oeil.

   Usage : node _status_centre_browser.mjs <page.html> <chrome.exe> <@plan.json|planJSON>
   Une etape : {width, height, theme?, reducedMotion?, seed?, actions:[...]} ;
   `seed` (objet) est fusionne dans l'etat du double AVANT la navigation.
   Actions (chacune pousse {name, value} dans `results`) :
     ["eval", name, expr, waitMs]
     ["click", name, selector, waitMs]     vrai clic souris au centre
     ["rclick", name, selector, waitMs]    vrai clic droit au centre
     ["key", name, key, waitMs, shift?]    vraie frappe sur l'element focalise
     ["drag", name, selector, waitMs, [dx,dy]]  vrai glisser souris depuis le centre
     ["shot", name, path, waitMs]
     ["move", name, selector, waitMs]      vrai deplacement souris au centre, sans clic (survol)
     ["press", name, selector, waitMs]     vrai appui gauche au centre, tenu (lire l'etat pendant l'appui)
     ["release", name, selector, waitMs]   relachement au centre
     ["dragto", name, selector, waitMs, target]  vrai glisser souris du centre de `selector`
                                           au centre de `target` (un objet tenu contre une commande)
     ["tabto", name, selector, waitMs, max]  vraies frappes Tab jusqu'a ce que le focus soit dans
                                           `selector` (au plus `max`) ; rend chaque arret
                                           {name, inside, selected, visible, ring} (orbital UI, Slice 09)
     ["axe", name, selector, waitMs, file] axe-core (fichier `file`) sur `selector` : violations
   Options d'etape (Slice 09) : `forcedColors` (forced-colors: active), `scale`
   (deviceScaleFactor : 720x450 a l'echelle 2 = une fenetre 1440x900 zoomee a 200 %).
   Une cible de souris (click, rclick, move, press, release, dragto) peut etre un point `[x, y]` au lieu d'un
   selecteur : un endroit vide de la page (le haut-gauche, libre depuis la Slice 02 de
   jarvis-board-ui-wheel-dossier-refactor), pour un clic « ailleurs » ou un survol qui s'eloigne.
   Graines (Slice 09) : `live` (bandeau GPT-Live du statut), `mode` (bloc `interaction_mode`), `presentation`
   (releve de Voice du statut, Slice 02 : la ligne de seance de la carte Board), `railRows` (lignes du rail,
   fusionnees sur une ligne type), `boardArtifacts` (artefacts du Board actif), `previews`
   ({artifact_id: svg}) ; `POST /api/captures/screenshot` rend une capture d'ecran complete,
   et la route bornee `/api/artifacts/{id}/payload` est doublee la ou la page la lit (un <img>).
   Sortie : un tableau JSON, un objet par etape {results, console, calls, bodies}. */
import {spawn} from 'node:child_process';
import {mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {disposeChromeOnExit} from './_cdp_profile.mjs';

const [,,PAGE,CHROME,PLAN]=process.argv;
const plan=JSON.parse(PLAN.startsWith('@')?readFileSync(PLAN.slice(1),'utf-8'):PLAN);

/* Le serveur double. `window.__sc` porte son etat ; `seed` (sessionStorage)
   le prepare avant que la page ne demande quoi que ce soit. */
const SERVER=`(()=>{
  let seed={};try{seed=JSON.parse(sessionStorage.getItem('__scSeed')||'{}')}catch(_){seed={}}
  const now=Date.now();
  const iso=ms=>new Date(ms).toISOString();
  const obj=(id,kind,extra)=>Object.assign({schema_version:1,object_id:id,kind,category:kind,exec_state:'running',
    representation:kind==='window'?'window':'point',geometry:null,layer:kind==='window'?220:100,order:0,
    visibility:'visible',disposition:'active',constraints:{placed_by:'user',pinned_by_user:false},origin:'runtime',
    work_ref:null,payload:{title:id,summary:'',items:[]}},extra||{});
  const S=window.__sc=Object.assign({
    counts:{failed:2,attention:1,done:3,said:1},seq:5,
    events:null,acks:[],calls:[],bodies:[],
    captures:[],
    sceneOn:true,revision:3,
    objects:[
      obj('jobj_star','agent',{geometry:{x:-60,y:-30,w:6,h:6},payload:{title:'Analyse',summary:'',items:[]}}),
      obj('jobj_hidden','agent',{visibility:'hidden',geometry:{x:40,y:-34,w:6,h:6},payload:{title:'Recherche masquée',summary:'',items:[]}}),
      obj('jobj_hidden_win','window',{visibility:'hidden',representation:'window',geometry:{x:-20,y:10,w:44,h:26},payload:{title:'Rapport masqué',summary:'Contenu',items:[]}}),
      obj('jobj_nowhere','agent',{visibility:'hidden',payload:{title:'Sans place',summary:'',items:[]}}),
    ],
    waiters:[],
    /* Boards (test_global_launcher_browser.py) : la bascule change le Board actif du statut. */
    boards:[{board_id:'default',title:'Jarvis',status:'active'}],activeBoard:'default',
    /* Slice 09 : bandeau GPT-Live, rail, artefacts du Board, apercus. */
    live:null,railRows:null,boardArtifacts:[],previews:{},payloads:[],mode:null,presentation:null,
  },seed);
  /* La route bornee des apercus, la ou la page la lit : la source d'un <img>
     (meme double que _presentation_rail_browser.mjs). Sans apercu seme, une
     image unie : la vignette existe, son contenu n'est pas l'objet du test. */
  const slide=(a,b,title)=>'<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="'+a+'"/><stop offset="1" stop-color="'+b+'"/></linearGradient></defs><rect width="1280" height="720" fill="url(#g)"/><text x="96" y="380" font-family="Segoe UI,sans-serif" font-size="120" font-weight="700" fill="#fff">'+title+'</text></svg>';
  const srcDesc=Object.getOwnPropertyDescriptor(HTMLImageElement.prototype,'src');
  /* Le getter rend l'adresse de la route, comme le navigateur la resoudrait : la page compare sa source a l'URL qu'elle a posee. */
  Object.defineProperty(HTMLImageElement.prototype,'src',{configurable:true,enumerable:true,get(){return this.__jvRoute||srcDesc.get.call(this)},set(v){
    this.__jvRoute=null;
    const m=String(v).match(/^\\/api\\/artifacts\\/([^/]+)\\/payload$/);
    if(m){S.payloads.push(m[1]);this.__jvRoute=new URL(String(v),location.href).href;v='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(S.previews[m[1]]||slide('#134e5e','#71b280','Capture'));}
    srcDesc.set.call(this,v)}});
  /* Une capture semee avec \`age_s\` : ses heures sont posees par rapport a maintenant. */
  S.captures=S.captures.map(c=>c.age_s!=null?Object.assign({},c,{created_at:iso(now-c.age_s*1000-1000),activated_at:iso(now-c.age_s*1000)}):c);
  const labels={failed:'Sous-agent en échec : Build',attention:'Point à vérifier : diapositive 3',done:'Tâche terminée : Résumé',said:'Résultat non dit : Notes'};
  const eventsOf=()=>{
    if(S.events)return S.events;
    const out=[];let seq=0;
    for(const [category,n] of Object.entries(S.counts))for(let i=0;i<n;i+=1)
      out.push({seq:++seq,ts:iso(now-60000*seq),category,kind:'agent.subagent.finished',label:labels[category]+' '+(i+1),detail:'',task_id:'',unread:true});
    return out;
  };
  const json=(status,body)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  const snapshot=()=>({source:'core',core_reachable:true,scene:{state:'ready',code:null,saturated:false,objects:S.objects.length,object_limit:512},
    scene_id:'scene',epoch:'e1',revision:S.revision,
    snapshot:{schema_version:1,scene_id:'scene',revision:S.revision,objects:S.objects,relations:[],archived_ids:[]},error:null});
  const release=patches=>{const w=S.waiters.splice(0);for(const fn of w)fn(patches)};
  window.fetch=async(path,init)=>{
    const method=(init&&init.method)||'GET';
    const url=String(path);
    if(url!=='/api/status'&&!url.startsWith('/api/captures/status'))S.calls.push(method+' '+url.split('?')[0]);
    if(init&&init.body&&method!=='GET'){let b=null;try{b=JSON.parse(init.body)}catch(_){b=init.body}S.bodies.push({path:url,body:b})}
    if(url==='/api/status'){
      const counts={};let unread=0;for(const [k,v] of Object.entries(S.counts))if(v>0){counts[k]=v;unread+=v}
      return json(200,{voice_state:'idle',voice_online:true,manual_wake_key:S.wakeKey||'f9',voice_turn_mode:'server',
        agent:{name:'claude',state:'running'},agent_cli:'claude',error_count:S.errorCount||0,subagents:S.subagents||null,
        background:{seq:S.seq,unread,counts,sources:[]},
        boards:{available:true,active:{board_id:S.activeBoard,title:(S.boards.find(b=>b.board_id===S.activeBoard)||{}).title||S.activeBoard,
          board_kind:(S.boards.find(b=>b.board_id===S.activeBoard)||{}).board_kind},jarvis_session_id:'jsess_1',bindings:[],error:null},
        scene:{enabled:S.sceneOn,source:'core'},scene_limits:{job_cancel_timeout_s:30},live:S.live,interaction_mode:S.mode||null,
        presentation:S.presentation||null});
    }
    /* Raccourcis d'interface (valeurs par défaut de jarvis/runtime/shortcuts.py). */
    if(url==='/api/shortcuts')return json(200,{values:{ui_settings:'s',ui_close:'Escape',ui_panel_errors:'e',ui_panel_trace:'t',ui_panel_agents:'a'}});
    if(url.startsWith('/api/background?'))return json(200,{ok:true,seq:S.seq,acknowledged:0,unread:1,counts:S.counts,events:eventsOf().filter(e=>S.counts[e.category]>0)});
    if(url==='/api/background/ack'){const b=JSON.parse(init.body);S.acks.push(b);S.counts[b.category]=0;S.seq+=1;
      return json(200,{ok:true,seq:S.seq,acknowledged:1});}
    if(url.startsWith('/api/captures/status'))return json(200,{captures:S.captures,stuck:[],recent:[]});
    if(url==='/api/captures/targets')return json(200,{screen:{available:true,devices:[{token:'default',label:'Écran principal',primary:true}]},
      audio:{available:true,devices:[{token:'default',label:'Micro de Voice',default:true}]}});
    /* Une capture d'ecran prise (Slice 09) : la capture et son artefact complets, comme Core les rend. */
    if(url==='/api/captures/screenshot'&&method==='POST'){
      const at=iso(Date.now());
      return json(200,{capture:{capture_id:'jcap_shot',channel:'screen',mode:'one_shot',state:'complete',device:'default',created_at:at},
        artifact:{artifact_id:'jart_'+'c'.repeat(32),kind:'screenshot',state:'complete',mime_type:'image/png',has_payload:true,created_at:at,title:'Capture d’écran'}});
    }
    if(/^\\/api\\/captures\\/[^/]+\\/stop$/.test(url)){const id=decodeURIComponent(url.split('/')[3]);
      S.captures=S.captures.filter(c=>c.capture_id!==id);return json(200,{capture:{capture_id:id,state:'complete'}});}
    if(url==='/api/scene')return json(200,snapshot());
    if(url.startsWith('/api/scene/patches'))return new Promise(resolve=>{
      const timer=setTimeout(()=>{S.waiters=S.waiters.filter(f=>f!==fn);resolve(json(200,{source:'core',core_reachable:true,
        scene:{state:'ready',code:null},scene_id:'scene',epoch:'e1',revision:S.revision,resync_required:false,more:false,patches:[],error:null}))},20000);
      const fn=patches=>{clearTimeout(timer);resolve(json(200,{source:'core',core_reachable:true,scene:{state:'ready',code:null},
        scene_id:'scene',epoch:'e1',revision:S.revision,resync_required:false,more:false,patches,error:null}))};
      S.waiters.push(fn);
    });
    if(url==='/api/scene/commands'){
      const command=JSON.parse(init.body);
      const target=S.objects.find(o=>o.object_id===command.object_id);
      /* Slice 09 : un objet tenu puis lache, applique et rejoue (il se redessine a sa place commise). */
      if(command.op==='set_geometry'&&target){
        target.geometry=command.geometry;S.revision+=1;
        const put={schema_version:1,revision:S.revision,ops:[{op:'put_object',object:target}]};
        setTimeout(()=>release([put]),50);
        return json(200,{outcome:'applied',revision:S.revision});
      }
      if(command.op==='set_visibility'&&target){
        target.visibility=command.visibility;S.revision+=1;
        const put={schema_version:1,revision:S.revision,ops:[{op:'put_object',object:target}]};
        setTimeout(()=>release([put]),50);
        return json(200,{outcome:'applied',revision:S.revision});
      }
      return json(200,{outcome:'applied',revision:S.revision});
    }
    if(url.split('?')[0]==='/api/boards')return json(200,{boards:S.boards,active_board_id:S.activeBoard});
    if(url==='/api/boards/switch'&&method==='POST'){S.activeBoard=JSON.parse(init.body).board_id;return json(200,{changed:true});}
    if(url==='/api/sessions/current')return json(200,{session:{jarvis_session_id:'jsess_1',started_at:iso(now),visited_board_ids:[S.activeBoard]}});
    if(url.startsWith('/api/work')&&!url.startsWith('/api/workspace'))return json(200,{items:[]});
    /* Le rail actif de l'espace de travail (zone droite) : deux presentations, pour qu'il soit mesure. */
    if(url==='/api/presentation-studio/rail'&&method==='GET'){
      /* La premiere est en travail : le rail se montre sans mode presentation. */
      const row=(n,title)=>({presentation_id:'pst_'+String(n).repeat(32),title,active_variant_id:'psv_'+String(n).repeat(32),
        variant_count:2,engine:'remotion',type:{engine:'remotion'},revision:1,updated_at:iso(now-3600000*n),hidden:false,archived:false,
        preview:null,unreviewed:null,work:n===1?{state:'working',label:'presentation_edit',age_s:3}:{state:'done',label:'',age_s:null}});
      const rows=S.railRows?S.railRows.map((r,i)=>Object.assign(row(i+1,r.title||'Présentation '+(i+1)),r)):[row(1,'Présentation Jarvis'),row(2,'Bilan trimestriel')];
      return json(200,{presentations:S.rail===false?[]:rows,problems:[],work_revision:1,
        ui:{seq:0,request:null,reported:null},playing:null});
    }
    if(url==='/api/presentation-studio/rail/display-state')return json(200,{seq:0});
    if(url.startsWith('/api/workspace/artifacts?'))return json(200,{artifacts:S.boardArtifacts,scope:{board_id:S.activeBoard},next_cursor:null});
    return json(404,{error:{code:'http_error',message:'not stubbed '+url}});
  };
  return 'ok';
})()`;

const profile=mkdtempSync(join(tmpdir(),'jarvis-status-centre-cdp-'));
const port=9222+Math.floor(Math.random()*500);
const chrome=spawn(CHROME,[
  '--headless=new',`--remote-debugging-port=${port}`,`--user-data-dir=${profile}`,
  '--no-first-run','--no-default-browser-check','--disable-gpu',
  '--disable-extensions','--allow-file-access-from-files','--hide-scrollbars','about:blank',
],{stdio:'ignore'});
disposeChromeOnExit(chrome,profile);
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
      consoleLines.push({type:'exception',text:JSON.stringify(msg.params.exceptionDetails).slice(0,600)});
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
  const center=async selector=>{
    if(Array.isArray(selector))return {x:selector[0],y:selector[1]};
    const box=await evaluate(`(()=>{const el=document.querySelector(${JSON.stringify(selector)});if(!el)return null;
      const r=el.getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2}})()`);
    if(!box)throw new Error(`selecteur absent : ${selector}`);
    return box;
  };
  const mouse=async(selector,button)=>{
    const {x,y}=await center(selector);
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'none'});
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button,buttons:button==='right'?2:1,clickCount:1});
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x,y,button,buttons:0,clickCount:1});
  };
  const KEYS={Tab:9,Enter:13,Escape:27,F10:121,ContextMenu:93,' ':32,
    End:35,Home:36,ArrowLeft:37,ArrowUp:38,ArrowRight:39,ArrowDown:40};
  const key=async(name,shift)=>{
    const code=KEYS[name]||0;
    const base={key:name,code:name==='ContextMenu'?'ContextMenu':name,windowsVirtualKeyCode:code,nativeVirtualKeyCode:code,modifiers:shift?8:0};
    await send('Input.dispatchKeyEvent',{type:'rawKeyDown',...base});
    /* Entree active un bouton sur son caractere, comme un vrai clavier. */
    if(name==='Enter')await send('Input.dispatchKeyEvent',{type:'char',text:String.fromCharCode(13),unmodifiedText:String.fromCharCode(13),...base});
    await send('Input.dispatchKeyEvent',{type:'keyUp',...base});
  };
  const drag=async(selector,[dx,dy])=>{
    const {x,y}=await center(selector);
    await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'none'});
    await send('Input.dispatchMouseEvent',{type:'mousePressed',x,y,button:'left',buttons:1,clickCount:1});
    for(let i=1;i<=8;i+=1){
      await send('Input.dispatchMouseEvent',{type:'mouseMoved',x:x+dx*i/8,y:y+dy*i/8,button:'left',buttons:1});
      await sleep(30);
    }
    await send('Input.dispatchMouseEvent',{type:'mouseReleased',x:x+dx,y:y+dy,button:'left',buttons:0,clickCount:1});
  };
  await send('Page.enable');await send('Runtime.enable');
  await send('Page.addScriptToEvaluateOnNewDocument',{source:SERVER});
  const out=[];
  for(const step of plan){
    consoleLines.length=0;
    await send('Emulation.setEmulatedMedia',{features:[
      ...(step.reducedMotion?[{name:'prefers-reduced-motion',value:'reduce'}]:[]),
      ...(step.forcedColors?[{name:'forced-colors',value:'active'}]:[])]});
    await send('Emulation.setDeviceMetricsOverride',
      {width:step.width,height:step.height,deviceScaleFactor:step.scale||1,mobile:false});
    /* La graine passe par le stockage de session de l'origine du fichier :
       une premiere navigation la pose, la seconde la lit avant tout script. */
    const url='file:///'+PAGE.replace(/\\/g,'/');
    await send('Page.navigate',{url});
    await sleep(400);
    await evaluate(`(()=>{sessionStorage.setItem('__scSeed',${JSON.stringify(JSON.stringify(step.seed||{}))});
      try{localStorage.removeItem('jarvis.scene.view')}catch(_){};
      ${step.storage?`try{localStorage.setItem('jarvis.scene.view',${JSON.stringify(JSON.stringify(step.storage))})}catch(_){}`:''}
      return 1})()`);
    await send('Page.navigate',{url});
    await sleep(1800);
    if(step.theme)await evaluate(`(()=>{if(window.JarvisThemeAPI)window.JarvisThemeAPI.activate(${JSON.stringify(step.theme)},{persist:false});return 1})()`);
    await sleep(step.settleMs||1200);
    const results={};
    for(const action of (step.actions||[])){
      const [kind,name,arg,wait,extra]=action;
      try{
        if(kind==='eval')results[name]=await evaluate(arg);
        else if(kind==='click'){await mouse(arg,'left');results[name]='ok'}
        else if(kind==='rclick'){await mouse(arg,'right');results[name]='ok'}
        else if(kind==='key'){await key(arg,!!extra);results[name]='ok'}
        else if(kind==='drag'){await drag(arg,extra);results[name]='ok'}
        else if(kind==='dragto'){const from=await center(arg),to=await center(extra);await drag(arg,[to.x-from.x,to.y-from.y]);results[name]={from,to}}
        else if(kind==='press'||kind==='release'){const {x,y}=await center(arg);
          if(kind==='press')await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'none'});
          await send('Input.dispatchMouseEvent',{type:kind==='press'?'mousePressed':'mouseReleased',x,y,button:'left',buttons:kind==='press'?1:0,clickCount:1});results[name]='ok'}
        else if(kind==='move'){const {x,y}=await center(arg);await send('Input.dispatchMouseEvent',{type:'mouseMoved',x,y,button:'none'});results[name]='ok'}
        else if(kind==='tabto'){
          const stops=[];
          for(let i=0;i<(extra||40);i+=1){
            await key('Tab');await sleep(60);
            const seen=await evaluate(`(()=>{const a=document.activeElement;if(!a||a===document.body)return {name:'body',inside:false,visible:false,ring:false};
              const r=a.getBoundingClientRect(),cs=getComputedStyle(a);
              const hidden=!!a.closest('[hidden]')||cs.visibility==='hidden'||!(r.width>0&&r.height>0);
              const ring=(cs.outlineStyle!=='none'&&parseFloat(cs.outlineWidth)>0)||(!!cs.boxShadow&&cs.boxShadow!=='none');
              const label=a.getAttribute('aria-label')||a.title||(a.textContent||'').trim().slice(0,40);
              const cls=typeof a.className==='string'?a.className.split(' ')[0]:'';
              return {name:(a.id?'#'+a.id:a.tagName.toLowerCase()+(cls?'.'+cls:''))+' '+label,
                inside:!!a.closest(${JSON.stringify(arg)}),selected:a.classList.contains('sc-selected'),visible:!hidden&&r.right>0&&r.bottom>0&&r.left<innerWidth&&r.top<innerHeight,ring}})()`);
            stops.push(seen);
            if(seen.inside)break;
          }
          results[name]=stops;
        }
        else if(kind==='axe'){
          await evaluate(readFileSync(extra,'utf8'));
          results[name]=await evaluate(`axe.run(document.querySelector(${JSON.stringify(arg)}),{resultTypes:['violations']})
            .then(r=>r.violations.map(v=>({id:v.id,impact:v.impact,help:v.help,nodes:v.nodes.slice(0,6).map(n=>n.target.join(' ')),
              html:v.nodes.map(n=>n.html.slice(0,120))})))`);
        }
        else if(kind==='shot'){
          const shot=await send('Page.captureScreenshot',{format:'png'});
          writeFileSync(arg,Buffer.from(shot.data,'base64'));results[name]=arg;
        }
      }catch(error){results[name]={error:String(error.message||error)}}
      await sleep(wait||300);
    }
    const server=await evaluate(`({calls:window.__sc.calls,bodies:window.__sc.bodies,acks:window.__sc.acks})`);
    out.push({results,console:consoleLines.filter(l=>l.type==='error'||l.type==='exception'||/\[(scène|background|capture)\]/.test(l.text)),...server});
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
