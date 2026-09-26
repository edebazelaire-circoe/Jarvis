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
  const STATUS_LIMITS=Object.freeze({measurements:24,feedback:12,evidence:12,hypotheses:16,trials:10});
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
    release_threshold_too_far:['pinch_primary','pinch_secondary'],
    release_confirmation_too_slow:['pinch_primary','pinch_secondary'],
    release_confirmation_too_fast:['pinch_primary','pinch_secondary','drag'],
    click_drag_separation_too_tight:['drag','aim'],
    click_drag_separation_too_loose:['drag'],
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
  });
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
    const origin=now();
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

    const ok=(result,extra)=>Object.freeze({ok:true,code:null,result,...(extra||{})});
    function refuse(code,errors,op){
      const list=(errors||[]).slice(0,8).map(e=>Object.freeze({code:String(e.code||REFUSED),
        message:String(e.message||'').slice(0,200)}));
      log('warn','barehands.calibration_agent_refused',{op,code,faults:list.map(e=>e.code)});
      return Object.freeze({ok:false,code,errors:Object.freeze(list)});
    }
    const fault=(code,message,op)=>refuse(REFUSED,[{code,message}],op);
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
            metrics:roundedNumbers(set[ref])};
        }),
        measurementCount:refs.length,
        feedback:feedback.slice(-STATUS_LIMITS.feedback).map(feedbackRow),
        evidence:evidence.slice(-STATUS_LIMITS.evidence).map(e=>({...evidenceRow(e),value:rounded(e.value)})),
        hypotheses:hypotheses.slice(-STATUS_LIMITS.hypotheses).map(hypothesisRow),
        trials:trials.slice(-STATUS_LIMITS.trials).map(trialRow),
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
    function applyTrial(payload){
      if(!running())return inactive('apply');
      const p=payload||{};
      const h=findHypothesis(String(p.hypothesisRef||''));
      if(!h)return fault('barehands_trial_hypothesis_missing',`Hypothèse introuvable : ${p.hypothesisRef}.`,'apply');
      if(h.record.status==='weakened'||h.record.status==='rejected')
        return fault('barehands_calibration_hypothesis_disproven',
          `${h.record.ref} (${h.record.cause}) a été démentie par un essai : ne la réessaie pas, propose une autre cause ou une preuve nouvelle.`,'apply');
      const allowed=C.HYPOTHESIS_CAUSE_KEYS[h.record.cause]||[];
      const patch=p.patch&&typeof p.patch==='object'?p.patch:{};
      const off=Object.keys(patch).filter(key=>!allowed.includes(key));
      if(off.length)return fault('barehands_calibration_trial_off_hypothesis',
        allowed.length?`${off.join(', ')} ne teste pas ${h.record.cause} (clés permises : ${allowed.join(', ')}).`
          :`Aucun réglage ne teste ${h.record.cause} : c’est une réponse, pas un essai à faire.`,'apply');
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
        return fault('barehands_calibration_trial_channel_mismatch',
          `La preuve de ${h.record.ref} vient de ${evidenceChannels[0]} : ${Object.keys(patch).filter(k=>CHANNEL_KEYS[k]&&CHANNEL_KEYS[k]!==evidenceChannels[0]).join(', ')} règle l’autre canal.`,'apply');
      const open=unresolved();
      if(open)return fault('barehands_calibration_trial_unresolved',
        `L’essai ${open.ref} n’est pas encore jugé${open.state==='rolled_back'?' (il a été annulé, il reste à juger)':''} : juge-le avant d’en appliquer un autre.`,'apply');
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
        exercises:exercisesFor(h.record.cause,patchChannels,evidenceStages)};
      trials.push(row);
      log('info','barehands.calibration_trial',{ref:row.ref,hypothesis:row.hypothesisRef,applied:row.applied,
        exercises:row.exercises});
      return ok({trialRef:row.ref,hypothesisRef:row.hypothesisRef,baseRef:row.baseRef,applied:row.applied,
        appliedAt:row.appliedAt,exercises:row.exercises.slice()});
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
      for(const ref of receipt.undone||[]){const row=findTrial(ref);if(row)row.state='rolled_back'}
      const undoneRows=(receipt.undone||[]).map(findTrial).filter(Boolean);
      if(undoneRows.length)generation=Math.min(...undoneRows.map(row=>row.baseStateId));
      const left=activeTrials().slice(-1)[0]||null;
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
      for(const row of kept)row.state='accepted';
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
      return move('rerun',stage);
    }
    function move(op,stageId){
      if(!running())return inactive(op);
      const f=flow();
      if(typeof f.concluded==='function'&&f.concluded())
        return fault('barehands_calibration_exercise_unavailable',
          'La calibration est au récapitulatif : il n’y a plus d’exercice à refaire ni à passer.',op);
      const step=typeof f[op]==='function'?(stageId?f[op](stageId):f[op]()):null;
      if(step===null||step===undefined)
        return fault('barehands_calibration_exercise_unavailable','Aucun exercice à cet endroit du parcours.',op);
      log('info',`barehands.calibration_${op}`,{step:exercise().step});
      return ok({exercise:exercise()});
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
      return op==='status'?status():op==='feedback'?recordFeedback(payload,'voice')
        :op==='hypothesis'?proposeHypothesis(payload):op==='apply'?applyTrial(payload)
        :op==='resolve'?resolveTrial(payload):op==='rollback'?rollbackTrial()
        :op==='accept'?acceptTrial(payload,'voice'):op==='rerun'?rerun(payload):op==='next'?move('next')
        :fault('barehands_command_unknown',`Opération inconnue : ${op}.`,op);
    }

    return Object.freeze({
      command,
      status,recordFeedback,proposeHypothesis,applyTrial,resolveTrial,rollbackTrial,acceptTrial,
      rerun:payload=>rerun(payload),next:()=>move('next'),
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
${sel} .jf-coach-trial[hidden]{display:none}
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
    let node=null,trialRow=null,trialText=null,line=null,busy=false;
    const buttons=[];
    const el=(tag,cls,text)=>{const n=doc.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n};
    function say(text,kind){if(!line)return;line.textContent=text;line.setAttribute('data-kind',kind||'')}
    function paint(){
      const active=d.session.activeTrial();
      if(trialRow)trialRow.hidden=!active;
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
      const feel=el('div','jf-coach-row');
      feel.appendChild(el('span','jf-coach-label','Votre ressenti'));
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
    return Object.freeze({mount,refresh:paint,announce:(text,kind)=>say(String(text||''),kind),
      close(){if(node&&typeof node.remove==='function')node.remove();node=null;trialRow=null;trialText=null;line=null;buttons.length=0},
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
      session:()=>id,
      held:()=>held,
      refusal:()=>refusal?Object.freeze({...refusal}):null,
    });
  }

  const api=Object.freeze({INACTIVE,REFUSED,STATUS_LIMITS,SESSION_CAPS,CONFIDENCE_RULE,FEEDBACK_BUTTONS,
    CAUSE_EXERCISES,CHANNEL_KEYS,MIN_AFTER_EPISODES,USER_TEXT,userText,
    createCalibrationAgentSession,createCoachPanel,createSessionReporter});
  root.JarvisBarehandsCalibrationAgent=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
