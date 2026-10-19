# Contrôles humains — refonte roue, carte Board et Dossier (Slice 09)

Préparé par la Slice 08 le 2026-10-19. À faire **sur le JARVIS réel**, après la fusion dans `main` et un
redémarrage que vous lancez vous-même (aucun agent ne démarre ni n'arrête votre JARVIS). Les captures de la
machine sont dans `slices/08-integration-accessibility-regression/evidence/` ; ce qui suit est ce qu'une machine
ne peut pas juger.

Chaque contrôle dit ce qu'il faut faire et ce qui est attendu. Cochez, ou notez ce qui ne va pas avec son
identifiant.

## Au premier démarrage après la fusion

- [ ] **HVAL-08-01 — Votre Board « Jarvis PRESENTATION ».** Au premier démarrage, la base passe en version 9
  (copie `jarvis.sqlite3.v8.bak` à côté d'elle, une ligne `core.state.migrated` dans la trace). Regardez la carte
  du bas à gauche. Attendu : « Présentation · Jarvis PRESENTATION », et JARVIS se comporte en mode PRESENTATION
  (il écoute la salle et reste discret). Si vous préférez ce Board en Assistant, créez un Board Assistant et
  basculez dessus : le type ne se change plus après la création (décision D02). « Board principal » est
  Assistant, « Mon Q » reste archivé.

## Les essentiels

- [ ] **HVAL-09-01 — Une vraie séance.** Travaillez normalement : changez de Board, ouvrez chaque catégorie de
  la roue, lancez et arrêtez une capture, masquez, rangez et réaffichez un contenu, passez plusieurs minutes dans
  le Dossier, puis revenez au Board. Comparez la roue avec `assets/style-reference-radial-ui.png` et l'écran avec
  `assets/current-ui-before.png`. Attendu : vous pensez « type de Board + carte Board », jamais « mode
  d'interaction » ; les anciennes commandes ont disparu ; la roue paraît vraiment redessinée et n'affiche jamais
  deux sous-menus ; la capture ne se montre que pendant un enregistrement ; le Dossier est agréable à lire et
  montre bien ce que Jarvis peut utiliser.
- [ ] **HVAL-02-01 — Carte Board.** Avec la carte du bas à gauche, passez d'un Board à un autre et créez un Board
  temporaire d'un type choisi. Attendu : la carte est compacte et évidente, aucun autre sélecteur de Board ou de
  mode ne lui fait concurrence, le type se voit mais ne se modifie plus.
- [ ] **HVAL-03-01 — Roue.** Utilisez la roue à la souris, puis au clavier : ouvrez JARVIS, passez directement à
  Capture, puis à Dossier, et fermez. Attendu : plus soignée et plus « en couches » qu'avant, un seul sous-menu à
  la fois, des libellés compris tout de suite, rien de pris à l'espace de travail quand elle est fermée. Dites si
  le panneau de JARVIS ou de Paramètres, qui déborde un peu au-dessus ou au-dessous de son secteur pour que toutes
  les lignes restent à l'écran à 720 px, vous gêne (QA S03, point 5).
- [ ] **HVAL-04-01 — Capture.** Lancez ensemble un court enregistrement audio et un court enregistrement d'écran
  depuis la catégorie Capture, regardez les indicateurs en haut à gauche, puis arrêtez les deux depuis eux.
  Attendu : la capture forme une seule fonction, les états actifs ne se voient que pendant l'enregistrement, les
  deux coexistent, et il ne reste aucune commande de capture ensuite. (La machine n'a ni ffmpeg ni micro : seul ce
  contrôle prouve une vraie vidéo et un vrai son.)
- [ ] **HVAL-06-01 — Masquer, Ranger, Retirer.** Sélectionnez un Artifact durable et un objet ordinaire. Essayez
  Masquer puis Réafficher, Changer la forme, Ranger dans le Dossier, Retirer du Board ; puis réaffichez sur le
  Board l'élément rangé, depuis le Dossier. Attendu : la différence entre masquer, ranger, changer de forme et
  retirer est évidente, et aucun contenu ne se perd sans que vous le sachiez.
- [ ] **HVAL-07-01 — Dossier.** Ouvrez le Dossier depuis la roue, trouvez et ouvrez un compte rendu et une image,
  comparez deux éléments, corrigez une note, puis demandez à Jarvis d'ouvrir un autre document nommé et d'en
  afficher un sur le Board. Attendu : un vrai environnement de travail ; la navigation de Jarvis se voit et se
  prévoit ; vos corrections et les présentations sur le Board portent sur le même contenu, sans copie mystère.
  (Machine : après votre correction, Jarvis a relu la version corrigée ; voir le LOG, Slice 08.)

## Gardés de la tâche orbital-ui (toujours valides, reformulés)

- [ ] **HV-03-01 — Souris / Bare Hands.** Roue › Sélection › Bare Hands, travaillez à la main, puis bougez ou
  cliquez la souris exprès ; laissez aussi la souris immobile. Attendu : un geste voulu reprend la souris vite, un
  tremblement non ; le retour à Bare Hands se fait par un choix explicite.
- [ ] **HV-05-01 — Aperçu de capture.** Prenez une capture et ignorez l'aperçu une fois, puis recommencez en
  essayant Ouvrir, Supprimer, Envoyer et Annoter. Attendu : l'aperçu ne bloque jamais le travail, ses actions sont
  claires et utiles.
- [ ] **HV-05-02 — Aperçu, sur un vrai tour.** Prenez une capture, cliquez « Envoyer à Jarvis », écrivez une
  question, envoyez, puis regardez la trace du tour. Attendu : le cerveau parle de l'image après un seul Read du
  payload, nommé « Capture d'écran HH-MM-SS.png ».
- [ ] **HV-05-03** — Rechargez la page sans ouvrir le Chat, prenez une capture puis « Envoyer à Jarvis ». Attendu :
  la puce « En attente de la conversation… N s » devient prête ; sinon l'échec est dit clairement.
- [ ] **HV-05-04** — Sur un écran de 1920 px ou plus, « Annoter » une capture plein écran, tracez, enregistrez.
  Attendu : l'éditeur tient dans l'écran, la copie s'enregistre, l'aperçu affiche « · annotée ».
- [ ] **HV-05-05** — En thème Cosmos avec Bare Hands actif, prenez une capture et utilisez l'aperçu. Attendu : il
  ne bloque ni la main ni la souris, ses actions répondent au pincement.
- [ ] **HV-07-01 — Rail.** Un rail mêlant présentations et médias dans plusieurs états ; ouvrez-en plusieurs.
  Attendu : le type se reconnaît d'un coup d'œil, les aperçus sont fidèles, les états ne dépendent pas de la
  couleur seule.
- [ ] **HV-08-02** — À 1280×720, rail affiché, ouvrez « Plus d'outils ». Attendu : le popover qui passe sur le
  haut du rail reste acceptable, se ferme par un clic ailleurs ou Échap, le rail est intact ensuite.
- [ ] **HV-08-03** — En thème Cosmos, regardez la rangée du lanceur : CNV, AGT, ERR, puis « Plus d'outils »
  (Réglages, l'ancien SET, est en tête de « Plus d'outils » ; la roue › Paramètres ouvre les mêmes onglets).
  Attendu : l'ordre vous convient et c'est le même qu'en circuit imprimé ; Réglages se trouve sans consigne.
- [ ] **HV-08-04** — Bare Hands actif, pincez « Plus d'outils », puis un outil du popover. Attendu : le popover
  s'ouvre au premier pincement, l'outil au second, une seule fois, puis le popover se ferme.
- [ ] **HV-09-07** — Ouvrez Variantes (fenêtré) avec le rail affiché. Attendu : aucun morceau du lanceur ne
  dépasse dans l'interstice, l'en-tête affiche « PRÉSENTATIONS » en entier.
- [ ] **HV-09-08** — Sous 940 px, un panneau latéral ouvert (Agents ou Erreurs), provoquez deux notifications.
  Attendu : qu'elles passent sur le panneau le temps de leur affichage reste acceptable ; c'est le seul
  recouvrement admis.

## Accessibilité réelle (reformulée pour la nouvelle coque)

- [ ] **HVAL-08-02 — Zoom 200 %.** Zoomez réellement à 200 % (Ctrl et +, fenêtre 1440×900), ouvrez la roue et
  chaque catégorie, la carte Board, le Dossier, prenez une capture. Attendu : tout reste dans l'écran, rien ne se
  recouvre, la carte Board et l'onglet Chat restent utilisables. (Remplace HV-09-02 / HV-06-05.)
- [ ] **HVAL-08-03 — Contraste élevé de Windows.** Parcourez la roue (secteurs, sous-menus), la carte Board et son
  panneau, les indicateurs d'enregistrement, les pastilles du bas, le Dossier et le lanceur. Attendu : chaque
  commande a un bord visible, le focus se voit partout, aucun état ne dépend de la couleur seule. (Remplace
  HV-09-03 / HV-06-04 ; la machine a vérifié les couleurs forcées émulées, `refus-capture-1280x720-circuit-fc.png`.)
- [ ] **HVAL-08-04 — Lecteur d'écran (Narrateur ou NVDA).** Au clavier : l'ancre de la roue, un secteur
  (« Capture » et son aide « Entrée ou flèche droite… »), une ligne d'état de JARVIS, la carte Board (« Présentation
  Projet Atlas : Board actif. Ouvrir la liste des Boards »), une puce REC, une ligne du panneau des Boards, le
  groupe « Plus d'outils », un onglet du Dossier. Attendu : chaque nom et chaque état sont annoncés, les noms du
  lanceur sont identiques après un aller-retour de thème. (Remplace HV-08-05 / HV-09-04.)
- [ ] **HVAL-08-05 — Accès vocal de Windows.** Dites « cliquer Outils » (l'ancre de la roue), « cliquer
  Capture », « cliquer CNV » puis, pendant un enregistrement d'écran, « cliquer REC ». Attendu : chaque commande
  atteint le bon bouton du premier coup et « cliquer REC » arrête l'enregistrement. (Remplace HV-09-05 : il n'y a
  plus de « Mode Assistant » à cliquer.)

## Ne plus demander (rendus caducs par cette tâche)

HV-01-01, HV-02-01, HV-04-01, HV-06-01 (œil), HV-06-02, HV-06-03, HV-06-06, HV-06-07, HV-06-08, HV-06-09,
HV-08-01 (tranché par D04 : Board en bas à gauche), HV-09-01, HV-09-06, HV-10-01, et HV-06-04/05, HV-08-05,
HV-09-02..05 dans leur ancienne formulation (remplacés ci-dessus) — `docs/08-readiness-audit.md` §5.
