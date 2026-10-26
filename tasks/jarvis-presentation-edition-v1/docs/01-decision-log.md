# Decision log

## D01 — Presentation is the only available product Board type
Locked. Distributed V1 permits creating/activating Presentation Boards. Assistant and Meeting remain in source but appear as incoming/unavailable.

## D02 — Product edition, not code deletion
Locked. Introduce/centralize a Presentation product capability policy. Do not fork out or delete Assistant/Meeting logic from the shared codebase.

## D03 — Windows first, shared source tree
Locked. Windows is the first packaging target. macOS/Linux follow later through platform-specific adapters/packagers, not permanently divergent product branches.

## D04 — Stable AppData identity
Locked. Installed Presentation Edition uses a stable per-user root under `%LOCALAPPDATA%\CIRCOE\Jarvis`. The repository-path hash remains useful for development/worktrees but must not determine installed-user identity.

## D05 — `CONTEXT_GLOBAL` belongs in AppData and is permanent
Locked after user correction. `CONTEXT_GLOBAL` is the brain's always-loaded personal directory across Boards/Sessions. It is canonical internal state and must not be cleaned as cache/runtime.

## D06 — Internal documents remain internal
Locked after user correction. Presentation sources, working documents, generated files, assets, artifacts, Board memory, drafts and code remain under the AppData Jarvis home.

## D07 — `Documents\Jarvis` is export-only
Locked after user correction. Only explicit exports go there. An exported file is a disposable copy from the perspective of Jarvis state; deletion/rename/move must not damage the canonical internal presentation.

## D08 — Brain confinement is a production gate
Locked. UI path guards alone are insufficient because the current CLI defaults are broad. Presentation V1 must remove arbitrary write/shell surfaces from the distributed brain and use bounded Jarvis capabilities for writes/exports.

## D09 — Keep selected connectors
Locked. Keep CIRCOE Mail/Calendar, Google Drive, document search and Presentation capabilities. Add IGuard through MCP once its concrete transport/auth contract is supplied.

## D10 — Drive is not canonical state
Locked. Google Drive is a document connector/source/export destination as product design later permits. SQLite and Jarvis canonical runtime state remain local for V1.

## D11 — Production installation is not a Git checkout
Locked. No requirement for Git, editable pip install, system Python, system Node/npm or user-managed FFmpeg. The installer/launcher owns required private runtimes and diagnostics.

## D12 — Local-first V1
Locked. Defer server/application decomposition. Remote providers/connectors are allowed, but execution/state ownership remains local.

## D13 — Presentation and editing get separate UX passes
Locked. Product shell/Board creation/onboarding and Presentation workspace UX are distinct from the later editing-focused pass.

## D14 — Third-party licensing is a release gate
Derived from repository evidence and required for production. Do not ship a dependency/model whose repository documentation restricts the intended use. The current openWakeWord model is explicitly documented as non-commercial; Presentation V1 must disable/replace/not ship it unless a compatible model/license is chosen.
