# Slice 03 — Internal documents and explicit export boundary

## Goal
Make AppData-owned internal storage the only canonical location for Jarvis-created working documents, while defining `%USERPROFILE%\Documents\Jarvis` as an explicit export-only destination.

## Context
The product must not use `Documents\Jarvis` as a general workspace. Presentation sources, generated code, assets, briefs, drafts and artifacts remain internal. Exported PDF/PPTX/MP4/etc. files are user-facing copies, not source-of-truth state.

## Canonical Concepts
- Presentation canonical storage: `docs/presentation-studio.md`, Remotion master/source docs;
- Artifact payloads: `docs/artifacts.md`;
- Board memory/Context workspaces: existing dedicated contracts;
- new product export contract owned by this Slice.

## Scope
### In Scope
- inventory all code paths that write presentation/doc/media outputs to filesystem locations;
- define internal-document ownership under product AppData;
- add a bounded export service/API capable of exporting to default `Documents\Jarvis` and, if already supported safely, an explicit user-selected destination;
- ensure export performs copy/render from canonical state and never moves canonical state;
- define naming/collision behavior and typed failures;
- surface export destination metadata without storing absolute exported paths as canonical dependencies;
- enforce path/junction/symlink safety for export roots;
- make export an explicit user action/capability.

### Out of Scope
- no arbitrary filesystem write tool;
- no Drive sync of canonical state;
- no automatic mirroring of every generated document into Documents.

## Dependencies
Hard `depends_on`: `02-windows-data-root-context-global`.

## Implementation Steps
1. Map internal presentation/document/artifact writes and identify any current user-visible output paths.
2. Write a dedicated export contract: canonical internal source, allowed default root, optional explicit destination, copy semantics, collision policy, audit/result payload.
3. Add platform export-root resolver for `%USERPROFILE%\Documents\Jarvis` (prefer OS-known Documents folder API if repository conventions support it; do not hardcode a localized folder name if avoidable).
4. Implement export through a bounded service/port rather than giving the agent a generic file path write primitive.
5. Ensure presentation render/export services write internal render intermediates under AppData, then copy final output on explicit export.
6. Add deletion/move test: remove exported file, then reopen/re-render/re-export the canonical presentation successfully.
7. Add escape/refusal tests for `..`, drive roots, junctions/symlinks/reparse points and forbidden destinations.
8. Expose the export capability to UI/agent only after its bounds are enforceable.
9. Document which file classes are internal vs exported.

## Files Likely Touched
- presentation render/output service/domain modules;
- new export port/service/platform path module;
- Control Center export relay/actions;
- tests around render/export/storage;
- new `docs/export.md` or equivalent canonical contract plus Presentation docs.

## Architecture Constraints
- export path is not canonical presentation state;
- internal files remain under AppData;
- no generic write-anywhere API;
- an exported file can disappear without corrupting Jarvis;
- connector/export destinations are explicit capabilities, not ambient filesystem authority.

## Automated Validation
- unit tests for export path policy/collisions;
- integration tests for PDF/video/presentation output classes already supported;
- delete-export-and-reexport test;
- path escape/junction/symlink tests;
- regression test proving internal authoring does not emit files into Documents automatically.

## Acceptance Criteria
- no working document appears in `Documents\Jarvis` without explicit export;
- explicit export creates a user file successfully;
- deletion/move/rename of the exported copy does not damage the internal presentation;
- the agent cannot repurpose export as a generic write-to-desktop primitive.

## Documentation Updates
Create a Level 3 internal-vs-export contract and link it from Presentation/storage docs.

## Handoff Notes
Coding Slice: `/caveman`, `/coding-guideline`. QA: `qa-verification`, `code-review`, `runtime-validation`.

## Slice 00 amendments (2026-10-26)
- E8: the existing output classes are MP4, PNG still and image-only PDF (`docs/remotion-render.md:27`). Final derivatives are Artifacts (`jarvis/domain/presentation_artifacts.py:77-81`). There is no PPTX and no Documents destination today. Today a user gets files only as a stream from the Control Center relay. The export contract covers the existing classes; PPTX stays out of V1 unless the Human decides otherwise.
