/* Carte « Présentations · moteur » du Control Center (jarvis-remotion-presentation-integration, Slice 20).

   Contrat : `docs/presentation-engine.md` › *Human engine control*. Placée au-dessus de la carte Remotion (Slice 11) dans l'onglet
   « Plugins externes » (`#sveCard`). Elle est la SEULE porte par laquelle un moteur est nommé : le relais du Control Center pose
   `actor: user` côté serveur ; aucun outil du cerveau n'a de moteur. Trois parties :

   - `JarvisStudioEngineCore`, logique pure exécutée telle quelle par les tests node : diagnostic d'un Remotion en panne, libellés,
     confirmations, modèle de la carte, client HTTP des trois adresses relayées ;
   - un bloc navigateur qui rend la carte et relit l'état.

   CINQ RÈGLES.
   1. REMOTION PAR DÉFAUT. « Créer » crée Remotion. Slidecar n'existe que derrière « Expérimental », avec son avertissement, une
      confirmation et un compteur visible de ses usages.
   2. AUCUN REPLI. Remotion en panne : la raison réelle de l'adaptateur, le geste de réparation, et la mention que rien d'autre ne joue.
   3. CE QUI ATTEND SE VOIT : pastille animée, durée écoulée, échéance, et la façon d'en sortir.
   4. LE MOTEUR D'UN DOCUMENT NE CHANGE JAMAIS : « Dupliquer en expérience Slidecar » crée un NOUVEAU document, la source reste.
   5. L'ÉTAT EST CELUI DE CORE avec son code stable ; un échec dit ce qui s'est passé, jamais « erreur ». */

