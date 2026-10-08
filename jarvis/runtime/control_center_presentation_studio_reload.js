/* Rechargement à chaud d'une scène du Studio, côté page (handoff jarvis-interactive-presentation-studio, Slice 06).
   Module DOM exposé en `window.JarvisStudioReload` dans la page et en `module.exports` pour node.

   Ce que ce module est, et n'est pas :
   - il N'EST PAS un second hôte, ni un second chemin vers le document d'un cadre : les cadres sont montés par
     `control_center_prefab_host.js`, qui reste le seul fichier à le poser. Il ne touche ni `sandbox`, ni la CSP, ni le
     protocole `jv:1` ; le cadre ne reçoit aucun droit de plus ;
   - il fait remonter à Core ce que l'hôte a OBSERVÉ pour un cadre `presentation-studio.*` (`hostOutcome`, branché sur
     `createPrefabHost({onOutcome})`) : `mounted` ou `failed` + raison courte + message du cadre (non fiable : jamais
     inséré comme balisage, toujours `textContent`). Core s'en sert pour confirmer une nouvelle source ou la ramener à la
     dernière version valide ;
   - il applique une édition de source (`applySourceEdit`) par le relais (acteur `user` imposé côté serveur) et rend
     VISIBLE tout ce qui peut arriver (RULE ZERO) : « en cours » avec un compteur vivant et une échéance, puis l'issue
     exacte de Core — rechargée, rechargée avec valeurs remises à zéro (les noms sont listés), enregistrée sans fenêtre,
     sans confirmation, refusée avant publication, revenue en arrière, périmée — ou la vraie panne de transport avec
     « Réessayer ». Chaque issue est journalisée dans la console (`[studio-reload]`) et l'interface est toujours rendue
     (`finally`) ;
   - il ne garde AUCUN état de présentation : le contexte (variante, scène, sélection de l'éditeur, position de partition)
     appartient à l'appelant ; `applySourceEdit` ne met à jour que `state.revision` de l'objet qu'on lui passe, et ne
     touche à rien d'autre (sélection, position) ;
   - `watch(presentationId)` surveille `GET .../reloads` pour montrer à l'utilisateur ce qu'il n'a pas lancé lui-même (une
     édition de la voix, un retour arrière tardif après le premier montage d'une scène). Il ne montre jamais l'historique
     au premier relevé.

   Clés : aucune écriture par clé dynamique dans un objet simple (les noms de propriétés des prefabs peuvent valoir
   `__proto__` ; QA S04/S05) — les listes de noms ne sont que lues et affichées. */
