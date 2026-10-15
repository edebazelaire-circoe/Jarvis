# 02 - Architecture and integration constraints

## Principle: recompose UI, do not duplicate owners

This task crosses several mature Jarvis domains. The key architectural requirement is to create a shared visual shell without creating shared local state that competes with Core.

### Canonical owners

| Concern | Canonical owner / evidence | UI responsibility |
| --- | --- | --- |
| Bare Hands lifecycle | existing Bare Hands controller + lifecycle seam | request transitions, project state |
| selection-method presentation | new UI policy layered on canonical Mouse/Bare Hands state | show active method and arbitrate input intent |
| interaction mode SIMPLE/PRESENTATION/REUNION | Core status + interaction-mode route | bottom-left projection and request |
| capture lifetime | `CaptureService` in Core | start/stop/capture requests + status projection |
| artifacts/media evidence | `ArtifactService` / registry | preview/open/delete through supported routes |
| presentation rail data | presentation rail API/Core work model | render cards, actions, visibility |
| Board identity | Board/session workspace services | show/switch Board through existing API |
| scene visibility/hidden objects | scene interaction contract | eye toggle only |
| notification categories/unread | existing notification/background-pill source | relocate and re-render |

## Proposed UI composition

### 1. `OrbitalToolWheel`

Prefer a new focused module rather than continuing to grow the current Bare Hands HUD file. It can be composed into `control_center.html` and depend on narrow adapters/seams for:

- wheel open/close;
- pointer position and keyboard navigation;
- Bare Hands directional activation event;
- selected action;
- secondary activation;
- accessible labels and focus.

The module should not know how Core stores captures or how Bare Hands is implemented internally.

Suggested split (names provisional and must be revalidated by PM):

- `control_center_tool_wheel.js`: rendering, geometry, keyboard, pointer and interaction state;
- `control_center_input_arbitration.js`: deliberate Mouse takeover policy, pure decision function + integration seam;
- capture adapter may remain in/refactor from `control_center_capture_rail.js` so canonical polling logic is reused rather than rewritten;
- `control_center_barehands_hud.js` remains lifecycle/diagnostic owner, but direct work-tool presentation moves out of its permanent strip.

### 2. Input arbitration state machine

Conceptual states:

```text
CONTROL_BARE_HANDS
  -- mouse click ----------------------------> CONTROL_MOUSE
  -- deliberate mouse movement --------------> CONTROL_MOUSE
  -- jitter/noise ----------------------------> CONTROL_BARE_HANDS

CONTROL_MOUSE
  -- explicit wheel choice Bare Hands -------> request canonical BH activation
  -- Jarvis verbal request -------------------> request canonical BH activation
  -- incidental camera hand presence --------> CONTROL_MOUSE (no auto switch)
```

The wheel's `Selection` item reflects the canonical/effective control method. Do not equate Bare Hands lifecycle `sleep` with Mouse control unless the product contract says so after audit; the arbitration policy may need a small canonical/effective mapping layer.

Mouse movement detection should be a pure/tunable decision component:

- ignore synthetic/programmatic pointer events if distinguishable;
- ignore movement during immediate pointer warp/recenter if current code has such behavior;
- accumulate displacement or velocity over a bounded time window;
- only transition once per takeover event;
- reset accumulator after transition;
- explicit click bypasses threshold;
- expose metrics/log reason (`click`, `movement`) for QA, without logging sensitive content.

### 3. Capture wheel adapter

Existing `control_center_capture_rail.js` is architecturally valuable:

- no optimistic capture state;
- polling `/api/captures/status`;
- duration from Core timestamps;
- post-write status refresh;
- unknown state on polling loss;
- stop remains available when privacy requires it;
- independent audio and screen continuous captures.

Refactor/migrate that logic into a reusable controller/view model that can drive wheel buttons and persistent indicators. Avoid a second polling loop if one existing controller can publish a view model.

Action mapping should preserve the Core model described by `docs/capture.md`:

- Audio continuous => audio recording;
- Video continuous => current screen recording family;
- Screenshot => screen one-shot.

Secondary target/source choice must be capability-driven. If current API only supports `desktop/default`, the menu must say only that, or be omitted until another target exists.

### 4. Screenshot preview pipeline

After a successful one-shot capture, the UI has an artifact/capture identity. The preview component should:

- request/display the actual payload through the supported local UI route;
- appear non-modally near a low-conflict corner/bottom zone;
- auto-dismiss on a short timeout unless focused/hovered;
- expose quick actions;
- never mark capture failed merely because preview rendering failed.

