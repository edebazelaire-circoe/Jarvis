/* Bare Hands — contrôle de cycle de vie de la barre du haut.

   Décision 1 de l'affinage d'UI : Bare Hands est un contrôle de premier plan
   de l'écran principal, et non d'abord une fonction de l'onglet Expérimental.
   Ce module en est la seule implantation : un bouton carré à icône de main en
   haut à gauche, un sélecteur visuel à trois états ouvert au clic
   (décisions 2 à 6), et — Slice 02 — quatre **actions rapides** au clic droit
   (décision 8 : Réglages, Calibration, Aide/Gestes, Diagnostic).

   Le menu contextuel n'est pas fabriqué ici : `control_center.html` en a déjà
   un, unique et partagé (`.ctxmenu`, rang 80), et ce module en devient un
   consommateur de plus par son point d'échappement `run`. Il est **injecté**,
   comme la surface et l'horloge, pour que le clic droit s'exerce sous node.
   Les deux absences du menu valent autant que ses quatre présences : pas
   d'entrée d'activation (décision 9 — le mode appartient au clic gauche) et
   pas d'entrée Tutoriel (décision 10).

   **Ce module ne tient aucun cycle de vie.** C'est une projection, et le mot
   est littéral : il n'a ni variable d'état, ni minuterie de cycle de vie, ni
   optimisme local. Il s'abonne à `JarvisBarehands.openLifecycleSeam` et peint
   ce qu'il reçoit ; il change d'état en appelant les **mêmes portes** que le
   panneau et que la voix (`enable` / `disable` / `activate` / `sleep`). Une
   seconde mémoire ici serait exactement la dérive que la décision 7 interdit :
   un réveil en C, un retour en veille après 30 s ou une caméra refusée
   changeraient l'état sans que le bouton le sache, et l'écran mentirait sans
   que rien ne tombe.

   Ce qu'il tient, lui, est de l'affichage et rien d'autre : le compteur de
   secondes du démarrage (RÈGLE ZÉRO — une attente sans borne doit dire depuis
   combien de temps elle dure, sans quoi « ça travaille » et « c'est figé » se
   ressemblent), l'ouverture du sélecteur, et le curseur de navigation au
   clavier.

   Les cinq présentations, et pourquoi elles sont cinq alors que la décision 6
   n'offre que trois modes :

   - `off` — gris fortement atténué (décision 3) ;
   - `sleep` — bleu Jarvis ordinaire, sans emphase (décision 4) ;
   - `active` — bleu électrique plus clair, avec un halo discret (décision 5).
     **Pas vert** : l'idée d'un actif vert a été explicitement retirée ;
   - `starting` — le démarrage attend `getUserMedia`, donc une invite de
     permission qu'un humain met le temps qu'il veut à lire. Le peindre
     « éteint » dirait que l'utilisateur l'a voulu, et le peindre « en veille »
     dirait que ça marche. Il a donc sa présentation, son mouvement et son
     compteur, et le sélecteur reste atteignable pour en sortir ;
   - `error` — arrêté **sans** l'avoir demandé (contrat § 1). Ce n'est pas un
     quatrième mode sélectionnable : aucune pastille n'est cochée, et le `code`
     du motif (`camera_denied`, `camera_busy`, `assets_missing`…) s'affiche tel
     quel. Une caméra refusée peinte comme un `off` choisi est exactement la
     panne qui disparaît de l'état, et c'est pour l'empêcher qu'`ERROR` existe.

   Insertion : `control_center.py` / `control_center.html`, APRÈS
   `control_center_barehands.js`, qui pose `window.JarvisBarehands` et la
   couture de cycle de vie. Le bloc navigateur les lit au chargement et
   **refuse de s'installer** sans eux : servi trop tôt, le contrôle n'apparaît
   pas et la console dit pourquoi, à l'insertion et non trois clics plus tard.
   Le refus est **rattrapé ici**, comme celui du canal de commandes, parce que
   la page servie concatène tous ses modules dans une seule balise `<script>` :
   une levée qui remonterait emporterait la scène, la timeline et le Test Lab
   avec elle. L'ordre est asserté par `test_barehands_hud_js`. */
