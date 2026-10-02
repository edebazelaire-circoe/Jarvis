# Implementation log

Reserved for implementation agents. Record durable execution notes here; do not fabricate progress.

## 2026-10-02 — Slice 00 (agent 0)

- S0 handoff mirrored from Drive (`6260a04`), 42 files byte-identical.
- Branch from `origin/main@467232f`, worktree `C:/Projects/jarvis/bbm`.
- Blind audit + wide baseline done; prerequisite landed; README Session premise stale.
- Resolved architecture `docs/06-resolved-architecture.md`, Slice 00 contracts appended, Task Types waived.
- Readiness: **READY** (`slices/00-project-manager/READINESS.md`).
- Drive: Human asked to move the folder `to-do` → `current` (no MCP move tool).

## 2026-10-02 — Slice 01 (implementer)

- Commit `a14a784` : `BoardKind` + `Board.board_kind` (défaut `empty`, décodage
  rétrocompatible, éditable via `update_board` et `POST`/`PATCH /v1/boards`
  par `parse_board_edits` — aucune route modifiée ; relais CC inchangé),
  `jarvis/domain/board_memory.py` (localisateur `boards/<board_id>/memory`,
  `BoardMemoryPath`, codes `memory_*`), 5 `ActivityKind` `board.*`,
  `docs/boards.md` (ligne 19, sections Board kind / Board memory /
  Non-activating inspection), `docs/artifacts.md` (kinds du ledger).
- Tests (premier plan, fichier par fichier) : test_board_memory_contract 84,
  test_workspace_board_contract 72, test_board_store_sqlite 17,
  test_board_service 25, test_board_switch 18, test_board_brief 3,
  test_session_manager 17, test_settings_mcp 63, test_mcp_catalog 71,
  test_schema_migrations 8, + 30 fichiers important les modules touchés
  (dont integration/test_board_session_e2e 7) : tous verts.
- Différé : `board_kind` dans les outils MCP `jarvis-console`/`jarvis-workspace`
  (S06), le HUD Boards (S08), le bloc `board` (S03).

## 2026-10-02 — Slice 02 (implementer)

- Commit `80f2a44` : migration v8 `board_artifact_links` (FK `work_boards`,
  `artifacts` ON DELETE CASCADE, origine `active_board|explicit`, index par
  artifact et par Board/temps), schéma figé `tests/schema/jarvis_state.v8.sql` ;
  lien auto au Board actif de la Session **ouverte** dans la transaction
  d'insertion de l'Artifact (`sqlite_artifacts.create_artifact` ->
  `link_to_active_board`), sans événement (`artifact.created` reste le fait),
  rien si aucune Session ouverte ou Artifact d'une autre Session ; pas de
  rattrapage. Port + adaptateur des liens explicites
  (`jarvis/ports/board_artifact_links.py`, `jarvis/adapters/sqlite_board_artifact_links.py`).
  `FileBoardMemoryStore` (`jarvis/adapters/board_memory_store.py`, port
  `jarvis/ports/board_memory.py`) : racine via `safe_folders`, lstat de chaque
  composant (lien/jonction jamais suivi -> `memory_path_escape`), fstat vs
  lstat à l'ouverture, tree/stat/read/search bornés, write create/replace/append
  atomique (temp + fsync + replace ; create sans écrasement), mkdir, move, delete.
  Docs : local-data (`boards/`, v8), artifacts (*Board links*), boards (*Store*).
- Tests (premier plan, fichier par fichier) : test_schema_migrations 8,
  test_board_artifact_links 9, test_board_memory_store 31 + 1 skip (symlink :
  WinError 1314, privilège absent ; la jonction réelle passe), test_board_memory_contract 84,
  test_artifact_store 15, test_artifacts_domain 50, test_board_store_sqlite 17,
  test_board_service 25, test_session_manager 17, test_session_context_store 39+1s,
  test_capture_mcp 14, integration/test_board_session_e2e 7, + 41 fichiers
  important `sqlite_state`/artifacts : verts sauf test_brain_delegation 1
  (hérité, READINESS §5). test_capture_store : assertion v6->v7 figée sur 7
  passée à `_SCHEMA_VERSION` (même motif que test_artifact_store).
