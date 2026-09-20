# Registre de clôture — `jarvis-bare-hands-ui-calibration-refinement`

État : **prêt pour validation humaine**. Rien n'est fusionné, rien n'est archivé, le dossier Drive reste dans `current`.

Branche `task/jarvis-bare-hands-ui-calibration-refinement`, 14 commits au-dessus de `a949f40` — le SHA exact que le handoff avait revu. `origin/main` n'a pas bougé pendant la tâche (vérifié avant chaque dispatch et à la clôture : `0 / 14`).

---

## 1. Slices — toutes livrées

| Slice | Objet | Commits |
| --- | --- | --- |
| 00 | Porte de readiness, audit aveugle | `edf1da3` |
| 01 | Contrôle de cycle de vie en HUD + couture de diffusion | `2fee826`, `e11c924` |
| 02 | Actions rapides au clic droit, Settings redevenus des réglages | `a95a469` |
| 03 | Palette d'outils fixe à gauche + couture d'outils | `b6e102b` |
| 04 | Carte d'aide, carte de diagnostic, vocabulaire `hand_art` | `005bed2`, `ff325ee` |
| 05 | Coquille de calibration plein cadre, cinq régions | `57409d8` |
| 06 | Phases `INTRO/ARMED/RUNNING/RESULT`, étapes 1–5 | `c5a598d` |
| 07A | Pratique de fenêtre réelle, refus D4 | `a14b450`, `1912d91` |
| 07B | Tutoriel supprimé, commande aliasée | `fa74bdd`, `165aaa8` |
| 08 | Intégration, migrations, docs, checklist humaine | `0bd22b3` |

**Aucune slice incomplète.** La Slice 07 a été coupée en deux par l'agent 0 : neuf fichiers et deux métiers aux profils de risque différents, dont un seul exigeait une analyse de traces d'agent.

## 2. Ce que chaque exigence verrouillée est devenue

| Exigence du handoff | Où elle vit |
| --- | --- |
| Bouton main carré, premier plan, hors des réglages | `control_center_barehands_hud.js`, 64 px, haut-gauche, icône en trait SVG |
| OFF gris / SLEEP bleu / ACTIVE bleu vif + halo, jamais vert | Échelle de tons écrite **une fois**, portée par `data-bh-tone` |
| Clic = sélecteur visuel à trois états, pas une liste texte | Trois pastilles, même dessin que le bouton |
| Le bouton reflète tout changement, quelle qu'en soit la source | `openLifecycleSeam` — **travail neuf**, aucune souscription n'existait |
| Clic droit = Réglages / Calibration / Aide / Diagnostic | Quatre entrées, via le `showMenu` existant de la page |
| Palette verticale fixe, `pointer`/`pan`/`select` seulement | `openToolSeam`, rendue depuis `describeTools()` |
| Settings = configuration seule | Cycle de vie, outils et tutoriel retirés de la présentation, **stockage intact** |
| Aide visuelle dérivée des contrats | Carte aérée ; deux mensonges de l'ancien bloc corrigés |
| Calibration plein écran, sans carte centrée | Voile par `brightness(.76)`, cinq régions nommées |
| Le temps de lecture n'est pas du temps de mesure | `stageTimeoutMs` ne s'arme qu'en `RUNNING` ; `ARMED` sans décompte |
| Sept écrans, fenêtre réelle en étape 6 | Six exercices + rapport ; cadre saisi par le vrai moteur |
| Plus de tutoriel séparé | Module **supprimé** ; commande aliasée, dépréciation dite au cerveau |

## 3. Tests et validateurs

**Bare Hands : 430 → 505**, sur 21 fichiers. Chaque chiffre re-mesuré par l'agent 0 après le rendu de chaque slice, en deux lots au premier plan, jamais repris d'un rapport. Le creux à 502 en 07B est la suppression du module tutoriel, réconciliée par fichier au journal.

**Balayage élargi (Slice 08) :** 43 fichiers adjacents — Control Center, réglages, scène, traces, voix, garde-fous de documentation. Tout vert hors dette héritée.

