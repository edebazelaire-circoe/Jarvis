/* Catégories JARVIS et Paramètres de la roue d'outils.

   Handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 04
   (`docs/06-ui-visual-spec.md` › C et F). Contrat :
   `docs/control-center-shell.md` › *Tool wheel* › *JARVIS and Paramètres*.

   **JARVIS dit l'état ; il ne pilote qu'une chose : couper ou rallumer la voix.**
   Ni Core ni le Control Center n'exposent de route pour réveiller Voice, ni pour
   changer un mode de réflexion ou d'autonomie : seule la touche d'éveil de Voice
   (raccourci global, F9 par défaut) réveille. Depuis la Slice 05 de
   presentation-edition-v1-2 (`docs/voice-lifecycle.md`), la ligne **Voix activée**
   est un interrupteur (`menuitemcheckbox`) de la préférence persistée Off / Sleep
   (`POST /api/voice/lifecycle`) ; elle n'apparaît que si le battement porte
   `voice_lifecycle`, et elle montre l'état que le serveur projette (coupée,
   veille, active, démarrage, arrêt, indisponible avec sa raison), jamais celui
   que le clic espère.

   **Une seule source : le battement de la page.** `refreshStatus`
   (`control_center.html`) lit `/api/status` et appelle `gate(status)` ;
   son échec appelle `statusLost()`. Ce module ne sonde rien et ne garde
   aucune vérité locale : ce qui n'est pas confirmé par le dernier battement
   est dit inconnu, jamais deviné depuis un clic.

   Lignes du sous-menu JARVIS, dans cet ordre :
   - **Voix** (état seul) : `voice_online` + `voice_state` (veille, attente,
     écoute, parole, réflexion — SLEEP / WAIT / LISTEN / TALK / THINKING,
     le vocabulaire de l'orbe), pile `voice_stack_label` en détail ;
   - **touche d'éveil** (état seul) : ce que la touche fait maintenant
     (`manual_wake_key`, `voice_turn_mode`) — l'ancien `#wakeHint` de la Slice 02 ;
   - **Agent** (état seul) : `agent.name` / `agent_cli`, `agent.state`,
     `agent.model` en détail ;
   - **Sous-agents** (action) : `subagents.active` ; ouvre le panneau Agents
     (`#agentsButton`, la même route que le lanceur) ;
   - **Réglages de la voix** (action) : les réglages sur Personnalisation ›
     Conversation (`VOICE_SETTINGS_TARGET`, une section du registre ; micro,
     modèle, pile vocale), la même surface que `#openSettings`.

   **Paramètres** : ouvre le hub des Réglages (`openSettingsHub` de la page,
   six cartes, 2026-10-23) ; plus de sous-menu.

   Deux blocs : le **modèle pur** (`factsOf`, `wakeHintOf`, `jarvisItemsOf`,
   `categoryStatusOf`), exécuté par node dans
   `tests/unit/test_jarvis_wheel_js.py`, et le **bloc navigateur** (registre
   de la roue), éprouvé dans Chrome par `tests/unit/test_jarvis_wheel_browser.py`. */
