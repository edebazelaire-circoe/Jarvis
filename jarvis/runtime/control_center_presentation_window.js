/* Fenêtre d'une présentation (rail des présentations) : afficher une présentation, la feuilleter, la mettre en plein écran, la jouer.

   Un clic sur une présentation du rail l'ouvre ici : une fenêtre flottante NON modale (la voix, le rail et le reste de la page restent
   utilisables ; rien n'est rendu inerte), déplaçable par son en-tête et redimensionnable. Elle montre la variante ACTIVE de la présentation, une
   slide à la fois, avec la bande des slides, et suit les corrections d'un agent (relecture toutes les 5 s : une nouvelle révision de la variante
   ou une autre variante active remplace l'affichage, la slide regardée est gardée quand elle existe encore).

   Ce que ce module est :
   - un LECTEUR : l'aperçu est un cadre de prefab en mode `preview` de l'hôte (`JarvisPrefabHost`), exactement celui de l'explorateur de
     variantes ; il lit `GET /api/presentation-studio/presentations/{id}` et n'écrit rien (aucun événement ne part du cadre) ;
   - le plein écran de l'hôte (`JarvisFullscreen.enter`, geste de l'utilisateur ou invite d'un clic), avec les flèches, Espace, Début, Fin ;
   - le départ de la lecture réelle : « Jouer » appelle `JarvisStudioPlayer.startRun(id, 'user_presenter')` (mêmes routes que la voix) puis la
     fenêtre se ferme (la scène de lecture prend la place) ; « Studio » ouvre l'explorateur de variantes (fenêtré, à côté du rail).

   Ce qu'il n'est PAS : une source de vérité (tout vient de Core et est relu), ni un second lecteur : la lecture reste celle de Core.
   Tout texte d'auteur (titres) passe par `textContent`. Chaque échec est dit à l'écran et journalisé (`[presentation-window] <clé> {json}`). */
