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
  /* Indices MediaPipe utiles : poignet, bout du pouce, bout de l'index, base du majeur. */
  const LM=Object.freeze({WRIST:0,THUMB_TIP:4,INDEX_TIP:8,MIDDLE_MCP:9});
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
    handednessBonusPalms:.35,  // prime d'accord de latéralité — un indice, jamais une clé
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
    o.handednessBonusPalms=clamp(atLeast(o.handednessBonusPalms,0,DEFAULTS.handednessBonusPalms),0,o.matchRadiusPalms);
    o.predictMs=atLeast(o.predictMs,0,DEFAULTS.predictMs);
    o.trackVelocityBlend=clamp(atLeast(o.trackVelocityBlend,0,DEFAULTS.trackVelocityBlend),.01,1);
    o.qualityFloor=clamp(atLeast(o.qualityFloor,0,DEFAULTS.qualityFloor),0,1);
    o.qualityEdge=positive(o.qualityEdge,DEFAULTS.qualityEdge);
    o.qualityPalmMin=positive(o.qualityPalmMin,DEFAULTS.qualityPalmMin);
    o.qualityComplete=clamp(atLeast(o.qualityComplete,0,DEFAULTS.qualityComplete),0,1);
    o.qualityWarmupFrames=Math.max(1,Math.round(atLeast(o.qualityWarmupFrames,1,DEFAULTS.qualityWarmupFrames)));
    o.wakeHoldMs=Math.max(0,Number(o.wakeHoldMs)||0);
    o.sleepTimeoutMs=Math.max(0,Number(o.sleepTimeoutMs)||0);
    o.wakeSoft=clamp(Number(o.wakeSoft)||0,0,.5);
    o.wakeScore=clamp(Number(o.wakeScore)||0,0,1);
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
  const usablePoint=point=>!!point&&Number.isFinite(Number(point.x))&&Number.isFinite(Number(point.y));
  const usableLandmarks=landmarks=>Array.isArray(landmarks)
    &&landmarks.length>LM.MIDDLE_MCP&&USED_LANDMARKS.every(at=>usablePoint(landmarks[at]));

  /* Écart pouce-index rapporté à la paume (poignet → base du majeur) : même
     seuil quelle que soit la distance à la caméra. `aspect` = largeur/hauteur
     de l'image, les coordonnées MediaPipe étant normalisées par axe. */
  function pinchRatio(landmarks,aspect){
    if(!usableLandmarks(landmarks))return null;
    const k=Number(aspect)>0?Number(aspect):1;
    const palm=distance(landmarks[LM.WRIST],landmarks[LM.MIDDLE_MCP],k);
    if(!(palm>1e-6))return null;
    return distance(landmarks[LM.THUMB_TIP],landmarks[LM.INDEX_TIP],k)/palm;
  }

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
     sous le seuil une image au milieu d'un geste franc. */
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

  /* Pincement d'une main. États : open → pinching (en cours) → pressed.
     Le clic part une seule fois, au passage en pressed ; il faut relâcher
     au-delà de releaseRatio pour pouvoir recliquer, et cooldownMs absorbe les
     rebonds d'un relâchement bref. */
  function createPinchDetector(overrides){
    const o=options(overrides);
    let state='open',frames=0,lastClickAt=-Infinity;
    return {
      update(ratio,now){
        let click=false;
        if(ratio===null||ratio===undefined||!isFinite(ratio)){
          state='open';frames=0;
          return {state,progress:0,click};
        }
        if(state==='pressed'){
          if(ratio>o.releaseRatio){state='open';frames=0}
        }else if(ratio<=o.pressRatio){
          frames+=1;
          if(frames>=o.pressFrames){
            state='pressed';frames=0;
            if(now-lastClickAt>=o.cooldownMs){click=true;lastClickAt=now}
          }else state='pinching';
        }else if(ratio<o.releaseRatio){state='pinching';frames=0}
        else{state='open';frames=0}
        const progress=state==='pressed'?1:state==='open'?0:
          clamp((o.releaseRatio-ratio)/(o.releaseRatio-o.pressRatio),0,1);
        return {state,progress,click};
      },
      reset(){state='open';frames=0},
      state(){return state},
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
    const gap=distance(landmarks[LM.THUMB_TIP],landmarks[LM.INDEX_TIP],k)/palm;
    const reach=distance(landmarks[LM.WRIST],landmarks[LM.INDEX_TIP],k)/palm;
    const soft=Math.max(1e-6,(o.wakeGapMax-o.wakeGapMin)*o.wakeSoft);
    const open=Math.min(ramp(gap,o.wakeGapMin,o.wakeGapMin+soft),1-ramp(gap,o.wakeGapMax-soft,o.wakeGapMax));
    const extended=ramp(reach,o.wakeIndexMin,o.wakeIndexMin*(1+o.wakeSoft));
    return clamp(Math.min(open,extended),0,1);
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
     minuteur de la décision 7, la pastille et la surimpression. Miroir de
     `JarvisBarehandsContracts.isUsableQuality` (le bloc pur est chargé seul
     par les tests node) ; le test de parité refuse la dérive. */
  const usableQuality=(quality,overrides)=>{
    const value=Number(quality);
    return Number.isFinite(value)&&value>=options(overrides).qualityFloor;
  };

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
        le C), moins une prime si les latéralités s'accordent ;
     3. une distance au-delà de `matchRadiusPalms` n'est pas un appariement du
        tout. **La porte se juge sur la distance seule, jamais sur le coût** :
        la latéralité départage, elle n'ouvre pas la porte. C'est ce qui
        empêche une étiquette qui bascule de voler une identité ;
     4. on retient l'attribution de coût **total** minimal, pas la meilleure
        paire d'abord : au croisement de deux mains, le glouton prend la paire
        la plus proche et impose la pire à l'autre.

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

  function createHandTrackManager(overrides){
    const o=options(overrides);
    const settle=o.qualityWarmupFrames;
    const tracks=new Map();
    let nextId=0;

    /* Attribution de coût total minimal. `null` = porte fermée ; ne pas
       apparier coûte `matchRadiusPalms`, si bien qu'un appariement dans la
       porte est toujours préféré à une piste neuve. */
    function assign(costs,detections,trackCount){
      const best={total:Infinity,pick:null};
      const current=new Array(detections).fill(-1);
      const used=new Array(trackCount).fill(false);
      (function walk(index,total){
        if(total>=best.total)return;
        if(index===detections){best.total=total;best.pick=current.slice();return}
        for(let t=0;t<trackCount;t+=1){
          if(used[t]||costs[index][t]===null)continue;
          used[t]=true;current[index]=t;
          walk(index+1,total+costs[index][t]);
          used[t]=false;
        }
        current[index]=-1;
        walk(index+1,total+o.matchRadiusPalms);
      })(0,0);
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
        const costs=list.map(observation=>{
          const palm=Number(observation&&observation.palm);
          const scale=Number.isFinite(palm)&&palm>1e-6?palm:1;
          return ids.map(id=>{
            const track=tracks.get(id);
            const horizon=Math.min(Math.max(0,at-track.at),o.predictMs)/1000;
            const gap=Math.hypot(
              ((track.x+track.vx*horizon)-observation.x)*k,
              (track.y+track.vy*horizon)-observation.y)/scale;
            if(!(gap<=o.matchRadiusPalms))return null;
            return gap-(observation.handedness&&observation.handedness===track.handedness
              ?o.handednessBonusPalms:0);
          });
        });
        const pick=assign(costs,list.length,ids.length);
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
          tokens.push({id,x:aim.x,y:aim.y,
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

  /* Première main exploitable d'un résultat de traqueur, ou `null`. */
  function usableHand(result){
    for(const landmarks of (result&&result.landmarks)||[])
      if(usableLandmarks(landmarks))return landmarks;
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
    const tracker=createHandTracker(deps.options);
    const wake=createWakeDetector(deps.options);
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
      wake.reset();tracker.reset();lastVideoTime=-1;lastHandAt=deps.now();features=[];
      state=STATE.ACTIVE;emit(code||'active');
      paintWatch(null);
    }
    function toSleep(code){
      tracker.reset();wake.reset();lastVideoTime=-1;lastWatchAt=-Infinity;features=[];
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
      const hand=usableHand(landmarker.detectForVideo(video.element,now));
      const out=wake.update(hand?cPoseScore(hand,aspect(),deps.options):null,now);
      const at=hand?toScreen(hand[LM.INDEX_TIP],deps.viewport(),o):null;
      paintWatch({present:!!hand,progress:out.progress,x:at?at.x:0,y:at?at.y:0});
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
      deps.interaction.hover(out.tokens);
      deps.overlay.render(out.tokens);
      // Traits du dernier instant, pour la calibration et les diagnostics
      // (architecture §12) : lus après le survol, donc `hover` y est juste.
      features=out.tokens;
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
    return {enable,activate,sleep,disable,state:()=>state,features:()=>features,tick};
  }

  return {LM,STATE,STATES,LIVE_STATES,isLiveState,isEngagedState,usableLandmarks,usableQuality,
    DEFAULTS,MESSAGES,pinchRatio,cPoseScore,handQuality,toScreen,
    createPinchDetector,createWakeDetector,createPointerFilter,createStillness,
    createHandTrackManager,createHandTracker,classifyError,createController};
})();

/* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
if(typeof module!=='undefined'&&module.exports)module.exports=JarvisBarehandsCore;

/* --------------------------------------------------------------------------
   Bloc navigateur : caméra, surimpression, clics, onglet de réglages.
   -------------------------------------------------------------------------- */
(function installJarvisBarehands(){
  if(typeof window==='undefined'||typeof document==='undefined')return;
  const Core=JarvisBarehandsCore;
  /* Noms partagés avec la scène et la page (identité de pointeur, formes du
     DOM) : `control_center_barehands_contracts.js`, inséré juste avant. Le
     bloc pur ci-dessus ne le lit pas — les tests node le chargent seul. */
  const BH=JarvisBarehandsContracts;
  const API='/api/barehands';
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
    let root=null,badge=null,wake=null;
    const tokens=new Map();
    return {
      mount(){
        ensureStyle();
        if(root)return;
        root=document.createElement('div');root.id=BH.DOM.rootId;root.setAttribute('aria-hidden','true');
        badge=document.createElement('div');badge.className=BH.DOM.badgeClass;badge.textContent=BADGE.mounted;
        wake=document.createElement('div');wake.className=BH.DOM.wakeClass;
        root.appendChild(wake);root.appendChild(badge);document.body.appendChild(root);
      },
      unmount(){
        if(root)root.remove();
        root=null;badge=null;wake=null;tokens.clear();
      },
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
      render(list){
        if(!root)return;
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
      },
    };
  }

  function createInteraction(){
    const hovered=new Map();
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
    function pointer(type,el,x,y,buttons,identity){
      const init={bubbles:true,cancelable:true,composed:true,view:window,clientX:x,clientY:y,button:0,buttons};
      if(type.startsWith('pointer')&&typeof PointerEvent==='function')
        el.dispatchEvent(new PointerEvent(type,{...init,pointerId:identity.pointerId,pointerType:BH.POINTER_TYPE,isPrimary:identity.isPrimary}));
      else if(!type.startsWith('pointer'))el.dispatchEvent(new MouseEvent(type,init));
    }
    function release(id){
      const previous=hovered.get(id);
      hovered.delete(id);
      const identity=identityOf(id);
      if(previous&&identity&&![...hovered.values()].includes(previous)){
        previous.classList.remove(BH.DOM.hoverClass);
        pointer('pointerout',previous,0,0,0,identity);pointer('mouseout',previous,0,0,0,identity);
      }
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
            hovered.set(token.id,el);el.classList.add(BH.DOM.hoverClass);
            pointer('pointerover',el,token.x,token.y,0,identity);pointer('mouseover',el,token.x,token.y,0,identity);
          }
        }
        for(const id of [...hovered.keys()])if(!live.has(id))release(id);
        // Une main partie rend sa fente : deux mains qui vont et viennent en
        // retrouvent toujours une. Les identités vides sont écartées avant
        // d'arriver au contrat, qui les refuserait — et ce refus-là tomberait
        // dans la boucle d'images, où il vaut la fin de la session.
        slots.retain([...live].map(handKey).filter(key=>key!==null));
      },
      /* Un vrai clic : la séquence qu'enverrait une souris, sur l'élément exact
         sous le jeton (les écouteurs, labels, cases et liens réagissent). */
      click({id,x,y}){
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
      clear(){for(const id of [...hovered.keys()])release(id);slots.clear()},
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
    status:{state:'off',code:'off',title:Core.MESSAGES.off.title,message:Core.MESSAGES.off.detail,error:null}};

  const controller=Core.createController({
    getUserMedia:navigator.mediaDevices&&typeof navigator.mediaDevices.getUserMedia==='function'
      ?constraints=>navigator.mediaDevices.getUserMedia(constraints):null,
    /* Les durées du cycle de vie viennent du contrat, pas des défauts du
       moteur : un seul endroit les fixe (décisions 5, 7). La cadence du
       guetteur les rejoint — c'est elle que l'onglet promet « 5 images par
       seconde », et une promesse affichée ne se règle pas ailleurs. */
    options:{sleepTimeoutMs:BH.SLEEP_TIMEOUT_MS,wakeHoldMs:BH.WAKE_HOLD_MS,
      wakeIntervalMs:BH.WAKE_INTERVAL_MS},
    createLandmarker,attachVideo,
    overlay:createOverlay(),interaction:createInteraction(),
    requestFrame:fn=>requestAnimationFrame(fn),cancelFrame:id=>cancelAnimationFrame(id),
    now:()=>performance.now(),viewport:()=>({width:window.innerWidth,height:window.innerHeight}),
    onStatus:onStatus,
  });

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

  function applyAssets(state){if(state&&state.assets)view.assets=state.assets}

  function applyServerState(state){
    applyAssets(state);
    view.enabled=!!(state&&state.enabled===true);
    if(view.enabled)controller.enable();
    else if(Core.isEngagedState(controller.state()))controller.disable();
    refreshPanel();
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

  async function setEnabled(enabled){
    view.busy=true;view.error='';
    // Éteindre n'attend pas l'écriture : la caméra est libérée tout de suite.
    if(!enabled&&Core.isEngagedState(controller.state()))controller.disable();
    refreshPanel();
    try{
      const state=await api(API,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});
      view.busy=false;applyServerState(state);
    }catch(error){
      view.busy=false;view.error=`Réglage non enregistré : ${error.message}`;
      refreshPanel();
    }
  }

  function statusHtml(){
    const s=view.status,cls=s.state==='error'?'bad':'info';
    const error=view.error?`<div class="notice bad">${esc(view.error)}</div>`:'';
    return `${error}<div class="notice ${cls}"><strong>${esc(s.title)}</strong><div class="hint">${esc(s.message)}</div></div>`;
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
      <h3>Gestes</h3>
      <ul class="hint" style="padding-left:18px;line-height:1.7">
        <li><strong>Réveil :</strong> en veille, formez un C avec le pouce et l'index — écartés sans se toucher, index déplié — et tenez une seconde. L'anneau se remplit autour de la main ; relâcher avant la fin annule.</li>
        <li>Chaque main visible affiche un jeton rond qui suit le bout de l'index ; il grossit au survol d'un élément cliquable.</li>
        <li>Rapprocher pouce et index remplit l'anneau du jeton (pincement en cours) ; le jeton se fige pour viser.</li>
        <li>Pincement franc : clic sous le jeton (onde visuelle). Rouvrir les doigts avant de recliquer.</li>
        <li>Un jeton <strong>pâle et pointillé</strong> signale une main que le suivi ne tient pas pour sûre — elle sort du cadre, elle est trop loin, ou elle vient d'apparaître. Elle est affichée et cliquable, mais elle ne maintient pas l'interaction éveillée : la pastille compte alors « 1/2 ».</li>
        <li>Sans main <em>sûre</em> vue pendant 30 secondes, l'interaction retourne en veille ; la caméra reste ouverte pour le guetteur.</li>
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

  function refreshPanel(){
    if(typeof SET==='undefined'||!SET.open||SET.tab!==TAB_ID)return;
    const toggle=document.getElementById('f_barehands');
    if(toggle){toggle.checked=view.enabled;toggle.disabled=view.busy}
    const life=document.getElementById('barehandsLifecycle');
    if(life){life.innerHTML=lifecycleHtml();bindWake()}
    const status=document.getElementById('barehandsStatus');
    if(status)status.innerHTML=statusHtml();
    const assets=document.getElementById('barehandsAssets');
    if(assets)assets.innerHTML=assetsHtml();
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
      const toggle=document.getElementById('f_barehands');
      if(toggle)toggle.addEventListener('change',()=>setEnabled(toggle.checked));
      bindWake();
      say('','');
      // Relire la présence des assets sans redessiner l'onglet.
      api(API).then(state=>{applyAssets(state);refreshPanel()}).catch(()=>{});
    };
  }

  window.JarvisBarehands=Object.freeze({
    version:2,core:Core,contracts:BH,
    state:()=>({enabled:view.enabled,status:view.status,assets:view.assets,
      controller:controller.state(),lifecycle:lifecycle()}),
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
    // Diagnostic sans caméra : poser un jeton et cliquer depuis la console.
    adapters:Object.freeze({createOverlay,createInteraction}),
  });

  setTimeout(()=>{
    installSettingsTab();
    api(API).then(applyServerState).catch(()=>{});
  },0);
  window.addEventListener('pagehide',()=>{if(Core.isEngagedState(controller.state()))controller.disable()});
})();
