# Slice 06 — Whole-variant native Remotion render/export

## Goal

Render a frozen compatible variant's master composition as one verified video Artifact through the existing guarded Remotion rendering path.

## Context

Current render planning selects exactly one scene. The snapshot already contains the full variant and exact pinned sources, so A+B should add a master render plan rather than invent another export engine.

## Canonical Concepts

Frozen package, master render scope, master composition, render guard/browser, presentation_video Artifact.

## Scope
### In Scope

- explicit whole-variant/master render request semantics;
- master target resolution from frozen snapshot;
- master files/props/project generation from frozen bytes;
- render/verify/spool one MP4;
- correct duration/dimensions/fps/audio metadata;
- deduplication identity includes master project/settings;
- scene export remains available.

### Out of Scope

- replacing snapshot model;
- concatenating pre-rendered scene MP4s as the implementation;
- automatic export without explicit user intent;
- new video codec/UI matrix beyond current render contract unless required by master.

## Dependencies

`04-master-workspace-materialization`.

## Implementation Steps

1. Extend render settings/request with the additive master scope defined in Slice 02.
2. Build MasterProjectPlan from the frozen package, not live source state.
3. Plan/materialize master project files from the frozen source bytes.
4. Render the stable master Composition ID through current guarded host/browser.
5. Verify full output duration, video stream and authored audio stream using existing media tools.
6. Store one derived `presentation_video` Artifact with master-specific resolved settings/project identity and normal `rendered_from` relation.
7. Preserve queue, cancellation, restart recovery, sandbox, egress guard and disk budgets.
8. Keep scene export and its low-level caller semantics green.
9. Add MCP/client support only through the existing explicit-user export trust rules.

## Files Likely Touched

`jarvis/domain/presentation_render*.py`, `jarvis/core/presentation_render_service.py`, render ports/runner host spec as needed, protocol/client/relay, Remotion MCP export tool, tests/docs.

## Architecture Constraints

The whole export is one native master Remotion Composition from source, not clip concatenation. It renders a frozen snapshot and never reads the live variant after the job is resolved.

## Automated Validation

Real multi-scene MP4 with boundaries and audio; ffprobe verification; frozen-vs-live mutation test; dedupe; cancellation/recovery; incompatible master refusal; scene-export regression; guard/sandbox/egress regression.

## Acceptance Criteria

An explicit full-video export of a compatible multi-scene variant returns one verified Artifact whose duration/media correspond to the master composition. No `scene_id` loop is required to build the user's final video.

## Documentation Updates

Replace the absolute "one scene per export" limitation with precise scene-vs-master render contracts in `docs/remotion-render.md` and related tool docs.

## Handoff Notes

Coding/runtime/tool Slice: `/caveman` + `/coding-guideline`; QA + code-review + runtime-validation. If MCP behavior changes, include real agent/tool trace validation or coordinate with Slice 07.
