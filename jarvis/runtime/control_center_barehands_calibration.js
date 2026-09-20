/* Bare Hands V1 — parcours de calibration et coque de surimpression (Slice 08).
   Architecture §10 et §11, décisions 26 à 32.

   Deux choses vivent ici, et c'est la décision 26 qui les met ensemble :

   - **la coque de surimpression**, plein écran, sombre et floutée, avec un
     titre, une consigne, une progression, un compteur vivant et une sortie
     évidente. Elle ne sait rien de la calibration : elle affiche des étapes.
     Le tutoriel (Slice 09) la réutilise telle quelle — « deux parcours, une
     coque » est un choix de produit, pas une ressemblance ;
   - **la dérivation**, pure : des échantillons entrent, des seuils sortent.
     Aucun DOM, aucune horloge, aucun réseau — node la pilote sans navigateur.

   **Décision 32, et c'est structurel.** Ce module ne reçoit jamais de points :
   le contrôleur lui passe, par main et par image, un enregistrement de
   scalaires (`deps.onMeasure`, `control_center_barehands.js`). Il ne peut donc
   pas conserver une image, une vidéo ni un point — non parce que c'est
   interdit, parce qu'il n'en a jamais eu. Ce qui sort d'ici est un profil de
   nombres, et `JarvisBarehandsContracts.toProfilePayload` est le seul chemin
   vers la route.

   **Décision 29/30** : statistique et seuils, rien d'autre. Aucun apprentissage
   personnalisé, aucun apprentissage continu — le parcours ne tourne que quand
   l'utilisateur l'a lancé (décision 27), et il s'arrête quand il a fini.

   Insertion : après les contrats (il les lit) et **avant**
   `control_center_barehands.js`, qui lit celui-ci pour poser
   `JarvisBarehands.calibrate()` sur sa surface gelée. Un test de page vérifie
   l'ordre (constat F3 de la Slice 00).

   Unités, et elles ne se mélangent pas :
   - **paumes** pour tout ce qui décrit la main (écart de pincement, portée) ;
   - **fraction de l'image 0..1** pour ce qui est persisté et doit survivre à un
     changement de résolution (`reachNorm`, `travelSlopNorm`) ;
   - **pixels de la fenêtre** pour ce qui est mesuré à l'écran (`jitterPx`), et
     pour rien d'autre. */
