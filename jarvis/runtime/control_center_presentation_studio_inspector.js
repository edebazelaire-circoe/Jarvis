/* Inspecteur d'édition d'une présentation du Studio (handoff jarvis-interactive-presentation-studio, Slice 07).
   Module DOM exposé en `window.JarvisStudioInspector` dans la page et en `module.exports` pour node.

   Ce fichier est le CONTRÔLEUR (état, réseau, file d'enregistrements, historique, aperçu local, disponibilité). Les fonctions pures et la CSS sont dans
   `control_center_presentation_studio_inspector_core.js`, les widgets générés dans `control_center_presentation_studio_inspector_widgets.js` (mêmes marqueurs de page, même surface publique `window.JarvisStudioInspector`).

   Ce que ce module est :
   - un panneau accroché au dock (bouton `INS`), contextuel : la scène choisie de la variante active d'une présentation, ses
     réglages rangés par groupe (contenu, style, mise en page, mouvement). Les widgets sont GÉNÉRÉS à partir de la route
     d'introspection (`GET .../variants/{vid}/scenes/{scene_id}/controls`) : type, bornes, défaut, valeur courante, sens. Aucun
     widget n'est écrit à la main pour un réglage précis (`widgetSpec` est la seule table) ;
   - une interface de la MÊME porte que la voix : toute modification passe par `POST .../variants/{vid}/edits` du relais (acteur
     `user` imposé côté serveur), avec les mêmes refus, la même base (`variant_revision`, `if_current`) et le même enregistrement
     d'annulation. Il n'existe aucun chemin d'écriture propre à l'inspecteur : rien dans `localStorage` sauf des préférences
     d'affichage (onglet, aperçu replié) ;
   - exigence de la Slice 08 : UNE modification = UNE entrée d'historique (l'anneau en garde 32). Un réglage continu (curseur,
     saisie, sélecteur de couleur) envoie des aperçus (`mode: preview`, jamais écrits, limités en débit, regroupés : seule la
     dernière valeur part) et n'est enregistré qu'UNE fois, au relâchement, à la sortie du champ ou sur Entrée (au clavier :
     après une courte pause sans nouvel appui) ;
   - lisible : chaque état est dit à l'écran ET journalisé (`[studio-inspector]`, et `obsClientLog` quand la page en a un) :
     chargement avec compteur, refus typés de Core avec ses propres mots, base périmée (valeurs relues et différences dites),
     scène en rechargement (409, nouvelles tentatives bornées et visibles), source dégradée, historique indisponible.

   Ce que ce module ne fait PAS :
   - il ne garde aucun état de présentation : tout vient de Core et y retourne ; l'aperçu local est un cadre de prefab en mode
     `preview` de l'hôte (rien ne part vers Core, les événements du cadre sont ignorés), jamais la scène projetée ;
   - il ne touche pas aux touches de la présentation : ses écouteurs sont posés sur son panneau, jamais sur le document en
     capture ; en lecture (une exécution tourne) ou en plein écran il est caché ENTIÈREMENT (`hidden` + `inert`, brouillons
     abandonnés) ; une saisie dans l'un de ses champs ne déclenche aucun raccourci de la page ;
   - il ne fait aucune édition de source (palier 3, voix/agent) : il montre seulement l'état de rechargement lu sur Core.

   Direction artistique : un chip en lecture seule (nom, provenance, contraste) lu par `GET .../art-direction`. La DA a SA PROPRE
   révision (l'enregistrer ne change pas celle de la variante) : c'est elle qu'on compare. Des 15 variables `--jv-*`, seules 5
   atteignent le cadre aujourd'hui (`THEME_VARS` du shim) ; les 10 autres sont montrées « non appliqué », jamais cachées.

   Clés : aucune écriture par clé dynamique dans un objet simple (les noms de propriétés d'un prefab peuvent valoir `__proto__`) ;
   `setAtPath` refuse ces noms et définit les propriétés avec `defineProperty`. Tout texte d'auteur passe par `textContent`. */
