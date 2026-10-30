# Architecture Settings: source paths and remaining timing evidence limits

This is read-only causal analysis, not a runtime rerun. S1 reports both exact
baseline cases passing in 60.06 seconds and both exact current cases passing
in its diagnostic batch. Their original broad-gate failures remain recorded;
these passes alone do not establish a pre-existing failure or its cause.

Compared `c0858a80` to integrated candidate `dc0c5036`, whose **jarvis product
tree** is `f43cb45fa92b4489171a0f60ffa96eda744a35c9` (a tree, not a commit).
[Fourteen exact comparisons](architecture-settings-source-identity.json) match:
the architecture browser test, shared Python fixture/driver and CDP harness;
Settings registry/UI/personalization/architecture/brain-panel/subagent modules;
CLI catalog, agent settings and architecture routes; `ControlCenter.cli_agents`;
and the **entire raw HTML after removing exactly the four new script-marker
lines**. That last equality includes all inline Settings bindings, CSS,
render/hydration functions, category specifications and hub/detail navigation.
ControlCenter's product delta only adds those four script injections to its
existing index composition; it does not edit Settings/CLI routes.

## Opening and category/section ownership

Both tests use the shared `OPEN` sequence. It waits only for DOM
`#openSettings`, clicks `#dockMore`, then `#openSettings`. The existing click
binding calls `openSettingsHub`, which refuses if `SET.open` is already true,
switches the existing overlay to hub view and synchronously renders cards
from `JarvisSettingsRegistry.categoriesFor`.

Clicking the `voice_audio` hub card calls `enterSettingsCategory`, dispatching
to `JarvisPersonalization.open`. Its `load` renders initial state, then reads
settings/profiles under a generation/deadline guard and renders again. Its
detail buttons come from registered `voice_audio` sections excluding absorbed
fields; `conversation` is still registered. Detail click leaves that page and
calls `openSettingsTab('conversation')`, which uses the existing Settings shell.
The helper subsequently calls `openSettingsTab('conversation')` directly as a
fallback/deep-link step and waits for the conversation section.

Within the shell, `selectTab` resolves a registry target and calls
`showSettingsTarget`/`applySettingsTarget`: `SET.category` and `SET.section`
change synchronously, then tabs and content render. `renderTab` cleans up the
old section and increments render revision. `mountRegisteredSection` chooses
the exact registered entry, sets footer visibility from `save`, mounts it in
a fresh host and supplies `context.isCurrent()` to reject late results.

## First failure: Runtime & CLI sampled after a fixed delay

The original first test passed `assert_waits` for its opening path and reached
line 98. It therefore cannot be described as failing the initial hub waits.
Its failed compound predicate checks category `advanced_diagnostics`, footer,
`#f_cli_cmd` and `#f_cli_perm`; the original plain trace did not print which
operand was false.

`TOUR` invokes category buttons via native JS `.click()` and invokes
`selectTab` directly, with 250/1500/400 ms sleeps. These programmatic clicks
do not generate the new scene pointerdown/gesture sequence. Runtime & CLI is
still registered under `advanced_diagnostics`, `save:'footer'`. Its body
initially contains `cliTechnicalHtml`: if `SET.clis` is absent it renders only
`#cliStatus` loading; if no spec exists it renders a retry/error. Command and
permission fields are emitted only by `cliRuntimeHtml(spec)`.

Mount then starts `hydrateCliAgents(revision)` without awaiting it. The real
`/api/cli/agents` handler awaits existing `cli_catalog.detect_all`: parallel
probes resolving CLI executables and asking their versions, not invoking a
model. Only a response matching current section/render/request generation
may fill `SET.clis` and rerender the technical host. Leaving the section
increments CLI generation. The test samples after **400 ms**, not after a
CLI-ready condition. This is a concrete source timing boundary, not a measured
400 ms overrun or permission to weaken the assertion. Response/error/status
and actual sampled operands are needed to establish the original cause.

## Second failure: earlier hub/personalization waits

The original second test failed `assert_waits` for hub `voice_audio`,
personalization `conversation` and the conversation tab. Those selectors still
exist in the unchanged registry/render path. The trace does not show them as
retired or prove failure of the later architecture canvas/core configuration.
The CDP driver continues after a failed wait or missing click; the later direct
deep-link step can still open the shell. Thus later plan actions can execute
even when the earlier user navigation failed.

The unchanged harness begins actions **1100 ms** after `Page.navigate`; its
initial wait checks element existence, not attached-handler readiness or
hit-testable geometry. Click scrolls the selector into view, samples one
rectangle center, then dispatches move/press/release and waits 80 ms. Missing
elements become a returned `missing` action rather than aborting the plan.
No original click target/rectangle/hub mutation timing was retained.

After successful OPEN, `mountArchitectureSettings` mounts the existing
architecture module's HTTP adapter and supplies a current-section guard.
Configure mounts the existing brain panel; its PATCH and graph reload stay
inside those owners. Section cleanup destroys the panel/view. No object
viewer or scene geometry path is involved in these actions.

## MOV changes actually considered and exclusions

New viewer/agent modules are scoped IIFEs with distinct globals. Their dialog,
provider/read timers and scene-viewer CSS are created lazily on viewer opening.
Neither Settings test requests the scene viewer. No new native dialog is
therefore created by this path, and its modal key propagation guard is absent.
New grips live under scene capsule/window nodes, not Settings controls. Scene
node pointer/double-click/Enter dispatch requires a closest `.sc-node`; the
Settings overlay/architecture panel is outside that subtree. Document band
selection excludes buttons and fields; ordinary selection clearing does not
prevent Settings clicks. Resize modifier handling exits without a resize
gesture; the new document undo/select-all branches require their own modifier
shortcuts, not the tested Tab/Escape sequence. The iframe Escape bridge does
not turn the native architecture SVG/panel into a prefab frame. F2's callback
only runs while arming fullscreen; these tests request no fullscreen intent.
Chat prefill is not invoked by this route.

One real changed startup surface remains: index injects four additional
modules, **73383 UTF-8 source bytes** at this revision, ahead of later inline
Settings initialization. This measures source size, not parse time. With a
fixed 1100 ms settle and only DOM-existence readiness, additional initialization
could affect when an early click occurs under load. No parse/handler timing
was measured, so this is a candidate task-sensitive path, not an established
regression or an excluded cause. Shared CPU/HTTP contention likewise was not
measured. Source identity cannot prove zero coverage or all-path isolation.

A separately allocated diagnostic could retain actual TOUR operands plus
`SET.clis`, CLI status/generations and request completion time; for navigation,
actual click targets/rectangles and hub/personalization state transitions.
No such runtime was launched here, no test/product behavior changed, and no
automatic waiver or known-failure entry is proposed from isolated passes.
