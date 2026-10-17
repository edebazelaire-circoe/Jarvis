# Recette Human — Orbital UI, roue d'outils, centre d'état, rail de travail

Ce dossier rassemble tous les checks des `slices/*/human-validation.json` (HV-01 à HV-10).
Chaque check dit quoi faire, quoi attendre, et son identifiant HV : notez « OK » ou ce qui
vous gêne en face de l'identifiant.

**Avant de commencer.**

- La recette se fait sur la branche `task/jarvis-board-orbital-ui-workspace-rail` : `main`
  ne contient la tâche que jusqu'à la Slice 03. Une fois la branche en place, JARVIS doit être
  relancé pour charger la nouvelle page : c'est à vous de le faire (aucun agent ne l'a fait).
- Les deux images de référence sont dans `assets/` : `current-ui.png` (avant) et
  `target-ui-reference.png` (la cible que vous avez approuvée).
- Les checks d'accessibilité réelle (contraste élevé, zoom, lecteur d'écran, Accès vocal) sont
  regroupés à la fin. Les tests automatiques ne les ont qu'émulés.

**Ce qui a changé et se voit tout de suite.**

- Le thème par défaut « circuit imprimé » prend la géométrie de Cosmos : ligne d'état en haut à
  gauche, lanceur en rangée en haut à droite, plus de marque. Seule la peau diffère entre les deux
  thèmes.
- F9 n'a plus de capsule « F9 · DÉMARRER » en bas au centre. La consigne est dans l'infobulle de la
  ligne d'état, et la touche fonctionne comme avant.
- Le dock de 10 boutons est réduit à 5 : CNV, AGT, ERR, SET et « Plus d'outils », qui contient
  TRC, LAB, MCP, WSP, PFB et INS.
- Le rail des présentations passe à droite (cartes avec aperçu, section « Sur ce Board »).
- Le bord gauche ne porte plus que l'ancre de la roue : la palette et le contrôle Bare Hands
  sont rangés dans la roue, sous Sélection.
- Le bas au centre devient le centre d'état : enregistrements, pastilles d'alertes et œil des
  objets masqués.

## Les essentiels (à faire en premier)

1. **Roue.** Approchez la souris du bord gauche, ouvrez la roue, survolez puis choisissez chaque
   secteur. Attendu : l'ancre se trouve sans gêner, la roue répond tout de suite, elle est lisible
   et facile à viser. — **HV-02-01**
2. **Souris / Bare Hands.** Sélection › Bare Hands, travaillez à la main, puis bougez ou cliquez la
   souris exprès ; laissez aussi la souris immobile. Attendu : un geste voulu reprend la souris
   vite, un tremblement non ; le retour à Bare Hands se fait par un choix explicite. — **HV-03-01**
3. **Captures.** Depuis la roue, lancez puis arrêtez un enregistrement audio et un enregistrement
   vidéo, puis prenez une capture d'écran. Attendu : les actions sont évidentes, l'arrêt se trouve
   facilement, et les durées restent visibles roue fermée. — **HV-04-01**
4. **Aperçu, sur un vrai tour.** Sur le JARVIS réel, prenez une capture, cliquez « Envoyer à
   Jarvis », écrivez une question, envoyez, puis regardez la trace du tour. Attendu : le cerveau
   parle de l'image après un seul Read du payload, nommé « Capture d'écran HH-MM-SS.png ».
   — **HV-05-02**
5. **Aperçu, usage courant.** Prenez une capture et ignorez l'aperçu une fois, puis recommencez en
   essayant chaque action (Ouvrir, Supprimer, Envoyer, Annoter). Attendu : l'aperçu ne bloque
   jamais le travail, et ses actions sont claires et utiles. — **HV-05-01**
6. **Centre d'état et œil.** Avec plusieurs catégories d'alertes, regardez le bas au centre, puis
   allumez et éteignez l'œil. Attendu : les compteurs se lisent sans s'imposer, l'état de l'œil se
   comprend, le bas de l'écran n'est pas encombré. — **HV-06-01**
