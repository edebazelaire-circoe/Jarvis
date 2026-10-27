# Slice 09 — QA code review + qa-verification

Relecteur : agent de QA indépendant (code-review, qa-verification, impeccable, error-handling), 2026-10-26.
Branche `task/jarvis-presentation-edition-v1-s09` (worktree `pev1e`), commits `d118d939`, `e3d7376c`, `10e752cc` au-dessus de `48972b1a`.
Aucun code produit modifié ; aucun JARVIS lancé (les bancs de test lancent leur propre Core / Control Center sur des ports et racines jetables).

## Résumé

Recommandation : **FAIL (rework ciblé)**. Le travail est soigné, bien documenté et sans régression mesurée (édition `full`
comprise), mais deux points touchent directement les critères d'acceptation de la Slice :

1. **MAJEUR (comportement)** — une saisie non enregistrée de l'éditeur est perdue sans un mot quand Variantes change de scène
   d'elle-même (lecture continue), et le champ garde le focus sur la scène suivante. Reproduit dans un vrai Chrome.
2. **MAJEUR (périmètre)** — le remplacement d'un visuel (étape 6 et « In Scope » de `SLICE.md`, HV-EDIT-01) n'est pas livré, et ce
   report n'est inscrit ni dans une Issue, ni dans les limites connues du contrat, ni dans HV-EDIT-01 (qui demande toujours au
   Human de « replace a visual »).

S'y ajoutent un trou de test majeur (la relecture de Core par Variantes après une édition n'est pas prouvée : la mutation qui la
retire survit) et des points mineurs (focus à la fermeture, région `aria-live` bavarde, captures périmées, une phrase de doc fausse à
600 px, une écriture en file qui peut viser la scène qu'« Annuler » vient d'afficher).

## Périmètre relu

- Core : `jarvis/domain/presentation_studio_history.py` (`scene_ids_of`, `HistoryEntry.summary`), `document_export.py` (libellés
  français, repli `Export Jarvis`), `presentation_studio_authoring.py` (`first_draft_rationale`), `presentation_studio_art_direction_authoring.py`.
- Page : `control_center_presentation_studio_inspector.js` / `_inspector_core.js`, `control_center_presentation_studio_explorer.js` /
  `_explorer_core.js` / `_explorer_remotion.js`, `control_center_workspace.js`, `control_center.html` (`@shell-layer`).
- Docs : `docs/presentation-studio.md` › *Editing from Variants (V1)*, `docs/control-center-shell.md` (z 9120, table *Product edition UI*),
  `docs/export.md`.
- Tests ajoutés/modifiés (14 fichiers), `LOG.md` (entrée S09), `human-validation.json`, captures `screenshots/`.
- Contexte : `SLICE.md`, `Issues/I-003`, `Issues/I-006`.

## Preuves (exécutées par moi)

Toutes depuis `pev1e`, `C:/Projects/jarvis/jarvis/.venv/Scripts/python.exe -m pytest`, avant-plan, par lots :

| Lot | Résultat |
|---|---|
| `test_presentation_editing_ui_browser.py` | 4 passés (37 s) |
| history, history_routes, document_export, document_export_routes, export_relay, remotion_export_save_mcp, export_after_edit, authoring, art_direction_authoring | 248 passés, 2 ignorés (liens symboliques sans privilège) |
| workspace_presentations_js, variants_controls_js, variants_remotion_studio_js, explorer_actions_js, variants_export_save_js, product_edition* | 136 passés |
| inspector behaviour_js, inspector_js, inspector_docs, inspector_browser | 68 passés |
| control_center_shell_layers, presentation_studio_explorer_browser, variants_controls_browser | 38 passés, 2 ignorés (Remotion runtime absent) |
| presentation_edition_ui_browser, control_center_presentation_rail_browser, workspace_presentations_browser | 39 passés |

