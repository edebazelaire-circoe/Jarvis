/* Contrôleur de capture du Control Center — capture d'écran, enregistrement
   audio, enregistrement d'écran : la vérité de Core, publiée en modèle de vue.

   Né en Slice 10 de `jarvis-session-context-recording-runtime` (rail de
   gauche, D14/D15) ; découpé en Slice 04 de `jarvis-board-orbital-ui-
   workspace-rail` (architecture résolue §5, D6, D3/D4) : ce fichier ne dessine
   plus rien. Il tient le **contrôleur** (sondage, écritures, relecture) et
   publie un modèle de vue ; les vues sont dans `control_center_capture_wheel.js`
   (secteurs Vidéo / Capture d'écran / Audio de la roue d'outils, sous-arcs de
   cibles, indicateurs persistants `#recIndicators`). Contrat :
   `docs/capture.md` › *Interface*.

   API (`window.JarvisCaptureRail`) : `subscribe(fn)` (appelée tout de suite
   puis à chaque peinture ; rend la fonction qui désabonne), `start(channel,
   {device})`, `screenshot({device})` (rend `{capture, artifact}` ou `null`),
   `stop(captureId)`, `targets()` (`GET /api/captures/targets`), `act(control)`
   (l'activation simple d'un secteur), `view()`, `note()`, `dismiss()`,
   `poll()`, `wake()`.

   **Ce ne sont pas des outils Bare Hands** (D15) : ce module ne lit ni
   `BH.TOOL` ni `describeTools()`.

   **Aucun état local de capture.** Ce qui est dit « en cours » vient
   **toujours** du dernier `GET /api/captures/status` réussi (relais du
   Control Center vers Core, `capture_relay.py`) ; jamais d'un clic. Une
   demande ouvre une attente visible (« démarrage… », compteur de secondes),
   part en `POST`, puis relit le statut. Un démarrage refusé n'a donc rien à
   défaire : rien n'a été peint actif, et le refus s'écrit en clair. Le
   chronomètre part de `activated_at` (à défaut `created_at`) rendu par Core,
   pas de l'heure du clic : un second onglet, un rechargement ou un démarrage
   par le cerveau affichent la même durée.

   **Plusieurs captures par canal.** Core tient une capture continue par
   canal **et par appareil** (`already_active`) : deux écrans peuvent
   s'enregistrer ensemble. Le modèle publie, par canal, la liste
   `captures` de toutes les captures ouvertes ; les champs du canal (`state`,
   `action`, `captureId`, chronomètre) décrivent la plus récente.

   **Statut perdu = état inconnu.** Si le sondage tombe (Control Center ou
   Core injoignable, délai dépassé), aucune commande n'est dite active, aucun
   démarrage n'est proposé. Les enregistrements que l'on savait ouverts juste
   avant peuvent encore être **arrêtés** (vie privée d'abord), chacun, et sont
   oubliés une fois l'arrêt accepté. Une demande pendant la perte relance une
   lecture tout de suite (sans attendre le recul) ; elle ne démarre rien.

   **Pourquoi un sondage et pas un flux.** La page n'a aucun flux poussé
   générique et `/api/status` ne porte pas les captures. Cadence (décision PM
   de la reprise QA de la Slice 10) : 1 s tant qu'une capture est ouverte,
   qu'une écriture est en vol, et 10 s après une écriture ; 3 s au repos ;
   20 s onglet caché ; statut perdu → recul exponentiel jusqu'à 15 s (chaque
   lecture ratée laisse une ligne au journal du relais), retour à la cadence
   normale au premier succès. Chaque sondage a une échéance : passé
   `statusDeadlineMs`, le statut est réputé perdu.

   **Relecture après écriture.** Une lecture partie **avant** la fin d'une
   écriture peut revenir après elle avec l'état d'avant : le contrôleur
   l'attend, puis en lance une neuve (`fresh`), et la demande reste en attente
   jusqu'au retour de celle-ci. Jamais un « repos » périmé après un
   démarrage, ni un « actif » périmé après un arrêt.

   Deux blocs : le **modèle pur et le contrôleur** (dépendances injectées,
   exécutés par node dans `tests/unit/test_capture_rail_js.py`) et le **bloc
   navigateur** (relie `fetch`, horloge, visibilité de l'onglet, et publie
   `window.JarvisCaptureRail`). Insertion : `control_center.py` /
   `control_center.html`, avant la roue et ses vues. */
