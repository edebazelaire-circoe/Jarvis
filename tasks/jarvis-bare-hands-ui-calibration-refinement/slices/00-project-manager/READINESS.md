# Slice 00 — Registre de readiness

État : **READY**

Date : 2026-09-20. Base : `origin/main` @ `a949f40c16c4a61fc563e7d7cdf1c32da913c207` — exactement le SHA revu par le handoff (`task.json.source_snapshot.sha`). Branche : `task/jarvis-bare-hands-ui-calibration-refinement`.

---

## 1. Ce que le handoff déclare

Raffinement d'UI d'une fonctionnalité déjà livrée. Bare Hands V1 est fusionné dans `main` (`git rev-list --left-right --count origin/main...task/jarvis-bare-hands-v1` → `4 0` : la branche de tâche n'a aucun commit que `main` n'ait pas). Les sémantiques d'interaction ne sont pas rouvertes ; seules l'architecture d'accès et l'UX de calibration changent.

## 2. Audit aveugle — ce que le dépôt dit réellement

Conduit avant lecture des conclusions du handoff, comme l'exige la Slice 00.

| Sujet | Réalité au SHA revu |
| --- | --- |
| Page | `jarvis/runtime/control_center.html`, 3608 lignes, **tout est inline** — style 7–710, markup 712–830, script 831–3606. Aucun fichier `.css` dans le runtime. |
| Jeton « bleu Jarvis » | `--accent:#6ee7ff` (`control_center.html:8`), résolu par les modules via `var(--omega-accent,var(--accent,#6ee7ff))`. |
| Boutons d'action principaux | `<nav class="dock">` — `control_center.html:722-729`, CSS `:40-42`. 52×52, radius 10, **étiquettes texte de trois lettres, aucune icône**. |
| Cycle de vie | `LIFECYCLE={OFF:'off',SLEEP:'sleep',ACTIVE:'active',ERROR:'error'}` — `control_center_barehands_contracts.js:110`. `ERROR` est un 4ᵉ état réel, pas un mode sélectionnable. |
| Surface publique | `window.JarvisBarehands`, gelée, `version:2` — `control_center_barehands.js:5720-5860`. |
| Outils | `TOOL={POINTER:'pointer',PAN:'pan',SELECT:'select'}` — `contracts.js:875`. Libellés `Pointeur` / `Main` / `Sélection`. **Aucune icône n'existe.** |
| Calibration | `control_center_barehands_calibration.js`, coquille `createFlowOverlay` (`:369`), carte centrée `.jf-step` `max-width:560px`, 7 étapes, `stageTimeoutMs:20000`, `watchdogMs:500`. |
| Tutoriel | `control_center_barehands_tutorial.js`, 10 étapes, **réutilise la coquille de calibration telle quelle**. |
| Canal de commandes | 5 commandes `activate / deactivate / calibrate / tutorial / exit_overlay`, miroirées en 3 endroits (JS, `jarvis/domain/barehands_command.py:32`, MCP `jarvis/runtime/barehands_mcp.py`) avec **assertion de parité au chargement** (`barehands_mcp.py:488-489`). |
| Géométrie de cadre | `control_center_scene_interact.js` (`manipulateBox`, `rebaseManipulation`, `clampBox`, `resizeBySides`) et la couture vivante `JarvisScene.frames.{begin,preview,commit,cancel,viewport}` — `control_center_scene_page.js:2087-2129`. |
| Tests | 17 fichiers `tests/unit/test_barehands_*.py`. **Pas de runner JS** : ce sont des modules pytest qui appellent `node` en sous-processus et `require()` les vrais modules. |

### Baseline mesurée

`430 tests collected`, **430 passés** (192 + 238 en deux lots), sur ces 17 fichiers, au SHA `a949f40` :

`test_barehands_calibration_js` · `clean_room` · `command_channel` · `commands_js` · `contracts_js` · `gestures_js` · `interaction_js` · `lifecycle_js` · `pointer_js` · `profile` · `recorder_js` · `target_js` · `test_mode` · `tools_settings_js` · `trace` · `tracking_js` · `tutorial_js`

Chiffre à re-mesurer, jamais à reporter : les slices ajoutent des fichiers de test.

## 3. Divergences trouvées entre le handoff et le code

### D1 — « près de la zone d'état en haut à gauche » ne désigne aucun bouton existant

Le handoff demande le bouton Bare Hands « près de la zone d'état en haut à gauche, dans le même langage visuel que les autres boutons d'action principaux ». Ces deux exigences pointent vers deux endroits différents : les boutons d'action principaux sont le dock, **à droite, centré verticalement** ; le haut-gauche est `.topbar` (`control_center.html:27,716`), en `pointer-events:none`, qui ne porte que la marque et l'état voix/agents.

**Tranché par l'Humain le 2026-09-20 : contrôle autonome en haut à gauche.** Le bouton n'entre pas dans `.dock`. Il devient un contrôle de premier plan distinct, groupé avec la palette d'outils qui est elle aussi imposée à gauche — la main et ses outils voisinent, le dock reste le dock. Conséquence technique : le contrôle doit rétablir `pointer-events:auto` localement, puisque son conteneur les coupe.

### D2 — le dock n'a jamais porté d'icône

