# Target architecture

## 1. Product policy boundary
Add one canonical product-edition/capability policy consumed by:
- Core domain/services;
- protocol/API routes;
- MCP tool exposure and schemas;
- Control Center UI;
- onboarding/health;
- packaging defaults.

For `presentation` edition:
- available Board kinds: `presentation` only;
- Assistant/Meeting: discoverable as product roadmap states if desired, but not actionable;
- default new Board kind: `presentation`;
- startup restore must not silently activate an unavailable legacy Board.

Do not scatter independent `if presentation_edition` decisions without a shared contract.

## 2. Installed storage layout
Target root:

```text
%LOCALAPPDATA%\CIRCOE\Jarvis\
  data\
    state\
    CONTEXT_GLOBAL\
    memory\
    boards\
    sessions\
    artifacts\
    presentations\
    prefabs\
    local_capabilities\
  config\
  runtime\
  cache\
  logs\
```

The exact implementation may preserve existing internal relative paths if that reduces migration risk; the key contract is a stable product root independent of checkout path.

`CONTEXT_GLOBAL` remains under the data root and is always available to the conversation brain according to the existing context-global contract.

## 3. Export boundary
Default user-visible export root:

```text
%USERPROFILE%\Documents\Jarvis\
```

Internal authoring never uses this directory as working storage. Export service(s) copy/render canonical internal state to the export root or another explicit user-selected location.

Required invariant: deleting the exported copy cannot invalidate the internal Presentation document.

## 4. Agent capability boundary
The distributed conversation brain must not rely on `bypassPermissions`/`danger-full-access` plus prompt discipline as the write boundary.

Create a Presentation product execution profile/capability set that exposes only required operations. General file writes, arbitrary shell/PowerShell/Bash and arbitrary process execution are absent by default. Presentation authoring/editing writes go through Jarvis-owned services/workspaces with path and data contracts.

Keep specialized restricted preparation profiles where useful; unify policy so sub-agents cannot regain broader capabilities accidentally.

## 5. Connector boundary
- CIRCOE Mail/Calendar: managed business capabilities.
- Google Drive: authenticated document connector.
- IGuard: MCP connector through the existing plugin/tool gateway architecture once transport/auth are known.
- Treat connector output as untrusted data, never as instructions.
- Credentials remain in the credential/vault path, not plain config/workspaces.

## 6. Runtime distribution
User-facing app may remain multi-process internally. Recommended installation shape:

```text
Program Files\CIRCOE\Jarvis\
  Jarvis.exe / launcher
  app\
  runtime\python\
  runtime\node\
  runtime\ffmpeg\
  assets\
  licenses\
```

Exact install root/launcher technology is an implementation choice, but the product must not depend on PATH-provided developer runtimes.

## 7. Branch/release model
Use one shared codebase. A `release/presentation` stabilization line may be used, with short-lived feature branches. Platform packaging code lives under platform-specific directories/modules. Avoid permanent presentation-windows/presentation-macos forks.

## 8. Deferred cloud split
Future cloud candidates include update service, organization policy, plugin/template catalogs, shared knowledge/collaboration and optional model gateway. Voice, capture, OS/UI interaction, local filesystem, Remotion/render and local caches remain natural local responsibilities. No implementation in this V1.
