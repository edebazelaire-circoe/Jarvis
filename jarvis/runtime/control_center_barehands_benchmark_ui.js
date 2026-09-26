/* Bare Hands — l'écran « Tester » : le test court, son rapport, l'avant/après
   (tâche `jarvis-bare-hands-adaptive-calibration-benchmark`, Slice 09,
   `docs/barehands-contracts.md` § 17, décisions 65 à 68).

   **Ce que cet écran montre : la qualité d'interaction de Bare Hands avec les
   réglages en vigueur — jamais une note des gestes de la personne.** Aucun
   texte ici ne parle d'habileté, de niveau ni de précision de l'utilisateur ;
   un test le vérifie sur le texte rendu.

   Ce module ne mesure rien et ne score rien : le plan, le déroulé, le score,
   la comparaison et le rangement sont ceux de la Slice 08
   (`control_center_barehands_benchmark.js`). Il **dessine** l'état du
   déroulé, **nourrit** le déroulé des images du moteur et **raconte** le
   résultat. Sa machine d'états est la sienne (`SCREEN`) : elle emprunte la
   coque plein cadre de la calibration (`createFlowOverlay`), jamais la
   machine d'étapes de la calibration.

   Lecture seule : le flux ne reçoit ni réglage, ni profil, ni essai, ni porte
   d'écriture. Il reçoit une fabrique de déroulé (qui, elle, ne reçoit que des
   vues gelées), le magasin de **résumés** et une porte `calibrate(étape)`
   qui ne fait qu'ouvrir la calibration — la calibration garde ses propres
   règles (rien ne s'enregistre sans l'utilisateur, décision 53).

   Insertion : après le banc (il le lit), avant le pointeur, qui le branche. */
