/* Rail de capture du bord gauche — capture d'écran, enregistrement audio,
   enregistrement d'écran.

   Slice 10 de `jarvis-session-context-recording-runtime`. Décisions D14 (le
   rail flottant de gauche est la maison des commandes d'enregistrement) et D15
   (ce ne sont **pas** des outils Bare Hands) ; décision D-UI de la Slice 00 :
   un hôte frère `#captureRail`, posé sous la palette dans le même langage
   visuel, avec son propre module, sans `data-bh-tool` et hors de
   `#barehandsPaletteStrip`. Contrat : `docs/capture.md` › *Interface (Slice 10)*.

   **Deux modèles séparés, par construction.** Les outils Bare Hands sont un
   choix exclusif tenu par les réglages ; les captures sont des canaux
   indépendants tenus par Core. Ce module ne lit ni `BH.TOOL` ni
   `describeTools()` et n'écrit rien dans la palette : il ne fait que se poser
   à côté d'elle, en mesurant où elle est.

   **Aucun état local de capture.** Ce qui est affiché comme « en cours » vient
   **toujours** du dernier `GET /api/captures/status` réussi (relais du
   Control Center vers Core, `capture_relay.py`) ; jamais d'un clic. Un clic
   ouvre une attente visible (« démarrage… », compteur de secondes), part en
   `POST`, puis relit le statut. Un démarrage refusé n'a donc rien à défaire :
   le bouton n'a jamais été peint actif, et le refus s'écrit en clair à côté
   de lui. Le chronomètre d'un enregistrement part de `activated_at` (à défaut
   `created_at`) rendu par Core, pas de l'heure du clic : un second onglet, un
   rechargement ou un démarrage par le cerveau affichent la même durée.

   **Statut perdu = état inconnu.** Si le sondage tombe (Control Center ou
   Core injoignable, délai dépassé), les trois commandes passent à « état
   inconnu » : aucune n'est peinte active, aucun démarrage n'est proposé. Un
   enregistrement que l'on savait ouvert juste avant peut encore être
   **arrêté** (vie privée d'abord) : le bouton le propose sous ce nom.

   **Pourquoi un sondage et pas un flux.** La page n'a aucun flux poussé
   générique (la seule diffusion est la couture de cycle de vie propre à Bare
   Hands) et `/api/status` ne porte pas les captures. Le motif du sondage avec
   relecture immédiate après chaque écriture est celui du contrôle de mode
   d'interaction. Cadence (décision PM de la reprise QA) : 1 s tant qu'une
   capture est ouverte, qu'une écriture est en vol, et 10 s après une
   écriture ; 3 s au repos ; 20 s onglet caché ; statut perdu → recul
   exponentiel jusqu'à 15 s (chaque lecture ratée laisse une ligne au journal
   du relais), retour à la cadence normale au premier succès. Chaque sondage a
   une échéance : passé `statusDeadlineMs`, le statut est réputé perdu.

   **Relecture après écriture.** Une lecture partie **avant** la fin d'une
   écriture peut revenir après elle avec l'état d'avant : la page l'attend,
   puis en lance une neuve (`fresh`), et la demande reste peinte en attente
   jusqu'au retour de celle-ci. Jamais un « repos » périmé après un
   démarrage, ni un « actif » périmé après un arrêt.

   Insertion : `control_center.py` / `control_center.html`. Le module refuse de
   s'installer sous un nom cherchable si son emplacement manque, et ce refus
   est **rattrapé ici** : la page sert tous ses modules dans une seule balise
   `<script>`. */
