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

## 2026-09-29 - Slice 03 (implementer)

- `jarvis/core/session_manager.py` (`SessionManager`, `JarvisCoreApplication.sessions`): Core start = new Session (open one closed `core_restart` with its bindings, new Session on the last active Board, `default` if archived/missing, foreground binding with a new Core conversation; the run that created `default` adopts the latest conversation via new `StateRepository.latest_conversation()` / `ConversationService.latest()`); `current()`, `start_new_session(expected_session_id=)` (one `commit_switch`, same active Board, Boards/jobs/mode untouched), `binding_for` (get-or-create, `suspended`, no promotion), `history(limit 1..100)`. Start order in `v2_app.start`: `boards.ensure_default()` -> `sessions.start()` -> `boards.start(ensure_default=False)`, all before the server starts.
- Routes `GET /v1/sessions/current`, `GET /v1/sessions?limit=`, `POST /v1/sessions/new` (201; 409 `session_closed` when `expected_session_id` is closed; 503 `core_unavailable` when not ready); client `current_session`, `list_sessions`, `new_session`.
- Voice: each activation reads `GET /v1/sessions/current` and uses `binding.conversation_id`; fallback to `.voice_conversation` pointer + create-on-404 only when the client lacks the method or Core answers 404; other errors raise. Pointer still written (cache). `docs/legacy/voice-conversation-pointer.md`.
- **Interim limitation (until 04a):** the Control Center CLI and the Core Session are not coupled. `/api/agent/restart {new_conversation:true}` unchanged (fresh CLI, no Session change); `POST /v1/sessions/new` opens a Session + new Core conversation without restarting the CLI. Bindings carry `agent_cli="pending"` until the pool reports it.
- Docs: `docs/boards.md` *Sessions*, `docs/ARCHITECTURE.md` voice conversation choice.
- Tests (foreground, chunked): new `test_session_manager.py` 11, `test_session_protocol.py` 13, `test_voice_session_binding.py` 8; with board_*/contract/documented_routes/interaction_mode contract+control_plane+protocol 359 passed; `test_voice_*.py` 616 passed; `test_v2_*.py` 213+123 passed; `test_live_*.py` + `test_app.py` 230 passed; integration `test_v2_*` + `test_voice_switch.py` 52 passed; conversation-event/back-brain/scene-restart/testlab-virtual/work-state 281 passed, 1 skipped.