(function(root){
  'use strict';

  /* Les contrats, lus **directement** : un module de page absent est une
     erreur d'insertion, pas un état d'exécution. Le vocabulaire du cycle de
     vie vit là-bas et nulle part ailleurs — aucun nom n'est recopié ici. */
  const BH=root.JarvisBarehandsContracts
    ||(typeof JarvisBarehandsContracts!=='undefined'?JarvisBarehandsContracts:null);
  if(!BH)throw new Error('JarvisBarehandsHud : control_center_barehands_contracts.js doit être inséré avant ce module');

  /* Les identifiants que la page, les tests et les Slices suivantes cherchent.
     Le menu contextuel de la Slice 02 est accroché à `triggerId` ; la palette
     d'outils de la Slice 03 viendra sous `hostId`. */
  const DOM=Object.freeze({
    hostId:'barehandsHud',
    styleId:'barehandsHudStyle',
    triggerId:'barehandsHudButton',
    chooserId:'barehandsHudChooser',
    captionId:'barehandsHudCaption',
    noteId:'barehandsHudNote',
    hintId:'barehandsHudHint',
    announceId:'barehandsHudAnnounce',
    /* ---- la palette d'outils (Slice 03, décisions 11 à 13) ----
       Son emplacement est **déclaré dans `control_center.html`**, comme celui
       du contrôle ci-dessus et pour la même raison : le rang d'empilement (30)
       vit dans le registre de la page.

       Les noms sont **neufs et volontairement distincts** de ceux que la
       Slice 02 a sortis des réglages (`barehandsTools`, `data-barehands-tool`,
       `role=radiogroup`). Ce n'est pas de la cosmétique : un test de la
       Slice 02 vérifie sur le balisage **réellement servi** que ces trois
       marqueurs-là ont disparu, parce que leur retour signifierait que les
       réglages ont repris la main sur l'outil (décision 14). Réutiliser les
       mêmes chaînes ici aurait fait passer ce test pour une régression alors
       que la garantie tient toujours — et, à l'inverse, l'aurait rendu
       incapable de voir un vrai retour en arrière. */
    paletteId:'barehandsPalette',
    paletteStripId:'barehandsPaletteStrip',
    paletteCaptionId:'barehandsPaletteCaption',
    paletteAnnounceId:'barehandsPaletteAnnounce',
    /* L'outil que chaque bouton porte, et **l'échelle des trois états** que la
       feuille lit. Un seul attribut pour la présentation, écrit par une seule
       fonction (`paletteOf`) : actif, disponible et sans moteur ne peuvent pas
       diverger entre le bouton, son halo et son libellé. */
    toolAttribute:'data-bh-tool',
    toolStateAttribute:'data-bh-tool-state',
    /* Le nom sous lequel la palette s'inscrit aux deux coutures. Deux parce que
       deux faits : l'outil courant (couture d'outil) et la disponibilité de
       Bare Hands (couture de cycle de vie). */
    paletteSeam:'palette',
    /* L'attribut que chaque pastille du sélecteur porte, sur le modèle de
       `data-barehands-tool` de l'onglet Expérimental. */
    modeAttribute:'data-barehands-mode',
    toneAttribute:'data-bh-tone',
    /* Le nom sous lequel ce module s'inscrit à la couture. Il est lisible par
       `JarvisBarehands.lifecycleSeam()` : « le bouton écoute » ne doit pas
       s'écrire comme « personne n'écoute ». */
    seamName:'hud',
    /* ---- les deux cartes rapides (Slice 04, décisions 15 et 16) ----
       Aide / Gestes et Diagnostic, les deux destinations du menu du clic droit
       qui n'étaient encore que des crochets. Elles partagent **un seul**
       emplacement — une seule peut être ouverte à la fois, et deux cartes
       superposées seraient deux fois la même question « laquelle lis-je ? ».

       L'emplacement est déclaré dans `control_center.html`, comme les deux
       autres surfaces de ce module et pour la même raison : son rang
       d'empilement (82) appartient au registre de la page. 82 et pas moins :
       la carte s'ouvre **depuis** le menu contextuel (80) et doit le
       recouvrir. 82 et pas plus : la confirmation en page (85) doit pouvoir
       recouvrir la carte. */
    cardsId:'barehandsCards',
    cardId:'barehandsCard',
    cardTitleId:'barehandsCardTitle',
    cardBodyId:'barehandsCardBody',
    cardCloseId:'barehandsCardClose',
    cardAnnounceId:'barehandsCardAnnounce',
    /* Quelle carte est ouverte, lisible par un test et par une console sans
       compter les nœuds. */
    cardAttribute:'data-bh-card',
  });

  /* Les trois modes **sélectionnables**, dans l'ordre où ils se présentent :
     éteint, veille, actif. Les noms viennent du contrat ; `ERROR` n'y est pas,
     et c'est tout le propos. */
  const MODES=Object.freeze([BH.LIFECYCLE.OFF,BH.LIFECYCLE.SLEEP,BH.LIFECYCLE.ACTIVE]);
  /* Présentations. Les trois premières sont les modes ; les deux autres sont
     des états que l'on subit et que l'on ne choisit pas. */
  const TONE=Object.freeze({OFF:BH.LIFECYCLE.OFF,SLEEP:BH.LIFECYCLE.SLEEP,
    ACTIVE:BH.LIFECYCLE.ACTIVE,STARTING:'starting',ERROR:BH.LIFECYCLE.ERROR});

  /* ------------------------------------------- les quatre actions rapides

     Décision 8 : **exactement** ces quatre-là, dans cet ordre. Deux absences
     sont aussi importantes que les quatre présences :

     - **aucune entrée d'activation ou de mode** (décision 9). Le mode se
       choisit au clic gauche, dans le sélecteur à trois pastilles ; le
       dupliquer ici ferait deux commandes pour un seul état, et la seconde
       finirait par mentir ;
     - **aucune entrée Tutoriel** (décision 10). Le parcours séparé cesse
       d'être une destination ; la calibration enseigne (décision 17).

     Chaque action **route** vers une porte qui existe déjà sur
     `window.JarvisBarehands`. Aucune n'en réimplante une seconde : ce menu
     n'est qu'un chemin de plus vers les mêmes fonctions, et c'est la seule
     chose qu'il a le droit d'être. */
  const QUICK=Object.freeze({SETTINGS:'settings',CALIBRATION:'calibration',
    HELP:'help',DIAGNOSTICS:'diagnostics'});
  const QUICK_ORDER=Object.freeze([QUICK.SETTINGS,QUICK.CALIBRATION,
    QUICK.HELP,QUICK.DIAGNOSTICS]);
  const QUICK_LABEL=Object.freeze({
    [QUICK.SETTINGS]:'Réglages…',
    [QUICK.CALIBRATION]:'Calibrer…',
    [QUICK.HELP]:'Aide · Gestes…',
    [QUICK.DIAGNOSTICS]:'Diagnostic…',
  });
  /* La porte de la surface gelée derrière chaque entrée. Écrite une seule fois
     pour que « le menu appelle la même fonction que le reste de la page » se
     vérifie en lisant cette table, et non en relisant quatre branches. */
  const QUICK_GATE=Object.freeze({
    [QUICK.SETTINGS]:'showSettings',
    [QUICK.CALIBRATION]:'calibrate',
    [QUICK.HELP]:'showHelp',
    [QUICK.DIAGNOSTICS]:'showDiagnostics',
  });
  /* Le délai de la touche Menu. Elle produit *aussi* un `contextmenu` dans les
     navigateurs, donc sans cette garde le menu s'ouvrirait, se refermerait et
     se rouvrirait sur une seule frappe. Même motif et même durée que les
     cartes d'agents de la page ; le repère est **local**, parce que c'est une
     déduplication entre deux événements de ce bouton-ci et de personne
     d'autre. */
  const KBD_MENU_GUARD_MS=700;

  const MODE_LABEL=Object.freeze({off:'Éteint',sleep:'Veille',active:'Actif'});
  const CAPTION=Object.freeze({off:'ÉTEINT',sleep:'VEILLE',active:'ACTIF',
    starting:'DÉMARRAGE',error:'INTERROMPU'});
  /* Ce que chaque mode **fait**, en français, sous le sélecteur. Trois phrases
     et trois conséquences réelles : OFF est le seul où le réveil en C ne peut
     rien, parce que c'est le seul où la caméra est rendue. */
  const MODE_HINT=Object.freeze({
    off:'Caméra libérée. La posture en C ne peut pas rallumer Bare Hands.',
    sleep:`Guetteur léger (${Math.round(1000/BH.WAKE_INTERVAL_MS)} images par seconde, aucun clic) : la posture en C réveille l’interaction.`,
    active:`Les mains pilotent l’interface. Sans main exploitable, retour en veille au bout de ${Math.round(BH.SLEEP_TIMEOUT_MS/1000)} s.`,
  });

  /* -------------------------------------------------------- vue, sans DOM */

  /* Ce que la couture publie, traduit en ce que l'écran doit peindre. Pur :
     aucune lecture de page, aucune horloge — c'est ce que les tests exercent
     sans navigateur. */
  function presentationOf(snapshot){
    const snap=snapshot&&typeof snapshot==='object'?snapshot:{};
    const lifecycle=BH.LIFECYCLES.includes(String(snap.lifecycle))
      ?String(snap.lifecycle)
      :BH.lifecycleOfControllerState(String(snap.state||BH.LIFECYCLE.OFF));
    const starting=!!snap.starting;
    const tone=starting?TONE.STARTING:lifecycle;
    return Object.freeze({
      tone,lifecycle,starting,
      /* La pastille cochée. **Aucune** pendant un démarrage (rien n'a encore
         atterri) et aucune sur une panne (personne ne l'a choisie) : cocher
         `off` dans ces deux cas est précisément le mensonge que la décision 7
         et le contrat § 1 refusent. */
      selected:!starting&&MODES.includes(lifecycle)?lifecycle:null,
      code:snap.code===undefined||snap.code===null?null:String(snap.code),
      title:String(snap.title||''),message:String(snap.message||''),
      enabled:!!snap.enabled,
      /* Une écriture de réglage en vol : `saveSettings` refuserait la suivante
         avec un mot que personne n'a demandé, donc le sélecteur se désarme et
         le bouton le montre. */
      busy:!!snap.busy,
    });
  }

  /* L'étiquette sous le bouton. Le démarrage y porte **son compteur** : c'est
     la seule chose qui distingue une attente qui avance d'une page figée, et
     elle continue de monter même quand les animations sont coupées. */
  function captionOf(view,seconds){
    if(view.tone===TONE.STARTING)return `${CAPTION.starting} ${Math.max(0,Math.round(seconds||0))} S`;
    return CAPTION[view.tone]||CAPTION.off;
  }

  /* La phrase lue par les lecteurs d'écran et affichée au survol. Elle dit
     l'état, le motif quand il y en a un, et **comment en sortir** quand
     l'attente peut durer. */
  function labelOf(view,seconds){
    if(view.tone===TONE.STARTING)
      return `Bare Hands démarre depuis ${Math.max(0,Math.round(seconds||0))} secondes. `
        +'Si le navigateur attend votre autorisation, répondez à l’invite ; '
        +'choisissez Éteint pour annuler — la caméra est rendue dès qu’elle arrive.';
    if(view.tone===TONE.ERROR)
      return `Bare Hands s’est interrompu${view.code?` (${view.code})`:''}. `
        +`${view.message||view.title} Choisissez un mode pour relancer.`;
    return `Bare Hands : ${MODE_LABEL[view.tone]||view.tone}. Ouvrir le choix du mode.`;
  }

  /* Le bandeau du sélecteur : ce qu'il faut savoir avant de choisir. Vide
     quand il n'y a rien à dire — un bandeau permanent cesse d'être lu. */
  function noteOf(view,seconds,failure){
    if(failure)return {tone:'bad',text:failure};
    if(view.tone===TONE.ERROR)
      return {tone:'bad',text:`${view.title}${view.code?` · ${view.code}`:''} — ${view.message}`};
    if(view.tone===TONE.STARTING)
      return {tone:'wait',text:`Démarrage depuis ${Math.max(0,Math.round(seconds||0))} s. `
        +'Choisir Éteint annule et rend la caméra.'};
    /* L'interrupteur maître dit non alors que le moteur tourne : cela arrive
       quand l'enregistrement du réglage a échoué (le moteur suit, le fichier
       non). Le dire plutôt que le laisser découvrir au rechargement. */
    if(!view.enabled&&BH.isLiveLifecycle(view.lifecycle))
      return {tone:'wait',text:'Le réglage n’a pas été enregistré : Bare Hands sera éteint au prochain chargement.'};
    return null;
  }

  /* Pourquoi « Calibrer… » ne se choisit pas, **quand** il ne se choisit pas.

     Les deux refus que `startCalibration` connaît d'avance sont connaissables
     d'ici aussi, donc l'entrée les dit plutôt que de laisser l'utilisateur
     cliquer pour apprendre. Ils gardent leur **code du moteur** — jamais un
     code inventé ici pour l'occasion.

     Depuis la Slice 08 ces deux codes sont **distincts** : le réglage décoché
     reste `barehands_calibration_disabled`, l'extinction de Bare Hands prend
     `barehands_calibration_lifecycle_off`. Ils partageaient un code et ne se
     distinguaient que par la phrase, ce qui obligeait tout appelant — la voix
     en premier — à lire du français pour choisir entre deux remèdes
     incompatibles. Les deux valeurs se lisent toujours du moteur et cette
     table doit suivre `startCalibration` ligne pour ligne :
     `test_calibration_says_why_it_cannot_be_chosen` tombe si elles divergent.

     Le troisième, `barehands_calibration_no_camera`, n'est **pas** anticipé et
     c'est délibéré : depuis une panne, `activate()` peut parfaitement
     reprendre la caméra. Griser l'entrée dirait « ça ne marchera pas » là où
     la vérité est « il faut essayer pour savoir ». Il reste donc un refus à
     l'exécution, avec son toast et sa cause réelle.

     `settings` vaut `null` quand la surface n'a pas pu être lue : c'est une
     troisième cause, et elle ne se déguise pas en « décoché ». */
  function calibrationBlockOf(view,settings){
    if(!settings)
      return Object.freeze({code:'barehands_hud_surface_missing',
        reason:'les réglages Bare Hands ne sont pas lisibles dans cette page'});
    if(!settings.calibrationEnabled)
      return Object.freeze({code:'barehands_calibration_disabled',
        reason:'« Proposer la calibration » est décoché dans les réglages'});
    if(!view.enabled)
      return Object.freeze({code:'barehands_calibration_lifecycle_off',
        reason:'Bare Hands est éteint : choisissez Veille ou Actif d’abord'});
    return null;
  }

  /* Le modèle du menu, **pur** : ni page, ni horloge, ni surface. C'est la
     forme que `showMenu` attend (`{act,label,note?}`), produite ici pour
     qu'un test puisse vérifier « exactement ces quatre entrées, dans cet
     ordre, et pas d'activation ni de tutoriel » sans ouvrir de navigateur.

     Un refus se **dit** : l'entrée grisée porte sa raison dans son libellé.
     `note` la marque `aria-disabled` plutôt que `disabled`, exprès — un bouton
     vraiment `disabled` n'est pas atteignable au clavier, donc un lecteur
     d'écran n'apprendrait jamais pourquoi l'action manque. C'est aussi
     pourquoi la feuille de la page laisse ces libellés-là revenir à la ligne. */
  function quickItemsOf(view,settings){
    const blocked=calibrationBlockOf(view,settings);
    return Object.freeze(QUICK_ORDER.map(act=>{
      const stop=act===QUICK.CALIBRATION?blocked:null;
      return Object.freeze(stop
        ?{act,label:`${QUICK_LABEL[act]} — ${stop.reason}.`,note:stop.code}
        :{act,label:QUICK_LABEL[act]});
    }));
  }

  /* ============================================ l'aide, dérivée du contrat

     Décision 15 : l'aide devient une carte visuelle aérée, et non le bloc de
     texte dense qui vivait dans l'onglet Expérimental.

     **La contrainte dure est ailleurs que dans la mise en page.** Une aide qui
     énumère des gestes devient, le jour où elle se trompe, un *second* contrat
     de gestes — et c'est le premier qui a raison, sans que personne le sache.
     Tout ce qui peut être lu du contrat l'est donc :

     - les états et leurs conséquences viennent de `MODE_HINT` / `CAPTION`, qui
       sont déjà, dix lignes plus haut, les phrases du sélecteur de mode. Deux
       rédactions du même fait auraient divergé au premier ajustement ;
     - la durée du maintien en C, le délai de retour en veille et la cadence du
       guetteur viennent de `BH.WAKE_HOLD_MS`, `BH.SLEEP_TIMEOUT_MS` et
       `BH.WAKE_INTERVAL_MS` ;
     - les doigts de chaque canal viennent de `BH.PINCH_FINGERS` ;
     - les couleurs du retour visuel viennent de `BH.feedbackRole()` **appelée**
       et de `BH.FEEDBACK_TOKENS`, pas d'une table recopiée ;
     - la liste des gestes vient de `BH.GESTURES`.

     Ce qui ne peut **pas** se lire du contrat, c'est la **liaison** geste →
     action : elle vit dans le moteur d'interaction et nulle part ailleurs sous
     forme de donnée. Elle est donc écrite ici, une fois, avec le lieu qui la
     produit en commentaire — et la soustraction fait le reste. */

  /* Les gestes auxquels une action est **réellement** liée aujourd'hui.

     Un seul : la posture en C. Elle réveille l'interaction depuis la veille,
     par `createWakeDetector` / `cPoseScore` dans `watch()`
     (`control_center_barehands.js`), et non par l'événement `GESTURE.C_POSE`,
     qui ne tourne qu'en actif et que personne ne consomme.

     Les quatre autres — main ouverte, poing, double fermeture, claquement —
     sont mesurés et publiés à chaque image et **rien ne les écoute**. Ils ne
     sont donc pas des commandes, et cette carte ne les présente pas comme
     telles.

     La liste des **non liés** n'est pas écrite : elle est déduite par
     soustraction de `BH.GESTURES`. Conséquence voulue — un geste ajouté demain
     au contrat arrive ici **sans effet annoncé**, ce qui est la seule valeur
     par défaut acceptable pour une aide. Promettre une action que personne n'a
     branchée est la faute que cette Slice existe pour empêcher. */
  const GESTURE_BOUND=Object.freeze([BH.GESTURE.C_POSE]);
  const GESTURE_LABEL=Object.freeze({
    [BH.GESTURE.C_POSE]:'Posture en C',
    [BH.GESTURE.OPEN_PALM]:'Main ouverte',
    [BH.GESTURE.FIST]:'Poing',
    [BH.GESTURE.DOUBLE_CLOSE]:'Double fermeture',
    [BH.GESTURE.CLAP]:'Claquement des deux paumes',
  });
  /* Un geste du contrat dont cette carte n'a pas la phrase française. Il
     n'est **pas** caché : le cacher ferait disparaître de l'aide un geste que
     le moteur reconnaît, ce qui est précisément le silence qu'on refuse. Il
     paraît sous son identifiant brut, et se dit sous un nom cherchable. */
  const UNNAMED_GESTURE='barehands_help_gesture_unnamed';

  /* Ce que chaque canal de pincement **fait**, aujourd'hui, pour de vrai.

     Primaire (pouce-index) : `INTERACTION.CLICK`, `SELECT`, `DRAG_*`,
     `SCROLL`, et `MOVE` / `RESIZE` sur un cadre — toutes publiées par
     `createInteractionEngine`.

     Secondaire (pouce-majeur) : `INTERACTION.CONTEXT`, qui part en un vrai
     `contextmenu` du DOM. **Il est lié**, et le bloc d'aide qu'on remplace
     disait le contraire — il le rangeait parmi les « reconnus, pas encore
     agissants ». C'est la raison pour laquelle rien de cette carte n'a été
     recopié de lui. */
  const CHANNEL_TITLE=Object.freeze({
    [BH.PINCH_CHANNEL.PRIMARY]:'Pincement principal',
    [BH.PINCH_CHANNEL.SECONDARY]:'Pincement secondaire',
  });
  const CHANNEL_ACTIONS=Object.freeze({
    [BH.PINCH_CHANNEL.PRIMARY]:Object.freeze([
      'Cliquer : pincer puis rouvrir sans bouger.',
      'Sélectionner : sur un champ de saisie ou un objet de la scène.',
      'Glisser et faire défiler : pincer, puis déplacer la main.',
      'Déplacer ou redimensionner un cadre : par son bord ou son coin, à une ou deux mains.',
    ]),
    [BH.PINCH_CHANNEL.SECONDARY]:Object.freeze([
      'Clic droit : ouvre le menu contextuel, exactement comme une souris.',
    ]),
  });
  /* Les postures que la carte dessine pour chaque canal : ouvert, puis fermé.
     Ce sont des noms du vocabulaire de dessin, pas des noms de gestes. */
  const CHANNEL_POSES=Object.freeze({
    [BH.PINCH_CHANNEL.PRIMARY]:Object.freeze(['pinch_primary_open','pinch_primary_closed']),
    [BH.PINCH_CHANNEL.SECONDARY]:Object.freeze(['pinch_secondary_open','pinch_secondary_closed']),
  });
  /* Le nom français d'un bout de doigt. `PINCH_FINGERS` les donne en rôles de
     points (`thumbTip`, `indexTip`, `middleTip`) : la carte les traduit, elle
     ne réécrit pas quels doigts font quel canal. */
  const FINGER_LABEL=Object.freeze({thumbTip:'pouce',indexTip:'index',middleTip:'majeur'});

  /* Les trois combinaisons qui font apparaître les trois couleurs du retour
     visuel. La couleur n'est **pas** écrite ici : `BH.feedbackRole()` est
     appelée avec la région et le canal, et c'est elle qui tranche. Si sa règle
     change, cette carte change avec elle sans qu'on y touche. */
  const FEEDBACK_CASES=Object.freeze([
    Object.freeze({region:BH.REGION.BODY,channel:BH.PINCH_CHANNEL.PRIMARY,
      text:'Le corps d’un objet : on le prend, on le déplace, on le clique.'}),
    Object.freeze({region:BH.REGION.EDGE,channel:BH.PINCH_CHANNEL.PRIMARY,
      text:'Un bord ou un coin : la zone qui déplace ou redimensionne un cadre.'}),
    Object.freeze({region:BH.REGION.BODY,channel:BH.PINCH_CHANNEL.SECONDARY,
      text:'Le pincement secondaire, où qu’il vise : c’est un clic droit.'}),
  ]);
  const FEEDBACK_LABEL=Object.freeze({
    [BH.FEEDBACK.BODY]:'Bleu',[BH.FEEDBACK.ZONE]:'Jaune',[BH.FEEDBACK.SECONDARY]:'Rouge',
  });

  const round=(ms,unit)=>Math.round(Number(ms)/unit);

  /* **Le modèle complet de l'aide, pur.** Aucune page, aucune horloge : c'est
     lui que les tests interrogent pour vérifier, sans navigateur, qu'aucun
     geste non lié n'est présenté comme une commande. */
  function helpModel(){
    const fingersOf=channel=>(BH.PINCH_FINGERS[channel]||[])
      .map(finger=>FINGER_LABEL[finger]||String(finger));
    return Object.freeze({
      title:'Aide · Gestes',
      /* Les trois états, dans l'ordre du sélecteur et avec **ses** phrases. */
      lifecycle:Object.freeze(MODES.map(mode=>Object.freeze({
        mode,caption:CAPTION[mode],label:MODE_LABEL[mode],hint:MODE_HINT[mode],
        pose:'rest',
      }))),
      wake:Object.freeze({
        title:'Réveiller d’un geste',
        pose:'wake_c',
        holdMs:BH.WAKE_HOLD_MS,
        sleepMs:BH.SLEEP_TIMEOUT_MS,
        text:`Depuis la veille, formez un C avec le pouce et l’index — écartés sans se toucher, `
          +`index déplié — et tenez ${round(BH.WAKE_HOLD_MS,1000)} seconde. L’anneau se remplit `
          +`autour de la main ; rouvrir avant la fin annule.`,
        /* Le retour en veille est un **défaut** réglable, et le dire ainsi
           évite qu'une aide contredise un réglage que l'utilisateur a changé. */
        back:`Sans main sûre pendant ${round(BH.SLEEP_TIMEOUT_MS,1000)} secondes (valeur par défaut, `
          +`réglable), l’interaction retourne en veille. La caméra reste ouverte pour le guetteur.`,
      }),
      pinch:Object.freeze(BH.PINCH_CHANNELS.map(channel=>Object.freeze({
        channel,
        title:CHANNEL_TITLE[channel]||channel,
        fingers:Object.freeze(fingersOf(channel)),
        /* « pouce et index », construit depuis le contrat : si un canal
           changeait de doigts, cette phrase changerait toute seule. */
        subtitle:fingersOf(channel).join(' et '),
        poses:CHANNEL_POSES[channel],
        actions:CHANNEL_ACTIONS[channel]||Object.freeze([]),
      }))),
      feedback:Object.freeze(FEEDBACK_CASES.map(seen=>{
        const role=BH.feedbackRole(seen.region,seen.channel);
        const token=BH.FEEDBACK_TOKENS[role];
        return Object.freeze({
          role,label:FEEDBACK_LABEL[role]||role,text:seen.text,
          /* La valeur vit dans le thème de la page ; seul le nom de la
             variable est un contrat. La pastille lit donc la variable, avec
             son repli — exactement comme le moteur qui peint à l'écran. */
          color:`var(${token.cssVar},${token.fallback})`,
        });
      })),
      /* **La légende du jeton** (Slice 08, vérités replacées).

         La Slice 04 a supprimé le bloc « Gestes » des réglages, à juste titre :
         deux de ses phrases étaient devenues fausses. Mais quatre phrases
         **vraies** sont parties avec, et deux d'entre elles décrivent ce que
         l'utilisateur a sous les yeux — le jeton rond, et le jeton pâle et
         pointillé d'une main que le suivi ne tient pas pour sûre.

         Elles reviennent **ici** plutôt que dans les réglages, et c'est la
         RÈGLE ZÉRO qui tranche : un jeton pâle qu'on ne sait pas lire est
         exactement le cas où « ça marche » et « c'est cassé » se ressemblent.
         La réponse doit être à un clic de l'écran où la question se pose (clic
         droit → Aide), pas dans un modal de configuration qu'on n'ouvre pas en
         pleine session. Les deux autres phrases, qui sont des **limites** et
         non une légende, vont aux réglages (`settingsHtml`).

         Contrainte du § 16 tenue : les doigts viennent de `PINCH_FINGERS`, la
         durée de `SLEEP_TIMEOUT_MS`. Et la pastille des mains est décrite par
         **ce qu'elle compte**, jamais par le littéral « MAINS · 1/2 » : ce
         libellé vit dans `control_center_barehands.js` et n'est pas un
         contrat, donc le citer ferait mentir l'aide le jour où il change. */
      reading:Object.freeze({
        title:'Ce que vous voyez à l’écran',
        /* Le littéral, comme `lifecycle` et `wake` juste au-dessus : ce modèle
           est **pur** et `HAND` n'est lu qu'au dessin. */
        pose:'pinch_target',
        token:`Chaque main suivie porte un jeton rond au bout de l’index ; il grossit quand il `
          +`survole un élément cliquable. Rapprocher ${fingersOf(BH.PINCH_CHANNEL.PRIMARY).join(' et ')} `
          +`remplit l’anneau du jeton et le fige pour viser ; le pincement franc dépose le clic `
          +`sous le jeton, avec une onde. Rouvrez les doigts avant de recliquer.`,
        /* Aucun astérisque de mise en forme dans ces phrases : elles partent en
           `textContent`, et la Slice 07 a déjà dû réparer une consigne où deux
           paires d'astérisques s'affichaient telles quelles (`1912d91`). Le
           relief se fait en DOM, au dessin, pas dans la chaîne. */
        unsure:`Un jeton pâle et pointillé signale une main que le suivi ne tient pas pour `
          +`sûre — elle sort du cadre, elle est trop loin, ou elle vient d’apparaître. Elle reste `
          +`affichée et cliquable, mais elle ne compte pas parmi les mains sûres : seule une main `
          +`sûre retarde le retour en veille de ${round(BH.SLEEP_TIMEOUT_MS,1000)} secondes.`,
      }),
      /* **Les reconnus sans effet.** Déduits, jamais listés à la main. */
      unbound:Object.freeze(BH.GESTURES
        .filter(gesture=>!GESTURE_BOUND.includes(gesture))
        .map(gesture=>Object.freeze({
          gesture,
          label:GESTURE_LABEL[gesture]||gesture,
          named:!!GESTURE_LABEL[gesture],
        }))),
      unnamedCode:UNNAMED_GESTURE,
    });
  }

  /* ------------------------------------------------- la main schématique */

  const SVG_NS='http://www.w3.org/2000/svg';

  /* Décision 20 : des mains **schématiques**, en trait, pas d'anatomie.

     Le tracé ne vit plus ici. La Slice 01 l'avait posé dans ce module parce
     qu'il n'avait alors qu'un usage ; la Slice 04 lui en donne trois de plus
     (la carte d'aide) et les Slices 05 et 06 un quatrième (la calibration,
     qui ne peut pas dépendre de ce module-ci — elle est servie **avant** lui).
     Il est donc sorti dans `control_center_barehands_hand_art.js`, chargé
     avant la calibration, et ce module en devient un consommateur comme les
     autres. La posture `rest` y reproduit **exactement** le dessin servi
     jusqu'ici : même paume, mêmes os, mêmes points, même ordre.

     Lu directement et refusé à l'insertion, comme les contrats : un module de
     page absent est une erreur d'ordonnancement, pas un état d'exécution. */
  const HAND=root.JarvisBarehandsHandArt
    ||(typeof JarvisBarehandsHandArt!=='undefined'?JarvisBarehandsHandArt:null);
  if(!HAND)throw new Error('JarvisBarehandsHud : control_center_barehands_hand_art.js doit être inséré avant ce module');

  /* L'icône du bouton et des trois pastilles : la main au repos, à la taille
     demandée. La signature ne bouge pas — c'est celle que la Slice 01 a posée
     et que les tests appellent — seul son intérieur délègue. */
  function handIcon(doc,size){
    return HAND.handSvg(doc,{pose:HAND.POSE.REST,size,className:'bh-hud-icon'});
  }

  /* --------------------------------------- la palette d'outils, sans DOM

     Décision 11 : les outils sortent des réglages et deviennent une bande
     verticale **fixe** d'icônes sur le bord gauche, sous la main. Décision 12 :
     **seulement les outils installés aujourd'hui** — pointeur, main, sélection.
     Décision 13 : fixe et verticale ; déplacer, ancrer et pivoter sont
     reportés, et rien ici n'en prépare l'affordance.

     **Rien n'est recopié du contrat.** La liste, les libellés, la capacité et
     surtout l'**installation** se lisent par `BH.describeTools()` à chaque
     peinture. Une liste en dur ici serait la table qui dérive : déclarer
     demain un outil sans moteur le ferait apparaître choisissable et inerte,
     ce que le § 8 du contrat a précisément construit `SERVED_CAPABILITIES`
     pour empêcher. Ce module ne possède qu'une chose que le contrat n'a pas :
     la phrase française et le dessin. */

  /* Les trois états d'un bouton d'outil. L'échelle est **nommée ici et
     écrite une seule fois** dans la feuille, sur le modèle de `data-bh-tone`
     de la Slice 01 : le bouton, son halo, son rail et son libellé lisent la
     même définition par héritage de propriétés personnalisées, donc « actif »
     ne peut pas vouloir dire deux choses à deux endroits. */
  const SLOT=Object.freeze({ACTIVE:'active',IDLE:'idle',ABSENT:'absent'});

  /* Ce que chaque outil **fait**, en français. Reprises mot pour mot des
     réglages d'où la décision 11 les a sorties : la phrase était juste, et la
     réécrire aurait été une seconde version du même fait. */
  const TOOL_HINT=Object.freeze({
    [BH.TOOL.POINTER]:'Contextuel : clic, glissement, défilement ou sélection selon ce qu’il y a sous la main. C’est le comportement par défaut, et il ne force rien.',
    [BH.TOOL.PAN]:'Le contenu suit la main. Une cible qui ne défile pas est refusée, avec un mot à l’écran.',
    [BH.TOOL.SELECT]:'Désigner et sélectionner. Réservé aux champs de saisie et aux étoiles de la scène ; ailleurs, refusé.',
  });
  /* Le motif d'un outil déclaré au contrat mais qu'aucun moteur ne sert. Il
     existait dans les réglages et il revient tel quel, parce que c'est
     exactement la phrase qui empêche « grisé » de se lire « cassé ». */
  const UNAVAILABLE='Aucun moteur derrière cet outil en V1.';
  /* Un outil **installé** dont ce module n'a pas le dessin. Ce n'est pas un
     état d'exécution, c'est la recette d'extension à moitié suivie (contrat
     § 8 : `TOOL`, `TOOL_CAPABILITY`, `TOOL_LABEL`, puis la capacité servie —
     et, pour l'écran, ces deux tables-ci). L'outil reste **choisissable**, lui
     : c'est son dessin qui manque, pas son moteur, et le refuser priverait
     l'utilisateur d'un outil qui marche. Il porte donc une marque de substitut
     et se dit sous un nom cherchable plutôt que d'apparaître comme un carré
     vide. Un test de parité le refuse avant qu'un humain ne le voie. */
  const ARTLESS='barehands_palette_icon_missing';

  /* Pourquoi la palette est en veille, par présentation. Elle ne redit
     **jamais** le cycle de vie à l'écran : le contrôle de la barre du haut est
     à 100 px au-dessus, dans la même colonne, et son étiquette dit déjà
     ÉTEINT / DÉMARRAGE / INTERROMPU. Deux textes pour un même fait apprennent
     à n'en lire aucun. Ce que la palette ajoute est ce que le contrôle ne dit
     pas : ce que devient **l'outil** pendant ce temps-là. */
  const DORMANT=Object.freeze({
    [TONE.OFF]:'Bare Hands est éteint : l’outil reste choisi et s’appliquera au prochain allumage.',
    [TONE.STARTING]:'Bare Hands démarre : l’outil reste choisi et s’appliquera dès que la main sera suivie.',
    [TONE.ERROR]:'Bare Hands est interrompu : l’outil reste choisi et s’appliquera à la reprise.',
  });

  /* **Le modèle complet de la palette, pur.** Une seule fonction décide des
     trois états, de la veille et de chaque libellé ; la peinture ne fait que
     l'appliquer et les tests l'exercent sans navigateur. C'est la discipline
     de la Slice 01 — l'échelle écrite une fois — appliquée à deux surfaces qui
     pourraient diverger : le bouton et ce qu'il annonce.

     `tool` est l'instantané de la couture d'outil ; `view` celui du cycle de
     vie, tel que `presentationOf` l'a déjà traduit. Deux sources, parce que ce
     sont deux faits de deux propriétaires. */
  function paletteOf(tool,view){
    const seen=view&&typeof view==='object'?view:presentationOf(null);
    /* L'outil que les réglages appliquent. Un nom hors table ne se replie
       **pas** sur « pointeur » en silence : la palette ne cocherait alors rien
       plutôt que de cocher un outil que personne n'a choisi. */
    const active=BH.TOOLS.includes(String(tool))?String(tool):null;
    /* Vivante en veille **et** en actif, et c'est la même ligne que le
       contrôle du dessus trace déjà (`MODE_HINT` : « OFF est le seul où le
       réveil en C ne peut rien »). En veille la caméra est tenue et la posture
       en C rend la main à l'interaction tout de suite : l'outil est à un geste
       de servir. Éteint, en panne ou en démarrage, rien ne tient la caméra et
       la palette le montre. */
    const live=BH.isLiveLifecycle(seen.lifecycle)&&!seen.starting;
    const busy=!!seen.busy;
    const dormant=live?null:(DORMANT[seen.tone]||DORMANT[TONE.OFF]);
    const items=BH.describeTools().map(tool_=>{
      const art=!!TOOL_ART[tool_.id];
      const state=!tool_.installed?SLOT.ABSENT
        :tool_.id===active?SLOT.ACTIVE:SLOT.IDLE;
      /* **Un outil sans moteur n'est pas un contrôle.** Ni cliquable, ni
         activable au clavier, et `aria-disabled` plutôt que `disabled` —
         exactement le choix de la Slice 02 pour « Calibrer… » bloqué : un
         bouton vraiment `disabled` sort du parcours clavier, donc un lecteur
         d'écran n'apprendrait **jamais** pourquoi l'outil manque. Il reste
         atteignable et il dit sa raison ; il ne se choisit pas. */
      const selectable=tool_.installed&&!busy;
      const hint=TOOL_HINT[tool_.id]||'';
      const reason=!tool_.installed?UNAVAILABLE:'';
      return Object.freeze({
        id:tool_.id,label:tool_.label,capability:tool_.capability,
        installed:tool_.installed,art,state,selectable,hint,reason,
        /* Ce que le survol et le lecteur d'écran reçoivent : l'outil, ce qu'il
           fait, puis **ce qui l'empêche** quand quelque chose l'empêche. Les
           trois empêchements sont distincts et ne se déguisent pas l'un en
           l'autre : pas de moteur, pas de dessin, Bare Hands en veille. */
        title:[`${tool_.label} — ${hint}`,reason,
          art?'':`Icône manquante pour cet outil (${ARTLESS}).`,
          dormant||''].filter(Boolean).join(' '),
      });
    });
    return Object.freeze({
      active,live,busy,dormant:dormant||null,
      tone:seen.tone,
      /* L'étiquette sous la bande : le **nom** de l'outil actif, en plus de
         son icône. Deux canaux pour « lequel est choisi » — la forme et le
         mot — parce que c'est le critère que l'Humain juge à l'œil. */
      caption:active?String((BH.TOOL_LABEL&&BH.TOOL_LABEL[active])||active).toUpperCase():'—',
      items:Object.freeze(items),
    });
  }

  /* ------------------------------------------------- les icônes d'outils

     Décision de l'affinage : **des icônes, pas des étiquettes de trois
     lettres**, dans le vocabulaire de trait que la Slice 01 a posé — même
     grille de 24, même trait de 1.5, mêmes bouts ronds, mêmes points pleins
     aux articulations. Le point, ici, marque le **point chaud** de l'outil :
     la pointe du curseur, le centre de prise, la cible désignée.

     Aucun des trois n'est une seconde main. La main schématique est déjà,
     juste au-dessus, l'identité de Bare Hands lui-même ; redessiner la même
     main pour « Main » aurait mis deux mains dans la même colonne avec deux
     sens différents, et le coin haut-gauche serait devenu illisible. `pan` est
     donc dessiné par ce qu'il **fait** — le contenu suit la main, dans les
     quatre directions — ce que sa propre phrase dit déjà.

     `select` n'est **pas** un rectangle de sélection en pointillés : cet outil
     désigne un objet nommé (un champ, une étoile), il ne tire pas un cadre
     autour d'une région. Des équerres de visée autour d'une cible pleine
     disent ce qu'il fait ; un lasso aurait promis un geste qui n'existe pas. */
  const TOOL_ART=Object.freeze({
    [BH.TOOL.POINTER]:Object.freeze({
      paths:Object.freeze(['M6 3.6v14.8l3.8-3.7 2.3 5.3 2.6-1.1-2.2-5.2 5.1-.4z']),
      dots:Object.freeze([[6,3.6]]),
    }),
    [BH.TOOL.PAN]:Object.freeze({
      paths:Object.freeze([
        'M12 4.4v15.2','M4.4 12h15.2',
        'M9.6 6.8 12 4.4l2.4 2.4','M9.6 17.2 12 19.6l2.4-2.4',
        'M6.8 9.6 4.4 12l2.4 2.4','M17.2 9.6 19.6 12l-2.4 2.4',
      ]),
      dots:Object.freeze([[12,12]]),
    }),
    [BH.TOOL.SELECT]:Object.freeze({
      paths:Object.freeze([
        'M4.7 9.2V6.1a1.4 1.4 0 0 1 1.4-1.4h3.1',
        'M14.8 4.7h3.1a1.4 1.4 0 0 1 1.4 1.4v3.1',
        'M19.3 14.8v3.1a1.4 1.4 0 0 1-1.4 1.4h-3.1',
        'M9.2 19.3H6.1a1.4 1.4 0 0 1-1.4-1.4v-3.1',
      ]),
      dots:Object.freeze([[12,12,2.1]]),
    }),
  });

  /* Le substitut d'un outil installé dont le dessin manque : un carré en
     pointillés, qui ne ressemble à aucun des trois et ne prétend donc rien. */
  const ART_MISSING=Object.freeze({
    paths:Object.freeze(['M6.5 6.5h11v11h-11z']),dots:Object.freeze([]),dashed:true,
  });

  function toolIcon(doc,id,size){
    const art=TOOL_ART[id]||ART_MISSING;
    const svg=doc.createElementNS(SVG_NS,'svg');
    svg.setAttribute('viewBox','0 0 24 24');
    svg.setAttribute('class','bh-tool-icon');
    svg.setAttribute('width',String(size));svg.setAttribute('height',String(size));
    svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');
    svg.setAttribute('stroke-width','1.5');
    svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');
    svg.setAttribute('aria-hidden','true');svg.setAttribute('focusable','false');
    for(const d of art.paths){
      const path=doc.createElementNS(SVG_NS,'path');
      path.setAttribute('d',d);
      if(art.dashed)path.setAttribute('stroke-dasharray','2.5 2.5');
      svg.appendChild(path);
    }
    for(const dot of art.dots){
      const mark=doc.createElementNS(SVG_NS,'circle');
      mark.setAttribute('cx',String(dot[0]));mark.setAttribute('cy',String(dot[1]));
      mark.setAttribute('r',String(dot[2]===undefined?0.95:dot[2]));
      mark.setAttribute('fill','currentColor');mark.setAttribute('stroke','none');
      svg.appendChild(mark);
    }
    return svg;
  }

  /* ------------------------------------------------------------- la feuille

     Les couleurs passent par l'indirection de thème, comme partout ailleurs
     dans Bare Hands : jamais un hexadécimal nu, toujours le jeton suivi de son
     repli. L'échelle des trois tons est écrite **une seule fois** et portée
     par `data-bh-tone` : le bouton et les trois pastilles du sélecteur la
     lisent par héritage de propriétés personnalisées, donc « actif » a la même
     définition aux deux endroits, par construction et non par recopie. */
  /* **Pourquoi `--omega-accent` n'est plus dans cette chaîne.**

     Ce n'est pas une couleur de thème : `control_center_work.js` l'écrit sur
     `document.documentElement` à *chaque changement d'état vocal*, depuis
     `STATE_COLORS` — `idle` bleu, `listening` **vert**, `speaking`
     **orange**, `thinking` violet. C'est la couleur de l'orbe, et l'orbe a
     raison de l'avoir : elle dit ce que fait la voix.

     Bare Hands, lui, ne dit pas ce que fait la voix. Tant que la voix était
     poussée au bouton, l'état dominant était `idle` et la colonne paraissait
     bleue ; depuis que le duplex GPT-Live parle en continu, l'état dominant
     est `speaking` et la colonne entière — bouton de cycle de vie, palette,
     outil actif, libellés — est peinte en `rgb(255,151,61)`. L'utilisateur l'a
     vu avant nous : « c'est en orange alors que la couleur principale, c'est
     le bleu ».

     La colonne reprend donc le bleu de la page (`--accent`, #6ee7ff, celui de
     la barre d'outils, des badges et des compteurs), sans passer par l'état
     vocal. Les deux bleus que décrit la décision 5 restent portés par
     l'échelle `data-bh-tone` juste en dessous, et non par une seconde teinte :
     au repos l'encre est diluée dans le transparent, en actif elle est
     éclaircie vers le blanc et porte le halo — bleu ordinaire contre bleu
     électrique. `--bh-accent` reste ouvert pour qui voudra surcharger. */
  const ACCENT='var(--bh-accent,var(--accent,#6ee7ff))';
  const MUTED='var(--omega-muted,var(--muted,#7190a0))';
  const DANGER='var(--omega-danger,var(--danger,#ff6577))';

  /* La géométrie de la colonne du haut-gauche, **écrite une seule fois**.

     La Slice 01 posait ses quatre nombres en clair dans la feuille ; ils y
     étaient seuls, donc justes. La Slice 03 pose une seconde boîte **sous**
     la première, et cette boîte doit connaître la hauteur de la première pour
     ne pas la chevaucher. Deux copies du même empilement auraient tenu
     jusqu'au jour où l'une des deux bouge — et le symptôme aurait été une
     palette par-dessus l'étiquette du bouton, c'est-à-dire un défaut visuel
     qu'aucun test de comportement n'attrape. Les valeurs sont celles de la
     Slice 01, inchangées ; seul leur lieu change.

     `capLine` : `.bh-hud-cap` est en 9 px et hérite du rapport 1.2 de la
     colonne, donc 10.8 px arrondis à 11. */
  const GEO=Object.freeze({
    top:76,left:18,button:64,gap:7,capLine:11,
    /* Le blanc entre l'étiquette du contrôle et le haut de la palette. */
    split:10,
    /* Sous 700 px, la barre du haut se resserre et la bannière GPT-Live occupe
       le coin : la colonne entière descend sur le bord gauche. Le décalage du
       contrôle est celui de la Slice 01 ; la palette s'en déduit. */
    narrowLeft:10,narrowTop:-41,
  });
  /* Hauteur du contrôle de cycle de vie, étiquette comprise. */
  const HUD_BLOCK=GEO.button+GEO.gap+GEO.capLine;
  const PALETTE_TOP=GEO.top+HUD_BLOCK+GEO.split;
  const PALETTE_NARROW_TOP=GEO.narrowTop+HUD_BLOCK+GEO.split;

  const STYLE=`
/* **Aucun \`z-index\` sur l'emplacement, et c'est délibéré.** Un rang posé ici
   ouvrirait un contexte d'empilement, et le sélecteur — 36, au-dessus du
   bandeau GPT-Live — s'y retrouverait enfermé sous les 32 du bouton : il
   passerait derrière le panneau (33) et derrière la bannière (35) qu'il est
   censé recouvrir. Les rangs vivent donc sur les deux éléments positionnés
   eux-mêmes. Même raison pour la variante étroite plus bas, qui centre par
   \`calc()\` et non par \`transform\` : une transformation ouvre le même piège. */
#${DOM.hostId}{position:absolute;top:${GEO.top}px;left:${GEO.left}px;width:${GEO.button}px;
  display:flex;flex-direction:column;align-items:center;gap:${GEO.gap}px;
  font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;
  /* \`.topbar\` coupe les événements de pointeur pour laisser passer les clics
     vers le visage. Ce contrôle vit à côté d'elle et non dedans, mais il les
     rétablit chez lui : rangé un jour sous un parent inerte, il resterait
     cliquable au lieu de se taire. */
  pointer-events:auto}
#${DOM.hostId}[data-bh-tone=off],#${DOM.hostId} [data-bh-tone=off]{
  --bh-hud-ink:color-mix(in srgb,${MUTED} 55%,transparent);
  --bh-hud-line:color-mix(in srgb,${MUTED} 20%,transparent);
  --bh-hud-face:rgba(3,8,12,.62);--bh-hud-glow:none;
  --bh-hud-cap:color-mix(in srgb,${MUTED} 72%,transparent)}
#${DOM.hostId}[data-bh-tone=sleep],#${DOM.hostId} [data-bh-tone=sleep],
#${DOM.hostId}[data-bh-tone=starting]{
  --bh-hud-ink:color-mix(in srgb,${ACCENT} 78%,transparent);
  --bh-hud-line:color-mix(in srgb,${ACCENT} 26%,transparent);
  --bh-hud-face:rgba(3,8,12,.82);--bh-hud-glow:none;
  --bh-hud-cap:color-mix(in srgb,${ACCENT} 68%,transparent)}
/* Plus clair **et** entouré : c'est la seule présentation qui porte un halo,
   et c'est ce qui la rend lisible d'un coup d'œil à côté de la veille. */
#${DOM.hostId}[data-bh-tone=active],#${DOM.hostId} [data-bh-tone=active]{
  --bh-hud-ink:color-mix(in srgb,${ACCENT} 84%,#fff);
  --bh-hud-line:color-mix(in srgb,${ACCENT} 66%,transparent);
  --bh-hud-face:color-mix(in srgb,${ACCENT} 9%,rgba(3,8,12,.86));
  --bh-hud-glow:0 0 0 1px color-mix(in srgb,${ACCENT} 24%,transparent),
    0 0 26px color-mix(in srgb,${ACCENT} 30%,transparent),
    inset 0 0 20px color-mix(in srgb,${ACCENT} 12%,transparent);
  --bh-hud-cap:color-mix(in srgb,${ACCENT} 88%,#fff)}
#${DOM.hostId}[data-bh-tone=error]{
  --bh-hud-ink:color-mix(in srgb,${DANGER} 88%,transparent);
  --bh-hud-line:color-mix(in srgb,${DANGER} 52%,transparent);
  --bh-hud-face:rgba(22,6,10,.86);
  --bh-hud-glow:0 0 20px color-mix(in srgb,${DANGER} 24%,transparent);
  --bh-hud-cap:${DANGER}}
#${DOM.hostId} .bh-hud-btn{position:relative;z-index:32;width:64px;height:64px;display:grid;place-items:center;
  padding:0;border:1px solid var(--bh-hud-line);border-radius:12px;background:var(--bh-hud-face);
  color:var(--bh-hud-ink);box-shadow:var(--bh-hud-glow);cursor:pointer;
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px);
  transition:color .18s ease,border-color .18s ease,box-shadow .26s ease,background .18s ease,transform .12s ease}
#${DOM.hostId} .bh-hud-btn:hover{border-color:color-mix(in srgb,var(--bh-hud-ink) 72%,transparent)}
#${DOM.hostId} .bh-hud-btn:active{transform:scale(.96)}
#${DOM.hostId} .bh-hud-btn:focus-visible{outline:2px solid ${ACCENT};outline-offset:3px}
#${DOM.hostId} .bh-hud-icon{display:block;color:inherit}
/* Le halo qui respire, et lui seul : l'actif est le seul état où quelque
   chose tourne vraiment, donc le seul à avoir le droit de bouger au repos. */
#${DOM.hostId}[data-bh-tone=active] .bh-hud-btn::before{content:'';position:absolute;inset:-7px;
  border-radius:17px;pointer-events:none;
  background:radial-gradient(closest-side,color-mix(in srgb,${ACCENT} 20%,transparent),transparent 78%);
  animation:bhHudBreathe 3.6s ease-in-out infinite}
@keyframes bhHudBreathe{0%,100%{opacity:.5}50%{opacity:1}}
/* RÈGLE ZÉRO : une attente se voit bouger. Armée pendant le démarrage **et**
   pendant une écriture de réglage en vol — les deux peuvent durer, et une
   page immobile ne dit pas laquelle des deux. */
#${DOM.hostId} .bh-hud-wait{position:absolute;left:9px;right:9px;bottom:8px;height:2px;border-radius:2px;
  overflow:hidden;display:none;background:color-mix(in srgb,var(--bh-hud-ink) 22%,transparent)}
#${DOM.hostId}[data-bh-tone=starting] .bh-hud-wait,
#${DOM.hostId}[data-bh-busy=true] .bh-hud-wait{display:block}
#${DOM.hostId} .bh-hud-wait::after{content:'';position:absolute;top:0;bottom:0;left:0;width:42%;
  border-radius:2px;background:currentColor;animation:bhHudSweep 1.25s ease-in-out infinite}
@keyframes bhHudSweep{from{transform:translateX(-115%)}to{transform:translateX(255%)}}
/* Une panne ne se lit pas « éteint » : elle porte une marque qu'aucun mode ne
   porte, en plus de sa couleur. */
#${DOM.hostId} .bh-hud-alert{position:absolute;right:-4px;top:-4px;width:12px;height:12px;border-radius:50%;
  display:none;background:${DANGER};box-shadow:0 0 10px color-mix(in srgb,${DANGER} 60%,transparent)}
#${DOM.hostId}[data-bh-tone=error] .bh-hud-alert{display:block}
#${DOM.hostId} .bh-hud-cap{position:relative;z-index:32;width:max-content;max-width:136px;text-align:center;white-space:nowrap;
  font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--bh-hud-cap);
  transition:color .18s ease}
/* Le sélecteur : trois fois le **même** motif de main, directement cliquables
   (décision 6). Ni liste déroulante, ni cycle aveugle. */
#${DOM.hostId} .bh-hud-pop{position:absolute;z-index:36;top:100%;left:0;margin-top:12px;
  min-width:244px;padding:13px 14px 12px;border:1px solid var(--line,#183343);border-radius:12px;
  background:var(--panel,rgba(6,12,18,.94));box-shadow:0 18px 44px rgba(0,0,0,.5);
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
  animation:bhHudPop .16s ease-out}
#${DOM.hostId} .bh-hud-pop[hidden]{display:none}
@keyframes bhHudPop{from{opacity:0;transform:translateY(-6px)}to{opacity:1;transform:none}}
#${DOM.hostId} .bh-hud-pop h3{margin:0 0 10px;font-size:9px;font-weight:400;letter-spacing:.18em;
  text-transform:uppercase;color:${MUTED}}
#${DOM.hostId} .bh-hud-opts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}
#${DOM.hostId} .bh-hud-opt{display:flex;flex-direction:column;align-items:center;gap:7px;
  padding:9px 4px 8px;border:1px solid transparent;border-radius:10px;background:transparent;
  color:inherit;font:inherit;cursor:pointer;transition:background .14s ease,border-color .14s ease}
#${DOM.hostId} .bh-hud-opt:hover:not([disabled]){background:rgba(110,231,255,.05);border-color:var(--line,#183343)}
#${DOM.hostId} .bh-hud-opt:focus-visible{outline:2px solid ${ACCENT};outline-offset:2px}
#${DOM.hostId} .bh-hud-opt[disabled]{opacity:.45;cursor:not-allowed}
#${DOM.hostId} .bh-hud-opt[aria-checked=true]{border-color:color-mix(in srgb,${ACCENT} 45%,transparent);
  background:rgba(110,231,255,.07)}
#${DOM.hostId} .bh-hud-chip{width:46px;height:46px;display:grid;place-items:center;border-radius:10px;
  border:1px solid var(--bh-hud-line);background:var(--bh-hud-face);color:var(--bh-hud-ink);
  box-shadow:var(--bh-hud-glow)}
/* Le halo de l'actif, à l'échelle de la pastille : le même effet, pas la même
   taille — un halo de 64 px autour d'un carré de 46 px baverait sur ses
   voisins et « actif » cesserait d'être lisible comme un choix parmi trois. */
#${DOM.hostId} .bh-hud-chip[data-bh-tone=active]{
  box-shadow:0 0 0 1px color-mix(in srgb,${ACCENT} 24%,transparent),
    0 0 15px color-mix(in srgb,${ACCENT} 28%,transparent)}
#${DOM.hostId} .bh-hud-note{margin:0 0 10px;padding:7px 9px;border-radius:8px;font-size:10px;line-height:1.5;
  color:${DANGER};border:1px solid color-mix(in srgb,${DANGER} 34%,transparent);background:rgba(35,7,12,.45)}
#${DOM.hostId} .bh-hud-note[data-bh-note=wait]{color:var(--warn,#ffb85c);
  border-color:color-mix(in srgb,var(--warn,#ffb85c) 34%,transparent);background:rgba(38,23,5,.45)}
#${DOM.hostId} .bh-hud-note[hidden]{display:none}
#${DOM.hostId} .bh-hud-hint{margin:11px 0 0;font-size:10px;line-height:1.55;color:${MUTED};min-height:3.1em}
#${DOM.hostId} .bh-hud-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;
  clip:rect(0,0,0,0);white-space:nowrap;border:0}

/* ------------------------------------------------- la palette d'outils

   **Un rang d'empilement est posé ici, et contrairement au contrôle ci-dessus
   c'est sans danger.** La note de la Slice 01 vaut pour une boîte qui doit
   laisser sortir un enfant plus haut qu'elle : son sélecteur (36) serait
   enfermé sous le rang du bouton (32). La palette, elle, ne contient aucune
   surimpression — que ses propres icônes — donc le contexte d'empilement
   qu'elle ouvre n'enferme rien. Son rang (30) est **sous** le contrôle (32) et
   sous le sélecteur (36) exprès : le sélecteur s'ouvre par-dessus elle le
   temps d'un choix, et l'inverse aurait fait choisir un mode à l'aveugle.
   Pas de \`transform\` sur l'emplacement lui-même, pour la même raison que
   la Slice 01 n'en met pas — seules les pseudo-éléments en portent. */
#${DOM.paletteId}{position:absolute;z-index:30;
  top:${PALETTE_TOP}px;left:${GEO.left}px;width:${GEO.button}px;
  display:flex;flex-direction:column;align-items:center;gap:8px;
  font:12px/1.2 ui-monospace,SFMono-Regular,Consolas,monospace;
  /* Même précaution que le contrôle du dessus : rangée un jour sous un parent
     aux événements coupés, la palette resterait cliquable. */
  pointer-events:auto;
  transition:opacity .22s ease}
#${DOM.paletteId}[hidden]{display:none}
/* La bande elle-même : fixe, verticale, et rien qui suggère le contraire —
   pas de poignée, pas de bouton d'ancrage, pas de bascule d'orientation
   (décision 13 : c'est reporté, donc ce n'est pas esquissé). */
/* Le padding est **dissymétrique exprès** : 6 px en haut et en bas, 2 px sur
   les côtés. La bande est verticale — le blanc vertical sépare trois outils
   les uns des autres et sert donc à quelque chose, tandis que le blanc
   horizontal ne sépare rien : il ne faisait qu'élargir la gélule de 12 px
   autour d'icônes de 44, ce que l'utilisateur a appelé « un peu lourdingue ».
   58 px de large deviennent 50, et la cible de clic reste entière. */
#${DOM.paletteId} .bh-tools{display:flex;flex-direction:column;align-items:center;gap:6px;
  padding:6px 2px;border:1px solid var(--line,#183343);border-radius:13px;
  background:rgba(3,8,12,.62);
  -webkit-backdrop-filter:blur(12px);backdrop-filter:blur(12px)}
/* **L'échelle des trois états, écrite une seule fois**, sur le modèle de
   \`data-bh-tone\`. Le bouton, son rail, son halo et son icône la lisent par
   héritage : « actif » a une seule définition, par construction. */
#${DOM.paletteId} [${DOM.toolStateAttribute}=idle]{
  --bh-tool-ink:color-mix(in srgb,${ACCENT} 58%,transparent);
  --bh-tool-line:transparent;--bh-tool-face:transparent;--bh-tool-glow:none}
#${DOM.paletteId} [${DOM.toolStateAttribute}=active]{
  --bh-tool-ink:color-mix(in srgb,${ACCENT} 86%,#fff);
  --bh-tool-line:color-mix(in srgb,${ACCENT} 60%,transparent);
  --bh-tool-face:color-mix(in srgb,${ACCENT} 12%,rgba(3,8,12,.88));
  --bh-tool-glow:0 0 0 1px color-mix(in srgb,${ACCENT} 26%,transparent),
    0 0 16px color-mix(in srgb,${ACCENT} 30%,transparent),
    inset 0 0 14px color-mix(in srgb,${ACCENT} 12%,transparent)}
/* Sans moteur : **gris**, jamais bleu. La couleur seule ne suffit pas et ne
   prétend pas suffire — la barre oblique ci-dessous porte la même information
   sans dépendre d'une teinte. */
#${DOM.paletteId} [${DOM.toolStateAttribute}=absent]{
  --bh-tool-ink:color-mix(in srgb,${MUTED} 40%,transparent);
  --bh-tool-line:transparent;--bh-tool-face:transparent;--bh-tool-glow:none}
#${DOM.paletteId} .bh-tool{position:relative;width:44px;height:44px;display:grid;place-items:center;
  padding:0;border:1px solid var(--bh-tool-line);border-radius:10px;background:var(--bh-tool-face);
  color:var(--bh-tool-ink);box-shadow:var(--bh-tool-glow);cursor:pointer;
  transition:color .16s ease,border-color .16s ease,background .16s ease,
    box-shadow .22s ease,transform .12s ease}
#${DOM.paletteId} .bh-tool-icon{display:block;color:inherit}
#${DOM.paletteId} .bh-tool:hover[${DOM.toolStateAttribute}=idle]{
  background:rgba(110,231,255,.06);border-color:var(--line,#183343)}
#${DOM.paletteId} .bh-tool:active[${DOM.toolStateAttribute}=idle]{transform:scale(.94)}
#${DOM.paletteId} .bh-tool:focus-visible{outline:2px solid ${ACCENT};outline-offset:3px}
/* **Le rail : ce qui rend l'outil actif lisible d'un coup d'œil**, et ce qui
   continue de le rendre lisible quand la couleur ne peut plus rien — en veille
   de la palette, en contraste élevé, ou pour un œil qui ne sépare pas le bleu
   du gris. La forme dit ce que la teinte dit, deux fois plutôt qu'une. */
#${DOM.paletteId} .bh-tool[${DOM.toolStateAttribute}=active]::before{content:'';position:absolute;
  left:-5px;top:8px;bottom:8px;width:3px;border-radius:3px;background:currentColor;
  box-shadow:0 0 10px color-mix(in srgb,${ACCENT} 55%,transparent)}
/* Un outil sans moteur est **barré**. Il reste dessiné — le retirer ferait
   croire qu'il n'existe pas, alors qu'il est au contrat — et il reste
   atteignable au clavier pour dire pourquoi ; il ne se choisit pas. */
#${DOM.paletteId} .bh-tool[${DOM.toolStateAttribute}=absent]{cursor:not-allowed}
#${DOM.paletteId} .bh-tool[${DOM.toolStateAttribute}=absent]::after{content:'';position:absolute;
  left:10px;right:10px;top:50%;height:1px;background:currentColor;opacity:.8;
  transform:rotate(-38deg)}
#${DOM.paletteId} .bh-tool[disabled]{opacity:.45;cursor:progress}
/* **La veille de la palette** (décision 11 + contrainte du périmètre).
   Bare Hands éteint, en panne ou en démarrage : la palette ne disparaît pas —
   elle serait alors introuvable le jour où l'on rallume, et l'Humain l'a
   voulue visible sans ouvrir les réglages — et elle ne fait pas non plus
   semblant d'agir. Elle s'atténue, elle perd le halo (le halo veut dire
   « quelque chose tourne », et rien ne tourne), et elle **garde son rail** :
   quel outil est choisi reste vrai et reste lisible. Le motif est dans
   l'infobulle et dans l'annonce ; le cycle de vie, lui, est déjà écrit en
   toutes lettres 100 px plus haut dans la même colonne. */
#${DOM.paletteId}[data-bh-live=false]{opacity:.5}
#${DOM.paletteId}[data-bh-live=false] .bh-tool[${DOM.toolStateAttribute}=active]{box-shadow:none}
#${DOM.paletteId} .bh-tool-cap{width:max-content;max-width:${GEO.button}px;text-align:center;
  font-size:9px;letter-spacing:.14em;text-transform:uppercase;
  color:color-mix(in srgb,${ACCENT} 72%,transparent);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  transition:color .16s ease}
#${DOM.paletteId} .bh-hud-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;
  overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
/* ======================================= les deux cartes rapides (Slice 04)

   Décision 15 : « petite fenêtre aérée, des schémas, pas un mur de texte ».
   Tout ici sert cette phrase — une colonne unique, des blocs séparés par du
   blanc franc, un dessin par idée, et des libellés courts en capitales qui
   se balaient sans être lus.

   L'emplacement est une nappe plein écran : elle centre la carte sans
   \`transform\` (la note de la Slice 01 vaut ici aussi) et elle sert de cible
   au clic de fermeture. Elle n'existe à l'écran que carte ouverte ; fermée,
   elle est \`display:none\` et ne vole donc aucun clic à la page. */
#${DOM.cardsId}{position:fixed;z-index:82;inset:0;display:none;
  align-items:center;justify-content:center;padding:24px;
  background:rgba(2,6,10,.62);
  -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
  font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace}
#${DOM.cardsId}[${DOM.cardAttribute}]{display:flex}
#${DOM.cardsId} .bh-card{position:relative;width:min(640px,100%);max-height:100%;
  overflow:auto;padding:22px 24px 24px;border:1px solid var(--line,#183343);border-radius:14px;
  background:var(--panel,rgba(6,12,18,.94));box-shadow:0 26px 70px rgba(0,0,0,.6);
  -webkit-backdrop-filter:blur(18px);backdrop-filter:blur(18px);
  animation:bhHudPop .16s ease-out}
#${DOM.cardsId} .bh-card:focus-visible{outline:2px solid ${ACCENT};outline-offset:3px}
#${DOM.cardsId} .bh-card-head{display:flex;align-items:flex-start;gap:14px;margin-bottom:6px}
#${DOM.cardsId} .bh-card-eyebrow{font-size:9px;letter-spacing:.2em;text-transform:uppercase;
  color:${MUTED}}
#${DOM.cardsId} .bh-card h2{margin:3px 0 0;font-size:16px;font-weight:400;letter-spacing:.04em;
  color:var(--text,#d8edf7)}
#${DOM.cardsId} .bh-card-close{margin-left:auto;width:30px;height:30px;flex:none;
  display:grid;place-items:center;padding:0;border:1px solid var(--line,#183343);border-radius:8px;
  background:transparent;color:${MUTED};font:inherit;font-size:15px;line-height:1;cursor:pointer;
  transition:color .16s ease,border-color .16s ease}
#${DOM.cardsId} .bh-card-close:hover{color:${ACCENT};border-color:color-mix(in srgb,${ACCENT} 45%,transparent)}
#${DOM.cardsId} .bh-card-close:focus-visible{outline:2px solid ${ACCENT};outline-offset:2px}
/* Le blanc, et c'est le sujet de la décision 15 : chaque bloc respire, et le
   filet qui les sépare est plus discret que le texte qu'il sépare. */
#${DOM.cardsId} .bh-card-block{margin-top:22px;padding-top:20px;
  border-top:1px solid color-mix(in srgb,var(--line,#183343) 70%,transparent)}
#${DOM.cardsId} .bh-card-block:first-of-type{border-top:0;padding-top:0}
#${DOM.cardsId} .bh-card-block h3{margin:0 0 12px;font-size:9px;font-weight:400;
  letter-spacing:.18em;text-transform:uppercase;color:${MUTED}}
#${DOM.cardsId} .bh-card p{margin:0;color:var(--text,#d8edf7);opacity:.86}
#${DOM.cardsId} .bh-card-note{margin-top:9px;font-size:11px;color:${MUTED}}
/* Les trois états : le même dessin trois fois, et seule la teinte change —
   c'est la démonstration, pas l'illustration. */
#${DOM.cardsId} .bh-card-modes{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
#${DOM.cardsId} .bh-card-mode{display:flex;flex-direction:column;align-items:center;gap:8px;
  padding:12px 8px;border:1px solid color-mix(in srgb,var(--line,#183343) 80%,transparent);
  border-radius:10px;text-align:center}
#${DOM.cardsId} .bh-card-chip{width:46px;height:46px;display:grid;place-items:center;border-radius:10px;
  border:1px solid var(--bh-hud-line);background:var(--bh-hud-face);color:var(--bh-hud-ink);
  box-shadow:var(--bh-hud-glow)}
#${DOM.cardsId} .bh-card-chip[data-bh-tone=active]{
  box-shadow:0 0 0 1px color-mix(in srgb,${ACCENT} 24%,transparent),
    0 0 15px color-mix(in srgb,${ACCENT} 28%,transparent)}
#${DOM.cardsId} .bh-card-cap{font-size:9px;letter-spacing:.16em;text-transform:uppercase;
  color:var(--bh-hud-cap)}
#${DOM.cardsId} .bh-card-mode p{font-size:11px;line-height:1.5;opacity:.72}
/* Une idée = un dessin à gauche, une phrase à droite. */
#${DOM.cardsId} .bh-card-row{display:flex;align-items:flex-start;gap:16px}
/* Le blanc entre deux idées du même bloc — les deux pincements. Il vit dans la
   feuille et pas dans un \`style\` posé au montage : un écart écrit en JS est un
   nombre de plus qui ne se trouve pas quand on cherche les espacements. */
#${DOM.cardsId} .bh-card-row+.bh-card-row{margin-top:18px}
#${DOM.cardsId} .bh-card-art{flex:none;display:flex;align-items:center;gap:6px;
  padding:9px 10px;border:1px solid color-mix(in srgb,${ACCENT} 18%,transparent);
  border-radius:10px;background:rgba(110,231,255,.04);color:${ACCENT}}
#${DOM.cardsId} .bh-hand{display:block;color:inherit}
/* La flèche entre « ouvert » et « fermé » : le geste est un mouvement, et deux
   dessins côte à côte sans elle se lisent comme deux gestes différents. */
#${DOM.cardsId} .bh-card-arrow{flex:none;color:${MUTED};font-size:12px}
#${DOM.cardsId} .bh-card-lead{margin:0 0 7px;font-size:11px;letter-spacing:.14em;
  text-transform:uppercase;color:${ACCENT}}
#${DOM.cardsId} .bh-card-sub{margin:0 0 8px;font-size:11px;color:${MUTED}}
#${DOM.cardsId} .bh-card ul{margin:0;padding-left:16px;line-height:1.7}
#${DOM.cardsId} .bh-card li{color:var(--text,#d8edf7);opacity:.86}
/* Les trois couleurs du retour visuel. La pastille **est** la couleur : la
   nommer sans la montrer n'aiderait personne à la reconnaître à l'écran. */
#${DOM.cardsId} .bh-card-feedback{display:flex;flex-direction:column;gap:10px}
#${DOM.cardsId} .bh-card-swatch{display:flex;align-items:flex-start;gap:11px}
#${DOM.cardsId} .bh-card-dot{flex:none;width:13px;height:13px;margin-top:3px;border-radius:50%;
  background:var(--bh-card-swatch);box-shadow:0 0 10px var(--bh-card-swatch)}
#${DOM.cardsId} .bh-card-swatch strong{font-weight:400;color:var(--bh-card-swatch)}
/* **Les reconnus sans effet**, et leur présentation dit déjà ce qu'ils sont :
   atténués, sans dessin, sans verbe. Une aide qui les mettrait au même rang
   que les pincements en ferait des commandes par la mise en page seule. */
#${DOM.cardsId} .bh-card-idle{font-size:11px;line-height:1.6;color:${MUTED}}
#${DOM.cardsId} .bh-card-idle strong{font-weight:400;color:color-mix(in srgb,${MUTED} 70%,#fff)}

/* ------------------------------------------------- la carte de diagnostic

   RÈGLE ZÉRO, et c'est toute la raison de cette carte plutôt qu'un bouton
   dans un menu : pendant un enregistrement, l'écran dit **que** ça tourne (la
   barre balaie), **quoi** (le titre), **depuis combien de temps** et **combien
   il reste** (deux compteurs vivants), et **comment en sortir** (Arrêter,
   Échap, et l'échéance qui arrête toute seule). */
#${DOM.cardsId} .bh-rec{display:flex;flex-direction:column;gap:14px}
#${DOM.cardsId} .bh-rec-state{position:relative;overflow:hidden;
  padding:13px 14px;border:1px solid var(--line,#183343);border-radius:10px;
  background:rgba(3,8,12,.5)}
#${DOM.cardsId} .bh-rec-state[data-bh-rec=on]{border-color:color-mix(in srgb,var(--warn,#ffb85c) 52%,transparent);
  background:rgba(38,23,5,.4)}
#${DOM.cardsId} .bh-rec-title{display:flex;align-items:center;gap:9px;
  font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:${MUTED}}
#${DOM.cardsId} .bh-rec-state[data-bh-rec=on] .bh-rec-title{color:var(--warn,#ffb85c)}
/* Le point qui bat : il ne dit pas l'état, il dit que la page est vivante. */
#${DOM.cardsId} .bh-rec-led{width:9px;height:9px;flex:none;border-radius:50%;
  background:color-mix(in srgb,${MUTED} 50%,transparent)}
#${DOM.cardsId} .bh-rec-state[data-bh-rec=on] .bh-rec-led{background:var(--warn,#ffb85c);
  box-shadow:0 0 12px var(--warn,#ffb85c);animation:bhRecPulse 1.1s ease-in-out infinite}
@keyframes bhRecPulse{0%,100%{opacity:.35}50%{opacity:1}}
/* Les compteurs : gros, alignés, lisibles d'un coup d'œil de loin. */
#${DOM.cardsId} .bh-rec-meters{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));
  gap:10px;margin-top:12px}
#${DOM.cardsId} .bh-rec-meter{display:flex;flex-direction:column;gap:3px}
#${DOM.cardsId} .bh-rec-value{font-size:17px;color:var(--text,#d8edf7)}
#${DOM.cardsId} .bh-rec-state[data-bh-rec=on] .bh-rec-value{color:var(--warn,#ffb85c)}
#${DOM.cardsId} .bh-rec-key{font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:${MUTED}}
/* La barre qui balaie : la seule chose qui distingue « ça tourne » de « c'est
   figé » quand rien d'autre ne bouge. */
#${DOM.cardsId} .bh-rec-sweep{position:absolute;left:0;right:0;bottom:0;height:2px;display:none;
  overflow:hidden;background:color-mix(in srgb,var(--warn,#ffb85c) 22%,transparent)}
#${DOM.cardsId} .bh-rec-state[data-bh-rec=on] .bh-rec-sweep{display:block}
#${DOM.cardsId} .bh-rec-sweep::after{content:'';position:absolute;top:0;bottom:0;left:0;width:38%;
  background:var(--warn,#ffb85c);animation:bhHudSweep 1.25s ease-in-out infinite}
#${DOM.cardsId} .bh-rec-actions{display:flex;gap:10px;flex-wrap:wrap}
#${DOM.cardsId} .bh-rec-btn{padding:9px 15px;border:1px solid var(--line,#183343);border-radius:9px;
  background:transparent;color:var(--text,#d8edf7);font:inherit;cursor:pointer;
  transition:color .16s ease,border-color .16s ease,background .16s ease}
#${DOM.cardsId} .bh-rec-btn:hover:not([disabled]){border-color:color-mix(in srgb,${ACCENT} 50%,transparent);
  background:rgba(110,231,255,.06)}
#${DOM.cardsId} .bh-rec-btn:focus-visible{outline:2px solid ${ACCENT};outline-offset:2px}
#${DOM.cardsId} .bh-rec-btn[disabled]{opacity:.4;cursor:not-allowed}
#${DOM.cardsId} .bh-rec-btn[data-bh-rec-act=stop]{border-color:color-mix(in srgb,var(--warn,#ffb85c) 55%,transparent);
  color:var(--warn,#ffb85c)}
/* La phrase de confidentialité. Elle n'est pas une note de bas de page : elle
   est la condition pour que ce bouton ait le droit d'exister ici. */
#${DOM.cardsId} .bh-rec-privacy{padding:11px 13px;border-radius:9px;font-size:11px;line-height:1.6;
  color:${MUTED};border:1px solid color-mix(in srgb,var(--line,#183343) 80%,transparent);
  background:rgba(3,8,12,.4)}
#${DOM.cardsId} .bh-rec-privacy strong{font-weight:400;color:var(--text,#d8edf7)}
#${DOM.cardsId} .bh-rec-fail{margin:0;padding:9px 11px;border-radius:8px;font-size:11px;line-height:1.55;
  color:${DANGER};border:1px solid color-mix(in srgb,${DANGER} 34%,transparent);
  background:rgba(35,7,12,.45)}
#${DOM.cardsId} .bh-rec-fail[hidden]{display:none}
@media(max-width:700px){
  /* La carte prend l'écran et la grille des trois états passe en colonne :
     trois tuiles de 100 px côte à côte ne se lisent plus. */
  #${DOM.cardsId}{padding:12px}
  #${DOM.cardsId} .bh-card{padding:18px 16px 20px}
  #${DOM.cardsId} .bh-card-modes,#${DOM.cardsId} .bh-rec-meters{grid-template-columns:1fr}
  #${DOM.cardsId} .bh-card-row{flex-direction:column;gap:12px}
}
@media(max-width:700px){
  /* En dessous de 700 px la barre du haut se resserre (\`left:10px\`), la marque
     disparaît et la bannière GPT-Live vient occuper la bande juste sous elle :
     le coin haut-gauche n'est plus libre. Le contrôle descend donc sur le bord
     gauche, en miroir du dock — le même côté que la palette d'outils à venir,
     et plus aucun croisement avec le texte de la marque ni avec la bannière. */
  #${DOM.hostId}{top:calc(50% - ${-GEO.narrowTop}px);left:${GEO.narrowLeft}px}
  /* La palette **suit** la main, à la même distance et du même côté : la
     colonne reste une colonne. Les icônes se resserrent parce que c'est là que
     l'écran est le plus court, et la bande reste verticale (décision 13 : une
     palette horizontale est reportée, pas improvisée ici). */
  #${DOM.paletteId}{top:calc(50% + ${PALETTE_NARROW_TOP}px);left:${GEO.narrowLeft}px}
  #${DOM.paletteId} .bh-tools{gap:5px;padding:5px}
  #${DOM.paletteId} .bh-tool{width:38px;height:38px}
}
@media(prefers-reduced-motion:reduce){
  /* Le mouvement s'arrête, pas l'information : le compteur de secondes sous le
     bouton continue de monter, et c'est lui qui distingue « ça travaille » de
     « c'est figé » quand plus rien ne bouge. */
  #${DOM.hostId} .bh-hud-btn,#${DOM.hostId} .bh-hud-cap,#${DOM.hostId} .bh-hud-opt{transition:none}
  #${DOM.hostId} .bh-hud-btn::before,#${DOM.hostId} .bh-hud-wait::after,
  #${DOM.hostId} .bh-hud-pop{animation:none}
  /* Même règle pour la palette, et même limite : le mouvement s'arrête,
     **l'information reste**. Le rail, la barre oblique et l'étiquette du nom
     ne sont pas des animations — ils disent lequel est choisi et lequel n'a
     pas de moteur, immobiles. */
  #${DOM.paletteId},#${DOM.paletteId} .bh-tool,#${DOM.paletteId} .bh-tool-cap{transition:none}
  /* Même règle pour les cartes, et même limite. Ce qui s'arrête : l'entrée de
     la carte, le battement du témoin, le balayage de la barre. Ce qui
     **reste** : les deux compteurs de l'enregistrement, qui montent en
     chiffres et sont la seule preuve que ça avance quand plus rien ne bouge. */
  #${DOM.cardsId} .bh-card{animation:none}
  #${DOM.cardsId} .bh-rec-led,#${DOM.cardsId} .bh-rec-sweep::after{animation:none}
  #${DOM.cardsId} .bh-rec-btn,#${DOM.cardsId} .bh-card-close{transition:none}
}`;

  /* ------------------------------------------------------- le contrôle DOM */

  /* Une seule feuille pour les deux surfaces de ce module. Le contrôle de
     cycle de vie et la palette sont la même famille et le même coin d'écran :
     deux balises `<style>` auraient été deux endroits où changer un ton. */
  function installStyle(doc){
    if(doc.getElementById(DOM.styleId))return false;
    const style=doc.createElement('style');
    style.id=DOM.styleId;style.textContent=STYLE;
    doc.head.appendChild(style);
    return true;
  }


  /* Toutes les dépendances sont injectées : le document, la surface Bare Hands
     et l'horloge. Rien n'est lu dans un global depuis l'intérieur, ce qui est
     la seule façon d'exercer ce contrôle sous node. */
  function createHudControl(deps){
    const doc=deps.document,host=deps.host;
    const surfaceOf=deps.surface,now=deps.now;
    const arm=deps.setInterval,disarm=deps.clearInterval,later=deps.setTimeout;
    const log=deps.log||function(){};
    /* Le menu contextuel de la page, **injecté comme tout le reste**. Il
       existe déjà (`.ctxmenu`, un seul élément partagé, rang 80) et ce module
       n'en fabrique surtout pas un second : il en est un consommateur de plus,
       par le même contrat `{title,items,pos,origin,run}`. Le lire dans un
       global depuis l'intérieur rendrait ce contrôle inexerçable sous node, ce
       que la Slice 01 a délibérément évité partout ailleurs. */
    const menuOf=typeof deps.showMenu==='function'?deps.showMenu:null;
    const dismissMenu=typeof deps.closeMenu==='function'?deps.closeMenu:null;

    let snapshot=null,view=presentationOf(null);
    let opened=false,cursor=0,failure='',choosing=false;
    /* Quand la touche Menu a ouvert le menu contextuel. Voir
       `KBD_MENU_GUARD_MS` : c'est de l'affichage, comme l'horloge de
       démarrage, et rien du cycle de vie n'en dépend. */
    let kbdMenuAt=-KBD_MENU_GUARD_MS;
    /* L'horloge du démarrage. C'est de l'**affichage** : elle ne décide de
       rien, elle ne survit pas au départ du démarrage, et le cycle de vie
       n'en dépend pas. */
    let bootSince=0,bootTimer=0,spoken='';

    ensureStyle();
    const trigger=doc.createElement('button');
    trigger.id=DOM.triggerId;trigger.className='bh-hud-btn';
    trigger.setAttribute('type','button');
    trigger.setAttribute('aria-haspopup','menu');
    trigger.setAttribute('aria-expanded','false');
    trigger.setAttribute('aria-controls',DOM.chooserId);
    trigger.appendChild(handIcon(doc,34));
    const wait=doc.createElement('span');
    wait.className='bh-hud-wait';wait.setAttribute('aria-hidden','true');
    trigger.appendChild(wait);
    const alert=doc.createElement('span');
    alert.className='bh-hud-alert';alert.setAttribute('aria-hidden','true');
    trigger.appendChild(alert);
    host.appendChild(trigger);

    const caption=doc.createElement('span');
    caption.id=DOM.captionId;caption.className='bh-hud-cap';
    caption.setAttribute('aria-hidden','true');
    host.appendChild(caption);

    const pop=doc.createElement('div');
    pop.id=DOM.chooserId;pop.className='bh-hud-pop';
    pop.setAttribute('role','menu');
    pop.setAttribute('aria-label','Mode Bare Hands');
    pop.hidden=true;
    const popTitle=doc.createElement('h3');
    popTitle.textContent='Bare Hands';
    pop.appendChild(popTitle);
    const note=doc.createElement('p');
    note.id=DOM.noteId;note.className='bh-hud-note';note.hidden=true;
    pop.appendChild(note);
    const opts=doc.createElement('div');
    opts.className='bh-hud-opts';
    pop.appendChild(opts);

    const options=MODES.map((mode,index)=>{
      const el=doc.createElement('button');
      el.setAttribute('type','button');
      /* `menuitemradio` et non `radio` : dans un menu, les flèches **déplacent
         le focus sans choisir**, et c'est exactement ce qu'il faut ici.
         Un groupe de radios choisit en passant dessus ; traverser ce
         sélecteur-là au clavier ouvrirait la caméra puis la rendrait à chaque
         touche — un défaut plausible que personne n'a demandé. */
      el.setAttribute('role','menuitemradio');
      el.setAttribute(DOM.modeAttribute,mode);
      el.className='bh-hud-opt';
      el.setAttribute('aria-checked','false');
      el.setAttribute('tabindex','-1');
      const chip=doc.createElement('span');
      chip.className='bh-hud-chip';
      chip.setAttribute(DOM.toneAttribute,mode);
      chip.setAttribute('aria-hidden','true');
      chip.appendChild(handIcon(doc,26));
      el.appendChild(chip);
      const cap=doc.createElement('span');
      cap.className='bh-hud-cap';cap.textContent=CAPTION[mode];
      el.appendChild(cap);
      el.addEventListener('click',()=>{choose(mode)});
      el.addEventListener('keydown',event=>onOptionKey(event,index));
      el.addEventListener('focus',()=>{cursor=index;paintHint(mode)});
      el.addEventListener('mouseenter',()=>paintHint(mode));
      el.addEventListener('focusout',scheduleOutsideClose);
      opts.appendChild(el);
      return {mode,el,chip};
    });

    const hint=doc.createElement('p');
    hint.id=DOM.hintId;hint.className='bh-hud-hint';
    pop.appendChild(hint);
    host.appendChild(pop);

    const announce=doc.createElement('div');
    announce.id=DOM.announceId;announce.className='bh-hud-sr';
    announce.setAttribute('role','status');
    announce.setAttribute('aria-live','polite');
    host.appendChild(announce);

    trigger.addEventListener('click',()=>{opened?close({focus:true}):open()});
    trigger.addEventListener('keydown',onTriggerKey);
    trigger.addEventListener('focusout',scheduleOutsideClose);
    /* Clic droit : les quatre actions rapides (décision 8). Le menu par défaut
       du navigateur est écarté — il n'a rien à proposer sur un bouton — et la
       touche Menu, qui produit *aussi* cet événement, ne le rouvre pas. */
    trigger.addEventListener('contextmenu',event=>{
      if(event&&typeof event.preventDefault==='function')event.preventDefault();
      if(now()-kbdMenuAt<KBD_MENU_GUARD_MS)return;
      openQuickMenu(pointerPos(event));
    });

    function ensureStyle(){installStyle(doc)}

    /* ------------------------------------------------------------ peinture */

    const bootSeconds=()=>bootSince?Math.max(0,(now()-bootSince)/1000):0;

    function paintHint(mode){hint.textContent=MODE_HINT[mode]||''}

    /* Le compteur de démarrage. Armé **par l'état**, jamais par un clic : un
       démarrage venu de la voix ou d'un rechargement doit compter comme celui
       qu'on a déclenché soi-même. */
    function paintBootClock(){
      if(view.tone!==TONE.STARTING){
        if(bootTimer){disarm(bootTimer);bootTimer=0}
        bootSince=0;return;
      }
      if(bootSince)return;
      bootSince=now();
      bootTimer=arm(()=>{
        if(view.tone!==TONE.STARTING){disarm(bootTimer);bootTimer=0;bootSince=0;return}
        paintClockText();
      },1000);
    }

    function paintClockText(){
      const seconds=bootSeconds();
      caption.textContent=captionOf(view,seconds);
      trigger.setAttribute('aria-label',labelOf(view,seconds));
      trigger.setAttribute('title',labelOf(view,seconds));
      if(opened)paintNote(seconds);
    }

    function paintNote(seconds){
      const said=noteOf(view,seconds,failure);
      note.hidden=!said;
      note.textContent=said?said.text:'';
      if(said)note.setAttribute('data-bh-note',said.tone);
      else note.removeAttribute('data-bh-note');
    }

    function paint(){
      host.setAttribute(DOM.toneAttribute,view.tone);
      host.setAttribute('data-bh-lifecycle',view.lifecycle);
      host.setAttribute('data-bh-busy',view.busy?'true':'false');
      trigger.setAttribute('aria-busy',view.tone===TONE.STARTING||view.busy?'true':'false');
      paintBootClock();
      paintClockText();
      for(let i=0;i<options.length;i+=1){
        const option=options[i];
        const on=option.mode===view.selected;
        option.el.setAttribute('aria-checked',on?'true':'false');
        option.el.disabled=view.busy;
        /* Un seul arrêt de tabulation dans le menu : le curseur, qui vaut le
           mode courant tant que personne n'a déplacé le focus. */
        option.el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      if(!opened){
        const at=options.findIndex(option=>option.mode===view.selected);
        cursor=at<0?0:at;
        for(let i=0;i<options.length;i+=1)
          options[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
      }
      paintNote(bootSeconds());
      if(!hint.textContent)paintHint(view.selected||MODES[cursor]);
      speak();
    }

    /* Ce que le lecteur d'écran entend, et **seulement quand ça change** : une
       région vivante qui répète le même mot à chaque repeinture cesse d'être
       écoutée. */
    function speak(){
      const line=view.tone===TONE.ERROR
        ?`Bare Hands interrompu${view.code?` : ${view.code}`:''}.`
        :view.tone===TONE.STARTING?'Bare Hands démarre.'
        :`Bare Hands : ${MODE_LABEL[view.tone]||view.tone}.`;
      if(line===spoken)return;
      spoken=line;announce.textContent=line;
    }

    /* --------------------------------------------------------- ouverture */

    function open(){
      if(opened)return false;
      /* Deux surimpressions du même bouton ne coexistent pas : le menu
         contextuel est au rang 80, le sélecteur au rang 36, donc le premier
         recouvrirait le second et l'on choisirait un mode à l'aveugle. */
      if(dismissMenu)dismissMenu(false);
      opened=true;
      pop.hidden=false;
      trigger.setAttribute('aria-expanded','true');
      paintNote(bootSeconds());
      paintHint(options[cursor].mode);
      focusAt(cursor);
      return true;
    }

    function close(options_){
      if(!opened)return false;
      opened=false;
      pop.hidden=true;
      trigger.setAttribute('aria-expanded','false');
      if(options_&&options_.focus&&typeof trigger.focus==='function')
        try{trigger.focus()}catch(_error){/* retiré entre-temps */}
      return true;
    }

    function focusAt(index){
      cursor=(index+options.length)%options.length;
      for(let i=0;i<options.length;i+=1)
        options[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
      const target=options[cursor].el;
      if(typeof target.focus==='function')try{target.focus()}catch(_error){/* retiré entre-temps */}
      paintHint(options[cursor].mode);
    }

    function onTriggerKey(event){
      const key=event&&event.key;
      if(key==='Escape'&&opened){event.preventDefault();close({focus:true});return}
      /* **L'équivalent clavier du clic droit**, sur les deux touches que la
         page utilise déjà pour les cartes d'agents. Sans lui, quatre actions
         n'auraient qu'un seul chemin et ce chemin serait la souris. */
      if(key==='ContextMenu'||(key==='F10'&&event.shiftKey)){
        event.preventDefault();
        kbdMenuAt=now();
        openQuickMenu(anchorBelowTrigger());
        return;
      }
      if(key!=='ArrowDown'&&key!=='ArrowUp')return;
      event.preventDefault();
      if(!opened)open();
      else focusAt(key==='ArrowDown'?cursor+1:cursor-1);
    }

    /* ------------------------------------------------ les actions rapides */

    /* Où poser le menu. Un `contextmenu` venu du clavier arrive en (0,0) dans
       les navigateurs — c'est le repère que la page utilise déjà ailleurs : on
       l'ancre alors sous le bouton plutôt que dans le coin de l'écran. */
    function pointerPos(event){
      const x=event&&typeof event.clientX==='number'?event.clientX:0;
      const y=event&&typeof event.clientY==='number'?event.clientY:0;
      if(!x&&!y)return anchorBelowTrigger();
      return {x,y,above:y};
    }
    function anchorBelowTrigger(){
      const rect=typeof trigger.getBoundingClientRect==='function'
        ?trigger.getBoundingClientRect():null;
      if(!rect)return {x:0,y:0,above:0};
      return {x:rect.left,y:rect.bottom+8,above:rect.top-8};
    }

    /* Les réglages, lus sur la surface au moment d'ouvrir : le menu ne tient
       pas de copie, pour la même raison que le bouton ne tient pas d'état. */
    function readSettings(){
      try{
        const surface=surfaceOf();
        return surface&&typeof surface.settings==='function'?surface.settings():null;
      }catch(error){
        log('warn','barehands.hud_settings_unreadable',
          {error:String((error&&error.message)||error)});
        return null;
      }
    }

    function openQuickMenu(pos){
      /* **Un refus codé plutôt qu'un défaut plausible.** Sans le menu de la
         page, un clic droit qui ne fait rien est indiscernable d'un bouton
         inerte. Le refus est confiné au menu — le bouton, lui, reste le
         contrôle de cycle de vie qu'il est (décision 1) — et il se **voit**,
         dans la bande du sélecteur, seul canal visible de ce module. */
      if(!menuOf){
        failure='Le menu contextuel de la page n’est pas disponible : les actions rapides sont inatteignables depuis ce bouton.';
        log('error','barehands.hud_menu_unavailable',{code:'barehands_hud_menu_missing'});
        announce.textContent=failure;spoken=failure;
        open();paintNote(bootSeconds());
        return false;
      }
      close({focus:false});
      const items=quickItemsOf(view,readSettings());
      menuOf({title:'Bare Hands',items,pos,origin:trigger,
        run:act=>{runQuick(act)}});
      log('info','barehands.hud_menu_opened',{items:items.map(item=>item.act)});
      return true;
    }

    /* Router, et **seulement** router. Chaque branche appelle la porte que le
       reste de la page appelle déjà ; aucune ne réimplante quoi que ce soit.
       Une porte absente — un moteur plus ancien que ce contrôle — se dit sous
       un nom cherchable au lieu de se taire. */
    async function runQuick(act){
      const gate=QUICK_GATE[act];
      try{
        if(!gate)
          throw Object.assign(new Error(`action Bare Hands inconnue : ${act}`),
            {code:'barehands_hud_action_unknown'});
        const surface=surfaceOf();
        if(!surface)
          throw Object.assign(new Error('window.JarvisBarehands absent'),
            {code:'barehands_hud_surface_missing'});
        if(typeof surface[gate]!=='function')
          throw Object.assign(new Error(`window.JarvisBarehands.${gate}() manque`),
            {code:'barehands_hud_entry_missing'});
        const outcome=await surface[gate]();
        /* Les portes de cette page **rendent** leur refus (`{ok:false,code}`)
           et le disent déjà à l'écran par leur propre toast. On ne le redit
           donc pas une seconde fois — deux phrases pour un fait apprennent à
           n'en lire aucune — mais on le journalise, parce que « le menu n'a
           rien fait » et « le menu a fait quelque chose qui a été refusé »
           doivent rester distinguables dans la console. */
        if(outcome&&outcome.ok===false){
          log('warn','barehands.hud_action_refused',
            {act,code:outcome.code||null,reason:outcome.reason||null});
          return outcome;
        }
        log('info','barehands.hud_action_taken',{act});
        return outcome;
      }catch(error){
        failure=`L’action « ${QUICK_LABEL[act]||act} » n’a pas abouti : ${(error&&error.message)||error}`;
        log('error','barehands.hud_action_failed',
          {act,code:(error&&error.code)||null,error:String((error&&error.message)||error)});
        announce.textContent=failure;spoken=failure;
        open();paintNote(bootSeconds());
        return null;
      }
    }

    function onOptionKey(event,index){
      const key=event&&event.key;
      if(key==='Escape'){event.preventDefault();close({focus:true});return}
      if(key==='Home'||key==='End'){event.preventDefault();focusAt(key==='Home'?0:options.length-1);return}
      const step=key==='ArrowRight'||key==='ArrowDown'?1
        :key==='ArrowLeft'||key==='ArrowUp'?-1:0;
      if(!step)return;
      event.preventDefault();
      focusAt(index+step);
    }

    /* Le focus a quitté le contrôle : le menu se ferme. Vérifié **après** que
       le focus a atterri — `focusout` part avant que `activeElement` ne soit à
       jour, et refermer trop tôt volerait le clic qu'on est en train de faire. */
    function scheduleOutsideClose(){
      later(()=>{
        if(!opened)return;
        const at=doc.activeElement;
        if(at===trigger)return;
        for(const option of options)if(option.el===at)return;
        close({focus:false});
      },0);
    }

    /* ------------------------------------------------------------- choix */

    /* Les transitions, sur les **mêmes portes** que le panneau et que la voix.
       Rien n'est réimplanté : une seconde implantation de « réveiller »
       diverge le jour où l'une des deux change, et personne ne voit laquelle
       l'utilisateur a prise. */
    async function choose(mode){
      if(choosing)return null;
      if(!MODES.includes(mode))
        throw Object.assign(new Error(`mode Bare Hands inconnu : ${mode}`),
          {code:'barehands_hud_mode_unknown'});
      choosing=true;failure='';
      close({focus:true});
      try{
        const surface=surfaceOf();
        if(!surface)
          throw Object.assign(new Error('window.JarvisBarehands absent'),
            {code:'barehands_hud_surface_missing'});
        if(mode===BH.LIFECYCLE.OFF){
          /* OFF est le seul mode où la posture en C ne peut rien, parce que
             c'est le seul où la caméra est **rendue** et l'interrupteur maître
             écrit à faux — donc le seul qui survive au rechargement. C'est
             `disable()`, jamais `sleep()`. */
          await surface.disable();
        }else if(mode===BH.LIFECYCLE.SLEEP){
          /* Endormir d'abord si la main pilote : `enable()` ne fait pas sortir
             d'ACTIVE, personne d'autre ne le ferait. */
          if(view.lifecycle===BH.LIFECYCLE.ACTIVE)await surface.sleep();
          /* `enable()` fait **deux** choses : écrire l'interrupteur maître sur
             le serveur, et armer le guetteur. On ne l'appelle donc que s'il en
             reste au moins une à faire. Maître déjà vrai **et** moteur déjà
             vivant : il n'y a rien à écrire, et l'écriture serait un
             aller-retour serveur par clic sans aucune garantie de plus. Maître
             vrai mais moteur éteint — une panne, un démarrage avorté — : il
             faut bien rarmer, et c'est le seul chemin public qui le fasse.

             L'état lu est celui du dernier instantané de la couture, donc
             l'autorité, jamais une copie tenue ici : c'est la règle de cette
             Slice, et une garde qui se tromperait de source n'écrirait pas là
             où il faut. */
          if(!(view.enabled&&BH.isLiveLifecycle(view.lifecycle)))await surface.enable();
        }else{
          /* `activate()` porte la chaîne entière depuis `off` ou depuis une
             panne : il allume, guette, puis réveille, en une seule attente.
             `enable()` vient **après**, pour persister le maître sans rien
             éteindre. Appelé avant, il laisserait le contrôleur en démarrage —
             et `activate()`, qui rend la main tout de suite dans cet état,
             n'aurait rien à réveiller. */
          await surface.activate();
          /* Ici `enable()` n'est **que** de la persistance : le travail moteur
             vient d'être fait. On n'écrit donc que ce qui tient vraiment. Un
             allumage qui vient d'échouer ne s'enregistre pas comme un souhait
             exaucé — et le réécrire relancerait un second démarrage et un
             second message pour la même panne. Règle du canal de commandes,
             appliquée ici : on rapporte ce que la page constate, jamais ce
             qu'on a demandé. */
          if(!view.enabled&&BH.isLiveLifecycle(view.lifecycle))await surface.enable();
        }
        log('info','barehands.hud_mode_selected',{mode});
        return mode;
      }catch(error){
        /* Un refus se dit, sous sa cause réelle, à l'écran **et** au journal.
           Le silence ici rendrait « le bouton n'a rien fait » indiscernable de
           « le bouton a fait quelque chose qui a échoué ». */
        failure=`Le mode « ${MODE_LABEL[mode]} » n’a pas été pris : ${(error&&error.message)||error}`;
        log('error','barehands.hud_mode_refused',
          {mode,code:(error&&error.code)||null,error:String((error&&error.message)||error)});
        announce.textContent=failure;spoken=failure;
        /* **Le refus se voit.** Le sélecteur s'était refermé sur le choix ; il
           se rouvre sur la phrase qui dit pourquoi, là où l'utilisateur vient
           de cliquer. Une région vivante seule ne parle qu'aux lecteurs
           d'écran, et un contrôle qui redevient silencieux après un clic est
           indiscernable d'un contrôle qui n'a rien reçu. */
        open();
        paintNote(bootSeconds());
        return null;
      }finally{
        choosing=false;
        paint();
      }
    }

    function render(next){
      snapshot=next;
      view=presentationOf(next);
      paint();
      return view;
    }

    render(null);

    return {
      element:host,trigger,chooser:pop,
      render,choose,open,close,
      /* Les actions rapides, atteignables sans souris ni clavier : c'est ce
         que les tests exercent, et ce que la console atteint. */
      openQuickMenu:pos=>openQuickMenu(pos||anchorBelowTrigger()),
      quickItems:()=>quickItemsOf(view,readSettings()),
      runQuick,
      isOpen:()=>opened,
      /* Ce que l'écran **peint**, par opposition à ce que le moteur dit : les
         deux doivent coïncider, et c'est la seule façon de le vérifier sans
         lire des pixels. */
      presentation:()=>view,
      snapshot:()=>snapshot,
      failure:()=>failure,
      destroy(){
        if(bootTimer){disarm(bootTimer);bootTimer=0}
        /* Le menu est un élément **partagé** de la page : il survivrait à ce
           contrôle, ancré sur un bouton qui n'existe plus. */
        if(dismissMenu)dismissMenu(false);
        trigger.remove();caption.remove();pop.remove();announce.remove();
      },
    };
  }

  /* ------------------------------------------- la palette d'outils, en DOM

     Mêmes règles que le contrôle ci-dessus, et pour les mêmes raisons :
     **aucune dépendance prise dans un global** (le document et la surface sont
     injectés, seule façon d'exercer ceci sous node) et **aucune mémoire de ce
     qui appartient à quelqu'un d'autre**. La palette ne tient pas l'outil : le
     contrat tient la liste, les réglages tiennent le choix, et les deux
     coutures le lui apportent. Ce qu'elle tient est un curseur de clavier et
     une phrase de refus — de l'affichage, rien d'autre.

     Une seconde mémoire de l'outil ici serait la dérive exacte que la
     Slice 01 a écartée pour le cycle de vie : un `tool()` appelé depuis la
     console ou une réponse de serveur qui corrige la valeur laisseraient la
     bande sur son ancien choix, et l'écran mentirait sans que rien ne tombe. */
  function createToolPalette(deps){
    const doc=deps.document,host=deps.host;
    const surfaceOf=deps.surface;
    const log=deps.log||function(){};

    let tool=null,view=presentationOf(null),model=paletteOf(null,view);
    let cursor=0,failure='',picking=false,held=false,spoken='';

    installStyle(doc);

    /* La bande. `role="toolbar"` et **pas** `radiogroup` : dans un groupe de
       boutons radio, les flèches *choisissent* en passant, et chaque touche
       partirait donc en écriture réseau — c'est ce que faisait `moveTool()`
       dans les réglages, où la cible était un formulaire. Ici, traverser la
       palette au clavier changerait le sens de la main à chaque frappe. Le
       sélecteur de mode de la Slice 02 a tranché la même question dans l'autre
       sens pour la même raison (`menuitemradio` : les flèches déplacent, la
       validation choisit) ; la palette suit sa voisine. */
    const strip=doc.createElement('div');
    strip.id=DOM.paletteStripId;strip.className='bh-tools';
    strip.setAttribute('role','toolbar');
    strip.setAttribute('aria-orientation','vertical');
    strip.setAttribute('aria-label','Outils Bare Hands');
    host.appendChild(strip);

    /* Les boutons, **construits depuis le contrat** une fois pour toutes. La
       liste ne change pas en cours de session : `describeTools()` est une
       table, pas un état. Ce qui change à chaque peinture, c'est l'état de
       chacun — et cela se fait en place, jamais en réécrivant la bande, pour
       la même raison que le panneau de réglages ne se redessine pas : une
       réécriture arracherait le focus au moment où l'on s'en sert. */
    const buttons=BH.describeTools().map((described,index)=>{
      const el=doc.createElement('button');
      el.setAttribute('type','button');
      el.setAttribute(DOM.toolAttribute,described.id);
      el.className='bh-tool';
      el.setAttribute('tabindex','-1');
      el.appendChild(toolIcon(doc,described.id,22));
      el.addEventListener('click',()=>{pick(described.id)});
      el.addEventListener('keydown',event=>onKey(event,index));
      el.addEventListener('focus',()=>{held=true;cursor=index;roving()});
      el.addEventListener('focusout',()=>{held=false});
      strip.appendChild(el);
      return {id:described.id,el};
    });

    /* Le **nom** de l'outil actif, sous la bande. L'icône dit lequel par la
       forme, le rail par la position, l'étiquette par le mot : « l'outil actif
       est immédiatement compréhensible » est le critère que l'Humain juge à
       l'œil, et un seul canal l'aurait joué sur une seule teinte. */
    const caption=doc.createElement('span');
    caption.id=DOM.paletteCaptionId;caption.className='bh-tool-cap';
    caption.setAttribute('aria-hidden','true');
    host.appendChild(caption);

    const announce=doc.createElement('div');
    announce.id=DOM.paletteAnnounceId;announce.className='bh-hud-sr';
    announce.setAttribute('role','status');
    announce.setAttribute('aria-live','polite');
    host.appendChild(announce);

    /* **La recette d'extension à moitié suivie se dit tout de suite.** Un
       outil installé sans dessin arrive ici au chargement, pas trois clics
       plus tard ; sans cette ligne, il serait un carré en pointillés que
       personne ne saurait expliquer. */
    const artless=model.items.filter(item=>item.installed&&!item.art).map(item=>item.id);
    if(artless.length)
      log('warn','barehands.palette_icon_missing',{code:ARTLESS,tools:artless});

    function roving(){
      /* Un seul arrêt de tabulation dans la barre d'outils : le curseur. Les
         flèches font le reste, ce que `role="toolbar"` promet. */
      for(let i=0;i<buttons.length;i+=1)
        buttons[i].el.setAttribute('tabindex',i===cursor?'0':'-1');
    }

    function focusAt(index){
      if(!buttons.length)return;
      cursor=(index+buttons.length)%buttons.length;
      roving();
      const target=buttons[cursor].el;
      if(typeof target.focus==='function')try{target.focus()}catch(_error){/* retiré entre-temps */}
    }

    function onKey(event,index){
      const key=event&&event.key;
      if(key==='Home'||key==='End'){
        if(typeof event.preventDefault==='function')event.preventDefault();
        focusAt(key==='Home'?0:buttons.length-1);return;
      }
      /* La bande est verticale, donc les flèches verticales la parcourent.
         Les horizontales sont acceptées aussi : elles l'étaient dans les
         réglages, et un utilisateur qui les a apprises là ne doit pas
         découvrir qu'elles ont cessé de marcher. */
      const step=key==='ArrowDown'||key==='ArrowRight'?1
        :key==='ArrowUp'||key==='ArrowLeft'?-1:0;
      if(!step)return;
      if(typeof event.preventDefault==='function')event.preventDefault();
      /* **Aucun saut.** `moveTool()` sautait les outils sans moteur, ce qui
         les rendait inatteignables au clavier : leur motif ne pouvait être lu
         que par une souris qui survole. Ils restent donc sur le chemin,
         `aria-disabled` et non `disabled`, et ils disent pourquoi ils ne se
         choisissent pas — même choix que « Calibrer… » bloqué à la Slice 02. */
      focusAt(index+step);
    }

    /* Ce que le lecteur d'écran entend, et **seulement quand ça change**. */
    function speak(line){
      if(!line||line===spoken)return;
      spoken=line;announce.textContent=line;
    }

    function paint(){
      model=paletteOf(tool,view);
      host.setAttribute('data-bh-live',model.live?'true':'false');
      host.setAttribute('data-bh-busy',model.busy?'true':'false');
      /* **Diagnostic, et rien d'autre** : aucune règle de la feuille ne le lit,
         exprès. La palette ne redit pas le cycle de vie à l'écran (le contrôle
         qui le porte est dans la même colonne), mais le dernier état qu'elle a
         reçu doit rester lisible depuis une console et depuis un test — sans
         quoi « la palette n'a pas été prévenue » et « la palette a été
         prévenue et a choisi de ne rien montrer » s'écrivent pareil. */
      host.setAttribute('data-bh-tone',model.tone);
      /* Le curseur suit l'outil actif tant que personne n'a posé le focus
         dans la bande : la tabulation arrive alors sur ce qui est choisi. */
      if(!held){
        const at=model.items.findIndex(item=>item.state===SLOT.ACTIVE);
        cursor=at<0?0:at;
      }
      for(let i=0;i<buttons.length;i+=1){
        const button=buttons[i],item=model.items[i];
        button.el.setAttribute(DOM.toolStateAttribute,item.state);
        /* `aria-pressed` et non `aria-checked` : ces boutons vivent dans une
           barre d'outils, pas dans un groupe de radios, et c'est `pressed` qui
           dit « cet outil est enfoncé » sans promettre qu'une flèche choisit. */
        button.el.setAttribute('aria-pressed',item.state===SLOT.ACTIVE?'true':'false');
        button.el.setAttribute('aria-disabled',item.installed?'false':'true');
        /* **Deux empêchements, deux mécaniques, et c'est voulu.** Sans moteur :
           `aria-disabled`, donc encore atteignable pour dire pourquoi. Écriture
           en vol : vraiment `disabled`, parce que c'est une fraction de seconde
           et qu'un second clic partirait se faire refuser par `saveSettings`
           avec un mot que personne n'a demandé. */
        button.el.disabled=item.installed&&model.busy;
        button.el.setAttribute('title',item.title);
        button.el.setAttribute('aria-label',item.title);
      }
      roving();
      caption.textContent=model.caption;
      speak(failure||(model.active
        ?`Outil Bare Hands : ${(BH.TOOL_LABEL&&BH.TOOL_LABEL[model.active])||model.active}.${model.dormant?` ${model.dormant}`:''}`
        :'Aucun outil Bare Hands sélectionné.'));
      return model;
    }

    /* Choisir, par **la porte canonique**. `JarvisBarehands.tool(id)` est
       exactement `saveSettings({tool:id})` : la même que la console, la même
       que l'onglet appelait avant la décision 11, la même que la voix
       appellera. Aucun magasin d'outils parallèle n'est créé ici, et c'est la
       seule chose que cette fonction a le droit de ne pas faire. */
    async function pick(id){
      if(picking)return null;
      const item=model.items.find(entry=>entry.id===id)||null;
      /* **Un refus codé plutôt qu'un défaut plausible.** Un outil sans moteur
         n'écrit rien et le redit ; se replier sur « pointeur » aurait changé
         l'outil de l'utilisateur sans qu'il l'ait demandé. */
      if(!item){
        failure=`Outil Bare Hands inconnu : ${String(id)}.`;
        log('error','barehands.palette_tool_unknown',{tool:String(id),code:'barehands_tool_unknown'});
        paint();return null;
      }
      if(!item.installed){
        failure=`${item.label} — ${UNAVAILABLE}`;
        log('warn','barehands.palette_tool_not_installed',
          {tool:item.id,code:'barehands_tool_not_installed'});
        paint();return null;
      }
      if(model.busy)return null;
      picking=true;failure='';
      try{
        const surface=surfaceOf();
        if(!surface)
          throw Object.assign(new Error('window.JarvisBarehands absent'),
            {code:'barehands_palette_surface_missing'});
        if(typeof surface.tool!=='function')
          throw Object.assign(new Error('window.JarvisBarehands.tool() manque'),
            {code:'barehands_palette_entry_missing'});
        const outcome=await surface.tool(item.id);
        /* `settings()` rend `null` quand rien n'a été enregistré, et il a déjà
           dit pourquoi à l'écran par son propre toast. On ne le redit pas une
           seconde fois — deux phrases pour un fait apprennent à n'en lire
           aucune — mais « la palette n'a rien fait » et « la palette a fait
           quelque chose qui a été refusé » restent distinguables au journal.
           La couture, elle, ramènera l'outil réellement appliqué. */
        if(outcome===null){
          log('warn','barehands.palette_tool_refused',{tool:item.id});
          return null;
        }
        log('info','barehands.palette_tool_selected',{tool:item.id});
        return item.id;
      }catch(error){
        failure=`L’outil « ${item.label} » n’a pas été pris : ${(error&&error.message)||error}`;
        log('error','barehands.palette_tool_failed',
          {tool:item.id,code:(error&&error.code)||null,
            error:String((error&&error.message)||error)});
        return null;
      }finally{
        picking=false;
        paint();
      }
    }

    /* Les deux entrées de peinture, une par couture. Elles ne se confondent
       pas : l'outil vient des réglages, la disponibilité du cycle de vie, et
       un module qui les mélangerait perdrait la trace de qui a changé quoi. */
    function renderTool(snapshot){
      tool=snapshot&&typeof snapshot==='object'?snapshot.tool:snapshot;
      return paint();
    }
    function renderLifecycle(snapshot){
      view=presentationOf(snapshot);
      return paint();
    }

    paint();

    return {
      element:host,strip,buttons,caption,
      renderTool,renderLifecycle,pick,focusAt,
      model:()=>model,failure:()=>failure,cursor:()=>cursor,
      destroy(){strip.remove();caption.remove();announce.remove()},
    };
  }

  /* ==================================== les deux cartes rapides, en DOM

     Décisions 15 et 16. Une seule carte à la fois, un seul emplacement, et le
     même jeu de règles que les deux autres surfaces de ce module : rien n'est
     pris dans un global (document, surface et horloge sont injectés, seule
     façon d'exercer ceci sous node) et rien n'est tenu qui appartienne à
     quelqu'un d'autre.

     **Ce que ce module ne fait pas** : il n'enregistre rien, il ne décide de
     rien de ce qui est retenu, et il ne touche à aucune rétention. Il appelle
     `record.start()`, `record.stop()` et `record.state()` — les mêmes portes
     que les deux boutons de l'onglet Expérimental, qui restent en place. Ce
     qui change est la découvrabilité, et strictement elle. */

  const CARD=Object.freeze({HELP:'help',DIAGNOSTICS:'diagnostics'});

  /* La phrase de confidentialité, reprise **mot pour mot** de la surface
     d'enregistrement de l'onglet Expérimental. Elle n'est pas réécrite : c'est
     la promesse faite à l'utilisateur, et deux formulations de la même
     promesse finissent par ne plus promettre la même chose. */
  const RECORD_PRIVACY='Un enregistrement retient des <strong>mesures dérivées</strong> — '
    +'position brute et filtrée, ratios de pincement, immobilité, issues — et '
    +'jamais une image, une vidéo ni les points de votre main.';

  const secondsOf=ms=>`${Math.round(Number(ms||0)/1000)} s`;

  /* **Le modèle de la carte de diagnostic, pur.** Il traduit ce que
     `record.state()` publie en ce que l'écran doit peindre, et il porte à lui
     seul les quatre exigences de la RÈGLE ZÉRO : `running` (que ça tourne),
     `title` (quoi), `elapsed` et `remaining` (depuis combien de temps, et
     combien il reste), `canStop` (comment en sortir). */
  function diagnosticsModel(state,bounds,failure){
    const seen=state&&typeof state==='object'?state:{};
    const installed=!!seen.installed;
    const running=!!seen.recording;
    const limit=bounds&&typeof bounds==='object'?bounds:{};
    /* Les bornes en vigueur viennent de l'enregistreur dès qu'il en a une ;
       avant le premier départ, `record.state()` rend des zéros et ce sont les
       défauts du module qui font foi. Aucun nombre n'est inventé ici : sans
       l'un ni l'autre, la phrase se dit **sans chiffre** plutôt qu'avec un
       chiffre plausible. */
    const maxDurationMs=Number(seen.maxDurationMs)>0?Number(seen.maxDurationMs)
      :Number(limit.maxDurationMs)>0?Number(limit.maxDurationMs):0;
    const maxFrames=Number(seen.maxFrames)>0?Number(seen.maxFrames)
      :Number(limit.maxFrames)>0?Number(limit.maxFrames):0;
    const bound=maxDurationMs&&maxFrames
      ?`Il s’arrête tout seul au bout de ${secondsOf(maxDurationMs)} ou de ${maxFrames} images.`
      :'Il s’arrête tout seul : une capture sans fin est exactement ce que la règle zéro interdit.';
    const last=seen.last&&typeof seen.last==='object'?seen.last:null;
    return Object.freeze({
      installed,running,
      title:running?'Enregistrement en cours':'Enregistrement de diagnostic',
      /* Les trois compteurs. Pendant : retenues / écoulé / restant — les deux
         derniers montent et descendent chaque seconde, et c'est eux qui
         distinguent « ça travaille » de « c'est figé ». Après : ce que la
         dernière séance a laissé, parce qu'un écran qui redevient vide après
         un arrêt se lit comme un arrêt qui a tout perdu. */
      meters:Object.freeze(running
        ?[Object.freeze({key:'retenues',value:`${Number(seen.frames)||0} / ${Number(seen.observed)||0}`}),
          Object.freeze({key:'écoulé',value:secondsOf(seen.elapsedMs)}),
          Object.freeze({key:'restant',value:secondsOf(seen.remainingMs)})]
        :[Object.freeze({key:'dernière séance',value:`${Number(seen.frames)||0} images`}),
          Object.freeze({key:'durée',value:secondsOf(seen.elapsedMs)}),
          Object.freeze({key:'écartées',value:String(Number(seen.dropped)||0)})]),
      privacy:`${RECORD_PRIVACY} ${bound}`,
      maxDurationMs,maxFrames,
      /* Un enregistreur absent n'est pas « pas en train d'enregistrer » : la
         carte ne propose alors rien et dit pourquoi, sous un nom cherchable. */
      canStart:installed&&!running,
      canStop:installed&&running,
      absent:!installed,
      absentReason:'Le module d’enregistrement n’est pas chargé dans cette page '
        +'(barehands_recorder_not_installed) : il n’y a rien à démarrer.',
      /* Le sort de la dernière trace envoyée. Une trace qui n'est pas partie
         doit se voir ici : « enregistré » et « enregistré puis perdu » sont
         deux choses, et seule la seconde demande quelque chose à l'humain. */
      last:last?Object.freeze({id:last.id===undefined?null:last.id,
        frames:Number(last.frames)||0,
        path:last.path===undefined?null:last.path,
        error:last.error===undefined||last.error===null?null:String(last.error)}):null,
      seam:Object.freeze([].concat(seen.seam||[])),
      failure:failure?String(failure):'',
    });
  }

  function createQuickCards(deps){
    const doc=deps.document,host=deps.host;
    const surfaceOf=deps.surface;
    const arm=deps.setInterval,disarm=deps.clearInterval;
    const boundsOf=typeof deps.recorderBounds==='function'?deps.recorderBounds:()=>null;
    const log=deps.log||function(){};

    let open=null,poll=0,failure='',restore=null,busy=false;

    installStyle(doc);

    const card=doc.createElement('div');
    card.id=DOM.cardId;card.className='bh-card';
    card.setAttribute('role','dialog');
    card.setAttribute('aria-modal','true');
    card.setAttribute('aria-labelledby',DOM.cardTitleId);
    /* Le conteneur reçoit le focus à l'ouverture : sans lui, la tabulation
       repartirait du haut de la page, c'est-à-dire derrière la carte. */
    card.setAttribute('tabindex','-1');

    const head=doc.createElement('div');
    head.className='bh-card-head';
    const heading=doc.createElement('div');
    const eyebrow=doc.createElement('div');
    eyebrow.className='bh-card-eyebrow';eyebrow.textContent='Bare Hands';
    const title=doc.createElement('h2');
    title.id=DOM.cardTitleId;
    heading.appendChild(eyebrow);heading.appendChild(title);
    head.appendChild(heading);
    const shut=doc.createElement('button');
    shut.id=DOM.cardCloseId;shut.className='bh-card-close';
    shut.setAttribute('type','button');
    shut.setAttribute('aria-label','Fermer');
    shut.textContent='×';
    shut.addEventListener('click',()=>close({focus:true}));
    head.appendChild(shut);
    card.appendChild(head);

    const body=doc.createElement('div');
    body.id=DOM.cardBodyId;
    card.appendChild(body);
    host.appendChild(card);

    const announce=doc.createElement('div');
    announce.id=DOM.cardAnnounceId;announce.className='bh-hud-sr';
    announce.setAttribute('role','status');
    announce.setAttribute('aria-live','polite');
    host.appendChild(announce);

    /* Cliquer **à côté** ferme, cliquer dedans non. La nappe est un élément à
       part entière, donc le test porte sur la cible et pas sur un calcul de
       coordonnées qui se tromperait au premier défilement. */
    host.addEventListener('click',event=>{
      if(event&&event.target===host)close({focus:true});
    });
    host.addEventListener('keydown',onKey);

    function onKey(event){
      const key=event&&event.key;
      if(key==='Escape'){
        if(typeof event.preventDefault==='function')event.preventDefault();
        close({focus:true});
        return;
      }
      /* Le piège à focus. Une carte `aria-modal` dont la tabulation sort
         derrière elle n'est modale que pour les voyants. */
      if(key!=='Tab')return;
      const stops=focusables();
      if(!stops.length)return;
      const at=doc.activeElement;
      const index=stops.indexOf(at);
      const last=stops.length-1;
      if(event.shiftKey?(index<=0):(index===last||index<0)){
        if(typeof event.preventDefault==='function')event.preventDefault();
        focusOn(stops[event.shiftKey?last:0]);
      }
    }

    const focusables=()=>collect(card).filter(node=>
      node.tagName==='BUTTON'&&!node.disabled);

    /* Le double de DOM des tests ne connaît pas `querySelectorAll` ; la page,
       elle, s'en passe très bien. Un parcours explicite marche dans les deux. */
    function collect(node){
      const out=[];
      const walk=current=>{
        for(const child of (current&&current.children)||[]){
          out.push(child);walk(child);
        }
      };
      walk(node);
      return out;
    }

    function focusOn(node){
      if(node&&typeof node.focus==='function')
        try{node.focus()}catch(_error){/* retiré entre-temps */}
    }

    function say(line){
      if(!line)return;
      announce.textContent=line;
    }

    /* ------------------------------------------------------- l'ouverture */

    function show(kind,paint){
      if(open&&open!==kind)clearBody();
      if(!open)restore=doc.activeElement||null;
      open=kind;
      host.setAttribute(DOM.cardAttribute,kind);
      paint();
      focusOn(card);
      log('info','barehands.card_opened',{card:kind});
      return true;
    }

    function clearBody(){
      while(body.firstChild)body.removeChild(body.firstChild);
    }

    function close(options_){
      if(!open)return false;
      const was=open;
      open=null;failure='';
      if(poll){disarm(poll);poll=0}
      host.removeAttribute(DOM.cardAttribute);
      clearBody();
      if(options_&&options_.focus)focusOn(restore);
      restore=null;
      log('info','barehands.card_closed',{card:was});
      return true;
    }

    /* ------------------------------------------------------- l'aide */

    const el=(tag,className,text)=>{
      const node=doc.createElement(tag);
      if(className)node.className=className;
      if(text!==undefined&&text!==null)node.textContent=text;
      return node;
    };
    const block=(into,heading_)=>{
      const section=el('section','bh-card-block');
      section.appendChild(el('h3',null,heading_));
      into.appendChild(section);
      return section;
    };
    const handArt=(pose,size)=>HAND.handSvg(doc,{pose,size,className:'bh-hand'});

    function paintHelp(){
      const model=helpModel();
      title.textContent=model.title;
      clearBody();

      const modes=block(body,'Les trois états');
      const grid=el('div','bh-card-modes');
      for(const state of model.lifecycle){
        const tile=el('div','bh-card-mode');
        tile.setAttribute(DOM.toneAttribute,state.mode);
        const chip=el('span','bh-card-chip');
        chip.setAttribute(DOM.toneAttribute,state.mode);
        chip.setAttribute('aria-hidden','true');
        chip.appendChild(handArt(HAND.POSE.REST,26));
        tile.appendChild(chip);
        tile.appendChild(el('span','bh-card-cap',state.caption));
        tile.appendChild(el('p',null,state.hint));
        grid.appendChild(tile);
      }
      modes.appendChild(grid);
      modes.appendChild(el('p','bh-card-note',
        'Le mode se choisit au clic gauche sur le bouton à icône de main, en haut à gauche.'));

      const wake=block(body,model.wake.title);
      const wakeRow=el('div','bh-card-row');
      const wakeArt=el('div','bh-card-art');
      wakeArt.appendChild(handArt(HAND.POSE.WAKE_C,54));
      wakeRow.appendChild(wakeArt);
      const wakeText=el('div');
      wakeText.appendChild(el('p',null,model.wake.text));
      wakeText.appendChild(el('p','bh-card-note',model.wake.back));
      wakeRow.appendChild(wakeText);
      wake.appendChild(wakeRow);

      const pinch=block(body,'Les deux pincements');
      for(const channel of model.pinch){
        const row=el('div','bh-card-row');
        row.setAttribute('data-bh-channel',channel.channel);
        const art=el('div','bh-card-art');
        art.appendChild(handArt(channel.poses[0],46));
        art.appendChild(el('span','bh-card-arrow','→'));
        art.appendChild(handArt(channel.poses[1],46));
        row.appendChild(art);
        const text=el('div');
        text.appendChild(el('p','bh-card-lead',channel.title));
        text.appendChild(el('p','bh-card-sub',channel.subtitle));
        const list=el('ul');
        for(const action of channel.actions)list.appendChild(el('li',null,action));
        text.appendChild(list);
        row.appendChild(text);
        pinch.appendChild(row);
      }

      const colours=block(body,'Les couleurs du retour');
      const swatches=el('div','bh-card-feedback');
      for(const role of model.feedback){
        const line=el('div','bh-card-swatch');
        line.setAttribute('data-bh-feedback',role.role);
        line.style.setProperty('--bh-card-swatch',role.color);
        const dot=el('span','bh-card-dot');
        dot.setAttribute('aria-hidden','true');
        line.appendChild(dot);
        const text=el('p');
        text.appendChild(el('strong',null,`${role.label} — `));
        text.appendChild(doc.createTextNode(role.text));
        line.appendChild(text);
        swatches.appendChild(line);
      }
      colours.appendChild(swatches);

      /* **La légende du jeton.** Elle suit les couleurs parce que c'est la
         même question — « qu'est-ce que je regarde ? » —, et précède les
         gestes sans effet parce qu'elle, elle décrit quelque chose qui agit. */
      const reading=block(body,model.reading.title);
      const readRow=el('div','bh-card-row');
      const readArt=el('div','bh-card-art');
      readArt.appendChild(handArt(model.reading.pose,54));
      readRow.appendChild(readArt);
      const readText=el('div');
      readText.appendChild(el('p',null,model.reading.token));
      readText.appendChild(el('p','bh-card-note',model.reading.unsure));
      readRow.appendChild(readText);
      reading.appendChild(readRow);

      /* **Reconnus, sans effet.** Ils sont dits, parce que les taire ferait
         croire que le moteur ne les voit pas — et ils sont dits *comme*
         n'étant pas des commandes : pas de dessin, pas de verbe, une seule
         ligne atténuée. */
      const idle=block(body,'Reconnus, sans effet');
      const names=model.unbound.map(item=>item.label).join(' · ');
      const note=el('p','bh-card-idle');
      note.appendChild(el('strong',null,names));
      note.appendChild(doc.createTextNode(
        ' — mesurés et publiés à chaque image, mais aucune action ne leur est liée aujourd’hui.'));
      idle.appendChild(note);
      const unnamed=model.unbound.filter(item=>!item.named).map(item=>item.gesture);
      if(unnamed.length)
        log('warn','barehands.help_gesture_unnamed',
          {code:model.unnamedCode,gestures:unnamed});

      say(`${model.title} ouverte.`);
    }

    function openHelp(){
      return show(CARD.HELP,paintHelp);
    }

    /* -------------------------------------------------- le diagnostic */

    function readRecord(){
      try{
        const surface=surfaceOf();
        if(!surface||!surface.record||typeof surface.record.state!=='function')return null;
        return surface.record.state();
      }catch(error){
        log('warn','barehands.card_record_unreadable',
          {error:String((error&&error.message)||error)});
        return null;
      }
    }

    function diagnosticsView(){
      return diagnosticsModel(readRecord(),safeBounds(),failure);
    }
    function safeBounds(){
      try{return boundsOf()}catch(_error){return null}
    }

    function paintDiagnostics(){
      const model=diagnosticsView();
      title.textContent='Diagnostic';
      clearBody();

      const section=block(body,'Enregistrement');
      const wrap=el('div','bh-rec');

      const state=el('div','bh-rec-state');
      state.setAttribute('data-bh-rec',model.running?'on':'off');
      const line=el('div','bh-rec-title');
      const led=el('span','bh-rec-led');
      led.setAttribute('aria-hidden','true');
      line.appendChild(led);
      line.appendChild(doc.createTextNode(model.title));
      state.appendChild(line);
      const meters=el('div','bh-rec-meters');
      for(const meter of model.meters){
        const cell=el('div','bh-rec-meter');
        cell.setAttribute('data-bh-meter',meter.key);
        cell.appendChild(el('span','bh-rec-value',meter.value));
        cell.appendChild(el('span','bh-rec-key',meter.key));
        meters.appendChild(cell);
      }
      state.appendChild(meters);
      const sweep=el('span','bh-rec-sweep');
      sweep.setAttribute('aria-hidden','true');
      state.appendChild(sweep);
      wrap.appendChild(state);

      const fail=el('p','bh-rec-fail');
      fail.hidden=!(model.failure||model.absent||(model.last&&model.last.error));
      fail.textContent=model.failure
        ||(model.absent?model.absentReason
          :model.last&&model.last.error
            ?`La dernière trace n’a pas été enregistrée sur le disque : ${model.last.error}`
            :'');
      wrap.appendChild(fail);

      const actions=el('div','bh-rec-actions');
      const start=el('button','bh-rec-btn','Démarrer');
      start.setAttribute('type','button');
      start.setAttribute('data-bh-rec-act','start');
      start.disabled=!model.canStart||busy;
      start.addEventListener('click',()=>run('start'));
      actions.appendChild(start);
      const stop=el('button','bh-rec-btn','Arrêter');
      stop.setAttribute('type','button');
      stop.setAttribute('data-bh-rec-act','stop');
      stop.disabled=!model.canStop||busy;
      stop.addEventListener('click',()=>run('stop'));
      actions.appendChild(stop);
      /* La surface complète reste là où elle a toujours été. Cette carte est
         un **raccourci**, pas un remplacement : le rejeu, la comparaison et
         les réglages de l'enregistreur vivent toujours dans l'onglet, et y
         renvoyer vaut mieux que les recopier ici à moitié. */
      const more=el('button','bh-rec-btn','Réglages avancés…');
      more.setAttribute('type','button');
      more.setAttribute('data-bh-rec-act','settings');
      more.addEventListener('click',()=>run('settings'));
      actions.appendChild(more);
      wrap.appendChild(actions);

      const privacy=el('div','bh-rec-privacy');
      privacy.innerHTML=model.privacy;
      wrap.appendChild(privacy);

      section.appendChild(wrap);
      return model;
    }

    /* Le battement d'une seconde. Il est armé **tant que la carte est
       ouverte**, et pas seulement pendant un enregistrement : c'est lui qui
       voit une séance démarrée d'ailleurs, et surtout une séance que
       l'échéance ou le plafond d'images vient d'arrêter toute seule. Sans
       lui, la carte annoncerait un enregistrement terminé comme s'il durait
       encore. */
    function watch(){
      if(poll)return;
      poll=arm(()=>{
        if(!open||open!==CARD.DIAGNOSTICS){disarm(poll);poll=0;return}
        const before=host.getAttribute('data-bh-recording');
        const model=paintDiagnostics();
        const nowOn=model.running?'true':'false';
        host.setAttribute('data-bh-recording',nowOn);
        if(before==='true'&&nowOn==='false')
          say('Enregistrement terminé.');
      },1000);
    }

    function openDiagnostics(){
      const done=show(CARD.DIAGNOSTICS,()=>{
        const model=paintDiagnostics();
        host.setAttribute('data-bh-recording',model.running?'true':'false');
        say(model.running
          ?'Enregistrement de diagnostic en cours.'
          :'Diagnostic ouvert. Aucun enregistrement en cours.');
      });
      watch();
      return done;
    }

    /* Les trois actions de la carte, **par les portes existantes**. Aucune ne
       réimplante quoi que ce soit : `record.start` et `record.stop` sont
       exactement celles des deux boutons de l'onglet, et rien de ce qui est
       retenu ni de ce qui est conservé ne passe par ici. */
    async function run(act){
      if(busy)return null;
      busy=true;failure='';
      try{
        const surface=surfaceOf();
        if(!surface)
          throw Object.assign(new Error('window.JarvisBarehands absent'),
            {code:'barehands_card_surface_missing'});
        if(act==='settings'){
          if(typeof surface.showSettings!=='function'||!surface.SECTION)
            throw Object.assign(new Error('window.JarvisBarehands.showSettings() manque'),
              {code:'barehands_card_entry_missing'});
          const outcome=await surface.showSettings(surface.SECTION.record);
          /* La carte s'efface derrière l'onglet qu'elle vient d'ouvrir : deux
             surfaces du même sujet empilées, et l'on ne sait plus laquelle
             répond. */
          close({focus:false});
          return outcome;
        }
        if(!surface.record||typeof surface.record[act]!=='function')
          throw Object.assign(new Error(`window.JarvisBarehands.record.${act}() manque`),
            {code:'barehands_card_entry_missing'});
        const outcome=await surface.record[act]();
        if(outcome&&outcome.ok===false){
          /* Le refus du moteur, **avec sa cause réelle**, à l'endroit d'où le
             clic est parti. Bare Hands éteint est le cas courant, et sa phrase
             dit déjà où aller l'allumer. */
          failure=String(outcome.reason||outcome.code||'Refusé.');
          log('warn','barehands.card_record_refused',{act,code:outcome.code||null});
        }else{
          log('info','barehands.card_record_taken',{act,frames:outcome&&outcome.frames});
          say(act==='start'?'Enregistrement démarré.':'Enregistrement arrêté.');
        }
        return outcome;
      }catch(error){
        failure=`L’action « ${act} » n’a pas abouti : ${(error&&error.message)||error}`;
        log('error','barehands.card_record_failed',
          {act,code:(error&&error.code)||null,error:String((error&&error.message)||error)});
        return null;
      }finally{
        busy=false;
        if(open===CARD.DIAGNOSTICS){
          const model=paintDiagnostics();
          host.setAttribute('data-bh-recording',model.running?'true':'false');
          if(failure)say(failure);
        }
      }
    }

    return {
      element:host,card,
      openHelp,openDiagnostics,close,
      opened:()=>open,
      helpModel,
      diagnostics:diagnosticsView,
      failure:()=>failure,
      run,
      destroy(){
        if(poll){disarm(poll);poll=0}
        card.remove();announce.remove();
      },
    };
  }

  const api=Object.freeze({DOM,MODES,TONE,MODE_LABEL,MODE_HINT,CAPTION,STYLE,
    QUICK,QUICK_ORDER,QUICK_LABEL,QUICK_GATE,KBD_MENU_GUARD_MS,
    presentationOf,captionOf,labelOf,noteOf,calibrationBlockOf,quickItemsOf,
    handIcon,createHudControl,
    /* La palette d'outils (Slice 03). Les tables et le modèle pur sont
       exportés au même titre que ceux du contrôle : c'est par eux qu'un test
       décrit « exactement les outils installés, dans ces trois états » sans
       ouvrir de navigateur. */
    SLOT,TOOL_HINT,UNAVAILABLE,ARTLESS,DORMANT,TOOL_ART,GEO,
    PALETTE_TOP,PALETTE_NARROW_TOP,
    paletteOf,toolIcon,createToolPalette,
    /* Les deux cartes rapides (Slice 04). Les tables de liaison et les deux
       modèles purs sont exportés au même titre que les précédents : c'est par
       eux qu'un test vérifie « aucun geste non lié n'est présenté comme une
       commande » sans ouvrir de navigateur. */
    CARD,GESTURE_BOUND,GESTURE_LABEL,CHANNEL_ACTIONS,CHANNEL_POSES,
    FEEDBACK_CASES,RECORD_PRIVACY,UNNAMED_GESTURE,
    helpModel,diagnosticsModel,createQuickCards});
  root.JarvisBarehandsHud=api;
  /* Exécution par les tests (node) ; dans la page, `module` n'existe pas. */
  if(typeof module!=='undefined'&&module.exports)module.exports=api;

  if(typeof window==='undefined'||typeof document==='undefined')return;

  function installJarvisBarehandsHud(){
    const surface=window.JarvisBarehands;
    if(!surface)
      throw new Error('JarvisBarehandsHud : control_center_barehands.js doit être inséré avant ce module');
    if(typeof surface.openLifecycleSeam!=='function')
      throw Object.assign(new Error('JarvisBarehandsHud : la couture de cycle de vie manque sur window.JarvisBarehands'),
        {code:'barehands_hud_seam_missing'});
    /* L'emplacement est **déclaré dans la page**, pas fabriqué ici : c'est lui
       qui porte le rang d'empilement du registre de `control_center.html`, et
       un contrôle qui se poserait tout seul au bout du `body` en sortirait
       sans que rien ne le dise. Absent, on refuse sous un nom cherchable
       plutôt que de choisir un parent plausible. */
    const host=document.getElementById(DOM.hostId);
    if(!host)
      throw Object.assign(new Error(`JarvisBarehandsHud : l’emplacement #${DOM.hostId} manque dans control_center.html`),
        {code:'barehands_hud_host_missing'});

    const control=createHudControl({
      document,host,
      surface:()=>window.JarvisBarehands,
      /* Le menu contextuel de la page, **passé plutôt que pris**. Les deux
         sont des déclarations de fonction du même `<script>`, donc remontées
         et définies même si leur texte vient plus bas ; elles sont enveloppées
         pour que l'appel parte au clic et non à l'insertion, où le `.ctxmenu`
         de la page n'a pas encore été résolu. Absentes — une page servie à
         moitié —, le contrôle s'installe quand même : perdre le clic droit est
         moins grave que perdre le cycle de vie (décision 1), et le menu refuse
         alors sous `barehands_hud_menu_missing`, à l'écran et à la console. */
      showMenu:typeof showMenu==='function'?spec=>showMenu(spec):undefined,
      closeMenu:typeof closeMenu==='function'?restore=>closeMenu(restore):undefined,
      now:()=>Date.now(),
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id),
      setTimeout:(fn,ms)=>window.setTimeout(fn,ms),
      log:(level,event,data)=>{
        const line=`[barehands] ${event} ${JSON.stringify(data)}`;
        if(level==='error')console.error(line);
        else if(level==='warn')console.warn(line);
        else console.info(line);
      },
    });
    /* **L'abonnement, et rien d'autre.** Le contrôle ne sonde pas, ne devine
       pas et ne part d'aucun état d'usine : la couture lui remet l'instantané
       courant tout de suite, puis chaque transition, d'où qu'elle vienne. */
    surface.openLifecycleSeam(DOM.seamName,state=>control.render(state));
    window.JarvisBarehandsHudControl=Object.freeze({
      presentation:control.presentation,snapshot:control.snapshot,
      isOpen:control.isOpen,open:control.open,close:control.close,
      choose:control.choose,failure:control.failure,
      openQuickMenu:control.openQuickMenu,quickItems:control.quickItems,
      runQuick:control.runQuick,
    });
    console.info('[barehands] barehands.hud_installed '
      +JSON.stringify({seam:surface.lifecycleSeam()}));
  }

  /* **La palette s'installe séparément, et c'est le point.** Elle partage ce
     module avec le contrôle de cycle de vie parce qu'elle est la même famille
     et le même coin d'écran, mais elle ne partage pas son sort : si son
     emplacement manque ou si la couture d'outil n'est pas là, c'est la palette
     qui n'apparaît pas, pas la main. L'ordre de gravité est celui de la
     décision 1 — le cycle de vie d'abord — et un seul `try` pour les deux
     l'aurait inversé au premier pépin. */
  function installJarvisBarehandsPalette(){
    const surface=window.JarvisBarehands;
    if(!surface)
      throw new Error('JarvisBarehandsHud : control_center_barehands.js doit être inséré avant ce module');
    if(typeof surface.openToolSeam!=='function')
      throw Object.assign(new Error('JarvisBarehandsHud : la couture d’outil manque sur window.JarvisBarehands'),
        {code:'barehands_palette_seam_missing'});
    if(typeof surface.openLifecycleSeam!=='function')
      throw Object.assign(new Error('JarvisBarehandsHud : la couture de cycle de vie manque sur window.JarvisBarehands'),
        {code:'barehands_hud_seam_missing'});
    const host=document.getElementById(DOM.paletteId);
    if(!host)
      throw Object.assign(new Error(`JarvisBarehandsHud : l’emplacement #${DOM.paletteId} manque dans control_center.html`),
        {code:'barehands_palette_host_missing'});

    const palette=createToolPalette({
      document,host,
      surface:()=>window.JarvisBarehands,
      log:(level,event,data)=>{
        const line=`[barehands] ${event} ${JSON.stringify(data)}`;
        if(level==='error')console.error(line);
        else if(level==='warn')console.warn(line);
        else console.info(line);
      },
    });
    /* **Deux abonnements, deux faits.** L'outil courant vient des réglages,
       la disponibilité du cycle de vie ; les deux rejouent leur instantané à
       l'ouverture, donc la palette est juste dès le chargement et n'attend
       aucun premier changement pour cesser de mentir. C'est la synchronisation
       bidirectionnelle exigée : un `JarvisBarehands.tool('pan')` tapé dans la
       console, un réglage écrit ailleurs ou un rechargement de page arrivent
       par le même chemin qu'un clic sur la bande. */
    surface.openToolSeam(DOM.paletteSeam,state=>palette.renderTool(state));
    surface.openLifecycleSeam(DOM.paletteSeam,state=>palette.renderLifecycle(state));
    window.JarvisBarehandsPalette=Object.freeze({
      model:palette.model,failure:palette.failure,cursor:palette.cursor,
      pick:palette.pick,focusAt:palette.focusAt,
    });
    console.info('[barehands] barehands.palette_installed '
      +JSON.stringify({tools:palette.model().items.map(item=>item.id),
        seam:surface.toolSeam()}));
  }

  /* **La levée reste, mais elle ne sort pas d'ici.** La page servie n'a qu'une
     seule balise `<script>` : tous les modules Bare Hands, la scène, la
     timeline, le Test Lab et ~2500 lignes de logique de page y sont concaténés,
     donc une levée non rattrapée avorterait tout ce qui suit. L'intention
     — casser à l'insertion, pas trois clics plus tard — est juste ; son rayon
     ne doit pas l'être. Rattrapée ici, la panne garde sa portée : ce contrôle
     ne s'installe pas, le reste de la page vit, et la console porte la cause. */
  try{
    installJarvisBarehandsHud();
  }catch(error){
    console.error('[barehands] barehands.hud_not_installed '
      +JSON.stringify({code:(error&&error.code)||null,
        error:String((error&&error.message)||error)}));
  }
  /* **Un second `try`, pas une seconde ligne dans le premier.** Les deux
     surfaces de ce module tombent indépendamment : une palette qui manque
     laisse la main et son sélecteur intacts, et une main qui manque n'emporte
     pas la palette. Confiner deux pannes ensemble aurait fait d'un
     emplacement oublié dans le balisage la perte du contrôle de cycle de vie,
     c'est-à-dire de la décision 1. */
  try{
    installJarvisBarehandsPalette();
  }catch(error){
    console.error('[barehands] barehands.palette_not_installed '
      +JSON.stringify({code:(error&&error.code)||null,
        error:String((error&&error.message)||error)}));
  }

  /* **Les cartes rapides, dans leur propre `try` pour la troisième fois.**
     Même raison que la palette : trois surfaces, trois sorts. Un emplacement
     oublié dans le balisage coûte l'aide et le diagnostic, jamais le contrôle
     de cycle de vie (décision 1).

     Elles ne s'abonnent à **aucune couture** : l'aide est immobile, et le
     diagnostic se relit à la seconde tant que sa carte est ouverte. Ouvrir une
     souscription permanente pour une surface fermée 99 % du temps aurait été
     un battement d'horloge pour rien. */
  function installJarvisBarehandsCards(){
    const surface=window.JarvisBarehands;
    if(!surface)
      throw new Error('JarvisBarehandsHud : control_center_barehands.js doit être inséré avant ce module');
    const host=document.getElementById(DOM.cardsId);
    if(!host)
      throw Object.assign(new Error(`JarvisBarehandsHud : l’emplacement #${DOM.cardsId} manque dans control_center.html`),
        {code:'barehands_cards_host_missing'});

    const cards=createQuickCards({
      document,host,
      surface:()=>window.JarvisBarehands,
      /* Les bornes de l'enregistreur, **lues chez lui**. La carte annonce ce
         qui est réellement en vigueur avant même le premier départ, au lieu
         d'écrire « deux minutes » en dur et de mentir le jour où le défaut
         change. Absentes, la phrase se dit sans chiffre. */
      recorderBounds:()=>(window.JarvisBarehandsRecorder
        &&window.JarvisBarehandsRecorder.DEFAULTS)||null,
      setInterval:(fn,ms)=>window.setInterval(fn,ms),
      clearInterval:id=>window.clearInterval(id),
      log:(level,event,data)=>{
        const line=`[barehands] ${event} ${JSON.stringify(data)}`;
        if(level==='error')console.error(line);
        else if(level==='warn')console.warn(line);
        else console.info(line);
      },
    });
    /* **La porte par laquelle `showHelp()` et `showDiagnostics()` arrivent.**
       Le moteur possède la surface gelée et ne peut pas la compléter après
       coup ; il lit donc ce global au moment du clic, jamais au chargement. */
    window.JarvisBarehandsHudCards=Object.freeze({
      openHelp:cards.openHelp,openDiagnostics:cards.openDiagnostics,
      close:cards.close,opened:cards.opened,
      helpModel:cards.helpModel,diagnostics:cards.diagnostics,
      failure:cards.failure,
    });
    console.info('[barehands] barehands.cards_installed '
      +JSON.stringify({cards:[CARD.HELP,CARD.DIAGNOSTICS]}));
  }

  try{
    installJarvisBarehandsCards();
  }catch(error){
    console.error('[barehands] barehands.cards_not_installed '
      +JSON.stringify({code:(error&&error.code)||null,
        error:String((error&&error.message)||error)}));
  }
})(typeof window!=='undefined'?window:globalThis);
