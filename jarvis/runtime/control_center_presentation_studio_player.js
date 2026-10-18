/* Client de lecture partagé de la page (studio de présentation, Slices 12, 14, 23 ; native-studio-playback-fix Slice 09).

   Jusqu'à la Slice 09 ce module dessinait aussi la bande flottante `#jvStudioBand` (qui présente, où, boutons, clavier sur l'hôte de la
   fenêtre de stage, plein écran) : la « vue flottante » que l'utilisateur a rejetée. La bande est RETIRÉE avec la fenêtre de stage ; une
   lecture se montre DANS Variantes (`control_center_presentation_studio_explorer.js` + `control_center_presentation_studio_run.js` : la
   bande du présentateur, le transport, les touches § 4.15, le plein écran de la scène). Ce module ne dessine plus RIEN. Il reste l'unique
   client de lecture de la page (contrat `docs/presentation-studio.md` › *2026-10 § 2*, ligne « band poll ») :

   1. un relevé de Core (`GET /api/presentation-studio/playback` : 500 ms quand une ligne de temps pilote la scène, 1,5 s en lecture, 5 s au
      repos, recul jusqu'à 15 s en panne ; seulement onglet visible) : ainsi une lecture lancée à la voix arrive dans la page sans action ;
   2. les événements de la page, dits sans attendre :
      - `jarvis:studio-view` {view} : chaque vue adoptée (Variantes s'y règle : ouvrir pour une nouvelle lecture, bande, transport) ;
      - `jarvis:studio-playback` {running} : une lecture commence ou finit (l'inspecteur se cache) ;
      - `jarvis:studio-surface` {surface} : ce que le lecteur de Variantes monte pour la lecture, relu (`GET .../playback/surface`) quand
        `view.surface.rev` bouge ;
      - `jarvis:studio-timeline` {object_id, timeline, preload} : la ligne de temps de la partition et la scène qui suit (`GET .../preload`) ;
   3. les commandes, par les MÊMES routes que la voix (`POST .../playback/<verbe>`, le relais force l'acteur `user`), en file (4 au plus),
      chacune avec une échéance de 10 s ; `advance {seq, event}` dit à Core ce que le suiveur a vu d'un segment (`jarvis:studio-segment`),
      un fait, jamais une commande.

   Un refus de la machine est rendu tel quel à l'appelant (Variantes le dit avec `REFUSALS`) ; une panne de transport ou un échec de la scène
   est aussi un toast et une ligne de console, pour qu'il se voie même Variantes fermé. Les tables de textes (`ROLE_LABEL`, `PHASE_LABEL`,
   `REFUSALS`, `PROBLEMS`, `FOLLOWER_ABSENT`, `pageWaitText`) servent la bande du présentateur de Variantes. Les titres et libellés viennent
   d'un auteur ou d'un modèle : ils ne passent que par `textContent`, jamais `innerHTML`, jamais comme une consigne. */