Sondes navigateur (vrai Core + Control Center + Chrome du banc `tests/fakes/explorer_browser.py`, hors dépôt :
`C:\Users\Clarice\AppData\Local\Temp\claude\C--Projects-jarvis-jarvis\448345f0-a514-4023-9dde-33aed523cf61\scratchpad\s09qa\test_s09qa_probe.py`,
lancées par `run_probe.py` du même dossier) :

- `test_probe_draft_when_variants_plays` → finding M1 (sortie citée plus bas).
- `test_probe_focus_after_escape` → focus à l'ouverture sur `jviTitle` (bon) ; après `Échap`, `document.activeElement` = `jviTitle`
  d'un panneau caché (finding m1).
- `test_probe_full_edition` (`JARVIS_PRODUCT_EDITION=full`) → `data-developer-surfaces="visible"`, « Remotion Studio » visible, ligne
  de source de l'éditeur visible, « Modifier » sur la branche non active #2 : contexte « scène 2 sur 3 de la variante #2 non active »,
  titre enregistré dans Core (`Titre full`), Variantes fermée → l'inspecteur reste ouvert à z 34, `jvx-open` retiré. **Pas de régression `full`.**
- `test_probe_shots` (deux présentations, 1440×900, 1280×720, 600×800) → le choix de présentation est bien masqué quand l'éditeur est
  ancré (`jvi-pick is-solo`, un seul `select`) ; captures `…\scratchpad\s09qa\shots\qa-docked-*.png`.

Mutations (copie `git archive` au scratchpad, supprimée ensuite ; jamais dans le worktree) :

| # | Mutation | Test | Issue |
|---|---|---|---|
| 1 | `scene_ids_of` sans le repli `op["scene"]["scene_id"]` | `test_presentation_studio_history.py` | **tuée** |
| 2 | `onVariantEdited` (explorer) ne relit plus le graphe ni l'aperçu (`loadGraph(...).then(renderAll; schedulePreview)` retiré) | `test_modifier_edits_…_reads_core_back` | **survit** (finding M3) |
| 3 | undo sur une autre scène : `followInExplorer(touched[0])` retiré | même test | survit — mutant équivalent : `sayEdited` → `onVariantEdited` → `showScene` ramène déjà Variantes (deux chemins redondants, observation) |
| 4 | `copyHtml` sans la garde `render.state!=='complete'` | `test_workspace_presentations_js.py` | **tuée** |

Fins de ligne et caractères de contrôle : `git ls-files --eol` → `i/lf w/lf` pour les 30 fichiers texte modifiés ; aucun octet de
contrôle hors tab/LF, aucun CR, aucun BOM, UTF-8 valide partout ; les libellés `vidéo` sont en NFC.

SQLite : aucun fichier `sqlite_*` touché, aucun DDL ; l'anneau d'annulation est en mémoire (`scene_ids` calculé à la lecture) — pas de migration requise.

## Findings

### M1 — MAJEUR — Une saisie en cours est perdue en silence quand Variantes change de scène d'elle-même

- Code : Variantes dit chaque changement de scène, y compris ceux de la lecture continue (`showScene` → `renderStage` → `sayScene()`,
  `control_center_presentation_studio_explorer.js:1175`, `:1216`) ; l'éditeur suit (`onExplorerScene`,
  `control_center_presentation_studio_inspector.js:556`) par `chooseScene` (`:503`) qui appelle `abandonDrafts('scene')` (`:954`) :
  sessions effacées, écritures en file marquées `superseded`, **aucune annonce ni message**, seulement un journal `drafts_abandoned`.
  Même chose quand Variantes passe à une autre variante (`selectPresentation`, `:564`, `abandonDrafts('presentation')`).
- Scénario : « Modifier » sur la scène 1, l'utilisateur tape un nouveau titre (pas encore relâché), la vidéo joue dans Variantes (▶,
  ou lecture lancée avant) → au passage à la scène 2, le texte tapé disparaît, le champ montre le titre de la scène 2 **et garde le
  focus** : la frappe suivante modifie la scène 2.
