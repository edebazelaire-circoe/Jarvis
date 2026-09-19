/* Bare Hands V1 — contrats et schémas partagés (Slice 01).

   Ce module ne fait rien : il **nomme**. Il tient les structures, les
   vocabulaires et les versions de schéma sur lesquels s'accordent le suivi des
   mains, les gestes, l'intention de pincement, la résolution de cible,
   l'interaction, les outils, les réglages et la calibration. Les Slices
   suivantes implémentent les moteurs derrière ces noms ; aucune d'elles ne
   redéfinit un nom qui vit ici.

   Trois règles tenues par ce fichier :

   1. **Neutre vis-à-vis du traqueur.** Les indices de points MediaPipe ne
      figurent que dans `adapters.mediapipe`. Tout le reste manipule un
      `HandFrame` : horodatage, dimensions de la source, et par main une
      identité stable, une latéralité, une qualité et des points nommés. Un
      traqueur spécialisé se branche en écrivant un autre adaptateur.
   2. **Identité par main, pas identité unique.** L'expérience actuelle envoie
      tous ses événements sous `pointerId 9001`. Ce littéral est un contrat
      avec `control_center_scene_page.js` et `control_center.html`, pas un
      détail interne (Slice 00, constat F2). Il devient ici une plage :
      `pointerIdForSlot(0) === 9001` — la main seule garde exactement le
      comportement d'aujourd'hui — et la seconde main reçoit `9002`. Les
      consommateurs testent `isBareHandsPointerId()`, plus le littéral.
   3. **Schémas versionnés et partiels.** `normalizeSettings` et
      `normalizeProfile` acceptent l'absence et le partiel, et rendent toujours
      une valeur complète : une calibration incomplète reste valide, les
      fonctions non calibrées retombent sur les défauts (décisions 28, 31).
      Elles n'acceptent pas le **faux** pour autant : un numéro de schéma
      étranger ou une mesure impossible sont des refus codés.
   4. **Un refus codé plutôt qu'un défaut plausible.** C'est la règle qui tient
      les trois autres. Partout où une valeur fausse deviendrait indiscernable
      d'une vraie — une piste sans identité, une zone hors table, un état de
      capture inconnu, un pincement sans coordonnées — le module lève un
      `BareHandsSchemaError` portant un `code` stable, journalisable tel quel.
      L'absence, elle, reste permise : un défaut n'est un défaut que si
      personne n'a rien dit.

   Frontière clean-room : aucune ligne reprise de l'amont Barehands (AGPL).
   Les noms de gestes, d'états et de régions viennent des décisions produit de
   `tasks/jarvis-bare-hands-v1/docs/`, pas d'une source amont. Contrat lisible :
   `docs/barehands-contracts.md`.

   Logique pure : ni DOM, ni réseau, ni horloge. Exécuté tel quel par les tests
   node (`tests/unit/test_barehands_contracts_js.py`) et inséré tel quel dans la
   page par `ControlCenter.index`, avant `control_center_barehands.js`. */
