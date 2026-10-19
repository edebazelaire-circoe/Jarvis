# 03 — Implementation strategy

## Sequence

1. **Readiness first.** Re-audit HEAD, active Drive tasks, actual shell contracts and Task Type vocabulary.
2. **Fix the product contract before the UI.** Convert Board type from metadata + independent interaction mode into the authoritative product type. Preserve legacy data deliberately.
3. **Remove obsolete chrome and move Board navigation.** Do not leave duplicate selectors behind.
4. **Refactor/redesign the wheel.** Preserve mature input/reducer behaviour while replacing primary categories and visuals.
5. **Migrate runtime/capture controls into the new categories.** Core remains truth.
6. **Define Dossier projection/semantic operations.** Reuse Board memory + Artifacts; add missing service/API seams only after audit.
7. **Wire selection actions.** Use existing atomic scene selection for hide/representation/archive; route Ranger through Dossier durability first.
8. **Build the full-screen Dossier UI and voice/manual navigation.** Human-first default, advanced technical view secondary.
9. **Run integrated regression/accessibility/trace validation.** Test the system, not isolated screenshots.
10. **Human acceptance after machine QA.** Compare against both reference images and human-intent audit.

## Refactor-first rules

- Prefer moving/reusing `control_center_boards.js` behaviour over introducing another Board client.
- Prefer evolving `control_center_tool_wheel.js` over replacing its tested multi-input reducer unless audit finds a structural blocker.
- Keep `CaptureService` and existing capture controller as truth; change presentation, not ownership.
- Use `SceneSelection`/atomic commands for bulk selection operations.
- Reuse Workspace memory/artifact APIs where they fit Dossier; do not expose the existing technical manager as the final human UX.
- Remove old routes/modules from page composition once replaced; dead-but-loaded UI is not an acceptable migration state.

## Compatibility / rollout

Board-type migration is the highest-risk semantic change. Before code:

- inventory persisted legacy values;
- identify whether `board_kind` lives in JSON or schema columns at current HEAD;
- identify all `interaction_mode` readers/writers, global replay and mode-switch rollback paths;
- decide whether compatibility reads are needed for older stored data;
- ensure an old Board does not silently change intent.

Prefer an idempotent migration/normalization with explicit diagnostics and regression fixtures covering old payloads.

## UI implementation principles

- Real backend state only; no optimistic active recording, Board, or runtime state.
- One clear active location per global function.
- No permanent chrome for an action that is only occasionally relevant.
- Decorative sci-fi details remain subordinate to hit areas, contrast, text and available Board workspace.
- Pointer, keyboard and Bare Hands should use the same semantic activation path.
- Reduced-motion mode preserves spatial hierarchy without glow/rotation dependence.
- Unknown/unavailable/refused states are visible and distinct from “off”.

## Evidence expectations

For visual Slices, store browser screenshots in the Slice evidence folder during implementation:

- wheel closed;
- each primary wheel category selected (at minimum JARVIS, Dossier, Capture);
- proof that only one submenu is visible;
- Board switcher closed/open/create flow;
- active audio, active video, simultaneous recording indicators;
- Dossier home/tree/viewer, multi-document view and advanced metadata collapsed/expanded;
- representative 1440×900, 1280×720, 900×600 and narrow layout evidence.

Do not commit generated reference images as proof of implementation. Runtime screenshots must come from the actual Control Center.
