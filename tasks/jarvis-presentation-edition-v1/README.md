# Jarvis Presentation Edition V1 — implementation handoff

## Project
- Project: `Jarvis`
- Repository: `edebazelaire-circoe/Jarvis`
- Source branch audited: `main`
- Source SHA at task creation: `2d6ca879afac7a0e773598cff0872b4f819fa876`
- Handoff slug: `jarvis-presentation-edition-v1`
- Target Drive queue: `Jarvis/task/to-do/jarvis-presentation-edition-v1/`

## Purpose
Turn the current local-first Jarvis codebase into a viable **Windows Presentation Edition V1** that can be installed and used by someone who is not developing Jarvis.

This is not a rewrite of Presentation. The repository already contains the Presentation interaction mode, Presentation Studio, Remotion integration, Board/Session/Context infrastructure, local capabilities, MCP plugins, Drive access, extensive tests, and product UI foundations. The work is a productionization effort: capability lock, storage identity, agent confinement, packaging, onboarding, product UI, health/recovery, and release validation.

## Locked V1 product decisions
1. The distributed product edition is `presentation`.
2. Only Presentation Boards can be created and activated in this edition. Assistant and Meeting remain in the shared codebase but are exposed as `Incoming / unavailable` in the product UI.
3. Do not delete Assistant/Meeting implementation from the repository. Enforce product capability policy at Core/API/MCP/UI boundaries.
4. V1 is Windows-first. macOS and Linux are later packaging targets, not long-lived divergent product branches.
5. Canonical per-user Jarvis state moves to `%LOCALAPPDATA%\CIRCOE\Jarvis\...` for the installed edition. Repository-path hashing remains a development behavior only.
6. `CONTEXT_GLOBAL` lives inside the canonical AppData data root. It is Jarvis's permanent personal directory, loaded for the brain across Boards and Sessions, and protected from cleanup.
7. All working documents, presentation sources, assets, artifacts, drafts, Board memory, Sessions, generated code, and internal files stay inside AppData.
8. `%USERPROFILE%\Documents\Jarvis\` is an **export-only** destination. Files appear there only after an explicit export. Exported files are not canonical state and may be deleted or moved without damaging the internal presentation.
9. The brain must not have general write/shell access to the PC. Presentation V1 writes through bounded Jarvis-owned APIs/capabilities and the explicit export surface.
10. Keep CIRCOE Mail and Calendar, Google Drive, document search, Presentation capabilities, and IGuard once its endpoint/auth contract is supplied.
11. Google Drive is a connector/document source for V1, not the canonical store for Jarvis SQLite/state.
12. The V1 distribution must not require Git, system Python, system Node/npm, or a user-installed FFmpeg. Prefer private pinned runtimes shipped/managed by Jarvis.
13. Server/local split is explicitly deferred. V1 remains local-first and may call remote providers/connectors.
14. The target user experience is one installer, one launcher, guided first-run provisioning, and product-level readiness/repair rather than developer commands.

## Project Manager entrypoint
Start at `slices/TODO.md`, then execute `slices/00-project-manager/SLICE.md` yourself. Do not dispatch implementation before Slice 00 reaches `READY`.

Slice 00 must perform an independent blind audit of the current repository before relying on the conclusions in this handoff. This task was designed against `main` SHA above, but Jarvis changes rapidly.

## Global QA doctrine
Every implemented Slice receives:
- baseline `qa-verification`;
- `code-review` for code changes;
- `runtime-validation` for user-visible or runtime behavior;
- `agent-trace-analysis` with real trace evidence for agent prompts, tools, routing, modules, or agent runtime changes.

QA returns evidence and findings. The Project Manager decides approve, rework, continue, create a new Slice, park a genuinely out-of-scope discovery in `Issues/`, or escalate. A regression caused by the current Slice is blocking and cannot be parked in `Issues/`.

Human validation is never a substitute for machine validation. Before any Human check, run the maximum reasonable automated/runtime validation and clear anything a machine could have caught.

## Coding and frontend requirements
- Every coding Slice requires `/caveman` and `/coding-guideline`.
- Every frontend Slice also requires `/impeccable` and should use a Claude Work Agent when the host supports that routing rule.
- Workspace Task Type vocabulary is not exposed at task creation. Slice 00 must resolve valid existing Task Types before dispatch; never invent one.

## Critical path
The shortest safe path to a distributable pilot is:

`01 product lock -> 02 storage -> 03 export boundary -> 04 confinement -> 06 packaging -> 07 installer -> 10 production gates -> 11 physical E2E`

Slices 05, 08, and 09 can proceed in parallel when their dependencies are satisfied.

## Known planning blockers / external inputs
- IGuard integration needs the actual MCP transport/endpoint/authentication contract. This blocks only the IGuard-specific part of Slice 05, not the rest of the V1.
- Release signing identity/certificate and final installer technology must be selected during Slice 06/10 if no repository standard exists.
- The repository documents openWakeWord model licensing as non-commercial. A distributed/commercial Presentation V1 must not silently ship an incompatible wake-word model. Slice 06 owns the dependency/license decision.

## Non-goals for V1
- Jarvis Cloud/server split.
- Cross-device state synchronization.
- macOS/Linux release packaging.
- Implementing Meeting mode.
- Implementing Assistant product availability.
- Rewriting Jarvis into C#/Electron/native Windows.
- Moving canonical Jarvis state into Google Drive.
- General-purpose filesystem or shell access for the distributed brain.
