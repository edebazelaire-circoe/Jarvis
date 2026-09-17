/* Réglage « Scène constellation » de l'onglet Expérimental (handoff
   jarvis-constellation-scene-runtime, Slice 11).

   Deux parties, comme `control_center_barehands.js` :
   - `JarvisSceneSettings.describe(scene, status)`, logique pure : à partir du
     bloc `scene` de `/api/settings` (`enabled`, `source`, `stored`, `env`) et
     du statut (`agent_cli`, `agent.state`, `agent.display_tools`,
     `agent.display_prompt`, `subagents.active`), ce que l'écran dit — interrupteur en lecture seule
     quand l'environnement l'impose, effets de l'interrupteur, état réel du
     brain en cours et redémarrage proposé quand il ne correspond pas au
     choix. Les tests l'exécutent avec node
     (`tests/unit/test_scene_settings_ui.py`) ;
   - un bloc navigateur : la section ajoutée en tête de l'onglet Expérimental
     (écrite par `POST /api/settings`, bloc `scene`), le redémarrage confirmé
     du brain (`confirmDialog` en page, `POST /api/agent/restart`) et la
     relecture de l'état du brain dans les réponses de `/api/status` que la
     page lit déjà (aucune requête de plus).

   Effets réels de l'interrupteur, que l'écran énonce : le rendu apparaît ou
   disparaît dans toutes les fenêtres à la lecture suivante de `/api/status`
   (une seconde au plus, sans rechargement) ; les outils d'affichage du brain
   sont fixés au lancement de son processus et ne changent qu'à son prochain
   démarrage ; Core projette et garde la scène quel que soit l'interrupteur. */
