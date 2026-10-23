# Recette humaine — réorganisation des Réglages

Tâche `jarvis-settings-ui-reorganization`, rédigée par la QA de la Slice 10 (2026-10-23). Ces vérifications sont les
seules qui restent à faire une fois la validation machine épuisée : elles portent sur ce qu'un test ne sait pas juger
(lisibilité, évidence d'un chemin, impression d'ensemble). Chaque check dit quoi faire, ce que vous devez voir et où
regarder. Cochez la case quand le résultat est celui attendu ; sinon notez ce que vous avez vu à côté.

## Avant de commencer

- [ ] **Redémarrage requis après le merge.** La tâche ne change aucun schéma : aucune base (`jarvis.sqlite3`,
  `scene.sqlite3`) n'est migrée, aucun fichier de réglages n'est réécrit. En revanche la page du Control Center et
  plusieurs modules Python servis par Core et le Control Center ont changé (`control_center.py`, `app.py`,
  `memory_settings.py`, `voice_settings_schema.py`, `shortcuts.py`, `barehands_commands.py`, `settings_mcp.py`,
  `presentation_runtime.py`, `model_catalog.py`, `memory_relay.py`, `credentials.py`) : redémarrez JARVIS (Core et
  Control Center) vous-même une fois la branche fusionnée, puis rechargez la page. Aucun agent ne le fera à votre place.
- Ouvrez les Réglages par le bouton « Plus d'outils » (⋯) › Réglages, ou par la touche `s` quand le focus n'est pas
  dans un champ. Échap ou « Fermer » les referme.

## Checks HV-SETTINGS

### HV-SETTINGS-001 — Six catégories lisibles, plus de « modale HUD » (Slice 02)

1. Sur votre écran habituel, navigateur à 100 %, ouvrez les Réglages.
2. Recommencez à 125 % de zoom (Ctrl + `+` jusqu'à 125 %), puis revenez à 100 % (Ctrl + `0`).

Résultat attendu :
- [ ] Le rail de gauche montre exactement six catégories, dans cet ordre : Voix & audio, Agents & modèles, Mémoire &
  connaissances, Interface & interactions, Connexions, Avancé & diagnostic ; chacune a son pictogramme, sa teinte et
  une description courte non tronquée.
- [ ] La page occupe toute la fenêtre (plus de grande boîte encadrée au milieu) ; aucune barre de défilement
  horizontale, à 100 % comme à 125 %.
- [ ] Les réglages ordinaires se lisent comme un formulaire (texte courant, champs alignés) et non comme un écran de
  débogage : le style technique (monospace) n'apparaît que dans Avancé & diagnostic.

Où regarder : le rail à gauche, la tête de catégorie en haut de la colonne principale. Référence machine :
`evidence/s10/1366x768-100-*.png`, `1366x768-125-*.png`, `1920x1080-100-*.png`.

### HV-SETTINGS-002 — Voix & audio sans passer par Avancé (Slice 03)

1. Ouvrez Voix & audio. Sans ouvrir Avancé & diagnostic, cherchez : le micro et le haut-parleur, la voix de JARVIS,
   la façon dont les tours de parole se terminent et s'interrompent, le mot d'éveil.

Résultat attendu :
- [ ] Micro et haut-parleur sont dans « Micro & son » (périphériques en premier) ; la voix et la transcription dans
  « Voix & transcription » ; fin de tour et interruptions dans « Tours & interruptions » ; le mot d'éveil dans
  « Mot d'éveil ».
- [ ] Le chemin vers chacun vous paraît évident à partir du nom de l'entrée.
- [ ] La page n'est pas dominée par l'architecture vocale, la VAD ou les diagnostics : ceux-ci sont dans Avancé &
  diagnostic › Architecture & compatibilité et › Diagnostics.

Où regarder : la rangée d'entrées sous la tête « Voix & audio ».

### HV-SETTINGS-003 — Agents & modèles depuis une seule catégorie (Slice 04)

1. Ouvrez Agents & modèles. Trouvez l'agent principal et son modèle, le comportement des réponses (verbosité,
   politesse), puis les rôles des sous-agents.

