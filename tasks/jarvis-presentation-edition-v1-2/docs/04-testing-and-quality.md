# Testing and quality

## Mandatory QA composition
- Every implementation Slice: `qa-verification`.
- Code: add `code-review`.
- User-visible/runtime behavior: add `runtime-validation`.
- Agent prompts/tools/routing/roles/work methods/runtime: add `agent-trace-analysis` with real trace evidence.

The Project Manager owns the verdict. A regression introduced by a Slice is blocking; it cannot be parked in `Issues/`.

## Core automated scenarios
### Product capability
- Presentation Edition refuses a direct request to edit Jarvis source or run arbitrary dev commands.
- Research/document tools, Mail/Calendar/approved connectors remain available.
- Presentation authoring still produces Remotion/prefab code through the bounded Presentation path.

### Project continuity
- Create project, establish objectives/decisions/next step, restart Core/Control Center, reopen Board, then verify Jarvis resumes from durable Board state without needing old conversation text.
- Multiple presentations can remain linked/discoverable under the same Board without changing Board identity.

### Research
- Existing fresh research is found and reused without redundant web search.
- Stale/volatile research triggers targeted/full refresh.
- “Latest/current” requests override stale cached conclusions.
- Research Lead uses existing nested agents/relations and can run while the main user conversation continues.
- Final research claims retain sources and freshness context.

### Documents/Dossier
- Substantial research writes a durable Board document, visible in Dossier and reusable by a later presentation task.
- Updating a research document preserves Board ownership and does not create a fake registry Artifact kind.

### Voice/chat
- Launch -> Sleep (unless persisted Off).
- Off -> no wake/mic; chat still works.
- Sleep -> wake word can activate according to provider contract.
- Chat while Sleep/Off does not silently change microphone/TTS state.
- App close stops child processes and releases audio resources.

### Bug report
- Bundle stays inside Jarvis roots, redacts/excludes secrets, includes manifest/report/log context, survives missing/corrupt optional files and has a manual-save fallback when send fails.
- Tests explicitly scan the ZIP for known test credentials/tokens and must find none.

### macOS
- CI exercises path resolution, install/package, startup smoke and core Presentation tests on supported macOS architectures available to the selected CI/runtime.
- Support claim remains blocked until a real-Mac run validates permissions, microphone/wake behavior, rendering and packaged launch.

## Human validation doctrine
Human checks happen only after machine validation is maximized. They focus on experiential questions: novice navigation, natural resume, voice behavior, support-report usability and real-device platform behavior.