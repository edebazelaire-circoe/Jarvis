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
      `normalizeProfile` acceptent l'absence, le partiel et le douteux, et
      rendent toujours une valeur complète : une calibration incomplète reste
      valide, les fonctions non calibrées retombent sur les défauts
      (décisions 28, 31).

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

  /* ------------------------------------------------------------------ 1
     Cycle de vie (décisions 4, 5, 7).
     OFF libère la caméra ; SLEEP garde un guetteur léger ; ACTIVE interagit. */

  const LIFECYCLE=Object.freeze({OFF:'off',SLEEP:'sleep',ACTIVE:'active'});
  const LIFECYCLES=values(LIFECYCLE);
  /* Le contrôleur actuel n'a pas encore de SLEEP : ses états se lisent comme
     un cycle de vie réduit. `starting` n'est pas encore ACTIVE — rien
     n'interagit tant que la première image n'est pas suivie. */
  const LEGACY_CONTROLLER_LIFECYCLE=Object.freeze({off:'off',starting:'off',running:'active',error:'off'});
  const lifecycleOfControllerState=state=>LEGACY_CONTROLLER_LIFECYCLE[String(state)]||LIFECYCLE.OFF;
  /* Décision 7 : 30 s sans main exploitable ramène ACTIVE à SLEEP.
     Décision 5 : la posture de réveil se tient environ une seconde. */
  const SLEEP_TIMEOUT_MS=30000;
  const WAKE_HOLD_MS=1000;

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
    const size=Math.max(1,Math.min(MAX_HANDS,Math.round(Number(max)||MAX_HANDS)));
    const byTrack=new Map();
    return {
      slot(handTrackId){
        const key=String(handTrackId);
        if(byTrack.has(key))return byTrack.get(key);
        const taken=new Set(byTrack.values());
        for(let i=0;i<size;i+=1)if(!taken.has(i)){byTrack.set(key,i);return i}
        return null;
      },
      pointerId(handTrackId){
        const slot=this.slot(handTrackId);
        return slot===null?null:pointerIdForSlot(slot);
      },
      /* Une piste perdue rend sa fente ; sans cela deux mains qui vont et
         viennent finiraient par n'en trouver aucune. */
      forget(handTrackId){return byTrack.delete(String(handTrackId))},
      retain(liveIds){
        const live=new Set([...(liveIds||[])].map(String));
        for(const key of [...byTrack.keys()])if(!live.has(key))byTrack.delete(key);
      },
      size(){return byTrack.size},
      clear(){byTrack.clear()},
    };
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
    badgeClass:'jh-badge',
    hoverClass:'jarvis-hand-hover',
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
    const id=String(source.handTrackId||'').trim();
    if(!id)reject('barehands_hand_track_id_missing','Chaque main observée doit porter un handTrackId.');
    const points={};
    const given=source.points&&typeof source.points==='object'?source.points:{};
    for(const role of POINT_ROLES)if(given[role]!==undefined&&given[role]!==null)points[role]=normalizePoint(given[role],role);
    return Object.freeze({
      handTrackId:id,
      handedness:oneOf(source.handedness,HANDEDNESSES,HANDEDNESS.UNKNOWN),
      handednessConfidence:unit(source.handednessConfidence,0),
      /* Qualité de suivi : 0 = main devinée, 1 = main franche. Les seuils et
         l'assistance s'y réfèrent plutôt qu'à un score propre au traqueur. */
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

  function createGestureEvent(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_gesture_invalid','Geste attendu sous forme d’objet.');
    if(!GESTURES.includes(source.gesture))
      reject('barehands_gesture_unknown',`Geste inconnu : ${String(source.gesture)}.`);
    if(!GESTURE_PHASES.includes(source.phase))
      reject('barehands_gesture_phase_unknown',`Phase de geste inconnue : ${String(source.phase)}.`);
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'gesture',
      gesture:source.gesture,phase:source.phase,
      scope:oneOf(source.scope,values(GESTURE_SCOPE),GESTURE_SCOPE.GLOBAL),
      handTrackId:source.handTrackId===undefined||source.handTrackId===null?null:String(source.handTrackId),
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

  function createPinchEvent(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_pinch_invalid','Pincement attendu sous forme d’objet.');
    if(!PINCH_CHANNELS.includes(source.channel))
      reject('barehands_pinch_channel_unknown',`Canal de pincement inconnu : ${String(source.channel)}.`);
    if(!PINCH_PHASES.includes(source.phase))
      reject('barehands_pinch_phase_unknown',`Phase de pincement inconnue : ${String(source.phase)}.`);
    const handTrackId=String(source.handTrackId||'').trim();
    if(!handTrackId)reject('barehands_hand_track_id_missing','Un pincement appartient à une main identifiée.');
    const slot=source.slot===undefined||source.slot===null?null:Number(source.slot);
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'pinch',
      channel:source.channel,phase:source.phase,handTrackId,
      slot:slot===null?null:slot,
      pointerId:slot===null?null:pointerIdForSlot(slot),
      /* Pixels de la fenêtre : le point visé, déjà figé par l'ancre pendant
         l'approche pour que la cible ne glisse pas sous les doigts. */
      x:finiteOr(source.x,0),y:finiteOr(source.y,0),
      t:finiteOr(source.t,0),
      progress:unit(source.progress,source.phase===PINCH_PHASE.DOWN?1:0),
      confidence:unit(source.confidence,1),
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
  /* La meilleure candidate, la première citée tranchant à priorité égale. */
  function pickRegion(candidates){
    let best=null;
    for(const candidate of candidates||[]){
      if(!candidate)continue;
      if(!best||regionPriority(candidate.region)>regionPriority(best.region))best=candidate;
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
    const bounds=source.bounds&&typeof source.bounds==='object'?source.bounds:{};
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,
      objectId:source.objectId===undefined||source.objectId===null?null:String(source.objectId),
      /* Type sémantique lu du composant (bouton, lien, nœud de scène…) : c'est
         lui, et non `elementFromPoint` seul, qui décide l'action possible. */
      kind:String(source.kind||'unknown'),
      region:source.region,
      zone:source.region===REGION.BODY?null:zone,
      axes:source.region===REGION.BODY?Object.freeze([]):zoneAxes(zone),
      bounds:Object.freeze({x:finiteOr(bounds.x,0),y:finiteOr(bounds.y,0),
        w:Math.max(0,finiteOr(bounds.w,0)),h:Math.max(0,finiteOr(bounds.h,0))}),
      /* Décision 3 : pas de pointeur permanent — une candidate non
         actionnable n'appelle aucun retour visuel. */
      actionable:bool(source.actionable,true),
      /* Représentation de scène, quand la candidate en est une : seules
         `capsule` et `window` ont des zones (décision D3 de la Slice 00). */
      representation:source.representation===undefined||source.representation===null?null:String(source.representation),
      distance:Math.max(0,finiteOr(source.distance,0)),
      feedback:source.region===REGION.BODY?FEEDBACK.BODY:FEEDBACK.ZONE,
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

  function createCapture(raw){
    const source=raw&&typeof raw==='object'?raw:reject('barehands_capture_invalid','Capture attendue sous forme d’objet.');
    const handTrackId=String(source.handTrackId||'').trim();
    if(!handTrackId)reject('barehands_hand_track_id_missing','Une capture appartient à une main identifiée.');
    if(!REGIONS.includes(source.region))
      reject('barehands_region_unknown',`Région inconnue : ${String(source.region)}.`);
    if(source.region!==REGION.BODY&&!zoneSides(source.zone).length)
      reject('barehands_zone_invalid',`Zone de manipulation inconnue : ${String(source.zone)}.`);
    return Object.freeze({
      schemaVersion:SCHEMA_VERSION,kind:'capture',
      handTrackId,channel:oneOf(source.channel,PINCH_CHANNELS,PINCH_CHANNEL.PRIMARY),
      state:oneOf(source.state,CAPTURE_STATES,CAPTURE_STATE.CAPTURED),
      objectId:source.objectId===undefined||source.objectId===null?null:String(source.objectId),
      region:source.region,
      zone:source.region===REGION.BODY?null:(source.zone===undefined||source.zone===null?null:String(source.zone)),
      t:finiteOr(source.t,0),
    });
  }

  /* Deux captures sur le même objet : ce que le couple produit.
     BODY n'est pas une poignée de déplacement (décision 8) ; ZONE + BODY ne
     forme jamais un redimensionnement (décision 14) ; deux fois la même zone
     est refusée (décision 15) ; deux coins partageant un axe neutralisent cet
     axe (décision 17). Le refus porte un motif, pour être dit à l'écran. */
  function combineCaptures(a,b){
    if(!a||!b)return Object.freeze({mode:null,axes:Object.freeze([]),reason:'missing_capture'});
    if(a.objectId!==b.objectId)return Object.freeze({mode:'independent',axes:Object.freeze([]),reason:'different_objects'});
    if(a.region===REGION.BODY||b.region===REGION.BODY)
      return Object.freeze({mode:'move',axes:Object.freeze(['x','y']),reason:'body_is_not_a_resize_handle'});
    if(a.zone===b.zone)return Object.freeze({mode:null,axes:Object.freeze([]),reason:'same_zone_rejected'});
    const sidesA=zoneSides(a.zone),sidesB=zoneSides(b.zone);
    const sharedSides=sidesA.filter(side=>sidesB.includes(side));
    /* Décision 16 : bord + coin qui se recouvrent — le bord possède l'axe du
       côté partagé, le coin ne garde que l'autre ; les deux axes restent donc
       manipulables, chacun par une seule main.
       Décision 17 : deux coins sur un même côté neutralisent son axe. */
    const bothCorners=CORNERS.includes(a.zone)&&CORNERS.includes(b.zone);
    const neutral=new Set(bothCorners?sharedSides.map(side=>SIDE_AXIS[side]):[]);
    const axes=[...new Set([...sidesA,...sidesB].map(side=>SIDE_AXIS[side]))].filter(axis=>!neutral.has(axis)).sort();
    /* Garde : `createCapture` refuse déjà une zone hors table, mais la
       décomposition accepte aussi des objets nus (rejeu, diagnostic). */
    if(!axes.length)return Object.freeze({mode:null,axes:Object.freeze([]),reason:'zone_unknown'});
    return Object.freeze({mode:'resize',axes:Object.freeze(axes),reason:null});
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
    sleepTimeoutMs:SLEEP_TIMEOUT_MS,   // décision 7
    tool:TOOL_DEFAULT,
    assistance:0.5,           // assistance de visée, bornée et sûre
    sensitivity:1,
    tutorialSeen:false,
    calibrationEnabled:true,  // décision 27 : la calibration reste optionnelle
    diagnostics:false,        // architecture §12 : enregistrement sur demande
  });
  function normalizeSettings(raw){
    const source=raw&&typeof raw==='object'?raw:{};
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
    pressRatio:null,releaseRatio:null,       // seuils de pincement dérivés
    secondaryPressRatio:null,secondaryReleaseRatio:null,
    jitter:null,                             // écart-type du repos, en pixels
    reach:null,                              // {x,y,w,h} atteint dans l'image
    quality:null,                            // 0..1, confiance de la mesure
  });
  const PROFILE_DEFAULTS=Object.freeze({
    schemaVersion:PROFILE_SCHEMA_VERSION,
    calibrated:false,updatedAt:null,
    hands:Object.freeze({left:HAND_PROFILE_DEFAULTS,right:HAND_PROFILE_DEFAULTS}),
  });

  function normalizeHandProfile(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    const ratio=(value,min,max)=>{const n=Number(value);return Number.isFinite(n)?clamp(n,min,max):null};
    const reach=source.reach&&typeof source.reach==='object'?source.reach:null;
    return Object.freeze({
      pressRatio:ratio(source.pressRatio,.05,.9),
      releaseRatio:ratio(source.releaseRatio,.05,1.5),
      secondaryPressRatio:ratio(source.secondaryPressRatio,.05,.9),
      secondaryReleaseRatio:ratio(source.secondaryReleaseRatio,.05,1.5),
      jitter:ratio(source.jitter,0,200),
      reach:reach?Object.freeze({x:finiteOr(reach.x,0),y:finiteOr(reach.y,0),
        w:Math.max(0,finiteOr(reach.w,0)),h:Math.max(0,finiteOr(reach.h,0))}):null,
      quality:source.quality===undefined||source.quality===null?null:unit(source.quality,0),
    });
  }
  function normalizeProfile(raw){
    const source=raw&&typeof raw==='object'?raw:{};
    const hands=source.hands&&typeof source.hands==='object'?source.hands:{};
    const left=normalizeHandProfile(hands.left),right=normalizeHandProfile(hands.right);
    /* Calibration partielle valide : un seul seuil mesuré suffit à dire
       « calibré », le reste retombant sur les défauts (décision 31). */
    const measured=[left,right].some(hand=>hand.pressRatio!==null||hand.jitter!==null||hand.reach!==null);
    const at=Number(source.updatedAt);
    return Object.freeze({
      schemaVersion:PROFILE_SCHEMA_VERSION,
      calibrated:measured,
      updatedAt:Number.isFinite(at)?at:null,
      hands:Object.freeze({left,right}),
    });
  }
  /* Un seuil calibré s'il existe, sinon celui du moteur (décision 31). */
  const profileValue=(profile,handedness,key,fallback)=>{
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
      let id=String(ids[index]||label||`hand-${index}`);
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
    return createHandFrame({t:finiteOr(info.t,0),
      source:{width:info.width,height:info.height,aspect:info.aspect,tracker:'mediapipe_hand_landmarker'},
      hands:hands.slice(0,MAX_HANDS)});
  }

  /* Jetons de `JarvisBarehandsCore.createHandTracker` → identité de pointeur
     stable. Chemin de compatibilité de la Slice 01 : l'expérience de clic
     garde sa forme, mais chaque main y gagne sa fente et son `pointerId`.
     `allocator` est fourni par l'appelant pour que les fentes tiennent d'une
     image à l'autre. */
  function pointersFromCoreTokens(tokens,allocator){
    const slots=allocator||createSlotAllocator(MAX_HANDS);
    const list=Array.isArray(tokens)?tokens:[];
    slots.retain(list.map(token=>token&&token.id));
    return list.map(token=>{
      const handTrackId=String((token&&token.id)||'');
      const slot=slots.slot(handTrackId);
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

  const api=Object.freeze({
    SCHEMA_VERSION,BareHandsSchemaError,
    LIFECYCLE,LIFECYCLES,lifecycleOfControllerState,SLEEP_TIMEOUT_MS,WAKE_HOLD_MS,
    MAX_HANDS,POINTER_ID_BASE,POINTER_ID_MAX,POINTER_TYPE,
    pointerIdForSlot,slotForPointerId,isBareHandsPointerId,createSlotAllocator,
    DOM,isOverlayRoot,HANDEDNESS,HANDEDNESSES,
    POINT_ROLES,createHandObservation,createHandFrame,
    GESTURE,GESTURES,GESTURE_PHASE,GESTURE_PHASES,GESTURE_SCOPE,createGestureEvent,
    PINCH_CHANNEL,PINCH_CHANNELS,PINCH_FINGERS,PINCH_PHASE,PINCH_PHASES,createPinchEvent,
    REGION,REGIONS,EDGE,EDGES,CORNER,CORNERS,SIDE_AXIS,ZONE_SIDES,zoneSides,zoneAxes,
    REGION_PRIORITY,regionPriority,pickRegion,FEEDBACK,FEEDBACK_TOKENS,
    createTargetCandidate,ZONED_REPRESENTATIONS,hasManipulationZones,
    INTERACTION,INTERACTIONS,CAPTURE_STATE,CAPTURE_STATES,createCapture,combineCaptures,
    TOOL,TOOLS,TOOL_DEFAULT,normalizeTool,
    SETTINGS_SCHEMA_VERSION,SETTINGS_DEFAULTS,normalizeSettings,toServerPayload,
    PROFILE_SCHEMA_VERSION,PROFILE_DEFAULTS,HAND_PROFILE_DEFAULTS,normalizeHandProfile,normalizeProfile,profileValue,
    adapters:Object.freeze({MEDIAPIPE_LANDMARK,handFrameFromMediapipe,pointersFromCoreTokens}),
  });
  root.JarvisBarehandsContracts=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