(function(root){
  'use strict';

  const isObject=v=>!!v&&typeof v==='object'&&!Array.isArray(v);

  /* `voice_state` de Voice -> le mot de l'interface et l'étiquette de l'orbe. */
  const VOICE_STATES=Object.freeze({
    idle:Object.freeze({word:'Veille',tag:'IDLE'}),
    sleep:Object.freeze({word:'Sommeil',tag:'SLEEP'}),
    waiting:Object.freeze({word:'Attente',tag:'WAIT'}),
    listening:Object.freeze({word:'Écoute',tag:'LISTEN'}),
    speaking:Object.freeze({word:'Parole',tag:'TALK'}),
    thinking:Object.freeze({word:'Réflexion',tag:'THINKING'}),
  });
  /* `agent.state` du processus du brain -> un mot. Un état inconnu de cette
     table est montré tel quel (jamais traduit au hasard). */
  const AGENT_STATES=Object.freeze({
    running:'actif',idle:'au repos',starting:'démarrage',stopped:'arrêté',stopping:'arrêt',
    error:'en erreur',failed:'en échec',exited:'terminé',
  });

  /* ------------------------------------------------- les faits

     `status` : la réponse de `/api/status`, ou `null`. `read` : `pending`
     (aucun battement encore), `ok`, `lost` (le dernier battement a échoué).
     Rien n'est gardé d'un battement réussi quand le suivant échoue : un fait
     ancien n'est plus un fait. */
  function factsOf(status,read){
    if(read==='lost')return Object.freeze({read:'lost'});
    if(!isObject(status))return Object.freeze({read:'pending'});
    const online=status.voice_online===true;
    const state=typeof status.voice_state==='string'&&status.voice_state?status.voice_state:'idle';
    const agent=isObject(status.agent)?status.agent:{};
    const sub=isObject(status.subagents)?status.subagents:null;
    const active=sub&&Number.isFinite(Number(sub.active))?Math.max(0,Math.trunc(Number(sub.active))):null;
    return Object.freeze({
      read:'ok',
      voice:Object.freeze({online,state,stack:typeof status.voice_stack_label==='string'?status.voice_stack_label:''}),
      wakeKey:String(status.manual_wake_key||'f9').toUpperCase(),
      turnMode:status.voice_turn_mode==='manual'?'manual':'auto',
      agent:Object.freeze({name:String(agent.name||status.agent_cli||'').trim(),
        state:typeof agent.state==='string'?agent.state:'',model:typeof agent.model==='string'?agent.model:''}),
      subagents:active,
      lifecycle:isObject(status.voice_lifecycle)?status.voice_lifecycle:null,
    });
  }

  /* L'état produit de la voix (`voice_lifecycle.state`) -> la note courte et le ton de l'interrupteur. */
  const LIFECYCLE_NOTES=Object.freeze({
    off:Object.freeze({note:'coupée · OFF',tone:'off'}),
    sleep:Object.freeze({note:'veille · SLEEP',tone:undefined}),
    active:Object.freeze({note:'en conversation',tone:undefined}),
    starting:Object.freeze({note:'démarrage…',tone:'busy'}),
    stopping:Object.freeze({note:'arrêt…',tone:'busy'}),
    degraded:Object.freeze({note:'indisponible',tone:'error'}),
    /* Sans lanceur : rallumée, mais Voice est à relancer par vous (pas une panne). */
    not_running:Object.freeze({note:'à relancer',tone:'off'}),
  });

  /* L'interrupteur « Voix activée » : coché quand la préférence n'est pas « coupée ». `pending` : une écriture est en
     vol (le bloc navigateur la tient), l'entrée est grisée et dit pourquoi. `null` sans `voice_lifecycle`. */
  function voicePowerItemOf(facts,pending){
    const lc=isObject(facts)&&facts.read==='ok'?facts.lifecycle:null;
    if(!lc)return null;
    /* Cochée seulement pour un choix « veille » lisible ; un choix illisible se réécrit en la rallumant. */
    const on=lc.preference==='sleep';
    const known=LIFECYCLE_NOTES[lc.state]||{note:String(lc.state||'état inconnu'),tone:'unknown'};
    const message=typeof lc.message==='string'?lc.message:'';
    const code=typeof lc.code==='string'&&lc.code&&lc.code!=='voice_off'?` (${lc.code})`:'';
    const next=on?'choisir pour couper la voix (le chat reste disponible)':'choisir pour rallumer la voix en veille';
    return {id:'voice_power',kind:'action',toggle:true,checked:on,icon:'jarvis',label:'Voix activée',
      note:pending?'enregistrement…':known.note,
      detail:`${message?message+code+' ; ':''}${pending?'enregistrement en cours':next}`,
      tone:pending?'busy':known.tone,disabled:pending===true};
  }

  /* La ligne « Voix » du parcours principal (V1.2 Slice 06 : accueil des présentations, Aide et assistance des
     Réglages) : la MÊME projection serveur que l'interrupteur, dite sans jargon (Coupée / En veille / En conversation),
     et le geste qui la change. `null` tant que le battement ne porte pas `voice_lifecycle` : rien n'est deviné. */
  const VOICE_LINE_WORDS=Object.freeze({off:'Coupée',sleep:'En veille',active:'En conversation',starting:'Démarrage…',
    stopping:'Arrêt…',degraded:'Indisponible',not_running:'À relancer'});
  function voiceLineOf(facts,pending){
    const lc=isObject(facts)&&facts.read==='ok'?facts.lifecycle:null;
    if(!lc)return null;
    const on=lc.preference==='sleep';
    const state=typeof lc.state==='string'?lc.state:'';
    const word=VOICE_LINE_WORDS[state]||'État inconnu';
    const key=facts.wakeKey||'F9';
    const message=typeof lc.message==='string'?lc.message:'';
    const hint=state==='sleep'?`Appuyez sur ${key} pour lui parler. Le chat reste disponible.`
      :state==='active'?'Jarvis vous écoute.'
      :state==='off'?'Aucun micro n’est ouvert. Le chat reste disponible.'
      :message;
    const tone=pending?'busy':(LIFECYCLE_NOTES[state]||{tone:'unknown'}).tone||'on';
    const code=typeof lc.code==='string'?lc.code:'';
    /* QA S06 m5 : l'action proposée est celle qui aide (`actionKind`). Voix voulue mais indisponible : la clé manque →
       « Ajouter la clé vocale » (Réglages › Connexions) ; voix non lancée sur ce poste ou configuration illisible →
       aucun bouton (le message dit pourquoi) ; plantages répétés ou erreur → « Couper la voix » reste le geste que le
       message demande (« coupez-la puis rallumez-la »). Ailleurs : couper / rallumer. */
    const NO_ACTION=['voice_not_launched','voice_configuration_invalid'];
    let actionKind='toggle',action=on?'Couper la voix':'Rallumer la voix';
    if(on&&state==='degraded'&&code==='voice_provider_key_missing'){actionKind='open_connections';action='Ajouter la clé vocale'}
    else if(on&&state==='degraded'&&NO_ACTION.includes(code)){actionKind=null;action=null}
    return {state,on,word:pending?'Enregistrement…':word,hint,tone,pending:pending===true,code,action,actionKind};
  }

  /* Ce que la touche d'éveil fait **maintenant** (l'ancien rappel caché de la page,
     inchangé) : selon l'état de la voix et le mode de tour. */
  function wakeHintOf(facts){
    if(!isObject(facts)||facts.read!=='ok')return 'VOICE HORS LIGNE';
    const k=facts.wakeKey;
    if(!facts.voice.online)return `${k} · VOICE HORS LIGNE`;
    const listening=facts.turnMode==='manual'?`${k} · ENVOYER`:`${k} · ANNULER`;
    return ({idle:`${k} · DÉMARRER`,waiting:listening,listening,thinking:`${k} · ANNULER`,
      speaking:`${k} · INTERROMPRE`})[facts.voice.state]||`${k} · CONTRÔLER`;
  }

  const UNKNOWN_DETAIL={
    pending:'pas encore lu : le premier relevé du statut n’est pas arrivé',
    lost:'statut du Control Center illisible : rien n’est confirmé',
  };

  /* ------------------------------------------------- les lignes JARVIS

     Rend des entrées **sans** action (le bloc navigateur branche les deux
     portes). `status:true` : une ligne d'état, lisible et focalisable, qui
     n'agit pas ; `tone:'unknown'` : un fait que le dernier battement ne
     confirme pas. */
  function jarvisItemsOf(facts){
    const f=isObject(facts)?facts:{read:'pending'};
    if(f.read!=='ok'){
      const why=UNKNOWN_DETAIL[f.read]||UNKNOWN_DETAIL.pending;
      return [
        {id:'voice',kind:'status',status:true,icon:'jarvis',label:'Voix',note:'état inconnu',detail:why,tone:'unknown'},
        {id:'wake',kind:'status',status:true,icon:'key',label:'Touche d’éveil',note:'état inconnu',detail:why,tone:'unknown'},
        {id:'agent',kind:'status',status:true,icon:'agent',label:'Agent',note:'état inconnu',detail:why,tone:'unknown'},
        {id:'subagents',kind:'action',icon:'subagents',label:'Sous-agents',note:'nombre inconnu',
          detail:`${why} ; ouvre le panneau Agents`,tone:'unknown'},
        {id:'voice_settings',kind:'action',icon:'settings',label:'Réglages de la voix',note:'micro, modèle, pile vocale'},
      ];
    }
    const v=f.voice,known=VOICE_STATES[v.state];
    const voice=v.online
      ?{note:known?`${known.word} · ${known.tag}`:v.state.toUpperCase(),
        detail:`Voice en ligne, ${known?known.word.toLowerCase():`état ${v.state}`}${v.stack?`, pile ${v.stack}`:''}`,
        tone:undefined}
      :{note:'hors ligne',detail:'Voice ne donne plus signe de vie : rien n’écoute',tone:'off'};
    if(!v.online&&f.lifecycle&&f.lifecycle.state==='off'){
      voice.note='coupée';voice.detail='Voix coupée par vous : aucun micro n’est ouvert';
    }
    const hint=wakeHintOf(f);
    const turn=f.turnMode==='manual'?'tour manuel':'tour automatique';
    const wake={label:hint,
      note:v.online?turn:'Voice hors ligne : sans effet',
      detail:`touche ${f.wakeKey}, raccourci global de Voice${v.online?`, ${turn}`:''}`,
      tone:v.online?undefined:'off'};
    const a=f.agent;
    const word=a.state?(AGENT_STATES[a.state]||a.state):'état non dit';
    const agent={label:`Agent : ${a.name||'inconnu'}`,note:word,
      detail:`état du brain : ${word}${a.model?`, modèle ${a.model}`:''}`,
      tone:a.state==='error'||a.state==='failed'?'error':!a.state?'unknown':undefined};
    const n=f.subagents;
    const subNote=n===null?'nombre non dit':n===0?'aucun en cours':n===1?'1 en cours':`${n} en cours`;
    const power=voicePowerItemOf(f,false);
    return [
      {id:'voice',kind:'status',status:true,icon:'jarvis',label:'Voix',...voice},
      ...(power?[power]:[]),
      {id:'wake',kind:'status',status:true,icon:'key',...wake},
      {id:'agent',kind:'status',status:true,icon:'agent',...agent},
      {id:'subagents',kind:'action',icon:'subagents',label:'Sous-agents',note:subNote,
        detail:`${subNote} ; ouvre le panneau Agents`,tone:n===null?'unknown':undefined},
      {id:'voice_settings',kind:'action',icon:'settings',label:'Réglages de la voix',note:'micro, modèle, pile vocale',
        detail:'ouvre les réglages, Personnalisation › Conversation'},
    ];
  }

  /* Ce que le secteur JARVIS projette (le cœur de la roue le lit) : une
     phrase courte, stable d'un battement à l'autre tant que rien ne change ;
     `unknown` quand rien n'est confirmé (un « ? » muet, l'ancre n'est pas
     colorée). */
  function categoryStatusOf(facts){
    const f=isObject(facts)?facts:{read:'pending'};
    if(f.read==='lost')return {tone:'unknown',text:'état inconnu, statut illisible'};
    if(f.read!=='ok')return null;
    const known=VOICE_STATES[f.voice.state];
    const voice=f.voice.online?`voix : ${known?known.word.toLowerCase():f.voice.state}`
      :f.lifecycle&&f.lifecycle.state==='off'?'voix coupée':'voix hors ligne';
    const n=f.subagents;
    return {tone:null,text:n?`${voice} · ${n} sous-agent${n>1?'s':''}`:voice};
  }

  /* La ligne « Réglages de la voix » ouvre la section Conversation de Personnalisation (ID canonique de section : la
     catégorie s'ouvre désormais sur Thème & scène, hub des Réglages du 2026-10-23). */
  const VOICE_SETTINGS_TARGET='conversation';
  /* Section où s'ajoute la clé du fournisseur vocal (`actionKind: open_connections` de la ligne Voix). */
  const VOICE_KEY_TARGET='providers';

  const LIFECYCLE_ROUTE='/api/voice/lifecycle';
  const api=Object.freeze({VOICE_STATES,AGENT_STATES,VOICE_SETTINGS_TARGET,VOICE_KEY_TARGET,LIFECYCLE_ROUTE,LIFECYCLE_NOTES,factsOf,wakeHintOf,
    jarvisItemsOf,voicePowerItemOf,categoryStatusOf,voiceLineOf});
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- le bloc navigateur */

  const log=(level,key,data)=>{
    const line=`[jarvis] ${key} ${JSON.stringify(data||{})}`;
    if(level==='error')console.error(line);
    else if(level==='warn')console.warn(line);
    else console.info(line);
  };

  function installJarvisWheel(){
    const W=window.JarvisToolWheel;
    if(!W)throw Object.assign(new Error('JarvisRuntimeWheel : JarvisToolWheel absent'),{code:'jarvis_wheel_dependency_missing'});
    let facts=factsOf(null,'pending');
    let lastRead=null,lastLine=null;

    /* Les deux portes : les routes que la page sert déjà. Une porte
       introuvable se dit (notification + journal), elle ne fait rien en
       silence. */
    function say(title,sub){
      if(typeof root.toast==='function')root.toast({title,sub,kind:'bad',ms:7000});
    }
    function openAgents(source){
      const button=document.getElementById('agentsButton');
      if(!button){
        log('error','jarvis_wheel.route_missing',{route:'agents'});
        say('Panneau Agents introuvable','Le bouton Agents manque dans cette page.');
        return;
      }
      log('info','jarvis_wheel.open_agents',{source:source||null});
      button.click();
    }
    function openSettingsAt(tab,source){
      if(typeof root.openSettingsTab!=='function'){
        log('error','jarvis_wheel.route_missing',{route:'settings'});
        say('Réglages introuvables','La surface des réglages manque dans cette page.');
        return undefined;
      }
      log('info','jarvis_wheel.open_settings',{tab:tab||null,source:source||null});
      /* L'ancre reprend le focus à la fermeture des Réglages (QA Slice 02 de jarvis-settings-ui-reorganization). */
      return root.openSettingsTab(tab||null,{returnFocus:document.querySelector('#toolWheel .tw-anchor')});
    }

    /* L'interrupteur de la voix : une écriture à la fois, la réponse du serveur (sa projection) devient le fait
       affiché ; un refus est dit (notification + journal) et rien n'est supposé. Délai borné : la page n'attend
       jamais sans fin. */
    let powerPending=false;
    async function toggleVoice(source){
      if(powerPending||facts.read!=='ok'||!facts.lifecycle)return;
      const preference=facts.lifecycle.preference==='sleep'?'off':'sleep';
      powerPending=true;apply(facts);
      log('info','jarvis_wheel.voice_power_requested',{preference,source:source||null});
      const abort=typeof AbortController==='function'?new AbortController():null;
      const timer=setTimeout(()=>{if(abort)abort.abort()},8000);
      try{
        const response=await fetch(LIFECYCLE_ROUTE,{method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({preference}),signal:abort?abort.signal:undefined});
        const text=await response.text();
        if(!response.ok){
          const code=response.headers.get('X-Jarvis-Error-Code')||`http_${response.status}`;
          throw Object.assign(new Error(text||code),{code});
        }
        const view=JSON.parse(text);
        facts=Object.freeze({...facts,lifecycle:isObject(view)?view:facts.lifecycle});
        log('info','jarvis_wheel.voice_power_saved',{preference,state:view&&view.state,code:view&&view.code});
        if(typeof root.toast==='function')root.toast({title:preference==='off'?'Voix coupée':'Voix rallumée',
          sub:String(view&&view.message||(preference==='off'?'Aucun micro n’est ouvert.':'La voix démarre en veille.')),kind:'ok',ms:4000});
      }catch(error){
        const code=error&&error.name==='AbortError'?'voice_lifecycle_timeout':(error&&error.code)||'voice_lifecycle_failed';
        log('error','jarvis_wheel.voice_power_failed',{preference,code,error:String(error&&error.message||error)});
        say('Voix : changement non enregistré',`${code} : ${String(error&&error.message||error).slice(0,200)}`);
      }finally{
        clearTimeout(timer);powerPending=false;apply(facts);
      }
    }

    function items(){
      return jarvisItemsOf(facts).map(spec=>{
        if(spec.id==='voice_power')return {...voicePowerItemOf(facts,powerPending),onActivate:ctx=>toggleVoice(ctx&&ctx.source)};
        if(spec.id==='subagents')return {...spec,onActivate:ctx=>openAgents(ctx&&ctx.source)};
        if(spec.id==='voice_settings')return {...spec,onActivate:ctx=>openSettingsAt(VOICE_SETTINGS_TARGET,ctx&&ctx.source)};
        return spec;
      });
    }

    W.register({id:'jarvis',menu:true,
      onActivate:()=>{/* `menu:true` : l'activation ouvre le sous-menu. */},
      onSecondary:ctx=>{
        log('info','jarvis_wheel.menu',{source:ctx&&ctx.source||null,read:facts.read});
        return items();
      }});

    /* Paramètres ouvre le hub des Réglages (six cartes, 2026-10-23) : plus de sous-menu dans la roue. Sans hub
       (page plus ancienne), les Réglages tels quels. */
    W.register({id:'settings',
      onActivate:ctx=>{
        const source=ctx&&ctx.source||null,anchor=document.querySelector('#toolWheel .tw-anchor');
        if(typeof root.openSettingsHub==='function'){
          log('info','jarvis_wheel.open_settings_hub',{source});
          return root.openSettingsHub({returnFocus:anchor,source:'wheel'});
        }
        return openSettingsAt(null,source);
      }});

    /* Un battement : les faits, la phrase du secteur, et le sous-menu s'il
       est ouvert (relu, sans rien rejouer). Journalisé seulement quand ce
       qui se lit change. */
    function apply(next){
      facts=next;
      try{W.setStatus('jarvis',categoryStatusOf(facts))}
      catch(error){log('error','jarvis_wheel.paint_failed',{error:String(error&&error.message||error)})}
      if(typeof W.refresh==='function')W.refresh('jarvis');
      const seen=facts.read==='ok'?`${facts.voice.online}:${facts.voice.state}:${facts.agent.state}:${facts.subagents}:${facts.lifecycle?facts.lifecycle.state+'/'+facts.lifecycle.code:'-'}`:facts.read;
      if(seen!==lastRead){lastRead=seen;log('info','jarvis_wheel.facts',{read:facts.read,hint:wakeHintOf(facts)})}
      /* La ligne « Voix » du parcours principal (accueil, Aide et assistance) se redessine sur ce signal : une
         seule source, ce battement (V1.2 Slice 06). */
      const line=voiceLineOf(facts,powerPending),said=line?`${line.state}:${line.on}:${line.pending}:${line.code}`:'-';
      if(said!==lastLine){lastLine=said;
        try{document.dispatchEvent(new CustomEvent('jarvis:voice-line',{detail:line}))}
        catch(error){log('error','jarvis_wheel.voice_line_event_failed',{error:String(error&&error.message||error)})}}
    }

    window.JarvisRuntimeWheel=Object.freeze({
      gate(status){apply(factsOf(status,'ok'))},
      statusLost(){apply(factsOf(null,'lost'))},
      /* Relevé des tests et des preuves. */
      facts:()=>facts,
      wakeHint:()=>wakeHintOf(facts),
      items:()=>jarvisItemsOf(facts),
      toggleVoice:source=>toggleVoice(source||'api'),
      voiceLine:()=>voiceLineOf(facts,powerPending),
      /* Le geste de la ligne Voix (`actionKind`) : interrupteur, ou Réglages › Connexions pour la clé. */
      voiceLineAct(source){
        const line=voiceLineOf(facts,powerPending);
        if(!line||!line.actionKind)return undefined;
        if(line.actionKind==='open_connections'){
          if(typeof root.openSettingsTab!=='function'){log('error','jarvis_wheel.route_missing',{route:'settings'});return undefined}
          log('info','jarvis_wheel.voice_key_settings',{source:source||null});
          return root.openSettingsTab(VOICE_KEY_TARGET);
        }
        return toggleVoice(source||'api');
      },
    });
    log('info','jarvis_wheel.installed',{categories:['jarvis','settings']});
  }

  try{installJarvisWheel()}
  catch(error){
    console.error('[jarvis] jarvis_wheel.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