(function(root){
  'use strict';

  const CONTROL=Object.freeze({SCREENSHOT:'screenshot',AUDIO:'audio',SCREEN:'screen'});
  /* L'action ponctuelle d'abord, puis les deux canaux. */
  const ORDER=Object.freeze([CONTROL.SCREENSHOT,CONTROL.AUDIO,CONTROL.SCREEN]);
  const CHANNELS=Object.freeze([CONTROL.AUDIO,CONTROL.SCREEN]);

  /* Les états publiés. `busy`/`done` n'existent que pour la capture d'écran,
     `starting`/`active`/`stopping`/`stuck` que pour les deux canaux. */
  const STATE=Object.freeze({
    IDLE:'idle',STARTING:'starting',ACTIVE:'active',STOPPING:'stopping',STUCK:'stuck',
    ERROR:'error',UNKNOWN:'unknown',BUSY:'busy',DONE:'done',
  });
  const OPEN_STATES=new Set(['starting','active','stopping']);
  const BAD_ENDS=new Set(['partial','failed']);
  const DEFAULT_DEVICE='default';

  /* `recent` ne sert qu'à voir finir une capture que l'on voyait ouverte :
     trois lignes suffisent entre deux sondages d'une seconde (Core borne
     `recent` à 0..20, défaut 5). */
  const RECENT_ROWS=3;
  const ROUTES=Object.freeze({
    status:`/api/captures/status?recent=${RECENT_ROWS}`,
    targets:'/api/captures/targets',
    start:'/api/captures/start',
    screenshot:'/api/captures/screenshot',
    stop:id=>`/api/captures/${encodeURIComponent(id)}/stop`,
  });

  const TIMING=Object.freeze({
    /* Capture ouverte, écriture en vol ou récente (`afterWriteMs`) : 1 s.
       Repos : 3 s. Onglet caché : 20 s. */
    fastPollMs:1000,idlePollMs:3000,hiddenPollMs:20000,afterWriteMs:10000,
    /* Statut perdu : 1, 2, 4, 8 puis 15 s entre deux essais. */
    lostBackoffMaxMs:15000,
    /* Le relais donne 10 s à une lecture ; une page qui attendrait autant
       laisserait un « en cours » vieux de dix secondes passer pour vrai. */
    statusDeadlineMs:6000,
    /* Le relais donne 45 s à une écriture (démarrage borné à 15 s par Core,
       arrêt à 10 s + réparation) : la page attend un peu plus, puis rend la
       main et relit le statut. */
    writeDeadlineMs:50000,
    /* La confirmation de la capture d'écran reste visible ce temps-là. */
    doneMs:2500,
    tickMs:1000,
  });

  const LABEL=Object.freeze({
    [CONTROL.SCREENSHOT]:'Capture d’écran',
    [CONTROL.AUDIO]:'Enregistrement audio',
    [CONTROL.SCREEN]:'Enregistrement d’écran',
  });

  /* ------------------------------------------------- les textes d'erreur

     Courts, en français, et **le code reste visible** entre parenthèses : la
     phrase est pour l'œil, le code pour le diagnostic (et pour retrouver la
     ligne dans le journal). Un code inconnu n'est jamais rebaptisé en une
     cause plausible : il est affiché tel quel. Une phrase ne porte donc
     **aucune** parenthèse (elle s'accolerait à celle du code) et ne répète
     pas le verbe de la note (« interrompu — interrompu… »). */
  const TEXT=Object.freeze({
    source_unavailable:Object.freeze({audio:'micro indisponible',screen:'écran indisponible',
      screenshot:'écran indisponible'}),
    permission_denied:Object.freeze({audio:'accès au micro refusé par Windows',
      screen:'accès à l’écran refusé, session peut-être verrouillée',
      screenshot:'accès à l’écran refusé, session peut-être verrouillée'}),
    already_active:'déjà en cours',
    storage_full:'disque plein',
    storage_unavailable:'dossier de stockage inaccessible',
    write_failed:'écriture impossible',
    finalize_failed:'finalisation impossible, fichier partiel gardé',
    source_timeout:'la source n’a pas répondu à temps',
    source_lost:'source perdue en cours de route',
    unsupported_platform:'capture non prise en charge sur ce poste',
    unsupported_source:'aucune source de capture installée',
    invalid_capture:'demande invalide',
    capture_not_found:'capture introuvable',
    capture_association_unavailable:'Session ou Context illisible',
    capture_service_stopping:'Jarvis s’arrête',
    core_unavailable:'Jarvis démarre encore',
    core_unreachable:'Core de Jarvis injoignable',
    core_unconfigured:'Core non configuré',
    core_timeout:'pas de réponse à temps, issue inconnue',
    client_timeout:'pas de réponse à temps, issue inconnue',
    network:'Control Center injoignable',
    forbidden_origin:'requête refusée, origine non autorisée',
    recoverable_partial:'fichier partiel récupéré',
    capture_interrupted:'rien de récupérable',
    capture_gap:'trou dans l’enregistrement',
    capture_invalid_transition:'transition refusée, défaut interne',
    targets_unreadable:'liste des cibles illisible',
    status_unknown:'état des captures inconnu, Jarvis injoignable',
  });
  const FFMPEG_HINT='ffmpeg manquant : installez l’extra « capture » ou définissez JARVIS_FFMPEG_EXE';

  function refusalText(code,message,control){
    const key=String(code||'');
    if(key==='source_unavailable'&&/ffmpeg/i.test(String(message||'')))return FFMPEG_HINT;
    const entry=TEXT[key];
    if(typeof entry==='string')return entry;
    if(entry&&entry[control])return entry[control];
    return key?`échec (${key})`:'cause inconnue';
  }

  /* La phrase complète d'une note : quoi, puis pourquoi, puis le code. Le
     tiret sépare le fait de sa cause : le texte de la cause peut lui-même
     porter un deux-points (ffmpeg). */
  function noteText(control,verb,code,message){
    const why=refusalText(code,message,control);
    return `${LABEL[control]} ${verb} — ${why}${code&&why.indexOf(code)<0?` (${code})`:''}.`;
  }

  /* ------------------------------------------------- durées */

  function clock(seconds){
    const s=Math.max(0,Math.floor(Number(seconds)||0));
    const h=Math.floor(s/3600),m=Math.floor((s%3600)/60),r=s%60;
    const two=v=>String(v).padStart(2,'0');
    return h?`${h}:${two(m)}:${two(r)}`:`${m}:${two(r)}`;
  }

  /* Secondes écoulées depuis l'horodatage `since` de Core, figées à `until`
     s'il existe (arrêt demandé). `null` si l'horodatage est illisible : on
     n'invente pas une durée. */
  function elapsedOf(since,until,now){
    const start=Date.parse(String(since||''));
    if(!Number.isFinite(start))return null;
    const end=until?Date.parse(String(until)):now;
    return Math.max(0,Math.floor(((Number.isFinite(end)?end:now)-start)/1000));
  }

  /* ------------------------------------------------- le modèle pur */

  const isObject=v=>!!v&&typeof v==='object'&&!Array.isArray(v);

  /* Les captures continues **ouvertes** d'un canal, selon Core, de la plus
     ancienne à la plus récente. */
  function opensOf(status,channel){
    const rows=isObject(status)&&Array.isArray(status.captures)?status.captures:[];
    return rows.filter(row=>isObject(row)&&row.channel===channel&&row.mode==='continuous'&&OPEN_STATES.has(row.state))
      .sort((a,b)=>String(a.created_at||'')<String(b.created_at||'')?-1:String(a.created_at||'')>String(b.created_at||'')?1:0);
  }
  /* La plus récente (le canal est décrit par elle). */
  function openOf(status,channel){
    const rows=opensOf(status,channel);
    return rows.length?rows[rows.length-1]:null;
  }
  function stuckOf(status,captureId){
    const rows=isObject(status)&&Array.isArray(status.stuck)?status.stuck:[];
    return rows.find(row=>isObject(row)&&row.capture_id===captureId)||null;
  }
  /* Les captures « connues ouvertes » d'un canal (statut perdu) : une liste,
     ou l'ancienne forme `{capture_id}`. */
  function knownOf(known,channel){
    const raw=isObject(known)?known[channel]:null;
    const list=Array.isArray(raw)?raw:isObject(raw)?[raw]:[];
    return list.filter(row=>isObject(row)&&row.capture_id);
  }

  /* Le modèle de vue de chaque commande, depuis :
     - `status` : le dernier statut de Core, `reachable` : le sondage tient ;
     - `pending` : la demande en vol par commande (`{kind, since, device?}`) ;
       un démarrage par canal, une prise d'écran (l'ancienne forme
       `{kind:'stop', captureId}` reste lue) ;
     - `stops` : les arrêts en vol, par id de capture (`{since, captureId,
       channel}`) : deux enregistrements s'arrêtent sans s'attendre ;
     - `failure` : le dernier refus par commande (`{code, text, verb?}`) ;
     - `known` : les captures ouvertes connues par canal (statut perdu) ;
     - `shotAt` : l'heure de la dernière capture d'écran réussie ; `now`.
     **Aucune** de ces entrées ne peut dire un canal actif : seul `status` le
     peut, et seulement quand `reachable` est vrai. */
  function viewOf(input){
    const i=isObject(input)?input:{};
    const now=Number(i.now)||0;
    const reachable=!!i.reachable&&isObject(i.status);
    const status=reachable?i.status:null;
    const pending=isObject(i.pending)?i.pending:{};
    const stops=isObject(i.stops)?i.stops:{};
    const failure=isObject(i.failure)?i.failure:{};
    const controls={};
    let recording=0,troubled=0;
    const waitOf=since=>Math.max(0,Math.floor((now-(Number(since)||now))/1000));

    for(const channel of CHANNELS){
      const pend=isObject(pending[channel])?pending[channel]:null;
      const startPend=pend&&pend.kind==='start'?pend:null;
      const legacyStop=pend&&pend.kind==='stop'?pend:null;
      const stopFor=id=>(id&&isObject(stops[id])?stops[id]:null)
        ||(legacyStop&&(!legacyStop.captureId||legacyStop.captureId===id)?legacyStop:null);
      const anyStop=legacyStop||Object.values(stops).find(s=>isObject(s)&&s.channel===channel)||null;
      const opens=status?opensOf(status,channel):[];
      const open=opens.length?opens[opens.length-1]:null;
      const fail=isObject(failure[channel])?failure[channel]:null;
      let state,action=null,captureId=null,since=null,until=null,stuck=null,waitSince=null;
      if(!reachable){
        if(anyStop){state=STATE.STOPPING;waitSince=anyStop.since}
        else if(startPend){state=STATE.STARTING;waitSince=startPend.since}
        else{
          state=STATE.UNKNOWN;
          const known=knownOf(i.known,channel).filter(row=>!stopFor(row.capture_id));
          const last=known.length?known[known.length-1]:null;
          if(last){captureId=last.capture_id;action='stop'}
        }
      }else if(open){
        captureId=open.capture_id;
        since=open.activated_at||open.created_at;
        stuck=stuckOf(status,captureId);
        const mine=stopFor(captureId);
        if(stuck){state=STATE.STUCK;action='stop'}
        else if(mine){state=STATE.STOPPING;until=open.stop_requested_at||null;waitSince=mine.since}
        /* Notre démarrage est en vol et Core n'a pas encore activé la ligne :
           c'est toujours un démarrage, même si Core la referme déjà (refus de
           la source : `starting` → `stopping` → `failed`). Tant que Core la
           tient `starting`, son id est connu et Core accepte l'arrêt : il est
           offert (vie privée d'abord), comme pour un démarrage venu
           d'ailleurs. Une ligne déjà en `stopping` n'a plus rien à arrêter. */
        else if(startPend&&open.state!=='active'){
          state=STATE.STARTING;waitSince=startPend.since;
          if(open.state==='starting')action='stop';
        }
        else if(open.state==='stopping'){state=STATE.STOPPING;until=open.stop_requested_at||null}
        else if(open.state==='starting'){state=STATE.STARTING;action='stop'}
        else{state=STATE.ACTIVE;action='stop'}
      }else if(startPend){state=STATE.STARTING;waitSince=startPend.since}
      else if(fail){state=STATE.ERROR;action='start'}
      else{state=STATE.IDLE;action='start'}

      const opened=!!(reachable&&open);
      if(opened)recording+=1;
      if(state===STATE.STUCK||state===STATE.ERROR)troubled+=1;
      const waited=waitSince!==null&&waitSince!==undefined?waitOf(waitSince):null;
      const seconds=opened&&state!==STATE.STARTING?elapsedOf(since,until,now):null;

      /* Chaque capture ouverte du canal, la plus ancienne d'abord : ce que
         les indicateurs et la liste d'arrêt du sous-arc montrent. */
      const captures=(reachable?opens.map(row=>{
        const rowStuck=stuckOf(status,row.capture_id),mineStop=stopFor(row.capture_id);
        let s,a=null,u=null;
        if(rowStuck){s=STATE.STUCK;a='stop'}
        else if(mineStop||row.state==='stopping'){s=STATE.STOPPING;u=row.stop_requested_at||null}
        else if(row.state==='starting'){s=STATE.STARTING;a='stop'}
        else{s=STATE.ACTIVE;a='stop'}
        const secs=s===STATE.STARTING?null:elapsedOf(row.activated_at||row.created_at,u,now);
        return captureView(channel,row.capture_id,row.device,s,a,secs,
          mineStop?waitOf(mineStop.since):null,rowStuck?rowStuck.error_code:null);
      }):knownOf(i.known,channel).map(row=>{
        const mineStop=stopFor(row.capture_id);
        return captureView(channel,row.capture_id,row.device,mineStop?STATE.STOPPING:STATE.UNKNOWN,
          mineStop?null:'stop',null,mineStop?waitOf(mineStop.since):null,null);
      }));

      controls[channel]=Object.freeze({
        id:channel,kind:'channel',state,action,captureId,
        /* `pressed` = Core dit qu'une capture est ouverte. Rien d'autre. */
        pressed:opened,
        /* La marque d'arrêt suit **l'action** : elle dit « activer arrête » et
           n'apparaît que si c'est vrai (actif, démarrage dont Core tient la
           ligne, capture connue ouverte quand le statut tombe), puis reste,
           estompée, pendant l'arrêt. Un arrêt bloqué garde son « ! ». */
        stopMark:state!==STATE.STUCK&&(action==='stop'||state===STATE.STOPPING),
        seconds,waited,
        timer:seconds!==null?clock(seconds):(waited!==null?`${waited} s`:''),
        /* La durée, pour la description accessible : hors du nom, qui ne doit
           pas changer chaque seconde (un lecteur d'écran le réannoncerait). */
        detail:seconds!==null
          ?(state===STATE.STOPPING?`durée ${clock(seconds)}`:`en cours depuis ${clock(seconds)}`)
          :(waited!==null?`attente depuis ${waited} s`:''),
        code:stuck?stuck.error_code:(fail&&state===STATE.ERROR?fail.code:null),
        label:labelOf(channel,state,{stuck,fail,action}),
        /* Un démarrage en vol (pour quel appareil) même quand une autre
           capture du canal est déjà ouverte. */
        pendingStart:startPend?Object.freeze({device:startPend.device||DEFAULT_DEVICE,
          waited:waitOf(startPend.since)}):null,
        captures:Object.freeze(captures),
      });
    }

    {
      const pend=isObject(pending.screenshot)?pending.screenshot:null;
      const fail=isObject(failure.screenshot)?failure.screenshot:null;
      let state,action=null;
      if(pend)state=STATE.BUSY;
      else if(!reachable)state=STATE.UNKNOWN;
      else if(fail){state=STATE.ERROR;action='shot'}
      else if(i.shotAt&&now-i.shotAt<TIMING.doneMs){state=STATE.DONE;action='shot'}
      else{state=STATE.IDLE;action='shot'}
      if(state===STATE.ERROR)troubled+=1;
      const waited=pend?waitOf(pend.since):null;
      controls.screenshot=Object.freeze({
        id:CONTROL.SCREENSHOT,kind:'shot',state,action,captureId:null,
        /* Une action ponctuelle n'a pas d'état enfoncé. */
        pressed:null,stopMark:false,seconds:null,waited,timer:waited!==null?`${waited} s`:'',
        detail:waited!==null?`attente depuis ${waited} s`:'',
        code:fail&&state===STATE.ERROR?fail.code:null,
        label:labelOf(CONTROL.SCREENSHOT,state,{fail}),
        device:pend&&pend.device||null,
      });
    }

    return Object.freeze({
      reachable,recording,troubled,
      /* Un enregistrement en cours reste dit même quand une autre commande est
         en erreur : « REC 1 ! » plutôt qu'un « ERREUR » qui le cacherait. */
      caption:!reachable?'ÉTAT ?':recording?`REC ${recording}${troubled?' !':''}`:troubled?'ERREUR':'CAPTURE',
      controls:Object.freeze(controls),
    });
  }

  function captureView(channel,captureId,device,state,action,seconds,waited,code){
    return Object.freeze({
      channel,captureId,device:device||DEFAULT_DEVICE,state,action,seconds,waited,code:code||null,
      timer:seconds!==null&&seconds!==undefined?clock(seconds):(waited!==null&&waited!==undefined?`${waited} s`:''),
      detail:seconds!==null&&seconds!==undefined
        ?(state===STATE.STOPPING?`durée ${clock(seconds)}`:`en cours depuis ${clock(seconds)}`)
        :(waited!==null&&waited!==undefined?`attente depuis ${waited} s`:''),
      stopMark:state!==STATE.STUCK&&(action==='stop'||state===STATE.STOPPING),
      label:labelOf(channel,state,{action,stuck:code?{error_code:code}:null}),
    });
  }

  /* Le nom accessible d'une commande, une seule phrase. Elle ne porte
     **aucun** compteur : la durée vit dans `detail` (description). Une erreur
     dit si elle vient d'un essai de cette page (`dernier essai`) ou d'une fin
     que personne ici n'a demandée (`précédent interrompu`). */
  function labelOf(control,state,ctx){
    const c=ctx||{};
    const lower=LABEL[control].charAt(0).toLowerCase()+LABEL[control].slice(1);
    if(control===CONTROL.SCREENSHOT){
      if(state===STATE.BUSY)return 'Capture d’écran en cours…';
      if(state===STATE.UNKNOWN)return 'Capture d’écran : état inconnu, Jarvis injoignable';
      if(state===STATE.DONE)return 'Capture d’écran enregistrée — en prendre une autre';
      if(state===STATE.ERROR)return `Prendre une capture d’écran — dernier essai : ${c.fail&&c.fail.text||'échec'}`;
      return 'Prendre une capture d’écran';
    }
    switch(state){
      case STATE.STARTING:return c.action
        ?`${LABEL[control]} : démarrage… — arrêter`
        :`${LABEL[control]} : démarrage…`;
      case STATE.ACTIVE:return `Arrêter l’${lower}`;
      case STATE.STOPPING:return `${LABEL[control]} : arrêt en cours…`;
      case STATE.STUCK:return `${LABEL[control]} : arrêt bloqué (${c.stuck&&c.stuck.error_code||'inconnu'}) — réessayer l’arrêt`;
      case STATE.ERROR:return c.fail&&c.fail.verb
        ?`Démarrer l’${lower} — précédent ${c.fail.verb} : ${c.fail.text||'cause inconnue'}`
        :`Démarrer l’${lower} — dernier essai : ${c.fail&&c.fail.text||'échec'}`;
      case STATE.UNKNOWN:return c.action
        ?`${LABEL[control]} : état inconnu, Jarvis injoignable — tenter l’arrêt`
        :`${LABEL[control]} : état inconnu, Jarvis injoignable`;
      default:return `Démarrer l’${lower}`;
    }
  }

  /* ------------------------------------------------- le contrôleur

     Dépendances injectées : `fetch`, horloge, minuteries, journal, visibilité
     de l'onglet. Ce qu'il tient est de l'interaction, jamais de la vérité de
     capture : demandes en vol, derniers refus, captures connues ouvertes (pour
     pouvoir les arrêter quand le statut tombe), la note du dernier refus, le
     dernier résultat de capture d'écran. */
  function createCaptureController(deps){
    const fetchFn=deps.fetch,now=deps.now;
    const later=deps.setTimeout,unlater=deps.clearTimeout;
    const every=deps.setInterval,unevery=deps.clearInterval;
    const hidden=deps.hidden||(()=>false);
    const log=deps.log||function(){};
    const onPaint=deps.onPaint||function(){};

    let status=null,reachable=false,lastLoss=null;
    const pending={},failure={},known={},stops={};
    let shotAt=0,note=null,spoken='',spokenSeq=0,lastShot=null;
    let pollTimer=0,tickTimer=0,polling=null,stopped=false;
    /* `lostCount` : lectures ratées d'affilée (recul). `wroteAt` : fin de la
       dernière écriture (cadence rapide). */
    let lostCount=0,wroteAt=-Infinity;
    /* Les captures que **cette page** a demandé d'arrêter : leur fin n'est pas
       une interruption à signaler. */
    const stoppedHere=new Set();
    let openBefore=new Map();
    const subscribers=new Set();
    let view=compose(viewOf({}));

    /* ------------------------------------------------- réseau */

    function failureOf(code,message,status_){
      return Object.assign(new Error(message||code),{code,status:status_||null});
    }

    async function call(path,init,deadline){
      const controller=typeof AbortController==='function'?new AbortController():null;
      let expired=false;
      const ticket=later(()=>{expired=true;if(controller)controller.abort()},deadline);
      try{
        const response=await fetchFn(path,Object.assign({
          headers:{'Accept':'application/json','Content-Type':'application/json'},
          cache:'no-store',
        },init||{},controller?{signal:controller.signal}:{}));
        const text=await response.text();
        let body=null;
        try{body=text?JSON.parse(text):null}catch(_error){body=null/* corps non JSON : le statut HTTP parle */}
        if(!response.ok){
          const envelope=isObject(body)&&isObject(body.error)?body.error:null;
          const code=(envelope&&envelope.code)||(isObject(body)&&typeof body.code==='string'?body.code:null)
            ||`http_${response.status}`;
          throw failureOf(code,(envelope&&envelope.message)||(text||'').slice(0,240)||`HTTP ${response.status}`,
            response.status);
        }
        return body;
      }catch(error){
        if(expired)throw failureOf('client_timeout',`pas de réponse au bout de ${Math.round(deadline/1000)} s`);
        if(error&&error.code)throw error;
        throw failureOf('network',String((error&&error.message)||error));
      }finally{
        unlater(ticket);
      }
    }

    /* Un sondage à la fois ; un second appel attend le premier. */
    function poll(){
      if(polling)return polling;
      polling=(async()=>{
        try{
          const body=await call(ROUTES.status,{method:'GET'},TIMING.statusDeadlineMs);
          if(!isObject(body)||!Array.isArray(body.captures))
            throw failureOf('invalid_status','statut de capture illisible');
          absorb(body);
          if(lastLoss)log('info','capture_rail.status_restored',{after:lastLoss.code,attempts:lostCount});
          else if(!status)log('info','capture_rail.status_received',{open:body.captures.length});
          status=body;reachable=true;lastLoss=null;lostCount=0;
        }catch(error){
          if(reachable||!lastLoss)
            log('warn','capture_rail.status_lost',{code:error.code||null,status:error.status||null,
              error:String(error.message||error)});
          reachable=false;lastLoss={code:error.code||'network'};lostCount+=1;
        }finally{
          polling=null;
          paint();
        }
        return reachable;
      })();
      return polling;
    }

    /* La lecture qui suit une écriture : jamais celle qui était déjà en vol
       (partie avant la fin de l'écriture, elle peut dire l'état d'avant). */
    async function fresh(){
      wroteAt=now();
      if(polling)await polling;
      const ok=await poll();
      schedule();
      return ok;
    }

    /* Ce qu'un statut frais apprend au-delà de lui-même : les captures
       ouvertes de chaque canal (pour les arrêter quand le statut tombe) et
       les fins **que personne ici n'a demandées** — une source perdue, un
       disque plein — qui ne doivent pas passer en silence. */
    function absorb(body){
      const openNow=new Map();
      for(const channel of CHANNELS){
        const rows=opensOf(body,channel);
        known[channel]=rows.map(row=>({capture_id:row.capture_id,device:row.device||DEFAULT_DEVICE}));
        for(const row of rows)openNow.set(row.capture_id,channel);
      }
      const recent=Array.isArray(body.recent)?body.recent:[];
      for(const [id,channel] of openBefore){
        if(openNow.has(id))continue;
        const ended=recent.find(row=>isObject(row)&&row.capture_id===id);
        if(stoppedHere.has(id)){stoppedHere.delete(id);continue}
        if(!ended)continue;
        /* Un démarrage refusé passe par une ligne ouverte (`starting` puis
           `stopping`, `stop_reason: start_failed`) : quand c'est cette page
           qui l'a demandé, la réponse du `POST` le dit déjà, mieux. */
        if(ended.stop_reason==='start_failed'&&(pending[channel]||failure[channel]))continue;
        if(BAD_ENDS.has(ended.state)){
          const verb=ended.stop_reason==='start_failed'?'non démarré':'interrompu';
          const code=ended.error_code||ended.stop_reason||null;
          /* `verb` : la fin vient d'ailleurs, le nom ne parlera pas d'un
             « dernier essai » que l'utilisateur n'a pas fait. */
          failure[channel]={code,text:refusalText(code,'',channel),verb};
          show(channel,'bad',noteText(channel,verb,code,''));
          log('warn','capture_rail.capture_interrupted',
            {channel,capture_id:id,state:ended.state,code,stop_reason:ended.stop_reason||null});
        }else log('info','capture_rail.capture_ended_elsewhere',
          {channel,capture_id:id,state:ended.state,stop_reason:ended.stop_reason||null});
      }
      openBefore=openNow;
    }

    /* ------------------------------------------------- actions */

    /* L'activation simple d'une commande (un secteur de la roue) : démarrer
       un canal au repos sur sa cible par défaut, arrêter sa capture la plus
       récente, prendre une capture d'écran. */
    function act(id){
      const control=view.controls[id];
      if(!control)return Promise.resolve(null);
      /* Statut inconnu : la demande dit « je veux agir », on relit tout de
         suite plutôt que d'attendre le pas du recul (jusqu'à 15 s). Aucun
         démarrage pour autant : seul l'arrêt d'une capture connue part. */
      const reading=view.reachable?null:wake();
      if(!control.action)return reading||Promise.resolve(null);
      if(control.action==='stop')return stop(id,control.captureId);
      /* Un arrêt passe pendant **notre** démarrage en vol ; toute autre
         demande en vol bloque. */
      if(pending[id])return Promise.resolve(null);
      if(control.action==='shot')return shoot(null);
      return start(id,null);
    }

    /* Une demande ne libère que **sa** place. */
    function release(channel,mine){
      if(pending[channel]===mine)pending[channel]=null;
    }

    async function start(channel,device){
      const mine={kind:'start',since:now(),device:device||DEFAULT_DEVICE};
      pending[channel]=mine;
      failure[channel]=null;
      if(note&&note.control===channel)dismiss({quiet:true});
      paint();
      schedule();  // une écriture en vol : cadence d'une seconde dès maintenant
      log('info','capture_rail.start_requested',{channel,device:mine.device});
      /* Sans appareil choisi, rien de plus que le canal (= `default`, comme
         avant la Slice 04) ; un appareil choisi part dans `options.device`. */
      const body=device&&device!==DEFAULT_DEVICE?{channel,options:{device}}:{channel};
      try{
        const answer=await call(ROUTES.start,{method:'POST',body:JSON.stringify(body)},TIMING.writeDeadlineMs);
        const capture=isObject(answer)&&isObject(answer.capture)?answer.capture:{};
        log('info','capture_rail.started',{channel,device:mine.device,capture_id:capture.capture_id||null,
          state:capture.state||null});
        say(`${LABEL[channel]} démarré.`);
        return capture.capture_id||null;
      }catch(error){
        if(mine.superseded){
          /* L'utilisateur a arrêté ce démarrage en vol : sa fin en échec est
             la réponse attendue, pas un refus à afficher. */
          log('info','capture_rail.start_superseded',{channel,code:error.code});
        }else if(error.code==='already_active'){
          /* Pas une panne : Core tient déjà ce canal (cet appareil), la
             relecture va le montrer ; l'attente reste jusque-là. */
          show(channel,'warn',noteText(channel,'déjà actif',error.code,error.message));
          log('info','capture_rail.start_already_active',{channel,device:mine.device,code:error.code});
        }else{
          /* L'attente tombe **avant** la note : jamais « démarrage… » à côté
             de « non démarré ». */
          release(channel,mine);
          failure[channel]={code:error.code,text:refusalText(error.code,error.message,channel)};
          show(channel,'bad',noteText(channel,'non démarré',error.code,error.message));
          log(error.code==='client_timeout'||error.code==='core_timeout'?'warn':'error',
            'capture_rail.start_failed',{channel,device:mine.device,code:error.code,status:error.status,
              error:error.message});
        }
        return null;
      }finally{
        /* Un démarrage accepté reste « démarrage… » jusqu'à la relecture qui
           le montre actif : pas de « repos » périmé entre les deux. */
        await fresh();
        release(channel,mine);
        paint();
      }
    }

    async function stop(channel,captureId){
      if(!captureId||stops[captureId])return null;
      const mine={kind:'stop',since:now(),captureId,channel};
      stops[captureId]=mine;
      /* Un arrêt pendant notre démarrage en vol : la fin en échec de ce
         démarrage sera la réponse attendue, pas un refus. */
      if(pending[channel]&&pending[channel].kind==='start')pending[channel].superseded=true;
      stoppedHere.add(captureId);
      paint();
      schedule();
      log('info','capture_rail.stop_requested',{channel,capture_id:captureId});
      try{
        const body=await call(ROUTES.stop(captureId),{method:'POST',body:'{}'},TIMING.writeDeadlineMs);
        const capture=isObject(body)&&isObject(body.capture)?body.capture:{};
        if(BAD_ENDS.has(capture.state)){
          show(channel,'warn',noteText(channel,'arrêté mais incomplet',capture.error_code,''));
          log('warn','capture_rail.stopped_incomplete',
            {channel,capture_id:captureId,state:capture.state,code:capture.error_code||null});
        }else{
          if(note&&note.control===channel)dismiss({quiet:true});
          log('info','capture_rail.stopped',{channel,capture_id:captureId,state:capture.state||null});
        }
        failure[channel]=null;
        /* Arrêtée : ce n'est plus une capture « connue ouverte ». Sans cela, un
           statut toujours perdu reproposerait d'arrêter ce qui l'est déjà. */
        known[channel]=knownOf(known,channel).filter(row=>row.capture_id!==captureId);
        say(`${LABEL[channel]} arrêté.`);
        return capture.state||null;
      }catch(error){
        stoppedHere.delete(captureId);
        /* L'attente tombe **avant** la note : jamais « arrêt… » à côté de
           « non arrêté ». */
        if(stops[captureId]===mine)delete stops[captureId];
        show(channel,'bad',noteText(channel,'non arrêté',error.code,error.message));
        log('error','capture_rail.stop_failed',
          {channel,capture_id:captureId,code:error.code,status:error.status,error:error.message});
        return null;
      }finally{
        /* « Arrêt… » jusqu'à la relecture : pas d'« actif » périmé. */
        await fresh();
        if(stops[captureId]===mine)delete stops[captureId];
        paint();
      }
    }

    async function shoot(device){
      const id=CONTROL.SCREENSHOT;
      const mine={kind:'shot',since:now(),device:device||DEFAULT_DEVICE};
      pending[id]=mine;
      failure[id]=null;
      if(note&&note.control===id)dismiss({quiet:true});
      paint();
      log('info','capture_rail.screenshot_requested',{device:mine.device});
      const body=device&&device!==DEFAULT_DEVICE?{options:{device}}:{};
      try{
        const answer=await call(ROUTES.screenshot,{method:'POST',body:JSON.stringify(body)},TIMING.writeDeadlineMs);
        const capture=isObject(answer)&&isObject(answer.capture)?answer.capture:{};
        const artifact=isObject(answer)&&isObject(answer.artifact)?answer.artifact:null;
        shotAt=now();
        /* Le résultat entier, pour l'aperçu (Slice 05) : jamais deviné. */
        lastShot=Object.freeze({capture,artifact,device:mine.device,at:shotAt});
        log('info','capture_rail.screenshot_taken',
          {device:mine.device,capture_id:capture.capture_id||null,artifact_id:artifact&&artifact.artifact_id||null});
        say('Capture d’écran enregistrée.');
        /* La confirmation s'efface d'elle-même : on repeint juste après. */
        later(()=>paint(),TIMING.doneMs+50);
        return {capture,artifact};
      }catch(error){
        pending[id]=null;
        failure[id]={code:error.code,text:refusalText(error.code,error.message,id)};
        show(id,'bad',noteText(id,'échouée',error.code,error.message));
        log('error','capture_rail.screenshot_failed',{device:mine.device,code:error.code,status:error.status,
          error:error.message});
        return null;
      }finally{
        if(pending[id]===mine)pending[id]=null;
        paint();
      }
    }

    /* ------------------------------------------------- l'API publique */

    /* Démarrer un canal sur un appareil choisi (sous-arc des cibles). Refusé
       sans bruit réseau quand Core ne dit rien de sûr : statut inconnu (on
       relit), demande déjà en vol, canal inconnu. */
    function startChannel(channel,opts){
      if(!CHANNELS.includes(channel)){
        log('error','capture_rail.start_refused',{channel,reason:'unknown_channel'});
        return Promise.resolve(null);
      }
      if(!view.reachable){
        log('warn','capture_rail.start_refused',{channel,reason:'status_unknown'});
        show(channel,'bad',noteText(channel,'non démarré','status_unknown',''));
        return wake().then(()=>null);
      }
      if(pending[channel]){
        log('info','capture_rail.start_refused',{channel,reason:'busy'});
        return Promise.resolve(null);
      }
      const device=opts&&typeof opts.device==='string'&&opts.device?opts.device:null;
      return start(channel,device);
    }

    function screenshot(opts){
      if(pending.screenshot)return Promise.resolve(null);
      if(!view.reachable){
        log('warn','capture_rail.screenshot_refused',{reason:'status_unknown'});
        show(CONTROL.SCREENSHOT,'bad',noteText(CONTROL.SCREENSHOT,'non prise','status_unknown',''));
        return wake().then(()=>null);
      }
      const device=opts&&typeof opts.device==='string'&&opts.device?opts.device:null;
      return shoot(device);
    }

    /* Le canal d'une capture ouverte, selon Core, ou connue (statut perdu). */
    function channelOf(captureId){
      if(reachable&&status){
        const row=(status.captures||[]).find(r=>isObject(r)&&r.capture_id===captureId&&r.mode==='continuous');
        return row&&CHANNELS.includes(row.channel)?row.channel:null;
      }
      return CHANNELS.find(ch=>knownOf(known,ch).some(r=>r.capture_id===captureId))||null;
    }

    function stopCapture(captureId){
      const channel=channelOf(captureId);
      if(!channel){
        log('warn','capture_rail.stop_unknown_capture',{capture_id:captureId||null,reachable});
        return (view.reachable?Promise.resolve(null):wake().then(()=>null));
      }
      return stop(channel,captureId);
    }

    /* Les cibles exécutables (D6). Rejette avec le code réel : la vue le dit. */
    async function targets(){
      try{
        const body=await call(ROUTES.targets,{method:'GET'},TIMING.statusDeadlineMs);
        if(!isObject(body))throw failureOf('invalid_targets','liste des cibles illisible');
        log('info','capture_rail.targets_read',{screen:((body.screen||{}).devices||[]).length,
          audio:((body.audio||{}).devices||[]).length});
        return body;
      }catch(error){
        log('warn','capture_rail.targets_failed',{code:error.code||null,status:error.status||null,
          error:String(error.message||error)});
        throw error;
      }
    }

    /* ------------------------------------------------- note et annonce */

    function show(control,tone,text){
      note={control,tone,text};
      say(text);
      paint();
    }
    function dismiss(opts){
      const o=opts||{};
      if(!note)return;
      const control=note.control;
      note=null;
      /* Fermer le message, c'est en avoir pris connaissance : la marque
         d'erreur part avec lui (le statut, lui, ne bouge pas). */
      if(!o.quiet&&failure[control])failure[control]=null;
      paint();
    }
    function say(line){
      if(!line||line===spoken)return;
      spoken=line;spokenSeq+=1;
    }

    /* ------------------------------------------------- publication */

    function compose(base){
      /* `settled` : une première lecture a abouti ou échoué ; avant, rien
         n'est encore su (ni repos, ni « état inconnu »). */
      return Object.freeze({...base,note:note?Object.freeze({...note}):null,shot:lastShot,
        settled:status!==null||lastLoss!==null,announce:Object.freeze({text:spoken,seq:spokenSeq})});
    }

    function paint(){
      view=compose(viewOf({status,reachable,pending,stops,failure,known,shotAt,now:now()}));
      onPaint(view);
      for(const fn of subscribers){
        try{fn(view)}
        catch(error){log('error','capture_rail.subscriber_failed',{error:String((error&&error.message)||error)})}
      }
      return view;
    }

    function subscribe(fn){
      if(typeof fn!=='function')throw Object.assign(new TypeError('JarvisCaptureRail.subscribe : fonction attendue'),
        {code:'capture_rail_bad_subscriber'});
      subscribers.add(fn);
      try{fn(view)}
      catch(error){log('error','capture_rail.subscriber_failed',{error:String((error&&error.message)||error)})}
      return ()=>{subscribers.delete(fn)};
    }

    /* ------------------------------------------------- cycle */

    function writing(){
      return ORDER.some(id=>pending[id])||Object.keys(stops).length>0;
    }

    /* Le délai jusqu'au prochain sondage (décision PM, voir l'en-tête). */
    function delay(){
      const lost=lostCount>0
        ?Math.min(TIMING.lostBackoffMaxMs,TIMING.fastPollMs*2**Math.min(lostCount-1,10)):0;
      if(hidden())return Math.max(TIMING.hiddenPollMs,lost);
      if(lost)return lost;
      const busy=view.recording>0||writing()||now()-wroteAt<TIMING.afterWriteMs;
      return busy?TIMING.fastPollMs:TIMING.idlePollMs;
    }

    /* **Une seule** minuterie de sondage, quoi qu'il arrive : chaque appel
       remplace la précédente (un réveil pendant une lecture en vol, une
       écriture, la boucle elle-même appellent tous `schedule`). */
    function schedule(){
      if(pollTimer){unlater(pollTimer);pollTimer=0}
      if(stopped)return;
      pollTimer=later(async()=>{
        pollTimer=0;
        await poll();
        schedule();
      },delay());
    }

    function begin(){
      stopped=false;
      paint();
      /* La cadence se choisit sur la première réponse (ouvert, repos, perdu). */
      poll().then(()=>schedule());
      /* Le chronomètre avance entre deux sondages, sans en déclencher. */
      tickTimer=every(()=>{
        const live=ORDER.some(id=>view.controls[id].timer)
          ||CHANNELS.some(ch=>view.controls[ch].captures.some(c=>c.timer));
        if(live||view.controls.screenshot.state===STATE.DONE)paint();
      },TIMING.tickMs);
    }
    function destroy(){
      stopped=true;
      if(pollTimer){unlater(pollTimer);pollTimer=0}
      if(tickTimer){unevery(tickTimer);tickTimer=0}
    }
    /* L'onglet revient au premier plan, ou une demande tombe pendant un
       statut inconnu : on relit tout de suite. */
    function wake(){
      if(stopped)return Promise.resolve(false);
      if(pollTimer){unlater(pollTimer);pollTimer=0}
      return poll().then(ok=>{schedule();return ok});
    }

    return {
      start:begin,destroy,wake,poll,act,dismiss,paint,subscribe,
      startChannel,screenshot,stop:stopCapture,targets,
      view:()=>view,note:()=>note,lastShot:()=>lastShot,nextDelay:delay,
    };
  }

  const CAPTURE_RAIL=Object.freeze({
    CONTROL,ORDER,CHANNELS,STATE,ROUTES,RECENT_ROWS,TIMING,LABEL,TEXT,FFMPEG_HINT,DEFAULT_DEVICE,
    refusalText,noteText,clock,elapsedOf,opensOf,openOf,viewOf,labelOf,createCaptureController,
  });
  root.JarvisCaptureRailModule=CAPTURE_RAIL;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=CAPTURE_RAIL;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- bloc navigateur */

  function installCaptureController(){
    if(typeof window.fetch!=='function')
      throw Object.assign(new Error('JarvisCaptureRail : fetch indisponible'),{code:'capture_rail_fetch_missing'});
    const log=(level,event,data)=>{
      const line=`[capture] ${event} ${JSON.stringify(data)}`;
      if(level==='error')console.error(line);
      else if(level==='warn')console.warn(line);
      else console.info(line);
    };
    const controller=createCaptureController({
      fetch:(url,init)=>window.fetch(url,init),
      now:()=>Date.now(),
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),clearTimeout:id=>window.clearTimeout(id),
      setInterval:(fn,ms)=>window.setInterval(fn,ms),clearInterval:id=>window.clearInterval(id),
      hidden:()=>document.hidden===true,
      log,
    });
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)controller.wake()});
    window.JarvisCaptureRail=Object.freeze({
      subscribe:controller.subscribe,start:controller.startChannel,screenshot:controller.screenshot,
      stop:controller.stop,targets:controller.targets,act:controller.act,
      view:controller.view,note:controller.note,lastShot:controller.lastShot,dismiss:controller.dismiss,
      poll:controller.poll,wake:controller.wake,
    });
    controller.start();
    log('info','capture_rail.installed',{views:'control_center_capture_wheel.js'});
  }

  try{installCaptureController()}
  catch(error){
    console.error('[capture] capture_rail.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
