# Slice 10 — Production readiness, recovery and CI

## Goal
Turn the V1 into a reproducible release candidate by adding production health/recovery, update/data-preservation rules, CI/release artifact gates and failure testing around the packaged Windows product.

## Context
The repository has extensive automated tests and release documentation, but the latest audited `main` commit had no GitHub Actions workflow run. Current acceptance documents also retain manual hardware/workstation gates. Product release must validate the packaged artifact itself.

## Canonical Concepts
- existing release verifier and acceptance docs;
- product readiness from Slice 07;
- package/runtime manifest from Slice 06;
- repository SQLite backup/migration rules;
- global QA doctrine in this handoff.

## Scope
### In Scope
- CI workflow for focused/full tests and Windows package build;
- package artifact hashes/provenance and version metadata;
- post-build install/smoke/health validation on a clean Windows runner/VM where feasible;
- crash recovery tests for Core/Voice/Control Center/Remotion/renderer;
- interrupted install/repair/render behavior;
- update over existing AppData profile, migration and rollback documentation;
- product logs/support bundle with secret/path redaction policy;
- release checklist distinguishing automated pass, physical/manual gate and waived/non-shipping features.

### Out of Scope
- no cloud updater service;
- no fleet telemetry backend;
- no macOS/Linux CI release artifacts.

## Dependencies
Hard `depends_on`: `04-agent-confinement-capability-policy`, `06-windows-private-runtime-packaging`, `07-installer-onboarding-health`, `08-presentation-product-ui`, `09-presentation-editing-ui`.

## Implementation Steps
1. Audit current test/release scripts; fix stale verifier assumptions before adding a new pipeline.
2. Add CI stages for static/contract tests, Presentation/security suites, packaging and Windows smoke.
3. Ensure package inputs/versions/hashes are captured and release artifact is immutable/addressable by SHA.
4. Add restart/crash probes for owned child processes and verify no persistent orphan process remains.
5. Add update/migration test over a seeded real-ish AppData profile containing Boards, `CONTEXT_GLOBAL`, artifacts and a Presentation.
6. Test rollback procedure without deleting the new data root; document schema compatibility limits.
7. Add support/readiness bundle collection with bounded diagnostics and secret redaction.
8. Create a release gate table: automated green, physical Human gate, licensing/signing external prerequisites.
9. Fail the pipeline if forbidden product capabilities reappear or package runtime falls back to system PATH dependencies.

## Files Likely Touched
- `.github/workflows/*` or repository CI equivalent;
- release verifier/scripts;
- package smoke harnesses;
- health/recovery/support diagnostics;
- acceptance/release docs.

## Architecture Constraints
- CI validates the packaged artifact, not only source checkout behavior;
- update cannot silently reset AppData;
- support diagnostics must not leak credentials or room transcripts beyond existing privacy policy;
- a missing physical gate must be reported as unverified, never assumed pass.

## Automated Validation
This Slice owns the full automated release matrix. Include full regression suites appropriate to the product, package build, clean install smoke, security/confinement regression, export persistence, restart/recovery and update/migration tests.

## Acceptance Criteria
- a reproducible Windows release artifact is built from a known commit;
- CI runs and records results for the release candidate;
- packaged smoke passes without developer prerequisites;
- update/recovery preserve canonical user state;
- release status accurately separates automated evidence from remaining Human gates.

## Documentation Updates
Update `docs/ACCEPTANCE_STATUS.md`, production install/release runbook, rollback and support diagnostics docs.

## Handoff Notes
Coding/release Slice: require `/caveman`, `/coding-guideline`. QA: `qa-verification`, `code-review`, `runtime-validation`; add `agent-trace-analysis` if any agent/runtime capability code changes during rework.

## Slice 00 amendments (2026-10-26)
- E7: `.github/workflows/ci.yml` **already exists** (pytest Ubuntu 3.11-3.13 plus `scripts/verify_release.py`). Extend it with a Windows job and package build/smoke instead of creating a parallel pipeline. `ARTIFACT_INFO.json` is stale (0.1.0-rc1 versus `pyproject` 0.2.0); fix it or generate it.
