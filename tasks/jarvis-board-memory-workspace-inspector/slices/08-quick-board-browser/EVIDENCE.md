# Slice 08 — preuves (navigateur rapide des Boards)

## Ce qui a changé

Le panneau du bouton **Board** du haut (`#boardsHud` / `#boardsPanel`,
`jarvis/runtime/control_center_boards.js`) a évolué, sans second sélecteur :

- chaque ligne : titre et état (« Actif », « En fond », « Archivé ») sur une
  ligne, puis badge de nature (`Générique` / `Réunion` / `Présentation`, mêmes
  mots que le gestionnaire profond, épinglés par un test) et dernière ouverture
  relative lue sur le serveur (`last_opened_at` ; heure exacte au survol) ;
- filtre « En service N / Archivés N » ; un archivé n'a **aucun** bouton de
  bascule, seulement « Inspecter » ; chaque ouverture revient à « En service » ;
- nature choisie à la création (envoyée seulement si ≠ `empty`) et changée avec
  le titre : un seul `PATCH /api/boards/{id}` portant ce qui change ; rien ne
  change → aucune requête ; le badge vient de la liste relue, jamais du
  sélecteur ;
- « Inspecter » (loupe) ferme le panneau et ouvre `WSP` sur ce Board :
  `window.JarvisWorkspace.openBoard(id)` (nouveau), action `inspect-board` du
  gestionnaire (vue Boards, filtre « Tous », ligne dépliée et focalisée, jamais
  repliée) ; gestionnaire absent → le panneau reste ouvert et le dit
  (`workspace_manager_missing`), rejet tardif → infusion ; inerte pendant une
  autre action Boards ;
- liste lue en un aller-retour : `GET /api/boards?include_archived=true`.

## Parcours réel et captures (`evidence/`)

`tests/unit/test_boards_hud_browser.py::test_quick_browser_creates_edits_filters_and_inspects_against_the_real_stack` :
Chrome sans tête (harnais `_workspace_browser.mjs`), page **servie** par un vrai
`ControlCenter` relié à un vrai Core (`CaptureStack`, SQLite et données sous
`tmp_path`), aucun double de `fetch`. Monde semé par
`test_workspace_inspection_api.build` (Board principal, « Projet A » Réunion,
« Projet B » actif, « Ancien » archivé). Régénérer :
`JARVIS_S8_EVIDENCE_DIR=<ce dossier>/evidence pytest tests/unit/test_boards_hud_browser.py -k real_stack`.

| Capture | Ce qu'elle montre |
|---|---|
| `01-list.png` | Liste en service : 3 Boards, natures, « jamais ouvert » / « ouvert à l’instant », Board actif marqué (point plein, cadre, « Actif »), archivage du Board actif éteint, filtre « En service 3 / Archivés 1 » |
| `02-created-meeting.png` | « Point hebdo S8 » créé en **Réunion** (badge relu), focus sur sa ligne, infusion « créé (Réunion) » |
| `03-edit-kind.png` | Formulaire de la ligne : titre « Démo S8 » + nature « Présentation », Enregistrer / Annuler |
| `04-kind-changed.png` | Après la réponse du serveur : « Démo S8 », badge **Présentation** |
| `05-archived.png` | Filtre « Archivés » : « Ancien », état « Archivé », seule action « Inspecter », phrase d'aide |
| `06-inspect-archived.png` | « Inspecter » sur l'archivé : gestionnaire ouvert, onglet Boards, filtre Tous, ligne « Ancien » dépliée (mémoire `boards/<id>/memory`, liaisons, legacy) et focalisée, panneau Boards fermé |
| `07-inspect-meeting.png` | « Inspecter » sur « Projet A » (Réunion) depuis la liste en service |
| `08-narrow-edit.png` | 500 px : formulaire d'édition ouvert, aucun débordement horizontal (panneau ni page) |

Vérifié côté serveur après le parcours : « Démo S8 » existe, `board_kind:
presentation`, `status: active` ; « Ancien » toujours archivé ;
`GET /api/boards/active` identique avant et après (créer, modifier, filtrer,
inspecter ne basculent rien). Console : aucune exception, aucune ligne d'erreur
`[boards]` / `[workspace]` ; `boards.create_done`, `boards.update_done`,
`boards.filter_changed`, `boards.inspect_requested` présents.

Détecteur `/impeccable` (`detect.mjs --json control_center_boards.js`) : `[]`.

## Tests (un fichier à la fois)

| Fichier | Résultat |
|---|---|
| `test_boards_hud_js` | 28 passed (21 + 7 neufs : mots de nature = gestionnaire, dernière ouverture relative, badge/ouverture par ligne, filtre archivés sans bascule, corps de création avec nature, `PATCH` de nature peint après relecture + refus `invalid_board`, « Inspecter » et ses refus, recherche du gestionnaire au clic) |
| `test_boards_hud_browser` | 10 passed (9 + le parcours réel ci-dessus) |
| `test_workspace_manager_js` | 16 passed (14 + `inspect-board` sur un archivé, entrée `openBoard`) |
| `test_workspace_manager_browser` | 2 passed |
| `test_control_center_quality` | 73 passed |
| `test_boards_status` | 5 passed |
| `test_board_alerts_js` / `test_board_alerts_browser` / `test_board_alerts` | 7 / 3 / 31 passed |
| `test_scene_renderer_logic` | 62 passed |
| `test_control_center_mcp_inspector_js` / `test_control_center_timeline_ui` / `test_interaction_mode_hud_browser` | 34 / 13 / 6 passed |

Doubles de `fetch` des harnais `_boards_browser.mjs` et `_board_alerts_browser.mjs` :
la route de liste est reconnue avec sa requête (`?include_archived=true`).

## Ce qui n'est pas prouvé ici

- La bascule réelle entre trois Boards : la pile de test n'a pas d'hôte
  d'agents capable d'activer un Board. Elle n'a pas changé (même
  `switchTo`), couverte par `test_boards_hud_js` / `test_boards_hud_browser`
  (double de `fetch`) et `tests/integration/test_board_session_e2e.py`.
- HV-WS-UI-002 (clarté jugée par l'Humain : identifier le Board actif, basculer
  entre au moins trois Boards, créer/renommer, atteindre le gestionnaire) reste
  à faire sur le Jarvis vivant.
