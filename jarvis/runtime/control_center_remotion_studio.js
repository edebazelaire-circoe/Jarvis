/* Carte « Remotion » et Studio optionnel du Control Center (jarvis-remotion-presentation-integration, Slice 11).

   Contrat : `docs/remotion-studio.md` §8. Placée en tête de l'onglet « Plugins externes » du dialogue MCP
   (`#mcpPlugins`), au-dessus des cartes de plugins MCP : c'est la « carte unique » que `docs/local-capabilities.md` §1 annonçait
   pour les capacités locales, sans toucher au rendu des plugins distants. Deux parties :

   - `JarvisRemotionStudioCore`, logique pure exécutée telle quelle par les tests node : vocabulaire des états, codes traduits,
     modèle de la carte (libellés, actions possibles, compteurs), client HTTP des six adresses relayées ;
   - un bloc navigateur qui rend la carte et relit l'état.

   QUATRE RÈGLES.
   1. SUR DEMANDE SEULEMENT. Remotion Studio ne s'ouvre que par un clic (« Ouvrir Remotion Studio » ici, « Remotion Studio » sous la
      vidéo de Variantes, native-studio-playback-fix Slice 11) ; rien ne le lance à l'affichage, à la relecture ni depuis l'aperçu.
   Noms (PX-1, `docs/presentation-studio.md` § 1) : ce que l'utilisateur lit dit toujours « Remotion Studio », jamais « Studio » tout court.
   2. CE QUI ATTEND SE VOIT : pastille animée, durée écoulée, échéance (« 2 min au plus »), arrêt automatique décompté.
   3. L'ÉTAT EST CELUI DE CORE, avec son code stable ; un échec dit ce qui s'est passé (journal du Studio, code), jamais « erreur ».
   4. AUCUN NOM NI CHEMIN EN DUR : seules les scènes que la bibliothèque rend (`/api/prefabs?engine=remotion`) sont proposées ;
      aucune adresse du disque n'est affichée (Core n'en rend pas). */

