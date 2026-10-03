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
| `04-relations-session.png`, `05-relations-board.png` | Session → Boards → liaison (statut traduit « ouverte »), mémoire, artefacts ; Context (« Actif », « Artefacts du Context ») ; « Artefacts de la Session ». Board → mémoire, artefacts liés (chaque identifiant ouvre son détail), références legacy, Sessions → liaisons |
| `06-memory-read.png` | Arborescence (tailles), lecture de `summary.md`, sha256 ; le volet du fichier nomme son Board (« dans la mémoire du Board « Projet A » · board_… ») |
| `15-memory-refreshed.png` | **Rework F1.** Écrit hors du gestionnaire (relais `POST …/memory/write` depuis la page, comme un autre onglet) : `notes/externe.md` créé, `summary.md` complété. « Actualiser » : l’arborescence montre `externe.md`, le fichier ouvert montre « Ajout externe. » ; le bandeau dit « Lu à HH:MM:SS » (l’âge des données de la vue), plus jamais « À jour » |
| `07-memory-written.png` | « Nouveau fichier » `notes/s7-ui.md` : créé, avis avec `journal n°`, arborescence relue, fichier rouvert |
| `08-memory-confirm-delete.png` | Après « Renommer » vers `notes/s7-renamed.md` : confirmation **à côté de la ligne cliquée** (ici dans le volet du fichier, entre ses commandes et son texte), rouge, seul rouge plein de la vue, qui nomme le chemin, le Board et « pas de corbeille » ; focus sur « Annuler » |
| `09-memory-deleted.png` | Suppression confirmée, arborescence relue sans le fichier |
| `14-memory-refusal.png` | Refus réel du serveur : créer `summary.md` qui existe → « Un élément porte déjà ce nom », `memory_exists · HTTP 409`, saisie gardée, une seule fois (dans le formulaire) |
| `10-session-ledger.png` | Journal de la Session ouverte : `board.memory.written`, `.moved`, `.deleted` avec Board et chemins |
| `11-memory-archived-read-only.png` | Board archivé : bandeau « lecture seule », aucune commande d’écriture, lecture permise |
| `12-artifacts-provenance.png` | Artefacts d’un Board ; détail : métadonnées, état traduit (« Complet », valeur brute en infobulle), texte, provenance **traduite et orientée** (« Cet artefact a produit jart_b… », infobulle `relation : derived_from`), Boards liés avec origine (« Board actif à la création », « Lien explicite ») |
| `16-artifact-outside-list.png` | **Rework F2.** Le lien de provenance vers `jart_b…` (lié au seul Board « Projet A », donc absent de la liste de « Projet B ») ouvre son détail épinglé « Artefact hors de la liste courante » (« Fermer »), focalisé : « Cet artefact est dérivé de jart_a… », texte « résumé » |
| `13-narrow-memory-confirm.png` | 700 px : la mémoire s’empile, pas de défilement horizontal, confirmation lisible |

Clavier (rework F3), touches **réelles** (CDP `Input.dispatchKeyEvent`) :
Entrée sur « Supprimer » du fichier ouvert → confirmation dans le volet du
fichier, focus sur « Annuler » ; Échap → focus revenu sur ce « Supprimer » ;
Entrée sur « Ajouter à la fin » → formulaire ; Échap → focus revenu sur
« Ajouter à la fin » ; Entrée sur « Supprimer » de la ligne `notes/plan.md` de
l’arborescence → confirmation juste sous cette ligne ; Entrée sur « Annuler »
→ focus revenu sur ce « Supprimer ».

Vérifié côté serveur après le parcours : `notes/s7-ui.md` et
`notes/s7-renamed.md` absents du disque ; exactement cinq lignes
`board.memory.*` avec `origin: "user"` dans le journal de la Session ouverte
(les deux écritures externes `notes/externe.md` et `summary.md`, puis
`written`, `moved`, `deleted` du gestionnaire) ; `GET /api/boards/active` identique avant et
après (aucune activation). Console : aucune exception ; une seule ligne
d’erreur `[workspace]`, celle du refus provoqué (`memory_exists`).

## Tests (un fichier à la fois)

| Fichier | Résultat |
|---|---|
| `tests/unit/test_workspace_manager_js.py` (nouveau) | 14 passed |
| `tests/unit/test_workspace_manager_browser.py` (nouveau) | 2 passed |

Rework S7 (après QA), mêmes fichiers un à la fois :

| Fichier | Résultat |
|---|---|
| `test_workspace_manager_js.py` | 22 passed (8 nouveaux : Actualiser relit arborescence et fichier ouvert et garde la saisie ; âge des données par vue ; artefact hors liste ; relations de Session → artefacts ; valeurs traduites avec valeur brute en infobulle ; confirmation à côté de la ligne et Board du fichier ; échappement de HTML dans noms de fichier, contenu, texte d’artefact, titre de Board, titre de Context, aperçus ; vue ouverte avant que le Board actif soit connu ; la liste d’adresses en refuse 11 de plus, dont `x/api/…`, `evil/api/artifacts/x`, `//evil/…`, `\`) |
| `test_workspace_manager_browser.py` | 2 passed, **21 exécutions de suite sans échec** après correction (≈ 11 s chacune, contre 25 s avant) ; les 4 dernières, sur le code final : 10,8 s, 11,4 s, 18,4 s, 11,5 s |
| `test_boards_hud_js` | 21 passed |
| `test_control_center_quality` | 73 passed |
| `test_control_center_mcp_inspector_js` | 34 passed |

Mutations tuées par le test d’échappement (chacune appliquée seule, test
rouge) : nom de fichier non échappé dans l’arborescence, `data-path` non
échappé, texte d’artefact non échappé, aperçu de recherche non échappé. Le
test « vue ouverte avant le Board actif » est rouge sans la relecture au
retour de `/api/boards`.

### F7 — cause de l’intermittence

Reproduit (2 échecs sur 22 exécutions, 57 s chacun) avec le harnais rendu bavard : c’était
`test_on_a_narrow_screen…`, l’attente de la ligne `notes/plan.md`. L’onglet
Mémoire était cliqué **avant** la réponse de `/api/boards` ; le plan donnait
alors au `<select>` une valeur dont l’option n’existait pas encore (valeur
vide, aucun Board choisi), et la vue restait sur « Choisissez un Board » : la
pause fixe de 250 ms après chaque clic ne couvrait ce délai que si la machine
n’était pas chargée. Corrigé des deux côtés : le produit choisit le Board
actif dès que `/api/boards` ou la vue d’ensemble répond (une vue ouverte trop
tôt ne reste plus vide) ; le plan attend que l’option **existe** avant de la
choisir. Le harnais n’a plus aucune pause à l’aveugle : port de débogage lu
dans `DevToolsActivePort` (plus de port tiré au hasard), page chargée et
module installé attendus (au lieu de 1,5 s), chaque attente plafonnée à 45 s
avec, en cas d’échec, la condition, la durée et ce que le panneau montrait ;
captures après deux images peintes. Même famille de course, corrigée dans le
produit : une liste déroulante changée mais pas encore envoyée (« Afficher »)
n’est plus remise à l’ancienne valeur par une réponse qui arrive entre-temps
(`data-dirty`).
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