7. **Rail.** Affichez un rail mêlant présentations et médias dans plusieurs états, puis ouvrez
   plusieurs éléments. Attendu : le type se reconnaît d'un coup d'œil, les aperçus sont fidèles, et
   les états se distinguent sans dépendre de la couleur seule. — **HV-07-01**
8. **Lanceur et Board.** Sans consigne, trouvez Réglages, les outils de diagnostic et de travail,
   changez de mode puis de Board. Dites ensuite si le Board doit rester dans la ligne d'état en
   haut (la cible, choix par défaut D11) ou descendre en bas à gauche, à côté du mode. Attendu :
   tout reste trouvable et l'écran est visiblement allégé. — **HV-08-01**
9. **Une vraie séance.** Travaillez normalement avec le Board, la roue, le rail, les alertes et
   une capture. Attendu : aucune commande ne concurrence le Board, et les transitions comme la
   hiérarchie suivent la direction artistique approuvée. — **HV-09-01**
10. **Comparaison finale.** Comparez l'écran final côte à côte avec `current-ui.png` et
    `target-ui-reference.png`. Attendu : la transformation est nette (roue rétractable à gauche,
    centre d'état en bas, rail riche à droite, habillage allégé, mode en bas à gauche, direction
    Cosmos). Pas d'identité au pixel près : le Board reste l'élément le plus fort. —
    **HV-10-01**, **HV-01-01**

## Bord gauche : la roue

- Les checks HV-02-01, HV-03-01 et HV-04-01 sont dans les essentiels.

## Aperçu de capture (bas gauche)

- Rechargez la page sans ouvrir le Chat, prenez une capture puis cliquez « Envoyer à Jarvis ».
  Attendu : la puce « En attente de la conversation… N s » s'affiche puis devient prête ; si rien
  ne vient, l'échec est dit clairement. — **HV-05-03**
- Sur un écran de 1920 px ou plus, ouvrez « Annoter » sur une capture plein écran, tracez, puis
  enregistrez. Attendu : l'éditeur tient dans l'écran, la copie s'enregistre et l'aperçu affiche
  « · annotée ». — **HV-05-04**
- En thème Cosmos avec Bare Hands actif, prenez une capture et utilisez l'aperçu. Attendu : il ne
  bloque ni la main ni la souris, et ses actions répondent au pincement. — **HV-05-05**
- Bare Hands actif (badge visible), coupez la lecture de la scène pour afficher « Scène figée » sur
  deux lignes, puis prenez une capture depuis la roue. Attendu : l'aperçu se pose au-dessus du
  bouton de mode sans le couvrir, et la note reste lisible. — **HV-06-09**

## Bas au centre : centre d'état et œil

- En Bare Hands, faites le pincement pouce + majeur sur l'œil. Attendu : la liste des objets
  masqués s'ouvre, comme au clic droit. — **HV-06-03**
- Allumez l'œil pour voir les fantômes, puis rechargez la page. Attendu : l'œil revient allumé avec
  les mêmes fantômes (préférence de ce navigateur). — **HV-06-06**
- Coupez la lecture de la scène (Control Center injoignable), à 1440 px puis à 1280 px de large.
  Attendu : « Scène figée · <cause> » se lit en entier, sans couvrir le bouton de mode ni le centre
  d'état. — **HV-06-08**

## Haut gauche : ligne d'état et Board

- Survolez la ligne d'état (infobulle « F9 · DÉMARRER » et ses variantes), puis utilisez le
  push-to-talk. Attendu : l'infobulle F9 se trouve ; dites si l'ancienne capsule visible vous
  manque. — **HV-06-02**
- Le choix de la place du Board se fait dans HV-08-01 (essentiels).

## Haut droite : le lanceur

