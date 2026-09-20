# Execution log

Reserved for implementation agents. Record durable discoveries, decisions, migrations, QA evidence, and handoff notes during execution. Do not treat planning text as evidence of completed work.

---

## Tenu par l'agent 0 (orchestrateur)

Base : `origin/main` @ `a949f40` — le SHA exact revu par le handoff. Branche `task/jarvis-bare-hands-ui-calibration-refinement`.

### Commits par slice

| Slice | Commits | Tests après |
| --- | --- | --- |
| S0 — miroir Drive + readiness | `edf1da3` | 430 / 17 fichiers |
| 01 — contrôle HUD + couture de cycle de vie | `2fee826`, `e11c924` | 444 / 18 |
| 02 — actions rapides au clic droit + Settings nettoyés | `a95a469` | 451 / 18 |
| 03 — palette d'outils + couture d'outils | `b6e102b` | 465 / 19 |
| 04 — carte d'aide + carte de diagnostic + `hand_art` | `005bed2` | 486 / 21 |
| 05 — coquille plein cadre, cinq régions | `57409d8` | 494 / 21 |
| 06 — phases INTRO/ARMED/RUNNING/RESULT, étapes 1–5 | `c5a598d` | 501 / 21 |
| 07A — pratique de fenêtre réelle, D4 | `a14b450` | 513 / 21 |
| 07 — correction d'affichage par l'agent 0 | `1912d91` | 514 / 21 |
| 07B — tutoriel retiré, commande aliasée | `fa74bdd` | 502 / 21 |

Chaque chiffre a été **re-mesuré par l'agent 0** après le rendu de la slice, en deux lots au premier plan, jamais repris d'un rapport.

### Dette héritée de `main`, à ne pas imputer à cette tâche

Trois foyers, **23 échecs**, tous vérifiés à l'identique à `a949f40` dans un worktree détaché — donc présents sur `origin/main` avant la première écriture de cette tâche. Aucun n'est réparé ici.

| Fichier | Échecs | Vérifié |
| --- | --- | --- |
| `tests/unit/test_display_mcp.py` | 4 | 2026-09-20, worktree détaché |
| `tests/unit/test_scene_transport_client.py` | 4 | 2026-09-20, worktree détaché |
| `tests/unit/test_scene_contracts.py` | 15 | 2026-09-20, worktree détaché |

Le troisième foyer a été repéré par l'agent de la Slice 07A, qui l'a constaté en remisant son travail ; l'agent 0 l'a re-vérifié à `a949f40` plutôt qu'à la tête de branche. Il ne figurait dans aucun inventaire antérieur. Échantillon : `test_revision_is_strictly_monotonic_and_patches_are_exact_deltas` attend `APPLIED` et reçoit `REJECTED_AUTHORITY` — c'est le domaine Python de la scène, hors du périmètre Bare Hands.

### Décisions d'orchestration

**Deux questions de présentation tranchées par l'Humain (2026-09-20).** Le handoff demandait le bouton « en haut à gauche, dans le même langage visuel que les autres boutons d'action » — deux exigences qui pointaient deux endroits différents, le dock étant à droite. L'Humain a choisi un **contrôle autonome en haut à gauche**, hors du dock, et une **icône de main en trait SVG** là où le dock n'a jamais porté que des étiquettes de trois lettres. Détail et conséquences : `slices/00-project-manager/READINESS.md` §3.

**Le vocabulaire graphique des mains est construit une seule fois.** Le handoff laissait la Slice 04 libre de faire des illustrations « réutilisables par la calibration *si c'est approprié* ». L'agent 0 a retiré le *si* : la Slice 06 a besoin de cinq poses, et une Slice 04 qui ne pense qu'à l'aide aurait garanti un second jeu de mains divergent. D'où `control_center_barehands_hand_art.js`, inséré **après les contrats et avant la calibration** précisément pour que la calibration puisse le lire.

**Deux coutures distinctes, pas une.** La Slice 01 a ouvert `openLifecycleSeam`, la Slice 03 `openToolSeam`. Elles n'ont pas été fondues : le contrat range l'outil sous les réglages (§8), le canal de commandes refuse de router `tool` à côté des transitions, et fondre les deux ferait passer « l'outil a changé » pour un événement de cycle de vie aux yeux du prochain lecteur. Deux faits, deux propriétaires.

**Le tutoriel devient un alias déprécié, pas une suppression.** Son nom est miroité sous assertion de parité au chargement en trois endroits (`commands.js`, `domain/barehands_command.py`, `barehands_mcp.py`). L'alias préserve le contrat et satisfait quand même l'exigence produit : une seule surface visible. Porté par la Slice 07.

