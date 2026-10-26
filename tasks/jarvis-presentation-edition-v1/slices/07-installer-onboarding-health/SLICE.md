# Slice 07 — Installer, first-run onboarding and product health

## Goal
Provide the one-button Windows installation and guided first-run flow that provisions Jarvis Presentation Edition, connects required services, validates dependencies and presents actionable repair states instead of developer commands.

## Context
Current setup is developer-oriented. Product health currently checks only a subset of runtime requirements. The V1 user should install Jarvis, launch it, connect services, and see whether Presentation is ready without understanding Python/npm/MCP.

## Canonical Concepts
- product package/runtime manifest from Slice 06;
- installed AppData root from Slice 02;
- connector statuses from Slice 05;
- existing `jarvis/runtime/health.py` and local-capability health;
- Settings visual system already on `main`.

## Scope
### In Scope
- Windows installer that lays down product binaries/private runtimes and preserves AppData on update/uninstall according to policy;
- launcher/service startup composition for Core/Voice/Control Center/Remotion as required;
- first-run provisioning screen/flow;
- create/validate canonical AppData layout and default export directory on demand;
- connect Google/CIRCOE/IGuard where applicable;
- production readiness matrix covering runtime, data, audio, connectors, Remotion, codecs and product edition;
- repair actions for recoverable local capability/runtime faults;
- user-facing status language that hides implementation jargon.

### Out of Scope
- no auto-update service beyond update-compatible installer semantics;
- no enterprise fleet deployment tooling;
- no general plugin marketplace.

## Dependencies
Hard `depends_on`: `02-windows-data-root-context-global`, `05-connectors-secrets-and-iguard-hook`, `06-windows-private-runtime-packaging`.
Soft `requires`: Slice 08 final product visual treatment may refine the UI after functionality lands.

## Implementation Steps
1. Select installer technology consistent with packaging and signing requirements.
2. Define install/update/uninstall data-retention policy; user AppData must not be erased by normal application update.
3. Build single launcher/startup path with controlled child-process ownership and clean shutdown.
4. Expand health into a product readiness model: product edition, AppData writable/migrations, private Python/Node, Remotion health, FFmpeg/codecs, audio devices, provider/API configuration, connectors, disk space and critical ports/processes.
5. Build first-run onboarding that requests only required user actions and defers optional ones cleanly.
6. Create default Presentation Board when appropriate after successful onboarding, never an Assistant Board.
7. Add repair/retry flows for Remotion/runtime/connectors; include clear offline/auth/disk/permission diagnostics.
8. Ensure no setup step asks the user to open PowerShell, run pip/npm or edit `.env` for normal use.
9. Add unattended/smoke test hooks suitable for CI and clean-machine validation.

## Files Likely Touched
- installer definition/build scripts;
- launcher/startup composition;
- `jarvis/runtime/health.py` or new product-readiness service;
- onboarding routes/UI modules;
- connector settings/status modules;
- package/version metadata and docs.

## Architecture Constraints
- installer owns program files; Jarvis owns AppData; exports remain user-owned copies;
- readiness checks are diagnostic, not side-effectful unless a named repair action is invoked;
- secrets never appear in installer logs;
- repair must not delete canonical presentation data.

## Automated Validation
- installer build validation;
- scripted install/upgrade/uninstall smoke in clean Windows VM where available;
- first-run state-machine tests;
- readiness matrix unit/integration tests for missing/corrupt/offline states;
- repair tests proving data preservation;
- startup/shutdown orphan-process tests.

## Acceptance Criteria
- normal user installation requires no developer tooling or terminal commands;
- first launch reaches a clear ready/not-ready state with actionable fixes;
- successful onboarding lands in Presentation product flow;
- update/repair preserves AppData and canonical Presentations.

## Documentation Updates
Create installation, onboarding, readiness and repair runbooks for Presentation Edition.

## Handoff Notes
This Slice has both code and user-visible UI. Require `/caveman`, `/coding-guideline`, `/impeccable`; use a Claude Work Agent for frontend where supported. QA: `qa-verification`, `code-review`, `runtime-validation`.

## Slice 00 amendments (2026-10-26)
- E4: onboarding must connect the brain provider (Claude account or key) with no terminal, no `.env` and no CLI commands.
- Existing health to build on: `GET /v1/health` (`jarvis/protocol/server.py:181,349`), `/api/status`, `/api/errors`, `python -m jarvis health`, `scripts/supervisor_v2.py` (5 restarts / 120 s), `scripts/windows_autostart.ps1` (Task Scheduler). `jarvis/runtime/deployment.py` is a git-based developer flow, not a product updater.
