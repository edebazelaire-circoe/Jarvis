# Implementation strategy

## Preserve a working baseline

Do not rewrite the entire Control Center interaction in one patch. Extract pure modules/contracts from the current JarvisBarehandsCore style so Node-based unit tests remain cheap and deterministic.

## Suggested rollout

1. Establish contracts and schemas without changing visible behavior.
2. Introduce stable hand identity, adaptive filtering and richer intent events while preserving existing primary-click compatibility.
3. Add lifecycle/wake states.
4. Add semantic target resolver and visual preview.
5. Add capture-based interaction engine and frame zone semantics.
6. Add tools/settings surfaces.
7. Add calibration and tutorial overlays.
8. Add diagnostics/replay/benchmarks.
9. Run e2e/manual validation on real webcam interaction.

## Migration constraints

- Keep the current vendored MediaPipe asset flow and security properties.
- Preserve camera cleanup on every shutdown/error path.
- Preserve no-cloud operation.
- Preserve barehands_test_mode compatibility where practical; migrate settings with versioned defaults.
- Keep native code clean-room relative to upstream AGPL Barehands.
- Do not assume the Control Center/Constellation DOM shape is unchanged; freshness-check relevant component contracts before dispatch.

## Unknowns to resolve empirically

Exact edge/corner pixel clamps, C-wake hold time around one second, click-vs-drag thresholds, adaptive-filter constants, component APIs for star/frame semantics, and the exact voice command registration point should be discovered and tuned without changing locked behavior.