const JarvisStudioEngineCore=(function(){
  'use strict';

  const PRESENTATIONS='/api/presentation-studio/presentations';
  const ENGINE='/api/presentation-studio/engine';
  const CAPABILITY='/api/local-capabilities/remotion';
  const READ_DEADLINE_MS=15000;
  const WRITE_DEADLINE_MS=30000;
  /* `install` / `repair` répondent 200 en 2 s ou 202 : l'écran relit ensuite la capacité (npm s'arrête à 15 min côté Core). */
  const REPAIR_LIMIT_S=15*60;
  const POLL_FAST_MS=2000;
  const POLL_SLOW_MS=10000;
  const MAX_TITLE=80;
  const SLIDECAR_WARNING='Slidecar est expérimental : pas de séquence image par image, pas d’export MP4. Le moteur d’une présentation ne change jamais après sa création. Aucun repli : si Remotion tombe en panne, rien ne joue à sa place.';

  const ENGINE_LABEL=Object.freeze({remotion:{label:'Remotion',tone:'ok'},slidecar:{label:'Slidecar · expérimental',tone:'warn'}});
  const EVENT_LABEL=Object.freeze({slidecar_created:'Création',slidecar_experiment_created:'Copie « expérience »',slidecar_used:'Utilisation'});
  const ACTION_LABEL=Object.freeze({play:'lecture',edit:'édition',preview:'aperçu',render_overlay:'édition'});

  const ERRORS=Object.freeze({
    presentation_studio_engine_selection_refused:'Seul vous pouvez choisir le moteur, depuis cette page. Le choix a été refusé.',
    presentation_studio_invalid:'La demande est refusée : ',
    presentation_studio_limit_reached:'Le nombre maximal de présentations est atteint.',
    presentation_studio_unknown_presentation:'Cette présentation n’existe plus.',
    presentation_studio_storage_io:'Le disque a refusé l’écriture : rien n’a été créé.',
    invalid_request:'La demande est mal formée.',
    core_unreachable:'Core ne répond pas.',core_unconfigured:'Le Control Center ne connaît pas Core.',
    core_timeout:'Core n’a pas répondu à temps : l’issue est inconnue, la liste est relue.',
    timeout:'Core n’a pas répondu à temps : l’issue est inconnue, la liste est relue.',
    network:'La connexion avec le Control Center a échoué.',
  });
  function errorText(code,message){
    const base=ERRORS[code]||'';
    if(code==='presentation_studio_invalid'&&message)return base+message;
    return base||message||'';
  }

  /* Codes d'échec de la capacité (`docs/remotion-runtime.md` §3) : la phrase et le geste utile. Un code inconnu s'affiche tel quel. */
  const CAPABILITY_FAILURES=Object.freeze({
    local_capability_requirement_missing:'Ce poste n’a pas Node.js ou npm en version suffisante (Node 20 ou plus, npm 9 ou plus). Installez-les, puis réparez.',
    local_capability_install_offline:'npm n’atteint pas le réseau. Rétablissez la connexion (proxy, pare-feu), puis réparez.',
    local_capability_install_permission_denied:'Le dossier d’installation n’est pas inscriptible ou un fichier est verrouillé (antivirus). Corrigez les droits, puis réparez.',
    local_capability_install_disk_full:'Il manque de la place sur le disque (1,5 Go libres requis). Libérez de la place, puis réparez.',
    local_capability_install_timeout:'L’installation a dépassé 15 minutes. Vérifiez le débit, puis réparez.',
    local_capability_install_integrity_failed:'npm a refusé un paquet dont l’empreinte ne correspond pas au verrou. Ne contournez pas : réparez, et si cela se répète, le réseau altère les paquets.',
    local_capability_install_interrupted:'Jarvis s’est arrêté pendant l’installation. Réparez pour la reprendre.',
    local_capability_install_failed:'npm a échoué. Le détail ci-dessous dit pourquoi ; réparez après l’avoir corrigé.',
    local_capability_health_failed:'L’environnement installé est abîmé. Réparez : il est refait depuis le verrou, sans toucher à vos présentations.',
  });

  /* Diagnostic d'un Remotion qui ne peut pas jouer. `remotion` : `{ready, reason, repair}` de Core ; `capability` : la vue de la
     capacité (ou null). Rend `{kind, title, reason, steps, action}` ; `action` est `install`, `repair` ou null (geste à faire soi-même). */
  function diagnose(remotion,capability){
    if(!remotion||remotion.ready)return null;
    const reason=String(remotion.reason||'raison inconnue');
    const status=capability&&capability.status;
    const code=capability&&capability.last_error_code||'';
    const detail=capability&&capability.last_error_detail||'';
    const base={reason,repair:String(remotion.repair||''),detail,code};
    if(/JARVIS_REMOTION_SANDBOX/.test(reason+' '+(remotion.repair||'')))
      return {...base,kind:'sandbox_settings',title:'Réglages du bac à sable Remotion invalides',action:null,
        steps:['Corrigez JARVIS_REMOTION_SANDBOX_HOST et JARVIS_REMOTION_SANDBOX_PORT (hôte de boucle locale, port libre).','Redémarrez Core vous-même : Jarvis ne se relance jamais seul.']};
    if(/no Remotion adapter|no local capability store|no Remotion sandbox/.test(reason))
      return {...base,kind:'no_adapter',title:'Ce Core n’a pas de moteur Remotion',action:null,
        steps:['Ce Core a été lancé sans l’environnement Remotion (banc d’essai ou script).','Lancez Core normalement, ou configurez JARVIS_REMOTION_SANDBOX_PORT.']};
    if(status==='installing')
      return {...base,kind:'installing',title:'Installation de Remotion en cours',action:null,steps:['Patientez : l’écran se met à jour tout seul.']};
    if(status==='not_installed')
      return {...base,kind:'runtime_missing',title:'Remotion n’est pas installé sur ce poste',action:'install',
        steps:['Une seule installation par poste : environ 270 Mo téléchargés par npm, une vingtaine de secondes avec un bon réseau.']};
    if(status==='install_failed'||status==='repair_needed'||status==='crashed'||code){
      const text=CAPABILITY_FAILURES[code]||(status==='crashed'?'Le processus de l’environnement s’est arrêté. Réparez pour le relancer.':'L’environnement Remotion est à réparer.');
      return {...base,kind:'runtime_broken',title:status==='install_failed'?'L’installation de Remotion a échoué':'L’environnement Remotion est à réparer',action:'repair',steps:[text]};
    }
    if(status==='disabled')
      return {...base,kind:'disabled',title:'L’environnement Remotion est désactivé',action:null,steps:['Réactivez-le dans les capacités locales de Core (action explicite).']};
    return {...base,kind:'unknown',title:'Remotion ne peut pas jouer pour l’instant',action:capability?'repair':null,
      steps:[remotion.repair?String(remotion.repair):'Lisez la raison ci-dessus.']};
  }

  function engineBadge(engine){return ENGINE_LABEL[engine]||{label:String(engine||'?'),tone:''}}

  function eventLine(event){
    const parts=[EVENT_LABEL[event.kind]||String(event.kind||'')];
    if(event.action)parts.push(ACTION_LABEL[event.action]||String(event.action));
    if(event.presentation_id)parts.push(String(event.presentation_id).slice(0,12)+'…');
    if(event.derived_from)parts.push('copie de '+String(event.derived_from).slice(0,12)+'…');
    if(event.actor)parts.push('acteur : '+(event.actor==='human'?'vous':String(event.actor)));
    if(event.reason)parts.push('raison : '+String(event.reason));
    return parts.join(' · ');
  }

  /* Confirmation (règle 1) : avertissement lu avant toute création Slidecar, y compris une copie « expérience ». */
  function confirmSlidecar(kind,sourceTitle){
    const copy=kind==='copy';
    const lines=[['Expérimental : ',SLIDECAR_WARNING],
      ['Journalisé : ','cette création est inscrite dans le journal des diagnostics (moteur, acteur, raison).']];
    if(copy)lines.push(['Nouveau document : ',`« ${sourceTitle||'la présentation'} » n’est pas modifiée ; la copie est vide (une scène Remotion ne s’exécute pas en Slidecar).`]);
    return {title:copy?'Dupliquer en expérience Slidecar ?':'Créer une présentation Slidecar (expérimental) ?',lines,
      confirmLabel:copy?'Créer la copie Slidecar':'Créer en Slidecar',cancelLabel:'Annuler',danger:true};
  }
  function confirmRepair(action){
    const install=action==='install';
    return {title:install?'Installer Remotion sur ce poste ?':'Réparer l’environnement Remotion ?',
      lines:[['Ce que ça fait : ',install?'npm télécharge Remotion depuis le registre (≈ 270 Mo) dans le dossier de données de ce poste.'
        :'npm refait l’environnement depuis le verrou, avec vérification des empreintes. Vos présentations et sources ne sont pas touchées.'],
        ['Durée : ','de 20 secondes à 15 minutes ; l’écran affiche le temps écoulé.'],
        ['Aucun repli : ','pendant ce temps, les présentations Remotion ne jouent pas, et aucune présentation Slidecar ne joue à leur place.']],
      confirmLabel:install?'Installer':'Réparer',cancelLabel:'Annuler',danger:false};
  }

  function fmtDuration(seconds){
    const s=Math.max(0,Math.round(seconds));
    if(s<60)return `${s} s`;
    const m=Math.floor(s/60),r=s%60;
    return r?`${m} min ${String(r).padStart(2,'0')} s`:`${m} min`;
  }

  /* Modèle de la carte : tout ce que le rendu affiche. `state` : {engine, presentations, capability, repairStartedAt}; `now` en ms. */
  function viewModel(state,now){
    const engine=state.engine||null;
    const remotion=engine&&engine.engines?engine.engines.remotion:null;
    const ledger=engine&&engine.slidecar||{events:[],total:0,kept:0};
    const rows=(state.presentations||[]).map(row=>({id:row.presentation_id,title:row.title,engine:row.engine,badge:engineBadge(row.engine),
      variants:row.variant_count,revision:row.revision,canCopy:row.engine!=='slidecar'}));
    const slidecarCount=rows.filter(r=>r.engine==='slidecar').length;
    const model={defaultEngine:engine?engine.default_engine:'remotion',
      remotion:{known:!!remotion,ready:!!(remotion&&remotion.ready),reason:remotion?remotion.reason:'',tone:!remotion?'':remotion.ready?'ok':'bad',
        label:!remotion?'Inconnu':remotion.ready?'Prêt':'Indisponible'},
      diagnosis:diagnose(remotion,state.capability),rows,slidecarCount,
      events:(ledger.events||[]).slice(0,20).map(e=>({at:e.at,line:eventLine(e)})),eventsTotal:ledger.total||0,eventsKept:ledger.kept||0,
      repair:null};
    const cap=state.capability;
    if(cap&&cap.status==='installing'){
      const since=state.repairStartedAt?Math.max(0,(now-state.repairStartedAt)/1000):(cap.updated_at?Math.max(0,now/1000-cap.updated_at):0);
      model.repair={text:`Installation de Remotion en cours… ${fmtDuration(since)} écoulées, ${REPAIR_LIMIT_S/60} min au plus. Vous pouvez laisser cette fenêtre : Core continue.`,since,overdue:since>REPAIR_LIMIT_S+60};
    }
    return model;
  }

  function createClient({fetchImpl,setTimeoutImpl=setTimeout,clearTimeoutImpl=clearTimeout}){
    async function request(method,path,{body,deadline}={}){
      const controller=typeof AbortController!=='undefined'?new AbortController():null;
      const timer=controller?setTimeoutImpl(()=>controller.abort(),deadline):null;
      let response;
      try{
        response=await fetchImpl(path,{method,headers:body===undefined?{}:{'Content-Type':'application/json'},
          body:body===undefined?undefined:JSON.stringify(body),signal:controller?controller.signal:undefined,cache:'no-store'});
      }catch(error){
        const timeout=error&&error.name==='AbortError';
        throw Object.assign(new Error(timeout?'delay exceeded':String(error&&error.message||error)),{code:timeout?'timeout':'network',status:0});
      }finally{if(timer)clearTimeoutImpl(timer)}
      let payload=null;
      try{payload=await response.json()}catch(_){payload=null}
      if(!response.ok){
        const e=payload&&payload.error||{};
        throw Object.assign(new Error(e.message||`HTTP ${response.status}`),{code:e.code||`http_${response.status}`,status:response.status});
      }
      return payload;
    }
    return {
      engine:()=>request('GET',ENGINE,{deadline:READ_DEADLINE_MS}),
      list:()=>request('GET',PRESENTATIONS+'?limit=64',{deadline:READ_DEADLINE_MS}),
      capability:()=>request('GET',CAPABILITY,{deadline:READ_DEADLINE_MS}).then(p=>p.capability).catch(()=>null),
      /* Seule création : `engine` n'est envoyé que pour Slidecar (confirmé). Remotion = rien de nommé, le défaut de Core. */
      create({title,slidecar=false,reason=''}){
        const body={title};
        if(slidecar){body.engine='slidecar';body.experimental_confirmed=true;if(reason)body.reason=reason}
        return request('POST',PRESENTATIONS,{body,deadline:WRITE_DEADLINE_MS});
      },
      experiment(id,reason=''){
        const body={experimental_confirmed:true};
        if(reason)body.reason=reason;
        return request('POST',`${PRESENTATIONS}/${encodeURIComponent(id)}/experiment`,{body,deadline:WRITE_DEADLINE_MS});
      },
      repair(operation){
        if(operation!=='install'&&operation!=='repair')throw new Error('unknown capability operation');
        return request('POST',`${CAPABILITY}/${operation}`,{body:{},deadline:WRITE_DEADLINE_MS}).then(p=>p&&p.capability);
      },
    };
  }

  return {PRESENTATIONS,ENGINE,CAPABILITY,MAX_TITLE,REPAIR_LIMIT_S,POLL_FAST_MS,POLL_SLOW_MS,SLIDECAR_WARNING,ERRORS,CAPABILITY_FAILURES,
    errorText,diagnose,engineBadge,eventLine,confirmSlidecar,confirmRepair,fmtDuration,viewModel,createClient};
})();

