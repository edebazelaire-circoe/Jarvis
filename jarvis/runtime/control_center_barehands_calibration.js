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
  /* Le contrat **étendu** du § 12 (`control_center_barehands_adaptive.js`,
     inséré juste après le contrat) : tous les noms du contrat, plus la
     calibration adaptative et le banc. Sous node, le module voisin. */
  const BH=root.JarvisBarehandsAdaptive
    ||(root.JarvisBarehandsContracts&&typeof require==='function'
      ?require('./control_center_barehands_adaptive.js'):null);
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
    /* La tenue de la **phrase** du verdict et du vert qui l'accompagne quand
       l'exercice se solde. **Elle ne fait plus avancer le parcours** (Slice 07
       adaptative, décision 56) : après la mesure vient la revue, qui attend
       une décision de l'utilisateur. Bornée des deux côtés comme avant : zéro
       milliseconde n'a rien montré, au-delà de l'échéance le vert deviendrait
       ambiant. */
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
    /* Rayon, en pixels de la fenêtre, dans lequel le jeton doit être posé au
       moment du pincement pour que le point compte (25/09/2026 : un pincement
       n'importe où soldait le point, et l'étape n'enseignait plus « viser »).
       Le point dessiné fait 24 px ; la marge absorbe le tremblement du
       jeton. */
    aimHitPx:40,
    /* Slice 05 adaptative (décision 49) : dans l'exercice de sélection, une
       manche se passe après autant de pincements ratés (mauvaise étoile ou
       vide). Sans elle, une assistance mal réglée enfermerait l'utilisateur
       dans une manche qu'il ne peut pas réussir — c'est précisément ce que
       l'exercice doit **mesurer**, pas subir. */
    selectionAttemptsMax:3,
    // Durée de maintien demandée dans une étape de pose (repos, C).
    stageHoldMs:2500,
    // Échantillons minimaux pour qu'une mesure compte comme une mesure.
    stageMinSamples:20,
    // Répétitions demandées dans les étapes de pincement.
    pinchRepeats:4,
    /* **Épisodes de pincement** (tâche adaptative, Slice 02, décision 43). Les
       seuils se dérivent d'épisodes complets, un geste = une voix : il en faut
       au moins ce nombre. Trois, parce qu'une médiane de trois écarte un
       geste aberrant et qu'une médiane de deux n'est qu'une moyenne. L'étape
       redemande un pincement tant qu'il en manque, sous son échéance. */
    pinchEpisodesMin:3,
    /* Le temps tenu **après** la dernière répétition comptée avant de
       dériver : la répétition se compte au passage du relâchement d'usine,
       avant que la main soit revenue à sa ligne de base ouverte. Sans cette
       queue, le dernier pincement serait toujours incomplet. */
    pinchSettleMs:300,
    /* Les bords des phases, en fraction de la profondeur de l'épisode : la
       fermeture commence quand le rapport quitte les 10 % du haut, le minimum
       quand il entre dans les 10 % du bas — la convention 10-90 % d'un temps
       de montée. Sous 0,5, les deux bords ne peuvent pas se croiser. */
    episodeEdge:.1,
    /* Trou maximal entre deux images lisibles à l'intérieur d'un épisode. Au
       delà, l'épisode est coupé et refusé (`EPISODE_REJECT.GAP`) : quatre
       images perdues à 30 images/s, pas une main sortie du cadre. */
    episodeGapMs:150,
    /* Fenêtre où se lit la ligne de base ouverte de part et d'autre d'un
       épisode (médiane des images du haut de la bande). */
    episodeBaselineMs:200,
    /* Marge sous `wakeGapMin` que le seuil de relâchement primaire dérivé ne
       franchit pas : un pincement en cours ne doit jamais se lire comme la
       posture de réveil (ancre `TRIAL_ANCHORS.wakeGapMin` du contrat). */
    wakeClearancePalms:.02,
    /* Écart minimal entre l'appui et le relâchement dérivés. 0,05 paume, soit
       ~4,5 mm sur une paume de 9 cm : plus du double du tremblement d'un bout
       de doigt tenu pincé (~2 mm), et de l'ordre de l'écart qui sépare déjà
       deux canaux (`pinchMarginRatio` 0,12 → 0,06 exigé). Sous lui, le
       plafond de réveil laissait 0,018 d'hystérésis à un utilisateur ordinaire
       (appui 0,422, relâchement 0,44) : un contact qui clignote. */
    hysteresisMinPalms:.05,
    /* Part des épisodes mesurés qui doit atteindre l'appui dérivé ; sous
       elle, l'étape avertit (`EPISODE_WARNING.PRESS_OUT_OF_REACH`) : un geste
       sur dix qui ne clique pas se remarque. */
    pressReachMin:.9,
    /* Ce que l'étape garde des images d'**avant** l'armement : assez pour la
       ligne de base ouverte (`episodeBaselineMs`) et une fermeture lente. Le
       pincement qui arme l'étape devient ainsi un épisode complet au lieu
       d'être toujours refusé comme tronqué. */
    pinchLookbackMs:1500,
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
    /* Bornes de la tolérance dérivée, en fraction de la largeur d'image. Le
       plafond valait 0,15 (288 px de clic toléré en 1920, donc 624 px avant
       qu'un pincement devienne un glissement) : une mesure ratée passait, et
       plus rien ne se déplaçait à mains nues sans message (21/09/2026 : une
       calibration à 0,124 armait le glissement au-delà de 515 px). 0,014 vaut
       ~27 px en 1920, la zone sensible d'une étoile (`POINT_HIT_PX`, 26) : un
       « clic » qui parcourt plus que sa cible en est sorti, ce n'est plus un
       clic. Même valeur dans le contrat du profil et dans
       `barehands_profile.py` (tests de parité). */
    travelSlopMin:.002,
    travelSlopMax:.014,
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
    /* **Exemples négatifs** (tâche adaptative, Slice 03, décision 47). Ce qui
       s'y compte est **faux par construction** — un appui, un réveil, une
       cible, un curseur —, et un taux se mesure par minute d'**exposition** :
       le temps où une main sûre était devant la caméra, pas le temps écoulé.
       Huit secondes de mouvement ordinaire : assez pour voir passer des
       gestes de conversation, assez court pour ne pas lasser. */
    negativeMs:8000,
    /* Exposition en dessous de laquelle une échéance ne rend rien : trois
       secondes de mains devant la caméra font encore un taux lisible. */
    negativeMinMs:3000,
    /* Trou maximal entre deux images comptées dans l'exposition : au-delà,
       la main était partie, ce temps-là n'expose à rien. */
    negativeGapMs:250,
    /* Temps posé sur un point, **sans pincer**, pour que le temps « viser sans
       cliquer » le compte. */
    negativeDwellMs:600,
    /* **Tenir puis relâcher** (Slice 07 adaptative, décision 56). Un pincement
       compte comme « tenu » quand sa phase fermée (le minimum de l'épisode)
       dure au moins ceci : assez pour qu'un relâchement prématuré du
       détecteur ait le temps d'arriver, assez court pour ne pas fatiguer. */
    holdPinchMs:800,
    // Pincements tenus demandés.
    holdRepeats:3,
    /* **Déposer** (6C) : écart maximal, en pixels de la fenêtre et par axe,
       entre le centre de la fenêtre relâchée et celui de la destination. Un
       peu moins que la moitié d'un bouton de barre : « dedans » à l'œil. */
    dropTolerancePx:48,
    // Lâchers avant la destination au-delà desquels 6C se solde.
    dropAttemptsMax:3,
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
       pincement à la première image (`repeats>=0` est déjà vrai), avant
       qu'un seul épisode ait pu se former : la dérivation manquerait
       d'épisodes pour tout le monde, et l'écran le dirait comme si
       l'utilisateur pinçait mal. À zéro,
       `progress(repeats/0)` vaut en plus `NaN`, donc la barre ne dit même plus
       où on en est. Même espèce que `stageMinSamples>=1` juste au-dessus. */
    if(!(o.pinchRepeats>=1))
      throw new RangeError('pinchRepeats doit valoir au moins 1 : en dessous, l’étape de pincement se solde à la première image, la dérivation n’a qu’un échantillon et les deux étapes de pincement échouent pour tout le monde — un défaut d’usine qui se lit « votre pincement n’est pas mesurable »');
    /* Les réglages des épisodes (Slice 02 adaptative). Chacun, hors de sa
       plage, fait échouer **toutes** les étapes de pincement de la même façon
       silencieuse que les paires ci-dessus. */
    if(!(Number.isInteger(o.pinchEpisodesMin)&&o.pinchEpisodesMin>=1))
      throw new RangeError('pinchEpisodesMin doit être un entier d’au moins 1 : à zéro, une étape sans un seul pincement complet dériverait des seuils tirés de rien');
    if(!(o.pinchSettleMs>=0&&o.pinchSettleMs<o.stageTimeoutMs))
      throw new RangeError('pinchSettleMs doit rester dans [0,stageTimeoutMs[ : au-delà, l’étape expire pendant qu’elle attend que la main se rouvre');
    if(!(o.episodeEdge>0&&o.episodeEdge<.5))
      throw new RangeError('episodeEdge doit rester dans ]0,0.5[ : à 0,5 ou plus, le bord du minimum passe au-dessus du bord de la fermeture et aucune phase ne se découpe');
    if(!(o.episodeGapMs>0))
      throw new RangeError('episodeGapMs doit être strictement positif : à zéro, chaque image serait un trou et aucun épisode ne serait jamais complet');
    if(!(o.episodeBaselineMs>0))
      throw new RangeError('episodeBaselineMs doit être strictement positif : la ligne de base ouverte se lit sur une fenêtre, pas sur un instant');
    if(!(o.hysteresisMinPalms>0&&o.hysteresisMinPalms<o.separationMinPalms))
      throw new RangeError('hysteresisMinPalms doit rester dans ]0,separationMinPalms[ : à zéro l’appui peut toucher le relâchement et le contact clignote, au-delà aucune bande mesurable ne loge l’hystérésis');
    if(!(o.pressReachMin>0&&o.pressReachMin<=1))
      throw new RangeError('pressReachMin doit rester dans ]0,1] : c’est une part des pincements mesurés, et à zéro l’avertissement ne dirait jamais rien');
    if(!(o.pinchLookbackMs>o.episodeBaselineMs))
      throw new RangeError('pinchLookbackMs doit dépasser episodeBaselineMs : sinon la ligne de base ouverte du pincement qui arme l’étape n’est jamais vue, et ce pincement est toujours refusé');
    if(!(o.wakeClearancePalms>=0&&o.wakeClearancePalms<o.separationMinPalms))
      throw new RangeError('wakeClearancePalms doit rester dans [0,separationMinPalms[ : au-delà, la marge sous la posture de réveil mange la bande que le pincement doit séparer');
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
    if(!(o.aimHitPx>0))
      throw new RangeError('aimHitPx doit être strictement positif : à zéro aucun pincement ne touche jamais le point, et l’étape de visée expire pour tout le monde');
    if(!(Number.isInteger(o.selectionAttemptsMax)&&o.selectionAttemptsMax>=1))
      throw new RangeError('selectionAttemptsMax doit être un entier ≥ 1 : à zéro, chaque manche de sélection se passerait avant le premier pincement');
    if(!(o.aimTargets>=1))
      throw new RangeError('aimTargets doit valoir au moins 1 : à zéro l’étape de visée se solde sans aucun clic mesuré, et la tolérance clic/glissement de tout le monde retombe sur le défaut d’usine');
    /* **Paire dangereuse n° 19** (Slice 03 adaptative). Le minimum
       d'exposition que l'échéance rend doit s'atteindre **avant** elle, sinon
       « bouger sans cliquer » échoue pour tout le monde ; il ne peut pas
       dépasser ce qu'on exige, ni être nul (un taux sur zéro seconde n'est pas
       un taux). `negativeMs` au-delà de l'échéance reste permis : l'exercice
       se solde alors à l'échéance sur ce qu'il a exposé. */
    if(!(o.negativeMs>0))
      throw new RangeError('negativeMs doit être strictement positif : l’exercice « bouger sans cliquer » se solde sur une durée d’exposition');
    if(!(o.negativeMinMs>0&&o.negativeMinMs<=o.negativeMs&&o.negativeMinMs<o.stageTimeoutMs))
      throw new RangeError('negativeMinMs doit rester dans ]0,negativeMs] et sous stageTimeoutMs : un taux par minute se calcule sur une exposition non nulle, et un minimum inatteignable avant l’échéance ferait échouer l’exercice pour tout le monde');
    if(!(o.negativeGapMs>0))
      throw new RangeError('negativeGapMs doit être strictement positif : à zéro aucune image ne compte dans l’exposition et l’exercice n’aboutit jamais');
    if(!(o.negativeDwellMs>0&&o.negativeDwellMs<o.stageTimeoutMs))
      throw new RangeError('negativeDwellMs doit rester dans ]0,stageTimeoutMs[ : le temps posé sur un point doit pouvoir s’atteindre avant l’échéance');
    /* **Paire dangereuse n° 20** (Slice 07 adaptative). Un maintien exigé
       au-delà de l'échéance ne s'atteint jamais : l'exercice « tenir puis
       relâcher » échouerait pour tout le monde. */
    if(!(o.holdPinchMs>0&&o.holdPinchMs<o.stageTimeoutMs))
      throw new RangeError('holdPinchMs doit rester dans ]0,stageTimeoutMs[ : un maintien plus long que l’échéance ne s’atteint jamais, et « tenir puis relâcher » échouerait pour tout le monde');
    if(!(Number.isInteger(o.holdRepeats)&&o.holdRepeats>=1))
      throw new RangeError('holdRepeats doit être un entier ≥ 1 : à zéro l’exercice se solderait sans un seul pincement tenu');
    if(!(o.dropTolerancePx>0))
      throw new RangeError('dropTolerancePx doit être strictement positif : à zéro aucun dépôt n’atteint jamais la destination');
    if(!(Number.isInteger(o.dropAttemptsMax)&&o.dropAttemptsMax>=1))
      throw new RangeError('dropAttemptsMax doit être un entier ≥ 1 : à zéro, le dépôt se solderait avant le premier lâcher');
    return Object.freeze(o);
  }

  /* ------------------------------------------------------------------ 2
     Statistiques. Rien de plus qu'il n'en faut (décision 29).

     Les quantiles, pas la moyenne : une main qui sort du cadre une image sur
     vingt produit des valeurs aberrantes, et une moyenne les porte. */
  const finite=list=>list.filter(value=>Number.isFinite(value));
  /* **Le quantile linéaire du contrat** (`JarvisBarehandsContracts.quantile`),
     le même que le rejeu et le jeu de mesures : deux définitions de « p95 »
     dans un dépôt rendent deux nombres sous un seul mot. La copie locale
     d'avant **bornait** `q` à [0,1] en silence ; celle du contrat ne le fait
     pas. Toutes les lectures d'ici passent des constantes dans [0,1], donc un
     `q` hors bornes est une erreur de programmation : il se refuse au lieu
     d'être rabattu. */
  function quantile(list,q){
    if(!(q>=0&&q<=1))throw new RangeError(`quantile : q attendu dans [0,1], reçu ${q}`);
    return BH.quantile(list,q);
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

  /* ------------------------------------------------------------------ 3 bis
     **Épisodes de pincement** (tâche adaptative, Slice 02, décisions 35 et 43).

     Le quantile sur toutes les images qu'utilisait cette étape pesait chaque
     geste au nombre d'images qu'il durait : un pincement tenu deux secondes
     comptait vingt fois un clic vif de 80 ms, et un utilisateur qui clique vite
     devait exagérer ses pincements pour être mesuré. Ici un pincement est
     découpé en phases (`EPISODE_PHASE_SEQUENCE`), et **un geste vaut une
     voix**.

     Des fonctions pures, et une règle qui les traverse : **ce qui n'a pas
     été vu n'est pas deviné.** Un épisode dont une phase manque est refusé
     sous un code (`EPISODE_REJECT`), jamais complété. */

  const finiteNumber=value=>typeof value==='number'&&Number.isFinite(value)?value:null;
  /* L'instant où le segment `a → b` franchit `threshold`, interpolé
     linéairement : à 30 images/s, un bord de phase pris sur la grille des
     images se tromperait de 33 ms, soit toute la latence qu'on veut mesurer. */
  const crossing=(a,b,threshold)=>{
    if(a.r===b.r)return a.t;
    const f=Math.min(Math.max((a.r-threshold)/(a.r-b.r),0),1);
    return a.t+(b.t-a.t)*f;
  };

  /* Les segments lisibles d'un flux : images au rapport fini, de qualité ≥
     `sampleQualityMin`, au temps strictement croissant ; un trou de plus de
     `episodeGapMs` ouvre un nouveau segment. `gapBefore`/`gapAfter` disent si
     le segment est bordé par un trou (images perdues ou douteuses) plutôt que
     par le début ou la fin du flux. */
  function usableSegments(frames,o){
    const segments=[];
    let segment=null,lastT=-Infinity,holeSinceUsable=false;
    for(const frame of frames||[]){
      const t=finiteNumber(frame&&frame.t);
      if(t===null||t<=lastT){holeSinceUsable=true;continue}
      lastT=t;
      const r=finiteNumber(frame.ratio),quality=finiteNumber(frame.quality);
      if(r===null||quality===null||quality<o.sampleQualityMin){holeSinceUsable=true;continue}
      if(!segment||t-segment.points[segment.points.length-1].t>o.episodeGapMs){
        if(segment)segment.gapAfter=true;
        segment={points:[],gapBefore:segment!==null||holeSinceUsable,gapAfter:false};
        segments.push(segment);
      }
      holeSinceUsable=false;
      segment.points.push({t,r});
    }
    if(segment&&holeSinceUsable)segment.gapAfter=true;
    return segments;
  }

  /* **La règle d'un pincement**, une fois pour tout le module : un creux n'en
     est un que si le rapport est descendu d'au moins `depthMin` depuis le
     sommet précédent, et un sommet ne se confirme que par une descente
     d'autant (zigzag). Rend les pivots confirmés, puis l'extrême en cours
     (`pending`). Le segmenteur, l'armement et le compte des répétitions de
     l'étape la lisent tous les trois — aucun seuil d'usine n'y entre. */
  function zigzagPivots(p,depthMin){
    const pivots=[],n=p.length;
    let mode=null,ext=0,hi=0,lo=0;
    for(let i=1;i<n;i+=1){
      const r=p[i].r;
      if(mode===null){
        if(r>p[hi].r)hi=i;
        if(r<p[lo].r)lo=i;
        if(p[hi].r-r>=depthMin){
          pivots.push({kind:'peak',i:hi});mode='down';ext=hi+1;
          for(let k=hi+1;k<=i;k+=1)if(p[k].r<p[ext].r)ext=k;
        }else if(r-p[lo].r>=depthMin){
          pivots.push({kind:'valley',i:lo});mode='up';ext=lo+1;
          for(let k=lo+1;k<=i;k+=1)if(p[k].r>p[ext].r)ext=k;
        }
      }else if(mode==='down'){
        if(r<p[ext].r)ext=i;
        else if(r-p[ext].r>=depthMin){pivots.push({kind:'valley',i:ext});mode='up';ext=i}
      }else{
        if(r>p[ext].r)ext=i;
        else if(p[ext].r-r>=depthMin){pivots.push({kind:'peak',i:ext});mode='down';ext=i}
      }
    }
    if(mode!==null)pivots.push({kind:mode==='down'?'valley':'peak',i:ext,pending:true});
    return pivots;
  }

  /* Le segmenteur. `frames` : un seul flux (une piste, un canal), en ordre de
     temps, `{t, ratio, quality}`. Rend `{episodes, rejected}` : des épisodes
     aux bords interpolés, et les refus codés.

     1. **Images lisibles** (`usableSegments`).
     2. **Pivots** (`zigzagPivots`, profondeur `separationMinPalms`) : le
        bruit du traqueur (quelques centièmes de paume) ne fait jamais un
        épisode, et le seuil est le même que celui qui refuse une calibration
        inséparable.
     3. **Bords.** Ligne de base avant = médiane des images du haut de la bande
        (à moins de `episodeEdge` de la profondeur du sommet) sur les
        `episodeBaselineMs` qui précèdent la fermeture ; idem après. La
        fermeture commence quand le rapport quitte les `episodeEdge` du haut ;
        le minimum commence quand il entre dans les `episodeEdge` du bas — pris
        sur la **plus petite** des deux profondeurs, pour qu'une réouverture
        partielle ne place pas ce bord au-dessus d'elle — et finit quand il en
        sort ; l'épisode finit quand le rapport rentre dans les `episodeEdge`
        du haut. Les seuils suivent chaque épisode : ils ne dépendent ni des
        seuils d'usine ni de ceux qu'on dérive, sans quoi la mesure changerait
        avec le réglage qu'elle doit juger. */
  function segmentPinchEpisodes(frames,o){
    const edge=o.episodeEdge;
    const episodes=[],rejected=[];
    for(const seg of usableSegments(frames,o)){
      const p=seg.points,n=p.length;
      const reject=(code,t)=>rejected.push({code,t});
      const startCode=seg.gapBefore?BH.EPISODE_REJECT.GAP:BH.EPISODE_REJECT.NO_OPEN_BEFORE;
      const endCode=seg.gapAfter?BH.EPISODE_REJECT.GAP:BH.EPISODE_REJECT.NO_REOPEN;
      const pivots=zigzagPivots(p,o.separationMinPalms);
      pivots.forEach((pivot,k)=>{
        if(pivot.kind!=='valley')return;
        const V=pivot.i,min=p[V].r;
        if(pivot.pending){reject(endCode,p[V].t);return}
        const before=pivots[k-1],after=pivots[k+1];
        if(!before){reject(startCode,p[V].t);return}
        const P1=before.i,P2=after.i;
        const lowBound=k>=2?pivots[k-2].i:-1;
        const highBound=pivots[k+2]?pivots[k+2].i:n;
        /* Ligne de base avant : les images du haut de la bande, sur la fenêtre
           qui précède la fermeture. */
        const bandL=p[P1].r-edge*(p[P1].r-min);
        let j=V-1;
        while(j>P1&&p[j].r<bandL)j-=1;
        const tops=[];
        for(let i=j;i>lowBound&&p[i].t>=p[j].t-o.episodeBaselineMs;i-=1)if(p[i].r>=bandL)tops.push(p[i].r);
        const baselineBefore=median(tops);
        const closeThr=baselineBefore-edge*(baselineBefore-min);
        j=V-1;
        while(p[j].r<closeThr)j-=1;
        /* Une seule image au-dessus du bord, et c'est la première du flux :
           rien ne dit qu'elle était une main ouverte plutôt qu'une fermeture
           déjà commencée. */
        if(j===0){reject(startCode,p[V].t);return}
        const bandR=p[P2].r-edge*(p[P2].r-min);
        let e=V+1;
        while(e<P2&&p[e].r<bandR)e+=1;
        const opens=[];
        for(let i=e;i<highBound&&p[i].t<=p[e].t+o.episodeBaselineMs;i+=1)if(p[i].r>=bandR)opens.push(p[i].r);
        const baselineAfter=median(opens);
        const openThr=baselineAfter-edge*(baselineAfter-min);
        e=V+1;
        while(p[e].r<openThr)e+=1;
        /* Symétrique : la dernière image du flux est la première revenue en
           haut — rien ne dit que la main a fini de se rouvrir. */
        if(e===n-1){reject(endCode,p[V].t);return}
        const minThr=min+edge*Math.min(baselineBefore-min,baselineAfter-min);
        let m=j+1;
        while(p[m].r>minThr)m+=1;
        let q=e-1;
        while(p[q].r>minThr)q-=1;
        episodes.push({
          startT:crossing(p[j],p[j+1],closeThr),
          minimumT:crossing(p[m-1],p[m],minThr),
          openingT:crossing(p[q],p[q+1],minThr),
          endT:crossing(p[e-1],p[e],openThr),
          baselineBefore,baselineAfter,minRatio:min,closeThr,minThr,openThr,
        });
      });
    }
    return {episodes,rejected};
  }

  /* **Le vrai détecteur, rejoué** — jamais une copie. `makeDetector()` rend un
     canal neuf du moteur (`createPinchChannel`, avec les options que le
     moteur applique à cette main) ; on lui passe les images dans l'ordre, avec
     la confiance, la qualité et le rapport 3D que le moteur a vus, et on
     relève ses `down` et ses `up`. Même purge que le moteur
     (`createPinchIntentEngine`) : une main absente plus de `lostGraceMs`
     annule son contact et repart d'un canal neuf. Rend `[{down, up}]`,
     `up: null` pour un contact annulé ou jamais relâché.

     **La clé du moteur se suit image par image** (Slice 04 adaptative).
     `makeDetector(clé)` rend un canal neuf pour cette clé ; la clé est la
     latéralité que le moteur a résolue pour la piste **à cette image**
     (`pinchHandedness`). Quand elle change en cours de piste, le moteur
     reconfigure son canal (`configure(forHand(...))`) — **seulement une fois
     le contact relâché** (un changement de seuils sous un doigt pincé
     relâchait le contact) : le rejeu fait de même, avec les options d'un
     canal neuf de la nouvelle clé (`options()`), et n'en change pas tant que
     son canal n'est pas ouvert. La clé enregistrée est celle que le moteur a
     **appliquée**, donc les deux règles coïncident. */
  function replayPinchContacts(stream,channel,makeDetector,lostGraceMs){
    const keyOf=sample=>BH.HANDEDNESSES.includes(sample.pinchHandedness)
      ?sample.pinchHandedness:BH.HANDEDNESS.UNKNOWN;
    let key=null;
    const own=channel===BH.PINCH_CHANNEL.SECONDARY?'secondary':'primary';
    const other=own==='primary'?'secondary':'primary';
    const contacts=[];
    let detector=null,down=null,seenAt=null;
    for(const sample of stream){
      const t=finiteNumber(sample.t);
      if(t===null)continue;
      const ratio=finiteNumber(sample[`${own}Ratio`]),otherRatio=finiteNumber(sample[`${other}Ratio`]);
      // Le moteur saute une main dont aucun canal ne se lit.
      if(ratio===null&&otherRatio===null)continue;
      if(detector===null||t-seenAt>lostGraceMs){
        if(down!==null){contacts.push({down,up:null});down=null}
        key=keyOf(sample);
        detector=makeDetector(key);
      }else if(keyOf(sample)!==key&&!(typeof detector.state==='function'&&detector.state()!=='open')){
        key=keyOf(sample);
        const fresh=makeDetector(key);
        if(typeof detector.configure==='function'&&fresh&&typeof fresh.options==='function')
          detector.configure(fresh.options());
        else detector=fresh;
      }
      seenAt=t;
      // Ce canal-ci ne se lit pas : le moteur ne lui donne rien.
      if(ratio===null)continue;
      for(const event of detector.update({handTrackId:sample.handTrackId,ratio,other:otherRatio,
        confidence:sample[`${own}Confidence`],worldRatio:sample[`${own}WorldRatio`],
        quality:sample.quality,stillness:sample.stillness,now:t,
        x:Number(sample.filteredX),y:Number(sample.filteredY),
        palmX:Number(sample.palmX),palmY:Number(sample.palmY),
        anchorX:Number(sample.pointerX),anchorY:Number(sample.pointerY)})){
        if(event.phase===BH.PINCH_PHASE.DOWN)down=event.t;
        else if(down!==null&&(event.phase===BH.PINCH_PHASE.UP||event.phase===BH.PINCH_PHASE.CANCEL)){
          /* `end` : l'instant où le contact a fini, relâché **ou** annulé —
             ce qu'un relâchement prématuré se lit contre (Slice 07). */
          contacts.push({down,up:event.phase===BH.PINCH_PHASE.UP?event.t:null,end:event.t});down=null;
        }
      }
    }
    if(down!==null)contacts.push({down,up:null});
    return contacts;
  }

  /* Les flux d'une étape, un par piste (à défaut d'identité, par
     latéralité) : deux mains ne forment pas un pincement. */
  function tracksOf(samples){
    const tracks=new Map();
    for(const sample of samples||[]){
      const key=sample.handTrackId!==undefined&&sample.handTrackId!==null
        ?`id:${sample.handTrackId}`:`hand:${sample.handedness}`;
      if(!tracks.has(key))tracks.set(key,[]);
      tracks.get(key).push(sample);
    }
    return [...tracks.values()];
  }
  const framesOf=(stream,channel)=>{
    const own=channel===BH.PINCH_CHANNEL.SECONDARY?'secondary':'primary';
    return stream.map(sample=>({t:sample.t,ratio:sample[`${own}Ratio`],quality:sample.quality}));
  };
  /* **Le compte des répétitions de l'étape** : les épisodes complets que le
     segmenteur trouve déjà, toutes pistes confondues. C'est la même règle que
     la dérivation, donc « 4 pincements demandés » veut dire quatre épisodes
     mesurables — et une main dont le repos passe sous le relâchement d'usine
     (ouverte à 0,38) compte ses pincements comme les autres. */
  const countPinchEpisodes=(samples,channel,o)=>tracksOf(samples)
    .reduce((sum,stream)=>sum+segmentPinchEpisodes(framesOf(stream,channel),o).episodes.length,0);
  /* Les épisodes **tenus** (Slice 07 adaptative) : même segmenteur, phase
     fermée d'au moins `holdPinchMs`. Rend `{held, all}` — l'écart dit à
     l'utilisateur qu'il a relâché trop tôt. */
  const countHeldEpisodes=(samples,channel,o)=>tracksOf(samples).reduce((sum,stream)=>{
    const list=segmentPinchEpisodes(framesOf(stream,channel),o).episodes;
    const last=list.length?list[list.length-1]:null;
    const lastAt=last?last.startT:-Infinity;
    return {held:sum.held+list.filter(ep=>ep.openingT-ep.minimumT>=o.holdPinchMs).length,all:sum.all+list.length,
      /* Le dernier geste (toutes pistes) a-t-il été relâché trop tôt ? */
      lastShort:lastAt>=sum.lastAt?!!last&&last.openingT-last.minimumT<o.holdPinchMs:sum.lastShort,
      lastAt:Math.max(lastAt,sum.lastAt)};
  },{held:0,all:0,lastShort:false,lastAt:-Infinity});
  /* **L'armement de l'étape** : le canal s'est fermé d'au moins
     `separationMinPalms` depuis un sommet (un pivot confirmé), sur n'importe
     quelle piste. Même règle que le segmenteur — ni une main au repos sous le
     relâchement d'usine, ni un tremblement n'arment rien. */
  /* Seul un sommet **confirmé** compte : `zigzagPivots` ajoute en fin de liste
     l'extrême en cours (`pending`), et après une main qui s'ouvre c'est un
     « sommet » que rien n'a encore confirmé. Le compter armait l'étape sur
     une main qui **s'ouvre** — un pincement tenu pendant la lecture, puis
     rouvert, lançait la mesure sans aucun pincement. */
  const pinchEngaged=(samples,channel,o)=>tracksOf(samples).some(stream=>
    usableSegments(framesOf(stream,channel),o).some(seg=>
      zigzagPivots(seg.points,o.separationMinPalms).some(pivot=>pivot.kind==='peak'&&!pivot.pending)));
  /* **Un pincement trop timide** : le canal a bougé d'au moins la moitié de
     `separationMinPalms` sur la fenêtre récente, mais moins que lui.
     Ce n'est pas un repos (le tremblement d'un doigt reste à quelques
     centièmes) : c'est quelqu'un qui essaie. L'étape le lui dit, et finit par
     le refuser comme inséparable plutôt que d'attendre sans fin. Rend
     l'étendue parcourue, ou `null` sous ce seuil. */
  const pinchShallow=(samples,channel,o)=>{
    const ratios=[];
    for(const stream of tracksOf(samples))
      for(const seg of usableSegments(framesOf(stream,channel),o))for(const point of seg.points)ratios.push(point.r);
    if(!ratios.length)return null;
    const span=Math.max(...ratios)-Math.min(...ratios);
    /* Au-delà de `separationMinPalms`, ce n'est plus un essai timide : c'est
       une main qui s'ouvre ou se ferme franchement, et elle arme (ou
       armera) sur un sommet confirmé. */
    return span>=o.separationMinPalms/2&&span<o.separationMinPalms?span:null;
  };

  /* Les épisodes d'une étape de pincement, prêts pour la séance : segmentés
     par piste, chronométrés contre le vrai détecteur, validés par
     `createPinchEpisode`. `samples` : les enregistrements de scalaires de
     l'étape (toutes mains) ; `ctx` : `{options, detector(handedness),
     lostGraceMs, stage, exerciseRef, trialRef, nextRef()}`.

     **Les latences** (décision 35) : appui = premier `down` du détecteur entre
     le début et la fin de l'épisode − début du minimum ; relâchement = son `up` − début de la
     réouverture, s'il arrive avant l'épisode suivant. `null` = jamais tranché
     (appui manqué, ou relâchement collé ; sans appui, rien à relâcher). */
  function measurePinchEpisodes(samples,channel,ctx){
    const o=ctx.options;
    const episodes=[],rejected=[],ratios=[];
    for(const stream of tracksOf(samples)){
      const handedness=BH.HANDEDNESSES.includes(stream[0].handedness)?stream[0].handedness:BH.HANDEDNESS.UNKNOWN;
      const frames=framesOf(stream,channel);
      for(const frame of frames)if(finiteNumber(frame.ratio)!==null&&finiteNumber(frame.quality)!==null
        &&frame.quality>=o.sampleQualityMin)ratios.push(frame.ratio);
      const cut=segmentPinchEpisodes(frames,o);
      rejected.push(...cut.rejected);
      /* **Les options que le moteur a appliquées à cette piste, image par
         image** : la clé qu'il a résolue (`pinchHandedness`, lue par la couture
         de mesure sur `trackHandedness`), pas la latéralité du jeton. Sans
         elle, c'est la clé du moteur quand rien n'est dit : `unknown`. */
      const contacts=replayPinchContacts(stream,channel,key=>ctx.detector(key),ctx.lostGraceMs);
      cut.episodes.forEach((ep,index)=>{
        /* L'appui appartient à l'épisode s'il tombe **dans** l'épisode : un
           contact ouvert avant le début de la fermeture est celui d'un geste
           précédent — typiquement le pincement qui a armé l'étape, que le
           segmenteur a refusé — et le lui prêter inventerait une latence. */
        const until=index+1<cut.episodes.length?cut.episodes[index+1].startT:Infinity;
        const contact=contacts.find(c=>c.down>=ep.startT&&c.down<=ep.endT)||null;
        const up=contact&&contact.up!==null&&contact.up<until?contact.up:null;
        const inside=stream.filter(s=>s.t>=ep.startT&&s.t<=ep.endT);
        const at=inside.filter(s=>finiteNumber(s.palmX)!==null&&finiteNumber(s.palmY)!==null);
        const stillness=median(inside.map(s=>finiteNumber(s.stillness)));
        const quality=median(inside.map(s=>finiteNumber(s.quality)));
        if(!at.length||stillness===null||quality===null){
          rejected.push({code:BH.EPISODE_REJECT.NOT_MEASURED,t:ep.startT});return;
        }
        const travelPx=Math.max(...at.map(s=>Math.hypot(s.palmX-at[0].palmX,s.palmY-at[0].palmY)));
        const closingMs=ep.minimumT-ep.startT,openingMs=ep.endT-ep.openingT;
        const made=BH.checkSchema(BH.createPinchEpisode,{
          schemaVersion:BH.SESSION_SCHEMA_VERSION,kind:'pinch_episode',ref:ctx.nextRef(),
          channel,slot:null,handedness,stage:ctx.stage||null,
          exerciseRef:ctx.exerciseRef||null,trialRef:ctx.trialRef||null,
          startT:ep.startT,endT:ep.endT,closingMs,minimumMs:ep.openingT-ep.minimumT,openingMs,
          baselineBefore:ep.baselineBefore,baselineAfter:ep.baselineAfter,minRatio:ep.minRatio,
          closingVelocity:closingMs>0?(ep.closeThr-ep.minThr)/(closingMs/1000):0,
          openingVelocity:openingMs>0?(ep.openThr-ep.minThr)/(openingMs/1000):0,
          pressLatencyMs:contact?contact.down-ep.minimumT:null,
          releaseLatencyMs:up===null?null:up-ep.openingT,
          travelPx,stillness:Math.min(Math.max(stillness,0),1),quality:Math.min(Math.max(quality,0),1),
          complete:true,
        });
        /* **Relâchement prématuré** (Slice 07 adaptative, exercice « tenir
           puis relâcher ») : le vrai détecteur a lâché le contact **avant**
           que la main commence à se rouvrir, ou l'a repris une seconde fois
           dans le même geste. Lu sur les mêmes contacts rejoués que les
           latences, jamais deviné. */
        const inContact=contacts.filter(c=>c.down>=ep.startT&&c.down<=ep.endT);
        const premature=!!contact&&(inContact.length>1
          ||(Number.isFinite(contact.end)&&contact.end<ep.openingT));
        if(made.ok)episodes.push(Object.freeze({...made.value,pressT:contact?contact.down:null,releaseT:up,
          premature,contacts:inContact.length}));
        else rejected.push({code:made.code,t:ep.startT});
      });
    }
    /* L'étendue parcourue par le canal pendant l'étape, entre les centiles 2
       et 98 : quand trop peu d'épisodes sont vus, elle dit si c'est parce que
       la main n'a jamais séparé ses deux états (refus `NOT_SEPARABLE`) ou
       parce que les gestes étaient coupés (`TOO_FEW_SAMPLES`). */
    const span=ratios.length?quantile(ratios,.98)-quantile(ratios,.02):null;
    return {episodes:episodes.sort((a,b)=>a.startT-b.startT),rejected,span};
  }

  /* **L'ouvert d'un épisode.** Par défaut la plus basse des deux lignes de
     base : la réouverture la moins ample doit encore relâcher. Sauf quand
     elles s'écartent de plus de `episodeEdge` de la profondeur : la plus
     basse est alors une **réouverture partielle** — un double pincement dont
     la main ne s'est pas rouverte entre les deux — et la retenir tirerait
     l'ouvert vers le milieu du geste (0,40 pour une main ouverte à 0,80).
     C'est la plus haute, la vraie main ouverte, qui compte alors. */
  function episodeOpen(ep,o){
    const low=Math.min(ep.baselineBefore,ep.baselineAfter),high=Math.max(ep.baselineBefore,ep.baselineAfter);
    return high-low>o.episodeEdge*(high-ep.minRatio)?high:low;
  }

  /* Les deux seuils d'un canal, dérivés des **épisodes** : un geste vaut une
     voix, quelle que soit sa durée. Fermé = médiane des minima ; ouvert =
     médiane des ouverts d'épisode (`episodeOpen`). Les seuils se posent
     ensuite dans cette bande comme avant (`pressAt`, `releaseAt`).

     `limits.releaseCeiling` (canal primaire : `wakeGapMin` du moteur) : le
     relâchement dérivé reste à `wakeClearancePalms` dessous. Au-delà, il est
     **ramené** à ce plafond — une borne du moteur, pas une valeur inventée —
     et le dit (`releaseCapped`).

     **L'hystérésis garde `hysteresisMinPalms`.** Ramené sous la posture de
     réveil, le relâchement peut tomber à deux centièmes de l'appui : le
     contact clignoterait sur le tremblement d'un bout de doigt. L'appui est
     alors abaissé à `relâchement − hysteresisMinPalms` (`pressCapped`) ; s'il
     tombe ainsi à moins de `hysteresisMinPalms / 2` du fermé, une bonne
     part de ses pincements ne l'atteindrait pas, et la mesure est refusée
     (`OUT_OF_BAND`). `pressReach` dit quelle part des épisodes l'atteint. */
  function deriveEpisodeHysteresis(episodes,o,limits){
    const l=limits||{};
    const usable=(episodes||[]).filter(ep=>ep&&ep.complete===true);
    const count=usable.length;
    if(count<o.pinchEpisodesMin){
      /* Pas assez d'épisodes, et la main n'a jamais parcouru la bande qui les
         séparerait : ce n'est pas un manque de gestes, c'est l'inséparable. */
      if(Number.isFinite(l.span)&&l.span<o.separationMinPalms)
        return {ok:false,reason:BH.STAGE_REASON.NOT_SEPARABLE,samples:count,separation:l.span};
      return {ok:false,reason:BH.STAGE_REASON.TOO_FEW_SAMPLES,samples:count};
    }
    const closed=median(usable.map(ep=>ep.minRatio));
    const open=median(usable.map(ep=>episodeOpen(ep,o)));
    const separation=open-closed;
    if(!(separation>=o.separationMinPalms))
      return {ok:false,reason:BH.STAGE_REASON.NOT_SEPARABLE,samples:count,separation,closed,open};
    let pressRatio=closed+separation*o.pressAt,pressCapped=false;
    let releaseRatio=closed+separation*o.releaseAt,releaseCapped=false;
    const ceiling=Number.isFinite(l.releaseCeiling)?l.releaseCeiling-o.wakeClearancePalms:null;
    if(ceiling!==null&&releaseRatio>ceiling){releaseRatio=ceiling;releaseCapped=true}
    if(releaseRatio-pressRatio<o.hysteresisMinPalms){
      pressRatio=releaseRatio-o.hysteresisMinPalms;pressCapped=true;
    }
    /* L'appui doit rester **franchement** au-dessus du fermé : à un cheveu
       au-dessus, la moitié des pincements de cet utilisateur ne l'atteindrait
       pas. La marge est la moitié de l'hystérésis minimale — le tremblement
       d'un doigt tenu pincé —, et sous elle la mesure est refusée. */
    if(!(pressRatio>=closed+o.hysteresisMinPalms/2))
      return {ok:false,reason:BH.STAGE_REASON.OUT_OF_BAND,samples:count,pressRatio,releaseRatio,closed,open,separation};
    /* Quelle part des gestes mesurés aurait atteint cet appui : un fait,
       rendu tel quel ; l'étape avertit sous `pressReachMin`. */
    const pressReach=usable.filter(ep=>ep.minRatio<=pressRatio).length/count;
    return {ok:true,samples:count,pressRatio,releaseRatio,closed,open,separation,releaseCapped,pressCapped,pressReach};
  }

  /* Ce qu'un épisode dit dans le **jeu de mesures** de la séance
     (`createMeasurementSet`, décision 38) : les métriques d'épisode du
     contrat, rien d'autre. `open_baseline_ratio` est l'ouvert que la
     dérivation lit (`episodeOpen`). */
  const episodeMeasures=(ep,o)=>({
    press_latency_ms:ep.pressLatencyMs,release_latency_ms:ep.releaseLatencyMs,
    episode_duration_ms:ep.durationMs,episode_min_ratio:ep.minRatio,
    open_baseline_ratio:episodeOpen(ep,o),
    closing_velocity:ep.closingVelocity,opening_velocity:ep.openingVelocity,
    episode_travel_px:ep.travelPx,episode_quality:ep.quality,
  });

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
    /* Ce que la veille **tient** : la posture du réveil (`wakePose`, le C
       composé du repli des trois autres doigts) quand la couture la publie,
       sinon le C seul. « Est-ce que mon C réveille ? » se juge sur elle. */
    const woken=sample=>Number.isFinite(sample.wakePose)?sample.wakePose:sample.cPose;
    const held=usable.filter(sample=>Number.isFinite(woken(sample))&&woken(sample)>=band.scoreMin).length;
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
    /* Le C est bon, mais les trois autres doigts restent dépliés : la veille
       ne le tiendrait pas (main plate). Une seule cause nommée pour ce cas,
       mesurée et non déduite : `wakePose` (le C composé du repli) est publié
       par la couture — la cause `middle` du correctif 89388a0, qui la
       déduisait d'un `cPoseScore` portant le témoin, s'y est fondue à la
       fusion du 28/09. */
    if(score>=band.scoreMin)
      return {ok:false,reason:BH.STAGE_REASON.OUT_OF_BAND,samples:usable.length,
        gap,reach,score,secondary,cause:'fingers'};
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
      /* Le zéro du score côté pincement, **tel quel** : c'est l'ancre contre
         laquelle le relâchement primaire dérivé se juge (`TRIAL_ANCHORS` du
         contrat), pas une borne de la bande tenue. */
      wakeGapMin:d.wakeGapMin,
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
    /* **Tenir puis relâcher** (Slice 07 adaptative, décision 56). Juste après
       le pincement primaire, sur le même doigt : l'utilisateur vient
       d'apprendre le geste, on mesure maintenant qu'il **tient** — les
       relâchements prématurés (le contact lâche sous des doigts encore
       fermés) et collés (le contact ne lâche pas à la réouverture) sont ce
       qui fait tomber une fenêtre en route ou la garder collée à la main. */
    Object.freeze({id:BH.STAGE.HOLD_RELEASE,title:'Tenir puis relâcher',
      instruction:'Pincez pouce et index, gardez les doigts fermés une seconde, puis rouvrez franchement. Trois fois.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.PINCH_SECONDARY,title:'Pincement pouce-majeur',
      instruction:'Même geste, autre doigt : pincez pouce et majeur, puis rouvrez. L’index reste replié. C’est le clic droit.',
      hold:false,needs:1}),
    Object.freeze({id:BH.STAGE.AIM,title:'Viser et cliquer',
      instruction:'Formez le C pour faire apparaître le jeton, amenez-le sur chaque cible marquée, puis pincez pouce et index sans bouger la main.',
      hold:false,needs:1,target:true}),
    /* **Un écran, deux sous-étapes** (Slice 07, décisions 29 et 30).

       Ce qui a été retiré compte autant que ce qui arrive. Les deux écrans
       d'avant — « Faire glisser : déplacez la main franchement vers la droite »
       et « Deux mains : écartez-les doucement » — demandaient des gestes **en
       l'air**, qui ne ressemblaient à rien de ce que l'utilisateur fera
       ensuite. On mesurait une course de paume et on comptait des mains ; on
       n'apprenait pas à manipuler une fenêtre, et rien de ce qui a été appris
       là ne servait devant une vraie fenêtre.

       Ici on manipule **la vraie chose** : un cadre qui porte `.sc-node` et
       `data-representation="window"`, donc le vrai résolveur de cible le
       collecte, les vraies zones s'y dessinent, le vrai `combineCaptures`
       décide ce que deux mains y produisent, et la vraie géométrie de scène
       calcule sa boîte. Rien n'est réécrit ici — ni taille minimale, ni
       non-inversion, ni appartenance de zone.

       **Les deux sous-étapes partagent un seul écran et un seul cadre.** Elles
       ne repassent donc pas par `overlay.step()` entre elles : il viderait la
       scène, donc le cadre que l'utilisateur tient des yeux, et lui ferait
       relire un titre qu'il vient de lire. C'est exactement ce que
       `overlay.deadline()` existe pour permettre (Slice 06).

       **Le vocabulaire persisté ne bouge pas.** `drag` et `resize` restent les
       deux identités mesurées — un profil doit continuer de dire laquelle a
       abouti (décision 31), et ces deux mots sont plus vrais qu'avant :
       maintenant, `drag` *est* un déplacement de cadre et `resize` *est* un
       redimensionnement. Ce qui change est le nombre d'**écrans**, pas le
       nombre d'étapes. */
    Object.freeze({id:BH.STAGE.DRAG,title:'Manipulation de fenêtre',
      instruction:'Une vraie fenêtre JARVIS est posée au centre. On va l’attraper par ses bords — d’une main, des deux, puis la déposer ailleurs.',
      hold:false,needs:1,practice:true,
      subs:Object.freeze([
        Object.freeze({id:BH.STAGE.DRAG,mode:'move',needs:1,
          label:'6A · Déplacer',
          instruction:'Pincez un bord ou un coin de la fenêtre, déplacez-la, puis relâchez.',
          caption:'Une main sur un bord'}),
        Object.freeze({id:BH.STAGE.RESIZE,mode:'resize',needs:2,
          label:'6B · Redimensionner',
          instruction:'Attrapez la même fenêtre des deux mains — n’importe où dedans, ou par deux bords — et écartez ou rapprochez vos mains.',
          caption:'Deux mains sur la fenêtre'}),
        /* **6C, déposer** (Slice 07 adaptative, décision 56) : le glissement
           a maintenant une **destination**. Ce qui se mesure est ce que le
           banc de test comptera : dépôt réussi, écart au centre, lâchers
           avant d'arriver. Même vraie fenêtre, même vrai moteur. */
        Object.freeze({id:BH.STAGE.DROP,mode:'drop',needs:1,
          label:'6C · Déposer',
          instruction:'Attrapez la fenêtre, portez-la jusque dans le cadre en pointillé, puis relâchez-la dedans.',
          caption:'Porter jusqu’à la destination'}),
      ])}),
    /* **Ce qui n'est pas un clic** (tâche adaptative, Slice 03, décision 47).
       Toutes les étapes d'avant mesurent un geste voulu ; celle-ci mesure ce
       qui se déclenche **sans** l'être. Un écran, deux temps, sur le modèle
       de la fenêtre (un rail, un « Passer ce temps ») :

       - 7A, **bouger librement** : les mains bougent comme en parlant. Tout
         appui, clic droit, réveil, cible prise ou curseur affiché est faux ;
       - 7B, **viser sans cliquer** : le jeton se pose sur des points, sans
         pincer. Le curseur y est voulu ; un appui ou une cible prise ne l'est
         pas.

       Joué **en dernier**, et c'est voulu : l'utilisateur sait alors ce
       qu'est un pincement, donc « ne pincez pas » veut dire quelque chose.
       Rien de ce qui s'y mesure ne devient un seuil : ce sont des taux
       (`CALIBRATION_METRIC`), la preuve que la Slice 04 et l'agent liront. */
    Object.freeze({id:BH.STAGE.NATURAL_MOTION,title:'Bouger sans cliquer',
      instruction:'Deux temps pour mesurer ce qui n’est pas un clic : bougez naturellement, puis visez sans pincer. Rien ne doit se déclencher.',
      hold:false,needs:1,negative:true,
      subs:Object.freeze([
        Object.freeze({id:BH.STAGE.NATURAL_MOTION,mode:'natural',needs:1,negative:true,
          label:'7A · Bouger librement',
          instruction:'Bougez les mains comme en parlant : gestes, main qui passe, main qui se pose. Ne visez rien et ne pincez pas.',
          caption:'Mouvements ordinaires'}),
        Object.freeze({id:BH.STAGE.AIM_NO_CLICK,mode:'aim',needs:1,negative:true,target:true,
          label:'7B · Viser sans cliquer',
          instruction:'Formez le C : le jeton apparaît. Posez-le sur chaque point et restez-y un instant, sans pincer.',
          caption:'Viser, sans pincer'}),
      ])}),
  ]);
  /* **Les écrans publics** : les six exercices, plus le rapport (Slice 07).

     Le rapport était jusqu'ici annoncé « Étape 7 sur 7 » alors que l'étape 7
     était un exercice : deux écrans différents portaient le même numéro, et le
     dernier exercice n'avait donc aucun écran à lui dans le décompte. Il est
     maintenant le **septième écran**, ce que la décision 26 demande en toutes
     lettres — « rest, C, primary pinch, secondary pinch, target pinch, window
     manipulation, completion ». */
  /* **Slice 07 adaptative** : huit exercices, neuf écrans, onze étapes
     mesurées. L'ordre des écrans (décision 56) va du geste le plus simple au
     plus composé, puis finit par ce qui n'est pas un geste : suivi au repos,
     posture de visée, pincement primaire, **tenue et relâchement** (même
     doigt, tout de suite après), pincement secondaire, visée, fenêtre
     (déplacer, redimensionner, **déposer**), négatifs. */
  const SCREENS=STEPS.length+1;

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
     - `REVIEW`  — **la revue** (Slice 07 adaptative, décision 56), qui
                   remplace `RESULT`/`NEXT` : le verdict, ce qui a été mesuré
                   en clair, l'explication de l'assistant s'il en a une, et
                   cinq actions — Refaire, Ajuster, Valider l'étape, Passer
                   (avec une raison), Quitter. **Elle n'avance jamais seule**,
                   quel que soit l'exercice et qu'un essai soit en cours ou
                   non : seule une décision de l'utilisateur (bouton ou voix)
                   en sort. Les règles de repli partiel ne changent pas : une
                   étape ratée laisse ses clés nulles (décision 31) — et elle
                   ne se **valide** pas : on la refait ou on la passe en
                   disant pourquoi.

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
  const PHASE=Object.freeze({INTRO:'intro',ARMED:'armed',RUNNING:'running',REVIEW:'review'});
  const PHASE_ORDER=Object.freeze([PHASE.INTRO,PHASE.ARMED,PHASE.RUNNING,PHASE.REVIEW]);
  /* Les quatre phases que l'utilisateur **voit** passer, et leur mot. La
     revue a sa pastille : c'est un état où il est attendu, pas une
     transition. */
  const PHASE_STRIP=Object.freeze([
    Object.freeze([PHASE.INTRO,'Lecture']),
    Object.freeze([PHASE.ARMED,'Prêt']),
    Object.freeze([PHASE.RUNNING,'Mesure']),
    Object.freeze([PHASE.REVIEW,'Revue']),
  ]);
  /* **Ce que la revue montre**, par étape (décision 56) : des lignes de
     mesures, chacune une **métrique du contrat** résumée par
     `aggregateMetric` sur des références de la séance — jamais un nombre
     calculé à côté. `from` : `ep` (les épisodes de l'essai), `ex` (la ligne
     d'exercice de l'essai). Les étapes absentes n'ont pas de métrique : la
     revue ne montre alors que le verdict. */
  const line=(metric,aggregate,from,label)=>Object.freeze({metric,aggregate,from,label});
  const REVIEW_LINES=Object.freeze({
    [BH.STAGE.NEUTRAL]:Object.freeze([line('pointer_jitter_px','p50','ex','Tremblement de la main immobile')]),
    [BH.STAGE.PINCH_PRIMARY]:Object.freeze([
      line('episode_duration_ms','count','ep','Pincements mesurés'),
      line('press_latency_ms','p50','ep','Appui reconnu (délai médian)'),
      line('release_latency_ms','p50','ep','Relâchement reconnu (délai médian)'),
      line('missed_press_rate','p50','ex','Pincements non reconnus'),
      line('missed_release_rate','p50','ex','Relâchements non reconnus')]),
    [BH.STAGE.HOLD_RELEASE]:Object.freeze([
      line('episode_duration_ms','count','ep','Pincements tenus mesurés'),
      line('premature_drop_count','p50','ex','Relâchements trop tôt (doigts encore fermés)'),
      line('missed_release_rate','p50','ex','Relâchements qui collent'),
      line('release_latency_ms','p50','ex','Relâchement reconnu (délai médian)')]),
    [BH.STAGE.AIM]:Object.freeze([
      line('wrong_target_count','p50','ex','Mauvaise étoile prise'),
      line('missed_click_count','p50','ex','Pincements dans le vide'),
      line('reacquisition_count','p50','ex','Bascules entre voisines'),
      line('acquisition_ms','p50','ex','Temps pour prendre la bonne étoile (médiane)')]),
    [BH.STAGE.DROP]:Object.freeze([
      line('drag_success_rate','p50','ex','Dépôts réussis'),
      line('placement_error_px','p50','ex','Écart au centre de la destination'),
      line('premature_drop_count','p50','ex','Lâchers avant la destination')]),
    [BH.STAGE.NATURAL_MOTION]:Object.freeze([
      line('false_press_rate','p50','ex','Faux appuis'),
      line('false_secondary_press_rate','p50','ex','Faux clics droits'),
      line('unintended_wake_rate','p50','ex','Réveils non voulus'),
      line('unintended_target_rate','p50','ex','Cibles prises sans le vouloir'),
      line('unintended_pointer_rate','p50','ex','Curseur affiché sans visée')]),
    [BH.STAGE.AIM_NO_CLICK]:Object.freeze([
      line('false_press_rate','p50','ex','Faux appuis'),
      line('false_secondary_press_rate','p50','ex','Faux clics droits'),
      line('unintended_target_rate','p50','ex','Cibles prises sans le vouloir')]),
  });
  /* Le pincement secondaire se lit comme le primaire. */
  const REVIEW_LINES_ALL=Object.freeze({...REVIEW_LINES,[BH.STAGE.PINCH_SECONDARY]:REVIEW_LINES[BH.STAGE.PINCH_PRIMARY]});
  /* Une valeur de métrique, en français, selon son unité du contrat. */
  const frNumber=(value,digits)=>value.toFixed(digits).replace('.',',').replace(/,0+$/,'');
  function formatMetric(metric,aggregate,value){
    if(value===null||value===undefined||!Number.isFinite(value))return 'non mesuré';
    if(aggregate==='count')return String(Math.round(value));
    const unit=BH.CALIBRATION_METRIC[metric].unit;
    if(unit==='ms')return `${Math.round(value)} ms`;
    if(unit==='px')return `${frNumber(value,1)} px`;
    if(unit==='ratio')return `${Math.round(value*100)} %`;
    if(unit==='per_min')return `${frNumber(value,1)} par minute`;
    if(unit==='count')return String(Math.round(value));
    return frNumber(value,2);
  }
  /* **Pourquoi passer**, en mots d'utilisateur (décision 57). */
  const SKIP_TEXT=Object.freeze({
    not_relevant:'Pas utile pour moi',
    cannot_perform:'Je n’arrive pas à faire le geste',
    tracking:'La caméra me voit mal',
    later:'Plus tard',
  });

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
      caption:'Pincer pouce-index sur la cible'}),
    /* **Slice 07, et aucune posture nouvelle.** `hand_art` est un alphabet de
       formes qui ne sait rien des gestes ; la question était donc « ces deux
       sous-étapes ont-elles besoin d'une lettre de plus ? », et la réponse est
       non. Saisir un bord, c'est pincer : 6A est le mime du pincement primaire,
       exactement comme l'étape 3 — ce qui se déplace n'est pas la main, c'est
       le cadre, et le cadre est à l'écran, vrai, juste à côté. Ajouter une
       « main qui tire » aurait dessiné une information que l'exercice porte
       déjà mieux que le dessin.

       6B est le **même** pincement, deux fois, dont une en miroir : c'est
       littéralement ce que fait l'utilisateur, et `handSvg({mirror:true})`
       rend la main gauche sans qu'une huitième posture existe. `pair` dit à
       `demoNode` de poser les deux côte à côte au lieu de les empiler — deux
       mains empilées se liraient comme une seule main qui bouge, ce qui est
       l'inverse du geste demandé. */
    [BH.STAGE.DRAG]:Object.freeze({mime:true,aside:true,
      poses:Object.freeze(['PINCH_PRIMARY_OPEN','PINCH_PRIMARY_CLOSED']),
      caption:'Une main pince un bord'}),
    [BH.STAGE.RESIZE]:Object.freeze({mime:false,pair:true,aside:true,
      poses:Object.freeze(['PINCH_PRIMARY_CLOSED','PINCH_PRIMARY_CLOSED']),
      mirror:Object.freeze([true,false]),
      caption:'Deux mains, deux zones différentes'}),
    /* Slice 03 adaptative, **aucune posture nouvelle** : la main au repos
       pour « bougez comme d'habitude », le C pour « visez » — c'est la posture
       qui fait apparaître le jeton (décision 46), donc celle qu'on montre. */
    /* Slice 07 adaptative, **aucune posture nouvelle** : tenir, c'est le
       pincement primaire fermé qu'on garde ; déposer, c'est le pincement de
       6A qui porte. */
    [BH.STAGE.HOLD_RELEASE]:Object.freeze({mime:true,
      poses:Object.freeze(['PINCH_PRIMARY_OPEN','PINCH_PRIMARY_CLOSED']),
      caption:'Fermer, tenir, rouvrir'}),
    [BH.STAGE.DROP]:Object.freeze({mime:true,aside:true,
      poses:Object.freeze(['PINCH_PRIMARY_OPEN','PINCH_PRIMARY_CLOSED']),
      caption:'Pincer, porter, relâcher dedans'}),
    [BH.STAGE.NATURAL_MOTION]:Object.freeze({mime:false,
      poses:Object.freeze(['REST']),caption:'Mains libres, aucun pincement'}),
    [BH.STAGE.AIM_NO_CLICK]:Object.freeze({mime:false,
      poses:Object.freeze(['WAKE_C']),caption:'Le C vise, sans pincer'}),
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

  /* **L'exercice de sélection** (Slice 05 adaptative, décision 49) : ce que
     l'étape de visée joue quand la page lui prête un banc de sélection. Au
     lieu de points dessinés par la coque, de **vraies** étoiles que le vrai
     résolveur présélectionne et que la vraie descente fige : l'erreur de
     sélection se mesure donc là où elle naît, et la mesure dit si
     l'assistance est trop faible (pincements dans le vide) ou trop forte
     (mauvaise étoile, bascules entre voisines).

     Quatre manches, chacune sur un emplacement de `AIM_SPOTS` (la main doit
     voyager, comme avant) : une **petite** étoile seule, **deux voisines**,
     un **groupe** serré, une étoile **qui bouge** près d'une voisine fixe.
     `dx`/`dy`/`size` en pixels de la fenêtre — l'écart entre voisines est une
     taille à l'écran, pas une fraction : c'est lui que l'assistance doit
     trancher, et il doit être le même sur un portable et sur un écran large.
     `expected` : la seule étoile attendue de la manche. */
  const roundStar=(dx,dy,size,extra)=>Object.freeze({dx,dy,size,expected:false,moving:false,...(extra||{})});
  const SELECTION_ROUNDS=Object.freeze([
    Object.freeze({id:'small',label:'Petite étoile',
      stars:Object.freeze([roundStar(0,0,12,{expected:true})])}),
    Object.freeze({id:'nearby',label:'Deux voisines',
      stars:Object.freeze([roundStar(-16,0,20),roundStar(16,0,20,{expected:true})])}),
    Object.freeze({id:'cluster',label:'Groupe serré',
      stars:Object.freeze([roundStar(-26,0,16),roundStar(0,0,16,{expected:true}),roundStar(26,0,16),roundStar(0,-26,16)])}),
    Object.freeze({id:'moving',label:'Étoile mobile',
      stars:Object.freeze([roundStar(0,0,18,{expected:true,moving:true}),roundStar(0,40,18)])}),
  ]);
  /* Les étoiles d'une manche, en pixels de la fenêtre. */
  function selectionStars(index,view){
    const round=SELECTION_ROUNDS[index];
    if(!round)return [];
    const spot=AIM_SPOTS[index%AIM_SPOTS.length];
    const width=Number(view&&view.width)||0,height=Number(view&&view.height)||0;
    const cx=Math.round(width*spot.x),cy=Math.round(height*spot.y);
    return round.stars.map(one=>({x:cx+one.dx,y:cy+one.dy,size:one.size,
      expected:one.expected,moving:one.moving}));
  }

  /* **Le compte de l'exercice**, pur : des faits du banc (`press`, `switch`,
     `ambiguous`, voir `createSelectionObserver` du moteur) à une ligne de
     mesures du contrat (`CALIBRATION_METRIC`). La progression se décide au
     **relâchement** — les étoiles d'une manche ne disparaissent pas sous un
     pincement tenu — et une manche se passe après `attemptsMax` pincements
     ratés.

       wrong_target_count   pincements qui ont figé une **autre** étoile
       missed_click_count   pincements qui n'ont rien figé
       target_ambiguity     ambiguïté moyenne (d1/d2) au moment des pincements
       reacquisition_count  bascules de la présélection entre deux cibles
       acquisition_ms       médiane, de l'ouverture d'une manche à la bonne prise */
  function createSelectionExercise(options){
    const rounds=Math.max(1,Math.round(Number(options&&options.rounds)||SELECTION_ROUNDS.length));
    const attemptsMax=Math.max(1,Math.round(Number(options&&options.attemptsMax)||3));
    let index=0,openedAt=null,pending=null,fails=0;
    const count={hits:0,wrong:0,missed:0,switches:0,ambiguous:0,skipped:0};
    const ambiguities=[],acquisitions=[];
    return {
      index:()=>index,
      done:()=>index>=rounds,
      open(at){openedAt=Number.isFinite(Number(at))?Number(at):null;pending=null;fails=0},
      /* Un fait du banc ; rend l'issue du pincement en cours, s'il y en a une. */
      fact(f){
        if(!f||typeof f!=='object')return pending;
        if(f.type==='switch')count.switches+=1;
        else if(f.type==='ambiguous')count.ambiguous+=1;
        else if(f.type==='press'){
          if(Number.isFinite(f.ambiguity))ambiguities.push(f.ambiguity);
          pending=f.outcome==='expected'||f.outcome==='other'?f.outcome:'none';
          if(pending==='expected'){
            count.hits+=1;
            if(openedAt!==null&&Number.isFinite(f.t))acquisitions.push(Math.max(0,f.t-openedAt));
          }else{
            fails+=1;
            if(pending==='other')count.wrong+=1;else count.missed+=1;
          }
        }
        return pending;
      },
      /* Le relâchement : `{outcome, next}` — `next` dit que la manche est
         finie (prise, ou passée après trop d'essais). */
      release(){
        const outcome=pending;pending=null;
        if(outcome===null)return {outcome:null,next:false,skipped:false};
        if(outcome==='expected'){index+=1;fails=0;return {outcome,next:true,skipped:false}}
        if(fails>=attemptsMax){index+=1;fails=0;count.skipped+=1;return {outcome,next:true,skipped:true}}
        return {outcome,next:false,skipped:false};
      },
      pending:()=>pending,
      summary:()=>Object.freeze({...count,rounds}),
      row(){
        const mean=ambiguities.length?ambiguities.reduce((a,b)=>a+b,0)/ambiguities.length:null;
        return Object.freeze({wrong_target_count:count.wrong,missed_click_count:count.missed,
          target_ambiguity:mean===null?null:Math.min(1,Math.max(0,mean)),
          reacquisition_count:count.switches,
          acquisition_ms:BH.quantile(acquisitions,.5)});
      },
    };
  }

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
  /* **L'armement des commandes** (Slice 07 adaptative, reprise QA) : un
     bouton que `buttons()` vient de dessiner n'accepte pas d'activation avant
     ce délai. Sans lui, un double-clic sur « Valider l'étape » tombait sur le
     « Passer… » de l'écran suivant, et Entrée tenue enfonçait la commande
     suivante dès qu'elle apparaissait. Assez court pour ne jamais se sentir. */
  const ARM_MS=300;

  const STYLE_ID=BH.DOM.flowStyleId;
  /* `--cosmos-accent` est **l'état vocal peint**, pas un jeton de thème :
     `control_center_work.js` le réécrit à chaque changement d'état (orange en
     `speaking`, vert en `listening`). La coque tenait donc sa consigne en
     orange pendant que JARVIS parlait, et — pire pour ce fichier — en **vert**
     pendant qu'il écoutait, alors que la décision 21 quarante lignes plus haut
     réserve le vert à « ce geste vient d'être reconnu » et borne sa durée. La
     coque reprend le bleu de la page ; il vaut #6ee7ff, exactement les
     `rgba(110,231,255,…)` que cette feuille écrit déjà en clair pour le voile,
     le rail et la cible — accent et littéraux sont enfin la même couleur.
     Voir la note de `control_center_barehands_hud.js`. */
  const ACCENT='var(--bh-accent,var(--accent,#6ee7ff))';
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
/* **Décision 18 amendée (Slice 10 adaptative, QA réelle).** Le voile
   translucide comptait sur \`backdrop-filter\` pour flouter la page ; or la
   racine de la coque s'anime en opacité (\`jfEnter\`, remplissage \`both\`),
   ce qui en fait sous Chrome la racine du fond filtré : le flou ne voyait
   plus la page, et le panneau Agents, les pastilles et les barres se lisaient
   à travers le rapport (capture QA 1440 × 900). Le voile est donc **opaque**,
   comme celui du test (Slice 09) : un bleu nuit en dégradé, jamais un noir
   plat, avec la teinte JARVIS du haut et une vignette — l'atmosphère reste,
   la page ne transparaît plus. */