(function(root){
  'use strict';

  const ROUTE='/api/presentation-studio/playback';
  const COMMAND_TIMEOUT_MS=10000;
  const POLL_ACTIVE_MS=1500;
  /* Une scène Remotion pilotée par la partition (`view.timeline`) : la position change à la vitesse de la parole, on lit plus vite. */
  const POLL_TIMELINE_MS=500;
  /* Repos : un GET de ~100 octets toutes les 5 s vers le Core local, seulement onglet visible : le prix pour qu'une lecture démarrée par la
     voix apparaisse sans action. */
  const POLL_IDLE_MS=5000;
  const POLL_BACKOFF_MAX_MS=15000;
  const QUEUE_MAX=4;
  const LINK_LOST_AFTER=2;

  const ROLE_LABEL=Object.freeze({user_presenter:'Vous présentez',jarvis_presenter:'Jarvis présente',rehearsal:'Répétition'});
  const PHASE_LABEL=Object.freeze({playing:'En cours',paused:'En pause',detour:'Détour',resuming:'Reprise…',ended:'Terminé',stopped:'Arrêtée'});
  /* Les refus de la machine (codes stables de Core), dits à l'humain. */
  const REFUSALS=Object.freeze({
    not_running:'Aucune présentation en cours.',already_running:'Une présentation est déjà en cours.',
    paused:'La lecture est en pause : reprenez d\'abord.',in_detour:'Une ressource annexe est à l\'écran : revenez du détour d\'abord.',
    resuming:'La scène est en cours de reprise : un instant.',at_start:'C\'est déjà le premier élément.',
    at_end:'La présentation est terminée.',locked_sequence_active:'Une séquence verrouillée est en cours : attendez sa fin, sortez-en (« Sortir de la séquence » ou S), ou arrêtez.',
    no_sequence:'Aucune séquence verrouillée n\'est en cours.',
    detour_invalid:'Cette ressource annexe n\'est pas acceptée par le catalogue de prefabs.',
    interruption_refused:'Cet élément ne peut être interrompu que par l\'arrêt.',aux_stack_full:'Trop de ressources annexes ouvertes.',
    no_detour:'Aucun détour en cours.',unknown_target:'Cet endroit n\'existe pas dans la présentation.',
    unknown_anchor:'Cette ancre n\'existe pas sur la scène.',mode_switch_refused:'Le mode d\'interaction n\'a pas pu être changé pour cette lecture.',
    illegal_transition:'Pas possible maintenant.',empty_score:'La partition est vide.',role_invalid:'Ce rôle ne convient pas.',
  });
  const PROBLEMS=Object.freeze({
    mode_restore_failed:'Le mode d\'interaction n\'a pas pu être rétabli : basculez sur un autre Board puis revenez sur celui-ci pour réappliquer le mode de son type.',
    aux_retire_failed:'Une ressource annexe n\'a pas pu être retirée.',
    stage_release_failed:'La surface de lecture n\'a pas pu être libérée.',
    aux_stage_failed:'La ressource annexe n\'a pas pu s\'afficher.',score_problems:'La partition ne correspond plus aux scènes : corrigez-la.',
    art_direction_changed:'La direction artistique a changé pendant la lecture.',
    anchor_control_not_toggle:'Une ancre pilote un réglage qui n\'est pas un interrupteur : le repère est suivi, pas l\'image.',
    /* Ligne de temps Remotion (Slice 12) : ce que la partition demande à une scène Remotion et que la ligne de temps ne tient pas. */
    timeline_unresolved:'La durée de la scène Remotion est introuvable : elle se joue une fois depuis sa première image, sans suivre les ancres de la partition.',
    timeline_anchor_clamped:'Une ancre tombe après la fin de la scène Remotion : elle a été ramenée à la dernière image.',
    timeline_anchors_share_frame:'Deux ancres de la scène Remotion tombent sur la même image : la première n\'a aucun tronçon à jouer.',
    timeline_anchors_partly_timed:'Seules certaines ancres de la scène Remotion ont une position (at_ms) : les autres sont réparties à parts égales.',
    /* Slice 09 : une synchronisation de la scène bornée, et un arrêt qui l'interrompt. */
    stage_timeout:'La scène n\'a pas pu s\'afficher à temps : la lecture est en pause. « Reprendre » réessaie, « Arrêter » arrête.',
    stage_preempted:'L\'affichage de la scène a été interrompu par l\'arrêt.',
    /* Jarvis présente (Slice 14) : pourquoi la voix n'a pas pu dire la ligne ; « Continuer » réessaie. */
    announce_refused:'Jarvis n\'a pas pu prendre la ligne (aucune conversation en cours, parole retenue ou arrêt en cours). Continuer réessaie.',
    announce_failed:'La ligne n\'a pas pu être remise à la voix (erreur de Core). Continuer réessaie.',
    speech_not_started:'La voix n\'a pas commencé la ligne à temps (voix non connectée, ou ligne retenue par le mode). Continuer réessaie.',
    speech_stalled:'La voix n\'a pas fini la ligne à temps. Continuer réessaie.',
    speech_failed:'La voix n\'a pas pu dire la ligne. Continuer réessaie.',
    speech_obsolete:'La ligne a été abandonnée avant d\'être dite (nouvelle demande, délai dépassé, ou retenue par le mode). Continuer la redit.',
    speech_unconfirmed:'Aucun son n\'a été entendu pour cette ligne. Continuer réessaie.',
    line_invalid:'Cette ligne de la partition ne peut pas être dite telle quelle.',
    presenter_crashed:'Le présentateur Jarvis a rencontré une erreur : la lecture a été arrêtée proprement.',
  });
  /* Le suiveur de cues (voix) : le texte dit POURQUOI et ce qui marche encore. */
  const FOLLOWER_ABSENT='Suivi vocal indisponible : les cues dites ne feront pas avancer la présentation (il faut l\'architecture vocale '+
    'OpenAI ambiante). La lecture continue au clavier et à la souris.';
  const FOLLOWER_WAITING='Suivi vocal : connexion…';
  /* Slice 05 rework (P1) : un segment vidéo sans nouvelle de la page (fin perdue, page fermée). Core tient la scène (jamais un saut) et le
     dit ; « Suivant » et « Arrêter » marchent toujours. */
  function pageWaitText(wait,scene){
    const which=scene&&Number.isInteger(scene.number)?`Scène ${scene.number}`:'La scène';
    /* Slice 07 rework (I1) : un silence de Jarvis sur une scène Remotion dont la ligne de temps n'a pas pu être lue : tenue, et dite. */
    if(wait.reason==='timeline_unresolved')return `${which} : la ligne de temps de la vidéo n'a pas pu être lue, la scène est tenue `+
      `depuis ${Math.round((wait.waited_ms||0)/1000)} s (jamais coupée) ; « Suivant » ou « Arrêter » restent possibles.`;
    return `${which} : lecture en attente de la page, rien n'a été signalé depuis ${Math.round((wait.waited_ms||0)/1000)} s. `+
      'Elle reste à l\'écran, jamais sautée ; « Suivant » ou « Arrêter » restent possibles.';
  }

  function messageOf(error){return String(error&&error.message||error||'erreur inconnue')}
  function pad(n){return n<10?'0'+n:String(n)}
  function clock(ms){const s=Math.max(0,Math.floor(ms/1000));return pad(Math.floor(s/60))+':'+pad(s%60)}
  function active(view){return !!view&&view.running===true&&view.phase!=='stopped'&&view.phase!=='idle'}

  function createStudioPlayer(deps){
    const win=deps.window||root;
    const request=deps.request;
    const now=deps.now||(()=>Date.now());
    const setT=deps.setTimeout||((fn,ms)=>win.setTimeout(fn,ms));
    const clearT=deps.clearTimeout||(id=>win.clearTimeout(id));
    const toast=typeof deps.toast==='function'?deps.toast:null;
    const log=deps.log||((level,event,data)=>{
      const line=`[studio] ${event} ${JSON.stringify(data||{})}`;
      if(level==='error')console.error(line);else if(level==='warn')console.warn(line);else console.info(line);
    });
    const stats={polls:0,pollFailures:0,commands:0,refused:0,failed:0,dropped:0,surfaces:0};

    let view={phase:'idle',running:false};
    let viewAt=now();
    let inflight=null;            /* {verb, at} */
    let queue=Promise.resolve();
    let queued=0;
    let failures=0;
    let linkLostSince=null;
    let pollTimer=null;
    let started=false;
    let visible=true;
    let preloadKey=null;          /* la scène qui suit, telle que la vue la nomme ; sa source et ses valeurs viennent de `GET .../preload` */
    let preloadData=null;
    let preloadDirty=false;
    let surfaceKey=null;          /* `id|rev` de la surface déjà lue (`GET .../surface`) */
    let surface=null;

    function emit(name,detail){
      if(typeof win.dispatchEvent!=='function'||typeof win.CustomEvent!=='function')return;
      try{win.dispatchEvent(new win.CustomEvent(name,{detail}))}
      catch(error){log('warn','studio.event_failed',{event:name,error:messageOf(error)})}
    }

    /* ---------------------------------------------------------------- vue venue de Core */
    function adopt(next){
      const was=view;
      view=next&&typeof next==='object'?next:{phase:'idle',running:false};
      viewAt=now();
      if(was&&(was.running===true)!==(view.running===true))emit('jarvis:studio-playback',{running:view.running===true});
      emit('jarvis:studio-view',{view});
      syncSurface();
      syncPreload();
      announceTimeline(was);
    }
    /* La ligne de temps de la partition : dite au lecteur de Variantes à chaque vue qui en porte une, et une dernière fois, vide, quand elle
       disparaît. `object_id` est la surface de la lecture (`variants-run-<run_id>`), l'id sous lequel Variantes monte le cadre. */
    function announceTimeline(was){
      const has=!!view.timeline,had=!!(was&&was.timeline);
      if(!has&&!had&&!preloadDirty)return;
      preloadDirty=false;
      emit('jarvis:studio-timeline',{object_id:view.stage_object_id||null,timeline:has?view.timeline:null,preload:preloadData});
    }
    /* La surface (Slice 09) : relue une fois par révision ; vide quand la lecture finit. Un échec est dit (console), la vue suivante réessaie. */
    function syncSurface(){
      const ref=active(view)&&view.surface&&typeof view.surface.id==='string'?view.surface:null;
      const key=ref?`${ref.id}|${ref.rev}`:null;
      if(!key){surfaceKey=null;if(surface!==null){surface=null;emit('jarvis:studio-surface',{surface:null})}return}
      if(key===surfaceKey)return;
      surfaceKey=key;
      call(`${ROUTE}/surface`,{method:'GET',timeoutMs:6000}).then(answer=>{
        if(surfaceKey!==key)return;
        if(answer.status!==200){surfaceKey=null;log('warn','studio.surface_failed',{status:answer.status});return}
        const got=answer.body&&answer.body.surface||null;
        if(got&&got.surface_id!==ref.id){surfaceKey=null;return}   /* une autre lecture entre-temps : la vue suivante relira */
        surface=got;stats.surfaces++;
        emit('jarvis:studio-surface',{surface});
      }).catch(error=>{if(surfaceKey===key)surfaceKey=null;log('warn','studio.surface_failed',{error:messageOf(error)})});
    }
    /* La scène qui suit (autre source) : lue UNE fois par scène annoncée, puis donnée au suiveur qui la charge à côté, en pause. Un échec
       n'est qu'une optimisation perdue : la scène se chargera à son tour. */
    function syncPreload(){
      const next=active(view)?view.next_scene:null;
      const key=next?`${next.scene_id}|${next.prefab}|${next.rev}`:null;
      if(key===preloadKey)return;
      preloadKey=key;preloadData=null;
      if(!key)return;
      call(`${ROUTE}/preload`,{method:'GET',timeoutMs:6000}).then(answer=>{
        if(preloadKey!==key||answer.status!==200)return;
        const hint=answer.body&&answer.body.preload;
        if(hint&&hint.scene_id===next.scene_id&&hint.prefab){preloadData=hint;preloadDirty=true;announceTimeline(view)}
      }).catch(error=>log('warn','studio.preload_failed',{error:messageOf(error)}));
    }

    /* ---------------------------------------------------------------- réseau */
    async function call(url,options){
      const timeoutMs=options.timeoutMs||COMMAND_TIMEOUT_MS;
      let timer=null;
      const timeout=new Promise((_,reject)=>{timer=setT(()=>reject(new Error(`Core ne répond pas depuis ${Math.round(timeoutMs/1000)} s`)),timeoutMs)});
      try{return await Promise.race([request(url,options),timeout])}
      finally{if(timer!==null)clearT(timer)}
    }

    async function refresh(){
      stats.polls++;
      try{
        const answer=await call(ROUTE,{method:'GET',timeoutMs:6000});
        if(answer.status!==200){
          const error=answer.body&&answer.body.error||{};
          throw new Error(String(error.message||`HTTP ${answer.status}`)+(error.code?` (${error.code})`:''));
        }
        failures=0;
        if(linkLostSince!==null){linkLostSince=null;log('info','studio.link_restored',{})}
        adopt(answer.body&&answer.body.state);
      }catch(error){
        failures++;stats.pollFailures++;
        log('warn','studio.poll_failed',{error:messageOf(error),failures});
        if(failures>=LINK_LOST_AFTER&&linkLostSince===null&&active(view)){
          linkLostSince=now();
          if(toast)toast({title:'Lecture : Core injoignable',sub:messageOf(error),kind:'bad'});
          console.error('[studio] studio.link_lost '+JSON.stringify({error:messageOf(error)}));
          emit('jarvis:studio-view',{view});
        }
      }
    }
    function schedule(){
      if(!started||!visible)return;
      if(pollTimer!==null)clearT(pollTimer);
      const base=active(view)?(view.timeline?POLL_TIMELINE_MS:POLL_ACTIVE_MS):POLL_IDLE_MS;
      const delay=failures?Math.min(POLL_BACKOFF_MAX_MS,base*Math.pow(2,failures-1)):base;
      pollTimer=setT(async()=>{pollTimer=null;await refresh();schedule()},delay);
    }

    /* ---------------------------------------------------------------- commandes */
    function command(verb,body,quiet){
      if(!quiet&&queued>=QUEUE_MAX){stats.dropped++;log('warn','studio.command_dropped',{verb});return Promise.resolve({status:'dropped',reason:'queue_full'})}
      queued++;
      const run=queue.then(()=>send(verb,body||{},quiet===true));
      queue=run.catch(()=>null).then(()=>{queued--});
      return run;
    }
    /* `quiet` : un fait que la page dit à Core (début / fin de segment), pas un geste de l'utilisateur : ni toast ni commande en vol ; l'état
       que Core rend est adopté, un échec n'est qu'une ligne de console. Rend la réponse de Core (`status` : applied, refused, stage_failed),
       ou `{status: 'failed', message}` quand Core n'a pas pu répondre. */
    async function send(verb,body,quiet){
      stats.commands++;
      if(!quiet)inflight={verb,at:now()};
      try{
        const answer=await call(`${ROUTE}/${encodeURIComponent(verb)}`,{method:'POST',body:JSON.stringify(body),timeoutMs:COMMAND_TIMEOUT_MS});
        const payload=answer.body||{};
        if(answer.status===200&&payload.status==='applied'){adopt(payload.state);return payload}
        if(quiet){
          if(payload.state)adopt(payload.state);
          log('info','studio.report_not_applied',{verb,status:payload.status||answer.status,reason:payload.reason||null});
          return payload;
        }
        if(payload.status==='refused'){   /* 409 (pas le moment) ou 422 (la demande elle-même est invalide) */
          stats.refused++;
          adopt(payload.state||view);
          log('info','studio.refused',{verb,reason:payload.reason});
          return payload;
        }
        if(payload.status==='stage_failed'){
          stats.failed++;
          adopt(payload.state||view);
          if(toast)toast({title:'Lecture : la scène n\'a pas suivi',sub:String(payload.message||payload.reason||''),kind:'bad'});
          console.error('[studio] studio.stage_failed '+JSON.stringify({verb,reason:payload.reason,message:payload.message}));
          return payload;
        }
        const error=payload.error||{};
        throw new Error(String(error.message||`HTTP ${answer.status}`)+(error.code?` (${error.code})`:''));
      }catch(error){
        stats.failed++;
        if(quiet){log('warn','studio.report_failed',{verb,error:messageOf(error)});return null}
        if(toast)toast({title:'Lecture : commande impossible',sub:messageOf(error),kind:'bad'});
        console.error('[studio] studio.command_failed '+JSON.stringify({verb,error:messageOf(error)}));
        return {status:'failed',command:verb,message:`${verb} impossible : ${messageOf(error)}`};
      }finally{
        if(!quiet)inflight=null;
      }
    }

    /* Ce que le suiveur du lecteur dit d'un segment : un fait, rendu à Core tel quel (il le juge contre son propre segment et son horloge). */
    function onSegment(event){
      const detail=event&&event.detail;
      if(!detail||!active(view)||(detail.event!=='started'&&detail.event!=='done')||!Number.isInteger(detail.seq)||detail.seq<0)return;
      command('advance',{seq:detail.seq,event:detail.event},true);
    }

    /* ---------------------------------------------------------------- cycle de vie */
    function start(){
      if(started)return;
      started=true;
      if(typeof win.addEventListener==='function')win.addEventListener('jarvis:studio-segment',onSegment);
      refresh().then(schedule);
    }
    function stop(){
      started=false;
      if(pollTimer!==null){clearT(pollTimer);pollTimer=null}
      if(typeof win.removeEventListener==='function')win.removeEventListener('jarvis:studio-segment',onSegment);
    }
    function setVisible(value){
      const next=!!value;if(next===visible)return;visible=next;
      if(!visible){if(pollTimer!==null){clearT(pollTimer);pollTimer=null}return}
      if(started)refresh().then(schedule);
    }

    return {start,stop,setVisible,refresh,command,adopt,onSegment,
      view:()=>view,surface:()=>surface,stats:()=>Object.assign({},stats),
      state:()=>({inflight,failures,linkLostSince,started,visible,viewAt}),
      /* Variantes, le rail : démarre une lecture par la MÊME route que la voix (le refus de Core est rendu tel quel). */
      startRun:(presentationId,role,extra)=>command('start',Object.assign({presentation_id:presentationId,role},extra||{}))};
  }

  const api=Object.freeze({ROUTE,ROLE_LABEL,PHASE_LABEL,REFUSALS,PROBLEMS,FOLLOWER_ABSENT,FOLLOWER_WAITING,COMMAND_TIMEOUT_MS,POLL_ACTIVE_MS,
    POLL_TIMELINE_MS,POLL_IDLE_MS,createStudioPlayer,clock,pageWaitText,active});
  root.JarvisStudioPlayerCore=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installStudioPlayer(){
    const request=async(url,options)=>{
      const response=await fetch(url,{method:options.method||'GET',headers:options.body?{'Content-Type':'application/json'}:undefined,
        body:options.body});
      let body=null;
      try{body=await response.json()}catch(error){body=null /* non-JSON answer: the caller reports the HTTP status */}
      return {status:response.status,body};
    };
    const player=createStudioPlayer({window,request,toast:typeof toast==='function'?toast:null});
    document.addEventListener('visibilitychange',()=>player.setVisible(document.visibilityState!=='hidden'));
    window.JarvisStudioPlayer=Object.freeze({start:player.start,stop:player.stop,refresh:player.refresh,command:player.command,
      startRun:player.startRun,view:player.view,surface:player.surface,stats:player.stats,state:player.state});
    player.start();
  }
  /* Rattrapé ici : la page servie n'a qu'une balise <script> ; une levée emporterait la page avec elle. */
  try{installStudioPlayer()}
  catch(error){console.error('[studio] studio.player_not_installed '+JSON.stringify({error:String(error&&error.message||error)}))}
})(typeof window!=='undefined'?window:globalThis);
