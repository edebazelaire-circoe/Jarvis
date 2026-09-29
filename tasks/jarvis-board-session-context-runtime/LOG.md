# Execution log

Implementation agents append durable execution notes here. Do not record fictional progress before work begins.

## 2026-09-29 - Slice 00 (agent 0)

- Handoff mirrored (`2a03d16`). Blind audit + design pass done; READINESS = READY. Architecture resolved in `docs/06-resolved-architecture.md`; Slice 04 split into 04a/04b; Task Type waived.
- Baseline at `202333d`: 9009 passed, 5 skipped, 11 stable failures + 1 flaky (list in READINESS B2).

## 2026-09-29 - Slice 01 (implementer)

- Pure contract `jarvis/domain/workspace_board.py` (Board, JarvisSession, BoardConversationBinding, enums, `BoardError` + 12 stable codes with HTTP status, transitions `create/update/archive/mark_opened`, `set_interaction_mode`, `adopt_legacy_interaction_mode`, `open/close_session`, `visit_board`, `new/find/promote/close_binding`, `set_lifecycle`, `record_agent_session`, `check_bindings`); strict `to_payload`/`from_payload`.
- Ports `jarvis/ports/workspace_board.py` (`BoardRepository`, `BoardBrainHost`, async, no impl). Canonical doc `docs/boards.md`; ownership table + link in `docs/ARCHITECTURE.md` (no `/api/boards` path quoted: `test_documented_routes` would fail until Slice 05 registers it).
- `context_summary` limit 1 500 chars, refused not truncated.
- Tests: `.venv/Scripts/python -m pytest -q tests/unit/test_workspace_board_contract.py tests/unit/test_documented_routes.py tests/unit/test_v2_architecture.py tests/unit/test_interaction_mode_contract.py tests/unit/test_v2_domain.py` -> 159 passed (45 new).

## 2026-09-29 - Slice 01 rework (Slice 02 implementer, from Slice 01 QA)

- Domain: refs refuse a str / non-list (`invalid_board`); `context_summary` printable + `\n`/`\t` only; `close_session` refuses end < start; `close_binding` on a closed binding is a no-op; `promote_binding(session, ...)` requires an open Session owning the target; new `close_session_with_bindings`; codes `brain_not_foreground` 409, `board_activation_failed` 502, `board_switch_rolled_back` 500.
- Port: `list_sessions(limit)`, `binding_by_conversation`, `list_live_bindings`, `insert_board_if_empty`, `BoardStoreError`; docstring says `ensure_default` belongs to `BoardService`. `docs/boards.md` updated (Codex/background_running is a 04a pool rule).
- Tests: `.venv/Scripts/python -m pytest -q tests/unit/test_workspace_board_contract.py tests/unit/test_documented_routes.py tests/unit/test_v2_architecture.py` -> 78 passed (contract 67, +22).

## 2026-09-29 - Slice 02 (implementer)

- Migration v3 (`sqlite_state._MIGRATIONS[3]`, `_SCHEMA_VERSION=3`): `work_boards`, `jarvis_sessions` (unique partial index one open), `board_conversation_bindings` (PK session+board, FKs, unique partial index one foreground). Backup `jarvis.sqlite3.v2.bak`.
- Adapter `jarvis/adapters/sqlite_workspace_board.py` (`SQLiteBoardRepository`, sibling of the event store via `run_serialized`, not methods on `SQLiteStateRepository`): strict decode + key cross-check (`BoardStoreError`), closed-Session SQL guard (`WHERE status='open'`, rowcount 0 -> `session_closed`), `commit_switch` one transaction, `insert_board_if_empty`, `list_sessions`, `binding_by_conversation`, `list_live_bindings`.
- `jarvis/core/board_service.py`: list/get/get_active/create/update/archive, `ensure_default` (keyed on empty table), mode listener (replay `startup`/`core_restart` -> adopted once as `migrated`, else re-assert Board mode; other sources -> `user`; `board_*` sources ignored), restore at start (`board_restore`, skipped when `unset`). Wired in `v2_app.py` (start before routes, drain before DB close); stale scene comment fixed.
- Active Board V1 = open Session's `active_board_id`, `default` without Session (no extra pointer table).
- Routes `GET/POST /v1/boards`, `GET /v1/boards/active`, `GET/PATCH /v1/boards/{id}`, `POST /v1/boards/{id}/archive`; `BoardError` mapped with its code/status, `BoardStoreError` -> 500 `board_store_unreadable`. Client methods added.
- Docs: `docs/boards.md` Persistence, `docs/interaction-mode.md`, `core/interaction_mode.py` docstrings, `docs/state-model.md`. Event-store schema asserts moved 2 -> 3.
- Tests (foreground, chunked): new `test_board_store_sqlite.py` 13, `test_board_service.py` 19, `test_board_protocol.py` 14; with contract/sqlite_scene/event_store/architecture 218 passed; interaction_mode (non-browser) 253 passed, browser 5 passed + 1 inherited B2 fail; test_v2_* 232+104 passed; Core-touching suites 381+330 passed; brain_delegation/display_mcp/documented_routes 92 passed + 1 inherited B2 fail.