(function(root){
  'use strict';

  const DOM=Object.freeze({
    hostId:'captureRail',
    styleId:'captureRailStyle',
    stripId:'captureRailStrip',
    captionId:'captureRailCaption',
    noteId:'captureRailNote',
    announceId:'captureRailAnnounce',
    /* + id de la commande : la durée lue par `aria-describedby`. */
    detailIdPrefix:'captureRailDetail-',
    /* La commande que porte un bouton. **Pas** `data-bh-tool` : D15. */
    controlAttribute:'data-capture-control',
    /* L'état peint, écrit par une seule fonction (`paint`). */
    stateAttribute:'data-capture-state',
    /* Où le placement a posé le rail : `below`, `beside`, `beside-up`,
       `beside-low`, `alone`. */
    slotAttribute:'data-capture-slot',
  });

  const CONTROL=Object.freeze({SCREENSHOT:'screenshot',AUDIO:'audio',SCREEN:'screen'});
  /* L'ordre du rail : l'action ponctuelle d'abord, puis les deux canaux. */
  const ORDER=Object.freeze([CONTROL.SCREENSHOT,CONTROL.AUDIO,CONTROL.SCREEN]);
  const CHANNELS=Object.freeze([CONTROL.AUDIO,CONTROL.SCREEN]);

  /* Les états peints. `busy`/`done` n'existent que pour la capture d'écran,
     `starting`/`active`/`stopping`/`stuck` que pour les deux canaux. */
  const STATE=Object.freeze({
    IDLE:'idle',STARTING:'starting',ACTIVE:'active',STOPPING:'stopping',STUCK:'stuck',
    ERROR:'error',UNKNOWN:'unknown',BUSY:'busy',DONE:'done',
  });
  const OPEN_STATES=new Set(['starting','active','stopping']);
  const BAD_ENDS=new Set(['partial','failed']);

  /* Le rail ne lit `recent` que pour voir finir une capture qu'il voyait
     ouverte : trois lignes suffisent entre deux sondages d'une seconde, et
     allègent chaque réponse (Core borne `recent` à 0..20, défaut 5). */
  const RECENT_ROWS=3;
  const ROUTES=Object.freeze({
    status:`/api/captures/status?recent=${RECENT_ROWS}`,
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

  /* La capture continue **ouverte** d'un canal, selon Core. La plus récente
     si (défaut) il y en avait deux. */
  function openOf(status,channel){
    const rows=isObject(status)&&Array.isArray(status.captures)?status.captures:[];
    let best=null;
    for(const row of rows){
      if(!isObject(row)||row.channel!==channel||row.mode!=='continuous'||!OPEN_STATES.has(row.state))continue;
      if(!best||String(row.created_at||'')>String(best.created_at||''))best=row;
    }
    return best;
  }
  function stuckOf(status,captureId){
    const rows=isObject(status)&&Array.isArray(status.stuck)?status.stuck:[];
    return rows.find(row=>isObject(row)&&row.capture_id===captureId)||null;
  }

  /* L'état peint de chaque commande, depuis :
     - `status` : le dernier statut de Core, `reachable` : le sondage tient ;
     - `pending` : la demande en vol par commande (`{kind, since, captureId}`) ;
     - `failure` : le dernier refus par commande (`{code, text}`) ;
     - `known` : la dernière capture ouverte connue par canal (statut perdu) ;
     - `shotAt` : l'heure de la dernière capture d'écran réussie ; `now`.
     **Aucune** de ces entrées ne peut peindre un canal actif : seul `status`
     le peut, et seulement quand `reachable` est vrai. */
  function viewOf(input){
    const i=isObject(input)?input:{};
    const now=Number(i.now)||0;
    const reachable=!!i.reachable&&isObject(i.status);
    const status=reachable?i.status:null;
    const pending=isObject(i.pending)?i.pending:{};
    const failure=isObject(i.failure)?i.failure:{};
    const known=isObject(i.known)?i.known:{};
    const controls={};
    let recording=0,troubled=0;

    for(const channel of CHANNELS){
      const pend=isObject(pending[channel])?pending[channel]:null;
      const open=status?openOf(status,channel):null;
      const fail=isObject(failure[channel])?failure[channel]:null;
      let state,action=null,captureId=null,since=null,until=null,stuck=null;
      if(!reachable){
        if(pend)state=pend.kind==='stop'?STATE.STOPPING:STATE.STARTING;
        else{
          state=STATE.UNKNOWN;
          const last=isObject(known[channel])?known[channel]:null;
          if(last&&last.capture_id){captureId=last.capture_id;action='stop'}
        }
      }else if(open){
        captureId=open.capture_id;
        since=open.activated_at||open.created_at;
        stuck=stuckOf(status,captureId);
        if(stuck){state=STATE.STUCK;action='stop'}
        /* Notre démarrage est en vol et Core n'a pas encore activé la ligne :
           c'est toujours un démarrage, même si Core la referme déjà (refus de
           la source : `starting` → `stopping` → `failed`). */
        else if(pend&&pend.kind==='start'&&open.state!=='active')state=STATE.STARTING;
        else if(pend&&pend.kind==='stop'||open.state==='stopping'){
          state=STATE.STOPPING;until=open.stop_requested_at||null;
        }else if(open.state==='starting'){state=STATE.STARTING;action='stop'}
        else{state=STATE.ACTIVE;action='stop'}
      }else if(pend&&pend.kind==='start')state=STATE.STARTING;
      else if(fail){state=STATE.ERROR;action='start'}
      else{state=STATE.IDLE;action='start'}

      const opened=!!(reachable&&open);
      if(opened)recording+=1;
      if(state===STATE.STUCK||state===STATE.ERROR)troubled+=1;
      const waited=pend?Math.max(0,Math.floor((now-(Number(pend.since)||now))/1000)):null;
      const seconds=opened&&state!==STATE.STARTING?elapsedOf(since,until,now):null;
      controls[channel]=Object.freeze({
        id:channel,kind:'channel',state,action,captureId,
        /* `aria-pressed` = Core dit qu'une capture est ouverte. Rien d'autre. */
        pressed:opened,
        /* La pastille d'arrêt posée sur l'icône du canal : ouvert selon Core,
           sans marque d'erreur ou d'inconnu qui occuperait le même coin. */
        stopMark:opened&&(state===STATE.ACTIVE||state===STATE.STARTING||state===STATE.STOPPING),
        seconds,waited,
        timer:seconds!==null?clock(seconds):(waited!==null?`${waited} s`:''),
        /* La durée, pour la description accessible : hors du nom, qui ne doit
           pas changer chaque seconde (un lecteur d'écran le réannoncerait). */
        detail:seconds!==null
          ?(state===STATE.STOPPING?`durée ${clock(seconds)}`:`en cours depuis ${clock(seconds)}`)
          :(waited!==null?`attente depuis ${waited} s`:''),
        code:stuck?stuck.error_code:(fail&&state===STATE.ERROR?fail.code:null),
        label:labelOf(channel,state,{stuck,fail,action}),
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
      const waited=pend?Math.max(0,Math.floor((now-(Number(pend.since)||now))/1000)):null;
      controls.screenshot=Object.freeze({
        id:CONTROL.SCREENSHOT,kind:'shot',state,action,captureId:null,
        /* Une action ponctuelle n'a pas d'état enfoncé : pas d'`aria-pressed`. */
        pressed:null,stopMark:false,seconds:null,waited,timer:waited!==null?`${waited} s`:'',
        detail:waited!==null?`attente depuis ${waited} s`:'',
        code:fail&&state===STATE.ERROR?fail.code:null,
        label:labelOf(CONTROL.SCREENSHOT,state,{fail}),
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

  /* Le nom accessible et l'infobulle, une seule phrase pour les deux. Elle ne
     porte **aucun** compteur : la durée vit dans `detail` (description). Une
     erreur dit si elle vient d'un essai de cette page (`dernier essai`) ou
     d'une fin que personne ici n'a demandée (`précédent interrompu`). */
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
      case STATE.STARTING:return `${LABEL[control]} : démarrage…`;
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

  /* ------------------------------------------------- le placement (pur)

     Le rail se pose **sous** la colonne Bare Hands (contrôle + palette), dans
     sa largeur, séparé par un filet : c'est la place que D14 et §10 de
     l'architecture lui donnent. Quand cette place sort de l'écran ou touche
     une autre commande (le bouton de mode du bas-gauche, l'indication vocale,
     les pastilles…), il passe **à côté** de la colonne, aligné sur son haut,
     puis remonté au-dessus de la commande qu'il toucherait, puis aligné sur
     son bas. Bare Hands absent (module non monté) : il prend le haut
     de la colonne, la place que la main occuperait.

     La hauteur de la palette dépend du nombre d'outils installés, et sous
     700 px la colonne est centrée verticalement : aucune règle CSS ne peut
     calculer ce dégagement, d'où la mesure. `m` est en pixels de l'emplacement
     parent : `{vw, vh, rail:{w,h}, column:{left,top,right,bottom}|null,
     base:{left,top}, obstacles:[{left,top,right,bottom}]}`. */
  const RAIL_GEO=Object.freeze({gap:10,margin:8});

  function slotOf(m){
    const rail=m.rail||{w:64,h:0},obstacles=Array.isArray(m.obstacles)?m.obstacles:[];
    const candidates=[];
    if(m.column){
      const left=m.column.right;
      candidates.push({mode:'below',left:m.column.left,top:m.column.bottom+RAIL_GEO.gap});
      candidates.push({mode:'beside',left,top:m.column.top});
      /* À côté, **remonté** juste au-dessus de la première commande qu'il
         toucherait dessous (320 × 568 : le bouton de mode, levé par
         l'indicateur de scène, mordait de 4 px le bas du rail). */
      let ceiling=Infinity;
      for(const o of obstacles){
        const across=Math.min(left+rail.w,o.right)-Math.max(left,o.left);
        if(across>0&&o.top>m.column.top&&o.top<m.column.top+rail.h)ceiling=Math.min(ceiling,o.top);
      }
      if(Number.isFinite(ceiling))candidates.push({mode:'beside-up',left,top:ceiling-RAIL_GEO.gap-rail.h});
      candidates.push({mode:'beside-low',left,top:m.column.bottom-rail.h});
    }else candidates.push({mode:'alone',left:m.base.left,top:m.base.top});
    let best=null;
    for(const c of candidates){
      const box={left:c.left,top:c.top,right:c.left+rail.w,bottom:c.top+rail.h};
      const overflow=Math.max(0,box.bottom-(m.vh-RAIL_GEO.margin))+Math.max(0,box.right-(m.vw-RAIL_GEO.margin))
        +Math.max(0,RAIL_GEO.margin-box.top);
      let hits=0;
      for(const o of obstacles){
        const w=Math.min(box.right,o.right)-Math.max(box.left,o.left);
        const h=Math.min(box.bottom,o.bottom)-Math.max(box.top,o.top);
        if(w>0&&h>0)hits+=w*h;
      }
      const scored={mode:c.mode,left:Math.round(c.left),top:Math.round(c.top),fits:!overflow&&!hits,
        score:overflow*1000+hits};
      if(scored.fits)return Object.freeze(scored);
      if(!best||scored.score<best.score)best=scored;
    }
    return Object.freeze(best);
  }

  /* ------------------------------------------------- les icônes

     Le vocabulaire de la palette Bare Hands : grille de 24, trait de 1.5,
     bouts ronds, points pleins. Le dessin d'un canal **ne change pas** quand
     il est ouvert : micro et écran restent reconnaissables côte à côte (deux
     carrés d'arrêt identiques ne disaient plus lequel était lequel). Ce que
     fait le clic s'écrit par une **pastille d'arrêt** (`.cr-stop`, carré
     plein sur fond ambre, 18 px) posée au coin de l'icône. La capture
     d'écran est un **appareil photo** — des équerres de visée se lisaient
     comme l'outil `select` de Bare Hands juste au-dessus — et une capture
     réussie montre une **coche**. */
  const ART=Object.freeze({
    screenshot:Object.freeze({paths:Object.freeze([
      'M4.2 8.6a1.6 1.6 0 0 1 1.6-1.6h2.4l1.5-2.2h4.6l1.5 2.2h2.4a1.6 1.6 0 0 1 1.6 1.6v8.8'
        +'a1.6 1.6 0 0 1-1.6 1.6H5.8a1.6 1.6 0 0 1-1.6-1.6z',
      'M12 9.4a3.4 3.4 0 1 1 0 6.8a3.4 3.4 0 1 1 0-6.8z']),dots:Object.freeze([[17.1,9.7,.85]])}),
    audio:Object.freeze({paths:Object.freeze([
      'M12 3.6a2.6 2.6 0 0 1 2.6 2.6v5a2.6 2.6 0 0 1-5.2 0v-5A2.6 2.6 0 0 1 12 3.6z',
      'M6.6 11.2a5.4 5.4 0 0 0 10.8 0','M12 16.6v3.6','M9.2 20.2h5.6']),dots:Object.freeze([])}),
    screen:Object.freeze({paths:Object.freeze([
      'M5 4.8h14a1.5 1.5 0 0 1 1.5 1.5v8.4a1.5 1.5 0 0 1-1.5 1.5H5a1.5 1.5 0 0 1-1.5-1.5V6.3A1.5 1.5 0 0 1 5 4.8z',
      'M12 16.2v3.4','M8.8 19.6h6.4']),dots:Object.freeze([[12,10.5,2.2]])}),
    done:Object.freeze({paths:Object.freeze(['M5.5 12.5l4.2 4.2 8.8-9.4']),dots:Object.freeze([])}),
  });
  const SVG_NS='http://www.w3.org/2000/svg';

  /* Quel dessin pour quel état : celui du canal, toujours ; la coche après
     une capture d'écran réussie. */
  function glyphOf(view){
    if(view.kind==='shot')return view.state===STATE.DONE?'done':'screenshot';
    return view.id;
  }

  function icon(doc,name,size){
    const art=ART[name];
    const svg=doc.createElementNS(SVG_NS,'svg');
    svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('class','cr-icon');
    svg.setAttribute('width',String(size));svg.setAttribute('height',String(size));
    svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
    svg.setAttribute('stroke-width','1.5');svg.setAttribute('stroke-linecap','round');
    svg.setAttribute('stroke-linejoin','round');svg.setAttribute('aria-hidden','true');
    svg.setAttribute('focusable','false');svg.setAttribute('data-cr-glyph',name);
    for(const d of art.paths){
      const path=doc.createElementNS(SVG_NS,'path');path.setAttribute('d',d);svg.appendChild(path);
    }
    for(const dot of art.dots){
      const mark=doc.createElementNS(SVG_NS,'circle');
      mark.setAttribute('cx',String(dot[0]));mark.setAttribute('cy',String(dot[1]));
      mark.setAttribute('r',String(dot[2]));mark.setAttribute('fill','currentColor');
      mark.setAttribute('stroke','none');svg.appendChild(mark);
    }
    return svg;
  }

  /* ------------------------------------------------- la feuille

     Même famille que la palette Bare Hands (`control_center_barehands_hud.js`) :
     bande de 44 px d'icônes en trait sur une gélule sombre floutée, rail de
     forme à gauche de l'actif, anneau de focus de 2 px à 3 px de décalage,
     resserrage à 38 px sous 700 px. Les couleurs passent par les jetons de la
     page avec repli, jamais un hexadécimal nu. Un canal ouvert est **ambre**
     (`--warn`, la couleur que la carte de diagnostic Bare Hands donne déjà à
     un enregistrement) : ni le bleu d'un outil choisi, ni le rouge d'une panne.

     Rang 30, comme la palette, et pour la même raison : rien dans ce rail ne
     doit passer au-dessus du sélecteur de mode (36) ni du contrôle (32). */
  const ACCENT='var(--bh-accent,var(--accent,#6ee7ff))';
  const MUTED='var(--cosmos-muted,var(--muted,#7190a0))';
  const DANGER='var(--cosmos-danger,var(--danger,#ff6577))';
  const WARN='var(--warn,#ffb85c)';
  const OK='var(--ok,#68e0a0)';
  const H='#'+DOM.hostId;
  const S=DOM.stateAttribute;

  const STYLE=`
${H}{position:absolute;z-index:30;top:76px;left:18px;width:64px;
  display:flex;flex-direction:column;align-items:center;gap:8px;
  font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;pointer-events:auto}
${H}:empty{display:none}
/* Le filet : ce rail est un **autre groupe** que les outils du dessus. */
${H} .cr-rule{display:block;width:26px;height:1px;border-radius:1px;
  background:color-mix(in srgb,${MUTED} 55%,transparent)}
/* Seul en tête de colonne, ou posé à côté d'elle : le blanc sépare déjà,
   un filet horizontal n'y séparerait rien. */
${H}[${DOM.slotAttribute}=alone] .cr-rule,${H}[${DOM.slotAttribute}^=beside] .cr-rule{display:none}
${H} .cr-tools{position:relative;display:flex;flex-direction:column;align-items:center;gap:6px;
  padding:6px 2px;border:1px solid var(--line,#183343);border-radius:13px;background:rgba(3,8,12,.62);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px)}
${H} [${S}]{--cr-ink:color-mix(in srgb,${ACCENT} 58%,transparent);--cr-line:transparent;
  --cr-face:transparent;--cr-glow:none;--cr-style:solid}
${H} [${S}=active],${H} [${S}=stopping]{--cr-ink:color-mix(in srgb,${WARN} 88%,#fff);
  --cr-line:color-mix(in srgb,${WARN} 62%,transparent);
  --cr-face:color-mix(in srgb,${WARN} 12%,rgba(3,8,12,.88));
  --cr-glow:0 0 0 1px color-mix(in srgb,${WARN} 22%,transparent),0 0 16px color-mix(in srgb,${WARN} 26%,transparent)}
${H} [${S}=starting],${H} [${S}=busy]{--cr-ink:color-mix(in srgb,${ACCENT} 84%,#fff);
  --cr-line:color-mix(in srgb,${ACCENT} 45%,transparent);--cr-face:rgba(3,8,12,.82)}
${H} [${S}=error],${H} [${S}=stuck]{--cr-ink:color-mix(in srgb,${DANGER} 90%,#fff);
  --cr-line:color-mix(in srgb,${DANGER} 58%,transparent);--cr-face:rgba(22,6,10,.86)}
${H} [${S}=done]{--cr-ink:${OK};--cr-line:color-mix(in srgb,${OK} 50%,transparent)}
/* Inconnu : gris **et** en tirets — la différence ne tient pas qu'à la teinte. */
${H} [${S}=unknown]{--cr-ink:color-mix(in srgb,${MUTED} 70%,transparent);
  --cr-line:color-mix(in srgb,${MUTED} 55%,transparent);--cr-style:dashed}
${H} .cr-btn{position:relative;width:44px;height:44px;display:grid;place-items:center;padding:0;
  border:1px var(--cr-style) var(--cr-line);border-radius:10px;background:var(--cr-face);
  color:var(--cr-ink);box-shadow:var(--cr-glow);font:inherit;cursor:pointer;
  transition:color .16s ease,border-color .16s ease,background .16s ease,box-shadow .22s ease,transform .12s ease}
${H} .cr-btn:hover:not([aria-disabled=true]){border-color:color-mix(in srgb,var(--cr-ink) 60%,transparent)}
${H} .cr-btn:active:not([aria-disabled=true]){transform:scale(.94)}
${H} .cr-btn:focus-visible{outline:2px solid ${ACCENT};outline-offset:3px}
${H} .cr-btn[aria-disabled=true]{cursor:not-allowed}
${H} .cr-btn[${S}=starting],${H} .cr-btn[${S}=stopping],${H} .cr-btn[${S}=busy]{cursor:progress}
${H} .cr-icon{display:block;color:inherit;transition:transform .16s ease}
/* Un chronomètre ou une attente s'écrit **dans** le bouton : l'icône monte. */
${H} .cr-btn[data-cr-timed=true] .cr-icon{transform:translateY(-6px) scale(.82)}
${H} .cr-time{position:absolute;left:0;right:0;bottom:4px;font-size:9px;line-height:1;letter-spacing:0;
  text-align:center;font-variant-numeric:tabular-nums;white-space:nowrap;color:inherit}
/* Le rail de forme de l'ouvert, comme l'outil actif de la palette. */
${H} .cr-btn[aria-pressed=true]::before{content:'';position:absolute;left:-5px;top:8px;bottom:8px;width:3px;
  border-radius:3px;background:currentColor;animation:crBreathe 2.4s ease-in-out infinite}
@keyframes crBreathe{0%,100%{opacity:.55}50%{opacity:1}}
/* La marque d'un problème : un signe, pas seulement une teinte. */
${H} .cr-badge{position:absolute;right:-5px;top:-5px;width:15px;height:15px;border-radius:50%;
  display:none;place-items:center;font-size:10px;font-weight:700;line-height:1;color:#05080b;
  background:${DANGER};pointer-events:none}
/* La pastille d'arrêt d'un canal ouvert : un carré plein sur fond ambre, au
   coin de l'icône du canal, qui reste, elle, reconnaissable. Le liseré sombre
   la détache du bord du bouton. Pendant l'arrêt, elle s'estompe : c'est fait. */
${H} .cr-stop{position:absolute;right:-6px;top:-6px;width:18px;height:18px;border-radius:6px;
  display:none;place-items:center;background:${WARN};box-shadow:0 0 0 2px rgba(3,8,12,.92);
  pointer-events:none;transition:opacity .16s ease}
${H} .cr-stop::after{content:'';width:8px;height:8px;border-radius:1.5px;background:#05080b}
${H} .cr-btn[data-cr-stop=true] .cr-stop{display:grid}
${H} .cr-btn[data-cr-stop=true][${S}=stopping] .cr-stop{opacity:.5}
${H} [${S}=error] .cr-badge,${H} [${S}=stuck] .cr-badge{display:grid}
${H} [${S}=unknown] .cr-badge{display:grid;background:color-mix(in srgb,${MUTED} 85%,#fff)}
/* RÈGLE ZÉRO : une attente se voit bouger, et dit depuis combien de temps. */
${H} .cr-wait{position:absolute;left:8px;right:8px;bottom:1px;height:2px;border-radius:2px;overflow:hidden;
  display:none;background:color-mix(in srgb,var(--cr-ink) 22%,transparent)}
${H} [${S}=starting] .cr-wait,${H} [${S}=stopping] .cr-wait,${H} [${S}=busy] .cr-wait{display:block}
${H} .cr-wait::after{content:'';position:absolute;top:0;bottom:0;left:0;width:42%;border-radius:2px;
  background:currentColor;animation:crSweep 1.25s ease-in-out infinite}
@keyframes crSweep{from{transform:translateX(-115%)}to{transform:translateX(255%)}}
${H} .cr-cap{width:max-content;max-width:64px;text-align:center;font-size:9px;letter-spacing:.14em;
  text-transform:uppercase;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  color:color-mix(in srgb,${ACCENT} 72%,transparent)}
${H}[data-cr-tone=rec] .cr-cap{color:${WARN}}
${H}[data-cr-tone=bad] .cr-cap{color:${DANGER}}
${H}[data-cr-tone=unknown] .cr-cap{color:${MUTED}}
/* La note : la phrase d'un refus, à droite de sa commande. */
${H} .cr-note{position:absolute;left:calc(100% + 8px);top:0;width:max-content;max-width:280px;
  padding:8px 30px 8px 10px;border:1px solid var(--line,#183343);border-radius:9px;
  background:var(--panel,rgba(6,12,18,.94));color:var(--text,#d8edf7);font-size:11px;line-height:1.45;
  box-shadow:0 10px 28px rgba(0,0,0,.45)}
${H} .cr-note[hidden]{display:none}
${H} .cr-note[data-cr-tone=bad]{border-color:color-mix(in srgb,${DANGER} 55%,transparent);background:rgba(35,7,12,.94)}
${H} .cr-note[data-cr-tone=warn]{border-color:color-mix(in srgb,${WARN} 55%,transparent);background:rgba(38,23,5,.94)}
${H} .cr-note-close{position:absolute;right:4px;top:4px;width:22px;height:22px;display:grid;place-items:center;
  padding:0;border:1px solid transparent;border-radius:6px;background:transparent;color:${MUTED};
  font:inherit;font-size:13px;line-height:1;cursor:pointer}
${H} .cr-note-close:hover{color:var(--text,#d8edf7);border-color:var(--line,#183343)}
${H} .cr-note-close:focus-visible{outline:2px solid ${ACCENT};outline-offset:1px}
${H} .cr-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}
@media(max-width:700px){
  ${H}{top:calc(50% - 41px);left:10px}
  ${H} .cr-tools{gap:5px;padding:5px}
  ${H} .cr-btn{width:38px;height:38px}
  ${H} .cr-btn[data-cr-timed=true] .cr-icon{transform:translateY(-5px) scale(.76)}
  ${H} .cr-time{bottom:3px;font-size:8.5px}
  ${H} .cr-stop{width:16px;height:16px;border-radius:5px;right:-5px;top:-5px}
  ${H} .cr-stop::after{width:7px;height:7px}
}
@media(prefers-reduced-motion:reduce){
  /* Le mouvement s'arrête, pas l'information : le chronomètre et le compteur
     d'attente continuent de monter en chiffres, la barre reste posée. */
  ${H} .cr-btn,${H} .cr-icon,${H} .cr-stop{transition:none}
  ${H} .cr-btn[aria-pressed=true]::before{animation:none;opacity:1}
  ${H} .cr-wait::after{animation:none;width:100%;opacity:.6}
}
@media(forced-colors:active){
  ${H} .cr-tools{border-color:CanvasText}
  ${H} .cr-btn{border:1px var(--cr-style) ButtonText;color:ButtonText;background:ButtonFace;box-shadow:none}
  ${H} .cr-btn[aria-pressed=true]{border:2px solid Highlight}
  ${H} .cr-btn[aria-pressed=true]::before{background:Highlight}
  ${H} .cr-badge{background:CanvasText;color:Canvas;forced-color-adjust:none}
  ${H} .cr-stop{background:Highlight;box-shadow:0 0 0 2px Canvas;forced-color-adjust:none}
  ${H} .cr-stop::after{background:HighlightText;forced-color-adjust:none}
  ${H} .cr-rule{background:CanvasText}
}`;

  function installStyle(doc){
    if(doc.getElementById(DOM.styleId))return false;
    const style=doc.createElement('style');
    style.id=DOM.styleId;style.textContent=STYLE;
    doc.head.appendChild(style);
    return true;
  }

  /* ------------------------------------------------- le contrôle DOM

     Dépendances injectées : document, emplacement, `fetch`, horloge,
     minuteries, journal, visibilité de l'onglet. Ce que ce contrôle tient est
     de l'affichage : demandes en vol, derniers refus, dernière capture ouverte
     connue (pour pouvoir l'arrêter quand le statut tombe), curseur clavier. */
  function createCaptureRail(deps){
    const doc=deps.document,host=deps.host;
    const fetchFn=deps.fetch,now=deps.now;
    const later=deps.setTimeout,unlater=deps.clearTimeout;
    const every=deps.setInterval,unevery=deps.clearInterval;
    const hidden=deps.hidden||(()=>false);
    const log=deps.log||function(){};
    const onPaint=deps.onPaint||function(){};

    let status=null,reachable=false,lastLoss=null;
    const pending={},failure={},known={};
    let shotAt=0,note=null,cursor=0,held=false,spoken='';
    let pollTimer=0,tickTimer=0,polling=null,stopped=false;
    /* `lostCount` : lectures ratées d'affilée (recul). `wroteAt` : fin de la
       dernière écriture (cadence rapide). */
    let lostCount=0,wroteAt=-Infinity;
    /* Les captures que **cette page** a demandé d'arrêter : leur fin n'est pas
       une interruption à signaler. */
    const stoppedHere=new Set();
    let openBefore=new Map();
    let view=viewOf({});

    installStyle(doc);
    host.textContent='';
    host.setAttribute('data-capture-rail','installed');

    const rule=doc.createElement('span');rule.className='cr-rule';rule.setAttribute('aria-hidden','true');
    host.appendChild(rule);
    const strip=doc.createElement('div');
    strip.id=DOM.stripId;strip.className='cr-tools';
    strip.setAttribute('role','toolbar');strip.setAttribute('aria-orientation','vertical');
    strip.setAttribute('aria-label','Capture : capture d’écran et enregistrements');
    host.appendChild(strip);

    const buttons=ORDER.map((id,index)=>{
      const el=doc.createElement('button');
      el.type='button';el.className='cr-btn';
      el.setAttribute(DOM.controlAttribute,id);el.setAttribute('tabindex','-1');
      const glyphHolder=doc.createElement('span');glyphHolder.className='cr-glyph';
      glyphHolder.style.display='contents';
      const time=doc.createElement('span');time.className='cr-time';time.setAttribute('aria-hidden','true');
      const badge=doc.createElement('span');badge.className='cr-badge';badge.setAttribute('aria-hidden','true');
      const stopMark=doc.createElement('span');stopMark.className='cr-stop';stopMark.setAttribute('aria-hidden','true');
      const wait=doc.createElement('span');wait.className='cr-wait';wait.setAttribute('aria-hidden','true');
      /* La durée lue par `aria-describedby` : un nœud masqué référencé par id
         compte dans la description, et une description qui change n'est pas
         réannoncée comme un nom. */
      const detail=doc.createElement('span');detail.className='cr-sr';detail.id=`${DOM.detailIdPrefix}${id}`;
      detail.setAttribute('aria-hidden','true');
      el.append(glyphHolder,time,badge,stopMark,wait,detail);
      el.addEventListener('click',()=>{act(id)});
      el.addEventListener('keydown',event=>onKey(event,index));
      el.addEventListener('focus',()=>{held=true;cursor=index;roving()});
      el.addEventListener('blur',()=>{held=false});
      strip.appendChild(el);
      return {id,el,glyphHolder,time,badge,detail,glyph:''};
    });

    const caption=doc.createElement('span');
    caption.id=DOM.captionId;caption.className='cr-cap';caption.setAttribute('aria-hidden','true');
    host.appendChild(caption);

    const noteBox=doc.createElement('div');
    noteBox.id=DOM.noteId;noteBox.className='cr-note';noteBox.hidden=true;
    const noteText_=doc.createElement('span');
    const close=doc.createElement('button');
    close.type='button';close.className='cr-note-close';close.textContent='×';
    close.setAttribute('aria-label','Fermer le message');
    close.addEventListener('click',()=>dismiss({focus:true}));
    noteBox.append(noteText_,close);
    host.appendChild(noteBox);

    const announce=doc.createElement('div');
    announce.id=DOM.announceId;announce.className='cr-sr';
    announce.setAttribute('role','status');announce.setAttribute('aria-live','polite');
    host.appendChild(announce);

    host.addEventListener('keydown',event=>{
      if(event&&event.key==='Escape'&&note){
        if(typeof event.preventDefault==='function')event.preventDefault();
        dismiss({focus:true});
      }
    });

    /* ------------------------------------------------- clavier */

    function roving(){
      for(let i=0;i<buttons.length;i+=1)buttons[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
    }
    function focusAt(index){
      cursor=(index+buttons.length)%buttons.length;
      roving();
      try{buttons[cursor].el.focus()}catch(_error){/* retiré entre-temps */}
    }
    /* Même barre d'outils que la palette du dessus : un seul arrêt de
       tabulation, flèches dans les deux axes, Début/Fin. Entrée et Espace sont
       ceux du `<button>` natif. */
    function onKey(event,index){
      const key=event&&event.key;
      if(key==='Home'||key==='End'){
        event.preventDefault();focusAt(key==='Home'?0:buttons.length-1);return;
      }
      const step=key==='ArrowDown'||key==='ArrowRight'?1:key==='ArrowUp'||key==='ArrowLeft'?-1:0;
      if(!step)return;
      event.preventDefault();
      focusAt(index+step);
    }

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

    /* Ce qu'un statut frais apprend au-delà de lui-même : la dernière capture
       ouverte de chaque canal (pour un arrêt quand le statut tombe) et les
       fins **que personne ici n'a demandées** — une source perdue, un disque
       plein — qui ne doivent pas passer en silence. */
    function absorb(body){
      const openNow=new Map();
      for(const channel of CHANNELS){
        const open=openOf(body,channel);
        known[channel]=open?{capture_id:open.capture_id}:null;
        if(open)openNow.set(open.capture_id,channel);
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
          /* `verb` : la fin vient d'ailleurs, l'infobulle ne parlera pas
             d'un « dernier essai » que l'utilisateur n'a pas fait. */
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

    function act(id){
      const control=view.controls[id];
      if(!control||!control.action||pending[id])return Promise.resolve(null);
      if(control.action==='shot')return shoot();
      if(control.action==='start')return start(id);
      return stop(id,control.captureId);
    }

    async function start(channel){
      pending[channel]={kind:'start',since:now()};
      failure[channel]=null;
      if(note&&note.control===channel)dismiss({quiet:true});
      paint();
      schedule();  // une écriture en vol : cadence d'une seconde dès maintenant
      log('info','capture_rail.start_requested',{channel});
      try{
        const body=await call(ROUTES.start,{method:'POST',body:JSON.stringify({channel})},TIMING.writeDeadlineMs);
        const capture=isObject(body)&&isObject(body.capture)?body.capture:{};
        log('info','capture_rail.started',{channel,capture_id:capture.capture_id||null,state:capture.state||null});
        say(`${LABEL[channel]} démarré.`);
        return capture.capture_id||null;
      }catch(error){
        if(error.code==='already_active'){
          /* Pas une panne : Core tient déjà ce canal, la relecture va le
             montrer ; l'attente reste peinte jusque-là. */
          show(channel,'warn',noteText(channel,'déjà actif',error.code,error.message));
          log('info','capture_rail.start_already_active',{channel,code:error.code});
        }else{
          /* L'attente tombe **avant** la note : jamais « démarrage… » à côté
             de « non démarré ». */
          pending[channel]=null;
          failure[channel]={code:error.code,text:refusalText(error.code,error.message,channel)};
          show(channel,'bad',noteText(channel,'non démarré',error.code,error.message));
          log(error.code==='client_timeout'||error.code==='core_timeout'?'warn':'error',
            'capture_rail.start_failed',{channel,code:error.code,status:error.status,error:error.message});
        }
        return null;
      }finally{
        /* Un démarrage accepté reste « démarrage… » jusqu'à la relecture qui
           le montre actif : pas de « repos » périmé entre les deux. */
        await fresh();
        pending[channel]=null;
        paint();
      }
    }

    async function stop(channel,captureId){
      if(!captureId)return null;
      pending[channel]={kind:'stop',since:now(),captureId};
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
        say(`${LABEL[channel]} arrêté.`);
        return capture.state||null;
      }catch(error){
        stoppedHere.delete(captureId);
        pending[channel]=null;
        show(channel,'bad',noteText(channel,'non arrêté',error.code,error.message));
        log('error','capture_rail.stop_failed',
          {channel,capture_id:captureId,code:error.code,status:error.status,error:error.message});
        return null;
      }finally{
        /* « Arrêt… » jusqu'à la relecture : pas d'« actif » périmé. */
        await fresh();
        pending[channel]=null;
        paint();
      }
    }

    async function shoot(){
      const id=CONTROL.SCREENSHOT;
      pending[id]={kind:'shot',since:now()};
      failure[id]=null;
      if(note&&note.control===id)dismiss({quiet:true});
      paint();
      log('info','capture_rail.screenshot_requested',{});
      try{
        const body=await call(ROUTES.screenshot,{method:'POST',body:'{}'},TIMING.writeDeadlineMs);
        const capture=isObject(body)&&isObject(body.capture)?body.capture:{};
        const artifact=isObject(body)&&isObject(body.artifact)?body.artifact:{};
        shotAt=now();
        log('info','capture_rail.screenshot_taken',
          {capture_id:capture.capture_id||null,artifact_id:artifact.artifact_id||null});
        say('Capture d’écran enregistrée.');
        /* La coche s'efface d'elle-même : on repeint juste après. */
        later(()=>paint(),TIMING.doneMs+50);
        return artifact.artifact_id||capture.capture_id||null;
      }catch(error){
        pending[id]=null;
        failure[id]={code:error.code,text:refusalText(error.code,error.message,id)};
        show(id,'bad',noteText(id,'échouée',error.code,error.message));
        log('error','capture_rail.screenshot_failed',{code:error.code,status:error.status,error:error.message});
        return null;
      }finally{
        pending[id]=null;
        paint();
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
         d'erreur du bouton part avec lui (le statut, lui, ne bouge pas). */
      if(!o.quiet&&failure[control])failure[control]=null;
      paint();
      if(o.focus){
        const index=ORDER.indexOf(control);
        if(index>=0)focusAt(index);
      }
    }
    function say(line){
      if(!line||line===spoken)return;
      spoken=line;announce.textContent=line;
    }

    /* ------------------------------------------------- peinture */

    function paint(){
      view=viewOf({status,reachable,pending,failure,known,shotAt,now:now()});
      host.setAttribute('data-cr-tone',!view.reachable?'unknown':view.troubled?'bad':view.recording?'rec':'idle');
      for(const button of buttons){
        const c=view.controls[button.id];
        const el=button.el;
        el.setAttribute(DOM.stateAttribute,c.state);
        if(c.pressed===null)el.removeAttribute('aria-pressed');
        else el.setAttribute('aria-pressed',c.pressed?'true':'false');
        /* `aria-disabled` et non `disabled` : la commande reste sur le chemin
           du clavier et son infobulle dit pourquoi elle ne s'active pas. */
        el.setAttribute('aria-disabled',c.action?'false':'true');
        /* Nom et infobulle stables ; la durée passe par la description. */
        if(el.getAttribute('aria-label')!==c.label){
          el.setAttribute('aria-label',c.label);
          el.setAttribute('title',c.label);
        }
        button.detail.textContent=c.detail;
        const described=[c.detail?button.detail.id:'',note&&note.control===button.id?DOM.noteId:'']
          .filter(Boolean).join(' ');
        if(described)el.setAttribute('aria-describedby',described);
        else el.removeAttribute('aria-describedby');
        const glyph=glyphOf(c);
        if(glyph!==button.glyph){
          button.glyphHolder.textContent='';
          button.glyphHolder.appendChild(icon(doc,glyph,22));
          button.glyph=glyph;
        }
        el.setAttribute('data-cr-stop',c.stopMark?'true':'false');
        button.time.textContent=c.timer;
        el.setAttribute('data-cr-timed',c.timer?'true':'false');
        button.badge.textContent=c.state===STATE.UNKNOWN?'?':(c.state===STATE.ERROR||c.state===STATE.STUCK?'!':'');
      }
      caption.textContent=view.caption;
      if(!held){
        const at=ORDER.findIndex(id=>view.controls[id].pressed);
        cursor=at<0?Math.min(cursor,ORDER.length-1):at;
      }
      roving();
      if(note){
        noteBox.hidden=false;
        noteBox.setAttribute('data-cr-tone',note.tone);
        noteText_.textContent=note.text;
        const anchor=buttons.find(b=>b.id===note.control);
        noteBox.style.top=anchor&&typeof anchor.el.offsetTop==='number'
          ?`${anchor.el.offsetTop+(strip.offsetTop||0)}px`:'0px';
      }else{
        noteBox.hidden=true;noteText_.textContent='';
      }
      onPaint(view);
      return view;
    }

    /* ------------------------------------------------- cycle */

    /* Le délai jusqu'au prochain sondage (décision PM, voir l'en-tête). */
    function delay(){
      const lost=lostCount>0
        ?Math.min(TIMING.lostBackoffMaxMs,TIMING.fastPollMs*2**Math.min(lostCount-1,10)):0;
      if(hidden())return Math.max(TIMING.hiddenPollMs,lost);
      if(lost)return lost;
      const busy=view.recording>0||ORDER.some(id=>pending[id])||now()-wroteAt<TIMING.afterWriteMs;
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

    function start_(){
      stopped=false;
      paint();
      /* La cadence se choisit sur la première réponse (ouvert, repos, perdu). */
      poll().then(()=>schedule());
      /* Le chronomètre avance entre deux sondages, sans en déclencher. */
      tickTimer=every(()=>{
        const live=ORDER.some(id=>view.controls[id].timer);
        if(live||view.controls.screenshot.state===STATE.DONE)paint();
      },TIMING.tickMs);
    }
    function destroy(){
      stopped=true;
      if(pollTimer){unlater(pollTimer);pollTimer=0}
      if(tickTimer){unevery(tickTimer);tickTimer=0}
    }
    /* L'onglet revient au premier plan : on relit tout de suite. */
    function wake(){
      if(stopped)return Promise.resolve(false);
      if(pollTimer){unlater(pollTimer);pollTimer=0}
      return poll().then(ok=>{schedule();return ok});
    }

    return {
      element:host,strip,start:start_,destroy,wake,poll,act,dismiss,focusAt,paint,
      view:()=>view,note:()=>note,nextDelay:delay,
    };
  }

  const CAPTURE_RAIL=Object.freeze({
    DOM,CONTROL,ORDER,CHANNELS,STATE,ROUTES,RECENT_ROWS,TIMING,LABEL,TEXT,FFMPEG_HINT,RAIL_GEO,ART,STYLE,
    refusalText,noteText,clock,elapsedOf,openOf,viewOf,labelOf,slotOf,glyphOf,icon,installStyle,
    createCaptureRail,
  });
  root.JarvisCaptureRailModule=CAPTURE_RAIL;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=CAPTURE_RAIL;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  /* ------------------------------------------------- bloc navigateur */

  /* La colonne Bare Hands, lue sur son module quand il est là : ses nombres
     ne sont écrits qu'une fois (`GEO` de `control_center_barehands_hud.js`). */
  function columnGeo(){
    const hud=window.JarvisBarehandsHud;
    const geo=hud&&hud.GEO?hud.GEO:{top:76,left:18,narrowLeft:10,narrowTop:-41};
    return geo;
  }
  const COLUMN_SELECTORS=Object.freeze(['#barehandsHud','#barehandsPalette']);
  /* Ce que le rail ne doit jamais recouvrir. */
  const OBSTACLE_SELECTOR='#interactionModeButton,.topbar>*,.dock,.voicehint,.bgpills,.live-banner,'
    +'#sceneLayer>.sc-status';

  function shown(el){
    if(!el||el.hidden||el.closest('[hidden]'))return null;
    const style=getComputedStyle(el);
    if(style.display==='none'||style.visibility==='hidden')return null;
    const r=el.getBoundingClientRect();
    return r.width>0&&r.height>0?r:null;
  }

  function createPlacer(host,log){
    let frame=0,slot=null,warned='';
    function measure(){
      const parent=host.offsetParent||document.body;
      const o=parent.getBoundingClientRect();
      const rel=r=>({left:r.left-o.left,top:r.top-o.top,right:r.right-o.left,bottom:r.bottom-o.top});
      let column=null;
      for(const selector of COLUMN_SELECTORS){
        const r=shown(document.querySelector(selector));
        if(!r)continue;
        const b=rel(r);
        column=column?{left:Math.min(column.left,b.left),top:Math.min(column.top,b.top),
          right:Math.max(column.right,b.right),bottom:Math.max(column.bottom,b.bottom)}:b;
      }
      const geo=columnGeo();
      const narrow=window.matchMedia&&window.matchMedia('(max-width:700px)').matches;
      const base=narrow?{left:geo.narrowLeft,top:o.height/2+geo.narrowTop}:{left:geo.left,top:geo.top};
      const obstacles=[];
      for(const el of document.querySelectorAll(OBSTACLE_SELECTOR)){
        if(host.contains(el))continue;
        const r=shown(el);
        if(r)obstacles.push(rel(r));
      }
      return {vw:o.width,vh:o.height,rail:{w:host.offsetWidth||64,h:host.offsetHeight||0},column,base,obstacles};
    }
    function place(){
      frame=0;
      const m=measure();
      const next=slotOf(m);
      host.style.top=`${next.top}px`;host.style.left=`${next.left}px`;
      host.setAttribute(DOM.slotAttribute,next.mode);
      host.setAttribute('data-capture-fits',next.fits?'true':'false');
      /* La note s'ouvre à droite du rail : elle s'arrête avant le bord de
         l'écran **et** avant la première commande qu'elle rencontrerait sur
         sa hauteur (le dock, sous 700 px, est à 60 px du rail). */
      const note=host.querySelector('.cr-note');
      if(note){
        const from=next.left+m.rail.w+8;
        let limit=m.vw-8;
        for(const o of m.obstacles)
          if(o.left>=from&&o.top<next.top+m.rail.h&&o.bottom>next.top)limit=Math.min(limit,o.left-8);
        note.style.maxWidth=`${Math.max(140,Math.min(280,limit-from))}px`;
      }
      const key=`${next.mode}:${next.fits}:${Math.round(m.vw)}x${Math.round(m.vh)}`;
      if(!next.fits&&warned!==key){
        warned=key;
        log('warn','capture_rail.no_free_slot',{mode:next.mode,viewport:[Math.round(m.vw),Math.round(m.vh)]});
      }
      if(!slot||slot.mode!==next.mode)log('info','capture_rail.placed',{mode:next.mode,fits:next.fits});
      slot=next;
      return next;
    }
    function schedule(){
      if(!frame)frame=requestAnimationFrame(place);
    }
    window.addEventListener('resize',schedule);
    if(typeof ResizeObserver==='function'){
      const ro=new ResizeObserver(schedule);
      for(const selector of [...COLUMN_SELECTORS,'#interactionModeHud'])
        {const el=document.querySelector(selector);if(el)ro.observe(el)}
      ro.observe(host);
    }
    if(typeof MutationObserver==='function'){
      const mo=new MutationObserver(schedule);
      for(const selector of [...COLUMN_SELECTORS,'#interactionModeHud']){
        const el=document.querySelector(selector);
        if(el)mo.observe(el,{attributes:true,childList:true,subtree:true});
      }
    }
    return {place,schedule,slot:()=>slot};
  }

  function installCaptureRail(){
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(new Error(`JarvisCaptureRail : l’emplacement #${DOM.hostId} manque dans control_center.html`),
        {code:'capture_rail_host_missing'});
    if(typeof window.fetch!=='function')
      throw Object.assign(new Error('JarvisCaptureRail : fetch indisponible'),{code:'capture_rail_fetch_missing'});
    const log=(level,event,data)=>{
      const line=`[capture] ${event} ${JSON.stringify(data)}`;
      if(level==='error')console.error(line);
      else if(level==='warn')console.warn(line);
      else console.info(line);
    };
    let placer=null;
    const rail=createCaptureRail({
      document,host,
      fetch:(url,init)=>window.fetch(url,init),
      now:()=>Date.now(),
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),clearTimeout:id=>window.clearTimeout(id),
      setInterval:(fn,ms)=>window.setInterval(fn,ms),clearInterval:id=>window.clearInterval(id),
      hidden:()=>document.hidden===true,
      log,
      onPaint:()=>{if(placer)placer.schedule()},
    });
    placer=createPlacer(host,log);
    document.addEventListener('visibilitychange',()=>{if(!document.hidden)rail.wake()});
    window.JarvisCaptureRail=Object.freeze({
      view:rail.view,note:rail.note,poll:rail.poll,act:rail.act,dismiss:rail.dismiss,
      place:placer.place,slot:placer.slot,
    });
    rail.start();
    placer.place();
    log('info','capture_rail.installed',{host:DOM.hostId});
  }

  try{installCaptureRail()}
  catch(error){
    console.error('[capture] capture_rail.install_failed '
      +JSON.stringify({code:(error&&error.code)||null,error:String((error&&error.message)||error)}));
  }
})(typeof globalThis!=='undefined'?globalThis:this);