if(typeof module!=='undefined'&&module.exports)module.exports=JarvisStudioEngineCore;

/* --------------------------------------------------------------------------
   Navigateur : rend la carte dans `#sveCard` quand l'onglet « Plugins externes » est visible. Ne crée rien d'elle-même : chaque
   création, copie ou réparation est un clic, avec sa confirmation quand elle est expérimentale ou téléchargeante.
   -------------------------------------------------------------------------- */
(function installJarvisStudioEngine(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const C=JarvisStudioEngineCore;
  const host=document.getElementById('sveCard');
  const dialog=document.getElementById('mcpInspector');
  const pane=document.getElementById('mcpPlugins');
  if(!host||!dialog||!pane)return;
  const client=C.createClient({fetchImpl:(path,options)=>window.fetch(path,options)});
  const S={engine:null,presentations:[],capability:null,loading:false,busy:'',readError:null,actionError:null,notice:'',poll:null,clock:null,gen:0,
    rendered:'',title:'',reason:'',experimentalOpen:false,logOpen:false,repairStartedAt:0,busySince:0};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const log=(level,event,data)=>{const line=`[studio-engine] ${event} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line)};
  const notify=spec=>{if(typeof toast==='function')toast(spec)};
  const visible=()=>!dialog.hidden&&!pane.hidden;
  const ACT='%%ACTIVITY%%';

  function render(){
    const now=Date.now();
    const m=C.viewModel({engine:S.engine,presentations:S.presentations,capability:S.capability,repairStartedAt:S.repairStartedAt},now);
    const busyText=S.busy?`${S.busy} ${C.fmtDuration((now-S.busySince)/1000)}`:'';
    const btn=(id,label,enabled,cls='',extra='')=>`<button type="button" class="action small ${cls}" id="${id}"${enabled&&!S.busy?'':' disabled'}${extra}>${esc(label)}</button>`;
    const d=m.diagnosis;
    const repairing=m.repair?`<p class="mcpp-activity rms-activity" id="sveRepair"><span class="mcpp-spin" aria-hidden="true"></span><span id="sveRepairText">${ACT}</span></p>`:'';
    const diagnosis=d&&d.kind!=='installing'?`<div class="mcpp-lasterr rms-err sve-diag" role="alert" id="sveDiag"><span class="mcpp-dot" aria-hidden="true"></span><span>
        <strong>${esc(d.title)}</strong><br>Raison : ${esc(d.reason)}${d.code?` <code>${esc(d.code)}</code>`:''}<br>
        ${d.steps.map(s=>esc(s)).join('<br>')}${d.detail?`<br><span class="rms-hint">Détail : ${esc(d.detail)}</span>`:''}<br>
        <span class="rms-hint">Aucune présentation Slidecar n’est affichée à la place : une présentation Remotion ne joue qu’avec Remotion.</span>
        ${d.action?`<br>${btn('sveRepairGo',d.action==='install'?'Installer Remotion':'Réparer Remotion',true,'primary')}`:''}</span></div>`:'';
    const readError=S.readError?`<p class="mcpp-lasterr rms-err" role="status"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(S.readError.text)} <code>${esc(S.readError.code)}</code> L’état affiché est le dernier connu.</span></p>`:'';
    const actionError=S.actionError?`<div class="mcpp-lasterr rms-err" role="alert"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(S.actionError.text)} <code>${esc(S.actionError.code)}</code></span></div>`:'';
    const notice=S.notice?`<p class="rms-hint" id="sveNotice" role="status">${esc(S.notice)}</p>`:'';
    const rows=m.rows.length?`<ul class="sve-list" id="sveList">${m.rows.map(r=>`<li class="sve-row" data-engine="${esc(r.engine)}" data-id="${esc(r.id)}"><span class="sve-title">${esc(r.title)}</span>
        <span class="chip ${r.badge.tone}" title="Moteur de cette présentation, fixé à sa création">${esc(r.badge.label)}</span>
        <span class="rms-hint">${r.variants} variante${r.variants>1?'s':''} · révision ${r.revision}</span>
        ${r.canCopy?btn('sveCopy-'+r.id,'Dupliquer en expérience Slidecar…',true,'',` data-copy="${esc(r.id)}" data-title="${esc(r.title)}"`):''}</li>`).join('')}</ul>`
      :`<p class="rms-none" id="sveNone">${S.engine?'Aucune présentation.':'Lecture des présentations…'}</p>`;
    const events=m.events.length?`<ul class="sve-events">${m.events.map(e=>`<li><time>${esc(e.at||'')}</time> ${esc(e.line)}</li>`).join('')}</ul>`
      :'<p class="rms-none">Aucun usage de Slidecar depuis le démarrage de Core.</p>';
    const html=`<article class="mcpp-card rms-card sve-card" data-state="${m.remotion.known&&!m.remotion.ready?'error':'on'}" aria-labelledby="sveTitle">
      <div class="mcpp-top"><span class="mcpp-avatar" aria-hidden="true"><span class="mcpp-letter">M</span></span>
        <div class="mcpp-ident"><h3 class="mcpp-name" id="sveTitle">Présentations · moteur</h3>
          <span class="mcpp-host">Moteur par défaut : Remotion</span></div>
        <div class="mcpp-badges"><span class="chip ok" id="sveDefault" title="Moteur de toute nouvelle présentation">Défaut : Remotion</span>
          <span class="chip ${m.remotion.tone}" id="sveRemotion" title="État de Remotion tel que son adaptateur le rapporte">Remotion : ${esc(m.remotion.label)}</span>
          <span class="chip ${m.slidecarCount||m.eventsTotal?'warn':''}" id="sveSlidecar" title="Présentations Slidecar enregistrées · entrées du journal Slidecar depuis le démarrage de Core">Slidecar : ${m.slidecarCount} document${m.slidecarCount>1?'s':''}${m.eventsTotal?` · ${m.eventsTotal} au journal`:''}</span></div></div>
      ${repairing}${diagnosis}${actionError}${readError}${notice}
      <form class="sve-new" id="sveNew" autocomplete="off"><label class="rms-scene"><span>Nouvelle présentation (Remotion)</span>
        <input id="sveTitleInput" type="text" maxlength="${C.MAX_TITLE}" placeholder="Titre" aria-label="Titre de la nouvelle présentation"${S.busy?' disabled':''}></label>
        <button type="submit" class="action small primary" id="sveCreate"${S.busy?' disabled':''}>Créer avec Remotion</button></form>
      <details class="mcpp-tech sve-exp" id="sveExp"${S.experimentalOpen?' open':''}><summary>Expérimental : Slidecar</summary>
        <p class="rms-hint sve-warn" id="sveWarn"><strong>Expérimental.</strong> ${esc(C.SLIDECAR_WARNING)}</p>
        <label class="rms-scene"><span>Pourquoi (facultatif, inscrit au journal)</span>
          <input id="sveReason" type="text" maxlength="160" aria-label="Raison de l’expérience Slidecar"${S.busy?' disabled':''}></label>
        ${btn('sveCreateSlidecar','Créer une présentation Slidecar…',true,'danger')}</details>
      <div class="sve-listwrap" aria-label="Présentations et moteur de chacune">${rows}</div>
      <details class="mcpp-tech" id="sveLog"${S.logOpen?' open':''}><summary>Journal Slidecar (${m.eventsTotal})</summary>
        <p class="rms-hint">Création, copie et usage d’une présentation Slidecar : moteur, acteur, raison. Ce registre est en mémoire (depuis le démarrage de Core) ; le moteur de chaque document, lui, est durable : voir son badge.</p>${events}</details>
    </article>`;
    if(!host.querySelector('#sveBusy')){
      const live=document.createElement('div');live.id='sveBusy';live.className='rms-busy';live.setAttribute('aria-live','polite');host.append(live);
    }
    const busy=host.querySelector('#sveBusy');
    if(busy.textContent!==busyText)busy.textContent=busyText;
    const repairText=m.repair?m.repair.text:'';
    if(html===S.rendered){
      const node=host.querySelector('#sveRepairText');
      if(node&&node.textContent!==repairText)node.textContent=repairText;
      return;
    }
    /* Un champ en cours de saisie ne doit pas être détruit par un rendu d'arrière-plan : on garde sa valeur et son focus. */
    const active=document.activeElement;
    const focusId=active&&host.contains(active)?active.id:'';
    const caret=focusId&&active.selectionStart!=null?active.selectionStart:null;
    const card=host.querySelector('.sve-card');
    const wrapper=document.createElement('div');
    wrapper.innerHTML=html.replace(ACT,esc(repairText));
    if(card)card.replaceWith(wrapper.firstElementChild);else host.prepend(wrapper.firstElementChild);
    S.rendered=html;
    /* Les champs ne font pas partie du gabarit comparé : la saisie n'est jamais détruite par un rendu d'arrière-plan. */
    const titleField=host.querySelector('#sveTitleInput'),reasonField=host.querySelector('#sveReason');
    if(titleField)titleField.value=S.title;
    if(reasonField)reasonField.value=S.reason;
    if(focusId){const back=document.getElementById(focusId);if(back&&!back.disabled){back.focus();if(caret!=null&&back.setSelectionRange)try{back.setSelectionRange(caret,caret)}catch(_){/* champ sans sélection */}}}
  }

  async function refresh(){
    if(S.loading)return;
    S.loading=true;
    const gen=++S.gen;
    try{
      const [engine,list,capability]=await Promise.all([client.engine(),client.list(),client.capability()]);
      if(gen!==S.gen)return;
      S.engine=engine;S.presentations=list.presentations||[];S.capability=capability;S.readError=null;
      if(capability&&capability.status!=='installing')S.repairStartedAt=0;
    }catch(error){
      S.readError={code:error.code||'network',text:C.errorText(error.code,error.message)||'Impossible de lire l’état du moteur.'};
      log('warn','read_failed',{code:error.code,status:error.status});
    }finally{S.loading=false}
    render();schedule();
  }

  function schedule(){
    clearTimeout(S.poll);
    if(!visible())return;
    const installing=S.capability&&S.capability.status==='installing';
    S.poll=setTimeout(refresh,installing||S.busy?C.POLL_FAST_MS:C.POLL_SLOW_MS);
  }

  /* Une action utilisateur : occupée visible avec durée, échec dit en clair + journalisé + notifié, état libéré dans `finally`. */
  async function act(label,work,done){
    if(S.busy)return;
    S.busy=label;S.busySince=Date.now();S.actionError=null;S.notice='';render();schedule();
    const started=Date.now();
    try{
      const result=await work();
      log('info','action_done',{action:label,seconds:Math.round((Date.now()-started)/1000)});
      if(done)done(result);
    }catch(error){
      S.actionError={code:error.code||'network',text:C.errorText(error.code,error.message)||error.message||'L’action a échoué.'};
      log('error','action_failed',{action:label,code:error.code,status:error.status});
      notify({title:'Moteur des présentations',sub:S.actionError.text,kind:'error'});
    }finally{S.busy='';S.busySince=0}
    S.rendered='';render();refresh();
  }

  async function confirm(spec){
    if(typeof confirmDialog!=='function'){
      S.actionError={code:'confirmation_unavailable',text:'La confirmation n’est pas disponible dans cette page : rien n’a été créé.'};
      render();return false;
    }
    return confirmDialog(spec);
  }

  function created(kind){
    return result=>{
      const p=result&&result.presentation;
      S.notice=`Présentation « ${p?p.title:''} » créée avec ${p&&p.engine==='slidecar'?'Slidecar (expérimental, journalisé)':'Remotion'}.`;
      if(kind==='new'){S.title='';S.reason=''}
      notify({title:'Présentation créée',sub:p?`${p.title} · ${p.engine==='slidecar'?'Slidecar':'Remotion'}`:'',kind:'ok'});
    };
  }

  host.addEventListener('submit',event=>{
    event.preventDefault();
    const title=(S.title||'').trim();
    if(!title){S.actionError={code:'title_required',text:'Donnez un titre à la présentation.'};S.rendered='';render();return}
    act('Création (Remotion)…',()=>client.create({title}),created('new'));
  });
  host.addEventListener('input',event=>{
    if(event.target.id==='sveTitleInput')S.title=event.target.value;
    else if(event.target.id==='sveReason')S.reason=event.target.value;
  });
  host.addEventListener('toggle',event=>{
    if(event.target.id==='sveExp')S.experimentalOpen=event.target.open;
    else if(event.target.id==='sveLog')S.logOpen=event.target.open;
  },true);
  host.addEventListener('click',async event=>{
    const button=event.target.closest&&event.target.closest('button');
    if(!button||button.disabled||S.busy)return;
    if(button.id==='sveCreateSlidecar'){
      const title=(S.title||'').trim();
      if(!title){S.actionError={code:'title_required',text:'Donnez un titre à la présentation (champ du haut) avant de la créer.'};S.rendered='';render();return}
      if(!await confirm(C.confirmSlidecar('new')))return;
      act('Création (Slidecar)…',()=>client.create({title,slidecar:true,reason:(S.reason||'').trim()}),created('new'));
    }else if(button.dataset.copy){
      if(!await confirm(C.confirmSlidecar('copy',button.dataset.title)))return;
      act('Copie Slidecar…',()=>client.experiment(button.dataset.copy,(S.reason||'').trim()),created('copy'));
    }else if(button.id==='sveRepairGo'){
      const diagnosis=C.diagnose(S.engine&&S.engine.engines&&S.engine.engines.remotion,S.capability);
      if(!diagnosis||!diagnosis.action||!await confirm(C.confirmRepair(diagnosis.action)))return;
      S.repairStartedAt=Date.now();
      act(diagnosis.action==='install'?'Installation de Remotion…':'Réparation de Remotion…',()=>client.repair(diagnosis.action),view=>{
        if(view)S.capability=view;
        const status=view&&view.status;
        S.notice=status==='installing'?'Opération lancée : l’écran suit sa progression.'
          :status==='ready'||status==='running'?'Environnement Remotion prêt.':'';
      });
    }
  });

  function start(){
    if(!visible())return;
    refresh();
    clearInterval(S.clock);
    S.clock=setInterval(()=>{if(visible())render();else{clearInterval(S.clock);clearTimeout(S.poll)}},1000);
  }
  const observer=new MutationObserver(()=>{if(visible())start();else{clearTimeout(S.poll);clearInterval(S.clock)}});
  observer.observe(dialog,{attributes:true,attributeFilter:['hidden']});
  observer.observe(pane,{attributes:true,attributeFilter:['hidden']});
  render();
  start();
  window.JarvisStudioEngine={state:S,refresh};
})();
