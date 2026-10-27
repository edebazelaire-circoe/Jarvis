# Slice 08 — macOS portability and build validation

## Goal
Make the same Jarvis Presentation Edition codebase buildable and testable for macOS without requiring the primary developer to own a Mac, while refusing to claim support until real-device acceptance is complete.

## Context
Parent V1 is Windows-first. The user wants macOS execution considered now and asked how to develop it from Windows. The correct amendment is platform abstraction + CI-built/tested mac artifacts + a later real-Mac release gate, not separate product branches.

## Canonical Concepts
- installed data-root/export contracts from parent V1;
- private Python/Node/FFmpeg/Remotion packaging;
- launcher/process supervision;
- Voice/audio/wake runtime;
- platform permissions and packaging/signing contracts discovered in Slice 00.

## Scope
### In Scope
- centralize platform path resolution so internal data, `CONTEXT_GLOBAL`, working docs and exports map correctly on Windows and macOS;
- target mac internal data at `~/Library/Application Support/CIRCOE/Jarvis` unless a current canonical project contract says otherwise;
- keep `~/Documents/Jarvis` export-only;
- package private runtimes/dependencies for supported mac architectures rather than requiring system Python/Node/FFmpeg;
- add macOS CI jobs that build/install/smoke the packaged product and run a focused Presentation/Board/research suite;
- audit platform-specific process launching, file paths, symlink safety, audio devices, browser/Remotion runtime and permissions;
- document signing/notarization and microphone/accessibility/screen-capture permission requirements;
- produce a mac artifact from CI for test distribution when credentials allow;
- define a real-Mac Human acceptance gate before “supported” status.

### Out of Scope
- long-lived `mac` product branch;
- pretending CI substitutes for physical permission/audio validation;
- Linux packaging in this Slice;
- cloud hosting as a workaround for local device capabilities.

## Dependencies
- `01-presentation-product-brain-scope`;
- current storage/packaging seams must be reconciled by Slice 00 before implementation.

## Implementation Steps
1. Inventory Windows assumptions across paths, subprocesses, executable names, shell usage, FFmpeg/Node/Remotion, audio and browser launch.
2. Introduce/finish a platform adapter for logical roots and process/runtime discovery; replace scattered OS-path assumptions.
3. Define mac private-runtime/package layout for arm64 and x64 as supported by actual pinned dependencies.
4. Add CI matrix/job on macOS runners: install/package, migration/path tests, Core/Control Center smoke, Presentation compile/render smoke, Board/research tests.
5. Add bundle/package verification that no Git/system Python/system Node dependency leaks into the user path.
6. Document and, where automatable, test signing/notarization and app entitlements/permissions.
7. Produce a real-Mac validation checklist covering first launch, permissions, wake/voice, chat, research, Presentation authoring/render/export, shutdown and update/repair.

## Files Likely Touched
platform path/runtime helpers, packaging scripts/manifests, CI workflows, launcher, Remotion capability bootstrap, voice/device adapters, docs/tests.

## Architecture Constraints
- one codebase, platform adapters;
- AppData/Application Support contain canonical internal state, Documents contains exports only;
- CI artifact is not a supported release until real-device gates pass.

## Automated Validation
- unit tests for Windows/mac path mapping;
- CI build/package on macOS;
- clean-environment smoke without Git/system Python/Node;
- Remotion render smoke and Board project/research tests;
- package-content/license manifest checks;
- symlink/path boundary tests on mac filesystem semantics.

## Acceptance Criteria
The project can produce and smoke-test a macOS package from CI without the primary developer owning a Mac, and the task clearly distinguishes “CI green” from “real Mac supported”.

## Documentation Updates
Add mac packaging/development guide, platform path table, permissions/signing/notarization checklist and support gate.

## Handoff Notes
If CI provider/architecture availability differs at execution time, use current supported runners and document the exact coverage. Never infer hardware coverage from a single simulator/build success.