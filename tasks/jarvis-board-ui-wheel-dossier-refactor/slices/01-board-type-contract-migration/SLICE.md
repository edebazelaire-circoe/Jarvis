# Slice 01a — Fixed Board type contract and stored-data migration (v9)

## Goal

Make the Board's type the authoritative, immutable product type and migrate stored Boards to it without losing legacy intent. **Split by Slice 00:** this Slice owns the domain, storage, API and MCP contract of the type **and** the Core-side derivation of the live mode from it (steps 1-6, 8-9, 11-12 below: removing the Board's stored mode fields cannot land without replacing `BoardService`'s mode listener in the same change). Retiring the remaining user-facing mode writers (Control Center route and replay, global key, `settings_set`, brain prompt, Core `POST` restriction — steps 7 and 10) moved to `01b-derived-interaction-mode`.

## Slice 00 reconciliation (read first)

`../../docs/08-readiness-audit.md` §2 and §4 are the audited plan. At HEAD `board_kind`, `interaction_mode` and `interaction_mode_origin` are JSON keys of `work_boards.data` (no column), decoded strictly; `jarvis.sqlite3` is at v8. The migration is a new versioned **v9 data-only step** (no DDL change, version bumped on purpose so a v8 binary refuses the file instead of crashing on `assistant`), with snapshot `tests/schema/jarvis_state.v9.sql`, following `CLAUDE.md` › *Tout changement de schéma passe par une migration versionnée*. Real data on this PC: 3 Boards; the active « Jarvis PRESENTATION » Board is `board_kind=presentation` with a user-chosen `assistant` mode — D22 rule 1 makes it Présentation (see LOG Slice 00, human question Q1; implement rule 1 unless the Human answers otherwise).


### 01a / 01b boundary (Slice 00 rework B1)

Slice 01a removes `interaction_mode` / `interaction_mode_origin` from `Board`. Everything that reads those fields or persists them breaks in the same commit, so **all of it is 01a scope** (minimal adaptation, no product redesign):

| Reader / writer at HEAD | 01a change | Asserted by |
| --- | --- | --- |
| `jarvis/core/board_service.py`: `_on_mode_changed`, `_persist_mode`, `NON_PERSISTED_SOURCES` (l. 88), `add_listener(..., with_state=True, with_unchanged=True)` (l. 293), `restore_interaction_mode` | listener and persistence deleted; restore/switch request the mode derived from `board_kind` (sources `board_restore` / `board_switch`) | `test_board_service.py`, `test_board_switch.py` |
| `jarvis/core/interaction_mode.py:317` `add_listener(with_unchanged=...)` and the `unchanged_only` notification (l. 309-311, 358-359) | `BoardService` was the only `with_unchanged` user: remove the parameter and its branch (or keep it unused only if another caller appears; grep at implementation time) | `test_interaction_mode_control_plane.py` |
| `jarvis/runtime/tool_brain_perception.py:378` `board.interaction_mode.value` | drop the key (keep `board_kind`) | `test_tool_brain_perception.py` |
| `jarvis/runtime/control_center.py:2750-2836` `_board_stored_mode`, `_core_boards_own_interaction_mode` (and callers l. 2680, 2841, 4165) | `_board_stored_mode` derives the displayed stored mode from the Board's `board_kind` (one shared domain mapping, no second table); `_core_boards_own_interaction_mode` answers `True` for any valid active Board (no origin check), so the replay is retired from 01a on and no `interaction.mode.board_unknown` / `invalid_board_snapshot` warning fires on a contract-valid v9 Board | `test_interaction_mode_control_plane.py`, `test_control_center_presentation_status.py` |

**Accepted intermediate state between 01a and 01b (asserted by tests in 01a):** no Board stores a mode any more (no stored divergence possible); the replay code still exists but never runs (Boards always own the mode); `POST /api/interaction-mode`, `POST /v1/interaction-mode` (any source), `settings_set("interaction_mode")` and the HUD chooser can still change the **live** mode until the next switch or Core restart, which re-apply the Board-derived mode. 01a adds a test that a live change through these paths is neither persisted nor survives a switch/restart. 01b closes the live divergence.

## Dependencies

- `00-project-manager` = READY

## Canonical context

At planning time `docs/boards.md` made `board_kind` (`empty|meeting|presentation`) independent from `interaction_mode`, and `docs/interaction-mode.md` persisted a mutable per-Board behaviour choice. That is now intentionally superseded by locked decisions D01–D03.

## Scope / implementation steps

1. Re-read current `Board`, `BoardKind`, Board persistence/store, Board routes/MCP, `InteractionModeService`, Board switch transaction, Presentation policy/Voice observers and tests.
2. Evolve the existing Board-kind/type vocabulary rather than adding a duplicate domain axis unless current HEAD makes reuse unsafe.
3. Target new canonical user-facing semantics: Assistant / Présentation / Réunion. Prefer stored values `assistant|presentation|meeting`; support legacy `empty` only as migration/compatibility input.
4. Implement an idempotent legacy normalization consistent with `docs/01-decision-log.md` D22 after validating real payloads:
   - explicit presentation/meeting kind wins;
   - legacy empty plus explicit non-default stored interaction mode may seed the type once;
   - otherwise empty/missing becomes Assistant.
