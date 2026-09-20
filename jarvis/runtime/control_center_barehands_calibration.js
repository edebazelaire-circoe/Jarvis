/* Bare Hands V1 — parcours de calibration et coque de surimpression (Slice 08).
   Architecture §10 et §11, décisions 26 à 32.

   Deux choses vivent ici, et c'est la décision 26 qui les met ensemble :

   - **la coque de surimpression**, plein écran, floutée et **sans carte**,
     avec un titre, une consigne, une progression, un compteur vivant et une
     sortie évidente. Elle ne sait rien de la calibration : elle affiche des
     étapes. Le tutoriel (Slice 09) la réutilise telle quelle — « deux
     parcours, une coque » est un choix de produit, pas une ressemblance ;

     **Refonte, Slice 05 (décisions 18 à 21, architecture §6).** La carte
     centrée de 560 px a été refusée par l'utilisateur : pas rabotée,
     remplacée. Ce qui la remplace est une **couche de présentation plein
     cadre** — un voile flouté qui laisse la scène JARVIS visible derrière au
     lieu de la recouvrir de noir, un bandeau haut (numéro, grand titre, une
     phrase), une **scène centrale vide** qui occupe l'essentiel du cadre, une
     progression légère et des commandes secondaires. La scène est vide
     *volontairement* : elle se remplit par `mount()`, et les cinq régions
     nommées (`FLOW_SLOTS`) sont le contrat que les parcours suivants lisent au
     lieu d'inventer chacun leur géométrie ;
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
  if(!BH){
    /* Même règle que l'aperçu de cible (§6), le tutoriel (§13) et
       l'enregistreur (§12) : la cause part dans la console et **ce module
       seul** reste absent. La page servie n'a qu'une seule balise `<script>`,
       donc une levée au chargement emporterait la scène, la timeline et le
       Test Lab avec elle. Le refus n'est pas adouci — il est confiné. */
    console.error('[barehands] barehands.calibration_not_installed '
      +JSON.stringify({error:'les contrats Bare Hands doivent être insérés avant ce module'}));
    return;
  }
  /* **Le vocabulaire de dessin des mains** (`control_center_barehands_hand_art.js`,
     Slice 04), servi avant ce module. Lu **à l'appel** et non figé au
     chargement : l'ordre d'insertion est garanti par la page, mais un test qui
     pose le global après avoir requis ce module-ci verrait sinon un `null`
     définitif, et « le dessin manque » se lirait comme « le dessin est vide ».

     Il n'est pas exigé pour **dériver** — la dérivation est pure et ne dessine
     rien — mais il l'est pour **construire un parcours** : une calibration sans
     démonstration montre une consigne écrite et un centre vide, c'est-à-dire le
     défaut plausible que ce dépôt refuse. `createCalibration` le refuse donc à
     la construction, comme il refuse déjà une coque ou une horloge absentes. */
  const handArt=()=>root.JarvisBarehandsHandArt
    ||(typeof JarvisBarehandsHandArt!=='undefined'?JarvisBarehandsHandArt:null);

  /* ------------------------------------------------------------------ 1
     Réglages du parcours, et les paires dangereuses qu'ils peuvent former.

     Même règle que partout sur cette tâche : une combinaison qui ne peut pas
     marcher se refuse **à la construction**, pas au premier utilisateur qui la
     rencontre. Les trois d'ici échouent toutes de la même façon — en silence,
     en retombant sur les défauts, ce qui se lit « l'utilisateur s'y prend
     mal ». */
  const DEFAULTS=Object.freeze({
    /* Échéance d'une étape **en mesure**, et seulement en mesure (Slice 06,
       architecture §7). Au-delà, l'étape **échoue et le dit** : une mesure qui
       attend pour toujours est la panne que la RÈGLE ZÉRO interdit. Elle ne
       court ni pendant la lecture (`introMs`) ni pendant que l'étape attend que
       l'utilisateur commence — c'est exactement la correction demandée : « le
       flux actuel commence à chronométrer pendant qu'on lit ». */
    stageTimeoutMs:20000,
    /* **Le temps de lecture, et ce n'est pas du temps de mesure** (décision 22).
       Durée minimale pendant laquelle le titre, la consigne et la démonstration
       sont à l'écran sans qu'aucune échéance ne descende. */
    introMs:2800,
    /* La tenue du verdict d'une étape avant de passer à la suivante
       (phase `RESULT`). Bornée des deux côtés : un verdict affiché zéro
       milliseconde n'a pas été rendu, un verdict qui reste est un parcours qui
       n'avance plus. */
    resultMs:1100,
    /* Images **consécutives** qu'il faut pour qu'un engagement compte. À une
       seule, un repère bruité arme l'étape et le chronomètre part contre
       quelqu'un qui n'a rien fait — le défaut d'origine déplacé de trois
       secondes. */
    engageFrames:2,
    /* Points à viser, répartis sur la surface utile de l'écran (décision 24).
       Un seul point toujours au même endroit n'enseigne pas « viser et
       cliquer » : il enseigne « pincer ». */
    aimTargets:3,
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
    /* **Paire dangereuse n° 16.** Un délai de lecture nul remet exactement le
       défaut que cette slice corrige : l'étape s'arme pendant que l'utilisateur
       lit, et la mesure démarre sur quelqu'un qui n'a pas fini la phrase. */
    if(!(o.introMs>0))
      throw new RangeError('introMs doit être strictement positif : à zéro l’étape s’arme pendant que l’utilisateur lit sa consigne, et « le parcours chronomètre pendant qu’on lit » est précisément le défaut que la phase de lecture existe pour corriger');
    /* **Paire dangereuse n° 17.** Personne ne nourrit une étape tant que
       l'utilisateur n'a pas montré ses mains : c'est donc le chien de garde qui
       fait finir la lecture. Plus lent qu'elle, c'est **lui** qui décide du
       moment où l'étape s'arme, et « prêt » arrive quand la montre le veut au
       lieu d'arriver quand la consigne a été lue. */
    if(!(o.watchdogMs<o.introMs))
      throw new RangeError('watchdogMs doit rester sous introMs : une étape que personne ne nourrit ne sort de la lecture que sur un battement du chien de garde, donc plus lent qu’elle il décide seul du moment où l’exercice s’arme');
    /* **Paire dangereuse n° 18.** Un verdict tenu plus longtemps que l'échéance
       d'une étape fait passer le parcours pour bloqué au moment précis où il
       vient de réussir. */
    if(!(o.resultMs>0&&o.resultMs<o.stageTimeoutMs))
      throw new RangeError('resultMs doit rester dans ]0,stageTimeoutMs[ : à zéro le verdict d’une étape est affiché zéro milliseconde, et au-delà de l’échéance le parcours a l’air bloqué à l’instant même où il vient de réussir');
    /* Même espèce que `stageMinSamples>=1` : en dessous de une image, le
       prédicat d'engagement est vrai avant que l'utilisateur ait bougé. */
    if(!(o.engageFrames>=1))
      throw new RangeError('engageFrames doit valoir au moins 1 : en dessous, une étape s’arme sans la moindre image qualifiante et la mesure démarre avant que l’utilisateur ait commencé');
    if(!(o.aimTargets>=1))
      throw new RangeError('aimTargets doit valoir au moins 1 : à zéro l’étape de visée se solde sans aucun clic mesuré, et la tolérance clic/glissement de tout le monde retombe sur le défaut d’usine');
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
      instruction:'Formez un C avec le pouce et l’index seuls : les deux s’écartent sans se toucher, les trois autres doigts restent repliés.',
      hold:true,needs:1}),
    Object.freeze({id:BH.STAGE.PINCH_PRIMARY,title:'Pincement pouce-index',
      instruction:'Pincez pouce et index, puis rouvrez. Recommencez tranquillement, comme pour cliquer.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.PINCH_SECONDARY,title:'Pincement pouce-majeur',
      instruction:'Même geste, autre doigt : pincez pouce et **majeur**, puis rouvrez. L’index reste replié. C’est le clic droit.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.AIM,title:'Viser et cliquer',
      instruction:'Amenez le jeton sur chaque point, puis pincez pouce et index sans bouger la main.',
      hold:false,needs:1,target:true}),
    Object.freeze({id:BH.STAGE.DRAG,title:'Faire glisser',
      instruction:'Pincez, déplacez la main franchement vers la droite, puis relâchez.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.RESIZE,title:'Deux mains',
      instruction:'Montrez vos deux mains et écartez-les doucement, comme pour agrandir une image.',
      hold:false,needs:2}),
  ]);

  /* ------------------------------------------------------------------ 4bis
     **Les phases d'une étape** (architecture §7, décisions 22 et 23).

     « Étape ouverte = test en cours » était faux, et cher : l'échéance de vingt
     secondes commençait à brûler à l'instant où la consigne s'affichait, donc
     l'utilisateur la lisait avec une montre déjà lancée contre lui — et
     quelqu'un qui gardait les mains sur les genoux échouait à une étape qu'il
     n'avait jamais commencée. L'Humain l'a refusé mot pour mot.

     Cinq phases, et **une seule chronomètre** :

     - `INTRO`   — lecture et démonstration, durée minimale `introMs`. Aucune
                   échéance de mesure ne court ; la coque n'en affiche aucune.
     - `ARMED`   — l'utilisateur *peut* commencer. Pour le repos, le C et les
                   deux pincements, l'étape reste ici **indéfiniment** tant
                   qu'il est inactif. Rien ne descend, la consigne reste.
     - `RUNNING` — la mesure tourne, et `stageTimeoutMs` **vit ici, et
                   seulement ici**. Le chien de garde de la page continue de la
                   surveiller, parce que zéro main vue coupe les images.
     - `RESULT`  — le verdict, tenu `resultMs`. Les règles de repli partiel ne
                   changent pas d'un iota : une étape ratée laisse ses clés
                   nulles et le moteur garde ses défauts (décision 31).
     - `NEXT`    — on avance.

     **RÈGLE ZÉRO pendant une phase sans échéance, et c'est la question que
     cette slice pose.** La règle interdit un état qui dure pour toujours parce
     qu'un utilisateur ne peut pas distinguer « ça attend » de « c'est
     bloqué ». `ARMED` porte cette distinction autrement, et explicitement :
     la démonstration continue de mimer le geste (*quelque chose tourne*), le
     bandeau de phases montre « Prêt » allumé et « Mesure » éteint (*quoi*), le
     compteur de la coque continue de compter la séance (*depuis combien de
     temps*), la phrase dit en toutes lettres que rien ne se mesure tant qu'on
     n'a pas commencé, et trois sorties sont à l'écran en permanence — « Passer
     cette étape », « Quitter », la croix, plus Échap (*comment en sortir*).

     Surtout : `ARMED` **n'est pas un état de travail**. Rien n'y tourne qui
     puisse se coincer ; la seule chose qui en sort est un geste de
     l'utilisateur, et il en sort par ses propres commandes. Y poser une
     échéance serait un compte à rebours contre quelqu'un qui n'a rien
     commencé, c'est-à-dire le défaut qu'on répare. */
  const PHASE=Object.freeze({INTRO:'intro',ARMED:'armed',RUNNING:'running',
    RESULT:'result',NEXT:'next'});
  const PHASE_ORDER=Object.freeze([PHASE.INTRO,PHASE.ARMED,PHASE.RUNNING,
    PHASE.RESULT,PHASE.NEXT]);
  /* Les trois phases que l'utilisateur **voit** passer, et leur mot. `RESULT`
     et `NEXT` n'ont pas de pastille : à ce moment-là les trois sont derrière
     lui, et la phrase du verdict occupe déjà la ligne vivante. */
  const PHASE_STRIP=Object.freeze([
    Object.freeze([PHASE.INTRO,'Lecture']),
    Object.freeze([PHASE.ARMED,'Prêt']),
    Object.freeze([PHASE.RUNNING,'Mesure']),
  ]);

  /* **Le lien entre une étape et la main qu'elle montre.** Il vit ici, et
     nulle part ailleurs : `hand_art` est un alphabet de formes qui ne sait rien
     des gestes (frontière de la Slice 04, épinglée par un test qui grep sa
     source). Une étape déclare la posture qu'elle montre ; le dessin déclare à
     quoi ressemble une posture. Lier les deux est le travail de qui affiche.

     `mime:true` alterne deux postures — l'invariant n° 1 de `hand_art` (ouvrir
     et fermer un pincement ne bouge **que** les deux doigts qui pincent) est ce
     qui rend cette alternance lisible au lieu de faire sauter toute la main.
     L'alternance est en CSS : ce module n'ouvre aucune minuterie pour dessiner,
     et « moins de mouvement » l'arrête en posant les deux postures côte à côte
     plutôt qu'en supprimant l'information. */
  const DEMO=Object.freeze({
    [BH.STAGE.NEUTRAL]:Object.freeze({mime:false,
      poses:Object.freeze(['REST']),caption:'Main ouverte, immobile'}),
    /* Décision 27 : ce sont **le pouce et l'index** qui dessinent le C, et la
       posture replie les trois autres doigts pour qu'aucune autre forme ne se
       dispute la lecture. Un C tracé au milieu d'une main ouverte se lit
       « main ouverte ». */
    [BH.STAGE.C_POSE]:Object.freeze({mime:false,
      poses:Object.freeze(['WAKE_C']),caption:'Pouce et index dessinent le C'}),
    [BH.STAGE.PINCH_PRIMARY]:Object.freeze({mime:true,
      poses:Object.freeze(['PINCH_PRIMARY_OPEN','PINCH_PRIMARY_CLOSED']),
      caption:'Pouce et index : fermer, rouvrir'}),
    /* Même grammaire, silhouette franchement différente : ici l'index est
       replié et le majeur descend, donc la main n'a plus de doigt dressé. C'est
       cette différence-là qui doit sauter aux yeux entre l'étape 3 et l'étape
       4, et elle est dans les tracés, pas dans une couleur. */
    [BH.STAGE.PINCH_SECONDARY]:Object.freeze({mime:true,
      poses:Object.freeze(['PINCH_SECONDARY_OPEN','PINCH_SECONDARY_CLOSED']),
      caption:'Pouce et majeur : fermer, rouvrir'}),
    /* Décision 28 : la visée montre une main qui **pince** une cible. Jamais un
       index tendu — `pinch_target` est littéralement le pincement primaire
       fermé plus une mire, et un test de `hand_art` l'épingle. */
    [BH.STAGE.AIM]:Object.freeze({mime:true,
      poses:Object.freeze(['PINCH_PRIMARY_OPEN','PINCH_TARGET']),
      caption:'Pincer pouce-index sur le point'}),
  });

  /* Les points à viser, **répartis sur la surface utile** (décision 24, et les
     mots de l'Humain : « des cibles réparties sur l'écran »). En fractions de
     la fenêtre et non en pixels : la même consigne doit valoir sur un portable
     et sur un écran large. Le bandeau du haut et le pied sont évités — un point
     posé sur le titre ferait viser la consigne. */
  const AIM_SPOTS=Object.freeze([
    Object.freeze({x:.22,y:.36}),
    Object.freeze({x:.78,y:.36}),
    Object.freeze({x:.5,y:.7}),
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

  /* Les **cinq régions nommées** de la coque (refonte Slice 05, décisions 18 et
     19, architecture §6). Elles sont le livrable de cette slice autant que le
     dessin : sans un vocabulaire publié, chaque parcours qui vient inventerait
     sa propre géométrie dans le centre laissé libre, et « le centre est
     réservé à l'exercice » redeviendrait une intention au lieu d'un contrat.

     Trois se **remplissent** (`mount`/`clear`), deux appartiennent à la coque
     et se refusent : `progress` est écrite par `progress()`, `controls` par
     `buttons()`, et toutes deux sont réécrites à chaque étape — un contenu
     monté là disparaîtrait sans un mot, c'est-à-dire le défaut plausible que
     ce dépôt refuse. */
  const FLOW_SLOTS=Object.freeze(['demo','exercise','feedback','progress','controls']);
  const FLOW_MOUNTABLE=Object.freeze(['demo','exercise','feedback']);
  /* **Le plafond du vert** (décision 21). Le bleu est la couleur de la
     consigne ; le vert dit « reconnu », brièvement. L'ACTIVE vert a été retiré
     par l'utilisateur lui-même, et le même instinct vaut ici : une couleur de
     succès qu'on peut laisser allumée devient la couleur ambiante, et ne dit
     alors plus rien. `flash()` borne donc toute tenue à cette valeur, publiée
     pour qu'un test l'épingle au lieu de la deviner. */
  const FLASH_MAX_MS=2000;

  const STYLE_ID=BH.DOM.flowStyleId;
  const ACCENT='var(--omega-accent,var(--accent,#6ee7ff))';
  /* Écrit avec deux raccourcis parce que la feuille a triplé de taille et
     qu'une règle illisible ne se relit pas. `R` est la racine, `D` les noms du
     contrat : le texte **produit** porte les vrais noms, et c'est lui que le
     test contrat-feuille compare. */
  const R=`#${BH.DOM.flowRootId}`;
  const D=BH.DOM;
  const STYLE=`
/* ================================================================= Slice 05
   La coque **plein cadre**. Ce qui a été retiré compte autant que ce qui a été
   ajouté : la carte centrée de 560 px, son rayon de 20 px, son fond propre et
   son ombre portée ont été refusés par l'utilisateur, mot pour mot. Il ne
   reste aucune boîte — une grille occupe le cadre, le voile est la seule
   surface qui teinte, et le centre est vide *par construction* pour que
   l'exercice s'y installe.

   Trois couches, et elles ne se recouvrent pas au hasard :
     0 — le voile (flou, assombrissement, teinte bleue) ;
     1 — la mise en page de l'étape (bandeau, scène, pied) ;
     2+ — le rail de progression, la croix de sortie, la cible.
   La surimpression des mains, elle, n'est pas ici : elle est un **frère** dans
   \`body\`, à 2147483000, donc au-dessus de tout ceci — on calibre avec ses
   mains, il faut voir son jeton. */
/* \`box-sizing\` est posé **ici** et non hérité de la page. La coque est une
   feuille injectée : elle doit tenir sur une page qui n'a pas de remise à zéro,
   sinon \`height:100%\` plus une gouttière pousse le pied hors du cadre — et le
   compteur et la sortie sont dans le pied. Une RÈGLE ZÉRO qui dépend du reset
   de l'hôte n'est pas une garantie. */
${R},${R} *{box-sizing:border-box}
${R}{position:fixed;inset:0;z-index:2147482000;overflow:hidden;
  color:#e9f1fb;font:14px/1.6 ui-monospace,SFMono-Regular,Consolas,monospace;
  --jf-accent:${ACCENT};
  /* Le vert n'est **pas** un jeton de la coque au repos : il n'est lu que sous
     \`[data-flash]\`, et \`flash()\` borne sa durée. Décision 21. */
  --jf-ok:#6ff2b0;
  --jf-bad:#ffa3a3;
  --jf-muted:#93a6bd;
  --jf-soft:#c6d5e6;
  --jf-gutter:clamp(18px,4.5vw,64px);
  --jf-sans:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;
  animation:jfEnter .34s cubic-bezier(.2,.7,.3,1) both}
${R}[hidden]{display:none}
/* **Le voile** (décision 18). Deux choses qu'on ne fait pas : une nappe noire
   opaque, et un flou seul. L'assombrissement passe par
   \`backdrop-filter: brightness()\`, donc la scène JARVIS garde sa **couleur**
   au lieu d'être recouverte ; \`saturate\` l'empêche de virer au gris ; la
   nappe par-dessus est légère (.52 au centre) et dégradée, ce qui donne
   l'atmosphère que l'utilisateur demandait à la place du noir mort. La teinte
   bleue du haut dit que ce n'est pas un voile générique : c'est un mode. */
${R} .${D.flowVeilClass}{position:absolute;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(120% 86% at 50% -8%,rgba(110,231,255,.13),transparent 58%),
    radial-gradient(140% 120% at 50% 112%,rgba(8,20,34,.66),transparent 70%),
    linear-gradient(180deg,rgba(4,9,16,.52),rgba(3,7,13,.68));
  backdrop-filter:blur(18px) saturate(118%) brightness(.76);
  -webkit-backdrop-filter:blur(18px) saturate(118%) brightness(.76)}
/* Sans \`backdrop-filter\`, la nappe porte **seule** la lisibilité du texte :
   elle s'opacifie plutôt que de laisser la scène traverser un titre. Un
   navigateur qui ne floute pas ne doit pas rendre la consigne illisible. */
@supports not ((backdrop-filter:blur(1px)) or (-webkit-backdrop-filter:blur(1px))){
  ${R} .${D.flowVeilClass}{background:linear-gradient(180deg,rgba(4,9,16,.92),rgba(3,7,13,.95))}
}
/* **La mise en page de l'étape.** Les cinq \`none\`/\`0\` ne sont pas du bruit :
   ils disent que la carte est partie, et un test les lit. */
${R} .${D.flowStepClass}{position:relative;z-index:1;height:100%;
  display:grid;grid-template-rows:auto minmax(0,1fr) auto;gap:clamp(12px,2.4vh,28px);
  padding:clamp(30px,6vh,76px) var(--jf-gutter) clamp(18px,3.4vh,40px);
  max-width:none;background:none;border:0;border-radius:0;box-shadow:none}
/* Le rail de progression : une **ligne de cheveu** sur l'arête du cadre.
   Utile, et léger — la progression ne doit pas concurrencer l'exercice. */
${R} .${D.flowProgressClass}{position:absolute;top:0;left:0;right:0;height:2px;z-index:2;
  background:rgba(255,255,255,.07)}
${R} .${D.flowProgressClass} i{display:block;height:100%;width:0;
  background:linear-gradient(90deg,rgba(110,231,255,.3),var(--jf-accent));
  box-shadow:0 0 12px rgba(110,231,255,.5);transition:width .12s linear}
/* La sortie **permanente**. Les boutons d'une étape sont redessinés à chaque
   étape, donc « on peut toujours sortir » dépendait de ce que le parcours
   pensait à dessiner — et le rapport de calibration, par exemple, n'offre que
   « Annuler ». Celle-ci ne bouge pas, ne dépend d'aucun parcours, et occupe
   maintenant le coin **de l'écran** et non celui d'une carte. Quatrième point
   de la RÈGLE ZÉRO : comment en sortir. */
${R} .jf-close{position:absolute;z-index:3;top:clamp(12px,2vh,24px);right:clamp(12px,2vw,28px);
  width:40px;height:40px;padding:0;display:flex;align-items:center;justify-content:center;
  border-radius:50%;font-size:20px;line-height:1;letter-spacing:0;
  color:var(--jf-muted);background:transparent;border:1px solid rgba(255,255,255,.12)}
${R} .jf-close:hover{color:#e9f1fb;background:rgba(255,255,255,.1);
  border-color:rgba(255,255,255,.22)}
${R} .jf-close:focus-visible{outline:2px solid var(--jf-accent);outline-offset:3px}
/* ---------------------------------------------------------------- bandeau
   **Haut, grand, calme** (décision 19). Le titre est la seule chose de la
   coque qui ait le droit d'être grande ; tout le reste se tait. */
${R} .${D.flowHeaderClass}{display:flex;flex-direction:column;align-items:center;
  gap:clamp(8px,1.4vh,14px);text-align:center;max-width:min(960px,94vw);margin:0 auto}
${R} .jf-kicker{display:flex;align-items:center;gap:14px;
  font-size:12px;letter-spacing:.24em;text-transform:uppercase;color:var(--jf-accent)}
/* La progression **globale**, en segments : où on en est dans le parcours,
   lisible d'un coup d'œil et sans peser. Le compte exact est dans le texte
   juste à côté ; ces traits ne le répètent pas, ils le situent. */
${R} .jf-dots{display:flex;gap:5px;align-items:center}
${R} .jf-dots span{width:16px;height:2px;border-radius:999px;background:rgba(255,255,255,.16);
  transition:width .2s ease,background .2s ease}
${R} .jf-dots span[data-at="done"]{background:rgba(110,231,255,.5)}
${R} .jf-dots span[data-at="now"]{width:30px;background:var(--jf-accent);
  box-shadow:0 0 10px rgba(110,231,255,.6)}
${R} h2{margin:0;font-family:var(--jf-sans);font-weight:600;letter-spacing:-.02em;
  font-size:clamp(28px,4.4vw,54px);line-height:1.08;text-wrap:balance}
${R} .jf-instruction{margin:0;font-family:var(--jf-sans);color:var(--jf-soft);
  font-size:clamp(15px,1.5vw,20px);line-height:1.5;max-width:56ch;text-wrap:pretty}
/* ------------------------------------------------------------------ scène
   **Le centre, réservé** (décision 19). La coque ne dessine rien ici : elle
   tient la place, la centre, et donne la couleur. \`color\` est le crochet du
   dessin de main de la Slice 04 — ses tracés sont en \`currentColor\`, donc
   une main montée dans \`jf-demo\` est bleue sans rien savoir de la coque, et
   devient verte pendant un \`flash()\` sans une ligne de plus. */
${R} .${D.flowStageClass}{position:relative;display:flex;flex-direction:column;
  align-items:center;justify-content:center;gap:clamp(14px,3vh,34px);
  min-height:0;color:var(--jf-accent);transition:color .22s ease}
${R} .${D.flowDemoClass},${R} .${D.flowExerciseClass}{display:flex;align-items:center;
  justify-content:center;width:100%;min-height:0}
${R} .${D.flowDemoClass}{flex:0 0 auto}
${R} .${D.flowExerciseClass}{flex:1 1 auto}
/* Une fente vide ne prend pas de place : une étape qui n'a qu'une
   démonstration ne doit pas laisser un trou centré sous elle. */
${R} .${D.flowDemoClass}:empty,${R} .${D.flowExerciseClass}:empty{display:none}
/* ------------------------------------------------------------------- pied */
${R} .jf-foot{display:flex;flex-direction:column;align-items:center;gap:clamp(10px,1.8vh,18px)}
/* **Sous la scène, jamais par-dessus.** Un commentaire vivant qui recouvre
   l'exercice cache ce qu'il commente. */
${R} .${D.flowFeedbackClass}{display:flex;flex-direction:column;align-items:center;gap:8px;
  width:100%;min-height:24px;text-align:center}
${R} .${D.flowNoteClass}{font-family:var(--jf-sans);font-size:clamp(13px,1.2vw,16px);
  color:var(--jf-soft);transition:color .2s ease}
${R} .${D.flowNoteClass}[data-kind="bad"]{color:var(--jf-bad)}
${R} .${D.flowNoteClass}[data-kind="ok"]{color:var(--jf-ok)}
/* Le compteur vivant, en petit : troisième point de la RÈGLE ZÉRO. Il est
   discret mais il est **là**, et il l'est à chaque instant. */
${R} .jf-meta{display:flex;gap:20px;font-size:11px;letter-spacing:.16em;
  text-transform:uppercase;color:var(--jf-muted)}
/* Les commandes sont **secondaires** : des contours, pas des blocs. Seule
   l'action que l'utilisateur doit vraiment choisir (« Appliquer ») est pleine. */
${R} .${D.flowControlsClass}{display:flex;gap:10px;justify-content:center;flex-wrap:wrap}
${R} button{font:inherit;font-size:13px;letter-spacing:.05em;padding:10px 20px;border-radius:999px;
  cursor:pointer;color:var(--jf-muted);background:transparent;border:1px solid rgba(255,255,255,.14);
  transition:color .18s ease,border-color .18s ease,background .18s ease}
${R} button:hover{color:#e9f1fb;border-color:rgba(110,231,255,.45);background:rgba(110,231,255,.08)}
${R} button:focus-visible{outline:2px solid var(--jf-accent);outline-offset:3px}
${R} button.primary{color:#04121a;background:var(--jf-accent);border-color:transparent;font-weight:600}
${R} button.primary:hover{color:#04121a;background:#9af0ff}
/* Le rapport de fin vit **dans la scène** : à la dernière page il n'y a plus
   d'exercice, donc le centre lui revient. Il n'est plus tassé en bas d'une
   carte, il est ce qu'on est venu lire. */
${R} .jf-report{margin:0;padding:0;list-style:none;width:min(580px,92vw);font-size:13px}
${R} .jf-report[hidden]{display:none}
${R} .jf-report li{display:flex;justify-content:space-between;gap:18px;padding:9px 2px;
  border-bottom:1px solid rgba(255,255,255,.07)}
${R} .jf-report b{font-weight:400;color:var(--jf-soft)}
${R} .jf-ok{color:var(--jf-ok)}
${R} .jf-failed{color:var(--jf-bad)}
${R} .jf-skipped{color:var(--jf-muted)}
${R} .${D.flowTargetClass}{position:fixed;z-index:4;width:24px;height:24px;margin:-12px 0 0 -12px;
  border-radius:50%;border:2px solid var(--jf-accent);
  box-shadow:0 0 0 6px rgba(110,231,255,.16),0 0 26px rgba(110,231,255,.34);
  animation:jfPulse 1.4s ease-in-out infinite}
/* ------------------------------------------------- le vert, et sa laisse
   Décision 21 : bleu = consigne, vert = **un geste vient d'être reconnu**.
   Tout ce qui verdit est sous cet attribut, que seule \`flash()\` pose et que
   l'horloge de la coque retire — il n'existe aucun chemin qui laisse le vert
   allumé, et c'est exprès. L'ACTIVE vert a été retiré par l'utilisateur ; on
   ne le réintroduit pas par la bande. */
${R}[data-flash="ok"] .${D.flowStageClass}{color:var(--jf-ok)}
${R}[data-flash="ok"] .${D.flowProgressClass} i{background:var(--jf-ok);
  box-shadow:0 0 14px rgba(111,242,176,.55)}
${R}[data-flash="ok"] .${D.flowTargetClass}{border-color:var(--jf-ok);
  box-shadow:0 0 0 6px rgba(111,242,176,.2),0 0 26px rgba(111,242,176,.3)}
@keyframes jfPulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.25);opacity:.65}}
@keyframes jfEnter{from{opacity:0}to{opacity:1}}
/* ------------------------------------------------------------- adaptation
   Téléphone : gouttière de 16 px, titre ramené à une taille lisible sans
   déborder, commandes sur toute la largeur. Rien ne sort du cadre — aucun
   défilement horizontal. */
@media (max-width:720px){
  ${R} .${D.flowStepClass}{padding:clamp(22px,5vh,44px) 16px 18px;gap:12px}
  ${R} h2{font-size:clamp(24px,7.2vw,34px)}
  ${R} .jf-instruction{font-size:15px;max-width:40ch}
  ${R} .${D.flowStageClass}{gap:16px}
  ${R} .${D.flowControlsClass}{width:100%}
  /* Au doigt, une commande se vise : 44 px de haut, pas 36. La coque est
     secondaire, elle n'est pas pour autant à rater. */
  ${R} .${D.flowControlsClass} button{flex:1 1 44%;padding:13px 18px}
  ${R} .jf-close{top:12px;right:12px}
  ${R} .jf-dots span{width:12px}
  ${R} .jf-dots span[data-at="now"]{width:22px}
}
/* Fenêtre **basse** (paysage de téléphone, moitié d'écran) : c'est la hauteur
   qui manque, pas la largeur. Le bandeau se resserre pour que la scène garde
   le centre — si le titre mangeait la scène, l'exercice deviendrait
   injouable, ce qui est pire que de perdre deux tailles de police. */
@media (max-height:560px){
  ${R} .${D.flowStepClass}{padding-top:clamp(14px,3vh,26px);gap:8px}
  ${R} .${D.flowHeaderClass}{gap:4px}
  ${R} h2{font-size:clamp(20px,3.6vh,30px)}
  ${R} .jf-instruction{font-size:14px;line-height:1.4}
  ${R} .${D.flowStageClass}{gap:10px}
  ${R} .jf-foot{gap:8px}
  ${R} .jf-meta{font-size:10px}
  ${R} .jf-report li{padding:5px 2px}
}
/* --------------------------------------------------------- moins de mouvement
   Tout ce qui bouge s'arrête, et **ce qui portait l'information est remplacé**
   plutôt que supprimé : la cible ne pulse plus, donc elle reçoit un halo fixe
   plus marqué — une cible qu'on ne trouve pas rend l'étape injouable, et
   « accessible » ne peut pas vouloir dire « inutilisable ». */
@media (prefers-reduced-motion:reduce){
  ${R}{animation:none}
  ${R} .${D.flowTargetClass}{animation:none;
    box-shadow:0 0 0 7px rgba(110,231,255,.3),0 0 0 1px rgba(110,231,255,.55)}
  ${R} .${D.flowProgressClass} i{transition:none}
  ${R} .jf-dots span{transition:none}
  ${R} .${D.flowNoteClass}{transition:none}
  ${R} .${D.flowStageClass}{transition:none}
  ${R} button{transition:none}
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
    let root=null,veil=null,kickerText=null,dots=null,heading=null,instruction=null;
    let bar=null,elapsed=null,deadline=null;
    let note=null,actions=null,report=null,target=null,timer=null;
    let openedAt=null,stageAt=null,stageLimit=null,onExit=null,onKey=null,inerted=[];
    /* Les cinq régions nommées, par leur nom public. Un objet plutôt que cinq
       variables : `mount('demo',…)` et `regions().demo` doivent désigner le
       **même** nœud, et deux chemins vers un nœud finissent toujours par
       diverger quand ils ne partagent pas la table. */
    let slot=null;
    /* Ce que le parcours a monté, par région. Tenu pour que `clear()` retire
       **exactement** ce qu'il a posé : vider `jf-feedback` en bloc emporterait
       la ligne de commentaire que la coque y tient, et la RÈGLE ZÉRO perdrait
       sa phrase sans que personne ne l'ait demandé. */
    let mounted=null;
    /* Jusqu'à quand la ligne de commentaire est **tenue** (voir `note`).
       Remise à zéro à chaque ouverture et à chaque fermeture : une tenue qui
       survivrait à la coque bâillonnerait le parcours suivant. */
    let heldUntil=0;
    /* Jusqu'à quand le vert est allumé (décision 21). Même mécanique que
       `heldUntil`, et pour la même raison : une échéance lue sur l'horloge
       injectée, donc un test qui pilote le temps voit exactement ce que
       l'écran montre. Il n'existe pas de chemin qui l'allume sans échéance. */
    let flashUntil=0;

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
      /* Le vert s'éteint **ici**, sur la même horloge que le compteur : une
         couleur de succès qui dépendrait d'un `setTimeout` séparé pourrait
         rester allumée si ce minuteur-là était perdu, et le vert deviendrait
         ambiant — exactement ce que la décision 21 refuse. */
      paintFlash();
      const since=Math.max(0,Math.round((now()-openedAt)/1000));
      elapsed.textContent=`${since} s`;
      if(stageLimit===null||stageAt===null){deadline.textContent='';return}
      const left=Math.max(0,Math.ceil((stageLimit-(now()-stageAt))/1000));
      deadline.textContent=`${left} s restantes`;
    }
    /* Le vert, peint depuis l'échéance et jamais depuis un appel. Rend l'état
       réel, pour que « allumé » soit lisible par un test comme il l'est à
       l'écran. */
    function paintFlash(){
      if(!root)return false;
      const on=flashUntil>now();
      if(!on)flashUntil=0;
      root.setAttribute('data-flash',on?'ok':'');
      return on;
    }
    /* La progression **globale**, en segments : où on en est dans le parcours.
       Le compte exact reste dans le texte à côté — ces traits le situent, ils
       ne le répètent pas. Bornée à vingt-quatre segments : au-delà, une barre
       de traits d'un pixel ne dit plus rien et déborde le bandeau, alors que
       « Étape 40 sur 300 » reste vrai et lisible juste à côté. */
    const DOTS_MAX=24;
    function paintDots(index,total){
      if(!dots)return 0;
      dots.innerHTML='';
      const drawn=Math.max(1,Math.min(total,DOTS_MAX));
      for(let i=1;i<=drawn;i+=1){
        const segment=el('span');
        segment.setAttribute('data-at',i<index?'done':i===index?'now':'next');
        dots.appendChild(segment);
      }
      return drawn;
    }
    function build(){
      ensureStyle();
      root=el('div');root.id=BH.DOM.flowRootId;
      root.setAttribute('role','dialog');
      root.setAttribute('aria-modal','true');
      /* Focalisable, pour que le focus quitte la page que le balayage `inert`
         vient de désarmer. Sans cela le focus reste sur un nœud désarmé, et
         la navigation au clavier part de nulle part. */
      root.setAttribute('tabindex','-1');
      root.setAttribute('data-flash','');
      /* Le voile est une **couche**, pas un fond de la racine : il porte le
         flou et l'assombrissement, et la mise en page passe au-dessus sans
         les subir. `pointer-events:none` lui est posé par la feuille — ce
         n'est pas lui qui avale les clics, c'est la racine. */
      veil=el('div',BH.DOM.flowVeilClass);
      veil.setAttribute('aria-hidden','true');
      root.appendChild(veil);
      const step=el('div',BH.DOM.flowStepClass);
      /* Le rail de progression, **frère du bandeau et non enfant** : il est
         collé à l'arête du cadre, sur toute la largeur. */
      const progress=el('div',BH.DOM.flowProgressClass);
      bar=el('i');progress.appendChild(bar);
      step.appendChild(progress);
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
      /* ------------------------------------------------------- le bandeau */
      const header=el('div',BH.DOM.flowHeaderClass);
      const kicker=el('div','jf-kicker');
      kickerText=el('span');
      dots=el('div','jf-dots');
      kicker.appendChild(kickerText);kicker.appendChild(dots);
      heading=el('h2');
      instruction=el('p','jf-instruction');
      header.appendChild(kicker);header.appendChild(heading);header.appendChild(instruction);
      /* --------------------------------------------------------- la scène
         **Vide, et c'est le sujet de cette slice.** La coque tient la place et
         donne la couleur ; ce qui s'y montre appartient à l'étape. Le rapport
         de fin y vit aussi : à la dernière page il n'y a plus d'exercice, donc
         le centre lui revient. */
      const stage=el('div',BH.DOM.flowStageClass);
      const demo=el('div',BH.DOM.flowDemoClass);
      const exercise=el('div',BH.DOM.flowExerciseClass);
      report=el('ul','jf-report');report.hidden=true;
      stage.appendChild(demo);stage.appendChild(exercise);stage.appendChild(report);
      /* ----------------------------------------------------------- le pied */
      const foot=el('div','jf-foot');
      const feedback=el('div',BH.DOM.flowFeedbackClass);
      note=el('div',BH.DOM.flowNoteClass);
      /* Annoncée : un commentaire vivant qui n'existe qu'en pixels n'existe
         pas pour qui ne regarde pas l'écran. */
      note.setAttribute('aria-live','polite');
      note.setAttribute('data-kind','');
      feedback.appendChild(note);
      const meta=el('div','jf-meta');
      elapsed=el('span','','0 s');deadline=el('span');
      meta.appendChild(elapsed);meta.appendChild(deadline);
      actions=el('div',BH.DOM.flowControlsClass);
      foot.appendChild(feedback);foot.appendChild(meta);foot.appendChild(actions);
      step.appendChild(header);step.appendChild(stage);step.appendChild(foot);
      root.appendChild(step);
      /* La table des régions, écrite **une fois** : `regions()` la publie et
         `mount()` la consulte, donc les deux ne peuvent pas désigner deux
         nœuds différents. */
      slot=Object.freeze({header,stage,demo,exercise,feedback,progress,controls:actions});
      mounted={demo:[],exercise:[],feedback:[]};
      (doc.body||doc.documentElement).appendChild(root);
    }
    /* Retirer ce que le parcours a monté dans une région, et **rien d'autre**.
       Rend le nombre de nœuds retirés. */
    function unmount(name){
      const list=mounted&&mounted[name];
      if(!list||!list.length)return 0;
      const count=list.length;
      for(const node of list.splice(0,count))if(node&&typeof node.remove==='function')node.remove();
      return count;
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
        openedAt=now();stageAt=null;stageLimit=null;heldUntil=0;flashUntil=0;
        root.hidden=false;
        root.setAttribute('aria-label',String(s.title||'Parcours Bare Hands'));
        paintFlash();
        sweepInert(true);
        /* Le focus suit la coque. Le balayage `inert` vient de désarmer la
           page : laisser le focus dessus ferait partir la navigation au
           clavier d'un nœud qui ne répond plus. Gardé, parce qu'un double de
           DOM n'a pas de focus et que la coque n'en dépend pas. */
        if(typeof root.focus==='function')root.focus();
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
        const index=Number(s.index)||1,total=Number(s.total)||1;
        kickerText.textContent=`Étape ${index} sur ${total}`;
        paintDots(index,total);
        heading.textContent=String(s.title||'');
        instruction.textContent=String(s.instruction||'');
        note.textContent='';note.setAttribute('data-kind','');
        report.hidden=true;
        /* **La scène est vidée par l'étape qui arrive**, exactement comme les
           boutons le sont. Une démonstration qui survivrait à son étape
           montrerait la main d'une autre consigne, et c'est pire que rien :
           l'utilisateur ferait le geste affiché. Même règle que `buttons()`,
           écrite au même endroit pour qu'on ne l'oublie pas d'un côté. */
        for(const name of FLOW_MOUNTABLE)unmount(name);
        /* Le vert ne traverse pas une frontière d'étape : « reconnu » parlait
           de l'étape précédente. */
        flashUntil=0;paintFlash();
        stageAt=now();
        stageLimit=Number.isFinite(Number(s.deadlineMs))?Number(s.deadlineMs):null;
        this.progress(0);
        paintClock();
        return true;
      },
      /* ------------------------------------------------ les régions nommées
         (refonte Slice 05, architecture §6, décisions 18 et 19)

         Le contrat que les parcours suivants lisent au lieu d'inventer chacun
         sa mise en page. `regions()` rend les nœuds, `mount()` y pose du
         contenu, `clear()` le retire. La coque décide **où** ; l'étape décide
         **quoi**.

         Rend `null` quand la coque est fermée, et ne la construit pas : une
         image qui arrive après Échap ne doit pas faire réapparaître une
         surimpression que l'utilisateur vient de quitter. */
      regions(){return root?slot:null},
      /* Poser un nœud dans une région. Le nœud appartient à l'appelant ; la
         coque se contente de le placer, de le retirer au changement d'étape et
         de lui donner une couleur (`currentColor` vaut le bleu de la consigne
         dans la scène, et le vert pendant un `flash()` — c'est le crochet des
         dessins de main de la Slice 04, qui tracent en `currentColor`). */
      mount(name,node){
        const region=String(name);
        if(!FLOW_SLOTS.includes(region))
          throw new RangeError(`createFlowOverlay.mount : région « ${region} » inconnue. `
            +`Les régions de la coque sont ${FLOW_SLOTS.join(', ')}.`);
        if(!FLOW_MOUNTABLE.includes(region))
          throw new RangeError(`createFlowOverlay.mount : la région « ${region} » appartient à la coque. `
            +'« progress » est écrite par progress(), « controls » par buttons(), et les deux sont '
            +'réécrites à chaque étape — un contenu monté là disparaîtrait sans un mot. '
            +`Les régions qui se remplissent sont ${FLOW_MOUNTABLE.join(', ')}.`);
        if(!root||!node)return null;
        slot[region].appendChild(node);
        mounted[region].push(node);
        return node;
      },
      /* Vider une région, et **elle seule**. Ne retire que ce que `mount()` a
         posé : la ligne de commentaire que la coque tient dans `feedback` lui
         appartient et survit. Rend le nombre de nœuds retirés. */
      clear(name){
        const region=String(name);
        if(!FLOW_MOUNTABLE.includes(region))
          throw new RangeError(`createFlowOverlay.clear : région « ${region} » hors des régions qui se remplissent `
            +`(${FLOW_MOUNTABLE.join(', ')}).`);
        if(!root)return 0;
        return unmount(region);
      },
      /* **Le vert, et sa laisse** (décision 21). Un geste vient d'être
         reconnu : la scène, le rail et la cible verdissent pour une durée
         **bornée**, puis l'horloge de la coque les rend au bleu. Il n'existe
         aucun appel qui allume le vert sans échéance, et c'est le point : le
         vert ACTIVE a été retiré par l'utilisateur parce qu'une couleur de
         succès permanente cesse de signaler un succès. Rend la durée retenue. */
      flash(ms){
        const span=Number(ms);
        if(!Number.isFinite(span)||span<=0)
          throw new RangeError('createFlowOverlay.flash exige une durée finie et positive : le vert dit '
            +'« reconnu », pas « en cours ». Sans échéance il deviendrait la couleur ambiante de la coque, '
            +'ce que la décision 21 refuse explicitement.');
        if(!root)return 0;
        /* Bornée plutôt que refusée au-delà du plafond : une durée trop longue
           est une erreur de dosage, pas une erreur de sens, et lever au milieu
           d'une image reconnue tuerait le parcours pour un geste **réussi**.
           Le plafond est publié (`FLASH_MAX_MS`) pour qu'il se lise au lieu de
           se deviner. */
        const held=Math.min(span,FLASH_MAX_MS);
        flashUntil=now()+held;
        paintFlash();
        return held;
      },
      /* Le vert est-il allumé ? Lu sur l'échéance, jamais sur l'attribut :
         « on l'a posé » et « il est encore vrai » sont deux faits différents. */
      flashing(){return !!root&&flashUntil>now()},
      /* **Armer l'échéance de l'étape sans la redessiner** (Slice 06).

         `step()` pose une échéance *et* vide la scène. Une étape qui n'arme sa
         mesure qu'au moment où l'utilisateur engage ne peut donc pas repasser
         par lui : elle effacerait la démonstration qu'il est justement en train
         de regarder, et lui ferait relire une consigne au moment où il commence
         à faire le geste. La coque garde la montre, le parcours dit quand elle
         part — c'est la même répartition qu'avant, à ceci près que le départ
         n'est plus collé à l'ouverture de l'étape.

         `null` retire l'échéance, et alors **aucun compte à rebours n'est
         affiché** : c'est exactement ce qu'une phase de lecture doit montrer,
         et l'inverse d'un « 0 s restantes » qui mentirait. Rend l'échéance
         retenue. */
      deadline(ms){
        if(!root)return null;
        const span=ms===null||ms===undefined?null:Number(ms);
        if(span!==null&&!(Number.isFinite(span)&&span>0))
          throw new RangeError('createFlowOverlay.deadline exige une durée finie et positive, ou null pour retirer l’échéance : '
            +'une échéance nulle ou négative est déjà passée à l’instant où on la pose, donc l’étape expirerait à l’image suivante '
            +'sans que l’utilisateur ait eu une seule image pour agir.');
        stageAt=now();stageLimit=span;
        paintClock();
        return span;
      },
      progress(value){
        if(!bar)return 0;
        const at=Math.min(Math.max(Number(value)||0,0),1);
        bar.style.width=`${Math.round(at*100)}%`;
        bar.setAttribute('data-at',at.toFixed(2));
        paintClock();
        return at;
      },
      /* La ligne de commentaire de l'étape, et **la seule qui puisse être
         tenue** (Slice 10).

         Les deux parcours la réécrivent à **chaque image** : leur `paint()`
         est appelé par la cadence de la caméra, donc une phrase posée par
         quelqu'un d'autre vit 16 à 33 ms à 30-60 images par seconde. C'est
         exactement ce qui est arrivé au reçu d'une commande vocale pendant
         un tutoriel : la coque couvre le panneau (z-index 2147482000 contre
         70), donc « refusée — le tutoriel est déjà à l'écran » n'était
         lisible nulle part, dans le seul cas que la Slice 09 désigne comme
         celui qu'on regarde.

         `holdMs` tient la phrase pendant un temps borné : les notes **sans**
         `holdMs` — c'est-à-dire toutes celles des deux parcours, aujourd'hui
         et telles quelles — ne l'effacent pas avant son échéance, et rien
         d'autre ne change pour elles. Une tenue n'est jamais infinie : la
         RÈGLE ZÉRO interdit un état qui dure pour toujours autant qu'un état
         qui ne se voit pas, et l'étape doit pouvoir reprendre la parole. Une
         note **avec** `holdMs` remplace toujours la précédente : le plus
         récent de ce que l'utilisateur a demandé est ce qu'il attend de
         lire. */
      note(text,kind,holdMs){
        if(!note)return '';
        const hold=Number(holdMs);
        const held=Number.isFinite(hold)&&hold>0;
        if(!held&&heldUntil>now())return note.textContent;
        heldUntil=held?now()+hold:0;
        note.textContent=String(text||'');
        note.setAttribute('data-kind',String(kind||''));
        /* Repeint le vert en passant : les deux parcours écrivent une note à
           chaque image, donc c'est le chemin le plus souvent emprunté de la
           coque — celui qui garantit que le vert s'éteint même sans minuterie
           injectée (un test qui pilote l'horloge à la main n'en a pas). */
        paintFlash();
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
        /* Les nœuds montés sont détachés **explicitement** avant que la racine
           parte : `root.remove()` suffirait à les sortir de la page, mais pas
           à vider la table — et une table qui survit à la coque ferait tenir
           en vie l'arbre d'un parcours terminé (une fuite qu'aucun écran ne
           montre). Même raison que la remise à zéro de `heldUntil`. */
        for(const name of FLOW_MOUNTABLE)unmount(name);
        mounted=null;slot=null;
        root.remove();root=null;
        veil=null;kickerText=null;dots=null;heading=null;instruction=null;
        bar=null;elapsed=null;deadline=null;note=null;actions=null;report=null;
        openedAt=null;stageAt=null;stageLimit=null;heldUntil=0;flashUntil=0;
        return true;
      },
    };
  }

  /* ------------------------------------------------------------------ 5bis
     Ce que l'étape **montre** : la démonstration, le bandeau de phases et le
     champ de cibles (architecture §8, décision 20).

     Trois règles tiennent cette section entière.

     **Un seul alphabet de formes.** Rien n'est dessiné ici : tout passe par
     `hand_art`, qui trace en `currentColor`. La scène de la coque pose
     `color: var(--jf-accent)`, donc une main montée dedans est bleue sans une
     ligne de plus, et **verdit d'elle-même pendant un `flash()`** parce que le
     vert recolore la scène. C'est le crochet que la Slice 05 a laissé, et il
     évite un second système de dessin.

     **La démonstration n'est jamais une entrée** (architecture §8, décision
     32). Elle ne traverse pas `feed()`, `KEEP` ne la connaît pas, et rien de
     ce qu'elle montre n'atteint un profil. C'est de la consigne en image.

     **Aucune minuterie pour animer.** L'alternance ouvert↔fermé des étapes 3,
     4 et 5 est une animation CSS. Une minuterie de plus serait une chose de
     plus à fermer proprement à la sortie, pour un mouvement que la feuille
     sait faire — et `prefers-reduced-motion` l'arrête sans que ce module ait à
     le savoir.

     Feuille **séparée de celle de la coque**, et c'est le point : la coque ne
     sait rien du parcours qu'elle porte (c'est ce qui permet au tutoriel de la
     réutiliser telle quelle). Ces classes-ci sont de la calibration. */
  const STEPS_STYLE_ID=BH.DOM.flowStepsStyleId;
  const DEMO_CLASS='jf-mime';
  const STEPS_STYLE=`
/* ================================================================= Slice 06
   Les exercices : la main qui montre, le bandeau qui dit où on en est, et les
   points à viser. Rien ici n'appartient à la coque. */
/* ---------------------------------------------------------- la démonstration
   Les deux postures d'un mime sont **empilées** dans la même cellule de
   grille, pas posées l'une à côté de l'autre : c'est ce qui fait qu'on voit
   deux doigts se fermer et non deux mains différentes. L'invariant n° 1 de
   \`hand_art\` — ouvrir et fermer ne bouge que les deux doigts qui pincent —
   est ce qui rend l'empilement légitime. */
${R} .jf-demo-wrap{display:flex;flex-direction:column;align-items:center;
  gap:clamp(8px,1.6vh,16px)}
${R} .${DEMO_CLASS}{display:grid;place-items:center}
${R} .${DEMO_CLASS}>svg{grid-area:1/1;width:clamp(128px,24vh,232px);height:auto;
  filter:drop-shadow(0 0 18px rgba(110,231,255,.18))}
${R} .${DEMO_CLASS}[data-mime="0"]>svg{opacity:1}
${R} .${DEMO_CLASS}[data-mime="1"]>svg{opacity:0;animation:jfMime 2.4s ease-in-out infinite both}
${R} .${DEMO_CLASS}[data-mime="1"]>svg:nth-of-type(2){animation-delay:1.2s}
/* La légende dit **ce que le dessin montre**, pas ce qu'il faut faire : la
   consigne, elle, est déjà grande en haut. Deux phrases qui disent la même
   chose se concurrencent. */
${R} .jf-caption{margin:0;font-family:var(--jf-sans);font-size:11px;
  letter-spacing:.18em;text-transform:uppercase;color:var(--jf-muted)}
/* ------------------------------------------------------- le bandeau de phases
   **Le cœur de la RÈGLE ZÉRO quand il n'y a pas d'échéance à annoncer.** Trois
   mots, un seul allumé : l'utilisateur voit qu'on lit, puis qu'on attend, puis
   qu'on mesure. La pastille allumée respire — c'est la « preuve de vie » que
   le compte à rebours portait avant, sans le compte à rebours. */
${R} .jf-phases{display:flex;gap:clamp(10px,2vw,20px);align-items:center;
  font-family:var(--jf-sans);font-size:10px;letter-spacing:.2em;
  text-transform:uppercase;color:var(--jf-muted)}
${R} .jf-phases b{display:inline-flex;align-items:center;gap:7px;font-weight:400;
  transition:color .2s ease}
${R} .jf-phases b::before{content:'';width:6px;height:6px;border-radius:50%;
  background:rgba(255,255,255,.16);transition:background .2s ease}
${R} .jf-phases b[data-at="done"]{color:var(--jf-soft)}
${R} .jf-phases b[data-at="done"]::before{background:rgba(110,231,255,.45)}
${R} .jf-phases b[data-at="now"]{color:var(--jf-accent)}
${R} .jf-phases b[data-at="now"]::before{background:var(--jf-accent);
  box-shadow:0 0 10px rgba(110,231,255,.65);animation:jfBreath 1.7s ease-in-out infinite}
/* ------------------------------------------------------- le champ de cibles
   Les points **qui restent à faire**, en pointillés — même vocabulaire que la
   mire de \`pinch_target\` et que l'outil absent de la palette : discontinu =
   annoncé, plein = constaté. Le point **courant** n'est pas ici : c'est
   \`jf-target\` de la coque, qui pulse. Un seul point vivant à la fois, sinon
   « lequel je vise ? » redevient une question. */
${R} .jf-ghosts{position:fixed;inset:0;z-index:3;pointer-events:none}
${R} .jf-ghost{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;
  border-radius:50%;border:1.5px dashed rgba(110,231,255,.34);
  transition:border-color .2s ease,opacity .2s ease}
/* Touché : le trait devient **plein**, et reste bleu. Le vert dit « à
   l'instant » et la décision 21 lui interdit de rester allumé — un point déjà
   fait n'est plus un instant, c'est un acquis. */
${R} .jf-ghost[data-at="done"]{border-style:solid;border-color:rgba(110,231,255,.6);
  box-shadow:0 0 0 4px rgba(110,231,255,.1)}
/* Le point vivant est dessiné par la coque : son fantôme s'efface pour qu'il
   n'y ait pas deux anneaux au même endroit. */
${R} .jf-ghost[data-at="now"]{opacity:0}
@keyframes jfMime{0%{opacity:0}6%{opacity:1}44%{opacity:1}50%{opacity:0}100%{opacity:0}}
@keyframes jfBreath{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.5);opacity:.6}}
@media (max-width:720px){
  ${R} .${DEMO_CLASS}>svg{width:clamp(108px,34vw,172px)}
  ${R} .jf-phases{gap:12px;font-size:9px;letter-spacing:.14em}
}
@media (max-height:560px){
  ${R} .${DEMO_CLASS}>svg{width:clamp(92px,20vh,148px)}
  ${R} .jf-demo-wrap{gap:6px}
}
/* **Moins de mouvement, et l'information reste.** Le mime ne peut pas
   simplement s'arrêter : figé, il ne montrerait qu'une des deux postures, donc
   « fermer et rouvrir » deviendrait « fermer ». Les deux se posent alors côte à
   côte, toutes deux visibles — la lecture passe de la durée à l'espace. */
