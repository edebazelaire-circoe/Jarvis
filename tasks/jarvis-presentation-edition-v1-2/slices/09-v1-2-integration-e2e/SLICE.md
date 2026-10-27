# Slice 09 — V1.2 integration and end-to-end acceptance

## Goal
Prove the V1.2 amendments work together on the actual packaged Presentation Edition and do not regress parent V1 productionization guarantees.

## Context
The amendments span agent policy, persistence, research, Voice, UI, diagnostics and platform packaging. Individual tests are insufficient if their integration changes the user experience or security boundary.

## Canonical Concepts
All contracts from Slices 01–08 plus parent V1 storage/export/confinement/installer/release gates.

## Scope
### In Scope
- run whole-product Windows E2E on the exact packaged artifact;
- run macOS CI package E2E and real-Mac acceptance when hardware/credentials are available;
- verify Board project continuity, background research, research-document reuse, Presentation production, Voice/chat lifecycle, full Settings and diagnostic reporting in one realistic workflow;
- verify product capability refusals under real agent runtime;
- collect release evidence, traces, screenshots and diagnostic bundle examples;
- reconcile any parent V1 acceptance matrix impacted by these amendments.

### Out of Scope
- new features found during validation unless they are regressions/blockers; substantial new work becomes a new Slice.

## Dependencies
- `01-presentation-product-brain-scope`;
- `02-board-project-continuity`;
- `03-research-reuse-freshness-orchestration`;
- `04-research-documents-and-dossier`;
- `05-voice-lifecycle-wake-chat`;
- `06-settings-and-novice-ui`;
- `07-bug-report-diagnostic-bundle`;
- `08-macos-portability-build-validation`.

## Implementation Steps
1. Build the exact distributable candidate from a clean commit.
2. On clean Windows install: launch -> Sleep, create/resume Presentation project, continue via voice/chat, run background research, create durable research doc, author/edit/render/export presentation, use Mail/Calendar/Drive/IGuard where configured, restart and resume project.
3. Attempt prohibited developer actions and verify capability refusals with traces.
4. Trigger a controlled failure and create/send/save a diagnostic bundle; inspect contents and secret scan.
5. Verify all Settings/transcription controls remain reachable after novice-UI simplification.
6. Run update/restart/crash-recovery scenarios inherited from parent V1.
7. Run mac CI candidate; when real Mac is available, execute `HV-V12-MAC-01` before support declaration.
8. Assemble evidence and Project Manager verdict. Regressions block release.

## Files Likely Touched
Tests/evidence/release docs only unless failures require returning to an implementation Slice.

## Architecture Constraints
Validate the exact packaged artifact, not a developer checkout pretending to be the release.

## Automated Validation
- full relevant unit/integration suites;
- packaged Windows smoke/E2E;
- security/refusal tests;
- real agent trace analysis;
- diagnostic ZIP secret scan;
- macOS CI package smoke;
- release manifest/checksum/signature checks where configured.

## Acceptance Criteria
All V1.2 behavior is proven on the candidate artifact, no introduced regression remains, and every unresolved platform/support limitation is explicit rather than hidden.

## Documentation Updates
Finalize release/acceptance evidence, known limitations and support matrix.

## Handoff Notes
Human acceptance is the last layer, never a substitute for QA. The Project Manager owns the final release recommendation.