# Slice 05 — Open the whole variant in managed native Remotion Studio

## Goal

Make the primary presentation Remotion Studio path open the compatible variant master project, while preserving current scene-level Studio behavior and the mature process/security boundary.

## Context

Today one Studio process exists but its workspace/provider/state is keyed to one scene `StudioPin`. The user expects Studio to contain the full video project.

## Canonical Concepts

Studio target kind, master project key, managed process, explicit unsandboxed acknowledgment, unpublished workspace edits.

## Scope
### In Scope

- master target support in service/runner/provider state;
- materialize/reuse/sync a master workspace by project key;
- native Studio master composition discovery;
- health/status relation to presentation/variant;
- explicit policy for unpublished master workspace files;
- preserve scene target behavior.

### Out of Scope

- publishing arbitrary master workspace edits back to scenes;
- UI polish beyond backend state/route contract (Slice 08 owns main UI);
- new second Studio process by default.

## Dependencies

`04-master-workspace-materialization`.

## Implementation Steps

1. Refresh current Studio service/runner/state routes and tests.
2. Implement target semantics per Slice 02 without overloading `StudioPin` ambiguously.
3. Reuse current explicit ack, loopback, clean-env, CSP/guard, health, adoption, idle-stop and process identity behavior.
4. Materialize master project atomically and launch the real Studio root on the master composition/project.
5. Define same-target reuse and variant repin/project-key refresh behavior.
6. Implement unpublished master-edit detection/set-aside/refusal; never silently regenerate over user changes.
7. Keep current scene-level open/sync/publish tests green.
8. Add real Studio test/harness on isolated runtime.

## Files Likely Touched

`jarvis/domain/remotion_studio*.py`, `jarvis/core/remotion_studio_service.py`, `jarvis/adapters/remotion_studio_runner.py`, Studio protocol/client/relay, tests/harness/docs.

## Architecture Constraints

One managed process/security boundary. Master project is a target, not a second presentation product. Arbitrary master project edits are non-publishable in A+B unless a later explicit task defines mapping/version semantics.

## Automated Validation

- service state/unit tests for master target and stale project key;
- scene target regressions;
- unpublished-work negative tests;
- real `remotion studio` open on master composition;
- network/process guard tests unchanged/green;
- Core restart/adoption behavior if currently supported.

## Acceptance Criteria

The native Studio opened from a compatible Presentation Variant exposes the full project/master composition. It is no longer fundamentally tied to one selected scene for the primary master path. Existing scene Studio remains usable.

## Documentation Updates

Update `docs/remotion-studio.md` to distinguish master vs scene compatibility target, including unpublished edits and non-publishable generated files.

## Handoff Notes

Coding/runtime Slice: `/caveman` + `/coding-guideline`; QA, code-review, runtime-validation. Human check `HV-RMP-05-01` only after real automated Studio evidence.