(function(root){
  'use strict';

  /* Version des structures d'événement de ce fichier. Un producteur et un
     consommateur qui ne partagent pas ce nombre ne partagent pas ce contrat. */
  const SCHEMA_VERSION=1;

  /* Refus de schéma : même forme que les erreurs du serveur (`code` stable),
     pour qu'un rejet soit journalisable tel quel. */
  class BareHandsSchemaError extends Error{
    constructor(code,message){super(message);this.name='BareHandsSchemaError';this.code=code}
  }
  const reject=(code,message)=>{throw new BareHandsSchemaError(code,message)};

  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
  const finiteOr=(v,fallback)=>{const n=Number(v);return Number.isFinite(n)?n:fallback};
  const unit=(v,fallback)=>clamp(finiteOr(v,fallback),0,1);
  const bool=(v,fallback)=>typeof v==='boolean'?v:fallback;
  const oneOf=(v,allowed,fallback)=>allowed.includes(v)?v:fallback;
  const values=o=>Object.freeze(Object.keys(o).map(k=>o[k]));

  /* Règle de ce fichier : une valeur fausse se refuse, elle ne se remplace
     pas. Un repli silencieux rend une entrée invalide indiscernable d'une
     entrée vraie, et la panne ressort trois Slices plus loin, ailleurs.
     `enumOr` accepte donc l'absence (le défaut est un vrai défaut) et refuse
     l'inconnu (personne ne l'a voulu). */
  const enumOr=(value,allowed,fallback,code,label)=>{
    if(value===undefined||value===null)return fallback;
    if(!allowed.includes(value))reject(code,`${label} inconnu : ${String(value)}.`);
    return value;
  };
  /* Une identité de main est une chaîne non vide — mais `0` en est une : c'est
     le premier identifiant qu'émet un traqueur qui numérote ses pistes
     (Slice 03). Tout `x||''` la détruit et la remplace par la latéralité ; les
     deux mains échangent alors leur pointeur en plein glissement. Seul
     `x == null` veut dire « absente ». */
  const trackId=(value,message)=>{
    if(value===undefined||value===null)reject('barehands_hand_track_id_missing',message);
    const id=String(value).trim();
    if(!id)reject('barehands_hand_track_id_missing',message);
    return id;
  };
  /* Un numéro de schéma étranger n'est pas un champ à ignorer : il dit que le
     producteur et le consommateur ne partagent pas ce contrat. Le taire
     reviendrait à rendre une valeur complète et fausse. */
  const requireSchemaVersion=(value,expected,what)=>{
    if(value===undefined||value===null)return;
    if(Number(value)!==expected)
      reject('barehands_schema_version_unsupported',
        `${what} en version ${String(value)} ; ce module ne lit que la version ${expected}.`);
  };

  /* ------------------------------------------------------------------ 1
     Cycle de vie (décisions 4, 5, 7).
     OFF libère la caméra ; SLEEP garde un guetteur léger ; ACTIVE interagit. */

  /* `ERROR` n'est pas dans la décision 4, qui nomme trois états d'usage. Il
     s'y ajoute parce que sans lui une caméra refusée, une webcam occupée et un
     modèle absent se liraient tous « éteint », c'est-à-dire « l'utilisateur
     l'a voulu » — la panne disparaîtrait de l'état. `ERROR` dit exactement
     l'inverse : arrêté sans l'avoir demandé. Comme OFF, il ne tient rien (la
     caméra est rendue avant qu'il soit publié) ; le motif précis vit à côté,
     dans le `code` du statut (`camera_denied`, `camera_busy`,
     `assets_missing`…), jamais aplati dans l'état. On en sort en rallumant. */
  const LIFECYCLE=Object.freeze({OFF:'off',SLEEP:'sleep',ACTIVE:'active',ERROR:'error'});
  const LIFECYCLES=values(LIFECYCLE);
  /* États d'usage : ceux où Bare Hands fonctionne. Un appelant qui veut
     « allumé ou pas » teste ceci plutôt que `!== OFF`, qui rendrait une panne
     pour un fonctionnement. */
  const LIVE_LIFECYCLES=Object.freeze([LIFECYCLE.SLEEP,LIFECYCLE.ACTIVE]);
  const isLiveLifecycle=value=>LIVE_LIFECYCLES.includes(String(value));
  /* Les états du contrôleur (`control_center_barehands.js`) lus dans ce
     vocabulaire. `sleep`, `active` et `error` sont les siens depuis la
     Slice 02 ; `starting` vaut `off`, parce que rien n'interagit et que rien
     n'est encore tenu pour de bon. `running` est l'ancien nom d'`active`,
     gardé pour qu'un état journalisé avant la Slice 02 se relise encore. */
  const CONTROLLER_LIFECYCLE=Object.freeze({
    off:'off',starting:'off',error:'error',
    sleep:'sleep',active:'active',running:'active',
  });
  const lifecycleOfControllerState=state=>CONTROLLER_LIFECYCLE[String(state)]||LIFECYCLE.OFF;
  /* Décision 7 : 30 s sans main exploitable ramène ACTIVE à SLEEP.
     Décision 5 : la posture de réveil se tient environ une seconde. */
  const SLEEP_TIMEOUT_MS=30000;
  const WAKE_HOLD_MS=1000;
  /* Cadence du guetteur de SLEEP. Promise « 5 images par seconde » dans le
     contrat lisible *et* à l'écran, dans l'onglet Expérimental : elle vit donc
     ici, au même titre que les deux durées ci-dessus, plutôt que dans les seuls
     défauts du moteur où muter 200 → 500 ne faisait rien tomber. */
  const WAKE_INTERVAL_MS=200;

  /* Motifs d'arrêt subi : le `code` que porte un statut `error`, à côté de
     l'état et jamais aplati dedans. Le moteur (`control_center_barehands.js`)
     possède les messages ; le contrat possède le **vocabulaire**, faute de quoi
     un code publié et un code documenté divergent en silence — la dérive même
     qu'`ERROR` a été ajouté pour empêcher. Parité testée dans les deux sens :
     chaque code a son message, et toute autre clé de `MESSAGES` raconte le
     cycle de vie au lieu de motiver une panne. */
  const FAILURE_CODE=Object.freeze({
    CAMERA_DENIED:'camera_denied',CAMERA_MISSING:'camera_missing',
    CAMERA_BUSY:'camera_busy',CAMERA_ENDED:'camera_ended',
    CAMERA_UNSUPPORTED:'camera_unsupported',ASSETS_MISSING:'assets_missing',
    TRACKING_FAILED:'tracking_failed',OVERLAY_FAILED:'overlay_failed',
    START_FAILED:'start_failed',
  });
  const FAILURE_CODES=values(FAILURE_CODE);
  const isFailureCode=value=>FAILURE_CODES.includes(String(value));

  /* ------------------------------------------------------------------ 2
     Identité de main et identité de pointeur (Slice 00, constat F2). */

  const MAX_HANDS=2;
  /* Première fente = 9001 : une main seule produit exactement les mêmes
     événements qu'avant cette Slice. Les fentes suivantes montent d'un. */
  const POINTER_ID_BASE=9001;
  const POINTER_ID_MAX=POINTER_ID_BASE+MAX_HANDS-1;
  /* Les cibles de la page écoutent la souris ; le type reste `mouse` tant que
     la sortie DOM est une compatibilité (architecture §7). */
  const POINTER_TYPE='mouse';

  function pointerIdForSlot(slot){
    const n=Number(slot);
    if(!Number.isInteger(n)||n<0||n>=MAX_HANDS)
      reject('barehands_slot_out_of_range',`Fente de main hors plage : ${slot} (0 à ${MAX_HANDS-1}).`);
    return POINTER_ID_BASE+n;
  }
  const isBareHandsPointerId=id=>Number.isInteger(Number(id))&&Number(id)>=POINTER_ID_BASE&&Number(id)<=POINTER_ID_MAX;
  const slotForPointerId=id=>isBareHandsPointerId(id)?Number(id)-POINTER_ID_BASE:null;

  /* Fentes stables : une piste garde sa fente tant qu'elle vit, et une fente
     libérée est réutilisée par la piste suivante. Au-delà de MAX_HANDS, la
     main surnuméraire n'a pas de fente (`null`) — elle est suivie, pas
     pointée : mieux qu'un identifiant volé à une autre main. */
  function createSlotAllocator(max){
    /* Une capacité douteuse ne se rabote pas : `0`, `'oops'` et `-1` rendaient
       tous une capacité de 1 ou 2, c'est-à-dire un allocateur qui marche alors
       que l'appelant s'est trompé. L'absence, elle, est un vrai défaut. */
    const capacity=max===undefined||max===null?MAX_HANDS:Number(max);
    if(!Number.isInteger(capacity)||capacity<1||capacity>MAX_HANDS)
      reject('barehands_slot_capacity_invalid',
        `Capacité de fentes attendue entre 1 et ${MAX_HANDS} ; reçue ${String(max)}.`);
    /* Toutes les entrées passent par `trackId` : une clé normalisée ici et une
       autre là laissait une piste fantôme occuper la fente 0 pour toujours,
       et la main suivante repartait à `9002` — la compatibilité perdue en
       silence. */
    const IDENTIFIED='Une fente de pointeur appartient à une main identifiée.';
    const byTrack=new Map();
    const slot=handTrackId=>{
      const key=trackId(handTrackId,IDENTIFIED);
      if(byTrack.has(key))return byTrack.get(key);
      const taken=new Set(byTrack.values());
      for(let i=0;i<capacity;i+=1)if(!taken.has(i)){byTrack.set(key,i);return i}
      return null;
    };
    /* Gelé comme tout ce que rend ce module, et sans `this` : l'allocateur se
       déstructure (`const {pointerId}=allocator`) sans se casser. */
    return Object.freeze({
      /* `capacity` = fentes existantes (constante) ; `size()` = fentes
         occupées à l'instant. Les deux se lisaient « size » avant. */
      capacity,
      slot,
      pointerId(handTrackId){const n=slot(handTrackId);return n===null?null:pointerIdForSlot(n)},
      /* Une piste perdue rend sa fente ; sans cela deux mains qui vont et
         viennent finiraient par n'en trouver aucune. */
      forget(handTrackId){return byTrack.delete(trackId(handTrackId,IDENTIFIED))},
      retain(liveIds){
        const live=new Set([...(liveIds||[])].map(id=>trackId(id,IDENTIFIED)));
        for(const key of [...byTrack.keys()])if(!live.has(key))byTrack.delete(key);
      },
      size(){return byTrack.size},
      clear(){byTrack.clear()},
    });
  }

  /* Formes du DOM qui sont un contrat entre modules : la scène reconnaît Bare
     Hands par là (`control_center_scene_page.js`), et le balayage `inert` de la
     boîte de confirmation exempte la racine par son identifiant
     (`control_center.html`). Changer un de ces noms se fait ici. */
  const DOM=Object.freeze({
    rootId:'jarvisHands',
    styleId:'jarvisHandsStyle',
    tokenClass:'jh-token',
    ringClass:'jh-ring',
    /* Anneau de progression du réveil en veille (Slice 02, décision 5) : il ne
       suit aucune main en particulier, il n'y en a qu'un. */
    wakeClass:'jh-wake',
    badgeClass:'jh-badge',
    hoverClass:'jarvis-hand-hover',
    /* Aperçu de cible (Slice 05, décision 3). Deux classes, parce qu'il y a
       deux choses à dire : `targetClass` trace l'objet visé, `targetZoneClass`
       le **seul** bord ou coin retenu. Un objet dont on ne montrerait que le
       contour ne dirait pas ce qui sera saisi. Elles n'existent dans l'arbre
       que pendant une intention — voir `jh-note` pour l'autre moitié de la
       règle zéro. */
    targetClass:'jh-target',
    targetZoneClass:'jh-target-zone',
    /* Une phrase courte sous la pastille : ce qui a été **refusé** et pourquoi
       (geste étouffé pendant une manipulation). Un geste qui disparaît sans
       trace est indiscernable d'un geste non reconnu. */
    noteClass:'jh-note',
    rootSelector:'#jarvisHands',
    tokenSelector:'#jarvisHands .jh-token',
    badgeSelector:'#jarvisHands .jh-badge',
  });
  /* Sans DOM dans ce module : on lit l'identifiant, on n'interroge pas l'arbre. */
  const isOverlayRoot=el=>!!el&&el.id===DOM.rootId;

  const HANDEDNESS=Object.freeze({LEFT:'left',RIGHT:'right',UNKNOWN:'unknown'});
  const HANDEDNESSES=values(HANDEDNESS);

  /* ------------------------------------------------------------------ 3
     HandFrame : sortie normalisée d'un traqueur, quel qu'il soit. */

  /* Points nommés dont dépendent les moteurs. Un traqueur qui n'en fournit pas
     un le laisse absent ; le moteur qui en a besoin le déclare indisponible. */
  const POINT_ROLES=Object.freeze(['wrist','thumbTip','indexTip','middleTip','middleMcp','ringMcp','pinkyMcp']);

  function normalizePoint(value,role){
    if(!value||typeof value!=='object')
      reject('barehands_point_invalid',`Point « ${role} » absent ou non objet.`);
    const x=Number(value.x),y=Number(value.y);
    if(!Number.isFinite(x)||!Number.isFinite(y))
      reject('barehands_point_invalid',`Point « ${role} » sans coordonnées utilisables.`);
    return Object.freeze({x,y,z:finiteOr(value.z,0)});
  }

  /* Une main observée sur une image. `handTrackId` est l'identité persistante
     que la Slice 03 rendra stable ; la latéralité n'est qu'un indice
     (architecture §2), jamais l'identité. */
  function createHandObservation(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_hand_invalid','Main attendue sous forme d’objet.');
    const id=trackId(source.handTrackId,'Chaque main observée doit porter un handTrackId.');
    const points={};
    const given=source.points&&typeof source.points==='object'?source.points:{};
    for(const role of POINT_ROLES)if(given[role]!==undefined&&given[role]!==null)points[role]=normalizePoint(given[role],role);
    return Object.freeze({
      handTrackId:id,
      handedness:oneOf(source.handedness,HANDEDNESSES,HANDEDNESS.UNKNOWN),
      handednessConfidence:unit(source.handednessConfidence,0),
      /* Qualité de suivi : 0 = main devinée, 1 = main franche. Les seuils et
         l'assistance s'y réfèrent plutôt qu'à un score propre au traqueur.
         Calculée depuis la Slice 03 par `JarvisBarehandsCore.handQuality` ;
         `HAND_QUALITY_FLOOR` dit à partir d'où une main **compte**. */
      quality:unit(source.quality,1),
      points:Object.freeze(points),
      /* Points bruts du traqueur, gardés pour le diagnostic et le rejeu
         (architecture §12) : aucun moteur n'a le droit de les lire. */
      raw:Object.freeze(Array.isArray(source.raw)?source.raw.slice():[]),
    });
  }

  function createHandFrame(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_frame_invalid','HandFrame attendu sous forme d’objet.');
    const t=Number(source.t);
    if(!Number.isFinite(t))reject('barehands_frame_time_invalid','HandFrame sans horodatage utilisable (t).');
    const given=source.source&&typeof source.source==='object'?source.source:{};
    const width=Math.max(0,finiteOr(given.width,0)),height=Math.max(0,finiteOr(given.height,0));
    const hands=(Array.isArray(source.hands)?source.hands:[]).map(createHandObservation);
    if(hands.length>MAX_HANDS)
      reject('barehands_too_many_hands',`V1 suit ${MAX_HANDS} mains au plus ; ${hands.length} reçues.`);
    const seen=new Set();
    for(const hand of hands){
      if(seen.has(hand.handTrackId))
        reject('barehands_hand_track_id_duplicate',`handTrackId en double dans une image : ${hand.handTrackId}.`);
      seen.add(hand.handTrackId);
    }
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,t,
      /* `aspect` sert les mesures invariantes à l'échelle (écart rapporté à la
         paume) : les coordonnées sont normalisées par axe, pas isotropes. */
      source:Object.freeze({width,height,aspect:height>0&&width>0?width/height:finiteOr(given.aspect,4/3),
        tracker:String(given.tracker||'unknown')}),
      hands:Object.freeze(hands),
    });
  }

  /* Seuil de confiance d'une main. `quality` est une note continue ; ce nombre
     est le **seul** endroit qui dise à partir d'où une main compte. La
     décision 7 le demandait déjà — son minuteur de 30 s se réarme sur « une
     main exploitable » — et la Slice 02 a dû l'approximer en « une main
     quelconque », faute de qualité à lire : une main à moitié hors cadre
     tenait donc l'interaction éveillée indéfiniment. Le moteur le recopie sous
     `DEFAULTS.qualityFloor` (le bloc pur est chargé seul par les tests node) et
     le test de parité refuse la dérive.

     Bas à dessein : il écarte une main devinée, pas une main mal placée. Une
     qualité sévère ferait dormir une session en plein usage, ce qui est une
     panne bien pire que celle qu'elle corrige. */
  const HAND_QUALITY_FLOOR=.25;
  const isUsableQuality=value=>Number.isFinite(Number(value))&&Number(value)>=HAND_QUALITY_FLOOR;

  /* ---- Traits de mouvement (architecture §3, Slice 03).

     Ce que le filtre adaptatif rend observable, et ce que les Slices 04 à 06
     liront pour trancher clic contre glissement. Comme les six autres
     structures de ce fichier, il a une fabrique plutôt que dix champs libres :
     `INTERACTION` a montré ce que coûte un nom sans forme — chaque
     consommateur invente la sienne, et les unités se perdent au premier appel.

     **Deux positions, pas une.** `rawX`/`rawY` est le point tel que le traqueur
     l'a rendu, `x`/`y` le point filtré. Les deux sont nécessaires : la
     calibration mesure le tremblement sur leur écart (`jitterPx`, §10) et le
     banc de rejeu (§12) compare l'erreur de l'un à l'erreur de l'autre. Un
     filtre dont on ne voit que la sortie ne se règle pas.

     `x`/`y` est la position **filtrée**, jamais l'ancre de visée que le jeton
     fige pendant un pincement : cet échantillon décrit la main, pas l'affichage.

     Unités : les positions sont en **pixels de la fenêtre**, comme
     `clientX`/`clientY` et comme `createPinchEvent` ; les vitesses portent la
     leur dans leur nom. */
  function createMotionSample(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_motion_invalid','Échantillon de mouvement attendu sous forme d’objet.');
    const handTrackId=trackId(source.handTrackId,'Un échantillon de mouvement appartient à une main identifiée.');
    /* Une position manquante ne se remplace pas par (0,0) : le coin de
       l'écran est un endroit plausible, et une immobilité mesurée là serait
       indiscernable d'une vraie. */
    const at=key=>{
      const n=Number(source[key]);
      return Number.isFinite(n)?n:reject('barehands_motion_position_missing',
        `Un échantillon de mouvement porte ses coordonnées : ${key} est requis, en pixels de la fenêtre.`);
    };
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'motion',
      handTrackId,
      rawX:at('rawX'),rawY:at('rawY'),x:at('x'),y:at('y'),
      vxPxPerSec:finiteOr(source.vxPxPerSec,0),vyPxPerSec:finiteOr(source.vyPxPerSec,0),
      speedPxPerSec:Math.max(0,finiteOr(source.speedPxPerSec,0)),
      /* 1 = main posée, 0 = main qui file. `stillMs` est **depuis quand** elle
         est posée : c'est cette durée, et non l'instantané, qui distingue un
         clic d'un début de glissement — une vitesse passe sous le seuil une
         image au milieu d'un geste franc.

         Les deux se lisent sur une vitesse lissée à 1 Hz (τ ≈ 159 ms) : après
         une main à 900 px/s stoppée net, `stillness` franchit 0,5 à ~250 ms et
         `stillMs` ne commence à courir qu'à ~585 ms. Une immobilité plus
         courte que ~600 ms ne se reconnaît donc pas, et un consommateur qui a
         besoin de « la main a-t-elle bougé » doit lire un déplacement, pas une
         vitesse. Chiffré dans `docs/barehands-contracts.md`, § Temps
         d'établissement de la vitesse. */
      stillness:unit(source.stillness,0),
      stillMs:Math.max(0,finiteOr(source.stillMs,0)),
      quality:unit(source.quality,1),
      t:finiteOr(source.t,0),
    });
  }

  /* ------------------------------------------------------------------ 4
     Gestes sémantiques (architecture §4, décision 5). */

  const GESTURE=Object.freeze({
    C_POSE:'c_pose',        // posture de réveil, tenue ~1 s (décision 5)
    OPEN_PALM:'open_palm',
    FIST:'fist',
    DOUBLE_CLOSE:'double_close',
    CLAP:'clap',
  });
  const GESTURES=values(GESTURE);
  const GESTURE_PHASE=Object.freeze({START:'start',HOLD:'hold',END:'end',CANCEL:'cancel'});
  const GESTURE_PHASES=values(GESTURE_PHASE);
  /* Portée : un geste global ne vole pas la main à une manipulation en cours
     (architecture §4) ; `hand` reste permis pendant une capture. */
  const GESTURE_SCOPE=Object.freeze({GLOBAL:'global',HAND:'hand'});
  const GESTURE_SCOPES=values(GESTURE_SCOPE);

  /* Table d'arbitrage (architecture §4, Slice 04). L'architecture demande
     qu'« un geste global ne vole pas la main à une manipulation capturée,
     **sauf autorisation explicite** » : la portée dit *à qui* le geste
     appartient, `duringCapture` est l'autorisation, et les deux vivent ici
     parce que la Slice 05 (retour visuel) et la Slice 06 (captures) doivent
     lire la même table que le moteur.

     - `global` se tait dès que **n'importe quelle** main tient une capture ;
     - `hand` se tait quand **cette** main en tient une, et reste permis
       pendant que l'autre manipule (décision 12 : deux mains indépendantes).

     La seule autorisation accordée est la **main ouverte**, et elle n'est pas
     un cas d'école : une manipulation qu'on ne peut pas abandonner est un
     piège, et le geste universel pour lâcher doit fonctionner exactement quand
     quelque chose est tenu. Ouvrir cette porte à d'autres gestes est une
     décision produit, pas un réglage : elle se prend ici, une fois. */
  const GESTURE_RULES=Object.freeze({
    c_pose:Object.freeze({scope:GESTURE_SCOPE.HAND,duringCapture:false}),
    open_palm:Object.freeze({scope:GESTURE_SCOPE.GLOBAL,duringCapture:true}),
    fist:Object.freeze({scope:GESTURE_SCOPE.HAND,duringCapture:false}),
    double_close:Object.freeze({scope:GESTURE_SCOPE.HAND,duringCapture:false}),
    clap:Object.freeze({scope:GESTURE_SCOPE.GLOBAL,duringCapture:false}),
  });
  /* Un geste hors table n'a pas de portée « par défaut » : le repli `global`
     serait le plus dangereux des deux, exactement comme pour `scope`. */
  const gestureRule=gesture=>GESTURE_RULES[gesture]
    ||reject('barehands_gesture_unknown',`Geste inconnu : ${String(gesture)}.`);
  const gestureScope=gesture=>gestureRule(gesture).scope;
  const gestureAllowedDuringCapture=gesture=>gestureRule(gesture).duringCapture;
  /* « Ce geste doit-il se taire ? » — une définition, partagée par le moteur,
     le retour visuel et les liaisons. `captured` est l'ensemble des identités
     de main qui tiennent une capture. */
  function isGestureSuppressed(gesture,handTrackId,captured){
    const rule=gestureRule(gesture);
    if(rule.duringCapture)return false;
    const held=new Set([...(captured||[])].map(id=>String(id)));
    if(rule.scope===GESTURE_SCOPE.GLOBAL)return held.size>0;
    return handTrackId!==undefined&&handTrackId!==null&&held.has(String(handTrackId));
  }

  function createGestureEvent(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_gesture_invalid','Geste attendu sous forme d’objet.');
    if(!GESTURES.includes(source.gesture))
      reject('barehands_gesture_unknown',`Geste inconnu : ${String(source.gesture)}.`);
    if(!GESTURE_PHASES.includes(source.phase))
      reject('barehands_gesture_phase_unknown',`Phase de geste inconnue : ${String(source.phase)}.`);
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'gesture',
      gesture:source.gesture,phase:source.phase,
      /* Une portée inconnue retombait sur `global`, c'est-à-dire sur celle qui
         peut voler la main à une manipulation en cours : le repli le plus
         dangereux des deux. Elle se refuse. */
      scope:enumOr(source.scope,GESTURE_SCOPES,GESTURE_SCOPE.GLOBAL,'barehands_gesture_scope_unknown','Portée de geste'),
      handTrackId:source.handTrackId===undefined||source.handTrackId===null
        ?null:trackId(source.handTrackId,'Un geste attribué porte une identité de main utilisable.'),
      t:finiteOr(source.t,0),
      progress:unit(source.progress,source.phase===GESTURE_PHASE.END?1:0),
      confidence:unit(source.confidence,1),
    });
  }

  /* ------------------------------------------------------------------ 5
     Intention de pincement (architecture §5, décisions 20-22).

     Le pincement est un flux de contact, pas une commande de clic : la durée et
     le déplacement pendant `down` servent à décider clic, glissement ou
     défilement. Le clic droit est un canal, jamais un appui long (décision 22). */

  const PINCH_CHANNEL=Object.freeze({PRIMARY:'primary',SECONDARY:'secondary'});
  const PINCH_CHANNELS=values(PINCH_CHANNEL);
  /* Doigts de chaque canal (décisions 20, 21), en rôles de points, non en
     indices de traqueur. */
  const PINCH_FINGERS=Object.freeze({primary:Object.freeze(['thumbTip','indexTip']),secondary:Object.freeze(['thumbTip','middleTip'])});
  const PINCH_PHASE=Object.freeze({APPROACH:'approach',DOWN:'down',MOVE:'move',UP:'up',CANCEL:'cancel'});
  const PINCH_PHASES=values(PINCH_PHASE);
  /* Ce qu'un contact **voulait dire** (décision 22). Le clic droit n'est pas
     ici : c'est un canal, pas une intention — le doigt le décide, jamais la
     durée. Ce que la durée et le déplacement décident, c'est ceci :

     - `drag` se tranche **en cours de route**, dès que la main a franchi la
       tolérance : une main qui repart d'où elle est venue a tout de même
       glissé ;
     - `click` ne se tranche qu'au relâchement — on ne peut pas savoir qu'un
       contact sera court avant qu'il finisse ;
     - `undecided` est l'état honnête entre les deux, et il a un nom pour que
       personne ne le lise « clic » par défaut.

     Le défilement n'en est pas non plus : il dépend de la **cible** sous la
     main, que la Slice 05 résout et que la Slice 06 consomme. Ce contrat
     fournit les ingrédients (`travelPx`, `durationMs`, plus la vitesse et
     l'immobilité de `createMotionSample`), pas la conclusion. */
  const PINCH_INTENT=Object.freeze({UNDECIDED:'undecided',CLICK:'click',DRAG:'drag'});
  const PINCH_INTENTS=values(PINCH_INTENT);

  function createPinchEvent(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_pinch_invalid','Pincement attendu sous forme d’objet.');
    if(!PINCH_CHANNELS.includes(source.channel))
      reject('barehands_pinch_channel_unknown',`Canal de pincement inconnu : ${String(source.channel)}.`);
    if(!PINCH_PHASES.includes(source.phase))
      reject('barehands_pinch_phase_unknown',`Phase de pincement inconnue : ${String(source.phase)}.`);
    const handTrackId=trackId(source.handTrackId,'Un pincement appartient à une main identifiée.');
    const slot=source.slot===undefined||source.slot===null?null:Number(source.slot);
    /* Pixels de la fenêtre : le point visé, déjà figé par l'ancre pendant
       l'approche pour que la cible ne glisse pas sous les doigts. Sans
       coordonnées, un clic partait en (0,0) — le coin de l'écran, où il y a
       toujours quelque chose à cliquer. Seul `cancel` n'a rien à viser. */
    const x=Number(source.x),y=Number(source.y);
    if(source.phase!==PINCH_PHASE.CANCEL&&!(Number.isFinite(x)&&Number.isFinite(y)))
      reject('barehands_pinch_position_missing',
        `Un pincement « ${source.phase} » vise un point : x et y sont requis, en pixels de la fenêtre.`);
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'pinch',
      channel:source.channel,phase:source.phase,handTrackId,
      slot:slot===null?null:slot,
      pointerId:slot===null?null:pointerIdForSlot(slot),
      x:Number.isFinite(x)?x:0,y:Number.isFinite(y)?y:0,
      t:finiteOr(source.t,0),
      progress:unit(source.progress,source.phase===PINCH_PHASE.DOWN?1:0),
      confidence:unit(source.confidence,1),
      /* Décision 22 : la durée et le déplacement du contact **contribuent** à
         l'intention, ils ne la remplacent pas et ne font jamais un clic droit.
         Absents, l'intention est `undecided` — jamais `click`, qui est la
         conclusion, pas le défaut. */
      intent:enumOr(source.intent,PINCH_INTENTS,PINCH_INTENT.UNDECIDED,
        'barehands_pinch_intent_unknown','Intention de pincement'),
      travelPx:Math.max(0,finiteOr(source.travelPx,0)),
      durationMs:Math.max(0,finiteOr(source.durationMs,0)),
    });
  }

  /* ------------------------------------------------------------------ 6
     Cible et régions (architecture §6, décisions 3, 8, 9, 16, 23). */

  const REGION=Object.freeze({BODY:'body',EDGE:'edge',CORNER:'corner'});
  const REGIONS=values(REGION);
  const EDGE=Object.freeze({TOP:'top',RIGHT:'right',BOTTOM:'bottom',LEFT:'left'});
  const EDGES=values(EDGE);
  const CORNER=Object.freeze({TOP_LEFT:'top_left',TOP_RIGHT:'top_right',BOTTOM_RIGHT:'bottom_right',BOTTOM_LEFT:'bottom_left'});
  const CORNERS=values(CORNER);
  /* Une zone tient un ou deux **côtés** du cadre ; chaque côté contraint un
     axe. Raisonner en côtés, et non en axes, est ce qui rend les décisions 16
     et 17 décidables : deux coins « partagent un axe » quand ils tirent sur le
     même côté (bas-droite et haut-droite tiennent tous deux la droite), pas
     simplement parce qu'ils contraignent tous deux x et y. */
  const SIDE_AXIS=Object.freeze({top:'y',bottom:'y',left:'x',right:'x'});
  const ZONE_SIDES=Object.freeze({
    top:Object.freeze(['top']),bottom:Object.freeze(['bottom']),
    left:Object.freeze(['left']),right:Object.freeze(['right']),
    top_left:Object.freeze(['top','left']),top_right:Object.freeze(['top','right']),
    bottom_right:Object.freeze(['bottom','right']),bottom_left:Object.freeze(['bottom','left']),
  });
  const zoneSides=zone=>ZONE_SIDES[String(zone)]||Object.freeze([]);
  const zoneAxes=zone=>Object.freeze([...new Set(zoneSides(zone).map(side=>SIDE_AXIS[side]))].sort());

  /* Priorité d'aperçu en recouvrement : coin > bord > corps (architecture §6). */
  const REGION_PRIORITY=Object.freeze({corner:3,edge:2,body:1});
  const regionPriority=kind=>REGION_PRIORITY[String(kind)]||0;
  /* La meilleure candidate. Trois critères, dans cet ordre :

     1. **actionnable d'abord** (décision 3). Une candidate non actionnable
        n'appelle aucun retour visuel ; la laisser gagner sur une candidate
        actionnable, c'est n'afficher plus rien alors qu'il y avait quelque
        chose à montrer.
     2. **priorité de région** : coin > bord > corps. Une région hors table
        vaut 0 et n'est pas une candidate du tout — avant, la première citée
        gagnait avant que la priorité soit consultée.
     3. **la plus proche** : `distancePx` était porté et jamais lu, si bien que
        l'ordre des arguments tranchait les égalités. À distance égale, la
        première citée gagne encore. */
  const isActionable=candidate=>candidate.actionable!==false;
  function pickRegion(candidates){
    let best=null,bestPriority=0,bestDistance=Infinity,bestActionable=false;
    for(const candidate of candidates||[]){
      if(!candidate)continue;
      const priority=regionPriority(candidate.region);
      if(!priority)continue;
      const actionable=isActionable(candidate);
      const distance=finiteOr(candidate.distancePx,Infinity);
      const better=!best
        ||(actionable!==bestActionable?actionable
          :priority!==bestPriority?priority>bestPriority
          :distance<bestDistance);
      if(better){best=candidate;bestPriority=priority;bestDistance=distance;bestActionable=actionable}
    }
    return best;
  }

  /* Rôles de couleur du retour visuel (décision 23). La valeur vit dans le
     thème de la page, pas ici : seul le nom de la variable est un contrat. */
  const FEEDBACK=Object.freeze({BODY:'body',ZONE:'zone',SECONDARY:'secondary'});
  const FEEDBACK_TOKENS=Object.freeze({
    body:Object.freeze({cssVar:'--bh-feedback-body',fallback:'#6ee7ff'}),      // bleu : corps / normal
    zone:Object.freeze({cssVar:'--bh-feedback-zone',fallback:'#ffd166'}),      // jaune : zone de manipulation
    secondary:Object.freeze({cssVar:'--bh-feedback-secondary',fallback:'#ff5d73'}), // rouge : clic droit
  });

  /* Quel rôle de couleur porte un retour visuel, décision 23 entière en une
     ligne. La région dit bleu ou jaune ; le **canal** passe devant les deux,
     parce que « clic droit » est une intention et non une partie du cadre : un
     coin visé au pouce-majeur est rouge, pas jaune. Elle vit ici et non chez
     le consommateur pour que le moteur, l'aperçu et les réglages lisent la
     même règle, et elle en est la **seule** source : `createTargetCandidate`
     en portait une seconde copie, aveugle au canal, qui rendait « jaune » là
     où l'écran affichait « rouge ». Une candidate ne connaît pas le canal — le
     canal appartient à la main, pas à la partie du cadre qu'elle vise — donc
     elle ne porte plus de couleur du tout, et qui dessine appelle cette
     fonction avec la région **et** le canal.

     Canal absent = `primary` (règle d'absence) ; canal ou région **inconnus**
     se refusent : une couleur inventée dirait à l'utilisateur qu'il va faire
     autre chose que ce qu'il fait. */
  function feedbackRole(region,channel){
    if(!REGIONS.includes(region))
      reject('barehands_region_unknown',`Région inconnue : ${String(region)}.`);
    const value=channel===undefined||channel===null?PINCH_CHANNEL.PRIMARY:String(channel);
    if(!PINCH_CHANNELS.includes(value))
      reject('barehands_pinch_channel_unknown',`Canal de pincement inconnu : ${String(channel)}.`);
    if(value===PINCH_CHANNEL.SECONDARY)return FEEDBACK.SECONDARY;
    return region===REGION.BODY?FEEDBACK.BODY:FEEDBACK.ZONE;
  }

  /* Candidate de cible. `objectId` est l'identité de la scène
     (`data-object-id`) quand il y en a une ; `element` reste au consommateur
     navigateur et ne traverse jamais ce contrat. */
  function createTargetCandidate(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_target_invalid','Candidate attendue sous forme d’objet.');
    if(!REGIONS.includes(source.region))
      reject('barehands_region_unknown',`Région inconnue : ${String(source.region)}.`);
    const zone=source.zone===undefined||source.zone===null?null:String(source.zone);
    if(source.region===REGION.EDGE&&!EDGES.includes(zone))
      reject('barehands_zone_invalid',`Bord attendu parmi ${EDGES.join(', ')} ; reçu ${String(zone)}.`);
    if(source.region===REGION.CORNER&&!CORNERS.includes(zone))
      reject('barehands_zone_invalid',`Coin attendu parmi ${CORNERS.join(', ')} ; reçu ${String(zone)}.`);
    const bounds=source.boundsPx&&typeof source.boundsPx==='object'?source.boundsPx:{};
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,
      objectId:source.objectId===undefined||source.objectId===null?null:String(source.objectId),
      /* Type sémantique lu du composant (bouton, lien, nœud de scène…) : c'est
         lui, et non `elementFromPoint` seul, qui décide l'action possible. */
      kind:String(source.kind||'unknown'),
      region:source.region,
      zone:source.region===REGION.BODY?null:zone,
      axes:source.region===REGION.BODY?Object.freeze([]):zoneAxes(zone),
      /* **Pixels de la fenêtre**, comme `clientX`/`clientY` — jamais des
         unités de scène (±160 × ±90, `control_center_scene_interact.js`). Le
         suffixe est là pour qu'une confusion d'unité se voie à la lecture
         plutôt que de se déboguer comme un défaut de géométrie.

         C'est le cadre de l'**objet entier**, pas celui de la zone : la zone
         est entièrement décrite par `region` + `zone`, et sa bande se redérive
         de ce cadre (`JarvisBarehandsCore.targetBand`). Deux rectangles pour
         une même chose auraient divergé. */
      boundsPx:Object.freeze({x:finiteOr(bounds.x,0),y:finiteOr(bounds.y,0),
        w:Math.max(0,finiteOr(bounds.w,0)),h:Math.max(0,finiteOr(bounds.h,0))}),
      /* Décision 3 : pas de pointeur permanent. Une candidate non actionnable
         n'appelle aucun retour visuel — c'est une obligation du consommateur,
         que `pickRegion` aide en la classant derrière les actionnables. */
      actionable:bool(source.actionable,true),
      /* Représentation de scène, quand la candidate en est une : seules
         `capsule` et `window` ont des zones (décision D3 de la Slice 00). */
      representation:source.representation===undefined||source.representation===null?null:String(source.representation),
      /* Distance du jeton à la candidate, en pixels de la fenêtre. */
      distancePx:Math.max(0,finiteOr(source.distancePx,0)),
      /* Pas de `feedback` ici, à dessein (décision 23) : le rôle de couleur
         dépend du **canal**, qu'une candidate ne porte pas. Le champ existait
         et valait `region===BODY ? body : zone` — une seconde règle, aveugle
         au canal, qui rendait jaune un coin visé au clic droit. C'est
         `feedbackRole(region, canal)` qui le décide, et lui seul. */
    });
  }
  /* Zones de manipulation : seules ces représentations en ont (décision D3). */
  const ZONED_REPRESENTATIONS=Object.freeze(['capsule','window']);
  const hasManipulationZones=representation=>ZONED_REPRESENTATIONS.includes(String(representation));

  /* ------------------------------------------------------------------ 7
     Interaction et capture (architecture §7, décisions 10-19). */

  const INTERACTION=Object.freeze({
    HOVER:'hover',CLICK:'click',CONTEXT:'context',
    DRAG_START:'drag_start',DRAG_MOVE:'drag_move',DRAG_END:'drag_end',
    SCROLL:'scroll',SELECT:'select',MOVE:'move',RESIZE:'resize',
  });
  const INTERACTIONS=values(INTERACTION);
  /* Une capture est latchée jusqu'au relâchement (décision 13). */
  const CAPTURE_STATE=Object.freeze({IDLE:'idle',CAPTURED:'captured',RELEASED:'released'});
  const CAPTURE_STATES=values(CAPTURE_STATE);

  const CAPTURE_IDENTIFIED='Une capture appartient à une main identifiée.';
  /* Région et zone d'une capture, validées de la même façon partout. Avant,
     `createCapture` refusait une zone hors table mais `combineCaptures`
     l'acceptait et en tirait un redimensionnement confiant : un seul des deux
     chemins gardait la porte. */
  function assertCaptureShape(capture,label){
    if(!capture||typeof capture!=='object')
      reject('barehands_capture_invalid',`${label} attendue sous forme d’objet.`);
    if(!REGIONS.includes(capture.region))
      reject('barehands_region_unknown',`Région inconnue : ${String(capture.region)}.`);
    if(capture.region!==REGION.BODY&&!zoneSides(capture.zone).length)
      reject('barehands_zone_invalid',`Zone de manipulation inconnue : ${String(capture.zone)}.`);
  }

  function createCapture(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_capture_invalid','Capture attendue sous forme d’objet.');
    const handTrackId=trackId(source.handTrackId,CAPTURE_IDENTIFIED);
    assertCaptureShape(source,'Capture');
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'capture',
      handTrackId,
      channel:enumOr(source.channel,PINCH_CHANNELS,PINCH_CHANNEL.PRIMARY,'barehands_pinch_channel_unknown','Canal de pincement'),
      /* Un état inconnu retombait sur `captured`, l'état latché : la capture
         ne se relâchait plus jamais (décision 13) et rien ne disait pourquoi.
         C'est exactement le repli qu'il ne faut pas faire. */
      state:enumOr(source.state,CAPTURE_STATES,CAPTURE_STATE.CAPTURED,'barehands_capture_state_unknown','État de capture'),
      objectId:source.objectId===undefined||source.objectId===null?null:String(source.objectId),
      region:source.region,
      zone:source.region===REGION.BODY?null:(source.zone===undefined||source.zone===null?null:String(source.zone)),
      t:finiteOr(source.t,0),
    });
  }

  /* Deux captures sur le même objet : ce que le couple produit.

     Le résultat est `{mode, axes, byHand, reason}`. `axes` reste l'union — ce
     que le cadre peut bouger — et `byHand` dit **quelle main tient quoi**,
     parce que l'union seule ne sait pas exprimer la décision 16 : bord droit +
     coin haut-droit et bord haut + coin bas-droit rendaient le même
     `{resize,[x,y]}` alors qu'ils demandent des attributions opposées, et le
     moteur de la Slice 06 aurait redérivé `ZONE_SIDES` chez lui.

     Chaque entrée de `byHand` porte `{sides, axes}` : les côtés du cadre que
     cette main tire, et les axes qui en découlent. Les côtés sont la donnée
     utile — deux mains peuvent tenir le même axe par deux côtés opposés
     (bas et haut), ce qui est un redimensionnement légitime, pas un conflit. */
  const attribution=sides=>Object.freeze({
    sides:Object.freeze([...sides]),
    axes:Object.freeze([...new Set(sides.map(side=>SIDE_AXIS[side]))].sort()),
  });
  const outcome=(mode,axes,byHand,reason)=>Object.freeze({
    mode,axes:Object.freeze(axes),byHand:Object.freeze(byHand),reason,
  });
  function combineCaptures(a,b){
    /* Une seule main capturée est l'état normal à une main, pas une faute. */
    if(!a||!b)return outcome(null,[],{},'missing_capture');
    assertCaptureShape(a,'Première capture');
    assertCaptureShape(b,'Seconde capture');
    const handA=trackId(a.handTrackId,CAPTURE_IDENTIFIED);
    const handB=trackId(b.handTrackId,CAPTURE_IDENTIFIED);
    /* `byHand` est indexé par identité : deux captures de la même main se
       seraient écrasées l'une l'autre, en rendant un couple plausible. */
    if(handA===handB)return outcome(null,[],{},'same_hand_twice');
    /* Décision 12. Sans `objectId`, on ne peut pas dire « le même objet » :
       deux éléments anonymes restent deux mains indépendantes, plutôt qu'un
       redimensionnement fantôme sur un cadre qui n'existe pas. */
    if(a.objectId===undefined||a.objectId===null||b.objectId===undefined||b.objectId===null)
      return outcome('independent',[],{},'object_unidentified');
    if(String(a.objectId)!==String(b.objectId))return outcome('independent',[],{},'different_objects');
    const bodyA=a.region===REGION.BODY,bodyB=b.region===REGION.BODY;
    /* Décision 8 : BODY est de l'interaction de contenu, pas une poignée de
       cadre. Deux mains dans le contenu d'une fenêtre ne déplaçaient pas du
       contenu, elles emportaient la fenêtre entière. */
    if(bodyA&&bodyB)return outcome(null,[],{},'both_captures_are_body');
    /* Décisions 10 et 14 : la zone déplace le cadre entier, le corps n'y
       participe pas — le déplacement appartient à la seule main qui tient la
       zone, et elle tire les deux axes. */
    if(bodyA||bodyB){
      const holder=bodyA?handB:handA;
      const grip=zoneSides(bodyA?b.zone:a.zone);
      return outcome('move',['x','y'],
        {[holder]:Object.freeze({sides:Object.freeze([...grip]),axes:Object.freeze(['x','y'])})},
        'body_is_not_a_resize_handle');
    }
    if(a.zone===b.zone)return outcome(null,[],{},'same_zone_rejected');
    const sidesA=zoneSides(a.zone),sidesB=zoneSides(b.zone);
    const shared=new Set(sidesA.filter(side=>sidesB.includes(side)));
    const cornerA=CORNERS.includes(a.zone),cornerB=CORNERS.includes(b.zone);
    /* Décision 16 : bord + coin qui se recouvrent — le bord possède le côté
       partagé, le coin ne garde que l'autre. Les deux axes restent donc
       manipulables, chacun par une seule main.
       Décision 17 : deux coins sur un même côté le neutralisent — ni l'un ni
       l'autre ne le garde, et son axe disparaît de l'union. */
    const keptA=sidesA.filter(side=>!shared.has(side)||(!cornerA&&cornerB));
    const keptB=sidesB.filter(side=>!shared.has(side)||(!cornerB&&cornerA));
    const ownA=attribution(keptA),ownB=attribution(keptB);
    const axes=[...new Set([...ownA.axes,...ownB.axes])].sort();
    /* Les deux mains se sont tout neutralisé : il ne reste rien à manipuler.
       Inatteignable avec des zones valides, gardé comme filet. */
    if(!axes.length)return outcome(null,[],{},'axes_all_neutralized');
    return outcome('resize',axes,{[handA]:ownA,[handB]:ownB},null);
  }

  /* Événement d'interaction : ce que le moteur de la Slice 06 publiera sous
     les noms d'`INTERACTION`. La Slice 01 en fixe la forme au lieu de laisser
     dix chaînes sans charge utile — six des sept structures de ce fichier ont
     leur fabrique, celle-ci n'en avait pas, et chaque consommateur aurait
     inventé la sienne. Comme les autres, elle se refuse plutôt que de se
     deviner : un type hors table, une main sans identité, une interaction sans
     point ou un défilement sans déplacement sont des refus codés. */
  const AXES=Object.freeze(['x','y']);
  function createInteractionEvent(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_interaction_invalid','Interaction attendue sous forme d’objet.');
    if(!INTERACTIONS.includes(source.type))
      reject('barehands_interaction_unknown',`Interaction inconnue : ${String(source.type)}.`);
    const handTrackId=trackId(source.handTrackId,'Une interaction appartient à une main identifiée.');
    /* Pixels de la fenêtre, comme `clientX`/`clientY`. */
    const x=Number(source.x),y=Number(source.y);
    if(!Number.isFinite(x)||!Number.isFinite(y))
      reject('barehands_interaction_position_missing',
        `Une interaction « ${source.type} » se produit quelque part : x et y sont requis, en pixels de la fenêtre.`);
    const dx=Number(source.dx),dy=Number(source.dy);
    if(source.type===INTERACTION.SCROLL&&!(Number.isFinite(dx)&&Number.isFinite(dy)))
      reject('barehands_interaction_delta_missing',
        'Un défilement porte son déplacement : dx et dy sont requis, en pixels de la fenêtre.');
    /* Axes contraints d'un déplacement ou d'un redimensionnement : ce que rend
       `combineCaptures().axes`, repris tel quel. */
    const axes=Object.freeze((Array.isArray(source.axes)?source.axes:[]).map(axis=>
      AXES.includes(axis)?axis:reject('barehands_axis_unknown',`Axe inconnu : ${String(axis)}.`)));
    const slot=source.slot===undefined||source.slot===null?null:Number(source.slot);
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'interaction',
      type:source.type,handTrackId,
      slot,pointerId:slot===null?null:pointerIdForSlot(slot),
      objectId:source.objectId===undefined||source.objectId===null?null:String(source.objectId),
      x,y,dx:Number.isFinite(dx)?dx:0,dy:Number.isFinite(dy)?dy:0,
      channel:enumOr(source.channel,PINCH_CHANNELS,PINCH_CHANNEL.PRIMARY,'barehands_pinch_channel_unknown','Canal de pincement'),
      /* Un événement n'est pas un réglage : `normalizeTool` tolère l'inconnu
         parce qu'il normalise un schéma stocké, une interaction le refuse. */
      tool:enumOr(source.tool,TOOLS,TOOL_DEFAULT,'barehands_tool_unknown','Outil'),
      axes,
      t:finiteOr(source.t,0),
    });
  }

  /* ------------------------------------------------------------------ 8
     Outils : « ce que la main veut dire », distinct des réglages (décision 25). */

  const TOOL=Object.freeze({POINTER:'pointer',PAN:'pan',HIGHLIGHTER:'highlighter',DRAW:'draw',SELECT:'select'});
  const TOOLS=values(TOOL);
  const TOOL_DEFAULT=TOOL.POINTER;
  const normalizeTool=value=>oneOf(value,TOOLS,TOOL_DEFAULT);

  /* ------------------------------------------------------------------ 9
     Réglages (architecture §9), versionnés et tolérants au partiel.

     Attention : le serveur ne connaît aujourd'hui que `enabled`
     (`barehands_test_mode.apply` refuse tout autre champ). `toServerPayload`
     est donc le seul chemin vers `/api/barehands` tant qu'une Slice
     ultérieure n'a pas élargi la route. */

  const SETTINGS_SCHEMA_VERSION=1;
  const SETTINGS_DEFAULTS=Object.freeze({
    schemaVersion:SETTINGS_SCHEMA_VERSION,
    enabled:false,            // Bare Hands reste éteint par défaut
    targetPreview:true,       // décision 24 : l'aperçu de cible est réglable
    /* Décision 7. **Exposé, pas encore branché** : le contrôleur de la
       Slice 02 reçoit la constante `SLEEP_TIMEOUT_MS`, pas ce champ. L'écrire
       normalise et persiste, et ne change rien au délai réel. La Slice 07
       possède les réglages et le câblera ; d'ici là, ne pas le supposer vivant. */
    sleepTimeoutMs:SLEEP_TIMEOUT_MS,
    tool:TOOL_DEFAULT,
    assistance:0.5,           // assistance de visée, bornée et sûre
    sensitivity:1,
    tutorialSeen:false,
    calibrationEnabled:true,  // décision 27 : la calibration reste optionnelle
    diagnostics:false,        // architecture §12 : enregistrement sur demande
  });
  function normalizeSettings(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    /* Le numéro de schéma était estampillé en sortie et jamais lu en entrée :
       des réglages en version 99 revenaient en version 1, champs inconnus
       jetés, sans que rien ne le dise. */
    requireSchemaVersion(source.schemaVersion,SETTINGS_SCHEMA_VERSION,'Réglages Bare Hands');
    return Object.freeze({
      schemaVersion:SETTINGS_SCHEMA_VERSION,
      enabled:bool(source.enabled,SETTINGS_DEFAULTS.enabled),
      targetPreview:bool(source.targetPreview,SETTINGS_DEFAULTS.targetPreview),
      sleepTimeoutMs:clamp(finiteOr(source.sleepTimeoutMs,SETTINGS_DEFAULTS.sleepTimeoutMs),5000,600000),
      tool:normalizeTool(source.tool),
      assistance:unit(source.assistance,SETTINGS_DEFAULTS.assistance),
      sensitivity:clamp(finiteOr(source.sensitivity,SETTINGS_DEFAULTS.sensitivity),.25,4),
      tutorialSeen:bool(source.tutorialSeen,SETTINGS_DEFAULTS.tutorialSeen),
      calibrationEnabled:bool(source.calibrationEnabled,SETTINGS_DEFAULTS.calibrationEnabled),
      diagnostics:bool(source.diagnostics,SETTINGS_DEFAULTS.diagnostics),
    });
  }
  const toServerPayload=settings=>({enabled:normalizeSettings(settings).enabled});

  /* ------------------------------------------------------------------ 10
     Profil de calibration (architecture §10, décisions 28-32).

     Un seul profil visible, des valeurs internes par main. Aucune image ni
     vidéo n'entre ici : seulement des seuils dérivés et des métriques de
     qualité (décision 32). Une fonction non calibrée vaut `null` et retombe
     sur le défaut du moteur (décision 31). */

  const PROFILE_SCHEMA_VERSION=1;
  const HAND_PROFILE_DEFAULTS=Object.freeze({
    pressRatio:null,releaseRatio:null,       // seuils de pincement dérivés, sans unité
    secondaryPressRatio:null,secondaryReleaseRatio:null,
    jitterPx:null,                           // écart-type du repos, en pixels de la fenêtre
    reachNorm:null,                          /* {x,y,w,h} atteint dans l'image, en
                                                coordonnées normalisées 0..1 comme les
                                                points d'un HandFrame — jamais des pixels */
    quality:null,                            // 0..1, confiance de la mesure
  });
  /* Les clés mesurables, lues du profil lui-même : une mesure ajoutée par une
     Slice ultérieure (`secondaryPressRatio`, décisions 21-22) compte pour
     « calibré » sans qu'on ait à y repenser. L'ancienne liste en citait trois
     sur sept, si bien que le drapeau et la donnée se contredisaient. */
  const MEASURED_KEYS=Object.freeze(Object.keys(HAND_PROFILE_DEFAULTS));
  /* Un seau par latéralité — `unknown` compris. `createHandObservation`
     retombe sur `unknown` dès que le traqueur n'étiquette pas la main, et ce
     seau manquant, toute sa calibration se perdait en silence. */
  const emptyHands=()=>{
    const hands={};
    for(const handedness of HANDEDNESSES)hands[handedness]=HAND_PROFILE_DEFAULTS;
    return Object.freeze(hands);
  };
  const PROFILE_DEFAULTS=Object.freeze({
    schemaVersion:PROFILE_SCHEMA_VERSION,
    calibrated:false,updatedAt:null,
    hands:emptyHands(),
  });

  /* Un seuil d'appui au-dessus du seuil de relâchement décrit un pincement qui
     ne peut jamais se relâcher : c'est une mesure ratée, pas une calibration
     exigeante, et elle bloquerait la main sur l'objet capturé. */
  const assertHysteresis=(press,release,label)=>{
    if(press!==null&&release!==null&&!(press<release))
      reject('barehands_profile_thresholds_invalid',
        `Calibration ${label} impossible : pressRatio (${press}) doit rester sous releaseRatio (${release}).`);
  };
  function normalizeHandProfile(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    const ratio=(value,min,max)=>{const n=Number(value);return Number.isFinite(n)?clamp(n,min,max):null};
    const pressRatio=ratio(source.pressRatio,.05,.9);
    const releaseRatio=ratio(source.releaseRatio,.05,1.5);
    const secondaryPressRatio=ratio(source.secondaryPressRatio,.05,.9);
    const secondaryReleaseRatio=ratio(source.secondaryReleaseRatio,.05,1.5);
    assertHysteresis(pressRatio,releaseRatio,'primaire');
    assertHysteresis(secondaryPressRatio,secondaryReleaseRatio,'secondaire');
    const given=source.reachNorm&&typeof source.reachNorm==='object'?source.reachNorm:null;
    const reachNorm=given?Object.freeze({x:unit(given.x,0),y:unit(given.y,0),
      w:unit(given.w,0),h:unit(given.h,0)}):null;
    /* Une portée plate ramène tout l'écran sur un point : elle défait le repli
       qu'elle devait remplacer, donc elle se refait, elle ne s'applique pas. */
    if(reachNorm&&!(reachNorm.w>0&&reachNorm.h>0))
      reject('barehands_profile_reach_invalid',
        'Portée calibrée dégénérée : largeur et hauteur doivent être positives.');
    return Object.freeze({
      pressRatio,releaseRatio,secondaryPressRatio,secondaryReleaseRatio,
      jitterPx:ratio(source.jitterPx,0,200),
      reachNorm,
      quality:source.quality===undefined||source.quality===null?null:unit(source.quality,0),
    });
  }
  function normalizeProfile(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    requireSchemaVersion(source.schemaVersion,PROFILE_SCHEMA_VERSION,'Profil de calibration');
    const given=source.hands&&typeof source.hands==='object'?source.hands:{};
    const hands={};
    for(const handedness of HANDEDNESSES)hands[handedness]=normalizeHandProfile(given[handedness]);
    /* Calibration partielle valide : une seule mesure suffit à dire
       « calibré », le reste retombant sur les défauts (décision 31). */
    const measured=HANDEDNESSES.some(handedness=>
      MEASURED_KEYS.some(key=>hands[handedness][key]!==null));
    const at=Number(source.updatedAt);
    return Object.freeze({
      schemaVersion:PROFILE_SCHEMA_VERSION,
      calibrated:measured,
      updatedAt:Number.isFinite(at)?at:null,
      hands:Object.freeze(hands),
    });
  }
  /* Un seuil calibré s'il existe, sinon celui du moteur (décision 31). Une
     latéralité ou une clé hors table se refuse : sans cela, une faute de
     frappe rendait le défaut du moteur et se lisait comme « pas calibré ». */
  const profileValue=(profile,handedness,key,fallback)=>{
    if(!HANDEDNESSES.includes(handedness))
      reject('barehands_handedness_unknown',`Latéralité inconnue : ${String(handedness)}.`);
    if(!MEASURED_KEYS.includes(key))
      reject('barehands_profile_key_unknown',`Clé de profil inconnue : ${String(key)}.`);
    const hand=profile&&profile.hands&&profile.hands[handedness];
    const value=hand?hand[key]:null;
    return value===null||value===undefined?fallback:value;
  };

  /* ------------------------------------------------------------------ 11
     Adaptateurs : le seul endroit qui connaisse un traqueur ou l'expérience
     actuelle. Rien au-dessus de cette ligne n'en dépend. */

  /* Indices MediaPipe Hand Landmarker. Table de correspondance, pas un
     contrat : un autre traqueur apporte la sienne. */
  const MEDIAPIPE_LANDMARK=Object.freeze({
    wrist:0,thumbTip:4,indexTip:8,middleMcp:9,middleTip:12,ringMcp:13,pinkyMcp:17,
  });

  /* Résultat MediaPipe → HandFrame neutre. `meta.trackIds` permet à la
     Slice 03 d'imposer son identité persistante ; sans elle, la latéralité
     sert d'identifiant de repli, exactement comme l'expérience actuelle. */
  function handFrameFromMediapipe(result,meta){
    const info=meta&&typeof meta==='object'?meta:{};
    const list=(result&&result.landmarks)||[];
    const groups=(result&&(result.handedness||result.handednesses))||[];
    const ids=Array.isArray(info.trackIds)?info.trackIds:[];
    const seen=new Set();
    const hands=[];
    list.forEach((landmarks,index)=>{
      if(!Array.isArray(landmarks)||landmarks.length<=MEDIAPIPE_LANDMARK.pinkyMcp)return;
      const category=Array.isArray(groups[index])?groups[index][0]:null;
      const label=category&&category.categoryName?String(category.categoryName).toLowerCase():'';
      /* `ids[index]` peut valoir `0` — le premier identifiant d'un traqueur
         qui numérote ses pistes. Un `||` le jetait au profit de la latéralité,
         et deux mains lues « left » échangeaient leur pointeur à l'image
         suivante. Seule l'absence fait retomber sur la latéralité. */
      const imposed=ids[index]===undefined||ids[index]===null?'':String(ids[index]).trim();
      let id=imposed||label||`hand-${index}`;
      if(seen.has(id))id=`${id}-${index}`;
      seen.add(id);
      const points={};
      for(const role of POINT_ROLES){
        const at=MEDIAPIPE_LANDMARK[role];
        if(at!==undefined&&landmarks[at])points[role]=landmarks[at];
      }
      hands.push({handTrackId:id,
        handedness:oneOf(label,HANDEDNESSES,HANDEDNESS.UNKNOWN),
        handednessConfidence:category&&Number.isFinite(Number(category.score))?Number(category.score):0,
        quality:info.quality===undefined?1:info.quality,
        points,raw:landmarks});
    });
    /* Pas de `slice(0, MAX_HANDS)` ici : `createHandFrame` refuse la main
       surnuméraire avec `barehands_too_many_hands`, et l'adaptateur la
       supprimait en silence — deux politiques opposées pour un même
       événement. Une seule tient : on refuse, pour que le jour où
       `numHands` monte au-dessus de `MAX_HANDS` cela se voie. */
    return createHandFrame({t:finiteOr(info.t,0),
      source:{width:info.width,height:info.height,aspect:info.aspect,tracker:'mediapipe_hand_landmarker'},
      hands});
  }

  /* Jetons de `JarvisBarehandsCore.createHandTracker` → identité de pointeur
     stable. Chemin de compatibilité de la Slice 01 : l'expérience de clic
     garde sa forme, mais chaque main y gagne sa fente et son `pointerId`.
     `allocator` est fourni par l'appelant pour que les fentes tiennent d'une
     image à l'autre. */
  function pointersFromCoreTokens(tokens,allocator){
    /* L'allocateur n'est **pas** optionnel. Un allocateur neuf à chaque image
       donne la fente 0 à qui passe en premier cette image-là : les deux mains
       échangent leur `pointerId` en plein glissement, et rien ne le dit. La
       signature invitait pourtant à l'omettre. */
    if(!allocator||typeof allocator.slot!=='function'||typeof allocator.retain!=='function')
      reject('barehands_allocator_required',
        'pointersFromCoreTokens exige l’allocateur de fentes de l’appelant : sans lui, les fentes ne tiennent pas d’une image à l’autre.');
    const list=Array.isArray(tokens)?tokens:[];
    /* Identités normalisées une seule fois, puis réutilisées par `retain` et
       par `slot` : les deux clés divergeaient (`"null"` contre `""`), et une
       entrée fantôme gardait la fente 0 pour toujours — la main suivante
       partait à `9002`, la compatibilité perdue en silence. */
    const ids=list.map(token=>trackId(token&&token.id,
      'Un jeton de suivi porte l’identité de sa main (token.id).'));
    allocator.retain(ids);
    return list.map((token,index)=>{
      const handTrackId=ids[index];
      const slot=allocator.slot(handTrackId);
      return Object.freeze({
        handTrackId,slot,
        pointerId:slot===null?null:pointerIdForSlot(slot),
        pointerType:POINTER_TYPE,
        /* Une seule main est « primaire » pour le DOM : la fente 0. */
        isPrimary:slot===0,
        x:finiteOr(token&&token.x,0),y:finiteOr(token&&token.y,0),
        channel:PINCH_CHANNEL.PRIMARY,
        phase:token&&token.click?PINCH_PHASE.DOWN
          :token&&token.state==='pressed'?PINCH_PHASE.MOVE
          :token&&token.state==='pinching'?PINCH_PHASE.APPROACH:PINCH_PHASE.UP,
        progress:unit(token&&token.progress,0),
      });
    });
  }

  /* Jeton de `createHandTracker` → échantillon de mouvement neutre. Même rôle
     que `pointersFromCoreTokens` pour l'identité de pointeur : le moteur garde
     sa forme de travail, le contrat possède celle qui traverse les Slices.
     `x`/`y` prennent la position **filtrée** du jeton (`filteredX`), pas son
     `x` d'affichage, qui se fige sur l'ancre pendant un pincement. */
  const motionFromCoreToken=token=>createMotionSample({
    handTrackId:token&&token.id,
    rawX:token&&token.rawX,rawY:token&&token.rawY,
    x:token&&token.filteredX,y:token&&token.filteredY,
    vxPxPerSec:token&&token.vxPxPerSec,vyPxPerSec:token&&token.vyPxPerSec,
    speedPxPerSec:token&&token.speedPxPerSec,
    stillness:token&&token.stillness,stillMs:token&&token.stillMs,
    quality:token&&token.quality,t:token&&token.t,
  });

  const api=Object.freeze({
    SCHEMA_VERSION,BareHandsSchemaError,
    LIFECYCLE,LIFECYCLES,LIVE_LIFECYCLES,isLiveLifecycle,lifecycleOfControllerState,
    SLEEP_TIMEOUT_MS,WAKE_HOLD_MS,WAKE_INTERVAL_MS,
    FAILURE_CODE,FAILURE_CODES,isFailureCode,
    MAX_HANDS,POINTER_ID_BASE,POINTER_ID_MAX,POINTER_TYPE,
    pointerIdForSlot,slotForPointerId,isBareHandsPointerId,createSlotAllocator,
    DOM,isOverlayRoot,HANDEDNESS,HANDEDNESSES,
    POINT_ROLES,createHandObservation,createHandFrame,
    HAND_QUALITY_FLOOR,isUsableQuality,createMotionSample,
    GESTURE,GESTURES,GESTURE_PHASE,GESTURE_PHASES,GESTURE_SCOPE,GESTURE_SCOPES,createGestureEvent,
    GESTURE_RULES,gestureScope,gestureAllowedDuringCapture,isGestureSuppressed,
    PINCH_CHANNEL,PINCH_CHANNELS,PINCH_FINGERS,PINCH_PHASE,PINCH_PHASES,createPinchEvent,
    PINCH_INTENT,PINCH_INTENTS,
    REGION,REGIONS,EDGE,EDGES,CORNER,CORNERS,SIDE_AXIS,ZONE_SIDES,zoneSides,zoneAxes,
    REGION_PRIORITY,regionPriority,pickRegion,FEEDBACK,FEEDBACK_TOKENS,feedbackRole,
    createTargetCandidate,ZONED_REPRESENTATIONS,hasManipulationZones,
    INTERACTION,INTERACTIONS,CAPTURE_STATE,CAPTURE_STATES,createCapture,combineCaptures,
    createInteractionEvent,
    TOOL,TOOLS,TOOL_DEFAULT,normalizeTool,
    SETTINGS_SCHEMA_VERSION,SETTINGS_DEFAULTS,normalizeSettings,toServerPayload,
    PROFILE_SCHEMA_VERSION,PROFILE_DEFAULTS,HAND_PROFILE_DEFAULTS,normalizeHandProfile,normalizeProfile,profileValue,
    adapters:Object.freeze({MEDIAPIPE_LANDMARK,handFrameFromMediapipe,pointersFromCoreTokens,motionFromCoreToken}),
  });
  root.JarvisBarehandsContracts=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
