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

Chaque chiffre a été **re-mesuré par l'agent 0** après le rendu de la slice, en deux lots au premier plan, jamais repris d'un rapport.

### Dette héritée de `main`, à ne pas imputer à cette tâche

`tests/unit/test_display_mcp.py` (4 échecs) et `tests/unit/test_scene_transport_client.py` (4 échecs) échouent **à l'identique à `a949f40`**, vérifié dans un worktree détaché le 2026-09-20. Huit échecs, mêmes noms, avant toute écriture de cette tâche. Ils ne sont pas réparés ici.

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

### Autre report vers la Slice 08

Le registre de `docs/barehands-contracts.md` (dernière ligne) annonce encore « Reste à venir : les diagnostics enregistrés (Slice 10) » alors que la Slice 10 est livrée. Déjà noté en READINESS §6.

### Ce que la machine ne peut pas valider ici

`node` ne peut pas pousser le vrai moteur au-delà de `starting` : `createLandmarker` importe le bundle MediaPipe et il n'y a pas de caméra, donc `enable()` finit toujours en `camera_unsupported`. **Les présentations `sleep` et `active` n'ont jamais été rendues contre un contrôleur vivant.** Tout ce qui est visuel dans cette tâche se juge à l'œil, devant une vraie webcam.

Aperçus autonomes laissés par les agents, ouvrables sans Jarvis ni caméra ni serveur, dans le scratchpad de session :

- `palette-preview.html` — les cinq présentations du cycle de vie, les trois états d'outil ;
- `s04-preview/preview.html` — les sept poses de main, l'échelle d'écartement mesurée, les deux cartes en vrai.
