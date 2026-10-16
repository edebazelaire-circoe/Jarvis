# Control Center shell (contract)

Canonical contract, documentation **Level 3**: this document (zones, tokens,
layer registry, control membership, accessibility rules), the reusable module
`jarvis/runtime/control_center_shell.js` (`window.JarvisShell`), the tokens on
`:root` of `jarvis/runtime/control_center.html`, and the conformance suite
`tests/unit/test_control_center_shell_layers.py`, which reads the **real**
stylesheets (the page, the Cosmos theme `STYLE` of `control_center_work.js`
and every module sheet `control_center*.js`) and compares them to the tables
below.

Origin: handoff `tasks/jarvis-board-orbital-ui-workspace-rail/`, Slice 01
(resolved architecture `docs/06-resolved-architecture.md` §2, §9, §10, §11).
It replaces the stacking comment that lived at the top of
`control_center.html` and the "Stacking registry" table of
`docs/ARCHITECTURE.md`; both now point here.

**Rule for every later change.** A surface that is added, moved, or gets a
`z-index` updates, in the same commit: its row below, the stylesheet, the
mirror comment at the top of `control_center.html` and, for a control, its
`data-shell-control` attribute. The suite fails otherwise.

## One geometry, two skins

The Control Center has two themes: `circuit-board` (default,
`control_center_work.js`, registry default) and `Cosmos` (what the user runs).
Until this slice they placed the same surfaces differently (vertical dock on
the right in circuit-board, top-right row in Cosmos; panel, pills, banner and
toasts offset accordingly) and each theme had its own stacking ranks. Every
later slice would have had to place each surface twice.

Since Slice 01 **the Cosmos zone geometry is the base geometry of both
themes**, written once in `control_center.html` with the tokens below. A theme
is a **skin** only: colours, borders, radii, blur, fonts, icons. The Cosmos
`STYLE` (and any `html[data-jarvis-theme="cosmos"]` rule of the page) carries
no `position`, `top`, `right`, `bottom`, `left`, `inset`, `z-index`,
`transform`, `width`, `max-width`, `flex-direction` or `flex-wrap` on a shell
surface (`test_cosmos_overrides_no_shell_position_or_rank`). The circuit-board
skin keeps its text labels in the launcher (`ERR`, `TRC`, …), at the shared
34 px size. The `JARVIS` brand of the state line is hidden in both themes (Cosmos
already hid it): in circuit-board it pushed the state onto a second row, over
the Bare Hands column, from 1024 px down.

## Zones

| Zone | Surfaces today | Owner of the content |
| --- | --- | --- |
| `top-left` | `.topbar`: `#boardsHud`, `.state` (the `.brand` element stays in the markup, hidden in both themes: the target shows Board then state) | page, `control_center_boards.js` |
| `top-right` | `.dock` (global launcher, one row of 34 px buttons); `#bgPills` left of it until Slice 06 | page |
| `top-centre` | `.live-banner` (GPT-Live, transient) | page |
| `left-edge` | `#toolWheel` anchor and orbital tool wheel (Slice 02, behind `JarvisToolWheel.enabled` until Slice 04); `#barehandsHud`, `#barehandsPalette`, `#captureRail`, `#presentationRail` until Slices 03, 04, 07 move them | their modules |
| `left-low` | `#screenshotPreview` (Slice 05) | — |
| `bottom-left` | `#interactionModeHud`, `.sc-status` notes of the scene | `control_center_interaction_mode.js`, scene |
| `bottom-centre` | `#voiceHint` (until Slice 06), `#boardDropTray`; status centre from Slice 06 | page, `control_center_board_drop.js` |
| `bottom-right` | `#chatTab` | `control_center_chat.js` |
| `right` | side panels (`#panel`, `#chatPanel`, `#jvStudioInspector`); workspace rail from Slice 07 | page, modules |
| `centre` | Board / scene (`#sceneLayer`) | scene |

`JarvisShell.ZONES` mirrors this table (one line per zone).

Placement rules that hold in both themes (measured by
`tests/unit/test_control_center_shell_browser.py` at 1440×900, 1280×720,
900×600 and 600×800):

- **State line** (`top-left`): one row above 700 px, ending 10 px before the
  launcher, and before the background pills while they sit left of it
  (`#app:has(#bgPills:not([hidden])) .topbar`, 4 × 28 px + gaps reserved until
  Slice 06 moves them). The Board control and the state shorten (ellipsis)
  rather than wrap onto the left-edge column, whose top is at 76 px. At 700 px
  and below the column moves to the middle of the screen and the state may
  wrap under the Board.
- **Launcher** (`top-right`): one row of 34 px buttons at
  `--shell-gutter`; two rows of five at 620 px and below. Pills sit left of it,
  below it at 700 px and below.
