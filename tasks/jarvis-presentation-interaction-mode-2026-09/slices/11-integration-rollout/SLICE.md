# Slice 11 - End-to-end integration, diagnostics, latency, privacy, and rollout

## Goal
Prove Presentation works as one coherent product without regressing Simple, voice architectures, Scene, wake controls or privacy/security boundaries.

## Context
Feature crosses audio ownership, voice composition, Core state, sub-agents, Scene, Control Center UI, prompts, notifications and latency. Final acceptance requires automated and workstation evidence.

## Canonical Concepts
All prior Slice contracts.

## Scope
### In Scope
- E2E Simple default and Presentation activation/deactivation.
- Matrix across every currently supported voice architecture capable of Presentation.
- Continuous ambient + speculative + explicit priority scenario.
- Visual-only command, knowledge question voice+visual, contradiction alert.
- Scene unavailable degradation; wake unavailable/manual fallback; restart reconciliation.
- Privacy review: no raw audio persistence; working-set lifecycle; trace boundaries.
- Performance/cost diagnostics: queue lag, backlog, speculative jobs, trigger latency.
- Docs/operator runbook.
- Real workstation validation with mic/speakers/key/wake when available.
### Out of Scope
Meeting implementation; personalized interruption settings.

## Dependencies
Slices 03, 06, 07, 08, 09, 10.

## Implementation Steps
1. Load `/caveman` and `/coding-guideline`; `/impeccable` for final UI changes and Claude routing when supported.
2. Run full relevant regressions/release gates.
3. Add deterministic Presentation integration fixture for slow ambient load.
4. Capture agent trace evidence for ambient delegation, fact-check, resource reuse and priority behavior.
5. Validate every supported architecture or mark precise blocker; do not silently make Presentation architecture-specific.
6. Run workstation human checks after machine QA.
7. Update README/ARCHITECTURE/OPERATIONS/ACCEPTANCE.
8. Record remaining real limitations separately.

## Files Likely Touched
Integration tests/fixtures; `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, `docs/ACCEPTANCE_STATUS.md`, release verifier if warranted.

## Architecture Constraints
Simple remains default; Presentation is mode not architecture fork; no false claims of workstation validation.

## Automated Validation
Full targeted matrix from testing doc; release verifier; new E2E/latency/backlog tests; `agent-trace-analysis` with real trace evidence.

## Acceptance Criteria
Automated gates pass or pre-existing failures separated; Simple unchanged by default; Presentation listens/prepares, prioritizes explicit commands, stays quiet for visual commands, speaks usefully for questions, signals contradictions discreetly; no duplicate mic; no raw audio persistence; human results recorded accurately.

## Documentation Updates
Bring interaction mode, Presentation architecture, operations, diagnostics and acceptance status to required levels.

## Handoff Notes
Do not mark fully accepted without listed human checks.