- Preuve (sonde `test_probe_draft_when_variants_plays`, vrai Chrome) :
  `typed: "Brouillon QA | focus=INPUT"` puis, après le passage de scène,
  `{"ex":"pss_…e2","ins":"pss_…e2","field":"Les chiffres","pending":[],"status":"Chargement des réglages…","focus":"INPUT"}` ;
  Core garde `Version initiale` pour le titre de la scène 1. Aucun texte « abandonné » visible.
- Le LOG (d) ne note que le cas « Variantes change de variante » ; le cas lecture continue (le plus courant) n'est pas dit, ni dans le
  contrat (*One scene on screen*).
- Pistes (au choix du PM) : ne pas suivre les changements de scène dus à la lecture tant qu'un brouillon est sale (ou mettre la
  lecture en pause à l'ouverture de l'éditeur / à la première frappe), ou enregistrer le brouillon valide avant de suivre, ou au
  minimum dire « Modification non enregistrée abandonnée : scène k » et rendre le focus au titre. Test navigateur à ajouter.

### M2 — MAJEUR — Remplacement d'un visuel non livré et report non tracé

- `SLICE.md` › *In Scope* « media/image replacement and source clarity », étape 6 « Integrate media replacement through bounded
  internal assets », critère « common content/visual edits ». Le LOG (a) dit que l'éditeur n'offre qu'un champ texte pour un contrôle
  `url` et renvoie à un futur contrat d'assets de Core.
- Jugement : **acceptable pour la V1 seulement s'il est décidé et tracé** — il exige un contrat d'assets de Core (hors d'une passe UI,
  et l'étape 6 interdit d'exposer un chemin) ; les couleurs, le mouvement et le texte, eux, sont éditables. En l'état il n'est
  tracé nulle part d'opposable : pas d'Issue `I-00x` pour la Slice 09, pas de ligne dans *Known limit* du contrat V1
  (`docs/presentation-studio.md:2749` ne cite que la scène en fondu), et **HV-EDIT-01** (`human-validation.json:5`) demande toujours au
  Human de « replace a visual » : la recette échouera par construction.
- Attendu : décision du PM (report V1 accepté ou non) ; si accepté, une Issue avec propriétaire, la limite écrite dans le contrat V1,
  HV-EDIT-01 reformulé.

### M3 — MAJEUR (tests) — La relecture de Core par Variantes après une édition n'est pas prouvée

- Le contrat (*Honest saving*) et le constat « avant » n° 4 du LOG (« l'aperçu de Variantes ne relit la variante qu'au battement de
  10 s ») reposent sur `onVariantEdited` (`control_center_presentation_studio_explorer.js:2103`). La mutation 2 qui retire la relecture
  **survit** : `frameUntil … 'Titre modifié S09'` attend jusqu'à 20 s, plus que le battement de 10 s (`GRAPH_POLL_MS`), donc l'ancien
  comportement passe aussi.
- Pistes : borner l'attente du cadre sous le battement (≈ 3 s) ou neutraliser la relève périodique pendant ce pas, et compter les
  `GET …/graph` relus après `jarvis:studio-variant-edited`. Le chemin d'échec « Modification enregistrée, mais l'aperçu n'a pas pu être
  relu » / « Relire » n'a pas de test non plus.

### m1 — MINEUR (accessibilité) — `Échap` ou × dans l'éditeur ancré ne rend pas le focus à « Modifier »