**Un seul implémenteur à la fois.** `control_center_barehands.js` fait ~6000 lignes et les slices 01 à 04 écrivent toutes dans la même région. Aucune dispatche parallèle, même quand le graphe de dépendances l'autoriserait.

### Corrections renvoyées à leur auteur

**Slice 01.** Choisir « Éteint » depuis `ERROR` laissait le bouton rouge. L'agent croyait protéger le toast « Caméra refusée » ; cette protection vit en réalité dans `controller.disable()` (`wasOn=isEngagedState(state)`, qui depuis `ERROR` émet `off` et non `disabled`, et `off` n'est pas notifié). Le garde extérieur ne protégeait rien et garait le contrôleur en panne après une demande explicite d'extinction. Le toast est le journal de l'événement, le bouton est l'état courant : deux métiers. Corrigé en `e11c924`, avec l'écriture inutile du réglage supprimée au passage.

### Vérités retirées de l'écran, à replacer — pour la Slice 08

La Slice 04 a supprimé le bloc « Gestes » des réglages. Deux de ses affirmations étaient **fausses** et sont mortes à juste titre : le pincement pouce-majeur y était rangé parmi les gestes « reconnus, pas encore agissants » alors qu'il publie `INTERACTION.CONTEXT` et déclenche un vrai `contextmenu` ; et « pas de glisser-déposer ni de défilement » alors que `DRAG_START`/`DRAG_MOVE`/`DRAG_END`/`SCROLL` sont tous implémentés.

Mais **quatre phrases vraies sont parties avec**, et l'utilisateur rencontrera au moins deux d'entre elles :

- un `<select>` ne s'ouvre pas sur un clic synthétique ;
- l'iframe ai-visualizer ne reçoit pas les clics ;
- le comportement du jeton de pointeur ;
- la main pointillée / non fiable.

Elles n'avaient pas leur place dans une carte de gestes — l'agent a eu raison de ne pas rouvrir le mur de texte. **La Slice 08 doit leur trouver une place** (une note compacte dans les réglages est le candidat naturel) ou constater explicitement qu'on assume de ne plus les dire.

### Autres reports vers la Slice 08

- Le registre de `docs/barehands-contracts.md` (dernière ligne) annonce encore « Reste à venir : les diagnostics enregistrés (Slice 10) » alors que la Slice 10 est livrée. Déjà noté en READINESS §6.
- **`barehands_calibration_disabled` sert deux causes distinctes** — le réglage décoché, et Bare Hands éteint. Un appelant ne peut pas les distinguer à partir du code seul, uniquement de la phrase. Repéré par l'agent de la 07B, hors de son périmètre. Un code par cause, ou une justification explicite de la fusion.

### Le compte de tests baisse en 07B, et c'est normal

514 → **502**. Le tutoriel a été **supprimé**, pas réduit à une coquille : un `createTutorial` encore constructible resterait une seconde machine à états vivante, ce que l'architecture interdit deux fois. Ses 26 tests décrivaient le module et meurent avec lui ; ceux qui décrivaient le **système** ont été relogés, pas jetés. Réconciliation par fichier, vérifiée : `514 − 26 + 11 + 2 + 2 − 1 = 502`.

**Une couverture est réellement perdue**, et elle est nommée plutôt que cachée : l'ancien test de reçu vocal ouvrait la coque par `BAREHANDS.tutorial()`, qui n'exigeait pas de caméra. La seule porte restante est la calibration, qui exige `active` — état que node ne peut pas atteindre. L'assertion « un reçu refusé est dessiné dans la coque » passe donc à la liste des vérifications à l'œil. Le chemin ordinaire (panneau fermé, toast) reste couvert.

### Correction d'un chiffre de l'audit initial

L'audit aveugle de la Slice 00 annonçait `test_barehands_command_channel.py` à **7 tests**. Il en collecte **32**. L'erreur n'a rien cassé, mais elle rappelle qu'un chiffre de test se re-mesure et ne se recopie pas — y compris depuis un audit qu'on a soi-même commandé.

### Ce que la machine ne peut pas valider ici

`node` ne peut pas pousser le vrai moteur au-delà de `starting` : `createLandmarker` importe le bundle MediaPipe et il n'y a pas de caméra, donc `enable()` finit toujours en `camera_unsupported`. **Les présentations `sleep` et `active` n'ont jamais été rendues contre un contrôleur vivant.** Tout ce qui est visuel dans cette tâche se juge à l'œil, devant une vraie webcam.

Aperçus autonomes laissés par les agents, ouvrables sans Jarvis ni caméra ni serveur, dans le scratchpad de session :

- `palette-preview.html` — les cinq présentations du cycle de vie, les trois états d'outil ;
- `s04-preview/preview.html` — les sept poses de main, l'échelle d'écartement mesurée, les deux cartes en vrai.