(function(root){
  'use strict';

  const DOM=Object.freeze({hostId:'jvPresWindow',styleId:'jvPresWindowStyle',objectId:'jv-presentation-window',previewObjectId:'jv-presentation-window-stage'});
  const ROUTE='/api/presentation-studio/presentations';
  const ID_PRESENTATION=/^pst_[0-9a-f]{32}$/;
  const FOLLOW_MS=5000,REQUEST_TIMEOUT_MS=10000,PREVIEW_ARM_MS=60;
  const SVG_NS='http://www.w3.org/2000/svg';

  function cleanLine(value,max){
    const text=String(value==null?'':value).replace(/[\u0000-\u001f\u007f-\u009f​-‏‪-‮⁦-⁩]+/g,' ').replace(/\s+/g,' ').trim();
    return max&&text.length>max?text.slice(0,Math.max(1,max-1))+'…':text;
  }
  /* Les slides d'une variante (pur) : seulement ce que l'aperçu monte. */
  function scenesOf(variantDoc){
    const list=Array.isArray(variantDoc&&variantDoc.scenes)?variantDoc.scenes.slice(0,64):[];
    return list.filter(s=>s&&typeof s.scene_id==='string').map(s=>({
      id:s.scene_id,title:cleanLine(s.title,80)||'(sans titre)',prefab:s.prefab&&typeof s.prefab.id==='string'?s.prefab:null,
      props:s.props&&typeof s.props==='object'?s.props:{},data:s.data&&typeof s.data==='object'?s.data:{}}));
  }
  /* L'affichage choisi dans la réponse `{presentation, variants}` (pur) : la variante active, sinon la première. */
  function pickVariant(view){
    const presentation=view&&view.presentation,variants=Array.isArray(view&&view.variants)?view.variants:[];
    const active=presentation&&presentation.active_variant_id;
    return variants.find(v=>v&&v.variant_id===active)||variants[0]||null;
  }
  /* Faut-il redessiner ? (pur) : une autre variante, ou une autre révision. */
  function changed(previous,variant){
    if(!variant)return !!previous;
    if(!previous)return true;
    return previous.variantId!==variant.variant_id||previous.revision!==variant.revision;
  }

  const CSS=`
#${DOM.hostId}{position:fixed;z-index:34;top:92px;left:276px;width:min(62vw,980px);height:min(66vh,640px);min-width:360px;min-height:260px;max-width:calc(100vw - 380px);max-height:calc(100vh - 120px);resize:both;overflow:hidden;
  display:flex;flex-direction:column;background:rgba(4,9,13,.96);border:1px solid rgba(110,231,255,.3);border-radius:12px;color:#d8edf7;box-shadow:0 22px 70px rgba(0,0,0,.6);
  font:13px ui-monospace,SFMono-Regular,Consolas,monospace}
#${DOM.hostId}[hidden]{display:none}
#${DOM.hostId}:focus{outline:none}
#${DOM.hostId}:fullscreen{max-width:none;max-height:none;width:100vw;height:100vh;border:0;border-radius:0;resize:none;top:0;left:0}
#${DOM.hostId} *{box-sizing:border-box}
#${DOM.hostId} button{font:inherit;color:inherit;cursor:pointer}
#${DOM.hostId} .jvw-bar{display:flex;align-items:center;gap:8px;padding:8px 10px;border-bottom:1px solid rgba(110,231,255,.16);cursor:grab;touch-action:none}
#${DOM.hostId}:fullscreen .jvw-bar{cursor:default}
#${DOM.hostId} .jvw-dot{flex:none;width:9px;height:9px;border-radius:50%;background:var(--c,#43d68c)}
#${DOM.hostId} .jvw-title{flex:1;min-width:0;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
#${DOM.hostId} .jvw-chip{flex:none;padding:1px 7px;border:1px solid rgba(110,231,255,.25);border-radius:999px;color:#9db6c4;font-size:11px}
#${DOM.hostId} .jvw-btn{display:inline-flex;align-items:center;gap:6px;min-height:28px;padding:0 10px;border-radius:7px;border:1px solid rgba(110,231,255,.28);background:rgba(110,231,255,.08)}
#${DOM.hostId} .jvw-btn:hover,#${DOM.hostId} .jvw-btn:focus-visible{background:rgba(110,231,255,.18);outline:0}
#${DOM.hostId} .jvw-btn[aria-disabled=true]{opacity:.45;cursor:default}
#${DOM.hostId} .jvw-body{position:relative;flex:1;min-height:0;display:grid;background:#02050a}
#${DOM.hostId} .jvw-slot{position:absolute;inset:0;overflow:hidden}
#${DOM.hostId} .jvw-veil{position:absolute;inset:0;display:grid;place-content:center;gap:6px;text-align:center;padding:20px;background:rgba(2,5,10,.82);color:#9db6c4}
#${DOM.hostId} .jvw-veil[hidden]{display:none}#${DOM.hostId} .jvw-veil strong{color:#d8edf7;font-size:15px}
#${DOM.hostId} .jvw-foot{display:flex;align-items:center;gap:8px;padding:6px 10px;border-top:1px solid rgba(110,231,255,.16)}
#${DOM.hostId} .jvw-strip{flex:1;min-width:0;display:flex;gap:5px;overflow-x:auto;padding:2px}
#${DOM.hostId} .jvw-pip{flex:none;min-width:26px;height:24px;padding:0 6px;border-radius:6px;border:1px solid rgba(110,231,255,.2);background:rgba(110,231,255,.05);font-size:11px}
#${DOM.hostId} .jvw-pip[aria-current=true]{border-color:#6ee7ff;background:rgba(110,231,255,.2)}
#${DOM.hostId} .jvw-count{flex:none;color:#7190a0;font-size:11px}
`;

  function createWindow(deps){
    const d=deps||{};
    const doc=d.document||root.document;
    const win=d.window||root;
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=d.clearTimeout||(id=>clearTimeout(id));
    const sink=d.console||root.console;
    const notify=typeof d.toast==='function'?d.toast:null;
    const S={open:false,pid:null,title:'',state:'done',variantId:null,variantNumber:null,revision:null,scenes:[],index:0,status:'idle',error:null,generation:0,mounted:null,via:null};
    const ui={};
    let followTimer=null,previewHost=null,drag=null;

    function log(key,data,level){
      const line=`[presentation-window] ${key} ${JSON.stringify(data||{})}`;
      try{if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}}catch(_e){/* intentional */}
    }
    function tell(title,sub,kind){if(notify){try{notify({title,sub:sub||'',kind:kind||'info',ms:5000})}catch(_e){/* intentional */}}}
    function el(tag,cls,text){const n=doc.createElement(tag);if(cls)n.className=cls;if(text!=null)n.textContent=text;return n}
    function clear(n){while(n.firstChild)n.removeChild(n.firstChild)}
    function btn(label,onClick,title){const b=el('button','jvw-btn',label);b.type='button';if(title)b.title=title;b.addEventListener('click',onClick);return b}
    async function call(path){
      if(!fetchImpl)throw Object.assign(new Error('fetch indisponible'),{code:'network'});
      const controller=typeof AbortController==='function'?new AbortController():null;
      const timer=later(()=>{if(controller)controller.abort()},REQUEST_TIMEOUT_MS);
      try{
        const response=await fetchImpl(path,{cache:'no-store',signal:controller?controller.signal:undefined});
        let payload=null;try{payload=await response.json()}catch(_e){payload=null /* intentional: reported by status */}
        if(!response.ok){const e=payload&&payload.error||{};throw Object.assign(new Error(e.message||`HTTP ${response.status}`),{status:response.status,code:e.code||`http_${response.status}`})}
        return payload;
      }catch(error){if(error&&error.code)throw error;throw Object.assign(new Error(String(error&&error.message||error)),{code:'network'})}
      finally{cancelLater(timer)}
    }

    function build(){
      if(ui.host)return ui.host;
      if(!doc.getElementById(DOM.styleId)){const s=el('style');s.id=DOM.styleId;s.textContent=CSS;(doc.head||doc.documentElement).appendChild(s)}
      const host=doc.getElementById(DOM.hostId)||(()=>{const n=el('div');n.id=DOM.hostId;doc.body.appendChild(n);return n})();
      host.hidden=true;host.setAttribute('role','dialog');host.setAttribute('aria-label','Présentation');host.setAttribute('data-object-id',DOM.objectId);host.setAttribute('data-keep-live','true');host.tabIndex=-1;
      const bar=el('div','jvw-bar');
      ui.dot=el('span','jvw-dot');ui.title=el('span','jvw-title');ui.title.setAttribute('dir','auto');ui.chip=el('span','jvw-chip');
      ui.fs=btn('Plein écran',()=>{toggleFullscreen()},'Plein écran (F)');
      ui.play=btn('Jouer',()=>{play()},'Lancer la lecture de la présentation');
      ui.studio=btn('Studio',()=>{studio()},'Ouvrir le Studio : toutes les slides, les variantes, l’édition');
      ui.close=btn('Fermer',()=>{close({reason:'user'})},'Fermer (Échap)');
      bar.append(ui.dot,ui.title,ui.chip,ui.fs,ui.play,ui.studio,ui.close);
      const body=el('div','jvw-body');ui.slot=el('div','jvw-slot');ui.veil=el('div','jvw-veil');ui.veilTitle=el('strong');ui.veilText=el('span');ui.veil.append(ui.veilTitle,ui.veilText);body.append(ui.slot,ui.veil);
      const foot=el('div','jvw-foot');
      ui.prev=btn('◀',()=>step(-1),'Slide précédente (←)');ui.next=btn('▶',()=>step(1),'Slide suivante (→)');
      ui.strip=el('div','jvw-strip');ui.count=el('span','jvw-count');
      foot.append(ui.prev,ui.next,ui.strip,ui.count);
      host.append(bar,body,foot);
      host.addEventListener('keydown',onKey);
      bar.addEventListener('pointerdown',onDragStart);
      doc.addEventListener('fullscreenchange',()=>{if(S.open)render()});
      ui.host=host;return host;
    }
    function onDragStart(event){
      if(event.target.closest&&event.target.closest('button')||doc.fullscreenElement===ui.host)return;
      const r=ui.host.getBoundingClientRect();drag={dx:event.clientX-r.left,dy:event.clientY-r.top};
      if(ui.host.setPointerCapture){try{ui.host.setPointerCapture(event.pointerId)}catch(_e){/* intentional */}}
      const move=e=>{if(!drag)return;ui.host.style.left=Math.max(0,Math.min((win.innerWidth||1280)-120,e.clientX-drag.dx))+'px';ui.host.style.top=Math.max(0,Math.min((win.innerHeight||800)-60,e.clientY-drag.dy))+'px'};
      const up=()=>{drag=null;doc.removeEventListener('pointermove',move);doc.removeEventListener('pointerup',up)};
      doc.addEventListener('pointermove',move);doc.addEventListener('pointerup',up);
    }
    function onKey(event){
      if(event.ctrlKey||event.altKey||event.metaKey)return;
      const key=event.key;
      if(key==='Escape'){if(doc.fullscreenElement===ui.host)return;event.preventDefault();event.stopPropagation();close({reason:'escape'});return}
      if(key==='ArrowRight'||key==='ArrowDown'||key==='PageDown'||key===' '){event.preventDefault();step(1)}
      else if(key==='ArrowLeft'||key==='ArrowUp'||key==='PageUp'||key==='Backspace'){event.preventDefault();step(-1)}
      else if(key==='Home'){event.preventDefault();go(0)}
      else if(key==='End'){event.preventDefault();go(S.scenes.length-1)}
      else if((key==='f'||key==='F')&&!(event.target&&event.target.tagName==='INPUT')){event.preventDefault();toggleFullscreen()}
    }

    /* ------------------------------------------------------------ aperçu */
    function ensureHost(){
      if(previewHost)return previewHost;
      const api=d.prefabHost||root.JarvisPrefabHost;
      if(!api||typeof api.createPrefabHost!=='function')return null;
      try{
        previewHost=api.createPrefabHost({mode:'preview',document:doc,window:win,
          fetchBundle:api.bundleFetcher((path,options)=>fetchImpl(path,Object.assign({cache:'no-store'},options))),
          onPreviewEvent:()=>{/* intentional: the preview frame writes nothing anywhere */},
          log:(key,data)=>{if(key!=='scene.prefab_mounted')log('preview_host_'+String(key).replace(/^scene\./,''),data,'warn')}});
      }catch(error){log('preview_host_failed',{error:cleanLine(error&&error.message,140)},'error');previewHost=null}
      return previewHost;
    }
    function unmount(){
      if(previewHost&&S.mounted){try{previewHost.unmount(DOM.previewObjectId)}catch(_e){/* intentional: the frame is gone either way */}}
      S.mounted=null;
    }
    function veil(title,text){ui.veil.hidden=!title;ui.veilTitle.textContent=title||'';ui.veilText.textContent=text||''}
    function renderStage(){
      const scene=S.scenes[S.index];
      if(S.status==='loading'){unmount();veil('Chargement…','');return}
      if(S.status==='error'){unmount();veil('Affichage impossible',S.error||'');return}
      if(!scene){unmount();veil('Cette présentation n’a pas encore de slide','Un agent peut être en train de la construire : elle apparaîtra ici.');return}
      const host=ensureHost();
      if(!host){veil('Aperçu indisponible',"Le runtime des prefabs n'est pas chargé dans cette page.");return}
      if(!scene.prefab){veil('Slide sans prefab','');return}
      try{
        host.mount(ui.slot,{object_id:DOM.previewObjectId,prefab:{id:scene.prefab.id,version:scene.prefab.version},title:scene.title,props:scene.props,data:scene.data});
        S.mounted=scene.prefab;veil('','');
      }catch(error){veil('Aperçu impossible',cleanLine(error&&error.message,160));log('mount_failed',{error:cleanLine(error&&error.message,160)},'error')}
    }
    function render(){
      if(!ui.host)return;
      ui.host.hidden=!S.open;
      ui.title.textContent=cleanLine(S.title,80)||'Présentation';
      ui.dot.style.setProperty('--c',S.state==='working'?'#4aa3ff':S.state==='problem'?'#ffa23a':'#43d68c');
      ui.dot.title=S.state==='working'?'Un agent travaille dessus':S.state==='problem'?'Un problème est survenu':'Terminé';
      ui.chip.hidden=!S.variantNumber;ui.chip.textContent=S.variantNumber?`variante #${S.variantNumber}`:'';
      const full=doc.fullscreenElement===ui.host;
      ui.fs.textContent=full?'Quitter le plein écran':'Plein écran';
      ui.prev.setAttribute('aria-disabled',S.index>0?'false':'true');ui.next.setAttribute('aria-disabled',S.index<S.scenes.length-1?'false':'true');
      ui.count.textContent=S.scenes.length?`${S.index+1} / ${S.scenes.length}`:'';
      clear(ui.strip);
      S.scenes.forEach((scene,i)=>{
        const b=el('button','jvw-pip',String(i+1));b.type='button';b.title=scene.title;b.setAttribute('aria-label',`Slide ${i+1} : ${scene.title}`);
        if(i===S.index)b.setAttribute('aria-current','true');
        b.addEventListener('click',()=>go(i));ui.strip.appendChild(b);
      });
    }
    function go(index){
      if(!S.scenes.length)return;
      const next=Math.max(0,Math.min(S.scenes.length-1,index));
      if(next===S.index&&S.mounted)return;
      S.index=next;render();renderStage();
    }
    function step(delta){go(S.index+delta)}

    /* ------------------------------------------------------------ données */
    async function load(options){
      const generation=S.generation;
      try{
        const view=await call(`${ROUTE}/${encodeURIComponent(S.pid)}`);
        if(generation!==S.generation||!S.open)return false;
        const variant=pickVariant(view);
        S.title=cleanLine(view&&view.presentation&&view.presentation.title,80)||S.title;
        if(!variant){S.scenes=[];S.variantId=null;S.revision=null;S.status='ready';render();renderStage();return true}
        const before=S.variantId?{variantId:S.variantId,revision:S.revision}:null;
        if(!changed(before,variant)&&!(options&&options.force))return true;
        const keepId=S.scenes[S.index]&&S.scenes[S.index].id;
        S.variantId=variant.variant_id;S.revision=variant.revision;S.variantNumber=variant.variant_number||null;
        S.scenes=scenesOf(variant);
        const kept=S.scenes.findIndex(s=>s.id===keepId);
        S.index=kept>=0?kept:Math.min(S.index,Math.max(0,S.scenes.length-1));
        S.status='ready';S.error=null;
        log('loaded',{variant_id:variant.variant_id,revision:variant.revision,scenes:S.scenes.length});
        render();renderStage();return true;
      }catch(error){
        if(generation!==S.generation||!S.open)return false;
        log('load_failed',{code:error.code,status:error.status},'warn');
        if(error.status===404){S.status='error';S.error='Cette présentation n’existe plus.';render();renderStage();return false}
        if(!S.scenes.length){S.status='error';S.error=cleanLine(error.message,160);render();renderStage()}
        return false;
      }
    }
    function follow(){
      if(followTimer)cancelLater(followTimer);
      followTimer=later(async()=>{followTimer=null;if(!S.open)return;if(!doc.hidden)await load();if(S.open)follow()},FOLLOW_MS);
    }

    /* ------------------------------------------------------------ gestes */
    async function open(pid,options){
      if(typeof pid!=='string'||!ID_PRESENTATION.test(pid))throw new Error('identifiant de présentation invalide');
      build();
      const same=S.open&&S.pid===pid;
      if(!same){
        unmount();
        S.generation+=1;S.pid=pid;S.scenes=[];S.index=0;S.variantId=null;S.revision=null;S.variantNumber=null;S.status='loading';S.error=null;
        const row=d.rowOf&&d.rowOf(pid);S.title=row?cleanLine(row.title,80):'';S.state=row&&row.work&&row.work.state||'done';
      }
      S.open=true;S.via=options&&options.via||null;
      render();renderStage();
      if(!same){await load({force:true});follow()}
      if(options&&options.via!=='focus'&&options.via!=='brain'&&ui.host.focus)ui.host.focus({preventScroll:true});
      dispatchChange();
      return {state:'opened',presentation_id:pid};
    }
    function close(options){
      if(!S.open)return {state:'closed',was_open:false};
      if(doc.fullscreenElement===ui.host){try{doc.exitFullscreen()}catch(_e){/* intentional: closing hides it either way */}}
      S.open=false;S.generation+=1;
      if(followTimer){cancelLater(followTimer);followTimer=null}
      unmount();
      if(previewHost&&typeof previewHost.destroy==='function'){try{previewHost.destroy()}catch(_e){/* intentional */}}
      previewHost=null;
      ui.host.hidden=true;
      log('closed',{reason:options&&options.reason||'api'});
      dispatchChange();
      return {state:'closed',was_open:true};
    }
    function dispatchChange(){
      if(typeof win.dispatchEvent==='function'&&typeof win.CustomEvent==='function'){
        try{win.dispatchEvent(new win.CustomEvent('jarvis:presentation-window',{detail:{open:S.open,presentation_id:S.open?S.pid:null}}))}
        catch(error){log('event_failed',{error:cleanLine(error&&error.message,100)},'warn')}
      }
    }
    async function toggleFullscreen(){
      if(doc.fullscreenElement===ui.host){try{await doc.exitFullscreen()}catch(error){tell('Plein écran',`Sortie impossible : ${cleanLine(error&&error.message,100)}. Échap quitte toujours.`,'warn')}return}
      const api=d.fullscreen||root.JarvisFullscreen;
      if(!api||typeof api.enter!=='function'){tell('Plein écran','Plein écran indisponible dans cette page.','warn');return}
      try{
        const result=await api.enter({object_id:DOM.objectId,keys:'none',arm_s:30});
        if(result&&result.state==='needs_gesture')tell('Plein écran','Cliquez « Passer en plein écran » dans l’invite.','info');
        else if(result&&(result.state==='refused'||result.state==='unsupported'))tell('Plein écran',`Refusé par le navigateur${result.reason?' : '+cleanLine(result.reason,100):''}.`,'warn');
      }catch(error){log('fullscreen_failed',{error:cleanLine(error&&error.message,100)},'error');tell('Plein écran',cleanLine(error&&error.message,100),'bad')}
    }
    /* Démarrer une lecture par la MÊME route que la voix et la bande de lecture (`POST /api/presentation-studio/playback/start`, acteur `user` imposé par le relais),
       mais en gardant la cause du refus de Core (le lecteur la dit dans sa bande et rend `null`) : `{status: 'applied'|'refused'|'failed', reason?, message?}`.
       Le lecteur relit tout de suite l'état de Core (`refresh`) : la bande apparaît sans attendre son prochain sondage. Partagé avec le rail et le Studio. */
    async function startRun(pid,role,extra){
      if(!fetchImpl)return {status:'failed',message:'fetch indisponible'};
      const body=Object.assign({presentation_id:pid,role},extra||{});
      let response=null,payload=null;
      try{
        response=await fetchImpl('/api/presentation-studio/playback/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
        try{payload=await response.json()}catch(_e){payload=null /* intentional: the HTTP status is reported below */}
      }catch(error){log('start_failed',{error:cleanLine(error&&error.message,100)},'warn');return {status:'failed',message:'Control Center injoignable'}}
      if(response.ok&&payload&&payload.status==='applied'){
        const player=d.player||root.JarvisStudioPlayer;
        try{if(player&&typeof player.refresh==='function')await player.refresh()}catch(_e){/* intentional: the band catches up on its next poll */}
        return {status:'applied',state:payload.state||null};
      }
      const error=payload&&payload.error||{};
      const reason=payload&&payload.reason||error.code||`http_${response.status}`;
      const raw=cleanLine(payload&&payload.message||error.message||`HTTP ${response.status}`,200);
      const message=/has no score/i.test(raw)?'Cette variante n’a pas de partition (le déroulé) : demandez à Jarvis d’en écrire une.':raw;
      log('start_refused',{reason,status:response.status},'warn');
      return {status:payload&&payload.status==='refused'?'refused':'failed',reason,message};
    }
    async function play(){
      const result=await startRun(S.pid,'user_presenter');
      if(result.status==='applied')close({reason:'run_started'});
      else tell('Lecture impossible',cleanLine(result.message||result.reason,160),'warn');
    }
    async function studio(){
      const ex=d.explorer||root.JarvisStudioExplorer;
      if(!ex||typeof ex.open!=='function'){tell('Studio',"Le Studio n'est pas chargé dans cette page.",'bad');return}
      const pid=S.pid;
      const result=await ex.open({presentation_id:pid,fullscreen:false,via:'window'});
      if(result&&result.state==='opened')close({reason:'studio'});
      else if(result&&result.state==='refused')tell('Studio',cleanLine(result.reason||result.code,140),'warn');
    }
    /* L'état de travail lu par le rail met la pastille de la fenêtre à jour. */
    function sync(rows){
      if(!S.open||!Array.isArray(rows))return;
      const row=rows.find(r=>r&&r.presentation_id===S.pid);
      if(!row)return;
      const state=row.work&&row.work.state||'done';
      if(row.title&&cleanLine(row.title,80)!==S.title){S.title=cleanLine(row.title,80)}
      if(state!==S.state||ui.title.textContent!==S.title){S.state=state;render()}
    }

    return {open,close,isOpen:()=>S.open,pid:()=>S.open?S.pid:null,sync,go,step,load,toggleFullscreen,play,studio,startRun,host:()=>ui.host,
      state:()=>({open:S.open,pid:S.pid,variantId:S.variantId,revision:S.revision,scenes:S.scenes.length,index:S.index,status:S.status,error:S.error,workState:S.state})};
  }

  const API=Object.freeze({DOM,ROUTE,CSS,cleanLine,scenesOf,pickVariant,changed,createWindow});
  root.JarvisPresentationWindowCore=API;
  if(typeof module!=='undefined'&&module.exports)module.exports=API;

  if(typeof window==='undefined'||typeof document==='undefined')return;
  function installWindow(){
    const instance=createWindow({document,window,toast:typeof toast==='function'?toast:null,
      rowOf:pid=>{const rail=root.JarvisPresentationRail;const rows=rail&&rail.model?[].concat(rail.model().visible,rail.model().hidden):[];return rows.find(r=>r.presentation_id===pid)||null}});
    root.JarvisPresentationWindow=Object.freeze({open:instance.open,close:instance.close,isOpen:instance.isOpen,pid:instance.pid,sync:instance.sync,state:instance.state,
      go:instance.go,step:instance.step,load:instance.load,startRun:instance.startRun});
  }
  try{installWindow()}
  catch(error){console.error('[presentation-window] install_failed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
