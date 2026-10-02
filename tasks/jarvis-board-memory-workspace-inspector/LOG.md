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
