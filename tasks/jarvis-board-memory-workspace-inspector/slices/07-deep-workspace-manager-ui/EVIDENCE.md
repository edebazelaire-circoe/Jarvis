# Slice 07 — preuves (gestionnaire Sessions & Boards)

## Montage

`tests/unit/test_workspace_manager_browser.py` : Chrome sans tête (CDP, harnais
`tests/unit/_workspace_browser.mjs`) ouvre la page **servie** par un vrai
`ControlCenter` relié à un vrai Core (`tests/fakes/capture_stack.py` : SQLite et
racine de données sous `tmp_path`, aucun double de `fetch`). Monde semé par les
propriétaires canoniques (`test_workspace_inspection_api.build`) puis élargi :
23 Sessions (1 ouverte, 22 closes), 4 Boards dont « Projet A » (Réunion) et
« Ancien » (archivé), liaisons, Contexts, trois artefacts dont un lien
`active_board` et un lien `explicit`, fichiers de mémoire (dont un binaire).
Captures régénérées par
`JARVIS_S7_EVIDENCE_DIR=<ce dossier>/evidence pytest tests/unit/test_workspace_manager_browser.py`.

## Parcours et captures (`evidence/`)

| Capture | Ce qu'elle montre |
|---|---|
| `01-overview.png` | Vue d’ensemble lue sur le serveur : Session ouverte, Board actif (nature, id, emplacement `boards/<id>/memory`, contenu, `summary.md`), Context actif (dossier), liaison au premier plan (cycle de vie, conversation, CLI, session d’agent, autorité de parole) |
| `02-sessions.png` | Historique paginé : 20 Sessions, « Charger la suite » (curseur du serveur) ; la deuxième page porte le total à 23 |
| `03-boards.png` | Tous les Boards, archivés compris, badge de nature, « Actif maintenant », détail : mémoire, artefacts liés, liaisons dans les Sessions, références legacy étiquetées |
| `04-relations-session.png`, `05-relations-board.png` | Session → Boards → liaison ; Board → mémoire, artefacts liés, références legacy, Sessions → liaisons |
| `06-memory-read.png` | Arborescence (tailles), lecture de `summary.md`, sha256 |
| `07-memory-written.png` | « Nouveau fichier » `notes/s7-ui.md` : créé, avis avec `journal n°`, arborescence relue, fichier rouvert |
| `08-memory-confirm-delete.png` | Après « Renommer » vers `notes/s7-renamed.md` : confirmation **dans le panneau**, rouge, qui nomme le chemin, le Board et « pas de corbeille » ; focus sur « Annuler » |
| `09-memory-deleted.png` | Suppression confirmée, arborescence relue sans le fichier |
| `14-memory-refusal.png` | Refus réel du serveur : créer `summary.md` qui existe → « Un élément porte déjà ce nom », `memory_exists · HTTP 409`, saisie gardée, une seule fois (dans le formulaire) |
| `10-session-ledger.png` | Journal de la Session ouverte : `board.memory.written`, `.moved`, `.deleted` avec Board et chemins |
| `11-memory-archived-read-only.png` | Board archivé : bandeau « lecture seule », aucune commande d’écriture, lecture permise |
| `12-artifacts-provenance.png` | Artefacts d’un Board ; détail : métadonnées, texte, provenance (« A produit »), Boards liés avec origine (« Board actif à la création », « Lien explicite ») |
| `13-narrow-memory-confirm.png` | 700 px : la mémoire s’empile, pas de défilement horizontal, confirmation lisible |

Vérifié côté serveur après le parcours : `notes/s7-ui.md` et
`notes/s7-renamed.md` absents du disque ; exactement trois lignes
`board.memory.*` (`written`, `moved`, `deleted`) avec `origin: "user"` dans le
journal de la Session ouverte ; `GET /api/boards/active` identique avant et
après (aucune activation). Console : aucune exception ; une seule ligne
d’erreur `[workspace]`, celle du refus provoqué (`memory_exists`).

## Tests (un fichier à la fois)

| Fichier | Résultat |
|---|---|
| `tests/unit/test_workspace_manager_js.py` (nouveau) | 14 passed |
| `tests/unit/test_workspace_manager_browser.py` (nouveau) | 2 passed |
| `test_boards_hud_js` / `test_boards_hud_browser` | 21 / 9 passed |
| `test_scene_renderer_logic` (registre d’empilement, `.wsp` au rang 55) | 62 passed |
| `test_control_center_quality` | 73 passed |
| `test_control_center_mcp_inspector_js` (ordre du dock avec `WSP`) | 34 passed |
| `test_control_center_timeline_ui` (8 outils, Cosmos) | 13 passed |
| `test_presentation_attention_browser` (pastilles à 520 px de haut) | 30 passed |
| 46 autres fichiers lisant la page ou ses repères (grep `_SCRIPT_MARKER`, `control_center.html`, `control_center_work.js`, `_served_page`) | verts (`test_capture_rail_browser` : 23 passed, 1 skipped), sauf 3 échecs **hérités** (identiques sur `5bc45e4` extrait à part) : `test_barehands_interaction_js` ×2, `test_interaction_mode_hud_browser::test_le_mouvement_reduit_arrete_vraiment_le_halo` |

## Ce qui n'est pas prouvé ici

- La bascule depuis le gestionnaire n'est prouvée que par node (contrôle Boards
  injecté) : la pile de test n'a pas d'hôte d'agents capable d'activer un Board.
  Elle emprunte `JarvisBoards.goToBoardFromAlert` → `JarvisBoardsControl.switchTo`,
  déjà couverts par `test_board_alerts_*` et `test_boards_hud_*`.
- HV-WS-UI-001 (clarté jugée par l'Humain) reste à faire.
