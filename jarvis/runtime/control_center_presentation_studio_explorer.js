/* Explorateur de variantes du Studio de présentation (handoff jarvis-interactive-presentation-studio, Slice 18).
   Module DOM exposé en `window.JarvisStudioExplorer` dans la page et en `module.exports` pour node. Les fonctions pures (arbre, clavier ARIA,
   messages, boîte d'archivage, CSS) sont dans `control_center_presentation_studio_explorer_core.js` (mêmes marqueurs de page, celui-là d'abord).

   Ce que ce module est : un espace de travail plein écran, sombre et flouté. À GAUCHE l'arbre d'évolution des variantes (arbre ARIA : flèches,
   Début/Fin, Entrée, F2, Suppr, N, A, menu contextuel ; rendu virtualisé), à DROITE l'aperçu riche de la variante choisie (une scène à la fois,
   parcourue à la flèche ou à la bande de scènes), ses métadonnées, et les actions : activer, brancher, renommer, archiver (avec ses
   sous-branches, après un plan et une confirmation), restaurer.

   Ce qu'il n'est PAS :
   - une source de vérité. L'arbre est le graphe de Core (`GET .../graph`), relu après CHAQUE opération (et toutes les 10 s) ; une action qui a échoué,
     été refusée ou trouvé le graphe périmé (`stale_revision`, `confirmation_stale`) est dite à l'écran, et rien n'est supposé fait ;
   - un second chemin d'écriture. Toute action est une opération canonique du relais (`/api/presentation-studio/presentations/.../variants`,
     acteur forcé à `user` par le relais), les mêmes que la voix. L'aperçu LIT le document de la variante (`GET .../variants/{id}`) et le monte dans
     un cadre de prefab en mode `preview` de l'hôte : aucun événement ne part du cadre, rien n'est écrit (un test de navigateur empreinte tout
     l'arbre de la présentation avant et après) ;
   - un outil de lecture. Il est refusé pendant une lecture (cause dite, code `explorer_run_in_progress`) et se ferme si une lecture démarre : un seul
     élément peut être en plein écran, et le public ne doit jamais voir l'atelier.

   Plein écran : l'hôte (`#jvStudioExplorer`, `data-object-id="studio-explorer"`) demande le VRAI plein écran par `JarvisFullscreen.enter` ;
   par la voix il ARME (invite d'un clic, compte à rebours) et l'explorateur est déjà visible en recouvrement fenêtré, clairement étiqueté. Échap
   (livré à la page) ferme d'abord le menu, puis la boîte de dialogue, puis l'explorateur ; en plein écran le navigateur garde la première pression
   pour sortir du plein écran, l'explorateur reste alors ouvert en fenêtré.

   Tout texte d'auteur (titres, raisons) passe par `textContent` après `cleanLine`, jamais par du balisage ; `dir="auto"` protège la mise en page
   d'un titre de droite à gauche. Chaque échec se voit à l'écran (zone d'état, jamais seulement un toast : hors du plein écran les toasts ne sont pas
   dessinés), est journalisé (`[studio-explorer] <clé> {json}` ; `obsClientLog` quand la page en a un) et libère l'interface dans un `finally`. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const W=root.JarvisStudioExplorerWidgets||(typeof require==='function'?require('./control_center_presentation_studio_explorer_widgets.js'):null);
  const {ROUTE,PLAYBACK_ROUTE,COMMAND_ROUTE,STATE_ROUTE,HOST_ID,OBJECT_ID,PREVIEW_OBJECT_ID,STYLE_ID,ROW_H,MAX_DEPTH_SHOWN,INDENT_PX,
    REQUEST_TIMEOUT_MS,READ_TIMEOUT_MS,PLAYBACK_CHECK_MS,LONG_PRESS_MS,PREVIEW_SETTLE_MS,NOTICE_MS,COMMAND_REFUSALS,ICONS,CSS,MAX_LIVE,MAX_ARCHIVED,
    cleanLine,checkTitle,checkRationale,rationaleBytes,relativeTime,absoluteTime,creatorLabel,shortId,buildForest,subtreeIds,flatten,windowOf,treeKey,
    describeRefusal,planModel,sameSet,readPrefs,writePrefs,MAX_RATIONALE_BYTES}=Core;

  const GRAPH_POLL_MS=10000;
  const COMMAND_POLL_WAIT_S=25;
  const COMMAND_POLL_TIMEOUT_MS=30000;
  const COMMAND_MIN_GAP_MS=1000;
  const OPEN_RECEIPT_WAIT_MS=2500;
  const ARM_DEFAULT_S=30;
  const SVG_NS='http://www.w3.org/2000/svg';
  const HEX=/^#[0-9a-fA-F]{6}$/;
  const ID_PRESENTATION=/^pst_[0-9a-f]{32}$/;
  const ID_VARIANT=/^psv_[0-9a-f]{32}$/;

  class ExplorerError extends Error{
    constructor(info){super(info&&info.message||info&&info.code||'erreur');this.info=info||{};this.status=this.info.status;this.code=this.info.code}
  }
  function describe(error){return cleanLine(error&&error.message||String(error||'erreur inconnue'),200)}

  function createStudioExplorer(deps){
    const d=deps||{};
    const doc=d.document||root.document;
    const win=d.window||root;
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=d.clearTimeout||((id)=>clearTimeout(id));
    const every=d.setInterval||((fn,ms)=>setInterval(fn,ms));
    const stopEvery=d.clearInterval||((id)=>clearInterval(id));
    const now=d.now||(()=>Date.now());
    const frame=d.requestAnimationFrame||((fn)=>later(fn,16));
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const notify=typeof d.toast==='function'?d.toast:(typeof root.toast==='function'?root.toast:null);
    const sink=d.console||root.console;
    const storage=()=>{
      if(typeof d.storage==='function')return d.storage();
      if(d.storage)return d.storage;
      try{return root.localStorage||null}catch(_error){return null /* intentional: blocked storage only costs the remembered folds */}
    };
    const playing=d.playing||(()=>{
      const player=root.JarvisStudioPlayer,view=player&&typeof player.view==='function'?player.view():null;
      return !!view&&view.running===true&&view.phase!=='stopped'&&view.phase!=='idle';
    });
    const fullscreenApi=()=>d.fullscreen||root.JarvisFullscreen||null;
    const prefabApi=()=>d.prefabHost||root.JarvisPrefabHost||null;
    const stats={renders:0,paints:0,lastPaintMs:0,lastRenderMs:0,graphLoads:0,previews:0,ops:0,refusals:0,failures:0,polls:0,commands:0,staleHandled:0};
    const S={
      open:false,pid:null,presentationTitle:'',graph:null,live:null,archived:null,selectedId:null,focus:{live:null,archived:null},
      collapsed:new Set(),archivedOpen:false,prefs:readPrefs(null),loading:null,busy:null,notice:null,
      preview:{variantId:null,status:'idle',doc:null,scenes:[],sceneId:null,error:null,since:0,generation:0,mounted:null},
      art:{variantId:null,state:'idle',doc:null},fs:'not_requested',generation:0,dialog:null,menu:null,opener:null,fullscreenOwned:false,
    };
    const ui={};
    const selectionListeners=new Set();
    let tickTimer=null,playbackTimer=null,pollTimer=null,previewTimer=null,reportTimer=null,noticeTimer=null,armTimer=null;
    let previewHost=null,inerted=[],idSeq=0,lastReported='',playbackFailures=0,graphFailures=0;

    /* -------------------------------------------------------------- journal et retour visible (RULE ZERO) */
    function log(key,data,level){
      const line=`[studio-explorer] ${key} ${JSON.stringify(data||{})}`;
      try{
        if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}
      }catch(_error){/* intentional: a broken console never breaks the workspace */}
      if(level==='error'||level==='warn'){
        try{const obs=d.obsClientLog||root.obsClientLog;if(typeof obs==='function')obs(level,level==='error'?'ERROR':'WARN',`studio_explorer_${key}`,data||{})}
        catch(_error){/* intentional: the console line above is the record when the page's logger is absent or broken */}
      }
    }
    function tell(title,sub,kind){
      if(!notify)return;
      try{notify({title,sub:sub||'',kind:kind||'info',ms:kind==='bad'?9000:5000})}catch(_error){/* intentional: the inline notice is the surface, the toast a courtesy */}
    }
    function announce(text){if(ui.live){ui.live.textContent='';ui.live.textContent=text}}
    function say(kind,text,extra){
      S.notice={kind,text,at:now(),action:extra&&extra.action||null};
      if(noticeTimer)cancelLater(noticeTimer);
      noticeTimer=kind==='ok'||kind==='info'?later(()=>{S.notice=null;renderNotice()},NOTICE_MS):null;
      renderNotice();   /* la zone du message est elle-même `aria-live` : l'annoncer une seconde fois ferait lire deux fois */
    }

    /* -------------------------------------------------------------- DOM */
    function el(tag,cls,text){
      const node=doc.createElement(tag);
      if(cls)node.className=cls;
      if(text!==undefined&&text!==null)node.textContent=text;
      return node;
    }
    function attrs(node,map){for(const key of Object.keys(map))node.setAttribute(key,String(map[key]));return node}
    function clear(node){while(node.firstChild)node.removeChild(node.firstChild)}
    function uid(prefix){idSeq+=1;return `jvx-${prefix}-${idSeq}`}
    function icon(name){
      const svg=doc.createElementNS(SVG_NS,'svg');
      attrs(svg,{viewBox:'0 0 24 24','aria-hidden':'true',focusable:'false'});
      for(const part of ICONS[name]||[]){const path=doc.createElementNS(SVG_NS,'path');path.setAttribute('d',part);svg.appendChild(path)}
      return svg;
    }
    function button(label,cls,onClick,extra){
      const b=el('button',cls||'jvx-btn');
      b.setAttribute('type','button');
      if(extra&&extra.icon)b.appendChild(icon(extra.icon));
      if(label!==null&&label!==undefined&&label!==''){const span=el('span',extra&&extra.labelClass||'',label);b.appendChild(span)}
      if(extra&&extra.attrs)attrs(b,extra.attrs);
      if(onClick)b.addEventListener('click',onClick);
      return b;
    }
    function ensureStyle(){
      if(!doc||typeof doc.getElementById!=='function'||doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;style.textContent=CSS;
      (doc.head||doc.body).appendChild(style);
    }

    function dialogButton(label,onClick,options){
      const b=button(label,'jvx-btn',onClick);
      if(options&&options.primary)b.setAttribute('data-primary','');
      if(options&&options.danger)b.setAttribute('data-danger','');
      return b;
    }
    /* Ce que les éléments (`..._explorer_widgets.js`) reçoivent : le DOM, l'horloge et les aides de rendu, jamais l'état. */
    const kit={doc,el,attrs,clear,button,icon,uid,later,cancelLater,every,stopEvery,frame,now,dialogButton,stats};

    /* -------------------------------------------------------------- réseau */
    async function call(method,path,body,options){
      if(!fetchImpl)throw new ExplorerError({code:'network',message:"fetch indisponible dans cette page"});
      const timeoutMs=options&&options.timeoutMs||REQUEST_TIMEOUT_MS;
      const controller=typeof AbortController==='function'?new AbortController():null;
      let timedOut=false;
      const timer=later(()=>{timedOut=true;if(controller)controller.abort()},timeoutMs);
      try{
        const init={method,cache:'no-store'};
        if(controller)init.signal=controller.signal;
        if(body!==undefined){init.body=JSON.stringify(body);init.headers={'Content-Type':'application/json'}}
        const response=await fetchImpl(path,init);
        let payload=null;
        try{payload=await response.json()}catch(_error){payload=null /* intentional: a non-JSON answer is reported by its HTTP status below */}
        if(!response.ok){
          const error=payload&&payload.error||{};
          throw new ExplorerError({status:response.status,code:error.code||(payload&&payload.code)||`http_${response.status}`,
            message:error.message||(payload&&typeof payload.error==='string'?payload.error:`HTTP ${response.status}`)});
        }
        return payload;
      }catch(error){
        if(error instanceof ExplorerError)throw error;
        if(timedOut)throw new ExplorerError({code:'timeout',after:timeoutMs,message:`aucune réponse en ${Math.round(timeoutMs/1000)} s`});
        throw new ExplorerError({code:'network',message:describe(error)});
      }finally{cancelLater(timer)}
    }
    const base=()=>`${ROUTE}/${encodeURIComponent(S.pid)}`;
    const variantPath=(id,tail)=>`${base()}/variants/${encodeURIComponent(id)}${tail||''}`;

    /* -------------------------------------------------------------- préférences (collapsed, dernière sélection) */
    function loadPrefs(){
      S.prefs=readPrefs(storage());
      S.collapsed=new Set(Array.isArray(S.prefs.collapsed[S.pid])?S.prefs.collapsed[S.pid]:[]);
      S.archivedOpen=S.prefs.archivedOpen===true;
    }
    function savePrefs(){
      S.prefs.collapsed[S.pid]=Array.from(S.collapsed);
      S.prefs.archivedOpen=S.archivedOpen;
      writePrefs(storage(),S.prefs);
    }

    /* -------------------------------------------------------------- modèle */
    const nodeOf=id=>S.graph&&S.graph.byId.get(id)||null;
    function rebuild(){
      const nodes=S.graph?S.graph.nodes:[];
      S.live=buildForest(nodes,'live');
      S.archived=buildForest(nodes,'archived');
    }
    function runningVariantId(){
      const player=root.JarvisStudioPlayer,view=player&&typeof player.view==='function'?player.view():null;
      return view&&view.running&&view.presentation_id===S.pid?view.variant_id||null:null;
    }
    function applyGraph(payload){
      const nodes=Array.isArray(payload&&payload.nodes)?payload.nodes:[];
      const byId=new Map();
      for(const node of nodes)if(node&&typeof node.variant_id==='string')byId.set(node.variant_id,node);
      S.graph={revision:payload.revision,counter:payload.variant_counter,activeId:payload.active_variant_id,nodes,byId,
        archivedCount:Number.isFinite(payload.archived_count)?payload.archived_count:nodes.filter(n=>n.state==='archived').length,
        reconciliation:payload.reconciliation||null};
      rebuild();
      if(S.selectedId&&!byId.has(S.selectedId))S.selectedId=null;
    }
    async function loadGraph(options){
      const opts=options||{};
      stats.graphLoads+=1;
      const payload=await call('GET',`${base()}/graph?archived=1`,undefined,{timeoutMs:READ_TIMEOUT_MS});
      if(!payload||!Array.isArray(payload.nodes))throw new ExplorerError({code:'presentation_studio_corrupt_document',message:"le graphe rendu par Core n'a pas la forme attendue"});
      const before=S.graph;
      applyGraph(payload);
      graphFailures=0;
      if(!S.selectedId){
        const last=S.prefs.last[S.pid];
        S.selectedId=opts.select&&S.graph.byId.has(opts.select)?opts.select:last&&S.graph.byId.has(last)?last:S.graph.activeId;
        if(!S.graph.byId.has(S.selectedId))S.selectedId=S.live.roots[0]||null;
      }
      if(opts.reveal)revealInTree(S.selectedId);
      return before;
    }
    function revealInTree(id){
      const forest=S.live&&S.live.byId.has(id)?S.live:S.archived;
      let changed=false;
      for(let cur=forest&&forest.parentOf.get(id);cur;cur=forest.parentOf.get(cur))if(S.collapsed.delete(cur))changed=true;
      if(S.archived&&S.archived.byId.has(id)&&!S.archivedOpen){S.archivedOpen=true;changed=true}
      if(changed)savePrefs();
    }

    /* -------------------------------------------------------------- construction de la page */
    function build(){
      if(ui.host)return ui.host;
      ensureStyle();
      const host=el('div');
      host.id=HOST_ID;
      attrs(host,{role:'dialog','aria-modal':'true','aria-labelledby':'jvxTitle','data-object-id':OBJECT_ID,tabindex:'-1'});
      host.hidden=true;
      /* En-tête : titre, présentation, état, plein écran, fermer. */
      const top=el('header','jvx-top');
      const heading=el('div','jvx-heading');
      ui.title=el('h1','jvx-title','Variantes');ui.title.id='jvxTitle';ui.title.setAttribute('tabindex','-1');
      ui.subtitle=el('p','jvx-subtitle jvx-bidi');ui.subtitle.setAttribute('dir','auto');
      heading.appendChild(ui.title);heading.appendChild(ui.subtitle);
      const actions=el('div','jvx-top-actions');
      ui.busy=el('span','jvx-busy');ui.busy.hidden=true;attrs(ui.busy,{role:'status','aria-live':'polite'});
      ui.modeChip=el('span','jvx-chip');
      ui.fsButton=button(null,null,()=>{toggleFullscreen()});
      ui.fsIconIn=icon('expand');ui.fsIconOut=icon('contract');ui.fsLabel=el('span','jvx-btn-label-long','Plein écran');
      ui.fsButton.appendChild(ui.fsIconIn);ui.fsButton.appendChild(ui.fsIconOut);ui.fsButton.appendChild(ui.fsLabel);
      ui.closeButton=button('Fermer',null,()=>{close({reason:'user'})},{icon:'close',labelClass:'jvx-btn-label-long',attrs:{'aria-label':"Fermer l'explorateur de variantes",title:'Fermer (Échap)'}});
      for(const node of [ui.busy,ui.modeChip,ui.fsButton,ui.closeButton])actions.appendChild(node);
      top.appendChild(heading);top.appendChild(actions);
      ui.notice=el('div','jvx-notice');
      ui.noticeText=el('span','jvx-notice-text');ui.noticeText.setAttribute('aria-live','polite');ui.noticeText.setAttribute('role','status');
      ui.noticeAction=button('',null,()=>{if(ui.noticeRun)ui.noticeRun()});ui.noticeAction.hidden=true;
      ui.noticeClose=button(null,'jvx-btn jvx-btn-icon',()=>{S.notice=null;if(noticeTimer){cancelLater(noticeTimer);noticeTimer=null}renderNotice()},{icon:'close',attrs:{'aria-label':'Masquer ce message',title:'Masquer ce message'}});
      ui.notice.appendChild(ui.noticeText);ui.notice.appendChild(ui.noticeAction);ui.notice.appendChild(ui.noticeClose);
      /* Corps : arbre à gauche, aperçu à droite. */
      const body=el('div','jvx-body');
      const treePane=el('aside','jvx-treepane');
      attrs(treePane,{'aria-label':"Évolution des variantes"});
      const head=el('div','jvx-panehead');
      head.appendChild(el('h2','jvx-panetitle','Évolution'));
      ui.count=el('span','jvx-chip');
      head.appendChild(ui.count);
      ui.liveTree=W.createTreeView(kit,{collapsed:()=>S.collapsed,label:'Variantes de la présentation',
        onSelect:(id,o)=>selectVariant(id,{focus:true,pointer:o&&o.pointer}),onToggle:id=>toggleFold(id),
        onKey:(event,id,rows,index)=>onTreeKey('live',event,id,rows,index),onFocus:id=>{S.focus.live=id;syncRoving('live')},
        onMenu:(id,anchor)=>openMenu(id,anchor)});
      const archive=el('section','jvx-archive');
      archive.setAttribute('data-open','false');
      ui.archiveToggle=button(null,'jvx-archive-toggle',()=>toggleArchive(),{attrs:{'aria-expanded':'false'}});
      ui.archiveToggle.appendChild(icon('chevron'));
      ui.archiveLabel=el('span','','Archivées');ui.archiveToggle.appendChild(ui.archiveLabel);
      ui.archiveTree=W.createTreeView(kit,{collapsed:()=>S.collapsed,label:'Variantes archivées',
        onSelect:(id,o)=>selectVariant(id,{focus:true,pointer:o&&o.pointer}),onToggle:id=>toggleFold(id),
        onKey:(event,id,rows,index)=>onTreeKey('archived',event,id,rows,index),onFocus:id=>{S.focus.archived=id;syncRoving('archived')},
        onMenu:(id,anchor)=>openMenu(id,anchor)});
      ui.archive=archive;
      archive.appendChild(ui.archiveToggle);archive.appendChild(ui.archiveTree.element);
      ui.hint=el('p','jvx-hint-keys');
      ui.hint.textContent='↑ ↓ → ← parcourir · Entrée choisir · N brancher · F2 renommer · Suppr archiver · A activer';
      treePane.appendChild(head);treePane.appendChild(ui.liveTree.element);treePane.appendChild(ui.hint);treePane.appendChild(archive);
      const preview=el('section','jvx-preview');
      attrs(preview,{'aria-label':'Aperçu de la variante choisie'});
      const wrap=el('div','jvx-stagewrap');
      ui.stage=el('div','jvx-stage');
      attrs(ui.stage,{role:'group',tabindex:'0','aria-roledescription':'aperçu de scène'});
      ui.slot=el('div','jvx-slot');
      ui.veil=el('div','jvx-stage-veil');
      ui.veilTitle=el('strong');ui.veilText=el('span');ui.veilAction=button('',null,()=>{if(ui.veilRun)ui.veilRun()});ui.veilAction.hidden=true;
      ui.veil.appendChild(ui.veilTitle);ui.veil.appendChild(ui.veilText);ui.veil.appendChild(ui.veilAction);
      ui.stage.appendChild(ui.slot);ui.stage.appendChild(ui.veil);wrap.appendChild(ui.stage);
      const note=el('div','jvx-stage-note');
      const sceneLine=el('div','jvx-scene-line');
      ui.prevScene=button(null,'jvx-btn jvx-btn-icon',()=>browseScene(-1),{icon:'prev',attrs:{'aria-label':'Scène précédente',title:'Scène précédente (Page précédente)'}});
      ui.nextScene=button(null,'jvx-btn jvx-btn-icon',()=>browseScene(1),{icon:'next',attrs:{'aria-label':'Scène suivante',title:'Scène suivante (Page suivante)'}});
      ui.sceneTitle=el('span','jvx-scene-title jvx-bidi');ui.sceneTitle.setAttribute('dir','auto');
      ui.sceneRole=el('span','jvx-chip');
      ui.sceneBadge=el('span','jvx-chip');
      sceneLine.appendChild(ui.prevScene);sceneLine.appendChild(ui.nextScene);sceneLine.appendChild(ui.sceneTitle);sceneLine.appendChild(ui.sceneRole);sceneLine.appendChild(ui.sceneBadge);
      ui.sceneCount=el('span','');
      note.appendChild(sceneLine);note.appendChild(ui.sceneCount);
      ui.strip=el('div','jvx-strip');
      attrs(ui.strip,{role:'listbox','aria-label':'Scènes de la variante','aria-orientation':'horizontal'});
      const bottom=el('div','jvx-bottom');
      ui.meta=el('div','jvx-meta');
      ui.actions=el('div','jvx-actions');attrs(ui.actions,{role:'toolbar','aria-label':'Actions sur la variante choisie'});
      bottom.appendChild(ui.meta);bottom.appendChild(ui.actions);
      preview.appendChild(wrap);preview.appendChild(note);preview.appendChild(ui.strip);preview.appendChild(bottom);
      body.appendChild(treePane);body.appendChild(preview);
      ui.live=el('div','jvx-sr');attrs(ui.live,{role:'status','aria-live':'polite','aria-atomic':'true'});
      ui.layer=el('div','jvx-layer');
      for(const node of [top,ui.notice,body,ui.live,ui.layer])host.appendChild(node);
      host.addEventListener('keydown',onHostKey);
      ui.stage.addEventListener('keydown',onSceneKey);
      ui.strip.addEventListener('keydown',onSceneKey);
      doc.body.appendChild(host);
      ui.host=host;
      return host;
    }

    /* -------------------------------------------------------------- rendu */
    function modeNow(){
      if(doc.fullscreenElement===ui.host)return 'fullscreen';
      const api=fullscreenApi(),st=api&&typeof api.state==='function'?api.state():null;
      return st&&st.armed?'fullscreen_armed':'windowed';
    }
    function armedNow(){
      const api=fullscreenApi(),st=api&&typeof api.state==='function'?api.state():null;
      return !!(st&&st.armed);
    }
    function fsNow(){
      if(doc.fullscreenElement===ui.host)return 'entered';
      if(armedNow())return 'needs_gesture';
      return S.fs==='needs_gesture'?'exited':S.fs;     /* l'invite a été annulée ou a expiré : le navigateur n'attend plus rien */
    }
    /* Annuler l'invite ou la laisser expirer ne déclenche aucun événement : on regarde, jusqu'à ce qu'elle soit partie, et on le rapporte. */
    function watchArm(){
      if(armTimer)return;
      armTimer=every(()=>{
        if(!S.open||!armedNow()){
          stopEvery(armTimer);armTimer=null;
          if(S.open){renderHeader();reportSoon();log('fullscreen_prompt_gone',{fullscreen:fsNow()})}
        }
      },1000);
    }
    function renderHeader(){
      const mode=modeNow();
      ui.modeChip.textContent=mode==='fullscreen'?'Plein écran':mode==='fullscreen_armed'?'Plein écran en attente de votre clic':'Fenêtré';
      ui.modeChip.setAttribute('data-tone',mode==='fullscreen'?'ok':mode==='fullscreen_armed'?'accent':(S.fs==='unsupported'||S.fs==='refused')?'warn':'');
      const why=S.fs==='unsupported'?"Plein écran indisponible dans ce navigateur : l'explorateur est affiché dans la fenêtre.":
        S.fs==='refused'?"Plein écran refusé par le navigateur : l'explorateur est affiché dans la fenêtre.":'';
      ui.modeChip.title=mode==='windowed'&&why?why:mode==='fullscreen_armed'?"Cliquez « Passer en plein écran » dans l'invite en haut de la fenêtre.":'';
      if(mode==='windowed'&&why)ui.modeChip.textContent='Fenêtré — '+(S.fs==='unsupported'?'plein écran indisponible':'plein écran refusé');
      const full=mode==='fullscreen';
      ui.fsIconIn.style.display=full?'none':'';ui.fsIconOut.style.display=full?'':'none';
      ui.fsLabel.textContent=full?'Quitter le plein écran':'Plein écran';
      const live=S.graph?S.live.size:0,dead=S.graph?S.archived.size:0;
      ui.subtitle.textContent=S.graph?`${S.presentationTitle?cleanLine(S.presentationTitle,80)+' · ':''}${live} variante${live>1?'s':''}${dead?` · ${dead} archivée${dead>1?'s':''}`:''}`:cleanLine(S.presentationTitle,80);
      ui.count.textContent=S.graph?`${live}/${MAX_LIVE}`:'';
      ui.count.title=`${live} variantes vivantes sur ${MAX_LIVE} au plus`;
      if(S.busy){ui.busy.hidden=false;ui.busy.textContent=`${S.busy.label}… ${Math.max(0,Math.round((now()-S.busy.at)/1000))} s`}
      else if(S.loading){ui.busy.hidden=false;ui.busy.textContent=`${S.loading.label}… ${Math.max(0,Math.round((now()-S.loading.at)/1000))} s`}
      else{ui.busy.hidden=true;ui.busy.textContent=''}
    }
    function renderNotice(){
      const n=S.notice;
      ui.notice.hidden=!n;
      if(!n){ui.noticeText.textContent='';ui.noticeAction.hidden=true;return}
      ui.notice.setAttribute('data-kind',n.kind);
      ui.noticeText.textContent=n.text;
      ui.noticeText.setAttribute('aria-live',n.kind==='failed'?'assertive':'polite');
      if(n.action){ui.noticeAction.hidden=false;ui.noticeAction.textContent=n.action.label;ui.noticeRun=n.action.run}
      else{ui.noticeAction.hidden=true;ui.noticeRun=null}
    }
    /* La variante lue et ses ancêtres (ceux dont l'archivage la viserait) : relu à chaque rendu, la lecture se démarre hors de cette page. */
    function playingNow(){
      const playingId=runningVariantId();
      const playingSet=new Set();
      if(playingId&&S.live&&S.live.byId.has(playingId)){playingSet.add(playingId);for(const a of Core.ancestorsOf(S.live,playingId))playingSet.add(a)}
      return playingSet;
    }
    function treeContext(kind){
      /* Lus à chaque rendu de ligne (défilement compris) : jamais une copie périmée de la sélection ou du focus. */
      return {get selectedId(){return S.selectedId},get activeId(){return S.graph&&S.graph.activeId},get focusId(){return S.focus[kind]||null},
        get playing(){return playingNow()}};
    }
    function renderTrees(){
      if(!S.graph){ui.liveTree.setData({forest:null,ctx:{},emptyText:S.loading?'Chargement du graphe…':''});return}
      ensureFocus('live');ensureFocus('archived');
      ui.liveTree.setData({forest:S.live,ctx:treeContext('live'),emptyText:'Aucune variante vivante.'});
      const dead=S.archived.size;
      ui.archive.hidden=false;
      ui.archive.setAttribute('data-open',S.archivedOpen?'true':'false');
      ui.archiveToggle.setAttribute('aria-expanded',S.archivedOpen?'true':'false');
      ui.archiveLabel.textContent=`Archivées (${dead})`;
      ui.archiveToggle.setAttribute('aria-controls',ui.archiveTree.element.id||(ui.archiveTree.element.id=uid('archive')));
      ui.archiveTree.element.hidden=!S.archivedOpen;
      ui.archiveTree.setData({forest:S.archived,ctx:treeContext('archived'),emptyText:dead?'':'Rien dans l\'archive : « Archiver… » met une branche de côté, elle se restaure ici.'});
    }
    function ensureFocus(kind){
      const forest=kind==='live'?S.live:S.archived;
      const cur=S.focus[kind];
      if(cur&&forest.byId.has(cur)&&visibleIn(kind,cur))return;
      const sel=S.selectedId&&forest.byId.has(S.selectedId)&&visibleIn(kind,S.selectedId)?S.selectedId:null;
      const rows=flatten(forest,S.collapsed);
      S.focus[kind]=sel||(rows[0]&&rows[0].id)||null;
    }
    function visibleIn(kind,id){
      const forest=kind==='live'?S.live:S.archived;
      for(const a of Core.ancestorsOf(forest,id))if(S.collapsed.has(a))return false;
      return true;
    }
    function syncRoving(kind){
      const tree=kind==='live'?ui.liveTree:ui.archiveTree;
      for(const row of tree.rows()){const node=tree.rowElement(row.id);if(node)node.setAttribute('tabindex',S.focus[kind]===row.id?'0':'-1')}
    }
    function renderAll(){
      const t0=now();
      stats.renders+=1;
      renderHeader();renderNotice();renderTrees();renderMeta();renderActions();renderStrip();renderStage();
      stats.lastRenderMs=now()-t0;
    }

    /* -------------------------------------------------------------- métadonnées, actions */
    function renderMeta(){
      const node=nodeOf(S.selectedId);
      const preview=S.preview;
      W.renderMeta(kit,ui.meta,{graphReady:!!S.graph,node,parent:node?nodeOf(node.parent_variant_id):null,
        isActive:!!node&&S.graph.activeId===node.variant_id,isPlaying:!!node&&runningVariantId()===node.variant_id,
        score:node&&preview.variantId===node.variant_id&&preview.doc?(preview.doc.score_id?'Partition liée':'Sans partition'):null,
        art:node&&S.art.variantId===node.variant_id?S.art:{state:'idle'}});
    }
    function actionModel(node){
      const live=S.live?S.live.size:0;
      const out=[];
      if(!node)return out;
      const archived=node.state==='archived';
      const busy=!!S.busy;
      const add=(act,label,iconName,key,opts)=>out.push(Object.assign({act,label,icon:iconName,key,disabled:busy?'Une opération est en cours.':null},opts||{}));
      if(archived){
        const dead=S.archived;
        const withKids=dead&&dead.kids.get(node.variant_id);
        add('restore','Restaurer','restore','R',{});
        if(withKids&&withKids.length)add('restore_all','Restaurer avec ses sous-branches','restore','',{});
      }else{
        add('activate','Activer','power','A',{disabled:busy?'Une opération est en cours.':S.graph.activeId===node.variant_id?'Cette variante est déjà la variante active.':null});
        add('branch','Brancher d\'ici…','fork','N',{disabled:busy?'Une opération est en cours.':live>=MAX_LIVE?`${MAX_LIVE} variantes vivantes au plus : archivez des branches abandonnées d'abord.`:null});
        add('rename','Renommer…','pencil','F2',{});
        add('archive','Archiver…','box','Suppr',{danger:true,disabled:busy?'Une opération est en cours.':live<=1?'Une présentation garde toujours au moins une variante vivante.':null});
      }
      return out;
    }
    function renderActions(){
      const focusedAct=ui.actions.contains(doc.activeElement)&&doc.activeElement.dataset?doc.activeElement.dataset.act:null;
      clear(ui.actions);
      const node=nodeOf(S.selectedId);
      for(const item of actionModel(node)){
        const b=button(item.label,'jvx-btn',null,{icon:item.icon});
        if(item.danger)b.setAttribute('data-danger','');
        b.dataset.act=item.act;
        if(item.key)b.setAttribute('aria-keyshortcuts',item.key==='Suppr'?'Delete':item.key);
        if(item.disabled){b.setAttribute('aria-disabled','true');b.title=item.disabled}
        else b.title=item.key?`${item.label} (${item.key})`:item.label;
        b.addEventListener('click',()=>{
          if(S.busy){say('info','Une opération est déjà en cours.');return}
          if(item.disabled){say('info',item.disabled);return}
          runAction(item.act,node.variant_id,{returnFocus:b});
        });
        ui.actions.appendChild(b);
        if(focusedAct===item.act)b.focus({preventScroll:true});
      }
    }
    /* Une opération en cours : les boutons restent LÀ (le focus ne saute pas), ils disent seulement « occupé ». */
    function syncActionsBusy(){
      for(const b of Array.from(ui.actions.children)){
        if(S.busy){b.setAttribute('aria-disabled','true');b.dataset.wasBusy='1'}
        else if(b.dataset.wasBusy){delete b.dataset.wasBusy;renderActions();return}
      }
    }

    /* -------------------------------------------------------------- aperçu : lecture seule du document, cadre en mode preview */
    function ensureHost(){
      if(previewHost)return previewHost;
      const api=prefabApi();
      if(!api||typeof api.createPrefabHost!=='function')return null;
      try{
        previewHost=api.createPrefabHost({mode:'preview',document:doc,window:win,
          fetchBundle:api.bundleFetcher((path,options)=>fetchImpl(path,Object.assign({cache:'no-store'},options))),
          onPreviewEvent:()=>{/* intentional: the preview frame writes nothing anywhere; its events are dropped */},
          log:(key,data)=>{if(key!=='scene.prefab_mounted')log('preview_host_'+String(key).replace(/^scene\./,''),data,'warn')}});
      }catch(error){log('preview_host_failed',{error:describe(error)},'error');previewHost=null}
      return previewHost;
    }
    function unmountPreview(){
      if(previewHost&&S.preview.mounted){try{previewHost.unmount(PREVIEW_OBJECT_ID)}catch(_error){/* intentional: the frame is gone either way */}}
      S.preview.mounted=null;
    }
    function scenesOf(variantDoc){
      const list=Array.isArray(variantDoc&&variantDoc.scenes)?variantDoc.scenes.slice(0,64):[];
      return list.filter(s=>s&&typeof s.scene_id==='string').map(s=>({
        id:s.scene_id,title:cleanLine(s.title,80)||'(sans titre)',section:cleanLine(s.section,40),prefab:s.prefab&&typeof s.prefab.id==='string'?s.prefab:null,
        props:s.props&&typeof s.props==='object'?s.props:{},data:s.data&&typeof s.data==='object'?s.data:{},
        locals:s.scene_variants&&Array.isArray(s.scene_variants.items)?s.scene_variants.items.length:0}));
    }
    function schedulePreview(){
      if(previewTimer)cancelLater(previewTimer);
      const node=nodeOf(S.selectedId);
      const p=S.preview;
      p.generation+=1;
      if(!node){p.variantId=null;p.status='idle';unmountPreview();renderStage();renderStrip();return}
      if(p.variantId!==node.variant_id){p.doc=null;p.scenes=[];p.error=null;p.variantId=node.variant_id}
      if(node.state==='archived'){p.status='archived';p.since=now();unmountPreview();renderStage();renderStrip();renderMeta();return}
      /* Relire une variante déjà à l'écran (après un renommage, un changement venu d'ailleurs) ne couvre pas l'aperçu d'un voile : l'ancien reste, le neuf le remplace. */
      const refreshing=p.status==='ready'&&p.scenes.length>0;
      if(!refreshing){p.status='loading';p.since=now();renderStage();renderStrip();startTicker()}
      const generation=p.generation,variantId=node.variant_id;
      previewTimer=later(()=>{previewTimer=null;loadPreview(variantId,generation)},PREVIEW_SETTLE_MS);
      loadArt(variantId);
    }
    async function loadPreview(variantId,generation){
      const p=S.preview;
      stats.previews+=1;
      try{
        const variantDoc=await call('GET',variantPath(variantId),undefined,{timeoutMs:READ_TIMEOUT_MS});
        if(generation!==p.generation||!S.open)return;
        p.doc=variantDoc;p.scenes=scenesOf(variantDoc);
        if(!p.scenes.some(s=>s.id===p.sceneId))p.sceneId=p.scenes[0]?p.scenes[0].id:null;
        p.status=p.scenes.length?'ready':'empty';p.error=null;
        log('preview_loaded',{variant_id:variantId,scenes:p.scenes.length,variant_revision:variantDoc.revision});
      }catch(error){
        if(generation!==p.generation||!S.open)return;
        const info=describeRefusal(error.info||error,{op:'preview'});
        if(info.code==='presentation_studio_unknown_variant'&&!p.rereading){
          /* La variante vient d'être archivée (ici, ailleurs, ou par la voix) : le graphe affiché est périmé, pas l'aperçu en panne. */
          p.rereading=true;
          log('preview_variant_gone',{variant_id:variantId});
          loadGraph({}).then(()=>{p.rereading=false;if(S.open){renderAll();schedulePreview()}}).catch(()=>{p.rereading=false;p.status='error';p.error=info.text;renderStage()});
          return;
        }
        p.status='error';p.error=info.text;stats.failures+=1;
        log('preview_failed',{variant_id:variantId,code:info.code},'warn');
      }
      renderStage();renderStrip();renderMeta();
    }
    async function loadArt(variantId){
      if(S.art.variantId===variantId&&(S.art.state==='ready'||S.art.state==='loading'))return;
      S.art={variantId,state:'loading',doc:null};
      try{
        const answer=await call('GET',variantPath(variantId,'/art-direction'),undefined,{timeoutMs:READ_TIMEOUT_MS});
        if(!S.open||S.art.variantId!==variantId)return;
        S.art={variantId,state:answer&&answer.art_direction?'ready':'none',doc:answer&&answer.art_direction||null};
      }catch(error){
        if(!S.open||S.art.variantId!==variantId)return;
        S.art={variantId,state:error.code==='presentation_studio_unknown_art_direction'?'none':'error',doc:null};
        if(S.art.state==='error')log('art_direction_failed',{variant_id:variantId,code:error.code},'warn');
      }
      renderMeta();applyGlow();
    }
    function applyGlow(){
      const palette=S.art.state==='ready'&&S.art.variantId===S.selectedId&&S.art.doc&&S.art.doc.profile&&S.art.doc.profile.palette||null;
      const a=palette&&HEX.test(palette.accent)?palette.accent:'#6ee7ff';
      const b=palette&&typeof palette.accent_alt==='string'&&HEX.test(palette.accent_alt)?palette.accent_alt:palette&&HEX.test(palette.surface)?palette.surface:'#a78bfa';
      ui.host.style.setProperty('--jvx-glow-a',a);ui.host.style.setProperty('--jvx-glow-b',b);
    }
    function currentScene(){return S.preview.scenes.find(s=>s.id===S.preview.sceneId)||null}
    function renderStage(){
      const p=S.preview;
      const scene=p.status==='ready'?currentScene():null;
      const veil=(tone,title,text,action)=>{
        ui.veil.hidden=false;ui.veil.setAttribute('data-tone',tone||'');
        ui.veilTitle.textContent=title;ui.veilText.textContent=text||'';
        ui.veilAction.hidden=!action;
        ui.veilRun=action?action.run:null;
        if(action)ui.veilAction.textContent=action.label;
      };
      const node=nodeOf(S.selectedId);
      if(!node)veil('','Aucune variante choisie','Choisissez une variante dans l\'arbre pour la voir ici.');
      else if(p.status==='archived'){unmountPreview();veil('warn',`#${node.variant_number} est archivée`,"Une variante archivée n'a pas d'aperçu : restaurez-la pour la voir.")}
      else if(p.status==='loading'){veil('','Chargement de l\'aperçu…',`Variante #${node.variant_number} · ${Math.max(0,Math.round((now()-p.since)/1000))} s`)}
      else if(p.status==='error'){unmountPreview();veil('danger',"Aperçu impossible",p.error||'',{label:'Réessayer',run:()=>schedulePreview()})}
      else if(p.status==='empty'){unmountPreview();veil('warn','Cette variante n\'a aucune scène','Il n\'y a rien à montrer.')}
      else if(scene){
        const host=ensureHost();
        if(!host)veil('danger','Aperçu indisponible',"Le runtime des prefabs n'est pas chargé dans cette page.");
        else if(!scene.prefab)veil('danger','Scène sans prefab','Cette scène ne désigne aucun prefab.');
        else{
          try{
            host.mount(ui.slot,{object_id:PREVIEW_OBJECT_ID,prefab:{id:scene.prefab.id,version:scene.prefab.version},title:scene.title,props:scene.props,data:scene.data});
            p.mounted=scene.prefab;ui.veil.hidden=true;
          }catch(error){
            veil('danger','Aperçu impossible',describe(error));
            log('preview_mount_failed',{error:describe(error)},'error');
          }
        }
      }
      const index=scene?p.scenes.indexOf(scene):-1;
      ui.sceneTitle.textContent=scene?scene.title:'';
      ui.sceneRole.hidden=!(scene&&scene.section);ui.sceneRole.textContent=scene?scene.section:'';
      ui.sceneBadge.hidden=!(scene&&scene.locals>1);
      ui.sceneBadge.textContent=scene&&scene.locals>1?`${scene.locals} variantes locales`:'';
      ui.sceneBadge.title='Variantes locales de cette scène (elles restent hors de l\'arbre tant qu\'on ne les promeut pas)';
      ui.sceneCount.textContent=scene?`Scène ${index+1} sur ${p.scenes.length}`:'';
      ui.prevScene.setAttribute('aria-disabled',index>0?'false':'true');
      ui.nextScene.setAttribute('aria-disabled',index>=0&&index<p.scenes.length-1?'false':'true');
      ui.stage.setAttribute('aria-label',scene?`Aperçu, scène ${index+1} sur ${p.scenes.length} : ${scene.title}`:'Aperçu');
    }
    function renderStrip(){
      const hadFocus=ui.strip.contains(doc.activeElement);
      clear(ui.strip);
      const p=S.preview;
      if(p.status!=='ready')return;
      p.scenes.forEach((scene,index)=>{
        const selected=scene.id===p.sceneId;
        const b=el('button','jvx-scene');
        attrs(b,{type:'button',role:'option','aria-selected':selected?'true':'false',tabindex:selected?'0':'-1','data-scene':scene.id,
          'aria-label':`Scène ${index+1}, ${scene.title}${scene.section?', '+scene.section:''}${scene.locals>1?`, ${scene.locals} variantes locales`:''}`});
        b.appendChild(el('span','jvx-scene-n',String(index+1).padStart(2,'0')));
        const t=el('span','jvx-scene-t jvx-bidi',scene.title);t.setAttribute('dir','auto');b.appendChild(t);
        b.appendChild(el('span','jvx-scene-r',scene.section||' '));
        if(scene.locals>1)b.appendChild(el('span','jvx-scene-b',`${scene.locals} variantes`));
        b.addEventListener('click',()=>setScene(scene.id,{focus:true}));
        ui.strip.appendChild(b);
        if(hadFocus&&selected)b.focus({preventScroll:true});
      });
    }
    function setScene(sceneId,options){
      const p=S.preview;
      if(p.sceneId===sceneId||!p.scenes.some(s=>s.id===sceneId))return;
      p.sceneId=sceneId;
      renderStage();renderStrip();
      const scene=currentScene();
      if(scene)announce(`Scène ${p.scenes.indexOf(scene)+1} sur ${p.scenes.length} : ${scene.title}`);
      if(options&&options.focus){const b=ui.strip.querySelector(`[data-scene="${sceneId}"]`);if(b)b.focus({preventScroll:true})}
    }
    function browseScene(delta,absolute){
      const p=S.preview;
      if(p.status!=='ready'||!p.scenes.length)return false;
      const index=Math.max(0,p.scenes.findIndex(s=>s.id===p.sceneId));
      const target=absolute!==undefined?absolute:index+delta;
      const clamped=Math.max(0,Math.min(p.scenes.length-1,target));
      if(clamped===index)return true;
      setScene(p.scenes[clamped].id,{focus:doc.activeElement&&ui.strip.contains(doc.activeElement)});
      return true;
    }
    function onSceneKey(event){
      if(event.ctrlKey||event.altKey||event.metaKey)return;
      const p=S.preview;
      const key=event.key;
      let handled=false;
      if(key==='ArrowRight'||key==='ArrowDown'||key==='PageDown')handled=browseScene(key==='PageDown'?3:1);
      else if(key==='ArrowLeft'||key==='ArrowUp'||key==='PageUp')handled=browseScene(key==='PageUp'?-3:-1);
      else if(key==='Home')handled=browseScene(0,0);
      else if(key==='End')handled=browseScene(0,p.scenes.length-1);
      if(handled){event.preventDefault();event.stopPropagation()}
    }

    /* -------------------------------------------------------------- sélection, pliage, clavier de l'arbre */
    function selectVariant(id,options){
      const node=nodeOf(id);
      if(!node)return;
      const changed=S.selectedId!==id;
      S.selectedId=id;
      S.prefs.last[S.pid]=id;savePrefs();
      const kind=node.state==='archived'?'archived':'live';
      S.focus[kind]=id;
      if(changed){
        schedulePreview();
        announce(`Variante ${node.variant_number} choisie : ${cleanLine(node.title,60)}`);
        for(const fn of Array.from(selectionListeners)){try{fn([id])}catch(error){log('selection_listener_failed',{error:describe(error)},'error')}}
        reportSoon();
      }
      renderTrees();renderMeta();renderActions();
      if(options&&options.focus){(kind==='live'?ui.liveTree:ui.archiveTree).focus(id)}
    }
    function toggleFold(id){
      if(S.collapsed.has(id))S.collapsed.delete(id);else S.collapsed.add(id);
      savePrefs();renderTrees();
      const kind=S.archived.byId.has(id)?'archived':'live';
      (kind==='live'?ui.liveTree:ui.archiveTree).focus(id);
    }
    function toggleArchive(){
      S.archivedOpen=!S.archivedOpen;savePrefs();renderTrees();
      if(S.archivedOpen){const id=S.focus.archived;if(id)ui.archiveTree.ensureVisible(id)}
    }
    function onTreeKey(kind,event,id,rows,index){
      const tree=kind==='live'?ui.liveTree:ui.archiveTree;
      const act=treeKey(rows,index,event.key,{ctrl:event.ctrlKey,alt:event.altKey,meta:event.metaKey,shift:event.shiftKey});
      if(!act)return;
      event.preventDefault();event.stopPropagation();
      const node=nodeOf(act.id);
      switch(act.type){
        case 'focus':S.focus[kind]=act.id;tree.focus(act.id);break;
        case 'expand':case 'collapse':
          if(act.type==='expand')S.collapsed.delete(act.id);else S.collapsed.add(act.id);
          savePrefs();renderTrees();tree.focus(act.id);break;
        case 'expand_siblings':{
          const forest=kind==='live'?S.live:S.archived;
          const parent=forest.parentOf.get(act.id);
          for(const sibling of parent?forest.kids.get(parent)||[]:forest.roots)S.collapsed.delete(sibling);
          savePrefs();renderTrees();tree.focus(act.id);break}
        case 'select':selectVariant(act.id,{focus:true});break;
        case 'menu':{
          const rowNode=tree.rowElement(act.id);
          const rect=rowNode?rowNode.getBoundingClientRect():{left:40,top:80,height:ROW_H};
          openMenu(act.id,{x:rect.left+48,y:rect.top+rect.height,pointer:false});break}
        case 'rename':case 'archive':case 'branch':case 'activate':case 'restore':
          if(!node)break;
          if(S.selectedId!==act.id)selectVariant(act.id,{focus:true});
          if(act.type==='restore'&&node.state!=='archived')break;
          if(act.type!=='restore'&&node.state==='archived'){say('info','Une variante archivée se restaure d\'abord (R).');break}
          runAction(act.type,act.id,{returnFocus:tree.rowElement(act.id)});break;
        default:break;
      }
    }

    /* -------------------------------------------------------------- opérations canoniques (relais, acteur `user` forcé côté relais) */
    function begin(label){S.busy={label,at:now()};renderHeader();syncActionsBusy();startTicker()}
    function endBusy(){S.busy=null;renderHeader();syncActionsBusy()}
    function startTicker(){
      if(tickTimer)return;
      tickTimer=every(()=>{
        if(S.busy||S.loading||S.preview.status==='loading'){renderHeader();if(S.preview.status==='loading')renderStage()}
        updateToken();
        if(!S.busy&&!S.loading&&S.preview.status!=='loading'&&!S.dialog)stopTicker();
      },1000);
    }
    function stopTicker(){if(tickTimer){stopEvery(tickTimer);tickTimer=null}}
    /* Une action : refus et pannes dits à l'écran, journalisés, interface libérée. `fn` rend le message de réussite. */
    async function perform(op,label,fn){
      if(S.busy){say('info','Une opération est déjà en cours.');return null}
      stats.ops+=1;
      begin(label);
      log('op_started',{op,presentation_id:S.pid});
      try{
        const result=await fn();
        log('op_done',{op});
        return result||true;
      }catch(error){
        const info=describeRefusal(error.info||error,{op});
        if(info.kind==='failed')stats.failures+=1;else stats.refusals+=1;
        if(info.kind==='stale')stats.staleHandled+=1;
        log('op_failed',{op,code:info.code,kind:info.kind,status:error.status},info.kind==='failed'?'error':'warn');
        say(info.kind==='failed'?'failed':info.kind==='stale'?'stale':'refused',info.text);
        if(info.kind==='failed'&&!S.open)tell('Variantes : '+label,info.text,'bad');
        if(info.kind==='stale'||info.code==='presentation_studio_unknown_variant'){
          try{await loadGraph({});renderAll();schedulePreview()}catch(reload){log('reload_after_stale_failed',{code:reload.code},'warn')}
        }
        return {error:info};
      }finally{endBusy()}
    }
    async function after(selectId,message){
      /* Après chaque opération, on relit le graphe de Core : l'arbre ne se met jamais à jour de tête. */
      try{
        await loadGraph({});
        renderAll();
        if(selectId&&nodeOf(selectId)){revealInTree(selectId);renderTrees();selectVariant(selectId,{focus:true})}
        schedulePreview();
        say('ok',message);
      }catch(error){
        const info=describeRefusal(error.info||error,{op:'graph'});
        say('failed',`${message} — mais la relecture de la liste a échoué : ${info.text}`,{action:{label:'Relire',run:()=>refresh()}});
        log('reload_failed',{code:info.code},'error');
      }
    }
    async function refresh(){
      begin('Relecture');
      try{await loadGraph({});renderAll();schedulePreview();if(S.notice&&S.notice.kind==='failed')S.notice=null;renderNotice()}
      catch(error){const info=describeRefusal(error.info||error,{op:'graph'});say('failed',info.text,{action:{label:'Réessayer',run:()=>refresh()}});log('refresh_failed',{code:info.code},'warn')}
      finally{endBusy()}
    }
    function expected(){return S.graph?{expected_revision:S.graph.revision}:{}}
    async function activate(id){
      const node=nodeOf(id);
      if(!node||node.state!=='live')return;
      if(S.graph.activeId===id){say('info',`#${node.variant_number} est déjà la variante active.`);return}
      const done=await perform('activate','Activation',async()=>{
        await call('POST',variantPath(id,'/activate'),Object.assign({},expected()));
        return true;
      });
      if(done&&!done.error)await after(id,`#${node.variant_number} « ${cleanLine(node.title,40)} » est maintenant la variante active.`);
    }
    async function branch(id,form){
      const node=nodeOf(id);
      const body=Object.assign({title:form.title,source_variant_id:id,activate:!!form.activate},expected());
      if(form.rationale)body.rationale=form.rationale;
      let created=null;
      const done=await perform('branch','Création de la branche',async()=>{
        created=await call('POST',`${base()}/variants`,body);
        return true;
      });
      if(done&&!done.error){
        const n=created&&created.node?created.node:{};
        return {select:n.variant_id||null,message:`Branche #${n.variant_number||'?'} créée depuis #${node.variant_number}${form.activate?' et activée':''}.`};
      }
      return false;
    }
    async function rename(id,title){
      const node=nodeOf(id);
      const done=await perform('rename','Renommage',async()=>{
        await call('POST',variantPath(id,'/rename'),Object.assign({title},expected()));
        return true;
      });
      if(done&&!done.error)return {select:id,message:`#${node.variant_number} renommée.`};
      return false;
    }
    async function restore(id,withDescendants){
      const node=nodeOf(id);
      let result=null;
      const done=await perform('restore','Restauration',async()=>{
        const body=Object.assign({},expected());
        if(withDescendants)body.with_descendants=true;
        result=await call('POST',variantPath(id,'/restore'),body);
        return true;
      });
      if(done&&!done.error){
        const count=result&&result.count||1;
        await after(id,count>1?`${count} variantes restaurées, dont #${node.variant_number} (ses ancêtres archivés, ou ses sous-branches, reviennent avec elle).`:`#${node.variant_number} restaurée.`);
      }
    }
    function runAction(act,id,options){
      const node=nodeOf(id);
      if(!node)return;
      if(S.busy){say('info','Une opération est déjà en cours.');return}
      const returnFocus=options&&options.returnFocus||null;
      if(act==='activate')return activate(id);
      if(act==='branch')return openBranchDialog(id,returnFocus);
      if(act==='rename')return openRenameDialog(id,returnFocus);
      if(act==='archive')return openArchiveDialog(id,returnFocus);
      if(act==='restore')return restore(id,false);
      if(act==='restore_all')return restore(id,true);
    }

    /* -------------------------------------------------------------- boîtes de dialogue (dans l'hôte : hors de lui, rien ne se dessine en plein écran) */
    function setInertBehind(on){
      /* Le reste de l'hôte est inerte pendant un dialogue ; le calque du dialogue ne l'est pas. */
      for(const node of ui.host.children){if(node!==ui.layer&&node.nodeType===1)node.inert=!!on}
    }
    function closeDialog(restore){
      const dlg=S.dialog;
      if(!dlg)return;
      S.dialog=null;
      if(dlg.timer)stopEvery(dlg.timer);
      clear(ui.layer);setInertBehind(false);
      if(restore!==false){
        const target=dlg.returnFocus&&dlg.returnFocus.isConnected!==false?dlg.returnFocus:null;
        const kindNode=nodeOf(S.selectedId);
        if(target&&typeof target.focus==='function')target.focus({preventScroll:true});
        else if(kindNode)(kindNode.state==='archived'?ui.archiveTree:ui.liveTree).focus(S.selectedId);
      }
    }
    function openDialog(spec){
      closeMenu(false);
      closeDialog(false);
      const scrim=el('div','jvx-scrim');
      const box=el('div','jvx-dialog');
      attrs(box,{role:'dialog','aria-modal':'true','aria-labelledby':spec.titleId});
      scrim.appendChild(box);
      ui.layer.appendChild(scrim);
      setInertBehind(true);
      S.dialog={kind:spec.kind,box,scrim,returnFocus:spec.returnFocus||doc.activeElement,onCancel:spec.onCancel||null,timer:null};
      scrim.addEventListener('mousedown',event=>{if(event.target===scrim&&spec.dismissible!==false)cancelDialog()});
      return S.dialog;
    }
    function cancelDialog(){
      const dlg=S.dialog;
      if(!dlg)return;
      if(dlg.busy)return;
      closeDialog(true);
    }
    function openTitleDialog(config){
      const dlg=openDialog({kind:config.kind,titleId:'jvxDialogTitle',returnFocus:config.returnFocus});
      W.fillTitleDialog(kit,dlg,config,{cancel:cancelDialog,close:()=>closeDialog(true),isCurrent:()=>S.dialog===dlg,notice:()=>S.notice&&S.notice.text||''});
      return dlg;
    }
    function openBranchDialog(id,returnFocus){
      const node=nodeOf(id);
      if(!node||node.state!=='live')return;
      if(S.live.size>=MAX_LIVE){say('refused',describeRefusal({code:'presentation_studio_limit_reached'},{op:'branch'}).text);return}
      openTitleDialog({kind:'branch',heading:`Brancher depuis #${node.variant_number}`,
        intro:`La nouvelle variante part d'une copie de #${node.variant_number} « ${cleanLine(node.title,50)} » ; l'original ne bouge pas.`,
        title:cleanLine(`Branche de ${cleanLine(node.title,60)}`,80),confirm:'Créer la branche',withRationale:true,returnFocus,
        run:(form)=>branch(id,form),finish:(out)=>after(out.select,out.message)});
    }
    function openRenameDialog(id,returnFocus){
      const node=nodeOf(id);
      if(!node||node.state!=='live')return;
      openTitleDialog({kind:'rename',heading:`Renommer #${node.variant_number}`,intro:'Le numéro ne change jamais.',title:cleanLine(node.title,80),
        confirm:'Renommer',unchanged:true,returnFocus,run:(form)=>rename(id,form.title),finish:(out)=>after(out.select,out.message)});
    }

    /* Archivage : plan (à blanc) -> boîte listant l'ensemble EXACT -> exécution avec le jeton. Jamais d'archivage sans plan montré. */
    async function openArchiveDialog(id,returnFocus){
      const node=nodeOf(id);
      if(!node||node.state!=='live')return;
      if(S.live.size<=1){say('refused',describeRefusal({code:'presentation_studio_active_variant_protected'}).text);return}
      let activateId=null;
      const planFor=async(activate)=>{
        const body=Object.assign({},activate?{activate_variant_id:activate}:{});
        const answer=await call('POST',variantPath(id,'/archive-plan'),body);
        return planModel(answer,S.live);
      };
      let model=null;
      const first=await perform('plan','Calcul de la liste',async()=>{model=await planFor(null);return true});
      if(!first||first.error||!model)return;
      if(model.requiresNewActive&&model.suggestedActive){activateId=model.suggestedActive;
        const again=await perform('plan','Calcul de la liste',async()=>{model=await planFor(activateId);return true});
        if(!again||again.error)return;
      }
      showArchiveDialog(id,model,activateId,planFor,returnFocus);
    }
    function showArchiveDialog(id,model,activateId,planFor,returnFocus){
      const dlg=openDialog({kind:'archive',titleId:'jvxDialogTitle',returnFocus});
      W.fillArchiveDialog(kit,dlg,{id,model,activateId,planFor},{perform,node:()=>nodeOf(id),isCurrent:()=>S.dialog===dlg,close:restore=>closeDialog(restore),
        cancel:cancelDialog,after,archive:body=>call('POST',variantPath(id,'/archive'),body)});
    }
    function updateToken(){
      const dlg=S.dialog;
      if(dlg&&dlg.kind==='archive'&&typeof dlg.tick==='function')dlg.tick();
    }

    /* -------------------------------------------------------------- menu contextuel */
    function menuItems(node){
      const items=[];
      for(const item of actionModel(node)){
        if(item.act==='restore_all')items.push({act:item.act,label:item.label,icon:item.icon,disabled:item.disabled});
        else items.push({act:item.act,label:item.label,icon:item.icon,key:item.key,danger:item.danger,disabled:item.disabled});
      }
      return items;
    }
    function closeMenu(restore){
      const menu=S.menu;
      if(!menu)return;
      S.menu=null;
      menu.node.remove();
      if(restore!==false){
        const target=menu.returnFocus;
        if(target&&target.isConnected!==false&&typeof target.focus==='function')target.focus({preventScroll:true});
      }
    }
    function openMenu(id,anchor){
      const node=nodeOf(id);
      if(!node||S.dialog)return;
      closeMenu(false);
      if(S.selectedId!==id)selectVariant(id,{});
      const kind=node.state==='archived'?'archived':'live';
      const tree=kind==='live'?ui.liveTree:ui.archiveTree;
      const returnFocus=tree.rowElement(id)||doc.activeElement;
      const {menu,buttons}=W.buildMenu(kit,{head:`#${node.variant_number} · ${cleanLine(node.title,40)}`,label:`Actions sur la variante ${node.variant_number}`,
        items:menuItems(node),anchor,width:win.innerWidth||1280,height:win.innerHeight||720,
        onPick:item=>{
          if(S.busy){say('info','Une opération est déjà en cours.');return}
          if(item.disabled){say('info',item.disabled);return}
          closeMenu(false);
          runAction(item.act,id,{returnFocus});
        }});
      ui.layer.appendChild(menu);
      S.menu={node:menu,buttons,returnFocus,id};
      menu.addEventListener('keydown',event=>onMenuKey(event));
      menu.addEventListener('mousedown',event=>event.stopPropagation());
      const first=buttons.find(b=>b.getAttribute('aria-disabled')!=='true')||buttons[0];
      if(first)first.focus({preventScroll:true});
      log('menu_opened',{variant_id:id,via:anchor&&anchor.touch?'long_press':anchor&&anchor.pointer?'pointer':'keyboard'});
    }
    function onMenuKey(event){
      const menu=S.menu;
      if(!menu)return;
      const list=menu.buttons;
      const index=list.indexOf(doc.activeElement);
      const move=i=>{event.preventDefault();event.stopPropagation();list[(i+list.length)%list.length].focus({preventScroll:true})};
      if(event.key==='ArrowDown')move(index+1);
      else if(event.key==='ArrowUp')move(index<0?list.length-1:index-1);
      else if(event.key==='Home')move(0);
      else if(event.key==='End')move(list.length-1);
      else if(event.key==='Tab'){event.preventDefault();closeMenu(true)}
      else if(event.key==='Enter'||event.key===' '){event.preventDefault();event.stopPropagation();if(list[index])list[index].click()}
    }

    /* -------------------------------------------------------------- clavier de l'hôte */
    function onHostKey(event){
      if(!S.open)return;
      if(event.key==='Escape'){
        event.preventDefault();event.stopPropagation();
        /* Imbriqué : le menu d'abord, puis la boîte, puis l'explorateur. */
        if(S.menu){closeMenu(true);return}
        if(S.dialog){cancelDialog();return}
        close({reason:'escape'});
        return;
      }
      if(event.key==='Tab'&&(S.dialog||S.menu)){
        const scope=S.dialog?S.dialog.box:S.menu.node;
        const focusable=Array.from(scope.querySelectorAll('button,input,textarea,select,[tabindex="0"]')).filter(n=>!n.disabled&&n.getAttribute('aria-disabled')!=='true'&&n.getAttribute('tabindex')!=='-1'&&n.offsetParent!==null);
        if(!focusable.length)return;
        const first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&doc.activeElement===first){event.preventDefault();last.focus()}
        else if(!event.shiftKey&&doc.activeElement===last){event.preventDefault();first.focus()}
        return;
      }
      /* Aucune touche tapée dans l'explorateur ne doit atteindre les raccourcis de la page derrière. */
      const t=event.target;
      const typing=t&&(t.isContentEditable||['INPUT','TEXTAREA','SELECT'].includes(String(t.tagName||'').toUpperCase()));
      if(!typing&&!event.ctrlKey&&!event.metaKey&&event.key.length===1)event.stopPropagation();
    }

    /* Le focus peut se perdre (sortie du plein écran, élément retiré) : l'événement part alors du corps de la page, hors de l'hôte. Pendant qu'il est
       ouvert, Échap et Tab sont donc aussi lus en capture sur le document : la page derrière est inerte, il n'y a rien d'autre à qui les laisser. */
    function onDocKey(event){
      if(!S.open||ui.host.contains(event.target))return;
      if(event.key==='Escape'){onHostKey(event);return}
      if(event.key==='Tab'){
        event.preventDefault();
        const target=S.selectedId&&nodeOf(S.selectedId)?(nodeOf(S.selectedId).state==='archived'?ui.archiveTree:ui.liveTree):ui.liveTree;
        if(!target.focus(S.selectedId||S.focus.live))ui.host.focus({preventScroll:true});
      }
    }

    /* -------------------------------------------------------------- plein écran */
    async function requestFullscreen(armS){
      const api=fullscreenApi();
      if(!api||typeof api.enter!=='function'){S.fs='unsupported';log('fullscreen_module_missing',{},'warn');return {state:'unsupported'}}
      try{
        const result=await api.enter({object_id:OBJECT_ID,keys:'none',arm_s:armS||ARM_DEFAULT_S});
        const state=result&&result.state||'refused';
        S.fs=state==='entered'||state==='needs_gesture'||state==='unsupported'||state==='refused'?state:'refused';
        if(S.fs==='needs_gesture')watchArm();
        if(state==='refused'||state==='unsupported')log('fullscreen_not_entered',{state,code:result&&result.code},'warn');
        return result||{state:'refused'};
      }catch(error){
        S.fs='refused';
        log('fullscreen_failed',{error:describe(error)},'error');
        return {state:'refused',reason:describe(error)};
      }finally{renderHeader();reportSoon()}
    }
    async function toggleFullscreen(){
      if(doc.fullscreenElement===ui.host){
        try{await doc.exitFullscreen()}catch(error){say('failed',`Sortie du plein écran impossible : ${describe(error)}. Échap quitte toujours.`)}
        return;
      }
      const result=await requestFullscreen();
      if(result.state==='refused')say('refused',`Plein écran refusé par le navigateur${result.reason?' : '+cleanLine(result.reason,120):''}. L'explorateur reste dans la fenêtre.`);
      else if(result.state==='unsupported')say('refused',"Plein écran indisponible dans ce navigateur : l'explorateur reste dans la fenêtre.");
      else if(result.state==='needs_gesture')say('info',"Cliquez « Passer en plein écran » dans l'invite en haut de la fenêtre.");
    }
    function onFullscreenChange(){
      if(!S.open)return;
      const full=doc.fullscreenElement===ui.host;
      if(full){S.fs='entered';S.fullscreenOwned=true;announce("Plein écran. Échap quitte le plein écran ; l'explorateur reste ouvert.")}
      else if(S.fullscreenOwned){
        S.fullscreenOwned=false;S.fs='exited';
        say('info',"Plein écran quitté : l'explorateur reste ouvert dans la fenêtre. Échap le ferme.");
      }
      renderHeader();reportSoon();
    }

    /* -------------------------------------------------------------- ouverture, fermeture */
    function refusal(code,reason){
      return {state:'refused',code,reason:cleanLine(reason||COMMAND_REFUSALS[code]||code,200)};
    }
    async function open(options){
      const opts=options||{};
      const presentationId=opts.presentation_id;
      if(typeof presentationId!=='string'||!ID_PRESENTATION.test(presentationId))return refusal('explorer_unknown_presentation',"Identifiant de présentation invalide.");
      if(opts.variant_id!==undefined&&opts.variant_id!==null&&!ID_VARIANT.test(opts.variant_id))return refusal('explorer_unknown_presentation',"Identifiant de variante invalide.");
      if(playing()||await corePlaying()){
        const result=refusal('explorer_run_in_progress');
        tell('Explorateur de variantes',result.reason,'warn');
        log('open_refused',{code:result.code});
        return result;
      }
      if(S.open&&S.pid===presentationId){
        if(opts.variant_id&&nodeOf(opts.variant_id))selectVariant(opts.variant_id,{focus:true});
        if(opts.fullscreen!==false&&modeNow()==='windowed')await requestFullscreen(opts.arm_s);
        return {state:'opened',mode:modeNow(),fullscreen:fsNow(),presentation_id:S.pid,variant_id:S.selectedId};
      }
      if(S.open)close({reason:'switch',quiet:true});
      try{build()}catch(error){log('build_failed',{error:describe(error)},'error');return refusal('explorer_page_error',describe(error))}
      S.generation+=1;
      S.pid=presentationId;S.presentationTitle='';S.graph=null;S.live=buildForest([],'live');S.archived=buildForest([],'archived');S.selectedId=null;
      S.focus={live:null,archived:null};S.notice=null;S.dialog=null;S.menu=null;S.fs='not_requested';
      S.preview={variantId:null,status:'idle',doc:null,scenes:[],sceneId:null,error:null,since:now(),generation:S.preview.generation+1,mounted:null};
      S.art={variantId:null,state:'idle',doc:null};
      loadPrefs();
      S.opener=opts.opener||doc.activeElement;
      S.open=true;S.loading={label:'Chargement du graphe',at:now()};
      ui.host.hidden=false;
      inerted=Array.from(doc.body.children).filter(n=>n!==ui.host&&!n.inert&&String(n.tagName).toUpperCase()!=='SCRIPT'&&!(n.classList&&n.classList.contains('toasts')));
      for(const n of inerted)n.inert=true;
      if(!ui.bound){doc.addEventListener('fullscreenchange',onFullscreenChange);ui.bound=true}
      doc.addEventListener('keydown',onDocKey,true);
      renderAll();startTicker();
      ui.title.focus({preventScroll:true});
      playbackTimer=every(checkPlayback,PLAYBACK_CHECK_MS);
      pollTimer=every(pollGraph,GRAPH_POLL_MS);
      log('opened',{presentation_id:S.pid,via:opts.via||'api'});
      /* Le plein écran se demande tout de suite : on est encore dans le geste de l'utilisateur quand il y en a un. */
      const wantFullscreen=opts.fullscreen!==false;
      const fullscreenDone=wantFullscreen?requestFullscreen(opts.arm_s):Promise.resolve({state:'not_requested'});
      if(!wantFullscreen)S.fs='not_requested';
      const generation=S.generation;
      const meta=call('GET',`${base()}`,undefined,{timeoutMs:READ_TIMEOUT_MS}).then(a=>{
        if(generation===S.generation&&a&&a.presentation)S.presentationTitle=cleanLine(a.presentation.title,80);renderHeader()}).catch(()=>{/* intentional: the title is a courtesy; the graph below reports the real failure */});
      let failure=null;
      try{
        await loadGraph({select:opts.variant_id||null,reveal:true});
      }catch(error){failure=error}
      await meta;
      if(generation!==S.generation)return refusal('explorer_page_error','Fermé pendant le chargement.');
      S.loading=null;
      if(failure){
        const info=describeRefusal(failure.info||failure,{op:'graph'});
        const unknown=failure.status===404;
        log('open_failed',{code:info.code,status:failure.status},'error');
        await fullscreenDone;
        close({reason:'load_failed'});
        tell('Explorateur de variantes',info.text,'bad');
        return refusal(unknown?'explorer_unknown_presentation':'explorer_load_failed',info.text);
      }
      renderAll();schedulePreview();
      const target=S.selectedId?nodeOf(S.selectedId):null;
      if(target){const kind=target.state==='archived'?'archived':'live';S.focus[kind]=target.variant_id;renderTrees();(kind==='live'?ui.liveTree:ui.archiveTree).focus(target.variant_id)}
      /* Le reçu ne attend pas un clic éventuel : 2,5 s au plus pour que le navigateur réponde, puis l'état OBSERVÉ (jamais « entré » deviné). */
      let waitTimer=null;
      const patience=new Promise(resolve=>{waitTimer=later(()=>resolve({state:fsNow()==='entered'?'entered':fsNow()==='needs_gesture'?'needs_gesture':'pending'}),OPEN_RECEIPT_WAIT_MS)});
      const fsResult=await Promise.race([fullscreenDone,patience]);
      if(waitTimer)cancelLater(waitTimer);
      reportSoon(true);
      return {state:'opened',mode:modeNow(),fullscreen:fsNow(),presentation_id:S.pid,variant_id:S.selectedId,fullscreen_result:fsResult&&fsResult.state};
    }
    function close(options){
      const opts=options||{};
      if(!S.open)return {state:'closed',was_open:false};
      closeMenu(false);closeDialog(false);
      doc.removeEventListener('keydown',onDocKey,true);
      S.open=false;S.generation+=1;
      for(const timer of [previewTimer,reportTimer,noticeTimer]){if(timer)cancelLater(timer)}
      previewTimer=reportTimer=noticeTimer=null;
      for(const t of [tickTimer,playbackTimer,pollTimer,armTimer])if(t)stopEvery(t);
      tickTimer=playbackTimer=pollTimer=armTimer=null;
      unmountPreview();
      if(previewHost&&typeof previewHost.destroy==='function'){try{previewHost.destroy()}catch(_error){/* intentional: the host is dropped either way */}}
      previewHost=null;
      const api=fullscreenApi();
      if(doc.fullscreenElement===ui.host){try{doc.exitFullscreen()}catch(error){log('fullscreen_exit_failed',{error:describe(error)},'warn')}}
      else if(api&&typeof api.cancel==='function'&&api.state&&api.state().armed){try{api.cancel()}catch(error){log('fullscreen_cancel_failed',{error:describe(error)},'warn')}}
      S.fullscreenOwned=false;
      for(const n of inerted)n.inert=false;
      inerted=[];
      ui.host.hidden=true;
      const target=S.opener;
      S.opener=null;
      if(!opts.quiet){
        if(target&&target.isConnected!==false&&typeof target.focus==='function')target.focus({preventScroll:true});
        else if(doc.body&&typeof doc.body.focus==='function')doc.body.focus();
      }
      for(const fn of Array.from(selectionListeners)){try{fn([])}catch(error){log('selection_listener_failed',{error:describe(error)},'error')}}
      log('closed',{reason:opts.reason||'api'});
      reportSoon(true);
      return {state:'closed',was_open:true};
    }
    function closeBecauseRun(){
      tell('Explorateur de variantes','Une lecture a démarré : l\'explorateur s\'est fermé.','warn');
      log('closed_by_run',{});
      close({reason:'run_started'});
    }
    /* La bande de lecture ne relève Core que toutes les 5 s au repos : une lecture lancée à la voix à l'instant n'y est pas encore. On le demande à Core. */
    async function corePlaying(){
      try{
        const answer=await call('GET',PLAYBACK_ROUTE,undefined,{timeoutMs:4000});
        const state=answer&&answer.state;
        return !!state&&state.running===true&&state.phase!=='stopped'&&state.phase!=='idle';
      }catch(error){
        log('playback_check_failed',{code:error.code,at:'open'},'warn');
        return false;   /* Core injoignable : le chargement du graphe, juste après, le dira avec ses mots */
      }
    }
    async function checkPlayback(){
      if(!S.open)return;
      if(playing()){closeBecauseRun();return}
      try{
        const answer=await call('GET',PLAYBACK_ROUTE,undefined,{timeoutMs:6000});
        playbackFailures=0;
        const state=answer&&answer.state;
        if(S.open&&state&&state.running===true&&state.phase!=='stopped'&&state.phase!=='idle')closeBecauseRun();
      }catch(error){
        playbackFailures+=1;
        if(playbackFailures===3)log('playback_check_failed',{code:error.code},'warn');
      }
    }
    async function pollGraph(){
      if(!S.open||S.busy||S.dialog||S.loading||doc.visibilityState==='hidden')return;
      stats.polls+=1;
      try{
        const before=S.graph?S.graph.revision:null;
        const beforeSignature=signature();
        await loadGraph({});
        if(!S.open)return;
        if(S.graph.revision!==before||signature()!==beforeSignature){
          renderAll();
          say('info',"Le graphe a changé ailleurs (voix, autre fenêtre) : la liste est à jour.");
          if(S.selectedId)schedulePreview();
        }else renderTrees();
      }catch(error){
        graphFailures+=1;
        if(graphFailures===2)say('failed',`Core ne répond plus : l'arbre affiché peut être périmé (${describeRefusal(error.info||error,{op:'graph'}).text})`,{action:{label:'Relire',run:()=>refresh()}});
      }
    }
    function signature(){return S.graph?S.graph.nodes.map(n=>`${n.variant_id}:${n.state}:${n.revision}:${n.active}`).join('|'):''}

    /* -------------------------------------------------------------- rapport d'état au Control Center (miroir lisible par l'agent) */
    function reportSoon(immediate){
      if(!fetchImpl||d.report===false)return;
      if(reportTimer)cancelLater(reportTimer);
      reportTimer=later(()=>{reportTimer=null;reportNow()},immediate?0:150);
    }
    async function reportNow(){
      const node=S.open?nodeOf(S.selectedId):null;
      const body=S.open?{open:true,mode:modeNow(),fullscreen:fsNow(),presentation_id:S.pid,variant_id:node?node.variant_id:null,
        variant_number:node&&Number.isInteger(node.variant_number)?node.variant_number:null}:{open:false,fullscreen:doc.fullscreenElement?'entered':'exited'};
      const text=JSON.stringify(body);
      if(text===lastReported)return;
      lastReported=text;
      try{await call('POST',STATE_ROUTE,body,{timeoutMs:4000})}
      catch(error){lastReported='';log('report_failed',{code:error.code},'warn')}
    }

    function onResize(){if(S.open){ui.liveTree.repaint();ui.archiveTree.repaint()}}
    if(typeof win.addEventListener==='function')win.addEventListener('resize',onResize);

    const api={
      open,close,isOpen:()=>S.open,refresh,
      selection:()=>S.open&&S.selectedId?[S.selectedId]:[],
      onSelectionChange(fn){selectionListeners.add(fn);return()=>selectionListeners.delete(fn)},
      select:(id)=>{if(S.open&&nodeOf(id))selectVariant(id,{focus:true})},
      runAction:(act,id)=>runAction(act,id||S.selectedId,{}),
      state:()=>({open:S.open,presentation_id:S.pid,selected:S.selectedId,active:S.graph&&S.graph.activeId,mode:S.open?modeNow():null,fullscreen:fsNow(),
        revision:S.graph&&S.graph.revision,live:S.live?S.live.size:0,archived:S.archived?S.archived.size:0,preview:{status:S.preview.status,scene:S.preview.sceneId,
        scenes:S.preview.scenes.length},busy:S.busy&&S.busy.label||null,dialog:S.dialog&&S.dialog.kind||null,menu:!!S.menu,notice:S.notice&&{kind:S.notice.kind,text:S.notice.text}||null,
        collapsed:Array.from(S.collapsed)}),
      stats:()=>Object.assign({},stats,{pool:ui.liveTree?ui.liveTree.poolSize():0,archivePool:ui.archiveTree?ui.archiveTree.poolSize():0}),
      element:()=>ui.host||null,
      ui:()=>ui,
      handleCommand:async(command)=>{
        stats.commands+=1;
        if(!command||typeof command!=='object')return {state:'refused',code:'explorer_page_error',reason:'commande illisible'};
        if(command.action==='close'){close({reason:'command'});return {state:'closed'}}
        if(command.action==='open'){
          const result=await open({presentation_id:command.presentation_id,variant_id:command.variant_id,fullscreen:command.fullscreen!==false,
            arm_s:command.arm_s,via:'command',opener:doc.activeElement});
          return result;
        }
        return {state:'refused',code:'explorer_page_error',reason:'action inconnue'};
      },
      destroy(){close({reason:'destroy',quiet:true});if(ui.host)ui.host.remove();if(typeof win.removeEventListener==='function')win.removeEventListener('resize',onResize);doc.removeEventListener&&doc.removeEventListener('fullscreenchange',onFullscreenChange)},
    };
    return api;
  }

  const api=Object.freeze({createStudioExplorer,createCommandChannel:W.createCommandChannel,ExplorerError});
  root.JarvisStudioExplorerModule=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installStudioExplorer(){
    const explorer=createStudioExplorer({document,window,toast:typeof toast==='function'?toast:null});
    const channel=W.createCommandChannel({fetch:window.fetch.bind(window),document,explorer,now:()=>Date.now(),
      log:(key,data,level)=>{
        const line=`[studio-explorer] ${key} ${JSON.stringify(data||{})}`;
        if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
      }});
    document.addEventListener('visibilitychange',()=>channel.setVisible(document.visibilityState!=='hidden'));
    window.JarvisStudioExplorer=Object.freeze({
      open:explorer.open,close:explorer.close,isOpen:explorer.isOpen,state:explorer.state,selection:explorer.selection,
      onSelectionChange:explorer.onSelectionChange,select:explorer.select,refresh:explorer.refresh,stats:explorer.stats,
      channel:Object.freeze({state:channel.state,stats:channel.stats,pageId:channel.pageId}),instance:explorer,
    });
    channel.setVisible(document.visibilityState!=='hidden');
    channel.start();
  }
  /* Rattrapé ici : la page servie n'a qu'une balise <script> ; une levée emporterait la scène avec elle. */
  try{installStudioExplorer()}
  catch(error){console.error('[studio-explorer] explorer_not_installed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
