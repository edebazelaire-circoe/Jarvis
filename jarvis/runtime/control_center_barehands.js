/* Barehands en mode test : pointeur à mains nues pour le Control Center.

   Réimplémentation native et réduite de l'idée Barehands (aucun code upstream
   AGPL repris) : la webcam suit les mains avec MediaPipe Hand Landmarker, servi
   localement par le Control Center (/barehands/assets/…), sans service cloud.
   Chaque main détectée affiche un jeton qui suit l'index ; un pincement
   pouce-index clique sous le jeton.

   Deux parties, comme `control_center_work.js` :
   - `JarvisBarehandsCore`, logique pure (géométrie, pincement, cycle de vie
     avec dépendances injectées), exécutée telle quelle par les tests (node) ;
   - un bloc navigateur qui branche la caméra, la surimpression, les clics et
     l'onglet « Expérimental » des réglages. Les tests node ne l'exécutent pas. */

const JarvisBarehandsCore=(function(){
  /* Indices MediaPipe utiles : poignet, bout du pouce, bout de l'index, base du
     majeur — puis, depuis la Slice 04, les trois bouts de doigt qui manquaient
     pour lire une posture (majeur pour le pincement secondaire de la
     décision 21, annulaire et auriculaire pour la main ouverte et le poing). */
  const LM=Object.freeze({WRIST:0,THUMB_TIP:4,INDEX_TIP:8,MIDDLE_MCP:9,
    MIDDLE_TIP:12,RING_TIP:16,PINKY_TIP:20});
  const DEFAULTS=Object.freeze({
    pressRatio:.28,     // pincé : pouce-index sous 28 % de la taille de la paume
    releaseRatio:.42,   // relâché au-dessus de 42 % (hystérésis : pas de clignotement)
    pressFrames:2,      // images consécutives pincées avant de valider
    cooldownMs:450,     // anti-rebond : délai minimal entre deux clics d'une même main
    margin:.12,         // bord de l'image ignoré : l'écran entier reste atteignable
    mirror:true,        // caméra frontale : l'image est vue en miroir
    lostGraceMs:250,    // une main perdue garde son identité et son état ce temps-là
    /* Filtre adaptatif du jeton (Slice 03, architecture §3). Remplace le
       `smoothing:.45` fixe, qui ne pouvait pas tenir le repos et la vitesse à
       la fois. Voir `createPointerFilter`. */
    minCutoffHz:1.2,    // coupure au repos : plus bas = plus calme
    betaCutoff:.012,    // gain de réactivité : plus haut = moins de retard
    dCutoffHz:1,        // coupure de l'estimation de vitesse
    filterResetMs:400,  // trou au-delà duquel le filtre repart au lieu de croire la vitesse
    /* Immobilité (px/s de la fenêtre) : rampe, pas seuil binaire. */
    stillSpeedPx:28,    // en dessous, la main est posée
    moveSpeedPx:420,    // au-dessus, elle file franchement
    /* Association d'identité (architecture §2). Les distances sont en paumes :
       invariantes à la distance à la caméra, comme le pincement et le C. */
    matchRadiusPalms:1.6,      // porte : au-delà, ce n'est pas la même main
    predictMs:120,             // extrapolation bornée de la vitesse d'une piste
    trackVelocityBlend:.5,     // lissage de cette vitesse : traverser un croisement, pas suivre le bruit
    /* Qualité de suivi (contrat : `HandFrame.quality`). Voir `handQuality`. */
    qualityFloor:.25,          // recopie de `JarvisBarehandsContracts.HAND_QUALITY_FLOOR`
    qualityEdge:.04,           // bande d'image où le cadrage se dégrade
    qualityPalmMin:.06,        // paume en dessous de laquelle les rapports n'ont plus de sens
    qualityComplete:.6,        // fraction de points finis en dessous de laquelle la main est devinée
    qualityWarmupFrames:3,     // images consécutives avant qu'une piste soit « installée »
    /* Réveil et veille (décisions 4, 5, 7). Ces deux durées appartiennent au
       contrat (`JarvisBarehandsContracts.SLEEP_TIMEOUT_MS`, `WAKE_HOLD_MS`) ;
       elles sont recopiées ici parce que le bloc pur est chargé seul par les
       tests node et ne peut pas lire le contrat. Un test de parité refuse
       qu'elles divergent. */
    sleepTimeoutMs:30000,  // ACTIVE → SLEEP après ce temps sans main exploitable
    wakeHoldMs:1000,       // posture en C tenue avant de réveiller
    wakeIntervalMs:200,    // cadence du guetteur de veille (5 images/s)
    wakeGraceMs:400,       // trou toléré dans la posture (2 images du guetteur)
    /* Posture en C : pouce et index écartés sans se toucher (pré-pincement),
       index déplié. L'écart est rapporté à la paume, la portée de l'index au
       poignet : mêmes seuils quelle que soit la distance à la caméra.
       `wakeGapMin` reste au-dessus de `releaseRatio` pour qu'un pincement en
       cours ne se lise jamais comme un réveil.

       Ces quatre nombres sont les **zéros du score**, pas les seuils de
       réveil : avec l'adoucissement de `wakeSoft` et le `wakeScore` qu'il faut
       tenir, la bande qui soutient réellement un maintien est plus étroite —
       écart dans [0,499 ; 0,811] et portée ≥ 1,485, soit
       `wakeGapMin + s·wakeScore` … `wakeGapMax − s·wakeScore` et
       `wakeIndexMin·(1 + wakeSoft·wakeScore)`, avec
       `s = (wakeGapMax − wakeGapMin)·wakeSoft`. C'est la bande effective que
       la Slice 08 calibre, et celle que publie `docs/barehands-contracts.md`. */
    wakeGapMin:.46,        // écart où le score tombe à 0 côté pincement
    wakeGapMax:.85,        // écart où il tombe à 0 côté main ouverte
    wakeIndexMin:1.35,     // portée où il tombe à 0 : en dessous, un poing
    wakeSoft:.2,           // fraction de la plage où le score retombe à 0
    wakeScore:.5,          // score minimal tenu pour que la posture compte
    /* ---- Slice 04 : intention de pincement (architecture §5, décisions 20-22).
       Les deux canaux partagent `pressRatio`/`releaseRatio` : tous deux se
       mesurent en paumes, du pouce à un bout de doigt, donc un seuil propre au
       majeur serait un nombre de plus sans question de plus. Ce qui les sépare
       n'est pas un seuil, c'est une **marge**. */
    /* Écart entre les deux canaux qui donne la pleine confiance. Il valait
       0,18 tant qu'il devait, **seul**, écarter la fermeture de main entière :
       à ce prix il écartait le poing de 0,02 paume et bloquait un pincement
       primaire dès que le majeur suivait l'index à moins de 8°. Une seule
       marge ne pouvait pas tenir les deux — la fermeture est maintenant lue
       sur l'extension des doigts (`handClosure`), et cette marge-ci ne répond
       plus qu'à sa vraie question : **de quel doigt s'agit-il**. Libérée, elle
       descend à 0,12, soit 0,06 paume d'écart exigé (~5 mm sur une paume de
       90 mm) — au-dessus du tremblement d'un bout de doigt, en dessous de
       l'écart qu'un pincement délibéré produit. */
    pinchMarginRatio:.12,    // écart minimal entre les deux canaux pour être sûr duquel il s'agit
    pinchConfidenceMin:.5,   // confiance de canal exigée pour descendre en contact
    /* ---- Slice 04 : clic contre glissement (décision 22). Lus sur la vitesse
       et l'immobilité **publiées par la Slice 03**, jamais sur une dérivée
       recalculée ici : la dérivée interne du filtre lit 40 px/s sur une main
       immobile, et aucun clic ne se distinguerait d'un glissement. */
    clickMaxMs:400,          // au-delà, un contact n'est plus un clic
    clickSlopPx:12,          // déplacement toléré dans un clic
    dragSlopPx:26,           // au-delà, le contact **est** un glissement, décidé en cours de route
    clickStillnessMin:.5,    // immobilité exigée au relâchement pour conclure à un clic
    /* ---- Slice 04 : postures (architecture §4). La portée d'un doigt depuis
       le poignet, rapportée à la paume : même mesure que le C, mêmes unités,
       même invariance à la distance à la caméra. Entre les deux bornes, le
       score est une rampe — un doigt à moitié plié ne bascule pas. */
    fingerCurledPalms:1.15,  // portée en dessous de laquelle un doigt est replié
    fingerExtendedPalms:1.6, // portée au-dessus de laquelle il est tendu
    postureScore:.7,         // score minimal pour qu'une posture compte
    postureHoldMs:250,       // durée tenue avant qu'une posture s'annonce
    /* ---- Slice 04 : gestes discrets. */
    doubleCloseMs:600,       // écart maximal entre deux fermetures d'un double
    clapPalms:1.4,           // distance des deux centres de paume, en paumes
    clapSpeedPalms:2.5,      // vitesse de rapprochement exigée (paumes/s) : deux mains posées côte à côte ne claquent pas
    gestureCooldownMs:500,   // anti-rebond des gestes discrets (clap, double fermeture)
    /* ---- Slice 05 : cible sémantique et aperçu (architecture §6, décisions
       3, 8, 9, 16, 23, 24). Tout est en **pixels de la fenêtre**, comme
       `boundsPx`/`distancePx` du contrat : ce sont des tailles à l'écran, pas
       des rapports à la paume. Une zone de manipulation se vise avec l'œil,
       pas avec la main. */
    targetZonePx:14,        // bande d'un bord : il faut y **entrer** pour prendre la zone
    targetZoneHoldPx:20,    // bande qui la **garde** : hystérésis, même idiome que pressRatio/releaseRatio
    targetZoneMaxRatio:.3,  // la bande ne prend jamais plus que cette fraction du petit côté
    targetAssistPx:24,      // portée d'assistance hors du cadre (une petite erreur de visée vise quand même)
  });
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));

  const positive=(value,fallback)=>{const n=Number(value);return Number.isFinite(n)&&n>0?n:fallback};
  const atLeast=(value,min,fallback)=>{const n=Number(value);return Number.isFinite(n)&&n>=min?n:fallback};

  function options(overrides){
    /* `smoothing` a disparu à la Slice 03. L'accepter en silence rendrait un
       réglage sans effet indiscernable d'un réglage appliqué — précisément le
       défaut que la reprise de la Slice 01 a chassé partout ailleurs. Un
       appelant qui le passe encore l'apprend à la construction, pas trois
       Slices plus loin devant un jeton qui tremble. */
    if(overrides&&overrides.smoothing!==undefined)
      throw new RangeError('`smoothing` n’existe plus : le filtre est adaptatif (minCutoffHz, betaCutoff)');
    /* Même refus, même raison, et une de plus : ce réglage-là était un
       **défaut**, pas seulement un poids mal choisi. Une prime soustraite au
       coût d'appariement peut renverser la géométrie, et le faisait sous 0,35
       paume de séparation. La latéralité est maintenant une clé secondaire de
       `assign`, lue à distance égale : il n'y a plus de nombre à régler, et
       l'accepter en silence laisserait croire qu'on en règle encore un. */
    if(overrides&&overrides.handednessBonusPalms!==undefined)
      throw new RangeError('`handednessBonusPalms` n’existe plus : la latéralité départage à distance égale, elle ne se soustrait plus au coût');
    const o={...DEFAULTS,...(overrides||{})};
    if(!(o.pressRatio>0&&o.pressRatio<o.releaseRatio))throw new RangeError('pressRatio doit être positif et inférieur à releaseRatio');
    if(!(o.wakeGapMin>0&&o.wakeGapMin<o.wakeGapMax))throw new RangeError('wakeGapMin doit être positif et inférieur à wakeGapMax');
    if(!(o.stillSpeedPx>=0&&o.stillSpeedPx<o.moveSpeedPx))throw new RangeError('stillSpeedPx doit rester sous moveSpeedPx');
    /* Troisième invariant de paire, et le seul dont la violation ne se voit
       nulle part : le guetteur de veille n'appelle `createWakeDetector` qu'une
       fois par `wakeIntervalMs`, donc le `dt` que voit le détecteur **est**
       cette cadence. Si elle dépasse `wakeGraceMs`, chaque mesure arrive après
       un trou plus long que la grâce, le maintien repart de zéro à chaque
       échantillon et la posture en C ne peut plus aboutir — mesuré : 0 ms de
       maintien crédité sur dix secondes de C parfait. Aucune erreur, aucune
       trace, aucun test rouge : tous les tests de réveil passent
       `wakeIntervalMs` en surcharge explicite. Le piège se referme le jour où
       quelqu'un abaisse la cadence pour le processeur (200 → 500) ou où la
       Slice 08 descend `wakeGraceMs`. Il se refuse donc à la construction.
       `interval === grace` reste permis : un trou **égal** à la grâce n'est pas
       au-delà, et c'est le cas limite du réglage d'usine. */
    o.wakeIntervalMs=Math.max(0,Number(o.wakeIntervalMs)||0);
    o.wakeGraceMs=Math.max(0,Number(o.wakeGraceMs)||0);
    if(o.wakeIntervalMs>o.wakeGraceMs)
      throw new RangeError('wakeIntervalMs ne peut pas dépasser wakeGraceMs : le guetteur échantillonne à cette cadence, et un trou plus long que la grâce annule le maintien à chaque image — le réveil deviendrait impossible sans rien dire');
    o.margin=clamp(Number(o.margin)||0,0,.45);
    o.pressFrames=Math.max(1,Math.round(o.pressFrames));
    /* Une coupure nulle ou négative fige le filtre sur son premier point : le
       jeton ne bougerait plus, sans que rien ne le dise. */
    o.minCutoffHz=positive(o.minCutoffHz,DEFAULTS.minCutoffHz);
    o.dCutoffHz=positive(o.dCutoffHz,DEFAULTS.dCutoffHz);
    o.betaCutoff=atLeast(o.betaCutoff,0,DEFAULTS.betaCutoff);
    o.filterResetMs=atLeast(o.filterResetMs,0,DEFAULTS.filterResetMs);
    o.matchRadiusPalms=positive(o.matchRadiusPalms,DEFAULTS.matchRadiusPalms);
    o.predictMs=atLeast(o.predictMs,0,DEFAULTS.predictMs);
    o.trackVelocityBlend=clamp(atLeast(o.trackVelocityBlend,0,DEFAULTS.trackVelocityBlend),.01,1);
    o.qualityFloor=clamp(atLeast(o.qualityFloor,0,DEFAULTS.qualityFloor),0,1);
    o.qualityEdge=positive(o.qualityEdge,DEFAULTS.qualityEdge);
    o.qualityPalmMin=positive(o.qualityPalmMin,DEFAULTS.qualityPalmMin);
    o.qualityComplete=clamp(atLeast(o.qualityComplete,0,DEFAULTS.qualityComplete),0,1);
    o.qualityWarmupFrames=Math.max(1,Math.round(atLeast(o.qualityWarmupFrames,1,DEFAULTS.qualityWarmupFrames)));
    o.wakeHoldMs=Math.max(0,Number(o.wakeHoldMs)||0);
    o.sleepTimeoutMs=Math.max(0,Number(o.sleepTimeoutMs)||0);
    /* Septième invariant de paire, et le premier que les **réglages** rendent
       atteignable : la Slice 07 laisse l'utilisateur écrire `sleepTimeoutMs`.
       Sous `wakeHoldMs`, la seconde de posture en C coûte plus cher que tout
       le temps qu'elle achète : on réveille, et le minuteur d'inactivité a
       déjà expiré à l'image suivante. La session **cycle** — réveil, veille,
       réveil — en détruisant à chaque tour les identités de piste et les
       fentes de pointeur, exactement la panne que la reprise de la Slice 03 a
       mesurée par un autre chemin. Rien ne lève, rien ne tombe : le réveil a
       simplement l'air de ne pas tenir. L'égalité se refuse aussi, parce qu'un
       réveil qui dure exactement le temps de sa propre posture n'en est pas un.
       La borne basse du contrat (5 000 ms) est cinq fois au-dessus de
       `wakeHoldMs` : un réglage venu de l'écran ne peut pas l'atteindre, et
       c'est bien pour ça qu'il faut le refuser ici plutôt que d'y compter. */
    if(!(o.sleepTimeoutMs>o.wakeHoldMs))
      throw new RangeError('sleepTimeoutMs doit rester au-dessus de wakeHoldMs : sous cette durée, la veille reprend la main avant que la posture de réveil ait servi à quoi que ce soit, et la session cycle sans rien dire');
    o.wakeSoft=clamp(Number(o.wakeSoft)||0,0,.5);
    o.wakeScore=clamp(Number(o.wakeScore)||0,0,1);
    /* Quatrième invariant de paire : un doigt ne peut pas être « replié » plus
       loin qu'il n'est « tendu ». Inversés, la rampe d'extension se lirait à
       l'envers — un poing passerait pour une main ouverte, sans rien casser
       visiblement. Même forme, même refus que les trois autres. */
    if(!(o.fingerCurledPalms>0&&o.fingerCurledPalms<o.fingerExtendedPalms))
      throw new RangeError('fingerCurledPalms doit être positif et inférieur à fingerExtendedPalms');
    o.pinchMarginRatio=positive(o.pinchMarginRatio,DEFAULTS.pinchMarginRatio);
    o.pinchConfidenceMin=clamp(atLeast(o.pinchConfidenceMin,0,DEFAULTS.pinchConfidenceMin),0,1);
    o.clickMaxMs=Math.max(0,Number(o.clickMaxMs)||0);
    o.clickSlopPx=Math.max(0,Number(o.clickSlopPx)||0);
    o.dragSlopPx=Math.max(0,Number(o.dragSlopPx)||0);
    /* Cinquième invariant de paire, et la **troisième** fois que cette classe
       de défaut se présente sur cette tâche (après `smoothing` et
       `wakeIntervalMs`/`wakeGraceMs`) : le glissement se tranche en cours de
       route à `dragSlopPx`, le clic ne se juge qu'au relâchement. Un
       `clickSlopPx` au-dessus de `dragSlopPx` est donc **silencieusement
       tronqué** — le contact est déjà DRAG quand le test du clic s'exécute, et
       toute la tolérance au-delà de `dragSlopPx` est du réglage sans effet.
       `createPinchIntentEngine({clickSlopPx:100})` était accepté et ne
       changeait rien. Le contrat l'écrivait déjà (`clickSlopPx < dragSlopPx`) ;
       il se refuse désormais là où il se lit. L'égalité reste permise : elle
       tronque zéro. */
    if(o.clickSlopPx>o.dragSlopPx)
      throw new RangeError('clickSlopPx ne peut pas dépasser dragSlopPx : le glissement se tranche en chemin, donc toute tolérance de clic au-delà est tronquée sans rien dire');
    o.clickStillnessMin=clamp(atLeast(o.clickStillnessMin,0,DEFAULTS.clickStillnessMin),0,1);
    o.postureScore=clamp(atLeast(o.postureScore,0,DEFAULTS.postureScore),0,1);
    o.postureHoldMs=Math.max(0,Number(o.postureHoldMs)||0);
    o.doubleCloseMs=Math.max(0,Number(o.doubleCloseMs)||0);
    o.clapPalms=positive(o.clapPalms,DEFAULTS.clapPalms);
    o.clapSpeedPalms=atLeast(o.clapSpeedPalms,0,DEFAULTS.clapSpeedPalms);
    o.gestureCooldownMs=Math.max(0,Number(o.gestureCooldownMs)||0);
    o.targetZonePx=Math.max(0,Number(o.targetZonePx)||0);
    o.targetZoneHoldPx=Math.max(0,Number(o.targetZoneHoldPx)||0);
    o.targetAssistPx=Math.max(0,Number(o.targetAssistPx)||0);
    /* Sixième invariant de paire, et la **quatrième** fois que cette classe de
       défaut se présente sur cette tâche (après `smoothing`,
       `wakeIntervalMs`/`wakeGraceMs` et `clickSlopPx`/`dragSlopPx`) : la bande
       d'entrée et la bande de maintien sont l'hystérésis d'une zone, exactement
       comme `pressRatio`/`releaseRatio` le sont d'un contact. Inversées, la
       zone se perd **plus tôt** qu'elle ne se prend : le bord se prend à
       `targetZonePx`, se rend dès `targetZoneHoldPx`, et l'aperçu clignote
       précisément là où l'hystérésis existe pour qu'il ne clignote pas. Rien ne
       lève, rien ne tombe, et le symptôme se lit comme un tremblement de main.
       L'égalité reste permise : elle vaut « pas d'hystérésis », pas une
       inversion. */
    if(o.targetZoneHoldPx<o.targetZonePx)
      throw new RangeError('targetZoneHoldPx ne peut pas être sous targetZonePx : la bande qui garde une zone doit être au moins celle qui la prend, sinon l’aperçu clignote au lieu de tenir');
    /* Et un invariant à un seul nombre, qui efface une décision entière s'il
       passe : les deux bandes opposées d'un axe se rejoignent à la moitié du
       côté. À 0,5 il n'existe plus un seul point de **corps** dans un objet
       étroit — la décision 8 (BODY est de l'interaction de contenu) devient
       inatteignable sur les capsules, qui sont les objets les plus courants, et
       rien ne le dit. */
    o.targetZoneMaxRatio=Number(o.targetZoneMaxRatio);
    if(!(o.targetZoneMaxRatio>0&&o.targetZoneMaxRatio<.5))
      throw new RangeError('targetZoneMaxRatio doit rester entre 0 et 0,5 exclus : à la moitié du côté, les deux bandes opposées se rejoignent et le corps de l’objet disparaît');
    return o;
  }

  function distance(a,b,aspect){
    return Math.hypot((a.x-b.x)*aspect,a.y-b.y);
  }

  /* Ce que « main exploitable » veut dire, **une fois** pour tout le fichier.
     Il y en avait deux lectures : les jetons exigeaient `length > INDEX_TIP`,
     le guetteur et le minuteur de veille `length > MIDDLE_MCP`, et aucune des
     deux ne regardait les entrées. Un seul point absent faisait lever
     `cPoseScore` sur `landmarks[4].x`, ce que la boucle d'images convertit en
     `tracking_failed` : session terminée, caméra rendue, toast de 9 s — pour
     une image. Une image malformée se saute ; elle n'arrête rien.
     Seuls les quatre points réellement lus sont exigés : exiger les 21 aurait
     refusé une main partielle que le traqueur sait pourtant mesurer. */
  const USED_LANDMARKS=Object.freeze([LM.WRIST,LM.THUMB_TIP,LM.INDEX_TIP,LM.MIDDLE_MCP]);
  /* Points du pincement secondaire (décision 21) et des postures (Slice 04).
     Chaque moteur déclare **ce qu'il lit**, et le prédicat reste unique : la
     Slice 04 avait le choix entre élargir `USED_LANDMARKS` aux 21 points — ce
     qui aurait refusé une main partielle que le réveil sait pourtant mesurer,
     une régression silencieuse sur le chemin de la Slice 02 — et paramétrer la
     seule définition. C'est la seconde : une définition, plusieurs besoins. */
  const SECONDARY_LANDMARKS=Object.freeze([LM.WRIST,LM.THUMB_TIP,LM.MIDDLE_TIP,LM.MIDDLE_MCP]);
  const POSTURE_LANDMARKS=Object.freeze([LM.WRIST,LM.THUMB_TIP,LM.INDEX_TIP,LM.MIDDLE_MCP,
    LM.MIDDLE_TIP,LM.RING_TIP,LM.PINKY_TIP]);
  const usablePoint=point=>!!point&&Number.isFinite(Number(point.x))&&Number.isFinite(Number(point.y));
  const usableLandmarks=(landmarks,needed)=>{
    /* Ce prédicat doit rester **total** : c'est lui qui rend une image
       sautable, et une exception levée ici redeviendrait `tracking_failed`.
       Il ne refuse donc pas un second argument qui n'est pas une liste de
       points — un `usableLandmarks` passé à `.map` en reçoit l'indice — il
       retombe sur l'ensemble par défaut. */
    const points=Array.isArray(needed)&&needed.length?needed:USED_LANDMARKS;
    return Array.isArray(landmarks)
      &&landmarks.length>Math.max(...points)&&points.every(at=>usablePoint(landmarks[at]));
  };

  /* Écart pouce-index rapporté à la paume (poignet → base du majeur) : même
     seuil quelle que soit la distance à la caméra. `aspect` = largeur/hauteur
     de l'image, les coordonnées MediaPipe étant normalisées par axe. */
  /* Deux canaux, décidés par le **doigt**, jamais par la durée (décision 22) :
     pouce-index est le primaire (décision 20), pouce-majeur le secondaire
     (décision 21). La mesure est la même des deux côtés — c'est le point lu qui
     change — et les seuils aussi, puisque les deux se rapportent à la paume. */
  const PINCH_CHANNEL=Object.freeze({PRIMARY:'primary',SECONDARY:'secondary'});
  const PINCH_CHANNELS=Object.freeze([PINCH_CHANNEL.PRIMARY,PINCH_CHANNEL.SECONDARY]);
  const PINCH_TIP=Object.freeze({primary:LM.INDEX_TIP,secondary:LM.MIDDLE_TIP});
  const PINCH_POINTS=Object.freeze({primary:USED_LANDMARKS,secondary:SECONDARY_LANDMARKS});

  function pinchRatioFor(landmarks,aspect,channel){
    const tip=PINCH_TIP[channel];
    if(tip===undefined)
      throw new RangeError(`canal de pincement inconnu : ${String(channel)} (${PINCH_CHANNELS.join(', ')})`);
    if(!usableLandmarks(landmarks,PINCH_POINTS[channel]))return null;
    const k=Number(aspect)>0?Number(aspect):1;
    const palm=distance(landmarks[LM.WRIST],landmarks[LM.MIDDLE_MCP],k);
    if(!(palm>1e-6))return null;
    return distance(landmarks[LM.THUMB_TIP],landmarks[tip],k)/palm;
  }
  /* Le pincement primaire garde son nom et sa signature : c'est lui que le
     chemin de compatibilité du clic appelle depuis la Slice 00. */
  const pinchRatio=(landmarks,aspect)=>pinchRatioFor(landmarks,aspect,PINCH_CHANNEL.PRIMARY);

  /* Point normalisé de la caméra → pixels de la fenêtre (miroir, marge, bornes). */
  function toScreen(point,viewport,overrides){
    const o=options(overrides);
    let x=clamp(Number(point&&point.x)||0,0,1),y=clamp(Number(point&&point.y)||0,0,1);
    if(o.mirror)x=1-x;
    const span=1-2*o.margin;
    return {
      x:clamp((x-o.margin)/span,0,1)*Math.max(0,viewport.width),
      y:clamp((y-o.margin)/span,0,1)*Math.max(0,viewport.height),
    };
  }

  /* ------------------------------------------------------------------
     Filtre adaptatif du pointeur (architecture §3, Slice 03).

     Le lissage d'hier tenait dans un seul coefficient, `smoothing:.45`, le
     même quoi qu'il arrive. Un coefficient unique ne peut pas tenir les deux
     promesses à la fois : assez bas, il calme le tremblement du repos mais
     traîne derrière un geste rapide ; assez haut, il suit le geste mais laisse
     passer le tremblement. Il fallait choisir laquelle des deux sacrifier, et
     0,45 était le milieu qui rate les deux.

     Le filtre One Euro (Casiez, Roussel & Vogel, CHI 2012) fait varier la
     fréquence de coupure **avec la vitesse** : main posée → coupure basse →
     très lissé ; main qui file → coupure haute → presque transparent.
     Réimplémenté ici depuis la formule publiée ; aucune ligne de l'amont
     Barehands (décision 33).

       α(f) = 1 / (1 + (1/(2πf))/dt)                       dt en secondes
       v  = (x − x̂ₙ₋₁)/dt        v̂ = lissage(v, α(dCutoffHz))
       fc = minCutoffHz + betaCutoff·|v̂|
       x̂  = lissage(x, α(fc))

     `minCutoffHz` règle le repos, `betaCutoff` règle le retard. Les deux se
     mesurent, et un test les compare **tous les deux** au lissage fixe d'hier :
     gagner sur l'un en perdant sur l'autre n'est pas un progrès, c'est le
     compromis qu'on vient de refuser.

     Les positions sont en pixels de la fenêtre, les vitesses en pixels par
     seconde — l'unité est dans le nom (leçon de la reprise de la Slice 01). */
  const lowpass=()=>{
    let value=null;
    return {
      filter(x,alpha){value=value===null?x:value+alpha*(x-value);return value},
      value(){return value},
      reset(){value=null},
    };
  };

  function createPointerFilter(overrides){
    const o=options(overrides);
    const x=lowpass(),y=lowpass(),dx=lowpass(),dy=lowpass(),sx=lowpass(),sy=lowpass();
    let last=null,vx=0,vy=0;
    const alpha=(cutoff,seconds)=>{const tau=1/(2*Math.PI*cutoff);return 1/(1+tau/seconds)};
    const reset=()=>{x.reset();y.reset();dx.reset();dy.reset();sx.reset();sy.reset();last=null;vx=0;vy=0};
    const sample=(rawX,rawY)=>({
      x:x.value(),y:y.value(),rawX,rawY,
      vxPxPerSec:vx,vyPxPerSec:vy,speedPxPerSec:Math.hypot(vx,vy),
    });
    return {
      update(point,now){
        const rawX=Number(point&&point.x),rawY=Number(point&&point.y),at=Number(now);
        /* Tous les appelants passent par `usableLandmarks` avant d'arriver
           ici : un point inutilisable à ce stade est un défaut de code, pas
           une image bancale. Le taire ferait geler le jeton sur sa dernière
           position — un curseur immobile que l'utilisateur lit comme un
           plantage, sans rien à l'écran ni dans la console. La boucle d'images
           le convertit en `tracking_failed`, qui se voit et se journalise. */
        if(!Number.isFinite(rawX)||!Number.isFinite(rawY)||!Number.isFinite(at))
          throw Object.assign(new Error('filtre du pointeur : point ou horodatage inutilisable'),
            {code:'tracking_failed'});
        /* Leçon de la reprise de la Slice 02, reprise telle quelle : un trou
           est du temps **non observé**, et une vitesse calculée dessus est une
           invention — la main a pu aller n'importe où entre les deux. Au-delà
           de `filterResetMs` (onglet en arrière-plan, caméra figée, main
           revenue après une absence), le filtre repart du point présent au
           lieu de créditer l'intervalle. */
        if(last!==null&&at-last>o.filterResetMs)reset();
        const dt=last===null?0:at-last;
        last=at;
        if(!(dt>0)){
          /* Deux mesures au même instant, ou une horloge qui recule : aucune
             durée, donc aucune vitesse. On initialise plutôt que de diviser
             par zéro et de publier une vitesse infinie. */
          if(x.value()===null){x.filter(rawX,1);y.filter(rawY,1)}
          return sample(rawX,rawY);
        }
        const seconds=dt/1000;
        const smoothing=alpha(o.dCutoffHz,seconds);
        /* Dérivée **interne** du filtre, mesurée contre la sortie précédente
           comme l'exige la formule publiée. C'est un signal de commande, pas
           une mesure : sur une rampe, la sortie traîne d'un retard constant,
           et cette dérivée lit donc la vitesse *plus* ce retard divisé par dt
           — 1400 px/s pour une main à 900, et jusqu'à 40 px/s sur une main
           parfaitement immobile qui tremble de trois pixels. Publiée telle
           quelle elle aurait dit « la main bouge » au repos, et l'immobilité
           des Slices 04-06 n'aurait jamais valu 1. Elle sert à ouvrir la
           coupure, rien d'autre. */
        const rx=dx.filter((rawX-x.value())/seconds,smoothing);
        const ry=dy.filter((rawY-y.value())/seconds,smoothing);
        const cutoff=o.minCutoffHz+o.betaCutoff*Math.hypot(rx,ry);
        const a=alpha(cutoff,seconds);
        const fromX=x.value(),fromY=y.value();
        x.filter(rawX,a);y.filter(rawY,a);
        /* La vitesse **publiée** est celle du point filtré, lissée au même
           `dCutoffHz` : sans biais en régime établi (899 px/s mesurés pour 900
           réels) et déjà débarrassée du tremblement, puisqu'elle dérive d'un
           signal qui l'est. C'est la vitesse du curseur que l'interaction
           déplace — la seule dont une intention de clic ou de glissement peut
           répondre. */
        vx=sx.filter((x.value()-fromX)/seconds,smoothing);
        vy=sy.filter((y.value()-fromY)/seconds,smoothing);
        return sample(rawX,rawY);
      },
      reset,
    };
  }

  /* Immobilité. `stillness` est une rampe, pas un seuil : entre « posée » et
     « qui file », le doute est un nombre. `stillMs` dit **depuis quand** la
     main est posée — c'est cette durée que les Slices 04 à 06 liront pour
     distinguer un clic d'un début de glissement, parce que l'instantané passe
     sous le seuil une image au milieu d'un geste franc.

     **Les deux se lisent sur une vitesse qui met du temps à admettre un
     arrêt**, et ce délai fait partie du contrat plutôt que de se découvrir à
     l'intégration. La vitesse publiée est lissée à `dCutoffHz` = 1 Hz, soit
     τ ≈ 159 ms. Après une main à 900 px/s stoppée net, mesuré sur des images
     de 16 ms : `stillness` franchit 0,5 à ~250 ms, vaut 1 à ~585 ms, et
     `stillMs` ne commence à courir qu'à ce ~585 ms. Sur une inversion franche
     la vitesse garde le **mauvais signe** ~120 ms. C'est structurel : la même
     coupure basse est ce qui empêche le tremblement du repos de se lire comme
     un mouvement.

     Donc `stillMs` ne reconnaît pas une immobilité plus courte que ~600 ms
     après un geste franc, et une main qui arrive vite et pince aussitôt se lit
     *en mouvement, `stillMs` = 0*. Ce que cela coûte au clic de la Slice 04
     est chiffré dans `docs/barehands-contracts.md` (§ Temps d'établissement de
     la vitesse, et § Clic contre glissement). Un consommateur qui a besoin de
     « la main a-t-elle bougé » plutôt que « à quelle vitesse » doit lire un
     déplacement : la position filtrée, elle, ne traîne que de quelques pixels
     refermés en deux ou trois images. */
  function createStillness(overrides){
    const o=options(overrides);
    let stillMs=0,last=null;
    return {
      update(speed,now){
        const at=Number(now);
        const dt=last===null||!Number.isFinite(at)?0:Math.max(0,at-last);
        if(Number.isFinite(at))last=at;
        const value=Number(speed);
        const moving=!Number.isFinite(value)||value>o.stillSpeedPx;
        // Même borne que partout ailleurs : un intervalle non observé ne se
        // crédite pas — une main « immobile depuis 60 s » à travers un onglet
        // en arrière-plan serait un mensonge que les Slices suivantes liraient.
        if(moving||dt>o.filterResetMs)stillMs=0;else stillMs+=dt;
        return {stillness:Number.isFinite(value)?1-ramp(value,o.stillSpeedPx,o.moveSpeedPx):0,stillMs};
      },
      reset(){stillMs=0;last=null},
    };
  }

  /* Hystérésis du contact, **une fois** pour les deux moteurs qui la lisent.

     États : open → pinching (en cours) → pressed. Descendre exige `pressRatio`
     tenu `pressFrames` images d'affilée ; remonter exige de repasser au-dessus
     de `releaseRatio`, strictement plus haut. C'est cet écart entre les deux
     seuils — et lui seul — qui empêche le clignotement d'un doigt posé pile
     sur la limite.

     La Slice 04 ajoute un second canal (pouce-majeur, décision 21) et un flux
     de contact ; recopier ces quinze lignes aurait donné deux hystérésis à
     régler et une seule documentée. Le chemin de compatibilité du clic
     (`createPinchDetector`) et le moteur d'intention (`createPinchChannel`)
     lisent donc la même machine, et `entered` est la seule information dont
     ils font deux choses différentes. */
  function createContactState(o){
    let state='open',frames=0;
    return {
      update(ratio){
        if(ratio===null||ratio===undefined||!isFinite(ratio)){
          state='open';frames=0;
          return {state,progress:0,entered:false};
        }
        let entered=false;
        if(state==='pressed'){
          if(ratio>o.releaseRatio){state='open';frames=0}
        }else if(ratio<=o.pressRatio){
          frames+=1;
          if(frames>=o.pressFrames){state='pressed';frames=0;entered=true}
          else state='pinching';
        }else if(ratio<o.releaseRatio){state='pinching';frames=0}
        else{state='open';frames=0}
        const progress=state==='pressed'?1:state==='open'?0:
          clamp((o.releaseRatio-ratio)/(o.releaseRatio-o.pressRatio),0,1);
        return {state,progress,entered};
      },
      reset(){state='open';frames=0},
      state(){return state},
    };
  }

  /* Pincement d'une main, chemin de compatibilité du clic (Slice 00 à 03) : le
     clic part une seule fois, au passage en pressed, et `cooldownMs` absorbe
     les rebonds d'un relâchement bref. La Slice 06 lui substituera le flux de
     contact ; d'ici là les deux coexistent sur la même hystérésis. */
  function createPinchDetector(overrides){
    const o=options(overrides);
    const contact=createContactState(o);
    let lastClickAt=-Infinity;
    return {
      update(ratio,now){
        const out=contact.update(ratio);
        let click=false;
        if(out.entered&&now-lastClickAt>=o.cooldownMs){click=true;lastClickAt=now}
        return {state:out.state,progress:out.progress,click};
      },
      reset(){contact.reset()},
      state(){return contact.state()},
    };
  }

  /* Rampe linéaire : 0 en `a`, 1 en `b`, bornée. */
  const ramp=(v,a,b)=>a===b?(v>=b?1:0):clamp((v-a)/(b-a),0,1);

  /* Posture de réveil (décision 5) : le « C » du pré-pincement — pouce et
     index écartés sans se toucher, index déplié. Score 0..1, `null` si la main
     n'est pas exploitable. Deux mesures suffisent et se mesurent en paumes,
     donc sans dépendre de la distance à la caméra :

     - l'ouverture du C, entre `wakeGapMin` (au-dessus du relâchement du
       pincement : un pincement en cours ne réveille pas) et `wakeGapMax`
       (au-delà, c'est une main ouverte) ;
     - la portée de l'index depuis le poignet, qui écarte le poing, où l'écart
       pouce-index tomberait par hasard dans la bande.

     Les bords des deux plages retombent à 0 sur `wakeSoft` de leur largeur :
     une posture limite donne un score faible, donc un maintien qui n'aboutit
     pas, plutôt qu'un réveil clignotant. */
  function cPoseScore(landmarks,aspect,overrides){
    const o=options(overrides);
    if(!usableLandmarks(landmarks))return null;
    const k=Number(aspect)>0?Number(aspect):1;
    const palm=distance(landmarks[LM.WRIST],landmarks[LM.MIDDLE_MCP],k);
    if(!(palm>1e-6))return null;
    /* Un pincement **en cours** ne réveille pas. La Slice 02 l'a garanti côté
       index, par construction : `wakeGapMin` (0,46) reste au-dessus de
       `releaseRatio` (0,42), donc un pouce posé sur l'index sort de la bande.
       Le canal secondaire de la décision 21 n'existait pas alors, et il échappe
       à cette garantie : **le pouce posé sur le majeur laisse l'écart
       pouce-index en plein milieu de la bande du C** — mesuré à 0,69 sur un
       pincement secondaire franc, entre 0,499 et 0,811. Un clic droit tenu une
       seconde réveillait donc la veille, et le moteur de gestes lisait « C » sur
       une main qui pince. La géométrie ne peut pas le dire toute seule : elle
       doit lire le second doigt. Absent du traqueur, il n'y a pas de pincement
       secondaire connu, donc rien à écarter — la mesure du C reste celle de la
       Slice 02, sur ses quatre points.

       Cette exclusion était d'abord un `return 0` sec au-dessus de
       `releaseRatio` — la **seule** frontière non adoucie d'un fichier qui
       adoucit toutes les autres, et pour la raison qu'elles le sont : une main
       dont le pouce passe près du majeur sans rien pincer clignotait 1 ↔ 0 sur
       le tremblement du traqueur, n'aboutissait jamais au maintien d'une
       seconde, et ne disait pas pourquoi. Mesuré sur 1 152 poses en C
       géométriquement valides, la falaise en annulait **167** — un C qui
       s'ouvre vers le bas, pouce sous le bout de l'index, majeur à demi replié.
       C'est donc une rampe, sur la bande que l'hystérésis possède déjà : zéro
       sous `pressRatio` — le seuil où le contact **entre** réellement, et le
       plus proche de l'état de contact qu'un score sans mémoire puisse lire —
       et plein au-dessus de `releaseRatio`. 45 de ces 167 poses repassent
       au-dessus du seuil de maintien, les 122 autres gagnent un score gradué
       au lieu d'un zéro, et un vrai pincement secondaire (rapport ≤ 0,28)
       reste exactement à zéro. */
    const secondary=pinchRatioFor(landmarks,k,PINCH_CHANNEL.SECONDARY);
    const apart=secondary===null?1:ramp(secondary,o.pressRatio,o.releaseRatio);
    const gap=distance(landmarks[LM.THUMB_TIP],landmarks[LM.INDEX_TIP],k)/palm;
    const reach=distance(landmarks[LM.WRIST],landmarks[LM.INDEX_TIP],k)/palm;
    const soft=Math.max(1e-6,(o.wakeGapMax-o.wakeGapMin)*o.wakeSoft);
    const open=Math.min(ramp(gap,o.wakeGapMin,o.wakeGapMin+soft),1-ramp(gap,o.wakeGapMax-soft,o.wakeGapMax));
    const extended=ramp(reach,o.wakeIndexMin,o.wakeIndexMin*(1+o.wakeSoft));
    return clamp(Math.min(open,extended,apart),0,1);
  }

  /* Maintien du réveil : la posture doit tenir `wakeHoldMs` d'affilée. Le
     temps vient de l'appelant (horloge injectée : aucun minuteur ici), et seul
     l'intervalle entre deux mesures *consécutivement* tenues est compté — une
     posture qui vient d'apparaître ne crédite pas le temps passé sans elle.
     Une perte plus courte que `wakeGraceMs` est un trou du traqueur et garde
     la progression ; au-delà, tout retombe à zéro, progression comprise, et le
     réveil redevient possible. `wake` ne part qu'une fois par maintien.

     Une perte se dit de deux façons, et la tolérance est la même pour les
     deux : une mesure explicitement non tenue, et **un trou entre deux
     mesures**. Un intervalle pendant lequel `update` n'est pas appelé est du
     temps *non observé* : rien n'y atteste la posture. Le créditer rendait une
     seconde de maintien à partir de deux images — une caméra figée (le
     guetteur sort avant d'appeler ici), un onglet en arrière-plan ou un écran
     rabattu (l'horloge avance, pas la boucle d'images) suffisaient à entrer en
     interaction sur une posture vaguement en C tenue une seule image, et
     l'anneau de progression de la décision 5 sautait de 0 à 100 % sans jamais
     se dessiner. Au-delà de `wakeGraceMs`, le trou se lit donc comme la perte
     qu'il est, et le maintien recommence — observé, cette fois. */
  function createWakeDetector(overrides){
    const o=options(overrides);
    let held=0,last=null,wasHeld=false,lostSince=null,fired=false;
    const report=wake=>({progress:o.wakeHoldMs>0?clamp(held/o.wakeHoldMs,0,1):1,wake,heldMs:held});
    return {
      update(score,now){
        const t=Number(now);
        const at=Number.isFinite(t)?t:0;
        const dt=last===null?0:Math.max(0,at-last);
        last=at;
        /* Trou plus long que la tolérance : tout ce qui précède est hors de
           vue, donc perdu. La mesure présente ouvre un nouveau maintien. */
        if(dt>o.wakeGraceMs){held=0;wasHeld=false;lostSince=null;fired=false}
        const value=Number(score);
        const holding=Number.isFinite(value)&&value>=o.wakeScore;
        if(!holding){
          wasHeld=false;
          if(lostSince===null)lostSince=at;
          if(at-lostSince>o.wakeGraceMs){held=0;fired=false}
          return report(false);
        }
        lostSince=null;
        if(fired)return report(false);
        if(wasHeld)held=Math.min(o.wakeHoldMs,held+dt);
        wasHeld=true;
        if(held>=o.wakeHoldMs){fired=true;return report(true)}
        return report(false);
      },
      reset(){held=0;last=null;wasHeld=false;lostSince=null;fired=false},
      heldMs(){return held},
    };
  }

  /* ------------------------------------------------------------------
     Gestes sémantiques (architecture §4, Slice 04).

     Cinq noms, tous du contrat (`JarvisBarehandsContracts.GESTURE`) : le bloc
     pur est chargé seul par les tests node et ne peut pas le lire, donc il les
     recopie et un test de parité refuse la dérive — même dispositif que
     `STATE` / `LIFECYCLE` depuis la Slice 02.

     **La posture en C n'est pas réimplantée.** `cPoseScore` la mesure depuis la
     Slice 02, avec sa bande effective calibrée et son test de balayage ; le
     moteur de gestes l'appelle. Une seconde lecture du C aurait été un second
     jeu de seuils à calibrer, et la Slice 08 n'aurait pas su lequel.

     Ce qui distingue les postures les unes des autres, en une phrase chacune :

     - **poing** : les quatre doigts repliés. Le pouce n'y entre pas — dans un
       poing il est tantôt dedans, tantôt dessus.
     - **main ouverte** : les quatre doigts tendus **et** le pouce écarté
       au-delà de la bande du C. La seconde condition n'est pas décorative :
       `wakeGapMax` est, par sa propre définition, « l'écart où le score du C
       tombe à zéro côté main ouverte ». La lire ici fait des deux postures des
       exclusives *par construction*, plutôt que par un réglage qui se
       trouverait bien choisi.
     - **C** : index tendu, pouce écarté sans toucher — donc ni un poing
       (l'index est tendu) ni une main ouverte (l'écart reste sous
       `wakeGapMax`).

     Les trois scores sont des rampes, pas des seuils : un doigt à moitié plié
     donne un score moyen, donc une posture qui n'aboutit pas, plutôt qu'un
     geste qui clignote. `postureHoldMs` finit le travail — une posture doit
     tenir avant de s'annoncer, et le temps non observé ne compte pas
     (leçon de la reprise de la Slice 02, troisième application dans ce
     fichier). */
  const GESTURE=Object.freeze({C_POSE:'c_pose',OPEN_PALM:'open_palm',FIST:'fist',
    DOUBLE_CLOSE:'double_close',CLAP:'clap'});
  const GESTURES=Object.freeze(Object.keys(GESTURE).map(k=>GESTURE[k]));
  const GESTURE_PHASE=Object.freeze({START:'start',HOLD:'hold',END:'end',CANCEL:'cancel'});
  const GESTURE_SCOPE=Object.freeze({GLOBAL:'global',HAND:'hand'});
  /* Postures **tenues** : elles ont une progression, un début et une fin. Les
     deux autres gestes sont ponctuels et ne portent qu'une fin. */
  const POSTURE_GESTURES=Object.freeze([GESTURE.C_POSE,GESTURE.OPEN_PALM,GESTURE.FIST]);

  /* Arbitrage (architecture §4) : « un geste global ne vole pas la main à une
     manipulation capturée, sauf autorisation explicite ». Deux portées, deux
     questions différentes :

     - `global` — le geste agit sur toute l'application. Il se tait dès que
       **n'importe quelle** main tient une capture.
     - `hand` — le geste appartient à la main qui le fait. Il se tait quand
       **cette** main tient une capture, et reste permis pendant que l'autre
       main manipule : la décision 12 veut deux mains indépendantes.

     `duringCapture` est l'« autorisation explicite », et elle n'est pas
     décorative : la main ouverte est la **sortie de secours**. Une
     manipulation qu'on ne peut pas abandonner est un piège, et le geste
     universel pour lâcher doit fonctionner précisément au moment où quelque
     chose est tenu. Les autres se taisent. `captured` vient de l'appelant — la
     Slice 06 possède les captures — et vaut vide tant qu'elle n'existe pas. */
  const GESTURE_RULES=Object.freeze({
    c_pose:Object.freeze({scope:GESTURE_SCOPE.HAND,duringCapture:false}),
    open_palm:Object.freeze({scope:GESTURE_SCOPE.GLOBAL,duringCapture:true}),
    fist:Object.freeze({scope:GESTURE_SCOPE.HAND,duringCapture:false}),
    double_close:Object.freeze({scope:GESTURE_SCOPE.HAND,duringCapture:false}),
    clap:Object.freeze({scope:GESTURE_SCOPE.GLOBAL,duringCapture:false}),
  });
  const gestureScope=gesture=>(GESTURE_RULES[gesture]||{}).scope||null;
  /* Repli pour un geste sans règle. `gestureScope` se gardait déjà ; la
     publication du moteur lisait `GESTURE_RULES[gesture].duringCapture` à nu,
     et une sixième posture ajoutée un jour aurait levé **dans la boucle
     d'images**, c'est-à-dire en `tracking_failed` : caméra rendue, session
     terminée, pour un nom manquant dans une table. Le contrat, lui, refuse un
     geste inconnu (`barehands_gesture_unknown`) — c'est la bonne réponse hors
     de la boucle, où le refus se lit.
     Le repli est le plus **silencieux** possible : portée globale et aucune
     autorisation pendant une capture, donc un geste sans règle ne peut jamais
     voler la main à une manipulation en cours. Le contrat prend le repli
     inverse sur une portée inconnue (`global` y est le plus dangereux) parce
     qu'il décrit un événement déjà émis ; ici on décide d'émettre. */
  const UNRULED_GESTURE=Object.freeze({scope:GESTURE_SCOPE.GLOBAL,duringCapture:false});
  const ruleFor=gesture=>GESTURE_RULES[gesture]||UNRULED_GESTURE;

  const FINGER=Object.freeze({index:LM.INDEX_TIP,middle:LM.MIDDLE_TIP,ring:LM.RING_TIP,pinky:LM.PINKY_TIP});
  const FINGERS=Object.freeze(Object.keys(FINGER));

  /* Centre de la paume : le même repère que l'identité de la Slice 03, pour
     que le claquement se mesure entre deux mains et non entre deux index qui
     voyagent. */
  const palmCenter=landmarks=>({
    x:(landmarks[LM.WRIST].x+landmarks[LM.MIDDLE_MCP].x)/2,
    y:(landmarks[LM.WRIST].y+landmarks[LM.MIDDLE_MCP].y)/2});

  /* Extension des quatre doigts, **une fois** pour les deux questions qui la
     posent : la posture (`handPosture`, qui nomme le geste) et la fermeture de
     main entière (`handClosure`, qui interdit un contact). Recopier la boucle
     aurait donné deux lectures d'« un doigt est-il tendu » à calibrer et une
     seule documentée — même raison que l'extraction de `createContactState`.

     Elle se lit sur les points **présents**, pas sur les sept de
     `POSTURE_LANDMARKS` : `handPosture` exige les sept avant d'appeler, mais
     `handClosure` doit répondre à une main dont l'annulaire manque — ce sont
     les deux derniers doigts que l'occlusion emporte en premier, et refuser de
     conclure là voudrait dire « aucun pincement ne peut commencer pendant que
     l'auriculaire est caché ». `readable` dit sur combien de doigts la réponse
     s'appuie ; `highest` reste le maximum de ceux-là, ce qui est la lecture
     prudente : un seul doigt tendu suffit à dire que la main n'est pas fermée,
     et il est vu ou il ne l'est pas. */
  function fingerExtensions(landmarks,k,palm,o){
    const extension={};
    /* La portée **en paumes**, à côté du score de rampe qu'on en tire. Elle
       était calculée puis jetée, si bien que le seul moyen de la relire était
       de recalculer `distance/palm` ailleurs — et la Slice 08 en a besoin pour
       dire à l'utilisateur *de combien* sa portée d'index manque la bande de
       réveil. Un score de rampe ne le dit pas : à 0 il dit « en dessous »,
       pas « en dessous de combien ». */
    const reach={};
    let lowest=1,highest=0,readable=0;
    for(const finger of FINGERS){
      const at=FINGER[finger];
      if(!usablePoint(landmarks[at])){extension[finger]=null;reach[finger]=null;continue}
      const palms=distance(landmarks[LM.WRIST],landmarks[at],k)/palm;
      const value=ramp(palms,o.fingerCurledPalms,o.fingerExtendedPalms);
      extension[finger]=value;reach[finger]=palms;readable+=1;
      lowest=Math.min(lowest,value);highest=Math.max(highest,value);
    }
    return {extension,reach,lowest,highest,readable};
  }

  /* **Fermeture de main entière**, 0..1, ou `null` si aucun bout de doigt ne
     se lit. C'est le second témoin qu'exigeait la décision 21 : la marge entre
     les deux canaux ne pouvait pas, à elle seule, séparer un poing d'un clic
     droit. Un poing rapproche le pouce de l'index *et* du majeur, mais il fait
     aussi — et c'est **sa** définition, pas une coïncidence de seuils —
     replier les quatre doigts. L'engin de pincement lit donc ici ce que le
     vocabulaire des gestes appelle déjà « poing », avec les mêmes deux
     constantes et aucune de plus.

     Mesuré : 1,000 sur toute la famille des poings (doigts à 0,7 / 0,8 / 0,9
     paume, pouce sur l'index comme pouce replié en travers de la paume),
     0,000 sur tous les pincements francs (primaire, secondaire, index écarté)
     et sur le C. La séparation est pleine échelle ; celle que la marge seule
     offrait valait 0,02 paume. */
  function handClosure(landmarks,aspect,overrides){
    const o=options(overrides);
    if(!Array.isArray(landmarks))return null;
    if(!usablePoint(landmarks[LM.WRIST])||!usablePoint(landmarks[LM.MIDDLE_MCP]))return null;
    const k=Number(aspect)>0?Number(aspect):1;
    const palm=distance(landmarks[LM.WRIST],landmarks[LM.MIDDLE_MCP],k);
    if(!(palm>1e-6))return null;
    const read=fingerExtensions(landmarks,k,palm,o);
    return read.readable?clamp(1-read.highest,0,1):null;
  }

  /* Posture d'une main, ou `null` si l'image ne porte pas les points qu'elle
     lit. `null` veut dire **sautée**, jamais « posture relâchée » : une image
     malformée ne doit pas interrompre un geste en cours (règle de la reprise
     de la Slice 02, appliquée ici à la lettre). */
  function handPosture(landmarks,aspect,overrides){
    const o=options(overrides);
    if(!usableLandmarks(landmarks,POSTURE_LANDMARKS))return null;
    const k=Number(aspect)>0?Number(aspect):1;
    const palm=distance(landmarks[LM.WRIST],landmarks[LM.MIDDLE_MCP],k);
    if(!(palm>1e-6))return null;
    // Les sept points sont là (`POSTURE_LANDMARKS`) : les quatre doigts se
    // lisent tous, `extension` ne porte donc aucun `null` de ce côté-ci.
    const {extension,reach,lowest,highest}=fingerExtensions(landmarks,k,palm,o);
    const gap=distance(landmarks[LM.THUMB_TIP],landmarks[LM.INDEX_TIP],k)/palm;
    /* Même adoucissement que le C, et pour la même raison : une frontière nette
       ferait clignoter la posture d'un pouce posé pile dessus. */
    const soft=Math.max(1e-6,(o.wakeGapMax-o.wakeGapMin)*o.wakeSoft);
    /* **Une main qui pince n'est pas une posture.** Le C était protégé du
       pincement primaire par construction depuis la Slice 02 (`wakeGapMin` au
       dessus de `releaseRatio`) ; ni lui ni la main ouverte ne l'étaient du
       canal secondaire, qui pousse le pouce **de côté** au lieu de le
       rapprocher de l'index : un clic droit tenu marquait 0,56 en main ouverte
       et 1 en C. Les deux canaux répondent donc ici à la même question, une
       fois, plutôt que chaque posture à la sienne. Le poing n'en est pas
       exempté pour rien : il ferme les deux rapports par nature, et c'est
       l'extension des doigts — pas le pouce — qui le nomme. */
    const contact=PINCH_CHANNELS.some(channel=>{
      const ratio=pinchRatioFor(landmarks,k,channel);
      return ratio!==null&&ratio<o.releaseRatio;
    });
    const scores={};
    scores[GESTURE.C_POSE]=cPoseScore(landmarks,k,overrides)||0;
    scores[GESTURE.OPEN_PALM]=contact?0
      :clamp(Math.min(lowest,ramp(gap,o.wakeGapMax-soft,o.wakeGapMax)),0,1);
    scores[GESTURE.FIST]=clamp(1-highest,0,1);
    return {extension:Object.freeze(extension),
      /* La portée de chaque doigt depuis le poignet, **en paumes** — la même
         grandeur que `wakeIndexMin`, donc celle que la Slice 08 compare à la
         bande de réveil. `extension` en est le score de rampe : à 0 il dit
         « en dessous », jamais « en dessous de combien ». */
      reach:Object.freeze(reach),gapPalms:gap,
      /* Nom trompeur conservé par compatibilité : c'est la paume en
         **coordonnées normalisées de l'image** (poignet → base du majeur), pas
         un rapport à elle-même. C'est elle qui convertit une mesure en paumes
         vers la fraction d'image que le profil persiste. */
      palmPalms:palm,center:palmCenter(landmarks),scores:Object.freeze(scores)};
  }

  /* Moteur de gestes. Une image entre, des événements sortent — aucun DOM,
     aucune horloge, aucune action : les liaisons geste → effet appartiennent
     aux Slices 05 et 06, et c'est ce qui les garde « découplées de la
     reconnaissance » (contrat de la Slice).

     Entrée : `{hands:[{handTrackId, landmarks}], now, aspect, captured}`.
     Sortie : `{events, suppressed, postures}` — `suppressed` existe pour que
     l'arbitrage soit **visible** : un geste qui disparaît sans trace est
     indiscernable d'un geste qui n'a pas été reconnu, et c'est la question
     qu'on se posera le premier jour où l'on croira que le moteur ne marche
     pas. */
  function createGestureEngine(overrides){
    const o=options(overrides);
    const hands=new Map();
    let clapAt=-Infinity,lastSpan=null,lastSpanAt=null;

    const fresh=()=>{
      const postures={};
      /* `started` = la posture a fini son maintien ; `announced` = son `start`
         est **parti**. Les deux ne sont pas le même fait : un `start` étouffé
         par une capture laisse `started` vrai — la reconnaissance continue,
         c'est voulu — mais rien n'a été annoncé, donc rien n'a à être rendu. */
      for(const gesture of POSTURE_GESTURES)
        postures[gesture]={heldMs:0,holding:false,started:false,announced:false};
      return {at:null,postures,closes:[],doubleAt:-Infinity};
    };

    return {
      update(frame){
        const f=frame||{};
        const now=Number(f.now);
        if(!Number.isFinite(now))
          throw Object.assign(new Error('moteur de gestes : horodatage inutilisable'),{code:'tracking_failed'});
        const k=Number(f.aspect)>0?Number(f.aspect):1;
        const captured=new Set([...(f.captured||[])].map(id=>String(id)));
        const list=Array.isArray(f.hands)?f.hands:[];
        const events=[],suppressed=[],postures=[];

        /* L'arbitrage se décide **au moment de publier**, pas au moment de
           reconnaître : la reconnaissance continue pendant une capture (la
           posture garde sa progression, son début et sa fin), seule la
           publication se tait. Sans cela, relâcher une capture ferait
           réapparaître un geste à moitié construit. */
        const build=(gesture,phase,handTrackId,progress,confidence)=>({
          gesture,phase,scope:ruleFor(gesture).scope,
          handTrackId:handTrackId===null||handTrackId===undefined?null:handTrackId,
          t:now,progress:clamp(progress,0,1),confidence:clamp(confidence,0,1)});
        /* **Une demande d'agir** : `start`, `hold`, et la fin des deux gestes
           ponctuels (le claquement et le double, qui n'ont que celle-là et
           dont elle *est* la demande). Arbitrée. */
        const publish=(gesture,phase,handTrackId,progress,confidence)=>{
          const rule=ruleFor(gesture);
          const blocked=!rule.duringCapture&&(rule.scope===GESTURE_SCOPE.GLOBAL
            ?captured.size>0
            :handTrackId!==null&&captured.has(String(handTrackId)));
          const event=build(gesture,phase,handTrackId,progress,confidence);
          if(blocked)suppressed.push({...event,reason:'capture_active'});
          else events.push(event);
          return !blocked;
        };
        /* **Une libération** : la fin ou l'annulation d'une posture dont le
           `start` est déjà parti. Toujours délivrée, capture ou pas.

           L'arbitrage ne peut pas être la même règle pour les deux. Un `start`
           demande d'agir — l'étouffer ne coûte que l'action qui n'a pas eu
           lieu. Un `end`/`cancel` rend quelque chose sur quoi le consommateur
           a **déjà** agi : l'étouffer le laisse accroché pour toujours.
           Mesuré : un poing annoncé libre, puis une capture prise, puis la
           main ouverte → `fist:end` étouffé, et plus rien ensuite ; sur une
           perte de main, `fist:cancel` étouffé **et** l'état effacé dans la
           foulée, si bien que rien ne pouvait plus corriger. L'invariant est
           désormais : tout `start` publié reçoit exactement une phase
           terminale, et aucune phase terminale n'arrive sans `start`. */
        const release=(gesture,phase,handTrackId,progress,confidence)=>{
          events.push(build(gesture,phase,handTrackId,progress,confidence));
        };

        /* Purge **avant** de lire, comme la Slice 03 : une boucle d'images
           arrêtée ne purge rien si l'on purge après, et la première image du
           retour retrouverait une posture vieille de dix secondes encore
           « tenue ». La grâce est `lostGraceMs`, la seule horloge d'identité de
           ce fichier : une posture vit exactement aussi longtemps que la main
           qui la tient. */
        for(const [id,state] of [...hands]){
          if(state.at!==null&&now-state.at<=o.lostGraceMs)continue;
          /* La main s'en va et son état part avec elle : c'est la **dernière**
             occasion de rendre ce qui a été annoncé. Un `cancel` étouffé ici
             ne revenait jamais, puisque la ligne suivante efface l'état. */
          for(const gesture of POSTURE_GESTURES)
            if(state.postures[gesture].announced)release(gesture,GESTURE_PHASE.CANCEL,id,0,0);
          hands.delete(id);
        }

        const seen=[];
        for(const hand of list){
          const id=hand&&hand.handTrackId;
          if(id===undefined||id===null)continue;
          const posture=handPosture(hand.landmarks,k,overrides);
          // Image sautée : ni progression créditée, ni geste interrompu.
          if(!posture)continue;
          const key=String(id);
          if(!hands.has(key))hands.set(key,fresh());
          const state=hands.get(key);
          const dt=state.at===null||now-state.at>o.lostGraceMs?0:Math.max(0,now-state.at);
          state.at=now;
          seen.push({id,posture});
          for(const gesture of POSTURE_GESTURES){
            const own=state.postures[gesture];
            const score=posture.scores[gesture];
            const holding=score>=o.postureScore;
            if(!holding){
              /* Rendu seulement si quelque chose a été annoncé. Sans ce test,
                 un `start` étouffé par une capture produisait tout de même un
                 `end` : un consommateur qui apparie début et fin voyait une
                 fin orpheline, et croyait relâcher ce qu'il n'avait jamais
                 pris. L'autre moitié du même invariant. */
              if(own.announced)release(gesture,GESTURE_PHASE.END,id,1,score);
              own.started=false;own.announced=false;own.holding=false;own.heldMs=0;
              continue;
            }
            /* Une posture qui vient d'apparaître ne crédite pas le temps passé
               sans elle : seul l'intervalle entre deux mesures **consécutivement
               tenues** compte. */
            if(own.holding)own.heldMs=Math.min(o.postureHoldMs,own.heldMs+dt);
            own.holding=true;
            if(own.started)continue;
            if(own.heldMs>=o.postureHoldMs){
              own.started=true;
              own.announced=publish(gesture,GESTURE_PHASE.START,id,1,score);
              if(gesture===GESTURE.FIST){
                /* Double fermeture : deux poings **commencés** dans la fenêtre.
                   Le poing garde ses propres événements — un consommateur lié
                   au poing et un consommateur lié au double ne se volent pas,
                   ils se choisissent à la liaison (Slices 05/06). */
                const previous=state.closes.length?state.closes[state.closes.length-1]:null;
                state.closes.push(now);
                if(state.closes.length>2)state.closes.shift();
                if(previous!==null&&now-previous<=o.doubleCloseMs
                  &&now-state.doubleAt>=o.gestureCooldownMs){
                  state.doubleAt=now;state.closes=[];
                  publish(GESTURE.DOUBLE_CLOSE,GESTURE_PHASE.END,id,1,score);
                }
              }
            }else publish(gesture,GESTURE_PHASE.HOLD,id,
              o.postureHoldMs>0?own.heldMs/o.postureHoldMs:1,score);
          }
          /* L'instantané est pris **après** la mise à jour : pris avant, il
             décrivait l'image précédente, et l'anneau de la Slice 05 aurait
             toujours eu une image de retard sur l'événement qui l'accompagne
             — deux chiffres différents pour le même instant. */
          postures.push({handTrackId:id,scores:posture.scores,extension:posture.extension,
            gapPalms:posture.gapPalms,
            progress:Object.freeze(POSTURE_GESTURES.reduce((acc,gesture)=>{
              const own=state.postures[gesture];
              acc[gesture]=own.started?1
                :o.postureHoldMs>0?clamp(own.heldMs/o.postureHoldMs,0,1):1;
              return acc;
            },{}))});
        }

        /* Claquement : deux paumes qui se rejoignent. La distance seule ne
           suffit pas — deux mains posées côte à côte la franchiraient sans que
           rien ne se passe — donc on exige aussi une **vitesse de
           rapprochement**, mesurée entre deux images observées. Au-delà de
           `lostGraceMs`, il n'y a pas de vitesse : il y a un trou. */
        let span=null;
        if(seen.length===2){
          const [a,b]=seen;
          const scale=(a.posture.palmPalms+b.posture.palmPalms)/2;
          if(scale>1e-6)span=Math.hypot((a.posture.center.x-b.posture.center.x)*k,
            a.posture.center.y-b.posture.center.y)/scale;
        }
        if(span!==null){
          const dt=lastSpanAt===null||now-lastSpanAt>o.lostGraceMs?0:now-lastSpanAt;
          const closing=dt>0&&lastSpan!==null?(lastSpan-span)/(dt/1000):0;
          if(span<=o.clapPalms&&closing>=o.clapSpeedPalms&&now-clapAt>=o.gestureCooldownMs){
            clapAt=now;
            publish(GESTURE.CLAP,GESTURE_PHASE.END,null,1,clamp(ramp(closing,0,o.clapSpeedPalms*2),0,1));
          }
        }
        lastSpan=span;lastSpanAt=span===null?null:now;
        return {events,suppressed,postures};
      },
      reset(){hands.clear();clapAt=-Infinity;lastSpan=null;lastSpanAt=null},
      size(){return hands.size},
    };
  }

  /* ------------------------------------------------------------------
     Intention de pincement (architecture §5, décisions 20-22, Slice 04).

     Le pincement est un **flux de contact**, pas une commande de clic :
     approche, descente, déplacement, remontée, annulation — avec un canal
     `primary` (pouce-index, décision 20) ou `secondary` (pouce-majeur,
     décision 21). Le clic droit est un **doigt**, jamais un appui long
     (décision 22) ; la durée et le déplacement du canal primaire servent à
     autre chose : distinguer un clic d'un glissement.

     Ce qui sépare réellement les deux canaux n'est pas un seuil mais une
     **marge**. Une main qui se ferme entièrement rapproche le pouce de l'index
     *et* du majeur : les deux rapports tombent ensemble, et un moteur qui
     regarderait chaque canal isolément lirait un clic droit dans un poing. La
     confiance d'un canal est donc l'écart qui le sépare de l'autre — nulle
     quand les deux se valent — et il faut `pinchConfidenceMin` pour descendre
     en contact. C'est ce que demande le contrat de la Slice : « rejeter la
     fermeture de main entière comme clic droit ». */
  const PINCH_PHASE=Object.freeze({APPROACH:'approach',DOWN:'down',MOVE:'move',UP:'up',CANCEL:'cancel'});
  const PINCH_INTENT=Object.freeze({UNDECIDED:'undecided',CLICK:'click',DRAG:'drag'});

  function createPinchChannel(channel,overrides){
    const o=options(overrides);
    const contact=createContactState(o);
    let held=null,lastProgress=null,lastX=null,lastY=null;

    /* Quel point porte l'événement, et pourquoi ce n'est pas le même partout :
       `approach` et `down` visent l'**ancre**, figée quand les doigts ont
       commencé à se rapprocher, pour que la cible ne glisse pas sous la main
       au moment de cliquer ; `move` et `up` suivent la position **filtrée**,
       parce qu'un glissement qui resterait sur l'ancre ne déplacerait rien.
       Sur un clic les deux sont à moins de `clickSlopPx` l'une de l'autre, par
       définition du clic. */
    /* **Où est la main**, par opposition à où elle vise. `x`/`y` suivent le
       bout de l'index : c'est ce que l'utilisateur pointe, et c'est juste pour
       le pointeur. C'était faux pour le **déplacement d'un contact**, parce
       que l'index est aussi le doigt qui *fait* le pincement primaire : il
       parcourt un demi-palme en se refermant, sans que la main ait bougé d'un
       millimètre. Mesuré de bout en bout, main parfaitement immobile, un
       pincement textbook marquait 39,4 px contre un `dragSlopPx` de 26 — et
       `dragSlopPx` latche DRAG sans retour : `intent:click` était
       **inatteignable** pour une vraie main.

       C'est exactement le défaut que la Slice 03 a corrigé une couche plus
       haut, avec les mêmes mots : elle ancre l'identité sur le **centre de la
       paume** « parce que l'index parcourt plusieurs paumes pendant un
       pincement, et qu'une main qui pince se lirait comme une main qui saute ».
       Ici elle se lisait comme une main qui glisse. Même repère, même raison.

       `palmX`/`palmY` sont donc le centre de la paume en pixels de la fenêtre,
       fournis par l'appelant comme le sont déjà `x`/`y` et l'ancre — le moteur
       ne connaît ni la surimpression ni `toScreen`. Absents, il retombe sur
       `x`/`y`, c'est-à-dire sur le comportement d'avant : un déplacement
       **sur-évalué**, donc un faux `drag` et jamais un faux `click`. Le sens
       de l'erreur reste le bon, et le seul appelant du dépôt les fournit. */
    const handAt=sample=>{
      const px=Number(sample.palmX),py=Number(sample.palmY);
      return Number.isFinite(px)&&Number.isFinite(py)
        ?{x:px,y:py}:{x:sample.x,y:sample.y};
    };

    const event=(phase,sample,x,y,progress)=>({
      channel,phase,handTrackId:sample.handTrackId,
      x,y,t:sample.now,progress:clamp(progress,0,1),confidence:sample.confidence,
      intent:held?held.intent:PINCH_INTENT.UNDECIDED,
      travelPx:held?held.travelPx:0,durationMs:held?held.durationMs:0,
    });

    return {
      channel,
      state:()=>contact.state(),
      intent:()=>held?held.intent:PINCH_INTENT.UNDECIDED,
      /* `sample` : `{handTrackId, ratio, other, quality, x, y, palmX, palmY,
         anchorX, anchorY, stillness, now, confidence}` — `confidence` est
         calculée par le moteur, qui seul voit les deux canaux et la fermeture
         de la main. Trois couples de coordonnées, trois questions : où la main
         **vise** (`anchorX`/`anchorY`, figé), où le pointeur **est**
         (`x`/`y`, le bout de l'index filtré), et où la **main** est
         (`palmX`/`palmY`, le centre de la paume) — seul le troisième mesure un
         déplacement, voir `handAt`. */
      update(sample){
        const out=[];
        /* Un contact ne **commence** ni sur une main que le suivi ne croit pas
           (décision 7 : `usableQuality`), ni sur une fermeture de main entière.
           Un contact **en cours**, lui, ne s'interrompt pas parce que la note
           baisse : une main qui sort à moitié du cadre au milieu d'un
           glissement doit pouvoir le finir. Il ne se termine que par un
           relâchement ou par la perte de la main. */
        const trusted=sample.confidence>=o.pinchConfidenceMin&&usableQuality(sample.quality,overrides);
        const step=contact.update(held||trusted?sample.ratio:null);
        const at=handAt(sample);
        if(held){
          held.durationMs=Math.max(0,sample.now-held.at);
          held.travelPx=Math.max(held.travelPx,Math.hypot(at.x-held.x,at.y-held.y));
          /* Le glissement se décide **en cours de route** : dès que la main a
             franchi `dragSlopPx`, l'intention est prise et ne revient pas —
             une main qui repart d'où elle est venue a tout de même glissé. Le
             clic, lui, ne se décide qu'au relâchement : on ne peut pas savoir
             qu'un contact sera court avant qu'il finisse. */
          if(held.travelPx>o.dragSlopPx)held.intent=PINCH_INTENT.DRAG;
        }
        if(step.state==='pressed'&&step.entered&&!held){
          held={at:sample.now,x:at.x,y:at.y,travelPx:0,durationMs:0,
            intent:PINCH_INTENT.UNDECIDED};
          lastX=sample.anchorX;lastY=sample.anchorY;
          out.push(event(PINCH_PHASE.DOWN,sample,sample.anchorX,sample.anchorY,1));
        }else if(step.state==='pressed'&&held){
          if(sample.x!==lastX||sample.y!==lastY){
            lastX=sample.x;lastY=sample.y;
            out.push(event(PINCH_PHASE.MOVE,sample,sample.x,sample.y,1));
          }
        }else if(held){
          /* Relâchement. Une intention restée indécise se tranche ici, sur les
             trois témoins de la Slice 03 — durée, déplacement, et
             l'**immobilité publiée**, jamais une dérivée recalculée : la
             dérivée interne du filtre lit 40 px/s sur une main immobile, et
             aucun clic ne se distinguerait d'un glissement. */
          if(held.intent===PINCH_INTENT.UNDECIDED)
            held.intent=(held.durationMs<=o.clickMaxMs&&held.travelPx<=o.clickSlopPx
              &&Number(sample.stillness)>=o.clickStillnessMin)
              ?PINCH_INTENT.CLICK:PINCH_INTENT.DRAG;
          out.push(event(PINCH_PHASE.UP,sample,sample.x,sample.y,0));
          held=null;lastX=null;lastY=null;
        }
        if(!held&&step.state==='pinching'&&step.progress!==lastProgress)
          out.push(event(PINCH_PHASE.APPROACH,sample,sample.anchorX,sample.anchorY,step.progress));
        lastProgress=step.state==='pinching'?step.progress:null;
        return out;
      },
      /* Main perdue, veille, arrêt : ce qui était tenu doit être rendu. Seul
         `cancel` n'a rien à viser — le contrat l'écrit, parce qu'au moment où
         l'on annule on ne sait plus où est la main. */
      cancel(handTrackId,now){
        if(!held)return null;
        const at=held;
        held=null;lastProgress=null;lastX=null;lastY=null;contact.reset();
        return {channel,phase:PINCH_PHASE.CANCEL,handTrackId,x:null,y:null,t:now,
          progress:0,confidence:0,intent:at.intent,travelPx:at.travelPx,durationMs:at.durationMs};
      },
      reset(){contact.reset();held=null;lastProgress=null;lastX=null;lastY=null},
      /* Réglage **à chaud** (Slice 07 : `settings.sensitivity` divise les deux
         tolérances de déplacement). Les seuils sont relus à chaque image, donc
         les remplacer en place suffit et ne perd aucun contact en cours — et
         `options()` refait passer tous les invariants de paire, si bien qu'un
         réglage dangereux se refuse là où il arrive plutôt qu'à la prochaine
         construction. */
      configure(next){Object.assign(o,options(next))},
    };
  }

  /* Les deux canaux de toutes les mains. Chaque main a les siens : deux mains
     pincent indépendamment (décision 12), et un canal ne sait rien de l'autre
     main. */
  function createPinchIntentEngine(overrides,deps){
    const o=options(overrides);
    /* Les surcharges **vivantes** : un réglage changé en cours de session doit
       aussi atteindre les mains qui apparaîtront ensuite, pas seulement celles
       qui sont déjà là. Une main neuve construite sur les surcharges d'origine
       aurait travaillé avec des seuils que l'écran n'affiche plus. */
    let live={...(overrides||{})};
    /* **Le profil de calibration entre par ici** (Slice 08, décision 28 :
       valeurs internes par main). Une fonction, pas une table : le bloc pur est
       chargé seul par les tests node et ne peut pas lire le contrat, donc il ne
       sait pas ce qu'est un profil — il sait seulement demander « quelles
       surcharges pour cette main, sur ce canal ». Absente, rien ne change :
       c'est exactement le moteur d'avant.

       Les deux canaux partagent les noms `pressRatio`/`releaseRatio` mais sont
       deux instances : donner au secondaire les seuils mesurés sur le majeur,
       c'est lui passer d'autres valeurs sous les mêmes noms, sans clé
       nouvelle. */
    const handOverrides=deps&&typeof deps.handOverrides==='function'?deps.handOverrides:null;
    const forHand=(handedness,channel)=>{
      if(!handOverrides)return live;
      const extra=handOverrides(handedness,channel);
      return extra&&typeof extra==='object'?{...live,...extra}:live;
    };
    const hands=new Map();
    const make=handedness=>({at:null,handedness:handedness||'unknown',channels:{
      primary:createPinchChannel(PINCH_CHANNEL.PRIMARY,forHand(handedness,PINCH_CHANNEL.PRIMARY)),
      secondary:createPinchChannel(PINCH_CHANNEL.SECONDARY,forHand(handedness,PINCH_CHANNEL.SECONDARY))}});
    return {
      /* `{hands:[{handTrackId, landmarks, x, y, palmX, palmY, anchorX,
         anchorY, stillness, quality}], now, aspect}` — tous en **pixels de la
         fenêtre** : `x`/`y` la position filtrée de la Slice 03,
         `anchorX`/`anchorY` le point de visée figé, `palmX`/`palmY` le centre
         de la paume. Les trois, parce qu'ils ne servent pas à la même chose. */
      update(frame){
        const f=frame||{};
        const now=Number(f.now);
        if(!Number.isFinite(now))
          throw Object.assign(new Error('intention de pincement : horodatage inutilisable'),{code:'tracking_failed'});
        const k=Number(f.aspect)>0?Number(f.aspect):1;
        const list=Array.isArray(f.hands)?f.hands:[];
        const events=[],contacts=[];
        // Purge avant lecture, même horloge d'identité que partout ailleurs.
        for(const [id,state] of [...hands]){
          if(state.at!==null&&now-state.at<=o.lostGraceMs)continue;
          for(const channel of PINCH_CHANNELS){
            const cancelled=state.channels[channel].cancel(id,now);
            if(cancelled)events.push(cancelled);
          }
          hands.delete(id);
        }
        for(const hand of list){
          const id=hand&&hand.handTrackId;
          if(id===undefined||id===null)continue;
          const ratios={};
          for(const channel of PINCH_CHANNELS)ratios[channel]=pinchRatioFor(hand.landmarks,k,channel);
          /* Image malformée : sautée, jamais lue comme un relâchement — et
             sautée **par canal**, pas par image. Les deux canaux ne lisent pas
             le même bout de doigt (`USED_LANDMARKS` veut `INDEX_TIP`,
             `SECONDARY_LANDMARKS` veut `MIDDLE_TIP`) : n'en perdre qu'un
             laissait l'autre lisible, donc l'image n'était pas sautée, donc le
             canal aveugle recevait `null` — et `null` fait retomber
             `createContactState` à `open`, ce qui **émettait un `up`**.
             Mesuré : pendant un clic droit, perdre `MIDDLE_TIP` une seule
             image donnait `secondary:up intent=click` ; or c'est le point le
             plus probablement occulté d'un pincement pouce-majeur, le pouce
             étant devant. Le consommateur lâchait l'objet et recevait un clic
             droit sur une main qui n'avait rien relâché.
             Le test d'origine ne pouvait pas le voir : il coupait le doigt du
             canal **au repos** pendant que l'autre tenait. */
          if(ratios.primary===null&&ratios.secondary===null)continue;
          const key=String(id);
          const handedness=String((hand&&hand.handedness)||'unknown');
          if(!hands.has(key))hands.set(key,make(handedness));
          const state=hands.get(key);
          /* La latéralité est un **indice** qui peut changer en cours de piste
             (architecture §2 : le vote se déplace). Quand elle change, les
             seuils calibrés de cette main changent avec elle — sinon la main
             garderait ceux de la latéralité qu'on lui avait d'abord prêtée,
             jusqu'à ce qu'elle disparaisse. */
          if(handOverrides&&state.handedness!==handedness){
            state.handedness=handedness;
            for(const channel of PINCH_CHANNELS)
              state.channels[channel].configure(forHand(handedness,channel));
          }
          state.at=now;
          /* Fermeture de main entière, lue une fois par main sur l'extension
             des doigts. `null` — pas un seul bout de doigt lisible — vaut 1,
             la lecture prudente : rien ne dit que la main est ouverte, donc
             rien ne commence. Le cas est inatteignable ici (un canal lisible
             implique son bout de doigt), et c'est justement pourquoi le repli
             doit être celui qui échoue du bon côté s'il le devenait. */
          const closed=handClosure(hand.landmarks,k,overrides);
          const open=1-(closed===null?1:closed);
          for(const channel of PINCH_CHANNELS){
            const own=ratios[channel],other=ratios[channel===PINCH_CHANNEL.PRIMARY
              ?PINCH_CHANNEL.SECONDARY:PINCH_CHANNEL.PRIMARY];
            const engine=state.channels[channel];
            if(own===null){
              /* Ce canal-ci ne se lit pas cette image : on ne lui donne rien.
                 Son état, son intention et son contact éventuel traversent
                 l'image intacts — c'est ce que « sautée » veut dire. */
              contacts.push({handTrackId:id,channel,state:engine.state(),
                intent:engine.intent(),ratio:null,confidence:0});
              continue;
            }
            /* La confiance d'un canal est ce qui le **sépare** de l'autre,
               **et** ce qui sépare la main d'un poing. Les deux rapports
               ensemble mettent la première à zéro ; les quatre doigts repliés
               mettent la seconde à zéro. Il fallait les deux : la marge seule
               n'écartait le poing du dépôt que de 0,02 paume, et un vrai poing
               au pouce replié en travers de la paume marquait une confiance de
               **1,0** — un clic droit maximalement sûr sur une main fermée.
               Garantie : quatre doigts à `fingerCurledPalms` ou en deçà
               donnent `open = 0`, donc une confiance **exactement** nulle sur
               les deux canaux, quelles que soient la marge et les distances.
               Elle ne coûte rien à un vrai pincement : il lui reste au moins un
               doigt tendu, donc `open = 1`. */
            const confidence=Number.isFinite(own)&&Number.isFinite(other)
              ?clamp(ramp(other-own,0,o.pinchMarginRatio)*open,0,1):0;
            for(const produced of engine.update({handTrackId:id,ratio:own,other,confidence,
              quality:hand.quality,stillness:hand.stillness,now,
              x:Number(hand.x),y:Number(hand.y),
              palmX:Number(hand.palmX),palmY:Number(hand.palmY),
              anchorX:Number(hand.anchorX===undefined?hand.x:hand.anchorX),
              anchorY:Number(hand.anchorY===undefined?hand.y:hand.anchorY)}))events.push(produced);
            contacts.push({handTrackId:id,channel,state:engine.state(),
              intent:engine.intent(),ratio:own,confidence});
          }
        }
        return {events,contacts};
      },
      /* Arrêt volontaire (veille, extinction, perte du suivi) : tout contact en
         cours est **annulé**, jamais relâché — un `up` déclencherait l'action
         que l'arrêt vient justement d'interrompre. */
      cancelAll(now){
        const events=[];
        for(const [id,state] of hands)
          for(const channel of PINCH_CHANNELS){
            const cancelled=state.channels[channel].cancel(id,Number(now)||0);
            if(cancelled)events.push(cancelled);
          }
        hands.clear();
        return events;
      },
      reset(){hands.clear()},
      size(){return hands.size},
      /* Réglage à chaud, propagé aux deux canaux de **chaque main déjà
         suivie** en plus des surcharges vivantes : sans la boucle, la main qui
         est sous la caméra au moment du changement garderait les anciens
         seuils jusqu'à ce qu'elle disparaisse — le réglage aurait l'air
         appliqué à l'écran et pas dans la main. */
      configure(partial){
        live={...live,...(partial||{})};
        Object.assign(o,options(live));
        for(const state of hands.values())
          for(const channel of PINCH_CHANNELS)
            state.channels[channel].configure(forHand(state.handedness,channel));
        return {...live};
      },
      /* Ce que **chaque main** applique vraiment, relisible sans reconfigurer.
         Règle de la Slice 07 : un réglage qu'on ne peut relire que sur l'objet
         qu'on vient d'écrire n'est pas un réglage qu'on peut dire branché — et
         un profil par main l'est encore moins, puisque rien à l'écran ne le
         montre. */
      handOptionsFor(handedness){
        const read={};
        for(const channel of PINCH_CHANNELS){
          const merged=options(forHand(String(handedness||'unknown'),channel));
          read[channel]=Object.freeze({pressRatio:merged.pressRatio,releaseRatio:merged.releaseRatio});
        }
        return Object.freeze(read);
      },
    };
  }

  /* Latéralité annoncée par le traqueur pour une détection : un **indice**,
     jamais une identité (architecture §2). La chaîne vide vaut « rien dit ». */
  function handLabel(result,index){
    const groups=(result&&(result.handedness||result.handednesses))||[];
    const first=Array.isArray(groups[index])?groups[index][0]:null;
    return first&&first.categoryName?String(first.categoryName).toLowerCase():'';
  }
  function handScore(result,index){
    const groups=(result&&(result.handedness||result.handednesses))||[];
    const first=Array.isArray(groups[index])?groups[index][0]:null;
    const score=Number(first&&first.score);
    // Absence = défaut (règle du contrat) : un traqueur qui ne note pas sa
    // latéralité n'est pas un traqueur qui doute de la sienne.
    return Number.isFinite(score)?clamp(score,0,1):1;
  }

  /* Qualité de suivi, 0..1, telle que la nomme le contrat (`HandFrame.quality`,
     §1) : 0 = main devinée, 1 = main franche. Quatre témoins, tous lisibles
     sur l'image ou sur la piste :

     - **l'échelle** : une paume minuscule ou dégénérée ôte son sens à tout ce
       qui se mesure en paumes (pincement, posture de réveil) ;
     - **le cadrage** : le point utile le plus proche d'un bord. Une main qui
       sort du cadre rend des points extrapolés, et rien dans le résultat du
       traqueur ne le dit. La bande est étroite (4 %) **exprès** : la marge de
       `toScreen` (12 %) existe pour qu'on puisse viser le bord de l'écran, et
       une qualité qui s'effondrerait là endormirait une session en plein
       usage — une panne pire que celle qu'elle corrige ;
     - **la complétude** : les 21 points, pas seulement les quatre qu'on lit.
       Un traqueur qui n'en rend qu'une poignée a deviné le reste ;
     - **la continuité**, que seule la piste connaît : une main qui vient
       d'apparaître, ou qui revient après un trou, est une main dont on
       *suppose* que c'est la même. C'est exactement ce que « devinée » veut
       dire.

     C'est le **minimum** des quatre, pas leur moyenne : une moyenne laisse
     trois bons chiffres cacher celui qui dit que la main sort du cadre, et
     c'est précisément celui-là qu'il fallait lire.

     Ce qui n'y est **pas** : le score de latéralité du traqueur. Il répond à
     « suis-je sûr que c'est une main *gauche* », pas à « suis-je sûr que c'est
     une main ». Une main vue de profil a une latéralité ambiguë et des points
     parfaits ; l'y mêler ferait baisser la confiance pour une raison qui n'a
     rien à voir avec elle. */
  function handQuality(landmarks,aspect,continuity,overrides){
    const o=options(overrides);
    if(!usableLandmarks(landmarks))return 0;
    const k=Number(aspect)>0?Number(aspect):1;
    const scale=ramp(distance(landmarks[LM.WRIST],landmarks[LM.MIDDLE_MCP],k),o.qualityPalmMin/2,o.qualityPalmMin);
    let edge=1;
    for(const at of USED_LANDMARKS){
      const point=landmarks[at];
      edge=Math.min(edge,ramp(Math.min(point.x,1-point.x,point.y,1-point.y),0,o.qualityEdge));
    }
    let finite=0;
    for(const point of landmarks)if(usablePoint(point))finite+=1;
    const complete=ramp(finite/Math.max(1,landmarks.length),o.qualityComplete,1);
    return clamp(Math.min(scale,edge,complete,clamp(Number(continuity)||0,0,1)),0,1);
  }
  /* « Cette main compte-t-elle ? » — **une** définition, partagée par le
     minuteur de la décision 7, le guetteur de la veille (`trustedHand`), la
     pastille et la surimpression. La veille en avait longtemps une seconde,
     plus large, et les deux se répondaient : un C tenu par une main que
     l'interaction refuse réveillait quand même, puis se rendormait 30 s plus
     tard, sans fin. Miroir de `JarvisBarehandsContracts.isUsableQuality` (le
     bloc pur est chargé seul par les tests node) ; le test de parité refuse la
     dérive. */
  const usableQuality=(quality,overrides)=>{
    const value=Number(quality);
    return Number.isFinite(value)&&value>=options(overrides).qualityFloor;
  };

  /* ------------------------------------------------------------------
     Cible sémantique (architecture §6, décisions 3, 8, 9, 16, 23, 24).

     `document.elementFromPoint` répond à « quel élément occupe ce pixel ». La
     question de cette Slice en est une autre : « que veut saisir cette
     main ? ». Elle se résout sur la **géométrie sémantique** des objets de
     Jarvis — leur cadre, leur type, leur actionnabilité, leurs zones — et
     l'élément sous le doigt n'en est qu'un indice parmi d'autres (il sert de
     départage « celui du dessus », voir le module d'aperçu).

     Tout est en **pixels de la fenêtre**. La scène, elle, vit en unités
     (±160 × ±90) : les deux espaces ne se rencontrent jamais ici, c'est
     `getBoundingClientRect` qui fait la conversion une fois, à la collecte.

     Le bloc pur ne peut pas lire le contrat (les tests node le chargent seul).
     Il ne **réinvente** donc pas la priorité coin > bord > corps : elle lui est
     passée (`pickRegion`), et une seconde règle ici aurait divergé en silence
     de celle que la Slice 06 lira. */

  const TARGET_REGION=Object.freeze({BODY:'body',EDGE:'edge',CORNER:'corner'});
  /* Miroir de `JarvisBarehandsContracts.EDGE`/`CORNER`, pour la même raison
     que `STATE` est celui de `LIFECYCLE` : un test de parité refuse la dérive. */
  const TARGET_SIDES=Object.freeze({HORIZONTAL:Object.freeze(['left','right']),
    VERTICAL:Object.freeze(['top','bottom'])});

  /* Une coordonnée **est un nombre**, et ce n'est pas la même question que
     « se convertit en nombre ». `Number.isFinite(Number(v))` refusait bien
     `NaN`, `undefined` et `'abc'`, mais laissait passer `null`, `''`, `[]` et
     `false`, qui valent tous **0** : une main sans position visait alors le
     coin supérieur gauche de l'écran, où il y a toujours quelque chose à
     saisir. C'est la classe de défaut que le contrat dit déjà corrigée pour
     les événements de pincement — « sans coordonnées, un clic partait en
     (0,0) » — et elle vivait encore ici. */
  const finiteCoord=value=>typeof value==='number'&&Number.isFinite(value);

  const finiteRect=value=>{
    const r=value&&typeof value==='object'?value:null;
    if(!r)return null;
    const x=Number(r.x),y=Number(r.y),w=Number(r.w),h=Number(r.h);
    if(![x,y,w,h].every(Number.isFinite)||w<=0||h<=0)return null;
    return {x,y,w,h};
  };

  /* Épaisseur de la bande d'un bord, en pixels de la fenêtre. Deux bornes, et
     les deux comptent : une taille lisible à l'écran (`targetZonePx`, ou
     `targetZoneHoldPx` quand la zone est déjà tenue) et une fraction du petit
     côté, pour qu'une capsule de 24 px de haut garde un corps. Sans la
     seconde, les deux bandes opposées se rejoignaient et la décision 8
     devenait inatteignable sur l'objet le plus courant.

     **Le plafond ne s'applique qu'à la bande large, et la bande d'entrée s'en
     déduit.** Appliqué aux deux indépendamment, il rendait le même nombre dès
     que `0,3 × petit côté <= targetZonePx`, c'est-à-dire sur tout objet de
     moins de 46,7 px : une capsule (24 à 42 px) et une fenêtre compacte
     (28 px) avaient une hystérésis **nulle**, et l'aperçu clignotait entre le
     bord et le corps sur un demi-pixel de tremblement — exactement le symptôme
     que la paire existe pour empêcher. L'hystérésis ne survivait que sur les
     grands objets, là où le clignotement est le moins gênant.

     C'est bien la bande **large** qui doit tenir dans la fraction : c'est elle
     qui décide du corps qui reste quand la zone est tenue, donc la garantie
     « au moins 40 % de corps sur chaque axe » est celle d'avant, au pixel
     près. La bande d'entrée garde le rapport des deux réglages
     (`targetZonePx / targetZoneHoldPx`, 14/20 par défaut) : l'hystérésis
     devient proportionnelle au lieu de disparaître, et les deux nombres
     continuent de se régler ensemble plutôt que de se croiser. Réglés égaux,
     elle vaut zéro — mais parce qu'on l'a demandé, pas parce que l'objet est
     petit. */
  function bandFor(bounds,o,holding){
    const rect=finiteRect(bounds);
    if(!rect)return 0;
    const hold=Math.min(o.targetZoneHoldPx,Math.min(rect.w,rect.h)*o.targetZoneMaxRatio);
    if(holding)return hold;
    /* `targetZoneHoldPx` nul (les deux réglages à zéro : plus de zones du tout)
       ne divise pas — il n'y a pas de bande à réduire. */
    return o.targetZoneHoldPx>0?hold*(o.targetZonePx/o.targetZoneHoldPx):0;
  }
  const targetBand=(bounds,overrides,holding)=>bandFor(bounds,options(overrides),holding);

  /* Quelle **partie** d'un cadre un point désigne, et à quelle distance.

     Dedans : les côtés dont on est à moins de `band` — au plus un par axe,
     le plus proche, sinon un point au centre d'un objet minuscule tiendrait
     « gauche » et « droite » à la fois. Dehors : les côtés **franchis**, ce qui
     donne naturellement le bord qu'on approche, et le coin quand on approche
     en diagonale. Zéro côté = corps.

     `distancePx` est la distance du point au rectangle (0 dedans) : c'est ce
     que `pickRegion` lit en troisième critère, et ce que la résolution entre
     objets lit en premier. */
  function regionAt(bounds,point,band){
    const rect=finiteRect(bounds);
    if(!rect)return null;
    const x=point&&point.x,y=point&&point.y;
    if(!finiteCoord(x)||!finiteCoord(y))return null;
    const x1=rect.x+rect.w,y1=rect.y+rect.h;
    const left=x-rect.x,right=x1-x,top=y-rect.y,bottom=y1-y;
    const reach=Math.max(0,Number(band)||0);
    const outside=left<0||right<0||top<0||bottom<0;
    const distancePx=Math.hypot(Math.max(rect.x-x,0,x-x1),Math.max(rect.y-y,0,y-y1));
    let horizontal=null,vertical=null;
    if(outside){
      if(left<0)horizontal='left';else if(right<0)horizontal='right';
      if(top<0)vertical='top';else if(bottom<0)vertical='bottom';
    }else if(reach>0){
      if(Math.min(left,right)<=reach)horizontal=left<=right?'left':'right';
      if(Math.min(top,bottom)<=reach)vertical=top<=bottom?'top':'bottom';
    }
    return {horizontal,vertical,distancePx,outside};
  }

  /* Les candidates qu'un objet offre à un point : son corps, plus — s'il a des
     zones (décision D3 : capsule et fenêtre seulement) — chaque côté retenu et
     le coin quand il y en a deux. Toutes à la même distance, ce qui est
     exactement le cas de **recouvrement** que `pickRegion` tranche
     (coin > bord > corps). */
  function targetRegionsOf(object,point,band){
    const geometry=regionAt(object.boundsPx,point,object.zoned?band:0);
    if(!geometry)return null;
    const shared={objectId:object.objectId,kind:object.kind,
      /* Renvoi opaque vers la candidate d'origine. La géométrie n'a rien à
         faire de l'élément du DOM — aucun n'en traverse ce module (contrat
         § 6) — mais l'appelant doit pouvoir retrouver ce qu'il a collecté sans
         réapparier sur des coordonnées, ce qui échouerait dès qu'une cible est
         figée et que la main est partie ailleurs. */
      ref:object.ref===undefined?null:object.ref,
      representation:object.representation,actionable:object.actionable!==false,
      boundsPx:object.boundsPx,distancePx:geometry.distancePx};
    const regions=[{...shared,region:TARGET_REGION.BODY,zone:null}];
    if(object.zoned){
      const {horizontal,vertical}=geometry;
      if(horizontal)regions.push({...shared,region:TARGET_REGION.EDGE,zone:horizontal});
      if(vertical)regions.push({...shared,region:TARGET_REGION.EDGE,zone:vertical});
      if(horizontal&&vertical)
        regions.push({...shared,region:TARGET_REGION.CORNER,zone:`${vertical}_${horizontal}`});
    }
    return {distancePx:geometry.distancePx,actionable:shared.actionable,regions};
  }

  /* Le résolveur. Une entrée par main **et par canal** : la décision 21 fait du
     clic droit un canal, donc la même main peut viser en bleu d'un doigt et en
     rouge de l'autre, et les deux ne se latchent pas ensemble.

     Deux étapes, et l'ordre n'est pas indifférent :

     1. **quel objet** — parmi les **actionnables** (décision 3 : ce qu'on ne
        peut pas actionner n'est pas une cible, donc rien à dessiner et rien à
        publier), le plus proche (`distancePx`), et à égalité le premier cité
        (le module de collecte cite celui du dessus
        en tête). La priorité de région ne participe **pas** à ce choix : elle
        départage un *recouvrement*, et l'appliquer entre objets ferait gagner
        le coin d'un objet à 20 px sur le bord de celui qu'on touche.
     2. **quelle partie** — `pickRegion` sur les candidates de cet objet, qui
        sont toutes à la même distance : coin > bord > corps, la règle du
        contrat, appliquée là où elle veut dire quelque chose.

     L'hystérésis est celle d'un contact (`pressRatio`/`releaseRatio`) : une
     zone déjà tenue se juge sur la bande large, les autres sur la bande
     étroite. Sans elle, un tremblement d'un pixel au bord de la bande fait
     clignoter l'aperçu entre le coin et tout le cadre. */
  function createTargetResolver(overrides){
    const o=options(overrides);
    const pick=overrides&&overrides.pickRegion;
    if(typeof pick!=='function')
      throw new RangeError('createTargetResolver exige `pickRegion` : la priorité coin > bord > corps appartient au contrat (JarvisBarehandsContracts.pickRegion), et une seconde règle ici divergerait en silence');
    const held=new Map();
    const keyOf=(id,channel)=>`${String(id)}|${String(channel)}`;
    /* L'assistance des réglages (contrat §9, bornée 0..1, défaut **0,5**)
       multiplie la portée. Le facteur 2 est ce qui fait du défaut des réglages
       le défaut du moteur : `assistance` 0,5 rend exactement `targetAssistPx`,
       0 coupe l'assistance et 1 la double. Sans lui, brancher le réglage à la
       Slice 07 aurait **divisé la portée par deux** sans que personne n'ait
       rien changé — une régression invisible au câblage. */
    const assistOf=value=>{
      if(value===undefined||value===null)return 1;
      const n=Number(value);
      return Number.isFinite(n)?clamp(n,0,1)*2:1;
    };
    return {
      /* Le rayon que la collecte doit balayer pour cette assistance : le
         module de page ne redérive pas ce nombre, sinon il collecterait un
         disque et le résolveur en jugerait un autre. */
      reach(assistance){return o.targetAssistPx*assistOf(assistance)},
      /* `{now, candidates:[{objectId, kind, representation, zoned, actionable,
         boundsPx}], hands:[{handTrackId, channel, state, x, y, assistance}]}`.
         `state` est celui que publie `createPinchChannel` : `open`,
         `pinching` (approche : décision 3, c'est **là** que l'aperçu vit) ou
         `pressed` (contact : le descripteur est figé). */
      update(frame){
        const f=frame||{};
        const now=Number(f.now);
        if(!Number.isFinite(now))
          throw Object.assign(new Error('résolution de cible : horodatage inutilisable'),{code:'tracking_failed'});
        const candidates=Array.isArray(f.candidates)?f.candidates:[];
        const hands=Array.isArray(f.hands)?f.hands:[];
        /* Même horloge d'identité que partout ailleurs : ce qu'une main tenait
           meurt avec elle, et la grâce se compte contre l'observation. */
        for(const [k,entry] of [...held])if(now-entry.at>o.lostGraceMs)held.delete(k);
        const out=[];
        for(const hand of hands){
          const id=hand&&hand.handTrackId;
          if(id===undefined||id===null)continue;
          const channel=String((hand&&hand.channel)||'primary');
          const k=keyOf(id,channel);
          const state=String((hand&&hand.state)||'open');
          /* **Décision 3.** Hors intention, il n'y a pas de cible — donc rien
             à dessiner, et pas un curseur qui reste. C'est ici que la règle est
             tenue, une fois, plutôt que dans chaque dessin. */
          if(state!=='pinching'&&state!=='pressed'){held.delete(k);continue}
          const previous=held.get(k);
          /* Dynamique jusqu'à la descente, stable ensuite : sous contact, le
             descripteur ne bouge plus, quoi que fasse la main. C'est ce que la
             Slice 06 latche (décision 13). */
          if(state==='pressed'&&previous&&previous.locked){
            previous.at=now;out.push(previous.target);continue;
          }
          /* Le point n'est pas validé ici : `regionAt` le fait, une fois, pour
             tout le monde — et une main sans position ne rend alors aucune
             candidate, donc elle **oublie** ce qu'elle tenait par le chemin
             normal (`if(!best)`). Un second contrôle au-dessus existait ; il
             rendait exactement le même résultat, et aucun test ne pouvait
             l'en distinguer. Une ligne qu'aucun test ne peut atteindre n'est
             pas une ceinture, c'est une ligne de moins à lire. */
          const point={x:hand.x,y:hand.y};
          const reach=o.targetAssistPx*assistOf(hand.assistance);
          let best=null,bestBand=0;
          for(const object of candidates){
            if(!object)continue;
            /* L'hystérésis suit un **objet identifié**. Sans ce garde-fou,
               deux candidates sans identité (les contrôles du DOM le sont
               toutes) auraient partagé la même mémoire — inoffensif tant
               qu'elles n'ont pas de zones, faux le jour où elles en auront. */
            const oid=object.objectId===undefined||object.objectId===null?null:String(object.objectId);
            const holding=!!previous&&!!previous.target&&oid!==null
              &&previous.target.objectId===oid
              &&previous.target.region!==TARGET_REGION.BODY;
            const band=object.zoned?bandFor(object.boundsPx,o,holding):0;
            const found=targetRegionsOf(object,point,band);
            /* **Décision 3, et c'est une porte, pas un classement.** Une
               candidate non actionnable n'appelle aucun retour visuel : le
               contrat le dit en toutes lettres (« c'est une obligation du
               consommateur ») et personne ne la tenait. Un bouton désactivé
               seul sous un doigt qui pince se résolvait à d=0, se publiait à
               la Slice 06 et se dessinait — un cadre bleu et un nom autour
               d'un contrôle qui ne fera rien. Un retour visuel qui promet une
               action impossible est pire que pas de retour du tout.

               Elle est tenue **ici** plutôt que chez l'aperçu parce que
               `targets()` publie ce que rend ce résolveur : filtrer plus bas
               aurait laissé la Slice 06 ouvrir une capture sur un contrôle
               désactivé, à moins qu'elle ne refiltre — donc à moins d'une
               seconde règle, qui divergerait en silence.

               Le classement « actionnable d'abord » de `pickRegion` reste : il
               est du contrat, il garde son sens pour tout autre appelant, et
               ici il ne peut plus rien trancher puisque plus rien de non
               actionnable ne l'atteint. Le résolveur, lui, n'en garde pas une
               copie : le plus proche gagne, un point. */
            if(!found||!found.actionable||found.distancePx>reach)continue;
            if(!best||found.distancePx<best.distancePx){best=found;bestBand=band}
          }
          if(!best){held.delete(k);continue}
          const picked=pick(best.regions);
          if(!picked){held.delete(k);continue}
          const target=Object.freeze({handTrackId:id,channel,
            locked:state==='pressed',bandPx:bestBand,
            objectId:picked.objectId===undefined||picked.objectId===null?null:String(picked.objectId),
            kind:picked.kind,region:picked.region,zone:picked.zone,ref:picked.ref,
            representation:picked.representation,actionable:picked.actionable,
            boundsPx:picked.boundsPx,distancePx:picked.distancePx});
          held.set(k,{at:now,locked:state==='pressed',target});
          out.push(target);
        }
        return out;
      },
      /* Le contact est rendu : la cible figée l'est aussi. */
      release(handTrackId,channel){
        held.delete(keyOf(handTrackId,channel===undefined||channel===null?'primary':channel));
      },
      reset(){held.clear()},
      size(){return held.size},
    };
  }

  /* ------------------------------------------------------------------
     Moteur d'interaction et captures (architecture §7, décisions 8-19, Slice 06).

     Une capture est ce qu'une main **tient**. Elle s'ouvre à la descente du
     pincement sur la cible **figée** que la Slice 05 publie (décision 13 : elle
     est latchée jusqu'au relâchement, sinon un glissement de 30 px changerait
     l'objet au milieu du geste), et elle se ferme sur le relâchement ou sur la
     perte de la main.

     Ce moteur **ne décide pas** ce que deux captures produisent : cette règle
     est `combineCaptures` (contrat § 7, décisions 12 et 14-17), et il la lit —
     y compris `byHand[id].sides`, parce que ce sont les **côtés** qui sont la
     donnée utile : deux mains peuvent tenir le même axe par deux côtés opposés,
     ce qu'une lecture par axes seuls prendrait pour un conflit. Redériver
     `ZONE_SIDES`/`SIDE_AXIS` ici serait exactement la duplication que le
     contrat existe pour éviter. Il ne décide pas non plus la géométrie : les
     décisions 18 et 19 vivent avec `clampBox` et `MIN_SIZE` dans
     `control_center_scene_interact.js`, en **unités de scène**, et c'est là que
     les pixels de la fenêtre sont convertis, une fois, dans `manipulateBox`.

     Le bloc pur ne peut pas lire les contrats (node le charge seul) : les deux
     lui sont donc **injectés**, comme `pickRegion` l'est au résolveur de la
     Slice 05, et il se refuse à la construction plutôt que d'en écrire une
     seconde copie.

     Trois repères, trois rôles, et les confondre est le piège de cette couche :

     - la **paume** (`palmX`/`palmY`) est où la main *est* : c'est elle qui
       mesure un déplacement, donc c'est elle qui déplace un cadre ;
     - le bout de l'index est ce que la main *vise* : c'est le pointeur ;
     - l'ancre figée est ce qu'elle visait **à la descente** : c'est ce que
       portent `approach` et `down`.

     Et la phase dit lequel : un événement `move`/`up` porte la position
     filtrée, un `down` porte l'ancre. */

  /* Ce qu'une capture de corps fait du contenu, décidé sur la **sémantique de
     la cible** et non sur le pixel qu'elle occupe (décision 8). */
  const CONTENT_MODE=Object.freeze({DRAG:'drag',SCROLL:'scroll',SELECT:'select'});
  const CONTENT_MODES=Object.freeze(Object.keys(CONTENT_MODE).map(k=>CONTENT_MODE[k]));
  /* Ce que le mode `select` sait réellement faire, et rien de plus : la sortie
     DOM y donne le focus et appelle `select()`. Sur un `div` il n'y aurait
     personne pour l'entendre — l'outil Sélection doit donc **refuser** cette
     cible-là plutôt que de rendre une main inerte. */
  const SELECTABLE_KINDS=Object.freeze(['field','scene_object']);

  function createInteractionEngine(deps){
    const d=deps&&typeof deps==='object'?deps:{};
    const C=d.contracts;
    const RULES=['combineCaptures','createCapture','createInteractionEvent','SIDE_AXIS','INTERACTION','zoneSides',
      /* Slice 07. La table des outils appartient au contrat (§ 8), comme
         `pickRegion` appartenait au contrat à la Slice 05 : une seconde table
         écrite ici divergerait en silence de celle que la palette dessine et
         que le serveur refuse. */
      'TOOL_DEFAULT','TOOL_CAPABILITY_CONTEXTUAL','toolCapability'];
    if(!C||RULES.some(name=>C[name]===undefined))
      throw new RangeError('createInteractionEngine exige `contracts` (JarvisBarehandsContracts) : les décisions 12 et 14-17 appartiennent à combineCaptures, et une seconde règle ici divergerait en silence de celle que le contrat publie');
    const G=d.geometry;
    const GEOMETRY=['manipulateBox','rebaseManipulation','resizable','sameBox'];
    if(!G||GEOMETRY.some(name=>typeof G[name]!=='function'))
      throw new RangeError('createInteractionEngine exige `geometry` (JarvisSceneInteract) : les décisions 18 et 19 vivent avec clampBox et MIN_SIZE, en unités de scène, et la conversion pixels → unités n’a qu’un seul endroit');
    const world=d.world&&typeof d.world==='object'?d.world:null;
    const dom=d.dom&&typeof d.dom==='object'?d.dom:null;
    const slotOf=typeof d.slotOf==='function'?d.slotOf:()=>null;
    const o=options(d.options);
    const I=C.INTERACTION;

    /* Une capture par main **et par canal** (décision 21 : le clic droit est un
       canal), comme les cibles de la Slice 05. */
    const captures=new Map();
    /* Un plan de manipulation par objet : sa signature, sa boîte de référence,
       les ancres des mains qui le tirent, et la boîte affichée. */
    const plans=new Map();
    /* Le **numéro de l'image** en cours. Il ne mesure pas le temps : il dit
       seulement si un plan a été conduit à l'image *précédente* ou s'il a sauté
       un tour. Un horodatage ne le dirait pas — rien ne garantit le pas entre
       deux images, et `now` est ce que l'appelant veut bien donner. */
    let frameIndex=0;
    let refused=[];
    /* Les mains qui ont **conduit** une manipulation pendant l'image en cours,
       celles qui viennent de relâcher comprises : c'est ce que le chemin de clic
       hérité consulte pour ne pas poser un clic sur l'objet qu'on vient de
       déplacer. Vidé à chaque image, comme tout ce qui décrit un instant. */
    let drove=new Set();

    const keyOf=(id,channel)=>`${String(id)}|${String(channel===undefined||channel===null?PINCH_CHANNEL.PRIMARY:channel)}`;
    const refuse=(entry,reason)=>{refused.push({handTrackId:entry?entry.handTrackId:null,
      channel:entry?entry.channel:null,objectId:entry?entry.objectId:null,reason})};

    function publish(out,type,entry,point,extra){
      const source=extra&&typeof extra==='object'?extra:{};
      /* Un refus codé dans une boucle d'images vaut la fin de la session (leçon
         des Slices 02 et 04) : une interaction mal formée se dit et se saute,
         elle n'arrête pas le suivi. */
      let event=null;
      try{
        event=C.createInteractionEvent({type,handTrackId:entry.handTrackId,
          slot:slotOf(entry.handTrackId),objectId:entry.objectId,
          x:point.x,y:point.y,dx:source.dx,dy:source.dy,
          /* L'outil actif voyage avec l'événement (contrat § 7) : un
             consommateur qui reçoit un `scroll` doit pouvoir savoir s'il vient
             d'un contenu défilant ou de l'outil Main. Le contrat **refuse** un
             outil inconnu ici, contrairement à `normalizeTool` : un événement
             n'est pas un schéma stocké. */
          channel:entry.channel,tool,axes:source.axes,t:source.t});
      }catch(error){
        refuse(entry,(error&&error.code)||'barehands_interaction_invalid');
        return null;
      }
      out.push(event);
      if(dom&&typeof dom.emit==='function'){
        try{dom.emit(event,{target:entry.target,cancelled:!!source.cancelled,mode:source.mode})}
        catch(error){refuse(entry,'dom_emit_failed')}
      }
      return event;
    }

    /* Ce que le corps d'une cible accepte. Une étoile de la scène est à part, et
       ce n'est pas un détail de confort : la page de scène lit un glissement de
       pointeur sur `.sc-node` comme un **déplacement de cadre**, donc émettre la
       séquence de pointeur sur le corps d'une capsule ferait exactement ce que
       la décision 8 interdit. Son corps se **sélectionne**, il ne se traîne
       pas. */
    function contentMode(target){
      if(!target)return CONTENT_MODE.DRAG;
      if(target.kind==='scene_object')return CONTENT_MODE.SELECT;
      if(target.kind==='field')return CONTENT_MODE.SELECT;
      if(dom&&typeof dom.scrollable==='function'&&dom.scrollable(target))return CONTENT_MODE.SCROLL;
      return CONTENT_MODE.DRAG;
    }

    /* **Décision 25 : l'outil, distinct des réglages.** Un outil dit ce que la
       main veut dire ; un réglage dit comment Bare Hands se comporte. Le
       premier se change en pleine session et ne se calibre pas, le second se
       persiste et se règle — deux concepts, deux surfaces.

       La capacité d'un outil **est** un mode de contenu (contrat § 8), donc il
       n'y a aucune table de correspondance à tenir ici : la question est
       seulement « ce moteur sert-il cette capacité ? » puis « cette cible-ci
       peut-elle l'honorer ? ». L'outil par défaut n'exige rien et laisse le
       moteur décider de ce qu'il y a sous la main — c'est ce que « le mode par
       défaut reste contextuel » veut dire, et c'est pour ça que `pointer` ne
       passe par aucune des portes ci-dessous.

       Ce que l'outil ne touche pas : les **zones** de manipulation (un bord
       reste un bord, décisions 9 à 11) et le corps d'une étoile déplaçable
       seulement (décision D3 : c'est sa seule prise, donc un cadre et non du
       contenu — la lui prendre la rendrait immobile sous tout autre outil). */
    let tool=C.TOOL_DEFAULT;
    const selectable=target=>!!target&&SELECTABLE_KINDS.includes(target.kind);
    function toolPlan(entry){
      const capability=C.toolCapability(tool);
      if(capability===C.TOOL_CAPABILITY_CONTEXTUAL)return {mode:contentMode(entry.target)};
      /* Un outil déclaré sans moteur ne prend rien, nulle part : le réglage le
         refuse déjà et la palette le grise, mais ce moteur est **injectable**
         et ne suppose pas son appelant (même raison que `target_not_actionable`
         à la Slice 06). Le refuser partout vaut mieux qu'une main qui se pose
         et ne fait rien. */
      if(!CONTENT_MODES.includes(capability))return {reason:'tool_not_installed'};
      if(entry.capture.region!==TARGET_REGION.BODY||movesByBody(entry))
        return {mode:contentMode(entry.target)};
      if(capability===CONTENT_MODE.SCROLL
        &&!(dom&&typeof dom.scrollable==='function'&&dom.scrollable(entry.target)))
        return {reason:'tool_target_unsupported'};
      if(capability===CONTENT_MODE.SELECT&&!selectable(entry.target))
        return {reason:'tool_target_unsupported'};
      return {mode:capability};
    }

    /* Une étoile sans zones (décision D3 : `point` et `signal`) n'a que son
       corps pour être déplacée — « déplaçables seulement » ne peut pas vouloir
       dire « pas déplaçables ». Une capsule ou une fenêtre, elle, garde son
       corps pour le contenu (décision 8) et ses bords pour le cadre. */
    /* Et les trois conditions comptent : **une étoile de la scène** (un bouton
       du DOM n'a pas de cadre à déplacer), **identifiée** (sans `objectId` il
       n'y a pas d'objet à bouger), et d'une représentation qui ne se
       redimensionne pas. Sans les deux premières, le corps de n'importe quel
       contrôle du DOM aurait été pris pour une étoile — donc jamais traîné, et
       jamais cliqué non plus. */
    const movesByBody=entry=>entry.capture.region===TARGET_REGION.BODY
      &&entry.objectId!==null&&entry.objectId!==undefined
      &&!!entry.target&&entry.target.kind==='scene_object'
      &&!G.resizable(entry.target.representation);
    /* Ce qui **peut** entrer dans un couple de captures : le canal primaire sur
       un objet identifié. Le clic droit n'en est pas — c'est une **intention**,
       pas une partie du cadre (décision 23) — et un élément sans identité de
       scène ne se couple à rien (décision 12, que le contrat redit lui-même
       sous `object_unidentified`).

       Le corps **y entre**, et c'est voulu : c'est `combineCaptures` qui doit
       dire que corps + zone déplace (décisions 10 et 14) et que corps + corps ne
       produit rien (décision 8). Le filtrer ici rendrait ces deux règles
       inatteignables et les réécrirait en silence. */
    const frameCandidate=entry=>entry.channel===PINCH_CHANNEL.PRIMARY
      &&entry.objectId!==null&&entry.objectId!==undefined;

    function openCapture(handTrackId,channel,target,now){
      /* **Décision 3, en profondeur.** Le résolveur de la Slice 05 est la porte :
         il ne publie plus rien de non actionnable, donc ce refus est
         inatteignable par le chemin réel. Il est là parce que ce moteur est
         **injectable** — il se construit avec ses contrats et sa géométrie, et
         rien ne garantit que son prochain appelant sera ce résolveur-là. Sans
         lui, une cible désactivée ouvrirait une capture et produirait un vrai
         `pointerdown` sur un contrôle qui ne fera rien.
         L'**absence** du champ reste crue, comme partout ailleurs ici : c'est
         « personne n'a rien dit », pas « non ». */
      if(target&&target.actionable===false){
        refused.push({handTrackId,channel,objectId:target.objectId,reason:'target_not_actionable'});
        return null;
      }
      let capture=null;
      try{
        capture=C.createCapture({handTrackId,channel,state:'captured',
          objectId:target.objectId,region:target.region,zone:target.zone,t:now});
      }catch(error){
        refused.push({handTrackId,channel,objectId:target?target.objectId:null,
          reason:(error&&error.code)||'barehands_capture_invalid'});
        return null;
      }
      const entry={key:keyOf(handTrackId,channel),handTrackId,channel,capture,target,
        objectId:capture.objectId,at:now,downAt:now,armed:false,drove:false,
        content:{mode:null,started:false,lastX:null,lastY:null}};
      /* **La prise refusée par l'outil se dit.** Une main qui se pose et ne
         produit rien est indiscernable d'une panne (RÈGLE ZÉRO) ; le motif
         remonte sur la ligne qui porte déjà les gestes étouffés et les refus
         de manipulation. */
      const plan=toolPlan(entry);
      if(plan.reason){
        refused.push({handTrackId,channel,objectId:capture.objectId,reason:plan.reason,tool});
        return null;
      }
      entry.content.mode=plan.mode;
      captures.set(entry.key,entry);
      return entry;
    }

    /* Toute capture publiée reçoit exactement une fin, et une fin ne s'étouffe
       pas : un `drag_start` sans `drag_end` laisse le consommateur accroché pour
       toujours (leçon de la reprise de la Slice 04). */
    function closeCapture(entry,phase,point,now,out){
      captures.delete(entry.key);
      entry.endedWith=phase;
      /* La dernière fin décide du sort du plan : une manipulation **annulée**
         ne valide rien. */
      const plan=entry.objectId===null?null:plans.get(String(entry.objectId));
      if(plan&&entry.drove)plan.lastEnd=phase;
      const at=point||{x:entry.content.lastX,y:entry.content.lastY};
      const usable=!!at&&Number.isFinite(at.x)&&Number.isFinite(at.y);
      if(entry.content.started&&entry.content.mode===CONTENT_MODE.DRAG&&usable)
        publish(out,I.DRAG_END,entry,at,{t:now,cancelled:phase==='cancel',mode:entry.content.mode});
      /* Une capture qui a **déplacé** quelque chose n'a pas cliqué dessus. Sans
         cette porte, chaque déplacement finirait par un clic sur l'objet qu'on
         vient de poser — et c'est elle que le chemin de clic hérité consulte
         aussi, pour la même raison. */
      if(phase!=='cancel'&&usable&&!entry.drove){
        /* Le canal secondaire est un **doigt**, jamais une durée (décision 22) :
           son relâchement est un clic droit, que le contact ait glissé ou non. */
        if(entry.channel===PINCH_CHANNEL.SECONDARY)publish(out,I.CONTEXT,entry,at,{t:now});
        else if(entry.content.started&&entry.content.mode===CONTENT_MODE.SELECT)
          publish(out,I.SELECT,entry,at,{t:now});
        else if(!entry.content.started)publish(out,I.CLICK,entry,at,{t:now});
      }
      if(entry.drove)drove.add(String(entry.handTrackId));
      if(typeof d.onRelease==='function')
        try{d.onRelease(entry.handTrackId,entry.channel)}catch(_error){}
    }

    /* Le couple que deux captures forment, lu du contrat. Une main ne se couple
       pas à elle-même : `same_hand_twice` est un filet du contrat, pas un
       résultat à interpréter, donc on passe à la capture suivante. */
    function pairFor(list){
      const sorted=[...list].sort((a,b)=>(a.downAt-b.downAt)||(a.key<b.key?-1:1));
      const first=sorted[0]||null;
      if(!first)return {first:null,second:null,out:null};
      for(let i=1;i<sorted.length;i+=1){
        const out=C.combineCaptures(first.capture,sorted[i].capture);
        if(out.reason==='same_hand_twice')continue;
        return {first,second:sorted[i],out};
      }
      return {first,second:null,out:C.combineCaptures(first.capture,null)};
    }

    /* La signature d'un plan : le mode, les axes, et **qui tient quels côtés**.
       Elle change dès que l'attribution change — une main qui entre, une main
       qui se retire, un axe neutralisé — et c'est ce changement, et lui seul,
       qui déclenche le rebasage de la décision 19. */
    const signatureOf=(mode,axes,byHand)=>`${mode}|${axes.join('')}|`+
      Object.keys(byHand).sort().map(id=>`${id}:${byHand[id].sides.join('+')}`).join(',');

    function manipulate(objectId,mode,axes,byHand,entries,palms,now,out){
      const hands=Object.keys(byHand);
      const drivers=hands.filter(id=>palms[id]);
      /* **Toutes** les mains du couple, ou aucune. Une main que le suivi perd
         pendant une image garde sa capture (`lostGraceMs`), mais son côté n'est
         pas pour autant une ancre : laisser l'autre main tirer seule
         redimensionnerait le cadre de travers pendant le clignement, et
         publierait un événement pour une main qui n'a pas de paume. La
         manipulation **se suspend** — et, parce qu'elle s'est suspendue, elle se
         rebase à la reprise, juste en dessous.

         Un `if(!drivers.length)` vivait ici aussi : il ne pouvait plus rien
         trancher que cette égalité ne tranche déjà (aucune paume et aucune main
         est le même compte), et aucun test ne pouvait l'en distinguer. */
      if(drivers.length!==hands.length)return;
      const signature=signatureOf(mode,axes,byHand);
      let plan=plans.get(objectId);
      /* Rien ne bouge tant qu'aucune main tenant ce cadre n'a **glissé** : le
         seuil est celui de la Slice 04 (`dragSlopPx`, mesuré sur la paume), pas
         un nombre de plus. Sans lui, un clic sur un bord déplacerait le cadre
         d'un pixel — et **l'épinglerait** au passage, puisque toute géométrie de
         l'utilisateur épingle. C'est aussi ce qui garantit qu'une main ne
         redimensionne pas par accident. */
      const armed=entries.some(entry=>entry.armed&&byHand[String(entry.handTrackId)]);
      if(!plan&&!armed)return;
      if(!plan){
        const base=world&&typeof world.begin==='function'?world.begin(objectId):null;
        if(!base||!base.box){refuse(entries[0],'object_not_drawn');return}
        plan={signature:null,drivenFrame:null,representation:base.representation,lastEnd:'up',
          origin:{...base.box},start:{...base.box},box:{...base.box},anchorsPx:{}};
        plans.set(objectId,plan);
      }
      /* Décision D3 : seules `capsule` et `window` se redimensionnent. Les zones
         n'existent pas ailleurs, donc ce refus est un filet — mais un filet qui
         se dit, plutôt qu'un redimensionnement sûr de lui sur une forme qui n'en
         a pas. */
      if(mode==='resize'&&!G.resizable(plan.representation)){refuse(entries[0],'frame_not_resizable');return}
      if(mode==='resize'){
        /* Deux mains ne gardent jamais le même côté : `combineCaptures` a déjà
           tranché (décisions 16 et 17), et un contrôle exhaustif des 64 couples
           de zones n'a trouvé aucune exception. Si cela arrivait quand même, ce
           serait le contrat qui aurait changé — mais un contrat qui change ne
           vaut pas la fin de la session : le refus **se dit et se saute**, comme
           partout ailleurs dans cette boucle d'images, au lieu de lancer une
           erreur hors de `update()`. Et il se lit sur l'attribution seule, avant
           le rebasage, pour que l'image suspendue reprenne sans saut. */
        const seen=new Set();
        for(const id of hands)for(const side of byHand[id].sides){
          if(seen.has(side)){refuse(entries[0],'side_held_twice');return}
          seen.add(side);
        }
      }
      /* **Décision 18 et la conversion.** La fenêtre de la scène est ce qui
         donne l'échelle pixels → unités ; sans elle `pxToUnits` retomberait à
         1:1, soit six fois trop de course pour le même geste. Une échelle qu'on
         ne connaît pas se **refuse** : un cadre qui ne bouge pas en le disant
         est réparable, un cadre qui part six fois trop loin ne l'est pas. */
      const vp=world&&typeof world.viewport==='function'?world.viewport():null;
      if(!vp||!(Number(vp.scale)>0)){refuse(entries[0],'viewport_unavailable');return}
      plan.mode=mode;
      /* **Décision 19, et son second déclencheur.** La signature dit *qui tient
         quoi* : elle attrape une main qui entre, une main qui se retire, un axe
         neutralisé, une main re-détectée sous une **autre** identité de piste.
         Elle ne peut pas dire « ce plan n'a pas tourné à l'image précédente » —
         or c'est exactement ce que laissent derrière elles toutes les
         suspensions : une prise refusée, une forme qui ne se redimensionne pas,
         une fenêtre non mesurable, et surtout une main que le suivi perd le
         temps d'un clignement puis retrouve **sous la même identité**, ailleurs.
         Sans ce second déclencheur, la course accumulée pendant la suspension
         s'appliquait d'un coup à la reprise : mesuré à 68 unités. */
      const resumed=plan.drivenFrame!==frameIndex-1;
      if(plan.signature!==signature||resumed){
        const rebased=G.rebaseManipulation(plan.box,palms);
        plan.signature=signature;plan.start=rebased.start;plan.anchorsPx=rebased.anchorsPx;
      }
      plan.drivenFrame=frameIndex;
      const sidesPx={};
      let deltaPx={dx:0,dy:0};
      /* Chaque conducteur a son ancre, et c'est un invariant, pas un espoir :
         toutes les mains du couple ont une paume (au-dessus), les ancres sont
         **reconstruites à partir des paumes** à chaque rebasage, et toute
         entrée ou sortie de main change la signature — donc rebase. Un
         `if(!anchor)continue` gardait ce point ; il ne pouvait plus se produire,
         et une ligne qu'aucun test ne peut atteindre n'est pas une ceinture. */
      for(const id of drivers){
        const anchor=plan.anchorsPx[id];
        const palm=palms[id];
        const dx=palm.x-anchor.x,dy=palm.y-anchor.y;
        if(mode==='resize'){
          for(const side of byHand[id].sides){
            const axis=C.SIDE_AXIS[side];
            if(axis===undefined)continue;
            sidesPx[side]=axis==='x'?dx:dy;
          }
        }else deltaPx={dx,dy};
      }
      /* La manipulation est **conduite** dès que le plan existe, qu'elle ait
         bougé d'une unité ou non : c'est elle qui tient la main, donc ni clic ni
         geste ne partent de là (décision 13). */
      for(const entry of entries)if(byHand[String(entry.handTrackId)]){
        entry.drove=true;drove.add(String(entry.handTrackId));
      }
      const box=G.manipulateBox({start:plan.start,representation:plan.representation,
        mode,axes,sidesPx,deltaPx,vp});
      if(G.sameBox(box,plan.box))return;
      plan.box=box;
      if(world&&typeof world.preview==='function')world.preview(objectId,box);
      for(const entry of entries){
        if(!byHand[String(entry.handTrackId)])continue;
        const palm=palms[String(entry.handTrackId)];
        publish(out,mode==='resize'?I.RESIZE:I.MOVE,entry,palm,{axes,t:now});
      }
    }

    /* Un plan se rend quand plus aucune main ne tient son cadre. Une fin par
       **annulation** (main perdue, veille, extinction) ne valide rien : c'est ce
       que fait déjà la souris sur `pointercancel`, et c'est la seule réponse
       honnête quand on ne sait plus où était la main. */
    function closePlan(objectId,plan,cancelled){
      plans.delete(objectId);
      if(!world)return;
      if(cancelled||G.sameBox(plan.box,plan.origin)){
        if(typeof world.cancel==='function')world.cancel(objectId);
        return;
      }
      if(typeof world.commit==='function')world.commit(objectId,plan.box,plan.mode||'move');
    }

    return {
      /* `{now, tokens, events, contacts, targets}` — les jetons de la Slice 03
         (position filtrée, ancre, **paume**), les événements et contacts de la
         Slice 04, les cibles figées de la Slice 05. */
      update(frame){
        const f=frame||{};
        const now=Number(f.now);
        if(!Number.isFinite(now))
          throw Object.assign(new Error('moteur d’interaction : horodatage inutilisable'),{code:'tracking_failed'});
        refused=[];drove=new Set();frameIndex+=1;
        const out=[];
        const palms={},aims={};
        for(const token of Array.isArray(f.tokens)?f.tokens:[]){
          const id=token&&token.id;
          if(id===undefined||id===null)continue;
          const px=Number(token.palmX),py=Number(token.palmY);
          const x=Number(token.x),y=Number(token.y);
          if(Number.isFinite(px)&&Number.isFinite(py))palms[String(id)]={x:px,y:py};
          else if(Number.isFinite(x)&&Number.isFinite(y))palms[String(id)]={x,y};
          if(Number.isFinite(x)&&Number.isFinite(y))aims[String(id)]={x,y};
        }
        const targets=new Map();
        for(const target of Array.isArray(f.targets)?f.targets:[])
          if(target)targets.set(keyOf(target.handTrackId,target.channel),target);
        /* L'intention vit dans les contacts, publiés à chaque image par la
           Slice 04 : c'est elle qui arme une manipulation et qui sépare un clic
           d'un glissement. */
        for(const contact of Array.isArray(f.contacts)?f.contacts:[]){
          const entry=captures.get(keyOf(contact&&contact.handTrackId,contact&&contact.channel));
          if(entry&&contact.intent===PINCH_INTENT.DRAG)entry.armed=true;
        }
        for(const event of Array.isArray(f.events)?f.events:[]){
          if(!event)continue;
          const key=keyOf(event.handTrackId,event.channel);
          const point=Number.isFinite(Number(event.x))&&Number.isFinite(Number(event.y))
            ?{x:Number(event.x),y:Number(event.y)}:null;
          if(event.phase===PINCH_PHASE.DOWN){
            const held=captures.get(key);
            if(held)closeCapture(held,'cancel',point,now,out);
            const target=targets.get(key);
            /* Rien sous la main : il n'y a rien à tenir. Ce n'est pas un refus,
               c'est la normale (décision 3 : hors cible, pas de pointeur). */
            if(target)openCapture(event.handTrackId,event.channel,target,now);
            continue;
          }
          const entry=captures.get(key);
          if(!entry)continue;
          entry.at=now;
          if(event.phase===PINCH_PHASE.UP)closeCapture(entry,'up',point,now,out);
          /* La perte donne un `cancel`, jamais un `up` : un `up` déclencherait
             l'action que l'arrêt vient d'interrompre. */
          else if(event.phase===PINCH_PHASE.CANCEL)closeCapture(entry,'cancel',null,now,out);
        }
        /* Filet : une capture dont la main a disparu sans que le canal ait
           publié son annulation ne survit pas à son identité. Même horloge
           qu'ailleurs, et comptée contre l'observation. */
        for(const entry of [...captures.values()]){
          if(palms[String(entry.handTrackId)])entry.at=now;
          else if(now-entry.at>o.lostGraceMs)closeCapture(entry,'cancel',null,now,out);
        }
        /* Les captures vivantes, par objet. Une capture sans `objectId` ne se
           couple à rien (décision 12 : deux éléments anonymes restent deux mains
           indépendantes), et le contrat le dit lui-même. */
        const byObject=new Map();
        for(const entry of captures.values()){
          const id=entry.objectId===null||entry.objectId===undefined?null:String(entry.objectId);
          const bucket=id===null?`@${entry.key}`:id;
          if(!byObject.has(bucket))byObject.set(bucket,[]);
          byObject.get(bucket).push(entry);
        }
        for(const [bucket,list] of byObject){
          const objectId=bucket.charAt(0)==='@'?null:bucket;
          if(objectId===null)continue;   // un élément anonyme ne se couple à rien
          const candidates=list.filter(frameCandidate);
          let pair=null;
          try{pair=pairFor(candidates)}
          catch(error){refuse(candidates[0]||list[0],(error&&error.code)||'barehands_capture_invalid');continue}
          if(!pair||!pair.first)continue;
          const verdict=pair.out||{mode:null,axes:[],byHand:{},reason:'missing_capture'};
          /* Une seule capture : la décision 10 pour une zone, la décision D3
             pour une étoile déplaçable seulement — et la **décision 8** pour le
             corps d'une capsule ou d'une fenêtre, qui reste du contenu. Le
             contrat ne parle que de couples ; la règle d'une capture seule est
             ici, et elle dit la même chose. */
          const single=entry=>{
            if(entry.capture.region===TARGET_REGION.BODY&&!movesByBody(entry))return;
            const id=String(entry.handTrackId);
            manipulate(objectId,'move',['x','y'],
              {[id]:{sides:[...C.zoneSides(entry.capture.zone)],axes:['x','y']}},
              [entry],palms,now,out);
          };
          if(verdict.mode==='resize'||verdict.mode==='move'){
            /* Décision 16/17 pour `resize`, décisions 10/14 pour `move` : les
               côtés et les mains viennent de `byHand`, jamais d'une seconde
               lecture des zones ici. */
            manipulate(objectId,verdict.mode,[...verdict.axes],verdict.byHand,
              candidates.filter(entry=>verdict.byHand[String(entry.handTrackId)]),
              palms,now,out);
          }else if(verdict.reason==='missing_capture'||verdict.reason==='same_hand_twice')single(pair.first);
          else if(verdict.reason==='both_captures_are_body'){
            /* Décision 8 : deux mains dans le contenu d'une fenêtre ne
               l'emportent pas. Chacune fait son interaction de contenu, plus
               bas — il n'y a donc rien à faire ici, et surtout pas un
               déplacement.

               **Sauf sur une étoile déplaçable seulement** (décision D3), où cet
               argument tombe : son corps n'est pas du contenu, c'est sa seule
               prise, et la boucle de contenu la saute elle aussi
               (`movesByBody`). Le résultat était alors un cadre figé, sans
               interaction et **sans un mot** — la main qui traînait l'étoile
               s'arrêtait net, ce qui est indiscernable d'une panne.

               Ce qui est choisi ici : la **première** main (la plus ancienne à
               la descente) continue de déplacer l'étoile, et la seconde se dit.
               Parce qu'une étoile `point` fait ~6 unités : deux mains dessus,
               c'est presque toujours la seconde qui arrive par accident sur un
               geste déjà en cours — et « attraper à deux mains et tirer » est la
               première chose qu'on essaie sur une forme dont on vient
               d'apprendre qu'elle ne se redimensionne pas. Punir le geste en
               cours pour l'arrivée de l'autre main serait la mauvaise moitié du
               choix ; geler n'apprend rien, le refus dit ce qui se passe. */
            if(movesByBody(pair.first)){
              single(pair.first);
              refuse(pair.second,'star_moves_with_one_hand');
            }
          }else if(verdict.reason==='object_unidentified'||verdict.reason==='different_objects'){
            /* Décision 12. Inatteignable depuis ce seau — il porte un
               identifiant et ne groupe qu'un objet — mais si le contrat le
               disait, deux mains resteraient **indépendantes** : chacune sur son
               propre chemin, ce que fait déjà la suite. */
          }else refuse(pair.first,verdict.reason||'capture_conflict');
        }
        /* Un plan dont plus aucune main ne tient le cadre se rend : la dernière
           fin décide s'il se valide ou s'il s'annule. */
        for(const [objectId,plan] of [...plans]){
          const alive=[...captures.values()].some(entry=>entry.drove&&String(entry.objectId)===objectId);
          if(alive)continue;
          closePlan(objectId,plan,plan.lastEnd==='cancel');
        }
        /* Interaction de contenu (décision 8) : ce qui n'est pas un cadre. */
        for(const entry of captures.values()){
          if(entry.drove)continue;                              // cette main tient un cadre
          if(entry.capture.region!==TARGET_REGION.BODY)continue; // une zone n'est jamais du contenu
          /* Une étoile déplaçable seulement (décision D3) : son corps est sa
             seule prise, donc il ne devient jamais du contenu — même si le plan
             n'a pas pu s'ouvrir (objet sorti du dessin). Sinon un `pointerdown`
             partirait dessus et la page de scène le lirait comme un second
             déplacement, par un autre chemin. */
          if(movesByBody(entry))continue;
          if(entry.channel===PINCH_CHANNEL.SECONDARY)continue;   // un clic droit ne traîne rien
          const aim=aims[String(entry.handTrackId)];
          if(!aim)continue;
          if(!entry.armed){entry.content.lastX=aim.x;entry.content.lastY=aim.y;continue}
          if(!entry.content.started){
            entry.content.started=true;
            entry.content.lastX=aim.x;entry.content.lastY=aim.y;
            if(entry.content.mode===CONTENT_MODE.DRAG)
              publish(out,I.DRAG_START,entry,aim,{t:now,mode:entry.content.mode});
            continue;
          }
          const dx=aim.x-entry.content.lastX,dy=aim.y-entry.content.lastY;
          if(dx===0&&dy===0)continue;
          entry.content.lastX=aim.x;entry.content.lastY=aim.y;
          if(entry.content.mode===CONTENT_MODE.SCROLL)
            publish(out,I.SCROLL,entry,aim,{dx,dy,t:now,mode:entry.content.mode});
          else if(entry.content.mode===CONTENT_MODE.DRAG)
            publish(out,I.DRAG_MOVE,entry,aim,{t:now,mode:entry.content.mode});
        }
        /* Ce que l'image rend, et **rien de plus** : `manipulating` et `drove`
           étaient publiés ici aussi, en doublon de `drivenHands()` — deux
           lectures du même fait, de deux types différents (identités brutes
           d'un côté, chaînes de l'autre), et sans un seul lecteur. Le clic
           hérité lit `drivenHands()`, qui est la seule des trois à compter les
           mains qui viennent de relâcher. */
        return {interactions:out,refusals:refused,
          captures:[...new Set([...captures.values()].map(entry=>entry.handTrackId))]};
      },
      /* Arrêt volontaire (veille, extinction, perte du suivi) : tout est
         **annulé**, jamais relâché, et aucune géométrie n'est validée. */
      cancelAll(now){
        const out=[];
        refused=[];
        const at=Number(now)||0;
        for(const entry of [...captures.values()])closeCapture(entry,'cancel',null,at,out);
        for(const [objectId,plan] of [...plans])closePlan(objectId,plan,true);
        return out;
      },
      reset(){captures.clear();plans.clear();refused=[];drove=new Set()},
      capturedHands(){return [...new Set([...captures.values()].map(entry=>entry.handTrackId))]},
      /* Ce que le clic hérité consulte : les mains qui ont conduit un cadre
         pendant cette image, celles qui viennent de relâcher comprises. */
      drivenHands(){return [...new Set([...drove,...[...captures.values()].filter(entry=>entry.drove).map(entry=>String(entry.handTrackId))])]},
      refusals(){return refused},
      /* L'outil actif (décision 25). `toolCapability` **refuse** un nom
         inconnu : c'est une question sur une table, pas un schéma stocké, et
         l'appel arrive hors de la boucle d'images — un refus y est sûr. Les
         captures en cours ne sont pas relues : chacune a déjà décidé ce
         qu'elle voulait dire, et la changer en cours de geste ferait faire à
         la main l'inverse de ce qu'elle a commencé. */
      setTool(value){C.toolCapability(value);tool=String(value);return tool},
      tool(){return tool},
      plans(){return [...plans].map(([objectId,plan])=>({objectId,box:{...plan.box},
        signature:plan.signature,representation:plan.representation}))},
      size(){return captures.size},
    };
  }

  /* ------------------------------------------------------------------
     Identité de main persistante (architecture §2).

     La latéralité ne fait pas une identité. Le traqueur la réétiquette d'une
     image à l'autre — une main vue de profil, deux mains qui se croisent, une
     paume qui se retourne — et l'expérience d'hier s'en servait de clé : les
     deux mains échangeaient leur jeton, leur pincement et leur `pointerId` au
     milieu d'un geste, sans que rien ne le dise. Le contrat l'écrit déjà : la
     latéralité est un indice, jamais l'identité.

     Ici l'identité vient de la **continuité spatiale**. Chaque image :

     1. chaque piste prédit où elle devrait être — dernière position plus
        vitesse, extrapolation bornée à `predictMs`, parce qu'au-delà on
        invente ;
     2. le coût d'un appariement est la distance prédiction ↔ détection **en
        paumes** (invariante à la distance à la caméra, comme le pincement et
        le C), et **rien d'autre** ;
     3. une distance au-delà de `matchRadiusPalms` n'est pas un appariement du
        tout ;
     4. on retient l'attribution de distance **totale** minimale, pas la
        meilleure paire d'abord : au croisement de deux mains, le glouton prend
        la paire la plus proche et impose la pire à l'autre ;
     5. la latéralité ne départage **qu'à distance totale égale**. Elle était
        une prime soustraite au coût jusqu'à cette reprise, et une prime
        soustraite est une clé déguisée : deux étiquettes qui basculent sur la
        même image — ce que fait MediaPipe quand deux mains se recouvrent —
        payaient l'échange `(d − prime) × 2` contre `0` pour l'appariement
        juste, si bien que **l'échange gagnait** sous `prime` paume de
        séparation (0,35, mesuré au millième près). Le pincement, la capture et
        le `pointerId` partaient alors à l'autre main, définitivement au-delà
        de ~330 ms, le temps que la vitesse des pistes se referme sur l'erreur.
        La latéralité est donc désormais une **clé secondaire** : elle ne peut
        rien renverser, seulement choisir entre deux géométries que rien ne
        sépare.

     Une détection sans piste ouvre une piste neuve, numérotée à partir de
     **0** — `0` est une identité, et le contrat le sait depuis sa reprise.
     Une piste sans détection survit `lostGraceMs` : un trou d'une image ne
     coûte pas l'identité, donc ne casse ni une capture ni un glissement en
     cours. Elle revient avec sa continuité retombée, parce qu'on *suppose*
     que c'est la même main. */

  /* Recherche exhaustive : `MAX_HANDS` vaut 2 et le contrat refuse la
     troisième main, donc l'arbre tient en quelques feuilles. Au-delà il
     faudrait un algorithme hongrois — plutôt que de laisser une factorielle
     grandir en silence le jour où `numHands` monte, l'image se refuse et le
     dit (`tracking_failed`), au lieu de faire ramer la boucle sans raison
     visible. */
  const ASSIGNMENT_LIMIT=4;
  /* Égalité de distance à la précision flottante près. Voir `assign` : ce
     n'est pas une bande de tolérance où la latéralité aurait le droit de
     renverser la géométrie, c'est la précision à laquelle deux sommes de
     flottants se lisent « la même ». */
  const MATCH_EPSILON=1e-9;

  function createHandTrackManager(overrides){
    const o=options(overrides);
    const settle=o.qualityWarmupFrames;
    const tracks=new Map();
    let nextId=0;

    /* Attribution de distance totale minimale. `null` = porte fermée ; ne pas
       apparier coûte `matchRadiusPalms`, si bien qu'un appariement dans la
       porte est toujours préféré à une piste neuve.

       **Trois clés, comparées dans cet ordre, et la première décide seule sauf
       égalité :**

       1. la somme des écarts, en paumes — la géométrie, et elle seule ;
       2. le nombre de **désaccords** de latéralité — l'indice. Une étiquette
          absente d'un côté ou de l'autre ne compte ni pour ni contre :
          l'absence d'indice n'est pas un indice contraire, même règle que le
          vote. Cette clé ne peut rien renverser, puisqu'elle n'est lue qu'à
          somme égale ;
       3. les écarts triés du plus grand au plus petit. À somme égale, on
          préfère l'attribution dont la pire paire est la moins mauvaise. Cette
          clé existe pour l'**ordre** : sans elle, deux attributions à somme et
          à latéralité égales étaient départagées par « la première trouvée »,
          c'est-à-dire par le rang des détections dans le tableau — l'identité
          dépendait alors de l'ordre où le traqueur rend ses mains, ce que le
          reste de cette section refuse explicitement. Les trois clés sont
          invariantes par permutation des détections.

       **Les coûts sont des distances, donc positifs ou nuls**, et c'est ce qui
       rend l'élagage légitime : un total partiel ne peut que croître, donc il
       minore le total final, et une branche déjà plus chère que la meilleure
       connue ne peut plus gagner. La prime soustraite d'avant cette reprise
       mettait les coûts dans [−0,35 ; 1,6] : le minorant tombait, et la
       recherche jetait des optimums — 670 attributions non minimales sur
       300 000 matrices 2×2 tirées au hasard, mesurées. L'élagage compare à
       `best.total + MATCH_EPSILON` et non à `best.total` : une branche à somme
       **égale** doit rester explorée, c'est là que les clés 2 et 3 travaillent.

       `MATCH_EPSILON` est une tolérance **numérique**, pas un réglage : 1e-9
       paume, treize ordres de grandeur sous la plus petite séparation que deux
       détections puissent avoir. Ce n'est pas une bande dans laquelle la
       latéralité aurait le droit de renverser la géométrie — c'est la
       précision à laquelle « la même distance » se lit sur des flottants. */
    function assign(costs,discords,detections,trackCount){
      const best={total:Infinity,discord:Infinity,gaps:null,pick:null};
      const current=new Array(detections).fill(-1);
      const used=new Array(trackCount).fill(false);
      const better=(total,discord,gaps)=>{
        if(total<best.total-MATCH_EPSILON)return true;
        if(total>best.total+MATCH_EPSILON)return false;
        if(discord!==best.discord)return discord<best.discord;
        for(let i=0;i<gaps.length;i+=1){
          if(gaps[i]<best.gaps[i]-MATCH_EPSILON)return true;
          if(gaps[i]>best.gaps[i]+MATCH_EPSILON)return false;
        }
        return false;
      };
      const gaps=[];
      (function walk(index,total,discord){
        if(total>best.total+MATCH_EPSILON)return;
        if(index===detections){
          const sorted=gaps.slice().sort((a,b)=>b-a);
          if(better(total,discord,sorted)){
            best.total=total;best.discord=discord;best.gaps=sorted;best.pick=current.slice();
          }
          return;
        }
        for(let t=0;t<trackCount;t+=1){
          if(used[t]||costs[index][t]===null)continue;
          used[t]=true;current[index]=t;gaps.push(costs[index][t]);
          walk(index+1,total+costs[index][t],discord+(discords[index][t]?1:0));
          gaps.pop();used[t]=false;
        }
        current[index]=-1;
        /* Ne pas apparier : la porte vaut son plein prix, et une piste neuve
           n'est ni un accord ni un désaccord de latéralité. */
        gaps.push(o.matchRadiusPalms);
        walk(index+1,total+o.matchRadiusPalms,discord);
        gaps.pop();
      })(0,0,0);
      return best.pick||new Array(detections).fill(-1);
    }

    /* La latéralité se vote, elle ne se lit pas image par image : une seule
       image contraire ne renverse pas une identité installée. Le gain est
       `1/qualityWarmupFrames` — ce dépôt appelle « installé » trois images
       consécutives, et il n'y a pas de raison que ce soit deux nombres.
       Une étiquette absente ne vote pas : l'absence d'indice n'est pas un
       indice contraire. */
    function vote(track,label,confidence){
      if(!label)return;
      const gain=clamp(confidence,0,1)/settle;
      if(label===track.handedness){track.vote=clamp(track.vote+gain,0,1);return}
      track.vote-=gain;
      if(track.vote<=0){track.handedness=label;track.vote=gain}
    }

    function advance(track,observation,at){
      const dt=Math.max(0,at-track.at);
      if(dt>0){
        const seconds=dt/1000;
        const vx=(observation.x-track.x)/seconds,vy=(observation.y-track.y)/seconds;
        track.vx+=(vx-track.vx)*o.trackVelocityBlend;
        track.vy+=(vy-track.vy)*o.trackVelocityBlend;
      }
      track.x=observation.x;track.y=observation.y;track.at=at;
      /* Revenue d'un trou : l'identité tient, la confiance non. Le compteur
         d'images consécutives repart, donc la qualité dit « devinée » le temps
         de le redevenir. */
      if(track.missed){track.seen=1;track.recovered=true;track.missed=false}
      else{track.seen+=1;track.recovered=false}
      vote(track,observation.handedness,observation.handednessConfidence);
    }

    return {
      /* `{hands:[{x,y,palm,handedness,handednessConfidence}], now, aspect}` →
         une entrée par main, dans le même ordre. Les positions sont en
         coordonnées d'image normalisées (0..1 par axe), `palm` déjà corrigée
         de l'aspect. Aucun indice MediaPipe n'arrive jusqu'ici. */
      update(frame){
        const f=frame||{};
        const at=Number(f.now);
        if(!Number.isFinite(at))
          throw Object.assign(new Error('suivi des mains : horodatage inutilisable'),{code:'tracking_failed'});
        const k=Number(f.aspect)>0?Number(f.aspect):1;
        const list=Array.isArray(f.hands)?f.hands:[];
        if(list.length>ASSIGNMENT_LIMIT)
          throw Object.assign(new Error(`suivi des mains : ${list.length} détections, au-delà de la recherche exhaustive (${ASSIGNMENT_LIMIT})`),
            {code:'tracking_failed'});
        /* Purge **avant** d'apparier, et non après. Purger après ne regarde
           que les images qu'on a reçues : une boucle arrêtée (onglet en
           arrière-plan, écran rabattu, caméra figée) ne purge rien, et la
           première image du retour retrouve une piste vieille de dix secondes
           encore posée là où la main était — ressuscitée, avec sa capture et
           son `pointerId`. Même leçon que la Slice 02 : la grâce se compte
           contre l'observation, pas contre le nombre d'appels. */
        for(const [id,track] of tracks)if(at-track.at>o.lostGraceMs)tracks.delete(id);
        const ids=[...tracks.keys()];
        const costs=[],discords=[];
        for(const observation of list){
          const palm=Number(observation&&observation.palm);
          const scale=Number.isFinite(palm)&&palm>1e-6?palm:1;
          const row=[],discord=[];
          for(const id of ids){
            const track=tracks.get(id);
            const horizon=Math.min(Math.max(0,at-track.at),o.predictMs)/1000;
            const gap=Math.hypot(
              ((track.x+track.vx*horizon)-observation.x)*k,
              (track.y+track.vy*horizon)-observation.y)/scale;
            /* La porte se juge sur la distance, et le coût **est** cette
               distance : la latéralité n'ouvre pas la porte et ne la ferme
               pas non plus, elle voyage à part (`discords`). */
            row.push(gap<=o.matchRadiusPalms?gap:null);
            discord.push(!!(observation.handedness&&track.handedness
              &&observation.handedness!==track.handedness));
          }
          costs.push(row);discords.push(discord);
        }
        const pick=assign(costs,discords,list.length,ids.length);
        const live=new Set();
        const out=list.map((observation,index)=>{
          const matched=pick[index]>=0;
          const id=matched?ids[pick[index]]:nextId++;
          if(matched)advance(tracks.get(id),observation,at);
          else tracks.set(id,{x:observation.x,y:observation.y,vx:0,vy:0,at,
            seen:1,missed:false,recovered:false,
            handedness:observation.handedness||'',vote:clamp(observation.handednessConfidence,0,1)/settle});
          const track=tracks.get(id);
          live.add(id);
          return Object.freeze({handTrackId:id,
            handedness:track.handedness||'unknown',handednessConfidence:track.vote,
            continuity:clamp(track.seen/settle,0,1),
            isNew:!matched,recovered:track.recovered,ageFrames:track.seen});
        });
        // Vue nulle part cette image : l'identité tient (la purge du début
        // décidera), la continuité non — c'est `advance` qui la fera retomber.
        for(const [id,track] of tracks)if(!live.has(id))track.missed=true;
        return out;
      },
      has(id){return tracks.has(id)},
      reset(){tracks.clear();nextId=0},
      size(){return tracks.size},
    };
  }

  /* Résultat du traqueur → jetons à afficher, clics à rejouer et identités
     stables. Pendant un pincement, le jeton se fige là où il était quand les
     doigts ont commencé à se rapprocher : le clic tombe sur ce qui était visé,
     pas à côté.

     Chaque jeton porte trois couples de coordonnées, et les trois servent :
     `rawX`/`rawY` ce que le traqueur a rendu, `filteredX`/`filteredY` la
     sortie du filtre, `x`/`y` le point d'affichage et de visée — le filtré,
     ou l'ancre gelée pendant un pincement. Sans les deux premiers, un filtre
     ne se règle pas et la calibration ne peut pas mesurer le tremblement
     (`jitterPx`) ; pendant un pincement, `x`/`y` ne dit plus rien de la main. */
  function createHandTracker(overrides){
    const o=options(overrides);
    const manager=createHandTrackManager(overrides);
    const hands=new Map();
    return {
      update(result,frame){
        const now=frame.now;
        const k=Number(frame.aspect)>0?Number(frame.aspect):1;
        const list=(result&&result.landmarks)||[];
        const observations=[],sources=[];
        const trackIds=list.map(()=>null);
        list.forEach((landmarks,index)=>{
          /* Même définition qu'ailleurs : une main qui ne donne pas ses quatre
             points ne porte pas de jeton — et, décision 7, ne réarme donc pas
             le retour en veille sous une définition plus large que celle du
             guetteur. Les deux se répondaient à un point d'écart. */
          if(!usableLandmarks(landmarks))return;
          const wrist=landmarks[LM.WRIST],middle=landmarks[LM.MIDDLE_MCP];
          observations.push({
            /* Le repère de l'association est le **centre de la paume**, pas le
               bout de l'index : l'index parcourt plusieurs paumes pendant un
               pincement, et une main qui pince se lirait comme une main qui
               saute — c'est-à-dire comme une autre main. */
            x:(wrist.x+middle.x)/2,y:(wrist.y+middle.y)/2,
            palm:distance(wrist,middle,k),
            handedness:handLabel(result,index),handednessConfidence:handScore(result,index),
          });
          sources.push({index,landmarks});
        });
        const assigned=manager.update({hands:observations,now,aspect:k});
        const tokens=[],clicks=[];
        assigned.forEach((entry,rank)=>{
          const {index,landmarks}=sources[rank];
          const id=entry.handTrackId;
          trackIds[index]=id;
          let hand=hands.get(id);
          if(!hand){hand={detector:createPinchDetector(overrides),filter:createPointerFilter(overrides),
            still:createStillness(overrides),anchor:null};hands.set(id,hand)}
          const motion=hand.filter.update(toScreen(landmarks[LM.INDEX_TIP],frame.viewport,o),now);
          const still=hand.still.update(motion.speedPxPerSec,now);
          const pinch=hand.detector.update(pinchRatio(landmarks,k),now);
          if(pinch.state==='open')hand.anchor=null;
          else if(!hand.anchor)hand.anchor={x:motion.x,y:motion.y};
          const aim=hand.anchor||motion;
          if(pinch.click)clicks.push({id,x:aim.x,y:aim.y});
          /* Où la **main** est, par opposition à où elle vise : le centre de la
             paume, en pixels de la fenêtre. Même repère que l'association
             d'identité, et pour la même raison — il ne bouge pas parce qu'un
             doigt se referme. La Slice 04 y mesure le déplacement d'un
             contact ; le jeton, lui, continue de suivre l'index. */
          const palm=toScreen(palmCenter(landmarks),frame.viewport,o);
          tokens.push({id,x:aim.x,y:aim.y,palmX:palm.x,palmY:palm.y,
            rawX:motion.rawX,rawY:motion.rawY,filteredX:motion.x,filteredY:motion.y,
            vxPxPerSec:motion.vxPxPerSec,vyPxPerSec:motion.vyPxPerSec,speedPxPerSec:motion.speedPxPerSec,
            stillness:still.stillness,stillMs:still.stillMs,
            quality:handQuality(landmarks,k,entry.continuity,overrides),
            handedness:entry.handedness,
            state:pinch.state,progress:pinch.progress,click:pinch.click,hover:false,t:now});
        });
        /* L'état par main vit exactement aussi longtemps que son identité :
           c'est le gestionnaire qui tient la grâce, un seul endroit plutôt que
           deux horloges qui se répondent à quelques millisecondes près. */
        for(const id of [...hands.keys()])if(!manager.has(id))hands.delete(id);
        /* `trackIds` est aligné sur `result.landmarks`, trous compris : c'est
           ce que `handFrameFromMediapipe(result,{trackIds})` attend pour
           imposer l'identité persistante au `HandFrame` neutre. */
        return {tokens,clicks,trackIds};
      },
      reset(){manager.reset();hands.clear()},
      size(){return hands.size},
    };
  }

  const MESSAGES=Object.freeze({
    off:{title:'Barehands éteint',detail:'Le mode test est désactivé.'},
    starting:{title:'Barehands démarre…',detail:'Chargement du suivi des mains et ouverture de la caméra.'},
    sleep:{title:'Barehands en veille',detail:'La caméra guette. Formez un C avec le pouce et l’index et tenez une seconde pour activer.'},
    active:{title:'Barehands actif',detail:'Montrez une main à la caméra ; pincez pouce et index pour cliquer.'},
    woken:{title:'Barehands activé',detail:'Posture de réveil reconnue : l’interaction à mains nues est active.'},
    idle_sleep:{title:'Retour en veille',detail:'Aucune main vue depuis 30 secondes : interaction suspendue, caméra gardée pour le guetteur.'},
    disabled:{title:'Barehands arrêté',detail:'Mode test désactivé : caméra libérée, jetons retirés.'},
    camera_denied:{title:'Caméra refusée',detail:'Autorisez la caméra pour cette page dans le navigateur, puis réactivez l’interrupteur.'},
    camera_missing:{title:'Aucune caméra',detail:'Aucune webcam utilisable n’a été trouvée.'},
    camera_busy:{title:'Caméra indisponible',detail:'La webcam est occupée par une autre application ou ne répond pas.'},
    camera_ended:{title:'Caméra coupée',detail:'La webcam s’est arrêtée (débranchée ou coupée) : suivi arrêté.'},
    camera_unsupported:{title:'Caméra non prise en charge',detail:'Ce navigateur n’expose pas la caméra à cette page.'},
    assets_missing:{title:'Modèle introuvable',detail:'Les fichiers MediaPipe ne sont pas installés : lancez python scripts/bootstrap_third_party.py.'},
    tracking_failed:{title:'Suivi interrompu',detail:'Le suivi des mains a échoué : caméra libérée.'},
    overlay_failed:{title:'Affichage interrompu',detail:'La surimpression des mains n’a pas pu se dessiner : suivi arrêté, caméra libérée.'},
    start_failed:{title:'Démarrage impossible',detail:'Le suivi des mains n’a pas pu démarrer.'},
  });

  function classifyError(error){
    if(error&&typeof error.code==='string'&&MESSAGES[error.code])return error.code;
    const name=String((error&&error.name)||'');
    if(['NotAllowedError','PermissionDeniedError','SecurityError'].includes(name))return 'camera_denied';
    if(['NotFoundError','DevicesNotFoundError','OverconstrainedError'].includes(name))return 'camera_missing';
    if(['NotReadableError','TrackStartError','AbortError'].includes(name))return 'camera_busy';
    return 'start_failed';
  }

  /* États du contrôleur. Les trois noms du contrat (décision 4) plus les deux
     transitoires : `starting` (rien n'est encore acquis pour de bon) et
     `error` (tout a été rendu), qui se lisent `off` côté contrat.
     Ces chaînes doivent rester celles de `JarvisBarehandsContracts.LIFECYCLE`.
     Le bloc pur ne peut pas lire le contrat — les tests node le chargent
     seul — donc un test de parité refuse qu'elles divergent. */
  const STATE=Object.freeze({OFF:'off',STARTING:'starting',SLEEP:'sleep',ACTIVE:'active',ERROR:'error'});
  const STATES=Object.freeze(Object.keys(STATE).map(k=>STATE[k]));
  /* Deux lectures d'« allumé » qu'un seul `!== OFF` confondait, et qui ne
     recouvrent pas les mêmes états :

     - `isLiveState` — **Bare Hands fonctionne**. C'est ce qu'on annonce : une
       panne n'est pas un fonctionnement, un démarrage pas encore un. Miroir de
       `JarvisBarehandsContracts.LIVE_LIFECYCLES`, comme `STATE` l'est de
       `LIFECYCLE` et pour la même raison (le bloc pur est chargé seul par les
       tests node) ; le test de parité refuse qu'ils divergent.
     - `isEngagedState` — **quelque chose est tenu et doit être rendu** : la
       veille, l'interaction, mais aussi un démarrage encore en vol, dont
       l'annulation est précisément ce qui libère la caméra qui arrive. `ERROR`
       n'en est pas : il a déjà tout rendu avant d'être publié, et l'y mettre
       ferait repasser un arrêt subi pour un arrêt voulu. */
  const LIVE_STATES=Object.freeze([STATE.SLEEP,STATE.ACTIVE]);
  const isLiveState=value=>LIVE_STATES.includes(value);
  const isEngagedState=value=>isLiveState(value)||value===STATE.STARTING;

  /* Première main exploitable d'un résultat de traqueur, ou `null`. Celle
     qu'on peut **dessiner** : ses points sont là, donc on sait où la montrer. */
  function usableHand(result){
    for(const landmarks of (result&&result.landmarks)||[])
      if(usableLandmarks(landmarks))return landmarks;
    return null;
  }
  /* Première main qui **compte** (décision 7), ou `null`. C'est `usableHand`
     plus `usableQuality` — la même question qu'en interaction, posée avec la
     même définition, et c'est tout l'objet de cette fonction.

     Elle existe parce que la veille et l'interaction en avaient deux. Le
     minuteur d'ACTIVE se réarme sur `usableQuality`, le guetteur ne lisait que
     les points : un C tenu par une main de qualité 0,125 réveillait, ACTIVE la
     refusait aussitôt, et la session **cyclait sans fin** — actif, 30 s,
     veille, réveil une seconde plus tard, et ainsi de suite, en détruisant
     toutes les identités et en réallouant les fentes de pointeur à chaque
     tour, deux pastilles par cycle. C'est exactement la classe de défaut que
     cette Slice s'était donnée pour but de fermer, et le commentaire de
     `usableQuality` prétendait déjà qu'il n'existait qu'une définition.

     La continuité vaut 1 : en veille il n'y a **pas d'identité à mettre en
     doute** — aucun gestionnaire de pistes ne tourne, le guetteur ne suit rien
     d'une image à l'autre. Ce que la continuité mesure en interaction, le
     maintien d'une seconde du C le mesure ici, et mieux : cinq mesures
     consécutives de la même posture. Les trois autres témoins (échelle,
     cadrage, complétude) répondent image par image et s'appliquent tels quels.

     La main **refusée reste dessinée** : `watch()` la montre et la progression
     n'avance pas, comme un C imparfait. L'écran dit « je te vois » et l'anneau
     dit « ça ne prend pas » — RÈGLE ZÉRO —, au lieu de la faire disparaître. */
  function trustedHand(result,aspect,overrides){
    for(const landmarks of (result&&result.landmarks)||[])
      if(usableLandmarks(landmarks)
        &&usableQuality(handQuality(landmarks,aspect,1,overrides),overrides))return landmarks;
    return null;
  }

  /* Cycle de vie OFF → SLEEP → ACTIVE (décisions 4, 5, 7).

     - **OFF** ne tient rien : modèle, flux caméra, vidéo, surimpression,
       survol et boucle d'images sont rendus par un seul chemin, `teardown`,
       que l'arrêt soit voulu ou subi. `generation` invalide un démarrage
       encore en vol quand on éteint entre-temps.
     - **SLEEP** garde la caméra et guette : une seule main, un seul score de
       posture, aucun survol, aucun clic, aucun jeton.
     - **ACTIVE** fait tourner le suivi complet et l'interaction.

     Allumer mène à SLEEP, jamais directement à ACTIVE : rien n'interagit tant
     que l'utilisateur n'a pas réveillé, d'un C tenu une seconde ou du bouton
     de l'onglet Expérimental. */
  function createController(deps){
    const o=options(deps.options);
    /* Surcharges vivantes du moteur : ce que `configure` a accumulé depuis la
       construction. Voir `configure` plus bas. */
    let liveOptions={...(deps.options||{})};
    const tracker=createHandTracker(deps.options);
    const wake=createWakeDetector(deps.options);
    /* Les deux moteurs de la Slice 04. Ils ne tournent qu'en ACTIVE : le budget
       d'images de la veille (5 inférences contre 60, mesuré) est un acquis de
       la Slice 02 et le travail sémantique n'y a rien à faire — la veille n'a
       qu'une question, la posture de réveil, et `createWakeDetector` y répond
       déjà. */
    const gestures=createGestureEngine(deps.options);
    const pinches=createPinchIntentEngine(deps.options,
      /* Le profil de calibration, s'il y en a un (Slice 08). Le contrôleur ne
         sait pas plus que le moteur ce qu'est un profil : il passe la question
         telle quelle. */
      {handOverrides:typeof deps.handOverrides==='function'?deps.handOverrides:null});
    let state=STATE.OFF,generation=0,landmarker=null,stream=null,video=null,frame=0,lastVideoTime=-1;
    /* Guetteur : dernière inférence de veille. Interaction : dernière image où
       une main exploitable a été vue, qui arme le retour en veille. */
    let lastWatchAt=-Infinity,lastHandAt=0;
    /* Dernier lot de traits de mouvement publié (Slice 03) : ce que
       `window.JarvisBarehands.diagnostics()` rend lisible sans caméra ni
       console, et ce que la calibration de la Slice 08 mesurera. Vidé partout
       où l'interaction s'arrête, pour qu'il ne survive jamais à ce qu'il
       décrit. */
    let features=[];
    /* Dernière sortie sémantique publiée (Slice 04), lisible sans caméra par
       `window.JarvisBarehands.gestures()`. Vidée partout où l'interaction
       s'arrête, pour la même raison que `features` : elle ne doit jamais
       survivre à ce qu'elle décrit. */
    let semantics={gestures:{events:[],suppressed:[],postures:[]},pinch:{events:[],contacts:[]}};
    const forgetSemantics=()=>{semantics={gestures:{events:[],suppressed:[],postures:[]},
      pinch:{events:[],contacts:[]}}};
    /* Tout contact en cours est **annulé**, jamais relâché : un `up` ferait
       partir l'action que l'arrêt vient justement d'interrompre. */
    function dropContacts(now){
      const cancelled=pinches.cancelAll(Number(now)||0);
      gestures.reset();
      forgetSemantics();
      return cancelled;
    }

    function emit(code,error){
      const message=MESSAGES[code]||MESSAGES.start_failed;
      if(typeof deps.onStatus==='function')deps.onStatus({state,code,title:message.title,message:message.detail,error:error||null});
    }
    function stopStream(value){
      if(!value||typeof value.getTracks!=='function')return;
      for(const track of value.getTracks()){try{track.stop()}catch(_error){}}
    }
    function teardown(){
      if(frame){deps.cancelFrame(frame);frame=0}
      stopStream(stream);stream=null;
      if(video){try{video.dispose()}catch(_error){}video=null}
      if(landmarker){try{landmarker.close()}catch(_error){}landmarker=null}
      try{deps.interaction.clear()}catch(_error){}
      try{deps.overlay.unmount()}catch(_error){}
      tracker.reset();wake.reset();lastVideoTime=-1;lastWatchAt=-Infinity;lastHandAt=0;features=[];
      dropContacts(0);
    }
    function fail(error,code){
      generation+=1;teardown();state=STATE.ERROR;emit(code||classifyError(error),error);
    }
    const aspect=()=>(video&&video.width&&video.height)?video.width/video.height:4/3;
    /* La surimpression n'est pas le suivi. `teardown` enveloppe chaque appel
       sorti d'ici parce qu'on rend déjà tout ; les transitions, elles, le
       laissaient nu, et un anneau qui lève se lisait « suivi interrompu :
       caméra libérée » ou « démarrage impossible » — une cause inventée à la
       place de la vraie. Le code voyage avec l'erreur et `classifyError` le
       reconnaît : la panne d'affichage se dit sous son nom. */
    function paintWatch(value){
      try{deps.overlay.watch(value)}
      catch(error){
        throw Object.assign(new Error(`surimpression : ${(error&&error.message)||error}`),
          {code:'overlay_failed',cause:error});
      }
    }
    /* SLEEP → ACTIVE et ACTIVE → SLEEP. La caméra, le modèle et la vidéo ne
       bougent pas : seules l'interaction et la surimpression changent de
       régime, et tout compteur repart de zéro pour que le réveil suivant ne
       parte pas d'un reste. */
    function toActive(code){
      wake.reset();tracker.reset();lastVideoTime=-1;lastHandAt=deps.now();features=[];dropContacts(deps.now());
      state=STATE.ACTIVE;emit(code||'active');
      paintWatch(null);
    }
    function toSleep(code){
      tracker.reset();wake.reset();lastVideoTime=-1;lastWatchAt=-Infinity;features=[];dropContacts(deps.now());
      try{deps.interaction.clear()}catch(_error){}
      state=STATE.SLEEP;emit(code||'sleep');
      paintWatch({present:false,progress:0,x:0,y:0});
    }
    /* Guetteur de veille. Budget d'images : le coût n'est pas la boucle mais
       l'inférence MediaPipe (plusieurs millisecondes par image). On ne la
       lance qu'une fois par `wakeIntervalMs` — 5 images/s, soit ~12 fois moins
       qu'à 60 Hz — et c'est assez : la seconde de maintien du C y laisse cinq
       intervalles, au-delà du minimum qu'il faut pour distinguer une posture
       tenue d'un passage de main. Entre deux inférences, le rappel
       d'animation ne fait qu'une comparaison d'horodatage. Le reste du travail
       d'ACTIVE — jetons, lissage, survol, clics — n'est pas exécuté du tout. */
    function watch(now){
      if(now-lastWatchAt<o.wakeIntervalMs)return;
      lastWatchAt=now;
      const time=video.currentTime();
      /* Horloge vidéo figée : aucune image nouvelle à lire. Ce n'est pas une
         posture tenue, c'est une **absence d'observation**, et elle se déclare
         telle quelle plutôt que de sortir en silence — sinon l'anneau reste
         figé sur une progression que plus rien n'alimente, et le guetteur ne
         voit pas passer le gel. Le détecteur la traite comme une perte : au
         bout de `wakeGraceMs` la progression retombe, à l'écran comme dedans.
         Deux mécanismes se recouvrent ici, à dessein : celui-ci voit une
         caméra figée, la borne de `createWakeDetector` voit une boucle
         d'images arrêtée (onglet en arrière-plan, écran rabattu), et aucun des
         deux ne peut se bloquer de la même façon que l'autre. */
      if(time===lastVideoTime){
        const stalled=wake.update(null,now);
        paintWatch({present:false,progress:stalled.progress,x:0,y:0});
        return;
      }
      lastVideoTime=time;
      const result=landmarker.detectForVideo(video.element,now);
      /* Deux questions, deux réponses, et c'est voulu : `seen` est la main
         qu'on **dessine**, `counts` celle qui **compte** (décision 7, même
         définition qu'en interaction — voir `trustedHand`). Une main vue mais
         pas crue reste à l'écran avec un anneau qui n'avance pas ; la faire
         disparaître dirait « je ne te vois pas », ce qui est faux, et réveiller
         sur elle ferait cycler la session entre veille et interaction. Le
         budget d'images ne bouge pas : une inférence par `wakeIntervalMs`,
         comme avant, plus une mesure de qualité qui ne coûte qu'une boucle. */
      const seen=usableHand(result);
      const counts=trustedHand(result,aspect(),deps.options);
      const out=wake.update(counts?cPoseScore(counts,aspect(),deps.options):null,now);
      const at=seen?toScreen(seen[LM.INDEX_TIP],deps.viewport(),o):null;
      paintWatch({present:!!seen,progress:out.progress,x:at?at.x:0,y:at?at.y:0});
      if(out.wake)toActive('woken');
    }
    /* Interaction complète. Le retour en veille est jugé avant de lire la
       vidéo : une caméra figée doit rendormir, pas rester active pour
       toujours (décision 7). */
    function interact(now,mine){
      if(now-lastHandAt>=o.sleepTimeoutMs){toSleep('idle_sleep');return}
      const time=video.currentTime();
      if(time===lastVideoTime)return;
      lastVideoTime=time;
      const result=landmarker.detectForVideo(video.element,now);
      const out=tracker.update(result,{viewport:deps.viewport(),aspect:aspect(),now});
      /* Décision 7 : « une main exploitable ». La Slice 02 a dû l'approximer
         en « une main quelconque », faute de qualité à lire — une main à
         moitié hors cadre, ou une ombre que le traqueur devine, gardait donc
         l'interaction éveillée pour toujours. La qualité existe désormais : le
         minuteur se réarme sur une main en laquelle on a confiance. Le jeton
         reste affiché dans tous les cas, et se dessine pâle : l'écran dit
         « je te vois mais je ne te crois pas », plutôt que de laisser la
         session s'endormir sans prévenir (RÈGLE ZÉRO). */
      if(out.tokens.some(token=>usableQuality(token.quality,deps.options)))lastHandAt=now;
      /* Slice 04 : le geste et le pincement se lisent sur la **même image** que
         les jetons, et sur les traits que la Slice 03 publie — jamais sur une
         dérivée recalculée ici. `x`/`y` du jeton est l'ancre de visée pendant
         un pincement et ne dit plus rien de la main : les deux positions
         voyagent donc séparément jusqu'au moteur, qui sait laquelle sert à
         quoi. `captured` est la couture de la Slice 06, vide tant que les
         captures n'existent pas. */
      const byId=new Map(out.tokens.map(token=>[String(token.id),token]));
      const observed=[];
      ((result&&result.landmarks)||[]).forEach((landmarks,index)=>{
        const id=out.trackIds[index];
        const token=id===null||id===undefined?null:byId.get(String(id));
        if(!token)return;
        observed.push({handTrackId:id,landmarks,
          x:token.filteredX,y:token.filteredY,anchorX:token.x,anchorY:token.y,
          palmX:token.palmX,palmY:token.palmY,
          stillness:token.stillness,quality:token.quality});
      });
      const held=typeof deps.captures==='function'?deps.captures():[];
      semantics={
        gestures:gestures.update({hands:observed,now,aspect:aspect(),captured:held}),
        pinch:pinches.update({hands:observed,now,aspect:aspect()}),
      };
      deps.interaction.hover(out.tokens);
      /* RÈGLE ZÉRO. Un geste étouffé pendant une manipulation (contrat § 4)
         partait dans `suppressed` et n'arrivait nulle part : à l'écran, une
         main qui insiste sans effet, et rien pour dire que c'est voulu. La
         raison du premier étouffement de l'image remonte donc à la
         surimpression, telle quelle. */
      /* Et ce que la Slice 06 a **refusé** de manipuler (deux mains sur la même
         prise, axes neutralisés, objet sorti du dessin) : même ligne, même
         raison. Un geste étouffé passe devant — il est plus rare et plus
         surprenant. Lu après `hover`, donc c'est bien le refus de cette image. */
      const muted=semantics.gestures.suppressed;
      const refused=typeof deps.interaction.refusal==='function'?deps.interaction.refusal():'';
      deps.overlay.render(out.tokens,muted.length?muted[0].reason:refused);
      // Traits du dernier instant, pour la calibration et les diagnostics
      // (architecture §12) : lus après le survol, donc `hover` y est juste.
      features=out.tokens;
      /* **La couture de la calibration (Slice 08), et la décision 32 en
         structure.** Le parcours ne reçoit jamais de points : il reçoit, par
         main, un enregistrement de **scalaires** construit ici. Il ne peut donc
         pas persister une image, un point ni une vidéo — non parce qu'on le lui
         interdit, parce qu'il n'en a jamais eu. La promesse est tenue par ce
         qui traverse la couture, pas par la discipline de ce qui est derrière.

         Rien n'est calculé tant que personne n'écoute : hors calibration le
         budget d'images est exactement celui d'avant. */
      if(typeof deps.onMeasure==='function'&&observed.length){
        const k=aspect();
        const samples=[];
        for(const hand of observed){
          const token=byId.get(String(hand.handTrackId));
          const posture=handPosture(hand.landmarks,k,deps.options);
          const tip=hand.landmarks[LM.INDEX_TIP];
          samples.push({
            handTrackId:hand.handTrackId,
            handedness:String((token&&token.handedness)||'unknown'),
            t:now,
            /* Les deux rapports de pincement, la posture en C et la fermeture :
               tout ce dont les étapes ont besoin, déjà réduit à des nombres. */
            primaryRatio:pinchRatioFor(hand.landmarks,k,PINCH_CHANNEL.PRIMARY),
            secondaryRatio:pinchRatioFor(hand.landmarks,k,PINCH_CHANNEL.SECONDARY),
            cPose:cPoseScore(hand.landmarks,k,deps.options),
            closure:handClosure(hand.landmarks,k,deps.options),
            gapPalms:posture?posture.gapPalms:null,
            indexReachPalms:posture&&posture.reach?posture.reach.index:null,
            /* La paume en coordonnées normalisées de l'image : c'est elle qui
               convertit une mesure en paumes vers la fraction d'image que le
               profil persiste (`travelSlopNorm`). */
            palmNorm:posture?posture.palmPalms:null,
            // Position de la main dans l'**image**, 0..1, comme `reachNorm`.
            xNorm:tip&&Number.isFinite(tip.x)?tip.x:null,
            yNorm:tip&&Number.isFinite(tip.y)?tip.y:null,
            /* Brut contre filtré : c'est **là** que se lit le tremblement, et
               jamais sur `x`/`y` du jeton, qui se fige sur l'ancre pendant un
               pincement et ne dit alors plus rien de la main. */
            rawX:token?token.rawX:null,rawY:token?token.rawY:null,
            filteredX:token?token.filteredX:null,filteredY:token?token.filteredY:null,
            palmX:hand.palmX,palmY:hand.palmY,
            quality:hand.quality,stillness:hand.stillness,
            speedPxPerSec:token?token.speedPxPerSec:null,
          });
        }
        deps.onMeasure({now,aspect:k,viewport:deps.viewport(),hands:samples});
      }
      for(const click of out.clicks){
        deps.interaction.click(click);
        if(mine!==generation)return;  // le clic a éteint le mode test
      }
    }
    function tick(){
      frame=0;
      if(state!==STATE.SLEEP&&state!==STATE.ACTIVE)return;
      const mine=generation;
      try{
        const now=deps.now();
        if(state===STATE.SLEEP)watch(now);else interact(now,mine);
      /* Une erreur qui porte son propre code le garde : la surimpression
         n'est pas la caméra, et `tracking_failed` lui inventerait une cause.
         Sans code connu, l'image qui a levé est bien le suivi. */
      }catch(error){fail(error,(error&&MESSAGES[error.code])?error.code:'tracking_failed');return}
      if(mine===generation&&(state===STATE.SLEEP||state===STATE.ACTIVE))frame=deps.requestFrame(tick);
    }
    async function enable(){
      if(state===STATE.SLEEP||state===STATE.ACTIVE||state===STATE.STARTING)return state;
      const mine=++generation;
      state=STATE.STARTING;emit('starting');
      try{
        if(typeof deps.getUserMedia!=='function')throw Object.assign(new Error('getUserMedia indisponible'),{code:'camera_unsupported'});
        const loaded=await deps.createLandmarker();
        if(mine!==generation){try{loaded.close()}catch(_error){}return state}
        landmarker=loaded;
        const opened=await deps.getUserMedia({audio:false,video:{facingMode:'user',width:{ideal:640},height:{ideal:480}}});
        if(mine!==generation){stopStream(opened);return state}
        stream=opened;
        const attached=await deps.attachVideo(opened);
        if(mine!==generation){try{attached.dispose()}catch(_error){}return state}
        video=attached;
        for(const track of (opened.getVideoTracks?opened.getVideoTracks():[])){
          if(typeof track.addEventListener==='function')track.addEventListener('ended',()=>{if(mine===generation)fail(null,'camera_ended')});
        }
        deps.overlay.mount();
        /* Allumer, c'est guetter : l'interaction attend un réveil explicite. */
        toSleep('sleep');
        frame=deps.requestFrame(tick);
      }catch(error){if(mine===generation)fail(error)}
      return state;
    }
    /* Réveil volontaire (bouton, plus tard la voix) : depuis OFF il allume
       d'abord, ce qui peut échouer — l'état rendu le dit. */
    async function activate(){
      if(state===STATE.ACTIVE)return state;
      if(state!==STATE.SLEEP)await enable();
      if(state===STATE.SLEEP)toActive('active');
      return state;
    }
    /* Mise en veille volontaire : la caméra reste ouverte, le guetteur reprend. */
    function sleep(){
      if(state===STATE.ACTIVE)toSleep('sleep');
      return state;
    }
    function disable(){
      /* « Barehands arrêté — caméra libérée » ne vaut que si quelque chose
         était tenu. Depuis ERROR, ce toast écrasait « Caméra refusée » par une
         phrase fausse, et la cause réelle disparaissait de l'écran — c'est ce
         qu'`isEngagedState` exclut, et c'était tout l'objet du correctif.
         `isLiveState` en excluait un second, sans raison : **STARTING**.
         Décocher l'interrupteur pendant l'invite de permission annule un
         démarrage en vol — le cas que `isEngagedState` existe pour nommer — et
         n'émettait alors aucun toast du tout (`off` n'est pas notifié). Or la
         caméra est rendue de façon **asynchrone** ici : `track.stop()` n'arrive
         qu'une fois `getUserMedia` résolu. Sans un mot à l'écran, l'utilisateur
         annule et n'a aucune confirmation que la webcam s'est éteinte
         (RÈGLE ZÉRO). Une annulation est un arrêt voulu : elle se dit. */
      const wasOn=isEngagedState(state);
      generation+=1;teardown();state=STATE.OFF;
      emit(wasOn?'disabled':'off');
      return state;
    }
    /* **Slice 07 : les réglages atteignent le moteur.** `sleepTimeoutMs` était
       exposé, normalisé, persisté — et inerte, parce que le contrôleur ne
       lisait que la constante. Le voici branché, avec la seule forme qui ne
       mente pas : `options()` revalide **tous** les invariants de paire à
       chaque écriture, donc un réglage dangereux se refuse là où il arrive,
       pas à la prochaine construction. Un refus ici ne casse rien : l'appelant
       (l'écran) l'attrape et le dit, et le moteur garde ce qu'il avait.

       Ce qui n'est **pas** reconfigurable à chaud, et pourquoi : le traqueur
       d'identité, le filtre et le guetteur de réveil tiennent un état par main
       construit sur leurs seuils. Les rejouer en pleine session ferait sauter
       les identités de piste — la panne que la Slice 03 a passé une reprise à
       fermer. La calibration (Slice 08) les reprendra à froid. */
    function configure(partial){
      /* Les surcharges s'**accumulent**. Repartir de `deps.options` à chaque
         appel perdrait le réglage précédent dès que deux d'entre eux ne
         voyagent pas ensemble, et le second aurait l'air d'avoir défait le
         premier. `options()` lève **avant** qu'on garde quoi que ce soit : un
         réglage refusé ne laisse pas le moteur à moitié changé. */
      const merged={...liveOptions,...(partial||{})};
      const next=options(merged);
      liveOptions=merged;
      Object.assign(o,next);
      pinches.configure(merged);
      return {sleepTimeoutMs:o.sleepTimeoutMs,clickSlopPx:o.clickSlopPx,dragSlopPx:o.dragSlopPx};
    }
    /* Ce que le moteur applique **vraiment**, en lecture seule. Sans elle, un
       réglage porté jusqu'ici ne se distingue pas d'un réglage enregistré et
       jamais transmis : `configure` ne rend ses valeurs qu'à celui qui écrit,
       donc personne — ni l'écran, ni un test, ni la console — ne pouvait
       relire le moteur sans le reconfigurer au passage. Les trois que la
       Slice 07 pilote, plus les deux durées de cycle de vie qui participent
       aux mêmes paires dangereuses. */
      const readOptions=()=>Object.freeze({sleepTimeoutMs:o.sleepTimeoutMs,
      clickSlopPx:o.clickSlopPx,dragSlopPx:o.dragSlopPx,
      wakeHoldMs:o.wakeHoldMs,wakeIntervalMs:o.wakeIntervalMs,
      /* Ce que le **profil** applique, par main : sans cette ligne, « profil
         enregistré » et « profil appliqué » n'étaient pas distinguables, ce qui
         est exactement la panne que `options()` a été ajouté pour empêcher à la
         Slice 07 — et un profil par main est plus invisible encore, puisque
         rien à l'écran ne le montre. */
      hands:Object.freeze({
        left:pinches.handOptionsFor('left'),
        right:pinches.handOptionsFor('right'),
        unknown:pinches.handOptionsFor('unknown'),
      })});
    return {enable,activate,sleep,disable,state:()=>state,features:()=>features,configure,
      options:readOptions,
      /* Sortie sémantique du dernier instant : ce que la Slice 05 dessinera et
         ce que la Slice 06 liera à des actions. Vide hors interaction. */
      semantics:()=>semantics,tick};
  }

  return {LM,STATE,STATES,LIVE_STATES,isLiveState,isEngagedState,usableLandmarks,usableQuality,
    USED_LANDMARKS,SECONDARY_LANDMARKS,POSTURE_LANDMARKS,
    DEFAULTS,MESSAGES,pinchRatio,pinchRatioFor,cPoseScore,handQuality,handPosture,handClosure,toScreen,
    GESTURE,GESTURES,GESTURE_PHASE,GESTURE_SCOPE,GESTURE_RULES,POSTURE_GESTURES,gestureScope,
    gestureRuleFor:ruleFor,
    PINCH_CHANNEL,PINCH_CHANNELS,PINCH_PHASE,PINCH_INTENT,
    createPinchDetector,createWakeDetector,createPointerFilter,createStillness,
    createGestureEngine,createPinchChannel,createPinchIntentEngine,
    TARGET_REGION,TARGET_SIDES,targetBand,regionAt,targetRegionsOf,createTargetResolver,
    CONTENT_MODE,CONTENT_MODES,SELECTABLE_KINDS,createInteractionEngine,
    createHandTrackManager,createHandTracker,classifyError,createController};
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisBarehandsCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : caméra, surimpression, clics, onglet de réglages.
   -------------------------------------------------------------------------- */
/* **La levée reste, mais elle ne sort pas d'ici.** Ce bloc lit **directement**
   quatre globaux de page — `JarvisBarehandsContracts`, `JarvisBarehandsTarget`,
   `JarvisBarehandsCalibration` et `JarvisSceneInteract` — et c'est un choix
   assumé : un module de page absent est une erreur d'insertion, pas un état
   d'exécution, et une surface **gelée** ne se complète pas après coup. Mais la
   page servie n'a qu'**une seule** balise `<script>` : les huit modules Bare
   Hands, la scène, la timeline, le Test Lab et ~2500 lignes de logique de page
   y sont concaténés, donc une `ReferenceError` ici blanchissait tout ce qui
   suit. Rattrapée, la panne garde sa portée : Bare Hands ne s'installe pas, le
   reste de la page vit, et la console porte la cause. Le refus n'est pas
   adouci — il est confiné, comme dans l'enregistreur (§12), le tutoriel (§13)
   et le canal de commandes. */
try{
(function installJarvisBarehands(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const Core=JarvisBarehandsCore;
  /* Noms partagés avec la scène et la page (identité de pointeur, formes du
     DOM) : `control_center_barehands_contracts.js`, inséré juste avant. Le
     bloc pur ci-dessus ne le lit pas — les tests node le chargent seul. */
  const BH=JarvisBarehandsContracts;
  /* Collecte des candidates et aperçu de cible (Slice 05) :
     `control_center_barehands_target.js`, inséré juste avant. Sa lecture ici
     est **directe** et non conditionnelle : un module de page absent est une
     erreur d'insertion, pas un état d'exécution, et un aperçu qui se tairait
     poliment laisserait la décision 3 sans preuve qu'elle est tenue. */
  const TARGET=JarvisBarehandsTarget;
  /* Parcours de calibration et coque de surimpression (Slice 08) :
     `control_center_barehands_calibration.js`, inséré juste avant. Lu
     **directement**, pour la même raison que l'aperçu de cible : un module de
     page absent est une erreur d'insertion, pas un état d'exécution — et ici
     elle casserait plus tard et plus mal, `JarvisBarehands.calibrate` étant
     posé sur une surface **gelée** qu'on ne peut pas compléter après coup. */
  const CALIB=JarvisBarehandsCalibration;
  /* Parcours de tutoriel (Slice 09) : `control_center_barehands_tutorial.js`,
     inséré juste après la calibration, dont il **reprend la coque sans la
     modifier** (décision 26).

     Lu **défensivement**, contrairement aux contrats, à l'aperçu de cible et à
     la calibration, et c'est une différence assumée. Ces trois-là sont lus
     directement parce qu'un module absent y est une erreur d'insertion ; mais
     celui-ci peut aussi ne pas s'installer parce que **sa garde de forme a
     refusé** (liste blanche de l'observation, décision 32), et la page servie
     n'a qu'une seule balise `<script>` : une lecture directe d'un global
     absent lèverait ici et emporterait la scène, la timeline et le Test Lab.

     Absent, le tutoriel **refuse avec un code** au lieu de disparaître : c'est
     ce que la surface gelée ne permettrait pas si la porte elle-même
     manquait. `exitOverlay()`, elle, n'a pas besoin de ce module et continue
     de fermer une calibration. */
  const TUTO=(typeof JarvisBarehandsTutorial!=='undefined'&&JarvisBarehandsTutorial)
    ||window.JarvisBarehandsTutorial||null;
  if(!TUTO)
    console.error('[barehands] barehands.tutorial_unavailable '
      +JSON.stringify({error:'control_center_barehands_tutorial.js ne s’est pas installé : le tutoriel refusera, le reste de Bare Hands est intact'}));
  /* Enregistreur, rejeu et mesures (Slice 10, §12). Lu **défensivement** pour
     la même raison que le tutoriel : sa garde de forme peut refuser de
     l'installer, et la page servie n'a qu'une seule balise `<script>`. Absent,
     `record.start()` refuse avec un code et l'onglet le dit ; tout le reste de
     Bare Hands est intact, y compris les deux parcours. */
  const REC=(typeof JarvisBarehandsRecorder!=='undefined'&&JarvisBarehandsRecorder)
    ||window.JarvisBarehandsRecorder||null;
  if(!REC)
    console.error('[barehands] barehands.recorder_unavailable '
      +JSON.stringify({error:'control_center_barehands_recorder.js ne s’est pas installé : l’enregistrement de diagnostic refusera, le reste de Bare Hands est intact'}));
  /* Géométrie de la scène (`control_center_scene_interact.js`, inséré bien avant
     ce module) : `clampBox`, `MIN_SIZE`, `manipulateBox`, `rebaseManipulation`.
     Les décisions 18 et 19 y vivent, en **unités de scène**, et c'est là que les
     pixels de la fenêtre sont convertis. Lecture directe, comme celle de
     l'aperçu de cible : un module de page absent est une erreur d'insertion,
     pas un état d'exécution. */
  const GEOMETRY=JarvisSceneInteract;
  const API='/api/barehands';
  const PROFILE_API='/api/barehands/profile';
  const ASSET_BASE='/barehands/assets';
  const TAB_ID='experimental';
  /* Ce qu'un jeton « survole » : l'élément cliquable le plus proche. */
  const INTERACTIVE='button,a[href],input,select,textarea,label,summary,[role="button"],[role="tab"],[tabindex]:not([tabindex="-1"]),.choice,.acard,.toast';
  const ACCENT='var(--omega-accent,var(--accent,#6ee7ff))';

  const STYLE=`
#jarvisHands{position:fixed;inset:0;z-index:2147483000;pointer-events:none;overflow:hidden}
#jarvisHands .jh-token{position:absolute;left:0;top:0;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;
  color:${ACCENT};border:2px solid currentColor;background:color-mix(in srgb,currentColor 12%,transparent);
  box-shadow:0 0 16px color-mix(in srgb,currentColor 45%,transparent),inset 0 0 8px color-mix(in srgb,currentColor 25%,transparent);
  transition:width .12s ease,height .12s ease,margin .12s ease,background .12s ease;will-change:transform}
#jarvisHands .jh-token::after{content:'';position:absolute;left:50%;top:50%;width:6px;height:6px;margin:-3px 0 0 -3px;border-radius:50%;background:currentColor}
#jarvisHands .jh-ring{position:absolute;inset:-7px;border-radius:50%;
  background:conic-gradient(currentColor calc(var(--jh-progress,0) * 1turn),transparent 0);
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2px));
          mask:radial-gradient(farthest-side,transparent calc(100% - 3px),#000 calc(100% - 2px))}
#jarvisHands .jh-token.hover{width:46px;height:46px;margin:-23px 0 0 -23px;background:color-mix(in srgb,currentColor 24%,transparent)}
#jarvisHands .jh-token.pinching{border-style:dashed}
/* Main vue mais pas crue (qualité sous le plancher : hors cadre, trop loin,
   à peine apparue). Le jeton reste — la masquer dirait « je ne te vois pas »,
   ce qui est faux — mais il s'efface, parce que cette main-là ne tient pas la
   session éveillée et que l'écran doit le dire avant que la veille arrive. */
#jarvisHands .jh-token.faint{opacity:.42;border-style:dotted}
#jarvisHands .jh-token.pressed{width:24px;height:24px;margin:-12px 0 0 -12px;background:color-mix(in srgb,currentColor 60%,transparent)}
#jarvisHands .jh-token.clicked::before{content:'';position:absolute;inset:-3px;border-radius:50%;border:2px solid currentColor;animation:jhClick .38s ease-out forwards}
@keyframes jhClick{from{transform:scale(1);opacity:.95}to{transform:scale(2.6);opacity:0}}
#jarvisHands .jh-wake{position:absolute;left:0;top:0;width:76px;height:76px;margin:-38px 0 0 -38px;border-radius:50%;
  color:${ACCENT};opacity:0;transition:opacity .2s ease;
  background:conic-gradient(currentColor calc(var(--jh-progress,0) * 1turn),transparent 0);
  -webkit-mask:radial-gradient(farthest-side,transparent calc(100% - 5px),#000 calc(100% - 4px));
          mask:radial-gradient(farthest-side,transparent calc(100% - 5px),#000 calc(100% - 4px))}
#jarvisHands .jh-wake.seen{opacity:1}
#jarvisHands .jh-wake::before{content:'';position:absolute;inset:0;border-radius:50%;border:1px dashed color-mix(in srgb,currentColor 40%,transparent)}
#jarvisHands .jh-wake::after{content:'C';position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
  font:600 20px/1 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.1em;color:currentColor;opacity:.75}
#jarvisHands .jh-badge{position:fixed;left:18px;bottom:18px;padding:6px 10px;border-radius:999px;font:10px/1 ui-monospace,SFMono-Regular,Consolas,monospace;
  letter-spacing:.12em;color:${ACCENT};border:1px solid color-mix(in srgb,currentColor 35%,transparent);background:rgba(3,8,12,.55);backdrop-filter:blur(12px)}
/* Ce qui a été refusé, juste au-dessus de la pastille : un geste étouffé
   pendant une manipulation (contrat § 4, liste "suppressed") disparaissait sans
   un mot, ce qui est indiscernable d'un geste non reconnu — et c'est la
   première question qu'on se pose devant une main qui ne fait rien.
   (Pas d'accent grave dans ce commentaire : il vit dans un littéral gabarit.) */
#jarvisHands .jh-note{position:fixed;left:18px;bottom:46px;padding:5px 10px;border-radius:999px;
  font:10px/1.4 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.06em;
  color:var(--bh-feedback-zone,#ffd166);border:1px solid color-mix(in srgb,currentColor 32%,transparent);
  background:rgba(3,8,12,.62);backdrop-filter:blur(12px)}
/* Lecture de diagnostic (reglage "diagnostics", architecture §12) : ce que le
   suivi croit voir, par main, pendant qu'on s'en sert. Elle n'est PAS dans
   l'arbre quand le reglage est faux — un panneau transparent et un panneau
   absent ne se testent pas pareil. */
#jarvisHands .jh-diag{position:fixed;right:18px;bottom:18px;padding:7px 11px;border-radius:10px;max-width:46ch;
  font:10px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;letter-spacing:.04em;white-space:pre;
  color:${ACCENT};border:1px solid color-mix(in srgb,currentColor 30%,transparent);
  background:rgba(3,8,12,.66);backdrop-filter:blur(12px)}
/* Les sections que Barehands ajoute a l'onglet Experimental. Portee par une
   classe a nous, et non par "section + section", pour ne rien changer aux
   autres onglets de la meme fenetre. */
#modalContent .bh-section{border-top:1px solid var(--line);padding-top:22px;margin-top:18px}
#modalContent .bh-section [type=range]{accent-color:var(--accent);cursor:pointer}
#modalContent .bh-section [type=range]:disabled{cursor:default;opacity:.5}
#modalContent .bh-section button[role=radio]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
#modalContent .bh-section button[role=radio][disabled]{opacity:.45;cursor:not-allowed}
.jarvis-hand-hover{outline:2px solid ${ACCENT}!important;outline-offset:2px!important}
@media(prefers-reduced-motion:reduce){#jarvisHands .jh-token,#jarvisHands .jh-wake{transition:none}#jarvisHands .jh-token.clicked::before{animation:none}}`;

  /* La feuille ci-dessus écrit ses sélecteurs en clair : elle est lue telle
     quelle par les tests. Le contrat reste la source des noms, et un test
     (`test_barehands_contracts_js`) refuse qu'ils divergent. */
  function ensureStyle(){
    if(document.getElementById(BH.DOM.styleId))return;
    const style=document.createElement('style');
    style.id=BH.DOM.styleId;style.textContent=STYLE;
    document.head.appendChild(style);
  }

  /* Ce que dit la pastille. « MAINS · TEST » était à la fois le texte du
     montage et celui d'ACTIVE sans main : l'écran ne distinguait pas « prêt »
     d'« en interaction, mais je ne vois personne », alors que seule la veille
     avait son mot à elle. */
  const BADGE=Object.freeze({mounted:'MAINS · TEST',sleep:'MAINS · VEILLE',active:'MAINS · ACTIF'});

  /* Un jeton en lequel on a confiance. Une qualité **absente** vaut « personne
     n'a rien dit » et reste crue — la règle d'absence du contrat — pour que le
     jeton posé à la main depuis la console (`adapters.createOverlay`) ne se
     dessine pas pâle sans raison. C'est une note basse, pas une note
     manquante, qui efface un jeton. */
  const believed=token=>token.quality===undefined||token.quality===null
    ?true:Core.usableQuality(token.quality);

  function createOverlay(){
    let root=null,badge=null,wake=null,note=null,diag=null;
    const tokens=new Map();
    /* Un geste étouffé porte sa raison (contrat § 4) ; l'écran la porte aussi.
       Une raison inconnue n'est pas remplacée par une phrase générique : elle
       s'affiche telle quelle entre parenthèses, parce que le nom exact est la
       seule information que cette ligne existe pour transporter. */
    const noteFor=reason=>{
      if(!reason)return '';
      if(reason==='capture_active')return 'GESTE IGNORÉ · une main manipule';
      /* Refus de manipulation (Slice 06). Une prise que le contrat rejette ne
         fait rien à l'écran : sans un mot, c'est une main qui insiste sans
         effet, indiscernable d'une panne. Une raison **inconnue** s'affiche
         telle quelle, pour la même raison qu'un geste étouffé. */
      if(reason==='same_zone_rejected')return 'PRISE REFUSÉE · deux mains sur la même zone';
      if(reason==='axes_all_neutralized')return 'PRISE REFUSÉE · les deux mains s’annulent';
      if(reason==='frame_not_resizable')return 'PRISE REFUSÉE · cette forme ne se redimensionne pas';
      if(reason==='object_not_drawn')return 'PRISE REFUSÉE · objet absent de la scène';
      if(reason==='star_moves_with_one_hand')return 'PRISE REFUSÉE · cette forme se déplace à une main';
      if(reason==='viewport_unavailable')return 'PRISE REFUSÉE · la scène ne se mesure pas';
      if(reason==='side_held_twice')return 'PRISE REFUSÉE · deux mains sur le même côté';
      if(reason==='target_not_actionable')return 'PRISE REFUSÉE · ce contrôle est inactif';
      /* Slice 07, décision 25. Un outil qui ne s'applique pas à ce qu'on vise
         doit **le dire** : sinon la main se pose, rien ne se passe, et
         l'utilisateur lit une panne là où il y a une règle. Quel outil est
         actif est déjà à l'écran, dans la palette — cette ligne dit ce qui
         manque, pas ce qui est choisi. */
      if(reason==='tool_target_unsupported')return 'OUTIL INAPPLICABLE · cette cible ne s’y prête pas';
      if(reason==='tool_not_installed')return 'OUTIL INDISPONIBLE · aucun moteur derrière cet outil';
      return `GESTE IGNORÉ · ${String(reason)}`;
    };
    /* Réglage `diagnostics` (architecture §12). Le panneau est **créé et
       retiré**, jamais caché : un réglage appliqué et un réglage sans effet
       doivent être distinguables, et un élément absent est la seule forme
       qu'un test puisse affirmer (même règle que l'aperçu de cible). */
    let diagnostics=false;
    /* Le dernier lot dessiné. Allumer la lecture au milieu d'une session doit
       montrer ce que l'écran montre **déjà**, pas attendre l'image suivante
       pour dire quelque chose. */
    let lastTokens=[];
    const diagLine=token=>{
      const q=Number(token.quality),s=Number(token.speedPxPerSec),still=Number(token.stillness);
      return `#${String(token.id)}  q ${Number.isFinite(q)?q.toFixed(2):'—'}`
        +`  v ${Number.isFinite(s)?Math.round(s):'—'} px/s`
        +`  imm ${Number.isFinite(still)?still.toFixed(2):'—'}`
        +`  ${String(token.state||'—')}`;
    };
    /* `null` = « redessine ce que tu montrais déjà » : allumer la lecture au
       milieu d'une session doit montrer l'image en cours, pas attendre la
       suivante pour dire quelque chose. */
    function paintDiagnostics(list){
      if(Array.isArray(list))lastTokens=list;
      if(!root)return;
      if(!diagnostics){if(diag){diag.remove();diag=null}return}
      if(!diag){diag=document.createElement('div');diag.className=BH.DOM.diagClass;root.appendChild(diag)}
      diag.textContent=lastTokens.length
        ?lastTokens.map(diagLine).join('\n')
        :'aucune main suivie';
    }
    return {
      mount(){
        ensureStyle();
        if(root)return;
        root=document.createElement('div');root.id=BH.DOM.rootId;root.setAttribute('aria-hidden','true');
        badge=document.createElement('div');badge.className=BH.DOM.badgeClass;badge.textContent=BADGE.mounted;
        wake=document.createElement('div');wake.className=BH.DOM.wakeClass;
        note=document.createElement('div');note.className=BH.DOM.noteClass;
        note.style.display='none';
        root.appendChild(wake);root.appendChild(badge);root.appendChild(note);document.body.appendChild(root);
        paintDiagnostics(null);
      },
      unmount(){
        if(root)root.remove();
        root=null;badge=null;wake=null;note=null;diag=null;lastTokens=[];tokens.clear();
      },
      /* Réglage `diagnostics` : rendu **tout de suite**, comme l'aperçu de
         cible (décision 24) — attendre l'image suivante ferait d'un réglage
         appliqué et d'un réglage sans effet la même chose pendant une seconde. */
      showDiagnostics(value){
        diagnostics=value===true;
        paintDiagnostics(null);
        return diagnostics;
      },
      diagnosticsShown(){return diagnostics},
      /* Veille : ni jeton ni survol — un seul anneau de progression, visible
         seulement quand une main est vue, qui dit combien de la seconde de
         maintien est acquise (décision 5). `null` le range (retour en ACTIVE). */
      watch(state){
        if(!root||!wake)return;
        if(!state){wake.classList.remove('seen');badge.textContent=BADGE.active;return}
        this.render([]);
        wake.classList.toggle('seen',!!state.present);
        wake.style.transform=`translate3d(${Number(state.x||0).toFixed(1)}px,${Number(state.y||0).toFixed(1)}px,0)`;
        wake.style.setProperty('--jh-progress',Number(state.progress||0).toFixed(3));
        badge.textContent=state.present
          ?`${BADGE.sleep} ${Math.round(Number(state.progress||0)*100)}%`
          :BADGE.sleep;
      },
      /* `suppression` : la raison du premier geste étouffé de cette image, ou
         rien. Second argument plutôt que méthode à part pour que les doubles
         de test existants (`render(tokens){…}`) l'ignorent sans se casser. */
      render(list,suppression){
        if(!root)return;
        if(note){
          const text=noteFor(suppression);
          note.textContent=text;
          note.style.display=text?'block':'none';
        }
        const seen=new Set();
        let trusted=0;
        for(const token of list){
          if(believed(token))trusted+=1;
          seen.add(token.id);
          let el=tokens.get(token.id);
          if(!el){el=document.createElement('div');el.className=BH.DOM.tokenClass;
            const ring=document.createElement('span');ring.className=BH.DOM.ringClass;el.appendChild(ring);
            root.appendChild(el);tokens.set(token.id,el)}
          el.style.transform=`translate3d(${token.x.toFixed(1)}px,${token.y.toFixed(1)}px,0)`;
          el.style.setProperty('--jh-progress',token.progress.toFixed(3));
          el.classList.toggle('hover',!!token.hover);
          el.classList.toggle('pinching',token.state==='pinching');
          el.classList.toggle('pressed',token.state==='pressed');
          el.classList.toggle('faint',!believed(token));
          if(token.click){el.classList.remove('clicked');void el.offsetWidth;el.classList.add('clicked')}
        }
        for(const [id,el] of tokens)if(!seen.has(id)){el.remove();tokens.delete(id)}
        /* La pastille compte les mains **crues**, et annonce les autres à part
           (« 1/2 ») : « 2 » alors qu'une seule tient la session éveillée était
           un chiffre exact et une information fausse. */
        if(badge)badge.textContent=!list.length?BADGE.active
          :trusted===list.length?`MAINS · ${list.length}`
          :`MAINS · ${trusted}/${list.length}`;
        paintDiagnostics(list);
      },
    };
  }

  function createInteraction(){
    const hovered=new Map();
    /* Les éléments qui portent **effectivement** le contour hérité, et rien
       d'autre. `hovered` dit « quelle main est au-dessus de quoi » (chemin du
       clic) ; ceci dit « qu'est-ce qui est souligné à l'écran »
       (présentation). Les deux se confondaient, et c'est ainsi que le contour
       suivait une main simplement suivie — voir `paintHover`. */
    let outlined=new Set();
    /* Résolution de cible et aperçu (Slice 05). La règle de recouvrement vient
       du contrat : le bloc pur ne la réinvente pas, il la reçoit. */
    const resolver=Core.createTargetResolver({pickRegion:BH.pickRegion});
    const preview=TARGET.createTargetPreview();
    /* D'où vient l'intention. Le contrôleur range la sortie des moteurs
       **avant** d'appeler `hover`, donc lire ses contacts ici, c'est lire ceux
       de l'image en cours. Non branchée, la source ne rend rien et l'aperçu
       n'existe pas — ce qui est exactement le comportement voulu hors
       interaction. */
    let contactsOf=null;
    /* Les événements de contact de l'image (Slice 04) : c'est eux qui ouvrent et
       ferment une capture, là où `contactsOf` donne l'état et l'intention. */
    let pinchOf=null;
    /* Qui veut savoir qu'une image d'interaction vient de se terminer
       (Slice 09, `afterFrame`). `null` hors parcours, donc rien n'est appelé. */
    let frameSink=null;
    /* Décision 24 : l'aperçu se règle. Le réglage lui-même appartient à la
       Slice 07 ; ce qui est à nous, c'est l'interrupteur qu'elle branchera.
       Il éteint le **dessin**, pas la résolution : la Slice 06 continue de
       recevoir sa cible, sans quoi couper une aide visuelle couperait aussi
       la manipulation. */
    let previewOn=true;
    /* Assistance (contrat § 9) : 0,5 par défaut, ce qui vaut exactement
       `targetAssistPx`. Même partage — la Slice 07 branche, nous exposons. */
    let assistance=.5;
    let resolved=[];
    /* Nom et arrondi de la cible de chaque main : ce qui n'est pas de la
       géométrie et que le résolveur ne transporte donc pas. */
    const decor=new Map();
    /* Identité de pointeur par main (contrat Slice 01, constat F2). La fente 0
       vaut `BH.POINTER_ID_BASE` : une main seule envoie exactement les mêmes
       événements qu'avant. La seconde main a enfin le sien, au lieu que deux
       mains parlent sous un identifiant unique. */
    const slots=BH.createSlotAllocator(BH.MAX_HANDS);
    let warnedUnslotted=false;
    /* Identité utilisable d'une main, ou `null`. Le contrat **refuse** une
       identité vide (`trackId`), et il a raison : une fente de pointeur
       appartient à une main identifiée. Mais ce refus arrive ici **par jeton et
       par image**, dans le `try` de la boucle, où il se convertit en
       `tracking_failed` : session terminée, caméra rendue, toast de 9 s — pour
       un jeton sans identité. C'est la règle que la reprise de la Slice 02 a
       posée côté points (`usableLandmarks`) et laissée ouverte côté identité :
       **une image malformée se saute, elle n'arrête rien**. La main reste donc
       suivie et dessinée, simplement sans pointeur — et `click` le dit une fois
       à la console au lieu de la faire passer pour inerte. */
    const handKey=id=>{
      if(id===undefined||id===null)return null;
      const key=String(id).trim();
      return key||null;
    };
    const identityOf=id=>{
      const key=handKey(id);
      if(key===null)return null;
      const slot=slots.slot(key);
      return slot===null?null:{pointerId:BH.pointerIdForSlot(slot),isPrimary:slot===0};
    };
    function targetAt(x,y){
      const el=document.elementFromPoint(x,y);
      return el&&!el.closest(BH.DOM.rootSelector)?el:null;
    }
    function pointer(type,el,x,y,buttons,identity,button){
      const init={bubbles:true,cancelable:true,composed:true,view:window,clientX:x,clientY:y,
        button:Number(button)||0,buttons};
      if(type.startsWith('pointer')&&typeof PointerEvent==='function')
        el.dispatchEvent(new PointerEvent(type,{...init,pointerId:identity.pointerId,pointerType:BH.POINTER_TYPE,isPrimary:identity.isPrimary}));
      else if(!type.startsWith('pointer'))el.dispatchEvent(new MouseEvent(type,init));
    }
    function release(id){
      const previous=hovered.get(id);
      hovered.delete(id);
      const identity=identityOf(id);
      /* Le contour ne se retire plus ici : il a un seul propriétaire,
         `paintHover`, qui le repose à chaque image d'après l'intention. Deux
         endroits qui posent et retirent la même classe se seraient marchés
         dessus dès que deux mains visent le même élément. Les événements, eux,
         sont inchangés — c'est le chemin du clic. */
      if(previous&&identity&&![...hovered.values()].includes(previous)){
        pointer('pointerout',previous,0,0,0,identity);pointer('mouseout',previous,0,0,0,identity);
      }
    }
    /* Qui **veut** quelque chose, à cet instant : une main qui pince ou qui
       approche. Même définition que celle du résolveur (décision 3), lue de la
       même source, pour qu'« intention » veuille dire la même chose à l'écran
       et dans la géométrie. */
    function intendingHands(){
      const out=new Set();
      for(const contact of (typeof contactsOf==='function'?contactsOf():null)||[])
        if(contact&&(contact.state==='pinching'||contact.state==='pressed'))
          out.add(String(contact.handTrackId));
      return out;
    }
    /* Le contour hérité (`jarvis-hand-hover`), **décision 3 enfin tenue à
       l'écran**.

       Il s'ajoutait pour tout jeton suivi survolant un élément interactif :
       pas de pincement, pas de geste, aucune intention — donc une main qui
       traverse la page entourait chaque bouton au passage, ce qui est
       exactement le curseur permanent que la décision 3 refuse. La preuve
       `previews().length==0` ne disait rien de lui : elle ne parle que du
       nouvel aperçu.

       Deux conditions, et la seconde est de la décision 23 : la main a une
       intention, **et** l'aperçu de cible ne dessine pas déjà cet élément-là.
       Le contour porte la couleur d'accent de la surimpression ; posé autour
       d'un objet que l'aperçu entoure déjà en bleu, en jaune ou en rouge, il
       ajouterait une quatrième couleur sans sens à une règle où la couleur
       *est* le sens. Quand l'aperçu est éteint (décision 24), le chemin de
       clic hérité garde ainsi son seul repère, sous intention.

       Ce qui n'est pas touché : la mesure. `hovered`, les fentes, les
       `pointerover`/`mouseover` et les clics sont ceux d'avant, au mot près.
       C'est de la présentation. */
    function paintHover(){
      const intent=intendingHands();
      const previewed=new Set();
      if(previewOn)for(const target of resolved){
        const look=decor.get(`${target.handTrackId}|${target.channel}`);
        if(look&&look.element)previewed.add(look.element);
      }
      const wanted=new Set();
      for(const [id,el] of hovered)
        if(el&&intent.has(String(id))&&!previewed.has(el))wanted.add(el);
      for(const el of outlined)if(!wanted.has(el))el.classList.remove(BH.DOM.hoverClass);
      for(const el of wanted)if(!outlined.has(el))el.classList.add(BH.DOM.hoverClass);
      outlined=wanted;
    }
    /* Plus rien de souligné : l'extinction et la veille ne laissent pas un
       contour derrière elles. */
    function clearOutlines(){
      for(const el of outlined)el.classList.remove(BH.DOM.hoverClass);
      outlined=new Set();
    }
    /* Une image de résolution de cible.

       **Décision 3 tenue ici, et visible dans l'arbre** : la collecte ne part
       que pour une main qui pince ou approche, et une image sans intention
       rend une liste vide, que l'aperçu traduit en *aucun élément*. Il n'y a
       donc jamais de curseur qui reste — et le coût de la lecture du DOM n'est
       jamais payé par une session au repos.

       Une main par appel : `collect` cite en tête la candidate qui est **au
       dessus** au point visé (`elementFromPoint`), et ce classement n'a de
       sens que pour ce point-là. Deux mains mélangées dans une seule liste
       auraient hérité du dessus de l'autre. */
    function resolveTargets(tokens){
      const contacts=typeof contactsOf==='function'?contactsOf():null;
      const byId=new Map((tokens||[]).map(token=>[String(token.id),token]));
      const out=[];
      for(const contact of contacts||[]){
        const token=byId.get(String(contact&&contact.handTrackId));
        if(!token)continue;
        const wanted=contact.state==='pinching'||contact.state==='pressed';
        /* On vise avec `token.x`/`token.y` — le point d'**affichage**, donc
           l'ancre figée pendant un pincement — et non `filteredX`/`filteredY`.
           Deux raisons, et la seconde est décisive :

           - le bout de l'index parcourt un demi-palme en se refermant sans que
             la main ait bougé (leçon des Slices 03 et 04) : suivre le point
             filtré ferait dériver l'aperçu du seul fait de la fermeture ;
           - le **jeton** se fige déjà là, et l'utilisateur le voit. Un aperçu
             calculé ailleurs que le point dessiné donnerait deux réponses à
             l'écran pour un seul geste, et c'est l'aperçu qui aurait tort :
             c'est le jeton que l'utilisateur croit. */
        const hand={handTrackId:contact.handTrackId,channel:contact.channel,
          state:contact.state,x:token.x,y:token.y,assistance};
        /* Sans intention on passe quand même la main au résolveur : c'est
           ainsi qu'il **oublie** ce qu'elle tenait, plutôt que de le garder
           jusqu'à la grâce. */
        const candidates=wanted
          ?TARGET.collect({x:token.x,y:token.y},resolver.reach(assistance)):[];
        for(const target of resolver.update({now:performance.now(),candidates,hands:[hand]})){
          /* Le nom et l'arrondi ne sont pas de la géométrie : ils ne traversent
             pas le résolveur, on les relit de la candidate par son renvoi.
             Une cible **figée** n'a plus de candidate sous la main — la main a
             bougé, la collecte ne la voit plus — donc son apparence est gardée
             telle qu'elle était à la descente, comme le descripteur lui-même. */
          const key=`${target.handTrackId}|${target.channel}`;
          let look=decor.get(key);
          if(!target.locked||!look){
            const source=target.ref===null?null:candidates[target.ref];
            /* L'élément voyage avec l'apparence et pour la même raison : il
               n'est pas de la géométrie, il ne traverse pas le contrat (§ 6),
               et une cible figée n'a plus de candidate où le relire. C'est la
               sortie de compatibilité DOM de la Slice 06 qui le consomme. */
            look={name:source?source.name:'',radiusPx:source?source.radiusPx:0,
              element:source?source.element:null};
            decor.set(key,look);
          }
          out.push({...target,
            feedback:BH.feedbackRole(target.region,target.channel),
            name:look.name,radiusPx:look.radiusPx});
        }
      }
      const live=new Set(out.map(target=>`${target.handTrackId}|${target.channel}`));
      for(const key of [...decor.keys()])if(!live.has(key))decor.delete(key);
      resolved=out;
      preview.render(previewOn?out:[]);
    }

    /* ------------------------------------------------ Slice 06 : captures

       Le moteur est **pur** et vit dans le bloc ci-dessus ; ce qui suit est ce
       que seule la page peut faire : tenir le cadre de la scène (monde) et
       rendre des événements du DOM pour le contenu (compatibilité). */

    /* L'élément de chaque cible **figée**, gardé à part de `decor` : `decor`
       est élagué sur ce que le résolveur rend encore, et une capture qui se
       ferme n'a plus de cible — son `drag_end` et son clic arriveraient alors
       sans élément. C'est le relâchement du moteur qui l'élague, pas l'image. */
    const elements=new Map();
    const elementFor=target=>{
      if(!target)return null;
      const entry=elements.get(`${target.handTrackId}|${target.channel}`);
      return entry||null;
    };
    const scrollHost=el=>{
      let node=el;
      while(node&&node.nodeType===1){
        const canScroll=(node.scrollHeight-node.clientHeight>1)||(node.scrollWidth-node.clientWidth>1);
        if(canScroll){
          const style=typeof getComputedStyle==='function'?getComputedStyle(node):null;
          const overflow=style?`${style.overflowY} ${style.overflowX}`:'auto';
          if(/auto|scroll|overlay/.test(overflow))return node;
        }
        node=node.parentElement;
      }
      return null;
    };

    /* Le monde de la scène : `window.JarvisScene.frames`, publié par
       `control_center_scene_page.js`. Il est lu **à l'appel** et non au
       chargement, parce que la page de scène est insérée après ce module
       (ordre `contracts → target → barehands → scene page`) — et parce qu'elle
       reste inerte tant que `scene.enabled` est faux, auquel cas il n'y a
       simplement pas de cadre à tenir. */
    let warnedNoScene=false;
    const frames=()=>{
      const scene=window.JarvisScene;
      const api=scene&&scene.frames;
      if(!api&&!warnedNoScene){warnedNoScene=true;
        console.warn('[barehands] la scène n’expose pas de cadres manipulables : aucun objet ne se déplacera')}
      return api||null;
    };
    const sceneCall=(name,fallback,...args)=>{
      const api=frames();
      if(!api||typeof api[name]!=='function')return fallback;
      try{return api[name](...args)}
      catch(error){console.warn('[barehands] scène :',name,error);return fallback}
    };
    const world={
      begin:objectId=>sceneCall('begin',null,objectId),
      preview:(objectId,box)=>sceneCall('preview',null,objectId,box),
      commit:(objectId,box,mode)=>sceneCall('commit',null,objectId,box,mode),
      cancel:objectId=>sceneCall('cancel',null,objectId),
      viewport:()=>sceneCall('viewport',null),
    };

    /* Sortie de **compatibilité** DOM (architecture §7). Le modèle de
       manipulation n'est pas fait d'événements de pointeur synthétiques : ceux
       qui restent servent le **contenu**, là où la page d'aujourd'hui écoute
       déjà une souris.

       Ce qui n'y est pas, et pourquoi : le **clic** reste au chemin hérité
       (`createPinchDetector`), prouvé identique sur 336 000 pas — l'émettre ici
       aussi enverrait deux clics pour un pincement ; et `move`/`resize` n'ont
       pas d'équivalent DOM, c'est la scène qui les applique. */
    const dom={
      scrollable(target){
        const el=elementFor(target);
        return !!el&&!!scrollHost(el);
      },
      emit(event,context){
        const el=elementFor(context&&context.target);
        const identity=identityOf(event.handTrackId);
        if(!el||!identity)return;
        const x=event.x,y=event.y;
        if(event.type===BH.INTERACTION.CONTEXT){
          /* Décision 21 : le clic droit est un doigt. Le menu contextuel de la
             page l'écoute par `contextmenu`, comme pour une souris. */
          pointer('contextmenu',el,x,y,0,identity,2);
          return;
        }
        if(event.type===BH.INTERACTION.DRAG_START){
          pointer('pointerdown',el,x,y,1,identity);pointer('mousedown',el,x,y,1,identity);
          return;
        }
        if(event.type===BH.INTERACTION.DRAG_MOVE){
          pointer('pointermove',el,x,y,1,identity);pointer('mousemove',el,x,y,1,identity);
          return;
        }
        if(event.type===BH.INTERACTION.DRAG_END){
          /* La perte donne une annulation, jamais un relâchement : un `pointerup`
             déclencherait l'action que l'arrêt vient d'interrompre. */
          if(context&&context.cancelled)pointer('pointercancel',el,x,y,0,identity);
          else{pointer('pointerup',el,x,y,0,identity);pointer('mouseup',el,x,y,0,identity)}
          return;
        }
        if(event.type===BH.INTERACTION.SCROLL){
          const host=scrollHost(el);
          if(!host)return;
          /* Un défilement synthétique ne défile pas : un `wheel` non approuvé
             est ignoré par le navigateur. On défile donc **pour de vrai** — la
             main tire le contenu — et l'événement part quand même, pour qui
             l'écoute. */
          host.scrollTop-=event.dy;host.scrollLeft-=event.dx;
          if(typeof WheelEvent==='function')
            host.dispatchEvent(new WheelEvent('wheel',{bubbles:true,cancelable:true,composed:true,
              clientX:x,clientY:y,deltaX:-event.dx,deltaY:-event.dy}));
          return;
        }
        if(event.type===BH.INTERACTION.SELECT){
          /* Sélectionner, c'est désigner : un champ prend le focus et se
             sélectionne, le reste se contente de l'événement sémantique. La
             sélection de texte fine appartient à un outil (contrat § 8), pas à
             une main nue en V1. */
          if(typeof el.focus==='function'){try{el.focus({preventScroll:true})}catch(_error){}}
          if(typeof el.select==='function'){try{el.select()}catch(_error){}}
        }
      },
    };

    const engine=Core.createInteractionEngine({
      contracts:BH,geometry:GEOMETRY,world,dom,
      slotOf:id=>{const key=handKey(id);return key===null?null:slots.slot(key)},
      /* Le contact est rendu : la cible figée et son élément le sont aussi. */
      onRelease:(handTrackId,channel)=>{
        resolver.release(handTrackId,channel);
        elements.delete(`${handTrackId}|${channel}`);
      },
    });
    let interactions=[];

    /* Une image du moteur de captures, après la résolution de cible : elle lit
       les contacts et les événements de la Slice 04, et les cibles **figées** de
       la Slice 05. Les deux dans le même instant, comme le survol. */
    function runCaptures(tokens){
      for(const target of resolved){
        if(!target.locked)continue;
        const key=`${target.handTrackId}|${target.channel}`;
        if(elements.has(key))continue;
        const look=decor.get(key);
        if(look&&look.element)elements.set(key,look.element);
      }
      const step=engine.update({now:performance.now(),tokens,
        targets:resolved,
        contacts:typeof contactsOf==='function'?contactsOf()||[]:[],
        events:typeof pinchOf==='function'?pinchOf()||[]:[]});
      interactions=step.interactions;
      return step;
    }

    return {
      hover(tokens){
        const live=new Set();
        for(const token of tokens){
          live.add(token.id);
          const identity=identityOf(token.id);
          const raw=targetAt(token.x,token.y);
          const el=raw&&raw.closest(INTERACTIVE);
          /* Sans fente, la main est suivie mais ne pointe pas : pas d'anneau
             de survol non plus, sans quoi la surimpression promet un clic que
             rien n'enverra. Inatteignable tant que `numHands` vaut
             `MAX_HANDS` ; vrai dès que l'un des deux monte. */
          token.hover=!!el&&!!identity;
          if(hovered.get(token.id)===el)continue;
          release(token.id);
          if(el&&identity){
            hovered.set(token.id,el);
            pointer('pointerover',el,token.x,token.y,0,identity);pointer('mouseover',el,token.x,token.y,0,identity);
          }
        }
        for(const id of [...hovered.keys()])if(!live.has(id))release(id);
        // Une main partie rend sa fente : deux mains qui vont et viennent en
        // retrouvent toujours une. Les identités vides sont écartées avant
        // d'arriver au contrat, qui les refuserait — et ce refus-là tomberait
        // dans la boucle d'images, où il vaut la fin de la session.
        slots.retain([...live].map(handKey).filter(key=>key!==null));
        /* La cible se résout sur la **même image** que le survol et sur les
           mêmes jetons : deux lectures du même instant donneraient deux
           réponses pour un seul geste. */
        resolveTargets(tokens);
        /* Le contour hérité se repose **après** la résolution : il a besoin de
           savoir ce que l'aperçu dessine déjà (décision 23). */
        paintHover();
        /* Puis ce que les mains **tiennent** (Slice 06). Après la résolution,
           jamais avant : une capture s'ouvre sur la cible figée de cette
           image-là. */
        runCaptures(tokens);
        /* L'image est finie et ses interactions sont rangées : c'est
           **maintenant** qu'un parcours peut les constater (Slice 09). Une
           levée du lecteur ne doit pas arrêter le suivi — un refus codé dans
           la boucle d'images vaut la fin de la session (leçon des Slices 02
           et 04) — donc elle se dit et se saute. */
        if(frameSink){
          try{frameSink()}
          catch(error){console.warn('[barehands] lecteur de fin d’image',error)}
        }
      },
      /* Un vrai clic : la séquence qu'enverrait une souris, sur l'élément exact
         sous le jeton (les écouteurs, labels, cases et liens réagissent). */
      click({id,x,y}){
        /* **Décision 13.** Une main qui tient un cadre ne clique pas dessus en
           le relâchant. Le détecteur hérité (`createPinchDetector`) rend un clic
           à **chaque** relâchement, glissement compris : sans cette porte, tout
           déplacement se terminait par un clic sur l'objet qu'on venait de
           poser — et, sur une étoile déjà sélectionnée, par l'ouverture de son
           menu. Le détecteur, lui, n'est pas touché : c'est la **livraison** du
           clic qui attend, pas sa mesure. */
        if(engine.drivenHands().includes(String(id)))return false;
        const raw=targetAt(x,y);
        const identity=identityOf(id);
        /* Deux échecs différents rendaient le même `false` muet. « Rien sous
           le jeton » est la normale ; « cette main n'a pas de fente » est une
           panne, et elle se dit au moins une fois à la console plutôt que de
           faire passer une main pour inerte. */
        if(!identity){
          if(!warnedUnslotted){warnedUnslotted=true;
            console.warn('[barehands] main sans fente de pointeur : son clic est perdu',id)}
          return false;
        }
        if(!raw)return false;
        pointer('pointerdown',raw,x,y,1,identity);pointer('mousedown',raw,x,y,1,identity);
        const focusable=raw.closest('button,a[href],input,select,textarea,summary,[tabindex]');
        if(focusable&&typeof focusable.focus==='function'){try{focusable.focus({preventScroll:true})}catch(_error){}}
        pointer('pointerup',raw,x,y,0,identity);pointer('mouseup',raw,x,y,0,identity);pointer('click',raw,x,y,0,identity);
        return true;
      },
      /* Fente de pointeur d'une main, pour qui publie un événement de contact
         (Slice 04) : le bloc pur ne connaît pas les fentes, et une fente
         inventée volerait un `pointerId` à l'autre main. `null` = pas de
         fente, ce que `createPinchEvent` accepte. */
      slotOf(id){const key=handKey(id);return key===null?null:slots.slot(key)},
      /* Où lire l'intention. Le contrôleur range la sortie des moteurs avant
         d'appeler `hover`, donc cette source rend bien les contacts de l'image
         en cours (Slice 04 : `contacts[].state`). */
      readContacts(fn){contactsOf=typeof fn==='function'?fn:null},
      /* Même couture pour les **événements** de contact : ce sont eux qui font
         descendre et remonter une capture (Slice 04 : `pinch().events`). */
      readPinch(fn){pinchOf=typeof fn==='function'?fn:null},
      /* **La fin d'une image d'interaction** (Slice 09). Troisième couture du
         même genre, et elle existe parce que `interactions()` ne décrit qu'un
         **instant** : elle est vidée à chaque image, donc un lecteur qui
         n'échantillonne que toutes les 500 ms rate quasiment tous les clics.
         Le tutoriel doit constater des gestes ; il lui faut donc la cadence
         des images, pas celle d'une minuterie.

         Appelée à la fin de `hover`, où `runCaptures` vient de ranger les
         interactions de l'image — au même endroit et pour la même raison que
         `contactsOf` est lu là. Non branchée, elle ne coûte rien : hors
         parcours le test `typeof` échoue et rien n'est appelé, exactement
         comme `deps.onMeasure` côté contrôleur. Elle ne transporte **aucun**
         argument : ce qu'un lecteur a le droit de constater, il va le chercher
         par les portes publiques. */
      afterFrame(fn){
        /* Sans argument, elle **se relit** — même idiome que `targetPreview`
           sur la surface. Sans cette lecture, « la couture est déposée à la
           sortie » et « elle reste branchée pour toute la session » s'écrivent
           pareil : un parcours fini laisserait une fermeture vivante appelée à
           chaque image, pour rien, et rien ne le dirait. */
        if(fn===undefined)return !!frameSink;
        frameSink=typeof fn==='function'?fn:null;
        return !!frameSink;
      },
      /* Décision 24. Éteindre l'aperçu retire ce qui est dessiné **tout de
         suite** : laisser le dernier cadre à l'écran jusqu'à la prochaine
         image ferait d'un réglage appliqué et d'un réglage sans effet la même
         chose pendant une seconde. */
      showTargets(value){
        previewOn=value!==false;
        if(!previewOn)preview.clear();
        return previewOn;
      },
      /* Lisible, pas seulement écrivable : un réglage qu'on ne peut que poser
         ne se distingue pas d'un réglage qu'on n'a pas posé. */
      targetsShown(){return previewOn},
      /* Décision 25. L'outil appartient au moteur de captures — c'est lui qui
         décide ce qu'une prise de corps veut dire. La page ne fait que le lui
         passer : une seconde mémoire d'outil ici donnerait deux réponses à la
         même question, dont une seule serait lue. */
      setTool(value){return engine.setTool(value)},
      tool(){return engine.tool()},
      /* Assistance des réglages (contrat § 9), bornée par le contrat lui-même
         si la Slice 07 la fait passer par `normalizeSettings`. */
      setAssistance(value){
        const n=Number(value);
        if(Number.isFinite(n))assistance=Math.max(0,Math.min(1,n));
        return assistance;
      },
      /* Ce que la Slice 06 consommera : une cible par main **et par canal**,
         figée dès la descente. Vide hors intention (décision 3). */
      targets(){return resolved},
      /* Ce que les mains tiennent et ce qu'elles produisent (Slice 06). */
      captures(){return engine.capturedHands()},
      interactions(){return interactions},
      /* RÈGLE ZÉRO : une manipulation refusée (deux mains sur la même prise,
         axes neutralisés, objet sorti du dessin) doit se voir. La raison remonte
         à la surimpression, telle quelle, comme celle d'un geste étouffé. */
      refusal(){const list=engine.refusals();return list.length?list[0].reason:''},
      clear(){
        clearOutlines();
        for(const id of [...hovered.keys()])release(id);
        /* Tout ce qui est tenu est **annulé**, jamais relâché : aucune géométrie
           n'est validée par une extinction ou un retour en veille. */
        engine.cancelAll(typeof performance!=='undefined'?performance.now():0);
        engine.reset();
        slots.clear();resolver.reset();preview.clear();decor.clear();elements.clear();
        resolved=[];interactions=[];
      },
    };
  }

  function attachVideo(stream){
    return new Promise((resolve,reject)=>{
      const el=document.createElement('video');
      el.muted=true;el.playsInline=true;el.autoplay=true;el.setAttribute('aria-hidden','true');
      el.style.cssText='position:fixed;left:-8px;top:-8px;width:4px;height:4px;opacity:0;pointer-events:none';
      const handle={element:el,get width(){return el.videoWidth||640},get height(){return el.videoHeight||480},
        currentTime:()=>el.currentTime,dispose(){try{el.pause()}catch(_error){}el.srcObject=null;el.remove()}};
      const timer=setTimeout(()=>{handle.dispose();reject(Object.assign(new Error('La vidéo ne démarre pas'),{code:'camera_busy'}))},10000);
      el.addEventListener('loadeddata',()=>{clearTimeout(timer);el.play().catch(()=>{});resolve(handle)},{once:true});
      el.srcObject=stream;document.body.appendChild(el);
    });
  }

  let visionModule=null;
  async function createLandmarker(){
    const state=await api(API);
    applyAssets(state);
    if(!state.assets||!state.assets.installed)throw Object.assign(new Error('assets manquants'),{code:'assets_missing'});
    let mod;
    try{
      if(!visionModule)visionModule=import(`${ASSET_BASE}/vision_bundle.mjs`);
      mod=await visionModule;
    }catch(error){visionModule=null;throw Object.assign(new Error(String(error&&error.message||error)),{code:'assets_missing'})}
    const fileset=await mod.FilesetResolver.forVisionTasks(`${ASSET_BASE}/wasm`);
    const settings=delegate=>({
      baseOptions:{modelAssetPath:`${ASSET_BASE}/models/hand_landmarker.task`,delegate},
      runningMode:'VIDEO',numHands:2,minHandDetectionConfidence:.6,minHandPresenceConfidence:.5,minTrackingConfidence:.5,
    });
    try{return await mod.HandLandmarker.createFromOptions(fileset,settings('GPU'))}
    catch(_gpu){return await mod.HandLandmarker.createFromOptions(fileset,settings('CPU'))}
  }

  const view={enabled:false,assets:null,busy:false,error:'',
    /* Slice 07. Les réglages tels que le serveur les a rendus, normalisés par
       le contrat. `enabled` en est un : il garde son champ à part parce que
       tout le reste de ce fichier le lit déjà là, et les deux sont tenus
       ensemble par `applyServerState`. */
    settings:BH.normalizeSettings(),
    /* La dernière trace de diagnostic envoyée, ou l'échec de son envoi
       (Slice 10). `null` tant que personne n'a enregistré, pour que « rien
       n'a été enregistré » ne se dessine pas comme « tout va bien ». */
    trace:null,
    /* Ce que le serveur a **lu** dans le fichier, par opposition à ce qu'il
       écrit : `null` tant qu'on ne lui a pas parlé, pour que « on ne sait pas
       encore » ne se dessine pas comme « tout va bien ». */
    stored:null,
    /* Le profil de calibration (Slice 08). `null` tant qu'on ne l'a pas relu :
       « pas encore demandé » et « rien de calibré » ne se dessinent pas pareil. */
    profile:null,profileError:'',
    /* La **dernière commande vocale**, telle que le canal l'a constatée
       (Slice 09, Issue « une commande vocale ne se voit pas à l'écran »).
       `null` tant qu'aucune n'est passée : « jamais » et « la dernière a
       échoué » ne se dessinent pas pareil. */
    voice:null,
    status:{state:'off',code:'off',title:Core.MESSAGES.off.title,message:Core.MESSAGES.off.detail,error:null}};

  /* Une seule instance, nommée : la surimpression et l'interaction sont des
     dépendances du contrôleur, mais l'interaction est aussi ce qui détient
     l'allocateur de fentes, que la publication des contacts (Slice 04) doit
     interroger. */
  const overlayView=createOverlay(),interactionView=createInteraction();

  const controllerDeps={
    getUserMedia:navigator.mediaDevices&&typeof navigator.mediaDevices.getUserMedia==='function'
      ?constraints=>navigator.mediaDevices.getUserMedia(constraints):null,
    /* Les durées du cycle de vie viennent du contrat, pas des défauts du
       moteur : un seul endroit les fixe (décisions 5, 7). La cadence du
       guetteur les rejoint — c'est elle que l'onglet promet « 5 images par
       seconde », et une promesse affichée ne se règle pas ailleurs. */
    options:{sleepTimeoutMs:BH.SLEEP_TIMEOUT_MS,wakeHoldMs:BH.WAKE_HOLD_MS,
      wakeIntervalMs:BH.WAKE_INTERVAL_MS},
    createLandmarker,attachVideo,
    overlay:overlayView,interaction:interactionView,
    /* La couture de la Slice 04, branchée par la Slice 06 : les mains qui
       tiennent une capture. Un geste global se tait pendant qu'une main
       manipule (contrat § 4, `GESTURE_RULES`), sauf la main ouverte — une
       manipulation qu'on ne peut pas abandonner serait un piège. */
    captures:()=>interactionView.captures(),
    /* **Le profil de calibration entre par ici** (Slice 08, décision 28). Le
       moteur ne sait pas ce qu'est un profil : il demande « quelles surcharges
       pour cette main, sur ce canal », et c'est le contrat qui répond.

       Une hystérésis est rendue **par paire ou pas du tout** : mélanger un
       seuil mesuré et un défaut du moteur peut inverser `press < release`, que
       `options()` refuse à la construction — une calibration partielle
       (décision 31) ferait alors tomber le moteur au lieu de retomber sur ses
       défauts. La même règle est écrite côté serveur, où elle porte un code. */
    handOverrides:(handedness,channel)=>{
      const profile=view.profile;
      if(!profile||!profile.calibrated)return null;
      const press=channel===BH.PINCH_CHANNEL.SECONDARY?'secondaryPressRatio':'pressRatio';
      const release=channel===BH.PINCH_CHANNEL.SECONDARY?'secondaryReleaseRatio':'releaseRatio';
      const low=BH.profileValue(profile,handedness,press,null);
      const high=BH.profileValue(profile,handedness,release,null);
      if(low===null||high===null||!(low<high))return null;
      return {pressRatio:low,releaseRatio:high};
    },
    requestFrame:fn=>requestAnimationFrame(fn),cancelFrame:id=>cancelAnimationFrame(id),
    now:()=>performance.now(),viewport:()=>({width:window.innerWidth,height:window.innerHeight}),
    onStatus:onStatus,
  };
  const controller=Core.createController(controllerDeps);

  /* La cible se résout dans l'adaptateur DOM, qui est le seul à pouvoir lire
     la page — mais l'**intention** vient des moteurs, que le contrôleur
     possède. Le branchement se fait donc ici, après les deux, plutôt qu'en
     ajoutant une dépendance au contrôleur : le bloc pur n'a pas à connaître
     l'aperçu, et les doubles de test du contrôleur n'ont rien à apprendre. */
  interactionView.readContacts(()=>controller.semantics().pinch.contacts);
  /* Et les événements, qui font descendre et remonter les captures (Slice 06).
     Même branchement, même raison : l'intention vient des moteurs, la page est
     la seule à savoir ce qu'il y a sous la main. */
  interactionView.readPinch(()=>controller.semantics().pinch.events);

  /* Tout changement de cycle de vie se voit : un panneau qui n'est pas ouvert
     ne dit rien, donc la bascule passe aussi par un toast. Un échec reste plus
     longtemps à l'écran et part dans la console avec sa cause réelle. */
  function onStatus(status){
    const previous=view.status;
    view.status=status;
    if(status.state==='error'&&status.error)console.warn('[barehands]',status.code,status.error);
    watchStartingClock();
    /* « Bare Hands fonctionne » se demande au contrat, pas à une liste
       recopiée ici : `starting` n'est pas un fonctionnement et n'a pas à
       sonner deux fois avant la veille. */
    const notify=status.state===BH.LIFECYCLE.ERROR||BH.isLiveLifecycle(status.state)
      ||(status.code==='disabled'&&previous.state!==BH.LIFECYCLE.ERROR);
    if(notify&&typeof toast==='function')
      toast({title:status.title,sub:status.message,
        kind:status.state==='error'?'bad':status.state===BH.LIFECYCLE.ACTIVE?'ok':'warn',
        ms:status.state==='error'?9000:4000});
    refreshPanel();
  }

  /* ------------------------------------------------------------------
     Couture de diffusion du cycle de vie.

     `onStatus` juste au-dessus est le seul endroit où **toutes** les
     transitions passent : la bascule du panneau, la voix et le canal MCP (qui
     appellent les mêmes portes), le réveil en C dans la boucle d'images, le
     retour en veille après 30 s sans main, la panne et la reprise, l'arrêt au
     déchargement. Jusqu'ici elles n'atteignaient l'écran que par
     `refreshPanel()`, qui ne peint **que l'onglet Expérimental ouvert** : un
     contrôle vivant hors du modal n'avait rien à quoi se lier, et « l'état a
     changé » et « personne ne regardait » s'écrivaient pareil.

     Même patron que la couture de mesures (`openMeasureSeam`, plus bas) et pour
     la même raison : un registre **nommé**, parce que deux consommateurs d'une
     même clé s'effaceraient l'un l'autre en silence. Deux différences assumées,
     toutes deux parce que celle-ci projette un **état** et non un flux :

     - l'abonné reçoit l'instantané **à l'ouverture**, tout de suite. Un
       contrôle installé après la dernière transition afficherait sinon un état
       d'usine jusqu'à la suivante — c'est exactement le cas du rechargement de
       page, où plus rien ne bouge avant que l'utilisateur ne touche à quelque
       chose ;
     - un instantané identique au précédent ne se republie pas. `refreshPanel`
       est appelé par des chemins qui ne touchent pas au cycle de vie (un
       curseur qu'on tire), et un abonné ne doit pas avoir à distinguer « ça a
       changé » de « on a repeint ». */
  const lifecycleSinks=new Map();
  let lifecycleLast='',lifecyclePublishing=false;
  /* Ce que la couture publie. Lu sur `view.status`, c'est-à-dire sur le
     **dernier statut émis par le contrôleur**, et non sur une variable tenue
     ici : une seconde mémoire du cycle de vie dans l'interface est précisément
     ce que l'architecture interdit. */
  function lifecycleSnapshot(){
    const status=view.status||{};
    const state=String(status.state||BH.LIFECYCLE.OFF);
    return Object.freeze({
      /* L'état d'usage, nommé par le contrat. `starting` y vaut `off` — rien
         n'interagit — mais il voyage **à côté**, dans `state`, parce qu'un
         démarrage peut durer (une invite de permission que personne ne borne)
         et qu'un écran qui le peindrait « éteint » mentirait sur ce qu'il
         attend (RÈGLE ZÉRO). */
      lifecycle:BH.lifecycleOfControllerState(state),
      state,
      /* Le démarrage n'a pas de nom dans `LIFECYCLE`, et n'en aura pas : le
         contrat le range sous `off` parce que rien n'interagit. Il se dit donc
         ici, où le vocabulaire du contrôleur est chez lui — plutôt que de
         laisser chaque abonné redécouvrir que `state === 'starting'`, ce qui
         serait un nom du moteur recopié hors du moteur. */
      starting:state===Core.STATE.STARTING,
      /* Le motif exact d'un arrêt subi, jamais aplati dans l'état (§ 1) :
         `camera_denied`, `camera_busy`, `assets_missing`… Sans lui, une caméra
         refusée se peindrait comme un « éteint » que l'utilisateur aurait
         choisi. */
      code:status.code===undefined?null:status.code,
      title:status.title||'',message:status.message||'',
      /* L'interrupteur maître (le réglage `enabled` du serveur) et l'écriture
         en vol : ensemble, ils disent si un choix est **possible** maintenant. */
      enabled:!!view.enabled,busy:!!view.busy,
    });
  }
  function publishLifecycle(){
    if(!lifecycleSinks.size)return null;
    const snapshot=lifecycleSnapshot();
    const signature=JSON.stringify(snapshot);
    if(signature===lifecycleLast)return snapshot;
    lifecycleLast=signature;
    /* Un abonné qui rappelle la surface (le bouton qui active) relance
       `refreshPanel`, donc cette diffusion, pendant qu'elle court. La reprise
       est **refusée** plutôt que réentrante : la signature a déjà retenu le
       changement, et la diffusion qui suit le portera. */
    if(lifecyclePublishing)return snapshot;
    lifecyclePublishing=true;
    try{
      for(const [who,fn] of [...lifecycleSinks.entries()]){
        /* Un consommateur qui lève ne doit emporter ni l'autre, ni le
           rafraîchissement du panneau (leçon des Slices 02 et 04). */
        try{fn(snapshot)}
        catch(error){console.warn(`[barehands] consommateur de cycle de vie « ${who} » a levé`,error)}
      }
    }finally{lifecyclePublishing=false}
    return snapshot;
  }
  function openLifecycleSeam(name,sink){
    /* Un refus codé plutôt qu'un défaut plausible : une couture ouverte sur
       rien est indiscernable d'une couture qui marche, et c'est le genre de
       silence que la décision 7 existe pour empêcher. */
    if(typeof sink!=='function')
      throw Object.assign(new Error('openLifecycleSeam : un consommateur est une fonction'),
        {code:'barehands_lifecycle_seam_invalid'});
    const key=String(name);
    lifecycleSinks.set(key,sink);
    const snapshot=lifecycleSnapshot();
    lifecycleLast=JSON.stringify(snapshot);
    try{sink(snapshot)}
    catch(error){console.warn(`[barehands] consommateur de cycle de vie « ${key} » a levé à l’ouverture`,error)}
    return lifecycleSinks.size;
  }
  function closeLifecycleSeam(name){lifecycleSinks.delete(String(name));return lifecycleSinks.size}
  function lifecycleSeamNames(){return [...lifecycleSinks.keys()]}

  function applyAssets(state){if(state&&state.assets)view.assets=state.assets}

  /* Ce que le serveur a **lu**, par opposition à ce qu'il écrit. Un bloc de
     réglages écrit par un Jarvis plus récent ne s'applique pas — c'est le bon
     choix — mais il se taisait : `schema_version` valait 2 quoi qu'il ait lu,
     donc « des défauts parce qu'illisible » et « des défauts parce que neuf »
     arrivaient identiques ici, et le bandeau ne pouvait rien dire. */
  function applyStored(state){
    const source=state&&typeof state==='object'?state:{};
    view.stored={
      unreadable:source.unreadable===true,
      version:Number.isFinite(Number(source.stored_schema_version))&&source.stored_schema_version!==null
        ?Number(source.stored_schema_version):null,
      archived:Array.isArray(source.archived)?source.archived.slice():[],
    };
  }

  /* Vu à l'écran, et pas seulement dans le journal du serveur : c'est la seule
     phrase qui dit à l'utilisateur pourquoi ses réglages ne sont pas ceux
     qu'il a laissés, et où ils sont passés. Deux états distincts, parce qu'ils
     demandent deux choses différentes : avant l'écriture le bloc est encore
     là, après elle il est rangé sous une clé qu'on nomme. */
  function storedHtml(){
    const stored=view.stored;
    if(!stored)return '';
    const kept=stored.archived.length
      ?`<div class="hint">Un bloc précédent est conservé sous ${stored.archived.map(esc).join(', ')} dans <code>runtime/control-center-settings.json</code> : rien n’a été détruit.</div>`:'';
    if(!stored.unreadable)return kept;
    const version=stored.version===null?'inconnu':String(stored.version);
    return `<div class="notice warn"><strong>Réglages écrits par une version plus récente de Jarvis (schéma ${esc(version)})</strong>
      <div class="hint">Cette version n’écrit que le schéma ${esc(String(BH.SETTINGS_SCHEMA_VERSION))} et ne sait pas les lire : elle ne les applique pas et n’en devine rien — Bare Hands utilise ses valeurs d’usine. Le bloc est intact ; le prochain enregistrement le rangera sous une clé d’archive au lieu de l’écraser.</div></div>${kept}`;
  }

  /* **Slice 07 : les réglages atteignent le moteur.** Un seul endroit les y
     porte, pour que « ce que l'écran montre » et « ce que la main fait » ne
     puissent pas diverger. Tout ce qui est ici est **vivant** : un réglage qui
     ne trouverait pas sa ligne dans cette fonction n'aurait pas sa place dans
     la table des réglages.

     `sensitivity` **divise** les deux tolérances de déplacement du moteur
     (`clickSlopPx`, `dragSlopPx`, Slice 04) : plus sensible, moins de
     mouvement toléré avant qu'un contact devienne un glissement. Les deux sont
     divisées par le **même** facteur, donc l'invariant `clickSlopPx <=
     dragSlopPx` traverse intact. Et 1 rend exactement les défauts du moteur —
     règle posée par la Slice 05 : quand un réglage stocké multiplie une
     constante du moteur, son défaut doit rendre le défaut du moteur, sans quoi
     le seul fait de brancher le champ serait une régression invisible. */
  /* **La tolérance de déplacement, composée en un seul endroit.** Elle a
     maintenant deux sources — le réglage `sensitivity` et la mesure
     `travelSlopNorm` du profil — et les composer à deux endroits les ferait
     diverger au premier changement.

     `travelSlopNorm` est une **fraction de la largeur de l'image** : la
     multiplier par la largeur de la fenêtre est ce qui règle le résidu de la
     Slice 04, puisque le même geste rend alors le même nombre de pixels à
     toutes les résolutions. Le rapport d'usine entre les deux tolérances est
     conservé, donc l'invariant `clickSlopPx <= dragSlopPx` traverse intact —
     exactement comme il traverse `sensitivity`. */
  const RATIO=Core.DEFAULTS.dragSlopPx/Core.DEFAULTS.clickSlopPx;
  function travelSlopFor(settings,profile){
    /* La main **qui a été mesurée**, pas une moyenne : on prend la première
       latéralité qui porte la mesure. Une moyenne de deux mains calibrées
       séparément serait un nombre qu'aucune des deux n'a produit. */
    let norm=null;
    for(const handedness of BH.HANDEDNESSES){
      const value=BH.profileValue(profile,handedness,'travelSlopNorm',null);
      if(value!==null&&value!==undefined){norm=value;break}
    }
    const clickSlopPx=norm===null
      ?Core.DEFAULTS.clickSlopPx
      :Math.max(1,norm*(window.innerWidth||Core.DEFAULTS.clickSlopPx/0.008));
    return {clickSlopPx:clickSlopPx/settings.sensitivity,
      dragSlopPx:clickSlopPx*RATIO/settings.sensitivity,
      calibrated:norm!==null};
  }
  function applyToEngine(settings){
    interactionView.setTool(settings.tool);
    interactionView.showTargets(settings.targetPreview);
    interactionView.setAssistance(settings.assistance);
    overlayView.showDiagnostics(settings.diagnostics);
    const travel=travelSlopFor(settings,view.profile);
    controller.configure({
      sleepTimeoutMs:settings.sleepTimeoutMs,
      clickSlopPx:travel.clickSlopPx,
      dragSlopPx:travel.dragSlopPx,
    });
  }
  /* Le profil change : c'est le **même** chemin que pour un réglage, parce
     qu'un profil et un réglage se composent dans les mêmes deux nombres. Les
     seuils par main, eux, n'ont pas besoin d'être poussés : le moteur les
     redemande par `handOverrides` à chaque main qu'il construit ou
     reconfigure. */
  function applyProfile(profile){
    view.profile=profile;
    applyToEngine(view.settings);
    /* Les mains **déjà suivies** reprennent leurs seuils : sans ce rappel, la
       main qui est sous la caméra au moment où la calibration se termine
       garderait les anciens jusqu'à ce qu'elle disparaisse — le profil aurait
       l'air appliqué à l'écran et pas dans la main (règle de la Slice 07). */
    controller.configure({});
  }

  /* Ce que le serveur vient de dire, appliqué et affiché. Une version de
     schéma étrangère **se dit** au lieu d'être devinée : le contrat lève, et
     un réglage illisible vaut mieux lu par un humain qu'appliqué de travers. */
  function applyServerState(state){
    applyAssets(state);
    applyStored(state);
    try{
      view.settings=BH.fromServerState(state);
      applyToEngine(view.settings);
      view.error='';
    }catch(error){
      view.error=`Réglages Bare Hands non appliqués : ${error&&error.message||error}`;
      console.warn('[barehands] réglages',(error&&error.code)||'',error);
      if(typeof toast==='function')
        toast({title:'Réglages Bare Hands non appliqués',sub:String(error&&error.message||error),kind:'bad',ms:9000});
    }
    view.enabled=!!(state&&state.enabled===true);
    if(view.enabled)controller.enable();
    else if(Core.isEngagedState(controller.state()))controller.disable();
    refreshPanel();
  }

  /* ------------------------------------------------------------------
     Calibration (Slice 08, décisions 26 à 32).

     La coque est construite **une fois** et partagée : c'est la décision 26,
     et c'est ce que la Slice 09 reprendra pour le tutoriel. Le parcours, lui,
     est construit à la demande — il ne tourne que quand l'utilisateur l'a
     lancé (décision 27) et s'arrête quand il a fini (décision 30). */
  let flowShell=null,calibration=null,tutorial=null;
  /* **Une coque, construite une fois, partagée par les deux parcours.** C'est
     la décision 26 rendue littérale : la calibration et le tutoriel ne sont
     pas deux surimpressions qui se ressemblent, c'est la même. Deux instances
     pourraient s'ouvrir l'une sur l'autre, et `exitOverlay()` n'aurait plus de
     référent unique. */
  function shell(){
    return flowShell||(flowShell=CALIB.createFlowOverlay({document,
      now:()=>Date.now(),
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id)}));
  }
  /* Le parcours ouvert, s'il y en a un. Une seule coque, donc au plus un : ce
     que `exitOverlay()` ferme, et ce qu'un autre parcours doit refuser de
     recouvrir. */
  function openFlow(){
    if(tutorial&&tutorial.isRunning())return {name:'tutorial',flow:tutorial};
    if(calibration&&calibration.isRunning())return {name:'calibration',flow:calibration};
    return null;
  }
  const FLOW_LABEL=Object.freeze({calibration:'La calibration',tutorial:'Le tutoriel'});
  /* Un parcours déjà ouvert refuse l'autre, **en le disant**. Sans ce refus,
     lancer le tutoriel pendant une calibration détruisait une minute de
     mesures sans un mot — et la voix, qui ne voit pas l'écran, est justement
     l'appelant qui peut le demander sans savoir. */
  function flowBusy(wanted){
    const open=openFlow();
    if(!open||open.name===wanted)return null;
    const message=`${FLOW_LABEL[open.name]} est déjà à l’écran. Quittez-la (bouton « Quitter », touche Échap, ou « ferme la surimpression ») avant d’en lancer une autre.`;
    view.error=message;
    console.warn('[barehands] parcours refusé (une coque est déjà ouverte)',{wanted,open:open.name});
    /* La coque couvre les toasts (elle est au-dessus d'eux) : la seule surface
       que l'utilisateur regarde à cet instant est la coque elle-même. */
    shell().note(message,'bad');
    refreshPanel();
    return {ok:false,code:'barehands_flow_busy',reason:message};
  }
  function calibrationFlow(){
    if(calibration)return calibration;
    calibration=CALIB.createCalibration({
      overlay:shell(),now:()=>Date.now(),
      /* L'horloge du chien de garde, la **même** que celle de la coque : une
         étape que plus aucune image ne nourrit expire quand même (RÈGLE ZÉRO).
         `createCalibration` la refuse absente, donc l'oublier ne se découvre
         pas devant un utilisateur immobile. */
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id),
      engineDefaults:Core.DEFAULTS,
      viewport:()=>({width:window.innerWidth,height:window.innerHeight}),
      save:payload=>saveProfile(payload),
      onSaved:()=>{stopMeasuring();refreshPanel()},
      onCancelled:()=>{stopMeasuring();refreshPanel()},
      log:(level,message,detail)=>{
        if(level==='warn')console.warn(message,detail);else console.info(message,detail);
      },
    });
    return calibration;
  }
  /* La couture du contrôleur n'est branchée **que pendant** un parcours : hors
     calibration, le budget d'images est exactement celui d'avant (décision 27,
     et l'acquis mesuré de la Slice 02).

     **Deux mécanismes, et aucun des deux n'est de trop** — même forme que
     les deux sources du tutoriel, et pour la même raison lue à l'envers :

     1. **la couture d'images** (`deps.onMeasure`), parce qu'elle seule peut
        construire un enregistrement de scalaires (décision 32) ;
     2. **un chien de garde**, parce que cette couture ne tire qu'en ACTIVE et
        **seulement quand une main a été observée** : l'utilisateur qui sort du
        cadre ne fait plus regarder l'échéance par personne, et l'étape ne se
        solde jamais. Il ne peut pas être bloqué de la même façon que la
        caméra, il ne vit que pendant la calibration, et sa cadence est bornée
        contre l'échéance d'une étape **à la construction** (paire dangereuse
        n° 14).

     Les deux n'appellent pas la même porte, et c'est délibéré : `tick()`
     regarde la montre sans fabriquer d'image (voir le module).

     **Et le second n'est pas posé ici.** Le tutoriel doit poser le sien dans la
     page parce que son observation se construit à partir de ce que la page
     publie ; l'échéance d'une calibration, elle, ne demande rien à personne.
     Elle appartient donc au parcours, qui l'ouvre et la referme lui-même et
     **refuse de se construire sans horloge** — la leçon que la Slice 09 a tirée
     de la croix de sortie : une garantie que chaque appelant doit se rappeler
     de respecter n'est pas une garantie, c'est une convention. */
  /* **Une seule réduction, deux consommateurs** (Slice 10).

     La couture est **posée sur les dépendances du contrôleur**, pas dans une
     branche qu'il évaluerait à chaque image : il teste `typeof
     deps.onMeasure`, donc l'absence de consommateur est l'absence de fonction,
     et rien n'est calculé. Une fonction toujours présente qui rendrait tout de
     suite aurait fait payer à chaque session le coût d'une fonctionnalité que
     personne n'a lancée. C'est cette propriété-là qui tient le budget
     d'images, et elle est **inchangée** : sans calibration et sans
     enregistrement, `measureSinks` est vide, la clé est supprimée, et le coût
     par image est exactement celui d'avant.

     Ils sont deux depuis la Slice 10 : la calibration, et l'enregistreur de
     diagnostic. Élargir la couture aurait été le mauvais réflexe — la question
     que la Slice 09 pose est « ce consommateur a-t-il besoin de **cette**
     couture », et la réponse est oui : l'enregistreur veut exactement
     l'enregistrement de scalaires qu'elle produit déjà, ni plus ni moins. Ce
     qu'il ne faut pas, c'est **deux propriétaires d'une même clé** : arrêter
     la calibration effacerait la couture de l'enregistreur et une séance
     s'arrêterait sans que rien ne le dise. D'où un registre nommé, et
     `measureSeam()` qui le relit — sans lecture, « les deux écoutent » et
     « l'un a été effacé par l'autre » s'écrivent pareil. */
  const measureSinks=new Map();
  function openMeasureSeam(name,sink){
    measureSinks.set(name,sink);
    if(typeof controllerDeps.onMeasure==='function')return measureSinks.size;
    controllerDeps.onMeasure=record=>{
      for(const [who,fn] of [...measureSinks.entries()]){
        /* Un consommateur qui lève ne doit pas emporter l'autre, ni la boucle
           d'images (leçon des Slices 02 et 04) : il se dit et se saute. */
        try{fn(record)}
        catch(error){console.warn(`[barehands] consommateur de mesures « ${who} » a levé`,error)}
      }
    };
    return measureSinks.size;
  }
  function closeMeasureSeam(name){
    measureSinks.delete(name);
    if(!measureSinks.size)delete controllerDeps.onMeasure;
    return measureSinks.size;
  }
  function startMeasuring(){
    openMeasureSeam('calibration',record=>{
      const flow=calibration;
      if(flow&&flow.isRunning())flow.feed(record);
    });
  }
  function stopMeasuring(){closeMeasureSeam('calibration')}

  /* ------------------------------------------------------------------
     Tutoriel (Slice 09, décisions 6 et 26).

     **Le tutoriel n'écrit jamais de paramètre de calibration.** Trois choses
     le tiennent, et aucune n'est une promesse :

     1. `createTutorial` n'accepte qu'une **liste blanche** de dépendances
        (Slice 10) : tout nom qui n'est pas au contrat §13 est refusé à la
        construction, écrivain connu ou nom que personne n'a encore inventé
        — voir le module ;
     2. le câblage ci-dessous ne lui en passe aucune : le seul effet durable
        est `onDone`, qui écrit le **réglage** `tutorialSeen` par la porte
        unique des réglages (`saveSettings`) ;
     3. il n'emprunte pas la couture `deps.onMeasure` du contrôleur : ce que
        `observe` lui donne est une **observation** construite ici à
        partir de ce que la page publie déjà, où aucune mesure de main
        n'entre. La couture de la décision 32 reste fermée pendant tout le
        tutoriel, ce qu'un test affirme. */
  function tutorialFlow(){
    if(tutorial)return tutorial;
    if(!TUTO)return null;
    tutorial=TUTO.createTutorial({
      overlay:shell(),now:()=>Date.now(),
      /* **Les deux sources sont passées, plus posées** (Slice 10). La page
         donne la couture d'images et le lecteur d'observation ; c'est le
         parcours qui les attache et les détache, parce que « Recommencer »
         rentre dans `begin()` sans que la page en sache rien. Tant que
         c'était l'inverse, un tutoriel relancé n'était plus nourri du tout.
         La minuterie vient d'ici parce que `window` est ici, mais la cadence
         est celle des options **effectives** du parcours, qui sont aussi
         celles que la paire dangereuse n° 13 valide. */
      frames:fn=>interactionView.afterFrame(fn),
      observe:tutorialObservation,
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id),
      onDone:result=>{markTutorialSeen(result)},
      onExit:()=>{refreshPanel()},
      log:(level,message,detail)=>{
        if(level==='warn')console.warn(message,detail);else console.info(message,detail);
      },
    });
    return tutorial;
  }

  /* Ce que le tutoriel a le droit de constater, construit **ici** à partir de
     ce que la page publie déjà : le cycle de vie, les cibles en cours de
     résolution, les interactions de l'instant et les deux réglages dont une
     étape parle. Aucun échantillon de main n'y entre, et le module réduit
     encore ce qu'il reçoit (`readObservation`) — la liste blanche est donc
     écrite des deux côtés, et c'est celle du module qui est testée au
     chargement. */
  function tutorialObservation(){
    /* Lire l'instant ne doit pas arrêter un tutoriel : ce qu'on ne peut pas
       lire se dit et vaut « rien vu », ce que les étapes savent traiter. Le
       cycle de vie reste hors du `try` : sans lui l'observation ne veut rien
       dire, et il ne lit qu'un état interne. */
    let interactions=[],targets=0,hands=0;
    try{
      interactions=interactionView.interactions();
      targets=interactionView.targets().length;
      hands=controller.features().length;
    }catch(error){
      console.warn('[barehands] tutoriel : l’instant est illisible',error);
      interactions=[];targets=0;hands=0;
    }
    return {
      now:Date.now(),
      lifecycle:lifecycle(),
      tool:view.settings.tool,
      targetPreview:!!view.settings.targetPreview,
      targets,hands,interactions,
    };
  }
  /* **Deux mécanismes, et aucun des deux n'est de trop.**

     1. **La cadence des images** (`interactionView.afterFrame`), parce que
        `interactions()` ne décrit qu'un **instant** : elle est vidée à chaque
        image, donc un lecteur qui n'échantillonnerait qu'à la minuterie
        raterait la quasi-totalité des clics — le tutoriel aurait demandé un
        geste que l'utilisateur aurait fait sans que rien ne l'enregistre, ce
        qui est la pire panne possible pour un parcours d'apprentissage.
     2. **Un chien de garde**, parce que cette boucle ne tourne qu'en ACTIVE et
        seulement quand une main est vue : une étape quittée par l'utilisateur
        ne serait jamais déclarée manquée et le compteur resterait figé sur
        « 0 s restantes » — la panne exacte que la RÈGLE ZÉRO interdit. Il ne
        peut pas être bloqué de la même façon que la caméra, il ne vit que
        pendant le tutoriel, et sa cadence est bornée contre l'échéance d'une
        étape **à la construction** (paire dangereuse n° 13).

     Les deux appellent le même `pump` : une observation de plus est
     inoffensive (une étape ne se solde qu'une fois), une observation de moins
     ne l'est pas.

     **Les deux vivent dans le parcours depuis la Slice 10**, et la page ne
     fait plus que les lui passer (voir `tutorialFlow`). Elle les posait
     elle-même autour de `startTutorial()`, ce qui marchait exactement une
     fois : le bouton « Recommencer » du récapitulatif rentre dans le parcours
     **depuis l'intérieur du module**, la page n'était jamais rappelée, et le
     tutoriel relancé n'était plus nourri du tout — `tutorialState().observed`
     restait à 0 pendant que l'utilisateur faisait le C correctement. Une
     garantie que l'appelant doit se rappeler de respecter n'est pas une
     garantie ; et un repli qui partage sa source avec ce qu'il double n'en
     est pas un non plus. */

  /* `tutorialSeen` **est lu par quelqu'un depuis la Slice 09** : il décide de
     ce que la section Tutoriel de l'onglet dit, et il est écrit ici, à
     l'arrivée sur le récapitulatif. Il passe par la porte unique des réglages
     — donc il est normalisé, appliqué et enregistré comme les huit autres, et
     un échec d'écriture a déjà ses trois obligations (bandeau, toast,
     `finally`). Ce qui manquerait sans la ligne ci-dessous, c'est de le dire
     **dans la coque**, seule surface visible à cet instant. */
  async function markTutorialSeen(result){
    /* **Rien n'est détaché ici**, et c'est la correction de la Slice 10 : le
       récapitulatif est un état vivant du parcours, d'où le bouton
       « Recommencer » repart. Couper les sources en y arrivant était le
       premier maillon de la panne — la relance retombait sur un parcours que
       plus rien ne nourrissait. Le parcours les tient lui-même jusqu'à
       `stop()`, et `pump()` n'observe pas tant que le récapitulatif est à
       l'écran : l'attache ne coûte donc rien de plus qu'un test de booléen
       par image. */
    refreshPanel();
    if(view.settings.tutorialSeen){shell().note('Tutoriel terminé.','ok');return null}
    const saved=await saveSettings({tutorialSeen:true});
    if(saved===null)
      shell().note('Tutoriel terminé, mais « tutoriel déjà vu » n’a pas pu être enregistré : il vous sera reproposé.','bad');
    else shell().note(`Tutoriel terminé (${result&&result.done||0} étape(s) sur ${result&&result.total||(TUTO?TUTO.STEPS.length:0)}).`,'ok');
    refreshPanel();
    return saved;
  }

  /* ------------------------------------------------------------------
     Enregistrement de diagnostic (Slice 10, architecture §12, décision 32).

     **Ce qui est enregistré, et comment l'utilisateur le sait.** Une trace ne
     porte que des faits dérivés — aucun point de main, aucune image, aucune
     vidéo, aucun identifiant — et le module le tient par trois mécanismes
     structurels, pas par intention (voir son en-tête). Ce qui est tenu **ici**
     est la seconde moitié de la promesse : l'enregistrement est éteint par
     défaut, ne s'allume que sur une action explicite, **dit à l'écran** qu'il
     tourne, depuis combien de temps, combien d'images il a prises et combien
     il lui reste, et s'arrête tout seul au bout de son échéance. Ce qui
     observe sans le dire est ce que personne n'accepte.

     **Coût quand personne n'enregistre : nul.** L'enregistreur n'est pas un
     consommateur permanent de la couture de mesures : il s'y inscrit au
     démarrage et s'en retire à l'arrêt. Hors enregistrement et hors
     calibration, `controllerDeps.onMeasure` n'existe pas, donc le contrôleur
     ne construit aucun enregistrement de scalaires — le budget d'images est
     exactement celui d'avant, ce qu'un test mesure sur le vrai contrôleur. */
  const TRACE_API='/api/barehands/traces';
  let recorder=null,recorderTick=0;
  function recorderFlow(options){
    if(recorder&&options===undefined)return recorder;
    if(!REC)return null;
    recorder=REC.createRecorder({
      options,
      now:()=>Date.now(),
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),
      clearTimeout:id=>window.clearTimeout(id),
      /* L'arrêt, quelle qu'en soit la cause — le bouton, l'échéance ou le
         plafond d'images. Les trois passent ici, donc une trace ne peut pas
         être perdue parce que l'utilisateur n'a pas appuyé sur le bouton. */
      onStop:trace=>{closeMeasureSeam('recorder');stopPainting();saveTrace(trace)},
      log:(level,message,detail)=>{
        if(level==='warn')console.warn(message,detail);else console.info(message,detail);
      },
    });
    return recorder;
  }

  /* Ce que l'enregistreur reçoit : l'enregistrement de scalaires du contrôleur
     (décision 32, déjà réduit), **plus** ce que la page publie déjà — les
     candidates de cible en cours, les issues de l'instant et les gestes.
     Aucune de ces trois portes ne transporte de point de main, et le module
     réduit encore ce qu'il reçoit (`readFrame`). La liste blanche est donc
     écrite des deux côtés, et c'est celle du module qui est vérifiée au
     chargement. */
  function traceFrame(record){
    let candidates=[],events=[],gestures=[];
    try{
      candidates=interactionView.targets();
      events=interactionView.interactions();
      const semantics=controller.semantics();
      gestures=[
        ...semantics.gestures.events.map(event=>({name:event.gesture,phase:event.phase,suppressed:false})),
        ...semantics.gestures.suppressed.map(event=>({name:event.gesture,phase:event.phase,suppressed:true})),
      ];
    }catch(error){
      /* Lire l'instant ne doit pas arrêter un enregistrement : ce qu'on ne
         peut pas lire vaut « rien vu » pour cette image, et le compte d'images
         retenues le dira. */
      console.warn('[barehands] enregistrement : l’instant est illisible',error);
      candidates=[];events=[];gestures=[];
    }
    /* **La fente vient de l'allocateur canonique, pas du rang dans le tableau.**
       `record.hands` est ordonné par le traqueur : quand une main quitte le
       cadre, celles qui restent se renumérotent. Une fente déduite du rang
       changeait donc de main sous le rejeu — et la voie 0, qui porte l'histoire
       du filtre de la main gauche, se faisait nourrir les coordonnées de la
       droite. Mesuré sur la même séance, l'erreur de pointeur empirait d'un
       facteur 3 à 5 selon **laquelle** des deux mains sortait du cadre, et
       `hand.loss_recovery_p95_ms` s'attribuait à la fente devenue vacante
       plutôt qu'à la main perdue.

       `interactionView.slotOf` est `BH.createSlotAllocator` (Level 3, contraté :
       « une main garde sa fente tant qu'elle vit ; une fente libérée est
       réutilisée »), sur l'objet que cette fonction appelle déjà, et c'est le
       même appel qu'à la construction d'un évènement de pincement. La fente est
       **dérivée et non identifiante** : `handTrackId` ne traverse pas la liste
       blanche de l'enregistreur, qui n'en écrit jamais. */
    const hands=(record&&Array.isArray(record.hands)?record.hands:[]).map(hand=>{
      let slot=null;
      try{slot=interactionView.slotOf(hand&&hand.handTrackId)}
      catch(error){
        /* Capturé, pas tu : une main sans identité lisible ne doit pas arrêter
           l'enregistrement, mais sa fente retombe alors sur le rang et le rejeu
           mérite de savoir pourquoi. */
        console.warn('[barehands] enregistrement : fente de main illisible',error);
        slot=null;
      }
      /* `null` = main surnuméraire ou sans identité : l'enregistreur retombe
         sur le rang, faute de mieux, et le dit dans son propre commentaire. */
      return slot===null?hand:{...hand,slot};
    });
    return {lifecycle:lifecycle(),hands,candidates,events,gestures};
  }

  /* Le compteur vivant. La RÈGLE ZÉRO demande qu'un état long dise **depuis
     combien de temps** il dure : sans repeinture périodique, « ça enregistre »
     et « c'est figé » s'écrivent pareil à l'écran. Il ne vit que pendant
     l'enregistrement, et il est démarré et arrêté par les deux mêmes portes
     que lui. */
  function startPainting(){
    if(recorderTick)return recorderTick;
    recorderTick=window.setInterval(()=>{
      const state=document.getElementById('barehandsRecordState');
      if(state)state.innerHTML=recordStateHtml();
    },250);
    return recorderTick;
  }
  function stopPainting(){
    if(!recorderTick)return false;
    window.clearInterval(recorderTick);recorderTick=0;
    return true;
  }

  /* **Le point d'entrée de l'enregistrement.** Comme les deux parcours, il
     confirme ou refuse avec un code, et le refus est dit à l'écran parce que
     c'est le seul endroit où sa cause exacte survit. */
  function startRecording(overrides){
    if(!REC){
      const message='L’enregistrement de diagnostic n’a pas pu être chargé dans cette page. Rechargez le Control Center ; la console porte la cause exacte.';
      view.error=message;console.warn('[barehands] enregistrement indisponible (module non installé)');
      if(typeof toast==='function')
        toast({title:'Enregistrement indisponible',sub:message,kind:'bad',ms:8000});
      refreshPanel();
      return {ok:false,code:'barehands_recorder_not_installed',reason:message};
    }
    /* Déjà en cours : c'est l'état demandé, et une seconde demande ne doit ni
       le couper ni le reconstruire. */
    if(recorder&&recorder.isRecording())return recorder.start();
    if(!view.enabled){
      const message='Bare Hands est éteint : cochez « Activer Barehands » avant d’enregistrer. L’interrupteur reste à vous.';
      view.error=message;console.warn('[barehands] enregistrement refusé (éteint)');
      if(typeof toast==='function')
        toast({title:'Enregistrement impossible',sub:message,kind:'warn',ms:6000});
      refreshPanel();
      return {ok:false,code:'barehands_recorder_disabled',reason:message};
    }
    /* **Les options sont celles de cette séance-là.** Un outil de diagnostic
       qu'on ne peut pas recadencer depuis la console est à moitié inutile, et
       les deux paires dangereuses se refusent **ici**, à la construction,
       plutôt qu'au premier utilisateur qui relirait une trace d'une image. */
    const spec=overrides&&typeof overrides==='object'?overrides:{};
    let flow,started;
    try{flow=recorderFlow(spec.options)}
    catch(error){
      const message=`Enregistrement refusé : ${error&&error.message||error}`;
      view.error=message;console.warn('[barehands] enregistrement refusé',error);
      if(typeof toast==='function')
        toast({title:'Enregistrement impossible',sub:message,kind:'bad',ms:8000});
      refreshPanel();
      return {ok:false,code:error&&error.code||'barehands_recorder_refused',reason:message};
    }
    try{started=flow.start({viewport:{width:window.innerWidth,height:window.innerHeight}})}
    catch(error){
      const message=`Enregistrement refusé : ${error&&error.message||error}`;
      view.error=message;console.warn('[barehands] enregistrement refusé',error);
      if(typeof toast==='function')
        toast({title:'Enregistrement impossible',sub:message,kind:'bad',ms:8000});
      refreshPanel();
      return {ok:false,code:error&&error.code||'barehands_recorder_refused',reason:message};
    }
    /* La couture ne s'ouvre qu'**après** que l'enregistreur a accepté : une
       couture ouverte devant un enregistreur qui a refusé ferait payer chaque
       image pour rien, sans que rien ne l'enregistre. */
    openMeasureSeam('recorder',record=>{
      const flow=recorder;
      if(flow&&flow.isRecording())flow.feed(traceFrame(record));
    });
    startPainting();
    if(typeof toast==='function')
      toast({title:'Enregistrement de diagnostic démarré',
        sub:'Aucune image, aucune vidéo, aucun point de main : seulement des mesures dérivées. Il s’arrête tout seul.',
        kind:'ok',ms:6000});
    refreshPanel();
    return started;
  }
  function stopRecording(){
    const flow=recorder;
    if(!flow||!flow.isRecording()){
      refreshPanel();
      /* Rien n'enregistrait : c'est l'état demandé, donc un succès — et
         `already` le dit, pour que personne n'annonce un arrêt qui n'a pas eu
         lieu (même raison qu'`exitOverlay`). */
      return {ok:true,already:true,recording:false};
    }
    const trace=flow.stop();
    refreshPanel();
    return {ok:true,recording:false,frames:trace?trace.frames.length:0};
  }

  /* **Où la trace va, et ce qu'elle laisse comme preuve.** Elle part sur la
     route, le serveur l'écrit sous `runtime/barehands-traces/` et journalise
     une ligne par enregistrement (`RuntimeJournal`, constat F6 de la Slice 00).
     Un échec d'envoi a ses trois obligations — vu à l'écran, journalisé,
     interface relâchée — et la trace **reste lisible dans la page**
     (`record.trace()`), pour qu'une séance ne soit pas perdue par une panne de
     réseau. */
  async function saveTrace(trace){
    view.trace=null;
    try{
      const answer=await api(TRACE_API,{method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify(trace)});
      view.trace={id:String(answer&&answer.trace_id||''),frames:trace.frames.length,
        path:String(answer&&answer.path||''),error:''};
      console.info('[barehands] trace enregistrée',view.trace);
      if(typeof toast==='function')
        toast({title:'Trace enregistrée',
          sub:`${trace.frames.length} image(s) · ${view.trace.id}`,kind:'ok',ms:6000});
    }catch(error){
      const message=String(error&&error.message||error);
      view.trace={id:'',frames:trace.frames.length,path:'',error:message};
      console.warn('[barehands] trace non enregistrée',error);
      if(typeof toast==='function')
        toast({title:'Trace non enregistrée',
          sub:`${message} — elle reste lisible dans cette page par JarvisBarehands.record.trace().`,
          kind:'bad',ms:9000});
    }
    refreshPanel();
    return view.trace;
  }

  function recordState(){
    const flow=recorder;
    const state=flow?flow.state():{recording:false,frames:0,observed:0,dropped:0,
      elapsedMs:0,remainingMs:0,maxFrames:0,maxDurationMs:0};
    return {installed:!!REC,...state,
      /* Ce que la couture de mesures porte **en ce moment**, relu plutôt que
         promis : c'est ce qui distingue « l'enregistreur écoute » de
         « quelqu'un a fermé la couture sous lui ». */
      seam:measureSeamNames(),
      last:view.trace?{...view.trace}:null};
  }
  function measureSeamNames(){return [...measureSinks.keys()].sort()}

  function recordStateHtml(){
    const state=recordState();
    if(!state.installed)
      return '<div class="notice bad"><strong>Enregistrement indisponible</strong><div class="hint">Son module ne s’est pas installé dans cette page. Rechargez le Control Center ; la console porte la cause exacte. Le reste de Bare Hands fonctionne normalement.</div></div>';
    if(state.recording)
      return `<div class="notice info"><strong>Enregistrement en cours</strong><div class="hint">${esc(String(state.frames))} image(s) retenue(s) sur ${esc(String(state.observed))} vue(s) · ${esc(seconds(state.elapsedMs))} écoulée(s) · il s’arrête tout seul dans ${esc(seconds(state.remainingMs))}, ou par le bouton « Arrêter ». Aucune image, aucune vidéo, aucun point de main n’est retenu.</div></div>`;
    if(state.last&&state.last.error)
      return `<div class="notice bad"><strong>Trace non enregistrée</strong><div class="hint">${esc(state.last.error)} — les ${esc(String(state.last.frames))} image(s) restent lisibles dans cette page par <code>JarvisBarehands.record.trace()</code>.</div></div>`;
    if(state.last)
      return `<div class="notice ok"><strong>Trace enregistrée</strong><div class="hint">${esc(String(state.last.frames))} image(s) · <code>${esc(state.last.id)}</code>. Rejouez-la sous plusieurs réglages avec <code>python -m jarvis barehands-replay</code>.</div></div>`;
    return '<div class="hint">Rien n’est enregistré. Un enregistrement retient des <strong>mesures dérivées</strong> — position brute et filtrée, ratios de pincement, immobilité, issues — et jamais une image, une vidéo ni les points de votre main. Il s’arrête tout seul au bout de deux minutes.</div>';
  }
  function recordHtml(){
    const state=recordState();
    return `<section class="bh-section" id="barehandsRecord">
      <h3>Enregistrement de diagnostic</h3>
      <div class="hint" style="margin-bottom:12px">Pour régler Bare Hands sur des <strong>faits</strong> plutôt qu'à l'estime : une séance enregistrée une fois se rejoue autant qu'on veut, sous autant de réglages qu'on veut, et rend des mesures comparables. Éteint par défaut, et il ne s'allume que d'ici.</div>
      <div id="barehandsRecordState">${recordStateHtml()}</div>
      <div class="field inline" style="align-items:center;gap:10px;margin-top:14px">
        <button type="button" class="action small${state.recording?'':' primary'}" id="barehandsRecordStart" ${view.busy||state.recording||!state.installed?'disabled':''}>Enregistrer une séance…</button>
        <button type="button" class="action small" id="barehandsRecordStop" ${state.recording?'':'disabled'}>Arrêter</button>
      </div>
    </section>`;
  }

  async function loadProfile(){
    try{
      const state=await api(PROFILE_API);
      view.profile=BH.normalizeProfile(fromProfileState(state));
      view.profileError='';
      applyProfile(view.profile);
      console.info('[barehands] profil de calibration relu',
        view.profile.calibrated?'calibré':'aucune mesure');
    }catch(error){
      /* RÈGLE ZÉRO : un profil qu'on n'a pas pu relire n'est pas un profil
         vide. Le moteur garde ses défauts — ce qui est le bon repli — mais
         l'écran le **dit**, sans quoi « pas calibré » et « pas lisible »
         seraient la même phrase. */
      view.profile=null;
      view.profileError=`Profil de calibration illisible : ${error&&error.message||error}`;
      console.warn('[barehands] profil de calibration illisible',error);
    }
    refreshPanel();
  }
  /* La route parle `snake_case`, le contrat `camelCase` : une seule table de
     passage, comme `SETTINGS_WIRE_KEYS` pour les réglages. */
  const PROFILE_WIRE=Object.freeze({pressRatio:'press_ratio',releaseRatio:'release_ratio',
    secondaryPressRatio:'secondary_press_ratio',secondaryReleaseRatio:'secondary_release_ratio',
    jitterPx:'jitter_px',travelSlopNorm:'travel_slop_norm',reachNorm:'reach_norm',quality:'quality'});
  function fromProfileState(state){
    const source=state&&typeof state==='object'?state:{};
    const hands={};
    for(const handedness of BH.HANDEDNESSES){
      const given=(source.hands&&source.hands[handedness])||{};
      const hand={};
      for(const key of Object.keys(PROFILE_WIRE))hand[key]=given[PROFILE_WIRE[key]];
      hands[handedness]=hand;
    }
    return {schemaVersion:source.schema_version,calibrated:source.calibrated,
      updatedAt:source.updated_at,hands,stages:source.stages};
  }
  function toProfileWire(payload){
    const hands={};
    for(const handedness of BH.HANDEDNESSES){
      const given=(payload.hands&&payload.hands[handedness])||{};
      const hand={};
      for(const key of Object.keys(PROFILE_WIRE))hand[PROFILE_WIRE[key]]=given[key];
      hands[handedness]=hand;
    }
    return {schema_version:payload.schemaVersion,updated_at:payload.updatedAt,
      hands,stages:payload.stages};
  }
  async function saveProfile(payload){
    const state=await api(PROFILE_API,{method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(toProfileWire(payload))});
    view.profile=BH.normalizeProfile(fromProfileState(state));
    view.profileError='';
    applyProfile(view.profile);
    if(typeof toast==='function')
      toast({title:'Profil de calibration enregistré',
        sub:view.profile.calibrated?'Bare Hands utilise vos mesures.'
          :'Aucune mesure retenue : Bare Hands garde ses valeurs d’usine.',
        kind:view.profile.calibrated?'ok':'warn',ms:5000});
    return view.profile;
  }
  async function resetProfile(){
    const ok=typeof confirmDialog==='function'?await confirmDialog({
      title:'Réinitialiser le profil de calibration ?',
      lines:['Bare Hands reviendra à ses seuils d’usine pour toutes les mains.',
        'Les réglages de l’onglet ne sont pas touchés.'],
      confirmLabel:'Réinitialiser'}):true;
    if(!ok)return null;
    try{
      const state=await api(PROFILE_API,{method:'DELETE'});
      view.profile=BH.normalizeProfile(fromProfileState(state));
      view.profileError='';
      applyProfile(view.profile);
      console.info('[barehands] profil de calibration réinitialisé');
      if(typeof toast==='function')
        toast({title:'Profil réinitialisé',sub:'Bare Hands est revenu à ses seuils d’usine.',kind:'ok',ms:4000});
    }catch(error){
      view.profileError=`Réinitialisation impossible : ${error&&error.message||error}`;
      console.warn('[barehands] profil non réinitialisé',error);
      if(typeof toast==='function')
        toast({title:'Profil non réinitialisé',sub:String(error&&error.message||error),kind:'bad',ms:7000});
    }
    refreshPanel();
    return view.profile;
  }

  /* **Le point d'entrée du parcours**, appelé par le bouton *et* par la voix
     (canal de commandes, Slice 12). Il **confirme** en résolvant `{ok:true}`,
     faute de quoi le canal refuse `barehands_flow_unconfirmed` et JARVIS dit à
     l'utilisateur que ça n'a pas démarré. Il confirme le **démarrage**, pas la
     fin : l'échéance du canal est de trois secondes et une calibration en
     prend trente.

     Les deux refus possibles sont rendus `{ok:false, code}` — le canal les
     traduit en « n'a pas confirmé », ce qui est vrai — **et** dits à l'écran,
     parce que c'est le seul endroit où leur cause exacte survit. */
  async function startCalibration(){
    if(!view.settings.calibrationEnabled){
      const message='La calibration est désactivée dans les réglages Bare Hands. Cochez « Proposer la calibration » pour la relancer.';
      view.error=message;console.warn('[barehands] calibration refusée (désactivée)');
      if(typeof toast==='function')
        toast({title:'Calibration désactivée',sub:message,kind:'warn',ms:6000});
      refreshPanel();
      return {ok:false,code:'barehands_calibration_disabled',reason:message};
    }
    /* Une seule coque : le tutoriel ouvert refuse la calibration plutôt que de
       le recouvrir (décision 26, et `exitOverlay()` n'aurait plus de référent
       unique). */
    const busy=flowBusy('calibration');
    if(busy)return busy;
    const flow=calibrationFlow();
    if(flow.isRunning())return flow.start();
    /* **L'interrupteur appartient à l'utilisateur**, et cette porte est aussi
       celle de la voix. Le § 12 garde délibérément `enable`/`disable` hors de
       la table des commandes pour cette raison ; un parcours qui allumerait
       Bare Hands au passage rendrait la décision contournable par un autre
       nom. On refuse donc, en disant quoi faire — plutôt que d'ouvrir une
       caméra que personne n'a rallumée. */
    if(!view.enabled){
      const message='Bare Hands est éteint : cochez « Activer Barehands » avant de lancer la calibration.';
      view.error=message;console.warn('[barehands] calibration refusée (éteint)');
      if(typeof toast==='function')
        toast({title:'Calibration impossible',sub:message,kind:'warn',ms:6000});
      refreshPanel();
      return {ok:false,code:'barehands_calibration_disabled',reason:message};
    }
    /* Réveiller, en revanche, est exactement ce que la voix sait déjà faire
       (`activate` est dans la table) : calibrer demande des mains vivantes. */
    try{await setAwake(true)}
    catch(_error){/* `setAwake` avale ses erreurs dans `view.error` */}
    if(lifecycle()!==BH.LIFECYCLE.ACTIVE){
      const message=view.error||'Bare Hands n’a pas pu activer la caméra : la calibration a besoin de voir vos mains.';
      if(typeof toast==='function')
        toast({title:'Calibration impossible',sub:message,kind:'bad',ms:8000});
      console.warn('[barehands] calibration refusée (caméra)',view.status&&view.status.code);
      refreshPanel();
      return {ok:false,code:'barehands_calibration_no_camera',reason:message};
    }
    startMeasuring();
    const started=flow.start();
    refreshPanel();
    return started;
  }

  /* **Le point d'entrée du tutoriel**, appelé par le bouton *et* par la voix
     (canal de commandes, § 12). Même forme que `startCalibration`, et pour les
     mêmes raisons : il **confirme** en résolvant `{ok:true}` dès que la coque
     est à l'écran et que la première étape tourne — le démarrage, pas la fin :
     l'échéance du canal est de trois secondes et un tutoriel en prend
     plusieurs minutes. Les refus sont rendus `{ok:false, code}` — le canal les
     traduit en « n'a pas confirmé », ce qui est vrai — **et** dits à l'écran,
     parce que c'est le seul endroit où leur cause exacte survit.

     **Il ne réveille pas, et c'est la différence avec la calibration.** La
     première étape *est* le geste de réveil : l'exécuter à la place de
     l'utilisateur lui retirerait ce qu'on prétend lui apprendre. Comme
     `calibrate()`, il n'allume pas non plus Bare Hands — le § 12 garde
     `enable`/`disable` hors du canal, et un parcours qui allumerait au
     passage rendrait la décision contournable par un autre nom. */
  function startTutorial(){
    /* Le module ne s'est pas installé (mauvais ordre d'insertion, ou sa garde
       de forme a refusé). On le **dit** avec son propre code plutôt que de
       laisser une porte absente : le canal rendrait `barehands_flow_absent`,
       qui est vrai, mais l'écran est le seul endroit où la cause exacte
       survit. */
    if(!TUTO){
      const message='Le tutoriel n’a pas pu être chargé dans cette page. Rechargez le Control Center ; la console porte la cause exacte.';
      view.error=message;console.warn('[barehands] tutoriel indisponible (module non installé)');
      if(typeof toast==='function')
        toast({title:'Tutoriel indisponible',sub:message,kind:'bad',ms:8000});
      refreshPanel();
      return {ok:false,code:'barehands_tutorial_not_installed',reason:message};
    }
    const busy=flowBusy('tutorial');
    if(busy)return busy;
    const flow=tutorialFlow();
    if(flow.isRunning())return flow.start();
    if(!view.enabled){
      const message='Bare Hands est éteint : cochez « Activer Barehands » avant de lancer le tutoriel. L’interrupteur reste à vous.';
      view.error=message;console.warn('[barehands] tutoriel refusé (éteint)');
      if(typeof toast==='function')
        toast({title:'Tutoriel impossible',sub:message,kind:'warn',ms:6000});
      refreshPanel();
      return {ok:false,code:'barehands_tutorial_disabled',reason:message};
    }
    /* **Il n'y a pas de refus « pas de caméra » ici, et c'est délibéré.** La
       calibration en a un parce qu'elle ne peut rien mesurer sans mains ; le
       tutoriel, lui, *enseigne*, et l'endroit où « la caméra n'est pas encore
       prête » doit se lire est justement la coque — avec sa phrase, son
       compteur vivant et ses trois sorties. Refuser renverrait l'utilisateur à
       un toast sans rien lui dire de ce qu'il doit faire ensuite, alors que la
       première étape est précisément celle qui parle du réveil. Le cycle de
       vie entre donc dans l'observation, et l'étape `wake` a une phrase pour
       chacun de ses quatre états. */
    const started=flow.start();
    refreshPanel();
    return started;
  }

  /* **Sortir de la surimpression**, quelle qu'elle soit. Troisième sortie du
     contrat de Slice, à côté du bouton « Quitter » et de la touche Échap :
     « Jarvis, ferme la surimpression ».

     Il **confirme** même quand rien n'était ouvert, et c'est le même
     raisonnement que `deactivate` au § 12 (« ne pilote plus » est vrai en
     veille comme éteint) : ce que l'appelant demande est qu'il n'y ait pas de
     surimpression, et il n'y en a pas. Répondre « non » ferait dire à JARVIS
     que ça n'a pas marché devant un écran qui montre exactement l'état
     demandé. Le reçu dit lequel des deux cas s'est produit (`closed`). */
  function exitOverlay(){
    const open=openFlow();
    if(!open){
      console.info('[barehands] sortie de surimpression : aucune n’était ouverte');
      /* **`already` pour la même raison que les deux autres parcours**
         (Slice 10) : c'est un succès, mais rien n'a changé. Sans ce drapeau
         le canal rend `applied` et JARVIS dit « je l'ai fermée » devant un
         écran où il n'y avait rien — le faux récit exact que le vocabulaire
         `duplicate` existe pour éviter. `closed` reste ce qu'il a toujours
         été : ce que la page a fait, que les tests de la Slice 09 lisent. */
      return {ok:true,flow:null,closed:false,already:true};
    }
    open.flow.exit('voix ou commande');
    stopMeasuring();
    refreshPanel();
    return {ok:true,flow:open.name,closed:true};
  }

  /* ------------------------------------------------------------------
     Ce que la voix vient de faire, **à l'écran** (Slice 09, Issue R13 de la
     Slice 12).

     La RÈGLE ZÉRO n'était pas violée — l'utilisateur *entend* JARVIS — mais un
     opérateur qui regarde la fenêtre ne pouvait pas distinguer une commande
     vocale d'un clic, et une commande vocale **refusée** ne laissait rien du
     tout à l'écran : un `console.warn`, et le silence. Le canal de la Slice 12
     avait déjà toute la matière ; ce qui manquait était le rendu, et il a été
     mis en attente de la Slice qui déciderait ce que la surimpression montre.

     Trois surfaces, parce qu'aucune seule ne suffit :
     - la **coque**, quand un parcours est ouvert : elle recouvre les toasts
       (z-index 2147482000 contre 70), donc c'est la seule qu'on regarde ;
     - un **toast**, panneau fermé — le cas ordinaire d'une commande vocale ;
     - une **ligne du panneau Expérimental**, qui survit au toast et porte
       l'heure, le nom, l'issue et le code du refus. */
  const VOICE_OUTCOME=Object.freeze({applied:'appliquée',duplicate:'déjà dans cet état',refused:'refusée'});
  /* Combien de temps le reçu d'une commande vocale est **tenu** dans la coque
     (`note(..., holdMs)`, Slice 10). Les mêmes durées que les toasts de
     l'autre branche, pour que la même commande ne se lise pas deux fois moins
     longtemps selon qu'un parcours est ouvert ou non. Bornées : la RÈGLE ZÉRO
     interdit autant l'état qui ne se voit pas que celui qui dure toujours. */
  const VOICE_NOTE_HOLD_MS=Object.freeze({refused:9000,applied:3000});
  function recordVoiceCommand(entry){
    const source=entry&&typeof entry==='object'?entry:{};
    const record={
      name:String(source.name||'?'),
      outcome:String(source.outcome||'refused'),
      code:source.code?String(source.code):'',
      reason:source.reason?String(source.reason):'',
      lifecycle:source.lifecycle?String(source.lifecycle):'',
      at:Date.now(),
    };
    view.voice=record;
    const said=VOICE_OUTCOME[record.outcome]||record.outcome;
    const line=`Commande vocale « ${record.name} » : ${said}`;
    /* Le chemin **normal** se journalise aussi : un journal qui ne porte que
       les échecs rend « rien dans le journal » indiscernable de « mort ». */
    if(record.outcome==='refused')console.warn('[barehands] commande vocale refusée',record);
    else console.info('[barehands] commande vocale',record);
    const open=openFlow();
    /* **Tenue, sinon elle n'existe pas** (Slice 10). La ligne était écrite
       dans la coque puis effacée par le `paint()` du parcours à l'image
       suivante — 16 à 33 ms à 30-60 images par seconde. La coque couvre le
       panneau (z-index 2147482000 contre 70), et aucun toast n'est posé dans
       ce cas : un refus de commande vocale pendant un tutoriel était donc
       invisible partout, dans le seul cas que la Slice 09 désigne comme celui
       qu'on regarde. `VOICE_NOTE_HOLD_MS` la tient le temps qu'on la lise, et
       pas plus : l'étape doit pouvoir reprendre la parole. Un refus est tenu
       plus longtemps qu'un succès, comme les toasts de l'autre branche. */
    if(open)shell().note(`${line}${record.reason?` — ${record.reason}`:''}`,
      record.outcome==='refused'?'bad':'ok',
      record.outcome==='refused'?VOICE_NOTE_HOLD_MS.refused:VOICE_NOTE_HOLD_MS.applied);
    else if(typeof toast==='function')
      toast({title:line,sub:record.reason||record.code
        ||`Bare Hands est ${LIFECYCLE_LABEL[record.lifecycle]||record.lifecycle||'?'}.`,
        kind:record.outcome==='refused'?'bad':'ok',
        ms:record.outcome==='refused'?9000:3000});
    refreshPanel();
    return record;
  }
  /* Ce que le panneau en dessine. Séparé du reste du statut : une commande
     vocale n'est pas un état du cycle de vie, et les mêler ferait disparaître
     la trace au premier changement d'état. */
  function voiceHtml(){
    const record=view.voice;
    if(!record)
      return '<div class="hint">Aucune commande vocale reçue depuis le chargement de cette page.</div>';
    const when=new Date(record.at).toLocaleTimeString('fr-FR');
    const said=VOICE_OUTCOME[record.outcome]||record.outcome;
    const why=record.outcome==='refused'
      ?` <span class="hint">— ${esc(record.code||'sans code')}${record.reason?` : ${esc(record.reason)}`:''}</span>`:'';
    return `<div class="notice ${record.outcome==='refused'?'bad':'info'}">
      <strong>${esc(when)} · ${esc(record.name)} · ${esc(said)}</strong>${why}
      <div class="hint">Cycle de vie relu après l’appel : <strong>${esc(LIFECYCLE_LABEL[record.lifecycle]||record.lifecycle||'inconnu')}</strong>. La voix et le bouton passent par le même point d’entrée.</div></div>`;
  }

  /* Écrire un réglage : appliqué **tout de suite** au moteur (la main suit
     sans attendre le réseau), puis enregistré. Un échec d'écriture rend
     l'ancienne valeur au moteur *et* à l'écran — laisser le moteur sur une
     valeur que le serveur a refusée ferait mentir la case qu'on vient de
     décocher. Les trois obligations de la règle zéro : vu (bandeau + toast),
     journalisé (console, seul canal de cette page), relâché (`finally`). */
  async function saveSettings(patch){
    /* Une écriture pendant qu'une autre part n'est pas prise — mais elle se
       **dit**. Les contrôles de l'écran sont désarmés pendant l'attente, donc
       seul un appelant sans écran peut arriver ici : la voix (Slice 12) et la
       console. C'est précisément celui à qui un abandon muet ne laisse rien à
       lire, et il rendait `null` comme un refus sans qu'aucun mot ne dise
       lequel des deux. */
    if(view.busy){
      const message='Un réglage Bare Hands est déjà en cours d’enregistrement ; celui-ci n’a pas été pris. Réessayez dans un instant.';
      view.error=message;
      console.warn('[barehands] réglage non pris (écriture en cours)',Object.keys(patch||{}));
      if(typeof toast==='function')
        toast({title:'Réglage Bare Hands non pris',sub:message,kind:'warn',ms:5000});
      refreshPanel();
      return null;
    }
    const previous=view.settings;
    let next=null;
    try{
      /* Un outil **inconnu** se refuse ici, avant toute normalisation.
         `normalizeTool` tolère l'inconnu parce qu'il relit un schéma stocké ;
         une écriture, elle, est une question posée à la table des outils
         (contrat § 8), et la réponse est non. Sans cette ligne, `tool('ciseaux')`
         devenait `pointer`, partait sur le fil **déjà normalisé** — donc le
         refus du serveur était inatteignable depuis la page — et se
         journalisait « réglage enregistré ». Un outil déclaré mais **sans
         moteur** passerait ici et se ferait refuser par le serveur, seul à
         savoir ce qu'il sert : les deux refus gardent leur phrase et leur
         auteur. La table n'en déclare aucun depuis que la couche d'annotation
         est hors V1, mais la porte reste la recette d'extension. */
      if(patch&&patch.tool!==undefined)BH.toolCapability(patch.tool);
      next=BH.normalizeSettings({...previous,...(patch||{})});
      applyToEngine(next);
    }catch(error){
      view.error=`Réglage refusé : ${error&&error.message||error}`;
      console.warn('[barehands] réglage refusé',(error&&error.code)||'',error);
      if(typeof toast==='function')
        toast({title:'Réglage Bare Hands refusé',sub:String(error&&error.message||error),kind:'bad',ms:7000});
      try{applyToEngine(previous)}catch(_error){/* l'ancien a déjà été accepté */}
      refreshPanel();
      return null;
    }
    view.settings=next;view.busy=true;view.error='';
    refreshPanel();
    try{
      const state=await api(API,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify(BH.toServerPayload(next))});
      view.busy=false;
      applyServerState(state);
      console.info('[barehands] réglage enregistré',Object.keys(patch||{}));
      return view.settings;
    }catch(error){
      view.settings=previous;
      try{applyToEngine(previous)}catch(_error){/* l'ancien a déjà été accepté */}
      view.error=`Réglage non enregistré : ${error&&error.message||error}`;
      console.warn('[barehands] écriture des réglages',error);
      if(typeof toast==='function')
        toast({title:'Réglage Bare Hands non enregistré',sub:String(error&&error.message||error),kind:'bad',ms:7000});
      return null;
    }finally{
      view.busy=false;
      refreshPanel();
    }
  }

  /* Nom visible du cycle de vie, lu du contrat plutôt que de l'état interne.
     `starting` fait exception, et c'est voulu des deux côtés : le contrat le
     range sous `off` parce que rien n'interagit et que rien n'est tenu pour de
     bon — mais l'afficher « Éteint » sous un bouton « Allumer et activer »,
     pendant que le statut juste en dessous dit « Barehands démarre… », donnait
     un écran qui se contredit et un bouton qui ne fait rien (`enable()` rend
     `starting` sans attendre le démarrage en vol : le contrôleur se posait en
     veille, jamais en interaction, et l'utilisateur devait recliquer sans
     savoir pourquoi). L'écran nomme donc le démarrage. */
  const LIFECYCLE_LABEL=Object.freeze({off:'Éteint',starting:'Démarrage…',sleep:'En veille',active:'Actif',
    /* Arrêté sans l'avoir demandé : le motif exact reste dans `view.status.code`
       et s'affiche juste en dessous, il n'est pas aplati dans l'état. */
    error:'Interrompu'});
  const lifecycle=()=>BH.lifecycleOfControllerState(controller.state());
  const starting=()=>controller.state()===Core.STATE.STARTING;

  /* RULE ZERO. Le démarrage attend `getUserMedia`, qui n'a pas de délai et ne
     peut pas en avoir : derrière, c'est une invite de permission qu'un humain
     met le temps qu'il veut à lire. Un état qui peut durer doit donc dire
     **depuis combien de temps** il dure — sinon « démarre… » et « bloqué » se
     ressemblent — et **comment en sortir** : ici l'interrupteur du dessus, qui
     annule un démarrage en vol et rend la caméra dès qu'elle arrive. Le
     compteur s'arrête de lui-même dès que l'état change. */
  let startingSince=0,startingTimer=0;
  function stopStartingClock(){
    if(startingTimer){clearInterval(startingTimer);startingTimer=0}
  }
  function watchStartingClock(){
    if(!starting()){stopStartingClock();return}
    if(startingTimer)return;
    startingSince=Date.now();
    startingTimer=setInterval(()=>{
      if(!starting()){stopStartingClock();return}
      refreshPanel();
    },1000);
  }
  const startingSeconds=()=>Math.max(0,Math.round((Date.now()-startingSince)/1000));

  /* Réveil et mise en veille à la main : le second chemin d'activation exigé
     par la décision 4, à côté de la posture en C. La voix empruntera le même
     (`window.JarvisBarehands.activate`) quand son canal existera. */
  async function setAwake(awake){
    view.busy=true;view.error='';refreshPanel();
    try{
      if(awake)await controller.activate();
      else controller.sleep();
    }catch(error){
      view.error=`Activation impossible : ${error&&error.message||error}`;
      console.warn('[barehands] activation',error);
    }
    view.busy=false;refreshPanel();
  }

  /* **R3.** `enabled` est le seul réglage dont l'état moteur ne passe pas par
     `applyToEngine` : la caméra est rendue **avant** l'écriture, exprès, pour
     qu'une décoche libère l'objectif sans attendre le réseau. L'échec
     d'écriture rendait donc l'ancienne valeur au moteur et à l'écran comme
     pour les autres — sauf que pour celui-là « l'ancienne valeur à l'écran »
     recochait une case pendant que la caméra, elle, restait éteinte : case
     cochée, serveur allumé, caméra éteinte, et deux bascules pour en sortir.

     Des deux issues, on ne rallume pas. Rouvrir la caméra (et, au navigateur,
     son invite de permission) parce qu'un **enregistrement** a échoué ferait
     faire à la machine quelque chose que personne n'a demandé, sur le chemin
     le moins sûr de la page. L'écran suit donc le moteur — la caméra est
     éteinte, la case le dit — et la seule chose qui reste divergente, le
     réglage resté « allumé » sur le serveur, est **nommée** : c'est ce que
     l'utilisateur retrouvera au prochain chargement. */
  async function setEnabled(enabled){
    /* **Éteindre éteint, quel que soit l'état de départ.** La garde qui
       protège « Caméra refusée » d'être écrasée par « Barehands arrêté —
       caméra libérée » ne vit pas ici : elle vit dans `controller.disable()`
       (`wasOn=isEngagedState(state)`), qui depuis `ERROR` émet `off` et non
       `disabled` — et `off` n'est pas notifié par `onStatus`. Aucun toast ne
       part donc, et celui de la panne reste à l'écran avec sa cause réelle.

       Conditionner l'appel ici faisait tout autre chose : depuis `ERROR`, le
       contrôleur restait garé en panne après que l'utilisateur ait
       explicitement demandé l'extinction — interrupteur à faux, écran rouge.
       C'est l'état courant qui mentait pour continuer de décrire un événement
       passé. Le toast est le journal de l'événement, l'écran est l'état
       courant : deux métiers. Depuis `OFF` ou `ERROR`, `teardown()` ne rend
       rien puisque rien n'est tenu, et `generation+=1` invalide au passage un
       démarrage encore en vol. */
    /* **Ce qui était vraiment tenu et vient d'être rendu**, lu *avant*
       l'extinction — et gardé séparé, parce que ce n'est pas la même question
       que « faut-il éteindre ». C'est celle qui gouverne la phrase « la caméra
       a bien été libérée, c'est le réglage qui n'a pas été enregistré » plus
       bas : sans objectif ouvert, cette phrase-là n'aurait rien à dire. */
    const released=!enabled&&Core.isEngagedState(controller.state());
    if(!enabled)controller.disable();
    const saved=await saveSettings({enabled});
    if(saved!==null||!released)return saved;
    view.enabled=false;
    view.error=`${view.error} La caméra a bien été libérée ; c'est le réglage qui n'a pas été enregistré, et Bare Hands sera de nouveau allumé au prochain chargement.`;
    /* Le bandeau ne suffit pas : ce chemin s'atteint aussi le panneau fermé
       (`JarvisBarehands.disable()`, donc la voix de la Slice 12), où le toast
       est le seul canal. Deux faits, deux phrases — celle de `saveSettings`
       dit pourquoi l'écriture a échoué, celle-ci dit où en est la caméra. */
    if(typeof toast==='function')
      toast({title:'Bare Hands se rallumera au prochain chargement',
        sub:'La caméra est bien libérée, mais le réglage n’a pas pu être enregistré.',
        kind:'warn',ms:7000});
    refreshPanel();
    return saved;
  }

  function statusHtml(){
    const s=view.status,cls=s.state==='error'?'bad':'info';
    const error=view.error?`<div class="notice bad">${esc(view.error)}</div>`:'';
    return `${error}${storedHtml()}<div class="notice ${cls}"><strong>${esc(s.title)}</strong><div class="hint">${esc(s.message)}</div></div>`;
  }

  function assetsHtml(){
    const assets=view.assets;
    return assets&&!assets.installed
      ?`<div class="notice bad"><strong>Modèle MediaPipe absent</strong><div class="hint">Fichiers manquants : ${assets.missing.map(esc).join(', ')}. Lancez <code>${esc(assets.install_hint)}</code> puis réessayez.</div></div>`:'';
  }

  /* Bandeau de cycle de vie : où l'on en est, et le bouton qui en change.
     Éteint, le bouton allume puis réveille d'un coup — l'interrupteur du
     dessus reste le seul à écrire le réglage sur le serveur. */
  function lifecycleHtml(){
    const booting=starting(),at=booting?Core.STATE.STARTING:lifecycle();
    const awake=at===BH.LIFECYCLE.ACTIVE;
    /* Pendant le démarrage le bouton est désarmé plutôt que trompeur : il
       n'aurait rien à activer qui ne soit déjà en route. */
    const label=booting?`Démarrage… ${startingSeconds()} s`
      :awake?'Mettre en veille'
      :at===BH.LIFECYCLE.SLEEP?'Activer l’interaction'
      :at===BH.LIFECYCLE.ERROR?'Réessayer':'Allumer et activer';
    /* Une panne ne se lit pas « éteint » : l'état le dit, et le code du motif
       reste visible à côté du nom. */
    const why=at===BH.LIFECYCLE.ERROR&&view.status&&view.status.code?` · ${esc(view.status.code)}`:'';
    const hint=booting
      ?'Chargement du modèle et ouverture de la caméra. Si le navigateur attend votre autorisation, répondez à l’invite ; pour annuler, décochez l’interrupteur ci-dessus — la caméra est rendue dès qu’elle arrive.'
      :`Éteint, la caméra est libérée. En veille, elle ne sert qu'au guetteur de réveil (${Math.round(1000/BH.WAKE_INTERVAL_MS)} images par seconde, aucun clic).`;
    return `<div class="field inline" style="align-items:center;gap:10px;margin-top:2px">
      <button type="button" class="action${awake||booting?'':' primary'}" id="barehandsWake" data-barehands-wake ${view.busy||booting?'disabled':''}>${esc(label)}</button>
      <div><div class="hint">Cycle de vie : <strong>${esc(LIFECYCLE_LABEL[at]||at)}</strong>${why}</div>
      <div class="hint">${esc(hint)}</div></div>
    </div>`;
  }

  /* ------------------------------------------------------------------
     Outils et réglages (Slice 07, décisions 24 et 25).

     **Deux concepts, deux sections, et la distinction est visible** : l'outil
     dit ce que la main veut dire *maintenant* ; les réglages disent comment
     Bare Hands se comporte. Les fondre en une seule liste ferait du choix d'un
     outil un réglage de plus, et du retour en veille une façon de tenir la
     main — ce que la décision 25 refuse précisément.

     Ce que chaque outil fait, en français, à côté de ce qu'il **exige** : le
     contrat possède le nom et la capacité (§ 8), l'écran possède la phrase.
     Une capacité sans moteur n'est pas grisée en silence — elle dit pourquoi. */
  const TOOL_HINT=Object.freeze({
    pointer:'Contextuel : clic, glissement, défilement ou sélection selon ce qu’il y a sous la main. C’est le comportement par défaut, et il ne force rien.',
    pan:'Le contenu suit la main. Une cible qui ne défile pas est refusée, avec un mot à l’écran.',
    select:'Désigner et sélectionner. Réservé aux champs de saisie et aux étoiles de la scène ; ailleurs, refusé.',
  });
  const UNAVAILABLE='Aucun moteur derrière cet outil en V1.';

  function toolsHtml(){
    const active=view.settings.tool;
    const buttons=BH.describeTools().map(tool=>{
      const on=tool.id===active;
      const off=!tool.installed||view.busy;
      /* Motif « groupe de boutons radio » : un seul arrêt de tabulation, les
         flèches parcourent la palette. Sans le `tabindex` mouvant, un lecteur
         d'écran annonce un groupe de radios que le clavier traverse un par un,
         c'est-à-dire une promesse que la page ne tient pas. */
      return `<button type="button" role="radio" class="action small${on?' primary':''}" `
        +`data-barehands-tool="${esc(tool.id)}" aria-checked="${on?'true':'false'}" `
        +`tabindex="${on?0:-1}" `
        +`${off?'disabled':''} ${tool.installed?'':`title="${esc(UNAVAILABLE)}"`}>`
        +`${esc(tool.label)}${tool.installed?'':' <span class="tag">—</span>'}</button>`;
    }).join('');
    return `<section class="bh-section" id="barehandsTools">
      <h3>Outils</h3>
      <div class="hint" style="margin-bottom:12px">Ce que la main veut dire. Distinct des réglages : un outil se choisit en pleine session et ne change pas la façon dont Bare Hands se comporte, seulement le sens de ce qu’on saisit. Les bords et les coins d’un cadre restent des poignées quel que soit l’outil.</div>
      <div class="row" role="radiogroup" aria-label="Outil Bare Hands" style="flex-wrap:wrap;gap:8px">${buttons}</div>
      <div class="hint" style="margin-top:10px" id="barehandsToolHint">${esc(TOOL_HINT[active]||'')}</div>
    </section>`;
  }

  /* ------------------------------------------------------------------
     Calibration (Slice 08, décisions 26 à 32), sa propre section.

     **Décision 27 : optionnelle et explicite.** Il y a un bouton, et rien ne
     se mesure avant qu'on l'ait pressé — ni au démarrage, ni en tâche de fond.
     La même porte sert à la voix (canal de commandes, Slice 12).

     Ce que l'écran doit dire, et qui n'existait pas : **ce qui est calibré**.
     « Profil enregistré » sans dire quoi laisse l'utilisateur incapable de
     savoir si sa main gauche est mesurée, si une étape a échoué, ou si ce
     qu'il ressent vient de ses mesures ou des valeurs d'usine. */
  const STAGE_LABEL=Object.freeze({
    neutral:'Repos',c_pose:'Posture de réveil',
    pinch_primary:'Pincement pouce-index',pinch_secondary:'Pincement pouce-majeur',
    aim:'Visée',drag:'Glissement',resize:'Deux mains',
  });
  const MEASURE_LABEL=Object.freeze({
    pressRatio:'seuil de pincement',releaseRatio:'seuil de relâchement',
    secondaryPressRatio:'seuil de clic droit',secondaryReleaseRatio:'relâchement du clic droit',
    jitterPx:'tremblement au repos',travelSlopNorm:'tolérance clic/glissement',
    reachNorm:'portée dans l’image',quality:'qualité de la mesure',
  });
  function handSummary(profile,handedness){
    const measured=BH.PROFILE_MEASURED_KEYS
      .filter(key=>BH.profileValue(profile,handedness,key,null)!==null)
      .map(key=>MEASURE_LABEL[key]||key);
    return measured;
  }
  /* L'état du profil seul : c'est ce que `refreshPanel` redessine, et la
     section entière n'est écrite qu'au premier dessin. Redessiner la section
     dans son propre conteneur l'imbriquerait dans elle-même à chaque
     rafraîchissement. */
  function profileStateHtml(){
    const profile=view.profile;
    const failed=profile?BH.STAGES.filter(stage=>
      profile.stages[stage].status===BH.STAGE_STATUS.FAILED):[];
    /* Trois états, trois phrases — et jamais la même pour deux causes
       différentes : on ne sait pas encore, on sait qu'il n'y a rien, on sait
       ce qu'il y a. */
    const state=view.profileError
      ?`<div class="notice bad"><strong>Profil illisible</strong><div class="hint">${esc(view.profileError)} Bare Hands utilise ses seuils d’usine en attendant.</div></div>`
      :profile===null
        ?'<div class="hint">Lecture du profil…</div>'
        :!profile.calibrated
          ?'<div class="hint">Aucune mesure enregistrée : Bare Hands utilise ses seuils d’usine, les mêmes pour tout le monde.</div>'
          :`<div class="hint">Calibré${profile.updatedAt?` le ${esc(new Date(profile.updatedAt).toLocaleString('fr-FR'))}`:''}.</div>
             <ul class="hint" style="padding-left:18px;margin:8px 0 0">${
               BH.HANDEDNESSES.map(handedness=>{
                 const measured=handSummary(profile,handedness);
                 return measured.length
                   ?`<li><strong>${esc(HAND_LABEL[handedness])}</strong> : ${esc(measured.join(', '))}</li>`:'';
               }).join('')}</ul>
             ${failed.length?`<div class="hint" style="margin-top:8px">Étapes non mesurées, qui gardent les valeurs d’usine : ${
               esc(failed.map(stage=>STAGE_LABEL[stage]||stage).join(', '))}.</div>`:''}`;
    return state;
  }
  function calibrationHtml(){
    const disabled=!view.settings.calibrationEnabled;
    return `<section class="bh-section" id="barehandsCalibration">
      <h3>Calibration</h3>
      <div class="hint" style="margin-bottom:12px">Une mesure courte qui adapte les seuils de Bare Hands à <strong>votre</strong> main. Elle ne démarre que si vous la lancez, ne conserve <strong>aucune image ni vidéo</strong> — seulement des nombres dérivés — et chaque étape peut être passée : ce qui n’est pas mesuré garde la valeur d’usine.</div>
      <div id="barehandsProfile">${profileStateHtml()}</div>
      <div class="field inline" style="align-items:center;gap:10px;margin-top:14px">
        <button type="button" class="action small primary" id="barehandsCalibrate" ${disabled||view.busy?'disabled':''}
          ${disabled?`title="${esc('Cochez « Proposer la calibration » ci-dessus pour l’activer.')}"`:''}>Calibrer…</button>
        <button type="button" class="action small" id="barehandsProfileReset" ${view.busy||!(view.profile&&view.profile.calibrated)?'disabled':''}>Effacer le profil</button>
        <div class="hint">${disabled
          ?'La calibration est désactivée dans les réglages ci-dessus.'
          :'La caméra s’allume au lancement et le parcours prend environ une minute. Vous voyez les mesures avant qu’elles soient enregistrées.'}</div>
      </div>
    </section>`;
  }
  const HAND_LABEL=Object.freeze({left:'Main gauche',right:'Main droite',unknown:'Main non étiquetée'});

  /* **Le tutoriel, et ce que `tutorialSeen` veut dire** (Slice 09).

     Le réglage traversait la route, le fichier et la normalisation sans qu'un
     seul parcours ne le lise ; c'est ici qu'il est lu. Il dit **« cet
     utilisateur a traversé le tutoriel au moins une fois jusqu'au
     récapitulatif »** — pas « il a réussi » (passer une étape reste vu :
     l'invitation de la scène peut n'avoir ni étoile ni cadre), et pas « on le
     lui a proposé » (quitter au milieu n'écrit rien). Il ne déclenche **aucun**
     lancement automatique : ce qu'il change est ce que cette section dit. */
  function tutorialState(){
    return {running:!!(tutorial&&tutorial.isRunning()),
      step:tutorial?tutorial.stepId():null,
      seen:!!view.settings.tutorialSeen,
      /* Combien d'observations le parcours a reçues : c'est ce qui distingue
         « nourri à la cadence des images » de « nourri par la seule
         minuterie », qui s'écrivent pareil et n'apprennent pas la même
         chose — la seconde rate la quasi-totalité des clics. */
      observed:tutorial?tutorial.observations():0,
      installed:!!TUTO,
      steps:TUTO?TUTO.STEPS.length:0};
  }
  function tutorialStateHtml(){
    const state=tutorialState();
    if(!state.installed)
      return '<div class="notice bad"><strong>Tutoriel indisponible</strong><div class="hint">Son module ne s’est pas installé dans cette page. Rechargez le Control Center ; la console porte la cause exacte. Le reste de Bare Hands fonctionne normalement.</div></div>';
    if(state.running)
      return `<div class="notice info"><strong>Tutoriel en cours</strong><div class="hint">Étape « ${esc(state.step||'?')} ». La surimpression est à l’écran ; quittez-la par « Quitter », la touche Échap, ou « ferme la surimpression ».</div></div>`;
    if(state.seen)
      return '<div class="hint">Vous avez déjà fait le tour du tutoriel. Vous pouvez le relancer quand vous voulez ; décocher « Tutoriel déjà vu » ci-dessus remet l’invitation.</div>';
    return `<div class="notice info"><strong>Vous n’avez pas encore fait le tutoriel</strong><div class="hint">${esc(String(state.steps))} étapes guidées pour apprendre le vocabulaire complet : réveil, cible, clic, clic droit, contenu, étoile, cadre, redimensionnement à deux mains, outils et sorties. Rien n’est mesuré et <strong>aucun paramètre de calibration n’est touché</strong>.</div></div>`;
  }
  function tutorialHtml(){
    const state=tutorialState();
    return `<section class="bh-section" id="barehandsTutorial">
      <h3>Tutoriel</h3>
      <div class="hint" style="margin-bottom:12px">Un parcours guidé qui apprend les gestes de la V1, dans la même surimpression que la calibration — mais il ne mesure rien et n’écrit aucun profil. Chaque étape peut être passée, et on en sort à tout moment.</div>
      <div id="barehandsTutorialState">${tutorialStateHtml()}</div>
      <div class="field inline" style="align-items:center;gap:10px;margin-top:14px">
        <button type="button" class="action small${state.seen||!state.installed?'':' primary'}" id="barehandsTutorialStart" ${view.busy||state.running||!state.installed?'disabled':''}>${state.seen?'Revoir le tutoriel…':'Lancer le tutoriel…'}</button>
        <div class="hint">Bare Hands doit être allumé et sa caméra démarrée : la première étape est le geste de réveil, et le tutoriel ne le fait pas à votre place.</div>
      </div>
    </section>`;
  }

  const seconds=ms=>`${Math.round(Number(ms)/1000)} s`;
  /* La portée réelle de l'assistance, en pixels, à côté du facteur : « 0,5 »
     ne dit rien, « 24 px » dit ce que la main gagne. Le facteur 2 est celui du
     moteur (Slice 05), pas un nombre inventé ici. */
  const assistPx=value=>`${Math.round(Core.DEFAULTS.targetAssistPx*2*Number(value))} px`;
  const slopPx=value=>`${Math.round(Core.DEFAULTS.dragSlopPx/Number(value))} px`;
  const decimal=value=>String(Number(value).toFixed(2)).replace('.',',');
  /* Ce que dit le chiffre à côté d'un curseur. Une seule table : le dessin
     initial et la mise à jour pendant qu'on tire la lisent toutes les deux,
     sans quoi la valeur affichée au chargement et celle affichée en tirant
     auraient deux formulations. */
  const RANGE_TEXT=Object.freeze({
    assistance:v=>`× ${decimal(v)} · ${assistPx(v)}`,
    sensitivity:v=>`× ${decimal(v)} · glissement à ${slopPx(v)}`,
    sleepTimeoutMs:v=>seconds(v),
  });
  function paintRangeValue(key,value){
    const el=document.querySelector(`[data-barehands-value="${key}"]`);
    if(el&&RANGE_TEXT[key])el.textContent=RANGE_TEXT[key](value);
  }

  function rangeHtml(key,label,hint){
    const bound=BH.SETTINGS_BOUNDS[key];
    return `<div class="field" style="margin-bottom:14px">
      <label for="bh_${esc(key)}">${esc(label)} · <strong data-barehands-value="${esc(key)}">${esc(RANGE_TEXT[key](view.settings[key]))}</strong></label>
      <input type="range" id="bh_${esc(key)}" data-barehands-range="${esc(key)}"
        min="${bound.min}" max="${bound.max}" step="${bound.step}" value="${Number(view.settings[key])}"
        ${view.busy?'disabled':''} style="width:100%;max-width:320px">
      <div class="hint">${esc(hint)}</div></div>`;
  }

  function checkHtml(key,label,hint){
    return `<div class="field inline"><input type="checkbox" id="bh_${esc(key)}" data-barehands-check="${esc(key)}"
        ${view.settings[key]?'checked':''} ${view.busy?'disabled':''}>
      <div><label for="bh_${esc(key)}">${esc(label)}</label>
      <div class="hint">${esc(hint)}</div></div></div>`;
  }

  function settingsHtml(){
    return `<section class="bh-section" id="barehandsSettings">
      <h3>Réglages</h3>
      <div class="hint" style="margin-bottom:14px">Comment Bare Hands se comporte. Enregistrés immédiatement et appliqués à chaud, sans recharger la page.</div>
      ${checkHtml('targetPreview','Aperçu de la cible',
        'Le cadre de l’objet visé et la zone retenue s’affichent dès qu’un pincement s’amorce. Éteint, la cible continue d’être résolue — seul le dessin disparaît, l’action reste la même.')}
      ${rangeHtml('assistance','Assistance de visée',
        'Portée au-delà du cadre où une petite erreur de visée compte quand même. À 0 il faut viser dans l’objet ; le défaut rend exactement la portée d’usine.')}
      ${rangeHtml('sensitivity','Sensibilité du geste',
        'Combien la main doit parcourir avant qu’un contact devienne un glissement plutôt qu’un clic. Plus sensible, moins de mouvement toléré dans un clic. Le défaut rend les seuils d’usine.')}
      ${rangeHtml('sleepTimeoutMs','Retour en veille',
        'Sans main sûre pendant ce temps, l’interaction retourne en veille. La caméra reste ouverte pour le guetteur de réveil ; seul « Éteint » la libère.')}
      ${checkHtml('diagnostics','Lecture de diagnostic à l’écran',
        'Qualité, vitesse et immobilité de chaque main suivie, en bas à droite pendant l’interaction. Rien n’est enregistré : c’est une lecture, pas un enregistreur.')}
      ${checkHtml('calibrationEnabled','Proposer la calibration',
        'Garde la calibration optionnelle et explicite : Bare Hands ne mesurera jamais votre main sans que vous l’ayez lancée.')}
      ${checkHtml('tutorialSeen','Tutoriel déjà vu',
        'Coché dès que vous avez traversé le tutoriel jusqu’à son récapitulatif. Décochez pour que l’invitation revienne — il ne se lance jamais tout seul.')}
      <div class="field inline" style="align-items:center;gap:10px;margin-top:14px">
        <button type="button" class="action small" id="barehandsReset" ${view.busy?'disabled':''}>Réinitialiser les réglages</button>
        <div class="hint">Rend aux sept réglages ci-dessus et à l’outil leur valeur d’usine. L’interrupteur ci-dessus n’y touche pas : réinitialiser n’éteint pas la caméra. Le profil de calibration a son propre bouton ci-dessous : ce sont deux choses distinctes.</div>
      </div>
    </section>
    ${calibrationHtml()}
    ${tutorialHtml()}
    ${recordHtml()}`;
  }

  function panelHtml(){
    const missing=assetsHtml();
    return `<section>
      <h3>Barehands · mode test</h3>
      <div class="hint" style="margin-bottom:14px">Piloter l'interface à mains nues. La webcam suit vos mains <strong>localement</strong> (MediaPipe, aucun envoi vers un service cloud). Le réglage est enregistré immédiatement et reste actif au prochain chargement de la page.</div>
      <div class="field inline"><input type="checkbox" id="f_barehands" data-barehands-toggle ${view.enabled?'checked':''} ${view.busy?'disabled':''}>
        <div><label for="f_barehands">Activer Barehands (mode test) <span class="tag warn">TEST</span></label>
        <div class="hint">Désactivé par défaut. Éteint, la caméra est libérée et les jetons disparaissent. Activé, Barehands démarre <strong>en veille</strong> : la caméra guette le geste de réveil, sans cliquer.</div></div></div>
      <div id="barehandsLifecycle">${lifecycleHtml()}</div>
      <div id="barehandsStatus">${statusHtml()}</div>
      <div id="barehandsAssets">${missing}</div>
      <div class="hint" style="margin-top:14px">Dernière commande vocale reçue par cette page :</div>
      <div id="barehandsVoice">${voiceHtml()}</div>
    </section>
    ${toolsHtml()}
    ${settingsHtml()}
    <section class="bh-section">
      <h3>Gestes</h3>
      <ul class="hint" style="padding-left:18px;line-height:1.7">
        <li><strong>Réveil :</strong> en veille, formez un C avec le pouce et l'index — écartés sans se toucher, index déplié — et tenez une seconde. L'anneau se remplit autour de la main ; relâcher avant la fin annule.</li>
        <li>Chaque main visible affiche un jeton rond qui suit le bout de l'index ; il grossit au survol d'un élément cliquable.</li>
        <li>Rapprocher pouce et index remplit l'anneau du jeton (pincement en cours) ; le jeton se fige pour viser.</li>
        <li>Pincement franc : clic sous le jeton (onde visuelle). Rouvrir les doigts avant de recliquer.</li>
        <li>Un jeton <strong>pâle et pointillé</strong> signale une main que le suivi ne tient pas pour sûre — elle sort du cadre, elle est trop loin, ou elle vient d'apparaître. Elle est affichée et cliquable, mais elle ne maintient pas l'interaction éveillée : la pastille compte alors « 1/2 ».</li>
        <li>Sans main <em>sûre</em> vue pendant 30 secondes, l'interaction retourne en veille ; la caméra reste ouverte pour le guetteur.</li>
        <li><strong>Reconnus, pas encore agissants :</strong> le pincement <strong>pouce-majeur</strong> (clic droit), la main ouverte, le poing, la double fermeture et le claquement des deux paumes. Ils sont mesurés et publiés à chaque image, mais aucune action ne leur est encore liée — <code>JarvisBarehands.gestures()</code> et <code>JarvisBarehands.pinch()</code> les montrent depuis la console.</li>
      </ul>
      <div class="hint" style="margin-top:10px">Limites du mode test : pas de glisser-déposer ni de défilement ; une liste déroulante ne s'ouvre pas au pincement (le navigateur l'interdit aux clics simulés) ; le visage ai-visualizer (iframe) ne reçoit pas les clics.</div>
    </section>`;
  }

  /* Le bandeau est redessiné à chaque rafraîchissement : son bouton est neuf à
     chaque fois, donc réarmé à chaque fois. */
  function bindWake(){
    const button=document.getElementById('barehandsWake');
    if(button)button.addEventListener('click',()=>setAwake(lifecycle()!==BH.LIFECYCLE.ACTIVE));
  }

  /* Tous les contrôles de l'onglet, armés une fois à l'ouverture. Les deux
     sections d'outils et de réglages ne sont **jamais** redessinées ensuite :
     leurs valeurs sont remises à jour en place. Redessiner arracherait le
     focus et le curseur qu'on est en train de tirer, exactement au moment où
     l'on s'en sert. */
  function bindPanel(){
    const toggle=document.getElementById('f_barehands');
    if(toggle)toggle.addEventListener('change',()=>setEnabled(toggle.checked));
    for(const button of document.querySelectorAll('[data-barehands-tool]')){
      button.addEventListener('click',()=>saveSettings({tool:button.getAttribute('data-barehands-tool')}));
      button.addEventListener('keydown',event=>moveTool(button,event));
    }
    for(const box of document.querySelectorAll('[data-barehands-check]'))
      box.addEventListener('change',()=>saveSettings({[box.getAttribute('data-barehands-check')]:box.checked}));
    for(const range of document.querySelectorAll('[data-barehands-range]')){
      const key=range.getAttribute('data-barehands-range');
      /* `input` ne fait que dire le chiffre pendant qu'on tire ; `change`
         enregistre. Écrire à chaque pixel enverrait une requête par image, et
         le serveur répondrait des valeurs déjà périmées. */
      range.addEventListener('input',()=>paintRangeValue(key,Number(range.value)));
      range.addEventListener('change',()=>saveSettings({[key]:Number(range.value)}));
    }
    const reset=document.getElementById('barehandsReset');
    if(reset)reset.addEventListener('click',resetSettings);
    /* Décision 27 : la calibration a une **porte**, et c'est la même que celle
       de la voix. Un bouton qui appellerait autre chose que `startCalibration`
       serait une seconde implantation du parcours. */
    const calibrate=document.getElementById('barehandsCalibrate');
    if(calibrate)calibrate.addEventListener('click',()=>{startCalibration()});
    const wipe=document.getElementById('barehandsProfileReset');
    if(wipe)wipe.addEventListener('click',resetProfile);
    /* Décision 6 : le tutoriel a une **porte**, et c'est la même que celle de
       la voix. Un bouton qui appellerait autre chose que `startTutorial`
       serait une seconde implantation du parcours — ce que cette Slice
       interdit explicitement. */
    const teach=document.getElementById('barehandsTutorialStart');
    if(teach)teach.addEventListener('click',()=>{startTutorial()});
    /* Slice 10 : une seule porte pour l'enregistrement, comme pour les deux
       parcours. Un bouton qui appellerait le module directement serait une
       seconde implantation — et celle-ci sauterait le refus « Bare Hands est
       éteint » et l'ouverture de la couture de mesures. */
    const tape=document.getElementById('barehandsRecordStart');
    if(tape)tape.addEventListener('click',()=>{startRecording()});
    const untape=document.getElementById('barehandsRecordStop');
    if(untape)untape.addEventListener('click',()=>{stopRecording()});
    bindWake();
  }

  /* Les flèches parcourent la palette et **sautent** ce qui n'a pas de moteur :
     s'arrêter sur un outil qu'on ne peut pas choisir est un cul-de-sac au
     clavier, alors que la souris, elle, voit tout de suite qu'il est grisé. */
  function moveTool(button,event){
    const step=event.key==='ArrowRight'||event.key==='ArrowDown'?1
      :event.key==='ArrowLeft'||event.key==='ArrowUp'?-1:0;
    if(!step)return;
    if(typeof event.preventDefault==='function')event.preventDefault();
    const list=[...document.querySelectorAll('[data-barehands-tool]')].filter(el=>!el.disabled);
    const at=list.indexOf(button);
    if(at<0||list.length<2)return;
    const next=list[(at+step+list.length)%list.length];
    if(typeof next.focus==='function')try{next.focus()}catch(_error){/* retiré entre-temps */}
    saveSettings({tool:next.getAttribute('data-barehands-tool')});
  }

  function refreshTools(){
    const active=view.settings.tool;
    for(const button of document.querySelectorAll('[data-barehands-tool]')){
      const id=button.getAttribute('data-barehands-tool');
      const on=id===active;
      button.classList.toggle('primary',on);
      button.setAttribute('aria-checked',on?'true':'false');
      button.setAttribute('tabindex',on?'0':'-1');
      /* Un outil sans moteur reste **dessiné** et désarmé : le retirer de la
         palette ferait croire qu'il n'existe pas, alors qu'il est au contrat
         et qu'il arrive. Son titre dit pourquoi il ne se choisit pas. */
      button.disabled=!BH.toolInstalled(id)||view.busy;
    }
    const hint=document.getElementById('barehandsToolHint');
    if(hint)hint.textContent=TOOL_HINT[active]||'';
  }

  function refreshSettings(){
    for(const box of document.querySelectorAll('[data-barehands-check]')){
      const key=box.getAttribute('data-barehands-check');
      box.checked=!!view.settings[key];box.disabled=view.busy;
    }
    for(const range of document.querySelectorAll('[data-barehands-range]')){
      const key=range.getAttribute('data-barehands-range');
      // Le curseur qu'on tire garde sa position : c'est la main qui commande.
      if(document.activeElement!==range)range.value=String(view.settings[key]);
      range.disabled=view.busy;
      paintRangeValue(key,Number(range.value));
    }
    const reset=document.getElementById('barehandsReset');
    if(reset)reset.disabled=view.busy;
  }

  /* Réinitialiser, c'est rendre leur valeur d'usine aux réglages — **pas**
     éteindre la caméra. `enabled` est reporté tel quel : un bouton qui coupe
     la webcam sans l'annoncer n'est pas une réinitialisation, c'est une
     extinction déguisée. Le profil de calibration n'existe pas encore : il n'y
     a rien d'autre à effacer, et l'écran le dit plutôt que de le laisser
     croire. */
  async function resetSettings(){
    const ok=typeof confirmDialog!=='function'||await confirmDialog({
      title:'Réinitialiser les réglages Bare Hands ?',
      lines:['Les réglages et l’outil reprennent leur valeur d’usine.',
        'L’interrupteur ne bouge pas : la caméra reste dans l’état où elle est.'],
      confirmLabel:'Réinitialiser'});
    if(!ok)return;
    const saved=await saveSettings({...BH.SETTINGS_DEFAULTS,enabled:view.settings.enabled});
    if(saved&&typeof toast==='function')
      toast({title:'Réglages Bare Hands réinitialisés',sub:'Valeurs d’usine restaurées.',kind:'ok',ms:3500});
  }

  function refreshPanel(){
    /* **La couture d'abord, avant le garde-fou.** Tout ce qui change le cycle
       de vie finit ici — `onStatus`, `setAwake`, `setEnabled`, `saveSettings`,
       `applyServerState`, l'horloge de démarrage —, mais la ligne suivante ne
       parle que du panneau : publier après elle n'aurait atteint personne tant
       que l'onglet Expérimental est fermé, c'est-à-dire presque toujours.
       Un instantané inchangé ne repart pas (`publishLifecycle` déduplique),
       donc les chemins qui repeignent sans changer d'état — un curseur qu'on
       tire — ne réveillent aucun abonné. */
    publishLifecycle();
    if(typeof SET==='undefined'||!SET.open||SET.tab!==TAB_ID)return;
    const toggle=document.getElementById('f_barehands');
    if(toggle){toggle.checked=view.enabled;toggle.disabled=view.busy}
    const life=document.getElementById('barehandsLifecycle');
    if(life){life.innerHTML=lifecycleHtml();bindWake()}
    const status=document.getElementById('barehandsStatus');
    if(status)status.innerHTML=statusHtml();
    const assets=document.getElementById('barehandsAssets');
    if(assets)assets.innerHTML=assetsHtml();
    const profile=document.getElementById('barehandsProfile');
    if(profile)profile.innerHTML=profileStateHtml();
    const calibrate=document.getElementById('barehandsCalibrate');
    if(calibrate)calibrate.disabled=!view.settings.calibrationEnabled||view.busy;
    const wipe=document.getElementById('barehandsProfileReset');
    if(wipe)wipe.disabled=view.busy||!(view.profile&&view.profile.calibrated);
    const voice=document.getElementById('barehandsVoice');
    if(voice)voice.innerHTML=voiceHtml();
    const teaching=document.getElementById('barehandsTutorialState');
    if(teaching)teaching.innerHTML=tutorialStateHtml();
    const teach=document.getElementById('barehandsTutorialStart');
    if(teach){
      const state=tutorialState();
      teach.disabled=view.busy||state.running||!state.installed;
      teach.textContent=state.seen?'Revoir le tutoriel…':'Lancer le tutoriel…';
    }
    const taping=document.getElementById('barehandsRecordState');
    if(taping)taping.innerHTML=recordStateHtml();
    const tape=document.getElementById('barehandsRecordStart');
    const untape=document.getElementById('barehandsRecordStop');
    if(tape||untape){
      const state=recordState();
      if(tape)tape.disabled=view.busy||state.recording||!state.installed;
      if(untape)untape.disabled=!state.recording;
    }
    refreshTools();refreshSettings();
  }

  function installSettingsTab(){
    if(typeof TABS==='undefined'||!Array.isArray(TABS)||TABS.some(tab=>tab.id===TAB_ID))return;
    TABS.push({id:TAB_ID,label:'Expérimental',save:false});
    const baseRenderTab=renderTab;
    renderTab=async function(){
      if(SET.tab!==TAB_ID)return baseRenderTab();
      if(typeof destroyAgentCatalog==='function')destroyAgentCatalog();
      SET.renderRevision=(SET.renderRevision||0)+1;
      modalSave.style.display='none';
      modalSub.textContent='Fonctions en test : appliquées et enregistrées immédiatement.';
      modalContent.innerHTML=panelHtml();
      bindPanel();
      say('','');
      // Relire la présence des assets sans redessiner l'onglet.
      api(API).then(state=>{applyAssets(state);refreshPanel()}).catch(()=>{});
    };
  }

  window.JarvisBarehands=Object.freeze({
    version:2,core:Core,contracts:BH,
    state:()=>({enabled:view.enabled,status:view.status,assets:view.assets,
      controller:controller.state(),lifecycle:lifecycle()}),
    /* **Ce que le moteur applique**, par opposition à `settings()`, qui dit ce
       que le fichier contient. Les deux doivent coïncider, et jusqu'ici rien
       ne permettait de le vérifier : cinq câblages de `applyToEngine`
       pouvaient disparaître sans qu'aucune lecture ne change, parce que la
       seule façon de relire le moteur était de le reconfigurer. Un réglage
       qu'on ne peut pas relire là où il agit est un réglage qu'on ne peut pas
       dire branché. */
    engine:()=>controller.options(),
    enable:()=>setEnabled(true),disable:()=>setEnabled(false),
    /* Réveil et veille sans passer par l'écran : point d'entrée du bouton, et
       plus tard du canal de commandes de la voix (Slice 12). */
    activate:()=>setAwake(true),sleep:()=>setAwake(false),
    lifecycle,
    /* Traits du dernier instant, par main : identité de piste stable, position
       brute **et** filtrée, vitesse, immobilité et qualité (architecture §3,
       §12). C'est ce que la calibration de la Slice 08 mesurera et ce qu'un
       réglage de filtre se relit pour savoir ce qu'il a changé — un filtre
       dont on ne voit que la sortie ne se règle pas. Vide hors interaction. */
    diagnostics:()=>controller.features().map(BH.adapters.motionFromCoreToken),
    /* Gestes et pincements du dernier instant (Slice 04), **publiés à travers
       le contrat** : `createGestureEvent` et `createPinchEvent` sont ce qui
       traverse les Slices, le bloc pur n'ayant que sa forme de travail (il est
       chargé seul par les tests node et ne peut pas lire le contrat). Les faire
       passer ici, c'est refuser une forme fausse au bord du moteur plutôt que
       trois Slices plus loin — et un test vérifie que **tout** ce que le moteur
       émet est accepté tel quel par ces deux fabriques.
       `slot` vient de l'allocateur de la page : le bloc pur ne connaît pas les
       fentes de pointeur, et une fente inventée volerait un `pointerId`. */
    gestures:()=>{
      const out=controller.semantics();
      return Object.freeze({
        events:out.gestures.events.map(BH.createGestureEvent),
        suppressed:out.gestures.suppressed.map(event=>Object.freeze({
          ...BH.createGestureEvent(event),reason:event.reason})),
        postures:out.gestures.postures,
      });
    },
    pinch:()=>{
      const out=controller.semantics();
      return Object.freeze({
        events:out.pinch.events.map(event=>
          BH.createPinchEvent({...event,slot:interactionView.slotOf(event.handTrackId)})),
        contacts:out.pinch.contacts,
      });
    },
    /* Slice 05. Ce que la Slice 06 lira pour ouvrir une capture : une cible
       par main et par canal, publiée **à travers le contrat** comme les gestes
       et les contacts, plus ce que le contrat ne porte pas (`handTrackId`,
       `channel`, `locked`, `feedback`). Vide hors intention — décision 3, et
       c'est aussi la preuve qu'on peut lire sans caméra. */
    targets:()=>Object.freeze(interactionView.targets().map(target=>Object.freeze({
      ...BH.createTargetCandidate(target),
      handTrackId:target.handTrackId,channel:target.channel,
      locked:target.locked,feedback:target.feedback}))),
    /* Slice 06. Ce que les mains **tiennent** et ce qu'elles produisent, du
       dernier instant : les captures par main, et les interactions publiées à
       travers `createInteractionEvent` (donc avec leur `pointerId` de main).
       Vide hors interaction, comme tout ce qui décrit un instant. */
    captures:()=>Object.freeze([...interactionView.captures()]),
    interactions:()=>Object.freeze(interactionView.interactions().map(event=>event)),
    /* **Décision 24 et contrat § 9, branchés (Slice 07).** Ces deux-là sont
       la porte *sans persistance* : elles changent le moteur pour l'instant et
       ne touchent pas au fichier de réglages. Ce que l'écran manipule, et ce
       que la Slice 12 appellera, c'est `settings(patch)` — qui applique **et**
       enregistre, donc qui survit au rechargement. Les deux existent parce
       qu'un essai depuis la console n'a pas à devenir une préférence. */
    targetPreview:value=>value===undefined
      ?interactionView.targetsShown():interactionView.showTargets(value),
    targetAssistance:value=>interactionView.setAssistance(value),
    /* Slice 07. Les réglages tels qu'ils s'appliquent ; avec un objet, ils
       s'écrivent (normalisés, appliqués à chaud, enregistrés). Rend `null`
       quand rien n'a été enregistré — un appelant qui ne peut pas distinguer
       un refus d'un succès en fabriquerait un. */
    settings:patch=>patch===undefined?view.settings:saveSettings(patch),
    /* L'outil actif (décision 25), sans passer par l'écran : le point d'entrée
       du canal de commandes de la voix (Slice 12), « prends le surligneur ».
       Un outil **inconnu** est refusé par `saveSettings` (contrat § 8), un
       outil déclaré mais **sans moteur** l'est par le serveur : dans les deux
       cas un refus nommé, jamais un silence ni un repli sur « pointeur ». */
    tools:()=>BH.describeTools(),
    tool:value=>value===undefined?view.settings.tool:saveSettings({tool:value}),
    /* **Le parcours de calibration** (Slice 08, décisions 26-32). Même porte
       pour le bouton et pour la voix : le canal de commandes appelle ceci et
       exige une **confirmation** (`{ok:true}`), sans quoi il refuse
       `barehands_flow_unconfirmed` (contrat § 12). */
    calibrate:()=>startCalibration(),
    /* **Le parcours de tutoriel et la sortie de surimpression** (Slice 09,
       décisions 6 et 26). Mêmes portes pour le bouton et pour la voix : le
       canal de commandes appelle celles-ci et exige une **confirmation**
       (`{ok:true}`), sans quoi il refuse `barehands_flow_unconfirmed`
       (contrat § 12). Le canal n'a pas changé d'une ligne pour les poser —
       elles étaient déjà dans sa table, routées vers un point d'entrée absent. */
    tutorial:()=>startTutorial(),
    exitOverlay:()=>exitOverlay(),
    /* L'état du tutoriel, et ce que `tutorialSeen` vaut : « profil
       enregistré » et « profil appliqué » ont appris à se distinguer à la
       Slice 07, « tutoriel vu » et « tutoriel en cours » aussi. */
    tutorialState:()=>Object.freeze(tutorialState()),
    /* **La couture de mesure est-elle ouverte ?** (décision 32.) Elle n'est
       posée que pendant une calibration, et hors d'elle le contrôleur ne
       calcule rien. Jusqu'ici la promesse n'était lisible nulle part : « le
       tutoriel ne mesure pas » et « le tutoriel mesure en silence »
       s'écrivaient pareil à l'écran comme à la console. C'est la règle que
       `engine()` a posée à la Slice 07 — un réglage qu'on ne peut pas relire
       là où il agit est un réglage qu'on ne peut pas dire branché — appliquée
       à une garantie de **non**-mesure. */
    measuring:()=>typeof controllerDeps.onMeasure==='function',
    /* **Qui** écoute la couture de mesures, et pas seulement qu'elle est
       ouverte. `measuring()` restait vrai quel que soit le consommateur : avec
       deux (la calibration et l'enregistreur, Slice 10), « une calibration
       mesure » et « une séance s'enregistre » s'écrivaient pareil. */
    measureSeam:()=>Object.freeze(measureSeamNames()),
    /* **La couture de diffusion du cycle de vie** (décision 7 de l'affinage
       d'UI). Ce que `state()` rend sur demande, celle-ci le **pousse** : tout
       consommateur hors de ce module — le contrôle de la barre du haut, et ce
       que les Slices suivantes y accrocheront — s'y abonne au lieu de sonder.
       Elle rejoue l'instantané courant à l'ouverture, pour qu'un abonné
       installé après la dernière transition ne parte pas d'un état d'usine.
       `lifecycleSeam()` dit **qui** écoute, pour la même raison que
       `measureSeam()` : sans lecture, « les deux écoutent » et « l'un a été
       effacé par l'autre » s'écrivent pareil. */
    openLifecycleSeam,closeLifecycleSeam,
    lifecycleSeam:()=>Object.freeze(lifecycleSeamNames()),
    /* Le même instantané, lisible sans s'abonner : ce que l'écran peint doit
       pouvoir se comparer à ce que le moteur dit, depuis une console comme
       depuis un test. */
    lifecycleStatus:()=>lifecycleSnapshot(),
    /* L'enregistrement de diagnostic (Slice 10, §12). `start`/`stop` sont la
       **même** porte que les deux boutons de l'onglet ; `state()` est ce que
       l'écran affiche ; `trace()` rend la dernière trace terminée, même si son
       envoi a échoué — une séance ne se perd pas par une panne de réseau. */
    record:Object.freeze({
      start:spec=>startRecording(spec),
      stop:()=>stopRecording(),
      state:()=>Object.freeze(recordState()),
      trace:()=>{const flow=recorder;return flow?flow.trace():null},
      /* Le rejeu et les mesures, posés ici parce que c'est la surface que la
         console d'un développeur atteint. Le `core` est fourni : le module de
         rejeu ne va pas le chercher dans un global, il le reçoit. */
      replay:(trace,config)=>REC?REC.replay(trace,config,{core:Core}):null,
      metrics:replayed=>REC?REC.metricsOf(replayed):null,
      compare:(trace,configs)=>REC?REC.compare(trace,configs,{core:Core}):null,
    }),
    /* **Ce que la voix vient de faire**, publié pour la même raison que le
       reste : le canal de commandes y dépose son reçu (Slice 12 →
       `deps.onReceipt`), la page le dessine, et un opérateur peut le relire
       depuis la console. `record` est le seul écrivain, et il n'accepte que ce
       que le canal constate — jamais ce qu'on lui a demandé. */
    voice:Object.freeze({record:entry=>recordVoiceCommand(entry),
      last:()=>view.voice?Object.freeze({...view.voice}):null}),
    /* Le profil tel qu'il est appliqué, et ce que le moteur en fait. Les deux,
       parce que « profil enregistré » et « profil appliqué » ne sont pas la
       même chose — c'est la règle que `engine()` a posée à la Slice 07. */
    profile:()=>view.profile,
    calibration:()=>Object.freeze({running:!!(calibration&&calibration.isRunning()),
      step:calibration?calibration.stepId():null,
      /* Le chien de garde de l'échéance, lu **sur la minuterie elle-même**
         (même règle que `measuring()`) : « posé » et « oublié » ne s'écrivent
         pas pareil. */
      watching:!!(calibration&&calibration.watching()),
      travel:travelSlopFor(view.settings,view.profile)}),
    /* Diagnostic sans caméra : poser un jeton et cliquer depuis la console.
       Les deux **instances vivantes** sont là aussi — ce sont elles que le
       contrôleur tient, donc les seules par lesquelles `targets()` et la
       surimpression se laissent exercer sans webcam. */
    adapters:Object.freeze({createOverlay,createInteraction,
      overlay:overlayView,interaction:interactionView}),
  });

  setTimeout(()=>{
    installSettingsTab();
    api(API).then(applyServerState).catch(()=>{});
    /* Le profil est relu au démarrage, comme les réglages : sans lui, la
       première session après une calibration repartirait sur les seuils
       d'usine, et « enregistré » n'aurait rien voulu dire. */
    loadProfile();
  },0);
  window.addEventListener('pagehide',()=>{if(Core.isEngagedState(controller.state()))controller.disable()});
})();
}catch(error){
  console.error('[barehands] barehands.pointer_not_installed '
    +JSON.stringify({error:String(error&&error.message||error)}));
}