- **Side panels** (`right`): `#panel`, `#chatPanel` and the Studio inspector
  `#jvStudioInspector` share the zone: top `--shell-panel-top` (under the
  launcher and the pills), bottom `--shell-panel-bottom` (above the chat tab),
  right `--shell-gutter`, full width minus the gutters at 700 px and below.
  Toasts move left of an open panel from 940 px up.
- **Board drop tray** (`bottom-centre`): above the bottom row; at 760 px and
  below it climbs to `--shell-panel-top` + 8 px, under the launcher and pills.

## Tokens

Defined **once** on `:root` in `control_center.html`; no theme and no module
sheet redefines a `--shell-*` or `--sem-*` token. Responsive values are set
only in the `@media` blocks listed here. `JarvisShell.TOKENS` and
`JarvisShell.RESPONSIVE_TOKENS` mirror them (`test_tokens_defined_once_and_reduced_motion_zeroes_durations`).

| Token | Base | Responsive | Use |
| --- | --- | --- | --- |
| `--shell-gutter` | `18px` | `10px` at `max-width:700px` | distance of every edge surface to the window edge |
| `--shell-top-h` | `40px` | | height of the state line |
| `--shell-bottom` | `18px` | | bottom baseline of bottom surfaces |
| `--shell-status-h` | `44px` | | height of the bottom status centre (Slice 06) |
| `--shell-control` | `34px` | | launcher button size |
| `--shell-launcher-w` | `394px` | `194px` at `max-width:620px` | launcher width: 10 buttons × 34 + 9 gaps × 6; two rows of 5 below 620 px |
| `--shell-panel-top` | `64px` | `88px` at 700, `126px` at 620 | top of side panels and of the GPT-Live banner (below the launcher) |
| `--shell-panel-w` | `500px` | | side panel width (capped by the window) |
| `--shell-panel-bottom` | `68px` | | bottom of side panels: they stop above the chat tab row (18 + 40 + 10), so the tab stays whole and clickable |
| `--shell-rail-w` | `300px` | `72px` at `max-width:1099px`, `0px` at 700 | workspace rail width (Slice 07) |
| `--shell-anchor-w` | `14px` | | visible part of the wheel anchor at rest (Slice 02) |
| `--shell-wheel-r` | `200px` | | wheel radius (Slice 02) |
| `--shell-wedge-min` | `48px` | | minimum target size of a wedge |
| `--shell-icon` / `--shell-icon-sm` | `20px` / `15px` | | icon sizes (status centre, launcher) |
| `--shell-radius` | `12px` | | shell surface radius |
| `--shell-glass-bg` / `--shell-glass-strong` | `rgba(5,11,16,.46)` / `rgba(4,10,15,.80)` | | glass surfaces (controls / panels) |
| `--shell-stroke` / `--shell-stroke-active` | `rgba(174,205,220,.12)` / `color-mix(in srgb,var(--accent) 46%,transparent)` | | thin strokes, resting / selected |
| `--shell-focus`, `--shell-focus-w`, `--shell-focus-offset` | `var(--accent)`, `2px`, `2px` | | focus ring |
| `--sem-alert` | `#ff9f43` | | orange: warning / failure to look at |
| `--sem-done` | `var(--ok)` | | green: ready / done |
| `--sem-question` | `var(--accent)` | | cyan: a question waiting for the user |
| `--sem-working` | `#4da3ff` | | blue: being worked on |
| `--sem-review` | `#ffd166` | | yellow: changed since reviewed |
| `--sem-problem` | `#ff6a4d` | | orange-red: canonical problem / error state (never relabelled as review) |
| `--shell-ease` | `cubic-bezier(.2,.7,.2,1)` | | shell motion curve |
| `--shell-dur-fast` / `--shell-dur` | `120ms` / `180ms` | `0ms` under `prefers-reduced-motion: reduce` | shell motion durations |

Colour is never the only carrier of a state: every semantic colour comes with
an icon or a text label.

## Layer registry

Single source of every `z-index` of the Control Center page. Same ranks in
both themes: since Slice 01 no theme has its own rank. Values are compared to
the stylesheets by `test_every_rank_in_css_matches_the_registry`: a `z-index`
in a sheet that matches neither a page layer row (same sheet, same rule, same
rank) nor a contained prefix fails, and so does a row that no sheet declares.
The rule is written exactly as in the sheet, `${…}` interpolations included.

### Page layers