const JarvisRemotionStudioCore=(function(){
  'use strict';

  const ROUTE='/api/local-capabilities/remotion';
  const STUDIO=ROUTE+'/studio';
  const PREFABS='/api/prefabs?engine=remotion&limit=50';
  const READ_DEADLINE_MS=15000;
  /* Démarrage : Core attend 120 s au plus, le relais 150 s. */
  const START_DEADLINE_MS=160000;
  const SHORT_DEADLINE_MS=45000;
  const START_LIMIT_S=120;
  const POLL_FAST_MS=2000;
  const POLL_SLOW_MS=10000;
  /* `publish` (native-studio-playback-fix Slice 12) : compilation réelle et attente du tour comprises, Core répond en 135 s au plus, le relais 150 s. */
  const PUBLISH_DEADLINE_MS=160000;
  const PUBLISH_LIMIT_S=150;
  const WRITES=Object.freeze({open:START_DEADLINE_MS,restart:START_DEADLINE_MS,sync:SHORT_DEADLINE_MS,close:SHORT_DEADLINE_MS,publish:PUBLISH_DEADLINE_MS});
  /* Champs que seule la page ajoute après une confirmation de l'utilisateur (jamais le cerveau : il n'a pas de chemin ici). */
  const CONFIRM_PUBLISH='confirm_publish';
  const DISCARD_FIELD='discard_unpublished';

  const STATUS=Object.freeze({
    stopped:{label:'Arrêté',tone:''},
    starting:{label:'Démarrage…',tone:'on'},
    ready:{label:'Prêt',tone:'ok'},
    stopping:{label:'Arrêt…',tone:'on'},
    failed:{label:'En échec',tone:'bad'},
  });
  const CAPABILITY=Object.freeze({
    not_installed:{label:'Non installé',tone:'warn'},installing:{label:'Installation…',tone:'on'},ready:{label:'Prêt',tone:'ok'},
    running:{label:'Prêt',tone:'ok'},crashed:{label:'Processus arrêté',tone:'warn'},repair_needed:{label:'À réparer',tone:'warn'},
    install_failed:{label:'Installation en échec',tone:'bad'},disabled:{label:'Désactivé',tone:''},starting:{label:'Prêt',tone:'ok'},
  });
  const STOP_REASON=Object.freeze({
    user:'Fermé à votre demande.',idle_timeout:'Arrêté automatiquement : plus aucune fenêtre ni activité.',
    core_stopped:'Arrêté avec Jarvis.',capability_change:'Arrêté avant un changement de l’environnement Remotion.',restart:'Relancé.',
  });
  /* Codes de Core (`docs/remotion-studio.md` §7), en phrases. Un code inconnu s'affiche tel quel. */
  const ERRORS=Object.freeze({
    remotion_studio_invalid:'La demande est mal formée.',
    remotion_studio_busy:'Une autre opération sur Remotion Studio est en cours : attendez qu’elle finisse.',
    remotion_studio_runtime_unavailable:'L’environnement Remotion n’est pas prêt. Installez-le ou réparez-le d’abord (action explicite sur Core), puis réessayez.',
    remotion_studio_source_unavailable:'Cette version de scène n’existe pas ou n’est pas une source Remotion saine.',
    remotion_studio_not_running:'Remotion Studio n’est pas ouvert : ouvrez-le d’abord.',
    remotion_studio_port_unavailable:'Le port demandé pour Remotion Studio est déjà utilisé sur ce poste.',
    remotion_studio_start_failed:'Remotion Studio n’a pas démarré. Son journal dit pourquoi.',
    remotion_studio_start_timeout:'Remotion Studio n’a pas répondu dans le délai (2 min). Réessayez.',
    remotion_studio_health_failed:'Remotion Studio ne répond plus ; il a été arrêté. Rouvrez-le.',
    remotion_studio_process_exited:'Le processus de Remotion Studio a disparu (fermé hors de Jarvis ou plantage). Rouvrez-le.',
    remotion_studio_stop_failed:'Remotion Studio n’a pas pu être arrêté : un processus peut rester actif. Réessayez la fermeture.',
    remotion_studio_sync_failed:'La scène n’a pas pu être rafraîchie dans Remotion Studio.',
    remotion_studio_store_failed:'L’état de Remotion Studio n’a pas pu être lu ou écrit sur le disque.',
    remotion_studio_internal_error:'Défaut interne de Remotion Studio.',
    remotion_studio_unavailable:'Ce Core n’a pas de Remotion Studio.',
    remotion_studio_ack_required:'Il faut confirmer que la scène s’exécutera sans bac à sable.',
    remotion_studio_state_unreadable:'Le fichier d’état de Remotion Studio est illisible : mettez-le de côté (studio/state.json), puis réessayez.',
    remotion_studio_unpublished_edits:'Des fichiers modifiés dans Remotion Studio ne sont pas publiés : publiez-les dans la variante, ou confirmez leur mise de côté.',
    remotion_studio_publish_confirm_required:'La publication demande votre confirmation.',
    remotion_studio_publish_nothing:'Rien à publier : l’espace de travail de Remotion Studio n’a aucune modification.',
    remotion_studio_publish_base_mismatch:'L’espace de travail de Remotion Studio a changé de version depuis la dernière lecture : relisez, puis réessayez.',
    remotion_studio_publish_conflict:'La scène a changé dans la variante depuis l’ouverture dans Remotion Studio : rien n’a été publié.',
    remotion_studio_publish_invalid_file:'Un fichier de l’espace de travail ne peut pas faire partie d’une scène (lien, fichier généré ou hors de src/ et public/, nom refusé) : rien n’a été publié.',
    remotion_studio_publish_import_refused:'Un import n’est pas autorisé dans une scène publiée (seuls react et remotion le sont) : rien n’a été publié.',
    remotion_studio_publish_refused:'La variante a refusé la publication (compilation, valeurs ou partition) : rien n’a été publié.',
    remotion_studio_publish_unavailable:'Ce Core ne peut pas publier dans une variante.',
    remotion_studio_publish_listing_changed:'Les fichiers de Remotion Studio ont changé depuis votre confirmation : rien n’a été publié. La liste est relue ; relisez-la, puis publiez de nouveau.',
    core_unreachable:'Core ne répond pas.',core_unconfigured:'Le Control Center ne connaît pas Core.',
    core_timeout:'Core n’a pas répondu à temps : l’issue est inconnue, l’état est relu.',
  });

  function errorText(code){return ERRORS[code]||''}

  /* Accusé obligatoire (B2) : la scène tourne dans l'onglet de Remotion Studio, sans le bac à sable du Player, à l'origine de son API. */
  const ACK_FIELD='acknowledge_unsandboxed_scene';
  const ORIGIN_LABEL=Object.freeze({base:'livrée avec Jarvis',custom:'créée sur ce poste',fork:'dérivée d’une autre scène (fork)',
    revision:'nouvelle version d’une scène',base_edit:'modification d’une scène de base'});
  const ACTOR_LABEL=Object.freeze({user:'vous',brain:'un agent de Jarvis',system:'Jarvis (système)'});
  /* Contenu de la confirmation : le risque nommé, la provenance de LA version, un avertissement renforcé si elle n'a pas été écrite par
     l'utilisateur (agent, système, import) ou si sa provenance est inconnue. `provenance` : `publication.provenance` de Core, ou null. */
  function confirmSpec(scene,provenance,kind){
    const known=provenance&&typeof provenance==='object';
    const actor=known&&provenance.created_by&&provenance.created_by.actor;
    const origin=known&&provenance.origin;
    const own=actor==='user';
    const lines=[
      ['Sans bac à sable : ','la scène s’exécute dans votre navigateur avec les droits d’une page web, pas dans le lecteur isolé de Jarvis.'],
      ['Même origine que l’API de Remotion Studio : ','elle peut appeler cette API (lecture de sa copie de travail).'],
      ['Données : ','sa source et ses paramètres peuvent sortir de ce poste (Remotion Studio bloque les connexions, mais pas tous les canaux d’un navigateur).'],
      ['Version : ',`${scene.label||scene.id}`],
      ['Provenance : ',known?`${ORIGIN_LABEL[origin]||String(origin)} · auteur : ${ACTOR_LABEL[actor]||String(actor)}`:'inconnue (lecture impossible)'],
    ];
    if(!own)lines.push(['Attention : ',known?'cette version n’a pas été écrite par vous (agent, système ou import) et n’a peut-être pas été relue. Ne l’ouvrez que si vous lui faites confiance.'
      :'sa provenance n’a pas pu être vérifiée. Ne l’ouvrez que si vous lui faites confiance.']);
    const verbs={open:'Ouvrir cette scène dans Remotion Studio',restart:'Relancer Remotion Studio',switch:'Afficher cette scène dans Remotion Studio'};
    return {title:own?'Ouvrir cette scène hors du bac à sable ?':'Ouvrir une scène que vous n’avez pas écrite ?',lines,
      confirmLabel:verbs[kind]||verbs.open,cancelLabel:'Annuler',danger:!own,own};
  }

  /* Une seule phrase par message d'erreur de notification : `sub` et `kind` sont les champs de `toast` de la page. */
  function failureToast(error,fallback){return {title:'Remotion Studio',sub:errorText(error&&error.code)||(error&&error.message)||fallback||'L’action a échoué.',kind:'error'}}

  function fmtDuration(seconds){
    const s=Math.max(0,Math.round(seconds));
    if(s<60)return `${s} s`;
    const m=Math.floor(s/60),r=s%60;
    return r?`${m} min ${String(r).padStart(2,'0')} s`:`${m} min`;
  }

  /* Modèle de la carte : tout ce que le rendu affiche, calculé depuis les vues de Core et l'instant `now` (ms). */
  function viewModel(studio,capability,scene,now){
    const st=studio&&STATUS[studio.status]?studio.status:'stopped';
    const info=STATUS[st];
    const capStatus=capability&&capability.status;
    const cap=CAPABILITY[capStatus]||{label:capStatus?String(capStatus):'Inconnu',tone:''};
    const runnable=capStatus==='ready'||capStatus==='running';
    const busy=st==='starting'||st==='stopping';
    const ready=st==='ready';
    const model={status:st,label:info.label,tone:info.tone,capability:{label:cap.label,tone:cap.tone,runnable},activity:null,url:null,
      note:null,error:null,diagnostics:[],actions:{open:{label:'Ouvrir Remotion Studio',enabled:false,why:''},sync:{enabled:false},restart:{enabled:false},close:{enabled:false}}};
    if(!studio){model.activity={text:'Lecture de l’état de Remotion Studio…',spin:true};return model}
    const pin=studio.pin||null;
    const differs=!!(ready&&pin&&scene&&(scene.id!==pin.prefab_id||Number(scene.version)!==Number(pin.version)));
    if(ready)model.actions.open.label=differs?'Afficher cette scène':'Ouvrir Remotion Studio';
    const canOpen=!busy&&!!scene&&runnable&&(!ready||differs);
    model.actions.open.enabled=canOpen||(ready&&!differs&&!!studio.url);
    if(!scene)model.actions.open.why='Aucune scène Remotion dans la bibliothèque.';
    else if(!runnable)model.actions.open.why='L’environnement Remotion n’est pas prêt.';
    model.actions.sync.enabled=ready;
    model.actions.restart.enabled=!busy&&!!pin&&runnable;
    model.actions.close.enabled=ready||st==='failed';
    if(st==='starting'){
      const since=studio.started_at?Math.max(0,now/1000-studio.started_at):0;
      model.activity={text:`Démarrage de Remotion Studio… ${fmtDuration(since)} écoulées, ${START_LIMIT_S/60} min au plus.`,spin:true,since};
    }else if(st==='stopping'){
      model.activity={text:'Arrêt de Remotion Studio…',spin:true};
    }else if(ready){
      model.url=studio.url;
      const parts=[];
      if(studio.port)parts.push(`127.0.0.1:${studio.port}`);
      parts.push(studio.viewers>0?`${studio.viewers} fenêtre${studio.viewers>1?'s':''} ouverte${studio.viewers>1?'s':''}`:'aucune fenêtre ouverte');
      if(typeof studio.idle_in_s==='number'&&studio.viewers===0)parts.push(`arrêt automatique dans ${fmtDuration(studio.idle_in_s)}`);
      if(studio.syncs>0)parts.push(`scène rafraîchie ${studio.syncs} fois`);
      model.activity={text:parts.join(' · '),spin:false};
    }else if(st==='stopped'&&studio.stop_reason){
      model.note=STOP_REASON[studio.stop_reason]||studio.stop_reason;
    }
    if(st==='failed'){
      const code=studio.last_error_code||'';
      model.error={code,text:errorText(code)||studio.last_error_detail||'Remotion Studio est en échec.',detail:studio.last_error_detail||''};
    }
    model.diagnostics=(studio.diagnostics||[]).slice(-12);
    const wc=studio.work_copy||{};
    model.edits={modified:typeof wc.unpublished==='number'?wc.unpublished:(wc.modified_files||[]).length,saved:wc.edits_saved||0};
    model.egressBlocked=studio.egress_blocked||0;
    model.pin=pin;
    model.portMode=studio.port_mode;
    return model;
  }

  function sceneOption(row){
    if(!row||typeof row.id!=='string')return null;
    const version=Number(row.latest_version);
    if(!Number.isInteger(version)||version<1)return null;
    return {id:row.id,version,label:`${row.title||row.id} · v${version}`};
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
        /* Slice 12 : l'enveloppe d'une publication refusée porte `publish_code`, `diagnostics`, `files`, `base` / `current` : gardés dans `info`. */
        throw Object.assign(new Error(e.message||`HTTP ${response.status}`),{code:e.code||`http_${response.status}`,status:response.status,info:e});
      }
      return payload;
    }
    return {
      capability:()=>request('GET',ROUTE,{deadline:READ_DEADLINE_MS}).then(p=>p.capability),
      studio:()=>request('GET',STUDIO,{deadline:READ_DEADLINE_MS}).then(p=>p.studio),
      scenes:()=>request('GET',PREFABS,{deadline:READ_DEADLINE_MS}).then(p=>(p.prefabs||[]).map(sceneOption).filter(Boolean)),
      /* Provenance de la version exacte (`/api/prefabs/{id}/{version}`, lecture) : null si illisible, jamais devinée. */
      provenance:(id,version)=>request('GET',`/api/prefabs/${encodeURIComponent(id)}/${Number(version)}`,{deadline:READ_DEADLINE_MS})
        .then(p=>(p&&p.publication&&p.publication.provenance)||null).catch(()=>null),
      write(action,body){
        if(!Object.prototype.hasOwnProperty.call(WRITES,action))throw new Error('unknown Studio action');
        const acked=(action==='open'||action==='restart'||(action==='sync'&&body&&body.prefab_id))?{...(body||{}),[ACK_FIELD]:true}
          :action==='publish'?{...(body||{}),[CONFIRM_PUBLISH]:true}:(body===undefined?{}:body);
        /* `publish` rend aussi son issue (`publish`) : la vue est jointe sous `studio` comme pour les autres écritures. */
        return request('POST',`${STUDIO}/${action}`,{body:acked,deadline:WRITES[action]}).then(p=>action==='publish'?p:p.studio);
      },
    };
  }

  return {ROUTE,STUDIO,PREFABS,STATUS,CAPABILITY,ERRORS,STOP_REASON,WRITES,START_LIMIT_S,POLL_FAST_MS,POLL_SLOW_MS,ACK_FIELD,
    CONFIRM_PUBLISH,DISCARD_FIELD,PUBLISH_LIMIT_S,
    errorText,fmtDuration,viewModel,sceneOption,createClient,confirmSpec,failureToast};
})();

