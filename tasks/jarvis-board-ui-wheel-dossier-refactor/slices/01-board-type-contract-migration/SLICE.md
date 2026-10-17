# Slice 01 — Fixed Board type contract and interaction-mode migration

## Goal

Make the Board's type the authoritative product behaviour input and retire the independent user-mutable interaction-mode axis without losing legacy Board intent.

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
7. Retire legacy global interaction-mode replay as an authority over Board behaviour.
8. Derive effective product behaviour from active Board type. If existing Presentation runtime still consumes `InteractionMode`, drive that internal service from Board activation/type only; it is no longer separately persisted/user-selected truth.
9. Meeting: do not invent a full runtime. Ensure a Meeting Board can remain a valid/openable Board; expose planned/unavailable behaviour explicitly and use the existing safest deterministic fallback if dedicated meeting behaviour is not implemented. Do not roll the Board switch back merely because a legacy mode setter refuses `meeting`.
10. Remove/disable ordinary user mutation route semantics for `/api/interaction-mode` after all internal callers migrate. If a compatibility endpoint remains temporarily, it must not create divergence from Board type and must be documented deprecated/derived.
11. Update README and canonical `docs/boards.md` / `docs/interaction-mode.md` in the same change. Remove contradictory old statements rather than appending a second story.
12. Add migration fixtures/tests for legacy payload combinations and restart/switch behaviour.

## Out of scope

- Building dedicated Réunion live behaviour.
- Visual wheel/Board switcher work (later Slices).
- Changing voice architecture or speaker authorization axes.

## Files likely touched

Verify at HEAD, likely:

- `jarvis/domain/workspace_board.py`
- `jarvis/adapters/sqlite_workspace_board.py`
- `jarvis/core/board_service.py`
- `jarvis/core/interaction_mode.py`
- Board/protocol parsing and workspace MCP/update surfaces
- runtime interaction-mode settings/observer compatibility seams
- `docs/boards.md`, `docs/interaction-mode.md`, `README.md`
- relevant Board/interaction-mode tests

## Architecture constraints

- One canonical Board type; no second user truth.
- Preserve Board switch atomicity, speech authority and background work guarantees.
- Stored legacy data must not silently lose an intentional Presentation/Meeting choice.
- Migration is idempotent and observable through diagnostics/tests.
- No optimistic UI concerns belong here.

## Automated validation

- `qa-verification`
- `code-review`
- `runtime-validation` using isolated data roots with migrated legacy fixtures
- Board domain/store/service/protocol/switch/session E2E regression
- interaction-mode tests updated to the derived/compatibility contract

## Acceptance criteria

- New Board has exactly one fixed type.
- Ordinary update cannot mutate type.
- Active behaviour is derived from active Board type.
- No user operation can create `Board type = X` and independent `interaction mode = Y` divergence.
- Legacy Board migration matrix passes.
- Presentation Boards retain Presentation intent across restart/switch.
- Meeting Board remains a valid Board without pretending meeting behaviour exists.
- Canonical docs no longer teach the rejected independent mode model.

## Documentation updates

Required: `docs/boards.md`, `docs/interaction-mode.md`, README, migration/rollback notes and any affected architecture pages.