| Rank | Surface | Sheet | Rule | Why |
| --- | --- | --- | --- | --- |
| 0 | `.face` | `control_center.html` | `.face` | visualizer iframe, bottom of the page |
| 0 | `#cosmosFace` | `control_center_work.js` | `#cosmosFace` | Cosmos canvas, same place as the face |
| 20 | `#sceneLayer` | `control_center_scene_page.js` | `.scene` | Board / scene, above the face, below every control; its own stacking context |
| 21 | `.board-drop::before` | `control_center.html` | `.board-drop::before` | drop frame, just above the scene, below the controls |
| 30 | `#toolWheel` | `control_center.html` | `#toolWheel` | wheel anchor at rest |
| 30 | `#barehandsPalette` | `control_center_barehands_hud.js` | `#${DOM.paletteId}` | below the Bare Hands control and its selector, which open over it |
| 30 | `#captureRail` | `control_center_capture_rail.js` | `${H}` | sibling of the palette, same rank for the same reason |
| 30 | `#presentationRail` | `control_center_presentation_rail.js` | `#${DOM.hostId}` | rail outside the Studio |
| 31 | `.topbar` | `control_center.html` | `.topbar` | state line; `#boardsHud` lives inside it |
| 31 | `#voiceHint` | `control_center.html` | `.voicehint` | wake key hint (removed in Slice 06) |
| 32 | `.dock` | `control_center.html` | `.dock` | launcher |
| 32 | `#chatTab` | `control_center.html` | `.chat-tab` | page control of the same class as the launcher |
| 32 | `#barehandsHud` | `control_center_barehands_hud.js` | `#${DOM.hostId} .bh-hud-btn` | Bare Hands control button |
| 32 | `#barehandsHud` | `control_center_barehands_hud.js` | `#${DOM.hostId} .bh-hud-cap` | its state cap |
| 32 | `#interactionModeHud` | `control_center_interaction_mode.js` | `#${DOM.hostId} .im-btn` | mode button |
| 33 | `.panel` | `control_center.html` | `.panel` | side panels (`#panel`, `#chatPanel`) |
| 34 | `.board-drop-card` | `control_center.html` | `.board-drop-card` | drop card, readable over the left column at 600 px |
| 34 | `#boardDropTray` | `control_center.html` | `.board-drop-tray` | drop tray, above the voice hint and the chat tab |
| 34 | `#jvStudioInspector` | `control_center_presentation_studio_inspector_core.js` | `#${PANEL_ID}` | Studio inspector side panel, above the panel it replaces |
| 35 | `.live-banner` | `control_center.html` | `.live-banner` | GPT-Live banner over the controls |
| 36 | `#boardsPanel` | `control_center.html` | `#boardsPanel` | Board chooser, opened by the user over the banner |
| 36 | `.bh-hud-pop` | `control_center_barehands_hud.js` | `#${DOM.hostId} .bh-hud-pop` | Bare Hands lifecycle selector |
| 36 | `.im-pop` | `control_center_interaction_mode.js` | `#${DOM.hostId} .im-pop` | mode chooser |
| 37 | `#toolWheel[data-open]` | `control_center.html` | `#toolWheel[data-open]` | open wheel and its radial sub-arcs: above the choosers, the wheel is the user's latest focus |
| 40 | `#bgPills` | `control_center.html` | `.bgpills` | background pills (status centre from Slice 06) |
| 55 | `.tl` | `control_center.html` | `.tl` | conversation timeline, full-screen launcher view |
| 55 | `.tlab` | `control_center.html` | `.tlab` | Test Lab (one full-screen view at a time) |
| 55 | `.mcpi` | `control_center.html` | `.mcpi` | MCP inspector |
| 55 | `.wsp` | `control_center.html` | `.wsp` | Sessions & Boards |
| 55 | `.pfb` | `control_center.html` | `.pfb` | prefab library |
| 60 | `.overlay` | `control_center.html` | `.overlay` | settings and modal overlays |
| 70 | `.toasts` | `control_center.html` | `.toasts` | toasts |
| 75 | `.bgpop` | `control_center.html` | `.bgpop` | background pill popover |
| 75 | `#jvStudioReloadBand` | `control_center_presentation_studio_reload.js` | `#${BAND_ID}` | Studio reload band |
| 80 | `.ctxmenu` | `control_center.html` | `.ctxmenu` | the one shared context menu, above the choosers it replaces |
| 82 | `#barehandsCards` | `control_center_barehands_hud.js` | `#${DOM.cardsId}` | Bare Hands quick cards, opened from the context menu |
| 85 | `.cdialog-back` | `control_center.html` | `.cdialog-back` | in-page confirmation |
| 9000 | `#jvStudioExplorer` | `control_center_presentation_studio_explorer_core.js` | `#${HOST_ID}` | Variantes (Studio explorer) |
| 9100 | `html.jvr-studio #presentationRail` | `control_center_presentation_rail.js` | `html.jvr-studio #${DOM.hostId}` | rail beside the Studio |
| 9150 | `html.jvx-run #interactionModeHud` | `control_center_presentation_studio_explorer_core.js` | `html.jvx-run #interactionModeHud` | mode control during a run shown in Variantes |
| 9300 | `.jvr-menu` | `control_center_presentation_rail.js` | `.jvr-menu` | rail menu |
| 9400 | `.jvr-dialog-back` | `control_center_presentation_rail.js` | `.jvr-dialog-back` | rail dialog |
| 9500 | `#jvFullscreenPrompt` | `control_center_fullscreen.js` | `#${PROMPT_ID}` | fullscreen prompt |
| 2147482000 | `#jarvisFlow` | `control_center_barehands_calibration.js` | `${R}` | Bare Hands calibration / benchmark flow, above the toasts |
| 2147483000 | `#jarvisHands` | `control_center_barehands.js` | `#jarvisHands` | Bare Hands pointer, paints over everything |

