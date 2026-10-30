# 01 - Decision Log

## Locked decisions

### D01 - Mouse and keyboard are first-class

Voice and Bare Hands remain optional accelerators. Every interaction in this feature must be usable without them.

### D02 - Context click preserves an existing multi-selection

Right-clicking a member of the current selection keeps the selection. Right-clicking an unselected object may replace the selection with that object before opening its menu.

### D03 - Resize is 8-way

Resizable scene windows/capsules expose four edge hit regions and four corner hit regions. Visual border thickness is independent from pointer hit thickness.

### D04 - Shift locks aspect ratio

The ratio is captured at resize start. Shift can be pressed/released during the gesture without causing a jump; the implementation rebases as necessary.

### D05 - Organization is atomic

Row, column, grid, alignment, distribution and same-size actions apply as one all-or-nothing scene change. Do not send one geometry command per item.

### D06 - Layout ordering is deterministic

Use current visual spatial order, with a stable tie-break. Custom grid fills row-major unless the PM finds an already-canonical ordering helper that should be reused.

### D07 - Organization stays near the selection

Layout actions preserve the selection's general location (centroid / bounding region) and clamp as a group to the usable viewport where possible. They do not teleport the group to a global origin.

### D08 - Undo is local and bounded

Ctrl/Cmd+Z covers user geometry organization/resize operations from this feature. It is page/session-local, bounded and not a new durable history system. Undo must refuse or invalidate an entry when target objects no longer match the state produced by that entry rather than overwriting newer work.

Redo is not required by this task.

### D09 - Viewer is an in-app overlay

The viewer covers the Control Center viewport with a dark/blurred backdrop. It is not `Element.requestFullscreen()` and must not change the existing fullscreen state machine.

### D10 - Viewer opening does not mutate Board geometry

Opening, changing viewer layout and closing do not write scene geometry. The user returns to the same Board arrangement.

### D11 - Multi-view is compatible-content oriented

A double-click on a viewable member of a compatible multi-selection opens the compatible selected set. Agents are not mixed into document/image comparison layouts in V1.

For a mixed Enter selection, the integration Slice must use a deterministic rule and accessible notice rather than silently producing an incoherent mixed renderer. Preferred default: open the compatible media/document subset and report skipped incompatible objects.

### D12 - Viewer layouts are transient

No persistent saved viewer workspace, composite artifact or contact-sheet export in this task.

### D13 - Agent viewer uses public state only

Mission History, Work State, actual child work and explicit public summaries are allowed. Raw provider traces, hidden reasoning, chain-of-thought and invented future steps are forbidden.

### D14 - Missing plan data degrades honestly

If no structured public plan/steps exist, show actual work children / completed facts and a neutral `No published plan` state. Do not fabricate a to-do list from model inference.

### D15 - Stop and Ask reuse canonical paths

Stop uses existing cancellation semantics. Ask uses an existing agent communication route when one is truly supported; otherwise route/prefill through the main chat with explicit target context. No second agent control plane.

### D16 - Representation redesign stays out

Point/capsule/window representation UX is a later feature. This handoff only changes the manipulation and inspection behavior needed for the scoped feature.

