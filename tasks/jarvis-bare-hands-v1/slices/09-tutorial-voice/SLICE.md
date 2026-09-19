# Slice 09 — Implement tutorial overlay and voice entry points

## Goal

Teach the V1 interaction vocabulary in a guided flow and expose Bare Hands activation/calibration/tutorial actions through Jarvis's existing voice architecture.

## Context

This Slice is part of Bare Hands V1. Preserve the locked decisions in docs/01-decision-log.md and the clean-room licensing boundary.

## Canonical Concepts

- Bare Hands V1 architecture/contracts
- calibration profile versus tutorial state
- derived parameters only by default
- existing Jarvis voice-command and UI architecture discovered by Slice 00

## Scope

### In Scope

- Reuse the calibration overlay shell but maintain a distinct tutorial state/data path.
- Guided steps for activation/wake, target preview, primary click, secondary/right click, contextual BODY drag/scroll, star/object drag, frame edge/corner move, bimanual resize, Tools and exit.
- UI entry from Bare Hands Settings.
- Voice entry points through the current Jarvis voice command architecture for activate/deactivate Bare Hands, launch calibration, launch tutorial and exit the overlay.
- Voice/UI actions must call the same underlying runtime commands rather than parallel implementations.
- Tutorial must never write calibration parameters.
- Always provide obvious X/Esc/voice exit paths.

### Out of Scope

- system-wide third-party application control
- specialized hardware tracker implementation
- personalized neural-model training
- continuous self-learning
- copying AGPL upstream Barehands implementation into native Jarvis

## Dependencies

06, 07, 08

## Implementation Steps

1. Load /caveman and /coding-guideline; for browser/frontend work also load /impeccable and use Claude routing when supported.
2. Freshness-check current settings, overlay and voice-command integration points.
3. Implement explicit state/data separation and deterministic tests before webcam/manual checks.
4. Preserve privacy defaults, camera cleanup and offline operation.
5. Record durable discoveries/corrections in LOG.md.

## Files Likely Touched

- tutorial/overlay UI
- current Jarvis voice command/router integration discovered by Slice 00
- Bare Hands controller/settings
- browser/unit/trace tests

## Architecture Constraints

- Calibration may modify only the explicit profile after user-run calibration.
- Tutorial must never mutate calibration.
- No raw images/video are retained by default.
- Current repository APIs must be discovered rather than invented.

## Automated Validation

Tutorial-state tests prove no calibration writes; UI/voice commands converge on identical runtime actions; exit paths work from every step; invalid/inapplicable voice actions fail safely; if voice routing changes agent/tool runtime, add agent-trace-analysis evidence.

## Acceptance Criteria

Calibration and tutorial can be launched from UI and voice; tutorial covers the V1 vocabulary without modifying the profile; users cannot become trapped in the overlay.

## Documentation Updates

Document tutorial step contract, supported voice intents/phrases, runtime action mapping and exit behavior.

## Handoff Notes

Baseline qa-verification is mandatory. Add code-review and runtime-validation as applicable. Regressions introduced by this Slice are blocking.