### Contained ranks

Ranks that only order children **inside** a stacking context created by a
page layer; they never compete with the page layers. A `z-index` whose rule
starts with one of these prefixes, in that sheet, is accepted whatever its
value.

| Container | Sheet | Rule prefix | Why |
| --- | --- | --- | --- |
| `#sceneLayer` (20) | `control_center_scene_page.js` | `.sc-` | node layers 0–1000, band, status chips; nodes also get an inline `z-index` |
| `#sceneLayer` (20) | `control_center_barehands_target.js` | `.jh-target` | Bare Hands target ring inside a node |
| `#sceneLayer` (20) | `control_center_barehands_target.js` | `.sc-node` | node raised under the hand |
| `.tl` (55) | `control_center.html` | `.tl-` | timeline internals 1–30 |
| `.overlay` / `.panel` | `control_center.html` | `.catalog-table` | sticky table header |
| `#chatPanel` (33) | `control_center.html` | `.chat-drop` | drop veil inside the chat panel |
| `#jarvisFlow` | `control_center_barehands_calibration.js` | `${R} ` | calibration internals |
| `#jarvisFlow` | `control_center_barehands_benchmark_ui.js` | `${R} ` | benchmark internals |
| `#jarvisFlow` | `control_center_barehands_calibration_agent.js` | `${sel} ` | calibration agent card |
| `#jvStudioExplorer` (9000) | `control_center_presentation_studio_explorer_core.js` | `#${HOST_ID} ` | Variantes internals |
| `#jvStudioExplorer` (9000) | `control_center_presentation_studio_run.js` | `${H} ` | run overlay internals |
| `.overlay` (60) | `control_center_wake_word.js` | `#wakeWordSettings ` | settings tooltip |

### Reserved ranks

Declared by later slices of the orbital shell; listed so that nobody takes
them for something else. They become page layers when their slice lands.

| Rank | Surface | Slice |
| --- | --- | --- |
| 38 | `#screenshotPreview` | S05 |
| 40 | status centre: `#recIndicators`, `#hiddenEye` beside `#bgPills` | S06 |
| 60 | screenshot lightbox, annotation editor (the `.overlay` pattern) | S05 |

### Invariants

Checked on the registry rows by `test_relative_order_of_the_old_registry_is_kept`:

- every page control is above the scene (20); the face and the Cosmos canvas
  are below it;
- `.topbar` ≤ `.dock` < `.panel` < `.live-banner` < `#boardsPanel` <
  `#bgPills` < `.toasts` < `.cdialog-back`;
- choosers (36) are above the GPT-Live banner (35) and below the pills,
  toasts, context menu and confirmation;
- the open wheel (37) is above the choosers and below the status centre
  (40), toasts and context menu; closed, its anchor is at the left-edge
  rank (30);
- `.ctxmenu` (80) < `#barehandsCards` (82) < `.cdialog-back` (85);
- full-screen launcher views (55) are above every control and below
  `.overlay` < `.toasts` < `.ctxmenu` < `.cdialog-back`;
- Variantes 9000 < rail beside it 9100 < mode control during a run 9150 <
  rail menu 9300 < rail dialog 9400;
- `#jarvisHands` is the top of the page.