`Open` and `Delete` can map to existing artifact routes if present. `Send to Jarvis` must use the canonical conversation/artifact attachment path available at HEAD. `Annotate` may need a new editing surface; if no annotation capability exists, Slice 05 must either implement a minimal real annotation flow or explicitly gate the action until it does. Do not render a dead button.

### 5. Bottom status center

The existing `.bgpills` model should be separated into:

- a data/category model (counts, severity, unseen items, popup content);
- a presentation component rendered horizontally at bottom center.

This avoids losing existing unread semantics while changing location/appearance.

The old `#voiceHint` visual element can be removed/reused, but voice keyboard handling must be audited separately. Do not delete key bindings just because the label moves.

Persistent recording indicators should be adjacent but not mixed into unread-count semantics.

### 6. Hidden-object eye toggle

The eye control is a thin adapter over current scene hidden-object visibility. It should have:

- `aria-pressed` / clear accessible label;
- eye = hidden objects visible or hidden, with wording confirmed in implementation so icon semantics are not ambiguous;
- no numeric capsule;
- optional tooltip with count if the count is useful, but count must not become permanent chrome again.

### 7. Active workspace rail

The current presentation rail is specialized. The user now wants a broader visual concept. Implement in stages without lying about data.

**Stage A:** rebuild the existing presentation rail visually and move it to the right, preserving all canonical actions/data. Add real presentation thumbnails if an existing render/still is available; otherwise typed presentation placeholder.

**Stage B:** introduce a workspace-item adapter that can also surface Board-linked image/video/document artifacts where canonical APIs support them. Do not make a second registry.

Recommended UI model:

```text
WorkspaceRailItem {
  id
  source_kind / artifact_kind
  title
  media_type
  preview { kind: image|video|slide|placeholder, url/ref }
  activity_state: working|ready|changed|problem|unknown
  updated_at?
  primary_action
  context_actions[]
  source_scope
}
```

This is a **view model**, not storage. Every item retains its canonical identity/source.

### Status mapping

User language:
- `working` -> blue;
- `ready/done` -> green;
- `changed/unreviewed` -> yellow;
- canonical `problem/error` -> explicit orange/red exceptional treatment;
- unknown/unavailable -> muted/dashed, not falsely green.

If the backend does not yet expose `changed/unreviewed`, add that concept only with a defined owner and persistence/event semantics. Do not infer "changed" from local polling timestamps in a way that resets on reload.

### 8. Top/bottom-left chrome

The final shell should preserve:

- bottom-left interaction mode as a primary context indicator;
- Board selection in the same visual context zone or an adjacent minimal control;
- compact top-right global tools only where they remain truly global;
- access to diagnostics/Settings/Test Lab/Timeline/MCP/Workspace/Studio, even if their permanent 52px vertical dock buttons disappear.

A good outcome may move less-frequent global tools into one compact launcher rather than delete them. The exact information architecture should be validated against usage and shortcuts in Slice 08.

## Layering / z-index

`control_center.html` currently documents many explicit layers: scene, topbar, Bare Hands palette, capture rail, dock, interaction-mode chooser, Board panel, notifications, popovers, context menus, Bare Hands cards, confirmations, Studio/Variantes/presentation rail, full-screen tools and settings.

The redesign must produce a new explicit layer registry and tests for at least:

- wheel anchor + expanded wheel;
- wheel submenu/secondary options;
- persistent recording indicator;
- bottom notification center and its popover;
- right workspace rail and context menu;
- Studio/Variantes overlays;
- interaction mode chooser;
- Board chooser;
- screenshot preview;
- confirmations/modals.

Never fix overlap bugs with arbitrary `99999` z-index values.

## Accessibility equivalence

Every Bare Hands-only interaction needs an equivalent Mouse/keyboard path:

- wheel: keyboard focus and arrow/roving navigation plus Enter/Space;
- secondary activation: keyboard-accessible menu action;
- selection methods: radio/menu semantics with current state;
- status counters: buttons with category + count announced;
- workspace cards: focusable primary action, menu via keyboard;
- recording states: live status text, not color alone;
- status dots: text/aria description accompanies color.

## Security/privacy

- No preview route should expose arbitrary filesystem paths.
- No artifact payload is copied into client-side persistent storage merely for thumbnailing.
- Ongoing capture must always offer a clear stop route even if status polling is degraded, following current capture-rail policy.
- Do not surface private agent traces or raw prompt/debug details in user-facing status counters.