if(typeof module!=='undefined'&&module.exports)module.exports=JarvisRemotionStudioCore;
/* Variantes (native-studio-playback-fix Slice 11, `control_center_presentation_studio_explorer_remotion.js`) lit ce même noyau : un seul client,
   une seule confirmation, un seul vocabulaire pour les deux portes de Remotion Studio. */
if(typeof window!=='undefined')window.JarvisRemotionStudioCore=JarvisRemotionStudioCore;

/* --------------------------------------------------------------------------
   Navigateur : rend la carte dans `#rmsCard` quand l'onglet « Plugins externes » est visible, relit l'état (2 s pendant un
   démarrage ou un arrêt, 10 s sinon), compte les secondes localement entre deux lectures. Ne lance jamais rien d'elle-même.
   -------------------------------------------------------------------------- */
(function installJarvisRemotionStudio(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const C=JarvisRemotionStudioCore;
  const host=document.getElementById('rmsCard');
  const dialog=document.getElementById('mcpInspector');
  const pane=document.getElementById('mcpPlugins');
  if(!host||!dialog||!pane)return;
  const client=C.createClient({fetchImpl:(path,options)=>window.fetch(path,options)});
  const S={studio:null,capability:null,scenes:[],sceneKey:'',loading:false,busy:'',readError:null,actionError:null,fetchedAt:0,
    poll:null,clock:null,gen:0,rendered:'',deferred:false,techOpen:false};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const log=(level,event,data)=>{const line=`[remotion-studio] ${event} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line)};
  const notify=spec=>{if(typeof toast==='function')toast(spec)};
  const visible=()=>!dialog.hidden&&!pane.hidden;

  function selectedScene(){return S.scenes.find(s=>`${s.id}@${s.version}`===S.sceneKey)||S.scenes[0]||null}

  const ACT='%%ACTIVITY%%';
  function render(){
    const scene=selectedScene();
    const now=Date.now();
    const studio=S.studio?{...S.studio}:null;
    /* Compteurs locaux entre deux lectures : durée de démarrage et décompte d'inactivité avancent à la seconde. */
    if(studio&&typeof studio.idle_in_s==='number')studio.idle_in_s=Math.max(0,studio.idle_in_s-(now-S.fetchedAt)/1000);
    const m=C.viewModel(studio,S.capability,scene,now);
    const activityText=m.activity?m.activity.text:'';
    const sceneSelect=S.scenes.length?`<label class="rms-scene"><span>Scène</span><select id="rmsScene" aria-label="Scène à afficher dans Remotion Studio"${S.busy||m.status==='starting'?' disabled':''}>${
      S.scenes.map(s=>`<option value="${esc(s.id)}@${s.version}"${scene&&s.id===scene.id&&s.version===scene.version?' selected':''}>${esc(s.label)}</option>`).join('')}</select></label>`
      :`<p class="rms-none">Aucune scène Remotion dans la bibliothèque : Remotion Studio s’ouvre sur une scène publiée.</p>`;
    const btn=(id,label,enabled,cls='',title='')=>`<button type="button" class="action small ${cls}" id="${id}"${enabled&&!S.busy?'':' disabled'}${title?` title="${esc(title)}"`:''}>${esc(label)}</button>`;
    const activity=m.activity?`<p class="mcpp-activity rms-activity" id="rmsActivity">${m.activity.spin?'<span class="mcpp-spin" aria-hidden="true"></span>':''}<span id="rmsActivityText">${ACT}</span></p>`:'';
    const link=m.url?`<p class="rms-link"><a class="mcpp-link" id="rmsOpenLink" href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">Ouvrir l’onglet Remotion Studio</a>${
      ' <span class="rms-hint">Ouverture dans un onglet à part ; Remotion Studio n’est jamais affiché dans cette page.</span>'}</p>`:'';
    const failure=m.error?`<div class="mcpp-lasterr rms-err" role="alert"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(m.error.text)} <code>${esc(m.error.code)}</code></span></div>`:'';
    const actionError=S.actionError?`<div class="mcpp-lasterr rms-err" role="alert"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(S.actionError.text)} <code>${esc(S.actionError.code)}</code></span></div>`:'';
    const readError=S.readError?`<p class="mcpp-lasterr rms-err" role="status"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(S.readError.text)} <code>${esc(S.readError.code)}</code> L’état affiché est le dernier connu.</span></p>`:'';
    const diag=m.diagnostics.length?`<details class="mcpp-tech" id="rmsTech"${S.techOpen?' open':''}><summary>Journal de Remotion Studio (${m.diagnostics.length})</summary><pre class="rms-log">${esc(m.diagnostics.join('\n'))}</pre></details>`:'';
    const edits=m.edits&&(m.edits.modified||m.edits.saved)?`<p class="rms-hint">${m.edits.modified?`${m.edits.modified} fichier(s) modifié(s) dans Remotion Studio, pas encore publiés : ils restent dans son espace de travail (même fermé). Pour une scène d’une présentation, « Publier dans la variante… » sous la vidéo de Variantes. `:''}${m.edits.saved?`${m.edits.saved} fichier(s) mis de côté (studio-edits) à votre demande ; pas publiés.`:''}</p>`:'';
    /* Le nœud `aria-live` (`#rmsBusy`) est créé une fois et jamais remplacé : son texte seul change, sinon le lecteur d'écran l'annonce à chaque rendu. */
    const html=`<article class="mcpp-card rms-card" data-state="${m.status==='failed'?'error':m.status==='stopped'?'off':'on'}" aria-labelledby="rmsTitle">
      <div class="mcpp-top"><span class="mcpp-avatar" aria-hidden="true"><span class="mcpp-letter">R</span></span>
        <div class="mcpp-ident"><h3 class="mcpp-name" id="rmsTitle">Remotion Studio</h3>
          <span class="mcpp-host">L’éditeur de Remotion sur une scène, dans un onglet à part, ouvert seulement à votre demande. Pour une scène d’une présentation : Variantes, « Remotion Studio » sous la vidéo (la version exacte de la variante)</span></div>
        <div class="mcpp-badges"><span class="chip ${m.capability.tone}" title="Environnement Remotion installé sur ce poste">Environnement : ${esc(m.capability.label)}</span><span class="chip ${m.tone}" id="rmsStatus">${esc(m.label)}</span></div></div>
      ${sceneSelect}${activity}${link}${failure}${actionError}${readError}${m.note?`<p class="rms-hint">${esc(m.note)}</p>`:''}${edits}${diag}
      <div class="mcpp-foot rms-foot">
        ${btn('rmsOpen',m.actions.open.label,m.actions.open.enabled,'primary',m.actions.open.why)}
        ${btn('rmsSync','Actualiser la scène',m.actions.sync.enabled,'','Recopier la dernière version publiée ; Remotion Studio se recharge sans redémarrer')}
        ${btn('rmsRestart','Relancer',m.actions.restart.enabled)}
        ${btn('rmsClose','Fermer Remotion Studio',m.actions.close.enabled,'danger')}</div>
    </article>`;
    if(!host.querySelector('#rmsBusy')){
      const live=document.createElement('div');live.id='rmsBusy';live.className='rms-busy';live.setAttribute('aria-live','polite');
      host.append(live);
    }
    const busy=host.querySelector('#rmsBusy');
    if(busy.textContent!==S.busy)busy.textContent=S.busy;
    if(html===S.rendered){
      /* Même structure : seuls le texte d'activité (compteurs) et rien d'autre bougent : aucun nœud n'est remplacé. */
      const node=host.querySelector('#rmsActivityText');
      if(node&&node.textContent!==activityText)node.textContent=activityText;
      return;
    }
    /* Une liste déroulante ouverte (ou un champ focalisé) ne doit pas être détruite par un rendu d'arrière-plan : on diffère. */
    const active=document.activeElement;
    if(active&&host.contains(active)&&active.id==='rmsScene'&&S.rendered){S.deferred=true;return}
    const focusId=active&&host.contains(active)?active.id:'';
    const card=host.querySelector('.rms-card');
    const wrapper=document.createElement('div');
    wrapper.innerHTML=html.replace(ACT,esc(activityText));
    if(card)card.replaceWith(wrapper.firstElementChild);else host.prepend(wrapper.firstElementChild);
    S.rendered=html;S.deferred=false;
    if(focusId){const back=document.getElementById(focusId);if(back&&!back.disabled)back.focus()}
  }

  async function refresh(){
    if(S.loading)return;
    S.loading=true;
    const gen=++S.gen;
    try{
      const [studio,capability]=await Promise.all([client.studio(),client.capability()]);
      if(gen!==S.gen)return;
      S.studio=studio;S.capability=capability;S.readError=null;S.fetchedAt=Date.now();
    }catch(error){
      S.readError={code:error.code||'network',text:C.errorText(error.code)||'Impossible de lire l’état de Remotion Studio.'};
      log('warn','remotion.studio.read_failed',{code:error.code,status:error.status});
    }finally{S.loading=false}
    render();schedule();
  }

  async function loadScenes(){
    try{
      S.scenes=await client.scenes();
      if(!S.sceneKey&&S.scenes[0])S.sceneKey=`${S.scenes[0].id}@${S.scenes[0].version}`;
    }catch(error){
      S.scenes=[];
      log('warn','remotion.studio.scenes_failed',{code:error.code,status:error.status});
    }
    render();
  }

  function schedule(){
    clearTimeout(S.poll);
    if(!visible())return;
    const fast=S.studio&&(S.studio.status==='starting'||S.studio.status==='stopping')||S.busy;
    S.poll=setTimeout(refresh,fast?C.POLL_FAST_MS:C.POLL_SLOW_MS);
  }

  /* Confirmation (B2) : jamais d'accusé envoyé sans que l'utilisateur ait lu le risque et la provenance de CETTE version. */
  async function confirmUnsandboxed(scene,kind){
    if(typeof confirmDialog!=='function'){
      S.actionError={code:'confirmation_unavailable',text:'La confirmation n’est pas disponible dans cette page : Remotion Studio n’a pas été ouvert.'};
      render();return false;
    }
    const provenance=await client.provenance(scene.id,scene.version);
    return confirmDialog(C.confirmSpec(scene,provenance,kind));
  }

  async function act(action,label,body,scene,kind){
    if(S.busy)return;
    if(scene&&!await confirmUnsandboxed(scene,kind))return;
    S.busy=label;S.actionError=null;render();
    /* Pendant un démarrage, l'état de Core (« starting ») est relu toutes les 2 s : l'écran montre le compteur. */
    schedule();
    const started=Date.now();
    try{
      const studio=await client.write(action,body);
      S.studio=studio;S.fetchedAt=Date.now();
      log('info','remotion.studio.action_done',{action,status:studio.status,seconds:Math.round((Date.now()-started)/1000)});
      if(studio.status==='failed')notify(C.failureToast({code:studio.last_error_code},'Remotion Studio est en échec.'));
      else if((action==='open'||action==='restart')&&studio.status==='ready'&&studio.url){
        /* Un navigateur peut refuser l'ouverture après une longue attente (plus de geste récent) : le lien reste affiché. */
        window.open(studio.url,'jarvis-remotion-studio','noopener,noreferrer');
      }
    }catch(error){
      if(error.code==='remotion_studio_unpublished_edits'&&!(body&&body[C.DISCARD_FIELD])){
        /* Slice 12 : jamais un remplacement silencieux. Les fichiers non publiés sont nommés ; les mettre de côté est un geste confirmé. */
        S.busy='';render();
        log('info','remotion.studio.unpublished_kept',{action,count:error.info&&error.info.count});
        if(await confirmDiscard(error))return act(action,label,{...(body||{}),[C.DISCARD_FIELD]:true});
        return;
      }
      S.actionError={code:error.code||'network',text:C.errorText(error.code)||error.message||'L’action a échoué.'};
      log('error','remotion.studio.action_failed',{action,code:error.code,status:error.status});
      notify(C.failureToast(error));
    }finally{S.busy=''}
    render();
    refresh();
  }

  async function confirmDiscard(error){
    const info=error.info||{},files=Array.isArray(info.files)?info.files:[],count=Number(info.count)||files.length;
    if(typeof confirmDialog!=='function'){
      S.actionError={code:error.code,text:C.errorText(error.code)};render();return false;
    }
    const base=info.base?` (faites sur ${info.base.prefab_id} v${info.base.version})`:'';
    return confirmDialog({title:'Mettre de côté les fichiers non publiés ?',
      lines:[['Fichiers : ',`${count} fichier${count>1?'s':''} modifié${count>1?'s':''} dans Remotion Studio${base} : ${files.slice(0,6).join(', ')}${files.length>6?'…':''}`],
        ['Ce qui se passe : ','ils sont copiés dans studio-edits (à côté de l’environnement Remotion), puis remplacés par la scène demandée. Ils ne sont pas publiés.'],
        ['Pour les garder dans la variante : ','annulez, puis « Publier dans la variante… » depuis Variantes, sur la scène qu’ils modifient.']],
      confirmLabel:'Mettre de côté et continuer',cancelLabel:'Annuler',danger:true});
  }

  host.addEventListener('click',event=>{
    const button=event.target.closest&&event.target.closest('button');
    if(!button||button.disabled)return;
    const scene=selectedScene();
    if(button.id==='rmsOpen'){
      const ready=S.studio&&S.studio.status==='ready';
      const same=ready&&scene&&S.studio.pin&&S.studio.pin.prefab_id===scene.id&&Number(S.studio.pin.version)===scene.version;
      if(same&&S.studio.url){window.open(S.studio.url,'jarvis-remotion-studio','noopener,noreferrer');return}
      if(scene)act('open',ready?'Changement de scène…':'Ouverture de Remotion Studio…',{prefab_id:scene.id,version:scene.version},scene,ready?'switch':'open');
    }else if(button.id==='rmsSync')act('sync','Rafraîchissement de la scène…');
    else if(button.id==='rmsRestart'){
      const pin=S.studio&&S.studio.pin;
      const known=pin&&S.scenes.find(x=>x.id===pin.prefab_id)||(pin?{id:pin.prefab_id,version:Number(pin.version),label:`${pin.prefab_id} · v${pin.version}`}:null);
      act('restart','Relance de Remotion Studio…',undefined,known&&{...known,version:pin?Number(pin.version):known.version},'restart');
    }
    else if(button.id==='rmsClose')act('close','Fermeture de Remotion Studio…');
  });
  host.addEventListener('change',event=>{
    if(event.target&&event.target.id==='rmsScene'){S.sceneKey=event.target.value;S.rendered='';S.deferred=false;render()}
  });
  /* Le rendu différé pendant qu'une liste était ouverte se fait dès qu'elle perd le focus. */
  host.addEventListener('focusout',()=>{if(S.deferred)setTimeout(render,0)});
  host.addEventListener('toggle',event=>{if(event.target&&event.target.id==='rmsTech')S.techOpen=event.target.open},true);

  function start(){
    if(!visible())return;
    refresh();
    if(!S.scenes.length)loadScenes();
    clearInterval(S.clock);
    S.clock=setInterval(()=>{if(visible())render();else{clearInterval(S.clock);clearTimeout(S.poll)}},1000);
  }
  const observer=new MutationObserver(()=>{if(visible())start();else{clearTimeout(S.poll);clearInterval(S.clock)}});
  observer.observe(dialog,{attributes:true,attributeFilter:['hidden']});
  observer.observe(pane,{attributes:true,attributeFilter:['hidden']});
  render();
  start();
  window.JarvisRemotionStudio={state:S,refresh};
})();
