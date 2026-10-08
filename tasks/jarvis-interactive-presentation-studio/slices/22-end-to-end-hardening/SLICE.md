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


## Slice 11 carry-forward (added by Slice 11, binding for this Slice)

Slice 11 proved the authoring planner without a model (a scripted rig, `slices/11-authoring-planner-first-draft/evidence/`). The behaviour of the real model against `PLANNER_PROMPT` is **not** established there and is a release gate here, on top of Slice 21's own traces:

1. Run the end-to-end trace scenarios of Slice 21 (rich brief, missing context, linked DA, vague exploratory, one-shot report, serious deliverable, no DA found, conflicting brands, refused draft then fix, hostile text) with the real Claude brain and the real tools, and keep the redacted traces as evidence: tool calls per scenario, questions asked against the budget, rounds to a passing gate, whether the first draft is respectable (a person judges a sample; the gate only proves it is not placeholder, not dense, not unbounded).
2. Assert in the release verifier that `presentation_studio.authoring.planner` is registered, read-only and attached to the program that declares the presentation tools, and that its fingerprint is the one the evidence was gathered with.
3. Re-run the Slice 11 crash drills (`test_presentation_studio_authoring_crash.py`) in the full-suite sweep, and the privacy assertion that no draft text reaches a log (`test_presentation_studio_authoring_service.py`, `test_presentation_studio_authoring_routes.py`).
4. Carry the Slice 09 scenarios and the untrusted-title / untrusted-note line named in Slice 21's carry-forward into the final trace assertions.
