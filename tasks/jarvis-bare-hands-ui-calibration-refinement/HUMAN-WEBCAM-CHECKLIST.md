# Bare Hands — ce qui doit passer devant une vraie webcam

Produit par la Slice 08. C'est la liste que l'Humain tient en main.

## Pourquoi cette liste existe

`node` ne peut **structurellement** pas pousser le contrôleur au-delà de
`starting` : `createLandmarker` importe le bundle MediaPipe et il n'y a pas de
caméra, donc `enable()` finit toujours en `camera_unsupported`. Conséquence
directe : **les présentations `sleep` et `active` n'ont jamais été rendues
contre un contrôleur vivant.** Tout ce qui est visuel dans cette tâche est
*argumenté et testé structurellement*, jamais constaté à l'œil.

Une case cochée ici vaut donc plus qu'un test vert : c'est la seule preuve
existante pour tout ce qui suit.

**Avant de commencer :** Bare Hands éteint, page du Control Center rechargée,
webcam standard branchée, lumière normale. Faites les 13 points **dans
l'ordre** — plusieurs dépendent de l'état laissé par le précédent.

---

## A. Cycle de vie et contrôle HUD

### 1. Trouver le contrôle sans qu'on vous le montre — `HV-BH-UI-01`

**Faire.** Rechargez la page sans toucher aux réglages. Cherchez de quoi
allumer Bare Hands.

**Attendu.** Un contrôle à **icône de main**, en trait, en **haut à gauche**,
hors du dock de droite.

**Serait faux.** Devoir ouvrir les Réglages pour allumer. Un bouton à étiquette
texte de trois lettres (c'est la convention du dock, et ce contrôle n'en est
pas un). Un contrôle qui ne réagit pas au clic parce que `.topbar` coupe les
`pointer-events` — le contrôle doit les rétablir localement.

### 2. Les trois états se distinguent à l'œil — `HV-BH-UI-01`

**Faire.** Passez OFF → SLEEP → ACTIVE → OFF au clic gauche, en regardant le
contrôle à chaque fois.

**Attendu.** OFF lit clairement « inactif ». SLEEP lit « armé, normal ».
ACTIVE est **distinctement mais sobrement** plus lumineux / bleu électrique.

**Serait faux.** Deux états qu'on ne distingue qu'en les comparant côte à côte.
Un ACTIVE tapageur au point de tirer l'œil en permanence. Un état qui reste
affiché après que la réalité a changé.

> **Jamais rendu par une machine.** `sleep` et `active` n'ont pas de couverture
> visuelle du tout. Ce point est la première fois que quiconque les voit.

### 3. Le réveil en C, et le retour en veille — `HV-BH-UI-01`

**Faire.** Depuis SLEEP, formez un **C** avec pouce et index (écartés sans se
toucher, index déplié) et **tenez une seconde**. Puis retirez vos mains du
champ et attendez 30 s.

**Attendu.** Un anneau se remplit autour de la main pendant le maintien ; à la
fin, le contrôle passe à ACTIVE **tout seul**. Après 30 s sans main sûre, il
retombe à SLEEP tout seul, caméra toujours ouverte.