- En thème Cosmos, regardez la rangée du lanceur. Attendu : l'ordre CNV, AGT, ERR, SET, puis
  « Plus d'outils », vous convient ; c'est le même qu'en circuit imprimé. — **HV-08-03**
- Avec Bare Hands actif, pincez « Plus d'outils », puis un outil du popover. Attendu : le popover
  s'ouvre au premier pincement et l'outil au second, une seule fois, puis le popover se ferme.
  — **HV-08-04**

## Droite : le rail

- À 1280×720, rail des présentations affiché, ouvrez « Plus d'outils ». Attendu : le popover qui
  passe sur le haut du rail reste acceptable, se ferme par un clic ailleurs ou par Échap, et le
  rail est intact ensuite. — **HV-08-02**
- Ouvrez Variantes (fenêtré) avec le rail affiché. Attendu : aucun morceau du lanceur (CNV) ne
  dépasse dans l'interstice, et l'en-tête affiche « PRÉSENTATIONS » en entier (le compte peut
  passer à la ligne). — **HV-09-07**

## Petites fenêtres

- À 700 px de large ou moins, lancez un enregistrement d'écran. Attendu : la puce REC est dans la
  colonne de droite, lisible, et arrête l'enregistrement d'un geste. — **HV-06-07**
- À 700 px ou moins, Bare Hands actif (« MAINS · ACTIF ») et Core coupé, prenez une capture par la
  roue. Attendu : l'aperçu ne couvre ni « MODE ? » ni « Scène figée », et ses quatre actions
  restent cliquables. — **HV-09-06**
- Sous 940 px, avec un panneau latéral ouvert (Agents ou Erreurs), provoquez deux notifications (une
  tâche qui se termine, un sous-agent en échec). Attendu : qu'elles passent sur le panneau le temps
  de leur affichage reste acceptable ; c'est le seul recouvrement admis. — **HV-09-08**

## Accessibilité réelle (Windows, navigateur, lecteur d'écran)

- Zoomez réellement le Control Center à 200 % (Ctrl et +, fenêtre 1440×900), ouvrez la roue,
  prenez une capture, ouvrez les alertes et le sélecteur de mode. Attendu : tout reste dans
  l'écran, rien ne se recouvre, et le centre d'état, le mode et l'onglet Chat restent utilisables.
  — **HV-09-02**, **HV-06-05**
- Activez un thème à contraste élevé de Windows, puis parcourez la roue, le centre d'état (pastilles,
  œil, puces REC), le rail, le lanceur et le mode. Attendu : chaque commande a un bord visible, le
  focus se voit partout, et aucun état ne dépend de la couleur seule. — **HV-09-03**, **HV-06-04**
- Avec le Narrateur ou NVDA, parcourez le groupe « Plus d'outils » au clavier. Attendu : le bouton,
  son état replié ou déplié, chaque outil et l'outil ouvert (« Ouvert : … ») sont annoncés. —
  **HV-08-05**
- Toujours au lecteur d'écran, écoutez une puce REC, une ligne du choix de Board, un outil « en
  cours » de la roue, puis le lanceur dans les deux thèmes. Attendu : « REC — arrêter
  l'enregistrement d'écran », puis le titre du Board et « Basculer sur ce Board » (ou « Board
  actif ») ; les noms du lanceur sont identiques après un aller-retour de thème. — **HV-09-04**
- Avec l'Accès vocal de Windows, dites « cliquer Mode Assistant », « cliquer CNV » puis, pendant un
  enregistrement d'écran, « cliquer REC ». Attendu : chaque commande atteint le bon bouton du
  premier coup, et « cliquer REC » arrête l'enregistrement. — **HV-09-05**

## Hors liste HV (à regarder si vous en avez l'occasion)

- Dites à JARVIS « passe en souris » pendant que Bare Hands est actif. Attendu : Bare Hands
  s'éteint, et la trace montre un seul `settings_set(barehands.enabled,false)`. Cette analyse de
  trace n'a pas pu être faite sans le JARVIS réel (Slices 03 et 09).