5. New Board creation requires/derives one type; legacy clients omitting the field may safely default to Assistant if compatibility requires it.
6. Normal Board update no longer changes type. Remove it from ordinary editable fields/routes/MCP updates or return a stable explicit refusal. Migration/admin repair must be separate if needed.
7. *(moved to Slice 01b)* Retire legacy global interaction-mode replay as an authority over Board behaviour. In this Slice the replay must merely become harmless: `BoardService` no longer adopts or stores anything, and re-applies the Board-derived mode after any replay.
8. Derive effective product behaviour from active Board type (`../../docs/08-readiness-audit.md` §4, Slice 01b plan items 1-2 are implemented **here**: `BoardService` sets the `InteractionModeService` baseline from the kind at Core start and on switch; the persistence listener `_persist_mode` / `with_unchanged` / `NON_PERSISTED_SOURCES` path is deleted). If existing Presentation runtime still consumes `InteractionMode`, drive that internal service from Board activation/type only; it is no longer separately persisted/user-selected truth.
9. Meeting: do not invent a full runtime. Ensure a Meeting Board can remain a valid/openable Board; expose planned/unavailable behaviour explicitly and use the existing safest deterministic fallback if dedicated meeting behaviour is not implemented. Do not roll the Board switch back merely because a legacy mode setter refuses `meeting`.
10. *(moved to Slice 01b)* Remove/disable ordinary user mutation route semantics for `/api/interaction-mode` after all internal callers migrate. If a compatibility endpoint remains temporarily, it must not create divergence from Board type and must be documented deprecated/derived.
11. Update README and canonical `docs/boards.md` (and the *Persistence owner* part of `docs/interaction-mode.md`) in the same change. Remove contradictory old statements rather than appending a second story.
12. Add migration fixtures/tests for legacy payload combinations and restart/switch behaviour.

## Out of scope

- Building dedicated Réunion live behaviour.
- Visual wheel/Board switcher work (later Slices).
- Changing voice architecture or speaker authorization axes.

## Files likely touched (verified at HEAD 2fb66040)

- `jarvis/domain/workspace_board.py` (`BoardKind`, `DEFAULT_BOARD_KIND`, `Board` fields, `from_payload`, `update_board`, `EDITABLE_FIELDS`/`parse_board_edits`)
- `jarvis/adapters/sqlite_state.py` (`_MIGRATIONS[9]`, `_SCHEMA_VERSION = 9`) + `tests/schema/jarvis_state.v9.sql`
- `jarvis/adapters/sqlite_workspace_board.py` (only if the cross-check changes)
- `jarvis/core/board_service.py` (create/update paths, mode listener and persistence deleted, restore/switch derivation)
- `jarvis/core/interaction_mode.py` (`with_unchanged`), `jarvis/runtime/control_center.py` (`_board_stored_mode`, `_core_boards_own_interaction_mode`), `jarvis/runtime/tool_brain_perception.py:378` (see boundary table)
- `jarvis/adapters/sqlite_state.py:38-40` comment « Additive only » and `docs/conversation-events.md` (schema-version paragraph near l. 2244, « forward-only, additive »): v9 is the **first data-rewriting migration**; update the contract text to say migrations are forward-only, one transaction per step, may rewrite JSON payloads when a version bump protects older binaries, and always run after the `.v<N>.bak` copy
- `jarvis/protocol/server.py` / `jarvis/protocol/client.py` (Board routes), `jarvis/runtime/workspace_boards.py`, `jarvis/runtime/workspace_mcp.py` (`board_create`, `board_update`)
- readers of `board_kind`: `jarvis/domain/brain_context.py` (`board_kind: str = "empty"`, « Nature » line), `jarvis/runtime/board_brief.py`, `jarvis/runtime/tool_brain_choices.py:218`, `jarvis/runtime/tool_brain_perception.py:374`, `jarvis/runtime/control_center_boards.js` (`BOARD_KINDS` labels, `empty` default — UI rework itself is Slice 02), `jarvis/runtime/control_center_workspace.js`
- `docs/boards.md` (*Board kind*, *Persistence*, *Core routes*, *MCP tools*), `docs/mcp/tool-contract.md` §10.9/§10.12, `README.md`
- tests: `test_workspace_board_contract.py`, `test_board_store_sqlite.py`, `test_board_service.py`, `test_board_protocol.py`, `test_board_switch.py`, `test_board_memory_contract.py`, `test_board_memory_hydration.py`, `test_board_context_and_host.py`, `test_boards_status.py`, `test_workspace_inspection_api.py`, `test_workspace_mcp.py`, `test_mcp_catalog.py`, `test_schema_migrations.py` (+ new legacy-payload migration test), `tests/integration/test_board_workspace_e2e.py`, `tests/integration/test_board_session_e2e.py`

## Architecture constraints

- One canonical Board type; no second user truth.
- Preserve Board switch atomicity, speech authority and background work guarantees.
- Stored legacy data must not silently lose an intentional Presentation/Meeting choice.
- Migration is idempotent and observable through diagnostics/tests.
- No optimistic UI concerns belong here.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation` using isolated data roots with migrated legacy fixtures (a copy of a v8 file, never the live DB)
- `agent-trace-analysis` (MCP `board_create`/`board_update` contract changes)
- Board domain/store/service/protocol/switch/session E2E regression
- interaction-mode tests updated to the derived/compatibility contract

## Acceptance criteria

- New Board has exactly one fixed type.
- Ordinary update cannot mutate type.
- Active behaviour is derived from active Board type.
- No stored divergence: no Board payload carries a mode, and nothing persists a mode (01a). The live divergence still possible through the legacy write paths until 01b is bounded: it is never persisted and is undone by the next switch or Core restart (tested). 01b closes it.
- Legacy Board migration matrix passes.
- Presentation Boards retain Presentation intent across restart/switch.
- Meeting Board remains a valid Board without pretending meeting behaviour exists.
- Canonical docs no longer teach the rejected independent mode model.

## Documentation updates

Required: `docs/boards.md`, `docs/interaction-mode.md`, README, migration/rollback notes and any affected architecture pages.
