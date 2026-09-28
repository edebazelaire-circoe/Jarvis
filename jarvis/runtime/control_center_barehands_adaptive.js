/* Bare Hands — contrats de la calibration adaptative et du banc d'essai
   (§ 12 du contrat ; tâche `jarvis-bare-hands-adaptive-calibration-benchmark`,
   décisions 34 à 70 de `docs/barehands-contracts.md` § 17).

   Ce bloc vivait à la fin de `control_center_barehands_contracts.js` (plus de
   1 300 lignes sur 3 300) ; la Slice 10 l'a séparé **sans changer une
   conduite**. Il ne fait rien lui non plus : il nomme.

   **Composition.** Ce module *étend* le contrat, il ne le recopie pas :

   - il lit `JarvisBarehandsContracts` (global de la page, inséré juste avant ;
     sous node, le module voisin) et n'en redéfinit aucun nom — un nom présent
     des deux côtés est un refus au chargement ;
   - ses refus passent par les aides du contrat (`schema.reject`,
     `BareHandsSchemaError`) : même classe, mêmes codes ;
   - il publie `JarvisBarehandsAdaptive`, objet gelé = **tous** les noms du
     contrat **plus** ceux du § 12. Un module qui lit la calibration
     adaptative ou le banc (calibration, agent, banc, enregistreur, pointeur)
     lit cet espace-là, et c'est lui qu'on injecte comme `contracts` aux blocs
     purs qui ont besoin des clés d'essai. Les autres (cible, HUD, scène)
     continuent de lire le contrat seul.

   Les contrôles de cohérence avec le § 10 (rangements `tuning` des clés
   d'essai, ancres, invariants) tournent **ici**, au chargement : un contrat
   dont le § 10 et le § 12 divergent refuse de se charger, comme avant.

   Logique pure : ni DOM, ni réseau, ni horloge. Inséré dans la page par
   `ControlCenter.index` juste après le contrat. */