**Cosmos rank collapse (Slice 01).** Cosmos used to raise `.topbar` 45,
`.panel` 42, `.live-banner` 48, `.dock`/`.bgpills`/`.chat-tab` 50,
`.board-drop-tray` 49, `#boardsPanel` 51. `git log -S` traces them to the
theme's first commit (`2868528e`, "add Omega visual theme") and to slices
that kept "one above the Cosmos dock" (`98f28604`, `4b99853b`); none records
a stacking conflict. With the geometry shared, the surfaces they ordered no
longer overlap (panel and banner start at `--shell-panel-top`, below the
launcher row; the Board chooser opens below the pills at every width; every
side panel stops at `--shell-panel-bottom`, above the chat tab, where Cosmos
used to draw the tab over the panel's last row), so the base ranks apply to
both themes.

## Controls (`CONTROL_SELECTOR`)

A **control** is a page surface the scene must not slide under: a held object
stops against it, and the capture rail avoids it. Every control host carries
the attribute `data-shell-control`; the shared selector is

```
[data-shell-control],#sceneLayer>.sc-status
```

published as `JarvisShell.CONTROL_SELECTOR` by `control_center_shell.js`, read
by the scene (`control_center_scene_page.js`, measured walls) and the capture
rail (`control_center_capture_rail.js`, obstacles, minus the Bare Hands column
it docks to and the side panels that cover it). Both keep an identical
fallback literal and journal `shell.missing` if the module is absent.

| Host | Zone | Declared by |
| --- | --- | --- |
| `#boardsHud`, `.topbar>.state` | top-left | page |
| `.dock` | top-right | page |
| `#bgPills` | top-right (bottom-centre from S06) | page |
| `.live-banner` | top-centre | page |
| `#panel`, `#chatPanel` | right | page |
| `#barehandsHud`, `#barehandsPalette`, `#captureRail` | left-edge | page (hosts) |
| `#toolWheel` | left-edge | page |
| `#presentationRail` | left-edge (right from S07) | `control_center_presentation_rail.js` (creates the host and the attribute) |
| `#interactionModeHud` | bottom-left | page |
| `#voiceHint`, `#boardDropTray` | bottom-centre | page |
| `#chatTab` | bottom-right | page |
| `#screenshotPreview` | left-low | S05 |

Before Slice 01 the scene's literal list missed `#interactionModeHud`,
`#chatTab`, `#presentationRail` and `#boardDropTray`: a held object could
stop under them. They are now measured. Not controls: transient layers that
open over everything by rank (choosers, menus, popovers, toasts, dialogs,
full-screen views, `#barehandsCards`) and the Studio surfaces.

`test_every_declared_control_host_matches_control_selector` checks that every
host in the page that the table names carries the attribute and that nothing
else does.

## Tool wheel (`#toolWheel`)

Slice 02, decisions D3 and D4 of the handoff's resolved architecture. Module
`jarvis/runtime/control_center_tool_wheel.js` (`window.JarvisToolWheel`),
served by `ControlCenter.index` (`TOOL_WHEEL_SCRIPT_FILE`). A **new surface**:
not the Bare Hands palette, not the capture rail. Slice 03 moved the palette
(and the top-left lifecycle control) into Selection: with the wheel on they
leave the default view (see Selection method below); the capture rail stays
until Slice 04 (rollback = leave the flag off, or remove `#toolWheel`).

**Feature flag.** `JarvisToolWheel.enabled` is `false` by default: the host
stays `hidden`, nothing is built, no listener is attached. Setting it to
`true` builds the anchor and the wheel; tests do so. Slice 04 removes the
flag once every wedge is wired.

**Closed.** Only the anchor shows: a `--shell-anchor-w` (14 px) × 112 px
glass tab with a thin cyan stroke, centred on the left edge, `<button
aria-haspopup="menu" aria-expanded="false">` named « Outils » (`aria-label` =
`title`).

**Reveal.** One wheel, three ways in, none of them network-bound:

| Input | Reveal | Focus |
| --- | --- | --- |
| Mouse | `pointerover` on the anchor | not moved (hover highlights only) |
| Bare Hands | the synthetic hand pointer (`pointerId` 9001-9002, `JarvisBarehandsContracts.isBareHandsPointerId`) reaching the anchor: the same `pointerover`; a pinch on the anchor is a `click` (`detail` 0, but its source is read from the preceding Bare Hands `pointerdown`, so it is a pointer, not the keyboard) | not moved |
| Keyboard | `Enter` / `Space` (native `click`, `detail` 0) or `ArrowRight` on the anchor | first (or last highlighted) wedge |

No new Bare Hands gesture: a "leftward reveal" gesture does not exist and is
deferred (`tasks/jarvis-board-orbital-ui-workspace-rail/Issues/bh-left-reveal-gesture.md`).
Pointer movement elsewhere on the page never opens the wheel: it only listens
on its own host.

**Open.** A half-disc of radius `--shell-wheel-r` (200 px) whose centre is on
the left edge, rank 37. Exactly four primary wedges, in this order:
**Sélection, Vidéo, Capture d'écran, Audio** (`JarvisToolWheel.SLOTS`), no
filler. They share 156° equally (39° each); each whole sector, from the hub
(44 px) to the rim, is the pointer target (`clip-path`), so a hand never
falls into a gap between two wedges. Icon dots are 52 px (≥
`--shell-wedge-min`) at 122 px from the centre, 83 px apart along the arc
(minimum: target + 8 px, `minSeparationDeg()`). Hover or pointing **highlights**
one wedge and shows its label, the only label on screen.

**Activation.** Primary = `click` only: mouse click, `Enter` / `Space`, Bare
Hands primary pinch. Never `pointerup`, so the Bare Hands sequence
(`pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`) fires once.
Secondary = the existing channel (D4): `contextmenu` (right click, Bare Hands
thumb + middle pinch), `ContextMenu` key, `Shift+F10`; a keyboard secondary
followed by the browser's own `contextmenu` on the same wedge within 500 ms
counts once (the dedupe is reset when the wheel closes or a second level
returns). Never long press. A Bare Hands `contextmenu` (thumb + middle pinch)
is attributed to `barehands` from the `pointerId` of the last `pointerover`
on the wheel, however long after the last pinch.

**Injected actions.** `JarvisToolWheel.register({id, onActivate(ctx),
onSecondary?(ctx)})` binds a slot (unknown slot → `TypeError`, code
`tool_wheel_unknown_slot`) and returns an unregister function. `ctx` =
`{slot, source: 'mouse'|'barehands'|'keyboard'}`. A slot with no action is
`aria-disabled`; activating it journals `tool_wheel.unbound` and shows a
notification instead of doing nothing silently. A callback that throws or
rejects is journalled (`tool_wheel.action_failed`, real cause) and shown as a
notification; the wheel itself is unaffected. A slot registered with
`menu:true` opens its sub-arc on **primary** activation instead of acting
(Selection, Slice 03). Capture wiring is Slice 04.

**Slot status.** `JarvisToolWheel.setStatus(id, {icon?, tone?:
'error'|'wait', text?} | null)` lets an action **project** its owner's state
onto its wedge (Selection: the current method): the dot icon is swapped
(`icon`: an `ART` key), a badge marks `error` (« ! », `--sem-problem`) or
`wait` (spinning ring, `--sem-working`, static under reduced motion), and
`text` joins the wedge name (`Sélection — Souris`) and its label pill
(`Sélection · Souris`). The anchor carries the worst projected tone
(`data-tw-tone`, coloured stroke + « ! » / « … » mark, `aria-label`/`title`
`Outils — <text>`), so a failure or a pending start stays visible with the
wheel closed. The wheel stores nothing else: the action re-reads its owner
and calls `setStatus` again on each change (journal `tool_wheel.status`).

**Radial sub-arc** (the reusable submenu pattern). `onSecondary` returns the
entries `[{id?, label, disabled?, checked?, icon?, note?, detail?, tone?,
onActivate?(ctx), onSecondary?(ctx)}]` (or a promise of them; « Chargement… »
shows while it is pending). `icon` draws an `ART` glyph in the pill, `note`
a short muted second text, `detail` the long reason that goes into the
accessible name and the tooltip, `tone` an `error`/`wait` mark; `id` is
exposed as `data-tw-item`. They are laid out on an
outer arc (radius 236 px, 15° apart) centred on the parent wedge and kept
within ±78°, as text pills (`role="menuitem"`, or `menuitemradio` with
`aria-checked` when `checked` is a boolean); labels go through `textContent`.
`ArrowUp` / `ArrowDown` / `Home` / `End` move, `Esc` or `ArrowLeft` return to
the parent wedge. Hovering **another** wedge while a sub-arc is open closes
the sub-arc (its label comes back).

**Second level.** An entry that carries `onSecondary` (`aria-haspopup="menu"`)
opens, on its secondary activation (right click, thumb + middle pinch,
`ContextMenu`, `Shift+F10`), a second list **in place of** the first, laid
out from the parent entry's angle downwards (`layoutSubArc(..., 'start')`, so
it never climbs into the top-left corner). `Esc` / `ArrowLeft` return to the
first level with the parent entry focused; journal `tool_wheel.item_secondary`.