(function(root){
  'use strict';

  const ENV_NAME='JARVIS_SCENE_ENABLED';
  const SETTINGS_ROUTE='/api/settings';
  const RESTART_ROUTE='/api/agent/restart';
  /* Conversation neuve : seule façon que la consigne d'affichage suive le réglage. */
  const RESTART_BODY=Object.freeze({new_conversation:true});
  /* Au-delà, l'écran le dit et rend la main (le brain peut encore démarrer). */
  const RESTART_DEADLINE_MS=30000;

  const plural=(n,one,many)=>`${n} ${n>1?many:one}`;

  function sourceNote(scene){
    if(!scene||scene.source!=='env')return null;
    const name=typeof scene.env==='string'&&scene.env?scene.env:ENV_NAME;
    return {
      title:`Imposé par la variable d'environnement ${name}`,
      detail:`Elle vaut « ${scene.enabled?'activée':'désactivée'} » au lancement du Control Center et l'emporte sur ce réglage : l'interrupteur est en lecture seule. `
        +`Retirez-la puis relancez le Control Center pour choisir ici. Réglage enregistré, ignoré tant qu'elle existe : ${scene.stored?'activée':'désactivée'}.`,
    };
  }

  function effects(){
    return [
      {term:'Affichage',text:'Immédiat : la scène apparaît ou disparaît dans toutes les fenêtres ouvertes du Control Center, sans recharger la page.'},
      {term:'Outils du brain',text:'Au prochain démarrage du brain sur une nouvelle conversation : lire la scène, y composer des objets et des artefacts, la capturer. Jamais archiver.'},
      {term:'Core',text:'Continue de projeter les travaux dans la scène même éteinte : rien n\'est perdu, tout réapparaît à l\'activation.'},
    ];
  }

  function brainView(wanted,status){
    if(!status||typeof status!=='object'||!status.agent||typeof status.agent!=='object')
      return {tone:'info',title:'État du brain inconnu',detail:'Le statut du Control Center n\'a pas pu être lu. Il est relu à chaque seconde.',restart:false};
    const cli=String(status.agent_cli||'');
    if(cli&&cli!=='claude')
      return {tone:'info',title:`Brain ${String(status.agent.name||cli)} : pas d'outils d'affichage`,
        detail:'Seul le brain Claude reçoit les outils de la scène. L\'affichage, lui, suit l\'interrupteur.',restart:false};
    const state=String(status.agent.state||'stopped');
    if(state!=='running')
      return {tone:'info',title:state==='exited'?'Brain terminé':'Brain arrêté',
        detail:wanted?'Il recevra les outils d\'affichage à son prochain démarrage.':'Il démarrera sans outils d\'affichage.',restart:false};
    const tools=status.agent.display_tools===true;
    /* Consigne de la conversation en cours ; absente (agent plus ancien) : on suppose qu'elle suit les outils. */
    const prompt=typeof status.agent.display_prompt==='boolean'?status.agent.display_prompt:tools;
    if(tools===wanted&&prompt===wanted)
      return wanted
        ?{tone:'ok',title:'Brain en cours : outils d\'affichage présents',detail:'Il peut lire, composer et capturer la scène.',restart:false}
        :{tone:'ok',title:'Brain en cours : sans outils d\'affichage',detail:'Il ne voit ni ne modifie la scène.',restart:false};
    const running=Math.max(0,Number(status.subagents&&status.subagents.active)||0);
    /* Nouvelle conversation : le CLI fige la consigne système d'une conversation
       reprise, seuls ses outils suivraient (constaté sur un vrai CLI, Slice 11). */
    const lines=[
      wanted?'Il repart sur une nouvelle conversation, avec les outils et la consigne d\'affichage.':'Il repart sur une nouvelle conversation, sans les outils ni la consigne d\'affichage.',
      'La conversation en cours n\'est pas reprise : une conversation reprise garderait son ancienne consigne.',
      running?`Cela interrompra ${plural(running,'sous-agent en cours','sous-agents en cours')}.`:'Aucun sous-agent n\'est en cours.',
    ];
    let title,detail;
    if(wanted&&!tools){
      title='Brain lancé avant l\'activation : pas encore d\'outils d\'affichage';
      detail='Il ne pourra lire ni composer la scène qu\'après un redémarrage.';
    }else if(wanted){
      title='Conversation reprise : outils présents, consigne d\'affichage absente';
      detail='Il ne crée pas d\'artefacts et ne pense pas à lire la scène tant qu\'il ne repart pas sur une nouvelle conversation.';
    }else if(tools){
      title='Brain lancé scène allumée : il garde ses outils d\'affichage';
      detail='Tant qu\'il n\'est pas redémarré, il peut encore lire et modifier la scène, même masquée.';
    }else{
      title='Conversation reprise : consigne d\'affichage encore active, sans ses outils';
      detail='Il pourrait chercher des outils de scène qu\'il n\'a plus.';
    }
    return {
      tone:'warn',
      title,
      detail,
      restart:true,
      confirm:{title:'Redémarrer le brain ?',lines,confirmLabel:'Redémarrer le brain',danger:running>0},
    };
  }

  /* Modèle de vue complet de la section. `scene` absent : réglages illisibles. */
  function describe(scene,status){
    const known=!!scene&&typeof scene==='object'&&typeof scene.enabled==='boolean';
    const wanted=known&&scene.enabled===true;
    return {
      known,
      checked:wanted,
      readOnly:!known||scene.source==='env',
      source:known?sourceNote(scene):null,
      effects:effects(),
      brain:brainView(wanted,status),
    };
  }

  /* Durée lisible d'une attente en cours (compteur du redémarrage). */
  function elapsedLabel(ms){return `${Math.max(0,Math.floor((Number(ms)||0)/1000))} s`}

  const api=Object.freeze({version:1,ENV_NAME,SETTINGS_ROUTE,RESTART_ROUTE,RESTART_BODY,RESTART_DEADLINE_MS,describe,elapsedLabel});
  root.JarvisSceneSettings=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);

/* --------------------------------------------------------------------------
   Bloc navigateur : section de l'onglet Expérimental. Les tests node ne
   l'exécutent pas.
   -------------------------------------------------------------------------- */
(function installJarvisSceneSettings(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const Logic=window.JarvisSceneSettings;
  const TAB_ID='experimental';
  const SECTION_ID='sceneSettings';
  const view={scene:null,status:null,busy:false,error:'',restart:null};

  const log=(level,event,data)=>{try{console[level==='error'?'error':level==='warn'?'warn':'info']('[scène] '+event,data||{})}catch(_error){/* console absente */}};
  const tabOpen=()=>typeof SET!=='undefined'&&SET.open&&SET.tab===TAB_ID;

  function node(tag,attrs,children){
    const el=document.createElement(tag);
    for(const [key,value] of Object.entries(attrs||{})){
      if(value===null||value===undefined||value===false)continue;
      if(key==='text')el.textContent=value;
      else if(key==='className')el.className=value;
      else el.setAttribute(key,value===true?'':String(value));
    }
    for(const child of children||[])if(child)el.append(child);
    return el;
  }

  function sectionNode(){
    const model=Logic.describe(view.scene,view.status);
    const section=node('section',{id:SECTION_ID,'aria-labelledby':'sceneSettingsTitle','data-scene-settings':''});
    section.append(
      node('h3',{id:'sceneSettingsTitle',text:'Scène constellation · mode test'}),
      node('div',{className:'hint',style:'margin-bottom:14px',text:'Une carte persistante du travail de JARVIS derrière l\'interface : un sous-agent devient une étoile, ses résultats des artefacts reliés, et le brain peut y montrer ce qui compte. Vous déplacez, épinglez, masquez et archivez ; le brain n\'archive jamais.'}),
    );
    const describedBy=['sceneEffects',model.source?'sceneSourceNote':null].filter(Boolean).join(' ');
    /* Occupé : `aria-disabled` plutôt que `disabled`, qui ferait perdre le focus clavier pendant l'écriture. */
    const input=node('input',{type:'checkbox',id:'f_scene','data-scene-toggle':'','aria-describedby':describedBy,
      checked:model.checked,disabled:model.readOnly,'aria-disabled':view.busy?'true':null,'aria-busy':view.busy?'true':null});
    input.checked=model.checked;
    input.addEventListener('click',event=>{if(view.busy)event.preventDefault()});
    const label=node('label',{for:'f_scene'},[document.createTextNode('Afficher la scène et donner ses outils au brain '),node('span',{className:'tag warn',text:'TEST'})]);
    const hint=node('div',{className:'hint',text:view.busy?'Enregistrement…':(model.readOnly&&model.source?'Lecture seule : voir ci-dessous.':'Désactivée par défaut. Enregistré immédiatement.')});
    section.append(node('div',{className:'field inline'},[input,node('div',{},[label,hint])]));
    if(!model.known)section.append(node('div',{className:'notice bad',role:'alert',text:'Réglage de scène illisible : rouvrez les réglages.'}));
    if(view.error)section.append(node('div',{className:'notice bad',role:'alert'},[node('strong',{text:'Réglage non enregistré'}),node('div',{className:'hint',text:view.error})]));
    if(model.source)section.append(node('div',{className:'notice',id:'sceneSourceNote'},[node('strong',{text:model.source.title}),node('div',{className:'hint',text:model.source.detail})]));
    const list=node('dl',{className:'scene-effects',id:'sceneEffects'});
    for(const effect of model.effects)list.append(node('dt',{text:effect.term}),node('dd',{text:effect.text}));
    section.append(list);
    const brain=node('div',{className:`notice ${model.brain.tone==='warn'?'':model.brain.tone}`,id:'sceneBrain',role:'status','aria-live':'polite'},
      [node('strong',{text:model.brain.title}),node('div',{className:'hint',text:model.brain.detail})]);
    if(model.brain.restart||view.restart){
      const running=!!view.restart;
      const button=node('button',{type:'button',className:'action small','data-scene-restart':'','aria-disabled':running?'true':null,'aria-busy':running?'true':null,
        text:running?`Redémarrage du brain… ${Logic.elapsedLabel(Date.now()-view.restart.startedAt)}`:'Redémarrer le brain…'});
      button.addEventListener('click',()=>restartBrain(model.brain.confirm));
      brain.append(node('div',{className:'row',style:'margin-top:10px'},[button]));
    }
    section.append(brain);
    input.addEventListener('change',()=>setEnabled(input.checked));
    return section;
  }

  /* Redessine la section en gardant le focus sur le contrôle qui l'avait. */
  function refresh(){
    if(!tabOpen())return;
    const content=document.getElementById('modalContent');
    const previous=document.getElementById(SECTION_ID);
    if(!content)return;
    const focused=previous&&previous.contains(document.activeElement)?document.activeElement:null;
    const key=focused?(focused.hasAttribute('data-scene-toggle')?'[data-scene-toggle]':focused.hasAttribute('data-scene-restart')?'[data-scene-restart]':null):null;
    const next=sectionNode();
    if(previous)previous.replaceWith(next);else content.prepend(next);
    if(key){
      const target=next.querySelector(key);
      const fallback=next.querySelector('[data-scene-toggle]:not([disabled])')||next.querySelector('h3');
      const el=target&&!target.disabled?target:fallback;
      if(el&&el.tagName==='H3')el.setAttribute('tabindex','-1');
      if(el)try{el.focus({preventScroll:true})}catch(_error){/* élément retiré entre-temps */}
    }
  }

  async function setEnabled(enabled){
    if(view.busy)return;
    view.busy=true;view.error='';refresh();
    log('info','scene.setting_requested',{enabled});
    try{
      const data=await api(Logic.SETTINGS_ROUTE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({scene:{enabled}})});
      if(!data||!data.scene||typeof data.scene.enabled!=='boolean')throw new Error('Réponse des réglages sans bloc scene.');
      view.scene=data.scene;
      if(typeof SET!=='undefined'&&SET.data)SET.data.scene=data.scene;
      log('info','scene.setting_saved',{enabled:data.scene.enabled,source:data.scene.source});
      if(typeof toast==='function')toast({title:data.scene.enabled?'Scène activée':'Scène désactivée',
        sub:'Affichage appliqué maintenant ; outils du brain au prochain démarrage.',kind:'ok',ms:3500});
    }catch(error){
      view.error=String(error&&error.message||error);
      log('error','scene.setting_failed',{enabled,error:view.error,status:error&&error.status});
      if(typeof toast==='function')toast({title:'Réglage de scène non enregistré',sub:view.error,kind:'bad',ms:7000});
    }finally{
      view.busy=false;
      refresh();
      // Rendu et état du brain relus tout de suite plutôt qu'au prochain battement.
      if(typeof refreshStatus==='function')refreshStatus();
    }
  }

  async function restartBrain(confirmation){
    if(view.restart)return;
    const ok=typeof confirmDialog==='function'&&await confirmDialog(confirmation||{title:'Redémarrer le brain ?',lines:[],confirmLabel:'Redémarrer le brain'});
    if(!ok){log('info','scene.brain_restart_cancelled',{});return}
    const controller=typeof AbortController==='function'?new AbortController():null;
    view.restart={startedAt:Date.now(),ticker:null,timer:null};
    view.restart.ticker=setInterval(refresh,1000);
    view.restart.timer=setTimeout(()=>{if(controller)controller.abort()},Logic.RESTART_DEADLINE_MS);
    refresh();
    log('info','scene.brain_restart_requested',{});
    try{
      await api(Logic.RESTART_ROUTE,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Logic.RESTART_BODY),signal:controller?controller.signal:undefined});
      log('info','scene.brain_restarted',{elapsed_ms:Date.now()-view.restart.startedAt});
      if(typeof toast==='function')toast({title:'Brain redémarré',sub:'Nouvelle conversation : outils et consigne d\'affichage suivent maintenant le réglage.',kind:'ok',ms:3500});
    }catch(error){
      const aborted=error&&error.name==='AbortError';
      const message=aborted?`Pas de réponse après ${Math.round(Logic.RESTART_DEADLINE_MS/1000)} s : l'état du brain ci-dessous est relu chaque seconde.`:String(error&&error.message||error);
      log('error','scene.brain_restart_failed',{error:message,status:error&&error.status});
      if(typeof toast==='function')toast({title:'Redémarrage du brain impossible',sub:message,kind:'bad',ms:8000});
    }finally{
      clearInterval(view.restart.ticker);clearTimeout(view.restart.timer);
      view.restart=null;
      refresh();
      if(typeof refreshStatus==='function')refreshStatus();
    }
  }

  const STYLE=`#sceneSettings .scene-effects{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:0 0 16px;font-size:12px;line-height:1.5}
#sceneSettings .scene-effects dt{color:var(--muted);letter-spacing:.04em}
#sceneSettings .scene-effects dd{margin:0}
#sceneSettings [data-scene-toggle]:focus-visible,#sceneSettings [data-scene-restart]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#sceneSettings [aria-disabled=true]{opacity:.6;cursor:wait}
#sceneSettings+section{border-top:1px solid var(--line);padding-top:22px;margin-top:8px}
@media(max-width:560px){#sceneSettings .scene-effects{grid-template-columns:1fr}#sceneSettings .scene-effects dd{margin-bottom:6px}}`;

  function ensureStyle(){
    if(document.getElementById('jarvisSceneSettingsStyle'))return;
    const style=document.createElement('style');
    style.id='jarvisSceneSettingsStyle';style.textContent=STYLE;
    document.head.appendChild(style);
  }

  /* L'onglet Expérimental est créé par Barehands (inséré avant ce fichier) :
     la section s'ajoute en tête de ce qu'il vient de dessiner. */
  function installSection(){
    if(typeof renderTab!=='function'||typeof TABS==='undefined'||!Array.isArray(TABS))return;
    ensureStyle();
    const baseRenderTab=renderTab;
    renderTab=async function(){
      const result=await baseRenderTab.apply(this,arguments);
      if(tabOpen()){
        view.scene=typeof SET!=='undefined'&&SET.data?SET.data.scene||null:null;
        // Onglet redessiné : une erreur d'un essai précédent ne s'affiche plus comme actuelle.
        if(!view.busy)view.error='';
        // Le sous-titre de Barehands dit « appliquées immédiatement » : faux pour les outils du brain.
        const sub=document.getElementById('modalSub');
        if(sub)sub.textContent='Fonctions en test, enregistrées immédiatement ; chaque section dit quand elle prend effet.';
        refresh();
      }
      return result;
    };
  }

  /* Le statut que la page lit déjà chaque seconde nourrit l'état du brain. */
  function observeStatus(){
    if(typeof api!=='function')return;
    const baseApi=api;
    api=async function(path,opts){
      const value=await baseApi(path,opts);
      if(typeof path==='string'&&path.split('?')[0]==='/api/status'&&value&&typeof value==='object'){
        const before=JSON.stringify(Logic.describe(view.scene,view.status).brain);
        view.status={agent_cli:value.agent_cli,agent:value.agent?{name:value.agent.name,state:value.agent.state,display_tools:value.agent.display_tools}:null,subagents:value.subagents};
        if(tabOpen()&&!view.restart&&JSON.stringify(Logic.describe(view.scene,view.status).brain)!==before)refresh();
      }
      return value;
    };
  }

  setTimeout(()=>{installSection();observeStatus()},0);
  window.JarvisSceneSettingsView=Object.freeze({inspect:()=>({scene:view.scene,status:view.status,busy:view.busy,error:view.error,restarting:!!view.restart})});
})();
