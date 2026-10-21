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
`docs/ARCHITECTURE.md`; both now point here. Slices 02 to 09 of that handoff
filled it in as they landed (wheel, Selection method, capture wedges and
indicators, screenshot preview, status centre and eye, workspace rail, global
launcher, integration matrix); the release check of Slice 10 re-read it
against the code of the task branch at `9c2848cc` (every cited file, id and
test exists). Slice 02 of `tasks/jarvis-board-ui-wheel-dossier-refactor/`
then emptied the top-left zone (no Board selector, no permanent state line),
moved the Board control to a bottom-left **Board card** in place of the
interaction-mode control (removed with its chooser), and removed the permanent
hidden-object eye from the status centre (decisions D03-D06 of that handoff).

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
skin keeps its text labels in the launcher (`CNV`, `AGT`, `ERR`, `⋯`; `SET` folded into « Plus d’outils » since the wheel/dossier refactor Slice 04), at the shared
34 px size; Cosmos swaps them for icons. The launcher's order is the page's, the
same in both themes (since Slice 08 the Cosmos skin no longer reorders it). The top state line (`.topbar`, its
hidden `JARVIS` brand and the `.state` badge) no longer exists (Slice 02 of the
wheel/dossier refactor), so neither skin styles it.

## Zones

| Zone | Surfaces today | Owner of the content |
| --- | --- | --- |
| `top-left` | empty at rest (wheel/dossier refactor Slice 02, D05: no Board selector, no permanent state badge); since its Slice 04 the recording indicators `#recIndicators` (red `REC` for the screen, audio cue), only while Core lists an open capture — see [capture.md](capture.md) › *Interface* | `control_center_capture_wheel.js` |
| `top-right` | `.dock` (global launcher, Slice 08: one row of 34 px buttons — four since the wheel/dossier refactor Slice 04 folded Réglages into « Plus d’outils » —, the « Plus d’outils » popover under it; see [Global launcher](#global-launcher-dock)) | page |
| `top-centre` | `.live-banner` (GPT-Live, transient) | page |
| `left-edge` | `#toolWheel` anchor and orbital tool wheel (Slice 02; live by default since Slice 04; five categories since the wheel/dossier refactor Slice 03: JARVIS, Sélection, Dossier, Capture, Paramètres); `#barehandsHud`, `#barehandsPalette` hosts stay declared but hidden while the wheel is visible (Slice 03) | their modules |
| `left-low` | `#screenshotPreview` (Slice 05): preview of the last successful screenshot, right of the wheel anchor, its bottom 172 px above the page bottom so it clears the bottom-left context zone (Board card and scene notes stacked up to 162 px) | `control_center_screenshot_preview.js` |
| `bottom-left` | Board card `#boardsHud` (its panel `#boardsPanel` opens above it, see [Board card](#board-card-boardshud)), `.sc-status` notes of the scene | `control_center_boards.js`, scene |
| `bottom-centre` | status centre `#statusCentre` (Slice 06): `#bgPills` (the recording indicators moved top-left in the wheel/dossier refactor Slice 04), see [Status centre](#status-centre-statuscentre); `#boardDropTray` above it | page, `control_center_board_drop.js` |
| `bottom-right` | `#chatTab` | `control_center_chat.js` |
| `right` | active workspace rail `#presentationRail` (Slice 07, see [Workspace rail](#workspace-rail-presentationrail)); side panels (`#panel`, `#chatPanel`, `#jvStudioInspector`, and the relation board `#relationBoard` of organic-agent-orchestration Slice 09, class `.panel`, opened from a relation mark of the scene) open over it | `control_center_presentation_rail.js`, page, modules, `control_center_relation_board.js` |
| `centre` | Board / scene (`#sceneLayer`) | scene |

`JarvisShell.ZONES` mirrors this table (one line per zone).

Placement rules that hold in both themes (measured by
`tests/unit/test_control_center_shell_browser.py` at 1440×900, 1280×720,
900×600 and 600×800):

- **Top-left** is empty at rest (wheel/dossier refactor Slice 02). Since its
  Slice 04 it holds the recording indicators `#recIndicators` while, and only
  while, Core lists an open capture (top and left at `--shell-gutter`, chips
  wrapping downwards, never wider than the space left of the launcher). The
  wake key hint (`F9 · DÉMARRER`, `F9 · VOICE HORS LIGNE`…) and the
  voice/agent/sub-agent words of the old `.state` (`VOICE SLEEP · CLAUDE
  RUNNING`) are read in the wheel's **JARVIS** submenu (see [Tool
  wheel](#tool-wheel-toolwheel) › *JARVIS and Paramètres*); the hidden
  `#wakeHint` and `setWakeHint` are gone. The key itself is Voice's global
  shortcut, unchanged; the dock keeps the sub-agent count badge (`#agentBadge`).
- **Launcher** (`top-right`): one row of four 34 px buttons at
  `--shell-gutter`, at every width (Slice 08; four since the wheel/dossier
  refactor Slice 04); its popover opens under the row, right-aligned.
- **Side panels** (`right`): `#panel`, `#chatPanel`, the Studio inspector
  `#jvStudioInspector` and the relation board `#relationBoard` (one open at a
  time: opening one closes the others, `closePanel()` closes them all) share the zone: top `--shell-panel-top` (under the
  launcher and the pills), bottom `--shell-panel-bottom` (above the chat tab),
  right `--shell-gutter`, full width minus the gutters at 700 px and below.
  Toasts move left of an open panel from 940 px up.
- **Board drop tray** (`bottom-centre`): above the status centre,
  `bottom: calc(var(--shell-bottom) + var(--shell-status-h) + 8px)`; at 760 px
  and below it climbs under the launcher, below the rail tab row
  (`--shell-panel-top` + 40 px) and below the GPT-Live banner when it shows
  (CSS anchor `--jv-live`), + 8 px. With a side panel open it never runs
  under the panel: from 1100 px it is centred between the Board card zone
  (gutter + 254 px) and the panel; from 761 to 1099 px it climbs top-left,
  beside the panel (Slice 09).
- **Stacking by geometry, not by rank (Slice 09).** Surfaces whose height is
  only known at runtime are tied with CSS anchor positioning (Chrome/Edge
  125+): `.live-banner`
  (`anchor-name: --jv-live`) and `#boardDropTray` (`--jv-tray`). The GPT-Live
  banner is centred between the two columns and never covers the rail
  (`width: min(680px, 100vw - 2 × (gutter + --shell-rail-w + 12px))`;
  rail hidden or absent: `min(680px, 100vw - 2 × (gutter + 12px))`); at
  700 px and below it sits under the rail tab row (`--shell-panel-top` +
  48 px). Toasts sit left of the visible rail above 700 px (`right: gutter +
  --shell-rail-w + 12px`), rise above a visible bottom drop tray
  (`bottom: max(68px, anchor(--jv-tray top) + 8px)`), and at 700 px and below
  go under the rail tab, the banner and the tray (`top: max(--shell-panel-top
  + 48px, banner bottom + 8, tray bottom + 8)`). Under 940 px with a side
  panel open the toasts stay at the right, over the panel, for the length of
  a toast (no room on its left) — the one accepted overlap.
  **Fallback without anchors (QA S09 P1).** An unknown `anchor()` invalidates its whole declaration, so each
  anchored rule is preceded by a separate rule that sets the fallback value
  with the banner's bottom estimated by `--jv-live-fb` (set on `body` while
  `#liveBanner` shows: 118 px under `--shell-panel-top`, 166 px at 700 px and
  below; 110 px is the tallest banner measured, at 600 px): the tray goes
  under the rail tab row (`--shell-panel-top` + 48 px) or under that estimate,
  or + 8 px beside an open panel; toasts go under the same row or estimate,
  plus 8 px + `min(30vh, 200px)` when the tray shows; above a bottom tray:
  `bottom: --shell-bottom + --shell-status-h + 16 px + min(46vh, 360px)`.
  Without anchors nothing leaves the screen at 500-1280 px and the tray covers
  neither the launcher, the rail tab nor the banner
  (`test_without_css_anchors_the_fallbacks_hold`).
- **Screenshot preview vs Board card.** The preview's bottom rises with the
  scene notes exactly as the Board card's rung does
  (`+ max(0, --sc-status-h − 24px)`); at 640 px of height and below its card
  is compact (72 px thumbnail, two rows of actions) so it fits between the
  top of the page and the Board card, 200 % zoom included. With the Bare Hands
  badge shown the Board card takes the rail's second rung (86 instead of
  52 px, lifted 42 px under 820 px and 62 px at 700 px and below): the
  preview rises with it (`body:has(#jarvisHands .jh-badge)`: + 188 px under
  820 px, + 216 px at 700 px and below; QA S09 P2, matrix state 19 at
  600 × 800 with the real badge). When the wheel is
  reopened while the preview shows, the preview steps to the right of the
  wheel's radius (`#app:has(#toolWheel[data-open])`) so every wedge stays
  under the pointer (Slice 09).

## Tokens

Defined **once** on `:root` in `control_center.html`; no theme and no module
sheet redefines a `--shell-*` or `--sem-*` token. Responsive values are set
only in the `@media` blocks listed here. `JarvisShell.TOKENS` and
`JarvisShell.RESPONSIVE_TOKENS` mirror them (`test_tokens_defined_once_and_reduced_motion_zeroes_durations`).

| Token | Base | Responsive | Use |
| --- | --- | --- | --- |
| `--shell-gutter` | `18px` | `10px` at `max-width:700px` | distance of every edge surface to the window edge |
| `--shell-bottom` | `18px` | | bottom baseline of bottom surfaces |
| `--shell-status-h` | `44px` | | height of the bottom status centre (Slice 06); the drop tray and the lifted Board card sit above it |
| `--shell-control` | `34px` | | launcher button size |
| `--shell-launcher-w` | `154px` | | launcher width: 4 buttons × 34 + 3 gaps × 6 (Slice 08, then wheel/dossier refactor Slice 04: three tools and « Plus d’outils »), one row at every width; also bounds the top-left recording indicators |
| `--shell-panel-top` | `64px` | `88px` at 700 | top of side panels and of the GPT-Live banner (below the launcher; at 700 px and below, 88 px: the launcher row plus the narrow gutter) |
| `--shell-panel-w` | `500px` | | side panel width (capped by the window) |
| `--shell-panel-bottom` | `68px` | | bottom of side panels: they stop above the chat tab row (18 + 40 + 10), so the tab stays whole and clickable |
| `--shell-rail-w` | `300px` | `72px` at `max-width:1099px`, `0px` at 700 | workspace rail width (Slice 07); `0px` = the rail is a tab |
| `--shell-anchor-w` | `14px` | | visible part of the wheel anchor at rest (Slice 02) |
| `--shell-wheel-r` | `224px` | | wheel radius: rim of the category band (Slice 02; 200 → 224 px in the wheel/dossier refactor Slice 03, five labelled categories). The module scales the whole wheel with its own `--tw-scale` (`.86` / `.76` / `.84` on short or narrow windows, [Tool wheel](#tool-wheel-toolwheel)) |
| `--shell-wedge-min` | `48px` | | minimum target size of a wheel category (icon + label block; the whole sector is the target) |
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
| 30 | `#presentationRail` | `control_center_presentation_rail.js` | `#${DOM.hostId}` | workspace rail (right zone) outside the Studio; side panels (33) open over it |
| 32 | `.dock` | `control_center.html` | `.dock` | launcher |
| 32 | `#chatTab` | `control_center.html` | `.chat-tab` | page control of the same class as the launcher |
| 32 | `#barehandsHud` | `control_center_barehands_hud.js` | `#${DOM.hostId} .bh-hud-btn` | Bare Hands control button |
| 32 | `#barehandsHud` | `control_center_barehands_hud.js` | `#${DOM.hostId} .bh-hud-cap` | its state cap |
| 32 | `#boardsHud` | `control_center_boards.js` | `${H} .bd-btn` | Board card button (bottom-left, wheel/dossier refactor Slice 02); the host has no rank of its own |
| 33 | `.panel` | `control_center.html` | `.panel` | side panels (`#panel`, `#chatPanel`) |
| 34 | `.board-drop-card` | `control_center.html` | `.board-drop-card` | drop card, readable over the left column at 600 px |
| 34 | `#boardDropTray` | `control_center.html` | `.board-drop-tray` | drop tray, above the status centre and the chat tab |
| 34 | `#jvStudioInspector` | `control_center_presentation_studio_inspector_core.js` | `#${PANEL_ID}` | Studio inspector side panel, above the panel it replaces |
| 35 | `.live-banner` | `control_center.html` | `.live-banner` | GPT-Live banner over the controls |
| 36 | `.bh-hud-pop` | `control_center_barehands_hud.js` | `#${DOM.hostId} .bh-hud-pop` | Bare Hands lifecycle selector |
| 36 | `.dock[data-more-open]` | `control_center.html` | `.dock[data-more-open]` | launcher with its « Plus d’outils » popover open (Slice 08): the whole launcher rises to the choosers' rank, over the side panels and the banner it briefly covers |
| 37 | `#toolWheel[data-open]` | `control_center.html` | `#toolWheel[data-open]` | open wheel and its curved submenu: above the choosers, the wheel is the user's latest focus; never open together with `#boardsPanel` ([Exclusive surfaces](#exclusive-surfaces-wheel-and-board-panel)) |
| 38 | `#screenshotPreview` | `control_center.html` | `#screenshotPreview` | screenshot preview (Slice 05): transient, non-modal, above the open wheel that took the shot, below the status centre, toasts and the lightbox |
| 40 | `#recIndicators` | `control_center.html` | `#recIndicators` | recording indicators (orbital UI Slice 04), top-left since the wheel/dossier refactor Slice 04 (before: left of the status centre); an open recording stays visible above the open wheel and the side panels, below toasts |
| 40 | `#bgPills` | `control_center.html` | `.bgpills` | status centre, middle: background pills |
| 55 | `.tl` | `control_center.html` | `.tl` | conversation timeline, full-screen launcher view |
| 55 | `.tlab` | `control_center.html` | `.tlab` | Test Lab (one full-screen view at a time) |
| 55 | `.mcpi` | `control_center.html` | `.mcpi` | MCP inspector |
| 55 | `.wsp` | `control_center.html` | `.wsp` | Sessions & Boards |
| 55 | `.pfb` | `control_center.html` | `.pfb` | prefab library |
| 55 | `#dossierView` | `control_center.html` | `.dsr` | full-screen Dossier of the Board (wheel/dossier refactor Slice 07): one full-screen view among the others; below `.overlay`, toasts and the page confirmation; Variantes (9000) covers it, so it never opens while the Studio is shown ([Dossier](#dossier-full-screen-view-dossierview)) |
| 58 | `#boardsPanel` | `control_center.html` | `#boardsPanel` | Board chooser: a full-screen blurred veil over the whole page (Board picker redesign, 2026-10-19), opened from the bottom-left Board card; above the status centre (40) and the full-screen views (55) it never opens with, below `.overlay`, the toasts that report its actions and the page confirmation (archive, new session). Exclusive with the open wheel (37) since wheel/dossier Slice 03 |
| 60 | `.overlay` | `control_center.html` | `.overlay` | settings and modal overlays; the screenshot lightbox `#screenshotLightbox` and annotation editor `#screenshotAnnotate` (Slice 05) take the class, no rank of their own |
| 70 | `.toasts` | `control_center.html` | `.toasts` | toasts |
| 75 | `.bgpop` | `control_center.html` | `.bgpop` | background pill popover |
| 75 | `#jvStudioReloadBand` | `control_center_presentation_studio_reload.js` | `#${BAND_ID}` | Studio reload band |
| 80 | `.ctxmenu` | `control_center.html` | `.ctxmenu` | the one shared context menu, above the choosers it replaces |
| 82 | `#barehandsCards` | `control_center_barehands_hud.js` | `#${DOM.cardsId}` | Bare Hands quick cards, opened from the context menu |
| 84 | `.ntdetail-back` | `control_center.html` | `.ntdetail-back` | notification detail window (2026-10-23), opened from a background pill row or a sub-agent toast: above the pill popover it replaces, below the in-page confirmation |
| 85 | `.cdialog-back` | `control_center.html` | `.cdialog-back` | in-page confirmation |
| 9000 | `#jvStudioExplorer` | `control_center_presentation_studio_explorer_core.js` | `#${HOST_ID}` | Variantes (Studio explorer) |
| 9100 | `html.jvr-studio #presentationRail` | `control_center_presentation_rail.js` | `html.jvr-studio #${DOM.hostId}` | rail docked as the right column beside the Studio |
| 9150 | `html.jvx-run #boardsHud` | `control_center_presentation_studio_explorer_core.js` | `html.jvx-run #boardsHud` | Board card during a run shown in Variantes (Voice presence stays visible) |
| 9150 | `html.jvx-run #boardsPanel` | `control_center_presentation_studio_explorer_core.js` | `html.jvx-run #boardsPanel` | its panel during a run, above Variantes like the card |
| 9150 | `html.jvx-run #recIndicators` | `control_center_presentation_studio_explorer_core.js` | `html.jvx-run #recIndicators` | recording indicators during a run (`data-keep-live="run"`, wheel/dossier refactor Slice 04, QA B1): a screen or audio recording stays visible and stoppable over Variantes, top-left, over no Studio control; not shown in the stage's native fullscreen (`F`), by design |
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
| `.overlay` (60) | `control_center_wake_word.js` | `:is(#wakeWordSettings,#wakeWordDiagnostics) ` | settings and diagnostics tooltip |
| `#dossierView` (55) | `control_center_dossier.js` | `#dossierView` | its organisation and context drawers (narrow screens) above the reading pane, whose excerpt is masked (QA S07) |

### Inline ranks

Ranks written by script on an element (`style.zIndex` or `style['zIndex']`,
`Object.assign(el.style, {zIndex…})`, `style.setProperty('z-index', …)`, a `cssText` or a
`style="…"` attribute carrying `z-index`). Like contained ranks, they only
order children inside a page layer's stacking context. Any other inline rank fails
`test_inline_ranks_are_contained_and_listed` (Slice 09: the sheet test could not see them).

| Container | Sheet | Write | Why |
| --- | --- | --- | --- |
| `#sceneLayer` (20) | `control_center_scene_page.js` | `style.zIndex` | node stacking order (`node.stack`, raised window) inside the scene |

### Reserved ranks

None. The orbital shell reserved ranks 37, 38 and 40 for its later slices
while they were being built; all three are now page layers (open wheel 37,
Slice 02; screenshot preview 38, Slice 05; status centre children 40,
Slices 04 and 06). A new rank is added straight to the page layers table.

### Invariants

Checked on the registry rows by `test_relative_order_of_the_old_registry_is_kept`:

- every page control is above the scene (20); the face and the Cosmos canvas
  are below it;
- `#boardsHud` (card button) ≤ `.dock` < `.panel` < `.live-banner` <
  `#bgPills` < `#boardsPanel` < `.overlay` < `.toasts` < `.cdialog-back`;
- choosers (36), the open launcher popover among them, are above the GPT-Live
  banner (35) and below the pills, toasts, context menu and confirmation; the
  Board chooser `#boardsPanel` is a full-screen veil at 58, above everything
  the page shows at rest; it is never open together with the
  wheel (37): [Exclusive surfaces](#exclusive-surfaces-wheel-and-board-panel);
- the open wheel (37) is above the choosers and below rank 40 (the top-left
  capture indicators `#recIndicators` and the status-centre pills), toasts and context menu; closed, its
  anchor is at the left-edge rank (30);
- the screenshot preview (38) is above the open wheel and below the status
  centre (40), toasts and the lightbox (`.overlay`, 60);
- `.ctxmenu` (80) < `#barehandsCards` (82) < `.cdialog-back` (85);
- full-screen launcher views (55) are above every control and below
  `.overlay` < `.toasts` < `.ctxmenu` < `.cdialog-back`;
- Variantes 9000 < rail beside it 9100 < Board card, its panel and the recording indicators during a run 9150 <
  rail menu 9300 < rail dialog 9400;
- `#jarvisHands` is the top of the page.

**Cosmos rank collapse (Slice 01).** Cosmos used to raise `.topbar` (removed since) 45,
`.panel` 42, `.live-banner` 48, `.dock`/`.bgpills`/`.chat-tab` 50,
`.board-drop-tray` 49, `#boardsPanel` 51. `git log -S` traces them to the
theme's first commit (`2868528e`, "add Omega visual theme") and to slices
that kept "one above the Cosmos dock" (`98f28604`, `4b99853b`); none records
a stacking conflict. With the geometry shared, the surfaces they ordered no
longer overlap (panel and banner start at `--shell-panel-top`, below the
launcher row; the Board chooser opens above the bottom-left Board card at every width; every
side panel stops at `--shell-panel-bottom`, above the chat tab, where Cosmos
used to draw the tab over the panel's last row), so the base ranks apply to
both themes.

## Controls (`CONTROL_SELECTOR`)

A **control** is a page surface the scene must not slide under: a held object
stops against it. Every control host carries
the attribute `data-shell-control`; the shared selector is

```
[data-shell-control],#sceneLayer>.sc-status
```

published as `JarvisShell.CONTROL_SELECTOR` by `control_center_shell.js`, read
by the scene (`control_center_scene_page.js`, measured walls), which keeps an
identical fallback literal and journals `shell.missing` if the module is
absent. (Until Slice 04 the left capture rail also read it to dodge the other
controls; the wheel and the indicators are placed by the sheet instead.)

| Host | Zone | Declared by |
| --- | --- | --- |
| `.dock` | top-right | page |
| `#recIndicators` | top-left (wheel/dossier refactor Slice 04) | page (host); content by `control_center_capture_wheel.js` |
| `#bgPills` | bottom-centre (status centre) | page (host); content by `renderBackgroundPills` |
| `.live-banner` | top-centre | page |
| `#panel`, `#chatPanel` | right | page |
| `#barehandsHud`, `#barehandsPalette` | left-edge (hidden while the wheel is visible) | page (hosts) |
| `#toolWheel` | left-edge | page |
| `#presentationRail` | right | `control_center_presentation_rail.js` (creates the host and the attribute) |
| `#boardsHud` | bottom-left | page (host), `control_center_boards.js` (card) |
| `#boardDropTray` | bottom-centre | page |
| `#chatTab` | bottom-right | page |
| `#screenshotPreview` | left-low | page (host), `control_center_screenshot_preview.js` (content) |

Before Slice 01 the scene's literal list missed the bottom-left control (then
`#interactionModeHud`), `#chatTab`, `#presentationRail` and `#boardDropTray`: a held object could
stop under them. They are now measured. Not controls: transient layers that
open over everything by rank (choosers, menus, popovers, toasts, dialogs,
full-screen views, `#barehandsCards`) and the Studio surfaces.

`test_every_declared_control_host_matches_control_selector` checks that every
host in the page that the table names carries the attribute and that nothing
else does.

## Global launcher (`.dock`)

Slice 08, decision D11 of the handoff's resolved architecture. The former
right dock of ten buttons is a compact top-right launcher: **three frequent
tools visible, the seven others in a « Plus d’outils » popover** (four and six
until the wheel/dossier refactor Slice 04 folded Réglages). Nothing was
deleted or renamed: `<nav class="dock">` keeps every button with its id, its
label (`ERR`, `TRC`…), its attributes and its module wiring; only where the
button sits changed. The Board control is the bottom-left Board card
`#boardsHud` since Slice 02 of the wheel/dossier refactor (D04 answered
HV-08-01; before, it sat in the top state line); the interaction-mode control
was removed with its chooser (D03). The launcher holds no Board control.

**Destination matrix** (before = the Slice 01 row of ten; keyboard
shortcuts are those of `jarvis/runtime/shortcuts.py`, unchanged):

| Tool | Button | Before | After | Shortcut |
| --- | --- | --- | --- | --- |
| Conversation (timeline) | `#openTimeline` `CNV` | dock row | **visible** | — |
| Agents (+ count badge `#agentBadge`) | `#agentsButton` `AGT` | dock row | **visible**, badge never behind a click | `a` |
| Erreurs (+ badge `#errorBadge`) | `[data-panel=errors]` `ERR` | dock row | **visible**, badge never behind a click | `e` |
| Réglages | `#openSettings` `SET` | dock row | « Plus d’outils » (first line) since the wheel/dossier refactor Slice 04; the wheel's **Paramètres** category opens the same surface, one row per settings tab | `s` |
| Trace | `[data-panel=trace]` `TRC` | dock row | « Plus d’outils » | `t` |
| Test Lab | `#openTestLab` `LAB` | dock row | « Plus d’outils » | — |
| MCP inspector | `#openMcpInspector` `MCP` | dock row | « Plus d’outils » | — |
| Sessions & Boards | `#openWorkspace` `WSP` | dock row | « Plus d’outils » | — |
| Prefabs | `#openPrefabs` `PFB` | dock row | « Plus d’outils » | — |
| Studio inspector | `#openStudioInspector` `INS` | dock row | « Plus d’outils » | — |
| Board | `#boardsHud` | top state line | bottom-left Board card (wheel/dossier refactor Slice 02) | — |
| Interaction mode | `#interactionModeHud` | bottom-left | removed (D03: the mode follows the Board type) | — |

`SET` was the fourth visible tool until the wheel's Paramètres went live:
Slice 04 of the wheel/dossier refactor folded it into « Plus d’outils » (same
id, label, `title`, `aria-label` « Réglages », `data-dock-label`, shortcut `s`;
the Cosmos skin keeps its icon).

`Escape` (`ui_close`) closes the popover first when it is open (topmost
transient), then the side panel as before.

**Row.** `CNV`, `AGT`, `ERR`, then `#dockMore` (three dots,
`aria-label` = `title` = « Plus d’outils », `aria-expanded`,
`aria-controls="dockMorePop"`), in this order in both themes; 4 × 34 px +
3 × 6 px = `--shell-launcher-w` (154 px), one row at every width. Popover
order: Réglages, Trace, Test Lab, MCP, Sessions & Boards, Prefabs, Inspecteur.

**Popover** `#dockMorePop` (`role="group"`, inside the launcher, hidden by
default): a list under the row, right-aligned, each tool on one 36 px line
with its label or icon and its short name (`data-dock-label`, drawn by CSS;
the accessible name stays the button's own). Open, the launcher carries
`data-more-open` and rises to rank 36 (registry row `.dock[data-more-open]`).

| Input | Effect |
| --- | --- |
| Click on « Plus d’outils » (mouse, Bare Hands pinch) | opens or closes; focus stays on the button |
| `Enter` / `Space` / `ArrowDown` on it | opens, focus on the first tool; `ArrowUp` on the last |
| `ArrowDown` / `ArrowUp` (wrapping), `Home` / `End` | move in the list (roving `tabindex`: one tab stop) |
| `Escape` | closes, focus back on « Plus d’outils » |
| activating a tool | the tool opens as before, the popover closes |
| `pointerdown` outside, `Tab` out | closes |

Focus is never left on a hidden element: a view that gives the focus back to
its button (Test Lab, MCP, Prefabs…) while that button sits in the closed
popover gives it to « Plus d’outils » (a `focus` method set on each folded
button: a call through `HTMLElement.prototype.focus.call(button)` would bypass
it — no page code does; a fallback in every view's close path was judged not
worth it, QA S08 P5). While a popover tool is open (`active`
or `aria-expanded="true"`), « Plus d’outils » shows the accent and a dot and
names it in `aria-description` (« Ouvert : Trace »): state is not hidden by the
fold, and not by colour alone.

**Journal.** `[launcher] launcher.installed {visible, more}`, `.open
{reason: pointer|keyboard}`, `.close {reason: toggle|escape|activate|outside|blur}`,
`.install_failed {code: launcher_host_missing}` (the page keeps its row; the
popover tools then stay unreachable by mouse but keep their shortcuts — the
markup declares every host, so this only fires if the page itself is broken).

**Tests.** `tests/unit/test_global_launcher_browser.py` (served page, the
status-centre fetch double, both themes, 1440×900, 1280×720, 900×600,
600×800): every pre-refactor tool has a route, popover keyboard (roving,
`Escape`), badges visible closed, Board card visible bottom-left and
switching, no Board or mode control in the launcher. The dock slicers
(`test_control_center_mvp.py`, `test_prefab_library.py`,
`test_control_center_mcp_inspector_js.py`, …) keep reading
`<nav class="dock">`.

## Board card (`#boardsHud`)

Slice 02 of `tasks/jarvis-board-ui-wheel-dossier-refactor/` (D04, D05, D03).
Module `jarvis/runtime/control_center_boards.js` (`window.JarvisBoardsControl`),
the same control that sat in the top state line, moved; contract of its data
and actions: [boards.md](boards.md) › *Control Center Boards control*.

**Place.** Zone `bottom-left`, the envelope of the interaction-mode control it
replaces: `left: 18px`, 168 to 236 px wide (`GEO`; up to 320 px from 1400 px,
`GEO.wideMaxWidth`, the title on up to two lines, so a long title is not cut on a
large screen), bottom on the shared
bottom-left rail (`--bd-rail`: 22 px, 52 above the Bare Hands badge or a scene
note, 86 above both or the gesture note, `max(…, --sc-status-h + 28px)` for a
multi-line note), lifted 42 px under 820 px (above the status-centre row) and
moved right of the Bare Hands column at 700 px and below (`left: 84px`, lift
62 px). Same rail convention as `.sc-status`
(`body:has(#jarvisHands .jh-badge)`, checked by
`test_barehands_contracts_js.py`). Because the envelope is unchanged, the
status-centre insets (gutter + 254 px), the screenshot-preview rungs and the
drop-tray centring keep their values, re-attributed to the card. The chooser
`#boardsPanel` is a **full-screen veil** over the page (dark, blurred), one
screen at a time: the grid of Boards (one large orb per Board, the type icon
inside, the title under it; rename / inspect / archive appear on hover or
keyboard focus), then creation in two steps — the type (three large orbs),
then the title (one large field). Escape goes back one screen, then closes;
a click on the veil itself closes.

**Content** (compact, two to four short lines): the type icon (Assistant =
speech bubble, cyan; Présentation = screen on a stand, violet; Réunion = three
people, amber; unknown = neutral frame) and the type word, then the title.
A Réunion Board reads « Réunion · prévu » and « Agit en Assistant » on the
card (D24; its full sentence is in the name). The sub-line says a pending
switch with its live counter, `Core ne répond pas`-style unavailability, the
number of Boards working in the background. The Voice **presence line** of a
PRESENTATION session (« Écoute la salle », « Sourd à la salle », « Refusé par
la voix », « Entrée échouée », « Séance inactive »; code in `title`) shows
whenever the effective mode is PRESENTATION (a Présentation Board, or a Studio
run); refusal and failure also turn the card's stroke red. It moved here
from the removed interaction-mode control (critical feedback kept, D05).

**Studio run.** `data-keep-live="run"` on the card and its panel; during a run
shown in Variantes both are drawn at 9150, in the rail's right column when the
Studio is windowed (`html.jvx-run.jvr-studio #boardsHud`). The way out of a
run is the Studio's own stop; the card adds no mode toggle. The page layers the
panel would open (the confirmation `.cdialog-back`, 85; the Sessions & Boards
manager `.wsp`, 55) stay **under** Variantes, so during a run the panel turns
off the actions that open them — Archiver, Nouvelle session, Inspecter —
(`aria-disabled`, tooltip and help line « Indisponible pendant la lecture… »,
journal `boards.action_blocked_during_run`); switching, creating and renaming
open no layer and stay available; everything comes back at the next status beat
after the run (QA Slice 02, B1;
`test_variants_run_browser.py::test_during_a_run_the_board_panel_opens_no_hidden_layer`).

**Accessibility.** One button (`aria-haspopup="dialog"`): its name starts
with what it shows (type then title), then the planned note and the presence
sentence, then « Ouvrir la liste des Boards »; `ArrowDown` opens; `Escape`
closes and returns focus. The presence has its own polite live region
(`#boardsPresenceAnnounce`), said once per change.

**Journal.** `[boards] boards.voice_presence_shown {state, code}` (`warn` for
a refusal or failed entry, `info` otherwise), plus the existing
`boards.*` lines.

**Tests.** `tests/unit/test_boards_hud_js.py` (type, planned Réunion,
presence per state, never optimistic, stale refusal, deletion assertions),
`tests/unit/test_boards_card_browser.py` (geometry against the Bare Hands
palette, toasts and status centre; presence on a real Control Center),
`tests/unit/test_boards_hud_browser.py`.

## Status centre (`#statusCentre`)

Slice 06, decisions D8 and D9 of the handoff's resolved architecture. Replaces
the bottom-centre `F9 · DÉMARRER` capsule, the background pills of the
top-right corner and the scene's « N objets masqués » note. The permanent
hidden-object eye it introduced was removed by Slice 02 of the wheel/dossier
refactor (D06: hidden is temporary, not a storage area); see *Hidden objects*
below. The recording indicators `#recIndicators`, its first item until then,
moved to the **top-left** zone in Slice 04 of the same refactor
(`docs/06-ui-visual-spec.md` › E of that task; [capture.md](capture.md) ›
*Interface*): the row now holds the background pills only. When a status
beat fails, the pills keep their last counts but say they are unconfirmed
(`#bgPills[data-unconfirmed]`: dashed, dimmed, each accessible name ends with
« compte non confirmé : Jarvis ne répond pas »), until the next beat that
succeeds (Slice 08, `test_status_centre_browser.py::test_a_lost_status_says_the_pill_counts_are_unconfirmed`).

**Place.** `#statusCentre` (`.status-centre`) is a **layout only**: one row,
centred, `bottom: --shell-bottom`, `min-height: --shell-status-h` (44 px), so
its top (62 px) stays below the bottom of the side panels and of the
workspace rail (`--shell-panel-bottom`, 68 px) and below the toasts. No rank
and no `transform` on it (a transform would open a stacking context and
shut its children under the scene); each of its children carries rank
40. Symmetric side insets keep it centred: `--shell-gutter` + 254 px above
820 px (the Board card is at most 236 px wide, bottom-left, `GEO.maxWidth` of
`control_center_boards.js`), `--shell-gutter` + 338 px from 1400 px (card up to
320 px, `GEO.wideMaxWidth`), `--shell-gutter` + 64 px below (the Board card
lifts above the row there; only the chat tab, 52 px, is left on the row). Too many chips: the row wraps upwards. With a side
panel open and 1100 px or more, it re-centres in the free space left of the
panel; narrower, it stays under the panel's bottom gap without touching it.
Pointer events pass through except on its controls. (The right-edge column
the recording chips took at 700 px and below is gone with them: they live
top-left at every width since the wheel/dossier refactor Slice 04.) The scene's `.sc-status` notes stop before the
row's reserved width above 820 px and **wrap** there (never an ellipsis: a frozen
scene's cause, « Control Center injoignable », must stay readable; the whole
text is also the note's `title`); they sit above the row (66 px) at 820 px and
below. The scene publishes their height as `--sc-status-h` on the page and the
Board card's rung is `max(52px, --sc-status-h + 28px)` (`max(86px, … + 62px)`
with the Bare Hands badge), so a multi-line note never slides under it (S06
rework, QA B1).

| Order | Host | Owner | What it shows |
| --- | --- | --- | --- |
| 1 | `#bgPills` | page, `renderBackgroundPills` (`BG` state) | one 32 px round pill per unread category, in `BG_CATS` order: `failed` (alert triangle, `--sem-alert`), `attention` (question, `--sem-question`, « points à vérifier »), `done` (check, `--sem-done`), `said` (speaker crossed out, muted, F8). Inline SVG icon, the count in a badge, `aria-label` = `title` = the `pillLabelOf` text (category + count + other-Board share); the other-Board satellite sits bottom-right. Popover `#bgPop` opens **above** the pill, centred on it and bounded to the screen; ack, sound cue, multi-tab leader, Board-elsewhere attribution and « Aller sur « X » » are unchanged (same code and ids) |

**Hidden objects (no permanent control since the wheel/dossier refactor
Slice 02, D06).** The eye `#hiddenEye` is gone for good: since Slice 06 the
count and the commands live only in the wheel › **Sélection › « Afficher les
masqués (N) »** (« Voir en fantômes », « Tout réafficher (N) », « Réafficher « … » »
for up to six named objects), or « Aucun objet masqué » as a status row
([scene-selection-batch.md](scene-selection-batch.md) › *Selection actions
(wheel)*). The page code for the host (`syncEye`, `wireEye`, `openHiddenMenu`) is
removed; `toggleGhosts` and `V.hiddenEye` (count, pressed) stay.

**Ghosts.** With « Voir en fantômes » on, the scene draws every hidden object **that has a
stored place** as a ghost at that place (`JarvisSceneLayout.viewModel`
`options.showHidden`, `node.ghost`): 42 % opacity, desaturated, dashed ring or
outline, no animation, accessible name suffixed « masqué ». A ghost is not
placed by the resolver, is no obstacle, carries no link, no constellation and
no signal, cannot be dragged or moved by keys (it has no layout placement),
and its context menu has one entry, « Réafficher » (`showObjects([id])`: one
`set_visibility visible`). A hidden object without stored geometry has no
ghost (an invented place would not be its own); it stays reachable in the
Sélection list. Per-object visibility is never touched by the ghost view: it is a view
decision of this browser (`jarvis.scene.view`), never sent to Core
([scene-model.md](scene-model.md) › Visibility).

**Journal.** `[scène] scene.hidden_view {show, hidden, ghosts}`, `.hidden_view_inert`,
`.user_shown {asked, shown, op}`; pills keep `[background]` lines.

**Tests.** `tests/unit/test_status_centre_browser.py` (served page, fetch
double for status, background, ack and scene; both themes; 1440×900,
1280×720, 900×600, 600×800; the recording chip measured top-left, out of the
row, overlapping none of the card, chat tab, rail, wheel anchor, launcher,
tray or scene notes), `tests/unit/test_scene_view_prefs.py`
(`showHidden`), `tests/unit/test_scene_renderer_logic.py` (ghosts, one
reveal = one `set_visibility`).

## Workspace rail (`#presentationRail`)

Slice 07, decision D10 of the handoff's resolved architecture. Module
`jarvis/runtime/control_center_presentation_rail.js` (`window.JarvisPresentationRail`);
data, actions and Core contract: `docs/presentation-studio.md` › *Rail des
presentations* › *Active workspace rail*.

**Place.** Zone `right`: top `--shell-panel-top` (under the launcher and the
pills), right `--shell-gutter`, bottom at most `--shell-panel-bottom` (above
the chat tab), width `--shell-rail-w`. It never covers the left column, the
launcher, the pills or the chat tab (`test_rail_right_no_overlap_launcher_chat_tab`,
1440×900, 1280×720, 900×600, 600×800). Side panels (33) open over it.

**Densities** (`JarvisPresentationRailCore.densityOf`, from the window width):

| Density | When | Card |
| --- | --- | --- |
| `full` | ≥ 1100 px | 300 px: preview 88 px 16:9 with type badge, title (2 lines), type · variants, dot + state label · age, « ⋯ » |
| `slim` | < 1100 px, or folded by the user | 72 px: preview + dot; the title, type and state label show in a bubble beside the card on hover and focus |
| `drawer` | ≤ 700 px (`--shell-rail-w` = 0) | a tab (title, count, most urgent dot); its button opens the list over the scene and closes it |
| `compact` | beside the Studio | 172 px column: small preview, title, dot + label |

**Studio docking** is the mirror of the old left docking: with Variants open
(windowed) the rail is the right column (`html.jvr-studio`, rank 9100, 8 px
from the edges) and `#jvStudioExplorer:not(:fullscreen)` stops at
`right: 188px` (60 px when slim); during a run the Board card (and its
panel) sits at the bottom of that right column, above Variantes, so Voice's
presence line stays visible (`control_center_presentation_studio_explorer_core.js`).
The page under the Studio is inert; the launcher and the chat tab, which it
covers, are not drawn meanwhile (`html.jvr-studio .dock, #chatTab
{visibility:hidden}`: a half CNV button showed, unclickable, in the 8 px gap
before the rail). In that column the rail title tightens and may wrap
(« PRÉSENTATIONS » / « (1) »), never cut (QA S09 P7, matrix state 9).

**State, never by colour alone.** Every card shows a mark with its own
**shape** in every density (also in the 72 px strip, where the label shows
only on hover and focus) **and** a label: `working` « En cours »
`--sem-working`, pulsing ring; `problem` « Problème » `--sem-problem`,
triangle and an orange-red card stroke (never relabelled as review);
`unreviewed` « À revoir » `--sem-review`, diamond; `done` « Prête » / « Prêt »
`--sem-done`, check; `unknown` « État inconnu », dashed hollow ring. Precedence
working > problem > unreviewed > done.

**Stage B.** A second listbox « Sur ce Board » under the presentations shows the Artifacts linked to the active Board in the same cards
(adapter `control_center_workspace_rail_model.js`, contract in `docs/presentation-studio.md` › *Active workspace rail*); it scrolls on its own
(at most 42 vh) and hides in the closed tab.

**Focus.** The list is one listbox (arrows, `ContextMenu` / `Shift+F10`, `F2`,
`Delete`); the « ⋯ » button is a pointer and Bare Hands affordance with
`tabindex=-1`. The list is rebuilt on every Core read and the focused card
keeps the focus, wherever it is (main list, « Sur ce Board », the Masquées /
Archivées folds); closing a card's menu with `Esc` returns the focus to that
card even if it was redrawn meanwhile (restored by its id).

## Tool wheel (`#toolWheel`)

Slice 02 of the orbital-UI handoff (decisions D3 and D4 of its resolved
architecture) created the surface; **Slice 03 of
`jarvis-board-ui-wheel-dossier-refactor` replaced its information
architecture and its graphics** (five categories, one curved submenu,
`tasks/jarvis-board-ui-wheel-dossier-refactor/docs/06-ui-visual-spec.md` › B).
Module `jarvis/runtime/control_center_tool_wheel.js`
(`window.JarvisToolWheel`), served by `ControlCenter.index`
(`TOOL_WHEEL_SCRIPT_FILE`). A **new surface**: not the Bare Hands palette, not
the capture rail. Orbital-UI Slice 03 moved the palette (and the top-left
lifecycle control) into Selection (see Selection method below); orbital-UI
Slice 04 moved the left capture rail into the wheel plus the persistent
indicators `#recIndicators` ([capture.md](capture.md) › *Interface*).

**Live by default.** No flag: the module builds the anchor and the wheel at
install and un-hides its host. The host stays declared `hidden` in the page,
so if the module fails to install the wheel never shows and the Bare Hands
column comes back by itself. Rollback = hide or remove `#toolWheel` (the
column returns, `body:has(#toolWheel:not([hidden]))`); the capture views then
have no category but the indicators still show and stop open recordings.

**Closed.** Only the anchor shows: a `--shell-anchor-w` (14 px) × 112 px
glass tab with a thin luminous cyan line, centred on the left edge, `<button
aria-haspopup="menu" aria-expanded="false">` named « Outils » (`aria-label` =
`title`). Nothing else of the wheel takes workspace at rest.

**Reveal.** One wheel, three ways in, none of them network-bound:

| Input | Reveal | Focus |
| --- | --- | --- |
| Mouse | `pointerover` on the anchor (not while the Board panel is open, see [Exclusive surfaces](#exclusive-surfaces-wheel-and-board-panel)) | not moved (hover highlights only) |
| Bare Hands | the synthetic hand pointer (`pointerId` 9001-9002, `JarvisBarehandsContracts.isBareHandsPointerId`) reaching the anchor: the same `pointerover`; a pinch on the anchor is a `click` (`detail` 0, but its source is read from the preceding Bare Hands `pointerdown`, so it is a pointer, not the keyboard) | not moved |
| Keyboard | `Enter` / `Space` (native `click`, `detail` 0) or `ArrowRight` on the anchor | first (or last highlighted) category |

No new Bare Hands gesture (a "leftward reveal" gesture is deferred,
`tasks/jarvis-board-orbital-ui-workspace-rail/Issues/bh-left-reveal-gesture.md`).
Pointer movement elsewhere on the page never opens the wheel: it only listens
on its own host.

**Open: a layered half-disc.** Rank 37, centre on the left edge, radius
`--shell-wheel-r` (224 px), three layers (`GEOMETRY`):

1. the **core** (radius 76 px, `hubRadius`): a restrained luminous Jarvis cue
   with fine ticks; nothing activates there. It carries the **readout** of the
   highlighted category (`#toolWheelLabel`: its name, then the state its
   action projects, e.g. « SÉLECTION / Souris »);
2. the **category band**, from the core to the rim: exactly five categories in
   this locked order — **JARVIS, Sélection, Dossier, Capture, Paramètres**
   (`JarvisToolWheel.SLOTS`, ids `jarvis`, `selection`, `dossier`, `capture`,
   `settings`). No filler and none of `boards`, `fichiers`, `recherche`,
   `outils`, `vidéo`, `screenshot`, `audio` at this level. They share 170°
   equally (34° each); each whole sector, core to rim, is the pointer target
   (`clip-path`), so a hand never falls into a gap. Each sector shows a 24 px
   line icon (1.5 stroke, round caps) and its **always visible** label (small
   uppercase), centred 150 px from the centre, 89 px apart along the arc
   (minimum: target + 8 px, `minSeparationDeg()`). Thin radial separators, a
   thin cyan rim, a dashed texture ring;
3. the **submenu**: one curved dark-glass panel against the rim (below).

The **highlighted / selected** category (hovered, focused, or owner of the
open submenu) gets a brighter cyan sector outline with a restrained inner
fill and a bright arc on the rim (`.tw-sec.is-on`, `.tw-arc.is-on`); the
others stay quiet (muted icon, no glow).

**One category tree at a time.** Every category registers `menu:true`:
primary activation (click, `Enter`, `Space`, Bare Hands pinch), its secondary
activation, or `ArrowRight` on it opens **its** submenu. The submenu is a
curved glass panel (`layoutSubMenu`): its concave inner edge follows the arc
`subInner` (238 px) just outside the rim, its rows (50 px, 256 px wide; a
long list tightens to 40 px, nine rows fit) are stacked around the height of
the parent sector and kept within the wheel's height, each row's left edge
following the arc; the inner edge facing the parent sector is lit
(`.tw-sub-link`), so the panel reads as attached to its sector. A small
uppercase heading names the tree (`SLOTS[].heading`: « État de Jarvis »,
« Sélection », « Dossier du Board », « Capture », « Paramètres »; at the
second level, the parent entry's label). Activating another category
**replaces** the open submenu (the module mounts exactly one `.tw-sub`, and
the reducer holds one `sub`); closing removes it; hovering another category
closes it. The category whose tree is open has `aria-expanded="true"`.

**Activation.** Primary = `click` only: mouse click, `Enter` / `Space`, Bare
Hands primary pinch. Never `pointerup`, so the Bare Hands sequence
(`pointerdown`, `mousedown`, `pointerup`, `mouseup`, `click`) fires once.
Secondary = the existing channel (D4): `contextmenu` (right click, Bare Hands
thumb + middle pinch), `ContextMenu` key, `Shift+F10`; a keyboard secondary
followed by the browser's own `contextmenu` on the same target within 500 ms
counts once (the dedupe is reset when the wheel closes or a second level
returns). Never long press. A Bare Hands `contextmenu` is attributed to
`barehands` from the `pointerId` of the last `pointerover` on the wheel.

**Injected actions.** `JarvisToolWheel.register({id, onActivate(ctx),
onSecondary?(ctx), menu?})` binds a category (unknown id → `TypeError`, code
`tool_wheel_unknown_slot`) and returns an unregister function; a new
registration replaces the previous one. `ctx` = `{slot, source:
'mouse'|'barehands'|'keyboard'}`. The wheel is not a domain owner: what a
category does comes from its registrant.

| Category | Registrant | Tree today |
| --- | --- | --- |
| JARVIS | `control_center_jarvis_wheel.js` (Slice 04) | status rows Voix, touche d'éveil, Agent; actions Sous-agents, Réglages de la voix — see *JARVIS and Paramètres* below |
| Sélection | `control_center_input_arbitration.js` (method rows) + `JarvisScene.selectionMenu` (Slice 06, action rows) | Souris / Bare Hands (then Bare Hands › tools, Veille, Aide, Diagnostic, Calibration); then the selection: a count, Ranger dans le Dossier, Masquer, Masqués (N) ›, Changer la forme ›, Retirer du Board… — or « Aucun objet sélectionné » and the hidden row — see *Selection actions* below |
| Dossier | `control_center_dossier.js` (Slice 07) | **no tree**: a click opens the displayed Board's Dossier directly (same path as « Ouvrir le Dossier », `dossier.wheel_open`); refused with a toast and its reason when the Board is unknown (status lost) or Variantes covers the screen — see [Dossier full-screen view](#dossier-full-screen-view-dossierview) |
| Capture | `control_center_capture_wheel.js` | Capture d'écran, Enregistrer l'écran, Enregistrer l'audio, each with its second level (stop list, then Core's real targets); live while open (`refresh`) — [capture.md](capture.md) › *Interface* |
| Paramètres | `control_center_jarvis_wheel.js` (Slice 04) | one row per Settings category (`settingsTabs()`, the six registry categories since Slice 02 of jarvis-settings-ui-reorganization), each opens Settings on that category |

Every category is registered by its module; the wheel keeps no placeholder
(the Slice 03 `PLACEHOLDERS` waiting rows were removed in Slice 08, once Dossier
was wired). A category with no
registration at all (its module failed to install, see `…install_failed` in the
console) is `aria-disabled`; activating it journals `tool_wheel.unbound` and
shows « <catégorie> indisponible — son module ne s'est pas chargé ». A callback that throws or
rejects is journalled (`tool_wheel.action_failed`, real cause) and shown as a
notification; the wheel itself is unaffected.

**Category status.** `JarvisToolWheel.setStatus(id, {icon?, tone?:
'error'|'wait'|'unknown', text?, checked?, live?} | null)` lets an action
**project** its owner's state onto its category (Selection: the current
method; Capture: the sum of its three channels): `icon` swaps the glyph (an
`ART` key), a badge marks `error` (« ! », `--sem-problem`), `wait` (spinning
ring, `--sem-working`, static under reduced motion) or `unknown` (« ? »,
muted, dashed; capture status lost), and `text` joins the category's
accessible name (`Sélection — Souris`, `Capture — Audio : en cours`) and the
core readout. `live` (Slice 03) marks something running inside the tree (an
open recording): amber icon plus a filled corner dot, readable without colour
since the sentence is in the name. `checked` (boolean) turns the sector into a
`menuitemcheckbox` (kept for compatibility; no category uses it today). The
anchor carries the worst projected tone (`data-tw-tone`, coloured stroke +
« ! » / « … » mark, `aria-label`/`title` `Outils — <text>`), so a failure or a
pending start stays visible with the wheel closed. The wheel stores nothing
else (journal `tool_wheel.status`).

**Submenu entries.** `onSecondary` returns `[{id?, label, disabled?,
checked?, toggle?, status?, icon?, note?, detail?, tone?:
'error'|'wait'|'busy'|'unknown'|'off', menu?, onActivate?(ctx),
onSecondary?(ctx)}]` (or a promise; « Chargement… » shows while it is
pending). `status:true` (Slice 04) is a **status row**: a fact, not a command
(`data-tw-kind="status"`, `aria-disabled="true"`, still focusable and read in
full); no tile frame, full-contrast label, the current value as an accent
note. `tone:'unknown'` marks an unconfirmed fact (dashed tile, « ? » before
the note), `tone:'off'` a muted value (Voice offline). Activating an inert
entry (status row, `disabled`, or neither `onActivate` nor `onSecondary`)
does nothing and **keeps the wheel open** (`tool_wheel.item_inert`; QA S03
polish 1). A row = an icon tile (`icon`, an `ART` key; `ART` is
published as `JarvisToolWheel.ART`), the label, a short muted `note` under it,
a chevron when it has a second level (`aria-haspopup="menu"`); `detail` is the
long sentence that goes into the accessible name and the tooltip; `tone`
colours the tile and the note (`busy` = amber, an open recording); `id` is
exposed as `data-tw-item`. Roles: `menuitem`, or with a boolean `checked`
`menuitemradio` (a choice, e.g. Souris / Bare Hands) or, with `toggle:true`,
`menuitemcheckbox` (something switched on, e.g. a recording). Labels go through
`textContent`. `ArrowUp` / `ArrowDown` / `Home` / `End` move, `Esc` or
`ArrowLeft` return to the parent category.

**Live refresh.** `JarvisToolWheel.refresh(id)` (Slice 04) re-reads the
first level of `id`'s submenu **if it is open** (not at the second level,
whose choices may need a network read; not if the action returns a promise)
and redraws it only when its rows changed (`tool_wheel.refreshed`), keeping
the highlighted row and the keyboard focus on the same line. Capture calls it
at every controller paint, JARVIS at every status beat. Returns `true` when it
redrew.

**JARVIS and Paramètres** (`jarvis/runtime/control_center_jarvis_wheel.js`,
`window.JarvisRuntimeWheel`, served after the Capture views; Slice 04 of the
wheel/dossier refactor, `docs/06-ui-visual-spec.md` › C and F of that task).
At this HEAD neither Core nor the Control Center exposes a route to put Voice
to sleep or wake it, nor any thinking / focus / autonomy mode: **the JARVIS
submenu states, it does not pilot**. Its only source is the page's one status
beat: `refreshStatus` calls `JarvisRuntimeWheel.gate(status)` with the
`/api/status` body and `statusLost()` when the read fails; the module polls
nothing and keeps no truth of its own.

| Row | Kind | Source (`/api/status`) | Shown |
| --- | --- | --- | --- |
| Voix | status | `voice_online`, `voice_state`, `voice_stack_label` | `Veille · SLEEP`, `Attente · WAIT`, `Écoute · LISTEN`, `Parole · TALK`, `Réflexion · THINKING` (the orb words), an unknown state as is in capitals, `hors ligne` (muted) |
| touche d'éveil | status | `manual_wake_key`, `voice_turn_mode`, `voice_state` | what the key does now (`F9 · DÉMARRER`, `F9 · ENVOYER` / `ANNULER`, `F9 · INTERROMPRE`, `F9 · VOICE HORS LIGNE`), note `tour automatique` / `tour manuel` — the former `#wakeHint` |
| Agent : <nom> | status | `agent.name` / `agent_cli`, `agent.state`, `agent.model` | `actif`, `arrêté`, `en erreur` (error tone)…, model in the long name |
| Sous-agents | action | `subagents.active` | `N en cours` / `aucun en cours`; opens the Agents panel (`#agentsButton`, the launcher's route) |
| Réglages de la voix | action | — | opens the settings modal on the Voix tab (`openSettingsTab('voice')`) |

Before the first beat every fact says `état inconnu` (`pas encore lu`); after
a failed beat, `état inconnu` (`statut du Control Center illisible : rien
n’est confirmé`), tone `unknown`: the last known state is **never** kept. The
JARVIS category projects a short sentence on its sector and the core readout
(`voix : veille · 2 sous-agents`, `état inconnu, statut illisible` with a muted
« ? » that does not colour the anchor). An open JARVIS submenu follows the
beat (`refresh`). No Veille / Réveil, Pause or mode row is drawn: a click-to-
sleep/wake control needs a canonical Voice lifecycle route first (follow-up,
not invented here). **Paramètres** lists the six Settings categories
(`settingsTabs()`, read from `JarvisSettingsRegistry.CATEGORIES` since Slice 02
of jarvis-settings-ui-reorganization; see `docs/settings/settings-shell.md`),
each row opening the same Settings as `#openSettings` on that category
(`openSettingsTab(category)`: location set before opening, or `selectTab` when
already open). « Réglages de la voix » opens `'voice'`: Voix & audio, tab Voix. Journal `[jarvis] jarvis_wheel.installed`,
`.menu`, `.settings_menu`, `.facts {read, hint}` (only when a fact changes),
`.open_agents`, `.open_settings {tab}`, `.route_missing`, `.paint_failed`,
`.install_failed`. Tests: `tests/unit/test_jarvis_wheel_js.py` (pure model),
`tests/unit/test_jarvis_wheel_browser.py` (served page: three sizes, live
beat then status lost with the submenu open and the focus kept, the two
routes, a settings tab, no extra status read).

**Second level.** An entry that carries `onSecondary` opens, on its secondary
activation (right click, thumb + middle pinch, `ContextMenu`, `Shift+F10`), on
`ArrowRight`, or on primary activation when its `menu` (boolean or function
read at each click) is true, a second list **in place of** the first, inside
the same category tree, centred on the parent row. `Esc` / `ArrowLeft` return
to the first level with the parent entry focused; journal
`tool_wheel.item_secondary`.

**Close.** `Esc` closes the topmost layer only (second level, then submenu,
then wheel; with the focus elsewhere in the page, `Esc` still closes a
pointer-opened wheel), activating an entry (or a category without tree), a
`pointerdown` outside (document `pointerdown` and `keydown` listeners present
**only while open**), focus leaving the host (`Tab` away: no focus trap),
another exclusive surface opening (`tool_wheel.close {reason: exclusive}`),
and — when the wheel was opened by a pointer and **no submenu is open** — the
pointer leaving it for 400 ms (grace covering the gaps between anchor, sectors
and submenu; Bare Hands sends `pointerout` without `relatedTarget`). A submenu
is only ever opened by an explicit gesture (click, pinch, keyboard), so it is
**pinned**: hovering another category neither closes it nor moves the
highlight, and the pointer (or the hand) leaving the wheel does not close it.
It goes away on a click on another category, a click outside, `Esc`, or an
explicit close. A click on the submenu's
glass between rows stays inside the wheel. Closing never touches domain
state. Focus is never left on a hidden element: if it was inside the wheel,
it returns to the anchor.

**Keyboard.** One tab stop (roving `tabindex` on the categories), `ArrowUp` /
`ArrowLeft` previous, `ArrowDown` next (wrapping), `ArrowRight` opens the
focused category's tree (focus on its first row), `Home` / `End`. A
screen-reader description on every category names the keys.

**Responsive.** `--tw-scale` (module sheet) scales the whole wheel, submenu
included: `.86` at `max-height:620px`, `.76` at `max-height:520px`, `.84` at
`max-width:560px`; the widest submenu reaches 514 px from the edge before
scaling. While a submenu is open the screenshot preview (`#screenshotPreview`,
38) is hidden (`visibility`) so it never covers a row; it comes back when the
submenu closes.

**Motion.** The half-disc slides 32 px out of the edge and fades in over
`--shell-dur`; the submenu slides 12 px out of the band and fades in over
`--shell-dur`; highlights change over `--shell-dur-fast`. Under
`prefers-reduced-motion: reduce` every duration is 0 ms (the submenu
animation is removed) and nothing waits for a transition end.
`forced-colors` maps glass to `Canvas`, strokes, icons and labels to
`CanvasText`, the highlighted sector, its arc, the submenu link and the
focused row to `Highlight`.

**Accessible names.** Categories carry `aria-label` (label, then projected
state) but **no** `title`; their visible label is `aria-hidden` (the name
already says it). The checked mark of a `menuitemradio` /
`menuitemcheckbox` row is drawn with `content:"" / ""`, so it never enters
the accessible name.

**Journal.** `[tool_wheel] <key> {json}`: `tool_wheel.installed`,
`.registered`, `.menu_failed`, `.open {reason: mouse|barehands|keyboard|api}`,
`.close {reason: leave|activate|escape|outside|blur|api|exclusive}`,
`.hover_blocked`, `.yield`, `.exclusive_announce_failed`, `.activate`,
`.secondary`, `.secondary_none`, `.item`, `.item_inert`, `.item_secondary`,
`.item_secondary_none`, `.status`, `.unbound`, `.action_failed`,
`.refreshed`, `.refresh_failed`, `.install_failed`, `.hover_ignored
{reason: pointer_still}`.

**A motionless pointer never takes the keyboard focus** (Slice 08). After a
key on the wheel, the wheel or a tree is drawn under a mouse that has not
moved, and Chrome sends a trusted `pointerover` without any `pointermove` on
what appears under it; the focus used to land there (ArrowRight on Capture
focused the row under the pointer). Such a hover is ignored
(`tool_wheel.hover_ignored`) until the first real `pointermove`, which then
gives the hover of the target under the pointer. Bare Hands' synthetic
pointer is not concerned (its events are not trusted). Test:
`test_tool_wheel_browser.py::test_a_motionless_pointer_never_takes_the_keyboard_focus`.

**Tests.** `tests/unit/test_tool_wheel_js.py` (node: five categories and
order, placeholders, geometry of the band and of the curved submenu, reducer,
one tree at a time, item `menu` / `ArrowRight`, exclusive surfaces, no
network, served page); `tests/unit/test_tool_wheel_browser.py` (headless
Chrome via CDP, real input events: mouse hotspot, keyboard, Bare Hands
synthetic pointer 9001, pinch on the anchor, late thumb + middle pinch, `Esc`
with outside focus, `Space`, reduced motion, focus, far pointer, the real
trees switched JARVIS → Capture → Dossier, wheel / Board panel exclusivity).
Capture tree, target lists and `#recIndicators`:
`tests/unit/test_capture_wheel_browser.py` (real Control Center and Core,
fake capture sources).

### Exclusive surfaces (wheel and Board panel)

The open wheel (37) and the Board panel `#boardsPanel` (39, bottom-left) are
**never open together** (Slice 03 of `jarvis-board-ui-wheel-dossier-refactor`;
before, the panel covered sectors of an open wheel and one `Esc` closed both):

- opening one closes the other. Each announces its opening and closing on
  `document` with the event `JarvisShell.EXCLUSIVE_EVENT`
  (`jarvis:shell-exclusive`, `detail: {id: 'tool-wheel'|'board-panel', open}`;
  `JarvisShell.EXCLUSIVE_SURFACES`) and closes itself when another opens
  (`tool_wheel.yield`, `boards.panel_yield`), without taking the focus back
  (it belongs to the surface that opened). The modules keep an identical
  fallback copy of the event name (tested);
- with the mouse, the `pointerdown` outside already closes the other surface
  first; the event covers the keyboard, Bare Hands and API paths
  (`JarvisToolWheel.open()`, `JarvisBoardsControl.open()`);
- hovering the wheel anchor does **not** open the wheel while the Board panel
  is open (`tool_wheel.hover_blocked`): moving the pointer along the left
  edge never takes the panel away. An explicit activation (click, pinch,
  `Enter` / `Space` / `ArrowRight`) opens the wheel and closes the panel;
- so one `Esc` only ever closes the one surface that is open.

Tests: `test_tool_wheel_js.py::test_exclusive_surface_blocks_hover_reveal_and_closes_an_open_wheel`,
`::test_exclusive_event_name_matches_the_shell`,
`test_tool_wheel_browser.py::test_wheel_and_board_panel_are_never_open_together`.

### Selection actions (Slice 06)

The Sélection tree shows, after the method rows, the actions on the page's
selection: contract and table in [scene-selection-batch.md](scene-selection-batch.md)
› *Selection actions (wheel)*. Shell rules: rows hidden when they make no sense
(empty selection: a status row and the hidden count only); a row that cannot
act now stays visible, `aria-disabled`, with its reason as name and tooltip
(Ranger on a Board that is not displayed, beyond 20 objects, nothing rangeable;
Retirer du Board during a Variantes run); status rows never close the wheel;
the open submenu follows selection, preview and hidden count through
`JarvisToolWheel.refresh('selection')`. Reaching the wheel (`#toolWheel`), by
mouse or by the Bare Hands pointer, never clears the selection. At most eight
rows with a selection (the arc holds nine): forms and the hidden list are second
levels. Retirer du Board is the only confirmed action (page `confirmDialog`);
there is no durable delete in the wheel.

## Dossier full-screen view (`#dossierView`)

Handoff `jarvis-board-ui-wheel-dossier-refactor`, Slice 07. Contract of the
content and of the agent channel: [dossier.md](dossier.md) › *Full-screen
Dossier (UI)*. Modules: `control_center_dossier_core.js` (pure, node tests
`test_dossier_core_js.py`) then `control_center_dossier.js` (view, Chrome tests
`test_dossier_fullscreen_browser.py`), inserted after the wheel they register on.

- **Layer.** `#dossierView` (`.dsr`) is a page layer at **55**, one of the
  full-screen launcher views: above every control, below `.overlay`, toasts,
  context menu and the page confirmation (85). Variantes (`#jvStudioExplorer`,
  9000) covers it: the Dossier refuses to open while Variantes is open or a run
  is shown (`html.jvx-run`), from the wheel (disabled row with the reason) and
  from Jarvis (receipt `refused dossier_unavailable`). If Variantes opens over
  an open Dossier, the Dossier stays underneath, unchanged, and its Escape
  handler stands aside while the Studio covers it. The permanent-delete
  confirmation is drawn **inside** the Dossier, never in a layer the Studio could
  hide, and is disabled during a run.
- **Opening.** Wheel › Dossier, `JarvisDossier.open()` (the displayed Board),
  `JarvisDossier.openBoard(id)` (a precise Board, e.g. an archived row of the
  Board panel), `JarvisDossier.openEntry({entry_id})` (Ranger toast), Jarvis's
  `open_entry`. Opening closes the wheel, makes the rest of the page `inert`
  (except toasts, Variantes, the page confirmation, the Bare Hands pointer and
  the fullscreen prompt) and puts focus in the view.
- **Board switch.** A Dossier opened on the displayed Board **follows** it: on a
  switch it is rebound (tabs closed, list re-read, generation counter drops any
  answer of the old Board) and says so in its notice line; the header title is
  the one the list answer carries, so Board A's title never sits on Board B's
  content. A Dossier opened on a precise Board (`openBoard`, archived) does not
  move. A switch while an edit is unsaved holds the Dossier on the old Board
  (said, Afficher sur le Board off) until it is closed.
- **Layout.** ≥ 1280 px: organisation 264 px (232 under 1280), centre, context
  300 px docked (open by default from 1500 px). Under 1280 px the context is a
  drawer over the centre. Under 900 px the organisation becomes a drawer too
  (« Organisation » button), header labels shrink to icons with names. Two
  documents side by side only when the centre keeps 960 px; otherwise the second
  stays a tab. No horizontal page scroll at 600 px.
- **Accessibility.** `role="dialog"`, `aria-modal`, labelled by its title line
  (« Dossier », Board type, Board title), described by a hidden help line. Tab
  cycles inside the view; tabs are a `tablist` (arrows, `Home`, `End`); menus
  are `role="menu"` (arrows, focus on the first item). **Escape** closes, in
  order: an open menu, the delete confirmation, the move form, the editor (an
  unsaved edit asks « Abandonner vos modifications ? », focus on « Continuer à
  modifier »), a drawer, then the Dossier. Closing returns focus to the element
  that opened it, else to the wheel anchor. Every waiting state shows its label
  and a seconds counter in the status line; a disabled action keeps its reason as
  tooltip and says it in the notice line when activated. Reduced motion: no
  transitions. Forced colours: borders follow `CanvasText`.
- **Journal** (`[dossier]` console lines): `dossier.installed`, `opened`,
  `closed`, `list_read`, `doc_read`, `save`, `move`, `delete`, `present`,
  `search`, `rebound`, `rebind_held`, `stale_list_dropped`,
  `navigation_answered`, `navigation_receipt_failed`, `navigation_poll_failed`,
  `open_refused`, `wheel_open` — entry kinds and codes, never a title.

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

**Wheel visible = Selection owns the column.** While `#toolWheel` is not
`hidden` (by default since Slice 04), the HUD sheet hides the top-left
lifecycle control (`#barehandsHud`) and the tool strip (`#barehandsPalette`)
with `body:has(#toolWheel:not([hidden]))`; wheel hidden or not installed,
both come back (rollback).
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
- **open Bare Hands flows are exempt**: while `JarvisBarehands.openFlow()`
  names a flow (`calibration`, `benchmark` — the `#jarvisFlow` overlay, the
  same guard that refuses a second flow and that an explicit sleep closes,
  `SLEEP_ENDS_FLOW`), no pointer event takes over; those flows are driven by
  mouse clicks by design, and a takeover would turn Bare Hands off under an
  overlay left open. Journal `input_arbitration.flow_exempt` /
  `.flow_closed`, counter `stats().flowExempt`; once the flow closes, the
  next deliberate event takes over again;
- one transition per episode (`pending` until the lifecycle changes),
  accumulator reset; a takeover the gate does not apply (`selectMethod`
  busy with a choice in flight, or refused) reopens the episode
  (`{type:'takeover_refused'}`, journal `input_arbitration.takeover_rearmed`,
  `stats().refusedTakeovers`) so the next deliberate event retries;
  `cooldownMs` after every entry into `active` (explicit
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
- **Full-screen views** (`.wsp`, `#dossierView`…): focus trapped inside while open, the rest of the page `inert`, focus restored to the opener on close ([Dossier full-screen view](#dossier-full-screen-view-dossierview)).
- **Keyboard**: one tab stop per group (roving tabindex), arrows inside the
  group, `Home`/`End`, `Enter`/`Space` on native buttons, `Esc` closes the
  topmost transient surface. Secondary activation is the existing channel:
  `contextmenu` (mouse right-click, Bare Hands thumb + middle pinch),
  `ContextMenu` key, `Shift+F10`. Never long press.
- **Announcements**: one polite live region per module; urgent only for what
  the user must act on now.
- **Scene selection by keyboard** (Slice 06): focus an object (Tab, arrows),
  `Ctrl+Espace` starts a keyboard selection with it and then adds or removes
  the focused object; arrows move the focus without dissolving the selection;
  `Esc` on the object ends it. The wheel (anchor, `Enter`, `ArrowDown` to
  Sélection, `Enter`) then acts on that selection, like the mouse
  (click, `Ctrl`+click, rectangle) and the Bare Hands pointer.
- **Target size**: at least `--shell-wedge-min` (48 px) for wheel wedges,
  32 px for status-centre buttons, the launcher's 34 px for launcher buttons.
- **Reduced motion**: under `prefers-reduced-motion: reduce` the shell
  durations are `0ms`; surfaces change state without travel.
- **Forced colours**: under `forced-colors: active` control borders use
  `CanvasText` and the focus ring `Highlight`.
- **Zoom**: usable at 200 % (the narrow breakpoints apply).
- **Label in name** (WCAG 2.5.3, checked by axe-core): the accessible name
  starts with, or contains, the words the control shows — « Assistant Jarvis :
  Board actif … » (the Board card: type, then title), the circuit-board launcher codes
  (`Trace · TRC`, completed by the launcher after every module that rewrites
  `aria-label`). A text eyebrow ends with a space (the card's type) so the
  visible text reads as two words; a wheel item's note follows its text after
  a space. A recording chip's name starts with the word it shows (« REC —
  arrêter l’enregistrement d’écran (écran 2) »); a busy target's long phrase
  starts with its note (« en cours d’enregistrement sur cette cible »); a
  Board row in the chooser takes its name from its content (title, state,
  kind, last opened) and says its action in `aria-description` (« Basculer
  sur ce Board », « Board actif »), its ticking wait `aria-hidden`. Two
  written exceptions, `label-content-name-mismatch` only: a recording chip
  (its ticking duration, which a name never carries — everything else it
  shows is in the name, checked word by word) and a rail card (its name is
  the title then the state in words; the engine badge, variant count and age
  are visible extras). axe runs in both themes on the wheel (closed, open,
  sub-arc), status centre with two recordings,
  launcher, rail, Board card and chooser (`#boardsPanel`), a rail card
  menu (`.jvr-menu`), the alert popover, `#chatTab` and the screenshot
  preview; it finds nothing else.
- **Menus and listboxes** hold only their entries in the accessibility tree:
  a rail card's « ⋯ » button is
  `aria-hidden` (mouse and hand only; the option itself opens the same menu
  with `ContextMenu` / `Shift+F10` / right click).
- All French UI strings address the user as « vous ».

## Integration matrix (Slice 09)

`tests/unit/test_control_center_shell_browser.py` replays the runtime matrix of
the handoff (`docs/04-testing-and-quality.md`) on the served page with the
`fetch` double of `_status_centre_browser.mjs`, in both themes, one screenshot
per state (`JARVIS_S09_EVIDENCE_DIR`): 1 Board, wheel closed; 2 wheel open,
Selection focused (opened by keyboard on JARVIS, one `ArrowDown`, since the
five-category wheel of the wheel/dossier refactor Slice 03); 3 Selection ›
Souris / Bare Hands; 4 audio recording;
5 screen recording (4-5: indicators top-left since the wheel/dossier refactor Slice 04); 6 screenshot preview (taken through the wheel: Capture,
then its « Capture d’écran » row); 7 alert
popover; 8 rail with every card state and the Board-linked items; 9 Variantes
+ rail (real isolated Core, `tests/fakes/explorer_browser.py`); 10 Board card
with Voice's presence refused (was the mode chooser until the wheel/dossier
refactor Slice 02); 11 Board chooser; 12 800×600; 13 1280×540 with the wheel open;
14 reduced motion; 15 200 % zoom (720×450 CSS px at scale 2); 16-19 the real
Bare Hands badge (« MAINS · ACTIF », text and rules read from
`control_center_barehands.js`) + frozen-scene note (two lines above 700 px) +
Core lost + fresh screenshot at 1440, 1280, 900 and 600 px. Every state is audited the same way: no control over
another (the side panel over the rail and the banner over a panel are the
registry's), every interactive target of every control hit-testable at its
centre (or under the state's own surface), no unnamed control, no clipped
text without its full text in a `title` / name, no control off-screen, no
horizontal scroll, the state's surface whole and on top. Next to it: keyboard
only and mouse only full paths, reduced motion (nothing in the shell animates
or transitions), forced colours, axe-core (`JARVIS_AXE_JS`), 200 % zoom,
700 px wide / 560 px high, the GPT-Live banner + drop tray + toasts + rail
stack at four sizes with a panel closed and open (and again with every
`anchor()` declaration removed, for the fallbacks), and a real held object
dragged into `#chatTab`, the Board card and the rail (it stops against each).

## Validation

- `tests/unit/test_control_center_shell_layers.py`: registry against the real
  sheets, Cosmos without geometry or rank, controls marked, tokens once,
  reduced motion, mirror comment, shared selector read by scene and rail.
- `tests/unit/test_scene_renderer_logic.py::test_the_scene_layer_sits_above_the_face_and_below_every_control`:
  the scene's own rank relations.
- Runtime: both themes at 1440×900, 1280×720, 900×600 and 600×800 in headless
  Chrome on an isolated instance (no control overlapping another, scene
  objects stop against every control including `#chatTab`,
  `#boardsHud` and `#presentationRail`).