(function(root){
  'use strict';
  const Core=root.JarvisStudioInspectorCore||(typeof require==='function'?require('./control_center_presentation_studio_inspector_core.js'):null);
  const Widgets=root.JarvisStudioInspectorWidgets||(typeof require==='function'?require('./control_center_presentation_studio_inspector_widgets.js'):null);
  const {ROUTE,GROUPS,GROUP_LABEL,PANEL_ID,BUTTON_ID,STYLE_ID,PREVIEW_OBJECT_ID,STORAGE_KEY,PLAYBACK_EVENT,PREVIEW_MIN_MS,TEXT_PREVIEW_MS,IDLE_COMMIT_MS,REQUEST_TIMEOUT_MS,READ_TIMEOUT_MS,POLL_MS,AVAILABILITY_MS,SAVED_FLASH_MS,RELOAD_RETRY_MS,UNSAFE_KEYS,HEX_COLOR,APPLIED_THEME,NOT_APPLIED_THEME,CSS,describe,clip,cloneJson,canonical,sameJson,pathParts,setAtPath,previewValues,widgetSpec,stepFor,decimalsOf,roundTo,formatValue,validateValue,diffControls,luminance,contrastRatio,PROVENANCE,describeRefusal,HISTORY_TEXT,InspectorError}=Core;

  /* ------------------------------------------------------------------ contrôleur */
  function createStudioInspector(deps){
    const d=deps||{};
    const doc=d.document||root.document;
    const win=d.window||root;
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=d.clearTimeout||((id)=>clearTimeout(id));
    const every=d.setInterval||((fn,ms)=>setInterval(fn,ms));
    const stopEvery=d.clearInterval||((id)=>clearInterval(id));
    const now=d.now||(()=>Date.now());
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const notify=typeof d.toast==='function'?d.toast:(typeof root.toast==='function'?root.toast:null);
    const playing=d.playing||(()=>{
      const player=root.JarvisStudioPlayer,view=player&&typeof player.view==='function'?player.view():null;
      return !!view&&view.running===true&&view.phase!=='stopped'&&view.phase!=='idle';
    });
    const inFullscreen=d.fullscreen||(()=>!!(doc&&doc.fullscreenElement));
    const storage=d.storage||(()=>{try{return root.localStorage||null}catch(_error){return null /* intentional: blocked storage only costs the remembered tab */}});
    const stats={previews:0,previewsCoalesced:0,writesSuperseded:0,commits:0,staleHandled:0,reloadRetries:0,undo:0,redo:0,failures:0,renders:0,polls:0,hiddenByPlayback:0};
    const S={
      open:false,available:true,hiddenReason:null,presentations:[],presentationId:null,variant:null,sceneId:null,scene:null,
      tab:'content',showPreview:true,history:null,art:{state:'idle',doc:null,revision:null,message:''},
      reload:{pending:[],rows:[],degraded:null},loading:null,fatal:null,status:null,reloading:null,generation:0,
    };
    const ui={};
    const widgets=new Map();     /* control_id -> {row, el, update(row), session} */
    const sessions=new Map();    /* control_id -> brouillon en cours */
    const queue={tail:Promise.resolve(),pending:new Map()};
    let pollTimer=null,availTimer=null,loadingTimer=null,saveTimer=null;
    let previewHost=null,previewMounted=null,storedScene=null;
    let primedReload=false;

    /* -------------------------------------------------------------- journal et retour visible (RULE ZERO) */
    function log(key,data,level){
      const line=`[studio-inspector] ${key} ${JSON.stringify(data||{})}`;
      try{
        const sink=d.console||root.console;
        if(sink){if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line)}
      }catch(_error){/* intentional: a broken console never breaks the editor */}
      if(level==='error'||level==='warn'){
        try{const obs=d.obsClientLog||root.obsClientLog;if(typeof obs==='function')obs(level,level==='error'?'ERROR':'WARN',`studio_inspector_${key}`,data||{})}
        catch(_error){/* intentional: the console line above is the record when the page's logger is absent or broken */}
      }
    }
    function tell(title,sub,kind){
      if(!notify)return;
      try{notify({title,sub:sub||'',kind:kind||'info',ms:kind==='bad'?9000:5000})}catch(_error){/* intentional: the inline message is the surface, the toast a courtesy */}
    }
    /* Le bouton dit pourquoi il est éteint : pas de présentation réglée, ou lecture / plein écran en cours (le panneau est alors masqué). */
    function syncExplore(){
      if(!ui.explore)return;
      const reason=!S.available?(S.hiddenReason==='fullscreen'?"Quittez le plein écran pour ouvrir l'explorateur de variantes.":"Une lecture est en cours : l'explorateur de variantes est un outil d'édition."):
        !S.presentationId?"Choisissez d'abord une présentation.":null;
      ui.explore.disabled=reason!==null;
      ui.explore.setAttribute('aria-disabled',String(reason!==null));
      ui.explore.title=reason||"Explorateur de variantes : l'arbre des branches de cette présentation";
    }
    async function openExplorer(){
      const explorer=root.JarvisStudioExplorer;
      if(!S.presentationId)return;
      if(!explorer||typeof explorer.open!=='function'){setStatus('warn','Explorateur indisponible',"Le module de l'explorateur de variantes n'est pas chargé dans cette page.");return}
      let result=null;
      S.explorerReturn=true;     /* le plein écran de l'explorateur range ce panneau : à la fermeture il revient, avec le focus sur ce bouton */
      try{
        result=await explorer.open({presentation_id:S.presentationId,variant_id:S.variant&&S.variant.variant_id||undefined,opener:ui.explore});
      }catch(error){log('explorer_open_failed',{error:describe(error)},'error');setStatus('bad','Explorateur de variantes',describe(error));return}
      if(!result||result.state!=='opened')S.explorerReturn=false;
      if(result&&result.state==='refused'){
        log('explorer_refused',{code:result.code},'warn');
        setStatus('warn','Explorateur de variantes',result.reason||result.code);
        announce(result.reason||'');
      }
    }
    function onExplorerClosed(){
      if(!S.explorerReturn)return;
      S.explorerReturn=false;
      checkAvailability();
      if(!S.available)return;
      if(!S.open)open({noFocus:true});
      if(ui.explore&&!ui.explore.disabled)ui.explore.focus();
    }
    function announce(text){if(ui.live)ui.live.textContent=text}
    function prefs(){
      try{const store=storage();const raw=store&&store.getItem(STORAGE_KEY);const p=raw?JSON.parse(raw):null;return p&&typeof p==='object'?p:{}}
      catch(_error){return {} /* intentional: unreadable preference = defaults */}
    }
    function savePrefs(){
      try{const store=storage();if(store)store.setItem(STORAGE_KEY,JSON.stringify({tab:S.tab,preview:S.showPreview}))}
      catch(_error){/* intentional: a preference that cannot be stored is only forgotten */}
    }

    /* -------------------------------------------------------------- DOM */
    function el(tag,cls,text){
      const node=doc.createElement(tag);
      if(cls)node.className=cls;
      if(text!==undefined&&text!==null)node.textContent=text;
      return node;
    }
    function attrs(node,map){for(const [k,v] of Object.entries(map))node.setAttribute(k,String(v));return node}
    function clear(node){while(node.firstChild)node.removeChild(node.firstChild)}
    function button(label,cls,onClick,extra){
      const b=el('button',cls,label);
      b.setAttribute('type','button');
      if(extra)attrs(b,extra);
      if(onClick)b.addEventListener('click',onClick);
      return b;
    }
    let idSeq=0;
    const uid=(p)=>`jvi-${p}-${++idSeq}`;

    function ensureStyle(){
      if(!doc||typeof doc.getElementById!=='function'||doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;style.textContent=CSS;
      (doc.head||doc.body).appendChild(style);
    }

    function build(){
      if(ui.root)return ui.root;
      ensureStyle();
      const panel=el('aside');
      panel.id=PANEL_ID;
      attrs(panel,{role:'region','aria-label':'Inspecteur de présentation'});
      panel.hidden=true;
      ui.title=el('h2','jvi-title','Inspecteur');
      ui.title.id='jviTitle';ui.title.setAttribute('tabindex','-1');
      ui.undo=button('↶','jvi-icon',()=>{runHistory('undo')},{'aria-label':'Annuler la dernière modification',title:'Annuler (Ctrl+Z dans l\'inspecteur)'});
      ui.redo=button('↷','jvi-icon',()=>{runHistory('redo')},{'aria-label':'Rétablir la modification annulée',title:'Rétablir (Ctrl+Y dans l\'inspecteur)'});
      ui.undo.disabled=true;ui.redo.disabled=true;
      /* Porte graphique de l'explorateur de variantes (Slice 18) : même appel que la voix, depuis la présentation réglée ici. */
      ui.explore=button('Variantes','jvi-icon jvi-explore',()=>{openExplorer()},{"aria-label":"Ouvrir l'explorateur de variantes",title:"Explorateur de variantes : l'arbre des branches de cette présentation"});
      ui.explore.disabled=true;
      ui.close=button('×','jvi-icon',()=>{close({restoreFocus:true})},{'aria-label':'Fermer l\'inspecteur',title:'Fermer (Échap)'});
      const bar=el('div','jvi-bar');
      [ui.title,ui.explore,ui.undo,ui.redo,ui.close].forEach((n)=>bar.appendChild(n));
      ui.live=el('div','jvi-sr');attrs(ui.live,{role:'status','aria-live':'polite'});
      ui.pick=el('div','jvi-pick');
      ui.status=el('div','jvi-status');ui.status.hidden=true;
      ui.spin=el('span','jvi-spin');ui.spin.setAttribute('aria-hidden','true');
      ui.statusText=el('div','jvi-msgtext');
      ui.statusActions=el('div');ui.statusActions.style.display='flex';ui.statusActions.style.gap='6px';
      ui.status.appendChild(ui.spin);ui.status.appendChild(ui.statusText);ui.status.appendChild(ui.statusActions);
      ui.reloadBanner=el('div','jvi-status');ui.reloadBanner.hidden=true;
      ui.reloadText=el('div','jvi-msgtext');ui.reloadBanner.appendChild(ui.reloadText);
      ui.srcline=el('p','jvi-default');ui.srcline.hidden=true;ui.srcline.style.margin='6px 14px 0';
      ui.da=el('details','jvi-da');ui.da.hidden=true;
      ui.stage=el('details','jvi-stage');ui.stage.hidden=true;
      ui.stageSummary=el('summary',null,'Aperçu local');
      ui.slot=el('div','jvi-slot');
      ui.stageNote=el('p','jvi-stagenote','Aperçu local : rien n\'est écrit avant le relâchement.');
      ui.stage.appendChild(ui.stageSummary);ui.stage.appendChild(ui.slot);ui.stage.appendChild(ui.stageNote);
      ui.stage.addEventListener('toggle',()=>{S.showPreview=!!ui.stage.open;savePrefs();if(S.showPreview)syncPreview()});
      ui.tabs=el('div','jvi-tabs');attrs(ui.tabs,{role:'tablist','aria-label':'Groupes de réglages'});
      ui.main=el('div','jvi-main');
      ui.issues=el('div');
      ui.panels=el('div');
      ui.empty=el('p','jvi-empty');ui.empty.hidden=true;
      ui.top=el('div','jvi-top');
      [ui.pick,ui.status,ui.reloadBanner,ui.srcline].forEach((n)=>ui.top.appendChild(n));
      [ui.da,ui.empty,ui.issues,ui.panels].forEach((n)=>ui.main.appendChild(n));
      [bar,ui.live,ui.top,ui.stage,ui.tabs,ui.main].forEach((n)=>panel.appendChild(n));
      panel.addEventListener('keydown',onPanelKey);
      ui.root=panel;
      /* Même repère que le panneau latéral (`.panel`) : le parent du dock (le bouton est dans un `.tool` du `nav.dock`). */
      const nav=ui.dock&&typeof ui.dock.closest==='function'?ui.dock.closest('.dock'):null;
      (nav&&nav.parentNode||doc.body).appendChild(panel);
      return panel;
    }

    /* -------------------------------------------------------------- réseau */
    async function call(url,options){
      const o=options||{};
      if(!fetchImpl)throw new InspectorError('fetch indisponible dans cette page','unreachable',0);
      const controller=typeof AbortController==='function'?new AbortController():null;
      const timeoutMs=o.timeoutMs||REQUEST_TIMEOUT_MS;
      let expired=false;
      const deadline=later(()=>{expired=true;if(controller)controller.abort()},timeoutMs);
      try{
        const response=await fetchImpl(url,{method:o.method||'GET',cache:'no-store',
          headers:o.body!==undefined?{'Content-Type':'application/json'}:undefined,
          body:o.body!==undefined?JSON.stringify(o.body):undefined,signal:controller?controller.signal:undefined});
        const text=await response.text();
        let json=null;
        try{json=text?JSON.parse(text):null}catch(_error){json=null /* a non-JSON answer is reported by its status below */}
        return {status:response.status,ok:response.ok,body:json};
      }catch(error){
        if(expired)throw new InspectorError(`Core n'a pas répondu en ${Math.round(timeoutMs/1000)} s`,'timeout',0);
        if(error&&error.name==='AbortError')throw new InspectorError('requête annulée','cancelled',0);
        throw new InspectorError(describe(error),'unreachable',0);
      }finally{cancelLater(deadline)}
    }
    function envelopeOf(response){
      const error=response.body&&response.body.error;
      return {code:error&&error.code?String(error.code):`http_${response.status}`,
        message:error&&error.message?String(error.message):`HTTP ${response.status}`,http:response.status};
    }
    async function read(url,what){
      const response=await call(url,{timeoutMs:READ_TIMEOUT_MS});
      if(!response.ok||!response.body||response.body.error){
        const e=envelopeOf(response);
        throw new InspectorError(`${what} : ${e.message}`,e.code,e.http);
      }
      return response.body;
    }
    const base=()=>`${ROUTE}/${encodeURIComponent(S.presentationId)}`;
    const variantBase=()=>`${base()}/variants/${encodeURIComponent(S.variant.variant_id)}`;

    /* -------------------------------------------------------------- attente visible */
    function setLoading(what){
      S.loading=what?{what,since:now()}:null;
      renderStatus();
    }
    /* Une seule horloge de 500 ms tant qu'une attente (chargement, rechargement) est à l'écran. */
    function syncClock(){
      const needed=!!(S.loading||S.reloading);
      if(needed&&loadingTimer===null)loadingTimer=every(()=>renderStatus(),500);
      else if(!needed&&loadingTimer!==null){stopEvery(loadingTimer);loadingTimer=null}
    }
    function setFatal(error,retry){
      S.fatal=error?{message:describe(error),code:error.code||'error',retry}:null;
      renderStatus();
    }
    function setStatus(kind,title,text,actions){
      S.status=kind?{kind,title,text,actions:actions||[],at:now()}:null;
      renderStatus();
    }

    function renderStatus(){
      if(!ui.status)return;
      syncClock();
      clear(ui.statusActions);
      const spinning=!!S.loading||!!S.reloading;
      let shown=null;
      if(S.fatal)shown={kind:'bad',title:'Chargement impossible',text:`${S.fatal.message} (${S.fatal.code})`,
        actions:S.fatal.retry?[{label:'Réessayer',run:S.fatal.retry}]:[]};
      else if(S.reloading){
        const r=S.reloading;
        const left=Math.max(0,Math.ceil((r.nextAt-now())/1000));
        shown={kind:'warn',title:'Rechargement en cours',clock:`tentative ${r.attempt}/${r.max} · prochaine dans ${left} s`,
          text:'Votre modification est en attente et repartira toute seule.',
          actions:[{label:'Arrêter d\'attendre',run:()=>giveUpReload()}]};
      }else if(S.loading){
        const sec=Math.floor((now()-S.loading.since)/1000);
        shown={kind:'info',title:S.loading.what,clock:`${sec} s / ${READ_TIMEOUT_MS/1000} s`,text:''};
      }else if(S.status)shown=S.status;
      ui.status.hidden=!shown;
      if(!shown)return;
      ui.status.setAttribute('data-kind',shown.kind);
      ui.spin.hidden=!spinning;
      ui.status.setAttribute('role',shown.kind==='bad'||shown.kind==='warn'?'alert':'status');
      clear(ui.statusText);
      ui.statusText.appendChild(el('strong',null,shown.title));
      if(shown.text)ui.statusText.appendChild(doc.createTextNode(shown.text));
      if(shown.clock)ui.statusText.appendChild(el('span','jvi-clock',shown.clock));
      for(const action of shown.actions||[])ui.statusActions.appendChild(button(action.label,'jvi-btn',action.run));
      if(!shown.actions||!shown.actions.length){
        if(shown.kind==='ok'||shown.kind==='info')return;
        ui.statusActions.appendChild(button('Fermer','jvi-btn',()=>setStatus(null)));
      }
    }

    /* -------------------------------------------------------------- chargement */
    async function loadPresentations(){
      const generation=++S.generation;
      setLoading('Chargement des présentations…');setFatal(null);
      try{
        const list=await read(ROUTE,'Liste des présentations');
        if(generation!==S.generation)return;
        S.presentations=Array.isArray(list.presentations)?list.presentations:[];
        const problems=Array.isArray(list.problems)?list.problems.length:0;
        log('presentations_loaded',{count:S.presentations.length,problems});
        if(!S.presentations.some((p)=>p.presentation_id===S.presentationId))S.presentationId=S.presentations.length?S.presentations[0].presentation_id:null;
        renderPick();
        if(S.presentationId)await selectPresentation(S.presentationId,{keepScene:true});
        else{setLoading(null);S.variant=null;S.scene=null;renderAll()}
      }catch(error){
        stats.failures++;
        setFatal(error,()=>{loadPresentations()});
        log('presentations_failed',{code:error.code,error:describe(error)},'error');
        tell('Inspecteur : présentations illisibles',describe(error),'bad');
      }finally{setLoading(null)}
    }
    async function selectPresentation(id,options){
      const keep=options&&options.keepScene;
      S.presentationId=id;
      abandonDrafts('presentation');
      const body=await read(`${ROUTE}/${encodeURIComponent(id)}`,'Présentation');
      const active=body.presentation&&body.presentation.active_variant_id;
      let variant=(body.variants||[]).find((v)=>v.variant_id===active)||null;
      if(!variant&&active)variant=await read(`${ROUTE}/${encodeURIComponent(id)}/variants/${encodeURIComponent(active)}`,'Variante');
      S.variant=variant;syncExplore();
      S.history=null;S.art={state:'idle',doc:null,revision:null,message:''};
      const scenes=variant&&Array.isArray(variant.scenes)?variant.scenes:[];
      if(!keep||!scenes.some((s)=>s.scene_id===S.sceneId))S.sceneId=scenes.length?scenes[0].scene_id:null;
      renderPick();
      log('variant_loaded',{presentation_id:id,variant_id:variant&&variant.variant_id,scenes:scenes.length,revision:variant&&variant.revision});
      await Promise.all([loadScene(),loadHistory(),loadArtDirection()]);
      pollReloads();
    }
    async function loadScene(options){
      const o=options||{};
      if(!S.variant||!S.sceneId){S.scene=null;storedScene=null;renderAll();return null}
      const generation=++S.generation;
      if(!o.quiet)setLoading('Chargement des réglages…');
      try{
        const [variant,scene]=await Promise.all([
          read(variantBase(),'Variante'),
          read(`${variantBase()}/scenes/${encodeURIComponent(S.sceneId)}/controls`,'Réglages de la scène')]);
        if(generation!==S.generation)return null;
        const before=S.scene&&S.scene.scene_id===scene.scene_id?S.scene.controls:null;
        S.variant=variant;
        storedScene=(variant.scenes||[]).find((s)=>s.scene_id===S.sceneId)||null;
        S.scene=scene;
        setFatal(null);
        renderAll();
        if(!o.quiet)log('scene_loaded',{scene_id:scene.scene_id,controls:(scene.controls||[]).length,revision:scene.variant_revision,problems:(scene.problems||[]).length});
        return before?{before,after:scene.controls}:null;
      }catch(error){
        stats.failures++;
        if(error.code==='presentation_studio_unknown_scene'&&S.variant){
          log('scene_gone',{scene_id:S.sceneId},'warn');
          const scenes=S.variant.scenes||[];
          S.sceneId=scenes.length?scenes[0].scene_id:null;
          setStatus('warn','La scène n\'existe plus','Une autre modification l\'a retirée : la première scène est affichée.');
          return loadScene({quiet:true});
        }
        setFatal(error,()=>{loadScene()});
        log('scene_failed',{scene_id:S.sceneId,code:error.code,error:describe(error)},'error');
        tell('Inspecteur : réglages illisibles',describe(error),'bad');
        return null;
      }finally{if(!o.quiet)setLoading(null)}
    }
    async function loadHistory(){
      if(!S.variant)return;
      try{
        S.history=await read(`${variantBase()}/history`,'Historique');
        renderHistory();
      }catch(error){
        S.history=null;renderHistory();
        log('history_failed',{code:error.code,error:describe(error)},'warn');
      }
    }
    async function loadArtDirection(){
      if(!S.variant)return;
      const previous=S.art.revision;
      try{
        const response=await call(`${variantBase()}/art-direction`,{timeoutMs:READ_TIMEOUT_MS});
        if(response.status===404&&response.body&&response.body.error&&response.body.error.code==='presentation_studio_unknown_art_direction'){
          S.art={state:'absent',doc:null,revision:null,message:''};
        }else if(!response.ok||!response.body||!response.body.art_direction){
          const e=envelopeOf(response);
          throw new InspectorError(e.message,e.code,e.http);
        }else{
          const doc_=response.body.art_direction;
          S.art={state:'ok',doc:doc_,revision:doc_.revision,message:''};
          if(previous!==null&&previous!==doc_.revision){
            log('art_direction_changed',{from:previous,to:doc_.revision});
            announce('La direction artistique a été mise à jour.');
          }
        }
      }catch(error){
        S.art={state:'error',doc:null,revision:null,message:describe(error)};
        log('art_direction_failed',{code:error.code,error:describe(error)},'warn');
      }
      renderArt();
    }
    async function pollReloads(){
      if(!S.open||!S.available||!S.presentationId||(doc&&doc.hidden))return;
      stats.polls++;
      try{
        const body=await read(`${base()}/reloads`,'Rechargements');
        S.reload.pending=Array.isArray(body.pending)?body.pending:[];
        S.reload.rows=Array.isArray(body.reloads)?body.reloads:[];
        const mine=S.sceneId;
        const rows=S.reload.rows.filter((r)=>r.scene_id===mine&&(!S.variant||r.variant_id===S.variant.variant_id));
        const last=rows.length?rows[rows.length-1]:null;
        const pending=S.reload.pending.find((p)=>p.scene_id===mine);
        const next=pending?{kind:'warn',title:'Source récente non confirmée',
          text:'Un nouveau modèle est en place mais la page ne l\'a pas encore vu monter : le repli enregistré reste disponible.'}:
          last&&last.status==='degraded'?{kind:'bad',title:'Source dégradée',
            text:'Le nouveau modèle n\'a pas monté et le retour arrière a échoué. La scène garde son repli enregistré : demandez un rechargement ou redémarrez Core.'}:null;
        /* Slice 06 QA-2 : un rechargement qui garde des valeurs que la nouvelle source ne peut plus accepter les NOMME (`reset.unfit`). */
        const unfit=last&&last.reset&&Array.isArray(last.reset.unfit)?last.reset.unfit:[];
        const banner=next||(unfit.length?{kind:'warn',title:'Valeurs à corriger après le rechargement',
          text:`La nouvelle source ne les accepte plus, elles sont gardées telles quelles : ${unfit.slice(0,6).join(', ')}${unfit.length>6?'…':''}.`}:null);
        const key=banner?banner.title:null;
        if(key!==S.reload.degraded){S.reload.degraded=key;if(banner)log('reload_state',{scene_id:mine,state:banner.title},banner.kind==='bad'?'error':'warn')}
        renderReloadBanner(banner);
        S.reload.versions=body.versions&&typeof body.versions==='object'?body.versions[mine]||null:null;
        S.reload.last=last;
        renderSourceLine();
        /* Un rechargement (voix ou autre) a changé la révision de la variante : on relit tout de suite, la prochaine modification part de la bonne base. */
        const rowKey=last?`${last.status}|${last.source_revision}|${last.late?'late':'now'}`:'';
        if(primedReload&&rowKey!==S.reload.rowKey){log('reload_seen',{scene_id:mine,status:last&&last.status});loadScene({quiet:true})}
        S.reload.rowKey=rowKey;
        primedReload=true;
        if(stats.polls%2===0)loadArtDirection();
      }catch(error){
        log('reloads_failed',{code:error.code,error:describe(error)},'warn');
      }
    }

    /* -------------------------------------------------------------- rendu */
    function renderPick(){
      if(!ui.pick)return;
      clear(ui.pick);
      const solo=S.presentations.length<=1;
      ui.pick.className='jvi-pick'+(solo?' is-solo':'');
      if(!S.presentations.length)return;
      if(!solo){
        const label=el('label','jvi-field');label.appendChild(el('span',null,'Présentation'));
        const select=el('select');select.setAttribute('aria-label','Présentation');
        for(const p of S.presentations){
          const o=el('option',null,p.title||p.presentation_id);o.value=p.presentation_id;
          if(p.presentation_id===S.presentationId)o.selected=true;
          select.appendChild(o);
        }
        select.addEventListener('change',()=>{selectPresentation(select.value).catch((error)=>{setFatal(error,()=>{loadPresentations()});log('presentation_failed',{error:describe(error)},'error')})});
        label.appendChild(select);ui.pick.appendChild(label);
      }
      const scenes=(S.variant&&S.variant.scenes)||[];
      const field=el('label','jvi-field');
      field.appendChild(el('span',null,S.variant?`Scène · ${S.variant.title||'variante active'}`:'Scène'));
      const sel=el('select');sel.setAttribute('aria-label','Scène');sel.id='jviScene';
      scenes.forEach((s,i)=>{
        const o=el('option',null,`${i+1}. ${s.title||'(sans titre)'}${s.section?' · '+s.section:''}`);o.value=s.scene_id;
        if(s.scene_id===S.sceneId)o.selected=true;
        sel.appendChild(o);
      });
      sel.addEventListener('change',()=>{chooseScene(sel.value)});
      field.appendChild(sel);
      const index=scenes.findIndex((s)=>s.scene_id===S.sceneId);
      const prev=button('‹','jvi-icon',()=>{if(index>0)chooseScene(scenes[index-1].scene_id)},{'aria-label':'Scène précédente',title:'Scène précédente'});
      const next=button('›','jvi-icon',()=>{if(index>=0&&index<scenes.length-1)chooseScene(scenes[index+1].scene_id)},{'aria-label':'Scène suivante',title:'Scène suivante'});
      prev.disabled=index<=0;next.disabled=index<0||index>=scenes.length-1;
      if(solo){
        const row=el('div');row.style.display='grid';row.style.gridTemplateColumns='minmax(0,1fr) auto auto';row.style.gap='6px';row.style.alignItems='end';
        row.appendChild(field);row.appendChild(prev);row.appendChild(next);ui.pick.appendChild(row);
      }else{ui.pick.appendChild(field);ui.pick.appendChild(prev);ui.pick.appendChild(next)}
    }
    function chooseScene(id){
      if(id===S.sceneId)return;
      abandonDrafts('scene');
      S.sceneId=id;S.reload.degraded=null;renderReloadBanner(null);
      renderPick();
      loadScene().then(()=>pollReloads());
    }

    function renderHistory(){
      if(!ui.undo)return;
      const h=S.history;
      const canUndo=!!h&&h.undo_count>0,canRedo=!!h&&h.redo_count>0;
      ui.undo.disabled=!canUndo;ui.redo.disabled=!canRedo;
      const who=(e)=>e&&e.actor==='brain'?' (faite par Jarvis)':'';
      ui.undo.title=canUndo?`Annuler la dernière modification${who(h.next_undo)} (Ctrl+Z dans l'inspecteur)`:'Rien à annuler';
      ui.redo.title=canRedo?`Rétablir la modification annulée${who(h.next_redo)} (Ctrl+Y dans l'inspecteur)`:'Rien à rétablir';
      if(!canUndo)ui.undo.title=h&&h.tracked===false?'Rien à annuler : l\'historique ne garde que les modifications faites depuis le démarrage de Core':'Rien à annuler';
    }

    function renderArt(){
      if(!ui.da)return;
      const a=S.art;
      ui.da.hidden=a.state==='idle';ui.da.style.margin='10px 14px 0';
      clear(ui.da);
      if(a.state==='idle')return;
      const summary=el('summary');
      if(a.state==='ok'){
        const p=a.doc.profile||{},prov=p.provenance||{},pal=p.palette||{};
        summary.appendChild(el('span','jvi-chip',`DA · rév. ${a.doc.revision}`));
        summary.appendChild(el('span','jvi-da-name',p.name||'(sans nom)'));
        summary.appendChild(el('span','jvi-chip',PROVENANCE[prov.origin]||String(prov.origin||'?')));
        if(prov.fallback)summary.appendChild(el('span','jvi-chip is-warn','repli'));
        const ratio=contrastRatio(pal.text,pal.background);
        if(ratio===null)summary.appendChild(el('span','jvi-chip is-warn','contraste inconnu'));
        else summary.appendChild(el('span','jvi-chip '+(ratio>=4.5?'is-ok':'is-bad'),`contraste ${ratio.toFixed(1)} : 1 ${ratio>=4.5?'✓':'✗'}`));
        ui.da.appendChild(summary);
        const body=el('div','jvi-da-body');
        const sw=el('div','jvi-swatches');sw.setAttribute('aria-hidden','true');
        for(const name of ['background','surface','text','muted','accent']){
          if(!HEX_COLOR.test(pal[name]||''))continue;
          const s=el('span','jvi-swatch');s.style.background=pal[name];s.title=`${name} ${pal[name]}`;sw.appendChild(s);
        }
        body.appendChild(sw);
        body.appendChild(el('p','jvi-default','Lecture seule. Livré au cadre de la scène aujourd\'hui : 5 variables ; les autres sont produites par la direction artistique mais aucun chemin ne les pose encore.'));
        const list=el('ul','jvi-theme');
        for(const name of APPLIED_THEME){const li=el('li');li.appendChild(el('code',null,name));li.appendChild(el('span',null,'appliqué'));list.appendChild(li)}
        for(const name of NOT_APPLIED_THEME){
          const li=el('li','is-off');li.title='Aucun chemin de livraison vers le cadre aujourd\'hui';
          li.appendChild(el('code',null,name));li.appendChild(el('span',null,'non appliqué'));list.appendChild(li);
        }
        body.appendChild(list);
        ui.da.appendChild(body);
      }else if(a.state==='absent'){
        summary.appendChild(el('span','jvi-chip','DA'));
        summary.appendChild(el('span','jvi-da-name','Aucune direction artistique pour cette variante'));
        ui.da.appendChild(summary);
      }else{
        summary.appendChild(el('span','jvi-chip is-bad','DA'));
        summary.appendChild(el('span','jvi-da-name',`Direction artistique illisible : ${clip(a.message,120)}`));
        ui.da.appendChild(summary);
        const body=el('div','jvi-da-body');body.appendChild(button('Réessayer','jvi-btn',()=>{loadArtDirection()}));ui.da.appendChild(body);
      }
    }
    const RELOAD_STATUS_TEXT=Object.freeze({reloaded:'rechargée',reloaded_state_reset:'rechargée, valeurs remises à zéro',repinned:'enregistrée, sans fenêtre à recharger',
      pending_mount:'montage non confirmé',refused_validation:'refusée avant publication',rolled_back:'annulée (retour à la version valide)',stale:'périmée',degraded:'dégradée'});
    /* Ligne de lecture seule : combien de versions a la source de la scène (vivantes, archivées) et comment s'est passé son dernier rechargement. */
    function renderSourceLine(){
      if(!ui.srcline)return;
      const v=S.reload.versions,last=S.reload.last;
      const parts=[];
      if(v&&Number.isFinite(v.live))parts.push(`Source du modèle : ${v.live} version${v.live>1?'s':''}${v.archived>0?` (+ ${v.archived} archivée${v.archived>1?'s':''})`:''}`);
      if(last)parts.push(`dernier rechargement : ${RELOAD_STATUS_TEXT[last.status]||last.status}`);
      ui.srcline.hidden=!parts.length;
      ui.srcline.textContent=parts.join(' · ');
    }
    function renderReloadBanner(info){
      if(!ui.reloadBanner)return;
      ui.reloadBanner.hidden=!info;
      if(!info)return;
      ui.reloadBanner.setAttribute('data-kind',info.kind);
      ui.reloadBanner.setAttribute('role',info.kind==='bad'?'alert':'status');
      clear(ui.reloadText);
      ui.reloadText.appendChild(el('strong',null,info.title));
      ui.reloadText.appendChild(doc.createTextNode(info.text));
    }

    /* Un réglage rendu : structure stable tant que la liste de réglages ne change pas. */
    function signature(scene){
      return canonical((scene.controls||[]).map((r)=>[r.control_id,r.type,r.widget,r.group,r.bounds,r.label,r.meaning,r.default,
        widgetSpec(r).kind]));
    }
    function renderAll(){
      if(!ui.root)return;
      stats.renders++;
      renderPick();renderHistory();renderArt();
      const scene=S.scene;
      ui.empty.hidden=true;
      if(!S.presentations.length&&!S.loading&&!S.fatal){
        ui.empty.hidden=false;ui.empty.textContent='Aucune présentation pour le moment. Demandez à Jarvis d\'en créer une, ou ouvrez-en une depuis l\'atelier.';
        clearPanels();ui.stage.hidden=true;ui.tabs.hidden=true;return;
      }
      if(S.variant&&!(S.variant.scenes||[]).length){
        ui.empty.hidden=false;ui.empty.textContent='Cette variante n\'a pas encore de scène.';
        clearPanels();ui.stage.hidden=true;ui.tabs.hidden=true;return;
      }
      if(!scene){clearPanels();ui.tabs.hidden=true;return}
      ui.tabs.hidden=false;
      clear(ui.issues);
      if(Array.isArray(scene.problems)&&scene.problems.length){
        const box=el('div','jvi-status');box.setAttribute('data-kind','warn');box.setAttribute('role','alert');
        const text=el('div','jvi-msgtext');text.appendChild(el('strong',null,'Cette scène a des valeurs à corriger'));
        const ul=el('ul','jvi-issues');for(const p of scene.problems.slice(0,6))ul.appendChild(el('li',null,clip(p,200)));
        text.appendChild(ul);box.appendChild(text);ui.issues.appendChild(box);
      }
      const rows=scene.controls||[];
      if(!rows.length){
        ui.empty.hidden=false;
        ui.empty.textContent='Cette scène n\'expose aucun réglage. Demandez à Jarvis de proposer des réglages, ou de modifier sa source.';
      }
      const sig=signature(scene);
      if(sig!==ui.signature||!ui.panels.firstChild){ui.signature=sig;rebuildPanels(rows)}
      else for(const row of rows){const w=widgets.get(row.control_id);if(w)w.update(row)}
      syncPreview();
    }
    function clearPanels(){clear(ui.panels);clear(ui.tabs);widgets.clear();ui.signature=null;unmountPreview()}

    function rebuildPanels(rows){
      clear(ui.panels);clear(ui.tabs);widgets.clear();
      const present=GROUPS.filter((g)=>rows.some((r)=>r.group===g));
      for(const r of rows)if(!GROUPS.includes(r.group)&&!present.includes(r.group))present.push(r.group);
      if(!present.includes(S.tab))S.tab=present[0]||'content';
      const tabs=[];
      for(const group of present){
        const tab=el('button','jvi-tab');
        tab.type='button';tab.id=`jviTab-${group}`;
        attrs(tab,{role:'tab','aria-controls':`jviPanel-${group}`,'aria-selected':group===S.tab,tabindex:group===S.tab?0:-1});
        tab.appendChild(doc.createTextNode(GROUP_LABEL[group]||group));
        tab.appendChild(el('span','jvi-n',String(rows.filter((r)=>r.group===group).length)));
        tab.addEventListener('click',()=>selectTab(group,{focus:false}));
        tab.addEventListener('keydown',(event)=>onTabKey(event,present));
        ui.tabs.appendChild(tab);tabs.push(tab);
        const panel=el('div');
        panel.id=`jviPanel-${group}`;
        attrs(panel,{role:'tabpanel','aria-labelledby':`jviTab-${group}`});
        panel.hidden=group!==S.tab;
        const list=el('ul','jvi-list');
        for(const row of rows.filter((r)=>r.group===group)){
          const w=buildRow(row);widgets.set(row.control_id,w);list.appendChild(w.el);
        }
        panel.appendChild(list);ui.panels.appendChild(panel);
      }
      ui.tabsList=present;
    }
    function selectTab(group,options){
      if(!ui.tabsList||!ui.tabsList.includes(group))return;
      S.tab=group;savePrefs();
      for(const tab of ui.tabs.children){
        const on=tab.id==='jviTab-'+group;
        tab.setAttribute('aria-selected',String(on));tab.setAttribute('tabindex',on?'0':'-1');
        if(on&&options&&options.focus)tab.focus();
      }
      for(const panel of ui.panels.children)panel.hidden=panel.id!=='jviPanel-'+group;
    }
    function onTabKey(event,groups){
      const keys={ArrowRight:1,ArrowLeft:-1,Home:'first',End:'last'};
      if(!(event.key in keys))return;
      event.preventDefault();
      const i=groups.indexOf(S.tab);
      const next=keys[event.key]==='first'?0:keys[event.key]==='last'?groups.length-1:(i+keys[event.key]+groups.length)%groups.length;
      selectTab(groups[next],{focus:true});
    }

    /* -------------------------------------------------------------- widgets générés */
    function buildRow(row0){
      const ctx={row:row0,session:null};
      const inputId=uid('in'),descId=uid('desc'),msgId=uid('msg');
      const li=el('li','jvi-row');li.setAttribute('data-control-id',row0.control_id);
      const head=el('div','jvi-head');
      const label=el('label','jvi-label',row0.label||row0.control_id);label.setAttribute('for',inputId);
      const stateEl=el('span','jvi-state');
      const reset=button('↺','jvi-reset',()=>{resetControl(ctx.row)},{'aria-label':`Rétablir « ${row0.label} » à sa valeur par défaut`});
      head.appendChild(label);head.appendChild(stateEl);head.appendChild(reset);
      const meaning=el('p','jvi-meaning',row0.meaning||'');meaning.id=descId;meaning.hidden=!row0.meaning;
      const slot=el('div','jvi-ctl');
      const defaultEl=el('p','jvi-default');
      const msg=el('p','jvi-msg');msg.id=msgId;msg.hidden=true;
      [head,meaning,slot,defaultEl,msg].forEach((n)=>li.appendChild(n));
      ctx.chrome={li,label,stateEl,reset,msg,defaultEl,inputId,descId,msgId};
      const widget=makeWidget(ctx,slot,inputId);
      ctx.widget=widget;
      const api={el:li,ctx,update(row){
        ctx.row=row;
        label.textContent=row.label||row.control_id;
        label.title=`${row.control_id} · ${row.type}${row.is_set?'':' · par défaut'}`;
        meaning.textContent=row.meaning||'';meaning.hidden=!row.meaning;
        const s=sessions.get(row.control_id);
        const dirty=!!s&&s.dirty;
        if(!dirty)widget.set(row.current,row);
        widget.refresh(row);
        reset.disabled=!row.is_set||!!(s&&s.committing);
        stateEl.textContent=dirty?'aperçu · non enregistré':(row.is_set?'modifié':'par défaut');
        li.classList.toggle('is-dirty',dirty);
        /* Le défaut n'est dit que lorsqu'il diffère de ce qu'on voit : une valeur déjà par défaut le dit dans son état. */
        defaultEl.textContent=`Par défaut : ${formatValue(row,row.default)}`;
        defaultEl.hidden=!row.is_set||row.default===null||row.default===undefined||sameJson(row.default,row.current);
      },focus(){widget.focus()}};
      label.title=`${row0.control_id} · ${row0.type}`;
      api.update(row0);
      return api;
    }
    function setRowMessage(controlId,kind,text,actions){
      const w=widgets.get(controlId);if(!w)return;
      const c=w.ctx.chrome;
      clear(c.msg);
      c.msg.hidden=!text;
      c.msg.setAttribute('data-kind',kind==='bad'?'bad':kind);
      c.msg.setAttribute('role',kind==='bad'?'alert':'status');
      if(text)c.msg.appendChild(doc.createTextNode(text));
      for(const a of actions||[])c.msg.appendChild(button(a.label,'jvi-btn',a.run));
      c.li.classList.toggle('is-bad',kind==='bad'&&!!text);
      const input=w.ctx.widget&&w.ctx.widget.input;
      if(input){if(kind==='bad'&&text){input.setAttribute('aria-invalid','true');input.setAttribute('aria-describedby',c.msgId)}else{input.removeAttribute('aria-invalid');input.removeAttribute('aria-describedby')}}
    }
    /* Efface le message d'un réglage seulement s'il est de l'un de ces genres : une saisie corrigée efface son erreur, jamais l'avis
       de base périmée (il reste jusqu'à un enregistrement, un « Fermer » ou un changement de scène). */
    function clearRowMessage(id,kinds){
      const w=widgets.get(id);if(!w)return;
      const m=w.ctx.chrome.msg;
      if(m.hidden)return;
      if(kinds&&!kinds.includes(m.getAttribute('data-kind')))return;
      setRowMessage(id,'info','');
    }
    function flashSaved(controlId){
      const w=widgets.get(controlId);if(!w)return;
      const c=w.ctx.chrome;
      c.li.classList.add('is-saved');c.stateEl.textContent='enregistré';
      later(()=>{if(widgets.get(controlId)!==w)return;c.li.classList.remove('is-saved');w.update(w.ctx.row)},SAVED_FLASH_MS);
    }

    /* Les widgets (partie 2/3) ne reçoivent que trois gestes ; créés à la première ligne rendue (le DOM existe alors). */
    let widgetKit=null;
    function makeWidget(ctx,slot,inputId){
      if(!widgetKit)widgetKit=Widgets.createWidgets({doc,el,attrs,button,clear,sessionFor,setRowMessage,log});
      return widgetKit.makeWidget(ctx,slot,inputId,{preview:onPreview,commit:onCommit,idle:onIdle});
    }

    /* -------------------------------------------------------------- brouillons : aperçu, enregistrement */
    function sessionFor(ctx){
      const id=ctx.row.control_id;
      let s=sessions.get(id);
      if(!s){
        s={id,dirty:false,draft:undefined,pointer:false,previewTimer:null,idleTimer:null,inflight:false,latest:undefined,hasLatest:false,
          lastSentAt:-Infinity,lastSent:undefined,epoch:0,committing:false,previews:0};
        sessions.set(id,s);
      }
      return s;
    }
    function clearTimers(s){
      if(s.previewTimer!==null){cancelLater(s.previewTimer);s.previewTimer=null}
      if(s.idleTimer!==null){cancelLater(s.idleTimer);s.idleTimer=null}
    }
    function editable(){
      if(!S.available){return false}
      if(!S.variant||!S.scene)return false;
      return true;
    }
    function onPreview(ctx,value,opts){
      if(!editable())return;
      const row=ctx.row,s=sessionFor(ctx);
      const problem=validateValue(row,value);
      if(problem){setRowMessage(row.control_id,'bad',problem);clearTimers(s);return}
      clearRowMessage(row.control_id,['bad']);
      s.dirty=true;s.draft=value;s.latest=value;s.hasLatest=true;s.version=(s.version||0)+1;
      const w=widgets.get(row.control_id);if(w){w.ctx.chrome.li.classList.add('is-dirty');w.ctx.chrome.stateEl.textContent='aperçu · non enregistré'}
      syncPreview();          /* aperçu local immédiat : le cadre reçoit la valeur avant que Core réponde ; un refus la reprend */
      s.minMs=opts&&opts.text?TEXT_PREVIEW_MS:PREVIEW_MIN_MS;
      schedulePreview(ctx,s,s.minMs);
    }
    function schedulePreview(ctx,s,minMs){
      if(s.inflight)return;                      /* la réponse en attente relancera avec la dernière valeur */
      const wait=Math.max(0,s.lastSentAt+minMs-now());
      if(s.previewTimer!==null){stats.previewsCoalesced++;return}
      if(wait===0){sendPreview(ctx,s);return}
      s.previewTimer=later(()=>{s.previewTimer=null;sendPreview(ctx,s)},wait);
    }
    async function sendPreview(ctx,s){
      if(!s.hasLatest||s.inflight||s.committing)return;
      const value=s.latest;s.hasLatest=false;
      if(s.lastSent!==undefined&&sameJson(s.lastSent,value))return;
      s.inflight=true;s.lastSentAt=now();s.lastSent=value;s.previews++;stats.previews++;
      const epoch=s.epoch;
      try{
        const outcome=await postEdit('preview',[{op:'control.set',scene_id:S.sceneId,control_id:ctx.row.control_id,value}]);
        if(epoch!==s.epoch)return;               /* un enregistrement ou un abandon a tourné la page */
        if(outcome.kind==='applied'){clearRowMessage(ctx.row.control_id,['bad']);return}
        if(outcome.kind==='stale'){handleStale(ctx,s,value,'preview');return}
        if(outcome.kind==='refused'||outcome.kind==='error'){
          showRefusal(ctx,outcome,value);
          syncPreview();                          /* le cadre reprend la dernière valeur valide */
          return;
        }
        if(outcome.kind==='reloading'){setRowMessage(ctx.row.control_id,'warn','Scène en rechargement : l\'aperçu reprendra, l\'enregistrement attendra.')}
      }catch(error){
        if(epoch!==s.epoch)return;
        stats.failures++;
        setRowMessage(ctx.row.control_id,'bad',`Aperçu non validé : ${describe(error)}`);
        log('preview_failed',{control_id:ctx.row.control_id,code:error.code,error:describe(error)},'warn');
      }finally{
        s.inflight=false;
        if(epoch===s.epoch&&s.hasLatest)schedulePreview(ctx,s,s.minMs||PREVIEW_MIN_MS);
      }
    }
    /* Clavier et ± : le dernier appui arme un seul enregistrement après une courte pause. */
    function onIdle(ctx,value){
      onPreview(ctx,value);
      const s=sessionFor(ctx);
      if(s.idleTimer!==null)cancelLater(s.idleTimer);
      s.idleTimer=later(()=>{s.idleTimer=null;if(s.dirty&&s.draft!==undefined)onCommit(ctx,s.draft,{immediate:true})},IDLE_COMMIT_MS);
    }
    function onCommit(ctx,value,opts){
      if(!editable())return Promise.resolve(null);
      const row=ctx.row,s=sessionFor(ctx);
      clearTimers(s);
      s.epoch++;s.hasLatest=false;
      const problem=validateValue(row,value);
      if(problem){
        setRowMessage(row.control_id,'bad',`${problem} Rien n'a été enregistré.`);
        return Promise.resolve(null);
      }
      /* Un enregistrement de ce réglage est en vol : `row.current` est périmé, c'est `runCommit` qui compare à la valeur relue. */
      if(!s.committing&&sameJson(value,row.current)){
        s.dirty=false;s.draft=undefined;
        clearRowMessage(row.control_id,['bad']);
        const w=widgets.get(row.control_id);if(w)w.update(row);
        syncPreview();
        return Promise.resolve(null);
      }
      s.dirty=true;s.draft=value;
      const ver=s.version=(s.version||0)+1;
      return enqueue(row.control_id,(task)=>runCommit(ctx,s,value,task,'set',ver),`Enregistrement de « ${row.label} »`);
    }
    function resetControl(row){
      if(!editable())return;
      const ctx={row};
      const w=widgets.get(row.control_id);
      const s=sessionFor(w?w.ctx:ctx);
      clearTimers(s);s.epoch++;s.hasLatest=false;s.dirty=true;s.draft=row.default;
      const ver=s.version=(s.version||0)+1;
      enqueue(row.control_id,(task)=>runCommit(w?w.ctx:ctx,s,row.default,task,'reset',ver),`Rétablissement de « ${row.label} »`);
    }
    function revertDraft(ctx){
      const s=sessions.get(ctx.row.control_id);
      if(s){clearTimers(s);s.epoch++;s.dirty=false;s.draft=undefined;s.hasLatest=false}
      const w=widgets.get(ctx.row.control_id);
      if(w){w.ctx.widget.set(ctx.row.current,ctx.row);w.update(ctx.row)}
      setRowMessage(ctx.row.control_id,'info','');
      syncPreview();
      announce(`${ctx.row.label} : modification abandonnée.`);
    }
    function abandonDrafts(reason){
      for(const s of sessions.values()){clearTimers(s);s.epoch++;s.dirty=false;s.draft=undefined;s.hasLatest=false}
      if(sessions.size)log('drafts_abandoned',{count:sessions.size,reason});
      sessions.clear();
      for(const task of queue.pending.values())task.superseded=true;
      queue.pending.clear();
      if(S.reloading){S.reloading=null;renderStatus()}
    }

    /* File d'écritures : UNE à la fois (la base `variant_revision` avance à chaque succès) ; une écriture encore en attente pour le
       même réglage est remplacée par la plus récente. */
    function enqueue(key,run,label){
      const prior=queue.pending.get(key);
      if(prior){prior.superseded=true;stats.writesSuperseded++;if(prior.wake)prior.wake()}
      const task={key,superseded:false,label};
      queue.pending.set(key,task);
      const job=queue.tail.then(()=>{
        if(task.superseded)return null;
        return run(task);
      }).catch((error)=>{log('queue_failed',{key,error:describe(error)},'error');return null})
        .finally(()=>{if(queue.pending.get(key)===task)queue.pending.delete(key)});
      queue.tail=job;
      return job;
    }

    async function postEdit(mode,ops){
      const response=await call(`${variantBase()}/edits`,{method:'POST',timeoutMs:REQUEST_TIMEOUT_MS,
        body:{mode,basis:{variant_revision:S.scene?S.scene.variant_revision:S.variant.revision},ops}});
      return classifyEdit(response);
    }
    function classifyEdit(response){
      const body=response.body;
      if(body&&typeof body.status==='string'&&(body.status==='applied'||body.status==='refused'||body.status==='stale')){
        if(body.status==='applied')return {kind:'applied',result:body};
        if(body.status==='stale')return {kind:'stale',result:body,code:body.code,message:body.message};
        return {kind:'refused',result:body,code:body.code,message:body.message};
      }
      const e=envelopeOf(response);
      if(e.code==='presentation_studio_scene_reloading')return {kind:'reloading',code:e.code,message:e.message};
      return {kind:'error',code:e.code,message:e.message,http:e.http};
    }

    async function runCommit(ctx,s,value,task,why,ver){
      const id=ctx.row.control_id;
      s.committing=true;
      const w0=widgets.get(id);if(w0){w0.ctx.chrome.li.classList.add('is-busy');w0.ctx.chrome.reset.disabled=true}
      try{
        let attempt=0;
        for(;;){
          if(task.superseded){return null}
          /* L'opération est construite ICI, à partir de la valeur relue après l'enregistrement précédent : jamais sur la base que
             notre propre écriture vient de périmer (une file de pas de clavier ne se rend pas `stale` à elle-même). */
          const fresh=widgets.get(id);
          const row=fresh?fresh.ctx.row:ctx.row;
          if(why!=='reset'&&sameJson(value,row.current)){
            if(s.version===ver){s.dirty=false;s.draft=undefined}
            return null;
          }
          const op=why==='reset'?{op:'control.reset',scene_id:S.sceneId,control_id:id,if_current:row.current}:
            {op:'control.set',scene_id:S.sceneId,control_id:id,value,if_current:row.current};
          let outcome;
          try{
            outcome=await postEdit('commit',[op]);
          }catch(error){
            stats.failures++;
            restoreDisplay(id);
            setRowMessage(id,'bad',`Enregistrement impossible : ${describe(error)}`,[{label:'Réessayer',run:()=>retryCommit(ctx,value,why)}]);
            log('commit_failed',{control_id:id,code:error.code,error:describe(error)},'error');
            tell('Enregistrement impossible',describe(error),'bad');
            return null;
          }
          if(outcome.kind==='reloading'){
            if(attempt>=RELOAD_RETRY_MS.length){
              S.reloading=null;renderStatus();restoreDisplay(id);
              setRowMessage(id,'bad','La scène est restée en rechargement trop longtemps. Rien n\'a été enregistré.',[{label:'Réessayer',run:()=>retryCommit(ctx,value,why)}]);
              log('reload_gave_up',{control_id:id,attempts:attempt},'error');
              tell('Scène en rechargement','Modification non enregistrée : réessayez dans un instant.','bad');
              return null;
            }
            const delay=RELOAD_RETRY_MS[attempt];attempt++;stats.reloadRetries++;
            const wait=S.reloading={attempt,max:RELOAD_RETRY_MS.length,nextAt:now()+delay,cancelled:false,wake:null};
            task.wake=()=>{if(wait.wake)wait.wake()};
            renderStatus();
            log('reload_wait',{control_id:id,attempt,delay_ms:delay},'warn');
            announce(`Scène en rechargement, nouvelle tentative ${attempt} sur ${RELOAD_RETRY_MS.length}.`);
            await new Promise((resolve)=>{wait.wake=resolve;later(resolve,delay)});
            task.wake=null;
            if(task.superseded||wait.cancelled){S.reloading=null;renderStatus();
              if(!task.superseded){restoreDisplay(id);setRowMessage(id,'warn','Attente arrêtée : rien n\'a été enregistré.',[{label:'Réessayer',run:()=>retryCommit(ctx,value,why)}])}
              return null}
            continue;
          }
          S.reloading=null;renderStatus();
          return await finishCommit(ctx,s,op,value,outcome,ver);
        }
      }finally{
        s.committing=false;
        const w=widgets.get(id);if(w){w.ctx.chrome.li.classList.remove('is-busy');w.ctx.chrome.reset.disabled=!w.ctx.row.is_set}
      }
    }
    function retryCommit(ctx,value,why){
      const w=widgets.get(ctx.row.control_id);
      const row=w?w.ctx.row:ctx.row;
      setRowMessage(row.control_id,'info','');
      if(why==='reset')resetControl(row);else onCommit(w?w.ctx:ctx,value,{immediate:true});
    }
    /* Rien n'a été enregistré : le widget montre de nouveau la valeur de Core (jamais celle d'un brouillon abandonné). */
    function restoreDisplay(id){
      const s=sessions.get(id);
      if(s){s.dirty=false;s.draft=undefined;s.hasLatest=false;s.lastSent=undefined}
      const w=widgets.get(id);
      if(w){w.ctx.widget.set(w.ctx.row.current,w.ctx.row);w.update(w.ctx.row)}
      syncPreview();
    }
    function giveUpReload(){
      if(!S.reloading)return;
      const wait=S.reloading;
      wait.cancelled=true;
      if(wait.wake)wait.wake();
      log('reload_wait_cancelled',{attempt:wait.attempt},'warn');
      S.reloading=null;renderStatus();
    }
    async function finishCommit(ctx,s,op,value,outcome,ver){
      const id=ctx.row.control_id;
      const latest=s.version===ver;      /* sinon l'utilisateur a continué de régler pendant l'écriture : son brouillon reste */
      if(outcome.kind==='applied'){
        const result=outcome.result;
        stats.commits++;
        const previews=s.previews;s.previews=0;
        if(latest){s.dirty=false;s.draft=undefined}
        s.lastSent=undefined;
        log('commit_applied',{control_id:id,op:op.op,revision:result.revision,changed:!!result.changed,previews});
        setRowMessage(id,'info','');
        await Promise.all([loadScene({quiet:true}),loadHistory()]);
        flashSaved(id);
        announce(`${ctx.row.label} : enregistré.`);
        return result;
      }
      if(outcome.kind==='stale'){return handleStale(ctx,s,value,'commit',op,ver)}
      if(outcome.kind==='refused'||outcome.kind==='error'){
        if(latest){s.dirty=false;s.draft=undefined}
        s.lastSent=undefined;
        showRefusal(ctx,outcome,value);
        if(outcome.code==='presentation_studio_unknown_control'||outcome.code==='presentation_studio_unknown_scene'||outcome.code==='presentation_studio_scene_incompatible'){
          await loadScene({quiet:true});
        }else if(latest){
          const w=widgets.get(id);if(w){w.ctx.widget.set(w.ctx.row.current,w.ctx.row);w.update(w.ctx.row)}
          syncPreview();
        }
        return null;
      }
      return null;
    }
    function showRefusal(ctx,outcome,value){
      const id=ctx.row.control_id;
      const text=describeRefusal(outcome.code,outcome.message);
      stats.failures++;
      setRowMessage(id,'bad',text);
      log('edit_refused',{control_id:id,code:outcome.code,status:outcome.kind,http:outcome.http||null},'warn');
      announce(`${ctx.row.label} : ${text}`);
      if(outcome.kind==='error'&&(outcome.http>=500||!outcome.http))tell('Modification refusée',text,'bad');
    }
    /* Base périmée (ou valeur modifiée ailleurs) : relire, dire ce qui a changé, ne rien écraser. */
    async function handleStale(ctx,s,value,phase,op,ver){
      const id=ctx.row.control_id;
      stats.staleHandled++;
      clearTimers(s);s.epoch++;s.hasLatest=false;
      if(ver===undefined||s.version===ver){s.dirty=false;s.draft=undefined}      /* avant la relecture : le widget reprend la valeur de Core */
      s.lastSent=undefined;
      const diff=await loadScene({quiet:true});
      await loadHistory();
      const changes=diff?diffControls(diff.before,diff.after):[];
      const mine=changes.find((c)=>c.control_id===id);
      /* La révision a bougé sans qu'AUCUN réglage ne change (rechargement de source, DA, voix sur autre chose) : ce n'est pas un conflit.
         On repart une fois, sur la base relue : `if_current` protège de toute façon la valeur de ce réglage. */
      if(phase==='commit'&&diff&&!changes.length&&!s.rebased){
        s.rebased=true;
        log('stale_rebased',{control_id:id});
        const wr=widgets.get(id);
        /* Pas d'attente ici : on est DANS la tâche de la file, la nouvelle écriture passera derrière elle (attendre serait un interblocage). */
        onCommit(wr?wr.ctx:ctx,value,{immediate:true}).then(()=>{s.rebased=false},()=>{s.rebased=false});
        return null;
      }
      const w=widgets.get(id);
      const now_=w?w.ctx.row:ctx.row;
      const lines=changes.slice(0,5).map((c)=>`${c.label} : ${formatValue(null,c.before)} → ${formatValue(null,c.after)}`);
      const more=changes.length>5?` (+${changes.length-5} autres)`:'';
      const read_=lines.length?`Valeurs relues : ${lines.join(' ; ')}${more}.`:'Valeurs relues (aucune différence sur cette scène).';
      const text=phase==='commit'?`La présentation a changé ailleurs avant votre réglage : il n'a pas été appliqué. ${read_}`:
        `La présentation a changé ailleurs pendant votre réglage. ${read_}${mine?' Votre réglage en cours repart de la valeur relue.':''}`;
      const reapply=phase==='commit'&&!sameJson(value,now_.current);
      const actions=reapply?[{label:`Réappliquer ma valeur (${formatValue(now_,value)})`,run:()=>{setRowMessage(id,'info','');
        const wx=widgets.get(id);onCommit(wx?wx.ctx:ctx,value,{immediate:true})}}]:[];
      actions.push({label:'Fermer',run:()=>setRowMessage(id,'info','')});
      setRowMessage(id,'warn',text,actions);
      log('edit_stale',{control_id:id,phase,changed:changes.map((c)=>c.control_id)},'warn');
      tell('Modification périmée',lines[0]||'Les valeurs ont été relues.','warn');
      announce('La présentation a changé ailleurs : valeurs relues.');
      return null;
    }

    /* -------------------------------------------------------------- annuler, rétablir */
    /* Abandonne tout brouillon en attente (aperçu rendu, minuteries coupées) ; un enregistrement déjà parti n'est pas un brouillon. */
    function discardDrafts(){
      for(const s of sessions.values()){
        clearTimers(s);s.epoch++;
        if(s.dirty&&!s.committing){
          const w=widgets.get(s.id);
          if(w)revertDraft(w.ctx);
          else{s.dirty=false;s.draft=undefined;s.hasLatest=false}
        }
      }
    }
    async function runHistory(direction){
      if(!S.variant||!S.available)return;
      const h=S.history,entry=h&&(direction==='undo'?h.next_undo:h.next_redo);
      discardDrafts();      /* règle : annuler / rétablir abandonne d'abord les brouillons en attente, jamais ils ne s'enregistrent après */
      const body={};
      if(entry&&entry.entry_id)body.expected_entry_id=entry.entry_id;
      stats[direction]++;
      ui.undo.disabled=true;ui.redo.disabled=true;
      setStatus('info',direction==='undo'?'Annulation…':'Rétablissement…','');
      let attempt=0;
      try{
        for(;;){
          const response=await call(`${variantBase()}/${direction}`,{method:'POST',body,timeoutMs:REQUEST_TIMEOUT_MS});
          const result=response.body;
          if(result&&typeof result.status==='string'&&(result.status==='applied'||Object.prototype.hasOwnProperty.call(HISTORY_TEXT,result.status))){
            if(result.status==='applied'){
              log('history_applied',{direction,revision:result.revision});
              setStatus(null);
              await Promise.all([loadScene({quiet:true}),loadHistory()]);
              setStatus('ok',direction==='undo'?'Modification annulée':'Modification rétablie','');
              later(()=>{if(S.status&&S.status.kind==='ok')setStatus(null)},4000);
              announce(direction==='undo'?'Modification annulée.':'Modification rétablie.');
              return result;
            }
            const text=`${HISTORY_TEXT[result.status]}.${result.message?' '+clip(result.message,300):''}`;
            log('history_not_applied',{direction,status:result.status,reason:result.reason||null,code:result.code||null},'warn');
            setStatus(result.status==='stale'?'warn':'info',direction==='undo'?'Annulation impossible':'Rétablissement impossible',text);
            announce(text);
            if(result.status==='stale'||result.status==='refused')await Promise.all([loadScene({quiet:true}),loadHistory()]);
            else await loadHistory();
            return result;
          }
          const e=envelopeOf(response);
          if(e.code==='presentation_studio_scene_reloading'&&attempt<RELOAD_RETRY_MS.length){
            const delay=RELOAD_RETRY_MS[attempt];attempt++;stats.reloadRetries++;
            const wait=S.reloading={attempt,max:RELOAD_RETRY_MS.length,nextAt:now()+delay,cancelled:false,wake:null};
            renderStatus();log('reload_wait',{direction,attempt,delay_ms:delay},'warn');
            await new Promise((resolve)=>{wait.wake=resolve;later(resolve,delay)});
            if(wait.cancelled){S.reloading=null;setStatus('warn','Attente arrêtée','Rien n\'a été annulé.');return null}
            continue;
          }
          S.reloading=null;
          setStatus('bad',direction==='undo'?'Annulation impossible':'Rétablissement impossible',describeRefusal(e.code,e.message));
          log('history_failed',{direction,code:e.code,http:e.http},'error');
          return null;
        }
      }catch(error){
        stats.failures++;
        setStatus('bad','Core ne répond pas',describe(error),[{label:'Réessayer',run:()=>{runHistory(direction)}}]);
        log('history_failed',{direction,code:error.code,error:describe(error)},'error');
        tell('Annuler / rétablir impossible',describe(error),'bad');
        return null;
      }finally{
        S.reloading=null;renderStatus();renderHistory();
      }
    }

    /* -------------------------------------------------------------- aperçu local (cadre sandboxé, mode preview) */
    function ensureHost(){
      if(previewHost)return previewHost;
      const api=d.prefabHost||root.JarvisPrefabHost;
      if(!api||typeof api.createPrefabHost!=='function')return null;
      try{
        previewHost=api.createPrefabHost({mode:'preview',document:doc,window:win,
          fetchBundle:api.bundleFetcher((path,options)=>fetchImpl(path,Object.assign({cache:'no-store'},options))),
          onPreviewEvent:()=>{/* intentional: the preview frame writes nothing anywhere; its events are dropped */},
          log:(key,data)=>{if(key!=='scene.prefab_mounted')log('preview_host_'+String(key).replace(/^scene\./,''),data,'warn')}});
      }catch(error){
        log('preview_host_failed',{error:describe(error)},'error');previewHost=null;
      }
      return previewHost;
    }
    function unmountPreview(){
      if(previewHost&&previewMounted){try{previewHost.unmount(PREVIEW_OBJECT_ID)}catch(_error){/* intentional: the frame is gone either way */}}
      previewMounted=null;
      if(ui.slot)clear(ui.slot);
    }
    function syncPreview(){
      if(!ui.stage)return;
      const scene=S.scene;
      ui.stage.hidden=!scene||!storedScene;
      if(!scene||!storedScene||!S.open||!S.available){return}
      ui.stage.open=S.showPreview;
      if(!S.showPreview)return;
      const host=ensureHost();
      if(!host){ui.stageNote.textContent='Aperçu indisponible : le runtime des prefabs n\'est pas chargé dans cette page.';return}
      const live=[];
      for(const s of sessions.values()){
        if(s.dirty&&s.draft!==undefined){const w=widgets.get(s.id);if(w)live.push({path:w.ctx.row.path,value:s.draft})}
      }
      const values=previewValues(storedScene,scene.controls,live);
      const pin=scene.prefab||storedScene.prefab;
      if(!pin)return;
      ui.stageSummary.textContent=`Aperçu local · ${clip(scene.title||storedScene.title||'scène',40)}`;
      try{
        host.mount(ui.slot,{object_id:PREVIEW_OBJECT_ID,prefab:{id:pin.id,version:pin.version},title:scene.title||'',props:values.props,data:values.data});
        previewMounted=pin;
      }catch(error){
        ui.stageNote.textContent=`Aperçu impossible : ${describe(error)}`;
        log('preview_mount_failed',{error:describe(error)},'error');
      }
    }

    /* -------------------------------------------------------------- clavier */
    function inTextField(target){
      if(!target)return false;
      const tag=String(target.tagName||'').toUpperCase();
      if(tag==='TEXTAREA')return true;
      if(tag!=='INPUT')return false;
      return !['range','color','checkbox','radio','button'].includes(String(target.type||'').toLowerCase());
    }
    function onPanelKey(event){
      const key=event.key;
      const mod=event.ctrlKey||event.metaKey;
      if(mod&&!event.altKey&&(key==='z'||key==='Z'||key==='y'||key==='Y')){
        const target=event.target;
        const s=target&&target.closest?target.closest('[data-control-id]'):null;
        const id=s?s.getAttribute('data-control-id'):null;
        const dirty=id&&sessions.get(id)&&sessions.get(id).dirty;
        if(inTextField(target)&&dirty)return;          /* l'annulation du champ est celle du navigateur tant qu'il est modifié */
        event.preventDefault();event.stopPropagation();
        if(dirty&&widgets.get(id)){revertDraft(widgets.get(id).ctx);return}      /* règle : Ctrl+Z avec un brouillon en attente l'abandonne d'abord */
        const redo=key==='y'||key==='Y'||event.shiftKey;
        runHistory(redo?'redo':'undo');
        return;
      }
      if(key==='Escape'){
        event.preventDefault();event.stopPropagation();
        const row=event.target&&event.target.closest?event.target.closest('[data-control-id]'):null;
        const id=row?row.getAttribute('data-control-id'):null;
        const s=id?sessions.get(id):null;
        if(s&&s.dirty&&widgets.get(id)){revertDraft(widgets.get(id).ctx);return}     /* d'abord abandonner le brouillon, ensuite fermer */
        close({restoreFocus:true});
        return;
      }
      /* Aucune touche non modifiée ne sort du panneau : ni raccourcis de la page (s, e, t, a…), ni navigation de la scène. Tab reste libre. */
      if(!mod&&!event.altKey&&key!=='Tab'&&!/^F\d{1,2}$/.test(key))event.stopPropagation();
    }

    /* -------------------------------------------------------------- disponibilité (lecture, plein écran) */
    function checkAvailability(){
      let reason=null;
      try{
        if(inFullscreen())reason='fullscreen';
        else if(playing())reason='playback';
      }catch(error){log('availability_failed',{error:describe(error)},'warn')}
      const available=reason===null;
      if(available===S.available&&reason===S.hiddenReason)return;
      S.available=available;S.hiddenReason=reason;
      applyAvailability();
    }
    function applyAvailability(){
      if(ui.dock){
        ui.dock.disabled=!S.available;
        ui.dock.setAttribute('aria-disabled',String(!S.available));
        ui.dock.title=S.available?'Inspecteur · réglages de la présentation':
          (S.hiddenReason==='fullscreen'?'Inspecteur masqué : plein écran':'Inspecteur masqué pendant une présentation');
      }
      syncExplore();
      if(!ui.root)return;
      if(!S.available){
        stats.hiddenByPlayback++;
        close({});                       /* ferme, abandonne les brouillons, rend le cadre d'aperçu et coupe la relève */
        ui.root.hidden=true;ui.root.inert=true;
        log('hidden',{reason:S.hiddenReason});
      }else{
        ui.root.inert=false;ui.root.hidden=!S.open;
        log('available',{});
      }
    }
    function startPolling(){if(pollTimer===null)pollTimer=every(()=>{pollReloads()},POLL_MS)}
    function stopPolling(){if(pollTimer!==null){stopEvery(pollTimer);pollTimer=null}}

    /* -------------------------------------------------------------- ouverture */
    function open(options){
      if(!S.available){
        log('open_refused',{reason:S.hiddenReason},'warn');
        tell('Inspecteur indisponible',S.hiddenReason==='fullscreen'?'Quittez le plein écran pour régler la présentation.':'Arrêtez la présentation en cours pour la régler.','warn');
        return false;
      }
      build();
      const p=prefs();
      if(typeof p.tab==='string'&&GROUPS.includes(p.tab))S.tab=p.tab;
      /* Sans préférence enregistrée, l'aperçu démarre replié sur un écran bas (il laisserait une seule ligne de réglage). */
      S.showPreview=p.preview!==undefined?p.preview!==false:(Number(win.innerHeight)||720)>=700;
      try{const player=root.JarvisStudioPlayer;if(player&&typeof player.refresh==='function')Promise.resolve(player.refresh()).then(checkAvailability,()=>{})}catch(_error){/* intentional: the periodic check follows */}
      checkAvailability();
      if(!S.available)return false;
      S.open=true;
      ui.root.hidden=false;ui.root.inert=false;
      if(ui.dock){ui.dock.classList.add('active');ui.dock.setAttribute('aria-expanded','true')}
      const closeSidePanel=typeof d.closeSidePanel==='function'?d.closeSidePanel:(typeof root.closePanel==='function'?root.closePanel:null);
      if(closeSidePanel){try{closeSidePanel()}catch(_error){/* intentional: the side panel closing is a courtesy */}}
      ui.stage.open=S.showPreview;
      startPolling();
      log('opened',{});
      loadPresentations().then(()=>{if(!(options&&options.noFocus)&&ui.title)ui.title.focus()});
      return true;
    }
    function close(options){
      if(!S.open&&!(ui.root&&!ui.root.hidden))return;
      abandonDrafts('close');
      S.open=false;
      stopPolling();
      unmountPreview();
      if(ui.root)ui.root.hidden=true;
      if(ui.dock){ui.dock.classList.remove('active');ui.dock.setAttribute('aria-expanded','false')}
      if(options&&options.restoreFocus&&ui.dock&&!ui.dock.disabled)ui.dock.focus();
      log('closed',{});
    }
    function toggle(){S.open?close({restoreFocus:true}):open()}

    function install(){
      ui.dock=doc.getElementById(BUTTON_ID);
      build();
      if(ui.dock){
        ui.dock.addEventListener('click',toggle);
      }
      /* Ouvrir un panneau latéral (ERR, TRC, AGT) occupe le même emplacement : l'inspecteur se range. */
      if(typeof doc.querySelectorAll==='function'){
        for(const b of doc.querySelectorAll('.dock button[data-panel]'))b.addEventListener('click',()=>{if(S.open)close({})},true);
      }
      if(typeof doc.addEventListener==='function'){
        doc.addEventListener('fullscreenchange',checkAvailability);
        /* Le lecteur dit tout de suite qu'une lecture commence ou finit (il l'apprend par son relevé) : pas d'attente du prochain tour de 500 ms. */
        if(typeof win.addEventListener==='function'){win.addEventListener(PLAYBACK_EVENT,checkAvailability);win.addEventListener('jarvis:studio-explorer-closed',onExplorerClosed)}
        doc.addEventListener('visibilitychange',()=>{if(S.open&&!doc.hidden)pollReloads()});
      }
      availTimer=every(checkAvailability,AVAILABILITY_MS);
      checkAvailability();
      log('installed',{dock:!!ui.dock});
    }
    function destroy(){
      close({});
      if(availTimer!==null){stopEvery(availTimer);availTimer=null}
      if(previewHost&&typeof previewHost.destroy==='function')previewHost.destroy();
    }

    const view=()=>({open:S.open,available:S.available,hiddenReason:S.hiddenReason,presentation_id:S.presentationId,
      variant_id:S.variant&&S.variant.variant_id,revision:S.scene?S.scene.variant_revision:(S.variant&&S.variant.revision),scene_id:S.sceneId,
      tab:S.tab,controls:S.scene?(S.scene.controls||[]).map((r)=>({control_id:r.control_id,current:r.current,is_set:r.is_set})):[],
      reloading:S.reloading?{attempt:S.reloading.attempt,max:S.reloading.max}:null,history:S.history?{undo:S.history.undo_count,redo:S.history.redo_count}:null,
      art:{state:S.art.state,revision:S.art.revision},loading:!!S.loading,fatal:S.fatal?S.fatal.code:null,
      pendingDrafts:[...sessions.values()].filter((s)=>s.dirty).map((s)=>s.id)});

    return Object.freeze({install,open,close,toggle,destroy,view,stats:()=>Object.assign({},stats),refresh:()=>loadPresentations(),
      checkAvailability,pollReloads,selectScene:chooseScene,selectTab,runHistory,loadScene,
      widget:(id)=>widgets.get(id)||null,element:()=>ui.root,dockButton:()=>ui.dock,previewHost:()=>previewHost});
  }

  const api={ROUTE,GROUPS,GROUP_LABEL,PANEL_ID,BUTTON_ID,STYLE_ID,STORAGE_KEY,PREVIEW_MIN_MS,TEXT_PREVIEW_MS,IDLE_COMMIT_MS,RELOAD_RETRY_MS,POLL_MS,
    APPLIED_THEME,NOT_APPLIED_THEME,PLAYBACK_EVENT,CSS,InspectorError,createStudioInspector,widgetSpec,stepFor,validateValue,setAtPath,previewValues,
    diffControls,contrastRatio,describeRefusal,formatValue,roundTo,sameJson,canonical,instance:null};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root.document&&typeof root.fetch==='function'&&root.document.getElementById){
    try{
      api.instance=createStudioInspector({});
      api.instance.install();
    }catch(error){
      if(root.console)root.console.error('[studio-inspector] not_installed '+JSON.stringify({error:describe(error)}));
    }
  }
  root.JarvisStudioInspector=api;
})(typeof globalThis!=='undefined'?globalThis:this);