Résultat attendu :
- [ ] Les trois se trouvent dans cette seule catégorie : « Agent principal », « Comportement », « Rôles des
  sous-agents » (et « Modèles des sous-agents » pour le mode Auto / Dupliqué et le catalogue).
- [ ] La commande du CLI, son chemin résolu, la permission et le détail du routage (profils, ordre des candidats)
  n'encombrent pas cette catégorie : ils sont dans Avancé & diagnostic › Runtime & CLI, atteignables par le lien
  « Régler la commande ».

Où regarder : les quatre entrées d'Agents & modèles ; le lien en bas d'« Agent principal ».

### HV-SETTINGS-004 — Mémoire & connaissances compréhensible, Memory Center joignable (Slice 05)

1. Ouvrez Mémoire & connaissances. Parcourez Rappel, Recherche sémantique, Consolidation, Sources de connaissances.
2. Ouvrez « Centre mémoire » puis « Ouvrir le Memory Center ».
3. Dans le Memory Center, onglet « Santé des index », cliquez « Ouvrir les réglages mémoire ».

Résultat attendu :
- [ ] Chaque section se comprend sans lire de diagnostic (une phrase dit à quoi elle sert, chaque champ a son libellé
  et son aide).
- [ ] « Ouvrir le Memory Center » ferme les Réglages et ouvre le Memory Center.
- [ ] Le bouton du Memory Center vous ramène dans Réglages › Mémoire & connaissances › Rappel.

Où regarder : le texte de tête de chaque section ; le titre « Memory Center » de la vue Sessions & Boards.

### HV-SETTINGS-005 — Interface & interactions : une seule place pour chaque réglage (Slice 06)

1. Ouvrez Interface & interactions › Thème & scène visuelle : choisissez Cosmos, puis revenez à Circuit imprimé.
2. Ouvrez Raccourcis : changez la touche « Réveiller / envoyer / interrompre » (F9 par défaut) pour une autre touche,
   vérifiez qu'elle agit, puis remettez F9.
3. Ouvrez Bare Hands : modifiez une préférence (par exemple « Aperçu de la cible »), puis « Réinitialiser les
   réglages » et confirmez.

Résultat attendu :
- [ ] Le thème change tout de suite, sans enregistrer, et reste après un rechargement de la page.
- [ ] La touche ne se règle qu'ici (Voix & audio › Tours & interruptions la montre en lecture seule avec un lien
  « Modifier dans … › Raccourcis ») ; la nouvelle touche agit comme l'ancienne ; F9 revient.
- [ ] La préférence Bare Hands n'existe qu'ici et s'applique comme avant ; la réinitialisation n'allume pas Bare Hands.

Où regarder : la carte de thème sélectionnée, la touche affichée dans Raccourcis, l'état Bare Hands du dock.

### HV-SETTINGS-006 — Connexions : état et clé active sans jamais voir de valeur (Slice 07)

1. Ouvrez Connexions › Fournisseurs. Lisez chaque carte.
2. (Facultatif) Ajoutez une clé de test sous un nom explicite, rendez-la active, puis supprimez-la. N'utilisez pas une
   clé dont vous avez besoin.
3. Au clavier seul, faites défiler les cartes avec Tab jusqu'au bout, puis encore un Tab.

Résultat attendu :
- [ ] Chaque carte dit si le fournisseur est configuré (« Clé enregistrée », « Variable d'environnement » ou « Non
  configuré ») et laquelle des clés est active (badge « Active »).
- [ ] Aucune valeur de clé n'apparaît jamais : seuls les quatre derniers caractères, même juste après l'ajout.
- [ ] Après le dernier « Ajouter une clé », Tab revient en haut des Réglages (rail) et non sur la page derrière ;
  Maj+Tab depuis le haut revient sur ce dernier « Ajouter une clé ». (Repris après la QA de livraison : machine
  vérifiée sur les 25 sections, `evidence/s10-rework/b1-keyboard.json`.)

Où regarder : les badges en tête de chaque carte ; le contour de focus après le dernier Tab.

### HV-SETTINGS-007 — Avancé & diagnostic organisé en groupes (Slice 08)

1. Ouvrez Avancé & diagnostic.