(function(root){
  'use strict';
  const BH=root.JarvisBarehandsContracts;
  const BM=root.JarvisBarehandsBenchmark;
  if(!BH||!BM){
    console.error('[barehands] barehands.benchmark_ui_not_installed '
      +JSON.stringify({error:'les contrats et le banc Bare Hands doivent être insérés avant ce module'}));
    return;
  }

  /* ------------------------------------------------------------------ 1
     Les écrans, et les temps. */
  const SCREEN=Object.freeze({START:'start',BRIEF:'brief',RUN:'run',PAUSED:'paused',REPORT:'report',
    COMPARE:'compare',HISTORY:'history',FAILED:'failed'});
  /* Un run est « en cours » dans ces trois écrans : c'est là, et seulement
     là, que le moteur est tenu éveillé et que la couture de mesure est
     ouverte. */
  const RUNNING=Object.freeze([SCREEN.BRIEF,SCREEN.RUN,SCREEN.PAUSED]);
  const TIMING=Object.freeze({
    /* La consigne d'un exercice reste lisible trois secondes avant ses
       essais ; le temps du déroulé ne court pas pendant ce temps. */
    briefMs:3000,
    /* Le chien de garde : l'horloge d'écran, l'échéance du run, les images
       vides quand aucune main n'est vue (la couture du contrôleur ne tire que
       sur une main observée ; sans lui, un essai n'expirerait jamais). */
    watchdogMs:100,
    handGapMs:250,
    noHandNoteMs:1200,
    /* L'échéance du run entier. Les exercices ont chacun la leur ; la somme
       de leurs pires cas reste sous quatre minutes. Au-delà, quelque chose
       ne tourne plus : on arrête et on le dit. */
    runDeadlineMs:6*60*1000,
    /* Échap en deux temps hors run : la seconde pression sous ce délai. */
    confirmMs:2000,
  });
  /* Huit écrans, comme la calibration en a douze : l'accueil, les six
     exercices, les résultats. « Étape 1 sur 8 » est lu par la coque. */
  const SCREENS_TOTAL=BM.SUITE.length+2;

  /* ------------------------------------------------------------------ 2
     Les mots. Dimensions : un nom simple et une phrase qui dit ce qui est
     mesuré — du système, jamais de la personne. */
  const DIMENSION_TEXT=Object.freeze({
    acquisition:Object.freeze({name:'Atteinte de la cible',
      meaning:'Le temps et les reprises pour amener le pointeur sur une cible et la prendre.',
      weak:'Prendre une cible demande du temps ou plusieurs reprises.'}),
    selection_accuracy:Object.freeze({name:'Justesse de sélection',
      meaning:'Un pincement prend la cible visée, pas une voisine ni le vide.',
      weak:'Des pincements prennent une voisine ou tombent dans le vide.'}),
    false_positive_resistance:Object.freeze({name:'Résistance aux faux clics',
      meaning:'Une main qui bouge ou vise sans pincer ne déclenche rien.',
      weak:'Des mouvements ordinaires déclenchent des appuis, des cibles ou le pointeur.'}),
    release_reliability:Object.freeze({name:'Fiabilité du relâchement',
      meaning:'Le relâchement est reconnu vite, et jamais trop tôt pendant une saisie.',
      weak:'Le relâchement arrive tard, ou une saisie se lâche trop tôt.'}),
    drag_drop:Object.freeze({name:'Glisser-déposer',
      meaning:'Une fenêtre saisie se dépose là où on la vise.',
      weak:'Les dépôts échouent ou tombent loin de la destination.'}),
    pointer_stability:Object.freeze({name:'Stabilité du pointeur',
      meaning:'Le pointeur reste calme quand la main vise un point.',
      weak:'Le pointeur tremble quand la main vise un point.'}),
    reactivity:Object.freeze({name:'Réactivité',
      meaning:'Le pointeur suit la main et l’appui est reconnu sans retard.',
      weak:'Le pointeur traîne derrière la main, ou l’appui est reconnu tard.'}),
    transitions:Object.freeze({name:'Enchaînements',
      meaning:'Passer d’un geste au suivant — clic, déplacement, clic — sans temps mort.',
      weak:'Entre deux gestes, la reprise est lente.'}),
  });
  /* **Une dimension faible**, sous ce score : l'écran l'explique et propose
     l'exercice de calibration qui y répond. Les rampes du score valent 100 à
     l'ancre « bon » et 0 à l'ancre « inutilisable » (décision 62) ; sous 60,
     la moyenne des métriques de la dimension est plus près du mauvais bout
     que du bon. */
  const WEAK_BELOW=60;
  /* **Dimension → exercice de calibration** (décision 67). L'exercice qui
     mesure la même chose, dont la revue permet d'« Ajuster ». */
  const DIMENSION_CALIBRATION=Object.freeze({
    acquisition:BH.STAGE.AIM,
    selection_accuracy:BH.STAGE.AIM,
    false_positive_resistance:BH.STAGE.NATURAL_MOTION,
    release_reliability:BH.STAGE.HOLD_RELEASE,
    drag_drop:BH.STAGE.DROP,
    pointer_stability:BH.STAGE.AIM_NO_CLICK,
    reactivity:BH.STAGE.PINCH_PRIMARY,
    transitions:BH.STAGE.DRAG,
  });
  /* Les métriques brutes, dans le registre des lignes de revue de la
     calibration (`REVIEW_LINES`). */
  const METRIC_TEXT=Object.freeze({
    acquisition_ms:'Temps pour prendre la cible (médiane)',
    reacquisition_count:'Reprises de visée avant de prendre',
    timeout_count:'Essais sans sélection à temps',
    wrong_target_count:'Essais où une autre cible a été prise',
    missed_click_count:'Essais avec un pincement dans le vide',
    target_ambiguity:'Ambiguïté entre voisines (médiane)',
    false_click_count:'Cibles prises sans pincer exprès',
    false_press_rate:'Appuis détectés sans pincer',
    false_secondary_press_rate:'Clics droits détectés sans pincer',
    unintended_target_rate:'Cibles présélectionnées en bougeant',
    unintended_pointer_rate:'Pointeur affiché en bougeant',
    release_latency_ms:'Délai de relâchement (médiane)',
    premature_drop_count:'Essais lâchés trop tôt',
    drag_success_rate:'Dépôts réussis',
    placement_error_px:'Écart au centre de la destination (médiane)',
    pointer_jitter_px:'Tremblement du pointeur posé (médiane)',
    pointer_lag_ms:'Retard du pointeur en mouvement (médiane)',
    press_latency_ms:'Délai d’appui (médiane)',
    transition_ms:'Temps entre deux gestes (médiane)',
  });
  /* Chaque exercice : un titre et une consigne d'une ligne. */
  const EXERCISE_TEXT=Object.freeze({
    target_acquisition:Object.freeze({title:'Prendre une étoile',
      instruction:'Pincez l’étoile pleine. Les cercles vides sont des leurres.'}),
    nearby_targets:Object.freeze({title:'Étoiles voisines',
      instruction:'Pincez l’étoile pleine, pas ses voisines.'}),
    moving_target:Object.freeze({title:'Étoile mobile',
      instruction:'Suivez l’étoile qui se déplace et pincez-la.'}),
    drag_drop:Object.freeze({title:'Glisser-déposer',
      instruction:'Saisissez la fenêtre et déposez-la dans le cadre en pointillé.'}),
    chained:Object.freeze({title:'Enchaîner',
      instruction:'Pincez l’étoile, déposez la fenêtre, puis pincez la dernière étoile.'}),
    no_click_tracking:Object.freeze({title:'Bouger sans cliquer',
      instruction:'Ne pincez pas : rien ne doit se déclencher.'}),
  });
  const MODE_TEXT=Object.freeze({
    natural:'Bougez la main librement, comme en parlant. Ne pincez pas.',
    aim:'Visez le point entouré, main posée, sans pincer.',
  });
  const CHAINED_STEP_TEXT=Object.freeze(['1 · Pincez l’étoile.','2 · Déposez la fenêtre dans le cadre.',
    '3 · Pincez la dernière étoile.']);
  const VERDICT_TEXT=Object.freeze({
    improved:'Amélioré',regressed:'Dégradé',unchanged:'Inchangé',
    inconclusive:'Pas de conclusion',unmeasured:'Non mesuré',
  });
  const SOURCE_TEXT=Object.freeze({defaults:'réglages d’usine',saved:'réglages enregistrés',
    trial:'réglage d’essai'});
  const NOT_COMPARABLE_TEXT=Object.freeze({
    plan_class:'une autre version du test',
    viewport:'une autre taille de fenêtre',
    suite:'une autre suite d’exercices',
  });
  const VIEWPORT_TEXT=Object.freeze({vp100:'grande fenêtre',vp90:'fenêtre moyenne',vp80:'petite fenêtre'});
  /* Les deux mises en garde qui accompagnent toujours un avant/après. */
  const SAME_PERSON_TEXT='Comparez deux tests faits par la même personne : le temps de réaction et le geste de chacun entrent dans les mesures.';
  const SAME_PROFILE_TEXT='Les deux tests ont mesuré les mêmes réglages : un écart vient du hasard ou de l’habitude du test, pas d’un réglage.';
  const RERUN_TEXT='Relancez le test pour trancher.';

  /* ------------------------------------------------------------------ 3
     Mise en forme. */
  const frNumber=(value,digits)=>value.toFixed(digits).replace('.',',').replace(/,0+$/,'').replace(/(,\d*?)0+$/,'$1');
  function formatMetric(name,value,trials){
    if(value===null||value===undefined||!Number.isFinite(value))return 'non mesuré';
    const spec=BH.CALIBRATION_METRIC[name];
    const unit=spec?spec.unit:null;
    if(unit==='ms')return `${Math.round(value)} ms`;
    if(unit==='px')return `${frNumber(value,1)} px`;
    if(unit==='ratio')return name==='target_ambiguity'?frNumber(value,2):`${Math.round(value*100)} %`;
    if(unit==='per_min')return `${frNumber(value,1)} par minute`;
    if(unit==='count'){
      const n=Math.round(value);
      return spec.perTrial&&Number.isFinite(trials)?`${n} sur ${trials} essais`:String(n);
    }
    return frNumber(value,2);
  }
  const scoreText=score=>score===null||score===undefined?'non mesuré':`${Math.round(score)} / 100`;
  function dateText(ms){
    if(!Number.isFinite(ms))return 'date inconnue';
    try{
      return new Date(ms).toLocaleString('fr-FR',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'});
    }catch(_error){/* intentional: un environnement sans locale rend la forme ISO, lisible aussi */
      return new Date(ms).toISOString().slice(0,16).replace('T',' ');
    }
  }
  function viewportText(viewport){
    const name=BH.benchmarkViewportClass(viewport);
    const size=viewport?`${Math.round(viewport.width)} × ${Math.round(viewport.height)}`:'?';
    return name?`${VIEWPORT_TEXT[name]||name} (${size})`:`fenêtre ${size}`;
  }
  const sourceText=result=>SOURCE_TEXT[result.profileSource]||result.profileSource;

  /* Le titre de l'exercice de calibration d'une étape, lu dans les étapes de
     la calibration (titre d'écran, ou libellé du temps pour un écran qui en a
     plusieurs). */
  function calibrationTitle(steps,stage){
    for(const step of Array.isArray(steps)?steps:[]){
      if(step.subs){
        const sub=step.subs.find(s=>s.id===stage);
        if(sub)return String(sub.label||step.title||stage);
      }else if(step.id===stage)return String(step.title||stage);
    }
    return String(stage);
  }

  /* ------------------------------------------------------------------ 4
     Modèles purs (ce que les tests lisent sans écran). */

  /* **Les lignes du rapport**, depuis `scoreResult` : les huit dimensions
     dans l'ordre du contrat, chacune avec son score, sa faiblesse, son
     exercice de calibration et ses métriques brutes ; la plus pénalisante
     d'une dimension faible est nommée. */
  function dimensionRows(scores,steps){
    return BH.BENCHMARK_DIMENSIONS.map(dimension=>{
      const d=scores.dimensions[dimension];
      const text=DIMENSION_TEXT[dimension];
      const score=d.score;
      const weak=score!==null&&score<WEAK_BELOW;
      const metrics=d.metrics.map(m=>Object.freeze({metric:m.metric,exercise:m.exercise,kind:m.kind,
        label:METRIC_TEXT[m.metric]||m.metric,value:m.value,score:m.score,
        text:formatMetric(m.metric,m.value,m.trials)}));
      const scored=metrics.filter(m=>m.score!==null);
      const worst=weak&&scored.length?scored.reduce((w,m)=>m.score<w.score?m:w,scored[0]):null;
      const stage=DIMENSION_CALIBRATION[dimension];
      return Object.freeze({dimension,name:text.name,meaning:text.meaning,score,weak,
        explanation:weak?text.weak:null,
        worst:worst?Object.freeze({label:worst.label,text:worst.text,exercise:worst.exercise}):null,
        calibrate:Object.freeze({stage,title:calibrationTitle(steps,stage)}),
        metrics:Object.freeze(metrics)});
    });
  }
  /* Le global, **secondaire** et prudent : `null` dit quelles dimensions
     manquent, jamais un nombre inventé. */
  function globalLine(scores){
    const g=scores.global;
    if(g.score===null){
      const names=g.unmeasured.map(n=>DIMENSION_TEXT[n]?DIMENSION_TEXT[n].name:n);
      return Object.freeze({score:null,text:`Indice global non calculé — non mesuré : ${names.join(', ')}.`});
    }
    const weakest=DIMENSION_TEXT[g.weakest]?DIMENSION_TEXT[g.weakest].name:g.weakest;
    return Object.freeze({score:g.score,capped:g.capped,
      text:`Indice global : ${scoreText(g.score)}${g.capped?` — limité par la dimension la plus faible (${weakest})`:''}.`});
  }

  /* **Quels runs se comparent à celui-ci**, depuis la liste du magasin
     (`[{id,result}]`). Rend les comparables (du plus récent au plus ancien,
     sans lui-même) et les autres avec leur raison. */
  function comparableRuns(target,entries){
    const list=Array.isArray(entries)?entries:[];
    const comparable=[],others=[];
    for(const entry of list){
      if(!entry||!entry.result||entry.result===target.result||entry.id===target.id)continue;
      let reason=null;
      try{
        if(!BH.benchmarkComparable(target.result,entry.result)){
          reason=target.result.planClass!==entry.result.planClass?'plan_class'
            :BH.benchmarkViewportClass(target.result.viewport)!==BH.benchmarkViewportClass(entry.result.viewport)?'viewport':'suite';
        }
      }catch(_error){reason='suite'}   // intentional: un résumé qui ne se relit pas ne se compare pas, et la raison le dit
      (reason?others:comparable).push(Object.freeze({entry,reason}));
    }
    const newest=(a,b)=>b.entry.result.runAt-a.entry.result.runAt;
    comparable.sort(newest);others.sort(newest);
    return Object.freeze({comparable:Object.freeze(comparable),others:Object.freeze(others)});
  }
  /* **Le partenaire par défaut** : le plus récent run comparable **avant**
     celui-ci ; à défaut (on regarde un ancien), le plus récent comparable. */
  function defaultPartner(target,entries){
    const {comparable}=comparableRuns(target,entries);
    const before=comparable.find(c=>c.entry.result.runAt<target.result.runAt);
    return before?before.entry:(comparable[0]?comparable[0].entry:null);
  }

  /* **Les lignes de l'avant/après**, depuis `compareResults`. Une dimension
     sans conclusion dit pourquoi et demande de relancer ; jamais un verdict
     que la comparaison n'a pas rendu. */
  function comparisonRows(cmp){
    return BH.BENCHMARK_DIMENSIONS.map(dimension=>{
      const d=cmp.dimensions[dimension];
      const few=d.metrics.some(m=>m.reason==='too_few_samples');
      const reason=d.verdict==='inconclusive'?(few?'too_few_samples':'uncertain'):null;
      const why=reason==='too_few_samples'?'Trop peu d’essais mesurés de part et d’autre'
        :reason==='uncertain'?'L’écart est trop incertain pour conclure':null;
      return Object.freeze({dimension,name:DIMENSION_TEXT[dimension].name,before:d.before,after:d.after,delta:d.delta,
        verdict:d.verdict,word:VERDICT_TEXT[d.verdict]||d.verdict,reason,
        text:why?`${why}. ${RERUN_TEXT}`:null});
    });
  }
  function comparisonNotes(cmp){
    const notes=[cmp.note,SAME_PERSON_TEXT];
    if(cmp.sameProfile)notes.push(SAME_PROFILE_TEXT);
    else notes.push(`Réglages : ${SOURCE_TEXT[cmp.before.profileSource]||cmp.before.profileSource} avant, `
      +`${SOURCE_TEXT[cmp.after.profileSource]||cmp.after.profileSource} après${
        cmp.before.profileSource===cmp.after.profileSource?' (valeurs différentes)':''}.`);
    return Object.freeze(notes);
  }
  function comparisonSummary(rows){
    const count=word=>rows.filter(r=>r.verdict===word).length;
    const parts=[];
    const plural=(n,one,many)=>`${n} ${n>1?many:one}`;
    if(count('improved'))parts.push(plural(count('improved'),'dimension améliorée','dimensions améliorées'));
    if(count('regressed'))parts.push(plural(count('regressed'),'dégradée','dégradées'));
    if(count('unchanged'))parts.push(plural(count('unchanged'),'inchangée','inchangées'));
    if(count('inconclusive'))parts.push(plural(count('inconclusive'),'sans conclusion','sans conclusion'));
    if(count('unmeasured'))parts.push(plural(count('unmeasured'),'non mesurée','non mesurées'));
    return parts.join(', ');
  }

  /* Deux entrées du magasin sont la même si elles sont le même objet ou
     portent le même identifiant (la liste se relit après chaque
     enregistrement : les objets changent, les identifiants non). */
  const sameEntry=(a,b)=>!!a&&!!b&&(a===b||(a.id!==null&&a.id!==undefined&&a.id===b.id));

  /* ------------------------------------------------------------------ 5
     La feuille. Posée **après** celle de la coque : elle habille ce que le
     test monte dans la scène, et range la coque en mode « run » (bandeau
     compact en haut, consigne en bas, le champ entier aux exercices). */
  const STYLE_ID='jarvisBenchStyle';
  const R=`#${BH.DOM.flowRootId}`;
  const D=BH.DOM;
  const STYLE=`
/* ================================================================ Slice 09
   Le test. Même coque, même voile, même bleu que la calibration : c'est un
   autre usage du même outil, pas un autre produit. Ce qui le distingue est
   la mise en page du run — le champ entier appartient aux exercices — et un
   calme voulu : aucun score pendant le run, seulement la progression. */
${R}{--jb-warn:#ffd58a;--jb-line:rgba(255,255,255,.08);--jb-ink:#e9f1fb}
/* ---- le run : bandeau compact en haut à gauche, commandes en haut à droite,
   consigne en bas. Les étoiles ne s'approchent jamais à moins de 64 px des
   bords (marge du champ à l'échelle la plus petite) : ces bandes sont à eux. */
${R}[data-bench="run"] .${D.flowStepClass},${R}[data-bench="brief"] .${D.flowStepClass},
${R}[data-bench="paused"] .${D.flowStepClass}{display:block;padding:0}
${R}[data-bench="run"] .${D.flowHeaderClass}{position:absolute;top:12px;left:var(--jf-gutter);
  align-items:flex-start;text-align:left;gap:2px;max-width:min(46vw,560px)}
${R}[data-bench="run"] .${D.flowHeaderClass} h2{font-size:15px;letter-spacing:0;line-height:1.3}
${R}[data-bench="run"] .jf-kicker{font-size:10px;letter-spacing:.2em}
${R}[data-bench="run"] .jf-instruction{display:none}
${R}[data-bench="run"] .jf-foot{position:absolute;left:0;right:0;bottom:12px;flex-direction:row;
  justify-content:center;align-items:baseline;gap:18px;padding:0 var(--jf-gutter)}
${R}[data-bench="run"] .${D.flowFeedbackClass}{width:auto;min-height:0}
${R}[data-bench="run"] .jf-meta{flex:0 0 auto;white-space:nowrap}
${R}[data-bench="run"] .${D.flowControlsClass}{position:fixed;top:14px;right:76px}
${R}[data-bench="run"] .${D.flowControlsClass} button{padding:8px 16px}
${R}[data-bench="run"] .${D.flowStageClass}{position:static}
/* ---- la consigne d'exercice et la pause : centrées, lisibles, rien derrière. */
${R}[data-bench="brief"] .${D.flowStepClass},${R}[data-bench="paused"] .${D.flowStepClass}{display:grid;
  padding:clamp(30px,6vh,76px) var(--jf-gutter) clamp(18px,3.4vh,40px)}
/* ---- le champ : en pixels de la fenêtre, comme le déroulé. Purement
   gestuel, caché des lecteurs d'écran ; la consigne dit ce qu'il y a à faire. */
${R} .jb-field{position:fixed;inset:0;z-index:2;pointer-events:none}
${R} .jb-star{position:absolute;border-radius:50%;box-sizing:border-box;transform:translate(-50%,-50%)}
/* L'étoile à prendre : pleine, du bleu de la consigne, avec un repère en
   pointillé (discontinu = annoncé, comme la mire de la calibration). */
${R} .jb-star[data-expected="1"]{background:var(--jf-accent);box-shadow:0 0 0 3px rgba(4,9,16,.6),0 0 18px rgba(110,231,255,.45)}
${R} .jb-star[data-expected="1"]::after{content:"";position:absolute;inset:-9px;border-radius:50%;
  border:1.5px dashed rgba(110,231,255,.7)}
/* Un leurre : un cercle vide, plus discret que la cible. */
${R} .jb-star[data-expected="0"]{border:2px solid rgba(233,241,251,.5);background:rgba(4,9,16,.35)}
/* Les points de « bouger sans cliquer » : présents, jamais invitants. */
${R} .jb-star[data-quiet="1"]{border:1.5px solid rgba(233,241,251,.28);background:transparent}
/* **La présélection** : l'anneau plein dit laquelle serait prise si l'on
   pinçait maintenant — le même sens que l'aperçu de cible de la page. */
${R} .jb-star[data-preview="1"]{outline:2px solid var(--jb-ink);outline-offset:5px}
${R} .jb-aim{position:absolute;width:44px;height:44px;margin:-22px 0 0 -22px;border-radius:50%;
  border:2px dashed var(--jf-accent)}
${R} .jb-aim::after{content:"";position:absolute;left:50%;top:50%;width:6px;height:6px;margin:-3px 0 0 -3px;
  border-radius:50%;background:var(--jf-accent)}
/* La destination : le cadre où la fenêtre doit tenir **entière** (sa taille
   plus la tolérance de chaque côté), et l'empreinte de la fenêtre au centre. */
${R} .jb-drop{position:absolute;box-sizing:border-box;border:1.5px dashed rgba(110,231,255,.75);border-radius:14px;
  background:rgba(110,231,255,.05)}
${R} .jb-drop i{position:absolute;box-sizing:border-box;border:1px dotted rgba(110,231,255,.45);border-radius:10px}
${R} .jb-window{position:absolute;box-sizing:border-box;border-radius:10px;overflow:hidden;
  background:rgba(14,26,40,.94);border:1px solid rgba(110,231,255,.4);box-shadow:0 14px 34px rgba(0,0,0,.35)}
${R} .jb-window b{display:block;padding:6px 10px;font:600 11px/1.2 var(--jf-sans);letter-spacing:.08em;
  text-transform:uppercase;color:var(--jf-soft);border-bottom:1px solid var(--jb-line)}
${R} .jb-window[data-preview="1"]{border-color:var(--jb-ink);outline:2px solid var(--jb-ink);outline-offset:3px}
/* ---- les écrans de lecture : accueil, résultats, comparaison, historique.
   Du haut vers le bas, la scène défile, une colonne lisible. */
${R}[data-bench="start"] .${D.flowStageClass},${R}[data-bench="report"] .${D.flowStageClass},
${R}[data-bench="compare"] .${D.flowStageClass},${R}[data-bench="history"] .${D.flowStageClass},
${R}[data-bench="failed"] .${D.flowStageClass}{justify-content:flex-start;overflow-y:auto;overscroll-behavior:contain;
  padding-bottom:8px}
${R}[data-bench="start"] .${D.flowExerciseClass},${R}[data-bench="report"] .${D.flowExerciseClass},
${R}[data-bench="compare"] .${D.flowExerciseClass},${R}[data-bench="history"] .${D.flowExerciseClass},
${R}[data-bench="failed"] .${D.flowExerciseClass}{flex:0 0 auto;align-items:flex-start}
${R}[data-bench] .${D.flowStageClass}{scrollbar-width:thin;scrollbar-color:rgba(255,255,255,.18) transparent}
/* Le titre reçoit le focus à chaque écran (lecteur d'écran) ; ce n'est pas
   une commande, il n'a pas d'anneau à montrer. */
${R}[data-bench] h2:focus{outline:none}
${R}[data-bench] .${D.flowStepClass}{grid-template-columns:minmax(0,1fr)}
${R} .jb-page{width:100%;max-width:720px;min-width:0;font-family:var(--jf-sans);color:var(--jf-soft);font-size:14px;line-height:1.55;
  display:flex;flex-direction:column;gap:18px;text-align:left}
${R} .jb-page h3{margin:0;font-size:12px;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--jf-muted)}
${R} .jb-page p{margin:0}
${R} .jb-meta{color:var(--jf-muted);font-size:13px;font-variant-numeric:tabular-nums}
${R} .jb-status{font-size:13px;color:var(--jf-muted);min-height:1.5em}
${R} .jb-status[data-kind="bad"]{color:var(--jf-bad)}
${R} .jb-status[data-kind="ok"]{color:var(--jf-ok)}
${R} .jb-list{margin:0;padding:0;list-style:none;display:flex;flex-direction:column}
${R} .jb-list > li{padding:12px 2px;border-bottom:1px solid var(--jb-line);display:flex;flex-direction:column;gap:4px}
${R} .jb-row{display:flex;align-items:baseline;justify-content:space-between;gap:16px}
${R} .jb-row b{font-weight:600;color:var(--jb-ink);font-size:15px}
${R} .jb-score{font-variant-numeric:tabular-nums;color:var(--jb-ink);white-space:nowrap}
${R} .jb-muted{color:var(--jf-muted);font-size:13px}
/* La barre : l'échelle d'un coup d'œil, le nombre à côté la dit exactement. */
${R} .jb-bar{display:block;height:4px;border-radius:999px;background:rgba(255,255,255,.08);overflow:hidden}
${R} .jb-bar i{display:block;height:100%;border-radius:999px;background:var(--jf-accent)}
${R} li[data-weak="1"] .jb-bar i{background:var(--jb-warn)}
${R} li[data-weak="1"] .jb-score{color:var(--jb-warn)}
${R} .jb-weak{margin-top:4px;padding:10px 12px;border-left:2px solid var(--jb-warn);background:rgba(255,213,138,.06);
  display:flex;flex-direction:column;gap:8px;align-items:flex-start}
${R} .jb-page button{font-size:12px;padding:8px 14px}
${R} .jb-link{align-self:flex-start;border:0;padding:4px 0;background:none;color:var(--jf-accent);letter-spacing:.02em;text-decoration:underline;
  text-underline-offset:3px}
${R} .jb-page .jb-link{padding:4px 0}
${R} .jb-link:hover{background:none;color:#9af0ff}
${R} .jb-details{margin:6px 0 0;padding:0 0 0 12px;list-style:none;border-left:1px solid var(--jb-line)}
${R} .jb-details li{display:flex;justify-content:space-between;gap:14px;padding:3px 0;font-size:12.5px;color:var(--jf-muted)}
${R} .jb-details li span:last-child{font-variant-numeric:tabular-nums;color:var(--jf-soft);white-space:nowrap}
${R} .jb-global{padding-top:4px;color:var(--jf-muted);font-size:13px}
${R} .jb-notice{padding:10px 12px;border-left:2px solid var(--jf-bad);background:rgba(255,163,163,.06);color:var(--jb-ink)}
${R} .jb-notes{margin:0;padding:0 0 0 16px;color:var(--jf-muted);font-size:13px}
${R} .jb-verdict{font-size:12px;letter-spacing:.06em;text-transform:uppercase;white-space:nowrap}
${R} .jb-verdict[data-verdict="improved"]{color:var(--jf-ok)}
${R} .jb-verdict[data-verdict="regressed"]{color:var(--jf-bad)}
${R} .jb-verdict[data-verdict="inconclusive"]{color:var(--jb-warn)}
${R} .jb-verdict[data-verdict="unchanged"],${R} .jb-verdict[data-verdict="unmeasured"]{color:var(--jf-muted)}
${R} .jb-runs{display:flex;flex-direction:column;gap:6px;margin:0;padding:0;list-style:none}
${R} .jb-runs button{width:100%;text-align:left;border-radius:10px;display:flex;justify-content:space-between;gap:12px;
  font-variant-numeric:tabular-nums}
${R} .jb-runs button[aria-pressed="true"]{color:var(--jb-ink);border-color:var(--jf-accent);background:rgba(110,231,255,.08)}
${R} .jb-runs li[data-comparable="0"]{padding:8px 14px;color:var(--jf-muted);font-size:12.5px}
${R} .jb-brief{font:600 clamp(40px,7vw,72px)/1 var(--jf-sans);color:var(--jf-accent);font-variant-numeric:tabular-nums}
@media (max-width:720px){
  ${R}[data-bench="run"] .${D.flowHeaderClass}{max-width:60vw}
  ${R} .jb-row{flex-direction:column;gap:2px}
}
/* **Moins de mouvement.** Les cibles mobiles bougent toujours : c'est
   l'exercice, et le mouvement est l'information. Rien d'autre ne bouge ici —
   aucune transition, aucune animation décorative ; la feuille de la coque
   arrête déjà les siennes. */
@media (prefers-reduced-motion:reduce){
  ${R} .jb-star,${R} .jb-window,${R} .jb-bar i,${R} .jb-page button{transition:none;animation:none}
}`;

  /* ------------------------------------------------------------------ 6
     Le flux. */
  const FLOW_DEPS=Object.freeze(['document','overlay','createRunner','store','now','engineNow','setInterval',
    'clearInterval','viewport','seed']);
  function createBenchmarkFlow(deps){
    const d=deps&&typeof deps==='object'?deps:{};
    for(const need of FLOW_DEPS)
      if(d[need]===undefined||d[need]===null)
        throw new RangeError(`createBenchmarkFlow exige \`${need}\` : ${need==='setInterval'||need==='clearInterval'
          ?'sans chien de garde, un essai sans main visible n’expirerait jamais (RÈGLE ZÉRO)'
          :'un module de page qui lit un global qu’il n’a pas déclaré ne se teste pas'}.`);
    const doc=d.document,overlay=d.overlay,store=d.store;
    const log=(level,event,data)=>{
      try{if(typeof d.log==='function')d.log(level,event,data||{});}
      catch(_error){/* intentional: un journal qui lève ne doit pas couper le test ni masquer la panne qu'il raconte */}
    };
    const steps=Array.isArray(d.calibrationSteps)?d.calibrationSteps:[];
    const defer=typeof d.setTimeout==='function'?fn=>d.setTimeout(fn,0):fn=>fn();

    let screen=null,open=false,timer=null;
    /* Le run. `shift` retire du temps du déroulé ce que les consignes et la
       pause ont duré : le déroulé ne voit qu'un temps continu. */
    let runner=null,started=false,shift=0,holdSince=null,briefUntil=null,shownExercise=-1;
    let lastT=null,lastFeedAt=null,lastHandAt=null,runStartedAt=null,seed=null,lastState=null;
    let field=null,nodes=new Map();
    /* Les résultats. */
    let entries=null,listState='idle',listError=null,skipped=0,keptMax=20;
    let current=null,currentScores=null,saveState='idle',saveError=null;
    let partner=null,comparison=null,compareError=null,failure=null,confirmUntil=0,clearArmedUntil=0;

    const el=(tag,cls,text)=>{
      const node=doc.createElement(tag);
      if(cls)node.className=cls;
      if(text!==undefined)node.textContent=text;
      return node;
    };
    const button=(label,run,cls)=>{
      const node=el('button',cls||'',label);
      node.setAttribute('type','button');
      node.addEventListener('click',()=>run());
      return node;
    };
    function ensureStyle(){
      if(doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;style.textContent=STYLE;
      (doc.head||doc.body).appendChild(style);
    }
    const rootNode=()=>doc.getElementById(BH.DOM.flowRootId);
    function setScreen(name){
      screen=name;
      const node=rootNode();
      if(node)node.setAttribute('data-bench',name);
      log('info','barehands.benchmark_screen',{screen:name});
    }
    const running=()=>open&&RUNNING.includes(screen);

    /* ---------------------------------------------------------------- ouvrir */
    function openFlow(){
      if(open)return Object.freeze({ok:true,already:true,screen});
      overlay.open({title:'Test Bare Hands',exit:why=>exit(why==='escape'?'escape':'fermeture'),escape:()=>onEscape()});
      open=true;
      ensureStyle();
      timer=d.setInterval(tick,TIMING.watchdogMs);
      showStart();
      loadEntries();
      log('info','barehands.benchmark_opened',{});
      return Object.freeze({ok:true,screen});
    }

    /* ---------------------------------------------------------------- accueil */
    function showStart(){
      clearField();
      overlay.step({index:1,total:SCREENS_TOTAL,title:'Tester Bare Hands',
        instruction:'Six petits exercices, environ deux minutes. Le test mesure la qualité d’interaction de Bare Hands avec vos réglages actuels. Il ne change aucun réglage.',
        deadlineMs:null});
      setScreen(SCREEN.START);
      const page=el('div','jb-page');
      page.setAttribute('role','region');page.setAttribute('aria-label','Avant de commencer');
      page.appendChild(el('h3','','Au programme'));
      const list=el('ol','jb-list');
      for(const e of BM.SUITE){
        const item=el('li');
        const row=el('div','jb-row');
        row.appendChild(el('b','',EXERCISE_TEXT[e.kind].title));
        row.appendChild(el('span','jb-muted',`${e.trials} essais`));
        item.appendChild(row);
        item.appendChild(el('span','jb-muted',EXERCISE_TEXT[e.kind].instruction));
        list.appendChild(item);
      }
      page.appendChild(list);
      page.appendChild(el('p','jb-muted','Le résultat décrit Bare Hands avec ces réglages, pas vos gestes. Refaites le test après une calibration pour voir ce qu’elle a changé.'));
      const check=BM.viewportCheck(d.viewport());
      const where=el('p',check.ok?'jb-meta':'jb-notice',check.ok
        ?`Fenêtre : ${viewportText(d.viewport())}.`
        :check.reason);
      where.setAttribute('data-viewport',check.ok?check.viewportClass:'refused');
      if(!check.ok)where.setAttribute('role','alert');
      page.appendChild(where);
      const past=el('p','jb-status');
      past.setAttribute('aria-live','polite');
      past.setAttribute('data-history','1');
      page.appendChild(past);
      paintHistoryStatus(past);
      overlay.mount('exercise',page);
      const actions=[];
      if(check.ok)actions.push({id:'start',label:'Commencer le test',primary:true,run:()=>start()});
      else actions.push({id:'recheck',label:'Vérifier à nouveau',primary:true,run:()=>showStart()});
      if(entries&&entries.length)actions.push({id:'history',label:'Résultats précédents',run:()=>showHistory()});
      actions.push({id:'close',label:'Fermer',run:()=>exit('fermer')});
      overlay.buttons(actions,'Commencer ou fermer');
      if(!check.ok)log('warn','barehands.benchmark_viewport_refused',{code:check.code,
        width:Math.round(Number(d.viewport().width)),height:Math.round(Number(d.viewport().height))});
      overlay.focusTitle();
    }
    function paintHistoryStatus(node){
      if(!node)return;
      node.setAttribute('data-kind',listState==='failed'?'bad':'');
      node.textContent=listState==='loading'?'Lecture des résultats précédents…'
        :listState==='failed'?`Résultats précédents illisibles : ${listError}`
        :entries&&entries.length?`${entries.length} test${entries.length>1?'s':''} enregistré${entries.length>1?'s':''}${
          skipped?` (${skipped} illisible${skipped>1?'s':''} écarté${skipped>1?'s':''})`:''}.`
        :'Aucun test enregistré pour l’instant.';
    }
    /* La liste du magasin. Une panne se voit (écran), se journalise (Error
       Logs) et ne bloque pas le test. */
    async function loadEntries(){
      listState='loading';listError=null;
      repaintStatus();
      try{
        const loaded=await store.list();
        const list=loaded&&Array.isArray(loaded.results)?loaded.results:null;
        if(!list)throw Object.assign(new Error('réponse sans liste de résultats'),{code:'barehands_benchmark_store_failed'});
        entries=list.filter(e=>e&&e.result);
        skipped=Number(loaded.skipped)||0;
        if(Number.isInteger(loaded.max)&&loaded.max>0)keptMax=loaded.max;
        listState='ok';
        log('info','barehands.benchmark_list_loaded',{count:entries.length,skipped});
      }catch(error){
        listState='failed';listError=describe(error);
        log('error','barehands.benchmark_list_failed',{code:error&&error.code||'barehands_benchmark_store_failed',error:listError});
      }
      if(!open)return;
      if(screen===SCREEN.START)showStart();
      else repaintStatus();
    }
    function repaintStatus(){
      const node=rootNode();
      if(!node)return;
      const found=findAttr(node,'data-history');
      if(found)paintHistoryStatus(found);
    }
    function findAttr(node,name){
      if(!node)return null;
      if(typeof node.getAttribute==='function'&&node.getAttribute(name)!==null)return node;
      for(const child of node.children||[]){const hit=findAttr(child,name);if(hit)return hit}
      return null;
    }
    const describe=error=>{
      const text=error&&error.message?String(error.message):String(error||'erreur inconnue');
      return error&&error.code&&!text.includes(error.code)?`${text} (${error.code})`:text;
    };

    /* ---------------------------------------------------------------- lancer */
    function start(){
      if(!open)return Object.freeze({ok:false,code:'barehands_benchmark_closed'});
      if(running())return Object.freeze({ok:false,code:'barehands_benchmark_already_started'});
      const viewport=d.viewport();
      const check=BM.viewportCheck(viewport);
      if(!check.ok){showStart();return Object.freeze({ok:false,code:check.code,reason:check.reason})}
      try{
        seed=Number(d.seed())>>>0;
        const plan=BM.generatePlan(seed);
        runner=d.createRunner(plan);
        if(!runner||typeof runner.frame!=='function'||typeof runner.start!=='function')
          throw Object.assign(new Error('la fabrique n’a pas rendu de déroulé'),{code:'barehands_benchmark_invalid'});
      }catch(error){
        runner=null;
        fail(error,'barehands.benchmark_start_failed');
        return Object.freeze({ok:false,code:error&&error.code||'barehands_benchmark_invalid',reason:describe(error)});
      }
      started=false;shift=0;holdSince=null;lastT=null;lastFeedAt=d.engineNow();lastHandAt=lastFeedAt;
      runStartedAt=d.now();shownExercise=-1;lastState=null;current=null;currentScores=null;comparison=null;partner=null;
      saveState='idle';saveError=null;failure=null;
      try{if(typeof d.onRunStart==='function')d.onRunStart()}
      catch(error){runner=null;fail(error,'barehands.benchmark_start_failed');return Object.freeze({ok:false,code:'barehands_benchmark_invalid'})}
      log('info','barehands.benchmark_run_started',{seed,viewportClass:check.viewportClass});
      enterBrief(0);
      return Object.freeze({ok:true,seed,viewportClass:check.viewportClass});
    }
    /* La fin d'un run, quelle qu'en soit la cause : la couture et l'éveil du
       moteur se rendent **toujours** ici. */
    function endRun(why){
      const was=runner!==null;
      runner=null;started=false;holdSince=null;briefUntil=null;
      clearField();
      if(was&&typeof d.onRunEnd==='function'){
        try{d.onRunEnd(why)}
        catch(error){log('error','barehands.benchmark_release_failed',{error:describe(error)})}
      }
      if(was)log('info','barehands.benchmark_run_ended',{why});
    }

    /* ---- le temps du déroulé : l'horloge du moteur, moins les arrêts. */
    const hold=()=>{if(holdSince===null)holdSince=d.engineNow()};
    const release=()=>{if(holdSince!==null){shift+=d.engineNow()-holdSince;holdSince=null}};
    const virtual=t=>t-shift;

    function enterBrief(index){
      hold();
      shownExercise=index;
      const e=BM.SUITE[index];
      const text=EXERCISE_TEXT[e.kind];
      clearField();
      overlay.step({index:index+2,total:SCREENS_TOTAL,title:text.title,
        instruction:e.kind==='no_click_tracking'?`${text.instruction} ${MODE_TEXT.natural} Puis : ${MODE_TEXT.aim.toLowerCase()}`
          :text.instruction,deadlineMs:TIMING.briefMs});
      setScreen(SCREEN.BRIEF);
      briefUntil=d.engineNow()+TIMING.briefMs;
      const count=el('div','jb-brief',String(Math.ceil(TIMING.briefMs/1000)));
      count.setAttribute('aria-hidden','true');
      count.setAttribute('data-countdown','1');
      overlay.mount('exercise',count);
      overlay.note(`Exercice ${index+1} sur ${BM.SUITE.length} · ${e.trials} essais. Il commence tout seul.`,'');
      overlay.buttons([
        {id:'ready',label:'Commencer maintenant',primary:true,run:()=>endBrief()},
        {id:'pause',label:'Pause',run:()=>pause()},
      ],'Consigne de l’exercice');
      overlay.progress(progressOf(lastState));
      overlay.focusTitle();
    }
    function endBrief(){
      if(!open||screen!==SCREEN.BRIEF)return false;
      briefUntil=null;
      release();
      const kind=BM.SUITE[shownExercise].kind;
      overlay.step({index:shownExercise+2,total:SCREENS_TOTAL,title:EXERCISE_TEXT[kind].title,
        instruction:EXERCISE_TEXT[kind].instruction,deadlineMs:null});
      setScreen(SCREEN.RUN);
      field=el('div','jb-field');field.setAttribute('aria-hidden','true');
      nodes=new Map();
      overlay.mount('exercise',field);
      overlay.buttons([{id:'pause',label:'Pause',run:()=>pause()}],'Test en cours');
      if(!started){
        const t=virtual(d.engineNow());
        try{lastState=runner.start(t);lastT=t;started=true}
        catch(error){fail(error,'barehands.benchmark_frame_failed');return false}
      }
      lastFeedAt=d.engineNow();
      paint(lastState);
      overlay.focusTitle();
      return true;
    }

    /* ---------------------------------------------------------------- images */
    /* **Une image du moteur** (couture `onMeasure` + sémantique de la même
       image). Ignorée hors run et pendant consigne/pause. Toute panne du
       déroulé arrête le run **proprement** et **se voit**. */
    function feed(measure,semantics){
      if(!open||screen!==SCREEN.RUN||!runner||!started)return false;
      let frame;
      try{frame=BM.engineFrame(measure,semantics)}
      catch(error){fail(error,'barehands.benchmark_frame_failed');return false}
      if(frame.hands.length)lastHandAt=d.engineNow();
      return push(frame);
    }
    function push(frame){
      const t=frame.t===null?null:virtual(frame.t);
      if(t===null||(lastT!==null&&t<=lastT))return false;
      const shifted={t,
        hands:frame.hands.map(h=>({...h,t:h.t===null||h.t===undefined?h.t:virtual(h.t)})),
        contacts:frame.contacts,
        events:frame.events.map(e=>({...e,t:e.t===null?null:virtual(e.t)}))};
      let state;
      try{state=runner.frame(shifted)}
      catch(error){fail(error,'barehands.benchmark_frame_failed');return false}
      lastT=t;lastFeedAt=d.engineNow();lastState=state;
      afterFrame(state);
      return true;
    }
    function afterFrame(state){
      if(!runner)return;
      if(runner.done()){finish();return}
      if(state.exerciseIndex!==shownExercise&&state.exerciseIndex>=0&&state.exerciseIndex<BM.SUITE.length){
        enterBrief(state.exerciseIndex);return;
      }
      paint(state);
    }

    /* ---------------------------------------------------------------- dessin */
    function clearField(){
      if(field&&typeof field.remove==='function')field.remove();
      field=null;nodes=new Map();
    }
    function node(key,make){
      let n=nodes.get(key);
      if(!n){n=make();nodes.set(key,n);field.appendChild(n)}
      n.__seen=true;
      return n;
    }
    const place=(n,x,y,w,h)=>{
      n.style.left=`${Math.round(x)}px`;n.style.top=`${Math.round(y)}px`;
      if(w!==undefined){n.style.width=`${Math.round(w)}px`;n.style.height=`${Math.round(h)}px`}
    };
    function paint(state){
      if(!state||!field||screen!==SCREEN.RUN)return;
      for(const n of nodes.values())n.__seen=false;
      const preview=new Set(state.preview||[]);
      const quiet=state.kind==='no_click_tracking';
      if(state.destination&&runner){
        const tol=runner.dropTolerancePx();
        const dst=state.destination;
        const box=node('drop',()=>{
          const n=el('div','jb-drop');n.setAttribute('data-bench-drop','1');
          n.appendChild(el('i'));return n;
        });
        box.setAttribute('data-tolerance',String(tol));
        place(box,dst.x-dst.w/2-tol,dst.y-dst.h/2-tol,dst.w+2*tol,dst.h+2*tol);
        const ghost=box.children[0];
        if(ghost)place(ghost,tol,tol,dst.w,dst.h);
      }
      if(state.frame){
        const f=state.frame;
        const win=node('window',()=>{
          const n=el('div','jb-window');n.setAttribute('data-bench-frame','1');
          n.appendChild(el('b','','Fenêtre'));return n;
        });
        win.setAttribute('data-preview',preview.has('practice-frame')?'1':'0');
        place(win,f.x,f.y,f.w,f.h);
      }
      for(const s of state.stars){
        const n=node(`star:${s.id}`,()=>{const x=el('div','jb-star');x.setAttribute('data-bench-star',s.id);return x});
        n.setAttribute('data-expected',s.expected?'1':'0');
        n.setAttribute('data-quiet',quiet?'1':'0');
        n.setAttribute('data-preview',preview.has(s.id)?'1':'0');
        place(n,s.x,s.y,s.size,s.size);
      }
      if(state.aimSpot){
        const n=node('aim',()=>{const x=el('div','jb-aim');x.setAttribute('data-bench-aim','1');return x});
        place(n,state.aimSpot.x,state.aimSpot.y);
      }
      for(const [key,n] of [...nodes.entries()])if(!n.__seen){n.remove();nodes.delete(key)}
      overlay.progress(progressOf(state));
      /* Sans main depuis un moment, la montre dit « aucune main vue » à la
         place de la consigne (voir `tick`). */
      if(d.engineNow()-lastHandAt<TIMING.noHandNoteMs)overlay.note(liveText(state),'');
    }
    function liveText(state){
      if(!state||!state.kind)return '';
      let text=EXERCISE_TEXT[state.kind].instruction;
      if(state.kind==='no_click_tracking'&&state.mode)text=MODE_TEXT[state.mode];
      if(state.kind==='chained'&&state.step!==null)text=CHAINED_STEP_TEXT[state.step]||text;
      const trial=state.phase==='live'?`Essai ${state.trial} sur ${state.trials}`:'Essai suivant…';
      return `${trial} · ${text}`;
    }
    /* La progression du run entier : essais soldés sur essais prévus. */
    function progressOf(state){
      const total=BM.SUITE.reduce((n,e)=>n+e.trials,0);
      if(!state||state.exerciseIndex<0)return 0;
      if(state.phase==='done')return 1;
      const before=BM.SUITE.slice(0,state.exerciseIndex).reduce((n,e)=>n+e.trials,0);
      return Math.min(1,(before+Math.max(0,state.trial-1))/total);
    }

    /* ---------------------------------------------------------------- montre */
    function tick(){
      if(!open)return;
      const now=d.engineNow();
      if(RUNNING.includes(screen)&&runStartedAt!==null&&d.now()-runStartedAt>TIMING.runDeadlineMs){
        fail(Object.assign(new Error(`le test n’a pas fini en ${Math.round(TIMING.runDeadlineMs/60000)} minutes`),
          {code:'barehands_benchmark_run_timeout'}),'barehands.benchmark_run_timeout');
        return;
      }
      if(screen===SCREEN.BRIEF&&briefUntil!==null){
        const left=Math.max(0,Math.ceil((briefUntil-now)/1000));
        const count=findAttr(rootNode(),'data-countdown');
        if(count)count.textContent=String(left);
        if(now>=briefUntil)endBrief();
        return;
      }
      if(screen!==SCREEN.RUN||!runner||!started)return;
      /* Aucune image depuis un moment : la main est hors champ. Une image
         vide fait avancer les échéances du déroulé, et l'écran le dit. */
      if(now-lastFeedAt>=TIMING.handGapMs)push({t:now,hands:[],contacts:[],events:[]});
      if(open&&screen===SCREEN.RUN&&now-lastHandAt>=TIMING.noHandNoteMs)
        overlay.note('Aucune main vue : montrez votre main à la caméra. Le test continue.','bad');
    }

    /* ---------------------------------------------------------------- pause */
    function pause(){
      if(!open||(screen!==SCREEN.RUN&&screen!==SCREEN.BRIEF))return false;
      hold();
      briefUntil=null;
      clearField();
      overlay.step({index:shownExercise+2,total:SCREENS_TOTAL,title:'Test en pause',
        instruction:'Le temps des exercices est arrêté. Reprenez quand vous êtes prêt : l’essai en cours continue où il en était.',
        deadlineMs:null});
      setScreen(SCREEN.PAUSED);
      overlay.note('Échap à nouveau : quitter le test sans rien enregistrer.','',TIMING.confirmMs*3);
      overlay.buttons([
        {id:'resume',label:'Reprendre',primary:true,run:()=>resume()},
        {id:'quit',label:'Quitter le test',run:()=>exit('quitter')},
      ],'Test en pause');
      overlay.focusTitle();
      log('info','barehands.benchmark_paused',{exercise:shownExercise+1});
      return true;
    }
    /* **Reprendre passe par la consigne de l'exercice** : on relit avant de
       reprendre, comme au début de chaque exercice, et le temps du déroulé
       ne repart qu'à la fin de la consigne. */
    function resume(){
      if(!open||screen!==SCREEN.PAUSED)return false;
      overlay.releaseNote();
      enterBrief(shownExercise);
      log('info','barehands.benchmark_resumed',{exercise:shownExercise+1});
      return true;
    }
    /* Échap : pendant un run, la première pression met en pause ; en pause,
       elle quitte. Ailleurs, deux pressions sous deux secondes ferment. */
    function onEscape(){
      if(screen===SCREEN.RUN||screen===SCREEN.BRIEF){pause();return true}
      if(screen===SCREEN.PAUSED)return false;
      const now=d.now();
      if(now<confirmUntil)return false;
      confirmUntil=now+TIMING.confirmMs;
      overlay.note('Appuyez de nouveau sur Échap pour fermer le test.','',TIMING.confirmMs);
      return true;
    }

    /* ---------------------------------------------------------------- panne */
    function fail(error,event){
      const code=error&&error.code||'barehands_benchmark_failed';
      const message=describe(error);
      log('error',event||'barehands.benchmark_failed',{code,error:message,screen,
        exercise:lastState?lastState.exerciseRef:null});
      endRun('panne');
      failure=Object.freeze({code,message});
      if(!open)return;
      overlay.step({index:SCREENS_TOTAL,total:SCREENS_TOTAL,title:'Le test s’est interrompu',
        instruction:'Rien n’a été enregistré et aucun réglage n’a changé.',deadlineMs:null});
      setScreen(SCREEN.FAILED);
      const page=el('div','jb-page');
      const notice=el('p','jb-notice',`Cause : ${message}`);
      notice.setAttribute('role','alert');notice.setAttribute('data-failure',code);
      page.appendChild(notice);
      overlay.mount('exercise',page);
      overlay.buttons([
        {id:'restart',label:'Relancer le test',primary:true,run:()=>{showStart();start()}},
        {id:'close',label:'Fermer',run:()=>exit('fermer')},
      ],'Après l’interruption');
      overlay.focusTitle();
    }

    /* ---------------------------------------------------------------- fin */
    function finish(){
      const r=runner;
      let result,scores;
      try{
        result=r.result({ref:`${BH.SESSION_REF.BENCHMARK}-1`,runAt:Math.round(d.now())});
        scores=BM.scoreResult(result);
      }catch(error){fail(error,'barehands.benchmark_result_failed');return}
      endRun('fini');
      log('info','barehands.benchmark_run_done',{seed,global:scores.global.score,
        weak:BH.BENCHMARK_DIMENSIONS.filter(n=>scores.dimensions[n].score!==null&&scores.dimensions[n].score<WEAK_BELOW)});
      current=Object.freeze({id:null,result});currentScores=scores;
      saveState='saving';saveError=null;
      showReport();
      save();
    }
    async function save(){
      if(!current)return false;
      saveState='saving';saveError=null;repaintSave();
      const target=current;
      try{
        const stored=await store.save(target.result);
        saveState='saved';
        if(stored&&stored.id&&current===target)current=Object.freeze({id:stored.id,result:target.result});
        log('info','barehands.benchmark_saved',{id:stored&&stored.id||null,duplicate:!!(stored&&stored.duplicate),
          dropped:stored&&stored.dropped||0});
      }catch(error){
        saveState='failed';saveError=describe(error);
        log('error','barehands.benchmark_save_failed',{code:error&&error.code||'barehands_benchmark_store_failed',error:saveError});
      }
      if(!open)return saveState==='saved';
      await loadEntries();
      if(open&&screen===SCREEN.REPORT&&current&&current.result===target.result)showReport();
      return saveState==='saved';
    }
    function repaintSave(){
      const found=findAttr(rootNode(),'data-save');
      if(!found)return;
      found.setAttribute('data-kind',saveState==='failed'?'bad':saveState==='saved'?'ok':'');
      found.setAttribute('data-save',saveState);
      found.textContent=saveState==='saving'?'Enregistrement du résultat…'
        :saveState==='saved'?'Résultat enregistré : il servira aux prochaines comparaisons.'
        :saveState==='failed'?`Résultat non enregistré : ${saveError}`:'';
    }

    /* ---------------------------------------------------------------- rapport */
    function showReport(entry){
      /* Un autre run à l'écran : son partenaire se recalcule. */
      if(entry){current=entry;currentScores=BM.scoreResult(entry.result);saveState='stored';partner=null}
      if(!current)return false;
      const scores=currentScores;
      clearField();
      overlay.step({index:SCREENS_TOTAL,total:SCREENS_TOTAL,title:'Résultats du test',
        instruction:'Qualité d’interaction de Bare Hands avec ces réglages. Le test ne juge pas vos gestes.',deadlineMs:null});
      setScreen(SCREEN.REPORT);
      const result=current.result;
      const page=el('section','jb-page');
      page.setAttribute('aria-label','Résultats du test');
      page.appendChild(el('p','jb-meta',`${dateText(result.runAt)} · ${viewportText(result.viewport)} · ${sourceText(result)}`));
      if(saveState!=='stored'){
        const status=el('p','jb-status');status.setAttribute('aria-live','polite');status.setAttribute('data-save',saveState);
        page.appendChild(status);
      }
      page.appendChild(el('h3','','Par dimension'));
      const list=el('ul','jb-list');
      for(const row of dimensionRows(scores,steps))list.appendChild(dimensionItem(row));
      page.appendChild(list);
      const g=globalLine(scores);
      const global=el('p','jb-global',g.text);
      global.setAttribute('data-global',g.score===null?'null':String(g.score));
      page.appendChild(global);
      page.appendChild(el('h3','','Avant / après'));
      page.appendChild(compareTeaser());
      overlay.mount('exercise',page);
      if(saveState!=='stored')repaintSave();
      const actions=[];
      /* Un enregistrement raté se réessaie d'ici : le résultat est encore en
         mémoire, et le perdre pour une panne de disque serait perdre deux
         minutes de test. */
      if(saveState==='failed')actions.push({id:'save',label:'Réessayer l’enregistrement',primary:true,run:()=>save()});
      if(partner)actions.push({id:'compare',label:'Voir l’avant / après',run:()=>showCompare()});
      actions.push({id:'rerun',label:'Relancer le test',run:()=>{showStart();start()}});
      actions.push({id:'history',label:'Tous les résultats',run:()=>showHistory()});
      actions.push({id:'close',label:'Fermer',primary:saveState!=='failed',run:()=>exit('fermer')});
      overlay.buttons(actions,'Après le test');
      overlay.focusTitle();
      return true;
    }
    function dimensionItem(row){
      const item=el('li');
      item.setAttribute('data-dimension',row.dimension);
      item.setAttribute('data-score',row.score===null?'null':String(row.score));
      item.setAttribute('data-weak',row.weak?'1':'0');
      const head=el('div','jb-row');
      head.appendChild(el('b','',row.name));
      head.appendChild(el('span','jb-score',scoreText(row.score)));
      item.appendChild(head);
      const bar=el('span','jb-bar');bar.setAttribute('aria-hidden','true');
      const fill=el('i');fill.style.width=`${row.score===null?0:Math.max(0,Math.min(100,row.score))}%`;
      bar.appendChild(fill);item.appendChild(bar);
      item.appendChild(el('span','jb-muted',row.meaning));
      if(row.weak){
        const box=el('div','jb-weak');
        box.appendChild(el('p','',`${row.explanation}${row.worst?` Ce qui pèse le plus : ${row.worst.label.toLowerCase()} — ${row.worst.text}.`:''}`));
        const go=button(`Calibrer « ${row.calibrate.title} »…`,()=>calibrate(row.calibrate.stage),'jb-link');
        go.setAttribute('data-calibrate',row.calibrate.stage);
        box.appendChild(go);
        item.appendChild(box);
      }
      const detailsId=`jbDetails-${row.dimension}`;
      const toggle=button('Mesures',()=>{
        const on=toggle.getAttribute('aria-expanded')!=='true';
        toggle.setAttribute('aria-expanded',on?'true':'false');
        details.hidden=!on;
      },'jb-link');
      toggle.setAttribute('aria-expanded','false');toggle.setAttribute('aria-controls',detailsId);
      toggle.setAttribute('data-details',row.dimension);
      const details=el('ul','jb-details');details.id=detailsId;details.hidden=true;
      for(const m of row.metrics){
        const line=el('li');line.setAttribute('data-metric',m.metric);
        line.appendChild(el('span','',`${m.label} · ${EXERCISE_TEXT[m.kind]?EXERCISE_TEXT[m.kind].title:m.kind}`));
        line.appendChild(el('span','',m.text));
        details.appendChild(line);
      }
      item.appendChild(toggle);item.appendChild(details);
      return item;
    }
    /* Le résumé de l'avant/après sous le rapport, et le partenaire par
       défaut : le plus récent run comparable avant celui-ci. */
    function compareTeaser(){
      const box=el('p','jb-muted');
      box.setAttribute('data-compare-teaser','1');
      if(listState==='failed'){box.textContent=`Comparaison indisponible : ${listError}`;box.className='jb-status';box.setAttribute('data-kind','bad');partner=null;return box}
      if(!entries){box.textContent='Lecture des résultats précédents…';partner=null;return box}
      if(!partner||!comparableRuns(current,entries).comparable.some(c=>sameEntry(c.entry,partner)))partner=defaultPartner(current,entries);
      if(!partner){
        const {others}=comparableRuns(current,entries);
        box.textContent=others.length
          ?`Aucun test précédent comparable : ${others.length} autre${others.length>1?'s':''} ont été faits dans ${
            [...new Set(others.map(o=>NOT_COMPARABLE_TEXT[o.reason]))].join(' ou ')}.`
          :'Premier test : refaites-le après une calibration pour voir ce qu’elle a changé.';
        box.setAttribute('data-partner','none');
        return box;
      }
      box.setAttribute('data-partner',String(partner.id));
      box.textContent=`Comparable au test du ${dateText(partner.result.runAt)} (${sourceText(partner.result)}).`;
      return box;
    }

    /* ---------------------------------------------------------------- avant/après */
    function showCompare(withEntry){
      if(!current)return false;
      if(withEntry)partner=withEntry;
      if(!partner)partner=entries?defaultPartner(current,entries):null;
      clearField();
      overlay.step({index:SCREENS_TOTAL,total:SCREENS_TOTAL,title:'Avant / après',
        instruction:'Chaque dimension dit si elle a bougé plus que le hasard d’un test à l’autre.',deadlineMs:null});
      setScreen(SCREEN.COMPARE);
      const page=el('section','jb-page');
      page.setAttribute('aria-label','Comparaison de deux tests');
      comparison=null;compareError=null;
      if(partner){
        try{
          comparison=BM.compareResults(partner.result,current.result);
          log('info','barehands.benchmark_compared',{comparable:comparison.comparable,
            verdicts:comparison.comparable?BH.BENCHMARK_DIMENSIONS.map(n=>comparison.dimensions[n].verdict):null});
        }catch(error){
          compareError=describe(error);
          log('error','barehands.benchmark_compare_failed',{code:error&&error.code||'barehands_benchmark_invalid',error:compareError});
        }
      }
      if(compareError){
        const n=el('p','jb-notice',`Comparaison impossible : ${compareError}`);n.setAttribute('role','alert');page.appendChild(n);
      }else if(comparison&&comparison.comparable===false){
        const n=el('p','jb-notice',`Ces deux tests ne se comparent pas : ${NOT_COMPARABLE_TEXT[comparison.reason]||comparison.reason}.`);
        n.setAttribute('data-not-comparable',comparison.reason);page.appendChild(n);
      }else if(comparison){
        const [before,after]=comparison.before.runAt<=comparison.after.runAt?[comparison.before,comparison.after]:[comparison.after,comparison.before];
        page.appendChild(el('p','jb-meta',`Avant : ${dateText(before.runAt)} · Après : ${dateText(after.runAt)}`));
        const notes=el('ul','jb-notes');
        for(const text of comparisonNotes(comparison))notes.appendChild(el('li','',text));
        page.appendChild(notes);
        const list=el('ul','jb-list');
        for(const row of comparisonRows(comparison)){
          const item=el('li');
          item.setAttribute('data-dimension',row.dimension);
          item.setAttribute('data-verdict',row.verdict);
          if(row.reason)item.setAttribute('data-reason',row.reason);
          const head=el('div','jb-row');
          head.appendChild(el('b','',row.name));
          const word=el('span','jb-verdict',row.word);word.setAttribute('data-verdict',row.verdict);
          head.appendChild(word);
          item.appendChild(head);
          item.appendChild(el('span','jb-muted',`${scoreText(row.before)} → ${scoreText(row.after)}`));
          if(row.text)item.appendChild(el('span','jb-muted',row.text));
          list.appendChild(item);
        }
        page.appendChild(list);
        const g=comparison.global;
        const gline=el('p','jb-global',g.before===null||g.after===null
          ?'Indice global : non comparé (une dimension manque d’un côté).'
          :`Indice global : ${scoreText(g.before)} → ${scoreText(g.after)} · ${VERDICT_TEXT[g.verdict]||g.verdict}${
            g.verdict==='inconclusive'?` — ${RERUN_TEXT}`:''}`);
        gline.setAttribute('data-global-verdict',g.verdict);
        page.appendChild(gline);
      }else{
        page.appendChild(el('p','jb-muted','Aucun test comparable à mettre en face.'));
      }
      /* Choisir un autre run : les comparables d'abord, puis les autres avec
         la raison qui les écarte. */
      page.appendChild(el('h3','','Comparer avec'));
      page.appendChild(runPicker());
      overlay.mount('exercise',page);
      overlay.buttons([
        {id:'back',label:'Retour aux résultats',primary:true,run:()=>showReport()},
        {id:'rerun',label:'Relancer le test',run:()=>{showStart();start()}},
        {id:'close',label:'Fermer',run:()=>exit('fermer')},
      ],'Comparaison');
      overlay.focusTitle();
      return true;
    }
    function runPicker(){
      const list=el('ul','jb-runs');
      list.setAttribute('aria-label','Tests enregistrés');
      const {comparable,others}=comparableRuns(current,entries||[]);
      for(const c of comparable){
        const item=el('li');item.setAttribute('data-comparable','1');
        const g=safeGlobal(c.entry.result);
        const pick=button('',()=>showCompare(c.entry));
        pick.appendChild(el('span','',`${dateText(c.entry.result.runAt)} · ${sourceText(c.entry.result)}`));
        pick.appendChild(el('span','',g===null?'global non calculé':`global ${Math.round(g)}`));
        pick.setAttribute('aria-pressed',sameEntry(partner,c.entry)?'true':'false');
        pick.setAttribute('data-run',String(c.entry.id));
        item.appendChild(pick);list.appendChild(item);
      }
      for(const o of others){
        const item=el('li',''
          ,`${dateText(o.entry.result.runAt)} — ne se compare pas : ${NOT_COMPARABLE_TEXT[o.reason]||o.reason}.`);
        item.setAttribute('data-comparable','0');item.setAttribute('data-reason',o.reason);
        list.appendChild(item);
      }
      if(!comparable.length&&!others.length)list.appendChild(el('li','jb-muted','Aucun autre test enregistré.'));
      return list;
    }
    function safeGlobal(result){
      try{return BM.scoreResult(result).global.score}
      catch(error){log('warn','barehands.benchmark_unscorable',{error:describe(error)});return null}
    }

    /* ---------------------------------------------------------------- historique */
    function showHistory(){
      clearField();
      overlay.step({index:SCREENS_TOTAL,total:SCREENS_TOTAL,title:'Tests enregistrés',
        instruction:`Les ${keptMax} derniers tests sont gardés sur cet ordinateur : des nombres, jamais d’image.`,deadlineMs:null});
      setScreen(SCREEN.HISTORY);
      const page=el('section','jb-page');page.setAttribute('aria-label','Tests enregistrés');
      const status=el('p','jb-status');status.setAttribute('data-history','1');status.setAttribute('aria-live','polite');
      page.appendChild(status);paintHistoryStatus(status);
      const list=el('ul','jb-runs');
      for(const entry of (entries||[]).slice().sort((a,b)=>b.result.runAt-a.result.runAt)){
        const item=el('li');
        const g=safeGlobal(entry.result);
        const reopen=button('',()=>showReport(entry));
        reopen.appendChild(el('span','',`${dateText(entry.result.runAt)} · ${viewportText(entry.result.viewport)} · ${sourceText(entry.result)}`));
        reopen.appendChild(el('span','',g===null?'global non calculé':`global ${Math.round(g)}`));
        reopen.setAttribute('data-run',String(entry.id));
        item.appendChild(reopen);list.appendChild(item);
      }
      page.appendChild(list);
      overlay.mount('exercise',page);
      const actions=[];
      if(current)actions.push({id:'back',label:'Retour aux résultats',primary:true,run:()=>showReport()});
      else actions.push({id:'back',label:'Retour',primary:true,run:()=>showStart()});
      if(entries&&entries.length)actions.push({id:'clear',label:'Effacer tous les résultats…',run:()=>clearAll()});
      actions.push({id:'close',label:'Fermer',run:()=>exit('fermer')});
      overlay.buttons(actions,'Tests enregistrés');
      overlay.focusTitle();
      return true;
    }
    /* Effacer : deux temps, comme Échap. La seconde pression sous deux
       secondes efface ; une panne se voit et se journalise. */
    async function clearAll(){
      const now=d.now();
      if(now>=clearArmedUntil){
        clearArmedUntil=now+TIMING.confirmMs*2;
        overlay.note('Appuyez de nouveau pour effacer tous les résultats enregistrés.','bad',TIMING.confirmMs*2);
        return false;
      }
      clearArmedUntil=0;
      try{
        await store.clear();
        log('info','barehands.benchmark_cleared',{});
        entries=[];current=null;currentScores=null;partner=null;
        overlay.note('Résultats effacés.','ok',TIMING.confirmMs);
      }catch(error){
        const message=describe(error);
        log('error','barehands.benchmark_clear_failed',{code:error&&error.code||'barehands_benchmark_store_failed',error:message});
        overlay.note(`Effacement impossible : ${message}`,'bad',TIMING.confirmMs*3);
        return false;
      }
      await loadEntries();
      if(open)showHistory();
      return true;
    }

    /* ---------------------------------------------------------------- sortir */
    function calibrate(stage){
      log('info','barehands.benchmark_calibrate',{stage});
      exit('calibration');
      if(typeof d.calibrate!=='function')return Promise.resolve({ok:false,code:'barehands_benchmark_calibrate_missing'});
      return Promise.resolve().then(()=>d.calibrate(stage)).catch(error=>{
        log('error','barehands.benchmark_calibrate_failed',{stage,error:describe(error)});
        return {ok:false,code:error&&error.code||'barehands_benchmark_calibrate_failed'};
      });
    }
    function exit(why){
      if(!open)return false;
      const wasRunning=runner!==null;
      endRun(String(why||'fermeture'));
      open=false;
      if(timer!==null){d.clearInterval(timer);timer=null}
      confirmUntil=0;clearArmedUntil=0;
      screen=null;
      overlay.close();
      log('info','barehands.benchmark_closed',{why:String(why||'fermeture'),discarded:wasRunning});
      if(typeof d.onClose==='function'){
        try{d.onClose(String(why||'fermeture'))}
        catch(error){log('error','barehands.benchmark_release_failed',{error:describe(error)})}
      }
      return true;
    }

    return Object.freeze({
      open:openFlow,start,feed,pause,resume,exit,endBrief,
      isOpen:()=>open,
      /* Un run est-il en cours (consigne, exercice ou pause) ? C'est ce que
         la page lit pour tenir le moteur éveillé. */
      running,
      screen:()=>screen,
      state:()=>lastState,
      result:()=>current?current.result:null,
      scores:()=>currentScores,
      comparison:()=>comparison,
      failure:()=>failure,
      saveState:()=>saveState,
      showReport,showCompare,showHistory,save,tick,
    });
  }

  const api=Object.freeze({
    SCREEN,RUNNING,TIMING,SCREENS_TOTAL,WEAK_BELOW,DIMENSION_TEXT,DIMENSION_CALIBRATION,METRIC_TEXT,EXERCISE_TEXT,
    MODE_TEXT,VERDICT_TEXT,SOURCE_TEXT,NOT_COMPARABLE_TEXT,SAME_PERSON_TEXT,SAME_PROFILE_TEXT,RERUN_TEXT,STYLE,STYLE_ID,
    formatMetric,calibrationTitle,dimensionRows,globalLine,comparableRuns,defaultPartner,comparisonRows,
    comparisonNotes,comparisonSummary,createBenchmarkFlow,
  });
  root.JarvisBarehandsBenchmarkUi=api;
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
