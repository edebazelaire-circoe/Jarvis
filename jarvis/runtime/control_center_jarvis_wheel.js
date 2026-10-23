/* Catégories JARVIS et Paramètres de la roue d'outils.

   Handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 04
   (`docs/06-ui-visual-spec.md` › C et F). Contrat :
   `docs/control-center-shell.md` › *Tool wheel* › *JARVIS and Paramètres*.

   **JARVIS dit l'état, il ne le pilote pas.** À la tête de cette Slice, ni
   Core ni le Control Center n'exposent de route pour endormir ou réveiller
   Voice, ni pour changer un mode de réflexion ou d'autonomie : seule la touche
   d'éveil de Voice (raccourci global, F9 par défaut) agit. Le sous-menu ne
   montre donc que des faits, chacun avec sa source, et deux portes vers des
   surfaces qui existent déjà (le panneau Agents, les réglages de la voix).
   Aucun bouton Veille / Réveil n'est dessiné : il mentirait.

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
    idle:Object.freeze({word:'Veille',tag:'SLEEP'}),
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
    });
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
    return [
      {id:'voice',kind:'status',status:true,icon:'jarvis',label:'Voix',...voice},
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
    const voice=f.voice.online?`voix : ${known?known.word.toLowerCase():f.voice.state}`:'voix hors ligne';
    const n=f.subagents;
    return {tone:null,text:n?`${voice} · ${n} sous-agent${n>1?'s':''}`:voice};
  }

  /* La ligne « Réglages de la voix » ouvre la section Conversation de Personnalisation (ID canonique de section : la
     catégorie s'ouvre désormais sur Thème & scène, hub des Réglages du 2026-10-23). */
  const VOICE_SETTINGS_TARGET='conversation';

  const api=Object.freeze({VOICE_STATES,AGENT_STATES,VOICE_SETTINGS_TARGET,factsOf,wakeHintOf,jarvisItemsOf,categoryStatusOf});
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
    let lastRead=null;

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

    function items(){
      return jarvisItemsOf(facts).map(spec=>{
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
      const seen=facts.read==='ok'?`${facts.voice.online}:${facts.voice.state}:${facts.agent.state}:${facts.subagents}`:facts.read;
      if(seen!==lastRead){lastRead=seen;log('info','jarvis_wheel.facts',{read:facts.read,hint:wakeHintOf(facts)})}
    }

    window.JarvisRuntimeWheel=Object.freeze({
      gate(status){apply(factsOf(status,'ok'))},
      statusLost(){apply(factsOf(null,'lost'))},
      /* Relevé des tests et des preuves. */
      facts:()=>facts,
      wakeHint:()=>wakeHintOf(facts),
      items:()=>jarvisItemsOf(facts),
    });
    log('info','jarvis_wheel.installed',{categories:['jarvis','settings']});
  }

  try{installJarvisWheel()}
  catch(error){
    console.error('[jarvis] jarvis_wheel.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