**Serait faux.** Le contrôle reste à SLEEP alors que l'interaction est active
(la couture de diffusion `openLifecycleSeam` est la seule chose qui le tient —
c'est du travail neuf de la Slice 01). Rouvrir la main avant la fin réveille
quand même. Le retour en veille éteint la caméra.

### 4. Éteindre depuis une panne — `HV-BH-UI-01`

**Faire.** Provoquez une erreur caméra (refusez la permission, ou débranchez la
webcam pendant qu'elle tourne), puis choisissez **Éteint**.

**Attendu.** Le contrôle passe à OFF. Le toast « Caméra refusée » peut rester
affiché — c'est le journal de l'événement — mais le **bouton** montre l'état
courant.

**Serait faux.** Le contrôle reste rouge après une demande explicite
d'extinction. C'est exactement le défaut corrigé en `e11c924` ; c'est ici qu'on
vérifie qu'il ne revient pas.

---

## B. Outils et actions rapides

### 5. La palette, en pleine session — `HV-BH-UI-03`

**Faire.** Bare Hands ACTIVE, manipulez la scène normalement et basculez
plusieurs fois entre **Pointeur**, **Main** et **Sélection** — **sans jamais
ouvrir les Réglages**.

**Attendu.** Une bande verticale fixe au bord gauche, sous la main. Le
basculement est immédiat et **l'outil actif est évident sans réfléchir**.

**Serait faux.** Devoir ouvrir un modal pour changer d'outil. Une ambiguïté sur
lequel des trois est actif. Un **quatrième** outil dans la palette — seuls
Pointeur / Main / Sélection sont installés, et rien ne doit préparer
l'affordance des autres.

### 6. Le changement d'outil venu d'ailleurs — `HV-BH-UI-03`

**Faire.** Panneau de réglages **fermé**, changez l'outil par la voix ou depuis
une autre surface.

**Attendu.** La palette se repeint toute seule.

**Serait faux.** La palette reste sur l'ancien outil jusqu'à ce qu'on la
touche. (La couture `openToolSeam` est délibérément distincte de celle du cycle
de vie ; si elle est fondue, « l'outil a changé » passe pour un événement de
cycle de vie.)

### 7. Les quatre destinations du clic droit — `HV-BH-UI-02`

**Faire.** Clic **droit** sur le contrôle à icône de main. Ouvrez chacune des
quatre entrées.

**Attendu.** Exactement quatre : **Réglages**, **Calibration**, **Aide ·
Gestes**, **Diagnostic**. Chacune ouvre ce qu'elle annonce.

**Serait faux.** Une entrée **Tutoriel** (le parcours n'existe plus). Une
entrée d'activation (le cycle de vie est au clic gauche, et deux commandes pour
un même état finissent par se contredire). Cinq entrées. Une entrée qui ouvre
l'onglet en haut sans révéler sa section.

### 8. Les refus se disent, et disent **lequel** — `HV-BH-UI-02` · Slice 08

**Faire.** Deux essais distincts, et lisez la phrase à chaque fois :

1. Bare Hands **éteint**, clic droit → regardez « Calibrer… ».
2. Rallumez, ouvrez les Réglages, **décochez « Proposer la calibration »**,
   refermez, clic droit → regardez « Calibrer… ».

**Attendu.** Dans les deux cas l'entrée est grisée et **porte sa raison dans
son libellé**. Cas 1 : « Bare Hands est éteint : choisissez Veille ou Actif
d'abord ». Cas 2 : « "Proposer la calibration" est décoché dans les réglages ».
Deux phrases différentes, deux remèdes différents.

**Serait faux.** La même phrase dans les deux cas. Une entrée grisée **muette**.
Une entrée réellement `disabled` — elle doit être `aria-disabled` pour rester
atteignable au clavier, sans quoi un lecteur d'écran n'apprend jamais pourquoi
l'action manque. **Testez-le au clavier** : tabulez jusqu'à l'entrée grisée,
elle doit être atteinte et lue.

> La Slice 08 a séparé les deux **codes** derrière ces deux phrases
> (`barehands_calibration_disabled` / `barehands_calibration_lifecycle_off`).
> Les phrases, elles, n'ont jamais été vues à l'écran.

### 9. Une panne **ne** grise **pas** — `HV-BH-UI-02`

**Faire.** Provoquez une erreur caméra, puis clic droit.

**Attendu.** « Calibrer… » reste **choisissable**. Le refus arrive à
l'exécution, avec sa cause réelle.

**Serait faux.** L'entrée grisée. Depuis une panne, `activate()` peut
parfaitement reprendre la caméra ; griser dirait « ça ne marchera pas » là où
la vérité est « il faut essayer pour savoir ».

---

## C. Aide et diagnostic

### 10. L'aide se comprend en ayant tout oublié — `HV-BH-UI-04`

**Faire.** Ouvrez **Aide · Gestes** en vous mettant dans la peau de quelqu'un
qui a oublié les contrôles. Lisez-la en entier.

**Attendu.** Aérée et visuelle ; les gestes importants se comprennent à
l'espacement, aux mains schématiques et à une copie courte. Un bloc **« Reconnus,
sans effet »** nomme main ouverte / poing / double fermeture / claquement
**sans dessin et sans verbe d'action**.

**Serait faux.** Un mur de texte. Un geste non lié présenté comme une commande.
Le pincement **secondaire** rangé parmi les non-liés — il est lié, il ouvre un
vrai menu contextuel.

### 11. La légende du jeton — **nouveau en Slice 08**

**Faire.** Dans la carte d'aide, trouvez le bloc **« Ce que vous voyez à
l'écran »**. Puis, Bare Hands ACTIVE, **provoquez la main non fiable** :
éloignez une main jusqu'au bord du champ, ou sortez-la et rentrez-la vite.

**Attendu.** Le bloc décrit le jeton rond (suit l'index, grossit au survol,
anneau qui se remplit, se fige pour viser, onde au clic) **et** le jeton pâle
et pointillé. À l'écran, la main peu fiable porte bien un jeton **pâle et
pointillé**, reste cliquable, et ne retarde pas le retour en veille.

**Serait faux.** Ce que le bloc décrit ne ressemble pas à ce que vous voyez —
c'est le seul point où la légende et la réalité peuvent diverger, et aucune
machine ne les a comparées. Des **astérisques** affichés tels quels au milieu
d'une phrase (défaut déjà réparé une fois en `1912d91`). Un jeton pâle qu'on ne
sait toujours pas lire après avoir lu le bloc.

### 12. Les deux limites connues — **nouveau en Slice 08**

**Faire.** Ouvrez les **Réglages**, descendez en bas de la section : bloc
**« Deux limites connues »**. Puis vérifiez-les pour de bon, au pincement :
pincez sur une **liste déroulante** de l'interface, puis sur le **visage
ai-visualizer**.

**Attendu.** Le bloc annonce les deux, et les deux se comportent comme
annoncé : la liste ne s'ouvre pas, le visage ne reçoit pas le clic. Le bloc ne
porte **ni case ni curseur** — ce n'est pas un réglage.

**Serait faux.** Le bloc promet autre chose que ce qui arrive. Le bouton
« Réinitialiser les réglages » prétend rendre sa valeur d'usine à ce bloc (il
annonce « les six réglages ci-dessus » — le bloc n'en fait pas partie). Le bloc
s'intercale entre deux contrôles au lieu de fermer la section.

### 13. Le diagnostic respecte la RÈGLE ZÉRO — `HV-BH-UI-04`

**Faire.** Clic droit → **Diagnostic**. Lancez une capture. **Regardez-la
tourner au moins 15 secondes sans rien faire.** Puis arrêtez-la. Relancez-en
une et laissez-la s'arrêter **toute seule** par son échéance.

**Attendu.** Pendant la capture, les quatre exigences sont à l'écran **en
permanence** : un témoin qui bat et une barre qui balaie (ça tourne),
« Enregistrement en cours » (quoi), le temps écoulé **et** le temps restant
relus chaque seconde (depuis combien de temps), un bouton Arrêter + Échap
(comment en sortir). L'échéance et le plafond d'images sont annoncés **avant**
de démarrer. Quand l'échéance arrête la séance, la carte **le dit**.

**Serait faux.** Un libellé statique sans mouvement — indiscernable d'une page
figée. Pas de compteur : « ça travaille » et « c'est bloqué » se ressemblent.
Une capture terminée par son échéance encore annoncée comme en cours. Ouvrir la
carte **démarre** un enregistrement (elle ne doit rien enregistrer à
l'ouverture).

---

## D. Calibration

### 14. La composition plein écran — `HV-BH-CAL-05`

**Faire.** Ouvrez la calibration sur la scène Jarvis normale. Redimensionnez la
fenêtre : étroite, large, basse.

**Attendu.** Un **mode Jarvis plein écran** : hiérarchie, respiration, flou de
fond, texte placé sur les bords, **centre de l'écran disponible pour
l'exercice**, sortie visible.

**Serait faux.** Une **carte centrée** au milieu de l'écran — c'est exactement
ce que la Slice 05 a retiré, et le centre doit appartenir à l'exercice. Du
texte qui déborde ou se chevauche à une taille de fenêtre donnée. Pas de moyen
de sortir visible.

### 15. Lire avant de mesurer — `HV-BH-CAL-06`

**Faire.** Pour **chacune** des étapes 1 à 5 : **laissez vos mains sur vos
genoux**, lisez la consigne tranquillement, à votre rythme. Ne vous engagez
qu'ensuite.

**Attendu.** Rien n'expire pendant la lecture. La mesure ne commence qu'**après
votre engagement** (phases `INTRO` → `ARMED` → `RUNNING` → `RESULT`).

**Serait faux.** Une étape qui expire alors que vous lisiez. Un chronomètre qui
tourne avant que vous ayez bougé. C'est le défaut central que la Slice 06
existe pour réparer.

### 16. Les gestes sont visuellement sans équivoque — `HV-BH-CAL-06`

**Faire.** À chaque exercice, regardez la main schématique **avant** de faire
le geste, et faites ce qu'elle montre.

**Attendu.** C, pincement primaire, pincement secondaire et mire visée sont
**immédiatement** reconnaissables. La main est en **trait**, schématique, pas
anatomique — et c'est le même vocabulaire graphique que l'icône du contrôle en
haut à gauche.

**Serait faux.** Devoir lire le texte pour comprendre le dessin. Deux
pincements qu'on ne distingue pas. Une main trop détaillée pour se lire d'un
coup d'œil. Deux jeux de mains différents entre l'aide et la calibration.

### 17. La pratique de fenêtre, sur un **vrai** cadre — `HV-BH-CAL-07`

**Faire.** Allez jusqu'à l'**étape 6**. Avec la webcam : d'abord **déplacez**
le cadre de pratique depuis un bord ou un coin, puis **redimensionnez**-le par
**deux zones compatibles distinctes**.

**Attendu.** Ça se comporte comme les vrais cadres Jarvis — même géométrie,
même sensation. Les deux sous-étapes sont compréhensibles.

**Serait faux.** Un cadre qui bouge autrement que les vrais cadres de la scène.
Une seule sous-étape au lieu de deux.

### 18. Scène éteinte : l'étape refuse au lieu d'inventer — `HV-BH-CAL-07`

**Faire.** Éteignez la scène, puis relancez une calibration et allez jusqu'à
l'étape 6.

**Attendu.** L'étape se marque **`skipped` avec une raison nommée**, et le
rapport final le dit.

**Serait faux.** Un cadre de pratique **inventé** sur une scène éteinte. C'est
la règle fondatrice du contrat : un refus codé plutôt qu'un défaut plausible.

### 19. La séquence entière, une fois, sans s'arrêter — `HV-BH-UI-08`

**Faire.** Calibration complète, les sept écrans, du début au rapport final.

**Attendu.** L'enchaînement se tient : on sait toujours où on en est, combien
il reste, et comment sortir. Le rapport dit ce qui a été mesuré.

**Serait faux.** Une étape dont on ne sait pas sortir. Un rapport avec un
statut que la coque ne sait pas dessiner (elle doit **refuser** un statut
inconnu, pas l'afficher à moitié).

---

## E. Voix, et la disparition du tutoriel

### 20. La voix change l'état, et l'écran suit — `HV-BH-UI-08`

**Faire.** Panneau de réglages **fermé**, demandez à JARVIS d'activer puis
d'endormir Bare Hands.

**Attendu.** Le contrôle en haut à gauche se repeint **tout seul**, sans que
vous ayez touché la page.

**Serait faux.** Le contrôle reste sur l'ancien état. C'est le cœur de la
Slice 01 : avant elle, un changement venu de la voix n'atteignait le panneau
que parce que le panneau vivait dans le même module.

### 21. L'alias déprécié dit la vérité — `HV-BH-UI-08`

**Faire.** Demandez à JARVIS **le tutoriel**, explicitement.

**Attendu.** **La calibration s'ouvre**, et JARVIS vous dit que c'est la
calibration qui a été ouverte — pas « j'ai lancé le tutoriel ».

**Serait faux.** JARVIS annonce un tutoriel. Un refus portant un code en
`tutorial_*` au lieu du code de la calibration — c'est précisément la vérité
que l'alias doit laisser passer.

### 22. Un reçu vocal refusé, **coque ouverte** — ⚠️ couverture perdue

**Faire.** Lancez une calibration et **laissez la coque ouverte**. Pendant
qu'elle est à l'écran, envoyez une commande vocale qui sera **refusée** (par
exemple relancer une calibration, ou une commande que l'état courant interdit).

**Attendu.** Le reçu refusé est **dessiné dans la coque**, avec sa cause.

**Serait faux.** Rien ne s'affiche, ou le refus part dans un toast derrière la
coque.

> **Pourquoi c'est ici.** La Slice 07B a perdu cette assertion et l'a nommée
> plutôt que de la cacher. L'ancien test ouvrait la coque par
> `BAREHANDS.tutorial()`, qui n'exigeait pas de caméra ; la seule porte
> restante est la calibration, qui exige `active` — état que `node` ne peut pas
> atteindre. **Le chemin ordinaire (panneau fermé, toast) reste couvert par les
> tests ; celui-ci ne l'est plus du tout.**

### 23. Le tutoriel a disparu de partout — `HV-BH-CAL-07` · `HV-BH-UI-08`

**Faire.** Parcourez l'interface normale : contrôle, palette, menu du clic
droit, les trois sections des Réglages.

**Attendu.** **Aucune** trace d'un parcours de tutoriel. Une seule surface
guidée : la calibration.

**Serait faux.** Une entrée Tutoriel où que ce soit. Une case « Tutoriel déjà
vu » dans les réglages — elle a été retirée à la Slice 07B, une case qui
interroge sur l'achèvement d'un parcours inexistant n'est pas un réglage.

---

## F. Migration, vie privée, et la porte finale

### 24. Une installation antérieure — `HV-BH-UI-08`

**Faire.** Si vous avez un `control-center-settings.json` **d'avant cette
tâche** (ou une sauvegarde), remettez-le en place et rechargez.

**Attendu.** Tout se charge. Vos réglages sont là. **« Calibrer… » n'est pas
grisé** alors que vous n'avez jamais rien décoché.

**Serait faux.** Une entrée silencieusement grisée — le défaut exact que la
migration doit empêcher, et qu'un test de schéma ne voit pas. (Couvert côté
machine par `test_an_older_install_still_loads_and_drives_the_refined_ui`, mais
jamais sur un vrai fichier à vous.)

### 25. Hors ligne, et la caméra rendue — `HV-BH-UI-08`

**Faire.** Ouvrez l'onglet **Réseau** des outils du navigateur, filtrez sur les
requêtes externes, puis faites une session Bare Hands complète. Ensuite
choisissez **Éteint** et regardez le **témoin lumineux de la webcam**.

**Attendu.** **Aucune** requête vers un domaine externe. Le témoin de la webcam
**s'éteint** à l'extinction.

**Serait faux.** La moindre requête sortante — MediaPipe est vendorisé et sert
depuis une liste blanche fermée. Un témoin de webcam qui reste allumé après
« Éteint » : seule l'extinction libère la caméra, et si elle ne la libère pas,
la promesse de confidentialité est rompue quoi que dise la documentation.

### 26. La porte finale — `HV-BH-UI-08`

**Faire.** Prenez du recul et répondez à une seule question : **est-ce que Bare
Hands ressemble à un mode Jarvis de premier rang ?**

**Attendu.** Oui — la calibration est lisible et spatialement claire, et
**aucune régression** n'est visible sur les interactions existantes.

**Serait faux.** Ça ressemble encore à un panneau de réglages expérimental avec
des boutons ajoutés autour.

---

## Ce que cette liste **ne** couvre **pas**

- **Les trois clusters** de dette héritée (`test_display_mcp`,
  `test_scene_transport_client`, `test_scene_contracts` — 23 échecs) **et deux
  de plus trouvés par la Slice 08** (`test_scene_artifacts` 2,
  `test_scene_user_lifecycle` 5, `test_scene_service` 2). Tous vérifiés
  présents sur `origin/main` @ `a949f40` avant la première ligne de cette
  tâche. **Total réel : 32.** Aucun n'est réparé ici — ce serait mélanger une
  correction étrangère au diff de cette tâche.
- Le comportement multi-mains au-delà de deux mains.
- La divergence délibérée mais **non arbitrée** de
  `control_center_scene_page.js` : une souris glisse toute la sélection, une
  main nue ne porte que l'objet nommé. En attente d'arbitrage humain, hors
  périmètre.
