/* Carte « Remotion » et Studio optionnel du Control Center (jarvis-remotion-presentation-integration, Slice 11).

   Contrat : `docs/remotion-studio.md` §8. Placée en tête de l'onglet « Plugins externes » du dialogue MCP
   (`#mcpPlugins`), au-dessus des cartes de plugins MCP : c'est la « carte unique » que `docs/local-capabilities.md` §1 annonçait
   pour les capacités locales, sans toucher au rendu des plugins distants. Deux parties :

   - `JarvisRemotionStudioCore`, logique pure exécutée telle quelle par les tests node : vocabulaire des états, codes traduits,
     modèle de la carte (libellés, actions possibles, compteurs), client HTTP des six adresses relayées ;
   - un bloc navigateur qui rend la carte et relit l'état.

   QUATRE RÈGLES.
   1. SUR DEMANDE SEULEMENT. Le Studio ne s'ouvre que par le bouton « Ouvrir le Studio » ; rien ne le lance à l'affichage, à la
      relecture ni depuis l'aperçu.
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
  const WRITES=Object.freeze({open:START_DEADLINE_MS,restart:START_DEADLINE_MS,sync:SHORT_DEADLINE_MS,close:SHORT_DEADLINE_MS});

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
    remotion_studio_busy:'Une autre opération sur le Studio est en cours : attendez qu’elle finisse.',
    remotion_studio_runtime_unavailable:'L’environnement Remotion n’est pas prêt. Installez-le ou réparez-le d’abord (action explicite sur Core), puis réessayez.',
    remotion_studio_source_unavailable:'Cette version de scène n’existe pas ou n’est pas une source Remotion saine.',
    remotion_studio_not_running:'Le Studio n’est pas ouvert : ouvrez-le d’abord.',
    remotion_studio_port_unavailable:'Le port demandé pour le Studio est déjà utilisé sur ce poste.',
    remotion_studio_start_failed:'Le Studio n’a pas démarré. Le journal ci-dessous dit pourquoi.',
    remotion_studio_start_timeout:'Le Studio n’a pas répondu dans le délai (2 min). Réessayez avec « Relancer ».',
    remotion_studio_health_failed:'Le Studio ne répond plus ; il a été arrêté. Rouvrez-le.',
    remotion_studio_process_exited:'Le processus du Studio a disparu (fenêtre fermée hors de Jarvis ou plantage). Rouvrez-le.',
    remotion_studio_stop_failed:'Le Studio n’a pas pu être arrêté : un processus peut rester actif. Réessayez la fermeture.',
    remotion_studio_sync_failed:'La scène n’a pas pu être rafraîchie dans le Studio.',
    remotion_studio_store_failed:'L’état du Studio n’a pas pu être lu ou écrit sur le disque.',
    remotion_studio_internal_error:'Défaut interne du Studio.',
    remotion_studio_unavailable:'Ce Core n’a pas de Studio Remotion.',
    core_unreachable:'Core ne répond pas.',core_unconfigured:'Le Control Center ne connaît pas Core.',
    core_timeout:'Core n’a pas répondu à temps : l’issue est inconnue, l’état est relu.',
  });

  function errorText(code){return ERRORS[code]||''}

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
      note:null,error:null,diagnostics:[],actions:{open:{label:'Ouvrir le Studio',enabled:false,why:''},sync:{enabled:false},restart:{enabled:false},close:{enabled:false}}};
    if(!studio){model.activity={text:'Lecture de l’état du Studio…',spin:true};return model}
    const pin=studio.pin||null;
    const differs=!!(ready&&pin&&scene&&(scene.id!==pin.prefab_id||Number(scene.version)!==Number(pin.version)));
    if(ready)model.actions.open.label=differs?'Afficher cette scène':'Ouvrir le Studio';
    const canOpen=!busy&&!!scene&&runnable&&(!ready||differs);
    model.actions.open.enabled=canOpen||(ready&&!differs&&!!studio.url);
    if(!scene)model.actions.open.why='Aucune scène Remotion dans la bibliothèque.';
    else if(!runnable)model.actions.open.why='L’environnement Remotion n’est pas prêt.';
    model.actions.sync.enabled=ready;
    model.actions.restart.enabled=!busy&&!!pin&&runnable;
    model.actions.close.enabled=ready||st==='failed';
    if(st==='starting'){
      const since=studio.started_at?Math.max(0,now/1000-studio.started_at):0;
      model.activity={text:`Démarrage du Studio… ${fmtDuration(since)} écoulées, ${START_LIMIT_S/60} min au plus.`,spin:true,since};
    }else if(st==='stopping'){
      model.activity={text:'Arrêt du Studio…',spin:true};
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
      model.error={code,text:errorText(code)||studio.last_error_detail||'Le Studio est en échec.',detail:studio.last_error_detail||''};
    }
    model.diagnostics=(studio.diagnostics||[]).slice(-12);
    const wc=studio.work_copy||{};
    model.edits={modified:(wc.modified_files||[]).length,saved:wc.edits_saved||0};
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
        throw Object.assign(new Error(e.message||`HTTP ${response.status}`),{code:e.code||`http_${response.status}`,status:response.status});
      }
      return payload;
    }
    return {
      capability:()=>request('GET',ROUTE,{deadline:READ_DEADLINE_MS}).then(p=>p.capability),
      studio:()=>request('GET',STUDIO,{deadline:READ_DEADLINE_MS}).then(p=>p.studio),
      scenes:()=>request('GET',PREFABS,{deadline:READ_DEADLINE_MS}).then(p=>(p.prefabs||[]).map(sceneOption).filter(Boolean)),
      write(action,body){
        if(!Object.prototype.hasOwnProperty.call(WRITES,action))throw new Error('unknown Studio action');
        return request('POST',`${STUDIO}/${action}`,{body:body===undefined?{}:body,deadline:WRITES[action]}).then(p=>p.studio);
      },
    };
  }

  return {ROUTE,STUDIO,PREFABS,STATUS,CAPABILITY,ERRORS,STOP_REASON,WRITES,START_LIMIT_S,POLL_FAST_MS,POLL_SLOW_MS,
    errorText,fmtDuration,viewModel,sceneOption,createClient};
})();

if(typeof module!=='undefined'&&module.exports)module.exports=JarvisRemotionStudioCore;

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
    poll:null,clock:null,gen:0,rendered:''};
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const log=(level,event,data)=>{const line=`[remotion-studio] ${event} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line)};
  const notify=spec=>{if(typeof toast==='function')toast(spec)};
  const visible=()=>!dialog.hidden&&!pane.hidden;

  function selectedScene(){return S.scenes.find(s=>`${s.id}@${s.version}`===S.sceneKey)||S.scenes[0]||null}

  function render(){
    const scene=selectedScene();
    const now=Date.now();
    const studio=S.studio?{...S.studio}:null;
    /* Compteurs locaux entre deux lectures : durée de démarrage et décompte d'inactivité avancent à la seconde. */
    if(studio&&typeof studio.idle_in_s==='number')studio.idle_in_s=Math.max(0,studio.idle_in_s-(now-S.fetchedAt)/1000);
    const m=C.viewModel(studio,S.capability,scene,now);
    const sceneSelect=S.scenes.length?`<label class="rms-scene"><span>Scène</span><select id="rmsScene" aria-label="Scène à afficher dans le Studio"${S.busy||m.status==='starting'?' disabled':''}>${
      S.scenes.map(s=>`<option value="${esc(s.id)}@${s.version}"${scene&&s.id===scene.id&&s.version===scene.version?' selected':''}>${esc(s.label)}</option>`).join('')}</select></label>`
      :`<p class="rms-none">Aucune scène Remotion dans la bibliothèque : le Studio s’ouvre sur une scène publiée.</p>`;
    const btn=(id,label,enabled,cls='',title='')=>`<button type="button" class="action small ${cls}" id="${id}"${enabled&&!S.busy?'':' disabled'}${title?` title="${esc(title)}"`:''}>${esc(label)}</button>`;
    const activity=m.activity?`<p class="mcpp-activity rms-activity" id="rmsActivity">${m.activity.spin?'<span class="mcpp-spin" aria-hidden="true"></span>':''}<span>${esc(m.activity.text)}</span></p>`:'';
    const link=m.url?`<p class="rms-link"><a class="mcpp-link" id="rmsOpenLink" href="${esc(m.url)}" target="_blank" rel="noopener noreferrer">Ouvrir la fenêtre du Studio</a>${
      ' <span class="rms-hint">Ouverture dans une fenêtre à part ; le Studio n’est jamais affiché dans cette page.</span>'}</p>`:'';
    const failure=m.error?`<div class="mcpp-lasterr rms-err" role="alert"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(m.error.text)} <code>${esc(m.error.code)}</code></span></div>`:'';
    const actionError=S.actionError?`<div class="mcpp-lasterr rms-err" role="alert"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(S.actionError.text)} <code>${esc(S.actionError.code)}</code></span></div>`:'';
    const readError=S.readError?`<p class="mcpp-lasterr rms-err" role="status"><span class="mcpp-dot" aria-hidden="true"></span><span>${esc(S.readError.text)} <code>${esc(S.readError.code)}</code> L’état affiché est le dernier connu.</span></p>`:'';
    const diag=m.diagnostics.length?`<details class="mcpp-tech"><summary>Journal du Studio (${m.diagnostics.length})</summary><pre class="rms-log">${esc(m.diagnostics.join('\n'))}</pre></details>`:'';
    const edits=m.edits&&(m.edits.modified||m.edits.saved)?`<p class="rms-hint">${m.edits.modified?`${m.edits.modified} fichier(s) modifié(s) dans le Studio : cette copie est en lecture seule et n’est jamais écrite dans la bibliothèque ; elle est mise de côté à la fermeture. `:''}${m.edits.saved?`${m.edits.saved} fichier(s) modifié(s) dans le Studio mis de côté ; la bibliothèque n’a pas été modifiée.`:''}</p>`:'';
    const html=`<article class="mcpp-card rms-card" data-state="${m.status==='failed'?'error':m.status==='stopped'?'off':'on'}" aria-labelledby="rmsTitle">
      <div class="mcpp-top"><span class="mcpp-avatar" aria-hidden="true"><span class="mcpp-letter">R</span></span>
        <div class="mcpp-ident"><h3 class="mcpp-name" id="rmsTitle">Remotion · Studio</h3>
          <span class="mcpp-host">Fenêtre d’édition à chaud d’une scène, ouverte seulement à votre demande</span></div>
        <div class="mcpp-badges"><span class="chip ${m.capability.tone}" title="Environnement Remotion installé sur ce poste">Environnement : ${esc(m.capability.label)}</span><span class="chip ${m.tone}" id="rmsStatus">${esc(m.label)}</span></div></div>
      ${sceneSelect}${activity}${link}${failure}${actionError}${readError}${m.note?`<p class="rms-hint">${esc(m.note)}</p>`:''}${edits}${diag}
      <div class="mcpp-foot rms-foot">
        ${btn('rmsOpen',m.actions.open.label,m.actions.open.enabled,'primary',m.actions.open.why)}
        ${btn('rmsSync','Actualiser la scène',m.actions.sync.enabled,'','Recopier la dernière version publiée ; le Studio se recharge sans redémarrer')}
        ${btn('rmsRestart','Relancer',m.actions.restart.enabled)}
        ${btn('rmsClose','Fermer le Studio',m.actions.close.enabled,'danger')}
        <span class="rms-busy" id="rmsBusy" aria-live="polite">${esc(S.busy)}</span></div>
    </article>`;
    if(html===S.rendered)return;
    const focusId=host.contains(document.activeElement)?document.activeElement.id:'';
    host.innerHTML=html;
    S.rendered=html;
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
      S.readError={code:error.code||'network',text:C.errorText(error.code)||'Impossible de lire l’état du Studio.'};
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

  async function act(action,label,body){
    if(S.busy)return;
    S.busy=label;S.actionError=null;render();
    /* Pendant un démarrage, l'état de Core (« starting ») est relu toutes les 2 s : l'écran montre le compteur. */
    schedule();
    const started=Date.now();
    try{
      const studio=await client.write(action,body);
      S.studio=studio;S.fetchedAt=Date.now();
      log('info','remotion.studio.action_done',{action,status:studio.status,seconds:Math.round((Date.now()-started)/1000)});
      if(studio.status==='failed')notify({title:'Studio Remotion',text:C.errorText(studio.last_error_code)||'Le Studio est en échec.',tone:'bad'});
      else if((action==='open'||action==='restart')&&studio.status==='ready'&&studio.url){
        /* Un navigateur peut refuser l'ouverture après une longue attente (plus de geste récent) : le lien reste affiché. */
        window.open(studio.url,'jarvis-remotion-studio','noopener,noreferrer');
      }
    }catch(error){
      S.actionError={code:error.code||'network',text:C.errorText(error.code)||error.message||'L’action a échoué.'};
      log('error','remotion.studio.action_failed',{action,code:error.code,status:error.status});
      notify({title:'Studio Remotion',text:S.actionError.text,tone:'bad'});
    }finally{S.busy=''}
    render();
    refresh();
  }

  host.addEventListener('click',event=>{
    const button=event.target.closest&&event.target.closest('button');
    if(!button||button.disabled)return;
    const scene=selectedScene();
    if(button.id==='rmsOpen'){
      const ready=S.studio&&S.studio.status==='ready';
      const same=ready&&scene&&S.studio.pin&&S.studio.pin.prefab_id===scene.id&&Number(S.studio.pin.version)===scene.version;
      if(same&&S.studio.url){window.open(S.studio.url,'jarvis-remotion-studio','noopener,noreferrer');return}
      if(scene)act('open',ready?'Changement de scène…':'Ouverture du Studio…',{prefab_id:scene.id,version:scene.version});
    }else if(button.id==='rmsSync')act('sync','Rafraîchissement de la scène…');
    else if(button.id==='rmsRestart')act('restart','Relance du Studio…');
    else if(button.id==='rmsClose')act('close','Fermeture du Studio…');
  });
  host.addEventListener('change',event=>{
    if(event.target&&event.target.id==='rmsScene'){S.sceneKey=event.target.value;S.rendered='';render()}
  });

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