- Différé : service/routes (S04), mutations sémantiques + ledger `board.memory.*`
  et règle Board archivé (S05), hydratation (S03).
- 2026-10-02 S1: rework — alias Windows : noms courts 8.3 (`~N`) refusés
  `memory_path_invalid` ; casse ignorée partout par le magasin (recherche par
  composant, collision `memory_exists`, renommage de casse permis, chemins
  rendus tels que stockés) ; `is_summary` casse ignorée ; docstrings exactes.
  Tests : `aux.tar.gz`, `COM¹`/`LPT³`, `.`/`:`, `board_kind` en HTTP.
  `preview()` dans board_service ; R2 en valeurs pointées + `ON DELETE
  CASCADE` ; READINESS §5 : test_settings_mcp intermittent. Verts :
  contract 116, store 33+1 skip, protocol 15, service 25, workspace_board 72,
  e2e 7.

## 2026-10-02 — Slice 03 (implementer)

- Bloc `board` du tour : `board_kind` (dans le budget 2 048 du Board) et
  `memory` (`BrainBoardMemory`, budget propre) — `locator`
  `boards/<id>/memory`, `path` absolu, manifeste `tree(depth=2,
  max_entries=40)` borné aussi à 2 048 car. sérialisés (`truncated`), tête de
  `summary.md` lue **par son nom** (casse ignorée, même si le manifeste coupé
  ne l'atteint pas) ≤ 2 048 octets coupée sur un caractère entier,
  `error` / `summary_error` (codes stables). Lecture à chaque tour par
  `jarvis/core/board_hydration.py` via `FileBoardMemoryStore` (composition
  `v2_app`), jamais copiée dans la Session ni un Context. Échec magasin ->
  bloc dégradé, journal `core.board.memory_unreadable` / `_readable` au
  changement d'état seulement.
- Control Center : `render_board_memory` (décodage strict : locator du Board
  du bloc, chemin absolu, entrées hors contrat sautées et liste dite coupée ;
  mémoire vide = une ligne ; illisible = « INDISPONIBLE ») ; résumé délimité et
  neutralisé (`neutralize_lines`). `--add-dir <data_root>/boards` (Claude,
  profil conversation) via `ControlCenter(boards_dir=)` / `ClaudeLocalAgent.boards_dir`,
  dossier créé par `safe_folders` avant le lancement, refus dit une fois.
- Prompt : section « MÉMOIRE DE BOARD » dans `BRAIN_SYSTEM_PROMPT` (+338 octets ;
  programme `conversation_session` 6 805 -> 7 143 octets). Hash figé de
  `test_scene_artifacts` mis à jour (changement délibéré).
- Tests : nouveau `test_board_memory_hydration.py` (21) ; `test_board_context_and_host`
  (`board_kind` dans le dict exact). test_brain_delegation : 1 échec hérité
  avant/après, inchangé (READINESS §5).
- Différé / risques : `summary.md` dans la trace non masqué (pas de parole de
  salle) ; `read` hache tout le fichier à chaque tour (gros `summary.md`) ;
  Codex sans `writable_roots` pour `boards/` ; terme non promu dans
  `docs/CONTEXT.md` (déjà absent pour la mémoire de Board) ; lectures/écritures
  ciblées d'un Board inactif = S04-S06.

## 2026-10-02 — QA S01/S02, reworks (agent 0)

- QA S01: approve (no escape on NTFS); rework `f1e0b01` (8.3 aliases refused, case-insensitive store, tests killing 2 surviving mutations, HTTP board_kind test).
- QA S02: approve with findings; rework on `fix/s2-rework` (725b1c7), cherry-picked after S03: chain identity re-checked before/after write/move/delete (residual race documented), temp names reserved, `read` sha256 only ≤ 1 MiB. 13/13 guard mutations caught. Re-run in bbm after pick: hydration 21, store 47+1s, contract 124, brief 3 — green.
- Carried to S04: store calls off the event loop; catch `BoardMemoryError` before `ValueError`; open Session `active_board_id` pointing at a missing Board blocks artifact creation (N6, corrupted-data only).

## 2026-10-02 — Slice 04 (implementer)

- Commit `e90902f` : `WorkspaceService` (`jarvis/core/workspace_service.py`) composant
  `BoardRepository`, `ContextRepository`, `ArtifactService`, `BoardArtifactLinkStore`,
  `BoardMemoryStore` (aucune copie) ; routes Core `/v1/workspace/*`
  (`jarvis/protocol/workspace_routes.py`, 11 GET) ; relais `/api/workspace/*`
  (`jarvis/runtime/workspace_relay.py`, sous-classe de `CaptureRelayRoutes`, préfixe de
  journal `workspace.request`, 30 s pour mémoire et `board_inspect`), gardé en lecture
  (`READ_GUARDED_ROUTES`) ; `/v1/workspace/` ajouté à `FORWARDABLE_PREFIXES` (test épinglé mis à jour).
- Extensions des magasins : `ArtifactQuery.board_id` (filtre par liens v8, même ordre et
  curseur) ; `list_sessions(before=)` ; `list_bindings_of_board` ; `FileBoardMemoryStore.exists`
  (`check_existing_tree`, ne crée rien, jonction -> `board_memory_unsafe`) ;
  `capture_api.artifact_summary` rendu public et partagé.
- Reports de S02/S03 traités : appels mémoire dans `asyncio.to_thread` ; bornes validées par
  le service (`WorkspaceError` `invalid_request`) ; `_CODED` (dont `BoardMemoryError`,
  `WorkspaceError`) attrapé avant `ValueError` ; exception inattendue -> 500
  `workspace_failed` journalisée (`core.workspace.read_failed`) ; Session ouverte dont
  `active_board_id` nomme un Board absent -> 200 + `problems` (`board_not_found`,
  `binding_not_found`) et entrée `missing`. `/v1/activity` inchangé (Session ouverte) ;
  l'activité d'une Session quelconque passe par `/v1/workspace/sessions/{id}/activity`.
- Choix : une lecture ne crée jamais `boards/<id>/memory` (Board sans mémoire : `exists:
  false`, arbre/recherche vides, `memory_not_found` pour un chemin) ; curseurs opaques
  base64url JSON typés ; `limit` ≤ 100 partout ; `/api/boards*` porte `board_kind` (vérifié).
- Tests (premier plan, fichier par fichier) : nouveau `test_workspace_inspection_api` 46
  (dont preuve sans effet de bord sur 31 lectures Core + relais : comptes de toutes les
  tables, Sessions, liaisons, Boards, autorité, mode, listing `boards/`) ;
  test_board_memory_store 49+1s ; test_board_protocol 15, test_board_service 25,
  test_board_switch 18, test_board_switch_control_center 17, test_capture_api_protocol 70,
  test_capture_relay 35, test_artifact_store 15, test_session_manager 17,
  integration/test_board_session_e2e 7, + 64 fichiers important les modules touchés : verts
  sauf test_app 1 (hérité, READINESS §5).
- Différé : mutations mémoire/liens (S05), MCP (S06), UI (S07-S08). Risque : la liste des
  Boards d'une Session lit tous les Boards (`list_boards`) — petit en V1.

## 2026-10-02 — QA S03, rework (agent 0)

- QA S03: approve; real Brain trace on isolated Core/CC (4 turns, ≈ $0.68) — Board summary used, durable note written to Board memory not SessionContext, other Board not leaked, Context unchanged across switches. Evidence `slices/03-board-sessioncontext-hydration/EVIDENCE.md`.
- Rework `fix/bm-s3-rework` (1148928) cherry-picked after S04: `neutralize_lines` uses `splitlines()` (\r, U+2028… no longer bypass), Context brief rule reconciled with the Board-memory rule (+82 B).

## 2026-10-02 — Slice 05 (implementer)

- `WorkspaceService` (`jarvis/core/workspace_service.py`) : `memory_write` (create par défaut |
  replace | append, `expected_sha256`), `memory_mkdir`, `memory_move`, `memory_delete`
  (`recursive` faux par défaut), `artifact_link` / `artifact_unlink` (origine `explicit`),
  sur un Board **nommé**. Board archivé -> `board_archived` pour toute mutation, lectures
  permises. Verrou `asyncio.Lock` par Board, de la vérification d'archivage à la ligne du
  ledger (vérification sha + remplacement jamais entrelacés). Magasin dans `asyncio.to_thread`.
- Ledger : une ligne par mutation qui change quelque chose (`board.memory.written` — `mkdir`
  aussi, `mode: mkdir` —, `.moved`, `.deleted`, `board.artifact.linked|unlinked`), `board_id`,
  chemins, mode, octets, taille, `sha256` du fichier entier, `origin` `user|brain` (convention
  des routes de capture, `ORIGINS`), Session ouverte ; aucune ligne pour un no-op. Mémoire :
  fichier puis ligne, échec de la ligne -> 500 `workspace_ledger_failed` avec `applied: true`
  et `result` (fenêtre documentée) ; liens : lien + ligne dans une transaction (S02).
- Routes Core `POST /v1/workspace/boards/{id}/memory/{write,mkdir,move,delete}`,
  `POST|DELETE /v1/workspace/boards/{id}/artifacts/{artifact_id}` ; corps JSON strict
  ≤ 2 Mio (`MAX_MUTATION_BODY_BYTES`), contenu ≤ 256 Kio UTF-8 sans NUL ni surrogat isolé
  (`memory_not_text`). Relais `/api/workspace/*` même méthode ; déjà dans `READ_GUARDED_ROUTES`
  (toutes méthodes : Host + Origin de bouclage, jamais cross-site), plus strict que la garde
  d'écriture de `/api/boards`. Journal : `core.workspace.mutated` / `.mutation_failed` /
  `.ledger_failed`, `workspace.request.relayed`.
- Corps lus en entier : `read_bounded` (`jarvis/protocol/strict_json.py`) remplace un
  `content.read(n)` unique (qui peut rendre moins que `n`) dans `capture_routes._body` et le
  relais ; borne du relais par classe (`MAX_BODY_BYTES`).
- Tests : nouveau `test_workspace_memory_mutations` 62 (chemins heureux, chaque code, archivé,
  verrou — prouvé rouge sans verrou —, contenu du ledger, échec du ledger, parité relais,
  garde cross-origin 18 cas, non-activation après 8 mutations, 256 Kio via relais).
  Verts : test_workspace_inspection_api 46, test_board_memory_store 49+1s,
  test_board_artifact_links 9, test_board_protocol 15, test_capture_relay 35,
  test_capture_api_protocol 70, test_board_switch 18, integration/test_board_session_e2e 7,
  + 41 fichiers important les modules touchés ou le serveur/CC. Deux listes blanches qui
  comparaient par préfixe `/api/work` (`test_work_view`, `integration/test_work_cancel_protocol`)
  prenaient `/api/workspace` pour l'état de travail : comparaison par segment.
- Risques : écrivain hors service (outils fichiers du cerveau via `--add-dir boards`) non
  sérialisé ; archivage concurrent (`BoardService` a son propre verrou) peut laisser passer
  une écriture ; `scene_wire.read_bounded_body` reste une variante propre à la scène.
- 2026-10-02 S4: rework (QA S04, après S5) — curseurs liés à leur liste **et** portée (empreinte
  `sha256` courte de `board_id:|session_id:|context_id:` + id) et entiers bornés à 64 bits signés
  (400 `invalid_request`, plus d'`OverflowError` 500) ; `core.workspace.read` émis aussi par
  `session_list`, `activity`, `memory_stat` (et la mémoire absente) ; les lectures du magasin ne
  créent plus jamais la racine (`check_existing_tree` ; préféré au verrou par Board, qui n'ordonne
  que les écrivains du service) ; délai 30 s du relais testé (faux Core lent : 504 pour les autres) ;
  `truncated` possible avec 0 correspondance documenté. Verts : inspection 51, mutations 62,
  capture_relay 35, board_memory_store 49+1s, e2e 7, hydration 31, board_context_and_host 17,
  capture_api_protocol 70.

## 2026-10-03 — Slice 06 (implementer)

- Nouveau serveur `jarvis-workspace` : `jarvis/runtime/workspace_mcp.py` (`WorkspaceTools`, `build_server`,
  `mcp_config`, `write_mcp_config`, `serve_stdio`), sous-commande `jarvis workspace-mcp`,
  `runtime/workspace-mcp.json`, catégorie `workspace` (« Boards et mémoire ») dans `mcp_tool_meta`.
  Déclaré au seul profil Claude `conversation`, sans interrupteur (`ClaudeLocalAgent._workspace_mcp_args`,
  drapeau `workspace_tools`, `ControlCenter(workspace_mcp=…)`, liste native de la passerelle).
- Les 9 outils Board/Session **déplacés** de `jarvis-console` (mêmes noms et sémantiques, aucun alias) ;
  `console_boards.py` -> `workspace_boards.py` (`BoardTools`, transport `call` partagé, `WorkspaceToolError`) ;
  `board_kind` sur `board_create` / `board_update` et dans chaque résultat Board. La console ne garde que
  `settings_*`.
- 11 outils neufs, façades des routes S04/S05 (aucune règle métier) : `session_list`, `session_get`,
  `board_inspect` (nom retenu au lieu de `workspace_inspect` : les relations d'une Session sont `session_get`),
  `board_memory_tree|read|search|write|move|delete`, `board_artifacts`, `board_artifact_link` (lier/délier).
  Mutations `origin: brain` ; `truncated` d'une recherche = note « Recherche incomplète » ; détail et provenance
  d'un Artifact restent sur `jarvis-capture` (`capture_mcp.artifact_item` partagé). Pas de mkdir/stat/activité.
- `board_kind` en motif, pas en enum : la valeur `meeting` indexée par `list_tools` faisait passer
  board_create/update devant l'agenda (recall@3 0,88 < 0,90) ; descriptions sans « fichier / dossier / écrire »
  pour la même raison — les deux jeux de pertinence gardent exactement leurs ratés d'avant.
- Budget : outils natifs déclarés 68 583 -> 75 823 o (+7 240 o ; console 9 616 -> 2 973, workspace 13 883) ;
  consignes +379 o ; prompt `BRAIN_WORKSPACE_PROMPT` 664 o (tous les programmes de conversation). Gates dans
  `test_mcp_catalog`.
- Traces réelles (Core 18991 + CC 18992 isolés, scratch) : cerveau liste, écrit `notes/s6.md` (origin brain),
  relit ; sous-agent délégué lit la mémoire de l'ancien Board B par `jarvis-workspace` (tree, inspect, 2 read),
  active_board_id / liaison de premier plan / autorité de parole identiques avant/après. ≈ 0,33 $ (2 tours +
  1 réveil). `slices/06-jarvis-workspace-mcp/EVIDENCE.md`.
- Tests : `test_workspace_mcp` 65 (47 déplacés de `test_settings_mcp`, 18 neufs) ; settings_mcp 17, mcp_catalog 77,
  capture_mcp 14, prompt_registry 20, scene_artifacts 57, v2_brain_contracts 31, workspace_inspection_api 51,
  workspace_memory_mutations 62, tool_relevance 56, tools_gateway_mcp 67, control_center_mcp_api 54,
  control_center_mcp_inspector_js 34, integration/board_session_e2e 7 ; 144 fichiers important les modules
  touchés : verts sauf hérités (READINESS §5 : test_app 1, barehands_interaction_js 2,
  interaction_mode_hud_browser 1, brain_delegation 1 — même assertion, pas aggravé).

## 2026-10-03 — QA S04/S05, reworks, S07 branch (agent 0)

- QA S04: approve; rework `5bc45e4` (cursors bounded + bound to list kind/scope, read traces, reads never create the memory root, relay long-timeout test).
- QA S05: approve; rework `fix/bm-s5-rework` (64c59f7) cherry-picked after S06: no ledger row for a no-op case move, valid-JSON body-cap test, `origin: null` → `user`. Re-run: mutations 65, inspection 51, workspace_mcp 65 (the known intermittent switch/new-session test, now in test_workspace_mcp, failed 1/4).
- S07 implemented in parallel on `fix/bm-s7-ui` (d99d0e6, worktree `bui`, based on 5bc45e4); QA running; merge into the task branch after QA.

## 2026-10-03 — Slice 08 (implementer)

- Navigateur rapide = évolution de `#boardsHud` / `control_center_boards.js` (aucun second sélecteur) :
  badge de nature (`BOARD_KINDS`, mots du gestionnaire profond, épinglés), dernière ouverture relative
  (`last_opened_at` du serveur), filtre « En service / Archivés » (archivés sans bascule, seulement
  « Inspecter »), nature à la création (envoyée si ≠ `empty`) et à l'édition (un `PATCH` des seuls champs
  changés, badge peint après relecture). Événements `boards.rename_*` -> `boards.update_*` ; neufs
  `boards.filter_changed`, `boards.inspect_requested|failed`. Liste en un appel `?include_archived=true`.
- « Inspecter » -> `window.JarvisWorkspace.openBoard(id)` (nouveau) -> action `inspect-board` du
  gestionnaire : vue Boards, filtre Tous, ligne dépliée (jamais repliée) et focalisée une fois peinte.
  Gestionnaire absent : panneau ouvert + `workspace_manager_missing` ; rejet tardif : infusion.
- Parcours réel (Chrome + CaptureStack, aucun double) : créer « Réunion », changer la nature, filtrer
  archivés, inspecter archivé et Réunion ; Board actif inchangé. 8 captures `slices/08-quick-board-browser/evidence/`.
- Tests : boards_hud_js 28, boards_hud_browser 10, workspace_manager_js 16, workspace_manager_browser 2,
  control_center_quality 73, boards_status 5, board_alerts_js 7, board_alerts_browser 3, board_alerts 31,
  scene_renderer_logic 62, mcp_inspector_js 34, timeline_ui 13, interaction_mode_hud_browser 6.
- Non prouvé : bascule réelle entre 3 Boards (pas d'hôte d'agents dans la pile de test) ; HV-WS-UI-002 à faire.

## 2026-10-03 — QA S06/S07/S08, reworks, merges (agent 0)

- S07 merged from `fix/bm-s7-ui` (merge 6fbee84). QA S07: approve with rework; rework `fix/bm-s7-rework` (db23f9d): Actualiser re-reads everything incl. memory tree, per-part freshness « Lu à », artifacts outside the list pinned, focus returns to opener, strict allow-list, escaping tests, French translated enums with raw tooltip, confirmation placed at the row, flaky browser test root-caused (early Mémoire click before /api/boards) and fixed (21/21). Merged after S08 with conflicts resolved (both `focusBoard` and `opener` kept). Post-merge: manager js 24, hud js 28, quality 73, manager browser 2, hud browser 10.
- QA S06: approve (7/7 mutations, live trace on an archived Board: read tools only, no switch, $0.175). Rework `801c21a` cherry-picked: `board_memory_write` destructive, session dates in board_inspect, transport error codes in text, stale docs, intermittent switch/new-session test fixed (test-side race; 66×6 green), QA evidence archived, Issue `workspace-prompt-without-config.md`.
- S08 implemented (9495d0b). QA S08: approve with minor follow-ups (real A→B→A switch works in browser; 206 Boards fine; injection neutral). Rework next.