Six boutons, six étiquettes de trois lettres. Le handoff exige une icône de main.

**Tranché par l'Humain le 2026-09-20 : icône de main en trait, SVG.** Même vocabulaire graphique que la main schématique de la calibration (décision 20 du journal) : une seule grammaire visuelle pour toute la fonctionnalité. D1 rend la question sans friction — le contrôle n'étant pas un bouton de dock, il n'a pas à en respecter la convention typographique.

### D3 — aucune souscription au cycle de vie n'existe

C'est la découverte la plus lourde, et le handoff ne l'anticipe pas. Le panneau Expérimental n'est repeint que par des appels impératifs à `refreshPanel()` depuis l'intérieur du module, plus `watchStartingClock()` qui ne sonde que pendant `starting`. Les changements venus de la voix/MCP, du réveil en C, ou de l'inactivité de 30 s atteignent le panneau **uniquement parce que le panneau est dans le même module**.

Un bouton HUD vivant hors du modal de réglages n'a donc rien à quoi se lier. La décision 7 du journal — « le bouton doit refléter les changements de toutes les sources » — est du travail **neuf**, pas du recâblage.

**Réparation de planification :** la Slice 01 doit ouvrir une couture de diffusion du cycle de vie, modelée sur le patron multi-consommateurs qui existe déjà juste à côté : `openMeasureSeam(name,sink)` / `closeMeasureSeam(name)` / `measureSeamNames()` (`control_center_barehands.js:4366-4390`). Point d'accroche amont : `controllerDeps.onStatus` (`:4110`). Cette couture est un prérequis des critères d'acceptation de la Slice 01, pas un détail d'implémentation.

### D4 — la calibration n'a aujourd'hui aucune dépendance à la scène

L'étape 6 doit manipuler un vrai cadre, donc appeler `JarvisScene.frames.*`. Or `frames.begin()` **et** `viewport()` renvoient `null` quand la scène est éteinte. La calibration, elle, ne dépend d'aucune scène à ce jour.

**Décision :** l'étape 6 ne doit pas inventer un défaut plausible. Conformément à la règle fondatrice du contrat (« un refus codé plutôt qu'un défaut plausible », `docs/barehands-contracts.md:20`), scène absente ⇒ étape marquée `skipped` avec une raison nommée, ajoutée à `STAGE_REASON` (`contracts.js:1165-1174`). C'est une modification de contrat assumée, à porter par la Slice 07 et à documenter.

## 4. Points bloquants de planification, résolus

**`task_type` — levée de la porte.** Le vocabulaire « Workspace Task Type » reste introuvable : `grep -ril "task_type\|task type"` sur `docs/` et la racine ne renvoie rien hors dossiers de handoff. C'est la cinquième tâche dans ce cas ; l'Humain a levé la porte pour les quatre précédentes (settings, observability, category2 test lab, bare hands). Aucun type n'est inventé ; les neuf `metadata.json` gardent `task_type: null` et ce paragraphe tient lieu de résolution.

**Migration du tutoriel — alias déprécié.** `tutorial` reste dans le vocabulaire et route vers la calibration. Raison : le nom est miroité en trois endroits sous assertion de parité au chargement (`barehands_mcp.py:488-489`, `domain/barehands_command.py:32`, `commands.js:76-83`) ; le supprimer est une rupture de contrat coordonnée sur trois fichiers plus les tests, alors que l'alias préserve le contrat **et** satisfait l'exigence produit — une seule surface utilisateur. L'entrée Tutoriel des réglages et le module `control_center_barehands_tutorial.js` cessent d'être un parcours concurrent.

## 5. Contrainte d'ordonnancement

`control_center_barehands.js` fait **5891 lignes / 349 Ko** et contient à la fois le moteur pur et la totalité du HTML du panneau de réglages (région ~4746–5720). Les slices 01, 02, 03 et 04 écrivent toutes dans cette même région.

**Un seul implémenteur à la fois dans cette région.** Aucune de ces slices ne part en parallèle d'une autre, même quand le graphe de dépendances l'autoriserait. Le graphe est de toute façon presque linéaire : `00 → 01 → 02`, puis `02 → 04` et `02 → 05 → 06` sont les seules branches, et elles ne se rejoignent qu'en 07.

## 6. Dette héritée, hors périmètre mais à ne pas perdre

- Le registre de `docs/barehands-contracts.md` (dernière ligne, 2800) annonce encore « Reste à venir : les diagnostics enregistrés (Slice 10) » alors que la Slice 10 est livrée (module recorder, trace/rejeu, `python -m jarvis barehands-replay`, § 14 du même document). Correction à replier dans la Slice 08.
- Quatre Issues ouvertes sous `tasks/jarvis-bare-hands-v1/Issues/` restent celles de la tâche précédente.
- La divergence délibérée mais non arbitrée de `control_center_scene_page.js:2069-2078` — une souris glisse toute la sélection, une main nue ne porte que l'objet nommé — reste en attente d'arbitrage humain. Hors périmètre ici.

## 7. Porte

Readiness **READY**. Les deux questions de présentation sont tranchées, les deux bloqueurs de planification sont résolus, les quatre divergences sont enregistrées avec leur réparation. Vérification de fraîcheur exigée juste avant chaque dispatch de slice.
