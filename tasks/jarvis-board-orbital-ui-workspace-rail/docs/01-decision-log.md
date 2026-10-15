# 01 - Decision log

## Locked product decisions

### D01 - Wheel is retractable
Only an edge anchor remains visible at rest. Mouse edge approach and Bare Hands leftward gesture reveal the wheel.

### D02 - Wheel activation supports Mouse and Bare Hands
Mouse uses hover + click. Bare Hands uses point/hover + the existing click/pinch activation gesture.

### D03 - Wheel is contextual
Do not make the wheel a generic all-settings menu. Global controls remain in dedicated surfaces.

### D04 - Initial wheel tool set is intentionally small
Initial direct items: `Selection`, `Video`, `Screenshot`, `Audio`. No speculative filler items.

### D05 - Selection has exactly two methods
`Mouse` and `Bare Hands`. Other current selection choices on this selector are removed.

### D06 - Bare Hands selector icon must be redesigned
The current hand icon is explicitly rejected by the user.

### D07 - Mouse takeover is automatic on deliberate Mouse use
Explicit click always activates Mouse. Meaningful movement also can, with jitter filtering. Return to Bare Hands is explicit only.

### D08 - Capture interaction model is hybrid
Direct/simple activation uses the default behavior immediately; long/secondary activation opens supported options.

### D09 - Audio is toggle recording
Start on first activation, stop on second, duration visible while active, source chooser on secondary activation.

### D10 - Video is toggle recording
Start on first activation, stop on second, persistent `REC + duration`, target chooser on secondary activation.

### D11 - Screenshot is immediate + non-blocking preview
Save immediately, show temporary preview, actions: open / annotate / send to Jarvis / delete.

### D12 - Right rail is active-workspace context
Not a general library. Show context-linked/active documents, presentations, media and artifacts.

### D13 - Right rail requires rich recognition
Use real previews where available plus type identity. Typed placeholder is acceptable when no preview exists; fake preview is not.

### D14 - Requested status semantics
Blue = active work, green = ready/done, yellow = changed/new to review. Existing backend error/problem remains separately represented.

### D15 - Bottom-center F9 capsule is removed
Its visual slot becomes the notification/status center. This does not automatically remove the F9 keyboard capability.

### D16 - Hidden-object count capsule is removed
Replace with one eye/eye-off toggle.

### D17 - Bottom-left context control stays
Interaction mode stays in bottom-left. Board access remains available in/next to the same context zone if feasible without duplicating canonical state.

### D18 - Central Board remains hero
Peripheral controls should consume less visual area and visual contrast than the Board.

## Architecture decisions inherited from current Jarvis

### A01 - Capture status truth remains in Core
`docs/capture.md` explicitly defines `CaptureService` as the owner. New UI must project `/api/captures/status`, not invent local recording truth.

### A02 - Interaction mode truth remains canonical
`control_center_interaction_mode.js` reads `/api/status` and writes through `/api/interaction-mode`, then re-reads. Preserve no-optimism behavior.

### A03 - Bare Hands lifecycle remains canonical
`control_center_barehands_hud.js` is already a projection of the lifecycle seam. The selection-method UI may request transitions but cannot own lifecycle.

### A04 - Presentation/work data stays server-backed
`control_center_presentation_rail.js` already reads its server-backed rail model. The visual redesign must not turn it into local-only state.

### A05 - Z-index is a contract
`control_center.html` has a deliberate z-index registry and tests. The visual refactor must update this model deliberately and verify overlays.

## Decisions left open for implementation after audit

### O01 - Movement threshold for Mouse takeover
Do not lock an arbitrary pixel count in planning. Implement an explicit threshold/window/hysteresis model, test it, then tune using runtime observation.

### O02 - Secondary gesture mapping
Prefer existing gesture vocabulary. PM/implementer must inspect Bare Hands contracts before deciding whether secondary activation is pinch-and-hold, dwell+pinch, or another existing action.

### O03 - Default capture target
Preserve current default unless product evidence says otherwise.

### O04 - Fourth bottom-center status category
Only use a canonical existing category. Three required categories are alert, completed, pending question.

### O05 - Workspace preview providers
A staged preview pipeline may be needed. Initial release can support real preview for presentations/images/video where data exists and typed fallback elsewhere.

### O06 - Board control exact composition
The user wants bottom-left as the mode/Board context zone. Whether this is one composite button or two colocated controls is an implementation choice constrained by existing Board APIs and accessibility.