**Close.** `Esc` (topmost first: second level, sub-arc, then wheel; with
the focus elsewhere in the page, `Esc` still closes a pointer-opened wheel),
activating a wedge or an entry, a `pointerdown` outside (document
`pointerdown` and `keydown` listeners present **only while open**), focus leaving the host (`Tab` away: no focus trap), and — when the
wheel was opened by a pointer — the pointer leaving it for 400 ms (grace that
covers the gaps between anchor, wedges and sub-arc; Bare Hands sends
`pointerout` without `relatedTarget`). Closing never touches domain state.
Focus is never left on a hidden element: if it was inside the wheel, it
returns to the anchor.

**Keyboard.** One tab stop (roving `tabindex` on the wedges), `ArrowUp` /
`ArrowLeft` previous, `ArrowDown` / `ArrowRight` next (wrapping), `Home` /
`End`. A screen-reader description on every wedge names the secondary keys.

**Motion.** The half-disc slides 28 px out of the edge and fades in over
`--shell-dur`; dots scale on highlight over `--shell-dur-fast`. Under
`prefers-reduced-motion: reduce` both are 0 ms and nothing waits for a
transition end. `forced-colors` maps strokes to `CanvasText`, the highlight
to `Highlight`.

**Accessible names.** Wedges carry `aria-label` but **no** `title`: the label
pill is their tooltip (a native tooltip would double it). The checked mark of
a `menuitemradio` entry is drawn with `content:"● " / ""`, so it never enters
the accessible name.

