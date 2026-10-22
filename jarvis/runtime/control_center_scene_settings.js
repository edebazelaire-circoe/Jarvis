/* Réglage « Scène constellation » (handoff jarvis-constellation-scene-runtime,
   Slice 11), section `scene_gate` du groupe Labs & outils de test d'Avancé &
   diagnostic depuis la Slice 08 de jarvis-settings-ui-reorganization (ancien
   onglet Expérimental ; son identifiant n'est plus un alias depuis la Slice 09).

   Deux parties, comme `control_center_barehands.js` :
   - `JarvisSceneSettings.describe(scene, status)`, logique pure : à partir du
     bloc `scene` de `/api/settings` (`enabled`, `source`, `stored`, `env`) et
     du statut (`agent_cli`, `agent.state`, `agent.display_tools`,
     `agent.display_prompt`, `subagents.active`), ce que l'écran dit — interrupteur en lecture seule
     quand l'environnement l'impose, effets de l'interrupteur, état réel du
     brain en cours et redémarrage proposé quand il ne correspond pas au
     choix. Les tests l'exécutent avec node
     (`tests/unit/test_scene_settings_ui.py`) ;
   - un bloc navigateur : la section enregistrée dans le registre des Réglages
     (`registerSettingsSection`, écrite par `POST /api/settings`, bloc `scene`), le redémarrage confirmé
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

  /* ------------------------------------------------------------------
     Le bloc `scene` de `/api/status`, fondu dans celui de `/api/settings`.

     Même défaut que l'interrupteur Bare Hands : cette section ne relisait son
     interrupteur qu'à l'ouverture du modal, donc un changement venu d'ailleurs
     (un outil, un `curl`, un second onglet) laissait la case afficher l'ancien
     état tant que le modal restait ouvert. Le battement qui porte le
     remède est celui que la page fait **déjà** tourner : `/api/status` bat à
     la seconde et porte `scene.enabled` depuis la Slice 05.

     Les deux blocs ne sont pas le même : le statut ne porte que `enabled` et
     `source`, `/api/settings` y ajoute `stored` et `env`. On ne les invente
     pas. `stored` se **déduit** quand la source est le réglage enregistré —
     c'est sa définition même (`load_gate` : hors variable d'environnement,
     `enabled` *est* `stored`) — et se conserve tel quel sinon, parce que
     `sourceNote` l'affiche mot pour mot et qu'une valeur devinée y mentirait.
     `env` n'est jamais reconstruit : il ne vient que de `/api/settings`. */
  function mergeGate(known,gate){
    if(!gate||typeof gate!=='object'||typeof gate.enabled!=='boolean')return null;
    const base=known&&typeof known==='object'?known:{};
    const enabled=gate.enabled===true;
    const source=gate.source===undefined?base.source:gate.source;
    const next={...base,enabled,source};
    if(source!=='env')next.stored=enabled;
    return next;
  }
  /* Y a-t-il quelque chose à réconcilier ? Comparé sur ce que l'écran
     **dessine** — la case et sa lecture seule — et non sur l'objet entier :
     `stored` et `env` ne changent pas ce que la case montre, et redessiner
     pour eux volerait le focus une fois par seconde. `true` aussi quand rien
     n'a encore été lu : « on ne sait pas » n'est pas « c'est déjà bon ». */
  function gateChanged(known,gate){
    const next=mergeGate(known,gate);
    if(!next)return false;
    if(!known||typeof known!=='object'||typeof known.enabled!=='boolean')return true;
    return known.enabled!==next.enabled||known.source!==next.source;
  }

  /* Ce que la section garde du statut lu par la page : l'état réel du brain.
     Pur (et testé) parce qu'un champ oublié ici rendrait `brainView` aveugle :
     `display_prompt` manquant renvoyait toujours au repli « agent plus ancien ». */
  function statusView(value){
    if(!value||typeof value!=='object')return null;
    const agent=value.agent&&typeof value.agent==='object'?value.agent:null;
    return {
      agent_cli:value.agent_cli,
      agent:agent?{name:agent.name,state:agent.state,display_tools:agent.display_tools,display_prompt:agent.display_prompt}:null,
      subagents:value.subagents,
    };
  }

  /* Phrase annoncée par la région vivante : l'état du brain, pas les compteurs. */
  function brainSentence(model){return `${model.brain.title}. ${model.brain.detail}`}

  /* Durée lisible d'une attente en cours (compteur du redémarrage). */
  function elapsedLabel(ms){return `${Math.max(0,Math.floor((Number(ms)||0)/1000))} s`}

  const api=Object.freeze({version:1,ENV_NAME,SETTINGS_ROUTE,RESTART_ROUTE,RESTART_BODY,RESTART_DEADLINE_MS,describe,statusView,mergeGate,gateChanged,brainSentence,elapsedLabel});
  root.JarvisSceneSettings=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);

