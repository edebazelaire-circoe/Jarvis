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
    WEBGL_UNAVAILABLE:'webgl_unavailable',TRACKING_FAILED:'tracking_failed',OVERLAY_FAILED:'overlay_failed',
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
    /* Lecture de diagnostic à l'écran (architecture §12, réglage
       `diagnostics`). Éteinte, elle n'existe **pas** dans l'arbre : c'est la
       seule forme d'un réglage qu'un test puisse vérifier, la même que pour
       l'aperçu de cible (décision 3). */
    diagClass:'jh-diag',
    rootSelector:'#jarvisHands',
    tokenSelector:'#jarvisHands .jh-token',
    badgeSelector:'#jarvisHands .jh-badge',
    /* **Coque de parcours** (Slice 08, architecture §11, décision 26) : une
       surimpression plein écran, sombre et floutée, partagée par la
       calibration et le tutoriel. Racine **distincte** de `jarvisHands`, et
       c'est la seule façon que les deux soient vrais en même temps : la
       surimpression des mains est `pointer-events:none` et doit rester au
       dessus — l'utilisateur calibre **avec ses mains**, donc il doit voir son
       jeton pendant tout le parcours. */
    flowRootId:'jarvisFlow',
    flowStyleId:'jarvisFlowStyle',
    /* **La feuille des exercices**, séparée de celle de la coque (Slice 06).
       Deux feuilles parce que deux propriétaires : `flowStyleId` habille une
       coque qui ne sait rien du parcours qu'elle porte — c'est ce qui permet au
       tutoriel de la réutiliser telle quelle — tandis que celle-ci habille les
       démonstrations de main, le bandeau de phases et le champ de cibles, qui
       sont de la calibration et d'elle seule. Les fondre ferait entrer les
       gestes dans la coque par la bande. */
    flowStepsStyleId:'jarvisFlowStepsStyle',
    /* **La mise en page d'une étape, et non plus une carte** (refonte Slice 05,
       décisions 18 et 19). Le nom n'a pas bougé parce qu'il n'a jamais désigné
       une boîte : il désigne *l'étape à l'écran*. Ce qu'il porte, si. `jf-step`
       était une carte centrée de 560 px avec son fond, son ombre et son rayon
       de 20 px, et l'utilisateur l'a **refusée** en toutes lettres. C'est
       maintenant une grille qui occupe tout le cadre — bandeau en haut, scène
       au milieu, commandes en bas — sans fond, sans bordure et sans ombre à
       elle. Le voile (`flowVeilClass`) est la seule surface qui teinte. */
    flowStepClass:'jf-step',
    flowProgressClass:'jf-progress',
    /* **Le voile**, et il est une couche à lui (décision 18). Il porte le
       flou, l'assombrissement et la teinte bleue qui font que la scène JARVIS
       reste *lisible derrière* au lieu d'être recouverte de noir : c'est
       `backdrop-filter: brightness()` qui assombrit, pas une nappe opaque,
       donc la scène garde sa couleur. Séparé de la racine pour qu'il puisse
       apparaître en fondu sans emporter le texte avec lui. */
    flowVeilClass:'jf-veil',
    /* **Les cinq régions nommées** (refonte Slice 05). Elles existent pour que
       deux parcours successifs ne réinventent pas chacun leur mise en page :
       une étape décrit *ce qu'elle montre*, la coque décide *où*. `jf-header`
       est haut et large (numéro, titre, une phrase) ; `jf-stage` est le centre,
       laissé vide par la coque et rempli par l'étape ; `jf-demo` et
       `jf-exercise` sont ses deux fentes (la démonstration et la cible de
       l'exercice) ; `jf-feedback` est la bande sous la scène — sous, et jamais
       par-dessus, pour qu'un commentaire vivant ne masque pas ce qu'on
       demande de faire ; `jf-controls` est la bande secondaire des boutons. */
    flowHeaderClass:'jf-header',
    flowStageClass:'jf-stage',
    flowDemoClass:'jf-demo',
    flowExerciseClass:'jf-exercise',
    flowFeedbackClass:'jf-feedback',
    flowControlsClass:'jf-controls',
    /* Le point à viser d'une étape de visée : il est **dans la coque**, donc à
       des coordonnées que le parcours connaît — viser un élément de la page
       demanderait que la page ait un élément à viser. */
    flowTargetClass:'jf-target',
    /* La ligne vivante : ce que l'étape attend, ce qu'elle a mesuré, et
       pourquoi elle a échoué. Même rôle que `jh-note` pour l'interaction. */
    flowNoteClass:'jf-note',
    flowRootSelector:'#jarvisFlow',
  });
  /* Sans DOM dans ce module : on lit l'identifiant, on n'interroge pas l'arbre. */
  const isOverlayRoot=el=>!!el&&el.id===DOM.rootId;
  /* La coque d'un parcours est **aussi** une racine Bare Hands : les balayages
     `inert` de la page doivent l'épargner comme ils épargnent la surimpression
     des mains, sans quoi le parcours se désarmerait lui-même. */
  const isFlowRoot=el=>!!el&&el.id===DOM.flowRootId;
  const isBareHandsRoot=el=>isOverlayRoot(el)||isFlowRoot(el);

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

  const TOOL=Object.freeze({POINTER:'pointer',PAN:'pan',SELECT:'select'});
  const TOOLS=values(TOOL);
  const TOOL_DEFAULT=TOOL.POINTER;
  const normalizeTool=value=>oneOf(value,TOOLS,TOOL_DEFAULT);

  /* Ce qu'un outil **exige** de la cible. C'est la seule chose qu'un outil
     ajoute au contrat : le reste (dessiner la palette, refuser une prise) se
     déduit de cette table.

     `contextual` n'est pas une capacité de cible : c'est l'absence d'exigence,
     le mode par défaut, celui qui laisse le moteur décider selon ce qu'il y a
     sous la main (décision 25 : l'outil par défaut reste contextuel). Les
     autres valeurs sont, **littéralement**, des modes de contenu du moteur
     (`CONTENT_MODE` dans `control_center_barehands.js`) : un outil est
     « installé » exactement quand le moteur sert sa capacité. Faire des deux
     un seul vocabulaire évite la table de correspondance qui aurait dérivé.

     Ajouter un outil, c'est donc : une entrée dans `TOOL`, une dans
     `TOOL_CAPABILITY`, une dans `TOOL_LABEL` ; puis, pour qu'il soit
     **installé**, servir sa capacité dans le moteur et l'ajouter à
     `SERVED_CAPABILITIES`. Un test de parité refuse un outil sans capacité et
     une capacité servie sans outil.

     **La couche d'annotation est hors V1 (décision du Human, reprise de la
     Slice 07).** `highlighter` et `draw` étaient déclarés ici, refusés partout
     et possédés par aucune Slice : deux outils sur cinq étaient des promesses
     que rien n'allait tenir. Ils sont retirés de la table. Ce qui reste — et
     qui est la recette d'extension, pas du code mort — c'est le mécanisme qui
     **refuse** un outil déclaré sans moteur : `SERVED_CAPABILITIES`,
     `toolInstalled`, le motif de `describeTool` et, côté moteur, la porte
     `tool_not_installed`. Déclarer demain un outil `annotate` sans le servir le
     fait griser avec son motif au lieu de le rendre choisissable et inerte. */
  const TOOL_CAPABILITY_CONTEXTUAL='contextual';
  const TOOL_CAPABILITY=Object.freeze({
    [TOOL.POINTER]:TOOL_CAPABILITY_CONTEXTUAL,
    [TOOL.PAN]:'scroll',
    [TOOL.SELECT]:'select',
  });
  /* Les capacités que le moteur V1 sert réellement. La table ci-dessus ne
     déclare aujourd'hui que celles-là : la palette offre donc exactement ce
     qui marche. La liste reste **distincte** de `TOOL_CAPABILITY` parce que
     c'est elle qui rend « installé » vérifiable plutôt qu'affirmé. */
  const SERVED_CAPABILITIES=Object.freeze([TOOL_CAPABILITY_CONTEXTUAL,'scroll','select']);
  const TOOL_LABEL=Object.freeze({
    [TOOL.POINTER]:'Pointeur',[TOOL.PAN]:'Main',[TOOL.SELECT]:'Sélection',
  });
  /* Un outil **inconnu** se refuse ici : ce n'est pas un schéma stocké, c'est
     une question sur une table. `normalizeTool`, lui, garde sa tolérance
     documentée. */
  const toolCapability=value=>{
    const tool=String(value);
    const capability=TOOL_CAPABILITY[tool];
    if(capability===undefined)reject('barehands_tool_unknown',`Outil Bare Hands inconnu : ${tool}.`);
    return capability;
  };
  const toolInstalled=value=>SERVED_CAPABILITIES.includes(toolCapability(value));
  const INSTALLED_TOOLS=Object.freeze(TOOLS.filter(toolInstalled));
  /* Ce que la palette dessine, sans recopier une table : nom, capacité,
     disponibilité et **la raison** d'une indisponibilité — sans elle, un outil
     grisé est indiscernable d'une panne. */
  const describeTool=value=>{
    const tool=String(value);
    const capability=toolCapability(tool);
    const installed=SERVED_CAPABILITIES.includes(capability);
    return Object.freeze({
      id:tool,label:TOOL_LABEL[tool]||tool,capability,installed,
      reason:installed?'':'barehands_tool_not_installed',
    });
  };
  const describeTools=()=>Object.freeze(TOOLS.map(describeTool));

  /* ------------------------------------------------------------------ 9
     Réglages (architecture §9), versionnés et tolérants au partiel.

     **Version 2 (Slice 07)** : la route `/api/barehands` n'acceptait que
     `enabled` ; elle accepte maintenant les neuf réglages. `toServerPayload`
     reste le seul chemin légal vers elle, et `SETTINGS_SCHEMA_VERSION` monte
     avec `barehands_test_mode.SCHEMA_VERSION`, dans le même changement — un
     producteur et un consommateur qui ne partagent pas ce nombre ne partagent
     pas ce contrat. */

  const SETTINGS_SCHEMA_VERSION=2;
  /* Les versions précédentes que ce module sait **convertir**. La v1 portait
     les mêmes neuf clés côté page ; seule la route était plus étroite. La
     conversion est donc une re-estampille, et c'est ici — pas dans un silence —
     que la prochaine s'écrira. */
  const SETTINGS_MIGRATED_VERSIONS=Object.freeze([1]);
  const SETTINGS_DEFAULTS=Object.freeze({
    schemaVersion:SETTINGS_SCHEMA_VERSION,
    enabled:false,            // Bare Hands reste éteint par défaut
    targetPreview:true,       // décision 24 : l'aperçu de cible est réglable
    /* Décision 7. Branché par la Slice 07 : le contrôleur reçoit désormais
       cette valeur (`controller.configure`) et non plus la seule constante
       `SLEEP_TIMEOUT_MS`, qui reste le **défaut**. */
    sleepTimeoutMs:SLEEP_TIMEOUT_MS,
    tool:TOOL_DEFAULT,
    assistance:0.5,           // assistance de visée, bornée et sûre
    sensitivity:1,            // divise `clickSlopPx`/`dragSlopPx` : 1 = défauts du moteur
    /* **Compatibilité, plus personne ne l'écrit** (Slice 07B). Le parcours de
       tutoriel est retiré ; ce champ ne porte plus qu'un fait historique, et il
       reste dans le schéma pour ne pas imposer une montée de version à trois
       fichiers pour un seul booléen. Il n'a plus de case à l'écran. Condition
       de suppression : `docs/legacy/barehands-tutorial-retirement.md`. */
    tutorialSeen:false,
    calibrationEnabled:true,  // décision 27 : la calibration reste optionnelle
    diagnostics:false,        // architecture §12 : lecture à la demande
  });
  /* Bornes des réglages numériques, en un seul endroit : l'écran dessine ses
     curseurs dessus, `normalizeSettings` borne dessus, et le serveur refuse
     dessus. Trois lectures d'une table, pas trois tables.

     **Paire dangereuse, refusée au chargement du module.** `clamp(v,lo,hi)`
     rend `lo` quand `lo > hi` : une borne inversée épinglerait *tous* les
     réglages sur une seule valeur, silencieusement, et l'écran dessinerait des
     curseurs dont aucune position ne change quoi que ce soit. Il n'y a pas de
     constructeur là où vit cette table — comme `MIN_SIZE`/`MAX_SIZE` à la
     Slice 06 —, donc le refus se pose ici, au chargement. */
  const SETTINGS_BOUNDS=Object.freeze({
    sleepTimeoutMs:Object.freeze({min:5000,max:600000,step:5000}),
    assistance:Object.freeze({min:0,max:1,step:.05}),
    sensitivity:Object.freeze({min:.25,max:4,step:.05}),
  });
  for(const key of Object.keys(SETTINGS_BOUNDS)){
    const bound=SETTINGS_BOUNDS[key];
    if(!(bound.min<bound.max))
      throw new RangeError(`SETTINGS_BOUNDS.${key} : le minimum doit rester sous le maximum, sinon clamp() épingle tous les réglages sur une seule valeur sans rien dire`);
    if(!(bound.min<=SETTINGS_DEFAULTS[key]&&SETTINGS_DEFAULTS[key]<=bound.max))
      throw new RangeError(`SETTINGS_DEFAULTS.${key} tombe hors de ses propres bornes`);
  }
  /* Le nom de chaque réglage sur le fil et dans le fichier de réglages. La
     route parle `snake_case` comme tout le reste du Control Center, le contrat
     parle `camelCase` comme tout le reste de Bare Hands : une seule table fait
     le passage, dans les deux sens, et un test la parcourt aller-retour. */
  const SETTINGS_WIRE_KEYS=Object.freeze({
    enabled:'enabled',targetPreview:'target_preview',sleepTimeoutMs:'sleep_timeout_ms',
    tool:'tool',assistance:'assistance',sensitivity:'sensitivity',
    tutorialSeen:'tutorial_seen',calibrationEnabled:'calibration_enabled',diagnostics:'diagnostics',
  });
  const SETTINGS_WIRE_VERSION_KEY='schema_version';
  function normalizeSettings(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    /* Le numéro de schéma était estampillé en sortie et jamais lu en entrée :
       des réglages en version 99 revenaient en version 1, champs inconnus
       jetés, sans que rien ne le dise. C'est ce refus qui est devenu, à la
       Slice 07, la porte d'entrée de la migration : une version **connue** se
       convertit ici, toute autre se refuse. */
    if(!SETTINGS_MIGRATED_VERSIONS.includes(Number(source.schemaVersion)))
      requireSchemaVersion(source.schemaVersion,SETTINGS_SCHEMA_VERSION,'Réglages Bare Hands');
    return Object.freeze({
      schemaVersion:SETTINGS_SCHEMA_VERSION,
      enabled:bool(source.enabled,SETTINGS_DEFAULTS.enabled),
      targetPreview:bool(source.targetPreview,SETTINGS_DEFAULTS.targetPreview),
      sleepTimeoutMs:clamp(finiteOr(source.sleepTimeoutMs,SETTINGS_DEFAULTS.sleepTimeoutMs),
        SETTINGS_BOUNDS.sleepTimeoutMs.min,SETTINGS_BOUNDS.sleepTimeoutMs.max),
      tool:normalizeTool(source.tool),
      assistance:unit(source.assistance,SETTINGS_DEFAULTS.assistance),
      sensitivity:clamp(finiteOr(source.sensitivity,SETTINGS_DEFAULTS.sensitivity),
        SETTINGS_BOUNDS.sensitivity.min,SETTINGS_BOUNDS.sensitivity.max),
      tutorialSeen:bool(source.tutorialSeen,SETTINGS_DEFAULTS.tutorialSeen),
      calibrationEnabled:bool(source.calibrationEnabled,SETTINGS_DEFAULTS.calibrationEnabled),
      diagnostics:bool(source.diagnostics,SETTINGS_DEFAULTS.diagnostics),
    });
  }
  /* Le seul chemin légal vers `POST /api/barehands` : normalisé, borné,
     renommé, estampillé. Un appelant qui construirait la charge utile à la
     main enverrait des valeurs que le serveur refuserait — ou, pire, un outil
     déclaré mais sans moteur. */
  function toServerPayload(settings){
    const value=normalizeSettings(settings);
    const out={[SETTINGS_WIRE_VERSION_KEY]:SETTINGS_SCHEMA_VERSION};
    for(const key of Object.keys(SETTINGS_WIRE_KEYS))out[SETTINGS_WIRE_KEYS[key]]=value[key];
    return out;
  }
  /* Et le retour : ce que `GET`/`POST /api/barehands` rendent, à plat, relu
     dans le vocabulaire du contrat. Les champs hors table (`assets`,
     `status`, `tools`) ne sont pas des réglages et ne passent pas par ici. */
  function fromServerState(state){
    const source=state&&typeof state==='object'?state:{};
    const raw={schemaVersion:source[SETTINGS_WIRE_VERSION_KEY]};
    for(const key of Object.keys(SETTINGS_WIRE_KEYS)){
      const wire=source[SETTINGS_WIRE_KEYS[key]];
      if(wire!==undefined)raw[key]=wire;
    }
    return normalizeSettings(raw);
  }

  /* ------------------------------------------------------------------ 10
     Profil de calibration (architecture §10, décisions 28-32).

     Un seul profil visible, des valeurs internes par main. Aucune image ni
     vidéo n'entre ici : seulement des seuils dérivés et des métriques de
     qualité (décision 32). Une fonction non calibrée vaut `null` et retombe
     sur le défaut du moteur (décision 31). */

  /* **Version 2 (Slice 08)** : le parcours de calibration existe, et il apporte
     deux choses que la v1 ne pouvait pas porter — une tolérance de déplacement
     **en paumes** (`travelSlopNorm`) et le rapport par étape que la décision 31
     exige. Monter ce numéro est donc obligatoire ; la v1 se **convertit** plutôt
     que de se refuser, ses six mesures étant toutes encore valides. */
  /* **Version 3 (tâche adaptative, Slice 04)** : le profil porte en plus les
     valeurs d'essai **acceptées** (`tuning`, décision 48). Monter le numéro
     est ce qui empêche un Jarvis plus ancien de relire un profil v3 comme un
     v2, d'en jeter `tuning` en silence (liste blanche) puis de réécrire la
     calibration sans lui : il le refuse et le serveur l'archive. La v2 se
     convertit sans perte — `tuning` vide, rien d'autre ne bouge. */
  const PROFILE_SCHEMA_VERSION=3;
  /* Les versions précédentes que ce module sait convertir. Un profil v1 ne
     portait ni `travelSlopNorm` ni `stages` : les deux prennent leur défaut
     (`null` et « aucune étape connue »), ce qui est exactement ce que dit un
     profil dérivé avant que la Slice 08 n'existe. C'est la couture de
     migration, au même endroit et de la même forme que celle des réglages. */
  const PROFILE_MIGRATED_VERSIONS=Object.freeze([1,2]);
  const HAND_PROFILE_DEFAULTS=Object.freeze({
    pressRatio:null,releaseRatio:null,       // seuils de pincement dérivés, sans unité
    secondaryPressRatio:null,secondaryReleaseRatio:null,
    jitterPx:null,                           // écart-type du repos, en pixels de la fenêtre
    /* Tolérance de déplacement d'un clic, en **fraction de la largeur de
       l'image** (0..1), comme `reachNorm` et comme les points d'un `HandFrame`.
       C'est le règlement du résidu que la Slice 04 a laissé à la Slice 08.

       `clickSlopPx`/`dragSlopPx` sont en pixels de la fenêtre alors que tout le
       reste du moteur mesure en paumes : le même geste vaut ~3 fois plus de
       pixels en 1920 qu'en 640, donc la **tolérance** dépendait de la résolution
       quand la grandeur mesurée, elle, n'en dépendait pas.

       **Et la paume n'est pas la réponse**, malgré le reste du fichier. Aucune
       des deux unités n'est invariante aux deux variables, et c'est pour ça que
       la question était ouverte : la paume est invariante à la distance à la
       caméra mais pas à la résolution ; la fraction d'image est invariante à la
       résolution mais pas à la distance. Ce qu'on borne ici est un déplacement
       **à l'écran**, donc une grandeur d'écran — et la distance à laquelle
       l'utilisateur se tient est déjà dans la mesure, puisque c'est *lui* qui
       l'a faite, à sa place habituelle. La fraction d'image tue donc la
       dépendance qu'on nous a signalée et absorbe l'autre dans la mesure.
       Résidu nommé plutôt que caché : un utilisateur qui se rapproche
       franchement de la caméra après s'être calibré voit sa tolérance devenir
       étroite, et doit recalibrer. C'est strictement moins que la constante
       unique d'avant, qui valait pour toutes les résolutions et tous les
       utilisateurs à la fois.

       Application : `clickSlopPx = travelSlopNorm × largeur de la fenêtre`, et
       `dragSlopPx` garde le rapport d'usine — l'invariant `clickSlopPx <=
       dragSlopPx` (Slice 04) traverse donc intact, comme il traverse
       `sensitivity`. */
    travelSlopNorm:null,
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
  /* **Ce qui est mesuré n'est pas forcément ce qui calibre.** `quality` est
     une *métrique* et non un seuil — le parcours le dit lui-même
     (« C'est une métrique, pas un seuil : elle ne change rien au moteur ») et
     aucun `profileValue` du moteur ne la lit. Mais `deriveProfile` l'écrit pour
     **tout seau de main ayant vu une image**, si bien qu'un parcours dont les
     sept étapes ont échoué persistait `calibrated: true` : l'onglet affichait
     « Calibré le … », le toast annonçait « Bare Hands utilise vos mesures »
     (faux), la branche « sans aucune mesure » du journal ne tirait jamais, et
     « Effacer le profil » s'activait pour un profil sans une seule mesure.

     Le drapeau répond à « le moteur a-t-il été adapté à cette main ? ». Une
     métrique qui ne l'adapte pas n'a donc pas le droit de le lever. Elle reste
     mesurée, persistée, affichée et bornée comme avant — elle ne **calibre**
     simplement rien. Toute clé ajoutée demain calibre par défaut : c'est
     l'exclusion qui doit être écrite, jamais l'inclusion. */
  /* **Et `jitterPx`, `reachNorm` non plus** (tâche adaptative, Slice 04,
     READINESS D4, décision 48). Mesurés, persistés, affichés — et lus par
     **aucune** fonction du moteur. Un profil qui ne portait qu'eux se disait
     « calibré » et l'onglet annonçait « Bare Hands utilise vos mesures » pour
     un moteur inchangé. Ils rejoignent la métrique : toujours mesurés et
     rangés (rien n'est perdu à la migration), ils ne lèvent plus le drapeau.
     Le jour où un lecteur existe, la ligne se retire et le test de lecteurs
     (`TRIAL_KEYS.reader`) le prouve. */
  const METRIC_KEYS=Object.freeze(['jitterPx','reachNorm','quality']);
  const CALIBRATING_KEYS=Object.freeze(MEASURED_KEYS.filter(key=>!METRIC_KEYS.includes(key)));
  /* Un seau par latéralité — `unknown` compris. `createHandObservation`
     retombe sur `unknown` dès que le traqueur n'étiquette pas la main, et ce
     seau manquant, toute sa calibration se perdait en silence. */
  const emptyHands=()=>{
    const hands={};
    for(const handedness of HANDEDNESSES)hands[handedness]=HAND_PROFILE_DEFAULTS;
    return Object.freeze(hands);
  };
  /* Les étapes du parcours (Slice 08), dans l'ordre où elles se jouent. Le
     vocabulaire vit ici et non dans le parcours parce qu'il est **persisté** :
     la décision 31 veut qu'un profil dise quelles étapes ont abouti, et un
     rapport dont les noms changent avec l'écran ne se relit pas. */
  /* **L'ordre est celui du parcours** (Slice 07 adaptative, décision 56) :
     la liste des étapes mesurées, écrans dépliés, **est** ce vocabulaire —
     une seule liste, pas deux. Un profil range ses étapes par nom, pas par
     position : insérer `hold_release` et `drop` à leur place de jeu ne change
     la lecture d'aucun profil (une étape absente se relit `skipped`). */
  const STAGE=Object.freeze({
    NEUTRAL:'neutral',            // main posée, ouverte : le repos et son tremblement
    C_POSE:'c_pose',              // la posture de réveil, vérifiée contre la bande du moteur
    PINCH_PRIMARY:'pinch_primary',
    /* **Slice 07 adaptative** (décision 56) : tenir puis relâcher, juste
       après le pincement primaire (même doigt). */
    HOLD_RELEASE:'hold_release',  // pincer, tenir, relâcher : relâchements prématurés ou collés
    PINCH_SECONDARY:'pinch_secondary',
    AIM:'aim',                    // viser une cible à l'écran et pincer
    DRAG:'drag',                  // un court glissement
    RESIZE:'resize',              // un petit redimensionnement à deux mains
    DROP:'drop',                  // 6C (Slice 07 adaptative) : déposer la fenêtre dans une destination
    /* **Exemples négatifs** (tâche adaptative, Slice 03, décision 47) : ce
       qui n'est **pas** un clic. Un écran, deux temps, joués en dernier —
       après la fenêtre, pour que l'utilisateur sache déjà ce qu'est un geste.
       Un profil v2 qui ne les porte pas les relit `skipped`
       (`normalizeProfile`, `barehands_profile._load_stage`) ; de même un
       profil v3 enregistré avant la tenue et le dépôt. */
    NATURAL_MOTION:'natural_motion', // bouger comme en parlant : rien ne doit se déclencher
    AIM_NO_CLICK:'aim_no_click',     // viser des points sans pincer
  });
  const STAGES=values(STAGE);
  /* `skipped` n'est pas `failed` : une étape qu'on n'a pas jouée (parcours
     abandonné, deuxième main jamais vue) et une étape jouée qui n'a pas abouti
     ne demandent pas la même chose à l'utilisateur. Les confondre ferait d'un
     abandon un échec de mesure. */
  const STAGE_STATUS=Object.freeze({OK:'ok',FAILED:'failed',SKIPPED:'skipped'});
  const STAGE_STATUSES=values(STAGE_STATUS);
  /* Pourquoi une étape n'a pas abouti — liste fermée, parce que cette phrase
     est ce que l'utilisateur lit et ce qu'une trace relit. Une étape ratée
     retombe sur les défauts du moteur (décision 31) ; elle ne doit jamais
     retomber sur un nombre inventé, ni sur un silence. */
  const STAGE_REASON=Object.freeze({
    NO_HAND:'barehands_stage_no_hand',             // aucune main exploitable pendant l'étape
    TIMEOUT:'barehands_stage_timeout',             // l'échéance de l'étape est passée
    TOO_FEW_SAMPLES:'barehands_stage_too_few_samples',
    NOT_SEPARABLE:'barehands_stage_not_separable', // repos et pincement ne se distinguent pas
    OUT_OF_BAND:'barehands_stage_out_of_band',     // la mesure sort des bornes du contrat
    NEEDS_TWO_HANDS:'barehands_stage_needs_two_hands',
    CANCELLED:'barehands_stage_cancelled',         // l'utilisateur est sorti
    /* **Huitième motif, ouvert par la Slice 07** (divergence D4 de la
       READINESS). L'étape de manipulation de fenêtre est la première du
       parcours à dépendre de la **scène** : elle fait manipuler un vrai cadre
       par le vrai moteur, donc elle emprunte l'échelle de la scène
       (`JarvisScene.frames.viewport()`), seule source des pixels par unité.

       Scène éteinte, cette échelle vaut `null`. Les deux replis possibles sont
       des défauts plausibles, et le contrat les refuse tous les deux : une
       échelle inventée ferait partir le cadre six fois trop loin (c'est la
       panne que `viewport_unavailable` existe déjà pour empêcher côté moteur),
       et un faux cadre d'entraînement ferait « réussir » une étape qui n'a rien
       mesuré du vrai geste. L'étape se marque donc `skipped` — pas `failed` :
       l'utilisateur n'a rien raté, sa scène était éteinte — et le rapport le
       dit avec ce motif-ci plutôt qu'avec le silence de `null`.

       Les règles de repli partiel ne bougent pas d'un iota : une étape passée
       laisse ses clés nulles et le moteur garde ses défauts (décision 31). */
    SCENE_UNAVAILABLE:'barehands_stage_scene_unavailable',
    /* **Passer se justifie** (Slice 07 adaptative, décision 57) : une étape
       passée par l'utilisateur porte la raison qu'il a choisie dans cette
       liste fermée, et elle se range comme les autres motifs. */
    SKIP_NOT_RELEVANT:'barehands_stage_skip_not_relevant',
    SKIP_CANNOT_PERFORM:'barehands_stage_skip_cannot_perform',
    SKIP_TRACKING:'barehands_stage_skip_tracking',
    SKIP_LATER:'barehands_stage_skip_later',
  });
  const STAGE_REASONS=values(STAGE_REASON);
  /* Les raisons de passer, par leur mot court (celui que la voix envoie,
     `calibration_next_exercise.reason`), dans l'ordre de l'écran. */
  const SKIP_REASON=Object.freeze({
    not_relevant:STAGE_REASON.SKIP_NOT_RELEVANT,
    cannot_perform:STAGE_REASON.SKIP_CANNOT_PERFORM,
    tracking:STAGE_REASON.SKIP_TRACKING,
    later:STAGE_REASON.SKIP_LATER,
  });
  const SKIP_REASONS=Object.freeze(Object.keys(SKIP_REASON));
  const emptyStages=()=>{
    const stages={};
    for(const stage of STAGES)
      stages[stage]=Object.freeze({status:STAGE_STATUS.SKIPPED,reason:null,samples:0});
    return Object.freeze(stages);
  };
  /* **Les valeurs d'essai acceptées** (tâche adaptative, Slice 04,
     décision 48). Un essai non accepté ne laisse rien (décision 41) ; un essai
     **accepté** est la seule écriture d'une séance de calibration, et il se
     range ici — dans le profil, pas dans les réglages : il vient d'une mesure
     et d'un « oui » de l'utilisateur, pas d'un curseur, et `settings_set` ne
     doit pas pouvoir l'écrire.

     **Réglages du moteur entier**, pas par main : un seuil de pincement
     accepté va dans le seau d'une main **dont la paire est mesurée** (seule
     la clé essayée change), et ici pour les mains sans mesure — jamais en
     fausse paire mesurée faite d'un défaut. `null` = pas accepté, le moteur garde sa valeur composée
     (défaut, `travelSlopNorm`, `sensitivity`). Les bornes sont celles de
     l'essai (`TRIAL_KEYS`), tenues par un refus au chargement du § 12 et par
     parité avec `barehands_profile.TUNING_BOUNDS` — **sauf** `clickSlopPx` et
     `dragSlopPx`, rangés **à sensibilité 1** : la valeur effective est
     `rangée ÷ sensitivity`, donc le curseur de sensibilité garde son effet
     sur une tolérance acceptée, et la borne rangée vaut la borne d'essai
     multipliée par l'étendue de `sensitivity`. `default` sert aux paires :
     une moitié rangée se juge contre le défaut de l'autre. */
  const SENS=SETTINGS_BOUNDS.sensitivity;
  const tb=(min,max,def,integer)=>Object.freeze({min,max,default:def,integer:!!integer});
  const TUNING_BOUNDS=Object.freeze({
    /* Seuils de pincement **acceptés pour les mains sans mesure** (reprise QA,
       décision 48) : une main dont la paire est mesurée garde sa paire, mise
       à jour de la seule clé essayée ; une main sans mesure ne reçoit pas une
       fausse « paire mesurée » faite d'un défaut — le seuil accepté se range
       ici, pour le moteur entier. */
    pressRatio:tb(.1,.4,.28),
    releaseRatio:tb(.2,.8,.42),
    secondaryPressRatio:tb(.1,.4,.28),
    secondaryReleaseRatio:tb(.2,.8,.42),
    pressFrames:tb(1,4,2,true),
    releaseFrames:tb(1,5,2,true),
    releaseMs:tb(0,250,60),
    releaseDeltaRatio:tb(.05,.35,.15),
    releaseDoubtMaxMs:tb(100,800,400),
    clickSlopPx:tb(3*SENS.min,48*SENS.max,12),
    dragSlopPx:tb(6*SENS.min,104*SENS.max,26),
    clickMaxMs:tb(150,900,400),
    clickStillnessMin:tb(.2,.9,.5),
    minCutoffHz:tb(.3,4,1.2),
    betaCutoff:tb(0,.05,.012),
    stillSpeedPx:tb(8,80,28),
    moveSpeedPx:tb(200,900,420),
    targetZonePx:tb(6,30,14),
    targetZoneHoldPx:tb(8,40,20),
    targetSwitchPx:tb(0,12,8),
    targetAmbiguityMax:tb(.5,1,.8),
    targetHoldRatio:tb(.3,.8,.5),
    wakeHoldMs:tb(400,2000,1000),
    wakeScore:tb(.3,.8,.5),
    pointingEnterScore:tb(.3,.9,.5),
    pointingExitScore:tb(.1,.6,.3),
    pointingEnterMs:tb(0,600,150),
    pointingExitMs:tb(200,1000,300),
    pointingMotionFloor:tb(0,1,.4),
    pointingFoldStartPalms:tb(1.3,1.55,1.45),
    pointingFoldEndPalms:tb(1.5,1.8,1.6),
  });
  const TUNING_KEYS=Object.freeze(Object.keys(TUNING_BOUNDS));
  /* Les paires de `options()` que deux valeurs rangées peuvent inverser.
     Recopie de `TRIAL_INVARIANTS` restreinte aux clés rangées ici (le § 12 la
     vérifie au chargement : même règle, même sens). */
  const TUNING_PAIRS=Object.freeze([
    Object.freeze({low:'pressRatio',high:'releaseRatio',strict:true}),
    Object.freeze({low:'secondaryPressRatio',high:'secondaryReleaseRatio',strict:true}),
    Object.freeze({low:'clickSlopPx',high:'dragSlopPx',strict:false}),
    Object.freeze({low:'stillSpeedPx',high:'moveSpeedPx',strict:true}),
    Object.freeze({low:'targetZonePx',high:'targetZoneHoldPx',strict:false}),
    Object.freeze({low:'targetHoldRatio',high:'targetAmbiguityMax',strict:false}),
    Object.freeze({low:'pointingExitScore',high:'pointingEnterScore',strict:false}),
    Object.freeze({low:'pointingFoldStartPalms',high:'pointingFoldEndPalms',strict:true}),
  ]);
  /* L'ancre de `TRIAL_ANCHORS` : un relâchement rangé reste sous
     `wakeGapMin` (0,46), sinon un pincement en cours se lirait comme une
     posture de réveil. Recopie tenue par le § 12 au chargement. */
  const TUNING_ANCHORS=Object.freeze({releaseRatio:.46});
  /* Nom sur le fil : `snake_case`, comme le reste de la route du profil. */
  const snake=key=>key.replace(/[A-Z]/g,c=>'_'+c.toLowerCase());
  const TUNING_WIRE_KEYS=Object.freeze(Object.fromEntries(TUNING_KEYS.map(key=>[key,snake(key)])));
  const emptyTuning=()=>Object.freeze(Object.fromEntries(TUNING_KEYS.map(key=>[key,null])));
  /* Lecture **tolérante**, comme le reste du profil : bornée, `null` pour
     l'illisible, et une paire inversée tombe **en entier** (même règle que la
     demi-hystérésis de `barehands_profile._load_hand`) — l'écriture, elle,
     refuse avec son code (`barehands_profile_tuning_invalid`). */
  function normalizeTuning(raw){
    const source=raw&&typeof raw==='object'&&!Array.isArray(raw)?raw:{};
    const out={};
    for(const key of TUNING_KEYS){
      const b=TUNING_BOUNDS[key];
      const value=Object.prototype.hasOwnProperty.call(source,key)?source[key]:null;
      if(value===null||value===undefined||value===''||typeof value==='boolean'){out[key]=null;continue}
      const n=Number(value);
      if(!Number.isFinite(n)){out[key]=null;continue}
      out[key]=clamp(b.integer?Math.round(n):n,b.min,b.max);
    }
    for(const rule of TUNING_PAIRS){
      if(out[rule.low]===null&&out[rule.high]===null)continue;
      const lo=out[rule.low]===null?TUNING_BOUNDS[rule.low].default:out[rule.low];
      const hi=out[rule.high]===null?TUNING_BOUNDS[rule.high].default:out[rule.high];
      if(rule.strict?!(lo<hi):!(lo<=hi)){out[rule.low]=null;out[rule.high]=null}
    }
    for(const key of Object.keys(TUNING_ANCHORS))
      if(out[key]!==null&&!(out[key]<TUNING_ANCHORS[key]))out[key]=null;
    return Object.freeze(out);
  }
  const PROFILE_DEFAULTS=Object.freeze({
    schemaVersion:PROFILE_SCHEMA_VERSION,
    calibrated:false,updatedAt:null,
    hands:emptyHands(),
    tuning:emptyTuning(),
    /* Décision 31 : le profil dit **quelles étapes ont abouti**. Sans lui, une
       calibration partielle et une calibration complète se relisent pareil, et
       personne ne sait quelles valeurs viennent de la main de l'utilisateur. */
    stages:emptyStages(),
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
    /* **`null` est une absence, pas un zéro.** `Number(null)` vaut `0`, qui est
       fini : une valeur non mesurée était donc bornée sur le **minimum** au
       lieu de rester nulle. Sans conséquence tant que rien ne relisait un
       profil, parce que l'entrée venait toujours d'un objet partiel où la clé
       manquait (`undefined` → `NaN` → `null`). Mais un profil **persisté** est
       du JSON, et du JSON porte des `null` explicites : le relire rendait les
       sept mesures « calibrées » à leur plancher — `pressRatio` 0,05,
       `travelSlopNorm` 0,02 — donc `calibrated` vrai sans qu'une seule mesure
       ait eu lieu, et `profileValue` rendant ce plancher au lieu du défaut du
       moteur. La Slice 08 est la première à relire un profil ; c'est elle qui
       trouve la mine. */
    const ratio=(value,min,max)=>{
      if(value===null||value===undefined||value==='')return null;
      const n=Number(value);
      return Number.isFinite(n)?clamp(n,min,max):null;
    };
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
      /* Bornes réelles. Le défaut du moteur vaut 12 px, soit ~0,008 de large
         sur une fenêtre de 1440 : sous 0,002 la tolérance passe sous le
         tremblement d'une main posée et aucun clic ne se conclurait ; au-delà
         de 0,014 (~27 px en 1920, la zone sensible d'une étoile) un clic sort
         de sa cible, et le glissement — qui s'arme au double — ne s'arme plus
         qu'au bout de plusieurs centimètres de main. Le plafond valait 0,15 :
         un profil mesuré à 0,124 armait le glissement au-delà de 515 px, et
         rien ne se déplaçait plus à mains nues (21/09/2026). Borné à la
         lecture, donc un profil déjà enregistré est ramené ici sans
         recalibrer. */
      travelSlopNorm:ratio(source.travelSlopNorm,.002,.014),
      reachNorm,
      /* **Même mine que `Number(null)`, dans la seule clé que le correctif
         n'avait pas touchée.** `unit(v,0)` remplaçait toute valeur illisible
         par son **plancher** `0` — une valeur inventée, indiscernable d'une
         qualité mesurée nulle, là où la route rend `None`. Les deux moitiés du
         schéma se coerçaient donc différemment sur la même entrée. `ratio` est
         la règle de ce fichier : une valeur fausse se refuse, elle ne se
         remplace pas. */
      quality:ratio(source.quality,0,1),
    });
  }
  /* Le rapport d'une étape : un état, un motif de la liste fermée, un compte.
     Trois scalaires — rien qui puisse porter une image (décision 32). */
  function normalizeStage(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    const status=oneOf(source.status,STAGE_STATUSES,STAGE_STATUS.SKIPPED);
    const reason=STAGE_REASONS.includes(source.reason)?source.reason:null;
    const samples=Math.max(0,Math.round(Number(source.samples)||0));
    /* Un état `ok` qui porte un motif d'échec, ou un `failed` muet, dit deux
       choses contraires. Le second est le plus dangereux : « ça n'a pas
       marché » sans raison est exactement le silence que cette Slice refuse. */
    if(status===STAGE_STATUS.OK&&reason!==null)
      reject('barehands_stage_report_inconsistent',
        `Étape réussie portant un motif d'échec (${reason}).`);
    if(status===STAGE_STATUS.FAILED&&reason===null)
      reject('barehands_stage_report_inconsistent',
        'Étape échouée sans motif : un échec sans raison ne se distingue pas d’une panne.');
    return Object.freeze({status,reason,samples});
  }
  function normalizeProfile(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    /* Même couture que `normalizeSettings` : une version **connue** se
       convertit ici, toute autre se refuse. La v1 n'avait ni
       `travelSlopNorm` ni `stages` ; les deux prennent leur défaut, ce qui
       est la conversion exacte. */
    if(!PROFILE_MIGRATED_VERSIONS.includes(Number(source.schemaVersion)))
      requireSchemaVersion(source.schemaVersion,PROFILE_SCHEMA_VERSION,'Profil de calibration');
    const given=source.hands&&typeof source.hands==='object'?source.hands:{};
    const hands={};
    for(const handedness of HANDEDNESSES)hands[handedness]=normalizeHandProfile(given[handedness]);
    /* Calibration partielle valide : une seule mesure suffit à dire
       « calibré », le reste retombant sur les défauts (décision 31). */
    const tuning=normalizeTuning(source.tuning);
    /* « Calibré » ne se dit que d'une **mesure** de la main. Une valeur
       d'essai acceptée adapte le moteur, mais sans mesure : elle lève
       `tuned`, pas `calibrated` (reprise QA de la Slice 06 adaptative : un
       seul réglage gardé, sans profil, écrivait `calibrated: true` avec
       toutes les étapes « passées »). */
    const measured=HANDEDNESSES.some(handedness=>
      CALIBRATING_KEYS.some(key=>hands[handedness][key]!==null));
    const tuned=TUNING_KEYS.some(key=>tuning[key]!==null);
    /* Même mine que `ratio` ci-dessus, et elle mordait plus visiblement :
       `Number(null)` vaut 0, donc un profil jamais calibré, relu depuis son
       JSON, disait avoir été calibré le 1er janvier 1970. */
    const at=source.updatedAt===null||source.updatedAt===undefined?NaN:Number(source.updatedAt);
    const givenStages=source.stages&&typeof source.stages==='object'?source.stages:{};
    const stages={};
    for(const stage of STAGES)stages[stage]=normalizeStage(givenStages[stage]);
    return Object.freeze({
      schemaVersion:PROFILE_SCHEMA_VERSION,
      calibrated:measured,
      tuned,
      updatedAt:Number.isFinite(at)?at:null,
      hands:Object.freeze(hands),
      tuning,
      stages:Object.freeze(stages),
    });
  }
  /* **Décision 32, en structure et non en intention.**

     La promesse « aucune image, aucun point, seulement des paramètres dérivés »
     est tenue d'abord par `normalizeProfile`, qui est une **liste blanche** :
     il reconstruit le profil clé par clé, donc une clé que le schéma ne nomme
     pas n'atteint jamais le fil, et `reachNorm` est rebâtie de ses quatre
     nombres. Un appelant qui glisserait `frames:[…]` dans un profil ne
     l'exporte pas — pas parce qu'on le refuse, parce qu'on ne le **recopie
     pas**.

     Ce que cette liste blanche ne protège pas, c'est le schéma **lui-même** :
     rien n'empêchait une Slice ultérieure d'ajouter à `HAND_PROFILE_DEFAULTS`
     une clé qui accepte un objet libre, et la décision 32 tomberait sans qu'une
     ligne ne change ailleurs. La porte est donc posée là où le trou est réel —
     sur la **forme**, au chargement du module, comme l'inversion de
     `SETTINGS_BOUNDS`. Un test de payload par-dessus la liste blanche, lui,
     serait la « seconde vérité » que ce dépôt refuse : il ne pourrait pas
     échouer.

     Elle refuse tout ce qui n'est pas un nombre fini, un booléen, `null` ou un
     mot de la liste fermée — donc toute chaîne libre (une image en base64 en
     est une) et tout tableau (une suite de points en est un). */
  const DERIVED_WORDS=Object.freeze([...STAGE_STATUSES,...STAGE_REASONS]);
  function assertDerivedOnly(value,path){
    const where=path||'profil';
    if(value===null||value===undefined||typeof value==='boolean')return;
    if(typeof value==='number'){
      if(!Number.isFinite(value))
        reject('barehands_profile_not_derived',`Valeur non finie dans le profil (${where}).`);
      return;
    }
    if(typeof value==='string'){
      if(!DERIVED_WORDS.includes(value))
        reject('barehands_profile_not_derived',
          `Texte libre dans le profil (${where}) : seules des valeurs dérivées y sont permises (décision 32).`);
      return;
    }
    if(Array.isArray(value))
      reject('barehands_profile_not_derived',
        `Liste dans le profil (${where}) : une suite de points ou d'images n'y entre pas (décision 32).`);
    if(typeof value!=='object')
      reject('barehands_profile_not_derived',`Valeur de type ${typeof value} dans le profil (${where}).`);
    for(const key of Object.keys(value))assertDerivedOnly(value[key],`${where}.${key}`);
  }
  /* La sonde, et elle est **pilotée par le schéma** plutôt qu'écrite à la
     main : un profil rempli de valeurs plausibles ne dit rien d'une clé
     ajoutée demain, puisque personne n'aurait pensé à la remplir. On présente
     donc à **chaque** clé mesurable, et à chaque champ d'étape, les deux
     formes que la décision 32 interdit — une suite de points et une image en
     base64 — et on regarde ce que la normalisation en laisse passer.

     Un refus de la normalisation (`reachNorm` dégénérée, hystérésis
     impossible) est **aussi** une réponse sûre : la valeur n'est pas passée.
     C'est la seule raison pour laquelle ce `catch` est muet, et c'est écrit
     ici plutôt que sous-entendu. */
  const LEAK_PROBES=Object.freeze([
    Object.freeze([{x:.1,y:.2,z:.3}]),        // une suite de points
    'data:image/png;base64,iVBORw0KGgo=',     // une image
    Object.freeze({blob:'AAAA'}),             // un objet libre
  ]);
  assertDerivedOnly(PROFILE_DEFAULTS,'PROFILE_DEFAULTS');
  for(const probe of LEAK_PROBES){
    for(const key of MEASURED_KEYS){
      let normalized=null;
      try{normalized=normalizeProfile({hands:{left:{[key]:probe}}})}
      catch(_refused){continue}   // refusé par la liste blanche : rien n'est passé
      assertDerivedOnly(normalized,'schéma');
    }
    for(const field of ['status','reason','samples']){
      let normalized=null;
      try{normalized=normalizeProfile({stages:{neutral:{status:'ok',[field]:probe}}})}
      catch(_refused){continue}
      assertDerivedOnly(normalized,'schéma');
    }
    for(const key of TUNING_KEYS)
      assertDerivedOnly(normalizeProfile({tuning:{[key]:probe}}),'schéma');
    assertDerivedOnly(normalizeProfile({tuning:probe}),'schéma');
    let dated=null;
    try{dated=normalizeProfile({updatedAt:probe})}catch(_refused){dated=null}
    if(dated)assertDerivedOnly(dated,'schéma');
  }
  /* **Les deux champs que la décision 32 nomme elle-même comme le risque, et
     que les sondes ci-dessus n'atteignaient pas.**

     Un refus de la normalisation est une réponse sûre — la valeur n'est pas
     passée — mais ce n'est pas une *couverture* : le `continue` ci-dessus
     avalait les deux sondes qui comptent le plus, et le contrat annonçait
     pourtant « chaque champ d'étape ». `reachNorm` portée par une sonde brute
     dégénérait (`w` et `h` à zéro) et se faisait refuser avant le gate ;
     `reason` était systématiquement accompagné de `status:'ok'`, ce qui rendait
     le rapport incohérent et le faisait refuser lui aussi.

     Les deux sondes ci-dessous sont donc **bien formées** : elles traversent la
     normalisation entière et atteignent le gate à tous les coups — pas de
     `try`, parce qu'il n'y a plus rien à rattraper. `reachNorm` est la seule
     forme imbriquée du schéma (la route l'appelle « la seule poche où tout
     pourrait passer » et la garde d'une vérification de clé inconnue) et
     `reason` est le seul champ en forme de texte libre. */
  for(const probe of LEAK_PROBES){
    assertDerivedOnly(
      normalizeProfile({hands:{left:{reachNorm:{x:.1,y:.1,w:.5,h:.5,leak:probe}}}}),
      'schéma');
    /* Un statut **non `ok`** : c'est le seul par lequel un motif survit à la
       vérification de cohérence, donc le seul qui laisse la sonde arriver. */
    assertDerivedOnly(
      normalizeProfile({stages:{neutral:{status:STAGE_STATUS.SKIPPED,reason:probe}}}),
      'schéma');
  }

  /* Ce qui part sur le fil : la sortie de la liste blanche, rendue en objet
     nu. Le seul chemin légal vers la route du profil, comme `toServerPayload`
     l'est pour les réglages. */
  function toProfilePayload(profile){
    return JSON.parse(JSON.stringify(normalizeProfile(profile)));
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

  /* ------------------------------------------------------------------ 12
     Calibration adaptative et banc d'essai (tâche
     `jarvis-bare-hands-adaptive-calibration-benchmark`, Slice 01,
     décisions 34 à 42 de `docs/barehands-contracts.md` § 17).

     **Une mesure n'est pas une préférence.** La mesure dit ce qui s'est
     passé ; le retour de l'utilisateur dit si c'est acceptable ; l'hypothèse
     relie les deux et se teste par un essai borné. Quatre natures, donc quatre
     formes qui ne se mélangent pas : un fait (épisode, faux événement,
     échantillon de séance), une parole (retour), une interprétation (preuve,
     hypothèse, issue d'essai) et un réglage (patch d'essai). Aucune de ces
     formes n'a de champ où une autre pourrait se glisser.

     Ce bloc **nomme**, comme le reste du fichier : aucun moteur ne tourne ici.
     Les Slices 02 à 09 produisent ces formes. **Règle d'extension** : une
     Slice qui a besoin d'un mot de plus (un événement, une cause, une clé
     d'essai, une métrique) l'ajoute **ici**, au vocabulaire existant, avec
     son test et sa ligne au § 17 du contrat lisible — jamais dans un
     vocabulaire parallèle chez elle. Étendre est permis ; dupliquer ne l'est
     pas.

     Deux règles propres à ce bloc, au-dessus de la règle du fichier :

     - **Clé inconnue = refus.** Ces formes traversent des frontières (la voix,
       l'agent de calibration, le canal de commandes) ; une clé que le schéma ne
       nomme pas est exactement la poche par laquelle un point de main, une
       image ou une phrase libre passerait. Là où `normalizeProfile` *ne
       recopie pas*, ces fabriques *refusent* — parce qu'elles valident un
       document venu d'ailleurs, pas un schéma stocké qu'on relit.
     - **Une preuve désigne, elle ne chiffre pas.** Une preuve, une hypothèse
       et une issue d'essai citent des mesures par **référence**
       (`ep-12`, `ng-3`…), jamais par une valeur recopiée : une valeur recopiée
       par un agent est indiscernable d'une valeur inventée. */

  const SESSION_SCHEMA_VERSION=1;
  const ADAPTIVE_LIST_MAX=64;
  /* **Propriété propre, jamais héritée.** Une table fermée est un objet, et un
     objet hérite `constructor`, `toString`, `hasOwnProperty`… : `TABLE[clé]`
     ou `clé in TABLE` les trouve, et un patch `{toString: 1}` passait pour une
     clé connue. Toute lecture d'une table de ce bloc par une clé venue de
     l'extérieur passe par ici. */
  const hasOwn=(object,key)=>object!==null&&object!==undefined
    &&Object.prototype.hasOwnProperty.call(object,key);
  const ownValue=(object,key)=>hasOwn(object,key)?object[key]:undefined;

  /* Les références de séance. Un préfixe par nature, un rang : `ep-12` est le
     douzième épisode de **cette** séance, et ne veut rien dire hors d'elle —
     même idée que `ref` dans une trace (§ 14). Ce ne sont pas des identifiants
     de personne ni de machine. */
  const SESSION_REF=Object.freeze({
    SAMPLE:'se',EPISODE:'ep',NEGATIVE:'ng',FEEDBACK:'fb',EVIDENCE:'ev',
    HYPOTHESIS:'hy',TRIAL:'tr',EXERCISE:'ex',BENCHMARK:'bm',
  });
  const SESSION_REF_KINDS=values(SESSION_REF);
  const SESSION_REF_PATTERN=/^([a-z]{2})-(\d{1,9})$/;
  const isSessionRef=(value,kinds)=>{
    if(typeof value!=='string')return false;
    const m=SESSION_REF_PATTERN.exec(value);
    if(!m||!SESSION_REF_KINDS.includes(m[1]))return false;
    return !kinds||kinds.includes(m[1]);
  };
  const sessionRef=(value,kinds,label)=>{
    if(!isSessionRef(value,kinds))
      reject('barehands_session_ref_invalid',
        `${label} : référence de séance attendue (${kinds.map(k=>`${k}-N`).join(' | ')}) ; reçu ${typeof value==='string'&&value.length<=24?value:typeof value}.`);
    return value;
  };
  const optionalRef=(value,kinds,label)=>value===undefined||value===null?null:sessionRef(value,kinds,label);
  const refList=(value,kinds,label)=>{
    if(value===undefined||value===null)return Object.freeze([]);
    if(!Array.isArray(value))reject('barehands_session_ref_invalid',`${label} : liste de références attendue.`);
    if(value.length>ADAPTIVE_LIST_MAX)
      reject('barehands_session_list_too_long',`${label} : ${value.length} références, ${ADAPTIVE_LIST_MAX} au plus.`);
    const seen=new Set();
    for(const item of value){
      sessionRef(item,kinds,label);
      if(seen.has(item))reject('barehands_session_ref_duplicate',`${label} : ${item} cité deux fois.`);
      seen.add(item);
    }
    return Object.freeze(value.slice());
  };
  /* La porte des clés. Refuser plutôt que taire : voir l'en-tête du bloc. */
  const onlyKeys=(source,allowed,label)=>{
    for(const key of Object.keys(source))
      if(!allowed.includes(key))
        reject('barehands_session_key_unknown',`${label} : clé « ${key.length<=32?key:key.slice(0,32)+'…'} » hors schéma.`);
  };
  const objectOf=(raw,code,label)=>raw&&typeof raw==='object'&&!Array.isArray(raw)
    ?raw:reject(code,`${label} attendu sous forme d’objet.`);
  /* Un nombre exigé. Pas de `finiteOr` ici : dans un fait mesuré, un zéro
     inventé est la panne que ce fichier chasse depuis la Slice 08. */
  const measured=(value,code,label,min,max)=>{
    const n=typeof value==='number'?value:NaN;
    if(!Number.isFinite(n))reject(code,`${label} : nombre fini attendu.`);
    if((min!==undefined&&n<min)||(max!==undefined&&n>max))
      reject(code,`${label} hors bornes (${min} … ${max}) : ${n}.`);
    return n;
  };
  const optionalMeasured=(value,code,label,min,max)=>
    value===undefined||value===null?null:measured(value,code,label,min,max);
  const wordOf=(value,allowed,code,label)=>allowed.includes(value)
    ?value:reject(code,`${label} inconnu : ${typeof value==='string'&&value.length<=32?value:typeof value}.`);
  const optionalWord=(value,allowed,code,label)=>value===undefined||value===null?null:wordOf(value,allowed,code,label);
  const optionalSlot=value=>{
    if(value===undefined||value===null)return null;
    if(!(Number.isInteger(value)&&value>=0&&value<MAX_HANDS))
      reject('barehands_slot_out_of_range',`Fente de main hors plage : ${String(value)} (0 à ${MAX_HANDS-1}).`);
    return value;
  };

  /* Un validateur qui **rend** son verdict au lieu de lever, pour les
     appelants qui doivent répondre (un reçu, un outil d'agent) : `{ok, code,
     errors, value}`. Il enveloppe les fabriques ci-dessous sans en recopier
     une règle. */
  function checkSchema(factory,...args){
    try{return Object.freeze({ok:true,code:null,errors:Object.freeze([]),value:factory(...args)})}
    catch(error){
      if(!(error instanceof BareHandsSchemaError))throw error;
      return Object.freeze({ok:false,code:error.code,
        errors:Object.freeze([Object.freeze({key:null,code:error.code,message:error.message})]),value:null});
    }
  }

  /* ---- 12.1 Métriques : le vocabulaire commun des faits (décision 38).

     Une preuve, un delta d'essai et un résultat de banc parlent de la même
     chose avec les mêmes mots. `better` est un **fait de la métrique** (moins
     de latence est mieux), pas une formule de score : la formule appartient à
     la Slice 08. `null` = pas de sens préféré (un rapport minimal n'est ni bon
     ni mauvais en soi). */
  const METRIC_UNIT=Object.freeze({
    MS:'ms',PX:'px',PALM_RATIO:'palm_ratio',PALM_RATIO_PER_S:'palm_ratio_per_s',
    PER_MIN:'per_min',RATIO:'ratio',COUNT:'count',UNIT:'unit',
  });
  const METRIC_UNITS=values(METRIC_UNIT);
  /* `min`/`max` : bornes de la **valeur** (une latence de détection peut être
     négative, décision 35 ; un rapport tient dans 0..1 ; `null` = sans
     plafond) ; `integer` : un compte ; `perTrial` : un compte qui ne peut pas
     dépasser le nombre d'essais d'un exercice (un essai rate au plus une
     fois). */
  const metric=(unit,better,extra)=>Object.freeze({unit,better,
    min:extra&&extra.min!==undefined?extra.min:0,
    max:extra&&extra.max!==undefined?extra.max:(unit==='ratio'||unit==='unit'?1:null),
    integer:unit==='count',perTrial:!!(extra&&extra.perTrial)});
  const CALIBRATION_METRIC=Object.freeze({
    /* Épisodes de pincement (Slice 02). */
    press_latency_ms:metric('ms','lower',{min:-2000,max:5000}),
    release_latency_ms:metric('ms','lower',{min:-2000,max:5000}),
    episode_duration_ms:metric('ms',null),
    episode_min_ratio:metric('palm_ratio',null),
    open_baseline_ratio:metric('palm_ratio',null),
    closing_velocity:metric('palm_ratio_per_s',null),
    opening_velocity:metric('palm_ratio_per_s',null),
    episode_travel_px:metric('px','lower'),
    episode_quality:metric('unit','higher'),
    missed_press_rate:metric('ratio','lower'),
    missed_release_rate:metric('ratio','lower'),
    /* Exemples négatifs (Slice 03), par minute d'exercice. */
    false_press_rate:metric('per_min','lower'),
    false_secondary_press_rate:metric('per_min','lower'),
    unintended_wake_rate:metric('per_min','lower'),
    unintended_target_rate:metric('per_min','lower'),
    /* Un pointeur affiché sans intention de pointer (décision 3, Slice 03) :
       ce qui rend la cause `pointer_shown_without_intent` mesurable. */
    unintended_pointer_rate:metric('per_min','lower'),
    /* Pointeur. */
    pointer_jitter_px:metric('px','lower'),
    pointer_lag_ms:metric('ms','lower'),
    /* Cible et banc (Slices 05, 08). */
    acquisition_ms:metric('ms','lower'),
    missed_click_count:metric('count','lower',{perTrial:true}),
    wrong_target_count:metric('count','lower',{perTrial:true}),
    false_click_count:metric('count','lower'),
    premature_drop_count:metric('count','lower',{perTrial:true}),
    reacquisition_count:metric('count','lower'),
    placement_error_px:metric('px','lower'),
    target_ambiguity:metric('ratio','lower'),
    drag_success_rate:metric('ratio','higher'),
    transition_ms:metric('ms','lower'),
  });
  const CALIBRATION_METRICS=Object.freeze(Object.keys(CALIBRATION_METRIC));
  /* Comment une métrique est résumée sur un ensemble de mesures. */
  /* `rate` n'y est plus : un taux est une **métrique** (`false_press_rate`),
     pas une façon d'en résumer une autre — un résumé qu'on ne sait pas
     calculer ne se cite pas. */
  const METRIC_AGGREGATE=Object.freeze({P50:'p50',P95:'p95',MEAN:'mean',MAX:'max',COUNT:'count'});
  const METRIC_AGGREGATES=values(METRIC_AGGREGATE);

  /* ---- 12.2 Télémétrie de séance (décision 34).

     La séance de calibration garde une **courte histoire structurée** pour
     qu'une phrase comme « là ça a merdé » se relie aux événements qui la
     précèdent. Elle **réutilise la trace** (§ 14) au lieu d'en écrire une
     seconde : un échantillon de séance porte soit une image de trace
     (`readFrame` de l'enregistreur, ses listes blanches `BLANK_*`), soit un
     événement de séance de ce vocabulaire. La lecture et la validation vivent
     dans l'enregistreur (`readSessionSample`, `validateSessionSample`), qui
     possède les formes ; ce fichier possède les **mots**. */
  const SESSION_EVENT=Object.freeze({
    PINCH_PRESS:'pinch_press',PINCH_RELEASE:'pinch_release',PINCH_CANCEL:'pinch_cancel',
    CLICK:'click',DRAG_START:'drag_start',DRAG_END:'drag_end',
    TARGET_PREVIEW:'target_preview',TARGET_CHANGED:'target_changed',
    CAPTURE_START:'capture_start',CAPTURE_END:'capture_end',
    WAKE_START:'wake_start',WAKE_CONFIRMED:'wake_confirmed',WAKE_CANCELLED:'wake_cancelled',
    /* Suivre une main, vouloir pointer et montrer un curseur sont trois
       états (décision 3, Slice 03) : l'intention a son début et sa fin, le
       curseur son apparition et sa disparition, et c'est l'écart entre les
       deux qui se mesure. */
    POINTING_INTENT_START:'pointing_intent_start',POINTING_INTENT_END:'pointing_intent_end',
    POINTER_SHOWN:'pointer_shown',POINTER_HIDDEN:'pointer_hidden',
    LIFECYCLE_CHANGE:'lifecycle_change',
    /* L'instant où l'écran a **montré** l'effet (clic rendu, cadre posé) : la
       latence ressentie se lit entre le geste et ceci, pas entre le geste et
       l'événement du moteur. */
    UI_EFFECT:'ui_effect',
    FALSE_EVENT:'false_event',        // porte `falseKind`
    FEEDBACK:'feedback',              // marque le moment d'un retour ; porte `ref: fb-N`, jamais le texte
    TRIAL_APPLIED:'trial_applied',TRIAL_ROLLED_BACK:'trial_rolled_back',TRIAL_ACCEPTED:'trial_accepted',
    /* **La revue d'un exercice** (Slice 07 adaptative, décision 56) : le
       verdict montré, puis la décision de l'utilisateur. Datés sur la même
       horloge que le reste de la séance, pour qu'un retour se lise à côté de
       la revue qui l'a suscité. */
    STAGE_REVIEW:'stage_review',STAGE_VALIDATED:'stage_validated',
    STAGE_RERUN:'stage_rerun',STAGE_SKIPPED:'stage_skipped',
  });
  const SESSION_EVENTS=values(SESSION_EVENT);

  /* ---- 12.3 Épisode de pincement (décision 35).

     Un pincement intentionnel découpé en phases, au lieu d'un quantile sur
     toutes les images — qui défavorise le pincement rapide, puisqu'un clic
     vif ne laisse que peu d'images fermées. Les phases, dans l'ordre : */
  const EPISODE_PHASE=Object.freeze({
    OPEN_BASELINE:'open_baseline',CLOSING:'closing',MINIMUM:'minimum',OPENING:'opening',
  });
  /* La séquence complète revient à la ligne de base ouverte : c'est ce retour
     qui ferme l'épisode. */
  const EPISODE_PHASE_SEQUENCE=Object.freeze(['open_baseline','closing','minimum','opening','open_baseline']);
  const EPISODE_KEYS=Object.freeze(['schemaVersion','kind','ref','channel','slot','handedness','stage',
    'exerciseRef','trialRef',
    'startT','endT','durationMs','closingMs','minimumMs','openingMs',
    'baselineBefore','baselineAfter','minRatio','closingVelocity','openingVelocity',
    'pressLatencyMs','releaseLatencyMs','travelPx','stillness','quality','complete']);
  /* Bornes d'une latence de détection. **Elle peut être négative**, et c'est
     voulu : elle se mesure depuis un repère **physique** (début du minimum,
     début de la réouverture), pas depuis un seuil — donc un détecteur qui
     tranche pendant la fermeture rend une latence négative, ce qui est
     exactement ce qu'on veut voir quand on compare deux seuils. Un repère pris
     sur le seuil changerait avec le seuil qu'on teste. */
  const EPISODE_LATENCY_MIN=-2000,EPISODE_LATENCY_MAX=5000;
  /* Pourquoi un pincement **vu** n'est pas devenu un épisode (Slice 02,
     décision 43). Le segmenteur ne devine jamais la moitié qui manque : un
     épisode dont une phase n'a pas été observée est refusé sous l'un de ces
     codes, compté et dit, jamais complété par une valeur plausible. */
  const EPISODE_REJECT=Object.freeze({
    /* Le flux commence en pleine fermeture : aucune ligne de base ouverte
       n'a été vue avant. */
    NO_OPEN_BEFORE:'barehands_episode_no_open_before',
    /* Le flux finit avant que la main soit revenue à sa ligne de base. */
    NO_REOPEN:'barehands_episode_no_reopen',
    /* Un trou (images manquantes ou de qualité insuffisante) coupe l'épisode. */
    GAP:'barehands_episode_gap',
    /* Phases vues, mais le déplacement, l'immobilité ou la qualité n'ont
       aucune image lisible pendant l'épisode. */
    NOT_MEASURED:'barehands_episode_not_measured',
  });
  const EPISODE_REJECTS=values(EPISODE_REJECT);
  /* Ce qu'une étape de pincement **mesurée** doit quand même dire (Slice 02,
     décision 44) : des seuils dérivés, mais un détecteur qui n'a tranché
     aucun appui pendant l'étape (veto de profondeur, confiance de canal). */
  const EPISODE_WARNING=Object.freeze({
    PRESS_NEVER_DETECTED:'barehands_episode_press_never_detected',
    /* Des seuils dérivés, mais moins de `pressReachMin` des épisodes
       mesurés atteignent l'appui : des clics manqués à l'usage. */
    PRESS_OUT_OF_REACH:'barehands_episode_press_out_of_reach',
  });
  const EPISODE_WARNINGS=values(EPISODE_WARNING);
  function createPinchEpisode(raw){
    const code='barehands_episode_invalid';
    const s=objectOf(raw,code,'Épisode de pincement');
    onlyKeys(s,EPISODE_KEYS,'Épisode de pincement');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Épisode de pincement');
    if(s.kind!==undefined&&s.kind!=='pinch_episode')reject(code,'Épisode : kind vaut « pinch_episode ».');
    const startT=measured(s.startT,code,'startT',0);
    const endT=measured(s.endT,code,'endT',0);
    if(endT<startT)reject('barehands_episode_inconsistent','Épisode qui finit avant de commencer.');
    const durationMs=endT-startT;
    if(s.durationMs!==undefined&&Math.abs(measured(s.durationMs,code,'durationMs',0)-durationMs)>1e-6)
      reject('barehands_episode_inconsistent','durationMs ne vaut pas endT − startT.');
    const closingMs=measured(s.closingMs,code,'closingMs',0);
    const minimumMs=measured(s.minimumMs,code,'minimumMs',0);
    const openingMs=measured(s.openingMs,code,'openingMs',0);
    if(closingMs+minimumMs+openingMs>durationMs+1e-6)
      reject('barehands_episode_inconsistent','Les phases durent plus que l’épisode.');
    const baselineBefore=measured(s.baselineBefore,code,'baselineBefore',0,5);
    const baselineAfter=measured(s.baselineAfter,code,'baselineAfter',0,5);
    const minRatio=measured(s.minRatio,code,'minRatio',0,5);
    /* Un minimum au-dessus d'une ligne de base n'est pas un pincement : c'est
       une segmentation ratée, pas une mesure exigeante. */
    if(minRatio>Math.min(baselineBefore,baselineAfter))
      reject('barehands_episode_inconsistent','minRatio au-dessus d’une ligne de base ouverte.');
    return Object.freeze({
      schemaVersion:SESSION_SCHEMA_VERSION,kind:'pinch_episode',
      ref:sessionRef(s.ref,[SESSION_REF.EPISODE],'Épisode'),
      channel:wordOf(s.channel,PINCH_CHANNELS,'barehands_pinch_channel_unknown','Canal de pincement'),
      slot:optionalSlot(s.slot),
      handedness:optionalWord(s.handedness,HANDEDNESSES,code,'Latéralité'),
      stage:optionalWord(s.stage,STAGES,code,'Étape'),
      exerciseRef:optionalRef(s.exerciseRef,[SESSION_REF.EXERCISE],'Exercice'),
      /* L'essai en cours pendant l'épisode : c'est ce qui range un épisode
         « avant » ou « après » un patch. */
      trialRef:optionalRef(s.trialRef,[SESSION_REF.TRIAL],'Essai'),
      startT,endT,durationMs,closingMs,minimumMs,openingMs,
      baselineBefore,baselineAfter,minRatio,
      closingVelocity:measured(s.closingVelocity,code,'closingVelocity',0),
      openingVelocity:measured(s.openingVelocity,code,'openingVelocity',0),
      /* `null` = le détecteur n'a **jamais** tranché : c'est un pincement
         manqué (ou un relâchement collé), pas une latence nulle. */
      pressLatencyMs:optionalMeasured(s.pressLatencyMs,code,'pressLatencyMs',EPISODE_LATENCY_MIN,EPISODE_LATENCY_MAX),
      releaseLatencyMs:optionalMeasured(s.releaseLatencyMs,code,'releaseLatencyMs',EPISODE_LATENCY_MIN,EPISODE_LATENCY_MAX),
      travelPx:measured(s.travelPx,code,'travelPx',0),
      stillness:measured(s.stillness,code,'stillness',0,1),
      quality:measured(s.quality,code,'quality',0,1),
      /* Les cinq phases ont-elles été vues ? Un épisode incomplet reste un
         fait, mais la Slice 02 ne l'agrège pas comme un complet. */
      complete:typeof s.complete==='boolean'?s.complete:reject(code,'complete : booléen attendu.'),
    });
  }

  /* ---- 12.4 Exemples négatifs : ce qui n'aurait pas dû arriver (décision 36).

     Pendant un exercice de mouvement naturel ou de visée sans clic, tout
     appui, tout réveil, toute acquisition de cible est **faux** par
     construction. Le schéma seul ; la Slice 03 les produit. */
  const FALSE_EVENT=Object.freeze({
    FALSE_PRESS:'false_press',
    FALSE_SECONDARY_PRESS:'false_secondary_press',
    UNINTENDED_WAKE:'unintended_wake',
    UNINTENDED_TARGET:'unintended_target',
    UNINTENDED_POINTER:'unintended_pointer',   // curseur montré sans intention de pointer
  });
  const FALSE_EVENTS=values(FALSE_EVENT);
  const FALSE_EVENT_KEYS=Object.freeze(['schemaVersion','kind','ref','falseKind','t','slot','stage','exerciseRef','sampleRef']);
  function createFalseEvent(raw){
    const code='barehands_false_event_invalid';
    const s=objectOf(raw,code,'Faux événement');
    onlyKeys(s,FALSE_EVENT_KEYS,'Faux événement');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Faux événement');
    if(s.kind!==undefined&&s.kind!=='false_event')reject(code,'Faux événement : kind vaut « false_event ».');
    return Object.freeze({
      schemaVersion:SESSION_SCHEMA_VERSION,kind:'false_event',
      ref:sessionRef(s.ref,[SESSION_REF.NEGATIVE],'Faux événement'),
      falseKind:wordOf(s.falseKind,FALSE_EVENTS,'barehands_false_event_unknown','Faux événement'),
      t:measured(s.t,code,'t',0),
      slot:optionalSlot(s.slot),
      stage:optionalWord(s.stage,STAGES,code,'Étape'),
      exerciseRef:optionalRef(s.exerciseRef,[SESSION_REF.EXERCISE],'Exercice'),
      /* L'échantillon de séance qui le montre : la preuve est dans la
         télémétrie, pas recopiée ici. */
      sampleRef:optionalRef(s.sampleRef,[SESSION_REF.SAMPLE],'Échantillon'),
    });
  }

  /* ---- 12.5 Paramètres réglables en essai (décision 39).

     La **liste fermée** de ce qu'un essai peut toucher. Chaque clé porte ses
     bornes, son unité, son défaut (recopie de `JarvisBarehandsCore.DEFAULTS`,
     tenue par un test de parité — le bloc pur est chargé seul par node), sa
     famille, **son lecteur dans le moteur** et l'endroit où une valeur
     acceptée serait rangée.

     **Pas de lecteur, pas de calibration** (READINESS D4). `reader:null` dit
     qu'aucune fonction du moteur ne lit la valeur : la clé est nommée pour
     qu'on sache qu'elle existe dans le profil, mais `validateTrialPatch` la
     **refuse** (`barehands_trial_key_not_wired`) et `TRIAL_ADVERTISED_KEYS` ne
     la contient pas. La Slice 04 adaptative ne l'a pas branchée (aucun
     lecteur ne le justifie) : elle l'a retirée de `CALIBRATING_KEYS`.

     `reader` nomme la fonction qui **lit** la valeur ; le chemin qui l'y
     porte à chaud est `JarvisBarehands.trial` (décision 48), et chaque clé
     annoncée s'y relit chez son lecteur (`controller.options().readback`).

     `store` : où une valeur **acceptée** se range — `profile` (clé de main du
     profil, bornes miroir de `barehands_profile.HAND_BOUNDS`), `settings`
     (réglage v2), `tuning` (bloc `tuning` du profil v3, Slice 04 adaptative,
     décision 48) — ou `null` pour une clé sans lecteur, qui n'a rien à
     ranger. Les bornes d'essai tiennent **dans** celles du rangement.

     `clickSlopPx` 3 – 48 et `dragSlopPx` 6 – 104 (Slice 04 adaptative) :
     exactement l'étendue que `sensitivity` (0,25 – 4) atteignait déjà sur les
     défauts 12 / 26. Plus étroites (4 – 30 / 8 – 80), une sensibilité basse
     mettait la base effective hors bornes et **chaque** essai de glissement se
     refusait (QA : 107 / 233 px). La composition borne désormais la valeur
     effective dans ces bornes-ci (`composeEffective`). */
  const TRIAL_UNIT=Object.freeze({
    PALM_RATIO:'palm_ratio',FRAMES:'frames',MS:'ms',PX:'px',PX_PER_S:'px_per_s',
    HZ:'hz',HZ_PER_PX_PER_S:'hz_per_px_per_s',UNIT:'unit',
  });
  const TRIAL_UNITS=values(TRIAL_UNIT);
  const PARAMETER_FAMILY=Object.freeze({
    PRESS:'press',RELEASE:'release',CLICK_DRAG:'click_drag',POINTER_FILTER:'pointer_filter',
    STILLNESS:'stillness',TARGET:'target',WAKE:'wake',TRACKING:'tracking',
    /* Slice 03 adaptative (décision 46) : l'intention de pointer, qui décide
       quand un curseur se dessine. */
    POINTING:'pointing',
  });
  const PARAMETER_FAMILIES=values(PARAMETER_FAMILY);
  const tk=(family,unit,min,max,step,def,reader,store,extra)=>Object.freeze({
    family,unit,min,max,step,default:def,reader,
    store:store?Object.freeze({...store}):null,
    integer:!!(extra&&extra.integer),
    channel:extra&&extra.channel||null,
  });
  const CONTACT='createContactState ← createPinchChannel';
  /* Slice 04 adaptative (décision 48) : chaque clé lue par le moteur a
     maintenant un rangement — le profil par main pour les seuils, les
     réglages pour `assistance`, et le bloc `tuning` du profil pour le reste. */
  const TUNING=key=>({kind:'tuning',key});
  const TRIAL_KEYS=Object.freeze({
    pressRatio:tk('press','palm_ratio',.1,.4,.01,.28,
      `${CONTACT} (seuil par main : createPinchIntentEngine.handOverrides)`,{kind:'profile',key:'pressRatio',tuning:'pressRatio'},{channel:'primary'}),
    releaseRatio:tk('release','palm_ratio',.2,.8,.01,.42,
      `${CONTACT} (seuil par main : createPinchIntentEngine.handOverrides)`,{kind:'profile',key:'releaseRatio',tuning:'releaseRatio'},{channel:'primary'}),
    secondaryPressRatio:tk('press','palm_ratio',.1,.4,.01,.28,
      `${CONTACT} (canal secondaire : createPinchIntentEngine.handOverrides)`,{kind:'profile',key:'secondaryPressRatio',tuning:'secondaryPressRatio'},{channel:'secondary'}),
    secondaryReleaseRatio:tk('release','palm_ratio',.2,.8,.01,.42,
      `${CONTACT} (canal secondaire : createPinchIntentEngine.handOverrides)`,{kind:'profile',key:'secondaryReleaseRatio',tuning:'secondaryReleaseRatio'},{channel:'secondary'}),
    pressFrames:tk('press','frames',1,4,1,2,CONTACT,TUNING('pressFrames'),{integer:true}),
    releaseFrames:tk('release','frames',1,5,1,2,CONTACT,TUNING('releaseFrames'),{integer:true}),
    releaseMs:tk('release','ms',0,250,10,60,CONTACT,TUNING('releaseMs')),
    releaseDeltaRatio:tk('release','palm_ratio',.05,.35,.01,.15,CONTACT,TUNING('releaseDeltaRatio')),
    releaseDoubtMaxMs:tk('release','ms',100,800,50,400,CONTACT,TUNING('releaseDoubtMaxMs')),
    clickSlopPx:tk('click_drag','px',3,48,1,12,'createPinchChannel (intention clic/glissement)',TUNING('clickSlopPx')),
    dragSlopPx:tk('click_drag','px',6,104,1,26,'createPinchChannel (intention clic/glissement)',TUNING('dragSlopPx')),
    clickMaxMs:tk('click_drag','ms',150,900,25,400,'createPinchChannel (intention clic/glissement)',TUNING('clickMaxMs')),
    clickStillnessMin:tk('click_drag','unit',.2,.9,.05,.5,'createPinchChannel (intention clic/glissement)',TUNING('clickStillnessMin')),
    minCutoffHz:tk('pointer_filter','hz',.3,4,.1,1.2,'createPointerFilter',TUNING('minCutoffHz')),
    betaCutoff:tk('pointer_filter','hz_per_px_per_s',0,.05,.001,.012,'createPointerFilter',TUNING('betaCutoff')),
    stillSpeedPx:tk('stillness','px_per_s',8,80,2,28,'createStillness',TUNING('stillSpeedPx')),
    moveSpeedPx:tk('stillness','px_per_s',200,900,20,420,'createStillness',TUNING('moveSpeedPx')),
    /* Le **réglage** d'assistance, pas `targetAssistPx` : le rayon vaut
       `targetAssistPx × assistance × 2`, et deux boutons pour un même rayon se
       contrediraient au premier essai. */
    assistance:tk('target','unit',0,1,.05,.5,'createTargetResolver.reach (× targetAssistPx)',{kind:'settings',key:'assistance'}),
    targetZonePx:tk('target','px',6,30,1,14,'bandFor ← createTargetResolver',TUNING('targetZonePx')),
    targetZoneHoldPx:tk('target','px',8,40,1,20,'bandFor ← createTargetResolver',TUNING('targetZoneHoldPx')),
    /* Présélection bornée (Slice 05 adaptative, décision 49). L'hystérésis de
       **sélection** entre deux cibles voisines (la tenue ne cède qu'à une
       voisine plus proche d'autant), et la borne d'**ambiguïté** d'une prise
       hors cadre (`d1 / d2`). Lues par `decideTarget`, reconfigurées à chaud
       par `configureTargets`, relues par `targetOptions()`. */
    targetSwitchPx:tk('target','px',0,12,1,8,'decideTarget ← createTargetResolver',TUNING('targetSwitchPx')),
    targetAmbiguityMax:tk('target','unit',.5,1,.05,.8,'decideTarget ← createTargetResolver',TUNING('targetAmbiguityMax')),
    /* Le seuil de **lâcher** de la tenue (reprise QA, round 3), séparé du
       seuil de prise : la voisine doit être `targetHoldRatio` fois plus
       proche pour que la tenue cède. Au plus `targetAmbiguityMax`. */
    targetHoldRatio:tk('target','unit',.3,.8,.05,.5,'decideTarget ← createTargetResolver',TUNING('targetHoldRatio')),
    wakeHoldMs:tk('wake','ms',400,2000,50,1000,'createWakeDetector',TUNING('wakeHoldMs')),
    wakeScore:tk('wake','unit',.3,.8,.05,.5,'createWakeDetector',TUNING('wakeScore')),
    /* Intention de pointer (Slice 03 adaptative, décision 46) : ce qui décide
       qu'un curseur apparaît, et qui rend `pointer_shown_without_intent`
       testable. Lues par `createPointingIntent` (interaction et veille),
       reconfigurées à chaud par `configure` du contrôleur. */
    pointingEnterScore:tk('pointing','unit',.3,.9,.05,.5,'createPointingIntent',TUNING('pointingEnterScore')),
    pointingExitScore:tk('pointing','unit',.1,.6,.05,.3,'createPointingIntent',TUNING('pointingExitScore')),
    pointingEnterMs:tk('pointing','ms',0,600,25,150,'createPointingIntent',TUNING('pointingEnterMs')),
    /* Plancher à 200 ms = la cadence du guetteur de veille (`WAKE_INTERVAL_MS`) :
       plus court, chaque écart entre deux mesures de veille se lirait comme
       une perte et l'intention de réveil retomberait à chaque inférence. */
    pointingExitMs:tk('pointing','ms',200,1000,50,300,'createPointingIntent',TUNING('pointingExitMs')),
    pointingMotionFloor:tk('pointing','unit',0,1,.05,.4,'createPointingIntent',TUNING('pointingMotionFloor')),
    /* Le plafond de repli des trois autres doigts : « le C qui réveille est le
       C qui vise ». Lu par la posture de visée et par la posture du réveil,
       que le contrôleur calcule sur ses options vivantes. */
    pointingFoldStartPalms:tk('pointing','palm_ratio',1.3,1.55,.05,1.45,
      'pointingPostureScore, wakePostureScore ← createController',TUNING('pointingFoldStartPalms')),
    pointingFoldEndPalms:tk('pointing','palm_ratio',1.5,1.8,.05,1.6,
      'pointingPostureScore, wakePostureScore ← createController',TUNING('pointingFoldEndPalms')),
    /* Mesuré par la calibration, persisté, affiché — et lu par **personne**
       dans le moteur (READINESS D4). Nommé pour le dire, refusé en essai. */
    jitterPx:tk('tracking','px',0,200,1,null,null,{kind:'profile',key:'jitterPx'}),
  });
  const TRIAL_KEY_NAMES=Object.freeze(Object.keys(TRIAL_KEYS));
  const TRIAL_ADVERTISED_KEYS=Object.freeze(TRIAL_KEY_NAMES.filter(key=>TRIAL_KEYS[key].reader!==null));
  /* Les invariants de paire que le moteur **refuse** déjà (`options()`), plus
     l'hystérésis par canal que le profil refuse. Rien d'inventé : chaque ligne
     a son refus existant ; l'essai le rend lisible **avant** d'appliquer. */
  /* **Ancres** : des nombres du moteur qu'un essai ne règle pas mais contre
     lesquels une clé d'essai se juge. `wakeGapMin` doit rester au-dessus de
     `releaseRatio` pour qu'un pincement en cours ne se lise jamais comme une
     posture de réveil (`DEFAULTS` du moteur, et `cPoseScore` qui s'appuie
     dessus « par construction »). `options()` ne le refuse pas, parce qu'aucun
     réglage ne pouvait jusqu'ici approcher `releaseRatio` de 0,46 ; un essai le
     peut (borne 0,8), donc la paire se juge ici. `base` peut porter la valeur
     effective de l'ancre ; sinon, son défaut (recopie tenue par parité). */
  const TRIAL_ANCHORS=Object.freeze({
    wakeGapMin:Object.freeze({default:.46,reader:'cPoseScore ← createWakeDetector'}),
  });
  const TRIAL_INVARIANTS=Object.freeze([
    Object.freeze({low:'pressRatio',high:'releaseRatio',strict:true}),
    Object.freeze({low:'releaseRatio',high:'wakeGapMin',strict:true}),
    Object.freeze({low:'secondaryPressRatio',high:'secondaryReleaseRatio',strict:true}),
    Object.freeze({low:'clickSlopPx',high:'dragSlopPx',strict:false}),
    Object.freeze({low:'stillSpeedPx',high:'moveSpeedPx',strict:true}),
    Object.freeze({low:'targetZonePx',high:'targetZoneHoldPx',strict:false}),
    Object.freeze({low:'targetHoldRatio',high:'targetAmbiguityMax',strict:false}),
    Object.freeze({low:'pointingExitScore',high:'pointingEnterScore',strict:false}),
    Object.freeze({low:'pointingFoldStartPalms',high:'pointingFoldEndPalms',strict:true}),
  ]);
  const trialPartners=key=>Object.freeze(TRIAL_INVARIANTS
    .filter(rule=>rule.low===key||rule.high===key)
    .map(rule=>rule.low===key?rule.high:rule.low));
  /* Refus au chargement, même idiome que `SETTINGS_BOUNDS` : une table
     incohérente épinglerait silencieusement chaque essai. */
  for(const key of TRIAL_KEY_NAMES){
    const k=TRIAL_KEYS[key];
    if(!PARAMETER_FAMILIES.includes(k.family)||!TRIAL_UNITS.includes(k.unit))
      throw new RangeError(`TRIAL_KEYS.${key} : famille ou unité hors vocabulaire`);
    if(!(k.min<k.max)||!(k.step>0))
      throw new RangeError(`TRIAL_KEYS.${key} : bornes inversées ou pas nul`);
    if(k.default!==null&&!(k.min<=k.default&&k.default<=k.max))
      throw new RangeError(`TRIAL_KEYS.${key} : le défaut sort de ses propres bornes`);
    if(k.reader!==null&&k.default===null)
      throw new RangeError(`TRIAL_KEYS.${key} : une clé lue par le moteur a un défaut`);
    if(k.store&&k.store.kind==='settings'){
      const b=SETTINGS_BOUNDS[k.store.key];
      if(!b||k.min<b.min||k.max>b.max)
        throw new RangeError(`TRIAL_KEYS.${key} : bornes d'essai hors de celles du réglage ${k.store.key}`);
    }
    if(k.store&&k.store.kind==='profile'&&!MEASURED_KEYS.includes(k.store.key))
      throw new RangeError(`TRIAL_KEYS.${key} : clé de profil inconnue ${k.store.key}`);
    /* Le rangement tient l'essai : une valeur essayée puis acceptée doit
       pouvoir s'écrire. `clickSlopPx`/`dragSlopPx` se rangent à sensibilité 1
       (valeur × sensitivity), d'où l'étendue multipliée. */
    if(k.store&&(k.store.kind==='tuning'||k.store.tuning)){
      const b=ownValue(TUNING_BOUNDS,k.store.tuning||k.store.key);
      const scaled=key==='clickSlopPx'||key==='dragSlopPx';
      const lo=scaled?k.min*SENS.min:k.min,hi=scaled?k.max*SENS.max:k.max;
      if(!b||b.min>lo||b.max<hi||b.integer!==k.integer||b.default!==k.default)
        throw new RangeError(`TRIAL_KEYS.${key} : rangement tuning absent ou plus étroit que l'essai`);
    }
    /* Pas de lecteur, pas de calibration — et l'inverse : toute clé lue par
       le moteur se range quelque part, sinon « accepter » ne pourrait rien
       garder (décision 48). */
    if(k.reader!==null&&!k.store)
      throw new RangeError(`TRIAL_KEYS.${key} : clé lue par le moteur sans rangement`);
  }
  for(const key of TUNING_KEYS){
    const k=ownValue(TRIAL_KEYS,key);
    const lands=k&&k.store&&((k.store.kind==='tuning'&&k.store.key===key)||k.store.tuning===key);
    if(!lands)throw new RangeError(`PROFILE_TUNING_BOUNDS.${key} : aucune clé d'essai ne s'y range`);
  }
  for(const key of Object.keys(TUNING_ANCHORS)){
    const rule=TRIAL_INVARIANTS.find(r=>r.low===key&&ownValue(TRIAL_ANCHORS,r.high));
    if(!rule||TRIAL_ANCHORS[rule.high].default!==TUNING_ANCHORS[key])
      throw new RangeError(`TUNING_ANCHORS.${key} : diverge de TRIAL_ANCHORS`);
  }
  for(const rule of TRIAL_INVARIANTS){
    const both=TUNING_KEYS.includes(rule.low)&&TUNING_KEYS.includes(rule.high);
    const listed=TUNING_PAIRS.some(p=>p.low===rule.low&&p.high===rule.high&&p.strict===rule.strict);
    if(both!==listed)throw new RangeError(`TUNING_PAIRS : ${rule.low}/${rule.high} diverge de TRIAL_INVARIANTS`);
  }
  const trialSpec=key=>ownValue(TRIAL_KEYS,key)||ownValue(TRIAL_ANCHORS,key);
  for(const rule of TRIAL_INVARIANTS){
    const a=trialSpec(rule.low),b=trialSpec(rule.high);
    if(!a||!b)throw new RangeError(`TRIAL_INVARIANTS : clé inconnue ${rule.low}/${rule.high}`);
    if(rule.strict?!(a.default<b.default):!(a.default<=b.default))
      throw new RangeError(`TRIAL_INVARIANTS : les défauts violent ${rule.low} / ${rule.high}`);
  }

  /* Le validateur de patch. Il **rend** `{ok, code, errors, value}` — un reçu
     d'essai doit pouvoir dire tout ce qui ne va pas d'un coup, pas la première
     faute seulement. `base` = les valeurs effectives actuelles (la Slice 04 les
     fournit) ; une clé absente de `base` vaut son défaut. Les invariants se
     jugent sur `défauts ← base ← patch`, parce qu'un patch valide seul peut
     inverser une paire avec la valeur qu'il ne touche pas. */
  const TRIAL_PATCH_MAX_KEYS=8;
  function validateTrialPatch(patch,base){
    const errors=[];
    const fail=(key,code,message)=>errors.push(Object.freeze({key,code,message}));
    const done=value=>Object.freeze({ok:!errors.length,code:errors.length?errors[0].code:null,
      errors:Object.freeze(errors.slice()),value:errors.length?null:value});
    if(!patch||typeof patch!=='object'||Array.isArray(patch)){
      fail(null,'barehands_trial_patch_invalid','Patch d’essai attendu sous forme d’objet {clé: nombre}.');
      return done(null);
    }
    const keys=Object.keys(patch);
    if(!keys.length)fail(null,'barehands_trial_patch_empty','Un essai qui ne change rien n’est pas un essai.');
    if(keys.length>TRIAL_PATCH_MAX_KEYS)
      fail(null,'barehands_trial_patch_too_wide',
        `${keys.length} clés d’un coup : ${TRIAL_PATCH_MAX_KEYS} au plus, sinon l’issue ne dit plus laquelle a compté.`);
    const clean=Object.create(null);
    for(const key of keys){
      const spec=ownValue(TRIAL_KEYS,key);
      const shown=key.length<=40?key:key.slice(0,40)+'…';
      if(!spec){fail(shown,'barehands_trial_key_unknown',`Clé d’essai hors liste : ${shown}.`);continue}
      if(spec.reader===null){
        fail(key,'barehands_trial_key_not_wired',
          `${key} n’a aucun lecteur dans le moteur : l’essayer ne changerait rien (READINESS D4).`);
        continue;
      }
      const value=patch[key];
      if(typeof value!=='number'||!Number.isFinite(value)){
        fail(key,'barehands_trial_value_invalid',`${key} : nombre fini attendu (${spec.unit}).`);continue;
      }
      if(spec.integer&&!Number.isInteger(value)){
        fail(key,'barehands_trial_value_invalid',`${key} : entier attendu (${spec.unit}).`);continue;
      }
      if(value<spec.min||value>spec.max){
        fail(key,'barehands_trial_value_out_of_bounds',`${key} = ${value} hors de [${spec.min} ; ${spec.max}] ${spec.unit}.`);continue;
      }
      clean[key]=value;
    }
    const current=Object.create(null);
    for(const key of TRIAL_KEY_NAMES)current[key]=TRIAL_KEYS[key].default;
    for(const key of Object.keys(TRIAL_ANCHORS))current[key]=TRIAL_ANCHORS[key].default;
    if(base&&typeof base==='object')
      for(const key of Object.keys(base)){
        const value=base[key];
        if(trialSpec(key)&&typeof value==='number'&&Number.isFinite(value))current[key]=value;
      }
    const merged=Object.assign(Object.create(null),current,clean);
    for(const rule of TRIAL_INVARIANTS){
      if(!hasOwn(clean,rule.low)&&!hasOwn(clean,rule.high))continue;
      const lo=merged[rule.low],hi=merged[rule.high];
      if(rule.strict?!(lo<hi):!(lo<=hi))
        fail(hasOwn(clean,rule.low)?rule.low:rule.high,'barehands_trial_invariant_violated',
          `${rule.low} (${lo}) doit rester ${rule.strict?'sous':'au plus'} ${rule.high} (${hi}).`);
    }
    return done(Object.freeze(Object.assign({},clean)));
  }

  /* ---- 12.6 Retour de l'utilisateur (décision 37).

     Une taxonomie **fermée** de ce que l'utilisateur peut vouloir dire, plus
     le texte **tel qu'il l'a dit**. Les catégories sont une interprétation
     (par l'agent, ou par le bouton pressé) ; le texte est le fait. Garder les
     deux permet de réinterpréter sans redemander. Un retour n'est **jamais** un
     réglage : il contraint l'interprétation des mesures, il n'écrit rien. */
  const USER_FEEDBACK=Object.freeze({
    FINE:'fine',                                  // « là c'est nickel »
    PRESS_MISSED:'press_missed',                  // « le clic ne passe pas »
    FALSE_CLICK:'false_click',                    // « ça clique tout seul »
    RELEASE_STICKY:'release_sticky',              // « le release colle »
    RELEASE_EARLY:'release_early',                // « ça lâche tout seul »
    DRAG_STARTS_TOO_EARLY:'drag_starts_too_early',// « le drag part trop vite »
    DRAG_HARD_TO_START:'drag_hard_to_start',      // « je n'arrive pas à déplacer »
    HARD_TO_AIM:'hard_to_aim',                    // « j'arrive pas à viser »
    WRONG_TARGET:'wrong_target',                  // « il prend l'étoile d'à côté »
    JUMPY_POINTER:'jumpy_pointer',                // « ça saute »
    LAGGY:'laggy',                                // « ça lag »
    POINTER_UNWANTED:'pointer_unwanted',          // « le curseur apparaît quand je bouge juste la main »
    WAKE_HARD:'wake_hard',                        // « il ne se réveille pas »
    UNCLEAR:'unclear',                            // dit, mais pas classable : le texte reste
  });
  const USER_FEEDBACKS=values(USER_FEEDBACK);
  const FEEDBACK_SOURCE=Object.freeze({VOICE:'voice',UI:'ui'});
  const FEEDBACK_SOURCES=values(FEEDBACK_SOURCE);
  /* Borne du texte : une phrase dite après un exercice, pas un long texte. */
  const FEEDBACK_TEXT_MAX=500;
  /* Au plus trois catégories distinctes par retour : au-delà, l'interprétation
     ne discrimine plus rien, elle énumère. */
  const FEEDBACK_CATEGORIES_MAX=3;
  const FEEDBACK_KEYS=Object.freeze(['schemaVersion','kind','ref','categories','text','source','t','stage','exerciseRef']);
  function createUserFeedback(raw){
    const code='barehands_feedback_invalid';
    const s=objectOf(raw,code,'Retour utilisateur');
    onlyKeys(s,FEEDBACK_KEYS,'Retour utilisateur');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Retour utilisateur');
    if(s.kind!==undefined&&s.kind!=='user_feedback')reject(code,'Retour : kind vaut « user_feedback ».');
    if(!Array.isArray(s.categories)||!s.categories.length)
      reject(code,'Un retour porte au moins une catégorie (« unclear » si rien ne se classe).');
    if(s.categories.length>ADAPTIVE_LIST_MAX)
      reject('barehands_session_list_too_long',`Retour : ${s.categories.length} catégories citées.`);
    const categories=[...new Set(s.categories.map(c=>wordOf(c,USER_FEEDBACKS,'barehands_feedback_category_unknown','Catégorie de retour')))];
    if(categories.length>FEEDBACK_CATEGORIES_MAX)
      reject('barehands_feedback_too_many_categories',
        `${categories.length} catégories distinctes : ${FEEDBACK_CATEGORIES_MAX} au plus.`);
    /* « Nickel » et « ça colle » dans le même retour se contredisent ; « je ne
       sais pas » à côté d'une plainte précise ne dit rien de plus. */
    if(categories.length>1&&(categories.includes(USER_FEEDBACK.FINE)||categories.includes(USER_FEEDBACK.UNCLEAR)))
      reject('barehands_feedback_contradictory','« fine » et « unclear » ne se combinent avec aucune autre catégorie.');
    const text=s.text===undefined||s.text===null?'':s.text;
    if(typeof text!=='string')reject(code,'text : chaîne attendue (le texte brut dit par l’utilisateur).');
    if(text.length>FEEDBACK_TEXT_MAX)
      reject('barehands_feedback_text_too_long',`Texte de ${text.length} caractères : ${FEEDBACK_TEXT_MAX} au plus.`);
    const source=wordOf(s.source,FEEDBACK_SOURCES,'barehands_feedback_source_unknown','Source de retour');
    /* Une parole sans texte n'a pas de trace de ce qui a été dit : la voix
       garde toujours ses mots. L'UI, elle, peut n'être qu'un bouton. */
    if(source===FEEDBACK_SOURCE.VOICE&&!text.trim())
      reject(code,'Un retour vocal garde le texte dit : sans lui, la catégorie est invérifiable.');
    return Object.freeze({
      schemaVersion:SESSION_SCHEMA_VERSION,kind:'user_feedback',
      ref:sessionRef(s.ref,[SESSION_REF.FEEDBACK],'Retour'),
      categories:Object.freeze(categories),text:text.trim(),source,
      t:measured(s.t,code,'t',0),
      stage:optionalWord(s.stage,STAGES,code,'Étape'),
      exerciseRef:optionalRef(s.exerciseRef,[SESSION_REF.EXERCISE],'Exercice'),
    });
  }

  /* ---- 12.7 Preuve, hypothèse, issue d'essai (décision 38). */

  /* Les causes qu'une hypothèse peut nommer, chacune avec les **clés d'essai**
     qui la testeraient. Une cause sans clé (`tracking_quality`,
     `user_learning`, `pointer_shown_without_intent`) est légitime : elle dit
     qu'aucun réglage de cette table ne la corrige, ce qui est une réponse. */
  const HYPOTHESIS_CAUSE_KEYS=Object.freeze({
    press_threshold_too_strict:Object.freeze(['pressRatio','secondaryPressRatio','pressFrames']),
    press_threshold_too_loose:Object.freeze(['pressRatio','secondaryPressRatio','pressFrames']),
    release_threshold_too_far:Object.freeze(['releaseRatio','secondaryReleaseRatio','releaseDeltaRatio']),
    release_confirmation_too_slow:Object.freeze(['releaseFrames','releaseMs']),
    release_confirmation_too_fast:Object.freeze(['releaseFrames','releaseMs','releaseDoubtMaxMs']),
    click_drag_separation_too_tight:Object.freeze(['clickSlopPx','dragSlopPx','clickMaxMs','clickStillnessMin']),
    click_drag_separation_too_loose:Object.freeze(['clickSlopPx','dragSlopPx']),
    pointer_filter_too_smooth:Object.freeze(['minCutoffHz','betaCutoff']),
    pointer_filter_too_noisy:Object.freeze(['minCutoffHz','betaCutoff']),
    stillness_misjudged:Object.freeze(['stillSpeedPx','moveSpeedPx','clickStillnessMin']),
    target_assist_too_weak:Object.freeze(['assistance']),
    target_assist_too_strong:Object.freeze(['assistance']),
    zone_hysteresis_too_narrow:Object.freeze(['targetZonePx','targetZoneHoldPx']),
    wake_too_sensitive:Object.freeze(['wakeHoldMs','wakeScore']),
    wake_too_strict:Object.freeze(['wakeHoldMs','wakeScore']),
    /* Mesurable (`unintended_pointer_rate`, faux événement
       `unintended_pointer`), et réglable depuis la Slice 03 : l'entrée de
       l'intention de pointer (décision 46). */
    pointer_shown_without_intent:Object.freeze(['pointingEnterScore','pointingEnterMs','pointingMotionFloor']),
    tracking_quality:Object.freeze([]),
    user_learning:Object.freeze([]),
  });
  const HYPOTHESIS_CAUSES=Object.freeze(Object.keys(HYPOTHESIS_CAUSE_KEYS));
  /* Ce qu'une catégorie de retour **suggère** de regarder — un point de
     départ pour l'agent, jamais une conclusion. */
  const FEEDBACK_CAUSES=Object.freeze({
    fine:Object.freeze([]),
    press_missed:Object.freeze(['press_threshold_too_strict','tracking_quality']),
    false_click:Object.freeze(['press_threshold_too_loose','tracking_quality']),
    release_sticky:Object.freeze(['release_threshold_too_far','release_confirmation_too_slow']),
    release_early:Object.freeze(['release_confirmation_too_fast','tracking_quality']),
    drag_starts_too_early:Object.freeze(['click_drag_separation_too_tight','stillness_misjudged']),
    drag_hard_to_start:Object.freeze(['click_drag_separation_too_loose']),
    hard_to_aim:Object.freeze(['target_assist_too_weak','pointer_filter_too_noisy','pointer_filter_too_smooth','user_learning']),
    wrong_target:Object.freeze(['target_assist_too_strong','zone_hysteresis_too_narrow']),
    jumpy_pointer:Object.freeze(['pointer_filter_too_noisy','tracking_quality']),
    laggy:Object.freeze(['pointer_filter_too_smooth','release_confirmation_too_slow']),
    pointer_unwanted:Object.freeze(['pointer_shown_without_intent','wake_too_sensitive']),
    wake_hard:Object.freeze(['wake_too_strict','tracking_quality']),
    unclear:Object.freeze([]),
  });
  for(const cause of HYPOTHESIS_CAUSES)
    for(const key of HYPOTHESIS_CAUSE_KEYS[cause])
      if(!TRIAL_ADVERTISED_KEYS.includes(key))
        throw new RangeError(`HYPOTHESIS_CAUSE_KEYS.${cause} cite ${key}, qui n'est pas une clé d'essai branchée`);
  for(const category of USER_FEEDBACKS){
    const causes=FEEDBACK_CAUSES[category];
    if(!causes||causes.some(cause=>!HYPOTHESIS_CAUSES.includes(cause)))
      throw new RangeError(`FEEDBACK_CAUSES.${category} : table incomplète ou cause inconnue`);
  }

  /* Une preuve **désigne** : une métrique, son résumé, et les mesures sur
     lesquelles il se calcule. La valeur se **recalcule** à partir des
     références par du code déterministe ; elle n'est jamais écrite ici. D'où
     le refus nommé d'une clé `value` : c'est la tentation exacte. */
  const EVIDENCE_KEYS=Object.freeze(['schemaVersion','kind','ref','metric','aggregate','sourceRefs','feedbackRefs']);
  /* `ex-N` (Slice 03, décision 47) : un taux par minute d'exercice négatif
     se mesure **sur l'exercice**, pas sur un de ses faux événements. */
  const MEASUREMENT_REFS=Object.freeze([SESSION_REF.SAMPLE,SESSION_REF.EPISODE,SESSION_REF.NEGATIVE,SESSION_REF.BENCHMARK,
    SESSION_REF.EXERCISE]);
  const EMBEDDED_VALUE_KEYS=Object.freeze(['value','values','number','measure','result',
    'before','after','delta','deltas']);
  const refuseEmbeddedValue=(s,label)=>{
    for(const key of EMBEDDED_VALUE_KEYS)
      if(hasOwn(s,key))reject('barehands_evidence_value_embedded',
        `${label} : « ${key} » refusé — une preuve cite des mesures par référence, elle n’en recopie pas la valeur.`);
  };
  function createEvidence(raw){
    const code='barehands_evidence_invalid';
    const s=objectOf(raw,code,'Preuve');
    refuseEmbeddedValue(s,'Preuve');
    onlyKeys(s,EVIDENCE_KEYS,'Preuve');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Preuve');
    if(s.kind!==undefined&&s.kind!=='evidence')reject(code,'Preuve : kind vaut « evidence ».');
    const sourceRefs=refList(s.sourceRefs,MEASUREMENT_REFS,'Mesures citées');
    const feedbackRefs=refList(s.feedbackRefs,[SESSION_REF.FEEDBACK],'Retours cités');
    const metricName=optionalWord(s.metric,CALIBRATION_METRICS,'barehands_metric_unknown','Métrique');
    if(metricName!==null&&!sourceRefs.length)
      reject('barehands_evidence_unsourced','Une preuve chiffrée cite au moins une mesure.');
    if(!sourceRefs.length&&!feedbackRefs.length)
      reject('barehands_evidence_unsourced','Une preuve sans mesure ni retour cité ne prouve rien.');
    return Object.freeze({
      schemaVersion:SESSION_SCHEMA_VERSION,kind:'evidence',
      ref:sessionRef(s.ref,[SESSION_REF.EVIDENCE],'Preuve'),
      metric:metricName,
      aggregate:metricName===null
        ?(s.aggregate===undefined||s.aggregate===null?null:reject(code,'aggregate sans métrique.'))
        :wordOf(s.aggregate,METRIC_AGGREGATES,'barehands_metric_aggregate_unknown','Résumé de métrique'),
      sourceRefs,feedbackRefs,
    });
  }

  const HYPOTHESIS_STATUS=Object.freeze({OPEN:'open',SUPPORTED:'supported',WEAKENED:'weakened',REJECTED:'rejected'});
  const HYPOTHESIS_STATUSES=values(HYPOTHESIS_STATUS);
  const HYPOTHESIS_KEYS=Object.freeze(['schemaVersion','kind','ref','cause','confidence','status',
    'evidenceRefs','feedbackRefs','trialRefs']);
  function createHypothesis(raw){
    const code='barehands_hypothesis_invalid';
    const s=objectOf(raw,code,'Hypothèse');
    onlyKeys(s,HYPOTHESIS_KEYS,'Hypothèse');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Hypothèse');
    if(s.kind!==undefined&&s.kind!=='hypothesis')reject(code,'Hypothèse : kind vaut « hypothesis ».');
    const evidenceRefs=refList(s.evidenceRefs,[SESSION_REF.EVIDENCE],'Preuves');
    const feedbackRefs=refList(s.feedbackRefs,[SESSION_REF.FEEDBACK],'Retours');
    const trialRefs=refList(s.trialRefs,[SESSION_REF.TRIAL],'Essais');
    const status=wordOf(s.status,HYPOTHESIS_STATUSES,'barehands_hypothesis_status_unknown','Statut d’hypothèse');
    /* Aucune hypothèse ne naît de rien, et aucune ne change de statut sans
       raison citée : c'est ce qui empêche l'agent de revenir au même
       diagnostic après qu'un essai l'a démenti. */
    if(!evidenceRefs.length&&!feedbackRefs.length)
      reject('barehands_hypothesis_unsourced','Une hypothèse cite au moins une preuve ou un retour.');
    if(status===HYPOTHESIS_STATUS.SUPPORTED&&!evidenceRefs.length)
      reject('barehands_hypothesis_unsourced','« supported » exige au moins une preuve mesurée.');
    if((status===HYPOTHESIS_STATUS.WEAKENED||status===HYPOTHESIS_STATUS.REJECTED)&&!trialRefs.length&&!evidenceRefs.length)
      reject('barehands_hypothesis_unsourced',`« ${status} » exige l’essai ou la preuve qui l’a démentie.`);
    return Object.freeze({
      schemaVersion:SESSION_SCHEMA_VERSION,kind:'hypothesis',
      ref:sessionRef(s.ref,[SESSION_REF.HYPOTHESIS],'Hypothèse'),
      cause:wordOf(s.cause,HYPOTHESIS_CAUSES,'barehands_hypothesis_cause_unknown','Cause'),
      confidence:measured(s.confidence,'barehands_hypothesis_confidence_invalid','confidence',0,1),
      status,evidenceRefs,feedbackRefs,trialRefs,
    });
  }

  const TRIAL_VERDICT=Object.freeze({IMPROVED:'improved',NO_CHANGE:'no_change',WORSE:'worse',INCONCLUSIVE:'inconclusive'});
  const TRIAL_VERDICTS=values(TRIAL_VERDICT);
  /* **L'agent cite, le code chiffre.** L'issue qu'un agent (ou l'UI)
     écrit ne porte **aucun nombre** : un verdict, les comparaisons voulues
     (`{metric, aggregate}`), et les mesures d'avant et d'après par
     référence. Les nombres viennent de `computeTrialDeltas`, une fonction
     déterministe qui lit un **jeu de mesures** (`createMeasurementSet` :
     référence → valeurs de métriques) que produisent les moteurs des
     Slices 02 à 05 et que la Slice 04/06 possède. `resolveTrialOutcome` fait
     les deux et refuse un verdict que les deltas calculés contredisent. */
  const TRIAL_COMPARISON_KEYS=Object.freeze(['metric','aggregate']);
  const TRIAL_OUTCOME_KEYS=Object.freeze(['schemaVersion','kind','trialRef','verdict','comparisons',
    'beforeRefs','afterRefs','hypothesisRefs','feedbackRefs']);
  function createTrialOutcome(raw){
    const code='barehands_trial_outcome_invalid';
    const s=objectOf(raw,code,'Issue d’essai');
    refuseEmbeddedValue(s,'Issue d’essai');
    onlyKeys(s,TRIAL_OUTCOME_KEYS,'Issue d’essai');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Issue d’essai');
    if(s.kind!==undefined&&s.kind!=='trial_outcome')reject(code,'Issue : kind vaut « trial_outcome ».');
    if(s.comparisons!==undefined&&!Array.isArray(s.comparisons))reject(code,'comparisons : liste attendue.');
    const given=s.comparisons||[];
    if(given.length>ADAPTIVE_LIST_MAX)reject('barehands_session_list_too_long','Trop de comparaisons.');
    const seen=new Set();
    const comparisons=Object.freeze(given.map(item=>{
      const c=objectOf(item,code,'Comparaison');
      refuseEmbeddedValue(c,'Comparaison');
      onlyKeys(c,TRIAL_COMPARISON_KEYS,'Comparaison');
      const metricName=wordOf(c.metric,CALIBRATION_METRICS,'barehands_metric_unknown','Métrique');
      const aggregate=wordOf(c.aggregate,METRIC_AGGREGATES,'barehands_metric_aggregate_unknown','Résumé de métrique');
      const key=`${metricName}/${aggregate}`;
      if(seen.has(key))reject('barehands_session_ref_duplicate',`Comparaison ${key} en double.`);
      seen.add(key);
      return Object.freeze({metric:metricName,aggregate});
    }));
    const beforeRefs=refList(s.beforeRefs,MEASUREMENT_REFS,'Mesures avant');
    const afterRefs=refList(s.afterRefs,MEASUREMENT_REFS,'Mesures après');
    /* La même mesure des deux côtés rend un delta nul par construction : il
       ne compare rien, et il le ferait passer pour « aucun changement ». */
    const overlap=beforeRefs.filter(ref=>afterRefs.includes(ref));
    if(overlap.length)
      reject('barehands_trial_refs_overlap',`Mesures citées avant et après : ${overlap.slice(0,4).join(', ')}.`);
    if(comparisons.length&&(!beforeRefs.length||!afterRefs.length))
      reject('barehands_evidence_unsourced','Une comparaison cite des mesures d’avant et d’après.');
    const feedbackRefs=refList(s.feedbackRefs,[SESSION_REF.FEEDBACK],'Retours');
    const verdict=wordOf(s.verdict,TRIAL_VERDICTS,'barehands_trial_verdict_unknown','Verdict d’essai');
    /* « mieux » ou « pire » sans une comparaison ni une parole citée est une
       opinion. `inconclusive` et `no_change` peuvent être muets : ne rien voir
       est un résultat. */
    if((verdict===TRIAL_VERDICT.IMPROVED||verdict===TRIAL_VERDICT.WORSE)&&!comparisons.length&&!feedbackRefs.length)
      reject('barehands_evidence_unsourced',`« ${verdict} » exige une comparaison mesurée ou un retour cité.`);
    return Object.freeze({
      schemaVersion:SESSION_SCHEMA_VERSION,kind:'trial_outcome',
      trialRef:sessionRef(s.trialRef,[SESSION_REF.TRIAL],'Essai'),
      verdict,comparisons,beforeRefs,afterRefs,
      hypothesisRefs:refList(s.hypothesisRefs,[SESSION_REF.HYPOTHESIS],'Hypothèses'),
      feedbackRefs,
    });
  }

  /* Le jeu de mesures : `{ "ep-3": {press_latency_ms: 42, …}, … }`. Des
     métriques de la table, des valeurs dans leurs bornes ou `null`. C'est la
     **seule** entrée chiffrée des calculs ci-dessous ; elle vient des
     moteurs, jamais d'un agent. */
  const MEASUREMENT_SET_MAX=10000;
  function createMeasurementSet(raw){
    const code='barehands_measurement_invalid';
    const s=objectOf(raw,code,'Jeu de mesures');
    const refs=Object.keys(s);
    if(refs.length>MEASUREMENT_SET_MAX)
      reject('barehands_session_list_too_long',`${refs.length} mesures : ${MEASUREMENT_SET_MAX} au plus.`);
    const out=Object.create(null);
    for(const ref of refs){
      sessionRef(ref,MEASUREMENT_REFS,'Mesure');
      const record=objectOf(s[ref],code,`Mesure ${ref}`);
      onlyKeys(record,CALIBRATION_METRICS,`Mesure ${ref}`);
      const values={};
      for(const name of Object.keys(record)){
        const spec=CALIBRATION_METRIC[name];
        const value=optionalMeasured(record[name],code,`${ref}.${name}`,spec.min,
          spec.max===null?undefined:spec.max);
        if(value!==null&&spec.integer&&!Number.isInteger(value))reject(code,`${ref}.${name} : entier attendu.`);
        values[name]=value;
      }
      out[ref]=Object.freeze(values);
    }
    return Object.freeze(out);
  }
  /* Le quantile **linéaire** — le même que celui du rejeu (§ 14), qui le
     lit d'ici : deux définitions de « p95 » dans un dépôt rendent deux
     nombres sous un seul mot. */
  function quantile(values,q){
    const sorted=values.filter(Number.isFinite).slice().sort((a,b)=>a-b);
    if(!sorted.length)return null;
    if(sorted.length===1)return sorted[0];
    const at=(sorted.length-1)*q;
    const low=Math.floor(at),high=Math.ceil(at);
    return low===high?sorted[low]:sorted[low]+(sorted[high]-sorted[low])*(at-low);
  }
  /* Une métrique résumée sur des mesures citées. Une référence absente du
     jeu se refuse (`barehands_measurement_missing`) : une mesure citée et
     introuvable n'est pas une mesure vide. Aucune valeur → `null`, sauf
     `count` qui vaut alors 0 — c'est un compte, pas une mesure. */
  function aggregateMetric(metricName,aggregate,refs,set){
    wordOf(metricName,CALIBRATION_METRICS,'barehands_metric_unknown','Métrique');
    wordOf(aggregate,METRIC_AGGREGATES,'barehands_metric_aggregate_unknown','Résumé de métrique');
    const values=[];
    for(const ref of refs){
      if(!hasOwn(set,ref))reject('barehands_measurement_missing',`Mesure citée introuvable : ${ref}.`);
      const value=ownValue(set[ref],metricName);
      if(typeof value==='number'&&Number.isFinite(value))values.push(value);
    }
    if(aggregate===METRIC_AGGREGATE.COUNT)return values.length;
    if(!values.length)return null;
    if(aggregate===METRIC_AGGREGATE.P50)return quantile(values,.5);
    if(aggregate===METRIC_AGGREGATE.P95)return quantile(values,.95);
    if(aggregate===METRIC_AGGREGATE.MAX)return Math.max(...values);
    return values.reduce((a,b)=>a+b,0)/values.length;
  }
  /* Le sens d'un delta, lu sur `better` : `better`, `worse`, `same`, ou `null`
     (métrique sans sens préféré, ou un côté non mesuré). `count` n'a pas de
     sens : plus de mesures n'est ni mieux ni pire. */
  function deltaDirection(metricName,aggregate,delta){
    const better=CALIBRATION_METRIC[metricName].better;
    if(delta===null||better===null||aggregate===METRIC_AGGREGATE.COUNT)return null;
    if(delta===0)return 'same';
    return (delta<0)===(better==='lower')?'better':'worse';
  }
  function computeTrialDeltas(outcome,measurements){
    const o=createTrialOutcome(outcome);
    const set=createMeasurementSet(measurements);
    return Object.freeze(o.comparisons.map(({metric:metricName,aggregate})=>{
      const before=aggregateMetric(metricName,aggregate,o.beforeRefs,set);
      const after=aggregateMetric(metricName,aggregate,o.afterRefs,set);
      const delta=before===null||after===null?null:after-before;
      return Object.freeze({metric:metricName,aggregate,before,after,delta,
        direction:deltaDirection(metricName,aggregate,delta)});
    }));
  }
  /* Les plaintes qui **visent** une cause : l'inverse de `FEEDBACK_CAUSES`.
     `release_sticky` vise `release_threshold_too_far` et
     `release_confirmation_too_slow` ; une hypothèse sur l'une de ces causes a
     donc été ouverte par cette plainte-là, et c'est son absence qui dit
     « mieux ». */
  const COMPLAINTS=Object.freeze(USER_FEEDBACKS.filter(c=>c!==USER_FEEDBACK.FINE&&c!==USER_FEEDBACK.UNCLEAR));
  const complaintsForCause=cause=>COMPLAINTS.filter(c=>FEEDBACK_CAUSES[c].includes(cause));
  const RESOLVE_CONTEXT_KEYS=Object.freeze(['appliedAt','feedback','hypotheses']);

  /* L'issue **résolue** — la seule qu'on ait le droit de ranger ou de faire
     peser sur la confiance d'une hypothèse ; `createTrialOutcome` seul ne
     vérifie qu'une forme.

     `context` = `{appliedAt, feedback, hypotheses}` : l'instant (ms de séance)
     où l'essai a été appliqué, et les **enregistrements** des retours et des
     hypothèses que l'issue cite. Une référence citée ne compte qu'une fois
     retrouvée : un retour absent se refuse (`barehands_trial_feedback_missing`),
     un retour antérieur à l'essai aussi (`barehands_trial_feedback_stale` —
     il parle de l'ancien réglage), une hypothèse citée introuvable aussi
     (`barehands_trial_hypothesis_missing`).

     **Les plaintes visées** : celles qui visent la cause d'une hypothèse
     citée ; sans hypothèse citée, toutes les plaintes. Un retour cité
     **soutient** :
     - `improved` s'il vaut `fine`, ou s'il ne contient **aucune** plainte
       visée (le symptôme qui a ouvert l'hypothèse a disparu) — `unclear` seul
       ne soutient rien ;
     - `worse` s'il contient une plainte visée.
     Un retour cité qui dit le contraire du verdict (une plainte visée sous
     `improved`, `fine` sous `worse`) se refuse
     (`barehands_trial_feedback_contradicts`).

     **Les deltas** : seuls ceux qui ont un sens comptent (`better`/`worse`) ;
     un côté non mesuré ou un `count` n'en a pas. `improved` exige un delta
     `better` ou un retour qui le soutient, et aucun `worse` sans `better`
     (`barehands_trial_verdict_contradicted` si un chiffre le dément,
     `barehands_trial_verdict_unsupported` si rien ne le soutient) ; `worse`
     symétriquement. `no_change` et `inconclusive` ne se contredisent pas par
     un chiffre : le bruit n'est pas un démenti. */
  function resolveTrialOutcome(outcome,measurements,context){
    const o=createTrialOutcome(outcome);
    const deltas=computeTrialDeltas(o,measurements);
    const c=context===undefined||context===null?{}:objectOf(context,'barehands_trial_context_invalid','Contexte de résolution');
    onlyKeys(c,RESOLVE_CONTEXT_KEYS,'Contexte de résolution');
    const listOf=(value,label)=>{
      if(value===undefined||value===null)return [];
      if(!Array.isArray(value))reject('barehands_trial_context_invalid',`${label} : liste attendue.`);
      return value;
    };
    const feedback=new Map(listOf(c.feedback,'feedback').map(raw=>{const f=createUserFeedback(raw);return [f.ref,f]}));
    const hypotheses=new Map(listOf(c.hypotheses,'hypotheses').map(raw=>{const h=createHypothesis(raw);return [h.ref,h]}));
    const cited=o.hypothesisRefs.map(ref=>hypotheses.get(ref)
      ||reject('barehands_trial_hypothesis_missing',`Hypothèse citée introuvable : ${ref}.`));
    const targeted=cited.length?new Set(cited.flatMap(h=>complaintsForCause(h.cause))):new Set(COMPLAINTS);
    let appliedAt=null;
    if(o.feedbackRefs.length){
      if(c.appliedAt===undefined||c.appliedAt===null)
        reject('barehands_trial_applied_at_missing','Un retour cité se date contre l’application de l’essai : appliedAt est exigé.');
      appliedAt=measured(c.appliedAt,'barehands_trial_context_invalid','appliedAt',0);
    }
    let supports=0;
    for(const ref of o.feedbackRefs){
      const f=feedback.get(ref)||reject('barehands_trial_feedback_missing',`Retour cité introuvable : ${ref}.`);
      if(!(f.t>appliedAt))
        reject('barehands_trial_feedback_stale',`${ref} (t=${f.t}) précède l’essai (appliedAt=${appliedAt}) : il parle de l’ancien réglage.`);
      const fine=f.categories.includes(USER_FEEDBACK.FINE);
      const complains=f.categories.some(cat=>targeted.has(cat));
      if(o.verdict===TRIAL_VERDICT.IMPROVED){
        if(complains)reject('barehands_trial_feedback_contradicts',`${ref} porte encore la plainte visée : il ne soutient pas « improved ».`);
        if(fine||!f.categories.includes(USER_FEEDBACK.UNCLEAR))supports+=1;
      }else if(o.verdict===TRIAL_VERDICT.WORSE){
        if(fine)reject('barehands_trial_feedback_contradicts',`${ref} dit « fine » : il ne soutient pas « worse ».`);
        if(complains)supports+=1;
      }
    }
    const has=direction=>deltas.some(d=>d.direction===direction);
    const describe=()=>deltas.map(d=>`${d.metric}/${d.aggregate}: ${d.direction}`).join(', ')||'aucun';
    const [pro,con]=o.verdict===TRIAL_VERDICT.IMPROVED?['better','worse']
      :o.verdict===TRIAL_VERDICT.WORSE?['worse','better']:[null,null];
    if(pro!==null){
      if(has(con)&&!has(pro))
        reject('barehands_trial_verdict_contradicted',`Verdict « ${o.verdict} » contredit par les deltas calculés (${describe()}).`);
      if(!has(pro)&&!supports)
        reject('barehands_trial_verdict_unsupported',
          `Verdict « ${o.verdict} » sans delta mesuré dans ce sens ni retour qui le soutienne (${describe()}).`);
    }
    return Object.freeze({outcome:o,deltas,supportingFeedback:supports});
  }

  /* ---- 12.8 Banc d'essai (décision 40).

     Le schéma seulement : exercices, plan, résultat, dimensions reliées à
     leurs métriques brutes. **Aucune formule de score** — elle appartient à
     la Slice 08, qui doit la justifier. Le banc ne change jamais un réglage :
     rien ici n'a de champ qui en porte un. */
  const BENCHMARK_EXERCISE=Object.freeze({
    TARGET_ACQUISITION:'target_acquisition',NO_CLICK_TRACKING:'no_click_tracking',
    NEARBY_TARGETS:'nearby_targets',DRAG_DROP:'drag_drop',
    MOVING_TARGET:'moving_target',CHAINED:'chained',
  });
  const BENCHMARK_EXERCISES=values(BENCHMARK_EXERCISE);
  /* Les métriques brutes que **chaque** exercice rend — toutes, `null` compris
     (« non mesuré »), pour que deux résultats aient la même forme. */
  const BENCHMARK_EXERCISE_METRICS=Object.freeze({
    target_acquisition:Object.freeze(['acquisition_ms','missed_click_count','wrong_target_count','reacquisition_count','press_latency_ms']),
    no_click_tracking:Object.freeze(['false_click_count','false_press_rate','false_secondary_press_rate','unintended_target_rate',
      'unintended_pointer_rate','pointer_jitter_px']),
    nearby_targets:Object.freeze(['acquisition_ms','wrong_target_count','target_ambiguity','reacquisition_count']),
    drag_drop:Object.freeze(['drag_success_rate','premature_drop_count','placement_error_px','release_latency_ms']),
    moving_target:Object.freeze(['acquisition_ms','pointer_lag_ms','missed_click_count','reacquisition_count']),
    chained:Object.freeze(['transition_ms','missed_click_count','wrong_target_count','premature_drop_count','release_latency_ms']),
  });
  /* Les dimensions de **qualité d'interaction** — du système, pas de
     l'utilisateur — et les métriques brutes qui les nourrissent. */
  const BENCHMARK_DIMENSION_METRICS=Object.freeze({
    acquisition:Object.freeze(['acquisition_ms','reacquisition_count']),
    selection_accuracy:Object.freeze(['wrong_target_count','missed_click_count','target_ambiguity']),
    false_positive_resistance:Object.freeze(['false_click_count','false_press_rate','false_secondary_press_rate','unintended_target_rate',
      'unintended_pointer_rate']),
    release_reliability:Object.freeze(['release_latency_ms','premature_drop_count']),
    drag_drop:Object.freeze(['drag_success_rate','placement_error_px']),
    pointer_stability:Object.freeze(['pointer_jitter_px']),
    reactivity:Object.freeze(['pointer_lag_ms','press_latency_ms']),
    transitions:Object.freeze(['transition_ms']),
  });
  const BENCHMARK_DIMENSIONS=Object.freeze(Object.keys(BENCHMARK_DIMENSION_METRICS));
  {
    const produced=new Set(BENCHMARK_EXERCISES.flatMap(kind=>BENCHMARK_EXERCISE_METRICS[kind]||[]));
    const scored=new Set(BENCHMARK_DIMENSIONS.flatMap(d=>BENCHMARK_DIMENSION_METRICS[d]));
    for(const name of [...produced,...scored])
      if(!CALIBRATION_METRICS.includes(name))throw new RangeError(`Banc : métrique inconnue ${name}`);
    for(const name of scored)if(!produced.has(name))
      throw new RangeError(`Banc : la dimension cite ${name}, qu'aucun exercice ne mesure`);
    for(const name of produced)if(!scored.has(name))
      throw new RangeError(`Banc : ${name} est mesurée et ne nourrit aucune dimension`);
  }
  /* Quel profil a été mesuré : c'est ce qui rend un avant/après lisible. */
  const BENCHMARK_PROFILE_SOURCE=Object.freeze({DEFAULTS:'defaults',SAVED:'saved',TRIAL:'trial'});
  const BENCHMARK_PROFILE_SOURCES=values(BENCHMARK_PROFILE_SOURCE);
  const BENCHMARK_EXERCISES_MAX=24,BENCHMARK_TRIALS_MAX=50;
  const PLAN_KEYS=Object.freeze(['schemaVersion','kind','seed','exercises']);
  const PLAN_EXERCISE_KEYS=Object.freeze(['ref','kind','trials']);
  const planExercises=(list,label,extraKeys,read)=>{
    if(!Array.isArray(list)||!list.length)reject('barehands_benchmark_invalid',`${label} : au moins un exercice.`);
    if(list.length>BENCHMARK_EXERCISES_MAX)
      reject('barehands_benchmark_invalid',`${label} : ${list.length} exercices, ${BENCHMARK_EXERCISES_MAX} au plus.`);
    const seen=new Set();
    return Object.freeze(list.map(item=>{
      const e=objectOf(item,'barehands_benchmark_invalid','Exercice');
      onlyKeys(e,[...PLAN_EXERCISE_KEYS,...extraKeys],'Exercice');
      const ref=sessionRef(e.ref,[SESSION_REF.EXERCISE],'Exercice');
      if(seen.has(ref))reject('barehands_session_ref_duplicate',`Exercice ${ref} en double.`);
      seen.add(ref);
      const kind=wordOf(e.kind,BENCHMARK_EXERCISES,'barehands_benchmark_exercise_unknown','Exercice de banc');
      const trials=measured(e.trials,'barehands_benchmark_invalid','trials',1,BENCHMARK_TRIALS_MAX);
      if(!Number.isInteger(trials))reject('barehands_benchmark_invalid','trials : entier attendu.');
      return Object.freeze({ref,kind,trials,...(read?read(e,kind):{})});
    }));
  };
  /* Le plan : une graine et une suite d'exercices. La graine rend deux runs
     **équivalents mais pas identiques** (dispositions tirées) ; la même graine
     rejoue exactement la même disposition. */
  function createBenchmarkPlan(raw){
    const s=objectOf(raw,'barehands_benchmark_invalid','Plan de banc');
    onlyKeys(s,PLAN_KEYS,'Plan de banc');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Plan de banc');
    if(s.kind!==undefined&&s.kind!=='benchmark_plan')reject('barehands_benchmark_invalid','Plan : kind vaut « benchmark_plan ».');
    const seed=measured(s.seed,'barehands_benchmark_seed_invalid','seed',0,4294967295);
    if(!Number.isInteger(seed))reject('barehands_benchmark_seed_invalid','seed : entier non signé 32 bits attendu.');
    return Object.freeze({schemaVersion:SESSION_SCHEMA_VERSION,kind:'benchmark_plan',seed,
      exercises:planExercises(s.exercises,'Plan de banc',[])});
  }
  const RESULT_KEYS=Object.freeze(['schemaVersion','kind','ref','seed','runAt','profileSource','trialRef',
    'profileFingerprint','exercises']);
  const FINGERPRINT_PATTERN=/^[0-9a-f]{8,64}$/;
  /* Le résultat : les **métriques brutes** de chaque exercice, rien d'agrégé.
     Les dimensions et le score se calculent dessus (Slice 08) ; les stocker
     ici en ferait une seconde vérité. Chaque valeur tient dans les bornes de
     sa métrique (`CALIBRATION_METRIC`) : une latence de détection peut être
     négative — même définition que l'épisode (décision 35) —, un compte est
     entier, et un compte « par essai » ne dépasse pas le nombre d'essais. */
  function createBenchmarkResult(raw){
    const s=objectOf(raw,'barehands_benchmark_invalid','Résultat de banc');
    onlyKeys(s,RESULT_KEYS,'Résultat de banc');
    requireSchemaVersion(s.schemaVersion,SESSION_SCHEMA_VERSION,'Résultat de banc');
    if(s.kind!==undefined&&s.kind!=='benchmark_result')reject('barehands_benchmark_invalid','Résultat : kind vaut « benchmark_result ».');
    const seed=measured(s.seed,'barehands_benchmark_seed_invalid','seed',0,4294967295);
    if(!Number.isInteger(seed))reject('barehands_benchmark_seed_invalid','seed : entier non signé 32 bits attendu.');
    /* L'ordre avant/après : l'instant du run, en ms depuis l'époque. Fourni
       par l'appelant — ce module n'a pas d'horloge. */
    const runAt=measured(s.runAt,'barehands_benchmark_invalid','runAt',0);
    if(!Number.isInteger(runAt))reject('barehands_benchmark_invalid','runAt : entier (ms depuis l’époque) attendu.');
    /* **Quel profil** a été mesuré. `trial` dit lequel (`trialRef`, exigé) ;
       les deux autres n'en ont pas. L'empreinte (hexadécimale, calculée par
       l'appelant sur les valeurs effectives) sépare deux profils `saved`
       différents. */
    const profileSource=wordOf(s.profileSource,BENCHMARK_PROFILE_SOURCES,'barehands_benchmark_invalid','profileSource');
    const trialRef=optionalRef(s.trialRef,[SESSION_REF.TRIAL],'Essai mesuré');
    if((profileSource===BENCHMARK_PROFILE_SOURCE.TRIAL)!==(trialRef!==null))
      reject('barehands_benchmark_profile_invalid','trialRef est exigé pour un profil « trial », et seulement pour lui.');
    const fingerprint=s.profileFingerprint===undefined||s.profileFingerprint===null?null:s.profileFingerprint;
    if(fingerprint!==null&&!(typeof fingerprint==='string'&&FINGERPRINT_PATTERN.test(fingerprint)))
      reject('barehands_benchmark_profile_invalid','profileFingerprint : 8 à 64 caractères hexadécimaux minuscules.');
    const exercises=planExercises(s.exercises,'Résultat de banc',['metrics'],(e,kind)=>{
      const given=objectOf(e.metrics,'barehands_benchmark_invalid','metrics');
      const expected=BENCHMARK_EXERCISE_METRICS[kind];
      onlyKeys(given,expected,`metrics de ${kind}`);
      const metrics={};
      for(const name of expected){
        if(!hasOwn(given,name))reject('barehands_benchmark_metric_missing',
          `${kind} rend ${name} (null si non mesurée) : deux résultats doivent avoir la même forme.`);
        const spec=CALIBRATION_METRIC[name];
        const value=optionalMeasured(given[name],'barehands_benchmark_invalid',name,spec.min,
          spec.max===null?undefined:spec.max);
        if(value!==null&&spec.integer&&!Number.isInteger(value))
          reject('barehands_benchmark_invalid',`${name} : un compte est entier.`);
        if(value!==null&&spec.perTrial&&value>e.trials)
          reject('barehands_benchmark_invalid',`${name} = ${value} dépasse les ${e.trials} essais de l’exercice.`);
        metrics[name]=value;
      }
      return {metrics:Object.freeze(metrics)};
    });
    return Object.freeze({schemaVersion:SESSION_SCHEMA_VERSION,kind:'benchmark_result',
      ref:sessionRef(s.ref,[SESSION_REF.BENCHMARK],'Résultat de banc'),seed,runAt,
      profileSource,trialRef,profileFingerprint:fingerprint,
      exercises});
  }
  /* Deux résultats se comparent quand ils ont joué **la même suite
     d'exercices** (types et nombre d'essais), graines comprises ou non : des
     graines différentes sont justement ce qui sépare l'effet du réglage de
     l'apprentissage de la disposition. */
  function benchmarkComparable(a,b){
    const x=createBenchmarkResult(a),y=createBenchmarkResult(b);
    return x.exercises.length===y.exercises.length
      &&x.exercises.every((e,i)=>e.kind===y.exercises[i].kind&&e.trials===y.exercises[i].trials);
  }

  /* ---- 12.8 bis Les métriques du rejeu (§ 14) et celles-ci.

     Deux tables, parce que deux questions : le rejeu (`METRIC_KEYS` de
     l'enregistreur) rejoue une **trace** hors ligne sous d'autres réglages,
     en fractions d'image et en hertz, et ses noms sont figés par le miroir
     Python et les rapports déjà écrits ; ces métriques-ci mesurent une
     **séance** ou un **banc** en direct, en pixels de fenêtre et par minute.
     Là où elles disent la même chose, la correspondance est écrite ici — et
     testée contre la table du rejeu — plutôt que devinée. Les autres clés du
     rejeu n'ont pas d'équivalent ici (`interaction.latency_p50_ms` mesure le
     délai de l'issue d'interaction, pas une latence de détection de
     pincement). */
  const REPLAY_METRIC_EQUIVALENTS=Object.freeze({
    false_press_rate:Object.freeze({replay:'pinch.false_primary_hz',conversion:'× 60 (hz → par minute)'}),
    false_secondary_press_rate:Object.freeze({replay:'pinch.false_secondary_hz',conversion:'× 60 (hz → par minute)'}),
    pointer_jitter_px:Object.freeze({replay:'pointer.stationary_jitter_p95_norm',
      conversion:'× largeur de la fenêtre (fraction d’image → px), résumé p95'}),
  });

  /* ---- 12.9 Ce qui reste, ce qui s'efface (décision 41).

     `session` : en mémoire de la page pendant la séance, effacé à sa fin.
     `persistent` : rangé côté serveur. `opt_in` : seulement si l'utilisateur a
     lancé l'enregistreur (§ 14). Le tableau lisible est au § 17. */
  const RETENTION=Object.freeze({PERSISTENT:'persistent',SESSION:'session',OPT_IN:'opt_in'});
  const DATA_RETENTION=Object.freeze({
    session_sample:'session',pinch_episode:'session',false_event:'session',
    user_feedback:'session',evidence:'session',hypothesis:'session',
    trial_patch:'session',trial_outcome:'session',
    accepted_trial_values:'persistent',benchmark_plan:'session',benchmark_result:'persistent',
    diagnostic_trace:'opt_in',
  });

  const api=Object.freeze({
    SCHEMA_VERSION,BareHandsSchemaError,
    LIFECYCLE,LIFECYCLES,LIVE_LIFECYCLES,isLiveLifecycle,lifecycleOfControllerState,
    SLEEP_TIMEOUT_MS,WAKE_HOLD_MS,WAKE_INTERVAL_MS,
    FAILURE_CODE,FAILURE_CODES,isFailureCode,
    MAX_HANDS,POINTER_ID_BASE,POINTER_ID_MAX,POINTER_TYPE,
    pointerIdForSlot,slotForPointerId,isBareHandsPointerId,createSlotAllocator,
    DOM,isOverlayRoot,isFlowRoot,isBareHandsRoot,HANDEDNESS,HANDEDNESSES,
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
    TOOL_CAPABILITY,TOOL_CAPABILITY_CONTEXTUAL,TOOL_LABEL,SERVED_CAPABILITIES,
    INSTALLED_TOOLS,toolCapability,toolInstalled,describeTool,describeTools,
    SETTINGS_SCHEMA_VERSION,SETTINGS_MIGRATED_VERSIONS,SETTINGS_DEFAULTS,SETTINGS_BOUNDS,
    SETTINGS_WIRE_KEYS,SETTINGS_WIRE_VERSION_KEY,normalizeSettings,toServerPayload,fromServerState,
    PROFILE_SCHEMA_VERSION,PROFILE_MIGRATED_VERSIONS,PROFILE_DEFAULTS,HAND_PROFILE_DEFAULTS,
    PROFILE_MEASURED_KEYS:MEASURED_KEYS,
    PROFILE_METRIC_KEYS:METRIC_KEYS,PROFILE_CALIBRATING_KEYS:CALIBRATING_KEYS,
    STAGE,STAGES,STAGE_STATUS,STAGE_STATUSES,STAGE_REASON,STAGE_REASONS,SKIP_REASON,SKIP_REASONS,
    normalizeHandProfile,normalizeStage,normalizeProfile,profileValue,
    PROFILE_TUNING_BOUNDS:TUNING_BOUNDS,PROFILE_TUNING_KEYS:TUNING_KEYS,PROFILE_TUNING_PAIRS:TUNING_PAIRS,
    PROFILE_TUNING_WIRE_KEYS:TUNING_WIRE_KEYS,PROFILE_TUNING_ANCHORS:TUNING_ANCHORS,normalizeTuning,
    assertDerivedOnly,toProfilePayload,
    /* § 12 — calibration adaptative et banc d'essai. */
    SESSION_SCHEMA_VERSION,SESSION_REF,SESSION_REF_KINDS,isSessionRef,checkSchema,
    METRIC_UNIT,METRIC_UNITS,CALIBRATION_METRIC,CALIBRATION_METRICS,METRIC_AGGREGATE,METRIC_AGGREGATES,
    SESSION_EVENT,SESSION_EVENTS,
    EPISODE_PHASE,EPISODE_PHASE_SEQUENCE,EPISODE_LATENCY_MIN,EPISODE_LATENCY_MAX,createPinchEpisode,
    EPISODE_REJECT,EPISODE_REJECTS,EPISODE_WARNING,EPISODE_WARNINGS,
    FALSE_EVENT,FALSE_EVENTS,createFalseEvent,
    TRIAL_UNIT,TRIAL_UNITS,PARAMETER_FAMILY,PARAMETER_FAMILIES,TRIAL_KEYS,TRIAL_KEY_NAMES,
    TRIAL_ADVERTISED_KEYS,TRIAL_INVARIANTS,TRIAL_PATCH_MAX_KEYS,trialPartners,validateTrialPatch,
    USER_FEEDBACK,USER_FEEDBACKS,FEEDBACK_SOURCE,FEEDBACK_SOURCES,FEEDBACK_TEXT_MAX,createUserFeedback,
    HYPOTHESIS_CAUSE_KEYS,HYPOTHESIS_CAUSES,FEEDBACK_CAUSES,createEvidence,
    HYPOTHESIS_STATUS,HYPOTHESIS_STATUSES,createHypothesis,
    TRIAL_VERDICT,TRIAL_VERDICTS,createTrialOutcome,createMeasurementSet,quantile,aggregateMetric,
    computeTrialDeltas,resolveTrialOutcome,REPLAY_METRIC_EQUIVALENTS,TRIAL_ANCHORS,FEEDBACK_CATEGORIES_MAX,
    BENCHMARK_EXERCISE,BENCHMARK_EXERCISES,BENCHMARK_EXERCISE_METRICS,
    BENCHMARK_DIMENSION_METRICS,BENCHMARK_DIMENSIONS,BENCHMARK_PROFILE_SOURCE,BENCHMARK_PROFILE_SOURCES,
    createBenchmarkPlan,createBenchmarkResult,benchmarkComparable,
    RETENTION,DATA_RETENTION,
    adapters:Object.freeze({MEDIAPIPE_LANDMARK,handFrameFromMediapipe,pointersFromCoreTokens,motionFromCoreToken}),
  });
  root.JarvisBarehandsContracts=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