**Journal.** `[tool_wheel] <key> {json}`: `tool_wheel.installed`,
`.enabled`, `.registered`, `.open {reason: mouse|barehands|keyboard|api}`,
`.close {reason: leave|activate|escape|outside|blur|api|disabled}`,
`.activate`, `.secondary`, `.secondary_none`, `.item`, `.item_inert`,
`.item_secondary`, `.item_secondary_none`, `.status`, `.unbound`,
`.action_failed`, `.install_failed`.

**Tests.** `tests/unit/test_tool_wheel_js.py` (node: geometry, reducer, menu
slot, second level, no network, served page);
`tests/unit/test_tool_wheel_browser.py` (headless Chrome via CDP, real input
events: mouse hotspot, keyboard, Bare Hands synthetic pointer 9001, pinch on
the anchor, late thumb + middle pinch, `Esc` with outside focus, `Space`,
reduced motion, focus, far pointer).

## Selection method (`control_center_input_arbitration.js`)

Slice 03, decision D5 of the handoff's resolved architecture (binding).
Module `jarvis/runtime/control_center_input_arbitration.js`
(`window.JarvisInputArbitration`, `INPUT_ARBITRATION_SCRIPT_FILE`), served
after the tool wheel and the Bare Hands HUD, which it reads at load; an
install refusal is caught and journalled (`input_arbitration.install_failed`,
`code: input_arbitration_dependency_missing`).

**No new owner.** The selection method is a **projection** of the Bare Hands
lifecycle (`JarvisBarehands.openLifecycleSeam('selection', …)`):

| Bare Hands lifecycle | Selection shows | Wedge / anchor |
| --- | --- | --- |
| `active`, `sleep` | Bare Hands (`sleep`: « Bare Hands · veille ») | Bare Hands icon |
| `off` | Souris | mouse icon |
| `error` | Bare Hands, never Souris | « ! » badge, `Bare Hands · interrompu (<code>)` |
| starting | Bare Hands | wait ring, `Bare Hands · démarrage N s` (1 s counter; « choisissez Souris pour annuler ») |

**Sub-arc.** The Selection wedge is a `menu:true` slot: its primary
activation opens exactly **Souris** and **Bare Hands** (`menuitemradio`, the
mouse icon and the Bare Hands icon — tracking-frame corners around a thumb +
index pinch; the former hand icon is not reused). Bare Hands' secondary
activation opens the second level: the **installed** tools
(`JarvisBarehands.tools()`, checked = current tool, uninstalled =
`aria-disabled` + reason), then **Veille**, **Aide**, **Diagnostic**,
**Calibration** (refused with the HUD's own reason, e.g. « Bare Hands est
éteint »).

| Choice | Gate (single write path) |
| --- | --- |
| Souris | `JarvisBarehandsHudControl.selectMethod('mouse')` = HUD `choose('off')` = `JarvisBarehands.disable()`: camera released, master switch written false, `c_pose` cannot wake |
| Bare Hands | `selectMethod('bare_hands')` = HUD `choose('active')`: `activate()` then `enable()` to persist |
| a tool | `JarvisBarehands.tool(id)` → `saveSettings({tool})` |
| Veille | HUD `choose('sleep')` |
| Aide / Diagnostic / Calibration | HUD `runQuick('help' / 'diagnostics' / 'calibration')` |

A refusal is shown (wheel notification with the real cause, plus Bare Hands'
own toast) and journalled (`selection.method_refused`). Réglages and Tester
stay reachable from the Bare Hands settings tab.

**Wheel on = Selection owns the column.** While `#toolWheel` is not
`hidden`, the HUD sheet hides the top-left lifecycle control
(`#barehandsHud`) and the tool strip (`#barehandsPalette`) with
`body:has(#toolWheel:not([hidden]))`; flag off, both come back (rollback).
Nothing is uninstalled: `JarvisBarehandsHudControl`, `JarvisBarehandsPalette`
and their seams stay live.

**Mouse takeover** (pure `decide(state, event, params)`):

- input = real pointer events only, listened on `document` in capture,
  passive, never prevented: `isTrusted === true` **and** a `pointerId` outside
  9001-9002; a keyboard `click` (`detail` 0) is not the mouse;
- only while the lifecycle is `active` (in `sleep` the hand drives nothing;
  `off` / `error` / starting never call);
- `pointerdown` / `click` / `wheel` / `contextmenu` → immediate (`reason:
  'click'`);
- `pointermove` → path length `>= distancePx` **and** net displacement
  `>= netPx` within a sliding `windowMs` (`reason: 'movement'`); jitter
  cancels in the net, slow drift never reaches the path within the window;
- one transition per episode (`pending` until the lifecycle changes),
  accumulator reset; `cooldownMs` after every entry into `active` (explicit
  choice, voice, `c_pose` wake) and after an explicit Bare Hands request;