${R} .${D.flowVeilClass}{position:absolute;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(120% 86% at 50% -8%,rgba(110,231,255,.13),transparent 58%),
    radial-gradient(140% 120% at 50% 112%,rgba(18,40,62,.55),transparent 70%),
    linear-gradient(180deg,#07111b,#040a12)}
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
/* **Le rapport a sa mise en page** (reprise QA de la Slice 07 adaptative) :
   liste puis récapitulatif, **du haut vers le bas** et défilant dans la
   scène, au lieu d'être centrés au point de déborder sous le titre. */
${R}[data-report="1"] .${D.flowStageClass}{justify-content:flex-start;overflow-y:auto;
  overscroll-behavior:contain;padding-bottom:8px}
${R}[data-report="1"] .jf-report{order:1}
/* **« Sera enregistré » sans défiler** (Slice 10, résidu de la QA de la
   Slice 07) : à 1440 × 900, onze lignes d'exercice poussaient le
   récapitulatif — ce sur quoi on décide — sous le pli. La liste garde sa
   place et son ordre (liste puis récapitulatif) mais sa **hauteur est
   bornée** et elle défile seule ; quand elle déborde, un liseré en bas le
   dit (\`data-scrolls\`) et elle se laisse parcourir au clavier. */
${R}[data-report="1"] .jf-report{max-height:min(34vh,330px);overflow-y:auto;overscroll-behavior:contain;
  flex:0 0 auto}
${R}[data-report="1"] .jf-report[data-scrolls="1"]{box-shadow:inset 0 -16px 14px -14px rgba(110,231,255,.45);
  border-bottom:1px solid rgba(110,231,255,.28)}
${R}[data-report="1"] .jf-report:focus-visible{outline:2px solid var(--jf-accent);outline-offset:3px}
${R}[data-report="1"] .${D.flowExerciseClass}{order:2;flex:0 0 auto}
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
    let openedAt=null,stageAt=null,stageLimit=null,onExit=null,onKey=null,onEscape=null,inerted=[];
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
      /* Focalisable par programme (Slice 07 adaptative) : à chaque nouvel
         écran le focus s'y pose, pour qu'un lecteur d'écran lise le titre qui
         vient d'arriver au lieu de rester sur un bouton qui n'existe plus. */
      heading.setAttribute('tabindex','-1');
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
        onEscape=typeof s.escape==='function'?s.escape:null;
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
        /* Échap : d'abord le parcours (`spec.escape`) — il ferme un
           sous-panneau ou demande confirmation — et seulement s'il ne l'a pas
           pris, la sortie. Une touche tenue (`repeat`) ne compte pas : une
           seule pression, une seule décision (reprise QA de la Slice 07). */
        onKey=event=>{
          if(!event||event.key!=='Escape')return;
          event.preventDefault&&event.preventDefault();
          if(event.repeat)return;
          if(typeof onEscape==='function'){
            let taken=false;
            try{taken=onEscape()===true}
            catch(error){console.warn('[barehands] flow.escape_failed',error)}
            if(taken)return;
          }
          onExit('escape');
        };
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
        root.setAttribute('data-report','');
        /* Une phrase tenue appartient à son écran (Slice 07 adaptative) : le
           choix d'une raison ou un verdict tenus ne bâillonnent pas l'écran
           qui arrive. */
        heldUntil=0;
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
        /* `null` = aucune échéance. `Number(null)` vaut 0 : le lire comme une
           durée affichait « 0 s restantes » sur le rapport (reprise QA). */
        stageLimit=s.deadlineMs===null||s.deadlineMs===undefined||!Number.isFinite(Number(s.deadlineMs))
          ?null:Number(s.deadlineMs);
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
      /* Rendre la parole avant l'échéance d'une phrase tenue (Slice 07
         adaptative : « Retour » depuis le choix d'une raison). */
      releaseNote(){heldUntil=0;return true},
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
      buttons(list,label){
        if(!actions)return 0;
        actions.innerHTML='';
        /* Un groupe nommé (Slice 07 adaptative) : « Actions de la revue »,
           « Pourquoi passer cette étape ? » — le lecteur d'écran dit à quoi
           servent les boutons avant de les lire. */
        if(label)actions.setAttribute('aria-label',String(label));
        actions.setAttribute('role','group');
        const armedAt=now()+ARM_MS;
        for(const item of(Array.isArray(list)?list:[])){
          const button=el('button','',String(item.label||''));
          button.setAttribute('type','button');
          if(item.primary)button.className='primary';
          if(item.id)button.setAttribute('data-flow-action',String(item.id));
          if(item.hint)button.setAttribute('title',String(item.hint));
          if(item.pressed!==undefined)button.setAttribute('aria-pressed',item.pressed?'true':'false');
          /* Une activation **avant l'armement** est ignorée, et dite au
             journal : elle vient d'un geste destiné à l'écran d'avant. Le
             focus ne reste pas sur le bouton ignoré (le clic l'y a posé, et
             Entrée l'activerait une fois armé) : il va au **titre** du nouvel
             écran, qui ne commet rien (Slice 10, résidu de la QA de la
             Slice 07). */
          button.addEventListener('click',()=>{
            if(now()<armedAt){console.warn('[barehands] flow.action_unarmed',JSON.stringify({action:item.id||null}));
              if(heading&&typeof heading.focus==='function')heading.focus();
              return}
            if(item.run)item.run();
          });
          /* Entrée ou Espace **tenues** : la répétition de la touche n'active
             rien — une pression, une décision. */
          button.addEventListener('keydown',event=>{
            if(event&&event.repeat&&(event.key==='Enter'||event.key===' '||event.key==='Spacebar'))
              event.preventDefault&&event.preventDefault();
          });
          actions.appendChild(button);
        }
        return actions.children.length;
      },
      /* **Le focus suit l'état** (Slice 07 adaptative) : une revue le pose
         sur son action principale, un nouvel écran sur son titre. Sans cela,
         le focus resterait sur un bouton que `buttons()` vient de détruire, et
         la navigation au clavier repartirait du haut de la page. Gardé : un
         double de DOM n'a pas toujours de focus. Rend `true` s'il a été
         posé. */
      focusAction(id){
        if(!actions)return false;
        const target=Array.from(actions.children).find(node=>node.getAttribute&&node.getAttribute('data-flow-action')===String(id));
        if(!target||typeof target.focus!=='function')return false;
        target.focus();return true;
      },
      focusTitle(){
        if(!heading||typeof heading.focus!=='function')return false;
        heading.focus();return true;
      },
      /* Poser le focus sur un nœud **qui ne commet rien** (une région de
         lecture), rendu focalisable par programme. Après un changement
         d'état, le focus ne tombe jamais sur une commande qui enregistre,
         valide ou passe (reprise QA : Entrée tenue enregistrait le profil
         sans que le rapport ait été lu). */
      focusNode(node){
        if(!node||typeof node.focus!=='function')return false;
        if(typeof node.setAttribute==='function')node.setAttribute('tabindex','-1');
        node.focus();return true;
      },
      /* Retirer **un** nœud monté, et lui seul (Slice 07 adaptative : la
         revue quitte la région `feedback` sans emporter le bandeau de phases
         ni le rail des temps). Rend `true` s'il y était. */
      unmountNode(name,node){
        const list=mounted&&mounted[String(name)];
        if(!list)return false;
        const at=list.indexOf(node);
        if(at<0)return false;
        list.splice(at,1);
        if(node&&typeof node.remove==='function')node.remove();
        return true;
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
        root.setAttribute('data-report',report.hidden?'':'1');
        /* La liste bornée défile seule : elle se nomme, se focalise au
           clavier, et dit quand elle déborde. */
        if(!report.hidden){
          report.setAttribute('aria-label','Détail par exercice');
          report.setAttribute('tabindex','0');
          const scrolls=Number(report.scrollHeight)>Number(report.clientHeight)+1;
          report.setAttribute('data-scrolls',scrolls?'1':'0');
        }
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
/* **Deux mains, côte à côte** (Slice 07). L'empilement est ce qui fait lire
   « deux doigts se ferment » ; pour une démonstration à deux mains c'est
   l'erreur exactement inverse qu'il faut éviter, donc \`data-pair\` pose les
   deux dessins l'un à côté de l'autre. La main gauche est la droite en
   miroir : aucune posture nouvelle n'a été ajoutée à l'alphabet. */
${R} .${DEMO_CLASS}[data-pair="1"]{grid-auto-flow:column;align-items:center;
  gap:clamp(14px,4vw,40px)}
${R} .${DEMO_CLASS}[data-pair="1"]>svg{grid-area:auto;opacity:1;animation:none;
  width:clamp(96px,16vh,150px)}
/* **La démonstration se range** pendant l'exercice de fenêtre : le centre du
   cadre appartient à la fenêtre d'entraînement, qui *est* l'exercice. Elle ne
   disparaît pas pour autant — c'est elle qui prouve que quelque chose tourne
   pendant « Prêt », où aucune échéance ne descend (RÈGLE ZÉRO). */
${R} .jf-demo-wrap.jf-demo-aside{position:absolute;left:0;bottom:0;z-index:3;
  align-items:flex-start;gap:6px}
${R} .jf-demo-aside .${DEMO_CLASS}>svg{width:clamp(64px,9.5vh,104px)}
${R} .jf-demo-aside .${DEMO_CLASS}[data-pair="1"]>svg{width:clamp(52px,7.5vh,84px)}
${R} .jf-demo-aside .jf-caption{max-width:22ch;text-align:left;letter-spacing:.12em}
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
/* ------------------------------------- la fenêtre d'entraînement (Slice 07)
   **Le cadre n'est pas habillé ici, et c'est le sujet.** Il porte
   \`.sc-node.sc-window\`, la feuille de la scène est **globale**, donc il est
   dessiné par exactement les mêmes règles que les vraies fenêtres JARVIS — un
   fond, un rayon, une ombre intérieure, un flou d'arrière-plan. Une seconde
   feuille « qui imite » aurait divergé au premier changement de thème, et
   l'exercice aurait cessé de ressembler à ce qu'il enseigne.

   Ce qui suit ne fait que le **placer** : \`toScreen\` rend des coordonnées de
   fenêtre, donc la couche est \`fixed\` et couvre le cadre entier. La classe
   \`scene\` est là pour ses **variables** (\`--sc-edge\`, \`--sc-surface\`,
   \`--sc-radius\`, \`--tone\`), pas pour sa mise en page : les trois
   déclarations ci-dessous la reprennent. */
${R} .jf-practice{position:fixed;inset:0;z-index:2;pointer-events:none;
  contain:none;overflow:visible}
${R} .jf-practice .sc-node{pointer-events:auto}
/* **Le pointillé dit « ceci ne sera pas enregistré ».** Même vocabulaire que
   la mire de \`pinch_target\`, que les cibles restantes et que l'outil absent
   de la palette : discontinu = annoncé, plein = constaté. Sans lui, un cadre
   d'entraînement parfaitement identique à une vraie fenêtre laisserait croire
   qu'on vient de déplacer quelque chose de sa scène. */
${R} .jf-practice-frame{outline:1.5px dashed color-mix(in srgb,var(--jf-accent) 45%,transparent);
  outline-offset:7px}
/* --------------------------------------- les deux temps de l'étape 6 (S07)
   Un écran, deux sous-étapes : il faut voir laquelle on joue **et** qu'il en
   reste une. Même grammaire que le bandeau de phases — un seul allumé — parce
   que c'est la même question posée à une autre échelle, et deux grammaires
   pour une question se liraient comme deux questions. */
${R} .jf-subs{display:flex;flex-direction:column;align-items:center;
  gap:clamp(6px,1.1vh,12px);text-align:center;width:100%}
${R} .jf-sub-rail{display:flex;gap:clamp(12px,2.4vw,24px);align-items:center;
  font-family:var(--jf-sans);font-size:10px;letter-spacing:.2em;
  text-transform:uppercase;color:var(--jf-muted)}
${R} .jf-sub-rail b{display:inline-flex;align-items:center;gap:7px;font-weight:400;
  transition:color .2s ease}
${R} .jf-sub-rail b::before{content:'';width:6px;height:6px;border-radius:50%;
  background:rgba(255,255,255,.16);transition:background .2s ease}
${R} .jf-sub-rail b[data-at="done"]{color:var(--jf-soft)}
${R} .jf-sub-rail b[data-at="done"]::before{background:rgba(110,231,255,.45)}
${R} .jf-sub-rail b[data-at="now"]{color:var(--jf-accent)}
${R} .jf-sub-rail b[data-at="now"]::before{background:var(--jf-accent);
  box-shadow:0 0 10px rgba(110,231,255,.65)}
/* La consigne de la **sous-étape**. Le titre de l'écran reste « Manipulation
   de fenêtre » du début à la fin : ce qui change entre 6A et 6B est ce qu'on
   demande, pas le sujet, et repasser par \`step()\` pour le dire effacerait le
   cadre que l'utilisateur est en train de regarder. */
${R} .jf-sub-say{margin:0;font-family:var(--jf-sans);color:var(--jf-soft);
  font-size:clamp(14px,1.3vw,18px);line-height:1.5;max-width:48ch;text-wrap:pretty}
@keyframes jfMime{0%{opacity:0}6%{opacity:1}44%{opacity:1}50%{opacity:0}100%{opacity:0}}
@keyframes jfBreath{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.5);opacity:.6}}
@media (max-width:720px){
  ${R} .${DEMO_CLASS}>svg{width:clamp(108px,34vw,172px)}
  ${R} .${DEMO_CLASS}[data-pair="1"]>svg{width:clamp(76px,22vw,118px)}
  ${R} .jf-phases{gap:12px;font-size:9px;letter-spacing:.14em}
  ${R} .jf-sub-rail{gap:12px;font-size:9px;letter-spacing:.14em}
  ${R} .jf-sub-say{font-size:14px;max-width:34ch}
  /* Au téléphone, la démonstration rangée dans un coin mangerait le cadre :
     elle passe sous lui, en ligne, plutôt que par-dessus. */
  ${R} .jf-demo-wrap.jf-demo-aside{position:static;align-items:center}
  ${R} .jf-demo-aside .jf-caption{text-align:center;max-width:none}
}
@media (max-height:560px){
  ${R} .${DEMO_CLASS}>svg{width:clamp(92px,20vh,148px)}
  ${R} .jf-demo-wrap{gap:6px}
  ${R} .jf-subs{gap:4px}
  ${R} .jf-sub-say{font-size:13px;line-height:1.4}
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
  ${R} .jf-sub-rail b,${R} .jf-sub-rail b::before{transition:none}
}
/* ------------------------------------ l'exercice de sélection (S05 adaptative)
   Deux cercles autour d'une étoile, et ils ne disent pas la même chose : le
   **pointillé** (celui-ci) dit laquelle prendre — discontinu = annoncé, comme
   la mire de visée ; l'**anneau plein** de la présélection (feuille de
   l'aperçu de cible) dit laquelle serait prise si l'on pinçait maintenant. Le
   geste juste est de pincer quand les deux se superposent. Le pointillé est
   plus large que l'anneau, pour que les deux restent lisibles ensemble. */
${R} .jf-select .jf-select-cue{position:absolute;left:-11px;top:-11px;right:-11px;bottom:-11px;
  border-radius:50%;border:1.5px dashed color-mix(in srgb,var(--jf-accent) 70%,transparent);
  pointer-events:none}
/* L'étoile qui bouge glisse par \`translate\`, pas par \`transform\` : la
   position posée par la page vit dans \`transform\`, et les deux s'ajoutent. Le
   résolveur lit la boîte **dessinée**, donc la cible mobile se vise là où on la
   voit. Sous « moins de mouvement », elle reste immobile (voir plus haut). */
${R} .jf-select .jf-select-moving{animation:jfSelectDrift 3.6s ease-in-out infinite alternate}
@keyframes jfSelectDrift{from{translate:-60px 0}to{translate:60px 0}}
@media (prefers-reduced-motion:reduce){${R} .jf-select .jf-select-moving{animation:none}}
/* ------------------------------------------------------ la revue (S07 adapt.)
   **Ce qui a été mesuré, en clair.** Même grammaire que le rapport de fin —
   libellé à gauche, valeur à droite, filet entre les lignes — parce que c'est
   la même question posée plus tôt : « qu'est-ce que ça a donné ? ». Aucune
   carte : la revue se lit dans le pied, sous la scène, comme le reste. */
${R} .jf-review{display:flex;flex-direction:column;gap:8px;width:min(560px,92vw);
  text-align:left;font-family:var(--jf-sans)}
${R} .jf-review h3{margin:0;font-size:11px;font-weight:500;letter-spacing:.18em;
  text-transform:uppercase;color:var(--jf-muted)}
${R} .jf-review ul{margin:0;padding:0;list-style:none;font-size:14px}
${R} .jf-review li{display:flex;justify-content:space-between;gap:18px;padding:6px 2px;
  border-bottom:1px solid rgba(255,255,255,.07)}
${R} .jf-review li span{color:var(--jf-soft)}
${R} .jf-review li b{font-weight:600;color:#e9f1fb;font-variant-numeric:tabular-nums;white-space:nowrap}
${R} .jf-review-attempt{font-size:12px;color:var(--jf-muted)}
/* L'assistant parle **à côté** des mesures, jamais à leur place : un filet
   d'accent à gauche, le mot « Assistant » avant, et une couleur plus douce que
   les valeurs mesurées. */
${R} .jf-review-agent,${R} .jf-review-hold{margin:0;padding:6px 0 6px 12px;font-size:14px;line-height:1.5;
  color:var(--jf-soft);border-left:2px solid color-mix(in srgb,var(--jf-accent) 55%,transparent)}
${R} .jf-review-agent b,${R} .jf-review-hold b{font-weight:600;color:#e9f1fb}
/* --------------------------------------------- la destination de 6C (S07 a.)
   Discontinu = annoncé, comme toutes les cibles de la calibration. La taille
   est celle de la fenêtre à déposer : « dedans » se voit d'un coup d'œil. */
${R} .jf-drop{position:fixed;z-index:2;pointer-events:none;box-sizing:border-box;
  border:2px dashed color-mix(in srgb,var(--jf-accent) 70%,transparent);border-radius:14px;
  background:rgba(110,231,255,.05);display:flex;align-items:flex-start;justify-content:center}
${R} .jf-drop span{margin-top:-22px;font-family:var(--jf-sans);font-size:11px;letter-spacing:.18em;
  text-transform:uppercase;color:var(--jf-accent)}
@media (max-width:720px){${R} .jf-review ul{font-size:13px}}
@media (max-height:560px){${R} .jf-review li{padding:3px 2px}${R} .jf-review{gap:4px}}`;

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
    /* `aside` : la démonstration se range dans un coin au lieu d'occuper le
       centre. Ce n'est pas un choix esthétique — l'étape de manipulation de
       fenêtre pose un vrai cadre au centre, et deux choses au même endroit
       n'en font voir aucune. */
    wrap.className=spec.aside?'jf-demo-wrap jf-demo-aside':'jf-demo-wrap';
    const box=doc.createElement('div');
    box.className=DEMO_CLASS;
    box.setAttribute('data-mime',spec.mime?'1':'0');
    /* **Côte à côte plutôt qu'empilées** (Slice 07). L'empilement est ce qui
       fait lire « deux doigts se ferment » au lieu de « deux mains
       différentes » ; pour une démonstration à deux mains c'est exactement
       l'erreur inverse qu'il faut éviter — deux mains empilées se liraient
       comme une seule qui bouge. */
    box.setAttribute('data-pair',spec.pair?'1':'0');
    box.setAttribute('data-demo',String(stepId));
    /* Annoncée **une fois**, sur le groupe : les postures empilées sont deux
       images du même fait, et deux `<title>` feraient lire le geste deux fois
       à un lecteur d'écran. Les SVG restent donc décoratifs (`handSvg` les pose
       `aria-hidden` quand on ne lui donne pas de `title`). */
    box.setAttribute('role','img');
    box.setAttribute('aria-label',spec.caption);
    spec.poses.forEach((key,index)=>{
      const pose=art.POSE[key];
      if(!pose)
        throw new RangeError(`La démonstration de l’étape ${stepId} demande la posture « ${key} », `
          +`que le vocabulaire de dessin ne publie pas. Postures connues : ${Object.keys(art.POSE).join(', ')}. `
          +'Une posture inconnue ne retombe pas sur la main au repos : un écran qui montre une main ouverte '
          +'là où on attend un pincement enseigne le mauvais geste.');
      /* `mirror` est une propriété du **dessin**, pas une posture de plus : la
         main gauche d'un pincement est le même pincement (invariant de
         `hand_art`). C'est pour cela que 6B n'a demandé aucune lettre nouvelle
         à l'alphabet. */
      box.appendChild(art.handSvg(doc,{pose,size:art.SIZE_DEFAULT*8,className:'bh-hand',
        mirror:!!(spec.mirror&&spec.mirror[index])}));
    });
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

  /* **Le rail des deux temps d'un écran** (Slice 07), et la consigne de celui
     qu'on joue.

     Même forme et même grammaire que `phaseStrip` — un seul allumé, ceux
     d'avant marqués faits — parce que c'est la même question posée à une autre
     échelle : « où en suis-je ? ». Deux grammaires pour une question se
     liraient comme deux questions.

     La consigne de la sous-étape vit **ici** et non dans le bandeau : le titre
     de l'écran reste « Manipulation de fenêtre » du début à la fin, et repasser
     par `overlay.step()` pour changer la phrase effacerait le cadre
     d'entraînement que l'utilisateur est en train de regarder. */
  function subStrip(doc,list){
    const box=doc.createElement('div');
    box.className='jf-subs';
    /* Annoncé : « on est passé au second temps » est une information, et elle
       n'existe qu'en pixels pour qui ne regarde pas l'écran. */
    box.setAttribute('aria-live','polite');
    const rail=doc.createElement('div');
    rail.className='jf-sub-rail';
    const chips=list.map(sub=>{
      const chip=doc.createElement('b');
      chip.textContent=sub.label;
      chip.setAttribute('data-sub',String(sub.id));
      chip.setAttribute('data-at','next');
      rail.appendChild(chip);
      return chip;
    });
    const line=doc.createElement('p');
    line.className='jf-sub-say';
    box.appendChild(rail);box.appendChild(line);
    return {node:box,set(index){
      chips.forEach((chip,at)=>chip.setAttribute('data-at',
        at<index?'done':at===index?'now':'next'));
      line.textContent=list[index]?list[index].instruction:'';
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
  /* **Ce que chaque étape réussie remplace** (décision 69, enregistrement
     fusionné). Une étape passée — bouton ou voix, quelle que soit la
     raison — ou échouée ne remplace rien : ses clés gardent la valeur
     enregistrée. La tolérance clic/glissement vient de la visée **et** du
     glissement ; la portée, de la visée ; la qualité accompagne une main
     dont au moins une mesure est remplacée (c'est la qualité de cette
     séance-là). */
  const STAGE_KEYS=Object.freeze({
    [BH.STAGE.NEUTRAL]:Object.freeze(['jitterPx']),
    [BH.STAGE.PINCH_PRIMARY]:Object.freeze(['pressRatio','releaseRatio']),
    [BH.STAGE.PINCH_SECONDARY]:Object.freeze(['secondaryPressRatio','secondaryReleaseRatio']),
  });
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
    /* **Le vrai détecteur de pincement, exigé** (Slice 02 adaptative). Les
       latences d'appui et de relâchement d'un épisode se lisent en rejouant
       le canal du moteur (`createPinchChannel`, avec les options que le moteur
       applique à cette main) sur les images de l'étape : une copie du
       détecteur ici mesurerait autre chose que ce que l'utilisateur vit. Le
       moteur est servi **après** ce module, d'où la couture plutôt qu'un
       global. `pinchChannel(channel, handedness)` rend un canal neuf. */
    if(typeof d.pinchChannel!=='function')
      throw new RangeError('createCalibration exige `pinchChannel(channel, handedness)` : la latence d’un pincement se mesure en rejouant le vrai détecteur, et sans lui chaque épisode dirait « appui manqué » à quelqu’un qui a pincé');
    /* **Le vrai guetteur de réveil, exigé** (Slice 03 adaptative). Un
       réveil non voulu se compte en rejouant le guetteur du moteur — avec ses
       options vivantes — sur la posture que la main a montrée pendant
       l'exercice négatif, à la cadence de la veille : une copie ici compterait
       autre chose que ce que la veille aurait fait. `wakeDetector()` rend un
       guetteur neuf. */
    if(typeof d.wakeDetector!=='function')
      throw new RangeError('createCalibration exige `wakeDetector()` : un réveil non voulu se compte en rejouant le vrai guetteur, et sans lui l’exercice « bouger sans cliquer » dirait « aucun réveil » sans l’avoir mesuré');
    const o=options(d.options);
    const band=wakeBandOf(d.engineDefaults);
    /* La cadence du guetteur de veille : le rejeu l'échantillonne comme lui. */
    const wakeIntervalMs=Math.max(0,Number(d.engineDefaults&&d.engineDefaults.wakeIntervalMs)||0);
    const lostGraceMs=Number(d.engineDefaults&&d.engineDefaults.lostGraceMs);
    const now=typeof d.now==='function'?d.now:()=>Date.now();
    const viewport=typeof d.viewport==='function'?d.viewport:()=>({width:1280,height:720});
    const say=typeof d.log==='function'?d.log:()=>{};
    /* **Le banc d'entraînement de l'étape 6** (Slice 07, décisions 29 et 30).

       Quatre portes, pas une de plus : l'échelle de la scène, l'ouverture du
       cadre dans une région de la coque, le journal de ce que le **vrai**
       moteur en a fait, et le démontage. Ce module ne calcule donc aucune
       géométrie de cadre et n'en dessine aucun — il dit *où* et *quand*, la
       page dit *quoi*. C'est le partage de l'observation du tutoriel
       (Slice 10), et il a la même raison d'être : un parcours qui irait
       chercher `JarvisScene` et la façade du moteur dans des globaux ne se
       testerait plus sous node.

       **Optionnel, et son absence est nommée.** Une calibration construite
       sans banc n'invente pas de cadre : elle passe l'étape avec
       `STAGE_REASON.SCENE_UNAVAILABLE`, exactement comme quand la scène est
       éteinte. Les deux cas disent la même chose à l'utilisateur — « il n'y
       avait pas de vraie fenêtre à manipuler » — et aucun des deux ne lui fait
       jouer un faux exercice. C'est pour cela que ce dep-là n'est pas refusé à
       la construction alors que la coque, l'horloge, le `document` et le
       vocabulaire de dessin le sont : les quatre autres manquent **toujours**
       ou **jamais**, celui-ci manque à l'exécution, sur la machine de
       l'utilisateur, et un refus de construction ferait alors disparaître les
       cinq étapes qui, elles, n'ont besoin de rien. */
    const PRACTICE_DOORS=['viewport','open','drain','close'];
    const practice=d.practice&&typeof d.practice==='object'
      &&PRACTICE_DOORS.every(door=>typeof d.practice[door]==='function')?d.practice:null;
    /* **Le banc de sélection de l'étape de visée** (Slice 05 adaptative,
       décision 49). Optionnel pour la même raison que le banc
       d'entraînement : sans lui, l'étape de visée joue ses points d'avant
       (dessinés par la coque, jugés à `aimHitPx`) — rien d'inventé. Avec lui,
       elle joue de vraies étoiles que le vrai résolveur présélectionne. Trois
       portes : poser une manche, lire ce que le résolveur en a fait, démonter. */
    const SELECTION_DOORS=['open','drain','close'];
    const selection=d.selection&&typeof d.selection==='object'
      &&SELECTION_DOORS.every(door=>typeof d.selection[door]==='function')?d.selection:null;

    let running=false,at=-1,collected=null,reports=null,derived=null,finished=null;
    let repeats=0,aimAt=null,pressFrom=null,clickTravels=null,dragTravels=null;
    let secondHandSeen=false,holdFrom=null;
    /* L'étape de pincement redemande un geste tant qu'il manque des épisodes
       complets (`pinchEpisodesMin`) : `pinchTarget` est le nombre de
       répétitions demandées **maintenant**, `settleFrom` l'instant où il a été
       atteint (la queue `pinchSettleMs` court de là). */
    let pinchTarget=0,settleFrom=null;
    /* « Tenir puis relâcher » : les pincements **tenus** demandés maintenant
       (redemandés comme pour un pincement, s'il en manque à la mesure). */
    let holdTarget=0;
    /* 6C : la destination à l'écran (`{x, y, width, height}`, pixels de la
       fenêtre), son nœud, et le compte des lâchers. */
    let dropSpot=null,dropNode=null,dropStats=null;
    /* Les images de l'étape de pincement **avant** l'armement, bornées à
       `pinchLookbackMs` : l'armement les lit (zigzag), puis elles amorcent le
       flux de l'étape pour que le pincement qui arme soit un épisode complet. */
    let armedStream=[];
    /* Depuis quand l'essai en attente est trop timide (`pinchShallow`), à
       l'horloge du parcours ; `null` sinon. */
    let shallowSince=null;
    /* **La séance** (décisions 34, 35, 38 et 41) : les épisodes mesurés, leur
       jeu de mesures et l'historique des événements de séance. En mémoire de
       la page, le temps d'un parcours, effacée à `stop()` — jamais postée. */
    let session=null;
    function openSession(){
      /* L'enregistreur est servi **après** ce module : il se lit à l'appel,
         comme le vocabulaire de dessin. Absent, les épisodes et leurs mesures
         restent, seul l'historique d'événements manque — et le journal le
         dit. */
      const recorder=root.JarvisBarehandsRecorder
        ||(typeof JarvisBarehandsRecorder!=='undefined'?JarvisBarehandsRecorder:null);
      if(!recorder)say('warn','[barehands] calibration.session_history_unavailable',
        {error:'l’enregistreur Bare Hands n’est pas chargé : pas d’historique d’événements de séance'});
      /* **Une seule horloge de séance** (Slice 07 adaptative, décision 58 —
         report des Slices 03 et 06). Les images sont datées par l'horloge du
         **moteur** ; les retours, les essais et les revues par celle de la
         **page** (`now()`). Mélanger les deux rendait l'historique
         incohérent : un retour pouvait se lire avant l'épisode qu'il
         commentait. Tout se date donc en ms depuis `clockOrigin` (horloge de
         la page, à l'ouverture de la séance) ; un instant d'image s'y convertit
         par le décalage **mesuré** entre les deux horloges à chaque image
         (`offset` = `now()` − temps de l'image, reposé à chaque `feed`). La
         séance de l'agent lit la même origine, donc ses `t` et ses
         `appliedAt` sont sur cette horloge-là. */
      session={clockOrigin:now(),offset:null,episodes:[],measurements:{},falseEvents:[],
        /* Les décisions de revue (décision 56), dans l'ordre. */
        reviews:[],
        /* Les références de mesure de la **dernière tentative** de chaque
           étape : ce que sa revue affiche. Remises à zéro quand l'étape
           repart en mesure ; l'historique, lui, garde tout. */
        attemptRefs:Object.create(null),
        /* Ce que chaque ligne du jeu de mesures **était** (Slice 06
           adaptative, décision 52) : l'étape, l'exercice, l'essai sous lequel
           elle a été prise, et quand. C'est ce qui permet au code — pas à
           l'agent — de dire qu'une mesure citée « après » a bien été prise
           sous l'essai jugé. */
        rowMeta:Object.create(null),
        history:recorder?recorder.createSessionHistory():null,recorder,
        nextEpisode:1,nextSample:1,nextExercise:1,nextNegative:1};
    }
    /* L'essai en cours, lu chez la page (`deps.trialRef`), ou `null`. Une
       lecture qui lève ou rend autre chose qu'une référence `tr-N` vaut
       « aucun essai » et se dit : une ligne mal rangée ne doit pas passer pour
       une mesure prise sous un essai. */
    function trialNow(){
      if(typeof d.trialRef!=='function')return null;
      try{
        const ref=d.trialRef();
        if(ref===null||ref===undefined)return null;
        if(BH.isSessionRef(ref,[BH.SESSION_REF.TRIAL]))return ref;
        say('warn','[barehands] calibration.trial_ref_invalid',{ref:String(ref).slice(0,20)});
      }catch(error){
        say('warn','[barehands] calibration.trial_ref_unreadable',{error:String(error&&error.message||error)});
      }
      return null;
    }
    /* **L'état effectif sous lequel la ligne a été prise** (`deps.stateRef`,
       reprise QA réelle, round 5) : un numéro que la séance de l'agent change à
       chaque essai appliqué ou défait, et garde à l'acceptation (l'effectif ne
       change pas). « Avant » un essai = prises sous l'état sur lequel il a été
       appliqué, « après » = sous l'essai — y compris après un essai gardé. */
    function stateNow(){
      if(typeof d.stateRef!=='function')return null;
      try{const v=d.stateRef();return Number.isInteger(v)&&v>=0?v:null}
      catch(error){say('warn','[barehands] calibration.state_ref_unreadable',{error:String(error&&error.message||error)});return null}
    }
    function noteRow(ref,stage,exerciseRef,trialRef){
      if(!session)return;
      session.rowMeta[ref]=Object.freeze({stage:stage||null,exerciseRef:exerciseRef||null,
        trialRef:trialRef||null,stateId:stateNow(),at:now(),t:pageT()});
      if(stage)(session.attemptRefs[stage]||(session.attemptRefs[stage]=[])).push(ref);
    }
    /* Les deux conversions vers l'horloge de séance (décision 58). */
    function pageT(){return session?Math.max(0,now()-session.clockOrigin):0}
    function frameT(at){
      if(!session)return 0;
      const offset=session.offset===null?now()-at:session.offset;
      return Math.max(0,at+offset-session.clockOrigin);
    }
    /* Le décalage entre l'horloge des images et celle de la page, lu à
       l'instant où une image arrive (elle est traitée dans la même pile). */
    function syncClock(at){
      if(session&&Number.isFinite(at))session.offset=now()-at;
    }
    /* Un échantillon de séance (événement), daté en ms de séance, rangé dans
       l'historique ; rend sa référence `se-N`, ou `null` sans historique.
       `at` : instant d'**image** (horloge du moteur), converti. */
    function pushEvent(at,event,where){
      return pushSample(frameT(at),event,where);
    }
    function pushSample(t,event,where){
      if(!session||!session.history)return null;
      const ref=`${BH.SESSION_REF.SAMPLE}-${session.nextSample++}`;
      session.history.push(session.recorder.readSessionSample({
        ref,t,
        stage:where&&where.stage||null,exerciseRef:where&&where.exerciseRef||null,
        trialRef:where&&where.trialRef||null,
        event}));
      return ref;
    }
    /* Un épisode entre dans la séance : sa ligne du jeu de mesures, et ses
       deux événements (`pinch_press`, `pinch_release`) datés en ms de séance,
       qui portent la latence et désignent l'épisode. Pas d'événement pour ce
       que le détecteur n'a pas tranché : un appui manqué se lit sur
       l'épisode (`pressLatencyMs: null`), il ne s'invente pas un instant. */
    function recordEpisode(ep){
      session.episodes.push(ep);
      session.measurements[ep.ref]=episodeMeasures(ep,o);
      noteRow(ep.ref,ep.stage,ep.exerciseRef,ep.trialRef);
      if(!session.history)return;
      const minimumT=ep.startT+ep.closingMs,openingT=minimumT+ep.minimumMs;
      const push=(kind,at,latencyMs)=>session.history.push(session.recorder.readSessionSample({
        ref:`se-${session.nextSample++}`,t:frameT(at),stage:ep.stage,
        exerciseRef:ep.exerciseRef,trialRef:ep.trialRef,
        event:{kind,channel:ep.channel,latencyMs,ref:ep.ref}}));
      if(ep.pressLatencyMs!==null)push(BH.SESSION_EVENT.PINCH_PRESS,minimumT+ep.pressLatencyMs,ep.pressLatencyMs);
      if(ep.releaseLatencyMs!==null)push(BH.SESSION_EVENT.PINCH_RELEASE,openingT+ep.releaseLatencyMs,ep.releaseLatencyMs);
    }
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
    /* **L'écran de manipulation et ses deux temps** (Slice 07). `subAt` dit
       lequel est joué, `subs` est son rail à l'écran, `practiceOn` dit si un
       cadre d'entraînement est **branché au moteur** — donc s'il y a quelque
       chose à démonter.

       `holdingFrame` et `frameDone` sont les deux seuls faits que ce module
       retient du vrai moteur : « une main tient le cadre » (l'engagement, donc
       l'armement) et « une main vient de le relâcher en l'ayant changé » (le
       geste, donc le verdict). Ni l'un ni l'autre n'est calculé ici. */
    let subAt=0,subs=null,practiceOn=false,holdingFrame=false,frameDone=null;

    /* **L'exercice négatif en cours** (Slice 03 adaptative, décision 47),
       ouvert à l'entrée en mesure d'un temps négatif et refermé à son verdict.
       Il ne dérive **aucun** seuil : il compte, par main, les décisions du
       vrai moteur qui n'auraient pas dû arriver, et le temps d'exposition qui
       en fait des taux. `null` partout ailleurs, donc rien ne se compte hors
       de lui. */
    let negative=null;
    /* **L'exercice de sélection en cours** (décision 49) : `{exercise,
       exerciseRef}`, ouvert à la fin de la lecture de l'étape de visée quand
       un banc de sélection existe, refermé à son verdict. `null` partout
       ailleurs. */
    let sel=null;
    const F=BH.FALSE_EVENT;
    /* Ce qui est faux dans chaque temps. En 7B le curseur est **voulu** (on
       vise) et la posture de visée est celle du réveil : ni l'un ni l'autre
       n'y est une faute. */
    const NEGATIVE_WATCH=Object.freeze({
      [BH.STAGE.NATURAL_MOTION]:Object.freeze([F.FALSE_PRESS,F.FALSE_SECONDARY_PRESS,
        F.UNINTENDED_WAKE,F.UNINTENDED_TARGET,F.UNINTENDED_POINTER]),
      [BH.STAGE.AIM_NO_CLICK]:Object.freeze([F.FALSE_PRESS,F.FALSE_SECONDARY_PRESS,F.UNINTENDED_TARGET]),
    });
    /* Chaque faux événement a sa métrique de taux (`CALIBRATION_METRIC`). */
    const FALSE_METRIC=Object.freeze({
      [F.FALSE_PRESS]:'false_press_rate',[F.FALSE_SECONDARY_PRESS]:'false_secondary_press_rate',
      [F.UNINTENDED_WAKE]:'unintended_wake_rate',[F.UNINTENDED_TARGET]:'unintended_target_rate',
      [F.UNINTENDED_POINTER]:'unintended_pointer_rate',
    });
    /* Ce que l'écran et le rapport disent d'un compte, en français. */
    const FALSE_WORDS=Object.freeze({
      [F.FALSE_PRESS]:'faux appui(s)',[F.FALSE_SECONDARY_PRESS]:'faux clic(s) droit(s)',
      [F.UNINTENDED_WAKE]:'réveil(s) non voulu(s)',[F.UNINTENDED_TARGET]:'cible(s) prise(s) sans le vouloir',
      [F.UNINTENDED_POINTER]:'curseur(s) affiché(s) sans visée',
    });
    const isNegative=step=>!!step&&Object.prototype.hasOwnProperty.call(NEGATIVE_WATCH,step.id);
    function openNegative(step){
      const counts={};
      for(const kind of NEGATIVE_WATCH[step.id])counts[kind]=0;
      negative={stage:step.id,
        exerciseRef:`${BH.SESSION_REF.EXERCISE}-${session?session.nextExercise++:1}`,
        exposureMs:0,lastT:null,counts,prev:new Map(),wake:new Map(),dwellFrom:null};
    }
    /* Un faux événement : l'échantillon de séance qui le montre (déjà rangé,
       ou rangé ici), la forme du contrat (`createFalseEvent`), et sa marque
       `false_event` dans l'historique. Rien d'autre ne le porte. */
    function recordFalse(kind,at,shown){
      const where={stage:negative.stage,exerciseRef:negative.exerciseRef};
      const sampleRef=typeof shown==='string'||shown===null?shown:pushEvent(at,shown,where);
      const ref=`${BH.SESSION_REF.NEGATIVE}-${session.nextNegative++}`;
      session.falseEvents.push(BH.createFalseEvent({schemaVersion:BH.SESSION_SCHEMA_VERSION,
        kind:'false_event',ref,falseKind:kind,t:frameT(at),
        stage:negative.stage,exerciseRef:negative.exerciseRef,sampleRef}));
      pushEvent(at,{kind:BH.SESSION_EVENT.FALSE_EVENT,falseKind:kind,ref},where);
      negative.counts[kind]+=1;
    }
    /* Une image d'exemple négatif. Les fronts se lisent **par main** sur ce
       que le moteur a décidé (`pressed`, `secondaryPressed`, `targeted`,
       publiés par la couture de mesure), sur toutes les mains vues — le
       moteur les lit toutes, qualité basse comprise. L'exposition, elle, ne
       court que devant une main sûre. Le réveil se rejoue sur le vrai guetteur,
       à sa cadence, sur les mains qu'il aurait crues. */
    function watchNegative(seen,trusted,time){
      const n=negative;
      if(trusted.length){
        if(n.lastT!==null){const dt=time-n.lastT;if(dt>0&&dt<=o.negativeGapMs)n.exposureMs+=dt}
        n.lastT=time;
      }else n.lastT=null;
      const counted=NEGATIVE_WATCH[n.stage];
      const floor=Number(d.engineDefaults&&d.engineDefaults.qualityFloor)||0;
      for(const hand of seen){
        const key=String(hand.handTrackId);
        const was=n.prev.get(key)||{pressed:false,secondaryPressed:false,targeted:false};
        const is={pressed:hand.pressed===true,secondaryPressed:hand.secondaryPressed===true,targeted:hand.targeted===true};
        n.prev.set(key,is);
        if(is.pressed&&!was.pressed&&counted.includes(F.FALSE_PRESS))
          recordFalse(F.FALSE_PRESS,time,{kind:BH.SESSION_EVENT.PINCH_PRESS,channel:BH.PINCH_CHANNEL.PRIMARY});
        if(is.secondaryPressed&&!was.secondaryPressed&&counted.includes(F.FALSE_SECONDARY_PRESS))
          recordFalse(F.FALSE_SECONDARY_PRESS,time,{kind:BH.SESSION_EVENT.PINCH_PRESS,channel:BH.PINCH_CHANNEL.SECONDARY});
        if(is.targeted&&!was.targeted&&counted.includes(F.UNINTENDED_TARGET))
          recordFalse(F.UNINTENDED_TARGET,time,{kind:BH.SESSION_EVENT.TARGET_CHANGED});
        if(!counted.includes(F.UNINTENDED_WAKE))continue;
        let w=n.wake.get(key);
        if(!w){w={detector:d.wakeDetector(),at:-Infinity};n.wake.set(key,w)}
        if(time-w.at<wakeIntervalMs)continue;
        w.at=time;
        /* La posture **du réveil** (`wakePose` : le C composé du repli des
           trois autres doigts), celle que la veille tiendrait. */
        const pose=Number(hand.wakePose);
        const believed=Number(hand.quality)>=floor&&hand.wakePose!==null&&hand.wakePose!==undefined&&Number.isFinite(pose);
        const out=w.detector.update(believed?pose:null,time);
        if(out&&out.wake)recordFalse(F.UNINTENDED_WAKE,time,{kind:BH.SESSION_EVENT.WAKE_CONFIRMED,
          score:Math.max(0,Math.min(1,pose))});
      }
    }
    const falseTotal=n=>NEGATIVE_WATCH[n.stage].reduce((sum,kind)=>sum+n.counts[kind],0);
    const falseSummary=n=>NEGATIVE_WATCH[n.stage].filter(kind=>n.counts[kind])
      .map(kind=>`${n.counts[kind]} ${FALSE_WORDS[kind]}`).join(', ');
    /* Le verdict d'un temps négatif : un **taux** par minute d'exposition pour
       chaque faux événement surveillé (`createMeasurementSet`, sous la
       référence de l'exercice), rangé dans la séance ; le compte en clair dans
       le rapport et le journal. Des faux événements ne sont pas un échec de
       l'étape — ils **sont** sa mesure. */
    function finishNegative(step){
      const n=negative;
      const minutes=n.exposureMs/60000;
      const row={};
      for(const kind of NEGATIVE_WATCH[n.stage])row[FALSE_METRIC[kind]]=minutes>0?n.counts[kind]/minutes:null;
      session.measurements[n.exerciseRef]=row;
      noteRow(n.exerciseRef,n.stage,n.exerciseRef,trialNow());
      const total=falseTotal(n),summary=falseSummary(n);
      const aimed=n.stage===BH.STAGE.AIM_NO_CLICK&&aimPoints?` ; points visés : ${aimHits} sur ${aimPoints.length}`:'';
      stageNotes[step.id]={unit:'s d’exposition',warnings:[],
        detail:(total?summary:'aucun faux déclenchement')+aimed};
      say('info','[barehands] calibration.negatives',{stage:n.stage,exerciseRef:n.exerciseRef,
        exposureMs:Math.round(n.exposureMs),counts:{...n.counts},rates:row});
      negative=null;
      settle(BH.STAGE_STATUS.OK,null,Math.round(n.exposureMs/1000),{exposureMs:n.exposureMs,counts:n.counts},
        total?summary:undefined);
    }
    /* Ce que l'écran dit pendant un temps négatif, et quand il se solde. */
    function paintNegative(step,trusted,time){
      const n=negative;
      const total=falseTotal(n);
      const tally=total?`Déclenché sans le vouloir : ${falseSummary(n)}.`:'Rien ne s’est déclenché.';
      if(n.stage===BH.STAGE.NATURAL_MOTION){
        if(n.exposureMs>=o.negativeMs){finishNegative(step);return}
        overlay.progress(n.exposureMs/o.negativeMs);
        overlay.note(!trusted.length?'Aucune main sûre n’est vue : bougez devant la caméra.'
          :`Bougez librement : ${Math.floor(n.exposureMs/1000)} s sur ${Math.round(o.negativeMs/1000)}. ${tally}`,
          total?'bad':'');
        return;
      }
      /* La main **qui vise** : la première main sûre dont le jeton est à
         l'écran, pas simplement la première vue — une seconde main posée au
         repos ne doit pas cacher celle qui vise (reprise QA). */
      const first=trusted.find(hand=>hand.pointerShown!==false)||trusted[0];
      const shown=!!first&&first.pointerShown!==false;
      if(first&&shown&&first.pressed!==true&&onAimPoint(first)){
        if(n.dwellFrom===null)n.dwellFrom=time;
        if(time-n.dwellFrom>=o.negativeDwellMs){
          n.dwellFrom=null;
          aimHits+=1;
          if(!aimPoints||aimHits>=aimPoints.length){finishNegative(step);return}
          aimIndex=aimHits;
          if(ghosts)ghosts.set(aimIndex,aimHits);
          overlay.target(aimPoints[aimIndex]);
          overlay.flash(420);
        }
      }else n.dwellFrom=null;
      const count=aimPoints?aimPoints.length:1;
      const dwell=n.dwellFrom===null?0:Math.min(1,(time-n.dwellFrom)/o.negativeDwellMs);
      overlay.progress((aimHits+dwell)/count);
      overlay.note(!first?'Aucune main sûre n’est vue : montrez une main à la caméra.'
        :!shown?'Le jeton est caché : formez le C — pouce et index écartés, index tendu — pour viser.'
        :`Point ${Math.min(aimHits+1,count)} sur ${count} : posez le jeton dessus et restez-y, sans pincer. ${tally}`,
        total?'bad':'');
    }

    /* ---- Exercice de sélection (décision 49). */
    const selectionFor=step=>!!selection&&!!step&&step.id===BH.STAGE.AIM;
    function openSelectionRound(){
      if(!sel)return false;
      const region=overlay.regions();
      if(!region||!region.exercise)return false;
      let opened=null;
      try{opened=selection.open(region.exercise,selectionStars(sel.exercise.index(),viewport()))}
      catch(error){say('warn','[barehands] banc de sélection non ouvert',error);return false}
      if(!opened)return false;
      sel.exercise.open(opened.openedAt);
      return true;
    }
    /* À la fin de la lecture. Si le banc ne peut pas poser d'étoiles (coque
       sans région), l'étape joue ses points d'avant plutôt que de rester
       vide : c'est la même étape, mesurée comme avant. */
    function startSelection(){
      if(sel)return true;
      sel={exercise:createSelectionExercise({attemptsMax:o.selectionAttemptsMax}),
        exerciseRef:`${BH.SESSION_REF.EXERCISE}-${session?session.nextExercise++:1}`};
      if(openSelectionRound()){
        say('info','[barehands] calibration.selection_open',{exerciseRef:sel.exerciseRef,rounds:SELECTION_ROUNDS.length});
        return true;
      }
      say('warn','[barehands] calibration.selection_unavailable',
        {error:'le banc de sélection n’a pas pu poser ses étoiles : l’étape de visée joue ses points'});
      sel=null;
      aimPoints=aimField();aimHits=0;aimIndex=0;
      overlay.clear('exercise');
      ghosts=ghostField(doc,aimPoints);
      overlay.mount('exercise',ghosts.node);
      return false;
    }
    function closeSelection(){
      if(!selection)return false;
      try{return selection.close()}
      catch(error){say('warn','[barehands] banc de sélection non démonté',error);return false}
    }
    function pumpSelection(){
      if(!sel)return;
      let facts=[];
      try{facts=selection.drain()||[]}
      catch(error){say('warn','[barehands] banc de sélection illisible',error);return}
      for(const fact of facts)sel.exercise.fact(fact);
    }
    const plural=(n,one,many)=>`${n} ${n>1?many:one}`;
    /* Le verdict de l'exercice : sa ligne de mesures sous la référence
       d'exercice (`ex-N`), le journal, et une phrase lisible pour le rapport.
       Rend `null` s'il n'y avait pas d'exercice. */
    function finishSelection(step){
      if(!sel)return null;
      const current=sel;sel=null;
      closeSelection();
      const row=current.exercise.row(),sum=current.exercise.summary();
      if(session){
        session.measurements[current.exerciseRef]=row;
        noteRow(current.exerciseRef,BH.STAGE.AIM,current.exerciseRef,trialNow());
      }
      const amb=row.target_ambiguity===null?'':`, ambiguïté moyenne ${row.target_ambiguity.toFixed(2).replace('.',',')}`;
      const detail=`${sum.hits} étoile(s) prise(s) sur ${sum.rounds} ; `
        +`${plural(sum.wrong,'mauvaise étoile','mauvaises étoiles')}, `
        +`${plural(sum.missed,'pincement dans le vide','pincements dans le vide')}, `
        +`${plural(sum.switches,'bascule entre voisines','bascules entre voisines')}${amb}`;
      if(step)stageNotes[step.id]={unit:'image(s)',warnings:[],detail};
      say('info','[barehands] calibration.selection',{exerciseRef:current.exerciseRef,summary:sum,row});
      return {row,summary:sum,detail};
    }

    const stepAt=index=>STEPS[index]||null;
    /* **L'étape mesurée** courante, qui n'est pas toujours l'écran courant. Un
       écran peut en porter deux (la manipulation de fenêtre) ; c'est elle, et
       non l'écran, qui porte une identité persistée, une exigence de mains, un
       verdict et une ligne de rapport. Partout ailleurs ici, « étape » veut
       dire ceci. */
    const stageOf=(step,index)=>!step?null:(step.subs?step.subs[index]||null:step);
    const stage=()=>stageOf(stepAt(at),subAt);
    /* Toutes les étapes mesurées, écrans dépliés — le vocabulaire persisté, qui
       compte sept entrées quand les écrans d'exercice n'en comptent que six. */
    const STAGES=Object.freeze(STEPS.reduce((list,step)=>
      list.concat(step.subs?[...step.subs]:[step]),[]));
    const blank=()=>({samples:[],xs:[],ys:[],stream:[]});

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
      /* Les pincements n'ont **pas** de prédicat d'une image : ils s'arment
         sur l'historique récent (`pinchEngaged`, la règle du segmenteur), pas
         sur un franchissement du relâchement d'usine — une main ouverte à 0,38
         était « armée » au repos et ne comptait jamais un pincement. */
      /* La visée et le glissement démarrent sur le **pincement primaire**, qui
         est le geste que la cible existe pour provoquer (décision 28 : on pince
         la cible, on ne la pointe pas). */
      [BH.STAGE.AIM]:(hand,wake)=>Number.isFinite(hand.primaryRatio)
        &&hand.primaryRatio<wake.releaseRatio,
      /* **Les deux sous-étapes de la fenêtre n'ont pas de prédicat de
         scalaires, et c'est un progrès** (Slice 07, décision 25).

         Les cinq autres lisent des nombres que le contrôleur publie déjà, et
         c'est le mieux qu'elles puissent faire : « la main est posée »,
         « l'écart entre dans la bande », « le canal s'est fermé » sont des
         approximations de l'engagement. Celles-ci lisent une **vraie
         capture** : le moteur d'interaction n'ouvre un plan sur le cadre
         d'entraînement que lorsqu'une main a réellement pincé un bord ou un
         coin **et** commencé à tirer (`dragSlopPx`, mesuré sur la paume). Ce
         n'est pas un signe d'engagement, c'est l'engagement lui-même — donc il
         n'y a rien à deviner, et aucun seuil de plus à poser.

         Le fait arrive par `practice.drain()`, pas par les scalaires : il n'y a
         donc pas d'entrée ici, et `feed()` ne cherche pas de prédicat pour ces
         deux-là. Une entrée qui rendrait `true` les armerait sur une main qui
         passe devant l'objectif ; une entrée qui rendrait `false` les rendrait
         injoignables. L'absence est la bonne réponse, et elle est écrite. */
      /* **Les temps négatifs** (Slice 03 adaptative). 7A s'arme sur une main
         sûre devant la caméra, rien de plus : exiger un geste reviendrait à
         demander le contraire de ce qu'on mesure. 7B s'arme quand le jeton
         est **à l'écran** (`pointerShown`, décision 46) — viser sans voir le
         jeton n'est pas viser. */
      [BH.STAGE.NATURAL_MOTION]:()=>true,
      [BH.STAGE.AIM_NO_CLICK]:(hand,wake,all)=>(all||[hand]).some(one=>one.pointerShown!==false),
    });
    /* **Une seule main suffit à armer 6B, alors qu'elle en demande deux**, et
       c'est la règle que l'ancienne étape « Deux mains » avait déjà raison de
       suivre : exiger les deux pour *commencer* rendrait `NEEDS_TWO_HANDS`
       injoignable dans le seul scénario qui porte son nom — l'étape resterait
       armée pour toujours au lieu de dire ce qui manque. On arme sur
       l'engagement, on mesure sur l'exigence, et l'échec explique. Ici,
       l'engagement est le même pour les deux temps : une prise réelle. */

    /* Ce qu'il y a à faire pour démarrer, dit en français. La phrase de
       `ARMED` est la moitié « quoi » de la RÈGLE ZÉRO quand il n'y a pas
       d'échéance à annoncer ; l'autre moitié est le bandeau de phases. */
    /* Ce qu'un pincement franc demande, dit quand l'essai est trop timide. */
    const SHALLOW=Object.freeze({
      [BH.STAGE.PINCH_PRIMARY]:'amenez le pouce au contact de l’index, puis rouvrez grand',
      [BH.STAGE.PINCH_SECONDARY]:'amenez le pouce au contact du majeur, puis rouvrez grand',
      [BH.STAGE.HOLD_RELEASE]:'amenez le pouce au contact de l’index, gardez-les fermés, puis rouvrez grand',
    });
    const START=Object.freeze({
      [BH.STAGE.NEUTRAL]:'posez une main ouverte devant la caméra et ne bougez plus',
      [BH.STAGE.C_POSE]:'formez le C avec le pouce et l’index',
      [BH.STAGE.PINCH_PRIMARY]:'pincez pouce et index',
      [BH.STAGE.PINCH_SECONDARY]:'pincez pouce et majeur',
      [BH.STAGE.AIM]:'formez le C pour faire apparaître le jeton, amenez-le sur le point, puis pincez pouce et index',
      [BH.STAGE.DRAG]:'pincez un bord ou un coin de la fenêtre, puis tirez',
      [BH.STAGE.RESIZE]:'pincez la fenêtre des deux mains, une de chaque côté',
      [BH.STAGE.NATURAL_MOTION]:'bougez les mains naturellement devant la caméra, sans viser ni pincer',
      [BH.STAGE.AIM_NO_CLICK]:'formez le C pour faire apparaître le jeton, puis posez-le sur le point sans pincer',
      [BH.STAGE.HOLD_RELEASE]:'pincez pouce et index, gardez les doigts fermés une seconde, puis rouvrez',
      [BH.STAGE.DROP]:'attrapez la fenêtre et portez-la dans le cadre en pointillé',
    });

    /* Une étape se solde une fois, et une seule. `skipped` n'est pas `failed` :
       ce que l'utilisateur n'a pas joué ne lui reproche rien.

       **Après le verdict vient la revue** (Slice 07 adaptative, décision 56) :
       le parcours ne passe plus à l'étape suivante au bout de `resultMs`, il
       s'arrête et attend une décision. La phrase du verdict reste donc à
       l'écran aussi longtemps que la revue — plus besoin de la « porter »
       dans l'étape suivante. `carry` ne sert plus qu'à une chose : quand
       l'utilisateur **passe** une étape ratée, la lecture de la suivante
       rappelle que Bare Hands garde ses valeurs d'usine pour elle
       (décision 31). */
    let carry=null;
    let lastPlayed=null;
    /* Le nombre de tentatives de chaque étape mesurée (une par verdict) : la
       revue dit « essai n° 2 », le rapport « 3 essais ». */
    let attempts=Object.create(null);
    /* La revue en cours : `{stage, status}` ; `null` hors revue. */
    let reviewing=null,reviewNode=null;
    /* Les ressentis d'« Ajuster » sont ouverts (Échap les referme). */
    let adjusting=false;
    /* Échap sur l'état de base : une première pression arme la sortie et le
       dit ; une seconde dans `ESCAPE_CONFIRM_MS` quitte. */
    let escapeArmedAt=null;
    const ESCAPE_CONFIRM_MS=2000;
    /* Le détour d'un « Refaire » vers une étape déjà franchie : où revenir
       après l'avoir validée ou passée, au lieu de rejouer tout ce qui suit. */
    let detour=null;
    function settle(status,reason,samples,detail,message,opts){
      /* **L'étape mesurée, pas l'écran** (Slice 07) : sur l'écran de
         manipulation, c'est 6A ou 6B qui se solde, et chacune porte sa propre
         ligne de rapport. Le nom dit à l'utilisateur ce qu'il vient de jouer —
         « 6A · Déplacer », pas « Manipulation de fenêtre », qui serait vrai
         deux fois de suite et n'apprendrait rien. */
      const step=stage();
      /* Une seule fois. « Passer cette étape » reste cliquable pendant la tenue
         du verdict — la sortie ne se retire jamais, RÈGLE ZÉRO — mais il ne
         doit pas réécrire un résultat déjà rendu. */
      if(!step||settled)return;
      settled=true;
      /* L'exercice qu'on vient de **jouer** : c'est lui que « refais-le »
         désigne, même quand le parcours a déjà ouvert la lecture du suivant
         (Slice 06 adaptative). */
      lastPlayed={at,subAt};
      attempts[step.id]=(attempts[step.id]||0)+1;
      const name=step.label||step.title;
      reports[step.id]={status,reason:reason||null,samples:Math.max(0,Math.round(samples||0))};
      if(detail)say('info',`[barehands] calibration ${step.id} : ${status}`,detail);
      const failed=status===BH.STAGE_STATUS.FAILED;
      const text=failed
        ?`${name} : ${message||LABEL[reason]||'mesure impossible'}. Rien n’est retenu de cet essai : refaites l’exercice, ou passez-le en disant pourquoi.`
        :status===BH.STAGE_STATUS.SKIPPED?`${name} : ${message||'étape passée, rien n’a été mesuré.'}`
        :message?`${name} : mesuré, mais ${message}.`:`${name} : mesuré.`;
      carry=null;
      if(status===BH.STAGE_STATUS.OK){
        /* **Le vert, bref, et seulement sur une réussite** (décision 21). La
           scène le porte, donc la main dessinée verdit avec elle sans une ligne
           de plus : les tracés de `hand_art` sont en `currentColor`. */
        overlay.flash(Math.min(o.resultMs,FLASH_MAX_MS));
        overlay.progress(1);
      }
      overlay.note(text,failed?'bad':status===BH.STAGE_STATUS.SKIPPED?'':'ok',o.resultMs);
      /* Un passage demandé par l'utilisateur ne se revoit pas : il vient de
         décider. Tout le reste s'arrête en revue (décision 56). */
      if(opts&&opts.review===false)return;
      enterReview();
    }

    /* ------------------------------------------------------------ la revue
       (Slice 07 adaptative, décision 56). Un état, pas une pause : on n'en
       sort que par une décision — Refaire, Valider l'étape, Passer (avec une
       raison), Quitter — venue d'un bouton **ou** de la voix, par les mêmes
       portes publiques (`rerun`, `validate`, `skip`, `next`). Ajuster n'en
       sort pas : il ouvre les ressentis, donc le chemin de l'assistant et de
       ses essais. */
    function reviewLines(stageId){
      const specs=REVIEW_LINES_ALL[stageId]||[];
      const refs=session?(session.attemptRefs[stageId]||[]):[];
      if(!specs.length||!refs.length)return [];
      const set=BH.createMeasurementSet(session.measurements);
      const has=(object,key)=>Object.prototype.hasOwnProperty.call(object,key);
      const out=[];
      for(const spec of specs){
        const cited=refs.filter(ref=>ref.startsWith(`${spec.from}-`)&&has(set,ref));
        if(!cited.length)continue;
        /* Une métrique absente de la ligne d'exercice (un temps qui ne la
           surveille pas) ne se montre pas ; présente mais nulle, elle se dit
           « non mesuré ». */
        if(spec.from==='ex'&&!cited.some(ref=>has(set[ref],spec.metric)))continue;
        const value=BH.aggregateMetric(spec.metric,spec.aggregate,cited,set);
        out.push(Object.freeze({metric:spec.metric,aggregate:spec.aggregate,refs:Object.freeze(cited.slice()),
          label:spec.label,value,text:formatMetric(spec.metric,spec.aggregate,value)}));
      }
      return out;
    }
    /* L'explication courte de l'assistant, lue chez la séance de l'agent
       (`deps.explanation(étape)`), ou `null`. Une lecture qui lève se dit et
       vaut « rien à dire ». */
    function explanation(stageId){
      if(typeof d.explanation!=='function')return null;
      try{const text=d.explanation(stageId);return typeof text==='string'&&text.trim()?text.trim().slice(0,240):null}
      catch(error){say('warn','[barehands] calibration.explanation_unreadable',{error:String(error&&error.message||error)});return null}
    }
    const el=(tag,cls,text)=>{const node=doc.createElement(tag);if(cls)node.className=cls;
      if(text!==undefined)node.textContent=text;return node};
    function paintReview(){
      if(!reviewing)return;
      const step=stage();
      if(!step)return;
      const report=reports[step.id]||{};
      if(reviewNode){overlay.unmountNode('feedback',reviewNode);reviewNode=null}
      const box=el('section','jf-review');
      box.setAttribute('aria-label','Revue de l’exercice');
      box.setAttribute('data-review',step.id);
      const tries=attempts[step.id]||1;
      box.appendChild(el('h3','',tries>1?`Ce qui a été mesuré — essai n° ${tries}`:'Ce qui a été mesuré'));
      const lines=reviewLines(step.id);
      if(lines.length){
        const list=el('ul');
        for(const item of lines){
          const li=el('li');
          li.setAttribute('data-metric',item.metric);
          li.setAttribute('data-aggregate',item.aggregate);
          li.setAttribute('data-refs',item.refs.join(','));
          li.setAttribute('data-value',item.value===null?'':String(item.value));
          li.appendChild(el('span','',item.label));li.appendChild(el('b','',item.text));
          list.appendChild(li);
        }
        box.appendChild(list);
      }else box.appendChild(el('p','jf-review-attempt',report.status===BH.STAGE_STATUS.OK
        ?'Cet exercice se juge sur le geste lui-même : il a abouti.':'Aucune mesure chiffrée pour cet essai.'));
      const said=explanation(step.id);
      if(said){
        const agent=el('p','jf-review-agent');
        agent.setAttribute('data-review-agent','1');
        agent.appendChild(el('b','','Assistant : '));agent.appendChild(el('span','',said));
        box.appendChild(agent);
      }
      const held=holdWanted(step);
      if(held)box.appendChild(el('p','jf-review-hold',
        'Un réglage d’essai attend d’être jugé sur cet exercice : refaites-le, ou dites ce que vous en pensez.'));
      reviewNode=overlay.mount('feedback',box);
      paintReviewButtons(step,report,held);
    }
    /* Le choix de la raison d'un passage (décision 57) : quatre raisons, un
       retour. Le même en revue et pendant un exercice. */
    let choosing=false;
    function paintChooser(){
      overlay.buttons([
        ...BH.SKIP_REASONS.map(reason=>({id:`skip-${reason}`,label:SKIP_TEXT[reason],run:()=>api.skip(reason)})),
        {id:'back',label:'Retour',run:()=>api.chooseSkip(false)},
      ],'Pourquoi passer cette étape ?');
    }
    /* Les commandes d'un exercice en cours (lecture, prêt, mesure). */
    function paintPlayButtons(){
      if(choosing){paintChooser();return}
      const screen=stepAt(at);
      overlay.buttons([
        {id:'skip',label:screen&&screen.subs?'Passer ce temps…':'Passer cette étape…',run:()=>api.chooseSkip(true)},
        {id:'exit',label:'Quitter',run:()=>cancel('bouton')},
      ],'Commandes de l’exercice');
    }
    /* « Ajuster » n'a de sens qu'avec un assistant à l'écoute : la page le dit
       (`deps.canAdjust()`, la séance de l'agent est ouverte). Un bouton qui
       n'ouvrirait rien serait un bouton mort. */
    function adjustable(){
      if(typeof d.adjust!=='function')return false;
      if(typeof d.canAdjust!=='function')return true;
      try{return !!d.canAdjust()}
      catch(error){say('warn','[barehands] calibration.adjust_unreadable',{error:String(error&&error.message||error)});return false}
    }
    const reviewPrimary=(report,held)=>report.status===BH.STAGE_STATUS.FAILED||held?'rerun':'validate';
    function paintReviewButtons(step,report,held){
      if(choosing){paintChooser();return}
      const failed=report.status===BH.STAGE_STATUS.FAILED;
      const list=[{id:'rerun',label:'Refaire',primary:failed||held,run:()=>api.rerun(step.id)}];
      if(adjustable())list.push({id:'adjust',label:'Ajuster',
        hint:'Dire ce qui ne va pas : l’assistant propose un réglage à essayer',run:()=>api.adjust()});
      /* **Une étape ratée ne se valide pas** : on la refait, ou on la passe en
         disant pourquoi. Une étape que le système a passée (scène éteinte)
         se « continue » : il n'y a rien à valider. */
      if(!failed)list.push({id:'validate',
        label:report.status===BH.STAGE_STATUS.SKIPPED?'Continuer':'Valider l’étape',
        primary:!held,run:()=>api.validate()});
      list.push({id:'skip',label:'Passer…',run:()=>api.chooseSkip(true)});
      list.push({id:'exit',label:'Quitter',run:()=>cancel('bouton')});
      overlay.buttons(list,'Actions de la revue');
    }
    function enterReview(){
      const step=stage();
      if(!step)return;
      phase=PHASE.REVIEW;phaseAt=now();engageRun=0;
      if(strip)strip.set(PHASE.REVIEW);
      overlay.deadline(null);
      overlay.target(null);
      const report=reports[step.id]||{};
      reviewing={stage:step.id,status:report.status||null};
      choosing=false;
      paintReview();
      markFlow(BH.SESSION_EVENT.STAGE_REVIEW,{stage:step.id});
      say('info','[barehands] calibration.review',{stage:step.id,status:report.status||null,
        attempt:attempts[step.id]||1,lines:reviewLines(step.id).map(item=>item.metric)});
      /* Le focus va à la **revue elle-même** (une région qui se lit), jamais
         à une commande : Entrée tenue ne valide ni ne passe rien (reprise QA). */
      overlay.focusNode(reviewNode);
    }
    function leaveReview(){
      if(reviewNode){overlay.unmountNode('feedback',reviewNode);reviewNode=null}
      const was=reviewing;reviewing=null;adjusting=false;
      if(was&&typeof d.adjust==='function'){
        try{d.adjust(null)}
        catch(error){say('warn','[barehands] calibration.adjust_failed',{error:String(error&&error.message||error)})}
      }
    }
    /* Une décision de revue, rangée dans la séance (décision 56) et dans
       l'historique, sur l'horloge de séance (décision 58). */
    function recordDecision(stageId,decision,status,reason){
      if(!session)return null;
      const row=Object.freeze({stage:stageId,decision,status:status||BH.STAGE_STATUS.SKIPPED,
        reason:reason||null,attempt:Math.max(1,attempts[stageId]||1),t:pageT()});
      session.reviews.push(row);
      const kind=decision==='validated'?BH.SESSION_EVENT.STAGE_VALIDATED
        :decision==='rerun'?BH.SESSION_EVENT.STAGE_RERUN:BH.SESSION_EVENT.STAGE_SKIPPED;
      markFlow(kind,{stage:stageId});
      say('info','[barehands] calibration.decision',row);
      return row;
    }
    /* Un événement daté par la **page** (retour, essai, revue). */
    function markFlow(kind,fields){
      if(!session)return null;
      const f=fields||{};
      const current=stage();
      return pushSample(pageT(),{kind,ref:f.ref||null},{stage:f.stage||(current?current.id:null),
        exerciseRef:null,trialRef:f.trialRef||null});
    }
    /* **Refaire efface la tentative d'avant de ce qui se dérive, pas de
       l'historique** (décision 56). Verdict, notes et valeurs dérivées de
       l'étape repartent de zéro — la nouvelle tentative est la seule qui
       compte, y compris si elle échoue : une étape ratée ne garde pas les
       seuils d'une tentative réussie d'avant (aucune valeur devinée). Les
       épisodes et lignes de mesure d'avant restent dans la séance, sous leurs
       références : c'est la preuve « avant » que l'assistant compare. */
    const DERIVED_KEYS=Object.freeze({
      [BH.STAGE.NEUTRAL]:Object.freeze(['jitterPx']),
      [BH.STAGE.PINCH_PRIMARY]:Object.freeze(['pressRatio','releaseRatio']),
      [BH.STAGE.PINCH_SECONDARY]:Object.freeze(['secondaryPressRatio','secondaryReleaseRatio']),
    });
    function resetStage(stageId){
      if(reports)reports[stageId]={status:BH.STAGE_STATUS.SKIPPED,reason:null,samples:0};
      delete stageNotes[stageId];
      for(const key of DERIVED_KEYS[stageId]||[])
        for(const bucket of Object.values(collectedAll||{}))if(bucket.measures)delete bucket.measures[key];
      if(stageId===BH.STAGE.AIM&&clickTravels)clickTravels.length=0;
      if(stageId===BH.STAGE.DRAG&&dragTravels)dragTravels.length=0;
      if(session)session.attemptRefs[stageId]=[];
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
        /* **Sauf le flux d'un pincement**, amorcé par les images qui ont armé
           l'étape : sa ligne de base ouverte et le début de sa fermeture sont
           d'avant l'armement, et sans elles ce premier pincement serait
           toujours refusé comme tronqué. Aucun seau du profil n'est amorcé. */
        collected.stream=armedStream;armedStream=[];
        repeats=0;pinchTarget=o.pinchRepeats;holdTarget=o.holdRepeats;settleFrom=null;
        pressFrom=null;holdFrom=null;secondHandSeen=false;
        /* Un temps négatif compte **à partir d'ici**, jamais pendant la
           lecture : ce qui s'est déclenché avant que l'utilisateur ait
           commencé n'est pas une faute de l'exercice. */
        negative=null;
        if(isNegative(stage()))openNegative(stage());
        overlay.deadline(o.stageTimeoutMs);
        overlay.progress(0);
      }else{
        overlay.deadline(null);
        if(next===PHASE.ARMED){armedStream=[];shallowSince=null}
      }
      /* L'exercice de sélection pose ses étoiles ici, à la fin de la lecture,
         pour la même raison que les points (décision 24). Sans banc, ou si le
         banc ne peut rien poser, `startSelection` rend les points. */
      if(next===PHASE.ARMED&&!aimPoints&&!sel&&selectionFor(stage()))startSelection();
      if(next===PHASE.ARMED&&aimPoints){
        /* **Décision 24 : les cibles n'apparaissent qu'ici.** Poser un point à
           viser sous une consigne qu'on est en train de lire, c'est demander de
           viser avant d'avoir lu. */
        aimIndex=0;
        if(ghosts)ghosts.set(aimIndex,aimHits);
        overlay.target(aimPoints[aimIndex]);
      }
      /* **Décision 25, et c'est la même règle que les cibles.** Le cadre
         d'entraînement n'apparaît qu'à la fin de la lecture : posé pendant
         qu'on lit, il serait saisi avant que la consigne soit finie — et une
         fenêtre qui arrive au milieu d'une phrase fait relever les yeux, ce qui
         est exactement le contraire d'une phase de lecture.

         Il n'est ouvert qu'**une fois** pour les deux sous-étapes : 6B reprend
         la même fenêtre, là où 6A l'a laissée. La rouvrir la ferait sauter à sa
         position de départ entre deux gestes, et l'utilisateur lirait ce saut
         comme un refus de ce qu'il vient de réussir. */
      if(next===PHASE.ARMED&&stepAt(at)&&stepAt(at).practice)openPractice();
      /* 6C pose sa destination à la fin de sa lecture, comme les cibles
         (décision 24) : ailleurs que là où la fenêtre se trouve. */
      if(next===PHASE.ARMED&&stage()&&stage().mode==='drop'&&!dropSpot&&placeDrop()===false)return;
      paintPhase();
    }

    /* Ce que l'écran dit pendant une phase où rien ne se mesure. Appelée à
       chaque image **et** à chaque battement du chien de garde, donc elle tient
       aussi quand la caméra ne voit personne — c'est le cas qui compte, parce
       que c'est celui où l'utilisateur n'a pas encore levé les mains. */
    function paintPhase(){
      const step=stage();
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
        if(shallowSince!==null){
          const left=Math.max(0,Math.ceil((o.stageTimeoutMs-(now()-shallowSince))/1000));
          overlay.note(`Pincez plus franchement : ${SHALLOW[step.id]||'fermez complètement, puis rouvrez grand'}. `
            +`Sans pincement franc, l’étape s’arrêtera dans ${left} s — vous pouvez aussi la passer.`,'');
          return;
        }
        /* Avec le banc de sélection, ce sont des **étoiles** (reprise QA). */
        const start=step.id===BH.STAGE.AIM&&sel
          ?'formez le C pour faire apparaître le jeton, amenez-le jusqu’à ce que l’anneau entoure l’étoile en pointillé, puis pincez pouce et index'
          :START[step.id];
        overlay.note(`À vous, quand vous voulez : ${start||'commencez le geste'}. `
          +'La mesure ne démarre qu’à ce moment-là — vous pouvez aussi passer cette étape ou quitter.','');
      }
    }

    /* **Lire ce que le vrai moteur a fait du cadre d'entraînement**, et en
       tirer les deux seules conclusions que cet écran ait besoin de tirer :
       l'utilisateur a **commencé**, l'utilisateur a **fini**.

       Appelée à chaque image **et** à chaque battement du chien de garde. Les
       deux, parce que le relâchement — le fait qui solde un temps — peut tomber
       sur une image où la couture de mesures ne tire pas, et une conclusion
       manquée laisserait l'utilisateur devant un exercice qu'il vient de
       réussir. Même leçon que la cadence d'images du tutoriel.

       Elle ne **décide** rien, elle constate. `mode` vient de
       `combineCaptures` (une main sur une zone ⇒ `move` ; deux zones distinctes
       et compatibles ⇒ `resize`) ; `moved`/`sized` viennent de la boîte que
       `manipulateBox` a calculée sous la taille minimale et la non-inversion.
       C'est ce qui rend 6B infalsifiable : deux zones identiques
       (`same_zone_rejected`), deux prises de corps (`both_captures_are_body`),
       deux captures de la même main (`same_hand_twice`) ou une seule main
       (`missing_capture` ⇒ `move`) ne produisent **jamais** un relâchement de
       type `resize`, parce que le contrat les a refusées bien avant d'arriver
       ici. Il n'y a donc aucune règle de compatibilité de zones écrite dans ce
       module — il n'y en avait pas besoin. */
    function pumpPractice(){
      if(!practiceOn||!practice)return false;
      let events=[];
      try{events=practice.drain()||[]}
      catch(error){say('warn','[barehands] cadre d’entraînement illisible',error);return false}
      for(const event of events){
        /* `preview` compte autant que `begin` : le moteur n'ouvre un plan
           qu'une fois, donc une main qui reste posée pendant qu'une seconde
           arrive ne produit **pas** de second `begin`. Sans cette ligne, 6B
           resterait armée sous les doigts de quelqu'un en train de
           redimensionner. */
        if(event.type==='begin'||event.type==='preview')holdingFrame=true;
        else if(event.type==='cancel')holdingFrame=false;
        else if(event.type==='commit'){holdingFrame=false;frameDone=event}
      }
      /* **L'armement, et c'est le signal le plus honnête du parcours** :
         le moteur n'ouvre un plan sur ce cadre que lorsqu'une main a réellement
         pincé un bord ou un coin **et** commencé à tirer (`dragSlopPx`, mesuré
         sur la paume). Ce n'est pas un indice d'engagement, c'est l'engagement. */
      if(phase===PHASE.ARMED&&(holdingFrame||frameDone))enterPhase(PHASE.RUNNING);
      if(phase!==PHASE.RUNNING||!frameDone)return false;
      const done=frameDone;frameDone=null;
      const want=stage();
      if(!want)return false;
      if(want.mode==='drop')return judgeDrop(want,done);
      const changed=want.mode==='resize'?done.sized:done.moved;
      if(done.mode===want.mode&&changed){
        settle(BH.STAGE_STATUS.OK,null,collected.samples.length,
          {mode:done.mode,box:done.box,from:done.from});
        return true;
      }
      /* **Un geste qui n'est pas celui qu'on demande se dit, et l'exercice
         continue.** Se taire ferait croire que le cadre ne répond pas, alors
         qu'il vient d'obéir — à l'autre geste. Ni réussite ni échec : l'échéance
         court toujours, et la phrase dit quoi faire de différent. */
      /* **Le geste d'abord, l'ampleur ensuite**, et l'ordre compte : un
         redimensionnement pendant 6A ne bouge pas forcément le coin haut
         gauche, donc « la fenêtre n'a pas bougé » serait techniquement vrai et
         trompeur — la fenêtre a changé, c'est le *geste* qui n'est pas celui
         qu'on demande. Nommer le geste apprend quelque chose ; nommer
         l'ampleur enverrait tirer plus fort sur le mauvais geste. */
      overlay.note(done.mode!==want.mode
        ?(done.mode==='resize'
          ?'C’est un redimensionnement. Pour ce temps-ci, prenez la fenêtre par une seule zone et déplacez-la entière.'
          :'Vous l’avez déplacée. Pour la redimensionner, attrapez-la des deux mains en même temps.')
        :'La fenêtre n’a pas bougé. Tirez un peu plus franchement avant de relâcher.',
        'bad',900);
      return false;
    }

    /* La course d'un geste **pincé**, en fraction de la largeur de l'image, ou
       `null` tant que le geste n'est pas relâché. C'est la moitié
       « glissement » de `deriveTravelSlop`, extraite pour que l'étape de visée
       et la sous-étape 6A mesurent la **même** grandeur de la même façon — deux
       copies auraient fini par diverger d'un facteur d'échelle, et la tolérance
       clic/glissement se serait mise à comparer deux unités différentes. */
    function pinchTravel(first,time){
      const pinched=Number.isFinite(first.primaryRatio)&&first.primaryRatio<band.releaseRatio;
      if(pinched){if(pressFrom===null)pressFrom={x:first.palmX,y:first.palmY,at:time};return null}
      if(pressFrom===null)return null;
      const travelPx=Math.hypot(Number(first.palmX)-pressFrom.x,Number(first.palmY)-pressFrom.y);
      /* En **fraction de la largeur de l'image**, pas en pixels : c'est l'unité
         que le profil persiste, et la conversion se fait ici, là où la largeur
         du moment est connue. */
      const width=Math.max(1,Number(viewport().width)||1);
      pressFrom=null;
      return travelPx/width;
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
      const step=stage();
      /* **La visée ne perd pas ce qu'elle a déjà mesuré.** Un utilisateur qui a
         touché un point sur trois a produit un déplacement de clic parfaitement
         exploitable : déclarer l'étape ratée jetterait une mesure réelle et
         ferait retomber sa tolérance clic/glissement sur le défaut d'usine
         alors qu'il a bien cliqué. Les règles de repli ne bougent pas pour
         autant — une visée sans **aucun** clic échoue exactement comme avant,
         et une étape ratée laisse toujours ses clés nulles. */
      /* L'exercice de sélection rend sa ligne de mesures **même à
         l'échéance** : trois mauvaises étoiles avant la fin du temps sont une
         mesure de l'assistance, pas un rien. */
      const selected=step&&step.id===BH.STAGE.AIM?finishSelection(step):null;
      if(step&&step.id===BH.STAGE.AIM&&aimHits>0){
        settle(BH.STAGE_STATUS.OK,null,collected.samples.length,selected||undefined);
        return true;
      }
      /* **Une étape de pincement rend ce qu'elle a mesuré** : épisodes rangés
         et journalisés, verdict sur les épisodes (`finishPinch` final). */
      if(step&&(step.id===BH.STAGE.PINCH_PRIMARY||step.id===BH.STAGE.PINCH_SECONDARY)
        &&collected.samples.length){
        finishPinch(step,true);
        return true;
      }
      /* Tenir puis relâcher rend ce qu'il a mesuré, pareil. */
      if(step&&step.id===BH.STAGE.HOLD_RELEASE&&collected.samples.length){
        finishHoldRelease(step,true);
        return true;
      }
      /* 6C rend ses lâchers, s'il y en a eu. */
      if(step&&step.id===BH.STAGE.DROP&&dropStats&&dropStats.attempts){
        finishDrop(step);
        return true;
      }
      /* **Un temps négatif rend son exposition** dès qu'elle fait un taux
         lisible (`negativeMinMs`) : trois secondes de mouvement ordinaire sans
         faux clic sont une mesure, pas un échec. */
      if(negative&&isNegative(step)&&negative.exposureMs>=o.negativeMinMs){
        finishNegative(step);
        return true;
      }
      /* Des mains vues, mais trop peu de temps devant la caméra pour qu'un
         taux veuille dire quelque chose : pas « temps écoulé », qui
         n'expliquerait rien. */
      if(negative&&isNegative(step)&&collected.samples.length){
        settle(BH.STAGE_STATUS.FAILED,BH.STAGE_REASON.TOO_FEW_SAMPLES,collected.samples.length,
          {exposureMs:negative.exposureMs},'trop peu de mouvement devant la caméra pour mesurer un taux');
        negative=null;
        return true;
      }
      const reason=!collected.samples.length?BH.STAGE_REASON.NO_HAND
        :(step&&step.needs>1&&!secondHandSeen)?BH.STAGE_REASON.NEEDS_TWO_HANDS
        :BH.STAGE_REASON.TIMEOUT;
      settle(BH.STAGE_STATUS.FAILED,reason,collected.samples.length);
      return true;
    }

    /* Le jeton est-il sur le point allumé ? Sans point à viser (pas de
       fenêtre mesurable) ou sans jeton lisible, on ne juge pas : refuser ici
       bloquerait l'étape sur une panne qui n'est pas celle de l'utilisateur. */
    function onAimPoint(hand){
      const point=aimPoints&&aimPoints[aimIndex];
      const x=Number(hand.pointerX),y=Number(hand.pointerY);
      if(!point||!Number.isFinite(x)||!Number.isFinite(y))return true;
      return Math.hypot(x-point.x,y-point.y)<=o.aimHitPx;
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

    /* La démonstration de l'**étape mesurée** courante. Appelée à l'ouverture
       d'un écran *et* au passage de 6A à 6B, où la coque n'est justement pas
       repassée : on remplace alors seulement ce qu'on avait posé, et le reste
       de l'écran — titre, consigne, cadre d'entraînement — ne bouge pas. */
    function mountDemo(){
      const current=stage();
      if(!current)return false;
      overlay.clear('demo');
      const demo=demoNode(doc,current.id);
      if(demo)overlay.mount('demo',demo);
      return !!demo;
    }

    /* Y a-t-il une **vraie** fenêtre à manipuler ? Deux questions en une — un
       banc branché, et une scène qui donne son échelle — et elles ont la même
       réponse pour l'utilisateur. */
    function practiceReady(){
      if(!practice)return false;
      try{return !!practice.viewport()}
      catch(error){say('warn','[barehands] échelle de scène illisible',error);return false}
    }
    function openPractice(){
      if(practiceOn||!practice)return false;
      /* `regions()` rend `null` quand la coque est fermée et **ne la construit
         pas** : une image en retard ne doit pas faire réapparaître un cadre
         dans une surimpression que l'utilisateur vient de quitter. */
      const region=overlay.regions();
      if(!region||!region.exercise)return false;
      let opened=null;
      try{opened=practice.open(region.exercise)}
      catch(error){say('warn','[barehands] cadre d’entraînement non ouvert',error);return false}
      if(!opened)return false;
      practiceOn=true;holdingFrame=false;frameDone=null;
      say('info','[barehands] cadre d’entraînement ouvert',opened);
      return true;
    }
    /* **Démonté sur tous les chemins de sortie.** Il n'y a que deux passages —
       `advance()` (changement d'écran, fin du parcours) et `stop()` (Échap,
       croix, bouton « Quitter », enregistrement, annulation) — et aucune sortie
       ne les contourne. Écrit là plutôt que sur chaque sortie : une garantie
       que chaque chemin doit se rappeler de respecter n'est pas une garantie.

       `overlay.step()` ne suffirait pas : le cadre n'a pas été posé par
       `mount()` (c'est la page qui l'append dans la région), donc la coque ne
       le retire pas, et un cadre oublié ici flotterait au-dessus du rapport. */
    function closePractice(){
      practiceOn=false;holdingFrame=false;frameDone=null;
      if(!practice)return false;
      try{return practice.close()}
      catch(error){say('warn','[barehands] cadre d’entraînement non démonté',error);return false}
    }

    /* **Divergence D4 : la scène est éteinte, donc il n'y a pas de vraie
       fenêtre — et ce dépôt refuse la fausse.**

       Cette étape est la première du parcours à dépendre de la scène : elle lui
       emprunte son **échelle**, parce qu'un geste calibré contre une échelle
       inventée ne calibre rien. C'est la panne que `viewport_unavailable`
       existe déjà pour empêcher côté moteur, vue d'ici. Les deux replis
       possibles sont des défauts plausibles : une échelle fabriquée fait partir
       le cadre six fois trop loin, un faux cadre fait « réussir » une étape qui
       n'a pas mesuré le vrai geste.

       Les deux temps sont donc **passés**, pas ratés — l'utilisateur n'a rien
       manqué, sa scène était éteinte — et le rapport nomme la cause au lieu de
       la taire. Les règles de repli partiel ne bougent pas d'un iota : clés
       nulles, défauts du moteur (décision 31). */
    function refuseNoScene(){
      const step=stepAt(at);
      for(const sub of step.subs)
        reports[sub.id]={status:BH.STAGE_STATUS.SKIPPED,
          reason:BH.STAGE_REASON.SCENE_UNAVAILABLE,samples:0};
      /* Sur le dernier temps et soldé : `nextStage()` passera donc à l'écran
         suivant au lieu de proposer 6B, qui n'a pas plus de cadre que 6A. */
      settled=true;subAt=step.subs.length-1;
      if(subs)subs.set(subAt);
      say('info','[barehands] calibration : manipulation de fenêtre passée',
        {reason:BH.STAGE_REASON.SCENE_UNAVAILABLE});
      overlay.note(`${step.title} : ${LABEL[BH.STAGE_REASON.SCENE_UNAVAILABLE]}. `
        +'Il n’y a pas de vraie fenêtre à manipuler, et Bare Hands préfère passer '
        +'l’étape plutôt que vous faire répéter un geste sur un faux cadre. '
        +'Ses valeurs d’usine restent en place.','',o.resultMs);
      /* La revue, comme après toute étape : l'utilisateur lit pourquoi, puis
         continue lui-même (décision 56). */
      enterReview();
    }

    /* **Le passage de 6A à 6B, et il ne repasse pas par la coque.**

       `overlay.step()` vide la scène et réécrit le bandeau : l'appeler ici
       effacerait le cadre d'entraînement que l'utilisateur tient encore des
       yeux, et lui ferait relire un titre qu'il vient de lire. Ce qui change
       entre les deux temps est la **consigne** et la **démonstration**, pas le
       sujet ; seuls ces deux-là sont donc remplacés, et l'échéance de mesure se
       réarme par `overlay.deadline()` — qui a été ajoutée à la coque
       exactement pour ce cas (Slice 06).

       Le cadre, lui, **reste** : 6B reprend la fenêtre là où 6A l'a laissée. La
       rouvrir la ferait sauter à sa position de départ entre deux gestes, et ce
       saut se lirait comme un refus de ce qu'on vient de réussir. */
    function enterSub(index){
      leaveReview();
      subAt=index;settled=false;
      /* Les commandes de l'exercice reviennent (la revue ou le choix d'une
         raison les avait remplacées). */
      choosing=false;
      paintPlayButtons();
      collected=blank();
      pressFrom=null;holdFrom=null;secondHandSeen=false;
      holdingFrame=false;frameDone=null;negative=null;
      if(subs)subs.set(index);
      mountDemo();
      /* Un temps qui vise (7B) pose ses points **à lui**, comme l'étape de
         visée, et ne les montre qu'à la fin de sa lecture (décision 24). */
      const current=stage();
      overlay.target(null);
      if(current&&current.target){
        aimPoints=aimField();aimHits=0;aimIndex=0;
        overlay.clear('exercise');
        ghosts=ghostField(doc,aimPoints);
        overlay.mount('exercise',ghosts.node);
      }
      clearDrop();
      /* 6C sans porte `rect()` : pas de destination honnête — le temps est
         passé **avant** sa lecture, comme l'écran entier quand la scène est
         éteinte, et la revue le dit. (La porte présente mais sans réponse —
         cadre pas encore ouvert — se juge à la fin de la lecture, dans
         `placeDrop`.) */
      if(current&&current.mode==='drop'&&!(practice&&typeof practice.rect==='function')){
        enterPhase(PHASE.INTRO);
        placeDrop();
        return;
      }
      enterPhase(PHASE.INTRO);
      overlay.focusTitle();
      if(carry){overlay.note(carry.text,carry.kind,o.resultMs);carry=null}
    }
    /* Après une décision : le temps suivant du même écran, ou l'écran
       suivant — ou, au bout d'un détour (« Refaire » une étape déjà
       franchie), l'étape où l'on en était. */
    function nextStage(){
      leaveReview();
      if(detour){
        const back=detour;detour=null;
        say('info','[barehands] calibration.detour_back',{to:stepAt(back.at)?stageOf(stepAt(back.at),back.subAt).id:null});
        jumpTo(back);
        return;
      }
      const step=stepAt(at);
      if(step&&step.subs&&subAt+1<step.subs.length){enterSub(subAt+1);return}
      advance();
    }
    /* Aller jouer une étape précise : son écran repart de sa lecture, puis
       son temps s'il y en a plusieurs. */
    function jumpTo(target){
      at=target.at-1;
      advance();
      if(target.subAt>0&&stepAt(at)&&stepAt(at).subs&&subAt!==target.subAt)enterSub(target.subAt);
    }

    /* **Un essai attend sa mesure sur cet exercice** (Slice 06 adaptative,
       `deps.holdAfterResult(étape)`). Depuis la Slice 07, toute revue attend
       une décision ; celle-ci ne change donc plus *si* le parcours s'arrête,
       mais *ce que la revue propose d'abord* : « Refaire » devient l'action
       principale, et la revue le dit. */
    function holdWanted(step){
      if(!step||typeof d.holdAfterResult!=='function')return false;
      try{return !!d.holdAfterResult(step.id)}
      catch(error){say('warn','[barehands] calibration.hold_unreadable',{error:String(error&&error.message||error)});return false}
    }
    /* **Les boutons refusent comme la voix** (Slice 10, résidu de la QA de la
       Slice 07) : tant qu'un essai attend sa mesure sur l'exercice en cours,
       ni « Valider l'étape » ni « Passer » ne quittent l'exercice qui doit le
       juger — la voix le refusait déjà (`barehands_calibration_trial_pending`,
       séance de l'agent), les boutons passaient. Une seule porte désormais :
       celle du parcours, que les boutons et la voix traversent. Le refus se
       voit (note de la coque) et se journalise. */
    const TRIAL_PENDING_TEXT='Un réglage d’essai attend d’être jugé sur cet exercice : refaites-le, ou annulez l’essai.';
    function trialPendingHere(action){
      const step=stage();
      if(!holdWanted(step))return false;
      say('info','[barehands] calibration.trial_pending_refused',{stage:step.id,action});
      overlay.note(TRIAL_PENDING_TEXT,'bad',4000);
      return true;
    }
    /* L'écran et le temps où se joue une étape nommée, ou `null`. */
    function locate(stageId){
      for(let index=0;index<STEPS.length;index+=1){
        const step=STEPS[index];
        if(step.subs){
          const sub=step.subs.findIndex(s=>s.id===stageId);
          if(sub>=0)return {at:index,subAt:sub};
        }else if(step.id===stageId)return {at:index,subAt:0};
      }
      return null;
    }

    function advance(){
      leaveReview();
      /* **Le cadre d'entraînement part le premier** : voir `closePractice()`.
         Les étoiles de sélection aussi, pour la même raison ; une étape
         passée garde la ligne de mesures de ce qui a été joué. */
      closePractice();
      if(sel)finishSelection(null);
      closeSelection();
      at+=1;subAt=0;subs=null;
      const step=stepAt(at);
      if(!step){conclude();return}
      collected=blank();
      repeats=0;pinchTarget=o.pinchRepeats;settleFrom=null;armedStream=[];
        pressFrom=null;holdFrom=null;secondHandSeen=false;
      settled=false;aimHits=0;aimIndex=0;ghosts=null;strip=null;aimPoints=null;negative=null;
      /* **Aucune échéance à l'ouverture** (décision 22). L'étape s'ouvre en
         lecture : `deadlineMs:null`, donc la coque n'affiche pas de compte à
         rebours, et `expired()` ne peut pas être vrai. Elle s'armera dans
         `enterPhase(RUNNING)`, par `overlay.deadline()`, quand l'utilisateur
         aura commencé.

         `total` compte le **rapport** (Slice 07) : il est le septième écran, et
         non un huitième numéro collé sur le septième. Avant, le dernier
         exercice et le rapport s'annonçaient tous deux « 7 sur 7 ». */
      overlay.step({index:at+1,total:SCREENS,title:step.title,
        instruction:step.instruction,deadlineMs:null});
      strip=phaseStrip(doc);
      overlay.mount('feedback',strip.node);
      /* Le rail des deux temps, pour l'écran qui en porte deux. Monté dans
         `feedback`, à côté du bandeau de phases : les deux répondent à « où en
         suis-je ? », à deux échelles, et les séparer ferait chercher la réponse
         à deux endroits. */
      if(step.subs){
        subs=subStrip(doc,step.subs);
        overlay.mount('feedback',subs.node);
        subs.set(0);
      }
      /* **Monter après `step()`, jamais avant** : `step()` vide la scène comme
         il redessine les boutons. Une démonstration qui survivrait à son étape
         montrerait la main d'une autre consigne — et l'utilisateur ferait le
         geste affiché. */
      mountDemo();
      /* Les cibles existent dès maintenant mais ne sont **posées** qu'à la fin
         de la lecture (`enterPhase(ARMED)`), fantômes compris. Le cadre
         d'entraînement suit la même règle, et au même endroit. */
      aimAt=null;overlay.target(null);
      /* Avec un banc de sélection, l'étape de visée pose ses **étoiles** à la
         fin de la lecture (`startSelection`), pas de points. */
      if(step.target&&!selectionFor(step)){
        aimPoints=aimField();
        ghosts=ghostField(doc,aimPoints);
        overlay.mount('exercise',ghosts.node);
      }
      /* Sortir, et **passer**. Une étape qu'on ne peut pas réussir sans pouvoir
         la passer est un cul-de-sac : la décision 31 existe précisément pour
         que le parcours survive à une étape ratée. Les deux sont là dès la
         lecture : une sortie qui n'apparaîtrait qu'une fois l'exercice armé
         manquerait justement au moment où l'utilisateur se demande dans quoi il
         vient d'entrer.

         « Passer ce temps » plutôt que « Passer cette étape » quand l'écran en
         porte deux : le bouton ne passe que celui qu'on joue, et promettre
         l'écran entier mentirait d'un geste. */
      /* **Passer se justifie** (décision 57) : le bouton ouvre le choix de la
         raison, il ne solde rien tout seul. */
      choosing=false;
      paintPlayButtons();
      /* **Scène éteinte : on refuse, on n'improvise pas** (divergence D4). Le
         constat est fait ici, avant la lecture : faire lire une consigne pour
         un exercice qui ne peut pas s'ouvrir ferait attendre l'utilisateur
         devant un centre vide. */
      if(step.practice&&!practiceReady()){refuseNoScene();return}
      enterPhase(PHASE.INTRO);
      /* Le focus suit le nouvel écran : son titre (Slice 07 adaptative). */
      overlay.focusTitle();
      /* **Après la phase**, pour que la phrase du verdict précédent couvre la
         phrase de lecture et non l'inverse : ce que l'utilisateur veut savoir
         en premier, c'est pourquoi l'étape qu'il vient de faire a échoué. Tenue
         puis rendue à la lecture. */
      if(carry){overlay.note(carry.text,carry.kind,o.resultMs);carry=null}
    }

    /* Ce qu'on garde d'une image : les scalaires de cette main, et rien
       d'autre. La sélection est **par nom** — un enregistrement qui porterait
       autre chose ne le transmettrait pas (décision 32). */
    /* `handTrackId` sépare les flux d'un épisode (deux mains ne forment pas
       un pincement) ; confiance de canal et rapport 3D sont ce que le moteur a
       vu, donc ce que le rejeu du détecteur doit revoir (Slice 02 adaptative).
       Tous des scalaires : la décision 32 tient. */
    const KEEP=Object.freeze(['t','handTrackId','handedness','pinchHandedness','primaryRatio','secondaryRatio',
      'primaryConfidence','secondaryConfidence','primaryWorldRatio','secondaryWorldRatio','cPose','closure',
      'gapPalms','indexReachPalms','palmNorm','xNorm','yNorm',
      'rawX','rawY','filteredX','filteredY','pointerX','pointerY','palmX','palmY','quality','stillness','speedPxPerSec',
      /* Slice 03 adaptative : l'intention de pointer, ce que l'écran en a fait,
         et les décisions du moteur qu'un exercice négatif compte. */
      'pointingScore','pointing','pointerShown','pressed','secondaryPressed','targeted','wakePose']);
    function keep(sample){
      const kept={};
      for(const key of KEEP)kept[key]=sample[key];
      return kept;
    }
    /* Un enregistrement du flux d'épisodes, daté par l'image qui le porte
       quand il ne l'est pas : c'est le même instant (`t` vaut `now` côté
       contrôleur). */
    function stamped(sample,time){
      const kept=keep(sample);
      if(!Number.isFinite(kept.t))kept.t=time;
      return kept;
    }
    const channelOf=step=>step.id===BH.STAGE.PINCH_SECONDARY?BH.PINCH_CHANNEL.SECONDARY:BH.PINCH_CHANNEL.PRIMARY;

    function conclude(){
      leaveReview();
      /* Les ressentis et la ligne de l'assistant appartiennent aux revues :
         le rapport part propre (reprise QA : une ligne périmée y restait). */
      if(typeof d.adjust==='function'){
        try{d.adjust(null)}
        catch(error){say('warn','[barehands] calibration.adjust_failed',{error:String(error&&error.message||error)})}
      }
      overlay.target(null);
      clearDrop();
      /* Plus d'étape, donc plus de phase : le récapitulatif n'est pas un
         exercice et ne s'arme pas. Les nœuds montés partent avec le `step()`
         ci-dessous ; les références locales les lâchent ici pour qu'un arbre
         d'étape ne survive pas au parcours. */
      phase=null;strip=null;ghosts=null;aimPoints=null;subs=null;
      derived=deriveProfile(collectedAll,reports,o,band,viewport());
      finished=true;
      /* **Le rapport est le dernier écran** (Slice 07, décision 26 ; neuf
         écrans depuis la Slice 07 adaptative). */
      overlay.step({index:SCREENS,total:SCREENS,title:'Résultat',
        instruction:'Voici ce que la séance a donné, exercice par exercice, et ce qui sera enregistré. Rien ne change tant que vous ne l’avez pas demandé.',
        deadlineMs:null});
      overlay.progress(1);
      const saving=derived.measuredCount>0;
      /* **Ce que le rapport promet est ce qu'Enregistrer fait** (décision
         59). Un parcours sans aucune mesure retenue n'offre pas d'enregistrer :
         enregistrer un profil vide effacerait le profil accepté d'avant pour
         des valeurs d'usine, ce que personne n'a demandé. */
      overlay.note(saving
        ?`${derived.measuredCount} mesure(s) retenue(s). Enregistrer ne remplace que ces mesures, le reste de votre profil est gardé ; quitter sans enregistrer n’y touche pas.`
        :'Aucune mesure n’a pu être retenue : il n’y a rien à enregistrer, et votre profil actuel reste tel quel.',
        saving?'ok':'bad');
      /* **Une ligne par étape mesurée**, pas par écran : les temps de la
         manipulation de fenêtre réussissent ou échouent séparément
         (décision 31), donc ils se rendent compte séparément. Chaque ligne dit
         aussi combien d'essais, et la raison d'un passage. */
      const skipsOf=Object.create(null);
      for(const row of (session?session.reviews:[]))if(row.decision==='skipped'&&row.reason)skipsOf[row.stage]=row.reason;
      overlay.report(STAGES.map(step=>{
        const report=reports[step.id];
        const tries=attempts[step.id]||0;
        const triesText=tries>1?` — ${tries} essais`:'';
        const skipText=skipsOf[step.id]?` (${SKIP_TEXT[skipsOf[step.id]].toLowerCase()})`:'';
        const note=stageNotes[step.id]||{};
        return {label:step.label||step.title,status:report.status,
          detail:report.status===BH.STAGE_STATUS.OK
            ?`mesuré (${report.samples} ${note.unit||'image(s)'})${
              (note.warnings||[]).map(code=>` — ${WARNING_TEXT[code]}`).join('')}${
              note.detail?` — ${note.detail}`:''}${triesText}`
            :report.status===BH.STAGE_STATUS.SKIPPED
              ?`passée${skipText||(report.reason&&LABEL[report.reason]?` (${LABEL[report.reason]})`:'')}`
              :`échouée — ${LABEL[report.reason]||report.reason}${skipText?`, passée${skipText}`:''}${triesText}`};
      }));
      /* **Ce qui sera enregistré, et ce qui l'est déjà** (décision 59), sous
         le rapport : les valeurs mesurées que « Enregistrer » range, en mots
         d'utilisateur, et les réglages d'essai que l'utilisateur a déjà gardés
         pendant la séance (rangés à ce moment-là : quitter ne les défait
         pas). */
      const summary=el('section','jf-review');
      summary.setAttribute('aria-label','Ce qui sera enregistré');
      summary.setAttribute('data-save-summary','1');
      summary.appendChild(el('h3','',saving?'Sera enregistré':'Rien à enregistrer'));
      const willSave=el('ul');willSave.setAttribute('data-will-save','1');
      for(const text of changeWords(derived))willSave.appendChild(el('li','',text));
      if(saving)summary.appendChild(willSave);
      /* **Ce qui reste** (décision 69) : les valeurs enregistrées que cette
         séance ne remplace pas — étapes passées, échouées, l'autre main. */
      const keptWords=keptValueWords(derived);
      if(saving&&keptWords.length){
        summary.appendChild(el('h3','','Conservé'));
        const keptList=el('ul');keptList.setAttribute('data-kept-values','1');
        for(const text of keptWords)keptList.appendChild(el('li','',text));
        summary.appendChild(keptList);
      }
      const kept=acceptedTrials();
      summary.appendChild(el('h3','',kept.length?'Déjà gardé pendant la séance':'Aucun réglage d’essai gardé'));
      if(kept.length){
        const list=el('ul');list.setAttribute('data-kept','1');
        for(const trial of kept)list.appendChild(el('li','',trial));
        summary.appendChild(list);
      }
      overlay.mount('exercise',summary);
      /* **Enregistrer est explicite** (exigence de la Slice), et « Quitter
         sans enregistrer » dit ce qu'il fait. */
      overlay.buttons(saving?[
        {id:'apply',label:'Enregistrer',primary:true,run:()=>apply()},
        {id:'discard',label:'Quitter sans enregistrer',run:()=>cancel('résultat refusé')},
      ]:[
        {id:'discard',label:'Quitter sans enregistrer',primary:true,run:()=>cancel('rien à enregistrer')},
      ],'Enregistrer ou quitter');
      /* Le focus va au **titre** du rapport, jamais à « Enregistrer » : le
         rapport se lit avant qu'on décide (reprise QA — Entrée tenue
         enregistrait sans lecture). */
      overlay.focusTitle();
      say('info','[barehands] calibration.report',{measured:derived.measured,kept:kept.length,
        reviews:session?session.reviews.length:0});
    }
    /* Les valeurs mesurées, en mots d'utilisateur : « seuil d'appui du
       pincement pouce-index (main gauche) ». */
    const KEY_WORDS=Object.freeze({
      pressRatio:'seuil d’appui du pincement pouce-index',releaseRatio:'seuil de relâchement du pincement pouce-index',
      secondaryPressRatio:'seuil d’appui du pincement pouce-majeur',
      secondaryReleaseRatio:'seuil de relâchement du pincement pouce-majeur',
      travelSlopNorm:'tolérance entre clic et glissement',
    });
    const HAND_WORDS=Object.freeze({left:'main gauche',right:'main droite',unknown:'main non identifiée'});
    /* « avant → après », une ligne par valeur calibrante remplacée. */
    const valueText=(key,value)=>{
      if(value===null||value===undefined)return 'valeur d’usine';
      if(key==='travelSlopNorm')return value.toFixed(4).replace('.',',');
      return value.toFixed(2).replace('.',',');
    };
    function changeWords(derived){
      const before=derived.saved;
      return (derived.measured||[]).map(entry=>{
        const [hand,key]=String(entry).split('.');
        const old=before&&before.hands[hand]?before.hands[hand][key]:null;
        const next=derived.profile&&derived.profile.hands[hand]?derived.profile.hands[hand][key]:null;
        return `${KEY_WORDS[key]||key} (${HAND_WORDS[hand]||hand}) : ${valueText(key,old)} → ${valueText(key,next)}`;
      });
    }
    function keptValueWords(derived){
      const before=derived.saved;
      if(!before)return [];
      const replaced=new Set(derived.measured||[]);
      const out=[];
      for(const hand of BH.HANDEDNESSES)for(const key of BH.PROFILE_CALIBRATING_KEYS){
        const value=before.hands[hand]?before.hands[hand][key]:null;
        if(value===null||value===undefined||replaced.has(`${hand}.${key}`))continue;
        out.push(`${KEY_WORDS[key]||key} (${HAND_WORDS[hand]||hand}) : ${valueText(key,value)}`);
      }
      return out;
    }
    /* Les réglages d'essai gardés pendant la séance, lus chez la page
       (`deps.acceptedTrials()`, des phrases), ou rien. */
    function acceptedTrials(){
      if(typeof d.acceptedTrials!=='function')return [];
      try{const list=d.acceptedTrials();return Array.isArray(list)?list.map(String).slice(0,12):[]}
      catch(error){say('warn','[barehands] calibration.accepted_unreadable',{error:String(error&&error.message||error)});return []}
    }

    let collectedAll=null;
    async function apply(){
      const payload=derived&&derived.payload;
      /* Rien de mesuré, rien d'écrit : le profil accepté d'avant reste. */
      if(!payload||!derived.measuredCount){cancel('rien à enregistrer');return}
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
      /* **Le cadre d'entraînement part avant tout le reste.** `stop()` est
         l'autre des deux seuls passages de sortie (avec `advance()`), et il
         couvre Échap au milieu d'une capture, la croix, « Quitter »,
         l'enregistrement et l'abandon. Débrancher avant de fermer la coque : le
         moteur ne doit pas garder une porte ouverte vers un cadre dont le nœud
         vient de partir avec la surimpression. */
      closePractice();
      sel=null;closeSelection();
      running=false;at=-1;collected=null;collectedAll=null;derived=null;finished=null;
      /* La séance s'efface avec le parcours (décision 41). */
      session=null;
      /* Tout ce que l'étape tenait est lâché : une phase qui survivrait au
         parcours ferait repartir le suivant au milieu d'une mesure, et un
         bandeau retenu ici garderait en vie l'arbre d'un parcours terminé (une
         fuite qu'aucun écran ne montre). Même raison que la table des régions
         que la coque vide dans `close()`. */
      phase=null;phaseAt=0;engageRun=0;settled=false;
      aimPoints=null;aimIndex=0;aimHits=0;ghosts=null;strip=null;carry=null;
      subAt=0;subs=null;negative=null;lastPlayed=null;
      reviewing=null;reviewNode=null;choosing=false;detour=null;attempts=Object.create(null);
      dropSpot=null;dropNode=null;dropStats=null;
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
    /* Ce que dit un avertissement d'étape (`EPISODE_WARNING` du contrat). */
    const WARNING_TEXT=Object.freeze({
      [BH.EPISODE_WARNING.PRESS_NEVER_DETECTED]:'aucun appui n’a été détecté pendant ces pincements',
      [BH.EPISODE_WARNING.PRESS_OUT_OF_REACH]:'une partie de ces pincements n’atteint pas le seuil d’appui dérivé',
    });
    /* Ce que le rapport dit d'une étape **en plus** de son verdict rangé :
       l'unité de son compte (épisodes pour un pincement, images ailleurs) et
       un avertissement éventuel. Pas dans `reports`, dont la forme est celle
       du profil v2. */
    let stageNotes={};
    const LABEL=Object.freeze({
      [BH.STAGE_REASON.NO_HAND]:'aucune main vue',
      [BH.STAGE_REASON.TIMEOUT]:'temps écoulé',
      [BH.STAGE_REASON.TOO_FEW_SAMPLES]:'pas assez de mesures',
      [BH.STAGE_REASON.NOT_SEPARABLE]:'les deux états ne se distinguent pas',
      [BH.STAGE_REASON.OUT_OF_BAND]:'hors de la plage utilisable',
      [BH.STAGE_REASON.NEEDS_TWO_HANDS]:'deux mains nécessaires',
      [BH.STAGE_REASON.CANCELLED]:'interrompue',
      /* Slice 07, divergence D4. Dit la **cause**, pas le symptôme : « la
         scène est éteinte » est quelque chose que l'utilisateur peut corriger,
         « étape passée » ne l'est pas. */
      [BH.STAGE_REASON.SCENE_UNAVAILABLE]:'la scène est éteinte',
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
      /* **L'étape mesurée** courante, et non l'écran : c'est elle qui porte
         l'identité que le profil persiste, et la suite de valeurs qu'un
         parcours complet produit est exactement la même qu'avant la Slice 07 —
         ce sont les écrans qui ont fusionné, pas les étapes. */
      stepId(){const step=stage();return step?step.id:null},
      /* Le temps courant d'un écran qui en porte deux, et combien il en porte.
         `null` ailleurs. Publié pour la même raison que `phase()` : « l'écran
         est ouvert » et « le second temps est en cours » sont deux faits
         différents, et sans porte on ne pourrait les distinguer qu'en
         devinant. */
      sub(){const step=stepAt(at);return step&&step.subs?{at:subAt,total:step.subs.length,
        id:stage()?stage().id:null}:null},
      /* Un cadre d'entraînement est-il branché au moteur ? Lu sur l'état réel,
         comme `watching()` lit la minuterie : sans cette porte, « il a été
         démonté » et « on a oublié de le démonter » s'écrivent pareil. */
      practising(){return practiceOn},
      /* **La phase de l'étape courante**, lue de l'extérieur. Publiée parce que
         « l'étape est ouverte » et « l'étape mesure » sont devenus deux faits
         différents : sans cette porte, un test — ou un appelant — ne pourrait
         les distinguer qu'en devinant, et c'est exactement la confusion que
         cette slice corrige. `null` hors étape (récapitulatif, parcours
         fermé). */
      phase(){return stepAt(at)?phase:null},
      /* Ce que l'étape de visée demande encore : combien de points, combien de
         touchés. Lu de l'extérieur pour la même raison. */
      aim(){
        /* L'exercice de sélection (décision 49) se lit en manches. */
        if(sel)return {mode:'selection',rounds:SELECTION_ROUNDS.length,hits:aimHits,at:sel.exercise.index(),
          exerciseRef:sel.exerciseRef,
          /* Courses de clic mesurées (tolérance clic/glissement) : une par
             **bonne** prise seulement. */
          clicks:clickTravels?clickTravels.length:0};
        return aimPoints?{points:aimPoints.length,hits:aimHits,at:aimIndex}:null;
      },
      /* **Ce que la séance a mesuré**, lu de l'extérieur (Slice 02
         adaptative) : les épisodes (`createPinchEpisode`), leur jeu de
         mesures (`createMeasurementSet`) et l'historique des événements de
         séance (`validateSessionSample`). Des copies : un lecteur ne réécrit
         pas la séance. `null` hors parcours — rien ne survit à `stop()`. */
      session(){
        if(!session)return null;
        return Object.freeze({episodes:Object.freeze(session.episodes.slice()),
          /* Les faux événements des exercices négatifs (`createFalseEvent`),
             dans l'ordre de la séance (Slice 03 adaptative). */
          falseEvents:Object.freeze(session.falseEvents.slice()),
          measurements:BH.createMeasurementSet(session.measurements),
          /* Référence → `{stage, exerciseRef, trialRef, at}` (Slice 06). */
          rowMeta:Object.freeze({...session.rowMeta}),
          /* Les décisions de revue (Slice 07, décision 56) et l'origine de
             l'horloge de séance (horloge de la page, décision 58). */
          reviews:Object.freeze(session.reviews.slice()),
          clockOrigin:session.clockOrigin,
          samples:Object.freeze(session.history?session.history.samples():[]),
          dropped:session.history?session.history.dropped():0,
          history:!!session.history});
      },
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
        reports={};stageNotes={};
        /* Les étapes **mesurées** (sept), pas les écrans (six) : c'est le
           vocabulaire que le profil persiste. */
        for(const step of STAGES)reports[step.id]={status:BH.STAGE_STATUS.SKIPPED,reason:null,samples:0};
        collectedAll={};
        openSession();
        running=true;at=-1;finished=false;
        clickTravels=[];dragTravels=[];
        /* Le mot de sortie vient de la **coque**, qui sait laquelle de ses
           sorties a servi (Slice 09) : l'ignorer journalisait « échap » pour
           un clic sur la croix, c'est-à-dire la mauvaise cause pour une action
           que l'utilisateur a bien faite. Les deux mots sont ceux que la coque
           émet, traduits ici comme le tutoriel traduit les siens. */
        overlay.open({title:'Calibration Bare Hands',
          exit:why=>cancel(EXIT_WORD[why]||String(why||'demandé')),
          /* Échap passe d'abord par le parcours (reprise QA) : il referme le
             choix d'une raison ou les ressentis, sinon demande confirmation. */
          escape:()=>api.escape()});
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
        /* `steps` compte les **exercices** (six depuis la Slice 07), `screens`
           les écrans que l'utilisateur va traverser, rapport compris (sept).
           Les deux, parce que « combien d'exercices » et « combien d'écrans »
           sont devenus deux nombres différents, et qu'un seul des deux répondu
           à la place de l'autre serait faux la moitié du temps. */
        return {ok:true,flow:'calibration',step:this.stepId(),
          steps:STEPS.length,screens:SCREENS,stages:STAGES.length};
      },
      exit(reason){if(!running)return false;cancel(reason||'demandé');return true},
      /* **Enregistrer**, la porte publique du bouton du rapport (reprise QA) :
         seulement au rapport, et seulement s'il y a une mesure retenue —
         sinon rien n'est écrit et le profil accepté d'avant reste. */
      save(){if(!running||finished!==true)return false;apply();return true},
      /* **Le récapitulatif est-il à l'écran ?** (Slice 06 adaptative.) Après
         lui il n'y a plus d'exercice à refaire ni à passer. */
      concluded(){return running&&finished===true},
      /* **Un essai attend-il sa mesure sur l'exercice en revue ?** (Slice 06 ;
         depuis la Slice 07 toute revue attend, ceci dit seulement que
         « Refaire » y est l'action principale.) */
      holding(){return running&&phase===PHASE.REVIEW&&holdWanted(stage())},
      /* **La revue en cours**, lue de l'extérieur (Slice 07 adaptative,
         décision 56) : l'étape, son verdict, l'essai n°, les lignes de
         mesures affichées **avec leurs références**, l'explication de
         l'assistant et le choix d'une raison ouvert ou non. `null` hors revue. */
      review(){
        if(!running||phase!==PHASE.REVIEW||!reviewing)return null;
        const step=stage();
        const report=reports[step.id]||{};
        return Object.freeze({stage:step.id,status:report.status||null,reason:report.reason||null,
          attempt:attempts[step.id]||1,lines:Object.freeze(reviewLines(step.id)),
          explanation:explanation(step.id),choosing,held:holdWanted(step),
          /* Les actions **à l'écran** : Ajuster seulement avec un assistant,
             Valider jamais sur une étape ratée. */
          actions:Object.freeze(['rerun',...(adjustable()?['adjust']:[]),
            ...(report.status===BH.STAGE_STATUS.FAILED?[]:['validate']),'skip','exit'])});
      },
      /* **Refaire un exercice** (Slice 06 adaptative, décision 55 ; Slice 07,
         décision 56) : l'exercice nommé, sinon celui qui se joue ou qui est en
         revue, sinon le dernier joué. Il repart de sa lecture ; ce qui se
         **dérive** de sa tentative d'avant est effacé (`resetStage`), ses
         mesures d'avant restent dans la séance. Refaire une étape déjà
         franchie est un **détour** : après l'avoir validée ou passée, le
         parcours revient où il en était. Rend l'étape, ou `null`. */
      rerun(stageId){
        if(!running||finished===true)return null;
        const named=stageId!==undefined&&stageId!==null;
        if(named&&!locate(stageId))return null;
        if(named&&!this.canRerun(stageId).ok){
          say('info','[barehands] calibration.rerun_refused',{to:stageId,code:'barehands_calibration_exercise_not_played'});
          return null;
        }
        const current=stepAt(at);
        const here=current?{at,subAt}:null;
        const playing=current&&!settled&&(phase===PHASE.RUNNING||phase===PHASE.ARMED);
        const target=named?locate(stageId)
          :(phase===PHASE.REVIEW||playing||!lastPlayed)?here:lastPlayed;
        if(!target)return null;
        const targetStage=stageOf(stepAt(target.at),target.subAt);
        say('info','[barehands] calibration.rerun',{from:stage()?stage().id:null,to:targetStage.id,sub:target.subAt});
        recordDecision(targetStage.id,'rerun',(reports[targetStage.id]||{}).status);
        /* Un détour : la cible est avant l'endroit où l'on en est. On revient
           ensuite à l'étape en cours (non soldée) ou à celle qui suit la revue
           qu'on quitte. Le premier détour fixe le retour. */
        if(here&&!detour&&(target.at<here.at||(target.at===here.at&&target.subAt<here.subAt))){
          const screen=stepAt(here.at);
          detour=!settled?here
            :screen&&screen.subs&&here.subAt+1<screen.subs.length?{at:here.at,subAt:here.subAt+1}
            :{at:here.at+1,subAt:0};
        }
        resetStage(targetStage.id);
        choosing=false;
        jumpTo(target);
        return this.stepId();
      },
      /* **Valider l'étape** (décision 56) : seulement depuis sa revue, et
         jamais une étape ratée — elle se refait ou se passe. Rend la
         nouvelle étape, ou `null` quand il n'y a rien à valider. */
      validate(){
        if(!running||finished===true||phase!==PHASE.REVIEW)return null;
        const step=stage();
        const report=reports[step.id]||{};
        if(report.status===BH.STAGE_STATUS.FAILED)return null;
        if(trialPendingHere('validate'))return null;
        recordDecision(step.id,'validated',report.status);
        nextStage();
        return this.stepId();
      },
      /* **Passer, avec une raison** (décision 57) : `reason` ∈ `SKIP_REASONS`,
         sinon refus `barehands_calibration_skip_reason_required`. Un exercice
         non soldé se solde « passé » avec cette raison ; une revue réussie
         qu'on passe **ne garde pas** sa mesure (passer veut dire « ne retiens
         pas ») ; une revue ratée reste ratée, la raison s'ajoute. Rend
         `{ok, step, code}`. */
      skip(reason){
        if(!running||finished===true)return Object.freeze({ok:false,step:null,code:'barehands_calibration_exercise_unavailable'});
        const step=stage();
        if(!step)return Object.freeze({ok:false,step:null,code:'barehands_calibration_exercise_unavailable'});
        if(!BH.SKIP_REASONS.includes(reason))
          return Object.freeze({ok:false,step:this.stepId(),code:'barehands_calibration_skip_reason_required'});
        if(trialPendingHere('skip')){
          choosing=false;
          if(phase===PHASE.REVIEW)paintReviewButtons(step,reports[step.id]||{},true);else paintPlayButtons();
          return Object.freeze({ok:false,step:this.stepId(),code:'barehands_calibration_trial_pending'});
        }
        const name=step.label||step.title;
        const words=SKIP_TEXT[reason].toLowerCase();
        if(phase===PHASE.REVIEW){
          const report=reports[step.id]||{};
          if(report.status===BH.STAGE_STATUS.OK){
            const samples=report.samples;
            resetStage(step.id);
            reports[step.id]={status:BH.STAGE_STATUS.SKIPPED,reason:BH.SKIP_REASON[reason],samples};
          }
          recordDecision(step.id,'skipped',reports[step.id].status,reason);
          carry={text:`${name} : passée (${words}). Bare Hands garde ses valeurs d’usine pour cette étape.`,kind:''};
        }else{
          settle(BH.STAGE_STATUS.SKIPPED,BH.SKIP_REASON[reason],collected?collected.samples.length:0,
            null,`passée (${words})`,{review:false});
          recordDecision(step.id,'skipped',BH.STAGE_STATUS.SKIPPED,reason);
          carry={text:`${name} : passée (${words}).`,kind:''};
        }
        choosing=false;
        nextStage();
        return Object.freeze({ok:true,step:this.stepId(),code:null});
      },
      /* **Continuer** : la porte de la voix (`calibration_next_exercise`).
         Revue d'une étape non ratée : Valider. Sinon : Passer, qui exige sa
         raison. Rend `{ok, step, code}`. */
      next(reason){
        if(!running||finished===true)return Object.freeze({ok:false,step:null,code:'barehands_calibration_exercise_unavailable',decision:null});
        /* **Une raison dit « passer », toujours** (reprise QA : « passe » à la
           voix sur une revue réussie validait et gardait la mesure, quand le
           bouton la passait sans la garder — décision 57). Sans raison : une
           revue non ratée se valide ; tout le reste exige la raison. Le reçu
           dit ce qui a été décidé. */
        const given=reason!==undefined&&reason!==null;
        if(stage()&&holdWanted(stage())){
          trialPendingHere('next');
          return Object.freeze({ok:false,step:this.stepId(),code:'barehands_calibration_trial_pending',decision:null});
        }
        if(!given&&phase===PHASE.REVIEW&&(reports[stage().id]||{}).status!==BH.STAGE_STATUS.FAILED){
          const step=this.validate();
          return Object.freeze({ok:true,step,code:null,decision:'validated'});
        }
        const answer=this.skip(reason);
        return Object.freeze({...answer,decision:answer.ok?'skipped':null});
      },
      /* Ouvrir (ou refermer) le choix de la raison d'un passage. */
      chooseSkip(on){
        if(!running||finished===true||!stage())return false;
        /* Rien à choisir tant que l'essai de cet exercice attend sa mesure. */
        if(on!==false&&trialPendingHere('choose_skip'))return false;
        choosing=on!==false;
        if(phase===PHASE.REVIEW){
          const step=stage();
          paintReviewButtons(step,reports[step.id]||{},holdWanted(step));
        }else paintPlayButtons();
        /* Le focus va à « Retour », qui ne commet rien — jamais à une raison
           (reprise QA : Entrée tenue passait l'étape « pas utile pour moi »). */
        if(choosing){
          overlay.note('Pourquoi passer cette étape ? Votre raison est notée dans le rapport.','',6000);
          overlay.focusAction('back');
        }else{
          overlay.releaseNote();
          if(phase===PHASE.REVIEW)overlay.focusNode(reviewNode);else overlay.focusAction('skip');
        }
        return choosing;
      },
      /* **Ajuster** (décision 56) : ouvre les ressentis de l'assistant
         (`deps.adjust(étape)` — la page montre les commandes de retour de la
         séance de l'agent). La revue reste : un ressenti mène à une hypothèse
         et à un essai, puis on refait l'exercice. */
      adjust(){
        if(!running||phase!==PHASE.REVIEW||!adjustable())return false;
        const step=stage();
        let shown=false;
        try{shown=d.adjust(step.id)!==false}
        catch(error){say('warn','[barehands] calibration.adjust_failed',{error:String(error&&error.message||error)});return false}
        adjusting=!!shown;
        if(shown)overlay.note('Qu’est-ce qui ne va pas ? Dites-le, ou choisissez un ressenti : l’assistant proposera un réglage à essayer, puis vous referez l’exercice.','',8000);
        say('info','[barehands] calibration.adjust',{stage:step.id,shown});
        return shown;
      },
      /* **Un événement daté par la page** (décision 58) : un retour, un essai
         appliqué, défait ou gardé, que la séance de l'agent range dans
         l'historique sur l'horloge de séance. Rend la référence `se-N`. */
      mark(kind,fields){
        if(!running||!session)return null;
        if(![BH.SESSION_EVENT.FEEDBACK,BH.SESSION_EVENT.TRIAL_APPLIED,BH.SESSION_EVENT.TRIAL_ROLLED_BACK,
          BH.SESSION_EVENT.TRIAL_ACCEPTED].includes(kind))return null;
        const f=fields&&typeof fields==='object'?fields:{};
        return markFlow(kind,{ref:BH.isSessionRef(f.ref)?f.ref:null,
          trialRef:BH.isSessionRef(f.trialRef,[BH.SESSION_REF.TRIAL])?f.trialRef:null});
      },
      /* **Ce que le rapport a dérivé**, lu de l'extérieur (Slice 07
         adaptative) : la charge utile qu'« Enregistrer » enverrait, ce qui est
         compté comme mesuré. `null` avant le rapport. Une lecture : rien
         n'est enregistré par elle. */
      result(){
        if(!running||finished!==true||!derived)return null;
        /* `payload` : ce qui part (les seules valeurs remplacées, avec
           `replaces`) ; `profile` : le profil tel qu'il sera enregistré
           (fusion du contrat, décision 69). */
        return Object.freeze({payload:derived.payload,profile:derived.profile,session:derived.session,measured:derived.measured.slice(),
          measuredCount:derived.measuredCount});
      },
      /* **Échap** (reprise QA de la Slice 07) : referme le choix d'une raison
         ou les ressentis ouverts ; sur l'état de base, la première pression
         arme la sortie et le dit, une seconde dans les deux secondes quitte.
         Rend `true` quand le parcours a pris la touche (la coque ne sort pas). */
      escape(){
        if(!running)return false;
        if(choosing){this.chooseSkip(false);escapeArmedAt=null;return true}
        if(adjusting){
          adjusting=false;escapeArmedAt=null;
          try{if(typeof d.adjust==='function')d.adjust(null)}
          catch(error){say('warn','[barehands] calibration.adjust_failed',{error:String(error&&error.message||error)})}
          overlay.releaseNote();
          overlay.focusAction('adjust');
          return true;
        }
        if(escapeArmedAt!==null&&now()-escapeArmedAt<=ESCAPE_CONFIRM_MS){escapeArmedAt=null;return false}
        escapeArmedAt=now();
        overlay.note('Appuyez encore sur Échap pour quitter la calibration. Rien n’est enregistré si vous quittez.','',ESCAPE_CONFIRM_MS);
        say('info','[barehands] calibration.escape_armed');
        return true;
      },
      /* **Peut-on refaire cette étape ?** (reprise QA) Refaire ne saute pas en
         avant : une étape **jamais jouée** placée après l'endroit où l'on en
         est se refuse (`barehands_calibration_exercise_not_played`) — sinon
         les étapes intermédiaires resteraient sans revue ni raison. Rend
         `{ok, code}`. */
      canRerun(stageId){
        if(!running||finished===true)return Object.freeze({ok:false,code:'barehands_calibration_exercise_unavailable'});
        if(stageId===undefined||stageId===null)return Object.freeze({ok:true,code:null});
        const target=locate(stageId);
        if(!target)return Object.freeze({ok:false,code:'barehands_calibration_exercise_unknown'});
        const ahead=target.at>at||(target.at===at&&target.subAt>subAt);
        const played=(attempts[stageId]||0)>0||(session&&session.reviews.some(r=>r.stage===stageId));
        const behindDetour=!!detour&&(target.at<detour.at||(target.at===detour.at&&target.subAt<detour.subAt));
        if(ahead&&!played&&!behindDetour)return Object.freeze({ok:false,code:'barehands_calibration_exercise_not_played'});
        return Object.freeze({ok:true,code:null});
      },
      /* L'instant de séance (ms depuis l'ouverture, horloge de la page). */
      sessionTime(){return session?pageT():null},
      /* **Un événement de séance du moteur** (Slice 03 adaptative, décision
         46) : `pointing_intent_start`/`_end`, `pointer_shown`/`_hidden`, tels
         que le contrôleur les émet (`deps.onSessionEvent`), avec le temps de
         l'image. Rangé dans l'historique de séance sous le vocabulaire du
         contrat ; pendant 7A, un curseur affiché est un faux événement
         `unintended_pointer`. Rend `true` s'il a été lu. */
      observe(event){
        if(!running||!session||!event||typeof event!=='object')return false;
        const kind=String(event.kind||'');
        if(!BH.SESSION_EVENTS.includes(kind))return false;
        const time=Number(event.t);
        if(!Number.isFinite(time))return false;
        syncClock(time);
        const current=stage();
        const measuring=phase===PHASE.RUNNING&&!!negative;
        const where=measuring?{stage:negative.stage,exerciseRef:negative.exerciseRef}
          :sel?{stage:BH.STAGE.AIM,exerciseRef:sel.exerciseRef}
          :{stage:current?current.id:null,exerciseRef:null};
        const score=Number(event.score);
        /* Les champs dérivés que le moteur a posés (décision 49 : canal,
           fente, région, distance, type de cible, cible attendue) ; la liste
           blanche de l'enregistreur (`readSessionEvent`) décide du reste. */
        const ref=pushEvent(time,{kind,score:event.score!==null&&Number.isFinite(score)?score:null,
          channel:event.channel,slot:event.slot,region:event.region,distancePx:event.distancePx,
          targetKind:event.targetKind,expected:event.expected},where);
        if(measuring&&kind===BH.SESSION_EVENT.POINTER_SHOWN
          &&NEGATIVE_WATCH[negative.stage].includes(F.UNINTENDED_POINTER))
          recordFalse(F.UNINTENDED_POINTER,time,ref);
        return true;
      },
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
        /* **Le chien de garde regarde aussi le cadre d'entraînement**, et il le
           doit : le relâchement qui solde un temps peut tomber sur une image où
           la couture de mesures ne tire pas, et personne d'autre ne le lirait.
           Il ne fabrique toujours rien — il lit un journal que le vrai moteur a
           écrit, exactement comme il lit une montre. */
        if(pumpPractice())return this.stepId();
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
        /* **La revue n'avance jamais seule** (décision 56) : ni le temps ni
           une image n'en sortent, seule une décision. */
        if(phase===PHASE.REVIEW)return this.stepId();
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
        /* **L'écran et l'étape mesurée sont deux choses depuis la Slice 07.**
           L'écran porte le titre, les cibles et le cadre d'entraînement ;
           l'étape mesurée porte l'identité persistée, l'exigence de mains et le
           verdict. Les cinq premiers écrans n'en portent qu'une, le sixième en
           porte deux — et tout ce qui suit lit `step`, c'est-à-dire l'étape. */
        const screen=stepAt(at);
        if(!screen)return null;
        /* Ce que le **vrai** moteur a fait du cadre depuis la dernière lecture,
           avant toute autre chose : c'est de là que viennent l'armement et le
           verdict de cet écran-là. */
        if(pumpPractice())return this.stepId();
        const step=stage();
        if(!step)return null;
        const seen=record&&Array.isArray(record.hands)?record.hands:[];
        const hands=seen.filter(hand=>Number(hand.quality)>=o.sampleQualityMin);
        const time=Number(record&&record.now);
        const pinchStage=step.id===BH.STAGE.PINCH_PRIMARY||step.id===BH.STAGE.PINCH_SECONDARY
          ||step.id===BH.STAGE.HOLD_RELEASE;
        syncClock(time);
        /* **Les phases d'abord, et dans l'ordre où elles arrivent.** Une image
           reçue pendant la lecture ou pendant l'attente ne mesure rien : elle
           ne remplit aucun seau, elle ne fait descendre aucune échéance, et le
           seul effet qu'elle peut avoir est de constater que l'utilisateur a
           commencé. C'est la correction de cette slice, écrite là où elle se
           voit. */
        if(phase===PHASE.REVIEW)return this.stepId();
        if(phase===PHASE.INTRO){
          if(now()-phaseAt<o.introMs){paintPhase();return this.stepId()}
          enterPhase(PHASE.ARMED);
        }
        if(phase===PHASE.ARMED){
          /* **L'écran de manipulation s'arme sur une vraie capture** (décision
             25), et `pumpPractice()` l'a déjà fait au-dessus s'il y avait lieu.
             Aucun prédicat de scalaires ici : une main qui passe devant
             l'objectif n'ouvre pas de plan sur un cadre, donc il n'y a rien à
             deviner et aucun seuil de plus à poser. */
          if(screen.practice){paintPhase();return this.stepId()}
          /* Aucune main sûre : l'étape attend, et elle le dit **sans reproche**
             — l'utilisateur n'a rien raté, il n'a pas encore commencé. C'est la
             différence avec la phrase rouge d'une mesure en cours. */
          if(pinchStage){
            for(const hand of seen)armedStream.push(stamped(hand,time));
            while(armedStream.length&&time-armedStream[0].t>o.pinchLookbackMs)armedStream.shift();
          }
          if(!hands.length){paintPhase();return this.stepId()}
          const test=ENGAGE[step.id];
          const qualifies=pinchStage?pinchEngaged(armedStream,channelOf(step),o)
            :!!test&&!!test(hands[0],band,hands);
          if(pinchStage){
            const span=qualifies?null:pinchShallow(armedStream,channelOf(step),o);
            shallowSince=span===null?null:shallowSince===null?now():shallowSince;
            /* La même échéance qu'une mesure : un essai timide qui dure ne
               reste pas une attente sans fin, il se solde sur le motif qui dit
               ce qui manque. */
            if(span!==null&&now()-shallowSince>=o.stageTimeoutMs){
              settle(BH.STAGE_STATUS.FAILED,BH.STAGE_REASON.NOT_SEPARABLE,0,{separation:span,armed:false},
                'le pincement et la main ouverte se ressemblent trop pour qu’un seuil les sépare');
              return this.stepId();
            }
          }
          /* Consécutives, sinon rien : un repère bruité seul ne peut pas armer
             une étape. Le compteur retombe à zéro à la première image qui ne
             qualifie pas, donc un mouvement de passage devant l'objectif
             n'accumule pas. */
          engageRun=qualifies?engageRun+1:0;
          if(engageRun<o.engageFrames){paintPhase();return this.stepId()}
          enterPhase(PHASE.RUNNING);
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
        /* **Le flux de l'épisode garde aussi les images douteuses.** Le
           segmenteur les écarte lui-même (ce sont des trous), mais le rejeu du
           détecteur doit revoir ce que le moteur a vu : une image de qualité
           basse y compte comme un doute, et l'effacer changerait la latence
           mesurée. */
        if(pinchStage)for(const hand of seen)collected.stream.push(stamped(hand,time));
        /* **Un temps négatif** (Slice 03 adaptative) : ses images ne
           remplissent aucun seau du profil — elles ne décrivent pas un geste
           voulu — mais elles comptent comme échantillons, pour que l'échéance
           dise « aucune main vue » à qui n'a rien montré. */
        if(negative&&isNegative(step)){
          for(const hand of hands)collected.samples.push(keep(hand));
          watchNegative(seen,hands,time);
          paintNegative(step,hands,time);
          return this.stepId();
        }
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
        /* Une répétition = un **épisode complet** (`countPinchEpisodes`, la
           règle du segmenteur), pas un franchissement du relâchement d'usine :
           la cadence de la caméra ne décide pas du nombre de pincements, et
           « quatre demandés » veut dire quatre épisodes mesurables. */
        /* **Tenir puis relâcher** (décision 56) : on compte les pincements
           **tenus** (`holdPinchMs`), et l'écran dit quand le dernier a été
           relâché trop tôt. */
        if(step.id===BH.STAGE.HOLD_RELEASE){
          const count=countHeldEpisodes(collected.stream,BH.PINCH_CHANNEL.PRIMARY,o);
          const shown=Math.min(count.held,holdTarget);
          overlay.progress(shown/holdTarget);
          overlay.note(count.lastShort&&count.held<holdTarget
            ?`Tenez plus longtemps : gardez les doigts fermés une seconde avant de rouvrir. ${shown} sur ${holdTarget}.`
            :`${shown} pincement(s) tenu(s) sur ${holdTarget}`,'');
          if(count.held>=holdTarget){
            if(settleFrom===null)settleFrom=time;
            if(!(time-settleFrom<o.pinchSettleMs))finishHoldRelease(step);
          }
          return this.stepId();
        }
        if(pinchStage){
          repeats=countPinchEpisodes(collected.stream,channelOf(step),o);
          const shown=Math.min(repeats,pinchTarget);
          overlay.progress(shown/pinchTarget);
          overlay.note(pinchTarget>o.pinchRepeats&&repeats>=o.pinchRepeats
            ?`Encore un pincement, franc et complet : ${shown} sur ${pinchTarget}.`
            :`${shown} pincement(s) sur ${pinchTarget}`,'');
          /* Le dernier épisode est complet dès que la main rentre dans le haut
             de sa bande ; sa ligne de base d'après se lit sur les
             `episodeBaselineMs` qui suivent. On les laisse venir
             (`pinchSettleMs`) avant de découper. */
          if(repeats>=pinchTarget){
            if(settleFrom===null)settleFrom=time;
            if(!(time-settleFrom<o.pinchSettleMs))finishPinch(step);
          }
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
        /* **La manipulation de fenêtre ne se mesure pas dans les scalaires**
           (Slice 07). Ce qui solde 6A et 6B est passé par `pumpPractice()`, en
           haut : c'est le **vrai** moteur qui a bougé un **vrai** cadre. Ce qui
           reste à faire ici tient en deux choses — nourrir la moitié
           « glissement » de la tolérance clic/glissement, et dire à l'écran ce
           qui se passe pendant que l'utilisateur tire. */
        if(screen.practice){
          /* **La moitié « glissement » de `deriveTravelSlop`, et elle reste
             honnête ici.** 6A est exactement ce que l'ancienne étape `drag`
             mesurait — un pincement, une course franche, un relâchement — à
             ceci près que la main tient maintenant un vrai bord de cadre au
             lieu de traverser le vide. La grandeur est la même (la course de la
             **paume** entre la fermeture et l'ouverture du canal, en fraction
             de la largeur d'image), et elle se compare donc toujours aux clics
             de l'étape de visée. La dérivation, elle, n'est pas touchée.

             **6B n'en produit aucune**, et c'est délibéré : un
             redimensionnement à deux mains fait deux courses simultanées dont
             aucune n'est « un glissement délibéré » au sens de
             `deriveTravelSlop`. Les y verser élargirait la tolérance de tout le
             monde sur une grandeur qui n'est pas celle qu'on croit mesurer. */
          if(step.mode==='move'){
            const travel=pinchTravel(first,time);
            if(travel!==null)dragTravels.push(travel);
          }
          overlay.progress(holdingFrame?0.7:0.25);
          overlay.note(holdingFrame
            ?(step.mode==='resize'
              ?'Fenêtre tenue à deux mains : écartez ou rapprochez vos mains, puis relâchez.'
              :step.mode==='drop'?'Vous tenez la fenêtre : portez-la dans le cadre en pointillé, puis relâchez-la dedans.'
              :'Vous tenez la fenêtre : déplacez-la, puis relâchez.')
            :`Attrapez la fenêtre : ${START[step.id]||'commencez le geste'}.`,'');
          return this.stepId();
        }
        if(step.id===BH.STAGE.AIM&&sel){
          /* **L'exercice de sélection** (décision 49). Ce qui a été pris se lit
             chez le vrai résolveur (`pumpSelection`) ; ce qui se mesure ici
             est la course de la paume entre la fermeture et l'ouverture, pour
             la tolérance clic/glissement, exactement comme sur les points —
             mais seulement quand la **bonne** étoile a été prise. */
          pumpSelection();
          const pinched=Number.isFinite(first.primaryRatio)&&first.primaryRatio<band.releaseRatio;
          if(pinched&&pressFrom===null)pressFrom={x:first.palmX,y:first.palmY,at:time};
          const outcome=sel.exercise.pending();
          if(!pinched&&outcome!==null){
            const verdict=sel.exercise.release();
            if(verdict.outcome==='expected'){
              aimHits+=1;
              if(pressFrom){
                const travelPx=Math.hypot(Number(first.palmX)-pressFrom.x,Number(first.palmY)-pressFrom.y);
                clickTravels.push(travelPx/Math.max(1,Number(viewport().width)||1));
              }
            }
            pressFrom=null;
            if(verdict.next&&sel.exercise.done()){
              const result=finishSelection(step);
              if(aimHits>0)settle(BH.STAGE_STATUS.OK,null,collected.samples.length,result);
              else settle(BH.STAGE_STATUS.FAILED,BH.STAGE_REASON.TOO_FEW_SAMPLES,0,result,
                'aucune étoile marquée n’a été prise');
              return this.stepId();
            }
            if(verdict.next){
              openSelectionRound();
              if(verdict.outcome==='expected')overlay.flash(420);
              overlay.progress(sel.exercise.index()/SELECTION_ROUNDS.length);
              const round=SELECTION_ROUNDS[sel.exercise.index()];
              overlay.note(verdict.skipped
                ?`Manche passée après ${o.selectionAttemptsMax} essais. Suivante : ${round.label.toLowerCase()}.`
                :`Prise. Suivante : ${round.label.toLowerCase()}.`,verdict.skipped?'bad':'ok',900);
              return this.stepId();
            }
            overlay.note(verdict.outcome==='other'
              ?'Une voisine a été prise : regardez quelle étoile porte l’anneau avant de pincer.'
              :'Rien sous le jeton : amenez-le jusqu’à ce que l’étoile marquée porte l’anneau, puis pincez.','bad',1200);
            return this.stepId();
          }
          if(!pinched)pressFrom=null;
          const round=SELECTION_ROUNDS[sel.exercise.index()];
          const sum=sel.exercise.summary();
          overlay.progress((sel.exercise.index()+(outcome==='expected'?.5:0))/SELECTION_ROUNDS.length);
          overlay.note(outcome==='expected'?'Prise : relâchez.'
            :outcome!==null?'Relâchez, puis visez l’étoile marquée.'
            :`${round?round.label:'Étoile'} (${Math.min(sel.exercise.index()+1,SELECTION_ROUNDS.length)} sur ${SELECTION_ROUNDS.length}) : `
              +'l’anneau montre l’étoile qui serait prise. Pincez quand il entoure l’étoile en pointillé.'
              +(sum.wrong||sum.missed?` Ratés : ${sum.wrong+sum.missed}.`:''),'');
          return this.stepId();
        }
        if(step.id===BH.STAGE.AIM){
          const pinched=Number.isFinite(first.primaryRatio)&&first.primaryRatio<band.releaseRatio;
          if(pinched&&pressFrom===null)pressFrom={x:first.palmX,y:first.palmY,at:time,
            hit:onAimPoint(first)};
          if(!pinched&&pressFrom!==null&&!pressFrom.hit){
            /* **Hors du point, ce n'est pas un point touché** : ni progression,
               ni course de clic mesurée — un pincement à côté ne dit rien de ce
               qu'un clic visé parcourt. L'écran le dit, et le même point
               reste allumé. */
            pressFrom=null;
            overlay.note('À côté du point : formez le C, amenez d’abord le jeton dessus, puis pincez.','bad',900);
            return this.stepId();
          }
          if(!pinched&&pressFrom!==null){
            const travelPx=Math.hypot(Number(first.palmX)-pressFrom.x,Number(first.palmY)-pressFrom.y);
            /* En **fraction de la largeur de l'image**, pas en pixels : c'est
               l'unité que le profil persiste, et la conversion se fait ici,
               là où la largeur du moment est connue. */
            const width=Math.max(1,Number(viewport().width)||1);
            clickTravels.push(travelPx/width);
            pressFrom=null;
            /* **Un point touché n'est pas l'étape finie** (décision 24). La
               visée enseigne « viser et cliquer » : un seul point toujours au
               même endroit enseignerait « pincer ». Le point suivant s'allume,
               le précédent passe en trait plein, et le vert dit « celui-là est
               pris » — brièvement, comme partout ailleurs. */
            if(aimPoints&&aimHits+1<aimPoints.length){
              aimHits+=1;aimIndex=aimHits;
              if(ghosts)ghosts.set(aimIndex,aimHits);
              overlay.target(aimPoints[aimIndex]);
              overlay.flash(420);
              overlay.progress(aimHits/aimPoints.length);
              overlay.note(`Point ${aimHits} sur ${aimPoints.length}. Visez le suivant.`,'ok',600);
              return this.stepId();
            }
            aimHits+=1;
            settle(BH.STAGE_STATUS.OK,null,collected.samples.length);
            return this.stepId();
          }
          const pressing=!!pressFrom&&pressFrom.hit;
          const done=aimPoints?(aimHits+(pressing?.5:0))/aimPoints.length:(pressing?.6:.2);
          overlay.progress(done);
          overlay.note(pressFrom&&!pressFrom.hit?'Ce pincement est à côté du point : relâchez, visez, puis recommencez.'
            :pressFrom?'Relâchez quand vous êtes prêt.'
            :`Formez le C pour voir le jeton, amenez-le sur le point${aimPoints&&aimPoints.length>1?` (${aimHits+1} sur ${aimPoints.length})`:''}, puis pincez.`,'');
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
        /* Le tremblement est aussi une **mesure de séance** (Slice 07,
           décision 56) : la revue l'affiche depuis le jeu de mesures, et
           l'assistant peut la citer (`pointer_filter_too_noisy`). */
        exerciseRow(step.id,{pointer_jitter_px:jitter.jitterPx});
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
          :check.cause==='fingers'?'majeur, annulaire et auriculaire restent dépliés, donc Bare Hands lit une main plate et non un C (le C se fait du pouce et de l’index seuls) — courbez-les vers la paume'
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

    /* **Épisodes, puis seuils** (Slice 02 adaptative, décision 43). Le flux
       de l'étape est découpé en épisodes, chaque épisode chronométré contre le
       vrai détecteur, et les seuils dérivés des épisodes — un geste, une
       voix. Trop peu d'épisodes complets alors que la main sépare bien ses
       deux états : l'étape **redemande un pincement** au lieu d'échouer,
       sous son échéance. */
    /* `final` : l'échéance est passée. Plus de pincement à redemander — ce
       qui a été mesuré est rangé, journalisé et rendu tel quel (une étape
       dont l'attente de la dernière ligne de base chevauche l'échéance
       aboutit ; une étape à qui il manque des épisodes échoue sur
       `TOO_FEW_SAMPLES`, compte d'épisodes à l'appui, pas sur « temps
       écoulé » avec un compte d'images). */
    function finishPinch(step,final){
      const channel=channelOf(step);
      let next=session.nextEpisode;
      const measured=measurePinchEpisodes(collected.stream,channel,{options:o,
        detector:handedness=>d.pinchChannel(channel,handedness),lostGraceMs,
        stage:step.id,trialRef:trialNow(),nextRef:()=>`${BH.SESSION_REF.EPISODE}-${next++}`});
      const read=deriveEpisodeHysteresis(measured.episodes,o,{span:measured.span,
        releaseCeiling:channel===BH.PINCH_CHANNEL.PRIMARY?band.wakeGapMin:null});
      if(!final&&!read.ok&&read.reason===BH.STAGE_REASON.TOO_FEW_SAMPLES){
        pinchTarget=repeats+1;settleFrom=null;
        return;
      }
      session.nextEpisode=next;
      for(const ep of measured.episodes)recordEpisode(ep);
      /* La ligne d'exercice de la tentative (Slice 07, décision 56) : parts
         d'appuis et de relâchements que le vrai détecteur n'a pas tranchés.
         Seulement sur assez d'épisodes pour être une mesure — une ligne
         d'exercice vaut un exercice entier pour juger un essai. */
      if(measured.episodes.length>=o.pinchEpisodesMin){
        const pressedEps=measured.episodes.filter(ep=>ep.pressLatencyMs!==null);
        exerciseRow(step.id,{
          missed_press_rate:(measured.episodes.length-pressedEps.length)/measured.episodes.length,
          missed_release_rate:pressedEps.length?pressedEps.filter(ep=>ep.releaseLatencyMs===null).length/pressedEps.length:null});
      }
      const rejected={};
      for(const r of measured.rejected)rejected[r.code]=(rejected[r.code]||0)+1;
      /* Le chemin normal se journalise aussi (RÈGLE ZÉRO) : combien
         d'épisodes, combien refusés et pourquoi, combien d'appuis manqués. */
      const missedPress=measured.episodes.filter(ep=>ep.pressLatencyMs===null).length;
      say('info','[barehands] calibration.episodes',{stage:step.id,channel,final:!!final,
        episodes:measured.episodes.length,rejected,missedPress,
        stickyRelease:measured.episodes.filter(ep=>ep.pressLatencyMs!==null&&ep.releaseLatencyMs===null).length});
      /* **Mesuré n'est pas « ça clique ».** Des seuils se dérivent de la main,
         mais si le vrai détecteur n'a tranché **aucun** appui pendant l'étape
         (veto de profondeur, confiance de canal), l'utilisateur le vivra
         après avoir appliqué : l'étape le dit, sous un avertissement nommé. */
      const warnings=[];
      if(measured.episodes.length&&missedPress===measured.episodes.length)
        warnings.push(BH.EPISODE_WARNING.PRESS_NEVER_DETECTED);
      /* Des seuils rendus, mais une part des gestes mesurés n'aurait pas
         atteint l'appui dérivé : l'utilisateur verrait des clics manqués. */
      if(read.ok&&read.pressReach<o.pressReachMin)warnings.push(BH.EPISODE_WARNING.PRESS_OUT_OF_REACH);
      stageNotes[step.id]={unit:'épisode(s)',warnings};
      if(!read.ok){
        settle(BH.STAGE_STATUS.FAILED,read.reason,read.samples,read,
          read.reason===BH.STAGE_REASON.NOT_SEPARABLE
            ?'le pincement et la main ouverte se ressemblent trop pour qu’un seuil les sépare'
            :read.reason===BH.STAGE_REASON.OUT_OF_BAND
              ?'votre pincement ne se ferme pas assez : le seuil d’appui tomberait au-dessus du relâchement permis sous la posture de réveil'
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
      settle(BH.STAGE_STATUS.OK,null,read.samples,{...read,missedPress,warnings},
        warnings.length?warnings.map(code=>WARNING_TEXT[code]).join(', et '):undefined);
    }


    /* **Une ligne d'exercice** (`ex-N`) du jeu de mesures, notée avec son
       étape et l'essai en cours : ce que la revue affiche et ce que
       l'assistant cite. Rend sa référence, ou `null` hors séance. */
    function exerciseRow(stageId,row){
      if(!session)return null;
      const ref=`${BH.SESSION_REF.EXERCISE}-${session.nextExercise++}`;
      session.measurements[ref]=row;
      noteRow(ref,stageId,ref,trialNow());
      return ref;
    }

    /* **Tenir puis relâcher** (Slice 07 adaptative, décision 56). Les
       épisodes du flux primaire, rejoués contre le vrai détecteur ; ne
       comptent que ceux dont la phase fermée a tenu `holdPinchMs`. Ce qui se
       mesure, par pincement tenu :

         prématuré  le contact a lâché (ou a été repris) avant que la main
                    commence à se rouvrir — la fenêtre tombe en route ;
         collé      le contact appuyé n'a pas lâché à la réouverture — la
                    fenêtre reste à la main.

       Ligne `ex-N` : `premature_drop_count`, `missed_release_rate` (collés /
       appuyés), `missed_press_rate`, `release_latency_ms` (médiane). Aucune
       clé de profil : c'est de la preuve, pas un seuil. */
    function finishHoldRelease(step,final){
      const channel=BH.PINCH_CHANNEL.PRIMARY;
      let next=session.nextEpisode;
      const measured=measurePinchEpisodes(collected.stream,channel,{options:o,
        detector:handedness=>d.pinchChannel(channel,handedness),lostGraceMs,
        stage:step.id,trialRef:trialNow(),nextRef:()=>`${BH.SESSION_REF.EPISODE}-${next++}`});
      const held=measured.episodes.filter(ep=>ep.minimumMs>=o.holdPinchMs);
      if(!final&&held.length<holdTarget){
        /* Un pincement compté à l'écran n'a pas passé la mesure (refusé au
           découpage) : on en redemande un, sous l'échéance. */
        holdTarget=held.length+1;settleFrom=null;
        return;
      }
      session.nextEpisode=next;
      for(const ep of held)recordEpisode(ep);
      /* **Trois catégories exclusives** par pincement tenu et appuyé (reprise
         QA) : prématuré (le contact a fini — relâché **ou annulé** — avant la
         réouverture, ou a été repris), collé (pas prématuré, et pas relâché
         à la réouverture), net. Un contact annulé doigts fermés est
         prématuré, pas collé. La latence de relâchement ne se lit que sur les
         nets : un prématuré n'y verse pas de valeur négative. */
      const pressed=held.filter(ep=>ep.pressLatencyMs!==null);
      const prematureEps=pressed.filter(ep=>ep.premature);
      const premature=prematureEps.length;
      const stickyEps=pressed.filter(ep=>!ep.premature&&ep.releaseLatencyMs===null);
      const sticky=stickyEps.length;
      const clean=pressed.filter(ep=>!ep.premature&&ep.releaseLatencyMs!==null);
      say('info','[barehands] calibration.hold_release',{final:!!final,episodes:measured.episodes.length,
        held:held.length,premature,sticky,missedPress:held.length-pressed.length});
      if(!held.length){
        settle(BH.STAGE_STATUS.FAILED,BH.STAGE_REASON.TOO_FEW_SAMPLES,measured.episodes.length,
          {episodes:measured.episodes.length},'aucun pincement n’a été tenu une seconde');
        return;
      }
      const row={premature_drop_count:premature,
        missed_release_rate:pressed.length?sticky/pressed.length:null,
        missed_press_rate:(held.length-pressed.length)/held.length,
        release_latency_ms:BH.quantile(clean.map(ep=>ep.releaseLatencyMs),.5)};
      exerciseRow(step.id,row);
      const trouble=[premature?`${premature} relâchement(s) trop tôt`:'',sticky?`${sticky} relâchement(s) qui collent`:'']
        .filter(Boolean).join(' et ');
      stageNotes[step.id]={unit:'pincement(s) tenu(s)',warnings:[],detail:trouble||'aucun relâchement prématuré ni collé'};
      settle(BH.STAGE_STATUS.OK,null,held.length,row,trouble||undefined);
    }

    /* **6C, déposer** (décision 56). La fenêtre se lit à l'écran par la porte
       optionnelle `practice.rect()` du banc (pixels de la fenêtre, calculés
       par la page avec la même conversion que le dessin). Sans elle, il n'y a
       pas de destination honnête à poser : le temps est **passé** avec le
       motif de la scène, comme la manipulation entière quand la scène est
       éteinte. */
    function practiceRect(){
      if(!practice||typeof practice.rect!=='function')return null;
      try{
        const r=practice.rect();
        return r&&['left','top','width','height'].every(key=>Number.isFinite(Number(r[key])))
          &&Number(r.width)>0&&Number(r.height)>0
          ?{left:Number(r.left),top:Number(r.top),width:Number(r.width),height:Number(r.height)}:null;
      }catch(error){say('warn','[barehands] calibration.drop_rect_unreadable',{error:String(error&&error.message||error)});return null}
    }
    function clearDrop(){
      if(dropNode)overlay.unmountNode('exercise',dropNode);
      dropNode=null;dropSpot=null;dropStats=null;
    }
    function placeDrop(){
      const rect=practiceRect();
      if(!rect){
        say('warn','[barehands] calibration.drop_unavailable',{error:'le banc ne dit pas où est la fenêtre'});
        settle(BH.STAGE_STATUS.SKIPPED,BH.STAGE_REASON.SCENE_UNAVAILABLE,0,null,
          'la fenêtre d’entraînement ne dit pas où elle est, donc aucune destination honnête ne peut être posée');
        return false;
      }
      const view=viewport();
      const width=Math.max(1,Number(view&&view.width)||1);
      const cx=rect.left+rect.width/2,cy=rect.top+rect.height/2;
      /* De l'autre côté de l'écran, à la même hauteur : un vrai trajet, et
         une destination qui ne recouvre jamais la fenêtre de départ. */
      const half=rect.width/2+16;
      const want=cx<width/2?width*.72:width*.28;
      const x=Math.min(Math.max(want,half),Math.max(half,width-half));
      dropSpot={x,y:cy,width:rect.width,height:rect.height};
      dropStats={attempts:0,hits:0,premature:0,lastError:null};
      const node=doc.createElement('div');
      node.className='jf-drop';
      node.setAttribute('aria-hidden','true');
      node.setAttribute('data-drop','1');
      node.style.left=`${Math.round(x-rect.width/2)}px`;
      node.style.top=`${Math.round(cy-rect.height/2)}px`;
      node.style.width=`${Math.round(rect.width)}px`;
      node.style.height=`${Math.round(rect.height)}px`;
      const label=doc.createElement('span');label.textContent='Destination';
      node.appendChild(label);
      dropNode=overlay.mount('exercise',node);
      say('info','[barehands] calibration.drop_placed',{x:Math.round(x),y:Math.round(cy)});
      return true;
    }
    /* Un relâchement pendant 6C : dans la destination (écart par axe sous
       `dropTolerancePx`), ou un lâcher **avant** elle. */
    function judgeDrop(want,done){
      if(!dropStats)return false;
      if(done.mode!=='move'){
        overlay.note('C’est un redimensionnement. Pour déposer, prenez la fenêtre par un bord ou un coin, d’une seule main.','bad',1500);
        return false;
      }
      const rect=practiceRect();
      if(!rect){
        settle(BH.STAGE_STATUS.SKIPPED,BH.STAGE_REASON.SCENE_UNAVAILABLE,dropStats.attempts,null,
          'la fenêtre d’entraînement ne dit plus où elle est');
        return true;
      }
      const dx=rect.left+rect.width/2-dropSpot.x,dy=rect.top+rect.height/2-dropSpot.y;
      const error=Math.hypot(dx,dy);
      dropStats.attempts+=1;dropStats.lastError=error;
      const inside=Math.abs(dx)<=o.dropTolerancePx&&Math.abs(dy)<=o.dropTolerancePx;
      if(inside){dropStats.hits+=1;finishDrop(want);return true}
      dropStats.premature+=1;
      if(dropStats.attempts>=o.dropAttemptsMax){finishDrop(want);return true}
      overlay.note(`Relâchée à ${Math.round(error)} px du centre de la destination : reprenez-la et amenez-la dans le cadre en pointillé.`,'bad',1500);
      return false;
    }
    function finishDrop(step){
      const s=dropStats;
      const row={drag_success_rate:s.attempts?s.hits/s.attempts:null,
        placement_error_px:s.lastError,premature_drop_count:s.premature};
      exerciseRow(step.id,row);
      stageNotes[step.id]={unit:'lâcher(s)',warnings:[],
        detail:s.hits?`déposée à ${Math.round(s.lastError)} px du centre`:'jamais déposée dans la destination'};
      say('info','[barehands] calibration.drop',{attempts:s.attempts,hits:s.hits,premature:s.premature,
        errorPx:s.lastError===null?null:Math.round(s.lastError)});
      if(s.hits)settle(BH.STAGE_STATUS.OK,null,s.attempts,row);
      else settle(BH.STAGE_STATUS.FAILED,BH.STAGE_REASON.TOO_FEW_SAMPLES,s.attempts,row,
        'la fenêtre n’a pas atteint la destination');
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
      const measured=[];
      const travel=deriveTravelSlop(clickTravels,dragTravels,opts);
      if(!travel.ok&&travel.reason===BH.STAGE_REASON.NOT_SEPARABLE)
        stages[BH.STAGE.DRAG]={status:BH.STAGE_STATUS.FAILED,
          reason:BH.STAGE_REASON.NOT_SEPARABLE,samples:travel.samples||0};
      const ok=stage=>!!stages[stage]&&stages[stage].status===BH.STAGE_STATUS.OK;
      const hands={},claimed={},sessionHands={};
      for(const handedness of Object.keys(buckets||{})){
        const bucket=buckets[handedness];
        const found={...(bucket.measures||{})};
        const reach=deriveReach(bucket.xs,bucket.ys,opts);
        if(reach.ok)found.reachNorm=reach.reachNorm;
        if(travel.ok)found.travelSlopNorm=travel.travelSlopNorm;
        const keys=[];
        for(const [stage,list] of Object.entries(STAGE_KEYS))
          if(ok(stage))for(const key of list)if(found[key]!==null&&found[key]!==undefined)keys.push(key);
        if(ok(BH.STAGE.AIM)&&ok(BH.STAGE.DRAG)&&found.travelSlopNorm!==undefined)keys.push('travelSlopNorm');
        if(ok(BH.STAGE.AIM)&&found.reachNorm!==undefined)keys.push('reachNorm');
        /* La qualité du profil de cette main : la médiane de la qualité de
           suivi pendant la séance. C'est une **métrique**, pas un seuil — elle
           ne change rien au moteur, elle dit à quel point croire le reste. */
        const quality=median(bucket.all.map(sample=>sample.quality));
        if(quality!==null)found.quality=quality;
        sessionHands[handedness]={...found};
        if(keys.length&&quality!==null)keys.push('quality');
        if(!keys.length)continue;
        const hand={};
        for(const key of keys)hand[key]=found[key];
        hands[handedness]=hand;claimed[handedness]=keys;
        /* **Ce qu'on compte est ce qui calibre** (`PROFILE_METRIC_KEYS` n'en
           sont pas) : sans mesure calibrante, rien à enregistrer. */
        for(const key of keys)if(!BH.PROFILE_METRIC_KEYS.includes(key))measured.push(`${handedness}.${key}`);
      }
      const replacedStages=BH.STAGES.filter(ok);
      const payload={schemaVersion:BH.PROFILE_SCHEMA_VERSION,updatedAt:now(),
        hands:JSON.parse(JSON.stringify(hands)),
        stages:Object.fromEntries(replacedStages.map(stage=>[stage,{...stages[stage]}])),
        replaces:{hands:claimed,stages:replacedStages}};
      /* Le profil tel qu'il sera **après** l'enregistrement : la fusion du
         contrat sur le profil enregistré — la même règle que le serveur. */
      let saved=null;
      try{saved=typeof d.savedProfile==='function'?d.savedProfile():null}
      catch(error){say('warn','[barehands] calibration.saved_profile_unreadable',{error:String(error&&error.message||error)})}
      /* Rien de calibrant : rien ne s'enregistre, le profil reste celui d'avant. */
      const profile=measured.length?BH.mergeProfile(saved,payload):BH.normalizeProfile(saved||{schemaVersion:BH.PROFILE_SCHEMA_VERSION});
      /* **La séance seule** (diagnostic, jamais envoyée) : tout ce qu'elle a
         mesuré et l'état de chacune de ses étapes, sous la forme d'un profil —
         ce qu'une calibration écrivait en entier avant la décision 69. */
      const session=BH.toProfilePayload({schemaVersion:BH.PROFILE_SCHEMA_VERSION,updatedAt:payload.updatedAt,
        hands:sessionHands,stages});
      return {payload,profile,session,saved:saved?BH.normalizeProfile(saved):null,
        measured:measured.sort(),measuredCount:measured.length,
        viewportWidth:Number(view&&view.width)||null};
    }
  }

  const api=Object.freeze({
    DEFAULTS,options,STEPS,SCREENS,FLOW_STATUS,FLOW_SLOTS,FLOW_MOUNTABLE,FLASH_MAX_MS,
    PHASE,PHASE_ORDER,PHASE_STRIP,DEMO,AIM_SPOTS,SELECTION_ROUNDS,selectionStars,createSelectionExercise,
    REVIEW_LINES:REVIEW_LINES_ALL,SKIP_TEXT,formatMetric,countHeldEpisodes,
    quantile,median,stdev,
    deriveJitter,segmentPinchEpisodes,replayPinchContacts,measurePinchEpisodes,deriveEpisodeHysteresis,
    episodeMeasures,episodeOpen,countPinchEpisodes,pinchEngaged,zigzagPivots,deriveTravelSlop,deriveReach,checkCPose,wakeBandOf,
    createFlowOverlay,createCalibration,STYLE,STYLE_ID,STEPS_STYLE,STEPS_STYLE_ID,
  });
  root.JarvisBarehandsCalibration=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