(function(root){
  'use strict';

  const C=root.JarvisBarehandsContracts
    ||(typeof require==='function'?require('./control_center_barehands_contracts.js'):null);
  if(!C||!C.schema)
    throw new Error('JarvisBarehandsAdaptive : control_center_barehands_contracts.js doit être chargé avant ce module');
  const {reject,finiteOr,unit,values,requireSchemaVersion}=C.schema;
  const {BareHandsSchemaError,HANDEDNESSES,MAX_HANDS,PINCH_CHANNELS,SETTINGS_BOUNDS,STAGES,
    WAKE_INTERVAL_MS,normalizeProfile}=C;
  const MEASURED_KEYS=C.PROFILE_MEASURED_KEYS;
  const METRIC_KEYS=C.PROFILE_METRIC_KEYS;
  const CALIBRATING_KEYS=C.PROFILE_CALIBRATING_KEYS;
  const TUNING_BOUNDS=C.PROFILE_TUNING_BOUNDS;
  const TUNING_KEYS=C.PROFILE_TUNING_KEYS;
  const TUNING_PAIRS=C.PROFILE_TUNING_PAIRS;
  const TUNING_ANCHORS=C.PROFILE_TUNING_ANCHORS;
  const SENS=SETTINGS_BOUNDS.sensitivity;

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
    /* L'écart pouce-index du C tenu à l'étape du C (médiane, en paumes ;
       28/09/2026) : ce que l'utilisateur **veut** comme réveil. Ni meilleur
       ni pire : c'est la mesure contre laquelle `wakeGapMin` se règle (la
       bande tenue commence à `wakeGapMin + (wakeGapMax − wakeGapMin)·wakeSoft
       ·wakeScore`). */
    c_pose_gap_palms:metric('palm_ratio',null),
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
    /* Un essai de banc arrivé à son échéance sans sélection (Slice 08,
       reprise QA) : séparé des clics manqués — rien n'a été appuyé — et des
       temps d'acquisition, qu'il ne censure plus. */
    timeout_count:metric('count','lower',{perTrial:true}),
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
    /* **Le plancher d'écart pouce-index du C** (retour du 28/09/2026 : « c'est
       moi qui te dis le geste que je veux, c'est pas à lui de me dire c'est pas
       bon »). Zéro du score du C côté pincement ; la bande tenue commence à
       `wakeGapMin + (wakeGapMax − wakeGapMin)·wakeSoft·wakeScore` (0,499 aux
       défauts). Ancre jusque-là, réglable désormais : un C serré se règle ici,
       pas en abaissant `wakeScore`, qui ne déplace le bord que de 0,008.
       Reste au-dessus de `releaseRatio` (invariant ci-dessous) : l'abaisser
       sous 0,43 demande d'abaisser le relâchement dans le même essai. Lu par
       les options vivantes du contrôleur (guetteur de veille, posture du
       réveil, étape du C). */
    wakeGapMin:tk('wake','palm_ratio',.3,.7,.01,.46,
      'cPoseScore, wakePostureScore ← createController (options vivantes)',TUNING('wakeGapMin')),
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
     lesquels une clé d'essai se juge. `base` peut porter la valeur effective
     d'une ancre ; sinon, son défaut. Vide depuis le 28/09/2026 : `wakeGapMin`,
     la seule, est devenue une clé d'essai (ci-dessus) ; la paire
     `releaseRatio < wakeGapMin` reste un invariant, jugé désormais contre la
     valeur **effective** du plancher du C. Au rangement, elle reste une ancre
     (`PROFILE_TUNING_ANCHORS`) et non une paire : voir le contrat. */
  const TRIAL_ANCHORS=Object.freeze({});
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
  /* Une ancre de rangement est un invariant d'essai strict entre deux clés
     rangées, jugé autrement (voir `PROFILE_TUNING_ANCHORS`) : jamais aussi
     une paire. */
  const anchored=rule=>ownValue(TUNING_ANCHORS,rule.low)===rule.high;
  for(const key of Object.keys(TUNING_ANCHORS)){
    const high=TUNING_ANCHORS[key];
    const rule=TRIAL_INVARIANTS.find(r=>r.low===key&&r.high===high&&r.strict);
    if(!rule||!TUNING_KEYS.includes(key)||!TUNING_KEYS.includes(high))
      throw new RangeError(`TUNING_ANCHORS.${key} : diverge de TRIAL_INVARIANTS`);
  }
  for(const rule of TRIAL_INVARIANTS){
    const both=TUNING_KEYS.includes(rule.low)&&TUNING_KEYS.includes(rule.high)&&!anchored(rule);
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
    /* `wakeGapMin` (28/09/2026) : le plancher d'écart du C. Trop strict, on
       l'abaisse — et sous 0,43 le relâchement primaire doit suivre dans le
       même essai (`releaseRatio < wakeGapMin`), d'où `releaseRatio` ici. */
    wake_too_sensitive:Object.freeze(['wakeHoldMs','wakeScore','wakeGapMin']),
    /* Le repli des trois autres doigts (`pointingFold*`, 28/09/2026) : un C
       « ouvert » dont majeur, annulaire et auriculaire suivent l'index se lit
       main plate et ne réveille pas, quel que soit l'écart pouce-index. */
    wake_too_strict:Object.freeze(['wakeHoldMs','wakeScore','wakeGapMin','releaseRatio',
      'pointingFoldStartPalms','pointingFoldEndPalms']),
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
    target_acquisition:Object.freeze(['acquisition_ms','missed_click_count','wrong_target_count','reacquisition_count','press_latency_ms',
      'timeout_count','release_latency_ms']),
    no_click_tracking:Object.freeze(['false_click_count','false_press_rate','false_secondary_press_rate','unintended_target_rate',
      'unintended_pointer_rate','pointer_jitter_px']),
    nearby_targets:Object.freeze(['acquisition_ms','wrong_target_count','target_ambiguity','reacquisition_count','timeout_count',
      'release_latency_ms']),
    drag_drop:Object.freeze(['drag_success_rate','premature_drop_count','placement_error_px','release_latency_ms']),
    moving_target:Object.freeze(['acquisition_ms','pointer_lag_ms','missed_click_count','reacquisition_count','timeout_count']),
    chained:Object.freeze(['transition_ms','missed_click_count','wrong_target_count','premature_drop_count','release_latency_ms',
      'timeout_count']),
  });
  /* Les dimensions de **qualité d'interaction** — du système, pas de
     l'utilisateur — et les métriques brutes qui les nourrissent. */
  const BENCHMARK_DIMENSION_METRICS=Object.freeze({
    acquisition:Object.freeze(['acquisition_ms','reacquisition_count','timeout_count']),
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
  /* **Échantillons par essai** (Slice 08, reprise QA, décision 63) : pour
     chaque métrique, les valeurs scalaires dont elle est la statistique (une
     par essai, par épisode ou par point visé), 64 au plus. Des nombres, jamais
     une image ni un point de main : c'est ce qui permet un intervalle de
     confiance entre deux runs. */
  const BENCHMARK_SAMPLES_MAX=64;
  /* **Combien d'échantillons par essai** une métrique peut porter : un par
     essai par défaut ; une latence en a un par épisode de pincement (bornée
     par `BENCHMARK_SAMPLES_MAX` seulement) ; une ambiguïté un par appui (trois
     tentatives au plus) ; une transition deux par essai enchaîné ; un
     tremblement un par point visé (trois par essai de visée). */
  const BENCHMARK_SAMPLES_PER_TRIAL=Object.freeze({press_latency_ms:null,release_latency_ms:null,
    target_ambiguity:3,transition_ms:2,pointer_jitter_px:3});
  /* **La statistique de chaque métrique de banc** (décision 61) : médiane
     d'une durée, d'une distance ou d'un rapport ; moyenne d'un taux ou d'une
     proportion par essai ; somme d'un compte par essai. Une métrique rangée
     avec ses échantillons **doit** valoir cette statistique d'eux, arrondie
     selon son unité (le miroir Python refait le même calcul). */
  const BENCHMARK_METRIC_STAT=Object.freeze({
    acquisition_ms:'median',press_latency_ms:'median',release_latency_ms:'median',placement_error_px:'median',
    pointer_lag_ms:'median',transition_ms:'median',target_ambiguity:'median',pointer_jitter_px:'median',
    drag_success_rate:'mean',false_press_rate:'mean',false_secondary_press_rate:'mean',unintended_target_rate:'mean',
    unintended_pointer_rate:'mean',missed_click_count:'sum',wrong_target_count:'sum',premature_drop_count:'sum',
    reacquisition_count:'sum',timeout_count:'sum',false_click_count:'sum',
  });
  for(const name of new Set(BENCHMARK_EXERCISES.flatMap(kind=>BENCHMARK_EXERCISE_METRICS[kind])))
    if(!hasOwn(BENCHMARK_METRIC_STAT,name))throw new RangeError(`Banc : ${name} n'a pas de statistique`);
  const BENCHMARK_METRIC_DIGITS=Object.freeze({ms:1,px:2,ratio:3,unit:3,per_min:3,count:0});
  function benchmarkStat(name,samples){
    const how=ownValue(BENCHMARK_METRIC_STAT,name);
    if(!how)throw new RangeError(`Banc : pas de statistique pour ${name}`);
    const list=Array.isArray(samples)?samples.filter(v=>typeof v==='number'&&Number.isFinite(v)):[];
    if(!list.length)return null;
    let value;
    if(how==='median'){
      const xs=list.slice().sort((a,b)=>a-b),m=xs.length>>1;
      value=xs.length%2?xs[m]:(xs[m-1]+xs[m])/2;
    }else{
      let total=0;for(const v of list)total+=v;
      value=how==='mean'?total/list.length:total;
    }
    const k=10**BENCHMARK_METRIC_DIGITS[CALIBRATION_METRIC[name].unit];
    return Math.round(value*k)/k;
  }
  /* **Les classes de fenêtre** (décision 60, reprise QA) : grossières, pour
     qu'un léger redimensionnement ne casse pas une comparaison. Une fenêtre
     prend la plus grande classe dont elle atteint le minimum ; le plan
     s'y tire à l'échelle `planScale` (tailles, distances, écarts, vitesses,
     tolérance), ce qui garde chaque indice de difficulté de Fitts
     identique. Sous la plus petite, pas de banc. */
  const BENCHMARK_VIEWPORT_CLASSES=Object.freeze([
    Object.freeze({name:'vp100',planScale:1,minWidth:1280,minHeight:700}),
    Object.freeze({name:'vp90',planScale:.9,minWidth:1152,minHeight:630}),
    Object.freeze({name:'vp80',planScale:.8,minWidth:1024,minHeight:560}),
  ]);
  const benchmarkViewportClass=viewport=>{
    if(viewport===null||viewport===undefined)return null;
    const w=Number(viewport.width),h=Number(viewport.height);
    const found=BENCHMARK_VIEWPORT_CLASSES.find(c=>w>=c.minWidth&&h>=c.minHeight);
    return found?found.name:null;
  };
  const VIEWPORT_KEYS=Object.freeze(['width','height','scale']);
  const readViewport=raw=>{
    if(raw===undefined||raw===null)return null;
    const v=objectOf(raw,'barehands_benchmark_invalid','viewport');
    onlyKeys(v,VIEWPORT_KEYS,'viewport');
    return Object.freeze({width:measured(v.width,'barehands_benchmark_invalid','viewport.width',1,100000),
      height:measured(v.height,'barehands_benchmark_invalid','viewport.height',1,100000),
      scale:measured(v.scale,'barehands_benchmark_invalid','viewport.scale',.01,1000)});
  };
  /* **La classe de plan** (Slice 08 adaptative, décision 60) : la version des
     règles d'équivalence qui tirent une disposition d'une graine (bandes de
     tailles, de distances, d'écarts et de vitesses). Deux runs ne se
     comparent que sous la même classe : une suite d'exercices identique tirée
     sous d'autres bandes ne mesure plus la même difficulté. Absente, elle vaut
     la classe courante (aucun résultat n'a été rangé avant elle). */
  const BENCHMARK_PLAN_CLASS='bh-bench-1';
  const BENCHMARK_PLAN_CLASSES=Object.freeze([BENCHMARK_PLAN_CLASS]);
  const planClassOf=value=>value===undefined||value===null?BENCHMARK_PLAN_CLASS
    :wordOf(value,BENCHMARK_PLAN_CLASSES,'barehands_benchmark_invalid','planClass');
  const PLAN_KEYS=Object.freeze(['schemaVersion','kind','seed','planClass','exercises']);
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
      planClass:planClassOf(s.planClass),exercises:planExercises(s.exercises,'Plan de banc',[])});
  }
  const RESULT_KEYS=Object.freeze(['schemaVersion','kind','ref','seed','planClass','runAt','profileSource','trialRef',
    'profileFingerprint','viewport','exercises']);
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
    const runAt=measured(s.runAt,'barehands_benchmark_invalid','runAt',0,Number.MAX_SAFE_INTEGER);
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
    const viewport=readViewport(s.viewport);
    const exercises=planExercises(s.exercises,'Résultat de banc',['metrics','samples'],(e,kind)=>{
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
      /* Les échantillons, facultatifs : une liste bornée de nombres par
         métrique de l'exercice, chacun dans les bornes de sa métrique. */
      if(e.samples===undefined||e.samples===null)return {metrics:Object.freeze(metrics)};
      const givenSamples=objectOf(e.samples,'barehands_benchmark_invalid','samples');
      onlyKeys(givenSamples,expected,`samples de ${kind}`);
      const samples={};
      for(const name of Object.keys(givenSamples)){
        const list=givenSamples[name];
        if(!Array.isArray(list)||list.length>BENCHMARK_SAMPLES_MAX)
          reject('barehands_benchmark_invalid',`samples.${name} : liste de ${BENCHMARK_SAMPLES_MAX} nombres au plus.`);
        /* Pas plus d'échantillons que l'exercice n'a pu en produire. */
        const perTrial=hasOwn(BENCHMARK_SAMPLES_PER_TRIAL,name)?BENCHMARK_SAMPLES_PER_TRIAL[name]:1;
        if(perTrial!==null&&list.length>perTrial*e.trials)
          reject('barehands_benchmark_invalid',`samples.${name} : ${list.length} valeurs pour ${e.trials} essais.`);
        const spec=CALIBRATION_METRIC[name];
        samples[name]=Object.freeze(list.map(v=>{
          const value=measured(v,'barehands_benchmark_invalid',`samples.${name}`,
            spec.integer?0:spec.min,spec.max===null||spec.perTrial?undefined:spec.max);
          if(spec.integer&&!Number.isInteger(value))reject('barehands_benchmark_invalid',`samples.${name} : un compte est entier.`);
          return value;
        }));
        /* La métrique rangée est la statistique de ses échantillons. */
        if(benchmarkStat(name,samples[name])!==metrics[name])
          reject('barehands_benchmark_samples_mismatch',
            `${name} = ${String(metrics[name])} n’est pas la statistique de ses échantillons (${String(benchmarkStat(name,samples[name]))}).`);
      }
      return {metrics:Object.freeze(metrics),samples:Object.freeze(samples)};
    });
    return Object.freeze({schemaVersion:SESSION_SCHEMA_VERSION,kind:'benchmark_result',
      ref:sessionRef(s.ref,[SESSION_REF.BENCHMARK],'Résultat de banc'),seed,planClass:planClassOf(s.planClass),runAt,
      profileSource,trialRef,profileFingerprint:fingerprint,viewport,
      exercises});
  }
  /* Deux résultats se comparent quand ils ont joué **la même suite
     d'exercices** (types et nombre d'essais), sous la même classe de plan et
     la même classe de fenêtre, graines comprises ou non : des
     graines différentes sont justement ce qui sépare l'effet du réglage de
     l'apprentissage de la disposition. */
  function benchmarkComparable(a,b){
    const x=createBenchmarkResult(a),y=createBenchmarkResult(b);
    return x.planClass===y.planClass&&benchmarkViewportClass(x.viewport)===benchmarkViewportClass(y.viewport)
      &&x.exercises.length===y.exercises.length
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

  const adaptive=Object.freeze({
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
    BENCHMARK_PLAN_CLASS,BENCHMARK_PLAN_CLASSES,BENCHMARK_EXERCISES_MAX,BENCHMARK_TRIALS_MAX,BENCHMARK_SAMPLES_MAX,
    BENCHMARK_SAMPLES_PER_TRIAL,BENCHMARK_METRIC_STAT,BENCHMARK_METRIC_DIGITS,benchmarkStat,
    BENCHMARK_VIEWPORT_CLASSES,benchmarkViewportClass,
    createBenchmarkPlan,createBenchmarkResult,benchmarkComparable,
    RETENTION,DATA_RETENTION,
  });
  /* Étendre, jamais recouvrir : un nom des deux côtés voudrait dire deux
     définitions, et `Object.assign` ferait gagner la dernière en silence. */
  const clash=Object.keys(adaptive).filter(name=>Object.prototype.hasOwnProperty.call(C,name));
  if(clash.length)throw new RangeError(`JarvisBarehandsAdaptive recouvre le contrat : ${clash.join(', ')}`);
  const api=Object.freeze(Object.assign({},C,adaptive,{ADAPTIVE_NAMES:Object.freeze(Object.keys(adaptive))}));
  root.JarvisBarehandsAdaptive=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof globalThis!=='undefined'?globalThis:this);