- defaults `distancePx 48`, `netPx 24`, `windowMs 400`, `cooldownMs 1500`;
  tunable live with `JarvisInputArbitration.configure(patch)` (bounded,
  `netPx <= distancePx`, refusals `input_arbitration_bad_param` /
  `input_arbitration_unknown_param`, journal `input_arbitration.configured`).

Reaching for the wheel with the mouse while Bare Hands is active is itself a
deliberate move: control passes to the mouse before the click on « Souris ».

The takeover calls `selectMethod('mouse', {reason: 'mouse_takeover'})`; the
reason only changes Bare Hands' stop toast to « Souris reprise — Bare Hands
éteint » (`JarvisBarehands.disable({reason})`). **Return to Bare Hands is
explicit only**: the wheel, or voice — `barehands_activate`; from `off` the
broker first answers `barehands_disabled` and the brain turns the switch on
(`settings_set(barehands.enabled, true)`), the status heartbeat re-arms the
page (sleep), then `barehands_activate` wakes it.

**Journal.** `[input_arbitration] <key> {json}`: `input_arbitration.installed`,
`.configured`, `.takeover {reason, input, distance_px, net_px, window_ms}`
(aggregates only), `selection.method_requested`, `.method_selected`,
`.method_refused`, `.method_busy`, `.projected`, `.tool_selected`,
`.bare_hands_return {ms, lifecycle, code}` (return latency, also
`JarvisInputArbitration.stats().lastReturnMs`).

**Return latency** (measured by `test_selection_method_browser.py`, headless
Chrome, fake camera, real MediaPipe 0.10.14 assets via
`SELECTION_REAL_VENDOR`, CPU / SwiftShader): 389-877 ms from the click to
`active` (the first, cold run is the slowest); with the fake landmarker
~150 ms. Under the 3 s threshold of D5, so the `idle_wake` fallback is not
filed. A real webcam's warm-up is not in this figure (Human check HV-03-01).

**Tests.** `tests/unit/test_input_arbitration_js.py` (node: `decide`
properties over 10 000 seeds — zero-mean jitter, slow drift —, click, Bare
Hands pointer ids, one transition per episode, cooldown, params, projection,
sub-arc items, served order); `tests/unit/test_selection_method_browser.py`
(headless Chrome, real page and real Bare Hands engine, fake camera, a test
HTTP server running the real `barehands_test_mode` settings: only Mouse and
Bare Hands offered, Bare Hands activates and persists, real jitter ignored
then a real deliberate move takes over, Mouse releases the camera and no
frame is analysed afterwards, failed activation shown with its cause, tools
and quick actions through the second level, voice return through the
command channel, latency).

## Accessibility and motion rules

- **Icon-only control**: `aria-label` and tooltip (`title`) carry the same
  words; neither carries a ticking counter (a timer goes in
  `aria-describedby`, not in the name).
- **State never by colour alone**: icon, shape or text with every semantic
  colour.
- **Focus**: `:focus-visible` shows a `--shell-focus-w` ring in
  `--shell-focus`, offset `--shell-focus-offset`. The page sets it, at zero
  specificity (`:where(...)`), on every focusable element of a control host;
  a module may draw its own ring, never remove it. Focus is never left on a
  hidden element: hiding a surface returns focus to its opener.
- **Keyboard**: one tab stop per group (roving tabindex), arrows inside the
  group, `Home`/`End`, `Enter`/`Space` on native buttons, `Esc` closes the
  topmost transient surface. Secondary activation is the existing channel:
  `contextmenu` (mouse right-click, Bare Hands thumb + middle pinch),
  `ContextMenu` key, `Shift+F10`. Never long press.
- **Announcements**: one polite live region per module; urgent only for what
  the user must act on now.
- **Target size**: at least `--shell-wedge-min` (48 px) for wheel wedges,
  32 px for status-centre buttons, the launcher's 34 px for launcher buttons.
- **Reduced motion**: under `prefers-reduced-motion: reduce` the shell
  durations are `0ms`; surfaces change state without travel.
- **Forced colours**: under `forced-colors: active` control borders use
  `CanvasText` and the focus ring `Highlight`.
- **Zoom**: usable at 200 % (the narrow breakpoints apply).
- All French UI strings address the user as « vous ».

## Validation

- `tests/unit/test_control_center_shell_layers.py`: registry against the real
  sheets, Cosmos without geometry or rank, controls marked, tokens once,
  reduced motion, mirror comment, shared selector read by scene and rail.
- `tests/unit/test_scene_renderer_logic.py::test_the_scene_layer_sits_above_the_face_and_below_every_control`:
  the scene's own rank relations.
- Runtime: both themes at 1440×900, 1280×720, 900×600 and 600×800 in headless
  Chrome on an isolated instance (no control overlapping another, scene
  objects stop against every control including `#chatTab`,
  `#interactionModeHud` and `#presentationRail`).
