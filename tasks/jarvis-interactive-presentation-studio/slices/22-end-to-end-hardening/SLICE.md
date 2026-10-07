# Slice 22 - End-to-End Hardening and Release Gates

## Goal
Prove the entire Presentation Studio as one coherent product workflow and close integration/regression gaps.

## Context
The value is in the continuous experience: research/brief -> strong first draft -> edit -> branch/compare -> rehearse -> fullscreen present -> detour/resume -> reusable extraction.

## Canonical Concepts
End-to-end presentation project, release gate, runtime validation, physical acceptance.

## Scope
### In Scope
- Full deterministic E2E scenarios across all major workflows.
- Performance/leak checks for repeated scene reload and variant previews.
- Crash/restart recovery.
- Fullscreen restore.
- Ambient cue safety under adversarial speech.
- SIMPLE/PRESENTATION regressions.
- Documentation/runbook completion.
- Physical human checks after machine validation.

### Out of Scope
- New feature design discovered during final polish unless it blocks a locked requirement.

## Dependencies
All behavior/UI Slices listed above.

## Implementation Steps
1. Build representative fixture presentation with real scenes, DA, score and variants.
2. Execute one-shot report flow.
3. Execute serious authoring + live edit + variant + rehearsal + user-presenter flow.
4. Execute Jarvis-presenter locked-sequence flow.
5. Execute compare/mix + promotion flow.
6. Inject compile errors, stale IDs, restart, cue ambiguity and auxiliary detours.
7. Run complete repository release/test gates.
8. Perform final workstation Human checks only after all machine findings are clear.

## Files Likely Touched
E2E/integration tests, fixtures, final docs and narrowly scoped fixes.

## Architecture Constraints
Do not waive failed regression gates for demo quality. Failures caused by this task are blocking.

## Automated Validation
Full unit/integration/E2E suite, release verifier, trace assertions, privacy assertions, leak/resource cleanup checks.

## Acceptance Criteria
A fresh operator can create, edit, rehearse and present a real deck end-to-end with no architecture-specific manual repair.

## Documentation Updates
Final implementation report, operations/runbook, acceptance status, canonical contract index.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; frontend fixes use `/impeccable` and Claude when supported.
