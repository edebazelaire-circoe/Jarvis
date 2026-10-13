# Slice 09 — Integrated release and Human acceptance

## Goal

Prove A+B end to end without destabilizing the current Remotion/presentation system, finish canonical docs, and prepare Human acceptance with evidence.

## Context

Success is not just "master render works". The old path must still work, the new path must be truly source-level Remotion, and voice regeneration must be credible.

## Canonical Concepts

Master project, compatibility lane, scene legacy lane, Studio target, whole-video Artifact, voice re-edit.

## Scope
### In Scope

- complete dependency-aware regression table;
- real isolated master Studio journey;
- real whole-video render with audio/video and boundary evidence;
- real voice/text create-edit-reexport trace;
- old-path scene Studio/player/render regression;
- failure injection and privacy/security checks;
- final docs/retirement map (nothing retired unless actually safe);
- Human checklist/evidence package.

### Out of Scope

- implementing phase C during release;
- waiving known regressions;
- touching live user data to get evidence.

## Dependencies

`05-remotion-studio-master-project`, `06-whole-variant-render-export`, `07-voice-generation-and-reedit`, `08-variants-master-entrypoints`.

## Implementation Steps

1. Re-run all release-critical directly affected tests in isolated environment.
2. Run a representative compatible multi-scene deck: open master Studio, inspect master composition, render whole MP4, verify audio/video/duration/boundaries.
3. Run create -> export -> user edit -> re-export real agent trace.
4. Run incompatible legacy deck and confirm current Variants path still works with a clear master refusal.
5. Inject Studio/render/Core failures and unpublished master workspace edits; verify no canonical data corruption.
6. Re-run scene-level Studio publish, scene export and current Variants playback regressions.
7. Perform security/privacy sweep: no secrets/paths in Studio/render responses/evidence; guards unchanged unless explicitly reviewed.
8. Update canonical docs to final Level 3 reality and write a release report with known limits.
9. Prepare Human checks only after all machine-detectable findings are cleared.

## Files Likely Touched

Release tests/harness/evidence, canonical docs, this Slice report/material, bug fixes only via PM-directed rework/new Slice rather than ad hoc release hacking.

## Architecture Constraints

A+B completion does not authorize deleting the current Player or making master workspace canonical. Any such proposal becomes a new task.

## Automated Validation

Full required matrix from `docs/04-testing-and-quality.md`; old-task release-critical regression subset; real runtime/browser/ffprobe; agent trace analysis; documentation parity tests.

## Acceptance Criteria

- master Studio opens the full compatible project;
- one whole-video Artifact renders from source with expected audio/video/duration;
- voice create/edit/re-export works without Studio;
- incompatible legacy variant fails master readiness explicitly and still works on current path;
- no task-caused regression remains open;
- docs accurately separate master Remotion Composition from the compatibility composition clock;
- rollback/data behavior is documented.

## Documentation Updates

Finalize architecture, Studio, render, authoring, operations and tool contracts. Record any deferred phase-C items as future work, not as partially implemented behavior.

## Handoff Notes

Release/QA coordination Slice. Resolve task type at dispatch; coding fixes discovered here should normally be sent back to the owning Slice or split into a new focused Slice. Human check `HV-RMP-09-01` is final product acceptance after machine gates.
