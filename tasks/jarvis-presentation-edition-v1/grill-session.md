# Reconstructed planning session

> Status: reconstructed faithfully from the active Jarvis conversation. This is not claimed as a verbatim transcript of every earlier turn.

## User goal
The immediate objective is to make Jarvis viable as a **Presentation-only V1**, distributable quickly, initially on Windows. The current Jarvis runs on the developer's machine; the task is to determine what stays, what is hidden/locked, how data is stored, how installation works, how permissions are constrained, and what must be validated before calling it a production-grade pilot.

## Product scope decisions captured
- Create a Presentation product branch/edition from the current codebase.
- Only Presentation Boards are available. Assistant and Meeting must be shown as incoming/unavailable.
- Keep CIRCOE mail/calendar access and add Google Drive; add IGuard as an MCP connector when its plugin contract is available.
- Presentation and editing UI deserve dedicated product passes.
- Preserve document search.
- Avoid unrelated technical/developer capabilities in the Presentation product unless they serve presentation authoring/editing.
- Prefer a one-button installation that verifies/installs all required runtimes/codecs.
- Do not require a user to manage a Git checkout as the production installation model.
- Keep the first release local-first; defer server/local decomposition.
- Constrain writes to Jarvis-owned internal storage plus an explicit output/export area.

## Storage correction locked later in the discussion
The installed edition should use AppData as Jarvis's canonical home. `CONTEXT_GLOBAL` must also live there because it is Jarvis's permanent personal directory and is loaded for the brain across work. All working documents remain internal to AppData.

`Documents\Jarvis` is **not** a general workspace. It is only the default export destination. A PDF/PPTX/MP4/etc. appears there only after explicit export. The internal AppData presentation remains canonical and can be re-exported if the user deletes or moves an exported copy.

## Architecture conclusions adopted
- Prefer a product-edition capability policy over deleting Assistant/Meeting code.
- Prefer one shared codebase with platform adapters/packagers over permanent Windows/macOS/Linux branches.
- Do not attempt a new server architecture for V1.
- Do not rely on UI hiding for security/product lock; enforce at Core/API/MCP boundaries.
- The current CLI brain permission defaults are too broad for a distributed product. Presentation V1 needs a constrained execution profile and bounded write surfaces.
- Production packaging should ship/manage private runtime dependencies rather than require Git/system Python/system Node/npm/FFmpeg.

## Repository evidence considered during planning
- `main` already contains Presentation mode, Studio, Remotion, Board/Session/Context, MCP plugin runtime, Drive access, local capability host, and extensive Presentation tests.
- Historical Presentation/Board task branches are behind `main` with no commits ahead, so `main` is the integration baseline.
- Current local data root is `~/.jarvis/instances/<repo>-<path-hash>/data`, appropriate for development but not a stable installed-product identity.
- `CONTEXT_GLOBAL` already exists under the data root and is granted to the conversation brain.
- Board memory and Context workspace adapters already contain strong path/junction/symlink defenses.
- Claude currently defaults to `bypassPermissions` and Codex to `danger-full-access`; `--add-dir` is documented as an authorization convenience, not a security boundary.
- The Remotion local capability pins packages and verifies Node/npm, but deliberately does not install Node.
- `setup.ps1` is a developer bootstrap, not a customer installer.
- Current `main` has no GitHub Actions workflow run attached to the latest commit, so product CI/release artifact validation must be added.

## V1 mental model
Jarvis owns its internal home in AppData. Presentation Boards, Sessions, memory, `CONTEXT_GLOBAL`, artifacts, drafts, source code, Remotion work, and canonical presentation state live there. The brain can use controlled Jarvis capabilities. The only normal way data leaves this home as a user file is explicit export to `Documents\Jarvis` or another user-selected destination.