@media (prefers-reduced-motion:reduce){
  ${R} .${DEMO_CLASS}[data-mime="1"]{grid-auto-flow:column;align-items:center;
    gap:clamp(10px,3vw,28px)}
  ${R} .${DEMO_CLASS}[data-mime="1"]>svg{grid-area:auto;opacity:1;animation:none}
  ${R} .jf-phases b[data-at="now"]::before{animation:none}
  ${R} .jf-phases b,${R} .jf-phases b::before,${R} .jf-ghost{transition:none}
}`;

  /* La feuille des exercices, posée une fois. Même forme que `ensureStyle()` de
     la coque, et **pas** au même identifiant : deux propriétaires, deux
     feuilles, donc retirer l'une ne mutile pas l'autre. */
  function ensureStepsStyle(doc){
    if(doc.getElementById(STEPS_STYLE_ID))return false;
    const style=doc.createElement('style');
    style.id=STEPS_STYLE_ID;style.textContent=STEPS_STYLE;
    (doc.head||doc.body).appendChild(style);
    return true;
  }

  /* La démonstration d'une étape, ou `null` quand l'étape n'en déclare pas
     (le glissement et les deux mains sont à la Slice 07 ; leur centre reste
     vide plutôt que de montrer une main qui ment).

     **Un refus codé plutôt qu'un défaut plausible** : une posture que le
     vocabulaire ne connaît pas lève ici, elle ne retombe pas sur `rest`. Un
     écran qui montre une main ouverte là où on attend un pincement enseigne le
     mauvais geste, et rien ne le signale. */
  function demoNode(doc,stepId){
    const spec=DEMO[stepId];
    if(!spec)return null;
    const art=handArt();
    const wrap=doc.createElement('div');
    wrap.className='jf-demo-wrap';
    const box=doc.createElement('div');
    box.className=DEMO_CLASS;
    box.setAttribute('data-mime',spec.mime?'1':'0');
    box.setAttribute('data-demo',String(stepId));
    /* Annoncée **une fois**, sur le groupe : les postures empilées sont deux
       images du même fait, et deux `<title>` feraient lire le geste deux fois
       à un lecteur d'écran. Les SVG restent donc décoratifs (`handSvg` les pose
       `aria-hidden` quand on ne lui donne pas de `title`). */
    box.setAttribute('role','img');
    box.setAttribute('aria-label',spec.caption);
    for(const key of spec.poses){
      const pose=art.POSE[key];
      if(!pose)
        throw new RangeError(`La démonstration de l’étape ${stepId} demande la posture « ${key} », `
          +`que le vocabulaire de dessin ne publie pas. Postures connues : ${Object.keys(art.POSE).join(', ')}. `
          +'Une posture inconnue ne retombe pas sur la main au repos : un écran qui montre une main ouverte '
          +'là où on attend un pincement enseigne le mauvais geste.');
      box.appendChild(art.handSvg(doc,{pose,size:art.SIZE_DEFAULT*8,className:'bh-hand'}));
    }
    const caption=doc.createElement('p');
    caption.className='jf-caption';caption.textContent=spec.caption;
    wrap.appendChild(box);wrap.appendChild(caption);
    return wrap;
  }

  /* Le bandeau de phases. Rend son nœud et le seul geste qu'on lui demande :
     dire quelle phase est en cours. */
  function phaseStrip(doc){
    const box=doc.createElement('div');
    box.className='jf-phases';
    /* Annoncé : « on est passé de la lecture à prêt » est une information, et
       elle n'existe qu'en pixels pour qui ne regarde pas l'écran. */
    box.setAttribute('aria-live','polite');
    const chips={};
    for(const row of PHASE_STRIP){
      const chip=doc.createElement('b');
      chip.textContent=row[1];
      chip.setAttribute('data-phase',row[0]);
      chip.setAttribute('data-at','next');
      box.appendChild(chip);
      chips[row[0]]=chip;
    }
    return {node:box,set(phase){
      const rank=PHASE_ORDER.indexOf(phase);
      for(const row of PHASE_STRIP){
        const mine=PHASE_ORDER.indexOf(row[0]);
        chips[row[0]].setAttribute('data-at',
          rank<0?'next':mine<rank?'done':mine===rank?'now':'next');
      }
    }};
  }

  /* Les cibles **restantes**, en pointillés, à leur place dans la fenêtre. Le
     point courant est dessiné par la coque (`overlay.target`) : un seul anneau
     vivant à la fois. */
  function ghostField(doc,points){
    const layer=doc.createElement('div');
    layer.className='jf-ghosts';
    layer.setAttribute('aria-hidden','true');
    const dots=points.map(point=>{
      const dot=doc.createElement('div');
      dot.className='jf-ghost';
      dot.style.left=`${Math.round(point.x)}px`;
      dot.style.top=`${Math.round(point.y)}px`;
      dot.setAttribute('data-at','next');
      layer.appendChild(dot);
      return dot;
    });
    return {node:layer,set(index,done){
      dots.forEach((dot,at)=>dot.setAttribute('data-at',
        at<done?'done':at===index?'now':'next'));
    }};
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
    /* **`document`, exigé ici et non lu dans un global** (Slice 06). Le parcours
       dessine maintenant : une démonstration de main par étape, un bandeau de
       phases, un champ de cibles. Même couture que la coque, et pour la même
       raison — un module de page qui lit un global qu'il n'a pas déclaré ne se
       teste pas sous node. */
    const doc=d.document;
    if(!doc||typeof doc.createElement!=='function')
      throw new RangeError('createCalibration exige `document` : le parcours montre une démonstration de main à chaque étape, et un module qui lit un global qu’il n’a pas déclaré ne se teste pas');
    /* Le vocabulaire de dessin, **refusé absent à la construction**. Une
       calibration qui s'ouvrirait sans lui montrerait une consigne écrite
       au-dessus d'un centre vide : l'utilisateur lirait « formez un C » sans
       jamais voir lequel, ce qui est le défaut plausible que ce dépôt refuse.
       Même espèce que la coque et l'horloge ci-dessus : une garantie que
       l'appelant doit se rappeler de respecter n'est pas une garantie. */
    if(!handArt())
      throw new RangeError('createCalibration exige `control_center_barehands_hand_art.js`, inséré avant ce module : sans le vocabulaire de dessin, chaque étape montrerait une consigne écrite au-dessus d’un centre vide, et « formez un C » ne dirait pas lequel');
    const o=options(d.options);
    const band=wakeBandOf(d.engineDefaults);
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const viewport=typeof d.viewport==='function'?d.viewport:()=>({width:1280,height:720});
    const say=typeof d.log==='function'?d.log:()=>{};

    let running=false,at=-1,collected=null,reports=null,derived=null,finished=null;
    let pinchLow=false,repeats=0,aimAt=null,pressFrom=null,clickTravels=null,dragTravels=null;
    let secondHandSeen=false,holdFrom=null;
    /* La phase de l'étape courante, l'instant où elle a commencé, et le nombre
       d'images consécutives qui **qualifient** l'engagement. Le compteur est
       remis à zéro par la première image qui ne qualifie pas : c'est ce qui
       fait qu'un mouvement de passage n'arme rien (`engageFrames`). */
    let phase=null,phaseAt=0,engageRun=0;
    /* Une étape ne se solde **qu'une fois**. Sans ce verrou, « Passer cette
       étape » cliqué pendant la tenue du verdict écraserait un résultat déjà
       rendu, et le rapport dirait « passée » d'une étape que l'utilisateur
       vient de réussir. */
    let settled=false;
    /* La visée : les points à l'écran, celui qu'on vise, ceux qui sont faits.
       Les points ne sont **posés** qu'à la fin de la lecture (décision 24). */
    let aimPoints=null,aimIndex=0,aimHits=0,ghosts=null,strip=null;

    const stepAt=index=>STEPS[index]||null;
    const blank=()=>({samples:[],xs:[],ys:[]});

    /* **Ce qui compte comme « l'utilisateur a commencé »**, étape par étape.

       Contrainte de la slice, et c'est la bonne : **aucun nouveau modèle de
       geste**. Chaque prédicat ne lit que des scalaires que le contrôleur
       publie déjà et que le reste de ce module mesure déjà — `stillness`,
       `gapPalms`, `primaryRatio`, `secondaryRatio`, et le nombre de mains sûres
       — et il réemploie les seuils qui existent : `band`, recalculée depuis les
       défauts du moteur, et `HOLD_STILLNESS`, la même valeur que la tenue de
       pose utilise trente lignes plus bas. Rien ici n'est un seuil neuf.

       Ils sont volontairement **plus stricts que la mesure qu'ils arment**.
       Un prédicat laxiste ferait partir le chronomètre sur une main qui passe
       devant l'objectif, et le défaut d'origine serait simplement décalé de
       trois secondes. Une main ouverte qui dérive ne pince pas, n'est pas
       immobile et son écart pouce-index (près de six paumes) est hors de la
       bande du C : elle ne qualifie **aucune** des cinq étapes. */
    const HOLD_STILLNESS=.35;
    const ENGAGE=Object.freeze({
      // Le repos mesure un tremblement : on a commencé quand une main est posée.
      [BH.STAGE.NEUTRAL]:hand=>Number(hand.stillness)>=HOLD_STILLNESS,
      /* Le C : l'écart pouce-index entre dans la bande de réveil. Le score, le
         majeur et la tenue sont l'affaire de la **mesure** — les exiger ici
         rendrait injoignable l'échec le plus instructif de l'étape (un C que le
         majeur étouffe), puisque l'étape ne démarrerait jamais. */
      [BH.STAGE.C_POSE]:(hand,wake)=>Number.isFinite(hand.gapPalms)
        &&hand.gapPalms>=wake.gapMin&&hand.gapPalms<=wake.gapMax,
      // Les pincements : le canal concerné s'est réellement fermé une fois.
      [BH.STAGE.PINCH_PRIMARY]:(hand,wake)=>Number.isFinite(hand.primaryRatio)
        &&hand.primaryRatio<wake.releaseRatio,
      [BH.STAGE.PINCH_SECONDARY]:(hand,wake)=>Number.isFinite(hand.secondaryRatio)
        &&hand.secondaryRatio<wake.releaseRatio,
      /* La visée et le glissement démarrent sur le **pincement primaire**, qui
         est le geste que la cible existe pour provoquer (décision 28 : on pince
         la cible, on ne la pointe pas). */
      [BH.STAGE.AIM]:(hand,wake)=>Number.isFinite(hand.primaryRatio)
        &&hand.primaryRatio<wake.releaseRatio,
      [BH.STAGE.DRAG]:(hand,wake)=>Number.isFinite(hand.primaryRatio)
        &&hand.primaryRatio<wake.releaseRatio,
      /* Deux mains demandées, mais **une seule suffit à commencer**, et c'est
         délibéré. Exiger les deux rendrait l'étape injoignable pour qui n'en
         montre qu'une : elle resterait armée pour toujours, et
         `NEEDS_TWO_HANDS` — le motif qui dit précisément « il en manque une » —
         deviendrait injoignable dans le seul scénario qui porte son nom. On
         arme sur l'engagement, on mesure sur l'exigence, et l'échec explique. */
      [BH.STAGE.RESIZE]:()=>true,
    });

    /* Ce qu'il y a à faire pour démarrer, dit en français. La phrase de
       `ARMED` est la moitié « quoi » de la RÈGLE ZÉRO quand il n'y a pas
       d'échéance à annoncer ; l'autre moitié est le bandeau de phases. */
    const START=Object.freeze({
      [BH.STAGE.NEUTRAL]:'posez une main ouverte devant la caméra et ne bougez plus',
      [BH.STAGE.C_POSE]:'formez le C avec le pouce et l’index',
      [BH.STAGE.PINCH_PRIMARY]:'pincez pouce et index',
      [BH.STAGE.PINCH_SECONDARY]:'pincez pouce et majeur',
      [BH.STAGE.AIM]:'amenez le jeton sur le point, puis pincez pouce et index',
      [BH.STAGE.DRAG]:'pincez, puis déplacez la main',
      [BH.STAGE.RESIZE]:'montrez vos deux mains',
    });

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
      /* Une seule fois. « Passer cette étape » reste cliquable pendant la tenue
         du verdict — la sortie ne se retire jamais, RÈGLE ZÉRO — mais il ne
         doit pas réécrire un résultat déjà rendu. */
      if(!step||settled)return;
      settled=true;
      reports[step.id]={status,reason:reason||null,samples:Math.max(0,Math.round(samples||0))};
      if(detail)say('info',`[barehands] calibration ${step.id} : ${status}`,detail);
      const failed=status===BH.STAGE_STATUS.FAILED;
      const text=failed
        ?`${step.title} : ${message||LABEL[reason]||'mesure impossible'}. Bare Hands gardera ses valeurs d’usine pour cette étape ; on continue.`
        :status===BH.STAGE_STATUS.SKIPPED?`${step.title} : étape passée, rien n’a été mesuré.`
        :`${step.title} : mesuré.`;
      /* Le motif d'un échec **survit au changement d'étape** (RÈGLE ZÉRO) : il
         est tenu ici pendant `RESULT`, puis reposé dans la lecture de l'étape
         suivante. Écrit puis effacé par `overlay.step()`, il était affiché zéro
         milliseconde — l'utilisateur voyait son C refusé sans jamais apprendre
         que c'était son majeur. */
      carry=failed?{text,kind:'bad'}:null;
      if(status===BH.STAGE_STATUS.OK){
        /* **Le vert, bref, et seulement sur une réussite** (décision 21). La
           scène le porte, donc la main dessinée verdit avec elle sans une ligne
           de plus : les tracés de `hand_art` sont en `currentColor`. */
        overlay.flash(Math.min(o.resultMs,FLASH_MAX_MS));
        overlay.progress(1);
      }
      /* Tenue exactement le temps de la phase : à l'instant où le parcours
         avance, la laisse est échue, donc la phrase de lecture suivante n'est
         pas bâillonnée par celle-ci. */
      overlay.note(text,failed?'bad':status===BH.STAGE_STATUS.SKIPPED?'':'ok',o.resultMs);
      enterPhase(PHASE.RESULT);
    }

    /* **Le changement de phase, en un seul endroit** (architecture §7). C'est
       ici, et nulle part ailleurs, que l'échéance de mesure s'arme et se
       retire : `stageTimeoutMs` n'existe que sous `RUNNING`. Toute autre phase
       passe `null` à la coque, qui n'affiche alors aucun compte à rebours —
       un « 0 s restantes » sous une consigne qu'on lit serait un mensonge. */
    function enterPhase(next){
      phase=next;phaseAt=now();engageRun=0;
      if(strip)strip.set(next);
      if(next===PHASE.RUNNING){
        /* La mesure part **propre**. Les images de la lecture et de l'attente
           n'ont rien collecté, mais remettre le seau à zéro ici dit l'intention
           là où on la lit : ce qui entre dans un profil a été produit après que
           l'utilisateur a commencé. */
        collected=blank();
        pinchLow=false;repeats=0;pressFrom=null;holdFrom=null;secondHandSeen=false;
        overlay.deadline(o.stageTimeoutMs);
        overlay.progress(0);
      }else{
        overlay.deadline(null);
      }
      if(next===PHASE.ARMED&&aimPoints){
        /* **Décision 24 : les cibles n'apparaissent qu'ici.** Poser un point à
           viser sous une consigne qu'on est en train de lire, c'est demander de
           viser avant d'avoir lu. */
        aimIndex=0;
        if(ghosts)ghosts.set(aimIndex,aimHits);
        overlay.target(aimPoints[aimIndex]);
      }
      paintPhase();
    }

    /* Ce que l'écran dit pendant une phase où rien ne se mesure. Appelée à
       chaque image **et** à chaque battement du chien de garde, donc elle tient
       aussi quand la caméra ne voit personne — c'est le cas qui compte, parce
       que c'est celui où l'utilisateur n'a pas encore levé les mains. */
    function paintPhase(){
      const step=stepAt(at);
      if(!step)return;
      if(phase===PHASE.INTRO){
        /* La barre avance pendant la lecture : quelque chose tourne, et ce
           quelque chose est la lecture elle-même. Ce n'est pas un compte à
           rebours — au bout il n'y a pas un échec, il y a « à vous ». */
        const done=Math.min(1,Math.max(0,(now()-phaseAt)/o.introMs));
        overlay.progress(done);
        overlay.note('Prenez le temps de lire : rien n’est mesuré et rien ne s’écoule pendant la démonstration.','');
        return;
      }
      if(phase===PHASE.ARMED){
        overlay.progress(0);
        overlay.note(`À vous, quand vous voulez : ${START[step.id]||'commencez le geste'}. `
          +'La mesure ne démarre qu’à ce moment-là — vous pouvez aussi passer cette étape ou quitter.','');
      }
    }

    /* **L'échéance d'une étape, évaluée sans image.** Elle vit ici et non dans
       `feed()` parce que `feed()` n'est appelée que quand le contrôleur a
       **observé une main** : zéro main devant la caméra, et la seule chose qui
       regardait la montre ne tournait plus. Le motif rendu est le plus
       **utile**, pas le plus littéral : « temps écoulé » est vrai de toutes ces
       pannes et n'aide personne. Rend `true` si l'étape vient de se solder. */
    function expire(){
      /* **L'échéance n'existe que sous `RUNNING`** (architecture §7). Ailleurs
         la coque n'en porte aucune, donc `overlay.expired()` est déjà faux ;
         la garde est écrite quand même, parce qu'une phase sans échéance est
         une **règle** de cette slice et non une conséquence heureuse d'un état
         de la coque. */
      if(phase!==PHASE.RUNNING)return false;
      if(!overlay.expired())return false;
      const step=stepAt(at);
      /* **La visée ne perd pas ce qu'elle a déjà mesuré.** Un utilisateur qui a
         touché un point sur trois a produit un déplacement de clic parfaitement
         exploitable : déclarer l'étape ratée jetterait une mesure réelle et
         ferait retomber sa tolérance clic/glissement sur le défaut d'usine
         alors qu'il a bien cliqué. Les règles de repli ne bougent pas pour
         autant — une visée sans **aucun** clic échoue exactement comme avant,
         et une étape ratée laisse toujours ses clés nulles. */
      if(step&&step.id===BH.STAGE.AIM&&aimHits>0){
        settle(BH.STAGE_STATUS.OK,null,collected.samples.length);
        return true;
      }
      const reason=!collected.samples.length?BH.STAGE_REASON.NO_HAND
        :(step&&step.needs>1&&!secondHandSeen)?BH.STAGE_REASON.NEEDS_TWO_HANDS
        :BH.STAGE_REASON.TIMEOUT;
      settle(BH.STAGE_STATUS.FAILED,reason,collected.samples.length);
      return true;
    }

    /* Les points à viser, en **pixels de la fenêtre** : la coque dessine à
       l'écran. Répartis sur la surface utile (décision 24) ; au-delà des trois
       emplacements publiés, on recommence le tour plutôt que d'inventer des
       positions — trois points déjà espacés couvrent la largeur. */
    function aimField(){
      const view=viewport();
      const width=Number(view&&view.width)||0,height=Number(view&&view.height)||0;
      const count=Math.max(1,Math.round(o.aimTargets));
      const points=[];
      for(let i=0;i<count;i+=1){
        const spot=AIM_SPOTS[i%AIM_SPOTS.length];
        points.push({x:Math.round(width*spot.x),y:Math.round(height*spot.y)});
      }
      return points;
    }

    function advance(){
      at+=1;
      const step=stepAt(at);
      if(!step){conclude();return}
      collected=blank();
      pinchLow=false;repeats=0;pressFrom=null;holdFrom=null;secondHandSeen=false;
      settled=false;aimHits=0;aimIndex=0;ghosts=null;strip=null;aimPoints=null;
      /* **Aucune échéance à l'ouverture** (décision 22). L'étape s'ouvre en
         lecture : `deadlineMs:null`, donc la coque n'affiche pas de compte à
         rebours, et `expired()` ne peut pas être vrai. Elle s'armera dans
         `enterPhase(RUNNING)`, par `overlay.deadline()`, quand l'utilisateur
         aura commencé. */
      overlay.step({index:at+1,total:STEPS.length,title:step.title,
        instruction:step.instruction,deadlineMs:null});
      /* **Monter après `step()`, jamais avant** : `step()` vide la scène comme
         il redessine les boutons. Une démonstration qui survivrait à son étape
         montrerait la main d'une autre consigne — et l'utilisateur ferait le
         geste affiché. */
      const demo=demoNode(doc,step.id);
      if(demo)overlay.mount('demo',demo);
      strip=phaseStrip(doc);
      overlay.mount('feedback',strip.node);
      /* Les cibles existent dès maintenant mais ne sont **posées** qu'à la fin
         de la lecture (`enterPhase(ARMED)`), fantômes compris. */
      aimAt=null;overlay.target(null);
      if(step.target){
        aimPoints=aimField();
        ghosts=ghostField(doc,aimPoints);
        overlay.mount('exercise',ghosts.node);
      }
      /* Sortir, et **passer**. Une étape qu'on ne peut pas réussir sans pouvoir
         la passer est un cul-de-sac : la décision 31 existe précisément pour
         que le parcours survive à une étape ratée. Les deux sont là dès la
         lecture : une sortie qui n'apparaîtrait qu'une fois l'exercice armé
         manquerait justement au moment où l'utilisateur se demande dans quoi il
         vient d'entrer. */
      overlay.buttons([
        {id:'skip',label:'Passer cette étape',run:()=>settle(BH.STAGE_STATUS.SKIPPED,null,collected.samples.length)},
        {id:'exit',label:'Quitter',run:()=>cancel('bouton')},
      ]);
      enterPhase(PHASE.INTRO);
      /* **Après la phase**, pour que la phrase du verdict précédent couvre la
         phrase de lecture et non l'inverse : ce que l'utilisateur veut savoir
         en premier, c'est pourquoi l'étape qu'il vient de faire a échoué. Tenue
         puis rendue à la lecture. */
      if(carry){overlay.note(carry.text,carry.kind,o.resultMs);carry=null}
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
      /* Plus d'étape, donc plus de phase : le récapitulatif n'est pas un
         exercice et ne s'arme pas. Les nœuds montés partent avec le `step()`
         ci-dessous ; les références locales les lâchent ici pour qu'un arbre
         d'étape ne survive pas au parcours. */
      phase=null;strip=null;ghosts=null;aimPoints=null;
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
      /* Tout ce que l'étape tenait est lâché : une phase qui survivrait au
         parcours ferait repartir le suivant au milieu d'une mesure, et un
         bandeau retenu ici garderait en vie l'arbre d'un parcours terminé (une
         fuite qu'aucun écran ne montre). Même raison que la table des régions
         que la coque vide dans `close()`. */
      phase=null;phaseAt=0;engageRun=0;settled=false;
      aimPoints=null;aimIndex=0;aimHits=0;ghosts=null;strip=null;carry=null;
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
      /* **La phase de l'étape courante**, lue de l'extérieur. Publiée parce que
         « l'étape est ouverte » et « l'étape mesure » sont devenus deux faits
         différents : sans cette porte, un test — ou un appelant — ne pourrait
         les distinguer qu'en devinant, et c'est exactement la confusion que
         cette slice corrige. `null` hors étape (récapitulatif, parcours
         fermé). */
      phase(){return stepAt(at)?phase:null},
      /* Ce que l'étape de visée demande encore : combien de points, combien de
         touchés. Lu de l'extérieur pour la même raison. */
      aim(){return aimPoints?{points:aimPoints.length,hits:aimHits,at:aimIndex}:null},
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
        /* La feuille des exercices, posée **après** celle de la coque : elle
           habille ce que le parcours monte dans la scène, donc elle vient
           après ce qui habille la scène. Posée ici et non à la construction :
           une calibration qu'on n'a jamais lancée n'a rien à styler
           (décision 27 — rien ne tourne tant que l'utilisateur ne l'a pas
           demandé). */
        ensureStepsStyle(doc);
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
        /* **C'est le chien de garde qui fait finir la lecture**, et c'est pour
           cela qu'il doit rester plus rapide qu'elle (paire dangereuse n° 17).
           Une étape que personne ne nourrit — mains sur les genoux, ce qui est
           exactement la posture qu'on attend pendant qu'on lit — ne reçoit
           aucune image, donc rien d'autre ne regarderait la montre. */
        if(phase===PHASE.INTRO){
          if(now()-phaseAt>=o.introMs)enterPhase(PHASE.ARMED);else paintPhase();
          return this.stepId();
        }
        /* **Rien ne descend.** L'étape reste armée aussi longtemps que
           l'utilisateur reste inactif : pas d'échéance, pas d'échec, la
           consigne et les sorties restent à l'écran. C'est la correction
           demandée, et c'est aussi pourquoi `expire()` n'est pas atteint
           d'ici. */
        if(phase===PHASE.ARMED){paintPhase();return this.stepId()}
        /* Le verdict est tenu, puis on avance — y compris si plus aucune image
           n'arrive, ce qui est le cas normal après une étape réussie (on
           repose les mains). */
        if(phase===PHASE.RESULT){
          if(now()-phaseAt>=o.resultMs)advance();
          return this.stepId();
        }
        if(expire())return this.stepId();
        /* RÈGLE ZÉRO : sans cette phrase, une étape sans la moindre image
           laisse l'écran muet pendant vingt secondes — et « la caméra ne me
           voit pas » ne se distingue pas de « le parcours est planté ». Elle
           ne peut pas recouvrir un compte de pincements ni une barre de
           maintien : ceux-là n'existent qu'à partir du premier échantillon.
           Elle ne peut pas non plus accuser quelqu'un qui n'a pas commencé :
           on n'arrive ici qu'en mesure. */
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
        /* **Les phases d'abord, et dans l'ordre où elles arrivent.** Une image
           reçue pendant la lecture ou pendant l'attente ne mesure rien : elle
           ne remplit aucun seau, elle ne fait descendre aucune échéance, et le
           seul effet qu'elle peut avoir est de constater que l'utilisateur a
           commencé. C'est la correction de cette slice, écrite là où elle se
           voit. */
        if(phase===PHASE.RESULT){
          if(now()-phaseAt>=o.resultMs)advance();
          return this.stepId();
        }
        if(phase===PHASE.INTRO){
          if(now()-phaseAt<o.introMs){paintPhase();return this.stepId()}
          enterPhase(PHASE.ARMED);
        }
        if(phase===PHASE.ARMED){
          /* Aucune main sûre : l'étape attend, et elle le dit **sans reproche**
             — l'utilisateur n'a rien raté, il n'a pas encore commencé. C'est la
             différence avec la phrase rouge d'une mesure en cours. */
          if(!hands.length){paintPhase();return this.stepId()}
          const test=ENGAGE[step.id];
          const qualifies=!!test&&!!test(hands[0],band,hands);
          /* Consécutives, sinon rien : un repère bruité seul ne peut pas armer
             une étape. Le compteur retombe à zéro à la première image qui ne
             qualifie pas, donc un mouvement de passage devant l'objectif
             n'accumule pas. */
          engageRun=qualifies?engageRun+1:0;
          if(engageRun<o.engageFrames){paintPhase();return this.stepId()}
          enterPhase(PHASE.RUNNING);
          /* Ce que l'image d'armement **laisse** à la mesure : pour un
             pincement, le fait que le canal est déjà fermé, sinon l'écran
             demanderait une répétition de plus qu'il n'en annonce. */
          if(step.id===BH.STAGE.PINCH_PRIMARY||step.id===BH.STAGE.PINCH_SECONDARY)pinchLow=true;
          /* **L'image qui arme n'est pas mesurée**, et c'est voulu. « La mesure
             commence quand l'utilisateur a commencé » devient alors
             littéralement vrai : le seau part vide, et une étape qui s'arme
             puis perd ses mains pour de bon expire sur `NO_HAND` — le motif qui
             dit « montrez vos mains à la caméra », c'est-à-dire le seul conseil
             utile dans ce cas. Consommer cette image-là le rendrait
             **injoignable**, et l'écran dirait « temps écoulé » à quelqu'un que
             la caméra ne voit plus. Une image de moins à 30 images par seconde
             ne coûte rien à aucune dérivation. */
          return this.stepId();
        }
        if(hands.length>=2)secondHandSeen=true;
        /* L'échéance ensuite : une étape expirée ne doit pas pouvoir avaler
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
            /* **Un point touché n'est pas l'étape finie** (décision 24). La
               visée enseigne « viser et cliquer » : un seul point toujours au
               même endroit enseignerait « pincer ». Le point suivant s'allume,
               le précédent passe en trait plein, et le vert dit « celui-là est
               pris » — brièvement, comme partout ailleurs. */
            if(step.id===BH.STAGE.AIM&&aimPoints&&aimHits+1<aimPoints.length){
              aimHits+=1;aimIndex=aimHits;
              if(ghosts)ghosts.set(aimIndex,aimHits);
              overlay.target(aimPoints[aimIndex]);
              overlay.flash(420);
              overlay.progress(aimHits/aimPoints.length);
              overlay.note(`Point ${aimHits} sur ${aimPoints.length}. Visez le suivant.`,'ok',600);
              return this.stepId();
            }
            if(step.id===BH.STAGE.AIM)aimHits+=1;
            settle(BH.STAGE_STATUS.OK,null,collected.samples.length);
            return this.stepId();
          }
          const done=step.id===BH.STAGE.AIM&&aimPoints
            ?(aimHits+(pressFrom?.5:0))/aimPoints.length:(pressFrom?.6:.2);
          overlay.progress(done);
          overlay.note(pressFrom?'Relâchez quand vous êtes prêt.'
            :step.id===BH.STAGE.AIM
              ?`Amenez le jeton sur le point${aimPoints&&aimPoints.length>1?` (${aimHits+1} sur ${aimPoints.length})`:''}, puis pincez.`
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
    DEFAULTS,options,STEPS,FLOW_STATUS,FLOW_SLOTS,FLOW_MOUNTABLE,FLASH_MAX_MS,
    PHASE,PHASE_ORDER,PHASE_STRIP,DEMO,AIM_SPOTS,
    quantile,median,stdev,
    deriveJitter,deriveHysteresis,deriveTravelSlop,deriveReach,checkCPose,wakeBandOf,
    createFlowOverlay,createCalibration,STYLE,STYLE_ID,STEPS_STYLE,STEPS_STYLE_ID,
  });
  root.JarvisBarehandsCalibration=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
