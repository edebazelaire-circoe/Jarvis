# Implementation strategy

## Preserve the implemented engine

The repository has moved beyond the original planning handoff. Do not restart Bare Hands V1 from scratch. The implementation should leave the mature runtime/geometry/diagnostic work intact and refactor only the presentation/integration needed by the new UI.

## Recommended rollout

1. Establish the new HUD control contract/state synchronization without removing old Settings entry points yet.
2. Move existing tools to the fixed palette and prove tool state remains synchronized.
3. Add right-click quick actions plus Help/Diagnostics surfaces; then simplify Settings.
4. Refactor calibration shell into full-screen layout without changing measurement derivation.
5. Introduce INTRO/ARMED/RUNNING phase timing and adapt steps 1–5.
6. Replace generic drag + resize steps with one real-window manipulation step containing move/resize sub-steps.
7. Remove the separate tutorial product surface and migrate any compatibility command/state.
8. Run full regression and update canonical docs.

## Migration constraints

- Preserve `OFF/SLEEP/ACTIVE` controller behavior and existing teardown guarantees.
- Preserve no-cloud/offline MediaPipe assets.
- Preserve profile privacy: derived values only by default.
- Preserve partial calibration/fallback behavior.
- Preserve recorder/replay semantics.
- Preserve existing contextual interaction and zone geometry rules.
- Preserve current command-channel verification semantics when aliasing/removing tutorial.
- Do not silently drop persisted settings from older schema versions; either retain ignored compatibility fields or perform explicit schema migration.

## Visual implementation guidance

The screenshots/concepts in the planning session are directional, not pixel-perfect specs. The durable rules are hierarchy and composition:

- no modal calibration card;
- center is exercise space;
- large calm text above;
- simple schematic hand visuals;
- atmospheric blurred Jarvis background;
- sparse chrome;
- clear success feedback;
- no early timer pressure while reading.

Use `/impeccable` for browser/frontend Slices and keep the result consistent with existing Jarvis/Omega visual tokens where possible.
