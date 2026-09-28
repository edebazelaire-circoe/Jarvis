/* Bare Hands — la séance de l'agent de calibration (tâche adaptative, Slice 06,
   décisions 50 à 55 ; `docs/barehands-contracts.md` § 17).

   L'« agent de calibration » est le cerveau existant en mode calibration
   (READINESS D1). Il ne voit ni les images ni le moteur : il parle à **cette**
   séance, par le canal de commandes (outils `calibration_*` → Control Center →
   page), et la page lui répond par des reçus. Ce module tient ce que la séance
   sait au-delà des mesures — retours, preuves, hypothèses, essais, accords —
   et applique les règles qui font d'une conversation un diagnostic honnête :

   - **le code chiffre, l'agent désigne** : une preuve cite des mesures par
     référence et sa valeur est calculée ici (`aggregateMetric`) ; une issue
     d'essai passe par `resolveTrialOutcome`, avec les **enregistrements** des
     retours et l'instant d'application ; aucun nombre venu de l'agent n'entre ;
   - **un essai teste une hypothèse** : ses clés sont celles de la cause
     (`HYPOTHESIS_CAUSE_KEYS`), un seul essai non jugé à la fois, et les
     mesures « après » doivent avoir été **prises sous cet essai** (le parcours
     note l'essai de chaque ligne, `rowMeta`) ;
   - **un démenti compte** : un essai sans amélioration affaiblit l'hypothèse
     par une règle fixe (`CONFIDENCE_RULE`) ; une hypothèse affaiblie ne
     s'essaie plus, et la même cause ne revient qu'avec une preuve **nouvelle**
     (postérieure au démenti) ;
   - **rien ne se range sans l'utilisateur** : `accept` exige un accord — la
     citation vérifiée par le Control Center pour la voix, le bouton « Garder
     ce réglage » pour l'écran — et l'enregistre.

   Trois fabriques : `createCalibrationAgentSession` (pure : la séance et ses
   règles), `createCoachPanel` (les commandes de repli à l'écran, pour qui ne
   parle pas), `createSessionReporter` (la séance déclarée au serveur, avec un
   battement). Insertion : après `control_center_barehands_recorder.js`, avant
   `control_center_barehands.js`, qui les lit à l'ouverture d'une calibration.
   Sous node, `module.exports`. */