**Preuve de trace d'agent réelle**, exigée pour la 07B : vrai `ControlCenter` sur port local, vrai client MCP, commande prise sur le vrai long-poll, vrai reçu POSTé. Quatre lignes de journal sous un identifiant unique, zéro reprise, zéro repli. Le cerveau reçoit une note qui dit que la calibration a été ouverte.

**Migrations prouvées, pas supposées :** un blob de réglages v1 sans clé de version et un profil v1 traversent ; `calibration_enabled` revient `True` — le défaut qui, mal géré, grisait silencieusement une entrée que personne n'avait désactivée.

**Vie privée / hors-ligne :** liste blanche MediaPipe, libération de la caméra sur tous les chemins d'arrêt, scalaires dérivés uniquement vers profil et traces. Aucune référence externe dans le diff.

## 4. Implémentations canoniques réutilisées, jamais recopiées

- `showMenu` / `closeMenu` et le crochet `run(act)` de `control_center.html` pour le menu contextuel ;
- `describeTools()` / `TOOL_CAPABILITY` pour la palette ;
- `manipulateBox`, `rebaseManipulation`, `resizeBySides`, `clampBox` et `JarvisScene.frames.*` pour la pratique de fenêtre — le cadre est **ramassé par le vrai résolveur de cibles**, pas simulé ;
- `JarvisSceneLayout.toScreen` pour le placer ;
- `openMeasureSeam` comme patron des deux nouvelles coutures ;
- `hand_art` comme unique vocabulaire de mains, consommé par l'aide **et** la calibration.

## 5. Risques résiduels

1. **Rien de visuel n'a été vu tourner.** `node` ne peut pas pousser le contrôleur au-delà de `starting` : pas de caméra, pas de bundle MediaPipe. Les présentations `sleep` et `active` n'ont **jamais** été rendues contre un contrôleur vivant. Tous les critères d'acceptation visuels sont argumentés et testés structurellement, pas regardés.
2. **Une couverture perdue, nommée :** un reçu vocal refusé dessiné dans une coque ouverte. La seule porte restante exige `active`. Point 22 de la checklist.
3. **32 échecs hérités de `main`**, six fichiers, tous vérifiés à `a949f40` — même domaine : autorité de scène et droits d'archivage du `brain`. Non réparés ici, délibérément : les mêler à ce diff le rendrait illisible. **Le dépôt n'est pas vert, et ne l'était pas avant nous.**
4. **Hypothèse de placement à vérifier à l'œil** : le cadre d'entraînement est posé en `position:fixed` alors que `toScreen` rend des coordonnées relatives à la racine de la scène. Les deux coïncident tant que `#sceneLayer` occupe le viewport entier, ce qui est le cas aujourd'hui.
5. **Fragilité signalée par son auteur** : dans `pumpPractice`, `preview` compte comme armement autant que `begin`. Qui simplifiera en « seulement `begin` » fera revenir un bug que les tests unitaires n'attrapent pas.
6. **Divergence héritée toujours non arbitrée** : une souris glisse toute la sélection, une main nue ne porte que l'objet nommé (`control_center_scene_page.js:2069-2078`). Hors périmètre, mais toujours en attente.

## 6. Ce que l'Humain doit faire

**`HUMAN-WEBCAM-CHECKLIST.md`** — 26 points ordonnés, chacun disant quoi faire et ce qui compterait comme faux. Il fusionne les huit vérifications des `human-validation.json` par slice et tout ce que la machine n'a pas pu atteindre.

Trois aperçus autonomes sont ouvrables sans Jarvis, sans caméra et sans serveur, dans le scratchpad de session : la palette et ses états, les sept poses de main avec l'échelle d'écartement mesurée, la coquille de calibration (avant/après contre la carte rejetée), les phases dans le temps, et la fenêtre d'entraînement aux deux moments d'armement.

Aucune fusion, aucun archivage Drive, aucune suppression de branche avant acceptation explicite.