Résultat attendu :
- [ ] Un avis « Outils d'opérateur » dit que les réglages du quotidien sont ailleurs.
- [ ] Les entrées sont rangées sous cinq intitulés de groupe : Architecture & compatibilité, Prompts & instructions,
  Runtime & CLI, Diagnostics, Labs & outils de test.
- [ ] L'atelier des prompts est dans « Prompts » ; la porte de test de la scène dans Labs › « Scène constellation ».
- [ ] À 1366×768, Labs passe en seconde ligne sans filet vertical au début de la ligne.

Où regarder : la liste des entrées sous la tête de catégorie. Référence machine :
`evidence/s10/1366x768-125-6-advanced_diagnostics.png`.

### HV-SETTINGS-008 — La roue Jarvis ouvre les bonnes catégories (Slice 09)

1. Ouvrez la roue (ancre à gauche de l'écran), secteur « Paramètres ».
2. Choisissez chaque ligne l'une après l'autre (rouvrez la roue entre deux).
3. Dans le secteur « JARVIS », choisissez « Réglages de la voix ».
4. Recommencez une fois au clavier seul : Tab jusqu'à l'ancre, flèche droite, flèches jusqu'à « Paramètres », flèche
   droite, flèches, Entrée.

Résultat attendu :
- [ ] « Paramètres » liste les six catégories, dans l'ordre du rail.
- [ ] Chaque ligne ouvre les Réglages sur sa catégorie ; « Réglages de la voix » ouvre Voix & audio.
- [ ] Au clavier, le focus arrive sur la catégorie ouverte dans le rail et y reste ; Échap rend le focus à l'ancre de
  la roue.

Où regarder : la catégorie surlignée dans le rail ; le contour de focus. Référence machine :
`evidence/s10/k01-roue-clavier-connexions.png`.

## Décisions produit à trancher

Aucune de ces décisions n'a été prise par un agent : chacune serait une nouvelle fonctionnalité ou un changement de
comportement. Indiquez pour chacune « oui / non / plus tard ».

- [ ] **Prévenir avant de perdre un brouillon mémoire.** Aujourd'hui, fermer les Réglages avec des changements
  mémoire non enregistrés les jette sans avertissement (comportement d'avant la tâche). Faut-il demander une
  confirmation à la fermeture ?
- [ ] **Garder le texte en cours des autres couches de prompts.** Dans Avancé › Prompts, enregistrer une couche
  redessine l'atelier et fait perdre le texte tapé mais non enregistré dans une autre couche (comportement d'avant la
  tâche). Faut-il le conserver ?
- [ ] **Renommer une clé de fournisseur.** Connexions permet d'ajouter, activer, remplacer la valeur et supprimer une
  clé, pas de la renommer (le magasin le permettrait). Faut-il l'offrir ?
- [ ] **Verdicts Solo Owner et annulation d'écho en clair, commande de réparation du vérificateur.** Leur rendu
  lisible (« Solo Owner appliqué », « Mode dégradé », commande à lancer pour réparer le vérificateur de locuteur)
  n'était déjà plus affiché sur `main` avant cette tâche ; la passe de finitions a retiré ce code mort.
  Avancé › Diagnostics montre ces états en JSON. Faut-il les remettre en phrases ?

## Ce que la machine a déjà vérifié (pour mémoire)

Balayage complet du dépôt, suites des Réglages et suites navigateur vertes hors échecs déjà présents sur `main` ;
bac à sable réel, 25 sections à 1366×768, 1440×900, 1920×1080, à 100 % et 125 % sans débordement ; clavier seul (rail,
entrées, contenu, pied, fermeture, roue, `s`, Échap sous une confirmation) ; régions vivantes ; mouvement réduit ;
couleurs forcées ; aucun minuteur, écoute globale ni requête qui fuit après trois tournées complètes. Détail et
findings : `LOG.md`, entrée Slice 10 ; preuves : `evidence/s10/`. Reprise après la QA de livraison (piège de Tab,
envois du Memory Center, profil de routage éteint lisible, catalogue défilant au clavier) : `LOG.md`, « Rework après
QA de livraison » ; preuves : `evidence/s10-rework/`.