(function(root){
  'use strict';
  const BH=root.JarvisBarehandsContracts;
  if(!BH)throw new Error('JarvisBarehandsCalibration : les contrats Bare Hands doivent être insérés avant ce module');

  /* ------------------------------------------------------------------ 1
     Réglages du parcours, et les paires dangereuses qu'ils peuvent former.

     Même règle que partout sur cette tâche : une combinaison qui ne peut pas
     marcher se refuse **à la construction**, pas au premier utilisateur qui la
     rencontre. Les trois d'ici échouent toutes de la même façon — en silence,
     en retombant sur les défauts, ce qui se lit « l'utilisateur s'y prend
     mal ». */
  const DEFAULTS=Object.freeze({
    /* Échéance d'une étape. Au-delà, l'étape **échoue et le dit** : une étape
       qui attend pour toujours est la panne que la RÈGLE ZÉRO interdit. */
    stageTimeoutMs:20000,
    // Durée de maintien demandée dans une étape de pose (repos, C).
    stageHoldMs:2500,
    // Échantillons minimaux pour qu'une mesure compte comme une mesure.
    stageMinSamples:20,
    // Répétitions demandées dans les étapes de pincement.
    pinchRepeats:4,
    /* Où poser les seuils dans la bande mesurée entre « ouvert » et « fermé ».
       `pressAt` bas veut dire : un pincement confortable, **pas entièrement
       fermé**, compte déjà (exigence de la Slice). `releaseAt` au-dessus laisse
       l'hystérésis que la décision 20 demande. */
    pressAt:.35,
    releaseAt:.65,
    /* Séparabilité minimale entre le repos et le pincement, en paumes. En
       dessous, les deux états ne se distinguent pas et poser un seuil entre eux
       ferait clignoter le contact : la mesure est **refusée**, pas rabotée. */
    separationMinPalms:.12,
    // Bornes de la tolérance dérivée, en fraction de la largeur d'image.
    travelSlopMin:.002,
    travelSlopMax:.15,
    // Marge au-dessus du déplacement observé pendant un clic délibéré.
    travelSlopMargin:1.6,
    // Qualité de suivi en dessous de laquelle un échantillon ne compte pas.
    sampleQualityMin:.4,
    /* Cadence du chien de garde **de la page**. Le parcours est nourri par la
       couture `deps.onMeasure`, qui ne tire qu'en ACTIVE **et seulement quand
       une main a été observée** : zéro main vue, et l'échéance n'était jamais
       évaluée — l'étape 1 sur 7 ne se soldait plus, le compteur restait figé
       sur « 0 s restantes », et `STAGE_REASON.NO_HAND` était injoignable dans
       le scénario qui porte son nom. Publiée ici et non dans la page pour que
       la paire dangereuse ci-dessous ait ses deux nombres au même endroit —
       même forme que `watchdogMs` du tutoriel (Slice 09). */
    watchdogMs:500,
  });

  function options(overrides){
    const o={...DEFAULTS,...(overrides||{})};
    /* **Paire dangereuse n° 9.** Une étape dont l'échéance est plus courte que
       le maintien qu'elle demande ne peut pas aboutir : elle expire pendant que
       l'utilisateur tient la pose. Toutes les étapes échoueraient, le profil
       retomberait sur les défauts à chaque fois, et l'écran dirait « ça n'a pas
       marché » à quelqu'un qui a tout fait correctement. Même espèce que
       `sleepTimeoutMs <= wakeHoldMs` (Slice 07) : le temps qu'on accorde doit
       dépasser le temps qu'on exige. */
    if(!(o.stageTimeoutMs>o.stageHoldMs))
      throw new RangeError('stageTimeoutMs doit rester au-dessus de stageHoldMs : une étape dont l’échéance est plus courte que le maintien qu’elle demande expire pendant que l’utilisateur tient la pose, et toutes les calibrations retombent sur les défauts en accusant l’utilisateur');
    /* **Paire dangereuse n° 10.** `pressAt >= releaseAt` dérive un
       `pressRatio >= releaseRatio` pour **tout le monde** : le contrat le
       refuse (`barehands_profile_thresholds_invalid`), donc chaque étape de
       pincement échouerait — mais elle échouerait *après* la mesure, ce qui se
       lit « votre pincement n'est pas mesurable ». La cause est ici. */
    if(!(o.pressAt>0&&o.pressAt<o.releaseAt&&o.releaseAt<1))
      throw new RangeError('pressAt doit rester dans ]0,1[ et sous releaseAt : au-dessus, chaque calibration dérive un pressRatio >= releaseRatio, que le contrat refuse — et l’échec se lirait comme un pincement non mesurable');
    /* **Paire dangereuse n° 11.** Bornes inversées : `clamp(v,lo,hi)` rend `lo`
       quand `lo > hi`, donc **tous** les utilisateurs recevraient la même
       tolérance, et « calibré » serait indiscernable de « pas calibré ». Même
       espèce que `SETTINGS_BOUNDS` inversé à la Slice 07, et que
       `MIN_SIZE`/`MAX_SIZE` à la Slice 06. */
    if(!(o.travelSlopMin>0&&o.travelSlopMin<o.travelSlopMax))
      throw new RangeError('travelSlopMin doit être positif et sous travelSlopMax : inversées, clamp() rend la borne basse à tout le monde et toutes les calibrations dérivent la même tolérance, ce qui rend « calibré » indiscernable de « pas calibré »');
    if(!(o.stageMinSamples>=1))
      throw new RangeError('stageMinSamples doit valoir au moins 1 : à zéro, une étape sans le moindre échantillon se déclarerait réussie et publierait une mesure tirée de rien');
    if(!(o.travelSlopMargin>=1))
      throw new RangeError('travelSlopMargin ne peut pas descendre sous 1 : une tolérance plus étroite que le déplacement mesuré pendant un clic délibéré ferait de chaque clic de cet utilisateur un glissement');
    /* **Paire dangereuse n° 14**, et c'est celle du tutoriel (n° 13) lue de ce
       côté-ci. Le chien de garde plus lent que l'échéance qu'il surveille
       laisse « 0 s restantes » à l'écran pendant toute une échéance de plus,
       et « ça attend » redevient indiscernable de « c'est bloqué » —
       exactement ce que le compteur existe pour empêcher. */
    if(!(o.watchdogMs>0&&o.watchdogMs<o.stageTimeoutMs))
      throw new RangeError('watchdogMs doit être positif et sous stageTimeoutMs : plus lent que l’échéance qu’il surveille, il laisse l’écran afficher « 0 s restantes » pendant toute une échéance de plus, et « ça attend » redevient indiscernable de « c’est bloqué »');
    /* **Paire dangereuse n° 15.** `pinchRepeats < 1` consomme l'étape de
       pincement à la première image (`repeats>=0` est déjà vrai),
       `deriveHysteresis` n'a alors qu'un échantillon et rend
       `TOO_FEW_SAMPLES` : **les deux étapes de pincement échouent pour tout le
       monde**, et l'écran le dit comme si l'utilisateur pinçait mal. À zéro,
       `progress(repeats/0)` vaut en plus `NaN`, donc la barre ne dit même plus
       où on en est. Même espèce que `stageMinSamples>=1` juste au-dessus. */
    if(!(o.pinchRepeats>=1))
      throw new RangeError('pinchRepeats doit valoir au moins 1 : en dessous, l’étape de pincement se solde à la première image, la dérivation n’a qu’un échantillon et les deux étapes de pincement échouent pour tout le monde — un défaut d’usine qui se lit « votre pincement n’est pas mesurable »');
    /* Une qualité minimale au-dessus de 1 n'est atteinte par **aucune** image :
       tous les échantillons sont filtrés, chaque étape expire sur « aucune main
       vue », et la caméra marche pourtant. Même panne universelle et
       silencieuse que les trois précédentes. */
    if(!(o.sampleQualityMin>=0&&o.sampleQualityMin<=1))
      throw new RangeError('sampleQualityMin doit rester dans [0,1] : au-dessus de 1 aucun échantillon ne passe le filtre, toutes les étapes expirent sur « aucune main vue » et la cause reste invisible');
    /* Une séparabilité exigée au-delà de ce qu'une main peut produire refuse
       **toutes** les mesures de pincement sur `NOT_SEPARABLE`. L'écart
       pouce-index d'une main ouverte vaut moins d'une paume : au-delà de 1, la
       borne n'est plus une exigence, c'est un refus déguisé. */
    if(!(o.separationMinPalms>0&&o.separationMinPalms<1))
      throw new RangeError('separationMinPalms doit rester dans ]0,1[ : au-delà, aucune main ne sépare assez le repos du pincement, chaque mesure sort « les deux états ne se distinguent pas » et la cause est le réglage, pas l’utilisateur');
    return Object.freeze(o);
  }

  /* ------------------------------------------------------------------ 2
     Statistiques. Rien de plus qu'il n'en faut (décision 29).

     Les quantiles, pas la moyenne : une main qui sort du cadre une image sur
     vingt produit des valeurs aberrantes, et une moyenne les porte. */
  const finite=list=>list.filter(value=>Number.isFinite(value));
  function quantile(list,q){
    const values=finite(list).slice().sort((a,b)=>a-b);
    if(!values.length)return null;
    const at=(values.length-1)*Math.min(Math.max(q,0),1);
    const low=Math.floor(at),high=Math.ceil(at);
    return low===high?values[low]:values[low]+(values[high]-values[low])*(at-low);
  }
  const median=list=>quantile(list,.5);
  function stdev(list){
    const values=finite(list);
    if(values.length<2)return null;
    const mean=values.reduce((sum,value)=>sum+value,0)/values.length;
    const variance=values.reduce((sum,value)=>sum+(value-mean)*(value-mean),0)/(values.length-1);
    return Math.sqrt(variance);
  }

  /* ------------------------------------------------------------------ 3
     Dérivations. Chacune rend `{ok,…}` ou `{ok:false,reason}` — **jamais** un
     nombre inventé. Une mesure impossible se dit (décision 31 : l'étape
     retombe sur les défauts du moteur, et le profil dit laquelle).

     Ce sont des fonctions pures sur des tableaux de nombres : elles ne savent
     ni ce qu'est une main, ni ce qu'est une image. */

  /* Le tremblement du repos, en **pixels de la fenêtre** : l'écart entre la
     position brute et la position filtrée. Jamais sur `x`/`y` du jeton — il se
     fige sur l'ancre pendant un pincement et ne dit alors plus rien de la
     main ; c'est la mine que la Slice 04 a déjà trouvée sur `travelPx`. */
  function deriveJitter(samples,o){
    const gaps=samples.map(sample=>{
      const dx=Number(sample.rawX)-Number(sample.filteredX);
      const dy=Number(sample.rawY)-Number(sample.filteredY);
      return Number.isFinite(dx)&&Number.isFinite(dy)?Math.hypot(dx,dy):null;
    });
    const usable=finite(gaps);
    if(usable.length<o.stageMinSamples)
      return {ok:false,reason:BH.STAGE_REASON.TOO_FEW_SAMPLES,samples:usable.length};
    /* L'écart-type dirait le bruit moyen ; c'est le **95e centile** qui dit ce
       qu'une tolérance doit encaisser pour qu'un clic immobile reste un clic. */
    const jitterPx=quantile(usable,.95);
    return {ok:true,samples:usable.length,jitterPx,spreadPx:stdev(usable)};
  }

  /* Les deux seuils d'un canal de pincement, dérivés de la bande réellement
     parcourue entre « ouvert » et « fermé » pendant des pincements répétés. */
  function deriveHysteresis(ratios,o){
    const usable=finite(ratios);
    if(usable.length<o.stageMinSamples)
      return {ok:false,reason:BH.STAGE_REASON.TOO_FEW_SAMPLES,samples:usable.length};
    /* Les deux extrêmes, pris à distance des queues : le 10e centile est le
       pincement fermé de cet utilisateur, le 90e sa main ouverte. */
    const closed=quantile(usable,.1),open=quantile(usable,.9);
    if(closed===null||open===null)
      return {ok:false,reason:BH.STAGE_REASON.TOO_FEW_SAMPLES,samples:usable.length};
    const separation=open-closed;
    /* **Refuser plutôt que raboter.** Deux états qu'on ne distingue pas ne
       donnent pas un seuil médiocre, ils donnent un seuil qui fait clignoter
       le contact — donc des clics qu'on n'a pas demandés. L'exigence de la
       Slice le dit en toutes lettres : on admet un pincement confortable, on
       refuse des seuils qui rendent repos et pincement inséparables. */
    if(!(separation>=o.separationMinPalms))
      return {ok:false,reason:BH.STAGE_REASON.NOT_SEPARABLE,samples:usable.length,
        separation,closed,open};
    const pressRatio=closed+separation*o.pressAt;
    const releaseRatio=closed+separation*o.releaseAt;
    return {ok:true,samples:usable.length,pressRatio,releaseRatio,closed,open,separation};
  }

  /* La tolérance clic/glissement, en **fraction de la largeur de l'image**.
     Elle a besoin des deux côtés : ce qu'un clic délibéré parcourt (au-dessus
     duquel il faut rester) et ce qu'un glissement délibéré parcourt (sous
     lequel il faut rester). Un seul côté donnerait un nombre sans borne de
     l'autre — et c'est précisément la question que la Slice 04 a laissée. */
  function deriveTravelSlop(clickTravels,dragTravels,o){
    const clicks=finite(clickTravels),drags=finite(dragTravels);
    if(clicks.length<1)return {ok:false,reason:BH.STAGE_REASON.TOO_FEW_SAMPLES,samples:clicks.length};
    const clickHigh=quantile(clicks,.95);
    const wanted=clickHigh*o.travelSlopMargin;
    if(drags.length){
      const dragLow=quantile(drags,.05);
      /* Si le clic le plus agité dépasse le glissement le plus sage, les deux
         gestes ne se distinguent pas chez cet utilisateur : aucun seuil ne les
         sépare, et en inventer un ferait de ses clics des glissements ou
         l'inverse. */
      if(!(clickHigh<dragLow))
        return {ok:false,reason:BH.STAGE_REASON.NOT_SEPARABLE,
          samples:clicks.length+drags.length,clickHigh,dragLow};
      /* À mi-chemin quand la marge dépasse le glissement : rester sous le
         glissement prime sur la marge de confort, sinon un glissement lent
         redeviendrait un clic. */
      const travelSlopNorm=Math.min(wanted,(clickHigh+dragLow)/2);
      return {ok:true,samples:clicks.length+drags.length,
        travelSlopNorm:Math.min(Math.max(travelSlopNorm,o.travelSlopMin),o.travelSlopMax),
        clickHigh,dragLow};
    }
    return {ok:true,samples:clicks.length,
      travelSlopNorm:Math.min(Math.max(wanted,o.travelSlopMin),o.travelSlopMax),
      clickHigh,dragLow:null};
  }

  /* Le rectangle que la main atteint dans l'image, en coordonnées normalisées
     0..1 — jamais des pixels (contrat §10). C'est la correction spatiale : un
     utilisateur qui n'atteint que le tiers gauche de l'image doit quand même
     pouvoir viser le bord droit de l'écran. */
  function deriveReach(xs,ys,o){
    const x=finite(xs),y=finite(ys);
    if(x.length<o.stageMinSamples)
      return {ok:false,reason:BH.STAGE_REASON.TOO_FEW_SAMPLES,samples:x.length};
    /* Les centiles plutôt que le minimum et le maximum : un seul point aberrant
       étirerait la portée sur toute l'image et annulerait la correction. */
    const box={x:quantile(x,.02),y:quantile(y,.02),
      w:quantile(x,.98)-quantile(x,.02),h:quantile(y,.98)-quantile(y,.02)};
    /* Une portée plate ramène tout l'écran sur un point : elle **défait** le
       repli qu'elle devait remplacer. Le contrat la refuse ; on ne la lui
       envoie pas. */
    if(!(box.w>0&&box.h>0))
      return {ok:false,reason:BH.STAGE_REASON.OUT_OF_BAND,samples:x.length,box};
    return {ok:true,samples:x.length,reachNorm:{
      x:Math.min(Math.max(box.x,0),1),y:Math.min(Math.max(box.y,0),1),
      w:Math.min(Math.max(box.w,0),1),h:Math.min(Math.max(box.h,0),1)}};
  }

  /* La posture en C, **vérifiée** plutôt que calibrée, et c'est délibéré.

     La bande de réveil (`wakeGapMin`/`wakeGapMax`/`wakeIndexMin`) est lue par
     le guetteur de veille, c'est-à-dire **avant** qu'une main ait une identité
     ou une latéralité : un seuil par main n'y aurait aucun lecteur. Le profil
     ne la porte donc pas (décision 28 : un seul profil visible), et cette étape
     répond à une autre question, qui est celle que l'utilisateur se pose —
     « est-ce que mon C réveille ? ».

     Et elle doit tenir compte du **canal secondaire** : depuis la Slice 04,
     `handPosture` annule toute posture dès qu'un des deux rapports passe sous
     `releaseRatio`, parce qu'une main qui pince n'est pas une posture. Un C
     dont le majeur reste près du pouce marque donc zéro alors que son écart
     pouce-index est parfait — et l'utilisateur ne peut pas le deviner. Ce cas a
     sa phrase. */
  function checkCPose(samples,band,o){
    const usable=samples.filter(sample=>Number.isFinite(sample.gapPalms));
    if(usable.length<o.stageMinSamples)
      return {ok:false,reason:BH.STAGE_REASON.TOO_FEW_SAMPLES,samples:usable.length};
    const gap=median(usable.map(sample=>sample.gapPalms));
    const reach=median(usable.map(sample=>sample.indexReachPalms));
    const score=median(usable.map(sample=>Number.isFinite(sample.cPose)?sample.cPose:0));
    const secondary=median(usable.map(sample=>sample.secondaryRatio));
    const held=usable.filter(sample=>Number.isFinite(sample.cPose)&&sample.cPose>=band.scoreMin).length;
    if(held>=o.stageMinSamples)
      return {ok:true,samples:held,gap,reach,score,secondary};
    /* Le majeur d'abord : c'est la cause qu'on ne devine pas, et elle rend les
       deux autres mesures trompeuses (l'écart peut être parfait). */
    if(Number.isFinite(secondary)&&secondary<band.releaseRatio)
      return {ok:false,reason:BH.STAGE_REASON.NOT_SEPARABLE,samples:usable.length,
        gap,reach,score,secondary,cause:'secondary'};
    if(!(gap>=band.gapMin&&gap<=band.gapMax))
      return {ok:false,reason:BH.STAGE_REASON.OUT_OF_BAND,samples:usable.length,
        gap,reach,score,secondary,cause:gap<band.gapMin?'gap_low':'gap_high'};
    if(!(reach>=band.reachMin))
      return {ok:false,reason:BH.STAGE_REASON.OUT_OF_BAND,samples:usable.length,
        gap,reach,score,secondary,cause:'reach'};
    return {ok:false,reason:BH.STAGE_REASON.OUT_OF_BAND,samples:usable.length,
      gap,reach,score,secondary,cause:'score'};
  }

  /* La bande **effective** du réveil, recalculée depuis les défauts du moteur
     plutôt que recopiée. Les quatre constantes sont les **zéros du score**, pas
     les seuils : citer 1,35 pour la portée se trompe de 10 % sur le nombre à
     mesurer, et c'est l'erreur que le contrat a déjà dû corriger une fois. */
  function wakeBandOf(engineDefaults){
    const d=engineDefaults||{};
    const soft=(d.wakeGapMax-d.wakeGapMin)*d.wakeSoft;
    return Object.freeze({
      gapMin:d.wakeGapMin+soft*d.wakeScore,
      gapMax:d.wakeGapMax-soft*d.wakeScore,
      reachMin:d.wakeIndexMin*(1+d.wakeSoft*d.wakeScore),
      scoreMin:d.wakeScore,
      releaseRatio:d.releaseRatio,
    });
  }

  /* ------------------------------------------------------------------ 4
     Les étapes, leur consigne et ce qu'elles mesurent (décision 31 : chacune
     réussit ou échoue **seule**). L'ordre est celui du contrat. */
  const STEPS=Object.freeze([
    Object.freeze({id:BH.STAGE.NEUTRAL,title:'Main au repos',
      instruction:'Posez une main ouverte devant la caméra et ne bougez plus. On mesure votre tremblement naturel.',
      hold:true,needs:1}),
    Object.freeze({id:BH.STAGE.C_POSE,title:'Posture de réveil',
      instruction:'Formez un C : pouce et index écartés sans se toucher, index déplié, les autres doigts détendus.',
      hold:true,needs:1}),
    Object.freeze({id:BH.STAGE.PINCH_PRIMARY,title:'Pincement pouce-index',
      instruction:'Pincez pouce et index, puis rouvrez. Recommencez tranquillement, comme pour cliquer.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.PINCH_SECONDARY,title:'Pincement pouce-majeur',
      instruction:'Même chose avec le majeur : pincez pouce et majeur, puis rouvrez. C’est le clic droit.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.AIM,title:'Viser et cliquer',
      instruction:'Amenez le jeton sur le point, puis pincez sans bouger la main.',
      hold:false,needs:1,target:true}),
    Object.freeze({id:BH.STAGE.DRAG,title:'Faire glisser',
      instruction:'Pincez, déplacez la main franchement vers la droite, puis relâchez.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.RESIZE,title:'Deux mains',
      instruction:'Montrez vos deux mains et écartez-les doucement, comme pour agrandir une image.',
      hold:false,needs:2}),
  ]);

  /* ------------------------------------------------------------------ 5
     La coque de surimpression (architecture §11, décision 26).

     Elle ne sait **rien** de la calibration : elle affiche des étapes, une
     progression, un compteur et une sortie. C'est ce qui la rend réutilisable
     par le tutoriel (Slice 09) sans la modifier — « deux parcours, une coque »
     est un choix de produit, et une coque qui connaîtrait les mesures ne le
     tiendrait pas.

     **RÈGLE ZÉRO, et elle est la raison d'être de la moitié de ce code.** À
     tout instant la coque dit : que quelque chose tourne (l'anneau avance),
     quoi (la consigne, en français), depuis combien de temps (un compteur
     vivant, en secondes), et comment en sortir (un bouton et Échap). Une étape
     porte toujours une échéance : « ça attend » et « c'est bloqué » se
     ressemblent trop pour qu'on laisse l'utilisateur trancher. */
  /* Les trois mots que la coque sait **dessiner** dans un rapport, et la
     feuille ci-dessous en définit exactement trois classes. Ce sont des
     statuts de **présentation**, pas ceux d'un parcours : la calibration s'en
     sert parce que `STAGE_STATUS` porte les mêmes mots, le tutoriel y traduit
     les siens (`done`/`missed`/`skipped`). Publiés pour qu'un parcours puisse
     s'y conformer au lieu de le deviner. */
  const FLOW_STATUS=Object.freeze(['ok','failed','skipped']);
  const STYLE_ID=BH.DOM.flowStyleId;
  const ACCENT='var(--omega-accent,var(--accent,#6ee7ff))';
  const STYLE=`
#${BH.DOM.flowRootId}{position:fixed;inset:0;z-index:2147482000;display:flex;align-items:center;
  justify-content:center;background:rgba(6,9,16,.82);backdrop-filter:blur(14px);
  -webkit-backdrop-filter:blur(14px);font:14px/1.6 system-ui,-apple-system,Segoe UI,sans-serif;color:#e8eef8}
#${BH.DOM.flowRootId}[hidden]{display:none}
#${BH.DOM.flowRootId} .${BH.DOM.flowStepClass}{position:relative;max-width:560px;padding:32px 36px;text-align:center;
  border-radius:20px;background:rgba(16,22,34,.72);box-shadow:0 24px 80px rgba(0,0,0,.55);
  border:1px solid rgba(255,255,255,.08)}
/* La sortie **permanente**. Les boutons d'une étape sont redessinés à chaque
   étape, donc « on peut toujours sortir » dépendait de ce que le parcours
   pensait à dessiner — et le rapport de calibration, par exemple, n'offre que
   « Annuler ». Celle-ci ne bouge pas, ne dépend d'aucun parcours, et occupe le
   coin où on la cherche. Quatrième point de la RÈGLE ZÉRO : comment en sortir. */
#${BH.DOM.flowRootId} .jf-close{position:absolute;top:10px;right:10px;width:34px;height:34px;padding:0;
  display:flex;align-items:center;justify-content:center;border-radius:50%;
  font-size:20px;line-height:1;color:#8b99ad;background:transparent;border:1px solid transparent}
#${BH.DOM.flowRootId} .jf-close:hover{color:#e8eef8;background:rgba(255,255,255,.1);
  border-color:rgba(255,255,255,.16)}
#${BH.DOM.flowRootId} .jf-close:focus-visible{outline:2px solid ${ACCENT};outline-offset:2px}
#${BH.DOM.flowRootId} .jf-kicker{font-size:12px;letter-spacing:.14em;text-transform:uppercase;
  color:${ACCENT};margin-bottom:10px}
#${BH.DOM.flowRootId} h2{margin:0 0 12px;font-size:24px;font-weight:600;letter-spacing:-.01em}
#${BH.DOM.flowRootId} .jf-instruction{margin:0 0 20px;color:#c3cede;font-size:15px}
#${BH.DOM.flowRootId} .${BH.DOM.flowProgressClass}{height:6px;border-radius:999px;overflow:hidden;
  background:rgba(255,255,255,.1);margin:0 0 10px}
#${BH.DOM.flowRootId} .${BH.DOM.flowProgressClass} i{display:block;height:100%;width:0;border-radius:999px;
  background:${ACCENT};transition:width .12s linear}
#${BH.DOM.flowRootId} .jf-meta{display:flex;justify-content:space-between;gap:12px;font-size:12px;
  color:#8b99ad;margin-bottom:18px}
#${BH.DOM.flowRootId} .${BH.DOM.flowNoteClass}{min-height:20px;font-size:13px;color:#c3cede;margin-bottom:18px}
#${BH.DOM.flowRootId} .${BH.DOM.flowNoteClass}[data-kind="bad"]{color:#ff9b9b}
#${BH.DOM.flowRootId} .${BH.DOM.flowNoteClass}[data-kind="ok"]{color:#8ce8b4}
#${BH.DOM.flowRootId} .jf-actions{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
#${BH.DOM.flowRootId} button{font:inherit;padding:9px 18px;border-radius:10px;cursor:pointer;
  border:1px solid rgba(255,255,255,.16);background:rgba(255,255,255,.06);color:inherit}
#${BH.DOM.flowRootId} button.primary{background:${ACCENT};color:#04121a;border-color:transparent;font-weight:600}
#${BH.DOM.flowRootId} .${BH.DOM.flowTargetClass}{position:fixed;width:24px;height:24px;margin:-12px 0 0 -12px;
  border-radius:50%;border:2px solid ${ACCENT};box-shadow:0 0 0 6px rgba(110,231,255,.18);
  animation:jfPulse 1.4s ease-in-out infinite}
#${BH.DOM.flowRootId} .jf-report{text-align:left;margin:0 0 18px;padding:0;list-style:none;font-size:13px}
#${BH.DOM.flowRootId} .jf-report li{display:flex;justify-content:space-between;gap:12px;padding:5px 0;
  border-bottom:1px solid rgba(255,255,255,.06)}
#${BH.DOM.flowRootId} .jf-report b{font-weight:500;color:#c3cede}
#${BH.DOM.flowRootId} .jf-ok{color:#8ce8b4}
#${BH.DOM.flowRootId} .jf-failed{color:#ff9b9b}
#${BH.DOM.flowRootId} .jf-skipped{color:#8b99ad}
@keyframes jfPulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.25);opacity:.65}}
@media (prefers-reduced-motion:reduce){
  #${BH.DOM.flowRootId} .${BH.DOM.flowTargetClass}{animation:none}
  #${BH.DOM.flowRootId} .${BH.DOM.flowProgressClass} i{transition:none}
}`;

  /* La coque. `document` est **injecté** : c'est la couture qui la rend
     testable sous node avec le double de DOM des Slices 05 et 07, et qui évite
     qu'un module de page lise un global qu'il n'a pas déclaré. */
  function createFlowOverlay(deps){
    const d=deps&&typeof deps==='object'?deps:{};
    const doc=d.document;
    if(!doc||typeof doc.createElement!=='function')
      throw new RangeError('createFlowOverlay exige `document` : la coque dessine, et un module qui lit un global qu’il n’a pas déclaré ne se teste pas');
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    let root=null,kicker=null,heading=null,instruction=null,bar=null,elapsed=null,deadline=null;
    let note=null,actions=null,report=null,target=null,timer=null;
    let openedAt=null,stageAt=null,stageLimit=null,onExit=null,onKey=null,inerted=[];

    function ensureStyle(){
      if(doc.getElementById(STYLE_ID))return;
      const style=doc.createElement('style');
      style.id=STYLE_ID;style.textContent=STYLE;
      (doc.head||doc.body).appendChild(style);
    }
    const el=(tag,cls,text)=>{
      const node=doc.createElement(tag);
      if(cls)node.className=cls;
      if(text!==undefined)node.textContent=text;
      return node;
    };
    /* Le compteur vivant, et la seule raison pour laquelle cette coque a une
       minuterie. Sans lui, « ça travaille » et « c'est bloqué » s'écrivent
       exactement pareil à l'écran — c'est la correction la plus répétée de ce
       dépôt. */
    function paintClock(){
      if(!root||root.hidden)return;
      const since=Math.max(0,Math.round((now()-openedAt)/1000));
      elapsed.textContent=`${since} s`;
      if(stageLimit===null||stageAt===null){deadline.textContent='';return}
      const left=Math.max(0,Math.ceil((stageLimit-(now()-stageAt))/1000));
      deadline.textContent=`${left} s restantes`;
    }
    function build(){
      ensureStyle();
      root=el('div');root.id=BH.DOM.flowRootId;
      root.setAttribute('role','dialog');
      root.setAttribute('aria-modal','true');
      const step=el('div',BH.DOM.flowStepClass);
      /* Posée **une fois**, hors de `actions` : `buttons()` vide `actions` à
         chaque étape, et une sortie qu'un parcours peut effacer sans le savoir
         n'est pas une sortie. Elle porte `data-flow-close` et non
         `data-flow-action`, pour que ce que le parcours dessine reste lisible
         séparément de ce que la coque garantit. */
      const close=el('button','jf-close','×');
      close.setAttribute('type','button');
      close.setAttribute('data-flow-close','1');
      close.setAttribute('aria-label','Quitter ce parcours');
      close.setAttribute('title','Quitter (Échap)');
      close.addEventListener('click',()=>{if(onExit)onExit('fermeture')});
      step.appendChild(close);
      kicker=el('div','jf-kicker');
      heading=el('h2');
      instruction=el('p','jf-instruction');
      const progress=el('div',BH.DOM.flowProgressClass);
      bar=el('i');progress.appendChild(bar);
      const meta=el('div','jf-meta');
      elapsed=el('span','','0 s');deadline=el('span');
      meta.appendChild(elapsed);meta.appendChild(deadline);
      note=el('div',BH.DOM.flowNoteClass);
      report=el('ul','jf-report');report.hidden=true;
      actions=el('div','jf-actions');
      step.appendChild(kicker);step.appendChild(heading);step.appendChild(instruction);
      step.appendChild(progress);step.appendChild(meta);step.appendChild(note);
      step.appendChild(report);step.appendChild(actions);
      root.appendChild(step);
      (doc.body||doc.documentElement).appendChild(root);
    }
    /* Le balayage `inert`, **et l'exemption**. La page derrière est désarmée
       pendant le parcours, mais la surimpression des mains ne l'est pas : on
       calibre *avec ses mains*, donc le jeton doit continuer de vivre. La
       question « est-ce une racine Bare Hands » appartient au contrat, comme
       pour le dialogue de confirmation de la page. */
    function sweepInert(on){
      const body=doc.body;
      if(!body||!body.children)return;
      if(on){
        inerted=[...body.children].filter(node=>
          node!==root&&!node.inert&&node.tagName!=='SCRIPT'&&!BH.isBareHandsRoot(node));
        for(const node of inerted)node.inert=true;
      }else{
        for(const node of inerted)node.inert=false;
        inerted=[];
      }
    }
    return {
      isOpen(){return !!root&&!root.hidden},
      /* Ouvrir. `exit` est **obligatoire** : une coque plein écran sans sortie
         est un piège, et c'est le quatrième point de la règle zéro. */
      open(spec){
        const s=spec&&typeof spec==='object'?spec:{};
        if(typeof s.exit!=='function')
          throw new RangeError('createFlowOverlay.open exige `exit` : une surimpression plein écran sans sortie est un piège');
        if(!root)build();
        onExit=s.exit;
        openedAt=now();stageAt=null;stageLimit=null;
        root.hidden=false;
        root.setAttribute('aria-label',String(s.title||'Parcours Bare Hands'));
        sweepInert(true);
        onKey=event=>{if(event&&event.key==='Escape'){event.preventDefault&&event.preventDefault();onExit('escape')}};
        if(typeof doc.addEventListener==='function')doc.addEventListener('keydown',onKey);
        /* La minuterie du compteur est **injectée** : sans elle la coque
           s'afficherait et le compteur resterait figé sur « 0 s », ce qui est
           pire que pas de compteur du tout. Elle est optionnelle uniquement
           parce qu'un test qui pilote l'horloge à la main n'en veut pas. */
        timer=typeof d.setInterval==='function'?d.setInterval(paintClock,250):null;
        paintClock();
        return true;
      },
      /* Une étape : ce qu'on demande, et l'échéance qu'elle ne peut pas
         dépasser. `index`/`total` disent où on en est — un parcours dont on ne
         voit pas la fin se lit comme un parcours sans fin. */
      step(spec){
        const s=spec&&typeof spec==='object'?spec:{};
        if(!root)return null;
        kicker.textContent=`Étape ${Number(s.index)||1} sur ${Number(s.total)||1}`;
        heading.textContent=String(s.title||'');
        instruction.textContent=String(s.instruction||'');
        note.textContent='';note.setAttribute('data-kind','');
        report.hidden=true;
        stageAt=now();
        stageLimit=Number.isFinite(Number(s.deadlineMs))?Number(s.deadlineMs):null;
        this.progress(0);
        paintClock();
        return true;
      },
      progress(value){
        if(!bar)return 0;
        const at=Math.min(Math.max(Number(value)||0,0),1);
        bar.style.width=`${Math.round(at*100)}%`;
        bar.setAttribute('data-at',at.toFixed(2));
        paintClock();
        return at;
      },
      note(text,kind){
        if(!note)return '';
        note.textContent=String(text||'');
        note.setAttribute('data-kind',String(kind||''));
        return note.textContent;
      },
      /* Le point à viser, en **pixels de la fenêtre** : la coque dessine à
         l'écran, et c'est la seule unité qu'un écran connaisse. */
      target(point){
        if(!root)return null;
        if(!point){if(target){target.remove();target=null}return null}
        if(!target){target=el('div',BH.DOM.flowTargetClass);root.appendChild(target)}
        target.style.left=`${Math.round(Number(point.x)||0)}px`;
        target.style.top=`${Math.round(Number(point.y)||0)}px`;
        return {x:Number(point.x)||0,y:Number(point.y)||0};
      },
      /* Les boutons de l'étape courante. Redessinés à chaque fois : un bouton
         qui survit à l'étape qui l'a posé déclenche ce que l'écran ne montre
         plus. */
      buttons(list){
        if(!actions)return 0;
        actions.innerHTML='';
        for(const item of(Array.isArray(list)?list:[])){
          const button=el('button','',String(item.label||''));
          if(item.primary)button.className='primary';
          if(item.id)button.setAttribute('data-flow-action',String(item.id));
          button.addEventListener('click',()=>item.run&&item.run());
          actions.appendChild(button);
        }
        return actions.children.length;
      },
      /* Le rapport de fin : ce que chaque étape a donné. C'est la décision 31
         rendue **lisible** — « partiellement calibré » sans dire quelle partie
         ne laisse rien à faire à l'utilisateur. */
      report(rows){
        if(!report)return 0;
        report.innerHTML='';
        for(const row of(Array.isArray(rows)?rows:[])){
          const line=el('li');
          /* **Un mot hors vocabulaire se refuse, il ne se dessine pas.**
             `jf-${status}` fabriquait une classe que la feuille ne définit
             pas : la ligne sortait sans couleur, sans erreur et sans
             avertissement, et « réussi » ressemblait à « passé ». Le repli
             muet sur `skipped` était pire encore — il *mentait*. C'est la
             règle de ce dépôt (un refus codé plutôt qu'un défaut plausible),
             et c'est ce qui tient la coque honnête pour un deuxième parcours :
             le tutoriel (Slice 09) traduit ses propres statuts vers ces trois
             mots de **présentation**, au lieu de les emprunter au profil. */
          const status=String(row.status||'');
          if(!FLOW_STATUS.includes(status))
            throw new RangeError(`createFlowOverlay.report : statut « ${status} » hors vocabulaire de la coque (${FLOW_STATUS.join(', ')}). `
              +'Un mot inconnu produirait une classe que la feuille ne définit pas, donc une ligne sans couleur — et « réussi » se lirait comme « passé ».');
          line.appendChild(el('b','',String(row.label||'')));
          line.appendChild(el('span',`jf-${status}`,String(row.detail||'')));
          report.appendChild(line);
        }
        report.hidden=!report.children.length;
        return report.children.length;
      },
      elapsedMs(){return openedAt===null?0:now()-openedAt},
      /* L'échéance de l'étape est passée : la coque le **dit**, elle ne décide
         pas. C'est le parcours qui sait ce qu'une étape expirée doit devenir. */
      expired(){return stageLimit!==null&&stageAt!==null&&(now()-stageAt)>stageLimit},
      close(){
        if(!root)return false;
        if(timer!==null&&typeof d.clearInterval==='function')d.clearInterval(timer);
        timer=null;
        if(onKey&&typeof doc.removeEventListener==='function')doc.removeEventListener('keydown',onKey);
        onKey=null;
        sweepInert(false);
        if(target){target.remove();target=null}
        root.remove();root=null;
        openedAt=null;stageAt=null;stageLimit=null;
        return true;
      },
    };
  }

  /* ------------------------------------------------------------------ 6
     Le parcours (décisions 27, 29, 30, 31).

     Une machine à états dirigée par les images : rien ne tourne tant que
     l'utilisateur n'a pas lancé le parcours (décision 27), et tout s'arrête
     quand il est fini (décision 30 : pas d'apprentissage continu). Chaque
     étape réussit ou échoue **seule** ; une étape ratée laisse ses clés nulles,
     donc le moteur garde ses défauts (décision 31), et le rapport dit laquelle.

     Aucune image n'entre : `feed()` reçoit l'enregistrement de scalaires que le
     contrôleur construit. C'est la décision 32, tenue par la couture. */
  function createCalibration(deps){
    const d=deps&&typeof deps==='object'?deps:{};
    const overlay=d.overlay;
    if(!overlay||typeof overlay.open!=='function')
      throw new RangeError('createCalibration exige `overlay` (createFlowOverlay) : la coque est partagée avec le tutoriel (décision 26), elle ne se recrée pas ici');
    if(typeof d.save!=='function')
      throw new RangeError('createCalibration exige `save` : un parcours qui mesure sans pouvoir enregistrer ne dit rien à personne');
    /* **L'horloge du chien de garde, exigée à la construction.** Le parcours
       n'est nourri que par `deps.onMeasure`, que le contrôleur ne tire qu'en
       ACTIVE **et seulement s'il a observé une main** : sans second mécanisme,
       l'utilisateur qui sort du cadre coupe la seule chose qui regardait
       l'échéance, et l'étape 1 sur 7 ne se solde plus jamais (mesuré à
       200 000 ms). Elle est **obligatoire** plutôt qu'optionnelle, et c'est la
       leçon de la croix de sortie (Slice 09) : une garantie que chaque appelant
       doit se rappeler de respecter n'est pas une garantie, c'est une
       convention. Le parcours l'ouvre dans `start()` et la referme dans
       `stop()`, donc elle ne vit que pendant lui (décisions 27 et 30). */
    if(typeof d.setInterval!=='function'||typeof d.clearInterval!=='function')
      throw new RangeError('createCalibration exige `setInterval`/`clearInterval` : l’échéance d’une étape ne peut pas dépendre des seules images, que zéro main observée suffit à arrêter — l’étape resterait alors ouverte pour toujours sous un compteur figé sur « 0 s restantes »');
    const o=options(d.options);
    const band=wakeBandOf(d.engineDefaults);
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const viewport=typeof d.viewport==='function'?d.viewport:()=>({width:1280,height:720});
    const say=typeof d.log==='function'?d.log:()=>{};

    let running=false,at=-1,collected=null,reports=null,derived=null,finished=null;
    let pinchLow=false,repeats=0,aimAt=null,pressFrom=null,clickTravels=null,dragTravels=null;
    let secondHandSeen=false,holdFrom=null;

    const stepAt=index=>STEPS[index]||null;
    const blank=()=>({samples:[],xs:[],ys:[]});

    /* Une étape se solde une fois, et une seule. `skipped` n'est pas `failed` :
       ce que l'utilisateur n'a pas joué ne lui reproche rien.

       **Le motif survit au changement d'étape**, et c'est la RÈGLE ZÉRO, pas
       une commodité : la phrase qui explique un échec était écrite par
       `finishHold`/`finishPinch` puis effacée par `overlay.step()` à l'image
       suivante — affichée zéro milliseconde. L'utilisateur voyait son C
       refusé sans jamais apprendre que c'était son majeur. Elle est donc
       **portée** dans l'étape suivante, préfixée du nom de l'étape ratée, avec
       le fait qu'on continue quand même (décision 31). */
    let carry=null;
    function settle(status,reason,samples,detail,message){
      const step=stepAt(at);
      if(!step)return;
      reports[step.id]={status,reason:reason||null,samples:Math.max(0,Math.round(samples||0))};
      if(detail)say('info',`[barehands] calibration ${step.id} : ${status}`,detail);
      carry=status===BH.STAGE_STATUS.FAILED
        ?{text:`${step.title} : ${message||LABEL[reason]||'mesure impossible'}. Bare Hands gardera ses valeurs d’usine pour cette étape ; on continue.`,kind:'bad'}
        :null;
      advance();
    }

    /* **L'échéance d'une étape, évaluée sans image.** Elle vit ici et non dans
       `feed()` parce que `feed()` n'est appelée que quand le contrôleur a
       **observé une main** : zéro main devant la caméra, et la seule chose qui
       regardait la montre ne tournait plus. Le motif rendu est le plus
       **utile**, pas le plus littéral : « temps écoulé » est vrai de toutes ces
       pannes et n'aide personne. Rend `true` si l'étape vient de se solder. */
    function expire(){
      if(!overlay.expired())return false;
      const step=stepAt(at);
      const reason=!collected.samples.length?BH.STAGE_REASON.NO_HAND
        :(step&&step.needs>1&&!secondHandSeen)?BH.STAGE_REASON.NEEDS_TWO_HANDS
        :BH.STAGE_REASON.TIMEOUT;
      settle(BH.STAGE_STATUS.FAILED,reason,collected.samples.length);
      return true;
    }

    function advance(){
      at+=1;
      const step=stepAt(at);
      if(!step){conclude();return}
      collected=blank();
      pinchLow=false;repeats=0;pressFrom=null;holdFrom=null;secondHandSeen=false;
      overlay.step({index:at+1,total:STEPS.length,title:step.title,
        instruction:step.instruction,deadlineMs:o.stageTimeoutMs});
      /* La cible d'une étape de visée est posée **au centre-bas** de l'écran :
         un point qu'on atteint sans sortir du cadre de la caméra, ce qui est
         justement ce qu'on n'a pas encore mesuré. */
      if(step.target){
        const view=viewport();
        aimAt={x:Math.round(view.width*.5),y:Math.round(view.height*.62)};
        overlay.target(aimAt);
      }else{aimAt=null;overlay.target(null)}
      /* Sortir, et **passer**. Une étape qu'on ne peut pas réussir sans pouvoir
         la passer est un cul-de-sac : la décision 31 existe précisément pour
         que le parcours survive à une étape ratée. */
      overlay.buttons([
        {id:'skip',label:'Passer cette étape',run:()=>settle(BH.STAGE_STATUS.SKIPPED,null,collected.samples.length)},
        {id:'exit',label:'Quitter',run:()=>cancel('bouton')},
      ]);
      if(carry){overlay.note(carry.text,carry.kind);carry=null}
    }

    /* Ce qu'on garde d'une image : les scalaires de cette main, et rien
       d'autre. La sélection est **par nom** — un enregistrement qui porterait
       autre chose ne le transmettrait pas (décision 32). */
    const KEEP=Object.freeze(['t','handedness','primaryRatio','secondaryRatio','cPose','closure',
      'gapPalms','indexReachPalms','palmNorm','xNorm','yNorm',
      'rawX','rawY','filteredX','filteredY','palmX','palmY','quality','stillness','speedPxPerSec']);
    function keep(sample){
      const kept={};
      for(const key of KEEP)kept[key]=sample[key];
      return kept;
    }

    function conclude(){
      overlay.target(null);
      derived=deriveProfile(collectedAll,reports,o,band,viewport());
      finished=true;
      overlay.step({index:STEPS.length,total:STEPS.length,title:'Résultat',
        instruction:'Voici ce qui a été mesuré. Appliquer remplace votre profil ; annuler ne touche à rien.',
        deadlineMs:null});
      /* **Après `step()`, jamais avant.** `step()` remet la phrase à zéro : la
         conclusion s'écrivait puis s'effaçait dans la même pile d'appels, donc
         « Aucune mesure n'a pu être retenue » était affiché zéro milliseconde —
         la leçon du motif porté d'une étape à l'autre, répétée à la dernière
         page du parcours, et sur la seule phrase qui dit à l'utilisateur si
         ses mesures ont servi. */
      overlay.progress(1);
      overlay.note(derived.measuredCount
        ?`${derived.measuredCount} mesure(s) retenue(s). Rien n’est enregistré tant que vous ne l’avez pas demandé.`
        :'Aucune mesure n’a pu être retenue : Bare Hands gardera ses réglages d’usine.',
        derived.measuredCount?'ok':'bad');
      overlay.report(STEPS.map(step=>{
        const report=reports[step.id];
        return {label:step.title,status:report.status,
          detail:report.status===BH.STAGE_STATUS.OK?`mesuré (${report.samples})`
            :report.status===BH.STAGE_STATUS.SKIPPED?'passée'
            :`échouée — ${LABEL[report.reason]||report.reason}`};
      }));
      /* **Appliquer est explicite** (exigence de la Slice). Un parcours qui
         enregistre tout seul à la dernière image prend une décision que
         l'utilisateur n'a pas prise, et sur des mesures qu'il n'a pas vues. */
      overlay.buttons([
        {id:'apply',label:'Appliquer et enregistrer',primary:true,run:()=>apply()},
        {id:'discard',label:'Annuler',run:()=>cancel('résultat refusé')},
      ]);
    }

    let collectedAll=null;
    async function apply(){
      const payload=derived&&derived.payload;
      if(!payload){cancel('rien à enregistrer');return}
      overlay.note('Enregistrement…','');
      try{
        await d.save(payload);
        overlay.note('Profil enregistré.','ok');
        say('info','[barehands] profil de calibration enregistré',derived.measured);
        stop();
        if(typeof d.onSaved==='function')d.onSaved(derived);
      }catch(error){
        /* RÈGLE ZÉRO : vu, journalisé, et la coque **reste ouverte** — la
           refermer sur un échec d'enregistrement jetterait une minute de
           mesures sans que l'utilisateur puisse réessayer. */
        overlay.note(`Enregistrement impossible : ${error&&error.message||error}`,'bad');
        say('warn','[barehands] profil non enregistré',error);
        overlay.buttons([
          {id:'retry',label:'Réessayer',primary:true,run:()=>apply()},
          {id:'discard',label:'Abandonner',run:()=>cancel('enregistrement abandonné')},
        ]);
      }
    }

    function cancel(why){
      say('info',`[barehands] calibration interrompue (${why})`);
      stop();
      if(typeof d.onCancelled==='function')d.onCancelled(String(why||''));
    }
    function stop(){
      running=false;at=-1;collected=null;collectedAll=null;derived=null;finished=null;
      stopClock();
      overlay.close();
    }
    /* Le chien de garde, **posé une fois pour tout le parcours** et non par
       étape : il doit survivre à chaque entrée dans une étape, y compris à une
       étape rejouée, sans quoi la seconde traversée retomberait sur la panne
       qu'il existe pour empêcher. `advance()` ne le touche donc pas. */
    let clockId=null;
    function startClock(){
      if(clockId!==null)return clockId;
      clockId=d.setInterval(()=>{api.tick()},o.watchdogMs);
      return clockId;
    }
    function stopClock(){
      if(clockId===null)return false;
      d.clearInterval(clockId);clockId=null;
      return true;
    }

    /* Les deux sorties que la coque produit, dites en français dans le
       journal. Même table et mêmes mots que celle du tutoriel : un test les
       compare, faute de pouvoir les partager — le tutoriel reçoit une coque,
       pas ce module (décision 26). */
    const EXIT_WORD=Object.freeze({escape:'échap',fermeture:'croix'});
    const LABEL=Object.freeze({
      [BH.STAGE_REASON.NO_HAND]:'aucune main vue',
      [BH.STAGE_REASON.TIMEOUT]:'temps écoulé',
      [BH.STAGE_REASON.TOO_FEW_SAMPLES]:'pas assez de mesures',
      [BH.STAGE_REASON.NOT_SEPARABLE]:'les deux états ne se distinguent pas',
      [BH.STAGE_REASON.OUT_OF_BAND]:'hors de la plage utilisable',
      [BH.STAGE_REASON.NEEDS_TWO_HANDS]:'deux mains nécessaires',
      [BH.STAGE_REASON.CANCELLED]:'interrompue',
    });

    /* Nommé plutôt qu'anonyme : le chien de garde appelle `tick()` par la
       **porte publique**, donc il traverse exactement les mêmes gardes qu'un
       appelant extérieur — une seconde évaluation privée de l'échéance aurait
       pu en diverger sans que rien ne le dise. */
    const api={
      isRunning(){return running},
      /* L'horloge tourne-t-elle ? Lue **sur la minuterie elle-même**, comme
         `measuring()` lit `deps.onMeasure` côté page : sans cette lecture,
         « le chien de garde est posé » et « on a oublié de le poser »
         s'écrivent pareil, à l'écran comme à la console. */
      watching(){return clockId!==null},
      stepId(){const step=stepAt(at);return step?step.id:null},
      /* **Le point d'entrée**, et il confirme (contrat §12). Il rend
         `{ok:true}` dès que la coque est à l'écran et que la première étape
         tourne — pas à la fin du parcours : l'échéance du canal de commandes
         est de trois secondes et une calibration en prend trente. Confirmer le
         **démarrage** est ce que le contrat demande, et c'est aussi ce qui est
         vrai. */
      start(){
        if(running)
          /* Déjà ouverte : c'est l'état que l'appelant demandait. Répondre
             « non » ferait dire à JARVIS que ça n'a pas démarré devant une
             coque ouverte à l'écran. */
          return {ok:true,flow:'calibration',already:true,step:this.stepId()};
        reports={};
        for(const step of STEPS)reports[step.id]={status:BH.STAGE_STATUS.SKIPPED,reason:null,samples:0};
        collectedAll={};
        running=true;at=-1;finished=false;
        clickTravels=[];dragTravels=[];
        /* Le mot de sortie vient de la **coque**, qui sait laquelle de ses
           sorties a servi (Slice 09) : l'ignorer journalisait « échap » pour
           un clic sur la croix, c'est-à-dire la mauvaise cause pour une action
           que l'utilisateur a bien faite. Les deux mots sont ceux que la coque
           émet, traduits ici comme le tutoriel traduit les siens. */
        overlay.open({title:'Calibration Bare Hands',
          exit:why=>cancel(EXIT_WORD[why]||String(why||'demandé'))});
        startClock();
        advance();
        say('info','[barehands] calibration démarrée');
        return {ok:true,flow:'calibration',step:this.stepId(),steps:STEPS.length};
      },
      exit(reason){if(!running)return false;cancel(reason||'demandé');return true},
      /* **Le second mécanisme, et il ne peut pas être bloqué comme le
         premier.** `feed()` n'arrive que par la couture `deps.onMeasure`, que
         le contrôleur ne tire qu'en ACTIVE **et seulement s'il a observé une
         main**. L'utilisateur qui sort du cadre ou masque l'objectif coupait
         donc la seule chose qui regardait l'échéance : l'étape 1 sur 7 ne se
         soldait plus (mesuré à 200 000 ms, dix fois l'échéance), le compteur
         restait figé sur « 0 s restantes », et le module promettait pourtant
         qu'« une étape porte toujours une échéance ». Une horloge la tient
         maintenant aussi.

         **Il ne fabrique pas d'image.** C'est la différence avec le chien de
         garde du tutoriel (Slice 09), qui appelle bien `feed()` : une
         observation de tutoriel se construit à partir de ce que la page publie
         déjà, alors qu'un enregistrement de calibration ne peut naître que
         dans la boucle d'images (décision 32). Un `feed({hands:[]})` de
         complaisance affirmerait « aucune main » sans rien en savoir, et
         l'écrirait à l'écran. `tick()` ne prétend donc rien : il regarde la
         montre, et il dit ce qu'il voit.

         Rend l'étape courante, comme `feed()`. */
      tick(){
        /* `finished` est **redondant aujourd'hui** et gardé exprès : le
           récapitulatif pose `deadlineMs:null` (donc `expired()` est faux) et
           `at` a dépassé la dernière étape (donc `stepAt(at)` est nul). Deux
           mécanismes le couvrent déjà, et une mutation qui le retire ne change
           rien d'observable — il coûte une comparaison et dit l'intention :
           un parcours conclu ne se solde pas une fois de plus. */
        if(!running||finished||!collected||!stepAt(at))return null;
        if(expire())return this.stepId();
        /* RÈGLE ZÉRO : sans cette phrase, une étape sans la moindre image
           laisse l'écran muet pendant vingt secondes — et « la caméra ne me
           voit pas » ne se distingue pas de « le parcours est planté ». Elle
           ne peut pas recouvrir un compte de pincements ni une barre de
           maintien : ceux-là n'existent qu'à partir du premier échantillon. */
        if(!collected.samples.length)
          overlay.note('Aucune main n’est vue. Montrez vos mains à la caméra, ou passez cette étape.','bad');
        return this.stepId();
      },
      /* Une image de scalaires. Rend l'étape courante, pour que l'appelant
         puisse la lire sans connaître la machine. */
      feed(record){
        if(!running||finished)return null;
        const step=stepAt(at);
        if(!step)return null;
        const hands=(record&&Array.isArray(record.hands)?record.hands:[])
          .filter(hand=>Number(hand.quality)>=o.sampleQualityMin);
        const time=Number(record&&record.now);
        if(hands.length>=2)secondHandSeen=true;
        /* L'échéance d'abord : une étape expirée ne doit pas pouvoir avaler
           une image de plus, sinon « temps écoulé » dépend de la cadence.
           **Même porte que le chien de garde** (`tick`) : deux évaluations de
           l'échéance qui divergeraient rendraient le motif dépendant de qui a
           regardé la montre en premier. */
        if(expire())return this.stepId();
        if(!hands.length){overlay.note('Aucune main sûre n’est vue. Approchez-vous de la caméra.','bad');return this.stepId()}
        for(const hand of hands){
          const kept=keep(hand);
          collected.samples.push(kept);
          if(Number.isFinite(kept.xNorm))collected.xs.push(kept.xNorm);
          if(Number.isFinite(kept.yNorm))collected.ys.push(kept.yNorm);
          const bucket=collectedAll[kept.handedness]||(collectedAll[kept.handedness]={xs:[],ys:[],all:[]});
          bucket.all.push(kept);
          if(Number.isFinite(kept.xNorm))bucket.xs.push(kept.xNorm);
          if(Number.isFinite(kept.yNorm))bucket.ys.push(kept.yNorm);
        }
        const first=hands[0];
        const ratio=step.id===BH.STAGE.PINCH_SECONDARY?first.secondaryRatio:first.primaryRatio;
        /* Une répétition = une descente sous le seuil d'usine puis une
           remontée. On compte des **franchissements**, pas des images : la
           cadence de la caméra ne doit pas décider du nombre de pincements. */
        if(step.id===BH.STAGE.PINCH_PRIMARY||step.id===BH.STAGE.PINCH_SECONDARY){
          if(Number.isFinite(ratio)){
            if(!pinchLow&&ratio<band.releaseRatio)pinchLow=true;
            else if(pinchLow&&ratio>band.releaseRatio){pinchLow=false;repeats+=1}
          }
          overlay.progress(repeats/o.pinchRepeats);
          overlay.note(`${repeats} pincement(s) sur ${o.pinchRepeats}`,'');
          if(repeats>=o.pinchRepeats)finishPinch(step);
          return this.stepId();
        }
        if(step.hold){
          const steady=Number(first.stillness)>=.35;
          if(!steady){holdFrom=null;overlay.progress(0);
            overlay.note('Gardez la main immobile.','');return this.stepId()}
          if(holdFrom===null)holdFrom=time;
          const held=time-holdFrom;
          overlay.progress(held/o.stageHoldMs);
          if(held>=o.stageHoldMs)finishHold(step);
          return this.stepId();
        }
        if(step.id===BH.STAGE.AIM||step.id===BH.STAGE.DRAG){
          const pinched=Number.isFinite(first.primaryRatio)&&first.primaryRatio<band.releaseRatio;
          if(pinched&&pressFrom===null)pressFrom={x:first.palmX,y:first.palmY,at:time};
          if(!pinched&&pressFrom!==null){
            const travelPx=Math.hypot(Number(first.palmX)-pressFrom.x,Number(first.palmY)-pressFrom.y);
            /* En **fraction de la largeur de l'image**, pas en pixels : c'est
               l'unité que le profil persiste, et la conversion se fait ici,
               là où la largeur du moment est connue. */
            const width=Math.max(1,Number(viewport().width)||1);
            const travelNorm=travelPx/width;
            if(step.id===BH.STAGE.AIM)clickTravels.push(travelNorm);else dragTravels.push(travelNorm);
            pressFrom=null;
            settle(BH.STAGE_STATUS.OK,null,collected.samples.length);
            return this.stepId();
          }
          overlay.progress(pressFrom?.6:.2);
          overlay.note(pressFrom?'Relâchez quand vous êtes prêt.'
            :step.id===BH.STAGE.AIM?'Amenez le jeton sur le point, puis pincez.'
            :'Pincez, puis déplacez la main.','');
          return this.stepId();
        }
        if(step.id===BH.STAGE.RESIZE){
          overlay.progress(secondHandSeen?.8:.2);
          overlay.note(secondHandSeen?'Deux mains vues, écartez-les doucement.'
            :'Montrez vos deux mains.','');
          if(secondHandSeen&&collected.samples.length>=o.stageMinSamples*2)
            settle(BH.STAGE_STATUS.OK,null,collected.samples.length);
          return this.stepId();
        }
        return this.stepId();
      },
    };
    return api;

    function finishHold(step){
      if(step.id===BH.STAGE.NEUTRAL){
        const jitter=deriveJitter(collected.samples,o);
        if(!jitter.ok){settle(BH.STAGE_STATUS.FAILED,jitter.reason,jitter.samples);return}
        store(collected.samples,'jitterPx',jitter.jitterPx);
        settle(BH.STAGE_STATUS.OK,null,jitter.samples,jitter);
        return;
      }
      const check=checkCPose(collected.samples,band,o);
      if(!check.ok){
        /* La cause qu'on ne devine pas a sa phrase : un C dont le majeur reste
           près du pouce marque zéro alors que l'écart pouce-index est parfait
           (gate du canal secondaire, Slice 04). */
        const why=check.cause==='secondary'
          ?'votre majeur reste trop près du pouce, donc Bare Hands lit un clic droit et non une posture — écartez le majeur'
          :check.cause==='gap_low'?'pouce et index sont trop proches, écartez-les davantage'
          :check.cause==='gap_high'?'pouce et index sont trop écartés, c’est une main ouverte et non un C'
          :check.cause==='reach'?'l’index n’est pas assez déplié'
          :'la posture n’a pas tenu assez longtemps';
        settle(BH.STAGE_STATUS.FAILED,check.reason,check.samples,check,why);
        return;
      }
      /* Le C **ne pose aucun seuil** : la bande de réveil est lue par le
         guetteur de veille, avant qu'une main ait une latéralité, donc un
         seuil par main n'y aurait pas de lecteur (décision 28). Cette étape
         répond à la question que l'utilisateur se pose — « est-ce que mon C
         réveille ? » — et sa réponse vit dans le rapport, pas dans une clé. */
      settle(BH.STAGE_STATUS.OK,null,check.samples,check);
    }

    function finishPinch(step){
      const key=step.id===BH.STAGE.PINCH_SECONDARY?'secondaryRatio':'primaryRatio';
      const read=deriveHysteresis(collected.samples.map(sample=>sample[key]),o);
      if(!read.ok){
        settle(BH.STAGE_STATUS.FAILED,read.reason,read.samples,read,
          read.reason===BH.STAGE_REASON.NOT_SEPARABLE
            ?'le pincement et la main ouverte se ressemblent trop pour qu’un seuil les sépare'
            :undefined);
        return;
      }
      const prefix=step.id===BH.STAGE.PINCH_SECONDARY?'secondary':'';
      const press=prefix?'secondaryPressRatio':'pressRatio';
      const release=prefix?'secondaryReleaseRatio':'releaseRatio';
      /* **Par paire, toujours.** Enregistrer un seuil d'appui sans son seuil de
         relâchement laisserait le moteur mélanger une mesure et un défaut, ce
         qui peut inverser `press < release` — le serveur le refuse, et il a
         raison. */
      store(collected.samples,press,read.pressRatio);
      store(collected.samples,release,read.releaseRatio);
      settle(BH.STAGE_STATUS.OK,null,read.samples,read);
    }

    /* Une mesure est rangée **par latéralité** : c'est la main qui l'a produite
       qui la porte (décision 28, valeurs internes par main). Une main que le
       traqueur n'étiquette pas tombe dans `unknown`, qui existe au contrat
       pour ça. */
    function store(samples,key,value){
      const counts={};
      for(const sample of samples)counts[sample.handedness]=(counts[sample.handedness]||0)+1;
      for(const handedness of Object.keys(counts)){
        const bucket=collectedAll[handedness]||(collectedAll[handedness]={xs:[],ys:[],all:[]});
        (bucket.measures||(bucket.measures={}))[key]=value;
      }
    }

    function deriveProfile(buckets,stages,opts,wake,view){
      const hands={};
      const measured=[];
      const travel=deriveTravelSlop(clickTravels,dragTravels,opts);
      for(const handedness of Object.keys(buckets||{})){
        const bucket=buckets[handedness];
        const hand={...(bucket.measures||{})};
        const reach=deriveReach(bucket.xs,bucket.ys,opts);
        if(reach.ok)hand.reachNorm=reach.reachNorm;
        if(travel.ok)hand.travelSlopNorm=travel.travelSlopNorm;
        /* La qualité du profil de cette main : la médiane de la qualité de
           suivi pendant la séance. C'est une **métrique**, pas un seuil — elle
           ne change rien au moteur, elle dit à quel point croire le reste. */
        const quality=median(bucket.all.map(sample=>sample.quality));
        if(quality!==null)hand.quality=quality;
        /* **Ce qu'on compte est ce qui calibre**, et `quality` n'en est pas
           (`PROFILE_METRIC_KEYS`) : elle est écrite dès qu'un seau a vu une
           image, donc la compter faisait annoncer « 1 mesure(s) retenue(s) » à
           un parcours dont les sept étapes avaient échoué — la coque disait
           l'inverse du `calibrated` que le même profil portait. */
        for(const key of Object.keys(hand))
          if(hand[key]!==null&&hand[key]!==undefined&&!BH.PROFILE_METRIC_KEYS.includes(key))
            measured.push(`${handedness}.${key}`);
        hands[handedness]=hand;
      }
      if(!travel.ok&&travel.reason===BH.STAGE_REASON.NOT_SEPARABLE)
        stages[BH.STAGE.DRAG]={status:BH.STAGE_STATUS.FAILED,
          reason:BH.STAGE_REASON.NOT_SEPARABLE,samples:travel.samples||0};
      const profile=BH.normalizeProfile({
        schemaVersion:BH.PROFILE_SCHEMA_VERSION,
        updatedAt:now(),hands,stages,
      });
      return {payload:BH.toProfilePayload(profile),profile,
        measured:measured.sort(),measuredCount:measured.length,
        viewportWidth:Number(view&&view.width)||null};
    }
  }

  const api=Object.freeze({
    DEFAULTS,options,STEPS,FLOW_STATUS,
    quantile,median,stdev,
    deriveJitter,deriveHysteresis,deriveTravelSlop,deriveReach,checkCPose,wakeBandOf,
    createFlowOverlay,createCalibration,STYLE,STYLE_ID,
  });
  root.JarvisBarehandsCalibration=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
