# Testing and quality

## Automated test layers

### Pure JS / Node

Extend tests/unit/test_barehands_pointer_js.py or split into focused suites for stable track IDs, primary/secondary pinch hysteresis, C wake progression, temporal gestures, adaptive filtering, capture latch semantics, BODY vs edge/corner resolution, zone conflict decomposition, one-hand move/two-hand resize math, independent two-object interactions, RESIZE -> MOVE rebasing, minimum-size clamps/no inversion, calibration derivation, and fallback behavior.

### Python/server/settings

Extend tests/unit/test_barehands_test_mode.py for versioned settings/profile schema, default compatibility, strict payload validation, asset whitelist and lifecycle/state exposure.

### Browser/runtime

Validate real DOM candidate resolution, overlays, colors, target-feedback toggle, tool palette, calibration/tutorial flows, voice-trigger hooks where test harnesses permit, and unique/stable pointer identities if compatibility DOM events are emitted.

### Manual real-webcam checks

After machine QA passes, a human must verify wake C gesture, click accuracy, right-click distinction, one-hand frame move, two-hand constraints, no-jump release, simultaneous two-object interactions, calibration improvement and tutorial clarity.

## Benchmark metrics

Expose click target success rate, median/percentile pointer error, stationary jitter, false primary/secondary pinch events per minute, gesture false positives, interaction latency, hand-loss recovery, drag continuity and two-hand resize stability.

## QA doctrine

Every implemented Slice gets qa-verification. Code changes add code-review. User-visible/runtime changes add runtime-validation. Agent/tool/routing changes add agent-trace-analysis with real evidence. Current-Slice regressions are blocking.
