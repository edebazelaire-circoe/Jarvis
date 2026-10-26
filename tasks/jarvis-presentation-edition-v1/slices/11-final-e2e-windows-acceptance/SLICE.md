# Slice 11 — Final Windows E2E and Human acceptance

## Goal
Run the complete V1 release journey on a clean Windows environment and produce the final evidence package deciding whether Jarvis Presentation Edition is ready for pilot distribution.

## Context
This is the integration/acceptance Slice, not a place to implement missing features. Any regression attributable to this task returns to the owning Slice. Substantial unrelated discoveries become new Slices or Issues as appropriate.

## Canonical Concepts
All contracts produced by Slices 01-10 plus repository acceptance doctrine.

## Scope
### In Scope
- clean-machine install with no developer prerequisites;
- first-run onboarding and connector setup;
- Presentation-only Board availability;
- `CONTEXT_GLOBAL` persistence;
- document/source research and allowed connectors;
- authoring, preview, editing, variants, presenting and export;
- delete/move exported copy and re-export;
- outside-write/shell denial;
- microphone/speaker/Presentation room behavior if voice is a shipping capability;
- crash/restart/update checks;
- final Human visual/usability review;
- final release evidence/status report.

### Out of Scope
- no feature expansion;
- no server architecture;
- no Mac/Linux acceptance.

## Dependencies
Hard `depends_on`: all Slices 01-10.

## Implementation Steps
1. Freeze the exact candidate commit/package/hash and dependency/license manifest.
2. Prepare clean Windows test profile/VM with Git/Python/Node/npm/FFmpeg absent from PATH.
3. Install through the real installer and record only user-visible/product logs needed for evidence.
4. Complete first-run connectors. If IGuard is unavailable because external contract was never supplied, mark that gate explicitly blocked and decide whether V1 pilot can ship without it; do not fake a pass.
5. Create Presentation Board, gather source material, use Drive/CIRCOE/IGuard as available, author a non-trivial deck, preview it, edit it, create/use a variant, present/play and export.
6. Confirm internal AppData state and `CONTEXT_GLOBAL` persist across restart.
7. Delete/move export and re-export.
8. Attempt forbidden Desktop/arbitrary path write and shell execution through the brain.
9. Exercise representative crash/recovery and update/rollback path.
10. Run physical audio/room acceptance if voice is included in the release candidate.
11. Execute Human UI/editing/install checks from the manifests; capture screenshots/evidence.
12. Produce final status: `READY_FOR_PILOT`, `BLOCKED`, or equivalent repository vocabulary, with no ambiguous unverified gate hidden.

## Files Likely Touched
Evidence/report files under the task/repository acceptance structure only unless a rework Slice is opened.

## Architecture Constraints
- do not patch product code inside final acceptance; route defects back to owners;
- use the exact packaged artifact intended for distribution;
- record environment/runtime versions needed to reproduce failures.

## Automated Validation
Re-run the full release pipeline for the frozen candidate and verify artifact hashes before Human checks.

## Acceptance Criteria
- all automated gates green or explicitly waived by an authorized Human decision;
- all required Human checks completed with evidence;
- no unrestricted write/shell capability;
- clean installation and Presentation workflow succeed;
- data survives restart/update/re-export tests;
- final status report lists every remaining blocker/waiver.

## Documentation Updates
Finalize acceptance status, release notes, installation/rollback/support instructions and known limitations.

## Handoff Notes
This Slice is primarily validation/integration. If implementation code must change, stop final acceptance and reopen/rework the owning Slice with normal QA. Human checks never replace QA.
