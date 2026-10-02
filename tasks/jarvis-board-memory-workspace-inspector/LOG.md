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