(function(root){
  'use strict';

  const ROUTE='/api/presentation-studio/presentations';
  const REPORT_ROUTE=ROUTE+'/mount-reports';
  const STUDIO_PREFIX='presentation-studio.';
  const STATUSES=Object.freeze(['reloaded','reloaded_state_reset','repinned','pending_mount','refused_validation','rolled_back','stale','degraded']);
  const OUTCOMES=Object.freeze(['mounted','failed']);
  const EDIT_TIMEOUT_MS=50000;
  const REPORT_TIMEOUT_MS=10000;
  const REPORT_ATTEMPTS=3;
  const REPORT_RETRY_MS=1000;
  const OK_DISMISS_MS=6000;
  const WATCH_MS=3000;
  const WATCH_SEEN_CAP=128;
  const MAX_MESSAGE=300;
  const BAND_ID='jvStudioReloadBand';
  const STYLE_ID='jv-studio-reload-style';
  const REASON=/^[a-z][a-z0-9_]{0,39}$/;
  const CSS=`
#${BAND_ID}{position:fixed;left:50%;bottom:18px;transform:translateX(-50%);z-index:75;box-sizing:border-box;display:grid;grid-template-columns:auto minmax(0,1fr) auto;
  gap:4px 10px;align-items:start;width:min(520px,calc(100vw - 36px));padding:10px 10px 10px 12px;background:var(--solid,#070d13);
  color:var(--text,#d8edf7);border:1px solid var(--line,#183343);border-left:3px solid var(--accent,#6ee7ff);border-radius:8px;
  box-shadow:0 14px 40px rgba(0,0,0,.55);font:13px/1.45 system-ui,sans-serif}
#${BAND_ID}[data-kind=ok]{border-left-color:var(--ok,#68e0a0)}
#${BAND_ID}[data-kind=warn]{border-left-color:var(--warn,#ffb85c)}
#${BAND_ID}[data-kind=bad]{border-left-color:var(--danger,#ff6577)}
#${BAND_ID} .jvsr-spin{width:12px;height:12px;margin-top:4px;border:2px solid var(--line,#183343);border-top-color:var(--accent,#6ee7ff);border-radius:50%;
  animation:jvsrSpin .9s linear infinite}
#${BAND_ID}[data-phase=done] .jvsr-spin{display:none}
#${BAND_ID} .jvsr-dot{display:none;width:8px;height:8px;margin-top:7px;border-radius:50%;background:var(--accent,#6ee7ff)}
#${BAND_ID}[data-phase=done] .jvsr-dot{display:block}
#${BAND_ID}[data-kind=ok] .jvsr-dot{background:var(--ok,#68e0a0)}
#${BAND_ID}[data-kind=warn] .jvsr-dot{background:var(--warn,#ffb85c)}
#${BAND_ID}[data-kind=bad] .jvsr-dot{background:var(--danger,#ff6577)}
#${BAND_ID} .jvsr-body{min-width:0;overflow-wrap:anywhere}
#${BAND_ID} .jvsr-title{display:block;font-weight:600}
#${BAND_ID} .jvsr-text{display:block;color:var(--text,#d8edf7)}
#${BAND_ID} .jvsr-clock{display:block;color:var(--muted,#7190a0);font:11.5px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace}
#${BAND_ID} .jvsr-names{margin:4px 0 0;padding:0 0 0 16px;color:var(--muted,#7190a0);font:11.5px/1.45 ui-monospace,SFMono-Regular,Consolas,monospace}
#${BAND_ID} .jvsr-actions{display:flex;gap:6px;align-items:start}
#${BAND_ID} button{appearance:none;padding:3px 9px;border:1px solid var(--line,#183343);border-radius:5px;background:transparent;color:inherit;font:inherit;cursor:pointer}
#${BAND_ID} button:hover{background:rgba(110,231,255,.1)}
#${BAND_ID} button:focus-visible{outline:2px solid var(--accent,#6ee7ff);outline-offset:1px}
@keyframes jvsrSpin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){#${BAND_ID} .jvsr-spin{animation:none;border-top-color:var(--accent,#6ee7ff);border-style:dotted}}
`;

  function describe(error){
    return error&&typeof error==='object'&&typeof error.message==='string'?error.message:String(error);
  }

  function clip(text,limit){
    const value=String(text==null?'':text).replace(/[\u0000-\u001f\u007f]+/g,' ').trim();
    return value.length>limit?value.slice(0,limit-1)+'…':value;
  }

  function isResult(body){
    return !!body&&typeof body==='object'&&typeof body.status==='string'&&STATUSES.includes(body.status)&&'prefab' in body;
  }

  class StudioReloadError extends Error{
    constructor(message,code,status){super(message);this.name='StudioReloadError';this.code=code||'unreachable';this.status=status||0}
  }

  function createStudioReload(deps){
    const d=deps||{};
    const doc=d.document||root.document;
    const win=d.window||root;
    const fetchImpl=d.fetch||(typeof root.fetch==='function'?root.fetch.bind(root):null);
    const later=d.setTimeout||((fn,ms)=>setTimeout(fn,ms));
    const cancelLater=d.clearTimeout||((id)=>clearTimeout(id));
    const every=d.setInterval||((fn,ms)=>setInterval(fn,ms));
    const stopEvery=d.clearInterval||((id)=>clearInterval(id));
    const now=d.now||(()=>Date.now());
    const notify=typeof d.toast==='function'?d.toast:(typeof root.toast==='function'?root.toast:null);
    const counters={reportsSent:0,reportsFailed:0,edits:0,failures:0,bands:0,toasts:0};
    let band=null,dismissTimer=null,clockTimer=null,busy=null,watcher=null;

    function log(key,data,level){
      const line=`[studio-reload] ${key} ${JSON.stringify(data||{})}`;
      try{
        const sink=d.console||root.console;
        if(!sink)return;
        if(level==='error')sink.error(line);else if(level==='warn')sink.warn(line);else sink.info(line);
      }catch(_error){/* intentional: a broken console never breaks the page */}
    }

    function tell(title,sub,kind){
      if(!notify)return;
      counters.toasts++;
      try{notify({title,sub:sub||'',kind:kind||'info',ms:kind==='bad'?9000:5000})}catch(_error){/* intentional: the band is the surface, the toast is a courtesy */}
    }

    function ensureStyle(){
      if(!doc||typeof doc.getElementById!=='function'||doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;style.textContent=CSS;
      (doc.head||doc.body).appendChild(style);
    }

    function element(tag,className,text){
      const el=doc.createElement(tag);
      if(className)el.className=className;
      if(text!==undefined)el.textContent=text;
      return el;
    }

    /* ------------------------------------------------------------ bande visible */

    function removeBand(){
      cancelLater(dismissTimer);dismissTimer=null;
      if(clockTimer!==null){stopEvery(clockTimer);clockTimer=null}
      if(band&&band.parentNode)band.parentNode.removeChild(band);
      band=null;
    }

    /* `phase` running|done ; `kind` ok|warn|bad|info ; `actions` : [{label, run}] ; `names` : lignes de détail (texte seul). */
    function paint({phase,kind,title,text,names,actions,clock,dismissMs}){
      ensureStyle();
      removeBand();
      counters.bands++;
      band=element('div');
      band.id=BAND_ID;
      band.setAttribute('data-phase',phase);band.setAttribute('data-kind',kind);
      const urgent=kind==='bad'||kind==='warn';
      band.setAttribute('role',urgent?'alert':'status');
      band.setAttribute('aria-live',urgent?'assertive':'polite');
      const lead=element('span');
      const spin=element('span','jvsr-spin'),dot=element('span','jvsr-dot');
      spin.setAttribute('aria-hidden','true');dot.setAttribute('aria-hidden','true');
      lead.appendChild(spin);lead.appendChild(dot);
      const body=element('div','jvsr-body');
      body.appendChild(element('span','jvsr-title',title));
      body.appendChild(element('span','jvsr-text',text));
      let clockEl=null;
      if(clock){clockEl=element('span','jvsr-clock','');body.appendChild(clockEl)}
      if(names&&names.length){
        const list=element('ul','jvsr-names');
        for(const line of names)list.appendChild(element('li','',line));
        body.appendChild(list);
      }
      const box=element('div','jvsr-actions');
      for(const action of actions||[]){
        const button=element('button','',action.label);
        button.type='button';
        button.addEventListener('click',(event)=>{if(event&&event.stopPropagation)event.stopPropagation();action.run()});
        box.appendChild(button);
      }
      band.appendChild(lead);band.appendChild(body);band.appendChild(box);
      (doc.body).appendChild(band);
      if(clock){
        const tick=()=>{if(clockEl)clockEl.textContent=clock()};
        tick();
        clockTimer=every(tick,250);
      }
      if(dismissMs)dismissTimer=later(removeBand,dismissMs);
      return band;
    }

    /* ------------------------------------------------------------ rapports de montage */

    async function postJson(path,body,timeoutMs){
      if(!fetchImpl)throw new StudioReloadError('fetch is unavailable in this page','unreachable',0);
      const controller=typeof AbortController==='function'?new AbortController():null;
      let expired=false;
      const deadline=later(()=>{expired=true;if(controller)controller.abort()},timeoutMs);
      try{
        const response=await fetchImpl(path,{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},
          body:JSON.stringify(body),signal:controller?controller.signal:undefined});
        const text=await response.text();
        let json=null;
        try{json=text?JSON.parse(text):null}catch(_error){json=null}
        return {status:response.status,ok:response.ok,body:json};
      }catch(error){
        if(expired)throw new StudioReloadError(`pas de réponse en ${Math.round(timeoutMs/1000)} s`,'timeout',0);
        if(error&&error.name==='AbortError')throw new StudioReloadError('attente annulée','cancelled',0);
        throw new StudioReloadError(describe(error),'unreachable',0);
      }finally{cancelLater(deadline)}
    }

    function envelope(response){
      const error=response.body&&response.body.error;
      return new StudioReloadError(error&&error.message?String(error.message):`HTTP ${response.status}`,
        error&&error.code?String(error.code):`http_${response.status}`,response.status);
    }

    /* Branché sur `createPrefabHost({onOutcome})`. Ne rapporte que les sources de scène du Studio. */
    async function hostOutcome(info){
      const prefab=info&&info.prefab;
      if(!prefab||typeof prefab.id!=='string'||!prefab.id.startsWith(STUDIO_PREFIX)||!OUTCOMES.includes(info.outcome))return null;
      const body={object_id:String(info.object_id),prefab:{id:prefab.id,version:prefab.version},outcome:info.outcome};
      if(info.outcome==='failed'){
        body.reason=REASON.test(info.reason||'')?info.reason:'error';
        body.message=clip(info.message,MAX_MESSAGE);
      }
      let last=null;
      for(let attempt=1;attempt<=REPORT_ATTEMPTS;attempt++){
        try{
          const response=await postJson(REPORT_ROUTE,body,REPORT_TIMEOUT_MS);
          if(!response.ok)throw envelope(response);
          counters.reportsSent++;
          log('mount_reported',{object_id:body.object_id,prefab:`${prefab.id}@${prefab.version}`,outcome:info.outcome,
            reason:body.reason||null,matched:!!(response.body&&response.body.matched),attempt});
          return response.body;
        }catch(error){
          last=error;
          if(error&&(error.status===400||error.status===403))break;   // a refusal is final: retrying changes nothing
          if(attempt<REPORT_ATTEMPTS)await new Promise((resolve)=>later(resolve,REPORT_RETRY_MS));
        }
      }
      counters.reportsFailed++;
      log('mount_report_unsent',{object_id:body.object_id,prefab:`${prefab.id}@${prefab.version}`,outcome:info.outcome,
        code:last&&last.code||'unreachable',error:describe(last)},'error');
      tell('Rapport de montage non envoyé',`Core ne sait pas si ${prefab.id}@${prefab.version} a monté : ${describe(last)}`,'bad');
      return null;
    }

    /* ------------------------------------------------------------ résultat d'une édition */

    function labelOf(opts,result){
      const title=opts&&opts.title?String(opts.title):'';
      return title?`« ${clip(title,60)} »`:(result&&result.scene_id?result.scene_id:'la scène');
    }

    function resetLines(reset){
      const lines=[];
      if(!reset)return lines;
      const props=Array.isArray(reset.props)?reset.props.map((name)=>`props.${name}`):[];
      const data=Array.isArray(reset.data)?reset.data.map((name)=>`data.${name}`):[];
      if(props.length||data.length)lines.push(`Valeurs retirées : ${props.concat(data).join(', ')}`);
      if(Array.isArray(reset.controls)&&reset.controls.length)lines.push(`Contrôles retirés : ${reset.controls.join(', ')}`);
      if(Array.isArray(reset.anchors)&&reset.anchors.length)lines.push(`Ancres déliées : ${reset.anchors.join(', ')}`);
      if(reset.runtime_values)lines.push('Valeurs vivantes du cadre remises aux valeurs de la scène');
      if(Array.isArray(reset.unfit)&&reset.unfit.length)lines.push(`Valeurs gardées mais invalides pour cette version : ${reset.unfit.join(', ')}`);
      return lines;
    }

    function version(pin){return pin&&pin.id?`${pin.id.split('.').slice(-1)[0]}@${pin.version}`:'?'}

    /* L'issue exacte de Core, en mots de l'utilisateur. Rend `{kind, title, text, names, persistent}`. */
    function describeResult(result,opts){
      const label=labelOf(opts,result);
      const why=result.message?` ${clip(result.message,MAX_MESSAGE)}`:'';
      switch(result.status){
        case 'reloaded':
          return {kind:'ok',title:`Scène ${label} rechargée`,text:`Nouvelle version en place (${version(result.prefab)}), montage confirmé. Le reste de la présentation n'a pas bougé.`};
        case 'reloaded_state_reset':
          return {kind:'warn',persistent:true,title:`Scène ${label} rechargée, mais des valeurs ont été remises à zéro`,
            text:'La nouvelle source ne s\'accorde plus avec ces réglages ; la partition n\'a pas changé.',names:resetLines(result.reset)};
        case 'repinned':
          return {kind:'info',persistent:true,title:`Version enregistrée pour ${label}`,
            text:'Aucune fenêtre n\'affiche cette scène : la version sera vérifiée à sa prochaine projection, et annulée si elle ne monte pas.'};
        case 'pending_mount':
          if(result.mounted===true)return {kind:'warn',persistent:true,title:`Scène ${label} : confirmation non écrite`,
            text:`Le cadre a monté la nouvelle version, mais Core n'a pas pu enregistrer la confirmation.${why} La version reste active avec son repli ; le prochain rapport ou rechargement la confirmera.`};
          return {kind:'warn',persistent:true,title:`Scène ${label} : montage non confirmé`,
            text:`La page n'a rien rapporté dans le délai.${why} La nouvelle version reste active avec son repli ; un échec tardif la ramènera en arrière.`};
        case 'refused_validation':
          return {kind:'bad',persistent:true,title:`Modification de ${label} refusée avant publication`,
            text:`Rien n'a changé.${why}`};
        case 'rolled_back':
          return {kind:'bad',persistent:true,title:`Modification de ${label} annulée`,
            text:`Le cadre n'a pas pu monter la nouvelle source : retour à la dernière version valide (${version(result.prefab)}).${why}`,
            names:resetLines(result.reset)};
        case 'degraded':
          return {kind:'bad',persistent:true,title:`Scène ${label} dégradée : le retour arrière a échoué`,
            text:`La nouvelle source n'a pas monté et la dernière version valide n'a pas pu être remise en place.${why} La scène garde son repli enregistré : relance un rechargement ou redémarre pour la réparer.`};
        case 'stale':
          return {kind:'warn',persistent:true,title:`La scène ${label} a changé entre-temps`,
            text:`Relis-la puis recommence.${why}`};
        default:
          return {kind:'bad',persistent:true,title:`Issue inconnue pour ${label}`,text:String(result.status)};
      }
    }

    function show(result,opts){
      const view=describeResult(result,opts);
      counters.edits++;
      if(view.kind==='bad'||view.kind==='warn')counters.failures++;
      paint({phase:'done',kind:view.kind,title:view.title,text:view.text,names:view.names,
        actions:[{label:'Fermer',run:removeBand}],dismissMs:view.persistent?0:OK_DISMISS_MS});
      log('result',{status:result.status,scene_id:result.scene_id,source_revision:result.source_revision,code:result.code||null,
        reason:result.reason||null,reset:result.reset?{props:(result.reset.props||[]).length,data:(result.reset.data||[]).length,
        controls:(result.reset.controls||[]).length,anchors:(result.reset.anchors||[]).length,runtime:!!result.reset.runtime_values}:null},
        view.kind==='bad'?'error':view.kind==='warn'?'warn':'info');
      if(view.kind==='bad'||view.kind==='warn')tell(view.title,clip(view.text,120),view.kind==='bad'?'bad':'warn');
      return view;
    }

    /* ------------------------------------------------------------ édition de source */

    function check(opts){
      const problems=[];
      for(const name of ['presentation_id','variant_id','scene_id']){
        if(!opts||typeof opts[name]!=='string'||!opts[name])problems.push(name);
      }
      if(!opts||!Number.isInteger(opts.revision)||opts.revision<1)problems.push('revision');
      if(!opts||!opts.files||typeof opts.files!=='object'||Array.isArray(opts.files)||!Object.keys(opts.files).length)problems.push('files');
      return problems;
    }

    /* `opts` : {presentation_id, variant_id, scene_id, revision, files, title?, allow_state_reset?, request_id?, state?}.
       Rend le résultat de Core (jamais une exception pour un refus, un retour arrière ou une base périmée). Lève
       `StudioReloadError` pour une requête mal formée ou une panne de transport — APRÈS l'avoir rendue visible. */
    async function applySourceEdit(opts){
      const problems=check(opts);
      if(problems.length){
        const error=new StudioReloadError(`requête incomplète : ${problems.join(', ')}`,'invalid_request',0);
        paint({phase:'done',kind:'bad',title:'Rechargement impossible',text:error.message,actions:[{label:'Fermer',run:removeBand}]});
        log('request_invalid',{problems},'error');
        throw error;
      }
      if(busy){
        paint({phase:'done',kind:'warn',title:'Un rechargement est déjà en cours',
          text:'Attends son résultat avant d\'en lancer un autre : la seconde demande n\'a pas été envoyée.',actions:[{label:'Fermer',run:removeBand}]});
        log('busy',{scene_id:opts.scene_id},'warn');
        throw new StudioReloadError('un rechargement est déjà en cours','busy',0);
      }
      const controller=typeof AbortController==='function'?new AbortController():null;
      const started=now();
      busy={controller};
      const label=labelOf(opts,{scene_id:opts.scene_id});
      const clock=()=>`${Math.min(Math.floor((now()-started)/1000),EDIT_TIMEOUT_MS/1000)} s / ${EDIT_TIMEOUT_MS/1000} s`;
      paint({phase:'running',kind:'info',title:`Rechargement de ${label}…`,
        text:'Validation, publication, puis attente du montage dans la page.',clock,
        actions:[{label:'Arrêter d\'attendre',run:()=>{if(controller)controller.abort()}}]});
      log('started',{scene_id:opts.scene_id,files:Object.keys(opts.files).length});
      let expired=false;
      const deadline=later(()=>{expired=true;if(controller)controller.abort()},EDIT_TIMEOUT_MS);
      try{
        const body={actor:'user',basis:{variant_revision:opts.revision},scene_id:opts.scene_id,files:opts.files};
        if(opts.request_id)body.request_id=opts.request_id;
        if(opts.allow_state_reset===true)body.allow_state_reset=true;
        const path=`${ROUTE}/${encodeURIComponent(opts.presentation_id)}/variants/${encodeURIComponent(opts.variant_id)}/source-edits`;
        let response;
        try{
          response=await fetchImpl(path,{method:'POST',cache:'no-store',headers:{'Content-Type':'application/json'},
            body:JSON.stringify(body),signal:controller?controller.signal:undefined});
        }catch(error){
          if(expired)throw new StudioReloadError(`pas de réponse en ${EDIT_TIMEOUT_MS/1000} s : le résultat reste consultable côté serveur`,'timeout',0);
          if(error&&error.name==='AbortError')throw new StudioReloadError('attente arrêtée : le rechargement peut encore aboutir côté serveur','cancelled',0);
          throw new StudioReloadError(describe(error),'unreachable',0);
        }
        const text=await response.text();
        let json=null;
        try{json=text?JSON.parse(text):null}catch(_error){json=null}
        if(isResult(json)){
          if(opts.state&&typeof opts.state==='object'&&Number.isInteger(json.revision))opts.state.revision=json.revision;
          show(json,opts);
          return json;
        }
        throw envelope({status:response.status,body:json});
      }catch(error){
        const failure=error instanceof StudioReloadError?error:new StudioReloadError(describe(error),'unreachable',0);
        counters.failures++;
        paint({phase:'done',kind:'bad',title:`Rechargement de ${label} : pas de réponse exploitable`,
          text:`${failure.message} (${failure.code})`,
          actions:[{label:'Réessayer',run:()=>{removeBand();applySourceEdit(opts).catch(()=>{/* shown by the band itself */})}},
                   {label:'Fermer',run:removeBand}]});
        log('failed',{scene_id:opts.scene_id,code:failure.code,status:failure.status,error:failure.message},'error');
        tell(`Rechargement de ${label} impossible`,failure.message,'bad');
        throw failure;
      }finally{
        cancelLater(deadline);
        busy=null;
      }
    }

    /* ------------------------------------------------------------ surveillance */

    function rowKey(row){return `${row.variant_id}|${row.scene_id}|${row.source_revision}|${row.status}|${row.late?'late':'now'}`}

    /* Montre ce que l'utilisateur n'a pas lancé : édition de la voix, retour arrière tardif. Le premier relevé n'est que
       la base (aucun historique n'est annoncé). Un relevé en échec est journalisé ; la panne continue d'être dite UNE fois. */
    function watch(presentationId,options){
      stopWatching();
      const o=options||{};
      const interval=Number.isInteger(o.intervalMs)&&o.intervalMs>=100?o.intervalMs:WATCH_MS;
      const seen=new Set();
      let primed=false,down=false,running=false;
      async function poll(){
        if(running||(doc&&doc.hidden))return;
        running=true;
        try{
          const response=await fetchImpl(`${ROUTE}/${encodeURIComponent(presentationId)}/reloads`,{cache:'no-store'});
          const text=await response.text();
          let json=null;
          try{json=text?JSON.parse(text):null}catch(_error){json=null}
          if(!response.ok||!json||!Array.isArray(json.reloads))throw envelope({status:response.status,body:json});
          if(down){down=false;log('watch_recovered',{presentation_id:presentationId})}
          for(const row of json.reloads){
            const key=rowKey(row);
            if(seen.has(key))continue;
            seen.add(key);
            if(seen.size>WATCH_SEEN_CAP)seen.delete(seen.values().next().value);
            if(!primed)continue;
            const stood=['reloaded'].includes(row.status);
            if(!stood||row.late)show(row,{title:o.titles&&o.titles[row.scene_id]});
            else{log('reload_seen',{scene_id:row.scene_id,status:row.status});tell('Scène rechargée','Une modification a été appliquée.','ok')}
            if(typeof o.onRow==='function'){try{o.onRow(row)}catch(error){log('watch_callback_failed',{error:describe(error)},'warn')}}
          }
          primed=true;
        }catch(error){
          log('watch_failed',{presentation_id:presentationId,error:describe(error)},'warn');
          if(!down){down=true;tell('Suivi des rechargements interrompu',describe(error),'warn')}
        }finally{running=false}
      }
      const timer=every(poll,interval);
      watcher={timer,poll};
      poll();
      return poll;
    }

    function stopWatching(){
      if(watcher){stopEvery(watcher.timer);watcher=null}
    }

    function dismiss(){removeBand()}

    function state(){
      return {busy:!!busy,band:band?{kind:band.getAttribute('data-kind'),phase:band.getAttribute('data-phase')}:null,
        watching:!!watcher,counters:Object.assign({},counters)};
    }

    /* Lecture seule, pour les tests de fuite : ce que CE module tient en ce moment (jamais une valeur, un texte ni un noeud).
       `bands` : bandes presentes dans le document (0 ou 1), `bandNodes` : leurs noeuds, `timers` : minuteries vivantes
       (fermeture automatique, compteur), `busy`, `toasts` : notifications emises depuis le debut (elles disparaissent
       seules apres leur duree : `ms`). Le cache de bundles et les cadres de l'hote se lisent par `host.stats()`. */
    function leakCounters(){
      const el=doc&&typeof doc.getElementById==='function'?doc.getElementById(BAND_ID):null;
      const count=(n)=>{let total=1;for(const c of (n.children||[]))total+=count(c);return total};
      const found=el?[el]:[];
      const nodes=el?count(el):0;
      return {bands:found.length,bandNodes:nodes,timers:(dismissTimer?1:0)+(clockTimer?1:0),busy:!!busy,watching:!!watcher,
        toasts:counters.toasts};
    }

    return Object.freeze({hostOutcome,applySourceEdit,show,describeResult,watch,stopWatching,dismiss,state,leakCounters,
      label:(opts,result)=>labelOf(opts,result)});
  }

  const api={ROUTE,REPORT_ROUTE,STUDIO_PREFIX,STATUSES,OUTCOMES,EDIT_TIMEOUT_MS,REPORT_TIMEOUT_MS,REPORT_ATTEMPTS,OK_DISMISS_MS,
    BAND_ID,StudioReloadError,createStudioReload,instance:null};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(root.document&&typeof root.fetch==='function'){
    try{api.instance=createStudioReload({})}
    catch(error){if(root.console)root.console.error('[studio-reload] not_installed '+JSON.stringify({error:describe(error)}))}
  }
  root.JarvisStudioReload=api;
})(typeof globalThis!=='undefined'?globalThis:this);