(function(root){
  'use strict';

  const INACTIVE='barehands_calibration_inactive';
  const REFUSED='barehands_calibration_refused';
  /* Ce que `calibration_status` rend au plus : la fin de la séance, qui est ce
     qu'une phrase comme « là ça a merdé » désigne. Tenu sous le reçu de 16 Ko. */
  const STATUS_LIMITS=Object.freeze({measurements:24,feedback:12,evidence:12,hypotheses:16,trials:10,reviews:12});
  /* Plafonds de la séance : au-delà, refus nommé plutôt qu'une mémoire sans fin. */
  const SESSION_CAPS=Object.freeze({feedback:100,evidence:100,hypotheses:24});
  /* **La confiance ne bouge que par une issue résolue**, et par cette règle
     seulement (décision 52). Une hypothèse naît « modeste » : au plus
     `initialMax`. `improved` la rapproche de `ceiling` de moitié ; `no_change`
     la multiplie par `noChangeFactor`, `worse` par `worseFactor` — un essai qui
     empire dément plus qu'un essai qui ne change rien ; sous `rejectBelow`,
     elle est rejetée. `inconclusive` la multiplie par `inconclusiveFactor` :
     un essai qui ne tranche pas — mesuré ou abandonné avant d'être mesuré —
     ne plaide pas pour sa cause. **Aucun verdict ne laisse la confiance
     intacte après un essai, sauf `improved`** (reprise QA : sans ce prix,
     appliquer puis annuler, ou juger « inconclusive » en boucle, gardait
     l'hypothèse intacte). */
  /* **L'avis seul** (round 6) : un « improved » soutenu par le ressenti de
     l'utilisateur **sans** mesure qui le montre rapproche la confiance de
     `feelingCeiling` de `feelingGain`, sans jamais la dépasser ni la baisser,
     et ne rend jamais l'hypothèse « supported ». Le retour est une entrée de
     premier rang ; il n'est pas une mesure. */
  const CONFIDENCE_RULE=Object.freeze({initialMax:.8,ceiling:.95,improvedGain:.5,feelingCeiling:.7,feelingGain:.5,
    noChangeFactor:.6,
    worseFactor:.4,inconclusiveFactor:.8,rejectBelow:.15});
  /* **Le reçu de `status` tient dans son budget** (reprise QA : 16,5 à
     16,9 Ko mesurés pour 24 lignes de neuf métriques, au-dessus des 16 Ko du
     reçu). Budget en octets UTF-8 du `result`, sous la borne du serveur avec
     sa marge pour l'enveloppe ; au-delà, les plus anciennes lignes partent
     d'abord, et `truncated` compte ce qui est parti. */
  const STATUS_BYTE_BUDGET=14000;
  const STATUS_TRIM_PASSES=Object.freeze([['feedback',4],['evidence',4],['trials',4],['measurements',8],
    ['feedback',1],['evidence',0],['trials',1],['measurements',2],['feedback',0],['trials',0],['measurements',0]]);
  const byteLength=text=>{
    if(typeof TextEncoder==='function')return new TextEncoder().encode(text).length;
    return unescape(encodeURIComponent(text)).length;
  };
  /* Trois décimales suffisent à ce que le cerveau lit (ms, px, rapports) ;
     dix-sept chiffres par nombre coûtaient le tiers du reçu. */
  const rounded=v=>typeof v==='number'&&Number.isFinite(v)?Math.round(v*1000)/1000:null;
  const FAILED_VERDICTS=Object.freeze(['no_change','worse']);
  /* **Les exercices qui peuvent juger une cause** (reprise QA, round 4) : un
     essai ne se juge que sur les mesures de ces exercices-là, le parcours
     s'arrête après leur verdict tant qu'il n'est pas jugé, et « refais
     l'exercice » y ramène. Identifiants d'étape du contrat (`STAGE`). Une
     cause sans exercice (`tracking_quality`, `user_learning`) n'a pas de clé
     d'essai non plus. */
  const CAUSE_EXERCISES=Object.freeze({
    press_threshold_too_strict:['pinch_primary','pinch_secondary'],
    press_threshold_too_loose:['pinch_primary','pinch_secondary','natural_motion'],
    /* Slice 07 adaptative : « tenir puis relâcher » mesure les relâchements
       prématurés et collés, et 6C les lâchers avant la destination. */
    release_threshold_too_far:['pinch_primary','pinch_secondary','hold_release'],
    release_confirmation_too_slow:['pinch_primary','pinch_secondary','hold_release'],
    release_confirmation_too_fast:['pinch_primary','pinch_secondary','hold_release','drag','drop'],
    click_drag_separation_too_tight:['drag','drop','aim'],
    click_drag_separation_too_loose:['drag','drop'],
    pointer_filter_too_smooth:['aim'],
    pointer_filter_too_noisy:['aim','neutral'],
    stillness_misjudged:['drag','neutral'],
    target_assist_too_weak:['aim'],
    target_assist_too_strong:['aim'],
    zone_hysteresis_too_narrow:['aim'],
    wake_too_sensitive:['natural_motion','c_pose'],
    wake_too_strict:['c_pose'],
    pointer_shown_without_intent:['natural_motion','aim_no_click'],
    tracking_quality:[],user_learning:[],
  });
  /* Les clés d'essai propres à un canal : un essai d'une de ces clés ne se
     juge que sur l'exercice de son canal, et ne répond pas à une preuve prise
     sur l'autre (constat de la QA réelle : preuve primaire, essai secondaire,
     jugement primaire contre secondaire — accepté). */
  const CHANNEL_KEYS=Object.freeze({pressRatio:'pinch_primary',releaseRatio:'pinch_primary',
    secondaryPressRatio:'pinch_secondary',secondaryReleaseRatio:'pinch_secondary'});
  const CHANNEL_STAGES=Object.freeze(['pinch_primary','pinch_secondary']);
  /* **Assez de mesures pour un verdict chiffré** (reprise QA réelle, round 5 :
     « improved » tiré d'un seul pincement). Trois épisodes après l'essai — le
     minimum de la calibration elle-même (`pinchEpisodesMin`) — ; une ligne
     d'exercice (`ex-N`, `ng-N`) vaut un exercice entier. En dessous, le
     verdict ne se chiffre pas : l'avis noté de l'utilisateur, ou
     « inconclusive ». */
  const MIN_AFTER_EPISODES=3;
  /* **Ce que l'écran dit d'un refus**, en français d'utilisateur : ni
     référence (`tr-4`), ni mot de vocabulaire (« worse »). Le message précis,
     lui, part au cerveau et au journal. */
  const USER_TEXT=Object.freeze({
    barehands_calibration_inactive:'Aucune calibration pilotée par la voix dans cet onglet.',
    barehands_calibration_trial_worse:'Ce réglage a été jugé moins bon : il ne se garde pas. Annulez-le.',
    barehands_calibration_trial_unresolved:'Refaites l’exercice (ou dites ce que vous en pensez) avant de garder ce réglage.',
    barehands_trial_verdict_contradicted:'Les mesures disent le contraire — refaites l’exercice ou annulez l’essai.',
    barehands_calibration_too_few_measures:'Pas assez de mesures sous ce réglage : refaites l’exercice jusqu’au bout.',
    barehands_trial_nothing_to_rollback:'Aucun essai à annuler.',
    barehands_trial_nothing_to_accept:'Aucun réglage d’essai à garder.',
    barehands_calibration_consent_missing:'Rien n’a été gardé : il faut votre accord.',
    barehands_trial_accept_failed:'L’enregistrement a échoué : le réglage d’essai reste en cours.',
    barehands_calibration_skip_reason_required:'Pour passer cet exercice, choisissez pourquoi.',
    barehands_calibration_exercise_unavailable:'Il n’y a pas d’exercice à cet endroit du parcours.',
    barehands_calibration_trial_pending:'Un réglage d’essai attend d’être jugé sur cet exercice : refaites-le, ou annulez l’essai.',
    barehands_calibration_exercise_not_played:'Cet exercice n’a pas encore été joué : il viendra à son tour.',
    barehands_calibration_proposal_stale:'Cette proposition ne vaut plus (l’exercice a changé) : rien n’a été appliqué.',
    barehands_calibration_proposal_missing:'Aucune proposition à appliquer.',
    barehands_calibration_proposal_committed:'Cette proposition a déjà été appliquée.',
    barehands_calibration_commit_busy:'Une validation est déjà en cours.',
    barehands_calibration_readback_mismatch:'Le moteur n’a pas pris ces valeurs : l’essai a été défait, rien n’a changé.',
    barehands_trial_invariant_violated:'Ces valeurs se contredisent : corrigez-les avant d’appliquer.',
  });
  /* **Ce que l'assistant explique dans la revue** (Slice 07 adaptative,
     décision 56), en mots d'utilisateur : la cause d'une hypothèse, sans nom
     de paramètre ni nombre. */
  const CAUSE_WORDS=Object.freeze({
    press_threshold_too_strict:'il faut pincer trop fort pour que l’appui compte',
    press_threshold_too_loose:'l’appui se déclenche trop facilement',
    release_threshold_too_far:'il faut trop rouvrir pour relâcher',
    release_confirmation_too_slow:'le relâchement tarde à être reconnu',
    release_confirmation_too_fast:'le relâchement est reconnu trop tôt',
    click_drag_separation_too_tight:'un clic se transforme trop vite en glissement',
    click_drag_separation_too_loose:'un glissement démarre trop tard',
    pointer_filter_too_smooth:'le jeton suit la main avec retard',
    pointer_filter_too_noisy:'le jeton tremble',
    stillness_misjudged:'la main immobile n’est pas reconnue comme immobile',
    target_assist_too_weak:'l’aide à la visée est trop faible',
    target_assist_too_strong:'l’aide à la visée attrape la mauvaise cible',
    zone_hysteresis_too_narrow:'la cible visée change trop facilement',
    wake_too_sensitive:'la veille se réveille sans le vouloir',
    wake_too_strict:'la posture de réveil est trop difficile à tenir',
    pointer_shown_without_intent:'le jeton apparaît sans que vous visiez',
    tracking_quality:'la caméra voit mal la main',
    user_learning:'le geste est encore nouveau',
  });
  const VERDICT_WORDS=Object.freeze({improved:'mieux',no_change:'pas de différence',worse:'moins bien',
    inconclusive:'pas tranché'});
  /* **Le nom d'un réglage pour l'utilisateur** (panneau de calibration) :
     ce que la valeur règle, en mots, jamais l'identifiant du moteur seul. */
  const KEY_LABELS=Object.freeze({
    pressRatio:'Seuil d’appui (pouce-index)',releaseRatio:'Seuil de relâchement (pouce-index)',
    secondaryPressRatio:'Seuil d’appui (pouce-majeur)',secondaryReleaseRatio:'Seuil de relâchement (pouce-majeur)',
    pressFrames:'Images pour confirmer l’appui',releaseFrames:'Images pour confirmer le relâchement',
    releaseMs:'Délai de confirmation du relâchement',releaseDeltaRatio:'Réouverture exigée pour relâcher',
    releaseDoubtMaxMs:'Doute maximal au relâchement',clickSlopPx:'Tolérance de mouvement d’un clic',
    dragSlopPx:'Mouvement qui lance un glissement',clickMaxMs:'Durée maximale d’un clic',
    clickStillnessMin:'Immobilité exigée pour un clic',minCutoffHz:'Lissage du jeton (au repos)',
    betaCutoff:'Réactivité du jeton (en mouvement)',stillSpeedPx:'Vitesse sous laquelle la main est immobile',
    moveSpeedPx:'Vitesse au-dessus de laquelle la main bouge',assistance:'Aide à la visée',
    targetZonePx:'Zone de prise d’une cible',targetZoneHoldPx:'Zone de maintien d’une cible',
    targetSwitchPx:'Écart pour changer de cible',targetAmbiguityMax:'Ambiguïté tolérée entre deux cibles',
    targetHoldRatio:'Tenue de la cible visée',wakeHoldMs:'Durée du C pour réveiller',
    wakeScore:'Exigence de la posture de réveil',wakeGapMin:'Écart pouce-index minimal du C',
    pointingEnterScore:'Exigence pour faire apparaître le jeton',pointingExitScore:'Seuil de disparition du jeton',
    pointingEnterMs:'Délai d’apparition du jeton',pointingExitMs:'Délai de disparition du jeton',
    pointingMotionFloor:'Mouvement minimal pour viser',pointingFoldStartPalms:'Repli début',
    pointingFoldEndPalms:'Repli fin',
  });
  const UNIT_WORDS=Object.freeze({palm_ratio:'paume',ms:'ms',px:'px',frames:'images',unit:'',hz:'Hz',
    hz_per_px_per_s:'',px_per_s:'px/s'});
  const userText=code=>USER_TEXT[code]||'Pas fait : la demande a été refusée.';

  const own=(o,k)=>!!o&&typeof o==='object'&&Object.prototype.hasOwnProperty.call(o,k);
  const messageOf=error=>String(error&&error.message||error||'');
  const finite=v=>typeof v==='number'&&Number.isFinite(v)?v:null;

  function createCalibrationAgentSession(deps){
    const d=deps||{};
    const C=d.contracts;
    if(!C||typeof C.resolveTrialOutcome!=='function')
      throw new RangeError('createCalibrationAgentSession exige `contracts` : preuves, hypothèses et issues y vivent');
    for(const need of ['flow','trials','values'])
      if(typeof d[need]!=='function')
        throw new RangeError(`createCalibrationAgentSession exige deps.${need}() : sans lui la séance ne peut ni lire ni essayer`);
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const log=typeof d.log==='function'?d.log:()=>{};
    /* **L'origine de l'horloge de séance** (Slice 07 adaptative, décision 58)
       : celle du parcours (`clockOrigin`, horloge de la page), pour que les
       `t` des retours, les `appliedAt` des essais et les instants des lignes
       de mesures soient sur la même horloge. Sans elle (tests), l'instant de
       création. */
    const origin=Number.isFinite(d.origin)?d.origin:now();
    const t=()=>Math.max(0,now()-origin);
    const V=C.SESSION_SCHEMA_VERSION;

    const feedback=[];            // createUserFeedback
    const evidence=[];            // {record: createEvidence, value}
    const hypotheses=[];          // {record: createHypothesis, failedAt}
    const trials=[];              // lignes d'essai (voir `trialRow`)
    const consents=[];
    let next={fb:1,ev:1,hy:1};
    /* **L'état effectif, numéroté** (round 5). Chaque essai appliqué ouvre un
       état neuf ; un retour arrière rend l'état d'avant l'essai défait ; une
       acceptation garde l'état (l'effectif ne change pas, il devient
       l'enregistré). Le parcours note ce numéro sur chaque ligne de mesures. */
    let generation=0,lastGeneration=0;
    /* Qui agit pendant l'appel en cours : `voice` (le cerveau, par le canal
       de commandes) ou `ui` (l'écran). Les événements et décisions le disent. */
    let acting='ui';
    const actAs=(f,fn)=>f&&typeof f.act==='function'?f.act(acting==='voice'?'voice':'ui',fn):fn();

    const ok=(result,extra)=>Object.freeze({ok:true,code:null,result,...(extra||{})});
    function refuse(code,errors,op){
      const list=(errors||[]).slice(0,8).map(e=>Object.freeze({code:String(e.code||REFUSED),
        message:String(e.message||'').slice(0,200)}));
      log('warn','barehands.calibration_agent_refused',{op,code,faults:list.map(e=>e.code)});
      return Object.freeze({ok:false,code,errors:Object.freeze(list)});
    }
    const fault=(code,message,op)=>refuse(REFUSED,[{code,message}],op);
    /* Un retour ou un essai entre dans l'historique de séance du parcours,
       sur son horloge (décision 58). Une panne ici se dit et n'empêche rien :
       le retour ou l'essai lui-même est déjà rangé. */
    function markFlow(kind,ref,trialRef){
      const f=flow();
      if(!f||typeof f.mark!=='function')return null;
      try{return f.mark(kind,{ref,trialRef:trialRef||null})}
      catch(error){log('warn','barehands.calibration_mark_failed',{kind,error:messageOf(error)});return null}
    }
    const flow=()=>{
      try{return d.flow()}
      catch(error){
        /* Pas de parcours lisible = pas de séance : chaque porte refusera
           `inactive`, et la cause est dite ici. */
        log('error','barehands.calibration_flow_unreadable',{error:messageOf(error)});
        return null;
      }
    };
    const running=()=>{const f=flow();return !!(f&&typeof f.isRunning==='function'&&f.isRunning())};
    const inactive=op=>refuse(INACTIVE,[{code:INACTIVE,
      message:'Aucune séance de calibration n’est ouverte à l’écran.'}],op);
    /* Un refus de schéma du contrat devient un refus nommé ; toute autre levée
       est une erreur de programmation et remonte (§ 17, `checkSchema`). */
    function contract(factory,...args){
      const verdict=C.checkSchema(factory,...args);
      return verdict.ok?{value:verdict.value}:{refusal:verdict.errors.map(e=>({code:e.code,message:e.message}))};
    }
    function reviewRows(){
      const f=flow();
      const s=f&&typeof f.session==='function'?f.session():null;
      const list=s&&Array.isArray(s.reviews)?s.reviews:[];
      return list.slice(-STATUS_LIMITS.reviews).map(r=>({stage:r.stage,decision:r.decision,status:r.status,
        reason:r.reason||null,attempt:r.attempt,t:rounded(r.t)}));
    }
    function measurementState(){
      const f=flow();
      const s=f&&typeof f.session==='function'?f.session():null;
      return {set:s?s.measurements:Object.freeze({}),meta:s&&s.rowMeta?s.rowMeta:Object.freeze({})};
    }
    const findFeedback=ref=>feedback.find(f=>f.ref===ref)||null;
    const findHypothesis=ref=>hypotheses.find(h=>h.record.ref===ref)||null;
    const findTrial=ref=>trials.find(x=>x.ref===ref)||null;
    const activeTrials=()=>trials.filter(x=>x.state==='active');
    /* **Un essai non jugé bloque le suivant, même annulé** (reprise QA) :
       l'annulation reste immédiate — l'utilisateur dit « annule », ça
       s'annule —, mais l'essai reste à juger. Seul un essai gardé sur accord
       sort de la file sans verdict. */
    const unresolved=()=>trials.find(x=>x.verdict===null&&x.state!=='accepted')||null;

    /* ---------------------------------------------------------- lignes rendues
       Chaque forme est **exactement** celle que le schéma fermé du domaine
       Python (`barehands_calibration._RESULTS`) attend : une clé de plus ou de
       moins et le reçu est refusé au serveur. */
    const feedbackRow=f=>({ref:f.ref,categories:f.categories.slice(),text:f.text,source:f.source,t:f.t,
      stage:f.stage,exerciseRef:f.exerciseRef});
    const evidenceRow=e=>({ref:e.record.ref,metric:e.record.metric,aggregate:e.record.aggregate,
      sourceRefs:e.record.sourceRefs.slice(),feedbackRefs:e.record.feedbackRefs.slice(),value:finite(e.value)});
    const hypothesisRow=h=>({ref:h.record.ref,cause:h.record.cause,confidence:h.record.confidence,
      status:h.record.status,evidenceRefs:h.record.evidenceRefs.slice(),feedbackRefs:h.record.feedbackRefs.slice(),
      trialRefs:h.record.trialRefs.slice(),trialKeys:(C.HYPOTHESIS_CAUSE_KEYS[h.record.cause]||[]).slice()});
    const trialRow=x=>({ref:x.ref,hypothesisRef:x.hypothesisRef,baseRef:x.baseRef,patch:{...x.patch},
      applied:{...x.applied},state:x.state,verdict:x.verdict,deltas:x.deltas.map(dl=>({...dl})),appliedAt:x.appliedAt,
      exercises:x.exercises.slice(),baseStateId:x.baseStateId,stateId:x.stateId,basis:x.basis||null});
    function exercise(){
      const f=flow();
      const live=running();
      return {step:live&&typeof f.stepId==='function'?f.stepId():null,
        phase:live&&typeof f.phase==='function'?f.phase():null,running:live,
        finished:live&&typeof f.concluded==='function'?!!f.concluded():false};
    }
    /* Une valeur effective par clé : un nombre quand les trois mains la
       tiennent pareil, sinon `{left, right, unknown}` (même règle que le
       reçu d'essai, décision 48). */
    function flatten(perHand){
      const out={};
      for(const key of C.TRIAL_ADVERTISED_KEYS){
        const values=['left','right','unknown'].map(h=>finite(perHand&&perHand[h]&&perHand[h][key]));
        out[key]=values.every(v=>v===values[0])?values[0]:{left:values[0],right:values[1],unknown:values[2]};
      }
      return out;
    }
    const numbers=o=>{const out={};for(const k of Object.keys(o||{}))out[k]=finite(o[k]);return out};
    const relevantKeys=()=>{
      const keys=new Set();
      for(const h of hypotheses)if(h.record.status==='open'||h.record.status==='supported')
        for(const key of C.HYPOTHESIS_CAUSE_KEYS[h.record.cause]||[])keys.add(key);
      for(const x of trials)if(x.state==='active'||x.verdict===null)for(const key of Object.keys(x.patch))keys.add(key);
      return keys;
    };
    const withRelevant=(shown,all)=>{const out={...shown};for(const key of relevantKeys())
      if(Object.prototype.hasOwnProperty.call(all,key))out[key]=all[key];return out};
    const departures=o=>{const out={};for(const k of Object.keys(o)){const spec=C.TRIAL_KEYS[k];
      const def=spec?spec.default:undefined;const v=o[k];
      if(v===null||(typeof v==='number'&&v===def))continue;out[k]=v}return out};
    const roundedNumbers=o=>{const out={};for(const k of Object.keys(o||{}))out[k]=rounded(o[k]);return out};
    const roundedValues=o=>{const out={};for(const k of Object.keys(o||{})){const v=o[k];
      out[k]=v&&typeof v==='object'?{left:rounded(v.left),right:rounded(v.right),unknown:rounded(v.unknown)}:rounded(v)}
      return out};

    /* ---------------------------------------------------------- lectures */
    function status(){
      if(!running())return inactive('status');
      const {set,meta}=measurementState();
      const refs=Object.keys(set);
      const values=d.values()||{};
      const result={
        exercise:exercise(),
        /* Seules les clés qui s'écartent du défaut du contrat (reprise QA : les
           deux tables entières coûtaient ~7 Ko par tour) ; l'essai en entier. */
        /* … plus, **toujours**, les clés des hypothèses ouvertes et des essais
           en cours (round 5 : le cerveau allait les chercher par settings_get). */
        /* Round 6 : **toutes** les clés d'essai annoncées, effectives et
           enregistrées, arrondies, dès le premier appel — le cerveau n'a
           jamais à chercher une valeur ailleurs (ni réglages, ni dépôt). */
        values:{effective:roundedValues(flatten(values.effective)),saved:roundedValues(flatten(values.saved)),
          trial:roundedNumbers(values.trial)},
        measurements:refs.slice(-STATUS_LIMITS.measurements).map(ref=>{
          const m=meta[ref]||{};
          return {ref,stage:m.stage||null,exerciseRef:m.exerciseRef||null,trialRef:m.trialRef||null,
            stateId:Number.isInteger(m.stateId)?m.stateId:null,
            /* Ms de séance, même horloge que `feedback.t` et `appliedAt`
               (décision 58). */
            t:Number.isFinite(m.t)?rounded(m.t):null,
            metrics:roundedNumbers(set[ref])};
        }),
        measurementCount:refs.length,
        feedback:feedback.slice(-STATUS_LIMITS.feedback).map(feedbackRow),
        evidence:evidence.slice(-STATUS_LIMITS.evidence).map(e=>({...evidenceRow(e),value:rounded(e.value)})),
        hypotheses:hypotheses.slice(-STATUS_LIMITS.hypotheses).map(hypothesisRow),
        trials:trials.slice(-STATUS_LIMITS.trials).map(trialRow),
        /* Les dernières décisions de revue (Slice 07 adaptative, décision
           56) : validé, refait, passé (avec la raison). */
        reviews:reviewRows(),
        /* La proposition en cours (retour du 28/09) : préparée, corrigée à
           l'écran, validée ou périmée — jamais appliquée par elle-même. */
        proposal:proposalRow(proposal),
        /* La révision de séance du dernier événement (monotone). */
        revision:typeof d.revision==='function'?Math.max(0,Number(d.revision())||0):0,
        truncated:{measurements:0,feedback:0,evidence:0,trials:0},
      };
      /* Au-delà du budget : les plus anciennes lignes d'abord, par passes à
         planchers (`STATUS_TRIM_PASSES`) — d'abord les textes et l'historique,
         en gardant les dernières lignes de chaque famille, puis les mesures,
         jamais les hypothèses (petites, et ce que le tour doit juger). */
      for(const [list,floor] of STATUS_TRIM_PASSES){
        while(result[list].length>floor&&byteLength(JSON.stringify(result))>STATUS_BYTE_BUDGET){
          result[list].shift();result.truncated[list]+=1;
        }
      }
      if(Object.values(result.truncated).some(Boolean))
        log('info','barehands.calibration_status_truncated',{truncated:result.truncated});
      return ok(result);
    }

    /* ---------------------------------------------------------- parole */
    function recordFeedback(payload,source){
      if(!running())return inactive('feedback');
      if(feedback.length>=SESSION_CAPS.feedback)
        return fault('barehands_session_list_too_long',`${SESSION_CAPS.feedback} retours dans cette séance : c’est le plafond.`,'feedback');
      const p=payload||{};
      const f=flow();
      const step=f&&typeof f.stepId==='function'?f.stepId():null;
      const made=contract(C.createUserFeedback,{schemaVersion:V,kind:'user_feedback',ref:`fb-${next.fb}`,
        categories:p.categories,text:p.text,source:source===C.FEEDBACK_SOURCE.UI?C.FEEDBACK_SOURCE.UI:C.FEEDBACK_SOURCE.VOICE,
        t:t(),stage:C.STAGES.includes(step)?step:null,exerciseRef:null});
      if(made.refusal)return refuse(REFUSED,made.refusal,'feedback');
      next.fb+=1;
      feedback.push(made.value);
      markFlow(C.SESSION_EVENT.FEEDBACK,made.value.ref);
      const causes=[...new Set(made.value.categories.flatMap(c=>C.FEEDBACK_CAUSES[c]||[]))];
      log('info','barehands.calibration_feedback',{ref:made.value.ref,categories:made.value.categories,
        source:made.value.source,chars:made.value.text.length});
      return ok({feedback:feedbackRow(made.value),suggestedCauses:causes});
    }

    /* ---------------------------------------------------------- hypothèses */
    function proposeHypothesis(payload){
      if(!running())return inactive('hypothesis');
      const p=payload||{};
      if(hypotheses.length>=SESSION_CAPS.hypotheses)
        return fault('barehands_session_list_too_long',`${SESSION_CAPS.hypotheses} hypothèses dans cette séance : c’est le plafond.`,'hypothesis');
      const cause=String(p.cause||'');
      const feedbackRefs=Array.isArray(p.feedbackRefs)?p.feedbackRefs.slice():[];
      for(const ref of feedbackRefs)
        if(!findFeedback(ref))return fault('barehands_trial_feedback_missing',`Retour cité introuvable : ${ref}.`,'hypothesis');
      const same=hypotheses.filter(h=>h.record.cause===cause);
      const alive=same.find(h=>h.record.status==='open'||h.record.status==='supported');
      if(alive)return fault('barehands_calibration_hypothesis_duplicate',
        `La cause ${cause} est déjà ouverte (${alive.record.ref}) : teste-la ou juge son essai.`,'hypothesis');
      const {set,meta}=measurementState();
      /* Les preuves d'abord, **toutes** vérifiées avant d'en ranger une. */
      const pending=[];
      for(const [index,item] of (Array.isArray(p.evidence)?p.evidence:[]).entries()){
        const made=contract(C.createEvidence,{schemaVersion:V,kind:'evidence',ref:`ev-${next.ev+index}`,
          metric:item&&item.metric,aggregate:item&&item.aggregate,sourceRefs:item&&item.sourceRefs,feedbackRefs:[]});
        if(made.refusal)return refuse(REFUSED,made.refusal,'hypothesis');
        const value=contract(C.aggregateMetric,made.value.metric,made.value.aggregate,made.value.sourceRefs,set);
        if(value.refusal)return refuse(REFUSED,value.refusal,'hypothesis');
        pending.push({record:made.value,value:value.value});
      }
      /* **Un démenti compte** : la même cause, déjà affaiblie ou rejetée par un
         essai, ne revient qu'avec au moins une preuve postérieure au démenti. */
      const failedAt=same.reduce((latest,h)=>h.failedAt!==null&&h.failedAt>latest?h.failedAt:latest,-1);
      if(failedAt>=0){
        const fresh=feedbackRefs.some(ref=>findFeedback(ref).t>failedAt)
          ||pending.some(e=>e.record.sourceRefs.some(ref=>meta[ref]&&(meta[ref].at-origin)>failedAt));
        if(!fresh)return fault('barehands_calibration_hypothesis_disproven',
          `La cause ${cause} a déjà été démentie par un essai : elle ne revient qu’avec une mesure ou un retour postérieur à ce démenti.`,'hypothesis');
      }
      const confidence=Math.min(Number(p.confidence),CONFIDENCE_RULE.initialMax);
      const made=contract(C.createHypothesis,{schemaVersion:V,kind:'hypothesis',ref:`hy-${next.hy}`,cause,
        confidence:Number.isFinite(confidence)?confidence:p.confidence,status:C.HYPOTHESIS_STATUS.OPEN,
        evidenceRefs:pending.map(e=>e.record.ref),feedbackRefs,trialRefs:[]});
      if(made.refusal)return refuse(REFUSED,made.refusal,'hypothesis');
      next.hy+=1;next.ev+=pending.length;
      evidence.push(...pending);
      const entry={record:made.value,failedAt:null};
      hypotheses.push(entry);
      log('info','barehands.calibration_hypothesis',{ref:made.value.ref,cause,confidence:made.value.confidence,
        evidence:pending.map(e=>e.record.ref),feedback:feedbackRefs});
      return ok({hypothesis:hypothesisRow(entry),evidence:pending.map(evidenceRow)});
    }

    /* ---------------------------------------------------------- essais */
    /* Les exercices qui jugent **cet** essai : ceux de la cause, restreints au
       canal des clés propres à un canal, sinon aux exercices de la preuve
       quand elle en désigne parmi eux. */
    function exercisesFor(cause,patchChannels,evidenceStages){
      const base=CAUSE_EXERCISES[cause]||[];
      if(patchChannels.length){const narrowed=base.filter(stage=>patchChannels.includes(stage));if(narrowed.length)return narrowed}
      const fromEvidence=base.filter(stage=>evidenceStages.includes(stage));
      return fromEvidence.length?fromEvidence:base.slice();
    }
    /* **Ce qu'un essai doit respecter**, vérifié avant de le proposer comme
       avant de l'appliquer : l'hypothèse existe et n'est pas démentie, les
       clés sont celles de sa cause et de son canal, aucun essai n'attend son
       verdict. Rend `{h, patch, patchChannels, evidenceStages}` ou `{refusal}`. */
    function checkTrial(payload,op){
      const p=payload||{};
      const h=findHypothesis(String(p.hypothesisRef||''));
      if(!h)return {refusal:fault('barehands_trial_hypothesis_missing',`Hypothèse introuvable : ${p.hypothesisRef}.`,op)};
      if(h.record.status==='weakened'||h.record.status==='rejected')
        return {refusal:fault('barehands_calibration_hypothesis_disproven',
          `${h.record.ref} (${h.record.cause}) a été démentie par un essai : ne la réessaie pas, propose une autre cause ou une preuve nouvelle.`,op)};
      const allowed=C.HYPOTHESIS_CAUSE_KEYS[h.record.cause]||[];
      const patch=p.patch&&typeof p.patch==='object'?p.patch:{};
      const off=Object.keys(patch).filter(key=>!allowed.includes(key));
      if(off.length)return {refusal:fault('barehands_calibration_trial_off_hypothesis',
        allowed.length?`${off.join(', ')} ne teste pas ${h.record.cause} (clés permises : ${allowed.join(', ')}).`
          :`Aucun réglage ne teste ${h.record.cause} : c’est une réponse, pas un essai à faire.`,op)};
      /* Canal : une preuve prise sur un seul canal de pincement ne se teste pas
         par une clé de l'autre canal. */
      const {meta:rowsMeta}=measurementState();
      const evidenceStages=[...new Set(h.record.evidenceRefs.flatMap(ref=>{
        const e=evidence.find(x=>x.record.ref===ref);
        return e?e.record.sourceRefs.map(r=>rowsMeta[r]&&rowsMeta[r].stage).filter(Boolean):[];
      }))];
      const evidenceChannels=evidenceStages.filter(stage=>CHANNEL_STAGES.includes(stage));
      const patchChannels=[...new Set(Object.keys(patch).map(key=>CHANNEL_KEYS[key]).filter(Boolean))];
      if(evidenceChannels.length===1&&patchChannels.some(stage=>stage!==evidenceChannels[0]))
        return {refusal:fault('barehands_calibration_trial_channel_mismatch',
          `La preuve de ${h.record.ref} vient de ${evidenceChannels[0]} : ${Object.keys(patch).filter(k=>CHANNEL_KEYS[k]&&CHANNEL_KEYS[k]!==evidenceChannels[0]).join(', ')} règle l’autre canal.`,op)};
      const open=unresolved();
      if(open)return {refusal:fault('barehands_calibration_trial_unresolved',
        `L’essai ${open.ref} n’est pas encore jugé${open.state==='rolled_back'?' (il a été annulé, il reste à juger)':''} : juge-le avant d’en appliquer un autre.`,op)};
      return {h,patch,patchChannels,evidenceStages};
    }
    /* **Appliquer un essai au moteur** : la porte interne de la transaction
       de validation (`commitProposal`), jamais un outil du cerveau (retour du
       28/09 : « le Brain ne peut plus muter directement le moteur »). */
    function applyTrial(payload,meta){
      if(!running())return inactive('apply');
      const checked=checkTrial(payload,'apply');
      if(checked.refusal)return checked.refusal;
      const {h,patch,patchChannels,evidenceStages}=checked;
      const base=activeTrials().slice(-1)[0]||null;
      let receipt;
      try{receipt=d.trials().apply(patch)}
      catch(error){return fault('barehands_trial_engine_refused',messageOf(error),'apply')}
      if(!receipt||!receipt.ok){
        const faults=receipt&&receipt.rejected&&receipt.rejected.length
          ?receipt.rejected.map(e=>({code:e.code,message:e.message}))
          :[{code:receipt&&receipt.code||'barehands_trial_engine_refused',message:receipt&&receipt.message||'essai refusé'}];
        return refuse(REFUSED,faults,'apply');
      }
      const baseStateId=generation;
      lastGeneration+=1;generation=lastGeneration;
      const row={ref:receipt.trialId,hypothesisRef:h.record.ref,baseRef:base?base.ref:null,patch:numbers(patch),
        baseStateId,stateId:generation,
        applied:{...receipt.applied},appliedAt:t(),state:'active',verdict:null,basis:null,deltas:[],
        exercises:exercisesFor(h.record.cause,patchChannels,evidenceStages),
        proposalRef:meta&&meta.proposalRef||null};
      trials.push(row);
      markFlow(C.SESSION_EVENT.TRIAL_APPLIED,row.ref,row.ref);
      log('info','barehands.calibration_trial',{ref:row.ref,hypothesis:row.hypothesisRef,applied:row.applied,
        exercises:row.exercises});
      return ok({trialRef:row.ref,hypothesisRef:row.hypothesisRef,baseRef:row.baseRef,applied:row.applied,
        appliedAt:row.appliedAt,exercises:row.exercises.slice()});
    }

    /* ---------------------------------------------------------- propositions
       (retour du 28/09). **Le cerveau propose, l'utilisateur décide, le
       runtime exécute.** Une proposition est un état **à part** de l'essai
       effectif : la préparer ne touche pas au moteur ; l'écran la montre (le
       panneau de calibration, valeurs enregistrées / effectives / proposées) ;
       l'utilisateur peut corriger chaque valeur avant de la valider ; seule
       sa validation — un bouton du panneau, ou sa parole vérifiée par le
       Control Center — l'applique, par une transaction qui relit le moteur
       (`commitProposal`). Une seule proposition vivante : une nouvelle
       remplace l'ancienne. Elle se prépare sur la revue d'un exercice et
       vaut pour **cette** revue : une décision, un nouvel essai de
       l'exercice, ou un autre réglage appliqué entre-temps la périment. */
    let proposal=null,nextProposal=1,committing=false;
    const PROPOSAL_TEXT_MAX=300;
    const specOf=key=>C.TRIAL_KEYS[key]||null;
    /* Une valeur par clé, pour l'écran : un nombre, ou la main non identifiée
       quand les mains diffèrent (le panneau le dit « selon la main »). */
    function flatValue(perHand,key){
      const values=['left','right','unknown'].map(h=>finite(perHand&&perHand[h]&&perHand[h][key]));
      const same=values.every(v=>v===values[0]);
      return {value:same?values[0]:values[2]!==null?values[2]:values.find(v=>v!==null)??null,perHand:!same};
    }
    /* Enregistré (ce qu'une prochaine séance utilisera) et effectif (ce que
       le moteur tient maintenant), relus à chaque appel. */
    function valuesOf(keys){
      const all=d.values()||{};
      const out={};
      for(const key of keys){
        const effective=flatValue(all.effective,key),saved=flatValue(all.saved,key);
        const spec=specOf(key);
        out[key]={effective:effective.value,saved:saved.value,perHand:effective.perHand||saved.perHand,
          default:spec?spec.default:null};
      }
      return out;
    }
    /* La base contre laquelle une proposition se juge (invariants de paire) :
       les valeurs effectives, une par clé. */
    function effectiveBase(){
      const all=d.values()||{};
      const base={};
      for(const key of C.TRIAL_ADVERTISED_KEYS){const v=flatValue(all.effective,key).value;if(v!==null)base[key]=v}
      return base;
    }
    const snap=(key,value)=>{
      const spec=specOf(key);
      if(!spec||typeof value!=='number'||!Number.isFinite(value))return null;
      const steps=Math.round((value-spec.min)/spec.step);
      const snapped=spec.min+steps*spec.step;
      const out=Math.min(spec.max,Math.max(spec.min,Math.round(snapped*1e6)/1e6));
      return spec.integer?Math.round(out):out;
    };
    const proposalPatch=pr=>{const out={};for(const row of pr.keys)out[row.key]=row.value;return out};
    /* Pourquoi une proposition ne vaut plus, ou `null` : décision prise,
       nouvel essai de l'exercice, autre état effectif, étape quittée. */
    function staleness(pr){
      if(!pr)return 'barehands_calibration_proposal_missing';
      if(pr.state!=='pending')return pr.state==='committed'?'barehands_calibration_proposal_committed'
        :'barehands_calibration_proposal_stale';
      const f=flow();
      const review=f&&typeof f.review==='function'?f.review():null;
      if(!review||review.stage!==pr.stage||review.attempt!==pr.attempt||generation!==pr.stateId)
        return 'barehands_calibration_proposal_stale';
      return null;
    }
    const STALE_TEXT=Object.freeze({
      barehands_calibration_proposal_missing:'Aucune proposition n’est ouverte.',
      barehands_calibration_proposal_committed:'Cette proposition a déjà été appliquée.',
      barehands_calibration_proposal_stale:'Cette proposition ne vaut plus : l’exercice a changé depuis (décision prise, nouvel essai ou autre réglage). Rien n’a été appliqué.',
    });
    function proposalRow(pr){
      if(!pr)return null;
      const now=valuesOf(pr.keys.map(row=>row.key));
      const stale=pr.state==='pending'&&staleness(pr)!==null;
      return {ref:pr.ref,state:stale?'stale':pr.state,hypothesisRef:pr.hypothesisRef,cause:pr.cause,stage:pr.stage,
        attempt:pr.attempt,summary:pr.summary,untouched:pr.untouched,version:pr.version,
        rerunStage:pr.rerunStage,
        keys:pr.keys.map(row=>({key:row.key,proposed:row.proposed,value:row.value,
          effective:rounded(now[row.key].effective),saved:rounded(now[row.key].saved),perHand:now[row.key].perHand,
          min:row.min,max:row.max,step:row.step,unit:row.unit})),
        errors:pr.errors.map(e=>({key:e.key||null,code:e.code,message:e.message})),
        receipt:pr.receipt?{...pr.receipt,steps:pr.receipt.steps.slice()}:null};
    }
    function emit(event){
      if(typeof d.emit!=='function')return;
      try{d.emit(Object.freeze(event))}
      catch(error){log('warn','barehands.calibration_emit_failed',{type:event.type,error:messageOf(error)})}
    }
    /* Juger les valeurs courantes contre les invariants du moteur, sans rien
       appliquer : l'écran dit tout de suite qu'un curseur viole une paire. */
    function recheck(pr){
      const verdict=C.validateTrialPatch(proposalPatch(pr),effectiveBase());
      pr.errors=verdict.ok?[]:verdict.errors.map(e=>({key:e.key,code:e.code,message:e.message}));
    }
    /* **Préparer** (cerveau, `calibration_prepare_trial`) : une proposition
       visible, **rien n'est appliqué**. Mêmes règles qu'un essai (cause,
       canal, un essai à la fois), plus les invariants du moteur jugés à sec. */
    function prepareTrial(payload){
      if(!running())return inactive('prepare');
      const p=payload||{};
      const f=flow();
      const review=f&&typeof f.review==='function'?f.review():null;
      if(!review)return fault('barehands_calibration_not_in_review',
        'Une proposition se prépare sur la revue d’un exercice : attends la fin de l’exercice.','prepare');
      const checked=checkTrial(p,'prepare');
      if(checked.refusal)return checked.refusal;
      const {h,patch,patchChannels,evidenceStages}=checked;
      if(!Object.keys(patch).length)return fault('barehands_trial_patch_empty','Une proposition change au moins une valeur.','prepare');
      const summary=String(p.summary||'').trim().slice(0,PROPOSAL_TEXT_MAX);
      if(summary.length<2)return fault('barehands_calibration_proposal_summary_missing',
        'Dis en une phrase ce que la proposition change pour l’utilisateur (summary).','prepare');
      const dry=C.validateTrialPatch(patch,effectiveBase());
      if(!dry.ok)return refuse(REFUSED,dry.errors.map(e=>({code:e.code,message:e.message})),'prepare');
      /* L'exercice qui jugera l'essai s'il est refait : celui en revue s'il
         juge cette cause, sinon le premier de la cause — seulement s'il a
         déjà été joué (on ne saute pas en avant). */
      const exercises=exercisesFor(h.record.cause,patchChannels,evidenceStages);
      const target=exercises.includes(review.stage)?review.stage:exercises[0]||null;
      const can=target&&typeof f.canRerun==='function'?f.canRerun(target):{ok:!!target};
      const now=valuesOf(Object.keys(patch));
      if(proposal&&proposal.state==='pending'){proposal.state='superseded';log('info','barehands.calibration_proposal_superseded',{ref:proposal.ref})}
      proposal={ref:`pr-${nextProposal}`,hypothesisRef:h.record.ref,cause:h.record.cause,summary,
        untouched:String(p.untouched||'').trim().slice(0,PROPOSAL_TEXT_MAX)||null,
        stage:review.stage,attempt:review.attempt,stateId:generation,t:t(),state:'pending',version:1,
        rerunStage:can&&can.ok?target:null,errors:[],receipt:null,
        keys:Object.keys(patch).map(key=>{const spec=specOf(key);return {key,proposed:patch[key],value:patch[key],
          before:now[key].effective,min:spec.min,max:spec.max,step:spec.step,unit:spec.unit}})};
      nextProposal+=1;
      log('info','barehands.calibration_proposal',{ref:proposal.ref,hypothesis:h.record.ref,stage:proposal.stage,
        attempt:proposal.attempt,keys:Object.keys(patch)});
      const row=proposalRow(proposal);
      emit({type:'proposal_ready',proposal_ref:row.ref,stage:row.stage,attempt:row.attempt,summary:row.summary,
        untouched:row.untouched,keys:row.keys.map(k=>({key:k.key,label:KEY_LABELS[k.key]||k.key,proposed:k.proposed,
          effective:k.effective,saved:k.saved})),source:'brain'});
      return ok({proposal:row});
    }
    /* **Corriger une valeur proposée** (le curseur ou le champ du panneau) :
       ramenée au pas et aux bornes de la clé, jugée aussitôt contre les
       invariants. Rien n'est appliqué. */
    function editProposal(ref,key,value){
      const pr=proposal;
      const stale=pr&&pr.ref===ref?staleness(pr):'barehands_calibration_proposal_missing';
      if(stale)return fault(stale,STALE_TEXT[stale],'edit');
      const row=pr.keys.find(k=>k.key===key);
      if(!row)return fault('barehands_calibration_proposal_key_unknown',`${key} ne fait pas partie de la proposition.`,'edit');
      const snapped=snap(key,Number(value));
      if(snapped===null)return fault('barehands_trial_value_invalid',`${key} : nombre attendu.`,'edit');
      row.value=snapped;pr.version+=1;
      recheck(pr);
      return ok({proposal:proposalRow(pr)});
    }
    function resetProposalKey(ref,key){
      const pr=proposal;
      const row=pr&&pr.ref===ref?pr.keys.find(k=>k.key===key):null;
      return row?editProposal(ref,key,row.proposed):fault('barehands_calibration_proposal_key_unknown','Valeur introuvable.','edit');
    }
    function discardProposal(ref,source){
      const pr=proposal;
      if(!pr||pr.ref!==ref||pr.state!=='pending')return fault('barehands_calibration_proposal_missing',STALE_TEXT.barehands_calibration_proposal_missing,'discard');
      pr.state='discarded';
      log('info','barehands.calibration_proposal_discarded',{ref,source:source||'ui'});
      return ok({proposal:proposalRow(pr)});
    }
    /* Les valeurs appliquées, relues : le reçu du moteur **et** la couche
       effective relue à l'instant, chacune égale à la valeur demandée. */
    function readback(patch,applied){
      const now=valuesOf(Object.keys(patch));
      const wrong=[];
      for(const key of Object.keys(patch)){
        const want=patch[key];
        const got=applied?applied[key]:undefined;
        const values=got&&typeof got==='object'?Object.values(got).filter(v=>v!==null):[got];
        const receiptOk=values.length>0&&values.every(v=>typeof v==='number'&&Math.abs(v-want)<1e-6);
        const effective=now[key].effective;
        const liveOk=typeof effective==='number'&&Math.abs(effective-want)<1e-6;
        if(!receiptOk||!liveOk)wrong.push(key);
      }
      return wrong;
    }
    /* **Valider une proposition** : une transaction, un reçu cohérent.

         rerun     vérifier → appliquer → relire → refaire l'exercice
         continue  vérifier → appliquer → relire → garder (enregistré) →
                   « accepté par l'utilisateur · non revérifié » → étape
                   suivante

       Ce qui est appliqué est la proposition **telle que l'écran la montre**
       (valeurs corrigées comprises), jamais l'ancienne réponse du cerveau.
       Source `panel` (bouton : l'accord est le clic) ou `voice` (la parole de
       l'utilisateur, retrouvée par le Control Center). Un second appel
       pendant la transaction est refusé (double clic). Une relecture fausse
       défait l'essai. */
    async function commitProposal(payload,source){
      const op='commit';
      if(!running())return inactive(op);
      const p=payload||{};
      const src=source==='voice'?'voice':'panel';
      if(src==='voice'){
        const consent=p.consent;
        const voiced=consent&&consent.source==='voice'&&consent.verifiedBy==='control_center'
          &&typeof consent.quote==='string'&&consent.quote.trim().length>=2;
        if(!voiced)return fault('barehands_calibration_consent_missing',
          'Aucun accord de l’utilisateur n’accompagne cette demande : rien n’a été appliqué.',op);
      }
      if(committing)return fault('barehands_calibration_commit_busy','Une validation est déjà en cours.',op);
      const action=p.action==='continue'?'continue':p.action==='rerun'?'rerun':null;
      if(!action)return fault('barehands_calibration_commit_action_unknown','action : rerun ou continue.',op);
      const pr=proposal;
      const stale=pr&&pr.ref===p.proposalRef?staleness(pr):pr&&pr.state==='pending'
        ?'barehands_calibration_proposal_stale':'barehands_calibration_proposal_missing';
      if(stale)return fault(stale,STALE_TEXT[stale],op);
      if(pr.errors.length)return refuse(REFUSED,pr.errors.map(e=>({code:e.code,message:e.message})),op);
      if(action==='rerun'&&!pr.rerunStage)return fault('barehands_calibration_exercise_not_played',
        'Aucun exercice déjà joué ne peut juger ce réglage : « Appliquer et continuer », ou attendre son exercice.',op);
      committing=true;
      const steps=[];
      try{
        const patch=proposalPatch(pr);
        const applied=applyTrial({hypothesisRef:pr.hypothesisRef,patch},{proposalRef:pr.ref});
        if(!applied.ok)return applied;
        steps.push('applied');
        const row=findTrial(applied.result.trialRef);
        const wrong=readback(patch,applied.result.applied);
        if(wrong.length){
          /* Le moteur ne tient pas ce qu'on lui a demandé : l'essai est
             défait, et il ne compte pas contre l'hypothèse (panne, pas
             démenti). */
          const back=rollbackTrial();
          if(row){row.verdict='inconclusive';row.basis='none'}
          log('error','barehands.calibration_readback_mismatch',{proposal:pr.ref,keys:wrong,rolledBack:!!back.ok});
          return fault('barehands_calibration_readback_mismatch',
            `Le moteur ne tient pas les valeurs demandées (${wrong.join(', ')}) : l’essai a été défait, rien n’a changé.`,op);
        }
        steps.push('verified');
        pr.state='committed';
        const f=flow();
        const act=fn=>typeof f.act==='function'?f.act(src,fn):fn();
        emit({type:'trial_applied',proposal_ref:pr.ref,trial_ref:applied.result.trialRef,action,
          applied:roundedValues(applied.result.applied),verified:true,source:src});
        let decision,attempt=null;
        if(action==='rerun'){
          const target=pr.rerunStage;
          const moved=act(()=>f.rerun(target));
          if(moved===null||moved===undefined){
            pr.receipt={action,steps:steps.slice(),trialRef:applied.result.trialRef,ok:false};
            return fault('barehands_calibration_exercise_unavailable',
              'Le réglage est appliqué (non enregistré) mais l’exercice n’a pas pu être relancé.',op);
          }
          steps.push('rerun');decision='rerun';
          attempt=target===pr.stage?pr.attempt+1:null;
        }else{
          let receipt;
          try{receipt=await d.trials().accept()}
          catch(error){receipt={ok:false,code:'barehands_trial_accept_failed',message:messageOf(error)}}
          if(!receipt||!receipt.ok){
            /* Rien de gardé : l'essai est défait, l'étape reste en revue. */
            rollbackTrial();
            if(row){row.verdict='inconclusive';row.basis='none'}
            pr.receipt={action,steps:steps.slice(),trialRef:applied.result.trialRef,ok:false};
            return fault(receipt&&receipt.code||'barehands_trial_accept_failed',
              `L’enregistrement a échoué (${receipt&&receipt.message||'refus'}) : l’essai a été défait.`,op);
          }
          steps.push('saved');
          for(const kept of activeTrials()){kept.state='accepted';kept.basis=kept.basis||'user_unverified';
            markFlow(C.SESSION_EVENT.TRIAL_ACCEPTED,kept.ref,kept.ref)}
          consents.push({source:src==='voice'?'voice':'ui',quote:src==='voice'?p.consent.quote.trim().slice(0,200):'',
            t:t(),trialRef:applied.result.trialRef,unverified:true});
          const moved=act(()=>typeof f.acceptUnverified==='function'?f.acceptUnverified():null);
          if(moved===null||moved===undefined){
            pr.receipt={action,steps:steps.slice(),trialRef:applied.result.trialRef,ok:false};
            return fault('barehands_calibration_exercise_unavailable',
              'Le réglage est gardé, mais l’étape n’a pas pu être soldée : validez-la ou passez-la.',op);
          }
          steps.push('advanced');decision='accepted_unverified';
        }
        pr.receipt={action,steps:steps.slice(),trialRef:applied.result.trialRef,ok:true,attempt,decision};
        log('info','barehands.calibration_proposal_committed',{ref:pr.ref,action,trial:applied.result.trialRef,
          source:src,steps});
        return ok({proposalRef:pr.ref,action,trialRef:applied.result.trialRef,applied:roundedValues(applied.result.applied),
          verified:true,steps:steps.slice(),exercise:exercise(),decision,attempt});
      }finally{committing=false}
    }

    /* **Juger un essai.** Le verdict est celui de l'agent, mais il ne passe
       que si `resolveTrialOutcome` le tient contre les deltas **calculés** et
       les retours **enregistrés** ; puis la confiance suit `CONFIDENCE_RULE`. */
    function resolveTrial(payload){
      if(!running())return inactive('resolve');
      const p=payload||{};
      const trial=findTrial(String(p.trialRef||''));
      if(!trial)return fault('barehands_calibration_trial_unknown',`Essai introuvable : ${p.trialRef}.`,'resolve');
      if(trial.verdict!==null)return fault('barehands_calibration_trial_resolved',
        `${trial.ref} est déjà jugé (${trial.verdict}).`,'resolve');
      if(trial.state==='accepted')return fault('barehands_calibration_trial_resolved',
        `${trial.ref} a déjà été gardé.`,'resolve');
      const {set,meta}=measurementState();
      const beforeRefs=Array.isArray(p.beforeRefs)?p.beforeRefs:[];
      const afterRefs=Array.isArray(p.afterRefs)?p.afterRefs:[];
      /* **Avant = sous l'état d'avant l'essai, après = sous l'essai.** Le
         parcours a noté l'essai de chaque ligne ; l'agent ne peut pas faire
         passer une mesure d'avant pour une mesure d'après. */
      /* Par **état effectif** (round 5) : « avant » = prises sous l'état sur
         lequel l'essai a été appliqué — y compris sous un essai précédent
         gardé —, « après » = sous l'essai. */
      const misplacedAfter=afterRefs.filter(ref=>meta[ref]&&meta[ref].stateId!==trial.stateId);
      const misplacedBefore=beforeRefs.filter(ref=>meta[ref]&&meta[ref].stateId!==trial.baseStateId);
      if(misplacedAfter.length||misplacedBefore.length)
        return fault('barehands_calibration_refs_misplaced',
          [misplacedAfter.length?`prises hors de ${trial.ref} : ${misplacedAfter.slice(0,6).join(', ')}`:'',
            misplacedBefore.length?`pas prises avant ${trial.ref} : ${misplacedBefore.slice(0,6).join(', ')}`:'']
            .filter(Boolean).join(' ; ')+'.','resolve');
      /* **Un essai qu'aucune mesure n'a vu** (annulé avant qu'on refasse
         l'exercice) ne se juge ni « mieux » ni « pareil » : rien ne le
         montre. « inconclusive » (au prix `inconclusiveFactor`) ou « worse »
         soutenu par la plainte de l'utilisateur. */
      const unmeasured=!Object.keys(meta).some(ref=>meta[ref]&&meta[ref].stateId===trial.stateId);
      if(unmeasured&&p.verdict==='no_change')
        return fault('barehands_calibration_trial_unmeasured',
          `Aucune mesure n’a été prise sous ${trial.ref} : « no_change » ne se constate pas sans mesure. Refais l’exercice (${trial.exercises.join(', ')||'aucun'}), ou juge « improved »/« worse » sur le retour de l’utilisateur, ou « inconclusive ».`,'resolve');
      /* **Même exercice des deux côtés, et le bon** (reprise QA, round 4). */
      const stagesOf=refs=>[...new Set(refs.map(ref=>meta[ref]&&meta[ref].stage).filter(Boolean))].sort();
      const beforeStages=stagesOf(beforeRefs),afterStages=stagesOf(afterRefs);
      const offExercise=[...beforeStages,...afterStages].filter(stage=>!trial.exercises.includes(stage));
      if(offExercise.length)
        return fault('barehands_calibration_refs_off_exercise',
          `${trial.ref} se juge sur ${trial.exercises.join(', ')||'aucun exercice'} ; mesures citées prises sur ${[...new Set(offExercise)].join(', ')}.`,'resolve');
      if(beforeStages.length&&afterStages.length&&beforeStages.join()!==afterStages.join())
        return fault('barehands_calibration_refs_mismatched',
          `Avant (${beforeStages.join(', ')}) et après (${afterStages.join(', ')}) ne viennent pas du même exercice.`,'resolve');
      const h=findHypothesis(trial.hypothesisRef);
      const evidenceMetrics=[...new Set(h.record.evidenceRefs.map(ref=>{
        const e=evidence.find(x=>x.record.ref===ref);return e?e.record.metric:null}).filter(Boolean))];
      const offMetric=(Array.isArray(p.comparisons)?p.comparisons:[])
        .filter(c=>c&&evidenceMetrics.length&&!evidenceMetrics.includes(c.metric)).map(c=>c.metric);
      if(offMetric.length)
        return fault('barehands_calibration_comparison_off_evidence',
          `${h.record.ref} repose sur ${evidenceMetrics.join(', ')} : comparer ${offMetric.join(', ')} ne la juge pas.`,'resolve');
      const afterEpisodes=afterRefs.filter(ref=>ref.startsWith('ep-')).length;
      const afterExercises=afterRefs.filter(ref=>!ref.startsWith('ep-')&&!ref.startsWith('se-')).length;
      if(['improved','worse','no_change'].includes(p.verdict)&&Array.isArray(p.comparisons)&&p.comparisons.length
        &&!afterExercises&&afterEpisodes<MIN_AFTER_EPISODES)
        return fault('barehands_calibration_too_few_measures',
          `${afterEpisodes} pincement(s) mesuré(s) sous ${trial.ref} : il en faut ${MIN_AFTER_EPISODES} pour un verdict chiffré. Refais l’exercice, ou juge sur l’avis noté de l’utilisateur, ou « inconclusive ».`,'resolve');
      const feedbackRefs=Array.isArray(p.feedbackRefs)?p.feedbackRefs:[];
      const cited=feedbackRefs.map(findFeedback).filter(Boolean);
      const resolved=contract(C.resolveTrialOutcome,{schemaVersion:V,kind:'trial_outcome',trialRef:trial.ref,
        verdict:p.verdict,comparisons:p.comparisons||[],beforeRefs,afterRefs,hypothesisRefs:[h.record.ref],
        feedbackRefs},set,{appliedAt:trial.appliedAt,feedback:cited,hypotheses:[h.record]});
      if(resolved.refusal)return refuse(REFUSED,resolved.refusal,'resolve');
      const verdict=resolved.value.outcome.verdict;
      const before=h.record.confidence;
      let confidence=before,status=h.record.status;
      const R=CONFIDENCE_RULE;
      /* Sur quoi repose le verdict : un delta mesuré dans son sens, ou l'avis
         noté seul. */
      const measuredDirection=verdict==='improved'?'better':verdict==='worse'?'worse':null;
      const basis=measuredDirection&&resolved.value.deltas.some(dl=>dl.direction===measuredDirection)?'measured'
        :(verdict==='improved'||verdict==='worse')&&resolved.value.supportingFeedback?'feeling'
        :resolved.value.deltas.some(dl=>dl.direction!==null)?'measured':'none';
      if(verdict==='improved'&&basis==='feeling'){
        confidence=Math.max(before,Math.min(R.feelingCeiling,before+(R.feelingCeiling-before)*R.feelingGain));
      }else if(verdict==='improved'){
        confidence=Math.min(R.ceiling,before+(R.ceiling-before)*R.improvedGain);
        /* « supported » exige une preuve **mesurée** (décision 38). */
        const measured=h.record.evidenceRefs.some(ref=>{const e=evidence.find(x=>x.record.ref===ref);return e&&e.record.metric});
        status=measured?C.HYPOTHESIS_STATUS.SUPPORTED:h.record.status;
      }else if(FAILED_VERDICTS.includes(verdict)){
        confidence=before*(verdict==='worse'?R.worseFactor:R.noChangeFactor);
        status=confidence<R.rejectBelow?C.HYPOTHESIS_STATUS.REJECTED:C.HYPOTHESIS_STATUS.WEAKENED;
      }else{
        /* `inconclusive` : mesuré ou non, un essai qui ne tranche pas ne plaide
           pas pour sa cause — seul `improved` laisse la confiance monter ou
           rester (reprise QA, round 3). */
        confidence=before*R.inconclusiveFactor;
        if(confidence<R.rejectBelow)status=C.HYPOTHESIS_STATUS.REJECTED;
      }
      const updated=contract(C.createHypothesis,{...h.record,confidence:Math.round(confidence*1000)/1000,status,
        trialRefs:[...h.record.trialRefs,trial.ref]});
      if(updated.refusal)return refuse(REFUSED,updated.refusal,'resolve');
      h.record=updated.value;
      if(FAILED_VERDICTS.includes(verdict))h.failedAt=t();
      trial.verdict=verdict;
      trial.basis=basis;
      trial.deltas=resolved.value.deltas.map(dl=>({metric:dl.metric,aggregate:dl.aggregate,before:finite(dl.before),
        after:finite(dl.after),delta:finite(dl.delta),direction:dl.direction}));
      log('info','barehands.calibration_trial_resolved',{ref:trial.ref,verdict,hypothesis:h.record.ref,
        confidence:[before,h.record.confidence],status:h.record.status});
      emit({type:'trial_resolved',trial_ref:trial.ref,verdict,basis,hypothesis_ref:h.record.ref,
        confidence:h.record.confidence,status:h.record.status,source:acting});
      return ok({trialRef:trial.ref,verdict,basis,deltas:trial.deltas,
        hypotheses:[{ref:h.record.ref,cause:h.record.cause,before,confidence:h.record.confidence,status:h.record.status}]});
    }

    function rollbackTrial(){
      if(!running())return inactive('rollback');
      let receipt;
      try{receipt=d.trials().rollback()}
      catch(error){return fault('barehands_trial_rollback_failed',messageOf(error),'rollback')}
      if(!receipt||!receipt.ok)
        return refuse(REFUSED,[{code:receipt&&receipt.code||'barehands_trial_rollback_failed',
          message:receipt&&receipt.message||'retour arrière refusé'}],'rollback');
      for(const ref of receipt.undone||[]){const row=findTrial(ref);if(row)row.state='rolled_back';
        markFlow(C.SESSION_EVENT.TRIAL_ROLLED_BACK,ref,ref)}
      const undoneRows=(receipt.undone||[]).map(findTrial).filter(Boolean);
      if(undoneRows.length)generation=Math.min(...undoneRows.map(row=>row.baseStateId));
      const left=activeTrials().slice(-1)[0]||null;
      if((receipt.undone||[]).length)emit({type:'trial_rolled_back',trial_ref:receipt.trialId,
        undone:(receipt.undone||[]).slice(),source:acting});
      /* Annulé n'est pas jugé : l'essai reste à juger (`unresolved`). */
      log('info','barehands.calibration_trial_rolled_back',{ref:receipt.trialId,undone:receipt.undone,
        pendingVerdict:(receipt.undone||[]).filter(ref=>{const row=findTrial(ref);return row&&row.verdict===null})});
      return ok({trialRef:receipt.trialId,undone:(receipt.undone||[]).slice(),restored:{...receipt.applied},
        active:left?left.ref:null});
    }

    /* **Garder** : exige un accord. Voix : la citation, retrouvée par le
       Control Center dans ce que l'utilisateur a dit depuis l'essai
       (`verifiedBy: control_center`, décision 53) ; écran : le bouton lui-même. */
    async function acceptTrial(payload,source){
      if(!running())return inactive('accept');
      const consent=payload&&payload.consent;
      const fromUi=source==='ui';
      const voiced=!fromUi&&consent&&consent.source==='voice'&&consent.verifiedBy==='control_center'
        &&typeof consent.quote==='string'&&consent.quote.trim().length>=2;
      if(!fromUi&&!voiced)return fault('barehands_calibration_consent_missing',
        'Aucun accord de l’utilisateur n’accompagne cette demande : rien n’a été rangé.','accept');
      if(!activeTrials().length)return fault('barehands_trial_nothing_to_accept','Aucun essai en cours : rien à garder.','accept');
      /* **À l'écran, le bouton est un avis** : « Garder ce réglage » range un
         retour `fine` et juge chaque essai non jugé « improved » sur lui — le
         contrat (`resolveTrialOutcome`) le refuse si les mesures le démentent. */
      if(fromUi){
        for(const row of activeTrials().filter(x=>x.verdict===null)){
          /* **Les mesures d'abord** (round 5 : un essai mesurablement pire a été
             gardé sur le bouton). S'il y a des mesures sous l'essai sur son
             exercice, les comparaisons se calculent sur les métriques de la
             preuve, comme au jugement, et le contrat refuse un « mieux »
             démenti. L'avis seul ne suffit que sans mesure sous l'essai. */
          const plan=screenComparison(row);
          if(plan.refusal)return plan.refusal;
          const said=recordFeedback({categories:['fine'],text:'Garder ce réglage (bouton)'},'ui');
          if(!said.ok)return said;
          const judged=resolveTrial({trialRef:row.ref,verdict:'improved',comparisons:plan.comparisons,
            beforeRefs:plan.beforeRefs,afterRefs:plan.afterRefs,feedbackRefs:[said.result.feedback.ref]});
          if(!judged.ok)return judged;
        }
      }
      /* **Un essai se garde jugé, et pas « pire »** (reprise QA, round 4 : un
         essai jamais mesuré a été gardé). */
      const pending=activeTrials().find(x=>x.verdict===null);
      if(pending)return fault('barehands_calibration_trial_unresolved',
        `${pending.ref} n’est pas jugé : refais l’exercice (${pending.exercises.join(', ')||'aucun'}) ou note l’avis de l’utilisateur, puis juge-le avant de le garder.`,'accept');
      const worse=activeTrials().find(x=>x.verdict==='worse');
      if(worse)return fault('barehands_calibration_trial_worse',
        `${worse.ref} a été jugé « worse » : il ne se garde pas. Annule-le.`,'accept');
      let receipt;
      try{receipt=await d.trials().accept()}
      catch(error){return fault('barehands_trial_accept_failed',messageOf(error),'accept')}
      if(!receipt||!receipt.ok)
        return refuse(REFUSED,[{code:receipt&&receipt.code||'barehands_trial_accept_failed',
          message:receipt&&receipt.message||'acceptation refusée'}],'accept');
      const kept=activeTrials();
      const basis=kept.some(x=>x.basis==='feeling')?'feeling':kept.some(x=>x.basis==='measured')?'measured':'none';
      const record={source:fromUi?'ui':'voice',quote:fromUi?'':consent.quote.trim().slice(0,200)};
      consents.push({...record,t:t(),trialRef:receipt.trialId});
      for(const row of kept){row.state='accepted';markFlow(C.SESSION_EVENT.TRIAL_ACCEPTED,row.ref,row.ref)}
      log('info','barehands.calibration_trial_accepted',{ref:receipt.trialId,source:record.source,
        accepted:receipt.accepted});
      return ok({trialRef:receipt.trialId,accepted:{...receipt.accepted},applied:{...receipt.applied},basis,
        consent:record});
    }

    /* Le jugement que le bouton « Garder » demande : comparaisons sur les
       métriques de la preuve, mesures d'avant (état de base) et d'après (état
       de l'essai) prises sur l'exercice de l'essai. */
    function screenComparison(row){
      const {meta}=measurementState();
      const on=(stateId,stages)=>Object.keys(meta).filter(ref=>meta[ref]&&meta[ref].stateId===stateId
        &&stages.includes(meta[ref].stage));
      const afterRefs=on(row.stateId,row.exercises);
      if(!afterRefs.length)return {comparisons:[],beforeRefs:[],afterRefs:[]};
      const afterStages=[...new Set(afterRefs.map(ref=>meta[ref].stage))];
      const beforeRefs=on(row.baseStateId,afterStages);
      const h=findHypothesis(row.hypothesisRef);
      const seen=new Set(),comparisons=[];
      for(const ref of h?h.record.evidenceRefs:[]){
        const e=evidence.find(x=>x.record.ref===ref);
        if(!e||!e.record.metric)continue;
        const key=`${e.record.metric}/${e.record.aggregate}`;
        if(!seen.has(key)){seen.add(key);comparisons.push({metric:e.record.metric,aggregate:e.record.aggregate})}
      }
      if(!comparisons.length||!beforeRefs.length)return {comparisons:[],beforeRefs:[],afterRefs:[]};
      const episodes=afterRefs.filter(ref=>ref.startsWith('ep-')).length;
      if(episodes&&episodes<MIN_AFTER_EPISODES&&!afterRefs.some(ref=>!ref.startsWith('ep-')))
        return {refusal:fault('barehands_calibration_too_few_measures',
          `${episodes} pincement(s) sous ${row.ref} : refaire l’exercice avant de garder.`,'accept')};
      return {comparisons,beforeRefs,afterRefs};
    }
    /* **Refaire l'exercice qui juge l'essai** : nommé (liste fermée des
       étapes), ou, sans nom, celui de l'essai non jugé en cours, ou celui qui
       vient d'être joué. */
    function rerun(payload){
      const p=payload&&typeof payload==='object'?payload:{};
      if(p.exercise!==undefined&&p.exercise!==null&&!C.STAGES.includes(p.exercise))
        return fault('barehands_calibration_exercise_unknown',`Exercice inconnu : ${String(p.exercise).slice(0,40)}.`,'rerun');
      const open=trials.find(x=>x.state==='active'&&x.verdict===null&&x.exercises.length);
      const stage=p.exercise||(open?open.exercises[0]:null);
      /* Refaire ne saute pas en avant vers une étape jamais jouée (reprise QA). */
      const f=running()?flow():null;
      if(stage&&f&&typeof f.canRerun==='function'){
        const can=f.canRerun(stage);
        if(can&&!can.ok&&can.code==='barehands_calibration_exercise_not_played')
          return fault(can.code,`${stage} n’a pas encore été joué : on ne saute pas en avant, on le jouera à son tour.`,'rerun');
      }
      return move('rerun',stage);
    }
    function move(op,stageId){
      if(!running())return inactive(op);
      const f=flow();
      if(typeof f.concluded==='function'&&f.concluded())
        return fault('barehands_calibration_exercise_unavailable',
          'La calibration est au récapitulatif : il n’y a plus d’exercice à refaire ni à passer.',op);
      const step=typeof f[op]==='function'?actAs(f,()=>stageId?f[op](stageId):f[op]()):null;
      if(step===null||step===undefined)
        return fault('barehands_calibration_exercise_unavailable','Aucun exercice à cet endroit du parcours.',op);
      log('info',`barehands.calibration_${op}`,{step:exercise().step});
      return ok({exercise:exercise()});
    }
    /* **Continuer** (Slice 07 adaptative, décisions 56 et 57) : la même porte
       que les boutons « Valider l'étape » et « Passer » (`flow.next(raison)`).
       Revue d'un exercice réussi : il est validé. Sinon il est passé, et
       passer exige la raison de l'utilisateur (liste fermée). */
    function continueFlow(payload){
      if(!running())return inactive('next');
      const p=payload&&typeof payload==='object'?payload:{};
      const reason=p.reason===undefined||p.reason===null?null:String(p.reason);
      if(reason!==null&&!C.SKIP_REASONS.includes(reason))
        return fault('barehands_calibration_skip_reason_unknown',
          `Raison inconnue : ${reason.slice(0,40)} (${C.SKIP_REASONS.join(', ')}).`,'next');
      const f=flow();
      if(typeof f.concluded==='function'&&f.concluded())
        return fault('barehands_calibration_exercise_unavailable',
          'La calibration est au récapitulatif : il n’y a plus d’exercice à valider ni à passer.','next');
      /* **Un essai attend sa mesure sur cet exercice** (reprise QA) : on ne
         quitte pas l'exercice qui doit le juger — refais-le, juge l'essai ou
         défais-le d'abord. */
      const here=typeof f.stepId==='function'?f.stepId():null;
      const waiting=trials.find(x=>x.state==='active'&&x.verdict===null&&x.exercises.includes(here));
      if(waiting)return fault('barehands_calibration_trial_pending',
        `L’essai ${waiting.ref} attend sa mesure sur ${here} : refais l’exercice, juge l’essai ou annule-le avant de continuer.`,'next');
      let answer=null;
      try{answer=typeof f.next==='function'?actAs(f,()=>f.next(reason)):null}
      catch(error){return fault('barehands_calibration_page_error',messageOf(error),'next')}
      if(!answer||!answer.ok){
        const code=answer&&answer.code||'barehands_calibration_exercise_unavailable';
        return fault(code,code==='barehands_calibration_skip_reason_required'
          ?`Passer cet exercice exige la raison que l’utilisateur a donnée : ${C.SKIP_REASONS.join(', ')}. Demande-lui pourquoi.`
          :'Aucun exercice à cet endroit du parcours.','next');
      }
      log('info','barehands.calibration_next',{step:exercise().step,reason,decision:answer.decision});
      /* Le reçu dit **ce qui a été décidé** : validé, ou passé. */
      return ok({exercise:exercise(),decision:answer.decision==='skipped'?'skipped':'validated'});
    }
    /* **L'explication de l'assistant pour la revue** (décision 56) : une
       phrase tirée de l'état de la séance — l'essai qui attend d'être jugé
       sur cet exercice, sinon le dernier essai jugé, sinon la dernière piste
       ouverte — en mots d'utilisateur, sans nombre. `null` s'il n'y a rien. */
    function explain(stage){
      /* **Cet exercice seulement** (reprise QA) : un essai ou une piste
         d'un autre exercice ne s'explique pas dans cette revue. Et **aucun
         chiffre** : une phrase qui en porterait un est refusée (journalisée),
         le code chiffre et l'écran montre les mesures. */
      const words=cause=>CAUSE_WORDS[cause]||'une piste';
      const causeOf=row=>{const h=findHypothesis(row.hypothesisRef);return h?h.record.cause:null};
      const onStage=x=>x.exercises.includes(stage);
      let text=null;
      const pending=trials.find(x=>x.state==='active'&&x.verdict===null&&onStage(x));
      const judged=trials.filter(x=>x.verdict!==null&&onStage(x)).slice(-1)[0];
      const open=hypotheses.filter(h=>(h.record.status==='open'||h.record.status==='supported')
        &&(CAUSE_EXERCISES[h.record.cause]||[]).includes(stage)).slice(-1)[0];
      if(pending)text=`Essai en cours : ${words(causeOf(pending))}. Refaites l’exercice pour voir si c’est mieux.`;
      else if(judged){
        const verdict=VERDICT_WORDS[judged.verdict]||judged.verdict;
        const kept=judged.state==='accepted'?' ; réglage gardé':judged.state==='rolled_back'?' ; réglage défait':'';
        text=`Dernier essai (${words(causeOf(judged))}) : ${verdict}${kept}.`;
      }else if(open)text=`Piste à tester : ${words(open.record.cause)}.`;
      if(text!==null&&/\d/.test(text)){log('warn','barehands.calibration_explain_digits',{stage});return null}
      return text;
    }

    /* **Ce que le cerveau reçoit avec une revue** (retour du 28/09) : pour
       l'étape, les valeurs enregistrées et effectives des réglages qui la
       concernent, l'historique de ses essais et décisions, et les derniers
       ressentis notés. Des faits de la séance, bornés ; rien d'interprété. */
    function reviewContext(stage){
      const keys=new Set();
      for(const cause of Object.keys(CAUSE_EXERCISES))
        if(CAUSE_EXERCISES[cause].includes(stage))for(const key of C.HYPOTHESIS_CAUSE_KEYS[cause]||[])keys.add(key);
      const values=valuesOf([...keys].filter(key=>specOf(key)));
      const f=flow();
      const s=f&&typeof f.session==='function'?f.session():null;
      const history=(s&&Array.isArray(s.reviews)?s.reviews:[]).filter(r=>r.stage===stage).slice(-6)
        .map(r=>({decision:r.decision,status:r.status,attempt:r.attempt,reason:r.reason||null}));
      const onStage=trials.filter(x=>x.exercises.includes(stage)).slice(-4).map(x=>{
        const h=findHypothesis(x.hypothesisRef);
        return {ref:x.ref,cause:h?h.record.cause:null,state:x.state,verdict:x.verdict,basis:x.basis||null,
          patch:roundedNumbers(x.patch)};
      });
      const said=feedback.filter(fb=>fb.stage===stage).slice(-3).map(fb=>({ref:fb.ref,text:fb.text.slice(0,200),
        categories:fb.categories.slice()}));
      return Object.freeze({values:Object.keys(values).map(key=>({key,label:KEY_LABELS[key]||key,
        saved:rounded(values[key].saved),effective:rounded(values[key].effective)})),history,trials:onStage,feedback:said});
    }
    /* **Le point d'entrée de la voix** (canal de commandes). Avant toute porte :
       cette page tient-elle la séance ? Deux onglets en calibration : le
       serveur n'en accepte qu'une (décision 50), et une commande remise par le
       long-poll à l'autre onglet ne doit pas y être appliquée. `deps.held`
       (le rapporteur de séance) le dit ; absent, la page n'a pas de rapporteur
       et rien n'est piloté par la voix. Les commandes de repli à l'écran, elles,
       appellent les portes directement : elles sont la page elle-même. */
    function command(op,payload){
      if(!running())return inactive(op);
      const held=typeof d.held==='function'?!!d.held():false;
      if(!held){
        const why=typeof d.refusal==='function'?d.refusal():null;
        return refuse(INACTIVE,[{code:INACTIVE,message:why&&why.code==='barehands_calibration_session_busy'
          ?'Une autre page du Control Center tient la séance de calibration : celle-ci n’est pas pilotée par la voix.'
          :'La séance de calibration de cette page n’est pas (encore) reconnue par le Control Center.'}],op);
      }
      /* **Le cerveau propose, il n'applique pas** (retour du 28/09) : pas
         d'opération « apply » ici. `prepare` rend une proposition visible ;
         `commit` l'applique seulement sur l'accord vérifié de l'utilisateur. */
      acting='voice';
      try{
        return op==='status'?status():op==='feedback'?recordFeedback(payload,'voice')
          :op==='hypothesis'?proposeHypothesis(payload):op==='prepare'?prepareTrial(payload)
          :op==='commit'?commitProposal(payload,'voice')
          :op==='resolve'?resolveTrial(payload):op==='rollback'?rollbackTrial()
          :op==='accept'?acceptTrial(payload,'voice'):op==='rerun'?rerun(payload):op==='next'?continueFlow(payload)
          :fault('barehands_command_unknown',`Opération inconnue : ${op}.`,op);
      }finally{acting='ui'}
    }

    return Object.freeze({
      command,
      status,recordFeedback,proposeHypothesis,applyTrial,resolveTrial,rollbackTrial,acceptTrial,
      /* Les propositions (retour du 28/09) : préparer (cerveau), corriger,
         remettre, écarter (écran), valider (écran ou voix vérifiée). */
      prepareTrial,editProposal,resetProposalKey,discardProposal,commitProposal,
      proposal:()=>{const row=proposalRow(proposal);return row?Object.freeze(row):null},
      valuesOf:keys=>valuesOf((keys||[]).filter(key=>specOf(key))),
      reviewContext,
      rerun:payload=>rerun(payload),next:payload=>continueFlow(payload),
      /* L'explication courte de la revue (Slice 07 adaptative). */
      explain,
      /* Ce qui a été gardé pendant la séance, en mots d'utilisateur, pour le
         rapport de fin (Slice 07 adaptative, décision 59). */
      acceptedSummary:()=>Object.freeze(trials.filter(x=>x.state==='accepted').map(x=>{
        const h=findHypothesis(x.hypothesisRef);
        const cause=h?CAUSE_WORDS[h.record.cause]:null;
        return `Correction gardée : ${cause||'réglage d’essai'}${x.basis==='feeling'?' (sur votre ressenti)'
          :x.basis==='user_unverified'?' (acceptée par vous · non revérifiée sur cet exercice)':''}.`;
      })),
      /* Le numéro de l'état effectif courant, noté sur chaque ligne de mesures. */
      stateRef:()=>generation,
      /* Le parcours tient-il le verdict de cette étape pour un essai non jugé ? */
      holdAfterResult:stage=>trials.some(x=>x.state==='active'&&x.verdict===null&&x.exercises.includes(stage)),
      /* Pour l'écran de repli : y a-t-il un essai à annuler ou à garder ? */
      activeTrial:()=>{const row=activeTrials().slice(-1)[0];return row?Object.freeze(trialRow(row)):null},
      consents:()=>Object.freeze(consents.map(c=>Object.freeze({...c}))),
    });
  }

  /* ------------------------------------------------------------------
     Les commandes de repli à l'écran (décision 55). Pour qui ne parle pas :
     quatre ressentis du vocabulaire fermé, et « Annuler l'essai » / « Garder
     ce réglage » quand un essai est en cours. **Les mêmes portes** que la voix
     (`recordFeedback`, `rollbackTrial`, `acceptTrial`) : un bouton n'a pas de
     chemin à lui. Le repli ne refait pas la revue d'exercice (Slice 07). */
  const COACH_STYLE_ID='jfCoachStyle';
  const FEEDBACK_BUTTONS=Object.freeze([
    Object.freeze({category:'release_sticky',label:'Le relâchement colle'}),
    Object.freeze({category:'false_click',label:'Clics fantômes'}),
    Object.freeze({category:'hard_to_aim',label:'Difficile de viser'}),
    Object.freeze({category:'fine',label:'C’est bien'}),
  ]);
  const COACH_CSS=(sel)=>`
${sel} .jf-coach{display:flex;flex-direction:column;align-items:center;gap:10px;width:100%;
  padding-top:12px;margin-top:4px;border-top:1px solid rgba(255,255,255,.08)}
${sel} .jf-coach-row{display:flex;flex-wrap:wrap;gap:8px;justify-content:center;align-items:center}
${sel} .jf-coach-label{font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--jf-muted);
  margin-right:4px}
${sel} .jf-coach button{padding:7px 14px;font-size:12px}
${sel} .jf-coach button[disabled]{opacity:.45;cursor:default}
${sel} .jf-coach-trial{gap:10px}
${sel} .jf-coach-trial[hidden],${sel} .jf-coach-feel[hidden]{display:none}
${sel} .jf-coach-trial span{font-family:var(--jf-sans);font-size:13px;color:var(--jf-soft)}
${sel} .jf-coach-line{min-height:18px;font-family:var(--jf-sans);font-size:12px;color:var(--jf-muted)}
${sel} .jf-coach-line[data-kind="ok"]{color:var(--jf-ok)}
${sel} .jf-coach-line[data-kind="bad"]{color:var(--jf-bad)}
@media (max-width:640px){${sel} .jf-coach-label{flex-basis:100%;text-align:center;margin:0}}`;

  function createCoachPanel(deps){
    const d=deps||{};
    const doc=d.document;
    if(!doc||typeof doc.createElement!=='function')
      throw new RangeError('createCoachPanel exige `document`');
    if(!d.session)throw new RangeError('createCoachPanel exige la séance (`session`)');
    const log=typeof d.log==='function'?d.log:()=>{};
    let node=null,trialRow=null,trialText=null,line=null,busy=false,feelRow=null,feelingsShown=false;
    const buttons=[];
    const el=(tag,cls,text)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
    function say(text,kind){if(!line)return;line.textContent=text;line.setAttribute('data-kind',kind||'')}
    function paint(){
      const active=d.session.activeTrial();
      if(trialRow)trialRow.hidden=!active;
      /* Les ressentis s'ouvrent par « Ajuster » dans la revue (Slice 07
         adaptative, décision 56) : une seule entrée vers l'assistant, au
         moment où l'exercice vient d'être mesuré. */
      if(feelRow)feelRow.hidden=!feelingsShown;
      if(trialText)trialText.textContent=active?'Un réglage d’essai est en cours.':'';
      for(const b of buttons)b.disabled=busy;
    }
    /* Une action : busy pendant, le résultat **dit** (ligne vivante), le refus
       aussi, et le bouton rendu dans tous les cas (RÈGLE ZÉRO). */
    async function run(action,okText,op){
      if(busy)return null;
      busy=true;paint();
      try{
        const answer=await action();
        if(answer&&answer.ok){say(okText(answer),'ok');return answer}
        say(userText(answer&&answer.errors&&answer.errors[0]?answer.errors[0].code:''),'bad');
        return answer;
      }catch(error){
        say('Pas fait : une erreur est survenue, elle est dans le journal.','bad');
        log('error','barehands.calibration_coach_failed',{op,error:messageOf(error)});
        return null;
      }finally{busy=false;paint()}
    }
    function mount(region){
      if(node||!region)return node;
      if(!doc.getElementById(COACH_STYLE_ID)){
        const style=el('style');style.id=COACH_STYLE_ID;style.textContent=COACH_CSS(d.rootSelector||'#jarvisFlow');
        (doc.head||doc.body).appendChild(style);
      }
      node=el('div','jf-coach');
      node.setAttribute('data-calibration-coach','1');
      node.setAttribute('role','group');
      node.setAttribute('aria-label','Votre ressenti et le réglage d’essai');
      const feel=el('div','jf-coach-row jf-coach-feel');
      feelRow=feel;
      feel.appendChild(el('span','jf-coach-label','Qu’est-ce qui ne va pas ?'));
      for(const item of FEEDBACK_BUTTONS){
        const b=el('button','',item.label);
        b.setAttribute('type','button');
        b.setAttribute('data-coach-feedback',item.category);
        b.addEventListener('click',()=>run(()=>d.session.recordFeedback({categories:[item.category],text:item.label},'ui'),
          ()=>`Noté : ${item.label.toLowerCase()}.`,'feedback'));
        buttons.push(b);feel.appendChild(b);
      }
      trialRow=el('div','jf-coach-row jf-coach-trial');
      trialText=el('span');
      const undo=el('button','','Annuler l’essai');
      undo.setAttribute('type','button');undo.setAttribute('data-coach-action','rollback');
      /* « Annuler » est aussi une parole (reprise QA) : elle se range comme
         retour, pour que le jugement de l'essai puisse la citer. */
      undo.addEventListener('click',()=>run(()=>{
        const answer=d.session.rollbackTrial();
        if(answer&&answer.ok)d.session.recordFeedback({categories:['unclear'],text:'Annuler l’essai (bouton)'},'ui');
        return answer;
      },answer=>{
        const row=d.session.status().ok?d.session.status().result.trials.find(x=>x.ref===answer.result.trialRef):null;
        return row&&row.verdict===null?'Essai annulé : le réglage d’avant est revenu. Dites ce que vous en pensiez.'
          :'Essai annulé : le réglage d’avant est revenu.';
      },'rollback'));
      const keep=el('button','primary','Garder ce réglage');
      keep.setAttribute('type','button');keep.setAttribute('data-coach-action','accept');
      keep.addEventListener('click',()=>run(()=>d.session.acceptTrial({},'ui'),answer=>answer&&answer.result&&answer.result.basis==='feeling'
        ?'Réglage gardé sur votre ressenti, sans mesure pour le confirmer.':'Réglage gardé et enregistré.','accept'));
      buttons.push(undo,keep);
      trialRow.appendChild(trialText);trialRow.appendChild(undo);trialRow.appendChild(keep);
      line=el('div','jf-coach-line');line.setAttribute('aria-live','polite');
      node.appendChild(feel);node.appendChild(trialRow);node.appendChild(line);
      region.appendChild(node);
      paint();
      return node;
    }
    /* Montrer ou cacher les ressentis (« Ajuster » de la revue) ; montrés,
       le focus va au premier. */
    function showFeelings(on){
      feelingsShown=!!on;paint();
      if(feelingsShown&&buttons[0]&&typeof buttons[0].focus==='function')buttons[0].focus();
      return feelingsShown;
    }
    return Object.freeze({mount,refresh:paint,announce:(text,kind)=>say(String(text||''),kind),showFeelings,
      feelingsShown:()=>feelingsShown,
      close(){if(node&&typeof node.remove==='function')node.remove();node=null;trialRow=null;trialText=null;line=null;
        feelRow=null;feelingsShown=false;buttons.length=0},
      node:()=>node});
  }

  /* ------------------------------------------------------------------
     **Le panneau de calibration** (retour du 28/09). Un panneau vertical
     flottant, à gauche, visible pendant toute la calibration : il rend
     visible ce que le runtime constate, ce que l'assistant propose et ce que
     l'utilisateur décide — sans avoir à croire la phrase prononcée.

       État de l'exercice   étape, essai n°, verdict, cause déterministe,
                            critères un par un (le C)
       Résultats            chaque mesure avec son interprétation (couleur,
                            marque **et** mot, calculés par le parcours)
       Proposition          la phrase de l'assistant, puis par réglage :
                            enregistré / effectif / proposé, un curseur et un
                            champ, « remettre » ; « Proposition non appliquée »
       Actions              Appliquer et refaire · Appliquer et continuer ·
                            Écarter, et le reçu de ce qui a été fait

     Déplaçable (par son en-tête), repliable (une languette qui dit l'état :
     « C · essai 3 · 2 changements proposés »), borné dans la fenêtre, avec
     son propre défilement ; 372 px de large, à gauche, jamais sur la zone
     centrale où l'on regarde sa main. Il lit tout chez la séance et le
     parcours à chaque `refresh()` : il ne tient aucun état métier. */
  const PANEL_STYLE_ID='jfCalPanelStyle';
  const PANEL_WIDTH=372;
  const PANEL_MARGIN=12;
  const STAGE_SHORT=Object.freeze({neutral:'Repos',c_pose:'C',pinch_primary:'Pincement',hold_release:'Tenir-relâcher',
    pinch_secondary:'Clic droit',aim:'Visée',drag:'Déplacer',resize:'Redimensionner',drop:'Déposer',
    natural_motion:'Mouvement libre',aim_no_click:'Viser sans cliquer'});
  const STATUS_VIEW=Object.freeze({ok:['good','✓ Réussi'],failed:['bad','✕ Échec'],skipped:['neutral','– Passé']});
  const STEP_WORDS=Object.freeze({applied:'Changements appliqués',verified:'Valeurs effectives vérifiées',
    rerun:'Exercice relancé',saved:'Réglage enregistré',
    advanced:'Étape soldée : accepté par vous · non revérifié sur cet exercice'});
  const PANEL_CSS=(sel)=>`
${sel} .jf-cal{position:fixed;z-index:6;left:${PANEL_MARGIN}px;top:72px;width:min(${PANEL_WIDTH}px,calc(100vw - ${2*PANEL_MARGIN}px));
  max-height:calc(100vh - 96px);display:flex;flex-direction:column;border-radius:12px;
  background:rgba(8,16,30,.94);border:1px solid rgba(255,255,255,.1);box-shadow:0 12px 40px rgba(0,0,0,.45);
  font-family:var(--jf-sans);font-size:13px;line-height:1.45;color:#e9f1fb;text-align:left}
${sel} .jf-cal[data-collapsed="1"]{width:auto;max-width:calc(100vw - ${2*PANEL_MARGIN}px)}
${sel} .jf-cal-head{display:flex;align-items:center;gap:8px;padding:8px 10px;cursor:grab;user-select:none;
  border-bottom:1px solid rgba(255,255,255,.08);touch-action:none}
${sel} .jf-cal[data-collapsed="1"] .jf-cal-head{border-bottom:0}
${sel} .jf-cal-title{flex:1;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--jf-muted)}
${sel} .jf-cal[data-collapsed="1"] .jf-cal-title{letter-spacing:.04em;text-transform:none;font-size:13px;color:#e9f1fb}
${sel} .jf-cal-head button{padding:2px 9px;font-size:12px;min-width:28px}
${sel} .jf-cal-body{overflow:auto;padding:4px 12px 12px;overscroll-behavior:contain}
${sel} .jf-cal[data-collapsed="1"] .jf-cal-body{display:none}
${sel} .jf-cal-zone{padding:10px 0;border-bottom:1px solid rgba(255,255,255,.07)}
${sel} .jf-cal-zone:last-child{border-bottom:0}
${sel} .jf-cal-zone h4{margin:0 0 6px;font-size:10.5px;font-weight:500;letter-spacing:.18em;text-transform:uppercase;color:var(--jf-muted)}
${sel} .jf-cal-stage{font-size:15px;font-weight:600}
${sel} .jf-cal-line{margin:2px 0;color:var(--jf-soft)}
${sel} .jf-cal ul{margin:4px 0 0;padding:0;list-style:none}
${sel} .jf-cal li{display:flex;gap:8px;align-items:baseline;padding:3px 0;border-bottom:1px solid rgba(255,255,255,.05)}
${sel} .jf-cal li span{flex:1;color:var(--jf-soft)}
${sel} .jf-cal li b{font-weight:600;font-variant-numeric:tabular-nums;white-space:nowrap}
${sel} .jf-cal [data-assessment]{font-style:normal;font-weight:600;white-space:nowrap}
${sel} .jf-cal [data-assessment="good"]{color:#6ff2b0}
${sel} .jf-cal [data-assessment="warning"]{color:#ffd27a}
${sel} .jf-cal [data-assessment="bad"]{color:#ffa3a3}
${sel} .jf-cal [data-assessment="neutral"]{color:var(--jf-muted)}
${sel} .jf-cal-badge{display:inline-block;margin:6px 0;padding:2px 8px;border-radius:999px;font-size:11.5px;
  border:1px solid rgba(255,210,122,.5);color:#ffd27a}
${sel} .jf-cal-badge[data-state="committed"]{border-color:rgba(111,242,176,.5);color:#6ff2b0}
${sel} .jf-cal-badge[data-state="stale"],${sel} .jf-cal-badge[data-state="discarded"],${sel} .jf-cal-badge[data-state="superseded"]{border-color:rgba(147,166,189,.5);color:var(--jf-muted)}
${sel} .jf-cal-key{margin-top:8px;padding:8px;border-radius:8px;background:rgba(255,255,255,.04)}
${sel} .jf-cal-key-name{font-weight:600}
${sel} .jf-cal-values{display:grid;grid-template-columns:auto 1fr;column-gap:10px;margin:4px 0;font-variant-numeric:tabular-nums}
${sel} .jf-cal-values span{color:var(--jf-muted)}
${sel} .jf-cal-edit{display:flex;gap:8px;align-items:center}
${sel} .jf-cal-edit input[type="range"]{flex:1;min-width:0;accent-color:var(--jf-accent)}
${sel} .jf-cal-edit input[type="number"]{width:5.5em;padding:2px 4px;border-radius:6px;border:1px solid rgba(255,255,255,.18);
  background:rgba(0,0,0,.3);color:#e9f1fb;font:inherit}
${sel} .jf-cal-edit button{padding:2px 8px;font-size:12px}
${sel} .jf-cal-errors{color:#ffa3a3}
${sel} .jf-cal-actions{display:flex;flex-wrap:wrap;gap:8px}
${sel} .jf-cal-actions button{padding:7px 12px;font-size:12.5px}
${sel} .jf-cal-actions button[disabled],${sel} .jf-cal-edit button[disabled]{opacity:.45;cursor:default}
${sel} .jf-cal-receipt li span{color:#e9f1fb}
@media (max-width:640px){${sel} .jf-cal{top:auto;bottom:${PANEL_MARGIN}px;max-height:45vh}}
@media (prefers-reduced-motion:no-preference){${sel} .jf-cal{transition:box-shadow .15s}}`;
  const frNum=(value,digits)=>typeof value==='number'&&Number.isFinite(value)
    ?value.toFixed(digits).replace('.',','):'—';
  const digitsOf=step=>{const text=String(step);const at=text.indexOf('.');return at<0?0:Math.min(4,text.length-at-1)};

  function createCalibrationPanel(deps){
    const d=deps||{};
    const doc=d.document;
    if(!doc||typeof doc.createElement!=='function')throw new RangeError('createCalibrationPanel exige `document`');
    if(!d.session)throw new RangeError('createCalibrationPanel exige la séance (`session`)');
    const log=typeof d.log==='function'?d.log:()=>{};
    const flow=()=>{try{return typeof d.flow==='function'?d.flow():null}catch(error){return null}};
    const viewport=()=>{try{return typeof d.viewport==='function'?d.viewport():{width:1280,height:720}}
      catch(error){return {width:1280,height:720}}};
    const storage=d.storage||null;
    const STORE_KEY='jarvis.barehands.calibrationPanel';
    let node=null,head=null,title=null,body=null,toggle=null;
    let collapsed=false,position=null,busy=false,held=false,pendingRefresh=false,lastAnswer=null;
    const el=(tag,cls,text)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
    function remember(){
      if(!storage)return;
      try{storage.setItem(STORE_KEY,JSON.stringify({collapsed,position}))}
      catch(error){/* intentional: a blocked storage only loses the panel's place */}
    }
    function recall(){
      if(!storage)return;
      try{
        const saved=JSON.parse(storage.getItem(STORE_KEY)||'null');
        if(saved&&typeof saved==='object'){collapsed=saved.collapsed===true;
          if(saved.position&&Number.isFinite(saved.position.left)&&Number.isFinite(saved.position.top))position=saved.position}
      }catch(error){/* intentional: an unreadable place falls back to the default */}
    }
    /* Borné dans la fenêtre : l'en-tête reste toujours attrapable. */
    function place(){
      if(!node||!position)return;
      const view=viewport();
      const left=Math.min(Math.max(PANEL_MARGIN,position.left),Math.max(PANEL_MARGIN,view.width-120));
      const top=Math.min(Math.max(PANEL_MARGIN,position.top),Math.max(PANEL_MARGIN,view.height-48));
      position={left,top};
      node.style.left=`${left}px`;node.style.top=`${top}px`;node.style.bottom='auto';
    }
    const read=()=>{
      const f=flow();
      const review=f&&typeof f.review==='function'?f.review():null;
      const stage=review?review.stage:f&&typeof f.stepId==='function'?f.stepId():null;
      let proposal=null;
      try{proposal=d.session.proposal()}catch(error){log('warn','barehands.calibration_panel_unreadable',{error:messageOf(error)})}
      return {review,stage,proposal,running:!!(f&&typeof f.isRunning==='function'&&f.isRunning())};
    };
    function tabText(state){
      const r=state.review;
      const short=STAGE_SHORT[state.stage]||'Calibration';
      const parts=[short];
      if(r)parts.push(`essai ${r.attempt}`);
      const p=state.proposal;
      if(p&&p.state==='pending'){const n=p.keys.length;parts.push(`${n} changement${n>1?'s':''} proposé${n>1?'s':''}`)}
      else if(r&&STATUS_VIEW[r.status])parts.push(STATUS_VIEW[r.status][1].slice(2).toLowerCase());
      return parts.join(' · ');
    }
    function zone(name,heading){
      const z=el('section','jf-cal-zone');z.setAttribute('data-zone',name);
      z.appendChild(el('h4','',heading));
      return z;
    }
    function row(label,valueText,assessment,word,mark){
      const li=el('li');
      li.appendChild(el('span','',label));
      if(valueText!==null&&valueText!==undefined)li.appendChild(el('b','',valueText));
      const i=el('i','',`${mark||''} ${word||''}`.trim());
      i.setAttribute('data-assessment',assessment||'neutral');
      li.appendChild(i);
      li.setAttribute('data-assessment',assessment||'neutral');
      return li;
    }
    function paintExercise(state){
      const z=zone('exercise','État de l’exercice');
      const r=state.review;
      z.appendChild(el('div','jf-cal-stage',r&&r.label?r.label:STAGE_SHORT[state.stage]||'—'));
      if(r){
        z.appendChild(el('p','jf-cal-line',`Essai ${r.attempt}`));
        const view=STATUS_VIEW[r.status]||['neutral','– Non jugé'];
        const verdict=el('p','jf-cal-line',view[1]);verdict.setAttribute('data-assessment',view[0]);
        verdict.setAttribute('data-panel-status',r.status||'');
        z.appendChild(verdict);
        if(r.cause){const why=el('p','jf-cal-line',r.cause);why.setAttribute('data-panel-cause','1');z.appendChild(why)}
        if(r.checks&&r.checks.length){
          const list=el('ul');list.setAttribute('data-panel-checks','1');
          for(const c of r.checks)list.appendChild(row(c.label,null,c.assessment,c.word,c.mark));
          z.appendChild(list);
        }
      }else z.appendChild(el('p','jf-cal-line',state.running?'Exercice en cours : les résultats viendront à sa fin.':'Pas d’exercice en cours.'));
      return z;
    }
    function paintResults(state){
      const z=zone('results','Résultats');
      const lines=state.review?state.review.lines:[];
      if(!lines.length){z.appendChild(el('p','jf-cal-line',state.review?'Aucune mesure chiffrée pour cet essai.':'—'));return z}
      const list=el('ul');list.setAttribute('data-panel-results','1');
      for(const line of lines){
        const li=row(line.label,line.text,line.assessment,line.word,line.mark);
        li.setAttribute('data-metric',line.metric);
        list.appendChild(li);
      }
      z.appendChild(list);
      return z;
    }
    function paintProposal(state){
      const z=zone('proposal','Proposition');
      const p=state.proposal;
      if(!p||p.state==='discarded'){
        z.appendChild(el('p','jf-cal-line',p?'Proposition écartée : rien n’a été appliqué.'
          :'Aucune proposition. Dites ce que vous ressentez : l’assistant proposera un réglage, que vous validerez ici.'));
        return z;
      }
      z.appendChild(el('p','jf-cal-line',p.summary));
      if(p.untouched)z.appendChild(el('p','jf-cal-line',p.untouched));
      const badge=el('span','jf-cal-badge',p.state==='pending'?'Proposition non appliquée'
        :p.state==='committed'?'Appliquée':p.state==='stale'?'Proposition périmée — rien n’a été appliqué'
        :'Remplacée par une nouvelle proposition');
      badge.setAttribute('data-state',p.state);badge.setAttribute('data-panel-badge','1');
      z.appendChild(badge);
      const editable=p.state==='pending'&&!busy;
      for(const k of p.keys){
        const box=el('div','jf-cal-key');box.setAttribute('data-panel-key',k.key);
        box.appendChild(el('div','jf-cal-key-name',KEY_LABELS[k.key]||k.key));
        const digits=digitsOf(k.step);
        const unit=UNIT_WORDS[k.unit]?` ${UNIT_WORDS[k.unit]}`:'';
        const grid=el('div','jf-cal-values');
        const cell=(label,value,attr)=>{grid.appendChild(el('span','',label));const b=el('b','',value);
          if(attr)b.setAttribute(attr,'1');grid.appendChild(b);return b};
        cell('Enregistré',`${frNum(k.saved,digits)}${unit}`,'data-value-saved');
        cell('Effectif',`${frNum(k.effective,digits)}${unit}${k.perHand?' (selon la main)':''}`,'data-value-effective');
        const delta=typeof k.effective==='number'?k.value-k.effective:null;
        const proposed=cell('Proposé',`${frNum(k.value,digits)}${unit}${delta!==null&&Math.abs(delta)>1e-9
          ?` (${delta>0?'+':'−'}${frNum(Math.abs(delta),digits)})`:''}${k.value!==k.proposed?' · corrigé':''}`,'data-value-proposed');
        box.appendChild(grid);
        const edit=el('div','jf-cal-edit');
        const slider=el('input');slider.type='range';
        for(const [attr,value] of [['min',k.min],['max',k.max],['step',k.step]]){slider.setAttribute(attr,String(value));slider[attr]=String(value)}
        slider.value=String(k.value);slider.setAttribute('aria-label',`${KEY_LABELS[k.key]||k.key} proposé`);
        slider.setAttribute('data-panel-slider',k.key);
        const field=el('input');field.type='number';
        for(const [attr,value] of [['min',k.min],['max',k.max],['step',k.step]]){field.setAttribute(attr,String(value));field[attr]=String(value)}
        field.value=String(k.value);field.setAttribute('aria-label',`${KEY_LABELS[k.key]||k.key}, valeur proposée`);
        field.setAttribute('data-panel-field',k.key);
        const reset=el('button','','Remettre');reset.setAttribute('type','button');
        reset.setAttribute('data-panel-reset',k.key);reset.setAttribute('title','Revenir à la valeur proposée par l’assistant');
        if(!editable){slider.disabled=true;field.disabled=true;reset.disabled=true}
        /* Un curseur qui bouge ne redessine pas le panneau (le glisser se
           perdrait) : seule la ligne « Proposé » et le champ suivent. */
        const apply=(raw,from)=>{
          const answer=d.session.editProposal(p.ref,k.key,Number(String(raw).replace(',','.')));
          if(!answer||!answer.ok){pendingRefresh=true;return}
          const now=answer.result.proposal.keys.find(x=>x.key===k.key);
          if(from!=='slider')slider.value=String(now.value);
          if(from!=='field')field.value=String(now.value);
          const dl=typeof now.effective==='number'?now.value-now.effective:null;
          proposed.textContent=`${frNum(now.value,digits)}${unit}${dl!==null&&Math.abs(dl)>1e-9
            ?` (${dl>0?'+':'−'}${frNum(Math.abs(dl),digits)})`:''}${now.value!==now.proposed?' · corrigé':''}`;
          paintErrors(answer.result.proposal.errors);
          paintActions(answer.result.proposal);
        };
        slider.addEventListener('pointerdown',()=>{held=true});
        slider.addEventListener('input',event=>apply(event&&event.target?event.target.value:slider.value,'slider'));
        slider.addEventListener('change',()=>{held=false;if(pendingRefresh)refresh()});
        field.addEventListener('change',event=>apply(event&&event.target?event.target.value:field.value,'field'));
        reset.addEventListener('click',()=>{const answer=d.session.resetProposalKey(p.ref,k.key);if(answer&&answer.ok)refresh()});
        edit.appendChild(slider);edit.appendChild(field);edit.appendChild(reset);
        box.appendChild(edit);
        z.appendChild(box);
      }
      errorsNode=el('ul','jf-cal-errors');errorsNode.setAttribute('data-panel-errors','1');
      z.appendChild(errorsNode);
      paintErrors(p.errors);
      return z;
    }
    let errorsNode=null,actionsNode=null,receiptNode=null;
    function paintErrors(errors){
      if(!errorsNode)return;
      errorsNode.innerHTML='';
      for(const e of errors||[])errorsNode.appendChild(el('li','',e.message));
    }
    function paintActions(p){
      if(!actionsNode)return;
      actionsNode.innerHTML='';
      const pending=!!p&&p.state==='pending';
      const blocked=busy||!pending||(p.errors&&p.errors.length>0);
      const button=(id,label,primary,disabled,run)=>{
        const b=el('button',primary?'primary':'',label);b.setAttribute('type','button');
        b.setAttribute('data-panel-action',id);b.disabled=!!disabled;
        b.addEventListener('click',()=>{if(!b.disabled)run()});
        actionsNode.appendChild(b);
      };
      button('rerun','Appliquer et refaire',true,blocked||!p.rerunStage,()=>commit('rerun'));
      button('continue','Appliquer et continuer',false,blocked,()=>commit('continue'));
      button('discard','Écarter',false,busy||!pending,()=>{
        const answer=d.session.discardProposal(p.ref,'panel');lastAnswer=answer;refresh()});
    }
    function paintReceipt(state){
      if(!receiptNode)return;
      receiptNode.innerHTML='';
      const p=state.proposal;
      const receipt=p&&p.receipt;
      if(receipt)for(const step of receipt.steps){
        const li=row(STEP_WORDS[step]||step,null,'good','✓','');li.setAttribute('data-receipt-step',step);
        receiptNode.appendChild(li);
      }
      if(receipt&&receipt.ok&&receipt.attempt)receiptNode.appendChild(el('li','',`Essai ${receipt.attempt}`));
      if(lastAnswer&&!lastAnswer.ok){
        const code=lastAnswer.errors&&lastAnswer.errors[0]?lastAnswer.errors[0].code:'';
        const li=row(userText(code),null,'bad','✕','');li.setAttribute('data-receipt-error',code);
        receiptNode.appendChild(li);
      }
    }
    async function commit(action){
      const state=read();
      const p=state.proposal;
      if(busy||!p)return null;
      busy=true;refresh();
      try{
        lastAnswer=await d.session.commitProposal({proposalRef:p.ref,action},'panel');
        if(!lastAnswer||!lastAnswer.ok)log('warn','barehands.calibration_panel_commit_refused',
          {action,code:lastAnswer&&lastAnswer.errors&&lastAnswer.errors[0]?lastAnswer.errors[0].code:null});
        return lastAnswer;
      }catch(error){
        lastAnswer={ok:false,errors:[{code:'barehands_calibration_page_error',message:messageOf(error)}]};
        log('error','barehands.calibration_panel_commit_failed',{action,error:messageOf(error)});
        return lastAnswer;
      }finally{busy=false;refresh()}
    }
    function refresh(){
      if(!node)return;
      if(held){pendingRefresh=true;return}
      pendingRefresh=false;
      const state=read();
      title.textContent=collapsed?tabText(state):'Calibration';
      toggle.textContent=collapsed?'▸':'▾';
      toggle.setAttribute('aria-expanded',collapsed?'false':'true');
      toggle.setAttribute('aria-label',collapsed?'Déplier le panneau de calibration':'Replier le panneau de calibration');
      node.setAttribute('data-collapsed',collapsed?'1':'0');
      body.innerHTML='';errorsNode=null;
      body.appendChild(paintExercise(state));
      body.appendChild(paintResults(state));
      body.appendChild(paintProposal(state));
      const actions=zone('actions','Actions');
      actionsNode=el('div','jf-cal-actions');actions.appendChild(actionsNode);
      receiptNode=el('ul','jf-cal-receipt');receiptNode.setAttribute('data-panel-receipt','1');actions.appendChild(receiptNode);
      body.appendChild(actions);
      paintActions(state.proposal);
      paintReceipt(state);
    }
    function setCollapsed(on){collapsed=!!on;remember();refresh();return collapsed}
    function mount(region){
      if(node||!region)return node;
      if(!doc.getElementById(PANEL_STYLE_ID)){
        const style=el('style');style.id=PANEL_STYLE_ID;style.textContent=PANEL_CSS(d.rootSelector||'#jarvisFlow');
        (doc.head||doc.body).appendChild(style);
      }
      recall();
      node=el('aside','jf-cal');
      node.setAttribute('data-calibration-panel','1');
      node.setAttribute('aria-label','Panneau de calibration');
      head=el('div','jf-cal-head');head.setAttribute('data-panel-handle','1');
      title=el('div','jf-cal-title','Calibration');
      toggle=el('button','','▾');toggle.setAttribute('type','button');toggle.setAttribute('data-panel-toggle','1');
      toggle.addEventListener('click',()=>setCollapsed(!collapsed));
      head.appendChild(title);head.appendChild(toggle);
      body=el('div','jf-cal-body');
      node.appendChild(head);node.appendChild(body);
      /* Déplacer par l'en-tête : la position suit le pointeur, bornée à la
         fenêtre, et se retient pour la prochaine calibration. */
      let from=null;
      const move=event=>{
        if(!from)return;
        position={left:from.left+(event.clientX-from.x),top:from.top+(event.clientY-from.y)};
        place();
      };
      const up=()=>{
        if(!from)return;
        from=null;remember();
        doc.removeEventListener('pointermove',move);doc.removeEventListener('pointerup',up);
      };
      head.addEventListener('pointerdown',event=>{
        if(event&&event.target&&event.target.tagName==='BUTTON')return;
        const box=typeof node.getBoundingClientRect==='function'?node.getBoundingClientRect():null;
        const start=position||{left:box?box.left:PANEL_MARGIN,top:box?box.top:72};
        from={x:Number(event&&event.clientX)||0,y:Number(event&&event.clientY)||0,left:start.left,top:start.top};
        doc.addEventListener('pointermove',move);doc.addEventListener('pointerup',up);
      });
      region.appendChild(node);
      place();
      refresh();
      return node;
    }
    return Object.freeze({mount,refresh,collapse:setCollapsed,collapsed:()=>collapsed,
      moveTo(left,top){position={left:Number(left),top:Number(top)};place();remember();return position?{...position}:null},
      position:()=>position?{...position}:null,
      commit,tab:()=>tabText(read()),
      close(){if(node&&typeof node.remove==='function')node.remove();node=null;head=null;title=null;body=null;toggle=null;
        errorsNode=null;actionsNode=null;receiptNode=null},
      node:()=>node});
  }

  /* ------------------------------------------------------------------
     La séance déclarée au serveur (décision 50) : ouverture, battement toutes
     les `heartbeatMs`, fermeture. Le serveur en tire le mode du cerveau et la
     porte des outils ; sans battement, il l'échoit lui-même. Un envoi raté se
     dit (console, puis `error` après trois échecs de suite) et se réessaie au
     battement suivant. */
  function createSessionReporter(deps){
    const d=deps||{};
    for(const need of ['post','setInterval','clearInterval','running'])
      if(typeof d[need]!=='function')throw new RangeError(`createSessionReporter exige deps.${need}()`);
    const log=typeof d.log==='function'?d.log:()=>{};
    const heartbeatMs=Number(d.heartbeatMs)>0?Number(d.heartbeatMs):10000;
    /* `held` : le serveur a **accepté** cette séance (réponse `active:true`).
       Refusée — une autre page tient déjà la sienne
       (`barehands_calibration_session_busy`) —, la calibration de cette page
       continue sans agent : ses portes `calibration_*` refusent. */
    let id=null,timer=null,failures=0,held=false,refusal=null,busyNoticed=false,disabled=false;
    const notify=(name,...args)=>{
      if(typeof d[name]!=='function')return;
      try{d[name](...args)}catch(error){log('warn','barehands.calibration_session_callback_failed',{name,error:messageOf(error)})}
    };
    const exercise=()=>{
      try{return typeof d.exercise==='function'?d.exercise():null}
      catch(error){
        /* Le battement part quand même : l'exercice est un confort du journal
           serveur, la séance ne s'arrête pas pour lui. La cause est dite. */
        log('warn','barehands.calibration_exercise_unreadable',{error:messageOf(error)});
        return null;
      }
    };
    /* L'essai en cours voyage avec le battement : un serveur qui a perdu la
       séance (échéance, redémarrage) rouvre la fenêtre d'accord sur lui. */
    const trial=()=>{
      try{const ref=typeof d.trial==='function'?d.trial():null;return typeof ref==='string'?ref:null}
      catch(error){log('warn','barehands.calibration_trial_unreadable',{error:messageOf(error)});return null}
    };
    async function send(active){
      if(!id)return false;
      try{
        const answer=await d.post({session:id,active,exercise:exercise(),trial:active?trial():null});
        if(failures)log('info','barehands.calibration_session_reported',{after:failures});
        failures=0;
        if(active){
          const was=held;
          held=!!(answer&&answer.active===true);refusal=held?null:refusal;
          if(held)busyNoticed=false;
          if(held!==was){
            log('info',held?'barehands.calibration_session_held':'barehands.calibration_session_released',
              {session:id.slice(0,8)});
            notify('onHeld',held);
          }
        }
        return true;
      }catch(error){
        const code=String(error&&error.code||'');
        if(active){
          const was=held;
          held=false;
          refusal={code,message:messageOf(error)};
          if(was)notify('onHeld',false);
        }
        /* **Deux refus attendus, dits une fois** (reprise QA : un « [object
           Object] » toutes les 10 s dans Error Logs). Bare Hands éteint : la
           séance n'a plus d'objet, la page ferme la calibration. Séance tenue
           par un autre onglet : cet onglet calibre sans la voix, et le dit. */
        if(code==='barehands_disabled'){
          if(!disabled){disabled=true;log('info','barehands.calibration_session_disabled',{session:id.slice(0,8)});
            notify('onDisabled')}
          return false;
        }
        if(code==='barehands_calibration_session_busy'){
          if(!busyNoticed){busyNoticed=true;log('warn','barehands.calibration_session_busy',{session:id.slice(0,8)});
            notify('onRefused',code)}
          return false;
        }
        failures+=1;
        log(failures>=3?'error':'warn','barehands.calibration_session_report_failed',
          {active,failures,code,error:messageOf(error)});
        return false;
      }
    }
    function randomId(){
      const bytes=new Uint8Array(18);
      const c=root.crypto||(typeof crypto!=='undefined'?crypto:null);
      if(c&&typeof c.getRandomValues==='function')c.getRandomValues(bytes);
      else for(let i=0;i<bytes.length;i++)bytes[i]=Math.floor(Math.random()*256);
      return Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    }
    function stop(){
      if(!id)return false;
      if(timer!==null)d.clearInterval(timer);
      timer=null;
      send(false);
      log('info','barehands.calibration_session_stopped',{session:id.slice(0,8)});
      const was=held;
      id=null;held=false;
      if(was)notify('onHeld',false);
      return true;
    }
    return Object.freeze({
      stop,
      start(){
        if(id)return id;
        id=randomId();failures=0;held=false;refusal=null;busyNoticed=false;disabled=false;
        send(true);
        timer=d.setInterval(()=>{
          /* Le parcours s'est fermé par un chemin qui n'a pas appelé `stop` :
             la séance se ferme quand même, ici. Éteint : plus de battement. */
          if(!d.running()||disabled){stop();return}
          send(true);
        },heartbeatMs);
        log('info','barehands.calibration_session_started',{session:id.slice(0,8)});
        return id;
      },
      /* **La page se ferme** (`pagehide`) : un `fetch` n'y survit pas, une
         balise (`sendBeacon`) si. Le serveur ferme la séance tout de suite au
         lieu d'attendre son échéance. */
      beacon(){
        if(!id||typeof d.beacon!=='function')return false;
        let sent=false;
        try{sent=!!d.beacon({session:id,active:false,exercise:null,trial:null})}
        catch(error){log('warn','barehands.calibration_session_beacon_failed',{error:messageOf(error)})}
        log(sent?'info':'warn','barehands.calibration_session_beacon',{session:id.slice(0,8),sent});
        return sent;
      },
      /* Un battement tout de suite (un exercice commence) : le serveur sait
         quel exercice est à l'écran sans attendre le prochain battement. */
      pulse(){if(!id)return false;send(true);return true},
      session:()=>id,
      held:()=>held,
      refusal:()=>refusal?Object.freeze({...refusal}):null,
    });
  }

  const api=Object.freeze({INACTIVE,REFUSED,STATUS_LIMITS,SESSION_CAPS,CONFIDENCE_RULE,FEEDBACK_BUTTONS,
    CAUSE_EXERCISES,CAUSE_WORDS,CHANNEL_KEYS,MIN_AFTER_EPISODES,USER_TEXT,userText,KEY_LABELS,UNIT_WORDS,
    createCalibrationAgentSession,createCoachPanel,createCalibrationPanel,createSessionReporter,STAGE_SHORT});
  root.JarvisBarehandsCalibrationAgent=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
