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
   - une fenêtre de plus pour jouer. Depuis native-studio-playback-fix Slice 09, Variantes EST la surface d'une présentation : une lecture (bouton
     « Présenter », rail, voix, MCP, présentateur Jarvis) se montre dans son lecteur, avec la bande du présentateur, le transport (pause, élément
     précédent / suivant, position en lecture seule) et la carte § 4.15 de la colonne « présentation » (`control_center_presentation_studio_run.js`).
     Une lecture qui démarre ouvre Variantes (fenêtré, jamais en plein écran) au lieu de le fermer ; l'arbre et les actions sont inertes pendant
     la présentation (« Présentation en cours ») ; fermer Variantes met la présentation en pause. Ouvrir une AUTRE présentation pendant une
     lecture est refusé (`explorer_run_in_progress`).

   Plein écran : à l'ouverture, l'hôte (`#jvStudioExplorer`, `data-object-id="studio-explorer"`) demande le VRAI plein écran par
   `JarvisFullscreen.enter` ; par la voix il ARME (invite d'un clic, compte à rebours) et l'explorateur est déjà visible en recouvrement fenêtré,
   clairement étiqueté. Le bouton « Plein écran » de l'en-tête (et `F`) met la SCÈNE en plein écran (`data-object-id="studio-explorer-stage"` :
   le lecteur et son transport, sans l'arbre ni les métadonnées ; native-studio-playback-fix Slice 08, § 4.12). Échap
   (livré à la page) ferme d'abord le menu, puis la boîte de dialogue, puis l'explorateur ; en plein écran le navigateur garde la première pression
   pour sortir du plein écran, l'explorateur reste alors ouvert en fenêtré.

   Tout texte d'auteur (titres, raisons) passe par `textContent` après `cleanLine`, jamais par du balisage ; `dir="auto"` protège la mise en page
   d'un titre de droite à gauche. Chaque échec se voit à l'écran (zone d'état, jamais seulement un toast : hors du plein écran les toasts ne sont pas
   dessinés), est journalisé (`[studio-explorer] <clé> {json}` ; `obsClientLog` quand la page en a un) et libère l'interface dans un `finally`. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioExplorerCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_core.js'):null);
  const W=root.JarvisStudioExplorerWidgets||(typeof require==='function'?require('./control_center_presentation_studio_explorer_widgets.js'):null);
  const CmpCore=root.JarvisStudioExplorerCompareCore||(typeof require==='function'?require('./control_center_presentation_studio_explorer_compare_core.js'):null);
  const Cmp=root.JarvisStudioExplorerCompare||(typeof require==='function'?require('./control_center_presentation_studio_explorer_compare.js'):null);
  const Compose=root.JarvisStudioExplorerCompose||(typeof require==='function'?require('./control_center_presentation_studio_explorer_compose.js'):null);
  const Upgrades=root.JarvisStudioExplorerUpgrades||(typeof require==='function'?require('./control_center_presentation_studio_explorer_upgrades.js'):null);
  /* Lecture continue de la variante dans Variantes (native-studio-playback-fix Slice 05) : le contrôleur sans DOM qui tient `f`. */
  const Seq=root.JarvisVariantsSequencer||(typeof require==='function'?require('./control_center_presentation_studio_sequencer.js'):null);
  /* Son, plein écran de la scène, carte des touches (Slice 08) : contrôleurs sans DOM. */
  const Media=root.JarvisVariantsStageMedia||(typeof require==='function'?require('./control_center_presentation_studio_stage_media.js'):null);
  /* Une présentation dans Variantes (Slice 09) : la surface de Core, la bande du présentateur, les touches de la présentation. */
  const Run=root.JarvisVariantsRun||(typeof require==='function'?require('./control_center_presentation_studio_run.js'):null);
  const Frames=()=>root.JarvisRemotionFrame||(typeof require==='function'?require('./control_center_remotion_frame.js'):null);
  const Clock=()=>root.JarvisCompositionClock||(typeof require==='function'?require('./control_center_composition_clock.js'):null);
  const {ROUTE,PLAYBACK_ROUTE,COMMAND_ROUTE,STATE_ROUTE,HOST_ID,OBJECT_ID,PREVIEW_OBJECT_ID,STAGE_OBJECT_ID,STYLE_ID,ROW_H,MAX_DEPTH_SHOWN,INDENT_PX,TYPEAHEAD_MS,PAGE_TOKEN,PAGE_TOKEN_HEADER,
    REQUEST_TIMEOUT_MS,READ_TIMEOUT_MS,LONG_PRESS_MS,PREVIEW_SETTLE_MS,NOTICE_MS,COMMAND_REFUSALS,ICONS,CSS,MAX_LIVE,MAX_ARCHIVED,
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
    /* The page's playback client (`control_center_presentation_studio_player.js`): Core's view, the run's surface, the commands. */
    const player=()=>d.player||root.JarvisStudioPlayer||null;
    const playerView=()=>{const p=player();try{return p&&typeof p.view==='function'?p.view():null}catch(_error){return null}};
    const fullscreenApi=()=>d.fullscreen||root.JarvisFullscreen||null;
    const prefabApi=()=>d.prefabHost||root.JarvisPrefabHost||null;
    const stats={renders:0,paints:0,lastPaintMs:0,lastRenderMs:0,graphLoads:0,previews:0,ops:0,refusals:0,failures:0,polls:0,commands:0,staleHandled:0};
    const S={
      open:false,pid:null,presentationTitle:'',graph:null,live:null,archived:null,selectedId:null,focus:{live:null,archived:null},
      collapsed:new Set(),archivedOpen:false,prefs:readPrefs(null),loading:null,busy:null,notice:null,
      preview:{variantId:null,status:'idle',doc:null,scenes:[],sceneId:null,error:null,since:0,generation:0,mounted:null},
      art:{variantId:null,state:'idle',doc:null},fs:'not_requested',generation:0,dialog:null,menu:null,opener:null,fullscreenOwned:false,
      fsKind:null,fsOpener:null,fsLeftAt:-1e9,
      /* Slice 09: the presentation Variants hosts (`{runId, view, viewAt, busy, map}`), and the runs it has opened by itself (once each). */
      run:null,
    };
    const runsOpened=new Set();
    /* Slice 09 rework: Variants closed during a detour (Core refuses `pause` there) — the run is paused as soon as Core's view leaves the
       detour for this run (`resuming` / `playing`), once, so it never goes on unseen. Cleared when Variants opens on the run again. */
    let pauseOnReturn=null;
    let runTimeline=null;
    const ui={};
    const selectionListeners=new Set();
    let tickTimer=null,pollTimer=null,previewTimer=null,reportTimer=null,noticeTimer=null,armTimer=null,runTicker=null;
    let previewHost=null,inerted=[],idSeq=0,lastReported='',graphFailures=0;

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
      /* Un échec reste affiché jusqu'à ce qu'on le masque : un message ordinaire (info, ok) ne l'écrase pas. Un nouvel échec, lui, le remplace. */
      if(S.notice&&S.notice.kind==='failed'&&kind!=='failed'){log('notice_kept',{kept:'failed',dropped:kind});return}
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
      style.id=STYLE_ID;style.textContent=CSS+(Cmp&&Cmp.CSS||'')+(Upgrades&&Upgrades.CSS||'')+(Run&&Run.CSS||'');
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
        if(body!==undefined){init.body=JSON.stringify(body);init.headers=Object.assign({'Content-Type':'application/json'},options&&options.headers||{})}
        const response=await fetchImpl(path,init);
        let payload=null;
        try{payload=await response.json()}catch(_error){payload=null /* intentional: a non-JSON answer is reported by its HTTP status below */}
        if(!response.ok){
          const error=payload&&payload.error||{};
          throw new ExplorerError({status:response.status,code:error.code||(payload&&payload.code)||`http_${response.status}`,
            message:error.message||(payload&&typeof payload.error==='string'?payload.error:`HTTP ${response.status}`),
            conflicts:Array.isArray(error.conflicts)?error.conflicts:undefined});
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

    /* -------------------------------------------------------------- comparaison et composition (Slice 19) : modules à part, ce contrôleur ne leur prête que des aides */
    const dialogApi={open:spec=>openDialog(spec),close:restore=>closeDialog(restore),cancel:()=>cancelDialog(),current:()=>S.dialog};
    const compose=Compose.createCompose({doc,el,attrs,clear,button,later,cancelLater,log,say,announce,call,base:()=>base(),dialog:dialogApi,
      getView:()=>cmp.view(),refreshView:()=>cmp.refresh(),graphRevision:()=>S.graph?S.graph.revision:null,after:(id,message)=>after(id,message)});
    const cmp=Cmp.createCompare({doc,el,attrs,clear,button,icon,later,cancelLater,log,say,announce,call,base:()=>base(),readTimeout:READ_TIMEOUT_MS,
      nodeOf:id=>nodeOf(id),scenesOf:d=>scenesOf(d),ensureHost:()=>ensureHost(),peekHost:()=>previewHost,repaintTrees:()=>{if(S.graph)renderTrees()},
      dialog:dialogApi,compose,
      setCompareVisible:on=>{if(ui.preview)ui.preview.hidden=!!on},
      onActive:on=>{
        if(on){if(previewTimer){cancelLater(previewTimer);previewTimer=null}if(seq)seq.reset('compare');unmountPreview()}
        else if(S.open&&S.selectedId)schedulePreview();
      }});

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
      cmp.onGraph();
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
    /* Nouvelle version d'un prefab épinglé (Remotion Slice 19) : avis et essai en variante, module à part ; l'essai est une écriture (occupation, relecture du graphe). */
    const upgrades=Upgrades.createUpgrades({doc,el,attrs,clear,button,icon,uid,later,cancelLater,every,stopEvery,now,log,announce,call,readTimeout:READ_TIMEOUT_MS,
      variantPath:(id,tail)=>variantPath(id,tail),node:()=>nodeOf(S.selectedId),scenes:()=>S.preview.variantId===S.selectedId?S.preview.scenes:[],
      busy:()=>!!S.busy,blocked:()=>S.writing||(!!S.busy&&!!S.busy.op&&S.busy.op!=='plan'),revision:()=>S.graph?S.graph.revision:null,isOpen:()=>S.open,say:(kind,text)=>say(kind,text),select:id=>{if(nodeOf(id))selectVariant(id,{focus:true})},
      perform:(op,label,fn)=>perform(op,label,fn),after:(id,message)=>after(id,message),describe:error=>describeRefusal(error.info||error,{op:'upgrades'})});

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
      ui.fsButton=button(null,null,(event)=>{toggleFullscreen({other:!!(event&&event.shiftKey)})});
      ui.fsIconIn=icon('expand');ui.fsIconOut=icon('contract');ui.fsLabel=el('span','jvx-btn-label-long','Plein écran');
      ui.fsButton.appendChild(ui.fsIconIn);ui.fsButton.appendChild(ui.fsIconOut);ui.fsButton.appendChild(ui.fsLabel);
      ui.closeButton=button('Fermer',null,()=>{close({reason:'user'})},{icon:'close',labelClass:'jvx-btn-label-long',attrs:{'aria-label':'Fermer Variantes',title:'Fermer (Échap)'}});
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
      ui.treePane=treePane;
      const head=el('div','jvx-panehead');
      head.appendChild(el('h2','jvx-panetitle','Évolution'));
      ui.count=el('span','jvx-chip');
      head.appendChild(ui.count);
      /* Slice 09: while a presentation plays here, the tree and the actions are inert, and this chip says why. */
      ui.runChip=el('span','jvx-chip','Présentation en cours');ui.runChip.hidden=true;ui.runChip.setAttribute('data-tone','accent');
      head.appendChild(ui.runChip);
      ui.liveTree=W.createTreeView(kit,{collapsed:()=>S.collapsed,label:'Variantes de la présentation',
        onSelect:(id,o)=>{if(o&&o.ctrl){cmp.toggleMark(id);return}selectVariant(id,{focus:true,pointer:o&&o.pointer})},onToggle:id=>toggleFold(id),
        onKey:(event,id,rows,index)=>onTreeKey('live',event,id,rows,index),onFocus:id=>{S.focus.live=id;syncRoving('live')},
        onMenu:(id,anchor)=>openMenu(id,anchor)});
      const archive=el('section','jvx-archive');
      archive.setAttribute('data-open','false');
      ui.archiveToggle=button(null,'jvx-archive-toggle',()=>toggleArchive(),{attrs:{'aria-expanded':'false'}});
      ui.archiveToggle.appendChild(icon('chevron'));
      ui.archiveLabel=el('span','','Archivées');ui.archiveToggle.appendChild(ui.archiveLabel);
      ui.archiveTree=W.createTreeView(kit,{collapsed:()=>S.collapsed,label:'Variantes archivées',
        onSelect:(id,o)=>{if(o&&o.ctrl){cmp.toggleMark(id);return}selectVariant(id,{focus:true,pointer:o&&o.pointer})},onToggle:id=>toggleFold(id),
        onKey:(event,id,rows,index)=>onTreeKey('archived',event,id,rows,index),onFocus:id=>{S.focus.archived=id;syncRoving('archived')},
        onMenu:(id,anchor)=>openMenu(id,anchor)});
      ui.archive=archive;
      archive.appendChild(ui.archiveToggle);archive.appendChild(ui.archiveTree.element);
      /* Slice 10 (§ 6 #6): the key hint is merged into the keyboard sheet; this line only says where it is (text, not a second control). */
      ui.hint=el('p','jvx-hint-keys');
      ui.hint.textContent='Touche ? : raccourcis clavier';
      treePane.appendChild(head);treePane.appendChild(cmp.buildBar());treePane.appendChild(ui.liveTree.element);treePane.appendChild(ui.hint);treePane.appendChild(archive);
      const preview=el('section','jvx-preview');
      attrs(preview,{'aria-label':'Aperçu de la variante choisie'});
      const wrap=el('div','jvx-stagewrap');
      ui.stage=el('div','jvx-stage');
      attrs(ui.stage,{role:'group',tabindex:'0','aria-roledescription':'aperçu de scène'});
      ui.slot=el('div','jvx-slot');
      ui.veil=el('div','jvx-stage-veil');
      ui.veilTitle=el('strong');ui.veilText=el('span');ui.veilAction=button('',null,()=>{if(ui.veilRun)ui.veilRun()});ui.veilAction.hidden=true;
      ui.veilAction2=button('',null,()=>{if(ui.veilRun2)ui.veilRun2()});ui.veilAction2.hidden=true;
      const veilActions=el('div','jvx-veil-actions');veilActions.appendChild(ui.veilAction);veilActions.appendChild(ui.veilAction2);
      ui.veil.appendChild(ui.veilTitle);ui.veil.appendChild(ui.veilText);ui.veil.appendChild(veilActions);
      /* Lecture continue : la scène suivante charge encore (Slice 05). Texte stable pour les lecteurs d'écran, compteur à part (caché d'eux). */
      ui.wait=el('div','jvx-stage-wait');ui.wait.hidden=true;attrs(ui.wait,{role:'status','aria-live':'polite'});
      ui.waitText=el('span');ui.waitCount=el('span');ui.waitCount.setAttribute('aria-hidden','true');
      ui.wait.appendChild(ui.waitText);ui.wait.appendChild(ui.waitCount);
      /* Slice 08: the sound the browser refused, said on the image itself (also in fullscreen, where the notice zone is not drawn). */
      ui.soundPill=el('div','jvx-stage-sound');ui.soundPill.hidden=true;attrs(ui.soundPill,{role:'status','aria-live':'polite'});
      ui.catcher=el('div','jvx-catch');ui.catcher.setAttribute('aria-hidden','true');
      for(const type of ['pointermove','pointerdown'])ui.catcher.addEventListener(type,()=>chrome.poke());
      /* Slice 09: a detour of the presentation is an overlay INSIDE the stage (never a Board window). */
      ui.overlay=el('div','jvx-stage-overlay');ui.overlay.hidden=true;attrs(ui.overlay,{role:'region','aria-label':'Ressource annexe de la présentation'});
      ui.stage.appendChild(ui.slot);ui.stage.appendChild(ui.overlay);ui.stage.appendChild(ui.veil);ui.stage.appendChild(ui.wait);ui.stage.appendChild(ui.soundPill);ui.stage.appendChild(ui.catcher);
      wrap.appendChild(ui.stage);
      const note=el('div','jvx-stage-note');
      const sceneLine=el('div','jvx-scene-line');ui.sceneLine=sceneLine;
      ui.sceneTitle=el('span','jvx-scene-title jvx-bidi');ui.sceneTitle.setAttribute('dir','auto');
      ui.sceneRole=el('span','jvx-chip');
      ui.sceneBadge=el('span','jvx-chip');
      sceneLine.appendChild(ui.sceneTitle);sceneLine.appendChild(ui.sceneRole);sceneLine.appendChild(ui.sceneBadge);
      ui.sceneCount=el('span','jvx-scene-count');
      /* One row under the stage: the transport, then the scene it is on (every pixel of height is the stage's width). */
      buildTransport();
      /* Slice 10 (Slice 02 inventory § 2): row 1 is the transport alone, so the slider gets the width; row 2 is « Scène n sur N », the scene
         title and « Présenter » (not a playback control). During a run row 2 gives way to the presenter strip; in fullscreen only row 1 shows. */
      note.appendChild(ui.transport);note.appendChild(ui.sceneCount);note.appendChild(sceneLine);note.appendChild(ui.present);
      ui.strip=el('div','jvx-strip');
      attrs(ui.strip,{role:'listbox','aria-label':'Scènes de la variante','aria-orientation':'horizontal'});
      const bottom=el('div','jvx-bottom');
      ui.meta=el('div','jvx-meta');
      ui.actions=el('div','jvx-actions');attrs(ui.actions,{role:'toolbar','aria-label':'Actions sur la variante choisie'});
      /* Slice 10: during a run the actions stay on screen, dimmed and inert, and this line says why (the chip is far, in the tree). */
      ui.runNote=el('p','jvx-run-note',RUN_BUSY);ui.runNote.hidden=true;
      const actionsCol=el('div','jvx-actions-col');actionsCol.appendChild(ui.actions);actionsCol.appendChild(ui.runNote);
      bottom.appendChild(ui.meta);bottom.appendChild(actionsCol);
      ui.upgrades=upgrades.buildSection();
      /* The « theater » (Slice 08): the stage and its transport, the one fullscreen target of « Plein écran » (§ 4.12). */
      ui.theater=el('div','jvx-theater');
      attrs(ui.theater,{'data-object-id':STAGE_OBJECT_ID,'aria-label':'Vidéo de la variante'});
      ui.theater.appendChild(wrap);ui.theater.appendChild(note);
      for(const type of ['pointermove','focusin','keydown'])ui.theater.addEventListener(type,()=>chrome.poke());
      /* Slice 09: the presenter strip (§ 5), windowed only, under the stage: it replaces the floating band. */
      ui.presenter=buildPresenter();
      preview.appendChild(ui.theater);preview.appendChild(ui.presenter);preview.appendChild(ui.strip);preview.appendChild(bottom);preview.appendChild(ui.upgrades);
      ui.preview=preview;
      body.appendChild(treePane);body.appendChild(preview);body.appendChild(cmp.buildRoot());
      ui.live=el('div','jvx-sr');attrs(ui.live,{role:'status','aria-live':'polite','aria-atomic':'true'});
      ui.layer=el('div','jvx-layer');
      for(const node of [top,ui.notice,body,ui.live,ui.layer])host.appendChild(node);
      host.addEventListener('keydown',onHostKey);
      ui.stage.addEventListener('keydown',onTransportKey);
      ui.transport.addEventListener('keydown',onTransportKey);
      ui.strip.addEventListener('keydown',onSceneKey);
      doc.body.appendChild(host);
      ui.host=host;
      return host;
    }

    /* -------------------------------------------------------------- rendu */
    /* Variants is fullscreen: the workspace (an opening that asked for it) or the stage (« Plein écran », `F`; Slice 08). */
    function fullscreenNow(){const fs=doc.fullscreenElement;return !!fs&&!!ui.host&&(fs===ui.host||fs===ui.theater)}
    function modeNow(){
      if(fullscreenNow())return 'fullscreen';
      const api=fullscreenApi(),st=api&&typeof api.state==='function'?api.state():null;
      return st&&st.armed?'fullscreen_armed':'windowed';
    }
    function armedNow(){
      const api=fullscreenApi(),st=api&&typeof api.state==='function'?api.state():null;
      return !!(st&&st.armed);
    }
    function fsNow(){
      if(fullscreenNow())return 'entered';
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
      const why=S.fs==='unsupported'?"Plein écran indisponible dans ce navigateur : Variantes reste dans la fenêtre.":
        S.fs==='refused'?"Plein écran refusé par le navigateur : Variantes reste dans la fenêtre.":'';
      ui.modeChip.title=mode==='windowed'&&why?why:mode==='fullscreen_armed'?"Cliquez « Passer en plein écran » dans l'invite en haut de la fenêtre.":'';
      if(mode==='windowed'&&why)ui.modeChip.textContent='Fenêtré — '+(S.fs==='unsupported'?'plein écran indisponible':'plein écran refusé');
      const full=mode==='fullscreen';
      ui.fsIconIn.style.display=full?'none':'';ui.fsIconOut.style.display=full?'':'none';
      ui.fsLabel.textContent=full?'Quitter le plein écran':'Plein écran';
      ui.fsButton.setAttribute('aria-label',ui.fsLabel.textContent);   // the label hides on a narrow window: the name stays (Slice 10)
      const live=S.graph?S.live.size:0,dead=S.graph?S.archived.size:0;
      ui.subtitle.textContent=S.graph?`${S.presentationTitle?cleanLine(S.presentationTitle,80)+' · ':''}${live} variante${live>1?'s':''}${dead?` · ${dead} archivée${dead>1?'s':''}`:''}`:cleanLine(S.presentationTitle,80);
      /* Authoring metadata, never a position (Slice 10, § 6 « every readout »): it says what it counts. */
      ui.count.textContent=S.graph?`${live} / ${MAX_LIVE} variantes`:'';
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
      return {get marked(){return cmp.markSet()},get selectedId(){return S.selectedId},get activeId(){return S.graph&&S.graph.activeId},get focusId(){return S.focus[kind]||null},
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
    /* `[` and `]` go to the previous / next live variant by number, from anywhere in Variants. The variant bar that showed them as chips is
       merged into the tree (Slice 10, § 6 #8): the tree is the one place where a variant is chosen. */
    function liveNodes(){
      const nodes=S.graph?S.graph.nodes.filter(n=>n&&n.state==='live'&&typeof n.variant_id==='string'):[];
      return nodes.sort((a,b)=>(Number(a.variant_number)||0)-(Number(b.variant_number)||0));
    }
    function stepVariant(delta){
      const nodes=liveNodes();
      if(nodes.length<2)return false;
      const index=Math.max(0,nodes.findIndex(n=>n.variant_id===S.selectedId));
      const next=nodes[Math.max(0,Math.min(nodes.length-1,index+delta))];
      if(!next||next.variant_id===S.selectedId)return true;
      selectVariant(next.variant_id,{});
      return true;
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
      renderHeader();renderNotice();renderTrees();renderMeta();renderActions();renderStrip();renderStage();cmp.renderBar();
      stats.lastRenderMs=now()-t0;
    }

    /* -------------------------------------------------------------- métadonnées, actions */
    function renderMeta(){
      const node=nodeOf(S.selectedId);
      const preview=S.preview;
      const path=node?[...Core.ancestorsOf(node.state==='archived'?S.archived:S.live,node.variant_id).reverse().map(nodeOf).filter(Boolean),node]:[];
      W.renderMeta(kit,ui.meta,{graphReady:!!S.graph,node,path,parent:node?nodeOf(node.parent_variant_id):null,
        isActive:!!node&&S.graph.activeId===node.variant_id,isPlaying:!!node&&runningVariantId()===node.variant_id,
        score:node&&preview.variantId===node.variant_id&&preview.doc?(preview.doc.score_id?'Partition liée':'Sans partition'):null,
        art:node&&S.art.variantId===node.variant_id?S.art:{state:'idle'}});
      upgrades.sync(node,S.graph?S.graph.revision:null);
    }
    function actionModel(node){
      const live=S.live?S.live.size:0;
      const out=[];
      if(!node)return out;
      const archived=node.state==='archived';
      const busy=!!S.busy||!!S.run;
      const busyText=S.run?RUN_BUSY:'Une opération est en cours.';
      const add=(act,label,iconName,key,opts)=>out.push(Object.assign({act,label,icon:iconName,key,disabled:busy?busyText:null},opts||{}));
      if(archived){
        const dead=S.archived;
        const withKids=dead&&dead.kids.get(node.variant_id);
        add('restore','Restaurer','restore','R',{});
        if(withKids&&withKids.length)add('restore_all','Restaurer avec ses sous-branches','restore','',{});
      }else{
        add('activate','Activer','power','A',{disabled:busy?busyText:S.graph.activeId===node.variant_id?'Cette variante est déjà la variante active.':null});
        add('branch','Brancher d\'ici…','fork','N',{disabled:busy?busyText:live>=MAX_LIVE?`${MAX_LIVE} variantes vivantes au plus : archivez des branches abandonnées d'abord.`:null});
        add('rename','Renommer…','pencil','F2',{});
        add('archive','Archiver…','box','Suppr',{danger:true,disabled:busy?busyText:live<=1?'Une présentation garde toujours au moins une variante vivante.':null});
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
        /* `swapPrefix` (Slice 05) : une autre scène `presentation-studio.*` se prépare À CÔTÉ de la scène vivante et ne la remplace qu'une
           fois prête (plus de cadre vide entre deux scènes), et la suivante se précharge. `onLive` / `onClock` / `onOutcome` : ce que la
           lecture continue écoute (Player devenu vivant, position du Player, échec d'une scène). */
        /* `autoplay: false`, `embed: 'variants'` (Slice 06): the Player opens paused on frame 0 and only the transport below plays it (§ 4.1);
           the stage page shows no bar of its own (§ 2). */
        previewHost=api.createPrefabHost({mode:'preview',document:doc,window:win,swapPrefix:'presentation-studio.',autoplay:false,embed:'variants',
          fetchBundle:api.bundleFetcher((path,options)=>fetchImpl(path,Object.assign({cache:'no-store'},options))),
          onPreviewEvent:()=>{/* intentional: the preview frame writes nothing anywhere; its events are dropped */},
          onLive:(id)=>{if(runAdapter.owns(id))runAdapter.onLive(id);else if(seq)seq.onLive(id)},
          onClock:(id)=>{if(runAdapter.owns(id)){runAdapter.onClock(id);renderRunPosition()}else if(seq)seq.onClock(id)},
          onOutcome:(info)=>{if(info&&runAdapter.owns(info.object_id))reportRunOutcome(info);else if(seq)seq.onOutcome(info)},
          /* Slice 09: the run's frame keeps the events it had in its stage window (`state` writes the surface's data, `notify` reaches the brain). */
          posts:(id)=>runAdapter.owns(id),postEvent:(event)=>postFrameEvent(event),
          /* Slice 08: the real state of the scene's sound, and a § 4.15 key typed in the scene that has the focus. */
          onSound:(id,audio)=>{if(id===PREVIEW_OBJECT_ID||id===runAdapter.objectId())sound.onAudio(audio)},onKey:(id,key)=>onFrameKey(id,key),
          log:(key,data)=>{const k=String(key);log('preview_host_'+k.replace(/^scene\./,''),data,PREVIEW_HOST_INFO.has(k)?'info':'warn')}});
      }catch(error){log('preview_host_failed',{error:describe(error)},'error');previewHost=null}
      if(previewHost)sound.attach();   // muted at opening (§ 4.14), or the sound the user turned on in this opening
      return previewHost;
    }
    /* -------------------------------------------------------------- lecture continue (Slice 05) et transport (Slice 06) */
    const PREVIEW_HOST_INFO=new Set(['scene.prefab_mounted','scene.prefab_preloaded','scene.prefab_swapped','scene.prefab_preload_queued']);
    let seq=null;
    function sequencer(){
      if(seq||!Seq)return seq;
      seq=Seq.createSequencer({objectId:PREVIEW_OBJECT_ID,host:()=>previewHost,now,setTimeout:later,clearTimeout:cancelLater,requestFrame:frame,
        log:(key,data,level)=>log(key,data,level),
        scenes:()=>S.preview.status==='ready'?S.preview.scenes:[],
        revision:()=>S.preview.doc&&Number.isInteger(S.preview.doc.revision)?S.preview.doc.revision:null,
        selectedIndex:()=>Math.max(0,S.preview.scenes.findIndex(s=>s.id===S.preview.sceneId)),
        fetchClock:()=>call('GET',variantPath(S.preview.variantId,'/composition-clock'),undefined,{timeoutMs:READ_TIMEOUT_MS}),
        show:(index)=>{const scene=S.preview.scenes[index];if(scene)showScene(scene.id)},
        variantChanged:()=>{say('info',"La variante a changé : l'aperçu est relu. Relancez la lecture.");schedulePreview()},
        changed:()=>renderPlayback()});
      return seq;
    }
    /* The map is read as soon as the preview is ready (§ 4.1): the transport shows `f` before anything plays, and a variant without video says
       so on « Lire ». Nothing is ordered to the Player, which already holds frame 0 of the scene on screen. */
    function preparePlayback(){
      if(S.run||cmp.isActive()||S.preview.status!=='ready'||!S.preview.scenes.length)return;
      const s=sequencer();
      if(!s||s.active())return;
      ensureHost();
      s.prepare().catch(error=>log('playback_prepare_failed',{error:describe(error)},'error'));
    }
    /* A playback command from the transport, a key or the page API: refused with its reason when it cannot run, its failure said. `run` gets
       the sequencer. */
    async function playback(run){
      if(S.run){say('info','Une présentation est en cours : la partition la mène. « Arrêter » pour revenir à la vidéo.');return null}
      if(cmp.isActive()){say('info',"La lecture se fait hors de la comparaison : fermez-la d'abord.");return null}
      if(S.preview.status!=='ready'||!S.preview.scenes.length){say('info',"Aucune scène à lire : attendez l'aperçu.");return null}
      const s=sequencer();
      if(!s){say('failed',"La lecture continue n'est pas chargée dans cette page.");return null}
      ensureHost();
      const before=s.view();
      if(before.phase==='unavailable'&&!before.retryable){say('info',unavailableText(before));return before}
      try{
        const v=await run(s);
        if(v&&v.phase==='failed'&&v.error)say('failed',playbackError(v.error));
        else if(v&&v.phase==='unavailable')say(v.retryable?'failed':'info',unavailableText(v));
        return v;
      }catch(error){
        say('failed',`Lecture impossible : ${describe(error)}`);
        log('playback_failed',{error:describe(error)},'error');
        return null;
      }finally{renderPlayback()}
    }
    function togglePlayback(){
      if(S.run){const m=runModel();return m.active?runCommand(m.pause.command):null}
      return playback(s=>s.view().phase==='failed'?s.retry():s.toggle());
    }
    function playSceneOnly(){return playback(s=>s.playScene())}
    function playbackError(error){
      const where=Number.isInteger(error.scene_index)?`Scène ${error.scene_index+1}${error.scene_title?` « ${cleanLine(error.scene_title,60)} »`:''} : `:'';
      return `${where}${cleanLine(error.message,220)}`;
    }
    function unavailableText(v){
      if(!v.retryable)return 'La lecture vidéo n\'existe que pour une présentation Remotion'+(v.error?` (${playbackError(v.error)}).`:'.');
      return `Vidéo indisponible : ${v.error?playbackError(v.error):'la carte de la vidéo n\'a pas pu être lue'}. « Lire » réessaie.`;
    }

    /* The one transport of Variants (contract § 4, § 4.16, § 6 #15-#20): a named toolbar under the stage, read only from the sequencer's
       `f`. The stage page shows no bar of its own (`embed: 'variants'`). */
    /* Slice 08: « Son » and `M` turn the sound of the scene on screen on and off (§ 4.14); a frame loaded ahead stays muted. */
    const sound=Media.createSound({host:()=>previewHost,log:(key,data,level)=>log(key,data,level),say:(kind,text)=>say(kind,text),
      announce:(text)=>announce(text),changed:()=>renderSound()});
    /* Slice 08: the transport over the stage in fullscreen, hidden while the video plays (§ 4.12, § 4.16). */
    const chrome=Media.createChrome({setTimeout:later,clearTimeout:cancelLater,
      apply:(hidden)=>{if(ui.theater){if(hidden)ui.theater.setAttribute('data-chrome','hidden');else ui.theater.removeAttribute('data-chrome')}},
      playing:()=>{if(S.run)return S.run.view.phase==='playing';const v=seq?seq.view():null;return !!v&&(v.phase==='playing'||v.phase==='waiting')},
      pinned:()=>!!S.menu||!!(ui.transport&&ui.transport.contains(doc.activeElement))});
    function toggleSound(){
      if(!ensureHost()){say('failed',Media.TEXT.unavailable);return}
      sound.toggle();
    }
    function renderSound(){
      if(!ui.sound)return;
      const v=sound.view();
      ui.sound.setAttribute('aria-pressed',v.pressed?'true':'false');
      ui.sound.title=v.title;
      if(v.blocked)ui.sound.setAttribute('data-sound','blocked');else ui.sound.removeAttribute('data-sound');
      clear(ui.soundIcon);ui.soundIcon.appendChild(icon(v.on?'sound':'muted'));
      ui.soundPill.hidden=!v.pill;ui.soundPill.textContent=v.pill;
    }
    const NO_POSITION='La position paraît dès que la vidéo est prête.';
    let drag=null;
    function buildTransport(){
      ui.transport=el('div','jvx-transport');
      attrs(ui.transport,{role:'toolbar','aria-label':'Lecture de la vidéo'});
      ui.prevScene=button(null,'jvx-btn jvx-btn-icon',()=>moveScene(-1),{icon:'first',attrs:{'aria-label':'Scène précédente',title:'Début de la scène précédente (←, Page précédente)'}});
      ui.playAll=button(null,'jvx-btn',()=>{togglePlayback()},{attrs:{'data-act':'continuous',title:'Lire la vidéo en continu, de la position à la fin (Espace)'}});
      ui.playAllIcon=el('span','jvx-icon-slot');ui.playAllIcon.appendChild(icon('play'));ui.playAllLabel=el('span','','Lire');
      ui.playAll.appendChild(ui.playAllIcon);ui.playAll.appendChild(ui.playAllLabel);
      ui.nextScene=button(null,'jvx-btn jvx-btn-icon',()=>moveScene(1),{icon:'last',attrs:{'aria-label':'Scène suivante',title:'Début de la scène suivante (→, Page suivante)'}});
      ui.scrub=el('div','jvx-scrub');
      attrs(ui.scrub,{role:'slider',tabindex:'0','aria-label':'Position dans la vidéo','aria-valuemin':'0','aria-disabled':'true'});
      ui.scrubTrack=el('div','jvx-scrub-track');ui.scrubFill=el('div','jvx-scrub-fill');ui.scrubTicks=el('div','');ui.scrubThumb=el('div','jvx-scrub-thumb');
      for(const node of [ui.scrubTrack,ui.scrubFill,ui.scrubTicks,ui.scrubThumb])ui.scrub.appendChild(node);
      ui.scrub.addEventListener('keydown',onScrubKey);
      ui.scrub.addEventListener('pointerdown',onScrubDown);
      ui.scrub.addEventListener('pointermove',(event)=>{if(drag)scrubAt(event.clientX)});
      /* `lostpointercapture` too: a drag cut short (capture taken away, the window left) ends there and never outlives its gesture. */
      for(const type of ['pointerup','pointercancel','lostpointercapture'])ui.scrub.addEventListener(type,endDrag);
      ui.time=el('span','jvx-time');
      ui.sound=button(null,'jvx-btn jvx-btn-icon',()=>toggleSound(),{attrs:{'aria-label':'Son','aria-pressed':'false',title:Media.TEXT.titleOff}});
      ui.soundIcon=el('span','jvx-icon-slot');ui.soundIcon.appendChild(icon('muted'));ui.sound.appendChild(ui.soundIcon);
      ui.more=button(null,'jvx-btn jvx-btn-icon',()=>openPlaybackMenu(),{icon:'more',attrs:{'aria-label':'Plus de lecture','aria-haspopup':'menu','aria-expanded':'false',title:'Plus de lecture'}});
      /* § 5 / § 6 #21 (Slice 09): « Présenter ▾ » starts a presenter run here; during the run « Arrêter » stops it (also in fullscreen). */
      ui.present=button('Présenter','jvx-btn',()=>openPresentMenu(),{attrs:{'aria-haspopup':'menu','aria-expanded':'false','data-act':'present',
        title:'Présenter cette variante : vous, Jarvis, ou une répétition (la partition mène)'}});
      ui.stopRun=button('Arrêter','jvx-btn',()=>{runCommand('stop')},{attrs:{'data-act':'stop_run','data-danger':'',title:'Arrêter la présentation'}});
      ui.stopRun.hidden=true;
      for(const node of [ui.prevScene,ui.playAll,ui.nextScene,ui.scrub,ui.time,ui.sound,ui.more,ui.stopRun])ui.transport.appendChild(node);
    }
    /* ⏮ ⏭, ← →, Page précédente / suivante: the start of the previous / next scene, play state kept (§ 4.4). Without a map (a variant
       without video, or before it is read) they browse the scenes. Next on the last scene says why it does nothing. */
    function moveScene(delta){
      if(S.run){runCommand(delta>0?'next':'previous');return true}
      if(seq&&seq.active()){
        const v=seq.view();
        if(delta>0&&v.scene_index>=v.scene_count-1){say('info','Dernière scène.');return true}
        if(seq.seek(delta>0?'next':'previous'))announceScene();
        return true;
      }
      return browseScene(delta);
    }
    function seekTo(kind,value){
      if(!(seq&&seq.active()))return false;
      return seq.seek(kind,value);
    }
    /* A scene change made by the user is said once (§ 4.16); continuous play never is. */
    function announceScene(){
      const v=seq.view();
      if(v.scene_index>=0&&v.scene_title)announce(`Scène ${v.scene_index+1} sur ${v.scene_count} : ${v.scene_title}`);
    }
    /* The § 4.15 map (one table, `Media.keyAction`), on the stage, the transport, the strip (F, M) and for the keys the scene passes on.
       Returns whether the key acted. `Escape` is not here: it is the nested rule of the host (`onHostKey`). */
    function transportKey(key,event){
      const action=Media.keyAction(key);
      if(S.run){
        /* § 4.15, column « Presenter run »: the score moves, never `f`; `S` leaves a locked sequence; F, M as in the video. */
        const asked=Run.keyCommand(key==='s'||key==='S'?'skip':action,S.run.view);
        if(asked&&asked.said){say('info',asked.said);return true}
        if(asked){runCommand(asked.verb,asked.body);return true}
      }
      if(action==='toggle')togglePlayback();
      else if(action==='next')moveScene(1);
      else if(action==='previous')moveScene(-1);
      else if(action==='home'){if(!seekTo('home'))browseScene(0,0)}
      else if(action==='end'){if(!seekTo('end'))browseScene(0,S.preview.scenes.length-1)}
      else if(action==='step_back'||action==='step_forward'){if(!seekTo('step',action==='step_back'?-1:1)&&seq&&seq.view().playing)say('info','Image par image : mettez d\'abord en pause.')}
      else if(action==='fullscreen')toggleFullscreen({other:!!(event&&event.shiftKey)});
      else if(action==='sound')toggleSound();
      else return false;
      return true;
    }
    /* The slider's own ARIA keys win (it stops them); a focused button acts on Space itself. */
    function onTransportKey(event){
      if(event.ctrlKey||event.altKey||event.metaKey||event.defaultPrevented)return;
      const tag=String(event.target&&event.target.tagName||'').toUpperCase();
      if(['INPUT','TEXTAREA','SELECT'].includes(tag))return;
      if(event.key===' '&&tag==='BUTTON')return;
      if(event.key==='Escape')return;
      if(transportKey(event.key,event)){event.preventDefault();event.stopPropagation()}
    }
    /* A key typed in the scene (the cross-origin frame keeps it; its stage page passes it on only while the scene has the focus): it acts
       once, here, only while the focus is really in the stage, and never while a menu or a dialog is open (Slice 08). */
    function onFrameKey(objectId,key){
      if(!S.open||(objectId!==PREVIEW_OBJECT_ID&&objectId!==runAdapter.objectId())||S.dialog||S.menu)return;
      const active=doc.activeElement;
      if(!(active&&ui.stage&&ui.stage.contains(active)))return;
      chrome.poke();
      if(key==='Escape'){escapeKey();return}
      transportKey(key,null);
    }
    /* ARIA slider keys (§ 4.6): ← → one second, Page précédente / suivante the previous / next scene start, Début / Fin. */
    function onScrubKey(event){
      if(event.ctrlKey||event.altKey||event.metaKey)return;
      const keys=['ArrowRight','ArrowUp','ArrowLeft','ArrowDown','PageUp','PageDown','Home','End'];
      if(!keys.includes(event.key))return;
      event.preventDefault();event.stopPropagation();
      if(S.run){say('info',RUN_SCRUB);return}
      const v=seq&&seq.active()?seq.view():null;
      if(!v){say('info',noPositionText());return}
      const second=v.fps;
      if(event.key==='ArrowRight'||event.key==='ArrowUp')seq.seek('scrub',Math.min(v.total_frames-1,v.frame+second));
      else if(event.key==='ArrowLeft'||event.key==='ArrowDown')seq.seek('scrub',Math.max(0,v.frame-second));
      else if(event.key==='PageDown')seq.seek('next');
      else if(event.key==='PageUp')seq.seek('previous');
      else seq.seek(event.key==='Home'?'home':'end');
    }
    /* No map yet: while it is read (or before), a neutral wording; the failure is said only once the map really failed (§ 4.2). */
    function noPositionText(){
      if(!seq)return "La lecture continue n'est pas chargée dans cette page.";
      const v=seq.view();
      return v.error&&['unavailable','failed','idle'].includes(v.phase)?unavailableText(v):NO_POSITION;
    }
    /* Dragging pauses for the drag and gives the play state back on release (§ 4.6); one seek per animation frame at most (the sequencer). */
    function onScrubDown(event){
      if(S.run){say('info',RUN_SCRUB);return}
      if(!(seq&&seq.active())||(event.button!==undefined&&event.button>0))return;
      event.preventDefault();
      ui.scrub.focus({preventScroll:true});
      drag={wasPlaying:seq.view().playing};
      if(drag.wasPlaying)seq.pause();
      try{ui.scrub.setPointerCapture(event.pointerId)}catch(_error){/* intentional: without capture the drag ends when the pointer leaves */}
      scrubAt(event.clientX);
    }
    function scrubAt(x){
      const v=seq.view(),box=ui.scrub.getBoundingClientRect();
      if(!v.total_frames||!box.width)return;
      seq.seek('scrub',Math.max(0,Math.min(v.total_frames-1,Math.round((x-box.left)/box.width*(v.total_frames-1)))));
    }
    function endDrag(){
      if(!drag)return;
      const resume=drag.wasPlaying;
      drag=null;
      if(resume)playback(s=>s.play());
    }
    /* « ⋯ » (§ 6 #20): « Lire seulement cette scène » (PX-21) and « Revenir au début ». The menu is the explorer's; focus goes back to « ⋯ ». */
    function openPlaybackMenu(){
      if(S.dialog)return;
      if(S.menu){closeMenu(true);return}
      const box=ui.more.getBoundingClientRect?ui.more.getBoundingClientRect():{left:80,bottom:80};
      /* During a presentation the menu speaks of score items, never of the video's position (the score leads, § 5). */
      const items=(S.run?[{act:'first_item',label:'Premier élément',icon:'first',key:'Début'},{act:'last_item',label:'Dernier élément',icon:'last',key:'Fin'}]
        :[{act:'scene_only',label:'Lire seulement cette scène',icon:'play'},{act:'home',label:'Revenir au début',icon:'restore',key:'Début'}])
        .concat([{act:'shortcuts',label:'Raccourcis clavier',icon:'keyboard',key:'?'}]);   // § 6 #20 (Slice 10)
      const {menu,buttons}=W.buildMenu(kit,{head:S.run?'Présentation':'Lecture',label:'Plus de lecture',items,anchor:{x:box.left,y:box.bottom+4},
        width:win.innerWidth||1280,height:win.innerHeight||720,
        onPick:item=>{
          closeMenu(true);
          if(item.act==='shortcuts')openShortcuts(ui.more);
          else if(item.act==='first_item')runCommand('goto',{position:1});
          else if(item.act==='last_item')runCommand('goto',{position:(S.run&&S.run.view.position&&S.run.view.position.of)||1});
          else if(item.act==='scene_only')playSceneOnly();
          else if(!seekTo('home'))browseScene(0,0);
        }});
      ui.layer.appendChild(menu);
      S.menu={node:menu,buttons,returnFocus:ui.more,id:null,onClose:()=>ui.more.setAttribute('aria-expanded','false')};
      ui.more.setAttribute('aria-expanded','true');
      menu.addEventListener('keydown',event=>onMenuKey(event));
      menu.addEventListener('mousedown',event=>event.stopPropagation());
      if(buttons[0])buttons[0].focus({preventScroll:true});
    }
    /* The keyboard sheet (Slice 10, § 6 #6 and #20): `?` anywhere in Variants, or « ⋯ › Raccourcis clavier ». One modal dialog of the
       explorer's layer (Tab stays in it, Échap closes it and gives the focus back), read from the one key map (`Media.shortcutRows`) in the
       mode on screen, and the tree keys (`Core.TREE_SHORTCUTS`). It acts on nothing: it only says. */
    function openShortcuts(returnFocus){
      if(!S.open)return;
      if(S.dialog&&S.dialog.kind==='shortcuts'){cancelDialog();return}
      if(S.dialog)return;
      const dlg=openDialog({kind:'shortcuts',titleId:'jvxDialogTitle',returnFocus:returnFocus||doc.activeElement});
      dlg.box.setAttribute('data-kind','shortcuts');
      const h=el('h2','','Raccourcis clavier');h.id='jvxDialogTitle';
      dlg.box.appendChild(h);
      dlg.box.appendChild(el('p','',S.run?'Une présentation est en cours : la partition mène, la vidéo suit.':'Sur la vidéo, la barre de lecture et les vignettes de scènes.'));
      const table=(caption,rows)=>{
        const t=el('table','jvx-keys');t.appendChild(el('caption','',caption));
        for(const row of rows){
          const tr=el('tr');const th=el('th');th.setAttribute('scope','row');
          row.keys.forEach((k,i)=>{if(i)th.appendChild(doc.createTextNode(' '));th.appendChild(el('kbd','',k))});
          tr.appendChild(th);tr.appendChild(el('td','',row.does));t.appendChild(tr);
        }
        return t;
      };
      const body=el('div','jvx-keys-body');
      body.appendChild(table(S.run?'Présentation':'Vidéo',Media.shortcutRows(S.run?'run':'video')));
      if(!S.run)body.appendChild(table('Barre de position (sélectionnée)',[{keys:['←','→'],does:'Une seconde'},{keys:['Page précédente','Page suivante'],does:'Début de la scène'},
        {keys:['Début','Fin'],does:'Début, fin de la vidéo'}]));
      body.appendChild(table(S.run?'Arbre et versions (à l’arrêt de la présentation)':'Arbre et versions',Core.TREE_SHORTCUTS));
      dlg.box.appendChild(body);
      const actions=el('div','jvx-dialog-actions');
      const done=dialogButton('Fermer',()=>cancelDialog(),{primary:true});
      actions.appendChild(done);dlg.box.appendChild(actions);
      done.focus({preventScroll:true});
      log('shortcuts_opened',{mode:S.run?'run':'video'});
    }
    function clockText(frames,fps){
      const s=Math.max(0,Math.round(frames/fps));
      return `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`;
    }
    /* The transport, the wait pill and the failure veil follow the sequencer. Every position shown here is `f`; without a map, none (§ 4.8). */
    function renderPlayback(){
      if(!ui.playAll)return;
      if(S.run){renderRun();return}
      renderPresent();
      const v=seq?seq.view():{phase:'idle',retryable:true};
      const running=v.phase==='playing'||v.phase==='waiting';
      chrome.sync();   // fullscreen: the transport stays while paused, hides itself while the video plays
      const label=running?'Pause':v.phase==='ended'?'Rejouer':v.phase==='loading'&&!v.total_frames?'Préparation…':'Lire';
      ui.playAllLabel.textContent=label;
      clear(ui.playAllIcon);ui.playAllIcon.appendChild(icon(running?'pause':v.phase==='ended'?'restore':'play'));
      ui.playAll.setAttribute('aria-pressed',running?'true':'false');
      ui.playAll.setAttribute('aria-label',label==='Préparation…'?'Préparation de la lecture':label);
      const ready=S.preview.status==='ready'&&S.preview.scenes.length>0;
      const blocked=!ready?"Aucune scène à lire : attendez l'aperçu.":v.phase==='unavailable'&&!v.retryable?unavailableText(v):null;
      ui.playAll.setAttribute('aria-disabled',blocked?'true':'false');
      ui.playAll.title=blocked||'Lire la vidéo en continu, de la position à la fin (Espace)';
      const mapped=!!(seq&&seq.active()&&v.total_frames);
      const index=mapped?v.scene_index:Math.max(-1,S.preview.scenes.findIndex(s=>s.id===S.preview.sceneId));
      const count=S.preview.scenes.length;
      ui.prevScene.setAttribute('aria-disabled',ready&&(mapped||index>0)?'false':'true');
      const last=index>=count-1;
      ui.nextScene.setAttribute('aria-disabled',ready&&!last?'false':'true');
      ui.nextScene.title=ready&&last?'Dernière scène':'Début de la scène suivante (→, Page suivante)';
      renderScrub(v,mapped);
      if(v.phase==='waiting'&&v.waiting_visible){
        ui.wait.hidden=false;
        ui.waitText.textContent=`Chargement de la scène ${v.scene_index+1} sur ${v.scene_count}`;
        ui.waitCount.textContent=`· ${Math.max(0,Math.round(v.waiting_ms/1000))} s`;
      }else if(!ui.wait.hidden){ui.wait.hidden=true;ui.waitText.textContent='';ui.waitCount.textContent=''}
      if(v.phase==='failed'&&v.error&&S.preview.status==='ready'&&!cmp.isActive()){
        ui.veil.hidden=false;ui.veil.setAttribute('data-tone','danger');
        ui.veilTitle.textContent=Number.isInteger(v.error.scene_index)?`Scène ${v.error.scene_index+1} : lecture impossible`:'Lecture impossible';
        ui.veilText.textContent=playbackError(v.error);
        ui.veilAction.hidden=false;ui.veilAction.textContent='Réessayer';ui.veilRun=()=>{seq.retry()};
        const hasNext=Number.isInteger(v.error.scene_index)&&v.error.scene_index+1<v.scene_count;
        ui.veilAction2.hidden=!hasNext;ui.veilAction2.textContent='Scène suivante';ui.veilRun2=hasNext?()=>{seq.seekScene(v.error.scene_index+1);seq.play()}:null;
      }else if(ui.veil.getAttribute('data-playback')==='1'&&v.phase!=='failed'){ui.veil.removeAttribute('data-playback');renderStage()}
      if(v.phase==='failed')ui.veil.setAttribute('data-playback','1');
    }
    function renderScrub(v,mapped){
      if(!mapped){
        attrs(ui.scrub,{'aria-disabled':'true',title:seq&&v.phase==='unavailable'?unavailableText(v):NO_POSITION});
        for(const name of ['aria-valuenow','aria-valuemax','aria-valuetext'])ui.scrub.removeAttribute(name);
        ui.time.textContent='';ui.scrubKey=null;clear(ui.scrubTicks);
        return;
      }
      const last=Math.max(1,v.total_frames-1),at=`${clockText(v.frame,v.fps)} sur ${clockText(v.total_frames,v.fps)}`;
      attrs(ui.scrub,{'aria-disabled':'false',title:'Position dans la vidéo (← → une seconde, Page précédente / suivante une scène, Début / Fin)',
        'aria-valuemax':String(v.total_frames-1),'aria-valuenow':String(v.frame),'aria-valuetext':`Scène ${v.scene_index+1} sur ${v.scene_count}, ${at}`});
      const pct=`${(v.frame/last*100).toFixed(3)}%`;
      ui.scrubFill.style.width=pct;ui.scrubThumb.style.left=pct;
      ui.time.textContent=`${clockText(v.frame,v.fps)} / ${clockText(v.total_frames,v.fps)}`;
      /* One tick per scene boundary, redrawn only when the map changes. */
      const key=`${v.total_frames}:${v.starts.join(',')}`;
      if(ui.scrubKey!==key){
        ui.scrubKey=key;clear(ui.scrubTicks);
        for(const start of v.starts.slice(1)){const tick=el('span','jvx-scrub-tick');tick.style.left=`${(start/last*100).toFixed(3)}%`;ui.scrubTicks.appendChild(tick)}
      }
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
      if(cmp.isActive())return;      /* l'aperçu simple est remplacé par la comparaison : rien à lire pour lui */
      if(previewTimer)cancelLater(previewTimer);
      const node=nodeOf(S.selectedId);
      const p=S.preview;
      p.generation+=1;
      if(!node){p.variantId=null;p.status='idle';unmountPreview();renderStage();renderStrip();return}
      if(p.variantId!==node.variant_id){
        if(seq)seq.reset('variant_changed');   // another variant: playback stops, its map (another key) is dropped (§ 4.10)
        p.doc=null;p.scenes=[];p.error=null;p.variantId=node.variant_id;
      }
      if(node.state==='archived'){p.status='archived';p.since=now();unmountPreview();renderStage();renderStrip();renderMeta();return}
      /* Relire une variante déjà à l'écran (après un renommage, un changement venu d'ailleurs) ne couvre pas l'aperçu d'un voile : l'ancien reste, le neuf le remplace. */
      const refreshing=p.status==='ready'&&p.scenes.length>0;
      if(!refreshing){p.status='loading';p.since=now();renderStage();renderStrip();startTicker()}
      const generation=p.generation,variantId=node.variant_id;
      const arm=()=>{
        previewTimer=later(()=>{
          previewTimer=null;
          /* Pas de lecture pendant qu'une écriture est en vol (elle peut archiver cette variante) : `after()` replanifiera une lecture sur le graphe relu. */
          if((S.writing||(S.busy&&S.busy.op&&S.busy.op!=='plan'))&&generation===p.generation){arm();return}
          loadPreview(variantId,generation);
        },PREVIEW_SETTLE_MS);
      };
      arm();
      loadArt(variantId);
    }
    async function loadPreview(variantId,generation){
      const p=S.preview;
      /* Jamais une lecture pour une variante absente du graphe le plus récent, ou archivée : le graphe affiché est celui qui fait foi. */
      const known=nodeOf(variantId);
      if(!known||known.state!=='live'){log('preview_skipped',{variant_id:variantId,why:known?'archived':'unknown'});return}
      stats.previews+=1;
      try{
        const variantDoc=await call('GET',variantPath(variantId),undefined,{timeoutMs:READ_TIMEOUT_MS});
        if(generation!==p.generation||!S.open)return;
        /* A new revision of the variant on screen once the map exists (hot reload, an agent edit): the sequencer keeps (scene, frame) and the
           play state across it (§ 4.9, PX-19); the new pin swaps in place below (`renderStage`). */
        const revised=!!(seq&&seq.active()&&p.doc&&p.doc.revision!==variantDoc.revision);
        p.doc=variantDoc;p.scenes=scenesOf(variantDoc);
        if(!p.scenes.some(s=>s.id===p.sceneId))p.sceneId=p.scenes[0]?p.scenes[0].id:null;
        p.status=p.scenes.length?'ready':'empty';p.error=null;
        log('preview_loaded',{variant_id:variantId,scenes:p.scenes.length,variant_revision:variantDoc.revision});
        renderStage();renderStrip();renderMeta();
        if(revised)seq.revise().catch(error=>log('playback_revise_failed',{error:describe(error)},'error'));
        else preparePlayback();
        return;
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
      if(cmp.isActive())return;      /* la comparaison tient la place de l'aperçu : aucun cadre n'est monté dans l'aperçu simple */
      if(S.run){renderRunStage();return}   /* Slice 09: the stage shows the run's surface, never the preview frame */
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
            host.mount(ui.slot,{object_id:PREVIEW_OBJECT_ID,scene_id:scene.id,prefab:{id:scene.prefab.id,version:scene.prefab.version},title:scene.title,props:scene.props,data:scene.data});
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
      ui.stage.setAttribute('aria-label',scene?`Aperçu, scène ${index+1} sur ${p.scenes.length} : ${scene.title}`:'Aperçu');
      renderPlayback();
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
      const index=p.scenes.findIndex(s=>s.id===sceneId);
      if(index<0)return;
      /* § 5 table: during a presentation a thumbnail is `goto {scene_id}` through Core; the Player follows. */
      if(S.run){runCommand('goto',{scene_id:sceneId});return}
      /* Once the video has been played, a scene chosen by the user is a seek of the one clock: its start, play state kept (§ 4.4, § 4.5);
         the thumbnail of the current scene restarts it. The sequencer then shows the scene (`showScene`). */
      if(seq&&seq.active()){if(!seq.seekScene(index))return;announceScene()}
      else{
        if(p.sceneId===sceneId)return;
        showScene(sceneId);
        const scene=currentScene();
        if(scene)announce(`Scène ${p.scenes.indexOf(scene)+1} sur ${p.scenes.length} : ${scene.title}`);
      }
      if(options&&options.focus){const b=ui.strip.querySelector(`[data-scene="${sceneId}"]`);if(b)b.focus({preventScroll:true})}
    }
    /* The scene on screen becomes `sceneId` (the user's choice, or the next scene of the continuous play: never announced, § 4.16). */
    function showScene(sceneId){
      const p=S.preview;
      if(!p.scenes.some(s=>s.id===sceneId))return;
      p.sceneId=sceneId;
      renderStage();renderStrip();
    }
    function browseScene(delta,absolute){
      const p=S.preview;
      if(p.status!=='ready'||!p.scenes.length)return false;
      const index=Math.max(0,p.scenes.findIndex(s=>s.id===(S.run?runSceneId():p.sceneId)));
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
      else if(['fullscreen','sound'].includes(Media.keyAction(key)))handled=transportKey(key,event);
      if(handled){event.preventDefault();event.stopPropagation()}
    }

    /* -------------------------------------------------------------- sélection, pliage, clavier de l'arbre */
    function selectVariant(id,options){
      const node=nodeOf(id);
      if(!node)return;
      if(S.run&&id!==S.run.view.variant_id){say('info',RUN_BUSY);return}
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
    let typed={text:'',at:0};
    function onTreeKey(kind,event,id,rows,index){
      const tree=kind==='live'?ui.liveTree:ui.archiveTree;
      /* Type-ahead par numéro : « 4 » puis « 2 » (en moins de 700 ms) va au #42 ; le numéro est immuable, donc la cible aussi. */
      if(/^[0-9]$/.test(event.key)&&!event.ctrlKey&&!event.altKey&&!event.metaKey){
        typed=now()-typed.at>TYPEAHEAD_MS?{text:event.key,at:now()}:{text:typed.text+event.key,at:now()};
        const target=Core.typeAhead(rows,index,typed.text);
        event.preventDefault();event.stopPropagation();
        if(target){S.focus[kind]=target;tree.focus(target);announce(`Variante ${nodeOf(target).variant_number}`)}
        else announce(`Aucune variante ne commence par ${typed.text}`);
        return;
      }
      if((event.key==='c'||event.key==='C')&&!event.ctrlKey&&!event.altKey&&!event.metaKey){
        event.preventDefault();event.stopPropagation();
        if(event.shiftKey){cmp.start({})}
        else{cmp.toggleMark(rows[index]&&rows[index].id||S.focus[kind]);const t=kind==='live'?ui.liveTree:ui.archiveTree;t.focus(S.focus[kind])}
        return;
      }
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
    function begin(label,op){S.busy={label,op:op||null,at:now()};if(op&&op!=='plan')S.writing=true;renderHeader();syncActionsBusy();startTicker()}
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
      /* Aucune lecture d'aperçu armée avant une écriture ne doit partir dans l'intervalle écriture / relecture : `after()` replanifie. */
      if(op!=='plan'&&previewTimer){cancelLater(previewTimer);previewTimer=null}
      begin(label,op);
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
        /* La boîte d'archivage dit déjà « la liste a changé » : le message flottant la répéterait, coupé sous le voile. */
        if(!(S.dialog&&S.dialog.kind==='archive'&&info.kind==='stale'))say(info.kind==='failed'?'failed':info.kind==='stale'?'stale':'refused',info.text);
        if(info.kind==='failed'&&!S.open)tell('Variantes : '+label,info.text,'bad');
        if(info.kind==='stale'||info.code==='presentation_studio_unknown_variant'){
          try{await loadGraph({});renderAll();schedulePreview()}catch(reload){log('reload_after_stale_failed',{code:reload.code},'warn')}
        }
        settle();
        return {error:info};
      }finally{endBusy()}
    }
    /* `S.writing` : de la requête d'écriture jusqu'à la relecture du graphe (et non jusqu'à la fin de l'occupation) : aucune lecture d'aperçu ne part dans cet intervalle. */
    function settle(){S.writing=false}
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
      }finally{settle()}
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
      if(act==='compare_mark'){cmp.toggleMark(id);renderActions();return}
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
      if(node.state==='live')items.push({act:'compare_mark',label:cmp.markSet().has(node.variant_id)?'Retirer de la comparaison':'Marquer pour comparer',icon:'compare',key:'C'});
      return items;
    }
    function closeMenu(restore){
      const menu=S.menu;
      if(!menu)return;
      S.menu=null;
      menu.node.remove();
      if(menu.onClose)menu.onClose();
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

    /* -------------------------------------------------------------- une présentation dans Variantes (native-studio-playback-fix Slice 09) */
    const RUN_BUSY='Présentation en cours : l\'arbre et les actions reviennent à l\'arrêt (« Arrêter »).';
    const RUN_SCRUB='La partition mène la présentation : la position suit les éléments (⏮ ⏭, ← →), elle ne se fait pas glisser.';
    const runAdapter=Run.createRunAdapter({host:()=>ensureHost(),slot:()=>ui.slot,overlaySlot:()=>ui.overlay,frames:Frames(),
      now,setInterval:every,clearInterval:stopEvery,
      onSegment:(report)=>{if(typeof win.dispatchEvent==='function'&&typeof win.CustomEvent==='function'){
        try{win.dispatchEvent(new win.CustomEvent('jarvis:studio-segment',{detail:report}))}catch(error){log('run_segment_failed',{error:describe(error)},'warn')}}},
      log:(key,data,level)=>log(key,data,level)});
    function runSceneId(){
      if(!S.run)return null;
      const surface=runAdapter.surface();
      return surface&&surface.scene_id||S.run.view.scene&&S.run.view.scene.scene_id||null;
    }
    function runElapsed(){
      const v=S.run.view,el=v.elapsed||{};
      return (el.item_ms||0)+(v.phase==='playing'||v.phase==='resuming'?Math.max(0,now()-S.run.viewAt):0);
    }
    function runModel(){
      if(!S.run)return {active:false};
      const state=player()&&typeof player().state==='function'?player().state():{};
      return Run.presenterModel(S.run.view,runElapsed(),{busy:S.run.busy,linkLostMs:state.linkLostSince?now()-state.linkLostSince:0});
    }
    function setRunInert(on){
      for(const node of [ui.treePane,ui.actions,ui.upgrades])if(node)node.inert=!!on;
      if(ui.runChip)ui.runChip.hidden=!on;
      /* Slice 10: inert is also SEEN — the tree, the actions and the upgrade notice are dimmed (`data-run` on the host) and the line
         under the actions says why; the actions stay on screen (never removed), each `aria-disabled` with the same reason. */
      if(ui.host){if(on)ui.host.setAttribute('data-run','');else ui.host.removeAttribute('data-run')}
      if(ui.runNote)ui.runNote.hidden=!on;
      /* Slice 09 rework: during a run the interaction-mode HUD (`data-keep-live="run"`) stays live and drawn above Variants (`jvx-run` on
         <html>, rank in the explorer's sheet): « Refusé par la voix » and the way out of PRESENTATION stay on screen. */
      const html=doc.documentElement;
      if(html&&html.classList)html.classList.toggle('jvx-run',!!on);
      if(S.open)applyInert();
    }
    /* The page under Variants is inert while it is open (a modal dialog), except what lives beside it: `data-keep-live="true"` (the
       presentations rail, its menu and dialogs) always, `data-keep-live="run"` (the interaction-mode HUD) during a run. A keep-live element
       nested in a container keeps it out of the inert set; its siblings are made inert one level down instead. */
    function keepsLive(n){
      const v=n&&typeof n.getAttribute==='function'?n.getAttribute('data-keep-live'):null;
      return v==='true'||v===''||(v==='run'&&!!S.run);
    }
    function holdsLive(n){
      if(!n||typeof n.querySelectorAll!=='function')return false;
      return Array.from(n.querySelectorAll('[data-keep-live]')).some(keepsLive);
    }
    function inertTargets(parent,out){
      for(const n of Array.from(parent.children||[])){
        if(n===ui.host||String(n.tagName).toUpperCase()==='SCRIPT'||(n.classList&&n.classList.contains('toasts'))||keepsLive(n))continue;
        if(holdsLive(n))inertTargets(n,out);
        else if(!n.inert||inerted.includes(n))out.push(n);
      }
      return out;
    }
    function applyInert(){
      const next=inertTargets(doc.body,[]);
      for(const n of inerted)if(!next.includes(n))n.inert=false;
      for(const n of next)n.inert=true;
      inerted=next;
    }
    function releaseInert(){
      for(const n of inerted)n.inert=false;
      inerted=[];
      const html=doc.documentElement;
      if(html&&html.classList)html.classList.remove('jvx-run');
    }
    /* A run of this deck: the stage shows its surface (paused on frame 0 until Core orders it), the tree and actions become inert. */
    function enterRun(view){
      if(!Run.isRun(view))return;
      if(cmp.isActive())cmp.close({});
      closeMenu(false);
      if(seq)seq.reset('run');   // continuous video stops: one Player, the run's
      unmountPreview();
      if(view.variant_id&&nodeOf(view.variant_id)&&S.selectedId!==view.variant_id)selectVariant(view.variant_id,{});
      S.run={runId:view.run_id,view,viewAt:now(),busy:false,map:null};
      setRunInert(true);
      const p=player(),surface=p&&typeof p.surface==='function'?p.surface():null;
      if(surface&&surface.run_id===view.run_id)runAdapter.applySurface(surface);
      runAdapter.setUnresolved(view.timeline_unresolved||null);
      if(runTimeline)runAdapter.applyTimeline(runTimeline);
      loadRunMap(view);
      if(!runTicker)runTicker=every(()=>{if(S.run)renderRun()},1000);
      renderAll();
      const m=runModel();
      announce(`Présentation en cours dans Variantes : ${m.role}. ${m.where}.`);
      log('run_hosted',{run_id:view.run_id,role:view.role||null});
    }
    function updateRun(view){
      S.run.view=view;S.run.viewAt=now();
      runAdapter.setUnresolved(view.timeline_unresolved||null);
      renderRun();renderStrip();renderRunStage();
    }
    function leaveRun(view){
      const ended=view&&view.last_run||null;
      runAdapter.clear();
      S.run=null;setRunInert(false);
      if(runTicker){stopEvery(runTicker);runTicker=null}
      renderAll();schedulePreview();
      const problems=(ended&&ended.problems||[]).map(code=>(root.JarvisStudioPlayerCore&&root.JarvisStudioPlayerCore.PROBLEMS[code])||`Problème : ${code}`);
      if(problems.length)say('failed',`Présentation arrêtée. ${problems.join(' ')}`);
      else say('info',ended&&ended.reason==='mode_changed_by_user'?'Présentation arrêtée : mode changé par vous.':ended&&ended.reason==='crashed'?
        'Présentation interrompue par une erreur de Core.':'Présentation terminée : la vidéo est de nouveau à vous.');
      log('run_left',{reason:ended&&ended.reason||null});
    }
    /* Core's view, every time the client adopts one: open Variants for a NEW run (once, windowed, never fullscreen), follow it, leave it. */
    function onRunView(event){
      const view=event&&event.detail&&event.detail.view;
      if(!view)return;
      if(pauseOnReturn&&(!Run.isRun(view)||view.run_id!==pauseOnReturn||view.phase==='paused'||view.phase==='ended'))pauseOnReturn=null;
      if(Run.isRun(view)){
        if(pauseOnReturn&&!S.open&&(view.phase==='resuming'||view.phase==='playing')){
          pauseOnReturn=null;
          const p=player();
          if(p&&typeof p.command==='function')p.command('pause',{}).then(r=>log('run_paused_on_return',{status:r&&r.status||null}),
            error=>log('run_pause_on_return_failed',{error:describe(error)},'error'));
          return;
        }
        if(!S.open||S.pid!==view.presentation_id){
          if(runsOpened.has(view.run_id))return;
          runsOpened.add(view.run_id);
          open({presentation_id:view.presentation_id,variant_id:view.variant_id||undefined,fullscreen:false,via:'run'})
            .then(result=>{if(result&&result.state==='refused')log('run_open_refused',{code:result.code},'warn')})
            .catch(error=>log('run_open_failed',{error:describe(error)},'error'));
          return;
        }
        runsOpened.add(view.run_id);
        if(pauseOnReturn===view.run_id)pauseOnReturn=null;   // Variants shows the run again: the user sees what plays
        if(!S.run||S.run.runId!==view.run_id)enterRun(view);else updateRun(view);
        return;
      }
      if(S.run)leaveRun(view);
    }
    function onRunSurface(event){
      const surface=event&&event.detail?event.detail.surface:null;
      if(!S.run){return}
      if(surface&&surface.run_id!==S.run.runId)return;
      runAdapter.applySurface(surface);
      renderRunStage();
    }
    function onRunTimeline(event){
      runTimeline=event&&event.detail||null;
      if(S.run&&runTimeline)runAdapter.applyTimeline(runTimeline);
    }
    if(typeof win.addEventListener==='function'){
      win.addEventListener('jarvis:studio-view',onRunView);
      win.addEventListener('jarvis:studio-surface',onRunSurface);
      win.addEventListener('jarvis:studio-timeline',onRunTimeline);
    }
    /* A command of the presentation, through the page's playback client (the voice's own routes): refusals and failures said here. */
    async function runCommand(verb,body){
      const p=player();
      if(!p||typeof p.command!=='function'){say('failed','Le client de lecture n\'est pas chargé dans cette page.');return null}
      if(S.run){S.run.busy=true;renderRun()}
      let result=null;
      try{result=await p.command(verb,body||{})}
      catch(error){say('failed',`${verb} impossible : ${describe(error)}`);log('run_command_failed',{verb,error:describe(error)},'error');return null}
      finally{if(S.run){S.run.busy=false;renderRun()}}
      const P=root.JarvisStudioPlayerCore||{REFUSALS:{}};
      if(result&&result.status==='refused')say('info',P.REFUSALS[result.reason]||result.message||'Commande refusée.');
      else if(result&&result.status==='stage_failed')say('failed',`La scène n'a pas suivi : ${result.message||result.reason||'cause inconnue'}`);
      else if(result&&result.status==='failed')say('failed',result.message);
      else if(result&&result.status==='dropped')say('info','Trop de commandes à la fois : un instant.');
      return result;
    }
    /* The surface's frame posts its events like its Board window did (`/api/prefabs/events`): a `state` keeps the clicks across a hot reload. */
    async function postFrameEvent(event){
      let answer;
      try{answer=await call('POST','/api/prefabs/events',event,{timeoutMs:15000})}
      catch(error){
        log('run_frame_event_failed',{event:event&&event.event,code:error.code},'warn');
        throw Object.assign(new Error(describe(error)),{code:error.code&&/^[a-z][a-z0-9_]{0,39}$/.test(error.code)?error.code:'unreachable'});
      }
      if(answer&&answer.outcome==='refused')say('info',`Action de la scène refusée : ${cleanLine(answer.detail||answer.reason||'',160)}`);
      return answer;
    }
    /* What the Player observed for the run's frame (mounted, failed): the hot reload confirms a new source or rolls it back with it. */
    function reportRunOutcome(info){
      const reload=root.JarvisStudioReload&&root.JarvisStudioReload.instance;
      if(!reload||typeof reload.hostOutcome!=='function')return;
      reload.hostOutcome(info).catch(error=>log('run_outcome_failed',{object_id:info&&info.object_id,error:describe(error)},'error'));
    }
    /* The read-only position (§ 5): the composition frame of the run's Player, from the variant's map; none until the map is read. */
    async function loadRunMap(view){
      const C=Clock();
      if(!C||!view.variant_id)return;
      try{
        const answer=await call('GET',variantPath(view.variant_id,'/composition-clock'),undefined,{timeoutMs:READ_TIMEOUT_MS});
        if(!S.run||S.run.runId!==view.run_id||!answer||!answer.clock)return;
        S.run.map=C.fromWire(answer.clock,{key:answer.key});
        renderRun();
      }catch(error){log('run_map_unavailable',{code:error.code||null,error:describe(error)},'info')}
    }
    function runPosition(){
      const map=S.run&&S.run.map,surface=runAdapter.surface();
      if(!map||!surface||!previewHost||typeof previewHost.clock!=='function')return null;
      const index=map.scenes.findIndex(sc=>sc.scene_id===surface.scene_id);
      const clock=previewHost.clock(surface.surface_id);
      if(index<0||!clock||!Number.isInteger(clock.frame))return null;
      let frame;
      try{frame=map.frameOf(index,clock.frame)}catch(_error){return null}
      return {frame,fps:map.fps,total_frames:map.total_frames,scene_index:index,scene_count:map.scenes.length,starts:map.scenes.map(sc=>sc.start)};
    }
    function renderRunPosition(){if(S.run)renderRunScrub()}
    function renderRunScrub(){
      const v=runPosition();
      ui.scrubKey=null;clear(ui.scrubTicks);
      if(!v){
        attrs(ui.scrub,{'aria-disabled':'true',title:RUN_SCRUB});
        for(const name of ['aria-valuenow','aria-valuemax','aria-valuetext'])ui.scrub.removeAttribute(name);
        ui.time.textContent='';
        return;
      }
      const last=Math.max(1,v.total_frames-1),at=`${clockText(v.frame,v.fps)} sur ${clockText(v.total_frames,v.fps)}`;
      attrs(ui.scrub,{'aria-disabled':'true',title:RUN_SCRUB,'aria-valuemax':String(v.total_frames-1),'aria-valuenow':String(v.frame),
        'aria-valuetext':`Scène ${v.scene_index+1} sur ${v.scene_count}, ${at} (la partition mène)`});
      const pct=`${(v.frame/last*100).toFixed(3)}%`;
      ui.scrubFill.style.width=pct;ui.scrubThumb.style.left=pct;
      ui.time.textContent=`${clockText(v.frame,v.fps)} / ${clockText(v.total_frames,v.fps)}`;
    }
    /* The transport during a presentation: ▶ is the run's pause / resume, ⏮ ⏭ the previous / next item, the slider read-only. */
    function renderRun(){
      if(!S.run||!ui.playAll)return;
      const m=runModel();
      if(!m.active)return;
      ui.stopRun.hidden=false;ui.present.hidden=true;
      ui.sceneCount.hidden=true;ui.sceneLine.hidden=true;   // the presenter strip says the scene and the item (Slice 02 inventory § 2)
      chrome.sync();
      const pausing=m.pause.command==='pause';
      ui.playAllLabel.textContent=m.pause.label;
      clear(ui.playAllIcon);ui.playAllIcon.appendChild(icon(pausing?'pause':'play'));
      attrs(ui.playAll,{'aria-pressed':pausing?'true':'false','aria-label':m.pause.label,'aria-disabled':m.pause.disabled?'true':'false',
        title:pausing?'Mettre la présentation en pause (Espace)':'Reprendre la présentation (Espace)'});
      attrs(ui.prevScene,{'aria-label':'Élément précédent','aria-disabled':m.previous.disabled?'true':'false',title:'Élément précédent (←, Page précédente)'});
      attrs(ui.nextScene,{'aria-label':'Élément suivant','aria-disabled':m.nextItem.disabled?'true':'false',title:'Élément suivant (→, Page suivante)'});
      renderRunScrub();
      ui.wait.hidden=true;
      if(ui.veil.getAttribute('data-playback')==='1'){ui.veil.removeAttribute('data-playback');ui.veil.hidden=true}
      renderPresenterStrip(m);
    }
    function renderRunStage(){
      if(!S.run)return;
      const v=S.run.view,scene=v.scene||{},surface=runAdapter.surface();
      ui.veil.hidden=!!surface;
      if(!surface){ui.veil.setAttribute('data-tone','');ui.veilTitle.textContent='Préparation de la présentation…';ui.veilText.textContent=v.scene&&v.scene.title?cleanLine(v.scene.title,80):'';ui.veilAction.hidden=true;ui.veilAction2.hidden=true}
      ui.overlay.hidden=!(surface&&(surface.overlays||[]).some(o=>o.visible));
      ui.sceneTitle.textContent=cleanLine(scene.title||'',80);
      ui.sceneRole.hidden=!scene.section;ui.sceneRole.textContent=scene.section||'';
      ui.sceneBadge.hidden=true;
      ui.sceneCount.textContent=scene.number?`Scène ${scene.number} sur ${scene.of}`:'';
      ui.stage.setAttribute('aria-label',scene.number?`Présentation, scène ${scene.number} sur ${scene.of} : ${cleanLine(scene.title||'',80)}`:'Présentation');
      renderRun();
    }
    function buildPresenter(){
      const box=el('section','jvx-presenter');
      attrs(box,{'aria-label':'Présentation en cours'});box.hidden=true;
      const head=el('div','jvx-presenter-head');
      ui.pRole=el('strong','jvx-presenter-role');ui.pPhase=el('span','jvx-chip');ui.pVoice=el('span','jvx-presenter-voice');ui.pVoice.hidden=true;
      attrs(ui.pVoice,{role:'status','aria-live':'polite'});
      ui.pClock=el('span','jvx-presenter-clock');
      for(const n of [ui.pRole,ui.pPhase,ui.pVoice,ui.pClock])head.appendChild(n);
      ui.pWhere=el('div','jvx-presenter-where');attrs(ui.pWhere,{role:'status','aria-live':'polite'});
      ui.pItem=el('p','jvx-presenter-line jvx-bidi');ui.pItem.setAttribute('dir','auto');
      ui.pNext=el('p','jvx-presenter-line jvx-bidi');ui.pNext.setAttribute('dir','auto');
      ui.pSeq=el('div','jvx-presenter-seq');ui.pSeq.hidden=true;
      ui.pSeqText=el('span');ui.pSeqBar=el('div','jvx-presenter-seqbar');
      attrs(ui.pSeqBar,{role:'progressbar','aria-label':'Avancement de la séquence verrouillée','aria-valuemin':'0','aria-valuemax':'100'});
      ui.pSeqFill=el('span');ui.pSeqBar.appendChild(ui.pSeqFill);ui.pSeq.appendChild(ui.pSeqText);ui.pSeq.appendChild(ui.pSeqBar);
      ui.pNote=el('p','jvx-presenter-note');ui.pNote.setAttribute('role','alert');
      const actions=el('div','jvx-presenter-actions');
      ui.pSkip=button('Sortir de la séquence','jvx-btn',()=>{runCommand('skip_sequence')},{attrs:{title:'Votre issue de secours, toujours possible : quitte la séquence verrouillée et continue après elle (S)','aria-keyshortcuts':'S'}});
      /* One « Arrêter »: the transport's (it stays in the stage fullscreen, where this strip is not). */
      actions.appendChild(ui.pSkip);
      for(const n of [head,ui.pWhere,ui.pItem,ui.pSeq,ui.pNext,ui.pNote,actions])box.appendChild(n);
      return box;
    }
    function renderPresenterStrip(m){
      const box=ui.presenter;
      if(!box)return;
      box.hidden=!m.active;
      if(!m.active)return;
      box.setAttribute('data-kind',m.kind);box.setAttribute('data-phase',m.phaseKey);
      ui.pRole.textContent=m.role;ui.pPhase.textContent=m.phase;
      ui.pVoice.hidden=!m.voice;if(m.voice){ui.pVoice.setAttribute('data-state',m.voice.state);ui.pVoice.textContent=m.voice.text}
      ui.pClock.textContent=m.clock;ui.pClock.title=m.clockTitle;ui.pClock.setAttribute('data-over',m.over?'1':'0');
      ui.pWhere.textContent=`${m.where} · ${cleanLine(m.sceneTitle,80)}`;
      ui.pItem.textContent=cleanLine(m.item,160);ui.pNext.textContent=cleanLine(m.next,200);
      ui.pSeq.hidden=!m.sequence;
      if(m.sequence){ui.pSeqText.textContent=m.sequence.text;ui.pSeqBar.setAttribute('aria-valuenow',String(m.sequence.percent));
        ui.pSeqBar.setAttribute('aria-valuetext',m.sequence.text);ui.pSeqFill.style.width=m.sequence.percent+'%'}
      ui.pNote.textContent=m.lines.join(' ');
      ui.pSkip.hidden=!m.skip;
    }
    /* « Présenter ▾ » (§ 5, § 6 #21): a presenter run of the variant on screen, in Variants. Without a score it says why. */
    function presentBlocked(){
      if(S.preview.status!=='ready'||!S.preview.doc)return "Aucune variante prête à présenter : attendez l'aperçu.";
      if(!S.preview.doc.score_id)return 'Cette variante n\'a pas de partition : « Présenter » suit une partition.';
      return null;
    }
    function renderPresent(){
      if(!ui.present)return;
      ui.stopRun.hidden=true;ui.present.hidden=false;
      ui.sceneCount.hidden=false;ui.sceneLine.hidden=false;
      const blocked=presentBlocked();
      attrs(ui.present,{'aria-disabled':blocked?'true':'false',title:blocked||'Présenter cette variante : vous, Jarvis, ou une répétition (la partition mène)'});
      if(ui.presenter)ui.presenter.hidden=true;
    }
    function openPresentMenu(){
      if(S.dialog)return;
      if(S.menu){closeMenu(true);return}
      const blocked=presentBlocked();
      if(blocked){say('info',blocked);return}
      const box=ui.present.getBoundingClientRect?ui.present.getBoundingClientRect():{left:120,bottom:80};
      const items=[{act:'user_presenter',label:'Vous présentez',icon:'play'},{act:'jarvis_presenter',label:'Jarvis présente',icon:'play'},
        {act:'rehearsal',label:'Répétition',icon:'play'}];
      const {menu,buttons}=W.buildMenu(kit,{head:'Présenter',label:'Présenter la variante',items,anchor:{x:box.left,y:box.bottom+4},
        width:win.innerWidth||1280,height:win.innerHeight||720,onPick:item=>{closeMenu(true);startPresenting(item.act)}});
      ui.layer.appendChild(menu);
      S.menu={node:menu,buttons,returnFocus:ui.present,id:null,onClose:()=>ui.present.setAttribute('aria-expanded','false')};
      ui.present.setAttribute('aria-expanded','true');
      menu.addEventListener('keydown',event=>onMenuKey(event));
      menu.addEventListener('mousedown',event=>event.stopPropagation());
      if(buttons[0])buttons[0].focus({preventScroll:true});
    }
    async function startPresenting(role){
      const p=player();
      if(!p||typeof p.startRun!=='function'){say('failed','Le client de lecture n\'est pas chargé dans cette page.');return null}
      const video=seq?seq.view():null;
      const wasPlaying=!!video&&(video.phase==='playing'||video.phase==='waiting');
      const scene=currentScene();
      if(wasPlaying)seq.pause();   // § 5: « Présenter » while a video plays pauses it, the run starts at the current scene
      const result=await p.startRun(S.pid,role,{variant_id:S.preview.variantId});
      const P=root.JarvisStudioPlayerCore||{REFUSALS:{}};
      if(!result||result.status!=='applied'){
        say(result&&result.status==='refused'?'refused':'failed',`Présentation impossible : ${result&&(P.REFUSALS[result.reason]||result.message||result.reason)||'le client de lecture ne répond pas'}`);
        return result;
      }
      log('run_started_here',{role});
      if(wasPlaying&&scene&&S.preview.scenes.indexOf(scene)>0)await runCommand('goto',{scene_id:scene.id});
      return result;
    }

    /* -------------------------------------------------------------- clavier de l'hôte */
    /* Échap, imbriqué (§ 4.15) : le menu d'abord, puis la boîte, puis le plein écran de la scène, puis l'explorateur. Jamais une pause. En
       vrai plein écran le navigateur garde la première pression ; si la page la reçoit quand même pendant le plein écran de la scène, elle
       le quitte sans fermer, et la pression qui vient de le quitter (livrée en retard) ne ferme rien. Le plein écran de l'atelier ouvert
       par une demande (Slice 18) garde sa règle. */
    const FS_ESCAPE_GRACE_MS=400;
    function escapeKey(){
      if(S.menu){closeMenu(true);return}
      if(S.dialog){cancelDialog();return}
      if(ui.theater&&doc.fullscreenElement===ui.theater){toggleFullscreen();return}
      if(now()-S.fsLeftAt<FS_ESCAPE_GRACE_MS){log('escape_after_fullscreen_ignored',{});return}
      if(cmp.isActive()){cmp.close({});return}
      close({reason:'escape'});
    }
    function onHostKey(event){
      if(!S.open)return;
      if(event.key==='Escape'){
        event.preventDefault();event.stopPropagation();
        escapeKey();
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
      if(!typing&&!S.menu&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&event.key==='?'&&(!S.dialog||S.dialog.kind==='shortcuts')){
        event.preventDefault();event.stopPropagation();openShortcuts(doc.activeElement);return;
      }
      if(!typing&&!S.dialog&&!S.menu&&!event.ctrlKey&&!event.metaKey&&!event.altKey&&(event.key==='['||event.key===']')){
        if(S.run){event.preventDefault();event.stopPropagation();say('info',RUN_BUSY);return}
        if(stepVariant(event.key===']'?1:-1)){event.preventDefault();event.stopPropagation();return}
      }
      if(!typing&&!event.ctrlKey&&!event.metaKey&&event.key.length===1)event.stopPropagation();
    }

    /* Le focus peut se perdre (sortie du plein écran, élément retiré) : l'événement part alors du corps de la page, hors de l'hôte. Pendant qu'il est
       ouvert, Échap et Tab sont donc aussi lus en capture sur le document : la page derrière est inerte, il n'y a rien d'autre à qui les laisser. */
    function onDocKey(event){
      if(!S.open||ui.host.contains(event.target))return;
      /* Le rail des présentations (et son menu, ses boîtes) vit à côté du Studio : ses touches ne sont pas les nôtres. */
      if(event.target&&typeof event.target.closest==='function'&&event.target.closest('[data-keep-live]'))return;
      if(event.key==='Escape'){onHostKey(event);return}
      if(event.key==='Tab'){
        event.preventDefault();
        const target=S.selectedId&&nodeOf(S.selectedId)?(nodeOf(S.selectedId).state==='archived'?ui.archiveTree:ui.liveTree):ui.liveTree;
        if(!target.focus(S.selectedId||S.focus.live))ui.host.focus({preventScroll:true});
      }
    }

    /* -------------------------------------------------------------- plein écran */
    async function requestFullscreen(armS,objectId,display){
      const api=fullscreenApi();
      if(!api||typeof api.enter!=='function'){S.fs='unsupported';log('fullscreen_module_missing',{},'warn');return {state:'unsupported'}}
      try{
        const spec={object_id:objectId||OBJECT_ID,keys:'none',arm_s:armS||ARM_DEFAULT_S};
        if(display&&display!=='current')spec.display=display;
        const result=await api.enter(spec);
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
    /* « Plein écran » / `F` (§ 4.12, Slice 08): the STAGE goes fullscreen (the Player and its transport, never the tree, the metadata or
       the actions); when Variants is already fullscreen (the stage, or a workspace an opening asked for) it leaves it. `f` and the play state
       are untouched: the frames stay in the page, only their box grows. `other` (Maj+F, Maj+clic): another screen, only when the browser
       already granted the window-management permission (never asked here); otherwise the window's current screen, said (§ 4.13). */
    async function toggleFullscreen(opts){
      if(fullscreenNow()){
        try{await doc.exitFullscreen()}catch(error){say('failed',`Sortie du plein écran impossible : ${describe(error)}. Échap quitte toujours.`)}
        return;
      }
      const active=doc.activeElement;
      S.fsOpener=null;
      const display=opts&&opts.other?await otherScreen():'current';
      const result=await requestFullscreen(undefined,STAGE_OBJECT_ID,display);
      /* The opener is kept only for a fullscreen that really started: a refused or merely armed request leaves none behind (the stage
         fullscreen an armed prompt starts later gives the focus to « Plein écran »). */
      if(result.state==='entered'&&doc.fullscreenElement===ui.theater)S.fsOpener=active&&active!==doc.body?active:null;
      if(result.state==='refused')say('refused',`Plein écran refusé par le navigateur${result.reason?' : '+cleanLine(result.reason,120):''}. La vidéo reste dans la fenêtre.`);
      else if(result.state==='unsupported')say('refused',"Plein écran indisponible dans ce navigateur : la vidéo reste dans la fenêtre.");
      else if(result.state==='needs_gesture')say('info',"Cliquez « Passer en plein écran » dans l'invite en haut de la fenêtre.");
    }
    /* `display: 'other'` only when the browser already granted window management; never a permission prompt from here (§ 4.13). */
    async function otherScreen(){
      let state='unavailable';
      try{
        const perms=win.navigator&&win.navigator.permissions;
        if(perms&&typeof perms.query==='function')state=(await perms.query({name:'window-management'})).state;
      }catch(_error){state='unavailable' /* intentional: an unknown permission name is the same answer as a refusal */}
      if(state==='granted')return 'other';
      say('info',"Choisir l'écran demande l'autorisation « Gestion des fenêtres » du navigateur : déplacez la fenêtre de Jarvis sur l'écran voulu, puis « Plein écran ».");
      log('fullscreen_screen_choice_unavailable',{permission:state});
      return 'current';
    }
    function restoreFullscreenFocus(){
      const target=S.fsOpener;S.fsOpener=null;
      const usable=target&&target.isConnected!==false&&typeof target.focus==='function'&&ui.host.contains(target);
      const into=!usable?ui.fsButton:String(target.tagName||'').toUpperCase()==='IFRAME'?ui.stage:target;
      try{into.focus({preventScroll:true})}catch(error){log('fullscreen_focus_failed',{error:describe(error)},'warn')}
    }
    function onFullscreenChange(){
      if(!S.open)return;
      const fs=doc.fullscreenElement;
      const stage=!!fs&&fs===ui.theater;
      if(fullscreenNow()){
        S.fs='entered';S.fullscreenOwned=true;S.fsKind=stage?'stage':'workspace';
        if(stage){
          chrome.enter();
          try{ui.stage.focus({preventScroll:true})}catch(error){log('fullscreen_focus_failed',{error:describe(error)},'warn')}
          announce("Plein écran de la vidéo. Échap ou F le quitte ; la lecture continue.");
          log('fullscreen_stage_entered',{});
        }else announce("Plein écran. Échap quitte le plein écran ; Variantes reste ouvert.");
      }else if(S.fullscreenOwned){
        const wasStage=S.fsKind==='stage';
        S.fullscreenOwned=false;S.fs='exited';S.fsKind=null;
        chrome.exit();
        if(wasStage){S.fsLeftAt=now();restoreFullscreenFocus();log('fullscreen_stage_left',{})}
        say('info',"Plein écran quitté : Variantes reste ouvert dans la fenêtre. Échap le ferme.");
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
      /* Slice 09: Variants IS the surface of a presentation. During a run it opens on THAT presentation and shows the run; another one is refused. */
      const running=Run.isRun(playerView())?playerView():await coreRun();
      if(running&&running.presentation_id!==presentationId){
        const result=refusal('explorer_run_in_progress');
        tell('Variantes',result.reason,'warn');
        log('open_refused',{code:result.code});
        return result;
      }
      if(running)opts.variant_id=running.variant_id||opts.variant_id;
      if(S.open&&S.pid===presentationId){
        if(running&&(!S.run||S.run.runId!==running.run_id))enterRun(running);
        if(opts.variant_id&&nodeOf(opts.variant_id))selectVariant(opts.variant_id,{focus:true});
        if(opts.fullscreen!==false&&modeNow()==='windowed')await requestFullscreen(opts.arm_s);
        return {state:'opened',mode:modeNow(),fullscreen:fsNow(),presentation_id:S.pid,variant_id:S.selectedId};
      }
      if(S.open&&S.dialog){
        /* Un formulaire est ouvert : on ne le jette pas pour changer de présentation (le texte tapé serait perdu en silence). */
        const result=refusal('explorer_dialog_open');
        say('info',result.reason);
        log('open_refused',{code:result.code});
        return result;
      }
      if(S.open)close({reason:'switch',quiet:true});
      try{build()}catch(error){log('build_failed',{error:describe(error)},'error');return refusal('explorer_page_error',describe(error))}
      S.generation+=1;
      S.pid=presentationId;S.presentationTitle='';S.graph=null;S.live=buildForest([],'live');S.archived=buildForest([],'archived');S.selectedId=null;
      S.focus={live:null,archived:null};S.notice=null;S.dialog=null;S.menu=null;S.fs='not_requested';S.fsKind=null;S.fsOpener=null;S.fsLeftAt=-1e9;
      sound.reset();   // muted at every opening (§ 4.1, § 4.14)
      S.preview={variantId:null,status:'idle',doc:null,scenes:[],sceneId:null,error:null,since:now(),generation:S.preview.generation+1,mounted:null};
      S.art={variantId:null,state:'idle',doc:null};
      loadPrefs();
      S.opener=opts.opener||doc.activeElement;
      S.open=true;S.loading={label:'Chargement du graphe',at:now()};
      ui.host.hidden=false;
      applyInert();
      if(!ui.bound){doc.addEventListener('fullscreenchange',onFullscreenChange);ui.bound=true}
      doc.addEventListener('keydown',onDocKey,true);
      renderAll();renderSound();startTicker();
      ui.title.focus({preventScroll:true});
      pollTimer=every(pollGraph,GRAPH_POLL_MS);
      log('opened',{presentation_id:S.pid,via:opts.via||'api'});
      /* Dit à la page que le Studio est ouvert : le rail des présentations se range à gauche du Studio, la voix et le rail restent utilisables. */
      if(typeof win.dispatchEvent==='function'&&typeof win.CustomEvent==='function'){
        try{win.dispatchEvent(new win.CustomEvent('jarvis:studio-explorer-opened',{detail:{presentation_id:S.pid}}))}
        catch(error){log('opened_event_failed',{error:describe(error)},'warn')}
      }
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
      /* A presentation of this deck plays (or started while the graph was read): Variants shows it at once. */
      const now_running=Run.isRun(playerView())?playerView():running;
      if(now_running&&now_running.presentation_id===S.pid)enterRun(now_running);
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
      S.open=false;S.generation+=1;S.writing=false;
      for(const timer of [previewTimer,reportTimer,noticeTimer]){if(timer)cancelLater(timer)}
      previewTimer=reportTimer=noticeTimer=null;
      for(const t of [tickTimer,pollTimer,armTimer,runTicker])if(t)stopEvery(t);
      tickTimer=pollTimer=armTimer=runTicker=null;
      /* Slice 09: closing Variants during a presentation pauses it (no visible surface: the run must not go on unseen), said. */
      /* Slice 09 rework: every active phase. `playing` / `resuming` pause now; a `detour` (Core refuses `pause` there) pauses as soon as
         it returns (`pauseOnReturn`); `paused` / `ended` have nothing to stop. */
      if(S.run){
        const view=S.run.view;
        runAdapter.clear();S.run=null;setRunInert(false);
        const phase=view.phase;
        if((phase==='playing'||phase==='resuming')&&player()){
          player().command('pause',{}).then(r=>log('run_paused_on_close',{status:r&&r.status||null,phase}));
          tell('Présentation en pause',"Variantes est fermé : la présentation attend. Rouvrez Variantes (rail) pour la reprendre.",'warn');
        }else if(phase==='detour'&&player()){
          pauseOnReturn=view.run_id;
          log('run_pause_on_return',{run_id:view.run_id});
          tell('Présentation en pause au retour',"Variantes est fermé : la présentation se mettra en pause à la fin du détour. Rouvrez Variantes (rail) pour la reprendre.",'warn');
        }
      }
      cmp.shutdown();
      drag=null;   // a drag cut short by the close: no resume, and a reopened slider does not seek on hover
      if(seq)seq.reset('closed');
      unmountPreview();
      if(previewHost&&typeof previewHost.destroy==='function'){try{previewHost.destroy()}catch(_error){/* intentional: the host is dropped either way */}}
      previewHost=null;
      const api=fullscreenApi();
      chrome.exit();
      if(fullscreenNow()){try{doc.exitFullscreen()}catch(error){log('fullscreen_exit_failed',{error:describe(error)},'warn')}}
      else if(api&&typeof api.cancel==='function'&&api.state&&api.state().armed){try{api.cancel()}catch(error){log('fullscreen_cancel_failed',{error:describe(error)},'warn')}}
      S.fullscreenOwned=false;
      releaseInert();
      ui.host.hidden=true;
      const target=S.opener;
      S.opener=null;
      if(!opts.quiet){
        if(target&&target.isConnected!==false&&typeof target.focus==='function')target.focus({preventScroll:true});
        else if(doc.body&&typeof doc.body.focus==='function')doc.body.focus();
      }
      for(const fn of Array.from(selectionListeners)){try{fn([])}catch(error){log('selection_listener_failed',{error:describe(error)},'error')}}
      /* Dit à la page que l'explorateur est fermé : l'inspecteur, rangé par le plein écran, reprend sa place et le focus (le bouton qui avait ouvert est alors masqué). */
      if(!opts.quiet&&typeof win.dispatchEvent==='function'&&typeof win.CustomEvent==='function'){
        try{win.dispatchEvent(new win.CustomEvent('jarvis:studio-explorer-closed',{detail:{reason:opts.reason||'api'}}))}
        catch(error){log('closed_event_failed',{error:describe(error)},'warn')}
      }
      log('closed',{reason:opts.reason||'api'});
      reportSoon(true);
      return {state:'closed',was_open:true};
    }
    /* The playback client polls Core every 5 s at rest: a run started by voice an instant ago is not in its view yet. Core is asked. */
    async function coreRun(){
      try{
        const answer=await call('GET',PLAYBACK_ROUTE,undefined,{timeoutMs:4000});
        const state=answer&&answer.state;
        return Run.isRun(state)?state:null;
      }catch(error){
        log('playback_check_failed',{code:error.code,at:'open'},'warn');
        return null;   /* Core injoignable : le chargement du graphe, juste après, le dira avec ses mots */
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
        cmp.onPoll();
        upgrades.onPoll();
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
      try{await call('POST',STATE_ROUTE,body,{timeoutMs:4000,headers:{[PAGE_TOKEN_HEADER]:PAGE_TOKEN}})}
      catch(error){lastReported='';log('report_failed',{code:error.code},'warn')}
    }

    function onResize(){if(S.open){ui.liveTree.repaint();ui.archiveTree.repaint()}}
    if(typeof win.addEventListener==='function')win.addEventListener('resize',onResize);

    const api={
      open,close,isOpen:()=>S.open,refresh,
      selection:()=>S.open&&cmp.isActive()&&cmp.view()?cmp.view().variant_ids.slice():S.open&&S.selectedId?[S.selectedId]:[],
      compare:cmp,compose,upgrades,
      /* Lecture continue (Slice 05) et transport (Slice 06) : les mêmes portes que les boutons (épreuves navigateur ; la voix s'y branchera). */
      playback:Object.freeze({toggle:()=>togglePlayback(),play:()=>playback(s=>s.play()),playScene:()=>playSceneOnly(),
        pause:()=>seq?seq.pause():null,seek:(kind,value)=>seekTo(kind,value),view:()=>seq?seq.view():{phase:'idle'},stats:()=>seq?seq.stats():null,
        /* Slice 08: the sound and the stage fullscreen, as the page shows them (proofs; the voice will use the same doors). */
        sound:()=>sound.view(),chrome:()=>chrome.view(),fullscreen:()=>({mode:S.open?modeNow():null,kind:S.fsKind})}),
      /* Slice 09: the presentation Variants hosts (proofs; the run itself is Core's). */
      run:Object.freeze({view:()=>S.run?S.run.view:null,model:()=>runModel(),stats:()=>runAdapter.stats(),objectId:()=>runAdapter.objectId(),
        position:()=>S.run?runPosition():null,present:(role)=>startPresenting(role||'user_presenter')}),
      onSelectionChange(fn){selectionListeners.add(fn);return()=>selectionListeners.delete(fn)},
      select:(id)=>{if(S.open&&nodeOf(id))selectVariant(id,{focus:true})},
      runAction:(act,id)=>runAction(act,id||S.selectedId,{}),
      state:()=>({open:S.open,presentation_id:S.pid,selected:S.selectedId,active:S.graph&&S.graph.activeId,mode:S.open?modeNow():null,fullscreen:fsNow(),
        revision:S.graph&&S.graph.revision,live:S.live?S.live.size:0,archived:S.archived?S.archived.size:0,preview:{status:S.preview.status,scene:S.preview.sceneId,
        scenes:S.preview.scenes.length},busy:S.busy&&S.busy.label||null,dialog:S.dialog&&S.dialog.kind||null,menu:!!S.menu,notice:S.notice&&{kind:S.notice.kind,text:S.notice.text}||null,
        collapsed:Array.from(S.collapsed),compare:cmp.state()}),
      stats:()=>Object.assign({},stats,{pool:ui.liveTree?ui.liveTree.poolSize():0,archivePool:ui.archiveTree?ui.archiveTree.poolSize():0}),
      element:()=>ui.host||null,
      ui:()=>ui,
      /* Surface publique pour les preuves navigateur (jamais le contrôleur lui-même sur `window`) : de quoi lire le modèle de l'arbre sans le piloter. */
      inspectTree:()=>({total:ui.liveTree?ui.liveTree.rows().length:0,lastId:ui.liveTree&&ui.liveTree.rows().length?ui.liveTree.rows()[ui.liveTree.rows().length-1].id:null,domRows:ui.liveTree?ui.liveTree.poolSize():0}),
      repaint:()=>{if(ui.liveTree)ui.liveTree.repaint();if(ui.archiveTree)ui.archiveTree.repaint()},
      handleCommand:async(command)=>{
        stats.commands+=1;
        if(!command||typeof command!=='object')return {state:'refused',code:'explorer_page_error',reason:'commande illisible'};
        if(command.action==='close'){close({reason:'command'});return {state:'closed'}}
        if(command.action==='open'){
          const result=await open({presentation_id:command.presentation_id,variant_id:command.variant_id,fullscreen:command.fullscreen!==false,
            arm_s:command.arm_s,via:'command',opener:doc.activeElement});
          return result;
        }
        if(command.action==='compare'||command.action==='compose'){
          if(!S.open)return {state:'refused',code:'explorer_page_error',reason:"L'explorateur n'est pas ouvert."};
          return cmp.handleCommand(command);
        }
        return {state:'refused',code:'explorer_page_error',reason:'action inconnue'};
      },
      destroy(){close({reason:'destroy',quiet:true});if(ui.host)ui.host.remove();
        if(typeof win.removeEventListener==='function'){win.removeEventListener('resize',onResize);win.removeEventListener('jarvis:studio-view',onRunView);
          win.removeEventListener('jarvis:studio-surface',onRunSurface);win.removeEventListener('jarvis:studio-timeline',onRunTimeline)}
        doc.removeEventListener&&doc.removeEventListener('fullscreenchange',onFullscreenChange)},
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
      inspectTree:explorer.inspectTree,repaint:explorer.repaint,playback:explorer.playback,run:explorer.run,
      compare:Object.freeze({open:o=>explorer.compare.start(o),close:o=>explorer.compare.close(o),isOpen:()=>explorer.compare.isActive(),view:()=>explorer.compare.view(),
        state:()=>explorer.compare.state(),marks:()=>explorer.compare.marks(),mark:id=>explorer.compare.mark(id),focus:pair=>explorer.compare.setPair(pair),
        mode:m=>explorer.compare.setMode(m),navigate:s=>explorer.compare.navigate(s),link:(a,b)=>explorer.compare.link(a,b),unlink:(a,b)=>explorer.compare.unlink(a,b),
        refresh:()=>explorer.compare.refresh()}),
      compose:Object.freeze({plan:r=>explorer.compose.plan(r),create:r=>explorer.compose.commit(r),dialog:o=>explorer.compare.openCompose(o)}),
      channel:Object.freeze({state:channel.state,stats:channel.stats,pageId:channel.pageId}),
    });
    channel.setVisible(document.visibilityState!=='hidden');
    channel.start();
  }
  /* Rattrapé ici : la page servie n'a qu'une balise <script> ; une levée emporterait la scène avec elle. */
  try{installStudioExplorer()}
  catch(error){console.error('[studio-explorer] explorer_not_installed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