- `close({restoreFocus:true})` vise le bouton du dock (`inspector.js:1388`), qui est sous Variantes (rendu inerte) : le focus reste sur
  `#jviTitle` d'un panneau caché (sonde `test_probe_focus_after_escape`). Un utilisateur clavier perd sa place. Rendre le focus à
  l'élément qui a ouvert l'éditeur (`[data-act=edit_scene]` quand l'ouverture vient de Variantes).
- Associé : « Modifier » porte `aria-haspopup="dialog"` (`explorer.js:793`) alors que l'éditeur est une `region` non modale.

### m2 — MINEUR (accessibilité) — La ligne de contexte est une région `aria-live` réécrite à chaque rendu

- `ui.context` (`inspector.js:186`) est `aria-live="polite"` et vidée/réécrite par `renderContext` à chaque `renderPick` → `renderAll`
  (chaque relecture, donc après chaque enregistrement). Un lecteur d'écran peut redire « Vous modifiez la scène… » après chaque
  « Titre : enregistré. ». Ne réécrire que si le texte change, ou annoncer le changement de scène par la région `ui.live` existante.

### m3 — MINEUR (course) — Une écriture en file peut viser la scène qu'« Annuler » vient d'afficher

- L'opération d'une écriture en file est construite au moment où elle part, avec `scene_id: S.sceneId` (`inspector.js:1012`, code
  existant). `chooseScene` neutralise la file (`abandonDrafts`), mais le nouveau saut d'« Annuler » vers une autre scène
  (`inspector.js:1191`) change `S.sceneId` sans le faire (`discardDrafts` ne marque pas les tâches en file `superseded`).
- Scénario (étroit, non reproduit) : deux réglages relâchés coup sur coup sur la scène A (le second attend le premier), Ctrl+Z dont le
  pas porte sur la scène B → la seconde écriture part avec `scene_id = B` et le `if_current` relu sur B : la valeur de A s'écrit sur B.
  C'est exactement le « silently affect unrelated scenes » du critère d'acceptation. Correctif simple : appeler `abandonDrafts('scene')`
  (ou marquer la file `superseded`) avant de changer `S.sceneId` dans ce chemin.

### m4 — MINEUR (preuves) — Captures « après » périmées

- `screenshots/after-edit-docked-1280x720.png` et `-600x800.png` montrent encore le choix « Présentation » et la rangée cassée
  (« › » seul sur sa ligne) que `e3d7376c` dit avoir réparés ; l'état actuel est correct (mes captures
  `…\scratchpad\s09qa\shots\qa-docked-*.png`). Le paquet Human doit montrer l'état livré.

### m5 — MINEUR (doc) — « fixed at the right » faux sous ~450 px de marge