/* --------------------------------------------------------------------------
   Bloc navigateur : section `scene_gate` des Réglages (Avancé & diagnostic ›
   Labs & outils de test). Les tests node ne l'exécutent pas.
   -------------------------------------------------------------------------- */
(function installJarvisSceneSettings(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const Logic=window.JarvisSceneSettings;
  /* Entrée du registre des Réglages (Avancé & diagnostic › Labs & outils de test). */
  const SECTION_ENTRY='scene_gate';
  const SECTION_ID='sceneSettings';
  /* `host` : l'hôte que le shell a monté pour la section, `null` dès qu'elle est quittée. */
  const view={scene:null,status:null,busy:false,error:'',restart:null,host:null};

  const log=(level,event,data)=>{try{console[level==='error'?'error':level==='warn'?'warn':'info']('[scène] '+event,data||{})}catch(_error){/* console absente */}};
  /* La section est montrée : Réglages ouverts, hôte monté et toujours dans la page, réglages lus. */
  const sectionShown=()=>typeof SET!=='undefined'&&SET.open&&!!SET.data&&!!view.host&&view.host.isConnected;

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

  /* Tête de section des Réglages (`JarvisSettingsUI.section`, comme les autres sections : titre, badges « Avancé » et
     « Mode test », description). Le gabarit du shell échappe ses textes ; le corps est ensuite fait de nœuds. Sans les
     primitives (page partielle), une tête simple. */
  function sectionShell(){
    const UI=window.JarvisSettingsUI;
    const description='Une carte persistante du travail de JARVIS derrière l\'interface : un sous-agent devient une étoile, ses résultats des artefacts reliés, et le brain peut y montrer ce qui compte. Vous déplacez, épinglez, masquez et archivez ; le brain n\'archive jamais.';
    if(UI&&typeof UI.section==='function'){
      const fragment=document.createRange().createContextualFragment(UI.section({id:SECTION_ID,title:'Scène constellation',
        description,advanced:true,badges:UI.badge('warn','Mode test')}));
      const section=fragment.firstElementChild;
      section.setAttribute('data-scene-settings','');
      return {section,body:section.querySelector('.set-section-body')};
    }
    const section=node('section',{id:SECTION_ID,'aria-labelledby':`${SECTION_ID}-title`,'data-scene-settings':''},
      [node('h3',{id:`${SECTION_ID}-title`,text:'Scène constellation · mode test'}),node('div',{className:'hint',text:description})]);
    return {section,body:section};
  }

  function sectionNode(){
    const model=Logic.describe(view.scene,view.status);
    const {section:shell,body:section}=sectionShell();
    const describedBy=['sceneEffects',model.source?'sceneSourceNote':null].filter(Boolean).join(' ');
    /* Occupé : `aria-disabled` plutôt que `disabled`, qui ferait perdre le focus clavier pendant l'écriture. */
    const input=node('input',{type:'checkbox',id:'f_scene','data-scene-toggle':'','aria-describedby':describedBy,
      checked:model.checked,disabled:model.readOnly,'aria-disabled':view.busy?'true':null,'aria-busy':view.busy?'true':null});
    input.checked=model.checked;
    input.addEventListener('click',event=>{if(view.busy)event.preventDefault()});
    const label=node('label',{for:'f_scene'},[document.createTextNode('Afficher la scène et donner ses outils au brain '),node('span',{className:'tag warn',text:'TEST'})]);
    const hint=node('div',{className:'hint',text:view.busy?'Enregistrement…':(model.readOnly&&model.source?'Lecture seule : voir ci-dessous.':'Activée par défaut. Enregistré immédiatement.')});
    section.append(node('div',{className:'field inline'},[input,node('div',{},[label,hint])]));
    if(!model.known)section.append(node('div',{className:'notice bad',role:'alert',text:'Réglage de scène illisible : rouvrez les réglages.'}));
    if(view.error)section.append(node('div',{className:'notice bad',role:'alert'},
      [node('strong',{text:view.error.startsWith('Redémarrage')?'Redémarrage impossible':'Réglage non enregistré'}),
       node('div',{className:'hint',text:view.error})]));
    if(model.source)section.append(node('div',{className:'notice',id:'sceneSourceNote'},[node('strong',{text:model.source.title}),node('div',{className:'hint',text:model.source.detail})]));
    const list=node('dl',{className:'scene-effects',id:'sceneEffects'});
    for(const effect of model.effects)list.append(node('dt',{text:effect.term}),node('dd',{text:effect.text}));
    section.append(list);
    const brain=node('div',{className:`notice ${model.brain.tone==='warn'?'':model.brain.tone}`,id:'sceneBrain'},
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
    return shell;
  }

  /* Redessine la section en gardant le focus sur le contrôle qui l'avait. */
  function refresh(){
    if(!sectionShown())return;
    const content=view.host;
    const previous=content.querySelector('#'+SECTION_ID);
    const focused=previous&&previous.contains(document.activeElement)?document.activeElement:null;
    const key=focused?(focused.hasAttribute('data-scene-toggle')?'[data-scene-toggle]':focused.hasAttribute('data-scene-restart')?'[data-scene-restart]':null):null;
    const next=sectionNode();
    if(previous)previous.replaceWith(next);else content.prepend(next);
    announce(Logic.brainSentence(Logic.describe(view.scene,view.status)));
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
      announce(data.scene.enabled?'Scène activée.':'Scène désactivée.');
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
    view.error='';
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
      // Bandeau rouge dans la section en plus de la notification : elle disparaît, pas lui.
      view.error=`Redémarrage du brain impossible : ${message}`;
      log('error','scene.brain_restart_failed',{error:message,status:error&&error.status});
      if(typeof toast==='function')toast({title:'Redémarrage du brain impossible',sub:message,kind:'bad',ms:8000});
    }finally{
      clearInterval(view.restart.ticker);clearTimeout(view.restart.timer);
      view.restart=null;
      refresh();
      if(typeof refreshStatus==='function')refreshStatus();
    }
  }

  /* Région vivante stable : recréer le nœud à chaque redessin rendait
     l'annonce imprévisible (certains lecteurs d'écran ne relisent qu'un nœud
     déjà présent). Un seul nœud, hors de la section redessinée, dont on ne
     change que le texte, et seulement quand la phrase change. */
  let liveEl=null;
  let lastSpoken='';

  function announce(sentence){
    const text=String(sentence||'');
    if(!text||text===lastSpoken)return;
    if(!liveEl||!liveEl.isConnected){
      liveEl=document.createElement('div');
      liveEl.id='sceneSettingsLive';liveEl.className='sc-settings-sr';
      liveEl.setAttribute('role','status');liveEl.setAttribute('aria-live','polite');
      document.body.appendChild(liveEl);
    }
    liveEl.textContent=text;
    lastSpoken=text;
  }

  const STYLE=`#sceneSettings .scene-effects{display:grid;grid-template-columns:max-content 1fr;gap:6px 14px;margin:0 0 16px;font-size:12px;line-height:1.5}
#sceneSettings .scene-effects dt{color:var(--muted);letter-spacing:.04em}
#sceneSettings .scene-effects dd{margin:0}
#sceneSettings [data-scene-toggle]:focus-visible,#sceneSettings [data-scene-restart]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#sceneSettings [aria-disabled=true]{opacity:.6;cursor:wait}
.sc-settings-sr{position:absolute;width:1px;height:1px;margin:-1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
#sceneSettings+section{border-top:1px solid var(--line);padding-top:22px;margin-top:8px}
@media(max-width:560px){#sceneSettings .scene-effects{grid-template-columns:1fr}#sceneSettings .scene-effects dd{margin-bottom:6px}}`;

  function ensureStyle(){
    if(document.getElementById('jarvisSceneSettingsStyle'))return;
    const style=document.createElement('style');
    style.id='jarvisSceneSettingsStyle';style.textContent=STYLE;
    document.head.appendChild(style);
  }

  /* Section du registre des Réglages (Slice 08) : le shell la monte dans un hôte neuf et la détruit en la quittant.
     Une écriture ou un redémarrage en vol continue ; sa fin ne redessine que si la section est de nouveau montrée. */
  function mount(host){
    ensureStyle();
    view.host=host;
    host.replaceChildren();
    if(typeof SET==='undefined'||!SET.data){
      // `openSettings` remonte la section à l'arrivée des réglages.
      host.append(node('div',{className:'empty',text:'Chargement…'}));return}
    view.scene=SET.data.scene||null;
    // Section remontée : une erreur d'un essai précédent ne s'affiche plus comme actuelle.
    if(!view.busy)view.error='';
    // Redémarrage encore en vol : son compteur reprend (`destroy` l'a arrêté en quittant la section).
    if(view.restart&&view.restart.ticker==null)view.restart.ticker=setInterval(refresh,1000);
    refresh();
  }
  /* Section quittée : plus d'hôte, et le compteur du redémarrage s'arrête (il ne redessinait plus rien). L'échéance
     du redémarrage, elle, continue : la requête doit finir ou être abandonnée même section quittée. */
  function destroy(host){
    if(view.host!==host)return;
    view.host=null;
    if(view.restart&&view.restart.ticker!=null){clearInterval(view.restart.ticker);view.restart.ticker=null}
  }
  function installSection(){
    if(typeof registerSettingsSection!=='function'){log('error','scene.settings_shell_missing',{});return}
    registerSettingsSection({id:SECTION_ENTRY,category:'advanced_diagnostics',group:'labs',order:40,save:'self',advanced:true,
      label:'Scène constellation',
      description:'Porte de test de la scène et redémarrage du brain. Enregistré immédiatement ; chaque effet dit quand il s’applique.',
      mount,destroy});
  }

  /* Le statut que la page lit déjà chaque seconde nourrit l'état du brain. */
  function observeStatus(){
    if(typeof api!=='function')return;
    const baseApi=api;
    api=async function(path,opts){
      const value=await baseApi(path,opts);
      if(typeof path==='string'&&path.split('?')[0]==='/api/status'&&value&&typeof value==='object'){
        const before=JSON.stringify(Logic.describe(view.scene,view.status).brain);
        view.status=Logic.statusView(value);
        /* L'interrupteur de la scène, repris du même battement. Jamais pendant
           une écriture (`view.busy`) : le statut en vol peut être plus vieux
           que le POST qui n'a pas encore répondu, et c'est la réponse qui fait
           foi. Et jamais de réécriture vers le serveur en retour — on ne fait
           que se mettre d'accord avec ce qu'il vient de dire, sinon lecture et
           écriture se relanceraient l'une l'autre à chaque seconde. */
        let gated=false;
        if(!view.busy&&Logic.gateChanged(view.scene,value.scene)){
          view.scene=Logic.mergeGate(view.scene,value.scene);
          /* La copie que le modal relit en se redessinant suit, sinon le
             prochain rendu d'onglet réinstallerait l'ancienne valeur. */
          if(typeof SET!=='undefined'&&SET.data)SET.data.scene=view.scene;
          gated=true;
        }
        if(sectionShown()&&!view.restart
          &&(gated||JSON.stringify(Logic.describe(view.scene,view.status).brain)!==before))refresh();
      }
      return value;
    };
  }

  setTimeout(()=>{installSection();observeStatus()},0);
  window.JarvisSceneSettingsView=Object.freeze({inspect:()=>({scene:view.scene,status:view.status,busy:view.busy,error:view.error,restarting:!!view.restart})});
})();