- `docs/presentation-studio.md:2711` et la règle `html.jvx-open #jvStudioInspector{…right:8px…}` (`_inspector_core.js:43`) : à 600×800
  le panneau mesuré est à `left:10, right:430` (une règle de base `left` l'emporte), donc à gauche, Variantes visible à droite. Le
  rendu est utilisable ; la phrase du contrat (et le constat LOG (e)) doit dire ce qui se passe réellement.

### m6 — MINEUR (tests) — Assertions plus faibles que la docstring

- `test_modifier_edits_…` affirme dans son commentaire « S2 and S3 untouched … byte-identical » mais ne vérifie que `S1` ; la
  phrase produit de I-006 (« Le moteur vidéo de Jarvis n'est pas prêt… », `explorer_remotion.js:200`) n'a aucun test ; aucun test
  navigateur de l'édition `full` (mes sondes la couvrent, pas la suite).

## Points vérifiés sans finding

- **Masquage des surfaces de développement** : « Remotion Studio », la ligne `.jvx-rms` et la ligne de source de l'éditeur portent
  `data-surface="developer"` (règle unique de la page) — pas de nouvelle liste ; le menu du rail était déjà marqué (S08). Test
  navigateur en `presentation` (caché) et `JARVIS_DEVELOPER_MODE=1` (visible) ; table de `control-center-shell.md` à jour.
- **Pas de boucle** éditeur ↔ Variantes : `sayScene` ne dit qu'un changement (`sceneSaid`), `chooseScene(…,{fromExplorer:true})` ne
  renvoie pas, `followInExplorer` sort si la scène est déjà à l'écran ; l'écho d'un `showScene` retombe sur `d.scene_id===S.sceneId`.
- **Pas de course relecture/saisie dans l'autre sens** : la relecture de Variantes (`onVariantEdited`) ne touche pas l'éditeur ;
  « enregistré » n'est dit qu'après relecture de Core (règle inchangée).
- **Historique côté Core** : `scene_ids` est un champ ajouté (clients existants intacts : routes, client typé, MCP passent), dérivé des
  opérations inverses à la lecture ; toutes les opérations du vocabulaire portent `scene_id` à plat sauf `scene.add` (`scene.scene_id`),
  couvert. Identifiants seulement, aucun titre ni valeur. Aucun schéma SQLite touché.
- **Copie PNG/PDF vers Documents** : `POST /api/exports {artifact_id}` seul (même relais et même contrat S03 que Variantes), ajouté à la
  liste blanche de la page, échéance 125 s alignée sur le relais, une seule copie à la fois par artefact, `display_path` de Core, phrases
  `SAVE_ERRORS` partagées, code affiché, journal `workspace.copy_*` au bon niveau. Noms : `default_stem` repasse par `file_stem`
  (séparateurs, noms réservés, 80 caractères) ; `Atelier - vidéo.mp4`, `- image.png`, `- PDF.pdf`, repli `Export Jarvis`.
- **Erreurs visibles** : refus d'ouvrir l'éditeur dits (archivée, aperçu pas prêt, comparaison, présentation en cours), éditeur absent
  dit, échec de relecture dit avec « Relire ».
- **Qualité visuelle** : 1440×900 et 1280×720 — Variantes laisse 436 px, rangée de scène sur une ligne, « Modifier » accentué sans
  concurrencer « Présenter » ; 600×800 — l'éditeur recouvre la partie gauche de Variantes, « Fermer » reste atteignable, pas de
  défilement horizontal (test).
- **Docs** : contrat V1 cohérent avec le code (hors m5) ; `export.md` et `control-center-shell.md` à jour ; `@shell-layer 9120` dans la page.

## Flagged (hors Slice ou à décider)

- **Phrase produit d'I-006 inatteignable** : en `presentation` sans mode développeur, la porte Remotion Studio et sa ligne d'état sont
  cachées, donc la nouvelle phrase « Le moteur vidéo de Jarvis n'est pas prêt… » n'apparaît nulle part. Sans gravité (l'export vidéo a
  ses propres messages), mais à savoir.
- **I-006 n° 5** (icônes du Board sur l'anneau à 600×800) : ni traité ni réattribué par la Slice 09.
- **Changement de nom d'export** : un rendu déjà copié sous `… - video.mp4` sera recopié sous `… - vidéo.mp4` (la déduplication par
  octets ne regarde que les noms de la série actuelle). Acceptable, à dire si un utilisateur s'en étonne.
- **Copie faite = bouton disparu** jusqu'au rechargement de la vue (`S.copies` jamais vidé) : pas de seconde copie volontaire. Choix
  défendable ; même comportement que Variantes à vérifier.
- **Aperçu local de l'éditeur écrasé à 1280×720** sur le banc (bandeau d'environ 40 px dans `qa-docked-1280x720.png`) : à regarder au
  runtime sur un vrai deck.
- Chemins redondants pour ramener Variantes après un « Annuler » (mutation 3 équivalente) : sans risque, à garder en tête.

## Non vérifié

- Essai réel de bout en bout sur un deck écrit par le vrai cerveau, export réel PNG/PDF/MP4 et copie dans le vrai `Documents\Jarvis`
  (confié à l'agent runtime ; je n'ai lancé aucun JARVIS).
- Lecteur d'écran réel (NVDA/Narrateur) : l'analyse ARIA est statique.
- Suites hors périmètre et échecs connus (`test_control_center_shell_browser`, MCP, barehands…) : non relancés.
- m3 n'a pas été reproduit (course étroite) : analyse de code seulement.

## Recommandations au PM

1. Rework M1 (avec test navigateur : brouillon + lecture continue) et m3 (une ligne).
2. Décider M2 : report V1 accepté → Issue `I-008` (propriétaire, contrat d'assets de Core), limite dans le contrat V1, HV-EDIT-01
   reformulé ; sinon implémenter.
3. Renforcer le test de M3 (attente sous le battement, compte des relectures) et les assertions de m6.
4. m1, m2, m4, m5 dans la même reprise (petits).
